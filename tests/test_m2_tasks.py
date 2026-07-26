from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, DBTaskEvent, DBTaskStep
from app.m1_repository import create_generation_task
from app.m2_baseline import seed_m2_baseline
from app.m2_tasks import (
    M2TaskStateError,
    complete_golden_task,
    complete_task_step,
    create_golden_task,
    fail_task_step,
    resume_golden_task,
    retry_task_step,
    start_golden_task,
    start_task_step,
)


def _seeded_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    baseline = seed_m2_baseline(session)
    return engine, Session, session, baseline


def test_golden_task_creation_is_idempotent_and_survives_new_session():
    engine, Session, session, baseline = _seeded_session()
    owner = baseline.generation_context.owner_public_id
    try:
        task, created = create_golden_task(
            session,
            context=baseline.generation_context,
            idempotency_key="m2-golden-idempotent-1",
            model="deterministic",
        )
        duplicate, duplicate_created = create_golden_task(
            session,
            context=baseline.generation_context,
            idempotency_key="m2-golden-idempotent-1",
            model="deterministic",
        )
        session.commit()
        task_id = task.id
        assert created is True
        assert duplicate_created is False
        assert duplicate.id == task_id
        assert session.query(DBTaskStep).filter_by(task_id=task_id).count() == 4
        assert session.query(DBTaskEvent).filter_by(
            task_id=task_id, event_type="m2.context.verified"
        ).count() == 1
        session.close()

        restarted = Session()
        state = resume_golden_task(restarted, task_id=task_id, owner_public_id=owner)
        assert state["status"] == "queued"
        assert [step["sequence"] for step in state["latest_steps"]] == [1, 2, 3, 4]
        assert [event["sequence"] for event in state["events"]] == list(
            range(1, state["last_event_sequence"] + 1)
        )
        restarted.close()
    finally:
        if session.is_active:
            session.close()
        engine.dispose()


def test_local_failure_retries_only_failed_step_and_preserves_completed_work():
    engine, _Session, session, baseline = _seeded_session()
    owner = baseline.generation_context.owner_public_id
    try:
        task, _ = create_golden_task(
            session, context=baseline.generation_context, idempotency_key="m2-local-retry"
        )
        start_golden_task(session, task_id=task.id, owner_public_id=owner)
        start_task_step(session, task_id=task.id, owner_public_id=owner, sequence=1)
        complete_task_step(session, task_id=task.id, owner_public_id=owner, sequence=1)
        start_task_step(session, task_id=task.id, owner_public_id=owner, sequence=2)
        failed = fail_task_step(
            session,
            task_id=task.id,
            owner_public_id=owner,
            sequence=2,
            error_code="transient_model_error",
            error_message="temporary failure",
        )
        retry = retry_task_step(session, task_id=task.id, owner_public_id=owner, sequence=2)
        assert failed.status == "failed"
        assert retry.attempt == 2
        assert retry.parent_step_id == failed.id
        start_task_step(session, task_id=task.id, owner_public_id=owner, sequence=2)
        complete_task_step(session, task_id=task.id, owner_public_id=owner, sequence=2)
        for sequence in (3, 4):
            start_task_step(session, task_id=task.id, owner_public_id=owner, sequence=sequence)
            complete_task_step(session, task_id=task.id, owner_public_id=owner, sequence=sequence)
        with pytest.raises(M2TaskStateError) as raised:
            complete_golden_task(session, task_id=task.id, owner_public_id=owner)
        assert raised.value.code == "task_feedback_missing"
        session.commit()

        state = resume_golden_task(session, task_id=task.id, owner_public_id=owner)
        assert state["status"] == "running"
        assert state["progress"] == 1.0
        assert state["latest_steps"][0]["status"] == "completed"
        assert state["latest_steps"][1]["attempt"] == 2
    finally:
        session.close()
        engine.dispose()


def test_task_cannot_report_success_with_incomplete_steps_and_event_cursor_resumes():
    engine, _Session, session, baseline = _seeded_session()
    owner = baseline.generation_context.owner_public_id
    try:
        task, _ = create_golden_task(
            session, context=baseline.generation_context, idempotency_key="m2-incomplete"
        )
        start_golden_task(session, task_id=task.id, owner_public_id=owner)
        with pytest.raises(M2TaskStateError) as raised:
            complete_golden_task(session, task_id=task.id, owner_public_id=owner)
        assert raised.value.code == "task_steps_incomplete"

        first_page = resume_golden_task(session, task_id=task.id, owner_public_id=owner)
        cursor = first_page["last_event_sequence"]
        start_task_step(session, task_id=task.id, owner_public_id=owner, sequence=1)
        next_page = resume_golden_task(
            session,
            task_id=task.id,
            owner_public_id=owner,
            after_event_sequence=cursor,
        )
        assert [event["event_type"] for event in next_page["events"]] == ["task_step.started"]
    finally:
        session.close()
        engine.dispose()


def test_idempotency_key_cannot_be_reused_by_a_non_m2_task():
    engine, _Session, session, baseline = _seeded_session()
    owner = baseline.generation_context.owner_public_id
    try:
        create_generation_task(
            session,
            owner_public_id=owner,
            capability="unrelated.capability",
            idempotency_key="m2-conflicting-key",
            course_id=baseline.generation_context.course_id,
        )
        with pytest.raises(M2TaskStateError) as raised:
            create_golden_task(
                session,
                context=baseline.generation_context,
                idempotency_key="m2-conflicting-key",
            )
        assert raised.value.code == "idempotency_conflict"
    finally:
        session.close()
        engine.dispose()
