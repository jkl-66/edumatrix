from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.local_webhook_api as webhook_api
import app.m7_api as m7_api
from app.auth import get_current_user, get_password_hash
from app.database import (
    Base, DBCertification, DBCertificationLifecycleEvent, DBIntegrationDelivery,
    DBJobFamily, DBJobLevel, DBLocalWebhookEndpoint, DBOrganization,
    DBOrganizationMembership, DBTrainingAssignment, DBTrainingCohort,
    DBTrainingProgram, DBUser, DBWebhookAcceptedNonce, DBWebhookEvent,
    DBWebhookReceipt,
)
from app.local_webhook import _sign
from app.main import app
from app.migrations import apply_registered_migrations


def _fixture():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def fk(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    apply_registered_migrations(engine)
    session = sessionmaker(bind=engine)()
    admin = DBUser(public_id="webhook-admin", username="webhook-admin", display_name="Webhook 管理员", hashed_password=get_password_hash("pw"), role="admin")
    learner = DBUser(public_id="webhook-learner", username="webhook-learner", display_name="冻结合成学员", hashed_password=get_password_hash("pw"), role="student")
    outsider = DBUser(public_id="webhook-outsider", username="webhook-outsider", display_name="外部用户", hashed_password=get_password_hash("pw"), role="student")
    org = DBOrganization(id="webhook-org", name="冻结合成 Webhook 组织")
    session.add_all([admin, learner, outsider, org]); session.flush()
    session.add_all([
        DBOrganizationMembership(organization_id=org.id, user_public_id=admin.public_id, role="admin"),
        DBOrganizationMembership(organization_id=org.id, user_public_id=learner.public_id, role="learner"),
    ]); session.flush()
    family = DBJobFamily(organization_id=org.id, code="AI", title="人工智能工程")
    session.add(family); session.flush()
    level = DBJobLevel(job_family_id=family.id, level_code="L1", version="1", title="初级工程师", status="active")
    session.add(level); session.flush()
    program = DBTrainingProgram(organization_id=org.id, target_job_level_id=level.id, title="冻结培训项目", version="1", status="active")
    session.add(program); session.flush()
    cohort = DBTrainingCohort(organization_id=org.id, training_program_id=program.id, standard_snapshot={"version": "1"}, status="active")
    session.add(cohort); session.flush()
    assignment = DBTrainingAssignment(
        id="webhook-assignment", organization_id=org.id, cohort_id=cohort.id,
        learner_public_id=learner.public_id, assignment_source="organization", status="completed",
        assigned_at=datetime(2026, 8, 5, 8),
    )
    certification = DBCertification(
        id="webhook-cert-active", organization_id=org.id, learner_public_id=learner.public_id,
        job_level_id=level.id, standard_snapshot={"version": "1"}, evidence_ids=["hidden-evidence"],
        issuer_public_id=admin.public_id, status="active", issued_at=datetime(2026, 8, 5, 9),
    )
    revoked = DBCertification(
        id="webhook-cert-revoked", organization_id=org.id, learner_public_id=learner.public_id,
        job_level_id=level.id, standard_snapshot={"version": "1"}, evidence_ids=["private-body"],
        issuer_public_id=admin.public_id, status="revoked", issued_at=datetime(2026, 8, 5, 9),
        revoked_at=datetime(2026, 8, 5, 10), lock_version=2,
    )
    session.add_all([assignment, certification, revoked]); session.flush()
    session.add(DBCertificationLifecycleEvent(
        certification_id=revoked.id, organization_id=org.id, actor_public_id=admin.public_id,
        actor_role="admin", action="revoke", from_status="active", to_status="revoked",
        reason="演示撤销", reason_hash="a" * 64, evidence_snapshot={"private": "must-not-leak"},
        created_at=datetime(2026, 8, 5, 10),
    ))
    session.commit()
    return session, admin, learner, outsider, org


def _client(monkeypatch, session, user):
    async def fake_run_db_op(operation):
        return operation(session)
    monkeypatch.setattr(webhook_api, "run_db_op", fake_run_db_op)
    monkeypatch.setattr(m7_api, "run_db_op", fake_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _endpoint(client, org):
    response = client.post("/api/v1/local-webhooks/endpoints", json={"organization_id": org.id})
    assert response.status_code == 201, response.text
    assert response.json()["secret_returned"] is False
    return response.json()["id"]


def _event(client, org, event_type, source_id):
    response = client.post("/api/v1/local-webhooks/events", json={
        "organization_id": org.id, "event_type": event_type, "source_object_id": source_id,
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_four_minimal_events_are_canonical_idempotent_and_secret_is_not_returned(monkeypatch):
    session, admin, _, _, org = _fixture(); client = _client(monkeypatch, session, admin)
    try:
        endpoint_id = _endpoint(client, org)
        assert endpoint_id
        cases = [
            ("training.assignment.created", "webhook-assignment"),
            ("training.assignment.completed", "webhook-assignment"),
            ("certification.issued", "webhook-cert-active"),
            ("certification.revoked", "webhook-cert-revoked"),
        ]
        for event_type, source_id in cases:
            first = _event(client, org, event_type, source_id)
            assert _event(client, org, event_type, source_id) == first
        rows = session.query(DBWebhookEvent).all()
        assert len(rows) == 4
        encoded = str([row.payload for row in rows])
        for forbidden in ["name", "email", "score", "hidden-evidence", "private-body", "must-not-leak", "api_key"]:
            assert forbidden not in encoded
        workspace = client.get("/api/v1/local-webhooks/workspace", params={"organization_id": org.id})
        assert workspace.status_code == 200
        body = workspace.json()
        assert body["security"]["secret_returned_by_api"] is False
        assert "signing_secret" not in str(body)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_signature_timestamp_nonce_and_event_replay_are_fail_closed(monkeypatch):
    session, admin, _, _, org = _fixture(); client = _client(monkeypatch, session, admin)
    try:
        endpoint_id = _endpoint(client, org)
        event_id = _event(client, org, "certification.issued", "webhook-cert-active")
        endpoint = session.query(DBLocalWebhookEndpoint).filter_by(id=endpoint_id).one()
        payload = session.query(DBWebhookEvent).filter_by(id=event_id).one().payload
        now_ts = int(datetime.now(timezone.utc).timestamp())
        bad = client.post(f"/api/v1/local-webhooks/receive/{endpoint_id}", json={
            "payload": payload, "timestamp": now_ts, "nonce": "bad-signature",
            "signature": "v1=" + "0" * 64,
        })
        assert bad.status_code == 401 and bad.json()["detail"]["code"] == "signature_invalid"
        stale_ts = now_ts - 301
        stale = client.post(f"/api/v1/local-webhooks/receive/{endpoint_id}", json={
            "payload": payload, "timestamp": stale_ts, "nonce": "stale",
            "signature": _sign(endpoint.signing_secret, stale_ts, "stale", payload),
        })
        assert stale.status_code == 401 and stale.json()["detail"]["code"] == "timestamp_outside_window"
        signature = _sign(endpoint.signing_secret, now_ts, "once", payload)
        accepted = client.post(f"/api/v1/local-webhooks/receive/{endpoint_id}", json={
            "payload": payload, "timestamp": now_ts, "nonce": "once", "signature": signature,
        })
        assert accepted.status_code == 200 and accepted.json()["accepted"] is True
        nonce_replay = client.post(f"/api/v1/local-webhooks/receive/{endpoint_id}", json={
            "payload": payload, "timestamp": now_ts, "nonce": "once", "signature": signature,
        })
        assert nonce_replay.status_code == 401 and nonce_replay.json()["detail"]["code"] == "nonce_replayed"
        event_replay = client.post(f"/api/v1/local-webhooks/receive/{endpoint_id}", json={
            "payload": payload, "timestamp": now_ts, "nonce": "another",
            "signature": _sign(endpoint.signing_secret, now_ts, "another", payload),
        })
        assert event_replay.status_code == 401 and event_replay.json()["detail"]["code"] == "event_replayed"
        assert session.query(DBWebhookAcceptedNonce).count() == 1
        assert [row.reason_code for row in session.query(DBWebhookReceipt).all()] == [
            "signature_invalid", "timestamp_outside_window", "accepted", "nonce_replayed", "event_replayed",
        ]
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_delivery_failure_dead_letter_explicit_requeue_and_local_acceptance(monkeypatch):
    session, admin, _, _, org = _fixture(); client = _client(monkeypatch, session, admin)
    try:
        endpoint_id = _endpoint(client, org)
        event_id = _event(client, org, "training.assignment.completed", "webhook-assignment")
        queued = client.post("/api/v1/local-webhooks/deliveries", json={"event_id": event_id, "endpoint_id": endpoint_id})
        assert queued.status_code == 201 and queued.json()["created"] is True
        delivery_id = queued.json()["id"]
        for attempt in range(5):
            failed = client.post(f"/api/v1/local-webhooks/deliveries/{delivery_id}/send", json={"fault": "invalid_signature"})
            assert failed.status_code == 200 and failed.json()["attempt_count"] == attempt + 1
        assert failed.json()["status"] == "dead_letter"
        denied = client.post(f"/api/v1/local-webhooks/deliveries/{delivery_id}/send", json={"fault": "none"})
        assert denied.status_code == 409 and denied.json()["detail"]["code"] == "dead_letter_requires_manual_requeue"
        requeued = client.post(f"/api/v1/m7/integrations/deliveries/{delivery_id}/requeue")
        assert requeued.status_code == 200 and requeued.json()["status"] == "pending"
        delivered = client.post(f"/api/v1/local-webhooks/deliveries/{delivery_id}/send", json={"fault": "none"})
        assert delivered.status_code == 200 and delivered.json()["status"] == "delivered"
        replay = client.post(f"/api/v1/local-webhooks/deliveries/{delivery_id}/send", json={"fault": "none"})
        assert replay.status_code == 200 and replay.json()["attempted"] is False
        row = session.query(DBIntegrationDelivery).filter_by(id=delivery_id).one()
        assert row.attempt_count == 6 and row.status == "delivered"
        assert session.query(DBWebhookReceipt).filter_by(delivery_id=delivery_id, outcome="rejected").count() == 5
        assert session.query(DBWebhookReceipt).filter_by(delivery_id=delivery_id, outcome="accepted").count() == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_permissions_migration_and_immutable_receipts(monkeypatch):
    session, admin, _, outsider, org = _fixture(); client = _client(monkeypatch, session, outsider)
    try:
        assert client.get("/api/v1/local-webhooks/workspace", params={"organization_id": org.id}).status_code == 403
        assert client.post("/api/v1/local-webhooks/endpoints", json={"organization_id": org.id}).status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    admin_client = _client(monkeypatch, session, admin)
    try:
        endpoint_id = _endpoint(admin_client, org)
        event_id = _event(admin_client, org, "certification.issued", "webhook-cert-active")
        endpoint = session.query(DBLocalWebhookEndpoint).filter_by(id=endpoint_id).one()
        payload = session.query(DBWebhookEvent).filter_by(id=event_id).one().payload
        now_ts = int(datetime.now(timezone.utc).timestamp())
        response = admin_client.post(f"/api/v1/local-webhooks/receive/{endpoint_id}", json={
            "payload": payload, "timestamp": now_ts, "nonce": "immutable",
            "signature": _sign(endpoint.signing_secret, now_ts, "immutable", payload),
        })
        assert response.status_code == 200
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    with session.bind.begin() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM schema_migrations WHERE version='20260805_052'")).scalar_one() == 1
        triggers = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'trg_webhook_%'"))}
        assert {"trg_webhook_event_no_update", "trg_webhook_nonce_no_update", "trg_webhook_receipt_no_update"} <= triggers
        receipt_id = connection.execute(text("SELECT id FROM webhook_receipts LIMIT 1")).scalar_one()
        try:
            connection.execute(text("UPDATE webhook_receipts SET reason_code='tampered' WHERE id=:id"), {"id": receipt_id})
            assert False, "immutable receipt update unexpectedly succeeded"
        except Exception as exc:
            assert "immutable" in str(exc)
