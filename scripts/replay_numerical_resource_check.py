"""Replay a retained resource through the product numerical checker, read-only.

This is a development replay, not a fresh automatic generation acceptance.
Configure the isolated database and the normal model through environment vars.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.numerical_verification import verify_numerical_content
from app.resource_bundles import _real_model_backend
from app.resource_review_context import teaching_candidate


async def main(run):
    folder = ROOT / 'scratch/automatic-generation-r207/runs' / run
    versions = json.loads((folder / 'versions.json').read_text(encoding='utf8'))
    version = versions[-1]
    candidate = teaching_candidate({'type': version['metadata_json']['resource_type'],
        'version_id': version['id'], 'content': version['content']})
    out = folder / 'numerical-replay-r208'; out.mkdir(exist_ok=True)
    cache_path = out / 'cache.json'
    cache = json.loads(cache_path.read_text(encoding='utf8')) if cache_path.exists() else {}
    def save(key, value):
        cache[key] = value
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf8')
        print(key.split(':')[0], value.get('status', 'saved'), flush=True)
    start = time.time()
    backend = _real_model_backend()
    result = {'version_id': version['id'], 'model': getattr(backend, 'model', ''),
              'evidence_type': 'retained_candidate_live_development_replay'}
    try:
        evidence = await verify_numerical_content(backend, candidate, completed=cache, save=save)
        result.update(evidence=evidence, seconds=round(time.time()-start, 2))
    except Exception as exc:
        result.update(error=str(exc), error_type=type(exc).__name__, seconds=round(time.time()-start, 2))
        (out / ('failure-' + str(int(start)) + '.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        raise
    (out / 'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'seconds':result['seconds'], 'status':evidence['status'],
        'comparisons':len(evidence['comparisons']), 'mismatches':sum(not r['matches'] for r in evidence['comparisons'])}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('run')
    asyncio.run(main(parser.parse_args().run))
