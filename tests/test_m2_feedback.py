from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.database import (
    DBArtifact,
    DBArtifactVersion,
    DBDecisionRecord,
    DBLearningEvent,
    DBProfileEvidence,
)
from app.m2_feedback import M2FeedbackError, M2LearningFeedback, record_m2_feedback
from app.m2_manifest import M2BundleManifest, build_m2_manifest
from app.m2_quality import run_m2_quality_checks
from app.m2_tasks import complete_golden_task, start_task_step
from tests.test_m2_artifacts import _seeded_session
from tests.test_m2_quality import _generate_three


def _quality_passed_task(session, baseline, task):
    context = baseline.generation_context
    _generate_three(session, baseline, task)
    start_task_step(
        session, task_id=task.id, owner_public_id=context.owner_public_id, sequence=4
    )
    assert run_m2_quality_checks(session, task_id=task.id, context=context).passed
    return context


def test_single_feedback_records_evidence_and_candidate_without_claiming_mastery():
    engine, session, baseline, task = _seeded_session()
    context = _quality_passed_task(session, baseline, task)
    try:
        manifest, first_manifest_version, _ = build_m2_manifest(
            session, task_id=task.id, context=context
        )
        quiz = session.query(DBArtifact).filter_by(
            creating_task_id=task.id, artifact_type="tiered_quiz"
        ).one()
        feedback = M2LearningFeedback(
            idempotency_key="m2-feedback-attempt-001",
            artifact_version_id=quiz.current_version_id,
            activity_type="quiz_attempt",
            completed=True,
            accuracy=0.67,
            help_requests=2,
            self_reported_difficulty=4,
            observed_seconds=780,
            occurred_at=datetime(2026, 7, 26, 4, 0, tzinfo=timezone.utc),
            note="我能定位来源，但拆分原子事实仍需提示。",
        )
        result = record_m2_feedback(
            session, task_id=task.id, context=context, feedback=feedback
        )
        assert result.created is True
        assert result.feedback_state == "recorded"
        assert result.mastery_state == "unchanged_pending_evidence"
        assert result.task_status == "completed"
        assert result.manifest_version_id != first_manifest_version.id

        event = session.query(DBLearningEvent).filter_by(id=result.learning_event_id).one()
        assert event.payload["mastery_state"] == "unchanged_pending_evidence"
        assert "note" not in event.payload
        evidence = session.query(DBProfileEvidence).filter_by(id=result.profile_evidence_id).one()
        assert evidence.confidence < 1.0
        assert "mastery remains unchanged" in evidence.evidence_summary
        decision = session.query(DBDecisionRecord).filter_by(id=result.decision_id).one()
        assert decision.status == "proposed"
        assert decision.user_confirmed is False
        assert decision.execution_impact["mastery_update"] == "none"
        final_manifest = M2BundleManifest.model_validate_json(
            session.query(DBArtifactVersion).filter_by(id=result.manifest_version_id).one().content
        )
        assert final_manifest.status == "completed"
        assert final_manifest.learning_event_ids == [event.id]
        assert final_manifest.profile_evidence_ids == [evidence.id]
        assert final_manifest.decision_ids == [decision.id]

        replay = record_m2_feedback(
            session, task_id=task.id, context=context, feedback=feedback
        )
        assert replay.created is False
        assert replay.manifest_version_id == result.manifest_version_id
        assert session.query(DBLearningEvent).filter_by(trace_id=task.trace_id).count() == 1
        assert session.query(DBProfileEvidence).filter_by(trace_id=task.trace_id).count() == 1
        assert session.query(DBDecisionRecord).filter_by(task_id=task.id).count() == 1
        assert session.query(DBArtifactVersion).filter_by(artifact_id=manifest.id).count() == 2
    finally:
        session.close()
        engine.dispose()


def test_feedback_idempotency_conflict_and_missing_feedback_completion_gate():
    engine, session, baseline, task = _seeded_session()
    context = _quality_passed_task(session, baseline, task)
    try:
        with pytest.raises(ValueError) as raised:
            complete_golden_task(session, task_id=task.id, owner_public_id=context.owner_public_id)
        assert getattr(raised.value, "code", "") == "task_feedback_missing"

        lesson = session.query(DBArtifact).filter_by(
            creating_task_id=task.id, artifact_type="lesson"
        ).one()
        first = M2LearningFeedback(
            idempotency_key="m2-feedback-conflict-001",
            artifact_version_id=lesson.current_version_id,
            activity_type="lesson_review",
            completed=True,
            accuracy=None,
            occurred_at=datetime(2026, 7, 26, 5, 0, tzinfo=timezone.utc),
        )
        record_m2_feedback(session, task_id=task.id, context=context, feedback=first)
        changed = first.model_copy(update={"help_requests": 1})
        with pytest.raises(M2FeedbackError) as raised:
            record_m2_feedback(session, task_id=task.id, context=context, feedback=changed)
        assert raised.value.code == "idempotency_conflict"
    finally:
        session.close()
        engine.dispose()
