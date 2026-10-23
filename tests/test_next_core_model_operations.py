from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, DBGenerationTask, DBTaskEvent, DBTaskStep, DBWorkerLease
from app.m5_capabilities import Capability, CapabilityContract, M5CapabilityError, QualityMode
from app.m5_operations import (
    OperationsError,
    PriceVersionInput,
    WorkerClaimInput,
    WorkerHeartbeatInput,
    cancel_task,
    claim_next_task,
    heartbeat_lease,
    operations_dashboard,
    recover_expired_leases,
    register_price_version,
)
from app.m5_policy import GatewayPolicy, ModelRef, ModelRegistration, select_model


OWNER = "usr-next-ops"
NOW = datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _task(session, key="ops-task"):
    row = DBGenerationTask(
        owner_public_id=OWNER, trace_id=f"trace-{key}", status="queued",
        capability="m5.capability.lecture", idempotency_key=key,
    )
    session.add(row)
    session.flush()
    return row


def _price(version="2026-08-03", input_cost=1.0):
    return PriceVersionInput(
        provider="demo", model="edu-model", version=version,
        currency="USD", input_cost_per_million=input_cost,
        output_cost_per_million=2.0,
        source_url="https://example.invalid/pricing-snapshot",
        source_label="Frozen operator pricing snapshot",
        effective_at=NOW,
    )


def test_price_versions_are_immutable_and_dashboard_labels_estimates():
    session = _session()
    first, created = register_price_version(session, _price())
    replay, replay_created = register_price_version(session, _price())
    assert created is True and replay_created is False and replay.id == first.id
    with pytest.raises(OperationsError, match="immutable"):
        register_price_version(session, _price(input_cost=9.0))

    report = operations_dashboard(session)
    assert report["price_versions"][0]["version"] == "2026-08-03"
    assert report["model_calls"]["actual_invoice_total"] is None
    assert report["model_calls"]["estimated_by_currency"] == {}
    assert "not a provider invoice" in report["cost_statement"]


def test_model_selection_enforces_budget_and_explains_price_version():
    registration = ModelRegistration(
        registration_version="registry-v1", provider="demo", model="edu-model",
        tier="strong", capabilities=(Capability.REPORT,), supports_json=True,
        context_length=8192, input_cost_per_million=10.0,
        output_cost_per_million=20.0, pricing_version="2026-08-03",
        pricing_basis="operator_config",
    )
    contract = CapabilityContract(
        capability=Capability.REPORT, quality_mode=QualityMode.VERIFIED,
        course_id="course-ops", domain_pack_id="domain-ops",
        profile_snapshot_id="profile-ops", target_knowledge_point_ids=("kp-ops",),
        target_difficulty_band="advanced", idempotency_key="budget-ops-001",
    )
    allowed = (ModelRef(provider="demo", model="edu-model"),)
    with pytest.raises(M5CapabilityError) as exc:
        select_model(contract, registrations=(registration,), policy=GatewayPolicy(
            policy_version="policy-v1", allowed_models=allowed, per_call_cost_limit=0.000001,
        ))
    assert exc.value.code == "model_budget_unavailable"
    selected = select_model(contract, registrations=(registration,), policy=GatewayPolicy(
        policy_version="policy-v2", allowed_models=allowed, per_call_cost_limit=1.0,
    ))
    assert "pricing_version:2026-08-03" in selected.reason


def test_worker_claim_heartbeat_credentials_and_expiry_recovery():
    session = _session()
    task = _task(session)
    claimed = claim_next_task(session, WorkerClaimInput(worker_id="worker-a"), now=NOW)
    assert claimed and claimed["task_id"] == task.id
    assert session.get(DBGenerationTask, task.id).status == "running"
    event = session.query(DBTaskEvent).filter_by(task_id=task.id, event_type="worker.lease_acquired").one()
    assert event.payload["lease_token_persisted_in_event"] is False
    assert claimed["lease_token"] not in str(event.payload)

    with pytest.raises(OperationsError) as exc:
        heartbeat_lease(session, claimed["lease_id"], WorkerHeartbeatInput(
            worker_id="worker-a", lease_token="0" * 48,
        ), now=NOW + timedelta(seconds=1))
    assert exc.value.code == "worker_lease_forbidden"
    renewed = heartbeat_lease(session, claimed["lease_id"], WorkerHeartbeatInput(
        worker_id="worker-a", lease_token=claimed["lease_token"], lease_seconds=30,
    ), now=NOW + timedelta(seconds=1))
    assert renewed["status"] == "active"

    running_step = DBTaskStep(
        task_id=task.id, sequence=1, attempt=1, agent_role="worker-test",
        tool_name="m5.test", status="running", input_summary="content_included=false",
    )
    session.add(running_step)
    session.flush()

    recovered = recover_expired_leases(session, now=NOW + timedelta(seconds=32))
    assert recovered == [task.id]
    assert session.get(DBGenerationTask, task.id).status == "queued"
    assert session.get(DBWorkerLease, claimed["lease_id"]).status == "expired"
    attempts = session.query(DBTaskStep).filter_by(task_id=task.id, sequence=1).order_by(DBTaskStep.attempt).all()
    assert [(row.attempt, row.status, row.error_code) for row in attempts] == [
        (1, "failed", "worker_lease_expired"), (2, "pending", ""),
    ]


def test_cancel_is_owner_scoped_and_releases_active_lease():
    session = _session()
    task = _task(session, "cancel-task")
    claimed = claim_next_task(session, WorkerClaimInput(worker_id="worker-c"), now=NOW)
    with pytest.raises(OperationsError) as exc:
        cancel_task(session, task_id=task.id, owner_public_id="usr-other", now=NOW)
    assert exc.value.code == "m5_task_forbidden"
    cancelled = cancel_task(session, task_id=task.id, owner_public_id=OWNER, now=NOW)
    assert cancelled.status == "cancelled"
    assert session.get(DBWorkerLease, claimed["lease_id"]).status == "cancelled"
    assert session.query(DBTaskEvent).filter_by(
        task_id=task.id, event_type="generation_task.cancelled",
    ).count() == 1
