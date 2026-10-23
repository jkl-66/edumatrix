from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.competition_demo_seed import seed_competition_demo
from app.database import Base, DBCourse, DBUser
import app.m5_api as m5_api
from app.m5_workspace import M5WorkspaceError, workspace_overview


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def test_workspace_overview_composes_existing_demo_facts():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()

        payload = workspace_overview(session, current_user=learner)

        assert payload["schema_version"] == "r2.workspace-overview.v1"
        assert payload["state"] == "ready"
        assert payload["course"]["id"] == "demo-course-rag-trust-v1"
        assert len(payload["chapters"]) == 12
        assert payload["current_path"]["id"] == "demo-path-lzz-rag-v1"
        assert [item["id"] for item in payload["current_path"]["nodes"]] == [
            "demo-task-lzz-read-01", "demo-task-lzz-lab-01", "demo-task-lzz-quiz-01",
        ]
        assert [item["node_id"] for item in payload["today_tasks"]] == [
            "demo-task-lzz-read-01", "review-1", "review-2",
        ]
        assert all(item["completion_criteria"] for item in payload["today_tasks"])
        assert all(item["recommendation_reason"] for item in payload["today_tasks"])
        assert payload["profile"]["snapshot_id"] == "demo-profile-lzz-v1"
        assert payload["profile"]["mastery"] == 0.58
        assert len(payload["profile"]["weak_knowledge_points"]) == 2
        assert len(payload["recent_artifacts"]) == 3
        assert payload["running_tasks"] == []
        assert payload["review"]["due_count"] == 2
        assert payload["next_action"]["route"] == "/workspace?node_id=demo-task-lzz-read-01"
    finally:
        session.close()
        engine.dispose()


def test_workspace_overview_returns_explainable_empty_state_without_course():
    engine, session = _session()
    try:
        learner = DBUser(
            public_id="workspace-empty-user", username="workspace-empty",
            hashed_password="x", role="student", display_name="Workspace Empty",
        )
        session.add(learner)
        session.commit()

        payload = workspace_overview(session, current_user=learner)

        assert payload["state"] == "course_required"
        assert payload["course"] is None
        assert payload["today_tasks"] == []
        assert payload["next_action"] == {"label": "选择课程", "route": "/knowledge"}
    finally:
        session.close()
        engine.dispose()


def test_workspace_overview_rejects_private_course_from_another_owner():
    engine, session = _session()
    try:
        owner = DBUser(
            public_id="workspace-owner", username="workspace-owner",
            hashed_password="x", role="teacher", display_name="Owner",
        )
        learner = DBUser(
            public_id="workspace-outsider", username="workspace-outsider",
            hashed_password="x", role="student", display_name="Outsider",
        )
        session.add_all([owner, learner])
        session.flush()
        session.add(DBCourse(
            id="workspace-private-course", version="1", title="Private",
            visibility="private", owner_public_id=owner.public_id,
            manifest_version="1", manifest_data={},
        ))
        session.commit()

        try:
            workspace_overview(
                session, current_user=learner, course_id="workspace-private-course",
            )
        except M5WorkspaceError as exc:
            assert exc.code == "workspace_course_forbidden"
        else:
            raise AssertionError("private course access should fail")
    finally:
        session.close()
        engine.dispose()


def test_workspace_api_uses_authenticated_owner_and_registers_main_route(monkeypatch):
    engine, session = _session()
    app = FastAPI()
    app.include_router(m5_api.router)

    async def fake_run_db_op(func, *args, **kwargs):
        return func(session, *args, **kwargs)

    monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
    seed_competition_demo(session)
    learner = session.query(DBUser).filter_by(username="lzz").one()
    app.dependency_overrides[get_current_user] = lambda: learner
    client = TestClient(app)
    try:
        response = client.get("/api/v1/m5/workspace")
        assert response.status_code == 200
        assert response.json()["course"]["id"] == "demo-course-rag-trust-v1"

        session.add(DBCourse(
            id="workspace-api-private", version="1", title="Private API",
            visibility="private", owner_public_id="usr-demo-teacher",
            manifest_version="1", manifest_data={},
        ))
        session.commit()
        forbidden = client.get("/api/v1/m5/workspace", params={"course_id": "workspace-api-private"})
        assert forbidden.status_code == 403
        assert forbidden.json()["detail"]["code"] == "workspace_course_forbidden"

        from app.main import app as main_app

        assert set(main_app.openapi()["paths"]["/api/v1/m5/workspace"]) == {"get"}
    finally:
        client.close()
        session.close()
        engine.dispose()
