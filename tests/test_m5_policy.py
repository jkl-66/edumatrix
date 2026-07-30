from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, DBModelCall, DBModelQuotaBucket
from app.m5_capabilities import Capability, CapabilityContract, M5CapabilityError, QualityMode
from app.m5_gateway import ModelRegistration
from app.m5_policy import GatewayPolicy, ModelRef, enforce_daily_quota, reserve_daily_quota, select_model


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _registration(model, tier, region="cn"):
    return ModelRegistration(
        registration_version="1", provider="secure-provider", model=model, tier=tier,
        capabilities=(Capability.ANSWER, Capability.LECTURE), supports_json=True,
        context_length=8192, data_region=region,
    )


def _policy(**updates):
    data = dict(
        policy_version="policy-1",
        allowed_models=(
            ModelRef(provider="secure-provider", model="fast-1"),
            ModelRef(provider="secure-provider", model="strong-1"),
            ModelRef(provider="secure-provider", model="review-1"),
        ),
        allowed_data_regions=("cn",), daily_user_call_limit=2, daily_user_token_limit=100,
        daily_user_cost_limit=5.0, daily_course_call_limit=3, daily_model_call_limit=4,
    )
    data.update(updates)
    return GatewayPolicy(**data)


def test_m5_policy_selects_quality_tier_and_returns_declared_fallbacks():
    selected = select_model(
        CapabilityContract(
            capability=Capability.LECTURE, quality_mode=QualityMode.VERIFIED,
            course_id="course-policy", domain_pack_id="domain-policy", profile_snapshot_id="profile-policy",
            target_knowledge_point_ids=("kp-policy",), target_difficulty_band="L2-L3",
            idempotency_key="policy-m5-001",
        ),
        registrations=(
            _registration("fast-1", "fast"),
            _registration("strong-1", "strong"),
            _registration("review-1", "review"),
        ),
        policy=_policy(),
    )
    assert selected.registration.model == "strong-1"
    assert selected.fallback_models == (ModelRef(provider="secure-provider", model="review-1"),)


def test_m5_policy_blocks_region_and_enforces_user_course_model_quotas():
    session = _session()
    registration = _registration("fast-1", "fast")
    with pytest.raises(M5CapabilityError, match="no registered"):
        select_model(
            CapabilityContract(idempotency_key="policy-m5-002"),
            registrations=(_registration("fast-1", "fast", region="us"),), policy=_policy(),
        )
    now = datetime(2026, 7, 27, tzinfo=timezone.utc)
    for number in range(2):
        session.add(DBModelCall(
            trace_id=f"trace-{number}", owner_public_id="usr-policy", course_id="course-policy",
            capability="answer", prompt_version="answer:1", provider="secure-provider", model="fast-1",
            status="completed", input_summary={}, input_tokens=10, output_tokens=5,
        ))
    session.commit()
    with pytest.raises(M5CapabilityError, match="user daily"):
        enforce_daily_quota(
            session, owner_public_id="usr-policy", course_id="course-policy", registration=registration,
            policy=_policy(), estimated_input_tokens=1, now=now,
        )


def test_m5_atomic_quota_reservation_rolls_back_all_scopes_on_limit():
    session = _session()
    registration = _registration("fast-1", "fast")
    policy = _policy(daily_user_call_limit=1)
    now = datetime(2026, 7, 27, tzinfo=timezone.utc)
    reserve_daily_quota(
        session, owner_public_id="usr-atomic", course_id="course-atomic",
        registration=registration, policy=policy,
        estimated_input_tokens=10, estimated_output_tokens=20, now=now,
    )
    session.commit()
    with pytest.raises(M5CapabilityError, match="user daily"):
        reserve_daily_quota(
            session, owner_public_id="usr-atomic", course_id="course-atomic",
            registration=registration, policy=policy,
            estimated_input_tokens=10, estimated_output_tokens=20, now=now,
        )
    buckets = session.query(DBModelQuotaBucket).order_by(DBModelQuotaBucket.scope_type).all()
    assert len(buckets) == 3
    assert all(item.call_count == 1 and item.reserved_tokens == 30 for item in buckets)
