"""Read, answer and restore both saved inquiry branches in the production UI."""
import argparse
import json
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright, expect


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--output',required=True); args=parser.parse_args()
    root=Path(args.output); cases=json.loads((root/'inputs.json').read_text(encoding='utf8'))['cases']
    shots=Path('scratch/validation-20261025/inquiry-ui-r193'); shots.mkdir(parents=True,exist_ok=True)
    reports=[]; errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        for case in cases:
            login=httpx.post('http://127.0.0.1:8944/api/auth/login',data={
                'username':case['username'],'password':'SyntheticLearning193!'}); login.raise_for_status()
            session=login.json()
            context=browser.new_context(viewport={'width':1707,'height':900},device_scale_factor=1.5)
            page=context.new_page(); page.set_default_timeout(45000)
            page.on('pageerror',lambda e: errors.append(str(e)))
            page.add_init_script('''const s = %s;
                localStorage.setItem('edumatrix_token',s.access_token);
                localStorage.setItem('edumatrix_username',s.username);
                localStorage.setItem('edumatrix_student_id',s.username);
                localStorage.setItem('edumatrix_role','student');
                localStorage.setItem('edumatrix_onboarded','true');
                localStorage.setItem('edumatrix_course_id','course-ai-deep-learning-agents-v1');
            ''' % json.dumps({**session,'username':case['username']}))
            url='http://127.0.0.1:8944/workspace/resources/quizzes/'+case['resource_id']
            page.goto(url,wait_until='networkidle')
            panel=page.get_by_test_id('learning-inquiry')
            expect(panel).to_contain_text(case['response'])
            expect(panel.locator('.next-practice')).to_be_visible()
            panel.locator('.learner-response').scroll_into_view_if_needed()
            page.screenshot(path=str(shots/f'{case["name"]}-feedback.png'),full_page=True)
            trace=json.loads((root/f'{case["name"]}-trace.json').read_text(encoding='utf8'))
            answer=trace['feedback']['next_task']['answer']
            if not panel.get_by_text('回答正确',exact=True).count():
                panel.locator(f'input[value="{answer}"]').check()
                panel.get_by_role('button',name='提交练习',exact=True).click()
                expect(panel.get_by_text('回答正确',exact=True)).to_be_visible()
            page.reload(wait_until='networkidle')
            expect(panel.get_by_text('回答正确',exact=True)).to_be_visible()
            expect(panel).to_contain_text(case['response'])
            panel.locator('.next-practice').scroll_into_view_if_needed()
            page.screenshot(path=str(shots/f'{case["name"]}-restored.png'),full_page=True)
            page.set_viewport_size({'width':1100,'height':850})
            panel.locator('.next-practice').scroll_into_view_if_needed()
            page.screenshot(path=str(shots/f'{case["name"]}-narrow.png'),full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            data=page.evaluate('''async id=>{
                let r=await fetch('/api/v1/m5/assessment/attempts/'+id+'/inquiry',
                    {headers:{Authorization:'Bearer '+localStorage.getItem('edumatrix_token')}});
                if(!r.ok)throw Error(r.status);return r.json();}''',case['attempt_id'])
            (root/f'{case["name"]}-ui-result.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
            reports.append({'case':case['name'],'url':url,'saved_response_restored':True,
                'next_practice_correct':data['feedback']['next_task']['latest_attempt']['correct'],
                'next_practice_attempt_id':data['feedback']['next_task']['latest_attempt']['id'],
                'viewports':[1707,1100],'horizontal_overflow':False})
            context.close()
        browser.close()
    (root/'ui-verification.json').write_text(json.dumps({'cases':reports,'page_errors':errors,'screenshots':str(shots)},
        ensure_ascii=False,indent=2),encoding='utf8')
    assert not errors,errors
    print('2 inquiry branches: next practice, persistence and both viewports passed')


if __name__=='__main__': main()
