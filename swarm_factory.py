from __future__ import annotations

import os
from typing import Any
from agent_swarm import EduMatrixSwarm
from llm_client import AsyncDeterministicEducationLLM, build_async_llm, AsyncOpenAIChatLLM
from rag_engine import hybrid_rag
from cache_utils import TTLBoundedCache
from config import CONFIG

_swarm_cache: TTLBoundedCache[str, EduMatrixSwarm] = TTLBoundedCache(
    maxsize=CONFIG.cache_max_entries,
    ttl_seconds=CONFIG.cache_ttl_seconds,
)


def build_swarm_from_headers(headers: dict[str, str] | Any) -> EduMatrixSwarm:
    # The browser acceptance path must not depend on an external provider. This
    # explicit header is available only outside production and is used by the
    # deterministic E2E harness, never as an implicit production fallback.
    deterministic_requested = (
        str(headers.get("x-edumatrix-llm-mode", "")).strip().lower() == "deterministic"
    )
    environment = os.getenv("EDUMATRIX_ENV", "development").strip().lower()
    if deterministic_requested and environment not in {"production", "prod"}:
        deterministic = _swarm_cache.get("__deterministic__")
        if deterministic is not None:
            return deterministic
        deterministic = EduMatrixSwarm(
            rag=hybrid_rag,
            llm=AsyncDeterministicEducationLLM(),
        )
        _swarm_cache["__deterministic__"] = deterministic
        return deterministic

    # All provider credentials and model selection come from backend-managed
    # configuration. Request headers are deliberately ignored so an external
    # caller cannot inject a provider, endpoint, model, or secret.
    default = _swarm_cache.get("__default__")
    if default is not None:
        return default
    default_swarm = EduMatrixSwarm(rag=hybrid_rag, llm=build_async_llm())
    _swarm_cache["__default__"] = default_swarm
    return default_swarm
