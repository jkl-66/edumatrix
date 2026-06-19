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
            from models import StudentProfile
            profile = swarm.profile_store.setdefault(student_id, StudentProfile(student_id=student_id))

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
                    yield _sse("agent_done", {"agent": role, "type": rtype, "progress": 50 + completed * 10})
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    completed += 1
                    yield _sse("agent_done", {"agent": role, "type": rtype, "progress": 50 + completed * 10, "error": str(e)[:80]})

            tasks = [_gen_one(role, rt) for role, rt in agent_jobs]
            for task in asyncio.as_completed(tasks):
                await check_disconnection()
                async for chunk in await task:
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

            final_content = ""
            for part in streamed_parts:
                if hasattr(part, "content") and hasattr(part, "resource_type"):
                    final_content += f"\n\n## {part.resource_type}\n\n{part.content}"

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

            safety_result = CONTENT_SAFETY.check_safety(final_content)
            if not safety_result["passed"]:
                final_content = f"[内容安全提示] 部分内容已过滤\n\n{CONTENT_SAFETY.sanitize(final_content)}"

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

            yield _sse("complete", {
                "target": getattr(retrieval, "target", ""),
                "content": final_content,
                "resources": [
                    {"agent": getattr(r, "agent", ""), "type": getattr(r, "resource_type", ""), "content": (getattr(r, "content", "") or "")[:200]}
                    for r in streamed_parts[:8]
                ],
                "safety": {
                    "passed": safety_result["passed"],
                    "issues_count": len(safety_result.get("issues", [])),
                },
                "profile": profile_data,
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
