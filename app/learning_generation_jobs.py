"""Durable preparation for inquiry and assessment on the shared job worker."""
from contextvars import ContextVar
from datetime import timedelta
import asyncio
import hashlib
import json

from app.database import DBGenerationTask, DBTaskEvent, DBUser, SessionLocal, _utcnow
from app.m1_repository import append_task_event, create_generation_task

CURRENT_JOB = ContextVar("learning_generation_job", default=None)
CAPABILITIES = {"learning_inquiry.prepare", "learning_inquiry.feedback", "assessment_exam.prepare", "diagnostic.prepare", "path.prepare",
                "multicourse_diagnostic.prepare", "multicourse_path.prepare", "diagnostic.report", "feynman.action"}


def enable_task(task):
    """Opt in only on explicit submission; preserve existing waits and cancellation."""
    from app.generation_dispatch import configuration_signature
    if not task.automation_state and task.status not in {'completed', 'cancelled'}:
        task.automation_state = 'queued'
        task.automation_context = {'phase':'preparing', 'attempts':0, 'configuration':configuration_signature()}
        task.next_attempt_at = _utcnow()


class LearningGenerationError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def assert_generation_owner(db):
    context = CURRENT_JOB.get()
    if not context:
        return
    task = db.get(DBGenerationTask, context["task_id"], populate_existing=True)
    if not task or task.execution_token != context["token"] or task.status == "cancelled":
        raise LearningGenerationError("generation_cancelled", "本次准备已停止。")


def event_payload(db, task_id, kind):
    row = db.query(DBTaskEvent).filter_by(task_id=task_id, event_type=kind).order_by(DBTaskEvent.sequence.desc()).first()
    return dict(row.payload or {}) if row else {}


def task_payload(db, task):
    from app.generation_dispatch import public_automation
    return {"id": task.id, "status": task.status, "automation": public_automation(task),
            "result": event_payload(db, task.id, "learning_generation.completed").get("result")}


def queue_task(db, actor, *, course_id, capability, request, key):
    from app.generation_dispatch import configuration_signature
    task, created = create_generation_task(db, owner_public_id=actor.public_id, course_id=course_id,
        capability=capability, idempotency_key=key, model="deepseek-v4-flash")
    if created:
        append_task_event(db, task_id=task.id, event_type="learning_generation.request", payload={"request": request})
        task.automation_state = "queued"
        task.automation_context = {"phase": "preparing", "attempts": 0, "configuration": configuration_signature()}
        task.next_attempt_at = _utcnow()
    elif event_payload(db, task.id, "learning_generation.request").get("request") != request:
        raise LearningGenerationError("generation_request_conflict", "这次准备已对应另一份要求。")
    db.commit()
    return task_payload(db, task)


def component_cache(db):
    context = CURRENT_JOB.get()
    if not context:
        return {}, lambda key, value: None
    values = {row.payload["key"]: row.payload["value"] for row in db.query(DBTaskEvent).filter_by(
        task_id=context["task_id"], event_type="learning_generation.component").order_by(DBTaskEvent.sequence)}
    def save(key, value):
        assert_generation_owner(db)
        append_task_event(db, task_id=context["task_id"], event_type="learning_generation.component",
                          payload={"key": key, "value": value})
        db.commit()
        values[key] = value
    return values, save


def repair_instruction():
    strategy = (CURRENT_JOB.get() or {}).get('repair_strategy', 'local')
    return {'local':'',
        'replan':'\n前次定向纠正仍有问题。按原始题设与来源重新组织当前未通过部分：逐项列清必需条件和判断依据，重算答案，再形成要求的输出；保留原任务、已完成部分及教学标准。',
        'segmented':'\n当前部分采用逐字段与条目生成。每一部分对照原题、实际学习依据和具体校验意见，先解决阻断，再形成完整教学内容。'}[strategy]


def course_generation_basis(db, *, course_id, owner_public_id, profile_snapshot_id=None, include_profile=True):
    """Read a compact content/profile identity before and after model work."""
    from app.database import DBCourse, DBSourceRef, DBSourceDocument, DBChapter, DBProfileSnapshot, DBKnowledgePoint, DBChapterKnowledgePoint
    from app.profile_onboarding import latest_profile_snapshot_for_course
    course = db.get(DBCourse, course_id, populate_existing=True)
    profile = None
    if include_profile:
        profile = (db.get(DBProfileSnapshot, profile_snapshot_id, populate_existing=True) if profile_snapshot_id else
                   latest_profile_snapshot_for_course(db, owner_public_id, course_id))
    refs = db.query(DBSourceRef).join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id).filter(
        DBSourceDocument.course_id == course_id).populate_existing().order_by(DBSourceRef.id).all()
    documents = db.query(DBSourceDocument.id, DBSourceDocument.content_hash).filter(
        DBSourceDocument.id.in_({ref.source_document_id for ref in refs})).order_by(DBSourceDocument.id).all()
    chapters = db.query(DBChapter.id, DBChapter.title, DBChapter.position, DBChapter.parent_id).filter_by(course_id=course_id).order_by(DBChapter.id).all()
    points = db.query(DBKnowledgePoint, DBChapterKnowledgePoint).join(
        DBChapterKnowledgePoint, DBChapterKnowledgePoint.knowledge_point_id == DBKnowledgePoint.id).join(
        DBChapter, DBChapter.id == DBChapterKnowledgePoint.chapter_id).filter(DBChapter.course_id == course_id).populate_existing().order_by(
        DBChapterKnowledgePoint.id).all()
    value = {'course': [course.version, course.manifest_version] if course else None,
             'profile': [profile.id, profile.snapshot] if profile else None,
             'sources': [(ref.id, ref.content_hash, ref.quote, ref.char_start, ref.char_end) for ref in refs],
             'documents':[list(row) for row in documents], 'chapters':[list(row) for row in chapters],
             'knowledge_points':[(point.id, point.code, point.title, point.version, point.level, point.status,
                 point.prerequisites, link.chapter_id, link.relation_type) for point,link in points]}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def assert_course_generation_basis(db, expected, **scope):
    from sqlalchemy.orm import Session
    bind = db.get_bind()
    url = getattr(bind, 'url', None)
    if url is not None and url.get_backend_name() == 'sqlite' and url.database in {None, '', ':memory:'}:
        # An in-memory SQLite pool can share the caller's connection. Closing a
        # second Session would roll back unpublished questions on that connection.
        with db.no_autoflush:
            actual = course_generation_basis(db, **scope)
    else:
        with Session(bind=bind) as current:
            actual = course_generation_basis(current, **scope)
    if actual != expected:
        raise LearningGenerationError('learning_generation.source_context_changed', '课程资料或学习依据已更新，正在按当前内容继续准备。')


async def generate_learning_json(backend, *, system, request, role, completed, save, validate=None):
    """Retain invalid responses for correction; cache only validated JSON."""
    from app.resource_generation_parts import generate_structured_parts, generation_parts_key
    from llm_client import parse_json_object, ModelOutputLimitError, StructuredModelContentError
    encoded = json.dumps(request, ensure_ascii=False, sort_keys=True)
    key = 'learning-json:' + hashlib.sha256((system + encoded + role).encode()).hexdigest()
    state = dict(completed.get(key) or {})
    if state.get('valid'):
        return state['output']
    prompt = system + repair_instruction()
    packet = {**request, **({'previous_invalid_part': state['invalid']} if state.get('invalid') else {})}
    user = json.dumps(packet, ensure_ascii=False, sort_keys=True)
    parts_key = generation_parts_key(prompt, user, backend) + ':started'
    segmented = (CURRENT_JOB.get() or {}).get('repair_strategy') == 'segmented' or parts_key in completed
    raw = ''
    try:
        if not segmented:
            try:
                raw = await backend.generate(prompt, user, role=role)
            except ModelOutputLimitError as exc:
                save(key + ':overflow', {'error':str(exc), 'type':type(exc).__name__})
                segmented = True
        if segmented:
            output = await generate_structured_parts(backend, resource_type=role, system=prompt, user=user,
                                                     completed=completed, save=save)
            raw = json.dumps(output, ensure_ascii=False)
        else:
            output = parse_json_object(raw)
        if validate:
            validate(output)
    except (ValueError, KeyError, TypeError, StructuredModelContentError) as exc:
        value = {'invalid': {'raw':raw, 'error':str(exc)}}
        save(key + ':invalid:' + hashlib.sha256(raw.encode()).hexdigest(), value)
        save(key, value)
        error = LearningGenerationError('learning_generation.output_invalid', str(exc))
        error.raw_output = raw
        raise error from exc
    save(key, {'valid':True, 'output':output})
    return output


def finish_attempt(db, task, error=None):
    from app.generation_dispatch import classify_failure, configuration_signature
    info = dict(task.automation_context or {})
    if error is None:
        task.status = task.automation_state = "completed"
        task.progress = 1
        task.completed_at = _utcnow()
        info["phase"] = "completed"
    else:
        code = getattr(error, "code", type(error).__name__)
        category = classify_failure(code, str(error))
        cause, seen = error.__cause__ or error.__context__, {id(error)}
        details = str(error)
        while cause is not None and id(cause) not in seen:
            seen.add(id(cause))
            status = getattr(getattr(cause, 'response', None), 'status_code', None)
            message = f'HTTP {status} {cause}' if status else str(cause)
            kind = classify_failure(getattr(cause, 'code', type(cause).__name__), message)
            details += '\n' + message
            if kind in {'configuration', 'transport', 'content'}:
                category = kind
            if category == 'configuration':
                break
            cause = cause.__cause__ or cause.__context__
        if isinstance(error, ValueError) and not getattr(error, 'code', None) and category == "application":
            category = "content"
        signature = hashlib.sha256((code + str(error)).encode()).hexdigest()
        same = info.get("same_failure", 0) + 1 if info.get("failure_signature") == signature else 0
        info.update(failure_code=code, failure_signature=signature, same_failure=same,
                    last_error=details, configuration=configuration_signature())
        task.failure_code, task.failure_reason = code, str(error)
        task.status = "failed"
        if category == "configuration":
            task.automation_state = "waiting_configuration"
            info["phase"] = "service_wait"
        elif category in {"transport", "review", "content", "source"}:
            task.automation_state = "retry_wait"
            task.next_attempt_at = _utcnow() + timedelta(seconds=min(300, 5 * 2**min(same, 6)))
            info["phase"] = "repairing" if category == "content" else "checking"
            if category == 'content':
                cache, _ = component_cache(db)
                bodies = {key: {name:value[name] for name in ('candidate','output','invalid') if name in value}
                          for key,value in cache.items() if isinstance(value,dict) and not ':invalid:' in key}
                candidate_hash = hashlib.sha256(json.dumps(bodies, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                stagnant = info.get('stagnant_attempts', 0) + 1 if same else 0
                strategies = ['local', 'replan', 'segmented']
                previous_strategy = info.get('repair_strategy', 'local')
                info.update(repair_strategy=strategies[min(stagnant, len(strategies)-1)],
                            stagnant_attempts=stagnant, candidate_hash=candidate_hash)
                # No total attempt limit: stop only an exhausted strategy that
                # returned the same body with the same unresolved defect.
                if previous_strategy == 'segmented' and same and candidate_hash == (task.automation_context or {}).get('candidate_hash'):
                    task.automation_state = 'needs_attention'
                    info['blocked_reason'] = '重新规划和分段生成后，同一内容的同一问题仍未改变。'
        else:
            task.automation_state = "needs_attention"
        append_task_event(db, task_id=task.id, event_type="learning_generation.failed",
            payload={"code": code, "message": details, "category": category, "action": task.automation_state})
    task.automation_context = info
    task.execution_token = None
    task.lease_expires_at = None
    db.commit()


def run_claimed_learning_job(task_id, token, *, session_factory=SessionLocal):
    from app.generation_dispatch import _owned
    with session_factory() as db:
        task = _owned(db, task_id, token)
        if task is None:
            return
        actor = db.query(DBUser).filter_by(public_id=task.owner_public_id, is_active=True).one()
        request = event_payload(db, task.id, "learning_generation.request").get("request", {})
        task.status = "running"
        task.started_at = task.started_at or _utcnow()
        task.automation_context = {**(task.automation_context or {}),
                                   "attempts": (task.automation_context or {}).get("attempts", 0)+1}
        db.commit()
        context_token = CURRENT_JOB.set({"task_id": task.id, "token": token,
                                       'session_factory': session_factory,
                                       'repair_strategy':(task.automation_context or {}).get('repair_strategy', 'local')})
        try:
            if task.capability == "learning_inquiry.prepare":
                from app.learning_inquiry import prepare_inquiry
                result = asyncio.run(prepare_inquiry(actor, request["attempt_id"]))
            elif task.capability == "learning_inquiry.feedback":
                from app.learning_inquiry import answer_inquiry
                result = asyncio.run(answer_inquiry(actor, request["attempt_id"], request["response"]))
            elif task.capability == 'diagnostic.prepare':
                from app.diagnostic_tasks import execute_diagnostic_task
                from app.diagnostic_api import build_diagnostic_llm
                result = execute_diagnostic_task(task.id, build_diagnostic_llm,
                    session_factory=session_factory, execution_token=token)
            elif task.capability == 'path.prepare':
                from app.path_tasks import execute_path_task
                from app.path_draft import _build_path_model
                result = execute_path_task(task.id, _build_path_model,
                    session_factory=session_factory, execution_token=token)
            elif task.capability in {'multicourse_diagnostic.prepare', 'multicourse_path.prepare'}:
                from app.multicourse_diagnostic import execute_multicourse_task
                result = execute_multicourse_task(db, user=actor, capability=task.capability, request=request)
            elif task.capability == 'diagnostic.report':
                from app.diagnostic_api import build_diagnostic_llm
                from app.diagnostic_report import generate_diagnostic_report
                report, _ = generate_diagnostic_report(db, user=actor,
                    session_id=request['session_id'], idempotency_key=task.idempotency_key,
                    llm=build_diagnostic_llm())
                result = {'report_id': report.id, 'session_id': report.session_id}
            elif task.capability == 'feynman.action':
                from app.feynman import apply_action
                result, _ = apply_action(db, actor=actor, **request)
            else:
                from app.m5_api import _create_configured_intelligent_exam
                from app.m5_exam_core import IntelligentExamConfigInput
                result = asyncio.run(_create_configured_intelligent_exam(
                    config=IntelligentExamConfigInput.model_validate(request), current_user=actor))
            assert_generation_owner(db)
            append_task_event(db, task_id=task.id, event_type="learning_generation.completed", payload={"result": result})
            finish_attempt(db, task)
        except Exception as exc:
            db.rollback()
            task = _owned(db, task_id, token)
            if task:
                finish_attempt(db, task, exc)
        finally:
            CURRENT_JOB.reset(context_token)
