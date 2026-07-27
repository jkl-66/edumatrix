"""Authenticated HTTP boundary for the M3 three-profile competition loop."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from app.auth import get_current_user
from app.database import DBArtifact, DBGenerationTask, DBProfileSnapshot, DBTaskEvent, DBUser, run_db_op
from app.m1_repository import M1Repository
from app.m2_contracts import GenerationContext, StrictModel
from app.m3_agents import (
    M3AgentRole,
    M3_COLLABORATION_CAPABILITY,
    complete_m3_agent_run,
    create_m3_collaboration_task,
    start_m3_agent_run,
    start_m3_collaboration_task,
)
from app.m3_baseline import seed_m3_profile_for_owner
from app.m3_debate import AtomicClaimInput, conduct_m3_debate, persist_m3_debate_report
from app.m3_decisions import build_m3_decision_comparison, persist_m3_decision_comparison
from app.m3_interactive import (
    InteractiveAction,
    apply_m3_interactive_action,
    build_m3_interactive_manifest,
    create_m3_interactive_session,
    persist_m3_interactive_manifest,
    record_m3_interactive_evidence,
)
from app.m3_matching import build_m3_matching_report, persist_m3_matching_report
from app.m3_profiles import load_m3_gold_profiles
from app.m3_resources import M3PersonalizedResourceGenerator, persist_m3_resource_bundle
from swarm_factory import build_swarm_from_headers


router = APIRouter(prefix="/api/v1/m3", tags=["m3-competition-loop"])


class M3TaskCreate(StrictModel):
    profile_id: str = Field(min_length=8, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=128)
    model: str = Field(default="", max_length=128)


class M3InteractiveSessionCreate(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=128)


class _LLMDebateReviewer:
    def __init__(self, llm: Any):
        self.llm = llm

    async def review_claim(self, claim: dict[str, Any], *, round_number: int, previous_rounds: list[dict[str, Any]]):
        system_prompt = (
            "Return JSON only. Act as independent Prover, Challenger and conservative Judge. "
            "Use only proposed_source_ref_ids. Verdict must be keep, revise, reject or uncertain."
        )
        payload = {
            "claim": claim,
            "round_number": round_number,
            "previous_rounds": previous_rounds,
            "required_schema": {
                "prover": {"support_status": "supported|partial|unsupported", "evidence_ref_ids": [], "applicable_conditions": [], "rationale": ""},
                "challenger": {"issue_types": [], "evidence_ref_ids": [], "rationale": ""},
                "judge": {"verdict": "keep|revise|reject|uncertain", "rationale": "", "evidence_ref_ids": [], "confidence": 0.0},
            },
        }
        raw = await self.llm.generate(system_prompt, json.dumps(payload, ensure_ascii=False), role="evidence_review")
        return json.loads(raw)


def _llm_from_request(request: Request):
    return build_swarm_from_headers(request.headers).factory.generator.llm


def _debate_reviewer_from_request(request: Request):
    return _LLMDebateReviewer(_llm_from_request(request))


def _domain_error(exc: Exception) -> HTTPException:
    code = str(getattr(exc, "code", "m3_operation_failed"))
    if code.endswith("not_found") or code in {"task_not_found", "interactive_session_not_found"}:
        status = 404
    elif code.endswith("forbidden") or code in {"task_forbidden", "profile_snapshot_forbidden"}:
        status = 403
    elif "conflict" in code or code in {
        "task_not_startable", "task_not_running", "role_dependency_incomplete",
        "role_not_startable", "role_not_running", "task_roles_incomplete",
        "invalid_transition", "recovery_not_verified", "hidden_acceptance_not_passed",
    }:
        status = 409
    else:
        status = 422
    return HTTPException(status_code=status, detail={"code": code, "message": str(exc)})


def _owned_task(session: Any, task_id: str, owner_public_id: str) -> DBGenerationTask:
    task = session.query(DBGenerationTask).filter_by(id=task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail={"code": "task_not_found", "message": "M3 task does not exist"})
    if task.owner_public_id != owner_public_id:
        raise HTTPException(status_code=403, detail={"code": "task_forbidden", "message": "M3 task belongs to another owner"})
    if task.capability != M3_COLLABORATION_CAPABILITY:
        raise HTTPException(status_code=422, detail={"code": "task_capability_mismatch", "message": "task is not an M3 task"})
    return task


def _task_context(session: Any, task_id: str, owner_public_id: str) -> GenerationContext:
    _owned_task(session, task_id, owner_public_id)
    event = (
        session.query(DBTaskEvent)
        .filter_by(task_id=task_id, event_type="m3.context.verified")
        .order_by(DBTaskEvent.sequence)
        .first()
    )
    if event is None:
        raise HTTPException(status_code=422, detail={"code": "verified_context_missing", "message": "M3 task has no verified context"})
    return GenerationContext.model_validate((event.payload or {}).get("context"))


def _redact(value: Any) -> Any:
    forbidden = {
        "answer_key", "explanation", "rationale", "rationale_evidence", "profile_evidence",
        "system_prompt", "user_prompt", "prompt", "api_key", "secret", "expected_values",
    }
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items() if key not in forbidden}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _artifact_payload(session: Any, artifact: DBArtifact) -> dict[str, Any]:
    return _redact(M1Repository(session).artifact_payload(artifact))


def _task_payload(session: Any, task: DBGenerationTask) -> dict[str, Any]:
    payload = M1Repository(session).task_payload(task)
    profile_id = None
    for event in payload["events"]:
        if event["event_type"] == "m3.context.verified":
            context = event.get("payload", {}).get("context", {})
            snapshot = session.query(DBProfileSnapshot).filter_by(id=context.get("profile_snapshot_id")).first()
            profile_id = (snapshot.snapshot or {}).get("source_profile_id") if snapshot is not None else None
            event["payload"] = {
                "context": {
                    "course_id": context.get("course_id"),
                    "profile_snapshot_id": context.get("profile_snapshot_id"),
                    "target_knowledge_point_ids": context.get("target_knowledge_point_ids", []),
                    "source_ref_count": len(context.get("source_ref_ids", [])),
                },
                "content_included": False,
            }
    payload["profile_id"] = profile_id
    return _redact(payload)


def _latest_task(session: Any, owner_public_id: str) -> DBGenerationTask | None:
    return (
        session.query(DBGenerationTask)
        .filter_by(owner_public_id=owner_public_id, capability=M3_COLLABORATION_CAPABILITY)
        .order_by(DBGenerationTask.created_at.desc(), DBGenerationTask.id.desc())
        .first()
    )


@router.get("/profiles")
async def list_profiles(current_user: DBUser = Depends(get_current_user)):
    profiles = load_m3_gold_profiles()
    return {
        "source_schema_version": profiles.source_schema_version,
        "profiles": [
            {
                "profile_id": item.source_profile.profile_id,
                "archetype": item.archetype,
                "label": item.source_profile.label,
                "background": item.source_profile.background,
                "goal": item.source_profile.goal,
                "ability_vector": item.ability_vector.model_dump(mode="json"),
                "adaptation_strategy": _redact(item.adaptation_strategy.model_dump(mode="json")),
                "job_task_id": item.shared_job_task_id,
                "knowledge_point_codes": list(item.target_knowledge_point_codes),
            }
            for item in profiles.profiles
        ],
    }


@router.post("/tasks", status_code=201)
async def create_task(payload: M3TaskCreate, current_user: DBUser = Depends(get_current_user)):
    def create(session):
        try:
            fixture = seed_m3_profile_for_owner(
                session,
                owner_public_id=current_user.public_id,
                source_profile_id=payload.profile_id,
            )
            task, created = create_m3_collaboration_task(
                session,
                context=fixture.generation_context,
                idempotency_key=payload.idempotency_key,
                model=payload.model,
            )
            session.commit()
            return {**_task_payload(session, task), "created": created, "profile_id": payload.profile_id}
        except HTTPException:
            raise
        except Exception as exc:
            session.rollback()
            raise _domain_error(exc)
    return await run_db_op(create)


@router.get("/tasks/latest")
async def latest_task(current_user: DBUser = Depends(get_current_user)):
    def fetch(session):
        task = _latest_task(session, current_user.public_id)
        if task is None:
            raise HTTPException(status_code=404, detail={"code": "task_not_found", "message": "no M3 task"})
        return _task_payload(session, task)
    return await run_db_op(fetch)


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(lambda session: _task_payload(session, _owned_task(session, task_id, current_user.public_id)))


@router.post("/tasks/{task_id}/start")
async def start_task(task_id: str, current_user: DBUser = Depends(get_current_user)):
    def start(session):
        try:
            task = start_m3_collaboration_task(session, task_id=task_id, owner_public_id=current_user.public_id)
            session.commit()
            return _task_payload(session, task)
        except Exception as exc:
            session.rollback()
            raise _domain_error(exc)
    return await run_db_op(start)


@router.post("/tasks/{task_id}/diagnose")
async def diagnose(task_id: str, current_user: DBUser = Depends(get_current_user)):
    def run(session):
        try:
            agent = start_m3_agent_run(session, task_id=task_id, owner_public_id=current_user.public_id, role=M3AgentRole.DIAGNOSIS)
            if agent.status == "running":
                complete_m3_agent_run(session, task_id=task_id, owner_public_id=current_user.public_id, role=M3AgentRole.DIAGNOSIS)
            task = _owned_task(session, task_id, current_user.public_id)
            session.commit()
            return _task_payload(session, task)
        except Exception as exc:
            session.rollback()
            raise _domain_error(exc)
    return await run_db_op(run)


@router.post("/tasks/{task_id}/generate")
async def generate(task_id: str, request: Request, current_user: DBUser = Depends(get_current_user)):
    llm = _llm_from_request(request)
    def run(session):
        try:
            context = _task_context(session, task_id, current_user.public_id)
            agent = start_m3_agent_run(session, task_id=task_id, owner_public_id=current_user.public_id, role=M3AgentRole.DOMAIN_GENERATION)
            bundle = asyncio.run(M3PersonalizedResourceGenerator(llm).generate(session, context=context))
            manifest, manifest_version, resources, created = persist_m3_resource_bundle(session, task_id=task_id, context=context, bundle=bundle)
            if agent.status == "running":
                complete_m3_agent_run(
                    session, task_id=task_id, owner_public_id=current_user.public_id,
                    role=M3AgentRole.DOMAIN_GENERATION, output_artifact_version_id=manifest_version.id,
                )
            session.commit()
            return {"created": created, "manifest": _artifact_payload(session, manifest), "resources": [_artifact_payload(session, item) for item in resources]}
        except Exception as exc:
            session.rollback()
            raise _domain_error(exc)
    return await run_db_op(run)


@router.post("/tasks/{task_id}/review")
async def review(task_id: str, request: Request, current_user: DBUser = Depends(get_current_user)):
    reviewer = _debate_reviewer_from_request(request)
    def run(session):
        try:
            context = _task_context(session, task_id, current_user.public_id)
            resources = session.query(DBArtifact).filter(
                DBArtifact.creating_task_id == task_id,
                DBArtifact.artifact_type.in_(["lesson", "lab_guide", "tiered_quiz"]),
            ).order_by(DBArtifact.artifact_type).all()
            if len(resources) != 3:
                raise ValueError("resource_set_incomplete")
            agent = start_m3_agent_run(session, task_id=task_id, owner_public_id=current_user.public_id, role=M3AgentRole.EVIDENCE_REVIEW)
            claims = [
                AtomicClaimInput(
                    claim_id=f"claim-{item.artifact_type}",
                    artifact_version_id=item.current_version_id,
                    location=f"{item.artifact_type}.primary_claim",
                    atomic_claim=f"{item.artifact_type} is grounded in the verified retrieval-tuning sources",
                    proposed_source_ref_ids=(context.source_ref_ids[index % len(context.source_ref_ids)],),
                )
                for index, item in enumerate(resources)
            ]
            report = asyncio.run(conduct_m3_debate(
                session, task_id=task_id, owner_public_id=current_user.public_id,
                claims=claims, reviewer=reviewer, reviewer_version="configured-structured-reviewer.v1", max_rounds=2,
            ))
            artifact, version, created = persist_m3_debate_report(session, owner_public_id=current_user.public_id, report=report)
            if agent.status == "running":
                complete_m3_agent_run(
                    session, task_id=task_id, owner_public_id=current_user.public_id,
                    role=M3AgentRole.EVIDENCE_REVIEW, output_artifact_version_id=version.id,
                )
            session.commit()
            return {"created": created, "report": report.model_dump(mode="json"), "artifact": _artifact_payload(session, artifact)}
        except Exception as exc:
            session.rollback()
            raise _domain_error(exc)
    return await run_db_op(run)


@router.post("/tasks/{task_id}/matching-report")
async def matching_report(task_id: str, current_user: DBUser = Depends(get_current_user)):
    def run(session):
        try:
            start_m3_agent_run(session, task_id=task_id, owner_public_id=current_user.public_id, role=M3AgentRole.DECISION_ORCHESTRATION)
            report = build_m3_matching_report(session, task_id=task_id, owner_public_id=current_user.public_id)
            artifact, version, created = persist_m3_matching_report(session, report=report)
            session.commit()
            return {"created": created, "version_id": version.id, "report": report.model_dump(mode="json"), "artifact_id": artifact.id}
        except Exception as exc:
            session.rollback()
            raise _domain_error(exc)
    return await run_db_op(run)


@router.post("/tasks/{task_id}/decision")
async def decision(task_id: str, current_user: DBUser = Depends(get_current_user)):
    def run(session):
        try:
            comparison = build_m3_decision_comparison(session, task_id=task_id, owner_public_id=current_user.public_id)
            record, artifact, version, created = persist_m3_decision_comparison(session, comparison=comparison)
            task = _owned_task(session, task_id, current_user.public_id)
            from app.m3_agents import complete_m3_collaboration_task
            complete_m3_collaboration_task(session, task_id=task_id, owner_public_id=current_user.public_id)
            session.commit()
            return {
                "created": created, "decision_record_id": record.id, "artifact_id": artifact.id,
                "comparison": comparison.model_dump(mode="json"), "task": _task_payload(session, task),
            }
        except Exception as exc:
            session.rollback()
            raise _domain_error(exc)
    return await run_db_op(run)


@router.post("/tasks/{task_id}/interactive/manifest")
async def interactive_manifest(task_id: str, current_user: DBUser = Depends(get_current_user)):
    def run(session):
        try:
            manifest = build_m3_interactive_manifest(session, task_id=task_id, owner_public_id=current_user.public_id)
            artifact, version, created = persist_m3_interactive_manifest(
                session, task_id=task_id, owner_public_id=current_user.public_id, manifest=manifest
            )
            session.commit()
            return {"created": created, "version_id": version.id, "manifest": manifest.model_dump(mode="json"), "artifact_id": artifact.id}
        except Exception as exc:
            session.rollback()
            raise _domain_error(exc)
    return await run_db_op(run)


@router.post("/tasks/{task_id}/interactive/sessions", status_code=201)
async def create_interactive_session(task_id: str, payload: M3InteractiveSessionCreate, current_user: DBUser = Depends(get_current_user)):
    def run(session):
        try:
            manifest = build_m3_interactive_manifest(session, task_id=task_id, owner_public_id=current_user.public_id)
            _artifact, manifest_version, _created = persist_m3_interactive_manifest(
                session, task_id=task_id, owner_public_id=current_user.public_id, manifest=manifest
            )
            artifact, version, created = create_m3_interactive_session(
                session, task_id=task_id, owner_public_id=current_user.public_id,
                manifest_artifact_version_id=manifest_version.id,
            )
            state = json.loads(version.content)
            session.commit()
            return {"created": created, "session_artifact_id": artifact.id, "version_id": version.id, "state": state}
        except Exception as exc:
            session.rollback()
            raise _domain_error(exc)
    return await run_db_op(run)


@router.post("/interactive/sessions/{session_id}/actions")
async def interactive_action(session_id: str, payload: InteractiveAction, current_user: DBUser = Depends(get_current_user)):
    def run(session):
        try:
            state, version, event, created = apply_m3_interactive_action(
                session, session_artifact_id=session_id, owner_public_id=current_user.public_id, request=payload,
            )
            session.commit()
            return {"created": created, "version_id": version.id, "learning_event_id": event.id, "state": state.model_dump(mode="json")}
        except Exception as exc:
            session.rollback()
            raise _domain_error(exc)
    return await run_db_op(run)


@router.post("/interactive/sessions/{session_id}/evidence")
async def interactive_evidence(session_id: str, current_user: DBUser = Depends(get_current_user)):
    def run(session):
        try:
            result = record_m3_interactive_evidence(session, session_artifact_id=session_id, owner_public_id=current_user.public_id)
            session.commit()
            return result.model_dump(mode="json")
        except Exception as exc:
            session.rollback()
            raise _domain_error(exc)
    return await run_db_op(run)


@router.get("/tasks/{task_id}/bundle")
async def get_bundle(task_id: str, current_user: DBUser = Depends(get_current_user)):
    def fetch(session):
        task = _owned_task(session, task_id, current_user.public_id)
        artifacts = session.query(DBArtifact).filter_by(creating_task_id=task.id).order_by(DBArtifact.created_at, DBArtifact.id).all()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for artifact in artifacts:
            grouped.setdefault(artifact.artifact_type, []).append(_artifact_payload(session, artifact))
        return {"task": _task_payload(session, task), "artifacts": grouped}
    return await run_db_op(fetch)
