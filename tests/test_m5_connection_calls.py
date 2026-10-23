import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, DBModelCall
import app.main as main_module


class Request:
    headers = {}


class TextBackend:
    model = "text-connection-model"


class VisionBackend:
    model = "vision-connection-model"

    def __init__(self, chunks):
        self.chunks = chunks

    async def generate_stream(self, system_prompt, user_prompt, *, role, images):
        for chunk in self.chunks:
            if isinstance(chunk, BaseException):
                raise chunk
            yield chunk


def _database_fixture(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    async def database_runner(operation, *args):
        return operation(session, *args)

    monkeypatch.setattr(main_module, "run_db_op", database_runner)
    return session


def _user():
    return SimpleNamespace(public_id="connection-owner-public")


def test_text_connection_endpoint_passes_authenticated_owner(monkeypatch):
    captured = {}

    async def fake_call(llm, **kwargs):
        captured.update(kwargs)
        return "API连接测试成功"

    monkeypatch.setattr(
        main_module, "build_swarm_from_headers",
        lambda headers: SimpleNamespace(llm=TextBackend()),
    )
    monkeypatch.setattr(main_module, "audited_legacy_text_call", fake_call)

    result = asyncio.run(main_module.test_llm_connection(Request(), _user()))

    assert result["status"] == "ok"
    assert captured["owner_public_id"] == "connection-owner-public"
    assert captured["operation"] == "text_connection_test"


def test_vision_connection_success_is_completed_and_private(monkeypatch):
    session = _database_fixture(monkeypatch)
    backend = VisionBackend(["vision ", "ok"])
    monkeypatch.setattr(
        main_module, "build_swarm_from_headers",
        lambda headers: SimpleNamespace(
            llm=SimpleNamespace(external_vision_backend=backend),
        ),
    )

    result = asyncio.run(main_module.test_vision_connection(Request(), _user()))
    row = session.query(DBModelCall).one()

    assert result["status"] == "ok"
    assert result["response"] == "vision ok"
    assert row.owner_public_id == "connection-owner-public"
    assert (row.status, row.error_code) == ("completed", "")
    summary = str(row.input_summary)
    assert "iVBOR" not in summary
    assert row.input_summary["image_payload_included"] is False


def test_vision_connection_partial_failure_is_audited_without_error_leak(monkeypatch):
    session = _database_fixture(monkeypatch)
    backend = VisionBackend(["partial output", RuntimeError("secret provider failure")])
    monkeypatch.setattr(
        main_module, "build_swarm_from_headers",
        lambda headers: SimpleNamespace(
            llm=SimpleNamespace(external_vision_backend=backend),
        ),
    )

    result = asyncio.run(main_module.test_vision_connection(Request(), _user()))
    row = session.query(DBModelCall).one()

    assert result == {
        "status": "error",
        "message": "视觉模型调用失败",
        "llm_type": "SimpleNamespace",
    }
    assert (row.status, row.error_code) == (
        "failed", "vision_connection_test_provider_failed",
    )
    assert row.output_tokens > 0
    assert row.output_hash


def test_vision_connection_cancellation_is_terminal_and_propagates(monkeypatch):
    session = _database_fixture(monkeypatch)
    backend = VisionBackend(["partial", asyncio.CancelledError()])
    monkeypatch.setattr(
        main_module, "build_swarm_from_headers",
        lambda headers: SimpleNamespace(
            llm=SimpleNamespace(external_vision_backend=backend),
        ),
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main_module.test_vision_connection(Request(), _user()))

    row = session.query(DBModelCall).one()
    assert (row.status, row.error_code) == ("failed", "client_disconnected")
    assert row.output_tokens > 0
