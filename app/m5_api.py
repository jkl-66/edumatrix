"""Authenticated M5 capability discovery and route preflight API."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user
from app.database import DBUser
from app.m5_capabilities import (
    M5CapabilityError,
    RoutingRequest,
    RuntimeAvailability,
    capability_statuses,
    route_capability,
)
from config import CONFIG


router = APIRouter(prefix="/api/v1/m5", tags=["m5-capabilities"])
ROOT = Path(__file__).resolve().parents[1]


def runtime_availability() -> RuntimeAvailability:
    provider = CONFIG.llm_provider.strip().lower()
    text_model = bool(CONFIG.llm_endpoint and CONFIG.llm_api_key and CONFIG.llm_model) and provider not in {"mock", "deterministic"}
    vision_model = bool(
        CONFIG.multimodal_llm_endpoint and CONFIG.multimodal_llm_api_key and CONFIG.multimodal_llm_model
    )
    retrieval = any((ROOT / "data" / "faiss_indexes").glob("*.faiss"))
    sandbox = CONFIG.sandbox_mode if CONFIG.sandbox_mode in {"disabled", "trusted_local", "docker", "external_lab"} else "disabled"
    return RuntimeAvailability(
        text_model=text_model,
        vision_model=vision_model,
        retrieval=retrieval,
        media_pipeline=(ROOT / "data" / "animations").is_dir(),
        sandbox_mode=sandbox,
    )


@router.get("/capabilities")
async def list_capabilities(current_user: DBUser = Depends(get_current_user)):
    runtime = runtime_availability()
    return {
        "schema_version": "m5.capability-status.v1",
        "runtime": runtime.model_dump(mode="json"),
        "capabilities": [item.model_dump(mode="json") for item in capability_statuses(runtime)],
        "user_configurable_secrets": False,
    }


@router.post("/route")
async def preflight_route(payload: RoutingRequest, current_user: DBUser = Depends(get_current_user)):
    try:
        decision = route_capability(payload, runtime_availability())
        return decision.model_dump(mode="json")
    except M5CapabilityError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc
