"""Profile- and source-bound entry-diagnostic generation."""

from __future__ import annotations

from app.source_refs import current_chapter_clause, current_source_clause, current_structure_ref_clause

import asyncio
import hashlib
import json
import random
import re
from collections import Counter
from copy import copy
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Annotated, Any, Literal, Union

from pydantic import Field
from sqlalchemy.orm import Session

from app.authorization import active_course_role
from app.database import (
    DBAssessmentQuestion,
    DBAssessmentQuestionVersion,
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
    DBDiagnosticBlueprint,
    DBKnowledgePoint,
    DBProfileSnapshot,
    DBSourceDocument,
    DBSourceRef,
    DBTaskEvent,
    DBUser,
)
from app.m5_assessment_core import (
    AssessmentCoreError,
    QuestionVersionInput,
    create_question_version,
    learner_option_texts,
    learner_question_content_issue,
    learner_safe_prompt,
    validate_question_version,
)
from app.m2_contracts import StrictModel
from app.m5_capabilities import Capability, M5CapabilityError, OutputConstraints
from app.m5_gateway import execute_registered_structured_call
from app.source_refs import source_ref_teaching_text


class DiagnosticGenerationError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _diagnostic_service_failure(exc: BaseException, *, reviewing: bool) -> DiagnosticGenerationError | None:
    """Keep provider availability separate from a judgment about the questions."""
    import httpx
    from concurrency import CircuitBreakerOpenError

    current = exc
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (httpx.TransportError, TimeoutError, CircuitBreakerOpenError)):
            step = "题目核对" if reviewing else "诊断题准备"
            return DiagnosticGenerationError(
                "diagnostic_service_unavailable",
                f"{step}时连接中断，尚未完成。请稍后重试。", status_code=503,
            )
        if isinstance(current, httpx.HTTPStatusError):
            status = current.response.status_code
            if status in {401, 402, 403}:
                return DiagnosticGenerationError(
                    "diagnostic_service_auth_failed",
                    "暂时无法使用出题服务，请管理员检查连接配置后重试。", status_code=503,
                )
            if status == 429 or status >= 500:
                return DiagnosticGenerationError(
                    "diagnostic_service_unavailable",
                    "出题服务暂时繁忙，诊断准备尚未完成。请稍后重试。", status_code=503,
                )
        current = current.__cause__
    return None


@dataclass(frozen=True)
class DiagnosticBlueprintRequest:
    course_id: str
    idempotency_key: str
    question_count: int = 15
    self_rating: str | None = None
    stage_id: str | None = None


DIAGNOSTIC_KINDS = ("theory", "application", "engineering_judgment")
DIAGNOSTIC_COUNTS = (15, 20, 25)
DIAGNOSTIC_QUESTION_TYPES = ("true_false", "single_choice", "short_answer")
SELF_RATING_VALUES = ("foundation", "advanced", "mastered")
SELF_RATING_LABELS = {
    "foundation": "基础",
    "advanced": "进阶",
    "mastered": "完全掌握",
}


class DiagnosticRubricCriterion(StrictModel):
    id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=200)
    weight: float = Field(gt=0, le=1)


class DiagnosticQuestionBase(StrictModel):
    item_id: str = Field(min_length=2, max_length=32)
    prompt: str = Field(min_length=8)
    primary_knowledge_point_id: str = Field(min_length=3, max_length=128)
    source_ref_id: str = Field(min_length=3, max_length=128)
    diagnostic_dimension: Literal["theory", "application", "engineering_judgment"]
    bloom_level: Literal["remember", "understand", "apply", "analyze", "evaluate"]
    difficulty: float = Field(ge=0, le=1)
    explanation: str = Field(min_length=8)


class DiagnosticTrueFalseQuestion(DiagnosticQuestionBase):
    question_type: Literal["true_false"]
    answer: bool


class DiagnosticChoiceQuestion(DiagnosticQuestionBase):
    question_type: Literal["single_choice"]
    options: tuple[str, ...] = Field(min_length=4, max_length=4)
    answer: Literal["A", "B", "C", "D"]


class DiagnosticShortAnswerQuestion(DiagnosticQuestionBase):
    question_type: Literal["short_answer"]
    reference_answer: str = Field(min_length=8)
    rubric: tuple[DiagnosticRubricCriterion, ...] = Field(min_length=1, max_length=8)


DiagnosticGeneratedQuestion = Annotated[
    Union[
        DiagnosticTrueFalseQuestion,
        DiagnosticChoiceQuestion,
        DiagnosticShortAnswerQuestion,
    ],
    Field(discriminator="question_type"),
]


class DiagnosticCoveragePlanItem(StrictModel):
    knowledge_point_id: str = Field(min_length=3, max_length=128)
    question_count: int = Field(ge=1, le=25)
    rationale: str = Field(min_length=2, max_length=500)


class DiagnosticGeneratedSet(StrictModel):
    profile_adaptation_summary: str = Field(min_length=4, max_length=1000)
    coverage_plan: tuple[DiagnosticCoveragePlanItem, ...] = Field(min_length=1, max_length=25)
    questions: tuple[DiagnosticGeneratedQuestion, ...] = Field(min_length=15, max_length=25)


class DiagnosticQuestionRevision(StrictModel):
    questions: tuple[DiagnosticGeneratedQuestion, ...] = Field(min_length=1, max_length=25)


class DiagnosticQuestionReview(StrictModel):
    item_id: str = Field(min_length=2, max_length=32)
    verdict: Literal["approved", "rejected"]
    source_support: Literal["supported", "unsupported"]
    answer_consistency: Literal["consistent", "inconsistent"]
    profile_fit: Literal["fit", "unfit"]
    knowledge_alignment: Literal["aligned", "misaligned"]
    question_clarity: Literal["self_contained", "missing_context"]
    public_note: str = Field(min_length=2, max_length=500)


class DiagnosticReviewBundle(StrictModel):
    status: Literal["approved", "rejected"]
    decision_summary: str = Field(min_length=4)
    items: tuple[DiagnosticQuestionReview, ...] = Field(min_length=1)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _saved_diagnostic_work(session: Any, task_id: str | None, work_key: str) -> list[dict]:
    if not task_id:
        return []
    with Session(bind=session.get_bind()) as state:
        return [dict(event.payload) for event in state.query(DBTaskEvent).filter_by(
            task_id=task_id, event_type="diagnostic.work_saved",
        ).order_by(DBTaskEvent.sequence) if event.payload.get("workKey") == work_key]


def _save_diagnostic_work(session: Any, scope: dict, **payload: Any) -> None:
    if not scope.get("_taskId"):
        return
    from app.m1_repository import append_task_event
    # Store only public questions/review decisions and their call identities.
    # Keep these outside the publication transaction so interruption or rollback
    # cannot discard an already completed model call.
    with Session(bind=session.get_bind()) as state:
        from app.learning_generation_jobs import assert_generation_owner
        assert_generation_owner(state)
        append_task_event(state, task_id=scope["_taskId"], event_type="diagnostic.work_saved",
                          payload={"workKey": scope["_workKey"], **payload})
        state.commit()


def _readable_course(session: Any, *, course_id: str, user: DBUser) -> DBCourse:
    course = session.get(DBCourse, course_id)
    if course is None:
        raise DiagnosticGenerationError("course_unknown", "课程不存在。", status_code=404)
    if course.status in {"withdrawn", "archived"}:
        raise DiagnosticGenerationError("course_unavailable", "这门课程当前不可用于入学诊断。", status_code=403)
    from course_catalog import course_is_selectable
    if not course_is_selectable(session, course):
        raise DiagnosticGenerationError("course_unavailable", "这门课程当前没有可用学习资料。", status_code=403)
    if course.visibility == "public" or course.owner_public_id == user.public_id or user.role == "admin":
        return course
    if active_course_role(session, course_id=course_id, user_public_id=user.public_id):
        return course
    raise DiagnosticGenerationError("course_forbidden", "你没有访问这门课程的权限。", status_code=403)


def diagnostic_course_catalog(session: Any, *, user: DBUser) -> dict[str, Any]:
    """Return only courses the learner can actually use for a new diagnosis."""
    from course_catalog import MASTER_COURSE_ID, course_is_selectable

    items = []
    for course in session.query(DBCourse).order_by(DBCourse.title, DBCourse.id).all():
        if not course_is_selectable(session, course):
            continue
        if not (
            course.visibility == "public"
            or user.role == "admin"
            or active_course_role(session, course_id=course.id, user_public_id=user.public_id)
        ):
            continue
        ready_sources = session.query(DBSourceDocument).filter_by(
            course_id=course.id,
            processing_status="ready",
        ).count()
        items.append({
            "id": course.id,
            "title": course.title,
            "subject": course.subject,
            "description": course.description,
            "version": course.version,
            "manifestVersion": course.manifest_version,
            "status": course.status,
            "sourceSummary": {"readyDocuments": ready_sources},
        })
    items.sort(key=lambda item: (0 if item["id"] == MASTER_COURSE_ID else 1, item["title"], item["id"]))
    return {
        "schemaVersion": "p1-b08.diagnostic-course-catalog.v1",
        "courses": items,
        "selfRatingOptions": [
            {"value": value, "label": SELF_RATING_LABELS[value]}
            for value in SELF_RATING_VALUES
        ],
    }


def _latest_profile(
    session: Any,
    owner_public_id: str,
    course_id: str | None = None,
) -> DBProfileSnapshot | None:
    query = (
        session.query(DBProfileSnapshot)
        .filter_by(owner_public_id=owner_public_id)
        .order_by(DBProfileSnapshot.created_at.desc(), DBProfileSnapshot.id.desc())
    )
    profiles = query.all()
    if course_id:
        for profile in profiles:
            snapshot = dict(profile.snapshot or {})
            if (snapshot.get("course_id") or (snapshot.get("course_context") or {}).get("courseId")) == course_id:
                return profile
        # A different course's measured mastery is not this course's prior.
        profiles = [profile for profile in profiles if not (
            (profile.snapshot or {}).get("course_id")
            or ((profile.snapshot or {}).get("course_context") or {}).get("courseId")
        )]
    return profiles[0] if profiles else None


def _target_difficulty(profile: DBProfileSnapshot | None, self_rating: str | None = None) -> float:
    snapshot = dict(profile.snapshot or {}) if profile else {}
    mastery = snapshot.get("mastery")
    if isinstance(mastery, (int, float)):
        profile_target = max(0.2, min(0.75, 0.25 + float(mastery) * 0.45))
    else:
        fields = snapshot.get("fields") or snapshot.get("confirmedFields") or {}
        foundation = str(fields.get("foundation") or snapshot.get("foundation") or "").lower()
        if any(token in foundation for token in ("进阶", "熟悉", "advanced", "较好")):
            profile_target = 0.62
        elif any(token in foundation for token in ("零基础", "入门", "beginner", "薄弱")):
            profile_target = 0.32
        else:
            profile_target = 0.48
    if self_rating is None:
        return profile_target
    rating_target = {"foundation": 0.30, "advanced": 0.58, "mastered": 0.78}.get(self_rating)
    if rating_target is None:
        raise DiagnosticGenerationError("diagnostic_self_rating_invalid", "自评起点不受支持。", status_code=422)
    return round((profile_target * 0.55) + (rating_target * 0.45), 3)


def _question_kind(version: DBAssessmentQuestionVersion) -> str:
    explicit = str((version.scoring_rule or {}).get("diagnostic_dimension") or "")
    if explicit in DIAGNOSTIC_KINDS:
        return explicit
    level = str(version.bloom_level or "understand")
    if level in {"remember", "understand"}:
        return "theory"
    if level == "apply":
        return "application"
    return "engineering_judgment"


def _question_count(value: int) -> int:
    count = int(value)
    if count not in DIAGNOSTIC_COUNTS:
        raise DiagnosticGenerationError(
            "diagnostic_question_count_invalid",
            "入学诊断题量只能选择 15、20 或 25 道。",
            status_code=422,
        )
    return count


def _coverage_question_count(requested_count: int, eligible_point_count: int) -> int:
    """Choose the smallest supported paper size that covers the course scope."""
    requested = _question_count(requested_count)
    for supported in DIAGNOSTIC_COUNTS:
        if supported >= requested and supported >= eligible_point_count:
            return supported
    return requested


def _question_type_quotas(count: int) -> dict[str, int]:
    base, remainder = divmod(_question_count(count), len(DIAGNOSTIC_QUESTION_TYPES))
    return {
        question_type: base + (1 if index < remainder else 0)
        for index, question_type in enumerate(DIAGNOSTIC_QUESTION_TYPES)
    }


def _require_model_policy(llm: Any) -> None:
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
        raise DiagnosticGenerationError(
            "diagnostic_model_policy_invalid",
            "入学诊断必须使用 deepseek-v4-flash、thinking enabled、reasoning max，且不允许回退模型。",
            status_code=503,
        )


def _profile_weak_text(profile: DBProfileSnapshot) -> str:
    snapshot = dict(profile.snapshot or {})
    return _canonical({
        "weak_points": snapshot.get("weak_points"),
        "concept_mastery": snapshot.get("concept_mastery"),
        "profile_projection": snapshot.get("profile_projection"),
    }).lower()


def _generation_scope(
    session: Any,
    *,
    course: DBCourse,
    profile: DBProfileSnapshot,
    question_count: int,
    self_rating: str | None = None,
    stage_id: str | None = None,
) -> dict[str, Any]:
    chapters = {
        row.id: row
        for row in session.query(DBChapter)
        .filter_by(course_id=course.id).filter(current_chapter_clause())
        .order_by(DBChapter.position, DBChapter.id)
        .all()
    }
    links = session.query(DBChapterKnowledgePoint).filter(
        DBChapterKnowledgePoint.chapter_id.in_(list(chapters) or ["-"]),
    ).all()
    point_ids = {row.knowledge_point_id for row in links}
    points = {
        row.id: row
        for row in session.query(DBKnowledgePoint).filter(
            DBKnowledgePoint.id.in_(list(point_ids) or ["-"]),
            DBKnowledgePoint.status == "active",
        ).all()
    }
    points_by_chapter: dict[str, set[str]] = {}
    for link in links:
        if link.knowledge_point_id in points:
            points_by_chapter.setdefault(link.chapter_id, set()).add(link.knowledge_point_id)

    documents = {
        row.id: row
        for row in session.query(DBSourceDocument).filter_by(
            course_id=course.id,
            processing_status="ready",
        ).filter(current_source_clause()).all()
    }
    sources = []
    point_source_ids: dict[str, set[str]] = {point_id: set() for point_id in points}
    for ref in session.query(DBSourceRef).filter(
        DBSourceRef.source_document_id.in_(list(documents) or ["-"]),
        current_structure_ref_clause(),
    ).order_by(DBSourceRef.chapter_id, DBSourceRef.page_number, DBSourceRef.id).all():
        chapter = chapters.get(ref.chapter_id)
        supported_points = sorted(points_by_chapter.get(ref.chapter_id, set()))
        quote = source_ref_teaching_text(session, ref, max_chars=max(12000, (ref.char_end or 0) - (ref.char_start or 0)))
        if chapter is None or not supported_points or not ref.content_hash or not quote:
            continue
        document = documents[ref.source_document_id]
        sources.append({
            "sourceRefId": ref.id,
            "sourceDocumentId": document.id,
            "title": document.title,
            "filename": document.filename,
            "location": ref.location_label or (f"第 {ref.page_number} 页" if ref.page_number else chapter.title),
            "contentHash": ref.content_hash,
            "documentContentHash": document.content_hash,
            "chapterId": chapter.id,
            "chapterTitle": chapter.title,
            "knowledgePointIds": supported_points,
            "quote": quote,
        })
        for point_id in supported_points:
            point_source_ids[point_id].add(ref.id)

    from app.diagnostic_scope import course_diagnostic_scope
    assessment_scope = course_diagnostic_scope(course, list(points.values()), profile,
                                               question_count=question_count, stage_id=stage_id)
    stage_points = (assessment_scope.get("selected") or {}).get("knowledgePointIds", [])
    eligible_points = [points[key] for key in stage_points]
    weak_text = _profile_weak_text(profile)
    level_order = {
        "foundation": {"foundation": 0, "basic": 0, "core": 1, "advanced": 2, "stretch": 3},
        "advanced": {"advanced": 0, "core": 1, "foundation": 1, "basic": 1, "stretch": 2},
        "mastered": {"stretch": 0, "advanced": 1, "core": 2, "foundation": 2, "basic": 2},
    }.get(self_rating or "", {})
    eligible_points.sort(key=lambda row: (
        0 if row.id.lower() in weak_text or row.title.lower() in weak_text else 1,
        level_order.get(str(row.level).lower(), 1),
        row.title,
        row.id,
    ))
    coverage_gap = eligible_points[question_count:]
    selected_points = eligible_points[:question_count] if coverage_gap else eligible_points
    remaining_questions = max(0, question_count - len(selected_points))
    cross_evidence_point_ids = [
        point.id for point in selected_points[:remaining_questions]
    ]
    selected_ids = {row.id for row in selected_points}
    selected_sources = [
        source for source in sources
        if selected_ids.intersection(source["knowledgePointIds"])
    ]
    # Allocate evidence per concept, not per book. A book shared by twenty
    # concepts must not spend its whole allowance on the first few concepts.
    # Retrieval is over every verified passage; the model sees selected
    # teaching evidence within its request context, not a truncated book prefix.
    from app.canonical_retrieval import teaching_excerpt, teaching_sections, _lexical_overlap
    point_specs = {item['code']: item for item in (course.manifest_data or {}).get('knowledge_points', [])}
    per_point = max(1, 120000 // max(1, len(selected_points)))
    selected_by_ref: dict[str, dict[str, Any]] = {}
    point_source_ids = {point.id: set() for point in selected_points}
    for point in selected_points:
        candidates = []
        selectors = point_specs.get(point.code, {}).get('teaching_sources', [])
        phrases = [part.strip() for part in re.split(r"[、，,与]", point.title) if len(part.strip()) > 2]
        for source in selected_sources:
            if point.id not in source["knowledgePointIds"]:
                continue
            matching = [item for item in selectors if item.get('filename') == source.get('filename')]
            section_text = teaching_sections(source['quote'], [heading for item in matching for heading in item.get('headings', [])]) if matching else ''
            excerpt = teaching_excerpt(section_text or source["quote"], topics=[point.title],
                                       max_chars=per_point, prefer_explanations=True)
            if not excerpt.strip():
                continue
            relevance = _lexical_overlap(point.title, excerpt)
            phrase_hits = sum(phrase.lower() in excerpt.lower() for phrase in phrases)
            title_relevance = _lexical_overlap(point.title, source["title"] + " " + source["chapterTitle"])
            candidates.append(((bool(section_text), phrase_hits, title_relevance, relevance, min(len(excerpt), per_point)), source, excerpt))
        candidates.sort(key=lambda item: item[0], reverse=True)
        # Each diagnostic item has one source binding. Give its strongest
        # concept passage the available space instead of offering a weaker
        # book introduction as an interchangeable source. Course learning
        # still has all linked documents available.
        chosen = candidates[:1]
        allowance = per_point // max(1, len(chosen))
        for _, source, excerpt in chosen:
            ref_id = source["sourceRefId"]
            target = selected_by_ref.setdefault(ref_id, {**source, "knowledgePointIds": [], "knowledgePointQuotes": {}})
            target["knowledgePointIds"].append(point.id)
            target["knowledgePointQuotes"][point.id] = excerpt
            point_source_ids[point.id].add(ref_id)
    selected_sources = list(selected_by_ref.values())
    for source in selected_sources:
        source["quote"] = "\n\n".join(dict.fromkeys(source["knowledgePointQuotes"].values()))
    return {
        "selfRating": self_rating,
        "assessmentScope": assessment_scope,
        "missingEvidencePointIds": [point.id for point in selected_points if not point_source_ids[point.id]],
        "targetDifficulty": round(_target_difficulty(profile, self_rating), 3),
        "coverageGap": [
            {"id": row.id, "title": row.title, "sourceRefIds": sorted({source["sourceRefId"] for source in sources if row.id in source["knowledgePointIds"]})}
            for row in coverage_gap
        ],
        "crossEvidencePointIds": cross_evidence_point_ids,
        "knowledgePoints": [
            {
                "id": row.id,
                "title": row.title,
                "level": row.level,
                "sourceRefIds": sorted(point_source_ids[row.id]),
                "minimumQuestionCount": 1,
                "crossEvidenceTarget": 2 if row.id in cross_evidence_point_ids else 1,
            }
            for row in selected_points
        ],
        "sources": selected_sources,
    }


def _question_version_input(question: DiagnosticGeneratedQuestion) -> QuestionVersionInput:
    if question.question_type == "true_false":
        options: tuple[str, ...] = ()
        answer_key = {"value": question.answer}
        scoring_rule = {
            "type": "exact",
            "version": "p1-b05-diagnostic-v1",
            "diagnostic_dimension": question.diagnostic_dimension,
        }
    elif question.question_type == "single_choice":
        options = tuple(question.options)
        answer_key = {"choice": question.answer}
        scoring_rule = {
            "type": "exact",
            "version": "p1-b05-diagnostic-v1",
            "diagnostic_dimension": question.diagnostic_dimension,
        }
    else:
        options = ()
        answer_key = {"reference_answer": question.reference_answer}
        scoring_rule = {
            "version": "p1-b05-diagnostic-rubric-v1",
            "diagnostic_dimension": question.diagnostic_dimension,
            "correct_threshold": 0.6,
            "criteria": [item.model_dump(mode="json") for item in question.rubric],
        }
    return QuestionVersionInput(
        prompt=question.prompt,
        options=options,
        answer_key=answer_key,
        scoring_rule=scoring_rule,
        explanation=question.explanation,
        misconception_tags=("entry-diagnostic", question.diagnostic_dimension),
        primary_knowledge_point_id=question.primary_knowledge_point_id,
        bloom_level=question.bloom_level,
        expert_difficulty=question.difficulty,
        source_ref_ids=(question.source_ref_id,),
    )


def _arrange_choice_options(generated: DiagnosticGeneratedSet, *, seed: str) -> DiagnosticGeneratedSet:
    """Arrange a new paper before review; saved papers and answers never move."""
    choices = [item for item in generated.questions if isinstance(item, DiagnosticChoiceQuestion)]
    rng = random.Random(seed)
    labels = list("ABCD")
    rng.shuffle(labels)
    targets = [labels[index % 4] for index in range(len(choices))]
    rng.shuffle(targets)
    arranged = {}
    for item, target in zip(choices, targets):
        correct = "ABCD".index(item.answer)
        options = [re.sub(r"^[A-D][.、:：)]\s*", "", text).strip() for text in item.options]
        distractors = sorted((index for index in range(4) if index != correct), key=lambda index: options[index])
        rng.shuffle(distractors)
        order = list(distractors)
        order.insert("ABCD".index(target), correct)
        mapping = {"ABCD"[old]: "ABCD"[new] for new, old in enumerate(order)}

        def remap(text: str) -> str:
            # Explicit option references only: e.g. matrix A must stay A.
            return re.sub(
                r"(?P<prefix>(?:选项|答案(?:为|是)?|正确选项(?:为|是)?|option|choice)\s*)(?P<before>[A-D])(?![A-Za-z0-9])"
                r"|(?P<after>[A-D])(?=\s*(?:选项|项(?:正确|错误|不|是|为)))"
                r"|(?P<line>^[A-D])(?=[.、:：]\s*)",
                lambda match: (match.group('prefix') or '') + mapping[
                    match.group('before') or match.group('after') or match.group('line')],
                text, flags=re.M,
            )

        arranged[item.item_id] = item.model_copy(update={
            "options": tuple(remap(options[index]) for index in order),
            "answer": target,
            "prompt": remap(item.prompt),
            "explanation": remap(item.explanation),
        })
    return generated.model_copy(update={
        "questions": tuple(arranged.get(item.item_id, item) for item in generated.questions),
    })


def _validate_generated_set(
    payload: dict[str, Any],
    *,
    count: int,
    quotas: dict[str, int],
    scope: dict[str, Any],
) -> DiagnosticGeneratedSet:
    generated = DiagnosticGeneratedSet.model_validate(payload)
    if len(generated.questions) != count:
        raise DiagnosticGenerationError(
            "diagnostic_generated_count_mismatch",
            f"模型返回 {len(generated.questions)} 道题，要求恰好 {count} 道。",
        )
    actual_types = Counter(item.question_type for item in generated.questions)
    if dict(actual_types) != quotas:
        raise DiagnosticGenerationError(
            "diagnostic_question_type_mismatch",
            f"题型配额不一致：要求 {quotas}，实际 {dict(actual_types)}。",
        )
    item_ids = [item.item_id for item in generated.questions]
    prompts = ["".join(item.prompt.lower().split()) for item in generated.questions]
    if len(set(item_ids)) != count or len(set(prompts)) != count:
        raise DiagnosticGenerationError("diagnostic_duplicate_question", "模型生成了重复题目。")
    allowed_points = {item["id"] for item in scope["knowledgePoints"]}
    allowed_sources = {item["sourceRefId"] for item in scope["sources"]}
    source_points = {
        item["sourceRefId"]: set(item["knowledgePointIds"])
        for item in scope["sources"]
    }
    dimensions = set()
    point_counts = Counter()
    for item in generated.questions:
        if item.primary_knowledge_point_id not in allowed_points:
            raise DiagnosticGenerationError("diagnostic_knowledge_point_invalid", "题目引用了当前课程范围外的知识点。")
        if item.source_ref_id not in allowed_sources:
            raise DiagnosticGenerationError("diagnostic_source_invalid", "题目引用了当前课程范围外的来源。")
        if item.primary_knowledge_point_id not in source_points[item.source_ref_id]:
            point = next(point for point in scope["knowledgePoints"] if point["id"] == item.primary_knowledge_point_id)
            titles = [source["title"] for source in scope["sources"] if item.primary_knowledge_point_id in source["knowledgePointIds"]]
            raise DiagnosticGenerationError("diagnostic_source_mismatch",
                f"题目“{item.prompt[:80]}”选用的材料不属于“{point['title']}”。请使用该知识点的材料：{'、'.join(titles)}。")
        try:
            validate_question_version(item.question_type, _question_version_input(item))
        except AssessmentCoreError as exc:
            raise DiagnosticGenerationError("diagnostic_question_contract_invalid", str(exc)) from exc
        dimensions.add(item.diagnostic_dimension)
        point_counts[item.primary_knowledge_point_id] += 1
    if dimensions != set(DIAGNOSTIC_KINDS):
        raise DiagnosticGenerationError("diagnostic_dimension_coverage_invalid", "题组必须覆盖理论、应用和工程判断三个诊断维度。")
    planned = Counter({item.knowledge_point_id: item.question_count for item in generated.coverage_plan})
    if planned != point_counts or set(point_counts) != allowed_points:
        raise DiagnosticGenerationError("diagnostic_coverage_plan_mismatch", "知识点覆盖矩阵与实际题目不一致或存在覆盖缺口。")
    for point_id in scope.get("crossEvidencePointIds", []):
        if point_counts[point_id] < 2:
            raise DiagnosticGenerationError(
                "diagnostic_cross_evidence_insufficient",
                "关键知识点需要至少两条独立题目证据。",
            )
    return generated


def _rejected_review_items(review: DiagnosticReviewBundle) -> list[DiagnosticQuestionReview]:
    return [item for item in review.items if (
        item.verdict != "approved" or item.source_support != "supported"
        or item.answer_consistency != "consistent" or item.profile_fit != "fit"
        or item.knowledge_alignment != "aligned" or item.question_clarity != "self_contained"
    )]


def _validate_diagnostic_revision(payload: dict[str, Any], *, previous: DiagnosticGeneratedSet,
                                  item_ids: set[str], count: int, quotas: dict[str, int],
                                  scope: dict[str, Any]) -> DiagnosticGeneratedSet:
    revised = DiagnosticQuestionRevision.model_validate(payload)
    ids = [item.item_id for item in revised.questions]
    if len(ids) != len(item_ids) or set(ids) != item_ids:
        raise DiagnosticGenerationError("diagnostic_revision_scope_invalid", "修订没有完整对应需要调整的题目。")
    original = {item.item_id: item for item in previous.questions}
    replacements = {item.item_id: item for item in revised.questions}
    for item_id, item in replacements.items():
        old = original[item_id]
        if (item.question_type, item.primary_knowledge_point_id, item.diagnostic_dimension) != (
                old.question_type, old.primary_knowledge_point_id, old.diagnostic_dimension):
            raise DiagnosticGenerationError("diagnostic_revision_scope_invalid", "修订改变了原题的题型或诊断范围。")
    merged = previous.model_copy(update={
        "questions": tuple(replacements.get(item.item_id, item) for item in previous.questions),
    })
    return _validate_generated_set(merged.model_dump(mode="json"), count=count, quotas=quotas, scope=scope)


def _validate_review(
    payload: dict[str, Any],
    *,
    generated: DiagnosticGeneratedSet,
    require_approval: bool = True,
) -> DiagnosticReviewBundle:
    review = DiagnosticReviewBundle.model_validate(payload)
    expected_ids = {item.item_id for item in generated.questions}
    actual_ids = [item.item_id for item in review.items]
    if len(actual_ids) != len(expected_ids) or set(actual_ids) != expected_ids:
        raise DiagnosticGenerationError("diagnostic_review_incomplete", "审核没有逐题覆盖完整题组。")
    rejected = _rejected_review_items(review)
    if require_approval and (review.status != "approved" or rejected):
        summary = "；".join(f"{item.item_id}：{item.public_note}" for item in rejected) or review.decision_summary
        raise DiagnosticGenerationError("diagnostic_review_rejected", f"题组审核未通过：{summary}")
    return review


def _diagnostic_sources_for_questions(questions, sources: list[dict]) -> list[dict]:
    by_id = {item["source_ref_id"]: item for item in sources}
    used: dict[str, set[str]] = {}
    for question in questions:
        used.setdefault(question.source_ref_id, set()).add(question.primary_knowledge_point_id)
    projected = []
    for ref_id, point_ids in used.items():
        source = by_id[ref_id]
        quotes = source.get("point_quotes") or {}
        projected.append({**{key: value for key, value in source.items() if key != "point_quotes"},
            "knowledge_point_ids": sorted(point_ids),
            "quote": "\n\n".join(dict.fromkeys(quotes[point_id] for point_id in sorted(point_ids) if point_id in quotes)) if quotes else source["quote"]})
    return projected


def _diagnostic_review_batches(generated: DiagnosticGeneratedSet, sources: list[dict], *, budget: int = 36000):
    """Bound each model request, without limiting the paper or dropping items."""
    def evidence_for(questions):
        return _diagnostic_sources_for_questions(questions, sources)

    batches, questions = [], []
    for question in generated.questions:
        candidate = questions + [question]
        size = len(_canonical([item.model_dump(mode="json") for item in candidate])) + len(_canonical(evidence_for(candidate)))
        if questions and size > budget:
            batches.append((questions, evidence_for(questions)))
            questions = []
        questions.append(question)
    if questions:
        batches.append((questions, evidence_for(questions)))
    return batches


def _profile_basis(profile: DBProfileSnapshot) -> dict[str, Any]:
    snapshot = dict(profile.snapshot or {})
    self_report = snapshot.get("self_report") or {}
    projection = snapshot.get("profile_projection") or {}
    return {
        "id": profile.id,
        "version": profile.profile_version,
        "source": "已确认自然语言画像" if self_report else "当前版本画像",
        "goal": str((self_report.get("goal") or {}).get("summary") or "").strip(),
        "foundation": str((self_report.get("foundation") or {}).get("summary") or projection.get("knowledge_base") or "").strip(),
        "contentHash": profile.content_hash,
    }


def _diagnostic_profile_context(session: Any, profile: DBProfileSnapshot) -> dict[str, Any]:
    from app.profile_adaptation import build_profile_adaptation, complete_learning_snapshot, profile_prompt_context

    snapshot = complete_learning_snapshot(session, profile)
    adaptation = profile_prompt_context(build_profile_adaptation(snapshot))
    return {
        **_profile_basis(profile),
        "learning_adaptation": adaptation,
        "confirmed_self_report": snapshot.get("self_report") or {},
        "diagnostic_evidence": snapshot.get("diagnostic_evidence") or {},
        "mastery_status": snapshot.get("mastery_status") or "以已有学习证据为准，未测不等于不会",
    }


def diagnostic_preflight(
    session: Any,
    *,
    user: DBUser,
    course_id: str,
    question_count: int = 15,
    self_rating: str | None = None,
    stage_id: str | None = None,
) -> dict[str, Any]:
    if self_rating is not None and self_rating not in SELF_RATING_VALUES:
        raise DiagnosticGenerationError("diagnostic_self_rating_invalid", "自评起点不受支持。", status_code=422)
    course = _readable_course(session, course_id=course_id, user=user)
    requested_count = _question_count(question_count)
    profile = _latest_profile(session, user.public_id, course.id)
    scope = _generation_scope(
        session,
        course=course,
        profile=profile,
        question_count=requested_count,
        self_rating=self_rating,
        stage_id=stage_id,
    ) if profile else {
        "knowledgePoints": [],
        "sources": [],
        "selfRating": self_rating,
        "targetDifficulty": None,
    }
    eligible_point_count = len(scope.get("knowledgePoints", [])) + len(scope.get("coverageGap", []))
    count = _coverage_question_count(requested_count, eligible_point_count) if profile else requested_count
    adjusted = count != requested_count
    if adjusted:
        scope = _generation_scope(
            session,
            course=course,
            profile=profile,
            question_count=count,
            self_rating=self_rating,
            stage_id=stage_id,
        )
    quotas = _question_type_quotas(count)
    can_generate = (
        profile is not None
        and len(scope["knowledgePoints"]) >= 1
        and bool(scope["sources"])
        and not scope.get("coverageGap")
        and not scope.get("missingEvidencePointIds")
    )
    blockers = []
    if profile is None:
        blockers.append("请先确认首次学习画像。")
    if profile is not None and len(scope["knowledgePoints"]) < 1:
        blockers.append("本阶段需要有可定位来源的知识点。")
    if profile is not None and scope.get("coverageGap"):
        blockers.append(
            f"当前题量不足以覆盖本阶段，还缺少 {len(scope['coverageGap'])} 个知识点。"
        )
    if profile is not None and not scope["sources"]:
        blockers.append("当前课程没有可用于定制出题的已解析知识来源。")
    if scope.get("missingEvidencePointIds"):
        blockers.append("部分知识点目前只有目录或练习题，需要补充正文讲解后再开始诊断。")
    return {
        "schemaVersion": "p1-b05.diagnostic-preflight.v2",
        "course": {
            "id": course.id,
            "title": course.title,
            "version": course.version,
            "manifestVersion": course.manifest_version,
        },
        "selfRating": self_rating,
        "assessmentScope": scope.get("assessmentScope", {}),
        "selfRatingLabel": SELF_RATING_LABELS.get(self_rating) if self_rating else None,
        "selfRatingOptions": [
            {"value": value, "label": SELF_RATING_LABELS[value]}
            for value in SELF_RATING_VALUES
        ],
        "profileBasis": _profile_basis(profile) if profile else None,
        "requestedQuestionCount": requested_count,
        "expectedQuestionCount": count,
        "selectedQuestionCount": count,
        "questionCountAdjusted": adjusted,
        "estimatedMinutes": count * 2,
        "coverage": {
            "knowledgePoints": scope["knowledgePoints"],
            "questionTypes": quotas,
            "questionKinds": {kind: "required" for kind in DIAGNOSTIC_KINDS},
            "sourceCount": len(scope["sources"]),
            "targetDifficulty": scope["targetDifficulty"],
            "coverageStatus": "blocked" if scope.get("coverageGap") else "ready",
            "coverageGap": scope.get("coverageGap", []),
            "crossEvidencePointIds": scope.get("crossEvidencePointIds", []),
        },
        "generationMode": "llm_knowledge_profile",
        "modelPolicy": {
            "model": "deepseek-v4-flash",
            "thinking": "enabled",
            "reasoningEffort": "max",
            "allowFallback": False,
        },
        "canGenerate": can_generate,
        "blockers": blockers,
    }


async def _generate_and_review(
    session: Any,
    *,
    llm: Any,
    user: DBUser,
    course: DBCourse,
    profile: DBProfileSnapshot,
    count: int,
    scope: dict[str, Any],
    self_rating: str | None = None,
) -> tuple[DiagnosticGeneratedSet, DiagnosticReviewBundle, dict[str, Any]]:
    _require_model_policy(llm)
    quotas = _question_type_quotas(count)
    public_sources = [
        {
            "source_ref_id": item["sourceRefId"],
            "title": item["title"],
            "location": item["location"],
            "chapter_title": item["chapterTitle"],
            "knowledge_point_ids": item["knowledgePointIds"],
            "quote": item["quote"],
            "point_quotes": item.get("knowledgePointQuotes", {}),
        }
        for item in scope["sources"]
    ]
    profile_basis = {
        **_diagnostic_profile_context(session, profile),
        "targetDifficulty": round(_target_difficulty(profile, self_rating), 3),
        "profileSnapshotId": profile.id,
        "profileVersion": profile.profile_version,
        "selfRating": self_rating,
        "selfRatingLabel": SELF_RATING_LABELS.get(self_rating) if self_rating else None,
    }
    revision_ids = set(scope.get("_revisionItemIds") or [])
    previous = DiagnosticGeneratedSet.model_validate(scope["_rejectedDraft"]) if revision_ids else None
    output_model = DiagnosticQuestionRevision if previous else DiagnosticGeneratedSet
    generator_system = (
        "你是 EduMatrix 入学诊断出题专家。只输出符合 JSON Schema 的原始 JSON 对象，不要 Markdown。"
        "必须只使用给定课程知识点、source_ref_id 和来源原文，结合已确认画像定制难度；不得声称学习者已经掌握。"
        + ("当前仅修订revision_items：只返回这些题目的questions数组，保持各题item_id、题型、主知识点和诊断维度。"
           "未列出的已通过题目由系统原样保留，不得重写、增删或换题型；全卷题干只供查重。" if previous else
           "严格生成指定总题数和题型配额，题目不得重复；判断题、单项选择题、简答题都要覆盖。"
           "诊断维度也要均衡覆盖：理论理解 8 题、应用判断 6 题、工程判断 6 题（题量变化时按比例缩放，三类至少各 1 题）。")
        +
        "每题必须绑定一个来源确实支持的 knowledge_point_id/source_ref_id；简答题必须给可执行评分 rubric，权重和为 1。"
        "每题source_ref_id只能从该知识点在target_knowledge_points中的sourceRefIds选择，不得借用其他知识点的章节；若该材料不能检验目标概念，应如实指出，不得换知识点编号冒充覆盖。"
        "题目必须直接检验绑定知识点的概念或应用，不能因为出自同一章节就把无关题目算入覆盖；例如GPU异步不能检验降维，优化器epsilon不能检验交叉验证。"
        "题干应提供作答所需条件，不用缺少背景的‘本任务’‘该案例’要求猜测教材；不考目录篇章位置或某份自检脚本的约定。"
        "把注册背景、分项基础、具体误解、语言、设备、时间与已记录学习证据共同用于出题，不能只看一个difficulty数值。"
        "本次只诊断assessment_scope.selected中的阶段，后续阶段保持未测，不在本卷考全课高级术语。"
        "不同基础保持本阶段共同专业核心。先修未学时从已有数量和逻辑经验考查进入本阶段的理解；"
        "题干加一个术语定义不能替代概率、矩阵、导数等先修，更不能让未学者直接推导高级公式。"
        "同一知识点可先检验直观判断再逐步检验独立解释或操作，不能围绕同一个判断反复换句式。"
        "已确认的强项不反复入门，薄弱项允许小步推理，但题干不能直接教会本题答案。"
        "诊断用于了解学习起点，不能把教学偏好中的‘先看完整例题’机械变成每题先给同类完整答案；"
        "只补理解题意所需的术语、数据和关系，保留独立判断或计算，教学示范安排留到诊断后的学习过程。"
        "入学诊断不强迫安装未具备的软件；在现有工具下用数据表、伪代码或可读运行结果考查同一原理。"
        "解释说清为什么成立、条件与误区，不能只说‘来源明确指出’。选择项用正文且不带A/B/C/D前缀，"
        "不用‘以上全对’或相互引用选项；解析用选项内容说明理由，避免只写字母。"
        "干扰项来自可解释的概念混淆，不靠明显无关、荒谬选项送分；判断题避免全真或几乎全真。"
        "整卷比较实际考查的推理步骤，两个知识点不能只换措辞重复问同一判断；分别检验相应核心。"
        "教材中的类比不等于通用定义，特定实现/配置的经验不等于普遍定律。用于比喻或特定实现时必须写清限定；"
        "不要把未经给定配置推导的资源消耗、效果或倍率作为确定结论，来源的概括也要核适用条件。"
        "改编教材数值案例时，原案例的结论不能随数字直接搬用：判断误差高低需要任务尺度、可比基线或明确的目标规律。"
        "训练与验证误差接近本身不证明欠拟合；缺少上述依据时应考查能得出什么、还需哪些信息，评分接受有依据的未确定判断。"
        "任务类型由预测目标和损失/输出约定决定，标签的数值编码或离散取值不能单独决定回归还是分类。"
        "例如星级评分可按数值误差回归，也可按类别或顺序建模；未指定目标时不能以教材举过某种建模为由排除其它合理建模。"
        "要考唯一答案就明确任务目标；要考建模选择就允许学习者说明条件，不把含糊的题意变成知识错误。"
        + ("" if previous else "coverage_plan 必须逐知识点列出实际题数并覆盖全部 target_knowledge_points。")
        +
        "知识结论必须由对应authorized_sources的quote支持，允许围绕其中的原理构造明确的练习数据、情境和计算，数值可复算。"
        "题干直接描述学习问题：解释原理、按给定关系计算、比较方案或找出具体错误；资料只作为后台核对依据。"
        "不要问‘材料怎么说/列了什么/建议什么’，也不要让学习者汇报来源缺了什么或声称自己是否已做某评测。"
        "诊断测专业理解，不测原文措辞和教材作者的实现习惯；文件路径、库类名、自检阈值或检查清单本身不是理解目标。"
        "源码示例的批次次数/配置比例不能直接成为方法定义。题干可以给求解所需关系，但必须保留一个学习者要自己完成的判断或计算。"
        "工程题区分算法所需的数学量与实现调用次数：合批、缓存或不同实现会改变调用次数，未固定实现时不能要求唯一次数。"
        "区分计算梯度、参数纳入优化器和执行更新这几个条件；只有前者不能推出参数已改变。损失掩码等配置要说明训练目标，不能把一种配方写成唯一正确方案。"
        "题干保留完整条件、必要数据和术语；解析与参考答案写足理解和评分所需理由，不为字数删掉前提。"
        "简答 rubric 覆盖实际可观察的独立完成标准；若题干允许任选若干方法，评分须接受满足要求的等价组合，不能暗中要求答全。去除与作答无关的铺陈和重复。"
        "每项计分标准必须对应题干明确要求的回答；解析里补充的延伸知识不能变成隐藏扣分项。"
        "涉及相对频率和大数定律时，给清同一概率机制、独立或足够可比的抽样条件；更多样本减小随机波动，不保证某一次估计更准，不能消除抽样偏差。"
        "若要求解释训练、验证、测试三者用途，题干须逐一问到；只问后两者用途时，不得把训练集用途另设扣分项。"
        "例如只要求计算和比较平方误差时，不能额外因未写异常值敏感而扣分；如需要解释异常值，先在题干明确提问。"
        "根据具体审核反馈修改错误条件、正文依据、题干或评分，不把缺正文改成目录背诵，也不把答案直接抄进题干。"
        f" JSON Schema: {_canonical(output_model.model_json_schema())}"
    )
    generator_payload = {
        "request": {
            "question_count": count,
            "question_type_quotas": quotas,
            "required_diagnostic_dimensions": DIAGNOSTIC_KINDS,
            "diagnostic_dimension_quotas": {"theory": 8, "application": 6, "engineering_judgment": 6} if count == 20 else None,
        },
        "course": {
            "id": course.id,
            "title": course.title,
            "version": course.version,
            "manifestVersion": course.manifest_version,
        },
        "profile": profile_basis,
        "self_rating": self_rating,
        "assessment_scope": scope.get("assessmentScope", {}),
        "target_difficulty": scope["targetDifficulty"],
        "target_knowledge_points": scope["knowledgePoints"],
        "coverage_plan_template": [
            {
                "knowledge_point_id": item["id"],
                "question_count": 2 if item["id"] in scope.get("crossEvidencePointIds", []) else 1,
                "rationale": "关键知识点需要交叉证据" if item["id"] in scope.get("crossEvidencePointIds", []) else "覆盖本阶段知识点",
            }
            for item in scope["knowledgePoints"]
        ],
        "authorized_sources": [{key: value for key, value in source.items() if key != "point_quotes"} for source in public_sources],
        "previous_attempt_feedback": scope.get("previousAttemptFeedback"),
    }
    if "_workKey" not in scope:
        # Bind reuse to all actual teaching inputs and the initial generation
        # instructions. A changed source passage, learner context or policy
        # cannot inherit an older candidate merely because the task is the same.
        scope["_workKey"] = _hash([
            generator_system, {key: value for key, value in generator_payload.items()
                               if key != "previous_attempt_feedback"},
            {key: getattr(llm, key, None) for key in
             ("provider", "model", "thinking_mode", "reasoning_effort", "temperature", "max_tokens")},
        ])
        saved_work = _saved_diagnostic_work(session, scope.get("_taskId"), scope["_workKey"])
        candidates = [item for item in saved_work if item.get("kind") == "candidate"]
        if candidates:
            candidate = candidates[-1]
            restored = _validate_generated_set(candidate["generated"], count=count, quotas=quotas, scope=scope)
            scope["_reviewCandidate"] = (restored, SimpleNamespace(**candidate["call"]), profile_basis)
            scope["_generationCallIds"] = candidate["generationCallIds"]
            scope["_choiceSeed"] = candidate["choiceSeed"]
            scope["_reviewBatchItemIds"] = candidate["reviewBatchItemIds"]
        scope["_reviewBatches"] = {
            item["batchKey"]: (SimpleNamespace(**item["call"]), DiagnosticReviewBundle.model_validate(item["review"]))
            for item in saved_work if item.get("kind") == "review_batch"
        }
    if previous:
        revision_items = [item for item in previous.questions if item.item_id in revision_ids]
        revision_points = {item.primary_knowledge_point_id for item in revision_items}
        # Reuse the same frozen point passages as review; don't resend unrelated
        # textbook sections or ask the model to rewrite already approved items.
        revision_sources = _diagnostic_sources_for_questions(revision_items, public_sources)
        generator_payload.update({
            "request": {"question_count": len(revision_items), "editable_item_ids": sorted(revision_ids)},
            "target_knowledge_points": [point for point in scope["knowledgePoints"] if point["id"] in revision_points],
            "authorized_sources": revision_sources,
            "revision_items": [item.model_dump(mode="json") for item in revision_items],
            "whole_paper_questions": [{"item_id": item.item_id, "prompt": item.prompt} for item in previous.questions],
        })
        generator_payload.pop("coverage_plan_template", None)
    generator_prompt = _canonical(generator_payload)
    cached_candidate = scope.get("_reviewCandidate")
    if cached_candidate:
        generated, generated_result, profile_basis = cached_candidate
    else:
        if scope.get("_progress"):
            scope["_progress"]("generation")
        try:
            generation_backend = llm
            if isinstance(getattr(llm, "max_tokens", None), int):
                # Deep reasoning and 15–25 complete questions share the output
                # allowance. Keep this request-local instead of enlarging chats.
                generation_backend = copy(llm)
                generation_backend.max_tokens = max(llm.max_tokens, 32768)
            generated_result = await execute_registered_structured_call(
                session,
                backend=generation_backend,
                capability=Capability.QUIZ,
                system_prompt=generator_system,
                user_prompt=generator_prompt,
                role="入学诊断出题",
                operation="p1_b05_diagnostic_generate",
                response_model=output_model,
                response_validator=(lambda payload: _validate_diagnostic_revision(
                    payload, previous=previous, item_ids=revision_ids, count=count, quotas=quotas, scope=scope,
                )) if previous else lambda payload: _validate_generated_set(
                    payload,
                    count=count,
                    quotas=quotas,
                    scope=scope,
                ),
                owner_public_id=user.public_id,
                course_id=course.id,
                output_constraints=OutputConstraints(
                    format="json",
                    max_length=180000,
                    source_scope=tuple(item["sourceRefId"] for item in scope["sources"]),
                    safety_boundary="Only the verified course and confirmed profile snapshot may be used.",
                ),
            )
            generated = DiagnosticGeneratedSet.model_validate(generated_result.structured_output)
            scope.setdefault("_generationCallIds", []).append(generated_result.call_id)
            generated = _arrange_choice_options(generated, seed=scope.setdefault("_choiceSeed", generated_result.call_id))
            _validate_generated_set(generated.model_dump(mode="json"), count=count, quotas=quotas, scope=scope)
        except M5CapabilityError as exc:
            service_failure = _diagnostic_service_failure(exc, reviewing=False)
            if service_failure is not None:
                raise service_failure from exc
            cause = exc.__cause__
            while isinstance(cause, M5CapabilityError) and cause.__cause__ is not None:
                cause = cause.__cause__
            if isinstance(cause, DiagnosticGenerationError):
                raise cause
            from llm_client import ModelOutputLimitError
            if isinstance(cause, ModelOutputLimitError):
                raise DiagnosticGenerationError(
                    "diagnostic_output_limit", "题组尚未完整生成，本次已停止。已完成的其他课程仍保留，可以稍后重试。", status_code=502,
                ) from exc
            raise DiagnosticGenerationError(
                "diagnostic_model_generation_failed",
                "真实模型未能生成符合题量、题型和来源合同的诊断题组，请重试。",
                status_code=502,
            ) from exc

        scope["_reviewCandidate"] = (generated, generated_result, profile_basis)

    if scope.get("_progress"):
        scope["_progress"]("validation")

    reviewer_system = (
        "你是独立的 EduMatrix 诊断题审核员。只输出符合 JSON Schema 的原始 JSON 对象，不要 Markdown。"
        "逐题核对：来源是否直接支持题意和答案、答案是否自洽、难度是否符合给定画像。"
        "来源是核对依据而非正确性保证：逐题检查定义、推理和数值条件；教材类比不能泛化为技术定义，"
        "改编案例还要检查原来源结论依赖的条件是否在新题中成立。训练与验证误差接近不能单独证明欠拟合，"
        "若未给任务尺度、可比基线或目标规律，不能把绝对误差数值直接叫作高误差并据此扣分；应允许有依据的未确定判断。"
        "题意允许不同建模时逐一检查答案是否仍唯一：整数/数值编码不单独决定回归或分类，星级可做回归、类别或有序预测。"
        "教材中的一种例子不自动限定新题的预测目标；没有明确输出/损失约定而排除合理建模的判断题应定向补条件或改问法。"
        "某实现的经验不能泛化为必然结果，内存/性能倍率须有对应配置或推导。来源自身概括过度时说明具体需修之处。"
        "工程条件逐项核对：求梯度不等于优化器已更新参数；数学上需要的各项量不等于固定的前向调用次数，须考虑合批和缓存。"
        "训练标签掩码等配置必须对应题干指定的目标。题干允许任选方法时，rubric不能只接受一个固定组合或要求答全。"
        "逐项把rubric与题干要求对应：学习者完整回答题干就应能得满分；未问的延伸知识、额外术语或额外方法不能成为隐藏扣分项。"
        "核对计分项时先设想一份严格只回答题干的完整答案；若它仍会被某项扣分，应补问或删除该项。划分出训练集不等于题干已要求解释训练集用途。"
        "概率题不能仅凭样本更多就下结论：须说明同一概率机制和可比抽样条件，区分随机波动减小、某次更接近真值与抽样偏差。"
        "结合完整分项基础、设备、时间、误解和学习依据判断profile_fit，不按职业贴标签，不能只看难度数值。"
        "按assessment_scope的阶段目标审核，未学先修应检验进入本阶段的基础理解；不能给高级术语加括号就判适配。"
        "逐步检查作答需要哪些知识与推理。如果已确认未学的矩阵、概率、导数或编程是必要前提，应改成同一原理的先修任务；不得只调低difficulty。"
        "区分必需先修与学习偏好：诊断不是教学讲义，‘先完整示范’偏好不能要求每道诊断题先给完整算例。"
        "已提供可读公式且只需其已确认会的基本算术时，可以独立作答；不能因未附教学示范判unfit。"
        "首次术语配英文等排版偏好应尽量满足；缺少不影响理解的括注只是可选完善，不因此拒绝正确且适配的题目。"
        "区分题干描述的当前实验条件与题目允许提出的后续改进：例如当前固定训练集比较后可以建议收集更多数据，二者本身不矛盾。"
        "选择项已经重新排列；逐项按正文推导答案并核对解析字母，不沿用初稿位置。"
        "还要跨题检查是否只换说法重复考同一判断，以及干扰项是否能区分常见误解；记录应改的题号和具体原因。"
        "还须逐题检查knowledge_alignment：题目实际检验的概念是否与target_knowledge_points中绑定知识点相符，同章节的无关事实不能充数；"
        "question_clarity检查题干是否独立可答，依赖未提供案例、任务约定，或只考教材目录而不考知识理解时必须拒绝。"
        "任何一题不满足就标记 rejected，整体 status 必须 rejected；不要输出私有思维链，只写公开审核说明。"
        "必须为每道题输出恰好一个items条目，public_note说明具体依据或修法，decision_summary总结主要问题；不重复题干。"
        f" JSON Schema: {_canonical(DiagnosticReviewBundle.model_json_schema())}"
    )
    batch_ids = scope.get("_reviewBatchItemIds")
    if batch_ids:
        questions_by_id = {item.item_id: item for item in generated.questions}
        review_batches = []
        for item_ids in batch_ids:
            group = generated.model_copy(update={"questions": tuple(questions_by_id[item_id] for item_id in item_ids)})
            # If a correction grows, split only its original group. Do not
            # shift every later boundary and invalidate unrelated reviews.
            review_batches.extend(_diagnostic_review_batches(group, public_sources))
    else:
        review_batches = _diagnostic_review_batches(generated, public_sources)
        scope["_reviewBatchItemIds"] = [[item.item_id for item in questions] for questions, _ in review_batches]
    if not cached_candidate:
        _save_diagnostic_work(session, scope, kind="candidate", generated=generated.model_dump(mode="json"),
                              call={"call_id": generated_result.call_id, "model": generated_result.model},
                              generationCallIds=list(scope["_generationCallIds"]), choiceSeed=scope["_choiceSeed"],
                              reviewBatchItemIds=scope["_reviewBatchItemIds"])
    reviewed_batches = scope.setdefault("_reviewBatches", {})
    if scope.get("_progress"):
        scope["_progress"]("review")
    try:
        from config import CONFIG
        review_backend = llm
        if isinstance(getattr(llm, "max_tokens", None), int):
            review_backend = copy(llm)
            review_backend.max_tokens = max(llm.max_tokens, 65536)
        review_slots = asyncio.Semaphore(max(1, CONFIG.max_concurrent_llm))

        async def review_one(questions, sources):
            point_ids = {question.primary_knowledge_point_id for question in questions}
            batch = generated.model_copy(update={
                "questions": tuple(questions),
                "coverage_plan": tuple(item for item in generated.coverage_plan if item.knowledge_point_id in point_ids),
            })
            reviewer_prompt = _canonical({
                "profile": profile_basis,
                "assessment_scope": scope.get("assessmentScope", {}),
                "target_knowledge_points": [point for point in scope["knowledgePoints"] if point["id"] in point_ids],
                "authorized_sources": sources,
                "generated_set": batch.model_dump(mode="json"),
                "whole_paper_questions": [{"item_id": item.item_id, "prompt": item.prompt,
                    "knowledge_point_id": item.primary_knowledge_point_id} for item in generated.questions],
                "review_scope": "只逐题审核generated_set中的题；whole_paper_questions用于核对跨批题目重复。",
            })
            # A revised question is checked against the entire paper. Its
            # unchanged peers need not be reviewed again solely because that
            # question changed; their own evidence/answers/profile still bind
            # the cached result. Cross-paper duplicates are checked by the
            # reviewers of the changed batch as well as structural validation.
            batch_key = _hash([reviewer_system, profile_basis, scope.get("assessmentScope", {}),
                [point for point in scope["knowledgePoints"] if point["id"] in point_ids],
                sources, [item.model_dump(mode="json") for item in questions]])
            if batch_key in reviewed_batches:
                saved_result, saved_review = reviewed_batches[batch_key]
                _validate_review(saved_review.model_dump(mode="json"), generated=batch, require_approval=False)
                return saved_result, saved_review
            async with review_slots:
                # Independent model I/O can overlap. Each audit owns its DB
                # session; never share the caller's transaction across tasks.
                with Session(bind=session.get_bind()) as review_session:
                    review_result = await execute_registered_structured_call(
                        review_session, backend=review_backend, capability=Capability.DECISION,
                        system_prompt=reviewer_system, user_prompt=reviewer_prompt,
                        role="入学诊断审核", operation="p1_b05_diagnostic_review",
                        response_model=DiagnosticReviewBundle,
                        response_validator=lambda payload: _validate_review(payload, generated=batch, require_approval=False),
                        owner_public_id=user.public_id, course_id=course.id,
                        output_constraints=OutputConstraints(format="json", max_length=80000,
                            source_scope=tuple(item["source_ref_id"] for item in sources),
                            safety_boundary="Review only public evidence; do not expose private reasoning."),
                    )
                batch_review = DiagnosticReviewBundle.model_validate(review_result.structured_output)
                reviewed_batches[batch_key] = (review_result, batch_review)
                _save_diagnostic_work(session, scope, kind="review_batch", batchKey=batch_key,
                                      call={"call_id": review_result.call_id, "model": review_result.model},
                                      review=batch_review.model_dump(mode="json"))
                return review_result, batch_review

        # Collect every started call, including failures. Successful batches
        # remain reusable and a failure cannot publish a partially checked paper.
        results = await asyncio.gather(*(review_one(*batch) for batch in review_batches), return_exceptions=True)
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            raise failures[0]
        review_results = [result[0] for result in results]
        batch_reviews = [result[1] for result in results]
        scope["_revisionItemIds"] = sorted({
            item.item_id for batch_review in batch_reviews for item in _rejected_review_items(batch_review)
        })
        if not scope["_revisionItemIds"] and any(item.status != "approved" for item in batch_reviews):
            scope["_revisionItemIds"] = [item.item_id for item in generated.questions]
        review = _validate_review({
            "status": "approved" if all(item.status == "approved" for item in batch_reviews) else "rejected",
            "decision_summary": "；".join(dict.fromkeys(item.decision_summary for item in batch_reviews)),
            "items": [item.model_dump(mode="json") for batch_review in batch_reviews for item in batch_review.items],
        }, generated=generated)
    except DiagnosticGenerationError:
        scope.pop("_reviewCandidate", None)
        scope["_rejectedDraft"] = generated.model_dump(mode="json")
        raise
    except M5CapabilityError as exc:
        service_failure = _diagnostic_service_failure(exc, reviewing=True)
        if service_failure is not None:
            raise service_failure from exc
        cause = exc.__cause__
        while isinstance(cause, M5CapabilityError) and cause.__cause__ is not None:
            cause = cause.__cause__
        if isinstance(cause, DiagnosticGenerationError):
            if cause.code == "diagnostic_review_rejected":
                scope.pop("_reviewCandidate", None)
                scope["_rejectedDraft"] = generated.model_dump(mode="json")
            raise cause
        from llm_client import ModelOutputLimitError
        if isinstance(cause, ModelOutputLimitError):
            raise DiagnosticGenerationError(
                "diagnostic_review_output_limit", "题组核对尚未完成，本次已停止。可以稍后重试。", status_code=502,
            ) from exc
        raise DiagnosticGenerationError(
            "diagnostic_model_review_failed",
            "诊断题组未通过真实模型审核，请重试。",
            status_code=502,
        ) from exc
    return generated, review, {
        "model": generated_result.model,
        "generationCallId": generated_result.call_id,
        "generationCallIds": list(scope.get("_generationCallIds") or [generated_result.call_id]),
        "reviewCallId": review_results[-1].call_id,
        "reviewCallIds": [result.call_id for result in review_results],
        "profileSnapshotId": profile.id,
        "profileVersion": profile.profile_version,
        "learningContext": profile_basis,
    }


def generate_diagnostic_blueprint(
    session: Any,
    *,
    user: DBUser,
    request: DiagnosticBlueprintRequest,
    llm: Any,
    progress: Any = None,
    task_id: str | None = None,
) -> tuple[DBDiagnosticBlueprint, bool]:
    course = _readable_course(session, course_id=request.course_id, user=user)
    key = request.idempotency_key.strip()
    if not key:
        raise DiagnosticGenerationError("idempotency_required", "请重新开始生成诊断。")
    requested_count = _question_count(request.question_count)
    self_rating = request.self_rating
    if self_rating is not None and self_rating not in SELF_RATING_VALUES:
        raise DiagnosticGenerationError("diagnostic_self_rating_invalid", "自评起点不受支持。", status_code=422)
    existing = session.query(DBDiagnosticBlueprint).filter_by(
        owner_public_id=user.public_id,
        course_id=course.id,
        idempotency_key=key,
    ).first()
    if existing is not None:
        existing_context = (existing.review_decision or {}).get("contextSnapshot") or {}
        existing_requested_count = int(
            (existing.review_decision or {}).get("requestedQuestionCount")
            or existing_context.get("requestedQuestionCount")
            or existing.question_count
        )
        if (
            existing_requested_count != requested_count
            or (request.stage_id is not None and
                (existing_context.get("assessmentScope", {}).get("selected") or {}).get("id") != request.stage_id)
            or (self_rating is not None and existing_context.get("selfRating") not in {None, self_rating})
            or (
                existing_context.get("course", {}).get("version")
                and existing_context["course"]["version"] != course.version
            )
        ):
            raise DiagnosticGenerationError(
                "diagnostic_idempotency_conflict",
                "同一生成请求不能更换题量，请重新选择题量后发起新请求。",
            )
        return existing, False

    profile = _latest_profile(session, user.public_id, course.id)
    if profile is None:
        raise DiagnosticGenerationError("diagnostic_profile_required", "请先确认首次学习画像，再开始入学诊断。")
    from app.learning_generation_jobs import course_generation_basis, assert_course_generation_basis
    basis_scope = {'course_id':course.id, 'owner_public_id':user.public_id}
    basis = course_generation_basis(session, **basis_scope)
    scope = _generation_scope(
        session,
        course=course,
        profile=profile,
        question_count=requested_count,
        self_rating=self_rating,
        stage_id=request.stage_id,
    )
    eligible_point_count = len(scope.get("knowledgePoints", [])) + len(scope.get("coverageGap", []))
    count = _coverage_question_count(requested_count, eligible_point_count)
    adjusted = count != requested_count
    if adjusted:
        scope = _generation_scope(
            session,
            course=course,
            profile=profile,
            question_count=count,
            self_rating=self_rating,
            stage_id=request.stage_id,
        )
    if scope.get("coverageGap"):
        raise DiagnosticGenerationError(
            "diagnostic_coverage_incomplete",
            f"当前题量不足以覆盖本阶段，还缺少 {len(scope['coverageGap'])} 个知识点。",
            status_code=422,
        )
    if len(scope["knowledgePoints"]) < 1 or not scope["sources"]:
        raise DiagnosticGenerationError(
            "diagnostic_sources_insufficient",
            "本阶段还没有可用的知识来源，请先补充或解析课程资料。",
        )
    if scope.get("missingEvidencePointIds"):
        raise DiagnosticGenerationError("diagnostic_sources_insufficient",
            "部分知识点目前只有目录或练习题，请补充正文讲解后再开始诊断。")
    last_generation_error: DiagnosticGenerationError | None = None
    if task_id is not None:
        scope["_taskId"] = task_id
    if progress is not None:
        scope["_progress"] = progress
    for _attempt in range(3):
        try:
            generated, model_review, model_evidence = asyncio.run(_generate_and_review(
                session,
                llm=llm,
                user=user,
                course=course,
                profile=profile,
                count=count,
                scope=scope,
                self_rating=self_rating,
            ))
            break
        except DiagnosticGenerationError as exc:
            last_generation_error = exc
            if exc.code in {"diagnostic_output_limit", "diagnostic_review_output_limit", "diagnostic_service_auth_failed"}:
                raise
            # A connection failure gives no teaching feedback. Keep the same
            # candidate and any completed review batches for the bounded retry.
            if exc.code != "diagnostic_service_unavailable":
                scope["previousAttemptFeedback"] = {"code": exc.code, "message": str(exc)}
            if _attempt == 2:
                raise
    else:
        if last_generation_error is not None:
            raise last_generation_error
        raise DiagnosticGenerationError("diagnostic_generation_failed", "诊断题组生成失败，请重试。", status_code=502)

    from app.learning_generation_jobs import assert_generation_owner
    assert_generation_owner(session)
    assert_course_generation_basis(session, basis, **basis_scope)
    selected = []
    point_counts = Counter()
    question_types = Counter()
    question_kinds = Counter()
    difficulty = Counter()
    for item in generated.questions:
        question, version = create_question_version(
            session,
            owner_public_id=user.public_id,
            course_id=course.id,
            question_type=item.question_type,
            origin="derived",
            version=_question_version_input(item),
        )
        question.status = "approved"
        selected.append((item, question, version))
        point_counts[item.primary_knowledge_point_id] += 1
        question_types[item.question_type] += 1
        question_kinds[item.diagnostic_dimension] += 1
        difficulty["foundation" if item.difficulty < 0.35 else "standard" if item.difficulty < 0.65 else "stretch"] += 1

    points_by_id = {item["id"]: item for item in scope["knowledgePoints"]}
    point_order = {item["id"]: index for index, item in enumerate(scope["knowledgePoints"])}
    knowledge = [
        {
            **points_by_id[point_id],
            "questionCount": point_counts[point_id],
            "minimumQuestionCount": points_by_id[point_id].get("minimumQuestionCount", 1),
            "crossEvidenceTarget": points_by_id[point_id].get("crossEvidenceTarget", 1),
            "coverageStatus": "verified" if point_counts[point_id] >= points_by_id[point_id].get("minimumQuestionCount", 1) else "insufficient_evidence",
            "crossEvidenceStatus": "verified" if point_counts[point_id] >= points_by_id[point_id].get("crossEvidenceTarget", 1) else "single_evidence",
        }
        for point_id in sorted(point_counts, key=point_order.get)
    ]
    used_source_ids = {item.source_ref_id for item in generated.questions}
    source_refs = [
        {key: value for key, value in source.items() if key != "quote"}
        for source in scope["sources"]
        if source["sourceRefId"] in used_source_ids
    ]
    review = {
        "status": "approved",
        "reviewer": "deepseek-v4-flash:diagnostic-review",
        "checks": {
            "schema": "passed",
            "courseScope": "passed",
            "sourceTraceability": "passed",
            "knowledgeCoverage": "passed",
            "questionTypeQuota": "passed",
            "duplicatePrompt": "passed",
            "profileFit": "passed",
            "answerKeyHidden": "passed",
            "knowledgePointCoverage": "passed",
            "crossEvidence": "passed" if scope.get("crossEvidencePointIds") else "not_required",
        },
        "requestedQuestionCount": requested_count,
        "selectedQuestionCount": count,
        "questionCountAdjusted": adjusted,
        "model": model_evidence["model"],
        "generationCallId": model_evidence["generationCallId"],
        "generationCallIds": model_evidence.get("generationCallIds", [model_evidence["generationCallId"]]),
        "reviewCallId": model_evidence["reviewCallId"],
        "reviewCallIds": model_evidence.get("reviewCallIds", [model_evidence["reviewCallId"]]),
        "profileSnapshotId": profile.id,
        "profileVersion": profile.profile_version,
        "profileAdaptationSummary": generated.profile_adaptation_summary,
        "decisionSummary": model_review.decision_summary,
        "itemReviews": [
            {"questionVersionId": version.id, **next(
                result.model_dump(mode="json") for result in model_review.items if result.item_id == item.item_id)}
            for item, _, version in selected
        ],
        "selfRating": self_rating,
        "contextSnapshot": {
            "sourceSnapshotVersion": "p1-b08-source.v2",
            "assessmentScope": scope.get("assessmentScope", {}),
            "requestedQuestionCount": requested_count,
            "selectedQuestionCount": count,
            "questionCountAdjusted": adjusted,
            "coverageContract": {
                "status": "verified",
                "scope": "stage",
                "courseKnowledgePointCount": len(scope.get("assessmentScope", {}).get("courseKnowledgePoints", [])),
                "deferredKnowledgePoints": scope.get("assessmentScope", {}).get("deferredKnowledgePoints", []),
                "requiredKnowledgePointCount": len(scope["knowledgePoints"]),
                "coveredKnowledgePointCount": len(scope["knowledgePoints"]),
                "coverageGap": list(scope.get("coverageGap", [])),
                "crossEvidencePointIds": list(scope.get("crossEvidencePointIds", [])),
            },
            "course": {
                "id": course.id,
                "title": course.title,
                "version": course.version,
                "manifestVersion": course.manifest_version,
            },
            "profile": {
                "id": profile.id,
                "version": profile.profile_version,
                "contentHash": profile.content_hash,
                "learningContext": model_evidence.get("learningContext", {}),
            },
            "selfRating": self_rating,
            "sourceRefs": [
                {
                    "sourceRefId": source["sourceRefId"],
                    "sourceDocumentId": source["sourceDocumentId"],
                    "title": source["title"],
                    "location": source["location"],
                    "chapterId": source["chapterId"],
                    "chapterTitle": source["chapterTitle"],
                    "knowledgePointIds": list(source["knowledgePointIds"]),
                    "quote": source["quote"],
                    "knowledgePointQuotes": source.get("knowledgePointQuotes", {}),
                    "contentHash": source["contentHash"],
                    "documentContentHash": source.get("documentContentHash", ""),
                }
                for source in scope["sources"]
            ],
        },
    }
    stages = [
        {"key": "analysis", "label": "分析课程、知识库与画像", "status": "completed"},
        {"key": "generation", "label": "AI 定制生成诊断题", "status": "completed"},
        {"key": "validation", "label": "校验题量、题型与来源", "status": "completed"},
        {"key": "review", "label": "独立模型逐题审核", "status": "completed"},
    ]
    payload = {
        "courseId": course.id,
        "profileSnapshotId": profile.id,
        "selfRating": self_rating,
        "contextSnapshot": review["contextSnapshot"],
        "questionVersionIds": [version.id for _, _, version in selected],
        "knowledgePointCoverage": knowledge,
        "difficultyBands": {
            "difficulty": dict(difficulty),
            "questionKinds": dict(question_kinds),
            "questionTypes": dict(question_types),
            "targetDifficulty": round(_target_difficulty(profile, self_rating), 3),
        },
        "sourceRefs": source_refs,
        "coverageContract": {
            "status": "verified",
            "scope": "stage",
            "courseKnowledgePointCount": len(scope.get("assessmentScope", {}).get("courseKnowledgePoints", [])),
            "deferredKnowledgePoints": scope.get("assessmentScope", {}).get("deferredKnowledgePoints", []),
            "requiredKnowledgePointCount": len(scope["knowledgePoints"]),
            "coveredKnowledgePointCount": len(knowledge),
            "coverageGap": list(scope.get("coverageGap", [])),
            "crossEvidencePointIds": list(scope.get("crossEvidencePointIds", [])),
        },
        "reviewDecision": review,
        "generationStages": stages,
        "questionCount": count,
        "estimatedMinutes": count * 2,
    }
    row = DBDiagnosticBlueprint(
        owner_public_id=user.public_id,
        course_id=course.id,
        idempotency_key=key,
        profile_snapshot_id=profile.id,
        question_version_ids=payload["questionVersionIds"],
        knowledge_point_coverage=knowledge,
        difficulty_bands=payload["difficultyBands"],
        source_refs=source_refs,
        review_decision=review,
        generation_stages=stages,
        question_count=count,
        estimated_minutes=payload["estimatedMinutes"],
        content_hash=_hash(payload),
    )
    session.add(row)
    session.flush()
    return row, True


def diagnostic_blueprint_payload(session: Any, row: DBDiagnosticBlueprint) -> dict[str, Any]:
    course = session.get(DBCourse, row.course_id)
    frozen_course = ((row.review_decision or {}).get("contextSnapshot") or {}).get("course") or {}
    items = []
    for version_id in row.question_version_ids or []:
        version = session.get(DBAssessmentQuestionVersion, version_id)
        if version is None:
            continue
        question = session.get(DBAssessmentQuestion, version.question_id)
        if question is None:
            continue
        knowledge = (
            session.get(DBKnowledgePoint, version.primary_knowledge_point_id)
            if version.primary_knowledge_point_id
            else None
        )
        response_spec: dict[str, Any] = {"inputKind": question.question_type}
        if question.question_type == "fill_blank":
            blanks = (version.answer_key or {}).get("blanks", (version.answer_key or {}).get("answers", []))
            response_spec["blankCount"] = len(blanks) if isinstance(blanks, (list, tuple)) else 1
        elif question.question_type == "code":
            response_spec["language"] = "python"
        items.append({
            "id": version.id,
            "questionId": question.id,
            "questionType": question.question_type,
            "prompt": learner_safe_prompt(version.prompt, knowledge_point=knowledge.title if knowledge else ""),
            "options": learner_option_texts(version, question),
            "contentIssue": learner_question_content_issue(version, question),
            "bloomLevel": version.bloom_level,
            "expertDifficulty": version.expert_difficulty,
            "primaryKnowledgePointId": version.primary_knowledge_point_id,
            "diagnosticKind": _question_kind(version),
            "responseSpec": response_spec,
            "contentHash": version.content_hash,
        })
    return {
        "schemaVersion": "f3.diagnostic-blueprint.v1",
        "id": row.id,
        "course": {
            "id": row.course_id,
            "title": frozen_course.get("title") or (course.title if course else "当前课程"),
            "version": frozen_course.get("version") or (course.version if course else ""),
            "manifestVersion": frozen_course.get("manifestVersion") or (course.manifest_version if course else ""),
        },
        "profileSnapshotId": row.profile_snapshot_id,
        "selfRating": (row.review_decision or {}).get("selfRating"),
        "contextSnapshot": (row.review_decision or {}).get("contextSnapshot"),
        "status": row.status,
        "versionNumber": row.version_number,
        "questionCount": row.question_count,
        "estimatedMinutes": row.estimated_minutes,
        "knowledgePointCoverage": list(row.knowledge_point_coverage or []),
        "assessmentScope": ((row.review_decision or {}).get("contextSnapshot") or {}).get("assessmentScope", {}),
        "difficultyBands": dict(row.difficulty_bands or {}),
        "coverageContract": ((row.review_decision or {}).get("contextSnapshot") or {}).get("coverageContract") or {},
        "sourceRefs": list(row.source_refs or []),
        "reviewDecision": dict(row.review_decision or {}),
        "generationStages": list(row.generation_stages or []),
        "questions": items,
        "contentHash": row.content_hash,
    }
