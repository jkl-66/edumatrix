from __future__ import annotations

import hashlib
import json
import asyncio
import math
import re
from contextvars import ContextVar
from copy import copy
from time import perf_counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from app.database import (
    DBAssessmentQuestion, DBAssessmentQuestionVersion, DBArtifact, DBArtifactVersion,
    DBChapter, DBChapterKnowledgePoint, DBCourse, DBCourseMembership,
    DBGenerationTask, DBKnowledgePoint, DBLearningEvent, DBProfileSnapshot, DBStudentProfile, DBResourceBundle,
    DBResourceBundleItem, DBResourceBundleVersion, DBSourceRef,
    DBTaskEvent, DBTaskStep, DBTeachingAnimation, DBTeachingAnimationVersion, DBUser,
    DBVideoOutputVersion, DBVideoProject, DBVideoScriptVersion, DBWebDeck,
    DBWebDeckVersion,
)
from app.interactive_lab import LAB_INSTANCE_TYPE, LabTemplate, experiment_execution_info, get_template
from app.code_sandbox import validate_code
from app.exam_gate import ExamGateError, freeze_exam_gate_snapshot
from app.authorization import ObjectAccess, active_course_role, can_access_object
from app.m1_repository import (
    append_task_event,
    create_artifact_with_version,
    create_generation_task,
    create_task_step,
)
from app.m5_assessment_core import QuestionVersionInput, create_question_version, learner_safe_explanation
from app.learner_output import LEARNER_FEEDBACK_INSTRUCTION, completion_description, feynman_material_text, map_teaching_prose, resource_failure_feedback, teacher_text, video_recommendation_reason
from app.m5_resources import (
    canonical_resource_type,
    parse_code_sandbox_content,
    parse_deck_content,
    parse_handout_content,
    parse_interactive_model_content,
    parse_mindmap_content,
    parse_quiz_content,
    quiz_study_sessions,
    parse_video_recommendation_content,
)
from app.training_tasks import parse_training_task_content
from app.source_refs import project_source_ref, source_ref_teaching_text
from app.profile_adaptation import LEARNING_TASK_INSTRUCTION, TEACHING_ADAPTATION_INSTRUCTION, build_profile_adaptation, complete_learning_snapshot, profile_has_signal, profile_prompt_context, with_current_learning_evidence
from app.path_learning_context import PATH_CONTINUITY_GUIDANCE
from app.resource_generation_parts import generate_document_parts, generation_parts_key
from app.resource_review_parts import document_review_scopes, split_review_scope, combine_document_reviews, conditional_teaching_claims, apply_condition_review, validate_condition_review, resource_review_calculation_feedback, resource_review_condition_feedback, CONDITION_EQUIVALENCE_GUIDANCE
from app.resource_review_context import (requirements_snapshot, requirements_for, teaching_context,
    teaching_candidate, actual_review_dependencies, local_dependencies, review_findings, concise_review,
    unresolved_review_findings, merge_unresolved_review)
from llm_client import ModelOutputLimitError, build_async_llm, parse_json_object


_HANDOUT_META_SENTENCE = re.compile(
    r"(?:请(?:求)?输出[^。！？\n]{0,60}[，,:：]\s*)?"
    r"(?:直接把|围绕|将|把)\s*(?:当前知识点|目标知识点|这个知识点)[^。！？\n]{0,180}"
    r"(?:要求说明|请说明|要求比较|请比较|输出|返回)[^。！？\n]*(?:[。！？]|$)"
)
_HANDOUT_META_INLINE = re.compile(
    r"(?:(?:只输出|仅输出|请输出|返回一个|返回内容|输出内容)\s*(?:一个\s*)?JSON\s*(?:对象|格式)?|"
    r"handoutSections|learner_adaptation|source_ref_ids|sourceRefIds|提示词|生成规则|模型提示)"
    r"[^。！？\n]{0,140}(?:[。！？]|$)",
    flags=re.IGNORECASE,
)


def _handout_text(value: Any, *, preserve_boundary: bool = False) -> str:
    """Project model prose into a lesson, dropping instruction leakage only."""
    text = map_teaching_prose(value, _handout_prose)
    return text if preserve_boundary else text.strip()


def _handout_prose(value: str) -> str:
    text = teacher_text(value, preserve_boundary=True)
    if not text:
        return ""
    text = _HANDOUT_META_SENTENCE.sub("", text)
    text = _HANDOUT_META_INLINE.sub("", text)
    # These phrases are generation directions, not useful lesson content.
    text = re.sub(
        r"(?:要求|请)\s*(?:说明|比较|输出|返回)\s*(?:取舍|验证依据|完整内容|教学内容)[^。！？\n]*[。！？]?",
        "",
        text,
    )
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


_GENERIC_HANDOUT_GOALS = (
    "当前学习资源",
    "当前课程资源",
    "完成课程目标",
    "按既定学习目标完成本次资源学习",
    "完成本次资源学习",
)

_GENERIC_HANDOUT_TITLE_SUFFIXES = (
    "当前学习资源",
    "当前课程资源",
    "当前教材文件",
    "当前教材选区",
    "当前资源",
)


def _handout_learning_goal(value: Any, knowledge_point: str) -> str:
    """Keep concrete goals and replace only generic task-level placeholders."""

    goal = _handout_text(value)
    normalized = re.sub(r"[\s。.!！?？]+", "", goal)
    if not goal or any(normalized == re.sub(r"[\s。.!！?？]+", "", item) for item in _GENERIC_HANDOUT_GOALS):
        point = str(knowledge_point or "当前知识点").strip()
        return f"理解{point}的核心机制，并能在新的情境中应用和验证。"
    return goal


def _normalize_handout_title(value: Any, knowledge_point: str) -> str:
    """Replace only generic handout title suffixes with the bound point title."""

    title = " ".join(str(value or "").split()).strip()
    point = str(knowledge_point or "当前知识点").strip()
    if not title:
        return f"个性化讲义 · {point}"
    generic_titles = {
        suffix for suffix in _GENERIC_HANDOUT_TITLE_SUFFIXES
    } | {
        f"个性化讲义 · {suffix}" for suffix in _GENERIC_HANDOUT_TITLE_SUFFIXES
    }
    if title in generic_titles:
        return f"个性化讲义 · {point}"
    return title
from config import CONFIG
from instruct_rag import LEGACY_RESOURCE_PROMPTS, LEGACY_LEARNING_STRATEGY_PROMPTS


RESOURCE_TYPES = ("handout", "mind_map", "code", "exercise", "video", "ppt", "animation", "lab")
GENERATION_RESOURCE_TYPES = (
    "handout",
    "mind_map",
    "quiz",
    "training_task",
    "code_sandbox",
    "video",
    "deck",
    "interactive_model",
    "feynman",
)
GENERATION_SCHEMA_VERSION = "f2.resource-generation.v1"
GENERATION_CAPABILITY = "learning_resource_bundle.generate"
GENERATION_ROUTES = {
    "handout": "/workspace/resources/handouts/{resource_id}",
    "mind_map": "/workspace/resources/mindmaps/{resource_id}",
    "quiz": "/workspace/resources/quizzes/{resource_id}",
    "training_task": "/workspace/resources/training-tasks/{resource_id}",
    "code_sandbox": "/workspace/code/{resource_id}",
    "video": "/workspace/resources/videos/{resource_id}",
    "deck": "/workspace/resources/decks/{resource_id}",
    "interactive_model": "/workspace/resources/models/{resource_id}",
    "feynman": "/workspace/feynman/{resource_id}",
}
ARTIFACT_TYPES = {
    "handout": {"lesson", "lecture_note", "handout"},
    "mind_map": {"mindmap", "mind_map"},
    "code": {"code", "code_example", "notebook"},
    "lab": {LAB_INSTANCE_TYPE},
}
ROUTES = {
    "handout": "/resources", "mind_map": "/resources", "code": "/resources",
    "exercise": "/assessment", "video": "/video-studio", "ppt": "/web-decks",
    "animation": "/teaching-animations", "lab": "/interactive-lab",
}


class ResourceBundleError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise ResourceBundleError(code, message)


_QUIZ_DIFFICULTY_LABELS = {
    "easy": 0.3,
    "easiest": 0.2,
    "basic": 0.3,
    "beginner": 0.3,
    "simple": 0.3,
    "容易": 0.3,
    "简单": 0.3,
    "基础": 0.3,
    "基础应用": 0.3,
    "入门": 0.3,
    "medium": 0.5,
    "moderate": 0.5,
    "intermediate": 0.5,
    "standard": 0.5,
    "一般": 0.5,
    "中等": 0.5,
    "标准": 0.5,
    "hard": 0.7,
    "difficult": 0.7,
    "advanced": 0.7,
    "challenging": 0.7,
    "困难": 0.7,
    "较难": 0.7,
    "高级": 0.7,
    "进阶": 0.7,
    "挑战": 0.7,
}


_QUIZ_BLOOM_LEVELS = {
    "remember": "remember",
    "recall": "remember",
    "记忆": "remember",
    "记住": "remember",
    "understand": "understand",
    "comprehend": "understand",
    "理解": "understand",
    "掌握": "understand",
    "apply": "apply",
    "application": "apply",
    "应用": "apply",
    "运用": "apply",
    "analyze": "analyze",
    "analysis": "analyze",
    "分析": "analyze",
    "evaluate": "evaluate",
    "evaluation": "evaluate",
    "评价": "evaluate",
    "评估": "evaluate",
    "create": "create",
    "creation": "create",
    "创造": "create",
}


def _normalize_quiz_bloom(value: Any, *, default: str, position: int) -> str:
    """Normalize model-provided Bloom labels into the canonical enum."""
    candidate: Any = value
    if candidate is None or (isinstance(candidate, str) and not candidate.strip()):
        candidate = default
    label = str(candidate).strip().casefold().replace("层级", "").replace("level", "").strip()
    normalized = _QUIZ_BLOOM_LEVELS.get(label)
    if normalized is None:
        _fail(
            "resource_generation.model_output_invalid",
            f"真实模型返回的第 {position} 道题 Bloom 层级无法解析：{candidate!s}。",
        )
    return normalized


def _normalize_quiz_difficulty(value: Any, *, default: float, position: int) -> float:
    """Normalize model-provided quiz difficulty metadata without generating content.

    DeepSeek may return a semantic difficulty label (for example ``简单`` or
    ``medium``) even though the canonical question-version schema stores a
    number in ``[0, 1]``.  Known labels are an explicit schema adaptation; an
    unknown value remains a truthful model-output error instead of silently
    switching to a template or another provider.
    """
    candidate: Any = value
    if candidate is None or (isinstance(candidate, str) and not candidate.strip()):
        candidate = default
    if isinstance(candidate, bool):
        _fail("resource_generation.model_output_invalid", f"真实模型返回的第 {position} 道题难度无效。")
    if isinstance(candidate, (int, float)):
        difficulty = float(candidate)
    else:
        label = str(candidate).strip().casefold().replace("难度", "").strip()
        difficulty = _QUIZ_DIFFICULTY_LABELS.get(label)
        if difficulty is None:
            try:
                difficulty = float(label)
            except (TypeError, ValueError):
                _fail(
                    "resource_generation.model_output_invalid",
                    f"真实模型返回的第 {position} 道题难度无法解析：{candidate!s}。",
                )
    if not math.isfinite(difficulty) or not 0 <= difficulty <= 1:
        _fail("resource_generation.model_output_invalid", f"真实模型返回的第 {position} 道题难度超出 0 到 1 范围。")
    return difficulty


def _normalize_quiz_options(value: Any, *, position: int) -> tuple[str, ...]:
    """Convert model option shapes to the four readable option bodies.

    DeepSeek may return choices either as an array or as an ``A``–``D``
    object. Iterating the latter directly would persist only its keys, which
    is the user-visible ``A/B/C/D``-only failure. Preserve the model text and
    reject any shape that cannot provide four non-empty option bodies.
    """
    if isinstance(value, dict):
        normalized_keys = {str(key).strip().upper(): item for key, item in value.items()}
        raw_values = [normalized_keys[key] for key in ("A", "B", "C", "D") if key in normalized_keys]
        if len(raw_values) != 4:
            raw_values = list(value.values())
    elif isinstance(value, (list, tuple)):
        raw_values = list(value)
    else:
        raw_values = []

    options: list[str] = []
    for item in raw_values:
        if isinstance(item, dict):
            item = next(
                (item.get(key) for key in ("text", "content", "option", "value", "label") if item.get(key) not in (None, "")),
                "",
            )
        text = str(item or "").strip()
        if text:
            options.append(text)
    if len(options) != 4 or all(re.fullmatch(r"[A-D]", item, re.IGNORECASE) for item in options):
        _fail(
            "resource_generation.model_output_invalid",
            f"真实模型返回的第 {position} 道题必须包含四个非空选项正文。",
        )
    return tuple(options)


# A resource run may execute in a worker thread while the canonical Chat SSE
# consumer remains active.  The callback is deliberately limited to the
# already-sanitized public event payload produced by ``_resource_event``.
_RESOURCE_EVENT_CALLBACK: ContextVar[Callable[[dict[str, Any]], None] | None] = ContextVar(
    "resource_event_callback", default=None
)
_RESOURCE_PARTS: ContextVar[Any] = ContextVar("resource_generation_parts", default=None)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


_TRANSIENT_SOURCE_FIELDS = {"available", "reason_code", "reason", "route", "historical"}


def _stable_source_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in snapshot.items()
        if key not in _TRANSIENT_SOURCE_FIELDS
    }


def _source_snapshot_hash(snapshots: list[dict[str, Any]]) -> str:
    return _sha256_json([_stable_source_snapshot(item) for item in snapshots])


def _generation_input_snapshot(
    *,
    context: dict[str, Any],
    profile: DBProfileSnapshot,
    source_snapshots_by_type: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    source_hashes = {
        resource_type: _source_snapshot_hash(snapshots)
        for resource_type, snapshots in source_snapshots_by_type.items()
    }
    event_ids = list(context.get("recent_event_ids") or [])
    shared_sources = next(
        (snapshots for snapshots in source_snapshots_by_type.values() if snapshots),
        [],
    )
    knowledge_point = str(context.get("knowledge_point_title") or "当前知识点")
    shared_semantic_context = {
        "conversation_source": context.get("conversation_source"),
        "teaching_scope": context.get("teaching_scope"),
        "path_learning_context": context.get("path_learning_context"),
        "long_term_memory": context.get("long_term_memory"),
        "course_title": context.get("course_title"),
        "knowledge_point_title": knowledge_point,
        "learning_goal": context.get("learning_goal"),
        "profile_adaptation": context.get("profile_adaptation"),
        "profile_adaptation_plan": context.get("profile_adaptation_plan"),
        "profile_context": context.get("profile_context"),
        "mastery_summary": context.get("mastery_summary"),
        "recent_learning_summary": context.get("recent_learning_summary"),
        "source_semantic_anchor": _source_semantic_anchor(shared_sources),
        "practical_focus": _practical_focus(knowledge_point, shared_sources),
        "source_ref_ids": [str(item.get("source_ref_id") or "") for item in shared_sources],
    }
    return {
        "schema_version": "pr-01.resource-input-snapshot.v1",
        "conversation_source": context.get("conversation_source"),
        "teaching_scope": context.get("teaching_scope"),
        "path_learning_context": context.get("path_learning_context"),
        "long_term_memory": context.get("long_term_memory"),
        "course_title": context.get("course_title"),
        "knowledge_point_title": context.get("knowledge_point_title"),
        "learning_goal": context.get("learning_goal"),
        "profile_adaptation": context.get("profile_adaptation"),
        "profile_adaptation_plan": context.get("profile_adaptation_plan"),
        "profile_context": context.get("profile_context"),
        "mastery_summary": context.get("mastery_summary"),
        "recent_learning_summary": context.get("recent_learning_summary"),
        "profile_snapshot_id": profile.id,
        "profile_snapshot_hash": _sha256_json(profile.snapshot or {}),
        "recent_event_cursor": _sha256_json(event_ids),
        "recent_event_count": len(event_ids),
        "source_snapshot_hashes": source_hashes,
        "source_snapshots": source_snapshots_by_type,
        "semantic_context": shared_semantic_context,
        "input_snapshot_hash": _sha256_json({
            "course_title": context.get("course_title"),
            "knowledge_point_title": context.get("knowledge_point_title"),
            "learning_goal": context.get("learning_goal"),
            "profile_adaptation": context.get("profile_adaptation"),
            "profile_adaptation_plan": context.get("profile_adaptation_plan"),
            "profile_context": context.get("profile_context"),
            "mastery_summary": context.get("mastery_summary"),
            "recent_learning_summary": context.get("recent_learning_summary"),
            "profile_snapshot_hash": _sha256_json(profile.snapshot or {}),
            "recent_event_cursor": _sha256_json(event_ids),
            "source_snapshot_hashes": source_hashes,
            "semantic_context": shared_semantic_context,
        }),
    }


def _source_semantic_anchor(source_snapshots: list[dict[str, Any]]) -> str:
    source = source_snapshots[0] if source_snapshots else {}
    title = str(source.get("title") or "预置课程来源")
    location = str(source.get("location_label") or source.get("location_kind") or "课程章节")
    quote = _public_source_excerpt(source.get("quote"))
    return (
        f"来源锚点：{title} · {location}；课程摘录：{quote}"
        if quote
        else f"来源锚点：{title} · {location}；课程摘录：当前来源未提供可展示摘录。"
    )


def _practical_focus(knowledge_point: str, source_snapshots: list[dict[str, Any]]) -> str:
    source_text = " ".join(
        str(item.get("quote") or "") for item in source_snapshots
    )
    knowledge_title = str(knowledge_point or "").strip()
    knowledge_text = knowledge_title.casefold()
    text = f"{knowledge_text} {source_text}".casefold()
    if "python" in knowledge_text and any(term in knowledge_text for term in ("编程", "基础", "入门")):
        return "Python 数据类型、控制流程、函数与数据处理验证"
    # The knowledge-point title is the primary intent signal.  Source quotes
    # may mention a neighbouring topic (for example a generic RAG example in
    # a chapter source) and must not hijack the exercise family.
    if any(term in knowledge_text for term in ("分类", "阈值", "混淆矩阵", "误报", "精确率", "召回率", "precision", "recall")):
        return "分类决策、指标权衡与误差诊断"
    if any(term in knowledge_text for term in ("rag", "检索", "重排", "embedding", "召回", "top-k", "top k", "retrieval")):
        return "混合检索与证据质量评估"
    if any(term in knowledge_text for term in ("二分", "边界查找", "binary search", "查找与边界")):
        return "二分查找、边界不变量与复杂度验证"
    if any(term in knowledge_text for term in ("向量、矩阵", "向量矩阵", "矩阵", "线性代数", "概率基础", "梯度与自动微分")):
        return "向量矩阵运算、概率归一化与数值验证"
    if any(term in knowledge_text for term in ("反向传播", "前向传播", "感知机", "梯度", "学习率", "优化", "收敛", "gradient", "optimizer")):
        return "前向计算、梯度核对与参数更新验证"
    if any(term in knowledge_text for term in ("回归", "损失函数", "拟合", "regression")):
        return "回归建模、损失观察与泛化诊断"
    if any(term in knowledge_text for term in ("聚类", "k-means", "无监督", "cluster")):
        return "数据分布、聚类选择与结果解释"
    # A title outside these familiar families is still an explicit topic.
    # A whole textbook can mention every family, so do not replace an unknown
    # but specific title with the first keyword found in its source excerpt.
    if knowledge_title and knowledge_title not in {"当前知识点", "未指定知识点"}:
        return f"{knowledge_title}的实践与结果解释"
    # Legacy requests without a concrete topic may still use source evidence.
    if re.search(r"\brag\b", text) or any(term in text for term in ("检索", "重排", "embedding", "top-k", "top k", "retrieval")):
        return "混合检索与证据质量评估"
    if any(term in text for term in ("分类", "阈值", "混淆矩阵", "误报", "精确率", "召回率", "precision", "recall")):
        return "分类决策、指标权衡与误差诊断"
    if any(term in text for term in ("二分", "边界查找", "binary search", "查找与边界")):
        return "二分查找、边界不变量与复杂度验证"
    if any(term in text for term in ("向量、矩阵", "向量矩阵", "矩阵", "线性代数", "概率基础", "梯度与自动微分")):
        return "向量矩阵运算、概率归一化与数值验证"
    if any(term in text for term in ("梯度", "学习率", "优化", "收敛", "gradient", "optimizer")):
        return "优化过程、收敛观察与参数诊断"
    if any(term in text for term in ("聚类", "k-means", "无监督", "cluster")):
        return "数据分布、聚类选择与结果解释"
    if any(term in text for term in ("回归", "损失函数", "拟合", "regression")):
        return "回归建模、损失观察与泛化诊断"
    return "课程来源驱动的模型实验与结果解释"


def _semantic_context(
    *,
    manifest: dict[str, Any],
    knowledge_point: str,
    source_snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return the safe, shared semantic context used by every generated artifact."""
    context = _public_generation_context(manifest)
    input_snapshot = dict(manifest.get("input_snapshot") or {})
    source_hash = _source_snapshot_hash(source_snapshots)
    practical_focus = _practical_focus(knowledge_point, source_snapshots)
    semantic = {
        "course_title": context.get("course_title"),
        "knowledge_point_title": knowledge_point,
        "learning_goal": context.get("learning_goal"),
        "profile_adaptation": context.get("profile_adaptation"),
        "profile_adaptation_plan": context.get("profile_adaptation_plan"),
        "profile_context": context.get("profile_context"),
        "mastery_summary": context.get("mastery_summary"),
        "recent_learning_summary": context.get("recent_learning_summary"),
        "source_semantic_anchor": _source_semantic_anchor(source_snapshots),
        "practical_focus": practical_focus,
        "source_snapshot_hash": source_hash,
        "profile_snapshot_hash": input_snapshot.get("profile_snapshot_hash"),
        "recent_event_cursor": input_snapshot.get("recent_event_cursor"),
        "input_snapshot_hash": input_snapshot.get("input_snapshot_hash"),
        "source_ref_ids": [str(item.get("source_ref_id") or "") for item in source_snapshots],
    }
    semantic["semantic_input_fingerprint"] = _sha256_json({
        key: value for key, value in semantic.items() if key != "source_semantic_anchor"
    })
    return semantic


def _version_generation_metadata(
    *,
    manifest: dict[str, Any],
    resource_type: str,
    source_snapshots: list[dict[str, Any]],
    content: str,
    question_version_ids: list[str],
    task_id: str,
    attempt: int,
    completion_rule: str,
    generation_mode: str = "deterministic_fallback",
    model: str = "deterministic",
    reasoning_effort: str = "",
) -> dict[str, Any]:
    context = _public_generation_context(manifest)
    knowledge_point = str(context.get("knowledge_point_title") or manifest.get("knowledge_point_id") or "当前知识点")
    semantic = _semantic_context(
        manifest=manifest,
        knowledge_point=knowledge_point,
        source_snapshots=source_snapshots,
    )
    input_snapshot = dict(manifest.get("input_snapshot") or {})
    semantic["content_semantic_fingerprint"] = _sha256_json({
        "resource_type": resource_type,
        "content": content,
        "semantic_input_fingerprint": semantic["semantic_input_fingerprint"],
    })
    return {
        "schema_version": "f2.resource.v1",
        "resource_type": resource_type,
        "knowledge_point_id": manifest.get("knowledge_point_id"),
        "profile_snapshot_id": manifest.get("profile_snapshot_id"),
        "profile_snapshot_hash": input_snapshot.get("profile_snapshot_hash"),
        "recent_event_cursor": input_snapshot.get("recent_event_cursor"),
        "source_ref_ids": semantic["source_ref_ids"],
        "source_snapshot": source_snapshots,
        "source_snapshot_hash": semantic["source_snapshot_hash"],
        "source_snapshot_hashes": input_snapshot.get("source_snapshot_hashes") or {},
        "input_snapshot_hash": input_snapshot.get("input_snapshot_hash"),
        "semantic_input_fingerprint": semantic["semantic_input_fingerprint"],
        "content_semantic_fingerprint": semantic["content_semantic_fingerprint"],
        "semantic_context": {
            key: value for key, value in semantic.items()
            if key not in {"source_ref_ids", "source_snapshot_hash", "profile_snapshot_hash", "recent_event_cursor", "input_snapshot_hash"}
        },
        "generation_mode": generation_mode,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "canonical_binding": {
            "schema_version": "edumatrix.canonical-resource-binding.v1",
            "artifact_id": None,
            "artifact_version_id": None,
            "resource_type": resource_type,
            "course_id": manifest.get("course_id"),
            "knowledge_point_id": manifest.get("knowledge_point_id"),
            "chapter_id": (manifest.get("context") or {}).get("chapter_id"),
            "profile_snapshot_id": manifest.get("profile_snapshot_id"),
            "source_ref_ids": list(semantic["source_ref_ids"]),
            "source_snapshot": source_snapshots,
            "source_snapshot_hash": semantic["source_snapshot_hash"],
        },
        "generation_job_id": task_id,
        "active_requirements": requirements_for(manifest, [resource_type]),
        "generation_item_attempt": attempt,
        "completion_rule": completion_rule,
        "question_version_ids": question_version_ids,
    }


def _generation_source_snapshots(
    db: Any,
    *,
    task: DBGenerationTask,
    manifest: dict[str, Any],
    item: dict[str, Any],
    resource_type: str,
) -> list[dict[str, Any]]:
    """Validate current source identity, then generate from the frozen request snapshot."""
    current = _source_snapshots(
        db,
        course_id=task.course_id,
        source_ref_ids=list(item.get("source_ref_ids") or []),
        require_available=True,
    )
    frozen = ((manifest.get("input_snapshot") or {}).get("source_snapshots") or {}).get(resource_type)
    if not frozen:
        return current
    expected_hash = ((manifest.get("input_snapshot") or {}).get("source_snapshot_hashes") or {}).get(resource_type)
    if expected_hash and _source_snapshot_hash(current) != expected_hash:
        _fail("resource_generation.source_snapshot_changed", "课程来源在生成前发生变化，请重新生成资源。")
    return [dict(snapshot) for snapshot in frozen]


def _attach_canonical_binding_identity(
    db: Any,
    *,
    artifact: DBArtifact,
    version: DBArtifactVersion,
    resource_type: str,
    content: str,
) -> None:
    """Complete the binding after the canonical artifact and version IDs exist."""
    metadata = dict(version.metadata_json or {})
    binding = dict(metadata.get("canonical_binding") or {})
    binding.update({
        "artifact_id": artifact.id,
        "artifact_version_id": version.id,
        "resource_type": resource_type,
        "course_id": artifact.course_id,
    })
    if resource_type == "mind_map" and version.content_format == "json":
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            payload = {}
        linked_ids = [
            str(resource_id)
            for node in payload.get("nodes", [])
            if isinstance(node, dict)
            for resource_id in node.get("linkedResourceIds", []) or []
            if str(resource_id).strip()
        ] if isinstance(payload, dict) else []
        linked_bindings = []
        for linked_id in dict.fromkeys(linked_ids):
            linked = db.get(DBArtifact, linked_id)
            linked_version = (
                db.get(DBArtifactVersion, linked.current_version_id)
                if linked is not None and linked.current_version_id else None
            )
            if linked is None or linked_version is None or linked.owner_public_id != artifact.owner_public_id:
                linked_bindings.append({"artifact_id": linked_id, "available": False})
                continue
            linked_metadata = dict(linked_version.metadata_json or {})
            linked_bindings.append({
                "artifact_id": linked.id,
                "artifact_version_id": linked_version.id,
                "resource_type": canonical_resource_type(linked.artifact_type, linked_metadata),
                "course_id": linked.course_id,
                "source_ref_ids": list(linked_metadata.get("source_ref_ids") or []),
                "available": linked.archived_at is None,
            })
        binding["linked_resource_bindings"] = linked_bindings
    metadata["canonical_binding"] = binding
    version.metadata_json = metadata


def _legal_video_catalog() -> list[dict[str, Any]]:
    path = Path(__file__).resolve().parents[1] / "data" / "raw" / "videos_metadata" / "legal_video_catalog.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in payload.get("items", []) if isinstance(item, dict)]


def _video_recommendations(knowledge_point: str, source_ids: list[str]) -> list[dict[str, Any]]:
    query = knowledge_point.casefold()
    catalog = _legal_video_catalog()
    ranked = sorted(
        catalog,
        key=lambda item: (
            -sum(1 for topic in item.get("topics") or [] if str(topic).casefold() in query or query in str(topic).casefold()),
            str(item.get("source_key") or ""),
        ),
    )
    recommendations = []
    for item in ranked[:3]:
        url = str(item.get("url") or "").strip()
        if not url.startswith("https://"):
            continue
        recommendations.append({
            "id": str(item.get("source_key") or f"video-{len(recommendations) + 1}"),
            "title": str(item.get("title") or "课程视频来源"),
            "sourceKind": "external_url",
            "availability": "external_only",
            "url": url,
            "localRef": None,
            "durationSeconds": None,
            "author": str(item.get("source_author") or "来源页标注作者"),
            "language": str(item.get("language") or "未标注"),
            "licenseStatus": str(item.get("license_status") or "reference_only_unverified"),
            "licenseLabel": str(item.get("license_label") or "许可状态以来源页为准，仅提供外链。"),
            "licenseUrl": str(item.get("license_url") or url),
            "reason": str(item.get("selection_rationale") or f"与“{knowledge_point}”的课程学习目标相关。"),
            "segments": [],
            "sourceRefIds": source_ids,
            "alternatives": [],
        })
    if recommendations:
        for index, recommendation in enumerate(recommendations):
            alternative = recommendations[(index + 1) % len(recommendations)]
            if alternative["id"] != recommendation["id"]:
                recommendation["alternatives"] = [{
                    "id": f"alternative-{alternative['id']}",
                    "title": alternative["title"],
                    "url": alternative["url"],
                    "reason": "当前来源无法访问时，可改用另一条已登记课程来源。",
                }]
    return recommendations


def _course(db: Any, actor: DBUser, course_id: str) -> DBCourse:
    from course_catalog import course_is_selectable
    row = db.get(DBCourse, course_id)
    if row is None:
        _fail("resource_bundle.course_unknown", "课程不存在")
    role = active_course_role(db, course_id=row.id, user_public_id=actor.public_id)
    if not can_access_object(actor, ObjectAccess("course", row.id, owner_public_id=row.owner_public_id, course_id=row.id, visibility=row.visibility), action="read", course_role=role):
        _fail("resource_bundle.course_forbidden", "无权访问该课程")
    if not course_is_selectable(db, row):
        _fail("resource_bundle.course_unavailable", "这门课程已停止发布或当前没有可用学习资料")
    return row


def _owned(db: Any, actor: DBUser, bundle_id: str) -> DBResourceBundle:
    row = db.get(DBResourceBundle, bundle_id)
    if row is None:
        _fail("resource_bundle.unknown", "资源包不存在")
    if row.owner_public_id != actor.public_id:
        _fail("resource_bundle.forbidden", "无权访问该资源包")
    return row


def _artifact(db: Any, actor: DBUser, course_id: str, resource_type: str, resource_id: str, version_id: str) -> dict[str, Any]:
    row = db.get(DBArtifact, resource_id)
    version = db.get(DBArtifactVersion, version_id)
    if row is None or version is None or version.artifact_id != resource_id:
        _fail("resource_bundle.resource_unknown", f"{resource_type} 资源或版本不存在")
    if row.owner_public_id != actor.public_id:
        _fail("resource_bundle.resource_forbidden", f"无权引用 {resource_type} 资源")
    if row.course_id not in {None, course_id}:
        _fail("resource_bundle.resource_course_conflict", f"{resource_type} 不属于当前课程")
    if row.artifact_type not in ARTIFACT_TYPES[resource_type]:
        _fail("resource_bundle.resource_type_mismatch", f"资源不是合法的 {resource_type} 类型")
    metadata = version.metadata_json or {}
    source_refs = metadata.get("source_ref_ids") or metadata.get("source_refs") or []
    quality = metadata.get("quality") or {"status": row.status, "recorded": False}
    return {"title": row.title, "resource_status": row.status, "source_refs": source_refs, "quality": quality,
            "profile": metadata.get("profile") or {"scope": "not_recorded"}, "content_hash": version.content_hash,
            "artifact_type": row.artifact_type, "boundary": "旧资源缺失的来源或质量字段按 not_recorded 展示，不补造证据。"}


def _exercise(db: Any, actor: DBUser, course_id: str, resource_id: str, version_id: str) -> dict[str, Any]:
    row = db.get(DBAssessmentQuestion, resource_id)
    version = db.get(DBAssessmentQuestionVersion, version_id)
    if row is None or version is None or version.question_id != resource_id:
        _fail("resource_bundle.resource_unknown", "练习或版本不存在")
    if row.owner_public_id not in {None, actor.public_id}:
        _fail("resource_bundle.resource_forbidden", "无权引用该练习")
    if row.course_id != course_id:
        _fail("resource_bundle.resource_course_conflict", "练习不属于当前课程")
    if row.status != "approved":
        _fail("resource_bundle.resource_not_ready", "只有已批准练习可以加入资源包")
    return {"title": version.prompt[:120], "resource_status": row.status, "source_refs": version.source_ref_ids or [],
            "quality": {"status": "approved", "bloom_level": version.bloom_level, "sample_size": version.sample_size},
            "profile": {"difficulty": version.expert_difficulty, "bloom_level": version.bloom_level},
            "content_hash": version.content_hash, "question_type": row.question_type,
            "boundary": "系统批准状态不等同于真人专家认证。"}


def _video(db: Any, actor: DBUser, course_id: str, resource_id: str, version_id: str) -> dict[str, Any]:
    row = db.get(DBVideoProject, resource_id)
    version = db.get(DBVideoScriptVersion, version_id)
    if row is None or version is None or version.project_id != resource_id:
        _fail("resource_bundle.resource_unknown", "视频项目或脚本版本不存在")
    if row.owner_public_id != actor.public_id:
        _fail("resource_bundle.resource_forbidden", "无权引用该视频")
    if row.course_id not in {None, course_id}:
        _fail("resource_bundle.resource_course_conflict", "视频不属于当前课程")
    output = db.query(DBVideoOutputVersion).filter_by(project_id=row.id).order_by(DBVideoOutputVersion.version_number.desc()).first()
    return {"title": row.title, "resource_status": "rendered" if output else "script_only", "source_refs": [],
            "quality": output.quality_report if output else {"status": "script_only"},
            "profile": {"scope": "script_snapshot"}, "content_hash": version.content_hash,
            "duration_ms": output.duration_ms if output else version.total_duration_ms,
            "boundary": "本地生成或导入状态不等同于生产级媒体认证。"}


def _deck(db: Any, actor: DBUser, course_id: str, resource_id: str, version_id: str) -> dict[str, Any]:
    row = db.get(DBWebDeck, resource_id); version = db.get(DBWebDeckVersion, version_id)
    if row is None or version is None or version.deck_id != resource_id:
        _fail("resource_bundle.resource_unknown", "PPT 或版本不存在")
    if row.owner_public_id != actor.public_id: _fail("resource_bundle.resource_forbidden", "无权引用该 PPT")
    if row.course_id not in {None, course_id}: _fail("resource_bundle.resource_course_conflict", "PPT 不属于当前课程")
    return {"title": row.title, "resource_status": row.status, "source_refs": [], "quality": {"status": "structured", "slide_count": len(version.slides_snapshot)},
            "profile": {"modality": "visual"}, "content_hash": version.content_hash, "boundary": "结构化课件状态不等同于人工内容审核。"}


def _animation(db: Any, actor: DBUser, course_id: str, resource_id: str, version_id: str) -> dict[str, Any]:
    row = db.get(DBTeachingAnimation, resource_id); version = db.get(DBTeachingAnimationVersion, version_id)
    if row is None or version is None or version.animation_id != resource_id:
        _fail("resource_bundle.resource_unknown", "动画或版本不存在")
    if row.owner_public_id != actor.public_id: _fail("resource_bundle.resource_forbidden", "无权引用该动画")
    if row.course_id not in {None, course_id}: _fail("resource_bundle.resource_course_conflict", "动画不属于当前课程")
    return {"title": row.title, "resource_status": "ready", "source_refs": [], "quality": version.quality_snapshot,
            "profile": {"modality": "visual_interactive"}, "content_hash": version.content_hash,
            "boundary": "确定性教学动画不宣称覆盖全部学科仿真。"}


def _resolve(db: Any, actor: DBUser, course_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    kind = str(raw.get("resource_type", ""))
    resource_id = str(raw.get("resource_id", "")); version_id = str(raw.get("resource_version_id", ""))
    if kind not in RESOURCE_TYPES: _fail("resource_bundle.resource_type_invalid", "资源类型不受支持")
    if not resource_id or not version_id: _fail("resource_bundle.resource_identity_required", "资源和版本身份不能为空")
    actual_domain = None
    if db.get(DBArtifact, resource_id) is not None: actual_domain = "artifact"
    elif db.get(DBAssessmentQuestion, resource_id) is not None: actual_domain = "exercise"
    elif db.get(DBVideoProject, resource_id) is not None: actual_domain = "video"
    elif db.get(DBWebDeck, resource_id) is not None: actual_domain = "ppt"
    elif db.get(DBTeachingAnimation, resource_id) is not None: actual_domain = "animation"
    expected_domain = "artifact" if kind in ARTIFACT_TYPES else kind
    if actual_domain is not None and actual_domain != expected_domain:
        _fail("resource_bundle.resource_type_mismatch", f"资源实际属于 {actual_domain}，不能声明为 {kind}")
    if kind in ARTIFACT_TYPES: snapshot = _artifact(db, actor, course_id, kind, resource_id, version_id)
    elif kind == "exercise": snapshot = _exercise(db, actor, course_id, resource_id, version_id)
    elif kind == "video": snapshot = _video(db, actor, course_id, resource_id, version_id)
    elif kind == "ppt": snapshot = _deck(db, actor, course_id, resource_id, version_id)
    else: snapshot = _animation(db, actor, course_id, resource_id, version_id)
    return {"resource_type": kind, "resource_id": resource_id, "resource_version_id": version_id,
            "route": ROUTES[kind], **snapshot}


def _current_availability(db: Any, actor: DBUser, course_id: str, item: DBResourceBundleItem) -> dict[str, Any]:
    if (item.frozen_snapshot or {}).get("marketplace_copy_status") == "independent_personal_copy":
        artifact = db.get(DBArtifact, item.resource_id)
        version = db.get(DBArtifactVersion, item.resource_version_id)
        if (artifact is not None and version is not None and version.artifact_id == artifact.id
                and artifact.owner_public_id == actor.public_id and artifact.course_id == course_id
                and artifact.archived_at is None):
            return {"status": "available", "reason": "", "current_resource_status": artifact.status}
        return {"status": "unavailable", "reason": "这份个人资源暂时无法打开。"}
    try:
        current = _resolve(db, actor, course_id, {"resource_type": item.resource_type, "resource_id": item.resource_id, "resource_version_id": item.resource_version_id})
        return {"status": "available", "reason": "", "current_resource_status": current["resource_status"]}
    except ResourceBundleError as exc:
        return {"status": "unavailable", "reason": str(exc), "code": exc.code}


def _version_payload(db: Any, actor: DBUser, bundle: DBResourceBundle, version: DBResourceBundleVersion) -> dict[str, Any]:
    items = db.query(DBResourceBundleItem).filter_by(bundle_version_id=version.id).order_by(DBResourceBundleItem.position).all()
    return {"id": version.id, "version_number": version.version_number, "profile": version.profile_snapshot,
            "quality": version.quality_summary, "content_hash": version.content_hash, "change_summary": version.change_summary,
            "created_at": version.created_at, "items": [{"id": item.id, "position": item.position, **item.frozen_snapshot,
            "availability": _current_availability(db, actor, bundle.course_id, item)} for item in items]}


def _payload(db: Any, actor: DBUser, row: DBResourceBundle, include_versions: bool = True) -> dict[str, Any]:
    current = db.get(DBResourceBundleVersion, row.current_version_id) if row.current_version_id else None
    versions = db.query(DBResourceBundleVersion).filter_by(bundle_id=row.id).order_by(DBResourceBundleVersion.version_number.desc()).all() if include_versions else []
    return {"id": row.id, "title": row.title, "learning_objective": row.learning_objective, "course_id": row.course_id,
            "knowledge_point_id": row.knowledge_point_id, "status": row.status, "lock_version": row.lock_version,
            "current_version_id": row.current_version_id, "current_version": _version_payload(db, actor, row, current) if current else None,
            "versions": [{"id": v.id, "version_number": v.version_number, "content_hash": v.content_hash, "change_summary": v.change_summary, "created_at": v.created_at} for v in versions],
            "created_at": row.created_at, "updated_at": row.updated_at,
            "boundary": "资源包使用冻结合成画像和系统质量状态；不代表真人专家或企业认证。"}


def list_bundles(db: Any, actor: DBUser) -> dict[str, Any]:
    rows = db.query(DBResourceBundle).filter_by(owner_public_id=actor.public_id).order_by(DBResourceBundle.updated_at.desc()).all()
    return {"items": [_payload(db, actor, row, False) for row in rows], "count": len(rows)}


def list_generation_jobs(
    db: Any,
    actor: DBUser,
    *,
    course_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    from course_catalog import course_is_selectable
    query = db.query(DBGenerationTask).filter_by(
        owner_public_id=actor.public_id,
        capability=GENERATION_CAPABILITY,
    )
    if course_id:
        query = query.filter(DBGenerationTask.course_id == course_id)
    rows = query.order_by(DBGenerationTask.updated_at.desc(), DBGenerationTask.id).limit(limit).all()
    rows = [row for row in rows if course_is_selectable(db, row.course_id)]
    return {"items": [generation_job_payload(db, actor, row.id) for row in rows], "count": len(rows)}


def workspace_context(db: Any, actor: DBUser) -> dict[str, Any]:
    from course_catalog import MASTER_COURSE_ID, course_is_selectable

    membership_ids = [row[0] for row in db.query(DBCourseMembership.course_id).filter_by(user_public_id=actor.public_id, status="active").all()]
    rows = db.query(DBCourse).filter(
        (DBCourse.visibility == "public") | (DBCourse.owner_public_id == actor.public_id) | (DBCourse.id.in_(membership_ids or ["__none__"]))
    ).order_by(DBCourse.title, DBCourse.id).all()
    rows = [row for row in rows if course_is_selectable(db, row)]
    rows.sort(key=lambda row: (0 if row.id == MASTER_COURSE_ID else 1, row.title, row.id))
    bundles = list_bundles(db, actor)
    return {"courses": [{"id": row.id, "title": row.title, "version": row.version, "visibility": row.visibility,
            "content_origin": row.content_origin, "license_text": row.license_text} for row in rows],
            "bundles": bundles["items"], "bundle_count": bundles["count"], "resource_types": list(RESOURCE_TYPES),
            "boundary": "课程按当前身份权限返回；资源包中的演示画像和系统质量状态不代表真人或企业认证。"}


def list_candidates(db: Any, actor: DBUser, course_id: str) -> dict[str, Any]:
    _course(db, actor, course_id)
    candidates: list[dict[str, Any]] = []
    for row in db.query(DBArtifact).filter_by(owner_public_id=actor.public_id).filter(DBArtifact.course_id.in_([course_id, None])).all():
        kind = next((key for key, values in ARTIFACT_TYPES.items() if row.artifact_type in values), None)
        if kind and row.current_version_id:
            candidates.append({"resource_type": kind, "resource_id": row.id, "resource_version_id": row.current_version_id, "title": row.title, "status": row.status})
    for row in db.query(DBAssessmentQuestion).filter_by(course_id=course_id, status="approved").all():
        if row.current_version_id and row.owner_public_id in {None, actor.public_id}:
            version = db.get(DBAssessmentQuestionVersion, row.current_version_id)
            candidates.append({"resource_type": "exercise", "resource_id": row.id, "resource_version_id": row.current_version_id, "title": version.prompt[:120] if version else "练习", "status": row.status})
    for row in db.query(DBVideoProject).filter_by(owner_public_id=actor.public_id).filter(DBVideoProject.course_id.in_([course_id, None])).all():
        if row.current_script_version_id: candidates.append({"resource_type": "video", "resource_id": row.id, "resource_version_id": row.current_script_version_id, "title": row.title, "status": row.status})
    for row in db.query(DBWebDeck).filter_by(owner_public_id=actor.public_id).filter(DBWebDeck.course_id.in_([course_id, None])).all():
        if row.current_version_id: candidates.append({"resource_type": "ppt", "resource_id": row.id, "resource_version_id": row.current_version_id, "title": row.title, "status": row.status})
    for row in db.query(DBTeachingAnimation).filter_by(owner_public_id=actor.public_id).filter(DBTeachingAnimation.course_id.in_([course_id, None])).all():
        if row.current_version_id: candidates.append({"resource_type": "animation", "resource_id": row.id, "resource_version_id": row.current_version_id, "title": row.title, "status": "ready"})
    candidates.sort(key=lambda item: (RESOURCE_TYPES.index(item["resource_type"]), item["title"], item["resource_id"]))
    grouped = {kind: [item for item in candidates if item["resource_type"] == kind] for kind in RESOURCE_TYPES}
    return {"course_id": course_id, "types": list(RESOURCE_TYPES), "items": candidates, "grouped": grouped,
            "count": len(candidates), "boundary": "候选来自当前账号可访问的真实对象和当前版本；加入资源包后不会静默换版。"}


def create_bundle(db: Any, actor: DBUser, title: str, learning_objective: str, course_id: str,
                  knowledge_point_id: str | None, profile: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    _course(db, actor, course_id)
    if knowledge_point_id:
        kp = db.get(DBKnowledgePoint, knowledge_point_id)
        if kp is None: _fail("resource_bundle.knowledge_point_unknown", "知识点不存在")
    clean_title = " ".join(title.split())[:256]; clean_objective = " ".join(learning_objective.split())[:2000]
    if not clean_title or not clean_objective: _fail("resource_bundle.text_required", "标题和学习目标不能为空")
    row = DBResourceBundle(owner_public_id=actor.public_id, course_id=course_id, knowledge_point_id=knowledge_point_id,
                           title=clean_title, learning_objective=clean_objective)
    db.add(row); db.flush()
    result = create_version(db, actor, row.id, profile, items, 1, "初始资源包")
    result["created"] = True
    return result


def create_version(db: Any, actor: DBUser, bundle_id: str, profile: dict[str, Any], items: list[dict[str, Any]], expected_lock_version: int, change_summary: str) -> dict[str, Any]:
    row = _owned(db, actor, bundle_id)
    if row.lock_version != expected_lock_version: _fail("resource_bundle.conflict", "资源包已更新，请刷新后重试")
    if not 1 <= len(items) <= 8: _fail("resource_bundle.item_count", "资源包必须包含 1 到 8 类资源")
    kinds = [str(item.get("resource_type", "")) for item in items]
    if len(set(kinds)) != len(kinds): _fail("resource_bundle.duplicate_type", "同一版本每类资源只能出现一次")
    resolved = [_resolve(db, actor, row.course_id, item) for item in items]
    clean_profile = {str(k)[:64]: str(v)[:256] for k, v in sorted((profile or {}).items())[:12]}
    identity = {"profile": clean_profile, "items": [{"resource_type": x["resource_type"], "resource_id": x["resource_id"], "resource_version_id": x["resource_version_id"], "snapshot": x} for x in resolved]}
    content_hash = hashlib.sha256(_canonical(identity).encode()).hexdigest()
    existing = db.query(DBResourceBundleVersion).filter_by(bundle_id=row.id, content_hash=content_hash).one_or_none()
    if existing: return {**_payload(db, actor, row), "version_created": False}
    quality = {"resource_count": len(resolved), "covered_types": kinds, "coverage": round(len(set(kinds)) / 8, 4),
               "all_available_at_freeze": True, "quality_states": {x["resource_type"]: x["resource_status"] for x in resolved}}
    version = DBResourceBundleVersion(bundle_id=row.id, version_number=db.query(DBResourceBundleVersion).filter_by(bundle_id=row.id).count() + 1,
        profile_snapshot=clean_profile, quality_summary=quality, content_hash=content_hash, change_summary=" ".join(change_summary.split())[:256], created_by_public_id=actor.public_id)
    db.add(version); db.flush()
    for position, snapshot in enumerate(resolved):
        db.add(DBResourceBundleItem(bundle_version_id=version.id, position=position, resource_type=snapshot["resource_type"],
            resource_id=snapshot["resource_id"], resource_version_id=snapshot["resource_version_id"], frozen_snapshot=snapshot))
    row.current_version_id = version.id; row.lock_version += 1; db.flush()
    return {**_payload(db, actor, row), "version_created": True}


def get_bundle(db: Any, actor: DBUser, bundle_id: str) -> dict[str, Any]:
    return _payload(db, actor, _owned(db, actor, bundle_id))


def restore_version(db: Any, actor: DBUser, bundle_id: str, version_id: str, expected_lock_version: int) -> dict[str, Any]:
    row = _owned(db, actor, bundle_id)
    if row.lock_version != expected_lock_version: _fail("resource_bundle.conflict", "资源包已更新，请刷新后重试")
    version = db.get(DBResourceBundleVersion, version_id)
    if version is None or version.bundle_id != row.id: _fail("resource_bundle.version_unknown", "资源包版本不存在")
    row.current_version_id = version.id; row.lock_version += 1; db.flush()
    return _payload(db, actor, row)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _generation_task(db: Any, actor: DBUser, task_id: str) -> DBGenerationTask:
    task = db.get(DBGenerationTask, task_id)
    if task is None or task.capability != GENERATION_CAPABILITY:
        _fail("resource_generation.unknown", "资源生成任务不存在")
    if task.owner_public_id != actor.public_id:
        _fail("resource_generation.forbidden", "无权访问该资源生成任务")
    return task


def _profile_snapshot(
    db: Any,
    actor: DBUser,
    profile_snapshot_id: str,
    *,
    course_id: str | None = None,
) -> DBProfileSnapshot:
    snapshot = db.get(DBProfileSnapshot, profile_snapshot_id)
    if snapshot is None:
        _fail("resource_generation.profile_unknown", "画像快照不存在")
    if snapshot.owner_public_id != actor.public_id:
        _fail("resource_generation.profile_forbidden", "画像快照不属于当前用户")
    if course_id:
        body = snapshot.snapshot if isinstance(snapshot.snapshot, dict) else {}
        snapshot_course_id = str(
            body.get("course_id")
            or (body.get("course_context") or {}).get("courseId")
            or ""
        ).strip()
        if snapshot_course_id and snapshot_course_id != course_id:
            _fail("resource_generation.profile_course_conflict", "画像快照不属于当前课程")
    return snapshot


def _knowledge_point(db: Any, course_id: str, knowledge_point_id: str | None) -> DBKnowledgePoint | None:
    # A Chat resource request may target the whole selected course.  A supplied
    # knowledge point is still validated against that course; an omitted one is
    # intentionally preserved as a course-level scope instead of choosing a
    # default point and narrowing the user's request.
    if not knowledge_point_id:
        return None
    point = db.get(DBKnowledgePoint, knowledge_point_id)
    if point is None:
        _fail("resource_generation.knowledge_point_unknown", "知识点不存在")
    linked = (
        db.query(DBChapterKnowledgePoint)
        .join(DBChapter, DBChapter.id == DBChapterKnowledgePoint.chapter_id)
        .filter(
            DBChapterKnowledgePoint.knowledge_point_id == point.id,
            DBChapter.course_id == course_id,
        )
        .first()
    )
    if linked is None:
        _fail("resource_generation.knowledge_point_conflict", "知识点不属于当前课程")
    return point


def _display_text(value: Any, *, limit: int = 120) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        parts = [_display_text(item, limit=limit) for item in list(value)[:3]]
        text = "、".join(part for part in parts if part)
    elif isinstance(value, dict):
        parts = [_display_text(item, limit=limit) for item in list(value.values())[:3]]
        text = "、".join(part for part in parts if part)
    else:
        text = " ".join(str(value).split())
    return text[:limit]


def _profile_value(snapshot: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = snapshot.get(key)
        if value is not None and value != "" and value != () and value != []:
            return value
    return None


def _profile_adaptation_summary(snapshot: DBProfileSnapshot) -> str:
    body = dict(snapshot.snapshot or {})
    preference = _display_text(_profile_value(
        body, "preference", "preferences", "learning_preference", "learning_preferences",
    ))
    weak_points = _display_text(_profile_value(body, "weak_points", "current_difficulties", "difficulties"))
    level = _display_text(_profile_value(body, "current_level", "foundation", "level"))
    parts = []
    if preference:
        parts.append(f"偏好{preference}")
    if weak_points:
        parts.append(f"重点巩固{weak_points}")
    if level:
        parts.append(f"当前基础为{level}")
    return "；".join(parts)[:240] or "已冻结当前学习画像，资源会采用分步讲解、示例和练习进行适配。"


def _mastery_summary(snapshot: DBProfileSnapshot, point: DBKnowledgePoint | None) -> str:
    body = dict(snapshot.snapshot or {})
    if point is None:
        overall = next((body[key] for key in ("course_mastery", "overall_mastery", "mastery_summary")
                        if body.get(key) not in (None, "", [], {})), None)
        if overall not in (None, "", [], {}):
            return f"课程级掌握摘要：{_display_text(overall, limit=220)}。"
        return "当前未绑定具体知识点，资源将依据课程范围和学习画像安排从基础到应用的难度。"
    adaptation = build_profile_adaptation(body, knowledge_point={"id": point.id, "title": point.title, "code": point.code})
    if adaptation["point_mastery"] is not None:
        return (f"当前知识点掌握度约为 {round(adaptation['point_mastery'] * 100)}%，"
                f"{adaptation['mastery_focus']}。")
    if adaptation["learning_requirements"]["diagnostic_followup"]:
        return adaptation["mastery_focus"] + "。"
    weak_points = body.get("weak_points") or []
    if isinstance(weak_points, list) and point.title in {str(item) for item in weak_points}:
        return "当前知识点被画像标记为待巩固，资源会加强分步解释与练习。"
    return "当前没有足够的知识点掌握证据，资源将以课程来源和诊断画像为主。"


def _contains_relevant_value(value: Any, *, point_id: str, point_title: str) -> bool:
    if isinstance(value, dict):
        return any(_contains_relevant_value(item, point_id=point_id, point_title=point_title) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_relevant_value(item, point_id=point_id, point_title=point_title) for item in value)
    text = str(value or "").strip()
    return bool(text and (text == point_id or (point_title and point_title in text)))


def _recent_learning_context(
    db: Any, *, actor: DBUser, course_id: str, point: DBKnowledgePoint | None,
) -> tuple[list[str], str]:
    from app.learning_aggregation import _event_observations
    rows = (
        db.query(DBLearningEvent)
        .filter_by(owner_public_id=actor.public_id, course_id=course_id,
                   evidence_status="accepted", mastery_eligible=True)
        .order_by(DBLearningEvent.occurred_at.desc(), DBLearningEvent.id.desc())
        .limit(50)
        .all()
    )
    if point is None:
        relevant = [
            row for row in rows
            if row.evidence_status == "accepted" and row.mastery_eligible
        ][:6]
    else:
        relevant = [
            row for row in rows
            if row.evidence_status == "accepted"
            and row.mastery_eligible
            and (
                row.object_id == point.id
                or _contains_relevant_value(row.context_ref or {}, point_id=point.id, point_title=point.title)
                or _contains_relevant_value(row.payload or {}, point_id=point.id, point_title=point.title)
                or any(point_id == point.id for point_id, _, _ in _event_observations(db, row))
            )
        ][:6]
    if not relevant:
        return [], "近期没有与当前课程范围直接相关的有效学习记录。" if point is None else "近期没有与此知识点直接相关的学习记录。"
    if point is None:
        return [row.id for row in relevant], f"近期有 {len(relevant)} 条与当前课程范围相关的有效学习记录。"
    return (
        [row.id for row in relevant],
        f"近期有 {len(relevant)} 条与此知识点相关的有效学习记录。",
    )


def _generation_context_snapshot(
    db: Any,
    *,
    actor: DBUser,
    course: DBCourse,
    point: DBKnowledgePoint | None,
    profile: DBProfileSnapshot,
    learning_goal: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    body = complete_learning_snapshot(db, profile)
    if point is not None:
        body = with_current_learning_evidence(db, body, actor=actor, course_id=course.id,
                                             knowledge_point_id=point.id)
    fallback_goal = _display_text(_profile_value(body, "goal", "learning_goal", "learning_goals"), limit=320)
    point_title = point.title if point is not None else "当前课程内容"
    clean_goal = " ".join(str(learning_goal or fallback_goal or f"理解并应用{point_title}").split())
    recent_event_ids, recent_summary = _recent_learning_context(
        db, actor=actor, course_id=course.id, point=point,
    )
    source_ids = {
        source_ref_id
        for item in items
        for source_ref_id in item.get("source_ref_ids", [])
    }
    from app.profile_onboarding import profile_influence_summary
    profile_row = db.get(DBStudentProfile, actor.username)
    adaptation = build_profile_adaptation(
        body,
        profile=None if profile_has_signal(body) else profile_row,
        knowledge_point=(
            {"id": point.id, "title": point.title, "code": point.code}
            if point is not None else None
        ),
    ) if profile_has_signal(profile, profile_row) else {}
    mastery_summary = _mastery_summary(profile, point)
    if adaptation.get("point_mastery") is not None:
        mastery_summary = (
            f"当前知识点掌握度约为 {round(float(adaptation['point_mastery']) * 100)}%，"
            f"{adaptation.get('mastery_focus') or '按掌握度安排下一步练习'}。"
        )
    from app.next_core_memory import active_memory_projection
    return {
        "long_term_memory": active_memory_projection(db, owner_public_id=actor.public_id),
        "course_title": course.title,
        "knowledge_point_title": point_title,
        "learning_goal": clean_goal,
        "profile_adaptation": adaptation.get("summary") or "当前没有可用画像，资源按课程目标组织。",
        "profile_snapshot_id": profile.id,
        "profile_version": profile.profile_version,
        "current_learning_evidence": body.get("current_learning_evidence", {}),
        "profile_influence": profile_influence_summary(profile),
        "mastery_summary": mastery_summary,
        "profile_adaptation_plan": profile_prompt_context(adaptation),
        "profile_context": profile_prompt_context(adaptation),
        "recent_event_ids": recent_event_ids,
        "recent_learning_summary": recent_summary,
        "source_count": len(source_ids),
    }


def _public_generation_context(manifest: dict[str, Any]) -> dict[str, Any]:
    context = teaching_context(manifest.get("context") or {}, manifest.get("active_requirements"))
    if not context:
        return {
            "course_title": "当前课程",
            "knowledge_point_title": "当前知识点",
            "learning_goal": "按既定学习目标完成本次资源学习",
            "profile_adaptation": "此任务创建于上下文摘要升级前，仍保留原画像快照。",
            "profile_adaptation_plan": {},
            "profile_context": {},
            "mastery_summary": "此任务未保存可展示的掌握摘要。",
            "recent_learning_summary": "此任务未保存可展示的近期学习摘要。",
            "source_count": len({
                ref_id
                for item in manifest.get("items") or []
                for ref_id in item.get("source_ref_ids") or []
            }),
        }
    return {
        key: context.get(key)
        for key in (
            "course_title", "knowledge_point_title", "learning_goal", "profile_adaptation",
            "mastery_summary", "recent_learning_summary", "source_count",
            "profile_adaptation_plan", "profile_context", "long_term_memory",
            "teaching_scope",
            "path_learning_context",
            "conversation_source",
        )
    }


def _source_snapshots(
    db: Any, *, course_id: str, source_ref_ids: list[str], require_available: bool
) -> list[dict[str, Any]]:
    unique_ids = list(dict.fromkeys(str(value).strip() for value in source_ref_ids if str(value).strip()))
    if not unique_ids:
        _fail("resource_generation.sources_required", "每类资源至少需要一条来源引用")
    if len(unique_ids) != len(source_ref_ids):
        _fail("resource_generation.sources_duplicate", "来源引用不能重复")
    snapshots: list[dict[str, Any]] = []
    for source_ref_id in unique_ids:
        projection = project_source_ref(
            db,
            source_ref_id,
            expected_course_id=course_id,
        )
        if projection["reason_code"] in {"source_ref_missing", "source_document_missing", "course_missing"}:
            _fail("resource_generation.source_unknown", "来源引用不存在")
        if projection["reason_code"] == "course_conflict":
            _fail("resource_generation.source_conflict", "来源引用不属于当前课程")
        if require_available and not projection["available"]:
            _fail("resource_generation.source_unavailable", "来源已撤回或暂不可用")
        if projection["available"]:
            ref = db.get(DBSourceRef, source_ref_id)
            teaching_text = source_ref_teaching_text(db, ref, max_chars=None)
            if teaching_text:
                projection["quote"] = teaching_text
        snapshots.append(projection)
    return snapshots


def _generation_task_evidence(db, *, actor, course_id, context, sources_by_type, user_instruction):
    """Freeze task passages alongside the complete, version-checked sources.

    Short selected material stays complete. Long chapters are searched across
    their whole selected range, once per teaching point, instead of taking the
    first characters. This is task retrieval, not a claim of whole-book coverage.
    """
    from app.canonical_retrieval import retrieve_canonical_sources
    from app.task_evidence import estimated_tokens

    scope = context.get("teaching_scope") or {}
    topics = [point.get("title", "") for point in scope.get("knowledge_points") or []]
    topics = list(dict.fromkeys(topic for topic in topics if topic)) or [context.get("knowledge_point_title") or ""]
    goal = scope.get("goal") or context.get("learning_goal") or ""
    cache, result = {}, {}
    for kind, sources in sources_by_type.items():
        ids = tuple(source["source_ref_id"] for source in sources)
        if ids in cache:
            result[kind] = cache[ids]
            continue
        long_ids = [source["source_ref_id"] for source in sources
                    if estimated_tokens(str(source.get("quote") or "")) > 6000
                    and source.get("location_kind") != "selection"]
        if not long_ids:
            continue
        passages, searches, seen = [], [], set()
        for topic in topics:
            query = "\n".join(value for value in [topic, goal, user_instruction] if value)
            found = retrieve_canonical_sources(
                db, course_id=course_id, query=query, actor=actor,
                source_ref_ids=long_ids, top_k=8, assemble_for_task=True,
            )
            searches.append({"topic": topic, "query": query,
                             "low_confidence": bool(found.get("low_confidence")),
                             "retrieval": found.get("retrieval") or {}, "reason": found.get("reason", "")})
            for item in found.get("items") or []:
                evidence = item["evidence"]
                metadata = evidence.metadata
                ref_id = item["source_ref"]["source_ref_id"]
                key = (ref_id, metadata.get("char_start"), metadata.get("char_end"))
                if ref_id not in long_ids or key in seen:
                    continue
                seen.add(key)
                passages.append({"source_ref_id": ref_id, "quote": evidence.content,
                                 "char_start": metadata.get("char_start"), "char_end": metadata.get("char_end"),
                                 "topic": topic, "relevant": item.get("relevant", True),
                                 "ranking": item.get("ranking") or {}})
        cache[ids] = {"mode": "task_passages", "source_ref_ids": long_ids,
                      "passages": passages, "searches": searches}
        result[kind] = cache[ids]
    return result


def _resource_prompt_sources(manifest, source_snapshots, resource_type=None):
    """Use the same frozen evidence for planning, generation and review."""
    by_type = (manifest.get("input_snapshot") or {}).get("task_evidence") or {}
    selected = ([by_type[resource_type]] if resource_type in by_type else
                list(by_type.values()) if resource_type is None else [])
    scoped_ids = {key for entry in selected for key in entry.get("source_ref_ids", [])}
    result = []
    for source in source_snapshots:
        ref_id = source.get("source_ref_id")
        basic = {key: source.get(key) for key in
                 ("source_ref_id", "title", "location_label", "char_start", "char_end", "document_version", "content_hash")}
        if ref_id not in scoped_ids:
            result.append({**basic, "quote": str(source.get("quote") or ""), "scope": "selected_source"})
            continue
        passages, seen = [], set()
        for entry in selected:
            for passage in entry.get("passages", []):
                key = (passage.get("char_start"), passage.get("char_end"))
                if passage["source_ref_id"] == ref_id and key not in seen:
                    seen.add(key)
                    passages.append(passage)
        result.append({**basic, "scope": "task_passages", "passages": passages,
                       "coverage_note": "仅为当前学习任务检索的原文片段，不代表整份资料；缺少依据的内容不得说成教材结论。"})
    return result


def _step_input(step: DBTaskStep) -> dict[str, Any]:
    try:
        value = json.loads(step.input_summary or "{}")
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def _task_steps(db: Any, task_id: str) -> tuple[list[DBTaskStep], dict[int, DBTaskStep]]:
    rows = (
        db.query(DBTaskStep)
        .filter_by(task_id=task_id)
        .order_by(DBTaskStep.sequence, DBTaskStep.attempt)
        .all()
    )
    latest: dict[int, DBTaskStep] = {}
    for row in rows:
        latest[row.sequence] = row
    return rows, latest


def _generation_manifest(db: Any, task_id: str) -> dict[str, Any]:
    event = (
        db.query(DBTaskEvent)
        .filter(DBTaskEvent.task_id == task_id, DBTaskEvent.event_type.in_({
            "resource_generation.requested", "resource_generation.revision.requested",
            "resource_generation.dependencies.prepared"}))
        .order_by(DBTaskEvent.sequence.desc())
        .first()
    )
    payload = dict(event.payload or {}) if event else {}
    manifest = dict(payload.get("manifest") or {})
    if manifest and not manifest.get("active_requirements") and "teaching_revision_history" not in manifest:
        # Old tasks stored each clarification only in its own immutable event.
        # Recover the ordered instructions without rewriting those records.
        revisions = db.query(DBTaskEvent).filter(
            DBTaskEvent.task_id == task_id,
            DBTaskEvent.event_type == "resource_generation.revision.requested",
            DBTaskEvent.sequence <= event.sequence,
        ).order_by(DBTaskEvent.sequence).all()
        manifest["teaching_revision_history"] = [
            {"feedback": row.payload.get("feedback", ""),
             "resource_types": ((row.payload.get("manifest") or {}).get("teaching_revision") or {}).get(
                 "resource_types", row.payload.get("requested_types", []))}
            for row in revisions
        ]
    plan_event = db.query(DBTaskEvent).filter_by(task_id=task_id,
        event_type="resource_generation.plan.completed").order_by(DBTaskEvent.sequence.desc()).first()
    if plan_event and event and plan_event.sequence > event.sequence and (plan_event.payload or {}).get("active_requirements"):
        manifest["active_requirements"] = plan_event.payload["active_requirements"]
    amendment = db.query(DBTaskEvent).filter_by(task_id=task_id,
        event_type="resource_generation.review.amended").filter(
            DBTaskEvent.sequence > max(event.sequence if event else 0, plan_event.sequence if plan_event else 0)
        ).order_by(DBTaskEvent.sequence.desc()).first()
    if amendment:
        manifest.update({key: amendment.payload[key] for key in ("active_requirements", "review_decisions")})
    return manifest


def _generation_plan(db: Any, task_id: str) -> dict[str, Any]:
    """Read the current plan; an explicit teaching revision requires a new one."""
    revision = db.query(DBTaskEvent).filter_by(task_id=task_id,
        event_type="resource_generation.revision.requested").order_by(DBTaskEvent.sequence.desc()).first()
    event = (
        db.query(DBTaskEvent)
        .filter_by(task_id=task_id, event_type="resource_generation.plan.completed")
        .filter(DBTaskEvent.sequence > (revision.sequence if revision else 0))
        .order_by(DBTaskEvent.sequence.desc())
        .first()
    )
    plan = dict(event.payload or {}) if event else {}
    if not event and revision and revision.payload.get("preserve_plan"):
        event = db.query(DBTaskEvent).filter_by(task_id=task_id,
            event_type="resource_generation.plan.completed").order_by(DBTaskEvent.sequence.desc()).first()
        plan = dict(event.payload or {}) if event else {}
    if not event and revision:
        amendment = db.query(DBTaskEvent).filter_by(task_id=task_id,
            event_type="resource_generation.review.amended").filter(
                DBTaskEvent.sequence > revision.sequence).order_by(DBTaskEvent.sequence.desc()).first()
        _, latest = _task_steps(db, task_id)
        explicit_requirements = (amendment.payload.get('requested_active_requirements') if amendment
                                 else revision.payload.get('active_requirements'))
        if (explicit_requirements is not None and latest
                and all(step.status == 'succeeded' for step in latest.values())):
            # Authored corrections are complete and the current requirements
            # are explicit. Reuse the teaching plan and check the new content.
            event = db.query(DBTaskEvent).filter_by(task_id=task_id,
                event_type='resource_generation.plan.completed').order_by(DBTaskEvent.sequence.desc()).first()
            plan = dict(event.payload or {}) if event else {}
            if plan:
                plan['active_requirements'] = explicit_requirements
    if event:
        amendment = db.query(DBTaskEvent).filter_by(task_id=task_id,
            event_type="resource_generation.review.amended").filter(
                DBTaskEvent.sequence > max(event.sequence, revision.sequence if revision else 0)).order_by(DBTaskEvent.sequence.desc()).first()
        if amendment:
            plan["active_requirements"] = amendment.payload["active_requirements"]
    return plan


def _public_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Expose only manifest fields required by the public resource timeline."""
    public = {
        key: manifest.get(key)
        for key in (
            "conversation_id", "message_id", "resource_intent", "user_instruction",
            "context_snapshot_id", "planner_run_id", "review_run_id",
            "selected_resource_types", "course_id", "knowledge_point_id", "path_id", "task_id",
        )
        if manifest.get(key) not in (None, "", [])
    }
    exam_gate = manifest.get("exam_gate") or {}
    if not public.get("path_id") and exam_gate.get("path_id"):
        public["path_id"] = exam_gate["path_id"]
    if not public.get("task_id") and exam_gate.get("selected_task_id"):
        public["task_id"] = exam_gate["selected_task_id"]
    return public


def _manifest_resource_types(manifest: dict[str, Any]) -> tuple[str, ...]:
    items = list(manifest.get("items") or [])
    resource_types = tuple(str(item.get("type") or "") for item in items)
    if (
        resource_types
        and len(resource_types) == len(set(resource_types))
        and all(resource_type in GENERATION_RESOURCE_TYPES for resource_type in resource_types)
    ):
        return resource_types
    return GENERATION_RESOURCE_TYPES


_PUBLIC_RESOURCE_EVENT_TYPES = {
    "stage.started", "stage.progress", "stage.completed", "stage.failed",
    "resource.item.started", "resource.item.progress", "resource.item.completed", "resource.item.failed",
    "review_gate.started", "review_gate.passed", "review_gate.failed",
    "publish.completed", "run.completed", "run.failed",
}


def _public_generation_events(db: Any, task: DBGenerationTask, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Project task events into the safe, single public resource timeline."""
    rows = (
        db.query(DBTaskEvent)
        .filter_by(task_id=task.id)
        .order_by(DBTaskEvent.sequence)
        .all()
    )
    projected: list[dict[str, Any]] = []
    for row in rows:
        payload = dict(row.payload or {})
        event_type = str(row.event_type or "")
        if event_type == "resource_generation.item.running":
            event_type = "resource.item.started"
        elif event_type == "resource_generation.item.succeeded":
            event_type = "resource.item.completed"
        elif event_type == "resource_generation.item.failed":
            event_type = "resource.item.failed"
        elif event_type.startswith("resource_generation.plan."):
            event_type = "stage.started" if event_type.endswith("started") else "stage.completed" if event_type.endswith("completed") else "stage.failed"
        if event_type not in _PUBLIC_RESOURCE_EVENT_TYPES:
            continue
        resource_type = str(payload.get("resource_type") or payload.get("type") or "")
        status = str(payload.get("status") or "")
        if not status:
            status = {
                "stage.started": "running", "stage.progress": "running", "stage.completed": "completed",
                "stage.failed": "failed", "resource.item.started": "running", "resource.item.progress": "running",
                "resource.item.completed": "completed", "resource.item.failed": "failed",
                "review_gate.started": "running", "review_gate.passed": "completed", "review_gate.failed": "failed",
                "publish.completed": "completed", "run.completed": "completed", "run.failed": "failed",
            }.get(event_type, "queued")
        input_refs = [str(value) for value in payload.get("input_refs") or [] if str(value).strip()]
        output_refs = [str(value) for value in payload.get("output_refs") or [] if str(value).strip()]
        projected.append({
            "event_id": row.id,
            "sequence": row.sequence,
            "event_type": event_type,
            "run_id": str(payload.get("run_id") or task.trace_id),
            "stage_id": str(payload.get("stage_id") or ("resource:" + resource_type if resource_type else "resource_generation")),
            "resource_item_id": str(payload.get("resource_item_id") or ""),
            "resource_type": resource_type,
            "status": status,
            "owner": str(payload.get("owner") or ("Resource Generator" if resource_type else "Supervisor")),
            "summary": " ".join(resource_failure_feedback(payload.get("summary") or payload.get("message") or "").split())[:320],
            "input_refs": input_refs[:20],
            "output_refs": output_refs[:20],
            "progress": payload.get("progress"),
            "retryable": bool(payload.get("retryable", event_type in {"resource.item.failed", "review_gate.failed", "run.failed"})),
        })
    return projected


def _review_gate_status(db: Any, task_id: str) -> str:
    rows = (
        db.query(DBTaskEvent)
        .filter(DBTaskEvent.task_id == task_id, DBTaskEvent.event_type.in_({
            "review_gate.passed", "review_gate.failed", "review_gate.started",
            "resource_generation.item.retry_queued", "resource_generation.recovered",
            "resource_generation.revision.requested",
            "resource_generation.review.amended",
        }))
        .order_by(DBTaskEvent.sequence.desc())
        .all()
    )
    if not rows:
        return "pending"
    return {"review_gate.passed": "passed", "review_gate.failed": "failed",
            "review_gate.started": "running"}.get(rows[0].event_type, "pending")


def _requires_live_gates(db: Any, task_id: str) -> bool:
    return db.query(DBTaskEvent).filter_by(
        task_id=task_id, event_type="resource_generation.demo_execution.started"
    ).first() is None


def _publish_gate_done(db: Any, task_id: str) -> bool:
    revision = db.query(DBTaskEvent).filter(DBTaskEvent.task_id == task_id,
        DBTaskEvent.event_type.in_({"resource_generation.revision.requested", "resource_generation.review.amended"})
        ).order_by(DBTaskEvent.sequence.desc()).first()
    return db.query(DBTaskEvent).filter_by(task_id=task_id, event_type="publish.completed").filter(
        DBTaskEvent.sequence > (revision.sequence if revision else 0)).first() is not None


def _public_generation_state(db: Any, task: DBGenerationTask, latest: dict[int, DBTaskStep]) -> str:
    if task.status == "cancelled":
        return "cancelled"
    states = [row.status for row in latest.values()]
    succeeded = states.count("succeeded")
    if states and succeeded == len(states) and _generation_stopped_with_failure(db, task.id):
        return 'failed'
    review_status = _review_gate_status(db, task.id)
    requires_live_gates = _requires_live_gates(db, task.id)
    if requires_live_gates and review_status == "failed" and not any(state in {"queued", "retry_queued", "requested", "running"} for state in states):
        return "partial_success" if succeeded and "failed" in states else "failed"
    if requires_live_gates and states and succeeded == len(states) and review_status != "passed":
        return "running"
    if states and succeeded == len(states):
        return "succeeded"
    if succeeded:
        return "partial_success"
    if "running" in states:
        return "running"
    if any(state in {"queued", "retry_queued"} for state in states):
        return "queued"
    if states and all(state == "requested" for state in states):
        return "requested"
    if "failed" in states:
        return "failed"
    return task.status


def _generation_stopped_with_failure(db: Any, task_id: str) -> bool:
    event = db.query(DBTaskEvent).filter(DBTaskEvent.task_id == task_id,
        DBTaskEvent.event_type.in_({'run.failed', 'run.completed', 'stage.started',
            'resource_generation.revision.requested', 'resource_generation.review.amended',
            'resource_generation.recovered'}))\
        .order_by(DBTaskEvent.sequence.desc()).first()
    return bool(event and event.event_type == 'run.failed')


def _sync_generation_task(db: Any, task: DBGenerationTask) -> None:
    _, latest = _task_steps(db, task.id)
    states = [row.status for row in latest.values()]
    succeeded = states.count("succeeded")
    task.progress = succeeded / len(states) if states else 0.0
    if task.status == "cancelled":
        return
    review_status = _review_gate_status(db, task.id)
    requires_live_gates = _requires_live_gates(db, task.id)
    if states and succeeded == len(states) and _generation_stopped_with_failure(db, task.id):
        task.status = 'failed'
        task.failure_code = 'resource_generation.check_incomplete'
        task.failure_reason = '内容已保留，继续完成尚未通过的核对。'
        task.completed_at = _utcnow()
    elif requires_live_gates and review_status == "failed" and not any(state in {"queued", "retry_queued", "requested", "running"} for state in states):
        task.status = "failed"
        task.failure_code = "resource_generation.review_failed"
        task.failure_reason = (
            "最后核对暂时未完成，已生成内容保留，请重新核对。"
            if succeeded == len(states) else "部分内容需要调整，请重试需要修改的资源。"
        )
        task.completed_at = _utcnow()
    elif states and succeeded == len(states) and (not requires_live_gates or (review_status == "passed" and _publish_gate_done(db, task.id))):
        task.status = "completed"
        task.completed_at = task.completed_at or _utcnow()
        task.failure_code = ""
        task.failure_reason = ""
    elif (states and succeeded == len(states)) or "running" in states:
        task.status = "running"
        task.started_at = task.started_at or _utcnow()
        task.completed_at = None
        task.failure_code = ""
        task.failure_reason = ""
    elif any(state in {"requested", "queued", "retry_queued"} for state in states):
        task.status = "queued"
        task.completed_at = None
        task.failure_code = ""
        task.failure_reason = ""
    elif "failed" in states:
        task.status = "failed"
        failed = next(row for row in latest.values() if row.status == "failed")
        task.failure_code = failed.error_code
        task.failure_reason = failed.error_message
        task.completed_at = _utcnow()
    db.flush()


def _resource_from_step(db: Any, step: DBTaskStep) -> dict[str, Any] | None:
    if not step.output_artifact_version_id:
        return None
    version = db.get(DBArtifactVersion, step.output_artifact_version_id)
    artifact = db.get(DBArtifact, version.artifact_id) if version else None
    if version is None or artifact is None:
        return None
    metadata = dict(version.metadata_json or {})
    current_sources = _source_snapshots(
        db,
        course_id=artifact.course_id,
        source_ref_ids=list(metadata.get("source_ref_ids") or []),
        require_available=False,
    )
    sources_available = all(item["available"] for item in current_sources)
    resource_type = str(metadata.get("resource_type") or artifact.artifact_type)
    from app.m5_resources import resource_generation_blocker
    generation_blocker = resource_generation_blocker(db, artifact, version.id)
    return {
        "schema_version": "f2.resource.v1",
        "resource_id": artifact.id,
        "type": resource_type,
        "course_id": artifact.course_id,
        "knowledge_point_id": metadata.get("knowledge_point_id"),
        "source_refs": current_sources,
        "profile_snapshot_id": metadata.get("profile_snapshot_id"),
        "version": {
            "id": version.id,
            "number": version.version_number,
            "content_hash": version.content_hash,
            "created_at": version.created_at,
        },
        "generation": {
            "mode": metadata.get("generation_mode") or "deterministic_fallback",
            "input_snapshot_hash": metadata.get("input_snapshot_hash"),
            "source_snapshot_hash": metadata.get("source_snapshot_hash"),
            "source_snapshot_hashes": metadata.get("source_snapshot_hashes") or {},
            "profile_snapshot_hash": metadata.get("profile_snapshot_hash"),
            "recent_event_cursor": metadata.get("recent_event_cursor"),
            "semantic_input_fingerprint": metadata.get("semantic_input_fingerprint"),
            "content_semantic_fingerprint": metadata.get("content_semantic_fingerprint"),
            "semantic_context": metadata.get("semantic_context") or {},
        },
        "status": (
            "archived" if artifact.archived_at is not None
            else "generation_pending" if generation_blocker
            else "available" if sources_available
            else "source_unavailable"
        ),
        "generation_state": step.status,
        "content_ref": f"artifact-version:{version.id}",
        "route": GENERATION_ROUTES[resource_type].format(resource_id=artifact.id),
        "title": artifact.title,
    }


def generation_job_payload(db: Any, actor: DBUser, task_id: str) -> dict[str, Any]:
    from app.generation_dispatch import public_automation
    task = _generation_task(db, actor, task_id)
    rows, latest = _task_steps(db, task.id)
    manifest = _generation_manifest(db, task.id)
    resource_types = _manifest_resource_types(manifest)
    items = []
    for resource_type in resource_types:
        sequence = GENERATION_RESOURCE_TYPES.index(resource_type) + 1
        step = latest.get(sequence)
        spec = _step_input(step) if step else {}
        attempts = [row for row in rows if row.sequence == sequence]
        public_state = "queued" if step and step.status == "retry_queued" else (step.status if step else "requested")
        items.append({
            "type": resource_type,
            "title": spec.get("title") or _DEMO_RESOURCE_LABELS.get(resource_type, resource_type),
            "completion_rule": spec.get("completion_rule") or {
                "handout": "阅读讲义，完成自测并核对解析。",
                "mind_map": "展开知识节点，梳理概念之间的关系。",
                "deck": "逐页学习，回顾要点并完成随页练习。",
                "video": "观看推荐视频，对照学习目标整理笔记。",
            }.get(resource_type, "按本资源的要求完成学习活动。"),
            "source_count": len(spec.get("source_ref_ids") or []),
            "state": public_state,
            "attempt": step.attempt if step else 0,
            "idempotency_key": f"{task.id}:{resource_type}",
            "checkpoint": "archived" if step and step.status == "succeeded" else "awaiting_generation",
            "failure": {
                "code": step.error_code,
                "message": resource_failure_feedback(step.error_message),
            } if step and step.status == "failed" else None,
            "input": spec,
            "resource": _resource_from_step(db, step) if step else None,
            "attempt_history": [{
                "attempt": row.attempt,
                "state": row.status,
                "failure_code": row.error_code,
                "failure_message": resource_failure_feedback(row.error_message),
            } for row in attempts],
        })
    succeeded_types = [item["type"] for item in items if item["state"] == "succeeded"]
    failed_types = [item["type"] for item in items if item["state"] == "failed"]
    pending_types = [item["type"] for item in items if item["state"] not in {"succeeded", "failed", "cancelled"}]
    manifest_public = _public_manifest(manifest)
    review_status = _review_gate_status(db, task.id)
    return {
        "schema_version": GENERATION_SCHEMA_VERSION,
        "job_id": task.id,
        "course_id": task.course_id,
        "knowledge_point_id": manifest.get("knowledge_point_id"),
        "profile_snapshot_id": manifest.get("profile_snapshot_id"),
        "scope": manifest.get("scope") or ("single" if len(resource_types) == 1 else "bundle"),
        "context": _public_generation_context(manifest),
        "status": _public_generation_state(db, task, latest),
        "automation": public_automation(task),
        "failure_code": task.failure_code,
        "failure_reason": resource_failure_feedback(task.failure_reason),
        "progress": task.progress,
        "idempotency_key": task.idempotency_key,
        "checkpoint": {
            "succeeded_types": succeeded_types,
            "failed_types": failed_types,
            "pending_types": pending_types,
        },
        "manifest": manifest_public,
        "planner": {
            "run_id": manifest.get("planner_run_id") or "",
            "status": "completed" if _generation_plan(db, task.id) else "pending",
            "summary": str(_generation_plan(db, task.id).get("summary") or "")[:320],
        },
        "review_gate": {
            "run_id": manifest.get("review_run_id") or "",
            "status": review_status,
        },
        "publish_gate": {"status": "completed" if _publish_gate_done(db, task.id) else "pending"},
        "events": _public_generation_events(db, task, manifest),
        "items": items,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "completed_at": task.completed_at,
    }


def create_generation_job(
    db: Any,
    actor: DBUser,
    *,
    course_id: str,
    knowledge_point_id: str | None,
    profile_snapshot_id: str,
    idempotency_key: str,
    items: list[dict[str, Any]],
    scope: str = "bundle",
    path_id: str | None = None,
    task_id: str | None = None,
    learning_goal: str = "",
    conversation_id: str | None = None,
    message_id: str | None = None,
    resource_intent: str | None = None,
    user_instruction: str = "",
    conversation_source: dict[str, Any] | None = None,
    verification_mode: str | None = None,
    context_snapshot_id: str | None = None,
    selected_resource_types: list[str] | None = None,
    teaching_scope: dict[str, Any] | None = None,
    auto_start: bool = False,
) -> dict[str, Any]:
    if verification_mode not in {None, "cove"}:
        _fail("resource_generation.verification_mode_invalid", "不支持的核验方式")
    course = _course(db, actor, course_id)
    point = _knowledge_point(db, course_id, knowledge_point_id)
    profile = _profile_snapshot(db, actor, profile_snapshot_id, course_id=course_id)
    if scope not in {"bundle", "single"}:
        _fail("resource_generation.scope_invalid", "资源生成范围不受支持")
    by_type = {str(item.get("type", "")): item for item in items}
    if scope == "bundle":
        # A bundle is any multi-select resource request.  The complete nine
        # item bundle remains valid, while the Chat resource picker may submit
        # any unique subset of two or more supported resource types.
        if len(items) < 2 or len(items) > len(GENERATION_RESOURCE_TYPES):
            _fail("resource_generation.item_count", "资源包必须包含至少两类且不超过九类资源")
        if len(by_type) != len(items) or set(by_type) - set(GENERATION_RESOURCE_TYPES):
            _fail("resource_generation.item_types", "资源包中的资源类型必须各出现一次且受支持")
        requested_types = tuple(dict.fromkeys(str(item.get("type", "")) for item in items))
    else:
        if len(items) != 1:
            _fail("resource_generation.item_count", "单类资源生成必须只包含一种资源")
        requested_type = str(items[0].get("type", ""))
        if requested_type not in GENERATION_RESOURCE_TYPES:
            _fail("resource_generation.item_types", "单类资源类型不受支持")
        requested_types = (requested_type,)
    selected_types = list(selected_resource_types or requested_types)
    if tuple(dict.fromkeys(str(value) for value in selected_types)) != tuple(requested_types):
        _fail("resource_generation.selected_types_conflict", "选定资源类型必须与资源任务项一致")
    clean_items: list[dict[str, Any]] = []
    source_snapshots_by_type: dict[str, list[dict[str, Any]]] = {}
    shared_source_ref_ids: list[str] = []
    for resource_type in requested_types:
        for value in by_type[resource_type].get("source_ref_ids") or []:
            source_ref_id = str(value).strip()
            if source_ref_id and source_ref_id not in shared_source_ref_ids:
                shared_source_ref_ids.append(source_ref_id)
    shared_source_snapshots = (
        _source_snapshots(
            db,
            course_id=course_id,
            source_ref_ids=shared_source_ref_ids,
            require_available=True,
        )
        if scope == "bundle"
        else None
    )
    for resource_type in requested_types:
        raw = by_type[resource_type]
        title = " ".join(str(raw.get("title", "")).split())[:256]
        if not title:
            _fail("resource_generation.title_required", "每类资源都需要标题")
        if resource_type == "handout":
            title = _normalize_handout_title(title, getattr(point, "title", ""))[:256]
        source_ref_ids = (
            list(shared_source_ref_ids)
            if scope == "bundle"
            else [str(value) for value in raw.get("source_ref_ids") or []]
        )
        source_snapshots_by_type[resource_type] = (
            list(shared_source_snapshots or [])
            if scope == "bundle"
            else _source_snapshots(
                db,
                course_id=course_id,
                source_ref_ids=source_ref_ids,
                require_available=True,
            )
        )
        clean_items.append({
            "type": resource_type,
            "title": title,
            "source_ref_ids": source_ref_ids,
            "completion_rule": " ".join(completion_description(raw.get("completion_rule", "")).split()),
            "depends_on": list(_resource_dependencies(resource_type)),
        })
    existing_task = db.query(DBGenerationTask).filter_by(
        owner_public_id=actor.public_id,
        idempotency_key=idempotency_key,
    ).first()
    if existing_task and existing_task.capability != GENERATION_CAPABILITY:
        _fail("resource_generation.idempotency_conflict", "同一幂等键已用于其他生成任务")
    existing_manifest = _generation_manifest(db, existing_task.id) if existing_task else {}
    gate_snapshot = None
    if path_id or task_id:
        if not path_id or not task_id:
            _fail("resource_generation.path_context_incomplete", "路径与今日任务必须同时提供")
        existing_gate = (
            existing_manifest.get("exam_gate")
            if existing_task
            else None
        )
        if existing_gate:
            if existing_gate.get("path_id") != path_id or existing_gate.get("selected_task_id") != task_id:
                _fail("resource_generation.idempotency_conflict", "同一幂等键已绑定其他路径任务")
            gate_snapshot = dict(existing_gate)
        else:
            try:
                gate_snapshot = freeze_exam_gate_snapshot(
                    db,
                    owner_public_id=actor.public_id,
                    course_id=course_id,
                    path_id=path_id,
                    task_id=task_id,
                    allow_scheduled_preparation=True,
                )
            except ExamGateError as exc:
                _fail(exc.code, str(exc))
    elif existing_manifest.get("exam_gate"):
        _fail("resource_generation.idempotency_conflict", "同一幂等键已绑定路径任务")
    requested_core = {
        "course_id": course_id,
        "knowledge_point_id": knowledge_point_id,
        "profile_snapshot_id": profile_snapshot_id,
        "scope": scope,
        "items": clean_items,
    }
    optional_core = {
        "conversation_id": str(conversation_id or "").strip() or None,
        "message_id": str(message_id or "").strip() or None,
        "resource_intent": str(resource_intent or ("custom_bundle" if scope == "bundle" else "single_resource")).strip(),
        "user_instruction": str(user_instruction or "").strip(),
        "conversation_source": conversation_source,
        "verification_mode": verification_mode,
        "context_snapshot_id": str(context_snapshot_id or "").strip() or None,
        "selected_resource_types": list(requested_types),
    }
    requested_core.update({key: value for key, value in optional_core.items() if value not in (None, "")})
    if teaching_scope is not None:
        requested_core["teaching_scope"] = teaching_scope
    if existing_task:
        existing_core = {key: existing_manifest.get(key) for key in requested_core}
        existing_core["items"] = existing_manifest.get("requested_items", existing_core["items"])
        existing_core["scope"] = existing_manifest.get("scope") or "bundle"
        if existing_core != requested_core:
            _fail("resource_generation.idempotency_conflict", "同一幂等键已用于不同资源包请求")
        existing_goal = str((existing_manifest.get("context") or {}).get("learning_goal") or "")
        if learning_goal.strip() and existing_goal and learning_goal.strip() != existing_goal:
            _fail("resource_generation.idempotency_conflict", "同一幂等键已绑定其他学习目标")
        return {**generation_job_payload(db, actor, existing_task.id), "created": False}
    context_snapshot = _generation_context_snapshot(
        db,
        actor=actor,
        course=course,
        point=point,
        profile=profile,
        learning_goal=learning_goal,
        items=clean_items,
    )
    if conversation_source:
        context_snapshot["conversation_source"] = conversation_source
    if teaching_scope is not None:
        context_snapshot["teaching_scope"] = teaching_scope
        context_snapshot["knowledge_point_title"] = teaching_scope.get("title") or context_snapshot["knowledge_point_title"]
    if gate_snapshot:
        from app.database import DBPathNode
        from app.path_scope import path_node_content
        path_node = db.get(DBPathNode, task_id)
        teaching = path_node_content(db, path_node)
        scoped_ids = list(teaching.get("knowledge_point_ids") or [])
        if scoped_ids:
            if knowledge_point_id not in scoped_ids:
                _fail("resource_generation.path_scope_conflict", "所选知识点不属于当前学习单元，请重新打开任务。")
            scoped_points = {item.id: item.title for item in db.query(DBKnowledgePoint).filter(DBKnowledgePoint.id.in_(scoped_ids))}
            context_snapshot["teaching_scope"] = {
                "unit_key": teaching.get("teaching_unit_key"), "title": path_node.title,
                "goal": teaching.get("teaching_goal") or "",
                "knowledge_points": [{"id": key, "title": scoped_points[key]} for key in scoped_ids if key in scoped_points],
                "chapter_id": path_node.target_object_id,
                "path_version_id": gate_snapshot.get("path_version_id"),
            }
        from app.path_learning_context import preceding_learning_context
        context_snapshot["path_learning_context"] = preceding_learning_context(
            db, owner_public_id=actor.public_id, course_id=course_id, path_id=path_id, task_id=task_id,
        )
    manifest = {
        **requested_core,
        "context": context_snapshot,
        "input_snapshot": _generation_input_snapshot(
            context=context_snapshot,
            profile=profile,
            source_snapshots_by_type=source_snapshots_by_type,
        ),
    }
    task_evidence = _generation_task_evidence(
        db, actor=actor, course_id=course_id, context=context_snapshot, sources_by_type=source_snapshots_by_type,
        user_instruction=optional_core["user_instruction"],
    )
    if task_evidence:
        manifest["input_snapshot"]["task_evidence"] = task_evidence
        manifest["input_snapshot"]["input_snapshot_hash"] = _sha256_json({
            "original_input_hash": manifest["input_snapshot"]["input_snapshot_hash"],
            "task_evidence": task_evidence,
        })
    if gate_snapshot:
        manifest["exam_gate"] = gate_snapshot
    manifest_hash = hashlib.sha256(_canonical(manifest).encode("utf-8")).hexdigest()
    task, created = create_generation_task(
        db,
        owner_public_id=actor.public_id,
        course_id=course_id,
        capability=GENERATION_CAPABILITY,
        idempotency_key=idempotency_key,
        model=("deepseek-v4-flash" if CONFIG.llm_provider.lower().strip() in {"openai", "vllm"} else "deterministic"),
    )
    if not created:
        _fail("resource_generation.idempotency_conflict", "资源生成任务刚刚发生变化，请刷新后重试")
    manifest.update({
        "planner_run_id": f"resource-plan:{task.id}",
        "review_run_id": f"resource-review:{task.id}",
    })
    append_task_event(
        db,
        task_id=task.id,
        event_type="resource_generation.requested",
        payload={"schema_version": GENERATION_SCHEMA_VERSION, "manifest": {**manifest, "manifest_hash": manifest_hash}},
    )
    for item in clean_items:
        sequence = GENERATION_RESOURCE_TYPES.index(item["type"]) + 1
        step = create_task_step(
            db,
            task_id=task.id,
            sequence=sequence,
            agent_role="resource_generator",
            tool_name=item["type"],
            input_summary=_canonical(item),
        )
        step.status = "queued"
    _sync_generation_task(db, task)
    if auto_start:
        from app.generation_dispatch import submit_resource_job
        submit_resource_job(db, actor, task.id)
    return {**generation_job_payload(db, actor, task.id), "created": True}


def prepare_generation_dependencies(db, task):
    """Track every companion so reviewed defects can repair upstream versions."""
    manifest = _generation_manifest(db, task.id)
    if "training_task" not in _manifest_resource_types(manifest):
        return
    _, latest = _task_steps(db, task.id)
    existing = {item["type"]: item for item in _practical_dependencies(db, task, latest)}
    missing = [kind for kind in _resource_dependencies("training_task")
               if GENERATION_RESOURCE_TYPES.index(kind) + 1 not in latest]
    if not missing:
        return
    training = next(item for item in manifest["items"] if item["type"] == "training_task")
    snapshot = dict(manifest["input_snapshot"])
    snapshots = dict(snapshot.get("source_snapshots") or {})
    hashes = dict(snapshot.get("source_snapshot_hashes") or {})
    evidence = dict(snapshot.get("task_evidence") or {})
    items = list(manifest["items"])
    for kind in missing:
        item = {**training, "type": kind, "title": _DEMO_RESOURCE_LABELS[kind],
                "completion_rule": resource_completion_rule(kind), "depends_on": [], "companion": True}
        items.append(item)
        snapshots[kind] = snapshots.get("training_task", [])
        hashes[kind] = hashes.get("training_task")
        if "training_task" in evidence:
            evidence[kind] = evidence["training_task"]
        step = create_task_step(db, task_id=task.id, sequence=GENERATION_RESOURCE_TYPES.index(kind)+1,
            agent_role="resource_generator", tool_name=kind, input_summary=_canonical(item))
        step.status = "queued"
        if kind in existing:
            # Reuse its immutable body, but include it in current task review.
            # A later rejection creates a task-owned revision, preserving the
            # original published resource and its learning history.
            step.status = 'succeeded'
            step.output_artifact_version_id = existing[kind]['version_id']
            step.completed_at = _utcnow()
    snapshot.update(source_snapshots=snapshots, source_snapshot_hashes=hashes, task_evidence=evidence)
    snapshot["input_snapshot_hash"] = _sha256_json(snapshot)
    manifest = {**manifest, "requested_items": manifest.get("requested_items", manifest["items"]),
                "items": items, "input_snapshot": snapshot}
    manifest.pop("manifest_hash", None)
    manifest["manifest_hash"] = _sha256_json(manifest)
    append_task_event(db, task_id=task.id, event_type="resource_generation.dependencies.prepared",
                      payload={"added_types": missing, "reused_versions": {kind:existing[kind]['version_id']
                               for kind in missing if kind in existing}, "manifest": manifest})


_DEMO_RESOURCE_LABELS = {
    "handout": "个性化讲义",
    "mind_map": "思维导图",
    "quiz": "测验题资源",
    "training_task": "实训任务书",
    "code_sandbox": "代码沙盒任务",
    "video": "视频推荐",
    "deck": "PPT与网页课件",
    "interactive_model": "可交互模型",
    "feynman": "费曼复述任务",
}


def resource_completion_rule(resource_type: str, value: Any = "") -> str:
    """Use actual learning actions for the old chat placeholder; preserve authored requirements."""
    text = " ".join(completion_description(value).split())
    legacy_label = {"quiz": "测验题", "code_sandbox": "代码沙盒", "deck": "PPT/网页课件"}.get(
        resource_type, _DEMO_RESOURCE_LABELS.get(resource_type, resource_type))
    if text and text != f"完成{legacy_label}并做一次简短回顾。":
        return text
    return {
        "handout": "完成本页学习检查，独立尝试迁移题后核对。",
        "mind_map": "梳理关键概念及其关系，并用自己的话解释。",
        "quiz": "作答并查看反馈，记录需要再练的知识点。",
        "training_task": "复用配套代码与实验记录，独立完成任务要求的判断与解释，并整理实训报告。",
        "code_sandbox": "运行当前代码，通过本页必需检查后提交完成；按检查点核对输出与适用条件。",
        "video": "观看与目标相关的片段，整理关键概念和仍有疑问的内容。",
        "deck": "按页面学习并完成随页练习，回顾本次目标。",
        "interactive_model": "运行有效参数组合，依据实际结果提交观察与解释。",
        "feynman": "用自己的话解释当前主题，提交后根据反馈补充和修正。",
    }.get(resource_type, "按本资源的要求完成学习活动。")


def _public_source_excerpt(value: Any) -> str:
    """Extract a short teaching excerpt from a source quote.

    Course provenance is still stored beside the resource, but front-facing
    question copy must not expose manifest paths, hashes, parser metadata or
    profile snapshots.
    """
    text = str(value or "")
    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip(">-• ").strip()
        if not line or line.startswith("#"):
            continue
        lowered = line.casefold()
        if any(marker in lowered for marker in (
            "source_path", "source_ref", "来源角色", "课程版本", "manifest",
            "commit", "content_hash", "parser_version", "parse_version", "license",
            "许可", "上游仓库", "固定版本", "文件路径", "profile", "画像",
        )):
            continue
        line = re.sub(r"`[^`]+`", "", line)
        line = re.sub(r"https?://\S+", "", line)
        line = re.sub(r"\b[0-9a-f]{12,64}\b", "", line, flags=re.IGNORECASE)
        line = " ".join(line.split())
        if line:
            lines.append(line)
    excerpt = " ".join(lines)
    excerpt = re.sub(r"\s+", " ", excerpt).strip()
    # Keep the option concise and stop at a natural sentence boundary where
    # possible; the full quote remains available through the source action.
    if len(excerpt) > 150:
        boundary = max(excerpt.rfind("。", 0, 150), excerpt.rfind("；", 0, 150))
        excerpt = excerpt[:boundary + 1 if boundary >= 48 else 150].rstrip()
    return excerpt


def _quiz_scope_issue(questions: list[dict[str, Any]], context: dict[str, Any]) -> str:
    if any(not isinstance(question, dict) for question in questions):
        return "部分题目内容不完整，请重新生成。"
    points = (context.get("teaching_scope") or {}).get("knowledge_points") or []
    allowed = {str(point["id"]): str(point.get("title") or "") for point in points if point.get("id")}
    if not allowed:
        return ""
    covered = set()
    for question in questions:
        point_id = str(question.get("knowledgePointId") or "")
        if not point_id and len(allowed) == 1:
            point_id = next(iter(allowed))
        if point_id not in allowed:
            return "每道题都需要对应本单元实际考查的知识点，不能把所有题都归入第一个知识点。"
        covered.add(point_id)
    missing = set(allowed) - covered
    return "测验还缺少这些单元知识点的学习检查：" + "、".join(allowed[key] for key in sorted(missing)) if missing else ""


def _create_quiz_resource_content(
    db: Any,
    *,
    actor: DBUser,
    task: DBGenerationTask,
    item: dict[str, Any],
    manifest: dict[str, Any],
    source_snapshots: list[dict[str, Any]],
    llm_payload: dict[str, Any] | None = None,
) -> str:
    """Create a public quiz projection and canonical private answer keys together."""
    context = _public_generation_context(manifest)
    knowledge_point_id = str(manifest.get("knowledge_point_id") or "")
    knowledge_point = str(context.get("knowledge_point_title") or knowledge_point_id or "当前知识点")
    scope_points = {
        str(point["id"]): str(point.get("title") or knowledge_point)
        for point in (context.get("teaching_scope") or {}).get("knowledge_points", [])
        if point.get("id")
    }
    source_ref_ids = tuple(str(snapshot["source_ref_id"]) for snapshot in source_snapshots)
    mastery = str(context.get("mastery_summary") or "当前掌握证据仍在积累")
    recent = str(context.get("recent_learning_summary") or "暂无近期有效作答")
    profile_adaptation = str(context.get("profile_adaptation") or "依据当前画像组织题目顺序")
    variant = _profile_content_variant(context)
    live_model_payload = llm_payload is not None
    learning_goal = (
        teacher_text(llm_payload.get("learningGoal")) if live_model_payload
        else str(context.get("learning_goal") or f"验证对{knowledge_point}的理解")
    )
    if not learning_goal:
        _fail("resource_generation.model_output_invalid", "测验尚未给出本组题目的学习目标，请重新生成。")
    semantic_context = {
        "schema_version": "pr-02.quiz-semantic-context.v1",
        "generation_mode": "llm" if live_model_payload else "deterministic_fallback",
        "course_title": str(context.get("course_title") or "当前课程"),
        "knowledge_point_id": knowledge_point_id,
        "knowledge_point_title": knowledge_point,
        "teaching_scope": context.get("teaching_scope") or {},
        "learning_goal": learning_goal,
        "profile_adaptation": profile_adaptation[:600],
        "mastery_summary": mastery[:600],
        "recent_learning_summary": recent[:600],
        "source_ref_ids": list(source_ref_ids),
        "source_titles": [str(snapshot.get("title") or "") for snapshot in source_snapshots],
        "source_locations": [
            str(snapshot.get("location_label") or snapshot.get("location_kind") or "课程章节")
            for snapshot in source_snapshots
        ],
        "profile_variant": variant["band"],
    }
    semantic_fingerprint = _sha256_json(semantic_context)
    semantic_context["semantic_input_fingerprint"] = semantic_fingerprint
    mastery_action = (
        "先用一个最小例子验证，再解释为什么结果成立"
        if any(token in mastery for token in ("未", "薄弱", "陌生", "不足", "needs_work"))
        else "比较一个新情境并说明适用边界"
    )
    profile_action = (
        "用分步提示拆开条件、机制和结果"
        if any(token in profile_adaptation for token in ("基础", "入门", "step", "分步"))
        else "用简短证据说明判断依据并连接到实际任务"
    )
    def variant_difficulty(base: float) -> float:
        return round(max(0.1, min(0.95, base + float(variant["difficulty_delta"]))), 2)

    correct_source_option = f"先明确“{knowledge_point}”的对象、条件和结果，再用一个最小例子验证结论。"
    specs = (
        {
            "prompt": f"{variant['question_prefix']} 围绕“{knowledge_point}”最需要先确认哪一项？",
            "options": (
                correct_source_option,
                f"跳过“{knowledge_point}”的适用条件，只记住术语。",
                "只浏览标题就可以直接提高掌握度。",
                "把与当前章节无关的结论当作本题依据。",
            ),
            "answer": "A",
            "explanation": learner_safe_explanation(
                "",
                prompt=f"围绕“{knowledge_point}”最需要先确认哪一项？",
                options=(
                    correct_source_option,
                    f"跳过“{knowledge_point}”的适用条件，只记住术语。",
                    "只浏览标题就可以直接提高掌握度。",
                    "把与当前章节无关的结论当作本题依据。",
                ),
                answer_key={"choice": "A"}, question_type="single_choice",
                knowledge_point=knowledge_point,
            ),
            "bloom": "remember",
            "difficulty": variant_difficulty(0.28 if "未" in mastery else 0.42),
        },
        {
            "prompt": f"{variant['question_prefix']} 为了在当前学习目标下验证“{knowledge_point}”，下面哪种行动最合适？",
            "options": (
                f"{profile_action}；{variant['example']} 并通过一次提交作答验证理解。",
                "只展开来源详情，不完成任何学习动作。",
                "跳过课程来源，直接照搬一个结论。",
                "只记住术语，不说明条件和机制。",
            ),
            "answer": "A",
            "explanation": learner_safe_explanation(
                "",
                prompt=f"为了验证“{knowledge_point}”，下面哪种行动最合适？",
                options=(
                    f"{profile_action}；{variant['example']}并通过一次提交作答验证理解。",
                    "只展开来源详情，不完成任何学习动作。",
                    "跳过课程来源，直接照搬一个结论。",
                    "只记住术语，不说明条件和机制。",
                ),
                answer_key={"choice": "A"}, question_type="single_choice",
                knowledge_point=knowledge_point,
            ),
            "bloom": "understand",
            "difficulty": variant_difficulty(0.44 if "基础" in profile_adaptation else 0.58),
        },
        {
            "prompt": f"{variant['question_prefix']} 结合掌握摘要和近期学习记录，完成“{knowledge_point}”后下一步最合理的是？",
            "options": (
                f"{mastery_action}；再依据判分与解析决定继续练习或进入下一项任务。",
                "把练习题移入正式测评中心作为第三类测评。",
                "删除原始尝试，只保留最后一次答案。",
                "无论判分结果如何都直接宣称已经完全掌握。",
            ),
            "answer": "A",
            "explanation": learner_safe_explanation(
                "",
                prompt=f"完成“{knowledge_point}”后下一步最合理的是？",
                options=(
                    f"{mastery_action}；再依据判分与解析决定继续练习或进入下一项任务。",
                    "把练习题移入正式测评中心作为第三类测评。",
                    "删除原始尝试，只保留最后一次答案。",
                    "无论判分结果如何都直接宣称已经完全掌握。",
                ),
                answer_key={"choice": "A"}, question_type="single_choice",
                knowledge_point=knowledge_point,
            ),
            "bloom": "apply",
            "difficulty": variant_difficulty(0.62 if recent != "暂无近期有效作答" else 0.52),
        },
    )
    model_questions = list((llm_payload or {}).get("quizQuestions") or [])
    if live_model_payload and (scope_issue := _quiz_scope_issue(model_questions, context)):
        _fail("resource_generation.quiz_scope_incomplete", scope_issue)
    if live_model_payload and not model_questions:
        _fail("resource_generation.model_output_invalid", "本组练习需要完整题目，请重新生成。")
    if model_questions:
        normalized_specs = []
        for index, question in enumerate(model_questions):
            if not isinstance(question, dict):
                continue
            options = _normalize_quiz_options(question.get("options"), position=index + 1)
            answer = str(question.get("answer") or "A").strip().upper()
            if answer not in {"A", "B", "C", "D"}:
                continue
            question_point = (
                str(question.get("knowledgePointId") or next(iter(scope_points)))
                if scope_points else knowledge_point_id
            )
            normalized_specs.append({
                "knowledge_point_id": question_point,
                "hints": [teacher_text(hint) for hint in question.get("hints") or []
                          if isinstance(hint, str) and hint.strip()],
                "prompt": str(question.get("prompt") or "").strip(),
                "options": options,
                "answer": answer,
                "explanation": learner_safe_explanation(
                    question.get("explanation"),
                    prompt=str(question.get("prompt") or ""),
                    options=options,
                    answer_key={"choice": answer}, question_type="single_choice",
                    knowledge_point=scope_points.get(question_point, knowledge_point),
                ),
                "bloom": _normalize_quiz_bloom(
                    question.get("bloom"),
                    default=("remember", "understand", "apply")[min(index, 2)],
                    position=index + 1,
                ),
                "difficulty": _normalize_quiz_difficulty(
                    question.get("difficulty"),
                    default=min(0.85, 0.35 + index * 0.1),
                    position=index + 1,
                ),
            })
        if len(normalized_specs) == len(model_questions) and all(item["prompt"] for item in normalized_specs):
            specs = tuple(normalized_specs)
        elif live_model_payload:
            _fail("resource_generation.model_output_invalid", "测验题模型输出的题目结构不完整。")
    try:
        sessions = quiz_study_sessions((llm_payload or {}).get("studySessions", []), len(specs))
    except ValueError:
        _fail("resource_generation.model_output_invalid", "分段题号需按顺序覆盖全部题目，并给出每段预计分钟数。")
    question_refs = []
    for position, spec in enumerate(specs, start=1):
        question, version = create_question_version(
            db,
            owner_public_id=actor.public_id,
            course_id=task.course_id,
            question_type="single_choice",
            origin="derived",
            version=QuestionVersionInput(
                prompt=spec["prompt"],
                options=spec["options"],
                answer_key={"choice": spec["answer"]},
                scoring_rule={"version": "f6-quiz-objective-v1", "correct_threshold": 1.0},
                explanation=spec["explanation"],
                misconception_tags=("source_misread", "mechanism_gap", "evidence_boundary"),
                primary_knowledge_point_id=spec.get("knowledge_point_id") or knowledge_point_id or None,
                bloom_level=spec["bloom"],
                expert_difficulty=spec["difficulty"],
                source_ref_ids=source_ref_ids,
            ),
        )
        question.status = "approved"
        question_refs.append({
            "questionVersionId": version.id,
            "position": position,
            "required": True,
            "hints": spec.get("hints") or [],
        })
    return _canonical({
        "schemaVersion": "f6.quiz-resource.v1",
        "title": str(item.get("title") or _DEMO_RESOURCE_LABELS["quiz"]),
        "summary": str((llm_payload or {}).get("summary") or f"围绕“{knowledge_point}”完成本组练习，提交后查看结果、解析和下一步建议。"),
        "courseTitle": str(context.get("course_title") or "当前课程"),
        "knowledgePoint": {"id": knowledge_point_id, "title": knowledge_point},
        "adaptation": {
            "learningGoal": learning_goal,
            "profileSummary": profile_adaptation,
            "masterySummary": mastery,
            "recentLearningSummary": recent,
        },
        "semanticContext": semantic_context,
        "sourceRefIds": list(source_ref_ids),
        "questions": question_refs,
        "requiredQuestionCount": len(question_refs),
        "studySessions": [session.model_dump() for session in sessions],
    })


_PROFILE_TOPIC_GROUPS = (
    ("优化", "正则", "训练", "损失", "学习率", "过拟合", "梯度", "早停"),
    ("rag", "检索", "召回", "向量", "关键词", "重排", "切分", "来源", "版本", "证据"),
    ("agent", "智能体", "mcp", "skill", "工具调用"),
    ("transformer", "注意力", "qkv", "位置编码"),
    ("卷积", "cnn", "图像", "池化"),
    ("循环", "rnn", "序列", "lstm", "gru"),
)


def _profile_adaptation_plan(context: dict[str, Any]) -> dict[str, Any]:
    raw = context.get("profile_adaptation_plan") or context.get("profile_context") or {}
    plan = dict(raw) if isinstance(raw, dict) else {}
    knowledge_point = str(context.get("knowledge_point_title") or "当前知识点").strip()

    def topic_groups(value: Any) -> set[int]:
        text = str(value or "").lower()
        return {
            index for index, group in enumerate(_PROFILE_TOPIC_GROUPS)
            if any(marker in text for marker in group)
        }

    knowledge_groups = topic_groups(knowledge_point)
    for key, fallback in (
        ("content_focus", f"当前知识点“{knowledge_point}”的核心机制、适用条件与验证方法"),
        ("example_context", f"围绕“{knowledge_point}”的课程实践场景"),
    ):
        value_groups = topic_groups(plan.get(key))
        if knowledge_groups and (not value_groups or knowledge_groups.isdisjoint(value_groups)):
            plan[key] = fallback
    return plan


def _profile_content_variant(context: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic content variant for the learner profile.

    Live model prompts receive the full adaptation plan.  This same small
    variant is applied by local structured generators so offline/demo runs
    change the actual lesson or question content, not only metadata.
    """
    plan = _profile_adaptation_plan(context)
    band = str(plan.get("difficulty_band") or "").strip().lower()
    label = str(plan.get("difficulty_label") or "").strip()
    source_text = " ".join(
        str(value or "") for value in (
            context.get("profile_adaptation"), context.get("mastery_summary"), label,
        )
    )
    if band not in {"foundation", "scaffolded", "transfer"}:
        if any(token in source_text for token in ("入门", "巩固", "基础薄弱", "零基础", "未掌握")):
            band = "foundation"
        elif any(token in source_text for token in ("进阶", "迁移", "熟练", "高级")):
            band = "transfer"
        else:
            band = "scaffolded"

    focus = str(plan.get("content_focus") or "当前知识点的核心机制").strip()
    example = str(plan.get("example_context") or "课程实践场景").strip()
    if band == "foundation":
        return {
            "band": band,
            "label": label or "入门巩固",
            "lead": f"先从{focus}的术语、输入和输出开始，用{example}中的最小案例逐步建立理解。",
            "example": f"使用{example}的单一变量案例，按‘条件—步骤—结果’逐项核对。",
            "question_prefix": "先识别题目给出的关键条件，再选择能说明机制的答案：",
            "difficulty_delta": -0.12,
        }
    if band == "transfer":
        return {
            "band": band,
            "label": label or "进阶迁移",
            "lead": f"先把{focus}放进{example}的变化情境，比较不同做法在边界条件下的表现，再用结果检验判断。",
            "example": f"使用{example}的变化情境，比较至少两种方案并解释适用边界。",
            "question_prefix": "在新的任务情境中比较方案、边界和证据，选择最合理的解释：",
            "difficulty_delta": 0.12,
        }
    return {
        "band": "scaffolded",
        "label": label or "基础应用",
        "lead": f"围绕{focus}先建立机制，再用{example}的基线案例完成一次应用检查。",
        "example": f"使用{example}的基线案例，先判断机制，再说明参数或条件变化。",
        "question_prefix": "结合条件和机制判断，再选择能够解释结果的答案：",
        "difficulty_delta": 0.0,
    }


def _deterministic_code_contract(
    *, knowledge_point: str, practical_focus: str, learning_goal: str = "",
) -> tuple[str, str, list[dict[str, Any]]]:
    """Choose a runnable code exercise whose algorithm matches the knowledge point.

    The old deterministic factory used one classifier starter for every
    non-RAG topic.  That made a successful run look healthy while teaching the
    wrong concept.  Keep the existing required-check protocol, but select a
    small, theory-grounded program for the current semantic family.
    """
    text = f"{knowledge_point} {practical_focus} {learning_goal}".casefold()
    common_exit = {"id": "exit-zero", "label": "程序正常结束", "kind": "exit_code_zero"}
    plot_check = {"id": "plot-created", "label": "生成结果图表", "kind": "plot_count_at_least", "minimum": 1}
    if any(term in text for term in ("二分", "binary search", "查找与边界")):
        code = """import matplotlib.pyplot as plt

values = [1, 3, 5, 7, 9, 11, 13, 15, 17]
raw = input().strip()
target = int(raw) if raw else 13
left, right = 0, len(values) - 1
history = []
while left <= right:
    mid = (left + right) // 2
    history.append((left, right, mid))
    if values[mid] == target:
        break
    if values[mid] < target:
        left = mid + 1
    else:
        right = mid - 1
index = mid if history and values[mid] == target else -1
print(f"target={target}")
print(f"index={index}")
print(f"iterations={len(history)}")
print("time_complexity=O(log n)")

plt.figure(figsize=(7, 3.6))
plt.plot(range(1, len(history) + 1), [item[2] for item in history], marker="o")
plt.xlabel("iteration")
plt.ylabel("mid index")
plt.title("Binary search interval trace")
plt.tight_layout()
plt.show()
"""
        checks = [common_exit,
                  {"id": "index-output", "label": "输出查找位置", "kind": "stdout_contains", "expectedText": "index="},
                  {"id": "complexity-output", "label": "输出时间复杂度", "kind": "stdout_contains", "expectedText": "time_complexity=O(log n)"},
                  plot_check]
        return code, "13", checks
    if practical_focus == "分类决策、指标权衡与误差诊断" or any(
        term in str(learning_goal).casefold() for term in ("分类", "阈值", "混淆矩阵", "误报")
    ):
        code = """import matplotlib.pyplot as plt

scores = [0.12, 0.28, 0.44, 0.51, 0.63, 0.76, 0.88]
labels = [0, 0, 0, 1, 1, 1, 1]
raw = input().strip()
threshold = float(raw) if raw else 0.50
predictions = [1 if score >= threshold else 0 for score in scores]
correct = sum(prediction == label for prediction, label in zip(predictions, labels))
true_negative = sum(prediction == 0 and label == 0 for prediction, label in zip(predictions, labels))
false_positive = sum(prediction == 1 and label == 0 for prediction, label in zip(predictions, labels))
false_negative = sum(prediction == 0 and label == 1 for prediction, label in zip(predictions, labels))
true_positive = sum(prediction == 1 and label == 1 for prediction, label in zip(predictions, labels))
print(f"threshold={threshold:.2f}")
print(f"validation_accuracy={correct / len(labels):.2f}")
print(f"confusion_matrix=tn:{true_negative},fp:{false_positive},fn:{false_negative},tp:{true_positive}")

plt.figure(figsize=(7, 3.6))
plt.scatter(range(len(scores)), scores, c=labels)
plt.axhline(threshold, color="#842b24", linestyle="--", label=f"threshold={threshold:.2f}")
plt.xlabel("sample")
plt.ylabel("score")
plt.title("Classification threshold check")
plt.legend()
plt.tight_layout()
plt.show()
"""
        checks = [common_exit,
                  {"id": "accuracy-output", "label": "输出验证准确率", "kind": "stdout_contains", "expectedText": "validation_accuracy="},
                  {"id": "matrix-output", "label": "输出混淆矩阵", "kind": "stdout_contains", "expectedText": "confusion_matrix="},
                  plot_check]
        return code, "0.50", checks
    if any(term in text for term in ("优化算法", "正则化", "训练稳定性", "梯度下降", "regularization")):
        code = """import math
import matplotlib.pyplot as plt

raw = input().strip() or "0.08,0.03,80"
learning_rate, l2_strength, raw_epochs = [float(value) for value in raw.split(",")]
epochs = int(raw_epochs)
if not 0 < learning_rate <= 0.5:
    raise ValueError("learning_rate 必须在 (0, 0.5] 内")
if not 0 <= l2_strength <= 1:
    raise ValueError("l2_strength 必须在 [0, 1] 内")
if not 10 <= epochs <= 500:
    raise ValueError("epochs 必须在 [10, 500] 内")

xs = [-2.0, -1.0, 0.0, 1.0, 2.0]
ys = [-5.1, -1.9, 1.0, 4.2, 6.8]

def train(regularization):
    weight, bias = 0.0, 0.0
    losses = []
    for _ in range(epochs):
        predictions = [weight * x + bias for x in xs]
        errors = [prediction - target for prediction, target in zip(predictions, ys)]
        grad_weight = 2 * sum(error * x for error, x in zip(errors, xs)) / len(xs)
        grad_weight += 2 * regularization * weight
        grad_bias = 2 * sum(errors) / len(xs)
        weight -= learning_rate * grad_weight
        bias -= learning_rate * grad_bias
        mse = sum((weight * x + bias - target) ** 2 for x, target in zip(xs, ys)) / len(xs)
        loss = mse + regularization * weight * weight
        if not math.isfinite(loss):
            raise ValueError("训练发散：请降低学习率")
        losses.append(loss)
    return weight, bias, losses

plain_weight, _, plain_losses = train(0.0)
regularized_weight, regularized_bias, regularized_losses = train(l2_strength)
print(f"learning_rate={learning_rate:.3f}")
print(f"l2_strength={l2_strength:.3f}")
print(f"initial_loss={regularized_losses[0]:.4f}")
print(f"final_loss={regularized_losses[-1]:.4f}")
print(f"weight_without_l2={plain_weight:.4f}")
print(f"weight_with_l2={regularized_weight:.4f}")
print(f"weight_shrinkage={abs(plain_weight) - abs(regularized_weight):.4f}")
print(f"bias={regularized_bias:.4f}")
print(f"converged={regularized_losses[-1] < regularized_losses[0]}")

plt.figure(figsize=(7, 3.6))
plt.plot(range(1, epochs + 1), plain_losses, label="without L2")
plt.plot(range(1, epochs + 1), regularized_losses, label="with L2")
plt.xlabel("epoch")
plt.ylabel("objective")
plt.title("Gradient descent and L2 regularization")
plt.legend()
plt.tight_layout()
plt.show()
"""
        checks = [common_exit,
                  {"id": "loss-output", "label": "输出训练损失", "kind": "stdout_contains", "expectedText": "final_loss="},
                  {"id": "regularization-output", "label": "输出正则化权重收缩", "kind": "stdout_contains", "expectedText": "weight_shrinkage="},
                  {"id": "convergence-output", "label": "确认优化过程收敛", "kind": "stdout_contains", "expectedText": "converged=True"},
                  plot_check]
        return code, "0.08,0.03,80", checks
    if any(term in text for term in ("向量、矩阵", "向量矩阵", "线性代数", "概率基础", "矩阵运算")):
        code = """import matplotlib.pyplot as plt

vector = [float(value) for value in input().split(",")]
weights = [1.0, 0.5, 0.25][:len(vector)]
dot_product = sum(value * weight for value, weight in zip(vector, weights))
l2_norm = sum(value * value for value in vector) ** 0.5
probabilities = [abs(value) / max(1e-9, sum(abs(item) for item in vector)) for value in vector]
print(f"dot_product={dot_product:.3f}")
print(f"l2_norm={l2_norm:.3f}")
print(f"probability_sum={sum(probabilities):.3f}")

plt.figure(figsize=(7, 3.6))
plt.bar(range(len(vector)), probabilities)
plt.xlabel("dimension")
plt.ylabel("normalized probability")
plt.title("Vector normalization check")
plt.tight_layout()
plt.show()
"""
        checks = [common_exit,
                  {"id": "dot-output", "label": "输出向量点积", "kind": "stdout_contains", "expectedText": "dot_product="},
                  {"id": "probability-output", "label": "输出概率归一化", "kind": "stdout_contains", "expectedText": "probability_sum=1.000"},
                  plot_check]
        return code, "1,2,3", checks
    if practical_focus == "混合检索与证据质量评估":
        code = """import matplotlib.pyplot as plt

keyword_weight, vector_weight, top_k, rerank_threshold = [float(value) for value in input().split(",")]
candidate_scores = [0.42, 0.55, 0.68, 0.74, 0.86]
scores = [keyword_weight * score + vector_weight * (1 - score / 2) for score in candidate_scores]
accepted = [score for score in scores if score >= rerank_threshold][:int(top_k)]
recall_at_k = len(accepted) / len(candidate_scores)
ranking_score = sum(sorted(accepted, reverse=True)) / max(1, len(accepted))
average_latency_ms = 8.0 + top_k * 1.5
print(f"recall_at_k={recall_at_k:.2f}")
print(f"ranking_score={ranking_score:.2f}")
print(f"average_latency_ms={average_latency_ms:.1f}")

plt.figure(figsize=(7, 3.6))
plt.plot(range(1, len(scores) + 1), scores, marker="o")
plt.axhline(rerank_threshold, color="#60727C", linestyle="--", label=f"threshold={rerank_threshold:.2f}")
plt.xlabel("candidate")
plt.ylabel("hybrid score")
plt.title("Retrieval rerank check")
plt.legend()
plt.tight_layout()
plt.show()
"""
        checks = [common_exit,
                  {"id": "recall-output", "label": "输出召回率", "kind": "stdout_contains", "expectedText": "recall_at_k="},
                  {"id": "ranking-output", "label": "输出排序质量", "kind": "stdout_contains", "expectedText": "ranking_score="},
                  plot_check]
        return code, "0.50,0.50,3,0.50", checks
    if any(term in text for term in ("回归", "损失函数", "拟合", "regression")):
        code = """import matplotlib.pyplot as plt

xs = [1.0, 2.0, 3.0, 4.0, 5.0]
ys = [2.0, 4.1, 5.9, 8.2, 10.1]
learning_rate = float(input().strip() or 0.05)
w, b = 0.0, 0.0
for _ in range(80):
    predictions = [w * x + b for x in xs]
    dw = sum((pred - y) * x for pred, x, y in zip(predictions, xs, ys)) / len(xs)
    db = sum(pred - y for pred, y in zip(predictions, ys)) / len(xs)
    w, b = w - learning_rate * dw, b - learning_rate * db
loss = sum((w * x + b - y) ** 2 for x, y in zip(xs, ys)) / len(xs)
print(f"slope={w:.3f}")
print(f"intercept={b:.3f}")
print(f"mse_loss={loss:.3f}")

plt.figure(figsize=(7, 3.6))
plt.scatter(xs, ys, label="observed")
plt.plot(xs, [w * x + b for x in xs], label="fitted")
plt.xlabel("x")
plt.ylabel("y")
plt.title("Linear regression fit")
plt.legend()
plt.tight_layout()
plt.show()
"""
        checks = [common_exit,
                  {"id": "slope-output", "label": "输出回归斜率", "kind": "stdout_contains", "expectedText": "slope="},
                  {"id": "loss-output", "label": "输出均方误差", "kind": "stdout_contains", "expectedText": "mse_loss="},
                  plot_check]
        return code, "0.05", checks
    # A safe, topic-neutral fallback is still a small input/assumption checker;
    # it never claims to demonstrate a different algorithm family.
    code = """problem = input().strip()
if not problem:
    raise ValueError("input 不能为空")
print(f"knowledge_point={problem}")
print("assumptions_checked=1")
"""
    return code, knowledge_point, [common_exit, {"id": "topic-output", "label": "输出知识点检查", "kind": "stdout_contains", "expectedText": "knowledge_point="}]


def _deterministic_demo_content(
    *,
    resource_type: str,
    item: dict[str, Any],
    manifest: dict[str, Any],
    source_snapshots: list[dict[str, Any]],
    linked_resource_ids: list[str] | None = None,
) -> str:
    """Create honest local demo artifacts without pretending to call a model."""
    title = str(item.get("title") or _DEMO_RESOURCE_LABELS[resource_type])
    context = _public_generation_context(manifest)
    knowledge_point = str(context.get("knowledge_point_title") or manifest.get("knowledge_point_id") or "当前知识点")
    source = source_snapshots[0] if source_snapshots else {}
    source_title = str(source.get("title") or "预置课程来源")
    source_location = str(source.get("location_label") or source.get("location_kind") or "课程章节")
    semantic = _semantic_context(
        manifest=manifest,
        knowledge_point=knowledge_point,
        source_snapshots=source_snapshots,
    )
    variant = _profile_content_variant(context)
    source_anchor = str(semantic["source_semantic_anchor"])
    practical_focus = str(semantic["practical_focus"])
    label = _DEMO_RESOURCE_LABELS[resource_type]
    if resource_type == "handout":
        source_ids = [str(item["source_ref_id"]) for item in source_snapshots]
        footnotes = [
            {
                "id": f"source-{index}",
                "sourceRefId": str(snapshot["source_ref_id"]),
                "label": f"[{index}]",
                "title": str(snapshot.get("title") or "预置课程来源"),
                "location": str(snapshot.get("location_label") or snapshot.get("location_kind") or "课程章节"),
            }
            for index, snapshot in enumerate(source_snapshots, start=1)
        ]
        # The legacy factory always started with a small conceptual scaffold
        # before introducing the main mechanism.  Keep that teaching richness
        # in the current schema, while leaving generic additions unreferenced
        # instead of pretending they came from a course document.
        extra_concepts = [{
            "id": "prerequisite-foundation",
            "title": "前置概念与最小案例",
            "explanation": f"{variant['lead']} 先列出对象、输入、输出和一个可观察结果，再进入课程中的核心机制。",
            "sourceRefIds": [],
        }, {
            "id": "mechanism-breakdown",
            "title": "核心机制拆解",
            "explanation": f"把“{knowledge_point}”拆成条件、关键步骤和结果三段：先确认{practical_focus}的输入，再观察机制如何改变结果，最后检查结论是否仍满足边界条件。",
            "sourceRefIds": source_ids,
        }]
        extra_examples = [{
            "id": "worked-example",
            "title": "Worked example：从条件到结果",
            "body": f"先写出问题条件，再按步骤执行并记录中间结果：{variant['example']} 最后用一个独立检查（题目、代码输出或图表）确认结论，而不是只凭直觉判断。",
            "sourceRefIds": source_ids,
        }, {
            "id": "retrieval-practice",
            "title": "闭卷检索与迁移",
            "body": f"合上资料，用三句话回答：{knowledge_point}解决什么问题？它依赖哪些条件？在{practical_focus}中怎样验证？回答后再打开讲义核对遗漏。",
            "sourceRefIds": [],
        }]
        if variant["band"] == "transfer":
            extra_examples.append({
                "id": "transfer-challenge",
                "title": "迁移挑战与边界比较",
                "body": variant["example"],
                "sourceRefIds": [],
            })
        return _canonical({
            "schemaVersion": "f5.handout.v1",
            "title": title,
            "summary": f"{variant['lead']} 围绕“{knowledge_point}”建立从概念、机制到应用检查的阅读路径，重点覆盖{practical_focus}。",
            "learningGoal": _handout_learning_goal(context.get("learning_goal"), knowledge_point),
            "estimatedMinutes": {"foundation": 30, "scaffolded": 24, "transfer": 20}[variant["band"]],
            "outline": [
                *([{"id": "prerequisite-foundation", "title": "前置概念与最小案例"}] if variant["band"] == "foundation" else []),
                {"id": "concept-core", "title": "关键概念"},
                {"id": "mechanism-breakdown", "title": "核心机制拆解"},
                {"id": "figure-mechanism", "title": "机制图解"},
                *[{"id": item["id"], "title": item["title"]} for item in extra_examples],
                {"id": "counterexample-boundary", "title": "边界与反例"},
                {"id": "misconception-contrast", "title": "常见误区辨析"},
                {"id": "code-reading", "title": "代码阅读"},
                *[{"id": f"quiz-check-{index}", "title": f"学习检查 {index}"} for index in range(1, 4)],
                *[{"id": item["id"], "title": item["label"]} for item in footnotes],
            ],
            "concepts": [*extra_concepts, {
                "id": "concept-core",
                "title": knowledge_point,
                "explanation": f"{variant['lead']} 先辨认“{knowledge_point}”解决的问题、输入输出和成立条件，再把机制连接到后续示例与实训。",
                "sourceRefIds": source_ids,
            }],
            "figures": [{
                "id": "figure-mechanism",
                "title": "从输入到结果的机制链",
                "kind": "diagram",
                "content": f"课程问题 -> {knowledge_point}的关键机制 -> {practical_focus} -> 可观察结果 -> 学习检查；{variant['example']}",
                "caption": "这张关系图帮助你快速看清概念之间的联系，正式公式请结合讲义中的推导阅读。",
                "sourceRefIds": source_ids,
            }],
            "examples": [{
                "id": "example-application",
                "title": "如何分析一个应用案例",
                "body": f"{variant['example']} 面对与“{knowledge_point}”相关的案例，依次说明问题条件、机制选择、预期输出和验证方法。先围绕{practical_focus}提出可验证假设。",
                "sourceRefIds": source_ids,
            }, *extra_examples],
            "counterExamples": [{
                "id": "counterexample-boundary",
                "title": "只记结论而忽略条件",
                "body": f"如果只复述结论、不说明输入条件和检查方法，就不能判断该方法是否适用于新的情境。{variant['lead']}",
                "sourceRefIds": [],
            }, {
                "id": "misconception-contrast",
                "title": "常见误区：相关不等于适用",
                "body": f"看到结果变好并不等于机制在所有场景都成立；要把正例和边界反例放在一起，说明{practical_focus}的适用条件、失败信号和排错动作。",
                "sourceRefIds": [],
            }],
            "codeBlocks": [{
                "id": "code-reading",
                "title": "机制检查：可运行最小示例",
                "language": "python",
                "code": "def inspect_mechanism(problem, assumptions):\n    if not problem:\n        raise ValueError('problem 不能为空')\n    missing = [key for key, value in assumptions.items() if value in (None, '')]\n    return {'problem': problem, 'missing_assumptions': missing, 'ready': not missing}\n\nif __name__ == '__main__':\n    result = inspect_mechanism('当前知识点', {'input': '已给出', 'boundary': '待确认'})\n    print(result)\n",
                "explanation": "这是可直接运行的最小检查器：先验证问题与前提是否完整，再把缺失条件显式打印出来；更复杂的实验进入代码沙盒。",
            }],
            "miniQuiz": [{
                "id": "quiz-check-1",
                "question": f"学习“{knowledge_point}”时，哪种做法最能形成可验证理解？",
                "options": ["只记住术语", "同时说明条件、机制和验证方法", "只浏览标题", "跳过来源直接下结论"],
                "correctIndex": 1,
                "explanation": "可验证理解需要把适用条件、核心机制和检查方法连接起来。",
                "required": True,
            }, {
                "id": "quiz-check-2",
                "question": f"当{practical_focus}的结果与预期不一致时，第一步更合理的是？",
                "options": ["直接换一个模型", "检查输入、条件和中间结果", "删除失败记录", "把异常结果当作新结论"],
                "correctIndex": 1,
                "explanation": "先定位输入和边界条件，才能区分实现错误、数据问题和机制不适用。",
                "required": True,
            }, {
                "id": "quiz-check-3",
                "question": f"闭卷复述“{knowledge_point}”后，哪项行动最能检验迁移能力？",
                "options": ["再次抄写定义", "在新情境中说明取舍并给出验证方法", "只看答案不动手", "忽略反例"],
                "correctIndex": 1,
                "explanation": "迁移练习要把机制放进新的限制条件中，说明取舍、边界和可以观察到的结果。",
                "required": True,
            }],
            "footnotes": footnotes,
            "profileAdaptation": {
                "summary": str(context.get("profile_adaptation") or "当前讲义按已有画像摘要组织阅读层级。"),
                "difficulty": str(context.get("mastery_summary") or "依据当前掌握摘要自适应"),
                "scaffolding": [
                    "先读摘要和关键概念，再进入例子与反例。",
                    "代码片段只用于理解结构，运行任务进入代码沙盒。",
                    f"{str(context.get('recent_learning_summary') or '完成小测后再决定是否进入下一项资源。')} 当前实践重点：{practical_focus}。",
                ],
            },
        })
    if resource_type == "mind_map":
        source_ids = [str(item["source_ref_id"]) for item in source_snapshots]
        handout_ids = list(dict.fromkeys(linked_resource_ids or []))
        return _canonical({
            "schemaVersion": "f5.mindmap.v1",
            "title": title,
            "summary": f"{variant['label']}：围绕“{knowledge_point}”组织核心机制、适用条件、{practical_focus}和后续资源。",
            "learningGoal": str(context.get("learning_goal") or f"解释{knowledge_point}的关键关系并找到可验证的下一步。"),
            "rootNodeId": "root",
            "nodes": [
                {
                    "nodeId": "root",
                    "parentNodeId": None,
                    "label": knowledge_point,
                    "summary": f"当前导图的中心知识点是“{knowledge_point}”，实践重点为{practical_focus}。{variant['lead']}",
                    "relation": "主题",
                    "depth": 0,
                    "sourceRefs": source_ids,
                    "masteryBand": "developing",
                    "linkedResourceIds": handout_ids,
                },
                {
                    "nodeId": "concept",
                    "parentNodeId": "root",
                    "label": "核心概念",
                    "summary": "先建立术语、条件和作用对象之间的准确联系。",
                    "relation": "组成",
                    "depth": 1,
                    "sourceRefs": source_ids,
                    "masteryBand": "developing",
                    "linkedResourceIds": handout_ids,
                },
                {
                    "nodeId": "mechanism",
                    "parentNodeId": "root",
                    "label": "关键机制",
                    "summary": f"说明输入如何经过关键步骤形成可观察结果，并连接到{practical_focus}。",
                    "relation": "组成",
                    "depth": 1,
                    "sourceRefs": source_ids,
                    "masteryBand": "needs_work",
                    "linkedResourceIds": handout_ids,
                },
                {
                    "nodeId": "conditions",
                    "parentNodeId": "mechanism",
                    "label": "适用条件",
                    "summary": "识别机制成立所依赖的前提、参数和边界。",
                    "relation": "前置",
                    "depth": 2,
                    "sourceRefs": source_ids,
                    "masteryBand": "unknown",
                    "linkedResourceIds": handout_ids,
                },
                {
                    "nodeId": "validation",
                    "parentNodeId": "mechanism",
                    "label": "验证方法",
                    "summary": "通过题目、代码或实验检查是否真正理解机制。",
                    "relation": "验证",
                    "depth": 2,
                    "sourceRefs": source_ids,
                    "masteryBand": "unknown",
                    "linkedResourceIds": [],
                },
                {
                    "nodeId": "application",
                    "parentNodeId": "root",
                    "label": "应用与反例",
                    "summary": "用一个正确应用和一个边界反例区分表面记忆与可迁移理解。",
                    "relation": "应用",
                    "depth": 1,
                    "sourceRefs": source_ids,
                    "masteryBand": "unknown",
                    "linkedResourceIds": handout_ids,
                },
                *([{
                    "nodeId": "foundation-start",
                    "parentNodeId": "root",
                    "label": "前置概念与最小案例",
                    "summary": variant["lead"],
                    "relation": "前置",
                    "depth": 1,
                    "sourceRefs": source_ids,
                    "masteryBand": "needs_work",
                    "linkedResourceIds": handout_ids,
                }] if variant["band"] == "foundation" else []),
                *([{
                    "nodeId": "transfer-challenge",
                    "parentNodeId": "application",
                    "label": "迁移挑战与边界比较",
                    "summary": variant["example"],
                    "relation": "迁移",
                    "depth": 2,
                    "sourceRefs": source_ids,
                    "masteryBand": "secure",
                    "linkedResourceIds": handout_ids,
                }] if variant["band"] == "transfer" else []),
            ],
        })
    elif resource_type == "code_sandbox":
        source_ids = [str(snapshot["source_ref_id"]) for snapshot in source_snapshots]
        completion_rule = str(item.get("completion_rule") or "保存代码，完成一次通过全部必需检查的真实运行，再明确提交完成。")
        starter_code, standard_input, required_checks = _deterministic_code_contract(
            knowledge_point=knowledge_point,
            practical_focus=practical_focus,
            learning_goal=str(context.get("learning_goal") or ""),
        )
        retrieval_contract = any(check.get("id") == "recall-output" for check in required_checks)
        if variant["band"] == "foundation":
            if retrieval_contract:
                standard_input = "0.65,0.35,2,0.45"
            elif any(term in knowledge_point.casefold() for term in ("二分", "binary search")):
                standard_input = "13"
        elif variant["band"] == "transfer":
            if retrieval_contract:
                standard_input = "0.35,0.65,5,0.60"
            elif any(term in knowledge_point.casefold() for term in ("二分", "binary search")):
                standard_input = "15"
        return _canonical({
            "schemaVersion": "f6.code-sandbox.v1",
            "title": title,
            "summary": f"围绕“{knowledge_point}”完成一次可复现的{practical_focus}实验、结果检查和排错。",
            "courseTitle": str(context.get("course_title") or "当前课程"),
            "knowledgePoint": {"id": str(manifest.get("knowledge_point_id") or ""), "title": knowledge_point},
            "adaptation": {
                "learningGoal": str(context.get("learning_goal") or f"通过真实代码运行验证{knowledge_point}的机制与边界"),
                "profileSummary": str(context.get("profile_adaptation") or "按当前画像提供起始代码、分步检查点和可复现输入。"),
                "masterySummary": str(context.get("mastery_summary") or "当前掌握证据仍在积累。"),
                "recentLearningSummary": str(context.get("recent_learning_summary") or "暂无近期有效运行记录。"),
            },
            "checkpoints": [
                {
                    "id": "inspect-input",
                    "title": "检查输入与实验边界",
                    "instruction": f"阅读样例与标准输入，确认{practical_focus}所需的输入、参数和实验边界。参考内容：{source_anchor}",
                    "completionHint": "代码输出必须保留实际使用的 threshold。",
                },
                {
                    "id": "run-baseline",
                    "title": "运行基线并核对指标",
                    "instruction": f"运行 main.py，核对与{practical_focus}对应的真实输出、指标和错误信息。",
                    "completionHint": "运行结果必须来自当前代码和标准输入。",
                },
                {
                    "id": "inspect-plot",
                    "title": "观察结果图表",
                    "instruction": f"查看实验图表，解释{practical_focus}中的参数变化如何影响结果。",
                    "completionHint": "至少生成一张可读取的图表。",
                },
            ],
            "files": [{"path": "main.py", "language": "python", "content": starter_code}],
            "entryFile": "main.py",
            "standardInput": standard_input,
            "requiredChecks": required_checks,
            "completionRule": completion_rule,
            "runtime": {
                "language": "python",
                "mode": "trusted_local",
                "timeoutSeconds": 10,
                "boundary": "本地研究模式在受限子进程和临时目录中运行，不具备 Docker 容器隔离，仅用于团队预置课程与比赛演示。",
            },
            "sourceRefIds": source_ids,
            "linkedTrainingTaskId": None,
            "linkedModelId": None,
            "semanticContext": semantic,
        })
    elif resource_type == "quiz":
        body = f"1. 请用自己的话解释“{knowledge_point}”的核心机制，并补充一个具体例子。\n\n提交后会立即显示结果和详细解析。"
    elif resource_type == "training_task":
        linked = list(dict.fromkeys(linked_resource_ids or []))
        sandbox_id = linked[0] if linked else None
        model_id = linked[1] if len(linked) > 1 else None
        source_ids = [str(item["source_ref_id"]) for item in source_snapshots]
        profile_adaptation = str(context.get("profile_adaptation") or "按当前画像安排先理解、再运行、后诊断的任务节奏。")
        mastery_summary = str(context.get("mastery_summary") or "依据当前掌握摘要设置为基础到应用难度")
        recent_learning = str(context.get("recent_learning_summary") or "暂无近期证据，先完成可复现基线。")
        return _canonical({
            "schemaVersion": "f5.training-task.v1",
            "title": title,
            "objective": f"围绕“{knowledge_point}”完成一次从数据检查、方案选择到结果评估与排错的工程任务。",
            "difficulty": mastery_summary[:64],
            "estimatedMinutes": 55,
            "prerequisites": [
                f"能够解释“{knowledge_point}”的核心机制与适用条件。",
                "已经阅读对应讲义，并能找到需要复习的章节。",
                profile_adaptation,
            ],
            "environment": [
                "Python 3.11 本地研究环境",
                "EduMatrix 代码沙盒（实际编辑与运行在该资源中完成）",
                "EduMatrix 可交互模型（参数观察在该资源中完成）",
            ],
            "data": [
                f"课程预置数据：{source_title} · {source_location}",
                "任务使用的输入、划分规则和随机种子必须在提交物中记录。",
            ],
            "steps": [
                {
                    "id": "step-data",
                    "title": "检查数据与任务边界",
                    "instruction": "确认输入字段、目标、缺失值和训练/验证划分，记录不可直接用于训练的信息。",
                    "expectedResult": "得到一份字段、数据质量问题和划分策略清单。",
                    "errorGuidance": "若数据不可读或字段不完整，停止训练并在提交物中记录缺失项，不得假造结果。",
                    "sourceRefIds": source_ids,
                },
                {
                    "id": "step-model",
                    "title": "选择模型与评价指标",
                    "instruction": f"根据“{knowledge_point}”的机制、数据规模和任务目标选择一个基线方案，并说明指标为何能反映任务质量。",
                    "expectedResult": "形成模型、关键参数、评价指标及选择理由。",
                    "errorGuidance": "若指标与任务目标不一致，回到讲义重新检查目标变量和评价口径。",
                    "sourceRefIds": source_ids,
                },
                {
                    "id": "step-run",
                    "title": "训练并保存真实结果",
                    "instruction": "进入关联代码沙盒实现基线、运行代码并保存真实输出或错误；不要在任务书中伪造运行结果。",
                    "expectedResult": "获得可重现的运行记录、指标和必要图表，或一份可定位的错误记录。",
                    "errorGuidance": "先根据错误类型检查数据、形状、参数和依赖，再修改代码重跑；保留失败记录用于说明排错过程。",
                    "sourceRefIds": source_ids,
                },
                {
                    "id": "step-evaluate",
                    "title": "评估、诊断与改进",
                    "instruction": f"比较训练与验证表现，识别过拟合、欠拟合或数据泄漏风险，并结合近期学习证据提出一个可验证的改进：{recent_learning}",
                    "expectedResult": "得到结论、风险说明和下一次实验建议。",
                    "errorGuidance": "若无法解释指标变化，进入关联可交互模型观察参数变化，再回到沙盒验证。",
                    "sourceRefIds": source_ids,
                },
            ],
            "checkpoints": [
                {
                    "id": "checkpoint-plan",
                    "afterStepId": "step-model",
                    "title": "方案可执行",
                    "verification": "逐项核对数据字段、模型输入输出、指标和课程目标是否一致。",
                    "passCondition": "没有未解释的数据字段，模型和指标均能追溯到当前任务目标。",
                },
                {
                    "id": "checkpoint-run",
                    "afterStepId": "step-run",
                    "title": "结果可重现",
                    "verification": "使用相同输入和随机种子重跑一次，并核对输出或错误是否一致。",
                    "passCondition": "运行记录包含代码、输入、环境、输出或错误，且结果能够再次复现。",
                },
                {
                    "id": "checkpoint-evaluate",
                    "afterStepId": "step-evaluate",
                    "title": "结论有结果支持",
                    "verification": "检查每个结论是否引用真实指标、图表、运行输出或明确错误。",
                    "passCondition": "不存在仅凭主观判断给出的性能结论。",
                },
            ],
            "deliverables": [
                {
                    "id": "deliverable-code",
                    "title": "可运行代码与环境说明",
                    "description": "提交能够复现本次实验的代码、依赖和输入说明。",
                    "format": "代码沙盒运行记录",
                },
                {
                    "id": "deliverable-report",
                    "title": "实验结果与排错记录",
                    "description": "提交指标、图表、失败记录、修正过程和最终结论。",
                    "format": "Markdown 实验报告",
                },
            ],
            "rubric": [
                {"id": "rubric-data", "criterion": "数据理解与处理", "evidence": "字段、质量问题、划分和防泄漏说明完整。", "points": 25},
                {"id": "rubric-model", "criterion": "模型与指标选择", "evidence": "选择理由与任务目标和课程机制一致。", "points": 25},
                {"id": "rubric-run", "criterion": "真实运行与可重现性", "evidence": "保留代码、输入、环境、输出或错误及重跑结果。", "points": 30},
                {"id": "rubric-analysis", "criterion": "评估、排错与改进", "evidence": "结论引用真实证据，并提出可验证改进。", "points": 20},
            ],
            "sourceRefs": source_ids,
            "linkedSandboxId": sandbox_id,
            "linkedModelId": model_id,
            "semanticContext": semantic,
        })
    elif resource_type == "interactive_model":
        source_ids = [str(item["source_ref_id"]) for item in source_snapshots]
        template = _interactive_template_for_knowledge_point(knowledge_point, context.get("teaching_scope"))
        if template is None:
            _fail(
                "resource_generation.interactive_not_applicable",
                f"当前知识点“{knowledge_point}”没有适配的交互实验模板，建议改用讲义、思维导图或代码沙盒。",
            )
        template_id = template.template_id
        parameters = [item.model_dump(mode="json") for item in template.parameters]
        series = [
            {
                "key": metric.key,
                "label": metric.label,
                "unit": metric.unit,
                "higherIsBetter": metric.higher_is_better,
            }
            for metric in template.metrics
        ]
        constraints_by_template = {
            "rag-hybrid-tuning": [{
                "id": "retrieval-weight-sum",
                "title": "检索权重守恒",
                "description": "关键词权重与向量权重之和必须等于 1。",
            }],
            "classifier-threshold-calibration": [{
                "id": "classification-boundary",
                "title": "覆盖率与风险同时观察",
                "description": "提高阈值或扩大拒判区间可能减少误报，但也会降低覆盖率。",
            }],
            "linear-algebra-probability": [{
                "id": "probability-normalization",
                "title": "维度一致与概率归一化",
                "description": "向量与矩阵运算必须维度一致，概率分布的归一化误差应保持接近 0。",
            }],
            "dimensionality-reduction": [{
                "id": "information-compression",
                "title": "信息保留与压缩平衡",
                "description": "保留更多主成分会提高信息保留，但压缩比例会下降。",
            }],
            "data-processing-sensitivity": [{
                "id": "data-quality-throughput",
                "title": "数据质量与吞吐权衡",
                "description": "提高向量化比例通常会提高吞吐，但缺失率会减少可用数据。",
            }],
            "model-complexity-generalization": [{
                "id": "capacity-generalization",
                "title": "容量与泛化平衡",
                "description": "模型复杂度、样本量和正则强度共同决定验证表现与泛化差距。",
            }],
            "clustering-configuration": [{
                "id": "cluster-stability",
                "title": "簇结构与稳定性",
                "description": "聚类数、噪声和初始化次数应同时观察，不能只追求更高的簇数。",
            }],
            "optimization-dynamics": [{
                "id": "optimization-stability",
                "title": "收敛与训练成本",
                "description": "学习率和训练轮次影响收敛与稳定性，批量大小会改变训练成本。",
            }],
        }
        constraints = constraints_by_template.get(template_id, [{
            "id": "template-contract",
            "title": "参数与指标关系",
            "description": template.summary,
        }])
        observation_by_template = {
            "rag-hybrid-tuning": "比较至少两组参数，说明召回数量和检索权重如何共同影响召回、排序质量与延迟。",
            "classifier-threshold-calibration": "比较至少两组参数，说明决策阈值和拒判区间如何共同影响准确性、误报率与覆盖率。",
            "linear-algebra-probability": "比较至少两组参数，说明向量尺度、矩阵维度和概率温度如何影响点积、矩阵迹、概率熵，同时核对归一化误差。",
            "dimensionality-reduction": "比较至少两组参数，说明保留维数和噪声如何影响解释方差、重构质量与压缩比例。",
            "data-processing-sensitivity": "比较至少两组参数，说明数据规模、向量化比例和缺失率如何影响处理耗时、吞吐与可用数据比例。",
            "model-complexity-generalization": "比较至少两组参数，说明模型复杂度、样本量和正则强度如何影响训练得分、验证得分与泛化差距。",
            "clustering-configuration": "比较至少两组参数，说明聚类数、噪声和初始化次数如何影响轮廓系数、稳定性与计算成本。",
            "optimization-dynamics": "比较至少两组参数，说明学习率、批量大小和训练轮次如何影响损失、收敛程度与训练稳定性。",
        }
        observation = observation_by_template.get(template_id, f"比较至少两组参数，解释{template.title}中的指标变化和适用边界。")
        x_axis = next((item.label for item in template.parameters if item.key == template.sweep_parameter_key), "参数实验序列")
        completion_rule = str(item.get("completion_rule") or "至少运行一次有效参数组合，并提交符合提示的观察结论。")
        return _canonical({
            "schemaVersion": "f6.interactive-model.v1",
            "templateId": template_id,
            "title": title,
            "summary": f"围绕“{knowledge_point}”调节参数、观察结果变化，并用自己的话解释其中的规律。",
            "courseTitle": str(context.get("course_title") or "当前课程"),
            "knowledgePoint": {"id": str(manifest.get("knowledge_point_id") or ""), "title": knowledge_point},
            "adaptation": {
                "learningGoal": str(context.get("learning_goal") or f"通过参数实验理解{knowledge_point}的变化规律"),
                "profileSummary": str(context.get("profile_adaptation") or "按当前画像保留分步参数说明和观察提示。"),
                "masterySummary": str(context.get("mastery_summary") or "当前掌握证据仍在积累。"),
                "recentLearningSummary": str(context.get("recent_learning_summary") or "暂无近期有效学习记录。"),
            },
            "parameters": parameters,
            "constraints": constraints,
            "dataset": {
                "id": f"dataset-{str(manifest.get('knowledge_point_id') or 'current')}",
                "title": f"{knowledge_point}练习样本",
                "summary": "这组样本用于本次练习，不访问外部网络或真实用户数据。",
                "sampleCount": max(12, len(source_snapshots) * 8),
                "sourceRefIds": source_ids,
            },
            "chart": {
                "kind": "line", "xAxisLabel": x_axis, "yAxisLabel": "计算结果", "series": series,
            },
            "observationPrompt": {
                "id": "observation-main", "prompt": observation, "minimumCharacters": 20,
                "completionRule": completion_rule,
            },
            "completionRule": completion_rule,
            "sourceRefIds": source_ids,
            "semanticContext": semantic,
        })
    elif resource_type == "video":
        recommendations = _video_recommendations(
            knowledge_point,
            [str(item["source_ref_id"]) for item in source_snapshots],
        )
        return _canonical({
            "schemaVersion": "f5.video-recommendation.v1",
            "title": title,
            "summary": f"围绕“{knowledge_point}”提供可追溯的视频来源，明确许可边界和观看方式。",
            "learningGoal": str(context.get("learning_goal") or f"通过视频来源补充理解{knowledge_point}的机制与应用。"),
            "adaptationSummary": str(context.get("profile_adaptation") or "根据当前画像优先推荐与学习目标和课程章节一致的来源。"),
            "recommendations": recommendations,
        })
    elif resource_type == "deck":
        source_ids = [str(item["source_ref_id"]) for item in source_snapshots]
        return _canonical({
            "schemaVersion": "f5.deck.v1",
            "title": title,
            "summary": f"以 16:9 课件梳理“{knowledge_point}”的概念、机制、边界和下一步学习。",
            "learningGoal": str(context.get("learning_goal") or f"能够解释{knowledge_point}的核心机制并辨认适用条件。"),
            "adaptationSummary": str(context.get("profile_adaptation") or "当前课件按已有画像控制信息密度，并把实训与测验保持为独立资源。"),
            "slides": [
                {
                    "id": "slide-title", "layout": "title", "title": knowledge_point,
                    "subtitle": "从概念理解到实际应用", "body": "",
                    "bullets": [], "speakerNotes": "先说明本节要解决的问题，再引导学生观察关键机制。",
                    "sourceRefIds": source_ids,
                },
                {
                    "id": "slide-problem", "layout": "content", "title": "它解决什么问题",
                    "subtitle": "先建立问题边界", "body": f"围绕“{knowledge_point}”辨认输入、输出、成立条件和可观察结果。",
                    "bullets": ["明确任务目标", "区分条件与结论", "找到对应复习章节"],
                    "speakerNotes": "引导学生先说清问题，再进入机制。", "sourceRefIds": source_ids,
                },
                {
                    "id": "slide-mechanism", "layout": "two_column", "title": "核心机制",
                    "subtitle": "概念不是孤立术语", "body": f"把{knowledge_point}拆成关键步骤，并连接到结果检查。",
                    "bullets": ["条件与假设", "关键转换", "结果与验证"],
                    "speakerNotes": "用一个具体例子解释每一步，并提醒学生注意适用条件。", "sourceRefIds": source_ids,
                },
                {
                    "id": "slide-boundary", "layout": "content", "title": "边界与常见误区",
                    "subtitle": "知道什么时候不能直接套用", "body": "只记结论、忽略输入条件和验证证据，会导致迁移到新情境时判断失真。",
                    "bullets": ["不把相关性当因果", "不把单次结果当稳定结论", "不跳过来源与验证"],
                    "speakerNotes": "使用反例帮助学生建立适用边界。", "sourceRefIds": source_ids,
                },
                {
                    "id": "slide-next", "layout": "closing", "title": "下一步学习",
                    "subtitle": "从理解进入可验证行动", "body": "返回资源中心，继续测验题、实训任务书、代码沙盒或可交互模型。",
                    "bullets": ["先完成今日必做任务", "需要帮助时引用当前课件进入智能对话"],
                    "speakerNotes": "浏览课件本身不会自动完成今日任务。", "sourceRefIds": source_ids,
                },
            ],
        })
    elif resource_type == "feynman":
        body = f"### 复述任务\n请用自己的话解释核心概念、适用条件和一个反例，并说明{practical_focus}。\n\n{source_anchor}"
    else:
        body = f"### 核心内容\n围绕“{knowledge_point}”组织定义、关键步骤、例子和学习检查点。实践重点：{practical_focus}。\n\n{source_anchor}"
    return (
        f"# {title}\n\n"
        f"**资源类型**：{label}\n\n"
        f"## 学习目标\n\n围绕 `{knowledge_point}` 完成一次可追溯的学习活动。\n\n"
        f"## 内容\n\n{body}\n\n"
        f"## 延伸阅读\n\n- {source_title} · {source_location}\n"
    )


def _real_model_backend() -> Any:
    """Build the configured live backend without a deterministic fallback."""
    if CONFIG.llm_provider.lower().strip() not in {"openai", "vllm"}:
        _fail("resource_generation.model_required", "资源合同要求真实模型生成，当前未配置 OpenAI-compatible 模型。")
    if not CONFIG.llm_endpoint or not CONFIG.llm_api_key:
        _fail("resource_generation.model_unavailable", "真实资源生成需要配置模型 endpoint 和 API key。")
    return build_async_llm(
        model="deepseek-v4-flash",
        allow_fallback=False,
        thinking_mode="max",
        reasoning_effort="max",
        # Reasoning and the teaching document share the output budget. Start
        # with the same supported room already used by continuation/review,
        # instead of exhausting 32k before the document can finish. Larger
        # configured budgets remain intact; overflow still uses saved parts.
        max_tokens=max(CONFIG.llm_max_tokens, 65536),
    )


# The interactive-lab registry is the only source of parameter and metric
# contracts.  These terms only choose an applicable experiment family; they
# never generate resource prose or replace a model response.
_INTERACTIVE_TEMPLATE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "rag-hybrid-tuning": (
        "检索", "rag", "向量", "关键词", "重排", "召回", "embedding", "retrieval", "search",
    ),
    "classifier-threshold-calibration": (
        "分类", "逻辑回归", "混淆矩阵", "精确率", "召回率", "阈值", "校准", "误报", "precision", "recall", "threshold",
    ),
    "data-processing-sensitivity": (
        "数据处理", "数据清洗", "缺失值", "向量化", "pandas", "numpy", "特征工程", "吞吐", "数据预处理", "data processing",
    ),
    "model-complexity-generalization": (
        "监督学习", "决策树", "集成学习", "过拟合", "欠拟合", "泛化", "正则化", "模型容量", "回归", "generalization", "overfitting",
    ),
    "clustering-configuration": (
        "聚类", "k-means", "kmeans", "无监督", "轮廓系数", "簇", "cluster", "clustering",
    ),
    "dimensionality-reduction": (
        "降维", "主成分", "pca", "解释方差", "重构误差", "特征压缩", "dimensionality", "principal component",
    ),
    "optimization-dynamics": (
        "梯度下降", "反向传播", "学习率", "批量训练", "训练轮次", "损失函数", "神经网络", "优化", "收敛", "learning rate", "backpropagation",
    ),
}


def _interactive_template_for_knowledge_point(
    knowledge_point: str, teaching_scope: dict[str, Any] | None = None,
) -> LabTemplate | None:
    # A unit may enter through a definition that has no experiment on its own.
    # Use its confirmed concepts, never the learner's unrelated career goal or
    # the entire course title, to resolve the experiment family consistently.
    scoped_points = (teaching_scope or {}).get("knowledge_points") or []
    if scoped_points:
        candidates = [_interactive_template_for_knowledge_point(str(point.get("title") or ""))
                      for point in scoped_points if isinstance(point, dict)]
        supported = [template for template in candidates if template is not None]
        if supported:
            counts = {template.template_id: sum(item.template_id == template.template_id for item in supported)
                      for template in supported}
            return max(supported, key=lambda template: counts[template.template_id])
        return None
    normalized = str(knowledge_point or "").strip().casefold()
    if not normalized:
        return None
    from app.concept_labs import TOPIC_LABS
    if normalized in TOPIC_LABS:
        return get_template(TOPIC_LABS[normalized])
    # Exact concepts precede family keywords: matrix vectors are not retrieval
    # vectors, and model complexity is not algorithmic time complexity.
    if any(term in normalized for term in ("过拟合", "欠拟合", "模型复杂度", "模型容量")):
        return get_template("model-complexity-generalization")
    if normalized in {"向量", "矩阵", "概率基础", "线性代数"} or any(term in normalized for term in ("向量、矩阵", "向量矩阵", "线性代数", "概率基础", "矩阵运算", "点积")):
        return get_template("linear-algebra-probability")
    # Explicit semantic families cover the two built-in manifests.  They run
    # before the legacy keyword scorer so a broad term such as "学习" cannot
    # hijack a more specific experiment.
    explicit_families: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("sample-frequency-estimation", ("频率与概率", "频率和概率", "样本频率", "总体比例", "互补事件", "独立重复试验", "frequency estimation")),
        ("prediction-score-to-class", ("监督学习的输入", "样本、特征与标签", "样本、特征和标签", "回归与分类任务", "原始分数与类别", "预测分数与类别")),
        ("inventory-demand-boundary", ("概率需求库存", "确定提前期", "固定提前期", "单店单品的随机需求", "库存模型假设", "单级单品种", "缺货延期", "缺货丢失", "probabilistic demand inventory", "backordering", "lost sales")),
        ("parallel-training-throughput", ("计算性能", "异步计算", "并行训练", "并行计算", "通信重叠", "amdahl")),
        ("model-complexity-generalization", ("训练误差", "验证误差", "泛化误差", "训练集与验证集", "训练集和验证集", "training error", "validation error")),
        ("sklearn-fit-predict", ("scikit-learn", "sklearn", "训练与推理接口", "fit与predict", "fit 与 predict")),
        ("exploratory-data-distribution", ("探索性数据分析", "探索性分析", "描述统计", "异常值", "exploratory data analysis")),
        ("data-processing-sensitivity", ("numpy", "向量化计算")),
        ("data-processing-sensitivity", ("python 机器学习编程基础", "python机器学习编程基础")),
        ("rag-hybrid-tuning", ("rag", "混合检索", "文档解析", "文档切分", "向量检索", "关键词检索", "重排")),
        ("agent-workflow", ("工具调用", "react", "agent", "智能体", "coding agent", "mcp", "skill", "工作流", "个性化学习")),
        ("attention-mechanics", ("注意力", "transformer", "qkv", "多头", "位置编码", "自注意力")),
        ("language-generation", ("自然语言处理", "预训练", "大语言模型", "语言模型", "指令微调", "偏好对齐", "生成")),
        ("clustering-configuration", ("聚类", "k-means", "kmeans", "无监督", "clustering")),
        ("optimization-dynamics", ("优化算法", "学习率", "训练稳定性", "梯度下降", "收敛", "正则化")),
        ("dimensionality-reduction", ("降维", "主成分", "pca", "解释方差", "重构误差")),
        ("graph-traversal", ("图神经网络", "知识图谱", "图表示", "图遍历", "bfs", "dfs", "拓扑排序", "最短路", "连通性")),
        ("dynamic-programming", ("动态规划", "背包", "区间", "路径 dp", "状态压缩")),
        ("search-boundary", ("二分查找", "二分", "边界", "哈希查找", "双指针")),
        ("sorting-strategy", ("排序", "归并", "快速排序", "堆排序", "线性排序", "稳定性")),
        ("recursion-backtracking", ("递归", "分治", "回溯", "剪枝")),
        ("algorithmic-strategy", ("贪心", "局部最优")),
        ("heap-priority-queue", ("堆", "优先队列", "top-k", "任务调度")),
        ("tree-traversal", ("二叉树", "二叉搜索树", "平衡", "前驱", "后继", "树遍历")),
        ("data-structure-operations", ("数组", "字符串", "链表", "指针", "栈", "队列", "哈希表", "冲突", "lru", "trie", "前缀树")),
        ("algorithm-complexity", ("复杂度", "规模", "渐进", "时间与空间")),
        ("neural-architecture", ("多层感知机", "反向传播", "卷积神经网络", "循环神经网络", "计算机视觉", "视觉表征", "神经网络结构")),
        ("algorithmic-problem-framing", ("人工智能、机器学习与深度学习概览", "人工智能概览", "算法问题建模")),
    )
    for template_id, terms in explicit_families:
        if any(term.casefold() in normalized for term in terms):
            return get_template(template_id)
    # Score every matching term instead of returning the first substring hit.
    # This keeps specific concepts such as "分类模型召回率" in the
    # classifier family while terms like "向量检索召回率" still prefer RAG
    # because it matches several retrieval-specific terms.
    ranked: list[tuple[int, int, int, str]] = []
    for order, (template_id, keywords) in enumerate(_INTERACTIVE_TEMPLATE_KEYWORDS.items()):
        matches = [
            keyword for keyword in keywords
            if keyword.casefold() in normalized
            # "无监督学习" is a clustering concept; do not let the
            # substring "监督学习" route it to the supervised-generalization
            # template.
            and not (keyword == "监督学习" and "无监督学习" in normalized)
        ]
        if matches:
            ranked.append((sum(len(keyword) for keyword in matches), len(matches), -order, template_id))
    if not ranked:
        return None
    _, _, _, template_id = max(ranked)
    return get_template(template_id)


def _interactive_template_directory(template: LabTemplate) -> dict[str, Any]:
    """Expose the selected template's contract to the live model."""
    execution = experiment_execution_info(template.template_id)
    return {
        "templateId": template.template_id,
        "title": template.title,
        "summary": template.summary,
        "applicability": template.applicability,
        "sweepParameterKey": template.sweep_parameter_key,
        "parameters": [item.model_dump(mode="json") for item in template.parameters],
        "metrics": [
            {
                "key": item.key,
                "label": item.label,
                "unit": item.unit,
                "higherIsBetter": item.higher_is_better,
            }
            for item in template.metrics
        ],
        "publicScenarios": list(template.public_scenarios),
        "executionMode": execution["mode"],
        "executionDescription": execution["description"],
        "capabilities": execution["capabilities"],
    }


def _complete_implicit_interactive_contract(
    payload: dict[str, Any],
    *,
    knowledge_point: str,
    teaching_scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Complete registry-owned fields when a model omits the template echo.

    The applicable template is selected from the current knowledge point by
    the product, not invented by the model.  Some compatible providers return
    the experiment narrative but omit ``templateId`` and copy generic
    parameter/metric examples.  In that narrow case we retain all model prose
    and replace only the registry-owned contract fields so the published
    artifact can run.  An explicitly supplied (even incorrect) template id is
    never rewritten; the normal mismatch error remains authoritative.
    """
    template = _interactive_template_for_knowledge_point(knowledge_point, teaching_scope)
    if template is None:
        return payload
    declared_template = str(payload.get("templateId") or "").strip()
    if declared_template and declared_template != template.template_id:
        return payload
    completed = dict(payload)
    completed["templateId"] = template.template_id
    if not isinstance(completed.get("parameters"), list) or not completed["parameters"]:
        completed["parameters"] = [item.model_dump(mode="json") for item in template.parameters]
    raw_chart = completed.get("chart")
    if isinstance(raw_chart, dict) and (not declared_template or not raw_chart.get("series")):
        chart = dict(raw_chart)
        chart["series"] = [
            {
                "key": metric.key,
                "label": metric.label,
                "unit": metric.unit,
                "higherIsBetter": metric.higher_is_better,
            }
            for metric in template.metrics
        ]
        completed["chart"] = chart
    return completed


def _normalize_interactive_constraints(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep model-authored constraint text while completing its public shape."""
    raw = payload.get("constraints")
    if not isinstance(raw, list) or not raw:
        return payload
    constraints = []
    for index, item in enumerate(raw, start=1):
        if isinstance(item, str):
            description = teacher_text(item)
            title = f"实验约束 {index}"
        elif isinstance(item, dict):
            description = teacher_text(item.get("description") or item.get("detail") or item.get("title"))
            title = teacher_text(item.get("title") or f"实验约束 {index}")
        else:
            continue
        if not description:
            continue
        constraints.append({
            "id": str(item.get("id") if isinstance(item, dict) else "").strip() or f"constraint-{index}",
            "title": title,
            "description": description,
        })
    if not constraints:
        return payload
    completed = dict(payload)
    completed["constraints"] = constraints
    return completed


def _normalize_interactive_dataset(payload: dict[str, Any], *, knowledge_point: str) -> dict[str, Any]:
    """Keep model dataset prose while completing the required public fields."""
    dataset = payload.get("dataset")
    if not isinstance(dataset, dict) or not dataset:
        return payload
    title = teacher_text(dataset.get("title") or knowledge_point)
    summary = teacher_text(dataset.get("summary") or dataset.get("description") or title)
    if not title or not summary:
        return payload
    completed_dataset = {
        **dataset,
        "id": str(dataset.get("id") or "dataset-interactive").strip(),
        "title": title,
        "summary": summary,
        "sampleCount": dataset.get("sampleCount"),
    }
    completed = dict(payload)
    completed["dataset"] = completed_dataset
    return completed


def _normalize_resource_code(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept an explicit code envelope without converting it to Python repr."""
    raw = payload.get("starterCode")
    if not isinstance(raw, dict):
        return payload
    code = raw.get("code") or raw.get("content")
    if not isinstance(code, str) or not code.strip():
        return payload
    return {**payload, "starterCode": code,
            "codeLanguage": payload.get("codeLanguage") or raw.get("language") or "python",
            "codeExplanation": payload.get("codeExplanation") or raw.get("explanation") or ""}


def _resource_runtime_context() -> dict[str, Any]:
    """All teaching roles plan against the same executable code environment."""
    from app.teaching_runtime import teaching_runtime_context
    return teaching_runtime_context()


_RESOURCE_LEARNING_ACTIONS = {
    "handout": "阅读讲解、与主题相符的完整示例和本页小测；涉及编程时可阅读完整代码。可安排纸笔或口头的非计分自查与迁移思考，不声称本页接收这些文字或给其计分。本页没有代码编辑或运行器，不把补全函数、取消注释或运行程序作为本页必做动作。正文中提及的题号与实际小测一致。小测按选项自查，hints可在作答前按需逐步展开，答案和解析在检查答案后显示；提示不提前给结论。迁移题的hint和successCheck由学习者主动展开。本页自查不作为独立掌握证据，不支持额外文字作答加分。",
    "mind_map": "展开概念节点、阅读节点说明、追问和跳转已关联资源；没有代码运行器，starterCode字段不会显示。节点不能要求运行未提供的代码。",
    "quiz": "逐题选择一个选项并提交，系统按正确选项判分；不接收解释文字或给解释加分。题干给齐该题条件与必要公式；基础支持放在题干中的方法说明或按需展开的hints，提交后看解析。测验没有题前独立的折叠讲义/不计分完整示例区，不将这类讲义安排设为测验交付条件；题目前不先公布同题完整答案。题目hints按需逐条展开，可在作答前查看；提示不能给出正确选项或最终数值答案。借助提示作答保留实际分数，不作为独立掌握证据。",
    "feynman": "阅读任务正文、输入或录音转写第一次解释并保存，再生成评价；随后提出疑问、查看回答、第二次复述与评价，最后选择应用到后续学习。正文narrative完整可见，没有逐级提示或参考答案的折叠控件；需要的方法提示应直接写在正文中，不能要求打开未提供的提示梯或反馈检查点。没有代码运行器，starterCode字段不会显示。引用的例子须在正文给全。复述检查学习者能否自主组织解释，已学定义、基础计算和完整例子是阅读材料，不因包含这些内容就判为答案泄露；明确要求独立判断的新情境题须保留作答空间。若当前要求将特定改述后置，仅核对该改述，不扩大成禁止提供任何基础示例。",
    "deck": "逐页阅读、切换页面、记笔记和追问；本页没有代码运行器。例子与推导须在幻灯片给全；若引导运行，只能明确转到dependency_resources提供的代码沙盒，并按它的实际代码和输出安排，不得虚构断言或入口。",
    "video": "打开推荐视频、对照学习目标和记录笔记；本页只展示学习目标与推荐列表，不展示starterCode或narrative中的数据表。需要特定数据的任务须明确指向已提供的配套资源，不假定视频讲过或页面给出了未提供的材料。",
    "interactive_model": "调整注册实验参数、运行实验、对照图表与指标、提交观察；实验只执行interactive_template说明的计算，没有通用代码运行器。概念说明由narrative保存为explanation并展示；starterCode不显示。本页任务应围绕参数与图表，若使用代码阅读例子，必须在narrative完整给出代码及输入；若要运行代码须明确转到实际配套沙盒，按它真实展示的代码与输出安排。",
    "code_sandbox": "阅读完整题目和数据、编辑并运行已提供代码、查看真实输出与必需检查，基于成功运行提交完成记录；检查点的提示按需展开。可安排纸笔解释，但本页没有通用解释作答和自动判分入口，不能把运行成功当成已经独立解释了概念。",
    "training_task": "阅读任务与数据，按需展开步骤提示和参考结果；通过关联入口使用本任务冻结版本的代码与实验。steps.expectedResult和checkpoints.passCondition均默认折叠在‘完成后核对’，steps.errorGuidance默认折叠在‘需要提示’；instruction、verification、deliverables.description与rubric.evidence是直接可见的要求。审核必须按具体字段判断答案是否提前显示，不把折叠参考答案误称为可见提交清单；可见要求中真正代答仍须修正。整理实训报告会在笔记中创建待填写的任务要求，学习者自己写观察与解释，不预填参考答案。已存报告可继续编辑；保存报告本身不产生评分，也不等于独立掌握，配套操作状态按实际记录显示。",
}

_RESOURCE_STEP_TYPES = {"handout", "training_task", "code_sandbox"}


def _resource_learning_context(resource_types, context, dependencies):
    """Keep planning and review tied to the actual learning surfaces in scope."""
    needs_template = bool({"interactive_model", "training_task"}.intersection(resource_types)) or any(
        item.get("type") == "interactive_model" for item in dependencies if isinstance(item, dict)
    )
    template = _interactive_template_for_knowledge_point(
        str(context.get("knowledge_point_title") or ""), context.get("teaching_scope"),
    ) if needs_template else None
    return {
        "learning_actions": {kind: _RESOURCE_LEARNING_ACTIONS.get(
            kind, "按当前资源合同与提供的运行能力安排学习动作。") for kind in resource_types},
        "interactive_template": _interactive_template_directory(template) if template else None,
    }


_HANDOUT_PRESENTATION_GUIDANCE = (
    "先按当前任务证据区分已会与待学内容，再决定示例载体。‘新公式先看完整示例’只适用于仍需教学的部分，不要求已掌握内容再次从完整讲解开始，也不等于偏好代码或已经会编程。"
    "需要示范的内容适合编程且明确偏好先看可运行例子时，该部分先用kind=code的完整短代码展示输入与预期输出，再解释机制；手算表格不能替代所需代码。"
    "需要示范且偏好直观例子时，先给短小数值场景或两行手算，再就地解释必要符号；基础支架不能变成长术语表挡在例子前。"
    "尚未系统学习编程而已会读表时，用可直接阅读的数据表承载任务；计算方法尚未掌握的步骤就地示范，已掌握的选择与解释先独做再按需回看。需要真实运行的示例配简短运行与读输出说明。"
)
_TEACHING_REVISION_GUIDANCE = (
    "active_requirements是当前生效的教学要求，生成、审核和评分标准须一致。"
    "其中source_request若存在，是本次原始请求；规划摘要不能省略或降低其中的任务。"
    "旧稿只提供待修正文，不是额外要求；不恢复已经撤销的句数、步骤或格式限制。"
    "review_decisions记录已经裁决的问题和依据，修复或撤销的意见保持关闭；"
    "只有当前正文出现新的具体错误证据才重新提出，不能用措辞偏好重复打开问题。"
    "revision_feedback是本次待落实的改动，须核对事实，不把模型误判当作新的学习要求。"
)
_RESOURCE_OUTPUT_FIELDS = {
    "handout": "practiceSteps、quizQuestions、estimatedMinutes（完成本页阅读与必做练习所需的正整数分钟；可用时段不是必须用满的最低时长）；仅需编程教学时提供starterCode",
    "mind_map": "rootNodeId、nodes；每个节点包含nodeId、parentNodeId、label、summary、relation、depth、sourceRefs",
    "training_task": "practiceSteps、rubric、environment、data、prerequisites、estimatedMinutes（实际完成本页核心任务所需的正整数分钟）",
    "code_sandbox": "practiceSteps、starterCode、requiredChecks",
    "interactive_model": "templateId、parameters、constraints、dataset、chart、completionRule、observationPrompt",
    "deck": "slides",
    "quiz": "quizQuestions",
}


def _real_model_prompt(
    *,
    resource_type: str,
    item: dict[str, Any],
    manifest: dict[str, Any],
    source_snapshots: list[dict[str, Any]],
    semantic_plan: str = "",
) -> tuple[str, str]:
    context = _public_generation_context(manifest)
    knowledge_point = str(context.get("knowledge_point_title") or manifest.get("knowledge_point_id") or "当前知识点")
    semantic = _semantic_context(manifest=manifest, knowledge_point=knowledge_point, source_snapshots=source_snapshots)
    safe_context = {
        "resource_type": resource_type,
        "learning_actions": _RESOURCE_LEARNING_ACTIONS.get(resource_type, "按当前资源合同与提供的运行能力安排学习动作。"),
        "user_instruction": "" if manifest.get("active_requirements") else str(manifest.get("user_instruction") or ""),
        "active_requirements": requirements_for(manifest, [resource_type]),
        "review_decisions": manifest.get("review_decisions") or [],
        "title": str(item.get("title") or resource_type),
        "course": context,
        "learner_adaptation": _profile_adaptation_plan(context),
        "semantic_context": semantic,
        "shared_semantic_plan": str(semantic_plan or ""),
        "resource_brief": next((brief for brief in manifest.get("resource_briefs") or []
                                if brief.get("type") == resource_type), {}),
        "revision_feedback": str(item.get("revision_feedback") or ""),
        "revision_source": manifest.get("revision_source"),
        "video_candidates": manifest.get("video_candidates") or [],
        "dependency_resources": manifest.get("dependency_resources") or [],
        "runtime": _resource_runtime_context(),
        "sources": _resource_prompt_sources(manifest, source_snapshots, resource_type),
    }
    selected_template = _interactive_template_for_knowledge_point(knowledge_point, context.get("teaching_scope"))
    safe_context["interactive_template"] = (
        _interactive_template_directory(selected_template)
        if selected_template and resource_type in {"interactive_model", "training_task"} else None
    )
    type_requirements = {
        "handout": (
            "handoutSections 按教学目标组织所需的完整段落（id、title、kind、content、sourceRefIds），不为凑数量重复内容，"
            "kind 可为 concept、figure、example、counterexample、code、review、task；数组顺序就是实际阅读顺序，按当前完成依据和已确认教法编排。"
            + _HANDOUT_PRESENTATION_GUIDANCE +
            "code段同时给出code和explanation；普通段的content完整表达正文。narrative用于最后串联回顾，不在开头重复全文。"
            "普通正文负责讲解、已解示例和方法回顾；不要另写包含本页小测或迁移题答案的章节。普通example、counterexample和misconceptions正文始终可见，同段已给解答时不能要求先独立尝试、遮住答案或先不看答案。"
            "需要在开头或中途先尝试的独立任务，用kind=task章节：content写完整题设，hint写可选方法提示，successCheck写完成后核对；它按章节顺序显示，提示与核对默认收起。末尾迁移题仍可放transferQuestions，同一题只放一次。"
            "已掌握的能力可从task开始，再按需要回看方法；新的计算方法先给局部示例，不因此重讲已会的定义与判断。"
            "quizQuestions单独承载小测，answer/explanation仅在检查答案后展示；transferQuestions单独承载迁移题，successCheck由学习者主动展开。"
            "handoutSections、narrative、practiceSteps不得重复这两组题目的正确选项、完整解答或核对结果；已解例题应明确标为示例。"
            "narrative用总结语气回顾已经讲过的内容，不再要求先做开篇任务；starterCode若复用正文代码，逐字复用该段代码，不再生成语义相同的第二份。"
            "代码按本次课程主题和学习要求选择；不需要编程时省略starterCode或留空，不创建code段。纸笔记录卡、操作清单和计算例子放普通example或concept正文，不能伪装为程序。"
            "本次明确不需要编程时，长期画像中的代码偏好不能覆盖它；仍保留完整例子、小测和适用的迁移练习。"
            "同时可提供 transferQuestions（迁移问题数组，每题有title、prompt、可选hint和successCheck）和 misconceptions（误区数组）。"
            "独立迁移题须改变未在正文解完的条件，不把完整例题换个标题当独立任务；题干在prompt、可选支架在hint、完整核对结果仅放successCheck。"
            "quizQuestions 的 prompt 只包含完整题干和必要数据，不能复述整段讲义；"
            "每题可提供hints字符串数组：按画像给概念线索、操作步骤、检查方向，不需要时为空；不要把提示塞进正文或解析替代此字段。"
            "每题 answer 必须为 A、B、C 或 D，并且与四个选项中的正确项一致。"
            "解析中的每个选项字母与其实际表达式、计算结果逐一对应；检查索引返回整行、整列还是单个元素，不能凭相近措辞推断。"
            "涉及筛选时逐行列出所有命中元素及其位置，重复数值按各自出现次数计数，不得当作去重集合；区分严格大于与大于等于。"
            "示例函数的返回项、顺序及数量必须与return语句一致，调用后另行计算或打印的量不能说成函数返回值。"
            "正文提及第几道学习检查时必须与最终quizQuestions对应；题目变更后同步更新概述，不能沿用旧题说明。"
            "数组下标从0开始；中文‘第几行/列’从1开始，若用0起算须明确写‘下标’，不能混淆。"
            "本页代码仅供阅读，必须给出完整实现与可推导的结果；迁移练习可让学生手算或解释，不要求在本页补全和运行程序。"
            "practiceSteps是本页的概念学习流程，不等于另一个实训任务的步骤；未提供实际任务书时不得编造它的步数或要求。"
            "这些字段必须是真实教学内容，不要用 placeholder。"
        ),
        "quiz": "quizQuestions 按学习范围提供足够题目，每个对象有 knowledgePointId（实际考查的本单元知识点ID）、prompt、options（四个非空选项正文的数组，不要只返回 A/B/C/D 标签）、answer(A-D)、explanation、hints（字符串数组，按画像需要给术语、步骤、结果检查提示；高支架的计算/应用题应有逐级提示，不直接给答案或选项，可独立完成的题可为空）、bloom（remember/understand/apply/analyze/evaluate/create）、difficulty（0 到 1 的数字，不要难度文字标签）。每道题单独显示，prompt必须包含计算所需的完整数据、数组或矩阵，不能用‘同一个矩阵’指代其他资源或上一题。提交前按最终options顺序逐项核对explanation中的A-D字母、正确项和错误项，不能重复错标字母。summary和learningGoal简洁概括本组能力，不复述备课指令；必要解题条件写进对应题干。新计算方法需要示范时，在hints中用另一组数值完整示范，再回到当前题；不提前计算当前题答案。按已确认单次时段评估题量，需要分次学习时输出studySessions数组，每段包含startQuestion、endQuestion（从1开始、连续、不重不漏覆盖全部题目）和estimatedMinutes（按题量和反馈阅读估算的正整数）；不需分段时返回空数组。页面在对应题组展示时间和续作入口，不把分段安排藏进summary。",
        "mind_map": "导图按来源中的概念与关系组织真实层级nodes，不用学习步骤代替知识结构，不固定分支数或层数。"
            "rootNodeId指向唯一根节点；根的parentNodeId为null、depth为0，其余节点指向已存在父节点，depth为父深度加一。"
            "label简短明确，summary解释这个节点本身，relation说明它与父概念的关系；分清组成、前提、对比、机制和应用。"
            "sourceRefs只能引用给定来源；不编造掌握度或配套资源。完整覆盖当前选区或已确认教学范围，不以目录挂靠主题替代。"
            "根节点只作概述，具体讲解放在相关分支，不把整篇讲义塞进根节点。需要时可以在节点summary中写公式或完整阅读代码；"
            "此页没有代码运行器，不能要求运行未提供的代码或声称存在可操作实验，不额外生成practiceSteps。",
        "feynman": "费曼页展示narrative供学生复述，并提供两轮复述、评价、疑问答复与应用反馈；不展示starterCode，也没有代码运行器。安排自述、对照例子和解释边界的学习动作。方法型提示直接写入正文；参考答案与反馈在学生提交后由实际评价流程提供，不声称正文中存在提示梯或反馈检查点按钮。若只安排几分钟的可选复述，这个时长指准备第一次解释，后续评价、答疑和再次复述另按实际需要继续。若必须阅读代码，完整代码及输入放进narrative，按其推理解释，不把运行未提供的程序当作复述前置。",
        "training_task": (
            "practiceSteps按完成任务所需安排，每个对象都有title、instruction、expectedResult、errorGuidance、submissionRequirement；"
            "rubric为评分项数组，每项包含id、criterion、evidence、points（0到100的整数），全部分值合计100；"
            "按实际成果的重要性分配分数，evidence只写核对依据。可选拓展不占核心分数，保留为0分项；"
            "environment 和 data 必须是非空字符串数组。必须分别安排配套代码运行、交互实验对照、机制解释和总结报告，"
            "不能只在 narrative 提及实验。expectedResult保留参考答案，只在学习者展开核对时显示；"
            "submissionRequirement说明要提交的观察、推理和记录及判定标准，不填写参考答案或独立题的结论；它进入交付要求和报告模板。"
            "narrative及data给出题干、必要数据、预测时点和已知条件；独立题的解答不要提前写入这些字段。"
            "因此目标中要求的全部观察与反思必须落实到相应步骤；实验对照明确固定参数和唯一改变的参数。"
            "若迁移任务需要修改代码，明确修改位置和运行范围；不能把建议当已输出的结果。"
            "已进行最终测试后，迁移练习必须在副本中移除或跳过最终测试段，只运行训练与交叉验证；"
            "不得要求重跑含最终测试的整个程序再忽略测试输出，也不能重复使用测试集选参。"
        ),
        "code_sandbox": (
            "starterCode 必须是非空代码字符串；requiredChecks 必须是非空对象数组。每项必须包含 id、label 和 kind，"
            "kind 只能是 exit_code_zero、stdout_contains、stderr_empty、plot_count_at_least；"
            "kind=stdout_contains 时必须有非空 expectedText，kind=plot_count_at_least 时必须有正整数 minimum。"
            "代码只使用 runtime.supportedModules 中的模块；使用明确的公开属性和普通语句，"
            "不要使用 getattr/setattr 等动态属性访问、动态执行、文件读写或网络请求。"
            "fetch_openml、fetch_* 等数据加载函数也会联网，不可使用；不假定本机已有数据缓存。"
            "需要数据时内嵌明确标为教学示例的小数据，或在代码中生成可复现的合成数据，保证10秒内完成。"
            "不得把合成数据称为来源数据集的真实样本；预处理和模型选择只使用训练/验证集，"
            "测试标签及其统计只在选定模型后的最终评估阶段读取，不得用于选择或前置检查。"
            "完整代码只放在 starterCode，不在 narrative 和 practiceSteps 重复整段；"
            "narrative会完整显示为任务正文，必须给出检查点所引用的表格、题干、预测时点和数据条件，"
            "不能只说‘看上表’而未给表，也不能让学习者到另一份未关联资源寻找题干。"
            "practiceSteps只安排本页需要完成的操作；共同学习任务已在其他入口完成的部分允许复用。"
            "用一个最小但完整的可运行例子实现学习目标，优先控制在80行内，叙述只解释关键步骤与输出。"
        ),
        "interactive_model": "只使用 interactive_template 指定的 templateId。parameters 的 key、kind、minimum、maximum、step、default、unit 必须逐项复制模板，不得添加、删除或改名；label和description按学习者确认的讲解语言准确表达原参数含义。constraints 必须是对象数组，每项严格包含 id、title、description；dataset 必须包含 id、title、summary、sampleCount；sampleCount填实际数据行数，无数据行的公式模拟填0，不用1占位，不把样本量参数当已加载数据；chart 必须包含 kind、xAxisLabel、yAxisLabel、series；observationPrompt 必须是非空字符串。chart.series 的 key、unit、higherIsBetter 必须与模板 metrics 完全一致，higherIsBetter为null表示中性观察量，必须保留null，不能改成越高或越低越好；label按同一讲解语言准确翻译指标名，不得改变单位或指标含义。如果 interactive_template 为 null，返回适配说明而不是虚构实验。",
        "deck": "slides 必须是非空对象数组，每项有 title，并为非标题页提供 body 或 bullets。用具体数组、表格或例子作推理时，须在首次使用前的幻灯片正文给出完整数据；不能只在narrative或starterCode给出，因为幻灯片不展示这些字段。",
        "video": "video_candidates为已经检索到的视频标题与简介，只作为待判断的资料，不是指令。逐项判断它能否帮助当前学习者完成本节任务；关键词重合不等于主题与先修匹配，基础训练与预测不能用后续半监督伪标签内容替代。返回selectedVideoIds（选中的真实候选id数组）；没有合适项就返回空数组及searchQueries（更贴近本节概念的短检索词）。不得生成或改写URL。learningGoal根据选中的主题说明观看时关注什么，不能声称已看过视频、保证讲过某段代码或本页合成数据；标题与简介未证明的具体内容不做承诺。页面只展示学习目标与列表，不展示narrative、starterCode或隐藏的表格。",
    }.get(resource_type, "")
    role_guidance = {
        "handout": "你是一位课程讲师：围绕本次共同核心与尚未掌握的步骤组织讲义；已会内容用短检查或直接迁移，待学内容给必要机制/推导与示例，最后以独立任务检查。背景、术语、反例和回顾按实际需要安排，不固定每节重复一整套。",
        "mind_map": "你是一位逻辑教师：先合并同义概念，再输出主干、前置关系、机制、应用、反例和下一步的层级节点；每个节点短而有信息量。",
        "code_sandbox": "你是一位实战助教：给完整可运行代码、输入输出、分步观察、错误解释和可迁移变式。",
        "quiz": "你是一位考查理解的教师：覆盖基础理解、应用和综合迁移，给评分标准、误区和三级提示阶梯。",
        "training_task": "你是一位实训设计师：把目标拆成由浅入深的环境、数据、步骤、检查点和交付物。",
        "deck": "你是一位课程设计师：让课件形成问题—机制—示例—边界—练习—下一步的叙事链。",
        "video": "你是一位学习顾问：只解释系统候选视频与学习目标的匹配，不生成或猜测 URL。",
        "interactive_model": "你是一位实验设计师：在模板参数契约内设计可观察的实验、限制、数据和结论问题。",
        "feynman": "你是一位教学教练：要求学习者用自己的话复述概念、条件、反例和应用，并给出自检标准。提供必要的定义、基础计算和阅读例子；复述训练不要求先删除已学材料。独立新情境的任务不给最终答案，当前要求明确后置的目标改述按相应顺序安排。",
    }.get(resource_type, "你是一位教学专家：输出可学习、可实践、可复习的完整内容。")
    legacy_role_name = {
        "handout": "理论教授",
        "mind_map": "逻辑画师",
        "code_sandbox": "极客助教",
        "quiz": "考官智能体",
        "video": "视频推荐官",
    }.get(resource_type)
    if legacy_role_name and legacy_role_name in LEGACY_RESOURCE_PROMPTS:
        role_guidance = f"{role_guidance}{LEGACY_RESOURCE_PROMPTS[legacy_role_name]}"
    strategy_guidance = "\n".join(
        f"- {name}: {description}"
        for name, description in LEGACY_LEARNING_STRATEGY_PROMPTS.items()
    )
    system = (
        LEARNER_FEEDBACK_INSTRUCTION
        + LEARNING_TASK_INSTRUCTION
        + TEACHING_ADAPTATION_INSTRUCTION
        + "你是 EduMatrix 的课程资源生成模型。课程来源是优先依据；当来源不足以覆盖完整教学链时，"
        "可以使用通用基础知识补足定义、例子、反例和练习，使资源仍然有教学价值。"
        "基础知识与按题设推导可以直接讲清定义和条件；来源引用只绑定实际支持的内容，不给这些补充内容伪造课程事实、来源、页码或 source_ref。"
        "区分定义恒等式、本例沿用的参数条件与一般成立条件；充分条件不能写成必要条件，可能变化不能写成必然变化。"
        "概念分类沿用当前课程明示的定义；若类别存在包含、交集或不同命名约定，说明判别口径，不擅自加排除条件。单选题逐项判断，不能让两个有重叠的选项同时符合题设。"
        "不得编造学生画像、掌握度或事件。只输出一个 JSON 对象，不要 Markdown 封装或思维链；保留本资源类型要求的全部字段。"
        "interactive_template是当前实际可运行的实验；旧共享计划若与其计算机制、参数或指标冲突，以当前模板及实际配套为准。"
        "资源包共用一个学习目标与练习成果，不意味着每种资源都重复整节课。讲义负责解释，导图/课件负责组织与回顾，测验检查理解，实验负责可观察对照，实训整合应用，复述检验表达；本资源可以独立使用，但已在配套完成的相同练习只需引用已有记录。按已确认时间给出本资源的适用片段与接续方式，不把每类都安排成同一个完整时段。"
        "代码编辑器里的全部代码和常量均可见；不打印某列不等于隐藏数据。不能把代码中的测试标签称为封存或真正盲测。"
        "需要先选择后查看结果时，安排明确的练习步骤；未给出必要数值前只要求写报告方法，看到结果后再填写具体数值。"
        "resource_brief是规划器为本页分配的具体目标、依赖和检查要求；与shared_semantic_plan一起落实到正文与实际学习动作。共享主线中的阅读、运行、实验和独立作答按各自片段接续，替代阅读不额外增加同一份必做作业。单独使用本页需要更多时间时明确区分，不改写主线时间来掩盖重复负担。"
        "完整示例可以先教方法；独立迁移须另给完整题设、业务目标和时点，不能在题干或此前正文先替学生完成该迁移题的列角色选择、计算与解释。参考解答只放入对应核对字段，不复写进任务要求。"
        "教学类比须保留定义的本义，不用操作建议替代概率/统计性质或逻辑条件。例子若违反模型其它已知条件，须明确所作简化及适用范围，不能把它说成完整适用实例。"
        "观察题以实际可见的变化为依据，允许结果不变或同向变化；未计算成本或权衡时，不要求找出必然变差的指标。"
        "比较模型须保持相同验证样本与评价口径，各候选的数据相关预处理只在训练部分拟合；允许各模型采用不同的合法预处理方法。"
        "区分信息泄漏带来的评价偏差风险与某组数值必然变好：未给具体算法与重算结果时，不能断言全量标准化一定降低MSE或重做后分数必然下降。"
        "明确区分原文图表、代码的真实计算和教学模拟，不能把固定图表观察写成这里可执行的实验。"
        "以learner_adaptation.assessment_target中的任务、先修、独立完成程度与检查条件作为共同教学标尺；"
        "difficulty_evidence区分学习记录与自述，偏好只能改变讲法，不能伪装成已掌握知识。"
        "必须把 learner_adaptation 中的 difficulty_band、scaffolding_level、explanation_style、"
        "example_context、hint_policy 和 practice_strategy 落实到正文、例子、步骤、"
        "提示和题目难度中；不要只复述适配摘要。返回内容必须能让同一知识点在不同画像下产生可观察差异。"
        "learning_requirements是已确认的实际学习条件：按语言要求写主体，目标落实到成果或练习，例子连接已有经历，"
        "操作须适用于可用设备和工具，任务按可用时段分段并能接续；不能由职业、学历或时间少推定高低能力。"
        "非编程主题不强行安排代码，学习者没有桌面环境时提供可在其现有工具上验证同一概念的操作。"
        "summary简明介绍本页目标，narrative按完整教学需要展开，避免与其他字段重复整段内容；"
        + ("practiceSteps按实际任务安排非空步骤，不凑步数；已完成的共同成果可复用，不要求重新抄写或重复运行；" if resource_type in {"training_task", "code_sandbox"} else
           "practiceSteps按本次需要组织实际学习动作，已掌握的基础不为凑步数重讲；" if resource_type == "handout" else "")
        + ("quizQuestions题量遵循本次明确要求；单题检查可以只包含一道完整题目，未指定题量时按实际学习范围安排，不为凑题数扩展任务。每题explanation讲清正确答案的依据，必要时指出易混选项违反的题设，禁止复用摘要。无需给每个干扰项编造错误操作；" if resource_type in {"handout", "quiz"} else "")
        + ("正确选项的位置自然分散，避免整组固定在同一位置或形成可猜的规律；编排后同步答案、解析和提示中的选项指代，不改变题意来凑分布。" if resource_type in {"handout", "quiz"} else "")
        + ("解释干扰项时必须按所声称的错误步骤实际算出该选项；符号写错、更新方向相反、漏系数或混淆参数与中间量不能混说。无法确知错因时只说明违反的条件，不臆造计算步骤；" if resource_type in {"handout", "quiz"} else "")
        + ("作答前的提示只给可执行的方法，不直接指定排除哪个选项、不复述正确选项的全部判断、不提前宣布关键结论或最终数值。先用其他例子教方法，再让学习者对当前条件作判断；" if resource_type in {"handout", "quiz"} else "")
        + ("handoutSections按本次待学能力组织；需要新方法时给具体定义、机制与完整例子，已有独立掌握依据时先做新任务，仅回看所需概念。边界、误区、代码按本次任务选择，不为齐备章节重讲全部基础；" if resource_type == "handout" else "")
        +
        "不要把写作要求、字段名或输出格式写进 narrative、section content、step 或题目正文；"
        "不要重复课程原文或用空泛套话填充篇幅。所有学生可见字段都要像真实老师直接讲解："
        "不要展示检索过程、上下文绑定、模型模式、生成规则或内部 ID、哈希和版本号；"
        "正常教学中的依据、约束、确定性等词保持原意，不要为了去除技术表达而替换学科术语。"
        "正文中的多行代码必须使用 Markdown 代码围栏并保留正确缩进；完整示例必须可直接运行，填空代码明确标为练习。"
        "JSON必须包含summary、learningGoal、narrative；"
        + (f"本类型另外需要{_RESOURCE_OUTPUT_FIELDS[resource_type]}；" if resource_type in _RESOURCE_OUTPUT_FIELDS else "")
        + "只生成本页实际使用的字段与内容，不额外编写其他资源的题目、代码或步骤。"
        + ("" if resource_type in {"handout", "code_sandbox"} else
           "本页不展示starterCode，不必生成该字段，不能在正文引用它或让学生阅读未展示的代码。")
        + ({"training_task": "narrative将用作页面的实训目标，只写要完成的具体成果，不重复整节讲义、备课策略和所有步骤。必要定义与示范放在对应practiceSteps的instruction，数据与预测时点放data，操作条件放environment；保留这些有效信息，不因缩短目标而删除。还必须在顶层包含 environment、data 两个非空字符串数组，以及prerequisites前置知识数组；只列完成当前任务前需要的基础，不能把本次要学会的目标当成已经掌握的前提。",
            "interactive_model": "还必须包含 templateId、parameters、constraints、dataset、chart、completionRule；parameters逐字复制interactive_template.parameters，不能改写其描述或范围。"}.get(resource_type, ""))
        + ("practiceSteps每步有title、instruction、expectedResult、errorGuidance；按实际学习顺序组织。"
           "学习动作按learning_actions组织。阅读类资源用理解条件、阅读示例、手工推理、回顾迁移，不能套用代码沙盒的编辑和运行步骤。"
           if resource_type in _RESOURCE_STEP_TYPES else "")
        +
        "若有 revision_feedback，逐项修正公开审核错误；实训必须读取 dependency_resources 的实际代码和实验指标，"
        + _TEACHING_REVISION_GUIDANCE +
        "若有revision_source，它是上一次被核对的实际原稿；在原稿上修正本次错误和受其影响的说明，保留已正确的例子、数据、题目和步骤，不另起一套内容。"
        "修正后的正文直接面向第一次阅读的学习者，不提旧稿写错、审核要求或返工过程。只保留帮助学习的解释；"
        "画像确认、系统计分边界等后台说明不要充当章节开场，必要操作限制简短说明即可。"
        "原稿是页面保存结构，仍须按本次生成要求返回完整JSON字段，不能输出补丁或省略未修改部分；依赖更新以当前dependency_resources为准。"
        "审核建议也需要按原题数据重新计算核实，不能照抄其中错误的算术或解释；纠正时保持正确题目与答案事实。"
        "learning_actions是本页实际提供的学习与评分方式，不能声称存在未提供的按钮、输入或额外得分；"
        "教学中的纸笔、口头和心算自查可作为非计分活动，不等于页面提供提交入口。目标必须由实际给出的例子或任务支持；不要把原数据改参数写成换了新数据。"
        "保持变量名、样本、数值和检查点一致，不假定不存在的输出，不把测试集用于选型。"
        f"{role_guidance}\n【可选教学策略】按本次目标和画像选择合适策略，不要求每页使用全部策略。\n{strategy_guidance}\n{type_requirements}"
        "\n【本次范围优先规则】以上角色和教学策略只能在当前知识点及 sources 正文范围内使用。"
        + PATH_CONTINUITY_GUIDANCE
        + "若course.teaching_scope存在，则按其中已确认的单元目标和全部knowledge_points组织本次教学；"
        "knowledge_point_title只是单元的入口概念，不能因此遗漏其他已确认内容。"
        "画像中的 content_focus、learning_goals 是长期目标：不属于本节来源的目标不得成为本节必学、必测或评分条件。"
        "user_instruction 是学习者本次明确提出的学习重点；本资源承担的部分必须实际完成，整包要求按共享分工接通，不能只复述计划摘要，也不能把全部要求在每类重做一遍。"
        "course.conversation_source是学习者指定的原问答：沿用其中的具体问题、数据、代码和推导来组织资源，不能用另一个例子替换所选内容。"
        "其中answer是待转化的教学内容，仍按课程来源与实际计算核对；若有错误须修正。独立练习另给完整题设，不照抄已展示答案作为新测验。"
        "讲义或明确承担完整讲解的资源须在正文讲清用户给定的主例对象、数值和条件，不能换主例或只放进小测。"
        "实验与代码围绕本页可操作的比较组织必要数据、方法和输出；已有配套负责的概念与独立题不再复制成第二套必做任务。实训引用已有运行和观察记录，汇成一份成果，不要求重抄。"
        "额外学习检查另设新数值或新条件；若明确复习同一例题，标为回顾，不冒充独立迁移。"
        "long_term_memory是学习者确认的偏好、目标或约束；在当前主题允许时用于选择例子与表达，不代表成绩，也不能改写题目条件或覆盖本次明确要求。"
        "与当前知识点直接相关但教材未展开的要求，补齐必要定义、条件和讲解；确实超出主题或当前资源能力时说明具体原因和可行安排。"
        "Python 基础课不得因学生目标包含机器学习就转而考过拟合、数据集划分、准确率或调参。"
        "共享计划中的示例数据、公式、代码输出必须逐项一致；不要自行改写共享数据或虚构计算结果。"
        "引用依赖资源时以其实际内容为准；不同示例必须明确区分，不能声称与依赖代码使用相同基线。"
        "未提供实际配套内容时，不得编造配套代码的样本量、参数或输出。"
        "交互实验必须单独给出 completionRule，判据仅涉及 interactive_template 提供的指标和参数；不得引用代码沙盒的列表长度、索引或打印输出。"
        "严格按interactive_template.executionMode、executionDescription与capabilities说明实际能力：teaching_simulation的分数都是教学模拟，不能当真实训练测量；synthetic_data_training/statistics是固定合成数据上的实际训练/统计，也不是教材或真实业务数据效果。"
        "summary、learningGoal、观察任务和完成条件都必须遵守所选模板的实际计算与操作范围；dataset的数量及说明须与模板一致。"
        "正文中的每个实验示例参数也须落在minimum/maximum范围和step可选值上；不是只把parameters字段复制正确就足够。"
        "表格只列少量设备数或参数值时，说明这是所列点的比较，不把它们之间的变化说成完整扫描找到的极值或转折点。"
        "未列出的真实数据划分、决策路径和不纯度计算只能指向实际支持它们的代码沙盒，不能声称实验页面有这些操作。"
        "不得把共享计划中虚构的参数映射当成模板的实际实现；模板只支持其目录中的参数和指标。"
        "实训每个检查点必须在依赖代码中找到对应输出或在实验中找到对应指标，若无对应项则改为已有的可核查动作。"
        "说明树路径时，明确路径属于示例浅树还是最终选出的模型，不能混用；样本数读取实际计数，不能把归一化类别比例当样本数。"
    )
    return system, json.dumps(safe_context, ensure_ascii=False, sort_keys=True)


def _real_model_payload(
    backend: Any,
    *,
    resource_type: str,
    item: dict[str, Any],
    manifest: dict[str, Any],
    source_snapshots: list[dict[str, Any]],
    loop: asyncio.AbstractEventLoop | None = None,
    semantic_plan: str = "",
) -> dict[str, Any]:
    system, user = _real_model_prompt(
        resource_type=resource_type, item=item, manifest=manifest, source_snapshots=source_snapshots,
        semantic_plan=semantic_plan,
    )
    try:
        coroutine = backend.generate(system, user, role="resource_generator")
        raw = loop.run_until_complete(coroutine) if loop is not None else asyncio.run(coroutine)
        payload = parse_json_object(raw)
    except Exception as exc:
        raise ResourceBundleError("resource_generation.model_call_failed", f"真实模型生成失败：{exc}") from exc
    if not str(payload.get("narrative") or "").strip() or not str(payload.get("summary") or "").strip():
        _fail("resource_generation.model_output_invalid", "真实模型返回缺少资源正文。")
    return payload


async def _real_model_payload_async(
    backend: Any,
    *,
    resource_type: str,
    item: dict[str, Any],
    manifest: dict[str, Any],
    source_snapshots: list[dict[str, Any]],
    semantic_plan: str = "",
    role: str = "resource_generator",
) -> dict[str, Any]:
    """Run a governed model call inside the Supervisor's shared event loop."""
    if resource_type == "interactive_model":
        context = _public_generation_context(manifest)
        knowledge_point = str(
            context.get("knowledge_point_title") or manifest.get("knowledge_point_id") or ""
        )
        if _interactive_template_for_knowledge_point(knowledge_point, context.get("teaching_scope")) is None:
            raise ResourceBundleError(
                "resource_generation.interactive_model_inapplicable",
                "当前知识点没有合适的可交互实验模板，建议改用讲义、思维导图或代码沙盒。",
            )
    system, user = _real_model_prompt(
        resource_type=resource_type,
        item=item,
        manifest=manifest,
        source_snapshots=source_snapshots,
        semantic_plan=semantic_plan,
    )
    if role == "resource_reviewer":
        system = (
            "你是 EduMatrix Resource Reviewer。只审核候选资源，不重新生成资源正文。"
            "只输出一个 JSON 对象，必须包含 approved（布尔值）、summary（字符串）、"
            "findings（数组）和 rejectedTypes（资源类型数组）；不得输出 Markdown、思维链、"
            "prompt、API key 或 reasoning_content。"
        )

    def shape_issue(payload: dict[str, Any]) -> str:
        """Return a concrete missing live-resource field, if any."""
        if resource_type in {"handout", "training_task"}:
            duration = payload.get("estimatedMinutes")
            if isinstance(duration, bool) or not isinstance(duration, int) or duration < 1:
                return "estimatedMinutes必须为实际任务时长的正整数，与步骤及正文一致；不能漏填后使用默认时长或虚减工作量"
        if resource_type == "mind_map":
            if not payload.get("rootNodeId") or not isinstance(payload.get("nodes"), list) or not payload["nodes"]:
                return "思维导图需要rootNodeId与完整nodes知识层级，不能用practiceSteps代替"
        if resource_type in _RESOURCE_STEP_TYPES:
            steps = payload.get("practiceSteps")
            minimum_steps = 1
            if not isinstance(steps, list) or len(steps) < minimum_steps or any(
                not isinstance(step, dict)
                or any(
                    not str(step.get(key) or "").strip()
                    for key in ("title", "instruction", "expectedResult", "errorGuidance")
                )
                for step in (steps if isinstance(steps, list) else [])
            ):
                return f"practiceSteps 必须包含至少{minimum_steps}个完整步骤对象"
            if resource_type == "handout":
                questions = payload.get("quizQuestions")
                if not isinstance(questions, list) or not questions:
                    return "quizQuestions 必须包含非空的完整题目对象"
                if any(
                    not isinstance(question, dict)
                    or not str(question.get("prompt") or "").strip()
                    or len([value for value in question.get("options") or [] if str(value).strip()]) != 4
                    or str(question.get("answer") or "").strip().upper() not in {"A", "B", "C", "D"}
                    for question in questions
                ):
                    return "handout 的 quizQuestions 需包含简洁题干、四个选项和 A-D 答案"
                if any("hints" in question and (not isinstance(question["hints"], list)
                       or any(not isinstance(hint, str) or not hint.strip() for hint in question["hints"]))
                       for question in questions):
                    return "每题hints必须是非空提示文字组成的数组，不需要提示时使用空数组"
        if resource_type == "quiz":
            questions = payload.get("quizQuestions")
            if not isinstance(questions, list) or not questions:
                return "quizQuestions 必须包含非空的完整题目对象"
            if any(
                not isinstance(question, dict)
                or len(question.get("options") or []) != 4
                or str(question.get("answer") or "").upper() not in {"A", "B", "C", "D"}
                or not str(question.get("prompt") or "").strip()
                for question in questions
            ):
                return "每个 quizQuestions 题目必须有题干、四个选项和 A-D 答案"
            if any("hints" in question and (not isinstance(question["hints"], list)
                   or any(not isinstance(hint, str) or not hint.strip() for hint in question["hints"]))
                   for question in questions):
                return "每题hints必须是非空提示文字组成的数组，不需要提示时使用空数组"
            scope_issue = _quiz_scope_issue(questions, _public_generation_context(manifest))
            if scope_issue:
                return scope_issue
            try:
                quiz_study_sessions(payload.get("studySessions", []), len(questions))
            except ValueError:
                return "studySessions需按顺序完整覆盖题号且不重复，每段包含startQuestion、endQuestion、estimatedMinutes正整数"
        elif resource_type == "training_task":
            for field in ("environment", "data"):
                values = payload.get(field)
                if not isinstance(values, list) or not any(str(value or "").strip() for value in values):
                    return f"{field} 必须是非空字符串数组"
            if "rubric" in payload:
                try:
                    _training_rubric(payload["rubric"])
                except ValueError as exc:
                    return str(exc)
        elif resource_type == "code_sandbox":
            checks = payload.get("requiredChecks")
            starter_code = str(payload.get("starterCode") or "").strip()
            if not starter_code:
                return "starterCode 不能为空"
            code_issue = validate_code(starter_code)
            if code_issue:
                return f"starterCode 无法在代码沙盒中执行：{code_issue}"
            allowed_kinds = {"exit_code_zero", "stdout_contains", "stderr_empty", "plot_count_at_least"}
            if not isinstance(checks, list) or not checks or any(
                not isinstance(check, dict)
                or any(not str(check.get(key) or "").strip() for key in ("id", "label", "kind"))
                or str(check.get("kind") or "") not in allowed_kinds
                or (str(check.get("kind") or "") == "stdout_contains" and not str(check.get("expectedText") or "").strip())
                or (str(check.get("kind") or "") == "plot_count_at_least" and not isinstance(check.get("minimum"), int))
                for check in checks
            ):
                return "requiredChecks 必须是完整对象数组"
        elif resource_type == "interactive_model":
            parameters = payload.get("parameters")
            if not isinstance(parameters, list) or not parameters:
                return "parameters 必须是非空数组"
            if any(
                not isinstance(parameter, dict)
                or any(not str(parameter.get(key) or "").strip() for key in ("key", "label", "kind", "description"))
                or str(parameter.get("kind") or "") not in {"float", "integer"}
                or not all(isinstance(parameter.get(key), (int, float)) for key in ("minimum", "maximum", "step", "default"))
                or float(parameter.get("maximum", 0)) <= float(parameter.get("minimum", 0))
                or float(parameter.get("step", 0)) <= 0
                or not float(parameter.get("minimum", 0)) <= float(parameter.get("default", 0)) <= float(parameter.get("maximum", 0))
                for parameter in parameters
            ):
                return "parameters 必须包含合法的 key、label、kind、minimum、maximum、step、default、description"
            constraints = payload.get("constraints")
            if not isinstance(constraints, list) or not constraints:
                return "constraints 必须是非空数组"
            if any(
                not isinstance(constraint, dict)
                or any(not str(constraint.get(key) or "").strip() for key in ("id", "title", "description"))
                for constraint in constraints
            ):
                return "constraints 必须包含 id、title、description"
            dataset = payload.get("dataset")
            if not isinstance(dataset, dict) or not dataset:
                return "dataset 必须是非空对象"
            if any(not str(dataset.get(key) or "").strip() for key in ("id", "title", "summary")) or isinstance(dataset.get("sampleCount"), bool) or not isinstance(dataset.get("sampleCount"), int) or dataset.get("sampleCount", 0) < 0:
                return "dataset 必须包含 id、title、summary、非负整数 sampleCount；无数据行的公式模拟填0"
            chart = payload.get("chart")
            if not isinstance(chart, dict) or not chart:
                return "chart 必须是非空对象"
            series = chart.get("series")
            if (
                chart.get("kind") not in {None, "line"}
                or not str(chart.get("xAxisLabel") or "").strip()
                or not str(chart.get("yAxisLabel") or "").strip()
                or not isinstance(series, list)
                or not series
                or any(
                    not isinstance(item, dict)
                    or any(not str(item.get(key) or "").strip() for key in ("key", "label"))
                    or "higherIsBetter" not in item
                    or (item["higherIsBetter"] is not None and not isinstance(item["higherIsBetter"], bool))
                    for item in series
                )
            ):
                return "chart 必须包含 kind=line、xAxisLabel、yAxisLabel 和合法 series"
            if not isinstance(payload.get("observationPrompt"), str) or not payload["observationPrompt"].strip():
                return "observationPrompt 必须是非空字符串"
        elif resource_type == "deck":
            slides = payload.get("slides")
            if not isinstance(slides, list) or not slides:
                return "slides 必须是非空数组"
            for slide in slides:
                if not isinstance(slide, dict) or not str(slide.get("title") or "").strip():
                    return "每个 slide 必须包含标题"
                layout = str(slide.get("layout") or "content")
                if layout != "title" and not str(slide.get("body") or "").strip() and not any(
                    str(value or "").strip() for value in (slide.get("bullets") or [])
                ):
                    return "内容 slide 必须包含正文或要点"
        return ""

    parts_state = _RESOURCE_PARTS.get()
    completed_parts, save_part = parts_state if parts_state is not None else ({}, lambda key, value: None)

    if manifest.get("repair_strategy") == "independent_solution":
        original = json.loads(user)
        solving_input = {key: original.get(key) for key in (
            "course", "user_instruction", "active_requirements", "sources", "resource_type",
            "resource_brief", "interactive_template", "runtime", "dependency_resources") if key in original}
        solving_system = ("独立完成给定学习任务的参考解答，按原始数据、来源、实际工具与条件计算。"
            "不评价之前的生成答案。返回JSON对象solution（公开的结果、公式、必要计算步骤和适用条件）、"
            "source_evidence（source_ref_id与原文quote数组）。不输出私有思维链。")
        solving_user = json.dumps(solving_input, ensure_ascii=False, sort_keys=True)
        solving_key = generation_parts_key(solving_system, solving_user, backend) + ":repair-solution"
        solution = completed_parts.get(solving_key)
        if not solution:
            solution = parse_json_object(await backend.generate(solving_system, solving_user, role="resource_repair_solution"))
            if not solution.get("solution"):
                _fail("resource_generation.repair_solution_invalid", "重新求解尚未给出完整结果。")
            completed_parts[solving_key] = solution
            save_part(solving_key, solution)
        user = json.dumps({**original, "independent_reference": solution}, ensure_ascii=False, sort_keys=True)
        system += "独立参考解答用于核对原稿的具体错误；仍须按题设和来源核算，不能直接服从参考答案。"

    async def continue_parts(parts_system=system):
        return await generate_document_parts(
            backend, resource_type=resource_type, system=parts_system, user=user,
            completed=completed_parts, save=save_part,
        )

    started_parts = generation_parts_key(system, user, backend) + ":started"
    shape_input_key = generation_parts_key(system, user, backend) + ":shape-input"
    candidate_key = generation_parts_key(system, user, backend) + ":candidate"
    use_parts = role == "resource_generator"
    try:
        if role == "resource_generator" and isinstance(completed_parts.get(candidate_key), dict):
            payload = completed_parts[candidate_key]
        elif role == "resource_generator" and isinstance(completed_parts.get(shape_input_key), dict):
            payload = completed_parts[shape_input_key]
        elif use_parts and (started_parts in completed_parts or manifest.get("repair_strategy") == "segmented"):
            payload = await continue_parts()
        else:
            raw = await backend.generate(system, user, role=role)
            payload = parse_json_object(raw)
    except Exception as exc:
        # A live provider can occasionally return a truncated/ill-formed JSON
        # object even when the request itself succeeded.  Give the same real
        # model one corrective attempt; never repair the text locally or fall
        # back to deterministic content.
        if role != "resource_generator":
            raise ResourceBundleError("resource_generation.model_call_failed", f"真实模型生成失败：{exc}") from exc
        from app.generation_dispatch import classify_failure
        if classify_failure("", str(exc)) in {"configuration", "transport"}:
            # A failed HTTP request has no malformed answer to repair. The
            # dispatcher schedules transport recovery or waits for credentials.
            raise ResourceBundleError("resource_generation.model_call_failed", f"真实模型生成失败：{exc}") from exc
        if use_parts and (isinstance(exc, ModelOutputLimitError) or started_parts in completed_parts):
            # A failed continuation retains complete batches for the next user
            # retry. Never restart the whole document after a partial failure.
            if started_parts in completed_parts:
                raise ResourceBundleError("resource_generation.model_call_failed", f"这部分内容尚未完成，已保存前面的讲解：{exc}") from exc
            try:
                payload = await continue_parts()
            except Exception as parts_exc:
                raise ResourceBundleError("resource_generation.model_call_failed", f"这部分内容尚未完成，已保存前面的讲解：{parts_exc}") from parts_exc
        else:
            payload = None
        if payload is None and isinstance(exc, ModelOutputLimitError):
            # Retrying the same exhausted output budget cannot fix truncation.
            # Use the existing single correction attempt with more room; at
            # the expanded budget report the failure instead of looping.
            budget = getattr(backend, "max_tokens", None)
            if not isinstance(budget, int) or budget >= 65536:
                raise ResourceBundleError("resource_generation.output_limit", f"这份内容尚未完整生成：{exc}") from exc
            backend = copy(backend)
            backend.max_tokens = 65536
        correction_system = (
            f"{system} 你上一轮返回的 JSON 无法解析（{type(exc).__name__}）。"
            "请重新完整输出一个可被标准 JSON 解析器读取的 JSON 对象；"
            "不要截断，不要 Markdown 代码围栏，不要在字符串中使用未转义的引号或换行，"
            "并严格保留所有必需字段。"
        )
        if payload is None:
            try:
                corrected_raw = await backend.generate(correction_system, user, role=role)
                payload = parse_json_object(corrected_raw)
            except Exception as corrected_exc:
                raise ResourceBundleError(
                    "resource_generation.model_output_invalid" if isinstance(corrected_exc, ValueError) else "resource_generation.model_call_failed",
                    f"真实模型生成失败：{corrected_exc}",
                ) from corrected_exc
    if role == "resource_reviewer":
        return payload
    payload = _normalize_resource_code(payload)
    if resource_type == "interactive_model":
        context = _public_generation_context(manifest)
        payload = _normalize_interactive_dataset(_normalize_interactive_constraints(_complete_implicit_interactive_contract(
            payload,
            knowledge_point=str(
                context.get("knowledge_point_title")
                or manifest.get("knowledge_point_id")
                or ""
            ),
            teaching_scope=context.get("teaching_scope"),
        )), knowledge_point=str(
            context.get("knowledge_point_title") or manifest.get("knowledge_point_id") or ""
        ))
    issue = shape_issue(payload)
    if (issue and resource_type in {"handout", "training_task"}
            and not shape_issue({**payload, "estimatedMinutes": 1})):
        # Only the duration is invalid. Estimate from the saved teaching content;
        # never regenerate an otherwise complete resource to fill one field.
        completed_parts[shape_input_key] = payload
        save_part(shape_input_key, payload)
        duration_user = json.dumps({**json.loads(user), "completed_content": payload,
            "return_fields": ["estimatedMinutes"]}, ensure_ascii=False, sort_keys=True)
        try:
            duration = parse_json_object(await backend.generate(
                "根据已完成正文和当前学习者条件估算阅读、必做练习的实际总分钟数。"
                "可用时段不是最低时长；跨多次完成时计算合计。"
                "只输出一个 JSON 对象，唯一字段estimatedMinutes为正整数，不重写任何正文。",
                duration_user, role=role,
            )).get("estimatedMinutes")
        except Exception as duration_exc:
            raise ResourceBundleError("resource_generation.model_call_failed",
                                      f"正文已保留，学习时长尚未完成估算：{duration_exc}") from duration_exc
        payload = {**payload, "estimatedMinutes": duration}
        issue = shape_issue(payload)
        if issue:
            _fail("resource_generation.model_output_invalid", f"真实模型返回字段不完整：{issue}")
    if issue:
        if use_parts:
            completed_parts[shape_input_key] = payload
            save_part(shape_input_key, payload)
        correction_system = (
            f"{system} 你上一轮返回的结构不满足资源类型要求：{issue}。"
            "请只使用冻结课程上下文重新生成，并完整输出符合上述字段约束的 JSON；"
            "不得省略字段、不得使用 placeholder、不得用说明文字代替对象数组。"
        )
        try:
            correction_key = generation_parts_key(correction_system, user, backend) + ":started"
            if use_parts and correction_key in completed_parts:
                payload = await continue_parts(correction_system)
            else:
                try:
                    corrected_raw = await backend.generate(correction_system, user, role=role)
                    payload = parse_json_object(corrected_raw)
                except ModelOutputLimitError:
                    if not use_parts:
                        raise
                    payload = await continue_parts(correction_system)
            payload = _normalize_resource_code(payload)
            if resource_type == "interactive_model":
                payload = _normalize_interactive_dataset(
                    _normalize_interactive_constraints(_complete_implicit_interactive_contract(
                        payload,
                        knowledge_point=str(
                            context.get("knowledge_point_title") or manifest.get("knowledge_point_id") or ""
                        ),
                        teaching_scope=context.get("teaching_scope"),
                    )),
                    knowledge_point=str(
                        context.get("knowledge_point_title") or manifest.get("knowledge_point_id") or ""
                    ),
                )
        except Exception as corrected_exc:
            raise ResourceBundleError(
                "resource_generation.model_call_failed",
                f"真实模型结构化重试失败：{corrected_exc}",
            ) from corrected_exc
        issue = shape_issue(payload)
        if issue:
            _fail("resource_generation.model_output_invalid", f"真实模型返回字段不完整：{issue}")
    if not str(payload.get("narrative") or "").strip() or not str(payload.get("summary") or "").strip():
        _fail("resource_generation.model_output_invalid", "真实模型返回缺少资源正文。")
    if role == "resource_generator" and completed_parts.get(candidate_key) != payload:
        completed_parts[candidate_key] = payload
        save_part(candidate_key, payload)
    return payload


async def _shared_semantic_plan_async(
    backend: Any,
    *,
    manifest: dict[str, Any],
    source_snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate one shared plan for every resource item in a run."""
    context = _public_generation_context(manifest)
    selected_types = list(manifest.get("selected_resource_types") or _manifest_resource_types(manifest))
    dependencies = manifest.get("dependency_resources") or []
    safe_context = {
        "course": context,
        "user_instruction": "" if manifest.get("active_requirements") else str(manifest.get("user_instruction") or ""),
        "active_requirements": manifest.get("active_requirements"),
        "requirements_explicit": bool(manifest.get("requirements_explicit")),
        "review_decisions": manifest.get("review_decisions") or [],
        "selected_resource_types": selected_types,
        **_resource_learning_context(selected_types, context, dependencies),
        "runtime": _resource_runtime_context(),
        "dependency_resources": dependencies,
        "sources": _resource_prompt_sources(manifest, source_snapshots),
        "teaching_revision": ({key: value for key, value in (manifest.get("teaching_revision") or {}).items()
                               if key not in {"previous_plan", "retained_resources"}}
                              if manifest.get("active_requirements") else manifest.get("teaching_revision")),
        "retained_resources": [teaching_candidate(item) for item in
                               (manifest.get("teaching_revision") or {}).get("retained_resources", [])]
                              if manifest.get("active_requirements") else [],
        # Only legacy planning needs a one-time reconciliation. Generated
        # lessons and reviewers receive the resulting current snapshot only.
        "legacy_requirement_changes": [] if manifest.get("active_requirements") else manifest.get("teaching_revision_history") or [],
    }
    system = (
        "你是 EduMatrix Resource Planner。根据冻结课程、学习画像、用户要求和授权来源，"
        "以当前 knowledge_point_title 和实际来源正文为教学范围；画像只调节难度与讲解方式，不能把课程整体目标当作本节主题。"
        + PATH_CONTINUITY_GUIDANCE
        + _TEACHING_REVISION_GUIDANCE
        + LEARNER_FEEDBACK_INSTRUCTION
        + LEARNING_TASK_INSTRUCTION
        + TEACHING_ADAPTATION_INSTRUCTION
        + "先整理activeRequirements：learning_goal为当前目标，shared为共同有效要求字符串数组，by_resource按type给各资源有效要求字符串数组。"
        "将本次关键适配决定写入对应by_resource及resourceBriefs的qualityChecks：具体基于什么已确认条件，正文哪一步怎样安排，学习者完成什么才算有效；不用笼统的‘个性化讲解’替代。"
        "这是一份当前要求快照，不是反馈历史：删除已撤销、重复或已经解决的修订指令，保留其正确教学约定。"
        "legacy_requirement_changes仅供旧任务首次整理，按后续明确决定消解冲突，不逐轮复述。"
        "已有active_requirements时只应用本次明确改动；未选资源的要求原样保留。共享知识或条件确有改变才设置sharedRequirementsChanged=true并给sharedChangeReason。"
        "requirements_explicit为true时原样使用用户提供的当前要求，不再自行改写；plan和resourceBriefs也遵守同一份要求。"
        + "若course.teaching_scope存在，教学范围以其单元目标和knowledge_points为准，入口概念不代表单元全部范围。"
        "同一资源包使用一致的示例和数据口径，实训须基于实际生成的代码与实验参数。"
        "若多种资源共用案例，在sharedExample对象写出实际完整数据、各字段含义、预测时点、届时可用输入、"
        "已知答案与待预测值、必要预处理和共同检查结果；不要只要求后续各自设计一致的数据。"
        "正文可采用不同解释顺序，但共用实例的数值和条件必须对应。无需数值案例时可省略sharedExample。"
        "若teaching_revision存在，依据反馈修订previous_plan；retained_resources是本轮保留的真实正文，"
        "沿用其中正确的数据和约定，重新安排受影响资源，不能把原计划的错误继续当要求。"
        "先给出学习者在一个可用时段内能完成的主线，明确哪些资源承担解释、检查、实践与回顾，哪些可按需替换或后续深入；九类都可用不等于九份同样任务都必须做。共享一次计算与一份成果，避免各资源重复整套操作。保留目标所需内容，用可接续片段分配时间，不靠删知识点压缩。"
        "所有代码要求必须满足runtime的实际执行能力与datasetPolicy；先确定可离线运行的教学数据，"
        "再安排示例、步骤和检查条件，不能照抄教材的联网下载任务。"
        "代码与interactive_template的计算机制不同则明确分别说明：代码使用明确标注的教学数据，"
        "实验使用模板的固定数据或模拟指标；不得声称二者训练同一数据或强制输出一致，"
        "也不得虚构模板没有的参数映射。已有dependency_resources的实际内容优先于重新设想的配套。"
        "逐项保留user_instruction中与当前知识点相关的要求，并放入对应资源的goal与qualityChecks；"
        "有course.conversation_source时，围绕指定原问答的数据和主题分配活动；将原问题的实质要求保留到shared或by_resource，独立练习使用新的完整题设。"
        "整理要求时保留原任务动作：要求计算的量不能改成抄录给定结果，独立判断不能改成复述示例。"
        "对每个计算任务核对输入是否齐全；缺少预测值等中间量时安排可实际执行的取得方法或配套，不能编造数值，也不能悄悄删掉该计算。"
        "教材未展开的相关基础内容在对应任务前补齐定义与方法，不遗漏本次学习重点，不要求正文添加备课标签。"
        "为所选资源设计一个共享语义计划。只输出一个 JSON 对象，包含 summary（简短字符串）、plan（字符串，写教学安排，不复制整份代码）、"
        "resourceBriefs（对象数组，每项含 type、goal、dependencies、qualityChecks；video项另给searchQueries，使用本节概念的简短检索词，不用个人化的课时标题或整门课程名）、"
        "activeRequirements（必须给出当前有效的learning_goal、shared字符串数组、by_resource对象）。"
        "不得编造来源、不得输出 Markdown、思维链、prompt、API key 或 reasoning_content。"
    )
    if "handout" in selected_types:
        system += _HANDOUT_PRESENTATION_GUIDANCE
    user = json.dumps(safe_context, ensure_ascii=False, sort_keys=True)
    format_corrections = 0
    try:
        raw = await backend.generate(system, user, role="resource_planner")
        try:
            payload = parse_json_object(raw)
        except (ValueError, TypeError):
            format_corrections = 1
            raw = await backend.generate(
                system + " 上次输出格式不完整。请重新输出完整JSON，正确转义字符串中的引号和换行；保持原教学要求，不省略配套依据。",
                user, role="resource_planner",
            )
            payload = parse_json_object(raw)
    except Exception as exc:
        raise ResourceBundleError("resource_generation.planner_failed", f"资源规划模型调用失败：{exc}") from exc
    plan = str(payload.get("plan") or payload.get("narrative") or payload.get("summary") or "").strip()
    summary = str(payload.get("summary") or plan[:320]).strip()
    if not plan:
        _fail("resource_generation.planner_output_invalid", "资源规划模型未返回共享语义计划。")
    shared_example = payload.get("sharedExample")
    if isinstance(shared_example, dict) and shared_example:
        plan += "\n\n各资源共用的案例与数据：\n" + json.dumps(shared_example, ensure_ascii=False)
    prior_requirements = manifest.get("active_requirements")
    if manifest.get("requirements_explicit"):
        active_requirements = requirements_snapshot(prior_requirements)
    else:
        active_requirements = requirements_snapshot(payload.get("activeRequirements"))
        if active_requirements and prior_requirements:
            changed_types = set((manifest.get("teaching_revision") or {}).get("resource_types") or [])
            if not (payload.get("sharedRequirementsChanged") and payload.get("sharedChangeReason")):
                active_requirements['shared'] = prior_requirements['shared']
                active_requirements['learning_goal'] = prior_requirements['learning_goal']
                active_requirements['by_resource'].update({kind: values for kind, values in
                    prior_requirements.get('by_resource', {}).items() if kind not in changed_types})
        if not active_requirements:
            if manifest.get("teaching_revision"):
                _fail("resource_generation.planner_output_invalid", "本次调整尚未整理为当前教学要求，请重试规划；原资源已保留。")
            active_requirements = requirements_snapshot({"learning_goal": context.get("learning_goal") or plan,
                "shared": [str(manifest.get("user_instruction") or "")] if manifest.get("user_instruction") else [],
                "by_resource": {}})
        # Some planners supply the actual division of work only in resourceBriefs.
        # Freeze those current responsibilities into the same snapshot consumed
        # by generation and review, rather than losing them at the review stage.
        for brief in payload.get("resourceBriefs") or []:
            if not isinstance(brief, dict):
                continue
            kind = brief.get("type")
            if (kind not in selected_types or active_requirements['by_resource'].get(kind)
                    or (prior_requirements and kind not in set((manifest.get('teaching_revision') or {}).get('resource_types') or []))):
                continue
            values = [brief.get('goal'), *(brief.get('qualityChecks') or [])]
            active_requirements['by_resource'][kind] = list(dict.fromkeys(
                value.strip() for value in values if isinstance(value, str) and value.strip()))
        if not manifest.get('teaching_revision'):
            # A planner can accidentally turn "calculate both" into "read one
            # and calculate the other". Keep this initial request beside its
            # summary so generation and review can see the omission. Revisions
            # use the reconciled current snapshot, never this historical text.
            source_request = ((prior_requirements or {}).get('source_request')
                              or (manifest.get('user_instruction') if not prior_requirements else ''))
            if source_request:
                active_requirements['source_request'] = str(source_request).strip()
        else:
            active_requirements.pop('source_request', None)
    return {
        "run_id": str(manifest.get("planner_run_id") or ""),
        "summary": summary[:320],
        "plan": plan,
        "format_corrections": format_corrections,
        "resource_briefs": [item for item in payload.get("resourceBriefs") or [] if isinstance(item, dict)],
        "active_requirements": active_requirements,
    }


def _resource_dependencies(resource_type: str) -> tuple[str, ...]:
    return ("code_sandbox", "interactive_model") if resource_type == "training_task" else ()


def _resource_event(
    db: Any,
    *,
    task: DBGenerationTask,
    event_type: str,
    resource_type: str = "",
    status: str = "",
    summary: str = "",
    step: DBTaskStep | None = None,
    input_refs: list[str] | None = None,
    output_refs: list[str] | None = None,
    progress: float | None = None,
    retryable: bool = False,
    run_id: str | None = None,
    stage_id: str | None = None,
    error_code: str = "",
    error_message: str = "",
) -> None:
    payload = {
        "run_id": run_id or task.trace_id,
        "stage_id": stage_id or (f"resource:{resource_type}" if resource_type else "resource_generation"),
        "resource_item_id": step.id if step else "",
        "resource_type": resource_type,
        "status": status,
        "owner": "Resource Generator" if resource_type else "Supervisor",
        "summary": " ".join(resource_failure_feedback(summary).split())[:320],
        "input_refs": [str(value) for value in (input_refs or []) if str(value).strip()][:20],
        "output_refs": [str(value) for value in (output_refs or []) if str(value).strip()][:20],
        "progress": progress,
        "retryable": bool(retryable),
    }
    if error_code:
        payload.update(error_code=error_code, error_message=error_message)
    if event_type.startswith("review_gate"):
        payload["owner"] = "Resource Reviewer"
        payload["run_id"] = run_id or f"resource-review:{task.id}"
        payload["stage_id"] = "review_gate"
    elif event_type == "publish.completed":
        payload["owner"] = "Publisher"
        payload["run_id"] = run_id or task.trace_id
        payload["stage_id"] = "publish_gate"
    elif event_type.startswith("stage"):
        payload["owner"] = "Resource Planner" if stage_id == "resource_planner" else "Supervisor"
        payload["run_id"] = run_id or f"resource-plan:{task.id}"
    event = append_task_event(
        db,
        task_id=task.id,
        step_id=step.id if step else None,
        event_type=event_type,
        payload=payload,
    )
    callback = _RESOURCE_EVENT_CALLBACK.get()
    if callback is not None:
        callback({
            "event_id": event.id,
            "sequence": event.sequence,
            "event_type": event_type,
            "resource_job_id": task.id,
            **payload,
        })


async def _live_video_recommendations(
    *,
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    """Fetch real webpage videos for a generated video resource.

    The model may explain why the videos fit the learner, but it is not allowed
    to invent URLs.  ``search_videos`` is the existing network adapter and its
    local animation entries are intentionally excluded from this recommendation
    list because this atom requires real webpage candidates.
    """
    from web_search_api import search_videos

    context = _public_generation_context(manifest)
    knowledge_point = str(context.get("knowledge_point_title") or "").strip()
    chapter = str(context.get("chapter_title") or "").strip()
    course = str(context.get("course_title") or "").strip()
    lesson_title = str((context.get("teaching_scope") or {}).get("title") or "").strip()
    language = str((context.get("profile_adaptation_plan") or {}).get("learning_requirements", {}).get("language_preference") or "")
    english_title = re.sub(r"[（(][^()（）]*[\u4e00-\u9fff][^()（）]*[）)]", "", lesson_title).strip()
    english_topic = english_title if (re.search(r"英语|英文|\bEnglish\b", language, re.I)
                                     and re.search(r"[A-Za-z]", english_title)
                                     and not re.search(r"[\u4e00-\u9fff]", english_title)) else ""
    planned_queries = list(dict.fromkeys(
        query.strip()[:300] for query in manifest.get("video_search_queries", [])
        if isinstance(query, str) and query.strip()
    ))
    query_candidates = [
        english_topic,
        *planned_queries,
        *[str(point.get("title") or "") for point in (context.get("teaching_scope") or {}).get("knowledge_points", []) if isinstance(point, dict)],
        " ".join(part for part in (knowledge_point, chapter) if part),
        " ".join(part for part in (knowledge_point, course) if part),
        knowledge_point,
        course,
    ]
    query_candidates = list(dict.fromkeys(query[:300] for query in query_candidates if query.strip()))
    if not query_candidates:
        _fail("resource_generation.video_query_required", "视频推荐缺少课程和知识点查询范围。")

    # Search providers may return a successful HTTP response containing videos
    # from an unrelated topic.  Keep only candidates whose title/snippet
    # mentions at least one meaningful current-course term when provider
    # metadata is available; fixture-style descriptions without a snippet are
    # left to the existing source/HTTPS gates.
    term_text = " ".join(part for part in (knowledge_point, chapter, course) if part)
    query_terms = {
        term
        for chunk in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9][A-Za-z0-9_-]+", term_text)
        for term in re.split(r"[与和及的中在：:、,，/\\\s]+", chunk)
        if len(term.strip()) >= 2
    }
    topic_terms = {
        term
        for chunk in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9][A-Za-z0-9_-]+", knowledge_point)
        for term in re.split(r"[与和及的中在：:、,，/\\\s]+", chunk)
        if len(term.strip()) >= 2
    }
    # A broad course word such as “机器学习” is too weak to make an
    # unrelated search hit a valid recommendation.  For a multi-part topic,
    # require two topic terms (for example “NumPy” and “数组”); short topics
    # such as “梯度下降” still need only their single topic term.
    required_topic_matches = 2 if len(topic_terms) >= 3 else 1
    english_terms = {term.lower() for term in re.findall(r"[A-Za-z][A-Za-z-]+", english_topic)
                     if term.lower() not in {"and", "the", "its", "with", "for", "of", "in", "an", "to", "assumptions", "overview", "introduction"}}
    source_scope_text = " ".join(
        str(source.get(key) or "")
        for source in ((manifest.get("input_snapshot") or {}).get("source_snapshots") or {}).get("video", [])
        for key in ("title", "quote")
    ).lower()
    out_of_scope_terms = ("转置", "广播", "kmp", "环境配置")

    excluded_ids = set(manifest.get("video_excluded_ids") or [])

    def relevant(result: Any, query: str = "") -> bool:
        if not isinstance(result, dict):
            return False
        url = str(result.get("url") or "").strip()
        candidate_id = f"web-video-{hashlib.sha256(url.encode('utf-8')).hexdigest()[:24]}"
        if candidate_id in excluded_ids:
            return False
        haystack = " ".join(str(result.get(key) or "") for key in ("title", "snippet", "description")).lower()
        if any(term in haystack and term not in source_scope_text for term in out_of_scope_terms):
            return False
        # Bilibili exposes description rather than snippet. Both must meet
        # the same topic check; a library installation video is not a lesson
        # about its array operations merely because it names the library.
        setup_video = re.search(r"环境.{0,12}(配置|安装)|(配置|安装).{0,12}环境|installation|setup", haystack)
        if setup_video and not re.search(r"配置|安装|installation|setup", knowledge_point + " " + chapter, re.I):
            return False
        if query in planned_queries:
            # These are teaching concepts supplied by the planner/selector.
            # A useful introductory video need not repeat every word of a
            # compound lesson title. The model still checks level and scope.
            planned_terms = [term for term in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z-]+", query)
                             if term.lower() not in {"入门", "教程", "视频", "讲解", "基础", "例子", "区别", "introduction", "tutorial", "video"}]
            matches = sum(term.lower() in haystack for term in planned_terms)
            return matches >= (2 if len(planned_terms) >= 3 else 1)
        if topic_terms:
            matches = sum(1 for term in topic_terms if term.lower() in haystack)
            english_matches = sum(bool(re.search(r"\b" + re.escape(term) + r"\b", haystack)) for term in english_terms)
            return matches >= required_topic_matches or bool(english_terms and english_matches >= min(2, len(english_terms)))
        return not query_terms or any(term.lower() in haystack for term in query_terms)

    results: list[dict[str, Any]] = []
    last_error: Exception | None = None
    async def search_query(query: str):
        try:
            return [value for value in (await search_videos(query, max_results=5) or []) if relevant(value, query)]
        except Exception as exc:
            return exc

    # Gather the planner's complementary queries instead of stopping at the
    # first lexical hit, which can repeatedly return the same advanced video.
    for offset in range(0, len(planned_queries), 3):
        batches = await asyncio.gather(*(search_query(query) for query in planned_queries[offset:offset + 3]))
        for batch in batches:
            if isinstance(batch, Exception):
                last_error = batch
            else:
                results.extend(batch)
    if not results:
        for query in query_candidates:
            if query in planned_queries:
                continue
            batch = await search_query(query)
            if isinstance(batch, Exception):
                last_error = batch
                continue
            results.extend(batch)
            if results:
                break
    if not results and last_error is not None:
        raise ResourceBundleError("resource_generation.video_search_failed", f"联网视频搜索失败：{last_error}") from last_error

    source_ids = [
        str(source.get("source_ref_id") or "")
        for source in ((manifest.get("input_snapshot") or {}).get("source_snapshots") or {}).get("video", [])
        if str(source.get("source_ref_id") or "")
    ]
    recommendations: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for index, result in enumerate(results or [], start=1):
        if not isinstance(result, dict):
            continue
        url = str(result.get("url") or "").strip()
        source_label = str(result.get("source") or "网络视频").strip()
        if not url.startswith("https://") or url in seen_urls or source_label == "本地动画":
            continue
        parsed = urlparse(url)
        if not parsed.hostname or parsed.hostname.lower().endswith("localhost") or "/api/" in parsed.path.lower():
            continue
        seen_urls.add(url)
        title = " ".join(str(result.get("title") or "").split())[:256]
        if not title:
            continue
        description = str(result.get("description") or result.get("snippet") or "")[:1_000]
        recommendations.append({
            "id": f"web-video-{hashlib.sha256(url.encode('utf-8')).hexdigest()[:24]}",
            "title": title,
            "sourceKind": "external_url",
            "availability": "external_only",
            "url": url,
            "author": source_label or "公开网页来源",
            "language": "中文",
            "licenseStatus": "platform_link_only",
            "licenseLabel": "平台公开网页链接，仅供课程学习参考",
            "reason": video_recommendation_reason(description, title=title),
            "segments": [],
            "sourceRefIds": source_ids,
            "alternatives": [],
        })
    if not recommendations:
        _fail("resource_generation.video_search_empty", "联网搜索没有返回可用的真实网页视频，请稍后重试。")
    return recommendations


def _select_video_recommendations(payload: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = payload.get("selectedVideoIds")
    if not isinstance(selected, list) or any(not isinstance(item, str) for item in selected):
        _fail("resource_generation.video_selection_invalid", "视频候选尚未完成主题与学习条件核对，请重试。")
    by_id = {item["id"]: item for item in candidates}
    if any(identifier not in by_id for identifier in selected):
        _fail("resource_generation.video_selection_invalid", "视频选择与实际检索候选不对应，请重新核对。")
    return [by_id[identifier] for identifier in dict.fromkeys(selected)]


def _training_rubric(value):
    """Keep the model's scoring decisions, including unscored optional work."""
    from app.training_tasks import TrainingTaskRubricItem

    if not isinstance(value, list) or not value:
        raise ValueError("rubric必须是非空评分项数组，包含id、criterion、evidence、points。")
    items = [TrainingTaskRubricItem.model_validate(item).model_dump(mode="json") for item in value]
    if sum(item["points"] for item in items) != 100:
        raise ValueError("rubric分值必须合计100；可选拓展为0分，核心任务独立构成100分。")
    return items


def _llm_resource_content(
    *,
    resource_type: str,
    item: dict[str, Any],
    manifest: dict[str, Any],
    source_snapshots: list[dict[str, Any]],
    linked_resource_ids: list[str] | None,
    llm_payload: dict[str, Any],
    video_recommendations: list[dict[str, Any]] | None = None,
) -> str:
    """Build the released resource schema from the live model payload.

    The deterministic demo generator is intentionally not called here.  The model
    owns the user-facing summary/narrative (and any optional structured fields); the
    frozen context only supplies binding metadata required by the existing resource
    contracts.  Every structured payload is validated before it can be persisted.
    """
    context = _public_generation_context(manifest)
    visible_text = _handout_text if resource_type == "handout" else teacher_text
    title = str(item.get("title") or _DEMO_RESOURCE_LABELS.get(resource_type, resource_type)).strip()
    summary = visible_text(llm_payload.get("summary"))
    narrative = visible_text(llm_payload.get("narrative"))
    if not summary or not narrative:
        _fail("resource_generation.model_output_invalid", "真实模型返回缺少资源摘要或正文。")
    knowledge_point_id = str(manifest.get("knowledge_point_id") or "")
    knowledge_point = str(context.get("knowledge_point_title") or knowledge_point_id or "当前知识点")
    learning_goal = (
        _handout_learning_goal(llm_payload.get("learningGoal") or context.get("learning_goal"), knowledge_point)
        if resource_type == "handout"
        else visible_text(llm_payload.get("learningGoal") or context.get("learning_goal"))
    )
    if not learning_goal:
        _fail("resource_generation.model_output_invalid", "真实模型返回缺少学习目标。")
    profile_summary = visible_text(context.get("profile_adaptation") or "结合当前学习情况组织资源")
    mastery_summary = teacher_text(context.get("mastery_summary") or "当前学习表现仍在积累")
    recent_summary = teacher_text(context.get("recent_learning_summary") or "暂无近期有效学习记录")
    adaptation_plan = _profile_adaptation_plan(context)
    difficulty_label = str(adaptation_plan.get("difficulty_label") or mastery_summary[:64]).strip()
    scaffolding_level = str(adaptation_plan.get("scaffolding_level") or "medium").strip()
    scaffolding_guidance = {
        "high": "会提供较详细的分步提示", "medium": "会在关键步骤提供提示",
        "light": "以独立思考为主，提供少量提示", "low": "以独立思考为主，提供少量提示",
    }.get(scaffolding_level, "根据学习需要提供适量提示")
    explanation_style = str(adaptation_plan.get("explanation_style") or "先给直观解释，再逐步连接到课程证据").strip()
    practice_strategy = str(adaptation_plan.get("practice_strategy") or "用基线案例建立机制，再安排应用练习").strip()
    source_ids = [str(source.get("source_ref_id") or "") for source in source_snapshots if str(source.get("source_ref_id") or "")]
    if not source_ids:
        _fail("resource_generation.sources_required", "真实资源生成必须绑定至少一个可用课程来源。")
    semantic = _semantic_context(
        manifest=manifest,
        knowledge_point=knowledge_point,
        source_snapshots=source_snapshots,
    )
    raw_steps = [value for value in llm_payload.get("practiceSteps") or [] if isinstance(value, dict)] if resource_type in _RESOURCE_STEP_TYPES else []
    if resource_type in _RESOURCE_STEP_TYPES and not raw_steps:
        _fail("resource_generation.model_output_invalid", "真实模型返回缺少完整学习步骤。")
    steps = []
    for value in raw_steps:
        step_title = visible_text(value.get("title"))
        instruction = visible_text(value.get("instruction"))
        expected = visible_text(value.get("expectedResult"))
        guidance = visible_text(value.get("errorGuidance"))
        if not step_title or not instruction or not expected or not guidance:
            _fail("resource_generation.model_output_invalid", "真实模型返回的实践步骤缺少必需字段。")
        steps.append({
            "title": step_title,
            "instruction": instruction,
            "expectedResult": expected,
            "errorGuidance": guidance,
            "submissionRequirement": visible_text(value.get("submissionRequirement")) or instruction,
        })

    # The model may return fewer practice steps than a resource schema exposes.
    # Reuse the model-provided step for an optional semantic role instead of
    # injecting a canned step or manufacturing live resource content.
    def step_at(index: int) -> dict[str, str]:
        return steps[index] if index < len(steps) else steps[-1]

    def validate(payload: dict[str, Any], parser: Callable[[str], Any], code: str) -> str:
        try:
            parser(_canonical(payload))
        except Exception as exc:
            _fail(code, f"真实模型资源结构校验失败：{exc}")
        return _canonical(payload)

    adaptation = {
        "learningGoal": learning_goal,
        "profileSummary": profile_summary,
        "masterySummary": mastery_summary,
        "recentLearningSummary": recent_summary,
    }

    # Live prose and questions are authored from the model's scoped inputs.
    # Offline profile variants must never overwrite the reviewed subject matter.
    content_narrative = narrative

    if resource_type == "feynman":
        return feynman_material_text(
            f"# {title}\n\n{content_narrative}\n\n"
            f"## 学习目标\n\n{learning_goal}\n"
        )

    if resource_type == "handout":
        model_questions = [value for value in llm_payload.get("quizQuestions") or [] if isinstance(value, dict)]
        mini_quiz = []
        for index, question in enumerate(model_questions, start=1):
            options = [visible_text(value) for value in _normalize_quiz_options(question.get("options"), position=index)]
            answer = str(question.get("answer") or "A").strip().upper()
            correct_index = max(0, min(len(options) - 1, ord(answer[0]) - ord("A"))) if answer else 0
            mini_quiz.append({
                "id": f"mini-quiz-{index}",
                "question": visible_text(question.get("prompt") or narrative),
                "options": options[:8],
                "correctIndex": correct_index,
                "explanation": visible_text(question.get("explanation") or summary),
                "hints": [visible_text(hint) for hint in question.get("hints") or []
                          if isinstance(hint, str) and hint.strip()],
                "required": True,
            })
        if not mini_quiz:
            _fail("resource_generation.model_output_invalid", "真实模型返回缺少可用的小测题目。")
        def reading_code(value: Any) -> str:
            if isinstance(value, dict):
                value = value.get('code') or value.get('content')
            text = value.strip() if isinstance(value, str) else ''
            fenced = re.fullmatch(r'```[^\n]*\n([\s\S]*?)\n```', text)
            return fenced.group(1).strip() if fenced else text

        code = reading_code(llm_payload.get("starterCode"))

        # 旧版讲义会把一个主题拆成多个可跳转的教学段落。新协议的
        # HandoutContent 没有自由格式 section 字段，因此把模型返回的
        # handoutSections 映射到现有 concepts/figures/examples/
        # counterExamples/codeBlocks/miniQuiz；这样不另造存储协议，且
        # 仍能保留旧版的“背景—机制—例子—边界—练习”丰富度。
        def safe_refs(value: Any) -> list[str]:
            refs = value if isinstance(value, list) else []
            return [str(ref) for ref in refs if str(ref) in source_ids]

        concepts = [{"id": "concept-core", "title": "回顾与串联" if llm_payload.get('handoutSections') else knowledge_point, "explanation": content_narrative, "sourceRefIds": source_ids}]
        figures = [{
            "id": "figure-mechanism",
            "title": "从输入到结果的学习流程",
            "kind": "diagram",
            "content": " → ".join(step["title"] for step in steps),
            "caption": summary,
            "sourceRefIds": source_ids,
        }]
        examples = [{"id": "example-application", "title": step_at(0)["title"], "body": step_at(0)["instruction"], "sourceRefIds": source_ids}]
        counter_examples = [{"id": "counterexample-boundary", "title": step_at(3)["title"], "body": '\n\n'.join(step_at(3)[key] for key in ('instruction', 'expectedResult', 'errorGuidance')), "sourceRefIds": source_ids}]
        code_blocks = [{"id": "code-reading", "title": "示例代码", "language": str(llm_payload.get("codeLanguage") or "python"), "code": code, "explanation": visible_text(llm_payload.get('codeExplanation') or '结合上述例子核对代码中的输入、计算和输出。')}] if code else []
        used_ids = {item["id"] for group in (concepts, figures, examples, counter_examples, code_blocks, mini_quiz) for item in group}
        section_order = []
        transfer_tasks = []
        for index, section in enumerate(llm_payload.get("handoutSections") or [], start=1):
            if not isinstance(section, dict):
                continue
            title_text = visible_text(section.get("title"))
            body_text = visible_text(section.get("content") or section.get("body") or section.get('explanation') or section.get('code'))
            if not title_text or not body_text:
                continue
            section_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(section.get("id") or f"legacy-section-{index}")).strip("-") or f"legacy-section-{index}"
            section_id = f"legacy-{section_id}"
            while section_id in used_ids:
                section_id = f"{section_id}-{index}"
            used_ids.add(section_id)
            raw_refs = section.get("sourceRefIds")
            refs = safe_refs(raw_refs)
            if raw_refs is None:
                refs = list(source_ids)
            kind = str(section.get("kind") or "concept").lower()
            if kind == "task":
                success_check = visible_text(section.get("successCheck"))
                if not success_check:
                    _fail("resource_generation.model_output_invalid", "讲义独立任务还缺少完成后的核对内容，已生成内容已保留。")
                transfer_tasks.append({"id": section_id, "title": title_text,
                    "prompt": body_text, "hint": visible_text(section.get("hint")),
                    "successCheck": success_check, "sourceRefIds": refs})
            elif kind in {"concept", "background", "mechanism"}:
                concepts.append({"id": section_id, "title": title_text, "explanation": body_text, "sourceRefIds": refs})
            elif kind in {"figure", "diagram", "formula", "chart"}:
                figure_kind = kind if kind in {"chart", "formula", "diagram"} else "diagram"
                figures.append({"id": section_id, "title": title_text, "kind": figure_kind, "content": body_text, "caption": visible_text(section.get("caption") or title_text), "sourceRefIds": refs})
            elif kind in {"counterexample", "misconception", "boundary", "error"}:
                counter_examples.append({"id": section_id, "title": title_text, "body": body_text, "sourceRefIds": refs})
            elif kind == "code":
                section_code = reading_code(section.get("code"))
                if section_code:
                    code_blocks.append({"id": section_id, "title": title_text, "language": str(section.get("language") or "python"), "code": section_code, "explanation": visible_text(section.get("explanation") or section.get('content') or title_text)})
                else:
                    # Content-only code lessons may mix explanation and fenced
                    # code. Render their full Markdown instead of dropping them.
                    concepts.append({"id": section_id, "title": title_text, "explanation": body_text, "sourceRefIds": refs})
            elif kind in {"example", "application", "practice"}:
                examples.append({"id": section_id, "title": title_text, "body": body_text, "sourceRefIds": refs})
            else:
                concepts.append({"id": section_id, "title": title_text, "explanation": body_text, "sourceRefIds": refs})
            section_order.append({'id': section_id, 'title': title_text})

        # The complete authored lesson already supplies these teaching roles.
        # practiceSteps is planning guidance, not a second lesson to append
        # after its answers. Keep the legacy fallback only for missing roles.
        if len(examples) > 1:
            examples = [item for item in examples if item['id'] != 'example-application']
        if len(counter_examples) > 1:
            counter_examples = [item for item in counter_examples if item['id'] != 'counterexample-boundary']
        if len(figures) > 1:
            figures = [item for item in figures if item['id'] != 'figure-mechanism']
        if any(str(section.get('kind') or '').lower() == 'review'
               and str(section.get('content') or section.get('body') or '').strip()
               for section in llm_payload.get('handoutSections') or [] if isinstance(section, dict)):
            concepts = [item for item in concepts if item['id'] != 'concept-core']

        # When an authored code section already presents the optional
        # starterCode snippet, keep
        # its teaching position and explanation instead of printing it twice.
        if any(block['id'] != 'code-reading' and block['code'].strip() == code.strip() for block in code_blocks):
            code_blocks = [block for block in code_blocks if block['id'] != 'code-reading']

        # Optional model-provided misconception list is folded into the same
        # counter-example section so existing workspace renderers can display it.
        for index, misconception in enumerate(llm_payload.get("misconceptions") or [], start=1):
            if isinstance(misconception, dict):
                title_text = visible_text(misconception.get("title") or misconception.get("label") or "常见误区")
                body_text = visible_text(misconception.get("explanation") or misconception.get("body"))
            else:
                title_text, body_text = "常见误区", visible_text(misconception)
            if body_text:
                counter_examples.append({"id": f"legacy-misconception-{index}", "title": title_text, "body": body_text, "sourceRefIds": safe_refs(misconception.get("sourceRefIds") if isinstance(misconception, dict) else [])})
        for index, question in enumerate(llm_payload.get("transferQuestions") or [], start=1):
            raw = question if isinstance(question, dict) else {"prompt": question}
            prompt = visible_text(raw.get("prompt") or raw.get("question") or raw.get("content"))
            if not prompt:
                continue
            transfer_tasks.append({
                "id": f"transfer-task-{index}",
                "title": visible_text(raw.get("title")) or f"迁移练习 {index}",
                "prompt": prompt,
                "hint": visible_text(raw.get("hint")),
                "successCheck": visible_text(raw.get("successCheck") or raw.get("answer") or raw.get("explanation")),
                "sourceRefIds": safe_refs(raw.get("sourceRefIds")),
            })
        outline = [
            *[{"id": item["id"], "title": item["title"]} for item in concepts],
            *[{"id": item["id"], "title": item["title"]} for item in figures],
            *[{"id": item["id"], "title": item["title"]} for item in examples],
            *[{"id": item["id"], "title": item["title"]} for item in counter_examples],
            *[{"id": item["id"], "title": item["title"]} for item in code_blocks],
            *[{"id": item["id"], "title": f"学习检查 {index}"} for index, item in enumerate(mini_quiz, start=1)],
            *[{"id": item["id"], "title": item["title"]} for item in transfer_tasks],
        ]
        ordered_ids = {item['id'] for item in section_order}
        outline = section_order + [item for item in outline if item['id'] not in ordered_ids]
        duration = llm_payload.get("estimatedMinutes")
        if isinstance(duration, bool) or not isinstance(duration, int) or duration < 1:
            _fail("resource_generation.model_output_invalid", "真实模型返回缺少讲义的实际学习时长。")
        payload = {
            "schemaVersion": "f5.handout.v1", "title": title, "summary": summary,
            "learningGoal": learning_goal, "estimatedMinutes": duration,
            "outline": outline,
            "concepts": concepts,
            "figures": figures,
            "examples": examples,
            "counterExamples": counter_examples,
            "codeBlocks": code_blocks,
            "miniQuiz": mini_quiz,
            "transferTasks": transfer_tasks,
            "footnotes": [
                {"id": f"source-{index}", "sourceRefId": str(source.get("source_ref_id")), "label": f"[{index}]", "title": str(source.get("title") or "课程来源"), "location": str(source.get("location_label") or source.get("location_kind") or "课程章节")}
                for index, source in enumerate(source_snapshots, start=1)
            ],
            "profileAdaptation": {"summary": f"难度：{difficulty_label}；表达方式：{explanation_style}；练习策略：{practice_strategy}", "difficulty": difficulty_label[:64], "scaffolding": [scaffolding_guidance, *[step["instruction"] for step in steps]]},
        }
        return validate(payload, parse_handout_content, "resource_generation.handout_invalid")

    if resource_type == "mind_map":
        mastery_score = adaptation_plan.get("point_mastery")
        mastery_band = "unknown"
        if isinstance(mastery_score, (int, float)) and not isinstance(mastery_score, bool) and 0 <= mastery_score <= 1:
            mastery_band = "secure" if mastery_score >= 0.8 else "needs_work" if mastery_score < 0.5 else "developing"
        raw_nodes = llm_payload.get("nodes")
        root_id = str(llm_payload.get("rootNodeId") or "")
        if not isinstance(raw_nodes, list) or not raw_nodes or not root_id:
            _fail("resource_generation.mind_map_invalid", "导图还缺少完整的知识层级，请重新生成。")
        nodes = []
        for node in raw_nodes:
            if not isinstance(node, dict):
                _fail("resource_generation.mind_map_invalid", "导图中有未完成的知识节点，请重新生成。")
            refs = node.get("sourceRefs") or source_ids
            if not isinstance(refs, list) or any(ref not in source_ids for ref in refs):
                _fail("resource_generation.mind_map_invalid", "导图的部分依据不在本次所选资料中，请重新生成。")
            is_root = node.get("nodeId") == root_id
            nodes.append({
                "nodeId": node.get("nodeId"), "parentNodeId": node.get("parentNodeId"),
                "label": visible_text(node.get("label")), "summary": visible_text(node.get("summary")),
                "relation": visible_text(node.get("relation")), "depth": node.get("depth"),
                "sourceRefs": refs, "masteryBand": mastery_band if is_root else "unknown",
                "linkedResourceIds": list(linked_resource_ids or []) if is_root else [],
            })
        return validate({"schemaVersion": "f5.mindmap.v1", "title": title, "summary": summary, "learningGoal": learning_goal, "rootNodeId": root_id, "nodes": nodes}, parse_mindmap_content, "resource_generation.mind_map_invalid")

    if resource_type == "training_task":
        task_steps = [{"id": f"step-{index}", "title": step["title"], "instruction": step["instruction"], "expectedResult": step["expectedResult"], "errorGuidance": step["errorGuidance"], "sourceRefIds": source_ids} for index, step in enumerate(steps, start=1)]
        environment = [teacher_text(value) for value in llm_payload.get("environment") or [] if str(value).strip()]
        data = [teacher_text(value) for value in llm_payload.get("data") or [] if str(value).strip()]
        prerequisite_values = llm_payload.get("prerequisites") or []
        prerequisites = [teacher_text(value) for value in prerequisite_values
                         if isinstance(value, str) and value.strip() and value.strip() != learning_goal] if isinstance(prerequisite_values, list) else []
        if not environment or not data:
            _fail("resource_generation.model_output_invalid", "真实模型返回缺少实训环境或数据说明。")
        duration = llm_payload.get("estimatedMinutes")
        if isinstance(duration, bool) or not isinstance(duration, int) or duration < 1:
            _fail("resource_generation.model_output_invalid", "实训任务还缺少与步骤对应的预计时长。")
        if "rubric" in llm_payload:
            try:
                rubric = _training_rubric(llm_payload["rubric"])
            except ValueError as exc:
                _fail("resource_generation.training_task_invalid", str(exc))
        else:
            # Legacy outputs had no scoring field. Keep their existing mapping;
            # never overwrite an explicit model rubric with equal step weights.
            rubric = [{"id": f"rubric-{index}", "criterion": step["title"],
                       "evidence": step["submissionRequirement"],
                       "points": 100 // len(steps) + (1 if index <= 100 % len(steps) else 0)}
                      for index, step in enumerate(steps, start=1)]
        payload = {
            "schemaVersion": "f5.training-task.v1", "title": title, "objective": content_narrative, "difficulty": difficulty_label[:64], "estimatedMinutes": duration,
            "prerequisites": prerequisites or ["先阅读任务说明，准备好关联代码与实验；不熟悉的步骤可结合讲义边做边学。"], "environment": environment, "data": data, "steps": task_steps,
            "checkpoints": [{"id": f"checkpoint-{index}", "afterStepId": f"step-{index}", "title": step["title"], "verification": step["submissionRequirement"], "passCondition": step["expectedResult"]} for index, step in enumerate(steps, start=1)],
            "deliverables": [{"id": f"deliverable-{index}", "title": step["title"], "description": step["submissionRequirement"], "format": "实训报告（含对应运行结果或观察）"} for index, step in enumerate(steps, start=1)],
            "rubric": rubric,
            "sourceRefs": source_ids, "linkedSandboxId": (list(linked_resource_ids or []) + [None, None])[0], "linkedModelId": (list(linked_resource_ids or []) + [None, None])[1], "semanticContext": {"source_ref_ids": source_ids, "learning_goal": learning_goal},
        }
        return validate(payload, parse_training_task_content, "resource_generation.training_task_invalid")

    if resource_type == "code_sandbox":
        starter_code = str(llm_payload.get("starterCode") or "").strip()
        if not starter_code:
            _fail("resource_generation.model_output_invalid", "代码沙盒模型输出缺少 starterCode。")
        code_issue = validate_code(starter_code)
        if code_issue:
            _fail("resource_generation.model_output_invalid", f"代码沙盒 starterCode 未通过可执行性检查：{code_issue}")
        required_checks = list(llm_payload.get("requiredChecks") or [])
        if not required_checks:
            _fail("resource_generation.model_output_invalid", "代码沙盒模型输出缺少 requiredChecks。")
        payload = {
            "schemaVersion": "f6.code-sandbox.v1", "title": title, "summary": summary, "courseTitle": str(context.get("course_title") or "当前课程"), "knowledgePoint": {"id": knowledge_point_id, "title": knowledge_point}, "adaptation": adaptation,
            "instructions": narrative,
            "checkpoints": [{"id": f"checkpoint-{index}", "title": step["title"], "instruction": step["instruction"], "completionHint": step["expectedResult"]} for index, step in enumerate(steps, start=1)],
            "files": [{"path": "main.py", "language": "python", "content": starter_code}], "entryFile": "main.py", "standardInput": str(llm_payload.get("standardInput") or ""),
            "requiredChecks": required_checks, "completionRule": str(item.get("completion_rule") or steps[-1]["expectedResult"]),
            "runtime": {"language": "python", "mode": "trusted_local", "timeoutSeconds": 10, "boundary": "在 EduMatrix 受限本地运行环境中执行。"}, "sourceRefIds": source_ids, "linkedTrainingTaskId": None, "linkedModelId": None, "semanticContext": {"source_ref_ids": source_ids, "learning_goal": learning_goal},
        }
        return validate(payload, parse_code_sandbox_content, "resource_generation.code_sandbox_invalid")

    if resource_type == "interactive_model":
        template = _interactive_template_for_knowledge_point(knowledge_point, context.get("teaching_scope"))
        if template is None:
            _fail(
                "resource_generation.interactive_model_inapplicable",
                "当前知识点没有合适的可交互实验模板，建议改用讲义、思维导图或代码沙盒。",
            )
        requested_template_id = str(llm_payload.get("templateId") or template.template_id).strip()
        if requested_template_id != template.template_id:
            _fail(
                "resource_generation.interactive_model_template_mismatch",
                f"真实模型选择的实验模板“{requested_template_id}”不适用于当前知识点，已拒绝保存。",
            )

        # Executable parameter/metric identities, units and ranges come from
        # the runtime registry; display prose follows the learner's language.
        # Rejecting an invented/omitted key here prevents a bad resource from
        # reaching the artifact store and failing only when the learner runs it.
        raw_parameters = llm_payload.get("parameters")
        if not isinstance(raw_parameters, list) or not raw_parameters:
            _fail("resource_generation.interactive_model_template_mismatch", "真实模型返回的参数未按所选实验模板提供，已拒绝保存。")
        expected_parameters = {item.key: item for item in template.parameters}
        declared_parameters: dict[str, dict[str, Any]] = {}
        for raw_parameter in raw_parameters:
            if not isinstance(raw_parameter, dict):
                _fail("resource_generation.interactive_model_template_mismatch", "真实模型返回了无效的实验参数，已拒绝保存。")
            key = str(raw_parameter.get("key") or "").strip()
            if not key or key in declared_parameters or key not in expected_parameters:
                _fail("resource_generation.interactive_model_template_mismatch", "真实模型返回的参数与所选实验模板不一致，已拒绝保存。")
            declared_parameters[key] = raw_parameter
        if set(declared_parameters) != set(expected_parameters):
            _fail("resource_generation.interactive_model_template_mismatch", "真实模型返回的参数与所选实验模板不一致，已拒绝保存。")
        for key, definition in expected_parameters.items():
            raw_parameter = declared_parameters[key]
            try:
                # ``unit`` is optional in the structured model response: many
                # valid parameters (for example a threshold or a count) have
                # no display unit.  Keep every identity/range field strict and
                # reject unknown keys, while treating a missing unit as "" so
                # a semantically valid model response is not discarded.
                required_keys = {"key", "label", "kind", "minimum", "maximum", "step", "default", "description"}
                if not required_keys.issubset(raw_parameter) or set(raw_parameter) - required_keys - {"unit"}:
                    raise ValueError
                if not str(raw_parameter["label"]).strip() or str(raw_parameter["kind"]).strip() != definition.kind:
                    raise ValueError
                if str(raw_parameter.get("unit") or "") != definition.unit or not str(raw_parameter["description"]).strip():
                    raise ValueError
                for field in ("minimum", "maximum", "step", "default"):
                    if float(raw_parameter[field]) != float(getattr(definition, field)):
                        raise ValueError
            except (KeyError, TypeError, ValueError):
                _fail("resource_generation.interactive_model_template_mismatch", "真实模型返回的参数范围或定义与所选实验模板不一致，已拒绝保存。")
        parameters = [{**definition.model_dump(mode="json"),
                       "label": teacher_text(declared_parameters[definition.key]["label"]),
                       "description": teacher_text(declared_parameters[definition.key]["description"])}
                      for definition in template.parameters]
        raw_constraints = [value for value in llm_payload.get("constraints") or [] if isinstance(value, dict)]
        constraints = []
        for constraint in raw_constraints:
            constraint_id = str(constraint.get("id") or "").strip()
            constraint_title = teacher_text(constraint.get("title"))
            constraint_description = teacher_text(constraint.get("description"))
            if not constraint_id or not constraint_title or not constraint_description:
                _fail("resource_generation.model_output_invalid", "真实模型返回的可交互模型约束缺少 id、title 或 description。")
            constraints.append({"id": constraint_id, "title": constraint_title, "description": constraint_description})
        if not constraints:
            _fail("resource_generation.model_output_invalid", "真实模型返回缺少可交互模型约束。")

        raw_dataset = llm_payload.get("dataset")
        if not isinstance(raw_dataset, dict):
            _fail("resource_generation.model_output_invalid", "真实模型返回缺少可交互模型数据集。")
        dataset_id = str(raw_dataset.get("id") or "").strip()
        dataset_title = teacher_text(raw_dataset.get("title"))
        dataset_summary = teacher_text(raw_dataset.get("summary"))
        sample_count = raw_dataset.get("sampleCount")
        if not dataset_id or not dataset_title or not dataset_summary or isinstance(sample_count, bool) or not isinstance(sample_count, int) or sample_count < 0:
            _fail("resource_generation.model_output_invalid", "真实模型返回的数据集必须包含 id、title、summary 和非负整数 sampleCount；无数据行的公式模拟填0。")
        dataset = {
            "id": dataset_id,
            "title": dataset_title,
            "summary": dataset_summary,
            "sampleCount": sample_count,
            "sourceRefIds": source_ids,
        }

        raw_chart = llm_payload.get("chart")
        if not isinstance(raw_chart, dict):
            _fail("resource_generation.model_output_invalid", "真实模型返回缺少可交互模型图表。")
        x_axis = teacher_text(raw_chart.get("xAxisLabel"))
        y_axis = teacher_text(raw_chart.get("yAxisLabel"))
        if str(raw_chart.get("kind") or "line") != "line" or not x_axis or not y_axis:
            _fail("resource_generation.model_output_invalid", "真实模型图表必须包含 kind=line、xAxisLabel 和 yAxisLabel。")
        raw_series = raw_chart.get("series")
        expected_series = {
            metric.key: {
                "key": metric.key,
                "label": metric.label,
                "unit": metric.unit,
                "higherIsBetter": metric.higher_is_better,
            }
            for metric in template.metrics
        }
        if (not isinstance(raw_series, list) or len(raw_series) != len(expected_series)
                or {row.get("key") for row in raw_series if isinstance(row, dict)} != set(expected_series)):
            _fail("resource_generation.interactive_model_template_mismatch", "真实模型返回的图表指标与所选实验模板不一致，已拒绝保存。")
        for raw_metric in raw_series:
            if not isinstance(raw_metric, dict) or str(raw_metric.get("key") or "") not in expected_series:
                _fail("resource_generation.interactive_model_template_mismatch", "真实模型返回的图表指标与所选实验模板不一致，已拒绝保存。")
            expected_metric = expected_series[str(raw_metric["key"])]
            if not str(raw_metric.get("label") or "").strip() or any(raw_metric.get(field) != expected_metric[field] for field in ("key", "unit", "higherIsBetter")):
                _fail("resource_generation.interactive_model_template_mismatch", "真实模型返回的图表指标定义与所选实验模板不一致，已拒绝保存。")
        chart = {
            "kind": "line",
            "xAxisLabel": x_axis,
            "yAxisLabel": y_axis,
            "series": [
                {"key": metric.key, "label": teacher_text(next(row["label"] for row in raw_series if row["key"] == metric.key)), "unit": metric.unit, "higherIsBetter": metric.higher_is_better}
                for metric in template.metrics
            ],
        }
        observation = teacher_text(llm_payload.get("observationPrompt"))
        if not observation:
            _fail("resource_generation.model_output_invalid", "真实模型返回缺少可交互模型观察提示。")
        completion_rule = str(item.get("completion_rule") or llm_payload.get("completionRule") or observation)
        payload = {
            "schemaVersion": "f6.interactive-model.v1",
            "templateId": template.template_id,
            "title": title,
            "summary": summary,
            "explanation": narrative,
            "courseTitle": str(context.get("course_title") or "当前课程"),
            "knowledgePoint": {"id": knowledge_point_id, "title": knowledge_point},
            "adaptation": adaptation,
            "parameters": parameters,
            "constraints": constraints,
            "dataset": dataset,
            "chart": chart,
            "observationPrompt": {"id": "observation-main", "prompt": observation, "minimumCharacters": 20, "completionRule": completion_rule},
            "completionRule": completion_rule,
            "sourceRefIds": source_ids,
            "semanticContext": semantic,
        }
        return validate(payload, parse_interactive_model_content, "resource_generation.interactive_model_invalid")

    if resource_type == "deck":
        raw_slides = [slide for slide in llm_payload.get("slides") or [] if isinstance(slide, dict)]
        if not raw_slides:
            _fail("resource_generation.model_output_invalid", "真实模型返回缺少幻灯片内容。")
        slides = []
        for index, model_slide in enumerate(raw_slides):
            layout = str(model_slide.get("layout") or (
                "title" if index == 0 and not model_slide.get("body") and not model_slide.get("bullets") else "content"
            ))
            if layout not in {"title", "content", "two_column", "closing"}:
                layout = "content"
            title_text = teacher_text(model_slide.get("title"))
            body_text = teacher_text(model_slide.get("body"))
            if not title_text or (layout != "title" and not body_text and not any(str(value).strip() for value in model_slide.get("bullets") or [])):
                _fail("resource_generation.model_output_invalid", "真实模型返回的幻灯片缺少标题或正文。")
            slides.append({"id": f"slide-{index + 1}", "layout": layout, "title": title_text, "subtitle": teacher_text(model_slide.get("subtitle")), "body": body_text, "bullets": [teacher_text(value) for value in model_slide.get("bullets") or [] if str(value).strip()], "speakerNotes": teacher_text(model_slide.get("speakerNotes")), "sourceRefIds": source_ids})
        return validate({"schemaVersion": "f5.deck.v1", "title": title, "summary": summary, "learningGoal": learning_goal, "adaptationSummary": narrative, "slides": slides}, parse_deck_content, "resource_generation.deck_invalid")

    if resource_type == "video":
        # URLs come only from the live search adapter; model-provided URL
        # suggestions are ignored so a structured response can never publish a
        # fabricated or local placeholder video.
        recommendations = [dict(value) for value in (video_recommendations or []) if isinstance(value, dict)]
        if not recommendations:
            _fail("resource_generation.video_search_empty", "联网搜索没有返回可用的真实网页视频，请稍后重试。")
        # The live adapter is the authority for links. Keep the learner-facing
        # explanation consistent with the actual recommendations; the model
        # must not claim that links are absent when this resource contains them.
        video_narrative = "以下是按当前主题找到的视频链接；打开后可以记录一条学习笔记。"
        video_summary = f"围绕{knowledge_point}找到{len(recommendations)}条视频来源。观看时结合下方学习目标，记录关键步骤和仍需核对的问题。"
        return validate({"schemaVersion": "f5.video-recommendation.v1", "title": title, "summary": video_summary, "learningGoal": learning_goal, "adaptationSummary": video_narrative, "recommendations": recommendations}, parse_video_recommendation_content, "resource_generation.video_invalid")

    _fail("resource_generation.type_invalid", f"不支持的资源类型：{resource_type}")


def _resource_review_groups(candidates: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Assign each whole resource once; other resources remain complete context."""
    if len(candidates) <= 4 and len(_canonical(candidates)) <= 28000:
        return [candidates]
    families = (
        {"handout", "mind_map", "quiz", "feynman"},
        {"handout", "deck", "video", "code_sandbox"},
        {"handout", "code_sandbox", "interactive_model", "training_task"},
    )
    groups = []
    covered = set()
    for family in families:
        group = [item for item in candidates if item["type"] in family and item["type"] not in covered]
        kinds = {item["type"] for item in group}
        if kinds - covered:
            groups.append(group)
            covered.update(kinds)
    remaining = [item for item in candidates if item["type"] not in covered]
    if remaining:
        groups.append(remaining)
    return groups or [candidates]


async def _resource_review_async(
    backend: Any,
    *,
    manifest: dict[str, Any],
    semantic_plan: str,
    candidates: list[dict[str, Any]],
    completed_reviews: dict[str, dict[str, Any]] | None = None,
    save_review: Callable[[str, dict[str, Any]], None] | None = None,
    on_independent_review: Callable[[dict, dict], None] | None = None,
    _grouped: bool = False,
    _review_scope: dict[str, Any] | None = None,
    _section_reviews: list[dict[str, Any]] | None = None,
    _review_slots: asyncio.Semaphore | None = None,
) -> dict[str, Any]:
    review_slots = _review_slots if _review_slots is not None else asyncio.Semaphore(2)
    if not _grouped:
        candidates = [teaching_candidate(item) for item in candidates]
        if manifest.get("verification_mode") == "cove":
            from app.quiz_verification import independently_solve_quizzes
            sources = _resource_prompt_sources(manifest, list({source.get("source_ref_id"): source
                for values in ((manifest.get("input_snapshot") or {}).get("source_snapshots") or {}).values()
                for source in values}.values()), "quiz")
            try:
                independent = await independently_solve_quizzes(backend, candidates, sources,
                    completed=completed_reviews, save=save_review, slots=review_slots)
            except Exception as exc:
                raise ResourceBundleError("resource_generation.reviewer_failed", f"独立解答尚未完成：{exc}") from exc
            manifest = {**manifest, "independent_quiz_verification": independent}
        dependencies = actual_review_dependencies(candidates, manifest.get("dependency_resources") or [])
        async def review_resource(index, candidate):
            computation = None
            if manifest.get('automated_calculation_check'):
                from app.numerical_verification import verify_numerical_content
                try:
                    computation = await verify_numerical_content(backend, candidate,
                        completed=completed_reviews, save=save_review, slots=review_slots)
                except Exception as exc:
                    raise ResourceBundleError('resource_generation.reviewer_failed', f'数值复算尚未完成：{exc}') from exc
                if computation:
                    candidate = {**candidate, 'runtime_verification': {
                        **candidate.get('runtime_verification', {}), 'numerical': computation}}
                    # The connection pass must see the same located claims as
                    # the local verdicts, including uncomputed numeric claims.
                    candidates[index] = candidate
            related = local_dependencies(candidate, candidates, dependencies)
            local_manifest = {**manifest, "dependency_resources": related,
                "active_requirements": requirements_for(manifest, [candidate["type"]]),
                "review_candidate_versions": [{key: item.get(key) for key in ("type", "resource_id", "version_id")}
                    for item in [candidate, *related]],
                "resource_briefs": [item for item in manifest.get("resource_briefs") or []
                                    if item.get("type") == candidate["type"]],
                "review_decisions": [item for item in manifest.get("review_decisions") or []
                                     if item.get("resource_type") in {None, "", candidate["type"]}]}
            result = await _resource_review_async(backend, manifest=local_manifest,
                semantic_plan="" if manifest.get("active_requirements") else semantic_plan,
                candidates=[candidate], completed_reviews=completed_reviews, save_review=save_review,
                _grouped=True, _review_slots=review_slots)
            if computation:
                from app.numerical_verification import apply_numerical_findings
                result = review_findings(apply_numerical_findings(result, candidate, computation), [candidate])
            if on_independent_review and not related and not candidate.get("dependency_bindings"):
                on_independent_review(candidate, result)
            return result

        results = await asyncio.gather(*(review_resource(index, item) for index, item in enumerate(candidates)), return_exceptions=True)
        failure = next((result for result in results if isinstance(result, Exception)), None)
        if failure:
            raise failure
        # One final connection check, after all independent resource reviews.
        # It receives all current teaching content and actual learner links.
        # A failed call leaves individual results available for the same retry.
        if len(candidates) > 1:
            connection = await _resource_review_async(backend,
                manifest={**manifest, "dependency_resources": dependencies,
                    "review_candidate_versions": [{key: item.get(key) for key in ("type", "resource_id", "version_id")}
                                                  for item in candidates]},
                semantic_plan="" if manifest.get("active_requirements") else semantic_plan,
                candidates=candidates, completed_reviews=completed_reviews, save_review=save_review,
                _grouped=True, _review_scope={"stage": "consistency"},
                _section_reviews=results, _review_slots=review_slots)
            results.append(connection)
        return combine_document_reviews(results) if len(results) > 1 else results[0]
    if "review_candidate_versions" not in manifest:
        manifest = {**manifest, "review_candidate_versions": [
            {key: item.get(key) for key in ("type", "resource_id", "version_id")} for item in candidates]}
    context = teaching_context(_public_generation_context(manifest), manifest.get("active_requirements"), review=True)
    reviewer = copy(backend) if hasattr(backend, "reasoning_effort") or hasattr(backend, "max_tokens") else backend
    if hasattr(reviewer, "reasoning_effort"):
        # A real retained-error probe missed arithmetic and resampling defects
        # at low effort. Keep substantive review deep; only the final connection
        # pass reuses already checked local knowledge with lower effort.
        reviewer.reasoning_effort = "high"
    if hasattr(reviewer, "thinking_mode"):
        reviewer.thinking_mode = "enabled"
    if isinstance(getattr(reviewer, "max_tokens", None), int):
        reviewer.max_tokens = 65536
    system = (
        LEARNER_FEEDBACK_INSTRUCTION + LEARNING_TASK_INSTRUCTION + TEACHING_ADAPTATION_INSTRUCTION
        + "你是 EduMatrix Resource Reviewer。只输出一个 JSON 对象：approved、summary、findings、rejectedTypes、teachingReview、conditionReview。"
        "按当前active_requirements、学习者依据、来源和实际页面能力核对；旧生成元数据不是有效要求。"
        "source_request若存在，逐项核对该当前请求的计算与判断动作，规划摘要漏掉的动作仍需完成；显式修订后的快照替代旧请求。"
        "findings只列知识错误、无法完成的任务或真实适配失效，每项写resourceType、location、issue、evidence、fix、"
        "runtime_verification若包含document_code，是本页Python代码的实际运行结果。逐项对照正文宣称的输出、整数属性与数值容差；"
        "numerical给出由原数据与方法独立编程的实跑结果、计算输入和逐项对照；核对输入、算法、参数是否对应原题，"
        "再按原文显示精度判断差异。逐点预测须来自拟合，不能仅因汇总MSE相等就认可；not_computed明确未计算范围，不作已验证。"
        "不要把不同函数/阈值算出的秩或不同计算对象混用。标作完整可运行例子的代码须实际完成；教学片段或待填写骨架按其用途核对，不要求片段单独运行成功。"
        "severity(knowledge_error/task_blocked/adaptation_failure)。给出原句及可核算依据，不复述已正确内容。"
        "普通润色放suggestions，不据此拒绝。approved=false须对应具体findings和rejectedTypes。"
        + _TEACHING_REVISION_GUIDANCE
        + "candidates是本次审核对象。dependency_resources仅为实际固定版本入口，按dependency_bindings中的resource_id/version_id找正文；"
        "review_candidate_versions给出当前版本，不按名称推测新旧，旧生成参考不参与本轮。"
        "单资源审核核对完整正文及显式依赖，未给出的其他资源由最后衔接核对，不猜测其内容。"
        "learning_actions给出本资源真实操作；正文说保存/评分时核对应功能，纸笔/口头/非计分自查不要求有输入框。"
        "完整例题、引导实践和讲义回顾题可展示结果；只有明确计作独立检验的任务不能提前代答。"
        "按learner_adaptation中的具体基础、误解、工具、时间核对先修与提示，不按职业推断能力；各资源可侧重不同子技能。"
        "可用学习时段是安排上限，不是必须填满的最低时长；estimatedMinutes按实际阅读与必做任务估算。"
        "计划中由可用时段推得的时长区间不要求讲义凑足时间，不能只因估时较短就拒绝；核对实际工作量能否完成。"
        "共同成果按resource_briefs的分工在整包完成，不能要求每类资源重做整套练习或使用完全相同的数据；"
        "实验核其可观察对照，视频核观看重点及本页实际安排的任务。仅当该资源明确要求的操作缺输入或整包共同目标确实遗漏时报告阻断。"
        "teachingReview逐资源写targetLevel、observedLevel(foundation/scaffolded/transfer/mixed/not_applicable)、matchesTarget、evidence。"
        "question_details是实际测验题干/选项/答案/解析，检查唯一答案及题设时点，未知目标可以预测、未知输入不能使用。"
        "解析只解释有依据的判断，不要求逐个干扰项编造错误操作。数值按原规则复算边界，不改变题设维护答案。"
        "讲义按outline的ID顺序显示，数组不是阅读顺序；miniQuiz为回顾自查，transferTasks的hint/successCheck默认折叠。"
        "实训expectedResult/passCondition默认折叠，errorGuidance为按需提示；instruction/verification/deliverables/rubric直接可见。"
        "实训报告在笔记填写，不自动评分；运行代码与观察实验只记进度，不冒称独立掌握。"
        "实际绑定的代码文件、输入、输出、运行环境与实验模板是执行依据，核对任务可完成及数据一致；"
        "代码编辑器中的代码常量、数据与答案都是可见内容，不打印不等于隐藏；不能把这种活动描述为封存数据或真实盲测。"
        "逐步核对当时已给出的数据：尚未展示测试结果时可要求先选候选和报告规则，不能要求先写未知测试数值。"
        "注册实验的模拟/固定数据不冒称真实训练，分数/计数/运行成功不代表泛化；不同演示可有不同数据但需准确说明。"
        "以来源支持的当前知识范围为准，保持必要核心深度、明确适用条件；直接返回公开依据和结论，不输出私有推理。"
    )
    reviews_video = any(candidate.get("type") == "video" for candidate in candidates)
    if reviews_video:
        system += "runtime的networkAvailable/fileAccessAvailable只描述代码沙盒，不能据此判定浏览器不能访问视频；学习者离线条件须来自已确认的工具信息。"
    if _review_scope:
        system += (
            "本次是长资源分段核对，当前candidates的全文仍完整提供。review_scope标明本次范围；"
            "section阶段逐项核对指定candidate_index与paths的内容，其余正文只用于查上下文，"
            "局部核对提供当前资源全文、实际代码/实验及显式绑定的配套；其他资源间的教学分工、答案暴露和总时长由最后一致性核对读取全部资源检查，不在局部阶段猜测缺席资源的内容。"
            "不要因本段未重复其他段内容而误报遗漏。consistency阶段核对全文目标覆盖、教学顺序、"
            "前后符号/例子/答案/引用及跨资源依赖是否一致，不重复每段的局部推导。"
            "各段通过不等于整份通过，最终一致性仍须单独给出结论。"
        )
        if _review_scope.get("checks"):
            system += "本次只核对review_scope.checks指定的衔接问题，其余衔接由并列检查承担；全文仍完整可见。"
    system += CONDITION_EQUIVALENCE_GUIDANCE
    condition_claims = conditional_teaching_claims(candidates, _review_scope)
    if _review_scope and _review_scope.get("stage") == "consistency" and _section_reviews is not None:
        # All local statements must already have a current, complete verdict.
        # The final pass still sees the complete candidates and every verdict,
        # but spends its output on relationships instead of repeating them all.
        apply_condition_review(combine_document_reviews(_section_reviews), condition_claims)
        condition_claims = []
        system += (
            "completed_section_reviews保留了全部已完成的局部核对与逐句条件判断，当前原句已逐一对应。"
            "本次不要重新输出这些conditionReview条目，conditionReview返回空数组；"
            "结合完整正文和这些结果，专门检查目标覆盖、学习负担、先后条件、符号、数据、答案与实际配套。"
            "approved只表示本次衔接检查是否发现新问题；局部已拒绝的问题由系统合并保留，不需要你再次拒绝或复述。"
            "没有新增衔接问题时返回approved=true、findings=[]、rejectedTypes=[]，即使completed_section_reviews含未修复问题；这不放行整包。"
            "若发现局部判断遗漏的跨段错误，仍在findings列出原句位置、实际冲突与修正办法，"
            "将approved设为false并列出对应rejectedTypes；不能以局部通过代替一致性核对。"
        )
        system = system.replace(
            "teachingReview逐资源写targetLevel、observedLevel(foundation/scaffolded/transfer/mixed/not_applicable)、matchesTarget、evidence。",
            "本轮teachingReview返回[]，复用已完成的局部适配结论。summary仅写衔接结论；findings只写新增的具体位置、问题、依据和改法，不逐资源复述正确内容。",
        )
    empty_conditions_instruction = "本次condition_claims为空，conditionReview必须返回空数组[]；其他疑点写findings，不把适配说明写成conditionReview对象。"
    if condition_claims:
        system += (
            "condition_claims列出候选中需检查的条件表述，不表示这些句子已经有错。"
            "在conditionReview数组逐项返回claimId、status(valid/overstated/incorrect/uncertain)、reason和fix，完整对应当前原句，不遗漏或重复。"
            "按完整上下文辨认否定、假设和充分/必要关系；用去掉条件后仍成立的反例检查必要性，"
            "用满足条件却不成立的反例检查充分性。区分单次公式与跨步稳定性、边缘结论与联合结论、"
            "本例控制变量与一般成立条件；改成逐步或逐坐标变化时仍成立的等式，不得要求全部步骤或坐标保持同一值。"
            "明确否定必然性的正确句子不能反过来当成肯定命题；正确结论保留valid，无法判定标uncertain。"
            "uncertain表示尚未完成核对，须说明缺少的条件或依据，不能同时宣称整份内容审核通过；也不能为了结束审核把未知改判为正确或错误。"
            "题干中的待判断说法、解析正在否定的干扰项不是作者采纳的结论，不因引用它们就判讲义错误。"
            "overstated/incorrect必须给出可核对的反例或推导和准确改写，纳入findings并拒绝相应资源。"
        )
    else:
        system += empty_conditions_instruction
    if _review_scope and _review_scope.get("stage") == "consistency" and _section_reviews is not None:
        # Local teaching and arithmetic checks are already complete. Giving the
        # connection reviewer that whole job again repeatedly exhausted reasoning
        # before it returned a verdict, even for a single relationship check.
        if hasattr(reviewer, "reasoning_effort"):
            reviewer.reasoning_effort = "low"
        system = (
            LEARNER_FEEDBACK_INSTRUCTION
            + "你核对已经完成逐资源审核的学习材料之间的衔接。只返回JSON对象："
            "approved、summary、findings、rejectedTypes、teachingReview=[]、conditionReview=[]。"
            "本轮teachingReview返回[]；conditionReview必须返回空数组[]。"
            "完整正文、当前版本、来源和completed_section_reviews已提供。复用局部知识、计算与适配结论，"
            "不重新逐句推导、逐题评分或重做全部适配判断。本次只检查review_scope.checks；未指定时核对整体衔接。"
            "检查资源分工是否合起来完成共同目标，先后依赖、数据、符号、答案、实际配套和学习条件是否一致。"
            "active_requirements是当前要求；review_decisions中的已修复/已撤销问题保持关闭，除非发现新的具体反证。"
            "按type/resource_id/version_id定位原句归属，不能把一个资源的完成规则或字段套到另一个资源。"
            "dependency_bindings是实际固定版本入口，旧生成参考不参与；配套页有自己的完成条件，"
            "不因此自动成为实训的必做步骤，是否必做依据实训正文及当前要求。"
            "各资源按分工完成子任务，不要求每页重复整课；同一练习从任一入口首次独立完成后可复用记录，"
            "可用时段是上限，不要求资源凑足时长；根据实际必做内容检查学习负担。"
            "回顾题可重用已解例子，只有计作独立检验的任务不能提前代答。"
            "讲义按outline顺序阅读，transferTasks的hint/successCheck与实训expectedResult/passCondition按需展开；"
            "instruction/verification/deliverables/rubric直接可见。纸笔自查不要求页面输入框，实训报告不自动评分。"
            "局部已拒绝的问题由系统合并保留。approved只表示本次衔接检查是否发现新问题，没有新增问题即true、findings=[]、rejectedTypes=[]；"
            "不能为了重复局部拒绝而再次列同一意见。普通润色不拒绝。"
            "若有知识冲突、任务阻断或适配失效，findings写resourceType、location、issue、evidence、fix、"
            "severity(knowledge_error/task_blocked/adaptation_failure)，引用冲突双方的版本和具体原句，给出准确改法。"
            "新增数值冲突直接复算，按原显示精度判断，不为每个干扰项编造错因。"
            "summary只写本次衔接结论，不逐资源复述正确内容，不输出私有推理。"
        )
        if isinstance(getattr(reviewer, "max_tokens", None), int):
            # Deep reasoning and the public verdict share this allowance.
            # Start with the already supported recovery budget for connections.
            reviewer.max_tokens = 65536
    learning_context = _resource_learning_context(
        [item["type"] for item in candidates], context, manifest.get("dependency_resources") or [],
    )
    if manifest.get("assessment_mode") == "formal_exam":
        learning_context["learning_actions"]["quiz"] = (
            "正式测评支持单选、多选、判断、填空文本和简答文本；按题型显示相应控件，"
            "逐题保存草稿，整卷提交后展示答案和解析。客观题按答案判分，简答按量规评分。"
            "作答前不提供分步提示，不能以缺少练习提示或填空/简答不是选择题为由拒绝。"
        )
        system += (
            "本次候选是正式测评题组，按learning_actions中的正式测评规则审核；"
            "学习者独立作答，不要求学习资源中的逐步提示。逐题检查答案、量规和解析，"
            "不能因某题的类型或数量不同而套用学习测验卡的选项规则。"
        )
    review_runtime = _resource_runtime_context()
    verifications = [item for item in manifest.get("independent_quiz_verification") or []
                     if item.get("version_id") in {candidate.get("version_id") for candidate in candidates}
                     and (not _review_scope or _review_scope.get("stage") == "consistency")]
    if verifications:
        system += (
            "independent_quiz_verification来自未接收原答案/解析的独立求解者。先核对两方结论与实际题目、来源和程序计算，"
            "不要把独立解答直接当真值或凭票数判定。另返回verificationDecisions数组，完整对应每个verification_id，"
            "每项含verification_id、verdict(agree/revise_candidate/solver_error/unresolved)、evidence、issue、fix。"
            "不同答案不得标agree；若原稿正确则solver_error并给具体依据。给定数据不是计算输出；计算检查只证明算式，"
            "仍要核对所用公式、数值和选项。伪引文不能作为依据。原稿确实错误时只修该题及依赖解析，未受影响题目保留。"
        )
    if not reviews_video:
        # The browser/code distinction only changes video review. Keep inputs
        # identical for previously checked code, text and experiment groups.
        review_runtime = {key: value for key, value in review_runtime.items()
                          if key not in {"scope", "scopeDescription"}}
    user = json.dumps({
        "course": {key: value for key, value in context.items()
                   if key not in {"profile_context", "profile_adaptation", "profile_adaptation_plan", "long_term_memory"}},
        "user_instruction": "" if manifest.get("active_requirements") else manifest.get("user_instruction") or "",
        "active_requirements": requirements_for(manifest, [item['type'] for item in candidates]),
        "review_decisions": manifest.get("review_decisions") or [],
        "shared_semantic_plan": "" if manifest.get("active_requirements") else semantic_plan,
        "resource_briefs": [] if manifest.get("active_requirements") else manifest.get("resource_briefs") or [],
        "learner_adaptation": _profile_adaptation_plan(context),
        **({"learner_evidence": manifest["learner_evidence"]} if manifest.get("learner_evidence") else {}),
        **learning_context,
        "runtime": review_runtime,
        "candidates": candidates,
        "review_candidate_versions": manifest["review_candidate_versions"],
        "condition_claims": condition_claims,
        **({"independent_quiz_verification": verifications} if verifications else {}),
        **({"completed_section_reviews": [concise_review(value) for value in _section_reviews]} if _section_reviews is not None else {}),
        "dependency_resources": manifest.get("dependency_resources") or [],
        **({"review_scope": _review_scope} if _review_scope else {}),
        "sources": _resource_prompt_sources(manifest, list({source.get("source_ref_id"): source
                         for values in ((manifest.get("input_snapshot") or {}).get("source_snapshots") or {}).values()
                         for source in values}.values())),
    }, ensure_ascii=False, sort_keys=True)
    # Same frozen inputs and same review instructions can reuse a completed group
    # after a network/output interruption. A changed version or companion invalidates it.
    request_identity = {"system": system, "user": user, "model": str(getattr(reviewer, "model", ""))}
    key = hashlib.sha256(_canonical({**request_identity,
                                    "reasoning": str(getattr(reviewer, "reasoning_effort", "")),
                                    "thinking_mode": getattr(reviewer, "thinking_mode", ""),
                                    "max_tokens": getattr(reviewer, "max_tokens", None)}).encode()).hexdigest()
    # Already completed high-reasoning conclusions remain valid for exactly
    # the same evidence and review instructions. Do not rerun them just because
    # the call controls changed after another resource exhausted its output.
    previous_key = hashlib.sha256(_canonical({**request_identity, "reasoning": "high",
                                              "max_tokens": 32768}).encode()).hexdigest()
    high_effort_key = hashlib.sha256(_canonical({**request_identity, "reasoning": "high",
        "thinking_mode": getattr(reviewer, "thinking_mode", ""),
        "max_tokens": getattr(reviewer, "max_tokens", None)}).encode()).hexdigest()
    high_32k_key = hashlib.sha256(_canonical({**request_identity, "reasoning": "high",
        "thinking_mode": getattr(reviewer, "thinking_mode", ""), "max_tokens": 32768}).encode()).hexdigest()
    # The empty-array clarification changes only formatting. Old results that
    # already satisfy the exact schema and arithmetic checks remain reusable.
    schema_compatible_key = hashlib.sha256(_canonical({**request_identity,
        "system": system.replace(empty_conditions_instruction, ""),
        "reasoning": str(getattr(reviewer, "reasoning_effort", "")),
        "thinking_mode": getattr(reviewer, "thinking_mode", ""),
        "max_tokens": getattr(reviewer, "max_tokens", None)}).encode()).hexdigest()
    cached = ((completed_reviews or {}).get(key) or (completed_reviews or {}).get(high_effort_key)
              or (completed_reviews or {}).get(high_32k_key)
              or (completed_reviews or {}).get(previous_key)
              or (completed_reviews or {}).get(schema_compatible_key))
    if isinstance(cached, dict) and isinstance(cached.get("approved"), bool):
        try:
            apply_condition_review(cached, condition_claims)
        except ValueError:
            pass  # Re-check an incomplete old result; retain other successful groups.
        else:
            if not resource_review_calculation_feedback(cached):
                return cached
    async def review_parts():
        scopes = document_review_scopes(candidates)
        if not scopes:
            raise ResourceBundleError("resource_generation.reviewer_failed", "这部分内容尚未完成核对，可以重试。")
        cache = completed_reviews if completed_reviews is not None else {}

        def remember(part_key, value):
            cache[part_key] = value
            if save_review:
                save_review(part_key, value)

        remember(key + ":parts", {"review_parts_started": True})
        async def review_section(index, scope):
            current = candidates[scope["candidate_index"]]
            # Every field is still assigned, and every section sees its whole
            # resource. Keep executable/explicit dependencies for checking real
            # outputs; the final pass below receives ALL resources and verdicts.
            # Repeating nine whole lessons in each local check caused reasoning
            # exhaustion even when its assigned output was only a few sentences.
            available = {item["version_id"]: item for item in [
                *(manifest.get("dependency_resources") or []), *candidates,
            ] if item.get("version_id") and item.get("version_id") != current.get("version_id")}
            required = {item.get("version_id") for item in current.get("dependency_bindings") or []}
            pending = list(required)
            while pending:
                for binding in available.get(pending.pop(), {}).get("dependency_bindings") or []:
                    version_id = binding.get("version_id")
                    if version_id and version_id not in required:
                        required.add(version_id)
                        pending.append(version_id)
            return await _resource_review_async(
                backend, manifest={**manifest, "dependency_resources": [
                    item for key, item in available.items() if key in required]},
                semantic_plan=semantic_plan, candidates=[current],
                completed_reviews=cache, save_review=remember, _grouped=True,
                _review_scope={"stage": "section", "index": index, **scope, "candidate_index": 0},
                _review_slots=review_slots,
            )
        results = await asyncio.gather(*(review_section(index, scope) for index, scope in enumerate(scopes)),
                                       return_exceptions=True)
        # A failed section must not discard successful siblings or run the
        # consistency pass on incomplete evidence. Gather retains source order.
        failure = next((result for result in results if isinstance(result, Exception)), None)
        if failure:
            raise failure
        results.append(await _resource_review_async(
            backend, manifest=manifest, semantic_plan=semantic_plan, candidates=candidates,
            completed_reviews=cache, save_review=remember, _grouped=True,
            _review_scope={"stage": "consistency"},
            _section_reviews=results,
            _review_slots=review_slots,
        ))
        result = combine_document_reviews(results)
        apply_condition_review(result, conditional_teaching_claims(candidates))
        remember(key, result)
        return result

    async def review_smaller_scopes(scopes, *, reason="output_limit"):
        cache = completed_reviews if completed_reviews is not None else {}

        def remember(part_key, value):
            cache[part_key] = value
            if save_review:
                save_review(part_key, value)

        # Retain the exhaustion as an observable failure and remember the new
        # work shape, so reconnecting does not repeat the known exhausted call.
        remember(key + ":split", {"review_scope_split": scopes, "reason": reason})
        results = await asyncio.gather(*(_resource_review_async(
            backend, manifest=manifest, semantic_plan=semantic_plan, candidates=candidates,
            completed_reviews=cache, save_review=remember, _grouped=True,
            _review_scope=scope, _review_slots=review_slots,
            _section_reviews=_section_reviews,
        ) for scope in scopes), return_exceptions=True)
        failure = next((result for result in results if isinstance(result, Exception)), None)
        if failure:
            raise failure
        combined = apply_condition_review(combine_document_reviews(results), condition_claims)
        remember(key, combined)
        return combined

    smaller_scopes = split_review_scope(candidates, _review_scope or {})
    saved_split = ((completed_reviews or {}).get(key + ":split")
                   or (completed_reviews or {}).get(high_effort_key + ":split")
                   or (completed_reviews or {}).get(high_32k_key + ":split")
                   or (completed_reviews or {}).get(previous_key + ":split"))
    if smaller_scopes and saved_split:
        return await review_smaller_scopes(saved_split.get("review_scope_split") or smaller_scopes,
                                           reason=saved_split.get("reason") or "output_limit")
    if (len(candidates) > 1 and _review_scope == {"stage": "consistency"}
            and len(_canonical(candidates)) > 28000 and smaller_scopes):
        # Four independent relationships, bounded by the same two call slots.
        # Two-relationship passes also exhausted on real nine-resource bundles;
        # go straight to the existing single checks without wasting those calls.
        smaller_scopes = [single for scope in smaller_scopes
                          for single in (split_review_scope(candidates, scope) or [scope])]
        return await review_smaller_scopes(smaller_scopes, reason="large_bundle")
    if not _review_scope and (
        (completed_reviews or {}).get(key + ":parts")
        or (completed_reviews or {}).get(high_effort_key + ":parts")
        or (completed_reviews or {}).get(high_32k_key + ":parts")
        or (completed_reviews or {}).get(previous_key + ":parts")
        or (len(_canonical(candidates)) > 28000 and document_review_scopes(candidates))
    ):
        return await review_parts()
    try:
        review_prompt = user
        calculation_attempts = list(((completed_reviews or {}).get(key + ':arithmetic') or {}).get('calculationReviewAttempts') or [])
        condition_attempts = list(((completed_reviews or {}).get(key + ':conditions') or {}).get('conditionReviewAttempts') or [])
        if calculation_attempts or condition_attempts:
            prior = (condition_attempts or calculation_attempts)[-1]
            review_prompt = json.dumps({**json.loads(user), 'previous_review': prior['review'],
                'review_calculation_feedback': calculation_attempts[-1]['feedback'] if calculation_attempts else [],
                'review_condition_feedback': condition_attempts[-1]['feedback'] if condition_attempts else [],
                'review_instruction': '接续上次尚未解决的具体核对意见，结合当前原文、原稿与实际计算核实。缺少任务必需条件时列清位置和补齐要求，交给后续裁决；不要仅因题设缺条件而反复等待确认。'}, ensure_ascii=False)
        budget_recovery = (completed_reviews or {}).get(key + ":budget")
        if budget_recovery and isinstance(getattr(reviewer, "max_tokens", None), int):
            reviewer.max_tokens = budget_recovery["max_tokens"]
        began = perf_counter()
        for attempt in range(2):
            if attempt and hasattr(reviewer, "reasoning_effort"):
                reviewer.reasoning_effort = "high"
            async with review_slots:
                try:
                    raw = await reviewer.generate(system, review_prompt, role="resource_reviewer")
                except ModelOutputLimitError:
                    # Once a check is indivisible, increasing its output space
                    # restores only that check; splitting and all successes survive.
                    if (smaller_scopes or (not _review_scope and document_review_scopes(candidates))
                            or not isinstance(getattr(reviewer, "max_tokens", None), int)
                            or reviewer.max_tokens >= 65536):
                        raise
                    budget_recovery = {"reason": "output_limit", "previous_max_tokens": reviewer.max_tokens,
                                       "max_tokens": 65536, "scope": _review_scope}
                    if save_review:
                        save_review(key + ":budget", budget_recovery)
                    reviewer.max_tokens = 65536
                    raw = await reviewer.generate(system, review_prompt, role="resource_reviewer")
            result = parse_json_object(raw)
            if not isinstance(result.get("approved"), bool):
                raise ValueError("审核未给出明确结论。")
            feedback = resource_review_calculation_feedback(result)
            try:
                condition_feedback = resource_review_condition_feedback(result, condition_claims)
            except ValueError as exc:
                condition_feedback = str(exc) + " 当前conditionReview须完整对应这些claimId：" + json.dumps(
                    [claim['id'] for claim in condition_claims], ensure_ascii=False)
            if not feedback and not condition_feedback:
                break
            if feedback:
                calculation_attempts.append({"review": result, "feedback": feedback})
                if save_review:
                    save_review(key + ":arithmetic", {"calculationReviewAttempts": calculation_attempts})
            if condition_feedback:
                condition_attempts.append({"review": result, "feedback": condition_feedback})
                if save_review:
                    save_review(key + ":conditions", {"conditionReviewAttempts": condition_attempts})
            if attempt:
                if condition_feedback:
                    raise ValueError("部分结论的适用条件尚未确认，可以重新核对；原稿已保留。")
                raise ValueError("核对意见中的计算仍有矛盾，请重新核对后继续。")
            review_prompt = json.dumps({**json.loads(user), "previous_review": result,
                **({"review_calculation_feedback": feedback} if feedback else {}),
                **({"review_condition_feedback": condition_feedback} if condition_feedback else {}),
                "review_instruction": "只重新核对审核意见，不生成新资源。结合原稿、所选资料和反馈返回完整审核对象；原稿正确时保留，仍缺依据时说明未确认的部分，不编造修正。"}, ensure_ascii=False)
        result = apply_condition_review(result, condition_claims)
        if verifications:
            from app.quiz_verification import apply_verification_decisions
            result = apply_verification_decisions(result, verifications)
        result = review_findings(result, candidates)
        result["reviewed_versions"] = [{"type": item['type'], "version_id": item.get('version_id')}
                                       for item in candidates]
        result["execution"] = {"seconds": round(perf_counter() - began, 3),
            "input_chars": len(system) + len(review_prompt), "scope": _review_scope,
            "reasoning_effort": getattr(reviewer, 'reasoning_effort', None),
            "thinking_mode": getattr(reviewer, 'thinking_mode', None),
            "max_tokens": getattr(reviewer, 'max_tokens', None)}
        if not result["approved"] and not result.get("rejectedTypes"):
            raise ValueError("审核未说明需要修改的内容。")
        if calculation_attempts:
            result["calculationReviewAttempts"] = calculation_attempts
        if condition_attempts:
            result["conditionReviewAttempts"] = condition_attempts
        if save_review:
            save_review(key, result)
        return result
    except ModelOutputLimitError as exc:
        if save_review:
            save_review(key + ":failure", {"review_failed": True, "reason": "output_limit",
                "execution": {"seconds": round(perf_counter() - began, 3),
                    "input_chars": len(system) + len(review_prompt), "scope": _review_scope,
                    "max_tokens": getattr(reviewer, "max_tokens", None)}})
        if not _review_scope and document_review_scopes(candidates):
            return await review_parts()
        if smaller_scopes:
            return await review_smaller_scopes(smaller_scopes)
        raise ResourceBundleError("resource_generation.reviewer_failed", "这部分内容尚未完成核对，可以重试。") from exc
    except Exception as exc:
        if save_review:
            save_review(key + ":failure", {"review_failed": True, "reason": "review_call_failed",
                "error_type": type(exc).__name__,
                "execution": {"seconds": round(perf_counter() - began, 3),
                    "input_chars": len(system) + len(review_prompt), "scope": _review_scope,
                    "max_tokens": getattr(reviewer, "max_tokens", None)}})
        raise ResourceBundleError("resource_generation.reviewer_failed", f"资源审核模型调用失败：{exc}") from exc


def _resource_review_content(db: Any, version: DBArtifactVersion, resource_type: str) -> str:
    raw_content = str(version.content or "")
    # Structured resource artifacts must remain parseable when passed to
    # the reviewer.  Truncating JSON at an arbitrary character boundary
    # made every sufficiently rich handout look corrupted and caused the
    # live review gate to reject otherwise valid model output. Keep the whole
    # Markdown body too, including its final instructions and learning goal.
    if version.content_format == "json":
        try:
            parsed_content = json.loads(raw_content)
            if resource_type == "quiz":
                parsed_content["question_details"] = []
                for reference in parsed_content.get("questions", []):
                    question_version = db.get(DBAssessmentQuestionVersion, reference.get("questionVersionId"))
                    if question_version is not None:
                        parsed_content["question_details"].append({
                            "questionVersionId": question_version.id,
                            "prompt": question_version.prompt,
                            "options": question_version.options,
                            "answer_key": question_version.answer_key,
                            "explanation": question_version.explanation,
                            "difficulty": question_version.expert_difficulty,
                            "knowledgePointId": question_version.primary_knowledge_point_id,
                        })
            review_content = json.dumps(parsed_content, ensure_ascii=False)
        except (TypeError, ValueError):
            review_content = raw_content
    else:
        review_content = raw_content
    return review_content


def _review_dependency_bindings(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    # Training links are learner navigation. Practical references are frozen
    # generation inputs; the code/experiment pages do not navigate through them.
    return [
        {**{key: binding[key] for key in ("type", "resource_id", "version_id") if key in binding},
         "purpose": purpose}
        for field, purpose in (("training_dependencies", "learner_link"),)
        for binding in metadata.get(field) or [] if isinstance(binding, dict)
    ]


def _candidate_resources(db: Any, task: DBGenerationTask, latest: dict[int, DBTaskStep]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for resource_type in _manifest_resource_types(_generation_manifest(db, task.id)):
        sequence = GENERATION_RESOURCE_TYPES.index(resource_type) + 1
        step = latest.get(sequence)
        if step is None or step.status != "succeeded" or not step.output_artifact_version_id:
            continue
        version = db.get(DBArtifactVersion, step.output_artifact_version_id)
        artifact = db.get(DBArtifact, version.artifact_id) if version else None
        if version is None or artifact is None:
            continue
        metadata = dict(version.metadata_json or {})
        review_content = _resource_review_content(db, version, resource_type)
        candidates.append({
            "type": resource_type,
            "resource_id": artifact.id,
            "version_id": version.id,
            "title": artifact.title,
            "content": review_content,
            "source_ref_ids": list(metadata.get("source_ref_ids") or []),
            "content_format": version.content_format,
            "dependency_bindings": _review_dependency_bindings(metadata),
            **({"runtime_verification": metadata["runtime_verification"]} if metadata.get("runtime_verification") else {}),
        })
    return candidates


def _generation_revision_context(db: Any, task: DBGenerationTask, step: DBTaskStep) -> dict[str, Any] | None:
    previous = db.query(DBTaskStep).filter(
        DBTaskStep.task_id == task.id, DBTaskStep.sequence == step.sequence,
        DBTaskStep.attempt < step.attempt, DBTaskStep.output_artifact_version_id.isnot(None),
    ).order_by(DBTaskStep.attempt.desc()).first()
    version = db.get(DBArtifactVersion, previous.output_artifact_version_id) if previous else None
    if version is None:
        return None
    kind = GENERATION_RESOURCE_TYPES[step.sequence - 1]
    return teaching_candidate({"type": kind, "version_id": version.id, "content_format": version.content_format,
            "content": _resource_review_content(db, version, kind)})


def _saved_training_rubric_payload(revision_source, completed_parts, **content_args):
    """Replay a saved model output only when conversion alone lost its rubric.

    Matching the entire visible body prevents borrowing another generation or
    ignoring revised dependencies. The resulting version still goes to review.
    """
    if not revision_source:
        return None
    previous = json.loads(revision_source["content"])
    previous.pop("semanticContext", None)
    for original in reversed(list(completed_parts.values())):
        if not isinstance(original, dict) or not original.get("rubric") or not original.get("practiceSteps"):
            continue
        try:
            converted = json.loads(_llm_resource_content(
                resource_type="training_task", llm_payload=original, **content_args))
        except (ResourceBundleError, ValueError, TypeError):
            continue
        converted.pop("semanticContext", None)
        if (converted.get("rubric") != previous.get("rubric")
                and {k: v for k, v in converted.items() if k != "rubric"}
                == {k: v for k, v in previous.items() if k != "rubric"}):
            return original
    return None


def _practical_dependencies(db: Any, task: DBGenerationTask, latest: dict[int, DBTaskStep], resource_type: str = "training_task") -> list[dict[str, Any]]:
    """Use this run's outputs first; reuse published, matching resources for omitted types."""
    manifest = _generation_manifest(db, task.id)
    current = {item["type"]: item for item in _candidate_resources(db, task, latest)}
    selected_item = next(item for item in manifest["items"] if item["type"] == resource_type)
    expected_sources = set(selected_item.get("source_ref_ids") or [])
    expected_hash = ((manifest.get("input_snapshot") or {}).get("source_snapshot_hashes") or {}).get(resource_type)
    gate = manifest.get("exam_gate") or {}
    path_identity = tuple(gate.get(key) for key in ('path_id', 'path_version_id', 'selected_task_id'))
    origin_manifests = {}
    dependencies = []
    for kind in _resource_dependencies("training_task"):
        if kind == resource_type:
            continue
        if GENERATION_RESOURCE_TYPES.index(kind) + 1 in latest:
            # A failed/currently running requested resource must never be replaced by an old one.
            if kind in current:
                dependencies.append(current[kind])
            continue
        if not manifest.get("knowledge_point_id"):
            continue
        rows = db.query(DBArtifact).filter_by(
            owner_public_id=task.owner_public_id, course_id=task.course_id,
            artifact_type=kind, status="published", archived_at=None,
        ).order_by(DBArtifact.updated_at.desc(), DBArtifact.id.desc()).all()
        for artifact in rows:
            version = db.get(DBArtifactVersion, artifact.current_version_id) if artifact.current_version_id else None
            metadata = dict(version.metadata_json or {}) if version else {}
            if (not version or metadata.get("knowledge_point_id") != manifest["knowledge_point_id"]
                    or set(metadata.get("source_ref_ids") or []) != expected_sources
                    or (expected_hash and metadata.get("source_snapshot_hash") != expected_hash)):
                continue
            origin_id = version.created_task_id or metadata.get('generation_job_id')
            if not origin_id:
                continue
            if origin_id not in origin_manifests:
                origin_manifests[origin_id] = _generation_manifest(db, origin_id)
            origin = origin_manifests[origin_id]
            snapshot = manifest.get('input_snapshot') or {}
            origin_snapshot = origin.get('input_snapshot') or {}
            if (any(origin_snapshot.get(key) != snapshot.get(key)
                    for key in ('profile_snapshot_hash', 'recent_event_cursor'))
                    or (origin.get('context') or {}).get('learning_goal') != (manifest.get('context') or {}).get('learning_goal')
                    or origin.get('user_instruction', '') != manifest.get('user_instruction', '')):
                continue
            if gate:
                origin_gate = origin.get('exam_gate') or {}
                if tuple(origin_gate.get(key) for key in ('path_id', 'path_version_id', 'selected_task_id')) != path_identity:
                    # Earlier lessons are supplied separately as learning context.
                    # A shared concept/source is not a current companion contract.
                    continue
            dependencies.append({
                "type": kind, "resource_id": artifact.id, "version_id": version.id,
                "title": artifact.title, "content": version.content,
                "content_format": version.content_format,
                "source_ref_ids": list(metadata.get("source_ref_ids") or []),
            })
            break
    return dependencies


def _frozen_practical_dependencies(db: Any, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Review the exact companion versions used when each practice resource was written."""
    dependencies = []
    for candidate in candidates:
        version = db.get(DBArtifactVersion, candidate["version_id"])
        metadata = version.metadata_json or {}
        for binding in metadata.get("training_dependencies", []):
            linked = db.get(DBArtifactVersion, binding["version_id"])
            artifact = db.get(DBArtifact, binding["resource_id"])
            if linked and artifact and linked.artifact_id == artifact.id:
                dependencies.append({**binding, "title": artifact.title, "content": linked.content,
                                     "content_format": linked.content_format,
                                     "dependency_bindings": _review_dependency_bindings(linked.metadata_json or {})})
    return dependencies


def _review_findings_for_type(findings: list[Any], resource_type: str) -> list[Any]:
    details = []
    for finding in findings:
        if isinstance(finding, str):
            details.append(finding)
        elif isinstance(finding, dict):
            kind = str(finding.get("resourceType") or finding.get("resource_type") or finding.get("type") or "")
            # Older reviewers used titles or issue categories instead of resource types.
            # Keep unclassified feedback; only exclude a known different resource.
            if kind == resource_type or kind not in GENERATION_RESOURCE_TYPES:
                details.append(finding)
    return details


def _mark_review_rejected(
    db: Any,
    *,
    task: DBGenerationTask,
    latest: dict[int, DBTaskStep],
    rejected_types: list[str],
    reason: str,
    findings: list[Any] | None = None,
) -> None:
    for resource_type in rejected_types:
        sequence = GENERATION_RESOURCE_TYPES.index(resource_type) + 1
        step = latest.get(sequence)
        if step is None or step.status != "succeeded":
            continue
        step.status = "failed"
        step.error_code = "resource_generation.review_rejected"
        details = _review_findings_for_type(findings or [], resource_type)
        step.error_message = (str(reason or "资源审核要求返工") + (
            "\n具体审核意见：" + json.dumps(details, ensure_ascii=False) if details else ""
        ))
        step.completed_at = _utcnow()
        _resource_event(
            db,
            task=task,
            event_type="resource.item.failed",
            resource_type=resource_type,
            status="failed",
            summary=step.error_message,
            step=step,
            output_refs=[f"artifact-version:{step.output_artifact_version_id}"],
            retryable=True,
        )


def execute_generation_job(
    db: Any,
    actor: DBUser,
    task_id: str,
    *,
    event_callback: Callable[[dict[str, Any]], None] | None = None,
    execution_token: str | None = None,
) -> dict[str, Any]:
    """Execute a live resource run through the shared Planner/Supervisor graph."""
    task = _generation_task(db, actor, task_id)
    if task.status == "cancelled":
        _fail("resource_generation.cancelled", "已取消任务不能执行")
    if task.status == "completed":
        return generation_job_payload(db, actor, task.id)
    if task.automation_state and (not execution_token or execution_token != task.execution_token):
        return generation_job_payload(db, actor, task.id)

    def was_cancelled() -> bool:
        # A different request may cancel while the external model is running.
        # Never write its late answer or publish it over that cancellation.
        db.refresh(task, attribute_names=["status", "execution_token"])
        if task.status != "cancelled" and (not execution_token or task.execution_token == execution_token):
            return False
        db.rollback()
        db.expire_all()
        return True
    manifest = _generation_manifest(db, task.id)
    if task.automation_state:
        manifest = {**manifest, "verification_mode": "cove",
                    "repair_strategy": (task.automation_context or {}).get("repair_strategy")}
    requested_types = list(_manifest_resource_types(manifest))
    run_event_start = max(
        (int(row.sequence or 0) for row in db.query(DBTaskEvent).filter_by(task_id=task.id).all()),
        default=0,
    )

    def ensure_run_failed(summary: str) -> None:
        """Expose one failed terminal event for this execution attempt."""
        rows = db.query(DBTaskEvent).filter_by(task_id=task.id).all()
        if any(
            int(row.sequence or 0) > run_event_start and row.event_type == "run.failed"
            for row in rows
        ):
            return
        _resource_event(
            db,
            task=task,
            event_type="run.failed",
            status="failed",
            summary=summary,
            retryable=True,
        )
    _, latest = _task_steps(db, task.id)
    try:
        backend = _real_model_backend()
    except ResourceBundleError as exc:
        for resource_type in requested_types:
            sequence = GENERATION_RESOURCE_TYPES.index(resource_type) + 1
            step = latest.get(sequence)
            if step and step.status in {"queued", "retry_queued", "requested", "running"}:
                fail_generation_item(db, actor, task.id, resource_type, error_code=exc.code, error_message=str(exc))
        _resource_event(db, task=task, event_type="run.failed", status="failed", summary=str(exc), retryable=True,
                        error_code=exc.code, error_message=str(exc))
        _sync_generation_task(db, task)
        return generation_job_payload(db, actor, task.id)

    callback_token = _RESOURCE_EVENT_CALLBACK.set(event_callback)
    completed_parts = {
        row.payload["input_hash"]: row.payload["part"]
        for row in db.query(DBTaskEvent).filter_by(task_id=task.id, event_type="resource_generation.part_result").all()
        if isinstance(row.payload, dict) and row.payload.get("input_hash") and isinstance(row.payload.get("part"), dict)
    }

    def save_generated_part(input_hash, part):
        if was_cancelled():
            raise ResourceBundleError("resource_generation.cancelled", "本次生成已停止，已完成部分仍然保留。")
        append_task_event(db, task_id=task.id, event_type="resource_generation.part_result",
                          payload={"input_hash": input_hash, "part": part})
        db.commit()

    parts_token = _RESOURCE_PARTS.set((completed_parts, save_generated_part))
    loop = asyncio.new_event_loop()
    previous_loop = None
    try:
        try:
            previous_loop = asyncio.get_event_loop()
        except RuntimeError:
            previous_loop = None
        asyncio.set_event_loop(loop)
        task.status = "running"
        task.started_at = task.started_at or _utcnow()
        _resource_event(
            db,
            task=task,
            event_type="stage.started",
            status="running",
            stage_id="resource_planner",
            run_id=manifest.get("planner_run_id") or f"resource-plan:{task.id}",
            summary="正在结合你的要求安排学习重点，让各项资源相互衔接。",
            input_refs=[f"task:{task.id}"],
            progress=0.02,
        )
        plan_payload = _generation_plan(db, task.id)
        plan = str(plan_payload.get("plan") or "")
        related_by_type = {kind: _practical_dependencies(db, task, latest, kind)
                           for kind in requested_types if kind in {"code_sandbox", "interactive_model", "training_task"}}
        planning_dependencies = list({item["version_id"]: item for values in related_by_type.values() for item in values}.values())
        if not plan:
            all_sources: list[dict[str, Any]] = []
            for resource_type in requested_types:
                sequence = GENERATION_RESOURCE_TYPES.index(resource_type) + 1
                step = latest.get(sequence)
                if step is None:
                    continue
                item = _step_input(step)
                all_sources.extend(_generation_source_snapshots(db, task=task, manifest=manifest, item=item, resource_type=resource_type))
            unique_sources = {str(source.get("source_ref_id") or ""): source for source in all_sources if source.get("source_ref_id")}
            db.commit()
            plan_payload = loop.run_until_complete(_shared_semantic_plan_async(
                backend,
                manifest={**manifest, "dependency_resources": planning_dependencies},
                source_snapshots=list(unique_sources.values()),
            ))
            if was_cancelled():
                return generation_job_payload(db, actor, task.id)
            plan = str(plan_payload["plan"])
            plan_event = append_task_event(
                db,
                task_id=task.id,
                event_type="resource_generation.plan.completed",
                payload={
                    "run_id": manifest.get("planner_run_id") or f"resource-plan:{task.id}",
                    "stage_id": "resource_planner",
                    "status": "completed",
                    "owner": "Resource Planner",
                    "summary": plan_payload.get("summary") or plan[:320],
                    "plan": plan,
                    "resource_briefs": plan_payload.get("resource_briefs") or [],
                    "active_requirements": plan_payload.get("active_requirements"),
                    "format_corrections": plan_payload.get("format_corrections", 0),
                    "progress": 0.12,
                    "retryable": False,
                },
            )
            callback = _RESOURCE_EVENT_CALLBACK.get()
            if callback is not None:
                callback({
                    "event_id": plan_event.id,
                    "sequence": plan_event.sequence,
                    "event_type": "stage.completed",
                    "run_id": plan_payload.get("run_id") or manifest.get("planner_run_id") or f"resource-plan:{task.id}",
                    "stage_id": "resource_planner",
                    "resource_item_id": "",
                    "resource_type": "",
                    "status": "completed",
                    "owner": "Resource Planner",
                    "summary": str(plan_payload.get("summary") or plan[:320])[:320],
                    "input_refs": [f"task:{task.id}"],
                    "output_refs": [],
                    "progress": 0.12,
                    "retryable": False,
                })
        else:
            plan_payload = {**plan_payload, "plan": plan}

        # Keep the planner's per-resource responsibilities in generator and
        # reviewer inputs, including when resuming an already saved plan.
        manifest = {**manifest, "resource_briefs": plan_payload.get("resource_briefs") or [],
                    "active_requirements": plan_payload.get("active_requirements") or manifest.get("active_requirements")}

        independent_types = [resource_type for resource_type in requested_types if resource_type != "training_task"]
        requests: list[tuple[str, DBTaskStep, dict[str, Any], list[dict[str, Any]]]] = []
        _, latest = _task_steps(db, task.id)
        for resource_type in independent_types:
            sequence = GENERATION_RESOURCE_TYPES.index(resource_type) + 1
            step = latest.get(sequence)
            if step is None or step.status in {"succeeded", "failed", "cancelled"}:
                continue
            item = _step_input(step)
            try:
                if step.status != "running":
                    mark_generation_item_running(db, actor, task.id, resource_type)
                    _, latest = _task_steps(db, task.id)
                    step = latest[sequence]
                source_snapshots = _generation_source_snapshots(db, task=task, manifest=manifest, item=item, resource_type=resource_type)
                requests.append((resource_type, step, item, source_snapshots))
                _resource_event(
                    db,
                    task=task,
                    event_type="resource.item.started",
                    resource_type=resource_type,
                    status="running",
                    summary=f"正在结合课程内容准备{_DEMO_RESOURCE_LABELS.get(resource_type, '学习资源')}。",
                    step=step,
                    input_refs=[f"task:{task.id}", *[f"source:{item_id}" for item_id in item.get("source_ref_ids") or []]],
                    progress=0.16,
                    retryable=True,
                )
            except ResourceBundleError as exc:
                fail_generation_item(db, actor, task.id, resource_type, error_code=exc.code, error_message=str(exc))
                _resource_event(db, task=task, event_type="resource.item.failed", resource_type=resource_type, status="failed", summary=str(exc), step=step, retryable=True)

        async def generate_candidate(request):
            resource_type, step, item, source_snapshots = request
            video_recommendations = None
            try:
                if resource_type == "video":
                    video_brief = next((brief for brief in plan_payload.get("resource_briefs", [])
                                        if brief.get("type") == "video"), {})
                    queries = video_brief.get("searchQueries") or []
                    rejected_ids: set[str] = set()
                    for search_attempt in range(2):
                        candidates = await _live_video_recommendations(manifest={**manifest, "video_search_queries": queries,
                                                                                "video_excluded_ids": sorted(rejected_ids)})
                        append_task_event(db, task_id=task.id, step_id=step.id,
                            event_type="resource_generation.video_search", payload={
                                "search_attempt": search_attempt + 1, "queries": queries, "candidates": candidates})
                        db.commit()
                        result = await _real_model_payload_async(
                            backend, resource_type=resource_type, item=item,
                            manifest={**manifest, "video_candidates": candidates,
                                      "revision_source": _generation_revision_context(db, task, step)},
                            source_snapshots=source_snapshots, semantic_plan=plan)
                        video_recommendations = _select_video_recommendations(result, candidates)
                        if video_recommendations:
                            break
                        rejected_ids.update(candidate["id"] for candidate in candidates)
                        queries = [query for query in result.get("searchQueries", []) if isinstance(query, str) and query.strip()]
                        if not queries:
                            break
                    if not video_recommendations:
                        _fail("resource_generation.video_topic_mismatch", "本次候选与学习重点不合适，检索记录已保留，可重新寻找。")
                    return request, result, video_recommendations
                result = await _real_model_payload_async(
                    backend, resource_type=resource_type, item=item,
                    manifest={**manifest, "dependency_resources": related_by_type.get(resource_type, []),
                              "revision_source": _generation_revision_context(db, task, step)},
                    source_snapshots=source_snapshots, semantic_plan=plan,
                )
            except Exception as exc:
                result = exc
            return request, result, video_recommendations

        async def generate_and_save_candidates():
            slots = asyncio.Semaphore(2)
            async def generate_in_slot(request):
                async with slots:
                    if was_cancelled():
                        raise asyncio.CancelledError()
                    return await generate_candidate(request)
            pending = [asyncio.create_task(generate_in_slot(request)) for request in requests]
            try:
                for completed in asyncio.as_completed(pending):
                    (resource_type, step, item, source_snapshots), result, video_recommendations = await completed
                    if was_cancelled():
                        return
                    try:
                        if isinstance(result, Exception):
                            raise result
                        linked_resource_ids: list[str] = []
                        content = (
                            _create_quiz_resource_content(db, actor=actor, task=task, item=item, manifest=manifest, source_snapshots=source_snapshots, llm_payload=result)
                            if resource_type == "quiz"
                            else _llm_resource_content(resource_type=resource_type, item=item, manifest={**manifest, "dependency_resources": related_by_type.get(resource_type, [])}, source_snapshots=source_snapshots, linked_resource_ids=linked_resource_ids, llm_payload=result, video_recommendations=video_recommendations)
                        )
                        content_format = "json" if resource_type in {"handout", "mind_map", "training_task", "code_sandbox", "video", "deck", "interactive_model", "quiz"} else "markdown"
                        if task.automation_state and resource_type == "code_sandbox":
                            from app.code_sandbox import validate_generated_code
                            run_key = "code-execution:" + hashlib.sha256(content.encode()).hexdigest()
                            execution = completed_parts.get(run_key)
                            if execution is None:
                                execution = await validate_generated_code(content)
                                completed_parts[run_key] = execution
                                save_generated_part(run_key, execution)
                            failed_checks = [check for check in execution.get('checks', []) if not check.get('passed')]
                            if execution.get("status") != "success" or failed_checks:
                                # Preserve the failed candidate as a version so
                                # the normal local revision can repair its code.
                                complete_generation_item(db, actor, task.id, resource_type, content=content,
                                    content_format=content_format, generation_mode="llm", model="deepseek-v4-flash",
                                    reasoning_effort="max", practical_dependencies=related_by_type.get(resource_type, []))
                                # The persisted item is a candidate that has
                                # failed execution, not an approved resource.
                                step.status = "running"
                                _fail("resource_generation.code_execution_invalid", "代码试运行未完成：" +
                                      str(execution.get("stderr") or execution.get("errorCode") or '') +
                                      (json.dumps(failed_checks, ensure_ascii=False) if failed_checks else ''))
                        document_execution = None
                        if task.automation_state and resource_type == 'handout':
                            from app.code_sandbox import verify_document_code
                            document_execution = await verify_document_code(content, completed=completed_parts, save=save_generated_part)
                            if was_cancelled():
                                return
                        complete_generation_item(db, actor, task.id, resource_type, content=content, content_format=content_format, generation_mode="llm", model="deepseek-v4-flash", reasoning_effort="max", practical_dependencies=related_by_type.get(resource_type, []))
                        _, latest = _task_steps(db, task.id)
                        output_step = latest[GENERATION_RESOURCE_TYPES.index(resource_type) + 1]
                        if document_execution:
                            output_version = db.get(DBArtifactVersion, output_step.output_artifact_version_id)
                            output_version.metadata_json = {**(output_version.metadata_json or {}),
                                'runtime_verification': {'document_code': document_execution}}
                        if task.automation_state and resource_type == "code_sandbox":
                            output_version = db.get(DBArtifactVersion, output_step.output_artifact_version_id)
                            output_version.metadata_json = {**(output_version.metadata_json or {}),
                                "runtime_verification": {key: execution.get(key) for key in
                                    ("status", "exitCode", "stdout", "stderr", "checks", "executionTimeMs")}}
                        _resource_event(db, task=task, event_type="resource.item.completed", resource_type=resource_type, status="completed", summary=f"{_DEMO_RESOURCE_LABELS.get(resource_type, '学习资源')}初稿已完成，正在等待内容核对。", step=output_step, output_refs=[f"artifact-version:{output_step.output_artifact_version_id}"], progress=0.55, retryable=False)
                    except Exception as exc:
                        if was_cancelled():
                            return generation_job_payload(db, actor, task.id)
                        error = exc if isinstance(exc, ResourceBundleError) else ResourceBundleError("resource_generation.model_call_failed", str(exc))
                        fail_generation_item(db, actor, task.id, resource_type, error_code=error.code, error_message=str(error))
                        _resource_event(db, task=task, event_type="resource.item.failed", resource_type=resource_type, status="failed", summary=str(error), step=step, retryable=True)
                    db.commit()
            finally:
                for pending_call in pending:
                    if not pending_call.done():
                        pending_call.cancel()
                await asyncio.gather(*pending, return_exceptions=True)

        # Each completed candidate is saved and reported immediately; a slow
        # sibling or provider interruption must not discard successful work.
        db.commit()
        loop.run_until_complete(generate_and_save_candidates())
        if was_cancelled():
            return generation_job_payload(db, actor, task.id)

        # Training task is a strict dependency edge and is evaluated only after both
        # code sandbox and interactive model have produced artifact versions.
        _, latest = _task_steps(db, task.id)
        if "training_task" in requested_types:
            sequence = GENERATION_RESOURCE_TYPES.index("training_task") + 1
            step = latest.get(sequence)
            dependency_steps = [latest.get(GENERATION_RESOURCE_TYPES.index(dep) + 1) for dep in _resource_dependencies("training_task")]
            dependencies = _practical_dependencies(db, task, latest)
            # A retried sandbox/model produces a new artifact version.  A
            # previously successful training task must be regenerated against
            # those newest dependency IDs instead of keeping a stale link.
            if step and step.status == "succeeded" and len(dependencies) == len(_resource_dependencies("training_task")):
                previous_version = db.get(DBArtifactVersion, step.output_artifact_version_id)
                previous_bindings = {
                    dep["type"]: dep["version_id"]
                    for dep in ((previous_version.metadata_json or {}).get("training_dependencies") or [])
                } if previous_version else {}
                current_bindings = {dep["type"]: dep["version_id"] for dep in dependencies}
                if previous_bindings != current_bindings:
                    refreshed_step = create_task_step(
                        db,
                        task_id=task.id,
                        sequence=sequence,
                        attempt=int(step.attempt or 0) + 1,
                        agent_role=step.agent_role,
                        tool_name=step.tool_name,
                        input_summary=step.input_summary,
                    )
                    refreshed_step.status = "retry_queued"
                    task.completed_at = None
                    step = refreshed_step
                    latest[sequence] = refreshed_step
                    append_task_event(
                        db,
                        task_id=task.id,
                        step_id=refreshed_step.id,
                        event_type="resource_generation.item.retry_queued",
                        payload={
                            "type": "training_task",
                            "attempt": refreshed_step.attempt,
                            "reason": "依赖资源版本已更新，按最新依赖重新生成",
                        },
                    )
            if step and step.status not in {"succeeded", "failed", "cancelled"}:
                if len(dependencies) == len(_resource_dependencies("training_task")):
                    item = _step_input(step)
                    try:
                        mark_generation_item_running(db, actor, task.id, "training_task")
                        _, latest = _task_steps(db, task.id)
                        step = latest[sequence]
                        source_snapshots = _generation_source_snapshots(db, task=task, manifest=manifest, item=item, resource_type="training_task")
                        linked_resource_ids = [dep["resource_id"] for dep in dependencies]
                        _resource_event(db, task=task, event_type="resource.item.started", resource_type="training_task", status="running", summary="配套代码和实验已准备好，开始生成实训任务书。", step=step, input_refs=[f"artifact-version:{dep['version_id']}" for dep in dependencies], progress=0.62, retryable=True)
                        db.commit()
                        revision_source = _generation_revision_context(db, task, step)
                        result = _saved_training_rubric_payload(revision_source, completed_parts,
                            item=item, manifest=manifest, source_snapshots=source_snapshots,
                            linked_resource_ids=linked_resource_ids)
                        if result is not None:
                            append_task_event(db, task_id=task.id, step_id=step.id,
                                event_type="resource_generation.conversion_recovered",
                                payload={"type": "training_task", "previous_version_id": revision_source["version_id"],
                                         "field": "rubric", "saved_model_output_reused": True})
                            db.commit()
                        else:
                            result = loop.run_until_complete(_real_model_payload_async(backend, resource_type="training_task", item=item, manifest={**manifest, "dependency_resources": dependencies, "revision_source": revision_source}, source_snapshots=source_snapshots, semantic_plan=plan))
                        if was_cancelled():
                            return generation_job_payload(db, actor, task.id)
                        content = _llm_resource_content(resource_type="training_task", item=item, manifest=manifest, source_snapshots=source_snapshots, linked_resource_ids=linked_resource_ids, llm_payload=result)
                        complete_generation_item(db, actor, task.id, "training_task", content=content, content_format="json", generation_mode="llm", model="deepseek-v4-flash", reasoning_effort="max", training_dependencies=dependencies)
                        _, latest = _task_steps(db, task.id)
                        output_step = latest[sequence]
                        _resource_event(db, task=task, event_type="resource.item.completed", resource_type="training_task", status="completed", summary="实训任务书已基于两个依赖资源生成。", step=output_step, output_refs=[f"artifact-version:{output_step.output_artifact_version_id}"], progress=0.7, retryable=False)
                    except Exception as exc:
                        if was_cancelled():
                            return generation_job_payload(db, actor, task.id)
                        error = exc if isinstance(exc, ResourceBundleError) else ResourceBundleError("resource_generation.model_call_failed", str(exc))
                        fail_generation_item(db, actor, task.id, "training_task", error_code=error.code, error_message=str(error))
                        _resource_event(db, task=task, event_type="resource.item.failed", resource_type="training_task", status="failed", summary=str(error), step=step, retryable=True)
                elif any(dep is None or dep.status == "failed" for dep in dependency_steps):
                    message = "请先为当前知识点和资料生成代码沙盒与交互实验，再重试实训任务书；也可以同时选择这三类资源。"
                    fail_generation_item(db, actor, task.id, "training_task", error_code="resource_generation.dependency_failed", error_message=message)
                    _resource_event(db, task=task, event_type="resource.item.failed", resource_type="training_task", status="failed", summary=message, step=step, retryable=True)

        _, latest = _task_steps(db, task.id)
        states = [row.status for row in latest.values()]
        complete_candidates = bool(states) and all(state == "succeeded" for state in states)
        if complete_candidates or (task.automation_state and 'succeeded' in states):
            review_status = _review_gate_status(db, task.id)
            if review_status != "passed" or not complete_candidates:
                _resource_event(db, task=task, event_type="review_gate.started", status="running", stage_id="review_gate", run_id=manifest.get("review_run_id") or f"resource-review:{task.id}", summary="正在核对讲解、题目和参考资料，检查各项资源是否一致。", input_refs=[f"artifact-version:{step.output_artifact_version_id}" for step in latest.values() if step.output_artifact_version_id], progress=0.78, retryable=True)
                candidates = _candidate_resources(db, task, latest)
                try:
                    review_history = db.query(DBTaskEvent).filter(DBTaskEvent.task_id == task.id,
                        DBTaskEvent.event_type.in_({'resource_generation.review_result',
                            'resource_generation.review_adjudicated'})).order_by(DBTaskEvent.sequence).all()
                    pending_findings = unresolved_review_findings(
                        [(row.event_type, row.payload or {}) for row in review_history], candidates)
                    review_dependencies = list({item["version_id"]: item for item in [*planning_dependencies, *_frozen_practical_dependencies(db, candidates)]}.values())
                    completed_reviews = {
                        row.payload["input_hash"]: row.payload["review"]
                        for row in db.query(DBTaskEvent).filter_by(
                            task_id=task.id, event_type="resource_generation.review_group_result").all()
                        if isinstance(row.payload, dict) and row.payload.get("input_hash") and isinstance(row.payload.get("review"), dict)
                    }

                    def save_review_group(input_hash, result):
                        if was_cancelled():
                            raise ResourceBundleError("resource_generation.cancelled", "本次执行已停止。")
                        append_task_event(db, task_id=task.id, event_type="resource_generation.review_group_result",
                                          payload={"input_hash": input_hash, "review": result})
                        db.commit()

                    def publish_independent(candidate, result):
                        if (not task.automation_state or result.get("approved") is not True
                                or result.get("rejectedTypes") or was_cancelled()):
                            return
                        if any(finding.get('version_id') == candidate['version_id'] for finding in pending_findings):
                            return
                        version = db.get(DBArtifactVersion, candidate["version_id"])
                        artifact = db.get(DBArtifact, version.artifact_id) if version else None
                        if not artifact or artifact.current_version_id != version.id:
                            return
                        item = next(item for item in manifest["items"] if item["type"] == candidate["type"])
                        _generation_source_snapshots(db, task=task, manifest=manifest, item=item,
                                                     resource_type=candidate["type"])
                        ref = f"{artifact.id}:{version.id}"
                        if any(ref in (row.payload or {}).get("output_refs", []) for row in
                               db.query(DBTaskEvent).filter_by(task_id=task.id, event_type="resource.publish.completed")):
                            return
                        artifact.status = "published"
                        append_task_event(db, task_id=task.id, event_type="resource.publish.completed",
                            payload={"output_refs": [ref], "type": candidate["type"], "review": result})
                        db.commit()

                    db.commit()
                    review = loop.run_until_complete(_resource_review_async(
                        backend, manifest={**manifest, "dependency_resources": review_dependencies,
                                           "automated_calculation_check": bool(task.automation_state)},
                        semantic_plan=plan, candidates=candidates, completed_reviews=completed_reviews,
                        save_review=save_review_group,
                        on_independent_review=publish_independent,
                    ))
                    if was_cancelled():
                        return generation_job_payload(db, actor, task.id)
                    review = merge_unresolved_review(review, pending_findings)
                    append_task_event(db, task_id=task.id, event_type="resource_generation.review_result",
                                      payload={"review": review, "version_ids": [candidate["version_id"] for candidate in candidates]})
                    if task.automation_state and review.get("approved") is False and review.get("findings"):
                        from app.resource_review_adjudication import adjudicate_review
                        db.commit()
                        try:
                            review = loop.run_until_complete(adjudicate_review(backend,
                                manifest={**manifest, "dependency_resources": review_dependencies},
                                candidates=candidates, review=review, completed=completed_reviews, save=save_review_group))
                        except Exception as exc:
                            code = "resource_generation.review_adjudication_invalid" if isinstance(exc, ValueError) else "resource_generation.reviewer_failed"
                            raise ResourceBundleError(code, f"审核意见核验尚未完成：{exc}") from exc
                        if was_cancelled():
                            return generation_job_payload(db, actor, task.id)
                        append_task_event(db, task_id=task.id, event_type="resource_generation.review_adjudicated",
                            payload={"review": review, "version_ids": [candidate["version_id"] for candidate in candidates]})
                    rejected = [str(value) for value in review.get("rejectedTypes") or [] if str(value) in requested_types]
                    explicit_approved = review.get("approved")
                    approved = bool(explicit_approved) if isinstance(explicit_approved, bool) else not rejected and str(review.get("status") or "").lower() not in {"failed", "rejected"}
                    if approved and not rejected:
                        _resource_event(db, task=task, event_type="review_gate.passed" if complete_candidates else "resource_generation.partial_review.completed", status="completed", stage_id="review_gate", run_id=manifest.get("review_run_id") or f"resource-review:{task.id}", summary=str(review.get("summary") or "当前候选资源通过审核。"), output_refs=[f"artifact-version:{candidate['version_id']}" for candidate in candidates], progress=0.9, retryable=False)
                        if not complete_candidates:
                            # The full package remains unfinished. Close this
                            # review run so failed siblings can resume normally.
                            _resource_event(db, task=task, event_type="review_gate.failed", status="failed", stage_id="review_gate", summary="已完成内容通过核对，正在继续其余资源。", retryable=True)
                    else:
                        rejected = rejected or requested_types
                        reason = str(review.get("summary") or "Resource Reviewer 要求返工被拒绝的资源项。")
                        _mark_review_rejected(db, task=task, latest=latest, rejected_types=rejected, reason=reason, findings=review.get("findings"))
                        _resource_event(db, task=task, event_type="review_gate.failed", status="failed", stage_id="review_gate", run_id=manifest.get("review_run_id") or f"resource-review:{task.id}", summary=reason, output_refs=[f"artifact-version:{candidate['version_id']}" for candidate in candidates], progress=0.9, retryable=True)
                except ResourceBundleError as exc:
                    if was_cancelled():
                        return generation_job_payload(db, actor, task.id)
                    _resource_event(db, task=task, event_type="review_gate.failed", status="failed", stage_id="review_gate", run_id=manifest.get("review_run_id") or f"resource-review:{task.id}", summary=str(exc), progress=0.9, retryable=True, error_code=exc.code, error_message=str(exc))
            if _review_gate_status(db, task.id) == "passed" and not _publish_gate_done(db, task.id):
                _, latest = _task_steps(db, task.id)
                if all(step.status == "succeeded" and step.output_artifact_version_id for step in latest.values()):
                    # Sources can change while a model request is in flight.
                    for item in manifest["items"]:
                        _generation_source_snapshots(db, task=task, manifest=manifest,
                                                     item=item, resource_type=item["type"])
                    if was_cancelled():
                        return generation_job_payload(db, actor, task.id)
                    published: list[str] = []
                    for step in latest.values():
                        version = db.get(DBArtifactVersion, step.output_artifact_version_id)
                        artifact = db.get(DBArtifact, version.artifact_id) if version else None
                        if artifact is None:
                            continue
                        artifact.status = "published"
                        published.append(f"{artifact.id}:{version.id}")
                    _resource_event(db, task=task, event_type="publish.completed", status="completed", stage_id="publish_gate", summary="内容已核对，可以打开资源开始学习。", output_refs=published, progress=1.0, retryable=False)
                    _resource_event(db, task=task, event_type="run.completed", status="completed", summary="本次学习资源已准备完成。", output_refs=published, progress=1.0, retryable=False)
        _, final_latest = _task_steps(db, task.id)
        if (
            any(step.status == "failed" for step in final_latest.values())
            or _review_gate_status(db, task.id) == "failed"
        ):
            ensure_run_failed("本次学习资源尚未准备完成，请重试需要调整的内容。")
        _sync_generation_task(db, task)
    except ResourceBundleError as exc:
        if was_cancelled():
            return generation_job_payload(db, actor, task.id)
        if not _generation_plan(db, task.id):
            _resource_event(
                db,
                task=task,
                event_type="stage.failed",
                status="failed",
                stage_id="resource_planner",
                run_id=manifest.get("planner_run_id") or f"resource-plan:{task.id}",
                summary=str(exc),
                retryable=True,
            )
            _, pending_steps = _task_steps(db, task.id)
            for resource_type in requested_types:
                sequence = GENERATION_RESOURCE_TYPES.index(resource_type) + 1
                step = pending_steps.get(sequence)
                if step and step.status in {"queued", "retry_queued", "requested", "running"}:
                    fail_generation_item(db, actor, task.id, resource_type, error_code=exc.code, error_message=str(exc))
                    _resource_event(db, task=task, event_type="resource.item.failed", resource_type=resource_type, status="failed", summary=str(exc), step=step, retryable=True)
        _resource_event(db, task=task, event_type="run.failed", status="failed", summary=str(exc), retryable=True,
                        error_code=exc.code, error_message=str(exc))
        _sync_generation_task(db, task)
    finally:
        loop.close()
        _RESOURCE_EVENT_CALLBACK.reset(callback_token)
        _RESOURCE_PARTS.reset(parts_token)
        if previous_loop is not None and not previous_loop.is_closed():
            asyncio.set_event_loop(previous_loop)
        else:
            asyncio.set_event_loop(None)
    return generation_job_payload(db, actor, task.id)


def execute_generation_job_demo(db: Any, actor: DBUser, task_id: str) -> dict[str, Any]:
    """Execute queued resource steps through the existing artifact protocol."""
    task = _generation_task(db, actor, task_id)
    if task.status == "cancelled":
        _fail("resource_generation.demo_cancelled", "已取消任务不能执行")
    if task.status == "completed":
        return generation_job_payload(db, actor, task.id)
    manifest = _generation_manifest(db, task.id)
    _, latest = _task_steps(db, task.id)
    append_task_event(
        db,
        task_id=task.id,
        event_type="resource_generation.demo_execution.started",
        payload={"mode": "deterministic_demo"},
    )
    requested_types = list(_manifest_resource_types(manifest))
    execution_types = [item for item in requested_types if item != "training_task"]
    if "training_task" in requested_types:
        execution_types.append("training_task")
    for resource_type in execution_types:
        sequence = GENERATION_RESOURCE_TYPES.index(resource_type) + 1
        step = latest.get(sequence)
        if step is None or step.status in {"succeeded", "cancelled", "failed"}:
            continue
        item = _step_input(step)
        try:
            if step.status != "running":
                mark_generation_item_running(db, actor, task.id, resource_type)
                _, latest = _task_steps(db, task.id)
                step = latest[sequence]
            source_snapshots = _generation_source_snapshots(
                db,
                task=task,
                manifest=manifest,
                item=item,
                resource_type=resource_type,
            )
            linked_resource_ids: list[str] = []
            if resource_type == "mind_map":
                for previous_step in latest.values():
                    if previous_step.sequence >= step.sequence or not previous_step.output_artifact_version_id:
                        continue
                    previous_version = db.get(DBArtifactVersion, previous_step.output_artifact_version_id)
                    if previous_version is not None:
                        linked_resource_ids.append(previous_version.artifact_id)
            elif resource_type == "training_task":
                for linked_type in ("code_sandbox", "interactive_model"):
                    linked_step = latest.get(GENERATION_RESOURCE_TYPES.index(linked_type) + 1)
                    linked_version = (
                        db.get(DBArtifactVersion, linked_step.output_artifact_version_id)
                        if linked_step and linked_step.output_artifact_version_id
                        else None
                    )
                    if linked_version is not None:
                        linked_resource_ids.append(linked_version.artifact_id)
            content = (
                _create_quiz_resource_content(
                    db,
                    actor=actor,
                    task=task,
                    item=item,
                    manifest=manifest,
                    source_snapshots=source_snapshots,
                )
                if resource_type == "quiz"
                else _deterministic_demo_content(
                    resource_type=resource_type,
                    item=item,
                    manifest=manifest,
                    source_snapshots=source_snapshots,
                    linked_resource_ids=linked_resource_ids,
                )
            )
            complete_generation_item(
                db,
                actor,
                task.id,
                resource_type,
                content=content,
                content_format=(
                    "json"
                    if resource_type in {"handout", "mind_map", "quiz", "training_task", "code_sandbox", "video", "deck", "interactive_model"}
                    else "markdown"
                ),
            )
        except ResourceBundleError as exc:
            fail_generation_item(
                db,
                actor,
                task.id,
                resource_type,
                error_code=exc.code,
                error_message=str(exc),
            )
            latest = _task_steps(db, task.id)[1]
    append_task_event(
        db,
        task_id=task.id,
        event_type="resource_generation.demo_execution.finished",
        payload={"mode": "deterministic_demo"},
    )
    _sync_generation_task(db, task)
    return generation_job_payload(db, actor, task.id)


def mark_generation_item_running(db: Any, actor: DBUser, task_id: str, resource_type: str) -> dict[str, Any]:
    task = _generation_task(db, actor, task_id)
    if resource_type not in GENERATION_RESOURCE_TYPES:
        _fail("resource_generation.type_invalid", "资源类型不受支持")
    _, latest = _task_steps(db, task.id)
    step = latest.get(GENERATION_RESOURCE_TYPES.index(resource_type) + 1)
    if step is None:
        _fail("resource_generation.item_unknown", "资源生成项不存在")
    if step.status == "succeeded":
        return generation_job_payload(db, actor, task.id)
    if step.status not in {"queued", "retry_queued", "requested"}:
        _fail("resource_generation.state_conflict", "当前资源项不能开始生成")
    step.status = "running"
    step.started_at = step.started_at or _utcnow()
    append_task_event(db, task_id=task.id, step_id=step.id, event_type="resource_generation.item.running", payload={"type": resource_type, "attempt": step.attempt})
    _sync_generation_task(db, task)
    return generation_job_payload(db, actor, task.id)


def complete_generation_item(
    db: Any,
    actor: DBUser,
    task_id: str,
    resource_type: str,
    *,
    content: str,
    content_format: str = "markdown",
    generation_mode: str = "deterministic_fallback",
    model: str = "deterministic",
    reasoning_effort: str = "",
    training_dependencies: list[dict[str, Any]] | None = None,
    practical_dependencies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    task = _generation_task(db, actor, task_id)
    if resource_type not in GENERATION_RESOURCE_TYPES:
        _fail("resource_generation.type_invalid", "资源类型不受支持")
    _, latest = _task_steps(db, task.id)
    step = latest.get(GENERATION_RESOURCE_TYPES.index(resource_type) + 1)
    if step is None:
        _fail("resource_generation.item_unknown", "资源生成项不存在")
    if step.status == "succeeded":
        return generation_job_payload(db, actor, task.id)
    if step.status not in {"queued", "retry_queued", "running", "requested"}:
        _fail("resource_generation.state_conflict", "当前资源项不能完成")
    clean_content = content.strip()
    if not clean_content:
        _fail("resource_generation.content_required", "生成内容不能为空")
    if content_format not in {"markdown", "json", "text", "html", "python"}:
        _fail("resource_generation.content_format", "生成内容格式不受支持")
    question_version_ids: list[str] = []
    if resource_type == "quiz" and content_format == "json":
        try:
            quiz_payload = json.loads(clean_content)
            question_version_ids = [
                str(question.get("questionVersionId") or "")
                for question in quiz_payload.get("questions", [])
                if isinstance(question, dict) and str(question.get("questionVersionId") or "")
            ]
        except (json.JSONDecodeError, AttributeError):
            _fail("resource_generation.quiz_content_invalid", "测验题资源内容必须是有效的结构化 JSON")
    structured_completion_rule = ""
    if resource_type == "interactive_model":
        if content_format != "json":
            _fail("resource_generation.interactive_model_content_format", "可交互模型必须使用结构化 JSON")
        try:
            structured_completion_rule = parse_interactive_model_content(clean_content).completionRule
        except ValueError as exc:
            _fail("resource_generation.interactive_model_content_invalid", str(exc))
    if resource_type == "code_sandbox":
        if content_format != "json":
            _fail("resource_generation.code_sandbox_content_format", "代码沙盒必须使用结构化 JSON")
        try:
            parsed_code = parse_code_sandbox_content(clean_content)
            structured_completion_rule = parsed_code.completionRule
            # Authored revisions use the same runtime contract as model output.
            from app.code_sandbox import local_module_roots
            local_modules = local_module_roots(parsed_code.files)
            for code_file in parsed_code.files:
                code_issue = validate_code(code_file.content, local_modules=local_modules)
                if code_issue:
                    _fail("resource_generation.code_sandbox_content_invalid", f"{code_file.path}: {code_issue}")
        except ValueError as exc:
            _fail("resource_generation.code_sandbox_content_invalid", str(exc))
    if resource_type == "training_task" and training_dependencies:
        # A revision can retain the old task body while replacing companions.
        # Persist the learner's links and the frozen review bindings together.
        try:
            training_payload = json.loads(clean_content)
        except (ValueError, TypeError):
            _fail("resource_generation.training_task_invalid", "实训任务必须使用结构化 JSON")
        for dependency in training_dependencies:
            field = {"code_sandbox": "linkedSandboxId", "interactive_model": "linkedModelId"}.get(dependency["type"])
            if not field:
                continue
            linked = db.get(DBArtifactVersion, dependency["version_id"])
            artifact = db.get(DBArtifact, dependency["resource_id"])
            if (not linked or not artifact or linked.artifact_id != artifact.id
                    or artifact.owner_public_id != actor.public_id or artifact.course_id != task.course_id
                    or artifact.artifact_type != dependency["type"]):
                _fail("resource_generation.training_dependency_invalid", "实训配套版本与当前课程不对应，请重新选择配套资源。")
            training_payload[field] = artifact.id
        clean_content = _canonical(training_payload)
    manifest = _generation_manifest(db, task.id)
    item = _step_input(step)
    requested_rule = " ".join(str(item.get("completion_rule") or "").split())
    content_rule = " ".join(structured_completion_rule.split())
    if requested_rule and content_rule and requested_rule != content_rule:
        _fail("resource_generation.completion_rule_mismatch", "生成内容的完成条件与本次学习要求不一致，请重新生成该资源。")
    source_snapshots = _source_snapshots(
        db,
        course_id=task.course_id,
        source_ref_ids=list(item.get("source_ref_ids") or []),
        require_available=True,
    )
    version_metadata = _version_generation_metadata(
        manifest=manifest,
        resource_type=resource_type,
        source_snapshots=source_snapshots,
        content=clean_content,
        question_version_ids=question_version_ids,
        task_id=task.id,
        attempt=step.attempt,
        completion_rule=requested_rule or content_rule,
        generation_mode=generation_mode,
        model=model,
        reasoning_effort=reasoning_effort,
    )
    if resource_type == "training_task" and training_dependencies:
        version_metadata["training_dependencies"] = [
            {key: dep[key] for key in ("type", "resource_id", "version_id", "source_ref_ids")}
            for dep in training_dependencies
        ]
    if practical_dependencies:
        version_metadata["practical_dependencies"] = [
            {key: dep[key] for key in ("type", "resource_id", "version_id", "source_ref_ids")}
            for dep in practical_dependencies
        ]
    artifact, version = create_artifact_with_version(
        db,
        owner_public_id=actor.public_id,
        course_id=task.course_id,
        artifact_type=resource_type,
        title=str(item.get("title") or resource_type),
        content=clean_content,
        content_format=content_format,
        creating_task_id=task.id,
        metadata=version_metadata,
    )
    _attach_canonical_binding_identity(
        db,
        artifact=artifact,
        version=version,
        resource_type=resource_type,
        content=clean_content,
    )
    artifact.status = "approved"
    step.status = "succeeded"
    step.output_artifact_version_id = version.id
    step.error_code = ""
    step.error_message = ""
    step.completed_at = _utcnow()
    append_task_event(
        db,
        task_id=task.id,
        step_id=step.id,
        event_type="resource_generation.item.succeeded",
        payload={"type": resource_type, "attempt": step.attempt, "resource_id": artifact.id, "version_id": version.id},
    )
    _sync_generation_task(db, task)
    return generation_job_payload(db, actor, task.id)


def fail_generation_item(
    db: Any,
    actor: DBUser,
    task_id: str,
    resource_type: str,
    *,
    error_code: str,
    error_message: str,
) -> dict[str, Any]:
    task = _generation_task(db, actor, task_id)
    if resource_type not in GENERATION_RESOURCE_TYPES:
        _fail("resource_generation.type_invalid", "资源类型不受支持")
    _, latest = _task_steps(db, task.id)
    step = latest.get(GENERATION_RESOURCE_TYPES.index(resource_type) + 1)
    if step is None:
        _fail("resource_generation.item_unknown", "资源生成项不存在")
    if step.status == "succeeded":
        _fail("resource_generation.state_conflict", "已成功资源不能改为失败")
    if step.status not in {"queued", "retry_queued", "running", "requested"}:
        _fail("resource_generation.state_conflict", "当前资源项不能标记为失败")
    step.status = "failed"
    step.error_code = str(error_code)[:64]
    step.error_message = str(error_message)
    step.completed_at = _utcnow()
    append_task_event(db, task_id=task.id, step_id=step.id, event_type="resource_generation.item.failed", payload={"type": resource_type, "attempt": step.attempt, "error_code": step.error_code})
    _sync_generation_task(db, task)
    return generation_job_payload(db, actor, task.id)


def _generation_retry_input(previous: DBTaskStep) -> dict[str, Any]:
    previous_input = _step_input(previous)
    content_errors = {
        "resource_generation.review_rejected", "resource_generation.model_output_invalid",
        "resource_generation.handout_invalid", "resource_generation.mind_map_invalid",
        "resource_generation.training_task_invalid", "resource_generation.code_sandbox_invalid",
        "resource_generation.interactive_model_invalid", "resource_generation.deck_invalid",
        "resource_generation.quiz_content_invalid", "resource_generation.interactive_model_content_invalid",
        "resource_generation.code_sandbox_content_invalid",
        "resource_generation.interactive_model_template_mismatch",
        "resource_generation.video_selection_invalid", "resource_generation.video_topic_mismatch",
    }
    # Transport/search failures keep the same candidate and completed sections.
    # A rejected structure, like a review finding, must reach the next generator
    # and change its cache key; otherwise retry repeats the identical invalid draft.
    feedback = previous.error_message if (previous.error_code in content_errors
        or previous.error_code.endswith(("_invalid", "_mismatch", "output_limit"))) else ""
    return {**previous_input, "revision_feedback": feedback or str(previous_input.get("revision_feedback") or "")}


def revise_generation_job(
    db: Any, actor: DBUser, task_id: str, *, feedback: str,
    resource_types: list[str], idempotency_key: str,
    active_requirements: dict[str, Any] | None = None,
    review_decisions: list[dict[str, Any]] | None = None,
    source_ref_ids_by_type: dict[str, list[str]] | None = None,
    preserve_plan: bool = False,
    preserve_learning_basis: bool = False,
) -> dict[str, Any]:
    """Revise teaching within the existing task, preserving every original version."""
    task = _generation_task(db, actor, task_id)
    try:
        active_requirements = requirements_snapshot(active_requirements)
    except ValueError as exc:
        _fail("resource_generation.revision_invalid", str(exc))
    feedback = str(feedback or "").strip()
    requested = list(dict.fromkeys(resource_types))
    source_updates = source_ref_ids_by_type or {}
    if set(source_updates) - set(requested):
        _fail("resource_generation.revision_invalid", "请同时选择要更新来源的资源。")
    if not feedback or not str(idempotency_key).strip() or (not requested and active_requirements is None and review_decisions is None):
        _fail("resource_generation.revision_invalid", "请说明需要调整的内容，并选择对应资源。")
    previous_requests = db.query(DBTaskEvent).filter(DBTaskEvent.task_id == task.id,
        DBTaskEvent.event_type.in_({"resource_generation.revision.requested", "resource_generation.review.amended"})).all()
    duplicate = next((row for row in previous_requests if row.payload.get("idempotency_key") == idempotency_key), None)
    if duplicate:
        requirement_key = "requested_active_requirements" if duplicate.event_type == "resource_generation.review.amended" else "active_requirements"
        decisions_key = "requested_review_decisions" if duplicate.event_type == "resource_generation.review.amended" else "review_decisions"
        if (duplicate.payload.get("feedback") != feedback or duplicate.payload.get("requested_types") != requested
                or duplicate.payload.get(requirement_key) != active_requirements
                or duplicate.payload.get(decisions_key) != review_decisions
                or bool(duplicate.payload.get('preserve_learning_basis')) != preserve_learning_basis
                or (duplicate.payload.get("source_ref_ids_by_type") or {}) != source_updates):
            _fail("resource_generation.idempotency_conflict", "这次调整已对应其他内容，请刷新后再操作。")
        return generation_job_payload(db, actor, task.id)
    _, latest = _task_steps(db, task.id)
    if task.status == "cancelled" or task.status in {"running", "queued"} or any(
        step.status in {"requested", "queued", "retry_queued", "running"} for step in latest.values()
    ) or _review_gate_status(db, task.id) == "running":
        _fail("resource_generation.revision_conflict", "本次内容还在处理中，请完成后再调整。")
    old_manifest = _generation_manifest(db, task.id)
    allowed = set(_manifest_resource_types(old_manifest))
    if set(requested) - allowed:
        _fail("resource_generation.type_invalid", "只能调整本次任务已有的资源。")
    revised_sources = {kind: _source_snapshots(db, course_id=task.course_id,
        source_ref_ids=refs, require_available=True) for kind, refs in source_updates.items()}
    if not requested:
        # Correct a review premise without making the learner regenerate correct
        # resources. This is a new review request, never a reviewer approval.
        if any(not step.output_artifact_version_id or step.status not in {"succeeded", "failed"}
               or (step.status == "failed" and step.error_code != "resource_generation.review_rejected")
               for step in latest.values()):
            _fail("resource_generation.revision_conflict", "请先完成尚未生成的内容，再重新核对要求。")
        effective_requirements = active_requirements or old_manifest.get("active_requirements")
        effective_decisions = review_decisions if review_decisions is not None else old_manifest.get("review_decisions", [])
        append_task_event(db, task_id=task.id, event_type="resource_generation.review.amended",
            payload={"idempotency_key": idempotency_key, "feedback": feedback, "requested_types": [],
                     "preserve_learning_basis": preserve_learning_basis,
                     "active_requirements": effective_requirements, "review_decisions": effective_decisions,
                     "requested_active_requirements": active_requirements, "requested_review_decisions": review_decisions,
                     "version_ids": [step.output_artifact_version_id for step in latest.values()]})
        for step in latest.values():
            if step.status == "failed":
                step.status = "succeeded"
                step.error_code = ""
                step.error_message = ""
        task.completed_at = None
        _sync_generation_task(db, task)
        return generation_job_payload(db, actor, task.id)
    selected = set(requested)
    if selected.intersection({"code_sandbox", "interactive_model"}) and "training_task" in allowed:
        selected.add("training_task")
    # A saved resource rejected by review still has usable generation output.
    # Keep it for the pending review, including a corrected review premise;
    # selecting another resource must not silently regenerate this one.
    # Generation failures without a completed draft remain failed until retried.
    for sequence, step in latest.items():
        if (GENERATION_RESOURCE_TYPES[sequence - 1] not in selected
                and step.status == "failed"
                and step.error_code == "resource_generation.review_rejected"
                and step.output_artifact_version_id):
            step.status = "succeeded"
            step.error_code = ""
            step.error_message = ""
    retained = []
    previous_versions = {}
    for sequence, step in latest.items():
        kind = GENERATION_RESOURCE_TYPES[sequence - 1]
        version = db.get(DBArtifactVersion, step.output_artifact_version_id) if step.output_artifact_version_id else None
        if version:
            previous_versions[kind] = version.id
            if kind not in selected:
                retained.append({"type": kind, "version_id": version.id,
                    "content": _resource_review_content(db, version, kind)})
    old_context = dict(old_manifest.get("context") or {})
    revised_items = [
        {**item, "completion_rule": resource_completion_rule(item["type"], item.get("completion_rule", "")),
         "source_ref_ids": list(source_updates.get(item["type"], item.get("source_ref_ids", [])))}
        if item["type"] in selected else dict(item)
        for item in old_manifest["items"]
    ]
    profile = _profile_snapshot(db, actor, old_manifest["profile_snapshot_id"], course_id=task.course_id)
    course = _course(db, actor, task.course_id)
    if preserve_learning_basis and old_context:
        # Repair the submitted task against its saved learner evidence. Learning
        # in another resource must not change its scaffolding or completed parts.
        # Source replacement is still explicit and remains independently bound.
        context = {**old_context, 'course_title': course.title,
                   'source_count': len({ref for item in revised_items for ref in item.get('source_ref_ids', [])})}
    else:
        context = _generation_context_snapshot(db, actor=actor, course=course,
            point=_knowledge_point(db, task.course_id, old_manifest.get("knowledge_point_id")), profile=profile,
            learning_goal=old_context.get("learning_goal", ""), items=revised_items)
    for key in ("teaching_scope", "path_learning_context", "knowledge_point_title", "conversation_source"):
        if key in old_context:
            context[key] = old_context[key]
    source_snapshots = {**(old_manifest.get("input_snapshot") or {}).get("source_snapshots", {}),
                        **revised_sources}
    input_snapshot = _generation_input_snapshot(context=context, profile=profile,
        source_snapshots_by_type=source_snapshots)
    task_evidence = dict((old_manifest.get("input_snapshot") or {}).get("task_evidence") or {})
    if revised_sources:
        for kind in revised_sources:
            task_evidence.pop(kind, None)
        task_evidence.update(_generation_task_evidence(db, actor=actor, course_id=task.course_id,
            context=context, sources_by_type=revised_sources,
            user_instruction=old_manifest.get("user_instruction") or ""))
    if task_evidence:
        input_snapshot["task_evidence"] = task_evidence
    revision = {"feedback": feedback, "resource_types": [kind for kind in _manifest_resource_types(old_manifest) if kind in selected],
        "previous_manifest_hash": old_manifest.get("manifest_hash"),
        "previous_plan": _generation_plan(db, task.id).get("plan", ""),
        "previous_versions": previous_versions, "retained_resources": retained}
    input_snapshot["input_snapshot_hash"] = _sha256_json({"input": input_snapshot, "revision": revision})
    manifest = {**old_manifest, "items": revised_items, "context": context, "input_snapshot": input_snapshot, "teaching_revision": revision,
                "active_requirements": active_requirements or old_manifest.get("active_requirements"),
                "requirements_explicit": active_requirements is not None,
                "review_decisions": review_decisions if review_decisions is not None else old_manifest.get("review_decisions", [])}
    if manifest.get('active_requirements') and active_requirements is None:
        manifest['active_requirements'] = {key: value for key, value in manifest['active_requirements'].items()
                                           if key != 'source_request'}
    if manifest.get("active_requirements"):
        manifest.pop("teaching_revision_history", None)
    manifest.pop("manifest_hash", None)
    manifest["manifest_hash"] = _sha256_json(manifest)
    for kind in revision["resource_types"]:
        previous = latest[GENERATION_RESOURCE_TYPES.index(kind) + 1]
        item = _generation_retry_input(previous)
        item["completion_rule"] = next(spec["completion_rule"] for spec in revised_items if spec["type"] == kind)
        item["source_ref_ids"] = next(spec["source_ref_ids"] for spec in revised_items if spec["type"] == kind)
        item["revision_feedback"] = feedback
        step = create_task_step(db, task_id=task.id, sequence=previous.sequence, attempt=previous.attempt + 1,
            agent_role=previous.agent_role, tool_name=previous.tool_name,
            input_summary=json.dumps(item, ensure_ascii=False))
        step.status = "retry_queued"
    append_task_event(db, task_id=task.id, event_type="resource_generation.revision.requested",
        payload={"idempotency_key": idempotency_key, "feedback": feedback, "requested_types": requested,
                 "preserve_plan": preserve_plan,
                 "preserve_learning_basis": preserve_learning_basis,
                 "active_requirements": active_requirements, "review_decisions": review_decisions,
                 "source_ref_ids_by_type": source_updates,
                 "manifest": manifest, "previous_versions": previous_versions})
    task.completed_at = None
    _sync_generation_task(db, task)
    return generation_job_payload(db, actor, task.id)


def retry_generation_item(db: Any, actor: DBUser, task_id: str, resource_type: str) -> dict[str, Any]:
    task = _generation_task(db, actor, task_id)
    if resource_type not in GENERATION_RESOURCE_TYPES:
        _fail("resource_generation.type_invalid", "资源类型不受支持")
    sequence = GENERATION_RESOURCE_TYPES.index(resource_type) + 1
    _, latest = _task_steps(db, task.id)
    previous = latest.get(sequence)
    if previous is None or previous.status != "failed":
        _fail("resource_generation.retry_conflict", "只有失败项可以单独重试")
    step = create_task_step(
        db,
        task_id=task.id,
        sequence=sequence,
        attempt=previous.attempt + 1,
        agent_role=previous.agent_role,
        tool_name=previous.tool_name,
        input_summary=json.dumps(_generation_retry_input(previous), ensure_ascii=False),
    )
    step.status = "retry_queued"
    task.completed_at = None
    append_task_event(db, task_id=task.id, step_id=step.id, event_type="resource_generation.item.retry_queued", payload={"type": resource_type, "attempt": step.attempt})
    _sync_generation_task(db, task)
    return generation_job_payload(db, actor, task.id)


def recover_generation_job(db: Any, actor: DBUser, task_id: str) -> dict[str, Any]:
    task = _generation_task(db, actor, task_id)
    if task.status == "cancelled":
        _fail("resource_generation.recovery_conflict", "已取消任务不能恢复")
    if task.status == "completed":
        _fail("resource_generation.recovery_conflict", "已完成任务不需要恢复")
    _, latest = _task_steps(db, task.id)
    recoverable = [
        (sequence, previous)
        for sequence, previous in sorted(latest.items())
        if previous.status in {"running", "failed"}
    ]
    review_failed = bool(latest) and all(step.status == "succeeded" for step in latest.values()) and _review_gate_status(db, task.id) == "failed"
    if not recoverable and not review_failed:
        _fail("resource_generation.recovery_conflict", "当前任务没有可恢复的中断项")
    recovered: list[str] = []
    for sequence, previous in recoverable:
        resource_type = GENERATION_RESOURCE_TYPES[sequence - 1]
        step = create_task_step(
            db,
            task_id=task.id,
            sequence=sequence,
            attempt=previous.attempt + 1,
            agent_role=previous.agent_role,
            tool_name=previous.tool_name,
            input_summary=json.dumps(_generation_retry_input(previous), ensure_ascii=False),
        )
        step.status = "retry_queued"
        recovered.append(resource_type)
    task.completed_at = None
    append_task_event(db, task_id=task.id, event_type="resource_generation.recovered", payload={"recovered_types": recovered})
    _sync_generation_task(db, task)
    return generation_job_payload(db, actor, task.id)


def cancel_generation_job(db: Any, actor: DBUser, task_id: str) -> dict[str, Any]:
    task = _generation_task(db, actor, task_id)
    if task.status == "completed":
        _fail("resource_generation.cancel_conflict", "已完成任务不能取消")
    _, latest = _task_steps(db, task.id)
    for step in latest.values():
        if step.status != "succeeded":
            step.status = "cancelled"
            step.completed_at = _utcnow()
    task.status = "cancelled"
    if task.automation_state:
        task.automation_state = "cancelled"
        task.execution_token = None
        task.lease_expires_at = None
        task.next_attempt_at = None
    task.completed_at = _utcnow()
    append_task_event(db, task_id=task.id, event_type="resource_generation.cancelled", payload={})
    db.flush()
    return generation_job_payload(db, actor, task.id)
