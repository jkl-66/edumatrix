import asyncio
import json
from types import SimpleNamespace

import pytest
import stream_api


@pytest.mark.parametrize('reject', [False, True, 'invalid_first'])
def test_recovery_reuses_draft_but_checks_it_against_current_sources(monkeypatch, reject):
    calls = []
    draft = '旧稿中需要重新核对的完整内容。'
    context = {
        'user_message': SimpleNamespace(content='回答当前问题。'),
        'assistant_message': SimpleNamespace(id='same-message', content='', stream_checkpoint={
            'answerRevisionHistory': [{'revision': {'after': draft, 'decision': 'unverified'}}]}),
        'source_materials': [{'available': True, 'sourceRefId': 'current-ref', 'quote': '当前课程证据。'}],
    }

    async def call(llm, *, operation, user_prompt, response_validator=None, **kwargs):
        calls.append(operation)
        assert draft in user_prompt and '当前课程证据。' in user_prompt
        assert operation in {'chat_challenger', 'chat_evidence_verifier'}
        if operation == 'chat_challenger':
            return '依据当前课程重新核对。'
        if reject is True:
            raise RuntimeError('connection interrupted')
        if reject == 'invalid_first' and calls.count('chat_evidence_verifier') == 1:
            response_validator('{"claims": []}')
        raw = json.dumps({'claims': [{'claim': draft, 'basis': 'worked_example',
            'support': 'unsupported', 'needs_revision': False, 'source_ref_ids': [], 'quote': ''}]})
        if response_validator:
            response_validator(raw)
        return raw

    monkeypatch.setattr(stream_api, 'audited_legacy_text_call', call)
    monkeypatch.setattr(stream_api, 'for_answer_step', lambda llm, **kwargs: llm)
    swarm = SimpleNamespace(llm=SimpleNamespace(generate=lambda: None))
    if reject is True:
        with pytest.raises(stream_api.EvidenceReviewError) as error:
            asyncio.run(stream_api._run_professional_chain(swarm, context, {}))
        assert error.value.answer_revision['after'] == draft
        assert error.value.answer_revision['decision'] == 'unverified'
    else:
        result = asyncio.run(stream_api._run_professional_chain(swarm, context, {}))
        assert result['expert'] == draft
        if reject == 'invalid_first':
            history = result['calculation_review_attempts']
            assert history[0]['rawReview'] == '{"claims": []}'
            assert history[0]['validationFeedback']
    assert calls == ['chat_challenger', 'chat_evidence_verifier'] + (
        ['chat_evidence_verifier'] if reject == 'invalid_first' else [])


@pytest.mark.parametrize('content,decision', [('already published', 'unverified'), ('', 'verified')])
def test_published_answer_or_completed_review_is_not_resumed_as_failed_draft(content, decision):
    message = SimpleNamespace(content=content, stream_checkpoint={
        'answerRevision': {'after': 'draft', 'decision': decision}})
    assert stream_api._professional_resume_draft({'assistant_message': message}) == ''


@pytest.mark.parametrize('actual_error', [False, True])
def test_review_cannot_attribute_its_own_wrong_exercise_answer_to_draft(actual_error):
    from app.claim_evidence import calculation_review_feedback
    item = {'claim': 'C的MSE为1.6666666667。', 'basis': 'worked_example',
            'support': 'contradicted', 'needs_revision': True,
            'calculations': [{'expression': '((2-1)^2+(4-3)^2+(6-5)^2)/3',
                              'claimed_result': '1.6666666667'}]}
    draft = ('C的MSE为1.6666666667。' if actual_error
             else '独立练习：真实值[2,4,6]，预测值[1,3,5]。计算均方误差并说明。')
    feedback = calculation_review_feedback([item], [], draft=draft)
    assert bool(feedback) is (not actual_error)
    if feedback:
        assert feedback[0]['unstatedErroneousResults'] == ['1.6666666667']


def test_unfixed_incomplete_learning_task_is_not_published_as_source_qualification(monkeypatch):
    context = {
        'user_message': SimpleNamespace(content='设计一个有完整数据的独立练习。'),
        'assistant_message': SimpleNamespace(id='same-message', content='', stream_checkpoint={
            'answerRevision': {'after': '请等提供数据后再计算。', 'decision': 'unverified'}}),
        'source_materials': [{'available': True, 'sourceRefId': 'ref', 'quote': '均方误差。'}],
    }
    async def call(llm, *, operation, response_validator=None, **kwargs):
        if operation == 'chat_challenger':
            return '练习没有可计算的数据。'
        if operation == 'chat_subject_revision':
            return '仍需补充练习数据。'
        raw = json.dumps({'claims': [{'claim': '练习缺少数据，不能完成。',
            'basis': 'worked_example', 'support': 'unsupported', 'needs_revision': True,
            'source_ref_ids': [], 'quote': '', 'review': {'revision': '提供完整练习数据。'}}]})
        if response_validator:
            response_validator(raw)
        return raw
    monkeypatch.setattr(stream_api, 'audited_legacy_text_call', call)
    monkeypatch.setattr(stream_api, 'for_answer_step', lambda llm, **kwargs: llm)
    with pytest.raises(stream_api.EvidenceReviewError) as error:
        asyncio.run(stream_api._run_professional_chain(
            SimpleNamespace(llm=SimpleNamespace(generate=lambda: None, max_tokens=32768)), context, {}))
    assert error.value.answer_revision['after'] == '仍需补充练习数据。'
    assert error.value.answer_revision['decision'] == 'rejected'
