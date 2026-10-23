from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.coder import async_refine_code_agent
from app.auth import get_current_user
from app.database import Base, DBModelCall, DBUser
from app.main import app
from app.model_call_governance import governance_summary, scan_model_calls
import app.m5_api as m5_api


ROOT = Path(__file__).resolve().parents[1]


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


class CodeBackend:
    provider = "test"
    model = "code-json"

    async def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        assert "代码精炼器" in system_prompt
        assert role == "代码精炼器"
        return json.dumps({
            "import_blocks": "import torch\nimport torch.nn as nn",
            "tensor_init": "x = torch.randn(1, 1, 4, 4)",
            "pool_layer_api": "pool = nn.MaxPool2d(2, 2)",
            "forward_and_print": "print(pool(x))",
        })


def test_static_inventory_has_no_unregistered_or_active_direct_calls():
    summary = governance_summary(scan_model_calls(ROOT))
    assert summary["unregistered_count"] == 0
    assert summary["active_direct_count"] == 0
    assert summary["migration_required_count"] == 0


def test_code_refinement_uses_gateway_trace_and_strict_output():
    session = _session()
    output = asyncio.run(async_refine_code_agent(
        "最大池化课程",
        "pool = nn.AvgPool2d(2)",
        "池化类型不一致",
        llm=CodeBackend(),
        owner_public_id="owner-1",
        course_id=None,
        trace_id="matrix-trace-code-refine",
        session_factory=lambda: session,
    ))
    assert "nn.MaxPool2d" in output
    row = session.query(DBModelCall).one()
    assert (row.trace_id, row.capability, row.status) == (
        "matrix-trace-code-refine", "code", "completed",
    )
    persisted = json.dumps(row.input_summary, ensure_ascii=False)
    assert "最大池化课程" not in persisted
    assert "nn.AvgPool2d" not in persisted
    assert len(row.output_hash) == 64


def test_model_governance_api_is_operator_only_and_content_free(monkeypatch):
    session = _session()
    session.add(DBModelCall(
        trace_id="trace-safe", owner_public_id=None, capability="answer",
        prompt_version="safe:1", provider="test", model="model",
        status="completed", input_summary={"user_prompt_chars": 12},
        output_hash="a" * 64,
    ))
    session.commit()

    async def fake_run_db_op(operation, *args):
        return operation(session, *args)

    monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
    client = TestClient(app)
    identity = {"user": DBUser(public_id="student", username="student", role="student", is_active=True)}
    app.dependency_overrides[get_current_user] = lambda: identity["user"]
    try:
        denied = client.get("/api/v1/m5/model-governance")
        assert denied.status_code == 403
        identity["user"] = DBUser(public_id="teacher", username="teacher", role="teacher", is_active=True)
        response = client.get("/api/v1/m5/model-governance")
        assert response.status_code == 200
        payload = response.json()
        assert payload["unregistered_count"] == 0
        assert payload["active_direct_count"] == 0
        assert payload["raw_prompts_persisted"] is False
        assert payload["raw_outputs_persisted"] is False
        rendered = json.dumps(payload, ensure_ascii=False)
        assert "Secret" not in rendered
    finally:
        app.dependency_overrides.pop(get_current_user, None)
