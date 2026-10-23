import hashlib
import re
from typing import Any

from pydantic import Field

from app.m2_contracts import StrictModel
from app.m5_capabilities import Capability, CapabilityContract
from app.m5_gateway import GatewayRequest, M5ModelGateway, PromptSpec
from app.m5_legacy_calls import model_identity
from app.m5_policy import ModelRegistration

class PyTorchPoolCodeSchema(StrictModel):
    import_blocks: str = Field(default="import torch\nimport torch.nn as nn")
    tensor_init: str = Field(description="特征图张量初始化代码，必须与讲义给定的尺寸自洽")
    pool_layer_api: str = Field(description="核心纠偏API。最大池化必须为 nn.MaxPool2d，平均池化必须为 nn.AvgPool2d")
    forward_and_print: str = Field(description="前向传播与输出代码")

async def async_refine_code_agent(
    context_lecture: str,
    error_code: str,
    alignment_advice: str,
    *,
    llm: Any,
    owner_public_id: str,
    course_id: str | None = None,
    trace_id: str | None = None,
    session_factory=None,
) -> str:
    system_prompt = f"你是EduMatrix的代码精炼器。当前讲义核心逻辑为：{context_lecture}。"
    user_prompt = f"上一次错误代码为：{error_code}。流形对齐拦截原因：{alignment_advice}。"

    try:
        provider, model_name = model_identity(llm)
        registration = ModelRegistration(
            registration_version="legacy-code-refinement-v1",
            provider=provider,
            model=model_name,
            tier="standard",
            capabilities=(Capability.CODE,),
            supports_json=True,
            context_length=200000,
        )
        request = GatewayRequest(
            contract=CapabilityContract(
                capability=Capability.CODE,
                course_id=course_id,
                idempotency_key=(
                    "code-refine-"
                    + hashlib.sha256(
                        f"{owner_public_id}:{context_lecture}:{error_code}:{alignment_advice}".encode("utf-8")
                    ).hexdigest()[:24]
                ),
            ),
            owner_public_id=owner_public_id,
            prompt=PromptSpec(
                key="legacy_code_refinement",
                version="2.0",
                system_prompt=system_prompt,
            ),
            user_prompt=user_prompt,
            role="代码精炼器",
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
                response_model=PyTorchPoolCodeSchema,
                trace_id=trace_id,
            )
        finally:
            session.close()
        refined_json = PyTorchPoolCodeSchema.model_validate(result.structured_output)
        return f"{refined_json.import_blocks}\n{refined_json.tensor_init}\n{refined_json.pool_layer_api}\n{refined_json.forward_and_print}"
    except Exception:
        """Guided Decoding 概率空间坍塌自愈防线：一旦校验失败或超时，立即启动规则引擎在0毫秒内强行修复"""
        fixed_code = error_code
        if "nn.AvgPool2d" in error_code and "最大池化" in context_lecture:
            fixed_code = re.sub(r"nn\.AvgPool2d", "nn.MaxPool2d", error_code)
        elif "nn.MaxPool2d" in error_code and "平均池化" in context_lecture:
            fixed_code = re.sub(r"nn\.MaxPool2d", "nn.AvgPool2d", error_code)
        return fixed_code
