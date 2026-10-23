from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.local_sso_api as local_sso_api
from app.auth import get_current_user, get_password_hash
from app.database import (
    Base, DBExternalIdentityMapping, DBLocalSSOEvent, DBLocalSSOMappingVersion,
    DBLocalSSOProvider, DBLocalSSOSession, DBOrganization, DBOrganizationMembership, DBUser,
)
from app.main import app
from app.migrations import apply_registered_migrations


def _fixture():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    apply_registered_migrations(engine)
    session = sessionmaker(bind=engine)()
    admin = DBUser(
        public_id="usr-fc4-admin", username="fc4-admin", display_name="FC4 管理员",
        hashed_password=get_password_hash("password"), role="admin",
    )
    learner = DBUser(
        public_id="usr-fc4-learner", username="fc4-learner", display_name="合成学员",
        hashed_password=get_password_hash("password"), role="student",
    )
    outsider = DBUser(
        public_id="usr-fc4-outsider", username="fc4-outsider", display_name="外部用户",
        hashed_password=get_password_hash("password"), role="student",
    )
    second = DBUser(
        public_id="usr-fc4-second", username="fc4-second", display_name="第二学员",
        hashed_password=get_password_hash("password"), role="student",
    )
    org = DBOrganization(id="org-fc4", name="FC4 冻结合成组织", organization_type="enterprise")
    session.add_all([admin, learner, outsider, second, org])
    session.flush()
    session.add_all([
        DBOrganizationMembership(organization_id=org.id, user_public_id=admin.public_id, role="admin"),
        DBOrganizationMembership(organization_id=org.id, user_public_id=learner.public_id, role="learner"),
        DBOrganizationMembership(organization_id=org.id, user_public_id=second.public_id, role="learner"),
    ])
    session.commit()
    return session, admin, learner, outsider, second, org


def _client(monkeypatch, session, user):
    async def fake_run_db_op(operation):
        return operation(session)

    monkeypatch.setattr(local_sso_api, "run_db_op", fake_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _provider(client, org):
    response = client.post("/api/v1/local-sso/providers", json={
        "organization_id": org.id,
        "provider_key": "competition-local-idp",
        "display_name": "比赛本地 IdP",
        "protocol_style": "oidc",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _assertion(org, provider_id, user_id, assertion_id="assertion-001", subject="synthetic:learner-001", groups=None):
    return {
        "organization_id": org.id, "provider_id": provider_id,
        "assertion_id": assertion_id, "subject": subject,
        "groups": groups or ["learners", "course-mentors"],
        "target_user_public_id": user_id,
    }


def test_local_sso_role_mapping_binding_login_refresh_and_idempotency(monkeypatch):
    session, admin, learner, _, _, org = _fixture()
    client = _client(monkeypatch, session, admin)
    try:
        provider_id = _provider(client, org)
        payload = _assertion(org, provider_id, learner.public_id)
        preview = client.post("/api/v1/local-sso/assertions/preview", json=payload)
        assert preview.status_code == 200
        assert preview.json()["resolved_role"] == "mentor"
        assert preview.json()["can_bind"] is True

        bound = client.post("/api/v1/local-sso/assertions/bind", json=payload)
        assert bound.status_code == 201 and bound.json()["created"] is True
        replay_bind = client.post("/api/v1/local-sso/assertions/bind", json=payload)
        assert replay_bind.status_code == 201 and replay_bind.json()["created"] is False
        changed_groups = dict(payload)
        changed_groups["assertion_id"] = "assertion-role-change"
        changed_groups["groups"] = ["training-managers"]
        role_conflict = client.post("/api/v1/local-sso/assertions/bind", json=changed_groups)
        assert role_conflict.status_code == 409
        assert role_conflict.json()["detail"]["code"] == "existing_binding_role_conflict"

        login_payload = {key: value for key, value in payload.items() if key != "target_user_public_id"}
        login = client.post("/api/v1/local-sso/sessions", json=login_payload)
        assert login.status_code == 201 and login.json()["created"] is True
        assert login.json()["application_access_token_issued"] is False
        replay_login = client.post("/api/v1/local-sso/sessions", json=login_payload)
        assert replay_login.status_code == 201 and replay_login.json()["created"] is False

        workspace = client.get("/api/v1/local-sso/workspace")
        assert workspace.status_code == 200
        body = workspace.json()
        assert body["truthfulness"]["real_idp_connected"] is False
        assert body["truthfulness"]["oidc_saml_conformance_verified"] is False
        assert len(body["selected"]["providers"]) == 1
        assert body["selected"]["mappings"][0]["status"] == "active"
        assert body["selected"]["sessions"][0]["resolved_organization_role"] == "mentor"
        membership = session.query(DBOrganizationMembership).filter_by(
            organization_id=org.id, user_public_id=learner.public_id,
        ).one()
        assert membership.role == "mentor"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_duplicate_subject_conflict_and_revoked_identity_fail_closed(monkeypatch):
    session, admin, learner, _, second, org = _fixture()
    client = _client(monkeypatch, session, admin)
    try:
        provider_id = _provider(client, org)
        original = _assertion(org, provider_id, learner.public_id)
        assert client.post("/api/v1/local-sso/assertions/bind", json=original).status_code == 201
        conflict = _assertion(
            org, provider_id, second.public_id, assertion_id="assertion-002",
            subject=original["subject"], groups=["learners"],
        )
        response = client.post("/api/v1/local-sso/assertions/bind", json=conflict)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "subject_bound_to_another_user"
        mapping = session.query(DBExternalIdentityMapping).filter_by(
            organization_id=org.id, external_subject=original["subject"],
        ).one()
        revoked = client.post(f"/api/v1/local-sso/mappings/{mapping.id}/revoke", json={"organization_id": org.id})
        assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
        login_payload = {key: value for key, value in original.items() if key != "target_user_public_id"}
        denied = client.post("/api/v1/local-sso/sessions", json=login_payload)
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == "identity_revoked"
        assert session.query(DBLocalSSOEvent).filter_by(action="identity_revoke", outcome="revoked").count() == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_disabled_provider_rejects_login_but_emergency_admin_remains_available(monkeypatch):
    session, admin, learner, _, _, org = _fixture()
    client = _client(monkeypatch, session, admin)
    try:
        provider_id = _provider(client, org)
        payload = _assertion(org, provider_id, learner.public_id)
        assert client.post("/api/v1/local-sso/assertions/bind", json=payload).status_code == 201
        disabled = client.post(f"/api/v1/local-sso/providers/{provider_id}/status", json={
            "organization_id": org.id, "status": "disabled", "expected_lock_version": 1,
        })
        assert disabled.status_code == 200 and disabled.json()["lock_version"] == 2
        login_payload = {key: value for key, value in payload.items() if key != "target_user_public_id"}
        denied = client.post("/api/v1/local-sso/sessions", json=login_payload)
        assert denied.status_code == 409 and denied.json()["detail"]["code"] == "provider_disabled"
        emergency = client.post("/api/v1/local-sso/emergency-admin", json={
            "organization_id": org.id, "reason": "本地 IdP 故障演练期间保留管理员入口",
        })
        assert emergency.status_code == 201
        assert emergency.json()["provider_bypassed"] is True
        assert emergency.json()["application_access_token_issued"] is False
        assert session.query(DBLocalSSOSession).filter_by(login_mode="emergency_admin", status="active").count() == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_non_admin_and_cross_organization_access_are_forbidden(monkeypatch):
    session, admin, learner, outsider, _, org = _fixture()
    client = _client(monkeypatch, session, learner)
    try:
        assert client.get("/api/v1/local-sso/workspace").status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    outsider.role = "admin"
    session.commit()
    client = _client(monkeypatch, session, outsider)
    try:
        response = client.get(f"/api/v1/local-sso/workspace?organization_id={org.id}")
        assert response.status_code == 200
        assert response.json()["selected"] is None
        create = client.post("/api/v1/local-sso/providers", json={
            "organization_id": org.id, "provider_key": "outside-idp",
            "display_name": "越权 IdP", "protocol_style": "saml",
        })
        assert create.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_migration_048_and_append_only_triggers_are_installed():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    apply_registered_migrations(engine)
    with engine.begin() as connection:
        version = connection.execute(text(
            "SELECT version FROM schema_migrations WHERE version='20260805_048'"
        )).scalar_one()
        triggers = {row[0] for row in connection.execute(text(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'trg_local_sso_%'"
        )).fetchall()}
    assert version == "20260805_048"
    assert {
        "trg_local_sso_mapping_no_update", "trg_local_sso_mapping_no_delete",
        "trg_local_sso_event_no_update", "trg_local_sso_event_no_delete",
        "trg_local_sso_session_identity_frozen",
    } <= triggers
