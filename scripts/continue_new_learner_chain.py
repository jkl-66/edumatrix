"""Continue the confirmed original path with one explicitly selected quiz."""
import json
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1] / 'scratch/automatic-generation-r207'
OUT = ROOT / 'runs/new-registration-learning-r208'
BASE = 'http://127.0.0.1:8955'


def save(name, value):
    (OUT / f'{name}.json').write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


def main():
    credentials = json.loads((ROOT / 'new-learner.credentials.local.json').read_text('utf8'))
    session = requests.Session()
    response = session.post(BASE + '/api/auth/login', data=credentials, timeout=30)
    response.raise_for_status()
    session.headers['Authorization'] = 'Bearer ' + response.json()['access_token']
    trace = OUT / 'representative-submission-r208r.json'
    if trace.exists():
        job = json.loads(trace.read_text('utf8'))
    else:
        today = session.get(BASE + '/api/v1/m5/today', timeout=60)
        today.raise_for_status()
        task = next(t for t in today.json()['items'] if t['node_id'] == 'node-6ed557fcc20240fe92c5786c420023ec')
        context = task['generation_context']
        assert task['status'] == 'pending' and context['ready']
        request = {'course_id': task['course_id'], 'knowledge_point_id': context['knowledge_point_id'],
            'profile_snapshot_id': context['profile_snapshot_id'], 'path_id': task['path_id'],
            'task_id': task['node_id'], 'scope': 'single', 'selected_resource_types': ['quiz'],
            'idempotency_key': 'r208-new-learner-first-path-quiz',
            'learning_goal': '核对频数与相对频率，解释为什么增加样本量不保证每一次估计都更接近真实概率。',
            'user_instruction': '本次只准备三道简短测验题，先给一个可直接读懂的数据小例子；覆盖相对频率的分母、单次抽样的波动及大样本估计的边界。保留我的原学习路径，测验后再继续原计划中的NumPy实验。',
            'items': [{'type': 'quiz', 'title': '频率与概率估计 · 学习检查',
                       'source_ref_ids': context['source_ref_ids'], 'completion_rule': '完成三题并阅读反馈。'}]}
        save('representative-request-r208r', request)
        response = session.post(BASE + '/api/v1/resource-bundles/generation-jobs', json=request, timeout=90)
        if not response.ok:
            save('representative-submit-failure-r208r', {'status': response.status_code, 'body': response.json()})
        response.raise_for_status()
        job = response.json()
        save('representative-submission-r208r', job)
    response = session.get(BASE + '/api/v1/resource-bundles/generation-jobs/' + job['job_id'], timeout=60)
    response.raise_for_status()
    value = response.json()
    save('representative-current-r208r', value)
    print(json.dumps({k: value.get(k) for k in ['job_id', 'status', 'automation']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
