"""Real computation with synthetic model responses, separate from live quality."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from app import numerical_verification as nv


def test_extraction_recovers_only_exact_text_at_a_sentence_boundary():
    candidate={'content':'(3) 均值与标准差应在哪些行上拟合，为什么不能用全部9行；(4) 检查测试集。'}
    item={'path':'content','quote':'均值与标准差应在哪些行上拟合，为什么不能用全部9行？'}
    nv._quote(candidate,item)
    assert item['quote']=='均值与标准差应在哪些行上拟合，为什么不能用全部9行；'
    for quote in ['均值与标准差应在哪些行上拟合，为什么不能用全部8行？',
                  '均值与标准差应在哪些行上拟合？']:
        with pytest.raises(ValueError,match='content'):
            nv._quote(candidate,{'path':'content','quote':quote})


def test_uncomputed_ambiguous_output_requires_a_verdict_while_given_data_can_pass():
    from app.resource_review_parts import conditional_teaching_claims, apply_condition_review
    body = {'slides': [{'body': '设计矩阵10×10，按lstsq默认截断有效数值秩8。'},
                       {'body': '给定验证MSE为0.20、0.14、0.17。'}]}
    candidate = {'type': 'deck', 'version_id': 'ambiguous-rank', 'content': json.dumps(body),
        'runtime_verification': {'numerical': {'plan': {'not_computed': [
            {'path': 'content.slides[0].body', 'quote': body['slides'][0]['body'],
             'reason': '没有区分增广矩阵与拟合器内部中心化矩阵，不能任选一个比较。'},
            {'path': 'content.slides[1].body', 'quote': body['slides'][1]['body'],
             'reason': '给定的练习输入，无需反造训练数据。'}]}}}}
    claims = conditional_teaching_claims([candidate])
    assert len(claims) == 2
    with pytest.raises(ValueError):
        apply_condition_review({'approved': True, 'conditionReview': []}, claims)
    checks = [{'claimId': c['id'], 'status': 'incorrect' if i == 0 else 'valid',
               'reason': '拟合器的有效秩不能充作增广矩阵的默认秩。' if i == 0 else '这些是题给输入。',
               'fix': '按实际接口标明对应矩阵与容差。' if i == 0 else ''}
              for i, c in enumerate(claims)]
    result = apply_condition_review({'approved': True, 'conditionReview': checks}, claims)
    assert result['approved'] is False
    assert len(result['findings']) == 1
    assert result['findings'][0]['location'] == 'content.slides[0].body'
    scoped = conditional_teaching_claims([candidate],
        {'stage': 'section', 'candidate_index': 0, 'paths': ['content.slides[1]']})
    assert [c['id'] for c in scoped] == [claims[1]['id']]
    assert apply_condition_review({'approved': True, 'conditionReview': [checks[1]]}, scoped)['approved']


def test_same_slide_distinct_numeric_findings_receive_independent_decisions():
    from app.resource_review_context import review_findings
    from app.resource_review_adjudication import _validate_decisions
    candidate = {'type': 'deck', 'version_id': 'numeric-slide-v1',
                 'content': '预测为2.1，平方误差为1.2。'}
    common = {'resourceType': 'deck', 'location': 'content', 'issue': '数值不一致',
              'issue_id': 'old-colliding-id'}
    findings = [{**common, 'evidence': {'quote': '预测为2.1', 'quantity': '预测', 'actual': [2.1]}},
                {**common, 'evidence': {'quote': '平方误差为1.2', 'quantity': '平方误差', 'actual': [1.21]}}]
    normalized = review_findings({'approved': False, 'findings': [*findings, findings[0]]}, [candidate])
    assert len(normalized['findings']) == 2
    assert len({f['issue_id'] for f in normalized['findings']}) == 2
    assert review_findings(normalized, [candidate]) == normalized
    decisions = [{'issue_id': f['issue_id'], 'verdict': 'false_positive' if i == 0 else 'confirmed',
                  'candidate_quote': f['evidence']['quote'], 'reason': '复核原输入与指定方法。',
                  'source_evidence': [], 'fix': '保留预测并修正平方误差。'}
                 for i, f in enumerate(normalized['findings'])]
    result = _validate_decisions(decisions, findings=normalized['findings'], sources={},
                                 candidates=[candidate], review=normalized)
    assert not result['approved']
    assert [f['evidence']['quantity'] for f in result['findings']] == ['平方误差']


@pytest.mark.parametrize('printed,actual,matches', [
    ('0.017012571479…', .01701257147985, True),
    ('0.017012571479…', .0170125714788, False),
    ('0.017012571479...', .0170125714802, False),
    ('-0.004253142869…', -.0042531428698, True),
    ('-0.004253142869…', -.0042531428688, False),
])
def test_ellipsis_is_a_truncated_interval_not_a_rounded_value(printed, actual, matches):
    candidate = {'content': '实际结果为' + printed}
    plan = {'cases': [{'id': 'example', 'inputs': {'x': [1]}, 'method': '给定方法',
        'input_evidence': [{'path': 'content', 'quote': candidate['content']}],
        'targets': [{'id': 'value', 'quantity': '计算结果', 'claims': [
            {'path': 'content', 'quote': candidate['content'], 'values': [printed]}]}]}], 'not_computed': []}
    nv._validate_plan(plan, candidate)
    assert nv._compare(plan, {'example:value': [actual]})[0]['matches'] == matches


def example():
    inputs = {'x': [0, .11, .22, .33, .44, .56, .67, .78, .89, 1.0],
              'y': [1.05, 1.104793, 1.295144, 1.325011, 1.548352, 1.709648, 2.049489, 2.976856, 2.845707, 3.53]}
    fabricated = ['1.046184', '1.108609', '1.291328', '1.328827', '1.544536',
                  '1.713464', '2.045673', '2.980672', '2.841891', '3.533816']
    quote = '| predictions | ' + ' | '.join(fabricated) + ' |'
    body = {'data': json.dumps(inputs), 'method': 'degree=9, include_bias=False, fit_intercept=True, tol=1e-6',
            'table': quote, 'mse': 'MSE=1.4564558749147509e-05'}
    candidate = {'type': 'deck', 'version_id': 'v1', 'content': json.dumps(body)}
    plan = {'cases': [{'id': 'fit', 'inputs': inputs, 'method': body['method'],
        'input_evidence': [{'path': 'content.data', 'quote': body['data']}],
        'targets': [
            {'id': 'predictions', 'quantity': '按x顺序计算9阶训练预测', 'claims': [
                {'path': 'content.table', 'quote': quote, 'values': fabricated}]},
            {'id': 'mse', 'quantity': '9阶训练MSE', 'claims': [
                {'path': 'content.mse', 'quote': body['mse'], 'values': ['1.4564558749147509e-05']}]}]}],
        'not_computed': []}
    return candidate, plan


CODE = '''import json
import numpy as np
from sklearn.preprocessing import PolynomialFeatures
from sklearn.linear_model import LinearRegression
c = json.loads(input())[0]
x = np.array(c['inputs']['x']).reshape(-1,1)
y = np.array(c['inputs']['y'])
features = PolynomialFeatures(9, include_bias=False).fit_transform(x)
model = LinearRegression(fit_intercept=True, tol=1e-6).fit(features, y)
pred = model.predict(features)
print(json.dumps({'values': {'fit:predictions': pred.tolist(), 'fit:mse': [float(np.mean((pred-y)**2))]}}, allow_nan=False))
'''


class Backend:
    model = 'synthetic'
    def __init__(self, plan, codes=None):
        self.plan, self.codes, self.calls = plan, codes or [CODE], []

    async def generate(self, system, user, *, role):
        request = json.loads(user)
        self.calls.append((role, request))
        if role == 'numerical_extractor':
            return json.dumps(self.plan)
        if role == 'numerical_programmer':
            return json.dumps({'code': self.codes.pop(0)})
        return json.dumps({'approved': True, 'summary': '核对完成', 'findings': [],
                           'rejectedTypes': [], 'teachingReview': [], 'conditionReview': []})


@pytest.fixture(autouse=True)
def runtime(monkeypatch):
    from app import code_sandbox
    configured = replace(nv.CONFIG, sandbox_mode='trusted_local', sandbox_timeout=60)
    monkeypatch.setattr(nv, 'CONFIG', configured)
    monkeypatch.setattr(code_sandbox, 'CONFIG', configured)


def test_real_fitting_rejects_invented_point_values_even_with_correct_aggregate():
    candidate, plan = example()
    backend, saved, events = Backend(plan), {}, []
    evidence = asyncio.run(nv.verify_numerical_content(backend, candidate, completed=saved,
        save=lambda key, value: events.append((key, deepcopy(value)))))
    assert evidence['status'] == 'computed'
    assert evidence['comparisons'][0]['matches'] is False
    assert evidence['comparisons'][1]['matches'] is True
    assert evidence['comparisons'][0]['actual'][0] == pytest.approx(1.050086, abs=5e-7)
    solver_input = next(request for role, request in backend.calls if role == 'numerical_programmer')
    assert '1.046184' not in json.dumps(solver_input)
    assert 'claims' not in json.dumps(solver_input)
    review = nv.apply_numerical_findings({'approved': True, 'findings': [], 'rejectedTypes': []}, candidate, evidence)
    assert review['approved'] is False and review['rejectedTypes'] == ['deck']
    assert len(review['findings']) == 1
    assert asyncio.run(nv.verify_numerical_content(backend, candidate, completed=saved)) == evidence
    assert len(backend.calls) == 2 and len(events) == 2


def test_failed_program_is_preserved_and_next_attempt_repairs_it():
    candidate, plan = example()
    backend, saved, events = Backend(plan, ['raise ValueError("bad program")', CODE]), {}, []
    with pytest.raises(ValueError, match='计算程序未完成'):
        asyncio.run(nv.verify_numerical_content(backend, candidate, completed=saved,
            save=lambda key, value: events.append((key, deepcopy(value)))))
    assert any(':failure:' in key and value['execution']['status'] == 'runtime_error' for key, value in events)
    result = asyncio.run(nv.verify_numerical_content(backend, candidate, completed=saved))
    assert result['status'] == 'computed'
    requests = [request for role, request in backend.calls if role == 'numerical_programmer']
    assert requests[1]['previous_failure']['execution']['status'] == 'runtime_error'
    assert len([role for role, _ in backend.calls if role == 'numerical_extractor']) == 1


@pytest.mark.parametrize('change', ['path', 'values', 'quote'])
def test_extracted_claim_must_match_the_exact_original_field(change):
    candidate, plan = example()
    claim = plan['cases'][0]['targets'][0]['claims'][0]
    claim[change] = {'path': 'content.method', 'values': ['99.999'], 'quote': 'invented output 99.999'}[change]
    with pytest.raises(ValueError):
        nv._validate_plan(plan, candidate)


def test_independent_publication_waits_for_computation_even_when_reviewer_approves():
    from app.resource_bundles import _resource_review_async
    candidate, plan = example()
    backend, published = Backend(plan), []
    result = asyncio.run(_resource_review_async(backend,
        manifest={'automated_calculation_check': True}, semantic_plan='', candidates=[candidate],
        on_independent_review=lambda item, review: published.append(review)))
    assert result['approved'] is False
    assert published[0]['approved'] is False
    assert result['findings'][0]['issue_id'] and result['findings'][0]['version_id'] == 'v1'
    request = next(request for role, request in backend.calls if role == 'resource_reviewer')
    assert request['candidates'][0]['runtime_verification']['numerical']['execution']['status'] == 'success'


def test_cancelled_save_stops_before_program_generation():
    candidate, plan = example()
    backend = Backend(plan)
    def stopped(*args):
        raise RuntimeError('ownership lost')
    with pytest.raises(RuntimeError, match='ownership lost'):
        asyncio.run(nv.verify_numerical_content(backend, candidate, save=stopped))
    assert [role for role, _ in backend.calls] == ['numerical_extractor']


def test_direct_output_mapping_is_equivalent_and_incomplete_mapping_is_rejected():
    _, plan = example()
    values = {'fit:predictions': [1.0]*10, 'fit:mse': [0.1]}
    execution = {'status':'success', 'stdout':json.dumps(values)}
    assert nv._execution_values(execution, plan) == values
    execution['stdout'] = json.dumps({'fit:mse':[0.1]})
    with pytest.raises(ValueError, match='全部计算目标'):
        nv._execution_values(execution, plan)


@pytest.mark.parametrize('printed,quote,actual', [
    ('0.00425', '验证MSE约为0.00425，推荐三阶。', .00425314),
    ('8', '数值秩为8', 8),
    ('1.46×10^-5', '训练MSE约1.46×10^-5。', .0000145645587),
    ('1.46×10⁻⁵', '训练MSE约1.46×10⁻⁵。', .0000145645587),
    ('1.46e-05', r'训练MSE约1.46\\times10^{-5}。'.replace('\\\\', '\\'), .0000145645587),
])
def test_printed_math_and_adjacent_chinese_keep_original_precision(printed, quote, actual):
    candidate, plan = example()
    candidate['content'] = json.dumps({'data': json.dumps(plan['cases'][0]['inputs']), 'mse': quote})
    target = plan['cases'][0]['targets'][1]
    target['claims'][0].update(quote=quote, values=[printed])
    plan['cases'][0]['targets'] = [target]
    nv._validate_plan(plan, candidate)
    assert nv._compare(plan, {'fit:mse':[actual]})[0]['matches']
    assert not nv._compare(plan, {'fit:mse':[actual + 1]})[0]['matches']


@pytest.mark.parametrize('claimed', ['8', '0.4', '1.46', '1.460e-5'])
def test_number_fragment_or_changed_precision_is_not_original_claim(claimed):
    candidate, plan = example()
    quote = 'MSE为0.00425，秩为18，误差为1.46e-5。'
    candidate['content'] = json.dumps({'data': json.dumps(plan['cases'][0]['inputs']), 'mse': quote})
    target = plan['cases'][0]['targets'][1]
    target['claims'][0].update(quote=quote, values=[claimed])
    plan['cases'][0]['targets'] = [target]
    with pytest.raises(ValueError, match='显示精度不符'):
        nv._validate_plan(plan, candidate)


def test_parser_recovery_reuses_complete_saved_extraction(monkeypatch):
    candidate, plan = example()
    backend, cache = Backend(plan), {}
    original = nv._validate_plan
    monkeypatch.setattr(nv, '_validate_plan', lambda *args: (_ for _ in ()).throw(ValueError('old parser')))
    with pytest.raises(ValueError, match='old parser'):
        asyncio.run(nv.verify_numerical_content(backend, candidate, completed=cache))
    monkeypatch.setattr(nv, '_validate_plan', original)
    result = asyncio.run(nv.verify_numerical_content(backend, candidate, completed=cache))
    assert result['status'] == 'computed'
    assert [role for role, _ in backend.calls] == ['numerical_extractor', 'numerical_programmer']
    assert any(':failure:' in key for key in cache)


@pytest.mark.parametrize('printed,actual', [('1/6', 1/6), ('−3 / 7', -3/7), ('4/-9', -4/9)])
def test_exact_fraction_is_preserved_and_compared_without_rounding_tolerance(printed, actual):
    candidate = {'content': '按等可能结果计算，概率=' + printed}
    plan = {'cases': [{'id': 'fraction', 'inputs': {'n': 6}, 'method': '等可能结果计数',
        'input_evidence': [{'path': 'content', 'quote': candidate['content']}],
        'targets': [{'id': 'p', 'quantity': '概率', 'claims': [
            {'path': 'content', 'quote': candidate['content'], 'values': [printed]}]}]}], 'not_computed': []}
    nv._validate_plan(plan, candidate)
    assert nv._compare(plan, {'fraction:p': [actual]})[0]['matches']
    assert not nv._compare(plan, {'fraction:p': [actual + .0001]})[0]['matches']
    for fragment in ['1', '6', '0.16666666666666666', '2/12']:
        plan['cases'][0]['targets'][0]['claims'][0]['values'] = [fragment]
        with pytest.raises(ValueError, match='显示精度不符'):
            nv._validate_plan(plan, candidate)


def test_fraction_zero_denominator_is_rejected():
    with pytest.raises(ValueError, match='分母'):
        nv._printed_number('1/0')
