"""Exercise the real review selection and submit one saved, owner-scoped request."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1] / 'scratch/automatic-generation-r207'
BASE = 'http://127.0.0.1:8955'


def main():
    folder = ROOT / 'runs/review-practice-r208m'
    folder.mkdir(exist_ok=True)
    shots = ROOT / 'browser/review-practice-r208m'
    shots.mkdir(parents=True, exist_ok=True)
    task = json.loads((ROOT / 'runs/review-practice/review-task.json').read_text(encoding='utf8'))
    credentials = json.loads((ROOT / 'credentials.local.json').read_text(encoding='utf8'))['shop_ai']
    result = {'kind': 'real_browser_review_selection', 'task_id': task['id'], 'errors': [], 'viewports': []}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1707, 'height': 900})
        page.set_default_timeout(45000)
        auth = page.request.post(BASE + '/api/auth/login', form=credentials)
        assert auth.ok
        state = {'edumatrix_token': auth.json()['access_token'], 'edumatrix_username': credentials['username'],
                 'edumatrix_student_id': credentials['username'], 'edumatrix_role': 'student',
                 'edumatrix_onboarded': 'true', 'edumatrix_course_id': task['course_id']}
        page.add_init_script('Object.entries(' + json.dumps(state) + ').forEach(([k,v])=>localStorage.setItem(k,v))')
        page.on('pageerror', lambda error: result['errors'].append(str(error)))
        page.goto(BASE + task['action']['route'] + '&course_id=' + task['course_id'] + '&month=2026-11', wait_until='networkidle')
        choice = page.get_by_label('复习资源内容', exact=True)
        expect(choice).to_have_value('recommended')
        choice.select_option('full')
        expect(choice).to_have_value('full')
        choice.select_option('recommended')
        for width in (1707, 1100):
            page.set_viewport_size({'width': width, 'height': 900})
            choice.scroll_into_view_if_needed()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
            page.screenshot(path=str(shots / f'selection-{width}.png'))
            result['viewports'].append(width)
        if not (folder / 'submission.json').exists():
            with page.expect_response(lambda r: '/resource-jobs' in r.url and r.request.method == 'POST') as response:
                page.get_by_role('button', name='生成复习资源', exact=True).click()
            reply = response.value
            (folder / 'request.json').write_text(json.dumps(reply.request.post_data_json, ensure_ascii=False, indent=2), encoding='utf8')
            assert reply.ok, reply.text()
            submitted = reply.json()
            (folder / 'submission.json').write_text(json.dumps(submitted, ensure_ascii=False, indent=2), encoding='utf8')
            assert [item['type'] for item in submitted['items']] == ['handout', 'quiz']
        else:
            submitted = json.loads((folder / 'submission.json').read_text(encoding='utf8'))
        result['job_id'] = submitted['job_id']
        result['selected_types'] = [item['type'] for item in submitted['items']]
        result['generation_status'] = 'submitted_not_yet_accepted'
        assert not result['errors']
        browser.close()
    (shots / 'review-selection.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
