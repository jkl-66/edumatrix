"""Privacy-minimized, course-scoped model operations aggregation."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Any

from app.database import (
    DBCourse, DBCourseMembership, DBGenerationTask, DBModelCall,
    DBModelPriceVersion, DBModelQuotaBucket, DBUser, DBWorkerLease,
)
from app.identity import normalize_role

SLA_VERSION = "model-ops-demo-sla-1.0.0"
SLA_DEFINITIONS = {
    "success_rate": {
        "name": "调用成功率", "formula": "completed_calls / terminal_calls * 100%",
        "threshold": 95.0, "unit": "%", "direction": "gte",
        "rationale": "比赛演示告警阈值，用于暴露失败调用；不代表生产 SLA 承诺。",
    },
    "p95_latency_ms": {
        "name": "P95 调用耗时", "formula": "terminal_call_duration_ms 的 nearest-rank P95",
        "threshold": 15000, "unit": "ms", "direction": "lte",
        "rationale": "比赛演示交互等待阈值；不代表供应商或企业生产 SLA。",
    },
}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") + ("Z" if value and value.tzinfo is None else "") if value else None


def managed_course_ids(session: Any, actor: DBUser) -> list[str] | None:
    if normalize_role(actor.role) == "admin":
        return None
    owned = {row[0] for row in session.query(DBCourse.id).filter_by(owner_public_id=actor.public_id).all()}
    memberships = session.query(DBCourseMembership.course_id).filter(
        DBCourseMembership.user_public_id == actor.public_id,
        DBCourseMembership.status == "active",
        DBCourseMembership.role.in_(("admin", "teacher", "assistant")),
    ).all()
    return sorted(owned | {row[0] for row in memberships})


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, ceil(percentile * len(ordered)) - 1)]


def _costs(rows: list[DBModelCall]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in rows:
        currency = row.cost_currency or "UNKNOWN"
        totals[currency] = round(totals.get(currency, 0.0) + float(row.estimated_cost or 0), 8)
    return totals


def _safe_input_summary(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    safe: dict[str, Any] = {}
    for key in ("operation", "operation_scope", "content_included", "user_data_included", "fields", "field_names", "item_count", "source_count"):
        item = source.get(key)
        if isinstance(item, (bool, int, float)) or item is None:
            safe[key] = item
        elif isinstance(item, str):
            safe[key] = item[:128]
        elif isinstance(item, list) and all(isinstance(entry, str) for entry in item[:50]):
            safe[key] = [entry[:64] for entry in item[:50]]
    safe["summary_fields_disclosed"] = sorted(safe)
    return safe


def dashboard(session: Any, *, actor: DBUser, days: int = 7, now: datetime | None = None) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(tzinfo=None)
    start = now - timedelta(days=days)
    allowed = managed_course_ids(session, actor)
    query = session.query(DBModelCall).filter(DBModelCall.created_at >= start, DBModelCall.created_at <= now)
    task_query = session.query(DBGenerationTask).filter(DBGenerationTask.created_at >= start, DBGenerationTask.created_at <= now)
    if allowed is not None:
        query = query.filter(DBModelCall.course_id.in_(allowed)) if allowed else query.filter(False)
        task_query = task_query.filter(DBGenerationTask.course_id.in_(allowed)) if allowed else task_query.filter(False)
    calls = query.order_by(DBModelCall.created_at.desc(), DBModelCall.id.desc()).all()
    tasks = task_query.all()
    terminal = [row for row in calls if row.status in {"completed", "failed"}]
    completed = [row for row in terminal if row.status == "completed"]
    success_rate = round(len(completed) * 100 / len(terminal), 2) if terminal else None
    p95 = _percentile([int(row.duration_ms or 0) for row in terminal], .95)

    groups: dict[tuple[str, str, str], list[DBModelCall]] = defaultdict(list)
    for row in calls:
        groups[(row.provider, row.model, row.capability)].append(row)
    breakdown = []
    for (provider, model, capability), rows in sorted(groups.items()):
        done = [row for row in rows if row.status in {"completed", "failed"}]
        ok = sum(row.status == "completed" for row in done)
        breakdown.append({
            "provider": provider, "model": model, "capability": capability,
            "call_count": len(rows), "success_rate": round(ok * 100 / len(done), 2) if done else None,
            "input_tokens": sum(row.input_tokens or 0 for row in rows),
            "output_tokens": sum(row.output_tokens or 0 for row in rows),
            "estimated_by_currency": _costs(rows),
            "p95_latency_ms": _percentile([int(row.duration_ms or 0) for row in done], .95),
        })

    stale_tasks = [row for row in tasks if row.status == "running" and (row.updated_at or row.created_at) < now - timedelta(minutes=10)]
    unpriced = sum((row.pricing_version or "unpriced") == "unpriced" for row in calls)
    alerts = []
    if success_rate is not None and success_rate < SLA_DEFINITIONS["success_rate"]["threshold"]:
        alerts.append({"severity": "high", "code": "success_rate_below_demo_threshold", "message": "调用成功率低于演示阈值。"})
    if p95 is not None and p95 > SLA_DEFINITIONS["p95_latency_ms"]["threshold"]:
        alerts.append({"severity": "medium", "code": "latency_above_demo_threshold", "message": "P95 调用耗时高于演示阈值。"})
    if stale_tasks:
        alerts.append({"severity": "high", "code": "stale_running_tasks", "message": f"{len(stale_tasks)} 个运行任务超过 10 分钟未更新。"})
    if unpriced:
        alerts.append({"severity": "medium", "code": "unpriced_calls", "message": f"{unpriced} 次调用没有冻结价格版本。"})

    quota_query = session.query(DBModelQuotaBucket).filter(DBModelQuotaBucket.utc_day >= start.date().isoformat())
    if allowed is not None:
        quota_query = quota_query.filter(DBModelQuotaBucket.scope_type == "course", DBModelQuotaBucket.scope_key.in_(allowed)) if allowed else quota_query.filter(False)
    quotas = quota_query.order_by(DBModelQuotaBucket.updated_at.desc()).limit(100).all()
    prices = session.query(DBModelPriceVersion).filter_by(active=True).order_by(DBModelPriceVersion.provider, DBModelPriceVersion.model).all()
    leases = session.query(DBWorkerLease).join(DBGenerationTask, DBWorkerLease.task_id == DBGenerationTask.id)
    if allowed is not None:
        leases = leases.filter(DBGenerationTask.course_id.in_(allowed)) if allowed else leases.filter(False)

    return {
        "schema_version": "next.model-operations-dashboard.v1", "generated_at": _iso(now),
        "scope": {"type": "global" if allowed is None else "managed_courses", "course_ids": None if allowed is None else allowed, "course_count": None if allowed is None else len(allowed)},
        "window": {"days": days, "start": _iso(start), "end": _iso(now)},
        "truthfulness": {"costs_are_estimates": True, "provider_invoice": False, "sla_is_demo_definition": True, "raw_prompts_included": False, "raw_outputs_included": False},
        "summary": {"calls": len(calls), "terminal_calls": len(terminal), "completed_calls": len(completed), "failed_calls": sum(row.status == "failed" for row in terminal), "input_tokens": sum(row.input_tokens or 0 for row in calls), "output_tokens": sum(row.output_tokens or 0 for row in calls), "estimated_by_currency": _costs(calls), "unpriced_calls": unpriced},
        "sla": {"version": SLA_VERSION, "sample_size": len(terminal), "metrics": {"success_rate": {**SLA_DEFINITIONS["success_rate"], "value": success_rate}, "p95_latency_ms": {**SLA_DEFINITIONS["p95_latency_ms"], "value": p95}}},
        "task_health": {"counts": {status: sum(row.status == status for row in tasks) for status in ("queued", "running", "completed", "failed", "cancelled")}, "stale_running_count": len(stale_tasks), "active_lease_count": leases.filter(DBWorkerLease.status == "active").count()},
        "breakdown": breakdown, "alerts": alerts,
        "quota_buckets": [{"scope_type": row.scope_type, "scope_key": row.scope_key, "utc_day": row.utc_day, "call_count": row.call_count, "reserved_tokens": row.reserved_tokens, "reserved_cost": row.reserved_cost, "configured_limit": None, "utilization": None} for row in quotas],
        "active_price_versions": [{"provider": row.provider, "model": row.model, "version": row.version, "currency": row.currency, "source_label": row.source_label} for row in prices],
        "recent_calls": [{"id": row.id, "trace_id": row.trace_id, "course_id": row.course_id, "capability": row.capability, "provider": row.provider, "model": row.model, "status": row.status, "input_tokens": row.input_tokens, "output_tokens": row.output_tokens, "estimated_cost": row.estimated_cost, "currency": row.cost_currency, "duration_ms": row.duration_ms, "error_code": row.error_code, "created_at": _iso(row.created_at), "input_summary": _safe_input_summary(row.input_summary)} for row in calls[:50]],
    }
