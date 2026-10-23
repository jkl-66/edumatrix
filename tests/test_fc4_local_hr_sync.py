from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.local_hr_sync_api as local_hr_sync_api
from app.auth import get_current_user, get_password_hash
from app.database import (
    Base, DBExternalIdentityMapping, DBHREmployeeProjection, DBHRSyncRecord,
    DBLearningEvent, DBOrganization, DBOrganizationMembership, DBUser,
)
from app.main import app
from app.migrations import apply_registered_migrations


def _fixture():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def fk(connection, _record): connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    apply_registered_migrations(engine)
    session = sessionmaker(bind=engine)()
    admin = DBUser(public_id="hr-admin", username="hr-admin", display_name="HR 管理员", hashed_password=get_password_hash("pw"), role="admin")
    outsider = DBUser(public_id="hr-outsider", username="hr-outsider", display_name="外部管理员", hashed_password=get_password_hash("pw"), role="admin")
    conflict = DBUser(public_id="hr-conflict", username="synthetic_hr_conflict", display_name="已有账号", hashed_password=get_password_hash("pw"), role="student")
    org = DBOrganization(id="hr-org", name="冻结合成组织")
    session.add_all([admin, outsider, conflict, org]); session.flush()
    session.add(DBOrganizationMembership(organization_id=org.id, user_public_id=admin.public_id, role="admin")); session.commit()
    return session, admin, outsider, conflict, org


def _client(monkeypatch, session, user):
    async def fake_run_db_op(operation): return operation(session)
    monkeypatch.setattr(local_hr_sync_api, "run_db_op", fake_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _mapping(client, org):
    response = client.post("/api/v1/local-hr/mappings", json={"organization_id": org.id})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _snapshot(client, sequence, offboard=False):
    response = client.get(f"/api/v1/local-hr/frozen-snapshot?sequence={sequence}&offboard_existing={'true' if offboard else 'false'}")
    assert response.status_code == 200
    return response.json()


def _preview(client, org, mapping_id, snapshot):
    return client.post("/api/v1/local-hr/previews", json={
        "organization_id": org.id, "mapping_version_id": mapping_id, **snapshot,
    })


def test_hr_two_phase_sync_offboarding_preserves_history_and_revokes_identity(monkeypatch):
    session, admin, _, _, org = _fixture(); client = _client(monkeypatch, session, admin)
    try:
        mapping_id = _mapping(client, org)
        first = _preview(client, org, mapping_id, _snapshot(client, 1))
        assert first.status_code == 201 and first.json()["preview"]["counts"] == {"create": 2, "skip_leave": 1}
        assert session.query(DBHREmployeeProjection).count() == 0
        apply_first = client.post(f"/api/v1/local-hr/batches/{first.json()['id']}/apply", json={"organization_id": org.id, "expected_lock_version": 1})
        assert apply_first.status_code == 200 and apply_first.json()["applied"] is True
        replay = client.post(f"/api/v1/local-hr/batches/{first.json()['id']}/apply", json={"organization_id": org.id, "expected_lock_version": 1})
        assert replay.status_code == 200 and replay.json()["applied"] is False
        employee = session.query(DBHREmployeeProjection).filter_by(external_employee_id="SYN-1001").one()
        session.add(DBExternalIdentityMapping(organization_id=org.id, user_public_id=employee.user_public_id, provider="competition-local-idp", external_subject="synthetic:hr-1001"))
        session.add(DBLearningEvent(id="hr-history-event", owner_public_id=employee.user_public_id, event_type="resource_opened", schema_version="v1", idempotency_key="hr-history", source="learner", trace_id="hr-history", object_type="chapter", object_id="chapter-1", payload={}, occurred_at=employee.created_at))
        session.commit()
        second = _preview(client, org, mapping_id, _snapshot(client, 2, True))
        assert second.status_code == 201
        assert second.json()["preview"]["counts"] == {"offboard": 1, "update": 1, "skip_leave": 1}
        apply_second = client.post(f"/api/v1/local-hr/batches/{second.json()['id']}/apply", json={"organization_id": org.id, "expected_lock_version": 1})
        assert apply_second.status_code == 200
        session.expire_all()
        employee = session.query(DBHREmployeeProjection).filter_by(external_employee_id="SYN-1001").one()
        assert employee.employment_status == "leave" and employee.source_sequence == 2
        membership = session.query(DBOrganizationMembership).filter_by(organization_id=org.id, user_public_id=employee.user_public_id).one()
        assert membership.status == "removed"
        assert session.query(DBExternalIdentityMapping).filter_by(user_public_id=employee.user_public_id).one().status == "revoked"
        assert session.query(DBUser).filter_by(public_id=employee.user_public_id).count() == 1
        assert session.query(DBLearningEvent).filter_by(id="hr-history-event").count() == 1
        record = session.query(DBHRSyncRecord).filter_by(external_employee_id="SYN-1001", outcome="offboarded").one()
        assert record.evidence_snapshot["user_deleted"] is False
        assert record.evidence_snapshot["learning_evidence_deleted"] is False
        workspace = client.get("/api/v1/local-hr/workspace").json()
        assert workspace["truthfulness"]["real_employee_data"] is False
        assert workspace["selected"]["employees"][0]["employment_status"] == "leave"
    finally: app.dependency_overrides.pop(get_current_user, None)


def test_hr_snapshot_idempotency_out_of_order_and_conflict_fail_closed(monkeypatch):
    session, admin, _, conflict, org = _fixture(); client = _client(monkeypatch, session, admin)
    try:
        mapping_id = _mapping(client, org); snapshot = _snapshot(client, 1)
        first = _preview(client, org, mapping_id, snapshot); assert first.status_code == 201
        same = _preview(client, org, mapping_id, snapshot); assert same.status_code == 201 and same.json()["created"] is False
        assert client.post(f"/api/v1/local-hr/batches/{first.json()['id']}/apply", json={"organization_id": org.id, "expected_lock_version": 1}).status_code == 200
        old = dict(snapshot); old["source_snapshot_id"] = "old-after-applied"
        response = _preview(client, org, mapping_id, old)
        assert response.status_code == 409 and response.json()["detail"]["code"] == "snapshot_out_of_order"
        conflict_snapshot = _snapshot(client, 2)
        conflict_snapshot["records"][0]["account"] = conflict.username
        blocked = _preview(client, org, mapping_id, conflict_snapshot)
        assert blocked.status_code == 201 and blocked.json()["preview"]["blocking_conflicts"] == 1
        denied = client.post(f"/api/v1/local-hr/batches/{blocked.json()['id']}/apply", json={"organization_id": org.id, "expected_lock_version": 1})
        assert denied.status_code == 409 and denied.json()["detail"]["code"] == "preview_has_conflicts"
    finally: app.dependency_overrides.pop(get_current_user, None)


def test_hr_permissions_and_migration_049(monkeypatch):
    session, admin, outsider, _, org = _fixture(); client = _client(monkeypatch, session, outsider)
    try:
        assert client.get("/api/v1/local-hr/workspace").json()["selected"] is None
        assert client.post("/api/v1/local-hr/mappings", json={"organization_id": org.id}).status_code == 403
    finally: app.dependency_overrides.pop(get_current_user, None)
    with session.bind.begin() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM schema_migrations WHERE version='20260805_049'")).scalar_one() == 1
        triggers = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'trg_hr_%'"))}
    assert {"trg_hr_mapping_no_update", "trg_hr_batch_frozen", "trg_hr_record_no_update"} <= triggers
