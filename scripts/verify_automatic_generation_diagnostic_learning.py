"""Use frozen synthetic answers on the actual new-learner diagnostic UI."""
import json
from pathlib import Path
import traceback
import argparse

from playwright.sync_api import expect, sync_playwright, TimeoutError as PlaywrightTimeout

ROOT = Path(__file__).resolve().parents[1] / 'scratch/automatic-generation-r207'
RUN = ROOT / 'runs/new-registration-learning-r208'
BASE = 'http://127.0.0.1:8944'


def main(prepare_path=False, run=None, blueprint_file=None, responses_file=None, persona=None,
         report_wait_seconds=45):
    folder = ROOT / 'runs' / run if run else RUN
    folder.mkdir(parents=True, exist_ok=True)
    shots = ROOT / 'browser' / run if run else ROOT / 'browser'
    shots.mkdir(parents=True, exist_ok=True)

    def save(name, value):
        (folder / (name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')

    frozen = json.loads((Path(responses_file) if responses_file else folder / 'diagnostic-synthetic-responses.json').read_text(encoding='utf8'))
    if blueprint_file:
        blueprint = json.loads(Path(blueprint_file).read_text(encoding='utf8'))
    else:
        blueprint = json.loads((folder / 'diagnostic-latest.json').read_text(encoding='utf8'))['body']['task']['blueprint']
    assert frozen['blueprint_id'] == blueprint['id'], 'Synthetic responses belong to another diagnostic.'
    assert len(frozen['responses']) == len(blueprint['questions']) == blueprint['questionCount']
    for number, (answer, question) in enumerate(zip(frozen['responses'], blueprint['questions']), 1):
        assert answer['number'] == number and answer['question_version_id'] == question['id']
    if persona:
        credentials = json.loads((ROOT / 'credentials.local.json').read_text(encoding='utf8'))[persona]
    else:
        credentials = json.loads((ROOT / 'new-learner.credentials.local.json').read_text(encoding='utf8'))
    result = {'evidence_type': '合成学习者冻结回答，经真实页面保存、提交、生成报告；不改题目/答案键/评分',
              'blueprint_id': blueprint['id'], 'course_id': blueprint['course']['id'],
              'checks': {}, 'page_errors': [], 'http_errors': []}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1707, 'height': 900})
        page.set_default_timeout(30000)
        auth = page.request.post(BASE + '/api/auth/login', form=credentials).json()
        headers = {'Authorization': 'Bearer ' + auth['access_token']}
        state = {'edumatrix_token': auth['access_token'], 'edumatrix_username': credentials['username'],
                 'edumatrix_display_name': '自动生成新学习者', 'edumatrix_role': 'student',
                 'edumatrix_student_id': auth.get('student_id') or credentials['username'],
                 'edumatrix_onboarded': 'true', 'edumatrix_course_id': blueprint['course']['id']}
        page.add_init_script('Object.entries(' + json.dumps(state) + ').forEach(([k,v])=>localStorage.setItem(k,v))')
        page.on('pageerror', lambda e: result['page_errors'].append(str(e)))
        page.on('response', lambda r: result['http_errors'].append({'status': r.status, 'url': r.url}) if r.status >= 400 else None)
        try:
            with page.expect_response(lambda r: r.url.endswith('/blueprints/' + blueprint['id'] + '/sessions')) as started:
                page.goto(BASE + '/workspace/assessment?course_id=' + blueprint['course']['id'] + '&blueprint_id=' + blueprint['id'],
                          wait_until='networkidle')
            work = started.value.json()['session']
            result['session_id'] = work['id']
            save('diagnostic-browser-session', work)
            if work['status'] != 'submitted':
                for item in frozen['responses']:
                    number = item['number']
                    saved = next((r for r in work['responses'] if r['questionVersionId'] == item['question_version_id']), None)
                    if saved and saved['complete']:
                        assert saved['answer'] == item['answer']
                        continue
                    page.locator('.question-buttons button').nth(number - 1).click()
                    expect(page.locator('.question-heading h1')).to_have_text(blueprint['questions'][number - 1]['prompt'])
                    answer = item['answer']
                    if answer.get('response_status') == 'not_yet':
                        page.get_by_test_id('diagnostic-not-yet').click()
                    else:
                        if 'value' in answer:
                            page.get_by_role('button', name='正确' if answer['value'] else '错误', exact=True).click()
                        elif 'choice' in answer:
                            page.locator('.option-list label').nth(ord(answer['choice']) - ord('A')).click()
                        elif 'choices' in answer:
                            for index, checkbox in enumerate(page.locator('.option-list input[type=checkbox]').all()):
                                checkbox.set_checked(chr(ord('A') + index) in answer['choices'])
                        elif 'blanks' in answer:
                            expect(page.locator('.blank-list input')).to_have_count(len(answer['blanks']))
                            for index, value in enumerate(answer['blanks']):
                                page.locator('.blank-list input').nth(index).fill(str(value))
                        elif 'code' in answer:
                            page.locator('.code-answer textarea').fill(answer['code'])
                        else:
                            page.locator('textarea.text-answer').fill(answer['text'])
                        page.get_by_text('有些理解' if item['understanding'] == '部分理解' else item['understanding'], exact=True).click()
                    if number < len(frozen['responses']):
                        with page.expect_response(lambda r: '/responses/' + item['question_version_id'] in r.url and r.request.method == 'PUT'):
                            page.get_by_role('button', name='保存并进入下一题', exact=True).click()
                        expect(page.locator('.question-heading h1')).to_have_text(blueprint['questions'][number]['prompt'])
                    else:
                        expect(page.locator('.question-actions')).to_contain_text('当前题已保存', timeout=30000)
                    work_response = page.request.get(BASE + '/api/v1/diagnostics/sessions/' + work['id'], headers=headers)
                    assert work_response.ok
                    work = work_response.json()
                    save('diagnostic-browser-session', work)
                    print('Saved diagnostic answer', number, flush=True)
                    if number == 7:
                        page.reload(wait_until='networkidle')
                        expect(page.get_by_test_id('diagnostic-restored')).to_be_visible()
                        expect(page.locator('.question-heading h1')).to_have_text(blueprint['questions'][number]['prompt'])
                        result['checks']['midway_refresh'] = True
                        page.screenshot(path=str(shots / 'new-learner-diagnostic-midway-r208.png'))
                assert work['completedCount'] == len(frozen['responses']) and work['canSubmit']
                with page.expect_response(lambda r: r.url.endswith('/sessions/' + work['id'] + '/report')
                                          and r.request.method == 'POST', timeout=60000) as reported:
                    page.get_by_role('button', name='提交本次诊断', exact=True).click()
                assert reported.value.ok, reported.value.text()
                save('diagnostic-report-submission', reported.value.json())
            try:
                page.locator('.report-hero').wait_for(state='visible', timeout=report_wait_seconds * 1000)
            except PlaywrightTimeout:
                task_response = page.request.get(BASE + '/api/v1/diagnostics/sessions/' + work['id'] + '/report-task', headers=headers)
                assert task_response.ok, task_response.text()
                task = task_response.json()['task']
                assert task and task['automation']['state'] in {'queued', 'running', 'retry_wait'}, task
                page.reload(wait_until='networkidle')
                restored_response = page.request.get(BASE + '/api/v1/diagnostics/sessions/' + work['id'] + '/report-task', headers=headers)
                assert restored_response.ok
                restored = restored_response.json()['task']
                assert restored['id'] == task['id']
                expect(page.locator('[data-testid="diagnostic-report-loading"], .report-hero')).to_be_visible()
                save('diagnostic-report-task', restored)
                result.update(passed=None, outcome='report_pending', report_task_id=task['id'])
                result['checks'].update(answers_saved=len(frozen['responses']), report_task_restored=True)
                assert not result['page_errors'] and not result['http_errors']
                page.screenshot(path=str(shots / 'diagnostic-report-preparing.png'))
                print(json.dumps({'outcome': 'report_pending', 'task_id': task['id']}, ensure_ascii=False))
                return
            report_response = page.request.get(BASE + '/api/v1/diagnostics/sessions/' + work['id'] + '/report', headers=headers)
            assert report_response.ok, report_response.text()
            save('diagnostic-report', report_response.json())
            result['checks']['report_text'] = page.locator('.report-hero').inner_text()
            page.screenshot(path=str(shots / 'new-learner-report-r208.png'))
            page.reload(wait_until='networkidle')
            expect(page.locator('.report-hero')).to_be_visible(timeout=60000)
            result['checks']['report_restored'] = True
            if prepare_path:
                submitted_path = folder / 'path-submission.json'
                if submitted_path.exists():
                    path_task = json.loads(submitted_path.read_text(encoding='utf8'))['task']
                else:
                    with page.expect_response(lambda r: r.url.endswith('/sessions/' + work['id'] + '/report/path'),
                                              timeout=60000) as prepared:
                        page.get_by_role('button', name='生成初始学习路径', exact=True).click()
                    assert prepared.value.ok, prepared.value.text()
                    save('path-submission', prepared.value.json())
                    path_task = prepared.value.json()['task']
                with page.expect_response(lambda r: '/api/v1/m5/path-generation-tasks?' in r.url,
                                          timeout=30000) as restored_path:
                    page.reload(wait_until='networkidle')
                actual_task = restored_path.value.json()['task']
                assert actual_task and actual_task['id'] == path_task['id']
                result['checks']['path_task_restored'] = actual_task['id']
                page.screenshot(path=str(shots / 'new-learner-path-preparing-r208.png'))
            result['checks']['horizontal_overflow'] = page.evaluate('document.documentElement.scrollWidth > innerWidth + 2')
            result['passed'] = not result['page_errors'] and not result['http_errors'] and not result['checks']['horizontal_overflow']
        except Exception:
            result.update(passed=False, failure=traceback.format_exc(), page_text=page.locator('body').inner_text())
            page.screenshot(path=str(shots / 'new-learner-diagnostic-learning-failed-r208.png'))
        finally:
            save('diagnostic-path-learning-ui' if prepare_path else 'diagnostic-learning-ui', result)
            browser.close()
    print(json.dumps({k: v for k, v in result.items() if k != 'page_text'}, ensure_ascii=False, indent=2))
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare-path', action='store_true')
    parser.add_argument('--run', help='Evidence folder under runs; defaults to the existing new-learner run.')
    parser.add_argument('--blueprint', dest='blueprint_file', help='Reviewed actual blueprint JSON, one course at a time.')
    parser.add_argument('--responses', dest='responses_file', help='Frozen synthetic responses bound to exact question versions.')
    parser.add_argument('--persona', help='Existing isolated persona; omitted for the new-learner account.')
    parser.add_argument('--report-wait-seconds', type=int, default=45)
    main(**vars(parser.parse_args()))
