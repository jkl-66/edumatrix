from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, DBAgentRun, DBTaskStep
from app.m3_agents import (
    M3_AGENT_CONTRACTS,
    M3AgentRole,
    M3AgentStateError,
    complete_m3_agent_run,
    complete_m3_collaboration_task,
    create_m3_collaboration_task,
    start_m3_agent_run,
    start_m3_collaboration_task,
    task_events,
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


def test_four_role_registry_has_separate_responsibilities_and_guardrails():
    assert [contract.role for contract in M3_AGENT_CONTRACTS] == list(M3AgentRole)
    assert len({contract.registry_id for contract in M3_AGENT_CONTRACTS}) == 4
    assert len({contract.version for contract in M3_AGENT_CONTRACTS}) == 4
    assert all(contract.required_input_fields for contract in M3_AGENT_CONTRACTS)
    assert all(contract.output_object_types for contract in M3_AGENT_CONTRACTS)
    assert all(contract.forbidden_actions for contract in M3_AGENT_CONTRACTS)
    assert "declare_competence" in M3_AGENT_CONTRACTS[0].forbidden_actions
    assert "overwrite_generator_output" in M3_AGENT_CONTRACTS[2].forbidden_actions
    assert "treat_click_as_mastery" in M3_AGENT_CONTRACTS[3].forbidden_actions


def test_three_profiles_get_persistent_four_role_tasks_with_minimized_inputs():
    engine, session = _session()
    try:
        fixtures = seed_m3_profile_baselines(session).fixtures
        task_ids = []
        for fixture in fixtures:
            task, created = create_m3_collaboration_task(
                session,
                context=fixture.generation_context,
                idempotency_key=f"m3-four-role-{fixture.gold_profile.archetype}",
                model="deterministic-test",
            )
            assert created is True
            task_ids.append(task.id)
            repeated, repeated_created = create_m3_collaboration_task(
                session,
                context=fixture.generation_context,
                idempotency_key=f"m3-four-role-{fixture.gold_profile.archetype}",
                model="deterministic-test",
            )
            assert repeated.id == task.id
            assert repeated_created is False

            steps = session.query(DBTaskStep).filter_by(task_id=task.id).order_by(DBTaskStep.sequence).all()
            assert [step.agent_role for step in steps] == [role.value for role in M3AgentRole]
            for step in steps:
                summary = json.loads(step.input_summary)
                assert summary["content_included"] is False
                assert "evidence" not in summary
                assert "prompt" not in summary
                assert "secret" not in summary
        assert len(set(task_ids)) == 3
        assert session.query(DBTaskStep).filter(DBTaskStep.task_id.in_(task_ids)).count() == 12
    finally:
        session.close()
        engine.dispose()


def test_role_runs_enforce_order_owner_and_complete_as_one_trace():
    engine, session = _session()
    try:
        first, outsider = seed_m3_profile_baselines(session).fixtures[:2]
        owner = first.generation_context.owner_public_id
        task, _ = create_m3_collaboration_task(
            session,
            context=first.generation_context,
            idempotency_key="m3-role-order",
        )
        start_m3_collaboration_task(session, task_id=task.id, owner_public_id=owner)

        with pytest.raises(M3AgentStateError) as raised:
            start_m3_agent_run(
                session,
                task_id=task.id,
                owner_public_id=owner,
                role=M3AgentRole.DOMAIN_GENERATION,
            )
        assert raised.value.code == "role_dependency_incomplete"
        with pytest.raises(M3AgentStateError) as raised:
            start_m3_agent_run(
                session,
                task_id=task.id,
                owner_public_id=outsider.generation_context.owner_public_id,
                role=M3AgentRole.DIAGNOSIS,
            )
        assert raised.value.code == "task_forbidden"

        for role in M3AgentRole:
            run = start_m3_agent_run(
                session,
                task_id=task.id,
                owner_public_id=owner,
                role=role,
                model="deterministic-test",
            )
            assert start_m3_agent_run(
                session,
                task_id=task.id,
                owner_public_id=owner,
                role=role,
                model="deterministic-test",
            ).id == run.id
            complete_m3_agent_run(
                session,
                task_id=task.id,
                owner_public_id=owner,
                role=role,
            )
        complete_m3_collaboration_task(session, task_id=task.id, owner_public_id=owner)
        session.commit()

        runs = session.query(DBAgentRun).filter_by(task_id=task.id).all()
        assert len(runs) == 4
        assert {run.trace_id for run in runs} == {task.trace_id}
        assert all(run.status == "completed" for run in runs)
        assert task.status == "completed"
        events = task_events(session, task.id)
        assert [event.sequence for event in events] == list(range(1, len(events) + 1))
        assert sum(event.event_type == "m3.agent_run.started" for event in events) == 4
        assert sum(event.event_type == "m3.agent_run.completed" for event in events) == 4
    finally:
        session.close()
        engine.dispose()
