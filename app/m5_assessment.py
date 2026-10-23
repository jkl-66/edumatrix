"""Normalize assessment, code, wrong-question, and review signals into M5 events."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field, model_validator

from app.m2_contracts import StrictModel
from app.m5_learning import (
    LearningEventInput,
    LearningEventType,
    process_path_event,
    record_learning_event,
)
from app.database import DBAssessmentAttempt, DBUser
from app.schemas import ContextRef


class M5AssessmentError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _aggregation_payload(consumption: Any) -> dict[str, Any]:
    result = dict(consumption.result or {})
    return {
        "id": consumption.id,
        "status": consumption.status,
        "processor_version": consumption.processor_version,
        "attempt": consumption.attempt,
        "error_code": consumption.error_code or "",
        "result": result,
    }


def _path_consumption_payload(consumption: Any) -> dict[str, Any]:
    result = dict(consumption.result or {})
    return {
        "id": consumption.id,
        "status": consumption.status,
        "result": dict((result.get("steps") or {}).get("path_task") or {}),
    }


class AssessmentEvidenceInput(StrictModel):
    schema_version: Literal["m5.assessment-evidence.v1"] = "m5.assessment-evidence.v1"
    idempotency_key: str = Field(min_length=8, max_length=128)
    source_type: Literal["quiz_attempt", "code_execution", "wrong_question_review", "delayed_retest"]
    source_object_id: str = Field(min_length=1, max_length=64)
    attempt_id: str | None = Field(default=None, max_length=64)
    course_id: str | None = Field(default=None, max_length=128)
    target_object_type: str = Field(min_length=1, max_length=64)
    target_object_id: str = Field(min_length=1, max_length=64)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    correct: bool | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    passed_count: int | None = Field(default=None, ge=0)
    total_count: int | None = Field(default=None, ge=1)
    test_scope: Literal["none", "public", "hidden", "required"] = "none"
    delay_hours: float | None = Field(default=None, ge=0)
    actual_minutes: int | None = Field(default=None, ge=0, le=10080)

    @model_validator(mode="after")
    def source_fields(self) -> "AssessmentEvidenceInput":
        if self.source_type == "quiz_attempt" and self.correct is None:
            raise ValueError("quiz_attempt requires correct")
        if self.source_type == "code_execution":
            if self.passed_count is None or self.total_count is None:
                raise ValueError("code_execution requires passed_count and total_count")
            if self.passed_count > self.total_count:
                raise ValueError("passed_count cannot exceed total_count")
        if self.source_type == "delayed_retest":
            if self.correct is None or self.delay_hours is None:
                raise ValueError("delayed_retest requires correct and delay_hours")
        return self


def normalize_assessment_event(
    evidence: AssessmentEvidenceInput, *, trusted_source: bool = True,
) -> LearningEventInput:
    payload: dict[str, Any] = {
        "evidence_schema_version": evidence.schema_version,
        "source_object_id": evidence.source_object_id,
    }
    if evidence.actual_minutes is not None:
        payload["actual_minutes"] = evidence.actual_minutes
    if evidence.source_type == "quiz_attempt":
        event_type = "quiz_answered"
        payload.update(
            correct=bool(evidence.correct),
            confidence=evidence.confidence,
            graded=True,
            attempt_id=evidence.attempt_id or evidence.source_object_id,
        )
    elif evidence.source_type == "code_execution":
        all_passed = evidence.passed_count == evidence.total_count
        strong_scope = evidence.test_scope in {"hidden", "required"}
        event_type = "code_tests_passed" if all_passed and strong_scope else "code_run"
        payload.update(
            passed_count=evidence.passed_count, total_count=evidence.total_count,
            test_scope=evidence.test_scope, all_passed=all_passed,
            attempt_id=evidence.attempt_id or evidence.source_object_id,
        )
    elif evidence.source_type == "wrong_question_review":
        event_type = "wrong_question_reviewed"
    else:
        stable = bool(evidence.correct) and float(evidence.delay_hours or 0) >= 24
        event_type = "delayed_retest_passed" if stable else "quiz_answered"
        payload.update(
            correct=bool(evidence.correct), delay_hours=evidence.delay_hours,
            stable_retest=stable,
            attempt_id=evidence.attempt_id or evidence.source_object_id,
        )
    return LearningEventInput(
        idempotency_key=evidence.idempotency_key,
        event_type=event_type,
        course_id=evidence.course_id,
        object_type=evidence.target_object_type,
        object_id=evidence.target_object_id,
        source="backend" if trusted_source else "frontend",
        occurred_at=evidence.occurred_at,
        payload=payload,
    )


def record_assessment_evidence(
    session: Any, *, owner_public_id: str, evidence: AssessmentEvidenceInput,
    user: DBUser | None = None, trusted_source: bool = True,
) -> dict[str, Any]:
    normalized = normalize_assessment_event(evidence, trusted_source=trusted_source)
    event, created = record_learning_event(
        session,
        owner_public_id=owner_public_id,
        event=normalized,
        user=user,
        trusted_source=trusted_source,
    )
    consumption = process_path_event(session, event=event)
    aggregation = _aggregation_payload(consumption)
    profile_result = dict((aggregation["result"].get("steps") or {}).get("profile_snapshot") or {})
    return {
        "event_id": event.id,
        "event_type": event.event_type,
        "created": created,
        "evidence_status": event.evidence_status,
        "evidence_strength": event.evidence_strength,
        "strong_evidence": bool(event.mastery_eligible and event.evidence_strength >= 0.75),
        "path_consumption": _path_consumption_payload(consumption),
        "aggregation": aggregation,
        "mastery_changed": bool(profile_result.get("mastery_changed")),
    }


def record_canonical_attempt_evidence(
    session: Any,
    *,
    attempt: DBAssessmentAttempt,
    user: DBUser | None = None,
) -> dict[str, Any]:
    """Link a server-graded canonical attempt to one replayable learning event."""
    if user is not None and user.public_id != attempt.owner_public_id:
        raise M5AssessmentError(
            "attempt_owner_mismatch",
            "assessment attempt belongs to another owner",
        )
    event_type: LearningEventType = (
        "formal_exam_submitted" if attempt.mode == "formal" else "quiz_answered"
    )
    context = (
        ContextRef(courseId=attempt.course_id, attemptId=attempt.id)
        if attempt.course_id
        else None
    )
    event, created = record_learning_event(
        session,
        owner_public_id=attempt.owner_public_id,
        user=user,
        trusted_source=True,
        event=LearningEventInput(
            idempotency_key=f"assessment-attempt:{attempt.id}",
            event_type=event_type,
            context=context,
            course_id=attempt.course_id,
            object_type="assessment_question_version",
            object_id=attempt.question_version_id,
            source="backend",
            occurred_at=attempt.submitted_at.replace(tzinfo=timezone.utc),
            payload={
                "attempt_id": attempt.id,
                "graded": attempt.grading_status == "graded",
                "correct": attempt.correct,
                "score": attempt.score,
                "confidence": attempt.confidence,
                "mode": attempt.mode,
            },
        ),
    )
    consumption = process_path_event(session, event=event)
    aggregation = _aggregation_payload(consumption)
    profile_result = dict((aggregation["result"].get("steps") or {}).get("profile_snapshot") or {})
    return {
        "event_id": event.id,
        "event_type": event.event_type,
        "created": created,
        "evidence_status": event.evidence_status,
        "evidence_strength": event.evidence_strength,
        "mastery_changed": bool(profile_result.get("mastery_changed")),
        "path_consumption": _path_consumption_payload(consumption),
        "aggregation": aggregation,
    }


def record_legacy_assessment_evidence(
    session: Any, *, student_id: str, evidence: AssessmentEvidenceInput,
) -> dict[str, Any]:
    """Bridge a trusted legacy username into the canonical event owner."""
    user = session.query(DBUser).filter_by(username=student_id).first()
    if user is None:
        raise M5AssessmentError("legacy_assessment_owner_unknown", "student user does not exist")
    return record_assessment_evidence(
        session,
        owner_public_id=user.public_id,
        evidence=evidence,
        user=user,
        trusted_source=True,
    )
