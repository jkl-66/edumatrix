from datetime import datetime, timedelta
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user, get_password_hash
from app.database import (
    Base,
    DBArtifact,
    DBAuditLog,
    DBGenerationTask,
    DBModelCall,
    DBTaskEvent,
    DBTaskStep,
    DBUser,
    DBWorkerLease,
)
from app.main import app
import app.admin_api as admin_api


def fixture():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    users = {
        role: DBUser(
            public_id=f"f9-admin-{role}",
            username=f"f9-admin-{role}",
            hashed_password=get_password_hash("pw"),
            role=role,
            display_name={"student": "学生甲", "teacher": "教师甲", "admin": "管理员"}[role],
        )
        for role in ("student", "teacher", "admin")
    }
    db.add_all(users.values())
    db.commit()
    return db, users


def client_for(monkeypatch, db, identity, *, raise_server_exceptions=True):
    async def fake_run_db_op(operation):
        return operation(db)

    monkeypatch.setattr(admin_api, "run_db_op", fake_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: identity["user"]
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def close_client(client):
    client.close()
    app.dependency_overrides.pop(get_current_user, None)


def test_admin_account_list_patch_conflict_and_role_boundary(monkeypatch):
    db, users = fixture()
    identity = {"user": users["admin"]}
    client = client_for(monkeypatch, db, identity)
    try:
        listed = client.get("/api/v1/admin/accounts")
        assert listed.status_code == 200
        items = listed.json()["items"]
        assert {item["role"] for item in items} == {"student", "teacher", "admin"}
        assert "hashed_password" not in str(items)

        student = next(item for item in items if item["role"] == "student")
        changed = client.patch(f"/api/v1/admin/accounts/{student['public_id']}", json={
            "expected_version": student["version"],
            "display_name": "课程助理演示",
            "role": "teacher",
            "is_active": True,
        })
        assert changed.status_code == 200
        assert changed.json()["role"] == "teacher"
        audit = db.query(DBAuditLog).filter_by(action="admin.account.update").one()
        assert audit.metadata_json == {
            "schemaVersion": "edumatrix.audit.summary.v1",
            "beforeSummary": {"role": "student", "active": True},
            "afterSummary": {
                "role": "teacher",
                "active": True,
                "changedFields": ["display_name", "role"],
            },
        }
        assert "课程助理演示" not in str(audit.metadata_json)

        stale = client.patch(f"/api/v1/admin/accounts/{student['public_id']}", json={
            "expected_version": student["version"],
            "display_name": "旧页面覆盖",
            "role": "student",
            "is_active": True,
        })
        assert stale.status_code == 409

        invalid = client.patch(f"/api/v1/admin/accounts/{student['public_id']}", json={
            "expected_version": changed.json()["version"],
            "display_name": "禁止角色",
            "role": "assistant",
            "is_active": True,
        })
        assert invalid.status_code == 422

        for role in ("teacher", "student"):
            identity["user"] = users[role]
            assert client.get("/api/v1/admin/accounts").status_code == 403
    finally:
        close_client(client)
        db.close()


def test_admin_account_update_rolls_back_when_required_audit_fails(monkeypatch):
    db, users = fixture()
    identity = {"user": users["admin"]}
    client = client_for(
        monkeypatch, db, identity, raise_server_exceptions=False,
    )
    try:
        listed = client.get("/api/v1/admin/accounts").json()["items"]
        student = next(item for item in listed if item["role"] == "student")
        original = db.query(DBUser).filter_by(public_id=student["public_id"]).one()
        original_display_name = original.display_name
        original_role = original.role

        def fail_audit(*args, **kwargs):
            raise RuntimeError("audit storage unavailable")

        monkeypatch.setattr(admin_api, "record_backend_audit", fail_audit)
        response = client.patch(f"/api/v1/admin/accounts/{student['public_id']}", json={
            "expected_version": student["version"],
            "display_name": "不应提交的名称",
            "role": "teacher",
            "is_active": True,
        })
        assert response.status_code == 500
        db.expire_all()
        persisted = db.query(DBUser).filter_by(public_id=student["public_id"]).one()
        assert persisted.display_name == original_display_name
        assert persisted.role == original_role
        assert db.query(DBAuditLog).filter_by(action="admin.account.update").count() == 0
    finally:
        close_client(client)
        db.close()


def test_system_lists_only_new_summary_audits(monkeypatch):
    db, users = fixture()
    db.add_all([
        DBAuditLog(
            actor_public_id=users["admin"].public_id,
            action="legacy_migration_observation",
            object_type="legacy_migration_chain",
            object_id="legacy-profile-history",
            trace_id="legacy-private-trace",
            outcome="success",
            metadata_json={"private": {"api_key": "must-not-be-returned"}},
        ),
        DBAuditLog(
            actor_public_id=users["admin"].public_id,
            action="admin.account.update",
            object_type="user",
            object_id=users["student"].public_id,
            trace_id="summary-private-trace",
            outcome="success",
            metadata_json={
                "schemaVersion": "edumatrix.audit.summary.v1",
                "beforeSummary": {"role": "student"},
                "afterSummary": {"role": "teacher"},
            },
        ),
    ])
    db.commit()

    client = client_for(monkeypatch, db, {"user": users["admin"]})
    try:
        response = client.get("/api/v1/admin/system")
        assert response.status_code == 200
        audits = response.json()["recent_audits"]
        assert [item["action"] for item in audits] == ["admin.account.update"]
        assert audits[0]["detailsAvailable"] is True
        assert "legacy" not in str(audits).lower()
        assert "private-trace" not in str(audits).lower()
    finally:
        close_client(client)
        db.close()


def test_model_status_is_classified_and_never_returns_secrets(monkeypatch):
    db, users = fixture()
    now = datetime.utcnow()
    db.add_all([
        DBModelCall(
            trace_id="private-trace-auth",
            owner_public_id=users["student"].public_id,
            capability="quiz",
            prompt_version="private-prompt-v1",
            provider="secret-provider",
            model="secret-model",
            status="failed",
            error_code="invalid_api_key",
            created_at=now - timedelta(seconds=2),
            completed_at=now - timedelta(seconds=1),
        ),
        DBModelCall(
            trace_id="private-trace-capacity",
            owner_public_id=users["student"].public_id,
            capability="report",
            prompt_version="private-prompt-v2",
            provider="secret-provider",
            model="secret-model",
            status="failed",
            error_code="model_capacity",
            created_at=now,
            completed_at=now,
        ),
    ])
    db.commit()
    identity = {"user": users["admin"]}
    client = client_for(monkeypatch, db, identity)
    monkeypatch.setattr(
        admin_api,
        "CONFIG",
        replace(admin_api.CONFIG, llm_api_key="DO-NOT-RETURN-THIS-KEY"),
    )
    try:
        response = client.get("/api/v1/admin/models")
        assert response.status_code == 200
        payload = response.json()
        assert set(payload) == {"schema_version", "configuration", "health"}
        assert set(payload["health"]) == {"authentication", "capacity", "rate_limit", "timeout"}
        assert payload["health"]["authentication"]["state"] == "issue_observed"
        assert payload["health"]["capacity"]["state"] == "issue_observed"
        serialized = str(payload).lower()
        for forbidden in (
            "do-not-return-this-key", "private-trace", "private-prompt",
            "secret-provider", "secret-model", "input_tokens", "output_tokens",
            "estimated_cost", "quota", "api_key",
        ):
            assert forbidden not in serialized
    finally:
        close_client(client)
        db.close()


def test_system_retry_reuses_task_preserves_result_and_retries_failed_steps(monkeypatch):
    db, users = fixture()
    failed = DBGenerationTask(
        id="f9-admin-failed-task",
        owner_public_id=users["student"].public_id,
        trace_id="private-task-trace",
        status="failed",
        progress=0.5,
        capability="lecture.generate_verified",
        idempotency_key="f9-admin-failed-task",
        failure_code="provider_timeout",
        failure_reason="private provider response",
    )
    db.add(failed)
    db.flush()
    db.add_all([
        DBTaskStep(
            task_id=failed.id,
            sequence=1,
            attempt=1,
            agent_role="generator",
            tool_name="lecture",
            status="completed",
            input_summary="content_included=false",
        ),
        DBTaskStep(
            task_id=failed.id,
            sequence=2,
            attempt=1,
            agent_role="reviewer",
            tool_name="review",
            status="failed",
            input_summary="content_included=false",
            error_code="provider_timeout",
        ),
        DBArtifact(
            id="f9-admin-existing-artifact",
            owner_public_id=users["student"].public_id,
            artifact_type="lesson",
            title="已完成的讲义部分",
            creating_task_id=failed.id,
        ),
    ])
    db.commit()

    identity = {"user": users["admin"]}
    client = client_for(monkeypatch, db, identity)
    try:
        system = client.get("/api/v1/admin/system")
        assert system.status_code == 200
        listed = next(item for item in system.json()["tasks"] if item["id"] == failed.id)
        assert listed["has_existing_result"] is True
        assert listed["failure_category"] == "timeout"
        assert "private" not in str(listed).lower()

        retried = client.post(f"/api/v1/admin/system/tasks/{failed.id}/retry")
        assert retried.status_code == 200
        assert retried.json()["task"]["id"] == failed.id
        assert retried.json()["task"]["status"] == "queued"
        assert retried.json()["task"]["has_existing_result"] is True
        assert db.query(DBGenerationTask).filter_by(id=failed.id).count() == 1
        assert db.query(DBArtifact).filter_by(creating_task_id=failed.id).count() == 1
        assert [(step.sequence, step.attempt, step.status) for step in db.query(DBTaskStep).filter_by(
            task_id=failed.id,
        ).order_by(DBTaskStep.sequence, DBTaskStep.attempt)] == [
            (1, 1, "completed"),
            (2, 1, "failed"),
            (2, 2, "pending"),
        ]
        assert db.query(DBAuditLog).filter_by(action="admin.task.retry").count() == 1
        assert db.query(DBTaskEvent).filter_by(
            task_id=failed.id,
            event_type="generation_task.admin_retry",
        ).count() == 1

        replay = client.post(f"/api/v1/admin/system/tasks/{failed.id}/retry")
        assert replay.status_code == 200
        assert db.query(DBGenerationTask).filter_by(id=failed.id).count() == 1
        assert db.query(DBTaskStep).filter_by(task_id=failed.id, sequence=2).count() == 2
        assert db.query(DBAuditLog).filter_by(action="admin.task.retry").count() == 1
    finally:
        close_client(client)
        db.close()


def test_system_cancel_is_admin_only_idempotent_and_releases_lease(monkeypatch):
    db, users = fixture()
    now = datetime.utcnow()
    task = DBGenerationTask(
        id="f9-admin-running-task",
        owner_public_id=users["student"].public_id,
        trace_id="private-running-trace",
        status="running",
        capability="quiz.generate_verified",
        idempotency_key="f9-admin-running-task",
    )
    db.add(task)
    db.flush()
    db.add(DBWorkerLease(
        task_id=task.id,
        worker_id="worker-a",
        lease_token="lease-token-not-public",
        status="active",
        attempt=1,
        leased_at=now,
        heartbeat_at=now,
        leased_until=now + timedelta(minutes=1),
    ))
    db.commit()

    identity = {"user": users["teacher"]}
    client = client_for(monkeypatch, db, identity)
    try:
        assert client.post(f"/api/v1/admin/system/tasks/{task.id}/cancel").status_code == 403
        identity["user"] = users["admin"]
        cancelled = client.post(f"/api/v1/admin/system/tasks/{task.id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["task"]["status"] == "cancelled"
        assert db.query(DBWorkerLease).filter_by(task_id=task.id).one().status == "cancelled"
        assert db.query(DBAuditLog).filter_by(action="admin.task.cancel").count() == 1

        replay = client.post(f"/api/v1/admin/system/tasks/{task.id}/cancel")
        assert replay.status_code == 200
        assert db.query(DBAuditLog).filter_by(action="admin.task.cancel").count() == 1
        assert "lease-token-not-public" not in str(replay.json())
    finally:
        close_client(client)
        db.close()
