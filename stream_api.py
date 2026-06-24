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


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat")
async def stream_chat(request: Request) -> StreamingResponse:
    payload = await request.json()
    message = str(payload.get("message", "")).strip()
    student_id = str(payload.get("student_id", "default"))

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

            async def _gen_one(role: str, rtype: str):
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
                    return _sse("agent_done", {"agent": role, "type": rtype, "progress": 50 + completed * 10})
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    completed += 1
                    return _sse("agent_done", {"agent": role, "type": rtype, "progress": 50 + completed * 10, "error": str(e)[:80]})

            tasks = [_gen_one(role, rt) for role, rt in agent_jobs]
            for task in asyncio.as_completed(tasks):
                await check_disconnection()
                chunk = await task
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
                        gather_coro = asyncio.gather(*coros, return_exceptions=True)
                        gather_task = asyncio.create_task(gather_coro)
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
    payload = await request.json()
    student_id = str(payload.get("student_id", "default"))
    role = str(payload.get("role", ""))
    resource_type = str(payload.get("resource_type", ""))
    query = str(payload.get("query", ""))
    
    if not role or not resource_type or not query:
        raise HTTPException(status_code=400, detail="参数缺失")
        
    swarm = build_swarm_from_headers(request.headers)
    profile = swarm.profile_store.get(student_id)
    
    try:
        retrieval = await swarm.planner.plan_async(swarm.rag, query, profile)
        evidence = swarm.debate.clean(retrieval).clean_evidence
        graph_context = retrieval.graph_context
    except Exception:
        evidence = []
        graph_context = ""
        
    try:
        result = await swarm.async_generator.generate(
            role=role,
            resource_type=resource_type,
            query=query,
            graph_context=graph_context,
            evidence=evidence,
            profile=profile,
        )
        content = result.content if hasattr(result, "content") else str(result)
        return {
            "status": "success",
            "content": content
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

    if not target_text:
        raise HTTPException(status_code=400, detail="target_text 不能为空")

    swarm = build_swarm_from_headers(request.headers)
    profile = swarm.profile_store.get(student_id)

    # 根据内容类型构建苏格拉底提示
    is_formula = any(c in target_text for c in ['\\', '∂', '∫', '∑', 'π', 'θ', '_', '^', 'lim', 'frac', 'partial'])
    is_code = 'def ' in target_text or 'import ' in target_text or 'class ' in target_text or '=' in target_text

    if is_formula:
        system = (
            "你是一位温和的苏格拉底导师。用户点击了一个数学公式，"
            "请用启发式分步推导解释这个公式。\n\n"
            "规则：\n"
            "1) 先问学生这个公式中每个符号表示什么，让学生自己回忆\n"
            "2) 再拆解公式结构，用通俗比喻解释\n"
            "3) 给出一个具体数值例子\n"
            "4) 最后问一个引导性问题确认理解\n"
            "5) 使用中文回复，保持简洁友善"
        )
        user = f"用户点击的公式: {target_text}\n上文: {context_before}\n下文: {context_after}"
    elif is_code:
        system = (
            "你是一位温和的苏格拉底导师。用户点击了一行代码，"
            "请用启发式方式解释这行代码的作用。\n\n"
            "规则：\n"
            "1) 先问学生你觉得这行代码在做什么\n"
            "2) 解释代码的关键部分和参数\n"
            "3) 给出一个简单的运行示例\n"
            "4) 最后问一个引导性问题\n"
            "5) 使用中文回复"
        )
        user = f"用户点击的代码: {target_text}\n上文: {context_before}\n下文: {context_after}"
    else:
        system = "你是一位温和的苏格拉底导师。用户选取了一段文本，请用启发式方式解释。"
        user = f"用户选取的内容: {target_text}\n上文: {context_before}\n下文: {context_after}"

    try:
        content = await swarm.async_generator.llm.generate(system, user, role="苏格拉底辩手")
        return {"status": "success", "content": content, "target_text": target_text}
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
