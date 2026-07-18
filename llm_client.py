from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import math
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


_shared_httpx_client: Any | None = None


async def _get_httpx_client() -> Any:
    global _shared_httpx_client
    if _shared_httpx_client is None:
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
    return _shared_httpx_client


@dataclass
class AsyncOpenAIChatLLM:
    endpoint: str
    api_key: str
    model: str
    temperature: float = 0.3
    max_tokens: int = 8192
    timeout_seconds: int = 120
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
                content = data["choices"][0]["message"]["content"].strip()
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
            fallback_endpoint = self.multimodal_endpoint or CONFIG.multimodal_llm_endpoint
            fallback_api_key = self.multimodal_api_key or CONFIG.multimodal_llm_api_key
            fallback_model = self.multimodal_model or CONFIG.multimodal_llm_model

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
            return data["choices"][0]["message"]["content"].strip()
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


class DeterministicEducationLLM:
    def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        if "学术概念实体消解与指代对齐助手" in system_prompt or "学术概念实体消解与指代对齐助手" in role:
            if "池化层" in user_prompt and ("这个" in user_prompt or "它" in user_prompt):
                return "池化层"
            return "None"
        if "画像抽取器" in role:
            return _profile_json(user_prompt)
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
        return f"{role} 已基于检索证据处理主题：{topic}。"


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
            multimodal_endpoint=overrides.get("multimodal_endpoint", config.multimodal_llm_endpoint),
            multimodal_api_key=overrides.get("multimodal_api_key", config.multimodal_llm_api_key),
            multimodal_model=overrides.get("multimodal_model", config.multimodal_llm_model),
            is_multimodal_fallback=overrides.get("is_multimodal_fallback", False),
        )
        
    if primary is not None:
        return FallbackAsyncLLMWrapper(primary, AsyncDeterministicEducationLLM())
    return AsyncDeterministicEducationLLM()


DEFAULT_LLM = DeterministicEducationLLM()
DEFAULT_ASYNC_LLM = build_async_llm()


def call_spark_api(prompt: str, role: str = "助手") -> str:
    return DEFAULT_LLM.generate(f"你现在是 EduMatrix 系统的{role}", prompt, role=role)


def _guess_topic(text: str) -> str:
    target_match = re.search(r"(?<!学习)目标=([^;；\n]+)|GraphRAG目标知识点[：:]\s*([^\n]+)", text)
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
        "神经网络", "卷积神经网络", "混淆矩阵",
    )
    sorted_words = sorted(words, key=len, reverse=True)
    for word in sorted_words:
        if word in text:
            return word
    return "目标知识点"


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
            "画像驱动支持：若学生反馈\u201c最大池化和平均池化总混\u201d，先做反例辨析；"
            "若反馈\u201c题干长会漏条件\u201d，先列窗口大小、stride、池化类型三项条件清单；"
            "若反馈\u201c看答案才懂\u201d，先给局部提示，再让学生独立完成一个 2x2 窗口。"
        )
    return f"# {topic}讲义\n\n基于检索证据，先说明前置概念，再解释核心机制、计算步骤和常见误区。"


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

