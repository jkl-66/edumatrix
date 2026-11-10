"""Use saved learner answers and ordinary inquiry/review APIs on the isolated DB.

The initial wrong choice and two explanations are synthetic scenario inputs.
Follow-up answers require an explicit choice after independent content review.
No draft edits, approval overrides or recovery endpoints are used.
"""
import argparse
import json
from pathlib import Path
import time

import requests


ROOT = Path(__file__).resolve().parents[1] / 'scratch/automatic-generation-r207'
BASE = 'http://127.0.0.1:8944'
QUESTION = 'aqv-19161e560ba947b192eb5587d9d4ea1a'
SCENARIOS = {
    'review-practice': ('shop_ai', ''),
    'inquiry-training-vs-validation': ('humanities_educator',
        '我选A是因为训练MSE 0.06最低。我觉得训练时做得最好，遇到新的数据也会最好，没用验证那一列作选择。'),
    'inquiry-mse-direction': ('humanities_educator',
        '我选A时实际看的是验证那一列：A是0.22，比0.16和0.19都大。我把MSE当成准确率一样的分数，认为越大越好；没有按选项里训练误差最低那句话作判断。'),
}


def run(case, action, choice=None, revision=''):
    persona, explanation = SCENARIOS[case]
    run_name = case + ('-' + revision if revision else '')
    folder = ROOT / 'runs' / run_name
    folder.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT / 'inputs.json').read_text(encoding='utf8'))
    credentials = json.loads((ROOT / 'credentials.local.json').read_text(encoding='utf8'))[persona]
    client = requests.Session()
    auth = client.post(BASE + '/api/auth/login', data=credentials, timeout=30)
    auth.raise_for_status()
    client.headers['Authorization'] = 'Bearer ' + auth.json()['access_token']

    def save(name, value):
        (folder / (name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')

    def saved(name):
        path = folder / (name + '.json')
        return json.loads(path.read_text(encoding='utf8')) if path.exists() else None

    def call(method, path, name, body=None):
        if body is not None:
            save(name + '-request', body)
        result = client.request(method, BASE + path, json=body, timeout=60)
        save(name + '-response', {'status_code': result.status_code, 'body': result.json(), 'at': time.time()})
        result.raise_for_status()
        return result.json()

    if action == 'prepare':
        if not saved('input'):
            question = call('GET', '/api/v1/m5/assessment/questions/' + QUESTION, 'question')
            save('input', {'evidence_type': '冻结合成学习输入；题目沿现有已审核版本',
                'question': question, 'choice': 'A', 'explanation': explanation, 'persona': persona})
        if not saved('attempt'):
            result = call('POST', '/api/v1/m5/assessment/attempts', 'attempt', {
                'question_version_id': QUESTION, 'idempotency_key': 'r208e-' + run_name,
                'mode': 'practice', 'answer': {'choice': 'A'}, 'confidence': 0.8,
                'duration_seconds': 65})
            save('attempt', result)
            assert result['correct'] is False
        print(case, 'saved wrong answer', saved('attempt')['id'])
        return

    attempt = saved('attempt')
    if not attempt:
        raise ValueError('Prepare the ordinary learner answer first.')
    if case == 'review-practice':
        schedule = call('GET', '/api/v1/review-schedule?month=2026-11&course_id=' + manifest['course_id'], 'schedule-latest')
        candidates = [item for item in schedule['tasks']
                      if item.get('knowledge_point_id') == manifest['knowledge_point_id']
                      and item['id'].startswith(('review-plan:', 'retest:'))]
        if action == 'start':
            if not candidates:
                raise ValueError('The saved answer has not produced a usable review task yet.')
            if not saved('submission'):
                task = candidates[0]
                save('review-task', task)
                result = call('POST', '/api/v1/review-schedule/tasks/' + task['id'] + '/resource-jobs', 'submission',
                              {'idempotency_key': 'r208e-' + run_name + '-resources'})
                save('submission', result)
        job = saved('submission')
        if job:
            result = call('GET', '/api/v1/resource-bundles/generation-jobs/' + job['job_id'], 'latest')
            save('latest', result)
            print(case, job['job_id'], result['automation']['state'])
        else:
            print(case, 'available review tasks', len(candidates))
        return

    endpoint = '/api/v1/m5/assessment/attempts/' + attempt['id'] + '/inquiry'
    latest = call('GET', endpoint, 'inquiry-latest')
    if action == 'start' and not saved('inquiry-submission'):
        latest = call('POST', endpoint, 'inquiry-submission', {})
        save('inquiry-submission', latest)
    elif action == 'answer' and not saved('answer-submission'):
        assert latest.get('question'), 'Wait for the actual inquiry question.'
        latest = call('POST', endpoint + '/answer', 'answer-submission', {'response': saved('input')['explanation']})
        save('answer-submission', latest)
    elif action == 'practice':
        if not choice:
            raise ValueError('Supply the independently reviewed follow-up choice.')
        question_id = latest['feedback']['next_task']['question_version_id']
        call('POST', '/api/v1/m5/assessment/attempts', 'practice', {
            'question_version_id': question_id, 'idempotency_key': 'r208e-' + run_name + '-followup',
            'mode': 'practice', 'answer': {'choice': choice}, 'duration_seconds': 65})
        latest = call('GET', endpoint, 'inquiry-latest')
    save('latest', latest)
    print(case, json.dumps({'status': latest['status'], 'question': latest.get('question'),
        'generation': latest.get('generation'), 'feedback': latest.get('feedback')}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('case', choices=list(SCENARIOS))
    parser.add_argument('action', choices=['prepare', 'start', 'status', 'answer', 'practice'])
    parser.add_argument('--choice', choices=list('ABCD'))
    parser.add_argument('--revision', default='', help='Fresh verification after a product fix; keep prior runs.')
    args = parser.parse_args()
    run(args.case, args.action, args.choice, args.revision)
