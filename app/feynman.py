"""Versioned five-stage Feynman retelling sessions."""

from __future__ import annotations

import hashlib
import json
import asyncio
import re
from typing import Any, Literal

from pydantic import Field

from app.database import (
    DBArtifact,
    DBArtifactVersion,
    DBCourse,
    DBKnowledgePoint,
    DBLearningEvent,
    DBProfileSnapshot,
    DBUser,
)
from app.m1_repository import add_artifact_version
from app.m2_contracts import StrictModel
from app.learner_output import teacher_text
from app.m5_learning import LearningEventInput, process_path_event, record_learning_event
from app.m5_resources import canonical_resource_type
from app.schemas import ContextRef
from config import CONFIG
from llm_client import (
    StructuredModelContentError,
    build_async_llm,
    parse_json_object,
)


SESSION_TYPE = "feynman_session"
SESSION_SCHEMA_VERSION = "f6.feynman-session.v1"
RUBRIC_VERSION = "f6.feynman-rubric.v1"
EVENT_PAYLOAD_VERSION = "f6.feynman-evidence.v1"

SessionStatus = Literal[
    "draft",
    "round1_submitted",
    "review1_ready",
    "question_pending",
    "question_answered",
    "round2_submitted",
    "comparison_ready",
    "applied",
]
ActionName = Literal[
    "submit_round1",
    "evaluate_round1",
    "begin_question",
    "answer_question",
    "submit_round2",
    "evaluate_round2",
    "apply",
]


class FeynmanError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise FeynmanError(code, message)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = chr(31).join(parts)
    return f"{prefix}-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]}"


class SourceSnapshot(StrictModel):
    source_ref_id: str
    source_document_id: str | None = None
    title: str
    location_label: str = ""
    quote: str = ""
    available: bool = True


class FeynmanContextSnapshot(StrictModel):
    """The frozen learning context used by every stage of one session."""

    schema_version: Literal["f6.feynman-context.v1"] = "f6.feynman-context.v1"
    course_id: str | None = None
    course_title: str
    knowledge_point_id: str | None = None
    knowledge_point_title: str
    profile_snapshot_id: str | None = None
    profile_content_hash: str | None = None
    profile_focus: tuple[str, ...] = ()
    recent_evidence_ids: tuple[str, ...] = ()
    recent_event_focus: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    context_fingerprint: str
    generation_mode: Literal["deterministic_local", "llm"] = "llm"


class RubricDimension(StrictModel):
    key: str
    label: str
    score: int = Field(ge=0)
    maximum: int = Field(ge=1)
    evidence: str


class RoundEvaluation(StrictModel):
    evaluation_id: str
    rubric_version: Literal["f6.feynman-rubric.v1"] = RUBRIC_VERSION
    round_number: Literal[1, 2]
    text_sha256: str
    score: int = Field(ge=0, le=100)
    normalized_score: float = Field(ge=0, le=1)
    dimensions: tuple[RubricDimension, ...]
    strengths: tuple[str, ...]
    gaps: tuple[str, ...]
    omissions: tuple[str, ...]
    evaluation_mode: Literal["deterministic_local", "llm"] = "llm"
    context_fingerprint: str | None = None
    context_focus: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()


class QuestionAnswer(StrictModel):
    question: str
    answer: str
    source_ref_ids: tuple[str, ...]
    answer_mode: Literal["deterministic_local_grounded", "llm_grounded"] = "llm_grounded"
    context_fingerprint: str | None = None
    context_focus: tuple[str, ...] = ()


class Comparison(StrictModel):
    first_score: int
    second_score: int
    score_delta: int
    conclusion: Literal["improved", "unchanged", "lower"]
    improved_dimensions: tuple[str, ...]
    lower_dimensions: tuple[str, ...]
    remaining_gaps: tuple[str, ...]
    next_actions: tuple[str, ...]
    first_evaluation_id: str
    second_evaluation_id: str
    rubric_version: Literal["f6.feynman-rubric.v1"] = RUBRIC_VERSION
    context_fingerprint: str | None = None
    context_focus: tuple[str, ...] = ()


class FeynmanState(StrictModel):
    schema_version: Literal["f6.feynman-session.v1"] = SESSION_SCHEMA_VERSION
    session_id: str
    owner_public_id: str
    source_resource_id: str
    source_resource_version_id: str
    source_resource_content_sha256: str
    title: str
    course_id: str | None = None
    course_title: str
    knowledge_point_id: str | None = None
    knowledge_point_title: str
    profile_snapshot_id: str | None = None
    recent_evidence_ids: tuple[str, ...] = ()
    source_refs: tuple[SourceSnapshot, ...] = ()
    task_prompt: str
    adaptation_note: str
    context_snapshot: FeynmanContextSnapshot | None = None
    rubric_version: Literal["f6.feynman-rubric.v1"] = RUBRIC_VERSION
    status: SessionStatus = "draft"
    round1_text: str | None = None
    round1_text_sha256: str | None = None
    round1_evaluation: RoundEvaluation | None = None
    question_answer: QuestionAnswer | None = None
    round2_text: str | None = None
    round2_text_sha256: str | None = None
    round2_evaluation: RoundEvaluation | None = None
    comparison: Comparison | None = None
    applied_event_id: str | None = None
    last_action: str = "created"


def _source_resource(
    db: Any, resource_id: str, owner: str,
) -> tuple[DBArtifact, DBArtifactVersion, dict[str, Any]]:
    artifact = db.get(DBArtifact, resource_id)
    if artifact is None:
        _fail("feynman_source_unknown", "费曼复述资源不存在")
    if artifact.owner_public_id != owner:
        _fail("feynman_source_forbidden", "费曼复述资源属于其他用户")
    version = db.get(DBArtifactVersion, artifact.current_version_id)
    metadata = dict(version.metadata_json or {}) if version else {}
    if version is None or canonical_resource_type(artifact.artifact_type, metadata) != "feynman":
        _fail("feynman_source_type_invalid", "目标资源不是费曼复述资源")
    return artifact, version, metadata


def _profile_text(value: Any, fragments: tuple[str, ...]) -> str:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower()
            if any(fragment in normalized for fragment in fragments):
                if isinstance(item, str) and item.strip():
                    text = " ".join(item.split())[:100]
                    if _public_focus_term(text):
                        return text
                if isinstance(item, list):
                    text = "、".join(
                        str(entry).strip()
                        for entry in item
                        if str(entry).strip() and _public_focus_term(str(entry))
                    )
                    if text:
                        return text[:100]
        for item in value.values():
            found = _profile_text(item, fragments)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _profile_text(item, fragments)
            if found:
                return found
    return ""


def _public_focus_term(value: Any) -> bool:
    text = " ".join(str(value or "").split())
    lowered = text.lower()
    if not text or any(marker in lowered for marker in (
        "kp-", "event_", "event-", "trace-", "run-", "sha256", ".md", ".json", "\\",
    )):
        return False
    return not re.search(r"\b(?:f\d+-)?(?:kp|event|trace|run)-[a-z0-9-]{6,}\b|\b[a-f0-9]{24,}\b", lowered)


def _focus_relevant_to_knowledge(value: str, knowledge_point: str) -> bool:
    focus = value.lower()
    title = knowledge_point.lower()
    topic_groups = (
        ("优化", "正则", "训练", "损失", "学习率", "过拟合", "梯度", "早停"),
        ("rag", "检索", "召回", "向量", "关键词", "重排", "切分", "来源", "版本", "证据", "失败"),
        ("agent", "智能体", "mcp", "skill", "工具调用"),
        ("transformer", "注意力", "qkv", "位置编码"),
        ("卷积", "cnn", "图像", "池化"),
        ("循环", "rnn", "序列", "lstm", "gru"),
    )
    for group in topic_groups:
        if any(marker in title for marker in group):
            return any(marker in focus for marker in group)
    title_terms = [term for term in re.split(r"[^a-z0-9\u4e00-\u9fff]+", title) if len(term) >= 2]
    return any(term in focus for term in title_terms)


def _focus_terms(profile: DBProfileSnapshot | None, recent: list[DBLearningEvent]) -> tuple[str, ...]:
    values: list[str] = []
    if profile is not None:
        snapshot = profile.snapshot or {}
        for fragments in (("weak", "gap", "difficulty", "薄弱", "困难", "误区"), ("goal", "target", "focus", "目标", "重点")):
            value = _profile_text(snapshot, fragments)
            if value:
                values.append(value)
    for event in recent:
        payload = event.payload or {}
        for key in ("focus", "focus_area", "summary", "knowledge_point_title"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                public_value = " ".join(value.split())[:120]
                if _public_focus_term(public_value):
                    values.append(public_value)
    unique: list[str] = []
    for value in values:
        if value and value not in unique:
            unique.append(value)
    return tuple(unique[:6])


def _adaptation_note(
    profile: DBProfileSnapshot | None,
    evidence_count: int,
    focus_terms: tuple[str, ...] = (),
    knowledge_point: str = "",
) -> str:
    if profile is None:
        base = "先把核心含义讲清楚，再说明它怎样工作、何时适用。"
    else:
        snapshot = profile.snapshot or {}
        difficulty = _profile_text(snapshot, ("weak", "gap", "difficulty", "薄弱", "困难", "误区"))
        goal = _profile_text(snapshot, ("goal", "target", "目标"))
        if difficulty and _focus_relevant_to_knowledge(difficulty, knowledge_point):
            base = f"你可以特别留意“{difficulty}”，把容易混淆的地方讲得更具体。"
        elif goal and _focus_relevant_to_knowledge(goal, knowledge_point):
            base = f"可以联系你的学习目标“{goal}”，试着把概念用到一个实际场景中。"
        else:
            base = "先用直白的话解释，再用例子检验自己是否真正理解。"
    focus_note = f"讲解时可以重点处理：{'；'.join(focus_terms[:3])}。" if focus_terms else "别忘了说明成立条件和容易误用的情形。"
    return f"{base} {focus_note}"


def _recent_evidence(db: Any, owner: str, course_id: str | None, knowledge_point_id: str | None) -> list[DBLearningEvent]:
    query = db.query(DBLearningEvent).filter(
        DBLearningEvent.owner_public_id == owner,
        DBLearningEvent.evidence_status == "accepted",
        DBLearningEvent.mastery_eligible.is_(True),
    )
    if course_id is None:
        query = query.filter(DBLearningEvent.course_id.is_(None))
    else:
        query = query.filter(DBLearningEvent.course_id == course_id)
    rows = query.order_by(DBLearningEvent.occurred_at.desc(), DBLearningEvent.id.desc()).limit(30).all()
    if not knowledge_point_id:
        return rows[:5]
    matched = []
    for row in rows:
        context = row.context_ref or {}
        payload = row.payload or {}
        if context.get("knowledgePointId") == knowledge_point_id or payload.get("knowledge_point_id") == knowledge_point_id:
            matched.append(row)
    return (matched or rows)[:5]


def _source_snapshots(metadata: dict[str, Any]) -> tuple[SourceSnapshot, ...]:
    values = []
    for item in metadata.get("source_snapshot") or []:
        if not isinstance(item, dict) or not item.get("source_ref_id"):
            continue
        values.append(SourceSnapshot(
            source_ref_id=str(item["source_ref_id"]),
            source_document_id=str(item.get("source_document_id") or "") or None,
            title=str(item.get("title") or "课程来源"),
            location_label=str(item.get("location_label") or ""),
            quote=" ".join(str(item.get("quote") or "").split())[:600],
            available=item.get("available") is not False,
        ))
    return tuple(values)


def _task_prompt(knowledge_point: str, adaptation: str) -> str:
    return teacher_text(
        f"请把“{knowledge_point}”讲给一位刚接触这个主题的同学听。用自己的话说明："
        "它要解决的问题和核心含义；关键机制或步骤以及成立条件；一个适用例子；"
        f"一个边界、反例或常见误区。尽量使用你自己的表达。{adaptation}"
    )


def _owned_session(
    db: Any, session_id: str, owner: str,
) -> tuple[DBArtifact, DBArtifactVersion, FeynmanState]:
    artifact = db.get(DBArtifact, session_id)
    if artifact is None or artifact.artifact_type != SESSION_TYPE:
        _fail("feynman_session_unknown", "费曼复述会话不存在")
    if artifact.owner_public_id != owner:
        _fail("feynman_session_forbidden", "费曼复述会话属于其他用户")
    version = db.get(DBArtifactVersion, artifact.current_version_id)
    if version is None:
        _fail("feynman_session_invalid", "费曼复述会话缺少当前版本")
    return artifact, version, FeynmanState.model_validate_json(version.content)


def create_session(
    db: Any, *, owner: str, source_resource_id: str, idempotency_key: str,
) -> tuple[DBArtifact, DBArtifactVersion, FeynmanState, bool]:
    source, source_version, metadata = _source_resource(db, source_resource_id, owner)
    session_id = _stable_id("feynman", owner, idempotency_key)
    request_hash = _digest({
        "source_resource_id": source.id,
        "source_resource_version_id": source_version.id,
    })
    existing = db.get(DBArtifact, session_id)
    if existing is not None:
        first = db.query(DBArtifactVersion).filter_by(
            artifact_id=existing.id, version_number=1,
        ).one()
        if (first.metadata_json or {}).get("create_request_sha256") != request_hash:
            _fail("feynman_idempotency_conflict", "幂等键已绑定到其他费曼资源")
        artifact, version, state = _owned_session(db, session_id, owner)
        return artifact, version, state, False

    course = db.get(DBCourse, source.course_id) if source.course_id else None
    knowledge_point_id = str(metadata.get("knowledge_point_id") or "") or None
    point = db.get(DBKnowledgePoint, knowledge_point_id) if knowledge_point_id else None
    profile_snapshot_id = str(metadata.get("profile_snapshot_id") or "") or None
    profile = db.get(DBProfileSnapshot, profile_snapshot_id) if profile_snapshot_id else None
    if profile is not None and profile.owner_public_id != owner:
        profile = None
        profile_snapshot_id = None
    recent = _recent_evidence(db, owner, source.course_id, knowledge_point_id)
    knowledge_title = point.title if point else source.title.replace("费曼复述", "").strip(" -·") or "当前知识点"
    focus_terms = tuple(
        item for item in _focus_terms(profile, recent)
        if _focus_relevant_to_knowledge(item, knowledge_title)
    )
    refs = _source_snapshots(metadata)
    source_generation_mode = str(metadata.get("generation_mode") or "llm").strip().lower()
    evaluation_mode = (
        "deterministic_local"
        if source_generation_mode in {"deterministic_fallback", "deterministic_local", "deterministic_demo"}
        else "llm"
    )
    context_snapshot = FeynmanContextSnapshot(
        course_id=source.course_id,
        course_title=course.title if course else "当前课程",
        knowledge_point_id=knowledge_point_id,
        knowledge_point_title=knowledge_title,
        profile_snapshot_id=profile_snapshot_id,
        profile_content_hash=profile.content_hash if profile is not None else None,
        profile_focus=tuple(focus_terms[:2]),
        recent_evidence_ids=tuple(row.id for row in recent),
        recent_event_focus=tuple(focus_terms[2:]),
        source_ref_ids=tuple(item.source_ref_id for item in refs),
        generation_mode=evaluation_mode,
        context_fingerprint=_digest({
            "course_id": source.course_id,
            "course_version": course.version if course else None,
            "knowledge_point_id": knowledge_point_id,
            "knowledge_point_title": knowledge_title,
            "profile_snapshot_id": profile_snapshot_id,
            "profile_content_hash": profile.content_hash if profile is not None else None,
            "recent_evidence_ids": [row.id for row in recent],
            "source_resource_version_id": source_version.id,
            "source_content_hash": source_version.content_hash,
        }),
    )
    adaptation = _adaptation_note(profile, len(recent), focus_terms, knowledge_title)
    state = FeynmanState(
        session_id=session_id,
        owner_public_id=owner,
        source_resource_id=source.id,
        source_resource_version_id=source_version.id,
        source_resource_content_sha256=source_version.content_hash,
        title=f"{knowledge_title} · 费曼复述",
        course_id=source.course_id,
        course_title=course.title if course else "当前课程",
        knowledge_point_id=knowledge_point_id,
        knowledge_point_title=knowledge_title,
        profile_snapshot_id=profile_snapshot_id,
        recent_evidence_ids=tuple(row.id for row in recent),
        source_refs=refs,
        task_prompt=_task_prompt(knowledge_title, adaptation),
        adaptation_note=adaptation,
        context_snapshot=context_snapshot,
    )
    artifact = DBArtifact(
        id=session_id,
        owner_public_id=owner,
        course_id=source.course_id,
        artifact_type=SESSION_TYPE,
        title=state.title,
    )
    db.add(artifact)
    db.flush()
    version = add_artifact_version(
        db,
        artifact=artifact,
        content=_canonical(state.model_dump(mode="json")),
        content_format="json",
        created_by_public_id=owner,
        metadata={
            "schema_version": SESSION_SCHEMA_VERSION,
            "status": state.status,
            "create_request_sha256": request_hash,
            "source_resource_id": source.id,
            "source_resource_version_id": source_version.id,
        },
    )
    return artifact, version, state, True


def _submitted_text(value: str | None, *, minimum: int, maximum: int, field: str) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) < minimum:
        _fail(f"feynman_{field}_too_short", f"{field} 至少需要 {minimum} 个字符")
    if len(text) > maximum:
        _fail(f"feynman_{field}_too_long", f"{field} 不能超过 {maximum} 个字符")
    return text


def _cue_score(text: str, cues: tuple[str, ...], maximum: int, unit: int) -> tuple[int, list[str]]:
    found = [cue for cue in cues if cue.lower() in text.lower()]
    return min(maximum, len(found) * unit), found


def _live_model_backend() -> Any:
    """Build the only production Feynman evaluator: DeepSeek with max reasoning."""
    provider = CONFIG.llm_provider.lower().strip()
    if provider not in {"openai", "vllm"}:
        _fail("feynman_model_required", "费曼评价需要配置真实 DeepSeek 模型。")
    if not CONFIG.llm_endpoint or not CONFIG.llm_api_key:
        _fail("feynman_model_unavailable", "费曼评价需要配置模型 endpoint 和 API key。")
    return build_async_llm(
        provider=provider,
        endpoint=CONFIG.llm_endpoint,
        api_key=CONFIG.llm_api_key,
        model="deepseek-v4-flash",
        allow_fallback=False,
        thinking_mode="max",
        reasoning_effort="max",
    )


def _model_json(*, system: str, user: dict[str, Any], role: str) -> dict[str, Any]:
    backend = _live_model_backend()

    async def call() -> dict[str, Any]:
        raw = await backend.generate(
            system,
            json.dumps(user, ensure_ascii=False, sort_keys=True),
            role=role,
        )
        return parse_json_object(raw)

    try:
        return asyncio.run(call())
    except FeynmanError:
        raise
    except Exception as exc:
        cause = exc
        empty_content = False
        while cause is not None:
            if isinstance(cause, StructuredModelContentError):
                empty_content = True
                break
            cause = cause.__cause__ or cause.__context__
        action_label = "评价" if role == "feynman_evaluator" else "答疑"
        detail = (
            "模型未返回可用的结构化内容"
            if empty_content
            else "模型返回内容暂时不可用或无法解析"
        )
        _fail("feynman_model_call_failed", f"真实模型{action_label}失败，请重试：{detail}。")


def _model_context(state: FeynmanState) -> dict[str, Any]:
    context = state.context_snapshot
    return {
        "course_id": state.course_id,
        "course_title": state.course_title,
        "knowledge_point_id": state.knowledge_point_id,
        "knowledge_point_title": state.knowledge_point_title,
        "profile_focus": list(context.profile_focus) if context else [],
        "recent_event_focus": list(context.recent_event_focus) if context else [],
        "sources": [
            {
                "source_ref_id": source.source_ref_id,
                "title": source.title,
                "location": source.location_label,
                "quote": source.quote[:1_200],
            }
            for source in state.source_refs
            if source.available
        ],
    }


def _live_evaluate(
    text: str,
    state: FeynmanState,
    *,
    round_number: Literal[1, 2],
) -> RoundEvaluation:
    system = (
        "你是一位耐心、严格的课程老师。根据提供的学习内容评价学生复述，"
        "不得编造教材事实。推理完成后必须把最终 JSON 放在公开 content 字段返回，"
        "不能只返回 reasoning_content。只输出 JSON 对象，不要 Markdown、思维链或 reasoning_content。"
        "dimensions 必须是包含五项 key 的 JSON 对象：core_meaning、mechanism、conditions、example、boundary，"
        "每项有 label、score、maximum、evidence；maximum 分别为 25、25、20、15、15，"
        "并输出 score（五项之和）、strengths、gaps、omissions 数组。"
        "这些公开文字要直接告诉学生哪里讲清了、哪里需要补充以及如何改进；"
        "不要提检索、上下文、来源、证据链、评分规则、运行方式、模型或任何内部编号。"
    )
    payload = _model_json(
        system=system,
        user={
            "round_number": round_number,
            "knowledge_point": state.knowledge_point_title,
            "task_prompt": state.task_prompt,
            "adaptation_note": state.adaptation_note,
            "context": _model_context(state),
            "student_retelling": text,
        },
        role="feynman_evaluator",
    )
    expected = {
        "core_meaning": ("核心含义", 25),
        "mechanism": ("机制与步骤", 25),
        "conditions": ("成立条件", 20),
        "example": ("适用例子", 15),
        "boundary": ("边界与反例", 15),
    }
    raw_dimensions = payload.get("dimensions")
    if isinstance(raw_dimensions, dict):
        raw_dimensions = [
            {**value, "key": key}
            for key, value in raw_dimensions.items()
            if isinstance(value, dict)
        ]
    if not isinstance(raw_dimensions, list):
        _fail("feynman_model_output_invalid", "真实模型评价缺少五维评分。")

    # Providers vary between canonical keys, camelCase keys, and translated
    # labels. Normalize those equivalent names while retaining the strict
    # requirement that all five rubric dimensions are present.
    dimension_aliases = {
        "coremeaning": "core_meaning",
        "核心含义": "core_meaning",
        "mechanism": "mechanism",
        "mechanismandsteps": "mechanism",
        "机制": "mechanism",
        "机制与步骤": "mechanism",
        "conditions": "conditions",
        "成立条件": "conditions",
        "条件": "conditions",
        "example": "example",
        "适用例子": "example",
        "例子": "example",
        "boundary": "boundary",
        "边界与反例": "boundary",
        "边界": "boundary",
    }

    def canonical_dimension_key(value: Any) -> str:
        normalized = "".join(char.lower() for char in str(value or "") if char.isalnum() or "\u4e00" <= char <= "\u9fff")
        if normalized in dimension_aliases:
            return dimension_aliases[normalized]
        return str(value or "")

    by_key = {}
    for item in raw_dimensions:
        if not isinstance(item, dict):
            continue
        key = canonical_dimension_key(item.get("key"))
        if key not in expected:
            key = canonical_dimension_key(item.get("label"))
        if key in expected:
            by_key[key] = {**item, "key": key}
    if set(by_key) != set(expected):
        _fail("feynman_model_output_invalid", "真实模型评价的五维评分不完整。")
    dimensions: list[RubricDimension] = []
    for key, (label, maximum) in expected.items():
        item = by_key[key]
        try:
            score = int(item.get("score"))
            dimension = RubricDimension(
                key=key,
                label=str(item.get("label") or label),
                score=score,
                maximum=maximum,
                evidence=teacher_text(item.get("evidence")),
            )
        except (TypeError, ValueError) as exc:
            _fail("feynman_model_output_invalid", f"真实模型评价的 {label} 评分无效：{exc}")
        if not dimension.evidence:
            _fail("feynman_model_output_invalid", f"真实模型评价缺少 {label} 的依据。")
        dimensions.append(dimension)
    score = sum(item.score for item in dimensions)
    if payload.get("score") is not None:
        try:
            if int(payload["score"]) != score:
                _fail("feynman_model_output_invalid", "真实模型总分与五维评分不一致。")
        except (TypeError, ValueError):
            _fail("feynman_model_output_invalid", "真实模型总分无效。")
    def text_items(key: str) -> tuple[str, ...]:
        value = payload.get(key)
        if not isinstance(value, list):
            _fail("feynman_model_output_invalid", f"真实模型评价缺少 {key} 列表。")
        return tuple(teacher_text(" ".join(str(item).split())[:500]) for item in value if str(item).strip())

    context = state.context_snapshot
    focus = tuple(
        (context.profile_focus if context else ()) + (context.recent_event_focus if context else ())
    )
    return RoundEvaluation(
        evaluation_id=_stable_id("feval", state.session_id, str(round_number), _text_digest(text), RUBRIC_VERSION, context.context_fingerprint if context else "live"),
        round_number=round_number,
        text_sha256=_text_digest(text),
        score=score,
        normalized_score=round(score / 100, 4),
        dimensions=tuple(dimensions),
        strengths=text_items("strengths"),
        gaps=text_items("gaps"),
        omissions=text_items("omissions"),
        evaluation_mode="llm",
        context_fingerprint=context.context_fingerprint if context else None,
        context_focus=focus,
        source_ref_ids=context.source_ref_ids if context else (),
    )


def _live_answer_question(state: FeynmanState, question: str) -> QuestionAnswer:
    system = (
        "你是一位熟悉本课程的老师。先直接回答学生疑问，再解释原理、举例并说明容易误解的地方。"
        "材料不足以确认某个细节时，用普通教学语言说明还需要哪些信息，不得编造教材内容。"
        "只输出 JSON 对象，包含 answer 字符串；"
        "推理完成后必须把最终 JSON 放在公开 content 字段返回，不能只返回 reasoning_content；"
        "answer 可以使用简洁 Markdown，但不要复述问题凑篇幅。"
        "不要在 answer 中提检索、上下文、来源、课文、依据、约束、确定性、评分规则、运行方式、"
        "prompt、API key、reasoning_content 或任何内部编号。"
    )
    payload = _model_json(
        system=system,
        user={
            "question": question,
            "knowledge_point": state.knowledge_point_title,
            "round1_gaps": list(state.round1_evaluation.gaps) if state.round1_evaluation else [],
            "context": _model_context(state),
        },
        role="feynman_tutor",
    )
    answer = teacher_text("\n".join(str(payload.get("answer") or "").splitlines()))
    if not answer:
        _fail("feynman_model_output_invalid", "真实模型没有返回有效的疑问回答。")
    context = state.context_snapshot
    source_ids = tuple(source.source_ref_id for source in state.source_refs if source.available)
    focus = tuple(
        (context.profile_focus if context else ()) + (context.recent_event_focus if context else ())
    )
    return QuestionAnswer(
        question=question,
        answer=answer[:8_000],
        source_ref_ids=source_ids,
        answer_mode="llm_grounded",
        context_fingerprint=context.context_fingerprint if context else None,
        context_focus=focus,
    )


def _evaluate(
    text: str,
    knowledge_point: str,
    *,
    round_number: Literal[1, 2],
    session_id: str,
    context: FeynmanContextSnapshot | None = None,
) -> RoundEvaluation:
    length = len(text)
    core = 8 if length >= 60 else 4
    if knowledge_point and knowledge_point.lower() in text.lower():
        core += 12
    focus_terms = tuple(
        item for item in ((context.profile_focus if context else ()) + (context.recent_event_focus if context else ()))
        if item and len(item) >= 2
    )
    focus_cues = [item for item in focus_terms if item.lower() in text.lower()]
    context_bonus = min(8, len(focus_cues) * 4)
    core = min(25, core + context_bonus)
    definition_points, definition_cues = _cue_score(text, ("是", "指", "意味着", "用于", "解决"), 5, 2)
    core = min(25, core + definition_points)

    mechanism, mechanism_cues = _cue_score(
        text, ("因为", "因此", "机制", "步骤", "先", "然后", "输入", "输出", "导致"), 25, 5,
    )
    conditions, condition_cues = _cue_score(
        text, ("条件", "前提", "当", "只有", "适用", "要求", "假设"), 20, 5,
    )
    example, example_cues = _cue_score(text, ("例如", "比如", "举例", "场景", "案例"), 15, 5)
    boundary, boundary_cues = _cue_score(
        text, ("反例", "边界", "限制", "不适用", "误区", "但是", "否则"), 15, 5,
    )
    dimensions = (
        RubricDimension(
            key="core_meaning", label="核心含义", score=core, maximum=25,
            evidence=("你已经点出这个概念，并用一句话说明了它的含义。" if core >= 18 else "还需要先用一句直白的话说明这个概念究竟是什么。"),
        ),
        RubricDimension(
            key="mechanism", label="机制与步骤", score=mechanism, maximum=25,
            evidence=("你已经说明了部分过程，下一步可把各步骤的先后关系连起来。" if mechanism_cues else "目前还没有讲清它怎样一步步产生结果。"),
        ),
        RubricDimension(
            key="conditions", label="成立条件", score=conditions, maximum=20,
            evidence=("你提到了适用条件，可以再说明缺少这些条件时会怎样。" if condition_cues else "还需要补上结论成立所需的前提。"),
        ),
        RubricDimension(
            key="example", label="适用例子", score=example, maximum=15,
            evidence=("你给出了例子；如果再把输入、过程和结果对应起来，会更有说服力。" if example_cues else "可以补一个带有具体输入和结果的小例子。"),
        ),
        RubricDimension(
            key="boundary", label="边界与反例", score=boundary, maximum=15,
            evidence=("你已经提醒了容易误用的情形，可以再解释为什么会失效。" if boundary_cues else "还需要说明一种不适用的情形或常见误区。"),
        ),
    )
    score = sum(item.score for item in dimensions)
    strengths = tuple(f"{item.label}表达较完整" for item in dimensions if item.score >= item.maximum * 0.65)
    gaps = tuple(f"{item.label}还需要补充" for item in dimensions if item.score < item.maximum * 0.65)
    omissions = tuple(item.label for item in dimensions if item.score == 0)
    context_fingerprint = context.context_fingerprint if context else None
    return RoundEvaluation(
        evaluation_id=_stable_id("feval", session_id, str(round_number), _text_digest(text), RUBRIC_VERSION, context_fingerprint or "legacy"),
        round_number=round_number,
        text_sha256=_text_digest(text),
        score=score,
        normalized_score=round(score / 100, 4),
        dimensions=dimensions,
        strengths=strengths or ("你已经完成了一次独立、连贯的表达",),
        gaps=gaps or ("继续用新的例子检验能否迁移理解",),
        omissions=omissions,
        evaluation_mode="deterministic_local",
        context_fingerprint=context_fingerprint,
        context_focus=focus_terms,
        source_ref_ids=context.source_ref_ids if context else (),
    )


def _answer_question(state: FeynmanState, question: str) -> QuestionAnswer:
    source = next((item for item in state.source_refs if item.available and item.quote), None)
    if source:
        source_ids = (source.source_ref_id,)
    elif state.source_refs:
        source = state.source_refs[0]
        source_ids = (source.source_ref_id,)
    else:
        source_ids = ()
    context = state.context_snapshot
    focus_terms = tuple(
        item for item in ((context.profile_focus if context else ()) + (context.recent_event_focus if context else ()))
        if item
    )
    gaps = "、".join(state.round1_evaluation.gaps[:2]) if state.round1_evaluation else "首轮尚未明确的部分"
    topic = f"{state.knowledge_point_title} {question}".lower()
    if any(marker in topic for marker in ("没有正确解析", "没有标准答案", "没有唯一答案", "为什么还能评价", "评价可靠吗")):
        answer = (
            "可以评价，因为费曼复述考查的不是你是否背出某一句固定表述，而是你有没有建立完整、能自洽的理解。"
            "老师会分别看五件事：你能否说清核心含义，能否解释过程，能否指出成立条件，能否举出合适的例子，"
            "以及能否识别不适用的情形。开放表达可以有很多种，但这五个方面都能从你的文字中具体判断。\n\n"
            "例如解释混合检索时，你可以用图书馆找书、搜索引擎或代码检索来举例，表述不必相同。"
            "只要你能讲清关键词方法擅长精确匹配、向量方法擅长相近含义、两类结果如何合并，"
            "并说明原始内容缺失时后面的排序也无法补回信息，这个解释就是完整而可检查的。\n\n"
            "为了避免评价只看字数或语气，分数会落在具体维度上。"
            "如果某一项被扣分，点评必须指出缺的是哪一部分，并给出可执行的补充方向。"
            "第二次复述也会与第一次逐项比较，所以真正的进步应体现在内容更完整、关系更清楚，而不是换几个词。"
        )
    elif any(marker in topic for marker in ("优化", "正则", "训练稳定", "梯度下降", "验证损失", "早停")):
        answer = (
            "结论：训练损失继续下降而验证损失开始上升，通常说明模型正在更贴合训练样本，"
            "但对未见数据的泛化能力已经变差。此时继续训练只会进一步优化训练目标，不能自动修复泛化问题。\n\n"
            "L2 正则化和早停解决的是两个不同环节。L2 在训练目标中加入 λ‖w‖²，持续抑制过大的权重，"
            "从模型复杂度上降低过拟合倾向；早停则监控验证集指标，在连续若干轮没有改善时停止训练并恢复最佳检查点，"
            "从训练时长上避免模型继续记忆训练噪声。它们可以组合使用，但不能互相替代。\n\n"
            "实际判断时，应固定训练集与验证集划分，同时观察两条损失曲线：训练损失下降、验证损失同步下降表示仍在有效学习；"
            "训练损失下降而验证损失持续上升才构成过拟合信号。随后分别比较不同 λ、patience 和学习率，保留验证指标最好的模型，"
            "而不是保留最后一轮。\n\n"
            "边界也要说明：验证损失波动还可能来自验证集过小、标签噪声、数据分布漂移或学习率过大。"
            "因此一次上升不能立即下结论，应结合连续趋势、重复实验和独立测试集复核。"
        )
    elif any(marker in topic for marker in ("混合检索", "rag", "文档解析", "重排", "向量检索")):
        answer = (
            "结论：重排只能重新组织已经召回的候选，不能补回解析阶段丢失的正文，也不能把错误切分的片段变成可靠证据。\n\n"
            "完整链路是“原文解析 -> 切分与索引 -> 关键词/向量召回 -> 合并去重 -> 重排 -> 生成回答”。"
            "如果前两步漏页、乱码或把公式与上下文拆散，后续检索面对的就是不完整候选集。即使重排算法把其中最相似的片段排到第一，"
            "它也只是在错误输入中选出相对最优项，无法证明该片段足以支持结论。\n\n"
            "可靠做法是先检查解析覆盖率、页码和章节连续性，再用可回答问题集验证 Recall@K；"
            "关键信息缺失时应明确说明无法确认。关键词权重、向量权重和重排模型只能改善排序，不能替代原始内容完整性检查。"
        )
    else:
        answer = (
            f"先直接回答你的问题：理解“{state.knowledge_point_title}”时，要把结论、成立条件、执行机制和失效边界分开。"
            "结论回答是什么，条件说明何时成立，机制解释为什么会发生，边界则说明在哪些输入或场景下不能沿用。\n\n"
            "可以用一个最小可检验例子验证：固定其他条件，只改变一个关键变量，记录输出是否按理论预期变化；"
            "如果结果不变或方向相反，就回到定义、输入和前提逐项检查，而不是重复结论。"
        )
    answer += f"\n\n第二次复述时，建议重点补上：{gaps}。"
    return QuestionAnswer(
        question=question,
        answer=answer,
        source_ref_ids=source_ids,
        answer_mode="deterministic_local_grounded",
        context_fingerprint=context.context_fingerprint if context else None,
        context_focus=focus_terms,
    )


def _comparison(first: RoundEvaluation, second: RoundEvaluation) -> Comparison:
    first_by_key = {item.key: item for item in first.dimensions}
    improved = []
    lower = []
    for item in second.dimensions:
        previous = first_by_key[item.key]
        if item.score > previous.score:
            improved.append(item.label)
        elif item.score < previous.score:
            lower.append(item.label)
    delta = second.score - first.score
    if delta > 0:
        conclusion = "improved"
    elif delta < 0:
        conclusion = "lower"
    else:
        conclusion = "unchanged"
    remaining = second.gaps
    focus = second.context_focus or first.context_focus
    focus_action = (
        f"围绕“{focus[0]}”补充一个具体例子，并把输入、过程和结果连起来。"
        if focus else "补充一个具体例子，并把输入、过程和结果连起来。"
    )
    next_actions = tuple(
        f"针对“{gap.replace('还需要补充', '')}”补充一句解释和一个具体例子。"
        for gap in remaining[:3]
    ) or (focus_action,)
    return Comparison(
        first_score=first.score,
        second_score=second.score,
        score_delta=delta,
        conclusion=conclusion,
        improved_dimensions=tuple(improved),
        lower_dimensions=tuple(lower),
        remaining_gaps=remaining,
        next_actions=next_actions,
        first_evaluation_id=first.evaluation_id,
        second_evaluation_id=second.evaluation_id,
        context_fingerprint=second.context_fingerprint or first.context_fingerprint,
        context_focus=focus,
    )


def session_payload(
    db: Any, artifact: DBArtifact, version: DBArtifactVersion, state: FeynmanState,
) -> dict[str, Any]:
    versions = db.query(DBArtifactVersion).filter_by(artifact_id=artifact.id).order_by(
        DBArtifactVersion.version_number,
    ).all()
    history = []
    for item in versions:
        saved = FeynmanState.model_validate_json(item.content)
        history.append({
            "version_id": item.id,
            "version_number": item.version_number,
            "status": saved.status,
            "last_action": saved.last_action,
            "round1_score": saved.round1_evaluation.score if saved.round1_evaluation else None,
            "round2_score": saved.round2_evaluation.score if saved.round2_evaluation else None,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        })
    payload = state.model_dump(mode="json")
    live_evaluation = bool(
        (state.round1_evaluation and state.round1_evaluation.evaluation_mode == "llm")
        or (state.round2_evaluation and state.round2_evaluation.evaluation_mode == "llm")
        or (state.question_answer and state.question_answer.answer_mode == "llm_grounded")
    )
    mode = "llm" if live_evaluation or (state.context_snapshot and state.context_snapshot.generation_mode == "llm") else "deterministic_local"
    payload.update(
        version_id=version.id,
        version_number=version.version_number,
        content_sha256=version.content_hash,
        history=history,
        review_mode=mode,
        external_model_called=live_evaluation,
        generation_mode=state.context_snapshot.generation_mode if state.context_snapshot else mode,
        context_fingerprint=state.context_snapshot.context_fingerprint if state.context_snapshot else None,
        context_focus=list(
            state.context_snapshot.profile_focus + state.context_snapshot.recent_event_focus
        ) if state.context_snapshot else [],
    )
    return payload


def get_session(db: Any, session_id: str, owner: str) -> dict[str, Any]:
    return session_payload(db, *_owned_session(db, session_id, owner))


def list_sessions(db: Any, owner: str, source_resource_id: str | None = None) -> list[dict[str, Any]]:
    query = db.query(DBArtifact).filter_by(owner_public_id=owner, artifact_type=SESSION_TYPE)
    rows = query.order_by(DBArtifact.created_at.desc(), DBArtifact.id.desc()).all()
    output = []
    for artifact in rows:
        version = db.get(DBArtifactVersion, artifact.current_version_id)
        state = FeynmanState.model_validate_json(version.content)
        if source_resource_id and state.source_resource_id != source_resource_id:
            continue
        output.append({
            "session_id": state.session_id,
            "source_resource_id": state.source_resource_id,
            "title": state.title,
            "status": state.status,
            "version_number": version.version_number,
            "round1_score": state.round1_evaluation.score if state.round1_evaluation else None,
            "round2_score": state.round2_evaluation.score if state.round2_evaluation else None,
            "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
            "updated_at": artifact.updated_at.isoformat() if artifact.updated_at else None,
        })
    return output


def _existing_action_version(
    db: Any, artifact: DBArtifact, idempotency_key: str, request_hash: str,
) -> DBArtifactVersion | None:
    versions = db.query(DBArtifactVersion).filter_by(artifact_id=artifact.id).order_by(
        DBArtifactVersion.version_number.desc(),
    ).all()
    for version in versions:
        metadata = dict(version.metadata_json or {})
        if metadata.get("action_idempotency_key") != idempotency_key:
            continue
        if metadata.get("action_request_sha256") != request_hash:
            _fail("feynman_idempotency_conflict", "幂等键已绑定到其他费曼操作")
        return version
    return None


def _apply_learning_event(
    db: Any, *, actor: DBUser, state: FeynmanState, idempotency_key: str,
) -> tuple[DBLearningEvent, bool]:
    if state.round1_evaluation is None or state.round2_evaluation is None or state.comparison is None:
        _fail("feynman_evidence_incomplete", "缺少两轮评价或对比，不能应用结果")
    context = ContextRef(
        userId=actor.public_id,
        courseId=state.course_id,
        knowledgePointId=state.knowledge_point_id,
        resourceId=state.source_resource_id,
        sourceRefId=state.source_refs[0].source_ref_id if state.source_refs else None,
    ) if state.course_id else None
    event, created = record_learning_event(
        db,
        owner_public_id=actor.public_id,
        user=actor,
        trusted_source=True,
        event=LearningEventInput(
            idempotency_key=idempotency_key,
            event_type="feynman_submitted",
            context=context,
            course_id=state.course_id,
            object_type="feynman_resource",
            object_id=state.source_resource_id,
            source="backend",
            payload_version=EVENT_PAYLOAD_VERSION,
            payload={
                "evaluation_id": state.round2_evaluation.evaluation_id,
                "rubric_score": state.round2_evaluation.normalized_score,
                "rubric_version": RUBRIC_VERSION,
                "session_id": state.session_id,
                "knowledge_point_id": state.knowledge_point_id,
                "round1_score": state.round1_evaluation.score,
                "round2_score": state.round2_evaluation.score,
                "score_delta": state.comparison.score_delta,
                "source_resource_version_id": state.source_resource_version_id,
                "source_ref_ids": [item.source_ref_id for item in state.source_refs],
                "context_fingerprint": state.context_snapshot.context_fingerprint if state.context_snapshot else None,
                "context_focus": list(
                    state.context_snapshot.profile_focus + state.context_snapshot.recent_event_focus
                ) if state.context_snapshot else [],
                "generation_mode": state.context_snapshot.generation_mode if state.context_snapshot else "deterministic_local",
            },
        ),
    )
    process_path_event(db, event=event)
    return event, created


def apply_action(
    db: Any,
    *,
    session_id: str,
    actor: DBUser,
    action: ActionName,
    text: str | None,
    expected_version: int,
    idempotency_key: str,
) -> tuple[dict[str, Any], bool]:
    artifact, version, state = _owned_session(db, session_id, actor.public_id)
    request_hash = _digest({
        "action": action,
        "text": text,
        "expected_version": expected_version,
    })
    existing = _existing_action_version(db, artifact, idempotency_key, request_hash)
    if existing is not None:
        saved = FeynmanState.model_validate_json(existing.content)
        return session_payload(db, artifact, existing, saved), False
    if version.version_number != expected_version:
        _fail("feynman_version_conflict", "费曼复述会话已经更新，请刷新后继续")

    data = state.model_dump(mode="json")
    if action == "submit_round1":
        if state.status != "draft":
            _fail("feynman_transition_invalid", "只有草稿状态可以提交第一轮复述")
        submitted = _submitted_text(text, minimum=40, maximum=12_000, field="round1")
        data.update(status="round1_submitted", round1_text=submitted, round1_text_sha256=_text_digest(submitted))
    elif action == "evaluate_round1":
        if state.status != "round1_submitted" or not state.round1_text:
            _fail("feynman_transition_invalid", "必须先保存第一轮复述")
        evaluation = (
            _evaluate(
                state.round1_text,
                state.knowledge_point_title,
                round_number=1,
                session_id=session_id,
                context=state.context_snapshot,
            )
            if state.context_snapshot and state.context_snapshot.generation_mode == "deterministic_local"
            else _live_evaluate(state.round1_text, state, round_number=1)
        )
        data.update(status="review1_ready", round1_evaluation=evaluation.model_dump(mode="json"))
    elif action == "begin_question":
        if state.status != "review1_ready" or state.round1_evaluation is None:
            _fail("feynman_transition_invalid", "必须先完成第一轮评价")
        data["status"] = "question_pending"
    elif action == "answer_question":
        if state.status != "question_pending":
            _fail("feynman_transition_invalid", "当前不能提交学习疑问")
        question = _submitted_text(text, minimum=6, maximum=2_000, field="question")
        answer = (
            _answer_question(state, question)
            if state.context_snapshot and state.context_snapshot.generation_mode == "deterministic_local"
            else _live_answer_question(state, question)
        )
        data.update(status="question_answered", question_answer=answer.model_dump(mode="json"))
    elif action == "submit_round2":
        if state.status != "question_answered" or state.question_answer is None:
            _fail("feynman_transition_invalid", "必须先提出真实疑问并获得回答")
        submitted = _submitted_text(text, minimum=40, maximum=12_000, field="round2")
        data.update(status="round2_submitted", round2_text=submitted, round2_text_sha256=_text_digest(submitted))
    elif action == "evaluate_round2":
        if state.status != "round2_submitted" or not state.round2_text or state.round1_evaluation is None:
            _fail("feynman_transition_invalid", "必须先保存第二轮复述")
        second = (
            _evaluate(
                state.round2_text,
                state.knowledge_point_title,
                round_number=2,
                session_id=session_id,
                context=state.context_snapshot,
            )
            if state.context_snapshot and state.context_snapshot.generation_mode == "deterministic_local"
            else _live_evaluate(state.round2_text, state, round_number=2)
        )
        data.update(
            status="comparison_ready",
            round2_evaluation=second.model_dump(mode="json"),
            comparison=_comparison(state.round1_evaluation, second).model_dump(mode="json"),
        )
    elif action == "apply":
        if state.status != "comparison_ready":
            _fail("feynman_transition_invalid", "必须先完成两轮对比")
        event, _ = _apply_learning_event(db, actor=actor, state=state, idempotency_key=idempotency_key)
        data.update(status="applied", applied_event_id=event.id)
    else:
        _fail("feynman_action_unknown", "不支持的费曼复述操作")

    data["last_action"] = action
    next_state = FeynmanState.model_validate(data)
    next_version = add_artifact_version(
        db,
        artifact=artifact,
        content=_canonical(next_state.model_dump(mode="json")),
        content_format="json",
        created_by_public_id=actor.public_id,
        metadata={
            "schema_version": SESSION_SCHEMA_VERSION,
            "status": next_state.status,
            "action": action,
            "action_idempotency_key": idempotency_key,
            "action_request_sha256": request_hash,
            "source_resource_id": next_state.source_resource_id,
            "source_resource_version_id": next_state.source_resource_version_id,
        },
    )
    return session_payload(db, artifact, next_version, next_state), True
