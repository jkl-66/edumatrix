"""Use the saved current inquiry and independently reviewed choice in the real UI."""
import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1] / 'scratch/automatic-generation-r207'
BASE = 'http://127.0.0.1:8944'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run')
    parser.add_argument('--resource')
    parser.add_argument('--version')
    parser.add_argument('--choice', choices=list('ABCD'), required=True)
    args = parser.parse_args()
    folder = ROOT / 'runs' / args.run
    frozen = json.loads((folder / 'input.json').read_text(encoding='utf8'))
    original = json.loads((folder / 'attempt.json').read_text(encoding='utf8'))
    credentials = json.loads((ROOT / 'credentials.local.json').read_text(encoding='utf8'))[frozen['persona']]
    shots = ROOT / 'browser' / args.run
    shots.mkdir(parents=True, exist_ok=True)
    result = {'evidence_type': '真实页面操作、合成学习回答；答案经Codex独立核读后指定',
              'attempt_id': original['id'], 'page_errors': [], 'viewports': []}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1707, 'height': 900})
        page.set_default_timeout(45000)
        auth = page.request.post(BASE + '/api/auth/login', form=credentials)
        assert auth.ok, auth.status
        state = {'edumatrix_token': auth.json()['access_token'], 'edumatrix_username': credentials['username'],
                 'edumatrix_student_id': credentials['username'], 'edumatrix_role': 'student',
                 'edumatrix_onboarded': 'true', 'edumatrix_course_id': 'course-ai-deep-learning-agents-v1'}
        page.add_init_script('Object.entries(' + json.dumps(state) + ').forEach(([k,v])=>localStorage.setItem(k,v))')
        page.on('pageerror', lambda e: result['page_errors'].append(str(e)))
        endpoint = BASE + '/api/v1/m5/assessment/attempts/' + original['id'] + '/inquiry'
        headers = {'Authorization': 'Bearer ' + state['edumatrix_token']}
        current = page.request.get(endpoint, headers=headers)
        assert current.ok
        before = current.json()
        assert before['status'] == 'completed'
        url = (BASE + '/workspace/resources/quizzes/' + args.resource + '?resource_version_id=' + args.version
               + '&question_version_id=' + original['question_version_id'] if args.resource else
               BASE + '/workspace/review/wrong-questions?course_id=' + state['edumatrix_course_id']
               + '&question_version_id=' + original['question_version_id'])
        page.goto(url, wait_until='networkidle')
        def open_saved_inquiry():
            if not args.resource:
                page.locator('[data-inquiry-attempt="' + original['id'] + '"]').click()
        open_saved_inquiry()
        panel = page.get_by_test_id('learning-inquiry')
        try:
            expect(panel).to_contain_text(frozen['explanation'])
            expect(panel).to_contain_text(before['feedback']['next_task']['prompt'])
            if not before['feedback']['next_task'].get('latest_attempt'):
                panel.locator('input[value="' + args.choice + '"]').check()
                panel.get_by_role('button', name='提交练习', exact=True).click()
            expect(panel.get_by_text('回答正确', exact=True)).to_be_visible()
            page.reload(wait_until='networkidle')
            open_saved_inquiry()
            expect(panel).to_contain_text(frozen['explanation'])
            expect(panel.get_by_text('回答正确', exact=True)).to_be_visible()
            for width in (1707, 1100):
                page.set_viewport_size({'width': width, 'height': 900})
                panel.locator('.next-practice').scroll_into_view_if_needed()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
                page.screenshot(path=str(shots / f'inquiry-restored-{width}.png'), full_page=True)
                result['viewports'].append(width)
            final = page.request.get(endpoint, headers=headers).json()
            attempt = final['feedback']['next_task']['latest_attempt']
            assert attempt['correct'] and attempt['answer']['choice'] == args.choice
            (folder / 'ui-result.json').write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding='utf8')
            result.update(passed=not result['page_errors'], next_attempt_id=attempt['id'],
                          answer_and_feedback_restored=True)
        except Exception as exc:
            result.update(passed=False, failure=str(exc), page_text=page.locator('body').inner_text()[:12000])
            page.screenshot(path=str(shots / 'failure.png'), full_page=True)
            raise
        finally:
            (shots / 'inquiry-ui.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
            browser.close()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
