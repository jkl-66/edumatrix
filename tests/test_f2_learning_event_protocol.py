from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.database import (
    Base,
    DBAssessmentQuestion,
    DBAssessmentQuestionVersion,
    DBChapter,
    DBCourse,
    DBCourseMembership,
    DBLearningEvent,
    DBProfileEvidence,
    DBSourceDocument,
    DBStudentProfile,
    DBUser,
)
import app.m5_api as m5_api
from app.m5_assessment import record_canonical_attempt_evidence
from app.m5_assessment_core import AttemptInput, record_attempt
from app.m5_learning import (
    LearningEventInput,
    M5LearningError,
    PlanNodeSpec,
    PlanSpec,
    confirm_plan,
    create_plan_draft,
    record_learning_event,
)
from app.migrations import _install_f2_learning_event_protocol
from app.models import ContextResolutionError
from app.schemas import ContextRef


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 12, 2, 30, tzinfo=timezone.utc)


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    owner = DBUser(
        public_id="usr-f2-owner", username="f2-owner", hashed_password="hash", role="student",
    )
    other = DBUser(
        public_id="usr-f2-other", username="f2-other", hashed_password="hash", role="student",
    )
    course = DBCourse(
        id="course-f2-events", owner_public_id=owner.public_id, version="1",
        title="F2 Event Course", visibility="private", status="published", manifest_version="1",
    )
    session.add_all([owner, other, course])
    session.add(DBCourseMembership(
        id="membership-f2-owner", course_id=course.id, user_public_id=owner.public_id,
        role="student", status="active",
    ))
    source = DBSourceDocument(
        id="source-f2-events", course_id=course.id, title="Source", filename="source.md",
        file_format="md", content_hash="a" * 64,
    )
    chapter = DBChapter(
        id="chapter-f2-events", course_id=course.id, source_document_id=source.id,
        stable_key="chapter-1", title="Chapter 1", position=1,
    )
    profile = DBStudentProfile(
        student_id=owner.username, concept_mastery={"gradient_descent": 0.4},
    )
    session.add_all([source, chapter, profile])
    session.flush()
    return session, owner, other, course, chapter, profile


def _activity(key: str, *, event_type: str = "resource_opened", source: str = "frontend", payload=None):
    return LearningEventInput(
        idempotency_key=key,
        event_type=event_type,
        context=ContextRef(userId="usr-f2-owner", courseId="course-f2-events"),
        course_id="course-f2-events",
        object_type="chapter",
        object_id="chapter-f2-events",
        source=source,
        occurred_at=NOW,
        payload=payload or {},
    )


def _question(session, owner, course):
    question = DBAssessmentQuestion(
        id="question-f2-events", owner_public_id=owner.public_id, course_id=course.id,
        question_type="single_choice", origin="manual", status="approved",
    )
    session.add(question)
    session.flush()
    version = DBAssessmentQuestionVersion(
        id="question-version-f2-events", question_id=question.id, version_number=1,
        prompt="Choose B", options=["A", "B"], answer_key={"choice": "B"},
        scoring_rule={"type": "exact"}, content_hash="b" * 64,
        created_by_public_id=owner.public_id,
    )
    session.add(version)
    session.flush()
    question.current_version_id = version.id
    return version


def test_browser_activity_is_not_mastery_evidence_and_fake_strong_evidence_is_rejected():
    session, owner, _, _, _, profile = _session()

    activity, _ = record_learning_event(
        session, owner_public_id=owner.public_id, user=owner,
        trusted_source=False, event=_activity("activity-open-001"),
    )
    assert activity.evidence_status == "none"
    assert activity.mastery_eligible is False
    assert activity.completion_effect == "progress"

    forged, _ = record_learning_event(
        session, owner_public_id=owner.public_id, user=owner, trusted_source=False,
        event=_activity(
            "forged-retest-001",
            event_type="delayed_retest_passed",
            source="backend",
            payload={"correct": True, "delay_hours": 24, "attempt_id": "fake-attempt"},
        ),
    )
    assert forged.source == "frontend"
    assert forged.evidence_status == "rejected"
    assert forged.mastery_eligible is False
    assert forged.completion_effect == "none"
    assert session.query(DBProfileEvidence).count() == 0
    assert profile.concept_mastery == {"gradient_descent": 0.4}


def test_server_graded_correct_and_wrong_attempts_create_idempotent_evidence_without_mastery_write():
    session, owner, _, course, _, profile = _session()
    version = _question(session, owner, course)
    plan, _, _ = create_plan_draft(
        session,
        owner_public_id=owner.public_id,
        course_id=course.id,
        title="Assessment path",
        idempotency_key="f2-assessment-plan",
        spec=PlanSpec(
            goal="Submit a graded assessment",
            nodes=(PlanNodeSpec(
                node_key="assessment-node", node_type="assessment",
                target_object_id=version.id, title="Assessment",
                resource_status="existing", estimate_min_minutes=5, estimate_max_minutes=10,
            ),),
        ),
    )
    path = confirm_plan(
        session, plan=plan, owner_public_id=owner.public_id, expected_lock_version=1,
    )

    events = []
    for key, choice, expected in (
        ("attempt-wrong-001", "A", False),
        ("attempt-correct-001", "B", True),
    ):
        attempt, _ = record_attempt(
            session,
            owner_public_id=owner.public_id,
            attempt=AttemptInput(
                question_version_id=version.id,
                idempotency_key=key,
                mode="practice",
                answer={"choice": choice},
            ),
        )
        assert attempt.correct is expected
        result = record_canonical_attempt_evidence(session, attempt=attempt, user=owner)
        event = session.query(DBLearningEvent).filter_by(id=result["event_id"]).one()
        assert event.evidence_status == "accepted"
        assert event.mastery_eligible is True
        assert event.context_ref["attemptId"] == attempt.id
        events.append((attempt, event))

    replay = record_canonical_attempt_evidence(session, attempt=events[0][0], user=owner)
    assert replay["created"] is False
    assert replay["event_id"] == events[0][1].id
    assert session.query(DBLearningEvent).count() == 2
    assert session.query(DBProfileEvidence).count() == 2
    assert path.status == "completed"
    assert profile.concept_mastery == {"gradient_descent": 0.4}


def test_event_idempotency_conflict_and_cross_user_context_are_rejected():
    session, owner, other, _, _, _ = _session()
    original, created = record_learning_event(
        session, owner_public_id=owner.public_id, user=owner,
        trusted_source=False, event=_activity("activity-stable-001"),
    )
    replay, replay_created = record_learning_event(
        session, owner_public_id=owner.public_id, user=owner,
        trusted_source=False, event=_activity("activity-stable-001"),
    )
    assert created is True and replay_created is False and replay.id == original.id

    with pytest.raises(M5LearningError, match="different data"):
        record_learning_event(
            session, owner_public_id=owner.public_id, user=owner, trusted_source=False,
            event=_activity("activity-stable-001", event_type="reading_started"),
        )

    cross_user = _activity("activity-cross-user-001").model_copy(update={
        "context": ContextRef(userId=other.public_id, courseId="course-f2-events"),
    })
    with pytest.raises(ContextResolutionError) as exc:
        record_learning_event(
            session, owner_public_id=owner.public_id, user=owner,
            trusted_source=False, event=cross_user,
        )
    assert exc.value.code == "context_cross_user"


def test_public_event_api_forces_untrusted_source_and_lists_only_the_owner(monkeypatch):
    session, owner, other, _, _, _ = _session()
    identity = {"user": owner}

    async def fake_run_db_op(operation):
        return operation(session)

    monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
    api = FastAPI()
    api.include_router(m5_api.router)
    api.dependency_overrides[get_current_user] = lambda: identity["user"]

    with TestClient(api) as client:
        created = client.post("/api/v1/m5/learning-events", json={
            "idempotency_key": "public-forged-001",
            "event_type": "delayed_retest_passed",
            "context": {"userId": owner.public_id, "courseId": "course-f2-events"},
            "course_id": "course-f2-events",
            "object_type": "chapter",
            "object_id": "chapter-f2-events",
            "source": "backend",
            "occurred_at": NOW.isoformat(),
            "payload": {"correct": True, "delay_hours": 24, "attempt_id": "fake-attempt"},
        })
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["source"] == "frontend"
        assert body["evidence_status"] == "rejected"
        assert body["mastery_eligible"] is False
        assert body["context"]["userId"] == owner.public_id
        assert body["consumption"]["status"] == "processed"
        assert body["aggregation"]["result"]["completed_steps"] == [
            "profile_snapshot", "path_task", "wrong_review", "activity", "dashboard",
        ]

        replayed = client.post(f"/api/v1/m5/learning-events/{body['id']}/process")
        assert replayed.status_code == 200
        assert replayed.json()["aggregation"]["id"] == body["aggregation"]["id"]

        owner_events = client.get("/api/v1/m5/learning-events")
        assert owner_events.status_code == 200
        assert [item["id"] for item in owner_events.json()["items"]] == [body["id"]]

        identity["user"] = other
        assert client.get("/api/v1/m5/learning-events").json()["items"] == []
        forbidden = client.post(f"/api/v1/m5/learning-events/{body['id']}/process")
        assert forbidden.status_code == 403


def test_assessment_attempt_api_records_server_graded_event(monkeypatch):
    session, owner, _, course, _, profile = _session()
    version = _question(session, owner, course)

    async def fake_run_db_op(operation):
        return operation(session)

    monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
    api = FastAPI()
    api.include_router(m5_api.router)
    api.dependency_overrides[get_current_user] = lambda: owner

    with TestClient(api) as client:
        response = client.post("/api/v1/m5/assessment/attempts", json={
            "question_version_id": version.id,
            "idempotency_key": "api-graded-attempt-001",
            "mode": "practice",
            "answer": {"choice": "A"},
        })
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["correct"] is False
        assert body["learning_evidence"]["evidence_status"] == "accepted"

        events = client.get("/api/v1/m5/learning-events", params={"evidence_status": "accepted"})
        assert events.status_code == 200
        assert len(events.json()["items"]) == 1
        event = events.json()["items"][0]
        assert event["event_type"] == "quiz_answered"
        assert event["context"]["attemptId"] == body["id"]
        assert event["payload_summary"]["correct"] is False
        assert profile.concept_mastery == {"gradient_descent": 0.4}


def test_f2_learning_event_migration_is_repeatable_and_enforces_evidence_consistency():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE learning_events ("
            "id VARCHAR(64) PRIMARY KEY, event_type VARCHAR(128) NOT NULL)"
        ))
        connection.execute(text(
            "INSERT INTO learning_events(id,event_type) VALUES ('legacy-event','resource_opened')"
        ))
        _install_f2_learning_event_protocol(connection)
        _install_f2_learning_event_protocol(connection)

        columns = {item["name"] for item in inspect(connection).get_columns("learning_events")}
        assert {
            "action", "context_ref", "evidence_strength", "evidence_status",
            "evidence_reason", "mastery_eligible", "completion_effect", "payload_version",
        }.issubset(columns)
        assert connection.execute(text(
            "SELECT action FROM learning_events WHERE id='legacy-event'"
        )).scalar_one() == "resource_opened"

        with pytest.raises(IntegrityError, match="invalid F2 learning event protocol"):
            connection.execute(text(
                "INSERT INTO learning_events("
                "id,event_type,evidence_strength,evidence_status,mastery_eligible,completion_effect"
                ") VALUES ('bad-event','quiz_answered',0.8,'accepted',0,'complete')"
            ))


def test_frontend_event_service_cannot_submit_strong_evidence_directly():
    service = (ROOT / "frontend/src/services/learningEvents.js").read_text(encoding="utf-8")
    workspace = (ROOT / "frontend/src/views/LearningWorkspace.vue").read_text(encoding="utf-8")

    assert "delayed_retest_passed" not in service
    assert "code_tests_passed" not in service
    assert "createM5LearningEvent" not in workspace
    assert "提交复测通过" not in workspace
    assert "recordBrowserLearningEvent" in workspace
    assert "学习活动已暂存，联网后同步" in workspace
