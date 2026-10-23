from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.m7_api as m7_api
from app.auth import get_current_user, get_password_hash
from app.database import (
    Base, DBCmi5Session, DBCmi5SessionEvent, DBIntegrationDelivery,
    DBIntegrationDeliveryEvent, DBLearningEvent, DBLocalLRSStatement,
    DBOrganization, DBOrganizationMembership, DBUser,
)
from app.main import app
from app.migrations import apply_registered_migrations


def _fixture():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def fk(connection, _record): connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine); apply_registered_migrations(engine)
    session = sessionmaker(bind=engine)()
    admin = DBUser(public_id="lrs-admin", username="lrs-admin", display_name="LRS 管理员", hashed_password=get_password_hash("pw"), role="admin")
    learner = DBUser(public_id="lrs-learner", username="lrs-learner", display_name="合成学员", hashed_password=get_password_hash("pw"), role="student")
    outsider = DBUser(public_id="lrs-outsider", username="lrs-outsider", display_name="外部学员", hashed_password=get_password_hash("pw"), role="student")
    org = DBOrganization(id="lrs-org", name="冻结合成组织")
    session.add_all([admin, learner, outsider, org]); session.flush()
    session.add_all([
        DBOrganizationMembership(organization_id=org.id, user_public_id=admin.public_id, role="admin"),
        DBOrganizationMembership(organization_id=org.id, user_public_id=learner.public_id, role="learner"),
        DBLearningEvent(id="lrs-learning-event", owner_public_id=learner.public_id, event_type="quiz_answered",
                        schema_version="v1", idempotency_key="lrs-event", source="learner", trace_id="lrs-trace",
                        object_type="assessment", object_id="quiz-1", payload={"correct": True}, occurred_at=datetime(2026,8,5,8)),
    ]); session.commit()
    return session, admin, learner, outsider, org


def _client(monkeypatch, session, user):
    async def fake_run_db_op(operation): return operation(session)
    monkeypatch.setattr(m7_api, "run_db_op", fake_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _enqueue(client, org, destination="competition-local-lrs"):
    response = client.post("/api/v1/m7/integrations/deliveries", json={
        "organization_id": org.id, "event_id": "lrs-learning-event", "destination_key": destination,
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_local_lrs_persists_immutable_idempotent_statement_without_mutating_event(monkeypatch):
    session, admin, _, _, org = _fixture(); client = _client(monkeypatch, session, admin)
    try:
        delivery_id = _enqueue(client, org)
        before = session.query(DBLearningEvent).filter_by(id="lrs-learning-event").one().payload.copy()
        accepted = client.post(f"/api/v1/m7/integrations/deliveries/{delivery_id}/local-lrs")
        assert accepted.status_code == 200 and accepted.json()["created"] is True
        replay = client.post(f"/api/v1/m7/integrations/deliveries/{delivery_id}/local-lrs")
        assert replay.status_code == 200 and replay.json()["created"] is False
        statement = session.query(DBLocalLRSStatement).one()
        assert statement.statement_id == "lrs-learning-event"
        assert statement.statement["result"]["success"] is True
        assert session.query(DBLearningEvent).filter_by(id="lrs-learning-event").one().payload == before
        assert session.query(DBIntegrationDelivery).one().status == "delivered"
        workspace = client.get("/api/v1/m7/integrations/workspace").json()["selected"]
        assert workspace["transport"]["local_lrs_persistent"] is True
        assert workspace["lrs_statements"][0]["statement_id"] == "lrs-learning-event"
    finally: app.dependency_overrides.pop(get_current_user, None)


def test_delivery_reaches_dead_letter_requires_explicit_requeue_then_lrs_delivery(monkeypatch):
    session, admin, _, _, org = _fixture(); client = _client(monkeypatch, session, admin)
    try:
        delivery_id = _enqueue(client, org, "competition-fault-lrs")
        for attempt in range(5):
            response = client.post(f"/api/v1/m7/integrations/deliveries/{delivery_id}/attempt", json={
                "outcome": "failure", "error_code": "local_lrs_fault",
            })
            assert response.status_code == 200
            assert response.json()["attempt_count"] == attempt + 1
        assert response.json()["status"] == "dead_letter"
        denied = client.post(f"/api/v1/m7/integrations/deliveries/{delivery_id}/local-lrs")
        assert denied.status_code == 409 and denied.json()["detail"]["code"] == "dead_letter_requires_manual_requeue"
        requeued = client.post(f"/api/v1/m7/integrations/deliveries/{delivery_id}/requeue")
        assert requeued.status_code == 200 and requeued.json()["status"] == "pending"
        accepted = client.post(f"/api/v1/m7/integrations/deliveries/{delivery_id}/local-lrs")
        assert accepted.status_code == 200 and accepted.json()["status"] == "delivered"
        events = session.query(DBIntegrationDeliveryEvent).filter_by(delivery_id=delivery_id).all()
        assert [row.action for row in events].count("attempt_failure") == 5
        assert any(row.action == "manual_requeue" for row in events)
        assert any(row.action == "local_lrs_accept" for row in events)
    finally: app.dependency_overrides.pop(get_current_user, None)


def test_cmi5_subset_state_machine_emits_xapi_and_recovers(monkeypatch):
    session, admin, learner, _, org = _fixture(); client = _client(monkeypatch, session, admin)
    try:
        payload = {"organization_id": org.id, "learner_public_id": learner.public_id,
                   "course_id": None, "launch_key": "competition-cmi5-launch-001"}
        launched = client.post("/api/v1/m7/integrations/cmi5/sessions", json=payload)
        assert launched.status_code == 201 and launched.json()["created"] is True
        replay = client.post("/api/v1/m7/integrations/cmi5/sessions", json=payload)
        assert replay.status_code == 201 and replay.json()["created"] is False
        session_id = launched.json()["id"]
        invalid = client.post(f"/api/v1/m7/integrations/cmi5/sessions/{session_id}/transition", json={"action":"complete","expected_lock_version":1})
        assert invalid.status_code == 409 and invalid.json()["detail"]["code"] == "cmi5_transition_invalid"
        active = client.post(f"/api/v1/m7/integrations/cmi5/sessions/{session_id}/transition", json={"action":"activate","expected_lock_version":1})
        assert active.status_code == 200 and active.json()["status"] == "active"
        stale = client.post(f"/api/v1/m7/integrations/cmi5/sessions/{session_id}/transition", json={"action":"complete","expected_lock_version":1})
        assert stale.status_code == 409 and stale.json()["detail"]["code"] == "cmi5_version_conflict"
        completed = client.post(f"/api/v1/m7/integrations/cmi5/sessions/{session_id}/transition", json={"action":"complete","expected_lock_version":2})
        exited = client.post(f"/api/v1/m7/integrations/cmi5/sessions/{session_id}/transition", json={"action":"exit","expected_lock_version":3})
        assert completed.json()["status"] == "completed" and exited.json()["status"] == "exited"
        assert session.query(DBCmi5Session).one().status == "exited"
        assert [row.action for row in session.query(DBCmi5SessionEvent).order_by(DBCmi5SessionEvent.created_at).all()] == ["launch","activate","complete","exit"]
        types = [row.event_type for row in session.query(DBLearningEvent).filter(DBLearningEvent.event_type.like("cmi5_%")).all()]
        assert types == ["cmi5_launched","cmi5_initialized","cmi5_completed","cmi5_terminated"]
        assert session.query(DBIntegrationDelivery).filter_by(destination_key="competition-local-lrs").count() == 4
        workspace = client.get("/api/v1/m7/integrations/workspace").json()["selected"]
        assert workspace["cmi5_sessions"][0]["status"] == "exited"
        assert workspace["transport"]["full_cmi5_conformance_claimed"] is False
    finally: app.dependency_overrides.pop(get_current_user, None)


def test_lrs_cmi5_permissions_and_migration_051(monkeypatch):
    session, admin, _, outsider, org = _fixture(); client = _client(monkeypatch, session, outsider)
    try:
        assert client.get("/api/v1/m7/integrations/workspace").status_code == 403
        assert client.post("/api/v1/m7/integrations/cmi5/sessions", json={"organization_id":org.id,"learner_public_id":outsider.public_id,"course_id":None,"launch_key":"outside"}).status_code == 403
    finally: app.dependency_overrides.pop(get_current_user, None)
    with session.bind.begin() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM schema_migrations WHERE version='20260805_051'")).scalar_one() == 1
        triggers={row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'trg_%lrs%' OR type='trigger' AND name LIKE 'trg_cmi5_%'"))}
    assert {"trg_local_lrs_statement_no_update","trg_cmi5_event_no_update","trg_cmi5_session_identity_frozen"} <= triggers
