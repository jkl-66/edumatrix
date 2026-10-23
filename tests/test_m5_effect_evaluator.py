import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agent_swarm import EffectEvaluatorAgent
from app.database import Base, DBModelCall
from models import AgentOutput, StudentProfile


class Backend:
    model = "evaluation-test-model"

    def __init__(self, output=None, *, error=None):
        self.output = output
        self.error = error

    async def generate(self, system_prompt, user_prompt, *, role):
        if self.error is not None:
            raise self.error
        return self.output


def _fixture(output=None, *, error=None):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    async def database_runner(operation, *args):
        return operation(session, *args)

    evaluator = EffectEvaluatorAgent(
        Backend(output, error=error), database_runner=database_runner,
    )
    profile = StudentProfile(
        student_id="evaluation-owner",
        concept_mastery={"private-concept": 0.35},
    )
    resources = (
        AgentOutput(
            agent="theory",
            resource_type="专业讲义",
            content="private-resource-content",
            citations=(),
        ),
        AgentOutput(
            agent="coder",
            resource_type="代码实操案例",
            content="private-code-content",
            citations=(),
        ),
    )
    return session, evaluator, profile, resources


def _evaluate(evaluator, profile, resources):
    return asyncio.run(evaluator.evaluate_async(
        profile,
        resources,
        owner_public_id="evaluation-owner",
        course_id="evaluation-course",
        trace_id="evaluation-parent-trace",
    ))


def test_effect_evaluator_records_strict_success_without_raw_profile_or_content():
    session, evaluator, profile, resources = _fixture(
        '{"accuracy":0.91,"completeness":0.8,"depth_match":0.75,"needs_replan":false}'
    )
    signal = _evaluate(evaluator, profile, resources)
    row = session.query(DBModelCall).one()

    assert signal.accuracy == 0.91
    assert signal.sandbox_error_rate == 0.18
    assert row.trace_id == "evaluation-parent-trace"
    assert row.prompt_version == "legacy_quantitative_evaluation:1.0"
    assert row.owner_public_id == "evaluation-owner"
    assert row.course_id == "evaluation-course"
    assert (row.status, row.error_code) == ("completed", "")
    summary = str(row.input_summary)
    assert "private-concept" not in summary
    assert "private-resource-content" not in summary
    assert "private-code-content" not in summary


def test_effect_evaluator_rejects_invalid_structure_and_uses_fallback():
    session, evaluator, profile, resources = _fixture(
        '{"accuracy":1.4,"completeness":0.8,"depth_match":0.7,"needs_replan":false}'
    )
    signal = _evaluate(evaluator, profile, resources)
    row = session.query(DBModelCall).one()

    assert signal.accuracy != 1.4
    assert (row.status, row.error_code) == ("failed", "evaluation_output_invalid")


def test_effect_evaluator_records_provider_failure_and_uses_fallback():
    session, evaluator, profile, resources = _fixture(error=RuntimeError("provider unavailable"))
    signal = _evaluate(evaluator, profile, resources)
    row = session.query(DBModelCall).one()

    assert 0.0 <= signal.accuracy <= 1.0
    assert (row.status, row.error_code) == ("failed", "evaluation_provider_failed")


def test_effect_evaluator_does_not_swallow_cancellation():
    session, evaluator, profile, resources = _fixture(error=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        _evaluate(evaluator, profile, resources)
    row = session.query(DBModelCall).one()
    assert (row.status, row.error_code) == ("failed", "client_disconnected")
