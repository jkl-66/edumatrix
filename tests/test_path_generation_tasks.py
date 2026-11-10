"""Isolated task recovery with synthetic model outputs, not live quality metrics."""
from sqlalchemy.orm import sessionmaker
import pytest

from app import path_tasks, path_draft
from app.database import DBGenerationTask, DBTaskEvent, DBUser
from tests.test_path_teaching_units import case, patch_model
from tests.test_acceptance_p1_b11_personalized_path import _RealPathBackend


def queue(case, **overrides):
    db, user, course, profile, *_ = case
    db.commit()
    return path_tasks.queue_path_task(db, user=user, course_id=course.id,
                                     **{'full_coverage': True, 'profile_snapshot_id': profile.id, **overrides})


def run(case, task):
    from unittest.mock import patch
    from app.generation_dispatch import claim_resource_job, run_claimed_resource_job, _utcnow
    db = case[0]
    factory = sessionmaker(bind=db.get_bind())
    with factory() as state:
        row = state.get(DBGenerationTask,task['id'])
        if row.status not in {'completed','cancelled'}:
            row.next_attempt_at = _utcnow()
            state.commit()
            claim = claim_resource_job(state)
        else:
            claim = None
    if claim:
        assert claim[0] == task['id']
        with patch('app.path_draft._build_path_model', _RealPathBackend):
            run_claimed_resource_job(*claim,session_factory=factory)
    db.expire_all()
    return path_tasks.get_path_task(db, user=case[1], task_id=task['id'])


def test_two_tabs_share_generation_and_restored_result_without_model_calls(case, monkeypatch):
    calls = patch_model(monkeypatch)
    first = queue(case, idempotency_key='first-browser-key')
    second = queue(case, idempotency_key='second-browser-key')
    assert first['id'] == second['id']
    result = run(case, first)
    assert result['status'] == 'completed', result
    assert result['result']['planId']
    assert result['progress']['completed'] == result['progress']['total'] > 0
    count = len(calls)
    run(case, first)
    assert len(calls) == count
    restored = path_tasks.find_path_task(case[0], user=case[1], course_id=case[2].id)
    assert restored['result'] == result['result']
    assert queue(case)['id'] == first['id']


@pytest.mark.parametrize('deployment_changed', [False, True])
def test_failed_review_keeps_candidate_and_retry_resumes_same_task(case, monkeypatch, deployment_changed):
    calls = patch_model(monkeypatch)
    real_review = path_draft._review_path_batch

    async def unavailable(*args, **kwargs):
        raise path_draft.PathDraftError('review_unavailable', 'HTTP 503 复核暂未完成。')

    monkeypatch.setattr(path_draft, '_review_path_batch', unavailable)
    task = queue(case, idempotency_key='resume-path-batch', profile_snapshot_id=None)
    failed = run(case, task)
    assert failed['status'] == 'failed'
    assert failed['progress']['stage'] == 'review'
    original_calls = len(calls)
    assert original_calls == 1
    # Learning while the first review is interrupted creates a newer profile;
    # the pending request must still reuse its original candidate and inputs.
    from tests.test_acceptance_p1_b11_personalized_path import _profile
    db, user, course, *_ = case
    newer = _profile(db, user, 'later-learning')
    newer.snapshot = {**newer.snapshot, 'learning_goal': '之后的新学习目标', 'course_id': course.id}
    db.commit()
    monkeypatch.setattr(path_draft, '_review_path_batch', real_review)
    if deployment_changed:
        from app import teaching_runtime, path_sequence
        from app.database import DBModelCall
        from app.m1_repository import append_task_event
        from copy import deepcopy
        # Older deployments did not link calls to the task. Its saved public
        # component proves provenance even when Pydantic added defaults or
        # validation reordered nodes and rebuilt prerequisite edges.
        for call in db.query(DBModelCall).all():
            summary = deepcopy(call.input_summary)
            for field in ('path_sequence_result', 'path_batch_result'):
                if field not in summary:
                    continue
                summary[field].pop('task_id', None)
                output = deepcopy(summary[field]['output'])
                if field == 'path_batch_result':
                    output['plan']['nodes'].reverse()
                    output['plan']['nodes'][0]['prerequisites'] = ['generator-edge-rebuilt-by-validator']
                append_task_event(db, task_id=task['id'], event_type='learning_generation.component',
                    payload={'key': 'legacy-' + call.id, 'value': {'valid': True, 'output': output}})
            call.input_summary = summary
        db.commit()
        runtime = teaching_runtime.teaching_runtime_context()
        monkeypatch.setattr(teaching_runtime, 'teaching_runtime_context', lambda: {
            **runtime, 'datasetPolicy': runtime['datasetPolicy'] + '支持内存CSV。'})
        monkeypatch.setattr(path_sequence, 'PATH_SEQUENCE_INSTRUCTION',
                            path_sequence.PATH_SEQUENCE_INSTRUCTION + '新的编排提示。')
        seen_reviews = []
        async def current_review(*args, **kwargs):
            seen_reviews.append(kwargs['payload'])
            return await real_review(*args, **kwargs)
        monkeypatch.setattr(path_draft, '_review_path_batch', current_review)
    assert failed['automation']['state'] == 'retry_wait'
    complete = run(case, task)
    assert complete['status'] == 'completed', complete
    # The first candidate is reused; the remaining course batches still run.
    assert sum(item['batch_index'] == 1 for item in calls) == original_calls
    assert len(calls) == len({item['batch_index'] for item in calls})
    assert all(item['context']['profile_snapshot_id'] != newer.id for item in calls)
    assert all(item['context']['learning_goal'] != '之后的新学习目标' for item in calls)
    events = case[0].query(DBTaskEvent).filter_by(task_id=task['id']).all()
    assert any(e.event_type == 'learning_generation.failed' for e in events)
    assert not any(e.event_type == 'path.retry' for e in events)
    if deployment_changed:
        assert seen_reviews[0]['candidate_reuse']
        assert seen_reviews[0]['context']['runtime']['datasetPolicy'].endswith('支持内存CSV。')
        from app.database import DBModelCall
        sequences = [c for c in db.query(DBModelCall).all() if c.input_summary.get('path_sequence_result')]
        assert len(sequences) == 1


def test_restart_preserves_automatic_task_for_worker_and_completed_tasks(case, monkeypatch):
    patch_model(monkeypatch)
    task = queue(case)
    db = case[0]
    row = db.get(DBGenerationTask, task['id'])
    row.status = 'running'
    db.commit()
    assert path_tasks.recover_interrupted_paths(db) == 0
    failed = path_tasks.get_path_task(db, user=case[1], task_id=task['id'])
    assert failed['status'] == 'running' and failed['automation']['enabled']
    result = run(case, task)
    assert result['status'] == 'completed', result
    assert path_tasks.recover_interrupted_paths(db) == 0


def test_later_learning_changes_apply_to_next_request_not_in_progress_path(case, monkeypatch):
    calls = patch_model(monkeypatch)
    task = queue(case)
    db, _, _, profile, *_ = case
    expected = path_tasks._event(db, task['id'], 'path.request').payload['learningBasis']
    profile.snapshot = {**profile.snapshot, 'learning_goal': '修改后的具体目标'}
    db.commit()
    result = run(case, task)
    assert result['status'] == 'completed', result
    assert calls
    assert calls[0]['context']['learning_goal'] == expected['snapshot']['learning_goal']
    assert calls[0]['context']['learning_goal'] != '修改后的具体目标'
    assert db.query(DBTaskEvent).filter_by(task_id=task['id'], event_type='path.context_updated').count() == 0
    assert queue(case)['id'] != task['id']


def test_source_version_changes_are_rechecked_with_frozen_learner_inputs(case, monkeypatch):
    calls = patch_model(monkeypatch)
    task = queue(case)
    db, user, course, *_ = case
    expected = path_tasks._event(db, task['id'], 'path.request').payload['learningBasis']
    course.version = 'synthetic-source-update'
    db.commit()
    result = run(case, task)
    assert result['status'] == 'completed', result
    assert calls[0]['context']['course']['version'] == 'synthetic-source-update'
    assert calls[0]['context']['learning_goal'] == expected['snapshot']['learning_goal']
    assert db.query(DBTaskEvent).filter_by(task_id=task['id'], event_type='path.context_updated').count() == 1
    assert path_tasks._event(db, task['id'], 'path.request').payload['learningBasis'] == expected


@pytest.mark.parametrize('role', ['近期学习成果安排', '诊断结果个性化路径规划', '学习路径教学复核', '全程学习安排'])
def test_provider_402_survives_path_wrappers_and_waits_without_probing(case, monkeypatch, role):
    import httpx
    from app import path_sequence
    from app.m5_capabilities import M5CapabilityError
    patch_model(monkeypatch)
    original = path_draft.execute_registered_structured_call
    failed_calls = []

    async def gateway(db, **kwargs):
        if kwargs['role'] == role:
            failed_calls.append(role)
            response = httpx.Response(402, request=httpx.Request('POST', 'https://provider.invalid/model'))
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise M5CapabilityError('provider_call_failed', 'model provider call failed') from exc
        return await original(db, **kwargs)

    monkeypatch.setattr(path_draft, 'execute_registered_structured_call', gateway)
    monkeypatch.setattr(path_sequence, 'execute_registered_structured_call', gateway)
    task = queue(case)
    result = run(case, task)
    assert result['automation']['state'] == 'waiting_configuration', result
    assert result['status'] == 'failed' and result['result'] is None
    row = case[0].get(DBGenerationTask, task['id'])
    assert 'HTTP 402' in row.automation_context['last_error']
    assert 'no running event loop' not in row.automation_context['last_error']
    run(case, task)
    assert failed_calls == [role]


def test_task_is_not_readable_by_another_learner(case):
    task = queue(case)
    db, user, *_ = case
    other = db.query(DBUser).filter(DBUser.public_id != user.public_id).first()
    with pytest.raises(path_draft.PathDraftError, match='没有找到'):
        path_tasks.get_path_task(db, user=other, task_id=task['id'])


def test_cancelled_task_is_not_overwritten_when_model_returns(case, monkeypatch):
    patch_model(monkeypatch)
    task = queue(case)
    real_review = path_draft._review_path_batch

    async def cancel_during_model(*args, **kwargs):
        with sessionmaker(bind=case[0].get_bind())() as db:
            db.get(DBGenerationTask, task['id']).status = 'cancelled'
            db.commit()
        return await real_review(*args, **kwargs)

    monkeypatch.setattr(path_draft, '_review_path_batch', cancel_during_model)
    result = run(case, task)
    assert result['status'] == 'cancelled'
    assert result['result'] is None
    assert not case[0].query(DBTaskEvent).filter_by(task_id=task['id'], event_type='path.failed').count()


def test_background_api_restores_task_and_defers_model_execution(case, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth import get_current_user
    from app import m5_api

    db, user, course, *_ = case
    db.commit()
    scheduled = []
    maker = sessionmaker(bind=db.get_bind())

    async def run_db(operation):
        with maker() as state:
            return operation(state)

    monkeypatch.setattr(m5_api, 'run_db_op', run_db)
    monkeypatch.setattr(path_tasks, 'execute_path_task', lambda task_id, factory: scheduled.append(task_id))
    app = FastAPI()
    app.include_router(m5_api.router)
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as client:
        response = client.post('/api/v1/m5/textbook-path-draft/generate', json={
            'course_id': course.id, 'full_coverage': True, 'background': True})
        assert response.status_code == 201, response.text
        task = response.json()['task']
        assert task['status'] == 'queued'
        assert scheduled == []
        assert task['automation']['state'] == 'queued'
        restored = client.get('/api/v1/m5/path-generation-tasks', params={'course_id': course.id})
        assert restored.json()['task']['id'] == task['id']
        assert client.get('/api/v1/m5/path-generation-tasks/'+task['id']).json()['task']['status'] == 'queued'
        assert scheduled == []
        assert task['automation']['state'] == 'queued'


def test_report_draft_api_keeps_explicit_selection_with_an_older_active_path(case, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth import get_current_user
    from app import m5_api
    db, user, course, profile, *_ = case
    patch_model(monkeypatch)
    plan, _ = path_draft.generate_textbook_path_draft(db, current_user=user, course_id=course.id,
        profile_snapshot_id=profile.id, time_budget_minutes=40, full_coverage=True,
        llm=_RealPathBackend(), idempotency_key='report-explicit-draft')
    db.commit()
    maker = sessionmaker(bind=db.get_bind())

    async def run_db(operation):
        with maker() as state:
            return operation(state)

    monkeypatch.setattr(m5_api, 'run_db_op', run_db)
    app = FastAPI()
    app.include_router(m5_api.router)
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as client:
        response = client.get('/api/v1/m5/textbook-path-draft', params={'course_id': course.id, 'plan_id': plan.id})
        assert response.status_code == 200, response.text
        assert response.json()['plan']['id'] == plan.id
        assert response.json()['plan']['profile_snapshot_id'] == profile.id
        assert response.json()['plan']['total_min_minutes'] == sum(n['estimate_min_minutes'] for n in response.json()['nodes'])
        missing = client.get('/api/v1/m5/textbook-path-draft', params={'course_id': course.id, 'plan_id': 'missing-draft'})
        assert missing.status_code == 409 and missing.json()['detail']['code'] == 'path_draft_not_found'
