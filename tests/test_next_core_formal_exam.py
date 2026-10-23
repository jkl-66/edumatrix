from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import (
    Base, DBAssessmentExamReport, DBAssessmentExamVersion,
    DBAssessmentGradingResult, DBCourse, DBCourseMembership, DBUser,
)
from app.m5_assessment_core import QuestionVersionInput, create_question_version
from app.m5_exam_core import (
    ExamCreateInput, ExamItemInput, FormalExamError, FormalResponseInput,
    HumanReviewInput, assign_sitting, complete_human_review, create_exam,
    generate_report, report_csv, request_review, start_sitting,
    submit_formal_response, submit_sitting, transition_exam,
)
from app.migrations import apply_registered_migrations
from app.auth import get_current_user
from app.main import app
import app.m5_api as m5_api


def _fixture():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    apply_registered_migrations(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([
        DBUser(public_id="teacher", username="teacher", hashed_password="test", role="teacher", is_active=True),
        DBUser(public_id="learner", username="learner", hashed_password="test", role="student", is_active=True),
        DBUser(public_id="other", username="other", hashed_password="test", role="student", is_active=True),
        DBCourse(id="course", version="1", title="Course", visibility="private", manifest_version="1", owner_public_id="teacher"),
        DBCourseMembership(course_id="course", user_public_id="teacher", role="teacher", status="active"),
        DBCourseMembership(course_id="course", user_public_id="learner", role="student", status="active"),
    ])
    session.flush()
    question, version = create_question_version(
        session, owner_public_id="teacher", course_id="course",
        question_type="single_choice", origin="manual",
        version=QuestionVersionInput(
            prompt="Choose B", options=("A", "B"), answer_key={"choice": "B"},
            scoring_rule={"type": "exact", "version": "objective-v1"},
        ),
    )
    question.status = "approved"
    session.flush()
    exam, exam_version, items = create_exam(
        session, owner_public_id="teacher",
        payload=ExamCreateInput(
            course_id="course", title="Formal exam", duration_minutes=30,
            items=(ExamItemInput(question_version_id=version.id, points=100),),
        ),
    )
    return session, engine, exam, exam_version, items[0]


def _completed_sitting(session, exam, item):
    transition_exam(session, exam=exam, target="published", expected_lock_version=1, actor_public_id="teacher")
    sitting, _ = assign_sitting(session, exam=exam, learner_public_id="learner", actor_public_id="teacher")
    transition_exam(session, exam=exam, target="open", expected_lock_version=2, actor_public_id="teacher")
    start_sitting(session, sitting=sitting, owner_public_id="learner", expected_lock_version=1)
    _, attempt, _ = submit_formal_response(
        session, sitting=sitting, owner_public_id="learner",
        payload=FormalResponseInput(exam_item_id=item.id, idempotency_key="formal-answer-001", answer={"choice": "B"}),
    )
    submit_sitting(session, sitting=sitting, owner_public_id="learner", expected_lock_version=2)
    return sitting, attempt


def test_formal_exam_release_sitting_close_and_report_are_reproducible():
    session, _, exam, version, item = _fixture()
    sitting, attempt = _completed_sitting(session, exam, item)
    with pytest.raises(FormalExamError, match="closed"):
        generate_report(session, sitting=sitting, actor_public_id="learner")
    transition_exam(session, exam=exam, target="closed", expected_lock_version=3, actor_public_id="teacher")
    report, created = generate_report(session, sitting=sitting, actor_public_id="learner")
    again, created_again = generate_report(session, sitting=sitting, actor_public_id="learner")
    assert created is True and created_again is False and again.id == report.id
    assert report.report_data["final_ratio"] == 1.0
    assert report.report_data["items"][0]["attempt_id"] == attempt.id
    assert report.report_data["manifest_hash"] == version.manifest_hash
    assert "服务端客观评分" in report_csv(report)


def test_human_review_preserves_initial_grade_and_creates_new_report_version():
    session, _, exam, _, item = _fixture()
    sitting, attempt = _completed_sitting(session, exam, item)
    transition_exam(session, exam=exam, target="closed", expected_lock_version=3, actor_public_id="teacher")
    first, _ = generate_report(session, sitting=sitting, actor_public_id="learner")
    initial_id = first.report_data["items"][0]["initial_grading_result_id"]
    review, _ = request_review(
        session, sitting=sitting, attempt_id=attempt.id,
        requested_by_public_id="learner", reason="Please recheck.",
    )
    human = complete_human_review(
        session, review=review, reviewer_public_id="teacher", expected_lock_version=1,
        payload=HumanReviewInput(score=0.8, confidence=0.9, note="Demonstration-role review."),
    )
    second, created = generate_report(session, sitting=sitting, actor_public_id="teacher")
    assert created is True and second.report_version == 2
    assert second.report_data["items"][0]["initial_grading_result_id"] == initial_id
    assert second.report_data["items"][0]["selected_grading_result_id"] == human.id
    assert second.report_data["items"][0]["selected_label"] == "人工复核（演示角色）"
    assert session.query(DBAssessmentGradingResult).filter_by(attempt_id=attempt.id).count() == 2


def test_sitting_owner_deadline_and_item_membership_fail_closed():
    session, _, exam, _, item = _fixture()
    transition_exam(session, exam=exam, target="published", expected_lock_version=1, actor_public_id="teacher")
    sitting, _ = assign_sitting(session, exam=exam, learner_public_id="learner", actor_public_id="teacher")
    transition_exam(session, exam=exam, target="open", expected_lock_version=2, actor_public_id="teacher")
    with pytest.raises(FormalExamError, match="another owner"):
        start_sitting(session, sitting=sitting, owner_public_id="other", expected_lock_version=1)
    start_sitting(session, sitting=sitting, owner_public_id="learner", expected_lock_version=1)
    sitting.due_at = datetime.utcnow() - timedelta(seconds=1)
    with pytest.raises(FormalExamError, match="deadline"):
        submit_formal_response(
            session, sitting=sitting, owner_public_id="learner",
            payload=FormalResponseInput(exam_item_id=item.id, idempotency_key="formal-expired-01", answer={"choice": "B"}),
        )
    sitting.due_at = datetime.utcnow() + timedelta(minutes=1)
    with pytest.raises(FormalExamError, match="not part"):
        submit_formal_response(
            session, sitting=sitting, owner_public_id="learner",
            payload=FormalResponseInput(exam_item_id="not-an-item", idempotency_key="formal-invalid-01", answer={"choice": "B"}),
        )


def test_exam_versions_responses_and_reports_are_database_immutable():
    session, _, exam, version, item = _fixture()
    sitting, _ = _completed_sitting(session, exam, item)
    transition_exam(session, exam=exam, target="closed", expected_lock_version=3, actor_public_id="teacher")
    report, _ = generate_report(session, sitting=sitting, actor_public_id="teacher")
    session.commit()
    version.instructions = "mutated"
    with pytest.raises(Exception, match="immutable"):
        session.commit()
    session.rollback()
    stored = session.query(DBAssessmentExamReport).filter_by(id=report.id).one()
    stored.content_hash = "0" * 64
    with pytest.raises(Exception, match="immutable"):
        session.commit()
    session.rollback()
    assert session.query(DBAssessmentExamVersion).count() == 1


def test_formal_exam_http_role_flow_and_cross_owner_report_denial(monkeypatch):
    session, _, _, _, item = _fixture()

    async def fake_run_db_op(operation):
        return operation(session)

    identity = {"user": session.query(DBUser).filter_by(public_id="teacher").one()}
    monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: identity["user"]
    try:
        created = client.post("/api/v1/m5/assessment/exams", json={
            "course_id": "course", "title": "HTTP formal exam", "duration_minutes": 20,
            "feedback_policy": "after_close",
            "items": [{"question_version_id": item.question_version_id, "points": 100, "required": True}],
        })
        assert created.status_code == 201, created.text
        exam = created.json()
        published = client.post(f"/api/v1/m5/assessment/exams/{exam['id']}/transition", json={
            "expected_lock_version": exam["lock_version"], "target_status": "published",
        })
        assert published.status_code == 200
        assigned = client.post(f"/api/v1/m5/assessment/exams/{exam['id']}/assignments", json={"learner_public_id": "learner"})
        assert assigned.status_code == 201, assigned.text
        opened = client.post(f"/api/v1/m5/assessment/exams/{exam['id']}/transition", json={
            "expected_lock_version": published.json()["lock_version"], "target_status": "open",
        })
        assert opened.status_code == 200

        identity["user"] = session.query(DBUser).filter_by(public_id="learner").one()
        catalog = client.get("/api/v1/m5/assessment/exams").json()["items"]
        http_exam = next(row for row in catalog if row["id"] == exam["id"])
        sitting = http_exam["sitting"]
        started = client.post(f"/api/v1/m5/assessment/exam-sittings/{sitting['id']}/start", json={"expected_lock_version": sitting["lock_version"]})
        assert started.status_code == 200
        answered = client.post(f"/api/v1/m5/assessment/exam-sittings/{sitting['id']}/responses", json={
            "exam_item_id": http_exam["items"][0]["id"],
            "idempotency_key": "http-formal-answer-001", "answer": {"choice": "B"},
        })
        assert answered.status_code == 201, answered.text
        answer_payload = answered.json()
        assert answer_payload["attempt"]["feedback_policy"] == "after_close"
        assert "version" not in answer_payload
        assert "answer_key" not in answer_payload
        assert "scoring_rule" not in answer_payload
        submitted = client.post(f"/api/v1/m5/assessment/exam-sittings/{sitting['id']}/submit", json={
            "expected_lock_version": started.json()["lock_version"],
        })
        assert submitted.status_code == 200

        identity["user"] = session.query(DBUser).filter_by(public_id="teacher").one()
        closed = client.post(f"/api/v1/m5/assessment/exams/{exam['id']}/transition", json={
            "expected_lock_version": opened.json()["lock_version"], "target_status": "closed",
        })
        assert closed.status_code == 200
        identity["user"] = session.query(DBUser).filter_by(public_id="learner").one()
        report = client.post(f"/api/v1/m5/assessment/exam-sittings/{sitting['id']}/reports")
        assert report.status_code == 200, report.text
        assert report.json()["report"]["final_ratio"] == 1.0

        identity["user"] = session.query(DBUser).filter_by(public_id="other").one()
        denied = client.get(f"/api/v1/m5/assessment/exam-reports/{report.json()['id']}")
        assert denied.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
