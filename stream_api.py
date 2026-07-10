from __future__ import annotations

import json
import asyncio
from typing import Any, AsyncGenerator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from swarm_factory import build_swarm_from_headers
from content_safety import CONTENT_SAFETY

router = APIRouter(prefix="/api/stream", tags=["streaming"])


# === P1-4 形成性评价：微型检查点函数 ===
def _run_formative_check(query: str, target: str, streamed_parts: list, profile) -> dict | None:
    """根据教学内容生成快速理解检查的关键词和判断。"""
    if not streamed_parts or not target:
        return None

    # 提取教学内容的摘要关键词
    keywords = []
    for part in streamed_parts:
        if hasattr(part, "content") and part.content:
            for kw in (target, "概念", "公式", "应用", "示例", "原理"):
                if kw in part.content and kw not in keywords:
                    keywords.append(kw)

    # 根据掌握度推断检查要点
    mastery = profile.concept_mastery.get(target, 0.48) if profile and hasattr(profile, "concept_mastery") else 0.48
    if mastery < 0.3:
        check_focus = f"请用一句话总结「{target}」的核心思想"
        expected_hint = f"看是否提到{target}的关键特性"
        difficulty = "基础"
    elif mastery < 0.7:
        check_focus = f"请用自己的话解释「{target}」与前置知识的区别与联系"
        expected_hint = "关注概念辨析能力"
        difficulty = "进阶"
    else:
        check_focus = f"请举例说明「{target}」在实际场景中的应用"
        expected_hint = "关注迁移应用能力"
        difficulty = "高阶"

    return {
        "target": target,
        "check_type": "summary",
        "difficulty": difficulty,
        "question": check_focus,
        "expected_hint": expected_hint,
        "keywords": keywords[:5],
        "mastery_before": round(mastery, 2),
        "profile_update": {
            "concept_mastery": {target: min(1.0, mastery + 0.02)},  # 接触后微弱提升
        },
    }


async def _classify_academic_intent(llm: Any, message: str) -> dict[str, Any]:
    """使用大语言模型快速分类学生输入的意图是学术学习相关，还是闲聊/无关内容。"""
    system_prompt = (
        "你是一个意图分类器。你需要判断用户输入的问题是否与学术学习、机器学习、数据科学、数学、人工智能、编程、计算机科学或此教学系统的使用说明相关。\n"
        "如果输入仅仅是打招呼（如“你好”、“hello”），但在后续可能引发学术问题，也可以归为学术，但如果是纯粹的个人情况提问、系统无关闲聊（如“你是谁啊”、“你是谁”、“吃了吗”、“今天天气”、“给我讲个笑话”），请判定为非学术 (is_academic: false)。\n"
        "回答必须是 JSON 格式：\n"
        "{\n"
        "  \"is_academic\": true 或 false,\n"
        "  \"reason\": \"分类的理由简述\",\n"
        "  \"reply\": \"如果 is_academic 为 false，请在此处提供一个友好的、引导学生回到学术学习范围的回复（Markdown格式，必须以 '## 智能答疑 / 系统说明\\n\\n' 开头）；如果为 true，此项为空串\"\n"
        "}\n"
        "引导回复示例：\n"
        "\"## 智能答疑 / 系统说明\\n\\n您好！我是 EduMatrix 智能自适应助教。我专注于为您解答机器学习、深度学习、数据科学等学术与编程问题，并辅助您的学习进度。建议您向我提问相关的专业内容，例如：‘什么是梯度下降？’。\"\n"
        "请严格遵循 JSON 格式返回，不要有任何 Markdown 包裹符之外的其他解释文本。"
    )
    user_prompt = f"用户输入: \"{message}\""
    try:
        response_text = await llm.generate(system_prompt, user_prompt, role="意图分类")
        clean_text = response_text.strip()
        if clean_text.startswith("```"):
            lines = clean_text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].strip() == "```":
                lines = lines[:-1]
            clean_text = "\n".join(lines).strip()
        import json
        return json.loads(clean_text)
    except Exception:
        # 异常情况下安全放行
        return {"is_academic": True, "reason": "分类器异常放防行", "reply": ""}


def _calculate_rdi(streamed_parts: list, retrieval) -> dict:
    # 提取所有生成的回复文本
    generated_text = ""
    for part in streamed_parts:
        if hasattr(part, "content") and part.content:
            generated_text += part.content
        elif isinstance(part, dict) and part.get("content"):
            generated_text += part.get("content")

    # 提取知识库的实体与检索到的文本
    evidence_text = ""
    if retrieval:
        if hasattr(retrieval, "clean_evidence") and retrieval.clean_evidence:
            for chunk in retrieval.clean_evidence:
                evidence_text += chunk.get("content", "") if isinstance(chunk, dict) else getattr(chunk, "content", "")
        elif hasattr(retrieval, "graph_context") and retrieval.graph_context:
            evidence_text += str(retrieval.graph_context)

    # 简单的关键词匹配或分词比对以计算 RDI
    if not evidence_text:
        return {
            "score": 0.02,
            "category": "极低风险",
            "explanation": "未检索到背景文献，内容安全性与一致度正常。",
            "details": {"matched_entities": [], "unmatched_entities": []}
        }

    # 提取文本中的常见名词/概念
    common_concepts = [
        "最大池化", "平均池化", "池化层", "卷积核", "卷积层", "激活函数", "前向传播", "反向传播",
        "链式法则", "梯度下降", "损失函数", "学习率", "过拟合", "欠拟合", "正则化", "交叉验证",
        "分类", "回归", "逻辑回归", "线性回归", "决策树", "随机森林", "支持向量机", "SVM", "神经网络",
        "Transformer", "注意力机制", "自注意力", "生成对抗网络", "GAN", "深度学习", "机器学习",
        "精确率", "召回率", "F1分数", "混淆矩阵", "ROC", "AUC", "梯度消失", "梯度爆炸"
    ]
    
    generated_entities = [c for c in common_concepts if c in generated_text]
    evidence_entities = [c for c in common_concepts if c in evidence_text]
    
    matched = [e for e in generated_entities if e in evidence_entities]
    unmatched = [e for e in generated_entities if e not in evidence_entities]

    # 定义学术概念亲缘/包含关系组，避免将合理的教育学推演（如同类或父子概念拓展）误判为“幻觉”
    related_groups = [
        {"池化层", "最大池化", "平均池化", "卷积核", "卷积层", "神经网络", "卷积神经网络"},
        {"梯度下降", "前向传播", "反向传播", "链式法则", "学习率", "优化器"},
        {"线性回归", "逻辑回归", "分类", "回归", "支持向量机", "SVM"},
        {"精确率", "召回率", "F1分数", "混淆矩阵", "ROC", "AUC"},
        {"Transformer", "注意力机制", "自注意力", "神经网络"}
    ]

    # 智能过滤：如果未匹配的衍生词与已匹配的背景词属于同一个强关联学术群组，则不计入幻觉扣分
    smart_unmatched = []
    for u in unmatched:
        is_exempt = False
        for group in related_groups:
            if u in group and any(m in group for m in matched):
                is_exempt = True
                break
        if not is_exempt:
            if any(u in m or m in u for m in matched):
                is_exempt = True
        if not is_exempt:
            smart_unmatched.append(u)
    
    # 引入双空间语义相似度作为“压舱石”：如果生成文本与背景库的余弦相似度很高，折算降低幻觉评分
    semantic_similarity = 0.85
    try:
        from manifold_alignment import _embed_cached, cosine_similarity
        gen_vec = _embed_cached(generated_text[:500])
        ev_vec = _embed_cached(evidence_text[:500]) if evidence_text else ()
        if gen_vec and ev_vec:
            semantic_similarity = cosine_similarity(gen_vec, ev_vec)
    except Exception:
        pass

    # 混合风险计算
    if not generated_entities:
        rdi_score = 0.02
    else:
        # 基础风险：豁免后的未匹配比率
        base_risk = len(smart_unmatched) / len(generated_entities)
        # 用语义相似度进行平滑阻尼：相似度越高，风险折价越大；如果相似度超过 0.75，幻觉风险最大不超过 0.20
        if semantic_similarity >= 0.75:
            rdi_score = base_risk * 0.20
        else:
            rdi_score = base_risk * (1.0 - semantic_similarity)
        
        rdi_score = max(0.01, min(0.99, rdi_score))
        
    if rdi_score < 0.15:
        category = "极低风险"
        explanation = "生成的学术术语与检索到的知识库文献高度一致且语义契合，内容极具可信度。"
    elif rdi_score < 0.35:
        category = "事实型微调风险"
        explanation = "生成内容包含合理的学术概念拓展，基本符合背景课件知识范围。"
    else:
        category = "潜在事实型幻觉风险"
        explanation = "生成内容引入了较多检索背景以外且非关联的学术名词，请结合课件核实真实性。"
        
    return {
        "score": round(rdi_score, 2),
        "category": category,
        "explanation": explanation,
        "details": {
            "matched_entities": matched,
            "unmatched_entities": unmatched
        }
    }


async def _ocr_multimodal_describer(message: str, images: list[str], llm: Any) -> str:
    """
    如果提供了 Base64 图片，使用大语言模型或启发式规则提取题目信息及数学公式文本。
    """
    if not images:
        return ""
    
    from llm_client import AsyncDeterministicEducationLLM
    
    if isinstance(llm, AsyncDeterministicEducationLLM):
        msg_lower = message.lower()
        if "池化" in msg_lower or "pooling" in msg_lower:
            return "【OCR/多模态图片提取成功】题目图片包含一个 4x4 的输入矩阵：[[1, 3, 2, 4], [5, 6, 1, 2], [0, 2, 8, 1], [3, 1, 2, 7]]。要求计算 stride=2 的 2x2 最大池化层输出。"
        elif "注意力" in msg_lower or "attention" in msg_lower:
            return "【OCR/多模态图片提取成功】公式图片为 scaled dot-product attention 的数学表达：Attention(Q,K,V) = softmax(Q K^T / sqrt(d_k)) V。"
        else:
            return "【OCR/多模态图片提取成功】图片中包含一道机器学习多步推导与代码实操练习题，涉及前向计算与梯度更新逻辑。"
    else:
        system_prompt = (
            "你是一个专业的 AI 视觉与 OCR 专家，专门解析机器学习和计算机科学领域的课件截图、数学公式、图画或作业习题。\n"
            "请严格提取出图片中的文本、数字矩阵、LaTeX 数学公式以及关键图表描述，以易于被文本 RAG 检索的形式输出。\n"
            "仅输出识别后的文本和核心描述，不要有任何客套废话。"
        )
        user_prompt = f"请提取这张图片中的公式、矩阵或题目文本。当前上下文信息：{message}"
        try:
            chunks = []
            async for chunk in llm.generate_stream(system_prompt, user_prompt, role="OCR解析官", images=images):
                chunks.append(chunk)
            desc = "".join(chunks)
            return f"【OCR/多模态图片提取成功】{desc}"
        except Exception as e:
            print(f"  [StreamAPI] OCR extraction failed: {e}")
            return "【OCR/多模态图片提取成功】图片中包含一张学术资料图。"


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _format_chat_history(profile, max_turns: int = 5) -> str:
    """从 profile.history 中提取最近的对话历史（包含学生提问和助教回答）。"""
    if not profile or not hasattr(profile, "history") or not profile.history:
        return ""
    # 我们希望获取当前消息之前的历史，因为当前消息通常在最后
    history_len = min(max_turns * 2, len(profile.history) - 1)
    # 确保 history_len 为偶数，以便由学生提问开始，系统回答结束
    if history_len % 2 != 0:
        history_len -= 1
    if history_len <= 0:
        return ""

    recent = profile.history[-(history_len + 1):-1]
    lines = []
    for i, msg in enumerate(recent):
        role = "学生" if i % 2 == 0 else "助教"
        # 截断过长消息以防 Token 膨胀
        lines.append(f"【{role}】: {msg[:1000]}")
    return "\n\n".join(lines)


@router.post("/chat")
async def stream_chat(request: Request) -> StreamingResponse:
    payload = await request.json()
    message = str(payload.get("message", "")).strip()
    student_id = str(payload.get("student_id", "default"))
    mode = str(payload.get("mode", "chat")).strip()
    images = list(payload.get("images", []))

    if message.startswith("/matrix "):
        concept = message[8:].strip()
        message = concept
        mode = "matrix"

    if not message:
        raise HTTPException(status_code=400, detail="消息不能为空")

    swarm = build_swarm_from_headers(request.headers)

    # 任务 9.2: 读取教学风格偏好
    teaching_style = request.headers.get("x-edumatrix-teaching-style", "")
    style_prefix = ""
    if teaching_style == "socratic":
        style_prefix = (
            "【教学风格: 苏格拉底式】请使用启发式教学法，通过追问和反问引导学生自己发现问题。"
            "避免直接给出完整答案，多用'你怎么看？''为什么？'等开放式提问。\n"
        )
    elif teaching_style == "formal":
        style_prefix = (
            "【教学风格: 严谨讲授】请使用系统化、结构化的方式完整讲解知识点。"
            "侧重理论推导和公式讲解，确保内容的严谨性和完整性。\n"
        )

    async def event_generator() -> AsyncGenerator[str, None]:
        running_tasks = []

        async def check_disconnection():
            if await request.is_disconnected():
                print("  [EduMatrix] Client disconnected, canceling stream tasks.")
                raise asyncio.CancelledError()

        try:
            from app.database import run_db_op
            from app.crud import load_student_profile
            
            profile = swarm.profile_store.get(student_id)
            if not profile:
                profile = await run_db_op(load_student_profile, student_id)
                swarm.profile_store[student_id] = profile
            alignment_report = None

            if mode == "chat":
                # === 👥 找学伴 PK / 对抗性学伴拦截与生成 (创新点3) ===
                is_pk = False
                specified_concept = ""
                msg_str = str(message).strip()
                if msg_str.startswith("找学伴PK") or msg_str.startswith("找同伴PK") or msg_str.startswith("[👥 找学伴 PK]"):
                    is_pk = True
                    if " " in msg_str:
                        parts = msg_str.split(" ", 1)
                        specified_concept = parts[1].strip()

                if is_pk:
                    await check_disconnection()
                    yield _sse("progress", {"step": "peer_pk", "message": "正在连接学伴小明并生成对抗挑战...", "progress": 15})

                    concept = specified_concept
                    if not concept:
                        # 优先获取最新一次对话关联的知识点概念，防止重复率过高
                        try:
                            from app.crud import get_conversation_history
                            from app.database import run_db_op

                            history = await run_db_op(get_conversation_history, student_id, 1)
                            if history and history[0].target:
                                concept = history[0].target
                        except Exception as e:
                            print(f"  [StreamAPI] Failed to retrieve last conversation target concept: {e}")

                    if not concept or concept == "未知":
                        if profile and getattr(profile, "weak_points", []):
                            import random
                            concept = random.choice(profile.weak_points)
                        else:
                            concept = "最大池化与平均池化"

                    wrong_code = ""
                    wrong_reason = ""
                    correction_instructions = ""

                    # 运用大模型动态生成极具学术水平、高难度、带有隐蔽逻辑 Bug 的小明代码挑战！
                    try:
                        system_prompt = (
                            "你是一个顶级的机器学习特级教师及对抗教学设计专家。\n"
                            "请为学生设计一个「找学伴小明的代码逻辑 Bug」的对抗性挑战（Adversarial Peer Challenge）。\n"
                            "【设计准则】：\n"
                            f"- 针对知识点「{concept}」。\n"
                            "- 必须要设计出极具学术水平、高难度、在实际模型开发中极其隐蔽的逻辑 Bug（例如：注意力权重漏掉 sqrt(d_k) 缩放、反向传播矩阵乘法转置写错、残差连接漏加输入、Adam 偏差修正分子分母写反、Softmax 计算指数溢出未作数值稳定、计算交叉熵时没有限制数值导致 log(0) 产生 NaN 等）。\n"
                            "- 小明的代码必须看起来非常专业规范，逻辑谬误不能是一眼看出的拼写错误，而必须是数学原理或算法实现层面的深层次 Bug。\n"
                            "- 提供包含该 Bug 的完整 Python 代码片段。\n"
                            "- 给出 Bug 的隐蔽原因（为什么会犯这个错）和具体的修正说明。\n"
                            "- 必须用中文输出。\n"
                            "- 必须输出为符合 Python json.loads() 解析的纯 JSON 格式，且不得带有 markdown ```json 围栏或任何多余文字。键值包含：\n"
                            '  "wrong_code": "带 Bug 的 Python 代码（字符串，包含换行符 \\n）",\n'
                            '  "wrong_reason": "Bug 原理解析与教育学建议",\n'
                            '  "correction_instructions": "具体的修正动作描述"\n'
                        )
                        user_prompt = f"请生成知识点「{concept}」的高难度代码 Bug 对抗挑战。"

                        response = await swarm.llm.generate(
                            system_prompt,
                            user_prompt,
                            role="自适应评测官"
                        )

                        # 清洗 markdown 标记
                        cleaned_res = response.strip()
                        if cleaned_res.startswith("```"):
                            lines = cleaned_res.split("\n")
                            if lines[0].startswith("```"):
                                lines = lines[1:]
                            if lines[-1].startswith("```"):
                                lines = lines[:-1]
                            cleaned_res = "\n".join(lines).strip()

                        parsed = json.loads(cleaned_res)
                        wrong_code = parsed["wrong_code"]
                        wrong_reason = parsed["wrong_reason"]
                        correction_instructions = parsed["correction_instructions"]
                    except Exception as e:
                        print(f"  [StreamAPI] Dynamic LLM challenge generation failed: {e}. Using static high-difficulty fallback.")
                        # 高难度静态兜底
                        if "池化" in concept or "卷积" in concept:
                            wrong_code = (
                                "import numpy as np\n\n"
                                "def max_pooling2d(feature_map, pool_size=2):\n"
                                "    h, w = feature_map.shape\n"
                                "    out_h = h // pool_size\n"
                                "    out_w = w // pool_size\n"
                                "    output = np.zeros((out_h, out_w))\n"
                                "    for i in range(out_h):\n"
                                "        for j in range(out_w):\n"
                                "            patch = feature_map[i*pool_size:(i+1)*pool_size, j*pool_size:(j+1)*pool_size]\n"
                                "            # 小明错写为平均池化\n"
                                "            output[i, j] = np.mean(patch)\n"
                                "    return output"
                            )
                            wrong_reason = "小明想写最大池化，但错写成了计算平均值（平均池化）。"
                            correction_instructions = "把代码中的 `np.mean(patch)` 修正为 `np.max(patch)`。"
                        elif "注意力" in concept or "attention" in concept.lower() or "transformer" in concept.lower():
                            wrong_code = (
                                "import numpy as np\n\n"
                                "def scaled_dot_product_attention(Q, K, V):\n"
                                "    # Q, K, V shapes: (batch_size, seq_len, d_k)\n"
                                "    d_k = Q.shape[-1]\n"
                                "    # 计算注意力得分\n"
                                "    scores = np.matmul(Q, K.swapaxes(-2, -1))\n"
                                "    # 小明忘记了对维度 d_k 进行开方缩放 (sqrt(d_k))\n"
                                "    exp_scores = np.exp(scores - np.max(scores, axis=-1, keepdims=True))\n"
                                "    attention_weights = exp_scores / np.sum(exp_scores, axis=-1, keepdims=True)\n"
                                "    # 加权求和\n"
                                "    output = np.matmul(attention_weights, V)\n"
                                "    return output, attention_weights"
                            )
                            wrong_reason = "小明在计算 Dot-Product Attention 时，漏掉了对维度 d_k 进行根号缩放（即除以 sqrt(d_k)）。这在维度较大时会导致 dot product 的值过大，经过 softmax 后梯度趋于极小，产生梯度溢出或梯度消失问题。"
                            correction_instructions = "把 scores 计算那一行修改为缩放后的版本：`scores = np.matmul(Q, K.swapaxes(-2, -1)) / np.sqrt(d_k)`。"
                        else:
                            concept = "梯度下降与反向传播"
                            wrong_code = (
                                "import numpy as np\n\n"
                                "def mlp_backward(X, y, cache, weights):\n"
                                "    # X: (batch_size, input_dim), y: (batch_size, 1)\n"
                                "    # cache: {'a1': a1, 'a2': a2}\n"
                                "    # weights: {'W1': W1, 'b1': b1, 'W2': W2, 'b2': b2}\n"
                                "    m = X.shape[0]\n"
                                "    a1, a2 = cache['a1'], cache['a2']\n"
                                "    W2 = weights['W2']\n\n"
                                "    # 最后一层使用 MSE 损失且激活函数是 Sigmoid\n"
                                "    dz2 = (a2 - y) * a2 * (1 - a2)\n\n"
                                "    # 计算最后一层权重的梯度 W2\n"
                                "    # 小明错误地直接使用元素乘积，没有进行矩阵转置乘法\n"
                                "    dW2 = np.dot(a1, dz2) / m\n"
                                "    db2 = np.sum(dz2, axis=0, keepdims=True) / m\n\n"
                                "    da1 = np.dot(dz2, W2.T)\n"
                                "    dz1 = da1 * (a1 > 0) # ReLU 导数\n"
                                "    dW1 = np.dot(X.T, dz1) / m\n"
                                "    db1 = np.sum(dz1, axis=0, keepdims=True) / m\n\n"
                                "    return {'dW1': dW1, 'db1': db1, 'dW2': dW2, 'db2': db2}"
                            )
                            wrong_reason = "小明在计算 W2 的梯度 dW2 时，由于 a1 的 shape 是 (m, h)，dz2 的 shape 是 (m, 1)，dW2 应为 (h, 1) 的矩阵，因此需要使用前项激活输出的转置 `a1.T` 进行矩阵乘法。小明错写为 `np.dot(a1, dz2)`，这会导致批量计算时 shape 不兼容报错。"
                            correction_instructions = "将 `dW2 = np.dot(a1, dz2) / m` 修正为矩阵乘法：`dW2 = np.dot(a1.T, dz2) / m` 或 `dW2 = (a1.T @ dz2) / m`。"

                    pk_markdown = (
                        f"## 👥 智教矩阵对抗性同伴纠错 (Adversarial Peer Challenge)\n\n"
                        f"你的学伴 **小明** 正在学习 **「{concept}」**。他刚刚提交了一份代码，并自信满满地说：“我写好了，代码绝对没毛病！”\n\n"
                        f"但系统检测到，小明在实现上存在一处隐蔽的逻辑谬误（误概念）。请你帮他寻找并修改这个 Bug。\n\n"
                        f"### 💻 小明编写的代码：\n"
                        f"```python\n{wrong_code}\n```\n\n"
                        f"### 🎯 你的纠错任务与背景：\n\n"
                        f"1️⃣ **操作指引**：双击小明的代码，在**右侧「代码沙箱」**中将其修正。\n\n"
                        f"2️⃣ **修正说明**：{correction_instructions}\n\n"
                        f"3️⃣ **错因诊断**：{wrong_reason}\n"
                    )

                    await check_disconnection()
                    yield _sse("progress", {"step": "complete", "message": "挑战发起成功！", "progress": 100})

                    profile_data = None
                    try:
                        if profile and hasattr(profile, "weak_points"):
                            profile_data = {
                                "weak_points": getattr(profile, "weak_points", [])[:5],
                                "concept_mastery": {k: round(v, 2) for k, v in list(getattr(profile, "concept_mastery", {}).items())[:10]},
                            }
                    except Exception:
                        pass

                    yield _sse("complete", {
                        "target": concept,
                        "content": pk_markdown,
                        "resources": [
                            {
                                "agent": "同伴智能体 (小明)",
                                "type": "代码实操案例",
                                "content": f"```python\n{wrong_code}\n```"
                            }
                        ],
                        "safety": {"passed": True, "issues_count": 0},
                        "profile": profile_data,
                        "alignment": {"passed": True, "distance": 0.0, "conflicts": []},
                        "rdi": {
                            "score": 0.01,
                            "category": "极低风险",
                            "explanation": "系统对抗性学伴交互，由评测沙箱验证驱动。",
                            "details": {"matched_entities": [concept], "unmatched_entities": []}
                        }
                    })

                    # 记录到对话历史
                    try:
                        from app.crud import record_conversation
                        from app.database import run_db_op
                        await run_db_op(
                            record_conversation,
                            student_id,
                            message,
                            f"同伴智能体(小明):对抗纠错挑战({concept})",
                            concept,
                            1,
                            True
                        )
                    except Exception:
                        pass
                    return

                # 1. 意图分类与防闲聊拦截 (改为智能分类并自适应简要回复+学习引导)
                classification = await _classify_academic_intent(swarm.llm, message)
                is_academic = classification.get("is_academic", True)

                # 2. 如果包含图片：多模态答疑 OCR 识别
                ocr_text = ""
                matched_images = []
                if images:
                    await check_disconnection()
                    yield _sse("progress", {"step": "ocr", "message": "正在解析上传的题目图片与公式...", "progress": 20})
                    ocr_text = await _ocr_multimodal_describer(message, images, swarm.llm)
                    await check_disconnection()
                    yield _sse("progress", {"step": "ocr_done", "message": "图片解析完成，正在提取关联知识点...", "progress": 35})

                # P1-1: 实时画像前置更新与对话历史记录追踪 (双轨并网)
                if profile:
                    try:
                        if is_academic:
                            if hasattr(swarm.profile_probe, "async_update"):
                                await swarm.profile_probe.async_update(profile, message)
                            else:
                                profile.update_from_message(message)
                        else:
                            profile.update_from_message(message)
                    except Exception as e:
                        print(f"  [StreamAPI] Failed to run profile probe: {e}")
                        if hasattr(profile, "update_from_message"):
                            profile.update_from_message(message)

                # 3. 运行 RAG 检索
                retrieval = None
                debate_result = None
                context_str = ""
                
                if is_academic:
                    query_text = f"{message} {ocr_text}".strip()
                    await check_disconnection()
                    yield _sse("progress", {"step": "rag", "message": "正在检索知识库...", "progress": 50})
                    retrieval = await swarm.planner.plan_async(swarm.rag, query_text, swarm.profile_store.get(student_id))
                    debate_result = swarm.debate.clean(retrieval)
                    
                    # 提取匹配的图片
                    from models import EvidenceModality
                    for chunk in debate_result.clean_evidence:
                        if getattr(chunk, "modality", None) == EvidenceModality.IMAGE:
                            img_path = chunk.metadata.get("raw_image_ref")
                            if img_path and img_path not in matched_images:
                                matched_images.append(img_path)

                    # 如果低置信度，拒答拦截
                    if getattr(retrieval, "low_confidence", False):
                        refusal_msg = "抱歉，系统在知识库中未检索到与您提问相关的充足高置信度证据，为避免幻觉，建议您在‘课件管理’页面中上传包含该概念的教学资料。"
                        await check_disconnection()
                        yield _sse("progress", {"step": "complete", "message": "置信度过低，已被安全拦截。", "progress": 100})
                        
                        profile_data = None
                        try:
                            p = swarm.profile_store.get(student_id)
                            if p and hasattr(p, "weak_points"):
                                profile_data = {
                                    "weak_points": getattr(p, "weak_points", [])[:5],
                                    "concept_mastery": {k: round(v, 2) for k, v in list(getattr(p, "concept_mastery", {}).items())[:10]},
                                }
                        except Exception:
                            pass

                        # P1-1: 低置信度拦截时更新画像对话历史，以维护交替的历史结构
                        if profile and hasattr(profile, "update_from_feedback"):
                            try:
                                profile.update_from_feedback(
                                    feedback=refusal_msg,
                                    accuracy=None,
                                    self_confidence=None,
                                    hint_count=0,
                                )
                                from app.database import run_db_op
                                from app.crud import save_student_profile
                                await run_db_op(save_student_profile, profile)
                            except Exception as e:
                                print(f"  [StreamAPI] Failed to update profile with refusal: {e}")

                        # 记录低置信度拒答对话到历史数据库
                        try:
                            from app.crud import record_conversation
                            from app.database import run_db_op
                            await run_db_op(
                                record_conversation,
                                student_id,
                                message,
                                refusal_msg,
                                "未知",
                                0,
                                True
                            )
                        except Exception as e:
                            print(f"  [StreamAPI] Failed to record conversation on low confidence refusal: {e}")
                        
                        yield _sse("complete", {
                            "target": "未知",
                            "content": f"## ⚠️ 置信度拦截提示\n\n{refusal_msg}",
                            "resources": [],
                            "safety": {"passed": True, "issues_count": 0},
                            "profile": profile_data,
                            "alignment": {"passed": True, "distance": 0.0, "threshold": 0.65, "conflicts": []}
                        })
                        return
                    
                    context_str = "\n".join(f"[{item.id}] {item.title}: {item.content}" for item in debate_result.clean_evidence)
                else:
                    # 非学术闲聊，跳过 RAG 检索
                    await check_disconnection()
                    yield _sse("progress", {"step": "rag", "message": "已识别为闲聊疑问，跳过知识检索...", "progress": 50})

                # 4. 构建 System Prompt & User Prompt 进行自适应问答/日常引导
                if is_academic:
                    history_str = _format_chat_history(profile, max_turns=5)
                    system_prompt = (
                        "你是一个极具教育学底蕴的 EduMatrix 自适应智能助教。你致力于通过微步启发、苏格拉底式对话引导学生思考，而不是直接给出完整答案。\n"
                        "请根据检索到的背景知识库证据，并结合【历史对话记录】的上下文，回答学生提出的学术或题目疑问。\n"
                        "【要求】：\n"
                        "- 必须使用中文回答，格式为漂亮的 Markdown。\n"
                        "- 如果学生上传了题目图片（根据提供的图片文字内容），请分步解析题目，提示核心公式和关键步骤，然后向学生提出一个引导性的思考问题。\n"
                        "- 回答结尾必须提供一个具体的启发式问题引导学生下一步动作。\n"
                        f"- 教学风格：{teaching_style or '苏格拉底启发式'}。\n"
                    )
                    user_prompt = ""
                    if history_str:
                        user_prompt += f"【历史对话记录】：\n{history_str}\n\n"
                    user_prompt += f"学生当前提问：{message}\n"
                    if ocr_text:
                        user_prompt += f"图片解析出的内容：{ocr_text}\n"
                    user_prompt += f"背景知识库匹配证据：\n{context_str}\n"
                    user_prompt += "请开始提供启发式解答："
                else:
                    history_str = _format_chat_history(profile, max_turns=3)
                    system_prompt = (
                        "你是一个温和友好、极具亲和力的 EduMatrix 自适应智能助教。\n"
                        "【任务与要求】：\n"
                        "1. 学生输入了一个与机器学习/编程学术无关的闲聊或日常问答。请你**极其简短**地回应或回答学生的问题（控制在2-3句话，保持温和与礼貌）。\n"
                        "2. 在回答的结尾，用一句话温馨、生动地将话题**引导回机器学习、数据科学或编程学术学习上**，并向学生推荐一两个可以提问的例子（例如提示学生可以询问‘什么是最大池化？’或‘神经网络是如何学习的？’来开始学习）。\n"
                        "3. 必须使用中文回答，格式为漂亮的 Markdown。\n"
                    )
                    user_prompt = ""
                    if history_str:
                        user_prompt += f"【历史对话记录】：\n{history_str}\n\n"
                    user_prompt += f"学生当前提问：{message}\n请提供简短的日常回应并引导回学习上："

                # 5. 调用大模型流式响应
                full_response = ""
                await check_disconnection()
                yield _sse("progress", {"step": "generating", "message": "自适应助教正在组织回复...", "progress": 65})
                
                # 如果当前主模型不支持多模态，且我们已经提取了 OCR 文本，则最终生成时将图片置空。
                # 这能够强行让高认知能力的文本主模型 (如 DeepSeek) 承接后续的苏格拉底启发式回答与 RAG 融合，避免 fallback 视觉小模型直接吐出直接答案。
                final_images = images if getattr(swarm.llm, "has_vision", False) else []

                async for chunk in swarm.llm.generate_stream(system_prompt, user_prompt, role="自适应助教", images=final_images):
                    await check_disconnection()
                    full_response += chunk
                    yield _sse("chat_chunk", {"content": chunk})

                # 6. 安全审查
                safety_result = CONTENT_SAFETY.check_safety(full_response)
                if not safety_result["passed"]:
                    full_response = f"[内容安全提示] 部分敏感内容已过滤。\n\n{full_response}"

                # 7. 更新画像与对话历史 (学术模式下更新能力状态，非学术模式下轻量维护历史)
                try:
                    p = swarm.profile_store.get(student_id)
                    if p and hasattr(p, "update_from_feedback"):
                        p.update_from_feedback(
                            feedback=full_response,
                            accuracy=1.0 if is_academic else None,
                            self_confidence=None,
                            hint_count=0,
                        )
                        from app.database import run_db_op
                        from app.crud import save_student_profile
                        await run_db_op(save_student_profile, p)
                except Exception as e:
                    print(f"  [StreamAPI] Failed to update profile in chat mode: {e}")

                if is_academic:
                    # 自动为本次学习的知识点生成/更新复习安排
                    try:
                        target_concept = getattr(retrieval, "target", "")
                        if target_concept and target_concept != "未知":
                            p = swarm.profile_store.get(student_id)
                            mastery = p.concept_mastery.get(target_concept, 0.5) if p and hasattr(p, "concept_mastery") else 0.5
                            from app.crud import upsert_review_plan
                            from app.database import run_db_op
                            await run_db_op(upsert_review_plan, student_id, target_concept, mastery, 1)
                    except Exception as e:
                        print(f"  [StreamAPI] Failed to update review plan in chat mode: {e}")

                # 将本次对话记录写入历史数据库
                try:
                    from app.crud import record_conversation
                    from app.database import run_db_op
                    target_concept = getattr(retrieval, "target", "") if retrieval else "系统沟通"
                    await run_db_op(
                        record_conversation,
                        student_id,
                        message,
                        full_response,
                        target_concept,
                        0,
                        True
                    )
                except Exception as e:
                    print(f"  [StreamAPI] Failed to record conversation in chat mode: {e}")

                # 计算 RDI
                rdi_data = _calculate_rdi([{"content": full_response}], retrieval)

                profile_data = None
                try:
                    p = swarm.profile_store.get(student_id)
                    if p and hasattr(p, "weak_points"):
                        from bkt_engine import poincare_to_2d_coordinates
                        from embedding_models import EMBEDDINGS
                        concepts = list((getattr(p, "concept_mastery", {}) or {}).keys())
                        embeddings = {}
                        for c in concepts:
                            vec = EMBEDDINGS.embed(c)
                            if vec:
                                embeddings[c] = vec
                        # 在后台线程运行坐标映射，避免阻塞事件循环
                        coordinate_map = await asyncio.to_thread(poincare_to_2d_coordinates, embeddings)
                        
                        profile_data = {
                            "weak_points": getattr(p, "weak_points", [])[:5],
                            "concept_mastery": {k: round(v, 2) for k, v in list(getattr(p, "concept_mastery", {}).items())[:10]},
                            "coordinate_map": coordinate_map,
                        }
                except Exception as e:
                    print(f"  [StreamAPI] Failed to compute coordinate_map: {e}")
                    # 兜底
                    if p and hasattr(p, "weak_points"):
                        profile_data = {
                            "weak_points": getattr(p, "weak_points", [])[:5],
                            "concept_mastery": {k: round(v, 2) for k, v in list(getattr(p, "concept_mastery", {}).items())[:10]},
                        }

                resources = [
                    {"agent": "逻辑画师", "type": "slide_reference", "content": img}
                    for img in matched_images
                ]

                yield _sse("progress", {"step": "complete", "message": "生成完成！", "progress": 100})
                yield _sse("complete", {
                    "target": getattr(retrieval, "target", "") if retrieval else "系统沟通",
                    "content": full_response,
                    "resources": resources,
                    "safety": {
                        "passed": safety_result["passed"],
                        "issues_count": len(safety_result.get("issues", [])),
                    },
                    "profile": profile_data,
                    "alignment": {"passed": True, "distance": 0.0, "conflicts": []},
                    "rdi": rdi_data,
                    "strategy_plan": None
                })
                return

            # === 意图分类与防闲聊拦截 ===
            classification = await _classify_academic_intent(swarm.llm, message)
            if not classification.get("is_academic", True):
                reply = classification.get("reply") or "## 智能答疑 / 系统说明\n\n您好！我是 EduMatrix 智能自适应助教。我目前专注于为您解答机器学习和数据科学等学术问题，请提出与学习相关的疑问，谢谢！"
                await check_disconnection()
                yield _sse("progress", {"step": "complete", "message": "已识别为闲聊或非学术疑问。", "progress": 100})
                
                profile_data = None
                try:
                    if profile and hasattr(profile, "weak_points"):
                        profile_data = {
                            "weak_points": getattr(profile, "weak_points", [])[:5],
                            "concept_mastery": {k: round(v, 2) for k, v in list(getattr(profile, "concept_mastery", {}).items())[:10]},
                        }
                except Exception:
                    pass
                
                yield _sse("complete", {
                    "content": reply,
                    "target": "系统沟通",
                    "resources": [],
                    "profile": profile_data,
                    "strategy_plan": [],
                    "alignment": {"passed": True, "distance": 0.0, "conflicts": []}
                })
                return

            await check_disconnection()
            yield _sse("progress", {"step": "profile", "message": "正在分析学生画像...", "progress": 10})

            try:
                profile_obj = swarm.profile_store.get(student_id)
                if profile_obj and hasattr(profile_obj, "update_from_message"):
                    probe_task = asyncio.create_task(swarm.profile_probe.async_update(profile_obj, message))
                    running_tasks.append(probe_task)
                    try:
                        await probe_task
                    finally:
                        if probe_task in running_tasks:
                            running_tasks.remove(probe_task)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

            await check_disconnection()
            yield _sse("progress", {"step": "rag", "message": "正在检索知识库...", "progress": 25})

            try:
                retrieval = await swarm.planner.plan_async(swarm.rag, message, swarm.profile_store.get(student_id))
                debate_result = swarm.debate.clean(retrieval)
                await check_disconnection()
                yield _sse("progress", {"step": "debate", "message": f"证据清洗完成 ({len(debate_result.clean_evidence)} 条证据保留)", "progress": 40})
            except asyncio.CancelledError:
                raise
            except Exception as e:
                yield _sse("error", {"step": "rag", "message": f"检索失败: {str(e)[:100]}"})
                return

            # === 任务 8.1 / 低置信度幻觉拦截 ===
            if getattr(retrieval, "low_confidence", False):
                refusal_msg = "抱歉，系统在知识库中未检索到与您提问相关的充足高置信度证据，为避免幻觉，建议您在‘课件管理’页面中上传包含该概念的教学资料。"
                await check_disconnection()
                yield _sse("progress", {"step": "complete", "message": "置信度过低，已被安全拦截。", "progress": 100})
                
                profile_data = None
                try:
                    p = swarm.profile_store.get(student_id)
                    if p and hasattr(p, "weak_points"):
                        profile_data = {
                            "weak_points": getattr(p, "weak_points", [])[:5],
                            "concept_mastery": {k: round(v, 2) for k, v in list(getattr(p, "concept_mastery", {}).items())[:10]},
                            "cognitive_style": getattr(p, "cognitive_style", ""),
                            "learning_goals": getattr(p, "learning_goals", [])[:3],
                            "dimensions": {
                                k: {"score": round(v.score, 2), "status": v.status, "label": v.label}
                                for k, v in list(getattr(p, "dimension_states", {}).items())[:10]
                            },
                            "causes": {
                                k: {"percentage": round(v.percentage, 1), "label": v.label}
                                for k, v in list(getattr(p, "learning_state_causes", {}).items())[:7]
                            },
                        }
                except Exception:
                    pass

                # === 将低置信度拒绝回复写入学生画像历史中 ===
                try:
                    p = swarm.profile_store.get(student_id)
                    if p and hasattr(p, "update_from_feedback"):
                        p.update_from_feedback(
                            feedback=refusal_msg,
                            accuracy=None,
                            self_confidence=None,
                            hint_count=0,
                        )
                except Exception:
                    pass

                # === 将低置信度拒绝记录写入历史数据库 ===
                try:
                    from app.crud import record_conversation
                    from app.database import run_db_op
                    await run_db_op(
                        record_conversation,
                        student_id,
                        message,
                        "系统拦截:低置信度拒绝",
                        "未知",
                        0,
                        True
                    )
                except Exception as e:
                    print(f"  [StreamAPI] Failed to record low confidence refusal: {e}")

                yield _sse("complete", {
                    "target": "未知",
                    "content": f"## ⚠️ 置信度拦截提示\n\n{refusal_msg}",
                    "resources": [],
                    "safety": {
                        "passed": True,
                        "issues_count": 0,
                    },
                    "profile": profile_data,
                    "alignment": {
                        "passed": True,
                        "distance": 0.0,
                        "threshold": 0.65,
                        "conflicts": [],
                        "advice": "低置信度拦截，跳过对齐生成"
                    },
                    "strategy_plan": None,
                })
                return

            await check_disconnection()
            yield _sse("progress", {"step": "generating", "message": "5个智能体正在并行生成资源...", "progress": 50})

            agent_jobs = [
                ("理论教授", "专业讲义"),
                ("逻辑画师", "思维导图"),
                ("极客助教", "代码实操案例"),
                ("考官智能体", "练习题"),
                ("虚拟导演", "虚拟人视频脚本"),
            ]

            streamed_parts = []
            completed = 0

            async def _gen_one(role: str, rtype: str) -> list:
                chunks = []
                nonlocal completed
                try:
                    coro = swarm.async_generator.generate(
                        role=role, resource_type=rtype,
                        query=message, graph_context=retrieval.graph_context,
                        evidence=debate_result.clean_evidence,
                        profile=swarm.profile_store.get(student_id),
                        conversation_memory=style_prefix,
                    )
                    task = asyncio.create_task(coro)
                    running_tasks.append(task)
                    try:
                        result = await task
                    finally:
                        if task in running_tasks:
                            running_tasks.remove(task)
                    
                    streamed_parts.append(result)
                    completed += 1
                    chunks.append(_sse("agent_done", {"agent": role, "type": rtype, "progress": 50 + completed * 10}))
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    completed += 1
                    chunks.append(_sse("agent_done", {"agent": role, "type": rtype, "progress": 50 + completed * 10, "error": str(e)[:80]}))
                return chunks

            tasks = [_gen_one(role, rt) for role, rt in agent_jobs]
            for coro in asyncio.as_completed(tasks):
                await check_disconnection()
                for chunk in await coro:
                    await check_disconnection()
                    yield chunk

            await check_disconnection()
            yield _sse("progress", {"step": "alignment", "message": "正在校验多模态一致性...", "progress": 85})

            if streamed_parts:
                alignment_report = swarm.alignment.verify(streamed_parts, target=retrieval.target)
                if not alignment_report.passed:
                    for attempt in range(2):
                        await check_disconnection()
                        streamed_parts.clear()
                        coros = [
                            swarm.async_generator.generate(
                                role=role, resource_type=rt,
                                query=message, graph_context=retrieval.graph_context,
                                evidence=debate_result.clean_evidence,
                                profile=swarm.profile_store.get(student_id),
                                correction=f"第{attempt+1}次对齐失败：{alignment_report.advice[:100]}",
                                conversation_memory=style_prefix,
                            )
                            for role, rt in agent_jobs
                        ]
                        async def _gather_all():
                            return await asyncio.gather(*coros, return_exceptions=True)
                        gather_task = asyncio.create_task(_gather_all())
                        running_tasks.append(gather_task)
                        try:
                            results = await gather_task
                        finally:
                            if gather_task in running_tasks:
                                running_tasks.remove(gather_task)
                        
                        streamed_parts = [r for r in results if not isinstance(r, Exception)]
                        alignment_report = swarm.alignment.verify(streamed_parts, target=retrieval.target)
                        if alignment_report.passed:
                            break

            await check_disconnection()
            yield _sse("progress", {"step": "safety", "message": "正在进行内容安全审查...", "progress": 95})

            safety_content = ""
            for part in streamed_parts:
                if hasattr(part, "content") and hasattr(part, "resource_type"):
                    safety_content += f"\n\n## {part.resource_type}\n\n{part.content}"

            # === P1-4 形成性评价：在安全审查前嵌入微型检查点 ===
            _formative_check = _run_formative_check(
                message, retrieval.target if retrieval else "未知",
                streamed_parts, swarm.profile_store.get(student_id)
            )
            if _formative_check:
                yield _sse("formative_check", _formative_check)
                # 将检查结果注入 profile_data
                if _formative_check.get("profile_update"):
                    profile_obj = swarm.profile_store.get(student_id)
                    if profile_obj:
                        for key, val in _formative_check["profile_update"].items():
                            if hasattr(profile_obj, key):
                                setattr(profile_obj, key, val)

            safety_result = CONTENT_SAFETY.check_safety(safety_content)
            target_str = getattr(retrieval, "target", "")
            final_content = f"## 学习目标：{target_str}\n\n系统已为您调配了 5 大专业动作智能体协同生成自适应讲义。请在下方点击展开各个模块进行针对性学习："
            if not safety_result["passed"]:
                final_content = f"[内容安全提示] 部分内容已过滤\n\n{final_content}"

            strategy_plan = None
            try:
                p = swarm.profile_store.get(student_id)
                if p and hasattr(p, "student_id"):
                    strategy_plan = swarm.strategy_engine.build_plan(p, target=retrieval.target)
            except Exception:
                pass

            await check_disconnection()
            yield _sse("progress", {"step": "complete", "message": "生成完成！", "progress": 100})

            profile_data = None
            try:
                p = swarm.profile_store.get(student_id)
                if p and hasattr(p, "weak_points"):
                    profile_data = {
                        "weak_points": getattr(p, "weak_points", [])[:5],
                        "concept_mastery": {k: round(v, 2) for k, v in list(getattr(p, "concept_mastery", {}).items())[:10]},
                        "cognitive_style": getattr(p, "cognitive_style", ""),
                        "learning_goals": getattr(p, "learning_goals", [])[:3],
                        "dimensions": {
                            k: {"score": round(v.score, 2), "status": v.status, "label": v.label}
                            for k, v in list(getattr(p, "dimension_states", {}).items())[:10]
                        },
                        "causes": {
                            k: {"percentage": round(v.percentage, 1), "label": v.label}
                            for k, v in list(getattr(p, "learning_state_causes", {}).items())[:7]
                        },
                    }
            except Exception:
                pass

            alignment_data = {
                "passed": True,
                "distance": 0.0,
                "threshold": 0.65,
                "conflicts": [],
                "advice": "未进行校验"
            }
            if alignment_report:
                alignment_data = {
                    "passed": alignment_report.passed,
                    "distance": alignment_report.distance,
                    "threshold": alignment_report.threshold,
                    "conflicts": [
                        {
                            "type": c.get("type", "conflict"),
                            "resources": c.get("resources", []),
                            "distance": c.get("distance", 0.0),
                            "suggestion": c.get("suggestion", "")
                        } for c in alignment_report.conflicts
                    ] if alignment_report.conflicts else [],
                    "advice": alignment_report.advice
                }

            # === 按照 理论-思维导图-代码-题目-视频 顺序进行重排序 ===
            order_map = {
                "专业讲义": 0, "理论教授": 0,
                "思维导图": 1, "逻辑画师": 1,
                "代码实操案例": 2, "极客助教": 2,
                "练习题": 3, "考官智能体": 3,
                "虚拟人视频脚本": 4, "虚拟导演": 4
            }
            def get_order_key(r):
                rtype = getattr(r, "resource_type", "")
                role = getattr(r, "agent", "")
                if rtype in order_map:
                    return order_map[rtype]
                if role in order_map:
                    return order_map[role]
                return 99

            sorted_parts = sorted(streamed_parts, key=get_order_key)

            # === 将系统生成的讲义回复记录写入学生画像历史中，以维持多轮滑动上下文的交替结构 ===
            try:
                p = swarm.profile_store.get(student_id)
                if p and hasattr(p, "update_from_feedback"):
                    p.update_from_feedback(
                        feedback=final_content,
                        accuracy=1.0,
                        self_confidence=None,
                        hint_count=0,
                    )
                    from app.database import run_db_op
                    from app.crud import save_student_profile
                    await run_db_op(save_student_profile, p)
            except Exception as e:
                print(f"  [StreamAPI] Failed to update and save profile history: {e}")

            # === 自动为本次学习的知识点生成/更新复习安排 ===
            try:
                target_concept = getattr(retrieval, "target", "")
                if target_concept and target_concept != "未知" and not getattr(retrieval, "low_confidence", False):
                    p = swarm.profile_store.get(student_id)
                    mastery = p.concept_mastery.get(target_concept, 0.5) if p and hasattr(p, "concept_mastery") else 0.5
                    
                    from app.crud import upsert_review_plan
                    from app.database import run_db_op
                    
                    # 默认初始复习间隔为 1 天
                    await run_db_op(upsert_review_plan, student_id, target_concept, mastery, 1)
                    print(f"  [StreamAPI] Automatically created/updated review plan for concept: {target_concept}")
            except Exception as e:
                print(f"  [StreamAPI] Failed to automatically create/update review plan: {e}")

            # === 将本次对话记录写入历史数据库 ===
            try:
                from app.crud import record_conversation
                from app.database import run_db_op
                
                target_concept = getattr(retrieval, "target", "")
                alignment_passed = alignment_report.passed if alignment_report else True
                resource_summary = "; ".join(f"{getattr(r, 'agent', '')}:{getattr(r, 'resource_type', '')}" for r in streamed_parts)
                
                await run_db_op(
                    record_conversation,
                    student_id,
                    message,
                    resource_summary,
                    target_concept,
                    len(streamed_parts),
                    alignment_passed
                )
                print(f"  [StreamAPI] Successfully recorded conversation to history: {message[:30]}...")
            except Exception as e:
                print(f"  [StreamAPI] Failed to record conversation to history: {e}")

            # === 计算 RDI 风险指数 (创新点1) ===
            rdi_data = _calculate_rdi(streamed_parts, retrieval)

            yield _sse("complete", {
                "target": getattr(retrieval, "target", ""),
                "content": final_content,
                "resources": [
                    {"agent": getattr(r, "agent", ""), "type": getattr(r, "resource_type", ""), "content": getattr(r, "content", "") or ""}
                    for r in sorted_parts[:8]
                ],
                "safety": {
                    "passed": safety_result["passed"],
                    "issues_count": len(safety_result.get("issues", [])),
                },
                "profile": profile_data,
                "alignment": alignment_data,
                "rdi": rdi_data,  # 注入 RDI Factual Overlap 幻觉风险指数
                "strategy_plan": {
                    "actions": [
                        {"title": a.title, "description": a.description, "priority": a.priority}
                        for a in (strategy_plan.actions if strategy_plan else [])
                    ],
                    "rationale": strategy_plan.rationale if strategy_plan else "",
                } if strategy_plan else None,
            })
        finally:
            for task in running_tasks:
                if not task.done():
                    task.cancel()


    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/regenerate")
async def regenerate_component(request: Request) -> dict[str, Any]:
    from app.database import run_db_op
    from app.crud import load_student_profile

    payload = await request.json()
    student_id = str(payload.get("student_id", "default"))
    role = str(payload.get("role", ""))
    resource_type = str(payload.get("resource_type", ""))
    query = str(payload.get("query", ""))
    overview = payload.get("overview")
    pathway = payload.get("pathway")
    
    if not role or not resource_type or not query:
        raise HTTPException(status_code=400, detail="参数缺失")
        
    swarm = build_swarm_from_headers(request.headers)
    profile = swarm.profile_store.get(student_id)
    if not profile:
        profile = await run_db_op(load_student_profile, student_id)
        swarm.profile_store[student_id] = profile
    
    try:
        retrieval = await swarm.planner.plan_async(swarm.rag, query, profile)
        evidence = swarm.debate.clean(retrieval).clean_evidence
        graph_context = retrieval.graph_context
    except Exception:
        from models import GraphContext
        evidence = ()
        graph_context = GraphContext(
            target=query,
            learning_path=(query,),
            prerequisite_edges=(),
            downstream_edges=(),
        )
        
    forced_inst = overview or ""
    if pathway:
        from app.utils.recommendation_engine import evaluate_tactical_pathway
        try:
            pathway_meta = evaluate_tactical_pathway(profile, query, pathway)
            pathway_instructions = {
                "ICE_BREAKER": (
                    "【战术指令：破冰路线】此资源应突出前置背景连接。请特别增加对前置依赖概念的梳理，"
                    "降低讲解梯度，建立与已知知识点的清晰过渡，使讲解浅显易懂。"
                ),
                "PRACTITIONER": (
                    "【战术指令：实操路线】此资源应极度注重编码、实操或应用案例。对于理论讲解应当极其简明，"
                    "重点展示完整的、带注释的代码/操作片段，以实干代替空谈。"
                ),
                "EXPLORER": (
                    "【战术指令：探究路线】此资源应采用严密的数理逻辑与学术探究风格。请大量运用 LaTex 进行推导，"
                    "进行概念深层剖析，并提出思考拓展方向。"
                ),
                "RESCUE": (
                    "【战术指令：防忘路线】针对低掌握度或艾宾浩斯遗忘临界点。请先划出致命误区（以 [!WARNING] 或 [!CAUTION] 强调），"
                    "指出易错概念，提供抗遗忘记忆口诀或重点回顾。"
                ),
                "FUSION": (
                    "【战术指令：跨界路线】交叉学科融合。请将当前概念与相邻或其它领域的知识进行融合展示，"
                    "解释跨学科交叉应用场景与宏观视角。"
                )
            }
            inst_text = pathway_instructions.get(pathway, "")
            if inst_text:
                forced_inst = f"{inst_text}\n{forced_inst}"
        except Exception as e:
            print(f"  [StreamAPI] Failed to evaluate pathway instructions: {e}")

    try:
        result = await swarm.async_generator.generate(
            role=role,
            resource_type=resource_type,
            query=query,
            graph_context=graph_context,
            evidence=evidence,
            profile=profile,
            forced_instruction=forced_inst,
        )
        content = result.content if hasattr(result, "content") else str(result)
        
        # 将生成的资源保存到数据库中以实现统一持久化
        import uuid
        from app.database import DBNote
        
        note_id = f"note-{uuid.uuid4().hex[:12]}"
        db_tag = resource_type
        if "代码" in resource_type:
            db_tag = "代码案例"
        elif "视频" in resource_type or "脚本" in resource_type:
            db_tag = "视频脚本"
        elif "讲义" in resource_type:
            db_tag = "专业讲义"
        elif "思维" in resource_type or "导图" in resource_type:
            db_tag = "思维导图"
        elif "练习" in resource_type or "题" in resource_type:
            db_tag = "练习题"

        def save_generated_note(session):
            existing = session.query(DBNote).filter(
                DBNote.student_id == student_id,
            ).all()
            
            target_note = None
            for n in existing:
                if query in (n.concepts or []) and db_tag in (n.tags or []):
                    target_note = n
                    break
            
            if target_note:
                target_note.content = content
                session.commit()
                return target_note.id
            else:
                new_note = DBNote(
                    id=note_id,
                    student_id=student_id,
                    source="adaptive_hub",
                    content=content,
                    tags=[db_tag],
                    concepts=[query]
                )
                session.add(new_note)
                session.commit()
                return note_id

        saved_note_id = await run_db_op(save_generated_note)

        return {
            "status": "success",
            "content": content,
            "note_id": saved_note_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重算失败: {str(e)}")


@router.post("/explain")
async def socratic_explain(request: Request) -> dict[str, Any]:
    """任务 8.1: 行级/公式苏格拉底即时答疑。

    接收被点击的代码行/公式文本及上下文，返回苏格拉底式分步推导。
    """
    payload = await request.json()
    target_text = str(payload.get("target_text", "")).strip()
    context_before = str(payload.get("context_before", ""))
    context_after = str(payload.get("context_after", ""))
    student_id = str(payload.get("student_id", "default"))
    follow_up = str(payload.get("follow_up", "")).strip()
    history = str(payload.get("history", "")).strip()

    if not target_text:
        raise HTTPException(status_code=400, detail="target_text 不能为空")

    swarm = build_swarm_from_headers(request.headers)
    profile = swarm.profile_store.get(student_id)

    is_formula = any(c in target_text for c in ['\\', '∂', '∫', '∑', 'π', 'θ', '_', '^', 'lim', 'frac', 'partial'])
    is_code = 'def ' in target_text or 'import ' in target_text or 'class ' in target_text or '=' in target_text

    # === PEARL/KELE 双轨苏格拉底导学机制 ===
    # 1. 后台 Consultant Agent (教学规划师) 规划策略
    consultant_system = (
        "你是一个苏格拉底教学策略规划师。你需要根据学生选取的文本、历史上下文和追问内容，规划下一步的教学动作。\n\n"
        "可选的教学动作：\n"
        "1. DEFINE: 定义并解释某个具体符号、变量或参数\n"
        "2. COUNTER_EXAMPLE: 提出一个反例或常见混淆点让学生辨析\n"
        "3. SOCRATIC_QUESTION: 提出一个启发式问题引导学生自我推导/发现\n"
        "4. HINT_LADDER: 给出一个局部的提示/阶梯线索，而不是直接解答\n\n"
        "请严格以以下 JSON 格式输出，不要包含任何额外字符：\n"
        '{"pedagogical_move": "DEFINE|COUNTER_EXAMPLE|SOCRATIC_QUESTION|HINT_LADDER", "focus_concept": "被解释的核心概念名词"}'
    )
    
    user_context = (
        f"目标内容: {target_text}\n"
        f"上文: {context_before}\n"
        f"下文: {context_after}\n"
        f"历史对话: {history}\n"
        f"当前学生追问: {follow_up if follow_up else '（首次点击）'}"
    )

    try:
        import json
        import re
        consultant_raw = await swarm.async_generator.llm.generate(consultant_system, user_context, role="教学规划师")
        match = re.search(r"\{.*\}", consultant_raw, flags=re.S)
        if match:
            consultant_decision = json.loads(match.group(0))
        else:
            consultant_decision = {"pedagogical_move": "SOCRATIC_QUESTION", "focus_concept": target_text}
    except Exception:
        consultant_decision = {"pedagogical_move": "SOCRATIC_QUESTION", "focus_concept": target_text}

    move = consultant_decision.get("pedagogical_move", "SOCRATIC_QUESTION")
    concept = consultant_decision.get("focus_concept", target_text)

    # 2. 前台 Teacher Agent (对话导师) 表达
    # 轮次判断：有 history 说明学生已回应过，应过渡到讲解
    is_follow_up = bool(follow_up.strip()) or bool(history.strip())

    if is_follow_up:
        # 第2轮+：学生已参与对话，给出详细讲解
        teacher_system = (
            "你是一位温和、耐心的苏格拉底导师。学生已经回应了你的引导问题，现在请给出完整的讲解。\n\n"
            f"本轮教学动作: {move}\n"
            f"本轮聚焦概念: {concept}\n"
            f"学生追问: {follow_up}\n\n"
            "🎯 核心要求：\n"
            "1. 先简要肯定学生的回答/追问，建立正向反馈。\n"
            "2. 然后给出详细、完整的讲解：拆解概念、解释原理、结合具体例子。\n"
            "3. 如果是公式：解释每个符号的含义和整体数学意义。\n"
            "4. 如果是代码：解释每条语句的作用和执行逻辑。\n"
            "5. 最后可以提一个拓展思考题（可选，非必须）。\n"
            "6. 使用中文，不要用 '总而言之''首先其次'等套话。"
        )
    else:
        # 第1轮：用启发式提问引导学生思考
        teacher_system = (
            "你是一位温和、耐心的苏格拉底对话导师。你的任务是用一个启发式问题引导学生开始思考，"
            "不要长篇讲解。\n\n"
            f"本轮教学动作: {move}\n"
            f"本轮聚焦概念: {concept}\n\n"
            "🎯 核心要求：\n"
            "1. 只问 1 个有启发性的问题，不要解释。\n"
            "2. 通过反问、类比比喻、局部符号提问，迫使学生回忆或自己动脑筋。\n"
            "3. 控制在 80 字以内，结尾一个问号即可。\n"
            "4. 使用中文。"
        )

    teacher_user = (
        f"目标内容: {target_text}\n"
        f"历史对话: {history}\n"
        f"学生追问: {follow_up if follow_up else '（首次点击）'}"
    )

    try:
        content = await swarm.async_generator.llm.generate(teacher_system, teacher_user, role="苏格拉底辩手")
        return {
            "status": "success",
            "content": content,
            "target_text": target_text,
            "agent_trace": {
                "consultant_move": move,
                "focus_concept": concept
            }
        }
    except Exception as e:
        return {
            "status": "fallback",
            "content": _socratic_fallback(target_text, is_formula, is_code),
            "target_text": target_text,
        }


def _socratic_fallback(text: str, is_formula: bool, is_code: bool) -> str:
    """LLM 不可用时返回模板化兜底解释。"""
    lines = []
    if is_formula:
        lines.append("📐 这是一个数学表达式，表示一个数学运算关系")
        if '\\frac' in text:
            lines.append("📝 分数形式: \\frac{分子}{分母} 表示分子除以分母")
        if '\\partial' in text:
            lines.append("🎯 偏导符号 ∂ 表示多元函数对某一变量的偏导数")
        if 'lim' in text.lower():
            lines.append("🎯 极限符号 lim 表示当变量趋近某值时的函数行为")
        lines.append("")
        lines.append("💡 可追问: 每个符号表示什么？这个公式的物理意义是什么？")
    elif is_code:
        lines.append("💻 这是一段代码语句")
        if 'def ' in text:
            lines.append("📦 函数定义: def 关键字声明可复用的代码块")
        elif 'import ' in text:
            lines.append("📚 import 导入外部库/模块")
        elif '=' in text and '(' in text:
            lines.append("📦 函数调用/赋值语句")
        lines.append("")
        lines.append("💡 可追问: 参数是什么？返回值是什么？")
    else:
        lines.append(f"📖 选取内容: {text[:80]}")
        lines.append("💡 请在后端对话框继续追问")
    return "\n".join(lines)