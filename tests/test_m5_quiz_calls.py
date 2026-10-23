import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, DBModelCall
from quiz_api import (
    QuizGenerationOutput,
    QuizGradingOutput,
    SimilarQuizOutput,
    _call_quiz_model,
)


class Backend:
    model = "quiz-test-model"

    def __init__(self, outputs):
        self.outputs = list(outputs)

    async def generate(self, system_prompt, user_prompt, *, role):
        output = self.outputs.pop(0)
        if isinstance(output, BaseException):
            raise output
        return output


def _fixture(outputs):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    async def database_runner(operation, *args):
        return operation(session, *args)

    return session, Backend(outputs), database_runner


def _call(backend, database_runner, response_model, *, operation="generate", attempt=1):
    return asyncio.run(_call_quiz_model(
        backend,
        system_prompt="strict quiz system prompt",
        user_prompt="private quiz input",
        response_model=response_model,
        owner_public_id="quiz-owner",
        operation=operation,
        trace_id="quiz-parent-trace",
        attempt=attempt,
        database_runner=database_runner,
    ))


def test_quiz_generation_call_records_strict_success_without_raw_input():
    session, backend, runner = _fixture([
        '{"question":"Q","reference_answer":"A","concept":"C",'
        '"difficulty":"medium","hints":["H"],"options":[]}'
    ])
    result = _call(backend, runner, QuizGenerationOutput)
    row = session.query(DBModelCall).one()

    assert result["question"] == "Q"
    assert row.trace_id == "quiz-parent-trace"
    assert row.prompt_version == "legacy_quiz_generate:1.0"
    assert row.owner_public_id == "quiz-owner"
    assert (row.status, row.error_code) == ("completed", "")
    assert "private quiz input" not in str(row.input_summary)


@pytest.mark.parametrize(
    ("model", "output"),
    [
        (QuizGenerationOutput, '{"question":"Q","difficulty":"medium"}'),
        (QuizGradingOutput, '{"accuracy_score":2,"ai_confidence":1}'),
        (SimilarQuizOutput, '{"question":"Q","correct_answer":"A","difficulty":"medium"}'),
    ],
)
def test_quiz_call_rejects_incomplete_or_out_of_range_structures(model, output):
    session, backend, runner = _fixture([output])
    with pytest.raises(Exception):
        _call(backend, runner, model)
    row = session.query(DBModelCall).one()
    assert (row.status, row.error_code) == ("failed", "quiz_output_invalid")


def test_quiz_call_records_provider_failure():
    session, backend, runner = _fixture([RuntimeError("provider unavailable")])
    with pytest.raises(RuntimeError, match="provider unavailable"):
        _call(backend, runner, QuizGenerationOutput)
    row = session.query(DBModelCall).one()
    assert (row.status, row.error_code) == ("failed", "quiz_provider_failed")


def test_quiz_call_records_cancellation_without_swallowing_it():
    session, backend, runner = _fixture([asyncio.CancelledError()])
    with pytest.raises(asyncio.CancelledError):
        _call(backend, runner, QuizGenerationOutput)
    row = session.query(DBModelCall).one()
    assert (row.status, row.error_code) == ("failed", "client_disconnected")


def test_similar_quiz_retries_share_trace_and_keep_attempt_records():
    session, backend, runner = _fixture([
        "not json",
        '{"question":"Q2","options":[],"correct_answer":"A2",'
        '"explanation":"E2","python_validator":"","difficulty":"hard"}',
    ])
    with pytest.raises(Exception):
        _call(backend, runner, SimilarQuizOutput, operation="similar", attempt=1)
    result = _call(backend, runner, SimilarQuizOutput, operation="similar", attempt=2)
    rows = session.query(DBModelCall).order_by(DBModelCall.created_at).all()

    assert result["question"] == "Q2"
    assert len(rows) == 2
    assert {row.trace_id for row in rows} == {"quiz-parent-trace"}
    assert [row.input_summary["attempt"] for row in rows] == [1, 2]
    assert [(row.status, row.error_code) for row in rows] == [
        ("failed", "quiz_output_invalid"),
        ("completed", ""),
    ]
