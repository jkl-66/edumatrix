from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user, get_password_hash
from app.database import (
    Base, DBChapter, DBCourse, DBCourseMembership, DBSourceDocument,
    DBStudentProfile, DBUser,
)
from app.main import app
from app.m6_enterprise import bootstrap_competition_training_demo, enterprise_workspace
import app.m6_api as m6_api
from app.m6_teacher import (
    learner_submit_intervention_evidence,
    publish_teacher_intervention,
    teacher_confirm_intervention,
    teacher_intervention_overview,
)


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    admin = DBUser(
        public_id="m6-admin",
        username="m6-admin",
        hashed_password=get_password_hash("pw"),
        role="admin",
        display_name="M6 Admin",
    )
    session.add(admin)
    session.commit()
    return session, admin


def test_m6_bootstrap_is_idempotent_and_exposes_real_gap_matrix():
    session, admin = _session()
    created = bootstrap_competition_training_demo(session, actor=admin)
    repeated = bootstrap_competition_training_demo(session, actor=admin)

    assert created["status"] == "created"
    assert repeated["status"] == "existing"
    assert repeated["organization_id"] == created["organization_id"]

    workspace = enterprise_workspace(
        session,
        actor_public_id=admin.public_id,
        organization_id=created["organization_id"],
        learner_public_id=created["learner_public_id"],
    )["selected"]
    assert workspace["assignment"]["source"] == "transfer_plan"
    assert workspace["job"]["version"] == "2026.1"
    assert workspace["summary"] == {
        "required": 3,
        "satisfied": 1,
        "gaps": 2,
        "completion_rate": 0.3333,
        "certification_ready": False,
    }
    assert {item["status"] for item in workspace["competencies"]} == {
        "satisfied", "training_required"
    }


def test_m6_enterprise_workspace_discloses_synthetic_data_and_demo_review_boundary():
    session, admin = _session()
    empty = enterprise_workspace(session, actor_public_id=admin.public_id)
    truth = empty["truthfulness"]
    assert truth["data_label"] == "冻结合成岗位标准 · 比赛演示数据"
    assert truth["uses_synthetic_data"] is True
    assert truth["uses_demo_reviewers"] is True
    assert truth["external_expert_verified"] is False
    assert truth["real_enterprise_verified"] is False

    identity = bootstrap_competition_training_demo(session, actor=admin)
    populated = enterprise_workspace(
        session,
        actor_public_id=admin.public_id,
        organization_id=identity["organization_id"],
        learner_public_id=identity["learner_public_id"],
    )
    assert populated["truthfulness"] == truth


def test_m6_http_evidence_and_certification_close_the_gap(monkeypatch):
    session, admin = _session()

    async def fake_run_db_op(operation):
        return operation(session)

    monkeypatch.setattr(m6_api, "run_db_op", fake_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: admin
    client = TestClient(app)
    try:
        boot = client.post("/api/v1/m6/demo/bootstrap")
        assert boot.status_code == 200, boot.text
        identity = boot.json()
        before = client.get(
            "/api/v1/m6/enterprise/workspace",
            params={
                "organization_id": identity["organization_id"],
                "learner_public_id": identity["learner_public_id"],
            },
        ).json()["selected"]
        gaps = [item for item in before["competencies"] if item["status"] == "training_required"]
        assert len(gaps) == 2

        for item in gaps:
            evidence_type = item["required_evidence_types"][0]
            payload = {
                "organization_id": identity["organization_id"],
                "learner_public_id": identity["learner_public_id"],
                "competency_standard_id": item["standard_id"],
                "evidence_type": evidence_type,
                "source_object_id": f"e2e-{item['skill_level']}",
                "result": "passed",
                "score": 0.91,
                "hidden_test_result": {"passed": 4, "total": 4} if evidence_type == "hidden_test" else {},
            }
            response = client.post("/api/v1/m6/enterprise/evidence", json=payload)
            assert response.status_code == 201, response.text
            if evidence_type == "expert_observation":
                assert response.json()["expert_signed"] is True

        after = client.get(
            "/api/v1/m6/enterprise/workspace",
            params={
                "organization_id": identity["organization_id"],
                "learner_public_id": identity["learner_public_id"],
            },
        ).json()["selected"]
        assert after["summary"]["certification_ready"] is True
        evidence_ids = [
            evidence["id"]
            for competency in after["competencies"]
            for evidence in competency["evidence"]
            if evidence["result"] == "passed"
        ]
        certification = client.post("/api/v1/m6/enterprise/certifications", json={
            "organization_id": identity["organization_id"],
            "learner_public_id": identity["learner_public_id"],
            "job_level_id": after["assignment"]["standard_snapshot"]["job_level_id"],
            "evidence_ids": evidence_ids,
            "retraining_rule": {"cycle_days": 180, "reason": "岗位标准周期复核"},
        })
        assert certification.status_code == 201, certification.text
        final = client.get(
            "/api/v1/m6/enterprise/workspace",
            params={
                "organization_id": identity["organization_id"],
                "learner_public_id": identity["learner_public_id"],
            },
        ).json()["selected"]
        assert len(final["certifications"]) == 1
        assert final["certifications"][0]["retraining_rule"]["cycle_days"] == 180
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_m6_learner_cannot_self_approve_enterprise_evidence(monkeypatch):
    session, admin = _session()
    identity = bootstrap_competition_training_demo(session, actor=admin)
    workspace = enterprise_workspace(
        session,
        actor_public_id=admin.public_id,
        organization_id=identity["organization_id"],
        learner_public_id=identity["learner_public_id"],
    )["selected"]
    learner = session.query(DBUser).filter_by(public_id=identity["learner_public_id"]).one()

    async def fake_run_db_op(operation):
        return operation(session)

    monkeypatch.setattr(m6_api, "run_db_op", fake_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: learner
    client = TestClient(app)
    try:
        gap = next(item for item in workspace["competencies"] if item["status"] == "training_required")
        response = client.post("/api/v1/m6/enterprise/evidence", json={
            "organization_id": identity["organization_id"],
            "learner_public_id": learner.public_id,
            "competency_standard_id": gap["standard_id"],
            "evidence_type": gap["required_evidence_types"][0],
            "source_object_id": "self-approved",
            "result": "passed",
        })
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def _teacher_fixture(session):
    teacher = DBUser(
        public_id="m6-teacher", username="m6-teacher",
        hashed_password=get_password_hash("pw"), role="teacher", display_name="Teacher",
    )
    learner = DBUser(
        public_id="m6-learner", username="m6-learner",
        hashed_password=get_password_hash("pw"), role="student", display_name="Learner",
    )
    course = DBCourse(
        id="m6-course", version="1", title="RAG 工程",
        visibility="private", manifest_version="1",
    )
    source = DBSourceDocument(
        id="m6-source", course_id=course.id, title="可信检索",
        filename="retrieval.md", file_format="md", content_hash="a" * 64,
    )
    session.add_all([teacher, learner, course, source])
    session.flush()
    session.add_all([
        DBCourseMembership(course_id=course.id, user_public_id=teacher.public_id, role="teacher"),
        DBCourseMembership(course_id=course.id, user_public_id=learner.public_id, role="student"),
        DBChapter(
            id="m6-chapter", course_id=course.id, source_document_id=source.id,
            stable_key="retrieval", title="混合检索", position=1,
        ),
        DBStudentProfile(
            student_id=learner.username,
            concept_mastery={"混合检索与重排": 0.28, "引用约束": 0.55},
        ),
    ])
    session.commit()
    return teacher, learner, course


def test_m6_teacher_intervention_requires_learner_evidence_then_teacher_confirmation():
    session, _ = _session()
    teacher, learner, course = _teacher_fixture(session)
    published = publish_teacher_intervention(
        session,
        actor=teacher,
        course_id=course.id,
        learner_public_id=learner.public_id,
        idempotency_key="teacher-intervention-001",
    )
    assert published["concept"] == "混合检索与重排"
    assert published["baseline_mastery"] == 0.28
    overview = teacher_intervention_overview(session, actor=teacher, course_id=course.id)
    assert overview["interventions"][0]["node_status"] == "pending"

    evidence = learner_submit_intervention_evidence(
        session, actor=learner, path_id=published["path_id"], active_seconds=900,
    )
    assert evidence["node_status"] == "in_progress"
    overview = teacher_intervention_overview(session, actor=teacher, course_id=course.id)
    assert overview["interventions"][0]["learner_event_id"] == evidence["event_id"]

    confirmed = teacher_confirm_intervention(
        session,
        actor=teacher,
        path_id=published["path_id"],
        learner_event_id=evidence["event_id"],
    )
    assert confirmed["node_status"] == "completed"
    assert confirmed["path_status"] == "completed"
    final = teacher_intervention_overview(session, actor=teacher, course_id=course.id)
    assert final["interventions"][0]["teacher_confirmed"] is True


def test_m6_teacher_http_intervention_enforces_actor_responsibility(monkeypatch):
    session, _ = _session()
    teacher, learner, course = _teacher_fixture(session)

    async def fake_run_db_op(operation):
        return operation(session)

    identity = {"user": teacher}
    monkeypatch.setattr(m6_api, "run_db_op", fake_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: identity["user"]
    client = TestClient(app)
    try:
        created = client.post("/api/v1/m6/teacher/interventions", json={
            "course_id": course.id,
            "learner_public_id": learner.public_id,
            "idempotency_key": "teacher-intervention-http-001",
        })
        assert created.status_code == 201, created.text
        path_id = created.json()["path_id"]

        identity["user"] = learner
        premature = client.post(
            f"/api/v1/m6/teacher/interventions/{path_id}/confirm",
            json={"learner_event_id": "missing"},
        )
        assert premature.status_code == 403
        evidence = client.post(
            f"/api/v1/m6/teacher/interventions/{path_id}/learner-evidence",
            json={"active_seconds": 900},
        )
        assert evidence.status_code == 200, evidence.text

        identity["user"] = teacher
        confirmed = client.post(
            f"/api/v1/m6/teacher/interventions/{path_id}/confirm",
            json={"learner_event_id": evidence.json()["event_id"]},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["path_status"] == "completed"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
