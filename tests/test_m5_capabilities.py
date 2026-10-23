import pytest
from pydantic import ValidationError

from app.m5_capabilities import (
    Capability,
    CapabilityContract,
    DeterministicAction,
    M5CapabilityError,
    OutputConstraints,
    QualityMode,
    RoutingRequest,
    RuntimeAvailability,
    route_capability,
)


READY = RuntimeAvailability(text_model=True, retrieval=True, sandbox_mode="trusted_local")


def _contract(**updates):
    data = {"idempotency_key": "idem-m5-001"}
    data.update(updates)
    return CapabilityContract(**data)


def test_m5_routes_r0_without_model_and_requires_confirmation_for_delete():
    ready = route_capability(
        RoutingRequest(contract=_contract(), deterministic_action=DeterministicAction.SEARCH), READY,
    )
    blocked = route_capability(
        RoutingRequest(contract=_contract(), deterministic_action=DeterministicAction.DELETE), READY,
    )
    assert (ready.route_level, ready.invokes_model, ready.status) == ("R0", False, "ready")
    assert blocked.status == "confirmation_required"
    assert blocked.invokes_model is False


def test_deterministic_demo_routes_without_claiming_an_external_text_model():
    runtime = RuntimeAvailability(deterministic_text_model=True)
    decision = route_capability(
        RoutingRequest(contract=CapabilityContract(idempotency_key="m5-deterministic-demo")),
        runtime,
    )
    assert runtime.text_model is False
    assert runtime.text_generation_available is True
    assert runtime.generation_mode == "deterministic_demo"
    assert decision.route_level == "R2" and decision.status == "ready"


def test_m5_locks_explicit_capability_and_preserves_plain_answer_default():
    default = route_capability(RoutingRequest(contract=_contract(), message="解释一下召回率"), READY)
    legacy = route_capability(RoutingRequest(contract=_contract(), message="/code 写一个例子"), READY)
    assert (default.capability, default.route_level) == (Capability.ANSWER, "R2")
    assert (legacy.capability, legacy.route_level) == (Capability.CODE, "R4")
    with pytest.raises(M5CapabilityError, match="conflicts"):
        route_capability(
            RoutingRequest(contract=_contract(capability=Capability.QUIZ), message="/code test"), READY,
        )


def test_m5_verified_and_specialized_contracts_fail_closed():
    with pytest.raises(ValidationError, match="verified mode requires"):
        _contract(capability=Capability.LECTURE, quality_mode=QualityMode.VERIFIED)
    with pytest.raises(ValidationError, match="environment and safety_boundary"):
        _contract(capability=Capability.PRACTICAL_GUIDE)
    experiment = _contract(
        capability=Capability.EXPERIMENT,
        output_constraints=OutputConstraints(runtime_mode="browser_simulation"),
    )
    unavailable = route_capability(
        RoutingRequest(contract=experiment), RuntimeAvailability(text_model=True, sandbox_mode="disabled"),
    )
    assert unavailable.status == "unavailable"
    assert "interactive_runtime_unavailable" in unavailable.blockers


def test_m5_routes_plan_and_compound_work_at_the_required_levels():
    plan = route_capability(RoutingRequest(contract=_contract(capability=Capability.PLAN)), READY)
    compound = route_capability(
        RoutingRequest(
            contract=_contract(capability=Capability.LECTURE),
            compound_capabilities=(Capability.LECTURE, Capability.TIERED_QUIZ),
        ),
        READY,
    )
    assert (plan.route_level, plan.status) == ("R3", "confirmation_required")
    assert (compound.route_level, compound.status, compound.estimated_cost_class) == ("R5", "ready", "high")
