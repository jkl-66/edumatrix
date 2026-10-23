"""Formal exam lifecycle built on canonical assessment evidence."""

from __future__ import annotations

import csv
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import Field, model_validator

from app.database import (
    DBAssessmentAttempt, DBAssessmentExam, DBAssessmentExamItem,
    DBAssessmentExamReport, DBAssessmentExamResponse, DBAssessmentExamResponseDraft,
    DBAssessmentExamSitting,
    DBAssessmentExamVersion, DBAssessmentGradingResult, DBAssessmentQuestion,
    DBAssessmentQuestionVersion, DBAssessmentReviewCase, DBChapter,
    DBChapterKnowledgePoint, DBCourse, DBKnowledgePoint, DBLearningEvent,
    DBProfileSnapshot, DBSourceDocument, DBSourceRef,
)
from app.m1_lifecycle import record_audit
from app.m2_contracts import StrictModel
from app.m5_assessment_core import (
    AIGradingOutput,
    AttemptInput, QuestionVersionInput, create_grading_result, create_question_version,
    ai_grading_prompt, grading_result_payload, learner_correct_answer, learner_option_texts, learner_safe_explanation,
    learner_topic_title,
    learner_safe_prompt, persist_ai_grading,
    persist_failed_ai_grading, record_attempt,
)
from app.m5_capabilities import Capability, M5CapabilityError, OutputConstraints
from app.m5_gateway import execute_registered_structured_call


class FormalExamError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise FormalExamError(code, message)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _learner_error_reason(tags: Any, knowledge_point: str) -> str:
    tag = str(next(iter(tags or ()), "")).strip()
    opaque = (
        not tag
        or bool(re.search(r"\b(?:f\d+-)?(?:kp|event|trace|run)-[a-z0-9-]{6,}\b|\b[a-f0-9]{24,}\b", tag, re.I))
        or (tag.isascii() and ("_" in tag or "-" in tag))
    )
    if opaque:
        subject = knowledge_point or "本题知识点"
        return f"{subject}的关键条件或判断边界仍需巩固，请结合上方解析复习后再测。"
    return tag


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _run_async(coro):
    """Bridge the synchronous core API to the async model gateway."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _require_exam_model(llm: Any) -> None:
    model = str(getattr(llm, "model", "")).strip()
    thinking = str(getattr(llm, "thinking_mode", "")).strip().lower()
    reasoning = str(getattr(llm, "reasoning_effort", "")).strip().lower()
    backend_name = llm.__class__.__name__.lower()
    if (
        model != "deepseek-v4-flash"
        or thinking != "enabled"
        or reasoning != "max"
        or "deterministic" in backend_name
        or "fallback" in backend_name
    ):
        _fail(
            "intelligent_exam_model_policy_invalid",
            "智能组卷必须使用 deepseek-v4-flash、thinking enabled、reasoning max，且不允许回退模型",
        )


def _validate_llm_exam_output(
    payload: dict[str, Any], *, config: IntelligentExamConfigInput, blueprint: dict[str, Any],
) -> IntelligentExamGenerationOutput:
    output = IntelligentExamGenerationOutput.model_validate(payload)
    expected_total = sum(config.question_type_counts.values())
    if len(output.questions) != expected_total:
        _fail("intelligent_exam_llm_question_count", "模型生成题量与组卷题型配额不一致")
    expected_counts = {key: int(value) for key, value in config.question_type_counts.items() if int(value)}
    actual_counts: dict[str, int] = {}
    allowed_points = {str(item["id"]) for item in blueprint.get("knowledge_points", [])}
    allowed_sources = set(str(item) for item in blueprint.get("source_ref_ids", []))
    for question in output.questions:
        actual_counts[question.question_type] = actual_counts.get(question.question_type, 0) + 1
        if question.primary_knowledge_point_id not in allowed_points:
            _fail("intelligent_exam_llm_knowledge_point_invalid", "模型题目绑定了当前范围之外的知识点")
        if not set(question.source_ref_ids).issubset(allowed_sources):
            _fail("intelligent_exam_llm_source_invalid", "模型题目引用了当前课程范围之外的来源")
        if not question.source_ref_ids:
            _fail("intelligent_exam_llm_source_missing", "模型题目必须绑定课程来源")
        if question.question_type in {"short_answer"}:
            criteria = question.scoring_rule.get("criteria") if isinstance(question.scoring_rule, dict) else None
            if not str(question.answer_key.get("reference_answer", "")).strip() or not isinstance(criteria, list) or not criteria:
                _fail("intelligent_exam_llm_rubric_missing", "模型主观题必须提供参考答案和评分量规")
    if actual_counts != expected_counts:
        _fail("intelligent_exam_llm_question_types", "模型生成题型与请求配额不一致")
    return output


class ExamItemInput(StrictModel):
    question_version_id: str
    points: float = Field(gt=0, le=10000)
    required: bool = True


class ExamCreateInput(StrictModel):
    course_id: str
    title: str = Field(min_length=1, max_length=256)
    instructions: str = Field(default="", max_length=20000)
    duration_minutes: int = Field(default=60, ge=1, le=1440)
    feedback_policy: str = Field(default="after_close", pattern="^(after_submission|after_close|teacher_only)$")
    scheduled_open_at: datetime | None = None
    scheduled_close_at: datetime | None = None
    generation_key: str | None = Field(default=None, min_length=8, max_length=128)
    configuration: dict[str, Any] = Field(default_factory=dict)
    generation_context: dict[str, Any] = Field(default_factory=dict)
    coverage: dict[str, Any] = Field(default_factory=dict)
    items: tuple[ExamItemInput, ...] = Field(min_length=1, max_length=200)


class FormalResponseInput(StrictModel):
    exam_item_id: str
    idempotency_key: str = Field(min_length=8, max_length=128)
    answer: dict[str, Any]
    confidence: float | None = Field(default=None, ge=0, le=1)
    duration_seconds: int | None = Field(default=None, ge=0)


LEARNER_EXAM_TYPES = (
    "single_choice", "multiple_choice", "true_false", "fill_blank", "short_answer",
)


class IntelligentExamConfigInput(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    course_id: str = Field(min_length=1, max_length=128)
    review_task_id: str | None = Field(default=None, min_length=8, max_length=128)
    title: str = Field(default="今日智能组卷", min_length=1, max_length=256)
    theme: str = Field(default="今日学习检验", min_length=1, max_length=256)
    duration_minutes: int = Field(default=45, ge=5, le=240)
    chapter_ids: tuple[str, ...] = Field(default=(), max_length=50)
    knowledge_point_ids: tuple[str, ...] = Field(default=(), max_length=100)
    difficulty: Literal["easy", "balanced", "challenging", "adaptive"] = "adaptive"
    question_type_counts: dict[str, int] = Field(default_factory=dict)
    source_limit: int = Field(default=8, ge=1, le=30)

    @model_validator(mode="after")
    def valid_counts(self) -> "IntelligentExamConfigInput":
        unknown = sorted(set(self.question_type_counts) - set(LEARNER_EXAM_TYPES))
        if unknown:
            raise ValueError(f"unsupported learner exam question types: {unknown}")
        if any(not isinstance(value, int) or value < 0 or value > 50 for value in self.question_type_counts.values()):
            raise ValueError("question type counts must be integers between 0 and 50")
        total = sum(self.question_type_counts.values())
        if total < 1 or total > 100:
            raise ValueError("intelligent exam requires 1 to 100 questions")
        return self


class IntelligentExamQuestionOutput(StrictModel):
    """One model-authored question in the canonical assessment schema."""

    question_type: Literal[
        "single_choice", "multiple_choice", "true_false", "fill_blank", "short_answer"
    ]
    prompt: str = Field(min_length=1, max_length=20000)
    options: tuple[str, ...] = Field(default=(), max_length=20)
    answer_key: dict[str, Any]
    scoring_rule: dict[str, Any]
    explanation: str = Field(default="", max_length=20000)
    primary_knowledge_point_id: str = Field(min_length=1, max_length=64)
    source_ref_ids: tuple[str, ...] = Field(min_length=1, max_length=16)
    bloom_level: Literal["remember", "understand", "apply", "analyze", "evaluate", "create"] = "understand"
    expert_difficulty: float = Field(default=0.5, ge=0, le=1)


class IntelligentExamGenerationOutput(StrictModel):
    questions: tuple[IntelligentExamQuestionOutput, ...] = Field(min_length=1, max_length=100)


class HumanReviewInput(StrictModel):
    score: float = Field(ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    note: str = Field(min_length=1, max_length=4000)
    criterion_results: tuple[dict[str, Any], ...] = ()


def create_exam(
    session: Any, *, owner_public_id: str, payload: ExamCreateInput,
) -> tuple[DBAssessmentExam, DBAssessmentExamVersion, list[DBAssessmentExamItem]]:
    if payload.scheduled_open_at and payload.scheduled_close_at and payload.scheduled_close_at <= payload.scheduled_open_at:
        _fail("exam_schedule_invalid", "scheduled close must be later than open")
    seen = set()
    validated = []
    for position, item in enumerate(payload.items, start=1):
        if item.question_version_id in seen:
            _fail("exam_item_duplicate", "question version appears more than once")
        seen.add(item.question_version_id)
        version = session.query(DBAssessmentQuestionVersion).filter_by(id=item.question_version_id).first()
        if version is None:
            _fail("question_version_unknown", "exam question version does not exist")
        question = session.query(DBAssessmentQuestion).filter_by(id=version.question_id).one()
        if question.status != "approved" or question.course_id != payload.course_id:
            _fail("exam_question_forbidden", "exam questions must be approved in the same course")
        validated.append((position, item, version))
    exam = DBAssessmentExam(
        course_id=payload.course_id, owner_public_id=owner_public_id,
        generation_key=payload.generation_key,
        title=payload.title.strip(), duration_minutes=payload.duration_minutes,
        scheduled_open_at=payload.scheduled_open_at,
        scheduled_close_at=payload.scheduled_close_at,
    )
    session.add(exam)
    session.flush()
    manifest = {
        "configuration": payload.configuration,
        "items": [
            {"position": p, "question_version_id": i.question_version_id, "points": i.points, "required": i.required}
            for p, i, _ in validated
        ],
    }
    version = DBAssessmentExamVersion(
        exam_id=exam.id, version_number=1, instructions=payload.instructions,
        feedback_policy=payload.feedback_policy,
        total_points=sum(item.points for item in payload.items),
        manifest_hash=_hash(manifest), configuration=payload.configuration,
        generation_context=payload.generation_context, coverage=payload.coverage,
        created_by_public_id=owner_public_id,
    )
    session.add(version)
    session.flush()
    rows = [DBAssessmentExamItem(
        exam_version_id=version.id, question_version_id=item.question_version_id,
        position=position, points=item.points, required=item.required,
    ) for position, item, _ in validated]
    session.add_all(rows)
    session.flush()
    exam.current_version_id = version.id
    record_audit(session, actor_public_id=owner_public_id, action="assessment.exam.create",
                 object_type="assessment_exam", object_id=exam.id,
                 metadata={"course_id": exam.course_id, "item_count": len(rows), "manifest_hash": version.manifest_hash})
    return exam, version, rows


def _question_sources(session: Any, version: DBAssessmentQuestionVersion) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for source_id in list(version.source_ref_ids or []):
        ref = session.query(DBSourceRef).filter_by(id=source_id).first()
        if ref is None:
            continue
        document = session.query(DBSourceDocument).filter_by(id=ref.source_document_id).first()
        chapter = session.query(DBChapter).filter_by(id=ref.chapter_id).first() if ref.chapter_id else None
        sources.append({
            "id": ref.id,
            "source_document_id": ref.source_document_id,
            "document_title": document.title if document else "课程来源",
            "chapter_id": ref.chapter_id,
            "chapter_title": chapter.title if chapter else "",
            "page_number": ref.page_number,
            "location_label": ref.location_label or "",
            "quote": (ref.quote or "")[:240],
        })
    return sources


def intelligent_exam_context(
    session: Any, *, owner_public_id: str, course_id: str,
) -> dict[str, Any]:
    course = session.query(DBCourse).filter_by(id=course_id).first()
    if course is None:
        _fail("course_unknown", "course does not exist")
    from course_catalog import course_is_selectable
    if not course_is_selectable(session, course):
        _fail("course_unavailable", "course has no usable learning material")
    chapters = session.query(DBChapter).filter_by(course_id=course_id).order_by(
        DBChapter.position, DBChapter.id,
    ).all()
    chapter_ids = [row.id for row in chapters]
    links = session.query(DBChapterKnowledgePoint).filter(
        DBChapterKnowledgePoint.chapter_id.in_(chapter_ids or ["-"]),
    ).all()
    point_ids = sorted({row.knowledge_point_id for row in links})
    points = session.query(DBKnowledgePoint).filter(
        DBKnowledgePoint.id.in_(point_ids or ["-"]), DBKnowledgePoint.status == "active",
    ).order_by(DBKnowledgePoint.title, DBKnowledgePoint.id).all()
    chapter_by_point: dict[str, list[str]] = {}
    for link in links:
        chapter_by_point.setdefault(link.knowledge_point_id, []).append(link.chapter_id)

    versions: list[DBAssessmentQuestionVersion] = []
    type_counts = {question_type: 0 for question_type in LEARNER_EXAM_TYPES}
    source_ids: set[str] = set()
    for question in session.query(DBAssessmentQuestion).filter_by(
        course_id=course_id, status="approved",
    ).order_by(DBAssessmentQuestion.id).all():
        if question.question_type not in LEARNER_EXAM_TYPES or not question.current_version_id:
            continue
        version = session.query(DBAssessmentQuestionVersion).filter_by(id=question.current_version_id).first()
        if version is None:
            continue
        versions.append(version)
        type_counts[question.question_type] += 1
        source_ids.update(version.source_ref_ids or [])

    from app.profile_onboarding import latest_profile_snapshot_for_course, profile_influence_summary
    profile = latest_profile_snapshot_for_course(session, owner_public_id, course_id)
    recent_events = session.query(DBLearningEvent).filter_by(
        owner_public_id=owner_public_id, course_id=course_id,
    ).order_by(DBLearningEvent.occurred_at.desc(), DBLearningEvent.id.desc()).limit(20).all()
    return {
        "schema_version": "f6.intelligent-exam-context.v1",
        "course": {"id": course.id, "title": course.title, "version": course.version},
        "chapters": [
            {"id": row.id, "title": row.title, "position": row.position}
            for row in chapters
        ],
        "knowledge_points": [
            {
                "id": row.id,
                "title": row.title,
                "level": row.level,
                "chapter_ids": chapter_by_point.get(row.id, []),
            }
            for row in points
        ],
        "question_type_counts": type_counts,
        "approved_question_count": len(versions),
        "approved_source_count": len(source_ids),
        "profile_snapshot_id": profile.id if profile else None,
        "profile_version": profile.profile_version if profile else None,
        "profile_influence": profile_influence_summary(profile),
        "recent_evidence_count": sum(
            row.evidence_status == "accepted" for row in recent_events
        ),
        "difficulty_options": ["easy", "balanced", "challenging", "adaptive"],
        # Keep the legacy field, but make its value reflect the production
        # contract: configured student intelligent exams require the live
        # model; they do not silently fall back to local questions.
        "external_model_required": True,
        "llm_generation_required": True,
    }


def _exam_recent_event_cursor(events: list[DBLearningEvent]) -> str:
    return _hash([
        {
            "event_type": row.event_type,
            "object_type": row.object_type,
            "object_id": row.object_id,
            "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
            "evidence_status": row.evidence_status,
        }
        for row in events
        if row.evidence_status == "accepted"
    ])


def _build_exam_generation_blueprint(
    session: Any,
    *,
    config: IntelligentExamConfigInput,
    course: DBCourse,
    chapters: list[DBChapter],
    points: list[DBKnowledgePoint],
    profile: DBProfileSnapshot | None,
    profile_data: dict[str, Any],
    recent_events: list[DBLearningEvent],
) -> dict[str, Any]:
    from app.profile_onboarding import profile_influence_summary
    chapter_ids = tuple(config.chapter_ids) or tuple(row.id for row in chapters)
    chapter_by_id = {row.id: row for row in chapters}
    selected_chapters = [chapter_by_id[item] for item in chapter_ids if item in chapter_by_id]
    source_rows = session.query(DBSourceRef).filter(
        DBSourceRef.chapter_id.in_(chapter_ids or ("-",)),
    ).order_by(DBSourceRef.chapter_id, DBSourceRef.location_index, DBSourceRef.id).limit(
        config.source_limit,
    ).all()
    mastery = dict(profile_data.get("concept_mastery") or {})
    mastery_by_point = {}
    for point in points:
        value = mastery.get(point.id, mastery.get(point.title))
        mastery_by_point[point.id] = round(float(value), 4) if isinstance(value, (int, float)) else None
    mastery_values = [value for value in mastery_by_point.values() if value is not None]
    mastery_average = sum(mastery_values) / len(mastery_values) if mastery_values else 0.5
    source_snapshot = [
        {
            "id": row.id,
            "chapter_id": row.chapter_id,
            "location_label": row.location_label or "",
            "content_hash": row.content_hash,
            "quote": (row.quote or "")[:240],
        }
        for row in source_rows
    ]
    blueprint = {
        "schema_version": "f7.intelligent-exam-blueprint.v1",
        "course": {"id": course.id, "title": course.title, "version": course.version},
        "theme": config.theme,
        "chapter_ids": list(chapter_ids),
        "chapters": [
            {"id": row.id, "title": row.title, "position": row.position}
            for row in selected_chapters
        ],
        "knowledge_points": [
            {"id": row.id, "title": row.title, "mastery": mastery_by_point.get(row.id)}
            for row in points
        ],
        "question_type_counts": dict(config.question_type_counts),
        "difficulty": config.difficulty,
        "profile_snapshot_id": profile.id if profile else None,
        "profile_version": profile.profile_version if profile else None,
        "profile_influence": profile_influence_summary(profile),
        "profile_snapshot_hash": _hash(profile_data) if profile else None,
        "mastery_average": round(mastery_average, 4),
        "recent_evidence_count": sum(row.evidence_status == "accepted" for row in recent_events),
        "recent_event_cursor": _exam_recent_event_cursor(recent_events),
        "source_ref_ids": [row.id for row in source_rows],
        "source_snapshot_hash": _hash(source_snapshot),
    }
    blueprint["semantic_input_hash"] = _hash(blueprint)
    blueprint["dynamic_generation_ready"] = bool(points and source_rows)
    blueprint["source_snapshot"] = source_snapshot
    return blueprint


def _dynamic_exam_question_version(
    *,
    question_type: str,
    point: DBKnowledgePoint,
    chapter: DBChapter | None,
    source: DBSourceRef,
    blueprint: dict[str, Any],
    position: int,
) -> QuestionVersionInput:
    point_mastery = next(
        (item.get("mastery") for item in blueprint["knowledge_points"] if item["id"] == point.id),
        None,
    )
    if point_mastery is not None and point_mastery < 0.45:
        mastery_focus = "先确认概念边界、输入和输出，再进入判断。"
    elif point_mastery is not None and point_mastery > 0.75:
        mastery_focus = "在熟悉定义后补充指标解释和边界条件。"
    else:
        mastery_focus = "把定义连接到一个可检查的步骤，并说明为什么这样判断。"
    stem = f"在“{blueprint['theme']}”的复习中，针对知识点“{point.title}”，{mastery_focus}"
    topic = point.title.lower()
    if any(marker in topic for marker in ("coding agent", "mcp", "skill")):
        single_prompt = "智能体准备调用一个新的文件检索工具时，哪种做法最能保证调用可控且可复现？"
        single_options = (
            "A. 明确工具的输入输出结构、权限边界、超时与失败处理，再允许模型选择调用",
            "B. 把访问密钥直接写进对话，让模型自行决定如何执行",
            "C. 允许模型运行任意系统命令，并省略参数校验",
            "D. 忽略工具返回状态，只根据模型原先的猜测继续回答",
        )
        statement = "MCP 可以规范工具与上下文的连接方式，Skill 可以封装可复用操作，但权限、参数校验和失败处理仍需显式约束。"
        fill_answer = "工具输入输出结构与权限边界"
        reference = "应先定义工具 Schema、权限和超时，再校验调用参数与返回状态，并为失败提供可见恢复路径。"
    elif any(marker in topic for marker in ("优化算法", "正则化", "训练稳定", "梯度下降")):
        single_prompt = "训练损失持续下降而验证损失连续上升时，下一步最合理的处理是什么？"
        single_options = (
            "A. 保留验证指标最好的检查点，并联合调整正则化强度、早停耐心值和学习率",
            "B. 只要训练损失下降就无限增加训练轮次",
            "C. 删除验证集，改用训练集判断泛化能力",
            "D. 同时改变数据、模型和指标后直接比较最后一轮结果",
        )
        statement = "L2 正则化通过限制权重规模降低模型复杂度，早停通过监控验证指标限制继续训练的时长，两者可以联合使用。"
        fill_answer = "验证集指标"
        reference = "应同时观察训练与验证曲线；出现持续分离时保留最佳检查点，并分别调节正则化、早停和学习率。"
    elif any(marker in topic for marker in ("rag", "文档解析", "切分", "混合检索")):
        single_prompt = "课程文档解析缺页后，即使混合检索已完成重排，系统最合理的处理是什么？"
        single_options = (
            "A. 标记证据不足并回查解析覆盖率、切分和来源定位，修复后再检索",
            "B. 把首个候选直接当作完整证据生成确定结论",
            "C. 只提高向量权重，默认缺失页面已经被补回",
            "D. 隐藏来源信息，用更长的回答弥补正文缺失",
        )
        statement = "重排只能调整已召回候选的顺序，不能补回解析阶段丢失的正文，因此关键来源缺失时应明确证据不足。"
        fill_answer = "解析覆盖率与来源定位"
        reference = "应按解析、切分、索引、召回和重排逐层检查；关键来源缺失时拒绝强结论，修复原文后重新评测。"
    elif all(marker in topic for marker in ("人工智能", "机器学习", "深度学习")):
        single_prompt = "下列对人工智能、机器学习和深度学习关系的表述哪一项准确？"
        single_options = (
            "A. 深度学习通常被视为机器学习的一类方法，机器学习又是实现人工智能目标的重要途径之一",
            "B. 三者完全等价，只是名称不同",
            "C. 机器学习只包含人工编写规则，不从数据中学习",
            "D. 深度学习覆盖所有人工智能方法，因此不需要数据和评价指标",
        )
        statement = "深度学习通常属于机器学习方法，而机器学习是实现人工智能能力的途径之一，但人工智能还包含其他方法。"
        fill_answer = "机器学习"
        reference = "应说明三者是目标与方法层级关系：人工智能范围更广，机器学习从数据中学习，深度学习使用多层神经网络。"
    else:
        single_prompt = "哪种学习判断最能证明自己真正理解了这个知识点？"
        single_options = (
            "A. 能说明核心定义、成立条件、最小例子和失效边界，并用结果复核",
            "B. 只记住术语名称，不说明输入与输出",
            "C. 跳过前提，直接套用结论到所有场景",
            "D. 用无关章节的例子替代当前知识点",
        )
        statement = "只有同时说明核心定义、成立条件、可检验例子和失效边界，才能形成较完整的理解证据。"
        fill_answer = point.title
        reference = f"应围绕 {point.title} 说明定义、输入输出、机制、成立条件、例子与边界，并给出可复核结果。"
    if question_type == "single_choice":
        prompt = stem + single_prompt
        options = single_options
        answer_key = {"choice": "A"}
        scoring_rule = {"type": "exact", "version": "f7.dynamic-objective-v1"}
    elif question_type == "multiple_choice":
        prompt = stem + "请选择所有能形成可靠学习证据的做法。"
        options = (
            f"A. 用自己的话解释{point.title}的机制与成立条件",
            "B. 固定输入和评价方式，用最小例子复核输出",
            "C. 忽略失败边界，只保留成功结果",
            "D. 用无关知识点替代当前问题",
        )
        answer_key = {"choices": ["A", "B"]}
        scoring_rule = {"type": "exact", "version": "f7.dynamic-objective-v1", "partial_credit": False}
    elif question_type == "true_false":
        prompt = stem + f"判断：{statement}"
        options = ()
        answer_key = {"value": True}
        scoring_rule = {"type": "exact", "version": "f7.dynamic-objective-v1"}
    elif question_type == "fill_blank":
        prompt = stem + "填空：完成本题判断时首先需要核对的是____。"
        options = ()
        answer_key = {"blanks": [fill_answer]}
        scoring_rule = {"type": "normalized_text", "version": "f7.dynamic-objective-v1"}
    else:
        prompt = stem + "请用自己的话说明应如何验证该结论，并指出一个失效边界。"
        options = ()
        answer_key = {
            "reference_answer": (
                reference
            ),
        }
        scoring_rule = {
            "version": "f7.dynamic-rubric-v1",
            "correct_threshold": 0.6,
            "criteria": [
                {"id": "concept", "label": "概念、机制与成立条件", "weight": 0.5},
                {"id": "verification", "label": "验证步骤与失效边界", "weight": 0.5},
            ],
        }
    explanation_seed = ""
    if question_type == "true_false":
        explanation_seed = (
            f"这道题考查{point.title}。题干判断为正确。{statement} 原因是：{reference} "
            "自检时应分别保持其他条件不变，只改变题干中的一个关键条件，再比较结论是否改变；"
            "最后把原条件代回训练过程或评价结果，确认结论与题干完全一致。"
        )
    learner_explanation = learner_safe_explanation(
        explanation_seed,
        prompt=prompt,
        options=options,
        answer_key=answer_key,
        question_type=question_type,
        knowledge_point=point.title,
    )
    return QuestionVersionInput(
        prompt=prompt,
        options=options,
        answer_key=answer_key,
        scoring_rule=scoring_rule,
        explanation=learner_explanation,
        misconception_tags=(f"f7-{point.id}", "contextual-generation"),
        primary_knowledge_point_id=point.id,
        bloom_level="apply" if question_type in {"short_answer", "fill_blank"} else "understand",
        expert_difficulty={"easy": 0.3, "balanced": 0.5, "challenging": 0.75, "adaptive": 0.55}[blueprint["difficulty"]],
        source_ref_ids=(source.id,),
    )


def _generate_dynamic_exam_items(
    session: Any,
    *,
    owner_public_id: str,
    config: IntelligentExamConfigInput,
    blueprint: dict[str, Any],
    chapters: list[DBChapter],
    points: list[DBKnowledgePoint],
) -> list[tuple[DBAssessmentQuestionVersion, DBAssessmentQuestion]]:
    if not blueprint.get("dynamic_generation_ready"):
        return []
    source_rows = session.query(DBSourceRef).filter(
        DBSourceRef.id.in_(blueprint["source_ref_ids"] or ["-"]),
    ).order_by(DBSourceRef.id).all()
    chapter_by_id = {row.id: row for row in chapters}
    selected: list[tuple[DBAssessmentQuestionVersion, DBAssessmentQuestion]] = []
    position = 0
    for question_type in LEARNER_EXAM_TYPES:
        requested = int(config.question_type_counts.get(question_type, 0))
        for offset in range(requested):
            point = points[(position + offset) % len(points)]
            source = source_rows[(position + offset) % len(source_rows)]
            version_input = _dynamic_exam_question_version(
                question_type=question_type,
                point=point,
                chapter=chapter_by_id.get(source.chapter_id),
                source=source,
                blueprint=blueprint,
                position=position + offset,
            )
            question, version = create_question_version(
                session,
                owner_public_id=owner_public_id,
                course_id=config.course_id,
                question_type=question_type,
                origin="derived",
                version=version_input,
            )
            question.status = "approved"
            selected.append((version, question))
        position += requested
    return selected


def _generate_llm_exam_items(
    session: Any,
    *,
    owner_public_id: str,
    config: IntelligentExamConfigInput,
    blueprint: dict[str, Any],
    points: list[DBKnowledgePoint],
    llm: Any,
) -> tuple[list[tuple[DBAssessmentQuestionVersion, DBAssessmentQuestion]], dict[str, Any]]:
    """Generate and persist one source-bound intelligent exam with the live model."""
    _require_exam_model(llm)
    schema = _canonical(IntelligentExamGenerationOutput.model_json_schema())
    system_prompt = (
        "你是 EduMatrix 智能组卷出题专家。只输出符合 JSON Schema 的原始 JSON，不要 Markdown。"
        "严格按照题型配额生成题目；每题只能使用输入提供的课程知识点和 source_ref_id。"
        "选择题必须提供互不重复的选项，并严格使用 answer_key={choice:'A'}（多选为 choices:['A','B']）；"
        "判断题严格使用 answer_key={value:true}，填空题严格使用 answer_key={blanks:['答案']}。"
        "简答题严格使用 answer_key={reference_answer:'参考答案'}，并把评分量规放在"
        "scoring_rule={version:'rubric-ml-v1',correct_threshold:0.6,criteria:[{id:'criterion',label:'标准',weight:1.0}]}；"
        "不要把 criteria 或 correct_threshold 放入 answer_key。"
        "题干、答案、解析和量规必须针对给定课程来源编写，不能编造未提供的教材事实。"
        "解析是学习者提交后直接看到的教学内容，必须先给结论，再解释正确选项为何满足题干，"
        "并逐项说明主要干扰项为何不成立，补充适用条件、常见误区或一个最小例子；"
        "禁止把来源核验、版本、哈希、蓝图或证据绑定话术写进 explanation。"
        "不要输出 prompt、思维链、reasoning_content、密钥或内部日志。"
        f" JSON Schema: {schema}"
    )
    user_prompt = _canonical({
        "task": "intelligent_exam_generation",
        "course": blueprint.get("course"),
        "theme": config.theme,
        "difficulty": config.difficulty,
        "question_type_counts": dict(config.question_type_counts),
        "chapters": blueprint.get("chapters", []),
        "knowledge_points": blueprint.get("knowledge_points", []),
        "profile_influence": blueprint.get("profile_influence", []),
        "sources": blueprint.get("source_snapshot", []),
    })
    try:
        result = _run_async(execute_registered_structured_call(
            session,
            backend=llm,
            capability=Capability.QUIZ,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            role="智能组卷出题",
            operation="intelligent_exam_generation",
            response_model=IntelligentExamGenerationOutput,
            response_validator=lambda value: _validate_llm_exam_output(
                value, config=config, blueprint=blueprint,
            ),
            owner_public_id=owner_public_id,
            course_id=config.course_id,
            trace_id=f"intelligent-exam-generate:{config.idempotency_key}",
            output_constraints=OutputConstraints(
                format="json",
                max_length=200000,
                source_scope=tuple(blueprint.get("source_ref_ids", [])),
                safety_boundary="Only the selected course chapters, knowledge points and source excerpts may be used.",
            ),
        ))
    except FormalExamError:
        raise
    except M5CapabilityError as exc:
        _fail("intelligent_exam_generation_failed", f"真实模型出题失败：{exc.code}")
    except Exception as exc:
        _fail("intelligent_exam_generation_failed", "真实模型出题失败，请稍后重试")
    if result.model != "deepseek-v4-flash" or result.fallback_used:
        _fail("intelligent_exam_model_policy_invalid", "智能组卷出题未使用受治理的 deepseek-v4-flash 模型")
    output = _validate_llm_exam_output(result.structured_output or {}, config=config, blueprint=blueprint)
    point_by_id = {row.id: row for row in points}
    selected: list[tuple[DBAssessmentQuestionVersion, DBAssessmentQuestion]] = []
    for item in output.questions:
        point = point_by_id.get(item.primary_knowledge_point_id)
        if point is None:
            _fail("intelligent_exam_llm_knowledge_point_invalid", "模型题目绑定了当前范围之外的知识点")
        version_input = QuestionVersionInput(
            prompt=item.prompt,
            options=item.options,
            answer_key=item.answer_key,
            scoring_rule=item.scoring_rule,
            explanation=learner_safe_explanation(
                item.explanation,
                prompt=item.prompt,
                options=item.options,
                answer_key=item.answer_key,
                question_type=item.question_type,
                knowledge_point=point.title,
            ),
            primary_knowledge_point_id=item.primary_knowledge_point_id,
            bloom_level=item.bloom_level,
            expert_difficulty=item.expert_difficulty,
            source_ref_ids=item.source_ref_ids,
        )
        try:
            question, version = create_question_version(
                session,
                owner_public_id=owner_public_id,
                course_id=config.course_id,
                question_type=item.question_type,
                origin="ai_generated",
                version=version_input,
            )
        except Exception as exc:
            _fail("intelligent_exam_llm_question_invalid", "模型题目不符合统一题目协议")
        question.status = "approved"
        selected.append((version, question))
    return selected, {
        "model": result.model,
        "call_id": result.call_id,
        "trace_id": result.trace_id,
    }


def build_intelligent_exam_input(
    session: Any, *, owner_public_id: str, config: IntelligentExamConfigInput,
    llm: Any | None = None,
) -> ExamCreateInput:
    course = session.query(DBCourse).filter_by(id=config.course_id).first()
    if course is None:
        _fail("course_unknown", "course does not exist")
    from course_catalog import course_is_selectable
    if not course_is_selectable(session, course):
        _fail("course_unavailable", "course has no usable learning material")

    course_chapters = session.query(DBChapter).filter_by(course_id=config.course_id).all()
    course_chapter_ids = {row.id for row in course_chapters}
    unknown_chapters = sorted(set(config.chapter_ids) - course_chapter_ids)
    if unknown_chapters:
        _fail("exam_chapter_forbidden", "selected chapters are outside the current course")
    links = session.query(DBChapterKnowledgePoint).filter(
        DBChapterKnowledgePoint.chapter_id.in_(course_chapter_ids or {"-"}),
    ).all()
    course_point_ids = {row.knowledge_point_id for row in links}
    unknown_points = sorted(set(config.knowledge_point_ids) - course_point_ids)
    if unknown_points:
        _fail("exam_knowledge_point_forbidden", "selected knowledge points are outside the current course")
    chapter_point_ids = {
        row.knowledge_point_id for row in links if not config.chapter_ids or row.chapter_id in config.chapter_ids
    }
    selected_point_ids = set(config.knowledge_point_ids) or chapter_point_ids

    from app.profile_onboarding import latest_profile_snapshot_for_course, profile_influence_summary
    profile = latest_profile_snapshot_for_course(session, owner_public_id, config.course_id)
    profile_data = dict(profile.snapshot or {}) if profile else {}
    mastery = dict(profile_data.get("concept_mastery") or {})
    mastery_values = [float(value) for value in mastery.values() if isinstance(value, (int, float))]
    mastery_average = sum(mastery_values) / len(mastery_values) if mastery_values else 0.5
    target_difficulty = {
        "easy": 0.3,
        "balanced": 0.5,
        "challenging": 0.75,
        "adaptive": max(0.3, min(0.8, 0.35 + mastery_average * 0.45)),
    }[config.difficulty]
    recent_events = session.query(DBLearningEvent).filter_by(
        owner_public_id=owner_public_id, course_id=config.course_id,
    ).order_by(DBLearningEvent.occurred_at.desc(), DBLearningEvent.id.desc()).limit(30).all()
    recent_object_ids = {row.object_id for row in recent_events if row.evidence_status == "accepted"}

    selected_scope = set(config.chapter_ids) or course_chapter_ids
    selected_chapter_rows = [row for row in course_chapters if row.id in selected_scope]
    blueprint_point_ids = selected_point_ids or course_point_ids
    point_rows = session.query(DBKnowledgePoint).filter(
        DBKnowledgePoint.id.in_(list(blueprint_point_ids) or ["-"]),
        DBKnowledgePoint.status == "active",
    ).order_by(DBKnowledgePoint.title, DBKnowledgePoint.id).all()
    blueprint = _build_exam_generation_blueprint(
        session,
        config=config,
        course=course,
        chapters=selected_chapter_rows,
        points=point_rows,
        profile=profile,
        profile_data=profile_data,
        recent_events=recent_events,
    )
    generation_meta: dict[str, Any] = {}
    if llm is not None:
        dynamic_items, generation_meta = _generate_llm_exam_items(
            session,
            owner_public_id=owner_public_id,
            config=config,
            blueprint=blueprint,
            points=point_rows,
            llm=llm,
        )
    else:
        # Direct library callers and historical fixtures can still construct a
        # deterministic blueprint explicitly.  The production API always
        # supplies the governed live model below.
        dynamic_items = _generate_dynamic_exam_items(
            session,
            owner_public_id=owner_public_id,
            config=config,
            blueprint=blueprint,
            chapters=selected_chapter_rows,
            points=point_rows,
        )
    if dynamic_items:
        total = len(dynamic_items)
        base_points = round(100 / total, 2)
        item_points = [base_points] * total
        item_points[-1] = round(100 - sum(item_points[:-1]), 2)
        point_counts: dict[str, int] = {}
        type_counts: dict[str, int] = {}
        for version, question in dynamic_items:
            point_id = version.primary_knowledge_point_id or "unbound"
            point_counts[point_id] = point_counts.get(point_id, 0) + 1
            type_counts[question.question_type] = type_counts.get(question.question_type, 0) + 1
        point_titles = {row.id: row.title for row in point_rows}
        generation_mode = "llm" if llm is not None else "deterministic_blueprint"
        generation_context = {
            "schema_version": "f7.intelligent-exam-generation.v2",
            "generation_mode": generation_mode,
            "external_model_used": llm is not None,
            "model_status": {
                "available": llm is not None,
                "model": generation_meta.get("model") if llm is not None else None,
                "reason": (
                    "题目已由受治理模型根据当前课程范围生成。"
                    if llm is not None
                    else "题目已根据当前课程知识点、画像摘要和学习记录生成，并在作答前冻结。"
                ),
            },
            "question_bank_fallback": {
                "available": llm is None,
                "used": False,
                "reason": "生产配置式智能组卷不回退题库" if llm is not None else "semantic blueprint produced source-bound questions; approved bank remains the recovery path",
            },
            "model_call": generation_meta,
            "blueprint": blueprint,
            "generated_question_version_ids": [version.id for version, _ in dynamic_items],
            "profile_snapshot_id": profile.id if profile else None,
            "profile_version": profile.profile_version if profile else None,
            "profile_influence": blueprint["profile_influence"],
            "mastery_average": blueprint["mastery_average"],
            "recent_evidence_count": blueprint["recent_evidence_count"],
            "recent_event_cursor": blueprint["recent_event_cursor"],
            "source_ref_ids": blueprint["source_ref_ids"],
            "request_hash": _hash(config.model_dump(mode="json")),
        }
        coverage = {
            "question_type_counts": type_counts,
            "knowledge_points": [
                {"id": point_id, "title": point_titles.get(point_id, "未绑定知识点"), "question_count": count}
                for point_id, count in sorted(point_counts.items())
            ],
            "source_ref_count": len(blueprint["source_ref_ids"]),
            "question_count": total,
            "generation_mode": generation_mode,
        }
        return ExamCreateInput(
            course_id=config.course_id,
            title=config.title,
            instructions=(
                f"主题：{config.theme}。请按题目顺序完成作答；不会的题可以先标记，全部保存后再提交。"
                if llm is not None else
                f"主题：{config.theme}。请先读清题目条件，再完成作答；全部保存后即可提交。"
            ),
            duration_minutes=config.duration_minutes,
            feedback_policy="after_submission",
            generation_key=config.idempotency_key,
            configuration=config.model_dump(mode="json"),
            generation_context=generation_context,
            coverage=coverage,
            items=tuple(
                ExamItemInput(question_version_id=version.id, points=item_points[index], required=True)
                for index, (version, _) in enumerate(dynamic_items)
            ),
        )

    candidates: dict[str, list[tuple[float, DBAssessmentQuestionVersion, DBAssessmentQuestion]]] = {
        question_type: [] for question_type in LEARNER_EXAM_TYPES
    }
    for question in session.query(DBAssessmentQuestion).filter_by(
        course_id=config.course_id, status="approved",
    ).order_by(DBAssessmentQuestion.id).all():
        if question.question_type not in candidates or not question.current_version_id:
            continue
        version = session.query(DBAssessmentQuestionVersion).filter_by(id=question.current_version_id).first()
        if version is None or not version.source_ref_ids:
            continue
        if selected_point_ids and version.primary_knowledge_point_id not in selected_point_ids:
            continue
        difficulty = float(
            version.measured_difficulty
            if version.measured_difficulty is not None
            else version.expert_difficulty if version.expert_difficulty is not None else 0.5
        )
        contextual = 1.0 - abs(difficulty - target_difficulty)
        if version.id in recent_object_ids or version.primary_knowledge_point_id in recent_object_ids:
            contextual += 0.25
        contextual += int(_hash(f"{owner_public_id}:{config.theme}:{version.id}")[:8], 16) / 0xFFFFFFFF / 100
        candidates[question.question_type].append((contextual, version, question))
    for values in candidates.values():
        values.sort(key=lambda item: (-item[0], item[1].id))

    selected: list[tuple[DBAssessmentQuestionVersion, DBAssessmentQuestion]] = []
    selected_sources: set[str] = set()
    shortages: list[str] = []
    for question_type in LEARNER_EXAM_TYPES:
        requested = int(config.question_type_counts.get(question_type, 0))
        if not requested:
            continue
        chosen = 0
        for _, version, question in candidates[question_type]:
            introduced = set(version.source_ref_ids or []) - selected_sources
            if len(selected_sources | introduced) > config.source_limit:
                continue
            selected.append((version, question))
            selected_sources.update(version.source_ref_ids or [])
            chosen += 1
            if chosen == requested:
                break
        if chosen != requested:
            shortages.append(f"{question_type}: requested {requested}, available {chosen}")
    if shortages:
        _fail("intelligent_exam_sources_insufficient", "当前范围题源不足：" + "; ".join(shortages))

    total = len(selected)
    base_points = round(100 / total, 2)
    item_points = [base_points] * total
    item_points[-1] = round(100 - sum(item_points[:-1]), 2)
    point_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    for version, question in selected:
        point_id = version.primary_knowledge_point_id or "unbound"
        point_counts[point_id] = point_counts.get(point_id, 0) + 1
        type_counts[question.question_type] = type_counts.get(question.question_type, 0) + 1
    point_titles = {
        row.id: row.title
        for row in session.query(DBKnowledgePoint).filter(
            DBKnowledgePoint.id.in_(list(point_counts) or ["-"]),
        ).all()
    }
    configuration = config.model_dump(mode="json")
    generation_context = {
        "schema_version": "f6.intelligent-exam-generation.v1",
        "algorithm": "f6.local-contextual-selector.v1",
        "generation_mode": "question_bank_fallback",
        "external_model_used": False,
        "question_bank_fallback": {
            "available": True,
            "used": True,
            "reason": "semantic blueprint could not produce source-bound questions for the selected scope",
        },
        "blueprint": blueprint,
        "profile_snapshot_id": profile.id if profile else None,
        "profile_version": profile.profile_version if profile else None,
        "profile_influence": blueprint.get("profile_influence") or [],
        "mastery_average": round(mastery_average, 4),
        "recent_evidence_count": sum(row.evidence_status == "accepted" for row in recent_events),
        "recent_event_cursor": _exam_recent_event_cursor(recent_events),
        "source_ref_ids": sorted(selected_sources),
        "request_hash": _hash(configuration),
    }
    coverage = {
        "question_type_counts": type_counts,
        "knowledge_points": [
            {"id": point_id, "title": point_titles.get(point_id, "未绑定知识点"), "question_count": count}
            for point_id, count in sorted(point_counts.items())
        ],
        "source_ref_count": len(selected_sources),
        "question_count": total,
    }
    return ExamCreateInput(
        course_id=config.course_id,
        title=config.title,
        instructions=f"主题：{config.theme}。请先读清题目条件，再完成作答；全部保存后即可提交。",
        duration_minutes=config.duration_minutes,
        feedback_policy="after_submission",
        generation_key=config.idempotency_key,
        configuration=configuration,
        generation_context=generation_context,
        coverage=coverage,
        items=tuple(
            ExamItemInput(question_version_id=version.id, points=item_points[index], required=True)
            for index, (version, _) in enumerate(selected)
        ),
    )


_EXAM_TRANSITIONS = {
    "draft": {"published"}, "published": {"open", "archived"},
    "open": {"closed"}, "closed": {"archived"}, "archived": set(),
}


def transition_exam(
    session: Any, *, exam: DBAssessmentExam, target: str,
    expected_lock_version: int, actor_public_id: str,
) -> DBAssessmentExam:
    if exam.lock_version != expected_lock_version:
        _fail("exam_lock_conflict", "exam changed since it was loaded")
    if target not in _EXAM_TRANSITIONS.get(exam.status, set()):
        _fail("exam_transition_invalid", f"cannot transition exam from {exam.status} to {target}")
    exam.status = target
    exam.lock_version += 1
    session.flush()
    record_audit(session, actor_public_id=actor_public_id, action="assessment.exam.transition",
                 object_type="assessment_exam", object_id=exam.id,
                 metadata={"target": target, "lock_version": exam.lock_version})
    return exam


def assign_sitting(
    session: Any, *, exam: DBAssessmentExam, learner_public_id: str,
    actor_public_id: str,
) -> tuple[DBAssessmentExamSitting, bool]:
    if exam.status not in {"published", "open"}:
        _fail("exam_not_assignable", "exam must be published before assignment")
    existing = session.query(DBAssessmentExamSitting).filter_by(exam_id=exam.id, owner_public_id=learner_public_id).first()
    if existing:
        return existing, False
    row = DBAssessmentExamSitting(
        exam_id=exam.id, exam_version_id=exam.current_version_id,
        owner_public_id=learner_public_id, status="assigned",
    )
    session.add(row)
    session.flush()
    record_audit(session, actor_public_id=actor_public_id, action="assessment.exam.assign",
                 object_type="assessment_exam_sitting", object_id=row.id,
                 metadata={"exam_id": exam.id, "learner_public_id": learner_public_id})
    return row, True


def start_sitting(
    session: Any, *, sitting: DBAssessmentExamSitting, owner_public_id: str,
    expected_lock_version: int, now: datetime | None = None,
) -> DBAssessmentExamSitting:
    now = now or _utcnow()
    if sitting.owner_public_id != owner_public_id:
        _fail("sitting_forbidden", "exam sitting belongs to another owner")
    if sitting.lock_version != expected_lock_version:
        _fail("sitting_lock_conflict", "exam sitting changed since it was loaded")
    exam = session.query(DBAssessmentExam).filter_by(id=sitting.exam_id).one()
    if exam.status != "open":
        _fail("exam_not_open", "exam is not open")
    if exam.scheduled_open_at and now < exam.scheduled_open_at:
        _fail("exam_not_open", "exam open time has not arrived")
    if exam.scheduled_close_at and now >= exam.scheduled_close_at:
        _fail("exam_closed", "exam close time has passed")
    if sitting.status == "in_progress":
        return sitting
    if sitting.status != "assigned":
        _fail("sitting_start_invalid", "only an assigned sitting can start")
    sitting.status = "in_progress"
    sitting.started_at = now
    duration_due = now + timedelta(minutes=exam.duration_minutes)
    sitting.due_at = min(duration_due, exam.scheduled_close_at) if exam.scheduled_close_at else duration_due
    sitting.lock_version += 1
    session.flush()
    return sitting


def _draft_content(payload: FormalResponseInput) -> dict[str, Any]:
    return {
        "answer": payload.answer,
        "confidence": payload.confidence,
        "duration_seconds": payload.duration_seconds,
    }


def save_formal_response_draft(
    session: Any, *, sitting: DBAssessmentExamSitting, owner_public_id: str,
    payload: FormalResponseInput, now: datetime | None = None,
) -> tuple[DBAssessmentExamResponseDraft, bool]:
    now = now or _utcnow()
    if sitting.owner_public_id != owner_public_id:
        _fail("sitting_forbidden", "exam sitting belongs to another owner")
    if sitting.status != "in_progress":
        _fail("sitting_not_in_progress", "exam sitting is not accepting answers")
    if sitting.due_at and now > sitting.due_at:
        _fail("sitting_deadline_passed", "exam sitting deadline has passed")
    item = session.query(DBAssessmentExamItem).filter_by(
        id=payload.exam_item_id, exam_version_id=sitting.exam_version_id,
    ).first()
    if item is None:
        _fail("exam_item_forbidden", "question is not part of this frozen exam version")
    content = _draft_content(payload)
    content_hash = _hash(content)
    existing = session.query(DBAssessmentExamResponseDraft).filter_by(
        owner_public_id=owner_public_id, idempotency_key=payload.idempotency_key,
    ).first()
    if existing is not None:
        if (
            existing.sitting_id != sitting.id
            or existing.exam_item_id != item.id
            or existing.content_hash != content_hash
        ):
            _fail("exam_draft_idempotency_conflict", "save key is bound to another answer")
        return existing, False
    latest = session.query(DBAssessmentExamResponseDraft).filter_by(
        sitting_id=sitting.id, exam_item_id=item.id,
    ).order_by(
        DBAssessmentExamResponseDraft.revision.desc(),
        DBAssessmentExamResponseDraft.id.desc(),
    ).first()
    row = DBAssessmentExamResponseDraft(
        sitting_id=sitting.id,
        exam_item_id=item.id,
        owner_public_id=owner_public_id,
        idempotency_key=payload.idempotency_key,
        revision=(latest.revision + 1 if latest else 1),
        answer=payload.answer,
        confidence=payload.confidence,
        duration_seconds=payload.duration_seconds,
        content_hash=content_hash,
        saved_at=now,
    )
    session.add(row)
    session.flush()
    return row, True


def latest_formal_response_drafts(
    session: Any, *, sitting_id: str,
) -> list[DBAssessmentExamResponseDraft]:
    rows = session.query(DBAssessmentExamResponseDraft).filter_by(
        sitting_id=sitting_id,
    ).order_by(
        DBAssessmentExamResponseDraft.exam_item_id,
        DBAssessmentExamResponseDraft.revision.desc(),
        DBAssessmentExamResponseDraft.id.desc(),
    ).all()
    latest: dict[str, DBAssessmentExamResponseDraft] = {}
    for row in rows:
        latest.setdefault(row.exam_item_id, row)
    return sorted(latest.values(), key=lambda row: row.exam_item_id)


def formal_draft_payload(row: DBAssessmentExamResponseDraft) -> dict[str, Any]:
    return {
        "id": row.id,
        "exam_item_id": row.exam_item_id,
        "revision": row.revision,
        "answer": row.answer or {},
        "confidence": row.confidence,
        "duration_seconds": row.duration_seconds,
        "content_hash": row.content_hash,
        "saved_at": row.saved_at.isoformat() if row.saved_at else None,
    }


def _grade_subjective_with_llm(
    session: Any, *, attempt: DBAssessmentAttempt, version: DBAssessmentQuestionVersion,
    owner_public_id: str, llm: Any,
) -> DBAssessmentGradingResult:
    _require_exam_model(llm)
    system_prompt, user_prompt, rubric_version, rubric = ai_grading_prompt(version, attempt.answer or {})
    base_rubric_version = rubric_version
    prior_count = session.query(DBAssessmentGradingResult).filter(
        DBAssessmentGradingResult.attempt_id == attempt.id,
        DBAssessmentGradingResult.grader_type == "ai",
    ).count()
    grading_rubric_version = (
        base_rubric_version
        if prior_count == 0
        else f"{base_rubric_version}:retry-{prior_count}"
    )
    user_payload = json.loads(user_prompt)
    user_payload["course_sources"] = _question_sources(session, version)
    user_prompt = _canonical(user_payload)
    try:
        result = _run_async(execute_registered_structured_call(
            session,
            backend=llm,
            capability=Capability.QUIZ,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            role="智能组卷主观题评分",
            operation="intelligent_exam_subjective_grading",
            response_model=AIGradingOutput,
            owner_public_id=owner_public_id,
            course_id=attempt.course_id,
            trace_id=f"intelligent-exam-grade:{attempt.id}",
            output_constraints=OutputConstraints(
                format="json",
                max_length=60000,
                source_scope=tuple(version.source_ref_ids or ()),
                safety_boundary="Only the frozen exam question, rubric and learner answer may be used.",
            ),
        ))
        if result.model != "deepseek-v4-flash" or result.fallback_used:
            raise FormalExamError(
                "intelligent_exam_model_policy_invalid",
                "智能组卷主观题评分未使用受治理的 deepseek-v4-flash 模型",
            )
        output = AIGradingOutput.model_validate(result.structured_output)
        grading, _ = persist_ai_grading(
            session,
            attempt_id=attempt.id,
            output=output,
            trace_id=result.trace_id,
            created_by_public_id=owner_public_id,
            rubric_version_override=grading_rubric_version,
        )
        return grading
    except FormalExamError:
        raise
    except (M5CapabilityError, Exception) as exc:
        # Do not turn an unavailable model into a zero score.  Persist the
        # failed grading row so the report can explain the pending state if a
        # caller chooses to inspect the in-flight transaction.
        persist_failed_ai_grading(
            session,
            attempt_id=attempt.id,
            rubric_version=grading_rubric_version,
            rubric_snapshot={"criteria": list(rubric)},
            trace_id=f"intelligent-exam-grade:{attempt.id}",
            error_code="ai_grading_unavailable",
        )
        raise FormalExamError(
            "intelligent_exam_subjective_grading_failed",
            "智能组卷主观题 AI 判分失败，请稍后重试",
        ) from exc


def finalize_formal_response_drafts(
    session: Any, *, sitting: DBAssessmentExamSitting, owner_public_id: str,
    llm: Any | None = None,
) -> list[DBAssessmentAttempt]:
    if sitting.owner_public_id != owner_public_id:
        _fail("sitting_forbidden", "exam sitting belongs to another owner")
    items = session.query(DBAssessmentExamItem).filter_by(
        exam_version_id=sitting.exam_version_id,
    ).order_by(DBAssessmentExamItem.position).all()
    drafts = {row.exam_item_id: row for row in latest_formal_response_drafts(session, sitting_id=sitting.id)}
    missing = [item.id for item in items if item.required and item.id not in drafts]
    if missing:
        _fail("sitting_incomplete", "all required exam items must be answered")
    attempts: list[DBAssessmentAttempt] = []
    for item in items:
        response = session.query(DBAssessmentExamResponse).filter_by(
            sitting_id=sitting.id, exam_item_id=item.id,
        ).first()
        if response is not None:
            attempts.append(session.query(DBAssessmentAttempt).filter_by(id=response.attempt_id).one())
            continue
        draft = drafts.get(item.id)
        if draft is None:
            continue
        version = session.query(DBAssessmentQuestionVersion).filter_by(id=item.question_version_id).one()
        question = session.query(DBAssessmentQuestion).filter_by(id=version.question_id).one()
        if question.question_type == "code":
            _fail("intelligent_exam_code_unsupported", "learner intelligent exams do not include code questions")
        attempt, _ = record_attempt(
            session,
            owner_public_id=owner_public_id,
            attempt=AttemptInput(
                question_version_id=item.question_version_id,
                idempotency_key=f"formal-final:{sitting.id}:{item.id}",
                mode="formal",
                answer=draft.answer or {},
                confidence=draft.confidence,
                duration_seconds=draft.duration_seconds,
            ),
            trusted_final_grade=None,
        )
        if question.question_type in {"short_answer", "open_task"}:
            if llm is None:
                _fail(
                    "intelligent_exam_grading_model_required",
                    "智能组卷主观题判分必须提供真实 deepseek-v4-flash 模型",
                )
            _grade_subjective_with_llm(
                session,
                attempt=attempt,
                version=version,
                owner_public_id=owner_public_id,
                llm=llm,
            )
        response = DBAssessmentExamResponse(
            sitting_id=sitting.id, exam_item_id=item.id, attempt_id=attempt.id,
        )
        session.add(response)
        session.flush()
        attempts.append(attempt)
    return attempts


def submit_formal_response(
    session: Any, *, sitting: DBAssessmentExamSitting, owner_public_id: str,
    payload: FormalResponseInput, now: datetime | None = None,
) -> tuple[DBAssessmentExamResponse, DBAssessmentAttempt, bool]:
    now = now or _utcnow()
    if sitting.owner_public_id != owner_public_id:
        _fail("sitting_forbidden", "exam sitting belongs to another owner")
    if sitting.status != "in_progress":
        _fail("sitting_not_in_progress", "exam sitting is not accepting answers")
    if sitting.due_at and now > sitting.due_at:
        _fail("sitting_deadline_passed", "exam sitting deadline has passed")
    item = session.query(DBAssessmentExamItem).filter_by(id=payload.exam_item_id, exam_version_id=sitting.exam_version_id).first()
    if item is None:
        _fail("exam_item_forbidden", "question is not part of this frozen exam version")
    existing = session.query(DBAssessmentExamResponse).filter_by(sitting_id=sitting.id, exam_item_id=item.id).first()
    attempt, attempt_created = record_attempt(
        session, owner_public_id=owner_public_id,
        attempt=AttemptInput(
            question_version_id=item.question_version_id,
            idempotency_key=payload.idempotency_key, mode="formal", answer=payload.answer,
            confidence=payload.confidence, duration_seconds=payload.duration_seconds,
        ),
    )
    if existing:
        if existing.attempt_id != attempt.id:
            _fail("exam_response_conflict", "exam item is already bound to another attempt")
        return existing, attempt, False
    response = DBAssessmentExamResponse(sitting_id=sitting.id, exam_item_id=item.id, attempt_id=attempt.id)
    session.add(response)
    session.flush()
    return response, attempt, attempt_created


def submit_sitting(
    session: Any, *, sitting: DBAssessmentExamSitting, owner_public_id: str,
    expected_lock_version: int, now: datetime | None = None,
) -> DBAssessmentExamSitting:
    now = now or _utcnow()
    if sitting.owner_public_id != owner_public_id:
        _fail("sitting_forbidden", "exam sitting belongs to another owner")
    if sitting.lock_version != expected_lock_version:
        _fail("sitting_lock_conflict", "exam sitting changed since it was loaded")
    if sitting.status != "in_progress":
        _fail("sitting_submit_invalid", "only an in-progress sitting can be submitted")
    required_ids = {row.id for row in session.query(DBAssessmentExamItem).filter_by(exam_version_id=sitting.exam_version_id, required=True).all()}
    response_ids = {row.exam_item_id for row in session.query(DBAssessmentExamResponse).filter_by(sitting_id=sitting.id).all()}
    if not required_ids.issubset(response_ids):
        _fail("sitting_incomplete", "all required exam items must be answered")
    sitting.status = "submitted"
    sitting.submitted_at = now
    sitting.lock_version += 1
    session.flush()
    return sitting


def request_review(
    session: Any, *, sitting: DBAssessmentExamSitting, attempt_id: str,
    requested_by_public_id: str, reason: str,
) -> tuple[DBAssessmentReviewCase, bool]:
    response = session.query(DBAssessmentExamResponse).filter_by(sitting_id=sitting.id, attempt_id=attempt_id).first()
    if response is None:
        _fail("review_attempt_forbidden", "attempt is not part of this exam sitting")
    existing = session.query(DBAssessmentReviewCase).filter_by(sitting_id=sitting.id, attempt_id=attempt_id).first()
    if existing:
        return existing, False
    row = DBAssessmentReviewCase(
        sitting_id=sitting.id, attempt_id=attempt_id,
        requested_by_public_id=requested_by_public_id,
        reason=reason[:4000], status="requested",
    )
    session.add(row)
    session.flush()
    return row, True


def complete_human_review(
    session: Any, *, review: DBAssessmentReviewCase, reviewer_public_id: str,
    expected_lock_version: int, payload: HumanReviewInput,
) -> DBAssessmentGradingResult:
    if review.lock_version != expected_lock_version:
        _fail("review_lock_conflict", "review case changed since it was loaded")
    if review.status not in {"requested", "assigned"}:
        _fail("review_already_decided", "review case is no longer open")
    attempt = session.query(DBAssessmentAttempt).filter_by(id=review.attempt_id).one()
    result, _ = create_grading_result(
        session, attempt=attempt, grader_type="human",
        rubric_version=f"human-review-v1:{review.id}",
        rubric_snapshot={"type": "human_review", "review_case_id": review.id},
        status="completed", score=payload.score, correct=payload.score >= 0.6,
        confidence=payload.confidence, criterion_results=list(payload.criterion_results),
        evidence={"review_case_id": review.id, "label": "人工复核（演示角色）", "prior_evidence_preserved": True},
        feedback=payload.note, improvement_advice=[],
        trace_id=f"human-review:{review.id}", created_by_public_id=reviewer_public_id,
    )
    review.status = "completed"
    review.reviewer_public_id = reviewer_public_id
    review.human_grading_result_id = result.id
    review.decision_note = payload.note
    review.decided_at = _utcnow()
    review.lock_version += 1
    session.flush()
    return result


def _selected_grading(session: Any, attempt_id: str) -> tuple[DBAssessmentGradingResult | None, DBAssessmentGradingResult | None]:
    rows = session.query(DBAssessmentGradingResult).filter_by(attempt_id=attempt_id).order_by(DBAssessmentGradingResult.created_at, DBAssessmentGradingResult.id).all()
    machine = next((row for row in reversed(rows) if row.grader_type != "human" and row.status == "completed"), None)
    human = next((row for row in reversed(rows) if row.grader_type == "human" and row.status == "completed"), None)
    return machine, human or machine


def generate_report(
    session: Any, *, sitting: DBAssessmentExamSitting, actor_public_id: str,
) -> tuple[DBAssessmentExamReport, bool]:
    if sitting.status not in {"submitted", "released"}:
        _fail("report_not_ready", "exam sitting must be submitted before reporting")
    exam = session.query(DBAssessmentExam).filter_by(id=sitting.exam_id).one()
    version = session.query(DBAssessmentExamVersion).filter_by(id=sitting.exam_version_id).one()
    if exam.status not in {"closed", "archived"} and version.feedback_policy != "after_submission":
        _fail("exam_not_closed", "exam must be closed before this report can be released")
    items = session.query(DBAssessmentExamItem).filter_by(exam_version_id=version.id).order_by(DBAssessmentExamItem.position).all()
    responses = {row.exam_item_id: row for row in session.query(DBAssessmentExamResponse).filter_by(sitting_id=sitting.id).all()}
    report_items, selected_ids, earned, pending = [], [], 0.0, 0
    coverage: dict[str, dict[str, Any]] = {}
    for item in items:
        question_version = session.query(DBAssessmentQuestionVersion).filter_by(id=item.question_version_id).one()
        question = session.query(DBAssessmentQuestion).filter_by(id=question_version.question_id).one()
        point = session.query(DBKnowledgePoint).filter_by(id=question_version.primary_knowledge_point_id).first()
        response = responses.get(item.id)
        attempt = session.query(DBAssessmentAttempt).filter_by(id=response.attempt_id).first() if response else None
        initial, selected = _selected_grading(session, attempt.id) if attempt else (None, None)
        if selected and selected.score is not None:
            earned += item.points * selected.score
            selected_ids.append(selected.id)
        else:
            pending += 1
        point_id = question_version.primary_knowledge_point_id or "unbound"
        point_coverage = coverage.setdefault(point_id, {
            "id": point_id,
            "title": learner_topic_title(question_version.prompt, point.title if point else "未绑定知识点"),
            "question_count": 0,
            "earned_points": 0.0,
            "total_points": 0.0,
        })
        point_coverage["question_count"] += 1
        point_coverage["total_points"] += item.points
        if selected and selected.score is not None:
            point_coverage["earned_points"] += item.points * selected.score
        score = selected.score if selected else None
        correct_answer = learner_correct_answer(question.question_type, question_version.answer_key or {})
        grading = grading_result_payload(selected) if selected else None
        report_items.append({
            "position": item.position, "points": item.points,
            "question_version_id": item.question_version_id,
            "question_type": question.question_type,
            "prompt": learner_safe_prompt(question_version.prompt, knowledge_point=point.title if point else ""),
            "options": learner_option_texts(question_version, question),
            "knowledge_point": {
                "id": point_id,
                "title": learner_topic_title(question_version.prompt, point.title if point else "未绑定知识点"),
            },
            "source_refs": _question_sources(session, question_version),
            "attempt_id": attempt.id if attempt else None,
            "learner_answer": attempt.answer if attempt else None,
            "correct_answer": correct_answer,
            "explanation": learner_safe_explanation(
                question_version.explanation or (grading or {}).get("feedback", ""),
                prompt=question_version.prompt,
                options=question_version.options,
                answer_key=question_version.answer_key,
                question_type=question.question_type,
                knowledge_point=point.title if point else "",
            ),
            "error_reason": (
                "未作答" if attempt is None else
                "待评分" if score is None else
                "" if score >= 0.6 else
                _learner_error_reason(question_version.misconception_tags, point.title if point else "")
            ),
            "initial_grading_result_id": initial.id if initial else None,
            "selected_grading_result_id": selected.id if selected else None,
            "selected_label": (
                "人工复核（演示角色）" if selected and selected.grader_type == "human" else
                "AI 智能初评" if selected and selected.grader_type == "ai" else
                "代码隐藏测试" if selected and selected.grader_type == "code" else
                "服务端客观评分" if selected else "待评分"
            ),
            "score": score,
            "correct": selected.correct if selected else None,
            "status": selected.status if selected else "pending",
            "grading": grading,
            "retest_action": {
                "label": "针对该知识点重新组卷",
                "route": "/workspace/assessment/exams",
                "query": {
                    "course_id": exam.course_id,
                    "knowledge_point_id": point_id,
                    "source_exam_id": exam.id,
                },
            } if score is not None and score < 0.6 else None,
        })
    inputs = {"exam_version_id": version.id, "manifest_hash": version.manifest_hash, "selected_grading_result_ids": selected_ids, "submitted_at": sitting.submitted_at}
    input_hash = _hash(inputs)
    existing = session.query(DBAssessmentExamReport).filter_by(sitting_id=sitting.id, input_hash=input_hash).first()
    if existing:
        return existing, False
    coverage_items = []
    for item in coverage.values():
        ratio = item["earned_points"] / item["total_points"] if item["total_points"] else 0.0
        coverage_items.append({
            **item,
            "earned_points": round(item["earned_points"], 4),
            "total_points": round(item["total_points"], 4),
            "ratio": round(ratio, 6),
            "status": "strong" if ratio >= 0.8 else "developing" if ratio >= 0.6 else "needs_review",
        })
    coverage_items.sort(key=lambda item: (item["ratio"], item["title"], item["id"]))
    model_generated = bool((version.generation_context or {}).get("external_model_used"))
    report_data = {
        "schema_version": "next.formal-exam-report.v1", "exam_id": exam.id,
        "exam_title": exam.title, "exam_version_id": version.id,
        "manifest_hash": version.manifest_hash, "sitting_id": sitting.id,
        "learner_public_id": sitting.owner_public_id,
        "submitted_at": sitting.submitted_at.isoformat() if sitting.submitted_at else None,
        "total_points": version.total_points, "earned_points": round(earned, 4),
        "final_ratio": None if pending else round(earned / version.total_points, 6),
        "pending_item_count": pending, "items": report_items,
        "coverage": coverage_items,
        "wrong_question_count": sum(
            item.get("score") is not None and item["score"] < 0.6 for item in report_items
        ),
        "retest": {
            "available": pending == 0,
            "route": "/workspace/assessment/exams",
            "knowledge_point_ids": [
                item["id"] for item in coverage_items if item["ratio"] < 0.6 and item["id"] != "unbound"
            ],
        },
        "labels": {"ai": "智能点评", "human": "教师复核"},
        "grading_mode": "mixed_ai_subjective" if model_generated else "local_deterministic",
        "external_model_used": model_generated,
        "limitations": (
            ["主观题会从内容完整性、推理过程和表达清晰度三个方面给出反馈。"]
            if model_generated else
            ["主观题会从内容完整性、推理过程和表达清晰度三个方面给出反馈。"]
        ),
    }
    latest = session.query(DBAssessmentExamReport).filter_by(sitting_id=sitting.id).order_by(DBAssessmentExamReport.report_version.desc()).first()
    row = DBAssessmentExamReport(
        sitting_id=sitting.id, report_version=(latest.report_version + 1 if latest else 1),
        report_data=report_data, input_hash=input_hash, content_hash=_hash(report_data),
        created_by_public_id=actor_public_id,
    )
    session.add(row)
    session.flush()
    return row, True


def report_csv(report: DBAssessmentExamReport) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["position", "question_version_id", "points", "score", "status", "grading_label"])
    for item in report.report_data.get("items", []):
        values = [item.get("position"), item.get("question_version_id"), item.get("points"), item.get("score"), item.get("status"), item.get("selected_label")]
        writer.writerow([f"'{value}" if isinstance(value, str) and value[:1] in {"=", "+", "-", "@"} else value for value in values])
    return output.getvalue()


def exam_payload(session: Any, exam: DBAssessmentExam, *, include_answers: bool = False) -> dict[str, Any]:
    version = session.query(DBAssessmentExamVersion).filter_by(id=exam.current_version_id).first()
    items = session.query(DBAssessmentExamItem).filter_by(exam_version_id=version.id).order_by(DBAssessmentExamItem.position).all() if version else []
    result_items = []
    for item in items:
        question_version = session.query(DBAssessmentQuestionVersion).filter_by(id=item.question_version_id).one()
        question = session.query(DBAssessmentQuestion).filter_by(id=question_version.question_id).one()
        point = session.query(DBKnowledgePoint).filter_by(id=question_version.primary_knowledge_point_id).first()
        payload = {"id": item.id, "position": item.position, "points": item.points, "required": item.required,
                   "question_version_id": item.question_version_id, "question_type": question.question_type,
                   "prompt": learner_safe_prompt(question_version.prompt, knowledge_point=point.title if point else ""),
                   "options": learner_option_texts(question_version, question),
                   "difficulty": (
                       question_version.measured_difficulty
                       if question_version.measured_difficulty is not None
                       else question_version.expert_difficulty
                   ),
                   "knowledge_point": {
                       "id": question_version.primary_knowledge_point_id,
                       "title": learner_topic_title(question_version.prompt, point.title if point else "未绑定知识点"),
                   },
                   "source_refs": _question_sources(session, question_version)}
        if include_answers:
            payload["answer_key"] = question_version.answer_key
            payload["correct_answer"] = learner_correct_answer(question.question_type, question_version.answer_key or {})
            payload["explanation"] = learner_safe_explanation(
                question_version.explanation,
                prompt=question_version.prompt,
                options=question_version.options,
                answer_key=question_version.answer_key,
                question_type=question.question_type,
                knowledge_point=point.title if point else "",
            )
        result_items.append(payload)
    return {"id": exam.id, "course_id": exam.course_id, "title": exam.title, "status": exam.status,
            "scheduled_open_at": exam.scheduled_open_at.isoformat() if exam.scheduled_open_at else None,
            "scheduled_close_at": exam.scheduled_close_at.isoformat() if exam.scheduled_close_at else None,
            "duration_minutes": exam.duration_minutes, "lock_version": exam.lock_version,
            "version": {"id": version.id, "version_number": version.version_number,
                        "instructions": version.instructions, "feedback_policy": version.feedback_policy,
                        "total_points": version.total_points, "manifest_hash": version.manifest_hash,
                        "configuration": version.configuration or {},
                        "generation_context": version.generation_context or {},
                        "coverage": version.coverage or {}} if version else None,
            "items": result_items}


def sitting_payload(session: Any, sitting: DBAssessmentExamSitting) -> dict[str, Any]:
    final_count = session.query(DBAssessmentExamResponse).filter_by(sitting_id=sitting.id).count()
    draft_count = len(latest_formal_response_drafts(session, sitting_id=sitting.id))
    answered = max(final_count, draft_count)
    return {"id": sitting.id, "exam_id": sitting.exam_id, "exam_version_id": sitting.exam_version_id,
            "owner_public_id": sitting.owner_public_id, "status": sitting.status,
            "started_at": sitting.started_at.isoformat() if sitting.started_at else None,
            "due_at": sitting.due_at.isoformat() if sitting.due_at else None,
            "submitted_at": sitting.submitted_at.isoformat() if sitting.submitted_at else None,
            "released_at": sitting.released_at.isoformat() if sitting.released_at else None,
            "lock_version": sitting.lock_version, "answered_count": answered}
