"""User-facing R2 task timeline projected from existing task governance facts."""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_

from app.database import (
    DBArtifact,
    DBArtifactVersion,
    DBGenerationTask,
    DBModelCall,
    DBQualityCheck,
    DBTaskEvent,
    DBTaskStep,
)


class WorkspaceTimelineError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise WorkspaceTimelineError(code, message)


_STATUS_LABELS = {
    "queued": "等待处理",
    "pending": "等待处理",
    "running": "正在处理",
    "completed": "已完成",
    "passed": "已通过",
    "failed": "需要处理",
    "manual_required": "等待确认",
    "cancelled": "已取消",
}

_STAGE_LABELS = {
    "context_assembler": "准备学习上下文",
    "planning_agent": "规划任务",
    "task_planner": "规划任务",
    "policy_validator": "检查任务要求",
    "capability_agent": "生成学习内容",
    "quality_checker": "校验生成结果",
    "decision_agent": "汇总生成结果",
    "artifact_committer": "保存学习产物",
}

_QUALITY_LABELS = {
    "integrity": "内容完整性检查",
    "type_schema": "结构检查",
    "source_binding": "来源检查",
    "topic": "主题检查",
    "runtime": "可运行性检查",
}

_FAILURE_LABELS = {
    "worker_lease_expired": "后台处理暂时中断，系统已保留进度并安排恢复。",
    "provider_timeout": "模型服务响应超时，可以稍后重试当前步骤。",
    "provider_unavailable": "模型服务暂时不可用，可以稍后重试当前步骤。",
    "schema_invalid": "生成结果结构未通过检查，需要局部返工。",
    "source_ref_missing": "生成结果缺少可核查来源，需要补充来源后再继续。",
    "content_hash_mismatch": "生成内容完整性检查未通过，需要重新校验。",
}


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _status_label(status: str) -> str:
    return _STATUS_LABELS.get(status, "处理中")


def _stage_label(step: DBTaskStep | None) -> str:
    if step is None:
        return "处理任务"
    return _STAGE_LABELS.get(step.agent_role, "处理任务")


def _failure_message(code: str) -> str:
    return _FAILURE_LABELS.get(code, "该步骤未完成，系统已保留上下文和已有结果。")


def _event_item(event: DBTaskEvent, step: DBTaskStep | None) -> dict[str, Any] | None:
    payload = event.payload or {}
    event_type = event.event_type
    stage = _stage_label(step)
    base = {
        "id": event.id,
        "source": "task",
        "sequence": event.sequence,
        "occurred_at": _iso(event.created_at),
        "stage": stage,
        "attempt": step.attempt if step is not None else None,
    }
    if event_type == "generation_task.created":
        return {**base, "kind": "queued", "status": "queued", "label": "任务已创建", "detail": "已进入后台任务队列。"}
    if event_type == "m5.contract.locked":
        return {**base, "kind": "planning", "status": "completed", "label": "任务要求已确认", "detail": "能力类型和当前课程上下文已经锁定。"}
    if event_type == "generation_task.started":
        return {**base, "kind": "running", "status": "running", "label": "任务开始执行", "detail": "系统正在按计划处理当前任务。"}
    if event_type == "task_step.started":
        attempt = payload.get("attempt", step.attempt if step else 1)
        return {**base, "kind": "stage", "status": "running", "label": f"{stage}开始", "detail": f"正在执行第 {attempt} 次尝试。"}
    if event_type == "task_step.completed":
        return {**base, "kind": "stage", "status": "completed", "label": f"{stage}完成", "detail": "该阶段结果已保留，可继续下一步。"}
    if event_type == "task_step.failed":
        code = str(payload.get("error_code") or (step.error_code if step else ""))
        return {**base, "kind": "failure", "status": "failed", "label": f"{stage}未完成", "detail": _failure_message(code), "retryable": bool(payload.get("retryable"))}
    if event_type == "task_step.retry_scheduled":
        return {**base, "kind": "retry", "status": "pending", "label": "已安排重试", "detail": f"将从{stage}继续，不会重做已完成阶段。"}
    if event_type == "task_step.rework_scheduled":
        code = str(payload.get("reason_code") or "")
        return {**base, "kind": "rework", "status": "pending", "label": "已安排局部返工", "detail": _failure_message(code)}
    if event_type == "generation_task.completed":
        return {**base, "kind": "completed", "status": "completed", "label": "任务已完成", "detail": "生成结果已经通过当前流程并保存。"}
    if event_type == "generation_task.failed":
        code = str(payload.get("failure_code") or "")
        return {**base, "kind": "failure", "status": "failed", "label": "任务未完成", "detail": _failure_message(code)}
    if event_type == "generation_task.cancelled":
        return {**base, "kind": "cancelled", "status": "cancelled", "label": "任务已取消", "detail": "已有进度和事件仍然保留。"}
    return None


def build_workspace_task_timeline(
    session: Any,
    *,
    current_user: Any,
    task_id: str,
    course_id: str,
) -> dict[str, Any]:
    task = session.query(DBGenerationTask).filter_by(id=task_id).first()
    if task is None:
        _fail("workspace_timeline_unknown", "生成任务不存在或已经不可用。")
    if task.owner_public_id != current_user.public_id:
        _fail("workspace_timeline_forbidden", "该生成任务属于其他用户。")
    if not course_id or task.course_id != course_id:
        _fail("workspace_timeline_course_conflict", "生成任务与当前课程不一致，请刷新学习空间。")

    steps = session.query(DBTaskStep).filter_by(task_id=task.id).order_by(
        DBTaskStep.sequence, DBTaskStep.attempt,
    ).all()
    steps_by_id = {item.id: item for item in steps}
    attempts_by_sequence: dict[int, list[DBTaskStep]] = {}
    for step in steps:
        attempts_by_sequence.setdefault(step.sequence, []).append(step)
    latest_steps = [values[-1] for _, values in sorted(attempts_by_sequence.items())]

    events = session.query(DBTaskEvent).filter_by(task_id=task.id).order_by(DBTaskEvent.sequence).all()
    timeline = []
    for event in events:
        item = _event_item(event, steps_by_id.get(event.step_id))
        if item is not None:
            timeline.append(item)

    model_calls = session.query(DBModelCall).filter(
        or_(DBModelCall.task_id == task.id, DBModelCall.trace_id == task.trace_id),
    ).order_by(DBModelCall.created_at, DBModelCall.id).all()
    model_calls = [row for row in model_calls if row.owner_public_id in {None, task.owner_public_id}]
    for index, row in enumerate(model_calls, start=1):
        status = row.status if row.status in {"running", "completed", "failed"} else "running"
        detail = "模型正在生成当前阶段结果。"
        if status == "completed":
            detail = f"模型生成完成，用时 {row.duration_ms} ms。" if row.duration_ms else "模型生成完成。"
        elif status == "failed":
            detail = _failure_message(row.error_code)
        timeline.append({
            "id": row.id,
            "source": "model",
            "sequence": 10000 + index,
            "occurred_at": _iso(row.completed_at or row.created_at),
            "kind": "model",
            "status": status,
            "stage": "生成学习内容",
            "label": "AI 生成" if status == "running" else "AI 生成完成" if status == "completed" else "AI 生成未完成",
            "detail": detail,
            "model": row.model or "当前模型",
        })

    artifacts = session.query(DBArtifact).filter_by(creating_task_id=task.id).all()
    artifact_ids = [row.id for row in artifacts]
    version_ids = [
        row.id for row in session.query(DBArtifactVersion).filter(
            DBArtifactVersion.artifact_id.in_(artifact_ids),
        ).all()
    ] if artifact_ids else []
    quality_query = session.query(DBQualityCheck).filter(DBQualityCheck.trace_id == task.trace_id)
    if version_ids:
        quality_query = session.query(DBQualityCheck).filter(or_(
            DBQualityCheck.trace_id == task.trace_id,
            DBQualityCheck.artifact_version_id.in_(version_ids),
        ))
    quality_checks = quality_query.order_by(DBQualityCheck.created_at, DBQualityCheck.id).all()
    for index, row in enumerate(quality_checks, start=1):
        status = row.status if row.status in {"passed", "failed", "manual_required"} else "manual_required"
        label = _QUALITY_LABELS.get(row.check_type, "质量检查")
        detail = "检查通过。" if status == "passed" else "检查未通过，需要局部返工。" if status == "failed" else "需要确认后继续。"
        timeline.append({
            "id": row.id,
            "source": "quality",
            "sequence": 20000 + index,
            "occurred_at": _iso(row.created_at),
            "kind": "quality",
            "status": status,
            "stage": "校验生成结果",
            "label": label,
            "detail": detail,
        })

    timeline.sort(key=lambda item: (item.get("occurred_at") or "", item["sequence"], item["id"]))
    completed_stages = sum(item.status == "completed" for item in latest_steps)
    failed_events = sum(item["status"] == "failed" for item in timeline)
    rework_events = sum(item["kind"] == "rework" for item in timeline)
    current_stage = next((item for item in latest_steps if item.status in {"running", "failed"}), None)
    if current_stage is None:
        current_stage = next((item for item in latest_steps if item.status == "pending"), None)

    return {
        "schema_version": "r2.workspace-task-timeline.v1",
        "task": {
            "task_id": task.id,
            "capability": task.capability,
            "status": task.status,
            "status_label": _status_label(task.status),
            "progress": task.progress,
            "created_at": _iso(task.created_at),
            "updated_at": _iso(task.updated_at),
        },
        "summary": {
            "current_phase": _stage_label(current_stage) if current_stage is not None else _status_label(task.status),
            "stage_count": len(latest_steps),
            "completed_stage_count": completed_stages,
            "model_call_count": len(model_calls),
            "quality_check_count": len(quality_checks),
            "failure_count": failed_events,
            "rework_count": rework_events,
            "refresh_after_seconds": 3 if task.status in {"queued", "running"} else 0,
        },
        "stages": [{
            "sequence": step.sequence,
            "label": _stage_label(step),
            "status": step.status,
            "status_label": _status_label(step.status),
            "attempt": step.attempt,
            "attempt_count": len(attempts_by_sequence[step.sequence]),
            "has_rework": len(attempts_by_sequence[step.sequence]) > 1,
            "retryable": task.status == "running" and step.status == "failed",
            "output_ready": bool(step.output_artifact_version_id),
        } for step in latest_steps],
        "items": timeline,
        "boundaries": {
            "internal_worker_events_hidden": True,
            "raw_prompts_hidden": True,
            "raw_error_messages_hidden": True,
        },
    }
