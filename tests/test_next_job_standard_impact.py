from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user, get_password_hash
from app.database import (
    Base, DBCertification, DBCompetencyStandard, DBDomainPack, DBDomainVersion, DBJobFamily, DBJobLevel,
    DBJobStandardImpactConfirmation, DBJobStandardImpactPreview,
    DBOrganization, DBOrganizationMembership, DBRetrainingTask, DBSkillStandard,
    DBTrainingAssignment, DBTrainingCohort, DBTrainingProgram, DBUser,
)
from app.job_standard_impact import (
    JobStandardImpactError, confirm_preview, create_preview, prepare_demo_upgrade, workspace,
)
from app.main import app
import app.job_standard_impact_api as impact_api


def _fixture():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    admin = DBUser(public_id="impact-admin", username="impact-admin", hashed_password=get_password_hash("pw"), role="admin", display_name="标准主管")
    manager = DBUser(public_id="impact-manager", username="impact-manager", hashed_password=get_password_hash("pw"), role="teacher", display_name="培训经理")
    learner = DBUser(public_id="impact-learner", username="impact-learner", hashed_password=get_password_hash("pw"), role="student", display_name="学习者")
    outsider = DBUser(public_id="impact-outsider", username="impact-outsider", hashed_password=get_password_hash("pw"), role="teacher", display_name="外部人员")
    organization = DBOrganization(id="impact-org", name="合成企业能力中心", organization_type="enterprise")
    other_org = DBOrganization(id="impact-other-org", name="隔离组织", organization_type="enterprise")
    db.add_all([admin, manager, learner, outsider, organization, other_org]); db.flush()
    db.add_all([
        DBOrganizationMembership(organization_id=organization.id, user_public_id=admin.public_id, role="admin"),
        DBOrganizationMembership(organization_id=organization.id, user_public_id=manager.public_id, role="manager"),
        DBOrganizationMembership(organization_id=organization.id, user_public_id=learner.public_id, role="learner"),
        DBOrganizationMembership(organization_id=other_org.id, user_public_id=outsider.public_id, role="admin"),
    ]); db.flush()
    family = DBJobFamily(id="impact-family", organization_id=organization.id, code="AI-ENG", title="AI 工程")
    source = DBJobLevel(id="impact-level-v1", job_family_id=family.id, level_code="L2", version="2026.1", title="AI 应用工程师", responsibilities=["构建 RAG 应用"], status="published")
    target = DBJobLevel(id="impact-level-v2", job_family_id=family.id, level_code="L2", version="2026.2", title="AI 应用工程师", responsibilities=["构建 RAG 应用", "执行可靠性评测"], status="published")
    domain = DBDomainPack(id="impact-domain", domain_key="impact-ai", title="合成 AI 能力域", status="active")
    domain_version = DBDomainVersion(id="impact-domain-v1", domain_pack_id=domain.id, version="1", content_hash="a" * 64)
    skill_a = DBSkillStandard(id="impact-skill-a", domain_version_id=domain_version.id, code="RAG", title="RAG 工程", level="L2")
    skill_b = DBSkillStandard(id="impact-skill-b", domain_version_id=domain_version.id, code="EVAL", title="可靠性评测", level="L2")
    db.add_all([family, source, target, domain, domain_version, skill_a, skill_b]); db.flush()
    old_standard = DBCompetencyStandard(id="impact-standard-old", job_level_id=source.id, skill_standard_id=skill_a.id, requirement_level="working", version="2026.1", evidence_requirements=["hidden_test"], risk_level="normal")
    new_standard = DBCompetencyStandard(id="impact-standard-new-a", job_level_id=target.id, skill_standard_id=skill_a.id, requirement_level="advanced", version="2026.2", evidence_requirements=["hidden_test", "artifact"], risk_level="high")
    added_standard = DBCompetencyStandard(id="impact-standard-new-b", job_level_id=target.id, skill_standard_id=skill_b.id, requirement_level="working", version="2026.2", evidence_requirements=["artifact"], risk_level="normal")
    db.add_all([old_standard, new_standard, added_standard]); db.flush()
    program = DBTrainingProgram(id="impact-program-old", organization_id=organization.id, target_job_level_id=source.id, title="旧版转岗培训", version="2026.1", status="published")
    cohort = DBTrainingCohort(id="impact-cohort-old", organization_id=organization.id, training_program_id=program.id, standard_snapshot={"job_level_id": source.id, "job_level_version": source.version}, status="active")
    assignment = DBTrainingAssignment(id="impact-assignment-old", organization_id=organization.id, cohort_id=cohort.id, learner_public_id=learner.public_id, assignment_source="transfer_plan")
    certification = DBCertification(id="impact-cert", organization_id=organization.id, learner_public_id=learner.public_id, job_level_id=source.id, standard_snapshot={"job_level_id": source.id, "job_level_version": source.version}, status="active", retraining_rule={"completion_days": 21})
    db.add_all([program, cohort, assignment, certification]); db.commit()
    return db, admin, manager, learner, outsider, organization, source, target, cohort, certification


def test_preview_diff_impact_and_old_snapshots_are_frozen():
    db, _, manager, _, _, organization, source, target, cohort, certification = _fixture()
    preview, created = create_preview(db, actor=manager, organization_id=organization.id, source_job_level_id=source.id, target_job_level_id=target.id)
    db.commit()
    assert created is True
    assert preview.standard_source == "frozen_synthetic_competition_demo"
    assert preview.diff_snapshot["responsibilities"]["changed"] is True
    assert len(preview.diff_snapshot["competencies"]["added"]) == 1
    assert len(preview.diff_snapshot["competencies"]["changed"]) == 1
    assert preview.impact_snapshot["counts"] == {"programs": 1, "cohorts": 1, "assignments": 1, "certifications": 1, "learners": 1}
    assert cohort.standard_snapshot["job_level_version"] == "2026.1"
    assert certification.standard_snapshot["job_level_version"] == "2026.1"


def test_confirmation_requires_exact_hash_and_is_idempotent():
    db, _, manager, _, _, organization, source, target, cohort, certification = _fixture()
    preview, _ = create_preview(db, actor=manager, organization_id=organization.id, source_job_level_id=source.id, target_job_level_id=target.id)
    with __import__("pytest").raises(JobStandardImpactError) as stale:
        confirm_preview(db, actor=manager, preview_id=preview.id, preview_hash="0" * 64, reason="确认升级影响")
    assert stale.value.code == "job_standard_preview_stale"
    confirmed, confirmation, created = confirm_preview(db, actor=manager, preview_id=preview.id, preview_hash=preview.preview_hash, reason="确认合成标准升级并安排复训")
    db.commit()
    again, repeated, made_again = confirm_preview(db, actor=manager, preview_id=preview.id, preview_hash=preview.preview_hash, reason="重复确认不应重复调度")
    db.commit()
    assert created is True and made_again is False
    assert confirmation.id == repeated.id and confirmed.id == again.id
    assert db.query(DBJobStandardImpactConfirmation).count() == 1
    assert db.query(DBTrainingProgram).count() == 2
    assert db.query(DBTrainingCohort).count() == 2
    assert db.query(DBTrainingAssignment).count() == 2
    assert db.query(DBRetrainingTask).count() == 1
    new_cohort = db.query(DBTrainingCohort).filter(DBTrainingCohort.id != cohort.id).one()
    assert new_cohort.standard_snapshot["job_level_version"] == "2026.2"
    assert certification.standard_snapshot["job_level_version"] == "2026.1"


def test_only_same_organization_manager_or_admin_can_operate():
    db, _, manager, learner, outsider, organization, source, target, *_ = _fixture()
    import pytest
    with pytest.raises(JobStandardImpactError) as learner_denied:
        create_preview(db, actor=learner, organization_id=organization.id, source_job_level_id=source.id, target_job_level_id=target.id)
    assert learner_denied.value.code == "job_standard_impact_forbidden"
    with pytest.raises(JobStandardImpactError) as outsider_denied:
        create_preview(db, actor=outsider, organization_id=organization.id, source_job_level_id=source.id, target_job_level_id=target.id)
    assert outsider_denied.value.code == "job_standard_impact_forbidden"
    assert workspace(db, actor=manager, organization_id=organization.id)["truth_label"].startswith("冻结合成")


def test_http_preview_confirmation_and_learner_403(monkeypatch):
    db, _, manager, learner, _, organization, source, target, *_ = _fixture()
    async def fake_run_db_op(operation):
        return operation(db)
    monkeypatch.setattr(impact_api, "run_db_op", fake_run_db_op)
    identity = {"user": learner}
    app.dependency_overrides[get_current_user] = lambda: identity["user"]
    client = TestClient(app)
    try:
        denied = client.get("/api/v1/job-standard-impact/workspace", params={"organization_id": organization.id})
        assert denied.status_code == 403
        identity["user"] = manager
        created = client.post("/api/v1/job-standard-impact/previews", json={"organization_id": organization.id, "source_job_level_id": source.id, "target_job_level_id": target.id})
        assert created.status_code == 201, created.text
        preview = created.json()["preview"]
        confirmed = client.post(f"/api/v1/job-standard-impact/previews/{preview['id']}/confirm", json={"preview_hash": preview["preview_hash"], "reason": "确认演示标准升级影响"})
        assert confirmed.status_code == 200, confirmed.text
        loaded = client.get("/api/v1/job-standard-impact/workspace", params={"organization_id": organization.id})
        assert loaded.status_code == 200
        assert loaded.json()["previews"][0]["status"] == "confirmed"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_demo_upgrade_is_admin_only_and_idempotent():
    db, admin, manager, *_rest = _fixture()
    organization, source = _rest[2], _rest[3]
    import pytest
    with pytest.raises(JobStandardImpactError) as denied:
        prepare_demo_upgrade(db, actor=manager, organization_id=organization.id, source_job_level_id=source.id, target_version="2026.3")
    assert denied.value.code == "job_standard_publish_forbidden"
    target, created = prepare_demo_upgrade(db, actor=admin, organization_id=organization.id, source_job_level_id=source.id, target_version="2026.3")
    repeated, created_again = prepare_demo_upgrade(db, actor=admin, organization_id=organization.id, source_job_level_id=source.id, target_version="2026.3")
    assert created is True and created_again is False and target.id == repeated.id
    assert "执行模型可靠性评测与可追溯交付" in target.responsibilities
