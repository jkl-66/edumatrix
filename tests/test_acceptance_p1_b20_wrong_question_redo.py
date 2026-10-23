from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import (
    Base,
    DBAssessmentAttempt,
    DBAssessmentQuestion,
    DBAssessmentQuestionVersion,
    DBLearningEvent,
    DBQuizRecord,
    DBStudentProfile,
    DBUser,
    DBWrongQuestion,
)
from app.wrong_question_read_model import (
    WrongQuestionRedoError,
    prepare_wrong_question_redo,
)
from app.m5_assessment_core import ensure_legacy_quiz_question_version


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _legacy_wrong(
    session,
    *,
    suffix: str,
    username: str = "student-b20",
    owner_public_id: str = "owner-b20",
    question: str = "为什么激活函数的误差项依赖后一层误差项？",
    options: list[str] | None = None,
    correct_answer: str = "因为链式法则会把后一层误差反向传播到当前层。",
):
    if session.query(DBUser).filter_by(public_id=owner_public_id).one_or_none() is None:
        session.add(DBUser(
            public_id=owner_public_id,
            username=username,
            hashed_password="x",
            role="student",
        ))
        session.add(DBStudentProfile(student_id=username))
    quiz = DBQuizRecord(
        id=f"quiz-b20-{suffix}",
        student_id=username,
        question=question,
        student_answer="旧答案保持不变",
        correct_answer=correct_answer,
        options=options or [],
        accuracy_score=0.2,
        student_confidence=0.4,
        target_concept="反向传播",
        feedback="旧评分反馈保持不变",
        attempt_number=1,
    )
    wrong = DBWrongQuestion(
        student_id=username,
        quiz_record_id=quiz.id,
        source_object_id=None,
        concept_name="反向传播",
        wrong_reason_category="pending_confirmation",
        notes="用户错题笔记保持不变",
    )
    session.add_all([quiz, wrong])
    session.commit()
    return session.query(DBUser).filter_by(public_id=owner_public_id).one(), quiz, wrong


def test_prepare_legacy_subjective_redo_binds_replayable_version_without_fake_attempts_or_events():
    session = _session()
    owner, quiz, wrong = _legacy_wrong(session, suffix="subjective")
    legacy_snapshot = {
        "question": quiz.question,
        "student_answer": quiz.student_answer,
        "correct_answer": quiz.correct_answer,
        "accuracy_score": quiz.accuracy_score,
        "feedback": quiz.feedback,
        "notes": wrong.notes,
    }

    prepared = prepare_wrong_question_redo(
        session,
        wrong_id=wrong.id,
        student_id=owner.username,
        owner_public_id=owner.public_id,
    )
    session.commit()

    rebound = session.get(DBWrongQuestion, prepared["wrong_question_id"])
    version = session.get(DBAssessmentQuestionVersion, prepared["question_version_id"])
    question = session.get(DBAssessmentQuestion, version.question_id)
    assert rebound.source_object_id == version.id
    assert prepared["question"]["type"] == "short_answer"
    assert prepared["question"]["response_spec"]["supports_ai_initial_grading"] is True
    assert question.question_type == "short_answer"
    assert version.scoring_rule["type"] == "ai_rubric"
    assert version.scoring_rule["criteria"]
    assert session.query(DBAssessmentAttempt).count() == 0
    assert session.query(DBLearningEvent).count() == 0
    assert {
        "question": quiz.question,
        "student_answer": quiz.student_answer,
        "correct_answer": quiz.correct_answer,
        "accuracy_score": quiz.accuracy_score,
        "feedback": quiz.feedback,
        "notes": rebound.notes,
    } == legacy_snapshot

    replay = prepare_wrong_question_redo(
        session,
        wrong_id=rebound.id,
        student_id=owner.username,
        owner_public_id=owner.public_id,
    )
    session.commit()
    assert replay["question_version_id"] == prepared["question_version_id"]
    assert replay["created"] is False
    assert session.query(DBAssessmentQuestion).count() == 1
    assert session.query(DBAssessmentQuestionVersion).count() == 1
    assert session.query(DBAssessmentAttempt).count() == 0
    assert session.query(DBLearningEvent).count() == 0


def test_prepare_legacy_choice_redo_returns_single_choice_schema():
    session = _session()
    owner, _, wrong = _legacy_wrong(
        session,
        suffix="choice",
        question="以下哪一项是链式法则的作用？",
        options=["A. 只计算前向值", "B. 逐层传递导数"],
        correct_answer="B",
    )

    prepared = prepare_wrong_question_redo(
        session,
        wrong_id=wrong.id,
        student_id=owner.username,
        owner_public_id=owner.public_id,
    )
    assert prepared["question"]["type"] == "single_choice"
    assert prepared["question"]["options"] == ["A. 只计算前向值", "B. 逐层传递导数"]
    assert prepared["question"]["response_spec"]["input_kind"] == "single_choice"


def test_prepare_redo_rejects_another_student_without_changing_legacy_rows():
    session = _session()
    owner, quiz, wrong = _legacy_wrong(session, suffix="scope")
    other, _, _ = _legacy_wrong(
        session,
        suffix="other",
        username="student-b20-other",
        owner_public_id="owner-b20-other",
    )
    before = (wrong.source_object_id, quiz.student_answer, session.query(DBAssessmentAttempt).count())

    with pytest.raises(WrongQuestionRedoError) as caught:
        prepare_wrong_question_redo(
            session,
            wrong_id=wrong.id,
            student_id=other.username,
            owner_public_id=other.public_id,
        )

    assert caught.value.code == "wrong_question_unknown"
    assert (wrong.source_object_id, quiz.student_answer, session.query(DBAssessmentAttempt).count()) == before
    assert owner.username != other.username


def test_prepare_redo_rejects_a_wrongly_bound_canonical_version_owner():
    session = _session()
    owner, _, wrong = _legacy_wrong(session, suffix="bound-owner")
    other, other_quiz, _ = _legacy_wrong(
        session,
        suffix="bound-other",
        username="student-b20-bound-other",
        owner_public_id="owner-b20-bound-other",
    )
    foreign_version = ensure_legacy_quiz_question_version(
        session,
        owner_public_id=other.public_id,
        quiz_record=other_quiz,
    )["version"]
    wrong.source_object_id = foreign_version.id
    session.commit()

    with pytest.raises(WrongQuestionRedoError) as caught:
        prepare_wrong_question_redo(
            session,
            wrong_id=wrong.id,
            student_id=owner.username,
            owner_public_id=owner.public_id,
        )

    assert caught.value.code == "wrong_question_forbidden"
