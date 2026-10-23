"""Restricted deterministic executor for workspace generation tasks."""

from __future__ import annotations

import json
from typing import Any

from app.database import DBArtifact, DBGenerationTask, DBQualityCheck, DBTaskStep
from app.m1_repository import create_artifact_with_version
from app.m5_tasks import (
    complete_capability_step,
    complete_capability_task,
    fail_capability_step,
    retry_capability_step,
    start_capability_step,
    start_capability_task,
)


class WorkspaceLocalExecutionError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise WorkspaceLocalExecutionError(code, message)


def _owned_task(session: Any, *, task_id: str, owner_public_id: str) -> DBGenerationTask:
    task = session.query(DBGenerationTask).filter_by(id=task_id).first()
    if task is None:
        _fail("workspace_local_task_unknown", "生成任务不存在或已经不可用。")
    if task.owner_public_id != owner_public_id:
        _fail("workspace_local_task_forbidden", "该生成任务属于其他用户。")
    if task.capability != "m5.capability.experiment":
        _fail("workspace_local_capability_unsupported", "本地演示执行器只处理交互实验任务。")
    if task.model != "deterministic":
        _fail("workspace_local_model_required", "当前任务不是本地确定性演示任务。")
    return task


def _artifact_payload(task: DBGenerationTask) -> str:
    return json.dumps({
        "schema_version": "r2.workspace-experiment.v1",
        "title": "混合检索 Recall@K 调优实验",
        "runtime_mode": "safe_deterministic_simulation",
        "parameters": {"keyword_weight": 0.45, "vector_weight": 0.55, "top_k": 5},
        "metrics": {"recall_at_k": 0.82, "ranking_score": 0.78, "isolation_leaks": 0},
        "source_course_id": task.course_id,
        "truth_boundary": "本结果由离线确定性演示执行器生成，不代表外部模型或真实实验室运行。",
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _quality_check(
    session: Any, *, version_id: str, trace_id: str, check_type: str,
    status: str, details: dict[str, Any] | None = None,
) -> None:
    session.add(DBQualityCheck(
        artifact_version_id=version_id,
        trace_id=trace_id,
        check_type=check_type,
        checker_version="r2.workspace-local.v1",
        status=status,
        score=1.0 if status == "passed" else 0.0,
        details=details or {},
        source_ref_ids=[],
    ))


def execute_deterministic_workspace_task(
    session: Any, *, task_id: str, owner_public_id: str,
) -> dict[str, Any]:
    task = _owned_task(session, task_id=task_id, owner_public_id=owner_public_id)
    existing = session.query(DBArtifact).filter_by(creating_task_id=task.id).first()
    if task.status == "completed" and existing is not None:
        return {"task_id": task.id, "artifact_id": existing.id, "created": False}
    if task.status != "queued":
        _fail("workspace_local_task_not_queued", "只有等待处理的本地演示任务可以执行。")

    start_capability_task(session, task_id=task.id, owner_public_id=owner_public_id)
    latest = {
        row.sequence: row for row in session.query(DBTaskStep).filter_by(task_id=task.id)
        .order_by(DBTaskStep.sequence, DBTaskStep.attempt).all()
    }
    artifact = None
    version = None
    for sequence in sorted(latest):
        step = latest[sequence]
        start_capability_step(
            session, task_id=task.id, owner_public_id=owner_public_id, sequence=sequence,
        )
        if step.agent_role == "capability_agent":
            artifact, version = create_artifact_with_version(
                session,
                owner_public_id=owner_public_id,
                artifact_type="interactive_lab",
                title="混合检索 Recall@K 调优实验",
                content=_artifact_payload(task),
                content_format="json",
                course_id=task.course_id,
                creating_task_id=task.id,
                metadata={
                    "runtime_mode": "safe_deterministic_simulation",
                    "truth_boundary": "offline_deterministic_demo",
                },
            )
            complete_capability_step(
                session, task_id=task.id, owner_public_id=owner_public_id,
                sequence=sequence, output_artifact_version_id=version.id,
            )
            continue
        if step.agent_role == "quality_checker":
            fail_capability_step(
                session, task_id=task.id, owner_public_id=owner_public_id,
                sequence=sequence, error_code="source_ref_missing", retryable=True,
            )
            _quality_check(
                session, version_id=version.id, trace_id=task.trace_id,
                check_type="source_binding", status="failed",
                details={"public_summary": "首稿缺少课程来源绑定，已触发局部返工。"},
            )
            retry = retry_capability_step(
                session, task_id=task.id, owner_public_id=owner_public_id, sequence=sequence,
            )
            start_capability_step(
                session, task_id=task.id, owner_public_id=owner_public_id, sequence=retry.sequence,
            )
            complete_capability_step(
                session, task_id=task.id, owner_public_id=owner_public_id, sequence=retry.sequence,
            )
            _quality_check(session, version_id=version.id, trace_id=task.trace_id, check_type="source_binding", status="passed")
            _quality_check(session, version_id=version.id, trace_id=task.trace_id, check_type="type_schema", status="passed")
            _quality_check(session, version_id=version.id, trace_id=task.trace_id, check_type="runtime", status="passed")
            continue
        complete_capability_step(
            session, task_id=task.id, owner_public_id=owner_public_id, sequence=sequence,
            output_artifact_version_id=version.id if step.agent_role == "artifact_committer" and version else None,
        )

    if artifact is None or version is None:
        _fail("workspace_local_artifact_missing", "本地演示任务没有生成产物。")
    artifact.status = "approved"
    complete_capability_task(session, task_id=task.id, owner_public_id=owner_public_id)
    session.flush()
    return {"task_id": task.id, "artifact_id": artifact.id, "version_id": version.id, "created": True}
