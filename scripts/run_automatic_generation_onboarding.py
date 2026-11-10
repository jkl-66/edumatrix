"""A synthetic new learner uses normal registration/onboarding/diagnostic APIs.

Each action is explicit; this script never changes database rows or repairs a
generated resource. Confirm only after reading the saved extracted candidates.
"""
import argparse
import json
from pathlib import Path
import secrets
import time

import requests

ROOT = Path(__file__).resolve().parents[1] / 'scratch/automatic-generation-r207'
OUT = ROOT / 'runs/new-registration-learning-r208'
BASE = 'http://127.0.0.1:8944'
ANSWERS = {
    'background': '我有两年软件开发经验，写过Python接口和CSV处理程序，在Windows笔记本上学习，没有独立GPU。',
    'goal': '我想完整学习《人工智能与深度学习：从机器学习基础到大模型智能体》，先会建立可复算的模型基线，解释验证选模与数据泄漏，再逐步学到神经网络和大模型应用。计划16周，每周二、四各60分钟、周日90分钟。',
    'foundation': '我会Python循环、函数、读写CSV和基础NumPy数组，能解简单代数式。概率、条件概率、矩阵运算和抽样误差还没系统学过，机器学习需要从基础确认。',
    'difficulty': '我过去习惯先在全量数据上标准化再切分，也会多次看测试集改参数。我还不能解释训练误差低为什么验证误差会高，需要用具体数据理解这些区别。',
    'preference': '请用中文讲解，保留代码和工具的英文名。先用一个有数据的小例子解释，再让我独立做新题，卡住时逐步提示。Windows笔记本CPU运行Python，不用GPU。每周二、四各60分钟、周日90分钟。',
}


def save(name, data):
    (OUT / (name + '.json')).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf8')


def main(action, dimension):
    OUT.mkdir(parents=True, exist_ok=True)
    frozen = OUT / 'learner-inputs.json'
    if not frozen.exists():
        save('learner-inputs', {'synthetic': True, 'answers': ANSWERS, 'self_rating': 'foundation', 'question_count': 15})
    inputs = json.loads(frozen.read_text(encoding='utf8'))
    credpath = ROOT / 'new-learner.credentials.local.json'
    if not credpath.exists():
        credpath.write_text(json.dumps({'username': 'auto_r208_new_learner', 'password': secrets.token_urlsafe(24)}), encoding='utf8')
    creds = json.loads(credpath.read_text(encoding='utf8'))
    session = requests.Session()
    if action == 'register' and not (OUT / 'registered.json').exists():
        response = session.post(BASE + '/api/auth/register', json={**creds, 'display_name': '自动生成新学习者'}, timeout=30)
        if response.status_code != 409:
            response.raise_for_status()
        save('registered', {'username': creds['username'], 'status': response.status_code, 'at': time.time()})
    login = session.post(BASE + '/api/auth/login', data=creds, timeout=30)
    login.raise_for_status()
    session.headers['Authorization'] = 'Bearer ' + login.json()['access_token']

    def call(method, path, name, data=None):
        if data is not None:
            save(name + '-request', data)
        response = session.request(method, BASE + path, json=data, timeout=900)
        save(name, {'status_code': response.status_code, 'body': response.json(), 'at': time.time()})
        response.raise_for_status()
        return response.json()

    state = call('GET', '/api/v1/onboarding/session', 'session')
    if action == 'turn':
        dimension = dimension or state['questionDimension']
        assert dimension in inputs['answers']
        state = call('POST', '/api/v1/onboarding/turns', 'turn-' + dimension, {
            'turn_id': 'r208-new-' + dimension, 'question_dimension': dimension,
            'user_answer': inputs['answers'][dimension]})
    elif action == 'confirm':
        assert dimension, 'Specify the reviewed dimension.'
        turn = next(t for t in state['turns'] if t['turnId'] == 'r208-new-' + dimension)
        assert turn['status'] in {'awaiting_confirmation', 'confirmed'}, turn['status']
        fields = {f['key']: f['value'] for f in turn['extractedCandidates']['fields']}
        state = call('POST', '/api/v1/onboarding/turns/' + turn['turnId'] + '/confirm',
                     'confirm-' + dimension, {'fields': fields})
    elif action == 'finalize':
        state = call('POST', '/api/v1/onboarding/finalize', 'finalize')
    elif action == 'diagnostic':
        trace = OUT / 'diagnostic-submission.json'
        if trace.exists():
            state = json.loads(trace.read_text(encoding='utf8'))['body']
        else:
            manifest = json.loads((ROOT / 'inputs.json').read_text(encoding='utf8'))
            state = call('POST', '/api/v1/diagnostics/blueprints', 'diagnostic-submission', {
                'course_id': manifest['course_id'], 'idempotency_key': 'r208-new-learner-diagnostic',
                'question_count': inputs['question_count'], 'self_rating': inputs['self_rating'], 'background': True})
    elif action == 'diagnostic-status':
        submitted = json.loads((OUT / 'diagnostic-submission.json').read_text(encoding='utf8'))['body']
        task = submitted.get('task', submitted)
        state = call('GET', '/api/v1/diagnostics/generation-tasks/' + task['id'], 'diagnostic-latest')
    print(json.dumps(state, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['register', 'status', 'turn', 'confirm', 'finalize', 'diagnostic', 'diagnostic-status'])
    parser.add_argument('--dimension', choices=list(ANSWERS))
    args = parser.parse_args()
    main(args.action, args.dimension)
