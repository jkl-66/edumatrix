"""Use the real course chat, then its ordinary answer-to-resource actions."""
import argparse
import json
from pathlib import Path
import time
import requests

ROOT = Path(__file__).resolve().parents[1] / 'scratch/automatic-generation-r207'
BASE = 'http://127.0.0.1:8944'


def main(action, revision='', base=BASE):
    run_name = 'chat-explanation' + ('-' + revision if revision else '')
    run = ROOT / 'runs' / run_name
    run.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT / 'inputs.json').read_text(encoding='utf8'))
    credentials = json.loads((ROOT / 'credentials.local.json').read_text(encoding='utf8'))['finance_practitioner']
    session = requests.Session()
    login = session.post(base + '/api/auth/login', data=credentials, timeout=30)
    login.raise_for_status()
    auth = login.json()
    session.headers['Authorization'] = 'Bearer ' + auth['access_token']

    def save(name, body):
        (run / (name + '.json')).write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding='utf8')

    def call(method, path, name, data=None):
        if data is not None:
            save(name + '-request', data)
        response = session.request(method, base + path, json=data, timeout=60)
        save(name, {'status_code': response.status_code, 'body': response.json(), 'at': time.time()})
        response.raise_for_status()
        return response.json()

    def saved(name):
        path = run / (name + '.json')
        return json.loads(path.read_text(encoding='utf8'))['body'] if path.exists() else None

    conversation = saved('conversation')
    if not conversation:
        conversation = call('POST', '/api/v1/chat/conversations', 'conversation',
                            {'course_id': manifest['course_id'], 'title': '模型选择与验证误差'})
    pair = saved('question')
    if not pair:
        pair = call('POST', '/api/v1/chat/conversations/' + conversation['id'] + '/messages', 'question', {
            'idempotency_key': 'r208-' + run_name, 'intent': 'course_qa',
            'content': manifest['common_instruction'],
            'context_refs': [{'courseId': manifest['course_id'], 'knowledgePointId': manifest['knowledge_point_id'],
                              'sourceRefId': source['id']} for source in manifest['sources']]})
    latest = call('GET', '/api/v1/chat/conversations/' + conversation['id'], 'latest')
    answer = next(m for m in latest['messages'] if m['id'] == pair['assistantMessage']['id'])
    if action == 'answer' and answer['status'] in {'queued', 'streaming'}:
        # Same saved message, one stream. This script does not invoke manual
        # continue/recovery or change an answer after generation.
        with session.post(base + '/api/stream/chat', json={
            'student_id': auth.get('student_id') or credentials['username'],
            'user_message_id': pair['userMessage']['id']}, stream=True, timeout=(30, 900)) as response:
            response.raise_for_status()
            response.encoding = 'utf8'
            with (run / 'answer-events.sse').open('a', encoding='utf8') as output:
                for line in response.iter_lines(decode_unicode=True):
                    output.write(line + '\n'); output.flush()
                    if line.startswith('event:'):
                        print(line, flush=True)
        latest = call('GET', '/api/v1/chat/conversations/' + conversation['id'], 'latest')
        answer = next(m for m in latest['messages'] if m['id'] == pair['assistantMessage']['id'])
    if action == 'resources':
        assert answer['status'] == 'completed', answer['status']
        # Same message-based request as the current resource picker. This
        # binds the selected answer even if other messages were added later.
        created = saved('resource-message') or call('POST',
            '/api/v1/chat/conversations/' + conversation['id'] + '/messages', 'resource-message', {
                'content': '基于这条回答生成所选学习资源，保留原问题的数据和推导，并安排新的独立练习。',
                'idempotency_key': 'r208f-' + run_name + '-resources',
                'intent': 'resource_generation', 'resource_types': ['handout', 'quiz'],
                'source_message_id': answer['id']})
        print('handout+quiz', created['assistantMessage']['resourceJobId'], flush=True)
    print(json.dumps({'conversation_id': conversation['id'], 'answer_id': answer['id'], 'status': answer['status']}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['answer', 'status', 'resources'])
    parser.add_argument('--revision', default='')
    parser.add_argument('--base', default=BASE)
    args = parser.parse_args()
    main(args.action, args.revision, args.base)
