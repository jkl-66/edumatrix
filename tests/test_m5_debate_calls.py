import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, DBModelCall, DBUser
from drag_debate import DebateAugmentedRAG
from models import Evidence, EvidenceModality, GraphContext, RetrievalBundle


class Backend:
    model = "debate-test-model"

    def __init__(self, output=None, *, error=None):
        self.output = output
        self.error = error
        self.calls = 0

    async def generate(self, system_prompt, user_prompt, *, role):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.output


def _fixture(backend):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(DBUser(
        public_id="debate-owner-public", username="debate-owner",
        hashed_password="test", role="student", is_active=True,
    ))
    session.commit()

    async def database_runner(operation, *args):
        return operation(session, *args)

    evidence = tuple(Evidence(
        id=f"e{i}", title=f"private title {i}", content="private evidence body",
        modality=EvidenceModality.TEXT, source="private source", score=0.8,
    ) for i in (1, 2))
    bundle = RetrievalBundle(
        query="private query", target="private target",
        graph_context=GraphContext("private target", ("private path",), (), ()),
        evidence=evidence,
    )
    return session, database_runner, bundle


def _run(backend, runner, bundle, **kwargs):
    return asyncio.run(DebateAugmentedRAG(llm=backend).aclean(
        bundle,
        owner_public_id="debate-owner-public",
        course_id=None,
        trace_id="m5-matrix-debate-trace",
        database_runner=runner,
        **kwargs,
    ))


def test_debate_strict_output_records_owner_trace_and_is_used():
    output = json.dumps([
        {"evidence_id": "e1", "pro_score": 0.9, "con_score": 0.1,
         "judge_score": 0.88, "reason": "relevant"},
        {"evidence_id": "e2", "pro_score": 0.2, "con_score": 0.9,
         "judge_score": 0.1, "reason": "conflict"},
    ])
    backend = Backend(output)
    session, runner, bundle = _fixture(backend)

    result = _run(backend, runner, bundle)
    row = session.query(DBModelCall).one()

    assert [item.id for item in result.clean_evidence] == ["e1"]
    assert row.owner_public_id == "debate-owner-public"
    assert row.trace_id == "m5-matrix-debate-trace"
    assert (row.status, row.error_code) == ("completed", "")
    summary = str(row.input_summary)
    assert "private query" not in summary
    assert "private evidence body" not in summary
    assert "private title" not in summary


def test_debate_invalid_output_is_failed_and_uses_deterministic_fallback():
    backend = Backend(json.dumps([
        {"evidence_id": "unknown", "pro_score": 0.9, "con_score": 0.1,
         "judge_score": 0.8, "reason": "invalid id"},
    ]))
    session, runner, bundle = _fixture(backend)

    result = _run(backend, runner, bundle)
    row = session.query(DBModelCall).one()

    assert len(result.clean_evidence) == 2
    assert (row.status, row.error_code) == (
        "failed", "evidence_debate_output_invalid",
    )


def test_debate_provider_failure_is_terminal_and_falls_back():
    backend = Backend(error=RuntimeError("provider unavailable"))
    session, runner, bundle = _fixture(backend)

    result = _run(backend, runner, bundle)
    row = session.query(DBModelCall).one()

    assert len(result.clean_evidence) == 2
    assert (row.status, row.error_code) == (
        "failed", "evidence_debate_provider_failed",
    )


def test_debate_cancellation_is_terminal_and_propagates():
    backend = Backend(error=asyncio.CancelledError())
    session, runner, bundle = _fixture(backend)

    with pytest.raises(asyncio.CancelledError):
        _run(backend, runner, bundle)

    row = session.query(DBModelCall).one()
    assert (row.status, row.error_code) == ("failed", "client_disconnected")


def test_unowned_debate_does_not_call_model():
    backend = Backend("unused")
    _, _, bundle = _fixture(backend)

    result = asyncio.run(DebateAugmentedRAG(llm=backend).aclean(bundle))

    assert backend.calls == 0
    assert all(item["method"] == "deterministic" for item in result.trajectory)
