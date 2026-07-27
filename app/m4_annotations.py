"""Immutable M4 annotations and draft metric-report persistence."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any, Literal

from app.database import DBEvaluationAnnotation, DBEvaluationReport, DBEvaluationResult, DBEvaluationRun
from app.m4_evaluation import (
    AdaptationAnnotation,
    AtomicFactAnnotation,
    CoverageAnnotation,
    FrozenBenchmark,
    M4EvaluationError,
    METRIC_VERSION,
)


AnnotationPayload = AtomicFactAnnotation | AdaptationAnnotation | CoverageAnnotation


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _annotation_identity(payload: AnnotationPayload) -> tuple[str, str]:
    if isinstance(payload, AtomicFactAnnotation):
        return "atomic_fact", payload.claim_id
    if isinstance(payload, AdaptationAnnotation):
        return "adaptation", payload.resource_id
    return "coverage", f"{payload.knowledge_point_id}:{payload.resource_type}:{payload.artifact_version_id}"


def add_annotation(
    session: Any,
    *,
    result: DBEvaluationResult,
    payload: AnnotationPayload,
    annotation_version: int = 1,
    supersedes_id: str | None = None,
) -> DBEvaluationAnnotation:
    output_case_id = str((result.output_data or {}).get("case_id", ""))
    payload_case_id = getattr(payload, "case_id", output_case_id)
    if payload_case_id != output_case_id:
        raise M4EvaluationError("annotation_case_mismatch", "annotation does not belong to the result case")
    annotation_type, annotation_key = _annotation_identity(payload)
    data = payload.model_dump(mode="json")
    existing = session.query(DBEvaluationAnnotation).filter_by(
        evaluation_result_id=result.id,
        annotation_type=annotation_type,
        annotation_key=annotation_key,
        annotator_ref=payload.annotator_ref,
        annotation_version=annotation_version,
    ).first()
    if existing is not None:
        if existing.content_hash != _hash(data):
            raise M4EvaluationError("annotation_version_conflict", "annotation version already contains different data")
        return existing

    if annotation_version > 1:
        previous = session.query(DBEvaluationAnnotation).filter_by(id=supersedes_id).first()
        if previous is None or (
            previous.evaluation_result_id != result.id
            or previous.annotation_type != annotation_type
            or previous.annotation_key != annotation_key
            or previous.annotator_ref != payload.annotator_ref
            or previous.annotation_version != annotation_version - 1
        ):
            raise M4EvaluationError("annotation_supersedes_invalid", "annotation revision must supersede the prior version")

    row = DBEvaluationAnnotation(
        evaluation_result_id=result.id,
        annotation_type=annotation_type,
        annotation_key=annotation_key,
        annotator_ref=payload.annotator_ref,
        annotation_version=annotation_version,
        supersedes_id=supersedes_id,
        payload=data,
        status=payload.status,
        content_hash=_hash(data),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def current_annotations(session: Any, run: DBEvaluationRun) -> tuple[DBEvaluationAnnotation, ...]:
    rows = (
        session.query(DBEvaluationAnnotation)
        .join(DBEvaluationResult, DBEvaluationAnnotation.evaluation_result_id == DBEvaluationResult.id)
        .filter(DBEvaluationResult.evaluation_run_id == run.id)
        .order_by(DBEvaluationAnnotation.annotation_version.desc(), DBEvaluationAnnotation.created_at.desc())
        .all()
    )
    latest = {}
    for row in rows:
        key = (row.evaluation_result_id, row.annotation_type, row.annotation_key, row.annotator_ref)
        latest.setdefault(key, row)
    return tuple(latest.values())


def resolve_scoring_annotations(
    rows: tuple[DBEvaluationAnnotation, ...],
) -> tuple[tuple[DBEvaluationAnnotation, ...], tuple[str, ...]]:
    grouped: dict[tuple[str, str, str], list[DBEvaluationAnnotation]] = defaultdict(list)
    for row in rows:
        grouped[(row.evaluation_result_id, row.annotation_type, row.annotation_key)].append(row)

    resolved = []
    unresolved = []
    for key, group in grouped.items():
        adjudicated = [row for row in group if row.status == "adjudicated"]
        if len(adjudicated) == 1:
            resolved.append(adjudicated[0])
            continue
        if len(adjudicated) > 1:
            unresolved.append(":".join(key) + ":multiple_adjudications")
            continue

        final = [row for row in group if row.status == "final"]
        if len({row.annotator_ref for row in final}) < 2:
            unresolved.append(":".join(key) + ":second_annotation_missing")
            continue
        signatures = set()
        for row in final:
            payload = dict(row.payload)
            for ignored in ("annotator_ref", "status", "rationale"):
                payload.pop(ignored, None)
            signatures.add(_canonical(payload))
        if len(signatures) != 1:
            unresolved.append(":".join(key) + ":annotation_disagreement")
            continue
        resolved.append(sorted(final, key=lambda row: row.annotator_ref)[0])
    return tuple(resolved), tuple(sorted(unresolved))


def persist_draft_report(
    session: Any,
    *,
    run: DBEvaluationRun,
    benchmark: FrozenBenchmark,
    report_data: dict[str, Any],
    report_version: int | None = None,
) -> DBEvaluationReport:
    if run.status not in {"awaiting_annotation", "failed"}:
        raise M4EvaluationError("report_run_state_invalid", "report requires a sealed or failed blind run")
    if report_data.get("publication_authorized") is not False:
        raise M4EvaluationError("metric_publication_not_approved", "M4 reports remain unapproved until independent review")
    envelope = {
        "benchmark_case_sha256": benchmark.case_file_sha256,
        "benchmark_kp_sha256": benchmark.knowledge_point_file_sha256,
        "data": report_data,
    }
    content_hash = _hash(envelope)
    latest = (
        session.query(DBEvaluationReport)
        .filter_by(evaluation_run_id=run.id, metric_version=METRIC_VERSION)
        .order_by(DBEvaluationReport.report_version.desc())
        .first()
    )
    if latest is not None and latest.content_hash == content_hash:
        return latest
    if report_version is None:
        report_version = 1 if latest is None else latest.report_version + 1
    elif latest is not None and report_version <= latest.report_version:
        raise M4EvaluationError("evaluation_report_conflict", "report version must advance for changed data")
    row = DBEvaluationReport(
        evaluation_run_id=run.id,
        metric_version=METRIC_VERSION,
        report_version=report_version,
        report_data=envelope,
        status="draft",
        approval_ref="",
        content_hash=content_hash,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
