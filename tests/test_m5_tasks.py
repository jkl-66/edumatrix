from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest

from app.database import Base, DBTaskEvent, DBTaskStep
from app.m5_capabilities import Capability, CapabilityContract, RoutingRequest, RuntimeAvailability
from app.m5_tasks import (
    M5TaskError,
    complete_capability_step,
    complete_capability_task,
    create_capability_task,
    fail_capability_step,
    resume_capability_task,
    retry_capability_step,
    start_capability_step,
    start_capability_task,
)


READY = RuntimeAvailability(text_model=True, retrieval=True, sandbox_mode="trusted_local")


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _request(key="m5-task-001"):
    return RoutingRequest(
        contract=CapabilityContract(capability=Capability.LECTURE, idempotency_key=key),
    )


def test_m5_task_compiles_r4_without_message_and_is_idempotent():
    session = _session()
    task, created = create_capability_task(
        session, owner_public_id="usr-m5-task", request=_request(), runtime=READY,
    )
    session.commit()
    replay, replay_created = create_capability_task(
        session, owner_public_id="usr-m5-task", request=_request(), runtime=READY,
    )
    locked = session.query(DBTaskEvent).filter_by(task_id=task.id, event_type="m5.contract.locked").one()

    assert created is True and replay_created is False and replay.id == task.id
    assert locked.payload["message_included"] is False
    assert [item.tool_name for item in session.query(DBTaskStep).filter_by(task_id=task.id).order_by(DBTaskStep.sequence)] == [
        "m5.context.assemble", "m5.lecture.generate", "m5.lecture.validate", "m5.artifact.commit",
    ]


def test_m5_task_retries_only_failed_step_and_resumes_from_events():
    session = _session()
    task, _ = create_capability_task(
        session, owner_public_id="usr-m5-task", request=_request("m5-task-retry"), runtime=READY,
    )
    start_capability_task(session, task_id=task.id, owner_public_id="usr-m5-task")
    start_capability_step(session, task_id=task.id, owner_public_id="usr-m5-task", sequence=1)
    complete_capability_step(session, task_id=task.id, owner_public_id="usr-m5-task", sequence=1)
    start_capability_step(session, task_id=task.id, owner_public_id="usr-m5-task", sequence=2)
    failed = fail_capability_step(
        session, task_id=task.id, owner_public_id="usr-m5-task", sequence=2,
        error_code="provider_timeout", retryable=True,
    )
    retry = retry_capability_step(session, task_id=task.id, owner_public_id="usr-m5-task", sequence=2)
    session.commit()
    state = resume_capability_task(session, task_id=task.id, owner_public_id="usr-m5-task")

    assert retry.attempt == 2 and retry.parent_step_id == failed.id
    assert state["latest_steps"][0]["status"] == "completed"
    assert state["latest_steps"][1]["status"] == "pending"
    assert session.query(DBTaskStep).filter_by(task_id=task.id, sequence=1).count() == 1


def test_m5_task_rejects_light_routes_and_requires_all_steps_before_completion():
    session = _session()
    with pytest.raises(M5TaskError, match="must not create"):
        create_capability_task(
            session,
            owner_public_id="usr-m5-task",
            request=RoutingRequest(contract=CapabilityContract(idempotency_key="m5-task-answer")),
            runtime=READY,
        )
    task, _ = create_capability_task(
        session, owner_public_id="usr-m5-task", request=_request("m5-task-incomplete"), runtime=READY,
    )
    start_capability_task(session, task_id=task.id, owner_public_id="usr-m5-task")
    with pytest.raises(M5TaskError, match="all latest"):
        complete_capability_task(session, task_id=task.id, owner_public_id="usr-m5-task")
