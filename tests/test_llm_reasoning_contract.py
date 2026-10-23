from __future__ import annotations

from config import CONFIG
from llm_client import (
    AsyncOpenAIChatLLM,
    apply_thinking_mode,
    build_async_llm,
    extract_structured_json_from_reasoning,
)


def test_deepseek_max_reasoning_is_preserved_in_openai_compatible_payload():
    payload: dict[str, object] = {}
    apply_thinking_mode(payload, "max")
    assert payload == {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "max",
    }


def test_explicit_reasoning_effort_overrides_provider_default_without_disabling_thinking():
    payload: dict[str, object] = {}
    apply_thinking_mode(payload, "enabled", "max")
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "max"


def test_configured_live_provider_does_not_silently_wrap_deterministic_fallback():
    backend = build_async_llm()
    if CONFIG.llm_provider in {"openai", "vllm"} and CONFIG.llm_api_key:
        assert isinstance(backend, AsyncOpenAIChatLLM)


def test_structured_reasoning_recovery_returns_only_json_object():
    reasoning = '先分析课程图谱。最终输出如下： {"plan":{"nodes":[]},"personalization_summary":"按诊断结果安排"}'
    assert extract_structured_json_from_reasoning(reasoning) == (
        '{"plan":{"nodes":[]},"personalization_summary":"按诊断结果安排"}'
    )
    assert extract_structured_json_from_reasoning("只有推理，没有最终对象") == ""
