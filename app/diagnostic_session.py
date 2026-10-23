"""Recoverable, owner-scoped learner drafts for entry diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.database import (
    DBAssessmentQuestion,
    DBAssessmentQuestionVersion,
    DBDiagnosticBlueprint,
    DBDiagnosticResponseDraft,
    DBDiagnosticSession,
    DBUser,
)
from app.diagnostic_generation import diagnostic_blueprint_payload


UNDERSTANDING_LEVELS = {"unfamiliar", "partial", "mostly", "clear"}


class DiagnosticSessionError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.details = details or {}


@dataclass(frozen=True)
class DiagnosticResponseInput:
    answer: dict[str, Any]
    understanding_level: str | None
    duration: int
    confidence: float | None
    idempotency_key: str
    saved_at: datetime
    resume_question_version_id: str | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(value: datetime | None) -> str | None:
    return f"{value.isoformat(timespec='seconds')}Z" if value else None


def _client_time(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _owned_blueprint(session: Any, *, user: DBUser, blueprint_id: str) -> DBDiagnosticBlueprint:
    row = session.get(DBDiagnosticBlueprint, blueprint_id)
    if row is None:
        raise DiagnosticSessionError("diagnostic_unknown", "诊断不存在。", status_code=404)
    if row.owner_public_id != user.public_id:
        raise DiagnosticSessionError("diagnostic_forbidden", "无权访问该诊断。", status_code=403)
    if row.status != "ready":
        raise DiagnosticSessionError("diagnostic_not_ready", "诊断题组尚未准备完成。")
    return row


def _owned_session(session: Any, *, user: DBUser, session_id: str) -> DBDiagnosticSession:
    row = session.get(DBDiagnosticSession, session_id)
    if row is None:
        raise DiagnosticSessionError("diagnostic_session_unknown", "诊断会话不存在。", status_code=404)
    if row.owner_public_id != user.public_id:
        raise DiagnosticSessionError("diagnostic_session_forbidden", "无权访问该诊断会话。", status_code=403)
    return row


def _answer_complete(question_type: str, answer: dict[str, Any]) -> bool:
    if question_type == "single_choice":
        return bool(str(answer.get("choice", "")).strip())
    if question_type == "multiple_choice":
        return bool(answer.get("choices"))
    if question_type == "true_false":
        return isinstance(answer.get("value"), bool)
    if question_type == "fill_blank":
        blanks = answer.get("blanks")
        return isinstance(blanks, list) and bool(blanks) and all(str(item).strip() for item in blanks)
    if question_type == "code":
        return bool(str(answer.get("code", "")).strip())
    return bool(str(answer.get("text", "")).strip())


def _response_complete(session: Any, row: DBDiagnosticResponseDraft) -> bool:
    version = session.get(DBAssessmentQuestionVersion, row.question_version_id)
    question = session.get(DBAssessmentQuestion, version.question_id) if version else None
    return bool(
        question
        and row.understanding_level in UNDERSTANDING_LEVELS
        and _answer_complete(question.question_type, dict(row.answer or {}))
    )


def start_or_resume_diagnostic_session(
    session: Any,
    *,
    user: DBUser,
    blueprint_id: str,
) -> tuple[DBDiagnosticSession, bool]:
    blueprint = _owned_blueprint(session, user=user, blueprint_id=blueprint_id)
    existing = session.query(DBDiagnosticSession).filter_by(
        owner_public_id=user.public_id,
        blueprint_id=blueprint.id,
    ).first()
    if existing is not None:
        return existing, False

    question_ids = list(blueprint.question_version_ids or [])
    if not question_ids:
        raise DiagnosticSessionError("diagnostic_questions_missing", "诊断题目不存在。")
    row = DBDiagnosticSession(
        owner_public_id=user.public_id,
        blueprint_id=blueprint.id,
        current_question_version_id=question_ids[0],
    )
    session.add(row)
    session.flush()
    return row, True


def save_diagnostic_response(
    session: Any,
    *,
    user: DBUser,
    session_id: str,
    question_version_id: str,
    response: DiagnosticResponseInput,
) -> tuple[DBDiagnosticResponseDraft, bool]:
    if response.understanding_level is not None and response.understanding_level not in UNDERSTANDING_LEVELS:
        raise DiagnosticSessionError("diagnostic_understanding_invalid", "理解程度选项无效。", status_code=422)
    if response.duration < 0 or response.duration > 86400:
        raise DiagnosticSessionError("diagnostic_duration_invalid", "本题作答时长无效。", status_code=422)
    if response.confidence is not None and not 0.0 <= response.confidence <= 1.0:
        raise DiagnosticSessionError("diagnostic_confidence_invalid", "作答信心必须在 0 到 1 之间。", status_code=422)
    work = _owned_session(session, user=user, session_id=session_id)
    if work.status != "active":
        raise DiagnosticSessionError("diagnostic_session_submitted", "诊断已提交，不能再修改答案。")
    blueprint = _owned_blueprint(session, user=user, blueprint_id=work.blueprint_id)
    question_ids = list(blueprint.question_version_ids or [])
    if question_version_id not in question_ids:
        raise DiagnosticSessionError("diagnostic_question_mismatch", "该题目不属于当前诊断。", status_code=422)
    if response.resume_question_version_id and response.resume_question_version_id not in question_ids:
        raise DiagnosticSessionError("diagnostic_resume_mismatch", "恢复位置不属于当前诊断。", status_code=422)

    replay = session.query(DBDiagnosticResponseDraft).filter_by(
        owner_public_id=user.public_id,
        idempotency_key=response.idempotency_key,
    ).first()
    if replay is not None:
        if replay.session_id != work.id or replay.question_version_id != question_version_id:
            raise DiagnosticSessionError("diagnostic_idempotency_conflict", "保存标识已用于其他题目。")
        return replay, False

    row = session.query(DBDiagnosticResponseDraft).filter_by(
        session_id=work.id,
        question_version_id=question_version_id,
    ).first()
    client_saved_at = _client_time(response.saved_at)
    if row is not None and row.client_saved_at is not None and client_saved_at <= row.client_saved_at:
        return row, False
    created = row is None
    saved_at = _now()
    if row is None:
        row = DBDiagnosticResponseDraft(
            session_id=work.id,
            owner_public_id=user.public_id,
            question_version_id=question_version_id,
        )
        session.add(row)
    row.answer = dict(response.answer)
    row.understanding_level = response.understanding_level
    row.duration_seconds = response.duration
    row.confidence = response.confidence
    row.idempotency_key = response.idempotency_key
    row.client_saved_at = client_saved_at
    row.saved_at = saved_at
    work.current_question_version_id = response.resume_question_version_id or question_version_id
    work.last_saved_at = saved_at
    session.flush()
    return row, created


def submit_diagnostic_session(
    session: Any,
    *,
    user: DBUser,
    session_id: str,
    idempotency_key: str,
) -> DBDiagnosticSession:
    work = _owned_session(session, user=user, session_id=session_id)
    if work.status == "submitted":
        return work
    blueprint = _owned_blueprint(session, user=user, blueprint_id=work.blueprint_id)
    responses = {
        row.question_version_id: row
        for row in session.query(DBDiagnosticResponseDraft).filter_by(session_id=work.id).all()
    }
    missing = [
        question_id
        for question_id in list(blueprint.question_version_ids or [])
        if question_id not in responses or not _response_complete(session, responses[question_id])
    ]
    if missing:
        raise DiagnosticSessionError(
            "diagnostic_answers_incomplete",
            "仍有题目未完成答案或理解程度选择。",
            details={"missingQuestionVersionIds": missing},
        )
    submitted_at = _now()
    work.status = "submitted"
    work.current_question_version_id = list(blueprint.question_version_ids or [])[-1]
    work.submission_idempotency_key = idempotency_key
    work.submitted_at = submitted_at
    work.last_saved_at = submitted_at
    session.flush()
    return work


def diagnostic_session_payload(session: Any, row: DBDiagnosticSession) -> dict[str, Any]:
    blueprint = session.get(DBDiagnosticBlueprint, row.blueprint_id)
    question_ids = list(blueprint.question_version_ids or []) if blueprint else []
    responses = session.query(DBDiagnosticResponseDraft).filter_by(session_id=row.id).all()
    response_items = []
    completed_ids = []
    for response in responses:
        complete = _response_complete(session, response)
        if complete:
            completed_ids.append(response.question_version_id)
        response_items.append({
            "id": response.id,
            "questionVersionId": response.question_version_id,
            "answer": dict(response.answer or {}),
            "understandingLevel": response.understanding_level,
            "duration": response.duration_seconds,
            "confidence": response.confidence,
            "clientSavedAt": _iso(response.client_saved_at),
            "savedAt": _iso(response.saved_at),
            "idempotencyKey": response.idempotency_key,
            "complete": complete,
        })
    current_index = question_ids.index(row.current_question_version_id) if row.current_question_version_id in question_ids else 0
    missing = [question_id for question_id in question_ids if question_id not in completed_ids]
    return {
        "schemaVersion": "f3.diagnostic-session.v1",
        "id": row.id,
        "blueprintId": row.blueprint_id,
        "status": row.status,
        "currentQuestionVersionId": row.current_question_version_id,
        "currentQuestionIndex": current_index,
        "questionCount": len(question_ids),
        "savedCount": len(responses),
        "completedCount": len(completed_ids),
        "canSubmit": not missing and bool(question_ids),
        "missingQuestionVersionIds": missing,
        "startedAt": _iso(row.started_at),
        "lastSavedAt": _iso(row.last_saved_at),
        "submittedAt": _iso(row.submitted_at),
        "responses": response_items,
        "blueprint": diagnostic_blueprint_payload(session, blueprint) if blueprint else None,
    }
