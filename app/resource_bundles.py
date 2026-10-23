from __future__ import annotations

import hashlib
import json
import asyncio
import math
import re
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from app.database import (
    DBAssessmentQuestion, DBAssessmentQuestionVersion, DBArtifact, DBArtifactVersion,
    DBChapter, DBChapterKnowledgePoint, DBCourse, DBCourseMembership,
    DBGenerationTask, DBKnowledgePoint, DBLearningEvent, DBProfileSnapshot, DBStudentProfile, DBResourceBundle,
    DBResourceBundleItem, DBResourceBundleVersion,
    DBTaskEvent, DBTaskStep, DBTeachingAnimation, DBTeachingAnimationVersion, DBUser,
    DBVideoOutputVersion, DBVideoProject, DBVideoScriptVersion, DBWebDeck,
    DBWebDeckVersion,
)
from app.interactive_lab import LAB_INSTANCE_TYPE, LabTemplate, get_template
from app.code_sandbox import validate_code
from app.exam_gate import freeze_exam_gate_snapshot
from app.authorization import ObjectAccess, active_course_role, can_access_object
from app.m1_repository import (
    append_task_event,
    create_artifact_with_version,
    create_generation_task,
    create_task_step,
)
from app.m5_assessment_core import QuestionVersionInput, create_question_version, learner_safe_explanation
from app.learner_output import teacher_text
from app.m5_resources import (
    canonical_resource_type,
    parse_code_sandbox_content,
    parse_deck_content,
    parse_handout_content,
    parse_interactive_model_content,
    parse_mindmap_content,
    parse_quiz_content,
    parse_video_recommendation_content,
)
from app.training_tasks import parse_training_task_content
from app.source_refs import project_source_ref
from app.profile_adaptation import build_profile_adaptation, profile_has_signal, profile_prompt_context
from llm_client import build_async_llm, parse_json_object


_HANDOUT_META_SENTENCE = re.compile(
    r"(?:请(?:求)?输出[^。！？\n]{0,60}[，,:：]\s*)?"
    r"(?:直接把|围绕|将|把)\s*(?:当前知识点|目标知识点|这个知识点)[^。！？\n]{0,180}"
    r"(?:要求说明|请说明|要求比较|请比较|输出|返回)[^。！？\n]*(?:[。！？]|$)"
)
_HANDOUT_META_INLINE = re.compile(
    r"(?:只输出|仅输出|请输出|返回一个|返回内容|输出内容|字段(?:包括|为)|JSON\s*(?:对象|格式)?|"
    r"handoutSections|learner_adaptation|source_ref_ids|sourceRefIds|提示词|生成规则|模型提示)"
    r"[^。！？\n]{0,140}(?:[。！？]|$)",
    flags=re.IGNORECASE,
)


def _handout_text(value: Any, *, preserve_boundary: bool = False) -> str:
    """Project model prose into a lesson, dropping instruction leakage only."""

    text = teacher_text(value, preserve_boundary=preserve_boundary)
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
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text if preserve_boundary else text.strip()


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
    knowledge_text = str(knowledge_point or "").casefold()
    text = f"{knowledge_text} {source_text}".casefold()
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
    # Only fall back to source evidence after the explicit title has been
    # checked.  This keeps legacy demo knowledge points compatible while
    # making current-course intent deterministic.
    if any(term in text for term in ("rag", "检索", "重排", "embedding", "top-k", "top k", "retrieval")):
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
        overall = body.get("course_mastery") or body.get("overall_mastery") or body.get("mastery_summary")
        if overall not in (None, "", [], {}):
            return f"课程级掌握摘要：{_display_text(overall, limit=220)}。"
        return "当前未绑定具体知识点，资源将依据课程范围和学习画像安排从基础到应用的难度。"
    mastery = body.get("concept_mastery") or body.get("mastery") or {}
    traces = body.get("knowledge_traces") or {}
    candidates = (point.id, point.title, point.code)
    value: Any = None
    if isinstance(mastery, dict):
        value = next((mastery.get(key) for key in candidates if key and key in mastery), None)
    if value is None and isinstance(traces, dict):
        trace = next((traces.get(key) for key in candidates if key and key in traces), None)
        if isinstance(trace, dict):
            value = trace.get("mastery")
        elif trace is not None:
            value = trace
    if isinstance(value, (int, float)):
        percent = max(0, min(100, round(float(value) * 100)))
        if percent < 60:
            guidance = "当前仍需重点巩固"
        elif percent < 80:
            guidance = "已有基础，适合通过练习和实验加深理解"
        else:
            guidance = "基础较稳，可增加迁移应用和解释任务"
        return f"画像记录的当前掌握度约为 {percent}%，{guidance}。"
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
    rows = (
        db.query(DBLearningEvent)
        .filter_by(owner_public_id=actor.public_id, course_id=course_id)
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
    body = dict(profile.snapshot or {})
    fallback_goal = _display_text(_profile_value(body, "goal", "learning_goal", "learning_goals"), limit=320)
    point_title = point.title if point is not None else "当前课程内容"
    clean_goal = " ".join(str(learning_goal or fallback_goal or f"理解并应用{point_title}").split())[:512]
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
        profile,
        profile=profile_row,
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
    return {
        "course_title": course.title,
        "knowledge_point_title": point_title,
        "learning_goal": clean_goal,
        "profile_adaptation": adaptation.get("summary") or "当前没有可用画像，资源按课程目标组织。",
        "profile_snapshot_id": profile.id,
        "profile_version": profile.profile_version,
        "profile_influence": profile_influence_summary(profile),
        "mastery_summary": mastery_summary,
        "profile_adaptation_plan": profile_prompt_context(adaptation),
        "profile_context": profile_prompt_context(adaptation),
        "recent_event_ids": recent_event_ids,
        "recent_learning_summary": recent_summary,
        "source_count": len(source_ids),
    }


def _public_generation_context(manifest: dict[str, Any]) -> dict[str, Any]:
    context = dict(manifest.get("context") or {})
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
            "profile_adaptation_plan", "profile_context",
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
        snapshots.append(projection)
    return snapshots


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
        .filter_by(task_id=task_id, event_type="resource_generation.requested")
        .order_by(DBTaskEvent.sequence)
        .first()
    )
    payload = dict(event.payload or {}) if event else {}
    return dict(payload.get("manifest") or {})


def _generation_plan(db: Any, task_id: str) -> dict[str, Any]:
    """Read the single shared semantic plan produced for this task."""
    event = (
        db.query(DBTaskEvent)
        .filter_by(task_id=task_id, event_type="resource_generation.plan.completed")
        .order_by(DBTaskEvent.sequence)
        .first()
    )
    return dict(event.payload or {}) if event else {}


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
            "summary": " ".join(str(payload.get("summary") or payload.get("message") or "").split())[:320],
            "input_refs": input_refs[:20],
            "output_refs": output_refs[:20],
            "progress": payload.get("progress"),
            "retryable": bool(payload.get("retryable", event_type in {"resource.item.failed", "review_gate.failed", "run.failed"})),
        })
    return projected


def _review_gate_status(db: Any, task_id: str) -> str:
    rows = (
        db.query(DBTaskEvent)
        .filter(DBTaskEvent.task_id == task_id, DBTaskEvent.event_type.in_({"review_gate.passed", "review_gate.failed"}))
        .order_by(DBTaskEvent.sequence.desc())
        .all()
    )
    return str(rows[0].event_type).rsplit(".", 1)[-1] if rows else "pending"


def _requires_live_gates(db: Any, task_id: str) -> bool:
    return db.query(DBTaskEvent).filter_by(
        task_id=task_id, event_type="resource_generation.demo_execution.started"
    ).first() is None


def _publish_gate_done(db: Any, task_id: str) -> bool:
    return db.query(DBTaskEvent).filter_by(task_id=task_id, event_type="publish.completed").first() is not None


def _public_generation_state(db: Any, task: DBGenerationTask, latest: dict[int, DBTaskStep]) -> str:
    if task.status == "cancelled":
        return "cancelled"
    states = [row.status for row in latest.values()]
    succeeded = states.count("succeeded")
    review_status = _review_gate_status(db, task.id)
    requires_live_gates = _requires_live_gates(db, task.id)
    if requires_live_gates and review_status == "failed":
        return "partial_success" if "failed" in states else "failed"
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


def _sync_generation_task(db: Any, task: DBGenerationTask) -> None:
    _, latest = _task_steps(db, task.id)
    states = [row.status for row in latest.values()]
    succeeded = states.count("succeeded")
    task.progress = succeeded / len(states) if states else 0.0
    if task.status == "cancelled":
        return
    review_status = _review_gate_status(db, task.id)
    requires_live_gates = _requires_live_gates(db, task.id)
    if requires_live_gates and review_status == "failed":
        task.status = "failed"
        task.failure_code = "resource_generation.review_failed"
        task.failure_reason = "资源审核门禁未通过，请仅重试被拒绝的资源项。"
        task.completed_at = _utcnow()
    elif states and succeeded == len(states) and (not requires_live_gates or (review_status == "passed" and _publish_gate_done(db, task.id))):
        task.status = "completed"
        task.completed_at = task.completed_at or _utcnow()
        task.failure_code = ""
        task.failure_reason = ""
    elif any(state in {"requested", "queued", "retry_queued", "running"} for state in states):
        task.status = "running"
        task.started_at = task.started_at or _utcnow()
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
            else "available" if sources_available
            else "source_unavailable"
        ),
        "generation_state": step.status,
        "content_ref": f"artifact-version:{version.id}",
        "route": GENERATION_ROUTES[resource_type].format(resource_id=artifact.id),
        "title": artifact.title,
    }


def generation_job_payload(db: Any, actor: DBUser, task_id: str) -> dict[str, Any]:
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
            "completion_rule": spec.get("completion_rule") or "完成资源规定的学习动作并提交结果。",
            "source_count": len(spec.get("source_ref_ids") or []),
            "state": public_state,
            "attempt": step.attempt if step else 0,
            "idempotency_key": f"{task.id}:{resource_type}",
            "checkpoint": "archived" if step and step.status == "succeeded" else "awaiting_generation",
            "failure": {
                "code": step.error_code,
                "message": step.error_message,
            } if step and step.status == "failed" else None,
            "input": spec,
            "resource": _resource_from_step(db, step) if step else None,
            "attempt_history": [{
                "attempt": row.attempt,
                "state": row.status,
                "failure_code": row.error_code,
                "failure_message": row.error_message,
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
    context_snapshot_id: str | None = None,
    selected_resource_types: list[str] | None = None,
) -> dict[str, Any]:
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
            "completion_rule": " ".join(str(raw.get("completion_rule", "")).split())[:512],
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
            gate_snapshot = freeze_exam_gate_snapshot(
                db,
                owner_public_id=actor.public_id,
                course_id=course_id,
                path_id=path_id,
                task_id=task_id,
            )
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
        "user_instruction": " ".join(str(user_instruction or "").split())[:4000],
        "context_snapshot_id": str(context_snapshot_id or "").strip() or None,
        "selected_resource_types": list(requested_types),
    }
    requested_core.update({key: value for key, value in optional_core.items() if value not in (None, "")})
    if existing_task:
        existing_core = {key: existing_manifest.get(key) for key in requested_core}
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
    manifest = {
        **requested_core,
        "context": context_snapshot,
        "input_snapshot": _generation_input_snapshot(
            context=context_snapshot,
            profile=profile,
            source_snapshots_by_type=source_snapshots_by_type,
        ),
    }
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
    return {**generation_job_payload(db, actor, task.id), "created": True}


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
    source_ref_ids = tuple(str(snapshot["source_ref_id"]) for snapshot in source_snapshots)
    mastery = str(context.get("mastery_summary") or "当前掌握证据仍在积累")
    recent = str(context.get("recent_learning_summary") or "暂无近期有效作答")
    profile_adaptation = str(context.get("profile_adaptation") or "依据当前画像组织题目顺序")
    variant = _profile_content_variant(context)
    learning_goal = str(context.get("learning_goal") or f"验证对{knowledge_point}的理解")
    live_model_payload = llm_payload is not None
    semantic_context = {
        "schema_version": "pr-02.quiz-semantic-context.v1",
        "generation_mode": "llm" if live_model_payload else "deterministic_fallback",
        "course_title": str(context.get("course_title") or "当前课程"),
        "knowledge_point_id": knowledge_point_id,
        "knowledge_point_title": knowledge_point,
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
    if live_model_payload and len(model_questions) < 3:
        _fail("resource_generation.model_output_invalid", "测验题模型输出必须包含三个有效题目。")
    if len(model_questions) >= 3:
        normalized_specs = []
        for index, question in enumerate(model_questions[:3]):
            if not isinstance(question, dict):
                continue
            options = _normalize_quiz_options(question.get("options"), position=index + 1)
            answer = str(question.get("answer") or "A").strip().upper()
            if answer not in {"A", "B", "C", "D"}:
                continue
            normalized_specs.append({
                "prompt": f"{variant['question_prefix']} {str(question.get('prompt') or '').strip()}".strip(),
                "options": options,
                "answer": answer,
                "explanation": learner_safe_explanation(
                    question.get("explanation"),
                    prompt=str(question.get("prompt") or ""),
                    options=options,
                    answer_key={"choice": answer}, question_type="single_choice",
                    knowledge_point=knowledge_point,
                ),
                "bloom": _normalize_quiz_bloom(
                    question.get("bloom"),
                    default=("remember", "understand", "apply")[index],
                    position=index + 1,
                ),
                "difficulty": variant_difficulty(_normalize_quiz_difficulty(
                    question.get("difficulty"),
                    default=0.35 + index * 0.1,
                    position=index + 1,
                )),
            })
        if len(normalized_specs) == 3 and all(item["prompt"] for item in normalized_specs):
            specs = tuple(normalized_specs)
        elif live_model_payload:
            _fail("resource_generation.model_output_invalid", "测验题模型输出的题目结构不完整。")
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
                primary_knowledge_point_id=knowledge_point_id or None,
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
        })
    return _canonical({
        "schemaVersion": "f6.quiz-resource.v1",
        "title": str(item.get("title") or _DEMO_RESOURCE_LABELS["quiz"]),
        "summary": str((llm_payload or {}).get("summary") or f"{variant['label']}：围绕“{knowledge_point}”完成三道即时练习；提交后原位查看判定、正确答案、解析和下一步。"),
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
        if variant["band"] == "foundation":
            if practical_focus == "混合检索与证据质量评估":
                standard_input = "0.65,0.35,2,0.45"
            elif any(term in knowledge_point.casefold() for term in ("二分", "binary search")):
                standard_input = "13"
        elif variant["band"] == "transfer":
            if practical_focus == "混合检索与证据质量评估":
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
        template = _interactive_template_for_knowledge_point(knowledge_point)
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
        # DeepSeek reasoning tokens and the structured resource body share the
        # provider output budget.  Keep enough room for the JSON body so a
        # valid model response is not truncated mid-string.
        # Resource payloads are long JSON documents.  Keep enough completion
        # budget for both DeepSeek reasoning and the complete structured body;
        # the previous 16k floor could truncate a valid response mid-string
        # when the course context contained many source excerpts.
        max_tokens=max(CONFIG.llm_max_tokens, 32768),
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


def _interactive_template_for_knowledge_point(knowledge_point: str) -> LabTemplate | None:
    normalized = str(knowledge_point or "").strip().casefold()
    if not normalized:
        return None
    # Exact semantic overrides prevent broad substrings from hijacking a
    # lesson.  A vector/matrix foundation can use the registry's dimensionality
    # reduction experiment; an algorithm-only topic has no honest interactive
    # template in the current lab catalogue and must be reported as such.
    if normalized in {"向量", "矩阵", "概率基础", "线性代数"} or any(term in normalized for term in ("向量、矩阵", "向量矩阵", "线性代数", "概率基础", "矩阵运算", "点积")):
        return get_template("linear-algebra-probability")
    # Explicit semantic families cover the two built-in manifests.  They run
    # before the legacy keyword scorer so a broad term such as "学习" cannot
    # hijack a more specific experiment.
    explicit_families: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("rag-hybrid-tuning", ("rag", "混合检索", "文档解析", "文档切分", "向量检索", "关键词检索", "重排")),
        ("agent-workflow", ("工具调用", "react", "agent", "智能体", "coding agent", "mcp", "skill", "工作流", "个性化学习")),
        ("attention-mechanics", ("注意力", "transformer", "qkv", "多头", "位置编码", "自注意力")),
        ("language-generation", ("自然语言处理", "预训练", "大语言模型", "语言模型", "指令微调", "偏好对齐", "生成")),
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
        ("algorithmic-problem-framing", ("人工智能、机器学习与深度学习概览", "算法问题建模")),
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
    }


def _complete_implicit_interactive_contract(
    payload: dict[str, Any],
    *,
    knowledge_point: str,
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
    template = _interactive_template_for_knowledge_point(knowledge_point)
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
    if isinstance(raw_chart, dict):
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
        "sampleCount": dataset.get("sampleCount") if isinstance(dataset.get("sampleCount"), int) and dataset.get("sampleCount") > 0 else 1,
    }
    completed = dict(payload)
    completed["dataset"] = completed_dataset
    return completed


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
        "title": str(item.get("title") or resource_type),
        "course": context,
        "learner_adaptation": _profile_adaptation_plan(context),
        "semantic_context": semantic,
        "shared_semantic_plan": str(semantic_plan or "")[:6000],
        "sources": [
            {"source_ref_id": str(source.get("source_ref_id") or ""), "title": str(source.get("title") or ""),
             "location": str(source.get("location_label") or ""), "quote": str(source.get("quote") or "")[:1200]}
            for source in source_snapshots
        ],
    }
    if resource_type == "interactive_model":
        selected_template = _interactive_template_for_knowledge_point(knowledge_point)
        safe_context["interactive_template"] = (
            _interactive_template_directory(selected_template) if selected_template else None
        )
    type_requirements = {
        "handout": (
            "handoutSections 可选但建议提供 8~10 个对象（id、title、kind、content、sourceRefIds），"
            "kind 可为 concept、figure、example、counterexample、code、review；"
            "同时可提供 transferQuestions（迁移问题数组）和 misconceptions（误区数组）。"
            "quizQuestions 的 prompt 必须是 400 字以内、只包含题干的问题，不能复述整段讲义；"
            "每题 answer 必须为 A、B、C 或 D，并且与四个选项中的正确项一致。"
            "这些字段必须是真实教学内容，不要用 placeholder。"
        ),
        "quiz": "quizQuestions 必须恰好包含三个对象，每个对象有 prompt、options（四个非空选项正文的数组，不要只返回 A/B/C/D 标签）、answer(A-D)、explanation、bloom、difficulty。",
        "training_task": "practiceSteps 必须至少包含四个对象，每个对象都有 title、instruction、expectedResult、errorGuidance；environment 和 data 必须是非空字符串数组。",
        "code_sandbox": "starterCode 必须是非空代码字符串；requiredChecks 必须是非空对象数组。每项必须包含 id、label 和 kind，kind 只能是 exit_code_zero、stdout_contains、stderr_empty、plot_count_at_least；kind=stdout_contains 时必须有非空 expectedText，kind=plot_count_at_least 时必须有正整数 minimum。",
        "interactive_model": "只使用 interactive_template 指定的 templateId。parameters 必须逐项复制该模板目录中的 key、kind、minimum、maximum、step、default、label、unit、description；不得添加、删除或改名。constraints 必须是对象数组，每项严格包含 id、title、description；dataset 必须包含 id、title、summary、sampleCount；chart 必须包含 kind、xAxisLabel、yAxisLabel、series；observationPrompt 必须是非空字符串。这些内容必须真实、具体、非 placeholder，并且 chart.series 的 key、label、unit、higherIsBetter 必须与模板 metrics 完全一致；如果 interactive_template 为 null，返回适配说明而不是虚构实验。",
        "deck": "slides 必须是非空对象数组，每项有 title，并为非标题页提供 body 或 bullets。",
        "video": "不要生成或猜测任何 URL；视频 URL 由系统提供的联网候选绑定，正文只解释课程学习目标。",
    }.get(resource_type, "")
    role_guidance = {
        "handout": "你是一位面向学生的理论教授：讲义要有背景、术语、机制/推导、示例、反例、误区、代码阅读、闭卷回忆和迁移任务。",
        "mind_map": "你是一位逻辑教师：先合并同义概念，再输出主干、前置关系、机制、应用、反例和下一步的层级节点；每个节点短而有信息量。",
        "code_sandbox": "你是一位实战助教：给完整可运行代码、输入输出、分步观察、错误解释和可迁移变式。",
        "quiz": "你是一位考查理解的教师：覆盖基础理解、应用和综合迁移，给评分标准、误区和三级提示阶梯。",
        "training_task": "你是一位实训设计师：把目标拆成由浅入深的环境、数据、步骤、检查点和交付物。",
        "deck": "你是一位课程设计师：让课件形成问题—机制—示例—边界—练习—下一步的叙事链。",
        "video": "你是一位学习顾问：只解释系统候选视频与学习目标的匹配，不生成或猜测 URL。",
        "interactive_model": "你是一位实验设计师：在模板参数契约内设计可观察的实验、限制、数据和结论问题。",
        "feynman": "你是一位教学教练：要求学习者用自己的话复述概念、条件、反例和应用，并给出自检标准。",
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
        "你是 EduMatrix 的课程资源生成模型。课程来源是优先依据；当来源不足以覆盖完整教学链时，"
        "可以使用通用基础知识补足定义、例子、反例和练习，使资源仍然有教学价值。"
        "无法由给定来源直接支持的内容必须在文本中标为‘通用拓展’，不得伪造课程事实、来源、页码或 source_ref。"
        "不得编造学生画像、掌握度或事件。只输出一个 JSON 对象，不要 Markdown、思维链或额外字段。"
        "必须把 learner_adaptation 中的 difficulty_band、scaffolding_level、explanation_style、"
        "content_focus、example_context、hint_policy 和 practice_strategy 落实到正文、例子、步骤、"
        "提示和题目难度中；不要只复述适配摘要。返回内容必须能让同一知识点在不同画像下产生可观察差异。"
        "为保证结构化响应在一次调用内完整返回，请控制输出规模：summary 不超过 120 字，"
        "narrative 不超过 2400 字，practiceSteps 恰好 4 步且每个字段不超过 220 字，"
        "handoutSections 最多 10 项，quizQuestions 恰好 3 题；代码和数组只保留完成学习目标所需内容，"
        "讲义要提供具体定义、机制、一个完整例子、至少一个边界或误区、代码阅读和迁移练习，"
        "不要把写作要求、字段名或输出格式写进 narrative、section content、step 或题目正文；"
        "不要重复课程原文或用空泛套话填充篇幅。所有学生可见字段都要像真实老师直接讲解："
        "不要提检索、上下文、来源绑定、课文、依据、约束、确定性、模型模式、生成规则或任何内部 ID、哈希和版本号。"
        "JSON 必须包含 summary、learningGoal、narrative、practiceSteps、starterCode、observationPrompt、quizQuestions；"
        "practiceSteps 必须包含四步 data/model/train/evaluate，每步有 title、instruction、expectedResult、errorGuidance。"
        f"{role_guidance}\n【旧版教学策略目录】\n{strategy_guidance}\n{type_requirements}"
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
        if _interactive_template_for_knowledge_point(knowledge_point) is None:
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
        step_resources = {
            "handout",
            "mind_map",
            "training_task",
            "code_sandbox",
            "interactive_model",
            "deck",
        }
        if resource_type in step_resources:
            steps = payload.get("practiceSteps")
            if not isinstance(steps, list) or len(steps) < 4 or any(
                not isinstance(step, dict)
                or any(
                    not str(step.get(key) or "").strip()
                    for key in ("title", "instruction", "expectedResult", "errorGuidance")
                )
                for step in (steps[:4] if isinstance(steps, list) else [])
            ):
                return "practiceSteps 必须包含四个完整步骤对象"
            if resource_type == "handout" and not str(payload.get("starterCode") or "").strip():
                return "starterCode 不能为空"
            if resource_type == "handout":
                questions = payload.get("quizQuestions")
                if not isinstance(questions, list) or len(questions) < 3:
                    return "quizQuestions 必须包含三个题目对象"
                if any(
                    not isinstance(question, dict)
                    or len(str(question.get("prompt") or "").strip()) > 400
                    or len([value for value in question.get("options") or [] if str(value).strip()]) != 4
                    or str(question.get("answer") or "").strip().upper() not in {"A", "B", "C", "D"}
                    for question in questions[:3]
                ):
                    return "handout 的 quizQuestions 需包含简洁题干、四个选项和 A-D 答案"
        if resource_type == "quiz":
            questions = payload.get("quizQuestions")
            if not isinstance(questions, list) or len(questions) < 3:
                return "quizQuestions 必须包含三个题目对象"
            if any(
                not isinstance(question, dict)
                or len(question.get("options") or []) != 4
                or str(question.get("answer") or "").upper() not in {"A", "B", "C", "D"}
                or not str(question.get("prompt") or "").strip()
                for question in questions[:3]
            ):
                return "每个 quizQuestions 题目必须有题干、四个选项和 A-D 答案"
        elif resource_type == "training_task":
            for field in ("environment", "data"):
                values = payload.get(field)
                if not isinstance(values, list) or not any(str(value or "").strip() for value in values):
                    return f"{field} 必须是非空字符串数组"
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
            if any(not str(dataset.get(key) or "").strip() for key in ("id", "title", "summary")) or not isinstance(dataset.get("sampleCount"), int) or dataset.get("sampleCount", 0) < 1:
                return "dataset 必须包含 id、title、summary、正整数 sampleCount"
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
                    or not isinstance(item.get("higherIsBetter"), bool)
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

    try:
        raw = await backend.generate(system, user, role=role)
        payload = parse_json_object(raw)
    except Exception as exc:
        # A live provider can occasionally return a truncated/ill-formed JSON
        # object even when the request itself succeeded.  Give the same real
        # model one corrective attempt; never repair the text locally or fall
        # back to deterministic content.
        if role != "resource_generator":
            raise ResourceBundleError("resource_generation.model_call_failed", f"真实模型生成失败：{exc}") from exc
        correction_system = (
            f"{system} 你上一轮返回的 JSON 无法解析（{type(exc).__name__}）。"
            "请重新完整输出一个可被标准 JSON 解析器读取的 JSON 对象；"
            "不要截断，不要 Markdown 代码围栏，不要在字符串中使用未转义的引号或换行，"
            "并严格保留所有必需字段。"
        )
        try:
            corrected_raw = await backend.generate(correction_system, user, role=role)
            payload = parse_json_object(corrected_raw)
        except Exception as corrected_exc:
            raise ResourceBundleError(
                "resource_generation.model_call_failed",
                f"真实模型生成失败：{corrected_exc}",
            ) from corrected_exc
    if role == "resource_reviewer":
        return payload
    if resource_type == "interactive_model":
        context = _public_generation_context(manifest)
        payload = _normalize_interactive_dataset(_normalize_interactive_constraints(_complete_implicit_interactive_contract(
            payload,
            knowledge_point=str(
                context.get("knowledge_point_title")
                or manifest.get("knowledge_point_id")
                or ""
            ),
        )), knowledge_point=str(
            context.get("knowledge_point_title") or manifest.get("knowledge_point_id") or ""
        ))
    issue = shape_issue(payload)
    if issue:
        correction_system = (
            f"{system} 你上一轮返回的结构不满足资源类型要求：{issue}。"
            "请只使用冻结课程上下文重新生成，并完整输出符合上述字段约束的 JSON；"
            "不得省略字段、不得使用 placeholder、不得用说明文字代替对象数组。"
        )
        try:
            corrected_raw = await backend.generate(correction_system, user, role=role)
            payload = parse_json_object(corrected_raw)
            if resource_type == "interactive_model":
                payload = _normalize_interactive_dataset(
                    _normalize_interactive_constraints(_complete_implicit_interactive_contract(
                        payload,
                        knowledge_point=str(
                            context.get("knowledge_point_title") or manifest.get("knowledge_point_id") or ""
                        ),
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
    return payload


async def _shared_semantic_plan_async(
    backend: Any,
    *,
    manifest: dict[str, Any],
    source_snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate one shared plan for every resource item in a run."""
    context = _public_generation_context(manifest)
    safe_context = {
        "course": context,
        "user_instruction": str(manifest.get("user_instruction") or "")[:4000],
        "selected_resource_types": list(manifest.get("selected_resource_types") or _manifest_resource_types(manifest)),
        "sources": [
            {
                "source_ref_id": str(source.get("source_ref_id") or ""),
                "title": str(source.get("title") or ""),
                "location": str(source.get("location_label") or ""),
                "quote": str(source.get("quote") or "")[:1200],
            }
            for source in source_snapshots
        ],
    }
    system = (
        "你是 EduMatrix Resource Planner。根据冻结课程、学习画像、用户要求和授权来源，"
        "为所选资源设计一个共享语义计划。只输出一个 JSON 对象，包含 summary、plan、"
        "resourceBriefs（对象数组，每项含 type、goal、dependencies、qualityChecks）。"
        "不得编造来源、不得输出 Markdown、思维链、prompt、API key 或 reasoning_content。"
    )
    try:
        raw = await backend.generate(system, json.dumps(safe_context, ensure_ascii=False, sort_keys=True), role="resource_planner")
        payload = parse_json_object(raw)
    except Exception as exc:
        raise ResourceBundleError("resource_generation.planner_failed", f"资源规划模型调用失败：{exc}") from exc
    plan = str(payload.get("plan") or payload.get("narrative") or payload.get("summary") or "").strip()
    summary = str(payload.get("summary") or plan[:320]).strip()
    if not plan:
        _fail("resource_generation.planner_output_invalid", "资源规划模型未返回共享语义计划。")
    return {
        "run_id": str(manifest.get("planner_run_id") or ""),
        "summary": summary[:320],
        "plan": plan[:12000],
        "resource_briefs": [item for item in payload.get("resourceBriefs") or [] if isinstance(item, dict)][:20],
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
) -> None:
    payload = {
        "run_id": run_id or task.trace_id,
        "stage_id": stage_id or (f"resource:{resource_type}" if resource_type else "resource_generation"),
        "resource_item_id": step.id if step else "",
        "resource_type": resource_type,
        "status": status,
        "owner": "Resource Generator" if resource_type else "Supervisor",
        "summary": " ".join(str(summary or "").split())[:320],
        "input_refs": [str(value) for value in (input_refs or []) if str(value).strip()][:20],
        "output_refs": [str(value) for value in (output_refs or []) if str(value).strip()][:20],
        "progress": progress,
        "retryable": bool(retryable),
    }
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
    query_candidates = [
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

    def relevant(result: Any) -> bool:
        if not isinstance(result, dict) or not result.get("snippet"):
            return True
        haystack = " ".join(str(result.get(key) or "") for key in ("title", "snippet", "description")).lower()
        return not query_terms or any(term.lower() in haystack for term in query_terms)

    results: list[dict[str, Any]] = []
    last_error: Exception | None = None
    for query in query_candidates:
        try:
            candidate_results = await search_videos(query, max_results=5)
        except Exception as exc:
            last_error = exc
            continue
        results = [value for value in (candidate_results or []) if relevant(value)]
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
        description = " ".join(str(result.get("description") or result.get("snippet") or "").split())[:1_000]
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
            "reason": description or f"联网检索结果第 {index} 条，与当前课程知识点相关。",
            "segments": [],
            "sourceRefIds": source_ids,
            "alternatives": [],
        })
    if not recommendations:
        _fail("resource_generation.video_search_empty", "联网搜索没有返回可用的真实网页视频，请稍后重试。")
    return recommendations[:5]


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
    variant = _profile_content_variant(context)
    difficulty_label = str(adaptation_plan.get("difficulty_label") or mastery_summary[:64]).strip()
    scaffolding_level = str(adaptation_plan.get("scaffolding_level") or "medium").strip()
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
    raw_steps = [value for value in llm_payload.get("practiceSteps") or [] if isinstance(value, dict)]
    if resource_type in {"handout", "mind_map", "training_task", "code_sandbox", "interactive_model", "deck"} and len(raw_steps) < 4:
        _fail("resource_generation.model_output_invalid", "真实模型返回缺少四步实践内容。")
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

    def variant_prompt(value: Any) -> str:
        prompt = visible_text(value)
        prefix = variant["question_prefix"]
        return prompt if prompt.startswith(prefix) else f"{prefix} {prompt}".strip()

    def variant_difficulty(value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = 0.5
        return round(max(0.1, min(0.95, number + float(variant["difficulty_delta"]))), 2)

    content_narrative = f"{visible_text(variant['lead'])} {narrative}".strip()

    if resource_type == "feynman":
        return (
            f"# {title}\n\n## 复述任务\n\n{content_narrative}\n\n"
            f"## 学习目标\n\n{learning_goal}\n"
        )

    if resource_type == "handout":
        model_questions = [value for value in llm_payload.get("quizQuestions") or [] if isinstance(value, dict)]
        mini_quiz = []
        for index, question in enumerate(model_questions[:3], start=1):
            options = [visible_text(value) for value in question.get("options") or [] if str(value).strip()]
            if len(options) < 2:
                continue
            answer = str(question.get("answer") or "A").strip().upper()
            correct_index = max(0, min(len(options) - 1, ord(answer[0]) - ord("A"))) if answer else 0
            mini_quiz.append({
                "id": f"mini-quiz-{index}",
                "question": variant_prompt(question.get("prompt") or narrative),
                "options": options[:8],
                "correctIndex": correct_index,
                "explanation": visible_text(question.get("explanation") or summary),
                "required": True,
            })
        if not mini_quiz:
            _fail("resource_generation.model_output_invalid", "真实模型返回缺少可用的小测题目。")
        code = str(llm_payload.get("starterCode") or "").strip()
        if not code:
            _fail("resource_generation.model_output_invalid", "真实模型返回缺少 handout 的 starterCode。")

        # 旧版讲义会把一个主题拆成多个可跳转的教学段落。新协议的
        # HandoutContent 没有自由格式 section 字段，因此把模型返回的
        # handoutSections 映射到现有 concepts/figures/examples/
        # counterExamples/codeBlocks/miniQuiz；这样不另造存储协议，且
        # 仍能保留旧版的“背景—机制—例子—边界—练习”丰富度。
        def safe_refs(value: Any) -> list[str]:
            refs = value if isinstance(value, list) else []
            return [str(ref) for ref in refs if str(ref) in source_ids]

        concepts = [{"id": "concept-core", "title": knowledge_point, "explanation": content_narrative, "sourceRefIds": source_ids}]
        figures = [{
            "id": "figure-mechanism",
            "title": "从输入到结果的学习流程",
            "kind": "diagram",
            "content": "输入数据 → 计算损失 → 求梯度 → 更新参数 → 检查验证结果",
            "caption": "把每一步的输入、计算和检查点串起来，便于定位训练过程中的问题。",
            "sourceRefIds": source_ids,
        }]
        examples = [{"id": "example-application", "title": step_at(0)["title"], "body": step_at(0)["instruction"], "sourceRefIds": source_ids}]
        counter_examples = [{"id": "counterexample-boundary", "title": step_at(3)["title"], "body": step_at(3)["errorGuidance"], "sourceRefIds": source_ids}]
        code_blocks = [{"id": "code-reading", "title": "示例代码", "language": str(llm_payload.get("codeLanguage") or "python"), "code": code, "explanation": step_at(1)["instruction"]}]
        used_ids = {item["id"] for group in (concepts, figures, examples, counter_examples, code_blocks, mini_quiz) for item in group}
        for index, section in enumerate(llm_payload.get("handoutSections") or [], start=1):
            if not isinstance(section, dict):
                continue
            title_text = visible_text(section.get("title"))
            body_text = visible_text(section.get("content") or section.get("body"))
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
            if kind in {"concept", "background", "mechanism"}:
                concepts.append({"id": section_id, "title": title_text, "explanation": body_text, "sourceRefIds": refs})
            elif kind in {"figure", "diagram", "formula"}:
                figure_kind = kind if kind in {"chart", "formula", "diagram"} else "diagram"
                figures.append({"id": section_id, "title": title_text, "kind": figure_kind, "content": body_text, "caption": visible_text(section.get("caption") or title_text), "sourceRefIds": refs})
            elif kind in {"counterexample", "misconception", "boundary", "error"}:
                counter_examples.append({"id": section_id, "title": title_text, "body": body_text, "sourceRefIds": refs})
            elif kind == "code":
                section_code = str(section.get("code") or "").strip()
                if not section_code or validate_code(section_code):
                    continue
                code_blocks.append({"id": section_id, "title": title_text, "language": str(section.get("language") or "python"), "code": section_code, "explanation": visible_text(section.get("explanation") or title_text)})
            elif kind in {"example", "application", "practice"}:
                examples.append({"id": section_id, "title": title_text, "body": body_text, "sourceRefIds": refs})

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
        outline = [
            *[{"id": item["id"], "title": item["title"]} for item in concepts],
            *[{"id": item["id"], "title": item["title"]} for item in figures],
            *[{"id": item["id"], "title": item["title"]} for item in examples],
            *[{"id": item["id"], "title": item["title"]} for item in counter_examples],
            *[{"id": item["id"], "title": item["title"]} for item in code_blocks],
            *[{"id": item["id"], "title": f"学习检查 {index}"} for index, item in enumerate(mini_quiz, start=1)],
        ][:30]
        payload = {
            "schemaVersion": "f5.handout.v1", "title": title, "summary": summary,
            "learningGoal": learning_goal, "estimatedMinutes": int(llm_payload.get("estimatedMinutes") or 24),
            "outline": outline,
            "concepts": concepts,
            "figures": figures,
            "examples": examples,
            "counterExamples": counter_examples,
            "codeBlocks": code_blocks,
            "miniQuiz": mini_quiz,
            "footnotes": [
                {"id": f"source-{index}", "sourceRefId": str(source.get("source_ref_id")), "label": f"[{index}]", "title": str(source.get("title") or "课程来源"), "location": str(source.get("location_label") or source.get("location_kind") or "课程章节")}
                for index, source in enumerate(source_snapshots, start=1)
            ],
            "profileAdaptation": {"summary": f"{visible_text(variant['lead'])} {profile_summary}；表达方式：{explanation_style}；练习策略：{practice_strategy}", "difficulty": difficulty_label[:64], "scaffolding": [f"支架等级：{scaffolding_level}", step_at(0)["instruction"], step_at(1)["instruction"], step_at(3)["instruction"]]},
        }
        return validate(payload, parse_handout_content, "resource_generation.handout_invalid")

    if resource_type == "mind_map":
        nodes = [{"nodeId": "root", "parentNodeId": None, "label": knowledge_point, "summary": content_narrative, "relation": "主题", "depth": 0, "sourceRefs": source_ids, "masteryBand": "developing", "linkedResourceIds": list(linked_resource_ids or [])}]
        for index, step in enumerate(steps, start=1):
            nodes.append({"nodeId": f"node-{index}", "parentNodeId": "root", "label": step["title"], "summary": step["instruction"], "relation": "组成", "depth": 1, "sourceRefs": source_ids, "masteryBand": "unknown", "linkedResourceIds": []})
        return validate({"schemaVersion": "f5.mindmap.v1", "title": title, "summary": f"{variant['label']}：{summary}（{explanation_style}）", "learningGoal": learning_goal, "rootNodeId": "root", "nodes": nodes}, parse_mindmap_content, "resource_generation.mind_map_invalid")

    if resource_type == "training_task":
        task_steps = [{"id": f"step-{index}", "title": step["title"], "instruction": step["instruction"], "expectedResult": step["expectedResult"], "errorGuidance": step["errorGuidance"], "sourceRefIds": source_ids} for index, step in enumerate(steps, start=1)]
        environment = [teacher_text(value) for value in llm_payload.get("environment") or [] if str(value).strip()]
        data = [teacher_text(value) for value in llm_payload.get("data") or [] if str(value).strip()]
        if not environment or not data:
            _fail("resource_generation.model_output_invalid", "真实模型返回缺少实训环境或数据说明。")
        payload = {
            "schemaVersion": "f5.training-task.v1", "title": title, "objective": content_narrative, "difficulty": difficulty_label[:64], "estimatedMinutes": int(llm_payload.get("estimatedMinutes") or 55),
            "prerequisites": [learning_goal], "environment": environment, "data": data, "steps": task_steps,
            "checkpoints": [{"id": f"checkpoint-{index}", "afterStepId": f"step-{index}", "title": step["title"], "verification": step["expectedResult"], "passCondition": step["expectedResult"]} for index, step in enumerate(steps, start=1)],
            "deliverables": [{"id": "deliverable-code", "title": "代码与运行记录", "description": step_at(2)["expectedResult"], "format": "代码沙盒运行记录"}, {"id": "deliverable-reflection", "title": "评估与反思", "description": step_at(3)["expectedResult"], "format": "Markdown"}],
            "rubric": [{"id": "rubric-data", "criterion": step_at(0)["title"], "evidence": step_at(0)["expectedResult"], "points": 25}, {"id": "rubric-model", "criterion": step_at(1)["title"], "evidence": step_at(1)["expectedResult"], "points": 25}, {"id": "rubric-run", "criterion": step_at(2)["title"], "evidence": step_at(2)["expectedResult"], "points": 30}, {"id": "rubric-evaluate", "criterion": step_at(3)["title"], "evidence": step_at(3)["expectedResult"], "points": 20}],
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
            "checkpoints": [{"id": f"checkpoint-{index}", "title": step["title"], "instruction": step["instruction"], "completionHint": step["expectedResult"]} for index, step in enumerate(steps, start=1)],
            "files": [{"path": "main.py", "language": "python", "content": starter_code}], "entryFile": "main.py", "standardInput": str(llm_payload.get("standardInput") or ""),
            "requiredChecks": required_checks, "completionRule": str(item.get("completion_rule") or steps[-1]["expectedResult"]),
            "runtime": {"language": "python", "mode": "trusted_local", "timeoutSeconds": 10, "boundary": "在 EduMatrix 受限本地运行环境中执行。"}, "sourceRefIds": source_ids, "linkedTrainingTaskId": None, "linkedModelId": None, "semanticContext": {"source_ref_ids": source_ids, "learning_goal": learning_goal},
        }
        return validate(payload, parse_code_sandbox_content, "resource_generation.code_sandbox_invalid")

    if resource_type == "interactive_model":
        template = _interactive_template_for_knowledge_point(knowledge_point)
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

        # Parameters and metric series must be echoed by the model exactly from
        # the same runtime registry used by interactive_lab.create_instance.
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
                if str(raw_parameter["label"]).strip() != definition.label or str(raw_parameter["kind"]).strip() != definition.kind:
                    raise ValueError
                if str(raw_parameter.get("unit") or "") != definition.unit or str(raw_parameter["description"]).strip() != definition.description:
                    raise ValueError
                for field in ("minimum", "maximum", "step", "default"):
                    if float(raw_parameter[field]) != float(getattr(definition, field)):
                        raise ValueError
            except (KeyError, TypeError, ValueError):
                _fail("resource_generation.interactive_model_template_mismatch", "真实模型返回的参数范围或定义与所选实验模板不一致，已拒绝保存。")
        parameters = [item.model_dump(mode="json") for item in template.parameters]
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
        if not dataset_id or not dataset_title or not dataset_summary or isinstance(sample_count, bool) or not isinstance(sample_count, int) or sample_count < 1:
            _fail("resource_generation.model_output_invalid", "真实模型返回的数据集必须包含 id、title、summary 和正整数 sampleCount。")
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
        if not isinstance(raw_series, list) or len(raw_series) != len(expected_series):
            _fail("resource_generation.interactive_model_template_mismatch", "真实模型返回的图表指标与所选实验模板不一致，已拒绝保存。")
        for raw_metric in raw_series:
            if not isinstance(raw_metric, dict) or str(raw_metric.get("key") or "") not in expected_series:
                _fail("resource_generation.interactive_model_template_mismatch", "真实模型返回的图表指标与所选实验模板不一致，已拒绝保存。")
            expected_metric = expected_series[str(raw_metric["key"])]
            if any(raw_metric.get(field) != expected_metric[field] for field in ("key", "label", "unit", "higherIsBetter")):
                _fail("resource_generation.interactive_model_template_mismatch", "真实模型返回的图表指标定义与所选实验模板不一致，已拒绝保存。")
        chart = {
            "kind": "line",
            "xAxisLabel": x_axis,
            "yAxisLabel": y_axis,
            "series": [
                {"key": metric.key, "label": metric.label, "unit": metric.unit, "higherIsBetter": metric.higher_is_better}
                for metric in template.metrics
            ],
        }
        observation = teacher_text(llm_payload.get("observationPrompt"))
        if not observation:
            _fail("resource_generation.model_output_invalid", "真实模型返回缺少可交互模型观察提示。")
        completion_rule = str(item.get("completion_rule") or step_at(3)["expectedResult"])
        payload = {
            "schemaVersion": "f6.interactive-model.v1",
            "templateId": template.template_id,
            "title": title,
            "summary": summary,
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
            layout = str(model_slide.get("layout") or ("title" if index == 0 else "content"))
            if layout not in {"title", "content", "two_column", "closing"}:
                layout = "content"
            title_text = teacher_text(model_slide.get("title"))
            body_text = teacher_text(model_slide.get("body"))
            if not title_text or (layout != "title" and not body_text and not any(str(value).strip() for value in model_slide.get("bullets") or [])):
                _fail("resource_generation.model_output_invalid", "真实模型返回的幻灯片缺少标题或正文。")
            slides.append({"id": f"slide-{index + 1}", "layout": layout, "title": title_text, "subtitle": teacher_text(model_slide.get("subtitle")), "body": "" if layout == "title" else body_text, "bullets": [teacher_text(value) for value in model_slide.get("bullets") or [] if str(value).strip()], "speakerNotes": teacher_text(model_slide.get("speakerNotes")), "sourceRefIds": source_ids})
        return validate({"schemaVersion": "f5.deck.v1", "title": title, "summary": summary, "learningGoal": learning_goal, "adaptationSummary": narrative, "slides": slides}, parse_deck_content, "resource_generation.deck_invalid")

    if resource_type == "video":
        # URLs come only from the live search adapter; model-provided URL
        # suggestions are ignored so a structured response can never publish a
        # fabricated or local placeholder video.
        recommendations = [dict(value) for value in (video_recommendations or []) if isinstance(value, dict)]
        if not recommendations:
            _fail("resource_generation.video_search_empty", "联网搜索没有返回可用的真实网页视频，请稍后重试。")
        return validate({"schemaVersion": "f5.video-recommendation.v1", "title": title, "summary": summary, "learningGoal": learning_goal, "adaptationSummary": narrative, "recommendations": recommendations}, parse_video_recommendation_content, "resource_generation.video_invalid")

    _fail("resource_generation.type_invalid", f"不支持的资源类型：{resource_type}")


async def _resource_review_async(
    backend: Any,
    *,
    manifest: dict[str, Any],
    semantic_plan: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    context = _public_generation_context(manifest)
    system = (
        "你是 EduMatrix Resource Reviewer。审核候选资源是否符合冻结课程、授权来源、"
        "学习画像、用户要求和资源间依赖。只输出一个 JSON 对象：approved（布尔值）、"
        "summary（字符串）、findings（数组）、rejectedTypes（资源类型数组）。"
        "approved=false 时必须列出需要返工的资源类型。不得重新生成正文，不得输出 Markdown、"
        "prompt、API key、思维链或 reasoning_content。"
    )
    user = json.dumps({
        "course": context,
        "user_instruction": manifest.get("user_instruction") or "",
        "shared_semantic_plan": semantic_plan[:12000],
        "candidates": candidates,
    }, ensure_ascii=False, sort_keys=True)
    try:
        raw = await backend.generate(system, user, role="resource_reviewer")
        return parse_json_object(raw)
    except Exception as exc:
        raise ResourceBundleError("resource_generation.reviewer_failed", f"资源审核模型调用失败：{exc}") from exc


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
        raw_content = str(version.content or "")
        # Structured resource artifacts must remain parseable when passed to
        # the reviewer.  Truncating JSON at an arbitrary character boundary
        # made every sufficiently rich handout look corrupted and caused the
        # live review gate to reject otherwise valid model output.  Markdown
        # candidates can still use a bounded excerpt for review context.
        if version.content_format == "json":
            try:
                json.loads(raw_content)
                review_content = raw_content
            except (TypeError, ValueError):
                review_content = raw_content[:6000]
        else:
            review_content = raw_content[:6000]
        candidates.append({
            "type": resource_type,
            "resource_id": artifact.id,
            "version_id": version.id,
            "title": artifact.title,
            "content": review_content,
            "source_ref_ids": list(metadata.get("source_ref_ids") or []),
            "content_format": version.content_format,
        })
    return candidates


def _mark_review_rejected(
    db: Any,
    *,
    task: DBGenerationTask,
    latest: dict[int, DBTaskStep],
    rejected_types: list[str],
    reason: str,
) -> None:
    for resource_type in rejected_types:
        sequence = GENERATION_RESOURCE_TYPES.index(resource_type) + 1
        step = latest.get(sequence)
        if step is None or step.status != "succeeded":
            continue
        step.status = "failed"
        step.error_code = "resource_generation.review_rejected"
        step.error_message = str(reason or "资源审核要求返工")[:2000]
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
) -> dict[str, Any]:
    """Execute a live resource run through the shared Planner/Supervisor graph."""
    task = _generation_task(db, actor, task_id)
    if task.status == "cancelled":
        _fail("resource_generation.cancelled", "已取消任务不能执行")
    if task.status == "completed":
        return generation_job_payload(db, actor, task.id)
    manifest = _generation_manifest(db, task.id)
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
        _resource_event(db, task=task, event_type="run.failed", status="failed", summary=str(exc), retryable=True)
        _sync_generation_task(db, task)
        return generation_job_payload(db, actor, task.id)

    callback_token = _RESOURCE_EVENT_CALLBACK.set(event_callback)
    loop = asyncio.new_event_loop()
    previous_loop = None
    try:
        try:
            previous_loop = asyncio.get_event_loop()
        except RuntimeError:
            previous_loop = None
        asyncio.set_event_loop(loop)
        _resource_event(
            db,
            task=task,
            event_type="stage.started",
            status="running",
            stage_id="resource_planner",
            run_id=manifest.get("planner_run_id") or f"resource-plan:{task.id}",
            summary="Resource Planner 正在为所选资源生成共享语义计划。",
            input_refs=[f"task:{task.id}"],
            progress=0.02,
        )
        plan_payload = _generation_plan(db, task.id)
        plan = str(plan_payload.get("plan") or "")
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
            plan_payload = loop.run_until_complete(_shared_semantic_plan_async(
                backend,
                manifest=manifest,
                source_snapshots=list(unique_sources.values()),
            ))
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
                    summary=f"{resource_type} 已派发给 Resource Generator，等待并行模型结果。",
                    step=step,
                    input_refs=[f"task:{task.id}", *[f"source:{item_id}" for item_id in item.get("source_ref_ids") or []]],
                    progress=0.16,
                    retryable=True,
                )
            except ResourceBundleError as exc:
                fail_generation_item(db, actor, task.id, resource_type, error_code=exc.code, error_message=str(exc))
                _resource_event(db, task=task, event_type="resource.item.failed", resource_type=resource_type, status="failed", summary=str(exc), step=step, retryable=True)

        async def gather_candidates() -> list[Any]:
            return await asyncio.gather(*[
                _real_model_payload_async(
                    backend,
                    resource_type=resource_type,
                    item=item,
                    manifest=manifest,
                    source_snapshots=source_snapshots,
                    semantic_plan=plan,
                )
                for resource_type, _, item, source_snapshots in requests
            ], return_exceptions=True)

        results = loop.run_until_complete(gather_candidates()) if requests else []
        for (resource_type, step, item, source_snapshots), result in zip(requests, results):
            try:
                if isinstance(result, Exception):
                    raise result
                linked_resource_ids: list[str] = []
                video_recommendations = None
                if resource_type == "video":
                    video_recommendations = loop.run_until_complete(
                        _live_video_recommendations(manifest=manifest)
                    )
                content = (
                    _create_quiz_resource_content(db, actor=actor, task=task, item=item, manifest=manifest, source_snapshots=source_snapshots, llm_payload=result)
                    if resource_type == "quiz"
                    else _llm_resource_content(resource_type=resource_type, item=item, manifest=manifest, source_snapshots=source_snapshots, linked_resource_ids=linked_resource_ids, llm_payload=result, video_recommendations=video_recommendations)
                )
                content_format = "json" if resource_type in {"handout", "mind_map", "training_task", "code_sandbox", "video", "deck", "interactive_model", "quiz"} else "markdown"
                complete_generation_item(db, actor, task.id, resource_type, content=content, content_format=content_format, generation_mode="llm", model="deepseek-v4-flash", reasoning_effort="max")
                _, latest = _task_steps(db, task.id)
                output_step = latest[GENERATION_RESOURCE_TYPES.index(resource_type) + 1]
                _resource_event(db, task=task, event_type="resource.item.completed", resource_type=resource_type, status="completed", summary=f"{resource_type} 候选已生成，等待统一审核。", step=output_step, output_refs=[f"artifact-version:{output_step.output_artifact_version_id}"], progress=0.55, retryable=False)
            except Exception as exc:
                error = exc if isinstance(exc, ResourceBundleError) else ResourceBundleError("resource_generation.model_call_failed", str(exc))
                fail_generation_item(db, actor, task.id, resource_type, error_code=error.code, error_message=str(error))
                _resource_event(db, task=task, event_type="resource.item.failed", resource_type=resource_type, status="failed", summary=str(error), step=step, retryable=True)

        # Training task is a strict dependency edge and is evaluated only after both
        # code sandbox and interactive model have produced artifact versions.
        _, latest = _task_steps(db, task.id)
        if "training_task" in requested_types:
            sequence = GENERATION_RESOURCE_TYPES.index("training_task") + 1
            step = latest.get(sequence)
            dependency_steps = [latest.get(GENERATION_RESOURCE_TYPES.index(dep) + 1) for dep in _resource_dependencies("training_task")]
            # A retried sandbox/model produces a new artifact version.  A
            # previously successful training task must be regenerated against
            # those newest dependency IDs instead of keeping a stale link.
            if step and step.status == "succeeded" and all(dep is not None for dep in dependency_steps):
                if any(int(dep.attempt or 0) > int(step.attempt or 0) for dep in dependency_steps):
                    refreshed_step = create_task_step(
                        db,
                        task_id=task.id,
                        sequence=sequence,
                        attempt=max(int(dep.attempt or 0) for dep in dependency_steps),
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
                if all(dep is not None and dep.status == "succeeded" and dep.output_artifact_version_id for dep in dependency_steps):
                    item = _step_input(step)
                    try:
                        mark_generation_item_running(db, actor, task.id, "training_task")
                        _, latest = _task_steps(db, task.id)
                        step = latest[sequence]
                        source_snapshots = _generation_source_snapshots(db, task=task, manifest=manifest, item=item, resource_type="training_task")
                        linked_resource_ids = [
                            str(db.get(DBArtifactVersion, dep.output_artifact_version_id).artifact_id)
                            for dep in dependency_steps
                            if dep and dep.output_artifact_version_id and db.get(DBArtifactVersion, dep.output_artifact_version_id)
                        ]
                        _resource_event(db, task=task, event_type="resource.item.started", resource_type="training_task", status="running", summary="代码沙盒和可交互模型已完成，开始生成依赖实训任务书。", step=step, input_refs=[f"artifact-version:{dep.output_artifact_version_id}" for dep in dependency_steps if dep], progress=0.62, retryable=True)
                        result = loop.run_until_complete(_real_model_payload_async(backend, resource_type="training_task", item=item, manifest=manifest, source_snapshots=source_snapshots, semantic_plan=plan))
                        content = _llm_resource_content(resource_type="training_task", item=item, manifest=manifest, source_snapshots=source_snapshots, linked_resource_ids=linked_resource_ids, llm_payload=result)
                        complete_generation_item(db, actor, task.id, "training_task", content=content, content_format="json", generation_mode="llm", model="deepseek-v4-flash", reasoning_effort="max")
                        _, latest = _task_steps(db, task.id)
                        output_step = latest[sequence]
                        _resource_event(db, task=task, event_type="resource.item.completed", resource_type="training_task", status="completed", summary="实训任务书已基于两个依赖资源生成。", step=output_step, output_refs=[f"artifact-version:{output_step.output_artifact_version_id}"], progress=0.7, retryable=False)
                    except Exception as exc:
                        error = exc if isinstance(exc, ResourceBundleError) else ResourceBundleError("resource_generation.model_call_failed", str(exc))
                        fail_generation_item(db, actor, task.id, "training_task", error_code=error.code, error_message=str(error))
                        _resource_event(db, task=task, event_type="resource.item.failed", resource_type="training_task", status="failed", summary=str(error), step=step, retryable=True)
                elif any(dep is None or dep.status == "failed" for dep in dependency_steps):
                    fail_generation_item(db, actor, task.id, "training_task", error_code="resource_generation.dependency_failed", error_message="代码沙盒或可交互模型未通过，实训任务书无法生成")
                    _resource_event(db, task=task, event_type="resource.item.failed", resource_type="training_task", status="failed", summary="依赖资源失败，实训任务书未生成。", step=step, retryable=True)

        _, latest = _task_steps(db, task.id)
        states = [row.status for row in latest.values()]
        if states and all(state == "succeeded" for state in states):
            review_status = _review_gate_status(db, task.id)
            if review_status != "passed":
                _resource_event(db, task=task, event_type="review_gate.started", status="running", stage_id="review_gate", run_id=manifest.get("review_run_id") or f"resource-review:{task.id}", summary="Resource Reviewer 正在审核候选资源的结构、来源和跨资源一致性。", input_refs=[f"artifact-version:{step.output_artifact_version_id}" for step in latest.values() if step.output_artifact_version_id], progress=0.78, retryable=True)
                candidates = _candidate_resources(db, task, latest)
                try:
                    review = loop.run_until_complete(_resource_review_async(backend, manifest=manifest, semantic_plan=plan, candidates=candidates))
                    rejected = [str(value) for value in review.get("rejectedTypes") or [] if str(value) in requested_types]
                    explicit_approved = review.get("approved")
                    approved = bool(explicit_approved) if isinstance(explicit_approved, bool) else not rejected and str(review.get("status") or "").lower() not in {"failed", "rejected"}
                    if approved and not rejected:
                        _resource_event(db, task=task, event_type="review_gate.passed", status="completed", stage_id="review_gate", run_id=manifest.get("review_run_id") or f"resource-review:{task.id}", summary=str(review.get("summary") or "全部候选资源通过审核。"), output_refs=[f"artifact-version:{candidate['version_id']}" for candidate in candidates], progress=0.9, retryable=False)
                    else:
                        rejected = rejected or requested_types
                        reason = str(review.get("summary") or "Resource Reviewer 要求返工被拒绝的资源项。")
                        _mark_review_rejected(db, task=task, latest=latest, rejected_types=rejected, reason=reason)
                        _resource_event(db, task=task, event_type="review_gate.failed", status="failed", stage_id="review_gate", run_id=manifest.get("review_run_id") or f"resource-review:{task.id}", summary=reason, output_refs=[f"artifact-version:{candidate['version_id']}" for candidate in candidates], progress=0.9, retryable=True)
                except ResourceBundleError as exc:
                    _resource_event(db, task=task, event_type="review_gate.failed", status="failed", stage_id="review_gate", run_id=manifest.get("review_run_id") or f"resource-review:{task.id}", summary=str(exc), progress=0.9, retryable=True)
            if _review_gate_status(db, task.id) == "passed" and not _publish_gate_done(db, task.id):
                _, latest = _task_steps(db, task.id)
                if all(step.status == "succeeded" and step.output_artifact_version_id for step in latest.values()):
                    published: list[str] = []
                    for step in latest.values():
                        version = db.get(DBArtifactVersion, step.output_artifact_version_id)
                        artifact = db.get(DBArtifact, version.artifact_id) if version else None
                        if artifact is None:
                            continue
                        artifact.status = "published"
                        published.append(f"{artifact.id}:{version.id}")
                    _resource_event(db, task=task, event_type="publish.completed", status="completed", stage_id="publish_gate", summary="审核通过，候选资源已发布到既有资源子空间。", output_refs=published, progress=1.0, retryable=False)
                    _resource_event(db, task=task, event_type="run.completed", status="completed", summary="资源 Supervisor 运行完成。", output_refs=published, progress=1.0, retryable=False)
        _, final_latest = _task_steps(db, task.id)
        if (
            any(step.status == "failed" for step in final_latest.values())
            or _review_gate_status(db, task.id) == "failed"
        ):
            ensure_run_failed("资源 Supervisor 本轮未完成，失败项可单独重试。")
        _sync_generation_task(db, task)
    except ResourceBundleError as exc:
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
        _resource_event(db, task=task, event_type="run.failed", status="failed", summary=str(exc), retryable=True)
        _sync_generation_task(db, task)
    finally:
        loop.close()
        _RESOURCE_EVENT_CALLBACK.reset(callback_token)
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
    if resource_type == "interactive_model":
        if content_format != "json":
            _fail("resource_generation.interactive_model_content_format", "可交互模型必须使用结构化 JSON")
        try:
            parse_interactive_model_content(clean_content)
        except ValueError as exc:
            _fail("resource_generation.interactive_model_content_invalid", str(exc))
    if resource_type == "code_sandbox":
        if content_format != "json":
            _fail("resource_generation.code_sandbox_content_format", "代码沙盒必须使用结构化 JSON")
        try:
            parse_code_sandbox_content(clean_content)
        except ValueError as exc:
            _fail("resource_generation.code_sandbox_content_invalid", str(exc))
    manifest = _generation_manifest(db, task.id)
    item = _step_input(step)
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
        completion_rule=str(item.get("completion_rule") or ""),
        generation_mode=generation_mode,
        model=model,
        reasoning_effort=reasoning_effort,
    )
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
    step.error_message = str(error_message)[:2000]
    step.completed_at = _utcnow()
    append_task_event(db, task_id=task.id, step_id=step.id, event_type="resource_generation.item.failed", payload={"type": resource_type, "attempt": step.attempt, "error_code": step.error_code})
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
        input_summary=previous.input_summary,
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
    if not recoverable:
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
            input_summary=previous.input_summary,
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
    task.completed_at = _utcnow()
    append_task_event(db, task_id=task.id, event_type="resource_generation.cancelled", payload={})
    db.flush()
    return generation_job_payload(db, actor, task.id)
