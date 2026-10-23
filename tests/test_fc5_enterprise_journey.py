from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.competition_journey_api as journey_api
from app.auth import get_current_user, get_password_hash
from app.certification_lifecycle import scan
from app.database import (
    Base,
    DBCertification,
    DBCompetitionJourneyRun,
    DBCompetencyStandard,
    DBLocalAdapterSession,
    DBMultilevelReviewCase,
    DBOrganization,
    DBOrganizationMembership,
    DBSkillEvidence,
    DBUser,
)
from app.m1_enterprise import issue_certification, record_skill_evidence
from app.m6_enterprise import bootstrap_competition_training_demo
from app.main import app
from app.migrations import apply_registered_migrations


def fixture():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    apply_registered_migrations(engine)
    db = sessionmaker(bind=engine)()
    manager = DBUser(
        public_id="enterprise-manager",
        username="enterprise-manager",
        display_name="企业培训负责人",
        hashed_password=get_password_hash("pw"),
        role="admin",
    )
    outsider = DBUser(
        public_id="enterprise-outsider",
        username="enterprise-outsider",
        display_name="外部管理员",
        hashed_password=get_password_hash("pw"),
        role="admin",
    )
    student = DBUser(
        public_id="enterprise-student",
        username="enterprise-student",
        display_name="无企业权限学员",
        hashed_password=get_password_hash("pw"),
        role="student",
    )
    db.add_all([manager, outsider, student])
    db.commit()
    identity = bootstrap_competition_training_demo(db, actor=manager)
    learner = db.query(DBUser).filter_by(public_id=identity["learner_public_id"]).one()
    return db, manager, outsider, student, learner, identity


def client(monkeypatch, db, user):
    async def fake(operation):
        return operation(db)

    monkeypatch.setattr(journey_api, "run_db_op", fake)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def create_run(http, identity, key="enterprise-run"):
    response = http.post(
        "/api/v1/competition-journeys/enterprise/runs",
        json={
            "organization_id": identity["organization_id"],
            "learner_public_id": identity["learner_public_id"],
            "run_key": key,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def seed_practical_signoff_and_certification(db, manager, learner, run):
    base = db.get(DBCompetitionJourneyRun, run["id"]).baseline_snapshot
    session = DBLocalAdapterSession(
        owner_public_id=learner.public_id,
        title="冻结合成本地质检实操",
        adapter_id="vision-quality-line-v1",
        credential_placeholder="DEMO-LOCAL-ONLY",
        status="passed",
        parameters={"confidence_threshold": 0.65, "inspection_rate": 80, "buffer_size": 50},
        metrics={"deterministic": True},
        hidden_acceptance={"passed": True, "passed_count": 4, "total_count": 4},
    )
    db.add(session)
    db.flush()

    standards = (
        db.query(DBCompetencyStandard)
        .filter_by(job_level_id=base["job_level_id"], mandatory=True)
        .order_by(DBCompetencyStandard.id)
        .all()
    )
    existing = {
        row.competency_standard_id
        for row in db.query(DBSkillEvidence).filter_by(
            organization_id=base["organization_id"], learner_public_id=learner.public_id
        )
    }
    practical_standard = next(row for row in standards if row.id not in existing)
    practical = record_skill_evidence(
        db,
        organization_id=base["organization_id"],
        learner_public_id=learner.public_id,
        competency_standard=practical_standard,
        evidence_type=(practical_standard.evidence_requirements or ["hidden_test"])[0],
        source_object_id=session.id,
        result="passed",
        score=0.93,
        hidden_test_result={"passed": 4, "total": 4},
        actor_public_id=manager.public_id,
    )
    signoff = DBMultilevelReviewCase(
        organization_id=base["organization_id"],
        submitter_public_id=learner.public_id,
        object_type="training_assignment",
        object_id=base["assignment_id"],
        object_version=base["standard_snapshot_hash"],
        evidence_snapshot={"data_class": "frozen_synthetic_demo"},
        status="signed",
        current_level=3,
        resolved_at=datetime.utcnow(),
    )
    db.add(signoff)
    db.commit()

    return practical, standards


def issue_journey_certification(db, manager, learner, run, practical, standards):
    base = db.get(DBCompetitionJourneyRun, run["id"]).baseline_snapshot

    evidence_ids = [practical.id]
    for standard in standards:
        rows = db.query(DBSkillEvidence).filter_by(
            organization_id=base["organization_id"],
            learner_public_id=learner.public_id,
            competency_standard_id=standard.id,
            result="passed",
        ).all()
        if rows:
            evidence_ids.extend(row.id for row in rows if row.id not in evidence_ids)
            continue
        item = record_skill_evidence(
            db,
            organization_id=base["organization_id"],
            learner_public_id=learner.public_id,
            competency_standard=standard,
            evidence_type=(standard.evidence_requirements or ["artifact"])[0],
            source_object_id=f"enterprise-journey-{standard.id}",
            result="passed",
            score=0.91,
            hidden_test_result={"passed": 4, "total": 4},
            actor_public_id=manager.public_id,
        )
        evidence_ids.append(item.id)
    level = standards[0].job_level_id
    certification = issue_certification(
        db,
        organization_id=base["organization_id"],
        learner_public_id=learner.public_id,
        job_level=db.get(__import__("app.database", fromlist=["DBJobLevel"]).DBJobLevel, level),
        evidence_ids=evidence_ids,
        issuer_public_id=manager.public_id,
        retraining_rule={"completion_days": 14},
    )
    db.commit()
    return certification


def test_enterprise_scope_idempotency_and_visits_do_not_complete(monkeypatch):
    db, manager, outsider, student, learner, identity = fixture()
    http = client(monkeypatch, db, manager)
    try:
        run = create_run(http, identity)
        assert run["journey_type"] == "enterprise"
        assert run["progress"] == {"completed": 3, "total": 7, "percent": 43}
        for step in run["steps"]:
            response = http.post(
                f"/api/v1/competition-journeys/enterprise/runs/{run['id']}/visits",
                json={"step_key": step["key"], "route": step["route"]},
            )
            assert response.status_code == 201, response.text
        refreshed = http.get(
            f"/api/v1/competition-journeys/enterprise/runs/{run['id']}"
        ).json()
        assert refreshed["progress"]["completed"] == 3
        assert len(refreshed["visits"]) == 7
        replay = create_run(http, identity)
        assert replay["id"] == run["id"] and replay["created"] is False
        other_org = DBOrganization(id="enterprise-other-org", name="其他冻结组织")
        db.add(other_org)
        db.flush()
        db.add_all([
            DBOrganizationMembership(
                organization_id=other_org.id, user_public_id=manager.public_id, role="admin"
            ),
            DBOrganizationMembership(
                organization_id=other_org.id, user_public_id=learner.public_id, role="learner"
            ),
        ])
        db.commit()
        conflict = http.post(
            "/api/v1/competition-journeys/enterprise/runs",
            json={
                "organization_id": other_org.id,
                "learner_public_id": learner.public_id,
                "run_key": "enterprise-run",
            },
        )
        assert conflict.status_code == 409
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    http = client(monkeypatch, db, outsider)
    try:
        empty = http.get("/api/v1/competition-journeys/enterprise")
        assert empty.status_code == 200 and empty.json()["organizations"] == []
        assert http.get(
            f"/api/v1/competition-journeys/enterprise/runs/{run['id']}"
        ).status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    for user in (student,):
        http = client(monkeypatch, db, user)
        try:
            assert http.get("/api/v1/competition-journeys/enterprise").status_code == 403
            assert http.get(
                f"/api/v1/competition-journeys/enterprise/runs/{run['id']}"
            ).status_code == 403
        finally:
            app.dependency_overrides.pop(get_current_user, None)


def test_enterprise_evidence_closes_only_after_formal_lifecycle(monkeypatch):
    db, manager, _, _, learner, identity = fixture()
    http = client(monkeypatch, db, manager)
    try:
        run = create_run(http, identity, "enterprise-lifecycle")
        practical, standards = seed_practical_signoff_and_certification(
            db, manager, learner, run
        )
        after_practical = http.get(
            f"/api/v1/competition-journeys/enterprise/runs/{run['id']}"
        ).json()
        assert after_practical["progress"]["completed"] == 5
        certification = issue_journey_certification(
            db, manager, learner, run, practical, standards
        )
        after_cert = http.get(
            f"/api/v1/competition-journeys/enterprise/runs/{run['id']}"
        ).json()
        assert after_cert["progress"]["completed"] == 6
        assert after_cert["status"] == "active"

        certification.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
        result = scan(
            db,
            actor=manager,
            organization_id=identity["organization_id"],
            now=datetime.utcnow(),
        )
        db.commit()
        assert result["expired"] == 1 and result["retraining_created"] == 1
        final = http.get(
            f"/api/v1/competition-journeys/enterprise/runs/{run['id']}"
        ).json()
        assert final["progress"]["completed"] == 7
        assert final["status"] == "completed"
        assert next(step for step in final["steps"] if step["key"] == "retraining")[
            "complete"
        ] is True
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_migration_058_preserves_all_four_journey_types():
    db, manager, _, _, _, identity = fixture()
    assert (
        db.execute(
            text("select count(*) from schema_migrations where version='20260805_058'")
        ).scalar_one()
        == 1
    )
    rows = [
        DBCompetitionJourneyRun(
            owner_public_id=manager.public_id,
            course_id=None,
            journey_type=kind,
            run_key=f"preserved-{kind}",
            baseline_snapshot={"data_class": "synthetic_fixture"},
            baseline_hash=str(index) * 64,
        )
        for index, kind in enumerate(("student", "media", "teacher", "enterprise"), 1)
    ]
    db.add_all(rows)
    db.commit()
    assert {row.journey_type for row in db.query(DBCompetitionJourneyRun).all()} == {
        "student",
        "media",
        "teacher",
        "enterprise",
    }
