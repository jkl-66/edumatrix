from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.local_lms_api as local_lms_api
from app.auth import get_current_user, get_password_hash
from app.database import (
    Base, DBAssessmentAbilityState, DBAssessmentAttempt, DBCertification,
    DBCourse, DBCourseMembership, DBJobFamily, DBJobLevel, DBLMSCatalogExport,
    DBLMSGradeSummary, DBLocalLMSConnection, DBOrganization,
    DBOrganizationMembership, DBSkillEvidence, DBTrainingAssignment,
    DBTrainingCohort, DBTrainingProgram, DBUser,
)
from app.main import app
from app.migrations import apply_registered_migrations


def _fixture():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def fk(connection, _record): connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    apply_registered_migrations(engine)
    session = sessionmaker(bind=engine)()
    admin = DBUser(public_id="lms-admin", username="lms-admin", display_name="LMS 管理员", hashed_password=get_password_hash("pw"), role="admin")
    learner = DBUser(public_id="lms-learner", username="lms-learner", display_name="合成学员", hashed_password=get_password_hash("pw"), role="student")
    outsider = DBUser(public_id="lms-outsider", username="lms-outsider", display_name="外部管理员", hashed_password=get_password_hash("pw"), role="admin")
    org = DBOrganization(id="lms-org", name="冻结合成组织")
    other_org = DBOrganization(id="lms-other-org", name="其他组织")
    session.add_all([admin, learner, outsider, org, other_org]); session.flush()
    session.add_all([
        DBOrganizationMembership(organization_id=org.id, user_public_id=admin.public_id, role="admin"),
        DBOrganizationMembership(organization_id=org.id, user_public_id=learner.public_id, role="learner"),
        DBOrganizationMembership(organization_id=other_org.id, user_public_id=outsider.public_id, role="admin"),
    ])
    family = DBJobFamily(id="lms-family", organization_id=org.id, code="RAG", title="RAG 工程师")
    level = DBJobLevel(id="lms-level", job_family_id=family.id, level_code="L2", version="1", title="RAG 工程师", status="active")
    program = DBTrainingProgram(id="lms-program", organization_id=org.id, target_job_level_id=level.id, title="RAG 训练营", version="1", status="active")
    course = DBCourse(id="lms-course", version="1.0", title="可信 RAG 工程", subject="人工智能", status="published", manifest_version="manifest-1")
    cohort = DBTrainingCohort(id="lms-cohort", organization_id=org.id, training_program_id=program.id,
                              standard_snapshot={"synthetic": True}, course_versions=["lms-course@1.0"], status="active")
    assignment = DBTrainingAssignment(id="lms-assignment", organization_id=org.id, cohort_id=cohort.id,
                                      learner_public_id=learner.public_id, assignment_source="transfer_plan", status="assigned")
    session.add(family); session.flush()
    session.add(level); session.flush()
    session.add(program); session.flush()
    session.add(course); session.flush()
    session.add(cohort); session.flush()
    session.add(assignment); session.flush()
    session.add_all([
        DBCourseMembership(course_id=course.id, user_public_id=admin.public_id, role="teacher"),
        DBCourseMembership(course_id=course.id, user_public_id=learner.public_id, role="student"),
    ])
    session.commit()
    return session, admin, learner, outsider, org, other_org, course, cohort, assignment


def _client(monkeypatch, session, user):
    async def fake_run_db_op(operation): return operation(session)
    monkeypatch.setattr(local_lms_api, "run_db_op", fake_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _connection(client, org):
    response = client.post("/api/v1/local-lms/connections", json={"organization_id": org.id})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _authority_counts(session, learner):
    return {
        "attempts": session.query(DBAssessmentAttempt).filter_by(owner_public_id=learner.public_id).count(),
        "abilities": session.query(DBAssessmentAbilityState).filter_by(owner_public_id=learner.public_id).count(),
        "skill_evidence": session.query(DBSkillEvidence).filter_by(learner_public_id=learner.public_id).count(),
        "certifications": session.query(DBCertification).filter_by(learner_public_id=learner.public_id).count(),
    }


def test_lms_catalog_assignment_and_candidate_grade_do_not_mutate_authorities(monkeypatch):
    session, admin, learner, _, org, _, course, cohort, assignment = _fixture()
    client = _client(monkeypatch, session, admin)
    try:
        connection_id = _connection(client, org)
        for source_type, source_id in (("course", course.id), ("cohort", cohort.id)):
            first = client.post("/api/v1/local-lms/catalog-exports", json={
                "organization_id": org.id, "connection_id": connection_id,
                "source_type": source_type, "source_object_id": source_id,
            })
            assert first.status_code == 201 and first.json()["created"] is True
            replay = client.post("/api/v1/local-lms/catalog-exports", json={
                "organization_id": org.id, "connection_id": connection_id,
                "source_type": source_type, "source_object_id": source_id,
            })
            assert replay.status_code == 201 and replay.json()["created"] is False
        exchange = client.post("/api/v1/local-lms/assignment-exchanges", json={
            "organization_id": org.id, "connection_id": connection_id,
            "training_assignment_id": assignment.id,
        })
        assert exchange.status_code == 201 and exchange.json()["changed"] is True
        replay_exchange = client.post("/api/v1/local-lms/assignment-exchanges", json={
            "organization_id": org.id, "connection_id": connection_id,
            "training_assignment_id": assignment.id,
        })
        assert replay_exchange.status_code == 201 and replay_exchange.json()["changed"] is False

        before = _authority_counts(session, learner)
        payload = {
            "organization_id": org.id, "connection_id": connection_id,
            "external_record_key": "synthetic-grade-001",
            "training_assignment_id": assignment.id, "course_id": course.id,
            "completion_status": "completed", "score": 0.95,
            "occurred_at": "2026-08-05T08:00:00",
        }
        grade = client.post("/api/v1/local-lms/grade-summaries", json=payload)
        assert grade.status_code == 201 and grade.json() == {
            "id": grade.json()["id"], "payload_hash": grade.json()["payload_hash"],
            "evidence_status": "candidate", "authoritative": False, "created": True,
        }
        replay = client.post("/api/v1/local-lms/grade-summaries", json=payload)
        assert replay.status_code == 201 and replay.json()["created"] is False
        assert _authority_counts(session, learner) == before
        summary = session.query(DBLMSGradeSummary).one()
        assert summary.score == 0.95 and summary.evidence_status == "candidate"
        assert session.query(DBLMSCatalogExport).count() == 2
        workspace = client.get("/api/v1/local-lms/workspace").json()
        assert workspace["truthfulness"]["external_grades_are_authoritative"] is False
        assert workspace["selected"]["grade_summaries"][0]["evidence_status"] == "candidate"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_lms_grade_same_key_different_payload_conflicts(monkeypatch):
    session, admin, _, _, org, _, course, _, assignment = _fixture(); client = _client(monkeypatch, session, admin)
    try:
        connection_id = _connection(client, org)
        payload = {"organization_id": org.id, "connection_id": connection_id,
                   "external_record_key": "same-key", "training_assignment_id": assignment.id,
                   "course_id": course.id, "completion_status": "completed", "score": 0.95,
                   "occurred_at": datetime(2026, 8, 5, 8).isoformat()}
        assert client.post("/api/v1/local-lms/grade-summaries", json=payload).status_code == 201
        payload["score"] = 0.61
        conflict = client.post("/api/v1/local-lms/grade-summaries", json=payload)
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "lms_grade_idempotency_conflict"
        assert session.query(DBLMSGradeSummary).count() == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_lms_permissions_cross_organization_and_migration_050(monkeypatch):
    session, admin, _, outsider, org, other_org, _, _, assignment = _fixture()
    client = _client(monkeypatch, session, outsider)
    try:
        assert client.get("/api/v1/local-lms/workspace").json()["selected"]["organization"]["id"] == other_org.id
        assert client.post("/api/v1/local-lms/connections", json={"organization_id": org.id}).status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    client = _client(monkeypatch, session, admin)
    try:
        connection_id = _connection(client, org)
        denied = client.post("/api/v1/local-lms/assignment-exchanges", json={
            "organization_id": other_org.id, "connection_id": connection_id,
            "training_assignment_id": assignment.id,
        })
        assert denied.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    with session.bind.begin() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM schema_migrations WHERE version='20260805_050'")).scalar_one() == 1
        triggers = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'trg_lms_%'"))}
    assert {"trg_lms_catalog_no_update", "trg_lms_grade_no_update", "trg_lms_event_no_update"} <= triggers
