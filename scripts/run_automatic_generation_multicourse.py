"""Normal second-course confirmation and background diagnostics on the test account."""
import argparse
import json
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1] / 'scratch/automatic-generation-r207'
COURSES = ['course-ai-deep-learning-agents-v1', 'course-machine-learning-foundations-v1']
TURN = 'r208e-second-course-confirmation'
PROFILE_INPUT = (
    '我同时学习《人工智能与深度学习：从机器学习基础到大模型智能体》和《机器学习基础与实践》。'
    '我是软件开发背景，会Python循环、函数、CSV和基础NumPy，用Windows笔记本CPU，没有GPU。'
    '新课希望从数据预处理、回归和分类基线学起，能独立运行实验、比较验证结果和解释数据泄漏。'
    '矩阵、条件概率和抽样误差需要先确认；我曾先在全量数据上做标准化，也会根据测试结果改参数。'
    '希望先有一个小数据例子，然后做独立练习，卡住时逐步提示。'
    '两门课程合计每周二和周四各60分钟、周日90分钟，总共210分钟；不是每门各有210分钟。'
    '先做好基础与无泄漏的模型评估，再继续神经网络和大模型，不要求在16周内学完两门课程。'
)


def main(action, base):
    folder = ROOT / 'runs/multicourse'
    folder.mkdir(parents=True, exist_ok=True)
    credentials = json.loads((ROOT / 'credentials.local.json').read_text(encoding='utf8'))['software_developer']
    client = requests.Session()
    response = client.post(base + '/api/auth/login', data=credentials, timeout=30)
    response.raise_for_status()
    client.headers['Authorization'] = 'Bearer ' + response.json()['access_token']

    def save(name, body):
        (folder / (name + '.json')).write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding='utf8')

    def read(name):
        path = folder / (name + '.json')
        return json.loads(path.read_text(encoding='utf8')) if path.exists() else None

    def call(method, path, name, body=None):
        if body is not None:
            save(name + '-request', body)
        result = client.request(method, base + path, json=body, timeout=900)
        save(name + '-response', {'status_code': result.status_code, 'body': result.json()})
        result.raise_for_status()
        value = result.json()
        save(name, value)
        return value

    if not read('input'):
        save('input', {'synthetic': True, 'course_ids': COURSES, 'profile_input': PROFILE_INPUT,
                      'question_count': 15, 'self_rating': 'foundation', 'weekly_shared_minutes': 210})
    if action == 'profile-start':
        value = call('POST', '/api/v1/onboarding/update/session', 'profile-session', {'course_id': COURSES[1]})
    elif action == 'profile-turn':
        value = read('profile-turn') or call('POST', '/api/v1/onboarding/update/turns', 'profile-turn', {
            'course_id': COURSES[1], 'turn_id': TURN, 'user_answer': read('input')['profile_input']})
    elif action == 'profile-confirm':
        state = read('profile-turn')
        turn = next(t for t in state['turns'] if t['turnId'] == TURN)
        candidates = turn['extractedCandidates']
        value = read('profile-confirmed') or call('POST', '/api/v1/onboarding/update/turns/' + TURN + '/confirm',
            'profile-confirmed', {'fields': {f['key']: f['value'] for f in candidates.get('fields', [])},
                'dimensions': candidates.get('dimensions', []),
                'weak_point_attribution': candidates.get('weakPointAttribution', []), 'continue_conversation': False})
    elif action == 'profile-complete':
        value = read('profile-completed') or call('POST', '/api/v1/onboarding/update/complete', 'profile-completed', {})
    elif action == 'prepare':
        value = read('blueprints-submission') or call('POST', '/api/v1/diagnostics/multi-course/blueprints',
            'blueprints-submission', {'courseIds': COURSES, 'idempotencyKey': 'r208e-multicourse-blueprints',
                                     'questionCount': 15, 'selfRating': 'foundation', 'background': True})
    elif action == 'paths':
        reports = read('reports')
        if not reports or len(reports['report_ids']) != len(COURSES):
            raise ValueError('Complete and review both actual diagnostic reports first.')
        value = read('paths-submission') or call('POST', '/api/v1/diagnostics/multi-course/paths', 'paths-submission', {
            'reportIds': reports['report_ids'], 'idempotencyKey': 'r208e-multicourse-paths', 'background': True})
    else:
        kind = 'paths' if action == 'paths-status' else 'blueprints'
        value = call('GET', '/api/v1/diagnostics/multi-course/generation-tasks?kind=' + kind
                     + '&idempotency_key=r208e-multicourse-' + kind, kind + '-latest')
    task = value.get('task')
    print(json.dumps({'action': action, 'task_id': task.get('id') if task else None,
                      'task_state': (task.get('automation') or {}).get('state') if task else None,
                      'status': value.get('status'), 'saved_keys': list(value)}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['profile-start', 'profile-turn', 'profile-confirm', 'profile-complete',
                                         'prepare', 'status', 'paths', 'paths-status'])
    parser.add_argument('--base', default='http://127.0.0.1:8955')
    args = parser.parse_args()
    main(args.action, args.base)
