"""Authenticated M5 capability discovery and route preflight API."""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from urllib.parse import quote
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import Field

from app.auth import get_current_user
from app.authorization import ObjectAccess, active_course_role, require_object_access
from app.database import (
    DBAssessmentAbilityState,
    DBAssessmentAttempt,
    DBAssessmentGradingResult,
    DBAssessmentExam,
    DBAssessmentExamReport,
    DBAssessmentExamResponse,
    DBAssessmentExamSitting,
    DBAssessmentExamVersion,
    DBAssessmentReviewCase,
    DBAssessmentQuestion,
    DBAssessmentQuestionVersion,
    DBAssessmentRetestTask,
    DBMisconceptionReview,
    DBAuditLog,
    DBArtifact,
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
    DBCourseMembership,
    DBKnowledgePoint,
    DBLearningEvent,
    DBLearningPath,
    DBPathNode,
    DBPlanDraft,
    DBPlanVersion,
    DBSourceDocument,
    DBSourceRef,
    DBTutorContextSession,
    DBReviewPlan,
    DBUser,
    run_db_op,
)
from app.m1_repository import M1Repository
from app.m2_contracts import StrictModel
from app.m5_capabilities import (
    M5CapabilityError,
    RoutingRequest,
    RuntimeAvailability,
    capability_statuses,
    route_capability,
)
from app.m5_resources import (
    ResourceArchiveRequest,
    ResourceVersionCreateRequest,
    ResourceVersionRestoreRequest,
    compare_resource_versions,
    create_resource_version,
    export_resource_version,
    locate_video_media,
    render_deck_export,
    resource_detail,
    restore_resource_version,
    search_resources,
    set_resource_archived,
    validate_resource_completion,
)
from app.m5_learning import (
    LearningEventInput,
    M5LearningError,
    PlanSpec,
    confirm_plan,
    create_plan_draft,
    plan_version_diff,
    process_path_event,
    propose_plan_revision,
    record_learning_event,
    resolve_learning_context,
    multi_course_schedule,
    today_work_items,
    transition_path,
)
from app.learning_aggregation import (
    LEARNING_FEEDBACK_EVENT_TYPES,
    get_learning_aggregation,
    learning_feedback_payload,
)
from app.dashboard_summary import build_dashboard_summary
from app.models import ContextResolutionError
from app.schemas import ContextRef, ContextResolution, ContextResolveRequest
from app.path_draft import (
    PathDraftError,
    _build_path_model,
    generate_textbook_path_draft,
    textbook_path_draft_payload,
)
from app.m5_assessment import (
    AssessmentEvidenceInput,
    record_canonical_attempt_evidence,
    record_assessment_evidence,
)
from app.m5_assessment_core import (
    AIGradingOutput,
    AssessmentCoreError,
    AttemptInput,
    CatSelectionInput,
    MisconceptionCandidateInput,
    MisconceptionDecisionInput,
    QuestionVersionInput,
    RetestAttemptInput,
    ability_state_payload,
    ai_grading_prompt,
    append_question_version,
    create_question_version,
    decide_misconception,
    ensure_legacy_misconception_candidate,
    grade_code_submission,
    grading_result_payload,
    learner_attempt_payload,
    learner_correct_answer,
    learner_safe_explanation,
    learner_safe_prompt,
    learner_question_payload,
    misconception_review_payload,
    persist_ai_grading,
    persist_code_grading,
    persist_failed_ai_grading,
    propose_misconception,
    project_misconception_decision,
    record_attempt,
    retest_task_payload,
    review_queue,
    schedule_delayed_retest,
    select_cat_question,
    submit_delayed_retest,
)
from app.m5_exam_core import (
    ExamCreateInput, ExamItemInput, FormalExamError, FormalResponseInput, HumanReviewInput,
    IntelligentExamConfigInput,
    assign_sitting, complete_human_review, create_exam, exam_payload,
    build_intelligent_exam_input, finalize_formal_response_drafts, formal_draft_payload,
    generate_report, intelligent_exam_context, latest_formal_response_drafts,
    report_csv, request_review, save_formal_response_draft, sitting_payload,
    start_sitting, submit_formal_response, submit_sitting, transition_exam,
)
from app.exam_gate import ExamGateError, exam_gate_status, require_exam_gate
from code_exec_api import SANDBOX_RUNNER
from quiz_api import _call_quiz_model
from llm_client import build_async_llm
from swarm_factory import build_swarm_from_headers
from app.m5_tasks import (
    M5TaskError,
    create_capability_task,
    resume_capability_task,
    retry_capability_step,
    schedule_capability_rework,
    start_capability_task,
)
from app.m5_operations import (
    OperationsError,
    PriceVersionInput,
    WorkerClaimInput,
    WorkerHeartbeatInput,
    cancel_task,
    claim_next_task,
    heartbeat_lease,
    operations_dashboard,
    pricing_payload,
    recover_expired_leases,
    register_price_version,
    release_lease,
)
from app.m5_workspace import (
    M5WorkspaceError,
    TutorContextSpec,
    TutorPromptPreflight,
    archive_tutor_context,
    create_tutor_context,
    tutor_context_payload,
    tutor_prompt_envelope,
    workspace_overview,
)
from app.profile_summary import (
    ProfileSummaryError,
    build_personal_activity,
    build_profile_summary,
)
from app.workspace_actions import (
    WorkspaceActionError,
    WorkspaceActionRequest,
    execute_workspace_action,
)
from app.workspace_timeline import (
    WorkspaceTimelineError,
    build_workspace_task_timeline,
)
from app.workspace_local_executor import (
    WorkspaceLocalExecutionError,
    execute_deterministic_workspace_task,
)
from config import CONFIG
from app.identity import normalize_role
from app.model_call_governance import governance_summary, scan_model_calls
from app.legacy_migration_governance import (
    LegacyMigrationError,
    legacy_governance_summary,
    legacy_object_migrations,
    migrate_legacy_object,
    migration_runtime_summary,
    rollback_legacy_object,
)


router = APIRouter(prefix="/api/v1/m5", tags=["m5-capabilities"])
ROOT = Path(__file__).resolve().parents[1]


def _local_assessment_demo_mode() -> bool:
    return (
        CONFIG.demo_mode
        and str(CONFIG.llm_provider).strip().lower() == "deterministic"
        and str(CONFIG.llm_model).strip().lower() == "deterministic"
    )


def _build_governed_assessment_llm():
    """Build the live model route, or the explicit local-demo blueprint route."""
    if _local_assessment_demo_mode():
        return None
    return build_async_llm(
        CONFIG,
        model="deepseek-v4-flash",
        thinking_mode="enabled",
        reasoning_effort="max",
        allow_fallback=False,
    )


def _require_model_operator(user: DBUser) -> None:
    if normalize_role(user.role) not in {"admin", "teacher"}:
        raise HTTPException(
            status_code=403,
            detail={"code": "model_governance_operator_required", "message": "model governance is restricted to operators"},
        )


def _require_admin(user: DBUser) -> None:
    if normalize_role(user.role) != "admin":
        raise HTTPException(
            status_code=403,
            detail={"code": "model_operations_admin_required", "message": "model operations require an admin role"},
        )


def _operations_error(exc: OperationsError) -> HTTPException:
    if exc.code.endswith("unknown"):
        status = 404
    elif "forbidden" in exc.code:
        status = 403
    elif any(token in exc.code for token in ("conflict", "expired", "not_")):
        status = 409
    else:
        status = 422
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


class CapabilityTaskCreate(StrictModel):
    routing: RoutingRequest
    model: str = ""


class CapabilityTaskRework(StrictModel):
    reason_code: str


class PlanDraftCreate(StrictModel):
    course_id: str | None = None
    title: str
    idempotency_key: str
    profile_snapshot_id: str | None = None
    spec: PlanSpec


class PlanRevisionCreate(StrictModel):
    expected_lock_version: int
    profile_snapshot_id: str | None = None
    spec: PlanSpec


class PlanConfirmRequest(StrictModel):
    expected_lock_version: int


class TextbookPathDraftRequest(StrictModel):
    course_id: str
    time_budget_minutes: int = 90


@router.post("/context/resolve", response_model=ContextResolution)
async def resolve_course_context(
    payload: ContextResolveRequest,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        try:
            return resolve_learning_context(
                session, user=current_user, context=payload.context
            )
        except ContextResolutionError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=exc.detail(),
            ) from exc
        except M5LearningError as exc:
            # Keep the legacy learning-context guard for direct callers, but
            # expose the same structured 4xx contract through this HTTP route.
            if exc.code == "course_unavailable":
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "context_course_unavailable",
                        "message": "这门课程当前没有可用学习资料，或已停止发布",
                        "field": "courseId",
                    },
                ) from exc
            raise _learning_error(exc) from exc

    return await run_db_op(operation)


class PathTransitionRequest(StrictModel):
    expected_lock_version: int
    target_status: Literal["active", "paused", "archived"]


class QuestionCreate(StrictModel):
    course_id: str | None = None
    question_type: Literal["single_choice", "multiple_choice", "true_false", "fill_blank", "short_answer", "code", "open_task"]
    origin: Literal["manual", "textbook", "ai_generated", "derived", "legacy"] = "manual"
    version: QuestionVersionInput


class QuestionRevisionCreate(StrictModel):
    expected_current_version_id: str
    version: QuestionVersionInput


class QuestionStatusUpdate(StrictModel):
    expected_current_version_id: str
    status: Literal["draft", "reviewing", "approved", "retired"]


class ExamTransitionRequest(StrictModel):
    expected_lock_version: int
    target_status: Literal["published", "open", "closed", "archived"]


class IntelligentExamCreateRequest(StrictModel):
    configuration: IntelligentExamConfigInput | None = None
    course_id: str | None = None
    title: str = "今日智能组卷"
    duration_minutes: int = 45
    question_version_ids: tuple[str, ...] = ()


class ExamAssignRequest(StrictModel):
    learner_public_id: str


class SittingTransitionRequest(StrictModel):
    expected_lock_version: int


class ExamReviewRequest(StrictModel):
    attempt_id: str
    reason: str = ""


class HumanReviewRequest(StrictModel):
    expected_lock_version: int
    result: HumanReviewInput


class ResourceCompletionRequest(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    resource_version_id: str = Field(min_length=1, max_length=64)
    completion_rule: str = Field(min_length=1, max_length=512)
    context: dict[str, Any] | None = None
    actual_minutes: int | None = Field(default=None, ge=0, le=10080)


class TutorContextArchiveRequest(StrictModel):
    expected_lock_version: int


class LegacyObjectMigrationRequest(StrictModel):
    owner_public_id: str
    old_type: Literal["profile", "path", "resource", "note", "wrong_question"]
    old_id: str
    version: str = "1"


class LegacyObjectRollbackRequest(StrictModel):
    owner_public_id: str
    rollback_token: str


def _learning_error(exc: M5LearningError) -> HTTPException:
    if exc.code.endswith("unknown"):
        status = 404
    elif "forbidden" in exc.code:
        status = 403
    elif "conflict" in exc.code or "transition" in exc.code or "not_" in exc.code:
        status = 409
    else:
        status = 422
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


def _workspace_error(exc: M5WorkspaceError) -> HTTPException:
    if exc.code.endswith(("unknown", "invalid")):
        status = 404
    elif "forbidden" in exc.code:
        status = 403
    elif "conflict" in exc.code or "archived" in exc.code:
        status = 409
    else:
        status = 422
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


def _workspace_action_error(exc: WorkspaceActionError) -> HTTPException:
    if exc.code.endswith(("unknown", "unavailable")):
        status = 404
    elif "forbidden" in exc.code:
        status = 403
    elif any(token in exc.code for token in ("conflict", "archived", "required")):
        status = 409
    else:
        status = 422
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


def _workspace_timeline_error(exc: WorkspaceTimelineError) -> HTTPException:
    if exc.code.endswith("unknown"):
        status = 404
    elif "forbidden" in exc.code:
        status = 403
    elif "conflict" in exc.code:
        status = 409
    else:
        status = 422
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


def _assessment_error(exc: AssessmentCoreError) -> HTTPException:
    if exc.code.endswith("unknown"):
        status = 404
    elif "forbidden" in exc.code:
        status = 403
    elif any(token in exc.code for token in ("model", "generation_failed", "grading_failed")):
        status = 503
    elif "conflict" in exc.code or "already" in exc.code or "not_due" in exc.code:
        status = 409
    else:
        status = 422
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


def _formal_exam_error(exc: FormalExamError) -> HTTPException:
    if exc.code.endswith("unknown"):
        status = 404
    elif "forbidden" in exc.code:
        status = 403
    elif any(token in exc.code for token in ("conflict", "transition", "not_", "closed", "deadline", "incomplete", "already")):
        status = 409
    else:
        status = 422
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


def _exam_gate_error(exc: ExamGateError) -> HTTPException:
    status = 409 if exc.code == "exam_gate.locked" else 422
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


def _can_manage_exam(session, exam: DBAssessmentExam, user: DBUser) -> bool:
    role = normalize_role(user.role)
    if role == "admin":
        return True
    course_role = active_course_role(
        session, course_id=exam.course_id, user_public_id=user.public_id,
    )
    return role in {"teacher", "assistant"} and (
        exam.owner_public_id == user.public_id or course_role in {"admin", "teacher", "assistant"}
    )


def _is_learner_generated_exam(exam: DBAssessmentExam, user: DBUser) -> bool:
    return normalize_role(user.role) == "student" and exam.owner_public_id == user.public_id


def _review_task_id_for_exam(session, exam: DBAssessmentExam) -> str:
    version = session.query(DBAssessmentExamVersion).filter_by(
        id=exam.current_version_id,
    ).first()
    configuration = dict(version.configuration or {}) if version else {}
    return str(configuration.get("review_task_id") or "").strip()


def _learner_exam_payload(
    session,
    *,
    exam: DBAssessmentExam,
    user: DBUser,
    sitting: DBAssessmentExamSitting | None = None,
) -> dict[str, Any]:
    sitting = sitting or session.query(DBAssessmentExamSitting).filter_by(
        exam_id=exam.id,
        owner_public_id=user.public_id,
    ).first()
    data = exam_payload(session, exam)
    data["sitting"] = sitting_payload(session, sitting) if sitting else None
    data["drafts"] = [
        formal_draft_payload(row)
        for row in latest_formal_response_drafts(session, sitting_id=sitting.id)
    ] if sitting else []
    data["can_manage"] = _can_manage_exam(session, exam, user)
    data["learner_generated"] = _is_learner_generated_exam(exam, user)
    return data


def _formal_exam_event_payload(
    *,
    exam: DBAssessmentExam,
    sitting: DBAssessmentExamSitting,
    report: DBAssessmentExamReport,
) -> dict[str, Any]:
    report_data = dict(report.report_data or {})
    coverage = list(report_data.get("coverage") or [])
    item_results = [
        {
            "position": item.get("position"),
            "question_version_id": item.get("question_version_id"),
            "knowledge_point_id": (item.get("knowledge_point") or {}).get("id"),
            "score": item.get("score"),
            "correct": item.get("correct"),
            "error_reason": item.get("error_reason") or "",
        }
        for item in report_data.get("items") or []
    ]
    recommended_ids = [
        item["id"] for item in coverage
        if item.get("id") not in {None, "unbound"} and float(item.get("ratio") or 0.0) < 0.8
    ]
    if not recommended_ids and coverage:
        lowest = min(coverage, key=lambda item: float(item.get("ratio") or 0.0))
        if lowest.get("id") not in {None, "unbound"}:
            recommended_ids = [lowest["id"]]
    base_time = sitting.submitted_at or datetime.now(timezone.utc).replace(tzinfo=None)
    next_day = (base_time.date() + timedelta(days=1)).isoformat()
    coverage_by_id = {item.get("id"): item for item in coverage}
    next_day_schedule = [
        {
            "knowledge_point_id": point_id,
            "title": str((coverage_by_id.get(point_id) or {}).get("title") or "Knowledge point review"),
            "scheduled_for": next_day,
            "reason": "Formal exam evidence indicates this topic should be reinforced next.",
            "route": "/workspace/review",
        }
        for point_id in recommended_ids
    ]
    return {
        "graded": report_data.get("final_ratio") is not None,
        "attempt_id": sitting.id,
        "exam_id": exam.id,
        "sitting_id": sitting.id,
        "report_id": report.id,
        "score": report_data.get("final_ratio"),
        "knowledge_point_scores": [
            {
                "knowledge_point_id": item.get("id"),
                "score": item.get("ratio"),
            }
            for item in coverage
            if item.get("id") not in {None, "unbound"}
        ],
        "item_results": item_results,
        "recommended_knowledge_point_ids": recommended_ids,
        "next_day_schedule": next_day_schedule,
    }


def _formal_exam_submission_bundle(
    session,
    *,
    exam: DBAssessmentExam,
    sitting: DBAssessmentExamSitting,
    report: DBAssessmentExamReport,
    event: DBLearningEvent | None,
) -> dict[str, Any]:
    consumption = get_learning_aggregation(session, event_id=event.id) if event else None
    aggregation = _aggregation_payload(consumption) if consumption else {
        "status": "pending",
        "attempt": 0,
        "error_code": "",
        "result": {},
    }
    steps = dict((aggregation.get("result") or {}).get("steps") or {})
    completed_steps = set((aggregation.get("result") or {}).get("completed_steps") or [])
    wrong_review = dict(steps.get("wrong_review") or {})
    event_payload = dict(event.payload or {}) if event else _formal_exam_event_payload(
        exam=exam, sitting=sitting, report=report,
    )
    return {
        "sitting": sitting_payload(session, sitting),
        "report": {
            "id": report.id,
            "report_version": report.report_version,
            "content_hash": report.content_hash,
            "report": report.report_data,
        },
        "event_id": event.id if event else None,
        "aggregation": aggregation,
        "learning_feedback": learning_feedback_payload(event, consumption) if event else None,
        "recoverable": aggregation.get("status") != "processed",
        "feedback_updates": {
            "profile": "completed" if "profile_snapshot" in completed_steps else "pending",
            "path": "completed" if "path_task" in completed_steps else "pending",
            "next_day_schedule": event_payload.get("next_day_schedule") or [],
            "wrong_question_ids": wrong_review.get("wrong_question_ids") or [],
            "review_plans": wrong_review.get("review_plans") or [],
        },
    }


def _formal_exam_report_response(
    session,
    *,
    report: DBAssessmentExamReport,
    sitting: DBAssessmentExamSitting,
    exam: DBAssessmentExam,
    created: bool | None = None,
) -> dict[str, Any]:
    result = {
        "id": report.id,
        "report_version": report.report_version,
        "input_hash": report.input_hash,
        "content_hash": report.content_hash,
        "report": report.report_data,
    }
    if created is not None:
        result["created"] = created
    event = session.query(DBLearningEvent).filter_by(
        owner_public_id=sitting.owner_public_id,
        idempotency_key=f"formal-exam-submission:{sitting.id}",
    ).first()
    if event is not None:
        bundle = _formal_exam_submission_bundle(
            session,
            exam=exam,
            sitting=sitting,
            report=report,
            event=event,
        )
        result["event_id"] = bundle["event_id"]
        result["aggregation"] = bundle["aggregation"]
        result["recoverable"] = bundle["recoverable"]
        result["feedback_updates"] = bundle["feedback_updates"]
    return result


def _can_manage_assessment_question(session, question: DBAssessmentQuestion, user: DBUser) -> bool:
    if normalize_role(user.role) == "admin" or question.owner_public_id == user.public_id:
        return True
    if not question.course_id:
        return False
    return active_course_role(
        session, course_id=question.course_id, user_public_id=user.public_id,
    ) in {"admin", "teacher", "assistant"}


def _assessment_question_readable(session, question: DBAssessmentQuestion, user: DBUser) -> bool:
    if question.status != "approved" and not _can_manage_assessment_question(session, question, user):
        return False
    if question.course_id:
        if _can_manage_assessment_question(session, question, user):
            return True
        course = session.query(DBCourse).filter_by(id=question.course_id).first()
        return bool(course and _course_is_readable(session, course, user))
    return question.owner_public_id == user.public_id or normalize_role(user.role) == "admin"


def _ability_explanation(payload: dict[str, Any]) -> dict[str, Any]:
    labels = ("理论理解", "代码实践", "数学推理")
    theta = list(payload.get("theta") or [0.0, 0.0, 0.0])
    theta_std = list(payload.get("theta_std") or [1.0, 1.0, 1.0])
    response_count = int(payload.get("response_count") or 0)
    dimensions = []
    for index, label in enumerate(labels):
        value = float(theta[index] if index < len(theta) else 0.0)
        uncertainty = float(theta_std[index] if index < len(theta_std) else 1.0)
        if response_count < 2:
            status = "证据积累中"
        elif value >= 0.35:
            status = "当前较稳定"
        elif value <= -0.35:
            status = "当前较薄弱"
        else:
            status = "仍需更多作答确认"
        confidence = "较高" if uncertainty <= 0.70 else "中等" if uncertainty <= 0.90 else "有限"
        dimensions.append({
            "key": ("theory", "coding", "math")[index],
            "label": label,
            "theta": round(value, 4),
            "theta_std": round(uncertainty, 4),
            "status": status,
            "confidence": confidence,
        })
    return {
        "dimensions": dimensions,
        "summary": "短诊断正在积累证据。" if response_count < 2 else "能力状态由本课程已提交诊断题逐题更新。",
        "boundary": "该结果是基于冻结题目参数的概率估计，不是课程总评、专家认证或不可更改的能力标签。",
    }


def _assessment_question_context(session, question: DBAssessmentQuestion, version: DBAssessmentQuestionVersion) -> dict[str, Any]:
    knowledge_point = session.query(DBKnowledgePoint).filter_by(id=version.primary_knowledge_point_id).first()
    chapter = None
    if knowledge_point is not None and question.course_id:
        chapter = (
            session.query(DBChapter)
            .join(DBChapterKnowledgePoint, DBChapterKnowledgePoint.chapter_id == DBChapter.id)
            .filter(
                DBChapter.course_id == question.course_id,
                DBChapterKnowledgePoint.knowledge_point_id == knowledge_point.id,
            )
            .order_by(DBChapter.position, DBChapter.id)
            .first()
        )
    sources = []
    for source_ref_id in version.source_ref_ids or []:
        source_ref = session.query(DBSourceRef).filter_by(id=source_ref_id).first()
        if source_ref is None:
            continue
        source_document = session.query(DBSourceDocument).filter_by(id=source_ref.source_document_id).first()
        if source_document is None or source_document.course_id != question.course_id:
            continue
        if chapter is not None and source_ref.chapter_id != chapter.id:
            continue
        sources.append({
            "source_ref_id": source_ref.id,
            "source_document_id": source_document.id,
            "document_title": source_document.title,
            "filename": source_document.filename,
            "chapter_id": source_ref.chapter_id,
            "location_label": source_ref.location_label,
            "location_kind": source_ref.location_kind,
            "char_start": source_ref.char_start,
            "char_end": source_ref.char_end,
            "content_hash": source_ref.content_hash,
            "source_sha256": source_document.source_sha256,
            "license": source_document.license_text,
            "quote": source_ref.quote,
        })
    return {
        "knowledge_point": {
            "id": knowledge_point.id,
            "code": knowledge_point.code,
            "title": knowledge_point.title,
        } if knowledge_point else None,
        "chapter": {
            "id": chapter.id,
            "position": chapter.position,
            "title": chapter.title,
        } if chapter else None,
        "sources": sources,
        "source_status": "verified" if sources else "unavailable",
        "version_evidence": {
            "question_version_id": version.id,
            "version_number": version.version_number,
            "content_hash": version.content_hash,
            "origin": question.origin,
        },
    }


def _assessment_question_bundle(session, question: DBAssessmentQuestion, version: DBAssessmentQuestionVersion) -> dict[str, Any]:
    return {
        **learner_question_payload(version, question),
        "evidence_context": _assessment_question_context(session, question, version),
    }


def _assessment_attempt_bundle(session, attempt: DBAssessmentAttempt) -> dict[str, Any]:
    grading = session.query(DBAssessmentGradingResult).filter_by(
        attempt_id=attempt.id,
    ).order_by(DBAssessmentGradingResult.created_at.desc(), DBAssessmentGradingResult.id.desc()).first()
    ability = session.query(DBAssessmentAbilityState).filter_by(
        owner_public_id=attempt.owner_public_id,
        course_scope=attempt.course_id or "__global__",
    ).first()
    version = session.query(DBAssessmentQuestionVersion).filter_by(id=attempt.question_version_id).one()
    question = session.query(DBAssessmentQuestion).filter_by(id=version.question_id).one()
    misconception = session.query(DBMisconceptionReview).filter_by(attempt_id=attempt.id).first()
    ability_payload = ability_state_payload(ability) if ability else None
    ability_update = (grading.evidence or {}).get("ability_update") if grading else None
    payload = {
        **learner_attempt_payload(attempt, grading),
        "grading": grading_result_payload(grading),
        "ability": ability_payload,
        "ability_explanation": _ability_explanation(ability_payload) if ability_payload else None,
        "ability_update": ability_update,
        "question": _assessment_question_context(session, question, version),
        "answer_explanation": (
            learner_safe_explanation(
                version.explanation,
                prompt=version.prompt,
                options=version.options,
                answer_key=version.answer_key,
                question_type=question.question_type,
            )
            if attempt.feedback_policy != "after_close" else ""
        ),
        "misconception_review": misconception_review_payload(misconception),
    }
    if attempt.feedback_policy != "after_close":
        payload["correct_answer"] = learner_correct_answer(question.question_type, version.answer_key or {})
    return payload


def _owned_plan(session, plan_id: str, owner_public_id: str) -> DBPlanDraft:
    plan = session.query(DBPlanDraft).filter_by(id=plan_id).first()
    if plan is None:
        raise HTTPException(status_code=404, detail={"code": "plan_unknown", "message": "plan does not exist"})
    if plan.owner_public_id != owner_public_id:
        raise HTTPException(status_code=403, detail={"code": "plan_forbidden", "message": "plan belongs to another owner"})
    return plan


def _owned_path(session, path_id: str, owner_public_id: str) -> DBLearningPath:
    path = session.query(DBLearningPath).filter_by(id=path_id).first()
    if path is None:
        raise HTTPException(status_code=404, detail={"code": "path_unknown", "message": "path does not exist"})
    if path.owner_public_id != owner_public_id:
        raise HTTPException(status_code=403, detail={"code": "path_forbidden", "message": "path belongs to another owner"})
    return path


def _plan_payload(session, plan: DBPlanDraft) -> dict[str, Any]:
    versions = session.query(DBPlanVersion).filter_by(plan_draft_id=plan.id).order_by(
        DBPlanVersion.version_number,
    ).all()
    return {
        "id": plan.id,
        "course_id": plan.course_id,
        "title": plan.title,
        "status": plan.status,
        "lock_version": plan.lock_version,
        "current_version_id": plan.current_version_id,
        "confirmed_version_id": plan.confirmed_version_id,
        "confirmed_at": plan.confirmed_at.isoformat() if plan.confirmed_at else None,
        "versions": [{
            "id": item.id,
            "number": item.version_number,
            "content_hash": item.content_hash,
            "content": item.content,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        } for item in versions],
    }


def _path_payload(session, path: DBLearningPath) -> dict[str, Any]:
    nodes = session.query(DBPathNode).filter_by(learning_path_id=path.id).order_by(DBPathNode.sequence).all()
    course = session.get(DBCourse, path.course_id) if path.course_id else None
    return {
        "id": path.id,
        "course_id": path.course_id,
        "course": {
            "id": course.id,
            "title": course.title,
            "subject": course.subject,
        } if course else None,
        "source_plan_version_id": path.source_plan_version_id,
        "supersedes_path_id": path.supersedes_path_id,
        "status": path.status,
        "lock_version": path.lock_version,
        "nodes": [{
            "id": item.id,
            "node_key": item.node_key,
            "sequence": item.sequence,
            "node_type": item.node_type,
            "target_object_id": item.target_object_id,
            "title": item.title,
            "status": item.status,
            "prerequisites": item.prerequisites or [],
            "is_extension": item.is_extension,
            "resource_status": item.resource_status,
            "estimate_minutes": [item.estimate_min_minutes, item.estimate_max_minutes],
            "actual_minutes": item.actual_minutes,
        } for item in nodes],
    }


def _event_payload(event: DBLearningEvent) -> dict[str, Any]:
    safe_payload_keys = {
        "active_seconds", "actual_minutes", "attempt_id", "confidence", "correct",
        "completion_rule", "generation_job_id", "knowledge_point_id",
        "delay_hours", "evaluation_id", "mode", "passed_checks", "passed_count",
        "recall_score", "review_id", "rubric_score", "run_id", "score",
        "resource_type", "resource_version_id", "test_scope", "total_checks", "total_count",
    }
    payload_summary = {
        key: value for key, value in (event.payload or {}).items()
        if key in safe_payload_keys
    }
    return {
        "id": event.id,
        "actor": {
            "owner_public_id": event.owner_public_id,
            "source": event.source,
        },
        "event_type": event.event_type,
        "action": event.action,
        "context": event.context_ref or {},
        "course_id": event.course_id,
        "object_type": event.object_type,
        "object_id": event.object_id,
        "source": event.source,
        "evidence_status": event.evidence_status,
        "evidence_strength": float(event.evidence_strength or 0.0),
        "evidence_reason": event.evidence_reason or "",
        "mastery_eligible": bool(event.mastery_eligible),
        "completion_effect": event.completion_effect,
        "payload_version": event.payload_version,
        "payload_summary": payload_summary,
        "trace_id": event.trace_id,
        "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
        "recorded_at": event.recorded_at.isoformat() if event.recorded_at else None,
    }


def _aggregation_payload(consumption: Any) -> dict[str, Any]:
    return {
        "id": consumption.id,
        "status": consumption.status,
        "processor_version": consumption.processor_version,
        "attempt": consumption.attempt,
        "error_code": consumption.error_code or "",
        "processed_at": consumption.processed_at.isoformat() if consumption.processed_at else None,
        "result": dict(consumption.result or {}),
    }


def _path_consumption_payload(consumption: Any) -> dict[str, Any]:
    aggregation = _aggregation_payload(consumption)
    return {
        "id": aggregation["id"],
        "status": aggregation["status"],
        "processor_version": aggregation["processor_version"],
        "attempt": aggregation["attempt"],
        "result": dict((aggregation["result"].get("steps") or {}).get("path_task") or {}),
    }


def _course_is_readable(session, course: DBCourse, current_user: DBUser) -> bool:
    from course_catalog import course_is_selectable
    if not course_is_selectable(session, course):
        return False
    if current_user.role == "admin" or course.owner_public_id == current_user.public_id:
        return True
    if course.visibility == "public":
        return True
    return session.query(DBCourseMembership.id).filter_by(
        course_id=course.id,
        user_public_id=current_user.public_id,
        status="active",
    ).first() is not None


def _planning_targets(session, current_user: DBUser) -> dict[str, Any]:
    from course_catalog import course_is_selectable
    courses = []
    for course in session.query(DBCourse).order_by(DBCourse.title, DBCourse.id).all():
        if not _course_is_readable(session, course, current_user):
            continue
        if not course_is_selectable(session, course):
            continue
        chapters = session.query(DBChapter).filter_by(course_id=course.id).order_by(
            DBChapter.position, DBChapter.id,
        ).all()
        courses.append({
            "id": course.id,
            "title": course.title,
            "version": course.version,
            "visibility": course.visibility,
            "chapters": [{
                "id": item.id,
                "title": item.title,
                "position": item.position,
                "parent_id": item.parent_id,
            } for item in chapters],
        })
    artifacts = session.query(DBArtifact).filter(
        DBArtifact.owner_public_id == current_user.public_id,
        DBArtifact.archived_at.is_(None),
    ).order_by(DBArtifact.updated_at.desc(), DBArtifact.id).all()
    return {
        "schema_version": "m5.planning-targets.v1",
        "courses": courses,
        "artifacts": [{
            "id": item.id,
            "course_id": item.course_id,
            "title": item.title,
            "artifact_type": item.artifact_type,
            "status": item.status,
        } for item in artifacts],
    }


def runtime_availability() -> RuntimeAvailability:
    provider = CONFIG.llm_provider.strip().lower()
    text_model = bool(CONFIG.llm_endpoint and CONFIG.llm_api_key and CONFIG.llm_model) and provider not in {"mock", "deterministic"}
    deterministic_text_model = provider == "deterministic" and CONFIG.llm_model.strip().lower() == "deterministic"
    vision_model = bool(
        CONFIG.multimodal_llm_endpoint and CONFIG.multimodal_llm_api_key and CONFIG.multimodal_llm_model
    )
    retrieval = any((ROOT / "data" / "faiss_indexes").glob("*.faiss"))
    sandbox = CONFIG.sandbox_mode if CONFIG.sandbox_mode in {"disabled", "trusted_local", "docker", "external_lab"} else "disabled"
    return RuntimeAvailability(
        text_model=text_model,
        deterministic_text_model=deterministic_text_model,
        vision_model=vision_model,
        retrieval=retrieval,
        media_pipeline=(ROOT / "data" / "animations").is_dir(),
        sandbox_mode=sandbox,
    )


@router.get("/capabilities")
async def list_capabilities(current_user: DBUser = Depends(get_current_user)):
    runtime = runtime_availability()
    return {
        "schema_version": "m5.capability-status.v1",
        "runtime": runtime.model_dump(mode="json"),
        "generation_mode": runtime.generation_mode,
        "capabilities": [item.model_dump(mode="json") for item in capability_statuses(runtime)],
        "user_configurable_secrets": False,
    }


@router.post("/route")
async def preflight_route(payload: RoutingRequest, current_user: DBUser = Depends(get_current_user)):
    try:
        decision = route_capability(payload, runtime_availability())
        return decision.model_dump(mode="json")
    except M5CapabilityError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc


@router.get("/model-governance")
async def get_model_governance(current_user: DBUser = Depends(get_current_user)):
    _require_model_operator(current_user)

    def operation(session):
        rows = (
            session.query(DBModelCall)
            .order_by(DBModelCall.created_at.desc(), DBModelCall.id.desc())
            .limit(50)
            .all()
        )
        recent = [
            {
                "id": row.id,
                "trace_id": row.trace_id,
                "capability": row.capability,
                "provider": row.provider,
                "model": row.model,
                "status": row.status,
                "input_tokens": row.input_tokens,
                "output_tokens": row.output_tokens,
                "estimated_cost": row.estimated_cost,
                "duration_ms": row.duration_ms,
                "error_code": row.error_code,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "input_summary": row.input_summary,
            }
            for row in rows
        ]
        callsites = scan_model_calls(ROOT)
        summary = governance_summary(callsites)
        return {
            **summary,
            "callsites": [item.payload() for item in callsites],
            "recent_calls": recent,
            "raw_prompts_persisted": False,
            "raw_outputs_persisted": False,
        }

    from app.database import DBModelCall
    return await run_db_op(operation)


@router.get("/model-operations")
async def get_model_operations(current_user: DBUser = Depends(get_current_user)):
    _require_model_operator(current_user)
    return await run_db_op(operations_dashboard)


@router.get("/legacy-migration-governance")
async def get_legacy_migration_governance(current_user: DBUser = Depends(get_current_user)):
    _require_model_operator(current_user)

    def operation(session):
        inventory = legacy_governance_summary(ROOT)
        runtime = migration_runtime_summary(session)
        rows = session.query(DBAuditLog).filter_by(
            action="legacy_migration_observation"
        ).order_by(DBAuditLog.created_at.desc(), DBAuditLog.id.desc()).limit(50).all()
        return {
            "schema_version": "next.legacy-migration-governance-api.v1",
            "registry_version": inventory["registry_version"],
            "inventory": inventory,
            "runtime": runtime,
            "recent_observations": [
                {
                    "id": row.id,
                    "trace_id": row.trace_id,
                    "chain_id": row.object_id,
                    "outcome": row.outcome,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "metadata": row.metadata_json or {},
                }
                for row in rows
            ],
            "raw_content_persisted": False,
            "deletion_requires_zero_consumer_proof": True,
        }

    return await run_db_op(operation)


def _legacy_migration_error(exc: LegacyMigrationError) -> HTTPException:
    status = 404 if exc.code.endswith("unknown") else 403 if exc.code.endswith("forbidden") else 409
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


@router.get("/legacy-object-migrations")
async def get_legacy_object_migrations(
    owner_public_id: str,
    current_user: DBUser = Depends(get_current_user),
):
    _require_model_operator(current_user)
    return await run_db_op(
        lambda session: {"items": legacy_object_migrations(session, owner_public_id=owner_public_id)}
    )


@router.post("/legacy-object-migrations", status_code=201)
async def create_legacy_object_migration(
    payload: LegacyObjectMigrationRequest,
    current_user: DBUser = Depends(get_current_user),
):
    _require_model_operator(current_user)

    def operation(session):
        try:
            result = migrate_legacy_object(
                session,
                owner_public_id=payload.owner_public_id,
                old_type=payload.old_type,
                old_id=payload.old_id,
                version=payload.version,
            )
        except LegacyMigrationError:
            session.commit()
            raise
        session.commit()
        return result

    try:
        return await run_db_op(operation)
    except LegacyMigrationError as exc:
        raise _legacy_migration_error(exc) from exc


@router.post("/legacy-object-migrations/{migration_id}/rollback")
async def rollback_legacy_object_migration(
    migration_id: str,
    payload: LegacyObjectRollbackRequest,
    current_user: DBUser = Depends(get_current_user),
):
    _require_model_operator(current_user)

    def operation(session):
        result = rollback_legacy_object(
            session,
            owner_public_id=payload.owner_public_id,
            migration_id=migration_id,
            rollback_token=payload.rollback_token,
        )
        session.commit()
        return result

    try:
        return await run_db_op(operation)
    except LegacyMigrationError as exc:
        raise _legacy_migration_error(exc) from exc


@router.post("/model-operations/prices", status_code=201)
async def create_model_price_version(
    payload: PriceVersionInput, current_user: DBUser = Depends(get_current_user),
):
    _require_admin(current_user)

    def operation(session):
        row, created = register_price_version(session, payload)
        session.commit()
        return {"price": pricing_payload(row), "created": created}

    try:
        return await run_db_op(operation)
    except OperationsError as exc:
        raise _operations_error(exc) from exc


@router.post("/model-operations/workers/claim")
async def claim_model_worker_task(
    payload: WorkerClaimInput, current_user: DBUser = Depends(get_current_user),
):
    _require_admin(current_user)

    def operation(session):
        claimed = claim_next_task(session, payload)
        session.commit()
        return {"claim": claimed}

    return await run_db_op(operation)


@router.post("/model-operations/workers/leases/{lease_id}/heartbeat")
async def heartbeat_model_worker(
    lease_id: str, payload: WorkerHeartbeatInput,
    current_user: DBUser = Depends(get_current_user),
):
    _require_admin(current_user)
    try:
        return await run_db_op(lambda session: _commit_operation(
            session, heartbeat_lease, lease_id, payload,
        ))
    except OperationsError as exc:
        raise _operations_error(exc) from exc


@router.post("/model-operations/workers/leases/{lease_id}/release")
async def release_model_worker(
    lease_id: str, payload: WorkerHeartbeatInput,
    current_user: DBUser = Depends(get_current_user),
):
    _require_admin(current_user)
    try:
        return await run_db_op(lambda session: _commit_operation(
            session, release_lease, lease_id, payload,
        ))
    except OperationsError as exc:
        raise _operations_error(exc) from exc


@router.post("/model-operations/workers/recover")
async def recover_model_workers(current_user: DBUser = Depends(get_current_user)):
    _require_admin(current_user)

    def operation(session):
        recovered = recover_expired_leases(session)
        session.commit()
        return {"recovered_task_ids": recovered, "count": len(recovered)}

    return await run_db_op(operation)


def _commit_operation(session, function, lease_id, payload):
    result = function(session, lease_id, payload)
    session.commit()
    return result


def _owned_resource(session, artifact_id: str, current_user: DBUser, action: str = "read") -> DBArtifact:
    artifact = session.query(DBArtifact).filter_by(id=artifact_id).first()
    if artifact is None:
        raise HTTPException(status_code=404, detail={"code": "resource_unknown", "message": "resource does not exist"})
    require_object_access(
        current_user,
        ObjectAccess("artifact", artifact.id, owner_public_id=artifact.owner_public_id, course_id=artifact.course_id),
        action=action,
    )
    return artifact


@router.get("/resources")
async def list_resources(
    q: str = "", artifact_type: str | None = None, course_id: str | None = None,
    status: str | None = None, source_status: str | None = None,
    include_archived: bool = False,
    cursor: str | None = None, limit: int = 25,
    current_user: DBUser = Depends(get_current_user),
):
    return await run_db_op(lambda session: search_resources(
        session, owner_public_id=current_user.public_id, query=q,
        artifact_type=artifact_type, course_id=course_id, status=status,
        source_status=source_status, include_archived=include_archived,
        cursor=cursor, limit=limit,
    ))


@router.get("/resources/{artifact_id}")
async def get_resource(artifact_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(lambda session: resource_detail(
        session, _owned_resource(session, artifact_id, current_user),
    ))


@router.get("/resources/{artifact_id}/compare")
async def compare_resource(
    artifact_id: str, left_version: int, right_version: int,
    current_user: DBUser = Depends(get_current_user),
):
    try:
        return await run_db_op(lambda session: compare_resource_versions(
            session, artifact=_owned_resource(session, artifact_id, current_user),
            left_version=left_version, right_version=right_version,
        ))
    except M5CapabilityError as exc:
        raise HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)}) from exc


@router.get("/resources/{artifact_id}/export")
async def export_resource(
    artifact_id: str, version_number: int | None = None,
    current_user: DBUser = Depends(get_current_user),
):
    try:
        return await run_db_op(lambda session: export_resource_version(
            session, artifact=_owned_resource(session, artifact_id, current_user),
            version_number=version_number,
        ))
    except M5CapabilityError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc


@router.post("/resources/{artifact_id}/archive")
async def archive_resource(
    artifact_id: str, payload: ResourceArchiveRequest,
    current_user: DBUser = Depends(get_current_user),
):
    try:
        return await run_db_op(lambda session: set_resource_archived(
            session,
            artifact=_owned_resource(session, artifact_id, current_user, action="update"),
            actor_public_id=current_user.public_id,
            archived=payload.archived,
            expected_lock_version=payload.expected_lock_version,
        ))
    except M5CapabilityError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc


@router.post("/plans", status_code=201)
async def create_learning_plan(payload: PlanDraftCreate, current_user: DBUser = Depends(get_current_user)):
    def operation(session):
        plan, version, created = create_plan_draft(
            session,
            owner_public_id=current_user.public_id,
            course_id=payload.course_id,
            title=payload.title,
            idempotency_key=payload.idempotency_key,
            profile_snapshot_id=payload.profile_snapshot_id,
            spec=payload.spec,
        )
        session.commit()
        return {**_plan_payload(session, plan), "created": created, "version_id": version.id}

    try:
        return await run_db_op(operation)
    except M5LearningError as exc:
        raise _learning_error(exc) from exc


@router.get("/planning-targets")
async def list_planning_targets(current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(lambda session: _planning_targets(session, current_user))


@router.get("/plans")
async def list_learning_plans(
    course_id: str | None = None,
    include_archived: bool = False,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        query = session.query(DBPlanDraft).filter_by(owner_public_id=current_user.public_id)
        if course_id:
            query = query.filter(DBPlanDraft.course_id == course_id)
        if not include_archived:
            query = query.filter(DBPlanDraft.archived_at.is_(None))
        plans = query.order_by(DBPlanDraft.updated_at.desc(), DBPlanDraft.id).all()
        return {"items": [_plan_payload(session, item) for item in plans]}

    return await run_db_op(operation)


@router.get("/plans/{plan_id}")
async def get_learning_plan(plan_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(lambda session: _plan_payload(
        session, _owned_plan(session, plan_id, current_user.public_id),
    ))


@router.post("/plans/{plan_id}/revisions", status_code=201)
async def revise_learning_plan(
    plan_id: str, payload: PlanRevisionCreate,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        plan = _owned_plan(session, plan_id, current_user.public_id)
        version, diff = propose_plan_revision(
            session,
            plan=plan,
            owner_public_id=current_user.public_id,
            expected_lock_version=payload.expected_lock_version,
            spec=payload.spec,
            profile_snapshot_id=payload.profile_snapshot_id,
        )
        session.commit()
        return {"plan": _plan_payload(session, plan), "version_id": version.id, "diff": diff}

    try:
        return await run_db_op(operation)
    except M5LearningError as exc:
        raise _learning_error(exc) from exc


@router.get("/plans/{plan_id}/diff")
async def get_learning_plan_diff(
    plan_id: str, from_version_id: str, to_version_id: str,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        plan = _owned_plan(session, plan_id, current_user.public_id)
        left = session.query(DBPlanVersion).filter_by(id=from_version_id, plan_draft_id=plan.id).first()
        right = session.query(DBPlanVersion).filter_by(id=to_version_id, plan_draft_id=plan.id).first()
        if left is None or right is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "plan_version_unknown", "message": "plan version does not exist"},
            )
        return plan_version_diff(left, right)

    return await run_db_op(operation)


@router.post("/plans/{plan_id}/confirm", status_code=201)
async def confirm_learning_plan(
    plan_id: str, payload: PlanConfirmRequest,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        plan = _owned_plan(session, plan_id, current_user.public_id)
        path = confirm_plan(
            session,
            plan=plan,
            owner_public_id=current_user.public_id,
            expected_lock_version=payload.expected_lock_version,
        )
        session.commit()
        return {"plan": _plan_payload(session, plan), "path": _path_payload(session, path)}

    try:
        return await run_db_op(operation)
    except M5LearningError as exc:
        raise _learning_error(exc) from exc


@router.get("/textbook-path-draft")
async def get_textbook_path_draft(
    course_id: str,
    current_user: DBUser = Depends(get_current_user),
):
    try:
        return await run_db_op(lambda session: textbook_path_draft_payload(
            session, current_user=current_user, course_id=course_id,
        ))
    except PathDraftError as exc:
        status_code = 404 if exc.code == "course_not_found" else 403 if exc.code == "course_forbidden" else 409
        raise HTTPException(
            status_code=status_code, detail={"code": exc.code, "message": str(exc)},
        ) from exc


@router.post("/textbook-path-draft/generate", status_code=201)
async def generate_textbook_path_draft_api(
    payload: TextbookPathDraftRequest,
    current_user: DBUser = Depends(get_current_user),
):
    if not 30 <= payload.time_budget_minutes <= 480:
        raise HTTPException(
            status_code=422,
            detail={"code": "path_draft_time_budget_invalid", "message": "时间预算需在 30 到 480 分钟之间"},
        )

    def operation(session):
        plan, changed = generate_textbook_path_draft(
            session,
            current_user=current_user,
            course_id=payload.course_id,
            time_budget_minutes=payload.time_budget_minutes,
            llm=_build_path_model(),
        )
        session.commit()
        return {
            **textbook_path_draft_payload(
                session, current_user=current_user, course_id=payload.course_id,
            ),
            "changed": changed,
            "plan_id": plan.id,
        }

    try:
        return await run_db_op(operation)
    except (PathDraftError, M5LearningError) as exc:
        code = getattr(exc, "code", "path_draft_failed")
        status_code = 404 if code == "course_not_found" else 403 if code in {"course_forbidden", "plan_forbidden"} else 409
        raise HTTPException(
            status_code=status_code, detail={"code": code, "message": str(exc)},
        ) from exc


@router.get("/paths/{path_id}")
async def get_learning_path(path_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(lambda session: _path_payload(
        session, _owned_path(session, path_id, current_user.public_id),
    ))


@router.post("/resources/{artifact_id}/versions", status_code=201)
async def create_resource_revision(
    artifact_id: str,
    payload: ResourceVersionCreateRequest,
    current_user: DBUser = Depends(get_current_user),
):
    try:
        return await run_db_op(lambda session: create_resource_version(
            session,
            artifact=_owned_resource(session, artifact_id, current_user, action="update"),
            actor_public_id=current_user.public_id,
            request=payload,
        ))
    except M5CapabilityError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc


@router.get("/resources/{artifact_id}/deck-export/{format_name}")
async def export_deck_resource(
    artifact_id: str,
    format_name: Literal["html", "pptx"],
    version_id: str | None = None,
    current_user: DBUser = Depends(get_current_user),
):
    try:
        content, filename, media_type = await run_db_op(lambda session: render_deck_export(
            session,
            artifact=_owned_resource(session, artifact_id, current_user),
            version_id=version_id,
            format_name=format_name,
        ))
    except M5CapabilityError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="edumatrix-courseware.{format_name}"; '
                f"filename*=UTF-8''{quote(filename)}"
            ),
        },
    )


@router.get("/resources/{artifact_id}/video-media/{recommendation_id}")
async def get_video_resource_media(
    artifact_id: str,
    recommendation_id: str,
    version_id: str | None = None,
    current_user: DBUser = Depends(get_current_user),
):
    try:
        path, media_type = await run_db_op(lambda session: locate_video_media(
            session,
            artifact=_owned_resource(session, artifact_id, current_user),
            recommendation_id=recommendation_id,
            version_id=version_id,
        ))
    except M5CapabilityError as exc:
        raise HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)}) from exc
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.post("/resources/{artifact_id}/restore")
async def restore_resource_revision(
    artifact_id: str,
    payload: ResourceVersionRestoreRequest,
    current_user: DBUser = Depends(get_current_user),
):
    try:
        return await run_db_op(lambda session: restore_resource_version(
            session,
            artifact=_owned_resource(session, artifact_id, current_user, action="update"),
            actor_public_id=current_user.public_id,
            request=payload,
        ))
    except M5CapabilityError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc


@router.post("/resources/{artifact_id}/complete", status_code=201)
async def complete_resource_learning(
    artifact_id: str,
    payload: ResourceCompletionRequest,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        artifact = _owned_resource(session, artifact_id, current_user)
        existing = session.query(DBLearningEvent).filter_by(
            owner_public_id=current_user.public_id,
            idempotency_key=payload.idempotency_key,
        ).first()
        if existing is not None:
            existing_payload = dict(existing.payload or {})
            submitted_rule = " ".join(payload.completion_rule.split())
            existing_rule = " ".join(str(existing_payload.get("completion_rule") or "").split())
            submitted_context = payload.context or {}
            context_matches = all(
                submitted_context.get(key) in {None, (existing.context_ref or {}).get(key)}
                for key in ("courseId", "pathId", "taskId")
            )
            if (
                existing.event_type != "user_marked_complete"
                or existing.object_type != "artifact"
                or existing.object_id != artifact.id
                or existing_payload.get("resource_version_id") != payload.resource_version_id
                or existing_rule != submitted_rule
                or existing_payload.get("actual_minutes") != payload.actual_minutes
                or not context_matches
            ):
                raise M5LearningError(
                    "learning_event_idempotency_conflict",
                    "event idempotency key is bound to different data",
                )
            consumption = process_path_event(session, event=existing)
            session.commit()
            return {
                **_event_payload(existing),
                "created": False,
                "consumption": _path_consumption_payload(consumption),
                "aggregation": _aggregation_payload(consumption),
            }
        completion = validate_resource_completion(
            session,
            artifact=artifact,
            resource_version_id=payload.resource_version_id,
            completion_rule=payload.completion_rule,
        )
        event_payload = dict(completion)
        if payload.actual_minutes is not None:
            event_payload["actual_minutes"] = payload.actual_minutes
        event, created = record_learning_event(
            session,
            owner_public_id=current_user.public_id,
            user=current_user,
            trusted_source=False,
            event=LearningEventInput(
                idempotency_key=payload.idempotency_key,
                event_type="user_marked_complete",
                context=ContextRef.model_validate(payload.context) if payload.context else None,
                course_id=artifact.course_id,
                object_type="artifact",
                object_id=artifact.id,
                source="frontend",
                payload=event_payload,
            ),
        )
        consumption = process_path_event(session, event=event)
        session.commit()
        return {
            **_event_payload(event),
            "created": created,
            "consumption": _path_consumption_payload(consumption),
            "aggregation": _aggregation_payload(consumption),
        }

    try:
        return await run_db_op(operation)
    except M5CapabilityError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc
    except M5LearningError as exc:
        raise _learning_error(exc) from exc
    except ContextResolutionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc


@router.get("/paths")
async def list_learning_paths(
    course_id: str | None = None,
    include_archived: bool = False,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        query = session.query(DBLearningPath).filter_by(owner_public_id=current_user.public_id)
        if course_id:
            query = query.filter(DBLearningPath.course_id == course_id)
        if not include_archived:
            query = query.filter(DBLearningPath.status != "archived")
        paths = query.order_by(DBLearningPath.updated_at.desc(), DBLearningPath.id).all()
        return {"items": [_path_payload(session, item) for item in paths]}

    return await run_db_op(operation)


@router.post("/paths/{path_id}/transition")
async def transition_learning_path(
    path_id: str, payload: PathTransitionRequest,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        path = transition_path(
            session,
            path=_owned_path(session, path_id, current_user.public_id),
            owner_public_id=current_user.public_id,
            target_status=payload.target_status,
            expected_lock_version=payload.expected_lock_version,
        )
        session.commit()
        return _path_payload(session, path)

    try:
        return await run_db_op(operation)
    except M5LearningError as exc:
        raise _learning_error(exc) from exc


@router.get("/learning-events")
async def list_learning_events(
    course_id: str | None = None,
    evidence_status: Literal["none", "accepted", "rejected"] | None = None,
    limit: int = 50,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        query = session.query(DBLearningEvent).filter_by(
            owner_public_id=current_user.public_id,
        )
        if course_id:
            query = query.filter(DBLearningEvent.course_id == course_id)
        if evidence_status:
            query = query.filter(DBLearningEvent.evidence_status == evidence_status)
        events = query.order_by(
            DBLearningEvent.occurred_at.desc(), DBLearningEvent.id.desc(),
        ).limit(max(1, min(limit, 200))).all()
        return {"items": [_event_payload(event) for event in events]}

    return await run_db_op(operation)


@router.post("/learning-events", status_code=201)
async def create_learning_event(
    payload: LearningEventInput, current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        event, created = record_learning_event(
            session,
            owner_public_id=current_user.public_id,
            event=payload,
            user=current_user,
            trusted_source=False,
        )
        consumption = process_path_event(session, event=event)
        session.commit()
        return {
            **_event_payload(event),
            "created": created,
            "consumption": _path_consumption_payload(consumption),
            "aggregation": _aggregation_payload(consumption),
        }

    try:
        return await run_db_op(operation)
    except M5LearningError as exc:
        raise _learning_error(exc) from exc
    except ContextResolutionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc


@router.post("/learning-events/{event_id}/process")
async def replay_learning_event(event_id: str, current_user: DBUser = Depends(get_current_user)):
    def operation(session):
        event = session.query(DBLearningEvent).filter_by(id=event_id).first()
        if event is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "learning_event_unknown", "message": "learning event does not exist"},
            )
        if event.owner_public_id != current_user.public_id:
            raise HTTPException(
                status_code=403,
                detail={"code": "learning_event_forbidden", "message": "learning event belongs to another owner"},
            )
        consumption = process_path_event(session, event=event)
        session.commit()
        aggregation = _aggregation_payload(consumption)
        return {
            "event_id": event.id,
            "consumption_id": consumption.id,
            "status": consumption.status,
            "attempt": consumption.attempt,
            "result": _path_consumption_payload(consumption)["result"],
            "aggregation": aggregation,
        }

    return await run_db_op(operation)


@router.get("/learning-feedback/latest")
async def latest_learning_feedback(
    course_id: str | None = None,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        query = session.query(DBLearningEvent).filter(
            DBLearningEvent.owner_public_id == current_user.public_id,
            DBLearningEvent.event_type.in_(LEARNING_FEEDBACK_EVENT_TYPES),
        )
        if course_id:
            query = query.filter(DBLearningEvent.course_id == course_id)
        event = query.order_by(
            DBLearningEvent.occurred_at.desc(),
            DBLearningEvent.recorded_at.desc(),
            DBLearningEvent.id.desc(),
        ).first()
        if event is None:
            return {"feedback": None}
        consumption = get_learning_aggregation(session, event_id=event.id)
        return {"feedback": learning_feedback_payload(event, consumption)}

    return await run_db_op(operation)


@router.get("/learning-events/{event_id}/aggregation")
async def learning_event_aggregation(
    event_id: str,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        event = session.query(DBLearningEvent).filter_by(id=event_id).first()
        if event is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "learning_event_unknown", "message": "learning event does not exist"},
            )
        if event.owner_public_id != current_user.public_id:
            raise HTTPException(
                status_code=403,
                detail={"code": "learning_event_forbidden", "message": "learning event belongs to another owner"},
            )
        consumption = get_learning_aggregation(session, event_id=event.id)
        if consumption is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "learning_aggregation_unknown", "message": "learning event has not been aggregated"},
            )
        return {
            "event_id": event.id,
            "aggregation": _aggregation_payload(consumption),
            "feedback": learning_feedback_payload(event, consumption),
        }

    return await run_db_op(operation)


@router.post("/assessment-evidence", status_code=201)
async def create_assessment_evidence(
    payload: AssessmentEvidenceInput, current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        result = record_assessment_evidence(
            session,
            owner_public_id=current_user.public_id,
            evidence=payload,
            user=current_user,
            trusted_source=False,
        )
        session.commit()
        return result

    try:
        return await run_db_op(operation)
    except M5LearningError as exc:
        raise _learning_error(exc) from exc
    except ContextResolutionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc


@router.post("/assessment/questions", status_code=201)
async def create_assessment_question(
    payload: QuestionCreate, current_user: DBUser = Depends(get_current_user),
):
    if current_user.role not in {"teacher", "admin"}:
        raise HTTPException(status_code=403, detail={"code": "question_create_forbidden", "message": "teacher or admin role required"})

    def operation(session):
        if payload.course_id:
            course = session.query(DBCourse).filter_by(id=payload.course_id).first()
            if course is None:
                raise HTTPException(status_code=404, detail={"code": "course_unknown", "message": "course does not exist"})
            from course_catalog import course_is_selectable
            if not course_is_selectable(session, course):
                raise HTTPException(status_code=409, detail={"code": "course_unavailable", "message": "course is not currently available for selection"})
            course_role = active_course_role(
                session, course_id=course.id, user_public_id=current_user.public_id,
            )
            can_create = (
                current_user.role == "admin" or course.owner_public_id == current_user.public_id
                or course_role in {"admin", "teacher", "assistant"}
            )
            if not can_create:
                raise HTTPException(status_code=403, detail={"code": "course_forbidden", "message": "course is unavailable"})
        question, version = create_question_version(
            session, owner_public_id=current_user.public_id, course_id=payload.course_id,
            question_type=payload.question_type, origin=payload.origin, version=payload.version,
        )
        session.commit()
        return {"question_id": question.id, "question_version": learner_question_payload(version, question)}

    try:
        return await run_db_op(operation)
    except AssessmentCoreError as exc:
        raise _assessment_error(exc) from exc


@router.get("/assessment/questions")
async def list_assessment_questions(
    course_id: str | None = None,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        query = session.query(DBAssessmentQuestion)
        if course_id:
            query = query.filter(DBAssessmentQuestion.course_id == course_id)
        rows = query.order_by(DBAssessmentQuestion.updated_at.desc(), DBAssessmentQuestion.id).all()
        items = []
        for question in rows:
            if not _assessment_question_readable(session, question, current_user):
                continue
            version = session.query(DBAssessmentQuestionVersion).filter_by(
                id=question.current_version_id,
            ).first()
            if version is not None:
                items.append(_assessment_question_bundle(session, question, version))
        version_ids = [item["id"] for item in items]
        attempts = []
        if version_ids:
            rows = (
                session.query(DBAssessmentAttempt)
                .filter(
                    DBAssessmentAttempt.owner_public_id == current_user.public_id,
                    DBAssessmentAttempt.question_version_id.in_(version_ids),
                    DBAssessmentAttempt.mode == "diagnostic",
                )
                .order_by(DBAssessmentAttempt.submitted_at.desc(), DBAssessmentAttempt.id.desc())
                .all()
            )
            seen_versions = set()
            for attempt in rows:
                if attempt.question_version_id in seen_versions:
                    continue
                seen_versions.add(attempt.question_version_id)
                attempts.append(_assessment_attempt_bundle(session, attempt))
        ability = session.query(DBAssessmentAbilityState).filter_by(
            owner_public_id=current_user.public_id,
            course_scope=course_id or "__global__",
        ).first()
        ability_payload = ability_state_payload(ability) if ability else {
            "course_id": course_id, "theta": [0.0, 0.0, 0.0], "theta_std": [1.0, 1.0, 1.0],
            "theta_cov": [], "response_count": 0, "lock_version": 0, "last_attempt_id": None,
        }
        return {
            "schema_version": "next.assessment-catalog.v2",
            "course_id": course_id,
            "items": items,
            "attempts": attempts,
            "ability": ability_payload,
            "ability_explanation": _ability_explanation(ability_payload),
        }

    return await run_db_op(operation)


@router.post("/assessment/questions/{question_id}/versions", status_code=201)
async def revise_assessment_question(
    question_id: str, payload: QuestionRevisionCreate,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        question = session.query(DBAssessmentQuestion).filter_by(id=question_id).first()
        if question is None:
            raise HTTPException(status_code=404, detail={"code": "question_unknown", "message": "question does not exist"})
        if not _can_manage_assessment_question(session, question, current_user):
            raise HTTPException(status_code=403, detail={"code": "question_forbidden", "message": "question is unavailable"})
        version = append_question_version(
            session,
            question=question,
            owner_public_id=current_user.public_id,
            expected_current_version_id=payload.expected_current_version_id,
            version=payload.version,
        )
        question.status = "draft"
        session.commit()
        return {"question_id": question.id, "question_version": learner_question_payload(version, question)}

    try:
        return await run_db_op(operation)
    except AssessmentCoreError as exc:
        raise _assessment_error(exc) from exc


@router.post("/assessment/questions/{question_id}/status")
async def set_assessment_question_status(
    question_id: str, payload: QuestionStatusUpdate,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        question = session.query(DBAssessmentQuestion).filter_by(id=question_id).first()
        if question is None:
            raise HTTPException(status_code=404, detail={"code": "question_unknown", "message": "question does not exist"})
        if not _can_manage_assessment_question(session, question, current_user):
            raise HTTPException(status_code=403, detail={"code": "question_forbidden", "message": "question is unavailable"})
        if question.current_version_id != payload.expected_current_version_id:
            raise HTTPException(status_code=409, detail={"code": "question_version_conflict", "message": "question current version changed"})
        question.status = payload.status
        session.commit()
        return {"question_id": question.id, "status": question.status, "current_version_id": question.current_version_id}

    return await run_db_op(operation)


@router.get("/assessment/questions/{version_id}")
async def get_assessment_question(
    version_id: str, current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        version = session.query(DBAssessmentQuestionVersion).filter_by(id=version_id).first()
        if version is None:
            raise HTTPException(status_code=404, detail={"code": "question_version_unknown", "message": "question version does not exist"})
        question = session.query(DBAssessmentQuestion).filter_by(id=version.question_id).one()
        if not _assessment_question_readable(session, question, current_user):
            raise HTTPException(status_code=403, detail={"code": "question_forbidden", "message": "question is unavailable"})
        return _assessment_question_bundle(session, question, version)

    return await run_db_op(operation)


@router.post("/assessment/cat/next")
async def get_next_cat_question(
    payload: CatSelectionInput,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        query = session.query(DBAssessmentQuestion).filter(
            DBAssessmentQuestion.status == "approved",
            DBAssessmentQuestion.current_version_id.is_not(None),
        )
        if payload.course_id:
            query = query.filter(DBAssessmentQuestion.course_id == payload.course_id)
        questions = [item for item in query.all() if _assessment_question_readable(session, item, current_user)]
        candidates = []
        for question in questions:
            version = session.query(DBAssessmentQuestionVersion).filter_by(id=question.current_version_id).one()
            candidates.append((question, version))
        selected, trace, ability = select_cat_question(
            session,
            owner_public_id=current_user.public_id,
            course_id=payload.course_id,
            candidates=candidates,
            excluded_version_ids=payload.excluded_version_ids,
        )
        question = session.query(DBAssessmentQuestion).filter_by(id=selected.question_id).one()
        session.commit()
        return {
            "schema_version": "next.assessment-cat.v1",
            "question": _assessment_question_bundle(session, question, selected),
            "selection": {
                "id": trace.id,
                "algorithm_version": trace.algorithm_version,
                "candidate_count": len(trace.candidate_metrics or []),
                "selected_information": next(item["information"] for item in trace.candidate_metrics if item["question_version_id"] == selected.id),
                "trace_hash": trace.trace_hash,
                "reason": "系统比较未完成题目对当前三维能力估计的信息增益，选择预计最能减少不确定性的题目。",
                "ability_before": trace.ability_before,
            },
            "ability": ability_state_payload(ability),
            "ability_explanation": _ability_explanation(ability_state_payload(ability)),
        }

    try:
        return await run_db_op(operation)
    except AssessmentCoreError as exc:
        raise _assessment_error(exc) from exc


@router.get("/assessment/ability")
async def get_assessment_ability(
    course_id: str | None = None,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        row = session.query(DBAssessmentAbilityState).filter_by(
            owner_public_id=current_user.public_id,
            course_scope=course_id or "__global__",
        ).first()
        payload = ability_state_payload(row) if row else {
            "course_id": course_id, "theta": [0.0, 0.0, 0.0], "theta_std": [1.0, 1.0, 1.0],
            "theta_cov": [], "response_count": 0, "lock_version": 0, "last_attempt_id": None,
        }
        return {**payload, "explanation": _ability_explanation(payload)}

    return await run_db_op(operation)


@router.get("/profile-summary")
async def get_profile_summary(
    course_id: str,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        return build_profile_summary(session, current_user=current_user, course_id=course_id)

    try:
        return await run_db_op(operation)
    except ProfileSummaryError as exc:
        status_code = 404 if exc.code == "course_not_found" else 403 if exc.code == "course_forbidden" else 409
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


@router.get("/personal-activity")
async def get_personal_activity(
    course_id: str | None = None,
    days: int = 30,
    offset: int = 0,
    limit: int = 20,
    kind: str | None = None,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        return build_personal_activity(
            session,
            current_user=current_user,
            course_id=course_id,
            days=days,
            offset=offset,
            limit=limit,
            kind=kind,
        )

    try:
        return await run_db_op(operation)
    except ProfileSummaryError as exc:
        status_code = 404 if exc.code == "course_not_found" else 403 if exc.code == "course_forbidden" else 422
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


@router.post("/assessment/attempts", status_code=201)
async def submit_assessment_attempt(
    request: Request, payload: AttemptInput,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        version = session.query(DBAssessmentQuestionVersion).filter_by(id=payload.question_version_id).first()
        if version is None:
            raise HTTPException(status_code=404, detail={"code": "question_version_unknown", "message": "question version does not exist"})
        question = session.query(DBAssessmentQuestion).filter_by(id=version.question_id).one()
        if not _assessment_question_readable(session, question, current_user):
            raise HTTPException(status_code=403, detail={"code": "question_forbidden", "message": "question is unavailable"})
        if question.question_type == "code" and not SANDBOX_RUNNER.execution_enabled:
            raise HTTPException(status_code=503, detail={
                "code": "code_runtime_unavailable",
                "message": SANDBOX_RUNNER.status_message(),
            })
        attempt, created = record_attempt(session, owner_public_id=current_user.public_id, attempt=payload)
        if payload.mode == "practice" and attempt.grading_status == "graded" and attempt.correct is False:
            tags = [str(item) for item in (version.misconception_tags or []) if str(item)]
            ensure_legacy_misconception_candidate(
                session,
                owner_public_id=current_user.public_id,
                attempt_id=attempt.id,
                category="concept_confusion" if tags else "insufficient_evidence",
                rationale=(
                    "系统依据正式题目版本给出待学生确认的错因候选。"
                    if tags else "当前证据不足，需学生确认或修正错因。"
                ),
                evidence={
                    "origin": "canonical_question_version",
                    "question_version_id": version.id,
                    "misconception_tags": tags,
                    "evidence_kind": "system_candidate",
                },
                model_confidence=None,
            )
        learning_evidence = (
            record_canonical_attempt_evidence(
                session,
                attempt=attempt,
                user=current_user,
            )
            if attempt.grading_status == "graded"
            else None
        )
        session.commit()
        return {
            "attempt": _assessment_attempt_bundle(session, attempt),
            "created": created,
            "learning_evidence": learning_evidence,
            "question_type": question.question_type,
            "version": {
                "id": version.id,
                "prompt": learner_safe_prompt(version.prompt),
                "answer_key": version.answer_key,
                "scoring_rule": version.scoring_rule,
            },
        }

    try:
        initial = await run_db_op(operation)
        attempt = initial["attempt"]
        question_type = initial["question_type"]
        if not initial["created"] or question_type not in {"short_answer", "code", "open_task"}:
            return {
                **attempt,
                "created": initial["created"],
                "learning_evidence": initial["learning_evidence"],
            }
        trace_id = f"next-assessment-{uuid.uuid4().hex}"
        if question_type == "code":
            version_data = initial["version"]
            version_stub = DBAssessmentQuestionVersion(
                id=version_data["id"], prompt=version_data["prompt"],
                answer_key=version_data["answer_key"], scoring_rule=version_data["scoring_rule"],
            )
            result = await grade_code_submission(version_stub, payload.answer, SANDBOX_RUNNER)

            def save_code(session):
                row, _ = persist_code_grading(session, attempt_id=attempt["id"], result=result, trace_id=trace_id)
                persisted_attempt = session.query(DBAssessmentAttempt).filter_by(id=attempt["id"]).one()
                learning_evidence = record_canonical_attempt_evidence(
                    session,
                    attempt=persisted_attempt,
                    user=current_user,
                )
                session.commit()
                return {
                    **_assessment_attempt_bundle(session, persisted_attempt),
                    "learning_evidence": learning_evidence,
                }

            return {**await run_db_op(save_code), "created": True}

        def prompt_data(session):
            version = session.query(DBAssessmentQuestionVersion).filter_by(id=payload.question_version_id).one()
            return ai_grading_prompt(version, payload.answer)

        system_prompt, user_prompt, rubric_version, rubric = await run_db_op(prompt_data)
        try:
            llm = build_swarm_from_headers(request.headers).llm
            output = await _call_quiz_model(
                llm,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=AIGradingOutput,
                owner_public_id=current_user.public_id,
                operation="canonical_grade",
                trace_id=trace_id,
            )

            def save_ai(session):
                persist_ai_grading(
                    session,
                    attempt_id=attempt["id"],
                    output=AIGradingOutput.model_validate(output),
                    trace_id=trace_id,
                )
                persisted_attempt = session.query(DBAssessmentAttempt).filter_by(id=attempt["id"]).one()
                learning_evidence = record_canonical_attempt_evidence(
                    session,
                    attempt=persisted_attempt,
                    user=current_user,
                )
                session.commit()
                return {
                    **_assessment_attempt_bundle(session, persisted_attempt),
                    "learning_evidence": learning_evidence,
                }

            return {**await run_db_op(save_ai), "created": True}
        except Exception:
            def save_failure(session):
                persist_failed_ai_grading(
                    session,
                    attempt_id=attempt["id"],
                    rubric_version=rubric_version,
                    rubric_snapshot=rubric,
                    trace_id=trace_id,
                    error_code="ai_grading_unavailable",
                )
                persisted_attempt = session.query(DBAssessmentAttempt).filter_by(id=attempt["id"]).one()
                session.commit()
                return {
                    **_assessment_attempt_bundle(session, persisted_attempt),
                    "learning_evidence": None,
                }

            return {**await run_db_op(save_failure), "created": True}
    except AssessmentCoreError as exc:
        raise _assessment_error(exc) from exc


@router.get("/workspace/exercises/{question_version_id}")
async def get_workspace_exercise(
    question_version_id: str, current_user: DBUser = Depends(get_current_user),
):
    """Return the existing canonical question contract for the workspace renderer."""
    def operation(session):
        version = session.query(DBAssessmentQuestionVersion).filter_by(id=question_version_id).first()
        if version is None:
            raise HTTPException(status_code=404, detail={"code": "question_version_unknown", "message": "question version does not exist"})
        question = session.query(DBAssessmentQuestion).filter_by(id=version.question_id).one()
        if not _assessment_question_readable(session, question, current_user):
            raise HTTPException(status_code=403, detail={"code": "question_forbidden", "message": "question is unavailable"})
        result = _assessment_question_bundle(session, question, version)
        latest_attempt = session.query(DBAssessmentAttempt).filter_by(
            owner_public_id=current_user.public_id,
            question_version_id=version.id,
            mode="practice",
        ).order_by(DBAssessmentAttempt.submitted_at.desc(), DBAssessmentAttempt.id.desc()).first()
        result["latest_attempt"] = _assessment_attempt_bundle(session, latest_attempt) if latest_attempt else None
        return result
    return await run_db_op(operation)


@router.get("/assessment/attempts/{attempt_id}")
async def get_assessment_attempt(
    attempt_id: str, current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        attempt = session.query(DBAssessmentAttempt).filter_by(id=attempt_id).first()
        if attempt is None:
            raise HTTPException(status_code=404, detail={"code": "attempt_unknown", "message": "assessment attempt does not exist"})
        if attempt.owner_public_id != current_user.public_id and normalize_role(current_user.role) != "admin":
            raise HTTPException(status_code=403, detail={"code": "attempt_forbidden", "message": "assessment attempt belongs to another owner"})
        return _assessment_attempt_bundle(session, attempt)

    return await run_db_op(operation)


@router.post("/assessment/exams", status_code=201)
async def create_formal_exam(
    payload: ExamCreateInput, current_user: DBUser = Depends(get_current_user),
):
    if normalize_role(current_user.role) not in {"teacher", "admin"}:
        raise HTTPException(status_code=403, detail={"code": "exam_create_forbidden", "message": "teacher or admin role required"})

    def operation(session):
        course = session.query(DBCourse).filter_by(id=payload.course_id).first()
        if course is None:
            raise HTTPException(status_code=404, detail={"code": "course_unknown", "message": "course does not exist"})
        from course_catalog import course_is_selectable
        if not course_is_selectable(session, course):
            raise HTTPException(status_code=409, detail={"code": "course_unavailable", "message": "course is not currently available for selection"})
        if normalize_role(current_user.role) != "admin" and course.owner_public_id != current_user.public_id and active_course_role(
            session, course_id=course.id, user_public_id=current_user.public_id,
        ) not in {"admin", "teacher", "assistant"}:
            raise HTTPException(status_code=403, detail={"code": "course_forbidden", "message": "course is unavailable"})
        exam, _, _ = create_exam(session, owner_public_id=current_user.public_id, payload=payload)
        session.commit()
        return exam_payload(session, exam)

    try:
        return await run_db_op(operation)
    except FormalExamError as exc:
        raise _formal_exam_error(exc) from exc


@router.get("/assessment/exam-gate")
async def get_intelligent_exam_gate(
    course_id: str,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        course = session.query(DBCourse).filter_by(id=course_id).first()
        if course is None:
            raise HTTPException(status_code=404, detail={"code": "course_unknown", "message": "课程不存在"})
        if not _course_is_readable(session, course, current_user):
            raise HTTPException(status_code=409, detail={"code": "course_unavailable", "message": "当前课程没有可用学习资料"})
        return exam_gate_status(session, owner_public_id=current_user.public_id, course_id=course_id)
    return await run_db_op(operation)


@router.get("/assessment/intelligent-exams/context")
async def get_intelligent_exam_context(
    course_id: str,
    current_user: DBUser = Depends(get_current_user),
):
    if normalize_role(current_user.role) != "student":
        raise HTTPException(
            status_code=403,
            detail={"code": "intelligent_exam_student_required", "message": "智能组卷仅面向学生学习闭环。"},
        )

    def operation(session):
        course = session.query(DBCourse).filter_by(id=course_id).first()
        if course is None:
            raise HTTPException(status_code=404, detail={"code": "course_unknown", "message": "课程不存在。"})
        if not _course_is_readable(session, course, current_user):
            raise HTTPException(status_code=403, detail={"code": "course_forbidden", "message": "当前课程不可用。"})
        context = intelligent_exam_context(
            session,
            owner_public_id=current_user.public_id,
            course_id=course_id,
        )
        if _local_assessment_demo_mode():
            context["question_type_counts"] = {
                **context["question_type_counts"],
                "short_answer": 0,
            }
            context["external_model_required"] = False
            context["llm_generation_required"] = False
        return {
            **context,
            "gate": exam_gate_status(
                session,
                owner_public_id=current_user.public_id,
                course_id=course_id,
            ),
        }

    try:
        return await run_db_op(operation)
    except FormalExamError as exc:
        raise _formal_exam_error(exc) from exc


async def _create_configured_intelligent_exam(
    *,
    config: IntelligentExamConfigInput,
    current_user: DBUser,
) -> dict[str, Any]:
    def operation(session):
        llm = _build_governed_assessment_llm()
        if llm is None and int(config.question_type_counts.get("short_answer", 0)):
            raise FormalExamError(
                "intelligent_exam_demo_subjective_unsupported",
                "本地演示模式暂不提供主观题模型评分，请选择客观题完成组卷。",
            )
        review_plan = None
        if config.review_task_id:
            if not config.review_task_id.startswith("review-plan:"):
                raise FormalExamError("review_task_invalid", "复习任务标识无效。")
            try:
                plan_id = int(config.review_task_id.split(":", 1)[1])
            except ValueError as exc:
                raise FormalExamError("review_task_invalid", "复习任务标识无效。") from exc
            review_plan = session.get(DBReviewPlan, plan_id)
            if review_plan is None or review_plan.student_id != current_user.username:
                raise FormalExamError("review_task_forbidden", "复习任务不属于当前学习者。")
            gate = {"unlocked": True, "reason": "review_task", "message": "复习任务已进入智能组卷。"}
        else:
            gate = require_exam_gate(
                session,
                owner_public_id=current_user.public_id,
                course_id=config.course_id,
            )
        existing = session.query(DBAssessmentExam).filter_by(
            owner_public_id=current_user.public_id,
            generation_key=config.idempotency_key,
        ).first()
        if existing is not None:
            version = session.query(DBAssessmentExamVersion).filter_by(
                id=existing.current_version_id,
            ).one()
            if version.configuration != config.model_dump(mode="json"):
                raise FormalExamError(
                    "intelligent_exam_idempotency_conflict",
                    "该生成键已绑定到另一份组卷配置。",
                )
            sitting = session.query(DBAssessmentExamSitting).filter_by(
                exam_id=existing.id,
                owner_public_id=current_user.public_id,
            ).one()
            return {
                **_learner_exam_payload(
                    session, exam=existing, user=current_user, sitting=sitting,
                ),
                "gate": gate,
                "created": False,
            }

        create_payload = build_intelligent_exam_input(
            session,
            owner_public_id=current_user.public_id,
            config=config,
            llm=llm,
        )
        exam, _, _ = create_exam(
            session,
            owner_public_id=current_user.public_id,
            payload=create_payload,
        )
        transition_exam(
            session,
            exam=exam,
            target="published",
            expected_lock_version=exam.lock_version,
            actor_public_id=current_user.public_id,
        )
        sitting, _ = assign_sitting(
            session,
            exam=exam,
            learner_public_id=current_user.public_id,
            actor_public_id=current_user.public_id,
        )
        transition_exam(
            session,
            exam=exam,
            target="open",
            expected_lock_version=exam.lock_version,
            actor_public_id=current_user.public_id,
        )
        session.commit()
        return {
            **_learner_exam_payload(session, exam=exam, user=current_user, sitting=sitting),
            "gate": gate,
            "created": True,
        }

    return await run_db_op(operation)


async def _submit_learner_generated_exam(
    *,
    sitting_id: str,
    expected_lock_version: int,
    current_user: DBUser,
) -> dict[str, Any]:
    def operation(session):
        sitting = session.query(DBAssessmentExamSitting).filter_by(id=sitting_id).first()
        if sitting is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "sitting_unknown", "message": "exam sitting does not exist"},
            )
        exam = session.query(DBAssessmentExam).filter_by(id=sitting.exam_id).one()
        if not _is_learner_generated_exam(exam, current_user):
            raise FormalExamError("sitting_forbidden", "exam sitting belongs to another owner")

        review_task_id = _review_task_id_for_exam(session, exam)
        gate = (
            {"unlocked": True, "reason": "review_task", "message": "复习任务已进入智能组卷。"}
            if review_task_id
            else require_exam_gate(
                session,
                owner_public_id=current_user.public_id,
                course_id=exam.course_id,
            )
        )
        event_key = f"formal-exam-submission:{sitting.id}"
        event = session.query(DBLearningEvent).filter_by(
            owner_public_id=current_user.public_id,
            idempotency_key=event_key,
        ).first()
        report = session.query(DBAssessmentExamReport).filter_by(
            sitting_id=sitting.id,
        ).order_by(
            DBAssessmentExamReport.report_version.desc(),
            DBAssessmentExamReport.id.desc(),
        ).first()

        if sitting.status not in {"submitted", "released"}:
            finalize_formal_response_drafts(
                session,
                sitting=sitting,
                owner_public_id=current_user.public_id,
                llm=_build_governed_assessment_llm(),
            )
            submit_sitting(
                session,
                sitting=sitting,
                owner_public_id=current_user.public_id,
                expected_lock_version=expected_lock_version,
            )
            if exam.status == "open":
                transition_exam(
                    session,
                    exam=exam,
                    target="closed",
                    expected_lock_version=exam.lock_version,
                    actor_public_id=current_user.public_id,
                )
            report, _ = generate_report(
                session,
                sitting=sitting,
                actor_public_id=current_user.public_id,
            )

        if report is None:
            report, _ = generate_report(
                session,
                sitting=sitting,
                actor_public_id=current_user.public_id,
            )
        event_payload = _formal_exam_event_payload(
            exam=exam,
            sitting=sitting,
            report=report,
        )
        if not event_payload["graded"]:
            raise FormalExamError(
                "formal_exam_grading_incomplete",
                "formal exam grading must finish before feedback aggregation",
            )
        if event is None:
            event, _ = record_learning_event(
                session,
                owner_public_id=current_user.public_id,
                user=current_user,
                trusted_source=True,
                event=LearningEventInput(
                    idempotency_key=event_key,
                    event_type="formal_exam_submitted",
                    context=ContextRef(
                        userId=current_user.public_id,
                        courseId=exam.course_id,
                    ),
                    course_id=exam.course_id,
                    object_type="assessment_exam_sitting",
                    object_id=sitting.id,
                    source="backend",
                    occurred_at=(sitting.submitted_at or datetime.now(timezone.utc)).replace(
                        tzinfo=timezone.utc
                    ),
                    payload=event_payload,
                ),
            )
        session.commit()

        consumption = get_learning_aggregation(session, event_id=event.id)
        if consumption is None or consumption.status != "processed":
            try:
                process_path_event(session, event=event)
            except Exception:
                # The aggregator persists its failed step before raising. The response exposes that
                # recoverable state, and a repeated submit resumes the same immutable event.
                pass
        return {
            **_formal_exam_submission_bundle(
                session,
                exam=exam,
                sitting=sitting,
                report=report,
                event=event,
            ),
            "gate": gate,
        }

    return await run_db_op(operation)


@router.post("/assessment/intelligent-exams", status_code=201)
async def create_intelligent_exam(
    payload: IntelligentExamCreateRequest,
    current_user: DBUser = Depends(get_current_user),
):
    if normalize_role(current_user.role) != "student":
        raise HTTPException(
            status_code=403,
            detail={"code": "intelligent_exam_student_required", "message": "智能组卷由学生在学习闭环中发起"},
        )
    if payload.configuration is not None:
        try:
            return await _create_configured_intelligent_exam(
                config=payload.configuration,
                current_user=current_user,
            )
        except ExamGateError as exc:
            raise _exam_gate_error(exc) from exc
        except FormalExamError as exc:
            raise _formal_exam_error(exc) from exc
        except AssessmentCoreError as exc:
            raise _assessment_error(exc) from exc
    if not payload.course_id:
        raise HTTPException(
            status_code=422,
            detail={"code": "intelligent_exam_course_required", "message": "请选择课程。"},
        )
    title = " ".join(payload.title.split())
    if not title or len(title) > 256:
        raise HTTPException(status_code=422, detail={"code": "intelligent_exam_title_invalid", "message": "试卷名称不能为空且不得超过 256 字"})
    if not 1 <= payload.duration_minutes <= 1440:
        raise HTTPException(status_code=422, detail={"code": "intelligent_exam_duration_invalid", "message": "考试时长必须在 1 到 1440 分钟之间"})
    version_ids = list(dict.fromkeys(payload.question_version_ids))
    if not 1 <= len(version_ids) <= 100:
        raise HTTPException(status_code=422, detail={"code": "intelligent_exam_question_count", "message": "智能组卷需选择 1 到 100 道题"})

    def operation(session):
        gate = require_exam_gate(
            session,
            owner_public_id=current_user.public_id,
            course_id=payload.course_id,
        )
        base_points = round(100 / len(version_ids), 2)
        item_points = [base_points] * len(version_ids)
        item_points[-1] = round(100 - sum(item_points[:-1]), 2)
        exam, _, _ = create_exam(
            session,
            owner_public_id=current_user.public_id,
            payload=ExamCreateInput(
                course_id=payload.course_id,
                title=title,
                instructions="根据当前课程、知识点范围与今日学习证据生成；题目版本已冻结。",
                duration_minutes=payload.duration_minutes,
                feedback_policy="after_submission",
                items=tuple(
                    ExamItemInput(question_version_id=version_id, points=item_points[index], required=True)
                    for index, version_id in enumerate(version_ids)
                ),
            ),
        )
        transition_exam(
            session,
            exam=exam,
            target="published",
            expected_lock_version=exam.lock_version,
            actor_public_id=current_user.public_id,
        )
        sitting, _ = assign_sitting(
            session,
            exam=exam,
            learner_public_id=current_user.public_id,
            actor_public_id=current_user.public_id,
        )
        transition_exam(
            session,
            exam=exam,
            target="open",
            expected_lock_version=exam.lock_version,
            actor_public_id=current_user.public_id,
        )
        session.commit()
        return {
            **_learner_exam_payload(session, exam=exam, user=current_user, sitting=sitting),
            "gate": gate,
            "created": True,
        }

    try:
        return await run_db_op(operation)
    except ExamGateError as exc:
        raise _exam_gate_error(exc) from exc
    except FormalExamError as exc:
        raise _formal_exam_error(exc) from exc


@router.get("/assessment/exams")
async def list_formal_exams(current_user: DBUser = Depends(get_current_user)):
    def operation(session):
        items = []
        for exam in session.query(DBAssessmentExam).order_by(DBAssessmentExam.created_at.desc()).all():
            sitting = session.query(DBAssessmentExamSitting).filter_by(exam_id=exam.id, owner_public_id=current_user.public_id).first()
            if _can_manage_exam(session, exam, current_user) or sitting is not None:
                data = _learner_exam_payload(
                    session, exam=exam, user=current_user, sitting=sitting,
                )
                if sitting is not None and sitting.owner_public_id == current_user.public_id:
                    data["responses"] = [{
                        "exam_item_id": response.exam_item_id,
                        "attempt": _assessment_attempt_bundle(
                            session, session.query(DBAssessmentAttempt).filter_by(id=response.attempt_id).one(),
                        ),
                    } for response in session.query(DBAssessmentExamResponse).filter_by(sitting_id=sitting.id).all()]
                items.append(data)
        return {"schema_version": "next.formal-exam-catalog.v1", "items": items}

    return await run_db_op(operation)


@router.get("/assessment/exams/{exam_id}")
async def get_formal_exam(exam_id: str, current_user: DBUser = Depends(get_current_user)):
    def operation(session):
        exam = session.query(DBAssessmentExam).filter_by(id=exam_id).first()
        if exam is None:
            raise HTTPException(status_code=404, detail={"code": "exam_unknown", "message": "exam does not exist"})
        sitting = session.query(DBAssessmentExamSitting).filter_by(exam_id=exam.id, owner_public_id=current_user.public_id).first()
        if not _can_manage_exam(session, exam, current_user) and sitting is None:
            raise HTTPException(status_code=403, detail={"code": "exam_forbidden", "message": "exam is unavailable"})
        return _learner_exam_payload(
            session, exam=exam, user=current_user, sitting=sitting,
        )

    return await run_db_op(operation)


@router.post("/assessment/exams/{exam_id}/transition")
async def transition_formal_exam(
    exam_id: str, payload: ExamTransitionRequest,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        exam = session.query(DBAssessmentExam).filter_by(id=exam_id).first()
        if exam is None:
            raise HTTPException(status_code=404, detail={"code": "exam_unknown", "message": "exam does not exist"})
        if not _can_manage_exam(session, exam, current_user):
            raise HTTPException(status_code=403, detail={"code": "exam_forbidden", "message": "exam is unavailable"})
        transition_exam(session, exam=exam, target=payload.target_status,
                        expected_lock_version=payload.expected_lock_version, actor_public_id=current_user.public_id)
        session.commit()
        return exam_payload(session, exam)
    try:
        return await run_db_op(operation)
    except FormalExamError as exc:
        raise _formal_exam_error(exc) from exc


@router.post("/assessment/exams/{exam_id}/assignments", status_code=201)
async def assign_formal_exam(
    exam_id: str, payload: ExamAssignRequest,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        exam = session.query(DBAssessmentExam).filter_by(id=exam_id).first()
        if exam is None:
            raise HTTPException(status_code=404, detail={"code": "exam_unknown", "message": "exam does not exist"})
        if not _can_manage_exam(session, exam, current_user):
            raise HTTPException(status_code=403, detail={"code": "exam_forbidden", "message": "exam is unavailable"})
        learner = session.query(DBUser).filter_by(public_id=payload.learner_public_id).first()
        if learner is None:
            raise HTTPException(status_code=404, detail={"code": "learner_unknown", "message": "learner does not exist"})
        if active_course_role(session, course_id=exam.course_id, user_public_id=learner.public_id) is None:
            raise HTTPException(status_code=403, detail={"code": "learner_course_forbidden", "message": "learner is not an active course member"})
        sitting, created = assign_sitting(session, exam=exam, learner_public_id=learner.public_id, actor_public_id=current_user.public_id)
        session.commit()
        return {**sitting_payload(session, sitting), "created": created}
    try:
        return await run_db_op(operation)
    except FormalExamError as exc:
        raise _formal_exam_error(exc) from exc


@router.get("/assessment/exam-sittings")
async def list_formal_exam_sittings(current_user: DBUser = Depends(get_current_user)):
    def operation(session):
        rows = session.query(DBAssessmentExamSitting).filter_by(owner_public_id=current_user.public_id).order_by(DBAssessmentExamSitting.created_at.desc()).all()
        return {"schema_version": "next.formal-exam-sittings.v1", "items": [sitting_payload(session, row) for row in rows]}
    return await run_db_op(operation)


@router.post("/assessment/exam-sittings/{sitting_id}/start")
async def start_formal_exam_sitting(
    sitting_id: str, payload: SittingTransitionRequest,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        sitting = session.query(DBAssessmentExamSitting).filter_by(id=sitting_id).first()
        if sitting is None:
            raise HTTPException(status_code=404, detail={"code": "sitting_unknown", "message": "exam sitting does not exist"})
        exam = session.query(DBAssessmentExam).filter_by(id=sitting.exam_id).one()
        if normalize_role(current_user.role) == "student" and exam.owner_public_id == current_user.public_id:
            require_exam_gate(
                session,
                owner_public_id=current_user.public_id,
                course_id=exam.course_id,
            )
        start_sitting(session, sitting=sitting, owner_public_id=current_user.public_id,
                      expected_lock_version=payload.expected_lock_version)
        session.commit()
        return sitting_payload(session, sitting)
    try:
        return await run_db_op(operation)
    except ExamGateError as exc:
        raise _exam_gate_error(exc) from exc
    except FormalExamError as exc:
        raise _formal_exam_error(exc) from exc


@router.post("/assessment/exam-sittings/{sitting_id}/responses", status_code=201)
async def submit_formal_exam_response(
    request: Request, sitting_id: str, payload: FormalResponseInput,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        sitting = session.query(DBAssessmentExamSitting).filter_by(id=sitting_id).first()
        if sitting is None:
            raise HTTPException(status_code=404, detail={"code": "sitting_unknown", "message": "exam sitting does not exist"})
        exam = session.query(DBAssessmentExam).filter_by(id=sitting.exam_id).one()
        if _is_learner_generated_exam(exam, current_user):
            draft, created = save_formal_response_draft(
                session,
                sitting=sitting,
                owner_public_id=current_user.public_id,
                payload=payload,
            )
            session.commit()
            return {
                "learner_draft": True,
                "draft": formal_draft_payload(draft),
                "created": created,
                "sitting": sitting_payload(session, sitting),
            }
        response, attempt, created = submit_formal_response(
            session, sitting=sitting, owner_public_id=current_user.public_id, payload=payload,
        )
        version = session.query(DBAssessmentQuestionVersion).filter_by(id=attempt.question_version_id).one()
        question = session.query(DBAssessmentQuestion).filter_by(id=version.question_id).one()
        if question.question_type == "code" and not SANDBOX_RUNNER.execution_enabled:
            raise HTTPException(status_code=503, detail={"code": "code_runtime_unavailable", "message": SANDBOX_RUNNER.status_message()})
        session.commit()
        return {
            "response_id": response.id, "attempt": _assessment_attempt_bundle(session, attempt),
            "created": created, "question_type": question.question_type,
            "version": {"id": version.id, "prompt": learner_safe_prompt(version.prompt),
                        "answer_key": version.answer_key, "scoring_rule": version.scoring_rule},
        }
    try:
        initial = await run_db_op(operation)
        if initial.get("learner_draft"):
            initial.pop("learner_draft", None)
            return initial
        response_id = initial["response_id"]
        attempt = initial["attempt"]
        question_type = initial["question_type"]
        if not initial["created"] or question_type not in {"short_answer", "code", "open_task"}:
            return {"response_id": response_id, "attempt": attempt, "created": initial["created"]}
        trace_id = f"next-formal-exam-{uuid.uuid4().hex}"
        if question_type == "code":
            version_data = initial["version"]
            version_stub = DBAssessmentQuestionVersion(
                id=version_data["id"], prompt=version_data["prompt"],
                answer_key=version_data["answer_key"], scoring_rule=version_data["scoring_rule"],
            )
            result = await grade_code_submission(version_stub, payload.answer, SANDBOX_RUNNER)

            def save_code(session):
                persist_code_grading(session, attempt_id=attempt["id"], result=result, trace_id=trace_id)
                row = session.query(DBAssessmentAttempt).filter_by(id=attempt["id"]).one()
                session.commit()
                return _assessment_attempt_bundle(session, row)
            return {"response_id": response_id, "attempt": await run_db_op(save_code), "created": True}

        def prompt_data(session):
            version = session.query(DBAssessmentQuestionVersion).filter_by(id=attempt["question_version_id"]).one()
            return ai_grading_prompt(version, payload.answer)
        system_prompt, user_prompt, rubric_version, rubric = await run_db_op(prompt_data)
        try:
            output = await _call_quiz_model(
                build_swarm_from_headers(request.headers).llm,
                system_prompt=system_prompt, user_prompt=user_prompt,
                response_model=AIGradingOutput, owner_public_id=current_user.public_id,
                operation="formal_exam_grade", trace_id=trace_id,
            )
            def save_ai(session):
                persist_ai_grading(session, attempt_id=attempt["id"],
                                   output=AIGradingOutput.model_validate(output), trace_id=trace_id)
                row = session.query(DBAssessmentAttempt).filter_by(id=attempt["id"]).one()
                session.commit()
                return _assessment_attempt_bundle(session, row)
            persisted = await run_db_op(save_ai)
        except Exception:
            def save_failure(session):
                persist_failed_ai_grading(
                    session, attempt_id=attempt["id"], rubric_version=rubric_version,
                    rubric_snapshot=rubric, trace_id=trace_id, error_code="ai_grading_unavailable",
                )
                row = session.query(DBAssessmentAttempt).filter_by(id=attempt["id"]).one()
                session.commit()
                return _assessment_attempt_bundle(session, row)
            persisted = await run_db_op(save_failure)
        return {"response_id": response_id, "attempt": persisted, "created": True}
    except (FormalExamError, AssessmentCoreError) as exc:
        raise (_formal_exam_error(exc) if isinstance(exc, FormalExamError) else _assessment_error(exc)) from exc


@router.post("/assessment/exam-sittings/{sitting_id}/submit")
async def submit_formal_exam_sitting(
    sitting_id: str, payload: SittingTransitionRequest,
    current_user: DBUser = Depends(get_current_user),
):
    if normalize_role(current_user.role) == "student":
        def is_learner_generated(session):
            sitting = session.query(DBAssessmentExamSitting).filter_by(id=sitting_id).first()
            if sitting is None:
                return False
            exam = session.query(DBAssessmentExam).filter_by(id=sitting.exam_id).first()
            return bool(exam and exam.owner_public_id == current_user.public_id)

        learner_generated = await run_db_op(is_learner_generated)
        if learner_generated:
            try:
                return await _submit_learner_generated_exam(
                    sitting_id=sitting_id,
                    expected_lock_version=payload.expected_lock_version,
                    current_user=current_user,
                )
            except ExamGateError as exc:
                raise _exam_gate_error(exc) from exc
            except FormalExamError as exc:
                raise _formal_exam_error(exc) from exc
            except AssessmentCoreError as exc:
                raise _assessment_error(exc) from exc
            except M5LearningError as exc:
                raise _learning_error(exc) from exc

    def operation(session):
        sitting = session.query(DBAssessmentExamSitting).filter_by(id=sitting_id).first()
        if sitting is None:
            raise HTTPException(status_code=404, detail={"code": "sitting_unknown", "message": "exam sitting does not exist"})
        exam = session.query(DBAssessmentExam).filter_by(id=sitting.exam_id).one()
        if normalize_role(current_user.role) == "student" and exam.owner_public_id == current_user.public_id:
            require_exam_gate(
                session,
                owner_public_id=current_user.public_id,
                course_id=exam.course_id,
            )
        submit_sitting(session, sitting=sitting, owner_public_id=current_user.public_id,
                       expected_lock_version=payload.expected_lock_version)
        if exam.owner_public_id == current_user.public_id and exam.status == "open":
            transition_exam(
                session,
                exam=exam,
                target="closed",
                expected_lock_version=exam.lock_version,
                actor_public_id=current_user.public_id,
            )
        session.commit()
        return sitting_payload(session, sitting)
    try:
        return await run_db_op(operation)
    except ExamGateError as exc:
        raise _exam_gate_error(exc) from exc
    except FormalExamError as exc:
        raise _formal_exam_error(exc) from exc


@router.post("/assessment/exam-sittings/{sitting_id}/reviews", status_code=201)
async def request_formal_exam_review(
    sitting_id: str, payload: ExamReviewRequest,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        sitting = session.query(DBAssessmentExamSitting).filter_by(id=sitting_id).first()
        if sitting is None:
            raise HTTPException(status_code=404, detail={"code": "sitting_unknown", "message": "exam sitting does not exist"})
        if sitting.owner_public_id != current_user.public_id:
            raise HTTPException(status_code=403, detail={"code": "sitting_forbidden", "message": "exam sitting belongs to another owner"})
        review, created = request_review(session, sitting=sitting, attempt_id=payload.attempt_id,
                                         requested_by_public_id=current_user.public_id, reason=payload.reason)
        session.commit()
        return {"id": review.id, "status": review.status, "lock_version": review.lock_version, "created": created}
    try:
        return await run_db_op(operation)
    except FormalExamError as exc:
        raise _formal_exam_error(exc) from exc


@router.get("/assessment/exam-reviews")
async def list_formal_exam_reviews(current_user: DBUser = Depends(get_current_user)):
    if normalize_role(current_user.role) not in {"teacher", "admin"}:
        raise HTTPException(status_code=403, detail={"code": "review_queue_forbidden", "message": "teacher or admin role required"})
    def operation(session):
        items = []
        for review in session.query(DBAssessmentReviewCase).order_by(DBAssessmentReviewCase.created_at.desc()).all():
            sitting = session.query(DBAssessmentExamSitting).filter_by(id=review.sitting_id).one()
            exam = session.query(DBAssessmentExam).filter_by(id=sitting.exam_id).one()
            if _can_manage_exam(session, exam, current_user):
                items.append({"id": review.id, "sitting_id": review.sitting_id, "attempt_id": review.attempt_id,
                              "status": review.status, "reason": review.reason,
                              "reviewer_public_id": review.reviewer_public_id,
                              "lock_version": review.lock_version})
        return {"schema_version": "next.formal-exam-review-queue.v1", "items": items}
    return await run_db_op(operation)


@router.post("/assessment/exam-reviews/{review_id}/complete")
async def complete_formal_exam_review(
    review_id: str, payload: HumanReviewRequest,
    current_user: DBUser = Depends(get_current_user),
):
    if normalize_role(current_user.role) not in {"teacher", "admin"}:
        raise HTTPException(status_code=403, detail={"code": "review_forbidden", "message": "teacher or admin role required"})
    def operation(session):
        review = session.query(DBAssessmentReviewCase).filter_by(id=review_id).first()
        if review is None:
            raise HTTPException(status_code=404, detail={"code": "review_unknown", "message": "review case does not exist"})
        sitting = session.query(DBAssessmentExamSitting).filter_by(id=review.sitting_id).one()
        exam = session.query(DBAssessmentExam).filter_by(id=sitting.exam_id).one()
        if not _can_manage_exam(session, exam, current_user):
            raise HTTPException(status_code=403, detail={"code": "review_forbidden", "message": "review case is unavailable"})
        result = complete_human_review(session, review=review, reviewer_public_id=current_user.public_id,
                                       expected_lock_version=payload.expected_lock_version, payload=payload.result)
        session.commit()
        return {"review_id": review.id, "status": review.status, "grading": grading_result_payload(result)}
    try:
        return await run_db_op(operation)
    except FormalExamError as exc:
        raise _formal_exam_error(exc) from exc


@router.post("/assessment/exam-sittings/{sitting_id}/reports")
async def generate_formal_exam_report(
    sitting_id: str, current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        sitting = session.query(DBAssessmentExamSitting).filter_by(id=sitting_id).first()
        if sitting is None:
            raise HTTPException(status_code=404, detail={"code": "sitting_unknown", "message": "exam sitting does not exist"})
        exam = session.query(DBAssessmentExam).filter_by(id=sitting.exam_id).one()
        if sitting.owner_public_id != current_user.public_id and not _can_manage_exam(session, exam, current_user):
            raise HTTPException(status_code=403, detail={"code": "report_forbidden", "message": "exam report is unavailable"})
        report, created = generate_report(session, sitting=sitting, actor_public_id=current_user.public_id)
        session.commit()
        return _formal_exam_report_response(
            session, report=report, sitting=sitting, exam=exam, created=created,
        )
    try:
        return await run_db_op(operation)
    except FormalExamError as exc:
        raise _formal_exam_error(exc) from exc


@router.get("/assessment/exam-reports/{report_id}")
async def get_formal_exam_report(report_id: str, current_user: DBUser = Depends(get_current_user)):
    def operation(session):
        report = session.query(DBAssessmentExamReport).filter_by(id=report_id).first()
        if report is None:
            raise HTTPException(status_code=404, detail={"code": "report_unknown", "message": "exam report does not exist"})
        sitting = session.query(DBAssessmentExamSitting).filter_by(id=report.sitting_id).one()
        exam = session.query(DBAssessmentExam).filter_by(id=sitting.exam_id).one()
        if sitting.owner_public_id != current_user.public_id and not _can_manage_exam(session, exam, current_user):
            raise HTTPException(status_code=403, detail={"code": "report_forbidden", "message": "exam report is unavailable"})
        return _formal_exam_report_response(
            session, report=report, sitting=sitting, exam=exam,
        )
    return await run_db_op(operation)


@router.get("/assessment/exam-reports/{report_id}/export/{format_name}")
async def export_formal_exam_report(
    report_id: str, format_name: Literal["json", "csv"],
    current_user: DBUser = Depends(get_current_user),
):
    data = await get_formal_exam_report(report_id, current_user)
    if format_name == "json":
        content = json.dumps(data, ensure_ascii=False, indent=2, default=str)
        media_type = "application/json"
    else:
        def load(session):
            return report_csv(session.query(DBAssessmentExamReport).filter_by(id=report_id).one())
        content = await run_db_op(load)
        media_type = "text/csv; charset=utf-8"
    return Response(content=content, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="exam-report-{report_id}.{format_name}"'})


@router.post("/assessment/attempts/{attempt_id}/misconception", status_code=201)
async def create_misconception_candidate(
    attempt_id: str, payload: MisconceptionCandidateInput,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        row = propose_misconception(
            session, owner_public_id=current_user.public_id,
            attempt_id=attempt_id, candidate=payload,
        )
        session.commit()
        return {"id": row.id, "status": row.status, "candidate_category": row.candidate_category, "model_confidence": row.model_confidence}

    try:
        return await run_db_op(operation)
    except AssessmentCoreError as exc:
        raise _assessment_error(exc) from exc


@router.post("/assessment/misconceptions/{review_id}/decision")
async def decide_misconception_candidate(
    review_id: str, payload: MisconceptionDecisionInput,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        existing = session.query(DBMisconceptionReview).filter_by(id=review_id).first()
        if existing is None:
            raise HTTPException(status_code=404, detail={"code": "misconception_unknown", "message": "misconception review does not exist"})
        if existing.owner_public_id != current_user.public_id:
            raise HTTPException(status_code=403, detail={"code": "misconception_forbidden", "message": "misconception review belongs to another owner"})
        attempt = session.query(DBAssessmentAttempt).filter_by(id=existing.attempt_id).one()
        version = session.query(DBAssessmentQuestionVersion).filter_by(id=attempt.question_version_id).one()
        question = session.query(DBAssessmentQuestion).filter_by(id=version.question_id).one()
        if not _assessment_question_readable(session, question, current_user):
            raise HTTPException(status_code=403, detail={"code": "course_forbidden", "message": "current account is not an active course member"})
        decision_created = existing.status == "proposed"
        row = decide_misconception(
            session, owner_public_id=current_user.public_id,
            review_id=review_id, decision=payload,
        )
        task = None
        task_created = False
        if row.status in {"accepted", "modified", "teacher_confirmed"}:
            task, task_created = schedule_delayed_retest(session, review=row)
        projections = project_misconception_decision(session, review=row, decision=payload)
        session.commit()
        return {
            "id": row.id, "status": row.status,
            "confirmed_category": row.confirmed_category,
            "decision_note": row.decision_note,
            "retest_task": retest_task_payload(task),
            "retest_task_created": task_created,
            "decision_created": decision_created,
            **projections,
        }

    try:
        return await run_db_op(operation)
    except AssessmentCoreError as exc:
        raise _assessment_error(exc) from exc


@router.get("/review-queue")
async def get_unified_review_queue(current_user: DBUser = Depends(get_current_user)):
    return {"schema_version": "m5.review-queue.v1", "items": await run_db_op(
        lambda session: review_queue(session, owner_public_id=current_user.public_id)
    )}


@router.get("/review-export")
async def export_review_diagnosis_material(current_user: DBUser = Depends(get_current_user)):
    """Export the learner's review summary without answers or secrets."""
    def operation(session):
        items = list(review_queue(session, owner_public_id=current_user.public_id))
        reviews = {
            row.id: row for row in session.query(DBMisconceptionReview).filter_by(
                owner_public_id=current_user.public_id,
            ).filter(DBMisconceptionReview.status.in_(
                ("accepted", "modified", "teacher_confirmed"),
            )).all()
        }
        lines = [
            "# EduMatrix 复习诊疗材料", "",
            "> 仅包含当前学习者自己的复习安排、错因分类和下一步建议；不包含题目答案、API Key、模型提示词或其他用户数据。",
            "", f"生成时间：{datetime.now(timezone.utc).isoformat()}",
            f"待处理项目：{len(items)}", "", "## 复习项目", "",
        ]
        if not items:
            lines.append("当前没有已确认的待复习项目。")
        for index, item in enumerate(items, 1):
            lines.extend([
                f"### {index}. {item.get('concept') or item.get('category') or '未命名知识点'}",
                f"- 来源：{item['source_type']}",
                f"- 状态：{item.get('status', 'unknown')}",
                f"- 计划时间：{item.get('due_at') or '待安排'}",
                f"- 进入原因：{item.get('reason') or '未提供'}",
                f"- 证据强度：{item.get('evidence_strength') or '未提供'}",
                f"- 下一步：{item.get('next_action') or '复习并提交反馈'}",
            ])
            review = reviews.get(item.get("source_id"))
            if review is not None and review.decision_note:
                lines.append(f"- 学习者备注：{review.decision_note}")
            lines.append("")
        lines.extend([
            "## 使用建议", "",
            "1. 先处理状态为 due 或 needs_review 的项目。",
            "2. 延迟复测通过后，系统才会形成稳定掌握证据；一次查看或主观声明不会直接改变掌握度。",
            "3. 完成 SM-2 复习后提交困难、一般或简单反馈，让现有调度器更新下一次复习时间。",
        ])
        return "\n".join(lines) + "\n"

    content = await run_db_op(operation)
    return Response(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": 'attachment; filename="edumatrix-review-diagnosis.md"'},
    )


@router.get("/assessment/retests/{task_id}")
async def get_delayed_retest_task(
    task_id: str, current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        task = session.query(DBAssessmentRetestTask).filter_by(id=task_id).first()
        if task is None:
            raise HTTPException(status_code=404, detail={"code": "retest_task_unknown", "message": "delayed retest task does not exist"})
        if task.owner_public_id != current_user.public_id:
            raise HTTPException(status_code=403, detail={"code": "retest_task_forbidden", "message": "delayed retest task belongs to another owner"})
        version = session.query(DBAssessmentQuestionVersion).filter_by(id=task.question_version_id).one()
        return {"task": retest_task_payload(task), "question": learner_question_payload(version)}

    return await run_db_op(operation)


@router.post("/assessment/retests/{task_id}/attempts")
async def submit_delayed_retest_attempt(
    task_id: str, payload: RetestAttemptInput,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        task, attempt, created = submit_delayed_retest(
            session, owner_public_id=current_user.public_id,
            task_id=task_id, submission=payload,
        )
        path_consumption = None
        if task.status == "completed":
            evidence = AssessmentEvidenceInput(
                idempotency_key=f"retest-pass-{task.id}-{attempt.id}",
                source_type="delayed_retest", source_object_id=task.id,
                attempt_id=attempt.id,
                course_id=task.course_id,
                target_object_type="assessment",
                target_object_id=task.question_version_id,
                occurred_at=task.completed_at.replace(tzinfo=timezone.utc),
                correct=True, delay_hours=24,
                confidence=attempt.confidence,
                actual_minutes=(
                    max(0, int(attempt.duration_seconds / 60))
                    if attempt.duration_seconds is not None else None
                ),
            )
            path_consumption = record_assessment_evidence(
                session,
                owner_public_id=current_user.public_id,
                evidence=evidence,
                user=current_user,
                trusted_source=True,
            )
        session.commit()
        return {
            "task": retest_task_payload(task),
            "attempt": learner_attempt_payload(attempt),
            "attempt_created": created,
            "path_evidence": path_consumption,
        }

    try:
        return await run_db_op(operation)
    except AssessmentCoreError as exc:
        raise _assessment_error(exc) from exc


@router.get("/today")
async def get_today_work(
    course_id: str | None = None,
    current_user: DBUser = Depends(get_current_user),
):
    return {
        "schema_version": "m5.today-work.v1",
        "items": await run_db_op(lambda session: today_work_items(
            session, owner_public_id=current_user.public_id, course_id=course_id, limit=3,
        )),
    }


@router.get("/schedule")
async def get_multi_course_schedule(
    day: int = 1,
    course_id: str | None = None,
    current_user: DBUser = Depends(get_current_user),
):
    """Read-only D-day projection over the learner's existing confirmed paths."""
    return await run_db_op(lambda session: multi_course_schedule(
        session,
        owner_public_id=current_user.public_id,
        course_id=course_id,
        selected_day=day,
    ))


@router.get("/workspace")
async def get_workspace_overview(
    course_id: str | None = None,
    current_user: DBUser = Depends(get_current_user),
):
    try:
        return await run_db_op(lambda session: workspace_overview(
            session, current_user=current_user, course_id=course_id,
        ))
    except M5WorkspaceError as exc:
        raise _workspace_error(exc) from exc


@router.get("/dashboard")
async def get_dashboard_summary(
    course_id: str | None = None,
    current_user: DBUser = Depends(get_current_user),
):
    try:
        return await run_db_op(lambda session: build_dashboard_summary(
            session,
            current_user=current_user,
            course_id=course_id,
        ))
    except M5WorkspaceError as exc:
        raise _workspace_error(exc) from exc


@router.post("/workspace/actions")
async def run_workspace_action(
    payload: WorkspaceActionRequest,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        result = execute_workspace_action(
            session,
            current_user=current_user,
            request=payload,
            runtime=runtime_availability(),
            model=CONFIG.llm_model,
        )
        session.commit()
        return result

    try:
        return await run_db_op(operation)
    except WorkspaceActionError as exc:
        raise _workspace_action_error(exc) from exc
    except M5WorkspaceError as exc:
        raise _workspace_error(exc) from exc
    except M5TaskError as exc:
        raise _task_error(exc) from exc


@router.get("/workspace/tasks/{task_id}/timeline")
async def get_workspace_task_timeline(
    task_id: str,
    course_id: str,
    current_user: DBUser = Depends(get_current_user),
):
    try:
        return await run_db_op(lambda session: build_workspace_task_timeline(
            session,
            current_user=current_user,
            task_id=task_id,
            course_id=course_id,
        ))
    except WorkspaceTimelineError as exc:
        raise _workspace_timeline_error(exc) from exc


@router.post("/workspace/tasks/{task_id}/execute-local-demo")
async def execute_workspace_local_demo_task(
    task_id: str,
    current_user: DBUser = Depends(get_current_user),
):
    if not CONFIG.demo_mode or CONFIG.llm_provider != "deterministic" or CONFIG.llm_model != "deterministic":
        raise HTTPException(
            status_code=409,
            detail={"code": "workspace_local_demo_disabled", "message": "当前未启用离线确定性演示执行器。"},
        )

    def operation(session):
        result = execute_deterministic_workspace_task(
            session, task_id=task_id, owner_public_id=current_user.public_id,
        )
        session.commit()
        return result

    try:
        return await run_db_op(operation)
    except WorkspaceLocalExecutionError as exc:
        status_code = 403 if "forbidden" in exc.code else 409
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)}) from exc


@router.post("/tutor-contexts", status_code=201)
async def create_current_tutor_context(
    payload: TutorContextSpec, current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        row, created = create_tutor_context(session, current_user=current_user, spec=payload)
        session.commit()
        return {**tutor_context_payload(row), "created": created}

    try:
        return await run_db_op(operation)
    except M5WorkspaceError as exc:
        raise _workspace_error(exc) from exc


@router.get("/tutor-contexts")
async def list_current_tutor_contexts(
    include_archived: bool = False, limit: int = 20,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        query = session.query(DBTutorContextSession).filter_by(owner_public_id=current_user.public_id)
        if not include_archived:
            query = query.filter_by(status="active")
        rows = query.order_by(DBTutorContextSession.last_used_at.desc()).limit(max(1, min(limit, 100))).all()
        return {"schema_version": "m5.tutor-context-list.v1", "items": [tutor_context_payload(row) for row in rows]}

    return await run_db_op(operation)


@router.get("/tutor-contexts/{context_id}")
async def get_current_tutor_context(
    context_id: str, current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        row = session.query(DBTutorContextSession).filter_by(id=context_id).first()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "tutor_context_unknown", "message": "tutor context does not exist"},
            )
        if row.owner_public_id != current_user.public_id:
            raise HTTPException(
                status_code=403,
                detail={"code": "tutor_context_forbidden", "message": "tutor context belongs to another owner"},
            )
        return tutor_context_payload(row)

    return await run_db_op(operation)


@router.post("/tutor-contexts/{context_id}/archive")
async def archive_current_tutor_context(
    context_id: str, payload: TutorContextArchiveRequest,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        row = session.query(DBTutorContextSession).filter_by(id=context_id).first()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "tutor_context_unknown", "message": "tutor context does not exist"},
            )
        row = archive_tutor_context(
            session, row=row, owner_public_id=current_user.public_id,
            expected_lock_version=payload.expected_lock_version,
        )
        session.commit()
        return tutor_context_payload(row)

    try:
        return await run_db_op(operation)
    except M5WorkspaceError as exc:
        raise _workspace_error(exc) from exc


@router.post("/tutor-contexts/{context_id}/preflight")
async def preflight_current_tutor_request(
    context_id: str, payload: TutorPromptPreflight,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        row = session.query(DBTutorContextSession).filter_by(id=context_id).first()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "tutor_context_unknown", "message": "tutor context does not exist"},
            )
        envelope = tutor_prompt_envelope(
            session, row=row, owner_public_id=current_user.public_id, request=payload,
        )
        session.commit()
        runtime = runtime_availability()
        blockers = []
        if not runtime.text_generation_available:
            blockers.append("text_model_unavailable")
        if row.context_mode != "current_resource" and not runtime.retrieval:
            blockers.append("retrieval_unavailable")
        return {
            **envelope,
            "ready": not blockers,
            "blockers": blockers,
            "runtime": runtime.model_dump(mode="json"),
        }

    try:
        return await run_db_op(operation)
    except M5WorkspaceError as exc:
        raise _workspace_error(exc) from exc


def _task_error(exc: M5TaskError) -> HTTPException:
    if exc.code.endswith("unknown"):
        status = 404
    elif "forbidden" in exc.code:
        status = 403
    elif any(token in exc.code for token in ("conflict", "not_", "incomplete", "required")):
        status = 409
    else:
        status = 422
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


@router.post("/tasks", status_code=201)
async def create_m5_task(payload: CapabilityTaskCreate, current_user: DBUser = Depends(get_current_user)):
    def operation(session):
        task, created = create_capability_task(
            session,
            owner_public_id=current_user.public_id,
            request=payload.routing,
            runtime=runtime_availability(),
            model=payload.model,
        )
        session.commit()
        return {**M1Repository(session).task_payload(task), "created": created}

    try:
        return await run_db_op(operation)
    except M5TaskError as exc:
        raise _task_error(exc) from exc


@router.post("/tasks/{task_id}/start")
async def start_m5_task(task_id: str, current_user: DBUser = Depends(get_current_user)):
    def operation(session):
        task = start_capability_task(session, task_id=task_id, owner_public_id=current_user.public_id)
        session.commit()
        return M1Repository(session).task_payload(task)

    try:
        return await run_db_op(operation)
    except M5TaskError as exc:
        raise _task_error(exc) from exc


@router.post("/tasks/{task_id}/cancel")
async def cancel_m5_task(task_id: str, current_user: DBUser = Depends(get_current_user)):
    def operation(session):
        task = cancel_task(
            session, task_id=task_id, owner_public_id=current_user.public_id,
        )
        session.commit()
        return M1Repository(session).task_payload(task)

    try:
        return await run_db_op(operation)
    except OperationsError as exc:
        raise _operations_error(exc) from exc


@router.get("/tasks/{task_id}")
async def get_m5_task(
    task_id: str, after_event_sequence: int = 0,
    current_user: DBUser = Depends(get_current_user),
):
    try:
        return await run_db_op(lambda session: resume_capability_task(
            session, task_id=task_id, owner_public_id=current_user.public_id,
            after_event_sequence=max(0, after_event_sequence),
        ))
    except M5TaskError as exc:
        raise _task_error(exc) from exc


@router.post("/tasks/{task_id}/steps/{sequence}/retry")
async def retry_m5_task_step(
    task_id: str, sequence: int, current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        step = retry_capability_step(
            session, task_id=task_id, owner_public_id=current_user.public_id, sequence=sequence,
        )
        session.commit()
        return {"step_id": step.id, "sequence": step.sequence, "attempt": step.attempt, "status": step.status}

    try:
        return await run_db_op(operation)
    except M5TaskError as exc:
        raise _task_error(exc) from exc


@router.post("/tasks/{task_id}/steps/{sequence}/rework")
async def rework_m5_task_step(
    task_id: str,
    sequence: int,
    payload: CapabilityTaskRework,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        step = schedule_capability_rework(
            session,
            task_id=task_id,
            owner_public_id=current_user.public_id,
            sequence=sequence,
            reason_code=payload.reason_code,
        )
        session.commit()
        return {
            "step_id": step.id,
            "sequence": step.sequence,
            "attempt": step.attempt,
            "status": step.status,
        }

    try:
        return await run_db_op(operation)
    except M5TaskError as exc:
        raise _task_error(exc) from exc
    grade_code_submission,
    grading_result_payload,
    persist_ai_grading,
    persist_code_grading,
    persist_failed_ai_grading,
    select_cat_question,
