from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.auth import get_password_hash
from app.database import (
    DBAuditLog,
    DBCertification,
    DBCompetencyStandard,
    DBExternalIdentityMapping,
    DBJobFamily,
    DBJobLevel,
    DBOrganization,
    DBOrganizationMembership,
    DBSkillEvidence,
    DBSkillStandard,
    DBTrainingAssignment,
    DBTrainingCohort,
    DBTrainingProgram,
    DBUser,
    SessionLocal,
    init_db,
)
from app.identity import new_public_id
from app.m1_enterprise import (
    add_organization_member, approve_exemption, assign_training, bind_external_identity,
    create_competency_standard, create_job_family, create_job_level, create_organization,
    create_training_cohort, create_training_program, issue_certification,
    publish_job_standard_version, record_skill_evidence, request_exemption,
    require_organization_access,
    revoke_external_identity,
)
from app.m1_evidence import seed_rag_domain_pack


init_db()


def _user(session, prefix):
    row = DBUser(
        username=new_public_id(prefix), hashed_password=get_password_hash("pw")
    )
    session.add(row)
    session.flush()
    return row


def _enterprise_fixture(session, *, risk="normal", exemption="allowed"):
    domain = seed_rag_domain_pack(session)
    skill = (
        session.query(DBSkillStandard)
        .filter_by(domain_version_id=domain["domain_version_id"])
        .first()
    )
    org = DBOrganization(name=new_public_id("org-name"))
    session.add(org)
    session.flush()
    learner = _user(session, "learner")
    admin = _user(session, "admin")
    session.add_all(
        [
            DBOrganizationMembership(
                organization_id=org.id,
                user_public_id=learner.public_id,
                role="learner",
            ),
            DBOrganizationMembership(
                organization_id=org.id,
                user_public_id=admin.public_id,
                role="admin",
            ),
        ]
    )
    session.flush()
    family = DBJobFamily(
        organization_id=org.id, code="RAG", title="RAG Engineer"
    )
    session.add(family)
    session.flush()
    level = DBJobLevel(
        job_family_id=family.id,
        level_code="L1",
        version="1",
        title="Junior",
        status="published",
    )
    session.add(level)
    session.flush()
    standard = DBCompetencyStandard(
        job_level_id=level.id,
        skill_standard_id=skill.id,
        requirement_level="independent",
        risk_level=risk,
        exemption_policy=exemption,
    )
    session.add(standard)
    session.flush()
    program = DBTrainingProgram(
        organization_id=org.id,
        target_job_level_id=level.id,
        title="RAG onboarding",
        version="1",
    )
    session.add(program)
    session.flush()
    snapshot = {
        "job_level_id": level.id,
        "job_level_version": level.version,
        "competency_ids": [standard.id],
    }
    cohort = DBTrainingCohort(
        organization_id=org.id,
        training_program_id=program.id,
        standard_snapshot=snapshot,
        course_versions=["course-rag-engineering-m0@0.1"],
    )
    session.add(cohort)
    session.flush()
    assignment = DBTrainingAssignment(
        organization_id=org.id,
        cohort_id=cohort.id,
        learner_public_id=learner.public_id,
        assignment_source="organization",
    )
    session.add(assignment)
    session.flush()
    return org, learner, admin, level, standard, cohort, assignment


def test_cross_organization_access_denied_and_cohort_snapshot_locked():
    with SessionLocal() as session:
        org, learner, admin, level, standard, cohort, assignment = _enterprise_fixture(
            session
        )
        outsider = _user(session, "outsider")
        with pytest.raises(HTTPException) as raised:
            require_organization_access(
                session,
                organization_id=org.id,
                user_public_id=outsider.public_id,
            )
        assert raised.value.status_code == 403
        original = dict(cohort.standard_snapshot)
        level.version = "2"
        session.commit()
        session.refresh(cohort)
        assert cohort.standard_snapshot == original


def test_exemption_policy_and_enterprise_evidence_chain():
    with SessionLocal() as session:
        org, learner, admin, level, standard, cohort, assignment = _enterprise_fixture(
            session
        )
        request = request_exemption(
            session,
            assignment_id=assignment.id,
            competency_standard_id=standard.id,
            requester_public_id=learner.public_id,
            evidence_ids=["evidence-1"],
        )
        approve_exemption(
            session, request=request, approver_public_id=admin.public_id
        )
        evidence = DBSkillEvidence(
            organization_id=org.id,
            learner_public_id=learner.public_id,
            competency_standard_id=standard.id,
            evidence_type="hidden_test",
            source_object_id="artifact-v1",
            result="passed",
            hidden_test_result={"passed": 5},
        )
        session.add(evidence)
        session.flush()
        cert = DBCertification(
            organization_id=org.id,
            learner_public_id=learner.public_id,
            job_level_id=level.id,
            standard_snapshot=cohort.standard_snapshot,
            evidence_ids=[evidence.id],
            issuer_public_id=admin.public_id,
            retraining_rule={"months": 12},
        )
        session.add(cert)
        session.commit()
        assert request.status == "approved"
        assert cert.standard_snapshot["job_level_version"] == "1"
        assert standard.version == "1"
        actions = {row.action for row in session.query(DBAuditLog).filter_by(object_id=request.id)}
        assert actions == {"exemption.request", "exemption.approve"}


def test_high_risk_forbidden_exemption_and_external_identity_uniqueness():
    with SessionLocal() as session:
        org, learner, admin, level, standard, cohort, assignment = _enterprise_fixture(
            session, risk="high", exemption="forbidden"
        )
        with pytest.raises(HTTPException) as raised:
            request_exemption(
                session,
                assignment_id=assignment.id,
                competency_standard_id=standard.id,
                requester_public_id=learner.public_id,
                evidence_ids=[],
            )
        assert raised.value.status_code == 403
        first = DBExternalIdentityMapping(
            organization_id=org.id,
            user_public_id=learner.public_id,
            provider="mock-sso",
            external_subject="employee-001",
        )
        session.add(first)
        session.commit()
        assert first.user_public_id != first.external_subject
        session.add(
            DBExternalIdentityMapping(
                organization_id=org.id,
                user_public_id=admin.public_id,
                provider="mock-sso",
                external_subject="employee-001",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_cross_organization_training_reference_is_rejected_by_database():
    with SessionLocal() as session:
        org, learner, admin, level, standard, cohort, assignment = _enterprise_fixture(session)
        other = DBOrganization(name=new_public_id("other-org"))
        session.add(other)
        session.flush()
        session.add(DBTrainingProgram(
            organization_id=other.id, target_job_level_id=level.id,
            title="Invalid cross-tenant program", version="1",
        ))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_external_identity_binding_requires_org_admin_and_is_audited():
    with SessionLocal() as session:
        org, learner, admin, level, standard, cohort, assignment = _enterprise_fixture(session)
        outsider = _user(session, "external-outsider")
        with pytest.raises(HTTPException) as raised:
            bind_external_identity(
                session, organization_id=org.id, user_public_id=learner.public_id,
                provider="enterprise-sso", external_subject="employee-100",
                actor_public_id=outsider.public_id,
            )
        assert raised.value.status_code == 403
        mapping = bind_external_identity(
            session, organization_id=org.id, user_public_id=learner.public_id,
            provider="enterprise-sso", external_subject="employee-100",
            actor_public_id=admin.public_id,
        )
        revoke_external_identity(session, mapping=mapping, actor_public_id=admin.public_id)
        session.commit()
        assert mapping.status == "revoked"
        assert mapping.revoked_at is not None
        actions = {row.action for row in session.query(DBAuditLog).filter_by(object_id=mapping.id)}
        assert actions == {"external_identity.bind", "external_identity.revoke"}


def test_enterprise_write_services_enforce_scope_snapshot_versions_and_audit():
    with SessionLocal() as session:
        domain = seed_rag_domain_pack(session)
        skill = session.query(DBSkillStandard).filter_by(
            domain_version_id=domain["domain_version_id"]
        ).first()
        global_admin = _user(session, "global-admin")
        global_admin.role = "admin"
        learner = _user(session, "managed-learner")
        organization = create_organization(
            session, name="Managed enterprise", actor=global_admin
        )
        add_organization_member(
            session, organization_id=organization.id,
            user_public_id=learner.public_id, role="learner",
            actor_public_id=global_admin.public_id,
        )
        family = create_job_family(
            session, organization_id=organization.id, code="RAG-MANAGED",
            title="RAG Engineering", actor_public_id=global_admin.public_id,
        )
        level = create_job_level(
            session, job_family=family, level_code="L2", version="2026.1",
            title="Independent", actor_public_id=global_admin.public_id,
        )
        standard = create_competency_standard(
            session, job_level=level, skill_standard=skill,
            requirement_level="independent", version="standard-1",
            actor_public_id=global_admin.public_id,
            evidence_requirements=["hidden_test"], acceptance_rules=["all_required_pass"],
        )
        program = create_training_program(
            session, organization_id=organization.id, target_job_level=level,
            title="Managed RAG onboarding", version="1",
            actor_public_id=global_admin.public_id,
        )
        cohort = create_training_cohort(
            session, program=program, actor_public_id=global_admin.public_id,
            course_versions=["course-rag-engineering-m0@0.1"],
        )
        assignment = assign_training(
            session, cohort=cohort, learner_public_id=learner.public_id,
            assignment_source="organization", actor_public_id=global_admin.public_id,
        )
        evidence = record_skill_evidence(
            session, organization_id=organization.id,
            learner_public_id=learner.public_id, competency_standard=standard,
            evidence_type="hidden_test", source_object_id="artifact-version-1",
            result="passed", actor_public_id=global_admin.public_id,
            hidden_test_result={"passed": 8, "total": 8},
        )
        certification = issue_certification(
            session, organization_id=organization.id,
            learner_public_id=learner.public_id, job_level=level,
            evidence_ids=[evidence.id], issuer_public_id=global_admin.public_id,
            retraining_rule={"months": 12},
        )
        session.commit()

        assert assignment.organization_id == organization.id
        assert cohort.standard_snapshot["competencies"][0]["version"] == "standard-1"
        assert certification.standard_snapshot["job_level_version"] == "2026.1"
        new_level, new_standards = publish_job_standard_version(
            session, source_job_level=level, new_version="2026.2",
            actor_public_id=global_admin.public_id,
        )
        session.commit()
        assert level.version == "2026.1"
        assert standard.version == "standard-1"
        assert new_level.id != level.id
        assert new_level.version == "2026.2"
        assert [item.version for item in new_standards] == ["2026.2"]
        assert cohort.standard_snapshot["competencies"][0]["version"] == "standard-1"
        assert certification.standard_snapshot["competencies"][0]["version"] == "standard-1"
        audited_types = {
            row.object_type for row in session.query(DBAuditLog).all()
            if (row.metadata_json or {}).get("organization_id") == organization.id
        }
        assert {"organization", "organization_membership", "job_family", "job_level",
                "competency_standard", "training_program", "training_cohort",
                "training_assignment", "skill_evidence", "certification"} <= audited_types
        version_actions = {
            row.action for row in session.query(DBAuditLog).filter(
                DBAuditLog.object_id.in_([new_level.id, new_standards[0].id])
            ).all()
        }
        assert version_actions == {
            "job_standard_version.publish",
            "competency_standard_version.publish",
        }
