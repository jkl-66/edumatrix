from __future__ import annotations

from fastapi.testclient import TestClient

from app.database import DBUser, SessionLocal
from app.identity import new_public_id
from app.main import app
from tests.api_test_helpers import TEST_PASSWORD, auth_headers


def _promote_to_teacher(username: str) -> None:
    with SessionLocal() as session:
        user = session.query(DBUser).filter_by(username=username).one()
        user.role = "teacher"
        session.commit()


def _login_headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login", data={"username": username, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_internal_inspection_rejects_learner_and_distinguishes_missing_object():
    with TestClient(app) as client:
        username = new_public_id("m1-inspector-learner")
        learner_headers = auth_headers(client, username)
        denied = client.get(
            "/api/v1/internal/objects", headers=learner_headers
        )
        assert denied.status_code == 403
        trace_denied = client.get(
            "/api/v1/internal/traces/not-present", headers=learner_headers
        )
        assert trace_denied.status_code == 403

        _promote_to_teacher(username)
        operator_headers = _login_headers(client, username)
        missing = client.get(
            "/api/v1/internal/objects/artifact/not-present",
            headers=operator_headers,
        )
        assert missing.status_code == 404
        trace_missing = client.get(
            "/api/v1/internal/traces/not-present", headers=operator_headers
        )
        assert trace_missing.status_code == 404


def test_internal_inventory_has_server_filters_stable_cursor_and_lineage():
    with TestClient(app) as client:
        username = new_public_id("m1-inspector-operator")
        auth_headers(client, username)
        _promote_to_teacher(username)
        headers = _login_headers(client, username)

        created_ids = []
        for suffix in ("alpha", "beta"):
            response = client.post(
                "/api/v1/artifacts",
                headers=headers,
                json={
                    "artifact_type": "inspection-fixture",
                    "title": f"M1 inspector {suffix}",
                    "content": f"fixture {suffix}",
                },
            )
            assert response.status_code == 201
            created_ids.append(response.json()["id"])

        first = client.get(
            "/api/v1/internal/objects",
            headers=headers,
            params={"object_type": "artifact", "status": "draft", "q": "M1 inspector", "limit": 1},
        )
        assert first.status_code == 200
        payload = first.json()
        assert len(payload["items"]) == 1
        assert payload["has_more"] is True
        assert payload["next_cursor"] == payload["items"][0]["id"]

        second = client.get(
            "/api/v1/internal/objects",
            headers=headers,
            params={
                "object_type": "artifact", "status": "draft", "q": "M1 inspector",
                "limit": 1, "cursor": payload["next_cursor"],
            },
        )
        assert second.status_code == 200
        assert second.json()["items"][0]["id"] != payload["items"][0]["id"]

        inspected = client.get(
            f"/api/v1/internal/objects/artifact/{created_ids[0]}", headers=headers
        )
        assert inspected.status_code == 200
        detail = inspected.json()
        assert detail["owner_public_id"]
        assert detail["version"]
        assert detail["permissions"]["owner_public_id"] == detail["owner_public_id"]
        assert "relations" in detail["lineage"]

        task = client.post(
            "/api/v1/generation-tasks",
            headers=headers,
            json={
                "capability": "inspection.trace",
                "idempotency_key": new_public_id("trace-idempotency"),
            },
        )
        assert task.status_code == 201
        task_payload = task.json()
        traced_artifact = client.post(
            "/api/v1/artifacts",
            headers=headers,
            json={
                "artifact_type": "inspection-trace-fixture",
                "title": "M1 trace fixture",
                "content": "private trace content must not appear in trace inventory",
                "creating_task_id": task_payload["id"],
            },
        )
        assert traced_artifact.status_code == 201
        trace = client.get(
            f"/api/v1/internal/traces/{task_payload['trace_id']}", headers=headers
        )
        assert trace.status_code == 200
        trace_payload = trace.json()
        assert trace_payload["counts"]["tasks"] == 1
        assert trace_payload["counts"]["artifacts"] == 1
        assert trace_payload["counts"]["artifact_versions"] == 1
        serialized = str(trace_payload)
        assert "private trace content" not in serialized
        assert "password" not in serialized.lower()
        assert "api_key" not in serialized.lower()
