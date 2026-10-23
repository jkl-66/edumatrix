"""Read-only student dashboard decision summary."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from app.database import (
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
    DBDiagnosticReport,
    DBLearningEvent,
    DBLearningEventConsumption,
    DBKnowledgePoint,
    DBProfileSnapshot,
)
from app.legacy_adapter import LegacyDataAdapter, LegacyProfileMigrationError
from app.m5_workspace import workspace_overview


_RESOURCE_LABELS = {
    "code": "代码沙盒",
    "lab": "实训任务",
    "practice": "测验题资源",
    "quiz": "测验题资源",
    "read": "个性化讲义",
    "review": "复习中心",
    "video": "视频推荐",
}

_LEGACY_ALIGNMENT_FIELDS = {
    "knowledge_base": "旧知识库",
    "learning_state_causes": "旧学习状态",
    "cognitive_style": "旧学习风格",
    "motivation_type": "旧学习动机",
}

_DISPLAY_TZ = ZoneInfo("Asia/Shanghai")


def _display_datetime(value: datetime) -> datetime:
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return aware.astimezone(_DISPLAY_TZ)


def _snapshot_course_id(row: DBProfileSnapshot) -> str | None:
    body = row.snapshot or {}
    return str(body.get("course_id") or (body.get("course_context") or {}).get("courseId") or "") or None


def _profile_alignment(
    session: Any,
    *,
    current_user: Any,
    course: DBCourse | dict[str, Any] | None,
) -> dict[str, Any]:
    """Expose the same read-only course/profile/legacy evidence used by profile summary."""
    if course is None:
        return {
            "status": "missing_course",
            "course": None,
            "profile_snapshot": {"id": None, "version": None, "updated_at": None, "status": "unknown"},
            "legacy_migration": {"status": "unknown", "fields": [], "read_only": True},
            "read_only": True,
        }

    course_id = course.id if isinstance(course, DBCourse) else str(course.get("id") or "")
    course_row = course if isinstance(course, DBCourse) else session.query(DBCourse).filter_by(id=course_id).first()
    if course_row is None:
        return {
            "status": "unknown",
            "course": dict(course) if isinstance(course, dict) else None,
            "profile_snapshot": {"id": None, "version": None, "updated_at": None, "status": "unknown"},
            "legacy_migration": {"status": "unknown", "fields": [], "read_only": True},
            "read_only": True,
        }

    snapshots = session.query(DBProfileSnapshot).filter_by(
        owner_public_id=current_user.public_id,
    ).order_by(DBProfileSnapshot.created_at.desc(), DBProfileSnapshot.id.desc()).all()
    snapshot = next(
        (row for row in snapshots if _snapshot_course_id(row) in {None, course_id}),
        None,
    )
    try:
        report = LegacyDataAdapter(session).profile_migration_report(
            current_user.public_id,
            course_id=course_id,
        )
    except LegacyProfileMigrationError as exc:
        report = {
            "status": "not_available",
            "mapping_version": "legacy-profile-map.v1",
            "source_profile": {"last_updated": None},
            "diff": [],
            "read_only": True,
            "error": {"code": exc.code, "message": str(exc)},
        }
    source_profile = report.get("source_profile") or {}
    fields = []
    for item in report.get("diff") or []:
        field = str(item.get("legacy_field") or "")
        if field not in _LEGACY_ALIGNMENT_FIELDS:
            continue
        fields.append({
            "field": field,
            "label": _LEGACY_ALIGNMENT_FIELDS[field],
            "status": item.get("status") or "unknown",
            "algorithm_version": item.get("algorithm_version"),
            "canonical_path": item.get("canonical_path"),
            "source": "DBStudentProfile",
            "observed_at": source_profile.get("last_updated"),
        })
    snapshot_updated_at = snapshot.created_at.isoformat() if snapshot and snapshot.created_at else None
    source_updated_at = source_profile.get("last_updated")
    has_evidence = bool(snapshot or fields)
    return {
        "status": "ready" if has_evidence else "unknown",
        "course": {
            "id": course_row.id,
            "title": course_row.title,
            "version": course_row.version,
            "source": course_row.content_origin or course_row.manifest_version,
            "updated_at": snapshot_updated_at or source_updated_at,
        },
        "profile_snapshot": {
            "id": snapshot.id if snapshot else (report.get("canonical_snapshot") or {}).get("id"),
            "version": snapshot.profile_version if snapshot else (report.get("canonical_snapshot") or {}).get("version"),
            "updated_at": snapshot_updated_at,
            "status": "available" if snapshot else "unknown",
        },
        "legacy_migration": {
            "status": report.get("status", "unknown"),
            "mapping_version": report.get("mapping_version"),
            "source": report.get("source_profile"),
            "fields": fields,
            "updated_at": source_updated_at,
            "read_only": True,
            "error": report.get("error"),
        },
        "read_only": True,
    }


def _strategy(task: dict[str, Any]) -> str:
    if task.get("task_kind") == "review":
        return "先独立回忆核心结论，再打开资料核对遗漏，最后完成一次有效复习。"
    node_type = str(task.get("node_type") or "").lower()
    if node_type in {"code", "lab"}:
        return "先按任务书完成实操，再根据真实运行结果定位问题并修正。"
    if node_type in {"practice", "quiz", "assessment"}:
        return "先独立作答，再根据解析补齐薄弱点，不把查看答案当作完成。"
    if node_type in {"read", "lecture", "handout"}:
        return "先阅读核心讲义并记录关键概念，再完成对应的理解检查。"
    return "按已确认路径完成当前任务，达到完成标准后再进入下一知识点。"


def _resource_label(task: dict[str, Any]) -> str:
    if task.get("task_kind") == "review":
        return "复习中心"
    node_type = str(task.get("node_type") or "").lower()
    return _RESOURCE_LABELS.get(node_type, "学习空间")


def _task_source(task: dict[str, Any]) -> list[dict[str, str]]:
    refs = []
    if task.get("path_id"):
        refs.append({"type": "learning_path", "id": str(task["path_id"]), "label": "当前已确认学习路径"})
    if task.get("node_id"):
        refs.append({
            "type": "review_plan" if task.get("task_kind") == "review" else "path_node",
            "id": str(task["node_id"]),
            "label": "到期复习计划" if task.get("task_kind") == "review" else "当前路径任务",
        })
    return refs


def _weak_summary(
    session: Any,
    *,
    current_user: Any,
    course: dict[str, Any] | None,
    profile: dict[str, Any] | None,
    aggregation_rows: list[tuple[Any, Any]],
    path: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Build read-only, evidence-aware priority cards from the current profile snapshot."""
    if not profile or not course:
        return []

    course_id = str(course.get("id") or "")
    snapshot_id = str(profile.get("snapshot_id") or "")
    snapshot_row = (
        session.query(DBProfileSnapshot).filter_by(
            id=snapshot_id, owner_public_id=current_user.public_id,
        ).first()
        if snapshot_id else None
    )
    body = dict(snapshot_row.snapshot or {}) if snapshot_row else {}
    snapshot_course_id = body.get("course_id") or (body.get("course_context") or {}).get("courseId")
    if snapshot_course_id and str(snapshot_course_id) != course_id:
        return []
    projection = dict(body.get("profile_projection") or {})
    raw_items = list(profile.get("weak_knowledge_points") or [])
    if not raw_items:
        raw_items = list(body.get("weak_knowledge_point_ids") or body.get("weak_points") or [])
    raw_items = raw_items[:3]

    point_ids = [
        str(item.get("id") or "") if isinstance(item, dict) else str(item or "")
        for item in raw_items
    ]
    point_ids = [item for item in point_ids if item]
    chapters = session.query(DBChapter.id).filter_by(course_id=course_id).all()
    course_chapter_ids = [row[0] for row in chapters]
    course_point_ids = {
        row[0] for row in session.query(DBChapterKnowledgePoint.knowledge_point_id).filter(
            DBChapterKnowledgePoint.chapter_id.in_(course_chapter_ids),
        ).all()
    } if course_chapter_ids else set()
    point_titles = {
        row.id: row.title
        for row in session.query(DBKnowledgePoint).filter(DBKnowledgePoint.id.in_(point_ids)).all()
    } if point_ids else {}
    course_point_titles = {
        row.id: row.title
        for row in session.query(DBKnowledgePoint).filter(DBKnowledgePoint.id.in_(course_point_ids)).all()
    } if course_point_ids else {}
    point_titles.update(course_point_titles)
    if course_point_ids:
        course_titles = set(course_point_titles.values())
        raw_items = [
            item for item in raw_items
            if (
                (str(item.get("id") or "") in course_point_ids if isinstance(item, dict) else str(item or "") in course_point_ids)
                or (isinstance(item, dict) and str(item.get("title") or "") in course_titles)
            )
        ]

    mastery_by_point = body.get("mastery_by_knowledge_point") or body.get("masteryByKnowledgePoint") or {}
    if not isinstance(mastery_by_point, dict):
        mastery_by_point = {}
    concept_mastery = projection.get("concept_mastery") or body.get("concept_mastery") or {}
    if not isinstance(concept_mastery, dict):
        concept_mastery = {}
    dimensions = (
        projection.get("dimension_states") or projection.get("dimensions")
        or body.get("dimension_states") or {}
    )
    if not isinstance(dimensions, dict):
        dimensions = {}
    attributions = body.get("weak_point_attribution") or body.get("weakPointAttribution") or []
    if not isinstance(attributions, list):
        attributions = []

    def _as_list(value: Any) -> list[Any]:
        if isinstance(value, (list, tuple, set)):
            return list(value)
        return [value] if value not in (None, "") else []

    def _event_matches(event: Any, item_id: str, title: str) -> bool:
        if event is None or str(getattr(event, "course_id", "") or "") != course_id:
            return False
        context = getattr(event, "context_ref", None)
        payload = getattr(event, "payload", None)
        context = context if isinstance(context, dict) else {}
        payload = payload if isinstance(payload, dict) else {}
        identifiers = {
            str(context.get("knowledgePointId") or ""),
            str(context.get("knowledge_point_id") or ""),
            str(payload.get("knowledge_point_id") or ""),
            str(payload.get("knowledgePointId") or ""),
            str(payload.get("concept") or ""),
            str(getattr(event, "object_id", "") or "")
            if getattr(event, "object_type", "") == "knowledge_point" else "",
        }
        if (item_id and item_id in identifiers) or (title and title in identifiers):
            return True
        for key in ("knowledge_point_scores", "item_results"):
            for entry in payload.get(key) or []:
                if not isinstance(entry, dict):
                    continue
                point = str(entry.get("knowledge_point_id") or entry.get("knowledgePointId") or "")
                if point in {item_id, title}:
                    return True
        return False

    snapshot_version = (
        snapshot_row.profile_version if snapshot_row
        else body.get("profile_version") or profile.get("profile_version")
    )
    path_nodes = list((path or {}).get("nodes") or [])
    result: list[dict[str, Any]] = []
    for raw in raw_items:
        item_id = str(raw.get("id") or "").strip() if isinstance(raw, dict) else str(raw or "").strip()
        raw_title = str(raw.get("title") or "").strip() if isinstance(raw, dict) else ""
        # Prefer the canonical course knowledge-point title over a stale profile label.
        title = point_titles.get(item_id) or raw_title or item_id or "未命名知识点"

        raw_mastery = mastery_by_point.get(item_id) if item_id else None
        mastery_record = raw_mastery if isinstance(raw_mastery, dict) else {}
        mastery_value = mastery_record.get("score") if mastery_record else raw_mastery
        if mastery_value is None:
            mastery_value = concept_mastery.get(item_id, concept_mastery.get(title))
        try:
            mastery_value = round(float(mastery_value), 4) if mastery_value is not None else None
        except (TypeError, ValueError):
            mastery_value = None
        mastery_status = "supported" if mastery_value is not None else "unknown"

        attribution = next((
            item for item in attributions
            if isinstance(item, dict)
            and str(
                item.get("weakPoint") or item.get("weak_point")
                or item.get("knowledge_point_id") or item.get("knowledgePointId") or ""
            ) in {item_id, title}
        ), None)
        reason = str((attribution or {}).get("reason") or "").strip()
        reason_evidence = str(
            (attribution or {}).get("evidence") or (attribution or {}).get("text") or ""
        ).strip()
        reason_status = "supported" if reason else "unknown"
        if not reason and mastery_value is not None and mastery_value < 0.6:
            reason = f"最近掌握证据为 {round(mastery_value * 100)}%，低于薄弱判定阈值 60%。"
            reason_status = "supported"
        elif not reason:
            reason = "当前画像快照记录该知识点需要优先强化；具体原因待确认。"

        dimension_keys = (
            (attribution or {}).get("dimension_keys")
            or (attribution or {}).get("dimensions")
            or (attribution or {}).get("dimension") or []
        )
        dimension_keys = _as_list(dimension_keys)
        source_turn_id = str(body.get("source_turn_id") or "")
        if not dimension_keys and source_turn_id:
            dimension_keys = [
                key for key, value in dimensions.items()
                if isinstance(value, dict) and str(value.get("source_turn_id") or "") == source_turn_id
            ]
        related_dimensions = []
        for key in dimension_keys:
            key = str(key or "").strip()
            if not key or key not in dimensions:
                continue
            value = dimensions.get(key)
            if isinstance(value, dict):
                related_dimensions.append({
                    "key": key,
                    "label": str(value.get("label") or key),
                    "status": str(value.get("status") or value.get("summary") or "已记录"),
                    "score": value.get("score"),
                    "evidence": str(value.get("evidence") or value.get("evidence_summary") or ""),
                })
            else:
                related_dimensions.append({"key": key, "label": key, "status": str(value), "score": None, "evidence": ""})
        if not related_dimensions:
            related_dimensions = [{"key": "unknown", "label": "关联画像维度", "status": "待确认", "score": None, "evidence": ""}]

        event_refs = []
        for _, event in aggregation_rows:
            if not _event_matches(event, item_id, title):
                continue
            event_refs.append({
                "type": "learning_event",
                "id": str(event.id),
                "label": "支持该知识点的学习事件",
                "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
            })
            if len(event_refs) >= 3:
                break
        source_refs = []
        if snapshot_row:
            source_refs.append({"type": "profile_snapshot", "id": snapshot_row.id, "label": "当前画像快照", "version": snapshot_version})
        for source_id in _as_list(mastery_record.get("source_ref_ids") or mastery_record.get("sourceRefIds")):
            source_id = str(source_id or "").strip()
            if source_id:
                source_refs.append({"type": "source_ref", "id": source_id, "label": "诊断课程来源"})
        for source in _as_list((attribution or {}).get("source_refs")):
            if isinstance(source, dict) and (source.get("id") or source.get("label")):
                source_refs.append(dict(source))
        deduped_refs = []
        seen_refs = set()
        for ref in source_refs:
            marker = (str(ref.get("type") or ""), str(ref.get("id") or ""), str(ref.get("label") or ""))
            if marker not in seen_refs:
                seen_refs.add(marker)
                deduped_refs.append(ref)

        params = {"course_id": course_id}
        if item_id:
            params["knowledge_point_id"] = item_id
            if snapshot_id:
                params["profile_snapshot_id"] = snapshot_id
        node = next((
            node for node in path_nodes
            if str(node.get("target_object_id") or "") == item_id
            or str(node.get("id") or "") == item_id
            or str(node.get("title") or "") == title
        ), None)
        if node and node.get("id"):
            params["node_id"] = str(node["id"])
        route = (
            f"/workspace?{urlencode(params)}" if item_id and node and node.get("id")
            else f"/workspace/path?{urlencode(params)}" if item_id else ""
        )
        result.append({
            "id": item_id or None,
            "knowledge_point_id": item_id or None,
            "title": title,
            "mastery": mastery_value,
            "mastery_status": mastery_status,
            "mastery_label": "有掌握证据" if mastery_value is not None else "未知（暂无掌握证据）",
            "weak_reason": reason,
            "weak_reason_status": reason_status,
            "weak_reason_evidence": reason_evidence,
            "profile_dimensions": related_dimensions,
            "course_snapshot": {
                "course_id": course_id,
                "course_title": str(course.get("title") or "") or None,
                "course_version": str(course.get("version") or "") or None,
                "snapshot_id": snapshot_id or None,
                "snapshot_version": str(snapshot_version or "") or None,
            },
            "source_refs": deduped_refs,
            "event_refs": event_refs,
            "next_action": {
                "label": "开始强化" if route else "路径待确认",
                "route": route or None,
                "available": bool(route),
                "course_id": course_id,
                "knowledge_point_id": item_id or None,
                "profile_snapshot_id": snapshot_id or None,
            },
        })
    return result


def _strategy_payload(task: dict[str, Any], *, current: bool) -> dict[str, Any]:
    estimate = list(task.get("estimate_minutes") or [])
    return {
        "id": str(task.get("node_id") or ""),
        "title": str(task.get("title") or "未命名任务"),
        "task_kind": str(task.get("task_kind") or "path"),
        "is_current": current,
        "strategy": _strategy(task),
        "reason": str(task.get("recommendation_reason") or "来自当前已确认学习路径。"),
        "recommended_resource": _resource_label(task),
        "estimate_minutes": estimate,
        "completion_criteria": str(task.get("completion_criteria") or "完成任务要求并保存有效学习证据。"),
        "continue_route": str(task.get("continue_route") or "/workspace"),
        "source_refs": _task_source(task),
    }


def _aggregation_rows(session: Any, *, owner_public_id: str, course_id: str | None) -> list[tuple[Any, Any]]:
    query = session.query(DBLearningEventConsumption, DBLearningEvent).join(
        DBLearningEvent,
        DBLearningEvent.id == DBLearningEventConsumption.learning_event_id,
    ).filter(
        DBLearningEventConsumption.consumer == "learning_aggregation",
        DBLearningEvent.owner_public_id == owner_public_id,
    )
    if course_id is None:
        query = query.filter(DBLearningEvent.course_id.is_(None))
    else:
        query = query.filter(DBLearningEvent.course_id == course_id)
    return query.order_by(
        DBLearningEvent.occurred_at.desc(),
        DBLearningEventConsumption.created_at.desc(),
    ).limit(24).all()


def mastery_trend(
    rows: list[tuple[Any, Any]], *, limit: int = 7,
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    seen_days: set[str] = set()
    for consumption, event in rows:
        if consumption.status != "processed":
            continue
        dashboard = (((consumption.result or {}).get("steps") or {}).get("dashboard") or {}).get("summary") or {}
        value = dashboard.get("mastery_average")
        if value is None or event.occurred_at is None:
            continue
        day = _display_datetime(event.occurred_at).date().isoformat()
        if day in seen_days:
            continue
        seen_days.add(day)
        points.append({
            "label": _display_datetime(event.occurred_at).strftime("%m-%d"),
            "value": round(float(value) * 100),
            "source_event_id": event.id,
            "occurred_at": event.occurred_at.isoformat(),
        })
        if len(points) >= limit:
            break
    return list(reversed(points))


def activity_trend(events: list[DBLearningEvent], *, limit: int = 30) -> list[dict[str, Any]]:
    """Summarize observable learning activity by display-local day.

    This is intentionally separate from mastery_trend: activity is visible
    progress context, while mastery remains gated by accepted processed evidence.
    """
    by_day: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.occurred_at is None:
            continue
        payload = event.payload or {}
        minutes = 0.0
        for key in ("actual_minutes", "duration_minutes"):
            value = payload.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
                minutes = float(value)
                break
        if not minutes:
            seconds = payload.get("active_seconds")
            if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and seconds > 0:
                minutes = float(seconds) / 60.0
        active = bool(
            minutes > 0
            or event.completion_effect in {"progress", "complete"}
            or (event.mastery_eligible and event.evidence_status == "accepted")
        )
        if not active:
            continue
        local_day = _display_datetime(event.occurred_at).date().isoformat()
        item = by_day.setdefault(local_day, {"date": local_day, "event_count": 0, "active_minutes": 0.0})
        item["event_count"] += 1
        item["active_minutes"] += minutes
    points = sorted(by_day.values(), key=lambda item: item["date"])
    return [
        {
            **item,
            "label": item["date"][5:10],
            "active_minutes": round(item["active_minutes"], 1),
        }
        for item in points[-max(1, int(limit)):]
    ]


def _trend(rows: list[tuple[Any, Any]]) -> list[dict[str, Any]]:
    return mastery_trend(rows)


def _primary_action(
    *,
    state: str,
    course_id: str | None,
    primary_task: dict[str, Any] | None,
    restore_task: dict[str, Any] | None,
) -> dict[str, str]:
    course_query = f"?course_id={course_id}" if course_id else ""
    if state == "course_required":
        return {"label": "选择预置课程", "route": "/knowledge"}
    if state == "onboarding_required":
        return {"label": "开始构建学习画像", "route": "/onboarding"}
    if state == "diagnostic_required":
        return {"label": "开始入学诊断", "route": f"/workspace/assessment/entry{course_query}"}
    if state == "path_required":
        return {"label": "生成并确认学习路径", "route": f"/workspace/path{course_query}"}
    if state == "restore_pending" and restore_task:
        suffix = "&" if course_query else "?"
        return {
            "label": "继续恢复中的任务",
            "route": f"/workspace{course_query}{suffix}task_id={restore_task['id']}",
        }
    if primary_task:
        return {"label": "继续当前任务", "route": str(primary_task.get("continue_route") or "/workspace")}
    return {"label": "查看下一步学习安排", "route": f"/workspace/path{course_query}"}


def _focus_copy(state: str, primary_task: dict[str, Any] | None) -> dict[str, Any]:
    if primary_task:
        estimate = list(primary_task.get("estimate_minutes") or [])
        return {
            "title": str(primary_task.get("title") or "继续今日学习"),
            "strategy": _strategy(primary_task),
            "reason": str(primary_task.get("recommendation_reason") or "来自当前已确认学习路径。"),
            "completion_criteria": str(primary_task.get("completion_criteria") or "完成任务要求并保存有效学习证据。"),
            "estimated_minutes": estimate,
            "source_refs": _task_source(primary_task),
        }
    copies = {
        "course_required": ("先选择一门预置课程", "选定课程后，系统才能读取对应知识点、来源和学习路径。"),
        "onboarding_required": ("先让系统了解你的学习目标", "通过自然语言交流确认背景、基础、困难和偏好。"),
        "diagnostic_required": ("完成入学诊断", "用真实作答建立初始掌握证据，再生成适合你的学习路径。"),
        "path_required": ("确认第一版学习路径", "检查知识顺序与预计投入，确认后才会生成今日任务。"),
        "today_complete": ("今天的必做任务已完成", "查看下一步安排，或按复习队列继续巩固。"),
    }
    title, strategy = copies.get(state, ("继续当前学习安排", "已有内容仍可使用，完成当前学习动作后即可查看最新结果。"))
    return {
        "title": title,
        "strategy": strategy,
        "reason": "依据当前课程状态生成。",
        "completion_criteria": "完成当前主动作后返回首页，系统会读取最新状态。",
        "estimated_minutes": [],
        "source_refs": [],
    }


def build_dashboard_summary(
    session: Any, *, current_user: Any, course_id: str | None = None,
) -> dict[str, Any]:
    """Compose one traceable next action without mutating learning state."""

    overview = workspace_overview(session, current_user=current_user, course_id=course_id)
    course = overview.get("course")
    resolved_course_id = str(course.get("id")) if course else None
    path = overview.get("current_path")
    tasks = list(overview.get("today_tasks") or [])
    primary_task = tasks[0] if tasks else None

    onboarding_snapshot = session.query(DBProfileSnapshot).filter_by(
        owner_public_id=current_user.public_id,
        profile_version="onboarding.initial.v1",
    ).order_by(DBProfileSnapshot.created_at.desc(), DBProfileSnapshot.id.desc()).first()
    report = None
    if resolved_course_id:
        report = session.query(DBDiagnosticReport).filter_by(
            owner_public_id=current_user.public_id,
            course_id=resolved_course_id,
        ).order_by(DBDiagnosticReport.created_at.desc(), DBDiagnosticReport.id.desc()).first()

    compatibility_ready = path is not None
    onboarding_complete = onboarding_snapshot is not None or overview.get("profile") is not None or compatibility_ready
    diagnostic_complete = report is not None or compatibility_ready
    restore_task = (overview.get("restore") or {}).get("task")
    aggregation_rows = _aggregation_rows(
        session,
        owner_public_id=current_user.public_id,
        course_id=resolved_course_id,
    ) if course else []
    activity_events = []
    if course:
        activity_now = datetime.now(timezone.utc)
        activity_start = (activity_now.astimezone(_DISPLAY_TZ).date() - timedelta(days=29))
        activity_start_utc = datetime.combine(activity_start, datetime.min.time(), tzinfo=_DISPLAY_TZ).astimezone(timezone.utc).replace(tzinfo=None)
        activity_query = session.query(DBLearningEvent).filter(
            DBLearningEvent.owner_public_id == current_user.public_id,
            DBLearningEvent.course_id == resolved_course_id,
            DBLearningEvent.occurred_at >= activity_start_utc,
        )
        activity_events = activity_query.order_by(DBLearningEvent.occurred_at.asc()).all()
    activity_points = activity_trend(activity_events, limit=30)
    latest_consumption, latest_event = aggregation_rows[0] if aggregation_rows else (None, None)

    if course is None:
        state = "course_required"
    elif not onboarding_complete:
        state = "onboarding_required"
    elif not diagnostic_complete:
        state = "diagnostic_required"
    elif path is None:
        state = "path_required"
    elif restore_task and restore_task.get("status") in {"queued", "running"}:
        state = "restore_pending"
    elif latest_consumption is not None and latest_consumption.status == "pending":
        state = "aggregation_updating"
    elif latest_consumption is not None and latest_consumption.status == "failed":
        state = "aggregation_recovery"
    elif primary_task:
        state = "ready"
    else:
        state = "today_complete"

    nodes = list((path or {}).get("nodes") or [])
    completed = sum(item.get("status") == "completed" for item in nodes)
    profile = overview.get("profile") or {}
    profile_alignment = _profile_alignment(
        session,
        current_user=current_user,
        course=course,
    )
    weak_summary = _weak_summary(
        session,
        current_user=current_user,
        course=course,
        profile=profile or None,
        aggregation_rows=aggregation_rows,
        path=path,
    )
    review = overview.get("review") or {"due_count": 0, "items": []}
    source_event_ids = [event.id for _, event in aggregation_rows if event.id][:8]
    latest_event_at = latest_event.occurred_at.isoformat() if latest_event and latest_event.occurred_at else None
    metrics = [
        {
            "label": "路径进度",
            "value": f"{completed}/{len(nodes)}" if nodes else "暂无",
            "detail": "已完成任务 / 路径任务",
            "source_refs": ([{"type": "learning_path", "id": path["id"], "label": "当前已确认学习路径"}] if path else []),
        },
        {
            "label": "到期复习",
            "value": str(int(review.get("due_count") or 0)),
            "detail": "来自当前课程复习队列",
            "source_refs": [{"type": "review_queue", "id": resolved_course_id or "", "label": "当前课程复习计划"}],
        },
        {
            "label": "需强化",
            "value": str(len(weak_summary)) if overview.get("profile") else "暂无",
            "detail": "来自最近画像快照",
            "source_refs": ([{"type": "profile_snapshot", "id": str(profile.get("snapshot_id") or ""), "label": "最近画像快照"}] if profile else []),
        },
        {
            "label": "最近更新",
            "value": latest_event_at[5:10] if latest_event_at else "暂无",
            "detail": "来自最近有效学习事件" if latest_event_at else "完成学习后生成",
            "source_refs": ([{"type": "learning_event", "id": latest_event.id, "label": "最近学习事件"}] if latest_event else []),
        },
    ]
    aggregation = {
        "status": latest_consumption.status if latest_consumption else "not_started",
        "source_event_id": latest_event.id if latest_event else None,
        "updated_at": latest_event_at,
        "message": (
            "最新学习结果正在同步，当前任务仍可继续。"
            if latest_consumption and latest_consumption.status == "pending"
            else "最新学习结果同步失败，已有路径和资源仍可使用。"
            if latest_consumption and latest_consumption.status == "failed"
            else ""
        ),
    }

    return {
        "schema_version": "f4.dashboard-summary.v1",
        "read_only": True,
        "state": state,
        "course": course,
        "focus": _focus_copy(state, primary_task),
        "primary_task": _strategy_payload(primary_task, current=True) if primary_task else None,
        "knowledge_strategies": [
            _strategy_payload(item, current=index == 0) for index, item in enumerate(tasks[:3])
        ],
        "primary_action": _primary_action(
            state=state,
            course_id=resolved_course_id,
            primary_task=primary_task,
            restore_task=restore_task,
        ),
        "metrics": metrics,
        "review_summary": {
            "due_count": int(review.get("due_count") or 0),
            "items": list(review.get("items") or [])[:3],
        },
        "weak_summary": weak_summary,
        "aggregation": aggregation,
        "trend": _trend(aggregation_rows),
        "activity_trend": activity_points,
        "activity_summary": {
            "event_count": sum(item["event_count"] for item in activity_points),
            "active_days": len(activity_points),
        },
        "sourceEventIds": source_event_ids,
        "traceability": {
            "profile_snapshot_id": profile.get("snapshot_id"),
            "profile_version": profile_alignment["profile_snapshot"].get("version"),
            "diagnostic_report_id": report.id if report else None,
            "learning_path_id": path.get("id") if path else None,
            "compatibility_source": "active_learning_path" if compatibility_ready and report is None else None,
        },
        "profile_alignment": profile_alignment,
    }
