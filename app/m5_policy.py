"""Backend-owned model selection and daily quota policy for M5 gateway calls."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid

from pydantic import ConfigDict, Field
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.database import DBModelCall, DBModelQuotaBucket
from app.m2_contracts import StrictModel
from app.m5_capabilities import Capability, CapabilityContract, M5CapabilityError, QualityMode


class ModelRegistration(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    registration_version: str = Field(min_length=1, max_length=64)
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    tier: str = Field(pattern=r"^(fast|standard|strong|review)$")
    capabilities: tuple[Capability, ...]
    supports_json: bool = False
    supports_vision: bool = False
    supports_streaming: bool = False
    context_length: int = Field(ge=1)
    input_cost_per_million: float = Field(default=0.0, ge=0)
    output_cost_per_million: float = Field(default=0.0, ge=0)
    data_region: str = Field(default="unspecified", min_length=1, max_length=64)


class ModelRef(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)


class GatewayPolicy(StrictModel):
    """A secret-free policy assembled by the backend or enterprise tenant layer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: str = Field(min_length=1, max_length=64)
    allowed_models: tuple[ModelRef, ...] = Field(min_length=1)
    allowed_capabilities: tuple[Capability, ...] = tuple(Capability)
    allowed_data_regions: tuple[str, ...] = ()
    daily_user_call_limit: int = Field(default=100, ge=1)
    daily_user_token_limit: int = Field(default=500000, ge=1)
    daily_user_cost_limit: float = Field(default=10.0, ge=0)
    daily_course_call_limit: int = Field(default=1000, ge=1)
    daily_model_call_limit: int = Field(default=10000, ge=1)


class ModelSelection(StrictModel):
    registration: ModelRegistration
    fallback_models: tuple[ModelRef, ...]
    reason: str


class QuotaUsage(StrictModel):
    call_count: int = Field(ge=0)
    token_count: int = Field(ge=0)
    estimated_cost: float = Field(ge=0)


def select_model(
    contract: CapabilityContract,
    *,
    registrations: tuple[ModelRegistration, ...],
    policy: GatewayPolicy,
) -> ModelSelection:
    capability = contract.locked_capability
    if capability not in policy.allowed_capabilities:
        raise M5CapabilityError("capability_policy_denied", "capability is disallowed by the backend model policy")
    allowed = {(item.provider, item.model) for item in policy.allowed_models}
    candidates = [
        registration for registration in registrations
        if (registration.provider, registration.model) in allowed
        and capability in registration.capabilities
        and (not policy.allowed_data_regions or registration.data_region in policy.allowed_data_regions)
    ]
    if not candidates:
        raise M5CapabilityError("model_policy_unavailable", "no registered model satisfies the capability policy")
    preferred = {
        QualityMode.FAST: ("fast", "standard", "strong", "review"),
        QualityMode.STANDARD: ("standard", "strong", "review"),
        QualityMode.VERIFIED: ("strong", "review"),
    }[contract.quality_mode]
    candidates = [item for item in candidates if item.tier in preferred]
    if not candidates:
        raise M5CapabilityError("model_quality_unavailable", "no registered model satisfies the requested quality mode")
    ordered = sorted(
        candidates,
        key=lambda item: (preferred.index(item.tier) if item.tier in preferred else len(preferred), item.provider, item.model),
    )
    primary = ordered[0]
    fallbacks = tuple(
        ModelRef(provider=item.provider, model=item.model)
        for item in ordered[1:]
    )
    return ModelSelection(registration=primary, fallback_models=fallbacks, reason=f"quality_mode:{contract.quality_mode.value}")


def _daily_rows(session: Any, *, now: datetime) -> Any:
    start = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
    return session.query(DBModelCall).filter(DBModelCall.created_at >= start)


def quota_usage(session: Any, *, owner_public_id: str | None, course_id: str | None, registration: ModelRegistration, now: datetime | None = None) -> dict[str, QuotaUsage]:
    now = now or datetime.now(timezone.utc)
    base = _daily_rows(session, now=now)

    def usage(rows: Any) -> QuotaUsage:
        items = rows.all()
        return QuotaUsage(
            call_count=len(items),
            token_count=sum(int(item.input_tokens or 0) + int(item.output_tokens or 0) for item in items),
            estimated_cost=round(sum(float(item.estimated_cost or 0.0) for item in items), 8),
        )

    return {
        "user": usage(base.filter(DBModelCall.owner_public_id == owner_public_id)) if owner_public_id else QuotaUsage(call_count=0, token_count=0, estimated_cost=0),
        "course": usage(base.filter(DBModelCall.course_id == course_id)) if course_id else QuotaUsage(call_count=0, token_count=0, estimated_cost=0),
        "model": usage(base.filter(DBModelCall.provider == registration.provider, DBModelCall.model == registration.model)),
    }


def enforce_daily_quota(
    session: Any,
    *,
    owner_public_id: str | None,
    course_id: str | None,
    registration: ModelRegistration,
    policy: GatewayPolicy,
    estimated_input_tokens: int,
    now: datetime | None = None,
) -> dict[str, QuotaUsage]:
    usage = quota_usage(
        session, owner_public_id=owner_public_id, course_id=course_id,
        registration=registration, now=now,
    )
    user = usage["user"]
    if owner_public_id and (
        user.call_count + 1 > policy.daily_user_call_limit
        or user.token_count + estimated_input_tokens > policy.daily_user_token_limit
        or user.estimated_cost
        + estimated_input_tokens * registration.input_cost_per_million / 1_000_000
        > policy.daily_user_cost_limit
    ):
        raise M5CapabilityError("user_daily_quota_exceeded", "user daily model quota is exhausted")
    course = usage["course"]
    if course_id and course.call_count + 1 > policy.daily_course_call_limit:
        raise M5CapabilityError("course_daily_quota_exceeded", "course daily model quota is exhausted")
    model = usage["model"]
    if model.call_count + 1 > policy.daily_model_call_limit:
        raise M5CapabilityError("model_daily_quota_exceeded", "model daily call quota is exhausted")
    return usage


def reserve_daily_quota(
    session: Any,
    *,
    owner_public_id: str | None,
    course_id: str | None,
    registration: ModelRegistration,
    policy: GatewayPolicy,
    estimated_input_tokens: int,
    estimated_output_tokens: int,
    now: datetime | None = None,
) -> None:
    """Atomically reserve all applicable daily scopes in the current transaction."""
    now = now or datetime.now(timezone.utc)
    utc_day = now.astimezone(timezone.utc).date().isoformat()
    tokens = max(0, estimated_input_tokens) + max(0, estimated_output_tokens)
    cost = (
        max(0, estimated_input_tokens) * registration.input_cost_per_million
        + max(0, estimated_output_tokens) * registration.output_cost_per_million
    ) / 1_000_000
    scopes = []
    if owner_public_id:
        scopes.append((
            "user", owner_public_id, policy.daily_user_call_limit,
            policy.daily_user_token_limit, policy.daily_user_cost_limit,
            "user_daily_quota_exceeded",
        ))
    if course_id:
        scopes.append((
            "course", course_id, policy.daily_course_call_limit,
            2**63 - 1, float("inf"), "course_daily_quota_exceeded",
        ))
    scopes.append((
        "model", f"{registration.provider}:{registration.model}",
        policy.daily_model_call_limit, 2**63 - 1, float("inf"),
        "model_daily_quota_exceeded",
    ))

    for scope_type, scope_key, call_limit, token_limit, cost_limit, error_code in scopes:
        insert = sqlite_insert(DBModelQuotaBucket).values(
            id=f"mqb-{uuid.uuid4().hex}",
            scope_type=scope_type,
            scope_key=scope_key,
            utc_day=utc_day,
            call_count=1,
            reserved_tokens=tokens,
            reserved_cost=cost,
        )
        update = {
            "call_count": DBModelQuotaBucket.call_count + 1,
            "reserved_tokens": DBModelQuotaBucket.reserved_tokens + tokens,
            "reserved_cost": DBModelQuotaBucket.reserved_cost + cost,
            "updated_at": datetime.now(timezone.utc).replace(tzinfo=None),
        }
        statement = insert.on_conflict_do_update(
            index_elements=["scope_type", "scope_key", "utc_day"],
            set_=update,
            where=(
                (DBModelQuotaBucket.call_count + 1 <= call_limit)
                & (DBModelQuotaBucket.reserved_tokens + tokens <= token_limit)
                & (DBModelQuotaBucket.reserved_cost + cost <= cost_limit)
            ),
        )
        result = session.execute(statement)
        if result.rowcount != 1:
            session.rollback()
            raise M5CapabilityError(error_code, f"{scope_type} daily model quota is exhausted")
