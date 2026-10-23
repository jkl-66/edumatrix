from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.m4_executor import M4RealModelExecutor, audit_m4_outbound_payload
from app.database import Base


class _M4LLM:
    def __init__(self, *, bad_source_once=False):
        self.requests = []
        self.bad_source_once = bad_source_once

    async def generate(self, system_prompt, user_prompt, *, role):
        request = json.loads(user_prompt)
        self.requests.append(request)
        original = request.get("original_request", request)
        case = original["blind_case"]
        profile = original["profile"]
        source_id = "ref-outside" if self.bad_source_once and len(self.requests) == 1 else "ref-allowed"
        return json.dumps({
            "case_id": case["case_id"],
            "status": "completed",
            "response_text": "grounded response",
            "claims": [{"claim_id": "c1", "text": "claim", "source_ref_ids": [source_id], "confidence": 0.8}],
            "adaptation": {
                "profile_id": case["profile_id"],
                "applied": True,
                "difficulty_band": profile["strategy"]["difficulty_band"],
                "scaffolding": profile["strategy"]["scaffolding"],
                "explanation": "profile strategy applied",
            },
            "uncertainty": "",
        })


def _case():
    return {
        "case_id": "M0-K01",
        "category": "knowledge_accuracy",
        "profile_id": "profile-m0-beginner",
        "objective": "explain source hashing",
        "input": "why hash a source",
    }


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def test_real_executor_uses_only_blind_input_and_persists_structured_evidence():
    llm = _M4LLM()
    engine, session = _session()
    output = asyncio.run(M4RealModelExecutor(
        llm, sources=({"source_ref_id": "ref-allowed", "title": "course", "excerpt": "source"},),
        session=session, trace_id="m4-test-success",
    ).execute(_case()))
    assert output.status == "completed"
    assert output.citation_count == output.locatable_citation_count == 1
    assert output.evidence["claims"][0]["source_ref_ids"] == ["ref-allowed"]
    serialized = json.dumps(llm.requests, ensure_ascii=False)
    assert "gold" not in serialized and "failure_branch" not in serialized and "difficulty\"" not in serialized
    session.close()
    engine.dispose()


def test_real_executor_retries_once_after_out_of_scope_citation():
    llm = _M4LLM(bad_source_once=True)
    engine, session = _session()
    output = asyncio.run(M4RealModelExecutor(
        llm, sources=({"source_ref_id": "ref-allowed", "title": "course", "excerpt": "source"},),
        session=session, trace_id="m4-test-repair",
    ).execute(_case()))
    assert output.evidence["claims"][0]["source_ref_ids"] == ["ref-allowed"]
    assert len(llm.requests) == 2
    assert "validation_feedback" in llm.requests[1]
    session.close()
    engine.dispose()


@pytest.mark.parametrize("payload", [
    {"gold": "hidden answer"},
    {"nested": {"failure_branch": "hidden branch"}},
    {"input": "contact learner@example.com"},
    {"input": "Authorization: Bearer abcdefghijklmnop"},
    {"input": "call 13800138000"},
])
def test_outbound_audit_rejects_forbidden_or_identity_data(payload):
    with pytest.raises(ValueError):
        audit_m4_outbound_payload(payload)


def test_outbound_audit_rejects_configured_secret(monkeypatch):
    monkeypatch.setenv("EDUMATRIX_LLM_API_KEY", "test-secret-value-123")
    with pytest.raises(ValueError):
        audit_m4_outbound_payload({"input": "test-secret-value-123"})
