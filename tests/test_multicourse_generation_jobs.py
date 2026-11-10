"""Persisted multi-course requests; injected failures are separate from live evidence."""
import asyncio
from datetime import timedelta

import pytest
from app import diagnostic_api, diagnostic_generation, multicourse_diagnostic as multi
from app import generation_dispatch as dispatch, learning_generation_jobs as jobs
from app.database import DBUser, DBGenerationTask, DBDiagnosticBlueprint, DBTaskEvent, DBKnowledgePoint
from tests.test_generation_dispatch import runtime


@pytest.mark.parametrize('failure', ['network', 'account'])
def test_multicourse_preserves_completed_course_and_resumes_original_job(runtime, monkeypatch, failure):
    generated, attempts = [], []
    monkeypatch.setattr(diagnostic_api, 'build_diagnostic_llm', lambda: object())
    def generate(db, *, user, request, llm, task_id):
        existing = db.query(DBDiagnosticBlueprint).filter_by(idempotency_key=request.idempotency_key).first()
        if existing:
            return existing, False
        attempts.append((request.course_id, task_id))
        if request.course_id == 'course-b' and len(attempts) == 2:
            raise diagnostic_generation.DiagnosticGenerationError(
                'diagnostic_service_auth_failed' if failure == 'account' else 'diagnostic_service_unavailable',
                'HTTP 402 Payment Required' if failure == 'account' else 'connection interrupted')
        generated.append(request.course_id)
        row = DBDiagnosticBlueprint(owner_public_id=user.public_id, course_id=request.course_id,
            idempotency_key=request.idempotency_key, question_count=15, estimated_minutes=30, content_hash='a'*64)
        db.add(row); db.flush()
        return row, True
    monkeypatch.setattr(multi, 'generate_diagnostic_blueprint', generate)
    monkeypatch.setattr(multi, 'diagnostic_blueprint_payload', lambda db, row: {'id':row.id, 'course':{'id':row.course_id}})
    with runtime() as db:
        actor = db.query(DBUser).filter_by(username='lzz').one()
        task_id = jobs.queue_task(db, actor, course_id='demo-course-rag-trust-v1', capability='multicourse_diagnostic.prepare',
            request={'courseIds':['course-a','course-b'], 'questionCount':15, 'selfRating':'foundation',
                     'idempotencyKey':'two-courses-original'}, key='multi-original')['id']
        claim = dispatch.claim_resource_job(db)
    dispatch.run_claimed_resource_job(*claim, session_factory=runtime)
    with runtime() as db:
        task = db.get(DBGenerationTask, task_id)
        assert task.automation_state == ('waiting_configuration' if failure == 'account' else 'retry_wait')
        assert db.query(DBDiagnosticBlueprint).count() == 1
        assert jobs.task_payload(db, task)['result'] is None
        if failure == 'account':
            assert dispatch.claim_resource_job(db) is None
            # Simulate the user restoring account configuration, not a blind retry.
            monkeypatch.setattr(dispatch, 'configuration_signature', lambda: 'restored-account')
            dispatch.resume_changed_configuration(db)
        task.next_attempt_at = dispatch._utcnow() - timedelta(seconds=1)
        db.commit()
        resumed = dispatch.claim_resource_job(db)
    assert resumed[0] == task_id
    dispatch.run_claimed_resource_job(*resumed, session_factory=runtime)
    with runtime() as db:
        task = db.get(DBGenerationTask, task_id)
        assert task.status == 'completed'
        assert jobs.task_payload(db, task)['result']['ready_count'] == 2
        assert db.query(DBTaskEvent).filter_by(task_id=task_id, event_type='learning_generation.failed').count() == 1
    assert generated == ['course-a', 'course-b']
    assert {item[1] for item in attempts} == {task_id}


def test_multicourse_queue_restore_is_private_and_does_not_call_model(runtime, monkeypatch):
    async def run(operation):
        with runtime() as db: return operation(db)
    monkeypatch.setattr(diagnostic_api, 'run_db_op', run)
    monkeypatch.setattr(diagnostic_api, 'diagnostic_preflight', lambda *a, **k: {'canGenerate':True})
    monkeypatch.setattr(diagnostic_api, 'build_diagnostic_llm', lambda: pytest.fail('queue must not call model'))
    with runtime() as db:
        actor = db.query(DBUser).filter_by(username='lzz').one()
        other = DBUser(public_id='other-multi-user', username='other-multi-user', hashed_password='x', role='student')
        db.add(other); db.commit()
        payload = diagnostic_api.MultiCourseDiagnosticGenerateRequest(courseIds=['demo-course-rag-trust-v1'],
            idempotencyKey='private-multi-request', background=True)
        first = asyncio.run(diagnostic_api.create_multicourse_diagnostic_blueprints(payload, actor))
        repeat = asyncio.run(diagnostic_api.create_multicourse_diagnostic_blueprints(payload, actor))
        assert first['task']['id'] == repeat['task']['id']
        assert asyncio.run(diagnostic_api.get_multicourse_generation_task('blueprints', payload.idempotencyKey, actor))['task']['id'] == first['task']['id']
        assert asyncio.run(diagnostic_api.get_multicourse_generation_task('blueprints', payload.idempotencyKey, other))['task'] is None


def test_changed_prerequisite_invalidates_learning_generation_basis(runtime):
    with runtime() as db:
        actor = db.query(DBUser).filter_by(username='lzz').one()
        scope = {'course_id':'demo-course-rag-trust-v1', 'owner_public_id':actor.public_id}
        basis = jobs.course_generation_basis(db, **scope)
        with runtime() as writer:
            point = writer.get(DBKnowledgePoint, 'demo-kp-07')
            point.prerequisites = ['demo-kp-06', 'new-required-prerequisite']
            writer.commit()
        with pytest.raises(jobs.LearningGenerationError):
            jobs.assert_course_generation_basis(db, basis, **scope)


def test_multicourse_selection_has_no_eight_course_ceiling():
    values = tuple(f'course-{i}' for i in range(12))
    assert multi._unique_ids(values, field='courseIds') == values
    assert diagnostic_api.MultiCourseDiagnosticGenerateRequest(courseIds=values, idempotencyKey='many-courses').courseIds == values
