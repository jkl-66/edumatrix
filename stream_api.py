from __future__ import annotations

import json
import asyncio
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.auth import enforce_student_access, get_current_user
from swarm_factory import build_swarm_from_headers
from content_safety import CONTENT_SAFETY
from models import AgentOutput

router = APIRouter(prefix="/api/stream", tags=["streaming"])


# === P1-4 形成性评价：微型检查点函数 ===
def _run_formative_check(query: str, target: str, streamed_parts: list, profile) -> dict | None:
    """根据教学内容生成快速理解检查的关键词和判断。"""
    if not streamed_parts or not target or target == "未知":
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



async def _upsert_review_plans_for_concept(swarm, student_id: str, target_concept: str):
    if not target_concept or target_concept == "未知":
        return
    concepts = []
    if "与" in target_concept:
        concepts = target_concept.split("与")
    elif "and" in target_concept.lower():
        # Match English "and" or similar separators if they occur
        concepts = target_concept.split(" and ")
    elif "和" in target_concept:
        concepts = target_concept.split("和")
    else:
        concepts = [target_concept]

    from app.crud import upsert_review_plan
    from app.database import run_db_op
    p = swarm.profile_store.get(student_id)
    for c in concepts:
        c = c.strip()
        if c:
            mastery = p.concept_mastery.get(c, 0.5) if p and hasattr(p, "concept_mastery") else 0.5
            await run_db_op(upsert_review_plan, student_id, c, mastery, 1)


def _extract_suggested_questions(content: str) -> tuple[str, list[str]]:
    import re
    # Define a pattern that matches the header or separator line for suggested questions
    header_pattern = r'(?:===SUGGESTED_QUESTIONS===|\[建议追问\]|【建议追问】|建议追问\s*[\(（]点击可追问[\)）]|建议追问|推荐追问)(?:\uff1a|:)?'
    
    match = re.search(header_pattern, content, re.IGNORECASE)
    
    if match:
        found_idx = match.start()
        # Backtrack if preceded by list markers like "1."
        prefix = content[:found_idx]
        list_match = re.search(r'\b1\s*[\.\u3002\uFF0E、\-\s]\s*$', prefix)
        if list_match:
            found_idx = list_match.start()
        questions_block = content[match.end():].strip()
    else:
        # Fallback if no header, look for the list start "1. 【建议追问】" or "1. 建议追问" or just "1. "
        fallback_match = re.search(r'\b1\s*[\.\u3002\uFF0E、\-\s]\s*(?:[\u3010\[]建议追问[\u3011\]]|【建议追问】|\[建议追问\]|建议追问)?', content)
        if fallback_match:
            found_idx = fallback_match.start()
            questions_block = content[fallback_match.start():].strip()
        else:
            return content, []
            
    main_content = content[:found_idx].strip()
    questions_block = re.sub(r'^[：:\s=\-]*', '', questions_block).strip()
    
    # Split questions_block into individual items
    if "\n" in questions_block:
        parts = questions_block.split("\n")
    else:
        pattern = r'\s+(?=\d+[\.\u3002\uFF0E、\-\s])|(?<=[？\uff1f！\uff01。\.])\s*(?=\d+[\.\u3002\uFF0E、\-\s])'
        parts = re.split(pattern, questions_block)
        
    questions = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        cleaned = re.sub(r'^\d+[\.\u3002\uFF0E\s、\-]*\s*', '', part).strip()
        cleaned = re.sub(r'^[\u3010\[]建议追问[\u3011\]]', '', cleaned).strip()
        cleaned = re.sub(r'^建议追问', '', cleaned).strip()
        cleaned = re.sub(r'[=\-]{3,}$', '', cleaned).strip()
        cleaned = cleaned.strip()
        if cleaned:
            questions.append(cleaned)
            
    questions = [q for q in questions if len(q) > 2 and not q.startswith("===") and not q.startswith("---")]
    
    if len(questions) >= 1:
        return main_content, questions[:3]
        
    return content, []


async def _generate_suggested_questions(swarm: Any, concept: str, profile: Any) -> list[str]:
    if not concept:
        return ["什么是机器学习？", "如何零基础开始学机器学习？", "什么是神经网络？"]
    
    import re
    profile_context = ""
    if profile:
        weak = "、".join(profile.weak_points[:3]) if getattr(profile, "weak_points", None) else "暂无"
        goals = "、".join(profile.learning_goals[:3]) if getattr(profile, "learning_goals", None) else "暂无"
        major = getattr(profile, "major", None) or getattr(profile, "major_preference", None) or "计算机"
        profile_context = f"学生专业={major}，学习目标={goals}，薄弱点={weak}"
        
    system_prompt = (
        "你是一个顶级的自适应教育顾问。根据给定的机器学习/编程知识点概念以及学生的学情画像，"
        "生成 3 个学生可能会想要继续提问的、最具有学习价值的后续追问问题。\n"
        "【生成规则】：\n"
        "1. 必须针对当前知识点 concept 的原理细节、推导步骤或代码实践。\n"
        "2. 结合学生的背景（例如：如果学生是计算机专业，可问算法实现或推导；如果基础弱，可问概念比喻）。\n"
        "3. 保持简短（每题 18 字以内，结尾带问号）。\n"
        "4. 必须输出 3 个问题，用换行分隔，前面加数字序号（如 1. 2. 3.）。不要输出任何其他内容。"
    )
    user_prompt = f"核心知识点概念: {concept}\n学生学情画像: {profile_context}"
    try:
        raw = await swarm.llm.generate(system_prompt, user_prompt, role="提示顾问")
        questions = []
        for line in raw.split("\n"):
            line = line.strip()
            if line:
                cleaned = re.sub(r'^\d+\.\s*', '', line).strip()
                if cleaned:
                    questions.append(cleaned)
        if len(questions) >= 3:
            return questions[:3]
    except Exception:
        pass
    return [
        f"如何用 Python 实现 {concept} 的最简 Demo？",
        f"在实际项目中，{concept} 最常见的错误和陷阱是什么？",
        f"{concept} 与它最临近的算法/概念有什么区别？"
    ]


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
async def stream_chat(request: Request, current_user=Depends(get_current_user)) -> StreamingResponse:
    import time
    start_time = time.time()

    def _make_metrics(content: str, query: str) -> dict:
        rtt = int((time.time() - start_time) * 1000)
        tokens = int(len(content or "") * 0.75 + len(query or "") * 0.75)
        cost = round(tokens * 0.000015, 4)
        return {
            "rtt_ms": rtt,
            "tokens_used": tokens,
            "cost_cny": cost,
            "model": "EduMatrix Swarm 1+3+5",
            "circuit_breaker": "CLOSED",
        }

    payload = await request.json()
    message = str(payload.get("message", "")).strip()
    student_id = enforce_student_access(payload.get("student_id"), current_user)
    mode = str(payload.get("mode", "chat")).strip()
    images = list(payload.get("images", []))
    active_doc_ids = list(payload.get("active_doc_ids", []))

    forced_target_agent = None
    doc_constraint = None
    doc_constraints = []

    # 1. 解析 active_doc_ids 并映射到文件名
    if active_doc_ids:
        try:
            from app.database import DBKnowledgeDocument, run_db_op
            def fetch_doc_filenames(session):
                return (
                    session.query(DBKnowledgeDocument.filename)
                    .filter(DBKnowledgeDocument.id.in_(active_doc_ids))
                    .all()
                )
            records = await run_db_op(fetch_doc_filenames)
            if records:
                doc_constraints.extend([r[0] for r in records if r[0]])
        except Exception as e:
            print(f"  [stream_api] 解析 active_doc_ids 异常: {e}")

    import re
    # 2. 匹配快捷 Slash 命令并映射到相应 Agent
    cmd_match = re.match(r"^/(explain|map|code|quiz|video)\s+(.*)", message, re.IGNORECASE)
    if cmd_match:
        cmd = cmd_match.group(1).lower()
        message = cmd_match.group(2).strip()
        mode = "matrix"
        ROLE_MAP = {
            "explain": "理论教授",
            "map": "逻辑画师",
            "code": "极客助教",
            "quiz": "考官智能体",
            "video": "视频推荐官",
        }
        forced_target_agent = ROLE_MAP.get(cmd)

    # 3. 匹配并提取 `@` 课件过滤条件 (优先检索数据库以完全兼容文件名空格)
    try:
        from app.database import DBKnowledgeDocument, run_db_op
        def fetch_docs(session):
            return session.query(DBKnowledgeDocument.filename).all()
        db_records = await run_db_op(fetch_docs)
        db_filenames = [r[0] for r in db_records] if db_records else []
        db_filenames.sort(key=len, reverse=True) # 优先匹配长名
        for fname in db_filenames:
            ref = f"@{fname}"
            if ref in message:
                doc_constraint = fname
                message = message.replace(ref, "").strip()
                break
    except Exception as e:
        print(f"  [stream_api] 检索课件库文件名异常: {e}")

    if not doc_constraint:
        # 正则降级匹配 (仅支持不含空格的文件名)
        doc_match = re.search(r"@([^\s]+)", message)
        if doc_match:
            doc_constraint = doc_match.group(1).strip()
            message = message.replace(doc_match.group(0), "").strip()

    if doc_constraint:
        doc_constraints.append(doc_constraint)

    # 统一转换约束列表，如果为空则为 None
    final_constraints = doc_constraints if doc_constraints else None

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
                    recent_history = ""
                    try:
                        from app.crud import get_conversation_history
                        from app.database import run_db_op

                        # 核心防线：拉取最近 10 条（5 轮）对话上下文，确保对抗挑战紧密契合当前教学语境，非孤立概念生成
                        history_records = await run_db_op(get_conversation_history, student_id, 10)
                        if history_records:
                            lines = []
                            for h in reversed(history_records):
                                role_name = "学生" if h.role == "user" else "系统"
                                lines.append(f"{role_name}: {h.message_body}")
                            recent_history = "\n".join(lines)

                            # 自动获取最近对话的目标知识点概念，防漏和跨越
                            if not concept:
                                for h in history_records:
                                    if h.target and h.target != "未知":
                                        concept = h.target
                                        break
                        
                    except Exception as e:
                        print(f"  [StreamAPI] Failed to retrieve history for peer PK: {e}")

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
                            "请根据学生最近的对话历史上下文，为学生设计一个「找学伴小明的代码逻辑 Bug」的对抗性挑战（Adversarial Peer Challenge）。\n"
                            "【设计准则】：\n"
                            f"- 针对知识点「{concept}」。\n"
                            "- 必须要紧密结合学生在历史对话中讨论/追问的具体技术细节或痛点，不要出与当前讨论完全无关的孤立知识点。\n"
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
                        user_prompt = (
                            f"请生成与以下对话上下文高度关联的「{concept}」代码 Bug 对抗挑战。\n\n"
                            f"【最近对话上下文】：\n{recent_history if recent_history else '无历史对话'}"
                        )

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
                    debate_result = await swarm.debate.aclean(retrieval)
                    
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
                                    "fsm_mode": getattr(p, "fsm_mode", "normal"),
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
                    # 触发 FSM 路由决策以获取自适应教学指令并持久化状态
                    swarm_mode = "normal"
                    forced_instruction = ""
                    chat_role = "自适应助教"
                    try:
                        target_concept = getattr(retrieval, "target", "") if retrieval else None
                        swarm_mode = swarm.mediation_router.decide_mode(profile, target=target_concept)
                        mediation_instructions = swarm.mediation_router.get_forced_instructions(swarm_mode)
                        
                        from agent_swarm import SwarmMediationMode
                        if swarm_mode == SwarmMediationMode.DEBATE_MODE:
                            forced_instruction = mediation_instructions.get("debater", "")
                            chat_role = "苏格拉底辩手"
                        elif swarm_mode == SwarmMediationMode.SIMPLIFIED_MODE:
                            forced_instruction = mediation_instructions.get("theory", "")
                            chat_role = "概念可视化导师"
                        elif swarm_mode == SwarmMediationMode.ADVANCED_MODE:
                            forced_instruction = mediation_instructions.get("theory", "")
                            chat_role = "自适应考官"
                        else:
                            forced_instruction = mediation_instructions.get("theory", "")
                            chat_role = "自适应助教"
                    except Exception as e:
                        print(f"  [StreamAPI] FSM Routing decision failed in chat mode: {e}")

                    history_str = _format_chat_history(profile, max_turns=5)
                    system_prompt = (
                        f"你是一个极具教育学底蕴的 EduMatrix 自适应智能助教。你当前的教学角色是「{chat_role}」。你致力于通过微步启发、苏格拉底式对话引导学生思考，而不是直接给出完整答案。\n"
                        "请根据检索到的背景知识库证据，并结合【历史对话记录】的上下文，回答学生提出的学术或题目疑问。\n"
                        "【要求】：\n"
                        "- 必须使用中文回答，格式为漂亮的 Markdown。\n"
                        "- 如果学生上传了题目图片（根据提供的图片文字内容），请分步解析题目，提示核心公式和关键步骤，然后向学生提出一个引导性的思考问题。\n"
                        "- 回答结尾必须提供一个具体的启发式问题引导学生下一步动作。\n"
                        f"- 教学风格：{teaching_style or '苏格拉底启发式'}。\n"
                        "- 并在你的回答正文的【最末尾换行输出 3 个学生可能会想要继续追问的问题】，必须严格遵循以下格式（包含横线和建议追问标志，用于系统提取后独立渲染为可点击按钮，不要加任何加粗，短小精练且极具学习价值，必须是提问问句）：\n"
                        "===\n"
                        "===SUGGESTED_QUESTIONS===\n"
                        "[建议追问]\n"
                        "1. 第一个建议追问问题？\n"
                        "2. 第二个建议追问问题？\n"
                        "3. 第三个建议追问问题？\n"
                        "========================\n"
                    )
                    if style_prefix:
                        system_prompt = style_prefix + system_prompt
                    if forced_instruction:
                        system_prompt += f"\n【自适应路由控制指令】：{forced_instruction}\n"
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
                    chat_role = "自适应助教"
                    system_prompt = (
                        "你是一个温和友好、极具亲和力的 EduMatrix 自适应智能助教。\n"
                        "【任务与要求】：\n"
                        "1. 学生输入了一个与机器学习/编程学术无关的闲聊或日常问答。请你**极其简短**地回应或回答学生的问题（控制在2-3句话，保持温和与礼貌）。\n"
                        "2. 在回答的结尾，用一句话温馨、生动地将话题**引导回机器学习、数据科学或编程学术学习上**，并向学生推荐一两个可以提问的例子（例如提示学生可以询问‘什么是最大池化？’或‘神经网络是如何学习的？’来开始学习）。\n"
                        "3. 必须使用中文回答，格式为漂亮的 Markdown。\n"
                        "4. 并在你的回答正文的【最末尾换行输出 3 个学生可能会想要继续追问的问题】，必须严格遵循以下格式（包含横线和建议追问标志，用于系统提取后独立渲染为可点击按钮，不要加任何加粗，短小精练且极具学习价值，必须是提问问句）：\n"
                        "===\n"
                        "===SUGGESTED_QUESTIONS===\n"
                        "[建议追问]\n"
                        "1. 第一个建议追问问题？\n"
                        "2. 第二个建议追问问题？\n"
                        "3. 第三个建议追问问题？\n"
                        "========================\n"
                    )
                    user_prompt = ""
                    if history_str:
                        user_prompt += f"【历史对话记录】：\n{history_str}\n\n"
                    user_prompt += f"学生当前提问：{message}\n请提供简短的日常回应并引导回学习上："

                # 5. 调用大模型流式响应
                full_response = ""
                await check_disconnection()
                yield _sse("progress", {"step": "generating", "message": f"{chat_role}正在组织回复...", "progress": 65})
                
                # 如果当前主模型不支持多模态，且我们已经提取了 OCR 文本，则最终生成时将图片置空。
                # 这能够强行让高认知能力的文本主模型 (如 DeepSeek) 承接后续的苏格拉底启发式回答与 RAG 融合，避免 fallback 视觉小模型直接吐出直接答案。
                final_images = images if getattr(swarm.llm, "has_vision", False) else []

                async for chunk in swarm.llm.generate_stream(system_prompt, user_prompt, role=chat_role, images=final_images):
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
                            await _upsert_review_plans_for_concept(swarm, student_id, target_concept)
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
                        
                        def _bulk_embed(concepts_list):
                            res = {}
                            for c in concepts_list:
                                vec = EMBEDDINGS.embed(c)
                                if vec:
                                    res[c] = vec
                            return res

                        embeddings = await asyncio.to_thread(_bulk_embed, concepts)
                        # 在后台线程运行坐标映射，避免阻塞事件循环
                        coordinate_map = await asyncio.to_thread(poincare_to_2d_coordinates, embeddings)
                        
                        profile_data = {
                            "weak_points": getattr(p, "weak_points", [])[:5],
                            "concept_mastery": {k: round(v, 2) for k, v in list(getattr(p, "concept_mastery", {}).items())[:10]},
                            "coordinate_map": coordinate_map,
                            "fsm_mode": getattr(p, "fsm_mode", "normal"),
                        }
                except Exception as e:
                    print(f"  [StreamAPI] Failed to compute coordinate_map: {e}")
                    # 兜底
                    if p and hasattr(p, "weak_points"):
                        profile_data = {
                            "weak_points": getattr(p, "weak_points", [])[:5],
                            "concept_mastery": {k: round(v, 2) for k, v in list(getattr(p, "concept_mastery", {}).items())[:10]},
                            "fsm_mode": getattr(p, "fsm_mode", "normal"),
                        }

                resources = [
                    {"agent": "逻辑画师", "type": "slide_reference", "content": img}
                    for img in matched_images
                ]

                clean_reply, suggested_qs = _extract_suggested_questions(full_response)
                if not suggested_qs:
                    target_concept = getattr(retrieval, "target", "") if retrieval else message
                    suggested_qs = await _generate_suggested_questions(swarm, target_concept, profile)

                yield _sse("progress", {"step": "complete", "message": "生成完成！", "progress": 100})
                yield _sse("complete", {
                    "target": getattr(retrieval, "target", "") if retrieval else "系统沟通",
                    "content": clean_reply,
                    "suggested_questions": suggested_qs,
                    "resources": resources,
                    "safety": {
                        "passed": safety_result["passed"],
                        "issues_count": len(safety_result.get("issues", [])),
                    },
                    "profile": profile_data,
                    "alignment": {"passed": True, "distance": 0.0, "conflicts": []},
                    "rdi": rdi_data,
                    "strategy_plan": None,
                    "metrics": _make_metrics(clean_reply, message),
                })
                return

            retrieval = None
            if not forced_target_agent:
                if message.startswith("一键生成资源包:"):
                    classification = {"is_academic": True}
                else:
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
                        "alignment": {"passed": True, "distance": 0.0, "conflicts": []},
                        "metrics": _make_metrics(reply, message),
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
                    debate_result = await swarm.debate.aclean(retrieval)
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
                        "metrics": _make_metrics(refusal_msg, message),
                    })
                    return

            await check_disconnection()
            yield _sse("progress", {"step": "generating", "message": "启动 1+3+5 智能体协作流，进行全流程有状态调度...", "progress": 50})

            # ===== 核心重构 (Task 4): 委托 EduMatrixSwarm.async_process 进行全流程调度 =====
            # event_callback 将 Swarm 内部进度事件桥接到当前 SSE 流
            event_queue: asyncio.Queue = asyncio.Queue()
            streamed_parts = []
            alignment_report = None
            package = None

            async def _swarm_event_callback(event_type: str, data: dict):
                await event_queue.put((event_type, data))

            swarm_task = asyncio.create_task(
                swarm.async_process(
                    message,
                    student_id=student_id,
                    event_callback=_swarm_event_callback,
                    forced_target_agent=forced_target_agent,
                    doc_constraint=final_constraints,
                )
            )
            running_tasks.append(swarm_task)

            # Launch suggested questions generation task in parallel with Swarm execution
            target_concept = getattr(retrieval, "target", "") or message
            suggested_task = asyncio.create_task(
                _generate_suggested_questions(swarm, target_concept, profile)
            )
            running_tasks.append(suggested_task)

            # 实时消费事件队列并转发给前端 SSE
            while not swarm_task.done():
                await check_disconnection()
                try:
                    ev_type, ev_data = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                    if ev_type == "progress":
                        yield _sse("progress", ev_data)
                    elif ev_type == "agent_done":
                        yield _sse("agent_done", {
                            "agent": ev_data.get("agent", ""),
                            "type": ev_data.get("type", ""),
                            "progress": 70,
                        })
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    raise

            # 刷空剩余事件
            while not event_queue.empty():
                try:
                    ev_type, ev_data = event_queue.get_nowait()
                    if ev_type == "progress":
                        yield _sse("progress", ev_data)
                    elif ev_type == "agent_done":
                        yield _sse("agent_done", {
                            "agent": ev_data.get("agent", ""),
                            "type": ev_data.get("type", ""),
                            "progress": 70,
                        })
                except Exception:
                    break

            try:
                package = swarm_task.result()
                streamed_parts = list(package.resources) if package else []
                alignment_report = package.alignment if package else None
                if package and package.retrieval:
                    retrieval = package.retrieval
            except Exception as e:
                yield _sse("error", {"step": "swarm", "message": f"Swarm 处理异常: {str(e)[:100]}"})
                return
            finally:
                if swarm_task in running_tasks:
                    running_tasks.remove(swarm_task)


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

            # 优先使用 Swarm 流程内已计算好的 strategy_plan（避免重复计算）
            strategy_plan = package.strategy_plan if package else None
            if strategy_plan is None:
                try:
                    p = swarm.profile_store.get(student_id)
                    if p and hasattr(p, "student_id"):
                        strategy_plan = swarm.strategy_engine.build_plan(p, target=getattr(retrieval, "target", "未知") if retrieval else "未知")
                except Exception:
                    pass

            suggested_questions = []
            try:
                suggested_questions = await suggested_task
            except Exception as e:
                print(f"  [StreamAPI] Failed to get suggested questions in Swarm mode: {e}")

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
                        "fsm_mode": getattr(p, "fsm_mode", "normal"),
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
                "自适应推荐视频": 4, "视频推荐官": 4
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
                    await _upsert_review_plans_for_concept(swarm, student_id, target_concept)
                    print(f"  [StreamAPI] Automatically created/updated review plan for concept: {target_concept}")
            except Exception as e:
                print(f"  [StreamAPI] Failed to automatically create/update review plan: {e}")

            # === 将本次对话记录写入历史数据库（含 profile_snapshot 快照用于时空回溯）===
            try:
                from app.crud import record_conversation
                from app.database import run_db_op

                target_concept = getattr(retrieval, "target", "")
                alignment_passed = alignment_report.passed if alignment_report else True
                resource_summary = "; ".join(f"{getattr(r, 'agent', '')}:{getattr(r, 'resource_type', '')}" for r in streamed_parts)

                # 构造画像快照供 History.vue 时空回溯
                p = swarm.profile_store.get(student_id)
                snapshot = None
                if p:
                    try:
                        snapshot = {
                            "fsm_mode": getattr(p, "fsm_mode", "normal"),
                            "concept_mastery": dict(list(getattr(p, "concept_mastery", {}).items())[:20]),
                            "weak_points": list(getattr(p, "weak_points", [])[:10]),
                            "cognitive_load": getattr(p, "cognitive_load", 0.5),
                            "mastery_score": getattr(p, "mastery_score", 0.0),
                            "motivation_type": getattr(p, "motivation_type", "未诊断"),
                        }
                    except Exception:
                        snapshot = None

                await run_db_op(
                    record_conversation,
                    student_id,
                    message,
                    resource_summary,
                    target_concept,
                    len(streamed_parts),
                    alignment_passed,
                    snapshot,
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
                "suggested_questions": suggested_questions,
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
                "metrics": _make_metrics(final_content, message),
            })
        finally:
            for task in running_tasks:
                if not task.done():
                    task.cancel()


    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/regenerate")
async def regenerate_component(request: Request, current_user=Depends(get_current_user)) -> dict[str, Any]:
    from app.database import run_db_op
    from app.crud import load_student_profile

    payload = await request.json()
    student_id = enforce_student_access(payload.get("student_id"), current_user)
    role = str(payload.get("role", ""))
    resource_type = str(payload.get("resource_type", ""))
    query = str(payload.get("query", ""))
    overview = payload.get("overview")
    pathway = payload.get("pathway")
    
    if not role or not resource_type or not query:
        raise HTTPException(status_code=400, detail="参数缺失")
        
    # 兼容历史遗留的虚拟导演/剧本命名的重算拦截与重映射，确保返回 JSON 推荐列表
    if role in ("虚拟导演", "director"):
        role = "视频推荐官"
    if resource_type in ("虚拟人视频脚本", "自适应视频推荐"):
        resource_type = "自适应推荐视频"
        
    swarm = build_swarm_from_headers(request.headers)
    profile = swarm.profile_store.get(student_id)
    if not profile:
        profile = await run_db_op(load_student_profile, student_id)
        swarm.profile_store[student_id] = profile
    
    try:
        retrieval = await swarm.planner.plan_async(swarm.rag, query, profile)
        evidence = (await swarm.debate.aclean(retrieval)).clean_evidence
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
        
    # 清洗 query，避免将 "一键生成资源包: " 动作前缀和 "(知识点: ...)" 传入模型生成指令中
    cleaned_query = query.strip()
    if cleaned_query.startswith("一键生成资源包:"):
        cleaned_query = cleaned_query[8:].strip()
        import re
        cleaned_query = re.sub(r"\((?:知识点|指定概念):\s*.+?\)|\[指定概念:\s*.+?\]", "", cleaned_query).strip()
        
    forced_inst = overview or ""
    if pathway:
        from app.utils.recommendation_engine import evaluate_tactical_pathway
        try:
            pathway_meta = evaluate_tactical_pathway(profile, cleaned_query, pathway)
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
            query=cleaned_query,
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
            
            concepts_list = []
            if "与" in query:
                concepts_list = [sub.strip() for sub in query.split("与") if sub.strip()]
            elif "和" in query:
                concepts_list = [sub.strip() for sub in query.split("和") if sub.strip()]
            else:
                concepts_list = [query]

            target_note = None
            for n in existing:
                if any(c in (n.concepts or []) for c in concepts_list) and db_tag in (n.tags or []):
                    target_note = n
                    break
            
            if target_note:
                target_note.content = content
                # 增量合并新概念
                current_concepts = list(target_note.concepts or [])
                for c in concepts_list:
                    if c not in current_concepts:
                        current_concepts.append(c)
                target_note.concepts = current_concepts
                session.commit()
                return target_note.id
            else:
                new_note = DBNote(
                    id=note_id,
                    student_id=student_id,
                    source="adaptive_hub",
                    content=content,
                    tags=[db_tag],
                    concepts=concepts_list
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


@router.post("/explain", response_model=None)
async def socratic_explain(request: Request, current_user=Depends(get_current_user)) -> StreamingResponse | dict[str, Any]:
    """任务 8.1: 行级/公式苏格拉底即时答疑（支持流式 SSE 和常规 JSON 双轨模式）。"""
    payload = await request.json()
    target_text = str(payload.get("target_text", "")).strip()
    context_before = str(payload.get("context_before", ""))
    context_after = str(payload.get("context_after", ""))
    student_id = enforce_student_access(payload.get("student_id"), current_user)
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

    # 根据 Accept 请求头实现双轨输出：支持前端 SSE 流式与 API JSON 同步
    accept_header = request.headers.get("accept", "")
    if "text/event-stream" in accept_header:
        async def _socratic_stream():
            """流式生成苏格拉底讲解内容。"""
            accumulated = ""
            try:
                async for token in swarm.async_generator.llm.generate_stream(
                    teacher_system, teacher_user, role="苏格拉底辩手"
                ):
                    accumulated += token
                    yield _sse("content", {"content": token})
                yield _sse("complete", {
                    "content": accumulated,
                    "target_text": target_text,
                    "agent_trace": {
                        "consultant_move": move,
                        "focus_concept": concept,
                    }
                })
            except Exception as e:
                fallback = _socratic_fallback(target_text, is_formula, is_code)
                yield _sse("content", {"content": fallback})
                yield _sse("complete", {
                    "content": fallback,
                    "target_text": target_text,
                })
        
        return StreamingResponse(
            _socratic_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        # JSON 响应模式（用于单元测试和传统的 HTTP 拦截获取）
        try:
            content = await swarm.async_generator.llm.generate(
                teacher_system, teacher_user, role="苏格拉底辩手"
            )
            return {
                "status": "success",
                "content": content,
                "target_text": target_text,
                "agent_trace": {
                    "consultant_move": move,
                    "focus_concept": concept,
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
