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
from typing import Any, Protocol
from urllib.parse import urlencode, urlparse

from config import CONFIG, EduMatrixConfig
from concurrency import APIRateLimiter, CircuitBreaker, retry_with_backoff

# 声明星火专用熔断器（Task 2.2: fail_max=3, reset_timeout=30.0）
spark_breaker = pybreaker.CircuitBreaker(fail_max=3, reset_timeout=30.0)


class LLMBackend(Protocol):
    def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        ...


class AsyncLLMBackend(Protocol):
    async def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
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
    max_tokens: int = 4096
    timeout_seconds: int = 120

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


class OpenAIChatLLM:
    def __init__(
        self,
        endpoint: str,
        api_key: str,
        model: str = "gpt-4o-mini",
        temperature: float = 0.3,
        max_tokens: int = 4096,
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
                    "temperature": 0.25,
                    "max_tokens": 4096,
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
                    "temperature": 0.25,
                    "max_tokens": 4096,
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

    @spark_breaker
    async def _generate_with_breaker(self, system_prompt: str, user_prompt: str) -> str:
        import asyncio
        import functools
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, functools.partial(self._sync_generate, system_prompt, user_prompt))


class DeterministicEducationLLM:
    def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
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
        if "路径规划师" in role:
            return f"学习路径建议：先补齐前置概念，再学习 {topic} 的定义、计算流程、代码实现和易错点。"
        return f"{role} 已基于检索证据处理主题：{topic}。"


class AsyncDeterministicEducationLLM:
    async def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        return DeterministicEducationLLM().generate(system_prompt, user_prompt, role=role)


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


def build_async_llm(config: EduMatrixConfig = CONFIG, **overrides) -> AsyncLLMBackend:
    # 支持动态覆盖配置（用于 swarm_factory）
    provider = overrides.get("provider", config.llm_provider).lower().strip()
    api_key = overrides.get("api_key", config.llm_api_key)
    endpoint = overrides.get("endpoint", config.llm_endpoint)
    model = overrides.get("model", config.llm_model)
    
    if provider == "spark" or (config.spark_app_id and config.spark_api_key):
        return AsyncSparkClient(
            app_id=config.spark_app_id,
            api_key=config.spark_api_key,
            api_secret=config.spark_api_secret,
            spark_url=config.spark_url,
            domain=config.spark_domain,
        )
        
    if (provider == "openai" or provider == "vllm") and api_key:
        return AsyncOpenAIChatLLM(
            endpoint=endpoint,
            api_key=api_key,
            model=model,
            temperature=overrides.get("temperature", config.llm_temperature),
            max_tokens=overrides.get("max_tokens", config.llm_max_tokens),
            timeout_seconds=config.llm_timeout,
        )
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
    for word in (
        "池化层", "最大池化", "平均池化", "卷积核", "反向传播",
        "链式法则", "梯度下降", "过拟合", "正则化", "逻辑回归",
        "线性回归", "模型评估", "混淆矩阵", "监督学习", "机器学习",
    ):
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
        "虚拟人脚本：先展示 4x4 特征图，再高亮第一个 2x2 窗口，播报\u201c我们取这个窗口里最大的 6\u201d，"
        "随后移动窗口得到 2x2 输出矩阵，最后提示最大池化降低尺寸但保留显著特征。"
    )
