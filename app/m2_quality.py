"""Versioned structural, source-binding, and cross-artifact checks for M2."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.database import (
    DBArtifact,
    DBArtifactVersion,
    DBClaimCheck,
    DBGenerationTask,
    DBQualityCheck,
    DBSourceDocument,
    DBSourceRef,
    DBTaskStep,
)
from app.m2_artifacts import validate_artifact_scope
from app.m2_contracts import (
    GenerationContext,
    LabGuideArtifact,
    LessonArtifact,
    M2Artifact,
    M2Capability,
    StrictModel,
    TieredQuizArtifact,
    validate_m2_artifact,
)
from app.m2_tasks import (
    M2_GOLDEN_CAPABILITY,
    complete_task_step,
    fail_task_step,
    schedule_rework_step,
)


SCHEMA_CHECKER_VERSION = "m2.schema.v1"
SOURCE_CHECKER_VERSION = "m2.source_binding.v1"
CONSISTENCY_CHECKER_VERSION = "m2.cross_binding.v1"

ARTIFACT_CAPABILITY = {
    "lesson": M2Capability.LESSON,
    "lab_guide": M2Capability.LAB_GUIDE,
    "tiered_quiz": M2Capability.TIERED_QUIZ,
}
ARTIFACT_SEQUENCE = {"lesson": 1, "lab_guide": 2, "tiered_quiz": 3}


class M2BundleQualityResult(StrictModel):
    passed: bool
    failed_artifact_types: list[str]
    quality_check_ids: list[str]
    claim_check_ids: list[str]
    checker_versions: dict[str, str]


class M2QualityError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _quality_check(
    session: Any,
    *,
    version: DBArtifactVersion,
    trace_id: str,
    check_type: str,
    checker_version: str,
    passed: bool,
    details: dict[str, Any],
    source_ref_ids: list[str],
) -> DBQualityCheck:
    existing = session.query(DBQualityCheck).filter_by(
        artifact_version_id=version.id,
        check_type=check_type,
        checker_version=checker_version,
    ).first()
    if existing is not None:
        return existing
    row = DBQualityCheck(
        artifact_version_id=version.id,
        trace_id=trace_id,
        check_type=check_type,
        checker_version=checker_version,
        status="passed" if passed else "failed",
        score=1.0 if passed else 0.0,
        details=details,
        source_ref_ids=source_ref_ids,
    )
    session.add(row)
    session.flush()
    return row


def _artifact_source_ids(artifact: M2Artifact) -> list[str]:
    source_ids: list[str] = []
    if isinstance(artifact, LessonArtifact):
        for section in artifact.sections:
            source_ids.extend(section.source_ref_ids)
    elif isinstance(artifact, LabGuideArtifact):
        for step in artifact.steps:
            source_ids.extend(step.source_ref_ids)
    elif isinstance(artifact, TieredQuizArtifact):
        for tier in artifact.tiers:
            for question in tier.questions:
                source_ids.extend(question.source_ref_ids)
    return list(dict.fromkeys(source_ids))


def _claim_checks(
    session: Any,
    *,
    artifact: M2Artifact,
    version: DBArtifactVersion,
    trace_id: str,
    source_ref_ids: list[str],
) -> list[DBClaimCheck]:
    rows = []
    for source_ref_id in source_ref_ids:
        atomic_claim = f"{artifact.artifact_type} structured unit binds source_ref={source_ref_id}"
        existing = session.query(DBClaimCheck).filter_by(
            artifact_version_id=version.id,
            source_ref_id=source_ref_id,
            atomic_claim=atomic_claim,
        ).first()
        if existing is None:
            existing = DBClaimCheck(
                artifact_version_id=version.id,
                trace_id=trace_id,
                atomic_claim=atomic_claim,
                source_ref_id=source_ref_id,
                support_status="source_resolved",
                verdict="structural_keep",
                rationale=(
                    "The source exists, is ready, and belongs to the verified course. "
                    "This check does not claim semantic truth support."
                ),
            )
            session.add(existing)
            session.flush()
        rows.append(existing)
    return rows


def run_m2_quality_checks(
    session: Any,
    *,
    task_id: str,
    context: GenerationContext,
) -> M2BundleQualityResult:
    task = session.query(DBGenerationTask).filter_by(id=task_id).first()
    if (
        task is None
        or task.capability != M2_GOLDEN_CAPABILITY
        or task.owner_public_id != context.owner_public_id
        or task.course_id != context.course_id
        or task.status != "running"
    ):
        raise M2QualityError("task_not_reviewable", "running M2 task does not match quality context")
    quality_step = (
        session.query(DBTaskStep)
        .filter_by(task_id=task.id, sequence=4)
        .order_by(DBTaskStep.attempt.desc())
        .first()
    )
    if quality_step is None or quality_step.status not in {"running", "completed"}:
        raise M2QualityError("quality_step_not_running", "quality step must be started before checks run")

    artifacts = session.query(DBArtifact).filter(
        DBArtifact.creating_task_id == task.id,
        DBArtifact.artifact_type.in_(ARTIFACT_CAPABILITY),
    ).all()
    by_type = {artifact.artifact_type: artifact for artifact in artifacts}
    if set(by_type) != set(ARTIFACT_CAPABILITY):
        raise M2QualityError("artifact_set_incomplete", "quality checks require exactly three M2 artifacts")

    check_rows: list[DBQualityCheck] = []
    claim_rows: list[DBClaimCheck] = []
    failed_types: set[str] = set()
    parsed: dict[str, M2Artifact] = {}
    versions: dict[str, DBArtifactVersion] = {}

    for artifact_type, capability in ARTIFACT_CAPABILITY.items():
        artifact_row = by_type[artifact_type]
        version = session.query(DBArtifactVersion).filter_by(id=artifact_row.current_version_id).one()
        versions[artifact_type] = version
        schema_errors: list[str] = []
        parsed_artifact: M2Artifact | None = None
        try:
            if hashlib.sha256(version.content.encode("utf-8")).hexdigest() != version.content_hash:
                schema_errors.append("content_hash_mismatch")
            parsed_artifact = validate_m2_artifact(capability, json.loads(version.content))
        except Exception as exc:
            schema_errors.append(f"schema_invalid:{type(exc).__name__}")
        schema_passed = not schema_errors and parsed_artifact is not None
        check_rows.append(
            _quality_check(
                session,
                version=version,
                trace_id=task.trace_id,
                check_type="schema",
                checker_version=SCHEMA_CHECKER_VERSION,
                passed=schema_passed,
                details={"errors": schema_errors, "metric": "structure_pass_rate"},
                source_ref_ids=[],
            )
        )
        if not schema_passed:
            failed_types.add(artifact_type)
            continue
        assert parsed_artifact is not None
        parsed[artifact_type] = parsed_artifact

        source_ids = _artifact_source_ids(parsed_artifact)
        source_errors: list[str] = []
        metadata = version.metadata_json or {}
        expected_metadata = {
            "quality_mode": context.quality_mode,
            "profile_snapshot_id": context.profile_snapshot_id,
            "domain_version_id": context.domain_version_id,
            "target_knowledge_point_ids": context.target_knowledge_point_ids,
            "source_ref_ids": context.source_ref_ids,
            "trace_id": task.trace_id,
        }
        for key, expected in expected_metadata.items():
            if metadata.get(key) != expected:
                source_errors.append(f"metadata_mismatch:{key}")
        source_rows = (
            session.query(DBSourceRef, DBSourceDocument)
            .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
            .filter(DBSourceRef.id.in_(source_ids))
            .all()
        )
        if {source_ref.id for source_ref, _doc in source_rows} != set(source_ids):
            source_errors.append("source_missing")
        if any(
            document.course_id != context.course_id or document.processing_status != "ready"
            for _source_ref, document in source_rows
        ):
            source_errors.append("source_course_or_status_mismatch")
        try:
            validate_artifact_scope(parsed_artifact, context)
        except Exception as exc:
            source_errors.append(getattr(exc, "code", type(exc).__name__))
        source_passed = not source_errors
        check_rows.append(
            _quality_check(
                session,
                version=version,
                trace_id=task.trace_id,
                check_type="source_binding",
                checker_version=SOURCE_CHECKER_VERSION,
                passed=source_passed,
                details={
                    "errors": source_errors,
                    "metric": "source_resolution_rate",
                    "semantic_support_assessed": False,
                },
                source_ref_ids=source_ids,
            )
        )
        if source_passed:
            claim_rows.extend(
                _claim_checks(
                    session,
                    artifact=parsed_artifact,
                    version=version,
                    trace_id=task.trace_id,
                    source_ref_ids=source_ids,
                )
            )
        else:
            failed_types.add(artifact_type)

    consistency_errors: list[str] = []
    consistency_failed_types: set[str] = set()
    if set(parsed) != set(ARTIFACT_CAPABILITY):
        consistency_errors.append("artifact_schema_set_incomplete")
        consistency_failed_types.update(set(ARTIFACT_CAPABILITY) - set(parsed))
    else:
        expected_shared = {
            "profile_snapshot_id": context.profile_snapshot_id,
            "domain_version_id": context.domain_version_id,
            "target_knowledge_point_ids": context.target_knowledge_point_ids,
            "source_ref_ids": context.source_ref_ids,
            "trace_id": task.trace_id,
        }
        for key, expected in expected_shared.items():
            mismatched = {
                artifact_type
                for artifact_type, version in versions.items()
                if (version.metadata_json or {}).get(key) != expected
            }
            if mismatched:
                consistency_errors.append(f"cross_artifact_mismatch:{key}")
                consistency_failed_types.update(mismatched)
        source_sets = [set(_artifact_source_ids(parsed[item])) for item in ARTIFACT_CAPABILITY]
        if not set.intersection(*source_sets):
            consistency_errors.append("no_shared_source_reference")
            consistency_failed_types.update(ARTIFACT_CAPABILITY)
    consistency_passed = not consistency_errors
    for artifact_type, version in versions.items():
        check_rows.append(
            _quality_check(
                session,
                version=version,
                trace_id=task.trace_id,
                check_type="cross_artifact_binding",
                checker_version=CONSISTENCY_CHECKER_VERSION,
                passed=consistency_passed,
                details={
                    "errors": consistency_errors,
                    "metric": "cross_artifact_binding_pass_rate",
                    "semantic_conflict_assessed": False,
                },
                source_ref_ids=list((version.metadata_json or {}).get("source_ref_ids") or []),
            )
        )
    if not consistency_passed:
        failed_types.update(consistency_failed_types)

    if failed_types:
        for artifact_type in sorted(failed_types):
            latest = (
                session.query(DBTaskStep)
                .filter_by(task_id=task.id, sequence=ARTIFACT_SEQUENCE[artifact_type])
                .order_by(DBTaskStep.attempt.desc())
                .first()
            )
            if latest is not None and latest.status == "completed":
                schedule_rework_step(
                    session,
                    task_id=task.id,
                    owner_public_id=context.owner_public_id,
                    sequence=latest.sequence,
                    reason_code="m2_quality_failed",
                )
        if quality_step.status == "running":
            fail_task_step(
                session,
                task_id=task.id,
                owner_public_id=context.owner_public_id,
                sequence=4,
                error_code="m2_quality_failed",
                error_message="one or more M2 artifact checks failed",
                retryable=True,
            )
    else:
        complete_task_step(
            session,
            task_id=task.id,
            owner_public_id=context.owner_public_id,
            sequence=4,
        )
    session.flush()
    return M2BundleQualityResult(
        passed=not failed_types,
        failed_artifact_types=sorted(failed_types),
        quality_check_ids=[row.id for row in check_rows],
        claim_check_ids=[row.id for row in claim_rows],
        checker_versions={
            "schema": SCHEMA_CHECKER_VERSION,
            "source_binding": SOURCE_CHECKER_VERSION,
            "cross_artifact_binding": CONSISTENCY_CHECKER_VERSION,
        },
    )
