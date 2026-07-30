"""Unified M5 text-model call boundary with traceable, schema-checked results."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import time
from typing import Any, Protocol
import uuid

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.database import DBModelCall
from app.m2_contracts import StrictModel
from app.m5_capabilities import Capability, CapabilityContract, M5CapabilityError
from app.m5_policy import GatewayPolicy, ModelRegistration, ModelRef, enforce_daily_quota, reserve_daily_quota, select_model


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
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1])
            if text.lstrip().lower().startswith("json\n"):
                text = text.lstrip()[5:]
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("structured model output must be a JSON object")
    return value


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
    ) -> GatewayResult:
        capability = request.contract.locked_capability
        if capability not in registration.capabilities:
            raise M5CapabilityError("model_capability_unsupported", "registered model does not support the locked capability")
        if response_model is not None and not registration.supports_json:
            raise M5CapabilityError("model_json_unsupported", "structured output requires a JSON-capable model")

        trace_id = f"m5-{uuid.uuid4().hex}"
        input_tokens = _estimate_tokens(request.prompt.system_prompt + request.user_prompt)
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
        except Exception as exc:
            row.status = "failed"
            row.error_code = "provider_call_failed"
            row.duration_ms = max(0, int((time.perf_counter() - started) * 1000))
            row.completed_at = datetime.now(timezone.utc)
            session.commit()
            raise M5CapabilityError("provider_call_failed", "model provider call failed") from exc

        output_tokens = _estimate_tokens(raw)
        structured = None
        if response_model is not None:
            try:
                parsed = _parse_json_object(raw)
                structured = response_model.model_validate(parsed).model_dump(mode="json")
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                row.status = "failed"
                row.error_code = "structured_output_invalid"
                row.output_tokens = output_tokens
                row.duration_ms = max(0, int((time.perf_counter() - started) * 1000))
                row.completed_at = datetime.now(timezone.utc)
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
    ) -> GatewayResult:
        selection = select_model(request.contract, registrations=registrations, policy=policy)
        by_ref = {(item.provider, item.model): item for item in registrations}
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
