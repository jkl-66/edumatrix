"""Explainable class analytics derived from canonical learning facts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from app.course_governance import CourseGovernanceError, require_manager
from app.database import (
    DBAssessmentAttempt, DBLearningEvent, DBLearningPath, DBPathNode,
    DBTeachingAnalyticsReport, DBTeachingClass, DBTeachingClassMember, DBUser,
)

METRIC_VERSION = "teaching-demo-metrics-1.0.0"
MIN_SAMPLE = 3
BURDEN_THRESHOLD_MINUTES = 180

METRIC_DEFINITIONS = (
    {
        "key": "participation_rate", "name": "周期参与率", "unit": "ratio",
        "formula": "周期内至少产生 1 条规范学习事件的活动学员数 / 活动学员总数",
        "sources": ["learning_events", "teaching_class_members"],
        "threshold": 0.70, "threshold_basis": "比赛演示阈值：低于 70% 提示教师检查触达，不来自真实企业生产数据",
    },
    {
        "key": "assessment_average", "name": "测评平均得分", "unit": "ratio",
        "formula": "周期内已评分规范测评尝试 score 的算术平均值",
        "sources": ["assessment_attempts"],
        "threshold": 0.60, "threshold_basis": "比赛演示阈值：低于 60% 提示补充练习，不代表正式考试及格线",
    },
    {
        "key": "path_completion_rate", "name": "路径节点完成率", "unit": "ratio",
        "formula": "班级学员课程路径中 completed 节点数 / 全部路径节点数",
        "sources": ["learning_paths", "path_nodes"],
        "threshold": 0.65, "threshold_basis": "比赛演示阈值：用于发现推进停滞，不来自真实学校考核制度",
    },
    {
        "key": "path_burden_minutes", "name": "待完成路径负担", "unit": "minutes",
        "formula": "每名学员 pending/in_progress 节点 estimate_max_minutes 之和，再取班级平均值",
        "sources": ["learning_paths", "path_nodes"],
        "threshold": BURDEN_THRESHOLD_MINUTES,
        "threshold_basis": "比赛演示阈值：待完成预计时长超过 180 分钟标记高负担，不是医学或企业人效结论",
    },
)


def _class_for_manager(db: Any, class_id: str, actor: DBUser) -> DBTeachingClass:
    classroom = db.get(DBTeachingClass, class_id)
    if classroom is None:
        raise CourseGovernanceError("analytics_class_unknown", "teaching class does not exist")
    require_manager(db, classroom.course_id, actor)
    return classroom


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds") + ("Z" if value.tzinfo is None else "")


def _metric(key: str, value: float | None, *, numerator: int | float, denominator: int | float,
            sample_size: int) -> dict[str, Any]:
    definition = next(item for item in METRIC_DEFINITIONS if item["key"] == key)
    threshold = float(definition["threshold"])
    if value is None:
        state = "unavailable"
    elif key == "path_burden_minutes":
        state = "attention" if value > threshold else "within_demo_threshold"
    else:
        state = "attention" if value < threshold else "within_demo_threshold"
    return {
        **definition, "value": round(value, 4) if value is not None else None,
        "numerator": numerator, "denominator": denominator, "sample_size": sample_size,
        "minimum_sample": MIN_SAMPLE, "sample_state": "sufficient" if sample_size >= MIN_SAMPLE else "small_sample",
        "state": state,
    }


def build_snapshot(db: Any, *, actor: DBUser, class_id: str, period_start: datetime,
                   period_end: datetime) -> dict[str, Any]:
    classroom = _class_for_manager(db, class_id, actor)
    if period_end <= period_start:
        raise CourseGovernanceError("analytics_period_invalid", "period end must be after period start")
    members = db.query(DBTeachingClassMember).filter_by(class_id=class_id, role="student", status="active").all()
    owners = [row.user_public_id for row in members]
    events = db.query(DBLearningEvent).filter(
        DBLearningEvent.course_id == classroom.course_id,
        DBLearningEvent.owner_public_id.in_(owners or [""]),
        DBLearningEvent.occurred_at >= period_start, DBLearningEvent.occurred_at < period_end,
    ).all()
    attempts = db.query(DBAssessmentAttempt).filter(
        DBAssessmentAttempt.course_id == classroom.course_id,
        DBAssessmentAttempt.owner_public_id.in_(owners or [""]),
        DBAssessmentAttempt.submitted_at >= period_start, DBAssessmentAttempt.submitted_at < period_end,
        DBAssessmentAttempt.grading_status == "graded",
    ).all()
    paths = db.query(DBLearningPath).filter(
        DBLearningPath.course_id == classroom.course_id,
        DBLearningPath.owner_public_id.in_(owners or [""]),
    ).all()
    nodes = db.query(DBPathNode).filter(DBPathNode.learning_path_id.in_([p.id for p in paths] or [""])).all()
    path_owner = {p.id: p.owner_public_id for p in paths}
    active_owners = {event.owner_public_id for event in events if event.owner_public_id}
    learner_rows = []
    for owner in owners:
        own_events = [event for event in events if event.owner_public_id == owner]
        own_attempts = [attempt for attempt in attempts if attempt.owner_public_id == owner]
        own_nodes = [node for node in nodes if path_owner.get(node.learning_path_id) == owner]
        pending = [node for node in own_nodes if node.status in {"pending", "in_progress"}]
        burden = sum(max(0, int(node.estimate_max_minutes or 0)) for node in pending)
        completed = sum(1 for node in own_nodes if node.status == "completed")
        learner_rows.append({
            "learner_public_id": owner, "event_count": len(own_events), "assessment_count": len(own_attempts),
            "assessment_average": round(sum(a.score for a in own_attempts) / len(own_attempts), 4) if own_attempts else None,
            "path_node_count": len(own_nodes), "completed_node_count": completed,
            "path_completion_rate": round(completed / len(own_nodes), 4) if own_nodes else None,
            "pending_burden_minutes": burden,
            "burden_state": "attention" if burden > BURDEN_THRESHOLD_MINUTES else "within_demo_threshold",
            "source_object_counts": {"learning_events": len(own_events), "assessment_attempts": len(own_attempts), "path_nodes": len(own_nodes)},
        })
    completed_nodes = sum(1 for node in nodes if node.status == "completed")
    total_burden = sum(row["pending_burden_minutes"] for row in learner_rows)
    metrics = [
        _metric("participation_rate", len(active_owners) / len(owners) if owners else None,
                numerator=len(active_owners), denominator=len(owners), sample_size=len(owners)),
        _metric("assessment_average", sum(a.score for a in attempts) / len(attempts) if attempts else None,
                numerator=round(sum(a.score for a in attempts), 4), denominator=len(attempts), sample_size=len(attempts)),
        _metric("path_completion_rate", completed_nodes / len(nodes) if nodes else None,
                numerator=completed_nodes, denominator=len(nodes), sample_size=len(nodes)),
        _metric("path_burden_minutes", total_burden / len(owners) if owners else None,
                numerator=total_burden, denominator=len(owners), sample_size=len(owners)),
    ]
    return {
        "schema_version": "next.teaching-analytics-snapshot.v1", "metric_version": METRIC_VERSION,
        "truthfulness": {"data_kind": "competition_demo_metrics", "real_enterprise_data": False,
                         "thresholds_are_demonstration_only": True, "missing_values_imputed": False},
        "class": {"id": classroom.id, "course_id": classroom.course_id, "title": classroom.title, "term": classroom.term},
        "period": {"start": _iso(period_start), "end": _iso(period_end), "end_exclusive": True},
        "population": {"active_learners": len(owners)}, "metrics": metrics, "learners": learner_rows,
        "source_counts": {"learning_events": len(events), "assessment_attempts": len(attempts), "learning_paths": len(paths), "path_nodes": len(nodes)},
    }


def create_report(db: Any, *, actor: DBUser, class_id: str, period_start: datetime,
                  period_end: datetime) -> tuple[DBTeachingAnalyticsReport, bool]:
    classroom = _class_for_manager(db, class_id, actor)
    existing = db.query(DBTeachingAnalyticsReport).filter_by(
        class_id=class_id, period_start=period_start, period_end=period_end, metric_version=METRIC_VERSION,
    ).first()
    if existing:
        return existing, False
    snapshot = build_snapshot(db, actor=actor, class_id=class_id, period_start=period_start, period_end=period_end)
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    row = DBTeachingAnalyticsReport(
        class_id=class_id, course_id=classroom.course_id, period_start=period_start, period_end=period_end,
        metric_version=METRIC_VERSION, report_data=snapshot, content_hash=hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        created_by_public_id=actor.public_id,
    )
    db.add(row); db.flush()
    return row, True


def report_payload(row: DBTeachingAnalyticsReport) -> dict[str, Any]:
    return {"id": row.id, "status": row.status, "report_version": row.report_version,
            "content_hash": row.content_hash, "created_at": _iso(row.created_at), **dict(row.report_data or {})}


def get_report(db: Any, *, actor: DBUser, report_id: str) -> DBTeachingAnalyticsReport:
    row = db.get(DBTeachingAnalyticsReport, report_id)
    if row is None:
        raise CourseGovernanceError("analytics_report_unknown", "analytics report does not exist")
    _class_for_manager(db, row.class_id, actor)
    return row


def list_reports(db: Any, *, actor: DBUser, class_id: str) -> list[dict[str, Any]]:
    _class_for_manager(db, class_id, actor)
    rows = db.query(DBTeachingAnalyticsReport).filter_by(class_id=class_id).order_by(DBTeachingAnalyticsReport.created_at.desc()).all()
    return [report_payload(row) for row in rows]
