from __future__ import annotations

import json
from uuid import uuid4

from fastapi.testclient import TestClient

import app.m3_api as m3_api
from app.main import app
from tests.api_test_helpers import auth_headers
from tests.test_m3_debate import DeterministicDebateReviewer
from tests.test_m3_resources import ProfileAwareFakeLLM


def _post(client, path, headers, payload=None):
    response = client.post(path, headers=headers, json=payload)
    assert response.status_code in {200, 201}, response.text
    return response.json()


def test_m3_authenticated_api_runs_four_roles_and_redacts_private_content(monkeypatch):
    monkeypatch.setattr(m3_api, "_llm_from_request", lambda request: ProfileAwareFakeLLM())
    monkeypatch.setattr(m3_api, "_debate_reviewer_from_request", lambda request: DeterministicDebateReviewer())

    with TestClient(app) as client:
        owner_headers = auth_headers(client, f"m3-api-owner-{uuid4().hex[:10]}")
        outsider_headers = auth_headers(client, f"m3-api-outsider-{uuid4().hex[:10]}")

        profiles_response = client.get("/api/v1/m3/profiles", headers=owner_headers)
        assert profiles_response.status_code == 200
        profiles = profiles_response.json()["profiles"]
        assert [item["archetype"] for item in profiles] == ["beginner", "theory_practice_gap", "advanced"]
        assert all("rationale" not in item["adaptation_strategy"] for item in profiles)

        idempotency_key = f"m3-api-task-{uuid4().hex}"
        request = {
            "profile_id": profiles[0]["profile_id"],
            "idempotency_key": idempotency_key,
            "model": "structured-test-double",
        }
        created = _post(client, "/api/v1/m3/tasks", owner_headers, request)
        task_id = created["id"]
        assert created["created"] is True
        duplicate = _post(client, "/api/v1/m3/tasks", owner_headers, request)
        assert duplicate["id"] == task_id and duplicate["created"] is False
        assert client.get(f"/api/v1/m3/tasks/{task_id}", headers=outsider_headers).status_code == 403

        started = _post(client, f"/api/v1/m3/tasks/{task_id}/start", owner_headers)
        assert started["status"] == "running"
        diagnosed = _post(client, f"/api/v1/m3/tasks/{task_id}/diagnose", owner_headers)
        assert diagnosed["steps"][0]["status"] == "completed"

        generated = _post(client, f"/api/v1/m3/tasks/{task_id}/generate", owner_headers)
        assert {item["artifact_type"] for item in generated["resources"]} == {"lesson", "lab_guide", "tiered_quiz"}
        quiz = next(item for item in generated["resources"] if item["artifact_type"] == "tiered_quiz")
        content = quiz["versions"][-1]["content"]
        assert "answer_key" not in content and "explanation" not in content
        assert "rationale" not in content

        reviewed = _post(client, f"/api/v1/m3/tasks/{task_id}/review", owner_headers)
        assert reviewed["report"]["semantic_quality_metric_assessed"] is False
        assert len(reviewed["report"]["results"]) == 3
        matching = _post(client, f"/api/v1/m3/tasks/{task_id}/matching-report", owner_headers)
        assert matching["report"]["plan_execution_authorized"] is False
        decision = _post(client, f"/api/v1/m3/tasks/{task_id}/decision", owner_headers)
        assert decision["task"]["status"] == "completed"
        assert decision["comparison"]["selected_decision_type"]
        assert decision["comparison"]["status"] == "proposed"
        assert decision["comparison"]["user_confirmed"] is False
        assert decision["comparison"]["mastery_update"] == "none"

        bundle = client.get(f"/api/v1/m3/tasks/{task_id}/bundle", headers=owner_headers)
        assert bundle.status_code == 200
        for artifacts in bundle.json()["artifacts"].values():
            for artifact in artifacts:
                for version in artifact["versions"]:
                    content = version["content"]
                    if isinstance(content, str) and content.startswith(("{", "[")):
                        content = json.loads(content)
                    serialized = json.dumps(content, ensure_ascii=False)
                    forbidden_fields = ("system_prompt", "user_prompt", "api_key")
                    if artifact["artifact_type"] == "tiered_quiz":
                        forbidden_fields += ("answer_key", "explanation")
                    for forbidden in forbidden_fields:
                        assert forbidden not in serialized


def test_m3_interactive_api_preserves_state_and_records_se4_evidence(monkeypatch):
    monkeypatch.setattr(m3_api, "_llm_from_request", lambda request: ProfileAwareFakeLLM())
    monkeypatch.setattr(m3_api, "_debate_reviewer_from_request", lambda request: DeterministicDebateReviewer())

    with TestClient(app) as client:
        headers = auth_headers(client, f"m3-api-interactive-{uuid4().hex[:10]}")
        profile_id = client.get("/api/v1/m3/profiles", headers=headers).json()["profiles"][2]["profile_id"]
        task = _post(client, "/api/v1/m3/tasks", headers, {
            "profile_id": profile_id,
            "idempotency_key": f"m3-api-interactive-task-{uuid4().hex}",
        })
        task_id = task["id"]
        for suffix in ("start", "diagnose", "generate", "review", "matching-report", "decision"):
            _post(client, f"/api/v1/m3/tasks/{task_id}/{suffix}", headers)

        manifest = _post(client, f"/api/v1/m3/tasks/{task_id}/interactive/manifest", headers)
        assert manifest["manifest"]["runtime_mode"] == "safe_deterministic_simulation"
        assert manifest["manifest"]["hidden_acceptance"]["hidden_expected_values_exposed"] is False
        created = _post(client, f"/api/v1/m3/tasks/{task_id}/interactive/sessions", headers, {
            "idempotency_key": f"m3-api-session-{uuid4().hex}",
        })
        session_id = created["session_artifact_id"]
        actions = [
            ("configure", {"parameters": {"keyword_weight": 0.4, "vector_weight": 0.6, "top_k": 5, "rerank_threshold": 0.55}}),
            ("run", {}),
            ("evaluate", {}),
            ("submit", {}),
        ]
        last = None
        for index, (action, extra) in enumerate(actions):
            last = _post(client, f"/api/v1/m3/interactive/sessions/{session_id}/actions", headers, {
                "idempotency_key": f"m3-api-action-{index}-{uuid4().hex}",
                "action": action,
                **extra,
            })
        assert last["state"]["status"] == "passed"
        assert set(last["state"]["hidden_acceptance"]) == {
            "passed_count", "total_count", "passed", "failure_categories", "checker_version", "hidden_expected_values_exposed",
        }
        evidence = _post(client, f"/api/v1/m3/interactive/sessions/{session_id}/evidence", headers)
        assert evidence["skill_evidence_level"] == "SE-4"
        assert evidence["mastery_update"] == "none"
