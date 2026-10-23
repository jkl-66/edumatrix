from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from app.database import (
    DBArtifact,
    DBArtifactVersion,
    DBCourseMembership,
    DBAssessmentAttempt,
    DBAssessmentExamItem,
    DBAssessmentExamReport,
    DBAssessmentExamResponse,
    DBAssessmentExamSitting,
    DBAssessmentGradingResult,
    DBAssessmentQuestion,
    DBAssessmentQuestionVersion,
    DBAssessmentRetestTask,
    DBKnowledgePoint,
    DBMisconceptionReview,
    DBQuizRecord,
    DBResourceBundle,
    DBResourceBundleItem,
    DBReviewPlan,
    DBSourceDocument,
    DBSourceRef,
    DBWrongQuestion,
)
from app.m5_assessment_core import (
    ensure_legacy_quiz_question_version,
    grading_result_payload,
    learner_option_texts,
    learner_question_payload,
    learner_correct_answer,
    learner_topic_title,
    learner_safe_explanation,
    learner_safe_prompt,
    misconception_review_payload,
    retest_task_payload,
)
from app.learning_aggregation import bind_legacy_wrong_question_version


RESOURCE_ROUTES = {
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

LEGACY_RESOURCE_TYPES = {
    "exercise": "quiz",
    "code": "code_sandbox",
    "ppt": "deck",
    "animation": "interactive_model",
    "lab": "interactive_model",
}

ARTIFACT_RESOURCE_TYPES = {
    "lesson": "handout",
    "lecture_note": "handout",
    "handout": "handout",
    "mindmap": "mind_map",
    "mind_map": "mind_map",
    "code": "code_sandbox",
    "code_example": "code_sandbox",
    "notebook": "code_sandbox",
}

MODE_LABELS = {
    "practice": "测验题资源",
    "diagnostic": "入学诊断",
    "formal": "智能组卷",
    "retest": "延迟复测",
}


class WrongQuestionRedoError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _answer_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("choice", "value", "text", "answer", "code"):
            if value.get(key) not in (None, ""):
                return str(value[key])
        choices = value.get("choices") or value.get("blanks") or value.get("answers")
        if isinstance(choices, list):
            return "、".join(str(item) for item in choices)
    if isinstance(value, list):
        return "、".join(str(item) for item in value)
    return str(value)


def _resource_route(resource_type: str, resource_id: str) -> str:
    normalized = LEGACY_RESOURCE_TYPES.get(resource_type, resource_type)
    template = RESOURCE_ROUTES.get(normalized)
    return template.format(resource_id=quote(resource_id, safe="")) if template else "/workspace/resources"


def _attempt_source(
    attempt: DBAssessmentAttempt,
    *,
    formal: dict[str, Any] | None,
    retest: DBAssessmentRetestTask | None,
) -> dict[str, Any]:
    course_query = f"?course_id={quote(attempt.course_id, safe='')}" if attempt.course_id else ""
    if formal:
        query = [f"sitting_id={quote(formal['sitting_id'], safe='')}"]
        if formal.get("report_id"):
            query.append(f"report_id={quote(formal['report_id'], safe='')}")
        return {
            "type": "formal_exam",
            "label": MODE_LABELS["formal"],
            **formal,
            "route": f"/workspace/assessment/exams/{quote(formal['exam_id'], safe='')}?{'&'.join(query)}",
        }
    if attempt.mode == "diagnostic":
        return {
            "type": "diagnostic",
            "label": MODE_LABELS["diagnostic"],
            "route": f"/workspace/assessment/diagnostic{course_query}",
        }
    if attempt.mode == "retest":
        retest_id = retest.id if retest else ""
        query = f"?retest_id={quote(retest_id, safe='')}" if retest_id else course_query
        return {
            "type": "retest",
            "label": MODE_LABELS["retest"],
            "retest_task_id": retest_id or None,
            "route": f"/workspace/review/calendar{query}",
        }
    query = f"?question_version_id={quote(attempt.question_version_id, safe='')}"
    if attempt.course_id:
        query += f"&course_id={quote(attempt.course_id, safe='')}"
    return {
        "type": "quiz_resource",
        "label": MODE_LABELS["practice"],
        "route": f"/workspace/resources{query}",
    }


def _source_payloads(session: Any, source_ref_ids: list[str]) -> list[dict[str, Any]]:
    rows = session.query(DBSourceRef).filter(DBSourceRef.id.in_(source_ref_ids)).all() if source_ref_ids else []
    refs = {row.id: row for row in rows}
    document_ids = {row.source_document_id for row in rows}
    documents = {
        row.id: row
        for row in session.query(DBSourceDocument).filter(DBSourceDocument.id.in_(document_ids)).all()
    } if document_ids else {}
    result = []
    for source_id in source_ref_ids:
        ref = refs.get(source_id)
        document = documents.get(ref.source_document_id) if ref else None
        if ref is None or document is None:
            result.append({
                "id": source_id,
                "title": "历史题目来源",
                "location": "原始来源记录当前不可用",
                "quote": "",
                "available": False,
                "status": "withdrawn_or_missing",
                "route": None,
            })
            continue
        available = document.processing_status == "ready"
        document_id = document.legacy_document_id or document.id
        result.append({
            "id": ref.id,
            "document_id": document.id,
            "title": document.title,
            "location": ref.location_label or (f"第 {ref.page_number} 页" if ref.page_number else "已定位章节"),
            "page_number": ref.page_number,
            "quote": ref.quote or "",
            "available": available,
            "status": document.processing_status,
            "route": (
                f"/knowledge/documents/{quote(document_id, safe='')}?source_ref_id={quote(ref.id, safe='')}"
                if available else None
            ),
        })
    return result


def _related_resources(
    session: Any,
    *,
    owner_public_id: str,
    course_id: str | None,
    knowledge_point_id: str | None,
) -> list[dict[str, Any]]:
    if not course_id or not knowledge_point_id:
        return []
    items: dict[tuple[str, str], dict[str, Any]] = {}
    bundles = session.query(DBResourceBundle).filter_by(
        owner_public_id=owner_public_id,
        course_id=course_id,
        knowledge_point_id=knowledge_point_id,
        status="active",
    ).order_by(DBResourceBundle.updated_at.desc()).all()
    version_ids = [row.current_version_id for row in bundles if row.current_version_id]
    if version_ids:
        for row in session.query(DBResourceBundleItem).filter(
            DBResourceBundleItem.bundle_version_id.in_(version_ids)
        ).order_by(DBResourceBundleItem.position).all():
            snapshot = dict(row.frozen_snapshot or {})
            resource_type = LEGACY_RESOURCE_TYPES.get(row.resource_type, row.resource_type)
            items.setdefault((resource_type, row.resource_id), {
                "type": resource_type,
                "resource_id": row.resource_id,
                "version_id": row.resource_version_id,
                "title": str(snapshot.get("title") or snapshot.get("resource_title") or resource_type),
                "status": str(snapshot.get("status") or snapshot.get("resource_status") or "available"),
                "route": str(snapshot.get("route") or _resource_route(resource_type, row.resource_id)),
            })
    artifacts = session.query(DBArtifact).filter_by(
        owner_public_id=owner_public_id,
        course_id=course_id,
    ).filter(DBArtifact.archived_at.is_(None), DBArtifact.current_version_id.isnot(None)).all()
    versions = {
        row.id: row
        for row in session.query(DBArtifactVersion).filter(
            DBArtifactVersion.id.in_([item.current_version_id for item in artifacts])
        ).all()
    } if artifacts else {}
    for artifact in artifacts:
        version = versions.get(artifact.current_version_id)
        metadata = dict(version.metadata_json or {}) if version else {}
        if str(metadata.get("knowledge_point_id") or "") != knowledge_point_id:
            continue
        resource_type = str(metadata.get("resource_type") or ARTIFACT_RESOURCE_TYPES.get(artifact.artifact_type, ""))
        if resource_type not in RESOURCE_ROUTES:
            continue
        items.setdefault((resource_type, artifact.id), {
            "type": resource_type,
            "resource_id": artifact.id,
            "version_id": artifact.current_version_id,
            "title": artifact.title,
            "status": artifact.status,
            "route": _resource_route(resource_type, artifact.id),
        })
    return list(items.values())


def prepare_wrong_question_redo(
    session: Any,
    *,
    wrong_id: int,
    student_id: str,
    owner_public_id: str,
) -> dict[str, Any]:
    """Resolve one wrong question to a canonical version without inventing an attempt."""
    wrong = session.query(DBWrongQuestion).filter_by(
        id=wrong_id,
        student_id=student_id,
    ).first()
    if wrong is None:
        raise WrongQuestionRedoError("wrong_question_unknown", "错题记录不存在或无权操作")

    version = None
    if wrong.source_object_id:
        version = session.query(DBAssessmentQuestionVersion).filter_by(
            id=str(wrong.source_object_id),
        ).first()
    created = False
    if version is None:
        quiz = session.query(DBQuizRecord).filter_by(
            id=wrong.quiz_record_id,
            student_id=student_id,
        ).first() if wrong.quiz_record_id else None
        if quiz is None:
            raise WrongQuestionRedoError(
                "wrong_question_redo_unavailable",
                "这条历史错题缺少可恢复的规范题目内容，暂时无法重做。",
            )
        prepared = ensure_legacy_quiz_question_version(
            session,
            owner_public_id=owner_public_id,
            quiz_record=quiz,
        )
        version = prepared["version"]
        rebound = bind_legacy_wrong_question_version(
            session,
            student_id=student_id,
            quiz_record_id=quiz.id,
            question_version_id=version.id,
        )
        if rebound is None:
            raise WrongQuestionRedoError(
                "wrong_question_bind_failed",
                "错题题目版本准备失败，请重试。",
            )
        wrong = rebound
        created = bool(prepared["question_created"] or prepared["version_created"])

    question = session.query(DBAssessmentQuestion).filter_by(id=version.question_id).first()
    if question is None:
        raise WrongQuestionRedoError(
            "wrong_question_redo_unavailable",
            "这条错题的规范题目当前不可用。",
        )
    if question.course_id:
        member = session.query(DBCourseMembership).filter_by(
            course_id=question.course_id,
            user_public_id=owner_public_id,
            status="active",
        ).first()
        if member is None and question.owner_public_id != owner_public_id:
            raise WrongQuestionRedoError("wrong_question_forbidden", "当前学生无权重做这道课程题目。")
    elif question.owner_public_id != owner_public_id:
        raise WrongQuestionRedoError("wrong_question_forbidden", "这道题目不属于当前学生。")
    payload = learner_question_payload(version, question)
    return {
        "wrong_question_id": wrong.id,
        "question_version_id": version.id,
        "created": created,
        "question": {
            "id": version.id,
            "question_id": version.question_id,
            "type": payload["question_type"],
            "prompt": payload["prompt"],
            "options": payload["options"],
            "response_spec": payload["response_spec"],
            "bloom_level": payload["bloom_level"],
            "answer_available": True,
            "answer_unavailable_reason": "",
            "explanation": learner_safe_explanation(
                version.explanation,
                prompt=version.prompt,
                options=version.options,
                answer_key=version.answer_key,
                question_type=question.question_type if question else "single_choice",
            ),
        },
    }


def build_wrong_question_read_model(
    session: Any,
    *,
    student_id: str,
    owner_public_id: str,
    concept: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    query = session.query(DBWrongQuestion).filter_by(student_id=student_id)
    if concept:
        query = query.filter_by(concept_name=concept)
    wrong_rows = query.order_by(
        DBWrongQuestion.pinned.desc(),
        DBWrongQuestion.created_at.desc(),
        DBWrongQuestion.id.desc(),
    ).limit(limit).all()
    version_ids = {str(row.source_object_id) for row in wrong_rows if row.source_object_id}
    versions = {
        row.id: row
        for row in session.query(DBAssessmentQuestionVersion).filter(
            DBAssessmentQuestionVersion.id.in_(version_ids)
        ).all()
    } if version_ids else {}
    question_ids = {row.question_id for row in versions.values()}
    questions = {
        row.id: row
        for row in session.query(DBAssessmentQuestion).filter(DBAssessmentQuestion.id.in_(question_ids)).all()
    } if question_ids else {}
    point_ids = {row.primary_knowledge_point_id for row in versions.values() if row.primary_knowledge_point_id}
    points = {
        row.id: row
        for row in session.query(DBKnowledgePoint).filter(DBKnowledgePoint.id.in_(point_ids)).all()
    } if point_ids else {}

    attempts = session.query(DBAssessmentAttempt).filter(
        DBAssessmentAttempt.owner_public_id == owner_public_id,
        DBAssessmentAttempt.question_version_id.in_(version_ids),
    ).order_by(DBAssessmentAttempt.submitted_at.desc(), DBAssessmentAttempt.id.desc()).all() if version_ids else []
    attempt_ids = [row.id for row in attempts]
    grading_rows = session.query(DBAssessmentGradingResult).filter(
        DBAssessmentGradingResult.attempt_id.in_(attempt_ids)
    ).order_by(DBAssessmentGradingResult.created_at.desc()).all() if attempt_ids else []
    grading_by_attempt: dict[str, DBAssessmentGradingResult] = {}
    for row in grading_rows:
        grading_by_attempt.setdefault(row.attempt_id, row)
    reviews = session.query(DBMisconceptionReview).filter(
        DBMisconceptionReview.owner_public_id == owner_public_id,
        DBMisconceptionReview.attempt_id.in_(attempt_ids),
    ).all() if attempt_ids else []
    reviews_by_attempt = {row.attempt_id: row for row in reviews}
    review_ids = [row.id for row in reviews]
    retest_rows = session.query(DBAssessmentRetestTask).filter(
        DBAssessmentRetestTask.owner_public_id == owner_public_id,
        DBAssessmentRetestTask.question_version_id.in_(version_ids),
    ).all() if version_ids else []
    retest_by_review = {row.misconception_review_id: row for row in retest_rows}
    retest_by_completion = {row.completion_attempt_id: row for row in retest_rows if row.completion_attempt_id}

    responses = session.query(DBAssessmentExamResponse).filter(
        DBAssessmentExamResponse.attempt_id.in_(attempt_ids)
    ).all() if attempt_ids else []
    sitting_ids = {row.sitting_id for row in responses}
    sittings = {
        row.id: row
        for row in session.query(DBAssessmentExamSitting).filter(
            DBAssessmentExamSitting.id.in_(sitting_ids),
            DBAssessmentExamSitting.owner_public_id == owner_public_id,
        ).all()
    } if sitting_ids else {}
    reports_by_sitting: dict[str, DBAssessmentExamReport] = {}
    if sitting_ids:
        report_rows = session.query(DBAssessmentExamReport).filter(
            DBAssessmentExamReport.sitting_id.in_(sitting_ids)
        ).order_by(DBAssessmentExamReport.report_version.desc()).all()
        for row in report_rows:
            reports_by_sitting.setdefault(row.sitting_id, row)
    exam_item_ids = {row.exam_item_id for row in responses}
    exam_items = {
        row.id: row
        for row in session.query(DBAssessmentExamItem).filter(DBAssessmentExamItem.id.in_(exam_item_ids)).all()
    } if exam_item_ids else {}
    formal_by_attempt: dict[str, dict[str, Any]] = {}
    for response in responses:
        sitting = sittings.get(response.sitting_id)
        if sitting is None:
            continue
        report = reports_by_sitting.get(sitting.id)
        formal_by_attempt[response.attempt_id] = {
            "exam_id": sitting.exam_id,
            "sitting_id": sitting.id,
            "sitting_status": sitting.status,
            "report_id": report.id if report else None,
            "exam_item_id": response.exam_item_id,
            "position": exam_items.get(response.exam_item_id).position if exam_items.get(response.exam_item_id) else None,
        }

    attempts_by_version: dict[str, list[DBAssessmentAttempt]] = {}
    for row in attempts:
        attempts_by_version.setdefault(row.question_version_id, []).append(row)

    quiz_ids = {row.quiz_record_id for row in wrong_rows if row.quiz_record_id}
    quizzes = {
        row.id: row
        for row in session.query(DBQuizRecord).filter(
            DBQuizRecord.id.in_(quiz_ids), DBQuizRecord.student_id == student_id,
        ).all()
    } if quiz_ids else {}
    review_plans = {
        row.concept: row
        for row in session.query(DBReviewPlan).filter_by(student_id=student_id).all()
    }

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    result: list[dict[str, Any]] = []
    for wrong in wrong_rows:
        version = versions.get(str(wrong.source_object_id or ""))
        question = questions.get(version.question_id) if version else None
        point = points.get(version.primary_knowledge_point_id) if version else None
        canonical_attempts = attempts_by_version.get(version.id, []) if version else []
        attempt_payloads = []
        formal_links: dict[str, dict[str, Any]] = {}
        for attempt in canonical_attempts:
            review = reviews_by_attempt.get(attempt.id)
            retest = retest_by_review.get(review.id) if review else retest_by_completion.get(attempt.id)
            formal = formal_by_attempt.get(attempt.id)
            feedback_released = attempt.feedback_policy != "after_close" or bool(
                formal and formal.get("sitting_status") == "released"
            )
            grading = grading_by_attempt.get(attempt.id)
            payload = {
                "id": attempt.id,
                "question_version_id": attempt.question_version_id,
                "course_id": attempt.course_id,
                "mode": attempt.mode,
                "mode_label": MODE_LABELS.get(attempt.mode, attempt.mode),
                "answer": attempt.answer,
                "score": attempt.score if feedback_released else None,
                "correct": attempt.correct if feedback_released else None,
                "confidence": attempt.confidence,
                "duration_seconds": attempt.duration_seconds,
                "grading_status": attempt.grading_status,
                "feedback_policy": attempt.feedback_policy,
                "feedback_released": feedback_released,
                "submitted_at": _iso(attempt.submitted_at),
                "grading": grading_result_payload(grading) if grading and feedback_released else None,
                "diagnosis": misconception_review_payload(review),
                "retest_task": retest_task_payload(retest),
                "source": _attempt_source(attempt, formal=formal, retest=retest),
            }
            attempt_payloads.append(payload)
            if formal:
                formal_links.setdefault(formal["sitting_id"], payload["source"])

        latest_attempt = canonical_attempts[0] if canonical_attempts else None
        latest_review = next(
            (reviews_by_attempt[row.id] for row in canonical_attempts if row.id in reviews_by_attempt),
            None,
        )
        active_retest = next(
            (row for row in retest_rows if version and row.question_version_id == version.id and row.status in {"scheduled", "due"}),
            next((row for row in retest_rows if version and row.question_version_id == version.id), None),
        )
        formal_only_unreleased = bool(canonical_attempts) and all(
            row.feedback_policy == "after_close" and not (
                formal_by_attempt.get(row.id, {}).get("sitting_status") == "released"
            )
            for row in canonical_attempts
        )
        answer = None
        if version and question and not formal_only_unreleased:
            answer = learner_correct_answer(question.question_type, dict(version.answer_key or {}))
        learner_payload = learner_question_payload(version, question) if version and question else None
        source_refs = _source_payloads(session, list(version.source_ref_ids or [])) if version else []
        course_id = question.course_id if question else (latest_attempt.course_id if latest_attempt else None)
        resources = _related_resources(
            session,
            owner_public_id=owner_public_id,
            course_id=course_id,
            knowledge_point_id=point.id if point else None,
        )
        plan = review_plans.get(wrong.concept_name)
        plan_status = None
        if plan:
            plan_status = "due" if not plan.next_review_at or plan.next_review_at <= now else "upcoming"
        quiz = quizzes.get(wrong.quiz_record_id)
        quiz_detail = None
        if quiz:
            quiz_detail = {
                "question": learner_safe_prompt((quiz.question or "")[:2000], knowledge_point=point.title if point else ""),
                "student_answer": (quiz.student_answer or "")[:2000],
                "correct_answer": (quiz.correct_answer or "")[:2000],
                "options": learner_option_texts(version, question) if version else list(quiz.options or []),
                "accuracy_score": quiz.accuracy_score,
                "feedback": learner_safe_explanation(
                    quiz.feedback,
                    prompt=version.prompt if version else quiz.question,
                    options=version.options if version else quiz.options,
                    answer_key=version.answer_key if version else {"choice": quiz.correct_answer},
                    question_type=question.question_type if question else "single_choice",
                ),
            }
        elif version:
            latest_payload = attempt_payloads[0] if attempt_payloads else {}
            quiz_detail = {
                "question": learner_safe_prompt(version.prompt, knowledge_point=point.title if point else ""),
                "student_answer": _answer_text(latest_payload.get("answer")),
                "correct_answer": _answer_text(answer),
                "options": learner_option_texts(version, question),
                "accuracy_score": latest_payload.get("score"),
                "feedback": learner_safe_explanation(
                    version.explanation,
                    prompt=version.prompt,
                    options=version.options,
                    answer_key=version.answer_key,
                    question_type=question.question_type if question else "single_choice",
                ),
            }
        status = "needs_review"
        if active_retest and retest_task_payload(active_retest)["status"] == "due":
            status = "retest_due"
        elif latest_attempt and latest_attempt.correct is True:
            status = "mastered"
        current_diagnosis = misconception_review_payload(latest_review)
        current_retest = retest_task_payload(active_retest)
        result.append({
            "id": wrong.id,
            "quiz_record_id": wrong.quiz_record_id,
            "question_version_id": version.id if version else wrong.source_object_id,
            "course_id": course_id,
            "concept_name": learner_topic_title(version.prompt, point.title if point else wrong.concept_name) if version else (point.title if point else wrong.concept_name),
            "knowledge_point": ({"id": point.id, "title": learner_topic_title(version.prompt, point.title)} if point and version else ({"id": point.id, "title": point.title} if point else None)),
            "wrong_reason_category": wrong.wrong_reason_category,
            "pinned": bool(wrong.pinned),
            "notes": wrong.notes or "",
            "created_at": _iso(wrong.created_at) or "",
            "status": status,
            "question": ({
                "id": version.id,
                "question_id": version.question_id,
                "type": question.question_type if question else "unknown",
                "prompt": learner_safe_prompt(version.prompt, knowledge_point=point.title if point else ""),
                "options": learner_option_texts(version, question),
                "response_spec": dict((learner_payload or {}).get("response_spec") or {}),
                "correct_answer": answer,
                "answer_available": not formal_only_unreleased,
                "answer_unavailable_reason": "本次正式测评尚未开放答案与解析。" if formal_only_unreleased else "",
                "explanation": (
                    learner_safe_explanation(
                        version.explanation,
                        prompt=version.prompt,
                        options=version.options,
                        answer_key=version.answer_key,
                        question_type=question.question_type if question else "single_choice",
                        knowledge_point=point.title if point else "",
                    )
                    if not formal_only_unreleased else ""
                ),
                "bloom_level": version.bloom_level,
                "source_refs": source_refs,
            } if version else None),
            "quiz_detail": quiz_detail,
            "attempt_count": len(attempt_payloads),
            "attempts": attempt_payloads,
            "formal_exam_links": list(formal_links.values()),
            "current_diagnosis": current_diagnosis,
            "retest_task": current_retest,
            "canonical_diagnosis": {
                "attempt_id": latest_attempt.id if latest_attempt else None,
                "review": current_diagnosis,
                "retest_task": current_retest,
            } if latest_attempt else None,
            "review_plan": ({
                "id": plan.id,
                "status": plan_status,
                "next_review_at": _iso(plan.next_review_at),
                "review_count": plan.review_count,
                "mastery": plan.mastery,
                "route": f"/workspace/review/calendar?review_task=review-plan:{plan.id}",
            } if plan else None),
            "source_refs": source_refs,
            "related_resources": resources,
            "actions": {
                "primary": {
                    "kind": "retest" if current_retest and current_retest["status"] == "due" else "redo",
                    "label": "开始复测" if current_retest and current_retest["status"] == "due" else "重做这道题",
                    "route": (
                        f"/workspace/review/calendar?retest_id={quote(current_retest['id'], safe='')}"
                        if current_retest and current_retest["status"] == "due" else None
                    ),
                },
                "chat": {
                    "label": "问学习伙伴",
                    "route": (
                        "/learn?"
                        f"question_version_id={quote(version.id, safe='')}&"
                        f"attempt_id={quote(latest_attempt.id, safe='') if latest_attempt else ''}&"
                        f"knowledge_point_id={quote(point.id, safe='') if point else ''}&"
                        f"course_id={quote(course_id, safe='') if course_id else ''}&"
                        f"return_to={quote('/workspace/review/wrong-questions', safe='')}"
                    ) if version else None,
                },
            },
        })
    return result
