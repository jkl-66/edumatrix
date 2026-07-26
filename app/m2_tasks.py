"""Persistent M2 golden-task state machine built on the M1 task tables."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.database import DBGenerationTask, DBLearningEvent, DBTaskEvent, DBTaskStep
from app.m1_repository import append_task_event, create_generation_task, create_task_step
from app.m2_context import assemble_verified_context
from app.m2_contracts import GenerationContext


M2_GOLDEN_CAPABILITY = "m2.golden_loop.execute_verified"
M2_GOLDEN_STEPS = (
    (1, "theory_professor", "lesson.generate_verified"),
    (2, "lab_instructor", "lab_guide.generate_verified"),
    (3, "examiner", "tiered_quiz.generate_verified"),
    (4, "quality_judge", "m2.bundle.verify"),
)


class M2TaskStateError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _fail(code: str, message: str) -> None:
    raise M2TaskStateError(code, message)


def _owned_task(session: Any, task_id: str, owner_public_id: str) -> DBGenerationTask:
    task = session.query(DBGenerationTask).filter_by(id=task_id).first()
    if task is None:
        _fail("task_not_found", "M2 golden task does not exist")
    if task.owner_public_id != owner_public_id:
        _fail("task_forbidden", "M2 golden task belongs to another owner")
    if task.capability != M2_GOLDEN_CAPABILITY:
        _fail("task_capability_mismatch", "task is not an M2 golden-loop task")
    return task


def _latest_steps(session: Any, task_id: str) -> dict[int, DBTaskStep]:
    rows = (
        session.query(DBTaskStep)
        .filter_by(task_id=task_id)
        .order_by(DBTaskStep.sequence, DBTaskStep.attempt)
        .all()
    )
    latest: dict[int, DBTaskStep] = {}
    for row in rows:
        latest[row.sequence] = row
    return latest


def _context_event(session: Any, task_id: str) -> DBTaskEvent | None:
    return session.query(DBTaskEvent).filter_by(
        task_id=task_id,
        event_type="m2.context.verified",
    ).first()


def create_golden_task(
    session: Any,
    *,
    context: GenerationContext,
    idempotency_key: str,
    model: str = "",
) -> tuple[DBGenerationTask, bool]:
    verified = assemble_verified_context(
        session,
        **context.model_dump(exclude={"quality_mode"}),
    )
    task, created = create_generation_task(
        session,
        owner_public_id=verified.owner_public_id,
        capability=M2_GOLDEN_CAPABILITY,
        idempotency_key=idempotency_key,
        course_id=verified.course_id,
        model=model,
        trace_id=None,
    )
    expected_context = verified.model_dump(mode="json")
    if not created:
        event = _context_event(session, task.id)
        if (
            task.capability != M2_GOLDEN_CAPABILITY
            or task.course_id != verified.course_id
            or task.model != model
            or event is None
            or (event.payload or {}).get("context") != expected_context
        ):
            _fail("idempotency_conflict", "idempotency key is bound to a different task request")
        return task, False

    append_task_event(
        session,
        task_id=task.id,
        event_type="m2.context.verified",
        payload={"context": expected_context},
    )
    for sequence, role, capability in M2_GOLDEN_STEPS:
        create_task_step(
            session,
            task_id=task.id,
            sequence=sequence,
            agent_role=role,
            tool_name=capability,
            input_summary=f"M2 verified step: {capability}",
        )
    session.flush()
    return task, True


def start_golden_task(session: Any, *, task_id: str, owner_public_id: str) -> DBGenerationTask:
    task = _owned_task(session, task_id, owner_public_id)
    if task.status == "running":
        return task
    if task.status != "queued":
        _fail("task_not_startable", f"cannot start task from {task.status}")
    task.status = "running"
    task.started_at = _now()
    task.failure_code = ""
    task.failure_reason = ""
    append_task_event(
        session,
        task_id=task.id,
        event_type="generation_task.started",
        payload={"status": task.status},
    )
    session.flush()
    return task


def start_task_step(
    session: Any,
    *,
    task_id: str,
    owner_public_id: str,
    sequence: int,
) -> DBTaskStep:
    task = _owned_task(session, task_id, owner_public_id)
    if task.status != "running":
        _fail("task_not_running", "task must be running before a step starts")
    step = _latest_steps(session, task.id).get(sequence)
    if step is None:
        _fail("step_not_found", "task step does not exist")
    if step.status == "running":
        return step
    if step.status != "pending":
        _fail("step_not_startable", f"cannot start step from {step.status}")
    step.status = "running"
    step.started_at = _now()
    append_task_event(
        session,
        task_id=task.id,
        step_id=step.id,
        event_type="task_step.started",
        payload={"sequence": step.sequence, "attempt": step.attempt},
    )
    session.flush()
    return step


def fail_task_step(
    session: Any,
    *,
    task_id: str,
    owner_public_id: str,
    sequence: int,
    error_code: str,
    error_message: str,
    retryable: bool = True,
) -> DBTaskStep:
    task = _owned_task(session, task_id, owner_public_id)
    step = _latest_steps(session, task.id).get(sequence)
    if step is None:
        _fail("step_not_found", "task step does not exist")
    if step.status != "running":
        _fail("step_not_running", "only a running step can fail")
    step.status = "failed"
    step.error_code = error_code
    step.error_message = error_message
    step.completed_at = _now()
    append_task_event(
        session,
        task_id=task.id,
        step_id=step.id,
        event_type="task_step.failed",
        payload={
            "sequence": step.sequence,
            "attempt": step.attempt,
            "error_code": error_code,
            "retryable": retryable,
        },
    )
    if not retryable:
        task.status = "failed"
        task.failure_code = error_code
        task.failure_reason = error_message
        task.completed_at = _now()
        append_task_event(
            session,
            task_id=task.id,
            event_type="generation_task.failed",
            payload={"failure_code": error_code, "failed_sequence": sequence},
        )
    session.flush()
    return step


def retry_task_step(
    session: Any,
    *,
    task_id: str,
    owner_public_id: str,
    sequence: int,
) -> DBTaskStep:
    task = _owned_task(session, task_id, owner_public_id)
    if task.status != "running":
        _fail("task_not_running", "only a running task can retry a step")
    previous = _latest_steps(session, task.id).get(sequence)
    if previous is None:
        _fail("step_not_found", "task step does not exist")
    if previous.status != "failed":
        _fail("step_not_retryable", "latest step attempt has not failed")
    retry = create_task_step(
        session,
        task_id=task.id,
        sequence=previous.sequence,
        attempt=previous.attempt + 1,
        agent_role=previous.agent_role,
        tool_name=previous.tool_name,
        input_summary=previous.input_summary,
        parent_step_id=previous.id,
    )
    append_task_event(
        session,
        task_id=task.id,
        step_id=retry.id,
        event_type="task_step.retry_scheduled",
        payload={"sequence": retry.sequence, "attempt": retry.attempt, "previous_step_id": previous.id},
    )
    session.flush()
    return retry


def schedule_rework_step(
    session: Any,
    *,
    task_id: str,
    owner_public_id: str,
    sequence: int,
    reason_code: str,
) -> DBTaskStep:
    """Create a new attempt without mutating the completed version that failed review."""
    task = _owned_task(session, task_id, owner_public_id)
    if task.status != "running":
        _fail("task_not_running", "only a running task can schedule rework")
    previous = _latest_steps(session, task.id).get(sequence)
    if previous is None:
        _fail("step_not_found", "task step does not exist")
    if previous.status != "completed":
        _fail("step_not_reworkable", "only a completed step can be sent back for rework")
    rework = create_task_step(
        session,
        task_id=task.id,
        sequence=previous.sequence,
        attempt=previous.attempt + 1,
        agent_role=previous.agent_role,
        tool_name=previous.tool_name,
        input_summary=previous.input_summary,
        parent_step_id=previous.id,
    )
    append_task_event(
        session,
        task_id=task.id,
        step_id=rework.id,
        event_type="task_step.rework_scheduled",
        payload={
            "sequence": rework.sequence,
            "attempt": rework.attempt,
            "previous_step_id": previous.id,
            "reason_code": reason_code,
        },
    )
    completed = sum(row.status == "completed" for row in _latest_steps(session, task.id).values())
    task.progress = completed / len(M2_GOLDEN_STEPS)
    session.flush()
    return rework


def complete_task_step(
    session: Any,
    *,
    task_id: str,
    owner_public_id: str,
    sequence: int,
    output_artifact_version_id: str | None = None,
) -> DBTaskStep:
    task = _owned_task(session, task_id, owner_public_id)
    step = _latest_steps(session, task.id).get(sequence)
    if step is None:
        _fail("step_not_found", "task step does not exist")
    if step.status == "completed":
        if step.output_artifact_version_id != output_artifact_version_id:
            _fail("step_completion_conflict", "completed step is bound to another output version")
        return step
    if step.status != "running":
        _fail("step_not_running", "only a running step can complete")
    step.status = "completed"
    step.output_artifact_version_id = output_artifact_version_id
    step.completed_at = _now()
    append_task_event(
        session,
        task_id=task.id,
        step_id=step.id,
        event_type="task_step.completed",
        payload={
            "sequence": step.sequence,
            "attempt": step.attempt,
            "output_artifact_version_id": output_artifact_version_id,
        },
    )
    session.flush()
    completed = sum(row.status == "completed" for row in _latest_steps(session, task.id).values())
    task.progress = completed / len(M2_GOLDEN_STEPS)
    session.flush()
    return step


def complete_golden_task(session: Any, *, task_id: str, owner_public_id: str) -> DBGenerationTask:
    task = _owned_task(session, task_id, owner_public_id)
    if task.status == "completed":
        return task
    if task.status != "running":
        _fail("task_not_running", "only a running task can complete")
    latest = _latest_steps(session, task.id)
    if set(latest) != {step[0] for step in M2_GOLDEN_STEPS} or any(
        step.status != "completed" for step in latest.values()
    ):
        _fail("task_steps_incomplete", "all latest logical step attempts must complete")
    feedback = session.query(DBLearningEvent).filter_by(
        trace_id=task.trace_id,
        event_type="m2.learning_feedback.recorded",
    ).first()
    if feedback is None:
        _fail("task_feedback_missing", "M2 golden task cannot complete before feedback is recorded")
    task.status = "completed"
    task.progress = 1.0
    task.completed_at = _now()
    append_task_event(
        session,
        task_id=task.id,
        event_type="generation_task.completed",
        payload={"status": task.status, "progress": task.progress},
    )
    session.flush()
    return task


def resume_golden_task(
    session: Any,
    *,
    task_id: str,
    owner_public_id: str,
    after_event_sequence: int = 0,
) -> dict[str, Any]:
    task = _owned_task(session, task_id, owner_public_id)
    latest = _latest_steps(session, task.id)
    events = (
        session.query(DBTaskEvent)
        .filter(DBTaskEvent.task_id == task.id, DBTaskEvent.sequence > after_event_sequence)
        .order_by(DBTaskEvent.sequence)
        .all()
    )
    return {
        "task_id": task.id,
        "trace_id": task.trace_id,
        "status": task.status,
        "progress": task.progress,
        "latest_steps": [
            {
                "id": step.id,
                "sequence": step.sequence,
                "attempt": step.attempt,
                "status": step.status,
                "capability": step.tool_name,
                "output_artifact_version_id": step.output_artifact_version_id,
                "error_code": step.error_code,
            }
            for step in sorted(latest.values(), key=lambda item: item.sequence)
        ],
        "events": [
            {
                "sequence": event.sequence,
                "step_id": event.step_id,
                "event_type": event.event_type,
                "payload": event.payload or {},
            }
            for event in events
        ],
        "last_event_sequence": events[-1].sequence if events else after_event_sequence,
    }
