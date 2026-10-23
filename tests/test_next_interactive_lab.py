from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from tests.api_test_helpers import auth_headers


def _params(template_id: str):
    if template_id == "rag-hybrid-tuning":
        return {"keyword_weight": 0.4, "vector_weight": 0.6, "top_k": 5, "rerank_threshold": 0.55}
    return {"decision_threshold": 0.55, "abstain_margin": 0.1, "calibration_bins": 12}


def _create(client, headers, template_id, key):
    return client.post("/api/v1/interactive-lab/instances", headers=headers, json={
        "template_id": template_id, "title": f"Lab {template_id}", "parameters": _params(template_id),
        "linked_media_resource_id": None, "idempotency_key": key,
    })


def _action(client, headers, instance, action, key, parameters=None):
    return client.post(f"/api/v1/interactive-lab/instances/{instance['instance_id']}/actions", headers=headers, json={
        "action": action, "parameters": parameters, "expected_version": instance["version_number"], "idempotency_key": key,
    })


def test_two_templates_are_versioned_deterministic_and_recoverable():
    with TestClient(app) as client:
        headers = auth_headers(client, "nc_media_05_templates")
        templates = client.get("/api/v1/interactive-lab/templates", headers=headers).json()["items"]
        assert [item["template_id"] for item in templates] == ["classifier-threshold-calibration", "rag-hybrid-tuning"]
        assert all(len(item["template_sha256"]) == 64 for item in templates)
        assert all(item["hidden_expected_values_exposed"] is False for item in templates)
        for index, template in enumerate(templates):
            current = _create(client, headers, template["template_id"], f"create-key-{index}").json()
            evaluated = _action(client, headers, current, "run", f"run-key-{index}").json()
            assert evaluated["status"] == "evaluated" and evaluated["metrics"]
            replay = client.get(f"/api/v1/interactive-lab/instances/{current['instance_id']}", headers=headers).json()
            assert replay["metrics"] == evaluated["metrics"]
            submitted = _action(client, headers, evaluated, "submit", f"submit-key-{index}").json()
            assert submitted["status"] == "passed"
            hidden = submitted["hidden_acceptance"]
            assert hidden["hidden_expected_values_exposed"] is False
            assert set(hidden) == {"passed", "passed_count", "total_count", "failure_categories", "checker_version", "hidden_expected_values_exposed"}


def test_typed_parameters_bounds_relations_and_optimistic_version():
    with TestClient(app) as client:
        headers = auth_headers(client, "nc_media_05_validation")
        bad_integer = _params("rag-hybrid-tuning"); bad_integer["top_k"] = 4.5
        bad_relation = _params("rag-hybrid-tuning"); bad_relation["vector_weight"] = 0.5
        responses = [
            client.post("/api/v1/interactive-lab/instances", headers=headers, json={"template_id": "rag-hybrid-tuning", "title": "bad", "parameters": bad_integer, "idempotency_key": "bad-integer", "linked_media_resource_id": None}),
            client.post("/api/v1/interactive-lab/instances", headers=headers, json={"template_id": "rag-hybrid-tuning", "title": "bad", "parameters": bad_relation, "idempotency_key": "bad-relation", "linked_media_resource_id": None}),
        ]
        assert [item.status_code for item in responses] == [422, 422]
        current = _create(client, headers, "rag-hybrid-tuning", "valid-create").json()
        evaluated = _action(client, headers, current, "run", "valid-run").json()
        stale = client.post(f"/api/v1/interactive-lab/instances/{current['instance_id']}/actions", headers=headers,
                            json={"action": "submit", "parameters": None, "expected_version": current["version_number"], "idempotency_key": "stale-submit"})
        assert evaluated["version_number"] == current["version_number"] + 1
        assert stale.status_code == 409 and stale.json()["detail"]["code"] == "lab_version_conflict"


def test_action_idempotency_hint_boundary_and_owner_isolation():
    with TestClient(app) as client:
        owner = auth_headers(client, "nc_media_05_owner")
        other = auth_headers(client, "nc_media_05_other")
        current = _create(client, owner, "classifier-threshold-calibration", "owner-create").json()
        evaluated = _action(client, owner, current, "run", "owner-run").json()
        replay = _action(client, owner, current, "run", "owner-run").json()
        assert replay["action_created"] is False and replay["version_id"] == evaluated["version_id"]
        create_replay = _create(client, owner, "classifier-threshold-calibration", "owner-create").json()
        assert create_replay["created"] is False and create_replay["version_id"] == evaluated["version_id"]
        hinted = _action(client, owner, evaluated, "request_hint", "owner-hint").json()
        assert hinted["hint_count"] == 1 and "降低" in hinted["feedback"][-1]
        forbidden_read = client.get(f"/api/v1/interactive-lab/instances/{current['instance_id']}", headers=other)
        forbidden_write = client.post(f"/api/v1/interactive-lab/instances/{current['instance_id']}/actions", headers=other,
                                      json={"action": "run", "parameters": None, "expected_version": 1, "idempotency_key": "other-run"})
        assert forbidden_read.status_code == forbidden_write.status_code == 403
        assert client.get("/api/v1/interactive-lab/instances", headers=other).json()["items"] == []


def test_media_link_requires_owner_and_refresh_preserves_link():
    with TestClient(app) as client:
        owner = auth_headers(client, "nc_media_05_media_owner")
        other = auth_headers(client, "nc_media_05_media_other")
        media = client.post("/api/v1/media-context/resources", headers=owner, json={
            "resource_type": "video", "title": "Calibration walkthrough", "course_id": None,
            "language": "", "locator": "/media/calibration.mp4", "content": "", "duration_ms": 120000,
        }).json()
        denied = client.post("/api/v1/interactive-lab/instances", headers=other, json={
            "template_id": "classifier-threshold-calibration", "title": "stolen", "parameters": _params("classifier-threshold-calibration"),
            "linked_media_resource_id": media["id"], "idempotency_key": "stolen-media",
        })
        created = client.post("/api/v1/interactive-lab/instances", headers=owner, json={
            "template_id": "classifier-threshold-calibration", "title": "linked", "parameters": _params("classifier-threshold-calibration"),
            "linked_media_resource_id": media["id"], "idempotency_key": "linked-media",
        }).json()
        restored = client.get(f"/api/v1/interactive-lab/instances/{created['instance_id']}", headers=owner).json()
        assert denied.status_code == 403
        assert restored["linked_media_resource_id"] == media["id"]
