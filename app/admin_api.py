"""Minimal administrator APIs for accounts, model health, and task recovery."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import Field

from config import CONFIG
from app.audit_log import AUDIT_SCHEMA_VERSION, audit_log_payload, record_backend_audit
from app.auth import get_current_user
from app.database import (
    DBArtifact,
    DBArtifactVersion,
    DBAuditLog,
    DBGenerationTask,
    DBModelCall,
    DBTaskStep,
    DBTaskEvent,
    DBUser,
    DBWorkerLease,
    run_db_op,
)
from app.identity import normalize_role
from app.m1_repository import append_task_event, create_task_step
from app.m2_contracts import StrictModel
from app import resource_bundles


router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

PUBLIC_ROLES = ("student", "teacher", "admin")


class AccountPatch(StrictModel):
    expected_version: str = Field(min_length=64, max_length=64)
    display_name: str = Field(max_length=64)
    role: Literal["student", "teacher", "admin"]
    is_active: bool


def _require_admin(user: DBUser) -> None:
    if normalize_role(user.role) != "admin":
        raise HTTPException(status_code=403, detail={
            "code": "admin_required",
            "message": "仅管理员可执行此操作",
        })


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _account_version(user: DBUser) -> str:
    snapshot = json.dumps({
        "display_name": user.display_name or "",
        "is_active": bool(user.is_active),
        "role": normalize_role(user.role),
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(snapshot.encode("utf-8")).hexdigest()


def _account_payload(user: DBUser) -> dict[str, Any]:
    return {
        "public_id": user.public_id,
        "username": user.username,
        "display_name": user.display_name or "",
        "role": normalize_role(user.role),
        "is_active": bool(user.is_active),
        "created_at": _iso(user.created_at),
        "version": _account_version(user),
    }


def _transaction(operation):
    def wrapped(db):
        try:
            result = operation(db)
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise

    return wrapped


def _classify_model_failure(code: str) -> str | None:
    normalized = str(code or "").strip().lower()
    categories = (
        ("authentication", ("auth", "credential", "api_key", "unauthorized", "forbidden")),
        ("capacity", ("capacity", "overload", "unavailable", "unsupported_model")),
        ("rate_limit", ("rate", "limit", "quota", "429")),
        ("timeout", ("timeout", "timed_out")),
    )
    for category, markers in categories:
        if any(marker in normalized for marker in markers):
            return category
    return None


def _configuration_slots() -> list[dict[str, Any]]:
    provider = str(CONFIG.llm_provider or "").strip().lower()
    local_generation = provider in {"deterministic", "local", "offline"}
    generation_configured = local_generation or bool(
        CONFIG.llm_endpoint and CONFIG.llm_api_key and CONFIG.llm_model
    )

    multimodal_provider = str(CONFIG.multimodal_llm_provider or "").strip().lower()
    multimodal_enabled = bool(multimodal_provider)
    multimodal_configured = multimodal_enabled and bool(
        CONFIG.multimodal_llm_endpoint
        and CONFIG.multimodal_llm_api_key
        and CONFIG.multimodal_llm_model
    )

    embedding_provider = str(CONFIG.embedding_provider or "").strip().lower()
    local_embedding = embedding_provider in {"hash", "local", "offline", "sentence_transformer"}
    embedding_configured = (local_embedding and (embedding_provider != 'sentence_transformer' or bool(CONFIG.embedding_model))) or bool(
        CONFIG.embedding_endpoint and CONFIG.embedding_api_key and CONFIG.embedding_model
    )

    return [
        {
            "slot": "generation",
            "label": "主要生成模型",
            "mode": "local" if local_generation else "external",
            "configured": generation_configured,
            "authentication": "not_required" if local_generation else (
                "configured" if generation_configured else "missing_configuration"
            ),
        },
        {
            "slot": "multimodal",
            "label": "多模态理解模型",
            "mode": "external" if multimodal_enabled else "disabled",
            "configured": multimodal_configured,
            "authentication": "configured" if multimodal_configured else (
                "missing_configuration" if multimodal_enabled else "not_configured"
            ),
        },
        {
            "slot": "embedding",
            "label": "知识检索模型",
            "mode": "local" if local_embedding else "external",
            "configured": embedding_configured,
            "authentication": "not_required" if local_embedding else (
                "configured" if embedding_configured else "missing_configuration"
            ),
        },
    ]


def _model_health(db: Any) -> dict[str, Any]:
    categories: dict[str, dict[str, Any]] = {
        name: {"state": "not_observed", "message": "近期记录中未发现此类异常", "observed_at": None}
        for name in ("authentication", "capacity", "rate_limit", "timeout")
    }
    calls = db.query(DBModelCall).filter(
        DBModelCall.status == "failed",
    ).order_by(DBModelCall.created_at.desc()).limit(100).all()
    for call in calls:
        category = _classify_model_failure(call.error_code)
        if category and categories[category]["state"] == "not_observed":
            categories[category] = {
                "state": "issue_observed",
                "message": {
                    "authentication": "近期出现模型认证失败",
                    "capacity": "近期出现模型容量不足或暂不可用",
                    "rate_limit": "近期出现模型请求限流",
                    "timeout": "近期出现模型响应超时",
                }[category],
                "observed_at": _iso(call.completed_at or call.created_at),
            }

    slots = _configuration_slots()
    if not any(slot["authentication"] == "missing_configuration" for slot in slots):
        return {"configuration": slots, "health": categories}
    if categories["authentication"]["state"] == "not_observed":
        categories["authentication"] = {
            "state": "missing_configuration",
            "message": "至少一个已启用的模型缺少认证配置",
            "observed_at": None,
        }
    return {"configuration": slots, "health": categories}


def _task_failure_category(task: DBGenerationTask) -> str:
    classified = _classify_model_failure(task.failure_code or task.failure_reason)
    return classified or "execution"


def _task_failure_message(task: DBGenerationTask) -> str:
    return {
        "authentication": "模型认证失败，请检查配置后重试",
        "capacity": "模型当前容量不足，可稍后重试或保留已有结果",
        "rate_limit": "请求频率受限，可稍后重试",
        "timeout": "任务等待超时，可从当前任务重试",
        "execution": "任务执行失败，可重试或保留已有结果",
    }[_task_failure_category(task)]


def _has_existing_result(db: Any, task_id: str) -> bool:
    if (
        db.query(DBArtifact.id).filter(DBArtifact.creating_task_id == task_id).first()
        or db.query(DBArtifactVersion.id).filter(DBArtifactVersion.created_task_id == task_id).first()
    ):
        return True
    for event in db.query(DBTaskEvent).filter(DBTaskEvent.task_id == task_id,
            DBTaskEvent.event_type.in_(["path.progress", "path.completed", "diagnostic.work_saved", "diagnostic.completed"])):
        if event.event_type != "path.progress" or (event.payload or {}).get("stage") in {"review", "saved"}:
            return True
    return False


def _task_label(capability: str) -> str:
    value = str(capability or "").lower()
    labels = (
        ("diagnostic", "学习起点诊断"),
        ("path.prepare", "学习路径安排"),
        ("lecture", "个性化讲义生成"),
        ("handout", "个性化讲义生成"),
        ("quiz", "测验题生成"),
        ("exam", "智能组卷"),
        ("mind", "思维导图生成"),
        ("video", "学习视频处理"),
        ("speech", "语音学习处理"),
        ("sandbox", "代码实训处理"),
        ("feynman", "费曼学习任务"),
    )
    for marker, label in labels:
        if marker in value:
            return label
    return "学习资源生成"


def _task_payload(db: Any, task: DBGenerationTask) -> dict[str, Any]:
    owner = db.query(DBUser).filter_by(public_id=task.owner_public_id).first()
    title = _task_label(task.capability)
    if task.capability == resource_bundles.GENERATION_CAPABILITY:
        manifest = resource_bundles._generation_manifest(db, task.id)
        items = manifest.get("items") or []
        if items and items[0].get("title"):
            title = items[0]["title"] + ("等学习资源" if len(items) > 1 else "")
    payload = {
        "id": task.id,
        "title": title,
        "learner_name": (owner.display_name or owner.username) if owner else "原学习账号已不可用",
        "status": task.status,
        "progress_percent": int(round(float(task.progress or 0.0) * 100)),
        "has_existing_result": _has_existing_result(db, task.id),
        "can_retry": task.status == "failed",
        "can_cancel": task.status in {"queued", "running"},
        "created_at": _iso(task.created_at),
        "updated_at": _iso(task.updated_at),
    }
    if task.status == "failed":
        payload.update({
            "failure_category": _task_failure_category(task),
            "failure_message": _task_failure_message(task),
        })
    return payload


def _resource_task_owner(db: Any, task: DBGenerationTask) -> DBUser:
    owner = db.query(DBUser).filter_by(public_id=task.owner_public_id).first()
    if owner is None:
        raise HTTPException(status_code=409, detail={
            "code": "admin_task_owner_unavailable", "message": "原学习账号已不可用，无法继续生成。",
        })
    return owner


def _retry_task(db: Any, *, actor: DBUser, task_id: str) -> DBGenerationTask:
    task = db.get(DBGenerationTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"code": "admin_task_unknown", "message": "任务不存在"})
    if task.status in {"queued", "running"}:
        return task
    if task.status != "failed":
        raise HTTPException(status_code=409, detail={
            "code": "admin_task_not_retryable",
            "message": "当前任务不需要重试，请刷新查看结果。",
        })

    previous_failure = _task_failure_category(task)
    updated = db.query(DBGenerationTask).filter_by(id=task.id, status="failed").update({
        "status": "queued",
        "failure_code": "",
        "failure_reason": "",
        "started_at": None,
        "completed_at": None,
        "updated_at": datetime.now(timezone.utc).replace(tzinfo=None),
    }, synchronize_session="fetch")
    if updated != 1:
        raise HTTPException(status_code=409, detail={
            "code": "admin_task_state_conflict",
            "message": "任务状态已变化，请刷新后重试",
        })

    latest_steps: dict[int, DBTaskStep] = {}
    for step in db.query(DBTaskStep).filter_by(task_id=task.id).order_by(
        DBTaskStep.sequence, DBTaskStep.attempt,
    ).all():
        latest_steps[step.sequence] = step
    is_resource = task.capability == resource_bundles.GENERATION_CAPABILITY
    owner = _resource_task_owner(db, task) if is_resource else None
    for step in latest_steps.values():
        if step.status == "failed":
            if is_resource:
                resource_type = resource_bundles.GENERATION_RESOURCE_TYPES[step.sequence - 1]
                resource_bundles.retry_generation_item(db, owner, task.id, resource_type)
                continue
            create_task_step(
                db,
                task_id=task.id,
                sequence=step.sequence,
                attempt=step.attempt + 1,
                agent_role=step.agent_role,
                tool_name=step.tool_name,
                input_summary=step.input_summary,
                parent_step_id=step.id,
            )

    # Resource generation is request driven; the endpoint schedules the shared
    # executor after committing this queue state. Existing worker tasks keep
    # their original queue/lease mechanism.
    task.status = "queued"
    task.failure_code = ""
    task.failure_reason = ""

    from app.learning_generation_jobs import CAPABILITIES, enable_task
    if task.capability in CAPABILITIES:
        enable_task(task)
        task.automation_state = 'queued'
        task.execution_token = None
        task.lease_expires_at = None
        task.next_attempt_at = datetime.now(timezone.utc).replace(tzinfo=None)

    existing_result = _has_existing_result(db, task.id)
    append_task_event(db, task_id=task.id, event_type="generation_task.admin_retry", payload={
        "previous_failure_category": previous_failure,
        "existing_result_preserved": existing_result,
        "same_task_reused": True,
    })
    record_backend_audit(
        db,
        actor_public_id=actor.public_id,
        action="admin.task.retry",
        object_type="generation_task",
        object_id=task.id,
        before_summary={
            "status": "failed",
            "failureCategory": previous_failure,
            "existingResult": existing_result,
        },
        after_summary={
            "status": "queued",
            "existingResult": existing_result,
            "sameTaskReused": True,
        },
    )
    db.flush()
    return task


def _cancel_task(db: Any, *, actor: DBUser, task_id: str) -> DBGenerationTask:
    task = db.get(DBGenerationTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"code": "admin_task_unknown", "message": "任务不存在"})
    if task.status == "cancelled":
        return task
    if task.status not in {"queued", "running"}:
        raise HTTPException(status_code=409, detail={
            "code": "admin_task_not_cancellable",
            "message": "任务已结束，不能再取消，请刷新查看结果。",
        })

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    expected_status = task.status
    updated = db.query(DBGenerationTask).filter_by(id=task.id, status=expected_status).update({
        "status": "cancelled",
        "completed_at": now,
        "updated_at": now,
    }, synchronize_session="fetch")
    if updated != 1:
        raise HTTPException(status_code=409, detail={
            "code": "admin_task_state_conflict",
            "message": "任务状态已变化，请刷新后重试",
        })
    if task.capability == resource_bundles.GENERATION_CAPABILITY:
        resource_bundles.cancel_generation_job(db, _resource_task_owner(db, task), task.id)
    for lease in db.query(DBWorkerLease).filter_by(task_id=task.id, status="active").all():
        lease.status = "cancelled"
        lease.released_at = now
    append_task_event(db, task_id=task.id, event_type="generation_task.admin_cancelled", payload={
        "previous_status": expected_status,
        "existing_result_preserved": _has_existing_result(db, task.id),
    })
    existing_result = _has_existing_result(db, task.id)
    record_backend_audit(
        db,
        actor_public_id=actor.public_id,
        action="admin.task.cancel",
        object_type="generation_task",
        object_id=task.id,
        before_summary={"status": expected_status, "existingResult": existing_result},
        after_summary={"status": "cancelled", "existingResult": existing_result},
    )
    db.flush()
    return task


@router.get("/accounts")
async def get_accounts(current_user: DBUser = Depends(get_current_user)):
    _require_admin(current_user)

    def operation(db):
        accounts = db.query(DBUser).order_by(DBUser.created_at, DBUser.public_id).all()
        items = [_account_payload(user) for user in accounts if normalize_role(user.role) in PUBLIC_ROLES]
        return {"schema_version": "admin.accounts.v1", "total": len(items), "items": items}

    return await run_db_op(operation)


@router.patch("/accounts/{public_id}")
async def patch_account(
    public_id: str,
    payload: AccountPatch,
    current_user: DBUser = Depends(get_current_user),
):
    _require_admin(current_user)

    def operation(db):
        user = db.query(DBUser).filter_by(public_id=public_id).first()
        if user is None:
            raise HTTPException(status_code=404, detail={"code": "admin_account_unknown", "message": "账号不存在"})
        if _account_version(user) != payload.expected_version:
            raise HTTPException(status_code=409, detail={
                "code": "admin_account_version_conflict",
                "message": "账号已被其他操作更新，请刷新后重试",
            })

        before = {
            "display_name": user.display_name or "",
            "role": normalize_role(user.role),
            "is_active": bool(user.is_active),
        }
        target = payload.model_dump(exclude={"expected_version"})
        changed_fields = sorted(key for key, value in target.items() if before[key] != value)
        if not changed_fields:
            return _account_payload(user)

        updated = db.query(DBUser).filter(
            DBUser.public_id == public_id,
            DBUser.display_name == before["display_name"],
            DBUser.role == before["role"],
            DBUser.is_active == before["is_active"],
        ).update(target, synchronize_session="fetch")
        if updated != 1:
            raise HTTPException(status_code=409, detail={
                "code": "admin_account_version_conflict",
                "message": "账号已被其他操作更新，请刷新后重试",
            })

        record_backend_audit(
            db,
            actor_public_id=current_user.public_id,
            action="admin.account.update",
            object_type="user",
            object_id=public_id,
            before_summary={
                "role": before["role"],
                "active": before["is_active"],
            },
            after_summary={
                "role": target["role"],
                "active": target["is_active"],
                "changedFields": changed_fields,
            },
        )
        db.flush()
        return _account_payload(user)

    return await run_db_op(_transaction(operation))


@router.get("/models")
async def get_models(current_user: DBUser = Depends(get_current_user)):
    _require_admin(current_user)
    return await run_db_op(lambda db: {
        "schema_version": "admin.models.v1",
        **_model_health(db),
    })


@router.get("/system")
async def get_system(current_user: DBUser = Depends(get_current_user)):
    _require_admin(current_user)

    def operation(db):
        tasks = db.query(DBGenerationTask).order_by(
            DBGenerationTask.updated_at.desc(), DBGenerationTask.id,
        ).limit(50).all()
        recent_audits = db.query(DBAuditLog).filter(
            DBAuditLog.metadata_json["schemaVersion"].as_string() == AUDIT_SCHEMA_VERSION,
        ).order_by(
            DBAuditLog.created_at.desc(), DBAuditLog.id.desc(),
        ).limit(20).all()
        return {
            "schema_version": "admin.system.v1",
            "status_counts": {
                task_status: sum(task.status == task_status for task in tasks)
                for task_status in ("queued", "running", "completed", "failed", "cancelled")
            },
            "tasks": [_task_payload(db, task) for task in tasks],
            "recent_audits": [audit_log_payload(row) for row in recent_audits],
        }

    return await run_db_op(operation)


@router.post("/system/tasks/{task_id}/retry")
async def retry_system_task(task_id: str, background_tasks: BackgroundTasks, current_user: DBUser = Depends(get_current_user)):
    _require_admin(current_user)
    def operation(db):
        before = db.get(DBGenerationTask, task_id)
        executor = before.capability if before and before.status == "failed" else None
        task = _retry_task(db, actor=current_user, task_id=task_id)
        return {"schema_version": "admin.system-task.v1", "task": _task_payload(db, task)}, executor

    result, executor = await run_db_op(_transaction(operation))
    if executor == resource_bundles.GENERATION_CAPABILITY:
        background_tasks.add_task(_execute_resource_retry, task_id)
    return result


def _resume_resource_retry(db, task_id: str) -> None:
    task = db.get(DBGenerationTask, task_id)
    if task is None or task.status == "cancelled":
        return
    owner = _resource_task_owner(db, task)
    from app.generation_dispatch import submit_resource_job, confirm_service_restored
    if task.automation_state == "waiting_configuration":
        confirm_service_restored(db)
    elif task.automation_state == "needs_attention":
        task.automation_state = ""
        db.flush()
    submit_resource_job(db, owner, task.id)


async def _execute_resource_retry(task_id: str) -> None:
    await run_db_op(_transaction(lambda db: _resume_resource_retry(db, task_id)))


@router.post("/system/tasks/{task_id}/cancel")
async def cancel_system_task(task_id: str, current_user: DBUser = Depends(get_current_user)):
    _require_admin(current_user)
    return await run_db_op(_transaction(lambda db: {
        "schema_version": "admin.system-task.v1",
        "task": _task_payload(db, _cancel_task(db, actor=current_user, task_id=task_id)),
    }))
