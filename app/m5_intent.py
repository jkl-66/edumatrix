"""Shared, audited academic-intent classification for legacy AI entry points."""

from __future__ import annotations

from typing import Any, Callable

from pydantic import Field, model_validator

from app.m2_contracts import StrictModel
from app.m5_capabilities import Capability, CapabilityContract
from app.m5_gateway import GatewayRequest, M5ModelGateway, PromptSpec
from app.m5_policy import ModelRegistration
from config import CONFIG


class IntentClassification(StrictModel):
    is_academic: bool
    reason: str = Field(min_length=1, max_length=1000)
    reply: str = Field(max_length=4000)

    @model_validator(mode="after")
    def validate_reply_contract(self) -> "IntentClassification":
        if self.is_academic and self.reply.strip():
            raise ValueError("academic intent must not include a redirect reply")
        if not self.is_academic and not self.reply.startswith("## 智能答疑 / 系统说明\n\n"):
            raise ValueError("non-academic intent must include the governed redirect heading")
        return self


INTENT_SYSTEM_PROMPT = (
    "你是一个意图分类器。你需要判断用户输入的问题是否与学术学习、机器学习、数据科学、数学、人工智能、编程、计算机科学或此教学系统的使用说明相关。\n"
    "如果输入仅仅是打招呼（如“你好”、“hello”），但在后续可能引发学术问题，也可以归为学术；纯粹个人情况或系统无关闲聊判定为非学术。\n"
    "只输出 JSON：is_academic 为布尔值，reason 为分类理由；非学术 reply 必须以 '## 智能答疑 / 系统说明\\n\\n' 开头，学术 reply 必须为空串。"
)


async def classify_academic_intent(
    llm: Any,
    message: str,
    *,
    owner_public_id: str | None = None,
    course_id: str | None = None,
    session_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    user_prompt = f'用户输入: "{message}"'
    provider = "deterministic" if llm.__class__.__name__ == "AsyncDeterministicEducationLLM" else CONFIG.llm_provider
    model = getattr(llm, "model", "deterministic" if provider == "deterministic" else CONFIG.llm_model)
    registration = ModelRegistration(
        registration_version="legacy-intent-v1",
        provider=provider or "unknown",
        model=model or "unknown",
        tier="fast",
        capabilities=(Capability.ANSWER,),
        supports_json=True,
        context_length=max(1, CONFIG.llm_max_tokens),
    )
    request = GatewayRequest(
        contract=CapabilityContract(
            capability=Capability.ANSWER,
            course_id=course_id,
            idempotency_key=f"intent-{__import__('hashlib').sha256(message.encode('utf-8')).hexdigest()[:24]}",
        ),
        owner_public_id=owner_public_id,
        prompt=PromptSpec(
            key="legacy_intent_classification",
            version="1.0",
            system_prompt=INTENT_SYSTEM_PROMPT,
        ),
        user_prompt=user_prompt,
        role="意图分类",
    )
    if session_factory is None:
        from app.database import SessionLocal
        session_factory = SessionLocal
    session = session_factory()
    try:
        result = await M5ModelGateway().execute(
            session,
            request=request,
            registration=registration,
            backend=llm,
            response_model=IntentClassification,
        )
        return result.structured_output or {
            "is_academic": True, "reason": "empty result", "reply": "",
        }
    except Exception:
        return {"is_academic": True, "reason": "分类器异常放行", "reply": ""}
    finally:
        session.close()
