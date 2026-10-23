"""Versioned model pricing and recoverable background-worker operations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import secrets

from pydantic import Field

from app.database import (
    DBGenerationTask,
    DBModelCall,
    DBModelPriceVersion,
    DBModelQuotaBucket,
    DBTaskEvent,
    DBTaskStep,
    DBWorkerLease,
)
from app.m1_repository import append_task_event, create_task_step
from app.m2_contracts import StrictModel


class OperationsError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise OperationsError(code, message)


def _now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return current.astimezone(timezone.utc).replace(tzinfo=None)


class PriceVersionInput(StrictModel):
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    currency: str = Field(default="USD", min_length=3, max_length=8)
    input_cost_per_million: float = Field(ge=0)
    output_cost_per_million: float = Field(ge=0)
    source_url: str = Field(default="", max_length=2000)
    source_label: str = Field(min_length=1, max_length=256)
    effective_at: datetime


class WorkerClaimInput(StrictModel):
    worker_id: str = Field(min_length=3, max_length=128)
    lease_seconds: int = Field(default=60, ge=15, le=900)


class WorkerHeartbeatInput(StrictModel):
    worker_id: str = Field(min_length=3, max_length=128)
    lease_token: str = Field(min_length=32, max_length=64)
    lease_seconds: int = Field(default=60, ge=15, le=900)


def register_price_version(session: Any, spec: PriceVersionInput) -> tuple[DBModelPriceVersion, bool]:
    existing = session.query(DBModelPriceVersion).filter_by(
        provider=spec.provider, model=spec.model, version=spec.version,
    ).first()
    expected = spec.model_dump(mode="json")
    if existing is not None:
        actual = {
            "provider": existing.provider, "model": existing.model, "version": existing.version,
            "currency": existing.currency,
            "input_cost_per_million": existing.input_cost_per_million,
            "output_cost_per_million": existing.output_cost_per_million,
            "source_url": existing.source_url, "source_label": existing.source_label,
            "effective_at": existing.effective_at.replace(tzinfo=timezone.utc).isoformat(),
        }
        expected["effective_at"] = spec.effective_at.astimezone(timezone.utc).isoformat()
        if actual != expected:
            _fail("price_version_conflict", "price version is immutable and already has different values")
        return existing, False
    session.query(DBModelPriceVersion).filter_by(
        provider=spec.provider, model=spec.model, active=True,
    ).update({"active": False}, synchronize_session=False)
    row = DBModelPriceVersion(
        **spec.model_dump(exclude={"effective_at"}),
        effective_at=_now(spec.effective_at), active=True,
    )
    session.add(row)
    session.flush()
    return row, True


def pricing_payload(row: DBModelPriceVersion) -> dict[str, Any]:
    return {
        "id": row.id, "provider": row.provider, "model": row.model,
        "version": row.version, "currency": row.currency,
        "input_cost_per_million": row.input_cost_per_million,
        "output_cost_per_million": row.output_cost_per_million,
        "source_url": row.source_url, "source_label": row.source_label,
        "effective_at": row.effective_at.replace(tzinfo=timezone.utc).isoformat(),
        "active": row.active,
    }


def operations_dashboard(session: Any) -> dict[str, Any]:
    tasks = session.query(DBGenerationTask).all()
    calls = session.query(DBModelCall).all()
    leases = session.query(DBWorkerLease).order_by(DBWorkerLease.leased_at.desc()).limit(50).all()
    prices = session.query(DBModelPriceVersion).order_by(
        DBModelPriceVersion.provider, DBModelPriceVersion.model, DBModelPriceVersion.effective_at.desc(),
    ).all()
    quotas = session.query(DBModelQuotaBucket).order_by(DBModelQuotaBucket.updated_at.desc()).limit(50).all()
    estimated_by_currency: dict[str, float] = {}
    for row in calls:
        currency = row.cost_currency or "UNKNOWN"
        estimated_by_currency[currency] = round(
            estimated_by_currency.get(currency, 0.0) + float(row.estimated_cost or 0), 8,
        )
    priced_calls = sum((row.pricing_version or "unpriced") != "unpriced" for row in calls)
    return {
        "schema_version": "next.model-operations.v1",
        "cost_statement": "Estimated from frozen price versions; not a provider invoice.",
        "currency_note": "Totals are grouped by currency and must not be converted without an explicit rate version.",
        "task_counts": {status: sum(row.status == status for row in tasks) for status in ("queued", "running", "completed", "failed", "cancelled")},
        "model_calls": {
            "count": len(calls), "priced_count": priced_calls,
            "unpriced_count": len(calls) - priced_calls,
            "estimated_by_currency": estimated_by_currency,
            "actual_invoice_total": None,
        },
        "price_versions": [pricing_payload(row) for row in prices],
        "leases": [{
            "id": row.id, "task_id": row.task_id, "worker_id": row.worker_id,
            "status": row.status, "attempt": row.attempt,
            "heartbeat_at": row.heartbeat_at.isoformat(), "leased_until": row.leased_until.isoformat(),
        } for row in leases],
        "quota_buckets": [{
            "scope_type": row.scope_type, "scope_key": row.scope_key,
            "utc_day": row.utc_day, "call_count": row.call_count,
            "reserved_tokens": row.reserved_tokens, "reserved_cost": row.reserved_cost,
        } for row in quotas],
        "raw_prompts_persisted": False,
        "raw_outputs_persisted": False,
    }


def claim_next_task(session: Any, claim: WorkerClaimInput, *, now: datetime | None = None) -> dict[str, Any] | None:
    current = _now(now)
    candidates = session.query(DBGenerationTask).filter(
        DBGenerationTask.status == "queued",
        DBGenerationTask.capability.like("m5.capability.%"),
    ).order_by(DBGenerationTask.created_at, DBGenerationTask.id).all()
    for candidate in candidates:
        updated = session.query(DBGenerationTask).filter_by(id=candidate.id, status="queued").update({
            "status": "running", "started_at": current,
        }, synchronize_session="fetch")
        if updated != 1:
            continue
        attempt = session.query(DBWorkerLease).filter_by(task_id=candidate.id).count() + 1
        token = secrets.token_hex(24)
        lease = DBWorkerLease(
            task_id=candidate.id, worker_id=claim.worker_id, lease_token=token,
            attempt=attempt, status="active", leased_at=current, heartbeat_at=current,
            leased_until=current + timedelta(seconds=claim.lease_seconds),
        )
        session.add(lease)
        append_task_event(session, task_id=candidate.id, event_type="worker.lease_acquired", payload={
            "worker_id": claim.worker_id, "attempt": attempt,
            "lease_seconds": claim.lease_seconds, "lease_token_persisted_in_event": False,
        })
        session.flush()
        return {
            "task_id": candidate.id, "trace_id": candidate.trace_id,
            "lease_id": lease.id, "lease_token": token, "worker_id": claim.worker_id,
            "attempt": attempt, "leased_until": lease.leased_until.isoformat(),
        }
    return None


def heartbeat_lease(session: Any, lease_id: str, heartbeat: WorkerHeartbeatInput, *, now: datetime | None = None) -> dict[str, Any]:
    current = _now(now)
    row = session.query(DBWorkerLease).filter_by(id=lease_id).first()
    if row is None:
        _fail("worker_lease_unknown", "worker lease does not exist")
    if row.worker_id != heartbeat.worker_id or not secrets.compare_digest(row.lease_token, heartbeat.lease_token):
        _fail("worker_lease_forbidden", "worker lease credentials do not match")
    if row.status != "active" or row.leased_until <= current:
        _fail("worker_lease_expired", "worker lease is no longer active")
    row.heartbeat_at = current
    row.leased_until = current + timedelta(seconds=heartbeat.lease_seconds)
    append_task_event(session, task_id=row.task_id, event_type="worker.heartbeat", payload={
        "worker_id": row.worker_id, "attempt": row.attempt,
        "lease_seconds": heartbeat.lease_seconds,
    })
    session.flush()
    return {"lease_id": row.id, "status": row.status, "leased_until": row.leased_until.isoformat()}


def release_lease(session: Any, lease_id: str, heartbeat: WorkerHeartbeatInput, *, now: datetime | None = None) -> dict[str, Any]:
    current = _now(now)
    row = session.query(DBWorkerLease).filter_by(id=lease_id).first()
    if row is None:
        _fail("worker_lease_unknown", "worker lease does not exist")
    if row.worker_id != heartbeat.worker_id or not secrets.compare_digest(row.lease_token, heartbeat.lease_token):
        _fail("worker_lease_forbidden", "worker lease credentials do not match")
    if row.status != "active":
        _fail("worker_lease_not_active", "worker lease is not active")
    row.status = "released"
    row.released_at = current
    append_task_event(session, task_id=row.task_id, event_type="worker.lease_released", payload={
        "worker_id": row.worker_id, "attempt": row.attempt,
    })
    session.flush()
    return {"lease_id": row.id, "status": row.status}


def recover_expired_leases(session: Any, *, now: datetime | None = None) -> list[str]:
    current = _now(now)
    rows = session.query(DBWorkerLease).filter(
        DBWorkerLease.status == "active", DBWorkerLease.leased_until <= current,
    ).order_by(DBWorkerLease.leased_until).all()
    recovered = []
    for row in rows:
        row.status = "expired"
        row.released_at = current
        task = session.query(DBGenerationTask).filter_by(id=row.task_id).first()
        if task is not None and task.status == "running":
            running_steps = session.query(DBTaskStep).filter_by(
                task_id=task.id, status="running",
            ).order_by(DBTaskStep.sequence, DBTaskStep.attempt).all()
            for step in running_steps:
                step.status = "failed"
                step.error_code = "worker_lease_expired"
                step.error_message = ""
                step.completed_at = current
                retry = create_task_step(
                    session, task_id=task.id, sequence=step.sequence,
                    attempt=step.attempt + 1, agent_role=step.agent_role,
                    tool_name=step.tool_name, input_summary=step.input_summary,
                    parent_step_id=step.id,
                )
                append_task_event(
                    session, task_id=task.id, step_id=step.id,
                    event_type="task_step.failed",
                    payload={
                        "sequence": step.sequence, "attempt": step.attempt,
                        "error_code": "worker_lease_expired", "retryable": True,
                    },
                )
                append_task_event(
                    session, task_id=task.id, step_id=retry.id,
                    event_type="task_step.retry_scheduled",
                    payload={
                        "sequence": retry.sequence, "attempt": retry.attempt,
                        "previous_step_id": step.id, "reason_code": "worker_lease_expired",
                    },
                )
            task.status = "queued"
            task.started_at = None
            append_task_event(session, task_id=task.id, event_type="worker.lease_expired", payload={
                "worker_id": row.worker_id, "attempt": row.attempt, "task_requeued": True,
            })
            recovered.append(task.id)
    session.flush()
    return recovered


def cancel_task(session: Any, *, task_id: str, owner_public_id: str, now: datetime | None = None) -> DBGenerationTask:
    task = session.query(DBGenerationTask).filter_by(id=task_id).first()
    if task is None:
        _fail("m5_task_unknown", "M5 capability task does not exist")
    if task.owner_public_id != owner_public_id:
        _fail("m5_task_forbidden", "M5 capability task belongs to another owner")
    if task.status == "cancelled":
        return task
    if task.status not in {"queued", "running"}:
        _fail("m5_task_not_cancellable", f"cannot cancel task from {task.status}")
    current = _now(now)
    task.status = "cancelled"
    task.completed_at = current
    for lease in session.query(DBWorkerLease).filter_by(task_id=task.id, status="active").all():
        lease.status = "cancelled"
        lease.released_at = current
    append_task_event(session, task_id=task.id, event_type="generation_task.cancelled", payload={"owner_requested": True})
    session.flush()
    return task
