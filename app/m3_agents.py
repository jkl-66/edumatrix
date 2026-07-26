"""Four-role contracts and persistent collaboration traces for M3."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import ConfigDict

from app.database import DBAgentRun, DBGenerationTask, DBTaskStep
from app.m1_repository import append_task_event, create_generation_task, create_task_step
from app.m2_context import assemble_verified_context
from app.m2_contracts import GenerationContext, StrictModel


M3_COLLABORATION_CAPABILITY = "m3.four_role_loop.execute_verified"


class M3AgentRole(str, Enum):
    DIAGNOSIS = "diagnosis"
    DOMAIN_GENERATION = "domain_generation"
    EVIDENCE_REVIEW = "evidence_review"
    DECISION_ORCHESTRATION = "decision_orchestration"


class M3AgentContract(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: M3AgentRole
    registry_id: str
    version: str
    responsibility: str
    required_input_fields: tuple[str, ...]
    output_object_types: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    forbidden_actions: tuple[str, ...]


M3_AGENT_CONTRACTS = (
    M3AgentContract(
        role=M3AgentRole.DIAGNOSIS,
        registry_id="agent-m3-diagnosis-v1",
        version="m3.diagnosis.v1",
        responsibility="Identify candidate skill gaps, evidence and uncertainty for the shared job task.",
        required_input_fields=("profile_snapshot_id", "job_task_id", "target_knowledge_point_ids"),
        output_object_types=("diagnostic_assessment", "profile_snapshot"),
        allowed_tools=("profile_snapshot.read", "profile_evidence.read", "job_task.read"),
        forbidden_actions=("publish_artifact", "declare_competence", "overwrite_profile"),
    ),
    M3AgentContract(
        role=M3AgentRole.DOMAIN_GENERATION,
        registry_id="agent-m3-domain-generation-v1",
        version="m3.domain_generation.v1",
        responsibility="Generate typed resources bound to the frozen profile, target skills and sources.",
        required_input_fields=("profile_snapshot_id", "domain_version_id", "target_knowledge_point_ids", "source_ref_ids"),
        output_object_types=("lesson", "lab_guide", "tiered_quiz"),
        allowed_tools=("source_ref.read", "artifact.create_draft", "artifact_version.append"),
        forbidden_actions=("self_publish", "change_gold_metrics", "change_capability_type"),
    ),
    M3AgentContract(
        role=M3AgentRole.EVIDENCE_REVIEW,
        registry_id="agent-m3-evidence-review-v1",
        version="m3.evidence_review.v1",
        responsibility="Split claims, challenge evidence and produce conservative structured verdicts.",
        required_input_fields=("artifact_version_ids", "source_ref_ids", "quality_rule_version"),
        output_object_types=("claim_check", "debate_round", "quality_check"),
        allowed_tools=("artifact_version.read", "source_ref.read", "quality_check.write", "debate_round.write"),
        forbidden_actions=("overwrite_generator_output", "approve_without_evidence", "assume_human_signoff"),
    ),
    M3AgentContract(
        role=M3AgentRole.DECISION_ORCHESTRATION,
        registry_id="agent-m3-decision-orchestration-v1",
        version="m3.decision_orchestration.v1",
        responsibility="Compare rule-bounded adaptation candidates using diagnosis, review and learning-event IDs.",
        required_input_fields=("profile_snapshot_id", "quality_check_ids", "learning_event_ids", "decision_rule_version"),
        output_object_types=("decision_record", "matching_report"),
        allowed_tools=("quality_check.read", "learning_event.read", "decision_record.write"),
        forbidden_actions=("rewrite_evidence", "treat_click_as_mastery", "execute_major_change_without_confirmation"),
    ),
)

_CONTRACT_BY_ROLE = {contract.role: contract for contract in M3_AGENT_CONTRACTS}
_ROLE_SEQUENCE = tuple(contract.role for contract in M3_AGENT_CONTRACTS)


class M3AgentStateError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise M3AgentStateError(code, message)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _owned_task(session: Any, task_id: str, owner_public_id: str) -> DBGenerationTask:
    task = session.query(DBGenerationTask).filter_by(id=task_id).first()
    if task is None:
        _fail("task_not_found", "M3 collaboration task does not exist")
    if task.owner_public_id != owner_public_id:
        _fail("task_forbidden", "M3 collaboration task belongs to another owner")
    if task.capability != M3_COLLABORATION_CAPABILITY:
        _fail("task_capability_mismatch", "task is not an M3 four-role task")
    return task


def _steps(session: Any, task_id: str) -> dict[int, DBTaskStep]:
    return {
        step.sequence: step
        for step in session.query(DBTaskStep)
        .filter_by(task_id=task_id)
        .order_by(DBTaskStep.sequence)
        .all()
    }


def _context_summary(context: GenerationContext, role: M3AgentRole) -> str:
    contract = _CONTRACT_BY_ROLE[role]
    summary = {
        "contract_version": contract.version,
        "role": role.value,
        "owner_public_id": context.owner_public_id,
        "course_id": context.course_id,
        "domain_version_id": context.domain_version_id,
        "profile_snapshot_id": context.profile_snapshot_id,
        "target_knowledge_point_ids": context.target_knowledge_point_ids,
        "source_ref_ids": context.source_ref_ids if role != M3AgentRole.DIAGNOSIS else [],
        "content_included": False,
    }
    return json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def create_m3_collaboration_task(
    session: Any,
    *,
    context: GenerationContext,
    idempotency_key: str,
    model: str = "",
) -> tuple[DBGenerationTask, bool]:
    verified = assemble_verified_context(session, **context.model_dump(exclude={"quality_mode"}))
    task, created = create_generation_task(
        session,
        owner_public_id=verified.owner_public_id,
        capability=M3_COLLABORATION_CAPABILITY,
        idempotency_key=idempotency_key,
        course_id=verified.course_id,
        model=model,
    )
    expected_context = verified.model_dump(mode="json")
    if not created:
        context_event = next(
            (
                event
                for event in task_events(session, task.id)
                if event.event_type == "m3.context.verified"
            ),
            None,
        )
        if (
            task.course_id != verified.course_id
            or task.model != model
            or context_event is None
            or (context_event.payload or {}).get("context") != expected_context
        ):
            _fail("idempotency_conflict", "idempotency key is bound to another M3 request")
        return task, False

    append_task_event(
        session,
        task_id=task.id,
        event_type="m3.context.verified",
        payload={"context": expected_context, "content_included": False},
    )
    for sequence, role in enumerate(_ROLE_SEQUENCE, start=1):
        contract = _CONTRACT_BY_ROLE[role]
        create_task_step(
            session,
            task_id=task.id,
            sequence=sequence,
            agent_role=role.value,
            tool_name=contract.registry_id,
            input_summary=_context_summary(verified, role),
        )
    session.flush()
    return task, True


def task_events(session: Any, task_id: str):
    from app.database import DBTaskEvent

    return session.query(DBTaskEvent).filter_by(task_id=task_id).order_by(DBTaskEvent.sequence).all()


def start_m3_collaboration_task(session: Any, *, task_id: str, owner_public_id: str) -> DBGenerationTask:
    task = _owned_task(session, task_id, owner_public_id)
    if task.status == "running":
        return task
    if task.status != "queued":
        _fail("task_not_startable", f"cannot start task from {task.status}")
    task.status = "running"
    task.started_at = _now()
    append_task_event(session, task_id=task.id, event_type="generation_task.started", payload={"status": "running"})
    session.flush()
    return task


def start_m3_agent_run(
    session: Any,
    *,
    task_id: str,
    owner_public_id: str,
    role: M3AgentRole,
    model: str = "",
) -> DBAgentRun:
    task = _owned_task(session, task_id, owner_public_id)
    if task.status != "running":
        _fail("task_not_running", "M3 collaboration task must be running")
    sequence = _ROLE_SEQUENCE.index(role) + 1
    steps = _steps(session, task.id)
    step = steps[sequence]
    if any(steps[index].status != "completed" for index in range(1, sequence)):
        _fail("role_dependency_incomplete", "all prior role runs must complete")
    existing = session.query(DBAgentRun).filter_by(task_id=task.id, role=role.value).first()
    if existing is not None:
        return existing
    if step.status != "pending":
        _fail("role_not_startable", f"role step is {step.status}")
    step.status = "running"
    step.started_at = _now()
    run = DBAgentRun(
        task_id=task.id,
        trace_id=task.trace_id,
        role=role.value,
        agent_version=_CONTRACT_BY_ROLE[role].version,
        input_summary=step.input_summary,
        tool_names=list(_CONTRACT_BY_ROLE[role].allowed_tools),
        model=model,
        status="running",
    )
    session.add(run)
    session.flush()
    append_task_event(
        session,
        task_id=task.id,
        step_id=step.id,
        event_type="m3.agent_run.started",
        payload={"role": role.value, "agent_run_id": run.id, "agent_version": run.agent_version},
    )
    session.flush()
    return run


def complete_m3_agent_run(
    session: Any,
    *,
    task_id: str,
    owner_public_id: str,
    role: M3AgentRole,
    output_artifact_version_id: str | None = None,
) -> DBAgentRun:
    task = _owned_task(session, task_id, owner_public_id)
    sequence = _ROLE_SEQUENCE.index(role) + 1
    step = _steps(session, task.id)[sequence]
    run = session.query(DBAgentRun).filter_by(task_id=task.id, role=role.value).first()
    if run is None or run.status != "running" or step.status != "running":
        _fail("role_not_running", "role run must be running before completion")
    run.status = "completed"
    run.output_artifact_version_id = output_artifact_version_id
    run.completed_at = _now()
    step.status = "completed"
    step.output_artifact_version_id = output_artifact_version_id
    step.completed_at = run.completed_at
    task.progress = sequence / len(_ROLE_SEQUENCE)
    append_task_event(
        session,
        task_id=task.id,
        step_id=step.id,
        event_type="m3.agent_run.completed",
        payload={
            "role": role.value,
            "agent_run_id": run.id,
            "output_artifact_version_id": output_artifact_version_id,
        },
    )
    session.flush()
    return run


def complete_m3_collaboration_task(session: Any, *, task_id: str, owner_public_id: str) -> DBGenerationTask:
    task = _owned_task(session, task_id, owner_public_id)
    if task.status == "completed":
        return task
    if task.status != "running" or any(step.status != "completed" for step in _steps(session, task.id).values()):
        _fail("task_roles_incomplete", "all four role runs must complete")
    task.status = "completed"
    task.progress = 1.0
    task.completed_at = _now()
    append_task_event(session, task_id=task.id, event_type="generation_task.completed", payload={"status": "completed"})
    session.flush()
    return task
