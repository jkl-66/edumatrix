from __future__ import annotations

import asyncio
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import pytest
from fastapi import HTTPException

from app.database import (
    Base, DBAssessmentGradingResult, DBAssessmentQuestion,
    DBAssessmentQuestionVersion, DBAssessmentSelectionTrace,
)
from app.m5_assessment_core import (
    AIGradingOutput, AssessmentCoreError, AttemptInput, QuestionVersionInput,
    RubricCriterionResult, append_question_version, create_question_version,
    grade_code_submission, learner_attempt_payload, learner_question_payload, persist_ai_grading,
    persist_code_grading, record_attempt, select_cat_question,
)
from app.migrations import apply_registered_migrations


def _session(*, migrated: bool = False):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    if migrated:
        apply_registered_migrations(engine)
    return sessionmaker(bind=engine)()


def _rubric():
    return {
        "type": "ai_rubric",
        "version": "rubric-ml-v1",
        "correct_threshold": 0.6,
        "criteria": [
            {"id": "accuracy", "label": "准确性", "description": "概念与事实正确", "weight": 0.7},
            {"id": "reasoning", "label": "推理", "description": "推理链完整", "weight": 0.3},
        ],
    }


def _create(session, question_type: str, *, suffix: str = ""):
    options = ()
    answer_key = {}
    scoring_rule = {"type": "exact", "version": "objective-v1"}
    if question_type == "single_choice":
        options, answer_key = ("A. zero", "B. one"), {"choice": "B"}
    elif question_type == "multiple_choice":
        options, answer_key = ("A", "B", "C"), {"choices": ["A", "C"]}
        scoring_rule["partial_credit"] = True
    elif question_type == "true_false":
        answer_key = {"value": True}
    elif question_type == "fill_blank":
        answer_key = {"blanks": [["gradient descent", "GD"], ["learning rate"]]}
        scoring_rule.update({"partial_credit": True, "case_sensitive": False})
    elif question_type in {"short_answer", "open_task"}:
        answer_key, scoring_rule = {"reference_answer": "Use evidence and explain the mechanism."}, _rubric()
    elif question_type == "code":
        answer_key = {
            "entrypoint": "add",
            "hidden_tests": [
                {"args": [1, 2], "expected": 3},
                {"args": [-1, 1], "expected": 0},
            ],
        }
        scoring_rule = {"type": "hidden_tests", "version": "hidden-v1", "correct_threshold": 1.0}
    question, version = create_question_version(
        session,
        owner_public_id="teacher",
        course_id=None,
        question_type=question_type,
        origin="manual",
        version=QuestionVersionInput(
            prompt=f"Question {question_type} {suffix}",
            options=options,
            answer_key=answer_key,
            scoring_rule=scoring_rule,
            irt_parameters={"alpha": [1.0, 0.8, 0.6], "beta": [0.0, 0.1, -0.1], "gamma": 0.2},
        ),
    )
    question.status = "approved"
    session.flush()
    return question, version


def test_all_seven_types_validate_and_objective_graders_are_type_specific():
    session = _session()
    created = {kind: _create(session, kind) for kind in (
        "single_choice", "multiple_choice", "true_false", "fill_blank",
        "short_answer", "code", "open_task",
    )}
    answers = {
        "single_choice": {"choice": "b) one"},
        "multiple_choice": {"choices": ["C", "A"]},
        "true_false": {"value": "正确"},
        "fill_blank": {"blanks": ["gd", " Learning   Rate "]},
    }
    for index, (kind, answer) in enumerate(answers.items()):
        attempt, _ = record_attempt(
            session,
            owner_public_id="learner",
            attempt=AttemptInput(
                question_version_id=created[kind][1].id,
                idempotency_key=f"objective-{index}-attempt",
                answer=answer,
            ),
        )
        assert attempt.correct is True and attempt.score == 1.0
    for kind in ("short_answer", "code", "open_task"):
        payload = learner_question_payload(created[kind][1], created[kind][0])
        assert payload["question_type"] == kind
        assert "answer_key" not in payload and "scoring_rule" not in payload


@pytest.mark.parametrize("actual,expected,correct", [
    ("[2,4,6,8]", "[2, 4, 6, 8]", True),
    ("array([[2,3],[5,6]])", "[[2, 3], [5, 6]]", True),
    ("np.array([2.0,4.0])", "[2, 4]", True),
    ("[[2,4,6,8]]", "[2, 4, 6, 8]", False),
    ("[2,6,4,8]", "[2, 4, 6, 8]", False),
    ("[2,4,6,-8]", "[2, 4, 6, 8]", False),
    ("[True]", "[1]", False),
    ("['a b']", "['ab']", False),
    ("ab", "a b", False),
])
def test_numeric_array_fill_blank_ignores_layout_not_shape_order_or_values(actual, expected, correct):
    from app.m5_assessment_core import grade_objective_answer
    result = grade_objective_answer("fill_blank", {"blanks": [actual]}, {"blanks": [expected]}, {})
    assert result["correct"] is correct


@pytest.mark.parametrize("actual,expected,correct", [
    ("(3,4)", "(3, 4)", True),
    ("(3,\n 4)", "(3, 4)", True),
    ("(3, 4,)", "(3, 4)", True),
    ("(3,)", "(3, )", True),
    ("((2,3), (4,5))", "((2, 3), (4, 5))", True),
    ("[(2,3), (4,5)]", "[(2, 3), (4, 5)]", True),
    ("(4,3)", "(3, 4)", False),
    ("(3,5)", "(3, 4)", False),
    ("((3,4),)", "(3, 4)", False),
    ("[3,4]", "(3, 4)", False),
    ("(3,4)", "[3, 4]", False),
    ("[[2,3], [4,5]]", "[(2, 3), (4, 5)]", False),
    ("(3)", "(3,)", False),
    ("3", "(3,)", False),
    ("(True,4)", "(1, 4)", False),
    ("('3','4')", "(3, 4)", False),
    ("(3, 2+2)", "(3, 4)", False),
])
def test_numeric_tuple_fill_blank_preserves_container_shape_order_and_values(actual, expected, correct):
    from app.m5_assessment_core import grade_objective_answer
    result = grade_objective_answer("fill_blank", {"blanks": [actual]}, {"blanks": [expected]}, {})
    assert result["correct"] is correct


def test_fill_blank_replay_preserves_historical_grade_after_normalization_fix(monkeypatch):
    import app.m5_assessment_core as core
    from app.database import DBAssessmentAbilityState
    session = _session()
    question, version = create_question_version(
        session, owner_public_id="teacher", course_id=None, question_type="fill_blank", origin="manual",
        version=QuestionVersionInput(prompt="填写数组形状。", answer_key={"blanks": ["(3, 4)"]}, scoring_rule={"type": "exact"}),
    )
    question.status = "approved"
    session.flush()
    payload = AttemptInput(question_version_id=version.id, idempotency_key="tuple-legacy-368", answer={"blanks": ["(3,4)"]})
    grade = core.grade_objective_answer

    def legacy_grade(*args, **kwargs):
        # Explicitly simulate the pre-fix exact-text outcome in this isolated test.
        return {**grade(*args, **kwargs), "score": 0.0, "correct": False}

    with monkeypatch.context() as patch:
        patch.setattr(core, "grade_objective_answer", legacy_grade)
        old, _ = record_attempt(session, owner_public_id="learner", attempt=payload)
    original_hash = version.content_hash
    replay, created = record_attempt(session, owner_public_id="learner", attempt=payload)
    assert not created and replay.id == old.id and replay.score == 0.0
    assert session.query(DBAssessmentGradingResult).count() == 1
    assert session.query(DBAssessmentAbilityState).one().response_count == 1
    new, created = record_attempt(session, owner_public_id="learner", attempt=payload.model_copy(update={"idempotency_key": "tuple-new-368"}))
    assert created and new.correct is True and new.answer == {"blanks": ["(3,4)"]}
    again, created = record_attempt(session, owner_public_id="learner", attempt=payload.model_copy(update={"idempotency_key": "tuple-new-368"}))
    assert not created and again.id == new.id
    # The new normalization fixes the grade, while a disclosed repeat is a
    # correction rather than a second independent ability observation.
    assert session.query(DBAssessmentAbilityState).one().response_count == 1
    grading = session.query(DBAssessmentGradingResult).filter_by(attempt_id=new.id).one()
    assert grading.evidence["practice_context"]["kind"] == "correction"
    assert session.query(DBAssessmentGradingResult).count() == 2
    assert old.score == 0.0 and version.content_hash == original_hash
    with pytest.raises(AssessmentCoreError, match="idempotency key"):
        record_attempt(session, owner_public_id="learner", attempt=payload.model_copy(update={"answer": {"blanks": ["(4,3)"]}}))


def test_append_version_is_compare_and_set_and_old_version_remains_immutable():
    session = _session(migrated=True)
    question, first = _create(session, "single_choice")
    second = append_question_version(
        session,
        question=question,
        owner_public_id="teacher",
        expected_current_version_id=first.id,
        version=QuestionVersionInput(
            prompt="Revised prompt", options=("A", "B"),
            answer_key={"choice": "A"}, scoring_rule={"type": "exact"},
        ),
    )
    session.commit()
    assert second.version_number == 2 and question.current_version_id == second.id
    assert session.query(DBAssessmentQuestionVersion).filter_by(question_id=question.id).count() == 2
    with pytest.raises(AssessmentCoreError, match="current version changed"):
        append_question_version(
            session, question=question, owner_public_id="teacher",
            expected_current_version_id=first.id,
            version=QuestionVersionInput(
                prompt="Stale revision", options=("A", "B"),
                answer_key={"choice": "B"}, scoring_rule={"type": "exact"},
            ),
        )
    first.prompt = "mutated"
    with pytest.raises(Exception, match="immutable"):
        session.commit()


def test_ai_initial_grading_uses_frozen_rubric_and_updates_canonical_ability():
    session = _session()
    _, version = _create(session, "short_answer")
    attempt, _ = record_attempt(
        session,
        owner_public_id="learner",
        attempt=AttemptInput(
            question_version_id=version.id,
            idempotency_key="subjective-attempt-001",
            answer={"text": "Evidence supports the mechanism."},
        ),
    )
    assert attempt.grading_status == "pending"
    result, ability = persist_ai_grading(
        session,
        attempt_id=attempt.id,
        trace_id="trace-ai-001",
        output=AIGradingOutput(
            criteria=(
                RubricCriterionResult(
                    criterion_id="accuracy", score=0.8,
                    evidence=("The mechanism is identified.",),
                    justification="The core claim is correct.", improvement="Add a concrete example.",
                ),
                RubricCriterionResult(
                    criterion_id="reasoning", score=0.6,
                    evidence=("A causal link is present.",),
                    justification="Reasoning exists but is brief.", improvement="Explain each inference.",
                ),
            ),
            confidence=0.75,
            summary="AI 智能初评：核心正确，推理仍可展开。",
            improvement_plan=("补充例子", "展开推理"),
        ),
    )
    assert result.score == 0.74 and result.correct is True
    assert result.rubric_version == "rubric-ml-v1"
    assert result.evidence["label"] == "AI 智能初评"
    assert ability["applied"] is True and ability["after"]["response_count"] == 1
    replay, created = record_attempt(
        session, owner_public_id="learner",
        attempt=AttemptInput(question_version_id=version.id, idempotency_key="subjective-attempt-001",
                             answer={"text": "Evidence supports the mechanism."}),
    )
    assert not created and replay.id == attempt.id and replay.grading_status == "pending"
    assert replay.score is None and session.query(DBAssessmentGradingResult).count() == 1
    core_payload = learner_attempt_payload(replay, result)
    assert core_payload["score"] == result.score and core_payload["grading_status"] == "graded"

    correction, _ = record_attempt(session, owner_public_id="learner", attempt=AttemptInput(
        question_version_id=version.id, idempotency_key="subjective-correction-002",
        answer={"text": "A revised answer after reading feedback."}))
    corrected, correction_ability = persist_ai_grading(session, attempt_id=correction.id,
        trace_id="trace-ai-002", output=AIGradingOutput(
            criteria=tuple(RubricCriterionResult(criterion_id=name, score=1,
                evidence=("Revised answer meets the criterion.",), justification="Correct after feedback.", improvement="")
                for name in ("accuracy", "reasoning")), confidence=0.9, summary="订正正确。", improvement_plan=()))
    assert corrected.score == 1 and corrected.correct
    assert corrected.evidence["practice_context"]["kind"] == "correction"
    assert not correction_ability["applied"]
    assert learner_attempt_payload(correction, corrected)["practice_kind"] == "correction"


class _FakeRunner:
    execution_enabled = True

    async def run(self, code):
        passed = "def add" in code
        return ("__EDUMATRIX_TEST__true\n" if passed else "__EDUMATRIX_TEST__false\n", "", 0.01)


def test_code_hidden_tests_return_only_sanitized_evidence():
    session = _session()
    _, version = _create(session, "code")
    attempt, _ = record_attempt(
        session,
        owner_public_id="learner",
        attempt=AttemptInput(
            question_version_id=version.id,
            idempotency_key="code-attempt-001",
            answer={"code": "def add(a, b): return a + b"},
        ),
    )
    raw = asyncio.run(grade_code_submission(version, attempt.answer, _FakeRunner()))
    result, ability = persist_code_grading(
        session, attempt_id=attempt.id, result=raw, trace_id="trace-code-001",
    )
    assert result.score == 1 and result.correct is True
    assert result.evidence["test_scope"] == "hidden"
    assert all(set(case) == {"case", "passed", "error_category"} for case in result.evidence["cases"])
    assert result.evidence["hidden_inputs_included"] is False
    assert result.evidence["hidden_expected_included"] is False
    assert result.evidence["suite_hash"] and ability["after"]["response_count"] == 1


def test_learner_question_payload_never_exposes_hidden_test_inputs_or_expected_values():
    session = _session()
    question, version = _create(session, "code")
    payload = learner_question_payload(version, question)
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    assert payload["response_spec"]["hidden_test_count"] == 2
    assert "answer_key" not in payload
    assert "hidden_tests" not in serialized
    assert '"expected"' not in serialized


def test_invalid_question_contract_maps_to_structured_http_422(monkeypatch):
    import app.m5_api as api_module
    from app.database import DBUser
    from app.m5_api import QuestionCreate, create_assessment_question

    session = _session()

    async def isolated_runner(operation):
        return operation(session)

    monkeypatch.setattr(api_module, "run_db_op", isolated_runner)
    payload = QuestionCreate.model_validate({
        "question_type": "short_answer",
        "origin": "manual",
        "version": {
            "prompt": "Explain validation data.",
            "answer_key": {"reference_answer": "Used for model selection."},
            "scoring_rule": {
                "type": "ai_rubric", "version": "invalid-rubric-v1",
                "criteria": [{"id": "purpose", "description": "Missing label", "weight": 1.0}],
            },
            "irt_parameters": {"alpha": [1.0, 0.5, 0.5], "beta": [0.0, 0.0, 0.0], "gamma": 0.0},
        },
    })
    with pytest.raises(HTTPException) as caught:
        asyncio.run(create_assessment_question(
            payload=payload,
            current_user=DBUser(public_id="teacher", username="teacher", role="teacher"),
        ))
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "rubric_invalid"


def test_cat_selection_persists_reproducible_trace_without_answer_keys():
    session = _session()
    candidates = []
    for index, beta in enumerate((-1.0, 0.0, 1.0)):
        question, version = _create(session, "single_choice", suffix=str(index))
        version.irt_parameters = {"alpha": [1.0, 0.8, 0.6], "beta": [beta, beta, beta], "gamma": 0.2}
        candidates.append((question, version))
    selected, trace, ability = select_cat_question(
        session,
        owner_public_id="learner",
        course_id=None,
        candidates=candidates,
        excluded_version_ids=(candidates[0][1].id,),
    )
    assert selected.id != candidates[0][1].id
    assert trace.algorithm_version == "mirt-d-optimal-v1"
    assert len(trace.candidate_metrics) == 2 and trace.trace_hash
    assert "answer" not in str(trace.candidate_metrics).lower()
    assert ability.response_count == 0
    assert session.query(DBAssessmentSelectionTrace).count() == 1


def test_invalid_type_specific_contracts_fail_closed():
    session = _session()
    with pytest.raises(AssessmentCoreError, match="answer_key.choice"):
        create_question_version(
            session, owner_public_id="teacher", course_id=None,
            question_type="single_choice", origin="manual",
            version=QuestionVersionInput(
                prompt="Broken", options=("A", "B"), answer_key={}, scoring_rule={"type": "exact"},
            ),
        )
    assert session.query(DBAssessmentQuestion).count() == 0
    assert session.query(DBAssessmentGradingResult).count() == 0
