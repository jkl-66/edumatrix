"""Persistent, versioned resource manifest for the M2 golden loop."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import Field

from app.database import (
    DBArtifact,
    DBArtifactRelation,
    DBArtifactVersion,
    DBClaimCheck,
    DBDecisionRecord,
    DBGenerationTask,
    DBLearningEvent,
    DBProfileEvidence,
    DBQualityCheck,
    DBTaskEvent,
    DBTaskStep,
)
from app.m1_repository import add_artifact_relation, add_artifact_version, create_artifact_with_version
from app.m2_context import assemble_verified_context
from app.m2_contracts import GenerationContext, StrictModel
from app.m2_quality import ARTIFACT_CAPABILITY
from app.m2_tasks import M2_GOLDEN_CAPABILITY


M2_MANIFEST_TYPE = "m2_bundle_manifest"


class ManifestArtifact(StrictModel):
    artifact_type: Literal["lesson", "lab_guide", "tiered_quiz"]
    artifact_id: str
    version_id: str
    version_number: int = Field(ge=1)
    content_hash: str
    status: str
    step_id: str
    step_attempt: int = Field(ge=1)
    quality_check_ids: list[str]
    claim_check_ids: list[str]


class M2BundleManifest(StrictModel):
    schema_version: Literal["m2.bundle_manifest.v1"] = "m2.bundle_manifest.v1"
    status: Literal["quality_passed", "feedback_recorded", "completed"]
    task_id: str
    trace_id: str
    owner_public_id: str
    course_id: str
    domain_version_id: str
    profile_snapshot_id: str
    target_knowledge_point_ids: list[str]
    source_ref_ids: list[str]
    artifacts: list[ManifestArtifact] = Field(min_length=3, max_length=3)
    task_event_ids: list[str]
    learning_event_ids: list[str]
    profile_evidence_ids: list[str]
    decision_ids: list[str]


class M2ManifestError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_m2_manifest(
    session: Any,
    *,
    task_id: str,
    context: GenerationContext,
) -> tuple[DBArtifact, DBArtifactVersion, bool]:
    verified = assemble_verified_context(
        session,
        **context.model_dump(exclude={"quality_mode"}),
    )
    task = session.query(DBGenerationTask).filter_by(id=task_id).first()
    if (
        task is None
        or task.capability != M2_GOLDEN_CAPABILITY
        or task.owner_public_id != verified.owner_public_id
        or task.course_id != verified.course_id
    ):
        raise M2ManifestError("task_context_mismatch", "manifest task does not match verified context")

    rows: list[ManifestArtifact] = []
    child_artifacts: list[DBArtifact] = []
    for artifact_type in ARTIFACT_CAPABILITY:
        artifact = session.query(DBArtifact).filter_by(
            creating_task_id=task.id,
            artifact_type=artifact_type,
        ).first()
        if artifact is None or not artifact.current_version_id:
            raise M2ManifestError("artifact_set_incomplete", "manifest requires all three artifacts")
        version = session.query(DBArtifactVersion).filter_by(id=artifact.current_version_id).one()
        latest_step = (
            session.query(DBTaskStep)
            .filter_by(task_id=task.id, output_artifact_version_id=version.id)
            .order_by(DBTaskStep.attempt.desc())
            .first()
        )
        if latest_step is None or latest_step.status != "completed":
            raise M2ManifestError("artifact_step_incomplete", "artifact version is not bound to a completed step")
        checks = session.query(DBQualityCheck).filter_by(artifact_version_id=version.id).all()
        required_check_types = {"schema", "source_binding", "cross_artifact_binding"}
        if {check.check_type for check in checks if check.status == "passed"} != required_check_types:
            raise M2ManifestError("quality_checks_incomplete", "artifact version has not passed every M2 check")
        claims = session.query(DBClaimCheck).filter_by(artifact_version_id=version.id).all()
        rows.append(
            ManifestArtifact(
                artifact_type=artifact_type,
                artifact_id=artifact.id,
                version_id=version.id,
                version_number=version.version_number,
                content_hash=version.content_hash,
                status=artifact.status,
                step_id=latest_step.id,
                step_attempt=latest_step.attempt,
                quality_check_ids=sorted(check.id for check in checks),
                claim_check_ids=sorted(claim.id for claim in claims),
            )
        )
        child_artifacts.append(artifact)

    task_events = session.query(DBTaskEvent).filter_by(task_id=task.id).order_by(DBTaskEvent.sequence).all()
    learning_events = session.query(DBLearningEvent).filter_by(trace_id=task.trace_id).all()
    profile_evidence = session.query(DBProfileEvidence).filter_by(trace_id=task.trace_id).all()
    decisions = session.query(DBDecisionRecord).filter_by(task_id=task.id).all()
    status = "completed" if task.status == "completed" else (
        "feedback_recorded" if learning_events or profile_evidence or decisions else "quality_passed"
    )
    manifest = M2BundleManifest(
        status=status,
        task_id=task.id,
        trace_id=task.trace_id,
        owner_public_id=verified.owner_public_id,
        course_id=verified.course_id,
        domain_version_id=verified.domain_version_id,
        profile_snapshot_id=verified.profile_snapshot_id,
        target_knowledge_point_ids=verified.target_knowledge_point_ids,
        source_ref_ids=verified.source_ref_ids,
        artifacts=rows,
        task_event_ids=[event.id for event in task_events],
        learning_event_ids=sorted(event.id for event in learning_events),
        profile_evidence_ids=sorted(item.id for item in profile_evidence),
        decision_ids=sorted(item.id for item in decisions),
    )
    content = _canonical_json(manifest.model_dump(mode="json"))
    metadata = {
        "schema_version": manifest.schema_version,
        "trace_id": task.trace_id,
        "profile_snapshot_id": verified.profile_snapshot_id,
        "domain_version_id": verified.domain_version_id,
        "source_ref_ids": verified.source_ref_ids,
        "contains_artifact_ids": [artifact.id for artifact in child_artifacts],
        "sensitive_fields": [],
    }
    artifact = session.query(DBArtifact).filter_by(
        creating_task_id=task.id,
        artifact_type=M2_MANIFEST_TYPE,
    ).first()
    created_version = False
    if artifact is None:
        artifact, version = create_artifact_with_version(
            session,
            owner_public_id=verified.owner_public_id,
            artifact_type=M2_MANIFEST_TYPE,
            title="M2 单画像黄金闭环资源包",
            content=content,
            content_format="json",
            course_id=verified.course_id,
            creating_task_id=task.id,
            metadata=metadata,
        )
        created_version = True
    else:
        version = session.query(DBArtifactVersion).filter_by(id=artifact.current_version_id).one()
        if version.content != content:
            version = add_artifact_version(
                session,
                artifact=artifact,
                content=content,
                content_format="json",
                created_by_public_id=verified.owner_public_id,
                created_task_id=task.id,
                metadata=metadata,
            )
            created_version = True

    for child in child_artifacts:
        relation = session.query(DBArtifactRelation).filter_by(
            source_artifact_id=artifact.id,
            target_artifact_id=child.id,
            relation_type="contains",
        ).first()
        if relation is None:
            add_artifact_relation(
                session,
                source_artifact_id=artifact.id,
                target_artifact_id=child.id,
                relation_type="contains",
                created_by_public_id=verified.owner_public_id,
            )
    session.flush()
    return artifact, version, created_version
