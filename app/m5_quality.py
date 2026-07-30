"""Type-aware, persisted quality checks for canonical M5 artifact versions."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import Field

from app.database import (
    DBArtifact,
    DBArtifactVersion,
    DBQualityCheck,
    DBSourceRef,
    DBTaskEvent,
)
from app.m2_contracts import LabGuideArtifact, LessonArtifact, StrictModel, TieredQuizArtifact
from app.m3_interactive import M3InteractiveManifest


M5_INTEGRITY_CHECKER = "m5.integrity.v1"
M5_SCHEMA_CHECKER = "m5.type-schema.v1"
M5_SOURCE_CHECKER = "m5.source-binding.v1"


class M5QualityResult(StrictModel):
    artifact_version_id: str
    status: Literal["passed", "failed", "manual_required"]
    ready_for_review: bool
    check_ids: tuple[str, ...]
    blockers: tuple[str, ...]


def _persist_check(
    session: Any,
    *,
    version: DBArtifactVersion,
    trace_id: str,
    check_type: str,
    checker_version: str,
    status: str,
    details: dict[str, Any],
    source_ref_ids: list[str] | None = None,
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
        status=status,
        score=1.0 if status == "passed" else 0.0 if status == "failed" else None,
        details=details,
        source_ref_ids=source_ref_ids or [],
    )
    session.add(row)
    session.flush()
    return row


def _quality_context(session: Any, artifact: DBArtifact, version: DBArtifactVersion) -> tuple[str, str]:
    metadata = version.metadata_json or {}
    quality_mode = str(metadata.get("quality_mode") or "standard")
    trace_id = str(metadata.get("trace_id") or "")
    if artifact.creating_task_id:
        event = session.query(DBTaskEvent).filter_by(
            task_id=artifact.creating_task_id,
            event_type="m5.contract.locked",
        ).first()
        if event is not None:
            contract = (event.payload or {}).get("contract") or {}
            quality_mode = str(contract.get("quality_mode") or quality_mode)
        if not trace_id:
            trace_id = str((event.payload or {}).get("route", {}).get("trace_id", "")) if event else ""
    return quality_mode, trace_id or f"quality-{version.id}"


def _validate_schema(artifact_type: str, content: str) -> tuple[str, list[str]]:
    validators = {
        "lesson": LessonArtifact,
        "lab_guide": LabGuideArtifact,
        "tiered_quiz": TieredQuizArtifact,
        "interactive_skill_artifact": M3InteractiveManifest,
    }
    validator = validators.get(artifact_type)
    if validator is None:
        return "manual_required", ["artifact_type_checker_unregistered"]
    try:
        validator.model_validate(json.loads(content))
        return "passed", []
    except Exception as exc:
        return "failed", [f"schema_invalid:{type(exc).__name__}"]


def run_artifact_quality_checks(
    session: Any,
    *,
    artifact: DBArtifact,
    version: DBArtifactVersion,
) -> M5QualityResult:
    if version.artifact_id != artifact.id:
        raise ValueError("artifact version does not belong to the artifact")
    quality_mode, trace_id = _quality_context(session, artifact, version)
    checks = []
    blockers = []

    actual_hash = hashlib.sha256(version.content.encode("utf-8")).hexdigest()
    integrity_status = "passed" if actual_hash == version.content_hash else "failed"
    if integrity_status == "failed":
        blockers.append("content_hash_mismatch")
    checks.append(_persist_check(
        session, version=version, trace_id=trace_id,
        check_type="integrity", checker_version=M5_INTEGRITY_CHECKER,
        status=integrity_status,
        details={"expected_hash": version.content_hash, "actual_hash": actual_hash},
    ))

    schema_status, schema_blockers = _validate_schema(artifact.artifact_type, version.content)
    blockers.extend(schema_blockers)
    checks.append(_persist_check(
        session, version=version, trace_id=trace_id,
        check_type="type_schema", checker_version=M5_SCHEMA_CHECKER,
        status=schema_status, details={"artifact_type": artifact.artifact_type, "blockers": schema_blockers},
    ))

    metadata = version.metadata_json or {}
    source_ids = list(dict.fromkeys(str(item) for item in metadata.get("source_ref_ids", []) if item))
    existing_ids = {
        item.id for item in session.query(DBSourceRef).filter(DBSourceRef.id.in_(source_ids)).all()
    } if source_ids else set()
    missing_sources = sorted(set(source_ids) - existing_ids)
    source_blockers = []
    if missing_sources:
        source_blockers.append("source_ref_missing")
    if quality_mode == "verified" and not source_ids:
        source_blockers.append("verified_source_refs_required")
    source_status = "failed" if source_blockers else "passed"
    blockers.extend(source_blockers)
    checks.append(_persist_check(
        session, version=version, trace_id=trace_id,
        check_type="source_binding", checker_version=M5_SOURCE_CHECKER,
        status=source_status,
        details={"quality_mode": quality_mode, "missing_source_ref_ids": missing_sources},
        source_ref_ids=source_ids,
    ))

    statuses = {item.status for item in checks}
    if "failed" in statuses:
        result_status = "failed"
    elif "manual_required" in statuses:
        result_status = "manual_required"
    else:
        result_status = "passed"
    return M5QualityResult(
        artifact_version_id=version.id,
        status=result_status,
        ready_for_review=result_status == "passed",
        check_ids=tuple(item.id for item in checks),
        blockers=tuple(sorted(set(blockers))),
    )
