"""Small live review task for the numeric-local-to-bundle handoff defect."""
import asyncio
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.resource_bundles import _real_model_backend, _resource_review_async
from app.resource_review_context import requirements_snapshot

OUT = ROOT / 'scratch/automatic-generation-r207/focused-defects-r208m/new-bundle-numerical-handoff-r208o'


def save(name, value):
    (OUT / (name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / 'result.json').exists():
        print('Reusing the saved live result.')
        return
    candidates = [
        {'type': 'handout', 'version_id': 'probe-handout-r208o', 'content': json.dumps({
            'concepts': [{'name': '数值秩', 'explanation':
                'A=diag(1,1e-12)。按默认阈值，A的数值秩为1。这里未指定计算接口及默认阈值。'}]}, ensure_ascii=False)},
        {'type': 'deck', 'version_id': 'probe-deck-r208o', 'content': json.dumps({
            'slides': [{'title': '报告数值秩', 'body':
                '数学秩与数值秩需要区分。数值秩的报告要明确矩阵、计算接口和截断阈值，才能复算。'}]}, ensure_ascii=False)},
    ]
    manifest = {'automated_calculation_check': True, 'active_requirements': requirements_snapshot({
        'learning_goal': '核对矩阵、接口和截断阈值是否足以支持数值秩结论。',
        'shared': ['只核对这两个短段的概念和衔接，不要求扩成完整课件或讲义。'], 'by_resource': {}})}
    save('input', {'candidates': candidates, 'manifest': manifest})
    cache_file = OUT / 'cache.json'
    cache = json.loads(cache_file.read_text(encoding='utf8')) if cache_file.exists() else {}
    def keep(key, value):
        cache[key] = value
        save('cache', cache)
    started = time.monotonic()
    try:
        result = await _resource_review_async(_real_model_backend(), manifest=manifest,
            semantic_plan='', candidates=candidates, completed_reviews=cache, save_review=keep)
        checks = result.get('conditionReview', [])
        uncomputed = [item for item in checks if ':uncomputed:' in item.get('claimId', '')]
        save('result', {'evidence_type': '真实模型服务层小型新任务；不发布资源，不计正式评价',
            'seconds': round(time.monotonic()-started, 2), 'review': result,
            'checks': {'numeric_ambiguity_retained': bool(uncomputed),
                       'bundle_merge_completed': True, 'error_not_approved': not result.get('approved')},
            'passed': bool(uncomputed) and not result.get('approved')})
        print('Merged review; numeric ambiguity retained:', bool(uncomputed), flush=True)
    except Exception as exc:
        save('failure-' + str(int(time.time())), {'type': type(exc).__name__, 'error': str(exc),
            'seconds': round(time.monotonic()-started, 2)})
        raise


if __name__ == '__main__':
    asyncio.run(main())
