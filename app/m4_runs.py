"""Persistent blind-run lifecycle for the M4 benchmark."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Literal

from pydantic import Field, model_validator

from app.database import DBEvaluationCase, DBEvaluationResult, DBEvaluationRun
from app.m2_contracts import StrictModel
from app.m4_evaluation import FrozenBenchmark, M4EvaluationError


class BlindCaseOutput(StrictModel):
    case_id: str
    status: Literal["completed", "legal_refusal", "failed", "timeout"]
    response_text: str = Field(default="", max_length=100000)
    task_id: str = Field(default="", max_length=128)
    artifact_version_ids: tuple[str, ...] = ()
    error_code: str = Field(default="", max_length=128)
    citation_count: int = Field(default=0, ge=0)
    locatable_citation_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def citation_counts_are_consistent(self) -> "BlindCaseOutput":
        if self.locatable_citation_count > self.citation_count:
            raise ValueError("locatable citations cannot exceed all citations")
        return self


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def sync_frozen_cases(session: Any, *, benchmark: FrozenBenchmark, domain_version_id: str) -> tuple[DBEvaluationCase, ...]:
    rows = []
    for case in benchmark.cases:
        payload = case.model_dump(mode="json")
        content_hash = _hash(payload)
        row = session.query(DBEvaluationCase).filter_by(
            case_code=case.case_id,
            case_version=benchmark.case_version,
        ).first()
        if row is None:
            row = DBEvaluationCase(
                case_code=case.case_id,
                case_version=benchmark.case_version,
                domain_version_id=domain_version_id,
                input_data=case.blind_payload(),
                gold_data={
                    "gold": case.gold,
                    "kp": list(case.kp),
                    "difficulty": case.difficulty,
                    "failure_branch": case.failure_branch,
                },
                data_version=benchmark.case_version,
                content_hash=content_hash,
            )
            session.add(row)
        elif (
            row.domain_version_id != domain_version_id
            or row.data_version != benchmark.case_version
            or row.content_hash != content_hash
            or row.input_data != case.blind_payload()
        ):
            raise M4EvaluationError("frozen_case_conflict", f"frozen case differs from database: {case.case_id}")
        rows.append(row)
    session.commit()
    return tuple(rows)


def start_evaluation_run(
    session: Any,
    *,
    benchmark: FrozenBenchmark,
    trace_id: str,
    code_version: str,
    model_version: str,
) -> DBEvaluationRun:
    existing = session.query(DBEvaluationRun).filter_by(trace_id=trace_id).first()
    if existing is not None:
        if (
            existing.code_version != code_version
            or existing.data_version != benchmark.case_version
            or existing.model_version != model_version
        ):
            raise M4EvaluationError("evaluation_run_conflict", "trace_id is bound to another evaluation configuration")
        return existing
    run = DBEvaluationRun(
        trace_id=trace_id,
        code_version=code_version,
        data_version=benchmark.case_version,
        model_version=model_version,
        status="running",
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def blind_cases_for_run(session: Any, run: DBEvaluationRun) -> tuple[dict[str, object], ...]:
    rows = session.query(DBEvaluationCase).filter_by(case_version=run.data_version).order_by(DBEvaluationCase.case_code).all()
    if len(rows) != 60:
        raise M4EvaluationError("evaluation_case_count_invalid", f"run requires 60 cases, found {len(rows)}")
    return tuple(dict(row.input_data) for row in rows)


def record_blind_result(session: Any, *, run: DBEvaluationRun, output: BlindCaseOutput) -> DBEvaluationResult:
    if run.status != "running":
        raise M4EvaluationError("evaluation_run_not_running", "blind results can only be recorded while running")
    case = session.query(DBEvaluationCase).filter_by(
        case_code=output.case_id,
        case_version=run.data_version,
    ).first()
    if case is None:
        raise M4EvaluationError("evaluation_case_unknown", f"case is not part of this run: {output.case_id}")
    payload = output.model_dump(mode="json")
    existing = session.query(DBEvaluationResult).filter_by(
        evaluation_run_id=run.id,
        evaluation_case_id=case.id,
    ).first()
    if existing is not None:
        if existing.output_data != payload:
            raise M4EvaluationError("evaluation_result_conflict", "case already has a different immutable output")
        return existing
    result = DBEvaluationResult(
        evaluation_run_id=run.id,
        evaluation_case_id=case.id,
        output_data=payload,
        scores={},
        passed=False,
        failure_reason=output.error_code if output.status in {"failed", "timeout"} else "",
    )
    session.add(result)
    session.commit()
    session.refresh(result)
    return result


def seal_blind_run(session: Any, run: DBEvaluationRun) -> DBEvaluationRun:
    if run.status == "awaiting_annotation":
        return run
    if run.status != "running":
        raise M4EvaluationError("evaluation_run_not_sealable", f"cannot seal run in state {run.status}")
    expected = session.query(DBEvaluationCase).filter_by(case_version=run.data_version).count()
    actual = session.query(DBEvaluationResult).filter_by(evaluation_run_id=run.id).count()
    if expected != 60 or actual != expected:
        raise M4EvaluationError("evaluation_run_incomplete", f"blind run has {actual}/{expected} persisted results")
    run.status = "awaiting_annotation"
    run.completed_at = datetime.now(timezone.utc)
    session.commit()
    return run


def fail_evaluation_run(session: Any, run: DBEvaluationRun, *, reason: str) -> DBEvaluationRun:
    if run.status not in {"running", "awaiting_annotation"}:
        raise M4EvaluationError("evaluation_run_not_failurable", f"cannot fail run in state {run.status}")
    run.status = "failed"
    run.completed_at = datetime.now(timezone.utc)
    session.commit()
    return run
