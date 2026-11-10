from __future__ import annotations

import asyncio
import json
import httpx
import pytest

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


@pytest.mark.parametrize("text,finish_reason,error", [
    ("", "stop", "回答暂时没有生成"),
    ("一部分解释", "length", "回答尚未写完"),
    ("完整解释", "stop", None),
])
def test_stream_requires_visible_answer_and_honors_truncation(monkeypatch, text, finish_reason, error):
    import llm_client
    async def run():
        chunks = [
            {"choices": [{"delta": {"reasoning_content": "私有推理"}}]},
            {"choices": [{"delta": {"content": text}}]},
            {"choices": [{"delta": {}, "finish_reason": finish_reason}]},
        ]
        body = "".join("data:" + json.dumps(chunk, ensure_ascii=False) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, text=body))) as client:
            async def get_client(): return client
            monkeypatch.setattr(llm_client, "_get_httpx_client", get_client)
            llm = AsyncOpenAIChatLLM(endpoint="https://test.invalid/chat", api_key="test", model="test-stream")
            result = []
            async def consume():
                async for chunk in llm.generate_stream("教学", "说明", role="学习伙伴", images=[]): result.append(chunk)
            if error:
                with pytest.raises(RuntimeError, match=error): await consume()
            else:
                await consume()
            assert "私有推理" not in "".join(result)
            assert "".join(result) == text
    asyncio.run(run())


def test_nonstream_exhausted_output_is_not_retried_or_published(monkeypatch):
    import llm_client
    from llm_client import ModelOutputLimitError
    requests=[]
    def respond(request):
        requests.append(request)
        return httpx.Response(200,json={"choices":[{"finish_reason":"length", "message":{
            "content":"未写完的结论", "reasoning_content":"私有推理"}}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            async def get_client(): return client
            monkeypatch.setattr(llm_client,"_get_httpx_client",get_client)
            llm=AsyncOpenAIChatLLM(endpoint="https://test.invalid/chat",api_key="test",model="test")
            with pytest.raises(ModelOutputLimitError,match="还没有整理完整"):
                await llm.generate("教学核对","问题",role="Challenger")
            assert len(requests)==1
    asyncio.run(run())


@pytest.mark.parametrize("status", [402, 429, 503])
def test_payment_failure_stops_but_transient_provider_errors_can_recover(monkeypatch, status):
    import llm_client
    requests = []
    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(status, json={"error": "provider unavailable"})
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "完整结果"}}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            async def get_client(): return client
            monkeypatch.setattr(llm_client, "_get_httpx_client", get_client)
            llm = AsyncOpenAIChatLLM(endpoint="https://test.invalid/chat", api_key="test", model="test")
            if status == 402:
                with pytest.raises(httpx.HTTPStatusError) as caught:
                    await llm.generate("教学核对", "问题", role="Challenger")
                assert caught.value.response.status_code == 402
                assert len(requests) == 1
            else:
                assert await llm.generate("教学核对", "问题", role="Challenger") == "完整结果"
                assert len(requests) == 2
    asyncio.run(run())


@pytest.mark.parametrize('prompt,structured', [
    ('只输出一个 JSON 对象。', True), ('请解释图中 JSON 的作用。', False),
])
def test_streamed_attachment_planning_preserves_explicit_json_contract(monkeypatch, prompt, structured):
    import llm_client
    captured = []
    def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"{}"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            async def get_client(): return client
            monkeypatch.setattr(llm_client, '_get_httpx_client', get_client)
            llm = AsyncOpenAIChatLLM(endpoint='https://test.invalid/chat', api_key='test', model='test')
            result = [part async for part in llm._generate_stream_internal(
                prompt, '设计一个练习', role='Pedagogical', images=['data:image/png;base64,dGVzdA=='])]
            assert ''.join(result) == '{}'
    asyncio.run(run())
    assert captured[0].get('response_format') == ({'type': 'json_object'} if structured else None)
    assert captured[0]['messages'][1]['content'][1]['type'] == 'image_url'


def test_stopping_rate_limit_wait_releases_slot_for_next_question():
    from concurrency import APIRateLimiter
    async def run():
        limiter=APIRateLimiter(max_concurrent=1)
        entered=asyncio.Event()
        async def wait_tokens(*args,**kwargs):
            entered.set()
            await asyncio.Event().wait()
        limiter.rpm_bucket.acquire=wait_tokens
        task=asyncio.create_task(limiter.acquire())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        await asyncio.wait_for(limiter.request_semaphore.acquire(),timeout=.5)
        limiter.release()
    asyncio.run(run())


def test_actual_model_usage_releases_overreservation_and_accounts_for_reasoning():
    from concurrency import APIRateLimiter
    async def run():
        limiter = APIRateLimiter(max_tpm=100, max_concurrent=1)
        limiter.tpm_bucket.refill_rate = 0
        assert await limiter.acquire(estimated_tokens=90, timeout=.1)
        limiter.release()
        await limiter.account_usage(90, 20)
        assert await limiter.acquire(estimated_tokens=60, timeout=.1)
        limiter.release()
        # Extra reasoning output must also be charged; do not refund it.
        await limiter.account_usage(60, 80)
        assert not await limiter.acquire(estimated_tokens=1, timeout=.1)
        await asyncio.wait_for(limiter.request_semaphore.acquire(), timeout=.1)
        limiter.release()
    asyncio.run(run())


def test_zero_model_rate_quotas_allow_large_requests_but_keep_concurrency_queue():
    from concurrency import APIRateLimiter
    async def run():
        limiter = APIRateLimiter(max_rpm=0, max_tpm=0, max_concurrent=1)
        assert await asyncio.wait_for(limiter.acquire(estimated_tokens=10_000_000), timeout=.2)
        queued = asyncio.create_task(limiter.acquire(estimated_tokens=20_000_000))
        await asyncio.sleep(0)
        assert not queued.done()
        await limiter.account_usage(10_000_000, 30_000_000)
        limiter.release()
        assert await asyncio.wait_for(queued, timeout=.2)
        limiter.release()
    asyncio.run(run())


def test_routine_answer_settings_do_not_change_deep_reasoning_or_other_requests():
    from llm_client import for_answer_step
    original=AsyncOpenAIChatLLM(endpoint="https://test.invalid/chat",api_key="test",model="test",
                               thinking_mode="max",reasoning_effort="max")
    routine=for_answer_step(original,deep_reasoning=False)
    assert routine is not original
    assert (routine.thinking_mode,routine.reasoning_effort)==("disabled","")
    assert routine.rate_limiter is original.rate_limiter
    assert routine.circuit_breaker is original.circuit_breaker
    assert (original.thinking_mode,original.reasoning_effort)==("max","max")
    assert for_answer_step(original,deep_reasoning=True) is original
    planning = for_answer_step(original, deep_reasoning=True, reasoning_effort="high")
    assert planning is not original
    assert (planning.thinking_mode, planning.reasoning_effort) == ("enabled", "high")
    assert planning.rate_limiter is original.rate_limiter
    assert planning.circuit_breaker is original.circuit_breaker
    assert (original.thinking_mode, original.reasoning_effort) == ("max", "max")
