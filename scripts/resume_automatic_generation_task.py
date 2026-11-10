"""Resume one failed acceptance task through the admin service and dispatcher.

This is recorded developer intervention after a code repair, not natural
automatic acceptance. Existing running requests keep their original owners.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main(task_id, label):
    from sqlalchemy import and_, or_
    from app.admin_api import _retry_task, _resume_resource_retry
    from app.database import DBGenerationTask, DBUser, SessionLocal, _utcnow
    from app.generation_dispatch import claim_resource_job, renew_lease, run_claimed_resource_job

    root = Path(__file__).resolve().parents[1] / 'scratch/automatic-generation-r207'
    output = root / ('resume-' + task_id + '-' + label + '.json')
    if output.exists():
        raise RuntimeError('This recovery was already recorded; inspect it before resubmitting.')
    with SessionLocal() as db:
        actual_db = Path(db.bind.url.database).resolve()
        assert actual_db == (root / 'acceptance.sqlite3').resolve(), actual_db
        # Admin retry and claim share the same write transaction, so the old
        # live server cannot pick up this repaired-code attempt in between.
        db.connection().exec_driver_sql('BEGIN IMMEDIATE')
        task = db.get(DBGenerationTask, task_id)
        assert task and task.automation_state == 'needs_attention'
        now = _utcnow()
        due = and_(DBGenerationTask.automation_state.in_(['queued', 'retry_wait']),
                   or_(DBGenerationTask.next_attempt_at.is_(None), DBGenerationTask.next_attempt_at <= now))
        expired = and_(DBGenerationTask.automation_state == 'running', DBGenerationTask.lease_expires_at <= now)
        assert not db.query(DBGenerationTask.id).filter(
            DBGenerationTask.status.notin_(['completed', 'cancelled']), or_(due, expired)).first()
        evidence = {'task_id': task_id, 'developer_recovery': True,
                    'entry': 'admin_api._retry_task -> generation_dispatch.claim/run',
                    'before': {'status': task.status, 'automation_state': task.automation_state,
                               'failure_code': task.failure_code, 'failure_reason': task.failure_reason,
                               'automation_context': task.automation_context}}
        actor = db.query(DBUser).filter_by(role='admin', is_active=True).first()
        assert actor is not None
        _retry_task(db, actor=actor, task_id=task_id)
        _resume_resource_retry(db, task_id)
        claim = claim_resource_job(db)
        assert claim and claim[0] == task_id
        evidence['claimed_at'] = _utcnow().isoformat()
        output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf8')
    print('claimed original task', task_id, flush=True)
    running = asyncio.create_task(asyncio.to_thread(run_claimed_resource_job, *claim))
    while not running.done():
        await asyncio.wait({running}, timeout=15)
        if not running.done():
            with SessionLocal() as db:
                if not renew_lease(db, *claim):
                    print('execution ownership ended', task_id, flush=True)
                    break
    await running
    with SessionLocal() as db:
        task = db.get(DBGenerationTask, task_id)
        evidence['after'] = {'status': task.status, 'automation_state': task.automation_state,
                             'failure_code': task.failure_code, 'failure_reason': task.failure_reason,
                             'progress': task.progress, 'automation_context': task.automation_context}
        evidence['finished_at'] = _utcnow().isoformat()
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'task_id': task_id, 'status': evidence['after']['status'],
                      'automation_state': evidence['after']['automation_state']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('task_id')
    parser.add_argument('--label', default='r208f')
    args = parser.parse_args()
    asyncio.run(main(args.task_id, args.label))
