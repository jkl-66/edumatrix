"""Authenticated HTTP boundary for the M2 single-profile golden loop."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from app.auth import get_current_user
from app.database import (
    DBArtifact,
    DBDecisionRecord,
    DBGenerationTask,
    DBLearningEvent,
    DBQualityCheck,
    DBUser,
    run_db_op,
)
from app.m1_repository import M1Repository
from app.m2_artifacts import M2StructuredArtifactGenerator, persist_generated_artifact
from app.m2_baseline import M2_BASELINE_COURSE_ID, seed_m2_baseline
from app.m2_contracts import GenerationContext, M2Capability, StrictModel
from app.m2_feedback import M2LearningFeedback, record_m2_feedback
from app.m2_manifest import M2_MANIFEST_TYPE, build_m2_manifest
from app.m2_quality import run_m2_quality_checks
from app.m2_tasks import (
    M2_GOLDEN_CAPABILITY,
    create_golden_task,
    fail_task_step,
    resume_golden_task,
    retry_task_step,
    start_golden_task,
    start_task_step,
)
from swarm_factory import build_swarm_from_headers


router = APIRouter(prefix="/api/v1/m2", tags=["m2-golden-loop"])


class GoldenTaskCreate(StrictModel):
    context: GenerationContext
    idempotency_key: str = Field(min_length=8, max_length=128)
    model: str = Field(default="", max_length=128)


class ContextRequest(StrictModel):
    context: GenerationContext


class FeedbackRequest(StrictModel):
    context: GenerationContext
    feedback: M2LearningFeedback


def _llm_from_request(request: Request):
    return build_swarm_from_headers(request.headers).factory.generator.llm


def _domain_error(exc: Exception) -> HTTPException:
    code = str(getattr(exc, "code", "m2_operation_failed"))
    if code.endswith("not_found") or code in {"task_not_found", "step_not_found"}:
        status = 404
    elif code.endswith("forbidden") or code in {"task_forbidden", "course_forbidden"}:
        status = 403
    elif "conflict" in code or code in {
        "task_not_startable", "task_not_running", "task_steps_incomplete",
        "task_feedback_missing", "quality_step_not_running", "artifact_set_incomplete",
    }:
        status = 409
    else:
        status = 422
    return HTTPException(status_code=status, detail={"code": code, "message": str(exc)})


def _require_context_owner(context: GenerationContext, user: DBUser) -> None:
    if context.owner_public_id != user.public_id:
        raise HTTPException(status_code=403, detail={"code": "context_forbidden", "message": "context owner mismatch"})


@router.get("/baseline")
async def get_baseline(current_user: DBUser = Depends(get_current_user)):
    def fetch(session):
        fixture = seed_m2_baseline(session)
        if fixture.generation_context.owner_public_id != current_user.public_id:
            raise HTTPException(status_code=403, detail={"code": "baseline_forbidden", "message": "baseline belongs to another owner"})
        return fixture.model_dump(mode="json")

    return await run_db_op(fetch)


@router.post("/golden-tasks", status_code=201)
async def create_task(payload: GoldenTaskCreate, current_user: DBUser = Depends(get_current_user)):
    _require_context_owner(payload.context, current_user)

    def create(session):
        try:
            task, created = create_golden_task(
                session,
                context=payload.context,
                idempotency_key=payload.idempotency_key,
                model=payload.model,
            )
            session.commit()
            return {
                **resume_golden_task(
                    session, task_id=task.id, owner_public_id=current_user.public_id
                ),
                "created": created,
            }
        except HTTPException:
            raise
        except Exception as exc:
            session.rollback()
            raise _domain_error(exc)

    return await run_db_op(create)


@router.get("/golden-tasks/latest")
async def latest_task(current_user: DBUser = Depends(get_current_user)):
    def fetch(session):
        task = (
            session.query(DBGenerationTask)
            .filter_by(
                owner_public_id=current_user.public_id,
                course_id=M2_BASELINE_COURSE_ID,
                capability=M2_GOLDEN_CAPABILITY,
            )
            .order_by(DBGenerationTask.created_at.desc(), DBGenerationTask.id.desc())
            .first()
        )
        if task is None:
            raise HTTPException(status_code=404, detail={"code": "task_not_found", "message": "no M2 task"})
        return resume_golden_task(session, task_id=task.id, owner_public_id=current_user.public_id)

    return await run_db_op(fetch)


@router.get("/golden-tasks/{task_id}")
async def get_task(task_id: str, after_event_sequence: int = 0, current_user: DBUser = Depends(get_current_user)):
    try:
        return await run_db_op(
            lambda session: resume_golden_task(
                session,
                task_id=task_id,
                owner_public_id=current_user.public_id,
                after_event_sequence=max(0, after_event_sequence),
            )
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _domain_error(exc)


@router.post("/golden-tasks/{task_id}/start")
async def start_task(task_id: str, current_user: DBUser = Depends(get_current_user)):
    def start(session):
        try:
            task = start_golden_task(session, task_id=task_id, owner_public_id=current_user.public_id)
            session.commit()
            return resume_golden_task(session, task_id=task.id, owner_public_id=current_user.public_id)
        except Exception as exc:
            session.rollback()
            raise _domain_error(exc)

    return await run_db_op(start)


@router.post("/golden-tasks/{task_id}/generate/{capability}")
async def generate_artifact(
    task_id: str,
    capability: M2Capability,
    payload: ContextRequest,
    request: Request,
    current_user: DBUser = Depends(get_current_user),
):
    _require_context_owner(payload.context, current_user)
    llm = _llm_from_request(request)

    def generate(session):
        sequence = {
            M2Capability.LESSON: 1,
            M2Capability.LAB_GUIDE: 2,
            M2Capability.TIERED_QUIZ: 3,
        }[capability]
        step_started = False
        try:
            start_task_step(
                session,
                task_id=task_id,
                owner_public_id=current_user.public_id,
                sequence=sequence,
            )
            step_started = True
            artifact = asyncio.run(
                M2StructuredArtifactGenerator(llm).generate(
                    session,
                    capability=capability,
                    context=payload.context,
                )
            )
            persisted, _version, created = persist_generated_artifact(
                session,
                task_id=task_id,
                context=payload.context,
                capability=capability,
                artifact=artifact,
            )
            session.commit()
            return {**M1Repository(session).artifact_payload(persisted), "created": created}
        except Exception as exc:
            session.rollback()
            if step_started:
                try:
                    start_task_step(
                        session,
                        task_id=task_id,
                        owner_public_id=current_user.public_id,
                        sequence=sequence,
                    )
                    fail_task_step(
                        session,
                        task_id=task_id,
                        owner_public_id=current_user.public_id,
                        sequence=sequence,
                        error_code=str(getattr(exc, "code", "generation_failed")),
                        error_message=str(exc)[:1000],
                        retryable=True,
                    )
                    session.commit()
                except Exception:
                    session.rollback()
            raise _domain_error(exc)

    return await run_db_op(generate)


@router.post("/golden-tasks/{task_id}/steps/{sequence}/retry")
async def retry_step(task_id: str, sequence: int, current_user: DBUser = Depends(get_current_user)):
    if sequence not in {1, 2, 3, 4}:
        raise HTTPException(status_code=422, detail={"code": "invalid_step_sequence", "message": "sequence must be 1..4"})

    def retry(session):
        try:
            step = retry_task_step(
                session,
                task_id=task_id,
                owner_public_id=current_user.public_id,
                sequence=sequence,
            )
            session.commit()
            return {
                "id": step.id,
                "sequence": step.sequence,
                "attempt": step.attempt,
                "status": step.status,
                "capability": step.tool_name,
            }
        except Exception as exc:
            session.rollback()
            raise _domain_error(exc)

    return await run_db_op(retry)


@router.post("/golden-tasks/{task_id}/quality")
async def check_quality(task_id: str, payload: ContextRequest, current_user: DBUser = Depends(get_current_user)):
    _require_context_owner(payload.context, current_user)

    def check(session):
        try:
            start_task_step(
                session, task_id=task_id, owner_public_id=current_user.public_id, sequence=4
            )
            result = run_m2_quality_checks(session, task_id=task_id, context=payload.context)
            if not result.passed:
                session.commit()
                raise HTTPException(status_code=422, detail={"code": "m2_quality_failed", "result": result.model_dump(mode="json")})
            manifest, manifest_version, _created = build_m2_manifest(
                session, task_id=task_id, context=payload.context
            )
            session.commit()
            return {
                **result.model_dump(mode="json"),
                "manifest_artifact_id": manifest.id,
                "manifest_version_id": manifest_version.id,
            }
        except HTTPException:
            raise
        except Exception as exc:
            session.rollback()
            raise _domain_error(exc)

    return await run_db_op(check)


@router.post("/golden-tasks/{task_id}/feedback")
async def submit_feedback(task_id: str, payload: FeedbackRequest, current_user: DBUser = Depends(get_current_user)):
    _require_context_owner(payload.context, current_user)

    def submit(session):
        try:
            result = record_m2_feedback(
                session,
                task_id=task_id,
                context=payload.context,
                feedback=payload.feedback,
            )
            session.commit()
            return result.model_dump(mode="json")
        except Exception as exc:
            session.rollback()
            raise _domain_error(exc)

    return await run_db_op(submit)


@router.get("/golden-tasks/{task_id}/bundle")
async def get_bundle(task_id: str, current_user: DBUser = Depends(get_current_user)):
    def fetch(session):
        task = session.query(DBGenerationTask).filter_by(id=task_id).first()
        if task is None:
            raise HTTPException(status_code=404, detail={"code": "task_not_found", "message": "task does not exist"})
        if task.owner_public_id != current_user.public_id:
            raise HTTPException(status_code=403, detail={"code": "task_forbidden", "message": "task belongs to another owner"})
        repository = M1Repository(session)
        resources = session.query(DBArtifact).filter(
            DBArtifact.creating_task_id == task.id,
            DBArtifact.artifact_type.in_({"lesson", "lab_guide", "tiered_quiz"}),
        ).order_by(DBArtifact.artifact_type).all()
        manifest = session.query(DBArtifact).filter_by(
            creating_task_id=task.id, artifact_type=M2_MANIFEST_TYPE
        ).first()
        checks = session.query(DBQualityCheck).filter_by(trace_id=task.trace_id).all()
        learning_events = session.query(DBLearningEvent).filter_by(trace_id=task.trace_id).all()
        decisions = session.query(DBDecisionRecord).filter_by(task_id=task.id).all()
        return {
            "task": resume_golden_task(session, task_id=task.id, owner_public_id=current_user.public_id),
            "resources": [repository.artifact_payload(item) for item in resources],
            "manifest": repository.artifact_payload(manifest) if manifest else None,
            "quality_checks": [
                {
                    "id": item.id,
                    "artifact_version_id": item.artifact_version_id,
                    "check_type": item.check_type,
                    "checker_version": item.checker_version,
                    "status": item.status,
                    "score": item.score,
                    "details": item.details or {},
                    "source_ref_ids": item.source_ref_ids or [],
                }
                for item in checks
            ],
            "feedback_events": [
                {"id": item.id, "event_type": item.event_type, "payload": item.payload or {}}
                for item in learning_events
            ],
            "decisions": [
                {
                    "id": item.id,
                    "decision_type": item.decision_type,
                    "candidates": item.candidates or [],
                    "confidence": item.confidence,
                    "execution_impact": item.execution_impact or {},
                    "user_confirmed": item.user_confirmed,
                    "status": item.status,
                }
                for item in decisions
            ],
        }

    return await run_db_op(fetch)
