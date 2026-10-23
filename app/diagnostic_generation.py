"""Profile- and source-bound entry-diagnostic generation."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union

from pydantic import Field

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
    DBUser,
)
from app.m5_assessment_core import (
    AssessmentCoreError,
    QuestionVersionInput,
    create_question_version,
    learner_option_texts,
    learner_safe_prompt,
    validate_question_version,
)
from app.m2_contracts import StrictModel
from app.m5_capabilities import Capability, M5CapabilityError, OutputConstraints
from app.m5_gateway import execute_registered_structured_call


class DiagnosticGenerationError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class DiagnosticBlueprintRequest:
    course_id: str
    idempotency_key: str
    question_count: int = 15
    self_rating: str | None = None


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
    prompt: str = Field(min_length=8, max_length=4000)
    primary_knowledge_point_id: str = Field(min_length=3, max_length=128)
    source_ref_id: str = Field(min_length=3, max_length=128)
    diagnostic_dimension: Literal["theory", "application", "engineering_judgment"]
    bloom_level: Literal["remember", "understand", "apply", "analyze", "evaluate"]
    difficulty: float = Field(ge=0, le=1)
    explanation: str = Field(min_length=8, max_length=4000)


class DiagnosticTrueFalseQuestion(DiagnosticQuestionBase):
    question_type: Literal["true_false"]
    answer: bool


class DiagnosticChoiceQuestion(DiagnosticQuestionBase):
    question_type: Literal["single_choice"]
    options: tuple[str, ...] = Field(min_length=4, max_length=4)
    answer: Literal["A", "B", "C", "D"]


class DiagnosticShortAnswerQuestion(DiagnosticQuestionBase):
    question_type: Literal["short_answer"]
    reference_answer: str = Field(min_length=8, max_length=4000)
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


class DiagnosticQuestionReview(StrictModel):
    item_id: str = Field(min_length=2, max_length=32)
    verdict: Literal["approved", "rejected"]
    source_support: Literal["supported", "unsupported"]
    answer_consistency: Literal["consistent", "inconsistent"]
    profile_fit: Literal["fit", "unfit"]
    public_note: str = Field(min_length=2, max_length=500)


class DiagnosticReviewBundle(StrictModel):
    status: Literal["approved", "rejected"]
    decision_summary: str = Field(min_length=4, max_length=1000)
    items: tuple[DiagnosticQuestionReview, ...] = Field(min_length=15, max_length=25)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


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
            if snapshot.get("course_id") == course_id:
                return profile
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
) -> dict[str, Any]:
    chapters = {
        row.id: row
        for row in session.query(DBChapter)
        .filter_by(course_id=course.id)
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
        ).all()
    }
    sources = []
    point_source_ids: dict[str, set[str]] = {point_id: set() for point_id in points}
    for ref in session.query(DBSourceRef).filter(
        DBSourceRef.source_document_id.in_(list(documents) or ["-"]),
    ).order_by(DBSourceRef.chapter_id, DBSourceRef.page_number, DBSourceRef.id).all():
        chapter = chapters.get(ref.chapter_id)
        supported_points = sorted(points_by_chapter.get(ref.chapter_id, set()))
        quote = " ".join(str(ref.quote or "").split())
        if chapter is None or not supported_points or not ref.content_hash or not quote:
            continue
        document = documents[ref.source_document_id]
        sources.append({
            "sourceRefId": ref.id,
            "sourceDocumentId": document.id,
            "title": document.title,
            "location": ref.location_label or (f"第 {ref.page_number} 页" if ref.page_number else chapter.title),
            "contentHash": ref.content_hash,
            "documentContentHash": document.content_hash,
            "chapterId": chapter.id,
            "chapterTitle": chapter.title,
            "knowledgePointIds": supported_points,
            "quote": quote[:1600],
        })
        for point_id in supported_points:
            point_source_ids[point_id].add(ref.id)

    eligible_points = [row for row in points.values() if point_source_ids.get(row.id)]
    weak_text = _profile_weak_text(profile)
    level_order = {
        "foundation": {"core": 0, "basic": 0, "advanced": 1, "stretch": 2},
        "advanced": {"advanced": 0, "core": 1, "basic": 1, "stretch": 2},
        "mastered": {"stretch": 0, "advanced": 1, "core": 2, "basic": 2},
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
    return {
        "selfRating": self_rating,
        "targetDifficulty": round(_target_difficulty(profile, self_rating), 3),
        "coverageGap": [
            {"id": row.id, "title": row.title, "sourceRefIds": sorted(point_source_ids[row.id])}
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
            raise DiagnosticGenerationError("diagnostic_source_mismatch", "题目来源与知识点没有章节关联。")
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


def _validate_review(
    payload: dict[str, Any],
    *,
    generated: DiagnosticGeneratedSet,
) -> DiagnosticReviewBundle:
    review = DiagnosticReviewBundle.model_validate(payload)
    expected_ids = {item.item_id for item in generated.questions}
    actual_ids = [item.item_id for item in review.items]
    if len(actual_ids) != len(expected_ids) or set(actual_ids) != expected_ids:
        raise DiagnosticGenerationError("diagnostic_review_incomplete", "审核没有逐题覆盖完整题组。")
    rejected = [
        item for item in review.items
        if item.verdict != "approved"
        or item.source_support != "supported"
        or item.answer_consistency != "consistent"
        or item.profile_fit != "fit"
    ]
    if review.status != "approved" or rejected:
        summary = "；".join(item.public_note for item in rejected[:3]) or review.decision_summary
        raise DiagnosticGenerationError("diagnostic_review_rejected", f"题组审核未通过：{summary}")
    return review


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


def diagnostic_preflight(
    session: Any,
    *,
    user: DBUser,
    course_id: str,
    question_count: int = 15,
    self_rating: str | None = None,
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
        )
    quotas = _question_type_quotas(count)
    can_generate = (
        profile is not None
        and len(scope["knowledgePoints"]) >= 3
        and bool(scope["sources"])
        and not scope.get("coverageGap")
    )
    blockers = []
    if profile is None:
        blockers.append("请先确认首次学习画像。")
    if profile is not None and len(scope["knowledgePoints"]) < 3:
        blockers.append("当前课程知识库至少需要 3 个有可定位来源的有效知识点。")
    if profile is not None and scope.get("coverageGap"):
        blockers.append(
            f"当前题量不足以覆盖全部课程知识点，还缺少 {len(scope['coverageGap'])} 个知识点；请提高题量或补充可诊断题量。"
        )
    if profile is not None and not scope["sources"]:
        blockers.append("当前课程没有可用于定制出题的已解析知识来源。")
    return {
        "schemaVersion": "p1-b05.diagnostic-preflight.v2",
        "course": {
            "id": course.id,
            "title": course.title,
            "version": course.version,
            "manifestVersion": course.manifest_version,
        },
        "selfRating": self_rating,
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
        }
        for item in scope["sources"]
    ]
    profile_basis = {
        **_profile_basis(profile),
        "targetDifficulty": round(_target_difficulty(profile, self_rating), 3),
        "profileSnapshotId": profile.id,
        "profileVersion": profile.profile_version,
        "selfRating": self_rating,
        "selfRatingLabel": SELF_RATING_LABELS.get(self_rating) if self_rating else None,
    }
    generator_system = (
        "你是 EduMatrix 入学诊断出题专家。只输出符合 JSON Schema 的原始 JSON 对象，不要 Markdown。"
        "必须只使用给定课程知识点、source_ref_id 和来源原文，结合已确认画像定制难度；不得声称学习者已经掌握。"
        "严格生成指定总题数和题型配额，题目不得重复；判断题、单项选择题、简答题都要覆盖。"
        "诊断维度也要均衡覆盖：理论理解 8 题、应用判断 6 题、工程判断 6 题（题量变化时按比例缩放，三类至少各 1 题）。"
        "每题必须绑定一个来源确实支持的 knowledge_point_id/source_ref_id；简答题必须给可执行评分 rubric，权重和为 1。"
        "coverage_plan 必须逐知识点列出实际题数并覆盖全部 target_knowledge_points。"
        "每道题只能改写对应 authorized_sources 的 quote 中明确出现的事实、定义、步骤或边界；"
        "不得根据章节标题、常识或模型记忆补充来源没有明确写出的概念。若知识点标题与 quote 不完全一致，"
        "仍以 quote 为唯一依据并选择 quote 中能直接证明该知识点的句子。"
        "为保证题组可读且能在一次诊断中完成：每题 prompt 控制在 120 字以内，explanation 和简答 reference_answer 控制在 180 字以内，"
        "简答 rubric 使用 2—3 条短标准；不要输出与作答无关的背景铺陈、重复定义或冗长推理。"
        f" JSON Schema: {_canonical(DiagnosticGeneratedSet.model_json_schema())}"
    )
    generator_prompt = _canonical({
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
        "target_difficulty": scope["targetDifficulty"],
        "target_knowledge_points": scope["knowledgePoints"],
        "coverage_plan_template": [
            {
                "knowledge_point_id": item["id"],
                "question_count": 2 if item["id"] in scope.get("crossEvidencePointIds", []) else 1,
                "rationale": "关键知识点需要交叉证据" if item["id"] in scope.get("crossEvidencePointIds", []) else "覆盖课程知识点",
            }
            for item in scope["knowledgePoints"]
        ],
        "authorized_sources": public_sources,
    })
    try:
        generated_result = await execute_registered_structured_call(
            session,
            backend=llm,
            capability=Capability.QUIZ,
            system_prompt=generator_system,
            user_prompt=generator_prompt,
            role="入学诊断出题",
            operation="p1_b05_diagnostic_generate",
            response_model=DiagnosticGeneratedSet,
            response_validator=lambda payload: _validate_generated_set(
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
    except M5CapabilityError as exc:
        cause = exc.__cause__
        if isinstance(cause, DiagnosticGenerationError):
            raise cause
        raise DiagnosticGenerationError(
            "diagnostic_model_generation_failed",
            "真实模型未能生成符合题量、题型和来源合同的诊断题组，请重试。",
            status_code=502,
        ) from exc

    reviewer_system = (
        "你是独立的 EduMatrix 诊断题审核员。只输出符合 JSON Schema 的原始 JSON 对象，不要 Markdown。"
        "逐题核对：来源是否直接支持题意和答案、答案是否自洽、难度是否符合给定画像。"
        "任何一题不满足就标记 rejected，整体 status 必须 rejected；不要输出私有思维链，只写公开审核说明。"
        "为确保审核结果完整且可读：必须为每一道题输出恰好一个 items 条目，public_note 控制在 60 字以内，"
        "decision_summary 控制在 120 字以内；只给结论和最短依据，不复述题干或来源原文。"
        f" JSON Schema: {_canonical(DiagnosticReviewBundle.model_json_schema())}"
    )
    reviewer_prompt = _canonical({
        "profile": profile_basis,
        "authorized_sources": public_sources,
        "generated_set": generated.model_dump(mode="json"),
    })
    try:
        review_result = await execute_registered_structured_call(
            session,
            backend=llm,
            capability=Capability.DECISION,
            system_prompt=reviewer_system,
            user_prompt=reviewer_prompt,
            role="入学诊断审核",
            operation="p1_b05_diagnostic_review",
            response_model=DiagnosticReviewBundle,
            response_validator=lambda payload: _validate_review(payload, generated=generated),
            owner_public_id=user.public_id,
            course_id=course.id,
            output_constraints=OutputConstraints(
                format="json",
                max_length=80000,
                source_scope=tuple(item["sourceRefId"] for item in scope["sources"]),
                safety_boundary="Review only public evidence; do not expose private reasoning.",
            ),
        )
        review = DiagnosticReviewBundle.model_validate(review_result.structured_output)
    except M5CapabilityError as exc:
        cause = exc.__cause__
        if isinstance(cause, DiagnosticGenerationError):
            raise cause
        raise DiagnosticGenerationError(
            "diagnostic_model_review_failed",
            "诊断题组未通过真实模型审核，请重试。",
            status_code=502,
        ) from exc
    return generated, review, {
        "model": generated_result.model,
        "generationCallId": generated_result.call_id,
        "reviewCallId": review_result.call_id,
        "profileSnapshotId": profile.id,
        "profileVersion": profile.profile_version,
    }


def generate_diagnostic_blueprint(
    session: Any,
    *,
    user: DBUser,
    request: DiagnosticBlueprintRequest,
    llm: Any,
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
    scope = _generation_scope(
        session,
        course=course,
        profile=profile,
        question_count=requested_count,
        self_rating=self_rating,
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
        )
    if scope.get("coverageGap"):
        raise DiagnosticGenerationError(
            "diagnostic_coverage_incomplete",
            f"当前题量不足以覆盖全部课程知识点，还缺少 {len(scope['coverageGap'])} 个知识点。",
            status_code=422,
        )
    if len(scope["knowledgePoints"]) < 3 or not scope["sources"]:
        raise DiagnosticGenerationError(
            "diagnostic_sources_insufficient",
            "当前课程至少需要 3 个有可定位知识来源的有效知识点，请先补充或解析课程资料。",
        )
    last_generation_error: DiagnosticGenerationError | None = None
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
            if _attempt == 2:
                raise
    else:
        if last_generation_error is not None:
            raise last_generation_error
        raise DiagnosticGenerationError("diagnostic_generation_failed", "诊断题组生成失败，请重试。", status_code=502)

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
        "reviewCallId": model_evidence["reviewCallId"],
        "profileSnapshotId": profile.id,
        "profileVersion": profile.profile_version,
        "profileAdaptationSummary": generated.profile_adaptation_summary,
        "decisionSummary": model_review.decision_summary,
        "selfRating": self_rating,
        "contextSnapshot": {
            "sourceSnapshotVersion": "p1-b08-source.v2",
            "requestedQuestionCount": requested_count,
            "selectedQuestionCount": count,
            "questionCountAdjusted": adjusted,
            "coverageContract": {
                "status": "verified",
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
        "difficultyBands": dict(row.difficulty_bands or {}),
        "coverageContract": ((row.review_decision or {}).get("contextSnapshot") or {}).get("coverageContract") or {},
        "sourceRefs": list(row.source_refs or []),
        "reviewDecision": dict(row.review_decision or {}),
        "generationStages": list(row.generation_stages or []),
        "questions": items,
        "contentHash": row.content_hash,
    }
