"""Synthetic semantic outputs test provenance, retry, scope and draft-only changes."""
from copy import deepcopy

import asyncio

from app.course_structure_suggestions import analysis_tasks, analyze_structure, normalize_suggestions, parse_suggestions, parse_review


def task():
    return {'kind': 'same_concept', 'items': [
        {'key': 'a', 'title': '训练误差', 'excerpts': [{'source_id': 'source', 'start': 10, 'end': 25, 'quote': '训练误差又称经验误差。'}]},
        {'key': 'b', 'title': '经验误差', 'excerpts': [{'source_id': 'source', 'start': 60, 'end': 80, 'quote': '经验误差是在训练集上的误差。'}]},
    ]}


def proposal():
    return {'kind': 'same_concept', 'keys': ['a', 'b'], 'title': '训练误差', 'reason': '两处原文描述同一个误差。',
            'evidence': [{'key': 'a', 'quote': '训练误差又称经验误差。'}, {'key': 'b', 'quote': '经验误差是在训练集上的误差。'}]}


def test_only_real_quotes_and_current_keys_form_proposals():
    valid = proposal()
    fake_quote = deepcopy(valid); fake_quote['evidence'][0]['quote'] = '训练和验证误差相同。'
    foreign = deepcopy(valid); foreign['keys'][1] = 'other-course'
    results, rejected = normalize_suggestions({'suggestions': [valid, fake_quote, foreign]}, task())
    assert rejected == 2 and len(results) == 1
    assert results[0]['evidence'][0]['start'] == 10
    assert results[0]['evidence'][1]['end'] == 60+len(valid['evidence'][1]['quote'])
    details = []
    normalize_suggestions({'suggestions': [valid, fake_quote, foreign]}, task(), details)
    assert len(details) == 2
    assert details[0]['proposal'] == fake_quote and '连续原句' in details[0]['reason']
    assert details[1]['proposal'] == foreign and '当前任务' in details[1]['reason']


def test_nonadjacent_chapters_and_unrequested_group_pairs_are_rejected():
    current = task(); current.update(kind='adjacent_chapters', allowed_pairs=[['b', 'a']])
    item = proposal(); item['kind'] = 'adjacent_chapters'
    assert normalize_suggestions({'suggestions': [item]}, current) == ([], 1)
    current = task(); current['group_pairs'] = [['a', 'b'], ['c']]
    assert normalize_suggestions({'suggestions': [proposal()]}, current) == ([], 1)


def sample_structure():
    return {'chapters': [
        {'key': 'c1', 'title': '训练误差', 'source_document_id': 's', 'char_start': 0, 'char_end': 12, 'knowledge_point_ids': ['a']},
        {'key': 'c2', 'title': '经验误差', 'source_document_id': 's', 'char_start': 12, 'char_end': 25, 'knowledge_point_ids': ['b']},
    ], 'concepts': [{'id': 'a', 'title': '训练误差'}, {'id': 'b', 'title': '经验误差'}]}


def test_failed_analysis_retries_only_failed_batches_and_never_edits_structure(monkeypatch):
    import app.course_structure_suggestions as module
    state = {'course_id': 'course', 'structure': sample_structure()}
    state['structure']['concepts'][1]['title'] = '训练误差'
    original = deepcopy(state['structure'])
    bodies = {'s': '训练误差又称经验误差。\n经验误差是在训练集上的误差。'}
    calls = []
    async def model_call(*args, **kwargs):
        calls.append(kwargs['input_summary']['kind'])
        if calls[-1] == 'same_concept' and calls.count('same_concept') == 1:
            raise RuntimeError('synthetic interruption')
        return '{"suggestions": []}'
    monkeypatch.setattr(module, 'audited_legacy_text_call', model_call)
    first = asyncio.run(analyze_structure(state, bodies, object(), 'test-user'))
    assert first['status'] == 'partial'
    state['semantic_analysis'] = first
    second = asyncio.run(analyze_structure(state, bodies, object(), 'test-user'))
    assert second['status'] == 'ready'
    assert calls.count('adjacent_chapters') == 1 and calls.count('same_concept') == 2
    assert state['structure'] == original


def test_source_gap_does_not_become_a_merge_candidate():
    structure = sample_structure()
    structure['chapters'][1]['char_start'] = 18
    result = analysis_tasks(structure, {'s': '训练误差又称经验误差。这里有另一个主题。经验误差。'})
    assert all(item['kind'] != 'adjacent_chapters' for item in result)


def test_structure_edit_reuses_only_batches_with_identical_prompt_inputs(monkeypatch):
    import json
    import app.course_structure_suggestions as module
    tasks = [task(), task()]
    tasks[1]['items'][0]['title'] = '原来的第二批'
    calls = []

    async def model_call(*args, **kwargs):
        calls.append(json.loads(kwargs['user_prompt']))
        return '{"suggestions": []}'

    monkeypatch.setattr(module, 'analysis_tasks', lambda *args: tasks)
    monkeypatch.setattr(module, 'audited_legacy_text_call', model_call)
    state = {'course_id': 'course', 'structure': sample_structure()}
    first = asyncio.run(analyze_structure(state, {}, object(), 'test-user'))
    assert len(calls) == 2 and first['status'] == 'ready'
    state.update(semantic_analysis=None, _analysis_batches=first['batches'])
    tasks[1]['items'][0]['title'] = '修改后的第二批'
    second = asyncio.run(analyze_structure(state, {}, object(), 'test-user'))
    assert len(calls) == 3
    assert calls[-1]['items'][0]['title'] == '修改后的第二批'
    assert sum(b.get('reused', False) for b in second['batches']) == 1


def test_retry_explains_rejections_and_preserves_verified_suggestions(monkeypatch):
    import json
    import app.course_structure_suggestions as module
    current = task()
    current['allowed_pairs'] = [['a', 'b']]
    bad = proposal(); bad['keys'] = ['a', 'foreign']
    calls = []
    reviews = []

    async def model_call(*args, **kwargs):
        data = json.loads(kwargs['user_prompt'])
        if kwargs['operation'] == 'course_structure_scope_review':
            reviews.append(data)
            return json.dumps({'decisions': [{'id': item['id'], 'equivalent': True,
                                              'reason': '两种名称指训练集上的误差。'}
                                             for item in data['suggestions']]})
        calls.append(data)
        if len(calls) == 1:
            return json.dumps({'suggestions': [proposal(), bad]}, ensure_ascii=False)
        if len(calls) == 2:
            raise RuntimeError('synthetic retry interruption')
        return '{"suggestions": []}'

    monkeypatch.setattr(module, 'analysis_tasks', lambda *args: [current])
    monkeypatch.setattr(module, 'audited_legacy_text_call', model_call)
    state = {'course_id': 'course', 'structure': sample_structure()}
    first = asyncio.run(analyze_structure(state, {}, object(), 'test-user'))
    assert first['status'] == 'partial' and len(first['suggestions']) == 1
    state['semantic_analysis'] = first
    interrupted = asyncio.run(analyze_structure(state, {}, object(), 'test-user'))
    assert interrupted['status'] == 'partial'
    assert interrupted['suggestions'] == first['suggestions']
    state['semantic_analysis'] = interrupted
    repaired = asyncio.run(analyze_structure(state, {}, object(), 'test-user'))
    assert repaired['status'] == 'ready' and repaired['suggestions'] == first['suggestions']
    assert len(calls) == 3 and len(reviews) == 1
    for retry in calls[1:]:
        assert retry['previous_rejections'][0]['proposal'] == bad
        assert retry['accepted_pairs'] == [['a', 'b']]
        assert retry['allowed_pairs'] == [['a', 'b']]
    assert [item['status'] for item in repaired['batches'][0]['retry_history']] == ['incomplete', 'failed']


def test_missing_model_output_is_not_a_successful_empty_analysis():
    import pytest
    with pytest.raises(ValueError):
        parse_suggestions('{"chapters": []}')
    assert parse_suggestions('{"suggestions": []}') == {'suggestions': []}


def test_scope_review_must_judge_every_proposal_and_keep_related_concepts_separate():
    import pytest
    with pytest.raises(ValueError):
        parse_review('{"decisions": []}', [{'id': 'one'}])
    rows = parse_review('{"decisions": [{"id":"one","equivalent":false,"reason":"比较两种误差不等于验证误差本身。"}]}', [{'id': 'one'}])
    assert rows[0]['equivalent'] is False


def test_concept_pair_may_choose_either_equivalent_title_as_the_target():
    current = task(); current['allowed_pairs'] = [['b','a']]
    result, rejected = normalize_suggestions({'suggestions':[proposal()]}, current)
    assert len(result) == 1 and rejected == 0


def test_comparing_methods_is_not_the_same_concept_as_one_method():
    current = task()
    current['items'][0]['title'] = '正则化与无正则化的对比'
    current['items'][1]['title'] = '正则化'
    result, rejected = normalize_suggestions({'suggestions': [proposal()]}, current)
    assert result == [] and rejected == 0


def test_observation_or_implementation_keeps_its_distinct_learning_task():
    for concept, task_title in [('验证误差', '验证误差高于训练误差的观察'),
                                ('梯度下降', '梯度下降的从零开始实现')]:
        current = task()
        current['items'][0]['title'] = concept
        current['items'][1]['title'] = task_title
        result, rejected = normalize_suggestions({'suggestions': [proposal()]}, current)
        assert result == [] and rejected == 0
