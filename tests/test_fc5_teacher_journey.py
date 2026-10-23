from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.competition_journey_api as journey_api
from app.auth import get_current_user, get_password_hash
from app.database import (
    Base, DBArtifact, DBArtifactVersion, DBCompetitionJourneyRun, DBContentReviewCase,
    DBCourse, DBCourseMembership, DBLearningEvent, DBLearningPath, DBPlanDraft,
    DBPlanVersion, DBTeachingAnalyticsReport, DBTeachingClass, DBTeachingGroup,
    DBTeachingTask, DBUser,
)
from app.main import app
from app.migrations import apply_registered_migrations


def fixture():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def fk(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    apply_registered_migrations(engine)
    db = sessionmaker(bind=engine)()
    teacher = DBUser(public_id="teacher-owner", username="teacher-owner", display_name="教学负责人", hashed_password=get_password_hash("pw"), role="teacher")
    other = DBUser(public_id="teacher-other", username="teacher-other", display_name="其他教师", hashed_password=get_password_hash("pw"), role="teacher")
    learner = DBUser(public_id="teacher-learner", username="teacher-learner", display_name="合成学员", hashed_password=get_password_hash("pw"), role="student")
    course = DBCourse(id="teacher-course", version="frozen-v1", title="教师旅程课程（冻结合成）", status="published", owner_public_id=teacher.public_id, manifest_version="m1", manifest_data={"data_class": "synthetic_fixture"})
    db.add_all([teacher, other, learner]); db.flush()
    db.add(course); db.flush()
    db.add_all([
        DBCourseMembership(course_id=course.id, user_public_id=teacher.public_id, role="teacher", status="active"),
        DBCourseMembership(course_id=course.id, user_public_id=learner.public_id, role="student", status="active"),
    ])
    db.commit()
    return db, teacher, other, learner, course


def client(monkeypatch, db, user):
    async def fake(operation):
        return operation(db)
    monkeypatch.setattr(journey_api, "run_db_op", fake)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def seed_six_steps(db, teacher, learner, course, *, confirmation_at):
    classroom = DBTeachingClass(course_id=course.id, title="人工智能 1 班", term="冻结演示", owner_public_id=teacher.public_id)
    db.add(classroom); db.flush()
    group = DBTeachingGroup(class_id=classroom.id, name="技能提升组", description="冻结合成分组")
    db.add(group); db.flush()
    task = DBTeachingTask(class_id=classroom.id, group_id=group.id, title="完成证据精读", idempotency_key="teacher-journey-task", status="published", created_by_public_id=teacher.public_id, published_at=confirmation_at-timedelta(hours=3))
    before = DBTeachingAnalyticsReport(class_id=classroom.id, course_id=course.id, period_start=confirmation_at-timedelta(days=7), period_end=confirmation_at-timedelta(days=1), metric_version="demo-v1", report_data={"truthfulness":{"data_kind":"competition_demo_metrics"}}, content_hash="1"*64, created_by_public_id=teacher.public_id, created_at=confirmation_at-timedelta(hours=2))
    db.add_all([task, before]); db.flush()

    plan = DBPlanDraft(owner_public_id=learner.public_id, course_id=course.id, title="教师干预：矩阵分解", status="confirmed", idempotency_key="teacher-journey-intervention", confirmed_at=confirmation_at-timedelta(minutes=30))
    db.add(plan); db.flush()
    version = DBPlanVersion(plan_draft_id=plan.id, version_number=1, content={"data_class":"synthetic_fixture"}, content_hash="2"*64, created_by_public_id=teacher.public_id)
    db.add(version); db.flush(); plan.current_version_id=version.id; plan.confirmed_version_id=version.id
    path = DBLearningPath(owner_public_id=learner.public_id, course_id=course.id, source_plan_version_id=version.id, status="completed", completed_at=confirmation_at)
    db.add(path); db.flush()
    learner_event = DBLearningEvent(owner_public_id=learner.public_id, course_id=course.id, event_type="reading_threshold", source="frontend", trace_id="teacher-journey-study", object_type="chapter", object_id="chapter-demo", payload={"path_id":path.id,"active_seconds":1200}, occurred_at=confirmation_at-timedelta(minutes=5))
    db.add(learner_event); db.flush()
    confirmation = DBLearningEvent(owner_public_id=learner.public_id, course_id=course.id, event_type="teacher_confirmed", source="teacher", trace_id="teacher-journey-confirm", object_type="chapter", object_id="chapter-demo", payload={"scope":"intervention_completion","path_id":path.id,"learner_event_id":learner_event.id,"teacher_public_id":teacher.public_id}, occurred_at=confirmation_at)
    db.add(confirmation)

    artifact = DBArtifact(owner_public_id=teacher.public_id, course_id=course.id, artifact_type="lesson", title="审核课程内容", status="approved")
    db.add(artifact); db.flush()
    artifact_version = DBArtifactVersion(artifact_id=artifact.id, version_number=1, content="# 冻结合成课程内容", content_hash="3"*64, created_by_public_id=teacher.public_id)
    db.add(artifact_version); db.flush(); artifact.current_version_id=artifact_version.id
    review = DBContentReviewCase(artifact_id=artifact.id, submitted_version_id=artifact_version.id, course_id=course.id, submitted_by_public_id=teacher.public_id, status="approved", evidence_snapshot={"data_class":"synthetic_fixture"}, submission_note="演示审核", resolved_at=confirmation_at-timedelta(hours=1))
    db.add(review); db.commit()
    return classroom, before, confirmation


def test_teacher_role_scope_visits_and_type_isolation(monkeypatch):
    db, teacher, other, _, course = fixture()
    c = client(monkeypatch, db, teacher)
    try:
        response = c.post("/api/v1/competition-journeys/teacher/runs", json={"course_id":course.id,"run_key":"teacher-run"})
        assert response.status_code == 201, response.text
        run = response.json()
        assert run["journey_type"] == "teacher"
        assert run["progress"] == {"completed":1,"total":7,"percent":14}
        for step in run["steps"]:
            visit = c.post(f"/api/v1/competition-journeys/teacher/runs/{run['id']}/visits", json={"step_key":step["key"],"route":step["route"]})
            assert visit.status_code == 201, visit.text
        refreshed = c.get(f"/api/v1/competition-journeys/teacher/runs/{run['id']}").json()
        assert refreshed["progress"]["completed"] == 1 and len(refreshed["visits"]) == 7
        student = c.post("/api/v1/competition-journeys/student/runs", json={"course_id":course.id,"run_key":"student-run"}).json()
        assert c.get(f"/api/v1/competition-journeys/teacher/runs/{student['id']}").status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    c = client(monkeypatch, db, other)
    try:
        assert c.post("/api/v1/competition-journeys/teacher/runs", json={"course_id":course.id,"run_key":"forbidden"}).status_code == 403
        assert c.get(f"/api/v1/competition-journeys/teacher/runs/{run['id']}").status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_teacher_effect_review_must_follow_confirmed_intervention(monkeypatch):
    db, teacher, _, learner, course = fixture()
    c = client(monkeypatch, db, teacher)
    try:
        run = c.post("/api/v1/competition-journeys/teacher/runs", json={"course_id":course.id,"run_key":"effect-run"}).json()
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    confirmation_at = datetime.utcnow().replace(microsecond=0)
    classroom, _, confirmation = seed_six_steps(db, teacher, learner, course, confirmation_at=confirmation_at)
    c = client(monkeypatch, db, teacher)
    try:
        before = c.get(f"/api/v1/competition-journeys/teacher/runs/{run['id']}").json()
        assert before["progress"]["completed"] == 6
        assert next(x for x in before["steps"] if x["key"]=="effect_review")["complete"] is False
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    after = DBTeachingAnalyticsReport(class_id=classroom.id, course_id=course.id, period_start=confirmation_at, period_end=confirmation_at+timedelta(days=1), metric_version="demo-v1", report_data={"truthfulness":{"data_kind":"competition_demo_metrics"}}, content_hash="4"*64, created_by_public_id=teacher.public_id, created_at=confirmation.occurred_at+timedelta(seconds=1))
    db.add(after); db.commit()
    c = client(monkeypatch, db, teacher)
    try:
        final = c.get(f"/api/v1/competition-journeys/teacher/runs/{run['id']}")
        assert final.status_code == 200, final.text
        body = final.json()
        assert body["status"] == "completed" and body["progress"]["completed"] == 7
        assert next(x for x in body["steps"] if x["key"]=="effect_review")["evidence_id"] == after.id
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_migration_057_keeps_all_journey_types_available():
    db, teacher, _, _, course = fixture()
    assert db.execute(text("select count(*) from schema_migrations where version='20260805_057'")).scalar_one() == 1
    db.add_all([
        DBCompetitionJourneyRun(owner_public_id=teacher.public_id, course_id=course.id, journey_type="student", run_key="preserved-student", baseline_snapshot={}, baseline_hash="5"*64),
        DBCompetitionJourneyRun(owner_public_id=teacher.public_id, course_id=course.id, journey_type="media", run_key="preserved-media", baseline_snapshot={}, baseline_hash="6"*64),
        DBCompetitionJourneyRun(owner_public_id=teacher.public_id, course_id=course.id, journey_type="teacher", run_key="new-teacher", baseline_snapshot={}, baseline_hash="7"*64),
    ])
    db.commit()
    assert {row.journey_type for row in db.query(DBCompetitionJourneyRun).all()} == {"student","media","teacher"}
