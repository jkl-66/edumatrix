from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user, get_password_hash
from app.database import (
    Base, DBAssessmentAttempt, DBAssessmentQuestion, DBAssessmentQuestionVersion,
    DBCourse, DBCourseMembership, DBLearningEvent, DBLearningPath, DBPathNode,
    DBPlanDraft, DBPlanVersion, DBTeachingAnalyticsReport, DBTeachingClass,
    DBTeachingClassMember, DBUser,
)
from app.main import app
from app.teaching_analytics import build_snapshot, create_report
import app.teaching_analytics_api as analytics_api


def _fixture():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    teacher = DBUser(public_id="ta-teacher", username="ta-teacher", hashed_password=get_password_hash("pw"), role="teacher", display_name="Teacher")
    outsider = DBUser(public_id="ta-outsider", username="ta-outsider", hashed_password=get_password_hash("pw"), role="teacher", display_name="Outsider")
    learners = [DBUser(public_id=f"ta-learner-{i}", username=f"ta-learner-{i}", hashed_password=get_password_hash("pw"), role="student", display_name=f"Learner {i}") for i in range(3)]
    course = DBCourse(id="ta-course", version="1", title="Analytics", visibility="private", manifest_version="1", owner_public_id=teacher.public_id)
    db.add_all([teacher, outsider, course, *learners]); db.flush()
    db.add(DBCourseMembership(course_id=course.id, user_public_id=teacher.public_id, role="teacher", status="active"))
    classroom = DBTeachingClass(id="ta-class", course_id=course.id, title="RAG Class", term="2026", owner_public_id=teacher.public_id)
    db.add(classroom); db.flush()
    for learner in learners:
        db.add_all([DBCourseMembership(course_id=course.id, user_public_id=learner.public_id, role="student", status="active"), DBTeachingClassMember(class_id=classroom.id, user_public_id=learner.public_id, role="student")])
    draft = DBPlanDraft(id="ta-plan", owner_public_id=learners[0].public_id, course_id=course.id, title="Plan", idempotency_key="ta-plan-key", status="confirmed")
    db.add(draft); db.flush()
    version = DBPlanVersion(id="ta-plan-version", plan_draft_id=draft.id, version_number=1, content={"goal":"Goal","nodes":[]}, content_hash="a" * 64, created_by_public_id=teacher.public_id)
    db.add(version); db.flush()
    path = DBLearningPath(id="ta-path", owner_public_id=learners[0].public_id, course_id=course.id, source_plan_version_id=version.id)
    db.add(path); db.flush()
    db.add_all([
        DBPathNode(id="ta-node-1", learning_path_id=path.id, node_key="n1", sequence=1, node_type="chapter", title="Done", status="completed", estimate_min_minutes=20, estimate_max_minutes=40),
        DBPathNode(id="ta-node-2", learning_path_id=path.id, node_key="n2", sequence=2, node_type="chapter", title="Pending", status="pending", estimate_min_minutes=90, estimate_max_minutes=200),
    ])
    question = DBAssessmentQuestion(id="ta-question", course_id=course.id, owner_public_id=teacher.public_id, question_type="single_choice", status="approved")
    db.add(question); db.flush()
    qv = DBAssessmentQuestionVersion(id="ta-qv", question_id=question.id, version_number=1, prompt="Q", options=["A", "B"], answer_key={"selected":"A"}, scoring_rule={"type":"exact"}, content_hash="b" * 64, created_by_public_id=teacher.public_id)
    db.add(qv); db.flush()
    now = datetime.utcnow()
    db.add_all([
        DBLearningEvent(id="ta-event-1", owner_public_id=learners[0].public_id, course_id=course.id, event_type="resource_viewed", trace_id="trace-1", occurred_at=now),
        DBLearningEvent(id="ta-event-2", owner_public_id=learners[1].public_id, course_id=course.id, event_type="assessment_submitted", trace_id="trace-2", occurred_at=now),
        DBAssessmentAttempt(id="ta-attempt", owner_public_id=learners[0].public_id, course_id=course.id, question_version_id=qv.id, idempotency_key="ta-attempt-key", answer={"selected":"A"}, score=0.8, correct=True, grading_status="graded", submitted_at=now),
    ])
    db.commit()
    return db, engine, teacher, outsider, classroom, now


def test_snapshot_exposes_formula_sources_samples_and_path_burden():
    db, _, teacher, _, classroom, now = _fixture()
    snapshot = build_snapshot(db, actor=teacher, class_id=classroom.id, period_start=now - timedelta(days=1), period_end=now + timedelta(days=1))
    metrics = {item["key"]: item for item in snapshot["metrics"]}
    assert metrics["participation_rate"]["value"] == pytest.approx(2 / 3, abs=0.0001)
    assert metrics["assessment_average"]["value"] == 0.8
    assert metrics["path_completion_rate"]["value"] == 0.5
    assert metrics["path_burden_minutes"]["value"] == pytest.approx(200 / 3, abs=0.0001)
    assert all(item["formula"] and item["sources"] and item["threshold_basis"] for item in metrics.values())
    assert snapshot["truthfulness"]["real_enterprise_data"] is False
    learner = next(row for row in snapshot["learners"] if row["learner_public_id"] == "ta-learner-0")
    assert learner["pending_burden_minutes"] == 200 and learner["burden_state"] == "attention"


def test_reports_are_idempotent_frozen_and_database_immutable():
    db, engine, teacher, _, classroom, now = _fixture()
    start, end = now - timedelta(days=1), now + timedelta(days=1)
    first, created = create_report(db, actor=teacher, class_id=classroom.id, period_start=start, period_end=end)
    second, repeated = create_report(db, actor=teacher, class_id=classroom.id, period_start=start, period_end=end)
    db.commit()
    assert created is True and repeated is False and first.id == second.id and len(first.content_hash) == 64
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TRIGGER IF NOT EXISTS trg_teaching_analytics_no_update BEFORE UPDATE ON teaching_analytics_reports BEGIN SELECT RAISE(ABORT, 'teaching analytics report is immutable'); END")
    with pytest.raises(DatabaseError):
        db.query(DBTeachingAnalyticsReport).filter_by(id=first.id).update({"status": "withdrawn"})


def test_api_enforces_course_manager_and_exports_json_csv(monkeypatch):
    db, _, teacher, outsider, classroom, now = _fixture()
    identity = {"user": teacher}
    async def fake_run_db_op(operation): return operation(db)
    monkeypatch.setattr(analytics_api, "run_db_op", fake_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: identity["user"]
    client = TestClient(app)
    try:
        response = client.post("/api/v1/teaching-analytics/reports", json={"class_id": classroom.id, "period_start": (now - timedelta(days=1)).isoformat(), "period_end": (now + timedelta(days=1)).isoformat()})
        assert response.status_code == 201, response.text
        report_id = response.json()["id"]
        assert client.get(f"/api/v1/teaching-analytics/reports/{report_id}/export/json").status_code == 200
        csv_response = client.get(f"/api/v1/teaching-analytics/reports/{report_id}/export/csv")
        assert csv_response.status_code == 200 and "participation_rate" in csv_response.text
        identity["user"] = outsider
        assert client.get(f"/api/v1/teaching-analytics/reports/{report_id}").status_code == 403
        assert client.get(f"/api/v1/teaching-analytics/reports/{report_id}/export/csv").status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_empty_period_is_truthful_unavailable_not_zero():
    db, _, teacher, _, classroom, now = _fixture()
    snapshot = build_snapshot(db, actor=teacher, class_id=classroom.id, period_start=now + timedelta(days=3), period_end=now + timedelta(days=4))
    assessment = next(item for item in snapshot["metrics"] if item["key"] == "assessment_average")
    assert assessment["value"] is None and assessment["state"] == "unavailable" and assessment["sample_state"] == "small_sample"
