"""Targeted feedback shared by inquiry follow-up and teaching-policy experiments."""
from copy import copy
import json
from pathlib import Path
import hashlib

from app.learner_output import LEARNER_FEEDBACK_INSTRUCTION
from app.model_evaluation_rules import MODEL_EVALUATION_INSTRUCTION
from llm_client import parse_json_object

BASE_STRATEGY = ('根据学习者对追问的实际回答，指出这次判断中需要改变的一步，给出简短解释，'
                 '再给一道有完整新数据的小题检查这个环节。保留已经会的部分。')
POLICY_PATH = Path(__file__).with_name('data') / 'learning_feedback_policy.json'


def selected_strategy():
    if POLICY_PATH.exists():
        return json.loads(POLICY_PATH.read_text(encoding='utf-8'))['instruction']
    return BASE_STRATEGY


async def generate_targeted_feedback(backend, context, *, strategy=None, verify=False, completed=None, save=None):
    llm = copy(backend)
    llm.reasoning_effort = 'medium'
    llm.thinking_mode = 'enabled'
    llm.max_tokens = 16384
    system = (LEARNER_FEEDBACK_INSTRUCTION + (strategy if strategy is not None else selected_strategy())
        + '只返回JSON：feedback（给学生的讲解）、next_task（prompt、options字符串数组、answer选项字母、explanation）。'
        'next_task的答案会在学生主动检查后显示；题干不能直接透露答案。依据实际回答区分错因，不能根据职业猜测。'
        + MODEL_EVALUATION_INSTRUCTION + '用必要的数字、对照或因果步骤讲清，不复述内部策略。')
    completed = completed if completed is not None else {}
    save = save or (lambda key, value: None)
    key = 'feedback:' + hashlib.sha256(json.dumps([system, context], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    state = dict(completed.get(key) or {}) if verify else {}
    learner_evidence = {name: context.get(name) for name in (
        'question', 'learner_answer', 'inquiry', 'learner_response', 'learning_evidence')}
    review_basis = hashlib.sha256(json.dumps(learner_evidence, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if verify and state.get('review_basis') != review_basis:
        # Older reviews did not receive the learner's actual answer. Recheck
        # their saved draft against the complete evidence before revising it.
        state = {name: state[name] for name in ('candidate', 'validation_error') if name in state}
        state['review_basis'] = review_basis
    if state.get('approved'):
        return state['candidate']
    request = ({**context, 'previous_draft': state['candidate'], 'required_corrections': state.get('findings') or state.get('validation_error')}
               if state.get('candidate') and (state.get('findings') or state.get('validation_error')) else context)
    # A provider interruption during review reuses the saved candidate.
    if state.get('candidate') and not state.get('findings') and not state.get('validation_error'):
        result = state['candidate']
    else:
        if verify:
            from app.learning_generation_jobs import generate_learning_json
            result = await generate_learning_json(llm, system=system, request=request,
                role='targeted_learning_feedback', completed=completed, save=save)
        else:
            result = parse_json_object(await llm.generate(system, json.dumps(request, ensure_ascii=False), role='targeted_learning_feedback'))
        if verify:
            state = {**state, 'candidate': result}
            save(key, state)
    task = result.get('next_task') or {}
    if (not str(result.get('feedback') or '').strip() or not str(task.get('prompt') or '').strip()
            or not isinstance(task.get('options'), list) or len(task['options']) < 2
            or not all(isinstance(v,str) and v.strip() for v in task['options'])
            or task.get('answer') not in [chr(65+i) for i in range(len(task['options']))]
            or not str(task.get('explanation') or '').strip()):
        if verify:
            save(key, {**state, 'validation_error': '后续讲解或练习须包含完整题干、选项、合法答案和解析。'})
        raise ValueError('后续讲解或练习尚未生成完整。')
    if verify:
        from app.resource_bundles import _resource_review_async
        from app.resource_review_adjudication import adjudicate_review
        from app.learning_generation_jobs import LearningGenerationError
        candidate = {'type': 'quiz', 'version_id': hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest(),
            'content_format': 'json', 'title': '后续讲解与练习', 'content': json.dumps({
                'feedback': result['feedback'], 'question_details': [{**task, 'answer_key': {'choice': task['answer']}}]}, ensure_ascii=False)}
        focus = (context.get('learning_evidence') or {}).get('next_focus') or '根据实际回答补齐当前误解'
        manifest = {'verification_mode': 'cove', 'automated_calculation_check': True, 'assessment_mode': 'learning_feedback',
            'learner_evidence': learner_evidence,
            'context': {'learning_goal': focus},
            'active_requirements': {'learning_goal': focus, 'shared': [
                '先给针对实际回答的准确反馈，再以完整新题检查同一知识环节；必要条件明确，不提前透露新题答案。'], 'by_resource': {}},
            'input_snapshot': {'source_snapshots': {'quiz': context.get('sources') or []}}}
        review = await _resource_review_async(llm, manifest=manifest, semantic_plan='', candidates=[candidate],
                                              completed_reviews=completed, save_review=save)
        save(key + ':review:' + candidate['version_id'], review)
        review = await adjudicate_review(llm, manifest=manifest, candidates=[candidate], review=review,
                                         completed=completed, save=save)
        if review.get('approved') is not True or review.get('rejectedTypes'):
            save(key, {**state, 'candidate': result, 'findings': review.get('findings') or [{'issue': review.get('summary')}],
                       'review': review})
            raise LearningGenerationError('learning_feedback.review_rejected', json.dumps(review, ensure_ascii=False))
        save(key, {**state, 'candidate': result, 'approved': True, 'review': review})
    return result
