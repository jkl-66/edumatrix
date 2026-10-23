import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, DBModelCall
from app.m5_legacy_calls import audited_legacy_text_call
import web_search_api


class Backend:
    model = "web-call-test-model"

    def __init__(self, output=None, *, error=None):
        self.output = output
        self.error = error

    async def generate(self, system_prompt, user_prompt, *, role):
        if self.error is not None:
            raise self.error
        return self.output


def _fixture():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    async def database_runner(operation, *args):
        return operation(session, *args)

    return session, database_runner


def _call(backend, runner, *, operation="web_search_summary"):
    return asyncio.run(audited_legacy_text_call(
        backend,
        system_prompt="system",
        user_prompt="private query and web content",
        role="极客助教",
        operation=operation,
        capability="summarize",
        owner_public_id="web-owner-public",
        input_summary={
            "result_count": 2,
            "web_content_included": False,
        },
        trace_id="web-shared-trace",
        database_runner=runner,
    ))


def test_audited_web_call_records_owner_trace_and_private_summary():
    session, runner = _fixture()

    assert _call(Backend("summary"), runner) == "summary"
    row = session.query(DBModelCall).one()

    assert row.owner_public_id == "web-owner-public"
    assert row.trace_id == "web-shared-trace"
    assert row.prompt_version == "legacy_web_search_summary:1.0"
    assert (row.status, row.error_code) == ("completed", "")
    assert "private query" not in str(row.input_summary)
    assert "web content" not in str(row.input_summary)


def test_audited_web_call_provider_failure_is_terminal():
    session, runner = _fixture()

    with pytest.raises(RuntimeError, match="provider unavailable"):
        _call(Backend(error=RuntimeError("provider unavailable")), runner)

    row = session.query(DBModelCall).one()
    assert (row.status, row.error_code) == (
        "failed", "web_search_summary_provider_failed",
    )


def test_audited_web_call_cancellation_is_terminal_and_propagates():
    session, runner = _fixture()

    with pytest.raises(asyncio.CancelledError):
        _call(Backend(error=asyncio.CancelledError()), runner)

    row = session.query(DBModelCall).one()
    assert (row.status, row.error_code) == ("failed", "client_disconnected")


def test_web_search_endpoint_passes_authenticated_public_owner(monkeypatch):
    captured = {}

    class Request:
        headers = {}

        async def json(self):
            return {"query": "gradient", "student_id": "learner-name"}

    async def fake_search(query, max_results):
        return [{"title": "Result", "url": "https://example.test/a", "snippet": "Body"}]

    async def fake_call(llm, **kwargs):
        captured.update(kwargs)
        return "governed summary"

    async def fake_run_db(operation, *args):
        return None

    web_search_api._search_cache.clear()
    monkeypatch.setattr(web_search_api, "_perform_web_search", fake_search)
    monkeypatch.setattr(web_search_api, "_get_llm", lambda request: asyncio.sleep(0, result=Backend("unused")))
    monkeypatch.setattr(web_search_api, "audited_legacy_text_call", fake_call)
    monkeypatch.setattr(web_search_api, "run_db_op", fake_run_db)

    result = asyncio.run(web_search_api.web_search(
        Request(),
        current_user=SimpleNamespace(
            public_id="authenticated-public-owner",
            username="learner-name",
            role="student",
        ),
    ))

    assert result["summary"] == "governed summary"
    assert captured["owner_public_id"] == "authenticated-public-owner"
    assert captured["operation"] == "web_search_summary"
