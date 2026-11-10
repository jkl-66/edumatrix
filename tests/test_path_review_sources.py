"""Review quotes must come from their actual supplied source, not the draft."""
import pytest
from app.path_draft import PathTeachingFinding, PathTeachingReview, _validate_path_review_sources
from app.path_draft import _restore_path_quote_typography


def review(reference='', quote=''):
    return PathTeachingReview(findings=(PathTeachingFinding(
        problem='需检查任务条件', correction='改正任务并说明依据',
        source_ref_id=reference, evidence_quote=quote),), revised_path=None)


def payload(text):
    return {'context': {'course_graph': {'chapters': [
        {'reading': {'source_ref_id': 'source-a', 'text': text}}]}}}


def test_whitespace_wrapped_quote_near_end_of_full_reading_is_valid():
    body = '前文。' * 30000 + '训练集拟合参数，\n验证集选择配置。'
    _validate_path_review_sources(review('source-a', '训练集拟合参数，验证集选择配置。'), payload(body))


def test_candidate_task_cannot_be_mislabeled_as_a_textbook_quote():
    data = payload('本节介绍VGG。')
    data['candidate'] = {'teaching_goal': '记录训练损失、验证精度、参数量和每轮耗时'}
    with pytest.raises(ValueError, match='不是所指reading的连续原文'):
        _validate_path_review_sources(review('source-a', data['candidate']['teaching_goal']), data)


def test_correct_quote_cannot_reference_another_source():
    with pytest.raises(ValueError, match='来源不在本批reading'):
        _validate_path_review_sources(review('source-other', '原始内容'), payload('原始内容'))


def test_runtime_finding_does_not_need_a_fabricated_source():
    _validate_path_review_sources(review(), payload('课程原文'))


def test_equation_cannot_lose_its_boundary_condition_in_a_quote():
    with pytest.raises(ValueError, match='不是所指reading的连续原文'):
        _validate_path_review_sources(review('source-a', '对p=1，E[h′]=h。'),
                                      payload('当0≤p<1时，E[h′]=h。对p=1返回零。'))


def test_missed_word_gets_exact_source_line_without_accepting_bad_quote():
    original = '# 对非标量调用backward需要传入一个gradient参数。'
    inaccurate = '# 对非标量调用backward需要传入gradient参数。'
    with pytest.raises(ValueError) as error:
        _validate_path_review_sources(review('source-a', inaccurate), payload(original))
    assert original in str(error.value)
    assert '仅帮助定位' in str(error.value)
    _validate_path_review_sources(review('source-a', original), payload(original))


def test_unprovided_helper_is_not_replaced_by_unrelated_similar_code():
    original = 'for X, y in train_iter:\n    l = loss(net(X), y)\n    l.mean().backward()'
    quote = 'metric.add(d2l.reduce_sum(l), d2l.size(l))\nreturn metric[0] / metric[1]'
    with pytest.raises(ValueError) as error:
        _validate_path_review_sources(review('source-a', quote), payload(original))
    feedback = str(error.value)
    assert '未定位到' in feedback
    assert '自行复算' in feedback
    assert '原文相近行' not in feedback


def test_punctuation_recovery_restores_exact_source_without_changing_the_finding():
    original = '这里将节点自身也纳入归一化范围，\n等价于在注意力聚合中保留自环信息．'
    data = payload(original)
    raw = review('source-a', original.replace('．', '。').replace('\n', ' ')).model_dump(mode='json')
    fixed = _restore_path_quote_typography(raw, data)
    assert fixed['findings'][0]['evidence_quote'] == original
    assert fixed['findings'][0]['problem'] == raw['findings'][0]['problem']
    assert raw['findings'][0]['evidence_quote'].endswith('。')
    _validate_path_review_sources(PathTeachingReview.model_validate(fixed), data)


@pytest.mark.parametrize('quote', ['当p=1时，输出为0。', '当p<1时，输出为1。', '当p<1时，输出不为0。', '数值为0。5。'])
def test_quote_recovery_never_changes_conditions_signs_numbers_or_negation(quote):
    data = payload('当p<1时，输出为0．数值为0.5．')
    fixed = _restore_path_quote_typography(review('source-a', quote).model_dump(mode='json'), data)
    with pytest.raises(ValueError):
        _validate_path_review_sources(PathTeachingReview.model_validate(fixed), data)
