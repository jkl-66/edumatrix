"""Generic persistent R3-R5 task compiler and resumable lifecycle for M5."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.database import DBGenerationTask, DBTaskEvent, DBTaskStep
from app.m1_repository import append_task_event, create_generation_task, create_task_step
from app.m5_capabilities import (
    Capability,
    RouteDecision,
    RoutingRequest,
    RuntimeAvailability,
    route_capability,
)


M5_TASK_CAPABILITY_PREFIX = "m5.capability."


class M5TaskError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise M5TaskError(code, message)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _owned_task(session: Any, task_id: str, owner_public_id: str) -> DBGenerationTask:
    task = session.query(DBGenerationTask).filter_by(id=task_id).first()
    if task is None:
        _fail("m5_task_unknown", "M5 capability task does not exist")
    if task.owner_public_id != owner_public_id:
        _fail("m5_task_forbidden", "M5 capability task belongs to another owner")
    if not task.capability.startswith(M5_TASK_CAPABILITY_PREFIX):
        _fail("m5_task_capability_mismatch", "task is not an M5 capability task")
    return task


def _latest_steps(session: Any, task_id: str) -> dict[int, DBTaskStep]:
    rows = session.query(DBTaskStep).filter_by(task_id=task_id).order_by(
        DBTaskStep.sequence, DBTaskStep.attempt,
    ).all()
    latest = {}
    for row in rows:
        latest[row.sequence] = row
    return latest


def _step_blueprint(request: RoutingRequest, decision: RouteDecision) -> tuple[tuple[str, str], ...]:
    if decision.route_level == "R3":
        return (
            ("context_assembler", "m5.context.assemble"),
            ("planning_agent", f"m5.{decision.capability.value}.draft"),
            ("policy_validator", "m5.plan.policy_validate"),
            ("artifact_committer", "m5.plan.commit_confirmed"),
        )
    if decision.route_level == "R4":
        return (
            ("context_assembler", "m5.context.assemble"),
            ("capability_agent", f"m5.{decision.capability.value}.generate"),
            ("quality_checker", f"m5.{decision.capability.value}.validate"),
            ("artifact_committer", "m5.artifact.commit"),
        )
    capabilities = request.compound_capabilities
    steps: list[tuple[str, str]] = [
        ("context_assembler", "m5.context.assemble"),
        ("task_planner", "m5.compound.plan"),
    ]
    for capability in capabilities:
        steps.append(("capability_agent", f"m5.{capability.value}.generate"))
        steps.append(("quality_checker", f"m5.{capability.value}.validate"))
    steps.extend((
        ("decision_agent", "m5.compound.aggregate"),
        ("artifact_committer", "m5.bundle.commit"),
    ))
    return tuple(steps)


def _contract_payload(request: RoutingRequest, decision: RouteDecision) -> dict[str, Any]:
    return {
        "contract": request.contract.model_dump(mode="json"),
        "route": decision.model_dump(mode="json"),
        "compound_capabilities": [item.value for item in request.compound_capabilities],
        "message_included": False,
    }


def create_capability_task(
    session: Any,
    *,
    owner_public_id: str,
    request: RoutingRequest,
    runtime: RuntimeAvailability,
    model: str = "",
) -> tuple[DBGenerationTask, bool]:
    decision = route_capability(request, runtime)
    if decision.status == "unavailable":
        _fail("m5_route_unavailable", f"route dependencies unavailable: {', '.join(decision.blockers)}")
    if decision.status == "confirmation_required":
        _fail("m5_confirmation_required", "route requires explicit confirmation before task creation")
    if decision.route_level not in {"R3", "R4", "R5"}:
        _fail("m5_route_not_background", f"{decision.route_level} must not create a background task")

    task, created = create_generation_task(
        session,
        owner_public_id=owner_public_id,
        capability=f"{M5_TASK_CAPABILITY_PREFIX}{decision.capability.value}",
        idempotency_key=request.contract.idempotency_key,
        course_id=request.contract.course_id,
        model=model,
    )
    expected = _contract_payload(request, decision)
    if not created:
        locked = session.query(DBTaskEvent).filter_by(
            task_id=task.id, event_type="m5.contract.locked",
        ).first()
        if (
            locked is None
            or locked.payload != expected
            or task.model != model
            or task.course_id != request.contract.course_id
        ):
            _fail("m5_task_idempotency_conflict", "idempotency key is bound to another M5 task request")
        return task, False

    append_task_event(
        session, task_id=task.id, event_type="m5.contract.locked", payload=expected,
    )
    summary = (
        f"capability={decision.capability.value};quality={request.contract.quality_mode.value};"
        f"artifacts={len(request.contract.active_artifact_ids)};"
        f"documents={len(request.contract.source_document_ids)};"
        f"knowledge_points={len(request.contract.target_knowledge_point_ids)};content_included=false"
    )
    for sequence, (role, tool) in enumerate(_step_blueprint(request, decision), start=1):
        create_task_step(
            session, task_id=task.id, sequence=sequence,
            agent_role=role, tool_name=tool, input_summary=summary,
        )
    session.flush()
    return task, True


def start_capability_task(session: Any, *, task_id: str, owner_public_id: str) -> DBGenerationTask:
    task = _owned_task(session, task_id, owner_public_id)
    if task.status == "running":
        return task
    if task.status != "queued":
        _fail("m5_task_not_startable", f"cannot start task from {task.status}")
    task.status = "running"
    task.started_at = _now()
    append_task_event(session, task_id=task.id, event_type="generation_task.started", payload={"status": "running"})
    session.flush()
    return task


def start_capability_step(
    session: Any, *, task_id: str, owner_public_id: str, sequence: int,
) -> DBTaskStep:
    task = _owned_task(session, task_id, owner_public_id)
    if task.status != "running":
        _fail("m5_task_not_running", "task must be running before a step starts")
    latest = _latest_steps(session, task.id)
    step = latest.get(sequence)
    if step is None:
        _fail("m5_step_unknown", "task step does not exist")
    if any(latest[index].status != "completed" for index in range(1, sequence)):
        _fail("m5_step_dependency_incomplete", "all prior logical steps must complete")
    if step.status == "running":
        return step
    if step.status != "pending":
        _fail("m5_step_not_startable", f"cannot start step from {step.status}")
    step.status = "running"
    step.started_at = _now()
    append_task_event(
        session, task_id=task.id, step_id=step.id,
        event_type="task_step.started",
        payload={"sequence": sequence, "attempt": step.attempt, "tool": step.tool_name},
    )
    session.flush()
    return step


def complete_capability_step(
    session: Any, *, task_id: str, owner_public_id: str, sequence: int,
    output_artifact_version_id: str | None = None,
) -> DBTaskStep:
    task = _owned_task(session, task_id, owner_public_id)
    latest = _latest_steps(session, task.id)
    step = latest.get(sequence)
    if step is None or step.status != "running":
        _fail("m5_step_not_running", "only a running step can complete")
    step.status = "completed"
    step.output_artifact_version_id = output_artifact_version_id
    step.completed_at = _now()
    append_task_event(
        session, task_id=task.id, step_id=step.id, event_type="task_step.completed",
        payload={"sequence": sequence, "attempt": step.attempt, "output_artifact_version_id": output_artifact_version_id},
    )
    latest[sequence] = step
    task.progress = sum(item.status == "completed" for item in latest.values()) / len(latest)
    session.flush()
    return step


def fail_capability_step(
    session: Any, *, task_id: str, owner_public_id: str, sequence: int,
    error_code: str, retryable: bool,
) -> DBTaskStep:
    task = _owned_task(session, task_id, owner_public_id)
    step = _latest_steps(session, task.id).get(sequence)
    if step is None or step.status != "running":
        _fail("m5_step_not_running", "only a running step can fail")
    step.status = "failed"
    step.error_code = error_code
    step.error_message = ""
    step.completed_at = _now()
    append_task_event(
        session, task_id=task.id, step_id=step.id, event_type="task_step.failed",
        payload={"sequence": sequence, "attempt": step.attempt, "error_code": error_code, "retryable": retryable},
    )
    if not retryable:
        task.status = "failed"
        task.failure_code = error_code
        task.failure_reason = ""
        task.completed_at = _now()
        append_task_event(
            session, task_id=task.id, event_type="generation_task.failed",
            payload={"failure_code": error_code, "failed_sequence": sequence},
        )
    session.flush()
    return step


def retry_capability_step(
    session: Any, *, task_id: str, owner_public_id: str, sequence: int,
) -> DBTaskStep:
    task = _owned_task(session, task_id, owner_public_id)
    if task.status != "running":
        _fail("m5_task_not_running", "only a running task can retry")
    previous = _latest_steps(session, task.id).get(sequence)
    if previous is None or previous.status != "failed":
        _fail("m5_step_not_retryable", "latest step attempt has not failed")
    retry = create_task_step(
        session, task_id=task.id, sequence=sequence, attempt=previous.attempt + 1,
        agent_role=previous.agent_role, tool_name=previous.tool_name,
        input_summary=previous.input_summary, parent_step_id=previous.id,
    )
    append_task_event(
        session, task_id=task.id, step_id=retry.id,
        event_type="task_step.retry_scheduled",
        payload={"sequence": sequence, "attempt": retry.attempt, "previous_step_id": previous.id},
    )
    session.flush()
    return retry


def schedule_capability_rework(
    session: Any, *, task_id: str, owner_public_id: str, sequence: int, reason_code: str,
) -> DBTaskStep:
    task = _owned_task(session, task_id, owner_public_id)
    if task.status != "running":
        _fail("m5_task_not_running", "only a running task can schedule rework")
    previous = _latest_steps(session, task.id).get(sequence)
    if previous is None or previous.status != "completed":
        _fail("m5_step_not_reworkable", "only a completed logical step can be reworked")
    rework = create_task_step(
        session, task_id=task.id, sequence=sequence, attempt=previous.attempt + 1,
        agent_role=previous.agent_role, tool_name=previous.tool_name,
        input_summary=previous.input_summary, parent_step_id=previous.id,
    )
    append_task_event(
        session, task_id=task.id, step_id=rework.id, event_type="task_step.rework_scheduled",
        payload={
            "sequence": sequence, "attempt": rework.attempt,
            "previous_step_id": previous.id, "reason_code": reason_code,
        },
    )
    latest = _latest_steps(session, task.id)
    task.progress = sum(item.status == "completed" for item in latest.values()) / len(latest)
    session.flush()
    return rework


def complete_capability_task(session: Any, *, task_id: str, owner_public_id: str) -> DBGenerationTask:
    task = _owned_task(session, task_id, owner_public_id)
    if task.status == "completed":
        return task
    latest = _latest_steps(session, task.id)
    if task.status != "running" or not latest or any(item.status != "completed" for item in latest.values()):
        _fail("m5_task_steps_incomplete", "all latest logical steps must complete")
    task.status = "completed"
    task.progress = 1.0
    task.completed_at = _now()
    append_task_event(
        session, task_id=task.id, event_type="generation_task.completed",
        payload={"status": "completed", "progress": 1.0},
    )
    session.flush()
    return task


def resume_capability_task(
    session: Any, *, task_id: str, owner_public_id: str, after_event_sequence: int = 0,
) -> dict[str, Any]:
    task = _owned_task(session, task_id, owner_public_id)
    latest = _latest_steps(session, task.id)
    events = session.query(DBTaskEvent).filter(
        DBTaskEvent.task_id == task.id,
        DBTaskEvent.sequence > after_event_sequence,
    ).order_by(DBTaskEvent.sequence).all()
    return {
        "task_id": task.id,
        "trace_id": task.trace_id,
        "status": task.status,
        "progress": task.progress,
        "latest_steps": [{
            "id": item.id, "sequence": item.sequence, "attempt": item.attempt,
            "role": item.agent_role, "tool": item.tool_name, "status": item.status,
            "error_code": item.error_code,
            "output_artifact_version_id": item.output_artifact_version_id,
        } for item in sorted(latest.values(), key=lambda value: value.sequence)],
        "events": [{
            "sequence": event.sequence, "step_id": event.step_id,
            "event_type": event.event_type, "payload": event.payload or {},
        } for event in events],
        "last_event_sequence": events[-1].sequence if events else after_event_sequence,
    }
