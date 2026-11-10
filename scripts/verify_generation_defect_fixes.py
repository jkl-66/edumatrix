"""Focused live service checks; never publish or edit retained teaching drafts.

Replays exact failed passages, then exercises the repaired mechanism on small
new inputs. These are development mechanism checks, separate from learner UI
evidence, fresh resource generation and the formal evaluation dataset.
"""
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.resource_bundles import _real_model_backend, _resource_review_async
from app.resource_review_adjudication import adjudicate_review
from app.resource_review_parts import conditional_teaching_claims
from app.resource_review_context import requirements_snapshot
from app.feynman import FeynmanState, _live_evaluate
from app.database import DBArtifact, SessionLocal

EVIDENCE = ROOT / 'scratch/automatic-generation-r207'
OUT = EVIDENCE / 'focused-defects-r208m'


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


def requirements(kind, goal):
    return requirements_snapshot({'learning_goal': goal, 'shared': [], 'by_resource': {kind: [goal]}})


def original(run, version_id):
    folder = EVIDENCE / 'runs' / run
    versions = json.loads((folder / 'versions.json').read_text(encoding='utf8'))
    version = next(v for v in versions if v['id'] == version_id)
    events = json.loads((folder / 'events.json').read_text(encoding='utf8'))
    manifest = next(e['payload']['manifest'] for e in events if e['event_type'] == 'resource_generation.requested')
    return version, events, manifest


async def review(name, candidate, manifest, scope=None):
    folder = OUT / name
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / 'result.json').exists():
        print(name, 'reusing saved live result', flush=True)
        return
    cache_path = folder / 'cache.json'
    cache = json.loads(cache_path.read_text(encoding='utf8')) if cache_path.exists() else {}
    def save(key, value):
        cache[key] = value
        write(cache_path, cache)
    write(folder / 'input.json', {'candidate': candidate, 'manifest': manifest,
          'scope': scope, 'claims': conditional_teaching_claims([candidate], scope)})
    started = time.time()
    backend = _real_model_backend()
    try:
        verdict = await _resource_review_async(backend, manifest=manifest,
            semantic_plan='', candidates=[candidate], _grouped=True, _review_scope=scope,
            completed_reviews=cache, save_review=save)
        write(folder / 'review.json', verdict)
        adjudicated = await adjudicate_review(backend, manifest=manifest,
            candidates=[candidate], review=verdict, completed=cache, save=save)
        write(folder / 'result.json', {'kind': 'live_scoped_service_verification',
            'seconds': round(time.time()-started, 2), 'review': verdict, 'adjudicated': adjudicated})
        print(name, 'approved', adjudicated.get('approved'), 'findings', len(adjudicated.get('findings', [])), flush=True)
    except Exception as exc:
        write(folder / f'failure-{int(started)}.json', {'error': str(exc), 'type': type(exc).__name__, 'seconds': time.time()-started})
        raise


async def numerical():
    version, events, manifest = original('single-deck-r208h', 'av-de834d93639c4c92b68f47eff86e94fa')
    plan = next(e['payload']['review'] for e in events if e['sequence'] == 109)
    candidate = {'type': 'deck', 'version_id': version['id'], 'content': version['content'],
        'runtime_verification': {'numerical': {'plan': plan}}}
    paths = ['content.slides[3].body']
    await review('original-numerical-ambiguity-r208n', candidate, manifest,
                 {'stage': 'section', 'candidate_index': 0, 'paths': paths})
    # New synthetic ambiguity, explicitly supplied as an uncomputed result.
    # This isolates the formerly dropped handoff from numerical analysis to review.
    quote = '矩阵diag(1, ε)的数值秩为1。'
    candidate = {'type': 'handout', 'version_id': 'r208m-new-ambiguous-rank',
        'content': json.dumps({'example': 'ε是尚未给定的非负实数。' + quote}, ensure_ascii=False),
        'runtime_verification': {'numerical': {'plan': {'cases': [], 'not_computed': [
            {'path': 'content.example', 'quote': quote,
             'reason': 'ε的取值与数值秩的阈值均未指定，不能给唯一数值。'}]}}}}
    await review('new-numerical-handoff', candidate,
        {'active_requirements': requirements('handout', '本次只核示例数值断言及其成立条件。')},
        {'stage': 'section', 'candidate_index': 0, 'paths': ['content.example']})


async def feynman():
    version, _, manifest = original('single-feynman-r208h', 'av-36572c6e7f6a4a3e94bca3bd3d2c4c8c')
    paragraphs = [p for p in version['content'].split('\n\n')
                  if ('泛化误差' in p and '只能' in p) or ('无限' in p and ('虚构' in p or '精确' in p))]
    assert paragraphs
    excerpt = '\n\n'.join(paragraphs)
    await review('original-feynman-definition', {'type': 'feynman', 'version_id': version['id'], 'content': excerpt},
        {**manifest, 'active_requirements': requirements('feynman', '本次只核原材料泛化误差定义、可计算条件与估计方式。')},
        {'stage': 'section', 'candidate_index': 0, 'paths': ['content']})
    folder = OUT / 'new-feynman-evaluation'
    folder.mkdir(exist_ok=True)
    if (folder / 'result.json').exists():
        return
    material = excerpt + '\n\n练习：说明泛化误差的定义，以及何时可精确计算、何时需样本估计。举一个已知离散总体的数值例子，并说明交叉验证选模后如何最终评价。'
    text = ('泛化误差是固定模型在目标数据分布下的期望损失，无须假设实际拿到无限样本。'
        '通常总体分布未知，才用验证集、交叉验证或独立测试集估计未见表现；不只测试集可以估计。'
        '若分布和损失已知，能用求和或积分精确计算。例如两类结果概率为0.75和0.25，'
        '损失分别为1和4，期望损失是0.75×1+0.25×4=1.75。'
        '交叉验证分数用于选模后，所选方案在同批数据上的分数可能偏乐观；'
        '最终评价要用未参与选择的独立数据或正确的外层交叉验证。材料把分布未知与无限样本混淆，'
        '我按目标分布的期望理解，不把估计方法当定义。')
    with SessionLocal() as db:
        artifact = db.get(DBArtifact, version['artifact_id'])
        owner = artifact.owner_public_id
        course_id = artifact.course_id
    state = FeynmanState(session_id='r208m-focused-feynman', owner_public_id=owner, course_id=course_id,
        source_resource_id=version['artifact_id'], source_resource_version_id=version['id'],
        source_resource_content_sha256=hashlib.sha256(version['content'].encode()).hexdigest(),
        title='泛化误差定义与估计', course_title='人工智能与深度学习', knowledge_point_title='模型选择与泛化',
        learning_material=material, task_prompt='解释定义、计算/估计条件，给离散例子并说明选模后的最终评价。',
        adaptation_note='', active_requirements=requirements('feynman', '仅评价当前短复述任务，不要求旧长材料的其它练习。'))
    write(folder / 'input.json', {'kind': 'new_live_service_evaluation_with_retained_faulty_excerpt',
        'state': state.model_dump(mode='json'), 'student_text': text})
    start = time.time()
    try:
        result = await asyncio.to_thread(_live_evaluate, text, state, round_number=1)
        write(folder / 'result.json', {'seconds': time.time()-start, 'evaluation': result.model_dump(mode='json')})
        print('new-feynman-evaluation', result.score, flush=True)
    except Exception as exc:
        write(folder / f'failure-{int(start)}.json', {'error': str(exc), 'type': type(exc).__name__})
        raise


async def main():
    OUT.mkdir(exist_ok=True)
    results = await asyncio.gather(numerical(), feynman(), return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            raise result


if __name__ == '__main__':
    asyncio.run(main())
