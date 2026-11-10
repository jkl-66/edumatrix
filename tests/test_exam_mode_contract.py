from __future__ import annotations

from dataclasses import replace
from contextlib import nullcontext
import json

import pytest
from fastapi.testclient import TestClient

import app.m5_api as m5_api
import app.m5_exam_core as exam_core
from app.auth import get_current_user
from app.database import DBModelCall, DBAuditLog, DBGenerationTask
from app.main import app
from app.m5_exam_core import FormalExamError, IntelligentExamConfigInput

from tests.test_f6_t06_formal_exam import _configuration, _demo_configuration, _fixture


class GovernedLLM:
    model = "deepseek-v4-flash"
    thinking_mode = "enabled"
    reasoning_effort = "max"


def _work(session, task_id):
    from app.generation_dispatch import claim_resource_job, _utcnow
    from app.learning_generation_jobs import run_claimed_learning_job
    task = session.get(DBGenerationTask, task_id)
    task.next_attempt_at = _utcnow()
    session.commit()
    claim = claim_resource_job(session)
    assert claim and claim[0] == task_id
    run_claimed_learning_job(*claim, session_factory=lambda: nullcontext(session))
    session.expire_all()
    return session.get(DBGenerationTask, task_id)


def _patch_db_and_user(monkeypatch, session, learner):
    async def fake_run_db_op(operation):
        return operation(session)

    monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: learner
    return TestClient(app)


def _patch_config(monkeypatch, **overrides):
    monkeypatch.setattr(m5_api, "CONFIG", replace(m5_api.CONFIG, **overrides))


def test_demo_mode_exposes_objective_contract_and_rejects_subjective_exam(monkeypatch):
    session, engine, learner, _completion = _fixture()
    _patch_config(
        monkeypatch,
        demo_mode=True,
        llm_provider="deterministic",
        llm_model="deterministic",
    )
    client = _patch_db_and_user(monkeypatch, session, learner)
    try:
        context = client.get(
            "/api/v1/m5/assessment/intelligent-exams/context",
            params={"course_id": "course-f6"},
        )
        assert context.status_code == 200, context.text
        body = context.json()
        assert body["external_model_required"] is False
        assert body["llm_generation_required"] is False
        assert body["question_type_counts"]["short_answer"] == 0

        unsupported = client.post(
            "/api/v1/m5/assessment/intelligent-exams",
            json={"configuration": _configuration("demo-subjective-rejected")},
        )
        assert unsupported.status_code == 422, unsupported.text
        assert unsupported.json()["detail"]["code"] == (
            "intelligent_exam_demo_subjective_unsupported"
        )
        assert session.query(exam_core.DBAssessmentExam).count() == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close()
        engine.dispose()


def test_production_context_keeps_live_model_contract(monkeypatch):
    session, engine, learner, _completion = _fixture()
    _patch_config(
        monkeypatch,
        demo_mode=False,
        llm_provider="openai",
        llm_model="deepseek-v4-flash",
    )
    client = _patch_db_and_user(monkeypatch, session, learner)
    try:
        context = client.get(
            "/api/v1/m5/assessment/intelligent-exams/context",
            params={"course_id": "course-f6"},
        )
        assert context.status_code == 200, context.text
        body = context.json()
        assert body["external_model_required"] is True
        assert body["llm_generation_required"] is True
        assert body["question_type_counts"]["short_answer"] == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close()
        engine.dispose()


def test_production_model_failure_is_explicit_and_never_falls_back(monkeypatch):
    session, engine, learner, _completion = _fixture()
    _patch_config(
        monkeypatch,
        demo_mode=False,
        llm_provider="openai",
        llm_model="deepseek-v4-flash",
    )
    client = _patch_db_and_user(monkeypatch, session, learner)
    monkeypatch.setattr(m5_api, "_build_governed_assessment_llm", lambda: GovernedLLM())

    async def failing_gateway(*_args, **_kwargs):
        raise RuntimeError("HTTP 402 insufficient balance")

    monkeypatch.setattr(exam_core, "execute_registered_structured_call", failing_gateway)
    monkeypatch.setattr(
        exam_core,
        "_generate_dynamic_exam_items",
        lambda *_args, **_kwargs: pytest.fail("production mode must not use the deterministic fallback"),
    )
    try:
        response = client.post(
            "/api/v1/m5/assessment/intelligent-exams",
            json={"configuration": _configuration("production-failure-explicit")},
        )
        assert response.status_code == 201, response.text
        task = _work(session, response.json()['generation']['id'])
        assert task.automation_state == 'waiting_configuration'
        assert task.failure_code == 'intelligent_exam_generation_failed'
        assert session.query(exam_core.DBAssessmentExam).count() == 0
        assert session.query(exam_core.DBAssessmentQuestion).filter_by(
            origin="ai_generated",
        ).count() == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close()
        engine.dispose()


def test_core_rejects_invalid_live_model_without_local_blueprint(monkeypatch):
    session, engine, learner, _completion = _fixture()

    async def failing_gateway(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(exam_core, "execute_registered_structured_call", failing_gateway)
    try:
        with pytest.raises(FormalExamError) as error:
            exam_core.build_intelligent_exam_input(
                session,
                owner_public_id=learner.public_id,
                config=IntelligentExamConfigInput(
                    **_configuration("core-production-failure")
                ),
                llm=GovernedLLM(),
            )
        assert error.value.code == "intelligent_exam_generation_failed"
        assert session.query(exam_core.DBAssessmentQuestion).filter_by(
            origin="ai_generated",
        ).count() == 0
    finally:
        session.close()
        engine.dispose()


def test_exam_schema_rejects_missing_options_before_gateway_records_success():
    config = IntelligentExamConfigInput(**{**_configuration(), "question_type_counts": {"single_choice": 1}})
    question = {"question_type": "single_choice", "prompt": "计算2+3", "answer_key": {"choice": "A"},
                "scoring_rule": {"type": "exact"}, "explanation": "2+3=5，因此选A。",
                "primary_knowledge_point_id": "kp-f6-a", "source_ref_ids": ["source-ref-f6"]}
    with pytest.raises(FormalExamError) as error:
        exam_core._validate_llm_exam_output({"questions": [question]}, config=config,
            blueprint={"knowledge_points": [{"id": "kp-f6-a", "title": "算术"}], "source_ref_ids": ["source-ref-f6"]})
    assert error.value.code == "intelligent_exam_llm_question_invalid"


class ScriptedExamLLM(GovernedLLM):
    provider = "openai"
    max_tokens = 65536

    def __init__(self, calls, invalid=None, failure=None):
        self.calls = calls
        self.invalid = invalid
        self.failure = failure

    async def generate(self, system, user, *, role):
        data = json.loads(user)
        self.calls.append((role, data))
        if role == '试卷组合核对':
            return json.dumps({'approved': True, 'findings': []})
        if role == 'quiz_independent_solver':
            assert 'answer_key' not in data['question'] and 'explanation' not in data['question']
            kind = data['question']['type']
            return json.dumps({'answer': 'A' if kind == 'single_choice' else ['7'] if kind == 'fill_blank'
                else True if kind == 'true_false' else '保留课程条件', 'justification': '根据原题条件求解。'})
        if role == 'resource_review_adjudicator':
            return json.dumps({'decisions':[{'issue_id': f['issue_id'], 'verdict':'confirmed',
                'reason':'给定3和4应相加。', 'fix':'按原数据重算。'} for f in data['findings']]})
        if role == 'resource_reviewer':
            qs = json.loads(data['candidates'][0]['content'])['question_details']
            failing = self.failure and any(q.get('question_type') == 'fill_blank' for q in qs)
            failed_before = any(r == 'injected_failure' for r, _ in self.calls)
            if failing and not failed_before:
                self.calls.append(('injected_failure', {'versions': [q['questionVersionId'] for q in qs]}))
                if self.failure == 'unavailable':
                    raise RuntimeError('HTTP 503 synthetic reviewer outage')
                findings = [{'resourceType':'quiz', 'location':'第1题', 'severity':'knowledge_error',
                    'issue':'逐项核对行列范围、干扰项来源及正确运算。' * 40, 'fix':'按原数据重算。'}]
                approved = self.failure == 'contradictory'
            else:
                findings, approved = [], True
            return json.dumps({'approved': approved, 'findings':findings, 'rejectedTypes':['quiz'] if findings else [],
                'summary':'题干、答案和解析已逐项核对，保留当前课程条件。' * 30,
                'conditionReview':[{'claimId': c['id'], 'status':'valid', 'reason':'合成检查', 'fix':''}
                    for c in data.get('condition_claims',[])],
                'verificationDecisions':[{'verification_id':v['verification_id'], 'verdict':'agree',
                    'evidence':'按题设比较答案一致。'} for v in data.get('independent_quiz_verification',[])]}, ensure_ascii=False)
        count = sum(r == '智能组卷出题' for r, _ in self.calls)
        questions = []
        for kind, quantity in data['question_type_counts'].items():
            for _ in range(quantity):
                q = {'question_type':kind, 'prompt':f"依据课程条件核对情境{data.get('question_position', 1)}的结论。" if kind != 'fill_blank' else '计算3+4。',
                    'options':['满足条件', '忽略条件'] if kind == 'single_choice' else [],
                    'answer_key': {'choice':'A'} if kind == 'single_choice' else {'value':True} if kind == 'true_false'
                        else {'blanks':['7']} if kind == 'fill_blank' else {'reference_answer':'保留课程条件'},
                    'scoring_rule':{'type':'exact'} if kind != 'short_answer' else {'version':'rubric-ml-v1',
                        'criteria':[{'id':'scope','label':'课程范围','weight':1}]},
                    'primary_knowledge_point_id':data['knowledge_points'][0]['id'], 'source_ref_ids':[data['sources'][0]['id']],
                    'explanation':'因为题干要求保留课程条件，只有保留关键前提才能推出结论。'}
                if count == 1 and self.invalid is not False:
                    if self.invalid is None:
                        q.pop('explanation')
                    else:
                        q['explanation'] = self.invalid
                questions.append(q)
        return json.dumps({'questions':questions}, ensure_ascii=False)


@pytest.mark.parametrize("invalid_explanation", [None, "", " \n ", "答案已依据课程来源核验。生成蓝图已经确认。", "正确答案是A。"])
def test_incomplete_exam_automatically_recovers_same_request(monkeypatch, invalid_explanation):
    session, engine, learner, _ = _fixture()
    _patch_config(monkeypatch, demo_mode=False, llm_provider='openai', llm_model='deepseek-v4-flash')
    client = _patch_db_and_user(monkeypatch, session, learner)
    calls = []
    monkeypatch.setattr(m5_api, '_build_governed_assessment_llm', lambda: ScriptedExamLLM(calls, invalid_explanation))
    request = {'configuration':_configuration('exam-auto-explanation-recovery')}
    try:
        submitted = client.post('/api/v1/m5/assessment/intelligent-exams', json=request)
        assert submitted.status_code == 201, submitted.text
        task_id = submitted.json()['generation']['id']
        assert client.post('/api/v1/m5/assessment/intelligent-exams', json=request).json()['generation']['id'] == task_id
        task = _work(session, task_id)
        assert task.automation_state == 'retry_wait', task.automation_context
        assert session.query(exam_core.DBAssessmentExam).count() == 0
        assert session.query(exam_core.DBAssessmentQuestion).filter_by(origin='ai_generated').count() == 0
        failed_call = session.query(DBModelCall).filter_by(status='failed').one()
        assert failed_call.error_code == 'structured_output_invalid' and failed_call.output_tokens > 0
        task = _work(session, task_id)
        assert task.status == 'completed', task.automation_context
        result = client.get('/api/v1/m5/assessment/intelligent-exams/generation',
            params={'course_id':'course-f6','task_id':task_id}).json()['generation']['result']
        assert len(result['items']) == 4
        assert session.query(exam_core.DBAssessmentExam).count() == 1
        assert all('answer_key' not in item for item in result['items'])
        assert sum(r == '智能组卷出题' for r, _ in calls) == 5
        before = len(calls)
        assert client.post('/api/v1/m5/assessment/intelligent-exams',json=request).json()['generation']['id'] == task_id
        assert len(calls) == before
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close(); engine.dispose()


@pytest.mark.parametrize('failure', ['rejected', 'unavailable', 'contradictory'])
def test_exam_reuses_successful_question_and_repairs_only_rejected_question(monkeypatch, failure):
    session, engine, learner, _ = _fixture()
    _patch_config(monkeypatch, demo_mode=False, llm_provider='openai', llm_model='deepseek-v4-flash')
    client = _patch_db_and_user(monkeypatch, session, learner)
    calls = []
    monkeypatch.setattr(m5_api, '_build_governed_assessment_llm', lambda: ScriptedExamLLM(calls, False, failure))
    request = {'configuration':{**_configuration('exam-auto-review-recovery'),
        'question_type_counts':{'single_choice':1,'fill_blank':1}}}
    try:
        submitted = client.post('/api/v1/m5/assessment/intelligent-exams',json=request)
        task_id = submitted.json()['generation']['id']
        task = _work(session, task_id)
        assert task.automation_state == 'retry_wait', task.automation_context
        candidates = session.query(exam_core.DBAssessmentQuestion).filter_by(origin='ai_generated').all()
        assert len(candidates) == 2
        good = next(q for q in candidates if q.status == 'approved')
        draft = next(q for q in candidates if q.status == 'draft')
        saved = {q.current_version_id: session.get(exam_core.DBAssessmentQuestionVersion, q.current_version_id).content_hash for q in candidates}
        with pytest.raises(FormalExamError) as error:
            exam_core.create_exam(session, owner_public_id=learner.public_id, payload=exam_core.ExamCreateInput(
                course_id='course-f6', title='未通过题目不得成卷', items=(exam_core.ExamItemInput(question_version_id=draft.current_version_id, points=100),)))
        assert error.value.code == 'exam_question_forbidden'
        if failure != 'unavailable':
            review = session.query(exam_core.DBAssessmentGenerationReview).order_by(exam_core.DBAssessmentGenerationReview.created_at.desc()).first()
            assert review.review['findings'][0]['issue'] == '逐项核对行列范围、干扰项来源及正确运算。' * 40
        task = _work(session, task_id)
        assert task.status == 'completed', task.automation_context
        result = client.get('/api/v1/m5/assessment/intelligent-exams/generation',
            params={'course_id':'course-f6','task_id':task_id}).json()['generation']['result']
        published = {item['question_version_id'] for item in result['items']}
        assert good.current_version_id in published
        assert (draft.current_version_id in published) == (failure == 'unavailable')
        assert sum(r == '智能组卷出题' for r,_ in calls) == (2 if failure == 'unavailable' else 3)
        for version_id, digest in saved.items():
            assert session.get(exam_core.DBAssessmentQuestionVersion,version_id).content_hash == digest
        assert session.query(exam_core.DBAssessmentExam).count() == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close(); engine.dispose()


def test_exam_retry_keeps_learning_basis_and_approved_question_after_learning(monkeypatch):
    from app.database import DBProfileSnapshot, DBTaskEvent, DBSourceRef
    from app import learning_generation_jobs as jobs
    session, engine, learner, _ = _fixture()
    _patch_config(monkeypatch, demo_mode=False, llm_provider='openai', llm_model='deepseek-v4-flash')
    client = _patch_db_and_user(monkeypatch, session, learner)
    calls = []
    monkeypatch.setattr(m5_api, '_build_governed_assessment_llm', lambda: ScriptedExamLLM(calls, False, 'unavailable'))
    configuration = {**_configuration('exam-learning-basis'),
        'question_type_counts': {'single_choice': 1, 'fill_blank': 1}}
    try:
        session.add(DBProfileSnapshot(id='exam-basis-profile', owner_public_id=learner.public_id,
            profile_version='profile.continuous.v1', content_hash='initial-learning-basis', trace_id='basis-test',
            snapshot={'course_id': 'course-f6', 'concept_mastery': {'kp-f6-a': .3, 'kp-f6-b': .4}}))
        session.commit()
        task_id = client.post('/api/v1/m5/assessment/intelligent-exams',
            json={'configuration': configuration}).json()['generation']['id']
        assert _work(session, task_id).automation_state == 'retry_wait'
        components = session.query(DBTaskEvent).filter_by(task_id=task_id,
            event_type='learning_generation.component').order_by(DBTaskEvent.sequence).all()
        original = next(row.payload['value'] for row in components
            if row.payload['key'].startswith('exam-blueprint:'))
        content_scope = dict(course_id='course-f6', owner_public_id=learner.public_id, include_profile=False)
        content_basis = jobs.course_generation_basis(session, **content_scope)
        profile = session.get(DBProfileSnapshot, original['profile_snapshot_id'])
        profile.snapshot = {**profile.snapshot, 'concept_mastery': {'kp-f6-a': .9, 'kp-f6-b': .8}}
        profile.profile_version = 'profile.continuous.v2'
        session.commit()
        jobs.assert_course_generation_basis(session, content_basis, **content_scope)
        assert _work(session, task_id).status == 'completed'
        exam = session.query(exam_core.DBAssessmentExam).one()
        version = session.get(exam_core.DBAssessmentExamVersion, exam.current_version_id)
        assert version.generation_context['blueprint'] == original
        assert version.generation_context['profile_version'] == original['profile_version']
        assert sum(role == '智能组卷出题' for role, _ in calls) == 2
        # A new explicit request gets the updated learning basis.
        newer = exam_core.build_intelligent_exam_input(session, owner_public_id=learner.public_id,
            config=IntelligentExamConfigInput(**{**configuration, 'idempotency_key':'next-exam'}))
        assert newer.generation_context['profile_version'] == profile.profile_version
        assert newer.generation_context['blueprint']['semantic_input_hash'] != original['semantic_input_hash']
        session.query(DBSourceRef).first().quote += '修订课程来源条件。'
        session.commit()
        with pytest.raises(jobs.LearningGenerationError):
            jobs.assert_course_generation_basis(session, content_basis, **content_scope)
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close(); engine.dispose()
