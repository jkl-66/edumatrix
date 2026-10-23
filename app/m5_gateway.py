"""Unified M5 text-model call boundary with traceable, schema-checked results."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import time
import asyncio
from typing import Any, Awaitable, Callable, Protocol
import uuid

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.database import DBGenerationTask, DBModelCall, DBModelPriceVersion
from app.m2_contracts import StrictModel
from app.m5_capabilities import Capability, CapabilityContract, M5CapabilityError, OutputConstraints
from app.m5_policy import GatewayPolicy, ModelRegistration, ModelRef, enforce_daily_quota, reconcile_daily_quota, reserve_daily_quota, resolve_registration_pricing, select_model
from llm_client import parse_json_object
from config import CONFIG


class TextBackend(Protocol):
    async def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str: ...


class PromptSpec(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=64)
    system_prompt: str = Field(min_length=1, max_length=20000)


class GatewayRequest(StrictModel):
    contract: CapabilityContract
    owner_public_id: str | None = Field(default=None, max_length=64)
    task_id: str | None = Field(default=None, max_length=64)
    prompt: PromptSpec
    user_prompt: str = Field(min_length=1, max_length=200000)
    role: str = Field(default="m5_gateway", min_length=1, max_length=128)


class GatewayResult(StrictModel):
    schema_version: str = "m5.gateway-result.v1"
    trace_id: str
    call_id: str
    capability: Capability
    status: str
    text: str = ""
    structured_output: dict[str, Any] | None = None
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    token_source: str
    estimated_cost: float
    attempted_models: tuple[str, ...] = ()
    fallback_used: bool = False


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _parse_json_object(raw: str) -> dict[str, Any]:
    return parse_json_object(raw)


DatabaseRunner = Callable[..., Awaitable[Any]]


class StreamingModelCallLifecycle:
    """Persist one streaming provider call without retaining raw prompts or output."""

    def __init__(
        self,
        *,
        capability: str,
        prompt_key: str,
        prompt_version: str,
        provider: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        owner_public_id: str | None = None,
        course_id: str | None = None,
        task_id: str | None = None,
        input_summary: dict[str, Any] | None = None,
        input_cost_per_million: float = 0.0,
        output_cost_per_million: float = 0.0,
        pricing_version: str = "unpriced",
        pricing_currency: str = "USD",
        pricing_basis: str = "unpriced",
        database_runner: DatabaseRunner | None = None,
        trace_id: str | None = None,
    ) -> None:
        self.trace_id = trace_id or f"m5-{uuid.uuid4().hex}"
        self.call_id: str | None = None
        self.capability = capability
        self.prompt_version = f"{prompt_key}:{prompt_version}"
        self.provider = provider or "unknown"
        self.model = model or "unknown"
        self.owner_public_id = owner_public_id
        self.course_id = course_id
        self.task_id = task_id
        self.input_tokens = _estimate_tokens(system_prompt + user_prompt)
        self.input_summary = {
            "capability": capability,
            "prompt_key": prompt_key,
            "system_prompt_chars": len(system_prompt),
            "user_prompt_chars": len(user_prompt),
            **(input_summary or {}),
        }
        self.input_cost_per_million = max(0.0, input_cost_per_million)
        self.output_cost_per_million = max(0.0, output_cost_per_million)
        self.pricing_version = pricing_version
        self.pricing_currency = pricing_currency
        self.pricing_basis = pricing_basis
        self._database_runner = database_runner
        self._started_at: float | None = None
        self._terminal = False
        self._lock = asyncio.Lock()

    async def _run_db(self, operation: Callable[..., Any], *args: Any) -> Any:
        if self._database_runner is None:
            from app.database import run_db_op
            self._database_runner = run_db_op
        return await self._database_runner(operation, *args)

    async def start(self) -> str:
        async with self._lock:
            if self.call_id is not None:
                return self.call_id

            def operation(session: Any) -> str:
                price = session.query(DBModelPriceVersion).filter_by(
                    provider=self.provider, model=self.model, active=True,
                ).order_by(DBModelPriceVersion.effective_at.desc()).first()
                if price is not None:
                    self.input_cost_per_million = price.input_cost_per_million
                    self.output_cost_per_million = price.output_cost_per_million
                    self.pricing_version = price.version
                    self.pricing_currency = price.currency
                    self.pricing_basis = "operator_config"
                row = DBModelCall(
                    trace_id=self.trace_id,
                    task_id=self.task_id,
                    owner_public_id=self.owner_public_id,
                    course_id=self.course_id,
                    capability=self.capability,
                    prompt_version=self.prompt_version,
                    provider=self.provider,
                    model=self.model,
                    status="running",
                    input_summary=self.input_summary,
                    input_tokens=self.input_tokens,
                    token_source="estimated",
                    pricing_version=self.pricing_version,
                    cost_currency=self.pricing_currency,
                    cost_basis=self.pricing_basis,
                )
                session.add(row)
                session.commit()
                session.refresh(row)
                return row.id

            self.call_id = await self._run_db(operation)
            self._started_at = time.perf_counter()
            return self.call_id

    async def complete(self, output: str) -> None:
        await self._finalize(status="completed", output=output, error_code="")

    async def fail(self, error_code: str, output: str = "") -> None:
        await self._finalize(status="failed", output=output, error_code=error_code)

    async def _finalize(self, *, status: str, output: str, error_code: str) -> None:
        async with self._lock:
            if self._terminal:
                return
            if self.call_id is None:
                raise RuntimeError("streaming model call lifecycle was not started")
            output_tokens = _estimate_tokens(output) if output else 0
            duration_ms = max(
                0,
                int((time.perf_counter() - (self._started_at or time.perf_counter())) * 1000),
            )
            estimated_cost = (
                self.input_tokens * self.input_cost_per_million
                + output_tokens * self.output_cost_per_million
            ) / 1_000_000
            output_hash = hashlib.sha256(output.encode("utf-8")).hexdigest() if output else ""

            def operation(session: Any) -> None:
                row = session.query(DBModelCall).filter_by(id=self.call_id).one()
                row.status = status
                row.output_tokens = output_tokens
                row.estimated_cost = estimated_cost
                row.duration_ms = duration_ms
                row.output_hash = output_hash
                row.error_code = error_code
                row.completed_at = datetime.now(timezone.utc)
                if row.task_id:
                    task = session.query(DBGenerationTask).filter_by(id=row.task_id).first()
                    if task is not None:
                        task.estimated_cost = float(task.estimated_cost or 0) + estimated_cost
                session.commit()

            await self._run_db(operation)
            self._terminal = True


class M5ModelGateway:
    async def execute(
        self,
        session: Any,
        *,
        request: GatewayRequest,
        registration: ModelRegistration,
        backend: TextBackend,
        response_model: type[BaseModel] | None = None,
        policy: GatewayPolicy | None = None,
        trace_id: str | None = None,
        response_validator: Callable[[dict[str, Any]], BaseModel] | None = None,
    ) -> GatewayResult:
        registration = resolve_registration_pricing(session, registration)
        capability = request.contract.locked_capability
        if capability not in registration.capabilities:
            raise M5CapabilityError("model_capability_unsupported", "registered model does not support the locked capability")
        if (response_model is not None or response_validator is not None) and not registration.supports_json:
            raise M5CapabilityError("model_json_unsupported", "structured output requires a JSON-capable model")

        trace_id = trace_id or f"m5-{uuid.uuid4().hex}"
        input_tokens = _estimate_tokens(request.prompt.system_prompt + request.user_prompt)
        projected_output_tokens = 0
        if policy is not None:
            projected_output_tokens = max(
                1,
                (request.contract.output_constraints.max_length or 4096) // 4,
            )
            reserve_daily_quota(
                session,
                owner_public_id=request.owner_public_id,
                course_id=request.contract.course_id,
                registration=registration,
                policy=policy,
                estimated_input_tokens=input_tokens,
                estimated_output_tokens=projected_output_tokens,
            )
        input_summary = {
            "capability": capability.value,
            "quality_mode": request.contract.quality_mode.value,
            "prompt_key": request.prompt.key,
            "contract_schema": request.contract.schema_version,
            "course_id": request.contract.course_id,
            "domain_pack_id": request.contract.domain_pack_id,
            "profile_snapshot_id": request.contract.profile_snapshot_id,
            "active_artifact_count": len(request.contract.active_artifact_ids),
            "source_document_count": len(request.contract.source_document_ids),
            "knowledge_point_count": len(request.contract.target_knowledge_point_ids),
            "user_prompt_chars": len(request.user_prompt),
        }
        row = DBModelCall(
            trace_id=trace_id,
            task_id=request.task_id,
            owner_public_id=request.owner_public_id,
            course_id=request.contract.course_id,
            capability=capability.value,
            prompt_version=f"{request.prompt.key}:{request.prompt.version}",
            provider=registration.provider,
            model=registration.model,
            status="running",
            input_summary=input_summary,
            input_tokens=input_tokens,
            token_source="estimated",
            pricing_version=registration.pricing_version,
            cost_currency=registration.pricing_currency,
            cost_basis=registration.pricing_basis,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        started = time.perf_counter()
        try:
            raw = await backend.generate(
                request.prompt.system_prompt,
                request.user_prompt,
                role=request.role,
            )
        except asyncio.CancelledError:
            # A disconnected browser request must not leave an indefinitely
            # running model-call row that looks active on the next retry.
            row.status = "failed"
            row.error_code = "provider_call_cancelled"
            row.duration_ms = max(0, int((time.perf_counter() - started) * 1000))
            row.completed_at = datetime.now(timezone.utc)
            if policy is not None:
                reconcile_daily_quota(
                    session, owner_public_id=request.owner_public_id,
                    course_id=request.contract.course_id, registration=registration,
                    reserved_input_tokens=input_tokens, reserved_output_tokens=projected_output_tokens,
                    actual_input_tokens=input_tokens, actual_output_tokens=0,
                )
            session.commit()
            raise
        except Exception as exc:
            failure_cost = input_tokens * registration.input_cost_per_million / 1_000_000
            row.status = "failed"
            row.error_code = "provider_call_failed"
            row.estimated_cost = failure_cost
            row.duration_ms = max(0, int((time.perf_counter() - started) * 1000))
            row.completed_at = datetime.now(timezone.utc)
            if policy is not None:
                reconcile_daily_quota(
                    session, owner_public_id=request.owner_public_id,
                    course_id=request.contract.course_id, registration=registration,
                    reserved_input_tokens=input_tokens, reserved_output_tokens=projected_output_tokens,
                    actual_input_tokens=input_tokens, actual_output_tokens=0,
                )
            if row.task_id:
                task = session.query(DBGenerationTask).filter_by(id=row.task_id).first()
                if task is not None:
                    task.estimated_cost = float(task.estimated_cost or 0) + failure_cost
            session.commit()
            raise M5CapabilityError("provider_call_failed", "model provider call failed") from exc

        output_tokens = _estimate_tokens(raw)
        structured = None
        if response_model is not None or response_validator is not None:
            try:
                parsed = _parse_json_object(raw)
                validated = response_validator(parsed) if response_validator is not None else response_model.model_validate(parsed)
                structured = validated.model_dump(mode="json")
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                failure_cost = (
                    input_tokens * registration.input_cost_per_million
                    + output_tokens * registration.output_cost_per_million
                ) / 1_000_000
                row.status = "failed"
                row.error_code = "structured_output_invalid"
                row.output_tokens = output_tokens
                row.estimated_cost = failure_cost
                row.duration_ms = max(0, int((time.perf_counter() - started) * 1000))
                row.completed_at = datetime.now(timezone.utc)
                if policy is not None:
                    reconcile_daily_quota(
                        session, owner_public_id=request.owner_public_id,
                        course_id=request.contract.course_id, registration=registration,
                        reserved_input_tokens=input_tokens, reserved_output_tokens=projected_output_tokens,
                        actual_input_tokens=input_tokens, actual_output_tokens=output_tokens,
                    )
                if row.task_id:
                    task = session.query(DBGenerationTask).filter_by(id=row.task_id).first()
                    if task is not None:
                        task.estimated_cost = float(task.estimated_cost or 0) + failure_cost
                session.commit()
                raise M5CapabilityError("structured_output_invalid", "model output failed strict schema validation") from exc

        cost = (
            input_tokens * registration.input_cost_per_million
            + output_tokens * registration.output_cost_per_million
        ) / 1_000_000
        row.status = "completed"
        row.output_tokens = output_tokens
        row.estimated_cost = cost
        row.duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        row.output_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        row.completed_at = datetime.now(timezone.utc)
        if policy is not None:
            reconcile_daily_quota(
                session, owner_public_id=request.owner_public_id,
                course_id=request.contract.course_id, registration=registration,
                reserved_input_tokens=input_tokens, reserved_output_tokens=projected_output_tokens,
                actual_input_tokens=input_tokens, actual_output_tokens=output_tokens,
            )
        if row.task_id:
            task = session.query(DBGenerationTask).filter_by(id=row.task_id).first()
            if task is not None:
                task.estimated_cost = float(task.estimated_cost or 0) + cost
        session.commit()
        return GatewayResult(
            trace_id=trace_id,
            call_id=row.id,
            capability=capability,
            status="completed",
            text="" if structured is not None else raw,
            structured_output=structured,
            model=registration.model,
            prompt_version=row.prompt_version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            token_source="estimated",
            estimated_cost=cost,
            attempted_models=(f"{registration.provider}:{registration.model}",),
        )

    async def execute_with_policy(
        self,
        session: Any,
        *,
        request: GatewayRequest,
        registrations: tuple[ModelRegistration, ...],
        policy: GatewayPolicy,
        backends: dict[tuple[str, str], TextBackend],
        response_model: type[BaseModel] | None = None,
        trace_id: str | None = None,
        response_validator: Callable[[dict[str, Any]], BaseModel] | None = None,
    ) -> GatewayResult:
        priced_registrations = tuple(resolve_registration_pricing(session, item) for item in registrations)
        selection = select_model(request.contract, registrations=priced_registrations, policy=policy)
        by_ref = {(item.provider, item.model): item for item in priced_registrations}
        refs = (
            ModelRef(provider=selection.registration.provider, model=selection.registration.model),
            *selection.fallback_models,
        )
        attempted = []
        last_error: M5CapabilityError | None = None
        for ref in refs:
            registration = by_ref[(ref.provider, ref.model)]
            backend = backends.get((ref.provider, ref.model))
            attempted.append(f"{ref.provider}:{ref.model}")
            if backend is None:
                last_error = M5CapabilityError("model_backend_unavailable", "approved model backend is not configured")
                continue
            try:
                result = await self.execute(
                    session,
                    request=request,
                    registration=registration,
                    backend=backend,
                    response_model=response_model,
                    policy=policy,
                    trace_id=trace_id,
                    response_validator=response_validator,
                )
                return result.model_copy(update={
                    "attempted_models": tuple(attempted),
                    "fallback_used": len(attempted) > 1,
                })
            except M5CapabilityError as exc:
                last_error = exc
                if exc.code != "provider_call_failed":
                    raise
        raise M5CapabilityError(
            "all_model_routes_failed",
            f"all approved model routes failed: {getattr(last_error, 'code', 'unavailable')}",
        ) from last_error


async def execute_registered_structured_call(
    session: Any,
    *,
    backend: TextBackend,
    capability: Capability,
    system_prompt: str,
    user_prompt: str,
    role: str,
    operation: str,
    response_model: type[BaseModel],
    owner_public_id: str | None = None,
    course_id: str | None = None,
    task_id: str | None = None,
    trace_id: str | None = None,
    output_constraints: OutputConstraints | None = None,
    response_validator: Callable[[dict[str, Any]], BaseModel] | None = None,
) -> GatewayResult:
    """Route a legacy structured call through the registered model boundary."""
    provider = getattr(backend, "provider", None) or (
        "deterministic"
        if backend.__class__.__name__ == "AsyncDeterministicEducationLLM"
        else CONFIG.llm_provider
    ) or "unknown"
    model = getattr(
        backend,
        "model",
        "deterministic" if provider == "deterministic" else CONFIG.llm_model,
    ) or "unknown"
    registration = ModelRegistration(
        registration_version="next-compat-registry-v1",
        provider=provider,
        model=model,
        tier="standard",
        capabilities=(capability,),
        supports_json=True,
        context_length=max(1, CONFIG.llm_max_tokens),
    )
    policy = GatewayPolicy(
        policy_version="next-compat-policy-v1",
        allowed_models=(ModelRef(provider=provider, model=model),),
        allowed_capabilities=(capability,),
        daily_user_call_limit=10000,
        daily_user_token_limit=100_000_000,
        daily_user_cost_limit=10000,
        daily_course_call_limit=100000,
        daily_model_call_limit=100000,
    )
    digest = hashlib.sha256(
        f"{operation}:{owner_public_id}:{course_id}:{task_id}:{user_prompt}".encode("utf-8")
    ).hexdigest()[:24]
    request = GatewayRequest(
        contract=CapabilityContract(
            capability=capability,
            course_id=course_id,
            output_constraints=output_constraints or OutputConstraints(format="json"),
            idempotency_key=f"compat-{digest}",
        ),
        owner_public_id=owner_public_id,
        task_id=task_id,
        prompt=PromptSpec(key=operation[:64], version="1.0", system_prompt=system_prompt),
        user_prompt=user_prompt,
        role=role,
    )
    return await M5ModelGateway().execute_with_policy(
        session,
        request=request,
        registrations=(registration,),
        policy=policy,
        backends={(provider, model): backend},
        response_model=response_model,
        trace_id=trace_id,
        response_validator=response_validator,
    )
