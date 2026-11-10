from __future__ import annotations

import json
import uuid
import asyncio
import pytest

from fastapi.testclient import TestClient

import stream_api
from app.database import DBSourceDocument, DBSourceRef, DBUser, SessionLocal
from app.main import app
from tests.api_test_helpers import auth_headers


COURSE_ID = "course-machine-learning-foundations-v1"


@pytest.mark.parametrize('revision_flag,expected', [(True, True), (False, False), (None, False)])
def test_verified_source_agreement_does_not_override_an_explicit_factual_correction(revision_flag, expected):
    materials = [{'available': True, 'sourceRefId': 'ref-with-error', 'title': '待核对材料',
                  'locationLabel': '计算示例', 'quote': '两个二相加等于五。'}]
    candidate = {'claim': '两个二相加等于五。', 'support': 'supported', 'basis': 'source',
                 'source_ref_ids': ['ref-with-error'], 'quote': '两个二相加等于五。', 'location': '计算示例',
                 'support_reason': '候选忠实复述原句，但原句算术错误，应该为四。'}
    if revision_flag is not None:
        candidate['needs_revision'] = revision_flag
    claim = stream_api._normalize_claims(json.dumps({'claims': [candidate]}), materials)[0]
    assert claim['quoteVerified'] and claim['support'] == 'supported'
    assert stream_api._claim_needs_revision(claim) is expected


@pytest.mark.parametrize('basis,needs_revision,quote,support,expected', [
    ('source_scope', False, '', 'unsupported', False),
    ('source_scope', False, '', 'supported', False),
    ('source_scope', False, '', 'partially_supported', False),
    ('source_scope', True, '', 'unsupported', True),
    ('source_scope', False, '资料中根本没有的句子', 'supported', True),
    ('source', False, '', 'unsupported', True),
    ('source', False, '本节介绍类别分布。', 'partially_supported', False),
    ('source', True, '本节介绍类别分布。', 'partially_supported', True),
    ('source', False, '资料中根本没有的句子', 'partially_supported', True),
    ('worked_example', False, '', 'unsupported', False),
])
def test_scope_observation_does_not_force_rewrite_but_false_quotes_still_do(basis, needs_revision, quote, support, expected):
    materials = [{'available': True, 'sourceRefId': 'ref-scope', 'title': '当前片段',
                  'locationLabel': '第一节', 'quote': '本节介绍类别分布。'}]
    raw = json.dumps({'claims': [{'claim': '当前片段没有给出计算公式。', 'basis': basis,
                                 'needs_revision': needs_revision, 'support': support,
                                 'source_ref_ids': ['ref-scope'], 'quote': quote,
                                 'location': '第一节', 'support_reason': '只判断本次可见材料的范围。'}]})
    claim = stream_api._normalize_claims(raw, materials)[0]
    assert stream_api._claim_needs_revision(claim) is expected


def _key(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _events(text: str) -> list[tuple[str, dict]]:
    result: list[tuple[str, dict]] = []
    event_name = ""
    for line in text.splitlines():
        if line.startswith("event: "):
            event_name = line[7:]
        elif line.startswith("data: "):
            result.append((event_name, json.loads(line[6:])))
    return result


class _ProfessionalLLM:
    model = "deepseek-v4-flash"
    has_vision = False
    organized_answer = "学习率过大可能导致损失震荡。 [S1]\n\n```python\nsource_ref_id = 'teaching-example'\nprint(source_ref_id)\n```"

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def generate(self, system_prompt, user_prompt, *, role):
        self.calls.append({"role": role, "system": system_prompt, "user": user_prompt})
        if role == 'Synthesizer':
            return self.organized_answer
        if role == "Evidence Verifier":
            return json.dumps({
                "claims": [{
                    "claim_id": "claim-01",
                    "claim": "学习率过大可能导致损失震荡",
                    "support": "supported",
                    "source_ref_ids": [self.source_ref_id],
                    "quote": getattr(self, 'frozen_quote', '学习率过大会导致损失震荡。'),
                    "location": "来源片段",
                    "confidence": 0.94,
                    "review": {
                        "challenger": "未发现概念混淆",
                        "verifier": "通过",
                        "revision": "",
                    },
                }]
            }, ensure_ascii=False)
        return f"{role} 已完成当前步骤。"

    async def generate_stream(self, system_prompt, user_prompt, *, role, images):
        self.calls.append({"role": role, "system": system_prompt, "user": user_prompt})
        yield "根据课程证据，学习率过大可能导致损失震荡。"


class _Swarm:
    def __init__(self, llm):
        self.llm = llm


@pytest.mark.parametrize('final_support,needs_revision,reject', [
    ('supported', False, False), ('unsupported', False, False), ('contradicted', True, True),
    ('partially_supported', True, True), ('partially_supported', False, False),
    ('supported', True, True),
])
def test_evidence_problem_gets_one_directed_revision_and_rechecks_the_new_text(monkeypatch, final_support, needs_revision, reject):
    from types import SimpleNamespace
    calls, stages = [], []
    original = '验证误差增加0.27。' + '已正确说明的教学条件。' * 1000 + '保留完整结尾。'
    corrected = '验证误差从0.30到0.47，增加0.17。'
    quote = '第2轮验证误差为0.30，第3轮验证误差为0.47。'

    async def call(_llm, *, operation, user_prompt, response_validator=None, **kwargs):
        calls.append((operation, user_prompt))
        if operation == 'chat_subject_expert': return original
        if operation == 'chat_challenger':
            assert '保留完整结尾。' in user_prompt
            return '0.47−0.30=0.17，原稿的0.27有误。'
        if operation == 'chat_subject_revision':
            assert original in user_prompt
            return corrected
        is_recheck = '这是定向修订后的完整草稿' in user_prompt
        if is_recheck:
            assert corrected in user_prompt and original not in user_prompt
        review = {'claims': [{'claim_id':'change','claim': corrected if is_recheck else '验证误差增加0.27。',
            'support': final_support if is_recheck else 'contradicted',
            'needs_revision': needs_revision if is_recheck else True,
            'source_ref_ids':['source-chart'],'quote':quote,'location':'第2页',
            'review': {'revision': '' if is_recheck else '差值应为0.17。'}}]}
        if is_recheck:
            # The corrected draft compares two numbers. Supply the additional
            # semantic verdict now required by the real verifier contract.
            assert 'revised:content:0' in user_prompt
            review['conditionReview'] = [{'claimId': 'revised:content:0',
                'status': 'valid', 'reason': '0.47−0.30=0.17，比较对象和增加方向一致。', 'fix': ''}]
        raw = json.dumps(review, ensure_ascii=False)
        if response_validator: response_validator(raw)
        return raw

    async def notify(*values): stages.append(values)
    monkeypatch.setattr(stream_api, 'audited_legacy_text_call', call)
    context = {'user_message':SimpleNamespace(content='比较两轮验证误差。'), 'source_materials':[
        {'available':True,'sourceRefId':'source-chart','quote':quote,'title':'误差图'}]}
    run = stream_api._run_professional_evidence(_Swarm(_ProfessionalLLM()),context,{},stage_callback=notify)
    if reject:
        with pytest.raises(stream_api.EvidenceReviewError) as caught:
            asyncio.run(run)
        assert caught.value.answer_revision['after'] == corrected
        assert caught.value.answer_revision['claimsAfter'][0]['support'] == final_support
        assert caught.value.answer_revision['decision'] == 'rejected'
        assert stages[-1][1] == 'failed'
        return
    result = asyncio.run(run)
    assert [op for op,_ in calls] == ['chat_subject_expert','chat_challenger','chat_evidence_verifier',
                                      'chat_subject_revision','chat_evidence_verifier']
    assert result['expert'] == corrected
    revision = result['answer_revision']
    assert revision['before'] == original and revision['after'] == corrected
    assert revision['claimsBefore'][0]['support'] == 'contradicted'
    assert revision['claimsAfter'][0]['support'] == final_support
    assert revision['decision'] == ('verified' if final_support == 'supported' else 'qualified')
    assert [event[0] for event in stages if event[1] == 'completed'][-2:] == ['answer_revision','revision_verification']


@pytest.mark.parametrize('failure', ['review_incomplete', 'provider_failed', 'generation_failed'])
def test_completed_revision_is_kept_when_recheck_cannot_finish(monkeypatch, failure):
    from types import SimpleNamespace

    original, corrected = '实际输出为14。', '实际输出为15。'
    quote = '总价等于单价乘以数量。'
    calls = []

    async def call(_llm, *, operation, user_prompt, response_validator=None, **kwargs):
        calls.append(operation)
        if operation == 'chat_subject_expert': return original
        if operation == 'chat_challenger': return '总价计算需要修正。'
        if operation == 'chat_subject_revision':
            if failure == 'generation_failed': raise RuntimeError('synthetic generation interruption')
            return corrected
        revised = '这是定向修订后的完整草稿' in user_prompt
        if revised and failure == 'provider_failed': raise RuntimeError('synthetic recheck interruption')
        raw = json.dumps({'claims': [{
            'claim': corrected if revised else original, 'support': 'supported',
            'source_ref_ids': ['price'], 'quote': quote, 'location': '总价',
            'basis': 'worked_example', 'needs_revision': False,
            'calculations': [] if revised else [{'expression': '3*5', 'claimed_result': '14'}],
        }]}, ensure_ascii=False)
        if response_validator: response_validator(raw)
        return raw

    monkeypatch.setattr(stream_api, 'audited_legacy_text_call', call)
    context = {'user_message': SimpleNamespace(content='单价3，数量5，打印总价。'),
               'source_materials': [{'available': True, 'sourceRefId': 'price', 'quote': quote, 'title': '总价'}]}
    with pytest.raises(stream_api.EvidenceReviewError) as caught:
        asyncio.run(stream_api._run_professional_evidence(_Swarm(_ProfessionalLLM()), context, {}))
    revision = getattr(caught.value, 'answer_revision', None)
    if failure == 'generation_failed':
        assert revision is None
    else:
        assert revision['before'] == original and revision['after'] == corrected
        assert revision['decision'] == 'unverified'
        assert revision['claimsBefore'][0]['support'] == 'contradicted'
        assert revision['claimsAfter'] == []
        assert revision['seconds'] >= 0
    assert calls.count('chat_subject_revision') == 1


@pytest.mark.parametrize('depth,selected_instruction', [
    ('focused', '学生选择聚焦重点'), ('detailed', '学生选择详细推导'),
])
def test_directed_revision_preserves_current_answer_depth(monkeypatch, depth, selected_instruction):
    from types import SimpleNamespace

    original, corrected = '总价为14。', '总价为15。'
    quote = '总价等于单价乘以数量。'
    context = {'user_message': SimpleNamespace(content='单价3，数量5，求总价。'),
               'assistant_message': SimpleNamespace(id='depth-revision-test', content=''),
               'source_materials': [{'available': True, 'sourceRefId': 'price',
                                    'quote': quote, 'title': '总价'}]}
    system, _, _ = stream_api._canonical_chat_prompts(context, 'formal', depth)
    context['_answer_system_prompt'] = system
    operations = []

    async def call(_llm, *, operation, user_prompt, system_prompt, response_validator=None, **kwargs):
        operations.append(operation)
        if operation == 'chat_subject_expert': return original
        if operation == 'chat_challenger': return '3乘5是15，应修正总价。'
        if operation == 'chat_subject_revision':
            assert system_prompt.startswith(system)
            assert selected_instruction in system_prompt
            detail_required = '不要省略题目要求的步骤、条件或可运行代码' if depth == 'focused' else '推导依据'
            assert detail_required in system_prompt
            assert '不在开头、正文和结尾重复同一组结果' in system_prompt
            assert '只有学生本次询问后续学习、资料或练习时才提供对应建议' in system_prompt
            assert '只处理核对中指出的' in system_prompt
            return corrected
        revised = '这是定向修订后的完整草稿' in user_prompt
        result = json.dumps({'claims': [{
            'claim': corrected if revised else original, 'support': 'supported',
            'source_ref_ids': ['price'], 'quote': quote, 'location': '总价',
            'basis': 'worked_example', 'needs_revision': False,
            'calculations': [{'expression': '3*5', 'claimed_result': '15' if revised else '14'}],
        }]}, ensure_ascii=False)
        if response_validator: response_validator(result)
        return result

    monkeypatch.setattr(stream_api, 'audited_legacy_text_call', call)
    result = asyncio.run(stream_api._run_professional_evidence(_Swarm(_ProfessionalLLM()), context, {}))
    assert result['expert'] == corrected
    assert operations == ['chat_subject_expert', 'chat_challenger', 'chat_evidence_verifier',
                          'chat_subject_revision', 'chat_evidence_verifier']
    assert result['claims'][0]['calculations'][0]['agrees']


def test_supported_professional_answer_does_not_run_an_extra_revision(monkeypatch):
    from types import SimpleNamespace
    operations=[]
    quote='训练误差由0.6降低到0.2。'
    async def call(_llm, *, operation, **kwargs):
        operations.append(operation)
        return json.dumps({'claims':[{'claim':quote,'support':'supported','source_ref_ids':['source-ok'],
            'quote':quote,'location':'误差记录'}]},ensure_ascii=False) if operation=='chat_evidence_verifier' else quote
    monkeypatch.setattr(stream_api,'audited_legacy_text_call',call)
    result=asyncio.run(stream_api._run_professional_evidence(_Swarm(_ProfessionalLLM()),
        {'user_message':SimpleNamespace(content='训练误差有何变化？'),
         'source_materials':[{'sourceRefId':'source-ok','available':True,'quote':quote,'title':'训练记录'}]},{}))
    assert len(operations)==3 and 'chat_subject_revision' not in operations
    assert result['answer_revision'] is None


def test_stale_source_absence_is_revised_even_when_other_claims_are_correct(monkeypatch):
    from types import SimpleNamespace
    original = '本次课程摘录未完整展示方差分母。'
    corrected = '本次课程公式使用样本数作为方差分母。'
    operations = []

    async def call(_llm, *, operation, response_validator=None, **kwargs):
        operations.append(operation)
        if operation == 'chat_subject_expert':
            return original
        if operation == 'chat_challenger':
            return '请按本次材料核对。'
        if operation == 'chat_subject_revision':
            assert original in kwargs['user_prompt']
            return corrected
        is_revised = 'chat_subject_revision' in operations
        items = stream_api.conditional_teaching_claims([{'type': 'answer', 'version_id': 'initial', 'content': original}])
        raw = json.dumps({'claims': [{'claim': corrected, 'basis': 'source', 'support': 'supported',
            'source_ref_ids': ['source-ok'], 'quote': corrected, 'needs_revision': False}],
            'conditionReview': [] if is_revised else [{'claimId': item['id'], 'status': 'incorrect',
                'reason': '当前材料已写明方差分母，缺失说法不准确。', 'fix': corrected} for item in items]}, ensure_ascii=False)
        response_validator(raw)
        return raw

    monkeypatch.setattr(stream_api, 'audited_legacy_text_call', call)
    result = asyncio.run(stream_api._run_professional_evidence(_Swarm(_ProfessionalLLM()),
        {'user_message': SimpleNamespace(content='请解释方差口径。'),
         'source_materials': [{'sourceRefId': 'source-ok', 'available': True, 'quote': corrected, 'title': '课程'}]}, {}))
    assert result['expert'] == corrected and operations.count('chat_subject_revision') == 1
    original_reviews = result['calculation_review_attempts'][0]['claims']
    assert any(c['basis'] == 'source_scope' and c['revisionNeeded'] for c in original_reviews)


def test_arithmetic_in_a_valid_condition_review_is_independently_checked(monkeypatch):
    from types import SimpleNamespace
    draft = '累计增量非负时，逐次加和的结果只增不减。'
    reviews = []

    async def call(_llm, *, operation, response_validator=None, **kwargs):
        if operation != 'chat_evidence_verifier':
            assert operation != 'chat_subject_revision'
            return draft
        items = stream_api.conditional_teaching_claims([{'type': 'answer', 'version_id': 'initial', 'content': draft}])
        reason = '示例2+2=5。' if not reviews else '示例2+2=4。'
        raw = json.dumps({'claims': [{'claim': draft, 'basis': 'worked_example', 'support': 'unsupported',
                                     'needs_revision': False}],
                          'conditionReview': [{'claimId': item['id'], 'status': 'valid', 'reason': reason, 'fix': ''}
                                              for item in items]}, ensure_ascii=False)
        reviews.append(raw)
        response_validator(raw)
        return raw

    monkeypatch.setattr(stream_api, 'audited_legacy_text_call', call)
    result = asyncio.run(stream_api._run_professional_evidence(_Swarm(_ProfessionalLLM()),
        {'user_message': SimpleNamespace(content='核对逐次加和。'), 'source_materials': []}, {}))
    assert len(reviews) == 2 and result['answer_revision'] is None
    attempts = result['calculation_review_attempts']
    assert attempts[0]['calculationFeedback'][0]['location'] == 'conditionReview[0]'
    assert attempts[1]['calculationFeedback'] == []


@pytest.mark.parametrize('preserve_original_in_claim,initial_support', [
    (False, 'unsupported'), (True, 'unsupported'), (True, 'supported'),
])
def test_conditions_are_located_from_each_current_draft_without_an_extra_model_stage(monkeypatch, preserve_original_in_claim, initial_support):
    from types import SimpleNamespace
    original = '不可省略的条件：整个分数条件分布必须保持不变。'
    corrected = '保持整个分数条件分布是充分条件，不是复用当前阈值TPR和FPR的必要条件。'
    operations, focused = [], []

    async def call(_llm, *, operation, user_prompt, response_validator=None, **kwargs):
        operations.append(operation)
        if operation == 'chat_subject_expert':
            return original + '\n```python\nprint("只有固定步长才成立")\n```'
        if operation == 'chat_challenger':
            return '应区分整个分布不变与当前决策区域的两个条件率不变。'
        if operation == 'chat_subject_revision':
            return corrected
        payload = user_prompt.split('条件表述定位（仅定位，不表示有错，仍以完整草稿上下文为准）：\n')[1]
        quotes = json.loads(payload.split('\n将其中实际采纳的专业结论')[0])
        focused.append(quotes)
        assert not any('print' in value or '固定步长' in value for value in quotes)
        is_revised = len(focused) == 2
        assert quotes == [corrected if is_revised else original]
        items = json.loads(user_prompt.split('\ncondition_claims：')[1].split('\n待核查的问题线索')[0].split('\n这是定向修订后的完整草稿')[0])
        raw = json.dumps({'claims': [{'claim': original if preserve_original_in_claim and not is_revised else corrected,
            'support': 'unsupported' if is_revised else initial_support,
            'basis': 'worked_example', 'needs_revision': preserve_original_in_claim and not is_revised,
            'review': {'verifier': '较弱的充分命题本身正确。', 'revision': ''}}],
            'conditionReview': [{'claimId': item['id'], 'status': 'valid' if is_revised else 'overstated',
                                 'reason': '充分不等于必要。', 'fix': '' if is_revised else corrected}
                                for item in items]}, ensure_ascii=False)
        if response_validator:
            response_validator(raw)
        return raw

    monkeypatch.setattr(stream_api, 'audited_legacy_text_call', call)
    result = asyncio.run(stream_api._run_professional_evidence(_Swarm(_ProfessionalLLM()),
        {'user_message': SimpleNamespace(content='核对指标复用的条件。'), 'source_materials': []}, {}))
    assert operations == ['chat_subject_expert', 'chat_challenger', 'chat_evidence_verifier',
                          'chat_subject_revision', 'chat_evidence_verifier']
    assert result['expert'] == corrected
    assert result['answer_revision']['claimsAfter'][0]['revisionNeeded'] is False
    assert result['answer_revision']['claimsBefore'][-1]['claim'] == original
    assert result['answer_revision']['claimsBefore'][-1]['revisionNeeded'] is True
    assert corrected in result['answer_revision']['claimsBefore'][-1]['review']['revision']
    assert len(result['answer_revision']['claimsBefore']) == (1 if preserve_original_in_claim else 2)


@pytest.mark.parametrize('kind,draft,has_conditions', [
    ('reasoning', '只有a=0和b=0同时成立，ab才为0。', True),
    ('reasoning', '训练误差从0.6降到了0.2。', False),
    ('lookup', '请保留本页标题“收敛的充分条件”。', True),
])
def test_conditions_reach_existing_challenger_without_slowing_the_verifier(monkeypatch, kind, draft, has_conditions):
    from types import SimpleNamespace
    selected, backends = [], []
    def select(backend, *, deep_reasoning, reasoning_effort=None):
        selected.append(deep_reasoning)
        value = SimpleNamespace(generate=lambda: None, deep=deep_reasoning, max_tokens=32768)
        backends.append(value)
        return value
    async def call(llm, *, operation, user_prompt, response_validator=None, **kwargs):
        if operation == 'chat_subject_expert': return draft
        if operation == 'chat_challenger':
            assert ('需要检查逻辑方向的原句' in user_prompt) is has_conditions
            assert draft in user_prompt
            if has_conditions:
                assert 'B⇒A' in user_prompt and '题设采用A' in user_prompt
                assert '一组充分条件未声称各项必要时不误判' in user_prompt
            return '检查当前原句。'
        assert llm.deep is False
        assert llm.max_tokens == 32768
        items = stream_api.conditional_teaching_claims([{'type': 'answer', 'version_id': 'initial', 'content': draft}])
        raw = json.dumps({'claims': [{'claim': draft, 'support': 'unsupported', 'basis': 'worked_example',
                                     'needs_revision': False}],
                          'conditionReview': [{'claimId': c['id'], 'status': 'valid', 'reason': '路由测试', 'fix': ''}
                                              for c in items]}, ensure_ascii=False)
        if response_validator: response_validator(raw)
        return raw
    monkeypatch.setattr(stream_api, 'for_answer_step', select)
    monkeypatch.setattr(stream_api, 'audited_legacy_text_call', call)
    result = asyncio.run(stream_api._run_professional_evidence(_Swarm(_ProfessionalLLM()),
        {'user_message': SimpleNamespace(content='核对讲解。'), 'source_materials': [], 'question_kind': kind}, {}))
    assert result['answer_revision'] is None
    assert selected == [kind == 'reasoning', False, False]
    assert all(backend.max_tokens == 32768 for backend in backends)


class _FailingProfessionalLLM(_ProfessionalLLM):
    async def generate(self, system_prompt, user_prompt, *, role):
        self.calls.append({"role": role, "system": system_prompt, "user": user_prompt})
        raise RuntimeError("provider unavailable")


class _InvalidVerifierLLM(_ProfessionalLLM):
    async def generate(self, system_prompt, user_prompt, *, role):
        if role == 'Evidence Verifier':
            return '以下是核对说明，但没有要求的结论清单。'
        return await super().generate(system_prompt, user_prompt, role=role)


class _IncorrectReviewLLM(_ProfessionalLLM):
    async def generate(self, system_prompt, user_prompt, *, role):
        if role == 'Evidence Verifier':
            return json.dumps({'claims': [{'claim': '当前结论需要检查。', 'support': 'unsupported',
                'review': {'verifier': '应改成5。'},
                'revision_calculations': [{'expression': '2+2', 'claimed_result': '5'}]}]})
        return await super().generate(system_prompt, user_prompt, role=role)


def _source_ref_id() -> str:
    with SessionLocal() as session:
        row = (
            session.query(DBSourceRef)
            .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
            .filter(DBSourceDocument.course_id == COURSE_ID)
            .first()
        )
        assert row is not None
        return row.id


def test_stopping_professional_stream_cancels_its_pending_model_chain(monkeypatch):
    llm = _ProfessionalLLM()
    monkeypatch.setattr(stream_api, "build_swarm_from_headers", lambda _headers: _Swarm(llm))
    cancelled = []

    async def pending_chain(*args, stage_callback, **kwargs):
        try:
            await stage_callback("subject_expert", "running", "等待合成测试回答", .2)
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    monkeypatch.setattr(stream_api, "_run_professional_chain", pending_chain)
    with TestClient(app) as client:
        username = _key("stream-cancel")
        headers = auth_headers(client, username)
        source_id = _source_ref_id()
        conversation = client.post("/api/v1/chat/conversations", headers=headers,
            json={"course_id": COURSE_ID, "title": "合成停止测试"}).json()
        created = client.post(f"/api/v1/chat/conversations/{conversation['id']}/messages", headers=headers,
            json={"content": "解释学习率过大时为什么会震荡。", "idempotency_key": _key("cancel-message"),
                  "context_refs": [{"courseId": COURSE_ID, "sourceRefId": source_id}]})
        assert created.status_code == 201, created.text
        with SessionLocal() as db:
            learner = db.query(DBUser).filter_by(username=username).one()
            db.expunge(learner)

        class Request:
            headers = {}
            async def json(self):
                return {"user_message_id": created.json()["userMessage"]["id"], "message": "ignored"}

        async def check_stop():
            response = await stream_api.stream_chat(Request(), learner)
            iterator = response.body_iterator
            async for frame in iterator:
                if "等待合成测试回答" in frame:
                    await iterator.aclose()
                    break
            assert cancelled == [True]

        asyncio.run(asyncio.wait_for(check_stop(), timeout=10))


@pytest.mark.parametrize('prior_content', ['', '旧的未完成讲解\n```python\npri'])
def test_professional_stream_runs_real_agent_stages_and_claim_projection(monkeypatch, prior_content) -> None:
    llm = _ProfessionalLLM()
    monkeypatch.setattr(stream_api, "build_swarm_from_headers", lambda _headers: _Swarm(llm))

    with TestClient(app) as client:
        source_ref_id = _source_ref_id()
        llm.source_ref_id = source_ref_id
        headers = auth_headers(client, _key("b35-professional"))
        conversation = client.post(
            "/api/v1/chat/conversations",
            headers=headers,
            json={"course_id": COURSE_ID, "title": "专业链"},
        )
        assert conversation.status_code == 201, conversation.text
        created = client.post(
            f"/api/v1/chat/conversations/{conversation.json()['id']}/messages",
            headers=headers,
            json={
                "content": "解释学习率过大时为什么会震荡。",
                "context_refs": [{"courseId": COURSE_ID, "sourceRefId": source_ref_id}],
                "idempotency_key": _key("message"),
            },
        )
        assert created.status_code == 201, created.text
        # The model is a deterministic fixture, but its quotation must now be
        # a real fragment from the exact frozen materials used by this run.
        from app.chat_api import load_stream_context
        from app.database import DBChatMessage
        with SessionLocal() as db:
            message = db.get(DBChatMessage, created.json()['userMessage']['id'])
            actor = db.query(DBUser).filter_by(public_id=message.owner_public_id).one()
            context = load_stream_context(db, actor, message.id)
            llm.frozen_quote = context['source_materials'][0]['quote'][:120]
            if prior_content:
                partial = db.get(DBChatMessage, created.json()['assistantMessage']['id'])
                partial.content = prior_content
                db.commit()
        response = client.post(
            "/api/stream/chat",
            headers=headers,
            json={"user_message_id": created.json()["userMessage"]["id"], "message": "ignored"},
        )
        assert response.status_code == 200, response.text
        parsed = _events(response.text)
        complete = next(data for name, data in parsed if name == "complete")
        run_events = complete["run_events"]
        event_types = [item["eventType"] for item in run_events]
        assert "source.bound" in event_types
        assert event_types.index("stage.started") < event_types.index("source.bound")
        roles = [item["role"] for item in llm.calls]
        assert len(roles) == 6
        assert sorted(roles[1:]) == sorted(["Subject Expert", "Challenger", "Evidence Verifier", "Pedagogical", "Synthesizer"])
        assert roles.index("Subject Expert") < roles.index("Synthesizer") < roles.index("Challenger") < roles.index("Evidence Verifier")
        assert roles.index("Pedagogical") < roles.index("Synthesizer")
        assert '学习伙伴' not in roles
        assert '你的输出会直接拼到末尾' not in next(c['user'] for c in llm.calls if c['role'] == 'Synthesizer')
        expected_answer = stream_api.teacher_text(llm.organized_answer)
        assert complete['content'] == expected_answer
        visible = ''
        for name, data in parsed:
            if name == 'chat_chunk':
                visible = data['content'] if data.get('replay') else visible + data['content']
        assert visible == expected_answer
        assert "source_ref_id = 'teaching-example'" in expected_answer
        assert llm.organized_answer in next(c['user'] for c in llm.calls if c['role'] == 'Evidence Verifier')
        restored = client.get(f"/api/v1/chat/conversations/{conversation.json()['id']}", headers=headers).json()
        assert next(m for m in restored['messages'] if m['id'] == complete['message_id'])['content'] == expected_answer
        from llm_client import requires_json_object
        assert requires_json_object(next(call['system'] for call in llm.calls if call['role'] == 'Evidence Verifier'))
        assert complete["message"]["orchestration"]["mode"] == "course_professional"
        assert complete["message"]["orchestration"]["groundingLevel"] == "A"
        claims = complete["message"]["claims"]
        assert claims[0]["support"] == "supported"
        assert claims[0]["sourceRefIds"] == [source_ref_id]
        claim_events = [item for item in run_events if item["eventType"] == "claim.checked"]
        assert len(claim_events) == 1
        assert claim_events[0]["stageId"] == "claim:claim-01"
        assert claim_events[0]["outputRefs"] == ["claim:claim-01", f"source:{source_ref_id}"]
        assert complete["message"]["runId"] == complete["run_id"]
        assert "system_prompt" not in response.text.lower()
        assert "reasoning_content" not in response.text.lower()


def test_course_without_materials_still_returns_general_answer_with_boundary_notice(monkeypatch) -> None:
    llm = _ProfessionalLLM()
    monkeypatch.setattr(stream_api, "build_swarm_from_headers", lambda _headers: _Swarm(llm))
    with TestClient(app) as client:
        headers = auth_headers(client, _key("b35-course-empty"))
        conversation = client.post(
            "/api/v1/chat/conversations",
            headers=headers,
            json={"course_id": COURSE_ID, "title": "课程资料不足"},
        ).json()
        created = client.post(
            f"/api/v1/chat/conversations/{conversation['id']}/messages",
            headers=headers,
            json={"content": "解释 Transformer 是什么", "idempotency_key": _key("message")},
        )
        response = client.post(
            "/api/stream/chat",
            headers=headers,
            json={"user_message_id": created.json()["userMessage"]["id"]},
        )
        assert response.status_code == 200, response.text
        complete = next(data for name, data in _events(response.text) if name == "complete")
        assert "当前没有找到能直接回答这道问题的课程材料" in complete["content"]
        assert complete["message"]["orchestration"]["groundingLevel"] == "C"


def test_high_risk_without_materials_exposes_insufficient_evidence_boundary(monkeypatch) -> None:
    llm = _ProfessionalLLM()
    monkeypatch.setattr(stream_api, "build_swarm_from_headers", lambda _headers: _Swarm(llm))
    with TestClient(app) as client:
        headers = auth_headers(client, _key("b35-course-risk"))
        conversation = client.post(
            "/api/v1/chat/conversations",
            headers=headers,
            json={"course_id": COURSE_ID, "title": "证据边界"},
        ).json()
        created = client.post(
            f"/api/v1/chat/conversations/{conversation['id']}/messages",
            headers=headers,
            json={
                "content": "请给出必须依据原文的精确规范条款",
                "idempotency_key": _key("message"),
            },
        )
        response = client.post(
            "/api/stream/chat",
            headers=headers,
            json={"user_message_id": created.json()["userMessage"]["id"]},
        )
        assert response.status_code == 200, response.text
        complete = next(data for name, data in _events(response.text) if name == "complete")
        assert "现有内容还不足以回答得很肯定" in complete["content"]
        assert complete["message"]["orchestration"]["groundingLevel"] == "D"


def test_explicit_general_qa_bypasses_course_debate_for_level_d_continue_action(monkeypatch) -> None:
    llm = _ProfessionalLLM()
    monkeypatch.setattr(stream_api, "build_swarm_from_headers", lambda _headers: _Swarm(llm))
    with TestClient(app) as client:
        source_ref_id = _source_ref_id()
        headers = auth_headers(client, _key("b35-general-qa"))
        conversation = client.post(
            "/api/v1/chat/conversations",
            headers=headers,
            json={"course_id": COURSE_ID, "title": "通用继续"},
        ).json()
        created = client.post(
            f"/api/v1/chat/conversations/{conversation['id']}/messages",
            headers=headers,
            json={
                "content": "请用通用知识继续解释 Transformer。",
                "intent": "general_qa",
                "context_refs": [{"courseId": COURSE_ID, "sourceRefId": source_ref_id}],
                "idempotency_key": _key("message"),
            },
        )
        assert created.status_code == 201, created.text
        response = client.post(
            "/api/stream/chat",
            headers=headers,
            json={"user_message_id": created.json()["userMessage"]["id"]},
        )
        assert response.status_code == 200, response.text
        complete = next(data for name, data in _events(response.text) if name == "complete")
        assert complete["message"]["orchestration"]["mode"] == "general"
        assert not any(call["role"] == "Subject Expert" for call in llm.calls)


def test_grounding_levels_keep_answerability_separate_from_course_evidence() -> None:
    class Message:
        content = "请解释一个概念"

    course_without_sources = {
        "context_snapshot": {"course_ids": ["course-a"]},
        "source_materials": [],
        "user_message": Message(),
    }
    assert stream_api._professional_grounding(course_without_sources)["level"] == "C"
    assert stream_api._professional_grounding(course_without_sources)["answerability"] == "answerable"

    high_risk = {
        **course_without_sources,
        "user_message": type("Message", (), {"content": "请给出必须依据原文的精确规范条款"})(),
    }
    classified = stream_api._professional_grounding(high_risk)
    assert classified["level"] == "D"
    assert classified["answerability"] == "needs_input"


def test_low_quality_and_changed_sources_are_classified_without_silent_refusal() -> None:
    class Message:
        content = "请解释这个课程概念"

    low_quality = stream_api._professional_grounding({
        "context_snapshot": {"course_ids": ["course-a"]},
        "source_materials": [{"sourceRefId": "source-a", "available": True, "quote": ""}],
        "user_message": Message(),
    })
    assert low_quality["level"] == "C"
    assert low_quality["answerability"] == "answerable"
    assert low_quality["quality_limited"]

    conflicted = stream_api._professional_grounding({
        "context_snapshot": {"course_ids": ["course-a"]},
        "source_materials": [{
            "sourceRefId": "source-a",
            "available": False,
            "reasonCode": "source_document_changed",
            "reason": "课程文档版本已变化",
        }],
        "user_message": Message(),
    })
    assert conflicted["level"] == "D"
    assert conflicted["conflicted"] is True
    assert conflicted["answerability"] == "answerable"
    mixed_conflict = stream_api._professional_grounding({
        "context_snapshot": {"course_ids": ["course-a"]},
        "source_materials": [
            {"sourceRefId": "source-good", "available": True, "quote": "可用片段"},
            {"sourceRefId": "source-old", "available": True, "quote": "旧片段", "reasonCode": "source_ref_version_changed"},
        ],
        "user_message": Message(),
    })
    assert mixed_conflict["level"] == "D"
    assert mixed_conflict["conflicted"] is True


def test_unrelated_chinese_question_does_not_match_generic_course_words() -> None:
    class Message:
        content = "请解释一个与本课程完全无关的量子物理概念"

    classified = stream_api._professional_grounding({
        "context_snapshot": {"course_ids": ["course-a"]},
        "source_materials": [{
            "sourceRefId": "source-a",
            "available": True,
            "title": "课程说明",
            "quote": "本课程介绍 RAG 检索、来源登记和证据边界。",
        }],
        "user_message": Message(),
    })

    assert classified["relevant"] == []
    assert classified["level"] == "C"
    assert classified["answerability"] == "answerable"


def test_short_chinese_subject_terms_match_relevant_course_materials() -> None:
    from types import SimpleNamespace
    classified = stream_api._professional_grounding({
        "context_snapshot": {"course_ids": ["course-ml"]},
        "source_materials": [{"available": True, "title": "监督学习",
                              "quote": "分类预测离散类别，回归预测连续数值。"}],
        "user_message": SimpleNamespace(content="请只用四句话解释分类和回归的区别，并举一个贴近我生活的例子。"),
    })
    assert classified["level"] == "A"
    assert len(classified["relevant"]) == 1


def test_only_levels_a_and_b_with_usable_sources_enter_professional_chain() -> None:
    assert stream_api._should_run_professional_chain({
        "level": "A",
        "course_ids": ["course-a"],
        "available": [{"sourceRefId": "source-a"}],
    }) is True
    assert stream_api._should_run_professional_chain({
        "level": "B",
        "course_ids": ["course-a"],
        "available": [{"sourceRefId": "source-a"}],
    }) is True
    for level in ("C", "D"):
        assert stream_api._should_run_professional_chain({
            "level": level,
            "course_ids": ["course-a"],
            "available": [{"sourceRefId": "source-a"}],
        }) is False
    assert stream_api._should_run_professional_chain({
        "level": "A",
        "course_ids": ["course-a"],
        "available": [],
    }) is False


def test_teaching_preparation_overlaps_evidence_checks_but_keeps_fact_dependencies(monkeypatch):
    from types import SimpleNamespace

    async def scenario():
        started = {name: asyncio.Event() for name in ("Subject Expert", "Pedagogical")}
        release = asyncio.Event()
        completed = []
        async def call(_llm, *, role, user_prompt, **kwargs):
            if role in started:
                started[role].set()
                await release.wait()
            if role == "Challenger":
                assert "Synthesizer" in completed
                assert '专家草稿：\nSynthesizer' in user_prompt
                assert '仅用于核对改写差异，不是课程证据或正确答案' in user_prompt
                assert '\nSubject Expert\n以上两稿都可能有错' in user_prompt
            if role == "Synthesizer":
                assert 'Subject Expert' in completed and 'Pedagogical' in completed
                assert '讲解安排：\nPedagogical' in user_prompt
                assert '当前页的附件与历史' in user_prompt
            if role == "Evidence Verifier":
                assert "Challenger" in completed
                assert '待核对的当前草稿：\nSynthesizer' in user_prompt
                assert '\nSubject Expert\n以上两稿都可能有错' in user_prompt
                assert '保留上题条件' in user_prompt and '图中标注' in user_prompt
            if role in {'Synthesizer', 'Challenger', 'Evidence Verifier'}:
                assert kwargs['images'] == ['synthetic-image-input']
            completed.append(role)
            return json.dumps({"claims": [{"claim": "可核对的结论", "support": "unsupported"}]}) if role == "Evidence Verifier" else role
        monkeypatch.setattr(stream_api, "audited_legacy_text_call", call)
        context = {"user_message": SimpleNamespace(content="简短解释"), "context_snapshot": {},
                   '_answer_user_prompt': '当前页的附件与历史', '_answer_images': ['synthetic-image-input'],
                   'history': [{'role': 'user', 'content': '保留上题条件'}],
                   'attachments': [{'filename': '合成图.png', 'parsed_text': '图中标注'}]}
        task = asyncio.create_task(stream_api._run_professional_chain(_Swarm(_ProfessionalLLM()), context, {}))
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started.values())), timeout=2)
        assert not completed
        release.set()
        result = await task
        assert result["pedagogy"] == "Pedagogical"
        assert result["claims"][0]["support"] == "unsupported"
    asyncio.run(scenario())


@pytest.mark.parametrize('second_review_correct', [True, False])
def test_incorrect_numeric_review_is_rechecked_before_synthesis(monkeypatch, second_review_correct):
    from types import SimpleNamespace
    calls = []
    async def call(_llm, *, role, user_prompt, response_validator=None, **kwargs):
        if role != 'Evidence Verifier':
            return '学生算例的损失为9，前提为只更新一次。'
        calls.append(user_prompt)
        value = '9' if len(calls) == 2 and second_review_correct else '0'
        output = json.dumps({'claims': [{
            'claim': '单步更新后损失不变。', 'support': 'unsupported',
            'review': {'verifier': f'新损失为{value}。'},
            'revision_calculations': [{'expression': '9*(1-18*(1/9))^2', 'claimed_result': value}],
        }]})
        response_validator(output)
        return output
    monkeypatch.setattr(stream_api, 'audited_legacy_text_call', call)
    context = {'user_message': SimpleNamespace(content='检查一次更新。'), 'source_materials': []}
    run = stream_api._run_professional_evidence(_Swarm(_ProfessionalLLM()), context, {})
    if second_review_correct:
        result = asyncio.run(run)
        assert len(result['calculation_review_attempts']) == 2
        assert result['claims'][0]['reviewCalculations'][0]['agrees']
        assert result['claims'][0]['support'] == 'unsupported'
    else:
        with pytest.raises(ValueError, match='计算和原文核对尚未完成'):
            asyncio.run(run)
    assert len(calls) == (2 if second_review_correct else 5)
    assert 'calculated' in calls[1] and '9.000' in calls[1]


def test_computed_answer_error_goes_to_revision_even_when_reviewer_says_supported(monkeypatch):
    from types import SimpleNamespace
    operations = []
    original = '总价为14。'
    corrected = '总价为15。'
    source = '总价等于单价乘以数量。'

    async def call(_llm, *, operation, user_prompt, response_validator=None, **kwargs):
        operations.append(operation)
        if operation == 'chat_subject_expert':
            return original
        if operation == 'chat_challenger':
            return '原计算正确。'
        if operation == 'chat_subject_revision':
            assert 'contradicted' in user_prompt and '15' in user_prompt
            return corrected
        revised = '这是定向修订后的完整草稿' in user_prompt
        raw = json.dumps({'claims': [{
            'claim': corrected if revised else original, 'support': 'supported',
            'source_ref_ids': ['price'], 'quote': source, 'location': '计算规则',
            'basis': 'worked_example', 'needs_revision': False,
            'calculations': [{'expression': '3*5', 'claimed_result': '15' if revised else '14'}],
            'review': {'verifier': '原计算正确。'},
        }]}, ensure_ascii=False)
        response_validator(raw)
        return raw

    monkeypatch.setattr(stream_api, 'audited_legacy_text_call', call)
    result = asyncio.run(stream_api._run_professional_evidence(_Swarm(_ProfessionalLLM()),
        {'user_message': SimpleNamespace(content='单价3，数量5，求总价。'), 'source_materials': [
            {'available': True, 'sourceRefId': 'price', 'quote': source, 'title': '总价'}]}, {}))
    assert operations == ['chat_subject_expert', 'chat_challenger', 'chat_evidence_verifier',
                          'chat_subject_revision', 'chat_evidence_verifier']
    assert result['expert'] == corrected
    before = result['answer_revision']['claimsBefore'][0]
    assert before['support'] == 'contradicted' and before['revisionNeeded']
    assert before['calculations'][0]['calculated'] == '15'
    assert result['claims'][0]['calculations'][0]['agrees']


@pytest.mark.parametrize('supply_missing', [True, False])
def test_missing_output_calculations_retry_the_review_without_rewriting_a_correct_answer(monkeypatch, supply_missing):
    from types import SimpleNamespace
    operations = []
    original = '实际输出为15、5。'
    source = '总价等于单价乘以数量，单价等于总价除以数量。'
    review_count = 0

    async def call(_llm, *, operation, user_prompt, response_validator=None, **kwargs):
        nonlocal review_count
        operations.append(operation)
        if operation == 'chat_subject_expert':
            return original
        if operation == 'chat_challenger':
            return '输出正确。'
        assert operation in {'chat_evidence_verifier', 'chat_evidence_verifier_local'}
        review_count += 1
        calculations = ([{'expression': '3*5', 'claimed_result': '15'},
                         {'expression': '15/3', 'claimed_result': '5'}]
                        if supply_missing and review_count == 2 else [])
        if review_count == 2:
            assert 'missingOutputCalculations' in user_prompt
        raw = json.dumps({'claims': [{
            'claim': original, 'support': 'supported', 'source_ref_ids': ['price'],
            'quote': source, 'location': '总价与单价', 'basis': 'worked_example', 'needs_revision': False,
            'calculations': calculations, 'review': {'verifier': '逐项手算一致。'},
        }]}, ensure_ascii=False)
        response_validator(raw)
        return raw

    monkeypatch.setattr(stream_api, 'audited_legacy_text_call', call)
    context = {'user_message': SimpleNamespace(content='单价5，数量3，打印总价和反算的单价。'),
               'source_materials': [{'available': True, 'sourceRefId': 'price', 'quote': source, 'title': '总价与单价'}]}
    run = stream_api._run_professional_evidence(_Swarm(_ProfessionalLLM()), context, {})
    if supply_missing:
        result = asyncio.run(run)
        assert result['expert'] == original and result['answer_revision'] is None
        assert len(result['claims'][0]['calculations']) == 2
        assert all(c['checked'] and c['agrees'] for c in result['claims'][0]['calculations'])
        history = result['calculation_review_attempts']
    else:
        with pytest.raises(stream_api.EvidenceReviewError) as caught:
            asyncio.run(run)
        history = caught.value.review_history
    assert history[0]['calculationFeedback'][0]['missingOutputCalculations'] == ['15', '5']
    assert operations == ['chat_subject_expert', 'chat_challenger', 'chat_evidence_verifier', 'chat_evidence_verifier'] + (
        [] if supply_missing else ['chat_evidence_verifier_local'] * 3)


@pytest.mark.parametrize('repair', ['quote', 'derivation', 'unresolved'])
def test_incomplete_reviewer_citation_retries_evidence_without_rewriting_correct_answer(monkeypatch, repair):
    from types import SimpleNamespace
    operations = []
    original = '总价是15。'
    source = '总价等于单价乘以数量。'

    async def call(_llm, *, operation, user_prompt, response_validator=None, **kwargs):
        operations.append(operation)
        if operation == 'chat_subject_expert': return original
        if operation == 'chat_challenger': return '计算正确。'
        assert operation in {'chat_evidence_verifier', 'chat_evidence_verifier_local'}
        second = operations.count(operation) == 2
        if second: assert 'citationFailures' in user_prompt
        item = {'claim': original, 'basis': 'worked_example', 'needs_revision': False,
                'support': 'supported', 'source_ref_ids': ['price'], 'quote': '',
                'calculations': [{'expression': '3*5', 'claimed_result': '15'}], 'review': '由题设计算正确。'}
        if second and repair == 'quote': item.update(quote=source, support='partially_supported')
        if second and repair == 'derivation': item.update(source_ref_ids=[], support='unsupported')
        raw = json.dumps({'claims': [item]}, ensure_ascii=False)
        response_validator(raw)
        return raw

    monkeypatch.setattr(stream_api, 'audited_legacy_text_call', call)
    run = stream_api._run_professional_evidence(_Swarm(_ProfessionalLLM()),
        {'user_message': SimpleNamespace(content='单价3，数量5，求总价。'), 'source_materials': [
            {'available': True, 'sourceRefId': 'price', 'quote': source, 'title': '总价'}]}, {})
    if repair == 'unresolved':
        with pytest.raises(stream_api.EvidenceReviewError) as caught: asyncio.run(run)
        history = caught.value.review_history
        assert len(history) == 8
        assert [row['repairStrategy'] for row in history if 'repairStrategy' in row] == [
            'local_correction', 'source_first', 'independent_calculation']
    else:
        result = asyncio.run(run)
        assert result['expert'] == original and result['answer_revision'] is None
        assert result['claims'][0]['quoteVerified'] is (repair == 'quote')
    assert operations == ['chat_subject_expert', 'chat_challenger', 'chat_evidence_verifier', 'chat_evidence_verifier'] + (
        ['chat_evidence_verifier_local'] * 3 if repair == 'unresolved' else [])


def test_confirming_wrong_output_in_claim_and_condition_goes_to_answer_repair(monkeypatch):
    from types import SimpleNamespace
    operations = []
    original = '实际输出：\n```text\n5.2500\n```'
    corrected = '实际输出：\n```text\n5.7500\n```'
    source = '加权均值按加权和除以总权重。'

    async def call(_llm, *, operation, user_prompt, response_validator=None, **kwargs):
        operations.append(operation)
        if operation == 'chat_subject_expert':
            return original
        if operation == 'chat_challenger':
            return '23/4=5.25，输出正确。'
        if operation == 'chat_subject_revision':
            assert 'contradicted' in user_prompt and '5.75' in user_prompt
            return corrected
        revised = '这是定向修订后的完整草稿' in user_prompt
        value = '5.7500' if revised else '5.2500'
        review = f'23/4={value}，与代码输出一致。'
        raw = json.dumps({'claims': [{
            'claim': f'实际输出为{value}。', 'support': 'supported', 'source_ref_ids': ['weighted'],
            'quote': source, 'location': '加权均值', 'basis': 'worked_example', 'needs_revision': False,
            'calculations': [{'expression': '(3*2+7+10)/(2+1+1)', 'claimed_result': value}],
            'review': review,
        }], 'conditionReview': [{'claimId': ('revised' if revised else 'initial') + ':content:output:0',
                                 'status': 'valid', 'reason': review, 'fix': ''}]}, ensure_ascii=False)
        response_validator(raw)
        return raw

    monkeypatch.setattr(stream_api, 'audited_legacy_text_call', call)
    result = asyncio.run(stream_api._run_professional_evidence(_Swarm(_ProfessionalLLM()),
        {'user_message': SimpleNamespace(content='计算加权均值，打印结果保留4位小数。'), 'source_materials': [
            {'available': True, 'sourceRefId': 'weighted', 'quote': source, 'title': '加权均值'}]}, {}))
    assert result['expert'] == corrected
    assert result['answer_revision']['claimsBefore'][0]['support'] == 'contradicted'
    assert operations == ['chat_subject_expert', 'chat_challenger', 'chat_evidence_verifier',
                          'chat_subject_revision', 'chat_evidence_verifier']


@pytest.mark.parametrize("kind", ["lookup", "explanation", "practice", "reasoning"])
def test_question_depth_applies_to_expert_without_repeating_deep_review(monkeypatch, kind):
    from types import SimpleNamespace
    from llm_client import AsyncOpenAIChatLLM

    original = AsyncOpenAIChatLLM(endpoint="https://test.invalid/chat", api_key="test",
                                 model="test", thinking_mode="max", reasoning_effort="max")
    modes = {}
    async def call(backend, *, role, **kwargs):
        modes[role] = backend.thinking_mode
        return json.dumps({"claims": [{"claim": "资料不足", "support": "unsupported"}]}) if role == "Evidence Verifier" else role
    monkeypatch.setattr(stream_api, "audited_legacy_text_call", call)
    context = {"user_message": SimpleNamespace(content="课程提问"), "question_kind": kind}
    result = asyncio.run(stream_api._run_professional_chain(_Swarm(original), context, {}))
    expected = "enabled" if kind in {"reasoning", "practice"} else "disabled"
    assert modes == {"Subject Expert": expected, "Challenger": "disabled",
                     "Evidence Verifier": "disabled", "Pedagogical": "disabled", "Synthesizer": "disabled"}
    assert result["model_stages_executed"] is True
    assert original.thinking_mode == "max"


def test_casual_question_does_not_send_course_material_or_schedule_to_answer_model(monkeypatch):
    llm = _ProfessionalLLM()
    monkeypatch.setattr(stream_api, "build_swarm_from_headers", lambda _headers: _Swarm(llm))
    async def classify(*args, **kwargs):
        return {"is_academic": True, "question_kind": "conversation"}
    monkeypatch.setattr(stream_api, "_classify_academic_intent", classify)
    with TestClient(app) as client:
        headers = auth_headers(client, _key("casual-scope"))
        conversation = client.post("/api/v1/chat/conversations", headers=headers,
                                   json={"course_id": COURSE_ID}).json()
        created = client.post(f"/api/v1/chat/conversations/{conversation['id']}/messages", headers=headers,
                              json={"content": "你好，用两句话鼓励我", "idempotency_key": _key("casual"),
                                    "context_refs": [{"courseId": COURSE_ID, "sourceRefId": _source_ref_id()}]}).json()
        response = client.post("/api/stream/chat", headers=headers,
                               json={"user_message_id": created["userMessage"]["id"]})
        complete = next(data for name, data in _events(response.text) if name == "complete")
        assert complete["message"]["orchestration"]["mode"] == "general"
        assert [call["role"] for call in llm.calls] == ["学习伙伴"]
        assert "你好，用两句话鼓励我" in llm.calls[0]["user"]
        assert "已验证来源" not in llm.calls[0]["user"]
        assert "本轮学习者画像适配" not in llm.calls[0]["user"]


@pytest.mark.parametrize("finish", ["stop", "evidence_failure"])
def test_parallel_teaching_is_cancelled_on_stop_or_evidence_failure(monkeypatch, finish):
    from types import SimpleNamespace

    async def scenario():
        started = {name: asyncio.Event() for name in ("Subject Expert", "Pedagogical")}
        closed = set()
        fail = asyncio.Event()
        async def call(_llm, *, role, **kwargs):
            started[role].set()
            try:
                if role == "Subject Expert" and finish == "evidence_failure":
                    await fail.wait()
                    raise RuntimeError("evidence unavailable")
                await asyncio.Event().wait()
            finally:
                closed.add(role)
        monkeypatch.setattr(stream_api, "audited_legacy_text_call", call)
        context = {"user_message": SimpleNamespace(content="停止后不继续计费"), "context_snapshot": {}}
        task = asyncio.create_task(stream_api._run_professional_chain(_Swarm(_ProfessionalLLM()), context, {}))
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started.values())), timeout=2)
        if finish == "stop":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            fail.set()
            with pytest.raises(RuntimeError, match="evidence unavailable"):
                await task
        assert closed == {"Subject Expert", "Pedagogical"}
    asyncio.run(scenario())


@pytest.mark.parametrize('model_class', [_FailingProfessionalLLM, _InvalidVerifierLLM, _IncorrectReviewLLM])
def test_professional_model_failure_is_persisted_and_retryable(monkeypatch, model_class) -> None:
    llm = model_class()
    monkeypatch.setattr(stream_api, "build_swarm_from_headers", lambda _headers: _Swarm(llm))
    with TestClient(app) as client:
        source_ref_id = _source_ref_id()
        headers = auth_headers(client, _key("b35-professional-failure"))
        conversation = client.post(
            "/api/v1/chat/conversations",
            headers=headers,
            json={"course_id": COURSE_ID, "title": "专业链失败"},
        ).json()
        created = client.post(
            f"/api/v1/chat/conversations/{conversation['id']}/messages",
            headers=headers,
            json={
                "content": "请严格依据课程资料解释。",
                "context_refs": [{"courseId": COURSE_ID, "sourceRefId": source_ref_id}],
                "idempotency_key": _key("message"),
            },
        )
        response = client.post(
            "/api/stream/chat",
            headers=headers,
            json={"user_message_id": created.json()["userMessage"]["id"]},
        )
        assert response.status_code == 200
        parsed = _events(response.text)
        error = next(data for name, data in parsed if name == "error")
        assert error["code"] == "chat_professional_chain_failed"
        assert any(item["eventType"] == "run.failed" for item in error["run_events"])
        stored = client.get(
            f"/api/v1/chat/conversations/{conversation['id']}", headers=headers
        ).json()
        assistant = stored["messages"][-1]
        assert assistant["status"] == "failed"
        assert assistant["failure"]["code"] == "chat_professional_chain_failed"
        if model_class is _IncorrectReviewLLM:
            history = assistant['streamCheckpoint']['claimReviewHistory']
            assert len(history) == 8
            checked = [row for row in history if 'calculationFeedback' in row]
            assert len(checked) == 5
            assert all(row['calculationFeedback'][0]['calculationChecks'][0]['calculated'] == '4' for row in checked)
            assert [row['repairStrategy'] for row in history if 'repairStrategy' in row] == [
                'local_correction', 'source_first', 'independent_calculation']
            assert not assistant['content']
        if model_class is _InvalidVerifierLLM:
            from app.database import DBModelCall
            with SessionLocal() as db:
                call = db.query(DBModelCall).filter_by(trace_id=f"{assistant['id']}:evidence_verifier").one()
                assert call.status == 'failed'
                assert call.error_code == 'chat_evidence_verifier_output_invalid'


@pytest.mark.parametrize("wrapper", ["single", "mapping", "list"])
def test_verifier_single_claim_keeps_evidence_checks_and_review(wrapper):
    claim = {"claim_id": "c3", "claim": "数组可逐元素乘以常量", "support": "supported",
             "source_ref_ids": ["source-a"], "quote": "np.eye(4) * 7", "location": "数组创建示例",
             "confidence": "high", "review": "同类机制有依据，具体数值仍需计算核验。"}
    body = claim if wrapper == "single" else {"claims": claim if wrapper == "mapping" else [claim]}
    raw = json.dumps(body, ensure_ascii=False)
    stream_api._validate_verifier_output(raw)
    result = stream_api._normalize_claims(raw, [{"available": True, "sourceRefId": "source-a", "quote": "np.eye(4) * 7"}])[0]
    assert result["claimId"] == "c3" and result["support"] == "supported"
    assert result["review"]["verifier"] == claim["review"]
    assert result["confidence"] == 0.0  # Do not invent a numeric certainty.
    assert stream_api._normalize_claims(raw, [])[0]["support"] == "unsupported"
    with pytest.raises(ValueError):
        stream_api._validate_verifier_output(json.dumps({"claim": "未核对完"}))


def test_claim_projection_rejects_unknown_sources_and_invalid_support_states() -> None:
    claims = stream_api._normalize_claims(
        json.dumps({
            "claims": [{
                "claim_id": "c1",
                "claim": "结论",
                "support": "invented",
                "source_ref_ids": ["not-allowed"],
                "confidence": 2,
            }]
        }),
        [{"sourceRefId": "source-1", "available": True}],
    )
    assert claims[0]["support"] == "unsupported"
    assert claims[0]["sourceRefIds"] == []
    assert claims[0]["confidence"] == 1.0


def test_claim_projection_requires_real_quote_and_derives_location_from_frozen_material() -> None:
    materials = [{
        "sourceRefId": "source-1",
        "available": True,
        "title": "课程资料",
        "quote": "课程原文片段",
        "locationLabel": "已知原文位置",
    }]
    raw = json.dumps({
        "claims": [
            {
                "claim_id": "missing-quote",
                "claim": "缺少原文引文的结论",
                "support": "supported",
                "source_ref_ids": ["source-1"],
                "location": "第 1 页",
                "confidence": 0.9,
                "review": {"revision": "模型备注"},
            },
            {
                "claim_id": "missing-location",
                "claim": "缺少位置的部分结论",
                "support": "partially_supported",
                "source_ref_ids": ["source-1"],
                "quote": "课程原文片段",
                "confidence": 0.8,
            },
            {
                "claim_id": "complete",
                "claim": "证据完整的结论",
                "support": "supported",
                "source_ref_ids": ["source-1"],
                "quote": "课程原文片段",
                "location": "第 2 页",
                "confidence": 0.95,
            },
        ]
    }, ensure_ascii=False)

    claims = stream_api._normalize_claims(raw, materials)

    assert [claim["support"] for claim in claims] == [
        "unsupported",
        "partially_supported",
        "supported",
    ]
    assert claims[0]["sourceRefIds"] == ["source-1"]
    assert claims[1]["sourceRefIds"] == ["source-1"]
    assert claims[2]["sourceRefIds"] == ["source-1"]
    assert "未能在本次课程资料中完整找到" in claims[0]["review"]["revision"]
    assert "模型备注" in claims[0]["review"]["revision"]
    assert claims[1]["location"] == "已知原文位置"
    assert claims[1]["quoteVerified"]
    assert claims[2]["review"]["revision"] == ""


def test_claim_projection_downgrades_claims_bound_to_unavailable_sources() -> None:
    claims = stream_api._normalize_claims(
        json.dumps({
            "claims": [{
                "claim_id": "unavailable-source",
                "claim": "来源已撤回的结论",
                "support": "contradicted",
                "source_ref_ids": ["source-1"],
                "quote": "旧版本原文",
                "location": "第 3 页",
                "confidence": 0.7,
            }]
        }, ensure_ascii=False),
        [{"sourceRefId": "source-1", "available": False}],
    )

    assert claims[0]["support"] == "unsupported"
    assert claims[0]["sourceRefIds"] == []
    assert "未能在本次课程资料中完整找到" in claims[0]["review"]["revision"]


def test_claim_source_labels_resolve_only_to_the_exact_available_frozen_materials():
    materials = [
        {"sourceRefId": "resource:video-v1", "available": True, "quote": "条件筛选视频", "title": "视频"},
        {"sourceRefId": "source-withdrawn", "available": False, "quote": "旧内容"},
        {"source_ref_id": "source-course", "available": True, "quote": "数组筛选"},
    ]
    evidence = stream_api._evidence_prompt_context(materials)
    assert "source_ref_id: resource:video-v1" in evidence
    assert "source_ref_id: source-course" in evidence
    claims = stream_api._normalize_claims(json.dumps({"claims": [
        {"claim": "当前视频标题", "support": "supported", "source_ref_ids": ["S1", "[S1]"],
         "quote": "条件筛选视频", "location": "当前选择"},
        {"claim": "课程说明", "support": "supported", "source_ref_ids": ["[S3]"],
         "quote": "数组筛选", "location": "数组章节"},
        {"claim": "已撤回内容", "support": "supported", "source_ref_ids": ["S2", "S99"],
         "quote": "旧内容", "location": "旧章节"},
        {"claim": "没有引文", "support": "supported", "source_ref_ids": ["S1"], "location": "当前选择"},
    ]}, ensure_ascii=False), materials)
    assert claims[0]["sourceRefIds"] == ["resource:video-v1"]
    assert claims[0]["support"] == "supported"
    assert claims[1]["sourceRefIds"] == ["source-course"]
    assert claims[1]["support"] == "supported"
    assert claims[2]["sourceRefIds"] == [] and claims[2]["support"] == "unsupported"
    assert claims[3]["support"] == "unsupported"


def test_resource_qa_freezes_selected_version_and_publishes_checked_code(monkeypatch):
    import hashlib
    from app.database import DBArtifact, DBArtifactVersion, DBUser
    from app.chat_api import load_stream_context

    code = "```python\ndef risk_score(t, v):\n    return t + 100 * v\nprint(risk_score(39.8, 0.41))\n```"
    class CodeLLM(_ProfessionalLLM):
        async def generate(self, system_prompt, user_prompt, *, role):
            if role in {'Subject Expert', 'Synthesizer', 'Evidence Verifier'}:
                self.calls.append({'role': role, 'system': system_prompt, 'user': user_prompt})
                if role == 'Evidence Verifier':
                    return json.dumps({'claims': [{'claim': '风险按温度加一百倍振动计算。',
                        'support': 'unsupported', 'basis': 'worked_example', 'needs_revision': False}]})
                return code
            return await super().generate(system_prompt, user_prompt, role=role)
        async def generate_stream(self, system_prompt, user_prompt, *, role, images):
            self.calls.append({"role": role, "system": system_prompt, "user": user_prompt})
            for char in code:
                yield char
    llm = CodeLLM()
    monkeypatch.setattr(stream_api, "build_swarm_from_headers", lambda _headers: _Swarm(llm))
    username = _key("resource-version-chat")
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        llm.source_ref_id = _source_ref_id()
        with SessionLocal() as db:
            user = db.query(DBUser).filter_by(username=username).one()
            resource = DBArtifact(owner_public_id=user.public_id, course_id=COURSE_ID,
                                  artifact_type="deck", title="传感器风险练习", status="published")
            db.add(resource); db.flush()
            versions = []
            for number, formula in [(1, "temperature + 100 * vibration"), (2, "unrelated later revision")]:
                body = json.dumps({"slides": [{"id": "slide-filter", "title": "先过滤缺失",
                    "body": formula}]}, ensure_ascii=False)
                version = DBArtifactVersion(artifact_id=resource.id, version_number=number,
                    content=body, content_hash=hashlib.sha256(body.encode()).hexdigest())
                db.add(version); db.flush(); versions.append(version.id)
            resource.current_version_id = versions[1]
            db.commit(); resource_id = resource.id
        conversation = client.post("/api/v1/chat/conversations", headers=headers,
                                   json={"course_id": COURSE_ID}).json()
        context = {"courseId": COURSE_ID, "resourceId": resource_id,
                   "resourceVersionId": versions[0], "resourcePartId": "slide-filter"}
        created = client.post(f"/api/v1/chat/conversations/{conversation['id']}/messages",
            headers=headers, json={"content": "说明这一页的公式", "context_refs": [context],
                                   "idempotency_key": _key("question")})
        assert created.status_code == 201, created.text
        with SessionLocal() as db:
            user = db.query(DBUser).filter_by(username=username).one()
            frozen = load_stream_context(db, user, created.json()["userMessage"]["id"])
            material = next(x for x in frozen["source_materials"] if x["kind"] == "resource_version")
            assert material["versionId"] == versions[0]
            assert "temperature + 100 * vibration" in material["quote"]
            assert "unrelated later revision" not in material["quote"]
            assert frozen["context_snapshot"]["resource_versions"][0]["version_id"] == versions[0]
        response = client.post("/api/stream/chat", headers=headers,
                               json={"user_message_id": created.json()["userMessage"]["id"]})
        complete = next(data for name, data in _events(response.text) if name == "complete")
        assert complete["content"] == code
        assert "temperature + 100 * vibration" in llm.calls[-1]["user"]
        replayed = ""
        for event, data in _events(response.text):
            if event == "chat_chunk":
                replayed = data["content"] if data.get("replay") else replayed + data["content"]
        assert replayed == code
        bad = client.post(f"/api/v1/chat/conversations/{conversation['id']}/messages", headers=headers,
            json={"content": "说明", "context_refs": [{**context, "resourcePartId": "absent"}],
                  "idempotency_key": _key("bad-part")})
        assert bad.status_code == 409


def test_bundle_question_keeps_all_nine_selected_versions_in_context():
    import hashlib
    from app.database import DBArtifact, DBArtifactVersion, DBUser
    from app.chat_api import load_stream_context

    username = _key('nine-resource-qa')
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        refs = []
        with SessionLocal() as db:
            user = db.query(DBUser).filter_by(username=username).one()
            for index in range(9):
                artifact = DBArtifact(owner_public_id=user.public_id, course_id=COURSE_ID,
                    artifact_type='handout', title=f'测试学习材料{index+1}', status='published')
                db.add(artifact); db.flush()
                versions = []
                for number, content in [(1, f'本次资料的独有内容{index+1}'), (2, '后续编辑，不能替换本次所选版本')]:
                    version = DBArtifactVersion(artifact_id=artifact.id, version_number=number,
                        content=content, content_hash=hashlib.sha256(content.encode()).hexdigest())
                    db.add(version); db.flush(); versions.append(version.id)
                artifact.current_version_id = versions[1]
                refs.append({'courseId': COURSE_ID, 'resourceId': artifact.id, 'resourceVersionId': versions[0]})
            db.commit()
        conversation = client.post('/api/v1/chat/conversations', headers=headers,
            json={'course_id': COURSE_ID}).json()
        response = client.post(f"/api/v1/chat/conversations/{conversation['id']}/messages", headers=headers,
            json={'content': '比较本次九份资料', 'context_refs': refs, 'idempotency_key': _key('nine-materials')})
        assert response.status_code == 201, response.text
        with SessionLocal() as db:
            user = db.query(DBUser).filter_by(username=username).one()
            context = load_stream_context(db, user, response.json()['userMessage']['id'])
            materials = [r for r in context['source_materials'] if r['kind'] == 'resource_version']
            assert len(materials) == 9
            assert {r['versionId'] for r in materials} == {r['resourceVersionId'] for r in refs}
            assert all('后续编辑' not in r['quote'] for r in materials)
            assert any('独有内容9' in r['quote'] for r in materials)


def test_video_qa_freezes_selected_recommendation_and_returns_to_same_video():
    from app.database import DBArtifact, DBArtifactVersion
    from app.chat_api import load_stream_context
    from urllib.parse import urlparse, parse_qs

    username = _key("selected-video")
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        with SessionLocal() as db:
            user = db.query(DBUser).filter_by(username=username).one()
            resource = DBArtifact(owner_public_id=user.public_id, course_id=COURSE_ID,
                                  artifact_type="video", title="数组学习视频", status="published")
            db.add(resource); db.flush()
            content = json.dumps({"recommendations": [
                {"id": "first-video", "title": "数组创建", "segments": [{"id": "intro", "title": "创建数组"}]},
                {"id": "second-video", "title": "条件筛选", "segments": [{"id": "intro", "title": "保留记录号"}],
                 "alternatives": [{"id": "replacement-video", "title": "替代课程讲解", "url": "https://example.edu/video", "reason": "同主题的另一种讲法"}]},
            ]}, ensure_ascii=False)
            version = DBArtifactVersion(artifact_id=resource.id, version_number=1,
                                        content=content, content_hash="a" * 64, content_format="json")
            db.add(version); db.flush()
            resource.current_version_id = version.id
            db.commit(); resource_id, version_id = resource.id, version.id
        conversation = client.post("/api/v1/chat/conversations", headers=headers,
                                   json={"course_id": COURSE_ID}).json()
        created = client.post(f"/api/v1/chat/conversations/{conversation['id']}/messages",
            headers=headers, json={"content": "我选中的是哪条视频？", "context_refs": [{
                "courseId": COURSE_ID, "resourceId": resource_id,
                "resourceVersionId": version_id, "resourcePartId": "second-video", "resourceSegmentId": "intro",
            }], "idempotency_key": _key("video-question")})
        assert created.status_code == 201, created.text
        with SessionLocal() as db:
            user = db.query(DBUser).filter_by(username=username).one()
            frozen = load_stream_context(db, user, created.json()["userMessage"]["id"])
            material = next(x for x in frozen["source_materials"] if x["kind"] == "resource_version")
            focus = material["quote"].split("本次材料全文：")[0]
            assert "条件筛选" in focus and "数组创建" not in focus
            assert "保留记录号" in focus and "创建数组" not in focus
            assert "没有提供实际画面或完整字幕" in focus
            assert '"id":' not in material["quote"]
            assert '"intro"' not in material["quote"]
            assert '标题：保留记录号' in focus
            assert 'segments' not in material["quote"]
            assert material["resourcePartId"] == "second-video"
            assert parse_qs(urlparse(material["route"]).query)["recommendation_id"] == ["second-video"]
            assert parse_qs(urlparse(material["route"]).query)["segment_id"] == ["intro"]
        invalid = client.post(f"/api/v1/chat/conversations/{conversation['id']}/messages", headers=headers,
            json={"content": "讲解", "context_refs": [{"courseId": COURSE_ID, "resourceId": resource_id,
                "resourceVersionId": version_id, "resourcePartId": "second-video", "resourceSegmentId": "absent"}],
                "idempotency_key": _key("invalid-video-segment")})
        assert invalid.status_code == 409
        replacement = client.post(f"/api/v1/chat/conversations/{conversation['id']}/messages", headers=headers,
            json={"content": "现在看的替代视频是什么？", "context_refs": [{"courseId": COURSE_ID, "resourceId": resource_id,
                "resourceVersionId": version_id, "resourcePartId": "replacement-video"}],
                "idempotency_key": _key("replacement-video-question")})
        assert replacement.status_code == 201
        with SessionLocal() as db:
            user = db.query(DBUser).filter_by(username=username).one()
            frozen = load_stream_context(db, user, replacement.json()['userMessage']['id'])
            material = next(x for x in frozen['source_materials'] if x['kind'] == 'resource_version')
            focus = material['quote'].split('本次材料全文：')[0]
            assert '标题：替代课程讲解' in focus and '标题：条件筛选' not in focus
            route = parse_qs(urlparse(material['route']).query)
            assert route['recommendation_id'] == ['second-video']
            assert route['alternative_id'] == ['replacement-video']
