"""Server-owned unlock gate for learner-generated intelligent exams."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.database import (
    DBGenerationTask,
    DBLearningEvent,
    DBLearningPath,
    DBPathNode,
    DBTaskEvent,
)
from app.m5_learning import _learning_today, multi_course_schedule, today_work_items
from app.learning_aggregation import _event_matches_node, _node_completion_supported, _node_predecessors


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
    return _learning_today().isoformat()


def _task_route(course_id: str, node_id: str) -> str:
    return f"/workspace/path?course_id={course_id}&node_id={node_id}"


def _scheduled_required_today(session, *, owner_public_id, course_id, path_id):
    schedule = multi_course_schedule(session, owner_public_id=owner_public_id, course_id=course_id)
    return [item for item in schedule['selected']['tasks']
            if item.get('path_id') == path_id and item.get('task_kind') == 'path'
            and item.get('required') is not False]


def freeze_exam_gate_snapshot(
    session: Any,
    *,
    owner_public_id: str,
    course_id: str,
    path_id: str,
    task_id: str,
    assigned_at: datetime | None = None,
    allow_scheduled_preparation: bool = False,
) -> dict[str, Any]:
    """Freeze tasks resolved by the server; preparation need not wait until class day."""
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
    assignment_date = _local_day()
    if selected is not None or allow_scheduled_preparation:
        schedule = multi_course_schedule(session, owner_public_id=owner_public_id, course_id=course_id)
        for day in schedule["days"]:
            planned = [item for item in day["tasks"] if item.get("path_id") == path.id]
            match = next((item for item in planned if item.get("node_id") == task_id), None)
            if match is not None:
                # Freeze the whole planned session, including successors that
                # become available after its first task. Otherwise finishing
                # the first step would prematurely unlock the session exam.
                candidates, selected, assignment_date = planned, match, day["date"]
                break
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
    snapshot = {
        "schema_version": GATE_SCHEMA_VERSION,
        "assignment_date": assignment_date,
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
    if assignment_date > _local_day():
        # Preparing materials is not completing today's work or earning a future
        # exam pass. The existing evidence window starts on the scheduled day.
        start = datetime.fromisoformat(assignment_date).replace(tzinfo=timezone(timedelta(hours=8)))
        for item in snapshot["required_tasks"]:
            item["assigned_at"] = start.astimezone(timezone.utc).isoformat()
    # Keep verified earlier work when preparing the next task in the same
    # session. Regenerating the selected task still needs fresh evidence;
    # replans retain only validated inherited completion as before.
    previous = _latest_snapshot(
        session, owner_public_id=owner_public_id, course_id=course_id,
        assignment_date=snapshot["assignment_date"], path=path,
    )
    inherited = {item["id"]: item for item in (previous or {}).get("required_tasks", [])}
    for item in snapshot["required_tasks"]:
        old = inherited.get(item["id"], {})
        if (not old or old.get("generation_required")
                or (item['id'] == task_id and not old.get('inherited_from_path_id'))):
            continue
        node = session.get(DBPathNode, item["id"])
        start = old.get("assigned_at") or previous["assigned_at"]
        if node is not None and _has_valid_completion_evidence(
            session, owner_public_id=owner_public_id, course_id=course_id,
            node=node, assigned_at=_parse_timestamp(start),
        ):
            item['assigned_at'] = start
            if old.get('inherited_from_path_id'):
                item['inherited_from_path_id'] = old['inherited_from_path_id']
    return snapshot


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
    predecessors = None
    earlier_snapshots = []
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
        if snapshot.get("course_id") != course_id:
            continue
        if snapshot.get("assignment_date") != assignment_date:
            if (str(snapshot.get("assignment_date") or "") < assignment_date
                    and snapshot.get("path_id") == path.id
                    and snapshot.get("path_version_id") == path.source_plan_version_id):
                earlier_snapshots.append(snapshot)
            continue
        if snapshot.get("path_id") == path.id and snapshot.get("path_version_id") == path.source_plan_version_id:
            return snapshot
        if not path.supersedes_path_id:
            continue
        if predecessors is None:
            nodes = session.query(DBPathNode).filter_by(learning_path_id=path.id).all()
            predecessors = {old.id: node for node in nodes for old in _node_predecessors(session, node)}
        original = session.get(DBLearningPath, snapshot.get("path_id"))
        if original is None or original.source_plan_version_id != snapshot.get("path_version_id"):
            continue
        today_items = _scheduled_required_today(session, owner_public_id=owner_public_id,
                                               course_id=course_id, path_id=path.id)
        today_ids = {item["node_id"] for item in today_items}
        projected = []
        for item in snapshot.get("required_tasks") or []:
            node = predecessors.get(item.get("id"))
            if node is None or node.is_extension:
                continue
            # A replan can move unfinished work to another day. Keep today's
            # work and completed nodes (whose evidence must still be checked),
            # not every unfinished target from the superseded assignment.
            if node.id not in today_ids and node.status != "completed":
                continue
            projected.append({
                **item, "id": node.id, "node_key": node.node_key, "title": node.title,
                "route": _task_route(course_id, node.id),
                "inherited_from_path_id": item.get("inherited_from_path_id") or original.id,
            })
        if not projected:
            continue
        inherited_ids = {item["id"] for item in projected}
        for item in today_items:
            if item["node_id"] in inherited_ids:
                continue
            projected.append({
                "id": item["node_id"], "node_key": item["node_key"], "title": item["title"],
                "node_type": item["node_type"], "target_object_id": item.get("target_object_id"),
                "route": _task_route(course_id, item["node_id"]), "generation_required": True,
                "completion_criteria": "先从新增的今日知识点生成资源，再完成其中的必做任务。",
            })
        return {
            **snapshot, "path_id": path.id, "path_version_id": path.source_plan_version_id,
            "required_tasks": projected,
            "optional_task_ids": [node.id for node in nodes if node.is_extension],
        }
    # A learner may finish yesterday's prepared resource today. Reuse its
    # unchanged assignment only for today's actual tasks, requiring today's
    # accepted work. Yesterday's score must not unlock a new day's exam.
    if earlier_snapshots and assignment_date == _local_day():
        today_items = _scheduled_required_today(session, owner_public_id=owner_public_id,
                                               course_id=course_id, path_id=path.id)
        start = datetime.fromisoformat(assignment_date).replace(tzinfo=timezone(timedelta(hours=8)))
        for snapshot in earlier_snapshots:
            previous = {item["id"]: item for item in snapshot.get("required_tasks") or []}
            if not any(item["node_id"] in previous for item in today_items):
                continue
            required = []
            for item in today_items:
                old = previous.get(item["node_id"])
                required.append({
                    **(old or {}), "id": item["node_id"], "node_key": item["node_key"],
                    "title": item["title"], "node_type": item["node_type"],
                    "target_object_id": item.get("target_object_id"),
                    "route": _task_route(course_id, item["node_id"]),
                    "assigned_at": start.astimezone(timezone.utc).isoformat(),
                    "generation_required": old is None or bool(old.get("generation_required")),
                    "completion_criteria": (item.get("completion_criteria") or "完成任务并留下有效学习记录。")
                    if old else "先为新增的今日知识点准备资源，再完成学习任务。",
                })
            return {**snapshot, "assignment_date": assignment_date,
                    "assigned_at": start.astimezone(timezone.utc).isoformat(), "required_tasks": required}
    return None


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)


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
    matching = [event for event in events if _event_matches_node(session, event, node)]
    return _node_completion_supported(session, node, matching)


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
                limit=50,
            )
            if item.get("path_id") == path.id and item.get("task_kind") == "path" and item.get("required") is not False
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
    assigned_at = _parse_timestamp(snapshot["assigned_at"])
    for task in snapshot.get("required_tasks") or []:
        task_id = str(task.get("id") or "")
        node = session.query(DBPathNode).filter_by(id=task_id, learning_path_id=path.id).first()
        complete = bool(
            node is not None
            and not task.get("generation_required")
            and _has_valid_completion_evidence(
                session,
                owner_public_id=owner_public_id,
                course_id=course_id,
                node=node,
                assigned_at=_parse_timestamp(task["assigned_at"]) if task.get("assigned_at") else assigned_at,
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
