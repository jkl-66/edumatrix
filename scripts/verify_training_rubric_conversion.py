"""Replay the saved conversion defect, then generate one small live rubric task."""
import asyncio
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import resource_bundles as bundles
from app.database import SessionLocal

OUT = ROOT / 'scratch/automatic-generation-r207/focused-defects-r208m/training-rubric-r208p'


def save(name, value):
    (OUT / (name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    task_id = 'task-fd30eb8b784e457d85e1d56faa86a2a9'
    original = json.loads((OUT.parent / 'training-rubric-original-r208p.json').read_text(encoding='utf8'))
    with SessionLocal() as db:
        assert Path(db.bind.url.database).resolve() == OUT.parents[1] / 'acceptance.sqlite3'
        task = db.get(bundles.DBGenerationTask, task_id)
        manifest = bundles._generation_manifest(db, task_id)
        version = db.get(bundles.DBArtifactVersion, 'av-42c5b4770b564c35b26ce47b92fbc8d2')
        item = next(item for item in manifest['items'] if item['type'] == 'training_task')
        sources = bundles._source_snapshots(db, course_id=task.course_id,
            source_ref_ids=item['source_ref_ids'], require_available=True)
        body = json.loads(version.content)
        kwargs = dict(item=item, manifest=manifest, source_snapshots=sources,
            linked_resource_ids=[body['linkedSandboxId'], body['linkedModelId']])
        recovered = bundles._saved_training_rubric_payload(
            {'content': version.content}, {'original': original}, **kwargs)
        assert recovered == original
        result = json.loads(bundles._llm_resource_content(resource_type='training_task',
            llm_payload=recovered, **kwargs))
        assert result['rubric'] == original['rubric'] and sum(r['points'] for r in result['rubric'][:-1]) == 100
        assert result['rubric'][-1]['points'] == 0
        save('original-replay', {'task_id': task_id, 'version_id': version.id,
            'before_rubric': body['rubric'], 'after_rubric': result['rubric'],
            'content_outside_rubric_unchanged': all(body[k] == v for k, v in result.items() if k != 'rubric'),
            'model_payload_reused': True, 'passed': True})

    if (OUT / 'new-result.json').exists():
        print('Reused saved small live result.')
        return
    short_manifest = {'course_id': manifest['course_id'], 'knowledge_point_id': manifest['knowledge_point_id'],
        'context': {'course_title': manifest['context']['course_title'],
            'knowledge_point_title': '训练误差与泛化误差',
            'learning_goal': '用同一验证集比较两个模型，并区分核心学习任务与可选拓展。'},
        'active_requirements': {'learning_goal': '正确比较同一验证集上的误差并保持可选任务不计核心分。',
            'shared': ['只生成三步短任务，已有配套代码和实验可复用。第一步核对已给定的代码输出表（甲训练MSE0.01、验证0.3；乙训练0.08、验证0.1），第二步写一句选择理由和总结，第三步可选交互拓展。核心两项分别60、40分，可选项0分。预计核心5分钟。只写必要说明，不重抄代码或创建长数据。'],
            'by_resource': {}}}
    item = {'title': '验证选择：核心与可选任务'}
    sources = [source for source in sources if source['source_ref_id'] == 'ref-6f1ab7bc82973c373a4727bb']
    assert sources
    save('new-input', {'manifest': short_manifest, 'item': item, 'sources': sources})
    began = time.monotonic()
    raw_path = OUT / 'new-model-output.json'
    try:
        raw = json.loads(raw_path.read_text(encoding='utf8')) if raw_path.exists() else await bundles._real_model_payload_async(
            bundles._real_model_backend(), resource_type='training_task', item=item,
            manifest=short_manifest, source_snapshots=sources)
        save('new-model-output', raw)
        content = json.loads(bundles._llm_resource_content(resource_type='training_task', item=item,
            manifest=short_manifest, source_snapshots=sources, linked_resource_ids=[], llm_payload=raw))
        assert [r['points'] for r in content['rubric']] == [60, 40, 0]
        assert content['rubric'] == raw['rubric']
        save('new-result', {'evidence_type': '真实模型服务层短任务及实际转换；未发布资源，不计正式评价',
            'seconds': round(time.monotonic()-began, 2), 'content': content, 'passed': True})
        print('Original replay and small live scoring task passed.', flush=True)
    except Exception as exc:
        save('failure-' + str(int(time.time())), {'type': type(exc).__name__, 'error': str(exc),
            'seconds': round(time.monotonic()-began, 2)})
        raise


if __name__ == '__main__':
    asyncio.run(main())
