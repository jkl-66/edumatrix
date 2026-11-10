"""Two persisted real chat runs with identical question, learner and sources."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time
import requests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--storage-state', required=True)
    parser.add_argument('--url', default='http://127.0.0.1:8944')
    parser.add_argument('--resume-failed', action='store_true')
    args = parser.parse_args()
    output = Path(args.output)
    inputs = json.loads((output/'inputs.json').read_text(encoding='utf-8'))
    state = json.loads(Path(args.storage_state).read_text(encoding='utf-8'))
    token = next(item['value'] for origin in state['origins'] for item in origin['localStorage']
                 if item['name'] == 'edumatrix_token')
    headers = {'Authorization': 'Bearer '+token}

    def save(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

    def post(path, payload):
        result = requests.post(args.url+path, json=payload, headers=headers, timeout=900)
        result.raise_for_status()
        return result.json()

    for mode in ('hybrid', 'hipporag2'):
        path = output/f'chat-{mode}.json'
        if path.exists():
            continue
        convo_path = output/f'conversation-{mode}.json'
        if convo_path.exists():
            conversation = json.loads(convo_path.read_text(encoding='utf-8'))
        else:
            conversation = post('/api/v1/chat/conversations', {
                'course_id': inputs['course_id'], 'title': '模型选择与泛化 · '+('普通检索' if mode=='hybrid' else '关联检索')})
            save(convo_path, conversation)
        payload = {'content': inputs['question'], 'retrieval_mode': mode,
                   'idempotency_key': 'hipporag-r190-'+mode,
                   'context_refs': [{'courseId': inputs['course_id'], 'sourceRefId': ref} for ref in inputs['source_ref_ids']]}
        started = time.monotonic()
        created = post('/api/v1/chat/conversations/'+conversation['id']+'/messages', payload)
        save(path, {'request': payload, 'created': created, 'retrieval_seconds': time.monotonic()-started})
        print('Prepared '+mode, flush=True)

    def answer(mode):
        result_path = output/f'answer-{mode}.json'
        if result_path.exists():
            saved = json.loads(result_path.read_text(encoding='utf-8'))
            if saved.get('complete'):
                print('Reuse completed '+mode, flush=True)
                return saved
            if not args.resume_failed:
                raise RuntimeError('Inspect and resume the original failed chat: '+mode)
            response = requests.get(args.url+'/api/v1/chat/conversations/'+saved['conversation_id'],
                                    headers=headers, timeout=30)
            response.raise_for_status()
            message = next(item for item in response.json()['messages']
                           if item['id'] == saved['assistant_message_id'])
            if message['status'] not in {'failed', 'stopped'}:
                raise RuntimeError('Original message is not failed/stopped; inspect its current run.')
            archive = output/'attempts'/f'{mode}-{time.time_ns()}'
            archive.mkdir(parents=True)
            result_path.replace(archive/result_path.name)
            sse = output/f'answer-{mode}.sse'
            if sse.exists():
                sse.replace(archive/sse.name)
            save(archive/'message.json', message)
            post('/api/v1/chat/messages/'+message['id']+'/continue',
                 {'expected_lock_version': message['lockVersion']})
            print('Resuming original draft '+mode, flush=True)
        created = json.loads((output/f'chat-{mode}.json').read_text(encoding='utf-8'))['created']
        started = time.monotonic()
        events, current = [], ''
        with requests.post(args.url+'/api/stream/chat', headers=headers,
            json={'user_message_id': created['userMessage']['id']}, stream=True, timeout=1800) as response:
            response.raise_for_status()
            response.encoding = 'utf-8'
            with (output/f'answer-{mode}.sse').open('w', encoding='utf-8') as log:
                for line in response.iter_lines(decode_unicode=True):
                    log.write(line+'\n'); log.flush()
                    if line.startswith('event: '):
                        current = line[7:]
                    elif line.startswith('data: '):
                        data = json.loads(line[6:])
                        events.append({'event': current, 'data': data})
                        if current in {'stage.completed', 'error', 'complete'}:
                            print(mode, current, flush=True)
        complete = next((item['data'] for item in reversed(events) if item['event']=='complete'), None)
        result = {'elapsed_seconds': time.monotonic()-started, 'complete': complete,
                  'errors': [item['data'] for item in events if item['event']=='error'],
                  'conversation_id': created['conversation']['id'],
                  'user_message_id': created['userMessage']['id'],
                  'assistant_message_id': created['assistantMessage']['id']}
        save(result_path, result)
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(answer, ['hybrid', 'hipporag2']))
    if not all(result['complete'] for result in results):
        raise SystemExit('One of the original chats needs recovery; saved outputs retained.')


if __name__ == '__main__':
    main()
