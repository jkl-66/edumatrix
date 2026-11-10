"""Shared, audited academic-intent classification for legacy AI entry points."""

from __future__ import annotations

from typing import Any, Callable, Literal

from pydantic import Field, model_validator

from app.m2_contracts import StrictModel
from app.m5_capabilities import Capability, CapabilityContract
from app.m5_gateway import GatewayRequest, M5ModelGateway, PromptSpec
from app.m5_policy import ModelRegistration
from config import CONFIG
from llm_client import for_answer_step


class IntentClassification(StrictModel):
    is_academic: bool
    reason: str = Field(min_length=1, max_length=1000)
    reply: str = Field(max_length=4000)
    question_kind: Literal["lookup", "learner_lookup", "explanation", "practice", "reasoning", "conversation"] | None = None

    @model_validator(mode="after")
    def validate_reply_contract(self) -> "IntentClassification":
        if self.is_academic and self.reply.strip():
            raise ValueError("academic intent must not include a redirect reply")
        if not self.is_academic and not self.reply.startswith("## 智能答疑 / 系统说明\n\n"):
            raise ValueError("non-academic intent must include the governed redirect heading")
        return self


INTENT_SYSTEM_PROMPT = (
    "你是一个学习意图分类器。is_academic包括任何领域的知识或技能学习、实际问题求解和此教学系统的使用说明，"
    "例如摄影、经营管理、语言、手工、自然科学和编程；不限于高校课程或计算机专业。\n"
    "如果输入仅仅是打招呼（如“你好”、“hello”），但在后续可能引发学术问题，也可以归为学术；纯粹个人情况或系统无关闲聊判定为非学术。\n"
    "只输出包含四个字段的 JSON 对象：is_academic 为布尔值，reason 为一句分类理由，reply，question_kind。"
    "非学术 reply 必须以 '## 智能答疑 / 系统说明\\n\\n' 开头，学术 reply 必须为空串。"
    "question_kind 必须给出：lookup表示查材料名称/位置/明确事实；learner_lookup表示只查询学习者已确认的时间、偏好或安排，不涉及学科讲解；"
    "explanation表示常规概念、简短示例、复述与已知步骤解释；"
    "practice表示本次明确要求用已知常规方法设计让学习者亲自完成的小练习、对比实验或实操，需要安排题设、操作和检查方法；"
    "即使同时查询个人时间或解释简单概念，要求新设计这种小任务仍用practice。"
    "reasoning表示需新推导证明、多步计算、复杂代码排错、算法设计或多条件判断；conversation表示闲聊或寒暄。"
    "练习设计若还需要新推导、复杂算法设计或多条件方案权衡，优先reasoning，不因要求动手就降低推理深度。"
    "按实际任务分类，不按领域分类：仅查询已有安排后解释一个已知例子属于explanation，"
    "只问定义或要求举例不等于practice；不因历史问题做过练习而给本次普通问答加任务。"
    "解释一个常见运算或修正短代码的单一语义错误也属于explanation；"
    "只有需要独立推导、复杂逻辑排查或方案权衡时才用reasoning。"
    "历史和选中材料只用于消解本次追问，不能把上一题的难度当成本题难度。不能确定时用reasoning。只分类，不回答或展开分析。"
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
            backend=for_answer_step(llm, deep_reasoning=False),
            response_model=IntentClassification,
        )
        output = result.structured_output or {
            "is_academic": True, "reason": "empty result", "reply": "",
        }
        if output.get("question_kind") is None:
            output.pop("question_kind", None)
        return output
    except Exception:
        return {"is_academic": True, "reason": "分类器异常放行", "reply": ""}
    finally:
        session.close()
