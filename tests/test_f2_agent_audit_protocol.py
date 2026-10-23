from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent_audit import (
    PublicAgentRun,
    assert_public_audit_is_sanitized,
    public_agent_audit_payload,
    record_agent_audit,
)
from app.database import Base, DBAgentRun, DBTaskStep
from app.m3_agents import (
    M3AgentRole,
    complete_m3_agent_run,
    create_m3_collaboration_task,
    fail_m3_agent_run,
    start_m3_agent_run,
    start_m3_collaboration_task,
)
from app.m3_baseline import seed_m3_profile_baselines


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def _task(session):
    owner_fixture, outsider_fixture = seed_m3_profile_baselines(session).fixtures[:2]
    task, _ = create_m3_collaboration_task(
        session,
        context=owner_fixture.generation_context,
        idempotency_key="f2-agent-audit-protocol",
        model="deterministic-test",
    )
    start_m3_collaboration_task(
        session,
        task_id=task.id,
        owner_public_id=owner_fixture.generation_context.owner_public_id,
    )
    session.commit()
    return task, owner_fixture, outsider_fixture


def test_public_contract_keeps_collaboration_evidence_and_removes_private_material():
    engine, session = _session()
    try:
        task, owner, _ = _task(session)
        run = start_m3_agent_run(
            session,
            task_id=task.id,
            owner_public_id=owner.generation_context.owner_public_id,
            role=M3AgentRole.DIAGNOSIS,
        )
        record_agent_audit(
            session,
            run=run,
            input_refs={
                "source_ids": ["ref-1", "ref-2"],
                "system_prompt": "hidden prompt",
                "api_key": "sk-never-return-this",
                "raw_log": "private log",
            },
            candidate_summary="Candidate uses system_prompt and token=secret-value",
            disagreement="Profile evidence and task difficulty disagree.",
            validation="Source scope passed.",
            revision="Reduce terminology density.",
            decision_summary="Use the revised candidate.",
        )
        complete_m3_agent_run(
            session,
            task_id=task.id,
            owner_public_id=owner.generation_context.owner_public_id,
            role=M3AgentRole.DIAGNOSIS,
            candidate_summary="One candidate profile interpretation retained.",
            disagreement="Profile evidence and task difficulty disagree.",
            validation="Source scope passed.",
            revision="Reduce terminology density.",
            decision_summary="Use the revised candidate.",
        )
        session.commit()

        payload = public_agent_audit_payload(
            session,
            task_id=task.id,
            owner_public_id=owner.generation_context.owner_public_id,
        )
        item = payload["items"][-1]
        assert item["runId"] == run.id
        assert item["role"] == "diagnosis"
        assert owner.generation_context.profile_snapshot_id in item["inputRefs"]
        assert item["candidateSummary"] == "One candidate profile interpretation retained."
        assert item["disagreement"] == "Profile evidence and task difficulty disagree."
        assert item["validation"] == "Source scope passed."
        assert item["revision"] == "Reduce terminology density."
        assert item["decisionSummary"] == "Use the revised candidate."
        assert item["status"] == "completed"
        assert set(item) == {
            "runId",
            "role",
            "inputRefs",
            "candidateSummary",
            "disagreement",
            "validation",
            "revision",
            "decisionSummary",
            "status",
        }
        assert PublicAgentRun.model_validate(item)
        assert_public_audit_is_sanitized(payload)
        serialized = json.dumps(payload, ensure_ascii=False).lower()
        for forbidden in (
            "system_prompt",
            "api_key",
            "sk-never-return-this",
            "raw_log",
            "secret-value",
            "chain_of_thought",
            "private_reasoning",
        ):
            assert forbidden not in serialized
    finally:
        session.close()
        engine.dispose()


def test_failed_stage_is_visible_and_retry_creates_a_new_attempt_without_replaying_prior_stage():
    engine, session = _session()
    try:
        task, owner, _ = _task(session)
        owner_id = owner.generation_context.owner_public_id
        first = start_m3_agent_run(
            session,
            task_id=task.id,
            owner_public_id=owner_id,
            role=M3AgentRole.DIAGNOSIS,
        )
        fail_m3_agent_run(
            session,
            task_id=task.id,
            owner_public_id=owner_id,
            role=M3AgentRole.DIAGNOSIS,
            error_code="model_capacity",
            error_message="Selected model is at capacity: sk-private-value",
        )
        session.commit()

        failed = public_agent_audit_payload(session, task_id=task.id, owner_public_id=owner_id)
        assert failed["items"][-1]["status"] == "failed"
        assert "retry later" in failed["items"][-1]["decisionSummary"].lower()
        assert_public_audit_is_sanitized(failed)

        second = start_m3_agent_run(
            session,
            task_id=task.id,
            owner_public_id=owner_id,
            role=M3AgentRole.DIAGNOSIS,
        )
        assert second.id != first.id
        assert second.parent_run_id == first.id
        complete_m3_agent_run(
            session,
            task_id=task.id,
            owner_public_id=owner_id,
            role=M3AgentRole.DIAGNOSIS,
            validation="Retry completed with valid structured output.",
            decision_summary="Continue to generation.",
        )
        session.commit()

        step = session.query(DBTaskStep).filter_by(task_id=task.id, sequence=1).one()
        runs = session.query(DBAgentRun).filter_by(task_id=task.id, role="diagnosis").all()
        assert step.status == "completed"
        assert "sk-private-value" not in step.error_message
        assert {run.status for run in runs} == {"failed", "completed"}
        recovered = public_agent_audit_payload(session, task_id=task.id, owner_public_id=owner_id)
        assert [item["status"] for item in recovered["items"]][-2:] == ["failed", "completed"]
    finally:
        session.close()
        engine.dispose()


def test_public_audit_is_owner_scoped():
    engine, session = _session()
    try:
        task, owner, outsider = _task(session)
        with pytest.raises(PermissionError):
            public_agent_audit_payload(
                session,
                task_id=task.id,
                owner_public_id=outsider.generation_context.owner_public_id,
            )
        assert public_agent_audit_payload(
            session,
            task_id=task.id,
            owner_public_id=owner.generation_context.owner_public_id,
        )["taskId"] == task.id
    finally:
        session.close()
        engine.dispose()
