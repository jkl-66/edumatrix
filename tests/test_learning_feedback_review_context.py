"""The feedback review must judge the same learner evidence as generation."""
import asyncio
from copy import deepcopy
import json

import pytest

from app.learning_feedback import generate_targeted_feedback


@pytest.mark.parametrize('prior_review', [None, 'rejected', 'approved'])
def test_actual_answer_reaches_review_and_adjudication_without_leaking_to_solver(prior_review):
    context = {'question': {'prompt': '根据验证误差选择模型。'}, 'learner_answer': {'choice': 'A'},
        'inquiry': '你怎样比较误差？', 'learner_response': '我看验证列，但把误差当成越大越好。',
        'learning_evidence': {'learner_quote': '把误差当成越大越好', 'next_focus': '误差比较方向'},
        'sources': []}
    draft = {'feedback': '你看的是验证列，需要纠正误差比较的方向。', 'next_task': {
        'prompt': '比较相同验证集上的两个候选，应该选择哪个？',
        'options': ['验证误差更高的候选', '验证误差更低的候选'], 'answer': 'B',
        'explanation': '选择验证误差更低的候选。'}}
    saved, calls = {}, []

    class Backend:
        model = 'synthetic-evidence-test'

        async def generate(self, system, user, *, role):
            packet = json.loads(user)
            calls.append((role, packet))
            if role == 'targeted_learning_feedback':
                return json.dumps(draft, ensure_ascii=False)
            if role == 'quiz_independent_solver':
                assert 'learner_evidence' not in packet
                assert context['learner_response'] not in user
                assert 'answer_key' not in packet['question'] and 'explanation' not in packet['question']
                return json.dumps({'answer': 'B', 'justification': '验证误差较低。'})
            assert packet['learner_evidence'] == {k: context[k] for k in context if k != 'sources'}
            if role == 'resource_reviewer':
                return json.dumps({'approved': False, 'summary': '模拟旧审核的缺依据误报',
                    'findings': [{'resourceType': 'quiz', 'location': 'content.feedback',
                        'issue': '没有看到实际回答', 'evidence': draft['feedback'], 'fix': '核对原回答'}],
                    'rejectedTypes': ['quiz'], 'teachingReview': [], 'conditionReview': [],
                    'verificationDecisions': [{'verification_id': v['verification_id'],
                        'verdict': 'agree', 'evidence': '较低误差符合选择规则'}
                        for v in packet.get('independent_quiz_verification', [])]})
            assert role == 'resource_review_adjudicator'
            return json.dumps({'decisions': [{'issue_id': f['issue_id'], 'verdict': 'false_positive',
                'candidate_quote': draft['feedback'], 'reason': '原回答明确说看验证列、把误差当成越大越好。',
                'fix': '', 'source_evidence': []} for f in packet['findings']]})

    def run():
        return asyncio.run(generate_targeted_feedback(Backend(), context, verify=True,
            completed=saved, save=lambda key, value: saved.__setitem__(key, deepcopy(value))))

    assert run() == draft
    if prior_review:
        key = next(k for k in saved if k.startswith('feedback:') and ':review:' not in k)
        saved.clear()
        saved[key] = {'candidate': deepcopy(draft)}
        if prior_review == 'approved':
            saved[key]['approved'] = True
        else:
            saved[key]['findings'] = [{'issue': '删去个人反馈，因为没有作答依据'}]
        calls.clear()
        assert run() == draft
        assert not any(role == 'targeted_learning_feedback' for role, _ in calls)
    assert any(role == 'resource_reviewer' for role, _ in calls)
    assert any(role == 'resource_review_adjudicator' for role, _ in calls)
    before = len(calls)
    assert run() == draft
    assert len(calls) == before
