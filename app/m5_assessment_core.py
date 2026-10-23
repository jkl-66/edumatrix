"""Canonical versioned assessment and learner-controlled misconception workflow."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import Field, model_validator

from app.database import (
    DBAssessmentAbilityState, DBAssessmentAttempt, DBAssessmentGradingResult,
    DBAssessmentQuestion, DBAssessmentQuestionVersion, DBAssessmentRetestTask,
    DBAssessmentSelectionTrace, DBMisconceptionReview, DBProfileEvidence,
    DBProfileSnapshot, DBQuizRecord, DBReviewPlan, DBUser,
)
from app.m2_contracts import StrictModel
from app.learner_output import teacher_text
from app.m1_lifecycle import record_audit
from app.m5_learning import LearningEventInput, process_path_event, record_learning_event


class AssessmentCoreError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise AssessmentCoreError(code, message)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


class QuestionVersionInput(StrictModel):
    prompt: str = Field(min_length=1, max_length=20000)
    options: tuple[str, ...] = ()
    answer_key: dict[str, Any]
    scoring_rule: dict[str, Any]
    explanation: str = Field(default="", max_length=20000)
    misconception_tags: tuple[str, ...] = ()
    primary_knowledge_point_id: str | None = None
    secondary_knowledge_point_ids: tuple[str, ...] = ()
    bloom_level: Literal["remember", "understand", "apply", "analyze", "evaluate", "create"] = "understand"
    expert_difficulty: float | None = Field(default=None, ge=0, le=1)
    measured_difficulty: float | None = Field(default=None, ge=0, le=1)
    irt_parameters: dict[str, Any] = Field(default_factory=dict)
    sample_size: int = Field(default=0, ge=0)
    source_ref_ids: tuple[str, ...] = ()


class AttemptInput(StrictModel):
    question_version_id: str
    idempotency_key: str = Field(min_length=8, max_length=128)
    mode: Literal["practice", "diagnostic", "formal", "retest"] = "practice"
    answer: dict[str, Any]
    confidence: float | None = Field(default=None, ge=0, le=1)
    duration_seconds: int | None = Field(default=None, ge=0)


class RubricCriterionResult(StrictModel):
    criterion_id: str = Field(min_length=1, max_length=64)
    score: float = Field(ge=0, le=1)
    evidence: tuple[str, ...] = Field(default=(), max_length=8)
    justification: str = Field(min_length=1, max_length=4000)
    improvement: str = Field(default="", max_length=2000)

    @model_validator(mode="before")
    @classmethod
    def normalize_live_model_fields(cls, value: Any) -> Any:
        """Map the observed DeepSeek rubric labels to the canonical schema.

        DeepSeek sometimes returns the rubric's author-facing ``id``/``label``
        fields and calls the explanation fields ``reason``/``suggestion``.
        These are the same values, not a second grading path; normalize them
        before the strict canonical validation so the score still comes only
        from the model response and the frozen rubric.
        """
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if "criterion_id" not in data and data.get("id") is not None:
            data["criterion_id"] = data["id"]
        if "justification" not in data and data.get("reason") is not None:
            data["justification"] = data["reason"]
        if "improvement" not in data and data.get("suggestion") is not None:
            data["improvement"] = data["suggestion"]
        if isinstance(data.get("evidence"), str):
            evidence = data["evidence"].strip()
            data["evidence"] = [evidence] if evidence else []
        for alias in ("id", "label", "reason", "suggestion"):
            data.pop(alias, None)
        return data


class AIGradingOutput(StrictModel):
    criteria: tuple[RubricCriterionResult, ...] = Field(min_length=1, max_length=12)
    confidence: float = Field(ge=0, le=1)
    summary: str = Field(min_length=1, max_length=4000)
    improvement_plan: tuple[str, ...] = Field(default=(), max_length=8)

    @model_validator(mode="before")
    @classmethod
    def normalize_live_model_shape(cls, value: Any) -> Any:
        """Accept the observed single-string improvement plan from DeepSeek."""
        if not isinstance(value, dict):
            return value
        data = dict(value)
        plan = data.get("improvement_plan")
        if isinstance(plan, str):
            plan = plan.strip()
            data["improvement_plan"] = [plan] if plan else []
        return data


class CatSelectionInput(StrictModel):
    course_id: str | None = None
    excluded_version_ids: tuple[str, ...] = Field(default=(), max_length=200)


class MisconceptionCandidateInput(StrictModel):
    category: Literal["knowledge_gap", "concept_confusion", "strategy_error", "calculation_error", "careless", "programming_error", "insufficient_evidence"]
    rationale: str = Field(default="", max_length=4000)
    evidence: dict[str, Any] = Field(default_factory=dict)
    model_confidence: float | None = Field(default=None, ge=0, le=1)


class MisconceptionDecisionInput(StrictModel):
    decision: Literal["accept", "modify", "reject"]
    category: str = Field(default="", max_length=64)
    note: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def modified_requires_category(self) -> "MisconceptionDecisionInput":
        if self.decision == "modify" and not self.category:
            raise ValueError("modified misconception requires category")
        return self


class RetestAttemptInput(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    answer: dict[str, Any]
    confidence: float | None = Field(default=None, ge=0, le=1)
    duration_seconds: int | None = Field(default=None, ge=0)


def create_question_version(
    session: Any, *, owner_public_id: str, course_id: str | None,
    question_type: str, origin: str, version: QuestionVersionInput,
) -> tuple[DBAssessmentQuestion, DBAssessmentQuestionVersion]:
    validate_question_version(question_type, version)
    question = DBAssessmentQuestion(
        owner_public_id=owner_public_id, course_id=course_id,
        question_type=question_type, origin=origin, status="draft",
    )
    session.add(question)
    session.flush()
    payload = version.model_dump(mode="json")
    row = DBAssessmentQuestionVersion(
        question_id=question.id, version_number=1,
        content_hash=_hash(payload), created_by_public_id=owner_public_id,
        **payload,
    )
    session.add(row)
    session.flush()
    question.current_version_id = row.id
    record_audit(
        session,
        actor_public_id=owner_public_id,
        action="assessment.question.create",
        object_type="assessment_question",
        object_id=question.id,
        metadata={
            "question_type": question_type,
            "origin": origin,
            "version_number": row.version_number,
            "content_included": False,
            "answer_included": False,
        },
    )
    session.flush()
    return question, row


def validate_question_version(question_type: str, version: QuestionVersionInput) -> None:
    if question_type not in {
        "single_choice", "multiple_choice", "true_false", "fill_blank",
        "short_answer", "code", "open_task",
    }:
        _fail("question_type_invalid", "unsupported assessment question type")
    key = version.answer_key or {}
    rule = version.scoring_rule or {}
    if question_type in {"single_choice", "multiple_choice"}:
        if len(version.options) < 2 or len(set(version.options)) != len(version.options):
            _fail("question_options_invalid", "choice questions require at least two unique options")
    if question_type == "single_choice" and not str(key.get("choice", "")).strip():
        _fail("answer_key_invalid", "single choice requires answer_key.choice")
    if question_type == "multiple_choice":
        choices = key.get("choices")
        if not isinstance(choices, (list, tuple)) or not choices:
            _fail("answer_key_invalid", "multiple choice requires answer_key.choices")
    if question_type == "true_false" and "value" not in key:
        _fail("answer_key_invalid", "true/false requires answer_key.value")
    if question_type == "fill_blank":
        blanks = key.get("blanks", key.get("answers"))
        if not isinstance(blanks, (list, tuple)) or not blanks:
            _fail("answer_key_invalid", "fill blank requires answer_key.blanks")
    if question_type in {"short_answer", "open_task"}:
        if not str(key.get("reference_answer", "")).strip():
            _fail("answer_key_invalid", "subjective questions require a reference answer")
        _validated_rubric(rule)
    if question_type == "code":
        entrypoint = str(key.get("entrypoint", ""))
        tests = key.get("hidden_tests")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", entrypoint):
            _fail("answer_key_invalid", "code question requires a valid entrypoint")
        if not isinstance(tests, list) or not tests or len(tests) > 20:
            _fail("answer_key_invalid", "code question requires one to twenty hidden tests")
        for case in tests:
            if not isinstance(case, dict) or "expected" not in case:
                _fail("answer_key_invalid", "each hidden test requires an expected value")
            if not isinstance(case.get("args", []), list) or not isinstance(case.get("kwargs", {}), dict):
                _fail("answer_key_invalid", "hidden test args and kwargs must be structured values")
    parameters = version.irt_parameters or {}
    for name in ("alpha", "beta", "gamma"):
        if name in parameters and not isinstance(parameters[name], (int, float, list, tuple)):
            _fail("irt_parameters_invalid", f"IRT parameter {name} has an invalid type")


def _validated_rubric(scoring_rule: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    criteria = scoring_rule.get("criteria")
    if not isinstance(criteria, list) or not criteria or len(criteria) > 12:
        _fail("rubric_invalid", "AI grading requires one to twelve rubric criteria")
    result = []
    total = 0.0
    seen: set[str] = set()
    for raw in criteria:
        if not isinstance(raw, dict):
            _fail("rubric_invalid", "rubric criteria must be objects")
        criterion_id = str(raw.get("id", "")).strip()
        label = str(raw.get("label", "")).strip()
        try:
            weight = float(raw.get("weight", 0))
        except (TypeError, ValueError):
            weight = -1
        if not criterion_id or criterion_id in seen or not label or weight <= 0:
            _fail("rubric_invalid", "rubric criteria require unique ids, labels and positive weights")
        seen.add(criterion_id)
        total += weight
        result.append({
            "id": criterion_id,
            "label": label,
            "description": str(raw.get("description", ""))[:2000],
            "weight": weight,
            "levels": raw.get("levels", []),
        })
    if total <= 0:
        _fail("rubric_invalid", "rubric weight total must be positive")
    return tuple({**item, "weight": item["weight"] / total} for item in result)


def append_question_version(
    session: Any, *, question: DBAssessmentQuestion, owner_public_id: str,
    expected_current_version_id: str, version: QuestionVersionInput,
) -> DBAssessmentQuestionVersion:
    if question.current_version_id != expected_current_version_id:
        _fail("question_version_conflict", "question current version changed")
    validate_question_version(question.question_type, version)
    latest = session.query(DBAssessmentQuestionVersion).filter_by(
        question_id=question.id,
    ).order_by(DBAssessmentQuestionVersion.version_number.desc()).first()
    payload = version.model_dump(mode="json")
    row = DBAssessmentQuestionVersion(
        question_id=question.id,
        version_number=(latest.version_number if latest else 0) + 1,
        content_hash=_hash(payload),
        created_by_public_id=owner_public_id,
        **payload,
    )
    session.add(row)
    session.flush()
    question.current_version_id = row.id
    record_audit(
        session,
        actor_public_id=owner_public_id,
        action="assessment.question.version.append",
        object_type="assessment_question",
        object_id=question.id,
        metadata={
            "version_number": row.version_number,
            "previous_version_id": expected_current_version_id,
            "content_hash": row.content_hash,
            "answer_included": False,
        },
    )
    session.flush()
    return row


def learner_question_payload(
    version: DBAssessmentQuestionVersion,
    question: DBAssessmentQuestion | None = None,
) -> dict[str, Any]:
    options = learner_option_texts(version, question)
    payload = {
        "id": version.id,
        "question_id": version.question_id,
        "version_number": version.version_number,
        "prompt": learner_safe_prompt(version.prompt),
        "options": options,
        "bloom_level": version.bloom_level,
        "expert_difficulty": version.expert_difficulty,
        "primary_knowledge_point_id": version.primary_knowledge_point_id,
        "content_hash": version.content_hash,
    }
    if question is not None:
        response_spec: dict[str, Any] = {"input_kind": question.question_type}
        if question.question_type == "fill_blank":
            blanks = (version.answer_key or {}).get("blanks", (version.answer_key or {}).get("answers", []))
            response_spec["blank_count"] = len(blanks) if isinstance(blanks, (list, tuple)) else 1
        elif question.question_type == "code":
            tests = (version.answer_key or {}).get("hidden_tests", [])
            response_spec.update({"language": "python", "hidden_test_count": len(tests)})
        elif question.question_type in {"short_answer", "open_task"}:
            response_spec["supports_ai_initial_grading"] = True
        payload.update({
            "question_type": question.question_type,
            "status": question.status,
            "course_id": question.course_id,
            "origin": question.origin,
            "response_spec": response_spec,
        })
    return payload


_OPTION_PROVENANCE_MARKERS = (
    "source_path", "source_ref", "source role", "来源角色", "来源路径", "来源引用",
    "课程版本", "manifest", "commit", "parser_version", "parse_version", "content_hash",
    "chapter_deep-learning", "computation/index", "profile", "画像偏好", "学习画像",
)

_EXPLANATION_PROVENANCE_MARKERS = (
    "先核对已冻结来源", "核对已冻结来源", "冻结课程来源", "绑定课程来源",
    "答案来自冻结", "依据冻结课程来源", "依据课程来源", "绑定来源",
    "生成蓝图", "source_path", "source_ref", "content_hash", "parser_version",
    "parse_version", "manifest", "版本哈希", "课程版本", "证据核验",
    "确定性评分", "本地确定性", "上下文重点", "模型模式", "rubric", "内部 id",
)

_PROMPT_PROVENANCE_MARKERS = (
    "课程来源锚点", "来源锚点", "source_path", "source_ref", "content_hash",
    "parser_version", "parse_version", "manifest", "版本哈希", "课程版本",
    "证据核验", "冻结课程来源", "绑定课程来源",
)


def _option_body(value: Any) -> str:
    """Return only the learner-facing body of an option."""
    if isinstance(value, dict):
        value = next(
            (value.get(key) for key in ("text", "content", "option", "value", "label")
             if value.get(key) not in (None, "")),
            "",
        )
    text = " ".join(str(value or "").strip().split())
    text = re.sub(r"^[A-D](?:[.、:)]\s*|\s+)", "", text, flags=re.IGNORECASE)
    return text.strip()


def _option_is_internal(text: str) -> bool:
    normalized = text.casefold()
    return any(marker.casefold() in normalized for marker in _OPTION_PROVENANCE_MARKERS)


def learner_option_texts(
    version: DBAssessmentQuestionVersion,
    question: DBAssessmentQuestion | None = None,
) -> list[str]:
    """Project historical question options as readable learner choices.

    Older generated versions occasionally persisted provenance strings as an
    option body.  Keep the stored answer labels and history intact, but replace
    only that malformed public projection with four concise, same-level choices.
    """
    raw = [_option_body(item) for item in list(version.options or [])]
    valid = len(raw) >= 2 and all(raw) and not any(_option_is_internal(item) for item in raw)
    if valid:
        return [teacher_text(item) for item in raw]
    prompt = _option_body(version.prompt)
    topic = "当前知识点"
    match = re.search(r"[“『\"]([^”』\"]{2,30})[”』\"]", prompt)
    if match:
        topic = match.group(1)
    correct_label = _choice_label((version.answer_key or {}).get("choice")) or "A"
    bodies = {
        "A": f"先明确“{topic}”的适用条件，再用一个最小例子验证结论。",
        "B": f"只记住“{topic}”的名称，不必确认输入、过程和输出。",
        "C": f"忽略“{topic}”的边界，直接把任意情境都当成相同问题。",
        "D": f"只查看章节标题，就据此判断已经理解“{topic}”。",
    }
    labels = ["A", "B", "C", "D"]
    if correct_label not in labels:
        correct_label = "A"
    # The exact key remains canonical; place the valid learning statement at
    # that label so old attempts continue to grade against the same choice.
    bodies[correct_label] = f"根据题干给出的条件，先说明“{topic}”的机制，再用结果检查理解。"
    return [bodies[label] for label in labels]


def learner_safe_prompt(value: Any, *, knowledge_point: str = "") -> str:
    """Project a learner-facing question without embedded provenance prose.

    Historical and model-generated questions can contain a long ``课程来源锚点``
    clause. That clause remains available through source references, but it is
    not part of the question a learner should read or answer.
    """
    raw = " ".join(str(value or "").strip().split())
    text = raw
    for marker in ("课程来源锚点", "来源锚点"):
        while marker in text:
            start = text.find(marker)
            tail = text[start + len(marker):]
            colon = re.match(r"\s*[：:]\s*", tail)
            content_start = start + len(marker) + (colon.end() if colon else 0)
            quote_start = text.find("“", content_start)
            if quote_start >= 0:
                end = text.find("”。", quote_start + 1)
                if end < 0:
                    end = text.find("”", quote_start + 1)
                if end >= 0:
                    skip = 2 if text[end:end + 2] == "”。" else 1
                    text = (text[:start] + " " + text[end + skip:]).strip()
                    continue
            sentence_end = text.find("。", content_start)
            if sentence_end < 0:
                text = text[:start].rstrip()
            else:
                text = (text[:start] + " " + text[sentence_end + 1:]).strip()
    text = re.sub(r"(^|\s)#{1,6}\s*", " ", text)
    chunks = [chunk.strip() for chunk in re.split(r"(?<=[。！？])\s*", text) if chunk.strip()]
    public = [
        chunk for chunk in chunks
        if not any(marker.casefold() in chunk.casefold() for marker in _PROMPT_PROVENANCE_MARKERS)
    ]
    text = re.sub(r"\s+", " ", " ".join(public))
    text = re.sub(r"(?<=[。！？；：])\s+", "", text).strip(" ，,。；;\n")
    if text:
        return teacher_text(text)
    topic = _option_body(knowledge_point).strip()
    return f"请围绕“{topic}”回答下面的问题。" if topic else "请根据题目条件作答。"


_EXPLANATION_TOPIC_WORDS = (
    "混合检索与重排", "RAG 评测口径", "三画像资源适配", "任务恢复与诚实降级",
    "梯度下降", "学习率", "负梯度", "反向传播", "链式法则", "过拟合", "正则化",
    "二分查找", "循环不变量", "闭区间", "开区间", "Transformer", "注意力机制",
    "卷积神经网络", "池化层", "逻辑回归", "线性回归", "模型评估",
)


def _topic_from_explanation_text(value: Any) -> str:
    candidate = _option_body(value)
    if not candidate:
        return ""
    match = re.search(r"[“『\"]([^”』\"]{2,40})[”』\"]", candidate)
    if match:
        return f"“{match.group(1)}”"
    for word in sorted(_EXPLANATION_TOPIC_WORDS, key=len, reverse=True):
        if word.casefold() in candidate.casefold():
            return f"“{word}”"
    return ""


def learner_topic_title(prompt: Any, fallback: str = "") -> str:
    """Choose the most concrete learner-facing topic named by a question.

    Generated exams may carry a broad planning label while the actual stem
    asks about a narrower concept.  Keep the stored knowledge-point binding,
    but use the concrete topic in the student-facing heading and explanation.
    """
    prompt_text = _option_body(prompt)
    fallback_text = _option_body(fallback)
    if not fallback_text:
        quoted = re.search(r"[“『\"]([^”』\"]{2,40})[”』\"]", prompt_text)
        if quoted:
            return quoted.group(1).strip()
    terms = sorted(_EXPLANATION_TOPIC_WORDS, key=len, reverse=True)
    matches = [term for term in terms if term.casefold() in prompt_text.casefold()]
    if matches:
        if fallback_text and any(term.casefold() in fallback_text.casefold() for term in matches):
            # Keep the stored learner-friendly label when the question and
            # the binding share a concrete term (for example, “过拟合”).
            return fallback_text
        return matches[0]
    return fallback_text or (matches[0] if matches else "")


def _explanation_topic(prompt: Any, knowledge_point: str = "") -> str:
    # The question is the learner's actual task.  A stale or broad knowledge
    # point label must never replace a concrete topic named in the prompt.
    prompt_text = _option_body(prompt)
    knowledge_text = _option_body(knowledge_point)
    display_topic = learner_topic_title(prompt_text, knowledge_text)
    if display_topic:
        return f"“{display_topic[:40]}”"
    prompt_topic = _topic_from_explanation_text(prompt)
    if prompt_topic and knowledge_text:
        prompt_topic_body = prompt_topic.strip("“”")
        if prompt_topic_body and prompt_topic_body in knowledge_text:
            return f"“{knowledge_text[:40]}”"
    for value in (prompt, knowledge_point):
        topic = _topic_from_explanation_text(value)
        if topic:
            return topic
    candidate = re.sub(
        r"^(?:先识别题目给出的关键条件，再选择能说明机制的答案：|结合条件和机制判断，再选择能够解释结果的答案：)\s*",
        "",
        _option_body(prompt) or _option_body(knowledge_point),
    )
    candidate = re.sub(r"\s+", " ", candidate).strip(" 。！？:")
    return f"“{candidate[:24]}”" if candidate else "这道题"


def _explanation_is_internal(text: str) -> bool:
    lowered = text.casefold()
    if not any(marker.casefold() in lowered for marker in _EXPLANATION_PROVENANCE_MARKERS):
        return False
    teaching_markers = (
        "正确", "错误", "选项", "题干", "因为", "因此", "适用", "边界", "复杂度",
        "步骤", "机制", "概念", "示例", "误区", "输入", "输出", "条件",
    )
    # A provenance sentence can accompany a good explanation, but a short
    # provenance-only sentence is never a learner explanation.
    return len(text) < 120 or not any(marker in text for marker in teaching_markers)


def _explanation_option_pairs(options: Any) -> list[tuple[str, str]]:
    values = list(options or []) if isinstance(options, (list, tuple)) else []
    pairs: list[tuple[str, str]] = []
    for index, value in enumerate(values):
        body = _option_body(value)
        if not body:
            continue
        raw = str(value or "").strip()
        match = re.match(r"^([A-D])(?:[.)、:：\s]|$)", raw, re.IGNORECASE)
        label = match.group(1).upper() if match else chr(65 + index)
        pairs.append((label, body))
    return pairs


def _dedupe_explanation_chunks(chunks: list[str]) -> list[str]:
    """Keep one copy of repeated learner-facing explanation sentences."""
    unique: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        cleaned = str(chunk or "").strip()
        key = re.sub(r"\s+", "", cleaned).strip("。！？；：:;,.，")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(cleaned)
    # Some historical records repeat a complete two-sentence block while
    # changing only the whitespace between sentences.  Remove that adjacent
    # duplicate block after sentence-level normalization as well.
    if len(unique) >= 2:
        normalized = [re.sub(r"\s+", "", item).strip("。！？；：:;,.，") for item in unique]
        midpoint = len(unique) // 2
        if len(unique) % 2 == 0 and normalized[:midpoint] == normalized[midpoint:]:
            return unique[:midpoint]
    return unique


def _explanation_answer_labels(question_type: str, answer_key: dict[str, Any] | None) -> list[str]:
    key = dict(answer_key or {})
    if question_type == "single_choice":
        label = _choice_label(key.get("choice"))
        return [label] if label else []
    if question_type == "multiple_choice":
        return [_choice_label(item) for item in key.get("choices", []) if _choice_label(item)]
    return []


def _fallback_learner_explanation(
    *, prompt: Any, options: Any, answer_key: dict[str, Any] | None,
    question_type: str, knowledge_point: str = "",
) -> str:
    topic = _explanation_topic(prompt, knowledge_point)
    key = dict(answer_key or {})
    if question_type in {"single_choice", "multiple_choice"}:
        pairs = _explanation_option_pairs(options)
        labels = _explanation_answer_labels(question_type, key)
        answer_text = "、".join(labels) if labels else "题目给出的正确选项"
        lines = [
            f"这道题考查{topic}的关键条件和判断方法。正确答案是 {answer_text}。",
            "判断时先提取题干要求，再检查选项是否同时满足对象、条件和结果，而不是只看熟悉的术语。",
        ]
        for label, body in pairs:
            short_body = body[:120]
            if label in labels:
                lines.append(f"选项 {label}（{short_body}）正确：它与题干条件一致，能够支持{topic}的核心结论。")
            else:
                if any(word in body for word in ("只", "忽略", "跳过", "无关", "任意")):
                    reason = "省略或改变了题干要求的关键条件，无法推出题目结论"
                else:
                    reason = "没有同时满足题干给出的条件，因而不能作为本题结论"
                lines.append(f"选项 {label}（{short_body}）不正确：{reason}。")
        lines.append(f"常见误区是把‘记住定义’当成‘能够判断适用边界’；遇到变式题时，应再用一个最小例子验证{topic}是否仍成立。")
        return " ".join(lines)
    if question_type == "true_false":
        expected = _boolean(key.get("value"))
        verdict = "正确" if expected is True else "错误" if expected is False else "需要结合题干条件判断"
        statement = _option_body(prompt)
        statement = re.sub(r"^(?:判断|判断题)\s*[：:]\s*", "", statement).strip()
        statement_line = f"题干要判断的是：“{statement}”。" if statement else "先把题干要判断的结论说清楚。"
        return (
            f"这道题考查{topic}的适用条件。{statement_line}题干判断为“{verdict}”。"
            "理由是先核对题干中的对象、前提和结果，再判断结论是否在这些条件下成立；只背术语而忽略边界，容易把相反情境误判为同一结论。"
            "可以做一个最小自检：保持对象和结果不变，只去掉或替换一个关键前提，再观察结论是否随之改变。"
            "如果答案发生变化，就说明该前提是判断边界，不能在复述时省略；最后再把原条件代回题干核对一次。"
        )
    if question_type == "fill_blank":
        blanks = key.get("blanks", key.get("answers", []))
        answer = "、".join(str(item[0] if isinstance(item, (list, tuple)) and item else item) for item in (blanks or []))
        return (
            f"这道题要求补出{topic}的关键术语或步骤。参考答案为：{answer or '题干要求的核心概念'}。"
            "作答时要结合题目条件解释这个术语的作用，而不是只写一个孤立的名词。"
        )
    if question_type in {"short_answer", "open_task"}:
        reference = str(key.get("reference_answer") or "").strip()
        detail = reference[:220] if reference else f"说明{topic}的定义、关键步骤和适用边界"
        return (
            f"这道题要求围绕{topic}组织完整说明。回答至少应覆盖：{detail}。"
            "先给结论，再解释原因和成立条件，最后补一个例子或反例；只复述名词而没有推理过程，不能说明你真正理解。"
        )
    return (
        f"这道题考查{topic}。请先明确输入、关键机制和预期输出，再按步骤执行并检查结果；"
        "如果结果不符合预期，优先检查边界条件、数据类型和中间状态，而不是直接修改结论。"
    )


def learner_safe_explanation(
    value: Any, *, prompt: str = "", options: Any = (),
    answer_key: dict[str, Any] | None = None, question_type: str = "single_choice",
    knowledge_point: str = "",
) -> str:
    """Return a question-specific learner explanation without provenance prose."""
    text = " ".join(str(value or "").strip().split())
    if text:
        # Match each sentence explicitly so adjacent Chinese sentences
        # without whitespace are still treated as separate chunks.
        chunks = [chunk.strip() for chunk in re.findall(r"[^。！？]+[。！？]?", text) if chunk.strip()]
        public = [chunk for chunk in chunks if not _option_is_internal(chunk) and not _explanation_is_internal(chunk)]
        text = " ".join(_dedupe_explanation_chunks(public)).strip()
    fallback = teacher_text(_fallback_learner_explanation(
        prompt=prompt, options=options, answer_key=answer_key,
        question_type=question_type, knowledge_point=knowledge_point,
    ))
    if text and not _explanation_is_internal(text):
        public_text = teacher_text(text)
        # Historical short explanations often equal the generated fallback.
        # Return one copy instead of repeating the same paragraph twice.
        if public_text.strip() == fallback.strip() or fallback.strip() in public_text:
            return public_text
        if public_text.strip() in fallback.strip():
            return fallback
        if question_type == "fill_blank" and ("参考答案" in public_text or "答案" in public_text):
            # Fill-in explanations are often already complete; appending the
            # generated fallback would repeat the answer and instructions.
            return public_text
        if len(public_text) >= 160:
            return public_text
        return teacher_text(f"{public_text} {fallback}")
    return fallback


def learner_correct_answer(question_type: str, answer_key: dict[str, Any]) -> dict[str, Any] | None:
    """Project only the learner-visible answer after feedback is allowed."""
    key = dict(answer_key or {})
    if question_type == "single_choice":
        return {"choice": _choice_label(key.get("choice"))}
    if question_type == "multiple_choice":
        return {"choices": [_choice_label(item) for item in key.get("choices", [])]}
    if question_type == "true_false":
        return {"value": _boolean(key.get("value"))}
    if question_type == "fill_blank":
        return {"blanks": key.get("blanks", key.get("answers", []))}
    if question_type in {"short_answer", "open_task"}:
        return {"reference_answer": str(key.get("reference_answer", ""))}
    return None


def _choice_label(value: Any) -> str:
    text = str(value or "").strip().upper()
    match = re.match(r"^([A-Z])(?:[.)、:\s]|$)", text)
    return match.group(1) if match else text


def _boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y", "对", "正确", "是"}:
        return True
    if normalized in {"false", "0", "no", "n", "错", "错误", "否"}:
        return False
    return None


def _normal_text(value: Any, *, case_sensitive: bool) -> str:
    text = " ".join(str(value or "").strip().split())
    return text if case_sensitive else text.casefold()


def grade_objective_answer(
    question_type: str, answer: dict[str, Any], answer_key: dict[str, Any],
    scoring_rule: dict[str, Any],
) -> dict[str, Any]:
    score = 0.0
    evidence: dict[str, Any] = {"question_type": question_type, "policy": "deterministic"}
    if question_type == "single_choice":
        submitted = _choice_label(answer.get("choice"))
        expected = _choice_label(answer_key.get("choice"))
        score = 1.0 if submitted and submitted == expected else 0.0
        evidence["normalized_submission"] = submitted
    elif question_type == "multiple_choice":
        submitted = {_choice_label(item) for item in answer.get("choices", []) if _choice_label(item)}
        expected = {_choice_label(item) for item in answer_key.get("choices", []) if _choice_label(item)}
        if scoring_rule.get("partial_credit"):
            score = max(0.0, (len(submitted & expected) - len(submitted - expected)) / max(1, len(expected)))
        else:
            score = 1.0 if submitted == expected else 0.0
        evidence.update({"selected_count": len(submitted), "matched_count": len(submitted & expected)})
    elif question_type == "true_false":
        submitted = _boolean(answer.get("value"))
        expected = _boolean(answer_key.get("value"))
        score = 1.0 if submitted is not None and submitted == expected else 0.0
        evidence["normalized_submission"] = submitted
    elif question_type == "fill_blank":
        case_sensitive = bool(scoring_rule.get("case_sensitive", False))
        submitted = answer.get("blanks", [])
        expected = answer_key.get("blanks", answer_key.get("answers", []))
        if not isinstance(submitted, list):
            submitted = []
        matches = []
        for index, accepted in enumerate(expected):
            alternatives = accepted if isinstance(accepted, (list, tuple)) else [accepted]
            actual = _normal_text(submitted[index] if index < len(submitted) else "", case_sensitive=case_sensitive)
            allowed = {_normal_text(item, case_sensitive=case_sensitive) for item in alternatives}
            matches.append(bool(actual) and actual in allowed)
        score = sum(matches) / max(1, len(matches)) if scoring_rule.get("partial_credit", True) else float(all(matches))
        evidence.update({"blank_count": len(matches), "matched_count": sum(matches), "case_sensitive": case_sensitive})
    else:
        _fail("objective_grader_unsupported", "question type requires a specialized grader")
    score = round(min(1.0, max(0.0, score)), 6)
    threshold = float(scoring_rule.get("correct_threshold", 1.0))
    return {
        "score": score,
        "correct": score >= threshold,
        "confidence": 1.0,
        "evidence": evidence,
        "criterion_results": [{
            "criterion_id": "answer_correctness",
            "score": score,
            "evidence": ["答案已完成逐项比对"],
            "justification": "你的作答已与本题正确答案逐项比较。",
            "improvement": "如果没有答对，请结合逐题解析复习遗漏或误选的部分。",
        }],
        "feedback": "本题已完成批改。",
        "improvement_advice": [] if score >= threshold else ["查看解析并针对未命中部分复习。"],
    }


def create_grading_result(
    session: Any, *, attempt: DBAssessmentAttempt, grader_type: str,
    rubric_version: str, rubric_snapshot: dict[str, Any], status: str,
    score: float | None, correct: bool | None, confidence: float | None,
    criterion_results: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    evidence: dict[str, Any], feedback: str, improvement_advice: list[str] | tuple[str, ...],
    trace_id: str = "", created_by_public_id: str | None = None,
) -> tuple[DBAssessmentGradingResult, bool]:
    payload = {
        "status": status,
        "score": score,
        "correct": correct,
        "confidence": confidence,
        "rubric_snapshot": rubric_snapshot,
        "criterion_results": list(criterion_results),
        "evidence": evidence,
        "feedback": feedback,
        "improvement_advice": list(improvement_advice),
        "trace_id": trace_id,
    }
    content_hash = _hash(payload)
    existing = session.query(DBAssessmentGradingResult).filter_by(
        attempt_id=attempt.id, grader_type=grader_type, rubric_version=rubric_version,
    ).first()
    if existing is not None:
        if existing.content_hash != content_hash:
            _fail("grading_result_conflict", "grading result key is bound to different evidence")
        return existing, False
    row = DBAssessmentGradingResult(
        attempt_id=attempt.id,
        owner_public_id=attempt.owner_public_id,
        grader_type=grader_type,
        rubric_version=rubric_version,
        rubric_snapshot=rubric_snapshot,
        criterion_results=list(criterion_results),
        score=score,
        correct=correct,
        confidence=confidence,
        evidence=evidence,
        feedback=feedback,
        improvement_advice=list(improvement_advice),
        trace_id=trace_id,
        status=status,
        content_hash=content_hash,
        created_by_public_id=created_by_public_id,
    )
    session.add(row)
    session.flush()
    record_audit(
        session,
        actor_public_id=created_by_public_id or attempt.owner_public_id,
        action="assessment.grading.create",
        object_type="assessment_grading_result",
        object_id=row.id,
        metadata={
            "attempt_id": attempt.id,
            "grader_type": grader_type,
            "status": status,
            "rubric_version": rubric_version,
            "score": score,
            "content_hash": content_hash,
            "answer_included": False,
            "hidden_tests_included": False,
        },
    )
    session.flush()
    return row, True


def record_attempt(
    session: Any, *, owner_public_id: str, attempt: AttemptInput,
    trusted_final_grade: tuple[float, bool] | None = None,
) -> tuple[DBAssessmentAttempt, bool]:
    version = session.query(DBAssessmentQuestionVersion).filter_by(id=attempt.question_version_id).first()
    if version is None:
        _fail("question_version_unknown", "assessment question version does not exist")
    question = session.query(DBAssessmentQuestion).filter_by(id=version.question_id).one()
    existing = session.query(DBAssessmentAttempt).filter_by(
        owner_public_id=owner_public_id, idempotency_key=attempt.idempotency_key,
    ).first()
    submitted = {**attempt.model_dump(mode="json"), "course_id": question.course_id}
    objective_result = None
    if question.question_type in {"short_answer", "code", "open_task"}:
        if trusted_final_grade is None:
            # A subjective response has no score until the governed grader
            # finishes.  Keep it explicitly pending instead of writing a
            # misleading zero that could be mistaken for a failed answer.
            score, correct, grading_status = None, None, "pending"
        else:
            if attempt.mode != "formal":
                _fail("attempt_final_grade_forbidden", "precomputed grades are limited to formal submissions")
            score, correct = trusted_final_grade
            if not 0.0 <= float(score) <= 1.0 or not isinstance(correct, bool):
                _fail("attempt_final_grade_invalid", "precomputed grade must contain a valid score and decision")
            score, grading_status = float(score), "graded"
    else:
        objective_result = grade_objective_answer(
            question.question_type, attempt.answer, version.answer_key or {}, version.scoring_rule or {},
        )
        score, correct, grading_status = objective_result["score"], objective_result["correct"], "graded"
    feedback_policy = {
        "practice": "immediate", "diagnostic": "after_submission",
        "formal": "after_close", "retest": "after_submission",
    }[attempt.mode]
    payload = {
        **submitted, "score": score, "correct": correct,
        "grading_status": grading_status, "feedback_policy": feedback_policy,
    }
    if existing is not None:
        comparable = {
            "question_version_id": existing.question_version_id, "idempotency_key": existing.idempotency_key,
            "course_id": existing.course_id, "mode": existing.mode, "answer": existing.answer,
            "score": existing.score, "correct": existing.correct, "confidence": existing.confidence,
            "duration_seconds": existing.duration_seconds, "grading_status": existing.grading_status,
            "feedback_policy": existing.feedback_policy,
        }
        if _canonical(comparable) != _canonical(payload):
            _fail("attempt_idempotency_conflict", "idempotency key is bound to another attempt")
        return existing, False
    row = DBAssessmentAttempt(owner_public_id=owner_public_id, **payload)
    session.add(row)
    session.flush()
    if objective_result is not None:
        ability_update = (
            {"applied": False, "reason": "formal_exam_updates_after_whole_submission"}
            if attempt.mode == "formal"
            else update_ability_state(
                session, attempt=row, version=version, correct=bool(objective_result["correct"]),
            )
        )
        create_grading_result(
            session,
            attempt=row,
            grader_type="deterministic",
            rubric_version=str((version.scoring_rule or {}).get("version", "objective-v1")),
            rubric_snapshot={"question_type": question.question_type, "rule": version.scoring_rule or {}},
            status="completed",
            score=objective_result["score"],
            correct=objective_result["correct"],
            confidence=objective_result["confidence"],
            criterion_results=objective_result["criterion_results"],
            evidence={**objective_result["evidence"], "ability_update": ability_update},
            feedback=objective_result["feedback"],
            improvement_advice=objective_result["improvement_advice"],
        )
    return row, True


def _course_scope(course_id: str | None) -> str:
    return course_id or "__global__"


def get_or_create_ability_state(
    session: Any, *, owner_public_id: str, course_id: str | None,
) -> DBAssessmentAbilityState:
    scope = _course_scope(course_id)
    row = session.query(DBAssessmentAbilityState).filter_by(
        owner_public_id=owner_public_id, course_scope=scope,
    ).first()
    if row is None:
        row = DBAssessmentAbilityState(
            owner_public_id=owner_public_id,
            course_scope=scope,
            theta=[0.0, 0.0, 0.0],
            theta_std=[1.0, 1.0, 1.0],
            theta_cov=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        )
        session.add(row)
        session.flush()
    return row


def ability_state_payload(row: DBAssessmentAbilityState) -> dict[str, Any]:
    return {
        "id": row.id,
        "course_id": None if row.course_scope == "__global__" else row.course_scope,
        "theta": list(row.theta or [0.0, 0.0, 0.0]),
        "theta_std": list(row.theta_std or [1.0, 1.0, 1.0]),
        "theta_cov": row.theta_cov or [],
        "response_count": row.response_count,
        "lock_version": row.lock_version,
        "last_attempt_id": row.last_attempt_id,
    }


def update_ability_state(
    session: Any, *, attempt: DBAssessmentAttempt,
    version: DBAssessmentQuestionVersion, correct: bool,
) -> dict[str, Any]:
    from mirt_engine import AdaptiveTestEstimator, IRTItemParams

    state = get_or_create_ability_state(
        session, owner_public_id=attempt.owner_public_id, course_id=attempt.course_id,
    )
    before = ability_state_payload(state)
    if state.last_attempt_id == attempt.id:
        return {"before": before, "after": before, "applied": False}
    estimator = AdaptiveTestEstimator(
        theta=state.theta or [0.0, 0.0, 0.0],
        theta_std=state.theta_std or [1.0, 1.0, 1.0],
        theta_cov=state.theta_cov or None,
    )
    parameters = version.irt_parameters or {}
    item = IRTItemParams.from_dict({
        "alpha": parameters.get("alpha_vector") or parameters.get("alpha") or 1.0,
        "beta": parameters.get("beta_vector") or parameters.get("beta") or 0.0,
        "gamma": parameters.get("gamma") if parameters.get("gamma") is not None else 0.25,
    })
    estimator.update_ability(item, bool(correct))
    state.theta = list(estimator.theta)
    state.theta_std = list(estimator.theta_std)
    state.theta_cov = estimator.theta_cov
    state.response_count = int(state.response_count or 0) + 1
    state.lock_version = int(state.lock_version or 0) + 1
    state.last_attempt_id = attempt.id
    session.flush()
    return {"before": before, "after": ability_state_payload(state), "applied": True}


def ai_grading_prompt(
    version: DBAssessmentQuestionVersion, answer: dict[str, Any],
) -> tuple[str, str, str, dict[str, Any]]:
    criteria = _validated_rubric(version.scoring_rule or {})
    rubric_version = str((version.scoring_rule or {}).get("version", "rubric-v1"))
    rubric = {"version": rubric_version, "criteria": list(criteria)}
    system_prompt = (
        "你是 EduMatrix 的 AI 智能初评器。只依据冻结评分量规逐项判断。"
        "必须先为每项给出可核查证据、理由和改进建议，再给 0 到 1 的分数。"
        "不要因答案更长或语气更自信而加分；证据不足时降低置信度。"
        "返回严格 JSON，顶层字段必须为 criteria、confidence、summary、improvement_plan；"
        "criteria 中每项字段必须严格为 criterion_id（使用输入量规中的 id）、score（0 到 1）、"
        "evidence（字符串数组）、justification（字符串）和 improvement（字符串）；"
        "improvement_plan 必须是字符串数组。不要输出 id、label、reason、suggestion 等替代字段。"
    )
    user_prompt = _canonical({
        "question": version.prompt,
        "reference_answer": (version.answer_key or {}).get("reference_answer", ""),
        "learner_answer": answer.get("text", answer.get("content", "")),
        "rubric": rubric,
    })
    return system_prompt, user_prompt, rubric_version, rubric


def persist_ai_grading(
    session: Any, *, attempt_id: str, output: AIGradingOutput,
    trace_id: str, created_by_public_id: str | None = None,
    rubric_version_override: str | None = None,
) -> tuple[DBAssessmentGradingResult, dict[str, Any]]:
    attempt = session.query(DBAssessmentAttempt).filter_by(id=attempt_id).first()
    if attempt is None:
        _fail("attempt_unknown", "assessment attempt does not exist")
    version = session.query(DBAssessmentQuestionVersion).filter_by(id=attempt.question_version_id).one()
    question = session.query(DBAssessmentQuestion).filter_by(id=version.question_id).one()
    if question.question_type not in {"short_answer", "open_task"}:
        _fail("ai_grader_unsupported", "AI rubric grading is limited to subjective text questions")
    criteria = _validated_rubric(version.scoring_rule or {})
    expected_ids = [item["id"] for item in criteria]
    actual = {item.criterion_id: item for item in output.criteria}
    if len(actual) != len(output.criteria) or set(actual) != set(expected_ids):
        _fail("ai_grading_criteria_invalid", "AI grading criteria do not match the frozen rubric")
    score = round(sum(actual[item["id"]].score * item["weight"] for item in criteria), 6)
    threshold = float((version.scoring_rule or {}).get("correct_threshold", 0.6))
    rubric_version = rubric_version_override or str((version.scoring_rule or {}).get("version", "rubric-v1"))
    result, created = create_grading_result(
        session,
        attempt=attempt,
        grader_type="ai",
        rubric_version=rubric_version,
        rubric_snapshot={"criteria": list(criteria)},
        status="completed",
        score=score,
        correct=score >= threshold,
        confidence=output.confidence,
        criterion_results=[item.model_dump(mode="json") for item in output.criteria],
        evidence={
            "criterion_count": len(criteria),
            "answer_hash": _hash(attempt.answer),
            "source_ref_ids": list(version.source_ref_ids or []),
            "label": "AI 智能初评",
        },
        feedback=output.summary,
        improvement_advice=list(output.improvement_plan),
        trace_id=trace_id,
        created_by_public_id=created_by_public_id,
    )
    # Attempts are immutable after submission.  The grading row is the
    # canonical post-submission score/feedback record consumed by reports and
    # learning aggregation; do not mutate the submitted attempt to mirror it.
    ability = update_ability_state(
        session, attempt=attempt, version=version, correct=bool(result.correct),
    ) if created else {"applied": False}
    return result, ability


def persist_failed_ai_grading(
    session: Any, *, attempt_id: str, rubric_version: str,
    rubric_snapshot: dict[str, Any], trace_id: str, error_code: str,
) -> DBAssessmentGradingResult:
    attempt = session.query(DBAssessmentAttempt).filter_by(id=attempt_id).first()
    if attempt is None:
        _fail("attempt_unknown", "assessment attempt does not exist")
    result, _ = create_grading_result(
        session,
        attempt=attempt,
        grader_type="ai",
        rubric_version=rubric_version,
        rubric_snapshot=rubric_snapshot,
        status="failed",
        score=None,
        correct=None,
        confidence=None,
        criterion_results=[],
        evidence={"error_code": error_code, "answer_hash": _hash(attempt.answer), "label": "AI 智能初评"},
        feedback="AI 智能初评暂不可用，本次作答已保存。",
        improvement_advice=["稍后重试评分，或在正式高风险场景申请人工复核。"],
        trace_id=trace_id,
    )
    # The submitted attempt is immutable and was created with a pending
    # subjective state.  Keep that state unchanged; the failed grading row is
    # the durable retry/error evidence.
    return result


async def grade_code_submission(
    version: DBAssessmentQuestionVersion, answer: dict[str, Any], runner: Any,
) -> dict[str, Any]:
    code = str(answer.get("code", "")).strip()
    if not code:
        _fail("code_answer_invalid", "code answer cannot be empty")
    if len(code.encode("utf-8")) > 50000:
        _fail("code_answer_too_large", "code answer exceeds the execution limit")
    key = version.answer_key or {}
    entrypoint = str(key.get("entrypoint", ""))
    cases = key.get("hidden_tests", [])
    suite_hash = _hash({"entrypoint": entrypoint, "hidden_tests": cases})
    case_evidence = []
    total_duration = 0
    for index, case in enumerate(cases):
        harness = (
            code
            + "\nimport json as __json\n"
            + f"__actual = {entrypoint}(*{repr(case.get('args', []))}, **{repr(case.get('kwargs', {}))})\n"
            + f"print('__EDUMATRIX_TEST__' + __json.dumps(__actual == {repr(case.get('expected'))}))\n"
        )
        stdout, stderr, duration = await runner.run(harness)
        total_duration += int(duration * 1000)
        passed = "__edumatrix_test__true" in str(stdout).lower() and not stderr
        case_evidence.append({
            "case": index + 1,
            "passed": passed,
            "error_category": "runtime_error" if stderr else "assertion_failed" if not passed else "",
        })
    passed_count = sum(1 for item in case_evidence if item["passed"])
    score = round(passed_count / max(1, len(case_evidence)), 6)
    threshold = float((version.scoring_rule or {}).get("correct_threshold", 1.0))
    return {
        "score": score,
        "correct": score >= threshold,
        "confidence": 1.0,
        "criterion_results": [{
            "criterion_id": "hidden_tests",
            "score": score,
            "evidence": [f"隐藏测试通过 {passed_count}/{len(case_evidence)}"],
            "justification": "提交的代码已经运行，并完成全部测试用例检查。",
            "improvement": "根据脱敏后的失败用例数量检查边界条件。",
        }],
        "evidence": {
            "suite_hash": suite_hash,
            "test_scope": "hidden",
            "passed_count": passed_count,
            "total_count": len(case_evidence),
            "cases": case_evidence,
            "execution_time_ms": total_duration,
            "hidden_inputs_included": False,
            "hidden_expected_included": False,
        },
        "feedback": f"隐藏测试通过 {passed_count}/{len(case_evidence)}。",
        "improvement_advice": [] if score >= threshold else ["检查未覆盖的边界条件和异常输入。"],
    }


def persist_code_grading(
    session: Any, *, attempt_id: str, result: dict[str, Any], trace_id: str,
) -> tuple[DBAssessmentGradingResult, dict[str, Any]]:
    attempt = session.query(DBAssessmentAttempt).filter_by(id=attempt_id).first()
    if attempt is None:
        _fail("attempt_unknown", "assessment attempt does not exist")
    version = session.query(DBAssessmentQuestionVersion).filter_by(id=attempt.question_version_id).one()
    row, created = create_grading_result(
        session,
        attempt=attempt,
        grader_type="code",
        rubric_version=str((version.scoring_rule or {}).get("version", "hidden-tests-v1")),
        rubric_snapshot={"type": "hidden_tests", "suite_hash": result["evidence"]["suite_hash"]},
        status="completed",
        score=result["score"],
        correct=result["correct"],
        confidence=result["confidence"],
        criterion_results=result["criterion_results"],
        evidence=result["evidence"],
        feedback=result["feedback"],
        improvement_advice=result["improvement_advice"],
        trace_id=trace_id,
    )
    ability = update_ability_state(
        session, attempt=attempt, version=version, correct=bool(row.correct),
    ) if created else {"applied": False}
    return row, ability


def grading_result_payload(row: DBAssessmentGradingResult | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "grader_type": row.grader_type,
        "label": "AI 智能初评" if row.grader_type == "ai" else "代码隐藏测试" if row.grader_type == "code" else "服务端客观评分",
        "status": row.status,
        "rubric_version": row.rubric_version,
        "criterion_results": row.criterion_results or [],
        "score": row.score,
        "correct": row.correct,
        "confidence": row.confidence,
        "evidence": row.evidence or {},
        "feedback": row.feedback,
        "improvement_advice": row.improvement_advice or [],
        "trace_id": row.trace_id,
        "content_hash": row.content_hash,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def select_cat_question(
    session: Any, *, owner_public_id: str, course_id: str | None,
    candidates: list[tuple[DBAssessmentQuestion, DBAssessmentQuestionVersion]],
    excluded_version_ids: tuple[str, ...] = (),
) -> tuple[DBAssessmentQuestionVersion, DBAssessmentSelectionTrace, DBAssessmentAbilityState]:
    from mirt_engine import AdaptiveTestEstimator, IRTItemParams

    excluded = set(excluded_version_ids)
    available = [(question, version) for question, version in candidates if version.id not in excluded]
    if not available:
        _fail("cat_candidates_empty", "no eligible CAT question remains")
    ability = get_or_create_ability_state(
        session, owner_public_id=owner_public_id, course_id=course_id,
    )
    estimator = AdaptiveTestEstimator(theta=ability.theta, theta_std=ability.theta_std, theta_cov=ability.theta_cov or None)
    metrics = []
    for question, version in available:
        raw = version.irt_parameters or {}
        item = IRTItemParams.from_dict({
            "alpha": raw.get("alpha_vector") or raw.get("alpha") or 1.0,
            "beta": raw.get("beta_vector") or raw.get("beta") or 0.0,
            "gamma": raw.get("gamma") if raw.get("gamma") is not None else 0.25,
        })
        metrics.append({
            "question_version_id": version.id,
            "question_type": question.question_type,
            "information": round(estimator.compute_d_optimality(estimator.theta, item), 8),
            "content_hash": version.content_hash,
        })
    metrics.sort(key=lambda item: (-item["information"], item["question_version_id"]))
    selected_id = metrics[0]["question_version_id"]
    selected = next(version for _, version in available if version.id == selected_id)
    trace_payload = {
        "algorithm_version": "mirt-d-optimal-v1",
        "ability_before": ability_state_payload(ability),
        "candidate_metrics": metrics,
        "excluded_version_ids": sorted(excluded),
        "selected_question_version_id": selected_id,
    }
    trace = DBAssessmentSelectionTrace(
        owner_public_id=owner_public_id,
        course_scope=_course_scope(course_id),
        selected_question_version_id=selected_id,
        algorithm_version="mirt-d-optimal-v1",
        ability_before=trace_payload["ability_before"],
        candidate_metrics=metrics,
        excluded_version_ids=sorted(excluded),
        trace_hash=_hash(trace_payload),
    )
    session.add(trace)
    session.flush()
    return selected, trace, ability


def _legacy_choice(value: Any) -> str:
    """Match the legacy grader's first-letter choice normalization."""
    normalized = str(value or "").strip().upper()
    return normalized[:1]


def _legacy_question_type(quiz_record: DBQuizRecord) -> str:
    if quiz_record.options:
        return "single_choice"
    # The legacy quiz row has no hidden-test contract, so an optionless answer
    # is replayable as rubric-graded text rather than a guessed code question.
    return "short_answer"


def _legacy_scoring_rule(question_type: str) -> dict[str, Any]:
    if question_type == "single_choice":
        return {
            "type": "exact",
            "version": "legacy-choice-v1",
            "correct_threshold": 1.0,
            "trusted_source": "quiz_api.evaluate",
        }
    return {
        "type": "ai_rubric",
        "version": "legacy-subjective-v1",
        "correct_threshold": 0.6,
        "trusted_source": "quiz_api.evaluate",
        "criteria": [
            {
                "id": "concept_accuracy",
                "label": "概念准确性",
                "description": "回答中的核心概念、关系和结论是否准确。",
                "weight": 0.7,
            },
            {
                "id": "reasoning_completeness",
                "label": "推理完整性",
                "description": "回答是否给出支撑结论所需的关键推理或条件。",
                "weight": 0.3,
            },
        ],
    }


def ensure_legacy_quiz_question_version(
    session: Any,
    *,
    owner_public_id: str,
    quiz_record: DBQuizRecord,
) -> dict[str, Any]:
    """Create or reuse a replayable canonical identity without recording an attempt."""
    if not isinstance(quiz_record, DBQuizRecord) or not quiz_record.id:
        _fail("legacy_quiz_invalid", "legacy quiz record is required")
    owner = session.query(DBUser).filter_by(public_id=owner_public_id).first()
    if owner is None:
        _fail("legacy_owner_unknown", "legacy quiz owner does not exist")
    if quiz_record.student_id and quiz_record.student_id != owner.username:
        _fail("legacy_quiz_owner_mismatch", "legacy quiz belongs to another owner")

    legacy_ref = f"legacy-quiz:{quiz_record.id}"
    question_id = f"aq_legacy_{hashlib.sha256(legacy_ref.encode('utf-8')).hexdigest()[:48]}"
    inferred_type = _legacy_question_type(quiz_record)
    question = session.query(DBAssessmentQuestion).filter_by(id=question_id).first()
    question_created = question is None
    if question is None:
        question = DBAssessmentQuestion(
            id=question_id,
            owner_public_id=owner_public_id,
            course_id=None,
            question_type=inferred_type,
            origin="legacy",
            status="approved",
        )
        session.add(question)
        session.flush()
    elif question.origin != "legacy" or question.owner_public_id != owner_public_id:
        _fail("legacy_question_identity_conflict", "legacy quiz identity is bound to another question")

    question_type = question.question_type
    if question_type not in {"single_choice", "short_answer"}:
        _fail("legacy_question_not_replayable", "legacy question has no replayable grading contract")
    options = tuple(str(option) for option in (quiz_record.options or []))
    answer_key = (
        {"choice": _legacy_choice(quiz_record.correct_answer)}
        if question_type == "single_choice"
        else {"reference_answer": str(quiz_record.correct_answer or "")}
    )
    version_input = QuestionVersionInput(
        prompt=str(quiz_record.question or ""),
        options=options,
        answer_key=answer_key,
        scoring_rule=_legacy_scoring_rule(question_type),
        primary_knowledge_point_id=None,
        irt_parameters={
            "alpha": quiz_record.irt_alpha,
            "beta": quiz_record.irt_beta,
            "gamma": quiz_record.irt_gamma,
            "alpha_vector": quiz_record.irt_alpha_vec,
            "beta_vector": quiz_record.irt_beta_vec,
        },
        source_ref_ids=(legacy_ref,),
    )
    validate_question_version(question_type, version_input)
    version_payload = version_input.model_dump(mode="json")
    content_hash = _hash(version_payload)
    version = session.query(DBAssessmentQuestionVersion).filter_by(
        question_id=question.id,
        content_hash=content_hash,
    ).first()
    version_created = version is None
    if version is None:
        existing = session.query(DBAssessmentQuestionVersion).filter_by(
            question_id=question.id,
        ).order_by(DBAssessmentQuestionVersion.version_number.desc()).all()
        if existing:
            latest = existing[0]
            same_content = (
                latest.prompt == version_input.prompt
                and tuple(latest.options or ()) == version_input.options
                and _canonical(latest.answer_key or {}) == _canonical(version_input.answer_key)
            )
            if not same_content:
                _fail(
                    "legacy_question_content_conflict",
                    "legacy quiz content changed after its canonical version was frozen",
                )
            version_number = latest.version_number + 1
        else:
            version_number = 1
        version = DBAssessmentQuestionVersion(
            question_id=question.id,
            version_number=version_number,
            content_hash=content_hash,
            created_by_public_id=owner_public_id,
            **version_payload,
        )
        session.add(version)
        session.flush()
        question.current_version_id = version.id
        session.flush()

    return {
        "question": question,
        "version": version,
        "question_created": question_created,
        "version_created": version_created,
    }


def record_legacy_quiz_attempt(
    session: Any, *, owner_public_id: str, quiz_record: DBQuizRecord,
    attempt_number: int, student_answer: str, score: float,
    confidence: float | None, duration_seconds: int | None,
) -> dict[str, Any]:
    """Trusted server-only bridge from a graded legacy quiz into canonical assessment."""
    if not isinstance(quiz_record, DBQuizRecord) or not quiz_record.id:
        _fail("legacy_quiz_invalid", "legacy quiz record is required")
    if attempt_number < 1:
        _fail("legacy_attempt_number_invalid", "legacy attempt number must be positive")
    if not 0.0 <= float(score) <= 1.0:
        _fail("legacy_score_invalid", "trusted legacy score must be between zero and one")
    if confidence is not None and not 0.0 <= float(confidence) <= 1.0:
        _fail("legacy_confidence_invalid", "legacy confidence must be between zero and one")
    if duration_seconds is not None and int(duration_seconds) < 0:
        _fail("legacy_duration_invalid", "legacy duration cannot be negative")
    prepared = ensure_legacy_quiz_question_version(
        session,
        owner_public_id=owner_public_id,
        quiz_record=quiz_record,
    )
    question = prepared["question"]
    version = prepared["version"]
    question_type = question.question_type

    idempotency_key = f"legacy-quiz-attempt:{quiz_record.id}:{attempt_number}"
    answer = (
        {"choice": _legacy_choice(student_answer)}
        if question_type == "single_choice"
        else {"text": str(student_answer)}
    )
    payload = {
        "question_version_id": version.id,
        "idempotency_key": idempotency_key,
        "course_id": question.course_id,
        "mode": "practice",
        "answer": answer,
        "score": float(score),
        "correct": float(score) >= 0.6,
        "confidence": None if confidence is None else float(confidence),
        "duration_seconds": None if duration_seconds is None else int(duration_seconds),
        "grading_status": "graded",
        "feedback_policy": "immediate",
    }
    attempt = session.query(DBAssessmentAttempt).filter_by(
        owner_public_id=owner_public_id, idempotency_key=idempotency_key,
    ).first()
    attempt_created = attempt is None
    if attempt is not None:
        comparable = {
            "question_version_id": attempt.question_version_id,
            "idempotency_key": attempt.idempotency_key,
            "course_id": attempt.course_id,
            "mode": attempt.mode,
            "answer": attempt.answer,
            "score": attempt.score,
            "correct": attempt.correct,
            "confidence": attempt.confidence,
            "duration_seconds": attempt.duration_seconds,
            "grading_status": attempt.grading_status,
            "feedback_policy": attempt.feedback_policy,
        }
        if _canonical(comparable) != _canonical(payload):
            _fail("attempt_idempotency_conflict", "idempotency key is bound to another attempt")
    else:
        attempt = DBAssessmentAttempt(owner_public_id=owner_public_id, **payload)
        session.add(attempt)
        session.flush()

    return {
        "question_id": question.id,
        "question_version_id": version.id,
        "attempt_id": attempt.id,
        "question_created": prepared["question_created"],
        "version_created": prepared["version_created"],
        "attempt_created": attempt_created,
        "content_hash": version.content_hash,
    }


def learner_attempt_payload(
    attempt: DBAssessmentAttempt,
    grading: DBAssessmentGradingResult | None = None,
) -> dict[str, Any]:
    payload = {
        "id": attempt.id, "question_version_id": attempt.question_version_id,
        "course_id": attempt.course_id, "mode": attempt.mode,
        "answer": attempt.answer, "score": attempt.score, "correct": attempt.correct,
        "confidence": attempt.confidence, "duration_seconds": attempt.duration_seconds,
        "grading_status": attempt.grading_status, "feedback_policy": attempt.feedback_policy,
        "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
    }
    if attempt.feedback_policy == "after_close":
        payload["score"] = None
        payload["correct"] = None
    if grading is not None and attempt.feedback_policy != "after_close":
        payload.update({
            "score": grading.score,
            "correct": grading.correct,
            "grading_status": "graded" if grading.status == "completed" else grading.status,
            "grading": grading_result_payload(grading),
        })
    return payload


def propose_misconception(
    session: Any, *, owner_public_id: str, attempt_id: str,
    candidate: MisconceptionCandidateInput,
) -> DBMisconceptionReview:
    attempt = session.query(DBAssessmentAttempt).filter_by(id=attempt_id).first()
    if attempt is None:
        _fail("attempt_unknown", "assessment attempt does not exist")
    if attempt.owner_public_id != owner_public_id:
        _fail("attempt_forbidden", "assessment attempt belongs to another owner")
    existing = session.query(DBMisconceptionReview).filter_by(attempt_id=attempt_id).first()
    if existing is not None:
        _fail("misconception_already_proposed", "attempt already has a misconception candidate")
    row = DBMisconceptionReview(
        owner_public_id=owner_public_id, attempt_id=attempt_id,
        candidate_category=candidate.category, candidate_rationale=candidate.rationale,
        evidence=candidate.evidence, model_confidence=candidate.model_confidence,
    )
    session.add(row)
    session.flush()
    return row


def ensure_legacy_misconception_candidate(
    session: Any, *, owner_public_id: str, attempt_id: str,
    category: str, rationale: str, evidence: dict[str, Any],
    model_confidence: float | None,
) -> tuple[DBMisconceptionReview, bool]:
    """Idempotently project a trusted legacy grading diagnosis for learner review."""
    existing = session.query(DBMisconceptionReview).filter_by(attempt_id=attempt_id).first()
    if existing is not None:
        if existing.owner_public_id != owner_public_id:
            _fail("misconception_forbidden", "misconception review belongs to another owner")
        return existing, False
    allowed = {
        "knowledge_gap", "concept_confusion", "strategy_error", "calculation_error",
        "careless", "programming_error", "insufficient_evidence",
    }
    normalized_category = category if category in allowed else "insufficient_evidence"
    row = propose_misconception(
        session, owner_public_id=owner_public_id, attempt_id=attempt_id,
        candidate=MisconceptionCandidateInput(
            category=normalized_category,
            rationale=rationale[:4000], evidence=evidence,
            model_confidence=model_confidence,
        ),
    )
    return row, True


def schedule_delayed_retest(
    session: Any, *, review: DBMisconceptionReview, minimum_delay_hours: int = 24,
) -> tuple[DBAssessmentRetestTask, bool]:
    if review.status not in {"accepted", "modified", "teacher_confirmed"}:
        _fail("misconception_unconfirmed", "retest requires a confirmed misconception")
    existing = session.query(DBAssessmentRetestTask).filter_by(
        misconception_review_id=review.id,
    ).first()
    if existing is not None:
        return existing, False
    attempt = session.query(DBAssessmentAttempt).filter_by(id=review.attempt_id).one()
    decided_at = review.decided_at or datetime.now(timezone.utc).replace(tzinfo=None)
    row = DBAssessmentRetestTask(
        owner_public_id=review.owner_public_id,
        misconception_review_id=review.id,
        source_attempt_id=attempt.id,
        question_version_id=attempt.question_version_id,
        course_id=attempt.course_id,
        due_at=decided_at + timedelta(hours=max(24, int(minimum_delay_hours))),
        status="scheduled",
    )
    session.add(row)
    session.flush()
    return row, True


def submit_delayed_retest(
    session: Any, *, owner_public_id: str, task_id: str,
    submission: RetestAttemptInput, now: datetime | None = None,
) -> tuple[DBAssessmentRetestTask, DBAssessmentAttempt, bool]:
    task = session.query(DBAssessmentRetestTask).filter_by(id=task_id).first()
    if task is None:
        _fail("retest_task_unknown", "delayed retest task does not exist")
    if task.owner_public_id != owner_public_id:
        _fail("retest_task_forbidden", "delayed retest task belongs to another owner")
    current = now or datetime.now(timezone.utc).replace(tzinfo=None)
    if current < task.due_at:
        _fail("retest_not_due", "delayed retest cannot be submitted before its due time")
    full_idempotency_key = f"retest:{task.id}:{submission.idempotency_key}"
    existing = session.query(DBAssessmentAttempt).filter_by(
        owner_public_id=owner_public_id, idempotency_key=full_idempotency_key,
    ).first()
    if existing is not None:
        attempt, _ = record_attempt(
            session, owner_public_id=owner_public_id,
            attempt=AttemptInput(
                question_version_id=task.question_version_id,
                idempotency_key=full_idempotency_key,
                mode="retest", answer=submission.answer,
                confidence=submission.confidence,
                duration_seconds=submission.duration_seconds,
            ),
        )
        return task, attempt, False
    if task.status in {"completed", "cancelled"}:
        _fail("retest_already_closed", "delayed retest task is already closed")
    attempt, created = record_attempt(
        session, owner_public_id=owner_public_id,
        attempt=AttemptInput(
            question_version_id=task.question_version_id,
            idempotency_key=full_idempotency_key,
            mode="retest", answer=submission.answer,
            confidence=submission.confidence,
            duration_seconds=submission.duration_seconds,
        ),
    )
    if attempt.grading_status == "graded" and attempt.correct is True:
        task.status = "completed"
        task.completion_attempt_id = attempt.id
        task.completed_at = current
    elif task.status == "scheduled":
        task.status = "due"
    session.flush()
    return task, attempt, created


def retest_task_payload(task: DBAssessmentRetestTask | None) -> dict[str, Any] | None:
    if task is None:
        return None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    status = "due" if task.status == "scheduled" and task.due_at <= now else task.status
    return {
        "id": task.id,
        "status": status,
        "question_version_id": task.question_version_id,
        "source_attempt_id": task.source_attempt_id,
        "course_id": task.course_id,
        "due_at": f"{task.due_at.isoformat()}Z" if task.due_at else None,
        "completion_attempt_id": task.completion_attempt_id,
        "stable_mastery": task.status == "completed",
    }


def legacy_quiz_diagnosis_payload(
    session: Any, *, owner_public_id: str, quiz_id: str,
) -> dict[str, Any] | None:
    prefix = f"legacy-quiz-attempt:{quiz_id}:"
    attempt = session.query(DBAssessmentAttempt).filter(
        DBAssessmentAttempt.owner_public_id == owner_public_id,
        DBAssessmentAttempt.idempotency_key.like(f"{prefix}%"),
    ).order_by(DBAssessmentAttempt.submitted_at.desc(), DBAssessmentAttempt.id.desc()).first()
    if attempt is None:
        return None
    review = session.query(DBMisconceptionReview).filter_by(attempt_id=attempt.id).first()
    if review is None:
        return {"attempt_id": attempt.id, "review": None, "retest_task": None}
    task = session.query(DBAssessmentRetestTask).filter_by(misconception_review_id=review.id).first()
    return {
        "attempt_id": attempt.id,
        "review": {
            "id": review.id,
            "status": review.status,
            "candidate_category": review.candidate_category,
            "candidate_rationale": review.candidate_rationale,
            "model_confidence": review.model_confidence,
            "confirmed_category": review.confirmed_category,
            "decision_note": review.decision_note,
        },
        "retest_task": retest_task_payload(task),
    }


def decide_misconception(
    session: Any, *, owner_public_id: str, review_id: str,
    decision: MisconceptionDecisionInput,
) -> DBMisconceptionReview:
    row = session.query(DBMisconceptionReview).filter_by(id=review_id).first()
    if row is None:
        _fail("misconception_unknown", "misconception review does not exist")
    if row.owner_public_id != owner_public_id:
        _fail("misconception_forbidden", "misconception review belongs to another owner")
    if row.status != "proposed":
        existing_decision = {
            "accepted": "accept", "modified": "modify", "rejected": "reject",
        }.get(row.status)
        existing_category = row.confirmed_category if existing_decision == "modify" else ""
        requested_category = decision.category if decision.decision == "modify" else ""
        if (
            existing_decision == decision.decision
            and existing_category == requested_category
            and row.decision_note == decision.note
        ):
            return row
        _fail("misconception_already_decided", "misconception review already has a different decision")
    row.status = {"accept": "accepted", "modify": "modified", "reject": "rejected"}[decision.decision]
    row.confirmed_category = (
        row.candidate_category if decision.decision == "accept"
        else decision.category if decision.decision == "modify" else ""
    )
    row.decision_note = decision.note
    row.decided_by_public_id = owner_public_id
    row.decided_at = datetime.now(timezone.utc).replace(tzinfo=None)
    record_audit(
        session,
        actor_public_id=owner_public_id,
        action="assessment.misconception.decide",
        object_type="misconception_review",
        object_id=row.id,
        metadata={
            "decision": decision.decision,
            "category_changed": decision.decision == "modify",
            "rationale_included": False,
            "evidence_included": False,
        },
    )
    session.flush()
    return row


def misconception_review_payload(review: DBMisconceptionReview | None) -> dict[str, Any] | None:
    if review is None:
        return None
    return {
        "id": review.id,
        "attempt_id": review.attempt_id,
        "status": review.status,
        "candidate_category": review.candidate_category,
        "candidate_rationale": review.candidate_rationale,
        "candidate_evidence": review.evidence or {},
        "model_confidence": review.model_confidence,
        "confirmed_category": review.confirmed_category,
        "decision_note": review.decision_note,
        "decided_at": f"{review.decided_at.isoformat()}Z" if review.decided_at else None,
    }


def project_misconception_decision(
    session: Any, *, review: DBMisconceptionReview, decision: MisconceptionDecisionInput,
) -> dict[str, Any]:
    attempt = session.query(DBAssessmentAttempt).filter_by(id=review.attempt_id).one()
    user = session.query(DBUser).filter_by(public_id=review.owner_public_id).one()
    category = review.confirmed_category or review.candidate_category
    event, event_created = record_learning_event(
        session,
        owner_public_id=review.owner_public_id,
        user=user,
        trusted_source=False,
        event=LearningEventInput(
            idempotency_key=f"misconception-decision:{review.id}",
            event_type="misconception_decided",
            course_id=attempt.course_id,
            object_type="assessment_question_version",
            object_id=attempt.question_version_id,
            source="frontend",
            occurred_at=(review.decided_at or datetime.now(timezone.utc).replace(tzinfo=None)).replace(tzinfo=timezone.utc),
            payload={
                "attempt_id": attempt.id,
                "review_id": review.id,
                "decision": decision.decision,
                "candidate_category": review.candidate_category,
                "confirmed_category": review.confirmed_category,
                "evidence_kind": "user_statement",
                "evidence_strength": "user_declared",
                "candidate_origin": "system_candidate",
                "mastery_changed": False,
            },
        ),
    )
    path_consumption = process_path_event(session, event=event)

    evidence_key = f"misconception-decision:{review.id}"
    evidence = session.query(DBProfileEvidence).filter_by(
        legacy_student_id=user.username, legacy_key=evidence_key,
    ).first()
    if evidence is None:
        evidence = DBProfileEvidence(
            owner_public_id=review.owner_public_id,
            legacy_student_id=user.username,
            legacy_key=evidence_key,
            source_type="misconception_user_statement",
            source_object_id=event.id,
            features=[
                f"decision:{decision.decision}", f"category:{category}",
                "evidence:user_statement", "mastery:unchanged",
            ],
            weight=0.75,
            confidence=1.0,
            evidence_summary=(
                f"Learner {decision.decision}ed misconception category {category}; "
                "this is a user statement and does not independently establish mastery."
            ),
            observed_at=event.occurred_at,
            status="active",
            evidence_version="r3.misconception-feedback.v1",
            trace_id=event.trace_id,
        )
        session.add(evidence)
        session.flush()

    profile_snapshot = None
    if review.status in {"accepted", "modified", "teacher_confirmed"}:
        profile_version = f"misconception-{review.id}-v1"
        profile_snapshot = session.query(DBProfileSnapshot).filter_by(
            owner_public_id=review.owner_public_id, profile_version=profile_version,
        ).first()
        if profile_snapshot is None:
            previous = session.query(DBProfileSnapshot).filter_by(
                owner_public_id=review.owner_public_id,
            ).order_by(DBProfileSnapshot.created_at.desc(), DBProfileSnapshot.id.desc()).first()
            snapshot = dict(previous.snapshot or {}) if previous else {}
            snapshot["misconception"] = {
                "category": category,
                "label": category.replace("_", " "),
                "review_id": review.id,
                "learning_event_id": event.id,
                "evidence_kind": "user_statement",
                "evidence_strength": "user_declared",
                "mastery_changed": False,
            }
            profile_snapshot = DBProfileSnapshot(
                owner_public_id=review.owner_public_id,
                legacy_student_id=user.username,
                profile_version=profile_version,
                snapshot=snapshot,
                content_hash=_hash(snapshot),
                trace_id=event.trace_id,
            )
            session.add(profile_snapshot)
            session.flush()

    return {
        "learning_event": {
            "id": event.id,
            "event_type": event.event_type,
            "created": event_created,
            "evidence_kind": "user_statement",
            "evidence_strength": "user_declared",
            "mastery_changed": False,
        },
        "profile_projection": {
            "evidence_id": evidence.id,
            "snapshot_id": profile_snapshot.id if profile_snapshot else None,
            "updated": profile_snapshot is not None,
            "category": category if profile_snapshot else None,
        },
        "path_projection": {
            "consumption_id": path_consumption.id,
            "status": path_consumption.status,
            "result": path_consumption.result or {},
        },
        "teacher_evidence": {
            "learning_event_id": event.id,
            "learner_public_id": review.owner_public_id,
            "course_id": attempt.course_id,
            "evidence_kind": "user_statement",
            "decision": decision.decision,
            "category": category,
        },
    }


def review_queue(session: Any, *, owner_public_id: str) -> tuple[dict[str, Any], ...]:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = session.query(DBMisconceptionReview, DBAssessmentAttempt, DBAssessmentRetestTask).join(
        DBAssessmentAttempt, DBAssessmentAttempt.id == DBMisconceptionReview.attempt_id,
    ).outerjoin(
        DBAssessmentRetestTask, DBAssessmentRetestTask.misconception_review_id == DBMisconceptionReview.id,
    ).filter(
        DBMisconceptionReview.owner_public_id == owner_public_id,
        DBMisconceptionReview.status.in_(("accepted", "modified", "teacher_confirmed")),
        (
            DBAssessmentRetestTask.id.is_(None)
            | DBAssessmentRetestTask.status.in_(("scheduled", "due"))
        ),
    ).order_by(DBAssessmentAttempt.submitted_at, DBMisconceptionReview.id).all()
    items = [{
        "source_type": "misconception_review",
        "source_id": review.id,
        "attempt_id": attempt.id,
        "course_id": attempt.course_id,
        "category": review.confirmed_category,
        "concept": review.confirmed_category,
        "reason": "confirmed misconception requires review and delayed retest",
        "stable_mastery": False,
        "due_at": f"{task.due_at.isoformat()}Z" if task and task.due_at else attempt.submitted_at.isoformat() if attempt.submitted_at else None,
        "retest_task": retest_task_payload(task),
        "priority": 0.5,
        "status": retest_task_payload(task)["status"] if task else "needs_review",
        "evidence_strength": "user_declared" if review.status in ("accepted", "modified") else "teacher_confirmed",
        "next_action": "complete_delayed_retest" if task else "review_diagnosis_material",
    } for review, attempt, task in rows]
    user = session.query(DBUser).filter_by(public_id=owner_public_id).first()
    if user is not None:
        plans = session.query(DBReviewPlan).filter_by(student_id=user.username).order_by(
            DBReviewPlan.next_review_at, DBReviewPlan.priority, DBReviewPlan.id,
        ).all()
        items.extend({
            "source_type": "sm2_review_plan",
            "source_id": str(plan.id),
            "attempt_id": None,
            "course_id": None,
            "category": "spaced_repetition",
            "concept": plan.concept,
            "reason": "SM-2 due date and legacy review priority",
            "stable_mastery": False,
            "due_at": plan.next_review_at.isoformat() if plan.next_review_at else None,
            "priority": float(plan.priority or 1.0),
            "status": "due" if plan.next_review_at and plan.next_review_at <= now else "scheduled",
            "evidence_strength": "algorithmic_schedule",
            "next_action": "rate_review_quality",
        } for plan in plans)
    items.sort(key=lambda item: (item["due_at"] or "9999", item["priority"], item["source_type"], item["source_id"]))
    return tuple(items)
