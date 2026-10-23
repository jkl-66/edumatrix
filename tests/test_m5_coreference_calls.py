import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agent_swarm import ZPDPlannerAgent
from app.database import Base, DBModelCall, DBUser
from models import StudentProfile
import llm_client


class Backend:
    model = "coreference-test-model"

    def __init__(self, output=None, *, error=None):
        self.output = output
        self.error = error
        self.calls = 0

    async def generate(self, system_prompt, user_prompt, *, role):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.output


def _fixture(monkeypatch, backend):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    session.add(DBUser(
        public_id="coreference-owner-public",
        username="coreference-owner",
        hashed_password="test",
        role="student",
        is_active=True,
    ))
    session.commit()
    monkeypatch.setattr(llm_client, "DEFAULT_ASYNC_LLM", backend)

    async def database_runner(operation, *args):
        return operation(session, *args)

    profile = StudentProfile(
        student_id="coreference-owner",
        history=["上一轮正在讨论池化层的作用。"],
    )
    return session, database_runner, profile


def _run_extract(profile, database_runner, *, owner=True):
    async def execute():
        loop = asyncio.get_running_loop()
        context = None
        if owner:
            context = {
                "owner_public_id": "coreference-owner-public",
                "course_id": None,
                "trace_id": "m5-matrix-coreference-trace",
                "database_runner": database_runner,
            }
        return await asyncio.to_thread(
            ZPDPlannerAgent()._extract_concept_from_query,
            "这个怎么理解",
            profile,
            loop,
            model_call_context=context,
        )

    return asyncio.run(execute())


def test_coreference_success_records_owner_trace_and_minimal_summary(monkeypatch):
    backend = Backend("池化层")
    session, runner, profile = _fixture(monkeypatch, backend)

    result = _run_extract(profile, runner)
    row = session.query(DBModelCall).one()

    assert result == "池化层"
    assert backend.calls == 1
    assert row.owner_public_id == "coreference-owner-public"
    assert row.trace_id == "m5-matrix-coreference-trace"
    assert (row.status, row.error_code) == ("completed", "")
    summary = str(row.input_summary)
    assert "上一轮" not in summary
    assert "池化层" not in summary
    assert "这个怎么理解" not in summary
    assert row.input_summary["history_payload_included"] is False


def test_coreference_invalid_output_is_failed_and_falls_back(monkeypatch):
    backend = Backend("PRIVATE_UNKNOWN_CONCEPT")
    session, runner, profile = _fixture(monkeypatch, backend)

    result = _run_extract(profile, runner)
    row = session.query(DBModelCall).one()

    assert result is None
    assert (row.status, row.error_code) == (
        "failed",
        "coreference_resolution_output_invalid",
    )
    assert row.output_tokens > 0
    assert row.output_hash


def test_coreference_provider_failure_is_terminal_and_falls_back(monkeypatch):
    backend = Backend(error=RuntimeError("provider unavailable"))
    session, runner, profile = _fixture(monkeypatch, backend)

    result = _run_extract(profile, runner)
    row = session.query(DBModelCall).one()

    assert result is None
    assert (row.status, row.error_code) == (
        "failed",
        "coreference_resolution_provider_failed",
    )


def test_unowned_coreference_does_not_call_model(monkeypatch):
    backend = Backend("池化层")
    _, runner, profile = _fixture(monkeypatch, backend)

    result = _run_extract(profile, runner, owner=False)

    assert result is None
    assert backend.calls == 0
