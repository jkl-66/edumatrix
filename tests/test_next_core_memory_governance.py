from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.database import (
    DBAuditLog,
    DBMemoryItem,
    DBMemorySubscription,
    DBTutorContextSession,
    DBUser,
    SessionLocal,
)
from app.main import app
from tests.api_test_helpers import auth_headers


def _identity(client: TestClient, headers: dict[str, str]) -> dict:
    response = client.get("/api/auth/me", headers=headers)
    assert response.status_code == 200
    return response.json()


def _context(owner_public_id: str, key: str = "memory-context") -> DBTutorContextSession:
    return DBTutorContextSession(
        owner_public_id=owner_public_id,
        idempotency_key=key,
        context_mode="current_resource",
        primary_object_type="chapter",
        primary_object_id="chapter-memory-test",
        context_snapshot={"schema_version": "m5.tutor-context.v1", "primary": {"title": "Memory test"}},
    )


def test_memory_schema_enforces_owner_key_and_subscription_identity():
    with SessionLocal() as session:
        user = DBUser(
            username="memory_schema_owner", hashed_password="not-used", role="student",
        )
        session.add(user)
        session.flush()
        first = DBMemoryItem(
            owner_public_id=user.public_id, memory_key="manual:stable", title="first",
            memory_type="goal", content="first", source_type="manual",
            source_id=user.public_id, confidence=1.0,
        )
        session.add(first)
        session.commit()
        duplicate = DBMemoryItem(
            owner_public_id=user.public_id, memory_key="manual:stable", title="second",
            memory_type="goal", content="second", source_type="manual",
            source_id=user.public_id, confidence=1.0,
        )
        session.add(duplicate)
        try:
            session.commit()
            raise AssertionError("duplicate owner memory key was accepted")
        except IntegrityError:
            session.rollback()

        subscription = DBMemorySubscription(
            owner_public_id=user.public_id, subscriber_type="tutor",
            subscriber_key="profile", profile_fields=["major"], memory_types=["learning_context"],
        )
        session.add(subscription)
        session.commit()
        assert subscription.lock_version == 1


def test_manual_memory_api_is_versioned_owner_scoped_and_privacy_safe():
    secret = "Prefer worked examples before formal proofs"
    with TestClient(app) as client:
        owner_headers = auth_headers(client, "memory_api_owner")
        other_headers = auth_headers(client, "memory_api_other")
        created = client.post(
            "/api/v1/next/core/memories",
            headers=owner_headers,
            json={"title": "Explanation preference", "memory_type": "preference", "content": secret},
        )
        assert created.status_code == 201
        item = created.json()
        assert item["lock_version"] == 1 and item["source_type"] == "manual"

        stale = client.patch(
            f"/api/v1/next/core/memories/{item['id']}", headers=owner_headers,
            json={"expected_version": 9, "content": "stale overwrite"},
        )
        assert stale.status_code == 409
        denied = client.patch(
            f"/api/v1/next/core/memories/{item['id']}", headers=other_headers,
            json={"expected_version": 1, "content": "cross-owner overwrite"},
        )
        assert denied.status_code == 403

        updated = client.patch(
            f"/api/v1/next/core/memories/{item['id']}", headers=owner_headers,
            json={"expected_version": 1, "content": "Use examples, then proofs"},
        )
        assert updated.status_code == 200
        assert updated.json()["lock_version"] == 2
        withdrawn = client.post(
            f"/api/v1/next/core/memories/{item['id']}/withdraw", headers=owner_headers,
            json={"expected_version": 2, "reason": "preference_changed"},
        )
        assert withdrawn.status_code == 200
        assert withdrawn.json()["status"] == "withdrawn"

        audit = client.get("/api/v1/next/core/memory-audit", headers=owner_headers)
        assert audit.status_code == 200
        assert {row["action"] for row in audit.json()["items"]} >= {
            "memory.created", "memory.updated", "memory.withdrawn",
        }
        serialized = str(audit.json())
        assert secret not in serialized
        assert "cross-owner overwrite" not in serialized
        assert "preference_changed" not in serialized


def test_profile_subscription_updates_and_revokes_existing_context_projection():
    with TestClient(app) as client:
        headers = auth_headers(client, "memory_profile_owner")
        identity = _identity(client, headers)
        with SessionLocal() as session:
            session.add(_context(identity["user_id"]))
            session.commit()

        subscribed = client.put(
            "/api/v1/next/core/memory-subscriptions/profile",
            headers=headers,
            json={"profile_fields": ["major", "learning_goals"], "expected_version": 0},
        )
        assert subscribed.status_code == 200
        subscription = subscribed.json()
        assert subscription["status"] == "active"
        assert subscription["memories_changed"] >= 1

        updated_profile = client.post(
            "/api/profile/memory_profile_owner/update",
            headers=headers,
            json={"major": "人工智能", "learning_goals": ["掌握可解释机器学习"]},
        )
        assert updated_profile.status_code == 200
        listed = client.get("/api/v1/next/core/memories", headers=headers)
        assert listed.status_code == 200
        by_key = {row["memory_key"]: row for row in listed.json()["items"]}
        assert by_key["profile:major"]["content"] == "人工智能"
        assert "掌握可解释机器学习" in by_key["profile:learning_goals"]["content"]

        with SessionLocal() as session:
            persisted = session.query(DBTutorContextSession).filter_by(
                owner_public_id=identity["user_id"],
            ).one()
            projected = persisted.context_snapshot["long_term_memory"]["items"]
            assert any(row["content"] == "人工智能" for row in projected)
            assert persisted.lock_version > 1

        revoked = client.post(
            "/api/v1/next/core/memory-subscriptions/profile/revoke",
            headers=headers,
            json={"expected_version": subscription["lock_version"], "reason": "privacy_reset"},
        )
        assert revoked.status_code == 200
        assert revoked.json()["status"] == "revoked"

        with SessionLocal() as session:
            persisted = session.query(DBTutorContextSession).filter_by(
                owner_public_id=identity["user_id"],
            ).one()
            assert persisted.context_snapshot["long_term_memory"]["items"] == []
            assert session.query(DBMemoryItem).filter_by(
                owner_public_id=identity["user_id"], source_type="profile", status="active",
            ).count() == 0


def test_memory_and_audit_lists_do_not_cross_owner_boundaries():
    with TestClient(app) as client:
        first_headers = auth_headers(client, "memory_list_first")
        second_headers = auth_headers(client, "memory_list_second")
        first = client.post(
            "/api/v1/next/core/memories", headers=first_headers,
            json={"title": "First owner", "memory_type": "constraint", "content": "Private boundary"},
        )
        second = client.post(
            "/api/v1/next/core/memories", headers=second_headers,
            json={"title": "Second owner", "memory_type": "goal", "content": "Separate boundary"},
        )
        assert first.status_code == second.status_code == 201
        first_list = client.get("/api/v1/next/core/memories", headers=first_headers).json()["items"]
        second_list = client.get("/api/v1/next/core/memories", headers=second_headers).json()["items"]
        assert {row["id"] for row in first_list} == {first.json()["id"]}
        assert {row["id"] for row in second_list} == {second.json()["id"]}
        first_audit = str(client.get("/api/v1/next/core/memory-audit", headers=first_headers).json())
        assert second.json()["id"] not in first_audit


def test_withdrawal_propagation_survives_new_database_session():
    with TestClient(app) as client:
        headers = auth_headers(client, "memory_restart_owner")
        identity = _identity(client, headers)
        created = client.post(
            "/api/v1/next/core/memories", headers=headers,
            json={"title": "Persistent goal", "memory_type": "goal", "content": "Finish the course"},
        ).json()
        with SessionLocal() as session:
            context = _context(identity["user_id"], "restart-context")
            session.add(context)
            session.commit()
        updated = client.patch(
            f"/api/v1/next/core/memories/{created['id']}", headers=headers,
            json={"expected_version": 1, "content": "Finish the advanced course"},
        )
        assert updated.status_code == 200

    with SessionLocal() as restarted_session:
        memory = restarted_session.get(DBMemoryItem, created["id"])
        context = restarted_session.query(DBTutorContextSession).filter_by(
            owner_public_id=identity["user_id"], idempotency_key="restart-context",
        ).one()
        assert memory.content == "Finish the advanced course"
        assert context.context_snapshot["long_term_memory"]["items"][0]["content"] == "Finish the advanced course"
        audit = restarted_session.query(DBAuditLog).filter_by(
            actor_public_id=identity["user_id"], action="memory.updated",
        ).one()
        assert "content" not in audit.metadata_json
