"""Explainable three-profile projection for the student golden loop."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from app.database import (
    DBAssessmentAbilityState,
    DBAssessmentAttempt,
    DBAssessmentGradingResult,
    DBAssessmentQuestionVersion,
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
    DBArtifact,
    DBKnowledgePoint,
    DBLearningEvent,
    DBLearningEventConsumption,
    DBLearningPath,
    DBPathNode,
    DBProfileEvidence,
    DBProfileSnapshot,
    DBReviewPlan,
    DBStudentProfile,
    DBUser,
)
from app.dashboard_summary import mastery_trend
from app.learning_aggregation import (
    AGGREGATION_PROCESSOR_VERSION,
    _event_observations,
)
from app.m5_resources import canonical_resource_type, resource_route
from app.legacy_adapter import LegacyDataAdapter, LegacyProfileMigrationError


class ProfileSummaryError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise ProfileSummaryError(code, message)


def _legacy_profile_report(session: Any, *, current_user: DBUser, course_id: str | None) -> dict[str, Any]:
    """Read migration evidence without making a page refresh a write."""
    try:
        return LegacyDataAdapter(session).profile_migration_report(
            current_user.public_id, course_id=course_id,
        )
    except LegacyProfileMigrationError as exc:
        return {
            "schema_version": "profile.legacy-migration-report.v1",
            "status": "not_available",
            "mapping_version": "legacy-profile-map.v1",
            "owner_public_id": current_user.public_id,
            "legacy_student_id": current_user.username,
            "course_id": course_id,
            "canonical_snapshot": {"id": None, "version": None, "kind": None},
            "confirmed_fields": [],
            "diff": [],
            "influence": [],
            "effective_projection": {},
            "read_only": True,
            "error": {"code": exc.code, "message": str(exc)},
            "boundary": "当前账号没有可读取的旧画像记录，页面不会因此创建新画像。",
        }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _latest_time(*values: datetime | None) -> str | None:
    present = [value for value in values if value is not None]
    return _iso(max(present)) if present else None


_DISPLAY_TZ = ZoneInfo("Asia/Shanghai")
_PERIOD_DAYS = {7, 30, 90}
_ACTIVITY_KINDS = {
    "assessment", "code", "conversation", "feynman", "note", "path", "resource", "review", "other",
}
_EVENT_LABELS = {
    "assessment_attempted": "完成一次学习作答",
    "assessment_correct": "完成一次正确作答",
    "assessment_incorrect": "完成一次错题诊断",
    "code_tests_passed": "代码任务通过检查",
    "formal_exam_submitted": "提交智能组卷",
    "feynman_submitted": "完成费曼复述",
    "misconception_decided": "确认错题原因",
    "note_created": "创建学习笔记",
    "note_version_saved": "保存笔记版本",
    "note_version_restored": "恢复笔记历史版本",
    "resource_completed": "完成学习资源",
    "review_completed": "完成到期复习",
    "user_marked_complete": "完成学习任务",
}
_EVENT_KIND_LABELS = {
    "assessment": "完成测评相关学习",
    "code": "完成代码实践",
    "conversation": "进行学习对话",
    "feynman": "进行费曼复述",
    "note": "更新学习笔记",
    "path": "更新学习安排",
    "resource": "学习课程资源",
    "review": "进行复习巩固",
    "other": "记录学习活动",
}


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _local_datetime(value: datetime) -> datetime:
    return _as_utc(value).astimezone(_DISPLAY_TZ)


def _utc_naive(value: datetime) -> datetime:
    return _as_utc(value).replace(tzinfo=None)


def _local_day_start_utc(day: Any) -> datetime:
    return datetime.combine(day, time.min, tzinfo=_DISPLAY_TZ).astimezone(timezone.utc).replace(tzinfo=None)


def _event_minutes(event: DBLearningEvent) -> float:
    payload = event.payload or {}
    for key in ("actual_minutes", "duration_minutes"):
        value = payload.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return float(value)
    seconds = payload.get("active_seconds")
    if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and seconds > 0:
        return float(seconds) / 60.0
    return 0.0


def _counts_as_active_learning(event: DBLearningEvent) -> bool:
    return bool(
        _event_minutes(event) > 0
        or event.completion_effect in {"progress", "complete"}
        or (event.mastery_eligible and event.evidence_status == "accepted")
    )


def _event_kind(event: DBLearningEvent) -> str:
    marker = f"{event.event_type} {event.object_type}".lower()
    if "note" in marker:
        return "note"
    if any(token in marker for token in ("assessment", "exam", "quiz", "misconception", "retest")):
        return "assessment"
    if any(token in marker for token in ("code", "sandbox", "run_attempt")):
        return "code"
    if "feynman" in marker:
        return "feynman"
    if "review" in marker:
        return "review"
    if any(token in marker for token in ("conversation", "chat", "tutor", "session")):
        return "conversation"
    if any(token in marker for token in ("artifact", "resource", "document")):
        return "resource"
    if any(token in marker for token in ("path", "chapter", "knowledge_point")):
        return "path"
    return "other"


def _human_event_label(event: DBLearningEvent) -> str:
    """Return a learner-facing action label without leaking event_type."""
    return _EVENT_LABELS.get(event.event_type) or _EVENT_KIND_LABELS.get(
        _event_kind(event), "记录学习活动",
    )


def _public_source(
    *,
    label: str,
    route: str = "",
    available: bool = False,
    kind: str = "evidence",
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    """Stable public source projection; internal ids remain outside this object."""
    item = {
        "label": label,
        "route": route,
        "available": bool(available and route),
        "kind": kind,
        "occurredAt": _iso(occurred_at),
    }
    return item


def _event_public_source(event: DBLearningEvent, *, course_id: str) -> dict[str, Any]:
    return _public_source(
        label=f"查看{_human_event_label(event)}记录",
        route=_route("/profile/history", course_id=course_id, event_id=event.id),
        available=True,
        kind="learning_event",
        occurred_at=event.occurred_at,
    )


def _human_source_label(source_type: str | None) -> str:
    return {
        "profile_snapshot": "课程画像快照",
        "assessment_attempt": "正式学习作答",
        "assessment_question": "课程测评题目",
        "assessment_ability_state": "诊断能力证据",
        "learning_event": "有效学习行为",
        "review_plan": "复习安排",
        "source_document": "课程来源文档",
        "source_ref": "课程原文片段",
    }.get(str(source_type or "").lower(), "课程学习证据")


def _route(path: str, **query: Any) -> str:
    values = {key: value for key, value in query.items() if value not in {None, ""}}
    return f"{path}?{urlencode(values)}" if values else path


def _event_target(
    event: DBLearningEvent, artifacts: dict[str, DBArtifact],
) -> dict[str, Any]:
    object_id = str(event.object_id or "")
    object_type = str(event.object_type or "").lower()
    course_id = event.course_id
    if object_type == "artifact" and object_id:
        artifact = artifacts.get(object_id)
        if artifact is None or artifact.status in {"archived", "withdrawn"}:
            return {"label": "原资源已不可用", "route": "", "available": False}
        resource_type = canonical_resource_type(artifact.artifact_type)
        route = resource_route(resource_type, artifact.id)
        if route:
            return {"label": f"打开{artifact.title or '学习资源'}", "route": route, "available": True}
    if object_type == "feynman_resource" and object_id:
        return {"label": "继续费曼复述", "route": f"/workspace/feynman/{object_id}", "available": True}
    if object_type == "assessment_exam_sitting" and object_id:
        return {"label": "查看组卷与报告", "route": _route("/workspace/assessment/exams", sitting_id=object_id, course_id=course_id), "available": True}
    if object_type in {"assessment_question", "assessment_question_version"} and object_id:
        return {"label": "查看题目与错因", "route": _route("/workspace/review/wrong-questions", question_id=object_id, course_id=course_id), "available": True}
    if object_type == "knowledge_point" and object_id:
        return {"label": "回到知识点", "route": _route("/workspace/review", knowledge_point_id=object_id, course_id=course_id), "available": True}
    if object_type == "chapter" and object_id:
        return {"label": "回到课程路径", "route": _route("/workspace/path", chapter_id=object_id, course_id=course_id), "available": True}
    if object_type in {"note", "note_version"} and object_id:
        return {"label": "打开笔记", "route": _route("/workspace/notes", note_id=object_id, course_id=course_id), "available": True}
    if object_type in {"document", "source_document"} and object_id:
        return {"label": "打开来源文档", "route": _route(f"/knowledge/documents/{object_id}", course_id=course_id), "available": True}
    if object_type in {"conversation", "tutor_context_session", "chat_session"} and object_id:
        return {"label": "继续对话", "route": _route("/learn", session_id=object_id, course_id=course_id), "available": True}
    if object_type in {"learning_path", "path_node"} and object_id:
        key = "path_id" if object_type == "learning_path" else "node_id"
        return {"label": "回到学习路径", "route": _route("/workspace/path", course_id=course_id, **{key: object_id}), "available": True}
    return {"label": "仅保留历史记录", "route": "", "available": False}


def _event_feedback(session: Any, event: DBLearningEvent) -> dict[str, Any]:
    """Expose canonical evidence-to-mastery feedback without writing state."""
    observations = []
    if event.evidence_status == "accepted" and event.mastery_eligible:
        observations = _event_observations(session, event)
    point_ids = list(dict.fromkeys(item[0] for item in observations))
    point_titles = list(dict.fromkeys(item[1] for item in observations))
    observation_rows = [
        {"knowledgePointId": point_id, "knowledgePointTitle": title, "value": round(float(value), 4)}
        for point_id, title, value in observations
    ]
    consumption = session.query(DBLearningEventConsumption).filter_by(
        learning_event_id=event.id,
        consumer="learning_aggregation",
        processor_version=AGGREGATION_PROCESSOR_VERSION,
    ).first()
    aggregation_status = consumption.status if consumption else "pending"
    aggregation_result = dict(consumption.result or {}) if consumption else {}
    profile_result = dict((aggregation_result.get("steps") or {}).get("profile_snapshot") or {})
    changed_concepts = dict(profile_result.get("changed_concepts") or {})
    if event.evidence_status == "accepted" and event.mastery_eligible:
        if observations:
            label = (
                "\u5df2\u8ba1\u5165\u638c\u63e1\u5ea6\uff08\u77e5\u8bc6\u70b9\uff1a"
                + "\u3001".join(point_titles)
                + "\uff09"
            ) if changed_concepts else "\u5df2\u6838\u9a8c\u638c\u63e1\u8bc1\u636e\uff08\u672c\u6b21\u6570\u503c\u672a\u53d8\u5316\uff09"
            reason = event.evidence_reason or "\u5df2\u901a\u8fc7\u670d\u52a1\u7aef\u8bc1\u636e\u6821\u9a8c"
        else:
            label = "\u5df2\u63a5\u53d7\uff0c\u4f46\u5c1a\u672a\u5f62\u6210\u638c\u63e1\u5ea6\u89c2\u5bdf\u503c"
            reason = event.evidence_reason or "\u7f3a\u5c11\u53ef\u8ba1\u7b97\u7684\u89c2\u5bdf\u503c\u6216\u77e5\u8bc6\u70b9\u5f15\u7528"
    else:
        reason = event.evidence_reason or "\u8be5\u884c\u4e3a\u672a\u5f62\u6210\u53ef\u8ba1\u5165\u638c\u63e1\u5ea6\u7684\u8bc1\u636e"
        label = reason if event.object_type != "external_url" else "\u5b66\u4e60\u8bb0\u5f55\uff0c\u4e0d\u76f4\u63a5\u6539\u53d8\u638c\u63e1\u5ea6"
    return {
        "status": event.evidence_status,
        "masteryEligible": bool(event.mastery_eligible),
        "completionEffect": event.completion_effect,
        "label": label,
        "reason": reason,
        "knowledgePointIds": point_ids,
        "knowledgePointTitles": point_titles,
        "observations": observation_rows,
        "masteryChanged": bool(changed_concepts),
        "changedConcepts": changed_concepts,
        "aggregationStatus": aggregation_status,
        "aggregationError": consumption.error_code if consumption else "",
        "sourceEventId": event.id,
    }


def _event_item(
    event: DBLearningEvent, *, course_titles: dict[str, str], artifacts: dict[str, DBArtifact],
    session: Any,
) -> dict[str, Any]:
    payload = event.payload or {}
    score = payload.get("score", payload.get("rubric_score"))
    detail = event.evidence_reason or "该动作已进入个人学习记录。"
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        detail = f"记录得分 {round(float(score) * 100)}%；{detail}"
    elif _event_minutes(event) > 0:
        detail = f"记录有效学习 {round(_event_minutes(event), 1)} 分钟；{detail}"
    label = _human_event_label(event)
    item = {
        "id": event.id,
        "label": label,
        "detail": detail,
        "kind": _event_kind(event),
        "eventType": event.event_type,
        "objectType": event.object_type or "",
        "objectId": event.object_id or "",
        "course": {
            "id": event.course_id,
            "title": course_titles.get(str(event.course_id), "未指定课程") if event.course_id else "未指定课程",
        },
        "occurredAt": _as_utc(event.occurred_at).isoformat() if event.occurred_at else None,
        "activeMinutes": round(_event_minutes(event), 1),
        "evidence": {
            "status": event.evidence_status,
            "masteryEligible": bool(event.mastery_eligible),
            "completionEffect": event.completion_effect,
            "label": "计入掌握证据" if event.mastery_eligible and event.evidence_status == "accepted" else "学习记录，不直接改变掌握度",
        },
        "target": _event_target(event, artifacts),
        "publicSource": _event_public_source(event, course_id=str(event.course_id or "")),
        "sourceEventIds": [event.id],
    }
    item["evidence"] = _event_feedback(session, event)
    return item


def _ability_dimensions(row: DBAssessmentAbilityState | None) -> list[dict[str, Any]]:
    labels = (("theory", "理论理解"), ("coding", "代码实践"), ("math", "数学推理"))
    theta = list(row.theta or [0.0, 0.0, 0.0]) if row else [0.0, 0.0, 0.0]
    std = list(row.theta_std or [1.0, 1.0, 1.0]) if row else [1.0, 1.0, 1.0]
    count = int(row.response_count or 0) if row else 0
    result = []
    for index, (key, label) in enumerate(labels):
        value = float(theta[index] if index < len(theta) else 0.0)
        uncertainty = float(std[index] if index < len(std) else 1.0)
        if count < 2:
            status = "证据积累中"
        elif value >= 0.35:
            status = "当前较稳定"
        elif value <= -0.35:
            status = "当前较薄弱"
        else:
            status = "仍需更多作答确认"
        result.append({
            "key": key,
            "label": label,
            "theta": round(value, 4),
            "theta_std": round(uncertainty, 4),
            "status": status,
            "confidence": "较高" if uncertainty <= 0.70 else "中等" if uncertainty <= 0.90 else "有限",
        })
    return result


def _evidence(
    *, label: str, value: str, source_type: str, source_id: str,
    observed_at: datetime | None, recommendation_impact: str,
) -> dict[str, Any]:
    return {
        "label": label,
        "value": value,
        "source_type": source_type,
        "source_id": source_id,
        "observed_at": _iso(observed_at),
        "recommendation_impact": recommendation_impact,
    }


def _referenced_knowledge_point_ids(value: Any, known_ids: set[str]) -> set[str]:
    """Extract explicit knowledge-point references from structured evidence."""
    found: set[str] = set()
    if isinstance(value, str):
        if value in known_ids:
            found.add(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in {
                "knowledge_point_id", "knowledge_point_ids", "primary_knowledge_point_id",
                "secondary_knowledge_point_ids", "concept_id", "concept_ids",
            }:
                found.update(_referenced_knowledge_point_ids(item, known_ids))
            elif isinstance(item, (dict, list, tuple, set)):
                found.update(_referenced_knowledge_point_ids(item, known_ids))
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            found.update(_referenced_knowledge_point_ids(item, known_ids))
    return found


def _knowledge_graph(
    *,
    session: Any,
    course_id: str,
    snapshot: dict[str, Any],
    snapshot_row: DBProfileSnapshot | None,
    attempts: list[DBAssessmentAttempt],
    versions: dict[str, DBAssessmentQuestionVersion],
    events: list[DBLearningEvent],
    profile_evidence_rows: list[DBProfileEvidence],
) -> dict[str, Any]:
    rows = (
        session.query(DBChapter, DBChapterKnowledgePoint, DBKnowledgePoint)
        .join(DBChapterKnowledgePoint, DBChapterKnowledgePoint.chapter_id == DBChapter.id)
        .join(DBKnowledgePoint, DBKnowledgePoint.id == DBChapterKnowledgePoint.knowledge_point_id)
        .filter(DBChapter.course_id == course_id, DBKnowledgePoint.status == "active")
        .order_by(DBChapter.position, DBKnowledgePoint.code, DBKnowledgePoint.id)
        .all()
    )
    point_rows: dict[str, tuple[DBChapter, DBKnowledgePoint]] = {}
    for chapter, _relation, point in rows:
        point_rows.setdefault(point.id, (chapter, point))
    known_ids = set(point_rows)

    categories: list[dict[str, Any]] = []
    category_indexes: dict[int, int] = {}
    for chapter, _point in point_rows.values():
        cluster_start = ((max(int(chapter.position or 1), 1) - 1) // 3) * 3 + 1
        if cluster_start not in category_indexes:
            category_indexes[cluster_start] = len(categories)
            categories.append({
                "id": f"chapters-{cluster_start}-{cluster_start + 2}",
                "name": f"第 {cluster_start}-{cluster_start + 2} 章",
            })

    mastered_ids = set(snapshot.get("mastered_knowledge_point_ids") or [])
    weak_ids = set(snapshot.get("weak_knowledge_point_ids") or [])
    attempts_by_point: dict[str, list[DBAssessmentAttempt]] = {point_id: [] for point_id in known_ids}
    for attempt in attempts:
        version = versions.get(attempt.question_version_id)
        if version is None:
            continue
        point_ids = _referenced_knowledge_point_ids(
            [version.primary_knowledge_point_id, version.secondary_knowledge_point_ids], known_ids,
        )
        for point_id in point_ids:
            attempts_by_point[point_id].append(attempt)

    events_by_point: dict[str, list[DBLearningEvent]] = {point_id: [] for point_id in known_ids}
    for event in events:
        if not event.mastery_eligible or event.evidence_status != "accepted":
            continue
        point_ids = set()
        if event.object_type == "knowledge_point" and event.object_id in known_ids:
            point_ids.add(event.object_id)
        point_ids.update(_referenced_knowledge_point_ids(event.context_ref, known_ids))
        point_ids.update(_referenced_knowledge_point_ids(event.payload, known_ids))
        for point_id in point_ids:
            events_by_point[point_id].append(event)

    profile_evidence_by_point: dict[str, list[DBProfileEvidence]] = {
        point_id: [] for point_id in known_ids
    }
    for row in profile_evidence_rows:
        point_ids = _referenced_knowledge_point_ids(
            [row.source_object_id, row.features], known_ids,
        )
        for point_id in point_ids:
            profile_evidence_by_point[point_id].append(row)

    graph_nodes: list[dict[str, Any]] = []
    latest_graph_time: datetime | None = None
    for point_id, (chapter, point) in point_rows.items():
        point_attempts = attempts_by_point[point_id]
        point_events = events_by_point[point_id]
        point_profile_evidence = profile_evidence_by_point[point_id]
        evidence: list[dict[str, Any]] = []
        behaviors: list[dict[str, Any]] = []
        evidence_times: list[datetime] = []
        snapshot_band = None
        if point_id in mastered_ids:
            snapshot_band = "mastered"
            evidence.append({
                "label": "课程画像快照",
                "value": "已掌握",
                "sourceType": "profile_snapshot",
                "sourceId": snapshot_row.id if snapshot_row else "",
                "observedAt": _iso(snapshot_row.created_at if snapshot_row else None),
                "sourceLabel": "课程画像快照",
                "source": _public_source(
                    label="查看课程画像依据",
                    route=_route("/profile/learning", course_id=course_id),
                    available=bool(snapshot_row),
                    kind="profile_snapshot",
                    occurred_at=snapshot_row.created_at if snapshot_row else None,
                ),
            })
            behaviors.append({
                "label": "课程画像记录为已掌握",
                "detail": "课程画像快照把该知识点标记为已掌握。",
                "occurredAt": _iso(snapshot_row.created_at if snapshot_row else None),
                "evidenceStatus": "accepted",
                "evidenceLabel": "计入掌握判断",
                "source": _public_source(
                    label="查看课程画像依据",
                    route=_route("/profile/learning", course_id=course_id),
                    available=bool(snapshot_row),
                    kind="profile_snapshot",
                    occurred_at=snapshot_row.created_at if snapshot_row else None,
                ),
            })
        if point_id in weak_ids:
            snapshot_band = "conflict" if snapshot_band else "weak"
            evidence.append({
                "label": "课程画像快照",
                "value": "当前薄弱",
                "sourceType": "profile_snapshot",
                "sourceId": snapshot_row.id if snapshot_row else "",
                "observedAt": _iso(snapshot_row.created_at if snapshot_row else None),
                "sourceLabel": "课程画像快照",
                "source": _public_source(
                    label="查看课程画像依据",
                    route=_route("/profile/learning", course_id=course_id),
                    available=bool(snapshot_row),
                    kind="profile_snapshot",
                    occurred_at=snapshot_row.created_at if snapshot_row else None,
                ),
            })
            behaviors.append({
                "label": "课程画像记录为当前薄弱",
                "detail": "课程画像快照把该知识点标记为当前薄弱，仍需后续证据确认。",
                "occurredAt": _iso(snapshot_row.created_at if snapshot_row else None),
                "evidenceStatus": "accepted",
                "evidenceLabel": "计入掌握判断",
                "source": _public_source(
                    label="查看课程画像依据",
                    route=_route("/profile/learning", course_id=course_id),
                    available=bool(snapshot_row),
                    kind="profile_snapshot",
                    occurred_at=snapshot_row.created_at if snapshot_row else None,
                ),
            })
        if snapshot_band and snapshot_row and snapshot_row.created_at:
            evidence_times.append(snapshot_row.created_at)

        scored_attempts = [
            item for item in point_attempts
            if item.grading_status == "graded" and item.score is not None
        ]
        attempt_score = (
            sum(float(item.score) for item in scored_attempts) / len(scored_attempts)
            if scored_attempts else None
        )
        for attempt in scored_attempts[:4]:
            evidence.append({
                "label": "正式学习作答",
                "value": f"得分 {round(float(attempt.score) * 100)}%",
                "sourceType": "assessment_attempt",
                "sourceId": attempt.id,
                "observedAt": _iso(attempt.submitted_at),
                "sourceLabel": "正式学习作答",
                "source": _public_source(
                    label="查看相关测评记录",
                    route=_route("/workspace/assessment/exams", course_id=course_id),
                    available=True,
                    kind="assessment_attempt",
                    occurred_at=attempt.submitted_at,
                ),
            })
            behaviors.append({
                "label": "完成正式学习作答",
                "detail": f"这次作答得分 {round(float(attempt.score) * 100)}%。",
                "occurredAt": _iso(attempt.submitted_at),
                "evidenceStatus": "accepted",
                "evidenceLabel": "计入掌握判断",
                "source": _public_source(
                    label="查看相关测评记录",
                    route=_route("/workspace/assessment/exams", course_id=course_id),
                    available=True,
                    kind="assessment_attempt",
                    occurred_at=attempt.submitted_at,
                ),
            })
            if attempt.submitted_at:
                evidence_times.append(attempt.submitted_at)
        for event in point_events[:4]:
            evidence.append({
                "label": "有效学习行为",
                "value": event.evidence_reason or f"{_human_event_label(event)}已记录。",
                "sourceType": "learning_event",
                "sourceId": event.id,
                "observedAt": _iso(event.occurred_at),
                "sourceLabel": _human_event_label(event),
                "source": _event_public_source(event, course_id=course_id),
            })
            behaviors.append({
                "label": _human_event_label(event),
                "detail": event.evidence_reason or "该行为已进入课程学习记录。",
                "occurredAt": _iso(event.occurred_at),
                "evidenceStatus": event.evidence_status or "unknown",
                "evidenceLabel": (
                    "计入掌握判断" if event.mastery_eligible and event.evidence_status == "accepted"
                    else "学习记录，不直接改变掌握度"
                ),
                "source": _event_public_source(event, course_id=course_id),
            })
            if event.occurred_at:
                evidence_times.append(event.occurred_at)
        for row in point_profile_evidence[:3]:
            evidence.append({
                "label": "画像判断依据",
                "value": row.evidence_summary or f"{_human_source_label(row.source_type)}已记录。",
                "sourceType": row.source_type,
                "sourceId": row.source_object_id or row.id,
                "observedAt": _iso(row.observed_at),
                "sourceLabel": _human_source_label(row.source_type),
                "source": _public_source(
                    label=f"查看{_human_source_label(row.source_type)}",
                    route=_route("/profile/learning", course_id=course_id),
                    available=True,
                    kind=str(row.source_type or "evidence"),
                    occurred_at=row.observed_at,
                ),
            })
            behaviors.append({
                "label": f"记录{_human_source_label(row.source_type)}",
                "detail": row.evidence_summary or "该依据已进入当前课程画像。",
                "occurredAt": _iso(row.observed_at),
                "evidenceStatus": row.status or "unknown",
                "evidenceLabel": "计入掌握判断" if row.status == "active" else "待确认",
                "source": _public_source(
                    label=f"查看{_human_source_label(row.source_type)}",
                    route=_route("/profile/learning", course_id=course_id),
                    available=True,
                    kind=str(row.source_type or "evidence"),
                    occurred_at=row.observed_at,
                ),
            })
            if row.observed_at:
                evidence_times.append(row.observed_at)

        conflict = snapshot_band == "conflict"
        if attempt_score is not None:
            if snapshot_band == "mastered" and attempt_score < 0.5:
                conflict = True
            if snapshot_band == "weak" and attempt_score >= 0.7:
                conflict = True
        if conflict:
            mastery_value = attempt_score if attempt_score is not None else 0.5
            mastery_band = "conflict"
            confidence = 0.35
            judgement = "现有证据方向不一致，暂不形成稳定掌握结论。"
        else:
            prior = 0.82 if snapshot_band == "mastered" else 0.34 if snapshot_band == "weak" else None
            if prior is not None and attempt_score is not None:
                mastery_value = round((prior + attempt_score) / 2, 4)
            else:
                mastery_value = attempt_score if attempt_score is not None else prior
            if mastery_value is None:
                mastery_band = "unknown"
                confidence = 0.0
                judgement = "尚无可用于判断掌握度的学习证据。"
            else:
                mastery_band = (
                    "mastered" if mastery_value >= 0.75
                    else "developing" if mastery_value >= 0.55
                    else "weak"
                )
                confidence = min(
                    0.95,
                    (0.68 if snapshot_band else 0.48)
                    + min(len(scored_attempts), 4) * 0.07
                    + min(len(point_events), 3) * 0.03
                    + min(len(point_profile_evidence), 2) * 0.03,
                )
                judgement = {
                    "mastered": "当前证据支持稳定掌握，可进入后续关联知识点。",
                    "developing": "已形成基础理解，仍需一次应用任务确认迁移能力。",
                    "weak": "当前证据显示仍有薄弱环节，建议先完成针对性学习任务。",
                }[mastery_band]

        last_evidence_at = max(evidence_times) if evidence_times else None
        if last_evidence_at and (latest_graph_time is None or last_evidence_at > latest_graph_time):
            latest_graph_time = last_evidence_at
        cluster_start = ((max(int(chapter.position or 1), 1) - 1) // 3) * 3 + 1
        graph_nodes.append({
            "id": point.id,
            "name": point.title,
            "code": point.code,
            "chapter": {"id": chapter.id, "title": chapter.title, "position": chapter.position},
            "category": category_indexes[cluster_start],
            "categoryName": categories[category_indexes[cluster_start]]["name"],
            "mastery": round(float(mastery_value), 4) if mastery_value is not None else None,
            "masteryBand": mastery_band,
            "evidenceCount": len(evidence),
            "lastEvidenceAt": _iso(last_evidence_at),
            "sourceEventIds": [event.id for event in point_events],
            "confidence": round(confidence, 2),
            "judgement": judgement,
            "evidence": evidence,
            "behaviors": behaviors,
            "behaviorCount": len(behaviors),
            "nextAction": {
                "title": (
                    "核对冲突证据" if mastery_band == "conflict"
                    else "完成一次短诊断" if mastery_band == "unknown"
                    else "继续关联知识点" if mastery_band == "mastered"
                    else "开始针对性学习"
                ),
                "route": f"/workspace?course_id={course_id}&knowledge_point_id={point.id}",
                "reason": (
                    "先补充或核对有效证据，再更新画像判断。"
                    if mastery_band in {"unknown", "conflict"}
                    else "根据当前掌握区间进入对应强度的下一项学习任务。"
                ),
            },
        })

    graph_edges = []
    for point_id, (_chapter, point) in point_rows.items():
        for prerequisite_id in point.prerequisites or []:
            if prerequisite_id in known_ids:
                graph_edges.append({
                    "source": prerequisite_id,
                    "target": point_id,
                    "relation": "prerequisite",
                    "label": "先修",
                    "lineStyle": {"type": "solid"},
                })
    conflict_count = sum(node["masteryBand"] == "conflict" for node in graph_nodes)
    evidence_node_count = sum(node["masteryBand"] != "unknown" for node in graph_nodes)
    status = "evidence_conflict" if conflict_count else "no_evidence" if not evidence_node_count else "normal"
    return {
        "schemaVersion": "f4.profile-knowledge-graph.v1",
        "status": status,
        "updatedAt": _iso(latest_graph_time),
        "nodes": graph_nodes,
        "edges": graph_edges,
        "categories": categories,
        "summary": {
            "nodeCount": len(graph_nodes),
            "evidenceNodeCount": evidence_node_count,
            "unknownNodeCount": len(graph_nodes) - evidence_node_count,
            "conflictNodeCount": conflict_count,
        },
        "boundary": "只有正式作答、代码、实验、费曼、正式组卷和有效复习等已接受证据参与判断；浏览、搜索、展开和选择节点不改变掌握度。",
    }


def build_profile_summary(
    session: Any, *, current_user: DBUser, course_id: str,
) -> dict[str, Any]:
    course = session.query(DBCourse).filter_by(id=course_id).first()
    if course is None:
        _fail("course_not_found", "课程不存在")
    from course_catalog import course_is_selectable
    if not course_is_selectable(session, course):
        _fail("course_unavailable", "课程当前不可用")
    if (
        course.visibility != "public"
        and course.owner_public_id != current_user.public_id
        and str(getattr(current_user, "role", "")) != "admin"
    ):
        _fail("course_unavailable", "当前课程画像上下文暂不可用")

    snapshot_row = (
        session.query(DBProfileSnapshot)
        .filter_by(owner_public_id=current_user.public_id)
        .order_by(DBProfileSnapshot.created_at.desc(), DBProfileSnapshot.id.desc())
        .all()
    )
    snapshot_row = next(
        (row for row in snapshot_row if (row.snapshot or {}).get("course_id") in {None, course_id}),
        None,
    )
    snapshot = dict(snapshot_row.snapshot or {}) if snapshot_row else {}
    legacy_migration = _legacy_profile_report(
        session, current_user=current_user, course_id=course_id,
    )
    ability = session.query(DBAssessmentAbilityState).filter_by(
        owner_public_id=current_user.public_id,
        course_scope=course_id,
    ).first()
    dimensions = _ability_dimensions(ability)
    all_attempts = session.query(DBAssessmentAttempt).filter_by(
        owner_public_id=current_user.public_id,
        course_id=course_id,
    ).order_by(DBAssessmentAttempt.submitted_at.desc(), DBAssessmentAttempt.id.desc()).all()
    attempts = [item for item in all_attempts if item.mode == "diagnostic"]
    attempt_ids = [item.id for item in attempts]
    grading_rows = session.query(DBAssessmentGradingResult).filter(
        DBAssessmentGradingResult.attempt_id.in_(attempt_ids),
    ).all() if attempt_ids else []
    grading_by_attempt = {item.attempt_id: item for item in grading_rows}
    version_ids = [item.question_version_id for item in all_attempts]
    versions = {
        item.id: item for item in session.query(DBAssessmentQuestionVersion).filter(
            DBAssessmentQuestionVersion.id.in_(version_ids),
        ).all()
    } if version_ids else {}

    weak_references = list(
        snapshot.get("weak_knowledge_point_ids")
        or snapshot.get("weak_points")
        or []
    )
    kp_ids = set(snapshot.get("mastered_knowledge_point_ids") or [])
    kp_ids.update(weak_references)
    kp_ids.update(
        version.primary_knowledge_point_id for version in versions.values()
        if version.primary_knowledge_point_id
    )
    knowledge_points = {
        row.id: row.title for row in session.query(DBKnowledgePoint).filter(
            DBKnowledgePoint.id.in_(kp_ids),
        ).all()
    } if kp_ids else {}
    mastered = [knowledge_points.get(item, item) for item in snapshot.get("mastered_knowledge_point_ids") or []]
    weak = [knowledge_points.get(item, item) for item in weak_references]
    correct_count = sum(item.correct is True for item in attempts)
    scored_count = sum(item.correct is not None for item in attempts)
    strongest = max(dimensions, key=lambda item: item["theta"])
    weakest = min(dimensions, key=lambda item: item["theta"])

    events = session.query(DBLearningEvent).filter_by(
        owner_public_id=current_user.public_id,
        course_id=course_id,
    ).order_by(DBLearningEvent.occurred_at.desc(), DBLearningEvent.id.desc()).all()
    event_counts: dict[str, int] = {}
    for event in events:
        event_counts[event.event_type] = event_counts.get(event.event_type, 0) + 1
    reviews = session.query(DBReviewPlan).filter_by(student_id=current_user.username).order_by(
        DBReviewPlan.priority, DBReviewPlan.id,
    ).all()
    path = session.query(DBLearningPath).filter(
        DBLearningPath.owner_public_id == current_user.public_id,
        DBLearningPath.course_id == course_id,
        DBLearningPath.status.in_(("active", "paused")),
    ).order_by(DBLearningPath.updated_at.desc(), DBLearningPath.id.desc()).first()
    nodes = session.query(DBPathNode).filter_by(learning_path_id=path.id).order_by(
        DBPathNode.sequence,
    ).all() if path else []
    next_node = next((item for item in nodes if item.status not in {"completed", "skipped"}), None)
    next_action = {
        "title": next_node.title if next_node else "回到学习空间继续当前章节",
        "route": f"/workspace?node_id={next_node.id}" if next_node else f"/workspace?course_id={course_id}",
        "reason": "优先使用已确认路径中的下一项任务，不在画像页另建计划。",
    }

    profile_evidence_rows = session.query(DBProfileEvidence).filter_by(
        owner_public_id=current_user.public_id,
        status="active",
    ).order_by(DBProfileEvidence.observed_at.desc(), DBProfileEvidence.id.desc()).all()
    misconception = dict(snapshot.get("misconception") or {})
    latest_attempt = attempts[0] if attempts else None
    latest_event = events[0] if events else None

    skill_evidence = []
    if snapshot_row:
        skill_evidence.append(_evidence(
            label="课程掌握快照",
            value=f"总体掌握度 {round(float(snapshot.get('mastery') or 0) * 100)}%",
            source_type="profile_snapshot",
            source_id=snapshot_row.id,
            observed_at=snapshot_row.created_at,
            recommendation_impact="已掌握知识点用于避免重复学习，薄弱知识点提高后续练习优先级。",
        ))
    if ability:
        skill_evidence.append(_evidence(
            label="短诊断三维能力",
            value=f"{ability.response_count} 次有效作答，{strongest['label']}当前证据最高",
            source_type="assessment_ability_state",
            source_id=ability.id,
            observed_at=ability.updated_at,
            recommendation_impact=f"{weakest['label']}的不确定性会提高相关解释与练习的推荐权重。",
        ))
    if latest_attempt:
        grade = grading_by_attempt.get(latest_attempt.id)
        attempt_score = latest_attempt.score
        attempt_result = (
            f"{'答对' if latest_attempt.correct else '答错'} · {round(float(attempt_score) * 100)} 分"
            if attempt_score is not None
            else "已作答 · 待评分"
        )
        skill_evidence.append(_evidence(
            label="最近一次诊断作答",
            value=attempt_result,
            source_type="assessment_attempt",
            source_id=latest_attempt.id,
            observed_at=latest_attempt.submitted_at,
            recommendation_impact="最近作答结果用于修正能力估计，不直接替代课程总评。" if grade else "作答已记录，等待完整评分证据。",
        ))

    cognitive_evidence = []
    if misconception and snapshot_row:
        cognitive_evidence.append(_evidence(
            label="已确认概念误区",
            value=str(misconception.get("label") or "已记录误区"),
            source_type="profile_snapshot",
            source_id=snapshot_row.id,
            observed_at=snapshot_row.created_at,
            recommendation_impact="优先推荐对比、反例和来源核查任务，避免继续强化错误概念。",
        ))
    if ability:
        cognitive_evidence.append(_evidence(
            label="判断置信边界",
            value=f"{weakest['label']}置信度{weakest['confidence']}，标准差 {weakest['theta_std']:.2f}",
            source_type="assessment_ability_state",
            source_id=ability.id,
            observed_at=ability.updated_at,
            recommendation_impact="证据不足时继续安排短任务收集证据，不给出固定能力标签。",
        ))
    for row in profile_evidence_rows[:2]:
        cognitive_evidence.append(_evidence(
            label="画像证据",
            value=row.evidence_summary or row.source_type,
            source_type=row.source_type,
            source_id=row.source_object_id or row.id,
            observed_at=row.observed_at,
            recommendation_impact="该证据仅在有效状态和当前版本下参与建议。",
        ))

    behavior_evidence = []
    if latest_event:
        behavior_evidence.append(_evidence(
            label="课程学习事件",
            value=f"累计 {len(events)} 条，最近为 {latest_event.event_type}",
            source_type="learning_event",
            source_id=latest_event.id,
            observed_at=latest_event.occurred_at,
            recommendation_impact="近期活动与未完成任务共同决定下一步入口，不把停留时间等同掌握。",
        ))
    if attempts:
        behavior_evidence.append(_evidence(
            label="诊断参与",
            value=f"已提交 {len(attempts)} 题，其中 {scored_count} 题已有客观结果",
            source_type="assessment_attempt",
            source_id=latest_attempt.id,
            observed_at=latest_attempt.submitted_at,
            recommendation_impact="完成诊断后优先转入学习任务，而不是继续无限出题。",
        ))
    if reviews:
        behavior_evidence.append(_evidence(
            label="复习队列",
            value=f"{len(reviews)} 项待复习，最高优先级 {min(float(item.priority or 1.0) for item in reviews):.2f}",
            source_type="review_plan",
            source_id=str(reviews[0].id),
            observed_at=reviews[0].created_at,
            recommendation_impact="复习到期和优先级会与今日学习任务共同排序。",
        ))

    sections = [
        {
            "key": "skill",
            "title": "技能画像",
            "question": "会什么",
            "headline": f"已掌握 {len(mastered)} 个课程知识点；{strongest['label']}当前证据相对更充分",
            "strengths": mastered or ["已有课程参与和诊断证据"],
            "difficulties": weak or ([f"{weakest['label']}仍需更多证据确认"] if ability else []),
            "next_step": next_action,
            "evidence": skill_evidence,
            "updated_at": _latest_time(snapshot_row.created_at if snapshot_row else None, ability.updated_at if ability else None, latest_attempt.submitted_at if latest_attempt else None),
        },
        {
            "key": "cognitive",
            "title": "认知画像",
            "question": "哪里困难",
            "headline": str(misconception.get("label") or "当前没有足够证据确认具体误区"),
            "strengths": [f"{correct_count}/{scored_count} 道诊断题作答正确"] if scored_count else ["正在积累诊断证据"],
            "difficulties": [str(misconception.get("label"))] if misconception else ["证据不足，暂不形成固定判断"],
            "next_step": {
                **next_action,
                "reason": "误区与能力不确定性优先影响解释方式、对比案例和练习难度。",
            },
            "evidence": cognitive_evidence,
            "updated_at": _latest_time(snapshot_row.created_at if snapshot_row else None, ability.updated_at if ability else None),
        },
        {
            "key": "behavior",
            "title": "行为画像",
            "question": "下一步做什么",
            "headline": f"已记录 {len(events)} 条课程事件和 {len(attempts)} 次诊断作答",
            "strengths": ["已进入主课程并持续产生可追溯学习证据"] if events or attempts else ["尚未形成稳定学习行为证据"],
            "difficulties": [f"仍有 {len(reviews)} 项复习任务"] if reviews else ["当前没有到期复习项"],
            "next_step": next_action,
            "evidence": behavior_evidence,
            "updated_at": _latest_time(latest_event.occurred_at if latest_event else None, latest_attempt.submitted_at if latest_attempt else None, path.updated_at if path else None),
        },
    ]
    knowledge_graph = _knowledge_graph(
        session=session,
        course_id=course_id,
        snapshot=snapshot,
        snapshot_row=snapshot_row,
        attempts=all_attempts,
        versions=versions,
        events=events,
        profile_evidence_rows=profile_evidence_rows,
    )
    return {
        "schema_version": "r3.profile-summary.v1",
        "course": {"id": course.id, "title": course.title, "version": course.version},
        "owner": {"public_id": current_user.public_id, "username": current_user.username},
        "summary": {
            "title": "会什么、哪里困难、下一步做什么",
            "diagnostic_response_count": int(ability.response_count or 0) if ability else 0,
            "diagnostic_attempt_count": len(attempts),
            "evidence_count": sum(len(item["evidence"]) for item in sections),
            "next_action": next_action,
        },
        "sections": sections,
        "knowledge_graph": knowledge_graph,
        "legacy_migration": legacy_migration,
        "recommendation_inputs": [
            "已掌握与薄弱知识点", "短诊断三维能力与不确定性", "已确认误区",
            "课程学习事件", "正式路径与复习队列", "旧画像字段映射与迁移版本",
        ],
        "boundary": "三画像是基于当前课程事实的可更新摘要，不是课程总评、人格标签、真人专家认证或自动高风险决定；旧画像迁移只作为带版本的来源证据。",
    }


def build_personal_activity(
    session: Any,
    *,
    current_user: DBUser,
    course_id: str | None = None,
    days: int = 30,
    offset: int = 0,
    limit: int = 20,
    kind: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Project profile and history facts without mutating learning state."""

    if days not in _PERIOD_DAYS:
        _fail("activity_period_invalid", "统计周期只支持7天、30天或90天")
    if kind is not None and kind not in _ACTIVITY_KINDS:
        _fail("activity_kind_invalid", "学习记录类型不可识别")
    offset = max(0, int(offset))
    limit = max(1, min(int(limit), 100))

    course: DBCourse | None = None
    if course_id:
        from course_catalog import course_is_selectable
        course = session.query(DBCourse).filter_by(id=course_id).first()
        if course is None:
            _fail("course_not_found", "课程不存在")
        if (
            course.visibility != "public"
            and course.owner_public_id != current_user.public_id
            and str(getattr(current_user, "role", "")) != "admin"
        ):
            _fail("course_unavailable", "当前课程画像上下文暂不可用")
        if not course_is_selectable(session, course):
            _fail("course_unavailable", "当前课程已停止发布或没有可用学习资料")

    utc_now = _as_utc(now or datetime.now(timezone.utc))
    local_now = utc_now.astimezone(_DISPLAY_TZ)
    today = local_now.date()
    period_start_day = today - timedelta(days=days - 1)
    heatmap_start_day = today - timedelta(days=29)
    query_start_day = min(period_start_day, heatmap_start_day, today - timedelta(days=6))
    query_start = _local_day_start_utc(query_start_day)
    query_end = utc_now.replace(tzinfo=None)

    event_query = session.query(DBLearningEvent).filter(
        DBLearningEvent.owner_public_id == current_user.public_id,
        DBLearningEvent.occurred_at >= query_start,
        DBLearningEvent.occurred_at <= query_end,
    )
    if course_id:
        event_query = event_query.filter(DBLearningEvent.course_id == course_id)
    events = event_query.order_by(
        DBLearningEvent.occurred_at.desc(), DBLearningEvent.id.desc(),
    ).all()

    event_course_ids = {str(event.course_id) for event in events if event.course_id}
    if course_id:
        event_course_ids.add(course_id)
    from course_catalog import course_is_selectable
    course_rows = session.query(DBCourse).filter(DBCourse.id.in_(event_course_ids)).all() if event_course_ids else []
    course_rows = [row for row in course_rows if course_is_selectable(session, row)]
    course_titles = {row.id: row.title for row in course_rows}
    artifact_ids = {
        str(event.object_id) for event in events
        if event.object_type == "artifact" and event.object_id
    }
    artifact_rows = session.query(DBArtifact).filter(
        DBArtifact.id.in_(artifact_ids), DBArtifact.owner_public_id == current_user.public_id,
    ).all() if artifact_ids else []
    artifacts = {row.id: row for row in artifact_rows}

    period_events = [
        event for event in events
        if event.occurred_at and _local_datetime(event.occurred_at).date() >= period_start_day
    ]
    filtered_events = [event for event in period_events if kind is None or _event_kind(event) == kind]
    page_events = filtered_events[offset:offset + limit]

    duration_events = [event for event in period_events if _event_minutes(event) > 0]
    today_duration_events = [
        event for event in duration_events if _local_datetime(event.occurred_at).date() == today
    ]
    week_start = today - timedelta(days=6)
    week_duration_events = [
        event for event in duration_events if _local_datetime(event.occurred_at).date() >= week_start
    ]

    heatmap_events = [
        event for event in events
        if event.occurred_at
        and _local_datetime(event.occurred_at).date() >= heatmap_start_day
        and _counts_as_active_learning(event)
    ]
    heatmap_by_day: dict[Any, list[DBLearningEvent]] = {}
    for event in heatmap_events:
        heatmap_by_day.setdefault(_local_datetime(event.occurred_at).date(), []).append(event)
    heatmap = []
    for index in range(30):
        day = heatmap_start_day + timedelta(days=index)
        day_events = heatmap_by_day.get(day, [])
        heatmap.append({
            "date": day.isoformat(),
            "eventCount": len(day_events),
            "activeMinutes": round(sum(_event_minutes(event) for event in day_events), 1),
            "sourceEventIds": [event.id for event in day_events],
        })

    streak_days = 0
    cursor = today
    while heatmap_by_day.get(cursor):
        streak_days += 1
        cursor -= timedelta(days=1)

    trend_query = session.query(DBLearningEventConsumption, DBLearningEvent).join(
        DBLearningEvent,
        DBLearningEvent.id == DBLearningEventConsumption.learning_event_id,
    ).filter(
        DBLearningEventConsumption.consumer == "learning_aggregation",
        DBLearningEvent.owner_public_id == current_user.public_id,
        DBLearningEvent.occurred_at >= _local_day_start_utc(period_start_day),
        DBLearningEvent.occurred_at <= query_end,
    )
    if course_id:
        trend_query = trend_query.filter(DBLearningEvent.course_id == course_id)
    trend_rows = trend_query.order_by(
        DBLearningEvent.occurred_at.desc(),
        DBLearningEventConsumption.created_at.desc(),
    ).all()
    trend = [
        {
            "label": point["label"],
            "value": point["value"],
            "sourceEventId": point["source_event_id"],
            "occurredAt": point["occurred_at"],
        }
        for point in mastery_trend(trend_rows, limit=days)
    ]

    student_profile = session.query(DBStudentProfile).filter_by(
        student_id=current_user.username,
    ).first()
    full_profile = build_profile_summary(
        session, current_user=current_user, course_id=course_id,
    ) if course_id else None
    legacy_migration = _legacy_profile_report(
        session, current_user=current_user, course_id=course_id,
    )
    profile_sections = [
        {
            "key": section["key"],
            "title": section["title"],
            "headline": section["headline"],
            "updatedAt": section["updated_at"],
            "nextAction": section["next_step"],
        }
        for section in (full_profile or {}).get("sections", [])
    ]

    period_source_ids = [event.id for event in period_events]
    active_days = len({
        _local_datetime(event.occurred_at).date()
        for event in period_events if event.occurred_at and _counts_as_active_learning(event)
    })
    mastery_events = [
        event for event in period_events
        if event.mastery_eligible and event.evidence_status == "accepted"
    ]
    period_minutes = round(sum(_event_minutes(event) for event in duration_events), 1)
    latest_item = _event_item(
        filtered_events[0], course_titles=course_titles, artifacts=artifacts, session=session,
    ) if filtered_events else None
    period = {
        "days": days,
        "startDate": period_start_day.isoformat(),
        "endDate": today.isoformat(),
        "timezone": "Asia/Shanghai",
        "generatedAt": utc_now.isoformat(),
    }
    calculation = {
        "duration": "只累计学习事件明确上报的actual_minutes、duration_minutes或active_seconds；页面停留和普通点击不计时。",
        "activity": "热力图与连续学习只统计有明确时长、完成效果或已接受掌握证据的事件。",
        "trend": "趋势来自已处理学习事件聚合结果中的真实掌握均值；无结果时不补线。",
    }
    return {
        "schemaVersion": "f8.personal-activity.v1",
        "readOnly": True,
        "owner": {
            "publicId": current_user.public_id,
            "username": current_user.username,
            "displayName": current_user.display_name or current_user.username,
            "major": student_profile.major if student_profile else "",
            "favoriteCount": len(student_profile.favorites or []) if student_profile else 0,
            "memberSince": _iso(current_user.created_at),
        },
        "course": ({"id": course.id, "title": course.title, "version": course.version} if course else None),
        "courses": [
            {"id": row.id, "title": row.title, "version": row.version}
            for row in sorted(course_rows, key=lambda item: item.title)
        ],
        "period": period,
        "calculation": calculation,
        "metrics": {
            "todayMinutes": {
                "value": round(sum(_event_minutes(event) for event in today_duration_events), 1),
                "sourceEventIds": [event.id for event in today_duration_events],
            },
            "weekMinutes": {
                "value": round(sum(_event_minutes(event) for event in week_duration_events), 1),
                "sourceEventIds": [event.id for event in week_duration_events],
            },
            "periodMinutes": {
                "value": period_minutes,
                "sourceEventIds": [event.id for event in duration_events],
            },
            "streakDays": {
                "value": streak_days,
                "sourceEventIds": [
                    event.id for day, rows in heatmap_by_day.items()
                    if today - timedelta(days=max(streak_days - 1, 0)) <= day <= today
                    for event in rows
                ] if streak_days else [],
            },
        },
        "heatmap": {
            "startDate": heatmap_start_day.isoformat(),
            "endDate": today.isoformat(),
            "days": heatmap,
            "sourceEventIds": [event.id for event in heatmap_events],
        },
        "trend": {
            "points": trend,
            "activityPoints": [
                {
                    "label": item["date"][5:10],
                    "date": item["date"],
                    "eventCount": item["eventCount"],
                    "activeMinutes": item["activeMinutes"],
                }
                for item in heatmap if item["eventCount"]
            ],
            "sourceEventIds": [point["sourceEventId"] for point in trend],
        },
        "activity": {
            "items": [
                _event_item(event, course_titles=course_titles, artifacts=artifacts, session=session)
                for event in page_events
            ],
            "total": len(filtered_events),
            "offset": offset,
            "limit": limit,
            "hasMore": offset + len(page_events) < len(filtered_events),
            "kinds": [
                {"value": value, "label": label}
                for value, label in (
                    ("assessment", "测评与练习"), ("resource", "学习资源"),
                    ("code", "代码实践"), ("feynman", "费曼复述"),
                    ("review", "复习巩固"), ("note", "学习笔记"),
                    ("conversation", "学习对话"), ("path", "路径与知识点"),
                    ("other", "其他记录"),
                )
            ],
        },
        "profile": {
            "status": "normal" if profile_sections else "no_evidence",
            "sections": profile_sections,
            "legacyMigration": legacy_migration,
            "fullProfileRoute": _route("/profile/learning", course_id=course_id),
            "sourceEventIds": list(dict.fromkeys(
                event.id for event in period_events
                if event.mastery_eligible and event.evidence_status == "accepted"
            )),
        },
        "report": {
            "title": f"近{days}天学习报告",
            "summary": f"记录{active_days}个有效学习日，共{period_minutes:g}分钟，形成{len(mastery_events)}条可用于掌握判断的证据。",
            "period": period,
            "highlights": [
                {"label": "有效学习日", "value": active_days, "unit": "天"},
                {"label": "明确学习时长", "value": period_minutes, "unit": "分钟"},
                {"label": "掌握证据", "value": len(mastery_events), "unit": "条"},
            ],
            "sourceEventIds": period_source_ids,
            "primaryAction": (latest_item or {}).get("target") or {
                "label": "查看学习路径",
                "route": _route("/workspace/path", course_id=course_id),
                "available": True,
            },
            "profileRoute": _route("/profile/learning", course_id=course_id),
            "historyRoute": _route("/profile/history", course_id=course_id, days=days),
        },
        "boundary": "普通浏览、筛选、展开和报告查看均为只读；旧画像迁移差异只读展示；只有符合现有证据合同的真实学习行为才能改变掌握度、路径或复习安排。",
    }
