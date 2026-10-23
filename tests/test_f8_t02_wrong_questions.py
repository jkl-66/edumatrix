from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import (
    Base,
    DBArtifact,
    DBArtifactVersion,
    DBAssessmentQuestion,
    DBAssessmentQuestionVersion,
    DBAssessmentAttempt,
    DBAssessmentExam,
    DBAssessmentExamItem,
    DBAssessmentExamReport,
    DBAssessmentExamResponse,
    DBAssessmentExamSitting,
    DBAssessmentExamVersion,
    DBAssessmentGradingResult,
    DBAssessmentRetestTask,
    DBChapter,
    DBCourse,
    DBKnowledgePoint,
    DBLearningEvent,
    DBMisconceptionReview,
    DBQuizRecord,
    DBReviewPlan,
    DBSourceDocument,
    DBSourceRef,
    DBStudentProfile,
    DBUser,
    DBWrongQuestion,
)
from app.learning_aggregation import aggregate_learning_event
from app.migrations import _install_f8_canonical_wrong_question_identity
from app.wrong_question_read_model import build_wrong_question_read_model


def _legacy_engine():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE users (public_id VARCHAR(64) PRIMARY KEY, username VARCHAR(64))"
        ))
        connection.execute(text("CREATE TABLE quiz_records (id VARCHAR(64) PRIMARY KEY)"))
        connection.execute(text(
            "CREATE TABLE assessment_attempts ("
            "id VARCHAR(64) PRIMARY KEY, owner_public_id VARCHAR(64), "
            "idempotency_key VARCHAR(128), question_version_id VARCHAR(64), submitted_at DATETIME)"
        ))
        connection.execute(text(
            "CREATE TABLE wrong_questions ("
            "id INTEGER PRIMARY KEY, student_id VARCHAR(64), quiz_record_id VARCHAR(64), "
            "source_event_id VARCHAR(64), source_object_id VARCHAR(64), "
            "concept_name VARCHAR(128), wrong_reason_category VARCHAR(128), "
            "pinned BOOLEAN DEFAULT 0, notes TEXT DEFAULT '', created_at DATETIME)"
        ))
        connection.execute(text(
            "CREATE UNIQUE INDEX ix_wrong_questions_event_object "
            "ON wrong_questions(source_event_id, COALESCE(source_object_id, '')) "
            "WHERE source_event_id IS NOT NULL"
        ))
        connection.execute(text(
            "CREATE TABLE wrong_question_video_links ("
            "id VARCHAR(64) PRIMARY KEY, wrong_question_id INTEGER)"
        ))
    return engine


def test_wrong_question_model_uses_learner_question_version_identity():
    constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in DBWrongQuestion.__table__.constraints
        if constraint.name
    }
    assert constraints["uq_wrong_question_student_question_version"] == (
        "student_id",
        "source_object_id",
    )
    assert "uq_wrong_question_event_object" not in constraints


def test_f8_migration_binds_merges_and_preserves_legacy_evidence():
    engine = _legacy_engine()
    machine_note = json.dumps(
        {"exam_id": "exam-1", "sitting_id": "sit-1", "position": 2, "score": 0.2}
    )
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO users(public_id,username) VALUES "
            "('owner-a','student-a'),('owner-b','student-b')"
        ))
        connection.execute(text(
            "INSERT INTO quiz_records(id) VALUES ('quiz-1')"
        ))
        connection.execute(text(
            "INSERT INTO assessment_attempts "
            "(id,owner_public_id,idempotency_key,question_version_id,submitted_at) VALUES "
            "('attempt-a1','owner-a','legacy-quiz-attempt:quiz-1:1','qv-shared','2026-08-01'),"
            "('attempt-a2','owner-a','legacy-quiz-attempt:quiz-1:2','qv-shared','2026-08-02'),"
            "('attempt-b1','owner-b','legacy-quiz-attempt:quiz-1:1','qv-shared','2026-08-01')"
        ))
        connection.execute(text(
            "INSERT INTO wrong_questions "
            "(id,student_id,quiz_record_id,source_event_id,source_object_id,concept_name,"
            "wrong_reason_category,pinned,notes,created_at) VALUES "
            "(1,'student-a','quiz-1',NULL,NULL,'反向传播','pending_confirmation',0,'','2026-08-01'),"
            "(2,'student-a',NULL,'event-2','quiz-1','反向传播','concept_confusion',1,"
            "'我总是漏掉链式法则','2026-08-02'),"
            "(3,'student-a',NULL,'event-3','qv-formal','优化器','pending_confirmation',0,:machine,'2026-08-03'),"
            "(4,'student-b','quiz-1','event-4',NULL,'反向传播','pending_confirmation',0,'','2026-08-01')"
        ), {"machine": machine_note})
        connection.execute(text(
            "INSERT INTO wrong_question_video_links(id,wrong_question_id) VALUES ('video-1',2)"
        ))

        _install_f8_canonical_wrong_question_identity(connection)

        rows = connection.execute(text(
            "SELECT id,student_id,quiz_record_id,source_event_id,source_object_id,"
            "wrong_reason_category,pinned,notes,created_at FROM wrong_questions ORDER BY id"
        )).mappings().all()
        assert [row["id"] for row in rows] == [1, 3, 4]
        assert rows[0]["student_id"] == "student-a"
        assert rows[0]["source_object_id"] == "qv-shared"
        assert rows[0]["source_event_id"] == "event-2"
        assert rows[0]["wrong_reason_category"] == "concept_confusion"
        assert rows[0]["pinned"] == 1
        assert rows[0]["notes"] == "我总是漏掉链式法则"
        assert str(rows[0]["created_at"]).startswith("2026-08-01")
        assert rows[1]["source_object_id"] == "qv-formal"
        assert rows[1]["notes"] == ""
        assert rows[2]["student_id"] == "student-b"
        assert rows[2]["source_object_id"] == "qv-shared"
        assert connection.execute(text(
            "SELECT wrong_question_id FROM wrong_question_video_links WHERE id='video-1'"
        )).scalar_one() == 1

        indexes = {item["name"] for item in inspect(connection).get_indexes("wrong_questions")}
        assert "ix_wrong_questions_student_question_version" in indexes
        assert "ix_wrong_questions_event_object" not in indexes
        with pytest.raises(IntegrityError):
            connection.execute(text(
                "INSERT INTO wrong_questions(id,student_id,source_object_id) "
                "VALUES (5,'student-a','qv-shared')"
            ))


def test_f8_migration_keeps_unmatched_legacy_rows_and_user_json_notes():
    engine = _legacy_engine()
    user_json = json.dumps({"exam_id": "a personal label", "reflection": "需要复习"})
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO users(public_id,username) VALUES ('owner-a','student-a')"
        ))
        connection.execute(text("INSERT INTO quiz_records(id) VALUES ('quiz-unmatched')"))
        connection.execute(text(
            "INSERT INTO wrong_questions "
            "(id,student_id,quiz_record_id,source_object_id,notes,created_at) VALUES "
            "(1,'student-a','quiz-unmatched',NULL,:notes,'2026-08-01')"
        ), {"notes": user_json})

        _install_f8_canonical_wrong_question_identity(connection)
        _install_f8_canonical_wrong_question_identity(connection)

        row = connection.execute(text(
            "SELECT source_object_id,notes FROM wrong_questions WHERE id=1"
        )).mappings().one()
        assert row["source_object_id"] is None
        assert row["notes"] == user_json

    engine.dispose()


def _canonical_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    user = DBUser(
        public_id="owner-f8",
        username="student-f8",
        hashed_password="x",
        role="student",
    )
    profile = DBStudentProfile(student_id=user.username, concept_mastery={"梯度": 0.4})
    point = DBKnowledgePoint(
        id="kp-f8",
        domain_pack="machine-learning",
        code="gradient",
        version="1",
        title="梯度",
    )
    question = DBAssessmentQuestion(
        id="question-f8",
        owner_public_id=user.public_id,
        question_type="single_choice",
        origin="legacy",
        status="approved",
    )
    session.add_all([user, profile, point, question])
    session.flush()
    version = DBAssessmentQuestionVersion(
        id="question-version-f8",
        question_id=question.id,
        version_number=1,
        prompt="梯度下降为什么沿负梯度更新？",
        options=["增大损失", "局部最快下降"],
        answer_key={"choice": "B"},
        scoring_rule={"type": "exact"},
        explanation="负梯度给出局部最速下降方向。",
        primary_knowledge_point_id=point.id,
        content_hash="f" * 64,
        created_by_public_id=user.public_id,
        source_ref_ids=["legacy-quiz:quiz-f8"],
    )
    quiz = DBQuizRecord(
        id="quiz-f8",
        student_id=user.username,
        question=version.prompt,
        student_answer="A",
        correct_answer="B",
        options=version.options,
        target_concept=point.title,
    )
    session.add_all([version, quiz])
    session.flush()
    question.current_version_id = version.id
    legacy_wrong = DBWrongQuestion(
        student_id=user.username,
        quiz_record_id=quiz.id,
        concept_name=point.title,
        wrong_reason_category="pending_confirmation",
        notes="保留这条反思",
    )
    session.add(legacy_wrong)
    session.commit()
    return session, user, version, legacy_wrong.id


def _quiz_event(user: DBUser, version: DBAssessmentQuestionVersion, index: int):
    return DBLearningEvent(
        id=f"quiz-event-{index}",
        owner_public_id=user.public_id,
        event_type="quiz_answered",
        schema_version="m5.learning-event.v2",
        idempotency_key=f"quiz-event-key-{index}",
        source="backend",
        trace_id=f"quiz-trace-{index}",
        object_type="assessment_question_version",
        object_id=version.id,
        action="assessment_completed",
        context_ref={"knowledgePointId": "kp-f8", "attemptId": f"attempt-{index}"},
        evidence_strength=0.8,
        evidence_status="accepted",
        evidence_reason="server graded canonical attempt",
        mastery_eligible=True,
        completion_effect="none",
        payload_version="1",
        payload={
            "graded": True,
            "correct": False,
            "score": 0.0,
            "attempt_id": f"attempt-{index}",
            "source_object_id": "quiz-f8",
        },
    )


def test_repeated_legacy_quiz_errors_reuse_one_canonical_wrong_question():
    session, user, version, legacy_wrong_id = _canonical_session()
    returned_ids = []
    for index in (1, 2):
        event = _quiz_event(user, version, index)
        session.add(event)
        session.flush()
        consumption = aggregate_learning_event(session, event=event)
        returned_ids.append(consumption.result["steps"]["wrong_review"]["wrong_question_ids"])

    rows = session.query(DBWrongQuestion).all()
    assert len(rows) == 1
    assert rows[0].id == legacy_wrong_id
    assert rows[0].source_object_id == version.id
    assert rows[0].notes == "保留这条反思"
    assert rows[0].wrong_reason_category == "pending_confirmation"
    assert returned_ids == [[legacy_wrong_id], [legacy_wrong_id]]


def test_repeated_formal_exam_errors_reuse_one_canonical_wrong_question():
    session, user, version, _ = _canonical_session()
    session.query(DBWrongQuestion).delete()
    session.commit()
    returned_ids = []
    for index in (1, 2):
        event = DBLearningEvent(
            id=f"formal-event-{index}",
            owner_public_id=user.public_id,
            event_type="formal_exam_submitted",
            schema_version="m5.learning-event.v2",
            idempotency_key=f"formal-event-key-{index}",
            source="backend",
            trace_id=f"formal-trace-{index}",
            object_type="assessment_exam_sitting",
            object_id=f"sitting-{index}",
            action="assessment_completed",
            context_ref={"knowledgePointId": "kp-f8"},
            evidence_strength=0.95,
            evidence_status="accepted",
            evidence_reason="server graded formal exam",
            mastery_eligible=True,
            completion_effect="none",
            payload_version="1",
            payload={
                "exam_id": f"exam-{index}",
                "sitting_id": f"sitting-{index}",
                "knowledge_point_scores": [{"knowledge_point_id": "kp-f8", "score": 0.0}],
                "item_results": [{
                    "question_version_id": version.id,
                    "knowledge_point_id": "kp-f8",
                    "position": 1,
                    "score": 0.0,
                    "error_reason": "candidate-only",
                }],
            },
        )
        session.add(event)
        session.flush()
        consumption = aggregate_learning_event(session, event=event)
        returned_ids.append(consumption.result["steps"]["wrong_review"]["wrong_question_ids"])

    rows = session.query(DBWrongQuestion).all()
    assert len(rows) == 1
    assert rows[0].source_object_id == version.id
    assert rows[0].wrong_reason_category == "pending_confirmation"
    assert rows[0].notes == ""
    assert returned_ids == [[rows[0].id], [rows[0].id]]


def test_wrong_question_read_model_projects_attempts_sources_and_deep_links_without_writes():
    session, user, version, wrong_id = _canonical_session()
    course = DBCourse(
        id="course-f8",
        version="1",
        title="机器学习",
        status="published",
        visibility="public",
        owner_public_id=user.public_id,
        manifest_version="1",
    )
    source_document = DBSourceDocument(
        id="source-f8",
        course_id=course.id,
        legacy_document_id="legacy-source-f8",
        title="梯度下降课程讲义",
        filename="gradient.md",
        file_format="md",
        content_hash="1" * 64,
        source_sha256="2" * 64,
        processed_sha256="3" * 64,
        processing_status="ready",
    )
    chapter = DBChapter(
        id="chapter-f8",
        course_id=course.id,
        source_document_id=source_document.id,
        stable_key="gradient",
        title="梯度下降",
    )
    source_ref = DBSourceRef(
        id="source-ref-f8",
        source_document_id=source_document.id,
        chapter_id=chapter.id,
        parser_version="1",
        page_number=8,
        location_label="第 2 章 · 梯度下降",
        content_hash="4" * 64,
        quote="负梯度给出局部最速下降方向。",
    )
    artifact = DBArtifact(
        id="artifact-f8",
        owner_public_id=user.public_id,
        course_id=course.id,
        artifact_type="handout",
        title="梯度下降个性化讲义",
        status="published",
    )
    artifact_version = DBArtifactVersion(
        id="artifact-version-f8",
        artifact_id=artifact.id,
        version_number=1,
        content="# 梯度下降",
        content_hash="5" * 64,
        metadata_json={"resource_type": "handout", "knowledge_point_id": "kp-f8"},
        created_by_public_id=user.public_id,
    )
    session.add_all([course, source_document, chapter, source_ref, artifact, artifact_version])
    session.flush()
    artifact.current_version_id = artifact_version.id
    question = session.get(DBAssessmentQuestion, version.question_id)
    question.course_id = course.id
    version.source_ref_ids = [source_ref.id]
    session.get(DBWrongQuestion, wrong_id).source_object_id = version.id

    practice_attempt = DBAssessmentAttempt(
        id="attempt-read-practice",
        owner_public_id=user.public_id,
        course_id=course.id,
        question_version_id=version.id,
        idempotency_key="read-practice",
        mode="practice",
        answer={"choice": "A"},
        score=0.0,
        correct=False,
        grading_status="graded",
        feedback_policy="immediate",
        submitted_at=datetime(2026, 8, 14, 8, 0, 0),
    )
    grading = DBAssessmentGradingResult(
        id="grade-read-practice",
        attempt_id=practice_attempt.id,
        owner_public_id=user.public_id,
        grader_type="deterministic",
        status="completed",
        rubric_version="test-v1",
        score=0.0,
        correct=False,
        feedback="需要区分梯度与更新方向。",
        content_hash="6" * 64,
    )
    diagnosis = DBMisconceptionReview(
        id="diagnosis-read-practice",
        owner_public_id=user.public_id,
        attempt_id=practice_attempt.id,
        candidate_category="concept_confusion",
        candidate_rationale="把梯度方向误认为下降方向。",
        status="accepted",
        confirmed_category="concept_confusion",
    )
    retest = DBAssessmentRetestTask(
        id="retest-read-practice",
        owner_public_id=user.public_id,
        misconception_review_id=diagnosis.id,
        source_attempt_id=practice_attempt.id,
        question_version_id=version.id,
        course_id=course.id,
        due_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1),
        status="scheduled",
    )
    plan = DBReviewPlan(
        student_id=user.username,
        concept="梯度",
        next_review_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1),
        review_count=2,
        mastery=0.4,
    )
    session.add_all([practice_attempt, grading, diagnosis, retest, plan])

    exam = DBAssessmentExam(
        id="exam-read",
        course_id=course.id,
        owner_public_id=user.public_id,
        generation_key="exam-read-key",
        title="梯度下降智能组卷",
        status="closed",
    )
    exam_version = DBAssessmentExamVersion(
        id="exam-version-read",
        exam_id=exam.id,
        version_number=1,
        feedback_policy="after_close",
        total_points=10,
        manifest_hash="7" * 64,
    )
    exam_item = DBAssessmentExamItem(
        id="exam-item-read",
        exam_version_id=exam_version.id,
        question_version_id=version.id,
        position=1,
        points=10,
    )
    sitting = DBAssessmentExamSitting(
        id="sitting-read",
        exam_id=exam.id,
        exam_version_id=exam_version.id,
        owner_public_id=user.public_id,
        status="released",
    )
    formal_attempt = DBAssessmentAttempt(
        id="attempt-read-formal",
        owner_public_id=user.public_id,
        course_id=course.id,
        question_version_id=version.id,
        idempotency_key="read-formal",
        mode="formal",
        answer={"choice": "A"},
        score=0.0,
        correct=False,
        grading_status="graded",
        feedback_policy="after_close",
        submitted_at=datetime(2026, 8, 15, 8, 0, 0),
    )
    response = DBAssessmentExamResponse(
        id="response-read",
        sitting_id=sitting.id,
        exam_item_id=exam_item.id,
        attempt_id=formal_attempt.id,
    )
    report = DBAssessmentExamReport(
        id="report-read",
        sitting_id=sitting.id,
        report_version=1,
        report_data={"score": 0},
        input_hash="8" * 64,
        content_hash="9" * 64,
    )
    session.add_all([exam, exam_version, exam_item, sitting, formal_attempt, response, report])
    session.flush()
    exam.current_version_id = exam_version.id
    session.commit()

    event_count = session.query(DBLearningEvent).count()
    rows = build_wrong_question_read_model(
        session,
        student_id=user.username,
        owner_public_id=user.public_id,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == wrong_id
    assert row["notes"] == "保留这条反思"
    assert row["question"]["correct_answer"] == {"choice": "B"}
    assert "负梯度给出局部最速下降方向。" in row["question"]["explanation"]
    assert "正确答案是 B" in row["question"]["explanation"]
    assert "选项 A" in row["question"]["explanation"]
    assert row["attempt_count"] == 2
    assert {item["mode"] for item in row["attempts"]} == {"practice", "formal"}
    assert row["formal_exam_links"][0]["report_id"] == report.id
    assert row["formal_exam_links"][0]["route"].startswith("/workspace/assessment/exams/exam-read?")
    assert row["current_diagnosis"]["status"] == "accepted"
    assert row["retest_task"]["status"] == "due"
    assert row["actions"]["primary"]["kind"] == "retest"
    assert row["source_refs"][0]["available"] is True
    assert "legacy-source-f8" in row["source_refs"][0]["route"]
    assert row["related_resources"][0]["route"] == "/workspace/resources/handouts/artifact-f8"
    assert row["review_plan"]["route"].endswith(f"review-plan:{plan.id}")
    assert session.query(DBLearningEvent).count() == event_count
    assert not session.new and not session.dirty and not session.deleted


def test_formal_only_wrong_question_hides_answer_until_feedback_is_released():
    session, user, version, _ = _canonical_session()
    session.query(DBWrongQuestion).delete()
    question = session.get(DBAssessmentQuestion, version.question_id)
    course = DBCourse(
        id="course-hidden",
        version="1",
        title="反馈边界课程",
        status="published",
        visibility="public",
        owner_public_id=user.public_id,
        manifest_version="1",
    )
    session.add(course)
    session.flush()
    question.course_id = course.id
    attempt = DBAssessmentAttempt(
        id="attempt-hidden",
        owner_public_id=user.public_id,
        course_id=course.id,
        question_version_id=version.id,
        idempotency_key="hidden-formal",
        mode="formal",
        answer={"choice": "A"},
        score=0.0,
        correct=False,
        grading_status="graded",
        feedback_policy="after_close",
    )
    wrong = DBWrongQuestion(
        student_id=user.username,
        source_object_id=version.id,
        concept_name="梯度",
        wrong_reason_category="pending_confirmation",
    )
    session.add_all([attempt, wrong])
    session.commit()

    row = build_wrong_question_read_model(
        session,
        student_id=user.username,
        owner_public_id=user.public_id,
    )[0]

    assert row["question"]["answer_available"] is False
    assert row["question"]["correct_answer"] is None
    assert row["question"]["explanation"] == ""
    assert row["attempts"][0]["score"] is None
    assert row["attempts"][0]["correct"] is None
