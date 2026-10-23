"""Server-owned unlock gate for learner-generated intelligent exams."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.database import (
    DBChapterKnowledgePoint,
    DBGenerationTask,
    DBLearningEvent,
    DBLearningPath,
    DBPathNode,
    DBTaskEvent,
)
from app.m5_learning import today_work_items


GATE_SCHEMA_VERSION = "f4.intelligent-exam-gate.v1"
RESOURCE_GENERATION_CAPABILITY = "learning_resource_bundle.generate"


class ExamGateError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise ExamGateError(code, message)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _local_day() -> str:
    return datetime.now().astimezone().date().isoformat()


def _task_route(course_id: str, node_id: str) -> str:
    return f"/workspace/path?course_id={course_id}&node_id={node_id}"


def freeze_exam_gate_snapshot(
    session: Any,
    *,
    owner_public_id: str,
    course_id: str,
    path_id: str,
    task_id: str,
    assigned_at: datetime | None = None,
) -> dict[str, Any]:
    """Freeze the server-resolved required TodayTasks for one resource request."""
    path = session.query(DBLearningPath).filter_by(
        id=path_id,
        owner_public_id=owner_public_id,
        course_id=course_id,
        status="active",
    ).first()
    if path is None:
        _fail("exam_gate.path_unknown", "当前课程没有可用于今日任务的活动路径")

    candidates = [
        item for item in today_work_items(
            session,
            owner_public_id=owner_public_id,
            course_id=course_id,
            limit=50,
        )
        if item.get("path_id") == path.id
    ]
    selected = next((item for item in candidates if item.get("node_id") == task_id), None)
    if selected is None:
        _fail("exam_gate.task_not_today", "所选知识点不属于当前路径的今日任务")

    required_items = [
        item for item in candidates
        if item.get("required") is not False and item.get("task_kind") == "path"
    ]
    if not required_items:
        _fail("exam_gate.required_tasks_missing", "当前路径还没有可冻结的今日必做任务")

    timestamp = assigned_at or _now()
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = timestamp.astimezone(timezone.utc)
    return {
        "schema_version": GATE_SCHEMA_VERSION,
        "assignment_date": _local_day(),
        "assigned_at": timestamp.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
        "course_id": course_id,
        "path_id": path.id,
        "path_version_id": path.source_plan_version_id,
        "selected_task_id": task_id,
        "required_tasks": [
            {
                "id": str(item["node_id"]),
                "node_key": str(item.get("node_key") or item["node_id"]),
                "title": str(item.get("title") or "今日学习任务"),
                "node_type": str(item.get("node_type") or "path"),
                "target_object_id": item.get("target_object_id"),
                "completion_criteria": str(item.get("completion_criteria") or "完成任务并留下有效学习证据。"),
                "route": _task_route(course_id, str(item["node_id"])),
            }
            for item in required_items
        ],
        "optional_task_ids": [
            node.id for node in session.query(DBPathNode).filter_by(
                learning_path_id=path.id,
                is_extension=True,
            ).order_by(DBPathNode.sequence, DBPathNode.id).all()
        ],
    }


def _snapshot_from_event(event: DBTaskEvent) -> dict[str, Any] | None:
    manifest = dict((event.payload or {}).get("manifest") or {})
    snapshot = manifest.get("exam_gate")
    return dict(snapshot) if isinstance(snapshot, dict) else None


def _latest_snapshot(
    session: Any,
    *,
    owner_public_id: str,
    course_id: str,
    assignment_date: str,
    path: DBLearningPath,
) -> dict[str, Any] | None:
    tasks = session.query(DBGenerationTask).filter_by(
        owner_public_id=owner_public_id,
        course_id=course_id,
        capability=RESOURCE_GENERATION_CAPABILITY,
    ).order_by(DBGenerationTask.created_at.desc(), DBGenerationTask.id.desc()).all()
    for task in tasks:
        event = session.query(DBTaskEvent).filter_by(
            task_id=task.id,
            event_type="resource_generation.requested",
        ).order_by(DBTaskEvent.sequence).first()
        if event is None:
            continue
        snapshot = _snapshot_from_event(event)
        if not snapshot:
            continue
        if (
            snapshot.get("assignment_date") == assignment_date
            and snapshot.get("course_id") == course_id
            and snapshot.get("path_id") == path.id
            and snapshot.get("path_version_id") == path.source_plan_version_id
        ):
            return snapshot
    return None


def _has_valid_completion_evidence(
    session: Any,
    *,
    owner_public_id: str,
    course_id: str,
    node: DBPathNode,
    assigned_at: datetime,
) -> bool:
    events = session.query(DBLearningEvent).filter_by(
        owner_public_id=owner_public_id,
        course_id=course_id,
        evidence_status="accepted",
        mastery_eligible=True,
        completion_effect="complete",
    ).filter(DBLearningEvent.occurred_at >= assigned_at).all()
    chapter_point_ids = {
        str(row[0]) for row in session.query(DBChapterKnowledgePoint.knowledge_point_id).filter_by(
            chapter_id=node.target_object_id,
        ).all()
    } if node.node_type == "chapter" and node.target_object_id else set()
    for event in events:
        if (event.context_ref or {}).get("taskId") == node.id:
            return True
        if node.target_object_id and event.object_id == node.target_object_id:
            return True
        if chapter_point_ids:
            context = event.context_ref or {}
            payload = event.payload or {}
            event_point_ids = {
                str(value) for value in (
                    context.get("knowledgePointId"),
                    context.get("knowledge_point_id"),
                    payload.get("knowledgePointId"),
                    payload.get("knowledge_point_id"),
                ) if value
            }
            if chapter_point_ids.intersection(event_point_ids):
                return True
    return False


def exam_gate_status(
    session: Any,
    *,
    owner_public_id: str,
    course_id: str,
    assignment_date: str | None = None,
) -> dict[str, Any]:
    day = assignment_date or _local_day()
    path = session.query(DBLearningPath).filter_by(
        owner_public_id=owner_public_id,
        course_id=course_id,
        status="active",
    ).order_by(DBLearningPath.updated_at.desc(), DBLearningPath.id.desc()).first()
    if path is None:
        path = session.query(DBLearningPath).filter_by(
            owner_public_id=owner_public_id,
            course_id=course_id,
            status="completed",
        ).order_by(DBLearningPath.completed_at.desc(), DBLearningPath.updated_at.desc(), DBLearningPath.id.desc()).first()
    if path is None:
        return {
            "schema_version": GATE_SCHEMA_VERSION,
            "assignment_date": day,
            "course_id": course_id,
            "path_id": None,
            "path_version_id": None,
            "required_task_ids": [],
            "completed_task_ids": [],
            "missing_task_ids": [],
            "missing_tasks": [],
            "unlocked": False,
            "reason": "active_path_required",
            "next_route": f"/workspace/path?course_id={course_id}",
        }

    snapshot = _latest_snapshot(
        session,
        owner_public_id=owner_public_id,
        course_id=course_id,
        assignment_date=day,
        path=path,
    )
    if snapshot is None:
        pending = [
            item for item in today_work_items(
                session,
                owner_public_id=owner_public_id,
                course_id=course_id,
                limit=3,
            )
            if item.get("path_id") == path.id and item.get("required") is not False
        ]
        return {
            "schema_version": GATE_SCHEMA_VERSION,
            "assignment_date": day,
            "course_id": course_id,
            "path_id": path.id,
            "path_version_id": path.source_plan_version_id,
            "required_task_ids": [],
            "completed_task_ids": [],
            "missing_task_ids": [str(item["node_id"]) for item in pending],
            "missing_tasks": [{
                "id": str(item["node_id"]),
                "title": str(item.get("title") or "今日学习任务"),
                "node_type": str(item.get("node_type") or "path"),
                "completion_criteria": "先从今日知识点生成完整资源包，再完成其中的必做任务。",
                "route": _task_route(course_id, str(item["node_id"])),
            } for item in pending],
            "unlocked": False,
            "reason": "today_snapshot_required",
            "next_route": f"/workspace/path?course_id={course_id}",
        }

    completed_ids: list[str] = []
    missing_tasks: list[dict[str, Any]] = []
    assigned_at = datetime.fromisoformat(
        str(snapshot["assigned_at"]).replace("Z", "+00:00")
    ).astimezone(timezone.utc).replace(tzinfo=None)
    for task in snapshot.get("required_tasks") or []:
        task_id = str(task.get("id") or "")
        node = session.query(DBPathNode).filter_by(id=task_id, learning_path_id=path.id).first()
        complete = bool(
            node is not None
            and _has_valid_completion_evidence(
                session,
                owner_public_id=owner_public_id,
                course_id=course_id,
                node=node,
                assigned_at=assigned_at,
            )
        )
        if complete:
            completed_ids.append(task_id)
        else:
            missing_tasks.append({
                "id": task_id,
                "title": str(task.get("title") or "今日学习任务"),
                "node_type": str(task.get("node_type") or "path"),
                "completion_criteria": str(task.get("completion_criteria") or "完成任务并留下有效学习证据。"),
                "route": str(task.get("route") or _task_route(course_id, task_id)),
            })

    required_ids = [str(task.get("id") or "") for task in snapshot.get("required_tasks") or []]
    unlocked = bool(required_ids) and not missing_tasks
    return {
        "schema_version": GATE_SCHEMA_VERSION,
        "assignment_date": day,
        "course_id": course_id,
        "path_id": path.id,
        "path_version_id": path.source_plan_version_id,
        "required_task_ids": required_ids,
        "completed_task_ids": completed_ids,
        "missing_task_ids": [task["id"] for task in missing_tasks],
        "missing_tasks": missing_tasks,
        "optional_task_ids": list(snapshot.get("optional_task_ids") or []),
        "unlocked": unlocked,
        "reason": "ready" if unlocked else "required_tasks_incomplete",
        "next_route": None if unlocked else (missing_tasks[0]["route"] if missing_tasks else f"/workspace/path?course_id={course_id}"),
    }


def require_exam_gate(
    session: Any,
    *,
    owner_public_id: str,
    course_id: str,
) -> dict[str, Any]:
    status = exam_gate_status(
        session,
        owner_public_id=owner_public_id,
        course_id=course_id,
    )
    if not status["unlocked"]:
        _fail("exam_gate.locked", "请先完成今日全部必做任务，再进入智能组卷")
    return status
