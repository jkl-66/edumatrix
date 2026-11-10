"""Resumable diagnostic preparation using the existing generation-task tables."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib

from sqlalchemy.orm import Session

from app.database import DBGenerationTask, DBTaskEvent, DBUser, DBDiagnosticBlueprint
from app.diagnostic_generation import (
    DiagnosticBlueprintRequest, DiagnosticGenerationError, diagnostic_preflight,
    diagnostic_blueprint_payload, generate_diagnostic_blueprint,
    _readable_course, _latest_profile,
)
from app.m1_repository import append_task_event, create_generation_task


CAPABILITY = "diagnostic.prepare"
STAGES = (
    ("analysis", "分析课程与学习起点"),
    ("generation", "准备诊断题"),
    ("validation", "核对题目与来源"),
    ("review", "复核答案与学习要求"),
)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _event(session, task_id, kind):
    return session.query(DBTaskEvent).filter_by(task_id=task_id, event_type=kind).order_by(
        DBTaskEvent.sequence.desc()).first()


def _owned(session, task_id, user):
    task = session.get(DBGenerationTask, task_id)
    if task is None or task.capability != CAPABILITY or task.owner_public_id != user.public_id:
        raise DiagnosticGenerationError("diagnostic_task_unknown", "没有找到这次诊断准备。", status_code=404)
    return task


def task_payload(session, task):
    from app.generation_dispatch import public_automation
    automation = public_automation(task)
    request_event = _event(session, task.id, "diagnostic.request")
    stage_event = _event(session, task.id, "diagnostic.stage")
    result_event = _event(session, task.id, "diagnostic.completed")
    stage = (stage_event.payload or {}).get("stage", "analysis") if stage_event else "analysis"
    index = next((i for i, (key, _) in enumerate(STAGES) if key == stage), 0)
    stages = [{"key": key, "label": label, "status": (
        "completed" if task.status == "completed" or i < index else
        "failed" if task.status == "failed" and i == index else
        "processing" if task.status == "running" and i == index else "pending"
    )} for i, (key, label) in enumerate(STAGES)]
    blueprint = session.get(DBDiagnosticBlueprint, (result_event.payload or {}).get("blueprintId")) if result_event else None
    return {
        "id": task.id, "status": task.status,
        "request": (request_event.payload or {}).get("request", {}) if request_event else {},
        "generationStages": stages,
        "automation": automation,
        "message": automation['message'] if automation['enabled'] else task.failure_reason if task.status == "failed" else "",
        "blueprint": diagnostic_blueprint_payload(session, blueprint) if blueprint else None,
    }


def get_diagnostic_task(session, *, task_id, user):
    return task_payload(session, _owned(session, task_id, user))


def _selected_stage(preflight):
    return (preflight.get("assessmentScope", {}).get("selected") or {}).get("id")


def _saved_stage(session, task, data):
    stage = data.get("resolvedStageId") or data.get("request", {}).get("stage_id")
    if stage:
        return stage
    # Older tasks kept the optional input only. A completed paper is the
    # authority for its scope even if the learner's default has since moved.
    completed = _event(session, task.id, "diagnostic.completed")
    blueprint = session.get(DBDiagnosticBlueprint, (completed.payload or {}).get("blueprintId")) if completed else None
    if blueprint:
        return _selected_stage((blueprint.review_decision or {}).get("contextSnapshot") or {})
    return None


def find_diagnostic_task(session, *, user, course_id, question_count, self_rating, stage_id=None):
    course = _readable_course(session, course_id=course_id, user=user)
    profile = _latest_profile(session, user.public_id, course_id)
    course_version = course.version
    profile_id = profile.id if profile else None
    default_stage = None

    def resolve_default():
        nonlocal default_stage
        if default_stage is None:
            default_stage = _selected_stage(diagnostic_preflight(session, user=user, course_id=course_id,
                question_count=question_count, self_rating=self_rating))
        return default_stage

    for task in session.query(DBGenerationTask).filter_by(
        owner_public_id=user.public_id, course_id=course_id, capability=CAPABILITY,
    ).order_by(DBGenerationTask.created_at.desc(), DBGenerationTask.id.desc()):
        event = _event(session, task.id, "diagnostic.request")
        data = event.payload if event else {}
        request = data.get("request", {})
        if (request.get("question_count") == question_count and request.get("self_rating") == self_rating
                and data.get("courseVersion") == course_version and data.get("profileId") == profile_id):
            saved_stage = _saved_stage(session, task, data) or resolve_default()
            if saved_stage == (stage_id or resolve_default()):
                return task_payload(session, task)
    return None


def queue_diagnostic_task(session, *, user, request):
    preflight = diagnostic_preflight(session, user=user, course_id=request.course_id,
                                    question_count=request.question_count, self_rating=request.self_rating, stage_id=request.stage_id)
    if not preflight.get("canGenerate"):
        raise DiagnosticGenerationError("diagnostic_not_ready", "请先完成学习起点确认，并检查课程资料。")
    key = "diagnostic:" + hashlib.sha256((request.course_id + ":" + request.idempotency_key).encode()).hexdigest()
    task, created = create_generation_task(session, owner_public_id=user.public_id,
        capability=CAPABILITY, idempotency_key=key, course_id=request.course_id, model="deepseek-v4-flash")
    expected = {"request": asdict(request), "courseVersion": preflight["course"]["version"],
                "profileId": preflight["profileBasis"]["id"]}
    if created:
        append_task_event(session, task_id=task.id, event_type="diagnostic.request",
                          payload={**expected, "resolvedStageId": _selected_stage(preflight)})
    else:
        previous = _event(session, task.id, "diagnostic.request")
        previous_payload = dict(previous.payload) if previous else {}
        previous_request = dict(previous_payload.get("request") or {})
        current_request = dict(expected["request"])
        previous_request.pop("stage_id", None)
        current_request.pop("stage_id", None)
        previous_stage = _saved_stage(session, task, previous_payload)
        if previous and not previous_stage:
            previous_stage = _selected_stage(diagnostic_preflight(session, user=user, course_id=request.course_id,
                question_count=request.question_count, self_rating=request.self_rating))
        if (previous is None or previous_request != current_request
                or any(previous_payload.get(key) != expected[key] for key in ("courseVersion", "profileId"))
                or previous_stage != _selected_stage(preflight)):
            raise DiagnosticGenerationError("diagnostic_idempotency_conflict", "课程或诊断要求已改变，请重新开始准备。")
        if task.status in {"failed", "cancelled"} and not task.automation_state:
            # Retain every failure event; an explicit retry reuses the same task.
            task.status = "queued"
            task.failure_code = task.failure_reason = ""
            task.completed_at = None
            append_task_event(session, task_id=task.id, event_type="diagnostic.retry", payload={})
    from app.learning_generation_jobs import enable_task
    enable_task(task)
    session.commit()
    return task_payload(session, task)


def execute_diagnostic_task(task_id, llm_factory, *, session_factory=None, execution_token=None):
    if session_factory is None:
        from app.database import SessionLocal
        session_factory = SessionLocal
    with session_factory() as session:
        from app.learning_generation_jobs import assert_generation_owner
        # Claim once, even if two tabs submitted the same queued task.
        changed = execution_token or session.query(DBGenerationTask).filter_by(
            id=task_id, capability=CAPABILITY, status="queued",
        ).filter(DBGenerationTask.automation_state == '').update({"status": "running", "started_at": _now()}, synchronize_session=False)
        session.commit()
        if not changed:
            return
        task = session.get(DBGenerationTask, task_id)
        request = DiagnosticBlueprintRequest(**_event(session, task_id, "diagnostic.request").payload["request"])
        user = session.query(DBUser).filter_by(public_id=task.owner_public_id).one()

        def progress(stage):
            with Session(bind=session.get_bind()) as state:
                assert_generation_owner(state)
                if state.get(DBGenerationTask, task_id).status == "cancelled":
                    raise DiagnosticGenerationError("diagnostic_cancelled", "已停止这次诊断准备。")
                append_task_event(state, task_id=task_id, event_type="diagnostic.stage", payload={"stage": stage})
                state.commit()

        try:
            progress("analysis")
            expected = _event(session, task_id, "diagnostic.request").payload
            stage = _saved_stage(session, task, expected)
            if not stage:
                stage = _selected_stage(diagnostic_preflight(session, user=user, course_id=request.course_id,
                    question_count=request.question_count, self_rating=request.self_rating))
                assert_generation_owner(session)
                expected = {**expected, "resolvedStageId": stage}
                append_task_event(session, task_id=task_id, event_type="diagnostic.request", payload=expected)
                session.commit()
            request = replace(request, stage_id=stage)
            course = _readable_course(session, course_id=request.course_id, user=user)
            profile = _latest_profile(session, user.public_id, request.course_id)
            if course.version != expected["courseVersion"] or not profile or profile.id != expected["profileId"]:
                if not profile:
                    raise DiagnosticGenerationError("diagnostic_profile_required", "请先确认学习起点。")
                assert_generation_owner(session)
                append_task_event(session, task_id=task_id, event_type='diagnostic.context_updated', payload={
                    'previous':expected, 'courseVersion':course.version, 'profileId':profile.id})
                append_task_event(session, task_id=task_id, event_type='diagnostic.request', payload={
                    **expected, 'courseVersion':course.version, 'profileId':profile.id})
                session.commit()
            row, _ = generate_diagnostic_blueprint(session, user=user, request=request,
                                                   llm=llm_factory(), progress=progress, task_id=task_id)
            assert_generation_owner(session)
            session.refresh(task, attribute_names=["status"])
            if task.status == "cancelled":
                session.rollback()
                return
            if not execution_token:
                task.status = "completed"
            task.progress = 1.0
            task.completed_at = _now()
            append_task_event(session, task_id=task_id, event_type="diagnostic.completed", payload={"blueprintId": row.id})
            session.commit()
            return {'blueprintId':row.id}
        except Exception as exc:
            session.rollback()
            if execution_token:
                raise
            task = session.get(DBGenerationTask, task_id)
            if task.status == "cancelled":
                return
            task.status = "failed"
            task.completed_at = _now()
            task.failure_code = exc.code if isinstance(exc, DiagnosticGenerationError) else "diagnostic_generation_failed"
            task.failure_reason = str(exc) if isinstance(exc, DiagnosticGenerationError) else "诊断准备暂未完成，可以继续重试。"
            append_task_event(session, task_id=task_id, event_type="diagnostic.failed",
                              payload={"code": task.failure_code, "message": task.failure_reason})
            session.commit()


def recover_interrupted_diagnostics(session):
    tasks = session.query(DBGenerationTask).filter(
        DBGenerationTask.capability == CAPABILITY,
        DBGenerationTask.status.in_(["queued", "running"]),
        DBGenerationTask.automation_state == '',
    ).all()
    for task in tasks:
        task.status = "failed"
        task.completed_at = _now()
        task.failure_code = "diagnostic_interrupted"
        task.failure_reason = "服务重启中断了这次准备，可以重新继续。"
        append_task_event(session, task_id=task.id, event_type="diagnostic.failed",
                          payload={"code": task.failure_code, "message": task.failure_reason})
    session.commit()
    return len(tasks)
