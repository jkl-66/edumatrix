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
        original_ids = {"classifier-threshold-calibration", "rag-hybrid-tuning"}
        assert original_ids <= {item["template_id"] for item in templates}
        assert all(len(item["template_sha256"]) == 64 for item in templates)
        assert all(item["hidden_expected_values_exposed"] is False for item in templates)
        for index, template in enumerate(item for item in templates if item["template_id"] in original_ids):
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


def test_parallel_training_parameters_and_calculated_results_survive_reload():
    from app.interactive_lab import get_template
    template = get_template("parallel-training-throughput")
    parameters = {item.key: int(item.default) if item.kind == "integer" else item.default for item in template.parameters}
    with TestClient(app) as client:
        headers = auth_headers(client, "parallel_lab_recovery")
        response = client.post("/api/v1/interactive-lab/instances", headers=headers, json={
            "template_id": template.template_id, "title": "测试：并行计算与通信",
            "parameters": parameters, "idempotency_key": "parallel-lab-create", "linked_media_resource_id": None,
        })
        assert response.status_code == 201, response.text
        current = response.json()
        first = _action(client, headers, current, "run", "parallel-lab-first").json()
        assert first["metrics"]["step_seconds"] == 35.5
        configured_response = _action(client, headers, first, "configure", "parallel-lab-configure", {**parameters, "devices": 8})
        assert configured_response.status_code == 200, configured_response.text
        configured = configured_response.json()
        changed_response = _action(client, headers, configured, "run", "parallel-lab-eight")
        assert changed_response.status_code == 200, changed_response.text
        changed = changed_response.json()
        assert changed["metrics"]["step_seconds"] == 28.25
        restored = client.get(f"/api/v1/interactive-lab/instances/{current['instance_id']}", headers=headers).json()
        assert restored["parameters"]["devices"] == 8
        assert restored["metrics"] == changed["metrics"]
        assert restored["computed_series"] == changed["computed_series"]
        replay = _action(client, headers, configured, "run", "parallel-lab-eight").json()
        assert replay["version_id"] == changed["version_id"] and replay["action_created"] is False


def test_frequency_observation_saves_neutral_metrics_without_unbound_learning_evidence():
    from app.interactive_lab import get_template
    template = get_template('sample-frequency-estimation')
    parameters = {p.key: int(p.default) if p.kind == 'integer' else p.default for p in template.parameters}
    with TestClient(app) as client:
        headers = auth_headers(client, 'sample_frequency_learning')
        response = client.post('/api/v1/interactive-lab/instances', headers=headers, json={
            'template_id':template.template_id, 'title':'样本频率', 'parameters':parameters,
            'idempotency_key':'frequency-create', 'linked_media_resource_id':None})
        assert response.status_code == 201, response.text
        instance = response.json()
        run = _action(client, headers, instance, 'run', 'frequency-first').json()
        assert run['metrics']['sample_frequency'] == 12
        assert run['learning_evidence']['created'] is False
        configured = _action(client, headers, run, 'configure', 'frequency-larger', {**parameters,'sample_size':1000}).json()
        larger = _action(client, headers, configured, 'run', 'frequency-larger-run').json()
        assert larger['metrics']['theoretical_se'] < run['metrics']['theoretical_se']
        saved = _action(client, headers, larger, 'submit', 'frequency-submit').json()
        assert saved['status'] == 'passed', saved
        assert saved['hidden_acceptance']['total_count'] == 1
        # This instance has no course resource, so it creates no learning event.
        assert saved['learning_evidence']['created'] is False
        restored = client.get('/api/v1/interactive-lab/instances/'+instance['instance_id'],headers=headers).json()
        assert restored['metrics'] == larger['metrics']
        assert restored['parameters']['sample_size'] == 1000
        assert restored['status'] == 'passed'


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


def test_inventory_experiment_changes_and_recovers_without_creating_mastery_from_running():
    from app.interactive_lab import get_template
    template = get_template("inventory-demand-boundary")
    parameters = {p.key: int(p.default) if p.kind == "integer" else p.default for p in template.parameters}
    with TestClient(app) as client:
        headers = auth_headers(client, "inventory_lab_recovery")
        response = client.post("/api/v1/interactive-lab/instances", headers=headers, json={
            "template_id": template.template_id, "title": "合成测试：单品库存", "parameters": parameters,
            "idempotency_key": "inventory-create", "linked_media_resource_id": None,
        })
        assert response.status_code == 201, response.text
        created = response.json()
        run = _action(client, headers, created, "run", "inventory-run").json()
        assert run["metrics"]["average_lost"] == .1
        assert run["learning_evidence"]["created"] is False
        configured = _action(client, headers, run, "configure", "inventory-backlog",
                             {**parameters, "backorder": 1}).json()
        changed = _action(client, headers, configured, "run", "inventory-backlog-run").json()
        assert changed["metrics"]["average_backlog"] == .1 and changed["metrics"]["average_lost"] == 0
        assert changed["learning_evidence"]["created"] is False
        restored = client.get(f"/api/v1/interactive-lab/instances/{created['instance_id']}", headers=headers).json()
        assert restored["metrics"] == changed["metrics"]
        assert restored["parameters"] == changed["parameters"]
        assert restored["computed_series"] == changed["computed_series"]


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
        assert hinted["hint_count"] == 1
        assert "决策阈值" in hinted["feedback"][-1] and "平衡准确率" in hinted["feedback"][-1]
        assert "证据强度" not in hinted["feedback"][-1]
        hint_replay = _action(client, owner, evaluated, "request_hint", "owner-hint").json()
        assert hint_replay["hint_count"] == 1 and hint_replay["version_id"] == hinted["version_id"]
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
