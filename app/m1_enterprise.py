"""Enterprise tenant policy and training-governance operations."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.database import (
    DBAuditLog, DBCertification, DBCompetencyStandard, DBExemptionRequest,
    DBExternalIdentityMapping, DBJobFamily, DBJobLevel, DBOrganization,
    DBOrganizationMembership, DBSkillEvidence, DBSkillStandard, DBTrainingAssignment,
    DBTrainingCohort, DBTrainingProgram, DBUser,
)
from app.identity import normalize_role
from app.m1_lifecycle import record_audit, utcnow


def _audit_enterprise(session: Any, *, actor_public_id: str, action: str,
                      object_type: str, object_id: str, organization_id: str) -> DBAuditLog:
    return record_audit(
        session, actor_public_id=actor_public_id, action=action,
        object_type=object_type, object_id=object_id,
        metadata={"organization_id": organization_id},
    )


def create_organization(
    session: Any, *, name: str, actor: DBUser,
    organization_type: str = "enterprise", sharing_policy: dict | None = None,
) -> DBOrganization:
    if normalize_role(actor.role) != "admin":
        raise HTTPException(status_code=403, detail="只有系统管理员可创建组织")
    organization = DBOrganization(
        name=name, organization_type=organization_type,
        sharing_policy=sharing_policy or {},
    )
    session.add(organization)
    session.flush()
    session.add(DBOrganizationMembership(
        organization_id=organization.id, user_public_id=actor.public_id, role="admin"
    ))
    session.flush()
    _audit_enterprise(
        session, actor_public_id=actor.public_id, action="organization.create",
        object_type="organization", object_id=organization.id,
        organization_id=organization.id,
    )
    return organization


def add_organization_member(
    session: Any, *, organization_id: str, user_public_id: str,
    role: str, actor_public_id: str,
) -> DBOrganizationMembership:
    require_organization_access(
        session, organization_id=organization_id,
        user_public_id=actor_public_id, action="manage",
    )
    user = session.query(DBUser).filter_by(public_id=user_public_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    membership = DBOrganizationMembership(
        organization_id=organization_id, user_public_id=user_public_id, role=role,
    )
    session.add(membership)
    session.flush()
    _audit_enterprise(
        session, actor_public_id=actor_public_id, action="organization_member.add",
        object_type="organization_membership", object_id=membership.id,
        organization_id=organization_id,
    )
    return membership


def create_job_family(
    session: Any, *, organization_id: str, code: str, title: str,
    actor_public_id: str,
) -> DBJobFamily:
    require_organization_access(
        session, organization_id=organization_id,
        user_public_id=actor_public_id, action="manage",
    )
    row = DBJobFamily(organization_id=organization_id, code=code, title=title)
    session.add(row); session.flush()
    _audit_enterprise(session, actor_public_id=actor_public_id, action="job_family.create",
                      object_type="job_family", object_id=row.id, organization_id=organization_id)
    return row


def create_job_level(
    session: Any, *, job_family: DBJobFamily, level_code: str, version: str,
    title: str, actor_public_id: str, responsibilities: list | None = None,
) -> DBJobLevel:
    require_organization_access(
        session, organization_id=job_family.organization_id,
        user_public_id=actor_public_id, action="manage",
    )
    row = DBJobLevel(
        job_family_id=job_family.id, level_code=level_code, version=version,
        title=title, responsibilities=responsibilities or [], status="published",
    )
    session.add(row); session.flush()
    _audit_enterprise(session, actor_public_id=actor_public_id, action="job_level.create",
                      object_type="job_level", object_id=row.id,
                      organization_id=job_family.organization_id)
    return row


def create_competency_standard(
    session: Any, *, job_level: DBJobLevel, skill_standard: DBSkillStandard,
    requirement_level: str, version: str, actor_public_id: str,
    evidence_requirements: list | None = None, mandatory: bool = True,
    risk_level: str = "normal", exemption_policy: str = "allowed",
    acceptance_rules: list | None = None,
) -> DBCompetencyStandard:
    family = session.query(DBJobFamily).filter_by(id=job_level.job_family_id).one()
    require_organization_access(
        session, organization_id=family.organization_id,
        user_public_id=actor_public_id, action="manage",
    )
    row = DBCompetencyStandard(
        job_level_id=job_level.id, skill_standard_id=skill_standard.id,
        requirement_level=requirement_level, version=version,
        evidence_requirements=evidence_requirements or [], mandatory=mandatory,
        risk_level=risk_level, exemption_policy=exemption_policy,
        acceptance_rules=acceptance_rules or [],
    )
    session.add(row); session.flush()
    _audit_enterprise(session, actor_public_id=actor_public_id, action="competency_standard.create",
                      object_type="competency_standard", object_id=row.id,
                      organization_id=family.organization_id)
    return row


def publish_job_standard_version(
    session: Any, *, source_job_level: DBJobLevel, new_version: str,
    actor_public_id: str, title: str | None = None,
    responsibilities: list | None = None,
) -> tuple[DBJobLevel, list[DBCompetencyStandard]]:
    """Publish a new immutable job-level standard without rewriting history."""
    family = session.query(DBJobFamily).filter_by(
        id=source_job_level.job_family_id
    ).one()
    require_organization_access(
        session, organization_id=family.organization_id,
        user_public_id=actor_public_id, action="manage",
    )
    normalized_version = str(new_version).strip()
    if not normalized_version:
        raise HTTPException(status_code=400, detail="新版本号不能为空")
    duplicate = session.query(DBJobLevel).filter_by(
        job_family_id=source_job_level.job_family_id,
        level_code=source_job_level.level_code,
        version=normalized_version,
    ).first()
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="岗位标准版本已存在")

    source_standards = session.query(DBCompetencyStandard).filter_by(
        job_level_id=source_job_level.id
    ).order_by(DBCompetencyStandard.id).all()
    new_level = DBJobLevel(
        job_family_id=source_job_level.job_family_id,
        level_code=source_job_level.level_code,
        version=normalized_version,
        title=title or source_job_level.title,
        responsibilities=(
            list(responsibilities) if responsibilities is not None
            else list(source_job_level.responsibilities or [])
        ),
        effective_from=source_job_level.effective_from,
        effective_to=source_job_level.effective_to,
        status="published",
    )
    session.add(new_level)
    session.flush()
    _audit_enterprise(
        session, actor_public_id=actor_public_id,
        action="job_standard_version.publish",
        object_type="job_level", object_id=new_level.id,
        organization_id=family.organization_id,
    )

    new_standards = []
    for source in source_standards:
        standard = DBCompetencyStandard(
            job_level_id=new_level.id,
            skill_standard_id=source.skill_standard_id,
            requirement_level=source.requirement_level,
            version=normalized_version,
            evidence_requirements=list(source.evidence_requirements or []),
            mandatory=source.mandatory,
            risk_level=source.risk_level,
            exemption_policy=source.exemption_policy,
            acceptance_rules=list(source.acceptance_rules or []),
        )
        session.add(standard)
        session.flush()
        new_standards.append(standard)
        _audit_enterprise(
            session, actor_public_id=actor_public_id,
            action="competency_standard_version.publish",
            object_type="competency_standard", object_id=standard.id,
            organization_id=family.organization_id,
        )
    return new_level, new_standards


def create_training_program(
    session: Any, *, organization_id: str, target_job_level: DBJobLevel,
    title: str, version: str, actor_public_id: str,
) -> DBTrainingProgram:
    family = session.query(DBJobFamily).filter_by(id=target_job_level.job_family_id).one()
    if family.organization_id != organization_id:
        raise HTTPException(status_code=400, detail="岗位等级不属于目标组织")
    require_organization_access(
        session, organization_id=organization_id,
        user_public_id=actor_public_id, action="manage",
    )
    row = DBTrainingProgram(
        organization_id=organization_id, target_job_level_id=target_job_level.id,
        title=title, version=version,
    )
    session.add(row); session.flush()
    _audit_enterprise(session, actor_public_id=actor_public_id, action="training_program.create",
                      object_type="training_program", object_id=row.id,
                      organization_id=organization_id)
    return row


def create_training_cohort(
    session: Any, *, program: DBTrainingProgram, actor_public_id: str,
    course_versions: list[str] | None = None, resource_version_ids: list[str] | None = None,
    assessment_versions: list[str] | None = None,
) -> DBTrainingCohort:
    require_organization_access(
        session, organization_id=program.organization_id,
        user_public_id=actor_public_id, action="manage",
    )
    level = session.query(DBJobLevel).filter_by(id=program.target_job_level_id).one()
    standards = session.query(DBCompetencyStandard).filter_by(job_level_id=level.id).order_by(
        DBCompetencyStandard.id
    ).all()
    snapshot = {
        "job_level_id": level.id, "job_level_version": level.version,
        "competencies": [{"id": item.id, "version": item.version,
                          "skill_standard_id": item.skill_standard_id,
                          "requirement_level": item.requirement_level,
                          "risk_level": item.risk_level} for item in standards],
    }
    row = DBTrainingCohort(
        organization_id=program.organization_id, training_program_id=program.id,
        standard_snapshot=snapshot, course_versions=course_versions or [],
        resource_version_ids=resource_version_ids or [],
        assessment_versions=assessment_versions or [],
    )
    session.add(row); session.flush()
    _audit_enterprise(session, actor_public_id=actor_public_id, action="training_cohort.create",
                      object_type="training_cohort", object_id=row.id,
                      organization_id=program.organization_id)
    return row


def assign_training(
    session: Any, *, cohort: DBTrainingCohort, learner_public_id: str,
    assignment_source: str, actor_public_id: str, source_reference: str = "",
) -> DBTrainingAssignment:
    require_organization_access(
        session, organization_id=cohort.organization_id,
        user_public_id=actor_public_id, action="assign",
    )
    member = session.query(DBOrganizationMembership).filter_by(
        organization_id=cohort.organization_id, user_public_id=learner_public_id, status="active"
    ).first()
    if member is None:
        raise HTTPException(status_code=400, detail="只能向组织内有效成员分配培训")
    row = DBTrainingAssignment(
        organization_id=cohort.organization_id, cohort_id=cohort.id,
        learner_public_id=learner_public_id, assignment_source=assignment_source,
        source_reference=source_reference,
    )
    session.add(row); session.flush()
    _audit_enterprise(session, actor_public_id=actor_public_id, action="training_assignment.create",
                      object_type="training_assignment", object_id=row.id,
                      organization_id=cohort.organization_id)
    return row


def record_skill_evidence(
    session: Any, *, organization_id: str, learner_public_id: str,
    competency_standard: DBCompetencyStandard, evidence_type: str,
    source_object_id: str, result: str, actor_public_id: str,
    score: float | None = None, hidden_test_result: dict | None = None,
) -> DBSkillEvidence:
    level = session.query(DBJobLevel).filter_by(id=competency_standard.job_level_id).one()
    family = session.query(DBJobFamily).filter_by(id=level.job_family_id).one()
    if family.organization_id != organization_id:
        raise HTTPException(status_code=400, detail="能力标准不属于目标组织")
    role = organization_role(
        session, organization_id=organization_id, user_public_id=actor_public_id
    )
    if actor_public_id != learner_public_id and role not in {"mentor", "manager", "admin"}:
        raise HTTPException(status_code=403, detail="无权记录该学员的技能证据")
    row = DBSkillEvidence(
        organization_id=organization_id, learner_public_id=learner_public_id,
        competency_standard_id=competency_standard.id, evidence_type=evidence_type,
        source_object_id=source_object_id, result=result, score=score,
        hidden_test_result=hidden_test_result or {},
    )
    session.add(row); session.flush()
    _audit_enterprise(session, actor_public_id=actor_public_id, action="skill_evidence.record",
                      object_type="skill_evidence", object_id=row.id,
                      organization_id=organization_id)
    return row


def issue_certification(
    session: Any, *, organization_id: str, learner_public_id: str,
    job_level: DBJobLevel, evidence_ids: list[str], issuer_public_id: str,
    retraining_rule: dict | None = None,
) -> DBCertification:
    require_organization_access(
        session, organization_id=organization_id,
        user_public_id=issuer_public_id, action="approve",
    )
    family = session.query(DBJobFamily).filter_by(id=job_level.job_family_id).one()
    if family.organization_id != organization_id:
        raise HTTPException(status_code=400, detail="认证岗位不属于目标组织")
    evidence = session.query(DBSkillEvidence).filter(DBSkillEvidence.id.in_(evidence_ids)).all()
    if len(evidence) != len(set(evidence_ids)) or any(
        item.organization_id != organization_id or item.learner_public_id != learner_public_id
        for item in evidence
    ):
        raise HTTPException(status_code=400, detail="认证证据不完整或不属于目标学员")
    standards = session.query(DBCompetencyStandard).filter_by(job_level_id=job_level.id).order_by(
        DBCompetencyStandard.id
    ).all()
    snapshot = {"job_level_id": job_level.id, "job_level_version": job_level.version,
                "competencies": [{"id": item.id, "version": item.version} for item in standards]}
    row = DBCertification(
        organization_id=organization_id, learner_public_id=learner_public_id,
        job_level_id=job_level.id, standard_snapshot=snapshot,
        evidence_ids=evidence_ids, issuer_public_id=issuer_public_id,
        retraining_rule=retraining_rule or {},
    )
    session.add(row); session.flush()
    _audit_enterprise(session, actor_public_id=issuer_public_id, action="certification.issue",
                      object_type="certification", object_id=row.id,
                      organization_id=organization_id)
    return row


def organization_role(session: Any, *, organization_id: str, user_public_id: str) -> str | None:
    row = session.query(DBOrganizationMembership).filter_by(
        organization_id=organization_id, user_public_id=user_public_id, status="active"
    ).first()
    return row.role if row else None


def require_organization_access(
    session: Any, *, organization_id: str, user_public_id: str,
    action: str = "read"
) -> str:
    role = organization_role(
        session, organization_id=organization_id, user_public_id=user_public_id
    )
    allowed = {
        "learner": {"read"},
        "mentor": {"read", "review"},
        "manager": {"read", "review", "assign"},
        "admin": {"read", "review", "assign", "manage", "approve"},
    }
    if role is None or action not in allowed.get(role, set()):
        raise HTTPException(status_code=403, detail="跨组织访问或操作被拒绝")
    return role


def request_exemption(
    session: Any, *, assignment_id: str, competency_standard_id: str,
    requester_public_id: str, evidence_ids: list[str]
) -> DBExemptionRequest:
    assignment = session.query(DBTrainingAssignment).filter_by(id=assignment_id).first()
    standard = session.query(DBCompetencyStandard).filter_by(id=competency_standard_id).first()
    if assignment is None or standard is None:
        raise HTTPException(status_code=404, detail="培训分配或能力标准不存在")
    require_organization_access(
        session, organization_id=assignment.organization_id,
        user_public_id=requester_public_id, action="read"
    )
    if assignment.learner_public_id != requester_public_id:
        raise HTTPException(status_code=403, detail="只能为自己的培训申请免修")
    if standard.risk_level == "high" and standard.exemption_policy == "forbidden":
        raise HTTPException(status_code=403, detail="高风险能力禁止免修")
    rule_result = "requires_human_approval" if standard.risk_level == "high" else "eligible"
    request = DBExemptionRequest(
        organization_id=assignment.organization_id, assignment_id=assignment.id,
        competency_standard_id=standard.id, requester_public_id=requester_public_id,
        evidence_ids=evidence_ids, rule_result=rule_result, status="pending"
    )
    session.add(request); session.flush()
    record_audit(
        session, actor_public_id=requester_public_id, action="exemption.request",
        object_type="exemption_request", object_id=request.id,
        metadata={"organization_id": assignment.organization_id, "rule_result": rule_result},
    )
    return request


def approve_exemption(
    session: Any, *, request: DBExemptionRequest, approver_public_id: str
) -> None:
    require_organization_access(
        session, organization_id=request.organization_id,
        user_public_id=approver_public_id, action="approve"
    )
    request.status = "approved"
    request.approver_public_id = approver_public_id
    record_audit(
        session, actor_public_id=approver_public_id, action="exemption.approve",
        object_type="exemption_request", object_id=request.id,
        metadata={"organization_id": request.organization_id},
    )


def bind_external_identity(
    session: Any, *, organization_id: str, user_public_id: str,
    provider: str, external_subject: str, actor_public_id: str,
) -> DBExternalIdentityMapping:
    require_organization_access(
        session, organization_id=organization_id,
        user_public_id=actor_public_id, action="manage",
    )
    member = session.query(DBOrganizationMembership).filter_by(
        organization_id=organization_id, user_public_id=user_public_id, status="active"
    ).first()
    if member is None:
        raise HTTPException(status_code=400, detail="只能为组织内有效成员绑定外部身份")
    mapping = DBExternalIdentityMapping(
        organization_id=organization_id, user_public_id=user_public_id,
        provider=provider, external_subject=external_subject,
    )
    session.add(mapping)
    session.flush()
    record_audit(
        session, actor_public_id=actor_public_id, action="external_identity.bind",
        object_type="external_identity_mapping", object_id=mapping.id,
        metadata={"organization_id": organization_id, "provider": provider},
    )
    return mapping


def revoke_external_identity(
    session: Any, *, mapping: DBExternalIdentityMapping, actor_public_id: str,
) -> None:
    require_organization_access(
        session, organization_id=mapping.organization_id,
        user_public_id=actor_public_id, action="manage",
    )
    mapping.status = "revoked"
    mapping.revoked_at = utcnow()
    record_audit(
        session, actor_public_id=actor_public_id, action="external_identity.revoke",
        object_type="external_identity_mapping", object_id=mapping.id,
        metadata={"organization_id": mapping.organization_id, "provider": mapping.provider},
    )
