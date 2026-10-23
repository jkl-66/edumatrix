from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field

from config import CONFIG
from app.auth import get_current_user
from app.database import DBUser, run_db_op
from app.m2_contracts import StrictModel
from app.resource_bundles import (
    GENERATION_RESOURCE_TYPES,
    ResourceBundleError,
    cancel_generation_job,
    create_bundle,
    create_generation_job,
    create_version,
    complete_generation_item,
    execute_generation_job_demo,
    execute_generation_job,
    fail_generation_item,
    generation_job_payload,
    get_bundle,
    list_bundles,
    list_candidates,
    list_generation_jobs,
    mark_generation_item_running,
    recover_generation_job,
    restore_version,
    retry_generation_item,
    workspace_context,
)

router = APIRouter(prefix="/api/v1/resource-bundles", tags=["resource-bundles"])


class ResourceInput(StrictModel):
    resource_type: str = Field(min_length=1, max_length=24)
    resource_id: str = Field(min_length=1, max_length=64)
    resource_version_id: str = Field(min_length=1, max_length=64)


class BundleInput(StrictModel):
    title: str = Field(min_length=1, max_length=256)
    learning_objective: str = Field(min_length=1, max_length=2000)
    course_id: str = Field(min_length=1, max_length=128)
    knowledge_point_id: str | None = Field(default=None, max_length=64)
    profile: dict[str, str] = Field(default_factory=dict)
    items: list[ResourceInput] = Field(min_length=1, max_length=8)


class VersionInput(StrictModel):
    profile: dict[str, str] = Field(default_factory=dict)
    items: list[ResourceInput] = Field(min_length=1, max_length=8)
    expected_lock_version: int = Field(ge=1)
    change_summary: str = Field(default="", max_length=256)


class RestoreInput(StrictModel):
    version_id: str = Field(min_length=1, max_length=64)
    expected_lock_version: int = Field(ge=1)


class GenerationItemInput(StrictModel):
    type: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=256)
    source_ref_ids: list[str] = Field(min_length=1)
    completion_rule: str = Field(default="", max_length=512)


class GenerationJobInput(StrictModel):
    course_id: str = Field(min_length=1, max_length=128)
    knowledge_point_id: str | None = Field(default=None, max_length=64)
    profile_snapshot_id: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=128)
    path_id: str | None = Field(default=None, max_length=64)
    task_id: str | None = Field(default=None, max_length=64)
    learning_goal: str = Field(default="", max_length=512)
    conversation_id: str | None = Field(default=None, max_length=64)
    message_id: str | None = Field(default=None, max_length=64)
    resource_intent: str | None = Field(default=None, max_length=64)
    user_instruction: str = Field(default="", max_length=4000)
    context_snapshot_id: str | None = Field(default=None, max_length=128)
    selected_resource_types: list[str] | None = Field(default=None, max_length=len(GENERATION_RESOURCE_TYPES))
    scope: Literal["bundle", "single"] = "bundle"
    items: list[GenerationItemInput] = Field(min_length=1, max_length=len(GENERATION_RESOURCE_TYPES))


class GenerationCompleteInput(StrictModel):
    content: str = Field(min_length=1, max_length=200000)
    content_format: str = Field(default="markdown", max_length=16)


class GenerationFailureInput(StrictModel):
    error_code: str = Field(min_length=1, max_length=64)
    error_message: str = Field(min_length=1, max_length=2000)


def _http(exc: ResourceBundleError) -> HTTPException:
    if exc.code.endswith("unknown"): code = status.HTTP_404_NOT_FOUND
    elif "forbidden" in exc.code: code = status.HTTP_403_FORBIDDEN
    elif "conflict" in exc.code: code = status.HTTP_409_CONFLICT
    else: code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(code, detail={"code": exc.code, "message": str(exc)})


def _op(fn, commit=False):
    def operation(db):
        try:
            result = fn(db)
            if commit: db.commit()
            return result
        except ResourceBundleError as exc:
            db.rollback(); raise _http(exc) from exc
    return operation


@router.get("")
async def bundle_list(current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: list_bundles(db, current_user)))


@router.get("/workspace")
async def workspace(current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: workspace_context(db, current_user)))


@router.get("/candidates")
async def candidate_list(course_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: list_candidates(db, current_user, course_id)))


@router.get("/generation-jobs")
async def generation_job_list(course_id: str | None = None, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: list_generation_jobs(db, current_user, course_id=course_id)))


@router.post("", status_code=201)
async def bundle_create(payload: BundleInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: create_bundle(db, current_user, payload.title, payload.learning_objective,
        payload.course_id, payload.knowledge_point_id, payload.profile, [x.model_dump() for x in payload.items]), True))


@router.get("/{bundle_id}")
async def bundle_detail(bundle_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: get_bundle(db, current_user, bundle_id)))


@router.post("/{bundle_id}/versions")
async def version_create(bundle_id: str, payload: VersionInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: create_version(db, current_user, bundle_id, payload.profile,
        [x.model_dump() for x in payload.items], payload.expected_lock_version, payload.change_summary), True))


@router.post("/{bundle_id}/restore")
async def version_restore(bundle_id: str, payload: RestoreInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: restore_version(db, current_user, bundle_id, payload.version_id, payload.expected_lock_version), True))


@router.post("/generation-jobs", status_code=201)
async def generation_job_create(payload: GenerationJobInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: create_generation_job(
        db,
        current_user,
        course_id=payload.course_id,
        knowledge_point_id=payload.knowledge_point_id,
        profile_snapshot_id=payload.profile_snapshot_id,
        idempotency_key=payload.idempotency_key,
        items=[item.model_dump() for item in payload.items],
        scope=payload.scope,
        path_id=payload.path_id,
        task_id=payload.task_id,
        learning_goal=payload.learning_goal,
        conversation_id=payload.conversation_id,
        message_id=payload.message_id,
        resource_intent=payload.resource_intent,
        user_instruction=payload.user_instruction,
        context_snapshot_id=payload.context_snapshot_id,
        selected_resource_types=payload.selected_resource_types,
    ), True))


@router.get("/generation-jobs/{task_id}")
async def generation_job_detail(task_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: generation_job_payload(db, current_user, task_id)))


@router.post("/generation-jobs/{task_id}/execute-demo")
async def generation_job_execute_demo(task_id: str, current_user: DBUser = Depends(get_current_user)):
    if not CONFIG.demo_mode:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "resource_generation.demo_disabled",
                "message": "当前未启用本地确定性演示执行器，请使用真实资源生成入口。",
            },
        )
    return await run_db_op(_op(lambda db: execute_generation_job_demo(db, current_user, task_id), True))


@router.post("/generation-jobs/{task_id}/execute")
async def generation_job_execute(task_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: execute_generation_job(db, current_user, task_id), True))


@router.post("/generation-jobs/{task_id}/items/{resource_type}/start")
async def generation_job_item_start(task_id: str, resource_type: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: mark_generation_item_running(db, current_user, task_id, resource_type), True))


@router.post("/generation-jobs/{task_id}/items/{resource_type}/complete")
async def generation_job_item_complete(
    task_id: str,
    resource_type: str,
    payload: GenerationCompleteInput,
    current_user: DBUser = Depends(get_current_user),
):
    return await run_db_op(_op(lambda db: complete_generation_item(
        db,
        current_user,
        task_id,
        resource_type,
        content=payload.content,
        content_format=payload.content_format,
    ), True))


@router.post("/generation-jobs/{task_id}/items/{resource_type}/fail")
async def generation_job_item_fail(
    task_id: str,
    resource_type: str,
    payload: GenerationFailureInput,
    current_user: DBUser = Depends(get_current_user),
):
    return await run_db_op(_op(lambda db: fail_generation_item(
        db,
        current_user,
        task_id,
        resource_type,
        error_code=payload.error_code,
        error_message=payload.error_message,
    ), True))


@router.post("/generation-jobs/{task_id}/items/{resource_type}/retry")
async def generation_job_item_retry(task_id: str, resource_type: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: retry_generation_item(db, current_user, task_id, resource_type), True))


@router.post("/generation-jobs/{task_id}/recover")
async def generation_job_recover(task_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: recover_generation_job(db, current_user, task_id), True))


@router.post("/generation-jobs/{task_id}/cancel")
async def generation_job_cancel(task_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: cancel_generation_job(db, current_user, task_id), True))
