from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.competition_demo_seed import seed_competition_demo
from app.database import (
    Base, DBAssessmentQuestionVersion, DBLearningEvent, DBMisconceptionReview,
    DBProfileEvidence, DBProfileSnapshot, DBUser,
)
from app.main import app
import app.m5_api as m5_api
from app.m5_workspace import workspace_overview


COURSE_ID = "demo-course-rag-trust-v1"


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def _client(monkeypatch, session, identity):
    async def isolated_run_db_op(operation, *args, **kwargs):
        return operation(session, *args, **kwargs)

    monkeypatch.setattr(m5_api, "run_db_op", isolated_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: identity["user"]
    return TestClient(app)


def _wrong_attempt(client, session, version_id, key):
    canonical = session.get(DBAssessmentQuestionVersion, version_id).answer_key["value"]
    return client.post("/api/v1/m5/assessment/attempts", json={
        "question_version_id": version_id,
        "idempotency_key": key,
        "mode": "practice",
        "answer": {"value": not canonical},
    })


def test_wrong_practice_creates_candidate_but_waits_for_learner_decision(monkeypatch):
    engine, session = _session()
    identity = {"user": None}
    client = _client(monkeypatch, session, identity)
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        identity["user"] = learner
        exercise = next(
            item for item in workspace_overview(session, current_user=learner, course_id=COURSE_ID)["learning_objects"]
            if item["object_type"] == "exercise"
        )
        version_id = exercise["render"]["question_version_id"]
        snapshot_count = session.query(DBProfileSnapshot).filter_by(owner_public_id=learner.public_id).count()

        response = _wrong_attempt(client, session, version_id, "r3-07-candidate-001")
        assert response.status_code == 201, response.text
        review = response.json()["misconception_review"]
        assert review["status"] == "proposed"
        assert review["candidate_evidence"]["evidence_kind"] == "system_candidate"
        assert session.query(DBLearningEvent).filter_by(
            owner_public_id=learner.public_id, event_type="misconception_decided",
        ).count() == 0
        assert session.query(DBProfileSnapshot).filter_by(owner_public_id=learner.public_id).count() == snapshot_count
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close()
        engine.dispose()


def test_learner_accepts_candidate_and_replay_is_idempotent(monkeypatch):
    engine, session = _session()
    identity = {"user": None}
    client = _client(monkeypatch, session, identity)
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        identity["user"] = learner
        attempt = _wrong_attempt(
            client, session, "demo-assessment-lzz-rag-01-q01-v1", "r3-07-accept-001",
        ).json()
        review_id = attempt["misconception_review"]["id"]
        decision = {"decision": "accept", "category": "", "note": "这正是我的理解偏差。"}

        first = client.post(f"/api/v1/m5/assessment/misconceptions/{review_id}/decision", json=decision)
        assert first.status_code == 200, first.text
        payload = first.json()
        assert payload["decision_created"] is True
        assert payload["learning_event"]["event_type"] == "misconception_decided"
        assert payload["learning_event"]["evidence_strength"] == "user_declared"
        assert payload["learning_event"]["mastery_changed"] is False
        assert payload["profile_projection"]["updated"] is True
        assert payload["path_projection"]["status"] == "processed"
        assert payload["teacher_evidence"]["learning_event_id"] == payload["learning_event"]["id"]
        assert session.query(DBProfileEvidence).filter_by(
            owner_public_id=learner.public_id, source_type="misconception_user_statement",
        ).count() == 1

        second = client.post(f"/api/v1/m5/assessment/misconceptions/{review_id}/decision", json=decision)
        assert second.status_code == 200, second.text
        assert second.json()["decision_created"] is False
        assert second.json()["learning_event"]["created"] is False
        assert session.query(DBLearningEvent).filter_by(event_type="misconception_decided").count() == 1

        conflict = client.post(f"/api/v1/m5/assessment/misconceptions/{review_id}/decision", json={
            "decision": "modify", "category": "strategy_error", "note": "different",
        })
        assert conflict.status_code == 409
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close()
        engine.dispose()


def test_modify_restores_from_workspace_and_owner_is_enforced(monkeypatch):
    engine, session = _session()
    identity = {"user": None}
    client = _client(monkeypatch, session, identity)
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        identity["user"] = learner
        version_id = "demo-assessment-lzz-rag-01-q01-v1"
        attempt = _wrong_attempt(client, session, version_id, "r3-07-modify-001").json()
        review_id = attempt["misconception_review"]["id"]
        modified = client.post(f"/api/v1/m5/assessment/misconceptions/{review_id}/decision", json={
            "decision": "modify", "category": "strategy_error", "note": "我是在解题策略上判断错了。",
        })
        assert modified.status_code == 200, modified.text
        assert modified.json()["confirmed_category"] == "strategy_error"

        restored = client.get(f"/api/v1/m5/workspace/exercises/{version_id}")
        assert restored.status_code == 200, restored.text
        latest = restored.json()["latest_attempt"]
        assert latest["misconception_review"]["status"] == "modified"
        assert latest["misconception_review"]["confirmed_category"] == "strategy_error"

        outsider = DBUser(
            public_id="outside-r3-07", username="outside-r3-07",
            hashed_password="not-used", role="student", is_active=True,
        )
        session.add(outsider)
        session.commit()
        identity["user"] = outsider
        forbidden = client.post(f"/api/v1/m5/assessment/misconceptions/{review_id}/decision", json={
            "decision": "modify", "category": "careless", "note": "越权修改",
        })
        assert forbidden.status_code == 403
        assert session.query(DBMisconceptionReview).filter_by(id=review_id).one().confirmed_category == "strategy_error"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close()
        engine.dispose()
