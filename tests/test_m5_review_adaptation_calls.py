import asyncio
import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.crud import build_review_adaptation_payload
from app.database import Base, DBModelCall, DBUser
import llm_client


class Backend:
    model = "deepseek-v4-flash"
    provider = "openai"
    thinking_mode = "max"
    reasoning_effort = "max"

    def __init__(self, output=None, *, error=None):
        self.output = output
        self.error = error
        self.calls = 0

    def generate(self, system_prompt, user_prompt, *, role):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.output


class AsyncBackend(Backend):
    async def generate(self, system_prompt, user_prompt, *, role):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.output


def _fixture(monkeypatch, backend):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    session.add(DBUser(
        public_id="review-owner-public",
        username="review-owner",
        hashed_password="test",
        role="student",
        is_active=True,
    ))
    session.commit()
    monkeypatch.setattr(llm_client, "DEFAULT_ASYNC_LLM", backend)
    return session, factory


def _run(factory, *, owner="review-owner-public"):
    return asyncio.run(build_review_adaptation_payload(
        "PRIVATE_CONCEPT",
        2,
        0.32,
        owner_public_id=owner,
        model_call_context={
            "trace_id": "m5-review-adaptation-trace",
            "session_factory": factory,
        },
    ))


def test_review_adaptation_records_owner_trace_and_minimal_summary(monkeypatch):
    backend = AsyncBackend('{"explanation":"先用生活中的分组类比理解概念，再完成一个最小练习并复述关键步骤。","mermaid":"mindmap\\n  root((概念))\\n    关系\\n    误区"}')
    session, factory = _fixture(monkeypatch, backend)

    result = _run(factory)
    row = session.query(DBModelCall).one()

    assert backend.calls == 1
    assert result["llm_backend"] == "deepseek-v4-flash"
    assert result["model"] == "deepseek-v4-flash"
    assert result["allow_fallback"] is False
    assert row.owner_public_id == "review-owner-public"
    assert row.trace_id == "m5-review-adaptation-trace"
    assert (row.status, row.error_code) == ("completed", "")
    summary = str(row.input_summary)
    assert "PRIVATE_CONCEPT" not in summary
    assert row.input_summary["concept_payload_included"] is False


def test_review_adaptation_invalid_output_is_failed_without_fallback(monkeypatch):
    backend = AsyncBackend('{"explanation":"太短","mermaid":"mindmap\\n  root((x))"}')
    session, factory = _fixture(monkeypatch, backend)

    with pytest.raises(Exception) as exc_info:
        _run(factory)
    row = session.query(DBModelCall).one()

    assert exc_info.value.code == "review_model_output_invalid"
    assert (row.status, row.error_code) == (
        "failed", "review_adaptation_output_invalid",
    )


def test_review_adaptation_provider_failure_is_terminal_without_fallback(monkeypatch):
    backend = AsyncBackend(error=RuntimeError("provider unavailable"))
    session, factory = _fixture(monkeypatch, backend)

    with pytest.raises(Exception) as exc_info:
        _run(factory)
    row = session.query(DBModelCall).one()

    assert exc_info.value.code == "review_model_call_failed"
    assert (row.status, row.error_code) == (
        "failed", "review_adaptation_provider_failed",
    )


def test_unowned_review_adaptation_fails_before_model_call(monkeypatch):
    backend = AsyncBackend("must not be used")
    _, factory = _fixture(monkeypatch, backend)

    with pytest.raises(Exception) as exc_info:
        _run(factory, owner=None)

    assert backend.calls == 0
    assert exc_info.value.code == "review_model_owner_required"
