import json
from decimal import Decimal

import pytest

from app.claim_evidence import verify_claim_quotes, check_claim_calculations
from stream_api import _normalize_claims


def material(text, *, ref='source-1', start=100):
    return {'available': True, 'sourceRefId': ref, 'quote': text, 'title': '模型评估',
            'locationLabel': '训练与验证', 'charStart': start, 'charEnd': start + len(text)}


def claim(quote, **extra):
    return {'claim': '检查结论', 'support': 'supported', 'source_ref_ids': ['source-1'],
            'quote': quote, 'location': '第999页', **extra}


@pytest.mark.parametrize('quote', ['训练误差低一定代表泛化好。', '不应只看训练误差。', '误差是0.03。', 'L=+x。'])
def test_a_valid_source_id_cannot_make_a_fabricated_quote_publishable(quote):
    materials = [material('应只看验证误差。误差是0.30。L=-x。')]
    result = _normalize_claims(json.dumps({'claims': [claim(quote)]}), materials)[0]
    assert result['support'] == 'unsupported'
    assert result['quoteVerified'] is False
    assert result['quote'] == ''
    assert '未能' in result['review']['revision']


def test_whitespace_is_allowed_but_location_comes_from_the_matching_frozen_passage():
    text = '说明：不能只看\n训练误差。'
    result = _normalize_claims(json.dumps({'claims': [claim('不能只看训练误差。')]}), [material(text)])[0]
    assert result['support'] == 'supported'
    assert result['location'] == '训练与验证'
    assert result['quote'] == '不能只看\n训练误差。'
    citation = result['citations'][0]
    assert citation['charStart'] == 103
    assert citation['charEnd'] == 100 + len(text)


def test_rendered_link_quote_preserves_original_destination_and_exact_source_span():
    text = 'The [pipeline](https://example.org/search?q=pipeline) prevents leakage.'
    rewritten = 'The [pipeline](https://example.org/api/Pipeline.html) prevents leakage.'
    result = verify_claim_quotes(claim(rewritten), [material(text)])
    assert result['verified']
    citation = result['citations'][0]
    assert citation['matchKind'] == 'markdown_links'
    assert citation['quote'] == text
    assert citation['charStart'] == 100 and citation['charEnd'] == 100 + len(text)
    assert not verify_claim_quotes(claim(rewritten.replace('prevents', 'does not prevent')), [material(text)])['verified']
    assert not verify_claim_quotes(claim(rewritten.replace('[pipeline]', '[validation set]')), [material(text)])['verified']
    shortened = verify_claim_quotes(claim('pipeline prevents leakage.'), [material(text)])['citations'][0]
    assert shortened['quote'] == text[4:]
    assert shortened['charStart'] == 104


@pytest.mark.parametrize('wrapper', ['`{}`', '```python\n{}\n```'])
def test_link_destinations_inside_code_remain_literal(wrapper):
    original = wrapper.format('print("[x](https://example.org/a)")')
    changed = original.replace('/a)', '/b)')
    assert not verify_claim_quotes(claim(changed), [material(original)])['verified']


def test_same_reference_cannot_join_separate_passages_and_aliases_stay_exact():
    materials = [material('训练误差下降。'), material('验证误差上升。', start=800)]
    assert not verify_claim_quotes(claim('训练误差下降。验证误差上升。'), materials)['verified']
    assert not verify_claim_quotes(claim('验证误差上升。', source_ref_ids=['S1']), materials)['verified']
    result = verify_claim_quotes(claim('验证误差上升。', source_ref_ids=['[S2]']), materials)
    assert result['verified']
    assert result['citations'][0]['charStart'] == 800


def test_multiple_citations_require_every_quote_to_exist_without_inventing_semantic_support():
    materials = [material('训练误差下降。'), material('验证误差上升。', ref='source-2')]
    item = claim('', support='contradicted', conditions='仅描述所给曲线', support_reason='两种误差变化不同', citations=[
        {'source_ref_id': 'S1', 'quote': '训练误差下降。'},
        {'source_ref_id': 'S2', 'quote': '验证误差上升。'},
    ])
    result = _normalize_claims(json.dumps({'claims': [item]}), materials)[0]
    assert result['support'] == 'contradicted'  # Quote authenticity never implies entailment.
    assert result['quoteVerified']
    assert len(result['citations']) == 2
    assert result['conditions'] == item['conditions']
    item['citations'][1]['quote'] = '验证误差下降。'
    result = _normalize_claims(json.dumps({'claims': [item]}), materials)[0]
    assert result['support'] == 'unsupported'
    assert result['quoteVerified'] is False


def test_titles_prove_selection_only_and_noncontiguous_excerpts_do_not_invent_offsets():
    source = material('训练误差下降。')
    source['charEnd'] += 100
    result = verify_claim_quotes(claim('训练误差下降。'), [source])
    assert result['verified'] and 'charStart' not in result['citations'][0]
    result = verify_claim_quotes(claim('模型评估'), [source])
    assert result['verified'] and result['citations'][0]['quoteKind'] == 'title'
    assert 'charStart' not in result['citations'][0]


def test_unavailable_or_other_source_cannot_validate_quote():
    source = material('训练误差下降。')
    source['available'] = False
    assert not verify_claim_quotes(claim('训练误差下降。'), [source])['verified']
    assert not verify_claim_quotes(claim('训练误差下降。'), [material('训练误差下降。', ref='other')])['verified']


def test_structured_resource_multiline_code_quotes_match_decoded_field_without_fabricated_offsets():
    code = 'def objective(w, lam):\n    data = (w - 3.0) ** 2\n    return data + (lam / 2.0) * w ** 2'
    text = '本次材料全文：\n' + json.dumps({'codeBlocks': [{'code': code}]}, ensure_ascii=False)
    source = {**material(text), 'kind': 'resource_version'}
    result = verify_claim_quotes(claim(code), [source])
    assert result['verified']
    citation = result['citations'][0]
    assert citation['quote'] == code
    assert citation['fieldPath'] == ['codeBlocks', 0, 'code']
    assert citation['matchKind'] == 'json_string_whitespace'
    assert 'charStart' not in citation
    assert not verify_claim_quotes(claim(code.replace('** 2', '** 3')), [source])['verified']


def test_decoded_resource_quotes_do_not_join_fields_or_decode_literal_backslashes():
    body = {'first': '第一段的内容。', 'second': '第二段的内容。', 'code': r'print("a\nb")'}
    source = {**material('本次材料全文：\n' + json.dumps(body, ensure_ascii=False)), 'kind': 'resource_version'}
    assert not verify_claim_quotes(claim(body['first'] + body['second']), [source])['verified']
    assert verify_claim_quotes(claim(body['code']), [source])['verified']
    assert not verify_claim_quotes(claim('print("a\nb")'), [source])['verified']
    ordinary = {**source, 'kind': 'canonical_source'}
    assert not verify_claim_quotes(claim(body['code']), [ordinary])['verified']


def test_wrong_arithmetic_cannot_be_published_even_if_model_labels_it_supported():
    text = '验证误差：第2轮0.30，第3轮0.47。'
    item = claim(text, claim='验证误差增加0.27。', calculations=[{'expression': '0.47 - 0.30', 'claimed_result': '0.27'}])
    result = _normalize_claims(json.dumps({'claims': [item]}), [material(text)])[0]
    assert result['support'] == 'contradicted'
    assert result['calculations'][0]['calculated'] == '0.17'
    assert '0.17' in result['review']['revision']
    item.update(claim='验证误差增加0.17。', calculations=[{'expression': '0.47 - 0.30', 'claimed_result': '0.17'}])
    result = _normalize_claims(json.dumps({'claims': [item]}), [material(text)])[0]
    assert result['support'] == 'supported'
    assert result['calculations'][0]['agrees']


@pytest.mark.parametrize('expression,expected', [('1/(1-.25)', '4/3'), ('4/(1-.25)', '16/3'), ('-.5/3', '-1/6')])
def test_exact_fraction_results_are_independently_checked(expression, expected):
    check = check_claim_calculations({'claim': f'结果为{expected}。', 'calculations': [
        {'expression': expression, 'claimed_result': expected}]}, [])[0]
    assert check['checked'] and check['agrees'] and check['resultMentioned']


def test_wrong_fraction_is_rejected_without_turning_a_correct_example_into_a_source_fact():
    item = claim('采用暂退法。', claim='本次输出为5/3。',
                 calculations=[{'expression': '1/(1-.25)', 'claimed_result': '5/3'}])
    result = _normalize_claims(json.dumps({'claims': [item]}), [material('采用暂退法。')])[0]
    assert result['support'] == 'contradicted'
    item.update(claim='本次输出为4/3。', support='unsupported', basis='worked_example', needs_revision=False,
                calculations=[{'expression': '1/(1-.25)', 'claimed_result': '4/3'}])
    result = _normalize_claims(json.dumps({'claims': [item]}), [material('采用暂退法。')])[0]
    assert result['support'] == 'unsupported'
    assert result['calculations'][0]['agrees']


@pytest.mark.parametrize('claimed_result', ['1/0', '1/2+1', '__import__("os")', '1e99/2'])
def test_fraction_result_does_not_accept_zero_denominators_or_code(claimed_result):
    check = check_claim_calculations({'calculations': [
        {'expression': '1/2', 'claimed_result': claimed_result}]}, [])[0]
    assert not check['checked']


@pytest.mark.parametrize('prefix,result', [('约 ', '4.9141'), ('约为', '4.914'), ('≈', '4.91'), ('\\approx ', '4.9141')])
def test_explicit_rounding_uses_the_stated_decimal_precision(prefix, result):
    item = claim('采用梯度下降。', claim=f'顺序更新损失{prefix}{result}。', basis='worked_example',
                 needs_revision=False, support='unsupported',
                 calculations=[{'expression': '(4.135-1)^2/2', 'claimed_result': result}])
    from app.claim_evidence import calculation_review_feedback
    assert calculation_review_feedback([item], [material('采用梯度下降。')]) == []
    checked = check_claim_calculations(item, [])[0]
    assert checked['checked'] and checked['agrees'] and checked['approximate']


@pytest.mark.parametrize('value,agrees', [('0.0149301', True), ('0.0149302', False)])
def test_actual_result_table_precision_reaches_normalized_claims(value, agrees):
    draft = '| 模型 | 四条验证平方残差 |\n|---|---|\n|1阶|' + value + '|'
    item = claim('', claim='1阶验证平方残差为' + value + '。', source_ref_ids=[],
                 support='unsupported', basis='worked_example', needs_revision=False,
                 calculations=[{'expression': '(3.049936333333333-3.172125)^2', 'claimed_result': value}])
    row = _normalize_claims(json.dumps({'claims': [item]}), [], draft=draft)[0]
    assert row['calculations'][0]['roundingBasis'] == 'rendered_result_table'
    assert row['calculations'][0]['agrees'] is agrees
    assert row['revisionNeeded'] is (not agrees)


@pytest.mark.parametrize('header', ['差的平方', '平方差'])
@pytest.mark.parametrize('value,agrees', [('0.0149301', True), ('0.0149302', False)])
def test_rounded_intermediate_table_values_do_not_create_false_arithmetic_feedback(header, value, agrees):
    from app.claim_evidence import calculation_review_feedback
    draft = '| 行 | ' + header + ' |\n|---|---|\n|4|' + value + '|'
    item = claim('', claim='验证MSE为0.0397528。', source_ref_ids=[],
                 support='unsupported', basis='worked_example', needs_revision=False,
                 calculations=[{'expression': '(3.049936333333333-3.172125)^2', 'claimed_result': value}])
    checked = check_claim_calculations(item, [], draft=draft)[0]
    assert not checked['resultMentioned']  # An intermediate value, not the claim's final MSE.
    assert checked['agrees'] is agrees
    assert bool(calculation_review_feedback([item], [], draft=draft)) is (not agrees)


@pytest.mark.parametrize('header,text', [
    ('真实y', '计算结果为0.3333。'),
    ('MSE（题给）', '计算结果为0.3333。'),
    ('MSE', '计算结果精确等于0.3333。'),
    ('MSE', '1/3=0.3333。'),
])
def test_table_precision_does_not_round_inputs_or_exact_assertions(header, text):
    draft = '| 模型 |' + header + '|\n|---|---|\n|A|0.3333|'
    checked = check_claim_calculations({'claim': text, 'calculations': [
        {'expression': '1/3', 'claimed_result': '0.3333'}]}, [], draft=draft)[0]
    assert not checked['agrees']


@pytest.mark.parametrize('text,value', [
    ('损失精确等于4.9141。', '4.9141'),
    ('损失约为4.90。', '4.90'),
    ('损失约为4.9141，另一个损失精确为4.9142。', '4.9142'),
])
def test_rounding_does_not_mask_wrong_values_or_other_exact_equalities(text, value):
    checked = check_claim_calculations({'claim': text, 'calculations': [
        {'expression': '(4.135-1)^2/2', 'claimed_result': value}]}, [])[0]
    assert checked['checked'] and not checked['agrees']


def test_approximation_applies_to_each_value_in_an_explicit_numeric_list():
    checks = check_claim_calculations({'claim': '四个变换结果约为 -1.6186、0.1271、1.8729、3.6186。',
        'calculations': [{'expression': f'2*({x}-5)/sqrt(5+.25)+1', 'claimed_result': value}
                         for x, value in zip([2,4,6,8], ['-1.6186','0.1271','1.8729','3.6186'])]}, [])
    assert all(check['checked'] and check['agrees'] and check.get('approximate') for check in checks)


@pytest.mark.parametrize('claim,value,agrees', [
    ('两个比例约为0.3333、0.6667。', '0.6667', True),
    ('两个比例约为0.3333、0.6666。', '0.6666', False),
    ('第一个比例约为0.3333，第二个比例精确为0.6667。', '0.6667', False),
    ('近似值为0.3333和0.6667；精确值为0.6666。', '0.6666', False),
])
def test_rounded_list_scope_stops_at_new_prose_and_keeps_wrong_rounding_rejected(claim, value, agrees):
    check = check_claim_calculations({'claim':claim,'calculations':[
        {'expression':'2/3','claimed_result':value}]},[])[0]
    assert check['agrees'] is agrees


@pytest.mark.parametrize('claim,question,value,agrees', [
    ('计算结果为0.6667。', '打印计算结果，保留4位小数。', '0.6667', True),
    ('四个变换结果为[0.3333,0.6667]。', '打印变换结果，保留4位小数。', '0.6667', True),
    ('手算结果是[0.3333,0.6667]。', '手算两种结果，结果保留4位小数，不用代码。', '0.6667', True),
    ('标准化结果为[0.0000,0.6667]。', '手算标准化结果，保留4位小数。', '0.6667', True),
    ('标准化结果为[0.0000,0.6666]。', '手算标准化结果，保留4位小数。', '0.6666', False),
    ('计算结果为0.6666。', '打印计算结果，保留4位小数。', '0.6666', False),
    ('计算结果精确等于0.6667。', '打印计算结果，保留4位小数。', '0.6667', False),
    ('精确参数为0.6667。', '打印计算结果，保留4位小数。', '0.6667', False),
    ('计算结果为0.6667。', '计算结果。', '0.6667', False),
    ('计算结果为0.6667。', '打印计算结果，保留6位小数。', '0.6667', False),
    ('计算结果为0.6667。', '分别打印两种结果，第一种保留4位小数，第二种保留6位小数。', '0.6667', False),
])
def test_requested_output_precision_survives_review_summary_without_weakening_exact_claims(claim, question, value, agrees):
    checked = check_claim_calculations({'claim':claim, 'calculations':[
        {'expression':'2/3','claimed_result':value}]},[],question=question)[0]
    assert checked['agrees'] is agrees
    if agrees:
        assert checked['roundingBasis']=='requested_output_precision'


def test_numeric_zero_is_a_valid_claimed_result():
    checked = check_claim_calculations({'claim': '本次梯度为0。', 'calculations': [
        {'expression': '-1 + 0.5 * 2', 'claimed_result': 0}]}, [])[0]
    assert checked['checked'] and checked['agrees'] and checked['resultMentioned']


@pytest.mark.parametrize('display,agrees', [('0.039753', True), ('0.039754', False)])
def test_labelled_approximate_program_results_keep_display_precision(display, agrees):
    text=f'输出约为：degree=1 train_mse=0.072289 val_mse={display}；degree=3 val_mse=0.004253。'
    checked=check_claim_calculations({'claim':text,'calculations':[
        {'expression':'0.1590111468134958/4','claimed_result':display}]},[])[0]
    assert checked['agrees'] is agrees
    assert checked['approximate']


def test_labelled_approximation_does_not_weaken_later_exact_statement():
    text='输出约为：mse=0.039753。另一个比例精确等于0.6667。'
    checked=check_claim_calculations({'claim':text,'calculations':[
        {'expression':'2/3','claimed_result':'0.6667'}]},[])[0]
    assert not checked['agrees']


@pytest.mark.parametrize('text,expected,agrees', [
    ('对[1,3,5]，变换得[-1.2247,0.0000,1.2247]。', ['-1.2247','0.0000','1.2247'], True),
    ('变换后得到[-1.2247, 0.0000, 1.2247]。', ['-1.2247','0.0000','1.2247'], True),
    ('变换结果：[-1.2247,0.0000,1.2247]。', ['-1.2247','0.0000','1.2247'], True),
    ('变换：[-1.2247,0.0000,1.2247]。', ['-1.2247','0.0000','1.2247'], True),
    ('变换得[-1.2247,0.0000,1.2248]。', ['-1.2247','0.0000','1.2248'], False),
    ('变换精确等于[-1.2247,0.0000,1.2247]。', [], False),
    ('输入数据为[-1.2247,0.0000,1.2247]。', [], False),
    ('输出形状为[2,3]，参数为1.2247。', [], False),
    ('输出版本为[1.2247,2.0000]。', [], False),
    ('输出比例为[1.2247%,2.0000%]。', [], False),
])
def test_result_vectors_share_precision_and_calculation_coverage(text, expected, agrees):
    from app.claim_evidence import calculation_review_feedback
    question='手算两种结果，结果保留4位小数。'
    item=claim('',claim=text,basis='worked_example',support='unsupported',needs_revision=False,calculations=[])
    feedback=calculation_review_feedback([item],[],question=question)
    missing=[v for f in feedback for v in f.get('missingOutputCalculations',[])]
    assert missing==expected
    value='1.2248' if '1.2248' in text else '1.2247'
    item['calculations']=[{'expression':'2/sqrt(8/3)','claimed_result':value}]
    assert check_claim_calculations(item,[],question=question)[0]['agrees'] is agrees


def test_result_precision_does_not_spill_to_other_numbers_in_same_claim():
    item={'claim':'参数为0.6667，结果为[0.0000,1.0000]。',
          'calculations':[{'expression':'2/3','claimed_result':'0.6667'}]}
    assert not check_claim_calculations(item,[],question='结果保留4位小数。')[0]['agrees']


@pytest.mark.parametrize('text,expected', [
    ('程序返回0只是约定，不等于数学上“归一化结果是0”。', []),
    ('不能说变换得[0.0000,0.0000]。', []),
    ('不是输出为0，而是输出为1。', ['1']),
])
def test_negated_results_are_not_approved_numeric_outputs(text, expected):
    from app.claim_evidence import calculation_review_feedback
    item=claim('',claim=text,basis='worked_example',needs_revision=False,calculations=[])
    findings=calculation_review_feedback([item],[])
    assert [v for f in findings for v in f.get('missingOutputCalculations',[])] == expected


@pytest.mark.parametrize('text,expected', [
    ('练习表给出5行验证数据，三个候选的训练MSE分别为甲0.042000、乙0.018000、丙0.000800，且表中不给出验证MSE和选择结果。', []),
    ('给定训练MSE分别为0.042、0.018、0.0008。', []),
    ('给出训练数据，计算的MSE分别为0.042、0.018、0.0008。', ['0.042','0.018','0.0008']),
    ('给出训练数据。MSE计算结果分别为0.042、0.018、0.0008。', ['0.042','0.018','0.0008']),
    ('计算结果如下，给定的新练习训练误差分别为0.042、0.018。', []),
])
def test_given_exercise_values_are_distinct_from_computed_results(text, expected):
    from app.claim_evidence import calculation_review_feedback
    item=claim('', claim=text, basis='worked_example', needs_revision=False, calculations=[])
    findings=calculation_review_feedback([item], [])
    assert [v for f in findings for v in f.get('missingOutputCalculations', [])] == expected


@pytest.mark.parametrize('tail', ['已经超过1。', '大于1。', '不等于1。', '小于2。', '介于1与2之间。'])
def test_result_boundary_is_not_an_additional_numeric_output(tail):
    from app.claim_evidence import calculation_review_feedback
    item=claim('',claim='新值11的结果是1.5000，'+tail,basis='worked_example',needs_revision=False,
               calculations=[{'expression':'(11-2)/(8-2)','claimed_result':'1.5000'}])
    assert not calculation_review_feedback([item],[])


@pytest.mark.parametrize('sign', ['-', '−'])
def test_mathematical_minus_is_consistent_in_claim_and_calculation(sign):
    from app.claim_evidence import calculation_review_feedback
    item=claim('',claim='结果：2→−1.0690，4→−0.2673，8→1.3363。',basis='worked_example',needs_revision=False,
               calculations=[{'expression':'(2-14/3)/sqrt(56/9)','claimed_result':sign+'1.0690'},
                             {'expression':'(4-14/3)/sqrt(56/9)','claimed_result':sign+'0.2673'},
                             {'expression':'(8-14/3)/sqrt(56/9)','claimed_result':'1.3363'}])
    checks=check_claim_calculations(item,[],question='结果保留4位小数。')
    assert all(x.get('checked') and x.get('resultMentioned') and x.get('agrees') for x in checks)
    assert not calculation_review_feedback([item],[],question='结果保留4位小数。')


@pytest.mark.parametrize('label', ['训练值分别得到', '结果依次为', '输出分别是', '结果依次如下：', '分别得到'])
def test_parallel_results_after_obtain_use_the_requested_precision(label):
    item={'claim':label+'0.0000、0.3333、1.0000。','calculations':[
        {'expression':'(4-2)/(8-2)','claimed_result':'0.3333'}]}
    assert check_claim_calculations(item,[],question='列出结果，保留4位小数。')[0]['agrees']


@pytest.mark.parametrize('label,agrees', [
    ('逐项相除得概率 ', True), ('计算得到距离为', True),
    ('计算得到输入为', False), ('计算得到的精确值为', False),
    ('T=1时三个概率分别为', True), ('距离依次是', True),
    ('输入数据分别为', False), ('输出形状依次是', False), ('精确值分别为', False),
])
def test_obtained_numeric_quantity_retains_precision_without_rounding_inputs_or_exact_values(label, agrees):
    item={'claim':label+'0.0900、0.2447、0.6652。', 'calculations':[
        {'expression':'exp(-2)/(exp(-2)+exp(-1)+1)', 'claimed_result':'0.0900'}]}
    assert check_claim_calculations(item,[],question='结果保留4位小数。')[0]['agrees'] is agrees


@pytest.mark.parametrize('result,expected', [('14/3≈4.6667',[True,True]),
    ('14/3≈4.6666',[True,False]),('≈2.4944',[True])])
def test_numeric_result_with_approximation_checks_all_values_instead_of_skipping(result,expected):
    expression='sqrt(56/9)' if result.startswith('≈') else '(2+4+8)/3'
    item={'claim':'均值为'+result+'。' if not result.startswith('≈') else '标准差'+result+'。',
          'calculations':[{'expression':expression,'claimed_result':result,'agrees':True}]}
    checks=check_claim_calculations(item,[])
    assert [x.get('agrees') for x in checks]==expected
    assert all(x['checked'] and x['resultMentioned'] for x in checks)


def test_reviewer_approximation_marker_does_not_weaken_exact_original_claim():
    checks=check_claim_calculations({'claim':'精确等于0.3333。','calculations':[
        {'expression':'1/3','claimed_result':'≈0.3333'}]},[])
    assert checks[0]['checked'] and checks[0]['agrees'] is False


@pytest.mark.parametrize('expression,text,expected', [
    ('ln(0.5)/ln(0.8)', '半衰期约3.1063步。', '3.1063'),
    ('0.8^(ln(0.5)/ln(0.8))', '权重比为0.5。', '0.5'),
    ('log(8,2)', '信息量为3。', '3'),
    ('sqrt(0.04)+exp(0)', '结果为1.2。', '1.2'),
    ('(abs(1-3)+abs(4-2))/2', '平均绝对误差为2。', '2'),
])
def test_standard_numeric_functions_are_recalculated_without_running_generated_code(expression, text, expected):
    result = check_claim_calculations({'claim': text, 'calculations': [
        {'expression': expression, 'claimed_result': expected}]}, [])[0]
    assert result['checked'] and result['agrees'] and result['resultMentioned']


@pytest.mark.parametrize('expression', ['ln(-1)', 'log(8,1)', 'sqrt(-4)', 'exp(100000)',
                                       'math.log(2)', '__import__("math").log(2)'])
def test_numeric_function_domain_errors_and_non_numeric_calls_are_not_executed(expression):
    result = check_claim_calculations({'calculations': [{'expression': expression, 'claimed_result': '0'}]}, [])[0]
    assert not result['checked']


def test_rejected_quote_does_not_keep_the_models_contradictory_support_explanation():
    item = claim('不存在的原句。', support_reason='原文完全支持。', confidence=.98,
                 review={'verifier': '引文逐字一致。'})
    result = _normalize_claims(json.dumps({'claims': [item]}), [material('真正的原文。')])[0]
    assert result['support'] == 'unsupported' and result['confidence'] == 0
    assert '完整找到' in result['supportReason']
    assert result['review']['verifier'] == result['supportReason']


@pytest.mark.parametrize('expression', ['__import__("os").system("bad")', '2 ** 100000', '0.47 / 0', '[x for x in range(5)]'])
def test_calculation_never_executes_code_or_unbounded_arithmetic(expression):
    result = check_claim_calculations({'claim':'差值0.17', 'calculations':[{'expression':expression,'claimed_result':'0.17'}]},
                                      [{'quote':'0.47和0.30'}])
    assert result[0]['checked'] is False


def test_worked_example_arithmetic_is_checked_without_fabricating_source_support():
    item = claim('采用梯度下降。', claim='当学习率为1/9时，新损失为9。', support='unsupported',
                 calculations=[{'expression': '9*(1-18*(1/9))^2', 'claimed_result': '9'}])
    result = _normalize_claims(json.dumps({'claims': [item]}), [material('采用梯度下降。')], question='x=2，w=1')[0]
    check = result['calculations'][0]
    assert check['checked'] and check['agrees']
    assert check['operandsCited'] is False
    assert result['support'] == 'unsupported'  # Arithmetic is not source entailment.


def test_arithmetic_disagreement_does_not_rewrite_a_claim_using_a_reviewers_substituted_result():
    item = claim('采用梯度下降。', claim='当学习率为1/9时损失保持不变。', support='unsupported',
                 calculations=[{'expression': '9*(1-18*(1/9))^2', 'claimed_result': '0'}])
    result = _normalize_claims(json.dumps({'claims': [item]}), [material('采用梯度下降。')])[0]
    check = result['calculations'][0]
    assert check['checked'] and not check['agrees'] and not check['resultMentioned']
    assert result['support'] != 'contradicted'
    from app.claim_evidence import calculation_review_feedback
    assert calculation_review_feedback([item], [material('采用梯度下降。')])


@pytest.mark.parametrize('quoted', [
    r'常数\epsilon > 0通常设置为10^{-6}，避免除零。',
    r'常数\(\epsilon > 0\)通常设置为\(10^{-6}\)，避免除零。',
])
def test_math_delimiters_do_not_lose_real_source_and_original_offsets(quoted):
    source = r'开头。常数$\epsilon > 0$通常设置为$10^{-6}$，避免除零。结尾。'
    entry = material(source)
    entry.update(charStart=100, charEnd=100+len(source))
    checked = verify_claim_quotes(claim(quoted), [entry])
    assert checked['verified']
    citation = checked['citations'][0]
    assert citation['matchKind'] == 'math_delimiters'
    assert citation['quote'] == source[3:-3]
    assert source[citation['charStart']-100:citation['charEnd']-100] == citation['quote']


@pytest.mark.parametrize('source,quoted', [
    (r'常数$\epsilon > 0$。', r'常数\epsilon < 0。'),
    (r'量为$10^{-6}$。', r'量为10^{6}。'),
    (r'量为$x^2$。', r'量为x。'),
    (r'值不等于$0$。', r'值等于0。'),
    (r'价格为\$5。', r'价格为5。'),
    (r'价格为$5。', r'价格为5。'),
])
def test_math_formatting_tolerance_keeps_values_signs_negation_and_currency(source, quoted):
    assert not verify_claim_quotes(claim(quoted), [material(source)])['verified']


def test_a_numeric_correction_is_independently_recalculated():
    from app.claim_evidence import calculation_review_feedback
    item = claim('采用梯度下降。', claim='原损失不变。', review={'verifier': '应改成损失为0。'},
                 revision_calculations=[{'expression': '9*(1-18*(1/9))^2', 'claimed_result': '0'}])
    feedback = calculation_review_feedback([item], [material('采用梯度下降。')])
    assert len(feedback) == 1
    assert Decimal(feedback[0]['calculationChecks'][0]['calculated']) == 9
    item['revision_calculations'][0]['claimed_result'] = '9'
    assert not calculation_review_feedback([item], [material('采用梯度下降。')])


@pytest.mark.parametrize('text,claimed,contradicted', [
    ('结果是4，不是5。', '5', False),
    ('结果不是4。', '4', True),
    ('结果是5，不能说不是5。', '5', True),
    ('结果不是4就是5。', '4', False),
])
def test_numeric_review_distinguishes_explicitly_denied_values(text, claimed, contradicted):
    item = claim('两个二相加。', claim=text, support='supported', needs_revision=False,
                 calculations=[{'expression':'2+2', 'claimed_result':claimed}])
    normalized = _normalize_claims(json.dumps({'claims':[item]}), [material('两个二相加。')])[0]
    assert (normalized['support']=='contradicted') is contradicted


def test_signed_powers_and_rounding_are_evaluated_consistently():
    checks = check_claim_calculations({'claim': '损失5.76，均值0.333333', 'calculations': [
        {'expression': '9*(-0.80)^2', 'claimed_result': '5.76'},
        {'expression': '1/3', 'claimed_result': '0.333333'},
    ]}, [])
    assert all(item['checked'] and item['agrees'] for item in checks)


def test_symbolic_corrections_are_left_to_semantic_review_without_claiming_numeric_verification():
    from app.claim_evidence import calculation_review_feedback
    item = claim('保留的活性除以1-p。', claim='保留的活性乘以1-p。', support='contradicted',
                 revision_calculations=[{'expression':'(1-p)*h/(1-p)','claimed_result':'h'}])
    result = check_claim_calculations({'calculations':item['revision_calculations']}, [])[0]
    assert result['checked'] is False
    assert result['reason'] == 'symbolic_requires_semantic_review'
    assert not calculation_review_feedback([item], [material('保留的活性除以1-p。')])
    item['revision_calculations'] = [{'expression':'__import__("os").system("bad")','claimed_result':'h'}]
    assert calculation_review_feedback([item], [material('保留的活性除以1-p。')])


def test_reviewer_prose_equalities_are_checked_when_model_omits_calculation_fields():
    from app.claim_evidence import calculation_review_feedback, check_review_calculations
    item = claim('采用梯度下降。', claim='J(2)=1.5。', review={
        'verifier': '数值可复核：λ=0.5 时 J(2)=0.5+0.25×4/2=0.5+0.5=1.5；推导正确。'})
    checks = check_review_calculations(item, [])
    errors = [check for check in checks if not check['agrees']]
    assert len(errors) == 1
    assert errors[0]['equality'] == '0.5+0.5 = 1.5'
    assert Decimal(errors[0]['calculated']) == 1
    assert calculation_review_feedback([item], [material('采用梯度下降。')])
    item['review']['verifier'] = '数值可复核：λ=0.5 时 J(2)=0.5+0.5×4/2=0.5+1=1.5。'
    assert not calculation_review_feedback([item], [material('采用梯度下降。')])


@pytest.mark.parametrize('text,expected', [
    ('5/45=0.111…≈11.1%，8/24=0.333…≈33.3%。', [True, True]),
    ('1/3=0.333...。', [True]),
    ('-1/3=-0.333…。', [True]),
    ('1/3=0.334…。', [False]),
    ('1/3=0.333。', [False]),
    ('1+1=3；1/3=0.333…。', [False, True]),
    ('1+1=3=3.000…。', [False, True]),
])
def test_review_decimal_prefixes_are_not_mistaken_for_finite_equalities(text, expected):
    from app.claim_evidence import check_review_calculations
    checks = check_review_calculations({'review': {'verifier': text}}, [])
    assert [check['agrees'] for check in checks] == expected


@pytest.mark.parametrize('text,requires_calculation', [
    ('三个候选的验证 MSE 分别为 A 0.22、B 0.16、C 0.19，最小的是0.16，对应候选B。', False),
    ('三个候选的训练 MSE 分别为 A 0.22、B 0.16、C 0.19。', True),
    ('三个候选的验证 MSE 分别为 A 0.22、B 0.15、C 0.19。', True),
    ('计算得到的验证 MSE 分别为0.22、0.16、0.19。', True),
    ('验证减训练分别为0.16、0.06、0.05。', True),
])
def test_question_metric_series_is_input_but_derived_and_mismatched_results_are_not(text, requires_calculation):
    from app.claim_evidence import calculation_review_feedback
    question = '候选A/B/C的训练MSE为0.06/0.10/0.14，验证MSE为0.22/0.16/0.19。'
    candidate = {'claim': text, 'basis': 'worked_example', 'support': 'unsupported',
                 'needs_revision': False, 'calculations': []}
    feedback = calculation_review_feedback([candidate], [], question=question)
    assert bool(feedback) is requires_calculation


@pytest.mark.parametrize('review', [
    '原式0.5+0.5=1.5不正确；正确结果为1。',
    '“0.5+0.5=1.5”应改为“0.5+0.5=1”。',
    '保留两位小数时约为1/3=0.33。',
    '比例0.3=30%。符号推导J(w)=w*w/2。',
    "导数J'(2)=(2-3)+0.5×2=0；J′(2)=0；∇J(2)=0。",
    r'计算得到\frac{1}{2}=0.5。',
    '取γ²=1.05后，γ²·5/(5+0.25)=1。',
    '取γ²=1.05后，γ²⋅5/(5+0.25)=1。',
    '比例a³·5/(5+0.25)=1。',
])
def test_inline_review_check_leaves_quoted_errors_rounding_and_units_to_semantic_review(review):
    from app.claim_evidence import calculation_review_feedback
    item = claim('采用梯度下降。', review={'verifier': review})
    assert not calculation_review_feedback([item], [material('采用梯度下降。')])


@pytest.mark.parametrize('basis', ['worked_example', 'worked_example题设或明确假设的推导'])
def test_correct_worked_example_does_not_trigger_revision_just_for_missing_textbook_numbers(basis):
    from stream_api import _claim_needs_revision
    item = claim('', claim='由题设计算，新损失为9。', support='unsupported', basis=basis, needs_revision=False,
                 calculations=[{'expression':'9*(1-18*(1/9))^2','claimed_result':'9'}])
    normalized = _normalize_claims(json.dumps({'claims':[item]}), [material('采用梯度下降。')])[0]
    assert normalized['support'] == 'unsupported'
    assert not _claim_needs_revision(normalized)
    item['claim'] = '新损失为0。'
    item['calculations'][0]['claimed_result'] = '0'
    assert _claim_needs_revision(_normalize_claims(json.dumps({'claims':[item]}), [material('采用梯度下降。')])[0])
    item.update(support='supported', quote='教材给出新损失为0。')
    item['calculations'] = []
    assert _claim_needs_revision(_normalize_claims(json.dumps({'claims':[item]}), [material('采用梯度下降。')])[0])


def test_uncited_worked_example_support_label_does_not_invent_a_bad_quotation():
    from stream_api import _claim_needs_revision
    item = claim('', claim='由题设计算，平均值为3。', support='supported',
                 source_ref_ids=[], citations=[], basis='worked_example', needs_revision=False,
                 calculations=[{'expression':'(1+3+5)/3','claimed_result':'3'}])
    result = _normalize_claims(json.dumps({'claims':[item]}), [])[0]
    assert result['support']=='unsupported' and not result['quoteVerified']
    assert not _claim_needs_revision(result)
    assert result['calculations'][0]['agrees']
    # Arithmetic errors still require a correction, even without a citation.
    item['claim']='由题设计算，平均值为4。'
    item['calculations'][0]['claimed_result']='4'
    assert _claim_needs_revision(_normalize_claims(json.dumps({'claims':[item]}), [])[0])
    # An actually claimed source or quotation must still be verified.
    item.update(claim='由题设计算，平均值为3。', calculations=[], quote='教材明确给出平均值为3。')
    assert _claim_needs_revision(_normalize_claims(json.dumps({'claims':[item]}), [])[0])
    item.update(quote='', source_ref_ids=['invented-source'])
    assert _claim_needs_revision(_normalize_claims(json.dumps({'claims':[item]}), [])[0])
    item.update(source_ref_ids=[], support='contradicted')
    assert _claim_needs_revision(_normalize_claims(json.dumps({'claims':[item]}), [])[0])


@pytest.mark.parametrize('separator', ['；', ';', '\n'])
def test_numeric_output_review_requires_calculations_for_every_numeric_row(separator):
    from app.claim_evidence import calculation_review_feedback
    item = claim('', claim=f'预期输出为：1.2 1.62{separator}1.92 0.5832。', basis='worked_example',
                 needs_revision=False, calculations=[{'expression': '0-0.4*(0-3)', 'claimed_result': '1.2'},
                    {'expression': '0.5*(1.2-3)^2', 'claimed_result': '1.62'}])
    assert calculation_review_feedback([item], [])[0]['missingOutputCalculations'] == ['1.92', '0.5832']
    item['calculations'].extend([{'expression': '1.2-0.4*(1.2-3)', 'claimed_result': '1.92'},
                                {'expression': '0.5*(1.92-3)^2', 'claimed_result': '0.5832'}])
    assert calculation_review_feedback([item], []) == []


def test_unlabeled_numeric_columns_are_not_silently_exempted_as_iteration_indices():
    from app.claim_evidence import _displayed_numeric_results
    assert _displayed_numeric_results('预期输出为：1 1.2 1.62；2 1.92 0.5832') == ['1', '1.2', '1.62', '2', '1.92', '0.5832']
    assert _displayed_numeric_results('结果为：1.2\n1.92\n输入为9，迭代次数为8。') == ['1.2', '1.92']
    assert _displayed_numeric_results('结果为：1.2\n第2步使用学习率0.4。') == ['1.2']


def test_numeric_output_review_cannot_claim_independent_check_with_empty_or_partial_calculations():
    from app.claim_evidence import calculation_review_feedback
    item = claim('', claim='实际输出为：均值5.0000，加入epsilon前的方差5.0000，四个变换结果-1.6186 0.1271 1.8729 3.6186',
                 basis='worked_example', needs_revision=False,
                 support_reason='输出数值经独立验算正确。', calculations=[])
    feedback = calculation_review_feedback([item], [], question='计算后打印结果，保留4位小数。')
    assert feedback[0]['missingOutputCalculations'] == ['5.0000', '-1.6186', '0.1271', '1.8729', '3.6186']
    item['calculations'] = [{'expression': '(2+4+6+8)/4', 'claimed_result': '5.0000'},
                            {'expression': '2*(2-5)/sqrt(5.25)+1', 'claimed_result': '-1.6186'}]
    assert calculation_review_feedback([item], [], question='计算后打印结果，保留4位小数。')[0]['missingOutputCalculations'] == ['0.1271', '1.8729', '3.6186']
    item['calculations'].extend({'expression': f'2*({value}-5)/sqrt(5.25)+1', 'claimed_result': result}
                               for value, result in [(4, '0.1271'), (6, '1.8729'), (8, '3.6186')])
    assert not calculation_review_feedback([item], [], question='计算后打印结果，保留4位小数。')


@pytest.mark.parametrize('input_text', ['权重w=[3,-4]时', '代入w=[3,-4]', '设w=[3,-4]', '取w=[3,-4]', '已知w=[3,-4]', 'w=[3,-4]'])
def test_given_weight_vector_in_condition_does_not_require_output_calculation(input_text):
    from app.claim_evidence import calculation_review_feedback
    item = claim('', claim=input_text+'，平方范数为25，新损失为4。', basis='worked_example',
                 needs_revision=False, calculations=[{'expression': '3^2+(-4)^2', 'claimed_result': '25'},
                    {'expression': '1.5+(0.2/2)*25', 'claimed_result': '4'}])
    assert calculation_review_feedback([item], [], question='权重w=[3,-4]，计算新损失。') == []


def test_computed_vector_used_as_condition_still_requires_output_calculation():
    from app.claim_evidence import calculation_review_feedback
    item = claim('', claim='权重更新结果为[3,-4]时，继续计算平方范数。', basis='worked_example',
                 needs_revision=False)
    assert calculation_review_feedback([item], [])[0]['missingOutputCalculations'] == ['3', '-4']


def test_substitution_followed_by_computed_vector_still_requires_calculation():
    from app.claim_evidence import calculation_review_feedback
    item = claim('', claim='代入给定的输入后得到[3,-4]。', basis='worked_example', needs_revision=False)
    assert calculation_review_feedback([item], [])[0]['missingOutputCalculations'] == ['3', '-4']


@pytest.mark.parametrize('result_text', ['更新后w=[3,-4]', 'w=[3,-5]', '得到v=[3,-4]'])
def test_explicit_output_or_changed_assignment_is_not_waived_by_question_inputs(result_text):
    from app.claim_evidence import calculation_review_feedback
    item = claim('', claim=result_text, basis='worked_example', needs_revision=False)
    assert calculation_review_feedback([item], [], question='权重w=[3,-4]，计算更新后的权重。')


def test_approving_quoted_numeric_outputs_requires_calculations_without_magic_verification_words():
    from app.claim_evidence import calculation_review_feedback
    item = claim('', claim='代码实际输出为“加权和: 23.0000”和“加权均值: 5.7500”。',
                 basis='worked_example', needs_revision=False,
                 review={'verifier': '代码按定义计算，输出与计算一致。'})
    assert calculation_review_feedback([item], [])[0]['missingOutputCalculations'] == ['23.0000', '5.7500']


def test_correct_task_output_without_textbook_numbers_still_requires_arithmetic():
    from app.claim_evidence import calculation_review_feedback
    item = claim('', claim='实际输出为3.0000和3.5000。', support='unsupported', basis='worked_example',
                 needs_revision=False, review='课程材料未涉及该输出，但题设推导正确，无需修订。')
    assert calculation_review_feedback([item], [])[0]['missingOutputCalculations'] == ['3.0000', '3.5000']
    item['calculations'] = [{'expression': '(1+4+4)/3', 'claimed_result': '3.0000'},
                            {'expression': '(1*1+2*4+3*4)/(1+2+3)', 'claimed_result': '3.5000'}]
    assert not calculation_review_feedback([item], [])
    normalized = _normalize_claims(json.dumps({'claims': [item]}), [])[0]
    assert normalized['support'] == 'unsupported' and normalized['revisionNeeded'] is False
    assert all(check['checked'] and check['agrees'] for check in normalized['calculations'])


def test_copying_output_literal_is_not_an_independent_calculation_and_wrong_computation_still_revises_answer():
    from app.claim_evidence import calculation_review_feedback
    item = claim('两个二相加。', claim='实际输出为5', basis='worked_example', needs_revision=False,
                 review={'verifier': '手算一致。'}, calculations=[{'expression': '5', 'claimed_result': '5'}])
    assert calculation_review_feedback([item], [material('两个二相加。')])[0]['missingOutputCalculations'] == ['5']
    item['calculations'][0]['expression'] = '2+2'
    assert not calculation_review_feedback([item], [material('两个二相加。')])
    normalized = _normalize_claims(json.dumps({'claims': [item]}), [material('两个二相加。')])[0]
    assert normalized['support'] == 'contradicted' and normalized['revisionNeeded']


@pytest.mark.parametrize('function,expected', [('min', '0.12'), ('max', '0.50')])
def test_numeric_extrema_use_safe_decimal_evaluation(function, expected):
    from app.claim_evidence import check_claim_calculations
    item = claim('', claim=f'比较结果为{expected}。', calculations=[
        {'expression': f'{function}(0.35,0.12,0.20,0.50)', 'claimed_result': expected}])
    check = check_claim_calculations(item, [])[0]
    assert check['checked'] and check['agrees']
    item['calculations'][0]['claimed_result'] = '0.20'
    assert not check_claim_calculations(item, [])[0]['agrees']


@pytest.mark.parametrize('expression', ['min()', 'min([1,2])', 'min(1, key=2)', 'max(os.system(1),2)'])
def test_extrema_do_not_enable_python_calls_or_containers(expression):
    from app.claim_evidence import check_claim_calculations
    assert not check_claim_calculations({'calculations': [{'expression': expression, 'claimed_result': '1'}]}, [])[0]['checked']


def test_given_example_table_inputs_are_distinct_from_computed_outputs():
    from app.claim_evidence import calculation_review_feedback
    draft = '''教学示例记录如下：
| 多项式阶数 d | 训练集MSE | 验证集MSE |
| --- | --- | --- |
| 1 | 0.30 | 0.35 |
| 3 | 0.10 | 0.12 |
| 5 | 0.04 | 0.20 |
| 9 | 0.01 | 0.50 |
'''
    item = claim('', claim='教学示例中候选阶数d=1,3,5,9的验证集MSE分别为0.35,0.12,0.20,0.50，应选d=3，因为验证集MSE最小。',
                 basis='worked_example', support='unsupported', needs_revision=False,
                 calculations=[{'expression': 'min(0.35,0.12,0.20,0.50)', 'claimed_result': '0.12'}])
    assert not calculation_review_feedback([item], [], draft=draft)
    # Reviewer assertions cannot invent an input table or change its values.
    assert calculation_review_feedback([item], [], draft='教学示例，没有给定指标表。')
    assert calculation_review_feedback([item], [], draft=draft.replace('0.35', '0.36'))
    # A program result remains a result, including inside a teaching example.
    assert calculation_review_feedback([item], [], draft=draft.replace('教学示例记录如下', '教学示例的程序输出如下'))
    item['claim'] = '计算得到验证集MSE分别为0.35,0.12,0.20,0.50。'
    assert calculation_review_feedback([item], [], draft=draft)


@pytest.mark.parametrize('fraction', ['3/2', r'\frac{3}{2}', r'\tfrac{3}{2}', r'\dfrac32'])
def test_review_must_not_treat_a_fraction_component_as_the_answers_result(fraction):
    from app.claim_evidence import calculation_review_feedback, check_claim_calculations
    item = claim('', claim=f'最小值为{fraction}。', basis='worked_example', needs_revision=False,
                 calculations=[{'expression': '0.5*(1+2)', 'claimed_result': '3'}])
    check = check_claim_calculations(item, [])[0]
    assert check['checked'] and not check['agrees']
    assert check['resultMentioned'] is False
    feedback = calculation_review_feedback([item], [])
    assert feedback[0]['calculationChecks'][0]['claimed'] == '3'
    item['calculations'] = [{'expression': '3-0.5*3', 'claimed_result': '3/2'}]
    corrected = check_claim_calculations(item, [])[0]
    assert corrected['resultMentioned'] and corrected['agrees']
    assert not calculation_review_feedback([item], [])


@pytest.mark.parametrize('text', ['结果为3/2，另一个结果为3。', r'结果为\frac{3}{2}，另一个结果为3。', '3/2=3。'])
def test_separately_stated_fraction_component_remains_a_real_answer_error(text):
    from app.claim_evidence import calculation_review_feedback, check_claim_calculations
    item = claim('', claim=text, basis='worked_example', needs_revision=False,
                 calculations=[{'expression': '0.5*(1+2)', 'claimed_result': '3'}])
    check = check_claim_calculations(item, [])[0]
    assert check['resultMentioned'] and not check['agrees']
    assert not calculation_review_feedback([item], [])
    normalized = _normalize_claims(json.dumps({'claims':[item]}), [])[0]
    assert normalized['revisionNeeded'] and normalized['support'] == 'contradicted'


@pytest.mark.parametrize(('text', 'value'), [
    ('−3/2', '-1.5'), (r'-\frac{3}{2}', '-1.5'),
    (r'\frac{-3}{2}', '-1.5'), (r'\frac3{2}', '1.5'),
    (r'\frac{3}2', '1.5'), ('1.5e1/1e1', '1.5'),
])
def test_fraction_result_matching_preserves_signs_and_numeric_arguments(text, value):
    from app.claim_evidence import check_claim_calculations
    item = claim('', claim=f'结果为{text}。',
                 calculations=[{'expression': f'({value})*2/2', 'claimed_result': value}])
    check = check_claim_calculations(item, [])[0]
    assert check['agrees'] and check['resultMentioned']


@pytest.mark.parametrize('connector', ['或', '或者', ' or '])
def test_each_alternative_numeric_output_requires_its_own_calculation(connector):
    from app.claim_evidence import calculation_review_feedback
    item = claim('', claim=f'两种可能输出为0{connector}8。', basis='worked_example', needs_revision=False,
                 calculations=[{'expression': '6/0.75', 'claimed_result': '8'},
                               {'expression': '0', 'claimed_result': '0'}])
    assert calculation_review_feedback([item], [], question='h=6，保留率0.75，掩码0或1。')[0]['missingOutputCalculations'] == ['0']
    item['calculations'][1]['expression'] = '0*6/0.75'
    assert not calculation_review_feedback([item], [], question='h=6，保留率0.75，掩码0或1。')


def test_review_repeating_the_original_wrong_equality_does_not_block_answer_repair():
    from app.claim_evidence import calculation_review_feedback
    item = claim('加权均值按加权和除以总权重。', claim='实际输出为5.2500。', basis='worked_example',
                 needs_revision=False, review='23/4=5.25，与原输出一致。',
                 calculations=[{'expression': '(3*2+7+10)/(2+1+1)', 'claimed_result': '5.2500'}])
    assert not calculation_review_feedback([item], [])
    normalized = _normalize_claims(json.dumps({'claims': [item]}), [material('加权均值按加权和除以总权重。')])[0]
    assert normalized['support'] == 'contradicted'
    assert '5.75' in normalized['review']['verifier']
    item['review'] += '另外1+1=3。'
    feedback = calculation_review_feedback([item], [])
    assert len(feedback[0]['calculationChecks']) == 1
    assert feedback[0]['calculationChecks'][0]['equality'] == '1+1 = 3'
    item['review'] = {'verifier': '原答案错误。', 'revision': '另一个例子的均值23/4=5.25。'}
    assert calculation_review_feedback([item], [])


@pytest.mark.parametrize('text,review,basis', [
    ('实际输出为5', '教材中的示例。', 'source'),
    ('输出方差为gamma²*v/(v+epsilon)，均值为beta。', '手算推导一致。', 'worked_example'),
    ('实际输出为version 1.2.3', '手算一致。', 'worked_example'),
    ('实际输出为(2, 3)', '手算推导了数组维度。', 'worked_example'),
    ('实际输出为30%', '手算一致。', 'worked_example'),
])
def test_output_calculation_coverage_does_not_invent_arithmetic_for_symbols_metadata_or_unchecked_results(text, review, basis):
    from app.claim_evidence import calculation_review_feedback
    item = claim('', claim=text, basis=basis, needs_revision=False, review={'verifier': review})
    assert not calculation_review_feedback([item], [])


@pytest.mark.parametrize('support,revision', [('contradicted', True), ('unsupported', True)])
def test_incorrect_or_unresolved_output_still_goes_to_content_revision(support, revision):
    from app.claim_evidence import calculation_review_feedback
    item = claim('', claim='实际输出为5。', support=support, basis='worked_example', needs_revision=revision,
                 review='此输出尚未验算，需进一步核对并修正。')
    assert not calculation_review_feedback([item], [])
