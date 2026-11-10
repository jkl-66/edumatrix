"""Ask about an actual wrong answer, save specific evidence, adapt next teaching."""
import asyncio
from copy import deepcopy
import hashlib
import json
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from app.auth import get_current_user
from app.database import (run_db_op, DBUser, DBAssessmentAttempt, DBAssessmentQuestionVersion,
                          DBAssessmentQuestion, DBMisconceptionReview)
from app.m2_contracts import StrictModel
from app.learner_output import LEARNER_FEEDBACK_INSTRUCTION
from app.learning_feedback import generate_targeted_feedback
from llm_client import build_async_llm, parse_json_object

router = APIRouter(prefix='/api/v1/m5/assessment/attempts', tags=['learning-inquiry'])
_locks = {}


def _backend():
    return build_async_llm(model='deepseek-v4-flash', allow_fallback=False,
                          thinking_mode='enabled', reasoning_effort='medium', max_tokens=16384)


def _load(db, actor, attempt_id, *, prepare_sources=False):
    from app.m5_api import _assessment_question_readable
    attempt = db.get(DBAssessmentAttempt, attempt_id)
    if attempt is None:
        raise HTTPException(404, '作答记录不存在。')
    if attempt.owner_public_id != actor.public_id:
        raise HTTPException(403, '不能读取他人的作答。')
    version = db.get(DBAssessmentQuestionVersion, attempt.question_version_id)
    if version is None:
        raise HTTPException(404, '题目版本不存在。')
    question = db.get(DBAssessmentQuestion, version.question_id)
    if not _assessment_question_readable(db, question, actor):
        raise HTTPException(403, '当前课程不可访问。')
    if attempt.grading_status != 'graded' or attempt.correct is not False or attempt.feedback_policy == 'after_close':
        raise HTTPException(409, '这次作答不需要错因追问。')
    review = db.query(DBMisconceptionReview).filter_by(attempt_id=attempt_id).first()
    stored = deepcopy((review.evidence or {}).get('inquiry') or {}) if review else {}
    followup = ((stored.get('feedback') or {}).get('next_task') or {})
    if followup.get('question_version_id'):
        latest = db.query(DBAssessmentAttempt).filter_by(owner_public_id=actor.public_id,
            question_version_id=followup['question_version_id']).order_by(DBAssessmentAttempt.submitted_at.desc()).first()
        if latest:
            from app.m5_assessment_core import learner_attempt_payload
            followup['latest_attempt'] = learner_attempt_payload(latest)
    context = {'attempt_id': attempt.id, 'course_id': attempt.course_id,
               'knowledge_point_id': version.primary_knowledge_point_id,
               'question': {'prompt': version.prompt, 'options': version.options,
                            'answer_key': version.answer_key, 'explanation': version.explanation},
               'learner_answer': attempt.answer}
    if prepare_sources and not stored.get('context'):
        from app.canonical_retrieval import retrieve_canonical_sources
        found = retrieve_canonical_sources(db, actor=actor, course_id=attempt.course_id,
            query=version.prompt, source_ref_ids=version.source_ref_ids or None, top_k=4)
        context['sources'] = [{'source_ref_id': item['source_ref'].get('id') or item['source_ref'].get('source_ref_id'),
                               'quote': item['evidence'].content} for item in found['items']]
    return attempt, review, context, stored


def inquiry_learning_needs(events, point_id, attempts):
    """Keep learner-reported reasons separate from scored mastery evidence."""
    needs = {}
    for event in sorted(events, key=lambda row: row.occurred_at):
        if event.event_type != 'learning_inquiry_answered' or event.source != 'backend':
            continue
        payload = event.payload or {}
        if payload.get('knowledge_point_id') != point_id:
            continue
        result = payload.get('interpretation') or {}
        version_id = payload.get('question_version_id')
        # Only a later independent correct response to this same question can
        # resolve this observation. Other scores do not erase the finding.
        if any(a.question_version_id == version_id and a.correct is True
               and a.submitted_at > event.occurred_at and not (a.answer or {}).get('used_hints')
               for a in attempts):
            needs.pop(version_id, None)
            continue
        needs[version_id] = {'criterion_id': 'inquiry_reason', 'basis': result.get('finding', ''),
            'next_focus': result.get('next_focus', ''), 'next_step': result.get('next_focus', ''),
            'learner_quote': result.get('learner_quote', ''),
            'uncertain': result.get('hypothesis_id') == 'uncertain',
            'question_version_id': version_id, 'attempt_id': payload.get('attempt_id'),
            'source_event_id': event.id, 'evidence_kind': 'learner_response'}
    return list(needs.values())


def _store(db, actor, attempt_id, patch):
    from app.learning_generation_jobs import assert_generation_owner
    assert_generation_owner(db)
    _, review, _, stored = _load(db, actor, attempt_id)
    if review is None:
        review = DBMisconceptionReview(owner_public_id=actor.public_id, attempt_id=attempt_id,
            candidate_category='insufficient_evidence', candidate_rationale='先通过一个短问题了解判断依据。')
        db.add(review)
    stored.update(patch)
    review.evidence = {**(review.evidence or {}), 'inquiry': stored}
    db.commit()
    return stored


def public_inquiry(stored):
    feedback = deepcopy(stored.get('feedback'))
    if feedback and not feedback['next_task'].get('latest_attempt'):
        feedback['next_task'].pop('answer', None)
        feedback['next_task'].pop('explanation', None)
    return {'question': (stored.get('plan') or {}).get('question', ''),
            'response': stored.get('response', ''), 'feedback': feedback,
            'event_id': stored.get('event_id'), 'status': 'completed' if stored.get('feedback') else 'ready'}


async def prepare_inquiry(actor, attempt_id, backend=None):
    async with _locks.setdefault((actor.public_id, attempt_id), asyncio.Lock()):
        _, _, context, stored = await run_db_op(lambda db: _load(db, actor, attempt_id, prepare_sources=True))
        if stored.get('plan'):
            return public_inquiry(stored)
        system = (LEARNER_FEEDBACK_INSTRUCTION
            + '同一个错答可能有不同原因。根据本题与实际错答，列出两种有区别的可能原因，再设计一个短追问，'
            '让回答能区分这些原因；不要根据职业推断，不把候选原因写成事实，也不让学生直接确认诊断标签。'
            '优先问他实际用了哪个量、怎样比较或在哪一步作了判断。只输出JSON：'
            'hypotheses（至少两项，每项id、description、discriminating_evidence），question（直接问学生的一小句）。')
        started = perf_counter()
        def validate_plan(plan):
            hypotheses = plan.get('hypotheses') or []
            if (not isinstance(hypotheses, list) or not str(plan.get('question') or '').strip() or len(hypotheses)<2
                    or not all(isinstance(item, dict) and item.get('id') and item.get('description')
                               and item.get('discriminating_evidence') for item in hypotheses)
                    or len({item['id'] for item in hypotheses}) != len(hypotheses)):
                raise ValueError('追问须有至少两种互不相同的原因、区分依据及一个短问题。')
        from app.learning_generation_jobs import component_cache, generate_learning_json
        from app.database import SessionLocal
        with SessionLocal() as cache_db:
            completed, save = component_cache(cache_db)
            plan = await generate_learning_json(backend or _backend(), system=system, request=context,
                role='learning_inquiry_plan', completed=completed, save=save, validate=validate_plan)
        stored = await run_db_op(lambda db: _store(db, actor, attempt_id,
            {'context':context,'plan':plan,'plan_execution':{'seconds':round(perf_counter()-started,3)}}))
        return public_inquiry(stored)


def validate_interpretation(result, plan, response):
    if result.get('hypothesis_id') not in [*(item['id'] for item in plan['hypotheses']), 'uncertain']:
        raise ValueError('追问判断没有对应的依据。')
    if not str(result.get('learner_quote') or '').strip() or result['learner_quote'] not in response:
        raise ValueError('判断引用没有对应学生的实际回答。')
    if not str(result.get('finding') or '').strip() or not str(result.get('next_focus') or '').strip():
        raise ValueError('追问判断缺少具体学习环节。')
    return result


def _record_response(db, actor, attempt_id, response, interpretation):
    from app.learning_generation_jobs import assert_generation_owner
    assert_generation_owner(db)
    from app.m5_learning import record_learning_event, LearningEventInput
    attempt, _, context, stored = _load(db, actor, attempt_id)
    digest = hashlib.sha256((attempt_id+'\n'+response).encode()).hexdigest()[:32]
    event, _ = record_learning_event(db, owner_public_id=actor.public_id, user=actor, trusted_source=True,
        event=LearningEventInput(idempotency_key='inquiry:'+digest, event_type='learning_inquiry_answered',
            course_id=attempt.course_id, object_type='assessment_question_version', object_id=attempt.question_version_id,
            source='backend', payload={'attempt_id':attempt.id,'knowledge_point_id':context['knowledge_point_id'],
                'question_version_id':attempt.question_version_id, 'question':stored['plan']['question'],
                'response':response, 'interpretation':interpretation, 'evidence_kind':'learner_response', 'mastery_changed':False}))
    stored = _store(db, actor, attempt_id, {'response':response,'interpretation':interpretation,'event_id':event.id})
    return stored


async def answer_inquiry(actor, attempt_id, response, backend=None):
    async with _locks.setdefault((actor.public_id, attempt_id), asyncio.Lock()):
        _, _, _, stored = await run_db_op(lambda db: _load(db, actor, attempt_id))
        if not stored.get('plan'):
            raise HTTPException(409, '请先读取这道追问。')
        if stored.get('response') and stored['response'] != response:
            raise HTTPException(409, '这次追问已保存另一份回答。')
        if stored.get('feedback'):
            return public_inquiry(stored)
        backend = backend or _backend()
        if not stored.get('interpretation'):
            system = (LEARNER_FEEDBACK_INSTRUCTION
                + '按追问的实际回答区分候选误解。只返回JSON：hypothesis_id（不能区分则uncertain）、'
                'learner_quote（学生本次回答的连续原句）、finding（具体判断）、next_focus（下一步要解决的具体环节）。'
                '不按原错选或职业猜原因；证据不够时保留uncertain并提出下一项需要辨别的信息。')
            request = {'context':stored['context'],'plan':stored['plan'],'response':response}
            from app.learning_generation_jobs import component_cache, generate_learning_json
            from app.database import SessionLocal
            with SessionLocal() as cache_db:
                completed, save = component_cache(cache_db)
                result = await generate_learning_json(backend, system=system, request=request,
                    role='learning_inquiry_interpretation', completed=completed, save=save,
                    validate=lambda output: validate_interpretation(output, stored['plan'], response))
            stored = await run_db_op(lambda db: _record_response(db,actor,attempt_id,response,result))
        # The saved response and interpretation are the inputs for actual next
        # teaching. Failure here can reuse the evidence without reclassifying it.
        from app.learning_generation_jobs import component_cache
        # Keep cache IO on the same async thread as generation. Each operation
        # fences its token before committing and never creates learning scores.
        from app.database import SessionLocal
        with SessionLocal() as cache_db:
            completed, save = component_cache(cache_db)
            feedback = await generate_targeted_feedback(backend, {'question':stored['context']['question'],
            'learner_answer':stored['context']['learner_answer'], 'inquiry':stored['plan']['question'],
            'learner_response':stored['response'], 'learning_evidence':stored['interpretation'],
            'sources':stored['context'].get('sources') or []}, verify=True,
            completed=completed, save=save)
        stored = await run_db_op(lambda db: _store_feedback(db,actor,attempt_id,feedback))
        return public_inquiry(stored)


def _store_feedback(db, actor, attempt_id, feedback):
    from app.m5_assessment_core import create_question_version, QuestionVersionInput
    from app.learning_generation_jobs import assert_generation_owner
    assert_generation_owner(db)
    attempt, _, context, existing = _load(db, actor, attempt_id)
    if existing.get('feedback'):
        return existing
    task = feedback['next_task']
    original = db.get(DBAssessmentQuestionVersion, attempt.question_version_id)
    _, version = create_question_version(db, owner_public_id=actor.public_id, course_id=attempt.course_id,
        question_type='single_choice', origin='ai_generated', version=QuestionVersionInput(
            prompt=task['prompt'], options=tuple(task['options']), answer_key={'choice':task['answer']},
            scoring_rule={'type':'exact'}, explanation=task['explanation'],
            primary_knowledge_point_id=context['knowledge_point_id'], source_ref_ids=tuple(original.source_ref_ids or [])))
    task['question_version_id'] = version.id
    return _store(db, actor, attempt_id, {'feedback':feedback})


class InquiryAnswerInput(StrictModel):
    response: str = Field(min_length=1)


@router.get('/{attempt_id}/inquiry')
async def get_inquiry(attempt_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(lambda db: inquiry_status(db, current_user, attempt_id))


def inquiry_status(db, actor, attempt_id):
    from app.learning_generation_jobs import task_payload
    from app.database import DBGenerationTask
    _, _, _, stored = _load(db, actor, attempt_id)
    task = db.query(DBGenerationTask).filter(DBGenerationTask.owner_public_id == actor.public_id,
        DBGenerationTask.idempotency_key.in_(['inquiry-prepare:' + attempt_id, 'inquiry-feedback:' + attempt_id])
        ).order_by(DBGenerationTask.created_at.desc()).first()
    result = public_inquiry(stored)
    if task:
        result['generation'] = task_payload(db, task)
    return result


def queue_inquiry(db, actor, attempt_id, response=None):
    from app.learning_generation_jobs import queue_task
    attempt, _, _, stored = _load(db, actor, attempt_id)
    feedback = response is not None
    if feedback:
        if not stored.get('plan'):
            raise HTTPException(409, '请先读取这道追问。')
        if stored.get('response') and stored['response'] != response:
            raise HTTPException(409, '这次追问已保存另一份回答。')
        if stored.get('feedback'):
            return inquiry_status(db, actor, attempt_id)
    elif stored.get('plan'):
        return inquiry_status(db, actor, attempt_id)
    request = {'attempt_id': attempt_id, **({'response': response} if feedback else {})}
    queue_task(db, actor, course_id=attempt.course_id,
        capability='learning_inquiry.feedback' if feedback else 'learning_inquiry.prepare', request=request,
        key=('inquiry-feedback:' if feedback else 'inquiry-prepare:') + attempt_id)
    if feedback:
        _store(db, actor, attempt_id, {'response': response})
    return inquiry_status(db, actor, attempt_id)


@router.post('/{attempt_id}/inquiry')
async def start_inquiry(attempt_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(lambda db: queue_inquiry(db, current_user, attempt_id))


@router.post('/{attempt_id}/inquiry/answer')
async def submit_inquiry(attempt_id: str, payload: InquiryAnswerInput, current_user: DBUser = Depends(get_current_user)):
    if not payload.response.strip():
        raise HTTPException(422, '请写下你的判断过程。')
    return await run_db_op(lambda db: queue_inquiry(db, current_user, attempt_id, payload.response.strip()))
