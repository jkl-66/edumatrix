import json
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal, DBUser, DBAssessmentAttempt, DBLearningEvent, DBMisconceptionReview, DBGenerationTask
from app.m5_assessment_core import create_question_version, QuestionVersionInput, record_attempt, AttemptInput
from app.learning_inquiry import validate_interpretation, inquiry_learning_needs
from tests.api_test_helpers import auth_headers


def test_saved_inquiry_reuses_interpretation_after_feedback_failure_and_keeps_grades(monkeypatch):
    calls = []
    class Backend:
        model = 'deepseek-v4-flash'
        async def generate(self, system, user, role):
            data = json.loads(user); calls.append((role, data))
            if role == 'quiz_independent_solver':
                assert 'answer_key' not in data['question'] and 'explanation' not in data['question']
                return json.dumps({'answer':'B','justification':'0.1小于0.4。'})
            if role == 'resource_reviewer':
                return json.dumps({'approved':True, 'summary':'通过', 'findings':[], 'rejectedTypes':[],
                    'verificationDecisions':[{'verification_id':v['verification_id'],'verdict':'agree','evidence':'验证误差0.1更小。'}
                        for v in data.get('independent_quiz_verification',[])]})
            if role == 'learning_inquiry_plan':
                return json.dumps({'question':'你看哪一列，怎样比较？', 'hypotheses':[
                    {'id':'train','description':'训练当泛化','discriminating_evidence':'用训练误差选择'},
                    {'id':'direction','description':'误差方向','discriminating_evidence':'误差越高越好'}]})
            if role == 'learning_inquiry_interpretation':
                return json.dumps({'hypothesis_id':'train','learner_quote':'训练误差最低',
                    'finding':'用训练拟合代替泛化判断','next_focus':'用验证集比较未见数据表现'})
            if sum(r == 'targeted_learning_feedback' for r, _ in calls) == 1:
                raise RuntimeError('HTTP 503 simulated provider interruption')
            assert data['learning_evidence']['learner_quote'] == '训练误差最低'
            return json.dumps({'feedback':'训练误差描述已见数据的拟合，选模型要比较验证误差。',
                'next_task':{'prompt':'X训练0.02、验证0.4；Y训练0.08、验证0.1。选哪个？',
                    'options':['X模型','Y模型'],'answer':'B','explanation':'Y的验证误差0.1更低。'}})
    monkeypatch.setattr('app.learning_inquiry._backend', Backend)
    monkeypatch.setattr('app.canonical_retrieval.retrieve_canonical_sources', lambda *a, **kw: {'items':[]})
    def work(task_id):
        from app.generation_dispatch import claim_resource_job, run_claimed_resource_job, _utcnow
        with SessionLocal() as db:
            db.get(DBGenerationTask,task_id).next_attempt_at = _utcnow()
            db.commit()
            claim = claim_resource_job(db)
        assert claim and claim[0] == task_id
        run_claimed_resource_job(*claim)
    with TestClient(app, raise_server_exceptions=False) as client:
        name = 'inquiry-'+uuid.uuid4().hex
        headers = auth_headers(client, name)
        other = auth_headers(client, name+'-other')
        with SessionLocal() as db:
            actor = db.query(DBUser).filter_by(username=name).one()
            owner_id = actor.public_id
            _, version = create_question_version(db,owner_public_id=actor.public_id,course_id=None,
                question_type='single_choice',origin='manual', version=QuestionVersionInput(
                    prompt='A训练0.06验证0.22；B训练0.10验证0.16。为新数据选模型。',
                    options=('模型A','模型B'),answer_key={'choice':'B'},scoring_rule={'type':'exact'}))
            attempt, _ = record_attempt(db,owner_public_id=actor.public_id,attempt=AttemptInput(
                question_version_id=version.id,idempotency_key=name,answer={'choice':'A'}))
            correct, _ = record_attempt(db,owner_public_id=actor.public_id,attempt=AttemptInput(
                question_version_id=version.id,idempotency_key=name+'-correct',answer={'choice':'B'}))
            attempt_id, correct_id = attempt.id, correct.id
            db.commit()
        path = f'/api/v1/m5/assessment/attempts/{attempt_id}/inquiry'
        assert client.get(path,headers=other).status_code == 403
        assert client.post(path.replace(attempt_id,correct_id),headers=headers).status_code == 409
        assert client.get(path,headers=headers).json()['question'] == ''
        queued = client.post(path,headers=headers).json()
        assert queued['generation']['automation']['state'] == 'queued'
        assert client.post(path,headers=headers).json()['generation']['id'] == queued['generation']['id']
        work(queued['generation']['id'])
        assert client.get(path,headers=headers).json()['question']
        body = {'response':'我看训练误差最低。'}
        response = client.post(path+'/answer',headers=headers,json=body)
        assert response.status_code == 200, response.text
        task_id = response.json()['generation']['id']
        work(task_id)
        assert client.get(path,headers=headers).json()['generation']['automation']['state'] == 'retry_wait'
        work(task_id)  # scheduler resumes; learner never resubmits
        saved = client.get(path,headers=headers).json()
        assert saved['generation']['automation']['state'] == 'completed', saved
        assert 'answer' not in saved['feedback']['next_task']
        assert client.post(path+'/answer',headers=headers,json=body).json() == saved
        assert client.get(path,headers=headers).json() == saved
        assert client.post(path+'/answer',headers=headers,json={'response':'   '}).status_code == 422
        assert client.post(path+'/answer',headers=headers,json={'response':'另一个回答'}).status_code == 409
        assert [r for r,_ in calls].count('learning_inquiry_interpretation') == 1
        assert [r for r,_ in calls].count('targeted_learning_feedback') == 2
        assert [r for r,_ in calls].count('quiz_independent_solver') == 1
        with SessionLocal() as db:
            assert db.get(DBAssessmentAttempt,attempt_id).score == 0
            event = db.query(DBLearningEvent).filter_by(event_type='learning_inquiry_answered',owner_public_id=owner_id).one()
            assert not event.mastery_eligible and event.completion_effect == 'none'
            assert db.query(DBMisconceptionReview).filter_by(attempt_id=attempt_id).one().status == 'proposed'
        next_attempt = client.post('/api/v1/m5/assessment/attempts',headers=headers,json={
            'question_version_id':saved['feedback']['next_task']['question_version_id'],
            'idempotency_key':name+'-next','mode':'practice','answer':{'choice':'B'}})
        assert next_attempt.status_code in (200,201), next_attempt.text
        refreshed = client.get(path,headers=headers).json()
        assert refreshed['feedback']['next_task']['latest_attempt']['correct'] is True
        assert refreshed['feedback']['next_task']['explanation']


def test_inquiry_needs_are_specific_and_only_corresponding_independent_correct_answer_closes_them():
    now = datetime.utcnow()
    event = SimpleNamespace(id='evt',event_type='learning_inquiry_answered',source='backend',occurred_at=now,
        payload={'knowledge_point_id':'kp','question_version_id':'qv','attempt_id':'attempt',
                 'interpretation':{'hypothesis_id':'train','finding':'训练当泛化','next_focus':'验证集比较','learner_quote':'训练最低'}})
    assert not inquiry_learning_needs([event],'other',[])
    needs = inquiry_learning_needs([event],'kp',[])
    assert needs[0]['learner_quote'] == '训练最低' and 'score' not in needs[0]
    answer = SimpleNamespace(question_version_id='other', correct=True,submitted_at=now+timedelta(seconds=1),answer={})
    assert inquiry_learning_needs([event],'kp',[answer])
    answer.question_version_id='qv'; answer.answer={'used_hints':True}
    assert inquiry_learning_needs([event],'kp',[answer])
    answer.answer={}
    assert not inquiry_learning_needs([event],'kp',[answer])


def test_interpretation_requires_a_real_quote_and_allows_uncertainty():
    plan = {'hypotheses':[{'id':'one'}]}
    result = {'hypothesis_id':'uncertain','learner_quote':'不记得','finding':'原因未明','next_focus':'比较两个误差'}
    assert validate_interpretation(result,plan,'我不记得了') == result
    with pytest.raises(ValueError):
        validate_interpretation({**result,'learner_quote':'使用准确率'},plan,'我不记得了')
