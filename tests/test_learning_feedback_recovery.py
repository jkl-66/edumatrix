"""Persisted feedback recovery with synthetic submissions and injected faults."""
import json
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import diagnostic_api, diagnostic_report, feynman, feynman_api
from app import learning_generation_jobs as jobs, generation_dispatch as dispatch
from app.auth import get_current_user
from app.database import DBGenerationTask, DBDiagnosticReport, DBProfileSnapshot, DBUser, DBAssessmentAttempt
from tests.test_generation_dispatch import runtime
from tests.test_f3_diagnostic_report import _submitted_diagnostic
from tests.test_f6_t05_feynman import _resource, _action, ROUND1
from tests.test_acceptance_p1_b07_diagnostic_explanations import _ApprovedExplanationLLM, _fake_gateway


def client_for(module, actor, runtime, monkeypatch):
    async def run(operation):
        with runtime() as db:
            return operation(db)
    monkeypatch.setattr(module, 'run_db_op', run)
    app = FastAPI()
    app.include_router(module.router)
    app.dependency_overrides[get_current_user] = lambda: actor
    return TestClient(app)


def run_next(runtime):
    with runtime() as db:
        claim = dispatch.claim_resource_job(db)
    assert claim
    dispatch.run_claimed_resource_job(*claim, session_factory=runtime)


def due(runtime, task_id):
    with runtime() as db:
        task = db.get(DBGenerationTask, task_id)
        assert task.automation_state == 'retry_wait'
        task.next_attempt_at = dispatch._utcnow() - timedelta(seconds=1)
        db.commit()


def test_diagnostic_partial_report_recovers_original_items_without_duplicate_attempts(runtime, monkeypatch):
    with runtime() as db:
        actor, blueprint, work, _ = _submitted_diagnostic(db)
        blueprint.generation_stages = [{'key': 'live', 'status': 'completed'}]
        db.commit()
        session_id, owner = work.id, actor.public_id
        before_profiles = db.query(DBProfileSnapshot).count()
    monkeypatch.setattr(diagnostic_api, 'build_diagnostic_llm', _ApprovedExplanationLLM)
    calls = []
    async def partial_then_disconnect(*args, **kwargs):
        packet = json.loads(kwargs['user_prompt'])
        calls.append(packet)
        if len(calls) == 2:
            raise ConnectionError('network disconnected after partial report')
        result = await _fake_gateway(*args, **kwargs)
        if len(calls) == 1:
            result.structured_output['items'] = result.structured_output['items'][:2]
            result.structured_output['status'] = 'partial'
        return result
    monkeypatch.setattr(diagnostic_report, 'execute_registered_structured_call', partial_then_disconnect)
    with client_for(diagnostic_api, actor, runtime, monkeypatch) as client:
        url = f'/api/v1/diagnostics/sessions/{session_id}'
        request = {'idempotencyKey': 'report-original-click', 'background': True}
        queued = client.post(url + '/report', json=request)
        assert queued.status_code == 201, queued.text
        task_id = queued.json()['task']['id']
        assert client.post(url + '/report', json=request).json()['task']['id'] == task_id
        run_next(runtime)
        with runtime() as db:
            assert not db.query(DBDiagnosticReport).filter_by(session_id=session_id).first()
            assert db.query(DBProfileSnapshot).count() == before_profiles
            assert db.query(DBAssessmentAttempt).filter(DBAssessmentAttempt.idempotency_key.like(f'diagnostic-session:{session_id}:%')).count() == 5
        assert client.get(url + '/report-task').json()['task']['automation']['state'] == 'retry_wait'
        due(runtime, task_id)
        run_next(runtime)
        result = client.get(url + '/report').json()
        assert result['evaluation']['completedCount'] == 5
        assert len(calls) == 3
        assert len({p['report_id'] for p in calls}) == 1
        first_two = {i['question_version_id'] for i in calls[0]['items'][:2]}
        assert not first_two & {i['question_version_id'] for i in calls[-1]['items']}
        assert client.post(url + '/report', json=request).json()['report']['id'] == result['id']
        with runtime() as db:
            assert db.query(DBAssessmentAttempt).filter(DBAssessmentAttempt.idempotency_key.like(f'diagnostic-session:{session_id}:%')).count() == 5
        actor.public_id = 'someone-else'
        assert client.get(url + '/report-task').status_code == 403


def prepare_feynman(runtime):
    with runtime() as db:
        actor = db.query(DBUser).filter_by(username='lzz').one()
        resource = _resource(db, actor, 'feedback-recovery-feynman')
        artifact, version, state, _ = feynman.create_session(db, owner=actor.public_id,
            source_resource_id=resource.id, idempotency_key='feedback-recovery-session')
        payload = feynman.session_payload(db, artifact, version, state)
        payload = _action(db, actor, payload, 'submit_round1', 'feedback-first-retelling', ROUND1)
        db.commit()
        db.refresh(actor)
        return actor, payload


def test_feynman_model_action_recovers_original_version_and_publishes_once(runtime, monkeypatch):
    actor, payload = prepare_feynman(runtime)
    original, calls = feynman._evaluate, []
    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionError('network interrupted')
        return original(*args, **kwargs)
    monkeypatch.setattr(feynman, '_evaluate', flaky)
    with client_for(feynman_api, actor, runtime, monkeypatch) as client:
        url = f"/api/v1/feynman/sessions/{payload['session_id']}"
        request = {'action': 'evaluate_round1', 'text': None, 'expected_version': payload['version_number'],
                   'idempotency_key': 'feedback-model-action', 'background': True}
        queued = client.post(url + '/actions', json=request)
        assert queued.status_code == 200, queued.text
        task_id = queued.json()['task']['id']
        assert client.post(url + '/actions', json=request).json()['task']['id'] == task_id
        assert client.post(url + '/actions', json={**request, 'background': False}).status_code == 409
        run_next(runtime)
        assert client.get(url).json()['status'] == 'round1_submitted'
        assert client.get(url + '/action-task').json()['task']['id'] == task_id
        due(runtime, task_id)
        run_next(runtime)
        completed = client.get(url).json()
        assert completed['status'] == 'review1_ready'
        assert completed['version_number'] == payload['version_number'] + 1
        assert completed['source_resource_version_id'] == payload['source_resource_version_id']
        assert client.post(url + '/actions', json=request).json()['task']['status'] == 'completed'
        assert len(calls) == 2


@pytest.mark.parametrize('interrupt', ['cancel', 'replace'])
def test_feynman_late_evaluation_does_not_publish(runtime, monkeypatch, interrupt):
    actor, payload = prepare_feynman(runtime)
    with runtime() as db:
        task_id = feynman.queue_action(db, session_id=payload['session_id'], actor=actor,
            action='evaluate_round1', text=None, expected_version=payload['version_number'],
            idempotency_key='late-feynman-action')['id']
    original = feynman._evaluate
    def delayed(*args, **kwargs):
        with runtime() as db:
            task = db.get(DBGenerationTask, task_id)
            if interrupt == 'cancel':
                task.status = task.automation_state = 'cancelled'
            else:
                task.execution_token = 'replacement-owner'
            db.commit()
        return original(*args, **kwargs)
    monkeypatch.setattr(feynman, '_evaluate', delayed)
    run_next(runtime)
    with runtime() as db:
        assert feynman.get_session(db, payload['session_id'], actor.public_id)['version_number'] == payload['version_number']


@pytest.mark.parametrize('failure', ['empty', 'malformed'])
def test_feynman_live_wrapper_repairs_bad_output_and_reuses_valid_output(runtime, monkeypatch, failure):
    from llm_client import StructuredModelContentError
    from tests.test_noc_t20_feynman_evaluation import _live_state
    with runtime() as db:
        actor = db.query(DBUser).filter_by(username='lzz').one()
        task_id = jobs.queue_task(db, actor, course_id='demo-course-rag-trust-v1', capability='feynman.action',
            request={}, key='feynman-wrapper-fault')['id']
        claim = dispatch.claim_resource_job(db)
    context = jobs.CURRENT_JOB.set({'task_id':task_id, 'token':claim[1], 'session_factory':runtime})
    calls = []
    class Backend:
        async def generate(self, system, user, *, role):
            packet = json.loads(user)
            calls.append(packet)
            if len(calls) == 1:
                if failure == 'empty':
                    raise StructuredModelContentError('missing public content')
                return '{broken'
            assert packet['previous_invalid_part']['error']
            return '{"answer":"完整的回答"}'
    async def audit(backend, **kwargs):
        return await backend.generate(kwargs['system_prompt'], kwargs['user_prompt'], role=kwargs['role'])
    monkeypatch.setattr(feynman, '_live_model_backend', Backend)
    monkeypatch.setattr(feynman, 'audited_legacy_text_call', audit)
    def call():
        return feynman._model_json(system='反馈', user={'student_text':'合成复述'}, role='feynman_evaluator',
                                  state=_live_state(), response_parser=lambda value: value['answer'])
    try:
        with pytest.raises(feynman.FeynmanError) as failed:
            call()
        with runtime() as db:
            cache, _ = jobs.component_cache(db)
            assert any(v.get('invalid') for v in cache.values())
        assert call() == '完整的回答'
        assert call() == '完整的回答'
        assert len(calls) == 2
    finally:
        jobs.CURRENT_JOB.reset(context)
