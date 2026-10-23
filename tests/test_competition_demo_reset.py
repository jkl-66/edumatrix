from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
import app.competition_demo_api as demo_api
from app.competition_demo_seed import (
    competition_demo_status,
    competition_demo_students,
    reset_competition_demo,
    seed_competition_demo,
)
from app.database import (
    Base,
    DBArtifact,
    DBCourse,
    DBLearningEvent,
    DBPathNode,
    DBProfileSnapshot,
    DBUser,
)


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def test_status_detects_mutation_and_reset_restores_initial_state():
    engine, session = _session()
    try:
        assert competition_demo_status(session).status == "uninitialized"
        seed_competition_demo(session)
        assert competition_demo_status(session).status == "ready"

        node = session.get(DBPathNode, "demo-task-lzz-read-01")
        node.status = "completed"
        artifact = session.get(DBArtifact, "demo-artifact-lzz-note-01")
        artifact.status = "archived"
        profile = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        profile.snapshot = {**profile.snapshot, "mastery": 0.99}
        session.add(DBLearningEvent(
            id="demo-event-lzz-diagnosis-02", owner_public_id=profile.owner_public_id,
            legacy_student_id="lzz", course_id="demo-course-rag-trust-v1",
            event_type="diagnosis_completed", schema_version="competition.demo.learning-event.v1",
            idempotency_key="competition-demo-v1:demo-event-lzz-diagnosis-02",
            source="api", trace_id="trace-test", object_type="course",
            object_id="demo-course-rag-trust-v1",
            payload={"demo_scope": "competition-demo-v1", "journey": True},
        ))
        session.commit()

        degraded = competition_demo_status(session)
        assert degraded.status == "degraded"
        assert degraded.reset_required is True
        assert "path_node_state" in degraded.issues
        assert "learning_event_set" in degraded.issues

        reset = reset_competition_demo(session)
        assert reset.before_status == "degraded"
        assert reset.after_status == "ready"
        assert competition_demo_status(session).status == "ready"
        assert session.get(DBPathNode, "demo-task-lzz-read-01").status == "in_progress"
        assert session.get(DBArtifact, "demo-artifact-lzz-note-01").status == "approved"
        assert session.get(DBProfileSnapshot, "demo-profile-lzz-v1").snapshot["mastery"] == 0.58
        assert session.get(DBLearningEvent, "demo-event-lzz-diagnosis-02") is None

        second = reset_competition_demo(session)
        assert second.before_status == "ready"
        assert second.after_status == "ready"
        assert second.deleted_counts == {}
    finally:
        session.close()
        engine.dispose()


def test_reset_preserves_non_demo_rows_and_never_deletes_bound_users():
    engine, session = _session()
    try:
        session.add(DBUser(
            public_id="usr-existing-lzz", username="lzz", hashed_password="owned-hash",
            role="student", display_name="用户自有账号",
        ))
        session.add(DBUser(
            public_id="usr-non-demo", username="outside", hashed_password="outside-hash",
            role="student", display_name="外部用户",
        ))
        session.add(DBCourse(
            id="course-non-demo", version="1", title="非演示课程",
            manifest_version="1", manifest_data={"scope": "non-demo"},
        ))
        session.commit()
        session.add(DBLearningEvent(
            id="event-non-demo", owner_public_id="usr-non-demo", legacy_student_id="outside",
            course_id="course-non-demo", event_type="resource_opened", schema_version="1",
            idempotency_key="outside:event", source="api", trace_id="outside",
            object_type="course", object_id="course-non-demo", payload={"scope": "non-demo"},
        ))
        session.commit()

        seed_competition_demo(session)
        session.get(DBPathNode, "demo-task-lzz-read-01").status = "completed"
        session.commit()
        reset_competition_demo(session)

        bound = session.query(DBUser).filter_by(username="lzz").one()
        assert bound.public_id == "usr-existing-lzz"
        assert bound.display_name == "用户自有账号"
        assert bound.hashed_password == "owned-hash"
        assert session.get(DBUser, session.query(DBUser).filter_by(public_id="usr-non-demo").one().id) is not None
        assert session.get(DBCourse, "course-non-demo").title == "非演示课程"
        assert session.get(DBLearningEvent, "event-non-demo").payload == {"scope": "non-demo"}
    finally:
        session.close()
        engine.dispose()


def test_competition_demo_teacher_scope_is_exactly_fifteen_students():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        students = competition_demo_students(session)
        assert len(students) == 15
        assert {item.username for item in students} == {"lzz", *(f"demo-stu-{index:03d}" for index in range(2, 16))}
    finally:
        session.close()
        engine.dispose()


def test_admin_api_initializes_and_resets_while_non_admin_is_forbidden(monkeypatch):
    engine, session = _session()
    app = FastAPI()
    app.include_router(demo_api.router)

    async def fake_run_db_op(func, *args, **kwargs):
        return func(session, *args, **kwargs)

    monkeypatch.setattr(demo_api, "run_db_op", fake_run_db_op)
    admin = DBUser(public_id="api-admin", username="api-admin", hashed_password="x", role="admin")
    student = DBUser(public_id="api-student", username="api-student", hashed_password="x", role="student")
    app.dependency_overrides[get_current_user] = lambda: admin
    client = TestClient(app)
    try:
        assert client.get("/api/v1/competition-demo/status").json()["status"] == "uninitialized"
        initialized = client.post("/api/v1/competition-demo/initialize")
        assert initialized.status_code == 200
        assert initialized.json()["status"]["status"] == "ready"
        assert initialized.json()["cohort_student_count"] == 15

        session.get(DBPathNode, "demo-task-lzz-read-01").status = "completed"
        session.commit()
        reset = client.post("/api/v1/competition-demo/reset")
        assert reset.status_code == 200
        assert reset.json()["status"]["status"] == "ready"

        app.dependency_overrides[get_current_user] = lambda: student
        forbidden = client.post("/api/v1/competition-demo/reset")
        assert forbidden.status_code == 403
        assert forbidden.json()["detail"]["code"] == "competition_demo_admin_required"
    finally:
        client.close()
        session.close()
        engine.dispose()


def test_main_application_registers_competition_demo_admin_routes():
    from app.main import app

    paths = app.openapi()["paths"]
    assert set(paths["/api/v1/competition-demo/status"]) == {"get"}
    assert set(paths["/api/v1/competition-demo/initialize"]) == {"post"}
    assert set(paths["/api/v1/competition-demo/reset"]) == {"post"}
