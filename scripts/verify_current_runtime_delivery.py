"""One unpacked-runtime flow, reusing saved submissions and normal stop/start."""
import argparse
import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sqlite3
import time
import traceback
import zipfile

import requests
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/current-runtime-20261110'
UNPACK=ROOT/'scratch/current-runtime-validation-r208x'
EVIDENCE=OUT/'validation'
BASE='http://127.0.0.1:8966'
COURSE='course-ai-deep-learning-agents-v1'
PASSWORD='EduMatrix2026!'


def save(name,value):
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    (EVIDENCE/f'{name}.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')


def read(name):return json.loads((EVIDENCE/f'{name}.json').read_text('utf8'))


def session(username):
    client=requests.Session();client.trust_env=False
    response=client.post(BASE+'/api/auth/login',data={'username':username,'password':PASSWORD},timeout=30)
    response.raise_for_status();auth=response.json()
    client.headers['Authorization']='Bearer '+auth['access_token']
    return client,auth


def launch(stop=False):
    env=os.environ.copy()
    env.pop('PYTHONPATH',None)
    for key in list(env):
        if key.startswith('EDUMATRIX_') or key=='PYTHON_DOTENV_DISABLED':env.pop(key)
    for key,value in dotenv_values(ROOT/'.env').items():
        if key.startswith('EDUMATRIX_LLM_') and value:env[key]=value
    env.update(EDUMATRIX_PORT='8966',EDUMATRIX_GENERATION_WORKER='true',
        EDUMATRIX_VENV_PATH=str(ROOT/'scratch/automatic-generation-r207/delivery-venv'))
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    log=EVIDENCE/f'{"stop" if stop else "start"}-{int(time.time())}.log'
    with log.open('w',encoding='utf8') as output:
        result=subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',
            str(UNPACK/'launch.ps1'),'-Stop' if stop else '-NoBrowser'],env=env,cwd=UNPACK,
            stdout=output,stderr=subprocess.STDOUT)
    if result.returncode:raise RuntimeError('Launcher failed: '+log.name)
    print('Normal stop requested.' if stop else 'Unpacked runtime started.',flush=True)


def unpack():
    if UNPACK.exists():raise RuntimeError('Independent directory already exists; resume it rather than overwrite.')
    with zipfile.ZipFile(OUT/'EduMatrix_当前运行包.zip') as archive:archive.extractall(UNPACK)
    assert not (UNPACK/'.env').exists()
    save('unpacked',{'path':str(UNPACK),'api_key_in_archive':False})
    print('Unpacked current archive into an independent directory.',flush=True)


def inspect_and_submit():
    accounts={}
    for alias in ['learner','reviewer','explorer','teacher','admin']:
        client,auth=session(alias)
        resources=client.get(BASE+'/api/v1/m5/resources',timeout=60) if auth['role']=='student' else None
        if resources is not None:resources.raise_for_status()
        accounts[alias]={'role':auth['role'],'login':True}
    save('accounts',accounts)
    client,auth=session('explorer')
    if (EVIDENCE/'submission.json').exists():
        print('Reusing saved package-validation submission.');return
    response=client.get(BASE+'/api/v1/m5/today',params={'course_id':COURSE},timeout=60)
    response.raise_for_status()
    task=next(t for t in response.json()['items'] if t.get('generation_context',{}).get('ready'))
    ctx=task['generation_context']
    payload={'course_id':COURSE,'knowledge_point_id':ctx['knowledge_point_id'],
        'profile_snapshot_id':ctx['profile_snapshot_id'],'path_id':task['path_id'],'task_id':task['node_id'],
        'scope':'single','selected_resource_types':['quiz'],'idempotency_key':'current-runtime-one-quiz-r208y',
        'learning_goal':'用一个有明确分母的频数例子检查相对频率，并解释单次抽样的波动。',
        'user_instruction':'本次只需要一道简短单选题。题干给出完整的频数和总次数，要求计算相对频率；四个选项，解析说明分母和单次抽样波动。',
        'items':[{'type':'quiz','title':'频率估计 · 一题练习','source_ref_ids':ctx['source_ref_ids'],
                  'completion_rule':'完成题目并阅读解析。'}]}
    save('request',payload)
    response=client.post(BASE+'/api/v1/resource-bundles/generation-jobs',json=payload,timeout=90)
    response.raise_for_status();save('submission',response.json())
    print('Submitted one selected quiz in the unpacked runtime.',flush=True)


def status():
    client,_=session('explorer');task=read('submission')['job_id']
    response=client.get(BASE+'/api/v1/resource-bundles/generation-jobs/'+task,timeout=60)
    response.raise_for_status();job=response.json();save('current',job)
    print(json.dumps({k:job.get(k) for k in ['job_id','status','automation']},ensure_ascii=False),flush=True)


def assets_and_code():
    client,_=session('learner')
    with sqlite3.connect((UNPACK/'edumatrix.db').as_uri()+'?mode=ro',uri=True) as db:
        sources=[]
        for source_id,raw in db.execute('select id,parser_metadata from source_documents where course_id=?',(COURSE,)):
            asset=json.loads(raw or '{}').get('bundle_asset') or {}
            if asset.get('path'):
                sources.append((source_id,asset))
        for _,asset in sources:
            path=(UNPACK/asset['path']).resolve()
            assert path.is_relative_to(UNPACK) and path.is_file()
            assert hashlib.sha256(path.read_bytes()).hexdigest()==asset['sha256']
        chosen=[next(s for s in sources if not s[1]['path'].startswith('scratch/')),
                next(s for s in sources if s[1]['path'].startswith('scratch/'))]
        downloads=[]
        for source_id,asset in chosen:
            response=client.get(BASE+'/api/v1/document-reader/documents/'+source_id+'/export',timeout=60)
            response.raise_for_status()
            assert hashlib.sha256(response.content).hexdigest()==asset['sha256']
            downloads.append({'source_id':source_id,'path':asset['path'],'original_file_hash_matches':True})
        row=db.execute("select a.id,v.id,v.content from artifacts a join artifact_versions v on v.id=a.current_version_id where a.id=?",
                       ('art-a8f17829374b46db81b6337b737c851e',)).fetchone()
    save('source-assets',{'all_source_assets_match':len(sources),'original_downloads':downloads})
    artifact,version,raw=row;content=json.loads(raw)
    code=next(f['content'] for f in content['files'] if f['path']==content['entryFile'])
    response=client.post(BASE+'/api/v1/code-sandbox/resources/'+artifact+'/runs',json={
        'resource_version_id':version,'code':code,'standard_input':content.get('standardInput',''),
        'idempotency_key':'current-runtime-code-r208w'},timeout=60)
    response.raise_for_status();run=response.json();save('code-submission',run)
    deadline=time.monotonic()+100
    while run['status'] in ['queued','running'] and time.monotonic()<deadline:
        time.sleep(1)
        response=client.get(BASE+'/api/v1/code-sandbox/runs/'+run['runAttemptId'],timeout=30)
        response.raise_for_status();run=response.json()
    save('code-result',run)
    assert run['status']=='success',run['status']
    assert run['passedCount']==run['totalCount'] and run['totalCount']>0
    print('Packaged source files and published code executed in the independent runtime.',flush=True)


def browser_check(after_restart=False):
    from playwright.sync_api import sync_playwright,expect
    result={'page_errors':[],'http_errors':[],'after_restart':after_restart}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        context=browser.new_context(viewport={'width':1707,'height':900},
            **({'storage_state':str(EVIDENCE/'browser-state.local.json')} if after_restart else {}))
        page=context.new_page();page.set_default_timeout(30000)
        page.on('pageerror',lambda e:result['page_errors'].append(str(e)))
        page.on('response',lambda r:result['http_errors'].append({'url':r.url,'status':r.status}) if r.status>=400 else None)
        try:
            if not after_restart:
                page.goto(BASE+'/login',wait_until='networkidle')
                page.get_by_test_id('fill-demo-account').click()
                expect(page.locator('input[autocomplete="username"]')).to_have_value('learner')
                page.get_by_role('button',name='登录',exact=True).click()
                expect(page).not_to_have_url(re.compile('/login'))
                page.goto(BASE+'/workspace/resources',wait_until='networkidle')
                expect(page.get_by_test_id('resource-center')).to_be_visible()
                page.screenshot(path=str(EVIDENCE/'learner-resources.png'),full_page=True)
                result['public_demo_login']=True
                page.get_by_role('button',name='退出登录',exact=True).click()
                expect(page).to_have_url(re.compile('/landing'))
                page.goto(BASE+'/login',wait_until='networkidle')
                page.locator('input[autocomplete="username"]').fill('reviewer')
                page.locator('input[autocomplete="current-password"]').fill(PASSWORD)
                page.get_by_role('button',name='登录',exact=True).click()
                expect(page).not_to_have_url(re.compile('/login'))
                page.goto(BASE+'/workspace/resources',wait_until='networkidle')
                expect(page.get_by_test_id('resource-center')).to_be_visible()
                result['reviewer_demo_login']=True
                # Use the normal login screen again for the small generated quiz.
                page.get_by_role('button',name='退出登录',exact=True).click()
                expect(page).to_have_url(re.compile('/landing'))
                page.goto(BASE+'/login',wait_until='networkidle')
                expect(page.locator('input[autocomplete="username"]')).to_be_visible()
                page.locator('input[autocomplete="username"]').fill('explorer')
                page.locator('input[autocomplete="current-password"]').fill(PASSWORD)
                page.get_by_role('button',name='登录',exact=True).click()
                expect(page).not_to_have_url(re.compile('/login'))
            answers=read('reviewed-answers');url=BASE+'/workspace/resources/quizzes/'+answers['artifact_id']
            reviewed=answers['questions']
            page.goto(url,wait_until='networkidle')
            expect(page.get_by_test_id('quiz-resource-workspace')).to_be_visible()
            if not after_restart:
                for index,answer in enumerate(reviewed):
                    page.locator('.question-rail > button').nth(index).click()
                    if not (EVIDENCE/f'attempt-{index}.json').exists():
                        page.locator('.option-list label').nth(answer['choice']).click()
                        with page.expect_response(lambda r:'/assessment/attempts' in r.url and r.request.method=='POST') as attempt:
                            page.get_by_role('button',name='提交答案',exact=True).click()
                        save('attempt-'+str(index),attempt.value.json())
                    expect(page.locator('.feedback-title strong')).to_have_text('回答正确')
            total=len(reviewed)
            expect(page.locator('.progress-summary strong')).to_have_text(f'{total}/{total}')
            expect(page.locator('.feedback-title strong')).to_have_text('回答正确')
            page.reload(wait_until='networkidle')
            expect(page.locator('.progress-summary strong')).to_have_text(f'{total}/{total}')
            page.screenshot(path=str(EVIDENCE/('after-restart.png' if after_restart else 'quiz-feedback.png')),full_page=True)
            context.storage_state(path=str(EVIDENCE/'browser-state.local.json'))
            result['saved_answer_restored']=True
            result['question_count']=total
            result['passed']=not result['page_errors'] and not result['http_errors']
            save('browser-restart' if after_restart else 'browser',result)
        except Exception:
            result['failure']=traceback.format_exc();save('browser-failure-'+str(int(time.time())),result);raise
        finally:browser.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['unpack','start','stop','submit','status','assets','browser','restart-browser'])
    action=parser.parse_args().action
    {'unpack':unpack,'start':launch,'stop':lambda:launch(True),'submit':inspect_and_submit,
     'status':status,'assets':assets_and_code,'browser':browser_check,'restart-browser':lambda:browser_check(True)}[action]()
