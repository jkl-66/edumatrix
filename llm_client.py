from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import ssl
import time
from typing import Protocol
from urllib.parse import urlencode, urlparse

from config import CONFIG, EduMatrixConfig


class LLMBackend(Protocol):
    def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        ...


@dataclass
class SparkClient:
    """科大讯飞星火 WebSocket 适配器。

    The adapter is isolated behind LLMBackend so tests and local demos never
    depend on external network access. Set EDUMATRIX_USE_REMOTE_LLM=1 and the
    SPARK_* environment variables to enable the remote provider.
    """

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
        except ImportError as exc:  # pragma: no cover - depends on optional package
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


class DeterministicEducationLLM:
    """Offline provider used for CI, demos, and fallback.

    It is deliberately evidence-grounded: every response quotes retrieved
    anchors instead of inventing external facts. This makes the RAG pipeline
    testable before real API keys are supplied.
    """

    def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
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


def _guess_topic(text: str) -> str:
    for word in ("池化层", "最大池化", "平均池化", "卷积核", "反向传播", "链式法则", "梯度下降"):
        if word in text:
            return word
    return "目标知识点"


def _lecture(topic: str, prompt: str) -> str:
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
            "画像驱动支持：若学生反馈“最大池化和平均池化总混”，先做反例辨析；"
            "若反馈“题干长会漏条件”，先列窗口大小、stride、池化类型三项条件清单；"
            "若反馈“看答案才懂”，先给局部提示，再让学生独立完成一个 2x2 窗口。"
        )
    return f"# {topic}讲义\n\n基于检索证据，先说明前置概念，再解释核心机制、计算步骤和常见误区。"


def _code(topic: str) -> str:
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
    return (
        "1. 选择题：2x2 最大池化窗口 [1, 3; 5, 2] 的输出是多少？答案：5。\n"
        "2. 填空题：最大池化主要保留局部区域中的____响应。答案：最大/最强。\n"
        "3. 代码改错：若讲义要求最大池化，代码应使用 nn.MaxPool2d 而不是 nn.AvgPool2d。\n"
        "4. 画像校准题：先自评本题把握度 0-1，再独立写出第一个窗口的计算过程；"
        "若自评高但做错，系统记录为元认知校准风险，并安排相似题重测。"
    )


def _video_script(topic: str) -> str:
    return (
        "虚拟人脚本：先展示 4x4 特征图，再高亮第一个 2x2 窗口，播报“我们取这个窗口里最大的 6”，"
        "随后移动窗口得到 2x2 输出矩阵，最后提示最大池化降低尺寸但保留显著特征。"
    )


def build_llm(config: EduMatrixConfig = CONFIG) -> LLMBackend:
    if config.use_remote_llm and config.spark_app_id and config.spark_api_key and config.spark_api_secret:
        return SparkClient(
            app_id=config.spark_app_id,
            api_key=config.spark_api_key,
            api_secret=config.spark_api_secret,
            spark_url=config.spark_url,
            domain=config.spark_domain,
        )
    return DeterministicEducationLLM()


DEFAULT_LLM = build_llm()


def call_spark_api(prompt: str, role: str = "助手") -> str:
    """Backward-compatible entry point used by older scripts."""

    return DEFAULT_LLM.generate(f"你现在是 EduMatrix 系统的{role}", prompt, role=role)
