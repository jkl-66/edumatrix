"""Read a real answer, select resources, and inject a lost submission/refresh.

The fault check aborts every resource POST before it reaches the server. It
verifies request preservation, not a successful model-generated resource.
"""
import argparse
import json
from pathlib import Path
import traceback

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1] / 'scratch/automatic-generation-r207'
BASE = 'http://127.0.0.1:8955'


def main(mode='offline', base=BASE):
    run = ROOT / 'runs/chat-explanation-r208e'
    conversation = json.loads((run / 'latest.json').read_text(encoding='utf8'))['body']
    pair = json.loads((run / 'question.json').read_text(encoding='utf8'))['body']
    answer_id = pair['assistantMessage']['id']
    credentials = json.loads((ROOT / 'credentials.local.json').read_text(encoding='utf8'))['finance_practitioner']
    out = ROOT / ('browser/chat-binding-r208f' if mode == 'offline' else 'browser/chat-resource-submit-r208f')
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'result.json').exists() and not (out / 'result-first.json').exists():
        (out / 'result-first.json').write_bytes((out / 'result.json').read_bytes())
    result = {'checks': {}, 'page_errors': [], 'aborted_requests': [],
              'evidence_type': ('Real saved answer and real UI; resource POSTs intentionally aborted before server acceptance'
                                if mode == 'offline' else 'Real UI answer-to-resource submission; generation observed separately')}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1707, 'height': 900})
        page.set_default_timeout(30000)
        page.on('pageerror', lambda error: result['page_errors'].append(str(error)))
        login = page.request.post(base + '/api/auth/login', form=credentials)
        assert login.ok
        auth = login.json()
        state = {'edumatrix_token': auth['access_token'], 'edumatrix_username': credentials['username'],
                 'edumatrix_student_id': auth.get('student_id') or credentials['username'],
                 'edumatrix_role': 'student', 'edumatrix_onboarded': 'true',
                 'edumatrix_course_id': conversation['courseId']}
        page.add_init_script('Object.entries(' + json.dumps(state) + ').forEach(([k,v])=>localStorage.setItem(k,v))')

        def disconnect(route):
            request = route.request
            if request.method == 'POST' and request.url.endswith('/messages'):
                result['aborted_requests'].append(request.post_data_json)
                route.abort('connectionfailed')
            else:
                route.continue_()

        if mode == 'offline':
            page.route('**/api/v1/chat/conversations/**', disconnect)
        try:
            page.goto(base + '/chat?conversation_id=' + conversation['id'], wait_until='networkidle')
            answer = page.locator('[data-message-id="' + answer_id + '"]')
            expect(answer.locator('.assistant-answer')).to_contain_text('0.039753')
            page.reload(wait_until='networkidle')
            expect(answer.locator('.assistant-answer')).to_contain_text('0.004253')
            result['checks']['real_answer_and_refresh'] = True
            if mode == 'submit':
                # A rerun observes the same server-side task. It never creates
                # another task just because the browser process was closed.
                headers = {'Authorization': 'Bearer ' + auth['access_token']}
                latest = page.request.get(base + '/api/v1/chat/conversations/' + conversation['id'], headers=headers).json()
                existing = [m for m in latest['messages'] if m.get('resourceJobId') and
                    (m.get('streamCheckpoint', {}).get('conversationSource') or {}).get('answer_id') == answer_id]
                if existing:
                    resource_message = existing[-1]
                    result['checks']['existing_job_reused'] = True
                else:
                    answer.get_by_role('button', name='在输入框生成资源', exact=True).click()
                    for label in ('个性化讲义', '测验题'):
                        page.locator('.resource-picker-option').filter(has_text=label).get_by_role('checkbox').check()
                    page.locator('.composer-resource-picker > button').click()
                    with page.expect_response(lambda response: response.request.method == 'POST' and response.url.endswith('/messages')) as response_info:
                        page.get_by_role('button', name='发送', exact=True).click()
                    response = response_info.value
                    pair_body = response.json()
                    (run / 'resource-message.json').write_text(json.dumps({'status_code': response.status,
                        'body': pair_body, 'entry': 'actual Chat resource picker'}, ensure_ascii=False, indent=2), encoding='utf8')
                    assert response.ok, pair_body
                    resource_message = pair_body['assistantMessage']
                job_id = resource_message['resourceJobId']
                assert resource_message['streamCheckpoint']['conversationSource']['answer_id'] == answer_id
                result.update(job_id=job_id, assistant_message_id=resource_message['id'])
                page.reload(wait_until='networkidle')
                latest = page.request.get(base + '/api/v1/chat/conversations/' + conversation['id'], headers=headers).json()
                restored = next(m for m in latest['messages'] if m['id'] == resource_message['id'])
                assert restored['resourceJobId'] == job_id
                result['checks']['same_job_after_refresh'] = True
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.locator('[data-message-id="' + restored['id'] + '"]').scroll_into_view_if_needed()
                page.screenshot(path=str(out / 'submitted-restored.png'))
                assert not result['page_errors']
                return
            answer.get_by_role('button', name='在输入框生成资源', exact=True).click()
            expect(page.get_by_role('button', name='取消引用所选回答')).to_be_visible()
            page.locator('.resource-picker-option').filter(has_text='个性化讲义').get_by_role('checkbox').check()
            page.locator('.resource-picker-option').filter(has_text='测验题').get_by_role('checkbox').check()
            request_text = page.get_by_role('textbox', name='输入问题').input_value()
            assert '请描述' not in request_text
            page.locator('.composer-resource-picker > button').click()
            page.screenshot(path=str(out / 'selected-answer.png'))
            page.get_by_role('button', name='发送', exact=True).click()
            expect(page.locator('.composer-recovery')).to_contain_text('自动继续准备资源')
            assert result['aborted_requests'][0]['source_message_id'] == answer_id
            assert result['aborted_requests'][0]['resource_types'] == ['handout', 'quiz']
            before = len(result['aborted_requests'])
            page.reload(wait_until='networkidle')
            page.wait_for_function("document.querySelector('.composer-recovery')?.textContent.includes('自动继续准备资源')")
            page.wait_for_timeout(2500)
            assert len(result['aborted_requests']) > before
            assert all(item == result['aborted_requests'][0] for item in result['aborted_requests'])
            result['checks']['same_request_after_offline_refresh'] = True
            result['checks']['no_manual_retry_button'] = page.get_by_role('button', name='重试发送', exact=True).count() == 0
            result['checks']['no_horizontal_overflow'] = page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(out / 'offline-restored.png'))
            page.set_viewport_size({'width': 1100, 'height': 800})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            result['checks']['narrow_no_horizontal_overflow'] = True
            page.screenshot(path=str(out / 'offline-restored-narrow.png'))
            assert not result['page_errors']
        except Exception:
            result['failure'] = traceback.format_exc()
            page.screenshot(path=str(out / 'failure.png'))
            raise
        finally:
            (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
            browser.close()
    print(json.dumps({'checks': result['checks'], 'aborted_posts': len(result['aborted_requests'])}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['offline', 'submit'], default='offline')
    parser.add_argument('--base', default=BASE)
    args = parser.parse_args()
    main(args.mode, args.base)
