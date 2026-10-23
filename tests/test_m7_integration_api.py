from datetime import datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user, get_password_hash
from app.database import (
    Base,
    DBLearningEvent,
    DBOrganization,
    DBOrganizationMembership,
    DBUser,
)
from app.main import app
import app.m7_api as m7_api


def _fixture():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    admin = DBUser(
        public_id="m7-admin", username="m7-admin",
        hashed_password=get_password_hash("pw"), role="admin", display_name="M7 Admin",
    )
    learner = DBUser(
        public_id="m7-learner", username="m7-learner",
        hashed_password=get_password_hash("pw"), role="student", display_name="M7 Learner",
    )
    outsider = DBUser(
        public_id="m7-outsider", username="m7-outsider",
        hashed_password=get_password_hash("pw"), role="student", display_name="Outsider",
    )
    organization = DBOrganization(id="org-m7-api", name="M7 API Org")
    session.add_all([admin, learner, outsider, organization])
    session.flush()
    session.add_all([
        DBOrganizationMembership(
            organization_id=organization.id, user_public_id=admin.public_id, role="admin"
        ),
        DBOrganizationMembership(
            organization_id=organization.id, user_public_id=learner.public_id, role="learner"
        ),
        DBLearningEvent(
            id="le-m7-api", owner_public_id=learner.public_id, course_id="course-m7",
            event_type="teacher_confirmed", schema_version="m5.learning-event.v1",
            idempotency_key="m7-api-event", source="teacher", trace_id="trace-m7-api",
            object_type="chapter", object_id="chapter-m7", payload={"scope": "completion"},
            occurred_at=datetime(2026, 8, 3, 2, 0),
        ),
        DBLearningEvent(
            id="le-m7-outsider", owner_public_id=outsider.public_id, course_id="course-m7",
            event_type="teacher_confirmed", schema_version="m5.learning-event.v1",
            idempotency_key="m7-api-outsider", source="teacher", trace_id="trace-m7-out",
            object_type="chapter", object_id="chapter-out", payload={},
            occurred_at=datetime(2026, 8, 3, 2, 1),
        ),
    ])
    session.commit()
    return session, admin, learner, organization


def _client(monkeypatch, session, identity):
    async def fake_run_db_op(operation):
        return operation(session)
    monkeypatch.setattr(m7_api, "run_db_op", fake_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: identity["user"]
    return TestClient(app)


def test_m7_api_closes_failure_recovery_loop_without_changing_event(monkeypatch):
    session, admin, _, organization = _fixture()
    identity = {"user": admin}
    client = _client(monkeypatch, session, identity)
    try:
        before = client.get("/api/v1/m7/integrations/workspace")
        assert before.status_code == 200
        truth = before.json()["truthfulness"]
        assert truth["mode"] == "local_simulation"
        assert truth["network_sent"] is False
        assert truth["real_enterprise_connected"] is False
        assert truth["real_lrs_compatibility_verified"] is False
        assert before.json()["selected"]["events"][0]["id"] == "le-m7-api"
        created = client.post("/api/v1/m7/integrations/deliveries", json={
            "organization_id": organization.id,
            "event_id": "le-m7-api",
            "destination_key": "mock-lrs",
        })
        assert created.status_code == 201, created.text
        replay = client.post("/api/v1/m7/integrations/deliveries", json={
            "organization_id": organization.id,
            "event_id": "le-m7-api",
            "destination_key": "mock-lrs",
        })
        assert replay.status_code == 201 and replay.json()["created"] is False
        delivery_id = created.json()["id"]
        failed = client.post(
            f"/api/v1/m7/integrations/deliveries/{delivery_id}/attempt",
            json={"outcome": "failure", "error_code": "mock_lrs_unavailable"},
        )
        assert failed.json()["status"] == "failed"
        delivered = client.post(
            f"/api/v1/m7/integrations/deliveries/{delivery_id}/attempt",
            json={"outcome": "success", "error_code": ""},
        )
        assert delivered.json()["status"] == "delivered"
        event = session.query(DBLearningEvent).filter_by(id="le-m7-api").one()
        assert event.event_type == "teacher_confirmed" and event.payload == {"scope": "completion"}
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_m7_api_rejects_cross_organization_event(monkeypatch):
    session, admin, _, organization = _fixture()
    client = _client(monkeypatch, session, {"user": admin})
    try:
        response = client.post("/api/v1/m7/integrations/deliveries", json={
            "organization_id": organization.id,
            "event_id": "le-m7-outsider",
            "destination_key": "mock-lrs",
        })
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "event_organization_mismatch"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_m7_api_rejects_learner_integration_access(monkeypatch):
    session, _, learner, _ = _fixture()
    client = _client(monkeypatch, session, {"user": learner})
    try:
        response = client.get("/api/v1/m7/integrations/workspace")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_m7_attempt_response_is_serialized_inside_db_operation(monkeypatch):
    session, admin, _, organization = _fixture()
    detached_identity = SimpleNamespace(
        public_id=admin.public_id, role=admin.role, username=admin.username
    )

    async def closing_run_db_op(operation):
        result = operation(session)
        session.expunge_all()
        return result

    monkeypatch.setattr(m7_api, "run_db_op", closing_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: detached_identity
    client = TestClient(app)
    try:
        created = client.post("/api/v1/m7/integrations/deliveries", json={
            "organization_id": organization.id,
            "event_id": "le-m7-api",
            "destination_key": "mock-lrs-detached",
        })
        assert created.status_code == 201, created.text
        response = client.post(
            f"/api/v1/m7/integrations/deliveries/{created.json()['id']}/attempt",
            json={"outcome": "failure", "error_code": "mock_lrs_unavailable"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "failed"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
