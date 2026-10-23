from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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
    AGGREGATION_PROCESSOR_VERSION,
    _next_day_schedule,
    aggregate_learning_event,
)
from app.m5_learning import LearningEventInput, classify_learning_event
from app.profile_summary import build_personal_activity


ROOT = Path(__file__).resolve().parents[1]
OWNER = "usr-p1-b22-owner"
COURSE = "course-p1-b22"
POINT_A = "kp-p1-b22-a"
POINT_B = "kp-p1-b22-b"
BASE_TIME = datetime(2026, 8, 25, 1, 0)


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    owner = DBUser(
        public_id=OWNER,
        username="p1-b22-owner",
        hashed_password="hash",
        role="student",
    )
    course = DBCourse(
        id=COURSE,
        owner_public_id=OWNER,
        version="1",
        title="P1-B22 事件反馈课程",
        visibility="private",
        status="published",
        manifest_version="1",
    )
    session.add_all([
        owner,
        course,
        DBKnowledgePoint(
            id=POINT_A,
            domain_pack="p1-b22",
            code="point_a",
            version="1",
            title="知识点 A",
        ),
        DBKnowledgePoint(
            id=POINT_B,
            domain_pack="p1-b22",
            code="point_b",
            version="1",
            title="知识点 B",
        ),
        DBStudentProfile(student_id=owner.username, concept_mastery={"知识点 A": 0.2, "知识点 B": 0.2}),
    ])
    session.commit()
    return engine, session, owner


def _event(
    event_type: str,
    event_id: str,
    *,
    point_id: str | None = POINT_A,
    payload: dict | None = None,
    context: dict | None = None,
) -> DBLearningEvent:
    context = context or {"courseId": COURSE, "knowledgePointId": point_id}
    return DBLearningEvent(
        id=event_id,
        owner_public_id=OWNER,
        course_id=COURSE,
        event_type=event_type,
        schema_version="m5.learning-event.v2",
        idempotency_key=f"p1-b22-{event_id}",
        source="backend",
        trace_id=f"trace-{event_id}",
        object_type="knowledge_point",
        object_id=point_id or event_id,
        action="trusted_completion",
        context_ref=context,
        evidence_strength=0.8,
        evidence_status="accepted",
        evidence_reason="server accepted evidence",
        mastery_eligible=True,
        completion_effect="complete",
        payload_version="1",
        payload=payload or {},
        occurred_at=BASE_TIME,
    )


def test_all_accepted_event_families_feed_their_knowledge_points_and_observations():
    engine, session, _ = _session()
    try:
        rows = [
            _event("quiz_answered", "quiz", payload={"score": 0.8, "correct": True}),
            _event(
                "code_tests_passed",
                "code",
                point_id=POINT_B,
                payload={"passed_count": 4, "total_count": 4, "test_scope": "required", "run_id": "run-code"},
            ),
            _event(
                "interactive_model_observation_submitted",
                "model",
                context={"courseId": COURSE, "knowledge_point_id": POINT_A},
                payload={"observation": "参数变化会影响召回与延迟"},
            ),
            _event(
                "interactive_experiment_completed",
                "experiment",
                point_id=POINT_B,
                payload={"passed_checks": 3, "total_checks": 4},
            ),
            _event("feynman_submitted", "feynman", payload={"rubric_score": 0.7}),
            _event(
                "formal_exam_submitted",
                "exam",
                point_id=None,
                context={"courseId": COURSE},
                payload={
                    "knowledge_point_scores": [
                        {"knowledge_point_id": POINT_A, "score": 0.9},
                        {"knowledge_point_id": POINT_B, "score": 0.6},
                    ],
                },
            ),
            _event("review_completed", "review", payload={"recall_score": 0.85}),
            _event("delayed_retest_passed", "retest", payload={"correct": True}),
            _event("teacher_confirmed", "teacher", point_id=POINT_B, payload={"score": 0.8}),
        ]
        for row in rows:
            session.add(row)
            session.flush()
            aggregate_learning_event(session, event=row)

        profile = session.query(DBStudentProfile).filter_by(student_id="p1-b22-owner").one()
        assert profile.concept_mastery["知识点 A"] != 0.2
        assert profile.concept_mastery["知识点 B"] != 0.2
        assert profile.knowledge_traces["知识点 A"]["knowledge_point_id"] == POINT_A
        assert profile.knowledge_traces["知识点 B"]["knowledge_point_id"] == POINT_B
    finally:
        session.close()
        engine.dispose()


def test_interactive_model_has_the_same_canonical_event_classification():
    event = LearningEventInput(
        idempotency_key="p1-b22-model-input-001",
        event_type="interactive_model_observation_submitted",
        course_id=COURSE,
        object_type="interactive_model",
        object_id="model-1",
        source="interactive_model",
        payload={"observation": "参数变化会影响召回与延迟"},
    )
    classification = classify_learning_event(event, trusted_source=True)
    assert classification.evidence_status == "accepted"
    assert classification.mastery_eligible is True


def test_history_feedback_exposes_knowledge_points_and_specific_non_evidence_reason():
    engine, session, owner = _session()
    try:
        accepted = _event("quiz_answered", "history-accepted", payload={"score": 0.8, "correct": True})
        browser = DBLearningEvent(
            id="history-browser",
            owner_public_id=OWNER,
            course_id=COURSE,
            event_type="resource_opened",
            schema_version="m5.learning-event.v2",
            idempotency_key="p1-b22-history-browser",
            source="frontend",
            trace_id="trace-history-browser",
            object_type="knowledge_point",
            object_id=POINT_A,
            action="resource.opened",
            context_ref={"courseId": COURSE, "knowledgePointId": POINT_A},
            evidence_strength=0.0,
            evidence_status="none",
            evidence_reason="仅打开课程资源，未提交可判定结果",
            mastery_eligible=False,
            completion_effect="progress",
            payload={},
            occurred_at=BASE_TIME,
        )
        session.add_all([accepted, browser])
        session.flush()
        aggregate_learning_event(session, event=accepted)
        session.commit()

        result = build_personal_activity(
            session,
            current_user=owner,
            course_id=COURSE,
            days=30,
            now=BASE_TIME,
        )
        items = {item["id"]: item for item in result["activity"]["items"]}
        accepted_item = items[accepted.id]
        browser_item = items[browser.id]
        assert accepted_item["evidence"]["status"] == "accepted"
        assert accepted_item["evidence"]["knowledgePointIds"] == [POINT_A]
        assert accepted_item["evidence"]["observations"][0]["value"] == pytest.approx(0.8)
        assert accepted_item["evidence"]["aggregationStatus"] == "processed"
        assert "知识点 A" in accepted_item["evidence"]["label"]
        assert browser_item["evidence"]["status"] == "none"
        assert browser_item["evidence"]["masteryEligible"] is False
        assert browser_item["evidence"]["reason"] == "仅打开课程资源，未提交可判定结果"
        assert browser_item["evidence"]["label"] != "学习记录，不直接改变掌握度"
    finally:
        session.close()
        engine.dispose()


def test_accepted_event_without_observation_does_not_get_a_fixed_half_schedule():
    engine, session, _ = _session()
    try:
        event = _event(
            "interactive_model_observation_submitted",
            "no-observation",
            payload={},
        )
        session.add(event)
        session.flush()
        assert _next_day_schedule(session, event) == []
    finally:
        session.close()
        engine.dispose()


def test_history_view_keeps_read_only_scope_and_exposes_feedback_fields():
    view = (ROOT / "frontend/src/views/History.vue").read_text(encoding="utf-8")
    for marker in (
        "查看、筛选和展开历史不会改变掌握度、路径或复习安排。",
        "selectedItem.evidence?.label",
        "selectedItem.evidence?.reason",
        "selectedItem.evidence?.knowledgePointTitles",
        "selectedItem.evidence?.aggregationStatus",
    ):
        assert marker in view
