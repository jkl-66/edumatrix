from __future__ import annotations

from typing import Any
from agent_swarm import EduMatrixSwarm
from llm_client import build_async_llm, AsyncOpenAIChatLLM
from rag_engine import hybrid_rag

_swarm_cache: dict[str, EduMatrixSwarm] = {}


def build_swarm_from_headers(headers: dict[str, str] | Any) -> EduMatrixSwarm:
    api_key = headers.get("x-edumatrix-api-key", "")
    endpoint = headers.get("x-edumatrix-endpoint", "")
    model = headers.get("x-edumatrix-model", "")
    temp_str = headers.get("x-edumatrix-temperature", "")
    mt_str = headers.get("x-edumatrix-max-tokens", "")
    
    mm_api_key = headers.get("x-edumatrix-multimodal-api-key", "")
    mm_endpoint = headers.get("x-edumatrix-multimodal-endpoint", "")
    mm_model = headers.get("x-edumatrix-multimodal-model", "")

    if not api_key:
        default = _swarm_cache.get("__default__")
        if default is not None:
            return default
        default_swarm = EduMatrixSwarm(rag=hybrid_rag, llm=build_async_llm())
        _swarm_cache["__default__"] = default_swarm
        return default_swarm

    temperature = 0.3
    max_tokens = 4096
    if temp_str:
        try:
            temperature = float(temp_str)
        except Exception:
            pass
    if mt_str:
        try:
            max_tokens = int(mt_str)
        except Exception:
            pass

    cache_key = f"{api_key[-8:]}::{endpoint}::{model}::{temperature}::{max_tokens}::{mm_api_key[-8:] if mm_api_key else ''}::{mm_endpoint}::{mm_model}"
    cached = _swarm_cache.get(cache_key)
    if cached is not None:
        return cached

    dynamic_llm = build_async_llm(
        api_key=api_key or None,
        endpoint=endpoint or None,
        model=model or None,
        temperature=temperature,
        max_tokens=max_tokens,
        multimodal_api_key=mm_api_key or None,
        multimodal_endpoint=mm_endpoint or None,
        multimodal_model=mm_model or None,
    )
    new_swarm = EduMatrixSwarm(rag=hybrid_rag, llm=dynamic_llm)
    _swarm_cache[cache_key] = new_swarm
    return new_swarm
