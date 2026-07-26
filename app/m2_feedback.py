"""Idempotent learning feedback, profile evidence, and candidate decision writes."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field

from app.database import (
    DBArtifact,
    DBArtifactVersion,
    DBDecisionRecord,
    DBGenerationTask,
    DBLearningEvent,
    DBProfileEvidence,
    DBProfileSnapshot,
    DBUser,
)
from app.m2_context import assemble_verified_context
from app.m2_contracts import GenerationContext, StrictModel
from app.m2_manifest import build_m2_manifest
from app.m2_tasks import M2_GOLDEN_CAPABILITY, complete_golden_task


class M2LearningFeedback(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    artifact_version_id: str = Field(min_length=3, max_length=64)
    activity_type: Literal["lesson_review", "lab_attempt", "quiz_attempt"]
    completed: bool
    accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    help_requests: int = Field(default=0, ge=0, le=100)
    self_reported_difficulty: int | None = Field(default=None, ge=1, le=5)
    observed_seconds: int | None = Field(default=None, ge=0, le=86400)
    occurred_at: datetime
    note: str = Field(default="", max_length=1000)


class M2FeedbackResult(StrictModel):
    learning_event_id: str
    profile_evidence_id: str
    decision_id: str
    manifest_artifact_id: str
    manifest_version_id: str
    task_status: str
    feedback_state: Literal["recorded"] = "recorded"
    mastery_state: Literal["unchanged_pending_evidence"] = "unchanged_pending_evidence"
    created: bool


class M2FeedbackError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(owner_public_id: str, idempotency_key: str) -> str:
    return hashlib.sha256(f"{owner_public_id}:{idempotency_key}".encode("utf-8")).hexdigest()[:40]


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _decision_candidates(feedback: M2LearningFeedback) -> tuple[list[str], str, float]:
    if feedback.accuracy is None:
        return ["collect_more_evidence", "maintain_current_path"], "collect_more_evidence", 0.35
    if feedback.accuracy < 0.5 or feedback.help_requests >= 3:
        return (
            ["reduce_expression_load", "add_prerequisite_microcheck", "collect_more_evidence"],
            "collect_more_evidence",
            0.55,
        )
    if feedback.accuracy >= 0.85 and feedback.help_requests == 0:
        return (
            ["maintain_and_reinforce", "schedule_delayed_retest", "advance_after_confirmation"],
            "schedule_delayed_retest",
            0.55,
        )
    return (
        ["maintain_and_reinforce", "targeted_variant_practice", "collect_more_evidence"],
        "maintain_and_reinforce",
        0.5,
    )


def record_m2_feedback(
    session: Any,
    *,
    task_id: str,
    context: GenerationContext,
    feedback: M2LearningFeedback,
) -> M2FeedbackResult:
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
        or task.status not in {"running", "completed"}
    ):
        raise M2FeedbackError("task_context_mismatch", "feedback task does not match verified context")
    version_row = (
        session.query(DBArtifactVersion, DBArtifact)
        .join(DBArtifact, DBArtifact.id == DBArtifactVersion.artifact_id)
        .filter(DBArtifactVersion.id == feedback.artifact_version_id)
        .first()
    )
    if version_row is None:
        raise M2FeedbackError("artifact_version_not_found", "feedback artifact version does not exist")
    version, artifact = version_row
    if (
        artifact.creating_task_id != task.id
        or artifact.owner_public_id != verified.owner_public_id
        or artifact.course_id != verified.course_id
        or artifact.artifact_type not in {"lesson", "lab_guide", "tiered_quiz"}
    ):
        raise M2FeedbackError("artifact_version_forbidden", "feedback artifact is outside this M2 task")

    digest = _digest(verified.owner_public_id, feedback.idempotency_key)
    event_id = f"le-m2-{digest}"
    evidence_id = f"pe-m2-{digest}"
    decision_id = f"decision-m2-{digest}"
    payload = {
        "idempotency_key": feedback.idempotency_key,
        "activity_type": feedback.activity_type,
        "artifact_type": artifact.artifact_type,
        "artifact_version_id": version.id,
        "completed": feedback.completed,
        "accuracy": feedback.accuracy,
        "help_requests": feedback.help_requests,
        "self_reported_difficulty": feedback.self_reported_difficulty,
        "observed_seconds": feedback.observed_seconds,
        "learner_note_present": bool(feedback.note.strip()),
        "target_knowledge_point_ids": verified.target_knowledge_point_ids,
        "feedback_state": "recorded",
        "mastery_state": "unchanged_pending_evidence",
        "rule_version": "m2.feedback.v1",
    }
    event = session.query(DBLearningEvent).filter_by(id=event_id).first()
    created = event is None
    if event is None:
        event = DBLearningEvent(
            id=event_id,
            owner_public_id=verified.owner_public_id,
            legacy_student_id=None,
            course_id=verified.course_id,
            event_type="m2.learning_feedback.recorded",
            schema_version="m2.feedback.v1",
            trace_id=task.trace_id,
            object_type="artifact_version",
            object_id=version.id,
            payload=payload,
            occurred_at=_naive_utc(feedback.occurred_at),
        )
        session.add(event)
        session.flush()
    elif (
        event.owner_public_id != verified.owner_public_id
        or event.trace_id != task.trace_id
        or event.object_id != version.id
        or _canonical(event.payload or {}) != _canonical(payload)
        or event.occurred_at != _naive_utc(feedback.occurred_at)
    ):
        raise M2FeedbackError("idempotency_conflict", "feedback key is bound to different content")

    user = session.query(DBUser).filter_by(public_id=verified.owner_public_id).one()
    evidence = session.query(DBProfileEvidence).filter_by(id=evidence_id).first()
    if evidence is None:
        evidence = DBProfileEvidence(
            id=evidence_id,
            owner_public_id=verified.owner_public_id,
            legacy_student_id=user.username,
            legacy_key=f"m2-{digest}",
            source_type="m2_learning_feedback",
            source_object_id=event.id,
            features=[
                *verified.target_knowledge_point_ids,
                f"activity:{feedback.activity_type}",
                "single_observation",
            ],
            weight=0.45,
            confidence=0.55 if feedback.accuracy is not None else 0.35,
            evidence_summary=(
                "M2 feedback recorded as one observation; mastery remains unchanged pending additional evidence."
            ),
            observed_at=_naive_utc(feedback.occurred_at),
            status="active",
            evidence_version="m2.feedback.v1",
            trace_id=task.trace_id,
        )
        session.add(evidence)
        session.flush()

    candidates, recommended, confidence = _decision_candidates(feedback)
    decision = session.query(DBDecisionRecord).filter_by(id=decision_id).first()
    if decision is None:
        snapshot = session.query(DBProfileSnapshot).filter_by(id=verified.profile_snapshot_id).one()
        decision = DBDecisionRecord(
            id=decision_id,
            owner_public_id=verified.owner_public_id,
            task_id=task.id,
            profile_snapshot_id=snapshot.id,
            trace_id=task.trace_id,
            decision_type="m2_feedback_path_candidate",
            candidates=candidates,
            rules=["m2.feedback.v1", "single_observation_does_not_establish_mastery"],
            evidence_ids=[event.id, evidence.id, version.id],
            confidence=confidence,
            execution_impact={
                "recommended_candidate": recommended,
                "requires_confirmation": recommended in {
                    "add_prerequisite_microcheck", "advance_after_confirmation"
                },
                "mastery_update": "none",
                "difficulty_match_point": {
                    "accuracy": feedback.accuracy,
                    "help_requests": feedback.help_requests,
                    "self_reported_difficulty": feedback.self_reported_difficulty,
                    "algorithm_version": "m2.feedback.v1",
                },
            },
            user_confirmed=False,
            before_version_id=verified.profile_snapshot_id,
            after_version_id=None,
            status="proposed",
        )
        session.add(decision)
        session.flush()

    if task.status != "completed":
        complete_golden_task(
            session,
            task_id=task.id,
            owner_public_id=verified.owner_public_id,
        )
    manifest, manifest_version, _manifest_created = build_m2_manifest(
        session,
        task_id=task.id,
        context=verified,
    )
    session.flush()
    return M2FeedbackResult(
        learning_event_id=event.id,
        profile_evidence_id=evidence.id,
        decision_id=decision.id,
        manifest_artifact_id=manifest.id,
        manifest_version_id=manifest_version.id,
        task_status=task.status,
        created=created,
    )
