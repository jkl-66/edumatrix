"""Observe the existing new-learner task through its real browser entry."""
import json
from pathlib import Path
import traceback

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1] / 'scratch/automatic-generation-r207'
BASE = 'http://127.0.0.1:8944'


def main():
    run = ROOT / 'runs/new-registration-learning-r208'
    credentials = json.loads((ROOT / 'new-learner.credentials.local.json').read_text(encoding='utf8'))
    manifest = json.loads((ROOT / 'inputs.json').read_text(encoding='utf8'))
    submitted = json.loads((run / 'diagnostic-submission.json').read_text(encoding='utf8'))['body']
    task_id = submitted.get('task', submitted)['id']
    result = {'task_id': task_id, 'requests': [], 'restored': [], 'page_errors': [], 'http_errors': [],
              'evidence_type': '真实生成任务、合成新用户，浏览器首次打开及刷新；只查询原任务'}
    shots = ROOT / 'browser'
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1707, 'height': 900})
        login = page.request.post(BASE + '/api/auth/login', form=credentials)
        assert login.ok, login.status
        auth = login.json()
        state = {'edumatrix_token': auth['access_token'], 'edumatrix_username': credentials['username'],
                 'edumatrix_display_name': '自动生成新学习者', 'edumatrix_role': 'student',
                 'edumatrix_student_id': auth.get('student_id') or credentials['username'],
                 'edumatrix_onboarded': 'true', 'edumatrix_course_id': manifest['course_id']}
        page.add_init_script('Object.entries(' + json.dumps(state) + ').forEach(([k,v])=>localStorage.setItem(k,v))')
        page.on('pageerror', lambda error: result['page_errors'].append(str(error)))
        page.on('request', lambda r: result['requests'].append({'method': r.method, 'url': r.url})
                if '/api/v1/diagnostics/' in r.url else None)
        page.on('response', lambda r: result['http_errors'].append({'status': r.status, 'url': r.url})
                if r.status >= 400 else None)
        try:
            for index in range(2):
                with page.expect_response(lambda r: '/api/v1/diagnostics/generation-tasks?' in r.url,
                                          timeout=30000) as response:
                    if index:
                        page.reload(wait_until='networkidle')
                    else:
                        page.goto(BASE + '/workspace/assessment/entry?course_id=' + manifest['course_id'],
                                  wait_until='networkidle')
                task = response.value.json()['task']
                assert task and task['id'] == task_id, task
                result['restored'].append({'id': task['id'], 'status': task['status'],
                                           'automation': task['automation']})
                if task['status'] == 'completed':
                    expect(page.get_by_test_id('diagnostic-ready')).to_be_visible()
                    expect(page.get_by_test_id('enter-diagnostic')).to_be_enabled()
                else:
                    expect(page.get_by_test_id('generate-diagnostic')).to_be_disabled()
                page.screenshot(path=str(shots / f'new-learner-diagnostic-r208d-{index}.png'))
            assert not [r for r in result['requests'] if r['method'] != 'GET']
            result['horizontal_overflow'] = page.evaluate('document.documentElement.scrollWidth > innerWidth + 2')
            result['passed'] = not result['page_errors'] and not result['http_errors'] and not result['horizontal_overflow']
        except Exception:
            result.update(passed=False, failure=traceback.format_exc(), page_text=page.locator('body').inner_text())
            page.screenshot(path=str(shots / 'new-learner-diagnostic-r208d-failed.png'))
        finally:
            (shots / 'new-learner-diagnostic-restored-r208d.json').write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
            browser.close()
    print(json.dumps({key: value for key, value in result.items() if key not in {'requests', 'page_text'}},
                     ensure_ascii=False, indent=2))
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
