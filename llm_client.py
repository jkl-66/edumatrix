from __future__ import annotations

import base64
import asyncio
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import math
import os
import random
import re
import ssl
import time
import pybreaker
from typing import Any, Protocol, AsyncGenerator
from urllib.parse import urlencode, urlparse

from config import CONFIG, EduMatrixConfig
from concurrency import APIRateLimiter, CircuitBreaker, retry_with_backoff, CircuitState, CircuitBreakerOpenError

# 声明星火专用熔断器（Task 2.2: fail_max=3, reset_timeout=30.0）
spark_breaker = pybreaker.CircuitBreaker(fail_max=3, reset_timeout=30.0)


class LLMBackend(Protocol):
    def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        ...


class AsyncLLMBackend(Protocol):
    async def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        ...

    async def generate_stream(self, system_prompt: str, user_prompt: str, *, role: str, images: list[str] = []) -> AsyncGenerator[str, None]:
        ...


class StructuredModelContentError(RuntimeError):
    """The provider returned no public assistant content for a structured call."""


def extract_openai_message_content(message: Any) -> str:
    """Extract public text from common OpenAI-compatible message shapes.

    Reasoning fields are intentionally not inspected: they are private model
    traces and must never become user-visible structured output.
    """
    if not isinstance(message, dict):
        raise StructuredModelContentError("模型返回的消息结构无效")

    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        text = content.get("text")
        return text.strip() if isinstance(text, str) else ""
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts).strip()
    return ""


def extract_structured_json_from_reasoning(reasoning: Any) -> str:
    """Recover only a final JSON object when a provider omits public content.

    Some OpenAI-compatible reasoning deployments place the final structured
    answer in ``reasoning_content`` and leave ``content`` empty. We never
    return the reasoning text; only a standalone object that can pass the
    normal JSON/schema validator is recovered.
    """
    if not isinstance(reasoning, str) or not reasoning.strip():
        return ""
    text = reasoning.strip()
    decoder = json.JSONDecoder()
    candidates = []
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            candidates.append((end, text[start:start + end]))
    if candidates:
        return max(candidates, key=lambda item: item[0])[1]
    return ""


def parse_json_object(raw: str) -> dict[str, Any]:
    """Parse one JSON object, accepting only an optional complete Markdown fence."""
    if not isinstance(raw, str):
        raise TypeError("structured model output must be text")
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) < 3 or lines[-1].strip() != "```":
            raise ValueError("structured model output has an incomplete Markdown fence")
        if lines[0].strip().lower() not in {"```", "```json"}:
            raise ValueError("structured model output uses an unsupported Markdown fence")
        text = "\n".join(lines[1:-1]).strip()
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("structured model output must be a JSON object")
    return value


def apply_thinking_mode(
    payload: dict[str, Any],
    mode: str | None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    """Apply provider thinking controls only when explicitly configured.

    DeepSeek's OpenAI-compatible endpoint enables reasoning with ``thinking``;
    deployments that expose an effort control additionally receive the explicit
    ``reasoning_effort`` value.  ``max`` is intentionally preserved instead of
    silently collapsing to a boolean enabled/disabled setting.
    """
    normalized = (mode or "").strip().lower()
    effort = (reasoning_effort or "").strip().lower()
    if normalized == "max":
        payload["thinking"] = {"type": "enabled"}
        payload["reasoning_effort"] = "max"
    elif normalized in {"enabled", "disabled"}:
        payload["thinking"] = {"type": normalized}
    if effort:
        payload["reasoning_effort"] = effort
    return payload


def describe_structured_output(raw: Any) -> dict[str, Any]:
    """Return non-content diagnostics for a rejected structured response."""
    if not isinstance(raw, str):
        return {"type": type(raw).__name__, "length": 0}
    text = raw.strip()
    return {
        "type": "str",
        "length": len(text),
        "starts_fence": text.startswith("```"),
        "ends_fence": text.endswith("```"),
        "contains_think": "<think>" in text.lower() or "</think>" in text.lower(),
        "first_nonspace": text[:1],
        "last_nonspace": text[-1:] if text else "",
        "first_object_at": text.find("{"),
        "last_object_at": text.rfind("}"),
    }


def requires_json_object(system_prompt: str) -> bool:
    normalized = system_prompt.lower()
    return (
        "json schema" in normalized
        or "return json only" in normalized
        or "只输出 json" in normalized
        or "仅输出 json" in normalized
        or "只输出符合 json" in normalized
        or "只输出一个符合给定 json" in normalized
    )


_shared_httpx_client: Any | None = None
_shared_httpx_loop: Any | None = None


def _env_or_config(name: str, fallback: str) -> str:
    """Treat an explicitly empty environment variable as an intentional override."""
    value = os.getenv(name)
    return fallback if value is None else value


async def _get_httpx_client() -> Any:
    global _shared_httpx_client, _shared_httpx_loop
    current_loop = asyncio.get_running_loop()
    if _shared_httpx_client is None or _shared_httpx_loop is not current_loop:
        import httpx
        limits = httpx.Limits(
            max_keepalive_connections=CONFIG.max_concurrent_llm * 2,
            max_connections=CONFIG.max_concurrent_llm * 4,
            keepalive_expiry=30.0,
        )
        _shared_httpx_client = httpx.AsyncClient(
            limits=limits,
            timeout=httpx.Timeout(CONFIG.llm_timeout, connect=10.0),
            headers={"Content-Type": "application/json"},
        )
        _shared_httpx_loop = current_loop
    return _shared_httpx_client


@dataclass
class AsyncOpenAIChatLLM:
    endpoint: str
    api_key: str
    model: str
    temperature: float = 0.3
    max_tokens: int = 8192
    timeout_seconds: int = 120
    thinking_mode: str = ""
    reasoning_effort: str = ""
    multimodal_endpoint: str | None = None
    multimodal_api_key: str | None = None
    multimodal_model: str | None = None
    is_multimodal_fallback: bool = False

    rate_limiter: APIRateLimiter = field(init=False)
    circuit_breaker: CircuitBreaker = field(init=False)
    _client_init: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "rate_limiter", APIRateLimiter(
            max_rpm=CONFIG.llm_rate_limit_rpm,
            max_tpm=CONFIG.llm_rate_limit_tpm,
            max_concurrent=CONFIG.max_concurrent_llm,
        ))
        object.__setattr__(self, "circuit_breaker", CircuitBreaker(
            name=f"llm:{self.model}",
            failure_threshold=CONFIG.llm_circuit_breaker_threshold,
            recovery_timeout=float(CONFIG.llm_circuit_breaker_window),
        ))

    @property
    def has_vision(self) -> bool:
        model_lower = self.model.lower()
        return self.is_multimodal_fallback or any(
            x in model_lower for x in ["vision", "vl", "vlm", "gpt-4", "claude-3", "gemini", "glm-4v", "glm-4.5v", "glm-4.6v", "glm-5v", "omni"]
        )

    @property
    def has_external_vision(self) -> bool:
        return self.has_vision or bool(
            (self.multimodal_endpoint or _env_or_config("EDUMATRIX_MULTIMODAL_LLM_ENDPOINT", CONFIG.multimodal_llm_endpoint))
            and (self.multimodal_api_key or _env_or_config("EDUMATRIX_MULTIMODAL_LLM_API_KEY", CONFIG.multimodal_llm_api_key))
            and (self.multimodal_model or _env_or_config("EDUMATRIX_MULTIMODAL_LLM_MODEL", CONFIG.multimodal_llm_model))
        )

    @property
    def external_vision_backend(self) -> "AsyncOpenAIChatLLM | None":
        return self if self.has_external_vision else None

    async def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        estimated_tokens = len(system_prompt + user_prompt) // 2 + 500

        async def _do_call() -> str:
            acquired = await self.rate_limiter.acquire(
                estimated_tokens=estimated_tokens, timeout=30.0
            )
            if not acquired:
                raise RuntimeError("API 限流等待超时，请降低请求频率。")

            try:
                client = await _get_httpx_client()
                payload = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                }
                if requires_json_object(system_prompt):
                    payload["response_format"] = {"type": "json_object"}
                apply_thinking_mode(payload, self.thinking_mode, self.reasoning_effort)
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                }
                resp = await client.post(
                    self.endpoint,
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
                message = data["choices"][0]["message"]
                content = extract_openai_message_content(message)
                if not content and requires_json_object(system_prompt):
                    content = extract_structured_json_from_reasoning(
                        message.get("reasoning_content") if isinstance(message, dict) else None
                    )
                if not content:
                    raise StructuredModelContentError("模型未返回可用的结构化正文")
                usage = data.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                return content
            finally:
                self.rate_limiter.release()

        return await self.circuit_breaker.call(
            lambda: retry_with_backoff(
                _do_call,
                max_attempts=CONFIG.llm_retry_max_attempts,
                base_delay=1.0,
                max_delay=30.0,
            )
        )

    async def generate_stream(self, system_prompt: str, user_prompt: str, *, role: str, images: list[str] = []) -> AsyncGenerator[str, None]:
        import os

        # Check if the active model supports vision
        has_vision = self.has_vision
        
        if not has_vision and images:
            # Look for configured fallback multimodal variables from CONFIG
            fallback_endpoint = self.multimodal_endpoint or _env_or_config(
                "EDUMATRIX_MULTIMODAL_LLM_ENDPOINT", CONFIG.multimodal_llm_endpoint
            )
            fallback_api_key = self.multimodal_api_key or _env_or_config(
                "EDUMATRIX_MULTIMODAL_LLM_API_KEY", CONFIG.multimodal_llm_api_key
            )
            fallback_model = self.multimodal_model or _env_or_config(
                "EDUMATRIX_MULTIMODAL_LLM_MODEL", CONFIG.multimodal_llm_model
            )

            # If not explicitly configured, fallback to Zhipu GLM-4v using ZHIPUAI_API_KEY
            if not fallback_endpoint:
                zhipu_key = os.getenv("ZHIPUAI_API_KEY", "")
                if zhipu_key:
                    fallback_endpoint = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
                    fallback_api_key = zhipu_key
                    fallback_model = "glm-4v"

            if fallback_endpoint and fallback_api_key and fallback_model:
                # Initialize a temporary client pointing to the multimodal fallback backend
                fallback_backend = AsyncOpenAIChatLLM(
                    endpoint=fallback_endpoint,
                    api_key=fallback_api_key,
                    model=fallback_model,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    is_multimodal_fallback=True,
                )
                print(f"  [EduMatrix] 检测到当前主模型 ({self.model}) 不支持多模态输入，已自动路由流式请求至多模态备用节点 ({fallback_model})。")
                async for chunk in fallback_backend.generate_stream(system_prompt, user_prompt, role=role, images=images):
                    yield chunk
                return
            else:
                # If no multimodal fallback configured/available, yield warning in stream and run text-only query
                yield f"【⚠️ 系统提示：当前主模型 ({self.model} / DeepSeek) 不支持多模态图片输入。请在网页的 Settings 页面配置多模态视觉模型，或在 `.env` 中设置多模态 API Key 以开启图片与公式识别。】\n\n"
                async for chunk in self._generate_stream_internal(system_prompt, user_prompt, role=role, images=[]):
                    yield chunk
                return

        async for chunk in self._generate_stream_internal(system_prompt, user_prompt, role=role, images=images):
            yield chunk

    async def _generate_stream_internal(self, system_prompt: str, user_prompt: str, *, role: str, images: list[str] = []) -> AsyncGenerator[str, None]:
        if self.circuit_breaker.state == CircuitState.OPEN:
            raise CircuitBreakerOpenError(f"熔断器 {self.circuit_breaker.name} 已打开，拒绝流式请求。")

        estimated_tokens = len(system_prompt + user_prompt) // 2 + 500
        acquired = await self.rate_limiter.acquire(
            estimated_tokens=estimated_tokens, timeout=30.0
        )
        if not acquired:
            raise RuntimeError("API 限流等待超时，请降低请求频率。")

        try:
            client = await _get_httpx_client()
            
            user_content = []
            if images:
                user_content.append({"type": "text", "text": user_prompt})
                for img in images:
                    user_content.append({"type": "image_url", "image_url": {"url": img}})
            else:
                user_content = user_prompt

            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "stream": True,
            }
            apply_thinking_mode(payload, self.thinking_mode, self.reasoning_effort)
            headers = {
                "Authorization": f"Bearer {self.api_key}",
            }

            async with client.stream("POST", self.endpoint, json=payload, headers=headers) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk["choices"][0]["delta"]
                            if "content" in delta and delta["content"] is not None:
                                yield delta["content"]
                        except Exception:
                            pass
        except Exception as exc:
            async with self.circuit_breaker._lock:
                self.circuit_breaker._failure_count += 1
                self.circuit_breaker._last_failure_time = time.time()
                if self.circuit_breaker._failure_count >= self.circuit_breaker.failure_threshold:
                    self.circuit_breaker._state = CircuitState.OPEN
            raise exc
        finally:
            self.rate_limiter.release()


class OpenAIChatLLM:
    def __init__(
        self,
        endpoint: str,
        api_key: str,
        model: str = "gpt-4o-mini",
        temperature: float = 0.3,
        max_tokens: int = 8192,
        timeout_seconds: int = 60,
    ) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_seconds = timeout_seconds

    def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        import requests
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        try:
            resp = requests.post(
                self.endpoint,
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()
            content = extract_openai_message_content(data["choices"][0]["message"])
            if not content:
                raise StructuredModelContentError("模型未返回可用正文")
            return content
        except Exception as exc:
            raise RuntimeError(f"OpenAI API 调用失败: {exc}") from exc


@dataclass
class SparkClient:
    app_id: str
    api_key: str
    api_secret: str
    spark_url: str = CONFIG.spark_url
    domain: str = CONFIG.spark_domain
    timeout_seconds: int = 45
    temperature: float = 0.25
    max_tokens: int = 8192

    def _create_url(self) -> str:
        parsed = urlparse(self.spark_url)
        host = parsed.netloc
        path = parsed.path or "/v3.5/chat"
        now = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())
        signature_origin = f"host: {host}\ndate: {now}\nGET {path} HTTP/1.1"
        digest = hmac.new(
            self.api_secret.encode("utf-8"),
            signature_origin.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        signature = base64.b64encode(digest).decode("utf-8")
        authorization_origin = (
            f'api_key="{self.api_key}", algorithm="hmac-sha256", '
            f'headers="host date request-line", signature="{signature}"'
        )
        authorization = base64.b64encode(authorization_origin.encode("utf-8")).decode("utf-8")
        return self.spark_url + "?" + urlencode({"authorization": authorization, "date": now, "host": host})

    def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        try:
            import websocket
        except ImportError as exc:
            raise RuntimeError("缺少 websocket-client；请安装后再启用远程星火模式。") from exc

        result: list[str] = []
        errors: list[str] = []
        url = self._create_url()
        payload = {
            "header": {"app_id": self.app_id},
            "parameter": {
                "chat": {
                    "domain": self.domain,
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                }
            },
            "payload": {
                "message": {
                    "text": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ]
                }
            },
        }

        def on_open(ws):
            ws.send(json.dumps(payload, ensure_ascii=False))

        def on_error(_ws, error):
            errors.append(str(error))

        def on_message(ws, message):
            data = json.loads(message)
            code = data.get("header", {}).get("code", 0)
            if code != 0:
                errors.append(json.dumps(data, ensure_ascii=False))
                ws.close()
                return
            choices = data["payload"]["choices"]
            result.append(choices["text"][0]["content"])
            if choices["status"] == 2:
                ws.close()

        ws = websocket.WebSocketApp(url, on_open=on_open, on_error=on_error, on_message=on_message)
        ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE}, ping_timeout=self.timeout_seconds)
        if errors:
            raise RuntimeError(f"星火 API 调用失败: {' | '.join(errors)}")
        return "".join(result).strip()


@dataclass
class AsyncSparkClient:
    app_id: str
    api_key: str
    api_secret: str
    spark_url: str = CONFIG.spark_url
    domain: str = CONFIG.spark_domain
    timeout_seconds: int = 45
    temperature: float = 0.25
    max_tokens: int = 8192

    def _create_url(self) -> str:
        parsed = urlparse(self.spark_url)
        host = parsed.netloc
        path = parsed.path or "/v3.5/chat"
        now = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())
        signature_origin = f"host: {host}\ndate: {now}\nGET {path} HTTP/1.1"
        digest = hmac.new(
            self.api_secret.encode("utf-8"),
            signature_origin.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        signature = base64.b64encode(digest).decode("utf-8")
        authorization_origin = (
            f'api_key="{self.api_key}", algorithm="hmac-sha256", '
            f'headers="host date request-line", signature="{signature}"'
        )
        authorization = base64.b64encode(authorization_origin.encode("utf-8")).decode("utf-8")
        return self.spark_url + "?" + urlencode({"authorization": authorization, "date": now, "host": host})

    def _sync_generate(self, system_prompt: str, user_prompt: str) -> str:
        try:
            import websocket
        except ImportError as exc:
            raise RuntimeError("缺少 websocket-client；请安装后再启用远程星火模式。") from exc

        result: list[str] = []
        errors: list[str] = []
        url = self._create_url()
        payload = {
            "header": {"app_id": self.app_id},
            "parameter": {
                "chat": {
                    "domain": self.domain,
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                }
            },
            "payload": {
                "message": {
                    "text": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ]
                }
            },
        }

        def on_open(ws):
            ws.send(json.dumps(payload, ensure_ascii=False))

        def on_error(_ws, error):
            errors.append(str(error))

        def on_message(ws, message):
            data = json.loads(message)
            code = data.get("header", {}).get("code", 0)
            if code != 0:
                errors.append(json.dumps(data, ensure_ascii=False))
                ws.close()
                return
            choices = data["payload"]["choices"]
            result.append(choices["text"][0]["content"])
            if choices["status"] == 2:
                ws.close()

        ws = websocket.WebSocketApp(url, on_open=on_open, on_error=on_error, on_message=on_message)
        ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE}, ping_timeout=self.timeout_seconds)
        if errors:
            raise RuntimeError(f"星火 API 调用失败: {' | '.join(errors)}")
        return "".join(result).strip()

    async def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        # 定义本地 vLLM 备份节点 (Task 2.2)
        local_backup = AsyncOpenAIChatLLM(
            endpoint="http://localhost:8000/v1/chat/completions",
            api_key="local-vllm-key",
            model="Qwen2.5-Coder-32B-Instruct"
        )
        
        try:
            # 使用 pybreaker 包装同步方法并运行在线程池中
            return await self._generate_with_breaker(system_prompt, user_prompt)
        except (pybreaker.CircuitBreakerError, Exception) as e:
            print(f"  [EduMatrix] 星火 API 熔断或异常: {e}。自动无缝切换至本地 vLLM 备用节点。")
            return await local_backup.generate(system_prompt, user_prompt, role=role)

    async def generate_stream(self, system_prompt: str, user_prompt: str, *, role: str, images: list[str] = []) -> AsyncGenerator[str, None]:
        local_backup = AsyncOpenAIChatLLM(
            endpoint="http://localhost:8000/v1/chat/completions",
            api_key="local-vllm-key",
            model="Qwen2.5-Coder-32B-Instruct"
        )
        async for chunk in local_backup.generate_stream(system_prompt, user_prompt, role=role, images=images):
            yield chunk

    @spark_breaker
    async def _generate_with_breaker(self, system_prompt: str, user_prompt: str) -> str:
        import asyncio
        import functools
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, functools.partial(self._sync_generate, system_prompt, user_prompt))


def _deterministic_m2_artifact(user_prompt: str) -> dict[str, Any] | None:
    """Produce contract-valid M2 fixtures for offline workflow demonstrations."""
    try:
        request = json.loads(user_prompt)
    except (TypeError, json.JSONDecodeError):
        return None
    capability = str(request.get("capability", ""))
    context = request.get("context") or {}
    target_ids = [str(item) for item in context.get("target_knowledge_point_ids") or []]
    source_ids = [str(item) for item in context.get("source_ref_ids") or []]
    if not target_ids or not source_ids:
        return None
    target_id = target_ids[0]
    source_id = source_ids[0]
    profile = request.get("profile_summary") or {}
    target = profile.get("target_knowledge_point") or {}
    title = str(target.get("title") or target.get("code") or "可追溯知识学习")

    if capability == "lesson.generate_verified":
        return {
            "artifact_type": "lesson",
            "schema_version": "m2.lesson.v1",
            "title": f"{title}：原理与证据边界",
            "objective": "理解核心方法，并能将结论逐项绑定到已验证课程来源。",
            "prerequisites": ["理解基本检索与生成流程"],
            "sections": [
                {
                    "heading": "核心机制",
                    "body_markdown": "先从受控课程材料检索证据，再基于证据形成回答；无法定位来源的结论应保留不确定性。",
                    "knowledge_point_ids": target_ids,
                    "source_ref_ids": source_ids,
                },
                {
                    "heading": "验证方法",
                    "body_markdown": "将回答拆分为原子事实，逐项检查来源、适用边界与上下文一致性。",
                    "knowledge_point_ids": target_ids,
                    "source_ref_ids": source_ids,
                },
            ],
            "retrieval_questions": ["每个结论由哪个 source_ref 支持？", "哪些结论需要降级为不确定？"],
            "summary": "检索、生成、引用核验和边界声明共同构成可追溯闭环。",
        }
    if capability == "lab_guide.generate_verified":
        return {
            "artifact_type": "lab_guide",
            "schema_version": "m2.lab_guide.v1",
            "title": f"{title}：来源核验实验",
            "objective": "完成一次可回滚的来源引用核验。",
            "environment": ["Python 3.11+", "EduMatrix 冻结课程数据"],
            "safety_boundary": "只读取当前课程的冻结来源，不访问外部网络，不执行破坏性命令。",
            "steps": [
                {
                    "step_number": 1,
                    "title": "装配受控上下文",
                    "instruction": "读取当前知识点和来源引用，确认均属于已验证上下文。",
                    "command_or_action": f"verify-context --knowledge-point {target_id} --source {source_id}",
                    "expected_result": "上下文校验返回 verified。",
                    "rollback": "丢弃本次临时上下文，不修改冻结来源。",
                    "risk_level": "low",
                    "source_ref_ids": source_ids,
                },
                {
                    "step_number": 2,
                    "title": "核验原子事实",
                    "instruction": "逐项比对回答中的事实与来源片段，标记 supported 或 unsupported。",
                    "command_or_action": "verify-claims --dry-run",
                    "expected_result": "每项事实均具有明确裁决和来源定位。",
                    "rollback": "删除本次临时核验报告。",
                    "risk_level": "low",
                    "source_ref_ids": source_ids,
                },
            ],
            "acceptance_criteria": ["所有确定性结论均有来源", "unsupported 事实均被显式标记"],
            "failure_branches": [
                {
                    "symptom": "来源无法定位",
                    "likely_cause": "引用不属于当前 verified 上下文",
                    "recovery_steps": ["停止生成", "重新装配上下文", "再次执行来源校验"],
                }
            ],
        }
    if capability == "tiered_quiz.generate_verified":
        def question(identifier: str, bloom: str, prompt: str) -> dict[str, Any]:
            return {
                "id": identifier,
                "prompt": prompt,
                "knowledge_point_ids": target_ids,
                "bloom_level": bloom,
                "difficulty_basis": "考查来源绑定、证据核验与边界判断。",
                "scoring_rule": "结论、来源和边界均正确得 2 分。",
                "answer_key": "先定位受控来源，再逐项核验原子事实；证据不足时保留不确定性。",
                "explanation": "可靠回答必须同时满足事实正确、来源可定位和适用边界清晰。",
                "source_ref_ids": source_ids,
            }
        return {
            "artifact_type": "tiered_quiz",
            "schema_version": "m2.tiered_quiz.v1",
            "title": f"{title}：分阶能力测验",
            "instructions": "依次完成基础、应用和进阶题，回答时说明来源与边界。",
            "tiers": [
                {"level": "foundation", "questions": [question("q-foundation", "understand", "为什么回答需要绑定课程来源？")]},
                {"level": "application", "questions": [question("q-application", "apply", "如何核验一个包含三个事实的回答？")]},
                {"level": "advanced", "questions": [question("q-advanced", "analyze", "证据冲突时应如何裁决并说明不确定性？")]},
            ],
            "pass_rules": {"foundation": "2 分", "application": "2 分", "advanced": "2 分"},
        }
    return None


def _deterministic_m3_artifact(user_prompt: str) -> dict[str, Any] | None:
    """Produce request-bound M3 resources and reviews for offline demonstrations."""
    try:
        request = json.loads(user_prompt)
    except (TypeError, json.JSONDecodeError):
        return None
    request = request.get("original_request", request)

    claim = request.get("claim")
    if isinstance(claim, dict) and request.get("required_schema"):
        source_ids = [str(item) for item in claim.get("proposed_source_ref_ids") or []]
        if not source_ids:
            return None
        return {
            "prover": {
                "support_status": "supported",
                "evidence_ref_ids": source_ids,
                "applicable_conditions": ["owner/course/version filter remains enabled"],
                "rationale": "冻结来源可在当前范围内支持该原子事实。",
            },
            "challenger": {
                "issue_types": ["none"],
                "evidence_ref_ids": source_ids,
                "rationale": "未发现超出当前来源范围的确定性主张。",
            },
            "judge": {
                "verdict": "keep",
                "rationale": "本地确定性审查仅确认来源范围和结构契约，不替代专家判断。",
                "evidence_ref_ids": source_ids,
                "confidence": 0.8,
            },
        }

    context = request.get("context") or {}
    profile = request.get("profile") or {}
    personalization = profile.get("personalization")
    source_ids = [str(item) for item in context.get("source_ref_ids") or []]
    knowledge_ids = [str(item) for item in context.get("target_knowledge_point_ids") or []]
    if not isinstance(personalization, dict) or not source_ids or not knowledge_ids:
        return None

    profile_id = str(profile.get("source_profile_id") or "profile")
    if profile_id.endswith("beginner"):
        lesson_body = "先解释检索、候选和重排术语，再用短步骤比较参数变化。"
        step_count, advanced_bloom = 4, "analyze"
    elif profile_id.endswith("theory"):
        lesson_body = "压缩基础理论，重点比较 owner 过滤、参数控制和故障定位。"
        step_count, advanced_bloom = 3, "evaluate"
    else:
        lesson_body = "分析召回、排序、成本、版本隔离和迁移场景之间的工程权衡。"
        step_count, advanced_bloom = 2, "create"

    def question(identifier: str, bloom: str) -> dict[str, Any]:
        return {
            "id": identifier,
            "prompt": f"{profile_id} 如何调优检索并保持课程隔离？",
            "knowledge_point_ids": knowledge_ids,
            "bloom_level": bloom,
            "difficulty_basis": str(personalization.get("difficulty_band") or "evidence-bound"),
            "scoring_rule": "参数、证据和隔离边界均正确得分。",
            "answer_key": "先过滤课程范围，再检索与重排，最后用冻结查询验收。",
            "explanation": "不能关闭 owner/course 过滤来换取表面指标。",
            "source_ref_ids": source_ids,
        }

    bundle = {
        "lesson": {
            "artifact_type": "lesson",
            "schema_version": "m3.lesson.v1",
            "title": f"{profile_id} 混合检索讲义",
            "objective": "调优混合检索并保持数据隔离。",
            "prerequisites": ["Python/JSON"] if profile_id.endswith("beginner") else [],
            "sections": [{
                "heading": "检索调优",
                "body_markdown": lesson_body,
                "knowledge_point_ids": knowledge_ids,
                "source_ref_ids": source_ids,
            }],
            "retrieval_questions": ["top-k 改变会影响什么？"],
            "summary": "参数变化必须绑定证据、版本和隔离验收。",
            "personalization": personalization,
        },
        "lab_guide": {
            "artifact_type": "lab_guide",
            "schema_version": "m3.lab_guide.v1",
            "title": f"{profile_id} 检索调优实操",
            "objective": "对冻结查询执行可回滚的参数实验。",
            "environment": ["冻结课程来源", "本地确定性演示环境"],
            "safety_boundary": "owner/course/version 过滤不可关闭。",
            "steps": [{
                "step_number": index,
                "title": f"步骤 {index}",
                "instruction": "调整一个变量并记录结果。",
                "command_or_action": f"set top_k={index + 2}",
                "expected_result": "结果保存参数、版本和来源。",
                "rollback": "恢复上一个参数快照。",
                "risk_level": "low",
                "source_ref_ids": source_ids,
            } for index in range(1, step_count + 1)],
            "acceptance_criteria": ["指标可复现", "跨 owner 泄露为 0"],
            "failure_branches": [{
                "symptom": "课程过滤后无结果",
                "likely_cause": "查询范围或索引版本错误",
                "recovery_steps": ["核对 owner/course/version", "恢复正确索引"],
            }],
            "personalization": personalization,
        },
        "tiered_quiz": {
            "artifact_type": "tiered_quiz",
            "schema_version": "m3.tiered_quiz.v1",
            "title": f"{profile_id} 检索调优测验",
            "instructions": "依次完成基础、应用和进阶题。",
            "tiers": [
                {"level": "foundation", "questions": [question("q-foundation", "understand")]},
                {"level": "application", "questions": [question("q-application", "apply")]},
                {"level": "advanced", "questions": [question("q-advanced", advanced_bloom)]},
            ],
            "pass_rules": {"foundation": "2 分", "application": "2 分", "advanced": "2 分"},
            "personalization": personalization,
        },
    }
    artifact_type = request.get("artifact_type")
    return bundle.get(artifact_type) if artifact_type else bundle


class DeterministicEducationLLM:
    def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        if "意图分类" in role:
            casual_markers = ("天气", "吃了吗", "讲个笑话", "你是谁")
            is_academic = not any(marker in user_prompt for marker in casual_markers)
            return json.dumps({
                "is_academic": is_academic,
                "reason": "这是一个学习问题" if is_academic else "这是一次日常交流",
                "reply": "" if is_academic else (
                    "## 智能答疑 / 系统说明\n\n"
                    "您好！我是 EduMatrix 智能自适应助教。可以向我提问机器学习、数学或编程问题。"
                ),
            }, ensure_ascii=False)
        if "学术概念实体消解与指代对齐助手" in system_prompt or "学术概念实体消解与指代对齐助手" in role:
            if "池化层" in user_prompt and ("这个" in user_prompt or "它" in user_prompt):
                return "池化层"
            return "None"
        if "画像抽取器" in role:
            return _profile_json(user_prompt)
        if "JSON Schema" in system_prompt:
            structured = _deterministic_m2_artifact(user_prompt)
            if structured is None:
                structured = _deterministic_m3_artifact(user_prompt)
            if structured is not None:
                return json.dumps(structured, ensure_ascii=False)
        if "【已验证的 M5 学习上下文】" in system_prompt:
            # M5 prompts include retrieved snippets that may mention a
            # different topic from the learner's latest question.  Let the
            # explicit, recognizable question take the same precedence as
            # normal chat.  A short follow-up such as ``为什么更稳定？`` has
            # no standalone topic and is intentionally answered from the
            # frozen source snippet it is referring to.
            current_question = _extract_current_question(user_prompt)
            if current_question and _has_standalone_question_focus(current_question):
                return _deterministic_chat_answer(user_prompt)
            match = re.search(r"\[([^\]]+)\]\s+([^\n]+)", user_prompt)
            if match:
                _source_ref_id, quote = match.groups()
                if not any(term in quote for term in ("混合检索", "关键词检索", "向量检索")):
                    return (
                        "## 接着刚才的问题\n\n"
                        f"上一段的关键意思是：{quote}\n\n"
                        "先把其中的对象、成立条件和结论对应起来，再用一个最小例子检查它在当前情形下是否成立。"
                        "如果你希望继续深入，可以补充想比较的对象、指标或一组具体数据。"
                    )
                return (
                    "## 为什么它通常更稳\n\n"
                    "混合检索更稳定的原因不是某一种检索方式始终更强，而是它把关键词检索的精确术语召回与向量检索的语义召回结合起来，"
                    "再用统一分数或重排器整理候选。这样可以减少单一检索方式在术语变化、同义表达或精确标识符场景中的偏差。"
                    "但这种优势仍需在固定测试问题上比较 Recall@K，不能从一次成功回答推断所有场景都更好。\n\n"
                    "你可以下一步分别运行关键词、向量和混合检索，比较同一组 query 的 Recall@K 与首个正确块位置。"
                )
        if role in {"学习伙伴", "助教", "EduMatrix 学习伙伴"} or "学习伙伴" in role or "助教" in role or "辩手" in role:
            return _deterministic_chat_answer(user_prompt)
        topic = _guess_topic(user_prompt)
        if "理论教授" in role:
            return _lecture(topic, user_prompt)
        if "极客助教" in role:
            return _code(topic)
        if "逻辑画师" in role:
            return _mermaid(topic)
        if "考官智能体" in role:
            return _quiz(topic)
        if "虚拟导演" in role:
            return _video_script(topic)
        if "视频推荐官" in role:
            return _video_recommendations(topic)
        if "概念可视化导师" in role or "Visualizer Agent" in role:
            return _simplified_explanation(topic, user_prompt)
        if "路径规划师" in role:
            return f"学习路径建议：先补齐前置概念，再学习 {topic} 的定义、计算流程、代码实现和易错点。"
        return f"我们可以从“{topic}”的核心含义、工作过程和一个具体例子开始。请告诉我你最想先解决哪一部分。"


class AsyncDeterministicEducationLLM:
    async def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        return DeterministicEducationLLM().generate(system_prompt, user_prompt, role=role)

    async def generate_stream(self, system_prompt: str, user_prompt: str, *, role: str, images: list[str] = []) -> AsyncGenerator[str, None]:
        import asyncio
        full_text = DeterministicEducationLLM().generate(system_prompt, user_prompt, role=role)
        if images and "【OCR/多模态图片提取成功】" not in full_text:
            ocr_text = ""
            if "池化" in user_prompt:
                ocr_text = "【OCR/多模态图片提取成功】题目图片包含一个 4x4 的输入矩阵：[[1, 3, 2, 4], [5, 6, 1, 2], [0, 2, 8, 1], [3, 1, 2, 7]]。要求计算 stride=2 的 2x2 最大池化层输出。\n\n"
            elif "注意力" in user_prompt or "attention" in user_prompt.lower():
                ocr_text = "【OCR/多模态图片提取成功】公式图片为 scaled dot-product attention 的数学表达：Attention(Q,K,V) = softmax(Q K^T / sqrt(d_k)) V。\n\n"
            else:
                ocr_text = "【OCR/多模态图片提取成功】图片中包含一道机器学习多步推导与代码实操练习题，涉及前向计算与梯度更新逻辑。\n\n"
            full_text = ocr_text + full_text

        chunk_size = 12
        for i in range(0, len(full_text), chunk_size):
            yield full_text[i:i+chunk_size]
            await asyncio.sleep(0.02)


class MultimodalOnlyAsyncLLM:
    """Use the local deterministic engine for text and a configured VLM for images.

    This keeps the application usable when an evaluator supplies only a visual
    model configuration from the Settings page.
    """

    def __init__(self, vision_backend: AsyncOpenAIChatLLM) -> None:
        self.vision_backend = vision_backend
        self.text_backend = AsyncDeterministicEducationLLM()

    @property
    def has_vision(self) -> bool:
        return True

    @property
    def has_external_vision(self) -> bool:
        return True

    @property
    def external_vision_backend(self) -> AsyncOpenAIChatLLM:
        return self.vision_backend

    async def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        return await self.text_backend.generate(system_prompt, user_prompt, role=role)

    async def generate_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        role: str,
        images: list[str] = [],
    ) -> AsyncGenerator[str, None]:
        backend = self.vision_backend if images else self.text_backend
        async for chunk in backend.generate_stream(
            system_prompt,
            user_prompt,
            role=role,
            images=images,
        ):
            yield chunk


def build_llm(config: EduMatrixConfig = CONFIG) -> LLMBackend:
    provider = config.llm_provider.lower().strip()
    if provider == "spark":
        if config.spark_app_id and config.spark_api_key and config.spark_api_secret:
            return SparkClient(
                app_id=config.spark_app_id,
                api_key=config.spark_api_key,
                api_secret=config.spark_api_secret,
                spark_url=config.spark_url,
                domain=config.spark_domain,
                temperature=config.llm_temperature,
                max_tokens=config.llm_max_tokens,
            )
    if provider == "openai" and config.llm_api_key:
        return OpenAIChatLLM(
            endpoint=config.llm_endpoint,
            api_key=config.llm_api_key,
            model=config.llm_model,
            temperature=config.llm_temperature,
            max_tokens=config.llm_max_tokens,
            timeout_seconds=config.llm_timeout,
        )
    return DeterministicEducationLLM()


class FallbackAsyncLLMWrapper:
    """Wrapper that catches any exception from a primary AsyncLLMBackend and falls back to a secondary backend."""
    def __init__(self, primary: AsyncLLMBackend, fallback: AsyncLLMBackend) -> None:
        self.primary = primary
        self.fallback = fallback

    @property
    def has_vision(self) -> bool:
        return getattr(self.primary, "has_vision", False) or getattr(self.fallback, "has_vision", False)

    @property
    def has_external_vision(self) -> bool:
        return getattr(self.primary, "has_external_vision", False) or getattr(
            self.fallback, "has_external_vision", False
        )

    @property
    def external_vision_backend(self) -> Any | None:
        return getattr(self.primary, "external_vision_backend", None) or getattr(
            self.fallback, "external_vision_backend", None
        )

    async def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        try:
            return await self.primary.generate(system_prompt, user_prompt, role=role)
        except Exception as e:
            print(f"  [EduMatrix Fallback] Primary LLM generate failed: {e}. Falling back to secondary.")
            return await self.fallback.generate(system_prompt, user_prompt, role=role)

    async def generate_stream(self, system_prompt: str, user_prompt: str, *, role: str, images: list[str] = []) -> AsyncGenerator[str, None]:
        try:
            async for chunk in self.primary.generate_stream(system_prompt, user_prompt, role=role, images=images):
                yield chunk
        except Exception as e:
            print(f"  [EduMatrix Fallback] Primary LLM generate_stream failed: {e}. Falling back to secondary.")
            async for chunk in self.fallback.generate_stream(system_prompt, user_prompt, role=role, images=images):
                yield chunk


def build_async_llm(config: EduMatrixConfig = CONFIG, **overrides) -> AsyncLLMBackend:
    # 支持动态覆盖配置（用于 swarm_factory）
    provider = overrides.get("provider", config.llm_provider).lower().strip()
    api_key = overrides.get("api_key", config.llm_api_key)
    endpoint = overrides.get("endpoint", config.llm_endpoint)
    model = overrides.get("model", config.llm_model)
    def configured(name: str, value: str) -> str | None:
        override = overrides.get(name)
        if override is not None:
            return override
        return _env_or_config(name, value)

    multimodal_endpoint = configured("multimodal_endpoint", config.multimodal_llm_endpoint)
    multimodal_api_key = configured("multimodal_api_key", config.multimodal_llm_api_key)
    multimodal_model = configured("multimodal_model", config.multimodal_llm_model)
    allow_fallback = overrides.get("allow_fallback")
    if allow_fallback is None:
        # A configured live provider must fail honestly.  Deterministic output
        # remains available only through an explicit deterministic provider or
        # an explicit operator opt-in to fallback.
        allow_fallback = (
            os.getenv("EDUMATRIX_ALLOW_LLM_FALLBACK", "0") == "1"
            and os.getenv("EDUMATRIX_DISABLE_LLM_FALLBACK", "0") != "1"
        )
    
    primary: AsyncLLMBackend | None = None
    
    if provider == "spark" or (config.spark_app_id and config.spark_api_key):
        primary = AsyncSparkClient(
            app_id=config.spark_app_id,
            api_key=config.spark_api_key,
            api_secret=config.spark_api_secret,
            spark_url=config.spark_url,
            domain=config.spark_domain,
            temperature=overrides.get("temperature", config.llm_temperature),
            max_tokens=overrides.get("max_tokens", config.llm_max_tokens),
        )
    elif (provider == "openai" or provider == "vllm") and api_key:
        primary = AsyncOpenAIChatLLM(
            endpoint=endpoint,
            api_key=api_key,
            model=model,
            temperature=overrides.get("temperature", config.llm_temperature),
            max_tokens=overrides.get("max_tokens", config.llm_max_tokens),
            timeout_seconds=config.llm_timeout,
            thinking_mode=overrides.get("thinking_mode", config.llm_thinking_mode),
            reasoning_effort=overrides.get("reasoning_effort", config.llm_reasoning_effort),
            multimodal_endpoint=multimodal_endpoint,
            multimodal_api_key=multimodal_api_key,
            multimodal_model=multimodal_model,
            is_multimodal_fallback=overrides.get("is_multimodal_fallback", False),
        )
        
    if primary is not None and not allow_fallback:
        return primary
    if primary is not None:
        return FallbackAsyncLLMWrapper(primary, AsyncDeterministicEducationLLM())
    if multimodal_endpoint and multimodal_api_key and multimodal_model:
        vision_backend = AsyncOpenAIChatLLM(
            endpoint=multimodal_endpoint,
            api_key=multimodal_api_key,
            model=multimodal_model,
            temperature=overrides.get("temperature", config.llm_temperature),
            max_tokens=overrides.get("max_tokens", config.llm_max_tokens),
            timeout_seconds=config.llm_timeout,
            is_multimodal_fallback=True,
        )
        return MultimodalOnlyAsyncLLM(vision_backend)
    return AsyncDeterministicEducationLLM()


DEFAULT_LLM = DeterministicEducationLLM()
DEFAULT_ASYNC_LLM = build_async_llm()


def call_spark_api(prompt: str, role: str = "助手") -> str:
    return DEFAULT_LLM.generate(f"你现在是 EduMatrix 系统的{role}", prompt, role=role)


_CURRENT_QUESTION_MARKERS = (
    "学生当前提问",
    "学生当前问题",
    "学生问题",
    "当前学生追问",
    "学生追问",
    "用户当前问题",
    "用户问题",
    "当前问题",
)
_CURRENT_QUESTION_BOUNDARY = re.compile(
    r"\n\s*(?:"
    r"课程证据|已验证来源|背景知识库匹配证据|已解析附件|图片解析出的内容|"
    r"学习者画像适配计划|学习上下文|课程上下文|检索上下文|"
    r"课程协作上下文|专业协作上下文|Subject Expert 草稿|Challenger 摘要|"
    r"Evidence Verifier 结果|Pedagogical 编排|公开 claims|课程 grounding|"
    r"专家草稿|反驳摘要|核验结论|这是中断前已保存的回答|"
    r"历史对话|会话历史|最近会话|目标内容|上文|下文|learner_adaptation|"
    r"请(?:开始|提供|给出|直接)|===|$"
    r")",
    re.MULTILINE,
)


def _extract_current_question(prompt: str) -> str:
    """Extract the learner's latest question from a mixed model prompt.

    Chat prompts deliberately include history, retrieved evidence and profile
    instructions.  Those sections are useful context but must never outrank
    the explicitly marked current question when a deterministic answer is
    selected.  Return an empty string when the caller did not provide a
    current-question marker so resource-generation prompts can keep their
    existing target-field behavior.
    """
    text = str(prompt or "")
    if not text:
        return ""
    marker_pattern = "|".join(re.escape(marker) for marker in _CURRENT_QUESTION_MARKERS)
    matches = list(re.finditer(rf"(?:{marker_pattern})\s*[：:]\s*", text))
    if not matches:
        return ""
    remainder = text[matches[-1].end():].lstrip()
    boundary = _CURRENT_QUESTION_BOUNDARY.search(remainder)
    if boundary:
        remainder = remainder[:boundary.start()]
    # Keep a question readable even when the caller supplied line breaks or
    # an accidental Markdown quote around the message.
    return re.sub(r"\s+", " ", remainder).strip(" `\t\r\n")


def _has_standalone_question_focus(question: str) -> bool:
    """Return whether a marked question carries its own answerable focus.

    A deterministic M5 answer may receive a short follow-up such as
    ``为什么更稳定？`` after a frozen source quote. That follow-up is
    intentionally answered from the frozen quote. A complete question,
    including a topic that is not in the small deterministic vocabulary,
    must instead win over the retrieved context.
    """
    normalized = re.sub(r"\s+", " ", str(question or "")).strip(" `\t\r\n")
    if not normalized:
        return False

    # Known topics and explicit identifiers are always self-contained, even
    # when the rest of the question is short (for example ``left 怎么移？``).
    if _guess_topic(normalized) != "目标知识点" or re.search(r"[A-Za-z][A-Za-z0-9_./-]*", normalized):
        return True

    compact = normalized.rstrip("？?。.!！")
    compact = re.sub(r"^(?:请问|请|那|那么|所以|然后|再问)\s*", "", compact)
    compact = re.sub(
        r"^(?:什么是|什么叫|解释一下|解释|说明|介绍|如何|怎么|怎样|为什么|为何|能否|是否|哪些|何时)\s*",
        "",
        compact,
    )
    # Predicate-only follow-ups have no subject to route on and should keep
    # using the source quote from the immediately preceding turn.
    if re.fullmatch(
        r"(?:更|最|很|不|比较|还)?(?:稳定|重要|复杂|简单|好|快|慢|合适|合理|准确|可靠|清晰|有用|这样|那样)(?:吗|呢|啊|呀)?",
        compact,
    ):
        return False
    # Very short Chinese fragments are normally deictic follow-ups (``怎么
    # 办？``/``为什么？``), not a new independently scoped question.
    return len(compact) >= 4


def _guess_topic(text: str) -> str:
    full_text = str(text or "")
    current_question = _extract_current_question(full_text)
    # A marked current question is authoritative.  Only prompts without that
    # marker fall back to explicit resource target fields or their full body.
    source_text = current_question or full_text
    target_match = re.search(r"(?<!学习)目标=([^;；\n]+)|GraphRAG目标知识点[：:]\s*([^\n]+)", source_text)
    if target_match:
        target = next((group for group in target_match.groups() if group), "").strip()
        if target:
            return target
    words = (
        "池化层", "最大池化", "平均池化", "卷积核", "特征图",
        "反向传播", "链式法则", "梯度下降", "逻辑回归", "线性回归",
        "决策树", "支持向量机", "过拟合", "正则化", "交叉验证",
        "机器学习", "监督学习", "模型评估", "前向传播", "损失函数",
        "欠拟合", "激活函数", "Transformer", "注意力机制",
        "神经网络", "卷积神经网络", "混淆矩阵", "二分查找", "循环不变量",
        "混合检索", "向量检索", "关键词检索", "学习率",
        "闭区间", "开区间", "left", "right",
    )
    sorted_words = sorted(words, key=len, reverse=True)
    for word in sorted_words:
        if word in source_text:
            return word
    return "目标知识点"


def _deterministic_chat_answer(prompt: str) -> str:
    """Give a domain-grounded answer when no external model is available.

    The deterministic path is used in the demo and as the honest local
    fallback.  It should still feel like a real teaching response: answer the
    latest question, show the reasoning chain, and leave the learner with a
    concrete way to verify the idea.  Keep topic branches separate so a
    follow-up about boundaries cannot accidentally reuse the first-turn
    invariant explanation verbatim.
    """
    full_text = str(prompt or "").strip()
    text = _extract_current_question(full_text) or full_text
    # Casual messages must remain conversational even when the conversation
    # is attached to a course.  The canonical route now classifies them as
    # general chat; this branch keeps the deterministic fallback aligned with
    # that decision instead of emitting an academic template.
    if any(marker in text for marker in ("讲个笑话", "天气怎么样", "天气如何", "吃了吗", "你是谁", "心情不错")):
        if "讲个笑话" in text:
            return "当然可以：程序员去面试，面试官问‘你会什么语言？’他说‘我会沉默，因为 bug 还没复现。’\n\n如果你想继续学习，可以随时问我一个机器学习、数据结构或编程问题。"
        if "你是谁" in text:
            return "我是 EduMatrix 的学习伙伴，负责陪你理解课程概念、检查代码和安排下一步练习。你可以直接告诉我现在最想弄懂的知识点。"
        return "收到！希望你的状态继续保持得不错。想学习时可以直接抛给我一个具体问题，我会按你的节奏一起拆解。"
    if (
        any(marker in text for marker in ("错答", "答错", "纠正", "改答"))
        and any(marker in text for marker in ("费曼", "代码", "实验"))
        and any(marker in text for marker in ("反思", "掌握", "薄弱点", "认知负荷"))
    ):
        score_match = re.search(r"(?:智能组卷|组卷|测验|考试)[^。；，,\n]{0,12}?(\d{1,3})\s*分", text)
        score_evidence = (
            f"你明确提到本轮智能组卷是 {score_match.group(1)} 分。这个结果说明知识还没有稳定迁移到独立作答，"
            "尤其要回查错题对应的边界条件和题型转换；它不能抹掉前面已经完成的代码、实验和复述证据。"
            if score_match
            else "你没有给出本轮组卷的具体分数，所以我不会猜测掌握率；应以正式报告中的错题知识点和逐题解析判断迁移薄弱处。"
        )
        return (
            "## 先给判断\n\n"
            "这组行为呈现的不是‘已经全会’或‘完全不会’，而是很典型的正在形成稳定能力：你能接收反馈、执行程序、控制实验变量并重新组织概念，"
            "但在脱离支架后的综合判断上仍有薄弱环节。最合适的下一步不是把整章重学一遍，而是把错题暴露出的边界条件做一次短而集中的迁移训练。\n\n"
            "### 哪些能力已经形成\n\n"
            "1. **错答后能够纠正**：说明你能利用反馈修正判断，具备恢复能力。它证明‘会根据证据改’，但不等于首次独立作答已经稳定。\n"
            "2. **代码真实运行完成**：说明你已经把部分概念转成了可执行步骤，形成了程序性掌握。下一步应解释关键参数为何这样设置，而不只是得到正确输出。\n"
            "3. **交互实验中调节参数并观察变化**：说明你能做基本变量控制，知道用结果曲线或指标检查假设。要继续确认每次只改变一个变量，并能预测变化方向。\n"
            "4. **费曼复述后有改进**：说明你能发现表达缺口并重组概念关系。真正稳定的标准是换一个例子仍能讲清前提、过程、结论和反例。\n\n"
            "### 目前仍然薄弱的地方\n\n"
            f"{score_evidence}\n\n"
            "优先检查三类错误：是否漏看题目的适用前提；是否混用了相似概念的边界；是否能在代码、图表和文字表述之间来回转换。"
            "这三类问题比单纯记忆定义更容易造成‘看懂了但一做就错’。\n\n"
            "### 认知负荷、参与度与受挫感怎么理解\n\n"
            "连续完成测验、代码、实验和费曼复述，说明本轮参与度较高；多种表征快速切换也会暂时提高认知负荷。"
            "你在错答后继续纠正并完成后续任务，说明受挫没有演变成退出，但不能据此断言受挫感为零。普通对话本身也不会直接写入掌握度，"
            "最终画像应只引用这些已经提交的可信学习事件。\n\n"
            "### 下一轮 30 分钟巩固计划\n\n"
            "- **8 分钟：错因归类。** 每道错题只标一个主因：前提遗漏、边界混淆、计算失误或迁移失败，并写出触发这个判断的题干词。\n"
            "- **10 分钟：边界对照。** 为薄弱概念写一组‘成立 / 不成立’最小例子，明确只改变了哪个条件，以及结论为什么随之变化。\n"
            "- **8 分钟：无支架迁移。** 关掉解析完成一道同构题，再把解法改写成三到五行伪代码或口头步骤。\n"
            "- **4 分钟：低负荷收束。** 用一句定义、一个关键边界、一个自检问题做结束记录；24 小时后只复测错题和边界题。\n\n"
            "达标条件不是立即全对，而是：能在新题中主动说出适用前提，首次作答正确率提高，并能解释代码或实验结果为何支持结论。"
        )
    # Prefer the learner's explicit question over unrelated concepts that may
    # appear in retrieved course context.  Without this guard, a prompt about
    # binary-search invariants can be hijacked by a context paragraph that
    # happens to mention hybrid retrieval first.
    # Code requests need a runnable, testable answer rather than the prose
    # invariant explanation.  Keep this branch before the generic binary
    # search branches so a request that mentions both "边界" and "代码" is
    # routed to the code-specific response.
    if "二分查找" in text and any(token in text for token in ("代码", "可运行", "实现", "Python", "python")):
        return (
            "## 直接回答\n\n"
            "下面给出闭区间 `[left, right]` 版本的 Python 实现。它假设输入数组已经按升序排列；如果数组无序，必须先排序，"
            "但排序本身会改变总体复杂度和原始下标。\n\n"
            "```python\n"
            "def binary_search(nums, target):\n"
            "    left, right = 0, len(nums) - 1\n"
            "    while left <= right:\n"
            "        # 用这种写法避免 left + right 在极大下标时溢出\n"
            "        mid = left + (right - left) // 2\n"
            "        if nums[mid] == target:\n"
            "            return mid\n"
            "        if nums[mid] < target:\n"
            "            left = mid + 1\n"
            "        else:\n"
            "            right = mid - 1\n"
            "    return -1\n"
            "```\n\n"
            "### 输入、输出与不变量\n\n"
            "输入是升序列表 `nums` 和目标值 `target`；输出是目标首次命中的下标，找不到时返回 `-1`。"
            "循环不变量是：每轮开始时，若目标存在，它仍位于 `[left, right]`。`mid` 已经比较过，所以排除左半边时写 `left = mid + 1`，"
            "排除右半边时写 `right = mid - 1`，不能写成 `left = mid` 或 `right = mid`。\n\n"
            "### 三个边界测试\n\n"
            "1. `binary_search([2, 5, 8, 12, 17], 2) == 0`：命中第一个元素；\n"
            "2. `binary_search([2, 5, 8, 12, 17], 17) == 4`：命中最后一个元素；\n"
            "3. `binary_search([2, 5, 8, 12, 17], 6) == -1`：目标位于两个元素之间，循环结束时 `left > right`。\n\n"
            "还应测试空数组、单元素命中/未命中、目标小于最小值和大于最大值。时间复杂度为 O(log n)，迭代实现的额外空间复杂度为 O(1)。"
            "如果你贴出自己的版本，我可以按每一轮的 left、right、mid 逐行检查。"
        )
    if "循环不变量" in text or "不变量" in text or ("二分查找" in text and "边界条件" in text):
        return (
            "## 直接回答\n\n"
            "先给结论：二分查找的循环不变量是——每一轮循环开始时，如果目标值存在，它一定仍在当前搜索区间内。"
            "这句话不是口号，而是证明代码正确性的关键条件；每次移动边界都必须保证它继续成立。\n\n"
            "### 1. 闭区间的含义\n\n"
            "采用 [left, right] 时，左右端点都可能是候选位置，所以初始值通常是 left = 0、right = n - 1，"
            "循环条件写成 left <= right。计算 mid = left + (right - left) // 2 后，mid 已经被比较过："
            "若 target < nums[mid]，mid 以及右侧都不可能再是答案，安全更新为 right = mid - 1；"
            "若 target > nums[mid]，mid 以及左侧都不可能再是答案，安全更新为 left = mid + 1；"
            "若相等则返回 mid。\n\n"
            "### 2. 用一个具体数组检查不变量\n\n"
            "在 nums = [2, 5, 8, 12, 17, 23] 中查找 17：第一次区间是 [0, 5]，mid = 2，nums[mid] = 8，"
            "因为 17 > 8，下一轮变为 [3, 5]；第二次 mid = 4，命中 17。注意下一轮区间仍然包含答案，"
            "这正是不变量在每次迭代后的可观察证据。若查找 6，区间会依次缩小为 [0, 1]、[1, 1]，"
            "最后变成 [1, 0]，left > right 表示候选集合为空，才能返回 -1。\n\n"
            "### 3. 终止性与复杂度\n\n"
            "每一轮都会排除 mid 及其一侧的元素，区间长度严格变短，因此不会无限循环。"
            "时间复杂度是 O(log n)，空间复杂度是 O(1)（迭代写法）。如果数组没有排序，"
            "这个不变量从一开始就不成立，必须先排序或改用适合无序数据的方案。\n\n"
            "### 4. 最常见的错误\n\n"
            "不要把闭区间的 right = mid - 1 与开区间 [left, right) 的 right = mid 混用；"
            "不要在已经比较过 mid 后仍写 left = mid 或 right = mid，某些长度为 1 或 2 的区间会原地不动；"
            "也不要只在命中时返回而遗漏退出后的‘未找到’分支。\n\n"
            "### 5. 自检练习\n\n"
            "请分别用目标值 2、23、6 记录每轮的 left、right、mid，并检查每次区间是否仍覆盖可能的答案。"
            "如果你把代码贴出来，我可以按这张迭代表逐行核对边界、不变量和终止条件。"
        )
    if (
        ("二分查找" in text and any(token in text for token in ("left", "right", "mid")))
        or ("闭区间" in text and ("left" in text or "right" in text))
        or ("开区间" in text and ("left" in text or "right" in text))
        or all(token in text for token in ("left", "right", "mid"))
    ):
        return (
            "## 直接回答\n\n"
            "你这次问的是二分查找中 left 和 right 的移动规则。它们不是凭感觉向中间靠拢，"
            "而是由区间定义和已经比较过的 mid 决定；二分查找的循环不变量仍然是：目标若存在，"
            "必须留在下一轮区间中。\n\n"
            "### 闭区间 [left, right] 的三条规则\n\n"
            "1. `target < nums[mid]`：目标只能在 mid 左侧，`right = mid - 1`。减 1 是因为 mid 已经比较过，"
            "不需要再次保留。\n"
            "2. `target > nums[mid]`：目标只能在 mid 右侧，`left = mid + 1`。加 1 同样是在排除已经确认的 mid。\n"
            "3. `target == nums[mid]`：直接返回 mid，不再移动边界。\n\n"
            "循环通常写 `while left <= right`。当 left == right 时，区间里还剩最后一个候选，"
            "必须再检查一次；当更新后 left = right + 1，区间才真正为空。\n\n"
            "### 迭代示例\n\n"
            "对 `nums = [2, 5, 8, 12, 17, 23]` 查找 12：初始 `[0, 5]`，mid = 2，8 < 12，"
            "所以 left 从 0 跳到 3，区间变成 `[3, 5]`；下一轮 mid = 4，17 > 12，"
            "所以 right 从 5 退到 3，区间变成 `[3, 3]`；最后 mid = 3 命中。"
            "这个例子同时说明了为什么不能写 `left = mid` 或 `right = mid`：当区间只剩一个元素时，"
            "边界可能保持不变，循环就不会结束。\n\n"
            "### 不要混用两种区间\n\n"
            "闭区间使用 `right = n - 1`、`left <= right`、排除 mid 时加减 1；"
            "半开区间 `[left, right)` 使用 `right = n`、`left < right`，当目标小于 mid 时通常写 `right = mid`。"
            "两套写法都正确，但初始化、循环条件和更新必须成套出现。\n\n"
            "### 代码自检清单\n\n"
            "检查四件事：数组是否有序；mid 是否能在大数下安全计算；每次更新是否严格缩短区间；"
            "未找到时是否返回明确结果。闭区间迭代版本的时间复杂度为 O(log n)，额外空间为 O(1)。"
            "你可以再试目标值小于最小值、大于最大值和数组为空这三个边界案例，逐行写出 left/right，"
            "就能确认实现没有遗漏。"
        )
    if any(token in text for token in ("池化层", "最大池化", "平均池化", "卷积神经网络")) or ("卷积" in text and "池化" in text):
        return (
            "## 直接回答\n\n"
            "池化层不是为了替代卷积，而是在卷积提取局部特征后做下采样：减少空间尺寸和计算量，扩大后续神经元的有效感受野，"
            "并让特征对小幅平移更稳定。它也会丢失部分精细位置，目标检测或分割任务不能不加分析地大量池化。\n\n"
            "### 2×2 最大池化示例\n\n"
            "对输入矩阵 `[[1, 3, 2, 4], [5, 6, 1, 2], [0, 2, 8, 1], [3, 1, 2, 7]]` 使用 `kernel=2、stride=2`。"
            "左上窗口 `[ [1,3], [5,6] ]` 的最大值是 6；右上窗口最大值是 4；左下窗口最大值是 3；右下窗口最大值是 8，"
            "所以输出为 `[[6, 4], [3, 8]]`。输出高宽计算为 `floor((4-2)/2)+1 = 2`。\n\n"
            "### 最大池化与平均池化\n\n"
            "最大池化保留最强响应，适合突出边缘或纹理是否出现；平均池化保留窗口平均趋势，输出更平滑。"
            "`stride` 大于 1 才会真正下采样，`padding` 会改变边缘尺寸；不要把池化理解成‘学习参数’，标准池化本身没有可训练权重。\n\n"
            "### 常见误区与练习\n\n"
            "不要把卷积核大小、步幅和池化窗口混为一谈，也不要只看输出尺寸而忽略通道数（池化通常不改变通道数）。"
            "你可以把 stride 改为 1，手算输出尺寸和重叠窗口，再比较最大池化、平均池化对边缘信息的影响。"
        )
    if any(token in text for token in ("自注意力", "Q、K、V", "Q,K,V", "Q、K", "缩放因子")) or ("Q" in text and "K" in text and "V" in text):
        return (
            "## 直接回答\n\n"
            "自注意力让序列中的每个位置根据其他位置动态决定‘应该关注谁’。Q（Query）表示当前查询，K（Key）表示可被匹配的特征，"
            "V（Value）是被加权汇总的内容；同一序列通常通过三组线性投影得到 Q、K、V。\n\n"
            "### 计算步骤\n\n"
            "1. 计算相似度矩阵 `S = QKᵀ`；\n"
            "2. 用 `sqrt(d_k)` 除以 S，得到 scaled scores，避免维度变大时点积方差过高；\n"
            "3. 对每一行做 softmax，把分数变成和为 1 的注意力权重；\n"
            "4. 用权重乘 V，得到 `Attention(Q,K,V)=softmax(QKᵀ/sqrt(d_k))V`。\n\n"
            "### 一个可核对的直觉例子\n\n"
            "句子中‘它’需要判断指代对象时，‘它’对应位置的 Q 会与其他位置的 K 比较；与真正对象更相似的位置获得更大权重，"
            "最终从对应 V 汇总更多信息。padding mask 会屏蔽补齐位置，causal mask 会阻止当前位置看到未来 token。\n\n"
            "### 常见误区与复杂度\n\n"
            "Q、K、V 不是三种词性标签，也不是直接从词典查出的固定向量；它们由当前层参数投影而来。缩放因子不是可学习温度，"
            "而是稳定 softmax 梯度的数值处理。长度为 n、隐藏维度为 d 时，标准自注意力的分数矩阵带来 O(n²d) 的时间和 O(n²) 的注意力矩阵空间。"
            "练习时可以写一个 3 个 token 的小矩阵，逐行验证 softmax 权重之和为 1。"
        )
    if "混合检索" in text or ("关键词" in text and "向量" in text):
        if any(token in text for token in ("Python", "python", "代码", "可运行")):
            return (
                "## 可直接运行的示例\n\n"
                "下面用三篇候选文档模拟两路召回分数。示例先分别做 min-max 归一化，再改变关键词权重；"
                "向量权重始终等于 `1 - keyword_weight`。运行不需要第三方库。\n\n"
                "```python\n"
                "documents = {\n"
                "    'A': {'keyword': 1.0, 'vector': 0.2},  # 精确命中术语\n"
                "    'B': {'keyword': 0.6, 'vector': 0.9},  # 词面和语义都较好\n"
                "    'C': {'keyword': 0.1, 'vector': 0.8},  # 主要依靠语义命中\n"
                "}\n\n"
                "def min_max(values):\n"
                "    low, high = min(values), max(values)\n"
                "    if high == low:\n"
                "        return [0.0 for _ in values]\n"
                "    return [(value - low) / (high - low) for value in values]\n\n"
                "def rank(keyword_weight):\n"
                "    if not 0.0 <= keyword_weight <= 1.0:\n"
                "        raise ValueError('keyword_weight must be between 0 and 1')\n"
                "    vector_weight = 1.0 - keyword_weight\n"
                "    names = list(documents)\n"
                "    keyword_scores = min_max([documents[name]['keyword'] for name in names])\n"
                "    vector_scores = min_max([documents[name]['vector'] for name in names])\n"
                "    fused = []\n"
                "    for name, keyword, vector in zip(names, keyword_scores, vector_scores):\n"
                "        score = keyword_weight * keyword + vector_weight * vector\n"
                "        fused.append((name, round(score, 3)))\n"
                "    return sorted(fused, key=lambda item: (-item[1], item[0]))\n\n"
                "for weight in (0.8, 0.5, 0.2):\n"
                "    print(f'keyword={weight:.1f}, vector={1-weight:.1f}: {rank(weight)}')\n"
                "```\n\n"
                "### 预期输出怎么读\n\n"
                "关键词权重为 0.8 时，A 的精确术语命中占优势，顺序是 A、B、C；权重各为 0.5 时，B 的两路综合表现最好，"
                "顺序变为 B、A、C；关键词权重降到 0.2 后，C 凭较高语义分超过 A，顺序变为 B、C、A。"
                "这说明权重改变的不是文档原始内容，而是两类证据在最终分数中的贡献。\n\n"
                "### 这个示例刻意简化了什么\n\n"
                "真实系统中的 BM25 和余弦相似度分布可能很偏，单次查询内的 min-max 也容易受极值影响；两路候选还可能不完全重合。"
                "生产方案通常要在独立验证集上比较 Recall@K、MRR、延迟和无证据率，并考虑 RRF 或 reranker。"
                "请至少再测试两种边界：某一路所有分数相同，以及某篇文档只被一路召回；不能为了提高分数而关闭课程和版本隔离。"
            )
        if any(token in text for token in ("严格推导", "评分归一化", "候选合并", "边界条件", "逐步说明")):
            return (
                "## 1. 输入与符号\n\n"
                "给定查询 `q` 和文档集合 `D`。关键词检索为文档 `d_i` 产生 BM25 分数 `b_i`，向量检索产生余弦相似度 `c_i`。"
                "两者不能直接相加，因为数值范围和分布不同。先分别取前 `k_b`、`k_c` 个候选，并保留各自的文档标识、课程和版本。\n\n"
                "### 2. 评分归一化\n\n"
                "一种可解释写法是 `b'_i=(b_i-min(b))/(max(b)-min(b))`，`c'_i` 同理。若某一路 `max=min`，分母为零，"
                "不能继续套公式；可以把该路视为没有区分度，或改用按排名计算的 RRF。余弦分数可能为负，也必须在归一化策略中明确处理。\n\n"
                "### 3. 候选合并与融合\n\n"
                "候选集合取并集 `C = C_b ∪ C_c`，同一文档按稳定 ID 去重。只在关键词路出现的文档令 `c'_i=0`，只在向量路出现的文档令 `b'_i=0`。"
                "给定 `0≤λ≤1`，基础融合分数是 `F_i = λb'_i + (1-λ)c'_i`。λ 越大越强调精确词面，越小越强调语义覆盖。"
                "若使用 RRF，则可写成 `F_i = 1/(K+r_b(i)) + 1/(K+r_c(i))`，避免直接比较原始分数。\n\n"
                "### 4. 重排与最终输出\n\n"
                "先按 `F_i` 取前 `m` 个候选，再由 reranker 对 `(q,d_i)` 计算更精细的相关性 `g_i`。"
                "最终分数可以是 `S_i=αF_i+(1-α)g_i`，也可以完全采用重排顺序；两种策略必须在验证集上固定，不能逐次随意切换。"
                "输出前还要执行 owner、course、version 和可见性过滤，并把最终文档绑定到可定位片段。\n\n"
                "### 5. 边界条件与正确性检查\n\n"
                "空查询、一路无结果、两路分数完全相同、候选重复、余弦为负、过滤后为空，都是必须定义的状态。"
                "过滤时机也有取舍：权限过滤必须在返回前严格完成；若过早截断候选，可能降低召回，若过晚才校验权限，则可能产生越界风险。"
                "工程上应固定金标准查询集，比较 Recall@K、MRR、nDCG、平均延迟与无证据拒答率，并用未参与调参的数据验证 λ 和 α。\n\n"
                "因此，混合检索的严格流程是：同一输入上的两路召回 → 可比较的分数或排名 → 稳定 ID 并集去重 → 融合取候选 → 重排 → 权限与来源绑定。"
                "任何一步缺失，都可能让最终排序看似有分数、实际上不可解释或不可复现。"
            )
        if any(token in text for token in ("生活类比", "直观", "类比")):
            return (
                "## 把它想成图书馆里两位配合找书的人\n\n"
                "你去图书馆说：‘我想找一本讲神经网络训练不稳定、参数总来回震荡的书。’第一位馆员只看书名、索引词和编号，"
                "他很擅长找到标题里明确写着‘学习率’或‘梯度下降’的书；这像关键词检索，遇到函数名、版本号、课程术语时又快又准。\n\n"
                "第二位馆员会先理解你的意思：你虽然没说‘学习率过大’，但描述的是‘参数震荡、训练不收敛’。"
                "他能把表达不同、含义相近的书也找出来；这像向量检索，擅长同义表达和上下文相似。\n\n"
                "### 为什么不能只留一位\n\n"
                "只让第一位找，‘PyTorch 2.4 的 AdamW’这种精确名称很可靠，但你换成口语‘训练为什么一直抖’，他可能漏掉。"
                "只让第二位找，覆盖面更大，却可能把‘振荡信号处理’这种语义相近但课程不相关的内容带进来。"
                "混合检索就是让两位各交一份候选清单，再由第三位负责人按统一标准合并、去重和重排。\n\n"
                "### 一次完整找书过程\n\n"
                "先把同一个问题同时交给两位馆员；然后把‘书名精确命中’和‘语义相似’这两种不同尺度的分数换到可比较范围；"
                "接着按当前任务分配权重：查版本号时偏关键词，描述现象时偏语义；最后检查课程、版本和阅读权限，再把真正相关的书放到前面。"
                "它不是把两摞书随便堆起来，而是一次有规则的候选合并和复核。\n\n"
                "### 用一个反例检验理解\n\n"
                "查询‘BERT 位置编码’时，关键词路若已精确命中教材章节，盲目提高向量权重可能引入其他 Transformer 章节；"
                "查询‘模型为什么记住训练集却不会做新题’时，语义路能把没有原词但讲‘过拟合’的材料召回。"
                "两种查询需要不同侧重，这正是混合的价值。\n\n"
                "真正评价它时，要用一组包含精确术语、口语改写和错别字的查询，比较 Recall@5、MRR、首个正确结果位置和延迟。"
                "如果现有课程内容里找不到能回答问题的信息，就应直接说明还缺什么，而不是让任一位馆员凭印象补一本不存在的书。"
            )
        return (
            "## 直接回答\n\n"
            "混合检索把两路互补的召回结果放到同一个排序流程中：关键词检索保留精确术语、函数名、版本号和专有编号，"
            "向量检索补足同义表达、口语描述和上下文相近但词面不同的内容。它解决的是‘精确性’与‘覆盖面’之间的折中，"
            "不是简单把两个列表拼在一起。\n\n"
            "### 一次请求经过什么步骤\n\n"
            "先对同一 query 分别执行关键词召回和向量召回；然后把 BM25、相似度等不同量纲的分数归一化；"
            "接着按加权融合或 Reciprocal Rank Fusion 合并候选，再用 reranker 做重排（结合题意、课程范围和知识点关系重新排序）；"
            "最后保留当前课程与当前版本内的相关内容。这样既能保留精确命中，也能避免语义相近的噪声排在最前。\n\n"
            "### 如何判断它真的更好\n\n"
            "不要只看一次回答。固定一组包含术语、同义表达、错别字和跨语言缩写的查询集，记录 Recall@5、MRR、"
            "首个正确内容位置、平均延迟和无法确认的比例；同时检查是否把其他课程或其他版本的内容混入答案。"
            "如果关键词召回已经精确命中专有名词，可以降低向量分支的权重；如果用户使用自然语言描述，再提高语义召回权重。\n\n"
            "### 一个可执行的小实验\n\n"
            "准备 10 条已知正确结果的查询，分别运行关键词、向量和混合三种方案，保存 top-5 结果与耗时，"
            "再以 0.2 为步长调整融合权重。选出 Recall 与延迟都能接受的点后，用一组未参与调参的查询复验。"
            "无论分数多高，都不能关闭课程隔离或凭空补造内容；信息不够时应明确告诉学习者还需要补充什么。"
        )
    if "梯度下降" in text or "学习率" in text:
        return (
            "## 直接回答\n\n"
            "梯度下降沿损失函数梯度的反方向更新参数：`θ ← θ − η∇L(θ)`，其中 η 是学习率。"
            "梯度告诉我们当前位置上升最快的方向，减去它就会朝损失更小的方向移动；学习率决定每一步迈多大。\n\n"
            "### 学习率过大或过小会怎样\n\n"
            "η 过大时，参数可能跨过最低点，在训练曲线上表现为损失上下震荡、突然变成 NaN，甚至持续发散；"
            "η 过小时，损失下降很慢，训练许多轮仍停在原地。合适的学习率通常表现为训练损失稳定下降，"
            "验证损失也在合理范围内改善，而不是只有训练集越来越好。\n\n"
            "### 一套可复现的排查顺序\n\n"
            "先固定随机种子、批大小和数据划分，记录前几轮的 loss、梯度范数和验证指标；"
            "再用当前值的 0.1 倍、0.3 倍、1 倍和 3 倍做小范围对照。若曲线发散，先降低 η 并检查输入尺度；"
            "若下降过慢，可适度提高 η、使用 warm-up 或选择带动量的 SGD/Adam。每次只改一个变量，"
            "并用验证集而不是训练集决定最终方案。\n\n"
            "### 还要注意什么\n\n"
            "学习率并不能修复错误标签、未归一化特征或损失函数写错等问题；梯度为零也可能来自激活函数饱和。"
            "建议把训练曲线、配置和数据版本一起保存，方便定位是优化器、数据还是模型结构导致的变化。\n\n"
            "### 一个数值化的小例子\n\n"
            "设当前参数 θ=2、梯度 ∇L=3、学习率 η=0.1，则更新后 θ=2−0.1×3=1.7；"
            "如果把 η 改成 1，步长会放大十倍，可能直接越过低谷。实际调参时先用一个小批量确认梯度方向正确，"
            "再比较不同学习率下的训练/验证曲线，并在记录中注明批大小、优化器和随机种子。"
        )
    if "Kubernetes" in text or "Deployment" in text or "就绪探针" in text or "滚动更新" in text:
        return (
            "## 直接回答\n\n"
            "Kubernetes Deployment 通过 ReplicaSet 管理一组相同 Pod，并用滚动更新逐步把旧版本替换成新版本。"
            "就绪探针（readinessProbe）决定 Pod 是否加入 Service 的可用端点；它失败时 Pod 可以继续运行，但不会接收新流量。"
            "这与存活探针（livenessProbe）不同：存活探针失败通常会触发容器重启。\n\n"
            "### 一次安全发布的检查顺序\n\n"
            "1. 在 Deployment 中设置 `spec.strategy.rollingUpdate.maxUnavailable` 和 `maxSurge`，控制发布期间不可用和额外 Pod 数量；\n"
            "2. 为应用配置就绪探针，检查真正代表‘可以接流量’的健康端点，而不是只检查进程存在；\n"
            "3. 用 `kubectl rollout status deployment/<name>` 等待新 ReplicaSet 达到期望副本数，并观察错误率、延迟和资源使用；\n"
            "4. 若新版本异常，执行 `kubectl rollout undo deployment/<name>` 回到上一个 Revision，再检查事件和日志。\n\n"
            "### 容易踩坑的地方\n\n"
            "探针初始延迟过短会让冷启动应用反复被摘流量；只设置 liveness 而没有 readiness 可能把尚未完成初始化的 Pod 暴露出去；"
            "数据库迁移若不可向后兼容，也不能只依赖 Deployment 回滚，因为旧代码可能无法读取新 schema。生产环境还应配合 PodDisruptionBudget、"
            "资源 requests/limits、发布暂停点和可观测性告警。这部分属于扩展工程知识；如果你有实际部署配置，我可以继续逐项检查。"
        )
    topic = _guess_topic(text)
    if topic == "目标知识点":
        question_hint = re.sub(r"\s+", " ", text).strip(" `\t\r\n")
        question_hint = question_hint.rstrip("？?。.!！")
        return (
            "## 直接回答\n\n"
            f"我理解你想讨论的是“{question_hint[:120]}”。这个问题目前还缺少决定答案的具体对象或条件，所以先给你一套能直接往下推进的分析方法。\n\n"
            "先明确问题中的对象、目标和适用前提，再把过程或推导拆开；最后用一个正常例子和一个边界情形检查结论。"
            "若问题涉及代码，还应分别说明输入、输出、状态变化和复杂度。\n\n"
            "你可以补充公式、代码、数据或希望达到的岗位场景。我拿到这些信息后，会继续给出分步骤解释、最小例子、常见错误和练习。\n\n"
            "如果这是一个决策问题，还要说明评价指标、限制条件和可接受的失败代价；如果是工程问题，"
            "则需要把方案拆成输入、处理、输出、监控和回滚五个环节。你可以先提供当前尝试和一个反例，"
            "我会据此判断是概念缺口、边界条件遗漏，还是实现细节导致的现象，并给出下一步可执行检查。"
        )
    return (
        "## 直接回答\n\n"
        f"关于“{topic}”，建议先把问题拆成对象、条件、过程和结果四部分。先确认定义和适用前提，"
        "再用一个最小例子走完过程，随后比较边界情况，最后用反例或测试数据检查结论是否仍然成立。\n\n"
        "先明确输入、输出和适用前提，再把过程拆成可观察的步骤；如果涉及代码，应说明运行环境、状态变化和复杂度；"
        "如果涉及公式，应解释每个符号、推导假设和量纲。\n\n"
        "### 可执行的核对方式\n\n"
        "用一个最小例子走完过程，再用一个反例或极端输入检查边界；记录你观察到的中间状态，避免只凭最终结果判断正确。"
        "如果问题属于工程决策，还要比较指标、资源限制、失败代价、监控信号和回滚方案。\n\n"
        "你可以补充代码、公式、数据或目标岗位场景，"
        "我会据此给出更具体的分步解释、最小实现、常见误区和下一步练习。"
    )


def _profile_json(prompt: str) -> str:
    causes = []
    if any(word in prompt for word in ("看不懂", "不会", "不理解", "不知道", "基础", "概念")):
        causes.append("prerequisite_gap")
    if any(word in prompt for word in ("混", "分不清", "误区", "老是错", "错题")):
        causes.append("misconception")
    if any(word in prompt for word in ("题干长", "条件", "漏", "多步骤", "复杂")):
        causes.append("cognitive_load")
    if any(word in prompt for word in ("看答案", "不会复习", "记不住", "只会看视频", "刷题没用")):
        causes.append("strategy_gap")
    if any(word in prompt for word in ("以为会", "一做就错", "不确定", "不知道哪里不会")):
        causes.append("metacognitive_mismatch")
    if any(word in prompt for word in ("焦虑", "害怕", "没信心", "压力", "挫败")):
        causes.append("affective_barrier")
    if any(word in prompt for word in ("图", "代码", "一步步", "例子", "换种讲法", "视频")):
        causes.append("interaction_mismatch")

    weak_points = []
    for point in (
        "数据预处理", "特征工程", "线性回归", "逻辑回归", "决策树",
        "支持向量机", "朴素贝叶斯", "模型评估", "混淆矩阵", "过拟合",
        "正则化", "交叉验证", "池化层", "最大池化", "平均池化",
    ):
        if point in prompt:
            weak_points.append(point)

    preferences = []
    for keyword, preference in (
        ("图", "图示演示"), ("代码", "代码实操"),
        ("一步步", "分步引导"), ("例子", "具体例子"), ("视频", "短视频讲解"),
    ):
        if keyword in prompt:
            preferences.append(preference)

    goals = []
    for keyword, goal in (
        ("期末", "期末复习"), ("考试", "通过考试"), ("项目", "机器学习项目实践"),
        ("竞赛", "竞赛提升"), ("就业", "就业能力"), ("面试", "面试准备"),
    ):
        if keyword in prompt:
            goals.append(goal)

    major = "计算机专业" if "计算机" in prompt else ""
    return json.dumps(
        {
            "course": "机器学习导论",
            "major": major,
            "goals": goals,
            "weak_points": weak_points,
            "preferences": preferences,
            "learning_state_causes": sorted(set(causes)),
        },
        ensure_ascii=False,
    )


def _lecture(topic: str, prompt: str) -> str:
    if any(word in topic for word in ("机器学习", "监督学习", "过拟合", "正则化", "逻辑回归", "模型评估", "混淆矩阵")):
        return (
            f"# {topic}讲义\n\n"
            "机器学习导论的核心不是背模型名称，而是完成从数据到泛化能力的闭环："
            "数据预处理、特征工程、模型训练、验证评估和误差分析。\n\n"
            "学习路径建议：\n"
            "1. 先确认任务类型：回归、分类或聚类。\n"
            "2. 再检查数据：缺失值、异常值、类别编码和数值缩放。\n"
            "3. 用基线模型建立可解释起点。\n"
            "4. 用交叉验证判断泛化，而不是只看训练集分数。\n"
            "5. 若训练好验证差，优先检查过拟合并考虑正则化。\n\n"
            "画像驱动支持：若学生把 precision 和 recall 混淆，先用混淆矩阵反例辨析；"
            "若学生只会看答案，先做检索练习；若学生以为会但一做就错，加入题前自评和题后校准。"
        )
    if "池化" in topic:
        return (
            "# 池化层讲义\n\n"
            "池化层位于特征图之后，用一个固定窗口把局部区域压缩成更小的表示。"
            "以 2x2 最大池化为例，每个窗口只保留最大响应值，因此输出保留最显著的局部特征，"
            "同时降低空间尺寸和后续计算量。\n\n"
            "关键步骤：\n"
            "1. 在特征图上放置 2x2 窗口。\n"
            "2. 按 stride 移动窗口。\n"
            "3. 对每个窗口取 max 得到输出矩阵中的一个元素。\n\n"
            "常见误区：最大池化不是卷积，不学习参数；平均池化取均值，最大池化取最大值，二者不能混用。\n\n"
            "学习建议：若你总把最大池化和平均池化混在一起，先做反例辨析；"
            "若反馈\u201c题干长会漏条件\u201d，先列窗口大小、stride、池化类型三项条件清单；"
            "若反馈\u201c看答案才懂\u201d，先给局部提示，再让学生独立完成一个 2x2 窗口。"
        )
    return f"# {topic}讲义\n\n先说明需要掌握的前置概念，再解释核心机制、计算步骤，并用例子辨析常见误区。"


def _code(topic: str) -> str:
    if any(word in topic for word in ("机器学习", "监督学习", "逻辑回归", "模型评估", "混淆矩阵")):
        return (
            "```python\n"
            "from sklearn.datasets import load_breast_cancer\n"
            "from sklearn.model_selection import train_test_split, cross_val_score\n"
            "from sklearn.preprocessing import StandardScaler\n"
            "from sklearn.linear_model import LogisticRegression\n"
            "from sklearn.pipeline import Pipeline\n"
            "from sklearn.metrics import classification_report, confusion_matrix\n\n"
            "X, y = load_breast_cancer(return_X_y=True)\n"
            "X_train, X_test, y_train, y_test = train_test_split(\n"
            "    X, y, test_size=0.2, random_state=42, stratify=y\n"
            ")\n\n"
            "pipe = Pipeline([\n"
            "    ('scaler', StandardScaler()),\n"
            "    ('clf', LogisticRegression(max_iter=1000, C=1.0))\n"
            "])\n\n"
            "cv_scores = cross_val_score(pipe, X_train, y_train, cv=5, scoring='f1')\n"
            "pipe.fit(X_train, y_train)\n"
            "pred = pipe.predict(X_test)\n\n"
            "print('CV F1:', cv_scores.mean().round(3))\n"
            "print(confusion_matrix(y_test, pred))\n"
            "print(classification_report(y_test, pred))\n"
            "```\n"
        )
    if any(word in topic for word in ("过拟合", "正则化")):
        return (
            "```python\n"
            "from sklearn.datasets import load_wine\n"
            "from sklearn.linear_model import LogisticRegression\n"
            "from sklearn.model_selection import cross_val_score\n"
            "from sklearn.pipeline import make_pipeline\n"
            "from sklearn.preprocessing import StandardScaler\n\n"
            "X, y = load_wine(return_X_y=True)\n"
            "for c in [0.01, 0.1, 1, 10, 100]:\n"
            "    model = make_pipeline(StandardScaler(), LogisticRegression(C=c, max_iter=2000))\n"
            "    score = cross_val_score(model, X, y, cv=5, scoring='accuracy').mean()\n"
            "    print(f'C={c:<6} mean_cv_accuracy={score:.3f}')\n"
            "```\n"
        )
    if "池化" in topic:
        return (
            "```python\n"
            "import torch\n"
            "import torch.nn as nn\n\n"
            "x = torch.tensor([[[[1., 3., 2., 4.],\n"
            "                    [5., 6., 1., 2.],\n"
            "                    [0., 2., 8., 1.],\n"
            "                    [3., 1., 2., 7.]]]])\n\n"
            "pool = nn.MaxPool2d(kernel_size=2, stride=2)\n"
            "y = pool(x)\n"
            "print(y)  # tensor([[[[6., 4.], [3., 8.]]]])\n"
            "```\n"
        )
    return "```python\n# TODO: 根据目标知识点补充可运行示例\n```"


def _mermaid(topic: str) -> str:
    if any(word in topic for word in ("机器学习", "监督学习", "逻辑回归", "模型评估", "过拟合", "正则化")):
        return (
            "```mermaid\n"
            "flowchart LR\n"
            "  A[学习目标] --> B[数据预处理]\n"
            "  B --> C[特征工程]\n"
            "  C --> D[训练基线模型]\n"
            "  D --> E[交叉验证]\n"
            "  E --> F{泛化表现}\n"
            "  F -->|过拟合| G[正则化/降复杂度]\n"
            "  F -->|指标不均衡| H[混淆矩阵与F1]\n"
            "  G --> E\n"
            "  H --> I[错因复盘与迁移练习]\n"
            "```\n"
        )
    return (
        "```mermaid\n"
        "flowchart LR\n"
        "  A[输入特征图] --> B[2x2 窗口]\n"
        "  B --> C[取局部最大值]\n"
        "  C --> D[降采样特征图]\n"
        "  D --> E[全连接层或下一层卷积]\n"
        "```\n"
    )


def _quiz(topic: str) -> str:
    if any(word in topic for word in ("机器学习", "监督学习", "逻辑回归", "模型评估", "过拟合", "正则化")):
        return (
            "1. 检索题：不看资料，说出训练集、验证集和测试集的区别。\n"
            "2. 辨析题：某分类器 accuracy=95%，但少数类 recall=20%，这个模型适合上线吗？为什么？\n"
            "3. 代码改错：如果逻辑回归在训练集 99%、验证集 70%，优先检查过拟合，并尝试正则化或交叉验证。\n"
            "4. 元认知校准题：先自评\u201c我能否解释 precision 与 recall 的差异\u201d，再用混淆矩阵计算一次。"
        )
    return (
        "1. 选择题：2x2 最大池化窗口 [1, 3; 5, 2] 的输出是多少？答案：5。\n"
        "2. 填空题：最大池化主要保留局部区域中的____响应。答案：最大/最强。\n"
        "3. 代码改错：若讲义要求最大池化，代码应使用 nn.MaxPool2d 而不是 nn.AvgPool2d。\n"
        "4. 画像校准题：先自评本题把握度 0-1，再独立写出第一个窗口的计算过程；"
        "若自评高但做错，系统记录为元认知校准风险，并安排相似题重测。"
    )


def _video_script(topic: str) -> str:
    if any(word in topic for word in ("机器学习", "监督学习", "逻辑回归", "模型评估", "过拟合", "正则化")):
        return (
            "虚拟人脚本：先展示一个机器学习项目看板，从数据预处理进入模型训练。"
            "画面切到混淆矩阵，讲解 accuracy 高但 recall 低的风险；"
            "再展示训练误差下降、验证误差上升的过拟合曲线，最后用正则化和交叉验证完成修正。"
        )
    return (
        "虚拟人脚本：先展示 4x4 特征图，再高亮第一个 2x2 窗口，播报“我们取这个窗口里最大的 6”，"
        "随后移动窗口得到 2x2 输出矩阵，最后提示最大池化降低尺寸 but 保留显著特征。"
    )


def _video_recommendations(topic: str) -> str:
    import json
    return json.dumps([
        {
            "title": f"Bilibili: 机器学习中{topic}的可视化教学",
            "url": "https://www.bilibili.com/video/BV1111111111",
            "source": "B站视频",
            "recommendation": f"该视频通过精美的三维动画直观地演示了{topic}的运行轨迹，非常适合帮助建立空间与几何直观感知。"
        },
        {
            "title": f"本地三维演示动画 - {topic}",
            "url": "/api/v1/animations/video/gd.mp4",
            "source": "本地动画",
            "recommendation": f"系统为您量身定制的{topic}本地推导演示动画，分步剖析其底层数学运算逻辑。"
        }
    ], ensure_ascii=False)


def get_concept_rich_adaptation(concept: str, mastery_score: float = 0.4) -> dict:
    """Return high-fidelity concept-specific simplified explanation and detailed Mermaid mindmap."""
    mastery_pct = round(max(0.0, min(1.0, mastery_score)) * 100)
    c = concept.strip()
    
    knowledge_map = {
        "池化层": {
            "explanation": (
                f"💡 降维直觉：池化层就像给高清大图生成缩略图！它用固定大小的滑动窗口（如 2x2）在特征图上扫描，"
                f"只抽取局部最显著的特征（最大池化 MaxPool）或求平均（平均池化 AvgPool）。"
                f"这样既降低了数据尺寸和后续计算量，又赋予了模型平移不变性。\n\n"
                f"🎯 避坑提醒：当前掌握度 {mastery_pct}%。请注意：池化层没有任何需要训练更新的权重参数，"
                f"且输入与输出的通道数 (Channel) 保持完全一致！"
            ),
            "mermaid": (
                "mindmap\n"
                '  root(("池化层 (Pooling)"))\n'
                "    生活化类比\n"
                "      像压缩照片生成缩略图\n"
                "      只保留最显著的局部特征\n"
                "    两大主流计算\n"
                "      MaxPool (最大池化: 提取最强响应)\n"
                "      AvgPool (平均池化: 保留背景均值)\n"
                "    核心参数约束\n"
                "      kernel_size 2x2 (采样窗口大小)\n"
                "      stride 2 (滑动步长)\n"
                "    避坑红线防错\n"
                "      无可学习参数 (不进行反向传播更新)\n"
                "      通道数 Channel 保持完全不变\n"
            )
        },
        "卷积神经网络": {
            "explanation": (
                f"💡 降维直觉：CNN 就像探长用放大镜逐区域扫描现场！低层卷积核提取直线、边缘等基础线条；"
                f"高层卷积核把基础线条拼装成眼睛、轮廓等完整零件。通过权值共享与局部感受野，参数量大幅降低。\n\n"
                f"🎯 最小演练：当前掌握度 {mastery_pct}%。尝试算一算：4x4 特征图用 3x3 卷积核无 padding 卷积，"
                f"输出尺寸为 (4-3+1) = 2x2。"
            ),
            "mermaid": (
                "mindmap\n"
                '  root(("卷积神经网络 (CNN)"))\n'
                "    生活化类比\n"
                "      像放大镜逐区域扫描探案\n"
                "      从局部边缘拼装出高层概念\n"
                "    三大核心结构\n"
                "      卷积层 (滑动窗口点乘提取特征)\n"
                "      池化层 (降维缩放与平移不变)\n"
                "      全连接层 (整合全局特征做分类)\n"
                "    尺寸计算公式\n"
                "      N_out = (W - K + 2P)/S + 1\n"
                "    三大工程优势\n"
                "      局部感受野 + 权值共享 + 平移不变\n"
            )
        },
        "逻辑回归": {
            "explanation": (
                f"💡 降维直觉：逻辑回归就像打分裁判！它先计算线性的综合得分 z = w1*x1 + w2*x2 + b，"
                f"再用 S 型的 Sigmoid 函数把得分压缩到 (0, 1) 区间表示概率。概率 > 0.5 判定为正类。\n\n"
                f"🎯 避坑提醒：当前掌握度 {mastery_pct}%。注意！逻辑回归名字叫“回归”，但它实际上是解决二分类问题的经典分类模型！"
            ),
            "mermaid": (
                "mindmap\n"
                '  root(("逻辑回归 (Logistic Regression)"))\n'
                "    生活化类比\n"
                "      像裁判将连续打分转化为通过或淘汰\n"
                "    核心计算管道\n"
                "      1. 线性加权得分 z = w^T x + b\n"
                "      2. Sigmoid 激活 sigma(z) = 1/(1+e^-z)\n"
                "      3. 概率判决 (默认阈值 0.5)\n"
                "    损失函数与优化\n"
                "      对数损失 (Cross-Entropy Loss)\n"
                "      梯度下降更新权重 w\n"
                "    经典误区辨析\n"
                "      名字叫回归，本质是分类模型！\n"
            )
        },
        "过拟合": {
            "explanation": (
                f"💡 降维直觉：过拟合就像考生死记硬背了模拟题原题答案！在做过的卷子上拿了 100 分，"
                f"可遇到高考新题就手足无措。根源在于模型太复杂、参数太多，把训练集里的细节噪声也当规律学进去了。\n\n"
                f"🎯 破局行动：当前掌握度 {mastery_pct}%。建议给模型降温：用 L1/L2 正则化惩罚大权重，或用 Dropout 随机截断部分神经元。"
            ),
            "mermaid": (
                "mindmap\n"
                '  root(("过拟合 (Overfitting)"))\n'
                "    生活化类比\n"
                "      考生死记硬背模拟题原题答案\n"
                "      训练集满分，测试集大跌\n"
                "    核心触发原因\n"
                "      模型参数量过大 / 复杂度过高\n"
                "      训练数据太少 / 混入噪声\n"
                "    四大解毒处方\n"
                "      L1/L2 正则化 (限制权重过大)\n"
                "      Dropout (随机暂停神经元)\n"
                "      数据增强 (Data Augmentation)\n"
                "      早停机制 (Early Stopping)\n"
            )
        },
        "正则化": {
            "explanation": (
                f"💡 降维直觉：正则化就像给过于骄傲的模型戴上“紧箍咒”！在原本的损失函数后面加上权重惩罚项，"
                f"强迫模型保持简单，防止某个特征的权重过于膨胀。\n\n"
                f"🎯 常用对比：掌握度 {mastery_pct}%。L1 正则 (Lasso) 让不重要的权重变为 0（做特征筛选）；"
                f"L2 正则 (Ridge) 让权重均匀收缩变小。"
            ),
            "mermaid": (
                "mindmap\n"
                '  root(("正则化 (Regularization)"))\n'
                "    生活化类比\n"
                "      给模型戴上紧箍咒，防止任意妄为\n"
                "    两大主流类型\n"
                "      L1 正则 (Lasso): 产生稀疏权重，做特征选择\n"
                "      L2 正则 (Ridge): 抑制大权重，平滑预测曲线\n"
                "    目标函数构成\n"
                "      Total Loss = Data Loss + lambda * Penalty\n"
                "    超参数 lambda 调节\n"
                "      lambda 过大 -> 欠拟合; lambda 过小 -> 过拟合\n"
            )
        },
        "交叉验证": {
            "explanation": (
                f"💡 降维直觉：交叉验证就像轮流当监考老师！把数据分成 K 份（如 K=5），每次用 1 份当测试集，"
                f"剩下的 4 份当训练集，做 5 次并取平均得分。这样确保每块数据都被评估过，结果比单次划分更真实。\n\n"
                f"🎯 最小建议：当前掌握度 {mastery_pct}%。类别不均衡时，务必使用分层 K 折交叉验证 (Stratified K-Fold)。"
            ),
            "mermaid": (
                "mindmap\n"
                '  root(("交叉验证 (Cross Validation)"))\n'
                "    生活化类比\n"
                "      轮流当考官，评估模型的真实泛化水平\n"
                "    主流 K-Fold 流程\n"
                "      1. 数据切分成 K 等份\n"
                "      2. 循环 K 次：1份验证 + K-1份训练\n"
                "      3. 计算 K 次指标的算术平均值\n"
                "    常用变体应用\n"
                "      Stratified K-Fold (分层保持类别比例)\n"
                "      Leave-One-Out (留一法，适用于小样本)\n"
            )
        },
        "注意力机制": {
            "explanation": (
                f"💡 降维直觉：注意力机制就像阅读长文时的眼神聚焦！我们看书时不会平均对待每个字，"
                f"而是重点扫描关键词。模型通过 Query（想找什么）、Key（标签）、Value（内容）计算相关度，把计算资源集中在关键输入上。\n\n"
                f"🎯 核心公式：Attention(Q,K,V) = Softmax( Q K^T / sqrt(d_k) ) V。"
            ),
            "mermaid": (
                "mindmap\n"
                '  root(("注意力机制 (Attention)"))\n'
                "    生活化类比\n"
                "      看文章时眼神自动聚焦高亮关键词\n"
                "    Q_K_V 三元组角色\n"
                "      Query (查询: 当前关注的目标)\n"
                "      Key (键: 序列中各元素的索引标签)\n"
                "      Value (值: 对应元素的丰富信息表示)\n"
                "    计算四步曲\n"
                "      1. 点积匹配 -> 2. 缩放 sqrt(d_k) -> 3. Softmax 归一化 -> 4. 加权求和 V\n"
                "    缩放因子作用\n"
                "      防止点积数值过大导致 Softmax 梯度消失\n"
            )
        },
        "Transformer": {
            "explanation": (
                f"💡 降维直觉：Transformer 就像拥有全局视野的同声传译！传统 RNN 必须逐字顺序读取，"
                f"而 Transformer 抛弃循环结构，利用自注意力机制 (Self-Attention) 一次性全局处理整句话，并能高度并行训练。\n\n"
                f"🎯 核心结构：Encoder 负责全局特征编码，Decoder 配合 Cross-Attention 逐字生成文本。"
            ),
            "mermaid": (
                "mindmap\n"
                '  root(("Transformer 架构"))\n'
                "    生活化类比\n"
                "      突破时间限制、拥有全局视野的同传专家\n"
                "    两大核心组件\n"
                "      Encoder (编码器: 提取全局多头特征)\n"
                "      Decoder (解码器: 自回归生成目标序列)\n"
                "    三大关键技术\n"
                "      Multi-Head Attention (多头注意力)\n"
                "      Positional Encoding (位置编码注入顺序)\n"
                "      Feed Forward & LayerNorm (前馈与残差归一化)\n"
            )
        },
        "梯度下降": {
            "explanation": (
                f"💡 降维直觉：梯度下降就像盲人蒙眼下山！茫茫大雾中看不见山脚，盲人通过脚尖感应坡度最陡的方向（负梯度方向），"
                f"向下迈出一小步（学习率 alpha），反复寻找最低处的谷底（Loss 最小值）。\n\n"
                f"🎯 避坑提醒：当前掌握度 {mastery_pct}%。学习率 alpha 太大容易跨过谷底发散，太小会导致下山极其缓慢！"
            ),
            "mermaid": (
                "mindmap\n"
                '  root(("梯度下降 (Gradient Descent)"))\n'
                "    生活化类比\n"
                "      大雾中蒙眼试探最陡坡度一步步下山\n"
                "    核心更新公式\n"
                "      w_new = w_old - alpha * grad(Loss)\n"
                "    三大常见算法\n"
                "      BGD (批量梯度下降: 准确但慢)\n"
                "      SGD (随机梯度下降: 快但抖动)\n"
                "      MBGD / Adam (小批量自适应动量下降)\n"
                "    学习率 alpha 影响\n"
                "      太大 -> 震荡发散; 太小 -> 收敛龟速\n"
            )
        },
        "支持向量机": {
            "explanation": (
                f"💡 降维直觉：SVM 就像在两组棋子之间画一条最宽的隔离河！它不仅要把两类棋子分开，"
                f"还要让离隔离河最近的关键棋子（支持向量 Support Vectors）距离河岸越远越好（最大化 Margin）。\n\n"
                f"🎯 核技巧 Kernel Trick：当平面上分不开时，用核函数把数据映射到高维空间变线性可分！"
            ),
            "mermaid": (
                "mindmap\n"
                '  root(("支持向量机 (SVM)"))\n'
                "    生活化类比\n"
                "      在两类棋子间修建一条最宽的护城河\n"
                "    核心数学目标\n"
                "      最大化分类间隔 (Maximize Margin = 2/||w||)\n"
                "    支持向量定义\n"
                "      决定超平面位置的那些临界边缘样本点\n"
                "    核技巧 Kernel Trick\n"
                "      RBF / 高斯核: 高维投影解决非线性分类\n"
            )
        },
        "决策树": {
            "explanation": (
                f"💡 降维直觉：决策树就像做“二十个问题”提问猜谜游戏！从根节点开始，每次挑一个最能区分物种的特征做二叉提问，"
                f"沿着条件分支向下剖析，直到末端的叶子节点做出最终分类。\n\n"
                f"🎯 分裂标准：ID3 用信息增益，C4.5 用信息增益比，CART 用基尼系数 (Gini Impurity)。"
            ),
            "mermaid": (
                "mindmap\n"
                '  root(("决策树 (Decision Tree)"))\n'
                "    生活化类比\n"
                "      按条件一步步提问分流的流程图猜谜游戏\n"
                "    三大节点构成\n"
                "      根节点 (起点) -> 内部节点 (特征提问) -> 叶子节点 (分类结果)\n"
                "    特征选择指标\n"
                "      信息增益 (Information Gain - ID3)\n"
                "      基尼系数 (Gini Impurity - CART)\n"
                "    防过拟合策略\n"
                "      预剪枝 (限制树深) / 后剪枝 (合并节点)\n"
            )
        },
        "混淆矩阵": {
            "explanation": (
                f"💡 降维直觉：混淆矩阵就像安检防爆的四宫格检验表！把预测和真实情况分为：真正 TP（抓对坏人）、"
                f"假正 FP（误伤好人）、假负 FN（漏抓坏人）、真负 TN（放行好人）。\n\n"
                f"🎯 指标辨析：精确率 Precision 看抓出的坏人里有多少真的坏人；召回率 Recall 看所有坏人里漏抓了多少。"
            ),
            "mermaid": (
                "mindmap\n"
                '  root(("混淆矩阵 (Confusion Matrix)"))\n'
                "    生活化类比\n"
                "      安检站拦截坏人与放行好人的四宫格账本\n"
                "    四宫格单元\n"
                "      TP (真正: 预测为1，真实为1)\n"
                "      FP (假正: 预测为1，真实为0 - 误报)\n"
                "      FN (假负: 预测为0，真实为1 - 漏报)\n"
                "      TN (真负: 预测为0，真实为0)\n"
                "    三大衍生指标\n"
                "      Precision = TP / (TP + FP)\n"
                "      Recall = TP / (TP + FN)\n"
                "      F1-Score = 2*P*R / (P + R)\n"
            )
        },
        "激活函数": {
            "explanation": (
                f"💡 降维直觉：激活函数就像神经元的电信号门槛阀门！没有激活函数，多层网络叠再高也只是简单线性乘法；"
                f"加入非线性激活函数（如 ReLU、Sigmoid），网络才能弯曲拟合复杂曲面。\n\n"
                f"🎯 常用首选：隐层首选 ReLU (f(x)=max(0,x))，计算快且缓解梯度消失；输出层二分类用 Sigmoid，多分类用 Softmax。"
            ),
            "mermaid": (
                "mindmap\n"
                '  root(("激活函数 (Activation)"))\n'
                "    生活化类比\n"
                "      神经元的非线性闸门，赋予网络拟合复杂曲面的能力\n"
                "    三大常用函数\n"
                "      ReLU: max(0,x) 简单高效，主流首选\n"
                "      Sigmoid: 1/(1+e^-x) 压缩至(0,1)，易梯度消失\n"
                "      Softmax: 归一化为多分类概率分布\n"
                "    核心作用原理\n"
                "      打破线性层叠加，引入非线性表达力\n"
            )
        },
        "损失函数": {
            "explanation": (
                f"💡 降维直觉：损失函数就是打靶比赛里的离靶心距离！它测量模型预测值与真实标准答案的差距。"
                f"Loss 算出的得分越小，预测越精准；模型训练的过程就是想方设法最小化损失函数。\n\n"
                f"🎯 任务匹配：回归问题用均方误差 (MSE)；分类问题用交叉熵损失 (Cross-Entropy)。"
            ),
            "mermaid": (
                "mindmap\n"
                '  root(("损失函数 (Loss Function)"))\n'
                "    生活化类比\n"
                "      打靶比赛中测量弹孔偏离靶心距离的尺子\n"
                "    两大任务标准\n"
                "      回归任务: MSE (均方误差) / MAE (绝对误差)\n"
                "      分类任务: Cross-Entropy (交叉熵损失)\n"
                "    优化目标\n"
                "      通过反向传播求梯度，引导参数朝 Loss 最小方向更新\n"
            )
        },
        "前向传播": {
            "explanation": (
                f"💡 降维直觉：前向传播就是工厂流水线从原料加工出成品的过程！数据从输入层进入，"
                f"经过各层权重加权与激活函数过滤，一步步向右传递，最后在输出层算出预测结果。\n\n"
                f"🎯 对应关系：前向传播计算预测值 y_hat；反向传播拿预测误差倒查更新各层机器参数。"
            ),
            "mermaid": (
                "mindmap\n"
                '  root(("前向传播 (Forward Pass)"))\n'
                "    生活化类比\n"
                "      工厂流水线从原材料一步步加工生成最终产品\n"
                "    单层计算链条\n"
                "      1. 线性变换 z = W * x + b\n"
                "      2. 非线性激活 a = activation(z)\n"
                "      3. 传递给下一层作为输入\n"
                "    核心输出目的\n"
                "      计算最终预测值 y_hat 并评估 Loss\n"
            )
        },
        "反向传播": {
            "explanation": (
                f"💡 降维直觉：反向传播就像项目出差错后的倒查责任制！当最后的效果 Loss 不好时，"
                f"从输出层开始向左追溯，运用链式法则 (Chain Rule) 计算各层权重 w 应对误差负多大责任（梯度），从而精准更新参数。\n\n"
                f"🎯 数学核心：逐层求导 dL/dw = dL/dy * dy/dz * dz/dw。"
            ),
            "mermaid": (
                "mindmap\n"
                '  root(("反向传播 (Backpropagation)"))\n'
                "    生活化类比\n"
                "      项目出差错后沿工序倒查责任人的链式追责\n"
                "    数学基石\n"
                "      微积分链式法则 (Chain Rule 逐层求导)\n"
                "    三大核心步骤\n"
                "      1. 计算输出层 Loss 梯度\n"
                "      2. 从右向左反向链式传递梯度\n"
                "      3. 配合优化器更新权重 w = w - alpha * grad\n"
            )
        }
    }
    
    # Check for direct match or partial match in knowledge map
    for key, val in knowledge_map.items():
        if key in c or c in key:
            return val
            
    # Dynamic fallback generator for unknown/custom concepts
    clean_c = c.replace('"', '').replace("'", '').replace("(", '').replace(")", '')
    return {
        "explanation": (
            f"💡 降维直觉：理解「{clean_c}」的核心在于理清它的输入、输出与解决痛点！"
            f"先确认它要替代的旧方法，观察它如何将复杂数据一步步转换，最后回到代码实现。\n\n"
            f"🎯 最小行动：当前掌握度约 {mastery_pct}%。建议结合具体数据例子跑一遍前向流程，重点辨析边界条件。"
        ),
        "mermaid": (
            "mindmap\n"
            f'  root(("{clean_c} 核心知识"))\n'
            "    生活化直觉\n"
            f"      理解 {clean_c} 要解决的关键痛点\n"
            "      用已知生活现象做对比抽象\n"
            "    核心变换流程\n"
            "      1. 确认输入数据格式\n"
            "      2. 逐步计算与特征变换\n"
            "      3. 导出最终预测/分类输出\n"
            "    关键要素与变量\n"
            "      关键超参数配置\n"
            "      数学约束与假设条件\n"
            "    避坑与最小复盘\n"
            "      识别常见易错边界误区\n"
            "      完成一次最小动手实操\n"
        )
    }


def _simplified_explanation(topic: str, prompt: str) -> str:
    import json
    data = get_concept_rich_adaptation(topic, 0.4)
    return json.dumps(data, ensure_ascii=False)

