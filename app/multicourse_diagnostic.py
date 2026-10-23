"""Multi-course entry diagnostics and aggregate path validation.

The implementation deliberately composes the existing diagnostic, report and
plan lifecycles.  A multi-course run is a transport-level orchestration object;
the canonical rows remain one blueprint/session/report and one plan draft per
course.  The aggregate plan is stored in the existing ``DBPlanDraft`` with a
null course id so no second path database is introduced.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
from typing import Any

from app.database import (
    DBDiagnosticReport,
    DBPlanDraft,
    DBPlanVersion,
    DBUser,
)
from app.diagnostic_generation import (
    DiagnosticBlueprintRequest,
    DiagnosticGenerationError,
    diagnostic_blueprint_payload,
    generate_diagnostic_blueprint,
)
from app.diagnostic_report import (
    DiagnosticReportError,
    generate_report_path,
)
from app.path_draft import PathDraftError
from app.m5_learning import PlanNodeSpec, PlanSpec, create_plan_draft


class MultiCourseDiagnosticError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 409, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.details = details or {}


@dataclass(frozen=True)
class MultiCourseBlueprintRequest:
    course_ids: tuple[str, ...]
    idempotency_key: str
    question_count: int = 15
    self_rating: str = "foundation"


@dataclass(frozen=True)
class MultiCoursePathRequest:
    report_ids: tuple[str, ...]
    idempotency_key: str
    time_budget_minutes: int = 90


def _unique_ids(values: tuple[str, ...] | list[str], *, field: str) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))
    if not normalized:
        raise MultiCourseDiagnosticError("multicourse_selection_required", f"{field} 不能为空。", status_code=422)
    if len(normalized) > 8:
        raise MultiCourseDiagnosticError("multicourse_selection_too_large", "一次最多选择 8 门课程。", status_code=422)
    if len(normalized) != len(values):
        raise MultiCourseDiagnosticError("multicourse_selection_duplicate", f"{field} 不能包含重复项目。", status_code=422)
    return normalized


def _course_item(payload: dict[str, Any], course_id: str) -> dict[str, Any]:
    course = dict(payload.get("course") or {})
    return {
        "course_id": course_id,
        "course": course,
        "status": "ready",
        "blueprint": payload,
        "error": None,
    }


def _scoped_idempotency_key(base: str, scope: str) -> str:
    """Keep per-course keys within the canonical 128-character column limit."""
    value = f"{base.strip()}:{scope.strip()}"
    if len(value) <= 128:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{base.strip()[:110]}:{digest}"


def generate_multicourse_blueprints(
    session: Any,
    *,
    user: DBUser,
    request: MultiCourseBlueprintRequest,
    llm: Any,
) -> dict[str, Any]:
    """Generate one independently audited blueprint for every selected course."""
    course_ids = _unique_ids(request.course_ids, field="course_ids")
    if not request.idempotency_key.strip():
        raise MultiCourseDiagnosticError("multicourse_idempotency_required", "请重新开始多课程诊断。", status_code=422)
    items: list[dict[str, Any]] = []
    for course_id in course_ids:
        # The per-course key keeps the existing unique constraint meaningful
        # while allowing one user action to be replayed safely.
        per_course_key = _scoped_idempotency_key(request.idempotency_key, course_id)
        try:
            # Isolate one course so a provider/validation failure cannot leave
            # partial question rows that affect the remaining courses.
            with session.begin_nested():
                row, created = generate_diagnostic_blueprint(
                    session,
                    user=user,
                    request=DiagnosticBlueprintRequest(
                        course_id=course_id,
                        idempotency_key=per_course_key,
                        question_count=request.question_count,
                        self_rating=request.self_rating,
                    ),
                    llm=llm,
                )
                payload = diagnostic_blueprint_payload(session, row)
            items.append({
                **_course_item(payload, course_id),
                "created": created,
                "blueprint_id": row.id,
            })
        except DiagnosticGenerationError as exc:
            # A weak or unavailable course must not erase other successful
            # courses.  The caller can retry this item with the same run key.
            items.append({
                "course_id": course_id,
                "course": {"id": course_id},
                "status": "failed",
                "blueprint": None,
                "blueprint_id": None,
                "created": False,
                "error": {"code": exc.code, "message": str(exc)},
            })
    ready = [item for item in items if item["status"] == "ready"]
    failed = [item for item in items if item["status"] == "failed"]
    return {
        "schema_version": "p1-b30.multicourse-blueprints.v1",
        "run_key": request.idempotency_key.strip(),
        "course_ids": list(course_ids),
        "status": "completed" if not failed else "partial" if ready else "failed",
        "items": items,
        "ready_count": len(ready),
        "failed_count": len(failed),
        "model_policy": {
            "provider": getattr(llm, "provider", None),
            "model": "deepseek-v4-flash",
            "thinking": "enabled",
            "reasoning_effort": "max",
            "allow_fallback": False,
        },
    }


def _path_node_spec(course_id: str, node: dict[str, Any], index: int) -> PlanNodeSpec:
    raw_key = str(node.get("node_key") or node.get("id") or f"node-{index}")
    node_key = f"{course_id}::{raw_key}"
    prerequisites = tuple(_scoped_node_key(course_id, item) for item in (node.get("prerequisites") or []))
    node_type = str(node.get("node_type") or "chapter")
    if node_type not in {"chapter", "artifact", "assessment", "interactive", "review", "extension"}:
        node_type = "chapter"
    target = node.get("target_object_id") or (node.get("chapter") or {}).get("id")
    if node_type != "extension" and not target:
        raise MultiCourseDiagnosticError("multicourse_path_node_invalid", "科目路径包含缺少目标的节点。", status_code=502)
    estimate = node.get("estimate_range")
    if estimate is None:
        estimate = node.get("estimate_minutes")
    if estimate is None:
        estimate = node.get("estimate_min_minutes")
    if isinstance(estimate, dict):
        estimate = [estimate.get("min"), estimate.get("max")]
    if isinstance(estimate, (int, float, str)):
        estimate = [estimate, estimate]
    if not isinstance(estimate, (list, tuple)) or len(estimate) < 2:
        estimate = [15, 15]
    minimum, maximum = estimate[0], estimate[1]
    minimum = max(1, int(minimum or 1))
    maximum = max(minimum, int(maximum or minimum))
    return PlanNodeSpec(
        node_key=node_key,
        node_type=node_type,
        target_object_id=str(target) if target else None,
        title=f"{course_id} · {node.get('title') or '学习任务'}",
        prerequisites=prerequisites,
        resource_status=str(node.get("resource_status") or "existing"),
        estimate_min_minutes=minimum,
        estimate_max_minutes=maximum,
        extension_reason=str(node.get("extension_reason") or "多课程总路径中的补充任务") if node_type == "extension" else "",
        difficulty=node.get("difficulty"),
        rationale=str(node.get("reason") or node.get("rationale") or "继承该科目路径的模型规划依据。"),
        required=bool(node.get("required", True)),
        risk_level="high" if node.get("risk_level") == "high" else "normal",
    )


def validate_total_schedule(
    subject_paths: list[dict[str, Any]],
    *,
    time_budget_minutes: int,
    max_days: int = 60,
) -> dict[str, Any]:
    """Validate and project independent subject paths into a total schedule."""
    budget = max(1, int(time_budget_minutes or 1))
    max_days = max(1, min(60, int(max_days or 60)))
    issues: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    task_keys: set[str] = set()
    by_key: dict[str, dict[str, Any]] = {}
    for subject in subject_paths:
        course_id = str(subject.get("course_id") or "")
        path_id = str(subject.get("path_id") or subject.get("plan_id") or "")
        for index, node in enumerate(subject.get("nodes") or [], start=1):
            raw_key = str(node.get("node_key") or node.get("id") or f"node-{index}")
            key = f"{course_id}::{raw_key}"
            if key in task_keys:
                issues.append({"code": "duplicate_node", "course_id": course_id, "node_key": raw_key, "message": "总路径包含重复节点。"})
                continue
            task_keys.add(key)
            prerequisites = [_scoped_node_key(course_id, item) for item in (node.get("prerequisites") or [])]
            task = {
                "id": str(node.get("id") or key),
                "node_key": raw_key,
                "aggregate_key": key,
                "course_id": course_id,
                "path_id": path_id,
                "title": node.get("title") or raw_key,
                "sequence": int(node.get("sequence") or index),
                "prerequisites": prerequisites,
                "estimate_minutes": _estimate_minutes(node),
                "priority": int(node.get("priority") or 0),
                "status": str(node.get("status") or "pending"),
            }
            tasks.append(task)
            by_key[key] = task

    if not tasks:
        issues.append({"code": "empty_day", "message": "没有可统筹的科目路径任务。"})

    for task in tasks:
        for prerequisite in task["prerequisites"]:
            parent = by_key.get(prerequisite)
            if parent is None:
                issues.append({"code": "unreachable_node", "course_id": task["course_id"], "node_key": task["node_key"], "message": "节点的先修任务不可达。"})
            elif parent["course_id"] == task["course_id"] and parent["sequence"] >= task["sequence"]:
                issues.append({"code": "prerequisite_inversion", "course_id": task["course_id"], "node_key": task["node_key"], "message": "先修关系顺序倒置。"})

    total_minutes = sum(item["estimate_minutes"] for item in tasks if item["status"] not in {"completed", "skipped"})
    if total_minutes > budget * max_days:
        issues.append({"code": "timeout", "message": f"总学习时长 {total_minutes} 分钟超过 {max_days} 天时间预算。"})

    remaining = {item["aggregate_key"] for item in tasks if item["status"] not in {"completed", "skipped"}}
    resolved = {item["aggregate_key"] for item in tasks if item["status"] in {"completed", "skipped"}}
    scheduled_course_counts: defaultdict[str, int] = defaultdict(int)
    days: list[dict[str, Any]] = []
    day = 1
    while remaining and day <= max_days:
        candidates = [
            by_key[key] for key in remaining
            if set(by_key[key]["prerequisites"]).issubset(resolved)
        ]
        # Prefer a course that has received fewer slots so a tight daily
        # budget cannot starve another selected subject indefinitely.
        candidates.sort(key=lambda item: (
            -item["priority"], scheduled_course_counts[item["course_id"]],
            item["course_id"], item["sequence"], item["aggregate_key"],
        ))
        selected: list[dict[str, Any]] = []
        used = 0
        for task in candidates:
            if selected and used + task["estimate_minutes"] > budget:
                continue
            selected.append(task)
            used += task["estimate_minutes"]
        if not selected:
            if remaining:
                issues.append({"code": "unreachable_node", "message": "剩余节点没有满足先修条件的可达任务。"})
            break
        for task in selected:
            remaining.remove(task["aggregate_key"])
            resolved.add(task["aggregate_key"])
            scheduled_course_counts[task["course_id"]] += 1
        days.append({
            "day": day,
            "tasks": [
                {**task, "scheduled_day": day, "prerequisites": [item.split("::", 1)[-1] for item in task["prerequisites"]]}
                for task in selected
            ],
            "total_minutes": used,
            "budget_minutes": budget,
        })
        day += 1

    if remaining:
        issues.append({"code": "timeout", "message": "部分节点未能在时间预算内排入总路径。"})
    scheduled_day_by_key = {
        task["aggregate_key"]: day["day"]
        for day in days
        for task in day["tasks"]
    }
    for task in tasks:
        current_day = scheduled_day_by_key.get(task["aggregate_key"])
        for prerequisite in task["prerequisites"]:
            parent_day = scheduled_day_by_key.get(prerequisite)
            if current_day and parent_day and parent_day >= current_day:
                issues.append({"code": "prerequisite_inversion", "course_id": task["course_id"], "node_key": task["node_key"], "message": "总路径排期晚于或同时安排了先修任务。"})

    unique_issues = []
    seen_issue = set()
    for issue in issues:
        identity = (issue.get("code"), issue.get("course_id"), issue.get("node_key"), issue.get("message"))
        if identity not in seen_issue:
            seen_issue.add(identity)
            unique_issues.append(issue)
    hard_codes = {"duplicate_node", "timeout", "prerequisite_inversion", "unreachable_node", "empty_day"}
    status = "invalid" if any(item.get("code") in hard_codes for item in unique_issues) else "needs_review" if unique_issues else "valid"
    return {
        "schema_version": "p1-b30.total-schedule-validation.v1",
        "status": status,
        "time_budget_minutes": budget,
        "max_days": max_days,
        "total_minutes": total_minutes,
        "scheduled_minutes": sum(item["total_minutes"] for item in days),
        "days": days,
        "issues": unique_issues,
        "course_ids": sorted({item["course_id"] for item in tasks if item["course_id"]}),
        "read_only": True,
        "learning_state_written": False,
    }


def _estimate_minutes(node: dict[str, Any]) -> int:
    estimate = node.get("estimate_range")
    if estimate is None:
        estimate = node.get("estimate_minutes")
    if estimate is None:
        estimate = node.get("estimate_min_minutes")
    if isinstance(estimate, dict):
        estimate = estimate.get("min")
    elif isinstance(estimate, (list, tuple)):
        estimate = estimate[0] if estimate else 15
    try:
        return max(1, int(estimate or 15))
    except (TypeError, ValueError):
        return 15


def _scoped_node_key(course_id: str, value: Any) -> str:
    raw = str(value or "").strip()
    prefix = f"{course_id}::"
    # A total path may declare a bridge prerequisite from another course.
    # Preserve an already-qualified reference; ordinary subject-local ids keep
    # the historical course scoping behavior.
    return raw if "::" in raw else f"{prefix}{raw}"


def _plan_payload(session: Any, plan: DBPlanDraft) -> dict[str, Any]:
    version = session.get(DBPlanVersion, plan.current_version_id) if plan.current_version_id else None
    content = dict(version.content or {}) if version else {}
    return {
        "id": plan.id,
        "title": plan.title,
        "course_id": plan.course_id,
        "status": plan.status,
        "lock_version": plan.lock_version,
        "current_version_id": plan.current_version_id,
        "version_number": version.version_number if version else None,
        "goal": content.get("goal"),
        "assumptions": list(content.get("assumptions") or []),
        "nodes": list(content.get("nodes") or []),
    }


def generate_multicourse_paths(
    session: Any,
    *,
    user: DBUser,
    request: MultiCoursePathRequest,
    llm: Any,
) -> dict[str, Any]:
    report_ids = _unique_ids(request.report_ids, field="report_ids")
    if not 30 <= int(request.time_budget_minutes) <= 480:
        raise MultiCourseDiagnosticError("multicourse_time_budget_invalid", "时间预算需在 30 到 480 分钟之间。", status_code=422)
    subjects: list[dict[str, Any]] = []
    for report_id in report_ids:
        report = session.get(DBDiagnosticReport, report_id)
        if report is None:
            subjects.append({"report_id": report_id, "status": "failed", "error": {"code": "diagnostic_report_unknown", "message": "诊断报告不存在。"}})
            continue
        if report.owner_public_id != user.public_id:
            subjects.append({"report_id": report_id, "course_id": report.course_id, "status": "failed", "error": {"code": "diagnostic_report_forbidden", "message": "无权使用该诊断报告。"}})
            continue
        try:
            with session.begin_nested():
                path = generate_report_path(
                    session,
                    user=user,
                    report=report,
                    time_budget_minutes=int(request.time_budget_minutes),
                    idempotency_key=_scoped_idempotency_key(request.idempotency_key, report.course_id),
                    llm=llm,
                )
            course = dict(path.get("course") or {})
            subjects.append({
                "report_id": report.id,
                "course_id": report.course_id,
                "course": course,
                "profile_snapshot_id": report.profile_snapshot_id,
                "plan_id": (path.get("plan") or {}).get("id"),
                "path_id": None,
                "status": "ready",
                "state": path.get("state"),
                "plan": path.get("plan"),
                "nodes": list(path.get("nodes") or []),
                "evidence": dict((report.report_data or {}).get("mastery") and {"mastery": (report.report_data or {}).get("mastery")} or {}),
            })
        except (DiagnosticReportError, PathDraftError, MultiCourseDiagnosticError) as exc:
            subjects.append({"report_id": report.id, "course_id": report.course_id, "status": "failed", "error": {"code": getattr(exc, "code", "path_generation_failed"), "message": str(exc)}})

    ready_subjects = [item for item in subjects if item["status"] == "ready" and item.get("nodes")]
    failed_subjects = [item for item in subjects if item["status"] != "ready"]
    validation = validate_total_schedule(ready_subjects, time_budget_minutes=int(request.time_budget_minutes))
    total_plan = None
    if ready_subjects and validation["status"] != "invalid":
        specs = tuple(
            _path_node_spec(subject["course_id"], node, index)
            for subject in ready_subjects
            for index, node in enumerate(subject["nodes"], start=1)
        )
        spec = PlanSpec(
            goal="统筹多个课程的诊断结果，按先修关系和时间预算安排可验证学习任务",
            assumptions=tuple([
                "每门课程保持独立的知识点、来源和画像边界。",
                f"本轮总路径时间预算为 {int(request.time_budget_minutes)} 分钟/日。",
                f"参与统筹的课程：{', '.join(item['course_id'] for item in ready_subjects)}。",
            ]),
            nodes=specs,
        )
        plan, _, _ = create_plan_draft(
            session,
            owner_public_id=user.public_id,
            course_id=None,
            title="多课程入学诊断 · 总路径统筹",
            idempotency_key=request.idempotency_key.strip(),
            spec=spec,
            profile_snapshot_id=None,
        )
        total_plan = _plan_payload(session, plan)
    return {
        "schema_version": "p1-b30.multicourse-paths.v1",
        "run_key": request.idempotency_key.strip(),
        "status": "completed" if not failed_subjects and validation["status"] == "valid" else "partial" if ready_subjects else "failed",
        "subjects": subjects,
        "total_plan": total_plan,
        "total_validation": validation,
        "failed_subject_count": len(failed_subjects),
        "model_policy": {
            "model": "deepseek-v4-flash",
            "thinking": "enabled",
            "reasoning_effort": "max",
            "allow_fallback": False,
        },
    }
