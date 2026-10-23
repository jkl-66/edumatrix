import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import get_current_user
from app.database import Base, DBModelCall, DBUser
from app.main import app
from models import AgentOutput, GraphContext, StudentProfile
import stream_api
from stream_api import (
    _generate_socratic_teacher,
    _plan_socratic_move,
    _stream_socratic_teacher,
)


class Backend:
    model = "socratic-test-model"

    def __init__(self, *, plan=None, answer=None, stream=()):
        self.plan = plan
        self.answer = answer
        self.stream = list(stream)

    async def generate(self, system_prompt, user_prompt, *, role):
        value = self.plan if role == "教学规划师" else self.answer
        if isinstance(value, BaseException):
            raise value
        return value

    async def generate_stream(self, system_prompt, user_prompt, *, role):
        for value in self.stream:
            if isinstance(value, BaseException):
                raise value
            yield value


def _fixture(backend):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    async def database_runner(operation, *args):
        return operation(session, *args)

    common = {
        "system_prompt": "socratic system",
        "user_prompt": "private selected source and learner reply",
        "owner_public_id": "socratic-owner",
        "trace_id": "socratic-parent-trace",
        "database_runner": database_runner,
    }
    return session, backend, common


def test_socratic_consultant_and_teacher_share_trace_with_strict_plan():
    session, backend, common = _fixture(Backend(
        plan='{"pedagogical_move":"HINT_LADDER","focus_concept":"梯度"}',
        answer="先观察梯度方向。",
    ))

    async def exercise():
        plan = await _plan_socratic_move(backend, **common)
        answer = await _generate_socratic_teacher(backend, **common)
        return plan, answer

    plan, answer = asyncio.run(exercise())
    rows = session.query(DBModelCall).order_by(DBModelCall.created_at).all()

    assert plan["pedagogical_move"] == "HINT_LADDER"
    assert answer == "先观察梯度方向。"
    assert len(rows) == 2
    assert {row.trace_id for row in rows} == {"socratic-parent-trace"}
    assert {row.prompt_version for row in rows} == {
        "legacy_socratic_consultant:1.0",
        "legacy_socratic_teacher:1.0",
    }
    assert all(row.status == "completed" for row in rows)
    assert all("private selected source" not in str(row.input_summary) for row in rows)


def test_socratic_consultant_rejects_unknown_move():
    session, backend, common = _fixture(Backend(
        plan='{"pedagogical_move":"DIRECT_ANSWER","focus_concept":"梯度"}'
    ))
    with pytest.raises(Exception):
        asyncio.run(_plan_socratic_move(backend, **common))
    row = session.query(DBModelCall).one()
    assert (row.status, row.error_code) == (
        "failed", "socratic_consultant_output_invalid",
    )


def test_socratic_teacher_sync_provider_failure_is_terminal():
    session, backend, common = _fixture(Backend(answer=RuntimeError("offline")))
    with pytest.raises(RuntimeError, match="offline"):
        asyncio.run(_generate_socratic_teacher(backend, **common))
    row = session.query(DBModelCall).one()
    assert (row.status, row.error_code) == (
        "failed", "socratic_teacher_provider_failed",
    )


def test_socratic_teacher_stream_records_partial_failure():
    session, backend, common = _fixture(Backend(
        stream=["partial", RuntimeError("stream offline")]
    ))

    async def consume():
        chunks = []
        async for chunk in _stream_socratic_teacher(backend, **common):
            chunks.append(chunk)
        return chunks

    with pytest.raises(RuntimeError, match="stream offline"):
        asyncio.run(consume())
    row = session.query(DBModelCall).one()
    assert (row.status, row.error_code) == (
        "failed", "socratic_teacher_stream_failed",
    )
    assert row.output_tokens > 0


def test_socratic_teacher_cancellation_is_not_swallowed():
    session, backend, common = _fixture(Backend(answer=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_generate_socratic_teacher(backend, **common))
    row = session.query(DBModelCall).one()
    assert (row.status, row.error_code) == ("failed", "client_disconnected")


def test_regenerate_endpoint_passes_authenticated_owner_and_fresh_trace(monkeypatch):
    captured = {}
    profile = StudentProfile(student_id="regenerate-owner")

    class Planner:
        async def plan_async(self, rag, query, current_profile):
            return type("Retrieval", (), {
                "graph_context": GraphContext(query, (query,), (), ()),
            })()

    class Debate:
        async def aclean(self, retrieval):
            return type("DebateResult", (), {"clean_evidence": ()})()

    class Generator:
        async def generate(self, **kwargs):
            captured.update(kwargs)
            return AgentOutput(
                agent=kwargs["role"], resource_type=kwargs["resource_type"],
                content="regenerated", citations=(),
            )

    fake_swarm = type("Swarm", (), {
        "profile_store": {"regenerate-owner": profile},
        "planner": Planner(), "rag": object(), "debate": Debate(),
        "async_generator": Generator(),
    })()

    async def fake_run_db_op(operation, *args, **kwargs):
        return "saved-regenerated-note"

    monkeypatch.setattr(stream_api, "build_swarm_from_headers", lambda headers: fake_swarm)
    monkeypatch.setattr(stream_api, "run_db_op", fake_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: DBUser(
        public_id="regenerate-public-id", username="regenerate-owner",
        hashed_password="test", role="student", is_active=True,
    )
    try:
        response = TestClient(app).post("/api/stream/regenerate", json={
            "student_id": "regenerate-owner",
            "role": "理论教授",
            "resource_type": "专业讲义",
            "query": "private regeneration query",
        })
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200, response.text
    assert response.json()["content"] == "regenerated"
    context = captured["model_call_context"]
    assert context["owner_public_id"] == "regenerate-public-id"
    assert context["trace_id"].startswith("m5-regenerate-")
    assert "course_id" not in context


def test_runtime_direct_socratic_route_delegates_to_governed_handler(monkeypatch):
    from app.main import socratic_explain_direct

    captured = {}

    async def governed_handler(request, current_user):
        captured["owner"] = current_user.public_id
        captured["payload"] = await request.json()
        return {"status": "governed", "content": "delegated"}

    monkeypatch.setattr(stream_api, "socratic_explain", governed_handler)
    user = DBUser(
        public_id="socratic-public-id", username="socratic-owner",
        hashed_password="test", role="student", is_active=True,
    )

    class RequestStub:
        async def json(self):
            return {
                "student_id": "socratic-owner",
                "target_text": "private selected text",
            }

    result = asyncio.run(socratic_explain_direct(RequestStub(), user))
    assert result == {"status": "governed", "content": "delegated"}
    assert captured == {
        "owner": "socratic-public-id",
        "payload": {
            "student_id": "socratic-owner",
            "target_text": "private selected text",
        },
    }

    # The FastAPI route was bound before monkeypatching the module attribute;
    # exercise it separately and identify the governed implementation by its
    # unique fallback wording when no model is configured.
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        response = TestClient(app).post("/api/stream/explain", json={
            "student_id": "socratic-owner",
            "target_text": "private selected text",
        })
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "fallback"
    assert "请在后端对话框继续追问" in response.json()["content"]
