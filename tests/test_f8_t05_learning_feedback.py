from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.database import (
    Base,
    DBCourse,
    DBKnowledgePoint,
    DBLearningEvent,
    DBLearningEventConsumption,
    DBStudentProfile,
    DBUser,
)
from app.learning_aggregation import (
    AGGREGATION_STEPS,
    AGGREGATION_VIEW_CONTRACT,
    _STEP_HANDLERS,
    aggregate_learning_event,
    learning_feedback_payload,
)
import app.m5_api as m5_api
from models import DIMENSION_LABELS


OWNER = "usr-f8-t05-owner"
OTHER = "usr-f8-t05-other"
COURSE = "course-f8-t05"
POINT = "kp-f8-t05"
BASE_TIME = datetime(2026, 8, 12, 9, 30)


def _database():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    owner = DBUser(
        public_id=OWNER,
        username="f8-t05-owner",
        hashed_password="hash",
        role="student",
    )
    other = DBUser(
        public_id=OTHER,
        username="f8-t05-other",
        hashed_password="hash",
        role="student",
    )
    session.add_all([
        owner,
        other,
        DBCourse(
            id=COURSE,
            owner_public_id=OWNER,
            version="1",
            title="F8 feedback course",
            visibility="private",
            status="published",
            manifest_version="1",
        ),
        DBKnowledgePoint(
            id=POINT,
            domain_pack="machine-learning",
            code="f8_feedback",
            version="1",
            title="梯度下降反馈",
        ),
        DBStudentProfile(student_id=owner.username, concept_mastery={"梯度下降反馈": 0.4}),
    ])
    session.commit()
    return factory, session, owner, other


def _event(event_type: str, *, event_id: str | None = None) -> DBLearningEvent:
    payloads = {
        "quiz_answered": {"score": 0.8, "correct": True},
        "code_tests_passed": {"passed_tests": 4, "total_tests": 4},
        "interactive_model_observation_submitted": {
            "observation": "学习率过大时损失函数会在最优点两侧振荡。",
            "hint_count": 0,
        },
        "feynman_submitted": {"rubric_score": 0.82},
        "formal_exam_submitted": {
            "knowledge_point_scores": [{"knowledge_point_id": POINT, "score": 0.75}],
            "item_results": [],
        },
        "review_completed": {"recall_score": 0.9},
    }
    suffix = event_id or event_type
    context = {"courseId": COURSE, "knowledgePointId": POINT}
    if event_type == "interactive_model_observation_submitted":
        context = {"courseId": COURSE, "knowledge_point_id": POINT}
    return DBLearningEvent(
        id=f"event-{suffix}",
        owner_public_id=OWNER,
        course_id=COURSE,
        event_type=event_type,
        schema_version="m5.learning-event.v2",
        idempotency_key=f"f8-t05-{suffix}",
        source="backend",
        trace_id=f"trace-{suffix}",
        object_type="knowledge_point",
        object_id=POINT,
        action="trusted_completion",
        context_ref=context,
        evidence_strength=0.7,
        evidence_status="accepted",
        evidence_reason="trusted F8-T05 test evidence",
        mastery_eligible=True,
        completion_effect="complete",
        payload_version="1",
        payload=payloads[event_type],
        occurred_at=BASE_TIME,
    )


@pytest.mark.parametrize(
    "event_type",
    [
        "quiz_answered",
        "code_tests_passed",
        "interactive_model_observation_submitted",
        "feynman_submitted",
        "formal_exam_submitted",
        "review_completed",
    ],
)
def test_all_trusted_completion_types_publish_one_six_view_feedback_version(event_type):
    _, session, _, _ = _database()
    event = _event(event_type)
    session.add(event)
    session.flush()

    consumption = aggregate_learning_event(session, event=event)
    result = consumption.result
    feedback = learning_feedback_payload(event, consumption)

    assert consumption.status == "processed"
    assert result["completed_steps"] == list(AGGREGATION_STEPS)
    assert result["affectedViews"] == list(AGGREGATION_VIEW_CONTRACT)
    assert set(result["expectedSnapshots"]) == set(AGGREGATION_VIEW_CONTRACT)
    assert set(result["snapshots"]) == set(AGGREGATION_VIEW_CONTRACT)
    assert result["consistencyToken"]
    assert len(result["consistencyToken"]) == 64
    assert all(item["status"] == "completed" for item in feedback["views"])
    assert all(item["snapshotVersion"] for item in feedback["views"])
    assert feedback["consistencyToken"] == result["consistencyToken"]
    assert feedback["completedCount"] == feedback["totalCount"] == 6
    assert feedback["nextDaySchedule"][0]["date"] == "2026-08-13"
    assert feedback["nextDaySchedule"][0]["knowledge_point_id"] == POINT
    assert feedback["nextDaySchedule"][0]["source_event_id"] == event.id


def test_partial_failure_survives_session_restart_and_replays_only_the_failed_tail(monkeypatch):
    factory, session, _, _ = _database()
    event = _event("quiz_answered", event_id="recover")
    session.add(event)
    session.flush()
    original = _STEP_HANDLERS["wrong_review"]

    def fail_wrong_review(_session, _event):
        raise RuntimeError("injected wrong/review failure")

    monkeypatch.setitem(_STEP_HANDLERS, "wrong_review", fail_wrong_review)
    with pytest.raises(RuntimeError, match="injected wrong/review failure"):
        aggregate_learning_event(session, event=event)

    failed = session.query(DBLearningEventConsumption).filter_by(
        learning_event_id=event.id,
        consumer="learning_aggregation",
    ).one()
    failed_feedback = learning_feedback_payload(event, failed)
    assert failed_feedback["recoverable"] is True
    assert failed_feedback["consistencyToken"] is None
    assert {item["id"]: item["status"] for item in failed_feedback["views"]} == {
        "dashboard": "pending",
        "profile": "completed",
        "path": "completed",
        "wrong_questions": "failed",
        "review": "failed",
        "history": "pending",
    }
    session.close()

    monkeypatch.setitem(_STEP_HANDLERS, "wrong_review", original)
    resumed_session = factory()
    resumed_event = resumed_session.get(DBLearningEvent, event.id)
    resumed = aggregate_learning_event(resumed_session, event=resumed_event)
    token = resumed.result["consistencyToken"]
    duplicate = aggregate_learning_event(resumed_session, event=resumed_event)

    assert resumed.status == "processed"
    assert resumed.attempt == 2
    assert duplicate.id == resumed.id
    assert duplicate.attempt == 2
    assert duplicate.result["consistencyToken"] == token
    assert resumed_session.query(DBLearningEvent).count() == 1
    assert resumed_session.query(DBLearningEventConsumption).count() == 1


def test_latest_feedback_endpoint_is_owner_and_course_scoped_and_read_only(monkeypatch):
    _, session, owner, other = _database()
    event = _event("review_completed", event_id="latest")
    session.add(event)
    session.flush()
    aggregate_learning_event(session, event=event)
    before_events = session.query(DBLearningEvent).count()

    async def fake_run_db_op(operation):
        return operation(session)

    identity = {"user": owner}
    monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
    app = FastAPI()
    app.include_router(m5_api.router)
    app.dependency_overrides[get_current_user] = lambda: identity["user"]

    with TestClient(app) as client:
        response = client.get(f"/api/v1/m5/learning-feedback/latest?course_id={COURSE}")
        assert response.status_code == 200
        feedback = response.json()["feedback"]
        assert feedback["event"]["id"] == event.id
        assert feedback["event"]["courseId"] == COURSE
        assert feedback["consistencyToken"]

        wrong_course = client.get("/api/v1/m5/learning-feedback/latest?course_id=another-course")
        assert wrong_course.status_code == 200
        assert wrong_course.json() == {"feedback": None}

        identity["user"] = other
        other_owner = client.get(f"/api/v1/m5/learning-feedback/latest?course_id={COURSE}")
        assert other_owner.status_code == 200
        assert other_owner.json() == {"feedback": None}

    assert session.query(DBLearningEvent).count() == before_events


def test_pending_feedback_without_consumption_still_declares_the_six_view_contract():
    _, session, _, _ = _database()
    event = _event("quiz_answered", event_id="pending")
    session.add(event)
    session.flush()

    feedback = learning_feedback_payload(event, None)

    assert feedback["status"] == "pending"
    assert feedback["recoverable"] is True
    assert feedback["completedCount"] == 0
    assert feedback["totalCount"] == 6
    assert set(feedback["expectedSnapshots"]) == set(AGGREGATION_VIEW_CONTRACT)
    assert all(item["status"] == "pending" for item in feedback["views"])
    for view_id, expected in feedback["expectedSnapshots"].items():
        contract = AGGREGATION_VIEW_CONTRACT[view_id]
        assert expected == {
            "label": contract["label"],
            "route": contract["route"],
            "step": contract["step"],
        }


def _prime_behavior_profile(session):
    profile = session.query(DBStudentProfile).filter_by(student_id="f8-t05-owner").one()
    profile.focus_level = 0.7
    profile.cognitive_load = 0.42
    profile.frustration_index = 0.08
    profile.dimension_states = {
        key: {
            "key": key,
            "label": label,
            "score": 0.55,
            "confidence": 0.58,
            "status": "入学画像基线",
            "evidence_count": 1,
            "evidence_fragments": ["入学画像对话已记录。"],
            "recommended_interventions": ["根据后续学习证据继续调整。"],
            "last_updated": "2026-08-12T08:00:00Z",
        }
        for key, label in DIMENSION_LABELS.items()
    }
    session.flush()
    return profile


def test_wrong_then_correct_replays_multidimensional_profile_with_recovery_and_evidence():
    _, session, _, _ = _database()
    profile = _prime_behavior_profile(session)
    wrong = _event("quiz_answered", event_id="wrong")
    wrong.payload = {"score": 0.0, "correct": False, "confidence": 0.95}
    session.add(wrong)
    session.flush()
    aggregate_learning_event(session, event=wrong)
    session.refresh(profile)
    wrong_state = (profile.focus_level, profile.cognitive_load, profile.frustration_index)

    correct = _event("quiz_answered", event_id="correct")
    correct.payload = {"score": 1.0, "correct": True, "confidence": 0.9}
    correct.occurred_at = BASE_TIME + timedelta(minutes=5)
    session.add(correct)
    session.flush()
    consumption = aggregate_learning_event(session, event=correct)
    session.refresh(profile)

    assert set(profile.dimension_states) == set(DIMENSION_LABELS)
    assert profile.cognitive_load < wrong_state[1]
    assert profile.frustration_index < wrong_state[2]
    assert profile.focus_level > wrong_state[0]
    assert [item["event_type"] for item in profile.mental_state_history[-2:]] == [
        "quiz_answered", "quiz_answered",
    ]
    assert profile.mental_state_history[-2]["frustration"] > profile.mental_state_history[-1]["frustration"]
    assert "测验题" in profile.dimension_states["knowledge_mastery"]["evidence_fragments"][-1]
    assert profile.dimension_states["metacognition"]["score"] != 0.55
    profile_step = consumption.result["steps"]["profile_snapshot"]
    assert profile_step["behavior_baseline_snapshot_id"]
    assert profile_step["behavior_after"]["dimension_states"] == profile.dimension_states

    stable_state = (
        profile.focus_level,
        profile.cognitive_load,
        profile.frustration_index,
        profile.dimension_states,
        profile.mental_state_history,
    )
    aggregate_learning_event(session, event=correct, processor_version="profile-replay-check")
    session.refresh(profile)
    assert (
        profile.focus_level,
        profile.cognitive_load,
        profile.frustration_index,
        profile.dimension_states,
        profile.mental_state_history,
    ) == stable_state


def test_non_mastery_browsing_does_not_change_behavior_profile_projection():
    _, session, _, _ = _database()
    profile = _prime_behavior_profile(session)
    trusted = _event("code_tests_passed", event_id="trusted")
    session.add(trusted)
    session.flush()
    aggregate_learning_event(session, event=trusted)
    session.refresh(profile)
    before = (
        profile.focus_level,
        profile.cognitive_load,
        profile.frustration_index,
        profile.dimension_states,
        profile.mental_state_history,
    )
    browsing = DBLearningEvent(
        id="event-resource-opened",
        owner_public_id=OWNER,
        course_id=COURSE,
        event_type="resource_opened",
        schema_version="m5.learning-event.v2",
        idempotency_key="f8-t05-resource-opened",
        source="frontend",
        trace_id="trace-resource-opened",
        object_type="artifact",
        object_id="artifact-reading-only",
        action="resource.opened",
        context_ref={"courseId": COURSE, "knowledgePointId": POINT},
        evidence_strength=0.0,
        evidence_status="none",
        evidence_reason="普通浏览不作为掌握证据",
        mastery_eligible=False,
        completion_effect="progress",
        payload_version="1",
        payload={},
        occurred_at=BASE_TIME + timedelta(minutes=10),
    )
    session.add(browsing)
    session.flush()
    aggregate_learning_event(session, event=browsing)
    session.refresh(profile)

    assert (
        profile.focus_level,
        profile.cognitive_load,
        profile.frustration_index,
        profile.dimension_states,
        profile.mental_state_history,
    ) == before


def test_mixed_formal_exam_keeps_weakness_and_records_nuanced_mental_state():
    _, session, _, _ = _database()
    profile = _prime_behavior_profile(session)
    exam = _event("formal_exam_submitted", event_id="mixed-formal")
    exam.payload = {
        "graded": True,
        "attempt_id": "sitting-mixed-formal",
        "score": 0.5,
        "knowledge_point_scores": [{"knowledge_point_id": POINT, "score": 0.5}],
        "item_results": [
            {"question_version_id": "qv-1", "knowledge_point_id": POINT, "score": 1.0, "correct": True},
            {"question_version_id": "qv-2", "knowledge_point_id": POINT, "score": 0.0, "correct": False},
        ],
    }
    session.add(exam)
    session.flush()
    aggregate_learning_event(session, event=exam)
    session.refresh(profile)

    assert "梯度下降反馈" in profile.weak_points
    assert profile.frustration_index > 0.08
    assert profile.cognitive_load > 0.42
    assert profile.mental_state_history[-1]["event_label"] == "智能组卷"
    assert profile.dimension_states["misconception_profile"]["status"] == "仍有错误证据需复习"
    assert "智能组卷" in profile.dimension_states["knowledge_mastery"]["evidence_fragments"][-1]
    assert "错误证据" in profile.dimension_states["misconception_profile"]["evidence_fragments"][-1]
    assert "认知负荷" in profile.dimension_states["cognitive_processing"]["evidence_fragments"][-1]


def test_forced_demo_modalities_do_not_rewrite_interaction_preference_or_learning_context():
    _, session, _, _ = _database()
    profile = _prime_behavior_profile(session)
    baseline_interaction = profile.dimension_states["interaction_preference"].copy()
    baseline_context = profile.dimension_states["learning_context"].copy()
    event = _event("code_tests_passed", event_id="preference-neutral")
    session.add(event)
    session.flush()

    aggregate_learning_event(session, event=event)
    session.refresh(profile)

    for key, baseline in (
        ("interaction_preference", baseline_interaction),
        ("learning_context", baseline_context),
    ):
        state = profile.dimension_states[key]
        assert state["score"] == baseline["score"]
        assert state["evidence_count"] == baseline["evidence_count"]
        assert state["evidence_fragments"] == baseline["evidence_fragments"]
