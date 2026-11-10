"""Background path preparation on the existing task/event and plan lifecycle."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import DBCourse, DBGenerationTask, DBTaskEvent, DBUser
from app.m1_repository import append_task_event, create_generation_task
from app.path_draft import (
    PathDraftError, PATH_PLANNING_REVISION, PATH_REVIEW_INSTRUCTION, PATH_OVERVIEW_INSTRUCTION, PATH_SEQUENCE_INSTRUCTION, _authorize, _latest_profile,
    _course_facts, _path_learning_snapshot, _path_model_context,
    generate_textbook_path_draft,
)


CAPABILITY = "path.prepare"


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _event(session, task_id, kind):
    return session.query(DBTaskEvent).filter_by(task_id=task_id, event_type=kind).order_by(
        DBTaskEvent.sequence.desc()).first()


def _learning_basis(session, user, request):
    profile = _latest_profile(session, owner_public_id=user.public_id, course_id=request['course_id'],
                              profile_snapshot_id=request.get('profile_snapshot_id'))
    if profile is None:
        raise PathDraftError("path_draft_profile_missing", "请先确认学习起点，再安排学习路径。")
    snapshot = _path_learning_snapshot(session, user=user, course_id=request['course_id'], profile=profile,
                                       use_current=not bool(request.get('profile_snapshot_id')))
    from app.profile_adaptation import confirmed_study_minutes
    return {'profile_snapshot_id': profile.id, 'snapshot': snapshot,
            'time_budget_minutes': request.get('time_budget_minutes') or confirmed_study_minutes(snapshot) or 90}


def _context(session, user, request, learning_basis=None):
    course = session.get(DBCourse, request["course_id"])
    if course is None:
        raise PathDraftError("course_not_found", "课程不存在。")
    _authorize(session, current_user=user, course=course)
    learning_basis = learning_basis or _learning_basis(session, user, request)
    profile = _latest_profile(session, owner_public_id=user.public_id, course_id=course.id,
                              profile_snapshot_id=learning_basis['profile_snapshot_id'])
    if profile is None:
        raise PathDraftError("path_draft_profile_missing", "请先确认学习起点，再安排学习路径。")
    snapshot = learning_basis['snapshot']
    minutes = learning_basis['time_budget_minutes']
    context = _path_model_context(_course_facts(session, course_id=course.id), course=course,
                                 profile=profile, snapshot=snapshot, time_budget_minutes=minutes)
    return hashlib.sha256(json.dumps({"context": context, "revision": PATH_PLANNING_REVISION,
        "path_overview": PATH_OVERVIEW_INSTRUCTION if request["full_coverage"] else None,
        "path_sequence": PATH_SEQUENCE_INSTRUCTION if request["full_coverage"] else None,
        "teaching_review": hashlib.sha256(PATH_REVIEW_INSTRUCTION.encode()).hexdigest(),
        "full_coverage": request["full_coverage"]}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def task_payload(session, task):
    from app.generation_dispatch import public_automation
    automation = public_automation(task)
    event = _event(session, task.id, "path.progress")
    progress = dict(event.payload) if event else {"stage": "analysis", "completed": 0, "total": 0}
    request = _event(session, task.id, "path.request")
    result = _event(session, task.id, "path.completed")
    return {"id": task.id, "status": task.status, "courseId": task.course_id,
            "progress": progress, "request": request.payload["request"] if request else {},
            "result": result.payload if result else None,
            "automation": automation,
            "message": automation['message'] if automation['enabled'] else task.failure_reason if task.status == "failed" else ""}


def get_path_task(session, *, task_id, user):
    task = session.get(DBGenerationTask, task_id)
    if task is None or task.capability != CAPABILITY or task.owner_public_id != user.public_id:
        raise PathDraftError("path_task_unknown", "没有找到这次学习路径安排。")
    course = session.get(DBCourse, task.course_id)
    if course is None:
        raise PathDraftError("course_not_found", "课程不存在。")
    _authorize(session, current_user=user, course=course)
    return task_payload(session, task)


def find_path_task(session, *, user, course_id, report_id=None):
    course = session.get(DBCourse, course_id)
    if course is None:
        raise PathDraftError("course_not_found", "课程不存在。")
    _authorize(session, current_user=user, course=course)
    for task in session.query(DBGenerationTask).filter_by(
        owner_public_id=user.public_id, course_id=course_id, capability=CAPABILITY,
    ).order_by(DBGenerationTask.created_at.desc(), DBGenerationTask.id.desc()):
        event = _event(session, task.id, "path.request")
        if event and (report_id is None or event.payload["request"].get("report_id") == report_id):
            return task_payload(session, task)
    return None


def queue_path_task(session, *, user, course_id, time_budget_minutes=None,
                    full_coverage=False, profile_snapshot_id=None, report_id=None,
                    idempotency_key=None):
    request = {"course_id": course_id, "time_budget_minutes": time_budget_minutes,
               "full_coverage": full_coverage, "profile_snapshot_id": profile_snapshot_id,
               "report_id": report_id, "idempotency_key": idempotency_key}
    learning_basis = _learning_basis(session, user, request)
    context_hash = _context(session, user, request, learning_basis)
    # One shared key for the same teaching inputs, including two tabs with
    # different transport request IDs. Actual model batch reuse remains unchanged.
    key = "path:" + hashlib.sha256(json.dumps({"context": context_hash,
        "course": course_id, "report": report_id}, sort_keys=True).encode()).hexdigest()
    active = session.query(DBGenerationTask).filter_by(owner_public_id=user.public_id,
        course_id=course_id, capability=CAPABILITY).filter(
            DBGenerationTask.status.in_(["queued", "running"])).first()
    if active and active.idempotency_key != key:
        raise PathDraftError("path_task_in_progress", "这门课程正在安排学习路径，完成后可按新的学习要求调整。")
    try:
        task, created = create_generation_task(session, owner_public_id=user.public_id,
            capability=CAPABILITY, idempotency_key=key, course_id=course_id, model="deepseek-v4-flash")
        if created:
            append_task_event(session, task_id=task.id, event_type="path.request",
                              payload={"request": request, "contextHash": context_hash,
                                       "learningBasis": learning_basis})
        elif task.status in {"failed", "cancelled"} and not task.automation_state:
            task.status = "queued"
            task.failure_code = task.failure_reason = ""
            task.completed_at = None
            append_task_event(session, task_id=task.id, event_type="path.retry", payload={})
        from app.learning_generation_jobs import enable_task
        enable_task(task)
        session.commit()
    except IntegrityError:
        session.rollback()
        task = session.query(DBGenerationTask).filter_by(owner_public_id=user.public_id,
                                                        idempotency_key=key).one_or_none()
        if task is None:
            raise
    return task_payload(session, task)


def execute_path_task(task_id, llm_factory, *, session_factory=None, execution_token=None):
    if session_factory is None:
        from app.database import SessionLocal
        session_factory = SessionLocal
    with session_factory() as session:
        from app.learning_generation_jobs import assert_generation_owner
        changed = execution_token or session.query(DBGenerationTask).filter_by(id=task_id, capability=CAPABILITY,
            status="queued", automation_state='').update({"status": "running", "started_at": _now()}, synchronize_session=False)
        session.commit()
        if not changed:
            return
        task = session.get(DBGenerationTask, task_id)

        def progress(value):
            with Session(bind=session.get_bind()) as state:
                assert_generation_owner(state)
                current = state.get(DBGenerationTask, task_id)
                if current.status == "cancelled":
                    raise PathDraftError("path_cancelled", "已停止这次学习安排。")
                current.progress = value["completed"] / value["total"] if value["total"] else 0
                append_task_event(state, task_id=task_id, event_type="path.progress", payload=value)
                state.commit()

        try:
            expected = _event(session, task_id, "path.request").payload
            request = expected["request"]
            user = session.query(DBUser).filter_by(public_id=task.owner_public_id).one()
            learning_basis = expected.get('learningBasis') or _learning_basis(session, user, request)
            current_hash = _context(session, user, request, learning_basis)
            if current_hash != expected["contextHash"] or not expected.get('learningBasis'):
                assert_generation_owner(session)
                append_task_event(session, task_id=task_id, event_type='path.context_updated', payload={
                    'previous':expected, 'contextHash':current_hash})
                append_task_event(session, task_id=task_id, event_type='path.request', payload={
                    'request':request, 'contextHash':current_hash, 'learningBasis':learning_basis})
                session.commit()
            plan, changed = generate_textbook_path_draft(session, current_user=user,
                course_id=request["course_id"], time_budget_minutes=learning_basis['time_budget_minutes'],
                profile_snapshot_id=learning_basis['profile_snapshot_id'], learning_snapshot=learning_basis['snapshot'],
                full_coverage=request["full_coverage"],
                idempotency_key=request["idempotency_key"], llm=llm_factory(), progress=progress)
            assert_generation_owner(session)
            session.refresh(task, attribute_names=["status"])
            if task.status == "cancelled":
                session.rollback()
                return
            if not execution_token:
                task.status = "completed"
            task.progress = 1.0
            task.completed_at = _now()
            append_task_event(session, task_id=task_id, event_type="path.completed",
                              payload={"planId": plan.id, "changed": changed})
            session.commit()
            return {'planId':plan.id, 'changed':changed}
        except Exception as exc:
            session.rollback()
            if execution_token:
                raise
            task = session.get(DBGenerationTask, task_id)
            if task.status == "cancelled":
                return
            task.status = "failed"
            task.completed_at = _now()
            task.failure_code = exc.code if isinstance(exc, PathDraftError) else "path_generation_failed"
            task.failure_reason = str(exc) if isinstance(exc, PathDraftError) else "学习安排暂未完成，已保存的内容会在重试时继续使用。"
            append_task_event(session, task_id=task_id, event_type="path.failed",
                              payload={"code": task.failure_code, "message": task.failure_reason})
            session.commit()


def recover_interrupted_paths(session):
    tasks = session.query(DBGenerationTask).filter(DBGenerationTask.capability == CAPABILITY,
        DBGenerationTask.status.in_(["queued", "running"]), DBGenerationTask.automation_state == '').all()
    for task in tasks:
        task.status = "failed"
        task.completed_at = _now()
        task.failure_code = "path_interrupted"
        task.failure_reason = "这次学习安排被服务重启中断。重试会继续使用已核对的内容。"
        append_task_event(session, task_id=task.id, event_type="path.failed",
                          payload={"code": task.failure_code, "message": task.failure_reason})
    session.commit()
    return len(tasks)
