"""Judge-visible enterprise training workspace on the canonical M1 objects."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.auth import get_password_hash
from app.database import (
    DBCertification,
    DBCompetencyStandard,
    DBCourse,
    DBCourseMembership,
    DBJobFamily,
    DBJobLevel,
    DBOrganization,
    DBOrganizationMembership,
    DBSkillEvidence,
    DBSkillStandard,
    DBStudentProfile,
    DBTrainingAssignment,
    DBTrainingCohort,
    DBTrainingProgram,
    DBUser,
)
from app.identity import normalize_role
from app.m1_enterprise import (
    add_organization_member,
    assign_training,
    create_competency_standard,
    create_job_family,
    create_job_level,
    create_organization,
    create_training_cohort,
    create_training_program,
    organization_role,
    record_skill_evidence,
    require_organization_access,
)
from app.m1_evidence import seed_rag_domain_pack
from app.m1_lifecycle import utcnow


DEMO_ORGANIZATION_NAME = "EduMatrix RAG 工程能力中心"
ENTERPRISE_DEMO_TRUTHFULNESS = {
    "data_label": "冻结合成岗位标准 · 比赛演示数据",
    "review_label": "签核由演示角色执行，不代表真实企业或外部专家认证",
    "environment": "local_demo",
    "uses_synthetic_data": True,
    "uses_demo_reviewers": True,
    "external_expert_verified": False,
    "real_enterprise_verified": False,
}


def _workspace_shell(
    organizations: list[dict[str, Any]], selected: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "truthfulness": dict(ENTERPRISE_DEMO_TRUTHFULNESS),
        "organizations": organizations,
        "selected": selected,
    }


def _evidence_passes(item: DBSkillEvidence, required_types: set[str]) -> bool:
    hidden = item.hidden_test_result or {}
    hidden_complete = not hidden.get("total") or hidden.get("passed") == hidden.get("total")
    valid = item.valid_until is None or item.valid_until >= utcnow()
    return (
        item.result == "passed"
        and hidden_complete
        and valid
        and (not required_types or item.evidence_type in required_types)
    )


def bootstrap_competition_training_demo(session: Any, *, actor: DBUser) -> dict[str, str]:
    if normalize_role(actor.role) != "admin":
        raise HTTPException(status_code=403, detail="只有管理员可初始化企业培训样例")
    existing = session.query(DBOrganization).filter_by(name=DEMO_ORGANIZATION_NAME).first()
    if existing is not None:
        role = organization_role(
            session, organization_id=existing.id, user_public_id=actor.public_id
        )
        if role != "admin":
            raise HTTPException(status_code=403, detail="样例组织已由其他管理员管理")
        assignment = (
            session.query(DBTrainingAssignment)
            .filter_by(organization_id=existing.id)
            .order_by(DBTrainingAssignment.assigned_at)
            .first()
        )
        return {
            "organization_id": existing.id,
            "learner_public_id": assignment.learner_public_id if assignment else "",
            "status": "existing",
        }

    seed_rag_domain_pack(session)
    organization = create_organization(session, name=DEMO_ORGANIZATION_NAME, actor=actor)
    learner_username = f"m6_demo_{actor.username}"[:64]
    learner = session.query(DBUser).filter_by(username=learner_username).first()
    if learner is None:
        learner = DBUser(
            username=learner_username,
            hashed_password=get_password_hash("EduMatrix-M6-Demo"),
            role="student",
            display_name="转岗学员 林然",
        )
        session.add(learner)
        session.flush()
    add_organization_member(
        session,
        organization_id=organization.id,
        user_public_id=learner.public_id,
        role="learner",
        actor_public_id=actor.public_id,
    )
    course = session.query(DBCourse).filter_by(id="course-rag-engineering-m0").first()
    if course is not None:
        for user, course_role in ((actor, "teacher"), (learner, "student")):
            membership = session.query(DBCourseMembership).filter_by(
                course_id=course.id, user_public_id=user.public_id
            ).first()
            if membership is None:
                session.add(DBCourseMembership(
                    course_id=course.id, user_public_id=user.public_id,
                    role=course_role, status="active",
                ))
        profile = session.query(DBStudentProfile).filter_by(student_id=learner.username).first()
        if profile is None:
            profile = DBStudentProfile(student_id=learner.username)
            session.add(profile)
        profile.target_course = course.title
        profile.concept_mastery = {
            "来源与许可核验": 0.78,
            "混合检索与重排": 0.31,
            "引用约束生成": 0.42,
        }
        profile.cognitive_load = 0.68
        profile.frustration_index = 0.36
    family = create_job_family(
        session,
        organization_id=organization.id,
        code="RAG-ENG",
        title="企业 RAG 工程师",
        actor_public_id=actor.public_id,
    )
    level = create_job_level(
        session,
        job_family=family,
        level_code="L2",
        version="2026.1",
        title="RAG 应用工程师（独立交付）",
        actor_public_id=actor.public_id,
        responsibilities=["可信知识库建设", "检索质量诊断", "上线安全与恢复"],
    )
    skills = {
        row.level: row
        for row in session.query(DBSkillStandard).filter_by(
            domain_version_id="dv-rag-kp-0-1", code="SKILL-RAG"
        )
    }
    standards = [
        create_competency_standard(
            session,
            job_level=level,
            skill_standard=skills[skill_level],
            requirement_level=requirement,
            version="2026.1",
            actor_public_id=actor.public_id,
            evidence_requirements=[evidence_type],
            risk_level=risk,
            exemption_policy="forbidden" if risk == "high" else "allowed",
            acceptance_rules=["passed", "evidence_valid"],
        )
        for skill_level, requirement, evidence_type, risk in (
            ("foundation", "可在指导下完成", "artifact", "normal"),
            ("independent", "可独立完成", "hidden_test", "normal"),
            ("advanced", "可诊断高风险故障", "expert_observation", "high"),
        )
    ]
    program = create_training_program(
        session,
        organization_id=organization.id,
        target_job_level=level,
        title="RAG 工程师转岗训练营",
        version="2026.1",
        actor_public_id=actor.public_id,
    )
    cohort = create_training_cohort(
        session,
        program=program,
        actor_public_id=actor.public_id,
        course_versions=["course-rag-engineering-m0@0.1.0"],
        resource_version_ids=["lesson", "lab_guide", "tiered_quiz"],
        assessment_versions=["evaluation-m0-0.1"],
    )
    assignment = assign_training(
        session,
        cohort=cohort,
        learner_public_id=learner.public_id,
        assignment_source="transfer_plan",
        source_reference="knowledge-engineer-to-rag-engineer",
        actor_public_id=actor.public_id,
    )
    record_skill_evidence(
        session,
        organization_id=organization.id,
        learner_public_id=learner.public_id,
        competency_standard=standards[0],
        evidence_type="artifact",
        source_object_id="m6-demo-foundation-artifact",
        result="passed",
        score=0.86,
        actor_public_id=actor.public_id,
    )
    session.commit()
    return {
        "organization_id": organization.id,
        "learner_public_id": learner.public_id,
        "assignment_id": assignment.id,
        "status": "created",
    }


def enterprise_workspace(
    session: Any,
    *,
    actor_public_id: str,
    organization_id: str | None = None,
    learner_public_id: str | None = None,
) -> dict[str, Any]:
    memberships = (
        session.query(DBOrganizationMembership)
        .filter_by(user_public_id=actor_public_id, status="active")
        .order_by(DBOrganizationMembership.created_at)
        .all()
    )
    organizations = []
    for membership in memberships:
        organization = session.query(DBOrganization).filter_by(id=membership.organization_id).one()
        organizations.append({
            "id": organization.id,
            "name": organization.name,
            "role": membership.role,
            "status": organization.status,
        })
    if not organizations:
        return _workspace_shell([], None)
    selected_id = organization_id or organizations[0]["id"]
    role = require_organization_access(
        session,
        organization_id=selected_id,
        user_public_id=actor_public_id,
        action="read",
    )
    learner_memberships = (
        session.query(DBOrganizationMembership)
        .filter_by(organization_id=selected_id, role="learner", status="active")
        .all()
    )
    learner_ids = [row.user_public_id for row in learner_memberships]
    if role == "learner":
        selected_learner = actor_public_id
    else:
        selected_learner = learner_public_id or (learner_ids[0] if learner_ids else "")
    if selected_learner not in learner_ids:
        raise HTTPException(status_code=403, detail="目标学员不属于当前组织")
    learner = session.query(DBUser).filter_by(public_id=selected_learner).one()
    assignment = (
        session.query(DBTrainingAssignment)
        .filter_by(organization_id=selected_id, learner_public_id=selected_learner)
        .order_by(DBTrainingAssignment.assigned_at.desc())
        .first()
    )
    if assignment is None:
        return _workspace_shell(organizations, {
            "organization_id": selected_id, "role": role, "learner": {
                "public_id": learner.public_id, "display_name": learner.display_name,
            }, "assignment": None, "competencies": [],
        })
    cohort = session.query(DBTrainingCohort).filter_by(id=assignment.cohort_id).one()
    program = session.query(DBTrainingProgram).filter_by(id=cohort.training_program_id).one()
    level = session.query(DBJobLevel).filter_by(id=program.target_job_level_id).one()
    family = session.query(DBJobFamily).filter_by(id=level.job_family_id).one()
    standards = (
        session.query(DBCompetencyStandard)
        .filter_by(job_level_id=level.id)
        .order_by(DBCompetencyStandard.id)
        .all()
    )
    evidence = session.query(DBSkillEvidence).filter_by(
        organization_id=selected_id, learner_public_id=selected_learner
    ).all()
    evidence_by_standard: dict[str, list[DBSkillEvidence]] = {}
    for item in evidence:
        evidence_by_standard.setdefault(item.competency_standard_id, []).append(item)
    competency_rows = []
    for standard in standards:
        skill = session.query(DBSkillStandard).filter_by(id=standard.skill_standard_id).one()
        required_types = set(standard.evidence_requirements or [])
        items = evidence_by_standard.get(standard.id, [])
        passed = [item for item in items if _evidence_passes(item, required_types)]
        competency_rows.append({
            "standard_id": standard.id,
            "skill_code": skill.code,
            "skill_title": skill.title,
            "skill_level": skill.level,
            "requirement_level": standard.requirement_level,
            "mandatory": standard.mandatory,
            "risk_level": standard.risk_level,
            "exemption_policy": standard.exemption_policy,
            "required_evidence_types": sorted(required_types),
            "status": "satisfied" if passed else "training_required",
            "evidence": [{
                "id": item.id,
                "type": item.evidence_type,
                "result": item.result,
                "score": item.score,
                "hidden_test_result": item.hidden_test_result or {},
                "expert_signed": bool(item.expert_signer_public_id),
            } for item in items],
        })
    certifications = session.query(DBCertification).filter_by(
        organization_id=selected_id, learner_public_id=selected_learner,
        job_level_id=level.id,
    ).order_by(DBCertification.issued_at.desc()).all()
    required = [item for item in competency_rows if item["mandatory"]]
    satisfied = [item for item in required if item["status"] == "satisfied"]
    return _workspace_shell(organizations, {
            "organization_id": selected_id,
            "role": role,
            "learners": [{
                "public_id": row.user_public_id,
                "display_name": session.query(DBUser).filter_by(public_id=row.user_public_id).one().display_name,
            } for row in learner_memberships],
            "learner": {"public_id": learner.public_id, "display_name": learner.display_name},
            "job": {
                "family": family.title,
                "level": level.title,
                "level_code": level.level_code,
                "version": level.version,
                "responsibilities": level.responsibilities or [],
            },
            "assignment": {
                "id": assignment.id,
                "status": assignment.status,
                "source": assignment.assignment_source,
                "program": program.title,
                "program_version": program.version,
                "cohort_id": cohort.id,
                "course_versions": cohort.course_versions or [],
                "resource_version_ids": cohort.resource_version_ids or [],
                "assessment_versions": cohort.assessment_versions or [],
                "standard_snapshot": cohort.standard_snapshot,
            },
            "competencies": competency_rows,
            "summary": {
                "required": len(required),
                "satisfied": len(satisfied),
                "gaps": len(required) - len(satisfied),
                "completion_rate": round(len(satisfied) / len(required), 4) if required else 1.0,
                "certification_ready": len(required) == len(satisfied),
            },
            "certifications": [{
                "id": item.id,
                "status": item.status,
                "issued_at": item.issued_at.isoformat() if item.issued_at else None,
                "retraining_rule": item.retraining_rule or {},
            } for item in certifications],
    })
