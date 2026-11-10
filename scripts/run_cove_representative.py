"""CoVe on three retained generated quiz questions, with one injected bad key.

Runs the production resource-review entry and its cache; formal artifacts and
scores are read-only. The injected failure is explicitly a mechanism test.
"""
import argparse
import asyncio
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding='utf-8')


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime-pid', type=int, required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    import psutil
    for key, value in psutil.Process(args.runtime_pid).environ().items():
        if key.startswith('EDUMATRIX_'):
            os.environ[key] = value
    assert Path(os.environ['EDUMATRIX_DB_PATH']).name == 'acceptance.sqlite3'
    from config import CONFIG
    from llm_client import AsyncOpenAIChatLLM
    from app.database import SessionLocal, DBArtifactVersion
    from app.resource_bundles import _generation_manifest, _resource_review_content, _resource_review_async
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    frozen_path = root/'inputs.json'
    if frozen_path.exists():
        frozen = json.loads(frozen_path.read_text(encoding='utf-8'))
    else:
        with SessionLocal() as db:
            version = db.get(DBArtifactVersion, 'av-7040152d4f834ca7946ea52be371c7e2')
            manifest = _generation_manifest(db, version.created_task_id)
            body = json.loads(_resource_review_content(db, version, 'quiz'))
            body = {'title': '模型选择与泛化：独立核验代表题', 'question_details': body['question_details'][:3]}
            # Keep the same original generated questions; verification is a new
            # development projection, not a change to the old resource version.
            manifest = {**manifest, 'verification_mode': 'cove', 'dependency_resources': [],
                'active_requirements': {'learning_goal': '核对本组三道模型选择与泛化题的答案和解析。',
                    'shared': ['保留同一课程专业定义、给定数据与任务。'], 'by_resource': {'quiz': []}},
                'review_decisions': [], 'resource_briefs': []}
            frozen = {'original_version_id': version.id, 'manifest': manifest,
                'candidate': {'type': 'quiz', 'version_id': 'cove-original-r192',
                              'content': json.dumps(body, ensure_ascii=False)},
                'criteria': ['独立输入不含答案/解析/提示/评分键', '正确答案一致',
                             '人为注入错答案触发分歧', '程序与来源裁决', '只改受影响题目并复用独立结果'],
                'note': 'Reuses existing real-generated questions; injected disagreement is synthetic, not a naturally occurring model error.'}
        save(frozen_path, frozen)
    cache_path = root/'review-cache.json'
    cache = json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.exists() else {}
    def remember(key, value):
        cache[key] = value
        save(cache_path, cache)

    class TracedLLM(AsyncOpenAIChatLLM):
        async def generate(self, system_prompt, user_prompt, **kwargs):
            start = time.monotonic()
            record = {'system': system_prompt, 'user': json.loads(user_prompt), 'role': kwargs.get('role'),
                      'model': self.model, 'reasoning_effort': self.reasoning_effort, 'max_tokens': self.max_tokens}
            path = root/'calls'/f'{time.time_ns()}-{kwargs.get("role")}.json'
            try:
                raw = await super().generate(system_prompt, user_prompt, **kwargs)
                record.update(status='completed', output=raw)
                return raw
            except Exception as exc:
                record.update(status='failed', error_type=type(exc).__name__)
                raise
            finally:
                record['seconds'] = round(time.monotonic()-start, 3)
                save(path, record)

    backend = TracedLLM(CONFIG.llm_endpoint, CONFIG.llm_api_key, model='deepseek-v4-flash',
        temperature=0, max_tokens=16384, timeout_seconds=CONFIG.llm_timeout,
        thinking_mode='enabled', reasoning_effort='medium')

    async def run():
        original = frozen['candidate']
        bad = deepcopy(original)
        bad['version_id'] = 'cove-injected-r192'
        body = json.loads(bad['content'])
        body['question_details'][2]['answer_key'] = {'choice': 'B'}
        body['question_details'][2]['explanation'] = 'B的验证与训练MSE差距0.06最大，因此选B。'
        bad['content'] = json.dumps(body, ensure_ascii=False)
        save(root/'injected.json', bad)
        async def review(name, candidate):
            path = root/f'{name}.json'
            if path.exists():
                return json.loads(path.read_text(encoding='utf-8'))
            result = await _resource_review_async(backend, manifest=frozen['manifest'], semantic_plan='',
                candidates=[candidate], completed_reviews=cache, save_review=remember)
            save(path, result)
            print(name, result['approved'], flush=True)
            return result
        # The first run saves three independent solves in two slots. The changed
        # answer then reuses them because its public question and sources match.
        baseline = await review('consistent-review', original)
        disagreement = await review('disagreement-review', bad)
        assert baseline['approved'] and not disagreement['approved']
        gaps = [Decimal(v)-Decimal(t) for v,t in [('0.22','0.06'),('0.16','0.10'),('0.19','0.14')]]
        assert gaps == [Decimal('0.16'),Decimal('0.06'),Decimal('0.05')]
        assert max(range(3), key=lambda i:gaps[i]) == 0
        verification = next(v for v in disagreement['independent_verification'] if v['question_position']==3)
        assert verification['independent_answer'] == 'A'
        fixed = deepcopy(bad); fixed['version_id'] = 'cove-revised-r192'
        revised = json.loads(fixed['content'])
        revised['question_details'][2]['answer_key'] = {'choice':'A'}
        revised['question_details'][2]['explanation'] = '按验证MSE减训练MSE计算：A为0.22−0.06=0.16，B为0.16−0.10=0.06，C为0.19−0.14=0.05；A的差距最大，选A。'
        assert revised['question_details'][:2] == json.loads(original['content'])['question_details'][:2]
        fixed['content'] = json.dumps(revised,ensure_ascii=False)
        save(root/'local-revision.json', {'actor':'Codex with Decimal calculation and independent/source review',
            'candidate':fixed,'gaps':list(map(str,gaps)), 'changed_question':3,'unchanged_questions':[1,2]})
        final = await review('revised-review', fixed)
        assert final['approved']
        solved = [v for k,v in cache.items() if k.startswith('cove:') and v.get('status')=='completed']
        assert len(solved)==3
        for entry in solved:
            assert set(entry['request']) == {'question','sources','verification_plan'}
            assert set(entry['request']['question']) == {'prompt','type','options'}
        save(root/'acceptance.json', {'status':'mechanism_verified','consistent':True,'injected_difference_detected':True,
            'local_revision_passed':True,'independent_calls':len(solved),'reused_on_answer_revision':True,
            'formal_artifacts_changed':False,'source_version':frozen['original_version_id'],
            'gaps':list(map(str,gaps)),'selected':'A','note':frozen['note']})
    asyncio.run(run())


if __name__ == '__main__':
    main()
