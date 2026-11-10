"""Exercise generated resources through the learner UI on the isolated server."""
import argparse
import json
from pathlib import Path
import traceback
import re
import math
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'scratch/automatic-generation-r207'
BASE = 'http://127.0.0.1:8944'


class FeedbackPending(Exception):
    """A submitted background action remains active; resume its original ID."""


def exercise_concept(page, concept, content, result):
    """Compare actual UI actions with independently calculated scenario values."""
    assert content['templateId'] == 'concept-' + concept
    parameter = next(p for p in content['parameters'] if p['key'] == 'value')
    control = page.get_by_label(parameter['label'], exact=True)
    settings = [0, 10, 20, 30, 40, 5] if concept == 'conditional' else [-4, -1, 0, 1, 4]
    measurements = []
    for value in settings:
        if concept == 'conditional':
            # Predict from the four disjoint cells before operating the model.
            cells = [[value, 30], [40-value, 30]]
            total = sum(sum(row) for row in cells)
            a_count, b_count = sum(cells[0]), sum(row[0] for row in cells)
            expected = [cells[0][0]/b_count, a_count/total,
                        cells[0][0]/total-(a_count/total)*(b_count/total)]
        else:
            weights = [math.exp(score) for score in [value, 0, -1]]
            expected = [weight/sum(weights) for weight in weights]
        if control.get_attribute('type') == 'range':
            control.focus()
            control.press('Home')
            steps = round((value - parameter['minimum']) / parameter['step'])
            for _ in range(steps):
                control.press('ArrowRight')
        else:
            control.fill(str(value))
        expect(control).to_have_value(str(value))
        with page.expect_response(lambda r: '/interactive-lab/instances/' in r.url
                and r.url.endswith('/actions') and r.request.post_data_json.get('action') == 'run') as action:
            page.locator('.parameter-actions .primary-button').click()
        response = action.value
        assert response.ok, response.status
        actual = response.json()
        assert actual['template_id'] == 'concept-' + concept
        assert actual['parameters']['value'] == value
        for i, reference in enumerate(expected):
            assert math.isclose(actual['metrics'][f'm{i}'], reference, abs_tol=6e-10)
        if concept == 'softmax':
            assert math.isclose(sum(actual['metrics'].values()), 1, abs_tol=2e-9)
        measurements.append({'parameters': actual['parameters'], 'metrics': actual['metrics'],
            'independent_expected': expected, 'feedback': actual.get('feedback'),
            'instance_id': actual['instance_id'], 'version': actual['version_number']})
        expect(page.locator('.parameter-actions .primary-button')).to_be_enabled()
        expect(page.get_by_role('table', name='实验指标')).to_be_visible()
    observation = (
        '我先预测v=10时条件概率较低、偏差为负；v=30时条件概率较高、偏差为正；交集计数20时独立。'
        '这是因为v/40-(v+30)/100=0.015v-0.3，正负由v与20的大小决定。前五次运行把A且B设为0、10、20、30、40，'
        'B总数保持40，A且非B保持30，总样本100。P(A|B)依次为0、0.25、0.5、0.75、1，'
        'P(A)依次为0.3、0.4、0.5、0.6、0.7；只有20时两者相等，交集概率也等于边缘概率乘积。'
        '条件概率的分母是B的40个样本，边缘概率的分母是全部100个样本。'
        if concept == 'conditional' else
        '我先预测第一类分数提高时，它的概率会提高。固定后两类logit为0和-1，'
        '第一类依次取-4、-1、0、1、4，实际概率与exp(logit)除以三个指数之和一致，每次概率和为1。'
        '第一类logit为0时与第二类并列最高；为1或4时第一类最高。'
        'logit可以为负且不要求和为1，概率则非负且归一化；这组实验改变了类别间相对分数。'
    )
    observation += '\n逐档先预测、后核对的记录：\n' + '\n'.join(
        f"参数={row['parameters']['value']}；预测数值="
        + ', '.join(f'{x:.6f}' for x in row['independent_expected'])
        + '；实际数值=' + ', '.join(f"{row['metrics'][f'm{i}']:.6f}" for i in range(3))
        + ('；三项和=' + f"{sum(row['metrics'].values()):.9f}" if concept == 'softmax' else '')
        + '，实际与预测一致。' for row in measurements)
    if concept == 'softmax':
        observation += ('\nx=-4和-1时预测第二类最高，x=0时第一、二类并列，x=1和4时第一类最高，'
            '均与logit大小及实际概率排序一致。独立复算x=1时，分母exp(1)+1+exp(-1)，'
            '三个分子为exp(1)、1、exp(-1)，除以分母得到约0.665241、0.244728、0.090031。'
            '先减最大logit等价于分子分母同乘exp(-最大值)，约去后概率不变，并可避免指数上溢。'
            '本实验没有标签，无法判断预测正确与否，单样本概率也不等于数据集准确率。')
    else:
        observation += '\n完整四格与独立性复算：\n' + '\n'.join(
            f'v={v}：四格为{v},30,{40-v},30，合计100；'
            f'联合概率={v/100:.3f}，边缘概率乘积={0.4*(v+30)/100:.3f}，'
            f'偏差={v/100-0.4*(v+30)/100:.3f}。'
            for v in settings)
        observation += ('\n迁移自查v=5：先算5/40=0.125，35/100=0.35，'
            '联合概率0.05、乘积0.14、偏差-0.09，再运行核对，一致。'
            'v=0时互斥但P(A)=0.3、P(B)=0.4均为正，因此不独立；'
            'v=20时独立但联合概率0.2不为零，因此不互斥。'
            '本表把100个样本作为完整练习总体，偏差小但不为0仍不独立；'
            '没有第三变量C的分层资料，不能据此判断条件独立。'
            '\n预测：两种方向均与结果相符，依据代数比较。'
            '\n计算：条件分母用40、边缘分母用100，下一次仍先检查条件和四格总数。'
            '\n解释：以联合概率等于边缘乘积判断独立；后续可用新列联表独立重做。')
    page.get_by_label('观察结论', exact=True).fill(observation)
    page.get_by_role('button', name='提交观察结论', exact=True).click()
    expect(page.get_by_test_id('interactive-model-completion')).to_be_visible()
    page.reload(wait_until='networkidle')
    expect(page.get_by_test_id('interactive-model-completion')).to_be_visible()
    expect(page.get_by_label('观察结论', exact=True)).to_have_value(observation)
    result['checks'].update(measurements=measurements, observation_restored=True,
                           concept=concept, independent_numeric_comparisons=len(measurements)*3)


def verify(kind, run=None, persona=None, answers=None, concept=None, responses=None, feedback_wait_seconds=45):
    manifest = json.loads((OUT / 'inputs.json').read_text(encoding='utf8'))
    if concept:
        assert kind == 'interactive_model' and run
        additional = json.loads((OUT / 'capability-inputs-r208e.json').read_text(encoding='utf8'))
        case = next(c for c in additional['cases'] if c['id'] == 'concept-' + concept)
        assert run.startswith(case['id'] + '-')
    else:
        case = next(c for c in manifest['cases'] if c['id'] == 'single-' + kind)
    folder = OUT / 'runs' / (run or ('single-' + kind + ('-r208' if kind in {'deck','feynman','interactive_model'} else '' if kind == 'video' else '-c')))
    versions = json.loads((folder / 'versions.json').read_text(encoding='utf8'))
    version = next(v for v in reversed(versions) if v['metadata_json']['resource_type'] == kind)
    learning = json.loads(Path(responses).read_text(encoding='utf8')) if responses else {}
    if learning:
        assert learning['version_id'] == version['id'], 'Reviewed learner responses belong to another resource version.'
    if kind == 'feynman' and folder.name != 'single-feynman-r208':
        assert all(learning.get(k) for k in ('round1', 'question', 'round2')), 'Review this version and supply its synthetic learner responses.'
    if kind == 'training_task' and folder.name != 'single-training_task-c':
        assert learning.get('report'), 'Supply the independently reviewed report for this version and its new transfer task.'
    credentials = json.loads((OUT / 'credentials.local.json').read_text(encoding='utf8'))[persona or case['persona']]
    routes = {'handout':'resources/handouts', 'code_sandbox':'code', 'quiz':'resources/quizzes',
              'training_task':'resources/training-tasks', 'video':'resources/videos',
              'interactive_model':'resources/models', 'deck':'resources/decks', 'feynman':'feynman'}
    result = {'resource_id':version['artifact_id'], 'version_id':version['id'], 'kind':kind,
              'evidence_type':'真实生成资源、浏览器实际操作；Codex核读答案后脚本模拟学习，不计正式指标',
              'checks':{}, 'page_errors':[], 'http_errors':[]}
    shots = OUT / 'browser' / run if run else OUT / 'browser'
    shots.mkdir(parents=True, exist_ok=True)
    prior_path = shots / f'{kind}-r208-learning.json'
    prior = json.loads(prior_path.read_text(encoding='utf8')) if prior_path.exists() else {}
    if prior.get('version_id') != version['id']:
        prior = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width':1707, 'height':900}, device_scale_factor=1)
        page = context.new_page()
        page.set_default_timeout(30000)
        page.on('pageerror', lambda error: result['page_errors'].append(str(error)))
        page.on('response', lambda response: result['http_errors'].append({'status':response.status,'url':response.url}) if response.status >= 400 else None)
        login = page.request.post(BASE + '/api/auth/login', form=credentials)
        assert login.ok, login.status
        auth = login.json()
        state = {'edumatrix_token':auth['access_token'], 'edumatrix_username':credentials['username'],
                 'edumatrix_display_name':auth.get('display_name') or credentials['username'],
                 'edumatrix_student_id':auth.get('student_id') or credentials['username'],
                 'edumatrix_role':'student','edumatrix_onboarded':'true',
                 'edumatrix_course_id':manifest['course_id'],
                 'edumatrix_course_title':'人工智能与深度学习：从机器学习基础到大模型智能体'}
        page.add_init_script('Object.entries(' + json.dumps(state) + ').forEach(([k,v])=>localStorage.setItem(k,v))')
        url = BASE + '/workspace/' + routes[kind] + '/' + version['artifact_id']
        result['url'] = url
        try:
            page.goto(url, wait_until='networkidle')
            if kind == 'handout':
                content = json.loads(version['content'])
                quizzes = content['miniQuiz']
                expect(page.locator('.quiz-section')).to_have_count(len(quizzes))
                for index, item in enumerate(quizzes):
                    section = page.locator('.quiz-section').nth(index)
                    section.locator('input[type=radio]').nth(item['correctIndex']).check()
                    section.get_by_role('button', name='检查答案', exact=True).click()
                    expect(section.locator('.quiz-feedback.correct')).to_be_visible()
                result['checks']['mini_quizzes'] = len(quizzes)
                page.reload(wait_until='networkidle')
                expect(page.locator('.quiz-feedback.correct')).to_have_count(len(quizzes))
                result['checks']['answers_restored'] = True
            elif kind == 'code_sandbox':
                button = page.get_by_role('button', name='运行代码', exact=True)
                expect(button).to_be_enabled()
                button.click()
                expect(page.locator('.result-summary.status-success')).to_be_visible(timeout=60000)
                required = len(json.loads(version['content'])['requiredChecks'])
                expect(page.locator('.check-results li')).to_have_count(required)
                expect(page.locator('.check-results li.passed')).to_have_count(required)
                result['checks']['required_checks_passed'] = required
                result['checks']['execution'] = page.locator('.result-summary').inner_text()
                result['checks']['stdout'] = page.locator('.result-scroll pre').first.inner_text()
                page.screenshot(path=str(shots / 'code-r208-run.png'))
                complete = page.get_by_role('button', name='完成学习', exact=True)
                expect(complete).to_be_enabled()
                complete.click()
                expect(page.get_by_role('button', name='已完成学习', exact=True)).to_be_visible()
                page.reload(wait_until='networkidle')
                expect(page.locator('.result-summary.status-success')).to_be_visible()
                expect(page.get_by_role('button', name='已完成学习', exact=True)).to_be_visible()
                result['checks']['run_and_completion_restored'] = True
            elif kind == 'training_task':
                if prior.get('checks', {}).get('observation_restored'):
                    result['checks'].update(prior['checks'])
                    measurements = result['checks']['measurements']
                    observation = ('实际模拟记录：' + json.dumps(measurements, ensure_ascii=False)
                        + '。只比较这五个运行点，不能外推全局最优；这些模拟指标不能当固定数据MSE或独立测试成绩。')
                else:
                    expect(page.locator('.tool-entry')).to_have_count(2)
                    expect(page.get_by_role('button', name='进入代码沙盒')).to_be_enabled()
                    expect(page.get_by_role('button', name='打开可交互模型')).to_be_enabled()
                    page.screenshot(path=str(shots / 'training-r208-instructions.png'))
                    page.get_by_role('button', name='进入代码沙盒').click()
                    expect(page.get_by_role('button', name='运行代码', exact=True)).to_be_enabled()
                    result['checks']['linked_code_url'] = page.url
                    page.get_by_role('button', name='运行代码', exact=True).click()
                    expect(page.locator('.result-summary.status-success')).to_be_visible(timeout=90000)
                    assert page.locator('.check-results li').count() == page.locator('.check-results li.passed').count()
                    result['checks']['code_stdout'] = page.locator('.result-scroll pre').first.inner_text()
                    page.get_by_role('button', name='完成学习', exact=True).click()
                    expect(page.get_by_role('button', name='已完成学习', exact=True)).to_be_visible()
                    page.goto(url, wait_until='networkidle')
                    page.get_by_role('button', name='打开可交互模型').click()
                    expect(page.get_by_label('模型复杂度', exact=True)).to_be_visible()
                    result['checks']['linked_model_url'] = page.url
                    measurements = []
                    def run_model(complexity, regularization):
                        page.get_by_label('模型复杂度', exact=True).fill(str(complexity))
                        page.get_by_label('训练样本量', exact=True).fill('500')
                        slider = page.get_by_label('正则强度', exact=True)
                        slider.focus(); slider.press('Home')
                        for _ in range(round(regularization/.05)):
                            slider.press('ArrowRight')
                        with page.expect_response(lambda r: '/interactive-lab/instances/' in r.url and r.url.endswith('/actions')
                                                  and r.request.post_data_json.get('action') == 'run') as action:
                            page.locator('.parameter-actions .primary-button').click()
                        response = action.value; assert response.ok, response.status
                        data = response.json()
                        expect(page.locator('.parameter-actions .primary-button')).to_be_enabled()
                        measurements.append({'parameters':data['parameters'], 'metrics':data['metrics'],
                                             'instance_id':data['instance_id'], 'version':data['version_number']})
                    for complexity in (1,5,9): run_model(complexity, .2)
                    best = max(measurements, key=lambda row: row['metrics']['validation_score'])['parameters']['model_complexity']
                    for regularization in (.1,.6): run_model(best, regularization)
                    result['checks']['measurements'] = measurements
                    observation = ('保持样本量500，复杂度1/5/9的实际结果为：' + json.dumps(measurements[:3],ensure_ascii=False)
                        + f'。在所列三个点中选择验证得分最高的复杂度{best}；固定该复杂度后的正则对照为：'
                        + json.dumps(measurements[3:],ensure_ascii=False)
                        + '。复杂度升高时训练得分改善并不保证验证得分改善，需结合泛化差距和推理成本。'
                        '只比较这五个运行点，不能外推全局最优；这些是模拟指标，不能当固定数据MSE或独立测试成绩。')
                    page.get_by_label('观察结论', exact=True).fill(observation)
                    page.get_by_role('button', name='提交观察结论', exact=True).click()
                    expect(page.get_by_test_id('interactive-model-completion')).to_be_visible()
                    page.reload(wait_until='networkidle')
                    expect(page.get_by_test_id('interactive-model-completion')).to_be_visible()
                    page.screenshot(path=str(shots / 'training-r208-observation.png'))
                    result['checks']['observation_restored'] = True
                    page.goto(url, wait_until='networkidle')
                page.get_by_role('button', name=re.compile('.*整理实训报告')).click()
                expect(page.get_by_role('button', name='编辑', exact=True)).to_be_visible()
                result['checks']['report_url'] = page.url
                page.get_by_role('button', name='编辑', exact=True).click()
                editor = page.get_by_role('textbox', name='笔记正文', exact=True)
                report = ('# 模型选择与过拟合：实践记录\n\n'
                    '固定数据为10条训练、4条验证，无测试集。预处理与模型只在训练部分拟合，验证用于选模。\n\n'
                    '## 计算\n第一验证点残差约0.2417968593，平方约0.0584657211；验证MSE为四项平方误差的平均。\n'
                    '实际代码输出：\n```text\n' + result['checks']['code_stdout'] + '\n```\n\n'
                    '按验证MSE选择3阶；9阶训练误差最低却验证误差最高，是过拟合表现。3阶验证误差小于训练误差并不矛盾，'
                    '两组样本不同且验证样本只有4条，结论只限当前切分。\n\n## 模拟观察\n' + observation + '\n\n'
                    '## 数据流与泄漏\n全量标准化使用了验证统计量；验证行参与fit也会污染评估。预处理和模型只在训练部分fit，'
                    '交叉验证每折也按此操作。正常用验证比较候选是选择用途，反复调参会使验证表现偏乐观。'
                    '反复拿测试集挑模型会把测试信息带入选择；应固定方案后另用全新独立测试一次。'
                    '合并训练与验证重拟合可以，但旧验证分数不再是最终模型的独立成绩。\n\n'
                    '## 新表\nS在切分前拟合标准化，不能按最低0.10直接选；P/Q/R预处理范围未给出，只能暂按表中分数比较。'
                    'Q的验证MSE0.14最低，暂选Q并先核对条件。R训练0.0008而验证0.29提示过拟合；P两端较高可能容量不足，'
                    '仅两个数不能定因。无独立测试时只报告验证阶段结论。')
                if learning.get('report'):
                    report = learning['report'].replace('{{code_stdout}}', result['checks']['code_stdout']).replace('{{observation}}', observation)
                if editor.input_value() != report:
                    editor.fill(report)
                    page.get_by_role('button', name='保存新版本', exact=True).click()
                    expect(page.get_by_role('button', name='编辑', exact=True)).to_be_visible()
                page.reload(wait_until='networkidle')
                if page.get_by_role('textbox', name='笔记正文', exact=True).count():
                    expect(page.get_by_role('textbox', name='笔记正文', exact=True)).to_have_value(report)
                else:
                    expect(page.get_by_test_id('notes-document')).to_contain_text('实践记录')
                result['checks']['report_saved_and_restored'] = True
                page.goto(url, wait_until='networkidle')
                expect(page.get_by_role('button', name='继续整理实训报告')).to_be_visible()
            elif kind == 'interactive_model' and concept:
                exercise_concept(page, concept, json.loads(version['content']), result)
            elif kind == 'interactive_model':
                expect(page.get_by_label('模型复杂度', exact=True)).to_be_visible()
                measurements = []
                high = 9 if run == 'single-interactive_model-r208d' else 10
                for complexity, regularization, samples in [(1,.2,500),(5,.2,500),(high,.2,500),
                                                          (high,0,500),(high,.8,500),(high,.2,100),(high,.2,1000)]:
                    page.get_by_label('模型复杂度', exact=True).fill(str(complexity))
                    page.get_by_label('训练样本量', exact=True).fill(str(samples))
                    slider = page.get_by_label('正则强度', exact=True)
                    slider.focus(); slider.press('Home')
                    for _ in range(round(regularization/.05)): slider.press('ArrowRight')
                    with page.expect_response(lambda r: '/interactive-lab/instances/' in r.url and r.url.endswith('/actions')
                            and r.request.post_data_json.get('action') == 'run') as action:
                        page.locator('.parameter-actions .primary-button').click()
                    response = action.value; assert response.ok, response.status
                    data = response.json()
                    measurements.append({'parameters':data['parameters'], 'metrics':data['metrics'],
                                         'instance_id':data['instance_id'], 'version':data['version_number']})
                    expect(page.locator('.parameter-actions .primary-button')).to_be_enabled()
                result['checks']['measurements'] = measurements
                observation = ('七次实际模拟：' + json.dumps(measurements,ensure_ascii=False)
                    + f'。复杂度对照固定样本500、正则0.2；正则对照固定复杂度{high}、样本500；样本量对照固定复杂度{high}、正则0.2。'
                    '训练得分提高不保证验证得分提高，复杂度增加也增加推理成本；较强正则可能缩小差距而同时降低得分。'
                    '本页为教学模拟；主例固定10/4数据按验证MSE选择3阶，三个验证MSE约0.03975、0.00425、0.23944。'
                    '预处理只在训练部分拟合，测试数据要保持独立；没有测试集时不报告测试成绩。')
                page.get_by_label('观察结论', exact=True).fill(observation)
                page.get_by_role('button', name='提交观察结论', exact=True).click()
                expect(page.get_by_test_id('interactive-model-completion')).to_be_visible()
                page.reload(wait_until='networkidle')
                expect(page.get_by_test_id('interactive-model-completion')).to_be_visible()
                expect(page.get_by_label('观察结论', exact=True)).to_have_value(observation)
                result['checks']['observation_restored'] = True
            elif kind == 'deck':
                slides = json.loads(version['content'])['slides']
                expect(page.locator('.outline-row')).to_have_count(len(slides))
                result['checks']['slides'] = []
                for index, slide in enumerate(slides):
                    page.locator('.outline-row').nth(index).click()
                    expect(page.get_by_test_id('deck-stage').locator('h2')).to_have_text(slide['title'])
                    result['checks']['slides'].append({'id':slide['id'], 'title':slide['title'],
                        'text':page.get_by_test_id('deck-stage').inner_text()})
                    if index in {0,len(slides)//2,len(slides)-1}:
                        page.screenshot(path=str(shots / f'deck-r208-page-{index+1}.png'))
                page.reload(wait_until='networkidle')
                expect(page.locator('.outline-row').last).to_have_class(re.compile('active'))
                result['checks']['selected_slide_restored'] = True
                for fmt in ['HTML','PPTX']:
                    with page.expect_download(timeout=90000) as download:
                        page.get_by_role('button',name='导出 '+fmt,exact=True).click()
                    artifact = shots / ('deck-r208-export.' + fmt.lower())
                    download.value.save_as(str(artifact))
                    assert artifact.stat().st_size > 100
                    result['checks']['export_' + fmt.lower()] = str(artifact)
            elif kind == 'feynman':
                result['checks']['actions'] = prior.get('checks', {}).get('actions', [])
                targets = {'evaluate_round1': '提出疑问', 'answer_question': '保存第二次复述',
                           'evaluate_round2': '应用到后续学习'}
                def current_task():
                    expect(page).to_have_url(re.compile(r'[?&]session_id='))
                    session_id = parse_qs(urlparse(page.url).query)['session_id'][0]
                    response = page.request.get(BASE+'/api/v1/feynman/sessions/'+session_id+'/action-task',
                        headers={'Authorization':'Bearer '+auth['access_token']})
                    assert response.ok, response.text()
                    return response.json().get('task')
                def await_feedback(task):
                    if not task or task['status'] in {'completed','cancelled'}:
                        return
                    target = page.get_by_role('button',name=targets[task['action']],exact=True)
                    try:
                        expect(target).to_be_enabled(timeout=feedback_wait_seconds*1000)
                    except AssertionError:
                        actual = current_task()
                        assert actual['id']==task['id']
                        assert actual['automation']['state'] in {'queued','running','retry_wait'},actual
                        page.reload(wait_until='networkidle')
                        assert current_task()['id']==task['id']
                        result['pending_task']=actual
                        result['checks']['background_task_restored']=True
                        raise FeedbackPending()
                await_feedback(current_task())
                def feynman_action(label, name):
                    with page.expect_response(lambda r: '/api/v1/feynman/sessions/' in r.url
                            and r.url.endswith('/actions'), timeout=900000) as response:
                        page.get_by_role('button',name=label,exact=True).click()
                    actual = response.value
                    payload = actual.json()
                    result['checks']['actions'].append({'action':name,'status':actual.status,'result':payload})
                    prior_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
                    assert actual.ok, payload
                    page.reload(wait_until='networkidle')
                    if payload.get('task'):
                        await_feedback(payload['task'])
                        result['checks']['actions'][-1]['background_completed_after_refresh'] = True
                        prior_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
                if page.locator('#round1').count():
                    page.locator('#round1').fill(learning.get('round1') or '训练误差衡量模型对训练样本的拟合。我看到九阶训练MSE约0.0000146，比一阶和三阶低得多，所以我会先选九阶。我知道验证数据没有拿去训练，但不确定为什么还要因为验证MSE更高而放弃它。标准化我习惯先对全量数据做，觉得这没有使用标签。')
                    feynman_action('保存第一次复述','submit_round1')
                if page.get_by_role('button',name='生成第一次评价',exact=True).count():
                    feynman_action('生成第一次评价','evaluate_round1')
                if page.get_by_role('button',name='提出疑问',exact=True).count():
                    feynman_action('提出疑问','begin_question')
                if page.locator('#question').count():
                    page.locator('#question').fill(learning.get('question') or '为什么九阶训练误差几乎为零还要选择三阶？全量标准化没有用标签，为什么也会造成泄漏？')
                    feynman_action('提交疑问并查看回答','answer_question')
                if page.locator('#round2').count():
                    page.locator('#round2').fill(learning.get('round2') or '训练误差只描述对已见样本的拟合，泛化误差是同分布新样本上的期望损失。固定10条训练和4条验证数据中，三个验证MSE约为0.0397528、0.00425314、0.239444，所以暂选三阶。九阶训练接近零但验证差，显示过拟合风险；三阶验证小于训练也可能来自两组样本及小验证集的波动。MSE为每条预测与真实值差的平方之和除以样本数。预处理统计量和模型参数都只在训练行拟合；全量标准化即使不用标签也利用了验证分布，交叉验证每折也要单独拟合。验证用于选方案，最终方案冻结后才用全新独立测试数据评价，反复看测试调参会失去独立性。本题没有测试数据，不能报告测试成绩。新表中D用训练加验证拟合标准化，须重新按训练拟合后重算；对条件相同的A、B、C，B验证MSE0.090最低，暂选B。')
                    feynman_action('保存第二次复述','submit_round2')
                if page.get_by_role('button',name='生成第二次评价与对比',exact=True).count():
                    feynman_action('生成第二次评价与对比','evaluate_round2')
                if page.get_by_role('button',name='应用到后续学习',exact=True).count():
                    page.screenshot(path=str(shots / 'feynman-r208-comparison.png'))
                    feynman_action('应用到后续学习','apply')
                expect(page.get_by_role('heading',name='已应用到后续学习',exact=True)).to_be_visible()
                page.reload(wait_until='networkidle')
                expect(page.get_by_role('heading',name='已应用到后续学习',exact=True)).to_be_visible()
                result['checks']['applied_and_restored'] = True
            elif kind == 'video':
                expect(page.locator('.recommendation-row')).to_have_count(3)
                result['checks']['sources'] = []
                for index in range(3):
                    page.locator('.recommendation-row').nth(index).click()
                    expect(page.get_by_test_id('embedded-video-player')).to_be_visible()
                    frame = page.get_by_test_id('embedded-video-player')
                    result['checks']['sources'].append({'title':page.locator('.player-title h2').inner_text(),
                        'iframe_src':frame.get_attribute('src'),
                        'original_url':page.get_by_role('link',name='在原网站观看').get_attribute('href')})
                page.reload(wait_until='domcontentloaded')
                expect(page.locator('.recommendation-row').nth(2)).to_have_class(re.compile('active'))
                result['checks']['selection_restored'] = True
                result['checks']['playback'] = '待核对外部播放器的实际播放状态；iframe出现不计观看成功'
            else:
                if answers:
                    reviewed = json.loads(Path(answers).read_text(encoding='utf8'))
                    assert reviewed['version_id'] == version['id']
                    choices = reviewed['choices']
                else:
                    # Only this original version uses the previously reviewed selections.
                    assert folder.name == 'single-quiz-c', 'Supply reviewed answers for this resource version.'
                    choices = [1,0,2,1,3,0]
                assert len(choices) == len(json.loads(version['content'])['questions'])
                for index, choice in enumerate(choices):
                    page.locator('.question-rail button').nth(index).click()
                    page.locator('.option-list label').nth(choice).click()
                    page.get_by_role('button', name='提交答案', exact=True).click()
                    expect(page.locator('.feedback-title strong')).to_have_text('回答正确')
                    if index == 1:
                        page.screenshot(path=str(shots / 'quiz-r208-calculation.png'))
                expect(page.locator('.progress-summary strong')).to_have_text(f'{len(choices)}/{len(choices)}')
                page.reload(wait_until='networkidle')
                expect(page.locator('.progress-summary strong')).to_have_text(f'{len(choices)}/{len(choices)}')
                result['checks']['answered_correctly_and_restored'] = len(choices)
            result['checks']['horizontal_overflow'] = page.evaluate('document.documentElement.scrollWidth > innerWidth + 2')
            page.screenshot(path=str(shots / f'{kind}-r208-complete.png'))
            result['passed'] = not result['page_errors'] and not result['http_errors'] and not result['checks']['horizontal_overflow']
        except FeedbackPending:
            result.update(passed=None,outcome='feedback_pending')
            page.screenshot(path=str(shots/'feynman-feedback-pending.png'))
            assert not result['page_errors'] and not result['http_errors'], result
        except Exception:
            result['passed'] = False
            result['failure'] = traceback.format_exc()
            result['page_text'] = page.locator('body').inner_text()[:14000]
            page.screenshot(path=str(shots / f'{kind}-r208-failure.png'))
        finally:
            (shots / f'{kind}-r208-learning.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
            browser.close()
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if result['passed'] is False: raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('kind', choices=['handout','code_sandbox','quiz','training_task','video','interactive_model','deck','feynman'])
    parser.add_argument('--run', help='Existing run folder; never creates a generation task.')
    parser.add_argument('--persona', help='Existing synthetic learner credential label.')
    parser.add_argument('--answers', help='Independently reviewed quiz choices tied to the exact version.')
    parser.add_argument('--concept', choices=['conditional', 'softmax'], help='Use the frozen supplementary experiment scenario.')
    parser.add_argument('--responses', help='Reviewed synthetic Feynman responses or training report tied to the exact version.')
    parser.add_argument('--feedback-wait-seconds', type=int, default=45)
    args = parser.parse_args()
    verify(args.kind, args.run, args.persona, args.answers, args.concept, args.responses, args.feedback_wait_seconds)
