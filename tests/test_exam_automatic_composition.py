"""Composition faults must repair only their named question slots."""
from types import SimpleNamespace
import json
import pytest

from app import m5_exam_core as core
from app import learning_generation_jobs as jobs


def config():
    return core.IntelligentExamConfigInput(idempotency_key='composition-test', course_id='c',
        theme='模型选择与数据泄漏', question_type_counts={'single_choice': 3})


def item(position, prompt):
    return (SimpleNamespace(id=f'v{position}', prompt=prompt, options=['A', 'B'],
        primary_knowledge_point_id='kp', answer_key={'choice':'A'}, explanation='解释'),
        SimpleNamespace(id=f'q{position}', question_type='single_choice'))


def test_duplicate_is_located_without_model_and_unique_whole_exam_gets_coverage_check(monkeypatch):
    calls = []
    async def gateway(*args, **kwargs):
        request = json.loads(kwargs['user_prompt']); calls.append(request)
        assert len(request['questions']) == 3 and request['theme'] == config().theme
        return SimpleNamespace(structured_output={'approved':True, 'findings':[]})
    monkeypatch.setattr(core, 'execute_registered_structured_call', gateway)
    result = core._review_exam_composition(None, llm=None, owner_public_id='u', config=config(),
        blueprint={}, selected=[item(1,'题甲'),item(2,'题甲'),item(3,'题丙')])
    assert not result['approved'] and result['findings'][0]['question_positions'] == [2]
    assert not calls
    assert core._review_exam_composition(None, llm=None, owner_public_id='u', config=config(),
        blueprint={}, selected=[item(1,'题甲'),item(2,'题乙'),item(3,'题丙')])['approved']
    assert len(calls) == 1


def test_composition_rejection_reuses_other_questions_on_next_automatic_attempt(monkeypatch):
    cache, generated, inspected = {}, [], []
    monkeypatch.setattr(jobs, 'component_cache', lambda db: (cache, cache.__setitem__))
    def generate(db, **kw):
        pos, state = kw['blueprint']['question_position'], kw['state']
        if not state.get('approved'):
            generated.append(pos)
        if pos == 2 and state.get('findings'):
            assert len(kw['blueprint']['retained_questions']) == 2
        meta = {'call_id':f'call{pos}', 'trace_id':'trace'}
        kw['save_state']({**state,'approved':True,'metadata':meta,'output':{}})
        return [item(pos, f'题{pos}')], meta
    def review(*args, **kwargs):
        inspected.append(True)
        return {'approved':len(inspected)>1, 'findings':[] if len(inspected)>1 else [
            {'question_positions':[2],'issue':'重复','evidence':'题干比较','fix':'补预处理边界'}]}
    monkeypatch.setattr(core, '_generate_llm_exam_batch', generate)
    monkeypatch.setattr(core, '_review_exam_composition', review)
    def run():
        return core._generate_llm_exam_items(None, owner_public_id='u', config=config(), blueprint={},
            points=[SimpleNamespace(id='kp')], llm=SimpleNamespace(model='test'))
    with pytest.raises(core.FormalExamError, match='重复'):
        run()
    selected, metadata = run()
    assert generated == [1,2,3,2]
    assert len(selected) == 3 and metadata['review']['composition']['approved']


@pytest.mark.parametrize('count', [3, 6, 67, 201, 10001])
def test_large_exam_scoring_keeps_every_question_positive_and_total_one_hundred(count):
    from decimal import Decimal
    points = core._equal_exam_points(count)
    assert len(points) == count and min(points) > 0
    assert sum(Decimal(str(value)) for value in points) == Decimal(100)
    assert max(points) - min(points) <= 10 ** -max(2, len(str(count))) + 1e-12
