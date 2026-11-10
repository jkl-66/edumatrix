from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, DBAssessmentAttempt, DBAssessmentQuestion, DBAssessmentQuestionVersion, DBAssessmentRetestTask, DBQuizRecord, DBReviewPlan, DBStudentProfile, DBUser
from app.m5_assessment_core import (
    AssessmentCoreError, AttemptInput, MisconceptionCandidateInput,
    MisconceptionDecisionInput, QuestionVersionInput, create_question_version,
    decide_misconception, ensure_legacy_misconception_candidate,
    learner_attempt_payload, learner_question_payload, propose_misconception,
    learner_explanation_has_content, record_attempt, record_legacy_quiz_attempt, review_queue, schedule_delayed_retest,
    RetestAttemptInput, submit_delayed_retest,
)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _version(session):
    return create_question_version(
        session, owner_public_id="owner", course_id=None,
        question_type="single_choice", origin="manual",
        version=QuestionVersionInput(
            prompt="Which statement is correct?", options=("A", "B"),
            answer_key={"choice": "B"}, scoring_rule={"type": "exact"},
            explanation="B is correct", misconception_tags=("concept_confusion",),
        ),
    )[1]


def _legacy_quiz(session, *, quiz_id="legacy-quiz-1", options=None):
    session.add(DBUser(public_id="owner", username="learner", hashed_password="x"))
    session.add(DBStudentProfile(student_id="learner"))
    quiz = DBQuizRecord(
        id=quiz_id, student_id="learner", question="Which option is correct?",
        correct_answer="B. canonical", options=options if options is not None else ["A", "B"],
        target_concept="canonical assessment", attempt_number=1,
    )
    session.add(quiz)
    session.flush()
    return quiz


def test_learner_payload_never_exposes_answer_or_explanation():
    session = _session()
    version = _version(session)
    payload = learner_question_payload(version)
    assert payload["prompt"] and payload["options"] == ["A", "B"]
    assert "answer_key" not in payload and "explanation" not in payload and "scoring_rule" not in payload


def test_explanation_quality_gate_keeps_concise_teaching_and_code():
    question = {
        "prompt": "选择 model.fit 的正确作用",
        "options": ("A. 训练模型", "B. 只显示图形"),
        "answer_key": {"choice": "A"},
        "question_type": "single_choice",
        "knowledge_point": "模型训练",
    }
    assert not learner_explanation_has_content("", **question)
    assert not learner_explanation_has_content(
        "答案已依据课程来源核验。生成蓝图已经确认。", **question,
    )
    assert learner_explanation_has_content(
        "正确答案是A。model.fit(X, y)会根据训练样本拟合参数，model.predict(X)则用于产生预测。",
        **question,
    )
    assert learner_explanation_has_content(
        "正确答案是A。执行 `model.fit(X, y)` 后，模型会得到训练出的参数。",
        **question,
    )
    assert learner_explanation_has_content("参考答案：A。因为2+3=5。", **question)
    assert learner_explanation_has_content("```python\nsource_ref = [1, 2]\nprint(sum(source_ref))  # 3\n```", **question)


@pytest.mark.parametrize("stamp", [datetime(2026, 10, 25, 13, 27), datetime(2026, 10, 25, 21, 27, tzinfo=timezone(timedelta(hours=8)))])
def test_attempt_history_time_keeps_the_instant_for_local_display(stamp):
    attempt = DBAssessmentAttempt(id="time-test", question_version_id="question-test", submitted_at=stamp)
    returned = datetime.fromisoformat(learner_attempt_payload(attempt)["submitted_at"])
    assert returned.tzinfo is not None
    assert returned.astimezone(timezone(timedelta(hours=8))).hour == 21
    assert returned.minute == 27
    assert attempt.submitted_at == stamp


def test_attempt_is_version_bound_idempotent_and_conflict_safe():
    session = _session()
    version = _version(session)
    attempt = AttemptInput(
        question_version_id=version.id, idempotency_key="attempt-key-001",
        answer={"choice": "A"},
    )
    first, created = record_attempt(session, owner_public_id="owner", attempt=attempt)
    replay, replay_created = record_attempt(session, owner_public_id="owner", attempt=attempt)
    assert created is True and replay_created is False and replay.id == first.id
    assert first.question_version_id == version.id
    with pytest.raises(AssessmentCoreError, match="another attempt"):
        record_attempt(session, owner_public_id="owner", attempt=attempt.model_copy(update={"answer": {"choice": "B"}}))


def test_incomplete_legacy_choices_do_not_create_grades_or_mastery_but_keep_history():
    from app.database import DBAssessmentAbilityState, DBAssessmentGradingResult

    session = _session()
    version = _version(session)
    attempt = AttemptInput(question_version_id=version.id, idempotency_key="legacy-history-363", answer={"choice": "B"})
    original, _ = record_attempt(session, owner_public_id="owner", attempt=attempt)
    # Model an old stored version with missing option content, not a new question.
    version.options = ["A. 有效内容", "B. source_ref: src-old-material"]
    session.flush()
    stored = (version.options[:], version.answer_key.copy(), version.content_hash, original.score)
    counts = [session.query(model).count() for model in (DBAssessmentAttempt, DBAssessmentGradingResult)]
    ability = session.query(DBAssessmentAbilityState).one()
    state = (ability.response_count, list(ability.theta), ability.lock_version)
    payload = learner_question_payload(version, session.get(DBAssessmentQuestion, version.question_id))
    assert payload["options"] == [] and "选项" in payload["content_issue"]
    with pytest.raises(AssessmentCoreError) as error:
        record_attempt(session, owner_public_id="owner", attempt=attempt.model_copy(update={"idempotency_key": "legacy-new-attempt-363"}))
    assert error.value.code == "question_content_incomplete"
    replay, created = record_attempt(session, owner_public_id="owner", attempt=attempt)
    assert replay.id == original.id and not created
    assert counts == [session.query(model).count() for model in (DBAssessmentAttempt, DBAssessmentGradingResult)]
    assert state == (ability.response_count, list(ability.theta), ability.lock_version)
    assert stored == (version.options, version.answer_key, version.content_hash, original.score)


@pytest.mark.parametrize("bad_option", ["B. ", "B. source_ref: src-old-material"])
def test_new_questions_require_actual_option_bodies(bad_option):
    session = _session()
    with pytest.raises(AssessmentCoreError) as error:
        create_question_version(session, owner_public_id="owner", course_id=None,
            question_type="single_choice", origin="manual", version=QuestionVersionInput(
                prompt="哪项正确？", options=("A. 实际选项", bad_option),
                answer_key={"choice": "A"}, scoring_rule={"type": "exact"}))
    assert error.value.code == "question_options_invalid"
    assert session.query(DBAssessmentQuestionVersion).count() == 0


def test_adaptive_selection_skips_incomplete_legacy_question():
    from app.m5_assessment_core import select_cat_question
    session = _session()
    bad = _version(session)
    good = _version(session)
    bad.options = []
    selected, trace, _ = select_cat_question(session, owner_public_id="owner", course_id=None,
        candidates=[(session.get(DBAssessmentQuestion, version.question_id), version) for version in (bad, good)])
    assert selected.id == good.id
    assert [item["question_version_id"] for item in trace.candidate_metrics] == [good.id]


def test_misconception_requires_owner_decision_before_review_queue():
    session = _session()
    version = _version(session)
    attempt, _ = record_attempt(session, owner_public_id="owner", attempt=AttemptInput(
        question_version_id=version.id, idempotency_key="attempt-key-002",
        answer={"choice": "A"},
    ))
    review = propose_misconception(
        session, owner_public_id="owner", attempt_id=attempt.id,
        candidate=MisconceptionCandidateInput(
            category="concept_confusion", rationale="A and B were confused",
            evidence={"answer": "A"}, model_confidence=0.7,
        ),
    )
    assert review_queue(session, owner_public_id="owner") == ()
    decide_misconception(
        session, owner_public_id="owner", review_id=review.id,
        decision=MisconceptionDecisionInput(decision="modify", category="knowledge_gap", note="I did not know this concept"),
    )
    queue = review_queue(session, owner_public_id="owner")
    assert len(queue) == 1 and queue[0]["category"] == "knowledge_gap"
    assert queue[0]["stable_mastery"] is False


def test_rejected_misconception_never_enters_queue_and_owner_boundary_holds():
    session = _session()
    version = _version(session)
    attempt, _ = record_attempt(session, owner_public_id="owner", attempt=AttemptInput(
        question_version_id=version.id, idempotency_key="attempt-key-003",
        answer={"choice": "A"},
    ))
    with pytest.raises(AssessmentCoreError, match="another owner"):
        propose_misconception(
            session, owner_public_id="intruder", attempt_id=attempt.id,
            candidate=MisconceptionCandidateInput(category="careless"),
        )
    review = propose_misconception(
        session, owner_public_id="owner", attempt_id=attempt.id,
        candidate=MisconceptionCandidateInput(category="careless"),
    )
    decide_misconception(
        session, owner_public_id="owner", review_id=review.id,
        decision=MisconceptionDecisionInput(decision="reject", note="not enough evidence"),
    )
    assert review_queue(session, owner_public_id="owner") == ()


def test_database_immutability_triggers_apply_after_registered_migration():
    from app.migrations import apply_registered_migrations

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    apply_registered_migrations(engine)
    session = sessionmaker(bind=engine)()
    version = _version(session)
    attempt, _ = record_attempt(session, owner_public_id="owner", attempt=AttemptInput(
        question_version_id=version.id, idempotency_key="attempt-key-004",
        answer={"choice": "B"},
    ))
    session.commit()
    version.prompt = "mutated"
    with pytest.raises(Exception, match="immutable"):
        session.commit()
    session.rollback()
    stored_attempt = session.query(DBAssessmentAttempt).filter_by(id=attempt.id).one()
    stored_attempt.score = 0
    with pytest.raises(Exception, match="immutable"):
        session.commit()
    session.rollback()
    assert session.query(DBAssessmentQuestionVersion).filter_by(id=version.id).one().prompt != "mutated"


def test_server_grades_answers_and_formal_mode_hides_result_until_close():
    session = _session()
    version = _version(session)
    correct, _ = record_attempt(session, owner_public_id="owner", attempt=AttemptInput(
        question_version_id=version.id, idempotency_key="attempt-key-005",
        answer={"choice": "B"}, mode="practice",
    ))
    formal, _ = record_attempt(session, owner_public_id="owner", attempt=AttemptInput(
        question_version_id=version.id, idempotency_key="attempt-key-006",
        answer={"choice": "B"}, mode="formal",
    ))
    assert correct.score == 1 and correct.correct is True
    assert learner_attempt_payload(correct)["correct"] is True
    assert learner_attempt_payload(formal)["score"] is None
    assert learner_attempt_payload(formal)["correct"] is None


def test_review_queue_merges_confirmed_misconceptions_and_legacy_sm2():
    session = _session()
    session.add(DBUser(public_id="owner", username="learner", hashed_password="x"))
    session.add(DBStudentProfile(student_id="learner"))
    session.flush()
    session.add(DBReviewPlan(student_id="learner", concept="retrieval", priority=0.8,
                             course_id="course-1", next_review_at=datetime(2026, 10, 25, 23, 30)))
    version = _version(session)
    attempt, _ = record_attempt(session, owner_public_id="owner", attempt=AttemptInput(
        question_version_id=version.id, idempotency_key="attempt-key-007", answer={"choice": "A"},
    ))
    review = propose_misconception(
        session, owner_public_id="owner", attempt_id=attempt.id,
        candidate=MisconceptionCandidateInput(category="concept_confusion"),
    )
    decide_misconception(
        session, owner_public_id="owner", review_id=review.id,
        decision=MisconceptionDecisionInput(decision="accept"),
    )
    queue = review_queue(session, owner_public_id="owner")
    assert {item["source_type"] for item in queue} == {"misconception_review", "sm2_review_plan"}
    assert all(item["stable_mastery"] is False for item in queue)
    plan = next(item for item in queue if item["source_type"] == "sm2_review_plan")
    assert plan["due_at"] == "2026-10-25T23:30:00Z"
    assert plan["course_id"] == "course-1"
    assert "SM-2" not in plan["reason"]


def test_legacy_quiz_bridge_freezes_one_question_version_and_is_idempotent():
    session = _session()
    quiz = _legacy_quiz(session)
    first = record_legacy_quiz_attempt(
        session, owner_public_id="owner", quiz_record=quiz, attempt_number=1,
        student_answer="b) canonical", score=1.0, confidence=0.8, duration_seconds=12,
    )
    replay = record_legacy_quiz_attempt(
        session, owner_public_id="owner", quiz_record=quiz, attempt_number=1,
        student_answer="B", score=1.0, confidence=0.8, duration_seconds=12,
    )
    assert first["question_created"] is True and first["version_created"] is True
    assert first["attempt_created"] is True and replay["attempt_created"] is False
    assert first["question_id"] == replay["question_id"]
    assert first["question_version_id"] == replay["question_version_id"]
    assert first["attempt_id"] == replay["attempt_id"]
    assert session.query(DBAssessmentQuestion).count() == 1
    assert session.query(DBAssessmentQuestionVersion).count() == 1
    assert session.query(DBAssessmentAttempt).count() == 1
    version = session.query(DBAssessmentQuestionVersion).one()
    attempt = session.query(DBAssessmentAttempt).one()
    assert version.answer_key == {"choice": "B"}
    assert attempt.answer == {"choice": "B"}
    assert attempt.question_version_id == version.id


def test_legacy_quiz_bridge_rejects_attempt_replay_conflict():
    session = _session()
    quiz = _legacy_quiz(session)
    record_legacy_quiz_attempt(
        session, owner_public_id="owner", quiz_record=quiz, attempt_number=1,
        student_answer="A", score=0.0, confidence=0.4, duration_seconds=3,
    )
    with pytest.raises(AssessmentCoreError, match="another attempt"):
        record_legacy_quiz_attempt(
            session, owner_public_id="owner", quiz_record=quiz, attempt_number=1,
            student_answer="B", score=1.0, confidence=0.4, duration_seconds=3,
        )


def test_legacy_optionless_server_score_is_preserved_as_replayable_subjective_question():
    session = _session()
    quiz = _legacy_quiz(session, quiz_id="legacy-code-1", options=[])
    quiz.question = "请编写 Python 函数计算平均值"
    quiz.correct_answer = "def avg(values): return sum(values) / len(values)"
    result = record_legacy_quiz_attempt(
        session, owner_public_id="owner", quiz_record=quiz, attempt_number=2,
        student_answer="def avg(v): return sum(v)/len(v)", score=0.9,
        confidence=None, duration_seconds=None,
    )
    attempt = session.query(DBAssessmentAttempt).filter_by(id=result["attempt_id"]).one()
    question = session.query(DBAssessmentQuestion).filter_by(id=result["question_id"]).one()
    assert question.question_type == "short_answer"
    version = session.query(DBAssessmentQuestionVersion).filter_by(
        id=result["question_version_id"],
    ).one()
    assert version.scoring_rule["type"] == "ai_rubric"
    assert version.scoring_rule["criteria"]
    assert attempt.score == 0.9 and attempt.correct is True and attempt.grading_status == "graded"
    with pytest.raises(AssessmentCoreError, match="between zero and one"):
        record_legacy_quiz_attempt(
            session, owner_public_id="owner", quiz_record=quiz, attempt_number=3,
            student_answer="client injected", score=2.0, confidence=None, duration_seconds=None,
        )


def test_legacy_misconception_candidate_is_idempotent_and_confirmation_schedules_delayed_retest():
    session = _session()
    quiz = _legacy_quiz(session)
    bridge = record_legacy_quiz_attempt(
        session, owner_public_id="owner", quiz_record=quiz, attempt_number=1,
        student_answer="A", score=0.0, confidence=0.7, duration_seconds=4,
    )
    first, created = ensure_legacy_misconception_candidate(
        session, owner_public_id="owner", attempt_id=bridge["attempt_id"],
        category="concept_confusion", rationale="A and B were confused",
        evidence={"source": "legacy_quiz_grading"}, model_confidence=0.8,
    )
    replay, replay_created = ensure_legacy_misconception_candidate(
        session, owner_public_id="owner", attempt_id=bridge["attempt_id"],
        category="knowledge_gap", rationale="ignored on replay",
        evidence={}, model_confidence=0.2,
    )
    assert created is True and replay_created is False and replay.id == first.id
    decided = decide_misconception(
        session, owner_public_id="owner", review_id=first.id,
        decision=MisconceptionDecisionInput(decision="modify", category="knowledge_gap"),
    )
    task, task_created = schedule_delayed_retest(session, review=decided)
    replay_task, replay_task_created = schedule_delayed_retest(session, review=decided)
    assert task_created is True and replay_task_created is False and task.id == replay_task.id
    assert task.due_at >= decided.decided_at + timedelta(hours=24)
    assert task.status == "scheduled" and task.completion_attempt_id is None
    assert session.query(DBAssessmentRetestTask).count() == 1
    queue = review_queue(session, owner_public_id="owner")
    assert queue[0]["retest_task"]["id"] == task.id
    assert queue[0]["stable_mastery"] is False


def test_rejected_misconception_cannot_schedule_retest():
    session = _session()
    version = _version(session)
    attempt, _ = record_attempt(session, owner_public_id="owner", attempt=AttemptInput(
        question_version_id=version.id, idempotency_key="attempt-key-rejected",
        answer={"choice": "A"},
    ))
    review = propose_misconception(
        session, owner_public_id="owner", attempt_id=attempt.id,
        candidate=MisconceptionCandidateInput(category="careless"),
    )
    review = decide_misconception(
        session, owner_public_id="owner", review_id=review.id,
        decision=MisconceptionDecisionInput(decision="reject"),
    )
    with pytest.raises(AssessmentCoreError, match="confirmed"):
        schedule_delayed_retest(session, review=review)


def test_delayed_retest_enforces_due_time_and_only_correct_answer_completes():
    session = _session()
    quiz = _legacy_quiz(session)
    bridge = record_legacy_quiz_attempt(
        session, owner_public_id="owner", quiz_record=quiz, attempt_number=1,
        student_answer="A", score=0.0, confidence=0.5, duration_seconds=5,
    )
    review = propose_misconception(
        session, owner_public_id="owner", attempt_id=bridge["attempt_id"],
        candidate=MisconceptionCandidateInput(category="concept_confusion"),
    )
    review = decide_misconception(
        session, owner_public_id="owner", review_id=review.id,
        decision=MisconceptionDecisionInput(decision="accept"),
    )
    task, _ = schedule_delayed_retest(session, review=review)
    with pytest.raises(AssessmentCoreError, match="before its due time"):
        submit_delayed_retest(
            session, owner_public_id="owner", task_id=task.id,
            submission=RetestAttemptInput(idempotency_key="retest-early-001", answer={"choice": "B"}),
            now=task.due_at - timedelta(seconds=1),
        )
    task, wrong, wrong_created = submit_delayed_retest(
        session, owner_public_id="owner", task_id=task.id,
        submission=RetestAttemptInput(idempotency_key="retest-wrong-001", answer={"choice": "A"}),
        now=task.due_at,
    )
    assert wrong_created is True and wrong.correct is False and task.status == "due"
    task, correct, correct_created = submit_delayed_retest(
        session, owner_public_id="owner", task_id=task.id,
        submission=RetestAttemptInput(idempotency_key="retest-correct-001", answer={"choice": "B"}),
        now=task.due_at + timedelta(minutes=1),
    )
    assert correct_created is True and correct.correct is True
    assert task.status == "completed" and task.completion_attempt_id == correct.id
    replay_task, replay, replay_created = submit_delayed_retest(
        session, owner_public_id="owner", task_id=task.id,
        submission=RetestAttemptInput(idempotency_key="retest-correct-001", answer={"choice": "B"}),
        now=task.due_at + timedelta(minutes=2),
    )
    assert replay_created is False and replay.id == correct.id and replay_task.id == task.id
    with pytest.raises(AssessmentCoreError, match="already closed"):
        submit_delayed_retest(
            session, owner_public_id="owner", task_id=task.id,
            submission=RetestAttemptInput(idempotency_key="retest-new-after-close", answer={"choice": "B"}),
            now=task.due_at + timedelta(minutes=3),
        )
