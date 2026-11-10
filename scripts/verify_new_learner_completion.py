"""Finish the original registered learner's selected quiz and return to the path."""
import json
from pathlib import Path
import traceback
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1] / 'scratch/automatic-generation-r207'
RUN = ROOT / 'runs/new-registration-learning-r208'
OUT = ROOT / 'browser/new-learner-completion-r208r'
BASE = 'http://127.0.0.1:8955'
VERSION = 'av-e485ea55a4164ad1bbe0fb6afcd844f6'
ARTIFACT = 'art-c0c40addaca343afbdc058acb90f5602'
COURSE = 'course-ai-deep-learning-agents-v1'


def save(name, value):
    (OUT / f'{name}.json').write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    reviewed = {'version_id': VERSION, 'choices': [2, 1, 3],
        'calculations': ['10/60=1/6', '12/60=0.2，10/60=1/6；同样本量也会波动',
                         '90/600=0.15，比10/60离1/6更远；单次波动不否定大样本的可靠性趋势'],
        'evidence_kind': 'Codex先独立核读和计算，再输入合成作答；非真人学习效果。'}
    save('reviewed-answers', reviewed)
    result = {'version_id': VERSION, 'page_errors': [], 'http_errors': [], 'answers': []}
    if (OUT/'progress.json').exists():
        previous = json.loads((OUT/'progress.json').read_text('utf8'))
        assert previous['version_id'] == VERSION
        result['answers'] = previous['answers']
    credentials = json.loads((ROOT / 'new-learner.credentials.local.json').read_text('utf8'))
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1707, 'height': 900}, device_scale_factor=1)
        page.set_default_timeout(30000)
        auth = page.request.post(BASE + '/api/auth/login', form=credentials).json()
        headers = {'Authorization': 'Bearer ' + auth['access_token']}
        state = {'edumatrix_token': auth['access_token'], 'edumatrix_username': credentials['username'],
            'edumatrix_student_id': auth.get('student_id') or credentials['username'],
            'edumatrix_display_name': '新学习者', 'edumatrix_role': 'student',
            'edumatrix_onboarded': 'true', 'edumatrix_course_id': COURSE}
        page.add_init_script('Object.entries(' + json.dumps(state) + ').forEach(([k,v])=>localStorage.setItem(k,v))')
        page.on('pageerror', lambda e: result['page_errors'].append(str(e)))
        page.on('response', lambda r: result['http_errors'].append({'url': r.url, 'status': r.status}) if r.status >= 400 else None)
        try:
            page.goto(BASE + '/workspace/resources/quizzes/' + ARTIFACT, wait_until='networkidle')
            for index, choice in enumerate(reviewed['choices']):
                if index < len(result['answers']):
                    continue
                page.locator('.question-rail button').nth(index).click()
                page.locator('.option-list label').nth(choice).click()
                with page.expect_response(lambda r: '/assessment/attempts' in r.url and r.request.method == 'POST') as attempt:
                    page.get_by_role('button', name='提交答案', exact=True).click()
                result['answers'].append(attempt.value.json())
                save('progress', result)
                expect(page.locator('.feedback-title strong')).to_have_text('回答正确')
            expect(page.locator('.progress-summary strong')).to_have_text('3/3')
            page.screenshot(path=str(OUT/'feedback.png'), full_page=True)
            page.reload(wait_until='networkidle')
            expect(page.locator('.progress-summary strong')).to_have_text('3/3')
            result['answers_restored'] = True
            response = page.request.get(BASE + '/api/v1/m5/today?course_id=' + COURSE, headers=headers)
            assert response.ok
            result['today_after'] = response.json()
            path = json.loads((RUN/'path-confirmed-r208r.json').read_text('utf8'))['path']['id']
            response = page.request.get(BASE + '/api/v1/m5/paths/' + path, headers=headers)
            assert response.ok
            save('path-after-learning', response.json())
            page.goto(BASE + '/workspace/path?course_id=' + COURSE, wait_until='networkidle')
            expect(page.get_by_test_id('today-resource-generation')).to_be_visible(timeout=60000)
            result['continuation_text'] = page.locator('.app-content').inner_text()
            page.screenshot(path=str(OUT/'continue-path.png'), full_page=True)
            result['same_path_id'] = path
            result['passed'] = not result['page_errors'] and not result['http_errors']
            save('result', result)
        except Exception:
            result['failure'] = traceback.format_exc()
            save('failure', result)
            page.screenshot(path=str(OUT/'failure.png'), full_page=True)
            raise
        finally:
            browser.close()
    print('New learner: original path, selected quiz, three saved answers, feedback and continuation passed.')


if __name__ == '__main__':
    main()
