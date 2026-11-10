"""Check the repaired training version and its exact linked code, reusing lab UI evidence."""
import json
from pathlib import Path
import re
import traceback
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]/'scratch/automatic-generation-r207'
OUT=ROOT/'browser/training-final-r208s'
BASE='http://127.0.0.1:8955'


def save(name,value):
    (OUT/f'{name}.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    versions=json.loads((ROOT/'runs/single-training_task-c/published-versions-r208r.json').read_text('utf8'))
    training=next(v for v in versions if v['metadata_json']['resource_type']=='training_task')
    body=json.loads(training['content'])
    code=next(v for v in versions if v['metadata_json']['resource_type']=='code_sandbox')
    model=next(v for v in versions if v['metadata_json']['resource_type']=='interactive_model')
    assert body['linkedSandboxId']==code['artifact_id'] and body['linkedModelId']==model['artifact_id']
    assert sum(r['points'] for r in body['rubric'][:-1])==100 and body['rubric'][-1]['points']==0
    report='''# 模型选择与过拟合：实践记录

开始自评7/10。我用同一验证集的MSE比较候选，分母为4，单位是y的平方。训练用来拟合，验证用来选方案；4个验证样本不足以给出精确总体误差，当前没有测试集。

固定表逐点平方误差：1阶[0.058466,0.008053,0.077562,0.014930]；3阶[0.0002928,0.0016565,0.0007333,0.0143300]；9阶[0.0622737,0.0000695,0.0002379,0.8951952]。各自和除以4约为0.039753、0.004253、0.239444，选择3阶。训练MSE约为0.072289、0.024205、0.0000146；9阶训练更低而验证更差，提示过拟合。1阶两端相对3阶更差是欠拟合线索。

配套代码实际输出如下；输入列形状为(10,1)/(4,1)，验证顺序0.06、0.27、0.50、0.95。matrix_rank_degree9检查原始10×9无偏置特征，不能与拟合器内部中心化的rank_混比。
{{stdout}}

A先在全部数据拟合标准化造成验证信息泄漏，应先切分、只在训练行拟合参数，再变换验证行；每折交叉验证同理。B反复挑最低验证误差会产生选择偏差；方案固定后另用未参与选择的数据做最终评估。正常用验证集比较候选属于模型选择，不因此自动算泄漏。

新表A残差[0.02,0.03,-0.02,-0.05]，平方和0.0042，MSE=0.00105；B残差[-0.25,0.30,-0.25,0.55]，平方和0.5175，MSE=0.129375，选A。B训练误差0.0002较低不能代替验证选择。此表没有测试集。

本次完成核心计算、代码核对和判断；交互拓展为0分可选，留待下一学习段，未补造其运行记录。
'''
    save('reviewed-input',{'version_id':training['id'],'linked_code_version':code['id'],
        'linked_model_version':model['id'],'rubric_points':[r['points'] for r in body['rubric']],
        'report_template':report,'lab_evidence':'既有工作区参数、实际输出及保存恢复证据复用；本轮只检查最终绑定和评分对应。'})
    credentials=json.loads((ROOT/'credentials.local.json').read_text('utf8'))['software_developer']
    result={'version_id':training['id'],'page_errors':[],'http_errors':[]}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1707,'height':900})
        page.set_default_timeout(30000)
        auth=page.request.post(BASE+'/api/auth/login',form=credentials).json()
        state={'edumatrix_token':auth['access_token'],'edumatrix_username':credentials['username'],
            'edumatrix_student_id':auth.get('student_id') or credentials['username'],
            'edumatrix_role':'student','edumatrix_onboarded':'true','edumatrix_course_id':'course-ai-deep-learning-agents-v1'}
        page.add_init_script('Object.entries('+json.dumps(state)+').forEach(([k,v])=>localStorage.setItem(k,v))')
        page.on('pageerror',lambda e:result['page_errors'].append(str(e)))
        page.on('response',lambda r:result['http_errors'].append({'url':r.url,'status':r.status}) if r.status>=400 else None)
        url=BASE+'/workspace/resources/training-tasks/'+training['artifact_id']
        try:
            page.goto(url,wait_until='networkidle')
            expect(page.get_by_role('button',name='进入代码沙盒')).to_be_enabled()
            expect(page.get_by_role('button',name='打开可交互模型')).to_be_enabled()
            page.screenshot(path=str(OUT/'training.png'),full_page=True)
            page.get_by_role('button',name='进入代码沙盒').click()
            expect(page).to_have_url(re.compile(re.escape(code['artifact_id'])))
            page.get_by_role('button',name='运行代码',exact=True).click()
            expect(page.locator('.result-summary.status-success')).to_be_visible(timeout=90000)
            count=len(json.loads(code['content'])['requiredChecks'])
            expect(page.locator('.check-results li.passed')).to_have_count(count)
            result['stdout']=page.locator('.result-scroll pre').first.inner_text()
            assert 'matrix_rank_degree9=9' in result['stdout'] and 'selection=degree_3' in result['stdout']
            result['code_checks']=count
            save('progress',result)
            page.screenshot(path=str(OUT/'linked-code.png'),full_page=True)
            page.goto(url,wait_until='networkidle')
            page.get_by_role('button',name=re.compile('.*整理实训报告')).click()
            page.get_by_role('button',name='编辑',exact=True).click()
            editor=page.get_by_role('textbox',name='笔记正文',exact=True)
            editor.fill(report.replace('{{stdout}}',result['stdout']))
            page.get_by_role('button',name='保存新版本',exact=True).click()
            expect(page.get_by_role('button',name='编辑',exact=True)).to_be_visible()
            page.reload(wait_until='networkidle')
            expect(page.get_by_test_id('notes-document')).to_contain_text('MSE=0.00105')
            result['report_saved']=True
            page.goto(url,wait_until='networkidle')
            expect(page.get_by_role('button',name='继续整理实训报告')).to_be_visible()
            result['passed']=not result['page_errors'] and not result['http_errors']
            save('result',result)
        except Exception:
            result['failure']=traceback.format_exc();save('failure',result)
            page.screenshot(path=str(OUT/'failure.png'),full_page=True);raise
        finally:browser.close()
    print('Final training links, five code checks, optional zero score and saved report passed.')


if __name__=='__main__':main()
