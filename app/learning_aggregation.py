"""Replay learning events into the legacy profile, path, review, and summary views."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Callable

from app.database import (
    DBAssessmentQuestionVersion,
    DBChapterKnowledgePoint,
    DBKnowledgePoint,
    DBLearningEvent,
    DBLearningEventConsumption,
    DBLearningPath,
    DBPathNode,
    DBProfileSnapshot,
    DBReviewPlan,
    DBStudentProfile,
    DBUser,
    DBWrongQuestion,
    DBWrongQuestionVideoLink,
)
from models import DIMENSION_LABELS


AGGREGATION_PROCESSOR_VERSION = "f8.learning-feedback.v3"
AGGREGATION_STEPS = (
    "profile_snapshot",
    "path_task",
    "wrong_review",
    "activity",
    "dashboard",
)

LEARNING_FEEDBACK_EVENT_TYPES = frozenset({
    "quiz_answered",
    "code_tests_passed",
    "interactive_model_observation_submitted",
    "interactive_experiment_completed",
    "feynman_submitted",
    "formal_exam_submitted",
    "review_completed",
    "delayed_retest_passed",
    "teacher_confirmed",
})

AGGREGATION_VIEW_CONTRACT = {
    "dashboard": {"label": "首页", "route": "/", "step": "dashboard"},
    "profile": {"label": "学习画像", "route": "/profile/learning", "step": "profile_snapshot"},
    "path": {"label": "学习路径", "route": "/workspace/path", "step": "path_task"},
    "wrong_questions": {
        "label": "错题本",
        "route": "/workspace/review/wrong-questions",
        "step": "wrong_review",
    },
    "review": {"label": "复习中心", "route": "/workspace/review", "step": "wrong_review"},
    "history": {"label": "学习历史", "route": "/profile/history", "step": "activity"},
}

_FEEDBACK_SOURCE_LABELS = {
    "interactive_experiment_completed": "interactive experiment",
    "delayed_retest_passed": "delayed retest",
    "teacher_confirmed": "teacher confirmation",
    "quiz_answered": "测验题",
    "code_tests_passed": "代码沙盒",
    "interactive_model_observation_submitted": "可交互模型",
    "feynman_submitted": "费曼复述",
    "formal_exam_submitted": "智能组卷",
    "review_completed": "复习任务",
}

_TRANSFER_EVENT_TYPES = frozenset({
    "code_tests_passed",
    "interactive_experiment_completed",
    "interactive_model_observation_submitted",
    "feynman_submitted",
    "formal_exam_submitted",
    "delayed_retest_passed",
})

_DIMENSION_EVENT_TYPES = {
    "knowledge_mastery": LEARNING_FEEDBACK_EVENT_TYPES,
    "misconception_profile": frozenset({
        "quiz_answered", "formal_exam_submitted", "review_completed", "delayed_retest_passed",
    }),
    "understanding_fluency_transfer": _TRANSFER_EVENT_TYPES,
    "cognitive_processing": LEARNING_FEEDBACK_EVENT_TYPES,
    "learning_strategy": LEARNING_FEEDBACK_EVENT_TYPES,
    "metacognition": frozenset({"quiz_answered", "feynman_submitted", "formal_exam_submitted"}),
    "motivation_and_purpose": LEARNING_FEEDBACK_EVENT_TYPES,
    "affect_resilience": LEARNING_FEEDBACK_EVENT_TYPES,
    "interaction_preference": frozenset(),
    "learning_context": frozenset(),
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(value: datetime | None) -> str | None:
    return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}-{hashlib.sha256(value.encode('utf-8')).hexdigest()[:48]}"


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _scope_events(session: Any, event: DBLearningEvent) -> list[DBLearningEvent]:
    query = session.query(DBLearningEvent).filter(
        DBLearningEvent.owner_public_id == event.owner_public_id,
    )
    if event.course_id is None:
        query = query.filter(DBLearningEvent.course_id.is_(None))
    else:
        query = query.filter(DBLearningEvent.course_id == event.course_id)
    return query.order_by(DBLearningEvent.occurred_at, DBLearningEvent.id).all()


def _profile_feedback_events(session: Any, event: DBLearningEvent) -> list[DBLearningEvent]:
    return session.query(DBLearningEvent).filter(
        DBLearningEvent.owner_public_id == event.owner_public_id,
        DBLearningEvent.event_type.in_(LEARNING_FEEDBACK_EVENT_TYPES),
        DBLearningEvent.evidence_status == "accepted",
        DBLearningEvent.mastery_eligible.is_(True),
    ).order_by(DBLearningEvent.occurred_at, DBLearningEvent.id).all()


def _event_concept(session: Any, event: DBLearningEvent) -> tuple[str, str] | None:
    context = event.context_ref or {}
    payload = event.payload or {}
    knowledge_point_id = (
        context.get("knowledgePointId")
        or context.get("knowledge_point_id")
        or payload.get("knowledge_point_id")
    )
    if not knowledge_point_id and event.object_type == "knowledge_point":
        knowledge_point_id = event.object_id
    if not knowledge_point_id and event.object_type == "assessment_question_version":
        version = session.query(DBAssessmentQuestionVersion).filter_by(id=event.object_id).first()
        knowledge_point_id = version.primary_knowledge_point_id if version else None
    if knowledge_point_id:
        point = session.query(DBKnowledgePoint).filter_by(id=str(knowledge_point_id)).first()
        return (point.id, point.title) if point else None
    concept = str(payload.get("concept") or "").strip()
    if not concept:
        return None
    point = session.query(DBKnowledgePoint).filter(
        (DBKnowledgePoint.id == concept)
        | (DBKnowledgePoint.code == concept)
        | (DBKnowledgePoint.title == concept)
    ).order_by(DBKnowledgePoint.id).first()
    return (point.id, point.title) if point else None


def _observation(event: DBLearningEvent) -> float | None:
    payload = event.payload or {}
    if event.event_type in {"quiz_answered", "formal_exam_submitted"}:
        if payload.get("score") is not None:
            return max(0.0, min(1.0, float(payload["score"])))
        if isinstance(payload.get("correct"), bool):
            return 1.0 if payload["correct"] else 0.0
    if event.event_type in {"code_tests_passed", "delayed_retest_passed"}:
        return 1.0
    if event.event_type == "interactive_experiment_completed":
        passed = float(payload.get("passed_checks", 0))
        total = float(payload.get("total_checks", 0))
        return max(0.0, min(1.0, passed / total)) if total > 0 else None
    if event.event_type == "interactive_model_observation_submitted":
        return 1.0 if str(payload.get("observation") or "").strip() else None
    if event.event_type == "feynman_submitted" and payload.get("rubric_score") is not None:
        return max(0.0, min(1.0, float(payload["rubric_score"])))
    if event.event_type == "review_completed" and payload.get("recall_score") is not None:
        return max(0.0, min(1.0, float(payload["recall_score"])))
    if event.event_type == "teacher_confirmed":
        return max(0.0, min(1.0, float(payload.get("score", 0.85))))
    return None


def _event_observations(
    session: Any, event: DBLearningEvent,
) -> list[tuple[str, str, float]]:
    payload = event.payload or {}
    if event.event_type == "formal_exam_submitted":
        output: list[tuple[str, str, float]] = []
        for item in payload.get("knowledge_point_scores") or []:
            point_id = str(item.get("knowledge_point_id") or "").strip()
            score = item.get("score")
            if not point_id or score is None:
                continue
            point = session.query(DBKnowledgePoint).filter_by(id=point_id).first()
            if point is not None:
                output.append((point.id, point.title, max(0.0, min(1.0, float(score)))))
        if output:
            return output
    concept = _event_concept(session, event)
    observation = _observation(event)
    return [(concept[0], concept[1], observation)] if concept is not None and observation is not None else []


def _mastery_events(
    session: Any, event: DBLearningEvent,
) -> list[tuple[DBLearningEvent, str, str, float]]:
    output: list[tuple[DBLearningEvent, str, str, float]] = []
    for item in _scope_events(session, event):
        if item.evidence_status != "accepted" or not item.mastery_eligible:
            continue
        for concept_id, concept_title, observation in _event_observations(session, item):
            output.append((item, concept_id, concept_title, observation))
    return output


def _next_day_schedule(session: Any, event: DBLearningEvent) -> list[dict[str, Any]]:
    candidates = [
        item for item in _scope_events(session, event)
        if (
            item.event_type in LEARNING_FEEDBACK_EVENT_TYPES
            and item.evidence_status == "accepted"
            and item.mastery_eligible
        )
    ]
    schedule_event = max(
        candidates or [event],
        key=lambda item: (item.occurred_at or datetime.min, item.id),
    )
    declared = list((schedule_event.payload or {}).get("next_day_schedule") or [])
    if declared:
        return declared

    observations = _event_observations(session, schedule_event)
    if not observations:
        return []

    occurred_at = schedule_event.occurred_at or schedule_event.recorded_at or _now()
    scheduled_for = (occurred_at + timedelta(days=1)).date().isoformat()
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for point_id, point_title, observation in sorted(observations, key=lambda item: item[2]):
        if point_id in seen:
            continue
        seen.add(point_id)
        needs_review = observation < 0.6
        output.append({
            "id": _stable_id("next", f"{schedule_event.id}:{point_id}:{scheduled_for}"),
            "date": scheduled_for,
            "knowledge_point_id": point_id,
            "knowledge_point_title": point_title,
            "title": f"{'复习' if needs_review else '继续学习'}：{point_title}",
            "reason": (
                "本次证据显示仍需巩固，已安排次日复习。"
                if needs_review
                else "本次证据已记录，次日继续沿路径学习。"
            ),
            "target_route": "/workspace/review" if needs_review else "/workspace/path",
            "status": "scheduled",
            "source_event_id": schedule_event.id,
        })
        if len(output) == 3:
            break
    return output


def _owner_profile(session: Any, event: DBLearningEvent) -> tuple[DBUser | None, DBStudentProfile]:
    user = session.query(DBUser).filter_by(public_id=event.owner_public_id).first()
    student_id = user.username if user is not None else (
        event.legacy_student_id or event.owner_public_id
    )
    if not student_id:
        raise ValueError("learning event has no resolvable learner identity")
    profile = session.query(DBStudentProfile).filter_by(student_id=student_id).first()
    if profile is None:
        profile = DBStudentProfile(student_id=student_id)
        session.add(profile)
        session.flush()
    return user, profile


def _baseline_snapshot(
    session: Any, event: DBLearningEvent, profile: DBStudentProfile,
) -> DBProfileSnapshot:
    scope_key = f"{event.owner_public_id}:{event.course_id or 'global'}"
    snapshot_id = _stable_id("psaggbase", scope_key)
    existing = session.query(DBProfileSnapshot).filter_by(id=snapshot_id).first()
    if existing is not None:
        return existing
    snapshot_data = {
        "kind": "learning_aggregation_baseline",
        "owner_public_id": event.owner_public_id,
        "legacy_student_id": profile.student_id,
        "course_id": event.course_id,
        "concept_mastery": dict(profile.concept_mastery or {}),
        "weak_points": list(profile.weak_points or []),
        "knowledge_traces": dict(profile.knowledge_traces or {}),
        "focus_level": float(profile.focus_level if profile.focus_level is not None else 0.72),
        "cognitive_load": float(profile.cognitive_load if profile.cognitive_load is not None else 0.45),
        "frustration_index": float(profile.frustration_index if profile.frustration_index is not None else 0.0),
        "dimension_states": deepcopy(profile.dimension_states or {}),
        "learning_state_causes": deepcopy(profile.learning_state_causes or {}),
        "mental_state_history": deepcopy(profile.mental_state_history or []),
    }
    snapshot = DBProfileSnapshot(
        id=snapshot_id,
        owner_public_id=event.owner_public_id,
        legacy_student_id=profile.student_id,
        profile_version=AGGREGATION_PROCESSOR_VERSION,
        snapshot=snapshot_data,
        content_hash=_hash(snapshot_data),
        trace_id=f"aggregation-baseline:{scope_key}",
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def _behavior_baseline_snapshot(
    session: Any,
    event: DBLearningEvent,
    profile: DBStudentProfile,
    baseline: DBProfileSnapshot,
) -> DBProfileSnapshot:
    baseline_data = baseline.snapshot or {}
    required = {
        "focus_level", "cognitive_load", "frustration_index",
        "dimension_states", "learning_state_causes", "mental_state_history",
    }
    if required.issubset(baseline_data):
        return baseline
    snapshot_id = _stable_id("psaggbehaviorbase", event.owner_public_id)
    existing = session.query(DBProfileSnapshot).filter_by(id=snapshot_id).first()
    if existing is not None:
        return existing
    snapshot_data = {
        "kind": "learning_behavior_baseline",
        "owner_public_id": event.owner_public_id,
        "legacy_student_id": profile.student_id,
        "focus_level": float(profile.focus_level if profile.focus_level is not None else 0.72),
        "cognitive_load": float(profile.cognitive_load if profile.cognitive_load is not None else 0.45),
        "frustration_index": float(profile.frustration_index if profile.frustration_index is not None else 0.0),
        "dimension_states": deepcopy(profile.dimension_states or {}),
        "learning_state_causes": deepcopy(profile.learning_state_causes or {}),
        "mental_state_history": deepcopy(profile.mental_state_history or []),
    }
    snapshot = DBProfileSnapshot(
        id=snapshot_id,
        owner_public_id=event.owner_public_id,
        legacy_student_id=profile.student_id,
        profile_version=AGGREGATION_PROCESSOR_VERSION,
        snapshot=snapshot_data,
        content_hash=_hash(snapshot_data),
        trace_id=f"aggregation-behavior-baseline:{event.owner_public_id}",
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def _event_score(session: Any, event: DBLearningEvent) -> float | None:
    observations = [item[2] for item in _event_observations(session, event)]
    if observations:
        return sum(observations) / len(observations)
    return _observation(event)


def _event_fragment(session: Any, event: DBLearningEvent, score: float | None) -> str:
    label = _FEEDBACK_SOURCE_LABELS.get(event.event_type, "学习任务")
    concept = _event_concept(session, event)
    if concept is not None:
        target = concept[1]
    elif event.event_type == "formal_exam_submitted":
        count = len((event.payload or {}).get("knowledge_point_scores") or [])
        target = f"覆盖 {count} 个知识点" if count else "课程综合测评"
    else:
        target = "当前学习目标"
    outcome = "已完成" if score is None else f"得分 {round(score * 100)}%"
    return f"{label} · {target}：{outcome}，已由可信学习事件确认。"


def _dimension_evidence_fragments(
    session: Any,
    key: str,
    scored_events: list[tuple[DBLearningEvent, float | None]],
    *,
    load: float,
    frustration: float,
    focus: float,
) -> list[str]:
    relevant = [
        (item, score) for item, score in scored_events
        if item.event_type in _DIMENSION_EVENT_TYPES[key]
    ]
    if key == "knowledge_mastery":
        return [_event_fragment(session, item, score) for item, score in relevant[-3:]]

    labels = []
    for item, _ in relevant:
        label = _FEEDBACK_SOURCE_LABELS.get(item.event_type, "学习任务")
        if label not in labels:
            labels.append(label)
    scores = [score for _, score in relevant if score is not None]
    low_scores = [score for score in scores if score < 0.6]
    high_scores = [score for score in scores if score >= 0.6]

    if key == "misconception_profile":
        if low_scores and high_scores:
            return [
                f"测验或组卷出现 {len(low_scores)} 条低于 60% 的错误证据，随后又出现 {len(high_scores)} 条达标证据，说明本轮发生了纠错恢复，但仍需延迟复测确认。"
            ]
        if low_scores:
            return [f"测验或组卷保留了 {len(low_scores)} 条低于 60% 的错误证据，当前误区仍需复习。"]
        return ["本轮测评未形成新的稳定错误证据。"] if relevant else []
    if key == "understanding_fluency_transfer":
        return [
            f"已在{'、'.join(labels)}中应用当前知识；这些不同任务形态共同支持迁移判断。"
        ] if labels else []
    if key == "cognitive_processing":
        return [
            f"本轮连续处理 {len(relevant)} 条可信任务，当前认知负荷为 {round(load * 100)}%；低分和任务切换会提高负荷，成功完成会逐步回落。"
        ] if relevant else []
    if key == "learning_strategy":
        return [
            f"本轮实际使用了{'、'.join(labels)}等 {len(labels)} 种学习方式，体现了从作答、实作到复述的多表征学习策略。"
        ] if labels else []
    if key == "metacognition":
        feynman_deltas = [
            float((item.payload or {}).get("score_delta") or 0.0)
            for item, _ in relevant if item.event_type == "feynman_submitted"
        ]
        if feynman_deltas:
            return [f"费曼两轮复述最高提升 {round(max(feynman_deltas))} 分，并结合测评结果校准了自我解释。"]
        return ["测评结果为后续自我判断提供了校准依据。"] if relevant else []
    if key == "motivation_and_purpose":
        return [
            f"本轮连续完成 {len(relevant)} 条可信学习任务，说明本次学习投入保持连续；该证据不等同于长期动机已经稳定。"
        ] if relevant else []
    if key == "affect_resilience":
        if low_scores and len(relevant) > len(low_scores):
            return [
                f"出现低分或错答后仍继续完成后续任务，当前参与度 {round(focus * 100)}%、受挫感受 {round(frustration * 100)}%，形成了本轮恢复证据。"
            ]
        return [
            f"本轮任务持续完成，当前参与度 {round(focus * 100)}%、受挫感受 {round(frustration * 100)}%。"
        ] if relevant else []
    return []


def _project_behavior_profile(
    session: Any,
    *,
    event: DBLearningEvent,
    profile: DBStudentProfile,
    baseline: DBProfileSnapshot,
    current_mastery: dict[str, float],
) -> dict[str, Any]:
    baseline_data = baseline.snapshot or {}
    events = _profile_feedback_events(session, event)
    focus = _clamp(float(baseline_data.get("focus_level", 0.72)))
    load = _clamp(float(baseline_data.get("cognitive_load", 0.45)))
    frustration = _clamp(float(baseline_data.get("frustration_index", 0.0)))
    history = deepcopy(baseline_data.get("mental_state_history") or [])
    scored_events: list[tuple[DBLearningEvent, float | None]] = []

    for item in events:
        score = _event_score(session, item)
        scored_events.append((item, score))
        payload = item.payload or {}
        item_results = list(payload.get("item_results") or [])
        wrong_ratio = (
            sum(result.get("correct") is False for result in item_results) / len(item_results)
            if item_results else 0.0
        )
        focus += 0.018
        if score is not None and score < 0.6:
            severity = (0.6 - score) / 0.6
            load += 0.05 + 0.05 * severity
            frustration += 0.06 + 0.08 * severity
            focus -= 0.025 * severity
        else:
            load -= 0.025 if item.event_type in _TRANSFER_EVENT_TYPES else 0.012
            frustration -= 0.035
            if score is not None and score >= 0.85:
                focus += 0.008
        if wrong_ratio:
            load += 0.07 * wrong_ratio
            frustration += 0.055 * wrong_ratio
            focus -= 0.015 * wrong_ratio
        if item.event_type == "feynman_submitted" and float(payload.get("score_delta") or 0.0) > 0:
            focus += 0.02
            frustration -= 0.02
        focus, load, frustration = _clamp(focus), _clamp(load, 0.18), _clamp(frustration)
        concept = _event_concept(session, item)
        history.append({
            "timestamp": _iso(item.occurred_at or item.recorded_at or _now()),
            "event_id": item.id,
            "event_type": item.event_type,
            "event_label": _FEEDBACK_SOURCE_LABELS.get(item.event_type, "学习任务"),
            "knowledge_point": concept[1] if concept else None,
            "score": round(score, 3) if score is not None else None,
            "cognitive_load": round(load, 3),
            "frustration": round(frustration, 3),
            "focus_level": round(focus, 3),
        })

    baseline_dimensions = deepcopy(baseline_data.get("dimension_states") or {})

    def base_score(key: str, default: float) -> float:
        state = baseline_dimensions.get(key) or {}
        return _clamp(float(state.get("score", default)))

    observations = [score for _, score in scored_events if score is not None]
    successful = sum(score >= 0.6 for score in observations)
    unsuccessful = sum(score < 0.6 for score in observations)
    modalities = {item.event_type for item, _ in scored_events}
    transfer_scores = [
        score for item, score in scored_events
        if item.event_type in _TRANSFER_EVENT_TYPES and score is not None
    ]
    calibration_scores = []
    for item, score in scored_events:
        confidence = (item.payload or {}).get("confidence")
        if score is not None and confidence is not None:
            calibration_scores.append(1.0 - abs(_clamp(float(confidence)) - score))
        elif item.event_type == "feynman_submitted" and score is not None:
            calibration_scores.append(score)

    average_mastery = (
        sum(float(value) for value in current_mastery.values()) / len(current_mastery)
        if current_mastery else base_score("knowledge_mastery", 0.5)
    )
    misconception = _clamp(
        base_score("misconception_profile", 0.65) + successful * 0.018 - unsuccessful * 0.08,
    )
    transfer = base_score("understanding_fluency_transfer", 0.5)
    if transfer_scores:
        transfer = transfer * 0.6 + (sum(transfer_scores) / len(transfer_scores)) * 0.4
    strategy = _clamp(
        base_score("learning_strategy", 0.5)
        + min(0.12, max(0, len(modalities) - 1) * 0.025)
        + (0.03 if "review_completed" in modalities else 0.0),
    )
    metacognition = base_score("metacognition", 0.5)
    if calibration_scores:
        metacognition = metacognition * 0.65 + (sum(calibration_scores) / len(calibration_scores)) * 0.35
    if "feynman_submitted" in modalities:
        metacognition += 0.03

    dimension_scores = {
        "knowledge_mastery": _clamp(average_mastery),
        "misconception_profile": misconception,
        "understanding_fluency_transfer": _clamp(transfer),
        "cognitive_processing": _clamp(1.0 - load),
        "learning_strategy": strategy,
        "metacognition": _clamp(metacognition),
        "motivation_and_purpose": _clamp(
            base_score("motivation_and_purpose", 0.54) + min(0.08, len(events) * 0.01),
        ),
        "affect_resilience": _clamp(focus - frustration * 0.35),
        "interaction_preference": base_score("interaction_preference", 0.56),
        "learning_context": base_score("learning_context", 0.48),
    }
    statuses = {
        "knowledge_mastery": "掌握证据稳定" if average_mastery >= 0.7 else "仍有知识点需要巩固",
        "misconception_profile": (
            "已出现纠错恢复" if unsuccessful and successful
            else "仍有错误证据需复习" if unsuccessful
            else "暂未发现新增稳定误概念"
        ),
        "understanding_fluency_transfer": "迁移能力已获得实作证据" if transfer_scores else "迁移表现待验证",
        "cognitive_processing": "负荷处于可教学区间" if load < 0.62 else "认知负荷偏高",
        "learning_strategy": "已使用多种学习策略" if len(modalities) >= 3 else "策略证据仍需丰富",
        "metacognition": "自我解释与测评证据已校准" if calibration_scores else "自评校准待继续观察",
        "motivation_and_purpose": "持续完成任务，目标投入稳定" if events else "目标意义仍需澄清",
        "affect_resilience": "经历错误后已形成恢复证据" if unsuccessful and successful else "情绪风险暂未升高",
        "interaction_preference": str(
            (baseline_dimensions.get("interaction_preference") or {}).get("status")
            or "统一演示流程不用于推断自主互动偏好"
        ),
        "learning_context": str((baseline_dimensions.get("learning_context") or {}).get("status") or "学习情境保持不变"),
    }
    dimensions: dict[str, dict[str, Any]] = {}
    for key, label in DIMENSION_LABELS.items():
        previous = deepcopy(baseline_dimensions.get(key) or {})
        relevant = [
            (item, score) for item, score in scored_events
            if item.event_type in _DIMENSION_EVENT_TYPES[key]
        ]
        fragments = _dimension_evidence_fragments(
            session,
            key,
            scored_events,
            load=load,
            frustration=frustration,
            focus=focus,
        )
        if not fragments:
            fragments = list(previous.get("evidence_fragments") or [])[-3:]
        dimensions[key] = {
            "key": key,
            "label": str(previous.get("label") or label),
            "score": round(dimension_scores[key], 2),
            "confidence": round(max(
                float(previous.get("confidence", 0.48)),
                min(0.94, 0.52 + len(relevant) * 0.05),
            ), 2),
            "status": statuses[key],
            "evidence_count": int(previous.get("evidence_count", 0)) + len(relevant),
            "evidence_fragments": fragments,
            "recommended_interventions": list(previous.get("recommended_interventions") or []),
            "last_updated": _iso(relevant[-1][0].occurred_at) if relevant else str(previous.get("last_updated") or ""),
        }

    causes = deepcopy(baseline_data.get("learning_state_causes") or {})
    recent_fragments = [_event_fragment(session, item, score) for item, score in scored_events[-3:]]
    cause_specs = {
        "cognitive_load": ("高认知负荷", load),
        "affective_barrier": ("学习焦虑障碍", frustration),
    }
    for key, (label, value) in cause_specs.items():
        previous = deepcopy(causes.get(key) or {})
        causes[key] = {
            "key": key,
            "label": str(previous.get("label") or label),
            "percentage": round(value * 100, 1),
            "confidence": round(min(0.94, 0.55 + len(events) * 0.04), 2),
            "evidence_count": int(previous.get("evidence_count", 0)) + len(events),
            "evidence_fragments": recent_fragments or list(previous.get("evidence_fragments") or [])[-3:],
            "recommended_interventions": list(previous.get("recommended_interventions") or []),
        }

    profile.focus_level = round(focus, 4)
    profile.cognitive_load = round(load, 4)
    profile.frustration_index = round(frustration, 4)
    profile.dimension_states = dimensions
    profile.learning_state_causes = causes
    profile.mental_state_history = history[-35:]
    return {
        "accepted_event_ids": [item.id for item in events],
        "focus_level": profile.focus_level,
        "cognitive_load": profile.cognitive_load,
        "frustration_index": profile.frustration_index,
        "dimension_states": dimensions,
        "learning_state_causes": causes,
        "mental_state_history": profile.mental_state_history,
    }


def _project_profile(session: Any, event: DBLearningEvent) -> dict[str, Any]:
    _, profile = _owner_profile(session, event)
    baseline = _baseline_snapshot(session, event, profile)
    behavior_baseline = _behavior_baseline_snapshot(session, event, profile, baseline)
    baseline_data = baseline.snapshot or {}
    grouped: dict[str, list[tuple[DBLearningEvent, float]]] = {}
    concept_ids: dict[str, str] = {}
    for item, concept_id, concept_title, observation in _mastery_events(session, event):
        grouped.setdefault(concept_title, []).append((item, observation))
        concept_ids[concept_title] = concept_id

    current_mastery = dict(profile.concept_mastery or {})
    before = dict(current_mastery)
    baseline_mastery = dict(baseline_data.get("concept_mastery") or {})
    traces = dict(profile.knowledge_traces or {})
    weak_points = list(profile.weak_points or [])
    changed: dict[str, dict[str, float]] = {}
    for concept_title, items in grouped.items():
        mastery = float(baseline_mastery.get(concept_title, 0.45))
        correct_attempts = 0
        for item, observation in items:
            alpha = max(0.05, min(0.5, float(item.evidence_strength or 0.0) * 0.5))
            mastery = max(0.0, min(1.0, mastery + alpha * (observation - mastery)))
            if observation >= 0.6:
                correct_attempts += 1
        mastery = round(mastery, 4)
        old = float(current_mastery.get(concept_title, baseline_mastery.get(concept_title, 0.45)))
        current_mastery[concept_title] = mastery
        traces[concept_title] = {
            "concept": concept_title,
            "knowledge_point_id": concept_ids[concept_title],
            "mastery": mastery,
            "attempts": len(items),
            "correct_attempts": correct_attempts,
            "last_updated": _iso(items[-1][0].occurred_at),
            "source_event_id": items[-1][0].id,
        }
        if mastery < 0.6 and concept_title not in weak_points:
            weak_points.insert(0, concept_title)
        elif mastery >= 0.7 and concept_title in weak_points:
            weak_points = [item for item in weak_points if item != concept_title]
        if round(old, 4) != mastery:
            changed[concept_title] = {"before": round(old, 4), "after": mastery}

    profile.concept_mastery = current_mastery
    profile.knowledge_traces = traces
    profile.weak_points = weak_points[:20]
    behavior_before = {
        "focus_level": float(profile.focus_level if profile.focus_level is not None else 0.72),
        "cognitive_load": float(profile.cognitive_load if profile.cognitive_load is not None else 0.45),
        "frustration_index": float(profile.frustration_index if profile.frustration_index is not None else 0.0),
        "dimension_states": deepcopy(profile.dimension_states or {}),
    }
    behavior_projection = _project_behavior_profile(
        session,
        event=event,
        profile=profile,
        baseline=behavior_baseline,
        current_mastery=current_mastery,
    )
    profile.narrative_report = ""
    profile.dashboard_report = ""
    profile.last_updated = _now()

    snapshot_data = {
        "kind": "learning_aggregation_projection",
        "source_event_id": event.id,
        "owner_public_id": event.owner_public_id,
        "legacy_student_id": profile.student_id,
        "course_id": event.course_id,
        "concept_mastery": current_mastery,
        "weak_points": profile.weak_points,
        "knowledge_traces": traces,
        "changed_concepts": changed,
        "focus_level": behavior_projection["focus_level"],
        "cognitive_load": behavior_projection["cognitive_load"],
        "frustration_index": behavior_projection["frustration_index"],
        "dimension_states": behavior_projection["dimension_states"],
        "learning_state_causes": behavior_projection["learning_state_causes"],
        "mental_state_history": behavior_projection["mental_state_history"],
        "accepted_behavior_event_ids": behavior_projection["accepted_event_ids"],
        "next_day_schedule": _next_day_schedule(session, event),
    }
    snapshot_id = _stable_id("psagg", event.id)
    snapshot = session.query(DBProfileSnapshot).filter_by(id=snapshot_id).first()
    if snapshot is None:
        snapshot = DBProfileSnapshot(
            id=snapshot_id,
            owner_public_id=event.owner_public_id,
            legacy_student_id=profile.student_id,
            profile_version=AGGREGATION_PROCESSOR_VERSION,
            snapshot=snapshot_data,
            content_hash=_hash(snapshot_data),
            trace_id=event.trace_id,
        )
        session.add(snapshot)
    return {
        "source_event_id": event.id,
        "profile_snapshot_id": snapshot.id,
        "baseline_snapshot_id": baseline.id,
        "behavior_baseline_snapshot_id": behavior_baseline.id,
        "mastery_changed": bool(changed),
        "changed_concepts": changed,
        "mastery_before": before,
        "mastery_after": current_mastery,
        "behavior_before": behavior_before,
        "behavior_after": {
            "focus_level": behavior_projection["focus_level"],
            "cognitive_load": behavior_projection["cognitive_load"],
            "frustration_index": behavior_projection["frustration_index"],
            "dimension_states": behavior_projection["dimension_states"],
        },
        "next_day_schedule": snapshot_data["next_day_schedule"],
    }


def _event_matches_node(session: Any, item: DBLearningEvent, node: DBPathNode) -> bool:
    task_id = (item.context_ref or {}).get("taskId")
    if task_id == node.id or (node.target_object_id and item.object_id == node.target_object_id):
        return True
    if node.node_type != "chapter" or not node.target_object_id:
        return False
    chapter_point_ids = {
        str(row[0]) for row in session.query(DBChapterKnowledgePoint.knowledge_point_id).filter_by(
            chapter_id=node.target_object_id,
        ).all()
    }
    if not chapter_point_ids:
        return False
    context = item.context_ref or {}
    payload = item.payload or {}
    event_point_ids = {
        str(value) for value in (
            context.get("knowledgePointId"),
            context.get("knowledge_point_id"),
            payload.get("knowledgePointId"),
            payload.get("knowledge_point_id"),
        ) if value
    }
    return bool(chapter_point_ids.intersection(event_point_ids))


def _project_path(session: Any, event: DBLearningEvent) -> dict[str, Any]:
    events = _scope_events(session, event)
    paths = session.query(DBLearningPath).filter(
        DBLearningPath.owner_public_id == event.owner_public_id,
        DBLearningPath.status.in_(("active", "paused", "completed")),
    )
    paths = paths.filter(
        DBLearningPath.course_id.is_(None)
        if event.course_id is None else DBLearningPath.course_id == event.course_id
    )
    current_result = {
        "path_id": None,
        "node_id": None,
        "old_status": None,
        "new_status": None,
        "prerequisite_blocked": False,
    }
    summaries: list[dict[str, Any]] = []
    for path in paths.order_by(DBLearningPath.created_at, DBLearningPath.id).all():
        nodes = session.query(DBPathNode).filter_by(learning_path_id=path.id).order_by(
            DBPathNode.sequence, DBPathNode.id,
        ).all()
        completed_keys = {node.node_key for node in nodes if node.status == "completed"}
        for node in nodes:
            matching = [item for item in events if _event_matches_node(session, item, node)]
            old_status = node.status
            complete_requested = any(item.completion_effect == "complete" for item in matching)
            progress_requested = complete_requested or any(
                item.completion_effect == "progress" for item in matching
            )
            blocked = complete_requested and not set(node.prerequisites or []).issubset(completed_keys)
            if complete_requested and not blocked:
                node.status = "completed"
                completed_keys.add(node.node_key)
                node.blocked_reason = ""
            elif progress_requested and node.status == "pending":
                node.status = "in_progress"
                node.blocked_reason = "前置任务尚未完成" if blocked else ""
            actual_values = [
                int(item.payload["actual_minutes"])
                for item in matching
                if item.payload and item.payload.get("actual_minutes") is not None
            ]
            if actual_values:
                node.actual_minutes = max(0, actual_values[-1])
            if _event_matches_node(session, event, node):
                current_result = {
                    "path_id": path.id,
                    "node_id": node.id,
                    "old_status": old_status,
                    "new_status": node.status,
                    "prerequisite_blocked": blocked,
                }
        if nodes and all(node.status == "completed" for node in nodes) and path.status != "completed":
            path.status = "completed"
            path.completed_at = _now()
            path.lock_version += 1
        path.updated_at = _now()
        summaries.append({
            "path_id": path.id,
            "status": path.status,
            "completed_nodes": sum(node.status == "completed" for node in nodes),
            "total_nodes": len(nodes),
        })
    return {
        **current_result,
        "source_event_id": event.id,
        "paths": summaries,
        "next_day_schedule": _next_day_schedule(session, event),
        "recommended_knowledge_point_ids": list(
            (event.payload or {}).get("recommended_knowledge_point_ids") or []
        ),
        "mastery_changed": False,
        "mastery_evidence": {
            "event_id": event.id,
            "eligible": bool(event.mastery_eligible),
            "status": event.evidence_status,
            "strength": float(event.evidence_strength or 0.0),
            "reason": event.evidence_reason,
        },
    }


def _review_interval(event: DBLearningEvent, mastery: float, observation: float) -> int:
    if event.event_type == "delayed_retest_passed":
        return 14
    if observation >= 0.85 and mastery >= 0.8:
        return 7
    if observation >= 0.6:
        return 3
    return 1


def _merge_wrong_question_rows(
    session: Any,
    *,
    rows: list[DBWrongQuestion],
    question_version_id: str,
) -> DBWrongQuestion:
    rows.sort(key=lambda row: (row.created_at or datetime.max, row.id or 0))
    survivor = rows[0]
    confirmed_reason = next(
        (
            str(row.wrong_reason_category)
            for row in rows
            if row.wrong_reason_category
            and row.wrong_reason_category != "pending_confirmation"
        ),
        str(survivor.wrong_reason_category or "pending_confirmation"),
    )
    preserved_note = next((str(row.notes) for row in rows if row.notes), "")
    survivor.quiz_record_id = next(
        (row.quiz_record_id for row in rows if row.quiz_record_id),
        None,
    )
    survivor.source_event_id = next(
        (row.source_event_id for row in rows if row.source_event_id),
        None,
    )
    survivor.wrong_reason_category = confirmed_reason
    survivor.pinned = any(bool(row.pinned) for row in rows)
    survivor.notes = preserved_note
    for duplicate in rows[1:]:
        session.query(DBWrongQuestionVideoLink).filter(
            DBWrongQuestionVideoLink.wrong_question_id == duplicate.id,
        ).update(
            {DBWrongQuestionVideoLink.wrong_question_id: survivor.id},
            synchronize_session=False,
        )
        session.delete(duplicate)
    session.flush()
    survivor.source_object_id = question_version_id
    session.flush()
    return survivor


def bind_legacy_wrong_question_version(
    session: Any,
    *,
    student_id: str,
    quiz_record_id: str,
    question_version_id: str,
) -> DBWrongQuestion | None:
    """Bind pre-canonical 7.20 rows to one frozen question version."""
    rows = session.query(DBWrongQuestion).filter(
        DBWrongQuestion.student_id == student_id,
        (
            (DBWrongQuestion.quiz_record_id == quiz_record_id)
            | (DBWrongQuestion.source_object_id == quiz_record_id)
            | (DBWrongQuestion.source_object_id == question_version_id)
        ),
    ).all()
    if not rows:
        return None
    return _merge_wrong_question_rows(
        session,
        rows=rows,
        question_version_id=question_version_id,
    )


def upsert_wrong_question(
    session: Any,
    *,
    student_id: str,
    question_version_id: str,
    source_event_id: str,
    concept_name: str,
    quiz_record_id: str | None = None,
) -> DBWrongQuestion:
    wrong = None
    if quiz_record_id:
        wrong = bind_legacy_wrong_question_version(
            session,
            student_id=student_id,
            quiz_record_id=quiz_record_id,
            question_version_id=question_version_id,
        )
    if wrong is None:
        wrong = session.query(DBWrongQuestion).filter_by(
            student_id=student_id,
            source_object_id=question_version_id,
        ).first()
    if wrong is None:
        wrong = DBWrongQuestion(
            student_id=student_id,
            quiz_record_id=quiz_record_id,
            source_event_id=source_event_id,
            source_object_id=question_version_id,
            concept_name=concept_name,
            wrong_reason_category="pending_confirmation",
        )
        session.add(wrong)
        session.flush()
        return wrong
    if wrong.source_event_id is None:
        wrong.source_event_id = source_event_id
    if wrong.quiz_record_id is None and quiz_record_id:
        wrong.quiz_record_id = quiz_record_id
    if not wrong.concept_name:
        wrong.concept_name = concept_name
    if not wrong.wrong_reason_category:
        wrong.wrong_reason_category = "pending_confirmation"
    session.flush()
    return wrong


def _project_wrong_review(session: Any, event: DBLearningEvent) -> dict[str, Any]:
    mastery_events = _mastery_events(session, event)
    if not mastery_events:
        return {
            "source_event_id": event.id,
            "concept": None,
            "wrong_question_ids": [],
            "review_plan_id": None,
            "reason": "event is not accepted mastery evidence",
        }
    _, profile = _owner_profile(session, event)
    wrong_ids: list[int] = []
    if event.event_type == "formal_exam_submitted":
        for result in (event.payload or {}).get("item_results") or []:
            score = result.get("score")
            if score is None or float(score) >= 0.6:
                continue
            point_id = str(result.get("knowledge_point_id") or "").strip()
            point = session.query(DBKnowledgePoint).filter_by(id=point_id).first() if point_id else None
            source_object_id = str(result.get("question_version_id") or "").strip() or None
            if not source_object_id:
                continue
            wrong = upsert_wrong_question(
                session,
                student_id=profile.student_id,
                question_version_id=source_object_id,
                source_event_id=event.id,
                concept_name=point.title if point else "正式组卷错题",
            )
            if wrong.id not in wrong_ids:
                wrong_ids.append(wrong.id)
    else:
        for item, _, concept_title, observation in mastery_events:
            if item.event_type != "quiz_answered" or observation >= 0.5:
                continue
            source_object_id = item.object_id or None
            if not source_object_id:
                continue
            quiz_record_id = str((item.payload or {}).get("source_object_id") or "").strip() or None
            wrong = upsert_wrong_question(
                session,
                student_id=profile.student_id,
                question_version_id=source_object_id,
                source_event_id=item.id,
                concept_name=concept_title,
                quiz_record_id=quiz_record_id,
            )
            if wrong.id not in wrong_ids:
                wrong_ids.append(wrong.id)

    review_plans: list[dict[str, Any]] = []
    grouped: dict[str, list[tuple[DBLearningEvent, str, str, float]]] = {}
    for item in mastery_events:
        grouped.setdefault(item[2], []).append(item)
    for concept_title, concept_events in grouped.items():
        latest_event, _, _, latest_observation = concept_events[-1]
        mastery = float((profile.concept_mastery or {}).get(concept_title, 0.45))
        interval = _review_interval(latest_event, mastery, latest_observation)
        plan = session.query(DBReviewPlan).filter_by(
            student_id=profile.student_id, concept=concept_title,
        ).order_by(DBReviewPlan.id).first()
        if plan is None:
            plan = DBReviewPlan(student_id=profile.student_id, concept=concept_title)
            session.add(plan)
        plan.interval_days = interval
        plan.next_review_at = latest_event.occurred_at + timedelta(days=interval)
        plan.mastery = round(mastery, 4)
        plan.review_count = max(
            int(plan.review_count or 0),
            sum(item[0].event_type in {"review_completed", "delayed_retest_passed"} for item in concept_events),
        )
        plan.easiness_factor = round(max(1.3, min(2.7, 1.7 + mastery)), 2)
        plan.last_quality = max(0, min(5, int(round(latest_observation * 5))))
        plan.priority = 0.35 if mastery < 0.5 else (0.7 if interval <= 3 else 1.0)
        session.flush()
        review_plans.append({
            "concept": concept_title,
            "review_plan_id": plan.id,
            "next_review_at": _iso(plan.next_review_at),
            "interval_days": interval,
            "mastery": round(mastery, 4),
        })
    first_plan = review_plans[0] if review_plans else {}
    return {
        "source_event_id": event.id,
        "concept": first_plan.get("concept"),
        "wrong_question_ids": wrong_ids,
        "review_plan_id": first_plan.get("review_plan_id"),
        "next_review_at": first_plan.get("next_review_at"),
        "interval_days": first_plan.get("interval_days"),
        "mastery": first_plan.get("mastery"),
        "review_plans": review_plans,
    }


def _project_activity(session: Any, event: DBLearningEvent) -> dict[str, Any]:
    return {
        "source_event_id": event.id,
        "activity_event_id": event.id,
        "action": event.action,
        "occurred_at": _iso(event.occurred_at),
        "activity_count": len(_scope_events(session, event)),
    }


def _project_dashboard(session: Any, event: DBLearningEvent) -> dict[str, Any]:
    _, profile = _owner_profile(session, event)
    mastery = dict(profile.concept_mastery or {})
    events = _scope_events(session, event)
    latest_event = events[-1] if events else event
    reference_time = latest_event.occurred_at
    paths = session.query(DBLearningPath).filter(
        DBLearningPath.owner_public_id == event.owner_public_id,
        DBLearningPath.status.in_(("active", "paused", "completed")),
    )
    paths = paths.filter(
        DBLearningPath.course_id.is_(None)
        if event.course_id is None else DBLearningPath.course_id == event.course_id
    ).all()
    nodes = session.query(DBPathNode).filter(
        DBPathNode.learning_path_id.in_([path.id for path in paths] or ["-"]),
    ).all()
    reviews = session.query(DBReviewPlan).filter_by(student_id=profile.student_id).all()
    summary = {
        "source_event_id": event.id,
        "course_id": event.course_id,
        "mastery_average": round(sum(mastery.values()) / len(mastery), 4) if mastery else None,
        "mastery_concept_count": len(mastery),
        "weak_points": list(profile.weak_points or [])[:5],
        "activity_count": len(events),
        "path_completed": sum(node.status == "completed" for node in nodes),
        "path_total": len(nodes),
        "review_due": sum(
            plan.next_review_at is None or plan.next_review_at <= reference_time for plan in reviews
        ),
        "latest_action": latest_event.action,
        "latest_event_at": _iso(latest_event.occurred_at),
        "next_day_schedule": _next_day_schedule(session, event),
    }
    return {"source_event_id": event.id, "summary": summary}


_STEP_HANDLERS: dict[str, Callable[[Any, DBLearningEvent], dict[str, Any]]] = {
    "profile_snapshot": _project_profile,
    "path_task": _project_path,
    "wrong_review": _project_wrong_review,
    "activity": _project_activity,
    "dashboard": _project_dashboard,
}


def _append_state(result: dict[str, Any], state: str) -> None:
    history = list(result.get("state_history") or [])
    if not history or history[-1] != state:
        history.append(state)
    result["state_history"] = history
    result["aggregate_status"] = state


def _persist(session: Any, consumption: DBLearningEventConsumption, result: dict[str, Any]) -> None:
    consumption.result = dict(result)
    session.commit()


def _sync_contract(
    session: Any,
    *,
    event: DBLearningEvent,
    result: dict[str, Any],
) -> None:
    completed = set(result.get("completed_steps") or [])
    failed_step = (result.get("last_failure") or {}).get("step")
    expected = {
        view_id: {
            "label": contract["label"],
            "route": contract["route"],
            "step": contract["step"],
        }
        for view_id, contract in AGGREGATION_VIEW_CONTRACT.items()
    }
    snapshots: dict[str, dict[str, Any]] = {}
    for view_id, contract in AGGREGATION_VIEW_CONTRACT.items():
        step = contract["step"]
        step_result = dict((result.get("steps") or {}).get(step) or {})
        status = "completed" if step in completed else ("failed" if step == failed_step else "pending")
        snapshots[view_id] = {
            **expected[view_id],
            "status": status,
            "version": (
                _hash({"event_id": event.id, "step": step, "result": step_result})
                if status == "completed"
                else None
            ),
        }

    result["affectedViews"] = list(AGGREGATION_VIEW_CONTRACT)
    result["expectedSnapshots"] = expected
    result["snapshots"] = snapshots
    result["nextDaySchedule"] = _next_day_schedule(session, event)
    result["sourceEvent"] = {
        "id": event.id,
        "eventType": event.event_type,
        "label": _FEEDBACK_SOURCE_LABELS.get(event.event_type, "学习任务"),
        "courseId": event.course_id,
        "objectType": event.object_type,
        "objectId": event.object_id,
        "occurredAt": _iso(event.occurred_at),
    }
    if all(item["status"] == "completed" for item in snapshots.values()):
        result["consistencyToken"] = _hash({
            "event_id": event.id,
            "processor_version": AGGREGATION_PROCESSOR_VERSION,
            "snapshot_versions": {
                view_id: item["version"] for view_id, item in snapshots.items()
            },
        })
    else:
        result["consistencyToken"] = None


def learning_feedback_payload(
    event: DBLearningEvent,
    consumption: DBLearningEventConsumption | None,
) -> dict[str, Any]:
    result = dict(consumption.result or {}) if consumption else {}
    snapshots = dict(result.get("snapshots") or {})
    failed_step = (result.get("last_failure") or {}).get("step")
    views = []
    for view_id, contract in AGGREGATION_VIEW_CONTRACT.items():
        snapshot = dict(snapshots.get(view_id) or {})
        step = contract["step"]
        status = snapshot.get("status") or (
            "failed" if step == failed_step else "pending"
        )
        views.append({
            "id": view_id,
            "label": contract["label"],
            "route": contract["route"],
            "step": step,
            "status": status,
            "snapshotVersion": snapshot.get("version"),
        })
    status = consumption.status if consumption else "pending"
    return {
        "schemaVersion": "f8.learning-feedback.v1",
        "event": {
            "id": event.id,
            "eventType": event.event_type,
            "label": _FEEDBACK_SOURCE_LABELS.get(event.event_type, "学习任务"),
            "courseId": event.course_id,
            "objectType": event.object_type,
            "objectId": event.object_id,
            "occurredAt": _iso(event.occurred_at),
        },
        "status": status,
        "attempt": int(consumption.attempt if consumption else 0),
        "errorCode": str(consumption.error_code or "") if consumption else "",
        "recoverable": status != "processed",
        "completedCount": sum(item["status"] == "completed" for item in views),
        "totalCount": len(views),
        "views": views,
        "affectedViews": list(result.get("affectedViews") or AGGREGATION_VIEW_CONTRACT),
        "expectedSnapshots": dict(result.get("expectedSnapshots") or {
            item["id"]: {
                "label": item["label"],
                "route": item["route"],
                "step": item["step"],
            }
            for item in views
        }),
        "consistencyToken": result.get("consistencyToken"),
        "nextDaySchedule": list(result.get("nextDaySchedule") or []),
        "completedAt": result.get("completed_at"),
    }


def aggregate_learning_event(
    session: Any,
    *,
    event: DBLearningEvent,
    processor_version: str = AGGREGATION_PROCESSOR_VERSION,
) -> DBLearningEventConsumption:
    """Project one immutable event through five recoverable, idempotent steps."""
    event_id = event.id
    consumption = session.query(DBLearningEventConsumption).filter_by(
        learning_event_id=event_id,
        consumer="learning_aggregation",
        processor_version=processor_version,
    ).first()
    if consumption is not None and consumption.status == "processed":
        return consumption
    if consumption is None:
        consumption = DBLearningEventConsumption(
            learning_event_id=event_id,
            consumer="learning_aggregation",
            processor_version=processor_version,
            status="pending",
            result={
                "schema_version": "f2.learning-aggregation.result.v1",
                "source_event_id": event_id,
                "step_order": list(AGGREGATION_STEPS),
                "completed_steps": [],
                "steps": {},
                "current_step": None,
                "next_step": AGGREGATION_STEPS[0],
            },
        )
        session.add(consumption)
        session.flush()
        result = dict(consumption.result or {})
        _append_state(result, "queued")
        _sync_contract(session, event=event, result=result)
        _persist(session, consumption, result)
    else:
        result = dict(consumption.result or {})
        if consumption.status == "failed":
            consumption.attempt += 1
            consumption.status = "pending"
            consumption.error_code = ""
            result["recovered_from_failure"] = True
            result["recovered_at"] = _iso(_now())
            _append_state(result, "recovered")
            _sync_contract(session, event=event, result=result)
            _persist(session, consumption, result)

    consumption = session.query(DBLearningEventConsumption).filter_by(id=consumption.id).one()
    result = dict(consumption.result or {})
    _append_state(result, "running")
    _sync_contract(session, event=event, result=result)
    _persist(session, consumption, result)

    completed = list(result.get("completed_steps") or [])
    for index, step in enumerate(AGGREGATION_STEPS):
        if step in completed:
            continue
        consumption = session.query(DBLearningEventConsumption).filter_by(id=consumption.id).one()
        result = dict(consumption.result or {})
        result["current_step"] = step
        result["next_step"] = step
        _append_state(result, "running")
        _sync_contract(session, event=event, result=result)
        _persist(session, consumption, result)
        try:
            current_event = session.query(DBLearningEvent).filter_by(id=event_id).one()
            step_result = _STEP_HANDLERS[step](session, current_event)
            consumption = session.query(DBLearningEventConsumption).filter_by(id=consumption.id).one()
            result = dict(consumption.result or {})
            steps = dict(result.get("steps") or {})
            steps[step] = step_result
            completed = list(result.get("completed_steps") or [])
            if step not in completed:
                completed.append(step)
            result["steps"] = steps
            if step == "path_task":
                for key in (
                    "path_id", "node_id", "old_status", "new_status",
                    "prerequisite_blocked", "mastery_changed", "mastery_evidence",
                ):
                    result[key] = step_result.get(key)
            result["completed_steps"] = completed
            result["current_step"] = None
            result["next_step"] = (
                AGGREGATION_STEPS[index + 1] if index + 1 < len(AGGREGATION_STEPS) else None
            )
            _sync_contract(session, event=current_event, result=result)
            _persist(session, consumption, result)
        except Exception as exc:
            session.rollback()
            consumption = session.query(DBLearningEventConsumption).filter_by(
                learning_event_id=event_id,
                consumer="learning_aggregation",
                processor_version=processor_version,
            ).one()
            result = dict(consumption.result or {})
            consumption.status = "failed"
            consumption.error_code = f"aggregation_{step}_{type(exc).__name__.lower()}"
            result["current_step"] = step
            result["next_step"] = step
            result["last_failure"] = {"step": step, "error_code": consumption.error_code}
            _append_state(result, "partial" if result.get("completed_steps") else "failed")
            current_event = session.query(DBLearningEvent).filter_by(id=event_id).one()
            _sync_contract(session, event=current_event, result=result)
            _persist(session, consumption, result)
            raise

    consumption = session.query(DBLearningEventConsumption).filter_by(id=consumption.id).one()
    result = dict(consumption.result or {})
    result["current_step"] = None
    result["next_step"] = None
    result["completed_at"] = _iso(_now())
    _append_state(result, "completed")
    current_event = session.query(DBLearningEvent).filter_by(id=event_id).one()
    _sync_contract(session, event=current_event, result=result)
    consumption.status = "processed"
    consumption.processed_at = _now()
    consumption.error_code = ""
    _persist(session, consumption, result)
    return session.query(DBLearningEventConsumption).filter_by(id=consumption.id).one()


def get_learning_aggregation(
    session: Any,
    *,
    event_id: str,
    processor_version: str = AGGREGATION_PROCESSOR_VERSION,
) -> DBLearningEventConsumption | None:
    return session.query(DBLearningEventConsumption).filter_by(
        learning_event_id=event_id,
        consumer="learning_aggregation",
        processor_version=processor_version,
    ).first()
