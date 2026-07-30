"""Authenticated M5 capability discovery and route preflight API."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user
from app.authorization import ObjectAccess, require_object_access
from app.database import (
    DBArtifact,
    DBLearningEvent,
    DBLearningPath,
    DBPathNode,
    DBPlanDraft,
    DBPlanVersion,
    DBTutorContextSession,
    DBUser,
    run_db_op,
)
from app.m1_repository import M1Repository
from app.m2_contracts import StrictModel
from app.m5_capabilities import (
    M5CapabilityError,
    RoutingRequest,
    RuntimeAvailability,
    capability_statuses,
    route_capability,
)
from app.m5_resources import (
    ResourceArchiveRequest,
    compare_resource_versions,
    export_resource_version,
    resource_detail,
    search_resources,
    set_resource_archived,
)
from app.m5_learning import (
    LearningEventInput,
    M5LearningError,
    PlanSpec,
    confirm_plan,
    create_plan_draft,
    plan_version_diff,
    process_path_event,
    propose_plan_revision,
    record_learning_event,
    today_work_items,
    transition_path,
)
from app.m5_assessment import (
    AssessmentEvidenceInput,
    record_assessment_evidence,
)
from app.m5_tasks import (
    M5TaskError,
    create_capability_task,
    resume_capability_task,
    retry_capability_step,
    start_capability_task,
)
from app.m5_workspace import (
    M5WorkspaceError,
    TutorContextSpec,
    TutorPromptPreflight,
    archive_tutor_context,
    create_tutor_context,
    tutor_context_payload,
    tutor_prompt_envelope,
)
from config import CONFIG


router = APIRouter(prefix="/api/v1/m5", tags=["m5-capabilities"])
ROOT = Path(__file__).resolve().parents[1]


class CapabilityTaskCreate(StrictModel):
    routing: RoutingRequest
    model: str = ""


class PlanDraftCreate(StrictModel):
    course_id: str | None = None
    title: str
    idempotency_key: str
    profile_snapshot_id: str | None = None
    spec: PlanSpec


class PlanRevisionCreate(StrictModel):
    expected_lock_version: int
    profile_snapshot_id: str | None = None
    spec: PlanSpec


class PlanConfirmRequest(StrictModel):
    expected_lock_version: int


class PathTransitionRequest(StrictModel):
    expected_lock_version: int
    target_status: Literal["active", "paused", "archived"]


class TutorContextArchiveRequest(StrictModel):
    expected_lock_version: int


def _learning_error(exc: M5LearningError) -> HTTPException:
    if exc.code.endswith("unknown"):
        status = 404
    elif "forbidden" in exc.code:
        status = 403
    elif "conflict" in exc.code or "transition" in exc.code or "not_" in exc.code:
        status = 409
    else:
        status = 422
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


def _workspace_error(exc: M5WorkspaceError) -> HTTPException:
    if exc.code.endswith(("unknown", "invalid")):
        status = 404
    elif "forbidden" in exc.code:
        status = 403
    elif "conflict" in exc.code or "archived" in exc.code:
        status = 409
    else:
        status = 422
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


def _owned_plan(session, plan_id: str, owner_public_id: str) -> DBPlanDraft:
    plan = session.query(DBPlanDraft).filter_by(id=plan_id).first()
    if plan is None:
        raise HTTPException(status_code=404, detail={"code": "plan_unknown", "message": "plan does not exist"})
    if plan.owner_public_id != owner_public_id:
        raise HTTPException(status_code=403, detail={"code": "plan_forbidden", "message": "plan belongs to another owner"})
    return plan


def _owned_path(session, path_id: str, owner_public_id: str) -> DBLearningPath:
    path = session.query(DBLearningPath).filter_by(id=path_id).first()
    if path is None:
        raise HTTPException(status_code=404, detail={"code": "path_unknown", "message": "path does not exist"})
    if path.owner_public_id != owner_public_id:
        raise HTTPException(status_code=403, detail={"code": "path_forbidden", "message": "path belongs to another owner"})
    return path


def _plan_payload(session, plan: DBPlanDraft) -> dict[str, Any]:
    versions = session.query(DBPlanVersion).filter_by(plan_draft_id=plan.id).order_by(
        DBPlanVersion.version_number,
    ).all()
    return {
        "id": plan.id,
        "course_id": plan.course_id,
        "title": plan.title,
        "status": plan.status,
        "lock_version": plan.lock_version,
        "current_version_id": plan.current_version_id,
        "confirmed_version_id": plan.confirmed_version_id,
        "confirmed_at": plan.confirmed_at.isoformat() if plan.confirmed_at else None,
        "versions": [{
            "id": item.id,
            "number": item.version_number,
            "content_hash": item.content_hash,
            "content": item.content,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        } for item in versions],
    }


def _path_payload(session, path: DBLearningPath) -> dict[str, Any]:
    nodes = session.query(DBPathNode).filter_by(learning_path_id=path.id).order_by(DBPathNode.sequence).all()
    return {
        "id": path.id,
        "course_id": path.course_id,
        "source_plan_version_id": path.source_plan_version_id,
        "supersedes_path_id": path.supersedes_path_id,
        "status": path.status,
        "lock_version": path.lock_version,
        "nodes": [{
            "id": item.id,
            "node_key": item.node_key,
            "sequence": item.sequence,
            "node_type": item.node_type,
            "target_object_id": item.target_object_id,
            "title": item.title,
            "status": item.status,
            "prerequisites": item.prerequisites or [],
            "is_extension": item.is_extension,
            "resource_status": item.resource_status,
            "estimate_minutes": [item.estimate_min_minutes, item.estimate_max_minutes],
            "actual_minutes": item.actual_minutes,
        } for item in nodes],
    }


def _event_payload(event: DBLearningEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "course_id": event.course_id,
        "object_type": event.object_type,
        "object_id": event.object_id,
        "source": event.source,
        "trace_id": event.trace_id,
        "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
    }


def runtime_availability() -> RuntimeAvailability:
    provider = CONFIG.llm_provider.strip().lower()
    text_model = bool(CONFIG.llm_endpoint and CONFIG.llm_api_key and CONFIG.llm_model) and provider not in {"mock", "deterministic"}
    vision_model = bool(
        CONFIG.multimodal_llm_endpoint and CONFIG.multimodal_llm_api_key and CONFIG.multimodal_llm_model
    )
    retrieval = any((ROOT / "data" / "faiss_indexes").glob("*.faiss"))
    sandbox = CONFIG.sandbox_mode if CONFIG.sandbox_mode in {"disabled", "trusted_local", "docker", "external_lab"} else "disabled"
    return RuntimeAvailability(
        text_model=text_model,
        vision_model=vision_model,
        retrieval=retrieval,
        media_pipeline=(ROOT / "data" / "animations").is_dir(),
        sandbox_mode=sandbox,
    )


@router.get("/capabilities")
async def list_capabilities(current_user: DBUser = Depends(get_current_user)):
    runtime = runtime_availability()
    return {
        "schema_version": "m5.capability-status.v1",
        "runtime": runtime.model_dump(mode="json"),
        "capabilities": [item.model_dump(mode="json") for item in capability_statuses(runtime)],
        "user_configurable_secrets": False,
    }


@router.post("/route")
async def preflight_route(payload: RoutingRequest, current_user: DBUser = Depends(get_current_user)):
    try:
        decision = route_capability(payload, runtime_availability())
        return decision.model_dump(mode="json")
    except M5CapabilityError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc


def _owned_resource(session, artifact_id: str, current_user: DBUser, action: str = "read") -> DBArtifact:
    artifact = session.query(DBArtifact).filter_by(id=artifact_id).first()
    if artifact is None:
        raise HTTPException(status_code=404, detail={"code": "resource_unknown", "message": "resource does not exist"})
    require_object_access(
        current_user,
        ObjectAccess("artifact", artifact.id, owner_public_id=artifact.owner_public_id, course_id=artifact.course_id),
        action=action,
    )
    return artifact


@router.get("/resources")
async def list_resources(
    q: str = "", artifact_type: str | None = None, course_id: str | None = None,
    status: str | None = None, include_archived: bool = False,
    cursor: str | None = None, limit: int = 25,
    current_user: DBUser = Depends(get_current_user),
):
    return await run_db_op(lambda session: search_resources(
        session, owner_public_id=current_user.public_id, query=q,
        artifact_type=artifact_type, course_id=course_id, status=status,
        include_archived=include_archived, cursor=cursor, limit=limit,
    ))


@router.get("/resources/{artifact_id}")
async def get_resource(artifact_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(lambda session: resource_detail(
        session, _owned_resource(session, artifact_id, current_user),
    ))


@router.get("/resources/{artifact_id}/compare")
async def compare_resource(
    artifact_id: str, left_version: int, right_version: int,
    current_user: DBUser = Depends(get_current_user),
):
    try:
        return await run_db_op(lambda session: compare_resource_versions(
            session, artifact=_owned_resource(session, artifact_id, current_user),
            left_version=left_version, right_version=right_version,
        ))
    except M5CapabilityError as exc:
        raise HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)}) from exc


@router.get("/resources/{artifact_id}/export")
async def export_resource(
    artifact_id: str, version_number: int | None = None,
    current_user: DBUser = Depends(get_current_user),
):
    try:
        return await run_db_op(lambda session: export_resource_version(
            session, artifact=_owned_resource(session, artifact_id, current_user),
            version_number=version_number,
        ))
    except M5CapabilityError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc


@router.post("/resources/{artifact_id}/archive")
async def archive_resource(
    artifact_id: str, payload: ResourceArchiveRequest,
    current_user: DBUser = Depends(get_current_user),
):
    try:
        return await run_db_op(lambda session: set_resource_archived(
            session,
            artifact=_owned_resource(session, artifact_id, current_user, action="update"),
            actor_public_id=current_user.public_id,
            archived=payload.archived,
            expected_lock_version=payload.expected_lock_version,
        ))
    except M5CapabilityError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc


@router.post("/plans", status_code=201)
async def create_learning_plan(payload: PlanDraftCreate, current_user: DBUser = Depends(get_current_user)):
    def operation(session):
        plan, version, created = create_plan_draft(
            session,
            owner_public_id=current_user.public_id,
            course_id=payload.course_id,
            title=payload.title,
            idempotency_key=payload.idempotency_key,
            profile_snapshot_id=payload.profile_snapshot_id,
            spec=payload.spec,
        )
        session.commit()
        return {**_plan_payload(session, plan), "created": created, "version_id": version.id}

    try:
        return await run_db_op(operation)
    except M5LearningError as exc:
        raise _learning_error(exc) from exc


@router.get("/plans/{plan_id}")
async def get_learning_plan(plan_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(lambda session: _plan_payload(
        session, _owned_plan(session, plan_id, current_user.public_id),
    ))


@router.post("/plans/{plan_id}/revisions", status_code=201)
async def revise_learning_plan(
    plan_id: str, payload: PlanRevisionCreate,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        plan = _owned_plan(session, plan_id, current_user.public_id)
        version, diff = propose_plan_revision(
            session,
            plan=plan,
            owner_public_id=current_user.public_id,
            expected_lock_version=payload.expected_lock_version,
            spec=payload.spec,
            profile_snapshot_id=payload.profile_snapshot_id,
        )
        session.commit()
        return {"plan": _plan_payload(session, plan), "version_id": version.id, "diff": diff}

    try:
        return await run_db_op(operation)
    except M5LearningError as exc:
        raise _learning_error(exc) from exc


@router.get("/plans/{plan_id}/diff")
async def get_learning_plan_diff(
    plan_id: str, from_version_id: str, to_version_id: str,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        plan = _owned_plan(session, plan_id, current_user.public_id)
        left = session.query(DBPlanVersion).filter_by(id=from_version_id, plan_draft_id=plan.id).first()
        right = session.query(DBPlanVersion).filter_by(id=to_version_id, plan_draft_id=plan.id).first()
        if left is None or right is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "plan_version_unknown", "message": "plan version does not exist"},
            )
        return plan_version_diff(left, right)

    return await run_db_op(operation)


@router.post("/plans/{plan_id}/confirm", status_code=201)
async def confirm_learning_plan(
    plan_id: str, payload: PlanConfirmRequest,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        plan = _owned_plan(session, plan_id, current_user.public_id)
        path = confirm_plan(
            session,
            plan=plan,
            owner_public_id=current_user.public_id,
            expected_lock_version=payload.expected_lock_version,
        )
        session.commit()
        return {"plan": _plan_payload(session, plan), "path": _path_payload(session, path)}

    try:
        return await run_db_op(operation)
    except M5LearningError as exc:
        raise _learning_error(exc) from exc


@router.get("/paths/{path_id}")
async def get_learning_path(path_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(lambda session: _path_payload(
        session, _owned_path(session, path_id, current_user.public_id),
    ))


@router.post("/paths/{path_id}/transition")
async def transition_learning_path(
    path_id: str, payload: PathTransitionRequest,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        path = transition_path(
            session,
            path=_owned_path(session, path_id, current_user.public_id),
            owner_public_id=current_user.public_id,
            target_status=payload.target_status,
            expected_lock_version=payload.expected_lock_version,
        )
        session.commit()
        return _path_payload(session, path)

    try:
        return await run_db_op(operation)
    except M5LearningError as exc:
        raise _learning_error(exc) from exc


@router.post("/learning-events", status_code=201)
async def create_learning_event(
    payload: LearningEventInput, current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        event, created = record_learning_event(
            session, owner_public_id=current_user.public_id, event=payload,
        )
        consumption = process_path_event(session, event=event)
        session.commit()
        return {
            **_event_payload(event),
            "created": created,
            "consumption": {
                "id": consumption.id,
                "status": consumption.status,
                "processor_version": consumption.processor_version,
                "attempt": consumption.attempt,
                "result": consumption.result,
            },
        }

    try:
        return await run_db_op(operation)
    except M5LearningError as exc:
        raise _learning_error(exc) from exc


@router.post("/learning-events/{event_id}/process")
async def replay_learning_event(event_id: str, current_user: DBUser = Depends(get_current_user)):
    def operation(session):
        event = session.query(DBLearningEvent).filter_by(id=event_id).first()
        if event is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "learning_event_unknown", "message": "learning event does not exist"},
            )
        if event.owner_public_id != current_user.public_id:
            raise HTTPException(
                status_code=403,
                detail={"code": "learning_event_forbidden", "message": "learning event belongs to another owner"},
            )
        consumption = process_path_event(session, event=event)
        session.commit()
        return {
            "event_id": event.id,
            "consumption_id": consumption.id,
            "status": consumption.status,
            "attempt": consumption.attempt,
            "result": consumption.result,
        }

    return await run_db_op(operation)


@router.post("/assessment-evidence", status_code=201)
async def create_assessment_evidence(
    payload: AssessmentEvidenceInput, current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        result = record_assessment_evidence(
            session, owner_public_id=current_user.public_id, evidence=payload,
        )
        session.commit()
        return result

    try:
        return await run_db_op(operation)
    except M5LearningError as exc:
        raise _learning_error(exc) from exc


@router.get("/today")
async def get_today_work(current_user: DBUser = Depends(get_current_user)):
    return {
        "schema_version": "m5.today-work.v1",
        "items": await run_db_op(lambda session: today_work_items(
            session, owner_public_id=current_user.public_id,
        )),
    }


@router.post("/tutor-contexts", status_code=201)
async def create_current_tutor_context(
    payload: TutorContextSpec, current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        row, created = create_tutor_context(session, current_user=current_user, spec=payload)
        session.commit()
        return {**tutor_context_payload(row), "created": created}

    try:
        return await run_db_op(operation)
    except M5WorkspaceError as exc:
        raise _workspace_error(exc) from exc


@router.get("/tutor-contexts")
async def list_current_tutor_contexts(
    include_archived: bool = False, limit: int = 20,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        query = session.query(DBTutorContextSession).filter_by(owner_public_id=current_user.public_id)
        if not include_archived:
            query = query.filter_by(status="active")
        rows = query.order_by(DBTutorContextSession.last_used_at.desc()).limit(max(1, min(limit, 100))).all()
        return {"schema_version": "m5.tutor-context-list.v1", "items": [tutor_context_payload(row) for row in rows]}

    return await run_db_op(operation)


@router.get("/tutor-contexts/{context_id}")
async def get_current_tutor_context(
    context_id: str, current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        row = session.query(DBTutorContextSession).filter_by(id=context_id).first()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "tutor_context_unknown", "message": "tutor context does not exist"},
            )
        if row.owner_public_id != current_user.public_id:
            raise HTTPException(
                status_code=403,
                detail={"code": "tutor_context_forbidden", "message": "tutor context belongs to another owner"},
            )
        return tutor_context_payload(row)

    return await run_db_op(operation)


@router.post("/tutor-contexts/{context_id}/archive")
async def archive_current_tutor_context(
    context_id: str, payload: TutorContextArchiveRequest,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        row = session.query(DBTutorContextSession).filter_by(id=context_id).first()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "tutor_context_unknown", "message": "tutor context does not exist"},
            )
        row = archive_tutor_context(
            session, row=row, owner_public_id=current_user.public_id,
            expected_lock_version=payload.expected_lock_version,
        )
        session.commit()
        return tutor_context_payload(row)

    try:
        return await run_db_op(operation)
    except M5WorkspaceError as exc:
        raise _workspace_error(exc) from exc


@router.post("/tutor-contexts/{context_id}/preflight")
async def preflight_current_tutor_request(
    context_id: str, payload: TutorPromptPreflight,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        row = session.query(DBTutorContextSession).filter_by(id=context_id).first()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "tutor_context_unknown", "message": "tutor context does not exist"},
            )
        envelope = tutor_prompt_envelope(
            session, row=row, owner_public_id=current_user.public_id, request=payload,
        )
        session.commit()
        runtime = runtime_availability()
        blockers = []
        if not runtime.text_model:
            blockers.append("text_model_unavailable")
        if row.context_mode != "current_resource" and not runtime.retrieval:
            blockers.append("retrieval_unavailable")
        return {
            **envelope,
            "ready": not blockers,
            "blockers": blockers,
            "runtime": runtime.model_dump(mode="json"),
        }

    try:
        return await run_db_op(operation)
    except M5WorkspaceError as exc:
        raise _workspace_error(exc) from exc


def _task_error(exc: M5TaskError) -> HTTPException:
    if exc.code.endswith("unknown"):
        status = 404
    elif "forbidden" in exc.code:
        status = 403
    elif any(token in exc.code for token in ("conflict", "not_", "incomplete", "required")):
        status = 409
    else:
        status = 422
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


@router.post("/tasks", status_code=201)
async def create_m5_task(payload: CapabilityTaskCreate, current_user: DBUser = Depends(get_current_user)):
    def operation(session):
        task, created = create_capability_task(
            session,
            owner_public_id=current_user.public_id,
            request=payload.routing,
            runtime=runtime_availability(),
            model=payload.model,
        )
        session.commit()
        return {**M1Repository(session).task_payload(task), "created": created}

    try:
        return await run_db_op(operation)
    except M5TaskError as exc:
        raise _task_error(exc) from exc


@router.post("/tasks/{task_id}/start")
async def start_m5_task(task_id: str, current_user: DBUser = Depends(get_current_user)):
    def operation(session):
        task = start_capability_task(session, task_id=task_id, owner_public_id=current_user.public_id)
        session.commit()
        return M1Repository(session).task_payload(task)

    try:
        return await run_db_op(operation)
    except M5TaskError as exc:
        raise _task_error(exc) from exc


@router.get("/tasks/{task_id}")
async def get_m5_task(
    task_id: str, after_event_sequence: int = 0,
    current_user: DBUser = Depends(get_current_user),
):
    try:
        return await run_db_op(lambda session: resume_capability_task(
            session, task_id=task_id, owner_public_id=current_user.public_id,
            after_event_sequence=max(0, after_event_sequence),
        ))
    except M5TaskError as exc:
        raise _task_error(exc) from exc


@router.post("/tasks/{task_id}/steps/{sequence}/retry")
async def retry_m5_task_step(
    task_id: str, sequence: int, current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        step = retry_capability_step(
            session, task_id=task_id, owner_public_id=current_user.public_id, sequence=sequence,
        )
        session.commit()
        return {"step_id": step.id, "sequence": step.sequence, "attempt": step.attempt, "status": step.status}

    try:
        return await run_db_op(operation)
    except M5TaskError as exc:
        raise _task_error(exc) from exc
