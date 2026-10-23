from __future__ import annotations

import hashlib
import json
from typing import Any

from app.database import (
    DBAssessmentAttempt,
    DBAssessmentQuestion,
    DBAssessmentQuestionVersion,
    DBMisconceptionReview,
    DBQuizRecord,
    DBReviewPlan,
    DBUser,
    DBWrongQuestion,
    DBWrongQuestionVideoLink,
)
from app.video_rendering import create_project, get_project


class WrongQuestionVideoError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise WrongQuestionVideoError(code, message)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _trim(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _diagnosis(db: Any, owner_public_id: str, quiz_id: str) -> dict[str, Any]:
    attempt = db.query(DBAssessmentAttempt).filter_by(
        owner_public_id=owner_public_id,
        idempotency_key=f"legacy-quiz-attempt:{quiz_id}:1",
    ).first()
    review = (
        db.query(DBMisconceptionReview).filter_by(attempt_id=attempt.id).first()
        if attempt else None
    )
    if review is None:
        return {"category": "", "rationale": "", "status": "unavailable", "review_id": ""}
    confirmed = review.status in {"accepted", "modified", "teacher_confirmed"}
    return {
        "category": review.confirmed_category if confirmed else review.candidate_category,
        "rationale": _trim(review.decision_note if confirmed else review.candidate_rationale, 300),
        "status": "confirmed" if confirmed else "candidate",
        "review_id": review.id,
    }


def _source_refs(db: Any, owner_public_id: str, quiz_id: str) -> tuple[list[str], str | None]:
    attempt = db.query(DBAssessmentAttempt).filter_by(
        owner_public_id=owner_public_id,
        idempotency_key=f"legacy-quiz-attempt:{quiz_id}:1",
    ).first()
    version = db.get(DBAssessmentQuestionVersion, attempt.question_version_id) if attempt else None
    question = db.get(DBAssessmentQuestion, version.question_id) if version else None
    refs = [str(item) for item in (version.source_ref_ids or []) if str(item)] if version else []
    if not refs:
        refs = [f"legacy-quiz:{quiz_id}"]
    return refs, question.course_id if question else None


def _snapshot(db: Any, *, actor: DBUser, student_id: str, wrong_question_id: int) -> tuple[dict[str, Any], DBWrongQuestion, DBQuizRecord, DBReviewPlan | None]:
    wrong = db.query(DBWrongQuestion).filter_by(id=wrong_question_id, student_id=student_id).first()
    if wrong is None:
        _fail("wrong_video.wrong_question_unknown", "错题不存在或不属于目标学习者")
    quiz = db.get(DBQuizRecord, wrong.quiz_record_id) if wrong.quiz_record_id else None
    if quiz is None or quiz.student_id != student_id:
        _fail("wrong_video.quiz_record_missing", "错题缺少可追溯的原始作答记录")
    subject = db.query(DBUser).filter_by(username=student_id).first()
    if subject is None:
        _fail("wrong_video.student_owner_missing", "目标学习者缺少认证身份映射")
    question = _trim(quiz.question, 1200)
    correct_answer = _trim(quiz.correct_answer, 1000)
    if not question or not correct_answer:
        _fail("wrong_video.required_fact_missing", "原题或参考答案为空，不能生成讲解视频")
    plan = db.query(DBReviewPlan).filter_by(student_id=student_id, concept=wrong.concept_name).order_by(DBReviewPlan.id.desc()).first()
    diagnosis = _diagnosis(db, subject.public_id, quiz.id)
    refs, course_id = _source_refs(db, subject.public_id, quiz.id)
    boundary = (
        "课程可定位来源" if any(not item.startswith("legacy-quiz:") for item in refs)
        else "旧题记录追溯；未宣称为可定位课程原文引用"
    )
    snapshot = {
        "student_id": student_id,
        "subject_owner_public_id": subject.public_id,
        "generated_by_public_id": actor.public_id,
        "wrong_question_id": wrong.id,
        "quiz_record_id": quiz.id,
        "question": question,
        "student_answer": _trim(quiz.student_answer, 1000) or "未作答",
        "correct_answer": correct_answer,
        "feedback": _trim(quiz.feedback, 1000),
        "concept": _trim(wrong.concept_name or quiz.target_concept, 128),
        "wrong_reason_category": _trim(wrong.wrong_reason_category, 128),
        "diagnosis": diagnosis,
        "review_plan": ({
            "id": plan.id,
            "next_review_at": plan.next_review_at.isoformat() if plan.next_review_at else "",
            "interval_days": plan.interval_days,
            "mastery": plan.mastery,
            "review_count": plan.review_count,
        } if plan else None),
        "source_refs": refs,
        "course_id": course_id,
        "truth_boundary": boundary,
    }
    return snapshot, wrong, quiz, plan


def _scenes(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    diagnosis = snapshot["diagnosis"]
    reason = diagnosis["category"] or snapshot["wrong_reason_category"] or "尚未形成明确错因"
    reason_state = "已确认" if diagnosis["status"] == "confirmed" else "候选诊断" if diagnosis["status"] == "candidate" else "当前记录"
    plan = snapshot["review_plan"]
    review_text = (
        f"计划在 {plan['next_review_at'] or '待排期'} 复习，当前间隔 {plan['interval_days']} 天。"
        if plan else "当前尚无独立复习计划，请完成相似题并根据结果安排复测。"
    )
    source_text = "；".join(snapshot["source_refs"][:3])
    return [
        {"title": "原题回看", "narration": f"先回到原题：{snapshot['question']}", "bullets": [f"知识点：{snapshot['concept']}", "先识别题目真正要求"], "duration_ms": 4500},
        {"title": "答案对照", "narration": f"你的答案是：{snapshot['student_answer']}。参考答案是：{snapshot['correct_answer']}。", "bullets": ["比较关键差异", "不要只记答案结论"], "duration_ms": 5000},
        {"title": "错因定位", "narration": f"{reason_state}为：{reason}。{diagnosis['rationale'] or snapshot['feedback'] or '需要在复习后进一步确认。'}", "bullets": [f"状态：{reason_state}", "候选错因不等于稳定结论"], "duration_ms": 5000},
        {"title": "正确思路", "narration": f"围绕 {snapshot['concept']} 重建解题路径。参考答案：{snapshot['correct_answer']}。", "bullets": ["提取核心概念", "按步骤验证答案", "回到原题检查"], "duration_ms": 5500},
        {"title": "复习与证据", "narration": f"{review_text} 本视频依据：{source_text}。", "bullets": ["完成相似题或实操", "测评结果才形成强证据", snapshot["truth_boundary"]], "duration_ms": 5000},
    ]


def _payload(db: Any, row: DBWrongQuestionVideoLink, actor: DBUser) -> dict[str, Any]:
    return {
        "id": row.id,
        "student_id": row.student_id,
        "wrong_question_id": row.source_wrong_question_id,
        "quiz_record_id": row.quiz_record_id,
        "review_plan_id": row.review_plan_id,
        "video_project_id": row.video_project_id,
        "input_hash": row.input_hash,
        "evidence_refs": row.evidence_refs,
        "snapshot": row.snapshot_json,
        "truth_boundary": row.truth_boundary,
        "project": get_project(db, actor=actor, project_id=row.video_project_id),
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


def generate_wrong_question_video(db: Any, *, actor: DBUser, student_id: str, wrong_question_id: int) -> dict[str, Any]:
    snapshot, wrong, quiz, plan = _snapshot(
        db, actor=actor, student_id=student_id, wrong_question_id=wrong_question_id,
    )
    input_hash = hashlib.sha256(_canonical(snapshot).encode("utf-8")).hexdigest()
    existing = db.query(DBWrongQuestionVideoLink).filter_by(
        owner_public_id=actor.public_id,
        student_id=student_id,
        source_wrong_question_id=wrong_question_id,
        input_hash=input_hash,
    ).first()
    if existing:
        result = _payload(db, existing, actor)
        result["idempotent"] = True
        return result
    project = create_project(
        db,
        actor=actor,
        title=f"错题讲解：{snapshot['concept']}",
        course_id=snapshot["course_id"],
        scenes=_scenes(snapshot),
    )
    row = DBWrongQuestionVideoLink(
        owner_public_id=actor.public_id,
        student_id=student_id,
        wrong_question_id=wrong.id,
        source_wrong_question_id=wrong.id,
        quiz_record_id=quiz.id,
        review_plan_id=plan.id if plan else None,
        video_project_id=project["id"],
        input_hash=input_hash,
        evidence_refs=snapshot["source_refs"],
        snapshot_json=snapshot,
        truth_boundary=snapshot["truth_boundary"],
    )
    db.add(row)
    db.flush()
    result = _payload(db, row, actor)
    result["idempotent"] = False
    return result


def list_wrong_question_videos(db: Any, *, actor: DBUser, student_id: str, wrong_question_id: int | None = None) -> dict[str, Any]:
    query = db.query(DBWrongQuestionVideoLink).filter_by(
        owner_public_id=actor.public_id, student_id=student_id,
    )
    if wrong_question_id is not None:
        query = query.filter_by(source_wrong_question_id=wrong_question_id)
    rows = query.order_by(DBWrongQuestionVideoLink.created_at.desc()).all()
    return {"schema_version": "fc1.wrong-question-video-list.v1", "items": [_payload(db, row, actor) for row in rows]}


def get_wrong_question_video(db: Any, *, actor: DBUser, link_id: str) -> dict[str, Any]:
    row = db.get(DBWrongQuestionVideoLink, link_id)
    if row is None:
        _fail("wrong_video.link_unknown", "错题视频记录不存在")
    if row.owner_public_id != actor.public_id:
        _fail("wrong_video.link_forbidden", "无权访问该错题视频")
    return _payload(db, row, actor)
