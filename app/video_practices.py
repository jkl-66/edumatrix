"""Versioned post-video practice bindings and evidence backlinks."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.database import (
    DBAssessmentAbilityState,
    DBAssessmentAttempt,
    DBAssessmentGradingResult,
    DBAssessmentQuestion,
    DBAssessmentQuestionVersion,
    DBArtifact,
    DBArtifactVersion,
    DBChapterVideoLink,
    DBLearningEvent,
    DBUser,
    DBVideoPracticeAttemptLink,
    DBVideoPracticeLabLink,
    DBVideoPracticeSet,
    DBVideoPracticeVersion,
    DBVideoWatchProgress,
)
from app.interactive_lab import LAB_INSTANCE_TYPE, LabState, instance_payload
from app.m5_assessment_core import (
    AttemptInput,
    ability_state_payload,
    grading_result_payload,
    learner_attempt_payload,
    learner_question_payload,
    record_attempt,
)


class VideoPracticeError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise VideoPracticeError(code, message)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{hashlib.sha256(chr(31).join(parts).encode()).hexdigest()[:32]}"


def _owned_video(db: Any, actor: DBUser, link_id: str) -> DBChapterVideoLink:
    row = db.get(DBChapterVideoLink, link_id)
    if row is None:
        _fail("video_practice.video_unknown", "章节视频不存在")
    if row.owner_public_id != actor.public_id:
        _fail("video_practice.video_forbidden", "无权访问该章节视频的练习")
    return row


def _ability(db: Any, owner: str, course_id: str) -> dict[str, Any]:
    row = db.query(DBAssessmentAbilityState).filter_by(owner_public_id=owner, course_scope=course_id).first()
    return ability_state_payload(row) if row else {
        "id": None, "course_id": course_id, "theta": [0.0, 0.0, 0.0],
        "theta_std": [1.0, 1.0, 1.0], "theta_cov": [], "response_count": 0,
        "lock_version": 0, "last_attempt_id": None,
    }


def _question_binding(db: Any, video: DBChapterVideoLink, version_id: str) -> tuple[DBAssessmentQuestion, DBAssessmentQuestionVersion, dict[str, Any]]:
    version = db.get(DBAssessmentQuestionVersion, version_id)
    if version is None:
        _fail("video_practice.question_unknown", "测评题版本不存在")
    question = db.get(DBAssessmentQuestion, version.question_id)
    if question is None or question.current_version_id != version.id:
        _fail("video_practice.question_not_current", "只能绑定题目的当前版本")
    if question.status != "approved":
        _fail("video_practice.question_not_approved", "只能绑定已审核通过的题目")
    if question.course_id != video.course_id:
        _fail("video_practice.question_course_mismatch", "题目与章节视频不属于同一课程")
    video_points = {str(item) for item in (video.knowledge_point_ids or [])}
    question_points = {str(version.primary_knowledge_point_id)} if version.primary_knowledge_point_id else set()
    question_points.update(str(item) for item in (version.secondary_knowledge_point_ids or []))
    point_overlap = sorted(video_points & question_points)
    if not point_overlap:
        _fail("video_practice.question_knowledge_mismatch", "题目与章节视频没有共同授课知识点")
    video_sources = {str(item) for item in (video.source_ref_ids or [])}
    source_overlap = sorted(video_sources & {str(item) for item in (version.source_ref_ids or [])})
    if not source_overlap:
        _fail("video_practice.question_source_mismatch", "题目与章节视频没有共同来源引用")
    return question, version, {
        "resource_type": "assessment_question",
        "question_id": question.id,
        "question_version_id": version.id,
        "question_type": question.question_type,
        "content_hash": version.content_hash,
        "knowledge_point_ids": point_overlap,
        "source_ref_ids": source_overlap,
    }


def _lab_binding(db: Any, video: DBChapterVideoLink, actor: DBUser, instance_id: str) -> tuple[DBArtifact, DBArtifactVersion, LabState, dict[str, Any]]:
    artifact = db.get(DBArtifact, instance_id)
    if artifact is None or artifact.artifact_type != LAB_INSTANCE_TYPE:
        _fail("video_practice.lab_unknown", "交互实验实例不存在")
    if artifact.owner_public_id != actor.public_id:
        _fail("video_practice.lab_forbidden", "交互实验属于其他用户")
    if artifact.course_id not in {None, video.course_id}:
        _fail("video_practice.lab_course_mismatch", "交互实验与章节视频不属于同一课程")
    version = db.get(DBArtifactVersion, artifact.current_version_id)
    if version is None:
        _fail("video_practice.lab_version_unknown", "交互实验当前版本不存在")
    state = LabState.model_validate_json(version.content)
    return artifact, version, state, {
        "resource_type": "interactive_lab",
        "lab_instance_id": artifact.id,
        "lab_version_id": version.id,
        "title": artifact.title,
        "template_id": state.template_id,
        "template_version": state.template_version,
        "content_hash": version.content_hash,
        "course_scope": artifact.course_id or video.course_id,
    }


def _set_and_version(db: Any, video: DBChapterVideoLink, actor: DBUser, question_ids: list[str], lab_ids: list[str], expected_lock_version: int | None) -> tuple[DBVideoPracticeSet, DBVideoPracticeVersion, bool]:
    practice_set = db.query(DBVideoPracticeSet).filter_by(chapter_video_link_id=video.id).first()
    if practice_set is None:
        if expected_lock_version not in {None, 0}:
            _fail("video_practice.version_conflict", "练习绑定已发生变化，请刷新后重试")
        practice_set = DBVideoPracticeSet(
            owner_public_id=actor.public_id, chapter_video_link_id=video.id,
            course_id=video.course_id,
        )
        db.add(practice_set)
        db.flush()
    elif practice_set.owner_public_id != actor.public_id:
        _fail("video_practice.binding_forbidden", "练习绑定属于其他用户")
    elif expected_lock_version is not None and practice_set.lock_version != expected_lock_version:
        _fail("video_practice.version_conflict", "练习绑定已发生变化，请刷新后重试")

    question_rows = [_question_binding(db, video, item) for item in dict.fromkeys(question_ids)]
    lab_rows = [_lab_binding(db, video, actor, item) for item in dict.fromkeys(lab_ids)]
    if not question_rows and not lab_rows:
        _fail("video_practice.binding_empty", "至少绑定一道测评题或一个交互实验")
    snapshot = [item[2] for item in question_rows] + [item[3] for item in lab_rows]
    content_hash = _digest({"video_link_id": video.id, "bindings": snapshot})
    current = db.get(DBVideoPracticeVersion, practice_set.current_version_id) if practice_set.current_version_id else None
    if current is not None and current.content_hash == content_hash:
        return practice_set, current, False
    number = 1 + (db.query(DBVideoPracticeVersion).filter_by(practice_set_id=practice_set.id).count())
    version = DBVideoPracticeVersion(
        practice_set_id=practice_set.id, version_number=number,
        question_version_ids=[item[1].id for item in question_rows],
        interactive_lab_instance_ids=[item[0].id for item in lab_rows],
        binding_snapshot=snapshot, content_hash=content_hash,
        created_by_public_id=actor.public_id,
    )
    db.add(version)
    db.flush()
    practice_set.current_version_id = version.id
    if current is not None:
        practice_set.lock_version += 1
    db.flush()
    return practice_set, version, True


def bind_practice(db: Any, *, actor: DBUser, link_id: str, question_version_ids: list[str], lab_instance_ids: list[str], expected_lock_version: int | None) -> dict[str, Any]:
    video = _owned_video(db, actor, link_id)
    practice_set, version, created = _set_and_version(
        db, video, actor, question_version_ids, lab_instance_ids, expected_lock_version,
    )
    payload = get_video_practice(db, actor=actor, link_id=link_id)
    payload.update({"binding_created": created, "practice_version_id": version.id, "lock_version": practice_set.lock_version})
    return payload


def _grading_for_attempt(db: Any, attempt: DBAssessmentAttempt) -> DBAssessmentGradingResult | None:
    return db.query(DBAssessmentGradingResult).filter_by(attempt_id=attempt.id, status="completed").order_by(DBAssessmentGradingResult.created_at.desc()).first()


def _event_payload(row: DBLearningEvent) -> dict[str, Any]:
    return {
        "id": row.id, "event_type": row.event_type, "schema_version": row.schema_version,
        "object_type": row.object_type, "object_id": row.object_id,
        "payload": row.payload or {}, "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
    }


def _attempt_link_payload(db: Any, row: DBVideoPracticeAttemptLink) -> dict[str, Any]:
    attempt = db.get(DBAssessmentAttempt, row.assessment_attempt_id)
    grading = db.get(DBAssessmentGradingResult, row.grading_result_id)
    event = db.get(DBLearningEvent, row.learning_event_id)
    return {
        "id": row.id, "practice_version_id": row.practice_version_id,
        "attempt": learner_attempt_payload(attempt, grading),
        "grading": grading_result_payload(grading), "evidence": row.evidence_snapshot,
        "next_action": row.next_action, "content_hash": row.content_hash,
        "learning_event": _event_payload(event),
    }


def _lab_link_payload(db: Any, row: DBVideoPracticeLabLink) -> dict[str, Any]:
    artifact = db.get(DBArtifact, row.lab_instance_id)
    version = db.get(DBArtifactVersion, row.lab_version_id)
    state = LabState.model_validate_json(version.content)
    event = db.get(DBLearningEvent, row.learning_event_id)
    return {
        "id": row.id, "practice_version_id": row.practice_version_id,
        "lab": instance_payload(artifact, version, state), "evidence": row.evidence_snapshot,
        "content_hash": row.content_hash, "learning_event": _event_payload(event),
    }


def get_video_practice(db: Any, *, actor: DBUser, link_id: str) -> dict[str, Any]:
    video = _owned_video(db, actor, link_id)
    practice_set = db.query(DBVideoPracticeSet).filter_by(chapter_video_link_id=video.id).first()
    version = db.get(DBVideoPracticeVersion, practice_set.current_version_id) if practice_set and practice_set.current_version_id else None
    watch = db.query(DBVideoWatchProgress).filter_by(owner_public_id=actor.public_id, chapter_video_link_id=video.id).first()
    questions = []
    if version:
        for version_id in version.question_version_ids or []:
            question_version = db.get(DBAssessmentQuestionVersion, version_id)
            question = db.get(DBAssessmentQuestion, question_version.question_id) if question_version else None
            if question_version and question:
                questions.append(learner_question_payload(question_version, question))
    labs = []
    if version:
        for instance_id in version.interactive_lab_instance_ids or []:
            artifact = db.get(DBArtifact, instance_id)
            if artifact and artifact.owner_public_id == actor.public_id and artifact.current_version_id:
                artifact_version = db.get(DBArtifactVersion, artifact.current_version_id)
                labs.append(instance_payload(artifact, artifact_version, LabState.model_validate_json(artifact_version.content)))
    attempt_links = db.query(DBVideoPracticeAttemptLink).filter_by(owner_public_id=actor.public_id, chapter_video_link_id=video.id).order_by(DBVideoPracticeAttemptLink.created_at.asc()).all()
    lab_links = db.query(DBVideoPracticeLabLink).filter_by(owner_public_id=actor.public_id, chapter_video_link_id=video.id).order_by(DBVideoPracticeLabLink.created_at.asc()).all()
    return {
        "schema_version": "fc1.video-practice.v1",
        "chapter_video_link_id": video.id, "course_id": video.course_id, "chapter_id": video.chapter_id,
        "practice_set": None if not practice_set else {
            "id": practice_set.id, "status": practice_set.status,
            "lock_version": practice_set.lock_version, "current_version_id": practice_set.current_version_id,
        },
        "practice_version": None if not version else {
            "id": version.id, "version_number": version.version_number,
            "content_hash": version.content_hash, "bindings": version.binding_snapshot or [],
        },
        "questions": questions, "labs": labs,
        "watch": {
            "watched_seconds": watch.watched_seconds if watch else 0.0,
            "duration_seconds": watch.duration_seconds if watch else 0.0,
            "completed": bool(watch.completed) if watch else False,
            "lock_version": watch.lock_version if watch else 0,
            "evidence_strength": "weak",
            "mastery_updated": False,
        },
        "ability": _ability(db, actor.public_id, video.course_id),
        "attempt_links": [_attempt_link_payload(db, row) for row in attempt_links],
        "lab_links": [_lab_link_payload(db, row) for row in lab_links],
        "truth_boundary": "观看时长仅形成弱事件，不更新能力；只有规范测评评分或实验隐藏验收通过后形成强证据。",
    }


def practice_context(db: Any, *, actor: DBUser, link_id: str) -> dict[str, Any]:
    video = _owned_video(db, actor, link_id)
    points = {str(item) for item in (video.knowledge_point_ids or [])}
    sources = {str(item) for item in (video.source_ref_ids or [])}
    pairs = db.query(DBAssessmentQuestion, DBAssessmentQuestionVersion).join(
        DBAssessmentQuestionVersion, DBAssessmentQuestion.current_version_id == DBAssessmentQuestionVersion.id,
    ).filter(DBAssessmentQuestion.course_id == video.course_id, DBAssessmentQuestion.status == "approved").all()
    eligible = []
    for question, version in pairs:
        q_points = ({str(version.primary_knowledge_point_id)} if version.primary_knowledge_point_id else set()) | {str(item) for item in (version.secondary_knowledge_point_ids or [])}
        q_sources = {str(item) for item in (version.source_ref_ids or [])}
        if points & q_points and sources & q_sources:
            eligible.append(learner_question_payload(version, question))
    artifacts = db.query(DBArtifact).filter_by(owner_public_id=actor.public_id, artifact_type=LAB_INSTANCE_TYPE).order_by(DBArtifact.created_at.desc()).all()
    labs = []
    for artifact in artifacts:
        if artifact.course_id not in {None, video.course_id} or not artifact.current_version_id:
            continue
        version = db.get(DBArtifactVersion, artifact.current_version_id)
        labs.append(instance_payload(artifact, version, LabState.model_validate_json(version.content)))
    return {
        "schema_version": "fc1.video-practice-context.v1", "questions": eligible,
        "labs": labs, "knowledge_point_ids": sorted(points), "source_ref_ids": sorted(sources),
    }


def update_watch(db: Any, *, actor: DBUser, link_id: str, watched_seconds: float, duration_seconds: float, completed: bool, expected_lock_version: int) -> dict[str, Any]:
    video = _owned_video(db, actor, link_id)
    if watched_seconds < 0 or duration_seconds < 0 or (duration_seconds and watched_seconds > duration_seconds + 1):
        _fail("video_practice.watch_invalid", "观看进度超出有效范围")
    row = db.query(DBVideoWatchProgress).filter_by(owner_public_id=actor.public_id, chapter_video_link_id=video.id).first()
    if row is None:
        if expected_lock_version != 0:
            _fail("video_practice.watch_conflict", "观看进度已变化，请刷新后重试")
        row = DBVideoWatchProgress(owner_public_id=actor.public_id, chapter_video_link_id=video.id)
        db.add(row)
        db.flush()
    elif row.lock_version != expected_lock_version:
        _fail("video_practice.watch_conflict", "观看进度已变化，请刷新后重试")
    row.watched_seconds = max(float(row.watched_seconds or 0), float(watched_seconds))
    row.duration_seconds = max(float(row.duration_seconds or 0), float(duration_seconds))
    row.completed = bool(row.completed or completed)
    if expected_lock_version != 0:
        row.lock_version += 1
    event = DBLearningEvent(
        id=_stable_id("le-vwatch", row.id, str(row.lock_version)), owner_public_id=actor.public_id,
        course_id=video.course_id, event_type="video.watch.completed" if row.completed else "video.watch.progress",
        schema_version="1.0", source="video_practice", trace_id=_stable_id("trace-vwatch", video.id),
        object_type="chapter_video_link", object_id=video.id,
        payload={"watched_seconds": row.watched_seconds, "duration_seconds": row.duration_seconds,
                 "completed": row.completed, "evidence_strength": "weak", "mastery_updated": False},
    )
    db.add(event)
    db.flush()
    return get_video_practice(db, actor=actor, link_id=link_id)


def _current_practice(db: Any, video: DBChapterVideoLink) -> DBVideoPracticeVersion:
    practice_set = db.query(DBVideoPracticeSet).filter_by(chapter_video_link_id=video.id).first()
    if not practice_set or not practice_set.current_version_id:
        _fail("video_practice.binding_unknown", "该视频尚未绑定练习")
    return db.get(DBVideoPracticeVersion, practice_set.current_version_id)


def link_attempt(db: Any, *, actor: DBUser, link_id: str, attempt_id: str) -> dict[str, Any]:
    video = _owned_video(db, actor, link_id)
    practice = _current_practice(db, video)
    attempt = db.get(DBAssessmentAttempt, attempt_id)
    if attempt is None:
        _fail("video_practice.attempt_unknown", "测评作答不存在")
    if attempt.owner_public_id != actor.public_id:
        _fail("video_practice.attempt_forbidden", "测评作答属于其他用户")
    if attempt.question_version_id not in (practice.question_version_ids or []):
        _fail("video_practice.attempt_not_bound", "作答题目不属于当前视频练习版本")
    existing = db.query(DBVideoPracticeAttemptLink).filter_by(assessment_attempt_id=attempt.id).first()
    if existing:
        return _attempt_link_payload(db, existing)
    grading = _grading_for_attempt(db, attempt)
    if grading is None or grading.status != "completed" or grading.score is None:
        _fail("video_practice.grading_incomplete", "作答尚无已完成的规范评分，不能形成强证据")
    next_action = "proceed" if grading.score >= 0.8 else "review_and_retry"
    evidence = {
        "evidence_strength": "strong", "score": grading.score, "correct": grading.correct,
        "grader_type": grading.grader_type, "grading_result_id": grading.id,
        "assessment_attempt_id": attempt.id, "question_version_id": attempt.question_version_id,
        "chapter_video_link_id": video.id, "practice_version_id": practice.id,
        "mastery_updated_by": "assessment_core", "next_action": next_action,
    }
    event = DBLearningEvent(
        id=_stable_id("le-vpractice", attempt.id), owner_public_id=actor.public_id,
        course_id=video.course_id, event_type="video.practice.assessment.completed",
        schema_version="1.0", source="video_practice", trace_id=_stable_id("trace-vpractice", video.id),
        object_type="assessment_attempt", object_id=attempt.id, payload=evidence,
    )
    db.add(event)
    db.flush()
    row = DBVideoPracticeAttemptLink(
        owner_public_id=actor.public_id, chapter_video_link_id=video.id,
        practice_version_id=practice.id, assessment_attempt_id=attempt.id,
        grading_result_id=grading.id, learning_event_id=event.id,
        evidence_snapshot=evidence, next_action=next_action, content_hash=_digest(evidence),
    )
    db.add(row)
    db.flush()
    return _attempt_link_payload(db, row)


def submit_objective_attempt(db: Any, *, actor: DBUser, link_id: str, attempt_input: AttemptInput) -> dict[str, Any]:
    video = _owned_video(db, actor, link_id)
    practice = _current_practice(db, video)
    if attempt_input.question_version_id not in (practice.question_version_ids or []):
        _fail("video_practice.question_not_bound", "题目不属于当前视频练习版本")
    version = db.get(DBAssessmentQuestionVersion, attempt_input.question_version_id)
    question = db.get(DBAssessmentQuestion, version.question_id)
    if question.question_type in {"code", "short_answer", "open_task"}:
        _fail("video_practice.external_grading_required", "该题型需先通过规范测评入口完成评分，再回链结果")
    ability_before = _ability(db, actor.public_id, video.course_id)
    attempt, created = record_attempt(db, owner_public_id=actor.public_id, attempt=attempt_input)
    linked = link_attempt(db, actor=actor, link_id=link_id, attempt_id=attempt.id)
    return {"created": created, "ability_before": ability_before,
            "ability_after": _ability(db, actor.public_id, video.course_id), "evidence_link": linked}


def link_lab(db: Any, *, actor: DBUser, link_id: str, instance_id: str) -> dict[str, Any]:
    video = _owned_video(db, actor, link_id)
    practice = _current_practice(db, video)
    if instance_id not in (practice.interactive_lab_instance_ids or []):
        _fail("video_practice.lab_not_bound", "交互实验不属于当前视频练习版本")
    artifact, version, state, _ = _lab_binding(db, video, actor, instance_id)
    existing = db.query(DBVideoPracticeLabLink).filter_by(lab_version_id=version.id).first()
    if existing:
        return _lab_link_payload(db, existing)
    if state.status != "passed" or not state.hidden_acceptance or not state.hidden_acceptance.passed:
        _fail("video_practice.lab_not_passed", "交互实验尚未通过隐藏验收，不能形成强证据")
    evidence = {
        "evidence_strength": "strong", "hidden_acceptance_passed": True,
        "lab_instance_id": artifact.id, "lab_version_id": version.id,
        "template_id": state.template_id, "checker_version": state.hidden_acceptance.checker_version,
        "chapter_video_link_id": video.id, "practice_version_id": practice.id,
        "mastery_updated_by": "not_applicable_lab_evidence", "next_action": "proceed",
    }
    event = DBLearningEvent(
        id=_stable_id("le-vplab", version.id), owner_public_id=actor.public_id,
        course_id=video.course_id, event_type="video.practice.lab.completed",
        schema_version="1.0", source="video_practice", trace_id=_stable_id("trace-vpractice", video.id),
        object_type=LAB_INSTANCE_TYPE, object_id=artifact.id, payload=evidence,
    )
    db.add(event)
    db.flush()
    row = DBVideoPracticeLabLink(
        owner_public_id=actor.public_id, chapter_video_link_id=video.id,
        practice_version_id=practice.id, lab_instance_id=artifact.id,
        lab_version_id=version.id, learning_event_id=event.id,
        evidence_snapshot=evidence, content_hash=_digest(evidence),
    )
    db.add(row)
    db.flush()
    return _lab_link_payload(db, row)
