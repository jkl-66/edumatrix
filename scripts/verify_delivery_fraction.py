"""Replay the exact saved fraction failure and run one short real computation."""
import asyncio
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import numerical_verification as nv
from app.resource_bundles import _real_model_backend, _resource_review_content
from app.database import DBArtifactVersion
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from llm_client import parse_json_object

OUT = ROOT/'outputs/current-runtime-20261110/validation/fraction-r208z'
TASK = 'task-f49f1d70af5e480ea30e413d47e873b4'


def save(name, value):
    (OUT/(name+'.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    database = ROOT/'scratch/current-runtime-validation-r208x/edumatrix.db'
    with sqlite3.connect(database.as_uri()+'?mode=ro', uri=True) as db:
        failure = json.loads(db.execute('select payload from task_events where task_id=? and sequence=91', (TASK,)).fetchone()[0])
        state = db.execute('select status,automation_state from generation_tasks where id=?', (TASK,)).fetchone()
    engine = create_engine('sqlite:///' + database.as_posix())
    with Session(engine) as db:
        content = _resource_review_content(db, db.get(DBArtifactVersion, 'av-84ac030cb43648e4a80bd186da5417ea'), 'quiz')
    engine.dispose()
    save('original-failure', failure)
    plan = nv._validate_plan(parse_json_object(failure['review']['raw']), {'content': content})
    save('original-replay', {'passed': True, 'plan': plan, 'task_state_before_fix': state,
        'scope': '原91事件的完整抽取原稿直接重放；原任务在本修复前已自动完成，不将本次重放称为任务重试。'})
    if (OUT/'new-result.json').exists():
        print('Reusing successful new fraction computation.', flush=True)
        return
    candidate = {'type': 'handout', 'content':
        '袋中有3个红球和4个蓝球，各球被抽到的机会相等。随机取一个球，抽到红球的概率=3/7。'}
    save('new-input', candidate)
    cache_file = OUT/'new-cache.json'
    cache = json.loads(cache_file.read_text('utf8')) if cache_file.exists() else {}
    def remember(key, value):
        cache[key] = value
        save('new-cache', cache)
    started = time.monotonic()
    try:
        result = await nv.verify_numerical_content(_real_model_backend(), candidate, completed=cache, save=remember)
        claims = result['comparisons']
        assert result['status'] == 'computed' and claims and all(c['matches'] for c in claims)
        assert any('3/7' in c['values'] for c in claims)
        save('new-result', {'passed': True, 'seconds': time.monotonic()-started, 'result': result,
            'evidence_kind': '合成短句；真实模型抽取与独立编程，实际本地执行；不新增学习成绩。'})
        print('Original failure replay and new real fraction calculation passed.', flush=True)
    except Exception as error:
        save('failure-'+str(int(time.time())), {'error': str(error), 'seconds': time.monotonic()-started})
        raise


if __name__ == '__main__':
    asyncio.run(main())
