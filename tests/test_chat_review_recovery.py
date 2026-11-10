import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from app.chat_review_recovery import repair_review_fields
from app.claim_evidence import quotation_review_feedback


def test_local_repair_preserves_passed_claims_and_checks_each_original_quote():
    materials = [{'available': True, 'sourceRefId': 'source', 'quote': '训练用于拟合。验证用于选择。测试用于评价。'}]
    claims = [{'claim_id': str(index), 'claim': text, 'basis': 'source', 'support': 'supported', 'needs_revision': False,
               'quote': text if index == 0 else '拼接且不存在的引文', 'source_ref_ids': ['source']}
              for index,text in enumerate(['训练用于拟合。','验证用于选择。','测试用于评价。'])]
    original = deepcopy(claims)
    feedback = []
    history = []
    calls = []

    def validate(raw):
        nonlocal feedback
        parsed = json.loads(raw)
        assert parsed['claims'][0] == original[0]
        feedback = quotation_review_feedback(parsed['claims'], materials)
        if feedback:
            raise ValueError('引文不匹配')

    raw=json.dumps({'claims':claims})
    with pytest.raises(ValueError): validate(raw)

    async def generate(request, validator):
        item=deepcopy(request['item']); calls.append(item['claim_id'])
        item['quote']=item['claim']
        result=json.dumps({'claims':[item]})
        validator(result)
        return result

    result=asyncio.run(repair_review_fields(raw, parse=json.loads, validate=validate,
        latest_feedback=lambda:feedback, generate=generate, history=history))
    repaired=json.loads(result)
    assert calls == ['1','2']
    assert repaired['claims'][0] == original[0]
    assert [c['claim'] for c in repaired['claims']] == [c['claim'] for c in original]
    assert not feedback and history


def test_unchanged_invalid_patch_changes_method_then_stops_without_approval():
    row={'claim':'原命题','quote':'错误引文'}
    feedback=[{'claim':'原命题','citationFailures':['quote_not_in_frozen_source']}]
    strategies=[];history=[]
    def validate(raw): raise ValueError('原文仍不匹配')
    async def generate(request, validator):
        strategies.append(request['strategy'])
        raw=json.dumps({'claims':[request['item']]});validator(raw);return raw
    with pytest.raises(ValueError,match='同一核验问题仍未改变'):
        asyncio.run(repair_review_fields(json.dumps({'claims':[row]}),parse=json.loads,
            validate=validate,latest_feedback=lambda:feedback,generate=generate,history=history))
    assert strategies == ['local_correction','source_first','independent_calculation']


def test_patch_cannot_omit_or_weaken_the_original_claim():
    feedback=[{'claim':'所有样本均满足条件','citationFailures':['quote_not_in_frozen_source']}]
    def validate(raw): raise AssertionError('Changed claim must not reach semantic validation')
    async def generate(request,validator):
        raw=json.dumps({'claims':[{'claim':'部分样本满足条件'}]});validator(raw);return raw
    with pytest.raises(ValueError,match='同一核验问题仍未改变'):
        asyncio.run(repair_review_fields(json.dumps({'claims':[{'claim':feedback[0]['claim']}]}),
            parse=json.loads,validate=validate,latest_feedback=lambda:feedback,generate=generate,history=[]))


def test_professional_answer_recovers_a_review_field_after_whole_review_attempts(monkeypatch):
    import stream_api
    draft='训练用于拟合。验证用于选择。'
    context={'user_message':SimpleNamespace(content='说明训练与验证的用途。'),
        'assistant_message':SimpleNamespace(id='local-repair-message',content='',stream_checkpoint={
            'answerRevision':{'after':draft,'decision':'unverified'}}),
        'source_materials':[{'available':True,'sourceRefId':'source','quote':draft}]}
    good={'claim_id':'good','claim':'训练用于拟合。','basis':'source','support':'supported',
          'source_ref_ids':['source'],'quote':'训练用于拟合。','needs_revision':False}
    bad={'claim_id':'bad','claim':'验证用于选择。','basis':'source','support':'supported',
         'source_ref_ids':['source'],'quote':'验证永远只用于选择。','needs_revision':False}
    calls=[]
    async def call(backend,*,operation,response_validator=None,**kwargs):
        calls.append(operation)
        if operation=='chat_challenger': return '核对实际原文。'
        if operation=='chat_evidence_verifier_local':
            result={'claims':[{**bad,'quote':'验证用于选择。'}]}
        else:
            assert operation=='chat_evidence_verifier'
            result={'claims':[good,bad]}
        raw=json.dumps(result,ensure_ascii=False)
        if response_validator: response_validator(raw)
        return raw
    monkeypatch.setattr(stream_api,'audited_legacy_text_call',call)
    monkeypatch.setattr(stream_api,'for_answer_step',lambda llm,**kwargs:llm)
    result=asyncio.run(stream_api._run_professional_chain(
        SimpleNamespace(llm=SimpleNamespace(generate=lambda:None)),context,{}))
    assert result['expert']==draft
    assert calls==['chat_challenger','chat_evidence_verifier','chat_evidence_verifier','chat_evidence_verifier_local']
    assert len(result['claims'])==2 and all(claim['quoteVerified'] for claim in result['claims'])
