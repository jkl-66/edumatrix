"""M5 capability contracts, truthful availability, and R0-R5 routing."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import ConfigDict, Field, model_validator

from app.m2_contracts import StrictModel


class M5CapabilityError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class Capability(str, Enum):
    ANSWER = "answer"
    LECTURE = "lecture"
    PRACTICAL_GUIDE = "practical_guide"
    MINDMAP = "mindmap"
    CODE = "code"
    QUIZ = "quiz"
    TIERED_QUIZ = "tiered_quiz"
    VIDEO = "video"
    EXPERIMENT = "experiment"
    SLIDES = "slides"
    REPORT = "report"
    MATCH_REPORT = "match_report"
    DECISION = "decision"
    PLAN = "plan"


class QualityMode(str, Enum):
    FAST = "fast"
    STANDARD = "standard"
    VERIFIED = "verified"


class DeterministicAction(str, Enum):
    SEARCH = "search"
    FILTER = "filter"
    OPEN = "open"
    CLOSE = "close"
    MOVE = "move"
    SAVE = "save"
    DELETE = "delete"
    PUBLISH = "publish"


class OutputConstraints(StrictModel):
    language: str = Field(default="zh-CN", min_length=2, max_length=16)
    format: str = Field(default="markdown", min_length=1, max_length=32)
    max_length: int | None = Field(default=None, ge=1, le=200000)
    section_count: int | None = Field(default=None, ge=1, le=100)
    source_scope: tuple[str, ...] = ()
    environment: tuple[str, ...] = ()
    safety_boundary: str = Field(default="", max_length=2000)
    runtime_mode: Literal["browser_simulation", "trusted_local", "docker", "external_lab"] | None = None


class CapabilityContract(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    schema_version: Literal["m5.capability.v1"] = "m5.capability.v1"
    capability: Capability | None = None
    quality_mode: QualityMode = QualityMode.FAST
    course_id: str | None = Field(default=None, min_length=3, max_length=64)
    domain_pack_id: str | None = Field(default=None, min_length=3, max_length=64)
    profile_snapshot_id: str | None = Field(default=None, min_length=3, max_length=64)
    active_artifact_ids: tuple[str, ...] = ()
    source_document_ids: tuple[str, ...] = ()
    target_knowledge_point_ids: tuple[str, ...] = ()
    target_difficulty_band: str | None = Field(default=None, max_length=64)
    output_constraints: OutputConstraints = OutputConstraints()
    plan_version_id: str | None = Field(default=None, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=128)

    @property
    def locked_capability(self) -> Capability:
        return self.capability or Capability.ANSWER

    @model_validator(mode="after")
    def validate_specialized_contracts(self) -> "CapabilityContract":
        reference_groups = (
            self.active_artifact_ids,
            self.source_document_ids,
            self.target_knowledge_point_ids,
        )
        if any(len(values) != len(set(values)) for values in reference_groups):
            raise ValueError("object references must be unique within each reference type")
        if self.quality_mode == QualityMode.VERIFIED:
            required = {
                "course_id": self.course_id,
                "domain_pack_id": self.domain_pack_id,
                "profile_snapshot_id": self.profile_snapshot_id,
                "target_knowledge_point_ids": self.target_knowledge_point_ids,
                "target_difficulty_band": self.target_difficulty_band,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError(f"verified mode requires: {', '.join(missing)}")
        if self.locked_capability == Capability.PRACTICAL_GUIDE:
            if not self.output_constraints.environment or not self.output_constraints.safety_boundary:
                raise ValueError("practical_guide requires environment and safety_boundary")
        if self.locked_capability == Capability.EXPERIMENT and self.output_constraints.runtime_mode is None:
            raise ValueError("experiment requires an explicit runtime_mode")
        return self


class RuntimeAvailability(StrictModel):
    text_model: bool = False
    deterministic_text_model: bool = False
    vision_model: bool = False
    retrieval: bool = False
    media_pipeline: bool = False
    sandbox_mode: Literal["disabled", "trusted_local", "docker", "external_lab"] = "disabled"

    @property
    def text_generation_available(self) -> bool:
        return self.text_model or self.deterministic_text_model

    @property
    def generation_mode(self) -> Literal["external_model", "deterministic_demo", "unavailable"]:
        if self.text_model:
            return "external_model"
        if self.deterministic_text_model:
            return "deterministic_demo"
        return "unavailable"


class CapabilityStatus(StrictModel):
    capability: Capability
    available: bool
    blockers: tuple[str, ...] = ()
    silent_downgrade_allowed: Literal[False] = False


class RoutingRequest(StrictModel):
    contract: CapabilityContract
    message: str = Field(default="", max_length=100000)
    deterministic_action: DeterministicAction | None = None
    natural_action: bool = False
    compound_capabilities: tuple[Capability, ...] = ()
    confirmation_token: str | None = Field(default=None, min_length=8, max_length=128)

    @model_validator(mode="after")
    def mutually_exclusive_route_inputs(self) -> "RoutingRequest":
        if self.deterministic_action is not None and self.compound_capabilities:
            raise ValueError("deterministic and compound routes cannot be combined")
        if self.natural_action and self.deterministic_action is None:
            raise ValueError("natural_action requires a proposed deterministic_action")
        if len(set(self.compound_capabilities)) != len(self.compound_capabilities):
            raise ValueError("compound capabilities must be unique")
        return self


class RouteDecision(StrictModel):
    schema_version: Literal["m5.route-decision.v1"] = "m5.route-decision.v1"
    capability: Capability
    route_level: Literal["R0", "R1", "R2", "R3", "R4", "R5"]
    status: Literal["ready", "confirmation_required", "unavailable"]
    invokes_model: bool
    capability_locked: Literal[True] = True
    reason_code: str
    blockers: tuple[str, ...] = ()
    requires_confirmation: bool = False
    estimated_cost_class: Literal["none", "low", "medium", "high"]


LEGACY_COMMANDS = {
    "/explain": Capability.ANSWER,
    "/map": Capability.MINDMAP,
    "/code": Capability.CODE,
    "/quiz": Capability.QUIZ,
    "/video": Capability.VIDEO,
}


def normalize_legacy_command(contract: CapabilityContract, message: str) -> Capability:
    command = message.strip().split(maxsplit=1)[0].lower() if message.strip().startswith("/") else ""
    mapped = LEGACY_COMMANDS.get(command)
    if mapped is None:
        return contract.locked_capability
    if contract.capability is not None and contract.capability != mapped:
        raise M5CapabilityError(
            "capability_lock_conflict",
            f"explicit capability {contract.capability.value} conflicts with legacy command {command}",
        )
    return mapped


def capability_statuses(runtime: RuntimeAvailability) -> tuple[CapabilityStatus, ...]:
    statuses = []
    for capability in Capability:
        blockers = []
        if not runtime.text_generation_available:
            blockers.append("text_model_unavailable")
        if capability == Capability.VIDEO and not runtime.media_pipeline:
            blockers.append("media_pipeline_unavailable")
        if capability == Capability.EXPERIMENT and runtime.sandbox_mode == "disabled":
            blockers.append("interactive_runtime_unavailable")
        statuses.append(CapabilityStatus(capability=capability, available=not blockers, blockers=tuple(blockers)))
    return tuple(statuses)


def route_capability(request: RoutingRequest, runtime: RuntimeAvailability) -> RouteDecision:
    capability = normalize_legacy_command(request.contract, request.message)
    if request.deterministic_action is not None:
        level = "R1" if request.natural_action else "R0"
        risky = request.deterministic_action in {DeterministicAction.DELETE, DeterministicAction.PUBLISH}
        if risky and not request.confirmation_token:
            return RouteDecision(
                capability=capability, route_level=level, status="confirmation_required",
                invokes_model=request.natural_action, reason_code="risky_action_confirmation_required",
                requires_confirmation=True, estimated_cost_class="low" if request.natural_action else "none",
            )
        if request.natural_action and not runtime.text_generation_available:
            return RouteDecision(
                capability=capability, route_level=level, status="unavailable", invokes_model=True,
                reason_code="intent_model_unavailable", blockers=("text_model_unavailable",),
                estimated_cost_class="low",
            )
        return RouteDecision(
            capability=capability, route_level=level, status="ready", invokes_model=request.natural_action,
            reason_code="authorized_deterministic_action", estimated_cost_class="low" if request.natural_action else "none",
        )

    if len(request.compound_capabilities) >= 2:
        level, cost = "R5", "high"
    elif capability in {Capability.PLAN, Capability.DECISION}:
        level, cost = "R3", "medium"
    elif capability == Capability.ANSWER:
        level, cost = "R2", "low"
    else:
        level, cost = "R4", "medium"

    status_map = {item.capability: item for item in capability_statuses(runtime)}
    selected = request.compound_capabilities or (capability,)
    blockers = tuple(sorted({blocker for item in selected for blocker in status_map[item].blockers}))
    if blockers:
        return RouteDecision(
            capability=capability, route_level=level, status="unavailable", invokes_model=True,
            reason_code="capability_dependencies_unavailable", blockers=blockers,
            estimated_cost_class=cost,
        )
    needs_confirmation = level == "R3" and request.confirmation_token is None
    return RouteDecision(
        capability=capability, route_level=level,
        status="confirmation_required" if needs_confirmation else "ready",
        invokes_model=True,
        reason_code="plan_confirmation_required" if needs_confirmation else "capability_route_selected",
        requires_confirmation=needs_confirmation,
        estimated_cost_class=cost,
    )
