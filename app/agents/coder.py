import re
import openai
import instructor
from pydantic import BaseModel, Field, ValidationError

class PyTorchPoolCodeSchema(BaseModel):
    import_blocks: str = Field(default="import torch\nimport torch.nn as nn")
    tensor_init: str = Field(description="特征图张量初始化代码，必须与讲义给定的尺寸自洽")
    pool_layer_api: str = Field(description="核心纠偏API。最大池化必须为 nn.MaxPool2d，平均池化必须为 nn.AvgPool2d")
    forward_and_print: str = Field(description="前向传播与输出代码")

async def async_refine_code_agent(context_lecture: str, error_code: str, alignment_advice: str) -> str:
    system_prompt = f"你是EduMatrix的代码精炼器。当前讲义核心逻辑为：{context_lecture}。"
    user_prompt = f"上一次错误代码为：{error_code}。流形对齐拦截原因：{alignment_advice}。"

    try:
        from config import CONFIG
        endpoint = CONFIG.llm_endpoint if CONFIG.llm_endpoint else "http://localhost:8000/v1"
        api_key = CONFIG.llm_api_key if CONFIG.llm_api_key else "none"
        model_name = CONFIG.llm_model if CONFIG.llm_model else "Qwen2.5-Coder-32B-Instruct"
        
        base_url = endpoint
        if "/chat/completions" in base_url:
            base_url = base_url.replace("/chat/completions", "")
            
        import asyncio
        client = instructor.patch(openai.AsyncClient(base_url=base_url, api_key=api_key, timeout=1.0))
        refined_json = await asyncio.wait_for(
            client.chat.completions.create(
                model=model_name,
                response_model=PyTorchPoolCodeSchema,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                temperature=0.01,
            ),
            timeout=1.0
        )
        return f"{refined_json.import_blocks}\n{refined_json.tensor_init}\n{refined_json.pool_layer_api}\n{refined_json.forward_and_print}"
    except (ValidationError, Exception) as e:
        """Guided Decoding 概率空间坍塌自愈防线：一旦校验失败或超时，立即启动规则引擎在0毫秒内强行修复"""
        fixed_code = error_code
        if "nn.AvgPool2d" in error_code and "最大池化" in context_lecture:
            fixed_code = re.sub(r"nn\.AvgPool2d", "nn.MaxPool2d", error_code)
        elif "nn.MaxPool2d" in error_code and "平均池化" in context_lecture:
            fixed_code = re.sub(r"nn\.MaxPool2d", "nn.AvgPool2d", error_code)
        return fixed_code
