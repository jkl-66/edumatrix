"""Faults on the shared worker, using a separate SQLite database and model doubles."""
import asyncio
import json
from datetime import timedelta

import pytest

from app import learning_generation_jobs as jobs, generation_dispatch as dispatch
from app.database import DBGenerationTask, DBTaskEvent, DBUser
from tests.test_generation_dispatch import runtime


@pytest.mark.parametrize('inner_code,expected', [('structured_output_invalid', 'retry_wait'),
                                               ('HTTP402', 'waiting_configuration')])
def test_wrapped_path_errors_keep_their_recovery_category(runtime, inner_code, expected):
    from app.path_draft import PathDraftError
    with runtime() as db:
        actor = db.query(DBUser).filter_by(username='lzz').one()
        task_id = jobs.queue_task(db, actor, course_id='demo-course-rag-trust-v1', capability='path.prepare',
                                 request={}, key='wrapped-path-' + inner_code)['id']
        try:
            try:
                raise jobs.LearningGenerationError(inner_code, 'HTTP 402 payment required' if inner_code == 'HTTP402' else '引用不匹配')
            except jobs.LearningGenerationError:
                # _fail helpers historically used implicit exception context.
                raise PathDraftError('path_draft_model_failed', '路径尚未审核完成')
        except PathDraftError as error:
            jobs.finish_attempt(db, db.get(DBGenerationTask, task_id), error)
        task = db.get(DBGenerationTask, task_id)
        assert task.automation_state == expected
        assert ('引用不匹配' if expected == 'retry_wait' else 'HTTP 402') in task.automation_context['last_error']


@pytest.mark.parametrize('interrupt', ['cancel', 'replace'])
def test_learning_job_late_results_cannot_save_components_or_publish(runtime, monkeypatch, interrupt):
    from app import learning_inquiry
    with runtime() as db:
        actor = db.query(DBUser).filter_by(username='lzz').one()
        queued = jobs.queue_task(db, actor, course_id='demo-course-rag-trust-v1',
            capability='learning_inquiry.prepare', request={'attempt_id':'synthetic-attempt'}, key='inquiry-cancel')
        task_id = queued['id']
        claim = dispatch.claim_resource_job(db)
    async def delayed(actor, attempt_id):
        with runtime() as other:
            task = other.get(DBGenerationTask, task_id)
            if interrupt == 'cancel':
                task.status = task.automation_state = 'cancelled'
            else:
                task.execution_token = 'replacement-owner'
            other.commit()
        with runtime() as state:
            _, save = jobs.component_cache(state)
            save('late-response', {'candidate':'must not be published'})
        return {'question':'late question'}
    monkeypatch.setattr(learning_inquiry, 'prepare_inquiry', delayed)
    dispatch.run_claimed_resource_job(*claim, session_factory=runtime)
    with runtime() as db:
        assert not db.query(DBTaskEvent).filter_by(task_id=task_id, event_type='learning_generation.component').first()
        assert not db.query(DBTaskEvent).filter_by(task_id=task_id, event_type='learning_generation.completed').first()
        task = db.get(DBGenerationTask, task_id)
        assert task.status == 'cancelled' if interrupt == 'cancel' else task.execution_token == 'replacement-owner'


def test_learning_lease_restart_reuses_saved_component_and_keeps_old_owner_out(runtime, monkeypatch):
    from app import learning_inquiry
    with runtime() as db:
        actor = db.query(DBUser).filter_by(username='lzz').one()
        task_id = jobs.queue_task(db, actor, course_id='demo-course-rag-trust-v1',
            capability='learning_inquiry.prepare', request={'attempt_id':'synthetic-attempt'}, key='inquiry-restart')['id']
        old = dispatch.claim_resource_job(db)
        context = jobs.CURRENT_JOB.set({'task_id':task_id, 'token':old[1]})
        try:
            _, save = jobs.component_cache(db)
            save('valid-part', {'output':{'question':'保存的问题'}})
        finally:
            jobs.CURRENT_JOB.reset(context)
        db.get(DBGenerationTask, task_id).lease_expires_at = dispatch._utcnow() - timedelta(seconds=1)
        db.commit()
        replacement = dispatch.claim_resource_job(db)
    calls = []
    async def resume(actor, attempt_id):
        calls.append(attempt_id)
        with runtime() as state:
            cache, _ = jobs.component_cache(state)
            return cache['valid-part']['output']
    monkeypatch.setattr(learning_inquiry, 'prepare_inquiry', resume)
    dispatch.run_claimed_resource_job(*old, session_factory=runtime)
    assert not calls
    dispatch.run_claimed_resource_job(*replacement, session_factory=runtime)
    with runtime() as db:
        assert db.get(DBGenerationTask, task_id).status == 'completed'
        assert jobs.task_payload(db, db.get(DBGenerationTask, task_id))['result']['question'] == '保存的问题'
    assert len(calls) == 1


def test_learning_json_keeps_invalid_draft_for_next_attempt():
    cache, calls = {}, []
    class Backend:
        async def generate(self, system, user, *, role):
            request = json.loads(user); calls.append(request)
            if len(calls) == 1:
                return '{"question":42}'
            assert request['previous_invalid_part']['raw'] == '{"question":42}'
            assert 'question必须为字符串' in request['previous_invalid_part']['error']
            return '{"question":"你比较的是哪一列？"}'
    def validate(value):
        if not isinstance(value.get('question'), str):
            raise ValueError('question必须为字符串')
    def run():
        return asyncio.run(jobs.generate_learning_json(Backend(), system='追问', request={'answer':'A'},
            role='inquiry', completed=cache, save=cache.__setitem__, validate=validate))
    with pytest.raises(jobs.LearningGenerationError): run()
    assert run()['question'] == '你比较的是哪一列？'
    assert run()['question'] and len(calls) == 2


def test_source_changed_during_model_call_resumes_from_current_inputs(runtime):
    from app.database import DBSourceRef
    with runtime() as db:
        actor = db.query(DBUser).filter_by(username='lzz').one()
        scope = {'course_id':'demo-course-rag-trust-v1', 'owner_public_id':actor.public_id}
        basis = jobs.course_generation_basis(db, **scope)
        jobs.assert_course_generation_basis(db, basis, **scope)
        task_id = jobs.queue_task(db, actor, course_id=scope['course_id'], capability='path.prepare',
            request={}, key='source-update-task')['id']
        with runtime() as updater:
            updater.get(DBSourceRef, 'demo-ref-07').quote += '修正后的课程条件。'
            updater.commit()
        with pytest.raises(jobs.LearningGenerationError) as changed:
            jobs.assert_course_generation_basis(db, basis, **scope)
        jobs.finish_attempt(db, db.get(DBGenerationTask, task_id), changed.value)
        assert db.get(DBGenerationTask, task_id).automation_state == 'retry_wait'


def test_document_code_review_gets_actual_stdout_and_reuses_execution(monkeypatch):
    from app import code_sandbox
    calls, cache = [], {}
    class Result:
        def model_dump(self, **kwargs):
            return {'status':'success', 'exitCode':0, 'stdout':'rank=9\n', 'stderr':'', 'executionTimeMs':12}
    class Executor:
        enabled = True
        async def execute(self, state):
            calls.append(state)
            return Result()
    monkeypatch.setattr(code_sandbox, 'LocalPythonExecutor', Executor)
    def run(explanation):
        return asyncio.run(code_sandbox.verify_document_code(json.dumps({'codeBlocks':[
            {'id':'example','language':'python','code':'print("rank=9")','explanation':explanation}]}),
            completed=cache, save=cache.__setitem__))
    assert run('预期rank=8')[0]['stdout'] == 'rank=9\n'
    assert run('预期rank=9')[0]['stdout'] == 'rank=9\n'
    assert len(calls) == 1
