"""Replay the saved null-version failure and one small live adjudication."""
import asyncio
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.database import SessionLocal, DBTaskEvent, DBArtifactVersion, DBArtifact
from app import resource_bundles as bundles
from app.resource_review_adjudication import _validate_decisions, adjudicate_review

OUT = ROOT / 'scratch/automatic-generation-r207/focused-defects-r208m/review-version-r208r'


def save(name, value):
    (OUT / f'{name}.json').write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    task_id = 'task-7246f1d6f3004a9fa2fee21d8b696c08'
    with SessionLocal() as db:
        assert Path(db.bind.url.database).resolve() == OUT.parents[1] / 'acceptance.sqlite3'
        def event(sequence):
            return db.query(DBTaskEvent).filter_by(task_id=task_id, sequence=sequence).one().payload
        original, failed = event(251), event(252)['review']
        candidates = []
        for version_id in original['version_ids']:
            version = db.get(DBArtifactVersion, version_id)
            artifact = db.get(DBArtifact, version.artifact_id)
            candidates.append({'type': artifact.artifact_type, 'version_id': version_id, 'content': version.content})
        manifest = bundles._generation_manifest(db, task_id)
    sources = {s['source_ref_id']: s for values in manifest['input_snapshot']['source_snapshots'].values() for s in values}
    save('original-input', {'review': original, 'failed': failed, 'candidates': candidates})
    # Replay precisely the failed item; other historic decisions are not
    # re-approved by this focused provenance test.
    decisions = [d for d in json.loads(failed['output'])['decisions']
                 if d['issue_id'] == 'cea098063717d737fc2d']
    findings = [f for f in original['review']['findings'] if f['issue_id'] == decisions[0]['issue_id']]
    result = _validate_decisions(decisions, findings=findings,
                                sources=sources, candidates=candidates, review=original['review'])
    target = next(d for d in result['adjudication'] if d['issue_id'] == 'cea098063717d737fc2d')
    assert target['version_id'] and target['verdict'] == 'false_positive'
    save('original-replay', {'passed': True, 'target': target, 'remaining_findings': result['findings'],
                            'scope': '验证原引用与版本绑定；旧裁决原样复放，不作为当前教学知识裁决或发布。'})
    if (OUT / 'new-result.json').exists():
        print('Reused successful live result.', flush=True)
        return
    candidates = [
        {'type': 'code_sandbox', 'version_id': 'short-code-r208r',
         'content': '给定训练误差0.1和验证误差0.2，二者评价的数据不同，可以不同。'},
        {'type': 'handout', 'version_id': 'short-handout-r208r',
         'content': '测试集应反复用于选择超参数，最后报告其中最小的测试误差作为独立估计。'}]
    review = {'approved': False, 'findings': [
        {'resourceType': 'code_sandbox', 'version_id': None, 'issue_id': 'different-loss',
         'location': 'content', 'issue': '训练与验证误差不同是矛盾。'},
        {'resourceType': 'handout', 'version_id': None, 'issue_id': 'test-selection',
         'location': 'content', 'issue': '反复根据测试集选超参数造成选择偏差，不能称独立估计。'}]}
    manifest = {'active_requirements': {'learning_goal': '正确区分训练、验证及测试的作用。'}}
    save('new-input', {'candidates': candidates, 'review': review, 'manifest': manifest})
    start = time.monotonic()
    try:
        result = await adjudicate_review(bundles._real_model_backend(), manifest=manifest,
            candidates=candidates, review=review,
            save=lambda key, value: save('call-' + key.replace(':', '-'), value))
        by_id = {d['issue_id']: d for d in result['adjudication']}
        assert by_id['different-loss']['verdict'] == 'false_positive'
        assert by_id['test-selection']['verdict'] == 'confirmed'
        assert all(d['version_id'] for d in by_id.values()) and not result['approved']
        save('new-result', {'passed': True, 'seconds': round(time.monotonic()-start, 2),
                           'evidence_type': '合成短教学输入，真实模型裁决；未生成或发布整包。', 'result': result})
        print('Saved failure replay and small live adjudication passed.', flush=True)
    except Exception as exc:
        save('failure-' + str(int(time.time())), {'error': str(exc), 'seconds': round(time.monotonic()-start, 2)})
        raise


if __name__ == '__main__':
    asyncio.run(main())
