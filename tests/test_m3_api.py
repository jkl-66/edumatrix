from __future__ import annotations

import json
import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient

import app.m3_api as m3_api
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.main import app
from app.m5_capabilities import M5CapabilityError
from tests.api_test_helpers import auth_headers
from tests.test_m3_debate import DeterministicDebateReviewer
from tests.test_m3_resources import ProfileAwareFakeLLM


class _RepairingDebateLLM:
    def __init__(self, *, repair: bool = True):
        self.calls = []
        self.repair = repair

    async def generate(self, system_prompt, user_prompt, *, role):
        request = json.loads(user_prompt)
        self.calls.append(request)
        issue = "none" if self.repair and len(self.calls) == 2 else "insufficient_evidence"
        return json.dumps({
            "prover": {"support_status": "supported", "evidence_ref_ids": ["ref-1"], "applicable_conditions": [], "rationale": "supported"},
            "challenger": {"issue_types": [issue], "evidence_ref_ids": ["ref-1"], "rationale": "checked"},
            "judge": {"verdict": "keep", "rationale": "supported", "evidence_ref_ids": ["ref-1"], "confidence": 0.9},
        })


def test_debate_reviewer_repairs_unknown_enum_once():
    llm = _RepairingDebateLLM()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    result = asyncio.run(m3_api._LLMDebateReviewer(llm, session=session, trace_id="m3-review-test").review_claim(
        {"proposed_source_ref_ids": ["ref-1"]}, round_number=1, previous_rounds=[]
    ))
    assert result["challenger"]["issue_types"] == ["none"]
    assert len(llm.calls) == 2
    assert "validation_feedback" in llm.calls[1]
    session.close()
    engine.dispose()


def test_public_failure_classifies_wrapped_capacity_without_exposing_provider_details():
    try:
        raise RuntimeError("Selected model is at capacity; api_key=sk-private-provider-value")
    except RuntimeError as cause:
        try:
            raise M5CapabilityError("provider_call_failed", "model provider call failed") from cause
        except M5CapabilityError as wrapped:
            code, message = m3_api._public_failure(wrapped)
    assert code == "model_capacity"
    assert message == "The selected model is temporarily at capacity."
    assert "private-provider-value" not in message


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
        quiz_version = quiz["versions"][-1]
        content = quiz_version["content"]
        assert "answer_key" not in content and "explanation" not in content
        assert "rationale" not in content
        content = json.loads(content)
        assert content["schema_version"] == "m3.tiered_quiz.v1"
        assert content["title"]
        assert content["personalization"]["profile_snapshot_id"]
        assert quiz_version["metadata"]["personalization"]["profile_snapshot_id"]

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

        audit = client.get(f"/api/v1/m3/tasks/{task_id}/agent-audit", headers=owner_headers)
        assert audit.status_code == 200
        assert [item["role"] for item in audit.json()["items"]] == [
            "diagnosis",
            "domain_generation",
            "evidence_review",
            "decision_orchestration",
        ]
        assert all(item["status"] == "completed" for item in audit.json()["items"])
        assert audit.json()["items"][1]["candidateSummary"]
        assert audit.json()["items"][2]["validation"]
        assert audit.json()["items"][3]["decisionSummary"]
        assert client.get(
            f"/api/v1/m3/tasks/{task_id}/agent-audit",
            headers=outsider_headers,
        ).status_code == 403
        audit_text = json.dumps(audit.json(), ensure_ascii=False).lower()
        for forbidden in (
            "system_prompt",
            "user_prompt",
            "api_key",
            "raw_log",
            "chain_of_thought",
            "private_reasoning",
            "bearer ",
        ):
            assert forbidden not in audit_text
        assert not __import__("re").search(r"\bsk-[a-z0-9_-]{8,}\b", audit_text)

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


def test_m3_generation_capacity_failure_is_a_sanitized_retryable_stage(monkeypatch):
    monkeypatch.setattr(m3_api, "_llm_from_request", lambda request: ProfileAwareFakeLLM())
    original_generate = m3_api.M3PersonalizedResourceGenerator.generate
    calls = 0

    async def capacity_then_success(self, session, *, context, task_id=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("Selected model is at capacity; api_key=sk-private-capacity-value")
        return await original_generate(self, session, context=context, task_id=task_id)

    monkeypatch.setattr(m3_api.M3PersonalizedResourceGenerator, "generate", capacity_then_success)

    with TestClient(app) as client:
        headers = auth_headers(client, f"m3-api-capacity-{uuid4().hex[:10]}")
        profile_id = client.get("/api/v1/m3/profiles", headers=headers).json()["profiles"][0]["profile_id"]
        task = _post(client, "/api/v1/m3/tasks", headers, {
            "profile_id": profile_id,
            "idempotency_key": f"m3-api-capacity-task-{uuid4().hex}",
        })
        task_id = task["id"]
        _post(client, f"/api/v1/m3/tasks/{task_id}/start", headers)
        _post(client, f"/api/v1/m3/tasks/{task_id}/diagnose", headers)

        failed = client.post(f"/api/v1/m3/tasks/{task_id}/generate", headers=headers)
        assert failed.status_code == 422
        audit = client.get(f"/api/v1/m3/tasks/{task_id}/agent-audit", headers=headers).json()
        assert [item["status"] for item in audit["items"]] == ["completed", "failed"]
        assert audit["items"][-1]["validation"] == "Stage failed: model_capacity."
        assert "retry later" in audit["items"][-1]["decisionSummary"].lower()
        serialized = json.dumps(audit, ensure_ascii=False).lower()
        assert "sk-private-capacity-value" not in serialized
        assert "api_key" not in serialized

        generated = _post(client, f"/api/v1/m3/tasks/{task_id}/generate", headers)
        assert generated["resources"]
        recovered = client.get(f"/api/v1/m3/tasks/{task_id}/agent-audit", headers=headers).json()
        assert [item["status"] for item in recovered["items"]] == ["completed", "failed", "completed"]
        assert recovered["items"][-1]["role"] == "domain_generation"


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
