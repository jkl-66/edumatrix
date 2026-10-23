"""Authenticated entry-diagnostic blueprint API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field, model_validator
from sqlalchemy.exc import IntegrityError

from app.auth import get_current_user
from app.database import DBDiagnosticBlueprint, DBDiagnosticReport, DBDiagnosticSession, DBUser, run_db_op
from app.diagnostic_generation import (
    DiagnosticBlueprintRequest,
    DiagnosticGenerationError,
    diagnostic_preflight,
    diagnostic_course_catalog,
    diagnostic_blueprint_payload,
    generate_diagnostic_blueprint,
)
from app.diagnostic_session import (
    DiagnosticResponseInput,
    DiagnosticSessionError,
    diagnostic_session_payload,
    save_diagnostic_response,
    start_or_resume_diagnostic_session,
    submit_diagnostic_session,
)
from app.diagnostic_report import (
    DiagnosticReportError,
    confirm_report_path,
    diagnostic_report_payload,
    generate_diagnostic_report,
    generate_report_path,
)
from app.multicourse_diagnostic import (
    MultiCourseBlueprintRequest,
    MultiCourseDiagnosticError,
    MultiCoursePathRequest,
    generate_multicourse_blueprints,
    generate_multicourse_paths,
)
from app.path_draft import PathDraftError
from app.m2_contracts import StrictModel
from config import CONFIG
from llm_client import build_async_llm


router = APIRouter(prefix="/api/v1/diagnostics", tags=["entry-diagnostic"])


class DiagnosticGenerateRequest(StrictModel):
    course_id: str
    idempotency_key: str = Field(min_length=8, max_length=128)
    question_count: Literal[15, 20, 25] = 15
    self_rating: Literal["foundation", "advanced", "mastered"] = "foundation"


class DiagnosticResponseSaveRequest(StrictModel):
    questionVersionId: str = Field(min_length=3, max_length=64)
    answer: dict[str, Any]
    understandingLevel: Literal["unfamiliar", "partial", "mostly", "clear"] | None = None
    duration: int = Field(ge=0, le=86400)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    savedAt: datetime
    idempotencyKey: str = Field(min_length=8, max_length=128)
    resumeQuestionVersionId: str | None = Field(default=None, min_length=3, max_length=64)

    @model_validator(mode="after")
    def answer_size(self) -> "DiagnosticResponseSaveRequest":
        if len(str(self.answer).encode("utf-8")) > 50000:
            raise ValueError("answer exceeds the diagnostic draft limit")
        return self


class DiagnosticSubmitRequest(StrictModel):
    idempotencyKey: str = Field(min_length=8, max_length=128)


class DiagnosticReportRequest(StrictModel):
    idempotencyKey: str = Field(min_length=8, max_length=128)


class DiagnosticPathRequest(StrictModel):
    idempotencyKey: str = Field(min_length=8, max_length=128)
    timeBudgetMinutes: int = Field(default=90, ge=30, le=480)


class MultiCourseDiagnosticGenerateRequest(StrictModel):
    courseIds: tuple[str, ...] = Field(min_length=1, max_length=8)
    idempotencyKey: str = Field(min_length=8, max_length=128)
    questionCount: Literal[15, 20, 25] = 15
    selfRating: Literal["foundation", "advanced", "mastered"] = "foundation"


class MultiCoursePathGenerateRequest(StrictModel):
    reportIds: tuple[str, ...] = Field(min_length=1, max_length=8)
    idempotencyKey: str = Field(min_length=8, max_length=128)
    timeBudgetMinutes: int = Field(default=90, ge=30, le=480)


def _error(exc: DiagnosticGenerationError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    )


def build_diagnostic_llm():
    return build_async_llm(
        CONFIG,
        model="deepseek-v4-flash",
        thinking_mode="enabled",
        reasoning_effort="max",
        allow_fallback=False,
    )


def _session_error(exc: DiagnosticSessionError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc), **exc.details},
    )


def _report_error(exc: DiagnosticReportError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    )


def _multicourse_error(exc: MultiCourseDiagnosticError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc), **exc.details},
    )


@router.get("/preflight")
async def get_diagnostic_preflight(
    course_id: str,
    question_count: int = Query(default=15),
    self_rating: Literal["foundation", "advanced", "mastered"] = Query(default="foundation"),
    current_user: DBUser = Depends(get_current_user),
):
    if current_user.role != "student":
        raise HTTPException(
            status_code=403,
            detail={"code": "diagnostic_student_required", "message": "仅学生可以开始入学诊断。"},
        )

    def operation(session):
        return diagnostic_preflight(
            session,
            user=current_user,
            course_id=course_id,
            question_count=question_count,
            self_rating=self_rating,
        )

    try:
        return await run_db_op(operation)
    except DiagnosticGenerationError as exc:
        raise _error(exc) from exc


@router.get("/courses")
async def get_diagnostic_courses(current_user: DBUser = Depends(get_current_user)):
    if current_user.role != "student":
        raise HTTPException(
            status_code=403,
            detail={"code": "diagnostic_student_required", "message": "仅学生可以开始入学诊断。"},
        )
    return await run_db_op(lambda session: diagnostic_course_catalog(session, user=current_user))


@router.post("/multi-course/blueprints", status_code=201)
async def create_multicourse_diagnostic_blueprints(
    payload: MultiCourseDiagnosticGenerateRequest,
    current_user: DBUser = Depends(get_current_user),
):
    """Create one independently frozen diagnostic blueprint per selected course."""
    if current_user.role != "student":
        raise HTTPException(
            status_code=403,
            detail={"code": "diagnostic_student_required", "message": "仅学生可以开始入学诊断。"},
        )

    def operation(session):
        try:
            result = generate_multicourse_blueprints(
                session,
                user=current_user,
                request=MultiCourseBlueprintRequest(
                    course_ids=tuple(payload.courseIds),
                    idempotency_key=payload.idempotencyKey,
                    question_count=payload.questionCount,
                    self_rating=payload.selfRating,
                ),
                llm=build_diagnostic_llm(),
            )
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise

    try:
        return await run_db_op(operation)
    except MultiCourseDiagnosticError as exc:
        raise _multicourse_error(exc) from exc


@router.post("/multi-course/paths", status_code=201)
async def create_multicourse_diagnostic_paths(
    payload: MultiCoursePathGenerateRequest,
    current_user: DBUser = Depends(get_current_user),
):
    """Generate subject path drafts and validate their aggregate schedule."""
    if current_user.role != "student":
        raise HTTPException(
            status_code=403,
            detail={"code": "diagnostic_student_required", "message": "仅学生可以生成入学路径。"},
        )

    def operation(session):
        try:
            result = generate_multicourse_paths(
                session,
                user=current_user,
                request=MultiCoursePathRequest(
                    report_ids=tuple(payload.reportIds),
                    idempotency_key=payload.idempotencyKey,
                    time_budget_minutes=payload.timeBudgetMinutes,
                ),
                llm=build_diagnostic_llm(),
            )
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise

    try:
        return await run_db_op(operation)
    except MultiCourseDiagnosticError as exc:
        raise _multicourse_error(exc) from exc


@router.post("/blueprints", status_code=201)
async def create_diagnostic_blueprint(
    payload: DiagnosticGenerateRequest,
    current_user: DBUser = Depends(get_current_user),
):
    if current_user.role != "student":
        raise HTTPException(
            status_code=403,
            detail={"code": "diagnostic_student_required", "message": "仅学生可以开始入学诊断。"},
        )

    def operation(session):
        llm = build_diagnostic_llm()
        request = DiagnosticBlueprintRequest(
            course_id=payload.course_id,
            idempotency_key=payload.idempotency_key,
            question_count=payload.question_count,
            self_rating=payload.self_rating,
        )
        try:
            row, created = generate_diagnostic_blueprint(
                session,
                user=current_user,
                request=request,
                llm=llm,
            )
            session.commit()
        except IntegrityError:
            session.rollback()
            row = session.query(DBDiagnosticBlueprint).filter_by(
                owner_public_id=current_user.public_id,
                course_id=payload.course_id,
                idempotency_key=payload.idempotency_key,
            ).first()
            if row is None:
                raise
            created = False
        except Exception:
            session.rollback()
            raise
        return {"created": created, "blueprint": diagnostic_blueprint_payload(session, row)}

    try:
        return await run_db_op(operation)
    except DiagnosticGenerationError as exc:
        raise _error(exc) from exc


@router.get("/blueprints/{blueprint_id}")
async def get_diagnostic_blueprint(
    blueprint_id: str,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        row = session.get(DBDiagnosticBlueprint, blueprint_id)
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "diagnostic_unknown", "message": "诊断不存在。"})
        if row.owner_public_id != current_user.public_id:
            raise HTTPException(status_code=403, detail={"code": "diagnostic_forbidden", "message": "无权查看该诊断。"})
        return diagnostic_blueprint_payload(session, row)

    return await run_db_op(operation)


@router.post("/blueprints/{blueprint_id}/sessions")
async def start_diagnostic_session(
    blueprint_id: str,
    current_user: DBUser = Depends(get_current_user),
):
    if current_user.role != "student":
        raise HTTPException(
            status_code=403,
            detail={"code": "diagnostic_student_required", "message": "仅学生可以进行入学诊断。"},
        )

    def operation(session):
        try:
            row, created = start_or_resume_diagnostic_session(
                session,
                user=current_user,
                blueprint_id=blueprint_id,
            )
            session.commit()
            return {"created": created, "session": diagnostic_session_payload(session, row)}
        except IntegrityError:
            session.rollback()
            row = session.query(DBDiagnosticSession).filter_by(
                owner_public_id=current_user.public_id,
                blueprint_id=blueprint_id,
            ).first()
            if row is None:
                raise
            return {"created": False, "session": diagnostic_session_payload(session, row)}
        except DiagnosticSessionError:
            session.rollback()
            raise

    try:
        return await run_db_op(operation)
    except DiagnosticSessionError as exc:
        raise _session_error(exc) from exc


@router.get("/sessions/{session_id}")
async def get_diagnostic_session(
    session_id: str,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        row = session.get(DBDiagnosticSession, session_id)
        if row is None:
            raise DiagnosticSessionError("diagnostic_session_unknown", "诊断会话不存在。", status_code=404)
        if row.owner_public_id != current_user.public_id:
            raise DiagnosticSessionError("diagnostic_session_forbidden", "无权访问该诊断会话。", status_code=403)
        return diagnostic_session_payload(session, row)

    try:
        return await run_db_op(operation)
    except DiagnosticSessionError as exc:
        raise _session_error(exc) from exc


@router.put("/sessions/{session_id}/responses/{question_version_id}")
async def save_diagnostic_session_response(
    session_id: str,
    question_version_id: str,
    payload: DiagnosticResponseSaveRequest,
    current_user: DBUser = Depends(get_current_user),
):
    if payload.questionVersionId != question_version_id:
        raise HTTPException(
            status_code=422,
            detail={"code": "diagnostic_question_mismatch", "message": "题目标识不一致。"},
        )

    def operation(session):
        try:
            _, created = save_diagnostic_response(
                session,
                user=current_user,
                session_id=session_id,
                question_version_id=question_version_id,
                response=DiagnosticResponseInput(
                    answer=payload.answer,
                    understanding_level=payload.understandingLevel,
                    duration=payload.duration,
                    confidence=payload.confidence,
                    idempotency_key=payload.idempotencyKey,
                    saved_at=payload.savedAt,
                    resume_question_version_id=payload.resumeQuestionVersionId,
                ),
            )
            row = session.get(DBDiagnosticSession, session_id)
            session.commit()
            return {"created": created, "session": diagnostic_session_payload(session, row)}
        except DiagnosticSessionError:
            session.rollback()
            raise

    try:
        return await run_db_op(operation)
    except DiagnosticSessionError as exc:
        raise _session_error(exc) from exc


@router.post("/sessions/{session_id}/submit")
async def submit_diagnostic_session_answers(
    session_id: str,
    payload: DiagnosticSubmitRequest,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        try:
            row = submit_diagnostic_session(
                session,
                user=current_user,
                session_id=session_id,
                idempotency_key=payload.idempotencyKey,
            )
            session.commit()
            return diagnostic_session_payload(session, row)
        except DiagnosticSessionError:
            session.rollback()
            raise

    try:
        return await run_db_op(operation)
    except DiagnosticSessionError as exc:
        raise _session_error(exc) from exc


@router.post("/sessions/{session_id}/report", status_code=201)
async def create_diagnostic_report(
    session_id: str,
    payload: DiagnosticReportRequest,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        try:
            llm = build_diagnostic_llm()
            row, created = generate_diagnostic_report(
                session,
                user=current_user,
                session_id=session_id,
                idempotency_key=payload.idempotencyKey,
                llm=llm,
            )
            session.commit()
            return {"created": created, "report": diagnostic_report_payload(session, user=current_user, row=row)}
        except DiagnosticReportError:
            session.rollback()
            raise

    try:
        return await run_db_op(operation)
    except DiagnosticReportError as exc:
        raise _report_error(exc) from exc


@router.get("/sessions/{session_id}/report")
async def get_diagnostic_report(
    session_id: str,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        row = session.query(DBDiagnosticReport).filter_by(session_id=session_id).first()
        if row is None:
            raise DiagnosticReportError("diagnostic_report_unknown", "诊断报告尚未生成。", status_code=404)
        return diagnostic_report_payload(session, user=current_user, row=row)

    try:
        return await run_db_op(operation)
    except DiagnosticReportError as exc:
        raise _report_error(exc) from exc


@router.post("/sessions/{session_id}/report/path")
async def generate_diagnostic_report_path(
    session_id: str,
    payload: DiagnosticPathRequest,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        row = session.query(DBDiagnosticReport).filter_by(session_id=session_id).first()
        if row is None:
            raise DiagnosticReportError("diagnostic_report_unknown", "请先生成诊断报告。", status_code=404)
        try:
            path = generate_report_path(
                session,
                user=current_user,
                report=row,
                time_budget_minutes=payload.timeBudgetMinutes,
                idempotency_key=payload.idempotencyKey,
                llm=build_diagnostic_llm(),
            )
            session.commit()
            return {"path": path, "report": diagnostic_report_payload(session, user=current_user, row=row)}
        except (DiagnosticReportError, PathDraftError) as exc:
            session.rollback()
            if isinstance(exc, DiagnosticReportError):
                raise
            raise DiagnosticReportError(exc.code, str(exc)) from exc

    try:
        return await run_db_op(operation)
    except DiagnosticReportError as exc:
        raise _report_error(exc) from exc


@router.post("/sessions/{session_id}/report/path/confirm")
async def confirm_diagnostic_report_path(
    session_id: str,
    payload: DiagnosticReportRequest,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        row = session.query(DBDiagnosticReport).filter_by(session_id=session_id).first()
        if row is None:
            raise DiagnosticReportError("diagnostic_report_unknown", "请先生成诊断报告。", status_code=404)
        try:
            result = confirm_report_path(session, user=current_user, report=row)
            session.commit()
            return result
        except DiagnosticReportError:
            session.rollback()
            raise

    try:
        return await run_db_op(operation)
    except DiagnosticReportError as exc:
        raise _report_error(exc) from exc
