"""Authenticated M6 teacher and enterprise training API."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from app.auth import get_current_user
from app.database import (
    DBCompetencyStandard,
    DBJobLevel,
    DBSkillEvidence,
    DBUser,
    run_db_op,
)
from app.m1_enterprise import issue_certification, record_skill_evidence, require_organization_access
from app.m2_contracts import StrictModel
from app.m6_enterprise import bootstrap_competition_training_demo, enterprise_workspace
from app.m6_teacher import (
    learner_submit_intervention_evidence,
    publish_teacher_intervention,
    teacher_confirm_intervention,
    teacher_intervention_overview,
)


router = APIRouter(prefix="/api/v1/m6", tags=["m6-enterprise-training"])


class SkillEvidenceCreate(StrictModel):
    organization_id: str
    learner_public_id: str
    competency_standard_id: str
    evidence_type: Literal["artifact", "hidden_test", "expert_observation"]
    source_object_id: str
    result: Literal["passed", "failed"]
    score: float | None = None
    hidden_test_result: dict[str, Any] = Field(default_factory=dict)


class CertificationCreate(StrictModel):
    organization_id: str
    learner_public_id: str
    job_level_id: str
    evidence_ids: list[str]
    retraining_rule: dict[str, Any] = Field(default_factory=dict)


class TeacherInterventionCreate(StrictModel):
    course_id: str
    learner_public_id: str
    idempotency_key: str


class LearnerInterventionEvidenceCreate(StrictModel):
    active_seconds: int = Field(ge=60, le=86400)


class TeacherInterventionConfirm(StrictModel):
    learner_event_id: str


@router.post("/demo/bootstrap")
async def bootstrap_demo(current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(
        lambda session: bootstrap_competition_training_demo(session, actor=current_user)
    )


@router.get("/enterprise/workspace")
async def get_enterprise_workspace(
    organization_id: str | None = None,
    learner_public_id: str | None = None,
    current_user: DBUser = Depends(get_current_user),
):
    return await run_db_op(lambda session: enterprise_workspace(
        session,
        actor_public_id=current_user.public_id,
        organization_id=organization_id,
        learner_public_id=learner_public_id,
    ))


@router.post("/enterprise/evidence", status_code=201)
async def create_enterprise_evidence(
    payload: SkillEvidenceCreate,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        require_organization_access(
            session,
            organization_id=payload.organization_id,
            user_public_id=current_user.public_id,
            action="review",
        )
        standard = session.query(DBCompetencyStandard).filter_by(
            id=payload.competency_standard_id
        ).first()
        if standard is None:
            raise HTTPException(status_code=404, detail="能力标准不存在")
        row = record_skill_evidence(
            session,
            organization_id=payload.organization_id,
            learner_public_id=payload.learner_public_id,
            competency_standard=standard,
            evidence_type=payload.evidence_type,
            source_object_id=payload.source_object_id,
            result=payload.result,
            score=payload.score,
            hidden_test_result=payload.hidden_test_result,
            actor_public_id=current_user.public_id,
        )
        if payload.evidence_type == "expert_observation":
            row.expert_signer_public_id = current_user.public_id
        session.commit()
        return {
            "id": row.id,
            "status": row.result,
            "expert_signed": bool(row.expert_signer_public_id),
            "review_mode": "demo_role" if payload.evidence_type == "expert_observation" else "standard_review",
            "external_expert_verified": False,
        }
    return await run_db_op(operation)


@router.post("/enterprise/certifications", status_code=201)
async def create_certification(
    payload: CertificationCreate,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        level = session.query(DBJobLevel).filter_by(id=payload.job_level_id).first()
        if level is None:
            raise HTTPException(status_code=404, detail="目标岗位标准不存在")
        row = issue_certification(
            session,
            organization_id=payload.organization_id,
            learner_public_id=payload.learner_public_id,
            job_level=level,
            evidence_ids=payload.evidence_ids,
            issuer_public_id=current_user.public_id,
            retraining_rule=payload.retraining_rule,
        )
        session.commit()
        return {"id": row.id, "status": row.status, "standard_snapshot": row.standard_snapshot}
    return await run_db_op(operation)


@router.get("/teacher/interventions")
async def get_teacher_interventions(
    course_id: str,
    current_user: DBUser = Depends(get_current_user),
):
    return await run_db_op(lambda session: teacher_intervention_overview(
        session, actor=current_user, course_id=course_id,
    ))


@router.post("/teacher/interventions", status_code=201)
async def create_teacher_intervention(
    payload: TeacherInterventionCreate,
    current_user: DBUser = Depends(get_current_user),
):
    return await run_db_op(lambda session: publish_teacher_intervention(
        session,
        actor=current_user,
        course_id=payload.course_id,
        learner_public_id=payload.learner_public_id,
        idempotency_key=payload.idempotency_key,
    ))


@router.post("/teacher/interventions/{path_id}/learner-evidence")
async def create_learner_intervention_evidence(
    path_id: str,
    payload: LearnerInterventionEvidenceCreate,
    current_user: DBUser = Depends(get_current_user),
):
    return await run_db_op(lambda session: learner_submit_intervention_evidence(
        session, actor=current_user, path_id=path_id, active_seconds=payload.active_seconds,
    ))


@router.post("/teacher/interventions/{path_id}/confirm")
async def confirm_teacher_intervention(
    path_id: str,
    payload: TeacherInterventionConfirm,
    current_user: DBUser = Depends(get_current_user),
):
    return await run_db_op(lambda session: teacher_confirm_intervention(
        session,
        actor=current_user,
        path_id=path_id,
        learner_event_id=payload.learner_event_id,
    ))
