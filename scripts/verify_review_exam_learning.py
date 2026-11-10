"""Use the existing three-question review exam and its saved review plan."""
import json
from pathlib import Path
import traceback
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1] / 'scratch/automatic-generation-r207'
RUN = ROOT / 'runs/review-exam-r208o'
OUT = ROOT / 'browser/review-exam-r208q'
BASE = 'http://127.0.0.1:8955'


def save(name, value):
    (OUT / (name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    exam = json.loads((RUN / 'generation-current.json').read_text('utf8'))['generation']['result']
    answers = ['A', False,
        '先在训练集上拟合模型参数及预处理参数，再用相同的验证集和相同指标比较候选模型。若以误差为指标，应选择验证误差较低的候选，并用验证结果调整超参数。'
        '训练集用于学习参数，训练误差反映对已见样本的拟合；验证集用于选模型和超参数；测试集留到方案固定后做最终独立评估，用来估计对新样本的泛化表现。'
        '不能反复看测试结果再调参，否则测试集参与了选择，最终报告会产生选择偏差。训练误差最低也可能是过拟合，只记住训练样本，不能据此保证新样本误差最低。']
    save('reviewed-input', {'exam_id':exam['id'], 'answers':answers,
        'evidence_type':'依据实际题干独立核读的合成回答；A对应最小验证损失0.18，反复用测试调参的判断为错，简答区分三集职责'})
    creds = json.loads((ROOT / 'credentials.local.json').read_text('utf8'))['shop_ai']
    result = {'exam_id':exam['id'], 'page_errors':[], 'http_errors':[], 'responses':[]}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width':1707,'height':900})
        page.set_default_timeout(30000)
        response = page.request.post(BASE + '/api/auth/login', form=creds)
        assert response.ok
        auth = response.json()
        state = {'edumatrix_token':auth['access_token'], 'edumatrix_username':creds['username'],
            'edumatrix_display_name':creds['username'], 'edumatrix_role':'student', 'edumatrix_onboarded':'true',
            'edumatrix_student_id':auth.get('student_id') or creds['username'], 'edumatrix_course_id':exam['course_id']}
        page.add_init_script('Object.entries(' + json.dumps(state) + ').forEach(([k,v])=>localStorage.setItem(k,v))')
        page.on('pageerror', lambda e: result['page_errors'].append(str(e)))
        page.on('response', lambda r: result['http_errors'].append({'status':r.status,'url':r.url}) if r.status>=400 else None)
        page.on('dialog', lambda dialog: dialog.accept())
        url = BASE + '/workspace/assessment/exams/' + exam['id'] + '?course_id=' + exam['course_id'] + '&review_task=review-plan:57'
        try:
            page.goto(url,wait_until='networkidle')
            start = page.get_by_role('button',name='开始作答',exact=True)
            if start.count():
                start.click()
                expect(page.get_by_role('button',name='提交试卷',exact=True)).to_be_visible()
            if page.get_by_role('button',name='提交试卷',exact=True).count():
                for index, answer in enumerate(answers):
                    page.locator('.question-nav button').nth(index).click()
                    if isinstance(answer,bool): page.locator('.binary-options').get_by_role('button',name='错误',exact=True).click()
                    elif index==0: page.locator('.option-list button').nth(0).click()
                    else: page.locator('.answer-stage textarea').fill(answer)
                    with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/responses')) as saved:
                        page.get_by_role('button',name='保存本题' if index==2 else '保存并下一题',exact=True).click()
                    assert saved.value.ok
                    result['responses'].append(saved.value.json())
                page.reload(wait_until='networkidle')
                expect(page.locator('.question-nav button.saved')).to_have_count(3)
                result['drafts_restored']=True
                page.screenshot(path=str(OUT/'saved.png'),full_page=True)
                save('progress',result)
                with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/submit'),timeout=240000) as submitted:
                    page.get_by_role('button',name='提交试卷',exact=True).click()
                result['submission']={'status':submitted.value.status,'body':submitted.value.json()}
                save('progress',result)
                assert submitted.value.ok
            if page.get_by_role('button',name='查看报告',exact=True).count():
                page.get_by_role('button',name='查看报告',exact=True).click()
            expect(page.get_by_test_id('formal-exam-report')).to_be_visible(timeout=120000)
            result['report_text']=page.get_by_test_id('formal-exam-report').inner_text()
            page.screenshot(path=str(OUT/'report.png'),full_page=True)
            page.reload(wait_until='networkidle')
            if page.get_by_role('button',name='查看报告',exact=True).count():
                page.get_by_role('button',name='查看报告',exact=True).click()
            expect(page.get_by_test_id('formal-exam-report')).to_be_visible()
            result['report_restored']=True
            page.goto(BASE + '/workspace/review?course_id=' + exam['course_id']
                + '&review_task=review-plan:57&month=2026-11', wait_until='networkidle')
            complete = page.get_by_role('button',name='提交复习完成',exact=True)
            expect(complete).to_be_enabled()
            page.locator('.duration-field input').fill('10')
            with page.expect_response(lambda r:r.request.method=='POST'
                    and '/review-schedule/tasks/' in r.url and r.url.endswith('/complete')) as completed:
                complete.click()
            assert completed.value.ok
            result['review_completion']=completed.value.json()
            assert result['review_completion'].get('next_review_at')
            page.screenshot(path=str(OUT/'review-completed.png'),full_page=True)
            result['passed']=not result['page_errors'] and not result['http_errors']
        except Exception:
            result.update(passed=False,failure=traceback.format_exc(),page_text=page.locator('body').inner_text())
            page.screenshot(path=str(OUT/'failed.png'),full_page=True)
        finally:
            save('result',result);browser.close()
    print(json.dumps({k:v for k,v in result.items() if k in ['passed','failure','page_errors','http_errors','drafts_restored','report_restored']},ensure_ascii=False))
    if not result['passed']: raise SystemExit(1)


if __name__=='__main__':main()
