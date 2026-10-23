"""Run the NOC-T23 learner-profile evaluation against the configured live model.

This is an explicit evidence command, not a production code path.  It writes
only under outputs/新意见重构执行/evidence/noc_t23 and never touches the
application database.  The model is always the configured DeepSeek endpoint;
if a call fails the failure is recorded instead of substituting local text.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import llm_client
from app.profile_adaptation import build_profile_adaptation, profile_prompt_context
from config import CONFIG
from stream_api import _canonical_chat_prompts


OUT = ROOT / "outputs" / "新意见重构执行" / "evidence" / "noc_t23"
OUT.mkdir(parents=True, exist_ok=True)
MODEL_CALL_TIMEOUT_SECONDS = 110
CORE_TERM_ALIASES = {
    "关键词检索": ("关键词检索", "关键字检索"),
    "向量检索": ("向量检索", "语义检索"),
    "混合检索": ("混合检索", "混合搜索"),
    "重排": ("重排", "重新排序", "统一排序", "排序融合"),
    "Recall@K": ("Recall@K", "Recall@k", "召回率"),
}


def _core_terms_found(text: str) -> list[str]:
    return [label for label, aliases in CORE_TERM_ALIASES.items() if any(alias in text for alias in aliases)]


def _evidence_resource_prompts(adaptation: dict[str, Any]) -> tuple[str, str]:
    """Build a bounded live-model prompt for the evidence run.

    The production resource path remains the source of truth and is covered by
    its own schema tests.  This evidence prompt asks the same configured model
    for a compact, inspectable handout so three profiles can be compared in a
    reasonable time while keeping all generated prose model-authored.
    """
    system = (
        "你是 EduMatrix 课程资源生成模型。只输出一个 JSON 对象，不要 Markdown、思维链或额外字段。"
        "字段必须为 summary、narrative、practiceSteps；summary 不超过 100 字，narrative 不超过 900 字，"
        "practiceSteps 恰好 4 个对象，每个对象包含 title、instruction、expectedResult、errorGuidance，"
        "每个字段不超过 100 字。围绕混合检索，严格落实 learner_adaptation 中的难度、表达、案例、"
        "提示和练习策略。课程证据不足的通用内容标注为‘通用拓展’，不得伪造来源。"
    )
    user = json.dumps(
        {
            "course": "检索工程与评估",
            "knowledge_point": "混合检索",
            "learning_goal": "掌握关键词与向量检索的组合、重排和 Recall@K 评估",
            "learner_adaptation": adaptation,
            "source": SOURCE,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return system, user


async def _live_evidence_resource(backend: Any, adaptation: dict[str, Any]) -> dict[str, Any]:
    system, user = _evidence_resource_prompts(adaptation)
    raw = await asyncio.wait_for(
        backend.generate(system, user, role="resource_generator"),
        timeout=MODEL_CALL_TIMEOUT_SECONDS,
    )
    payload = llm_client.parse_json_object(raw)
    if not str(payload.get("summary") or "").strip() or not str(payload.get("narrative") or "").strip():
        raise ValueError("真实模型返回缺少 summary 或 narrative")
    steps = payload.get("practiceSteps")
    if not isinstance(steps, list) or len(steps) != 4 or any(
        not isinstance(step, dict)
        or any(not str(step.get(key) or "").strip() for key in ("title", "instruction", "expectedResult", "errorGuidance"))
        for step in steps
    ):
        raise ValueError("真实模型返回的 practiceSteps 不是四个完整步骤")
    return payload


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

KNOWLEDGE_POINT = {"id": "kp-rag", "title": "混合检索", "code": "RAG-01"}
SOURCE = {
    "source_ref_id": "src-rag-industry-01",
    "title": "检索工程课程：混合检索与评估",
    "location_label": "第 2 章 / 第 3 节",
    "quote": (
        "关键词检索擅长精确术语、代码和 ID；向量检索通过 embedding 发现语义相似文本；"
        "混合检索需要统一排序并用 Recall@K 等指标评估。"
    ),
    "available": True,
}

PROFILES: list[dict[str, Any]] = [
    {
        "id": "beginner",
        "label": "零基础、岗位转型学习者",
        "major": "软件工程",
        "target_course": "检索工程入门",
        "knowledge_base": "零基础，第一次学习 RAG",
        "cognitive_style": "分步讲解",
        "motivation_type": "就业与岗位转型",
        "learning_goals": ["理解混合检索", "完成第一个检索评估任务"],
        "interaction_preferences": ["例子", "分步讲解"],
        "focus_level": 0.55,
        "cognitive_load": 0.8,
        "frustration_index": 0.35,
        "weak_points": ["混合检索"],
        "concept_mastery": {"kp-rag": 0.2},
        "dimension_states": {
            "knowledge_mastery": {"score": 0.2, "summary": "前置概念尚未稳定"},
            "cognitive_processing": {"score": 0.8, "summary": "一次处理的信息不宜过多"},
            "misconception_profile": {"score": 0.35, "summary": "需要先识别关键词与语义检索的区别"},
            "understanding_fluency_transfer": {"score": 0.25, "summary": "迁移到新查询需要示范"},
            "learning_strategy": {"score": 0.75, "summary": "适合短步骤和即时检查"},
            "metacognition": {"score": 0.4, "summary": "需要明确自检标准"},
            "motivation_and_purpose": {"score": 0.8, "summary": "以就业转型为目标"},
            "affect_resilience": {"score": 0.55, "summary": "任务过长时容易受挫"},
            "interaction_preference": {"score": 0.8, "summary": "偏好例子和分步讲解"},
            "learning_context": {"score": 0.5, "summary": "利用碎片时间学习"},
        },
    },
    {
        "id": "practitioner",
        "label": "有项目经验的工程学习者",
        "major": "数据科学与大数据技术",
        "target_course": "检索系统性能优化",
        "knowledge_base": "熟悉 Python、向量库和评估指标",
        "cognitive_style": "代码实操",
        "motivation_type": "项目交付",
        "learning_goals": ["优化检索召回", "完成岗位级评估报告"],
        "interaction_preferences": ["项目实践", "对比实验"],
        "focus_level": 0.9,
        "cognitive_load": 0.25,
        "frustration_index": 0.1,
        "weak_points": [],
        "concept_mastery": {"kp-rag": 0.86},
        "dimension_states": {
            "knowledge_mastery": {"score": 0.86, "summary": "基础概念已掌握"},
            "understanding_fluency_transfer": {"score": 0.9, "summary": "能迁移到新数据"},
            "misconception_profile": {"score": 0.2, "summary": "暂无明显概念误区"},
            "cognitive_processing": {"score": 0.25, "summary": "可同时比较多种方案"},
            "learning_strategy": {"score": 0.85, "summary": "偏好项目实践和对比实验"},
            "metacognition": {"score": 0.82, "summary": "能主动检查评估指标"},
            "motivation_and_purpose": {"score": 0.9, "summary": "以项目交付为目标"},
            "affect_resilience": {"score": 0.8, "summary": "能处理失败实验"},
            "interaction_preference": {"score": 0.9, "summary": "偏好代码和参数对比"},
            "learning_context": {"score": 0.65, "summary": "有稳定项目练习环境"},
        },
    },
    {
        "id": "theorist",
        "label": "理论基础强但有权重误区的学习者",
        "major": "人工智能",
        "target_course": "机器学习检索理论",
        "knowledge_base": "理论基础较强，但混合检索的权重选择容易混淆",
        "cognitive_style": "公式推导",
        "motivation_type": "研究与算法分析",
        "learning_goals": ["解释权重与重排边界", "识别检索指标误用"],
        "interaction_preferences": ["推导", "反例"],
        "focus_level": 0.85,
        "cognitive_load": 0.4,
        "frustration_index": 0.3,
        "weak_points": ["混合检索权重"],
        "concept_mastery": {"kp-rag": 0.58},
        "misconception_patterns": {"权重无需归一化": 0.8},
        "dimension_states": {
            "knowledge_mastery": {"score": 0.58, "summary": "机制理解基本形成"},
            "misconception_profile": {"score": 0.8, "summary": "需要用反例纠正权重误区"},
            "understanding_fluency_transfer": {"score": 0.6, "summary": "能解释机制但迁移仍需边界题"},
            "cognitive_processing": {"score": 0.45, "summary": "可处理公式和多条件比较"},
            "learning_strategy": {"score": 0.75, "summary": "偏好推导后验证"},
            "metacognition": {"score": 0.7, "summary": "能识别自己的权重误区"},
            "motivation_and_purpose": {"score": 0.85, "summary": "以研究与算法分析为目标"},
            "affect_resilience": {"score": 0.65, "summary": "愿意通过反例修正理解"},
            "interaction_preference": {"score": 0.8, "summary": "偏好公式推导和反例"},
            "learning_context": {"score": 0.7, "summary": "有研究资料和实验环境"},
        },
    },
]


def _profile_object(data: dict[str, Any]) -> SimpleNamespace:
    defaults = {
        "learning_goals": [],
        "interaction_preferences": [],
        "weak_points": [],
        "misconception_patterns": {},
        "dimension_states": {},
        "concept_mastery": {},
        "knowledge_traces": {},
    }
    defaults.update(data)
    return SimpleNamespace(**defaults)


def _manifest(adaptation: dict[str, Any], profile_id: str) -> dict[str, Any]:
    plan = profile_prompt_context(adaptation)
    return {
        "course_id": "course-rag-industry-v1",
        "knowledge_point_id": KNOWLEDGE_POINT["id"],
        "profile_snapshot_id": f"profile-{profile_id}-v1",
        "user_instruction": "请结合岗位实际说明如何组合关键词和语义检索并验证效果。",
        "context": {
            "course_title": "检索工程与评估",
            "knowledge_point_title": KNOWLEDGE_POINT["title"],
            "learning_goal": "掌握关键词与向量检索的组合、重排和 Recall@K 评估",
            "profile_adaptation": adaptation["summary"],
            "profile_adaptation_plan": plan,
            "profile_context": plan,
            "mastery_summary": f"当前知识点掌握度：{adaptation.get('point_mastery')}",
            "recent_learning_summary": "本次 NOC-T23 评估无额外学习事件。",
        },
    }


async def _run() -> dict[str, Any]:
    # Use the real configured provider with a bounded evidence-run budget.  The
    # production path still uses its configured max_tokens value.  Structured
    # resource responses contain a narrative plus four complete practice steps;
    # with DeepSeek reasoning enabled an 8k completion can be cut off before
    # the closing JSON brace.  Keep enough completion budget for one complete
    # response and record any provider failure instead of fabricating content.
    llm_client.CONFIG = replace(CONFIG, llm_timeout=120, llm_retry_max_attempts=2, llm_max_tokens=16384)
    llm_client._shared_httpx_client = None
    backend = llm_client.build_async_llm(
        provider="openai",
        endpoint=CONFIG.llm_endpoint,
        api_key=CONFIG.llm_api_key,
        model="deepseek-v4-flash",
        allow_fallback=False,
        thinking_mode="max",
        reasoning_effort="max",
        max_tokens=16384,
    )
    results: list[dict[str, Any]] = []
    for raw_profile in PROFILES:
        profile = _profile_object(raw_profile)
        adaptation = build_profile_adaptation(None, profile=profile, knowledge_point=KNOWLEDGE_POINT)
        manifest = _manifest(adaptation, raw_profile["id"])
        row: dict[str, Any] = {
            "profile": raw_profile,
            "adaptation": profile_prompt_context(adaptation),
            "model": {"provider": "openai-compatible", "model": "deepseek-v4-flash", "reasoning_effort": "max", "allow_fallback": False},
            "source": {"source_ref_id": SOURCE["source_ref_id"], "location": SOURCE["location_label"], "quote": SOURCE["quote"]},
            "resource": {},
            "conversation": {},
        }
        try:
            payload = await _live_evidence_resource(backend, row["adaptation"])
            content = "\n".join(
                [str(payload.get("summary") or ""), str(payload.get("narrative") or "")]
                + [str(step.get("instruction") or "") for step in payload.get("practiceSteps") or []]
            )
            narrative = str(payload.get("narrative") or "")
            row["resource"] = {
                "status": "succeeded",
                "generation_path": "live_model_evidence_prompt",
                "summary": str(payload.get("summary") or ""),
                "narrative_preview": narrative[:1200],
                "content_length": len(content),
                "practice_step_titles": [str(item.get("title") or "") for item in payload.get("practiceSteps") or []],
                "core_terms_found": _core_terms_found(content),
                "source_refs": [SOURCE["source_ref_id"]],
                "input_fingerprint": _canonical_hash({"profile": row["adaptation"], "source": SOURCE["source_ref_id"]}),
            }
        except Exception as exc:  # record the real provider failure, never fake success
            row["resource"] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}

        assistant = SimpleNamespace(content="")
        system_prompt, user_prompt, _ = _canonical_chat_prompts(
            {
                "history": [],
                "attachments": [],
                "source_materials": [{
                    "sourceRefId": SOURCE["source_ref_id"],
                    "title": SOURCE["title"],
                    "locationLabel": SOURCE["location_label"],
                    "quote": SOURCE["quote"],
                    "available": True,
                }],
                "context_snapshot": {
                    "profile_adaptation_plan": profile_prompt_context(adaptation),
                    "profile_adaptation_summary": adaptation["summary"],
                },
                "assistant_message": assistant,
                "user_message": SimpleNamespace(content="如何组合关键词和语义搜索，才能在岗位项目中提高检索质量？"),
            },
            "formal",
        )
        try:
            answer = await asyncio.wait_for(
                backend.generate(system_prompt, user_prompt, role="chat"),
                timeout=MODEL_CALL_TIMEOUT_SECONDS,
            )
            row["conversation"] = {
                "status": "succeeded",
                "answer": answer[:5000],
                "answer_length": len(answer),
                "source_refs": [SOURCE["source_ref_id"]] if SOURCE["source_ref_id"] in answer or "[S1]" in answer else [],
                "profile_terms_visible": [term for term in (adaptation["difficulty_label"], adaptation["explanation_style"].split("，")[0], adaptation["practice_strategy"].split("，")[0]) if term and term in answer],
                "prompt_contains_profile_plan": all(str(value) in user_prompt for value in (adaptation["difficulty_band"], adaptation["practice_strategy"])),
            }
        except Exception as exc:
            row["conversation"] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        results.append(row)
    report = {
        "task_id": "NOC-T23",
        "run_type": "live_model_evaluation",
        "model": {"provider": CONFIG.llm_provider, "endpoint": CONFIG.llm_endpoint, "model": "deepseek-v4-flash", "reasoning_effort": "max", "allow_fallback": False},
        "knowledge_point": KNOWLEDGE_POINT,
        "source": SOURCE,
        "profiles": results,
        "comparison": {
            "profile_count": len(results),
            "difficulty_bands": [item["adaptation"]["difficulty_band"] for item in results],
            "unique_adaptation_plans": len({json.dumps(item["adaptation"], ensure_ascii=False, sort_keys=True) for item in results}),
            "resource_success_count": sum(item["resource"].get("status") == "succeeded" for item in results),
            "conversation_success_count": sum(item["conversation"].get("status") == "succeeded" for item in results),
            "core_coverage": [len(item["resource"].get("core_terms_found", [])) / 5 for item in results],
        },
    }
    (OUT / "profile_evaluation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    result = asyncio.run(_run())
    print(json.dumps(result["comparison"], ensure_ascii=False, indent=2))
