"""Reuse the cancelled duplicate path's saved work and review only its failed tail.

No path is generated or published. This is a focused live service check of
deployment reuse and the retained source-quotation failure, not a full path run.
"""
import asyncio
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import path_draft, path_sequence, path_tasks
from app.database import SessionLocal, DBGenerationTask, DBUser, DBCourse, DBProfileSnapshot
from app.learning_generation_jobs import CURRENT_JOB

OUT = ROOT / 'scratch/automatic-generation-r207/focused-defects-r208m/path-saved-tail-r208o'
TASK = 'task-50c34e418ba5467cbce40efb8c784bc6'


def save(name, data):
    (OUT / (name + '.json')).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf8')


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / 'result.json').exists():
        print('Reusing the saved result.')
        return
    started = time.monotonic()
    with SessionLocal() as db:
        assert Path(db.bind.url.database).resolve() == OUT.parents[1] / 'acceptance.sqlite3'
        task = db.get(DBGenerationTask, TASK)
        assert task.status == 'cancelled'
        user = db.query(DBUser).filter_by(public_id=task.owner_public_id).one()
        course = db.get(DBCourse, task.course_id)
        basis = path_tasks._event(db, TASK, 'path.request').payload['learningBasis']
        profile = db.get(DBProfileSnapshot, basis['profile_snapshot_id'])
        facts = path_draft._course_facts(db, course_id=course.id)
        context = path_draft._path_model_context(facts, course=course, profile=profile,
            snapshot=basis['snapshot'], time_budget_minutes=basis['time_budget_minutes'])
        backend = path_draft._build_path_model()
        async def no_regeneration(*args, **kwargs):
            raise AssertionError('The existing selected outcome must be reused without a new model call.')
        backend.generate = no_regeneration
        token = CURRENT_JOB.set({'task_id': TASK})
        try:
            tasks, sequence, sequence_call = await path_sequence.prepare_task_sequence(db,
                llm=backend, user=user, course=course, context=context,
                tasks=path_draft._full_course_tasks(facts), knowledge=facts['knowledge'])
            saved_calls = path_sequence.saved_task_path_calls(db, user=user, course=course, field='path_batch_result')
        finally:
            CURRENT_JOB.reset(token)
        assert sequence_call == 'mcall-63a032fd9ad448dc9cfab389e1347793'
        assigned = tasks[-2:]
        chapter_ids = {item['target_object_id'] for item in assigned}
        def validate(value):
            parsed = path_draft._validate_model_plan_output(value, facts=facts,
                owner_public_id=user.public_id, course_id=course.id, session=db,
                required_chapter_ids=chapter_ids)
            return path_draft._validate_task_batch(parsed, assigned,
                time_budget_minutes=basis['time_budget_minutes'])
        candidates = []
        for call in saved_calls:
            try:
                parsed = validate(call.input_summary['path_batch_result']['output'])
            except (path_draft.PathDraftError, ValueError):
                continue
            candidates.append((call, parsed))
        assert candidates
        call, candidate = candidates[0]
        context['course_graph']['chapters'] = [chapter for chapter in context['course_graph']['chapters']
                                               if chapter['id'] in chapter_ids]
        context['teaching_units'] = [unit for unit in context['teaching_units']
                                     if unit['key'] in {item['teaching_unit_key'] for item in assigned}]
        payload = {'task': 'focused_saved_path_tail_review', 'context': context,
            'required_learning_tasks': assigned, 'near_term_learning': sequence.model_dump(mode='json'),
            'course_learning_outline': [{key: item[key] for key in ('node_key', 'title', 'teaching_goal', 'prerequisites')}
                                        for item in tasks],
            'candidate_reuse': {'original_input_hash': call.input_summary['path_batch_result']['input_hash'],
                'instruction': '复用本任务原末批候选，仅核对这两项及真实原文。此前引文多写了“对比”；复制实际连续原文，不能改写教材引文。当前不是重新生成或发布整条路径。'}}
        save('input', {'task_id': TASK, 'sequence_call_id': sequence_call,
            'saved_candidate_call_ids': [item.id for item in saved_calls],
            'reviewed_candidate_call_id': call.id, 'candidate': candidate.model_dump(mode='json'), 'payload': payload})
        try:
            output, review_id = await path_draft._review_path_batch(db,
                llm=path_draft._build_path_model(), user=user, course=course, payload=payload,
                candidate=candidate, generator_call=call, validate_batch=validate)
            save('result', {'evidence_type': '真实模型定点复核；未发布整条路径或重生成成功批次',
                'seconds': round(time.monotonic()-started, 2), 'review_call_id': review_id,
                'checks': {'original_sequence_reused': True, 'saved_candidate_reused': True,
                           'current_sources_and_runtime_reviewed': True},
                'output': output.model_dump(mode='json')})
            print('Original sequence and saved tail reused; live review completed.', flush=True)
        except Exception as exc:
            save('failure-' + str(int(time.time())), {'type': type(exc).__name__, 'error': str(exc),
                'seconds': round(time.monotonic()-started, 2)})
            raise


if __name__ == '__main__':
    asyncio.run(main())
