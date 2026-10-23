"""Authenticated operator API for M4 benchmark runs and draft reports."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from app.auth import get_current_user
from app.database import (
    DBDomainVersion,
    DBEvaluationCase,
    DBEvaluationResult,
    DBEvaluationRun,
    DBUser,
    run_db_op,
)
from app.identity import normalize_role
from app.m2_contracts import StrictModel
from app.m4_annotations import add_annotation, current_annotations, persist_draft_report, resolve_scoring_annotations
from app.m4_evaluation import (
    AdaptationAnnotation,
    AtomicFactAnnotation,
    CaseOutcome,
    CoverageAnnotation,
    M4EvaluationError,
    calculate_metric_report,
    load_frozen_benchmark,
)
from app.m4_runs import (
    BlindCaseOutput,
    blind_cases_for_run,
    record_blind_result,
    seal_blind_run,
    start_evaluation_run,
    sync_frozen_cases,
)


router = APIRouter(prefix="/api/v1/m4", tags=["m4-evaluation"])


class RunCreate(StrictModel):
    trace_id: str = Field(min_length=8, max_length=128)
    code_version: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=128)
    domain_version_id: str = Field(min_length=3, max_length=64)


class AnnotationCreate(StrictModel):
    case_id: str
    annotation_type: Literal["atomic_fact", "adaptation", "coverage"]
    annotation_version: int = Field(default=1, ge=1)
    supersedes_id: str | None = None
    payload: dict[str, Any]


def _operator(user: DBUser) -> None:
    if normalize_role(user.role) not in {"admin", "teacher"}:
        raise HTTPException(status_code=403, detail={"code": "m4_operator_required", "message": "M4 evaluation is restricted to operators"})


def _http_error(exc: Exception) -> HTTPException:
    code = str(getattr(exc, "code", "m4_operation_failed"))
    status = 409 if any(token in code for token in ("conflict", "incomplete", "not_")) else 422
    if code.endswith("unknown"):
        status = 404
    return HTTPException(status_code=status, detail={"code": code, "message": str(exc)})


def _run(session: Any, run_id: str) -> DBEvaluationRun:
    row = session.query(DBEvaluationRun).filter_by(id=run_id).first()
    if row is None:
        raise M4EvaluationError("evaluation_run_unknown", "evaluation run does not exist")
    return row


@router.get("/benchmark")
async def benchmark_summary(current_user: DBUser = Depends(get_current_user)):
    _operator(current_user)
    benchmark = load_frozen_benchmark()
    return {
        "schema_version": benchmark.schema_version,
        "case_version": benchmark.case_version,
        "knowledge_point_version": benchmark.knowledge_point_version,
        "metric_version": benchmark.metric_version,
        "case_count": len(benchmark.cases),
        "core_knowledge_point_count": len(benchmark.core_knowledge_point_ids),
        "domain_id": benchmark.domain_id,
        "course_id": benchmark.course_id,
        "course_manifest_sha256": benchmark.course_manifest_sha256,
        "profile_version": benchmark.profile_version,
        "profile_ids": list(benchmark.profile_ids),
        "profile_count": len(benchmark.profile_ids),
        "case_file_sha256": benchmark.case_file_sha256,
        "knowledge_point_file_sha256": benchmark.knowledge_point_file_sha256,
        "gold_included": False,
    }


@router.post("/runs")
async def create_run(payload: RunCreate, current_user: DBUser = Depends(get_current_user)):
    _operator(current_user)
    benchmark = load_frozen_benchmark()

    def operation(session: Any):
        domain_version = session.query(DBDomainVersion).filter_by(id=payload.domain_version_id).first()
        if domain_version is None:
            raise M4EvaluationError("domain_version_unknown", "domain version does not exist")
        sync_frozen_cases(session, benchmark=benchmark, domain_version_id=domain_version.id)
        run = start_evaluation_run(
            session,
            benchmark=benchmark,
            trace_id=payload.trace_id,
            code_version=payload.code_version,
            model_version=payload.model_version,
        )
        return {"run_id": run.id, "status": run.status, "trace_id": run.trace_id, "data_version": run.data_version}

    try:
        return await run_db_op(operation)
    except M4EvaluationError as exc:
        raise _http_error(exc) from exc


@router.get("/runs/{run_id}/cases")
async def get_blind_cases(run_id: str, current_user: DBUser = Depends(get_current_user)):
    _operator(current_user)
    try:
        return await run_db_op(lambda session: {"run_id": run_id, "cases": blind_cases_for_run(session, _run(session, run_id))})
    except M4EvaluationError as exc:
        raise _http_error(exc) from exc


@router.post("/runs/{run_id}/results")
async def submit_result(run_id: str, payload: BlindCaseOutput, current_user: DBUser = Depends(get_current_user)):
    _operator(current_user)
    try:
        return await run_db_op(lambda session: {
            "result_id": record_blind_result(session, run=_run(session, run_id), output=payload).id,
            "case_id": payload.case_id,
            "scored": False,
        })
    except M4EvaluationError as exc:
        raise _http_error(exc) from exc


@router.post("/runs/{run_id}/seal")
async def seal_run(run_id: str, current_user: DBUser = Depends(get_current_user)):
    _operator(current_user)
    try:
        return await run_db_op(lambda session: {
            "run_id": run_id,
            "status": seal_blind_run(session, _run(session, run_id)).status,
        })
    except M4EvaluationError as exc:
        raise _http_error(exc) from exc


@router.post("/runs/{run_id}/annotations")
async def create_annotation(run_id: str, request: AnnotationCreate, current_user: DBUser = Depends(get_current_user)):
    _operator(current_user)
    payload_types = {
        "atomic_fact": AtomicFactAnnotation,
        "adaptation": AdaptationAnnotation,
        "coverage": CoverageAnnotation,
    }
    try:
        annotation_payload = payload_types[request.annotation_type].model_validate(request.payload)

        def operation(session: Any):
            run = _run(session, run_id)
            case = session.query(DBEvaluationCase).filter_by(case_code=request.case_id, case_version=run.data_version).first()
            result = session.query(DBEvaluationResult).filter_by(
                evaluation_run_id=run.id,
                evaluation_case_id=case.id if case else "",
            ).first()
            if result is None:
                raise M4EvaluationError("evaluation_result_unknown", "case has no persisted blind result")
            row = add_annotation(
                session,
                result=result,
                payload=annotation_payload,
                annotation_version=request.annotation_version,
                supersedes_id=request.supersedes_id,
            )
            return {"annotation_id": row.id, "status": row.status, "content_hash": row.content_hash}

        return await run_db_op(operation)
    except (M4EvaluationError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.post("/runs/{run_id}/report")
async def create_draft_report(run_id: str, current_user: DBUser = Depends(get_current_user)):
    _operator(current_user)
    benchmark = load_frozen_benchmark()

    def operation(session: Any):
        run = _run(session, run_id)
        annotations, unresolved = resolve_scoring_annotations(current_annotations(session, run))
        facts = tuple(AtomicFactAnnotation.model_validate(row.payload) for row in annotations if row.annotation_type == "atomic_fact")
        adaptations = tuple(AdaptationAnnotation.model_validate(row.payload) for row in annotations if row.annotation_type == "adaptation")
        coverage = tuple(CoverageAnnotation.model_validate(row.payload) for row in annotations if row.annotation_type == "coverage")
        results = session.query(DBEvaluationResult).filter_by(evaluation_run_id=run.id).all()
        outputs = [BlindCaseOutput.model_validate(row.output_data) for row in results]
        outcomes = tuple(
            CaseOutcome(
                case_id=item.case_id,
                status=item.status,
                citation_count=item.citation_count,
                locatable_citation_count=item.locatable_citation_count,
            )
            for item in outputs
        )
        report = calculate_metric_report(
            benchmark,
            outcomes=outcomes,
            fact_annotations=facts,
            adaptation_annotations=adaptations,
            coverage_annotations=coverage,
        )
        if unresolved:
            report = report.model_copy(update={
                "publication_blockers": report.publication_blockers + ("annotation_groups_unresolved",),
            })
        row = persist_draft_report(
            session,
            run=run,
            benchmark=benchmark,
            report_data=report.model_dump(mode="json"),
        )
        return {
            "report_id": row.id,
            "status": row.status,
            "content_hash": row.content_hash,
            "report": report.model_dump(mode="json"),
            "annotation_resolution": {"resolved": len(annotations), "unresolved": list(unresolved)},
        }

    try:
        return await run_db_op(operation)
    except M4EvaluationError as exc:
        raise _http_error(exc) from exc
