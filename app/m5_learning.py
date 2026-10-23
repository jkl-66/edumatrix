"""Versioned plans, confirmed learning paths, and replayable M5 learning events."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
import hashlib
import json
from typing import Any, Literal
import uuid

from pydantic import Field, model_validator

from app.database import (
    DBCourse,
    DBAssessmentQuestion,
    DBAssessmentQuestionVersion,
    DBArtifact,
    DBChapter,
    DBChapterKnowledgePoint,
    DBKnowledgePoint,
    DBLearningEvent,
    DBLearningEventConsumption,
    DBLearningPath,
    DBPathNode,
    DBPlanDraft,
    DBPlanVersion,
    DBProfileSnapshot,
    DBReviewPlan,
    DBSourceRef,
    DBUser,
)
from app.m1_lifecycle import record_audit
from app.m1_profile_evidence import project_learning_event_evidence
from app.learning_aggregation import AGGREGATION_PROCESSOR_VERSION, aggregate_learning_event
from app.m2_contracts import StrictModel
from app.models import resolve_context_ref
from app.schemas import ContextRef, ContextResolution


class M5LearningError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise M5LearningError(code, message)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def resolve_learning_context(
    session: Any, *, user: DBUser, context: ContextRef
) -> ContextResolution:
    """Resolve one canonical context before a course-scoped workflow proceeds."""
    if context.course_id:
        from course_catalog import course_is_selectable
        course = session.get(DBCourse, context.course_id)
        if not course_is_selectable(session, course):
            _fail("course_unavailable", "course is not currently available for selection")
    return resolve_context_ref(session, user=user, context=context)


class PlanNodeSpec(StrictModel):
    node_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}$")
    node_type: Literal["chapter", "artifact", "assessment", "interactive", "review", "extension"]
    target_object_id: str | None = Field(default=None, max_length=64)
    title: str = Field(min_length=1, max_length=256)
    prerequisites: tuple[str, ...] = ()
    resource_status: Literal["existing", "to_generate", "external_dependency"]
    estimate_min_minutes: int = Field(ge=1, le=10080)
    estimate_max_minutes: int = Field(ge=1, le=10080)
    extension_reason: str = Field(default="", max_length=1000)
    difficulty: float | None = Field(default=None, ge=0, le=1)
    rationale: str = Field(default="", max_length=2000)
    required: bool = True
    risk_level: Literal["normal", "high"] = "normal"

    @model_validator(mode="after")
    def valid_estimate_and_target(self) -> "PlanNodeSpec":
        if self.estimate_max_minutes < self.estimate_min_minutes:
            raise ValueError("estimate_max_minutes must be >= estimate_min_minutes")
        if self.node_type == "extension":
            if not self.extension_reason:
                raise ValueError("extension nodes require extension_reason")
        elif not self.target_object_id:
            raise ValueError("formal plan nodes require target_object_id")
        return self


class PlanSpec(StrictModel):
    schema_version: Literal["m5.plan.v1"] = "m5.plan.v1"
    goal: str = Field(min_length=1, max_length=2000)
    deadline: datetime | None = None
    assumptions: tuple[str, ...] = ()
    nodes: tuple[PlanNodeSpec, ...] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def ordered_acyclic_nodes(self) -> "PlanSpec":
        keys = [item.node_key for item in self.nodes]
        if len(keys) != len(set(keys)):
            raise ValueError("plan node keys must be unique")
        seen = set()
        for item in self.nodes:
            if item.node_key in item.prerequisites:
                raise ValueError("plan node cannot depend on itself")
            unknown_or_late = set(item.prerequisites) - seen
            if unknown_or_late:
                raise ValueError(f"prerequisites must reference earlier nodes: {sorted(unknown_or_late)}")
            seen.add(item.node_key)
        return self


LearningEventType = Literal[
    "resource_opened", "reading_started", "reading_threshold",
    "video_started", "video_threshold", "video_completed",
    "explanation_started", "explanation_completed", "note_created",
    "quiz_answered", "code_run", "code_tests_passed",
    "wrong_question_reviewed", "delayed_retest_passed",
    "user_marked_complete", "teacher_confirmed", "misconception_decided",
    "interactive_experiment_completed", "interactive_model_observation_submitted", "feynman_submitted",
    "formal_exam_submitted", "review_completed",
]

EvidenceStatus = Literal["none", "accepted", "rejected"]
CompletionEffect = Literal["none", "progress", "complete"]


@dataclass(frozen=True)
class LearningEventClassification:
    action: str
    evidence_strength: float
    evidence_status: EvidenceStatus
    evidence_reason: str
    mastery_eligible: bool
    completion_effect: CompletionEffect


_ACTIONS: dict[str, str] = {
    "resource_opened": "resource.opened",
    "reading_started": "reading.started",
    "reading_threshold": "reading.threshold_reached",
    "video_started": "video.started",
    "video_threshold": "video.threshold_reached",
    "video_completed": "video.completed",
    "explanation_started": "explanation.started",
    "explanation_completed": "explanation.completed",
    "note_created": "note.created",
    "quiz_answered": "assessment.answered",
    "code_run": "code.ran",
    "code_tests_passed": "code.tests_passed",
    "wrong_question_reviewed": "wrong_question.reviewed",
    "delayed_retest_passed": "assessment.delayed_retest_passed",
    "user_marked_complete": "task.user_marked_complete",
    "teacher_confirmed": "task.teacher_confirmed",
    "misconception_decided": "misconception.decided",
    "interactive_experiment_completed": "experiment.completed",
    "interactive_model_observation_submitted": "interactive_model.observation_submitted",
    "feynman_submitted": "feynman.submitted",
    "formal_exam_submitted": "exam.submitted",
    "review_completed": "review.completed",
}

_PROGRESS_EVENTS = {
    "resource_opened", "reading_started", "reading_threshold",
    "video_started", "video_threshold", "video_completed",
    "explanation_started", "explanation_completed", "note_created",
    "code_run", "wrong_question_reviewed", "user_marked_complete",
    "misconception_decided",
}

_EVIDENCE_RULES: dict[str, tuple[float, frozenset[str]]] = {
    "quiz_answered": (0.55, frozenset({"backend"})),
    "code_tests_passed": (0.80, frozenset({"backend", "sandbox"})),
    "delayed_retest_passed": (0.90, frozenset({"backend"})),
    "teacher_confirmed": (0.75, frozenset({"teacher"})),
    "interactive_experiment_completed": (0.75, frozenset({"backend", "sandbox"})),
    "interactive_model_observation_submitted": (0.75, frozenset({"backend", "sandbox", "interactive_model"})),
    "feynman_submitted": (0.65, frozenset({"backend"})),
    "formal_exam_submitted": (0.90, frozenset({"backend"})),
    "review_completed": (0.70, frozenset({"backend"})),
}


class LearningEventInput(StrictModel):
    schema_version: Literal["m5.learning-event.v1"] = "m5.learning-event.v1"
    idempotency_key: str = Field(min_length=8, max_length=128)
    event_type: LearningEventType
    context: ContextRef | None = None
    course_id: str | None = Field(default=None, max_length=128)
    object_type: str = Field(min_length=1, max_length=64)
    object_id: str = Field(min_length=1, max_length=64)
    source: Literal[
        "frontend", "backend", "sandbox", "media_player", "teacher", "migration", "interactive_model",
    ]
    payload_version: str = Field(default="1", min_length=1, max_length=32)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def event_specific_fields(self) -> "LearningEventInput":
        if self.event_type in {"reading_threshold", "video_threshold"}:
            if int(self.payload.get("active_seconds", 0)) <= 0:
                raise ValueError("threshold event requires positive active_seconds")
        if self.event_type == "quiz_answered" and self.payload.get("correct") is not None:
            if not isinstance(self.payload.get("correct"), bool):
                raise ValueError("quiz_answered correct must be boolean")
            confidence = self.payload.get("confidence")
            if confidence is not None and not 0 <= float(confidence) <= 1:
                raise ValueError("quiz confidence must be within [0,1]")
        if self.event_type == "code_tests_passed":
            passed = int(self.payload.get("passed_count", 0))
            total = int(self.payload.get("total_count", 0))
            if total < 1 or passed < 0 or passed > total:
                raise ValueError("code_tests_passed requires valid test counts")
        if self.event_type == "misconception_decided":
            if self.payload.get("evidence_kind") != "user_statement":
                raise ValueError("misconception_decided requires user_statement evidence")
            if self.payload.get("decision") not in {"accept", "modify", "reject"}:
                raise ValueError("misconception_decided requires an explicit learner decision")
        return self


def _semantic_rejection(event: LearningEventInput) -> str:
    payload = event.payload
    if event.event_type == "quiz_answered":
        if payload.get("graded") is not True or not isinstance(payload.get("correct"), bool):
            return "题目证据必须来自服务端完成的正式判分"
        if not payload.get("attempt_id"):
            return "题目证据缺少可追溯作答记录"
    elif event.event_type == "code_tests_passed":
        passed = int(payload.get("passed_count", 0))
        total = int(payload.get("total_count", 0))
        if total < 1 or passed != total or payload.get("test_scope") not in {"hidden", "required"}:
            return "代码证据必须通过全部隐藏或必需测试"
        if not payload.get("attempt_id") and not payload.get("run_id"):
            return "代码证据缺少可追溯运行记录"
    elif event.event_type == "delayed_retest_passed":
        if (
            payload.get("correct") is not True
            or float(payload.get("delay_hours", 0)) < 24
            or not payload.get("attempt_id")
        ):
            return "延迟复测证据必须在至少24小时后正确完成并关联作答记录"
    elif event.event_type == "teacher_confirmed":
        if not payload.get("scope") or not payload.get("teacher_public_id"):
            return "教师确认必须包含确认范围和教师身份"
    elif event.event_type == "interactive_experiment_completed":
        passed = int(payload.get("passed_checks", 0))
        total = int(payload.get("total_checks", 0))
        if total < 1 or passed != total or not payload.get("run_id"):
            return "交互实验证据必须通过全部检查并关联运行记录"
    elif event.event_type == "interactive_model_observation_submitted":
        if not str(payload.get("observation") or "").strip():
            return "interactive model evidence requires a traceable observation"
    elif event.event_type == "feynman_submitted":
        score = payload.get("rubric_score")
        if not payload.get("evaluation_id") or score is None or not 0 <= float(score) <= 1:
            return "费曼复述证据必须关联评分记录和有效量表分数"
    elif event.event_type == "formal_exam_submitted":
        if payload.get("graded") is not True or not payload.get("attempt_id"):
            return "正式组卷证据必须完成交卷、判分并关联作答记录"
    elif event.event_type == "review_completed":
        score = payload.get("recall_score")
        if not payload.get("review_id") or score is None or not 0 <= float(score) <= 1:
            return "复习证据必须关联复习任务和有效回忆结果"
    return ""


def classify_learning_event(
    event: LearningEventInput, *, trusted_source: bool,
) -> LearningEventClassification:
    action = _ACTIONS[event.event_type]
    rule = _EVIDENCE_RULES.get(event.event_type)
    if rule is None:
        return LearningEventClassification(
            action=action,
            evidence_strength=0.0,
            evidence_status="none",
            evidence_reason="普通学习活动不作为掌握证据",
            mastery_eligible=False,
            completion_effect="progress" if event.event_type in _PROGRESS_EVENTS else "none",
        )
    strength, allowed_sources = rule
    if not trusted_source or event.source not in allowed_sources:
        return LearningEventClassification(
            action=action,
            evidence_strength=0.0,
            evidence_status="rejected",
            evidence_reason="该证据必须由受信任的判分、沙盒、实验或教师流程提交",
            mastery_eligible=False,
            completion_effect="none",
        )
    rejection = _semantic_rejection(event)
    if rejection:
        return LearningEventClassification(
            action=action,
            evidence_strength=0.0,
            evidence_status="rejected",
            evidence_reason=rejection,
            mastery_eligible=False,
            completion_effect="none",
        )
    return LearningEventClassification(
        action=action,
        evidence_strength=strength,
        evidence_status="accepted",
        evidence_reason="已通过来源与证据完整性校验",
        mastery_eligible=True,
        completion_effect="complete",
    )


def _validate_plan_targets(session: Any, *, owner_public_id: str, course_id: str | None, spec: PlanSpec) -> None:
    for node in spec.nodes:
        if node.node_type == "extension":
            continue
        if node.node_type == "chapter":
            chapter = session.query(DBChapter).filter_by(id=node.target_object_id).first()
            if chapter is None or (course_id and chapter.course_id != course_id):
                _fail("plan_chapter_invalid", f"chapter is not in the confirmed course: {node.node_key}")
            continue
        if node.node_type == "assessment":
            version = session.query(DBAssessmentQuestionVersion).filter_by(id=node.target_object_id).first()
            question = (
                session.query(DBAssessmentQuestion).filter_by(id=version.question_id).first()
                if version is not None else None
            )
            if version is None or question is None:
                _fail("plan_assessment_invalid", f"assessment version is unavailable: {node.node_key}")
            if question.owner_public_id != owner_public_id and (
                question.status != "approved" or not question.course_id
            ):
                _fail("plan_assessment_invalid", f"assessment version is unavailable: {node.node_key}")
            if course_id and question.course_id not in {None, course_id}:
                _fail("plan_assessment_invalid", f"assessment belongs to another course: {node.node_key}")
            continue
        artifact = session.query(DBArtifact).filter_by(id=node.target_object_id).first()
        if artifact is None or artifact.owner_public_id != owner_public_id:
            _fail("plan_artifact_invalid", f"artifact is unavailable to the plan owner: {node.node_key}")
        if course_id and artifact.course_id not in {None, course_id}:
            _fail("plan_artifact_invalid", f"artifact belongs to another course: {node.node_key}")


def _add_version(
    session: Any,
    *,
    plan: DBPlanDraft,
    spec: PlanSpec,
    actor_public_id: str,
    profile_snapshot_id: str | None,
) -> DBPlanVersion:
    latest = session.query(DBPlanVersion).filter_by(plan_draft_id=plan.id).order_by(
        DBPlanVersion.version_number.desc(),
    ).first()
    payload = spec.model_dump(mode="json")
    version = DBPlanVersion(
        plan_draft_id=plan.id,
        version_number=(latest.version_number + 1) if latest else 1,
        profile_snapshot_id=profile_snapshot_id,
        content=payload,
        content_hash=_hash(payload),
        created_by_public_id=actor_public_id,
    )
    session.add(version)
    session.flush()
    plan.current_version_id = version.id
    return version


def create_plan_draft(
    session: Any,
    *,
    owner_public_id: str,
    course_id: str | None,
    title: str,
    idempotency_key: str,
    spec: PlanSpec,
    profile_snapshot_id: str | None = None,
    actor_public_id: str | None = None,
) -> tuple[DBPlanDraft, DBPlanVersion, bool]:
    actor_public_id = actor_public_id or owner_public_id
    if course_id:
        from course_catalog import course_is_selectable
        if not course_is_selectable(session, session.get(DBCourse, course_id)):
            _fail("course_unavailable", "course is not currently available for selection")
    _validate_plan_targets(session, owner_public_id=owner_public_id, course_id=course_id, spec=spec)
    existing = session.query(DBPlanDraft).filter_by(
        owner_public_id=owner_public_id, idempotency_key=idempotency_key,
    ).first()
    if existing is not None:
        version = session.query(DBPlanVersion).filter_by(id=existing.current_version_id).first()
        if (
            version is None or version.content_hash != _hash(spec.model_dump(mode="json"))
            or existing.title != title or existing.course_id != course_id
        ):
            _fail("plan_idempotency_conflict", "idempotency key is bound to another plan draft")
        return existing, version, False
    plan = DBPlanDraft(
        owner_public_id=owner_public_id,
        course_id=course_id,
        title=title,
        status="draft",
        idempotency_key=idempotency_key,
    )
    session.add(plan)
    session.flush()
    version = _add_version(
        session, plan=plan, spec=spec, actor_public_id=actor_public_id,
        profile_snapshot_id=profile_snapshot_id,
    )
    record_audit(
        session, actor_public_id=actor_public_id, action="plan.draft_created",
        object_type="plan_draft", object_id=plan.id,
        metadata={"version_id": version.id, "node_count": len(spec.nodes)},
    )
    session.flush()
    return plan, version, True


def plan_version_diff(left: DBPlanVersion, right: DBPlanVersion) -> dict[str, Any]:
    left_nodes = {item["node_key"]: (index, item) for index, item in enumerate(left.content.get("nodes", []))}
    right_nodes = {item["node_key"]: (index, item) for index, item in enumerate(right.content.get("nodes", []))}
    added = sorted(set(right_nodes) - set(left_nodes))
    removed = sorted(set(left_nodes) - set(right_nodes))
    moved = sorted(
        key for key in set(left_nodes) & set(right_nodes)
        if left_nodes[key][0] != right_nodes[key][0]
    )
    changed = sorted(
        key for key in set(left_nodes) & set(right_nodes)
        if left_nodes[key][1] != right_nodes[key][1]
    )
    return {
        "from_version_id": left.id,
        "to_version_id": right.id,
        "added": added,
        "removed": removed,
        "moved": moved,
        "changed": changed,
        "deadline_changed": left.content.get("deadline") != right.content.get("deadline"),
    }


def propose_plan_revision(
    session: Any,
    *,
    plan: DBPlanDraft,
    owner_public_id: str,
    expected_lock_version: int,
    spec: PlanSpec,
    profile_snapshot_id: str | None = None,
) -> tuple[DBPlanVersion, dict[str, Any]]:
    if plan.owner_public_id != owner_public_id:
        _fail("plan_forbidden", "plan belongs to another owner")
    if plan.lock_version != expected_lock_version:
        _fail("plan_version_conflict", "plan lock version changed")
    if plan.status not in {"draft", "confirmed", "replan_pending"}:
        _fail("plan_not_revisable", f"cannot revise plan from {plan.status}")
    _validate_plan_targets(session, owner_public_id=owner_public_id, course_id=plan.course_id, spec=spec)
    previous = session.query(DBPlanVersion).filter_by(id=plan.current_version_id).one()
    version = _add_version(
        session, plan=plan, spec=spec, actor_public_id=owner_public_id,
        profile_snapshot_id=profile_snapshot_id,
    )
    diff = plan_version_diff(previous, version)
    plan.status = "draft" if plan.confirmed_version_id is None else "replan_pending"
    plan.lock_version += 1
    record_audit(
        session, actor_public_id=owner_public_id, action="plan.revision_proposed",
        object_type="plan_draft", object_id=plan.id,
        metadata={"version_id": version.id, "diff": diff},
    )
    session.flush()
    return version, diff


def _publish_path(
    session: Any, *, plan: DBPlanDraft, version: DBPlanVersion, previous_path: DBLearningPath | None,
) -> DBLearningPath:
    spec = PlanSpec.model_validate(version.content)
    path = DBLearningPath(
        owner_public_id=plan.owner_public_id,
        course_id=plan.course_id,
        source_plan_version_id=version.id,
        supersedes_path_id=previous_path.id if previous_path else None,
        status="active",
    )
    session.add(path)
    session.flush()
    for sequence, node in enumerate(spec.nodes, start=1):
        session.add(DBPathNode(
            learning_path_id=path.id,
            node_key=node.node_key,
            sequence=sequence,
            node_type=node.node_type,
            target_object_id=node.target_object_id,
            title=node.title,
            prerequisites=list(node.prerequisites),
            is_extension=node.node_type == "extension",
            resource_status=node.resource_status,
            estimate_min_minutes=node.estimate_min_minutes,
            estimate_max_minutes=node.estimate_max_minutes,
        ))
    session.flush()
    return path


def confirm_plan(
    session: Any,
    *,
    plan: DBPlanDraft,
    owner_public_id: str,
    expected_lock_version: int,
    actor_public_id: str | None = None,
) -> DBLearningPath:
    actor_public_id = actor_public_id or owner_public_id
    if plan.owner_public_id != owner_public_id:
        _fail("plan_forbidden", "plan belongs to another owner")
    if plan.lock_version != expected_lock_version:
        _fail("plan_version_conflict", "plan lock version changed")
    if plan.status not in {"draft", "replan_pending"}:
        _fail("plan_not_confirmable", f"cannot confirm plan from {plan.status}")
    version = session.query(DBPlanVersion).filter_by(id=plan.current_version_id).one()
    _validate_plan_targets(
        session, owner_public_id=owner_public_id, course_id=plan.course_id,
        spec=PlanSpec.model_validate(version.content),
    )
    previous = session.query(DBLearningPath).join(
        DBPlanVersion, DBPlanVersion.id == DBLearningPath.source_plan_version_id,
    ).filter(
        DBLearningPath.owner_public_id == owner_public_id,
        DBLearningPath.course_id == plan.course_id,
        DBPlanVersion.plan_draft_id == plan.id,
        DBLearningPath.status.in_(("active", "paused")),
    ).order_by(DBLearningPath.created_at.desc()).first()
    if previous is not None:
        previous.status = "archived"
        previous.archived_at = _now()
        previous.lock_version += 1
    path = _publish_path(session, plan=plan, version=version, previous_path=previous)
    plan.status = "confirmed"
    plan.confirmed_version_id = version.id
    plan.confirmed_at = _now()
    plan.lock_version += 1
    record_audit(
        session, actor_public_id=actor_public_id, action="plan.confirmed",
        object_type="plan_draft", object_id=plan.id,
        metadata={"version_id": version.id, "path_id": path.id, "supersedes_path_id": path.supersedes_path_id},
    )
    session.flush()
    return path


def transition_path(
    session: Any,
    *,
    path: DBLearningPath,
    owner_public_id: str,
    target_status: Literal["active", "paused", "archived"],
    expected_lock_version: int,
) -> DBLearningPath:
    if path.owner_public_id != owner_public_id:
        _fail("path_forbidden", "path belongs to another owner")
    if path.lock_version != expected_lock_version:
        _fail("path_version_conflict", "path lock version changed")
    allowed = {
        "active": {"paused", "archived"},
        "paused": {"active", "archived"},
        "completed": {"archived"},
        "archived": set(),
    }
    if target_status == path.status:
        return path
    if target_status not in allowed.get(path.status, set()):
        _fail("path_transition_invalid", f"cannot transition {path.status} to {target_status}")
    path.status = target_status
    path.lock_version += 1
    path.updated_at = _now()
    path.paused_at = _now() if target_status == "paused" else None
    if target_status == "archived":
        path.archived_at = _now()
    record_audit(
        session, actor_public_id=owner_public_id, action=f"learning_path.{target_status}",
        object_type="learning_path", object_id=path.id,
    )
    session.flush()
    return path


def record_learning_event(
    session: Any,
    *,
    owner_public_id: str,
    event: LearningEventInput,
    user: DBUser | None = None,
    trusted_source: bool = False,
) -> tuple[DBLearningEvent, bool]:
    effective_source = event.source if trusted_source else "frontend"
    effective_event = event.model_copy(update={"source": effective_source})
    course_id = effective_event.course_id
    if effective_event.context is not None:
        if user is not None:
            resolution = resolve_learning_context(
                session, user=user, context=effective_event.context,
            )
            context_ref = resolution.context.model_dump(mode="json", by_alias=True)
            course_id = resolution.context.course_id
        else:
            context_ref = effective_event.context.model_dump(mode="json", by_alias=True)
            course_id = effective_event.context.course_id or course_id
        if effective_event.course_id and effective_event.course_id != course_id:
            _fail("learning_event_context_conflict", "event course disagrees with ContextRef")
    else:
        context_ref = ContextRef(
            userId=owner_public_id,
            courseId=course_id,
        ).model_dump(mode="json", by_alias=True)
    classification = classify_learning_event(
        effective_event, trusted_source=trusted_source,
    )
    occurred_at = effective_event.occurred_at
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    occurred_at = occurred_at.astimezone(timezone.utc).replace(tzinfo=None)
    submitted = {
        "schema_version": effective_event.schema_version,
        "idempotency_key": effective_event.idempotency_key,
        "event_type": effective_event.event_type,
        "context": context_ref,
        "course_id": course_id,
        "object_type": effective_event.object_type,
        "object_id": effective_event.object_id,
        "source": effective_source,
        "payload_version": effective_event.payload_version,
        "occurred_at": occurred_at.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
        "payload": effective_event.payload,
    }
    existing = session.query(DBLearningEvent).filter_by(
        owner_public_id=owner_public_id,
        idempotency_key=effective_event.idempotency_key,
    ).first()
    if existing is not None:
        existing_payload = {
            "schema_version": existing.schema_version,
            "idempotency_key": existing.idempotency_key,
            "event_type": existing.event_type,
            "context": existing.context_ref or ContextRef(
                userId=existing.owner_public_id,
                courseId=existing.course_id,
            ).model_dump(mode="json", by_alias=True),
            "course_id": existing.course_id,
            "object_type": existing.object_type,
            "object_id": existing.object_id,
            "source": existing.source,
            "payload_version": existing.payload_version or "1",
            "occurred_at": existing.occurred_at.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
            "payload": existing.payload or {},
        }
        if _hash(existing_payload) != _hash(submitted):
            _fail("learning_event_idempotency_conflict", "event idempotency key is bound to different data")
        project_learning_event_evidence(session, existing)
        return existing, False
    row = DBLearningEvent(
        owner_public_id=owner_public_id,
        course_id=course_id,
        event_type=effective_event.event_type,
        schema_version=effective_event.schema_version,
        idempotency_key=effective_event.idempotency_key,
        source=effective_source,
        trace_id=f"learn-{uuid.uuid4().hex}",
        object_type=effective_event.object_type,
        object_id=effective_event.object_id,
        action=classification.action,
        context_ref=context_ref,
        evidence_strength=classification.evidence_strength,
        evidence_status=classification.evidence_status,
        evidence_reason=classification.evidence_reason,
        mastery_eligible=classification.mastery_eligible,
        completion_effect=classification.completion_effect,
        payload_version=effective_event.payload_version,
        payload=effective_event.payload,
        occurred_at=occurred_at,
    )
    session.add(row)
    session.flush()
    project_learning_event_evidence(session, row)
    return row, True


def process_path_event(
    session: Any,
    *,
    event: DBLearningEvent,
    processor_version: str = AGGREGATION_PROCESSOR_VERSION,
) -> DBLearningEventConsumption:
    return aggregate_learning_event(
        session,
        event=event,
        processor_version=processor_version,
    )


def _completion_criteria(node_type: str) -> str:
    return {
        "chapter": "阅读章节并完成一项学习检查。",
        "interactive": "完成交互实验并提交一次有效结果。",
        "assessment": "提交作答并查看解析。",
        "artifact": "打开资源并完成对应学习动作。",
        "review": "先回顾该知识点的授权资源，再完成一次智能组卷并提交服务端判分结果。",
    }.get(node_type, "完成任务并提交结果。")


def _generation_context(
    session: Any,
    *,
    owner_public_id: str,
    course_id: str,
    node: DBPathNode,
) -> dict[str, Any]:
    """Resolve the immutable inputs needed by the resource bundle request."""
    context: dict[str, Any] = {
        "knowledge_point_id": None,
        "knowledge_point_title": "",
        "source_ref_ids": [],
        "source_refs": [],
        "profile_snapshot_id": None,
        "profile_version": None,
        "profile_influence": [],
        "path_version_id": None,
        "ready": False,
        "block_reason": "当前路径节点还没有可用的课程知识点、来源或画像快照。",
    }
    if node.node_type != "chapter" or not node.target_object_id:
        context["block_reason"] = "只有绑定课程章节的路径节点可以生成完整资源包。"
        return context

    chapter = session.query(DBChapter).filter_by(id=node.target_object_id, course_id=course_id).first()
    if chapter is None:
        context["block_reason"] = "当前路径节点对应的课程章节不存在。"
        return context
    knowledge_point = (
        session.query(DBKnowledgePoint)
        .join(DBChapterKnowledgePoint, DBChapterKnowledgePoint.knowledge_point_id == DBKnowledgePoint.id)
        .filter(DBChapterKnowledgePoint.chapter_id == chapter.id)
        .order_by(DBKnowledgePoint.title, DBKnowledgePoint.id)
        .first()
    )
    source_refs = session.query(DBSourceRef).filter_by(chapter_id=chapter.id).order_by(
        DBSourceRef.location_index, DBSourceRef.id,
    ).all()
    snapshots = session.query(DBProfileSnapshot).filter_by(owner_public_id=owner_public_id).order_by(
        DBProfileSnapshot.created_at.desc(), DBProfileSnapshot.id.desc(),
    ).all()
    profile = next(
        (
            row for row in snapshots
            if (row.snapshot or {}).get("course_id") in {None, course_id}
        ),
        None,
    )
    from app.profile_onboarding import profile_influence_summary
    context.update({
        "knowledge_point_id": knowledge_point.id if knowledge_point else None,
        "knowledge_point_title": knowledge_point.title if knowledge_point else "",
        "source_ref_ids": [row.id for row in source_refs],
        "source_refs": [{
            "id": row.id,
            "location_kind": row.location_kind,
            "location_label": row.location_label,
            "page_number": row.page_number,
        } for row in source_refs],
        "profile_snapshot_id": profile.id if profile else None,
        "profile_version": profile.profile_version if profile else None,
        "profile_influence": profile_influence_summary(profile),
        "path_version_id": node.learning_path_id,
    })
    missing = []
    if knowledge_point is None:
        missing.append("知识点")
    if not source_refs:
        missing.append("课程来源")
    if profile is None:
        missing.append("画像快照")
    context["ready"] = not missing
    context["block_reason"] = "" if not missing else f"还缺少：{'、'.join(missing)}。"
    return context


def _profile_for_schedule(
    session: Any, *, owner_public_id: str, course_id: str | None,
    preferred_snapshot_id: str | None = None,
) -> DBProfileSnapshot | None:
    """Return the owner-scoped profile snapshot used to explain a schedule."""
    if preferred_snapshot_id:
        candidate = session.get(DBProfileSnapshot, preferred_snapshot_id)
        if candidate is not None and candidate.owner_public_id == owner_public_id:
            snapshot_course = (candidate.snapshot or {}).get("course_id")
            if snapshot_course in {None, course_id}:
                return candidate
    rows = session.query(DBProfileSnapshot).filter_by(
        owner_public_id=owner_public_id,
    ).order_by(DBProfileSnapshot.created_at.desc(), DBProfileSnapshot.id.desc()).all()
    return next(
        (
            row for row in rows
            if (row.snapshot or {}).get("course_id") in {None, course_id}
        ),
        None,
    )


def _schedule_profile_projection(snapshot: DBProfileSnapshot | None) -> dict[str, Any]:
    body = dict(snapshot.snapshot or {}) if snapshot is not None else {}
    projection = dict(body.get("profile_projection") or {})
    mastery = body.get("mastery_by_knowledge_point") or {}
    if not isinstance(mastery, dict):
        mastery = {}
    weak_ids = {str(item) for item in body.get("weak_knowledge_point_ids") or []}
    mastered_ids = {str(item) for item in body.get("mastered_knowledge_point_ids") or []}
    unknown_ids = {str(item) for item in body.get("unknown_knowledge_point_ids") or []}
    preferences = body.get("learning_preferences") or body.get("interaction_preferences")
    if isinstance(preferences, dict):
        preferences = list(preferences.values())
    if isinstance(preferences, str):
        preferences = [preferences]
    if not isinstance(preferences, list):
        preferences = list(projection.get("interaction_preferences") or [])
    time_budget = body.get("time_budget_minutes") or projection.get("time_budget_minutes") or 60
    try:
        time_budget = max(15, min(240, int(time_budget)))
    except (TypeError, ValueError):
        time_budget = 60
    return {
        "snapshot_id": snapshot.id if snapshot is not None else None,
        "snapshot_version": snapshot.profile_version if snapshot is not None else None,
        "mastery": mastery,
        "weak_ids": weak_ids,
        "mastered_ids": mastered_ids,
        "unknown_ids": unknown_ids,
        "preferences": [str(item) for item in preferences if str(item).strip()],
        "time_budget_minutes": time_budget,
    }


def _mastery_state(
    knowledge_point_id: str, *, profile: dict[str, Any],
) -> tuple[str, float | None, str]:
    """Classify only evidence-backed mastery; a score by itself never skips a point."""
    entry = profile["mastery"].get(knowledge_point_id) or {}
    if not isinstance(entry, dict):
        entry = {}
    status = str(entry.get("status") or entry.get("label") or "").lower()
    weak = (
        knowledge_point_id in profile["weak_ids"]
        or status in {"weak", "needs_support", "薄弱", "待加强"}
    )
    unknown = (
        knowledge_point_id in profile["unknown_ids"]
        or not entry
        or status in {"unknown", "未测", ""}
    )
    raw_score = entry.get("score", entry.get("mastery"))
    try:
        score = max(0.0, min(1.0, float(raw_score))) if raw_score is not None else None
    except (TypeError, ValueError):
        score = None
    # A weak flag always wins over a stale/contradictory `known` label. A
    # zero or low score is actionable evidence, not permission to skip.
    if weak:
        return "weak", score, "画像或诊断将该知识点标记为薄弱，优先安排理解与巩固。"
    evidence_count = entry.get("evidence_item_count") or (2 if entry.get("cross_evidence") else 0)
    explicit_mastered = (
        knowledge_point_id in profile["mastered_ids"]
        or status in {"known", "mastered", "completed", "已掌握", "基本掌握"}
        and bool(evidence_count or entry.get("source_ref_ids"))
        and score is not None
        and score >= 0.8
    )
    if explicit_mastered:
        return "mastered", score, "有明确掌握标记和诊断证据，可从新学习任务中跳过。"
    if unknown:
        return "unknown", score, "当前没有足够诊断证据，不跳过该知识点。"
    if score is not None and score < 0.5:
        return "developing", score, "已有部分证据但掌握度偏低，优先安排练习。"
    return "developing", score, "保留在路径中，通过学习行为继续验证掌握度。"


def _schedule_resource_plan(
    *, expected_minutes: int, mastery_state: str, preferences: list[str],
) -> list[dict[str, Any]]:
    preference_text = " ".join(preferences).lower()
    if mastery_state == "weak":
        order = ["learning", "practice", "extension"]
        rationale = "薄弱知识点先理解、再练习，最后才安排拓展。"
    elif any(marker in preference_text for marker in ("代码", "实操", "练习", "案例")):
        order = ["practice", "learning", "extension"]
        rationale = "学习偏好包含实操/案例信号，先给可操作练习，再补充讲解。"
    elif any(marker in preference_text for marker in ("图", "例子", "视频", "视觉")):
        order = ["learning", "practice", "extension"]
        rationale = "学习偏好包含图示/例子信号，先提供理解材料，再安排巩固。"
    else:
        order = ["learning", "practice", "extension"]
        rationale = "没有足够偏好信号，按课程默认的理解—练习—拓展顺序。"
    labels = {
        "learning": ("学习理解", "理解当前知识点的课程内容", "完成重点阅读并能复述核心概念"),
        "practice": ("巩固练习", "用题目或实操作业验证理解", "提交一次练习并获得可追溯结果"),
        "extension": ("拓展迁移", "把知识点迁移到跨章节或真实场景", "完成一个拓展任务或写下迁移结论"),
    }
    weights = {"learning": 0.45, "practice": 0.35, "extension": 0.20}
    return [
        {
            "type": item,
            "label": labels[item][0],
            "explanation": labels[item][1],
            "completion_criteria": labels[item][2],
            "estimate_minutes": max(5, round(expected_minutes * weights[item])),
            "priority": len(order) - index,
            "priority_reason": rationale,
        }
        for index, item in enumerate(order)
    ]


def _completed_node_ids_today(
    session: Any,
    *,
    owner_public_id: str,
    course_id: str | None,
    nodes: list[DBPathNode],
) -> set[str]:
    """Return path nodes backed by an accepted completion event from today."""

    start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    query = session.query(DBLearningEvent).filter(
        DBLearningEvent.owner_public_id == owner_public_id,
        DBLearningEvent.evidence_status == "accepted",
        DBLearningEvent.completion_effect == "complete",
        DBLearningEvent.occurred_at >= start,
        DBLearningEvent.occurred_at < end,
    )
    query = query.filter(
        DBLearningEvent.course_id.is_(None)
        if course_id is None else DBLearningEvent.course_id == course_id
    )
    events = query.order_by(DBLearningEvent.occurred_at, DBLearningEvent.id).all()
    completed: set[str] = set()
    for node in nodes:
        if node.status != "completed":
            continue
        for event in events:
            context = event.context_ref or {}
            payload = event.payload or {}
            if (
                context.get("taskId") == node.id
                or event.object_id == node.target_object_id
                or payload.get("path_node_id") == node.id
                or payload.get("node_id") == node.id
            ):
                completed.add(node.id)
                break
    return completed


def _schedule_course_projection(
    session: Any, *, owner_public_id: str, path: DBLearningPath,
) -> dict[str, Any]:
    from app.profile_onboarding import profile_influence_summary

    course = session.get(DBCourse, path.course_id) if path.course_id else None
    version = session.get(DBPlanVersion, path.source_plan_version_id)
    profile_snapshot_id = getattr(version, "profile_snapshot_id", None)
    snapshot = _profile_for_schedule(
        session,
        owner_public_id=owner_public_id,
        course_id=path.course_id,
        preferred_snapshot_id=profile_snapshot_id,
    )
    profile = _schedule_profile_projection(snapshot)
    nodes = session.query(DBPathNode).filter_by(
        learning_path_id=path.id,
    ).order_by(DBPathNode.sequence, DBPathNode.id).all()
    completed_today = _completed_node_ids_today(
        session,
        owner_public_id=owner_public_id,
        course_id=path.course_id,
        nodes=nodes,
    )
    chapter_ids = [
        str(node.target_object_id) for node in nodes
        if node.node_type == "chapter" and node.target_object_id
    ]
    chapters = {
        chapter.id: chapter for chapter in session.query(DBChapter).filter(
            DBChapter.id.in_(chapter_ids or ["-"]),
        ).all()
    }
    links = session.query(DBChapterKnowledgePoint).filter(
        DBChapterKnowledgePoint.chapter_id.in_(chapter_ids or ["-"]),
    ).all()
    kp_ids_by_chapter: dict[str, list[str]] = {}
    for link in links:
        kp_ids_by_chapter.setdefault(link.chapter_id, []).append(str(link.knowledge_point_id))
    knowledge_points = {
        point.id: point for point in session.query(DBKnowledgePoint).filter(
            DBKnowledgePoint.id.in_(sorted({item for values in kp_ids_by_chapter.values() for item in values}) or ["-"]),
        ).all()
    }
    node_projections: list[dict[str, Any]] = []
    topology_nodes: list[dict[str, Any]] = []
    topology_edges: list[dict[str, Any]] = []
    modules: dict[str, dict[str, Any]] = {}
    for node in nodes:
        kp_ids = kp_ids_by_chapter.get(str(node.target_object_id), [])
        kp_states = [
            _mastery_state(kp_id, profile=profile) for kp_id in kp_ids
        ]
        mastered = bool(kp_states) and all(item[0] == "mastered" for item in kp_states)
        weak = any(item[0] == "weak" for item in kp_states)
        if node.status == "completed":
            state = "completed"
            reason = "已有真实学习事件完成该路径节点。"
        elif mastered and not weak:
            state = "skipped"
            reason = "所有绑定知识点都有明确掌握证据；未测或冲突点不会走这条分支。"
        else:
            state = "pending"
            reason = next((item[2] for item in kp_states if item[0] in {"weak", "unknown", "developing"}), "路径节点没有可用于跳过的掌握证据。")
        expected_minutes = max(1, round((int(node.estimate_min_minutes) + int(node.estimate_max_minutes)) / 2))
        chapter = chapters.get(str(node.target_object_id))
        module_id = str(chapter.parent_id or chapter.id) if chapter else f"module:{node.node_key}"
        module_title = chapters.get(module_id).title if module_id in chapters else (chapter.title if chapter else node.title)
        modules.setdefault(module_id, {"id": module_id, "title": module_title, "node_keys": []})["node_keys"].append(node.node_key)
        knowledge_projection = [
            {
                "id": kp_id,
                "title": knowledge_points[kp_id].title if kp_id in knowledge_points else kp_id,
                "status": kp_states[index][0] if index < len(kp_states) else "unknown",
                "score": kp_states[index][1] if index < len(kp_states) else None,
                "reason": kp_states[index][2] if index < len(kp_states) else "没有足够诊断证据，不跳过该知识点。",
            }
            for index, kp_id in enumerate(kp_ids)
        ]
        resources = _schedule_resource_plan(
            expected_minutes=expected_minutes,
            mastery_state="weak" if weak else ("mastered" if mastered else (kp_states[0][0] if kp_states else "unknown")),
            preferences=profile["preferences"],
        )
        projection = {
            "id": node.id,
            "node_key": node.node_key,
            "sequence": node.sequence,
            "title": node.title,
            "node_type": node.node_type,
            "target_object_id": node.target_object_id,
            "status": state,
            "completed_today": node.id in completed_today,
            "path_status": path.status,
            "prerequisites": list(node.prerequisites or []),
            "module_id": module_id,
            "module_title": module_title,
            "knowledge_points": knowledge_projection,
            "estimate_minutes": expected_minutes,
            "estimate_range": [node.estimate_min_minutes, node.estimate_max_minutes],
            "completion_criteria": _completion_criteria(node.node_type),
            "reason": reason,
            "priority": 0,
            "resources": resources,
            "generation_context": None,
        }
        if node.node_type == "chapter":
            context = _generation_context(
                session,
                owner_public_id=owner_public_id,
                course_id=path.course_id or "",
                node=node,
            )
            context.update({
                "knowledge_point_ids": kp_ids,
                "profile_snapshot_id": profile["snapshot_id"],
                "profile_version": profile["snapshot_version"],
                "schedule_resources": resources,
            })
            projection["generation_context"] = context
        mastery_scores = [item[1] for item in kp_states if item[1] is not None]
        if weak:
            projection["priority"] = 100
        elif any(item[0] == "unknown" for item in kp_states) or not kp_states:
            projection["priority"] = 80
        elif mastery_scores:
            projection["priority"] = round(70 - max(0.0, min(mastery_scores)) * 40)
        else:
            projection["priority"] = 60
        if node.is_extension:
            projection["priority"] = max(10, projection["priority"] - 20)
        node_projections.append(projection)
        topology_nodes.append({
            "id": node.id,
            "node_key": node.node_key,
            "title": node.title,
            "sequence": node.sequence,
            "module_id": module_id,
            "status": state,
            "knowledge_point_ids": kp_ids,
            "prerequisites": list(node.prerequisites or []),
        })
        topology_edges.extend({
            "from": prerequisite,
            "to": node.node_key,
            "type": "path_prerequisite",
        } for prerequisite in (node.prerequisites or []))
    for kp_id, point in knowledge_points.items():
        for prerequisite in point.prerequisites or []:
            if str(prerequisite) in knowledge_points:
                topology_edges.append({
                    "from": str(prerequisite),
                    "to": kp_id,
                    "type": "knowledge_prerequisite",
                })
    return {
        "path_id": path.id,
        "course_id": path.course_id,
        "course": {"id": course.id, "title": course.title, "subject": course.subject} if course else None,
        "status": path.status,
        "lock_version": path.lock_version,
        "source_plan_version_id": path.source_plan_version_id,
        "profile_snapshot_id": profile["snapshot_id"],
        "profile_influence": profile_influence_summary(snapshot),
        "time_budget_minutes": profile["time_budget_minutes"],
        "nodes": node_projections,
        "topology": {
            "nodes": topology_nodes,
            "edges": topology_edges,
            "modules": list(modules.values()),
        },
    }


def multi_course_schedule(
    session: Any, *, owner_public_id: str, course_id: str | None = None,
    selected_day: int = 1, max_days: int = 60,
) -> dict[str, Any]:
    """Project active course paths into D-day work without writing learning state."""
    try:
        selected_day = max(1, int(selected_day))
    except (TypeError, ValueError):
        selected_day = 1
    max_days = max(1, min(60, int(max_days or 60)))
    query = session.query(DBLearningPath).filter(
        DBLearningPath.owner_public_id == owner_public_id,
        DBLearningPath.status.in_(("active", "paused", "completed")),
    )
    if course_id:
        query = query.filter(DBLearningPath.course_id == course_id)
    paths = query.order_by(DBLearningPath.course_id, DBLearningPath.updated_at.desc(), DBLearningPath.id.desc()).all()
    from course_catalog import course_is_selectable
    paths = [
        path for path in paths
        if path.course_id and course_is_selectable(session, session.get(DBCourse, path.course_id))
    ]
    courses = [_schedule_course_projection(session, owner_public_id=owner_public_id, path=path) for path in paths]
    active_courses = [item for item in courses if item["status"] in {"active", "completed"}]
    remaining: dict[str, set[str]] = {
        item["path_id"]: {
            node["node_key"] for node in item["nodes"]
            if node["status"] == "pending" or node.get("completed_today")
        }
        for item in active_courses
    }
    resolved: dict[str, set[str]] = {
        item["path_id"]: {
            node["node_key"] for node in item["nodes"]
            if node["status"] == "skipped" or (node["status"] == "completed" and not node.get("completed_today"))
        }
        for item in active_courses
    }
    by_path = {item["path_id"]: item for item in active_courses}
    completed_today_by_path = {
        item["path_id"]: {
            node["node_key"] for node in item["nodes"] if node.get("completed_today")
        }
        for item in active_courses
    }
    days: list[dict[str, Any]] = []
    day_number = 1
    while remaining and any(remaining.values()) and day_number <= max_days:
        candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for path_id, keys in remaining.items():
            projection = by_path[path_id]
            for node in projection["nodes"]:
                if node["node_key"] not in keys:
                    continue
                prerequisite_keys = set(node["prerequisites"] or [])
                unresolved = prerequisite_keys - resolved[projection["path_id"]]
                if unresolved:
                    continue
                candidates.append((projection, node))
        candidates.sort(key=lambda pair: (-int(pair[1]["priority"]), pair[0]["course_id"] or "", int(pair[1]["sequence"])))
        if day_number == 1:
            completed_today_keys = {
                key for keys in completed_today_by_path.values() for key in keys
            }
            if completed_today_keys:
                existing_keys = {
                    (projection["path_id"], node.get("node_key"))
                    for projection, node in candidates
                }
                candidates.extend(
                    (projection, node)
                    for projection in active_courses
                    for node in projection["nodes"]
                    if node.get("node_key") in completed_today_by_path.get(projection["path_id"], set())
                    and (projection["path_id"], node.get("node_key")) not in existing_keys
                )
                candidates = [
                    pair for pair in candidates
                    if pair[1].get("node_key") in completed_today_keys
                    or not completed_today_keys.intersection(set(pair[1].get("prerequisites") or []))
                ]
                candidates.sort(key=lambda pair: (-int(pair[1]["priority"]), pair[0]["course_id"] or "", int(pair[1]["sequence"])))
        # A time estimate describes the day's workload; it must not hide a
        # course task or turn a valid path node into a locked item.  Select
        # every currently-unblocked candidate and let prerequisites determine
        # the next day.
        selected: list[tuple[dict[str, Any], dict[str, Any]]] = list(candidates)
        if not selected:
            break
        task_payload: list[dict[str, Any]] = []
        for projection, node in selected:
            remaining[projection["path_id"]].discard(node["node_key"])
            resolved[projection["path_id"]].add(node["node_key"])
            node["scheduled_day"] = day_number
            node["generation_context"] = dict(node.get("generation_context") or {})
            node["generation_context"]["schedule_day"] = day_number
            node["generation_context"]["schedule_path_id"] = projection["path_id"]
            task_payload.append({
                **node,
                # A node reaches this branch only after its path prerequisites
                # have been resolved.  Keep the course projection and
                # persistent path node unchanged, but expose this selected
                # day's task as currently learnable to the client.
                "status": "in_progress" if node["status"] == "pending" else node["status"],
                # Keep the persistent path-node identity separate from the
                # display/node key.  Chat path_bundle context validation uses
                # this ID to resolve the authorized path task.
                "node_id": node["id"],
                "course_id": projection["course_id"],
                "course_title": (projection.get("course") or {}).get("title", ""),
                "path_id": projection["path_id"],
                "task_kind": "path",
                "continue_route": f"/workspace?course_id={projection['course_id']}&node_id={node['id']}",
            })
        days.append({
            "day": day_number,
            "date": (_now().date()).isoformat(),
            "tasks": task_payload,
            "total_minutes": sum(int(item["estimate_minutes"]) for item in task_payload),
            "progress": {
                "completed": sum(1 for item in task_payload if item["status"] == "completed"),
                "total": len(task_payload),
            },
        })
        day_number += 1
    for item in days:
        item["date"] = (_now().date() + timedelta(days=int(item["day"]) - 1)).isoformat()
    total_days = max(1, len(days))
    selected = next((item for item in days if item["day"] == min(selected_day, total_days)), None)
    if selected is None:
        selected = {"day": selected_day, "date": (_now().date()).isoformat(), "tasks": [], "total_minutes": 0, "progress": {"completed": 0, "total": 0}}
    return {
        "schema_version": "m5.multi-course-schedule.v1",
        "selected_day": int(selected["day"]),
        "total_days": total_days,
        "days": days,
        "selected": selected,
        "courses": courses,
        "read_only": True,
        "learning_state_written": False,
    }


def today_work_items(
    session: Any, *, owner_public_id: str, course_id: str | None = None, limit: int = 3,
) -> tuple[dict[str, Any], ...]:
    limit = max(1, int(limit or 3))
    query = session.query(DBLearningPath).filter_by(owner_public_id=owner_public_id, status="active")
    if course_id:
        query = query.filter(DBLearningPath.course_id == course_id)
    paths = query.order_by(DBLearningPath.updated_at.desc(), DBLearningPath.id.desc()).all()
    from course_catalog import course_is_selectable
    paths = [
        path for path in paths
        if path.course_id and course_is_selectable(session, session.get(DBCourse, path.course_id))
    ]
    # Keep the Today projection fair when several active courses exist.  A
    # single path can contain many unlocked nodes; appending that path in full
    # before another course would otherwise make the other courses disappear
    # behind the response limit.
    path_items_by_course: dict[str, list[dict[str, Any]]] = {}
    course_titles = {
        row.id: row.title
        for row in session.query(DBCourse).filter(
            DBCourse.id.in_([path.course_id for path in paths if path.course_id]),
        ).all()
    }
    for path in paths:
        nodes = session.query(DBPathNode).filter_by(learning_path_id=path.id).order_by(DBPathNode.sequence).all()
        completed_keys = {item.node_key for item in nodes if item.status == "completed"}
        completed_today = _completed_node_ids_today(
            session,
            owner_public_id=owner_public_id,
            course_id=path.course_id,
            nodes=nodes,
        )
        completed_today_keys = {node.node_key for node in nodes if node.id in completed_today}
        for node in nodes:
            if node.status == "completed" and node.id not in completed_today:
                continue
            if node.status != "completed" and not set(node.prerequisites or []).issubset(completed_keys):
                continue
            if node.status != "completed" and completed_today_keys.intersection(set(node.prerequisites or [])):
                continue
            course_items = path_items_by_course.setdefault(path.course_id, [])
            first_path_item = not course_items
            generation_context = _generation_context(
                session,
                owner_public_id=owner_public_id,
                course_id=path.course_id,
                node=node,
            )
            course_items.append({
                "path_id": path.id,
                "path_version_id": path.source_plan_version_id,
                "course_id": path.course_id,
                "course_title": course_titles.get(path.course_id, ""),
                "node_id": node.id,
                "node_key": node.node_key,
                "title": node.title,
                "status": "completed" if node.status == "completed" else node.status,
                "task_kind": "path",
                "node_type": node.node_type,
                "target_object_id": node.target_object_id,
                "resource_status": node.resource_status,
                "required": not node.is_extension,
                "estimate_minutes": [node.estimate_min_minutes, node.estimate_max_minutes],
                "completion_criteria": _completion_criteria(node.node_type),
                "knowledge_point_id": generation_context["knowledge_point_id"],
                "knowledge_point_title": generation_context["knowledge_point_title"] or node.title,
                "generation_context": generation_context,
                "recommendation_reason": (
                    "正式路径中首个已解锁任务，优先继续以保持学习连续性。"
                    if first_path_item else "该任务的前置条件已满足，可在本次学习时段并行推进。"
                ),
                "continue_route": f"/workspace?node_id={node.id}",
            })
    if not course_id:
        # Round-robin by course so every active course contributes visible
        # work before a long path consumes the whole projection.
        interleaved: list[dict[str, Any]] = []
        course_keys = list(path_items_by_course)
        offset = 0
        while len(interleaved) < limit and course_keys:
            added = False
            for course_key in course_keys:
                items = path_items_by_course[course_key]
                if offset < len(items):
                    interleaved.append(items[offset])
                    added = True
                    if len(interleaved) >= limit:
                        break
            if not added:
                break
            offset += 1
        return tuple(interleaved)

    path_items = [item for items in path_items_by_course.values() for item in items]

    user = session.query(DBUser).filter_by(public_id=owner_public_id).first()
    chapter_ids = [
        row[0] for row in session.query(DBChapter.id).filter_by(course_id=course_id).all()
    ]
    course_kp_ids = {
        row[0] for row in session.query(DBChapterKnowledgePoint.knowledge_point_id).filter(
            DBChapterKnowledgePoint.chapter_id.in_(chapter_ids or ["-"]),
        ).all()
    }
    points = session.query(DBKnowledgePoint).filter(
        DBKnowledgePoint.id.in_(course_kp_ids or ["-"]),
    ).all()
    point_by_alias: dict[str, str] = {}
    titles: dict[str, str] = {}
    for point in points:
        titles[point.id] = point.title
        for alias in (point.id, point.code, point.title):
            if alias:
                point_by_alias[str(alias).strip().casefold()] = point.id
    reviews = session.query(DBReviewPlan).filter_by(
        student_id=user.username if user else "",
    ).order_by(DBReviewPlan.priority, DBReviewPlan.next_review_at, DBReviewPlan.id).all()
    due_reviews_by_point: dict[str, list[DBReviewPlan]] = {}
    for review in reviews:
        if review.next_review_at is not None and review.next_review_at > _now():
            continue
        point_id = point_by_alias.get(str(review.concept or "").strip().casefold())
        if point_id:
            due_reviews_by_point.setdefault(point_id, []).append(review)

    course = session.get(DBCourse, course_id)
    output: list[dict[str, Any]] = []
    used_review_ids: set[int] = set()

    def review_item(review: DBReviewPlan, point_id: str, path: DBLearningPath | None) -> dict[str, Any]:
        title = titles.get(point_id, str(review.concept or point_id))
        review_task_id = f"review-plan:{review.id}"
        return {
            "path_id": path.id if path else None,
            "path_version_id": path.source_plan_version_id if path else None,
            "course_id": course_id,
            "course_title": course.title if course else "",
            "node_id": f"review-{review.id}",
            "node_key": f"review-{review.id}",
            "title": f"复习：{title}",
            "status": "due",
            "task_kind": "review",
            "node_type": "review",
            "target_object_id": str(review.id),
            "knowledge_point_id": point_id,
            "knowledge_point_title": title,
            "resource_status": "existing",
            "required": True,
            "estimate_minutes": [10, 15],
            "completion_criteria": _completion_criteria("review"),
            "recommendation_reason": f"新学任务后安排该知识点复习，当前计划优先级 {float(review.priority or 1.0):.2f}。",
            "continue_route": f"/workspace/review?review_task={review_task_id}&course_id={course_id}",
            "review_task_id": review_task_id,
            "review_flow": {
                "sequence": ["resource_review", "intelligent_assessment", "submit"],
                "resource_review": {
                    "required": True,
                    "status": "pending",
                    "course_id": course_id,
                    "knowledge_point_id": point_id,
                },
                "assessment": {
                    "required": True,
                    "status": "pending",
                    "mode": "practice",
                    "course_id": course_id,
                    "knowledge_point_id": point_id,
                },
                "completion_requires_assessment": True,
            },
        }

    for item in path_items:
        if len(output) >= limit:
            break
        output.append(item)
        context = item.get("generation_context") or {}
        point_id = str(context.get("knowledge_point_id") or "")
        current_path = next((path for path in paths if path.id == item.get("path_id")), None)
        for review in due_reviews_by_point.get(point_id, []):
            if len(output) >= limit:
                break
            output.append(review_item(review, point_id, current_path))
            used_review_ids.add(review.id)

    if len(output) < limit:
        for point_id, point_reviews in due_reviews_by_point.items():
            for review in point_reviews:
                if review.id in used_review_ids:
                    continue
                output.append(review_item(review, point_id, paths[0] if paths else None))
                used_review_ids.add(review.id)
                if len(output) >= limit:
                    break
            if len(output) >= limit:
                break

    return tuple(output[:limit])
