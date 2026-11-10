"""One live service-level exam while a normal practice answer updates its owner."""
import asyncio
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import m5_api
from app.database import SessionLocal, DBUser
from app.learning_generation_jobs import course_generation_basis
from app.profile_onboarding import latest_profile_snapshot_for_course
from app.m5_exam_core import IntelligentExamConfigInput
import requests

OUT = ROOT / 'scratch/automatic-generation-r207/focused-defects-r208m/exam-learning-basis-r208q'
BASE = 'http://127.0.0.1:8955'


def save(name, value):
    (OUT / (name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / 'result.json').exists():
        print('Reused saved live result.'); return
    root = ROOT / 'scratch/automatic-generation-r207'
    config = json.loads((root / 'runs/review-exam-r208o/request.json').read_text('utf8'))['configuration']
    config.update(idempotency_key='r208q-exam-learning-basis', title='复习选择核对',
        theme='在固定的同一验证集上比较两个模型的验证MSE，越小越好；只出一道简短判断题。',
        question_type_counts={'true_false': 1}, duration_minutes=5)
    creds = json.loads((root / 'credentials.local.json').read_text('utf8'))['shop_ai']
    client = requests.Session()
    login = client.post(BASE + '/api/auth/login', data=creds, timeout=30); login.raise_for_status()
    client.headers['Authorization'] = 'Bearer ' + login.json()['access_token']
    with SessionLocal() as db:
        assert Path(db.bind.url.database).resolve() == root / 'acceptance.sqlite3'
        actor = db.query(DBUser).filter_by(username=creds['username']).one()
        db.expunge(actor)
        scope = dict(course_id=config['course_id'], owner_public_id=actor.public_id)
        before = course_generation_basis(db, **scope)
        source_before = course_generation_basis(db, **scope, include_profile=False)
        profile_before = latest_profile_snapshot_for_course(db, **scope).id
    save('input', {'configuration': config, 'profile_before': profile_before,
        'evidence_type': '真实模型、正常组卷服务及本人合法复习门槛；协调一次普通作答发生在出题与发布之间，不模拟模型输出'})

    # Coordinate the exact failing interleaving. The production generator and
    # publication guard still run unchanged; only normal learning writes occur.
    original = m5_api.build_intelligent_exam_input
    def build(db, **kwargs):
        payload = original(db, **kwargs)
        save('generated', payload.model_dump(mode='json'))
        answer = {'question_version_id': 'aqv-19161e560ba947b192eb5587d9d4ea1a',
            'idempotency_key': 'r208q-exam-concurrent-learning', 'mode':'practice',
            'answer': {'choice': 'B'}, 'confidence': .9, 'duration_seconds': 45}
        save('learning-request', answer)
        response = client.post(BASE + '/api/v1/m5/assessment/attempts', json=answer, timeout=120)
        save('learning-response', {'status': response.status_code, 'body': response.json()})
        response.raise_for_status()
        with SessionLocal() as current:
            after = course_generation_basis(current, **scope)
            source_after = course_generation_basis(current, **scope, include_profile=False)
            profile_after = latest_profile_snapshot_for_course(current, **scope).id
        assert after != before and source_before == source_after
        assert payload.generation_context['profile_snapshot_id'] == profile_before
        save('interleaving', {'profile_before':profile_before, 'profile_after':profile_after,
            'learning_basis_changed':True, 'course_sources_unchanged':True,
            'generated_profile_is_frozen':True})
        return payload
    m5_api.build_intelligent_exam_input = build
    began = time.monotonic()
    try:
        result = await m5_api._create_configured_intelligent_exam(
            config=IntelligentExamConfigInput(**config), current_user=actor)
        save('result', {'passed': True, 'seconds': round(time.monotonic()-began, 2),
            'exam': result, 'external_model':True, 'full_queue_retry_tested':False})
        print('Live exam published across a real learning update.', flush=True)
    except Exception as error:
        save('failure-' + str(int(time.time())), {'type':type(error).__name__, 'error':str(error)})
        raise
    finally:
        m5_api.build_intelligent_exam_input = original


if __name__ == '__main__':
    asyncio.run(main())
