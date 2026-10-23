"""Owner-scoped review calendar built from existing learning records."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.authorization import ObjectAccess, active_course_role, can_access_object
from app.database import (
    DBAssessmentQuestionVersion,
    DBAssessmentRetestTask,
    DBChapter,
    DBChapterKnowledgePoint,
    DBCheckinLog,
    DBCourse,
    DBKnowledgePoint,
    DBLearningEvent,
    DBProfileSnapshot,
    DBReviewPlan,
    DBSourceRef,
    DBUser,
    DBAssessmentAttempt,
)
from app.exam_gate import exam_gate_status
from app.learning_aggregation import aggregate_learning_event
from app.m5_learning import LearningEventInput, record_learning_event
from app.resource_bundles import (
    GENERATION_RESOURCE_TYPES,
    create_generation_job,
)
from app.schemas import ContextRef


SCHEMA_VERSION = "f8.review-schedule.v1"
LOCAL_ZONE = ZoneInfo("Asia/Shanghai")
RESOURCE_LABELS = {
    "handout": ("个性化讲义", "阅读关键内容并完成讲义内学习检查。"),
    "mind_map": ("思维导图", "展开核心分支并完成一次关系检查。"),
    "quiz": ("测验题资源", "提交测验并获得服务端判分。"),
    "training_task": ("实训任务书", "完成任务书规定的检查点与提交物。"),
    "code_sandbox": ("代码沙盒", "运行代码并通过当前任务的必需检查。"),
    "video": ("视频推荐", "完成有效观看并记录一个理解检查。"),
    "deck": ("PPT与网页课件", "浏览课件并完成结尾学习检查。"),
    "interactive_model": ("可交互模型", "保存一次通过全部检查的参数实验。"),
    "feynman": ("费曼复述", "提交复述并获得有效量表评分。"),
}


class ReviewScheduleError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise ReviewScheduleError(code, message)


def _utc_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _local(value: datetime | None) -> datetime | None:
    value = _utc_naive(value)
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc).astimezone(LOCAL_ZONE)


def _iso(value: datetime | None) -> str | None:
    local = _local(value)
    return local.isoformat(timespec="seconds") if local else None


def _readable_courses(db: Any, actor: DBUser) -> dict[str, DBCourse]:
    from course_catalog import course_is_selectable
    output: dict[str, DBCourse] = {}
    for course in db.query(DBCourse).order_by(DBCourse.title, DBCourse.id).all():
        # The review selector follows the active knowledge-base directory. A
        # private course whose membership was removed remains auditable, but
        # must not reappear as an active course choice through owner access.
        course_role = active_course_role(
            db, course_id=course.id, user_public_id=actor.public_id,
        )
        if course.visibility != "public" and actor.role != "admin" and not course_role:
            continue
        access = ObjectAccess(
            "course",
            course.id,
            owner_public_id=course.owner_public_id,
            course_id=course.id,
            visibility=course.visibility,
        )
        if can_access_object(actor, access, action="read", course_role=course_role):
            if not course_is_selectable(db, course):
                continue
            output[course.id] = course
    return output


def _knowledge_contexts(
    db: Any,
    courses: dict[str, DBCourse],
) -> tuple[dict[str, list[dict[str, str]]], dict[str, dict[str, str]]]:
    by_alias: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_id: dict[str, dict[str, str]] = {}
    if not courses:
        return by_alias, by_id
    rows = (
        db.query(DBKnowledgePoint, DBChapter)
        .join(
            DBChapterKnowledgePoint,
            DBChapterKnowledgePoint.knowledge_point_id == DBKnowledgePoint.id,
        )
        .join(DBChapter, DBChapter.id == DBChapterKnowledgePoint.chapter_id)
        .filter(DBChapter.course_id.in_(tuple(courses)))
        .order_by(DBChapter.course_id, DBKnowledgePoint.title)
        .all()
    )
    for point, chapter in rows:
        item = {
            "course_id": chapter.course_id,
            "knowledge_point_id": point.id,
            "knowledge_point_title": point.title,
            "chapter_id": chapter.id,
        }
        by_id.setdefault(point.id, item)
        for alias in {point.id.casefold(), point.code.casefold(), point.title.casefold()}:
            if item not in by_alias[alias]:
                by_alias[alias].append(item)
    return by_alias, by_id


def _plan_context(
    plan: DBReviewPlan,
    by_alias: dict[str, list[dict[str, str]]],
) -> dict[str, str | None]:
    candidates = by_alias.get(str(plan.concept or "").strip().casefold(), [])
    unique = {
        (item["course_id"], item["knowledge_point_id"]): item
        for item in candidates
    }
    if len(unique) == 1:
        return dict(next(iter(unique.values())))
    return {
        "course_id": None,
        "knowledge_point_id": None,
        "knowledge_point_title": str(plan.concept or "未命名知识点"),
        "chapter_id": None,
    }


def _retest_context(
    db: Any,
    task: DBAssessmentRetestTask,
    by_id: dict[str, dict[str, str]],
    readable_course_ids: set[str],
) -> dict[str, str | None]:
    version = db.get(DBAssessmentQuestionVersion, task.question_version_id)
    point_id = str(version.primary_knowledge_point_id or "") if version else ""
    point = by_id.get(point_id)
    if task.course_id and task.course_id in readable_course_ids and point_id:
        exact = (
            db.query(DBKnowledgePoint, DBChapter)
            .join(
                DBChapterKnowledgePoint,
                DBChapterKnowledgePoint.knowledge_point_id == DBKnowledgePoint.id,
            )
            .join(DBChapter, DBChapter.id == DBChapterKnowledgePoint.chapter_id)
            .filter(
                DBChapter.course_id == task.course_id,
                DBKnowledgePoint.id == point_id,
            )
            .order_by(DBChapter.id)
            .first()
        )
        if exact:
            exact_point, chapter = exact
            return {
                "course_id": task.course_id,
                "knowledge_point_id": exact_point.id,
                "knowledge_point_title": exact_point.title,
                "chapter_id": chapter.id,
            }
    if task.course_id and task.course_id not in readable_course_ids:
        point = None
    if point:
        return dict(point)
    canonical_point = db.get(DBKnowledgePoint, point_id) if point_id else None
    return {
        "course_id": task.course_id if task.course_id in readable_course_ids else None,
        "knowledge_point_id": point_id or None,
        "knowledge_point_title": canonical_point.title if canonical_point else "延迟复测",
        "chapter_id": None,
    }


def _resource_context(
    db: Any,
    *,
    actor: DBUser,
    context: dict[str, str | None],
) -> dict[str, Any]:
    course_id = context.get("course_id")
    point_id = context.get("knowledge_point_id")
    missing: list[str] = []
    if not course_id:
        missing.append("课程归属")
    if not point_id:
        missing.append("知识点")
    chapter_ids: list[str] = []
    if course_id and point_id:
        chapter_ids = [
            row[0]
            for row in (
                db.query(DBChapter.id)
                .join(
                    DBChapterKnowledgePoint,
                    DBChapterKnowledgePoint.chapter_id == DBChapter.id,
                )
                .filter(
                    DBChapter.course_id == course_id,
                    DBChapterKnowledgePoint.knowledge_point_id == point_id,
                )
                .all()
            )
        ]
    source_refs = (
        db.query(DBSourceRef)
        .filter(DBSourceRef.chapter_id.in_(chapter_ids))
        .order_by(DBSourceRef.location_index, DBSourceRef.id)
        .all()
        if chapter_ids else []
    )
    if not source_refs:
        missing.append("课程来源")
    snapshots = (
        db.query(DBProfileSnapshot)
        .filter_by(owner_public_id=actor.public_id)
        .order_by(DBProfileSnapshot.created_at.desc(), DBProfileSnapshot.id.desc())
        .all()
    )
    profile = next(
        (
            row for row in snapshots
            if (row.snapshot or {}).get("course_id") in {None, course_id}
        ),
        None,
    )
    if profile is None:
        missing.append("画像快照")
    return {
        "ready": not missing,
        "block_reason": "" if not missing else f"还缺少：{'、'.join(missing)}。",
        "course_id": course_id,
        "knowledge_point_id": point_id,
        "knowledge_point_title": context.get("knowledge_point_title") or "当前知识点",
        "chapter_id": context.get("chapter_id"),
        "source_ref_ids": [row.id for row in source_refs],
        "profile_snapshot_id": profile.id if profile else None,
    }


def _exam_context(
    db: Any,
    *,
    actor: DBUser,
    course_id: str | None,
) -> dict[str, Any]:
    if not course_id:
        return {
            "unlocked": False,
            "reason": "course_context_required",
            "message": "需要先确认课程归属，才能检查智能组卷条件。",
            "next_route": "/workspace/path",
        }
    status = exam_gate_status(
        db, owner_public_id=actor.public_id, course_id=course_id,
    )
    return {
        **status,
        "message": (
            "今日必做任务已完成，可以进入智能组卷。"
            if status.get("unlocked")
            else "请先完成总路径中的今日必做任务。"
        ),
    }


def _task_payload(
    db: Any,
    *,
    actor: DBUser,
    task_id: str,
    source_type: str,
    source_id: str,
    context: dict[str, str | None],
    due_at: datetime,
    status: str,
    task_type: str,
    reason: str,
    method: str,
    completion_rule: str,
    priority: float,
    start_kind: str,
    start_route: str,
) -> dict[str, Any]:
    resource = _resource_context(db, actor=actor, context=context)
    exam = _exam_context(
        db, actor=actor, course_id=context.get("course_id"),
    )
    title = context.get("knowledge_point_title") or "未命名复习任务"
    resource_review = {
        "required": source_type == "sm2_review_plan",
        "status": "ready" if resource["ready"] else "blocked",
        "source_ref_ids": list(resource.get("source_ref_ids") or []),
        "profile_snapshot_id": resource.get("profile_snapshot_id"),
        "course_id": context.get("course_id"),
        "knowledge_point_id": context.get("knowledge_point_id"),
    }
    assessment = {
        "required": source_type == "sm2_review_plan",
        "status": "pending" if source_type == "sm2_review_plan" else "not_required",
        "mode": "practice",
        "course_id": context.get("course_id"),
        "knowledge_point_id": context.get("knowledge_point_id"),
        "source_ref_ids": list(resource.get("source_ref_ids") or []),
        "attempt_id": None,
    }
    return {
        "id": task_id,
        "source_type": source_type,
        "source_id": source_id,
        "course_id": context.get("course_id"),
        "knowledge_point_id": context.get("knowledge_point_id"),
        "knowledge_point_title": title,
        "chapter_id": context.get("chapter_id"),
        "due_at": _iso(due_at),
        "date": _local(due_at).date().isoformat(),
        "status": status,
        "type": task_type,
        "reason": reason,
        "method": method,
        "completion_rule": completion_rule,
        "priority": priority,
        "review_flow": {
            "sequence": ["resource_review", "intelligent_assessment", "submit"]
            if source_type == "sm2_review_plan" else [],
            "resource_review": resource_review,
            "assessment": assessment,
            "completion_requires_assessment": source_type == "sm2_review_plan",
        },
        "action": {
            "kind": start_kind,
            "label": "去复习" if status != "completed" else "查看记录",
            "route": start_route,
            "enabled": status != "completed",
            "disabled_reason": "该任务已完成。" if status == "completed" else "",
        },
        "resource_generation": resource,
        "exam_gate": exam,
        "chat_route": (
            f"/learn?course_id={context.get('course_id') or ''}"
            f"&knowledge_point_id={context.get('knowledge_point_id') or ''}"
            f"&task_id={task_id}"
        ),
    }


def _month_dates(month: str) -> tuple[date, list[date]]:
    try:
        year_text, month_text = month.split("-", 1)
        first = date(int(year_text), int(month_text), 1)
    except (TypeError, ValueError):
        _fail("review_schedule.month_invalid", "月份必须使用 YYYY-MM 格式。")
    if first.strftime("%Y-%m") != month:
        _fail("review_schedule.month_invalid", "月份必须使用 YYYY-MM 格式。")
    start = date.fromordinal(first.toordinal() - first.weekday())
    return first, [date.fromordinal(start.toordinal() + offset) for offset in range(42)]


def _status_for_due(due_date: date, today: date) -> str:
    if due_date < today:
        return "overdue"
    if due_date == today:
        return "due"
    return "scheduled"


def build_review_schedule(
    db: Any,
    *,
    actor: DBUser,
    month: str,
    course_id: str = "all",
    now: datetime | None = None,
) -> dict[str, Any]:
    first, grid_dates = _month_dates(month)
    current = (now or datetime.now(timezone.utc)).astimezone(LOCAL_ZONE)
    today = current.date()
    courses = _readable_courses(db, actor)
    if course_id not in {"all", "unclassified"} and course_id not in courses:
        _fail("review_schedule.course_forbidden", "当前课程不可用。")
    by_alias, by_id = _knowledge_contexts(db, courses)
    tasks: list[dict[str, Any]] = []

    plans = (
        db.query(DBReviewPlan)
        .filter_by(student_id=actor.username)
        .order_by(DBReviewPlan.next_review_at, DBReviewPlan.priority, DBReviewPlan.id)
        .all()
    )
    for plan in plans:
        due_at = _utc_naive(plan.next_review_at or plan.created_at) or current.astimezone(timezone.utc).replace(tzinfo=None)
        due_date = _local(due_at).date()
        context = _plan_context(plan, by_alias)
        tasks.append(_task_payload(
            db,
            actor=actor,
            task_id=f"review-plan:{plan.id}",
            source_type="sm2_review_plan",
            source_id=str(plan.id),
            context=context,
            due_at=due_at,
            status=_status_for_due(due_date, today),
            task_type="SM-2 间隔复习",
            reason="根据上次掌握证据和间隔重复计划安排。",
            method="先回顾当前知识点的授权资源，再完成一次智能组卷并提交作答。",
            completion_rule="完成资源回顾并提交一次服务端判分的智能组卷作答。",
            priority=float(plan.priority or 1.0),
            start_kind="review_assessment",
            start_route=f"/workspace/review?review_task=review-plan:{plan.id}",
        ))

    retests = (
        db.query(DBAssessmentRetestTask)
        .filter_by(owner_public_id=actor.public_id)
        .filter(DBAssessmentRetestTask.status != "cancelled")
        .order_by(DBAssessmentRetestTask.due_at, DBAssessmentRetestTask.id)
        .all()
    )
    for retest in retests:
        context = _retest_context(db, retest, by_id, set(courses))
        if retest.status == "completed":
            due_at = _utc_naive(retest.completed_at or retest.due_at)
            status = "completed"
        else:
            due_at = _utc_naive(retest.due_at)
            status = _status_for_due(_local(due_at).date(), today)
        tasks.append(_task_payload(
            db,
            actor=actor,
            task_id=f"retest:{retest.id}",
            source_type="delayed_retest",
            source_id=retest.id,
            context=context,
            due_at=due_at,
            status=status,
            task_type="延迟复测",
            reason="已确认的错误模式需要在间隔后重新作答验证。",
            method="进入真实题目并提交答案，判分通过后自动形成证据。",
            completion_rule="延迟至少 24 小时后正确完成服务端判分。",
            priority=0.45,
            start_kind="delayed_retest",
            start_route=f"/workspace/review?retest_id={retest.id}",
        ))

    completions = (
        db.query(DBLearningEvent)
        .filter_by(owner_public_id=actor.public_id, event_type="review_completed")
        .order_by(DBLearningEvent.occurred_at, DBLearningEvent.id)
        .all()
    )
    for event in completions:
        context_ref = dict(event.context_ref or {})
        point_id = str(context_ref.get("knowledgePointId") or event.object_id or "")
        point = by_id.get(point_id)
        context = dict(point) if point else {
            "course_id": event.course_id,
            "knowledge_point_id": point_id or None,
            "knowledge_point_title": str((event.payload or {}).get("concept") or "复习记录"),
            "chapter_id": context_ref.get("chapterId"),
        }
        tasks.append(_task_payload(
            db,
            actor=actor,
            task_id=f"completion:{event.id}",
            source_type="review_completion",
            source_id=event.id,
            context=context,
            due_at=_utc_naive(event.occurred_at),
            status="completed",
            task_type="复习完成记录",
            reason="已提交有效回忆结果并进入统一学习聚合。",
            method="查看本次回忆结果和后续安排。",
            completion_rule="已完成。",
            priority=1.0,
            start_kind="completion_record",
            start_route="/workspace/review",
        ))

    if course_id == "unclassified":
        tasks = [item for item in tasks if item["course_id"] is None]
    elif course_id != "all":
        tasks = [item for item in tasks if item["course_id"] == course_id]
    grid_set = set(grid_dates)
    tasks = [item for item in tasks if date.fromisoformat(item["date"]) in grid_set]
    tasks.sort(key=lambda item: (
        item["due_at"], item["priority"], item["source_type"], item["id"],
    ))

    tasks_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in tasks:
        tasks_by_date[item["date"]].append(item)
    days: list[dict[str, Any]] = []
    for day in grid_dates:
        items = tasks_by_date.get(day.isoformat(), [])
        active = [item for item in items if item["status"] != "completed"]
        completed = [item for item in items if item["status"] == "completed"]
        if day == today and active:
            state = "today"
        elif day < today and active:
            state = "overdue"
        elif completed and not active:
            state = "completed"
        elif active:
            state = "future"
        else:
            state = "empty"
        days.append({
            "date": day.isoformat(),
            "day": day.day,
            "in_month": day.month == first.month,
            "is_today": day == today,
            "state": state,
            "counts": {
                "total": len(items),
                "pending": len(active),
                "completed": len(completed),
                "overdue": sum(item["status"] == "overdue" for item in items),
            },
            "task_ids": [item["id"] for item in items],
        })

    has_unclassified = any(item["course_id"] is None for item in tasks) or any(
        _plan_context(plan, by_alias).get("course_id") is None for plan in plans
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "timezone": str(LOCAL_ZONE),
        "month": month,
        "today": today.isoformat(),
        "selected_course_id": course_id,
        "courses": [
            {"id": item.id, "title": item.title}
            for item in courses.values()
        ] + ([{"id": "unclassified", "title": "未归类计划"}] if has_unclassified else []),
        "weekdays": ["一", "二", "三", "四", "五", "六", "日"],
        "days": days,
        "tasks": tasks,
        "summary": {
            "total": len(tasks),
            "due": sum(item["status"] == "due" for item in tasks),
            "overdue": sum(item["status"] == "overdue" for item in tasks),
            "completed": sum(item["status"] == "completed" for item in tasks),
        },
    }


def _owned_plan(db: Any, actor: DBUser, task_id: str) -> DBReviewPlan:
    if not task_id.startswith("review-plan:"):
        _fail("review_schedule.task_not_completable", "该任务必须在对应学习页面完成。")
    try:
        plan_id = int(task_id.split(":", 1)[1])
    except ValueError:
        _fail("review_schedule.task_invalid", "复习任务标识无效。")
    plan = db.get(DBReviewPlan, plan_id)
    if plan is None or plan.student_id != actor.username:
        _fail("review_schedule.task_unknown", "复习任务不存在。")
    return plan


def complete_review_task(
    db: Any,
    *,
    actor: DBUser,
    task_id: str,
    idempotency_key: str,
    recall_score: float,
    duration_minutes: int,
    assessment_attempt_id: str | None = None,
    assessment_event_id: str | None = None,
) -> dict[str, Any]:
    plan = _owned_plan(db, actor, task_id)
    courses = _readable_courses(db, actor)
    by_alias, _ = _knowledge_contexts(db, courses)
    context = _plan_context(plan, by_alias)
    canonical_concept = str(context.get("knowledge_point_title") or plan.concept)
    if context.get("knowledge_point_id") and plan.concept != canonical_concept:
        existing_canonical = (
            db.query(DBReviewPlan)
            .filter(
                DBReviewPlan.student_id == actor.username,
                DBReviewPlan.concept == canonical_concept,
                DBReviewPlan.id != plan.id,
            )
            .first()
        )
        if existing_canonical is not None:
            _fail(
                "review_schedule.plan_context_conflict",
                "同一知识点存在重复复习计划，请先保留一条计划再提交。",
            )
        plan.concept = canonical_concept
        db.flush()
    point_id = context.get("knowledge_point_id") or f"legacy-review-{plan.id}"
    assessment = None
    assessment_event = None
    if assessment_attempt_id:
        assessment = db.query(DBAssessmentAttempt).filter_by(
            id=assessment_attempt_id,
            owner_public_id=actor.public_id,
        ).first()
        if assessment is None:
            _fail("review_schedule.assessment_unknown", "智能组卷作答不存在或不属于当前学习者。")
        if assessment.grading_status != "graded" or assessment.submitted_at is None:
            _fail("review_schedule.assessment_not_graded", "智能组卷尚未完成服务端判分，不能完成复习。")
        if context.get("course_id") and assessment.course_id != context.get("course_id"):
            _fail("review_schedule.assessment_context_conflict", "智能组卷课程与当前复习知识点不一致。")
        version = db.get(DBAssessmentQuestionVersion, assessment.question_version_id)
        if version is None or (
            context.get("knowledge_point_id")
            and version.primary_knowledge_point_id != context.get("knowledge_point_id")
        ):
            _fail("review_schedule.assessment_context_conflict", "智能组卷题目与当前复习知识点不一致。")
        recall_score = float(assessment.score)
    elif assessment_event_id:
        assessment_event = db.query(DBLearningEvent).filter_by(
            id=assessment_event_id,
            owner_public_id=actor.public_id,
            event_type="formal_exam_submitted",
        ).first()
        if assessment_event is None:
            _fail("review_schedule.assessment_event_unknown", "智能组卷提交记录不存在或不属于当前学习者。")
        event_payload = dict(assessment_event.payload or {})
        if not event_payload.get("graded"):
            _fail("review_schedule.assessment_not_graded", "智能组卷尚未完成服务端判分，不能完成复习。")
        if context.get("course_id") and assessment_event.course_id != context.get("course_id"):
            _fail("review_schedule.assessment_context_conflict", "智能组卷课程与当前复习知识点不一致。")
        point_scores = [
            item for item in event_payload.get("knowledge_point_scores") or []
            if item.get("knowledge_point_id") == context.get("knowledge_point_id")
        ]
        if not point_scores or point_scores[0].get("score") is None:
            _fail("review_schedule.assessment_context_conflict", "智能组卷提交未包含当前复习知识点的判分结果。")
        recall_score = float(point_scores[0]["score"])
    existing = (
        db.query(DBLearningEvent)
        .filter_by(owner_public_id=actor.public_id, idempotency_key=idempotency_key)
        .first()
    )
    expected_payload = {
        "review_id": task_id,
        "recall_score": round(float(recall_score), 4),
        "concept": canonical_concept,
        "duration_minutes": duration_minutes,
    }
    if assessment is not None:
        expected_payload.update({
            "assessment_attempt_id": assessment.id,
            "assessment_score": round(float(assessment.score), 4),
        })
    if assessment_event is not None:
        expected_payload.update({
            "assessment_event_id": assessment_event.id,
            "assessment_score": round(float(recall_score), 4),
        })
    if existing is not None:
        if (
            existing.event_type != "review_completed"
            or existing.object_id != point_id
            or dict(existing.payload or {}) != expected_payload
        ):
            _fail(
                "review_schedule.idempotency_conflict",
                "同一提交标识已用于不同的复习结果。",
            )
        event, created = existing, False
    else:
        event, created = record_learning_event(
            db,
            owner_public_id=actor.public_id,
            user=actor if context.get("course_id") else None,
            trusted_source=True,
            event=LearningEventInput(
                idempotency_key=idempotency_key,
                event_type="review_completed",
                context=ContextRef(
                    userId=actor.public_id,
                    courseId=context.get("course_id"),
                    chapterId=context.get("chapter_id"),
                    knowledgePointId=context.get("knowledge_point_id"),
                ),
                course_id=context.get("course_id"),
                object_type="knowledge_point",
                object_id=point_id,
                source="backend",
                payload=expected_payload,
            ),
        )
        db.add(DBCheckinLog(
            student_id=actor.username,
            checkin_date=event.occurred_at,
            duration_minutes=duration_minutes,
            concepts_reviewed=[expected_payload["concept"]],
        ))
    aggregation = aggregate_learning_event(db, event=event)
    db.commit()
    db.refresh(plan)
    return {
        "schema_version": SCHEMA_VERSION,
        "created": created,
        "event": {
            "id": event.id,
            "status": event.evidence_status,
            "strength": event.evidence_strength,
            "reason": event.evidence_reason,
        },
        "aggregation": {
            "id": aggregation.id,
            "status": aggregation.status,
            "result": aggregation.result or {},
        },
        "assessment": {
            "required": True,
            "attempt_id": assessment.id if assessment is not None else None,
            "event_id": assessment_event.id if assessment_event is not None else None,
            "score": round(float(assessment.score), 4) if assessment is not None else (
                round(float(recall_score), 4) if assessment_event is not None else None
            ),
            "submitted": assessment is not None or assessment_event is not None,
        },
        "next_review_at": _iso(plan.next_review_at),
        "review_count": plan.review_count,
    }


def create_review_resource_job(
    db: Any,
    *,
    actor: DBUser,
    task_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    courses = _readable_courses(db, actor)
    by_alias, by_id = _knowledge_contexts(db, courses)
    if task_id.startswith("review-plan:"):
        context = _plan_context(_owned_plan(db, actor, task_id), by_alias)
    elif task_id.startswith("retest:"):
        retest_id = task_id.split(":", 1)[1]
        retest = db.get(DBAssessmentRetestTask, retest_id)
        if retest is None or retest.owner_public_id != actor.public_id:
            _fail("review_schedule.task_unknown", "复习任务不存在。")
        context = _retest_context(db, retest, by_id, set(courses))
    else:
        _fail("review_schedule.resource_task_unsupported", "该任务不能生成复习资源包。")
    resource = _resource_context(db, actor=actor, context=context)
    if not resource["ready"]:
        _fail("review_schedule.resource_context_incomplete", resource["block_reason"])
    title = str(resource["knowledge_point_title"])
    items = [
        {
            "type": resource_type,
            "title": f"{title} · {RESOURCE_LABELS[resource_type][0]}",
            "source_ref_ids": resource["source_ref_ids"],
            "completion_rule": RESOURCE_LABELS[resource_type][1],
        }
        for resource_type in GENERATION_RESOURCE_TYPES
    ]
    result = create_generation_job(
        db,
        actor,
        course_id=str(resource["course_id"]),
        knowledge_point_id=str(resource["knowledge_point_id"]),
        profile_snapshot_id=str(resource["profile_snapshot_id"]),
        idempotency_key=idempotency_key,
        items=items,
        learning_goal=f"复习并验证对{title}的稳定理解。",
    )
    db.commit()
    return result
