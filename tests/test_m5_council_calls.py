import hashlib
import json
from functools import partial
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, DBModelCall, DBUser
from app.m5_legacy_calls import audited_legacy_sync_text_call
from manifold_alignment import CouncilDecisionEngine
import llm_client
import manifold_alignment


class Backend:
    model = "council-test-model"

    def __init__(self, output=None, *, error=None):
        self.output = output
        self.error = error
        self.calls = 0

    def generate(self, system_prompt, user_prompt, *, role):
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
        public_id="council-owner-public",
        username="council-owner",
        hashed_password="test",
        role="student",
        is_active=True,
    ))
    session.commit()
    monkeypatch.setattr(llm_client, "build_llm", lambda: backend)
    monkeypatch.setattr(
        manifold_alignment,
        "audited_legacy_sync_text_call",
        partial(audited_legacy_sync_text_call, session_factory=factory),
    )
    resources = [
        SimpleNamespace(
            agent="TeacherAgent",
            resource_type="讲义",
            content="PRIVATE_RESOURCE_BODY teacher details",
        ),
        SimpleNamespace(
            agent="ConsultantAgent",
            resource_type="实验",
            content="PRIVATE_RESOURCE_BODY consultant details",
        ),
    ]
    return session, resources


def _success_output():
    return json.dumps({
        "overall_passed": True,
        "conflicts": [],
        "verdicts": [
            {
                "agent": "TeacherAgent",
                "passed": True,
                "score": 0.94,
                "suggestion": "通过",
            },
            {
                "agent": "ConsultantAgent",
                "passed": True,
                "score": 0.91,
                "suggestion": "通过",
            },
        ],
    })


def _synthesize(resources):
    return CouncilDecisionEngine().synthesize(
        resources,
        "PRIVATE_TARGET_CONCEPT",
        owner_public_id="council-owner-public",
        trace_id="m5-matrix-council-trace",
    )


def test_council_success_records_owner_trace_and_minimal_summary(monkeypatch):
    backend = Backend(_success_output())
    session, resources = _fixture(monkeypatch, backend)

    result = _synthesize(resources)
    row = session.query(DBModelCall).one()

    assert result["overall_passed"] is True
    assert backend.calls == 1
    assert row.owner_public_id == "council-owner-public"
    assert row.trace_id == "m5-matrix-council-trace"
    assert (row.status, row.error_code) == ("completed", "")
    summary = str(row.input_summary)
    assert "PRIVATE_RESOURCE_BODY" not in summary
    assert "PRIVATE_TARGET_CONCEPT" not in summary
    assert "TeacherAgent" not in summary
    assert row.input_summary["resource_payload_included"] is False


def test_council_invalid_agent_is_output_invalid_and_falls_back(monkeypatch):
    output = json.loads(_success_output())
    output["verdicts"][1]["agent"] = "UnknownAgent"
    raw_output = json.dumps(output)
    backend = Backend(raw_output)
    session, resources = _fixture(monkeypatch, backend)

    result = _synthesize(resources)
    row = session.query(DBModelCall).one()

    assert result["advice"] == "Agentic校验不可用，采用确定性事实检查。"
    assert (row.status, row.error_code) == (
        "failed",
        "council_fact_review_output_invalid",
    )
    assert row.output_tokens > 0
    assert row.output_hash == hashlib.sha256(raw_output.encode("utf-8")).hexdigest()


def test_council_provider_failure_is_terminal_and_falls_back(monkeypatch):
    backend = Backend(error=RuntimeError("provider unavailable"))
    session, resources = _fixture(monkeypatch, backend)

    result = _synthesize(resources)
    row = session.query(DBModelCall).one()

    assert result["advice"] == "Agentic校验不可用，采用确定性事实检查。"
    assert (row.status, row.error_code) == (
        "failed",
        "council_fact_review_provider_failed",
    )


def test_unowned_council_does_not_build_or_call_model(monkeypatch):
    backend = Backend(_success_output())
    monkeypatch.setattr(
        llm_client,
        "build_llm",
        lambda: (_ for _ in ()).throw(AssertionError("must not build model")),
    )
    resources = [SimpleNamespace(
        agent="TeacherAgent",
        resource_type="讲义",
        content="deterministic content",
    )]

    result = CouncilDecisionEngine().synthesize(resources, "target")

    assert backend.calls == 0
    assert result["overall_passed"] is True
    assert result["advice"] == "Agentic校验不可用，采用确定性事实检查。"
