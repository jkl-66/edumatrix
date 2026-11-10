import asyncio
from copy import deepcopy
import json

import pytest


@pytest.mark.parametrize('kind,original,independent', [
    ('multiple_choice', {'choices':['B','A']}, ['A','B']),
    ('true_false', {'value':False}, False),
    ('fill_blank', {'blanks':['5']}, ['5']),
    ('short_answer', {'reference_answer':'应比较验证误差。'}, '应比较验证误差。'),
])
def test_independent_solver_supports_each_exam_answer_shape(kind, original, independent):
    class TypedSolver(Solver):
        async def generate(self, system, user, role):
            payload = json.loads(user)
            assert payload['question']['type'] == kind
            assert 'answer_key' not in payload['question']
            return json.dumps({'answer':independent, 'justification':'按给定条件独立求解。'})
    item = candidate()
    body = json.loads(item['content'])
    body['question_details'][0].update(question_type=kind, answer_key=original)
    if kind not in {'single_choice', 'multiple_choice'}:
        body['question_details'][0]['options'] = []
    item['content'] = json.dumps(body)
    result = asyncio.run(independently_solve_quizzes(TypedSolver(), [item], []))
    assert result[0]['answers_match']

from app.quiz_verification import independently_solve_quizzes, apply_verification_decisions


def candidate(answer='B', version='quiz-v1'):
    return {'type': 'quiz', 'version_id': version, 'content': json.dumps({'question_details': [{
        'prompt': '求2+3。', 'options': [{'id': 'A', 'text': '4', 'correct': False}, {'id': 'B', 'text': '5', 'correct': True}],
        'answer_key': {'choice': answer}, 'explanation': 'PRIVATE_EXPLANATION', 'hints': ['PRIVATE_HINT'],
        'scoring_rule': {'private_answer': 'B'}}]})}


class Solver:
    model = 'test'
    def __init__(self):
        self.calls = []
    async def generate(self, system, user, role):
        self.calls.append((role, json.loads(user)))
        return json.dumps({'answer': 'B', 'justification': '2+3=5。',
                           'calculations': [{'expression': '2+3', 'claimed_result': '5'}], 'citations': []})


def test_blind_input_and_answer_only_revision_reuses_the_independent_solution():
    backend = Solver()
    cache = {}
    def run(value):
        return asyncio.run(independently_solve_quizzes(backend, [value], [], completed=cache))
    first = run(candidate())
    assert first[0]['answers_match']
    request = backend.calls[0][1]
    assert set(request['question']) == {'prompt', 'type', 'options'}
    assert all(set(item) == {'id', 'text'} for item in request['question']['options'])
    assert 'PRIVATE_' not in json.dumps(request) and 'answer_key' not in json.dumps(request)
    second = run(candidate('A', 'quiz-v2'))
    assert not second[0]['answers_match'] and len(backend.calls) == 1
    changed = candidate()
    changed['content'] = changed['content'].replace('2+3', '1+4')
    run(changed)
    assert len(backend.calls) == 2


def test_failed_sibling_keeps_success_and_retry_only_solves_failed_question():
    class FailingSolver(Solver):
        async def generate(self, system, user, role):
            if json.loads(user)['question']['prompt'] == 'fail' and not self.calls:
                self.calls.append(('failed', None))
                raise RuntimeError('network')
            return await super().generate(system, user, role)
    backend, cache = FailingSolver(), {}
    bad = candidate(); body = json.loads(bad['content']); body['question_details'][0]['prompt'] = 'fail'
    bad['content'] = json.dumps(body)
    with pytest.raises(RuntimeError):
        asyncio.run(independently_solve_quizzes(backend, [bad, candidate()], [], completed=cache))
    assert sum(v['status']=='completed' for v in cache.values()) == 1
    asyncio.run(independently_solve_quizzes(backend, [bad, candidate()], [], completed=cache))
    assert len(backend.calls) == 3  # one failure, two actual successful requests


def test_disagreement_cannot_be_approved_without_adjudication():
    verified = asyncio.run(independently_solve_quizzes(Solver(), [candidate('A')], []))
    base = {'approved': True, 'findings': [], 'rejectedTypes': []}
    with pytest.raises(ValueError):
        apply_verification_decisions(deepcopy(base), verified)
    decision = {'verification_id': 'quiz-v1:1', 'verdict': 'agree', 'evidence': 'Both answers match.'}
    with pytest.raises(ValueError):
        apply_verification_decisions({**base, 'verificationDecisions': [decision]}, verified)
    decision.update(verdict='revise_candidate', evidence='2+3=5，选B；原键A对应4。')
    result = apply_verification_decisions({**base, 'verificationDecisions': [decision]}, verified)
    assert result['approved'] is False and result['rejectedTypes'] == ['quiz']
    assert result['findings'][0]['location'] == '第1题'


def test_cove_enters_existing_reviewer_after_blind_solving():
    from app.resource_bundles import _resource_review_async
    class Reviewer(Solver):
        async def generate(self, system, user, role):
            if role == 'quiz_independent_solver':
                return await super().generate(system, user, role)
            payload = json.loads(user)
            self.calls.append((role, payload))
            verification = payload['independent_quiz_verification'][0]
            return json.dumps({'approved': True, 'summary': '已核对', 'findings': [], 'rejectedTypes': [],
                'teachingReview': [], 'conditionReview': [], 'verificationDecisions': [
                    {'verification_id': verification['verification_id'], 'verdict': 'agree', 'evidence': '2+3=5。'}]})
    backend = Reviewer()
    result = asyncio.run(_resource_review_async(backend, manifest={'verification_mode':'cove'},
                         semantic_plan='', candidates=[candidate()]))
    assert result['approved'] and result['independent_verification'][0]['answers_match']
    assert [role for role, _ in backend.calls] == ['quiz_independent_solver', 'resource_reviewer']
