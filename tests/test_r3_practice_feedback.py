from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.competition_demo_seed import seed_competition_demo
from app.database import (
    Base,
    DBAssessmentAttempt,
    DBAssessmentQuestionVersion,
    DBAssessmentReviewCase,
    DBUser,
)
from app.main import app
import app.m5_api as m5_api
from app.m5_workspace import workspace_overview


COURSE_ID = "demo-course-rag-trust-v1"


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def _run(awaitable):
    return asyncio.run(awaitable)


def test_workspace_exercise_uses_canonical_question_without_answer_key():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        payload = workspace_overview(session, current_user=learner, course_id=COURSE_ID)
        exercises = [item for item in payload["learning_objects"] if item["object_type"] == "exercise"]
        assert exercises
        exercise = exercises[0]
        render = exercise["render"]
        assert render["question_version_id"] == exercise["id"]
        assert render["explanation"]
        assert isinstance(render["misconception_tags"], list)
        assert "answer_key" not in render
        assert exercise["context"]["source_ref_ids"]
        assert exercise["evidence_panel"]["ready"] is True
        assert exercise["evidence_panel"]["sources"]
        assert exercise["evidence_panel"]["sources"][0]["source_ref_id"] in exercise["context"]["source_ref_ids"]
    finally:
        session.close()
        engine.dispose()


def test_practice_feedback_is_server_graded_idempotent_and_not_auto_review(monkeypatch):
    engine, session = _session()
    identity = {"user": None}

    async def isolated_run_db_op(operation, *args, **kwargs):
        return operation(session, *args, **kwargs)

    monkeypatch.setattr(m5_api, "run_db_op", isolated_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: identity["user"]
    client = TestClient(app)
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        identity["user"] = learner
        workspace = workspace_overview(session, current_user=learner, course_id=COURSE_ID)
        exercise = next(item for item in workspace["learning_objects"] if item["object_type"] == "exercise")
        version_id = exercise["render"]["question_version_id"]
        canonical_answer = session.get(DBAssessmentQuestionVersion, version_id).answer_key["value"]

        fetched = client.get(f"/api/v1/m5/workspace/exercises/{version_id}")
        assert fetched.status_code == 200, fetched.text
        assert "answer_key" not in fetched.json()

        body = {
            "question_version_id": version_id,
            "idempotency_key": "r3-06-practice-feedback-001",
            "mode": "practice",
            "answer": {"value": not canonical_answer},
        }
        first = client.post("/api/v1/m5/assessment/attempts", json=body)
        assert first.status_code == 201, first.text
        first_payload = first.json()
        assert first_payload["correct"] is False
        assert first_payload["score"] == 0
        assert first_payload["grading"]["grader_type"] == "deterministic"
        assert "answer_key" not in first_payload

        second = client.post("/api/v1/m5/assessment/attempts", json=body)
        assert second.status_code == 201, second.text
        assert second.json()["id"] == first_payload["id"]
        assert second.json()["created"] is False
        assert session.query(DBAssessmentAttempt).filter_by(
            owner_public_id=learner.public_id,
            idempotency_key=body["idempotency_key"],
        ).count() == 1
        assert session.query(DBAssessmentReviewCase).filter_by(
            attempt_id=first_payload["id"],
        ).count() == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close()
        engine.dispose()


def test_workspace_exercise_requires_course_membership(monkeypatch):
    engine, session = _session()
    identity = {"user": None}

    async def isolated_run_db_op(operation, *args, **kwargs):
        return operation(session, *args, **kwargs)

    monkeypatch.setattr(m5_api, "run_db_op", isolated_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: identity["user"]
    client = TestClient(app)
    try:
        seed_competition_demo(session)
        identity["user"] = DBUser(
            public_id="outside-r3-06", username="outside-r3-06", role="student", is_active=True,
        )
        response = client.get("/api/v1/m5/workspace/exercises/demo-assessment-lzz-rag-01-q01-v1")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close()
        engine.dispose()
