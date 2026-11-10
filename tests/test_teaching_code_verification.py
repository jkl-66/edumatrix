import asyncio
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from app import code_sandbox
from app.teaching_code_verification import verify_teaching_code, compare_output, output_claim_executed


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setattr(code_sandbox, 'CONFIG', replace(code_sandbox.CONFIG,
        sandbox_mode='trusted_local', sandbox_timeout=10))
    monkeypatch.setenv('EDUMATRIX_ENV', 'development')


def test_real_execution_detects_invented_output_and_reuses_unchanged_code(runtime):
    async def run():
        cache = {}
        draft = '```python\nx = [1, 2, 3]\nprint("mean:", sum(x)/len(x))\n```\n输出：\n```text\nmean: 0.02\n```'
        first = await verify_teaching_code(draft, cache=cache, owner='test', course_id=None)
        second = await verify_teaching_code(draft.replace('mean: 0.02', 'mean: 2.0'),
            cache=cache, owner='test', course_id=None)
        assert first[0]['status'] == 'success' and first[0]['matches'] is False
        assert second[0]['matches'] is True and second[0]['cached']
        assert len(cache) == 1
    asyncio.run(run())


@pytest.mark.parametrize('expected,actual,result', [
    ('MSE: 0.114', 'MSE: 0.11393703471260572', True),
    ('MSE: 0.020000000000000018', 'MSE: 0.11393703471260572', False),
    ('rank: 8', 'rank: 9', False),
    ('count: 10000000000', 'count: 10000000001', False),
    ('mean: 1', 'loss: 2', None),
    ('1 ... 3', '1 2 3', None),
])
def test_precision_and_correspondence(expected, actual, result):
    assert compare_output(expected, actual) is result


def test_full_output_claim_reuses_execution_but_a_number_or_different_claim_does_not():
    records=[{'matches':True,'expected':'0.25 -1.5 2.3\n0.0 -2.0 2.4'}]
    assert output_claim_executed('程序输出为：0.25 -1.5 2.3 与 0.0 -2.0 2.4。', records)
    assert output_claim_executed('代码输出块为：0.25 -1.5 2.3 与 0.0 -2.0 2.4。', records)
    assert output_claim_executed('```text\n0.25 -1.5 2.3\n0.0 -2.0 2.4\n```', records)
    assert not output_claim_executed('程序输出为0.25。', records)
    assert not output_claim_executed('0.25 -1.5 2.4 与 0.0 -2.0 2.3', records)
    assert not output_claim_executed('同一输出说明任何优化器均等价。', records)


def test_fragments_random_output_and_disabled_runtime_do_not_become_false_defects(runtime, monkeypatch):
    async def run():
        for code in ['x = ...\nprint(x)', 'x = input()\nprint(x)']:
            assert await verify_teaching_code(f'```python\n{code}\n```\n输出\n```text\n3\n```',
                cache={}, owner='test', course_id=None) == []
        random = await verify_teaching_code('```python\nimport random\nprint(random.random())\n```\n输出\n```text\n0.1\n```',
            cache={}, owner='test', course_id=None)
        assert random[0]['status'] == 'success' and random[0]['matches'] is None
        fragment = await verify_teaching_code('```python\nprint(previous_x)\n```\n输出\n```text\n3\n```',
            cache={}, owner='test', course_id=None)
        assert fragment[0]['status'] == 'runtime_error' and fragment[0]['matches'] is None
    asyncio.run(run())
    monkeypatch.setenv('EDUMATRIX_ENV', 'production')
    assert asyncio.run(verify_teaching_code('```python\nprint(3)\n```\n输出\n```text\n3\n```',
        cache={}, owner='test', course_id=None)) == []


@pytest.mark.parametrize('correct_revision', [True, False])
def test_overlooked_output_error_drives_local_revision_and_checks_revised_output(runtime, monkeypatch, correct_revision):
    import stream_api
    original = '```python\nprint("sum:", 2+3)\n```\n输出\n```text\nsum: 4\n```'
    calls = []
    context = {'user_message': SimpleNamespace(content='计算2加3。'),
        'source_materials': [{'available': True, 'sourceRefId': 's', 'quote': '加法计算总和。'}]}

    async def call(llm, *, operation, user_prompt, response_validator=None, **kwargs):
        calls.append(operation)
        if operation == 'chat_subject_expert': return original
        if operation == 'chat_pedagogical': return '直接计算。'
        if operation == 'chat_synthesizer': return original
        if operation == 'chat_challenger': return '未发现问题。'
        if operation == 'chat_subject_revision':
            assert 'sum: 5' in user_prompt and 'execution:' in user_prompt
            return original.replace('sum: 4', 'sum: 5') if correct_revision else original
        assert operation == 'chat_evidence_verifier'
        assert '"stdout": "sum: 5' in user_prompt
        # Deliberately miss the numerical defect: runtime evidence must win.
        conditions = json.loads(user_prompt.split('condition_claims：')[1].split('\n')[0])
        raw = json.dumps({'claims': [{'claim': '这是加法例子。', 'basis': 'worked_example',
            'support': 'unsupported', 'needs_revision': False, 'quote': '', 'source_ref_ids': []}],
            'conditionReview': [{'claimId': c['id'], 'status': 'valid', 'reason': '可用', 'fix': ''} for c in conditions]})
        if response_validator: response_validator(raw)
        return raw

    monkeypatch.setattr(stream_api, 'audited_legacy_text_call', call)
    monkeypatch.setattr(stream_api, 'for_answer_step', lambda llm, **kwargs: llm)
    task = stream_api._run_professional_chain(SimpleNamespace(llm=SimpleNamespace(generate=lambda: None)), context, {})
    if correct_revision:
        result = asyncio.run(task)
        assert result['expert'] == original.replace('sum: 4', 'sum: 5')
        assert result['calculation_review_attempts'][-1]['codeExecutions'][0]['cached']
    else:
        with pytest.raises(stream_api.EvidenceReviewError) as error:
            asyncio.run(task)
        assert error.value.answer_revision['decision'] == 'rejected'
    assert calls.count('chat_subject_expert') == 1
    assert calls.count('chat_subject_revision') == 1
