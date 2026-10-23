import asyncio

import pytest
from pydantic import Field
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, DBGenerationTask, DBModelCall, DBModelPriceVersion, DBModelQuotaBucket
from app.m2_contracts import StrictModel
from app.m5_capabilities import Capability, CapabilityContract, M5CapabilityError
from app.m5_gateway import (
    GatewayRequest,
    M5ModelGateway,
    ModelRegistration,
    PromptSpec,
    StreamingModelCallLifecycle,
)


class Answer(StrictModel):
    summary: str = Field(min_length=1)


class Backend:
    def __init__(self, output):
        self.output = output

    async def generate(self, system_prompt, user_prompt, *, role):
        return self.output


class FailingBackend:
    async def generate(self, system_prompt, user_prompt, *, role):
        raise ValueError("provider payload failed")


class ProviderFailureBackend:
    async def generate(self, system_prompt, user_prompt, *, role):
        raise RuntimeError("provider unavailable")


class CancelledBackend:
    async def generate(self, system_prompt, user_prompt, *, role):
        raise asyncio.CancelledError()


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _request():
    return GatewayRequest(
        contract=CapabilityContract(capability=Capability.ANSWER, idempotency_key="m5-gateway-001"),
        prompt=PromptSpec(key="answer", version="1.0", system_prompt="Answer from supplied context only."),
        user_prompt="Explain recall.",
    )


def _registration(**updates):
    data = dict(
        registration_version="1", provider="test", model="test-json", tier="fast",
        capabilities=(Capability.ANSWER,), supports_json=True, context_length=8192,
        input_cost_per_million=1.0, output_cost_per_million=2.0,
    )
    data.update(updates)
    return ModelRegistration(**data)


def test_m5_gateway_persists_trace_without_raw_prompt_and_validates_json():
    session = _session()
    result = asyncio.run(M5ModelGateway().execute(
        session,
        request=_request(),
        registration=_registration(),
        backend=Backend('{"summary":"Recall measures relevant items found."}'),
        response_model=Answer,
    ))
    row = session.query(DBModelCall).one()
    assert result.status == "completed"
    assert result.structured_output["summary"].startswith("Recall")
    assert row.prompt_version == "answer:1.0"
    assert row.input_summary["user_prompt_chars"] == len("Explain recall.")
    assert "Explain recall" not in str(row.input_summary)
    assert len(row.output_hash) == 64


def test_m5_gateway_records_schema_failure_as_terminal_result():
    session = _session()
    with pytest.raises(M5CapabilityError, match="strict schema"):
        asyncio.run(M5ModelGateway().execute(
            session,
            request=_request(),
            registration=_registration(),
            backend=Backend("not-json"),
            response_model=Answer,
        ))
    row = session.query(DBModelCall).one()
    assert (row.status, row.error_code) == ("failed", "structured_output_invalid")


def test_m5_gateway_does_not_misclassify_provider_value_errors():
    session = _session()
    with pytest.raises(M5CapabilityError, match="provider call failed"):
        asyncio.run(M5ModelGateway().execute(
            session,
            request=_request(),
            registration=_registration(),
            backend=FailingBackend(),
            response_model=Answer,
        ))
    row = session.query(DBModelCall).one()
    assert (row.status, row.error_code) == ("failed", "provider_call_failed")


def test_m5_gateway_closes_cancelled_provider_call():
    session = _session()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(M5ModelGateway().execute(
            session,
            request=_request(),
            registration=_registration(),
            backend=CancelledBackend(),
            response_model=Answer,
        ))
    row = session.query(DBModelCall).one()
    assert (row.status, row.error_code) == ("failed", "provider_call_cancelled")
    assert row.completed_at is not None


def test_streaming_lifecycle_records_completion_without_raw_content():
    session = _session()

    async def database_runner(operation, *args):
        return operation(session, *args)

    lifecycle = StreamingModelCallLifecycle(
        capability="answer",
        prompt_key="legacy_stream_chat",
        prompt_version="1.0",
        provider="test",
        model="stream-model",
        system_prompt="Secret system content",
        user_prompt="Secret learner content",
        owner_public_id="owner-1",
        input_summary={"context_session_id": "ctx-1", "source_document_count": 2},
        input_cost_per_million=1.0,
        output_cost_per_million=2.0,
        database_runner=database_runner,
    )
    asyncio.run(lifecycle.start())
    row = session.query(DBModelCall).one()
    assert row.status == "running"

    asyncio.run(lifecycle.complete("Private generated answer"))
    session.refresh(row)
    assert row.status == "completed"
    assert row.output_tokens > 0
    assert row.estimated_cost > 0
    assert len(row.output_hash) == 64
    persisted = str(row.input_summary)
    assert "Secret system content" not in persisted
    assert "Secret learner content" not in persisted
    assert "Private generated answer" not in persisted
    assert row.input_summary["context_session_id"] == "ctx-1"


@pytest.mark.parametrize("error_code", ["provider_stream_failed", "client_disconnected"])
def test_streaming_lifecycle_records_failure_terminal_state_once(error_code):
    session = _session()

    async def database_runner(operation, *args):
        return operation(session, *args)

    lifecycle = StreamingModelCallLifecycle(
        capability="answer",
        prompt_key="legacy_stream_chat",
        prompt_version="1.0",
        provider="test",
        model="stream-model",
        system_prompt="system",
        user_prompt="learner",
        database_runner=database_runner,
    )

    async def exercise():
        await lifecycle.start()
        await lifecycle.fail(error_code, "partial")
        await lifecycle.complete("must not overwrite terminal state")

    asyncio.run(exercise())
    row = session.query(DBModelCall).one()
    assert (row.status, row.error_code) == ("failed", error_code)
    assert row.output_hash == __import__("hashlib").sha256(b"partial").hexdigest()


def test_m5_gateway_uses_only_policy_approved_same_quality_fallback():
    from app.m5_policy import GatewayPolicy, ModelRef

    session = _session()
    primary = _registration(model="strong-primary", tier="strong")
    fallback = _registration(model="review-fallback", tier="review")
    policy = GatewayPolicy(
        policy_version="policy-fallback",
        allowed_models=(
            ModelRef(provider="test", model="strong-primary"),
            ModelRef(provider="test", model="review-fallback"),
        ),
        daily_user_call_limit=10,
    )
    request = _request().model_copy(update={
        "contract": CapabilityContract(
            capability=Capability.ANSWER,
            quality_mode="verified",
            course_id="course-policy", domain_pack_id="domain-policy",
            profile_snapshot_id="profile-policy", target_knowledge_point_ids=("kp-policy",),
            target_difficulty_band="L2-L3", idempotency_key="m5-fallback-001",
        ),
    })
    result = asyncio.run(M5ModelGateway().execute_with_policy(
        session,
        request=request,
        registrations=(primary, fallback),
        policy=policy,
        backends={
            ("test", "strong-primary"): ProviderFailureBackend(),
            ("test", "review-fallback"): Backend('{"summary":"fallback succeeded"}'),
        },
        response_model=Answer,
    ))
    assert result.fallback_used is True
    assert result.attempted_models == ("test:strong-primary", "test:review-fallback")
    rows = session.query(DBModelCall).order_by(DBModelCall.created_at).all()
    assert [row.status for row in rows] == ["failed", "completed"]


def test_gateway_freezes_active_price_version_reconciles_quota_and_rolls_cost_to_task():
    from datetime import datetime
    from app.m5_policy import GatewayPolicy, ModelRef

    session = _session()
    task = DBGenerationTask(
        id="task-priced", owner_public_id="owner-priced", trace_id="trace-priced",
        capability="m5.capability.answer", idempotency_key="priced-task", status="running",
    )
    session.add(task)
    session.add(DBModelPriceVersion(
        provider="test", model="test-json", version="price-20260803", currency="CNY",
        input_cost_per_million=3.0, output_cost_per_million=7.0,
        source_url="https://example.invalid/frozen-price", source_label="Frozen price",
        effective_at=datetime(2026, 8, 3, 8, 0), active=True,
    ))
    session.commit()
    request = _request().model_copy(update={"owner_public_id": "owner-priced", "task_id": task.id})
    result = asyncio.run(M5ModelGateway().execute_with_policy(
        session,
        request=request,
        registrations=(_registration(),),
        policy=GatewayPolicy(
            policy_version="priced-policy",
            allowed_models=(ModelRef(provider="test", model="test-json"),),
        ),
        backends={("test", "test-json"): Backend('{"summary":"priced response"}')},
        response_model=Answer,
    ))
    call = session.query(DBModelCall).one()
    session.refresh(task)
    bucket = session.query(DBModelQuotaBucket).filter_by(
        scope_type="user", scope_key="owner-priced",
    ).one()
    assert call.pricing_version == "price-20260803"
    assert call.cost_currency == "CNY" and call.cost_basis == "operator_config"
    assert result.estimated_cost == call.estimated_cost == task.estimated_cost
    assert bucket.reserved_tokens == call.input_tokens + call.output_tokens
    assert bucket.reserved_cost == pytest.approx(call.estimated_cost)
