"""Durable execution of explicitly submitted resource jobs using the existing DB.

The browser only submits and observes. A lease identifies the sole writer, and
completed parts/versions/reviews remain in the existing task records on restart.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import and_, case, or_

from app.database import DBGenerationTask, DBTaskEvent, DBUser, SessionLocal, _utcnow
from config import CONFIG

log = logging.getLogger(__name__)
LEASE_SECONDS = 120
ACTIVE_STATES = {"queued", "running", "retry_wait"}
LEARNING_FEEDBACK_CAPABILITIES = {
    "feynman.action", "learning_inquiry.prepare", "learning_inquiry.feedback", "diagnostic.report",
}


def configuration_signature() -> str:
    # Only a digest is persisted. Changing a loaded configuration is a recovery
    # signal; elapsed time alone never retries an invalid credential or balance.
    values = [getattr(CONFIG, name, "") for name in (
        "llm_provider", "llm_endpoint", "llm_api_key", "llm_model",
    )]
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


def public_automation(task: DBGenerationTask) -> dict:
    state = task.automation_state or ""
    if task.status == "cancelled" and state:
        state = "cancelled"
    info = task.automation_context or {}
    subject = ('试卷' if task.capability == 'assessment_exam.prepare' else '追问' if task.capability == 'learning_inquiry.prepare'
               else '讲解与练习' if task.capability == 'learning_inquiry.feedback' else '诊断题目' if task.capability == 'diagnostic.prepare'
               else '诊断报告' if task.capability == 'diagnostic.report'
               else '复述反馈' if task.capability == 'feynman.action'
               else '学习路径' if task.capability == 'path.prepare' else '学习资源')
    return {
        "enabled": bool(state), "state": state,
        "phase": info.get("phase", "preparing"),
        "attempts": info.get("attempts", 0),
        "next_attempt_at": task.next_attempt_at.isoformat() if task.next_attempt_at else None,
        "message": {
            "queued": "正在排队准备。", "running": f"正在准备{subject}。",
            "retry_wait": "正在核对并调整内容。" if info.get('phase') == 'repairing' else "服务暂时繁忙，稍后自动继续。",
            "waiting_configuration": "模型服务暂不可用，管理员恢复服务后会继续。",
            "needs_attention": "生成遇到系统问题，已保留当前进度。",
            "completed": f"{subject}已就绪。", "cancelled": "本次生成已取消。",
        }.get(state, ""),
    }


def submit_resource_job(db, actor, task_id: str) -> dict:
    from app.resource_bundles import _generation_task, generation_job_payload, prepare_generation_dependencies
    task = _generation_task(db, actor, task_id)
    if task.status in {"completed", "cancelled"} or task.automation_state in ACTIVE_STATES:
        return generation_job_payload(db, actor, task_id)
    # Repeated execute calls, refreshes and queued historical requests must not
    # release a service/account block or an unresolved application defect.
    if task.automation_state in {"waiting_configuration", "needs_attention"}:
        return generation_job_payload(db, actor, task_id)
    db.query(DBGenerationTask).filter(DBGenerationTask.id == task_id,
        DBGenerationTask.automation_state.in_(["", "completed"]),
        DBGenerationTask.status.notin_(["completed", "cancelled"])).update({
            DBGenerationTask.automation_state: "queued", DBGenerationTask.execution_token: None,
            DBGenerationTask.lease_expires_at: None, DBGenerationTask.next_attempt_at: _utcnow(),
            DBGenerationTask.automation_context: {"phase": "preparing", "attempts": 0,
                                                  "configuration": configuration_signature()},
        }, synchronize_session=False)
    db.flush()
    db.refresh(task)
    if task.automation_state == "queued":
        prepare_generation_dependencies(db, task)
    return generation_job_payload(db, actor, task_id)


def classify_failure(code: str, message: str) -> str:
    value = f"{code} {message}".lower()
    if code in {'feynman_model_required', 'feynman_model_unavailable'}:
        return 'configuration'
    if code == 'diagnostic_explanation_incomplete':
        return 'content'
    # Teaching findings contain numbers (e.g. 500 samples) and version hashes.
    # Only an explicit HTTP/status marker is a transport status.
    if any(x in code for x in ('review_rejected', '_mismatch', 'output_limit')):
        return 'content'
    status = re.search(r'(?:http(?:\s*error)?|status(?:[_ ]code)?)\s*[:=]?\s*(\d{3})\b', value)
    if not status:
        status = re.search(r'\b(401|402|403|429|500|502|503|504)\s+(?:unauthorized|payment required|forbidden|too many requests|internal server error|bad gateway|service unavailable|gateway timeout)\b', value)
    status_code = int(status.group(1)) if status else None
    if status_code in {401, 402, 403} or any(x in value for x in (
        "insufficient balance", "insufficient_quota", "invalid_api_key", "unauthorized",
        "余额不足", "额度不足", "model_not_configured", "provider_unavailable",
        "service_auth_failed",
    )):
        return "configuration"
    if any(x in value for x in ("timeout", "timed out", "connection", "network", "ssl", "service_unavailable", "超时", "连接", "限流")) or status_code == 429 or (status_code is not None and status_code >= 500):
        return "transport"
    if any(x in code for x in ("review_rejected", "_invalid", "_mismatch", "output_limit")):
        return "content"
    if "reviewer_failed" in code:
        return "review"
    if "dependency_failed" in code:
        return "dependency"
    if "source" in code.removeprefix('resource_generation.'):
        return "source"
    return "application"


def _failure_details(db, task):
    from app.resource_bundles import _task_steps
    _, latest = _task_steps(db, task.id)
    failures = [{"type": step.tool_name, "code": step.error_code, "message": step.error_message}
                for step in latest.values() if step.status == "failed"]
    # Review failures keep every generated candidate succeeded. Store the real
    # transport cause on the event, so account failures never become blind polls.
    boundary = db.query(DBTaskEvent).filter_by(task_id=task.id,
        event_type="resource_generation.auto_recovery").order_by(DBTaskEvent.sequence.desc()).first()
    events = db.query(DBTaskEvent).filter(DBTaskEvent.task_id == task.id,
        DBTaskEvent.sequence > (boundary.sequence if boundary else 0),
        DBTaskEvent.event_type.in_(["review_gate.failed", "run.failed"])).order_by(DBTaskEvent.sequence.desc()).all()
    event = next((event for event in events if (event.payload or {}).get("error_code")), None)
    if event:
        payload = event.payload or {}
        detail = {"code": payload.get("error_code", "resource_generation.reviewer_failed"),
                  "message": payload.get("error_message") or payload.get("summary", "")}
        if not any(item['code'] == detail['code'] and item['message'] == detail['message'] for item in failures):
            failures.append(detail)
    return failures or [{"code": task.failure_code or "resource_generation.incomplete",
                         "message": task.failure_reason or "生成尚未完成。"}]


def _owned(db, task_id, token):
    task = db.get(DBGenerationTask, task_id, populate_existing=True)
    return task if task and task.execution_token == token and task.status != "cancelled" else None


def claim_resource_job(db, *, now=None) -> tuple[str, str] | None:
    now = now or _utcnow()
    due = and_(DBGenerationTask.automation_state.in_(["queued", "retry_wait"]),
               or_(DBGenerationTask.next_attempt_at.is_(None), DBGenerationTask.next_attempt_at <= now))
    expired = and_(DBGenerationTask.automation_state == "running", DBGenerationTask.lease_expires_at <= now)
    eligible = and_(DBGenerationTask.status.notin_(["completed", "cancelled"]), or_(due, expired))
    # Finish the learner's current interaction before starting another long
    # resource bundle. Existing leases are untouched; each queue remains FIFO.
    priority = case((DBGenerationTask.capability.in_(LEARNING_FEEDBACK_CAPABILITIES), 0), else_=1)
    candidate = db.query(DBGenerationTask.id).filter(eligible).order_by(
        priority, DBGenerationTask.created_at, DBGenerationTask.id).first()
    if not candidate:
        return None
    token = uuid4().hex
    count = db.query(DBGenerationTask).filter(DBGenerationTask.id == candidate.id, eligible).update({
        DBGenerationTask.automation_state: "running", DBGenerationTask.execution_token: token,
        DBGenerationTask.lease_expires_at: now + timedelta(seconds=LEASE_SECONDS),
    }, synchronize_session=False)
    db.commit()
    return (candidate.id, token) if count else None


def renew_lease(db, task_id, token):
    count = db.query(DBGenerationTask).filter(
        DBGenerationTask.id == task_id, DBGenerationTask.execution_token == token,
        DBGenerationTask.automation_state == "running", DBGenerationTask.status != "cancelled",
    ).update({DBGenerationTask.lease_expires_at: _utcnow() + timedelta(seconds=LEASE_SECONDS)}, synchronize_session=False)
    db.commit()
    return bool(count)


def _prepare_attempt(db, actor, task):
    from app.resource_bundles import (
        _task_steps, _review_gate_status, recover_generation_job,
    )
    _, latest = _task_steps(db, task.id)
    if any(step.status in {"running", "failed"} for step in latest.values()) or (
        latest and all(step.status == "succeeded" for step in latest.values())
        and _review_gate_status(db, task.id) == "failed"
    ):
        recover_generation_job(db, actor, task.id)
    info = dict(task.automation_context or {})
    info["attempts"] = info.get("attempts", 0) + 1
    info["configuration"] = configuration_signature()
    task.automation_context = info
    db.commit()


def _automatic_revision_key(db, task, kind, request):
    """Bind a repair to saved work and its inputs, across operator recovery."""
    from app.resource_bundles import _task_steps
    _, latest = _task_steps(db, task.id)
    basis = {'steps': [(seq, step.id, step.output_artifact_version_id)
                       for seq, step in sorted(latest.items())], 'request': request}
    digest = hashlib.sha256(json.dumps(basis, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return f'auto-{kind}-{task.id}-{digest}'


def _finish_attempt(db, actor, task, *, failure=None):
    from app.m1_repository import append_task_event
    from app.resource_bundles import (_task_steps, revise_generation_job, GENERATION_RESOURCE_TYPES,
        _generation_manifest, _generation_source_snapshots)
    info = dict(task.automation_context or {})
    if task.status == "completed":
        task.automation_state = "completed"
        info["phase"] = "completed"
    else:
        failures = failure or _failure_details(db, task)
        categories = {classify_failure(item["code"], item["message"]) for item in failures}
        fingerprint = hashlib.sha256(json.dumps(failures, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        repeated = info.get("repeated_failure", 0) + 1 if fingerprint == info.get("failure_hash") else 0
        info.update(failure_hash=fingerprint, repeated_failure=repeated, last_failures=failures)
        if "configuration" in categories:
            task.automation_state = "waiting_configuration"
            info["phase"] = "service_wait"
        elif categories <= {"transport", "review"}:
            # Individual model requests already have bounded retries. Schedule
            # a new attempt with backoff rather than nesting another retry loop.
            task.automation_state = "retry_wait"
            delay = min(300, 10 * 2 ** min(repeated, 5))
            task.next_attempt_at = _utcnow() + timedelta(seconds=delay)
            info["phase"] = "checking" if "review" in categories else "preparing"
        elif "source" in categories and categories <= {"source", "content", "dependency", "transport", "review"}:
            manifest = _generation_manifest(db, task.id)
            changed = {}
            unavailable = None
            for item in manifest["items"]:
                try:
                    _generation_source_snapshots(db, task=task, manifest=manifest, item=item, resource_type=item["type"])
                except Exception as exc:
                    if getattr(exc, "code", "") == "resource_generation.source_snapshot_changed":
                        changed[item["type"]] = item["source_ref_ids"]
                    else:
                        unavailable = str(exc)
            if changed and not unavailable:
                # New versions still refer to the user's original sources. All
                # affected resources and dependency bindings are regenerated.
                revise_generation_job(db, actor, task.id, feedback="课程来源已更新，按当前原文重新核对并生成受影响内容。",
                    resource_types=list(changed), source_ref_ids_by_type=changed,
                    idempotency_key=_automatic_revision_key(db, task, 'source', changed), preserve_learning_basis=True)
                task.automation_state = "queued"
                task.next_attempt_at = _utcnow()
                info["phase"] = "repairing"
            else:
                task.automation_state = "needs_attention"
                info.update(phase="blocked", blocked_reason=unavailable or "课程来源尚不可用。")
        elif categories & {"content", "dependency"} and categories <= {"content", "dependency", "transport", "review"}:
            _, latest = _task_steps(db, task.id)
            # Measure progress against the problem set and saved content, not
            # model wording (which changes on every otherwise identical retry).
            problems = sorted((step.tool_name, step.error_code) for step in latest.values()
                              if step.status == "failed" and classify_failure(step.error_code, step.error_message) in {'content', 'dependency'})
            review_event = db.query(DBTaskEvent).filter(DBTaskEvent.task_id == task.id,
                DBTaskEvent.event_type.in_(["resource_generation.review_result", "resource_generation.review_adjudicated"])
                ).order_by(DBTaskEvent.sequence.desc()).first()
            findings = (((review_event.payload or {}).get("review") or {}).get("findings") or []) if review_event else []
            # A different defect at a different location is progress even when
            # the number of findings stays the same. Wording alone is not.
            locations = sorted((str(f.get('resourceType') or f.get('resource_type') or ''),
                                str(f.get('location') or ''), str(f.get('severity') or ''))
                               for f in findings if isinstance(f, dict))
            problem_key = hashlib.sha256(json.dumps([problems, locations], ensure_ascii=False).encode()).hexdigest()
            count = len(findings or problems)
            progress = count < info.get("problem_count", count) or problem_key != info.get("problem_key")
            stagnant = 0 if progress else info.get("stagnant_attempts", 0) + 1
            strategies = ["local", "independent_solution", "replan", "segmented"]
            stage = min(stagnant, len(strategies)-1)
            info.update(problem_key=problem_key, problem_count=count, stagnant_attempts=stagnant,
                        repair_strategy=strategies[stage])
            from app.database import DBArtifactVersion
            bodies = [db.get(DBArtifactVersion, s.output_artifact_version_id).content_hash
                      for s in latest.values() if s.output_artifact_version_id]
            candidate_hash = hashlib.sha256(json.dumps(bodies).encode()).hexdigest()
            unchanged = candidate_hash == info.get('candidate_hash')
            previous_strategy = (task.automation_context or {}).get('repair_strategy')
            info['candidate_hash'] = candidate_hash
            if not progress and unchanged and previous_strategy == 'segmented':
                task.automation_state = "needs_attention"
                info.update(phase="blocked", blocked_reason="局部修订、独立求解、重新规划与拆分生成后，同一问题仍未解决。")
                task.automation_context = info
                task.execution_token = None
                task.lease_expires_at = None
                append_task_event(db, task_id=task.id, event_type="resource_generation.auto_recovery",
                    payload={"action": "needs_attention", "reason": info["blocked_reason"], "failures": failures})
                db.commit()
                return
            rejected = [GENERATION_RESOURCE_TYPES[seq - 1] for seq, step in latest.items()
                        if step.status == "failed" and step.output_artifact_version_id]
            if rejected:
                strategy = ("核对原题、来源与实际计算，只修具体错误并同步答案和解析。" if stage == 0 else
                            "上次修订未解决问题。重新独立求解相关任务，逐项对照原始数据与适用条件，再重写受影响部分；保留无关已通过内容。")
                feedback = strategy + "\n" + json.dumps(failures, ensure_ascii=False)
                adjudication = db.query(DBTaskEvent).filter_by(task_id=task.id,
                    event_type="resource_generation.review_adjudicated").order_by(DBTaskEvent.sequence.desc()).first()
                decisions = ((adjudication.payload.get("review") or {}).get("review_decisions") if adjudication else None)
                revise_generation_job(db, actor, task.id, feedback=feedback, resource_types=rejected,
                                      idempotency_key=_automatic_revision_key(db, task, 'repair', {
                                          'feedback': feedback, 'types': rejected, 'decisions': decisions,
                                          'preserve_plan': stage < 2}),
                                      preserve_plan=stage < 2, preserve_learning_basis=True,
                                      review_decisions=decisions)
            task.automation_state = "queued"
            task.next_attempt_at = _utcnow()
            info["phase"] = "repairing"
        else:
            # A missing capability or an unknown software exception needs a code
            # repair, not repeated paid calls with identical input.
            task.automation_state = "needs_attention"
            info["phase"] = "blocked"
        append_task_event(db, task_id=task.id, event_type="resource_generation.auto_recovery",
                          payload={"action": task.automation_state, "categories": sorted(categories),
                                   "attempt": info.get("attempts"), "failures": failures,
                                   "repeated_failure": repeated, "next_attempt_at": task.next_attempt_at.isoformat() if task.next_attempt_at else None})
    task.automation_context = info
    task.execution_token = None
    task.lease_expires_at = None
    db.commit()


def run_claimed_resource_job(task_id, token, *, session_factory=SessionLocal):
    from app.resource_bundles import execute_generation_job
    with session_factory() as db:
        task = _owned(db, task_id, token)
        if not task:
            return
        from app.learning_generation_jobs import CAPABILITIES, run_claimed_learning_job
        if task.capability in CAPABILITIES:
            db.close()
            return run_claimed_learning_job(task_id, token, session_factory=session_factory)
        actor = db.query(DBUser).filter_by(public_id=task.owner_public_id, is_active=True).first()
        if not actor:
            task.automation_state = "needs_attention"
            task.execution_token = None
            task.lease_expires_at = None
            db.commit()
            return
        try:
            _prepare_attempt(db, actor, task)
            execute_generation_job(db, actor, task_id, execution_token=token)
            db.commit()
            task = _owned(db, task_id, token)
            if task:
                _finish_attempt(db, actor, task)
        except Exception as exc:
            db.rollback()
            task = _owned(db, task_id, token)
            if task:
                _finish_attempt(db, actor, task, failure=[{
                    "code": getattr(exc, "code", type(exc).__name__), "message": str(exc),
                }])
            log.exception("Resource generation attempt failed: %s", task_id)


def resume_changed_configuration(db):
    signature = configuration_signature()
    for task in db.query(DBGenerationTask).filter_by(automation_state="waiting_configuration"):
        if task.status not in {"cancelled", "completed"} and (task.automation_context or {}).get("configuration") != signature:
            task.automation_state = "queued"
            task.next_attempt_at = _utcnow()
    db.commit()


def confirm_service_restored(db):
    """Explicit administrator signal, including a balance top-up with the same key."""
    for task in db.query(DBGenerationTask).filter_by(automation_state="waiting_configuration"):
        if task.status not in {"cancelled", "completed"}:
            task.automation_state = "queued"
            task.next_attempt_at = _utcnow()


class GenerationDispatcher:
    def __init__(self, session_factory=SessionLocal, concurrency=2):
        self.session_factory = session_factory
        self.concurrency = concurrency
        self.loop_task = None
        self.running = {}
        self.stopping = False

    async def start(self):
        if self.loop_task and not self.loop_task.done():
            return
        self.stopping = False
        self.loop_task = asyncio.create_task(self._loop(), name="resource-generation-dispatch")

    def _tick(self):
        with self.session_factory() as db:
            for status in ("completed", "cancelled"):
                db.query(DBGenerationTask).filter(DBGenerationTask.status == status,
                    DBGenerationTask.automation_state.in_(ACTIVE_STATES)).update({
                        DBGenerationTask.automation_state: status, DBGenerationTask.execution_token: None,
                        DBGenerationTask.lease_expires_at: None,
                    }, synchronize_session=False)
            resume_changed_configuration(db)
            for task_id, token in list(self.running):
                renew_lease(db, task_id, token)
            signature = configuration_signature()
            if any((task.automation_context or {}).get("configuration") == signature
                   for task in db.query(DBGenerationTask).filter_by(automation_state="waiting_configuration")
                   if task.status not in {"completed", "cancelled"}):
                return []
            claimed = []
            for _ in range(self.concurrency - len(self.running)):
                claim = claim_resource_job(db)
                if not claim:
                    break
                claimed.append(claim)
            return claimed

    async def _loop(self):
        while not self.stopping:
            self.running = {key: future for key, future in self.running.items() if not future.done()}
            try:
                for claim in await asyncio.to_thread(self._tick):
                    self.running[claim] = asyncio.create_task(asyncio.to_thread(
                        run_claimed_resource_job, *claim, session_factory=self.session_factory))
            except Exception:
                log.exception("Generation dispatch tick failed")
            await asyncio.sleep(2)

    async def stop(self):
        self.stopping = True
        if self.loop_task:
            await self.loop_task
        # Fence outstanding writers before returning; threads cannot be killed
        # safely. Their late responses check ownership before persistence.
        with self.session_factory() as db:
            for task_id, token in self.running:
                db.query(DBGenerationTask).filter_by(id=task_id, execution_token=token).update({
                    DBGenerationTask.execution_token: None,
                    DBGenerationTask.lease_expires_at: _utcnow(),
                }, synchronize_session=False)
            db.commit()


GENERATION_DISPATCHER = GenerationDispatcher()
