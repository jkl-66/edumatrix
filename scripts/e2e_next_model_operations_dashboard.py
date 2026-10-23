"""NC-GOV-04 isolated Chromium acceptance."""
from __future__ import annotations
import hashlib,json,os,socket,sqlite3,subprocess,sys,time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1];OUT=Path(os.environ.get('EDUMATRIX_E2E_OUTPUT_DIR',ROOT/'outputs'/'NEXT_完全体主动开发'/'evidence'/'NC-GOV-04'/'browser-e2e'));DB=Path(os.environ.get('EDUMATRIX_E2E_DB_PATH',ROOT/'outputs'/'_next_gov_model_ops_e2e.db'));EVIDENCE=OUT/'model_operations_dashboard_evidence.db';PORT=8794;BASE=f'http://127.0.0.1:{PORT}';PASSWORD='Next-gov-model-ops-2026!'
def wait(open_,timeout=45):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        with socket.socket() as s:available=s.connect_ex(('127.0.0.1',PORT))==0
        if available is open_:return
        time.sleep(.2)
    raise RuntimeError('port state timeout')
def stop(p):
    if p and p.poll() is None:subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True,timeout=15);p.wait(timeout=5);wait(False,15)
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    for p in OUT.iterdir():
        if p.is_file():p.unlink()
    for suffix in ('','-wal','-shm'):
        p=Path(str(DB)+suffix)
        if p.exists():p.unlink()
    env=os.environ.copy();env.update({'EDUMATRIX_DB_PATH':str(DB),'EDUMATRIX_AUTH_SECRET_KEY':'nc-gov-04-e2e','EDUMATRIX_DEMO_MODE':'1','EDUMATRIX_LLM_PROVIDER':'deterministic','EDUMATRIX_LLM_MODEL':'deterministic','EDUMATRIX_LLM_API_KEY':'','EDUMATRIX_LLM_ENDPOINT':'','EDUMATRIX_RELOAD':'0','EDUMATRIX_HOST':'127.0.0.1','EDUMATRIX_PORT':str(PORT),'PYTHONUNBUFFERED':'1'})
    report={'schema_version':'next.nc-gov-04-browser-e2e.v1','started_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'checks':{},'screenshots':[]};backend=None
    try:
        with (OUT/'backend.log').open('w',encoding='utf-8') as log:
            backend=subprocess.Popen([sys.executable,'run.py'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT);wait(True)
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True);context=browser.new_context(viewport={'width':1440,'height':1000},locale='zh-CN',accept_downloads=True);page=context.new_page()
                try:
                    stamp=str(int(time.time()))
                    tokens={}
                    for name in ('gov_teacher','gov_outsider','gov_student'):
                        username=f'{name}_{stamp}';res=page.request.post(f'{BASE}/api/auth/register',data={'username':username,'password':PASSWORD,'display_name':name});assert res.ok;tokens[name]=res.json()['access_token'];tokens[name+'_name']=username
                    with sqlite3.connect(DB) as db:
                        db.execute("UPDATE users SET role='teacher' WHERE username IN (?,?)",(tokens['gov_teacher_name'],tokens['gov_outsider_name']))
                        ids={row[0]:row[1] for row in db.execute('SELECT username,public_id FROM users WHERE username IN (?,?,?)',(tokens['gov_teacher_name'],tokens['gov_outsider_name'],tokens['gov_student_name']))}
                        teacher,outsider,student=(ids[tokens[k+'_name']] for k in ('gov_teacher','gov_outsider','gov_student'))
                        db.executemany('INSERT INTO courses(id,version,title,visibility,status,owner_public_id,manifest_version,manifest_data,created_at) VALUES(?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)',[('gov-course','1','模型运营课程','private','published',teacher,'1','{}'),('hidden-course','1','隔离课程','private','published',outsider,'1','{}')])
                        db.execute("INSERT INTO course_memberships(id,course_id,user_public_id,role,status,created_at,updated_at) VALUES('cm-gov','gov-course',?,'teacher','active',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",(teacher,))
                        calls=[('call-ok','trace-gov-ok','gov-course','quiz','completed',120,30,.002,'price-demo',900,''),('call-fail','trace-gov-fail','gov-course','quiz','failed',40,0,0,'unpriced',22000,'provider_timeout'),('call-hidden','trace-hidden','hidden-course','report','completed',999,999,8,'price-secret',5,'')]
                        for cid,trace,course,cap,status,it,ot,cost,price,duration,error in calls:db.execute('INSERT INTO model_calls(id,trace_id,owner_public_id,course_id,capability,prompt_version,provider,model,status,input_summary,input_tokens,output_tokens,token_source,retry_count,estimated_cost,pricing_version,cost_currency,cost_basis,duration_ms,output_hash,error_code,created_at,completed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)',(cid,trace,student,course,cap,'1','demo','edu-model',status,'{"content_included":false,"fields":["course_id"]}',it,ot,'estimated',0,cost,price,'CNY','estimate',duration,'',error))
                        db.execute("INSERT INTO generation_tasks(id,owner_public_id,course_id,trace_id,status,progress,capability,model,idempotency_key,estimated_cost,actual_cost,failure_code,failure_reason,created_at,updated_at) VALUES('task-stale',?,'gov-course','trace-task','running',.5,'quiz','edu-model','task-stale',0,0,'','',datetime('now','-20 minutes'),datetime('now','-20 minutes'))",(student,))
                        db.execute("INSERT INTO model_quota_buckets(id,scope_type,scope_key,utc_day,call_count,reserved_tokens,reserved_cost,updated_at) VALUES('quota-gov','course','gov-course',date('now'),2,190,.002,CURRENT_TIMESTAMP)")
                        db.commit()
                    denied=page.request.get(f'{BASE}/api/v1/model-operations-dashboard',headers={'Authorization':f"Bearer {tokens['gov_student']}"});teacher_data=page.request.get(f'{BASE}/api/v1/model-operations-dashboard',headers={'Authorization':f"Bearer {tokens['gov_teacher']}"})
                    assert denied.status==403 and teacher_data.ok and teacher_data.json()['summary']['calls']==2 and teacher_data.json()['scope']['course_ids']==['gov-course'];report['checks']['scope_and_role']={'student':403,'teacher_calls':2,'hidden_excluded':True}
                    page.goto(f'{BASE}/login');page.evaluate("([t,u])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role','teacher');localStorage.setItem('edumatrix_username',u);localStorage.setItem('edumatrix_student_id',u);localStorage.setItem('edumatrix_display_name','运营教师');localStorage.setItem('edumatrix_onboarded','true')}",[tokens['gov_teacher'],tokens['gov_teacher_name']]);page.goto(f'{BASE}/model-operations',wait_until='domcontentloaded');page.locator('.ops-page h2').get_by_text('Agent 与模型运营',exact=True).wait_for(timeout=20000);page.locator('.sla-grid article').first.locator('strong').get_by_text('50%',exact=True).wait_for();page.locator('.alerts').get_by_text('运营告警',exact=True).wait_for();page.locator('.calls-grid').get_by_text('trace-gov-ok',exact=True).wait_for();
                    with page.expect_download() as dl:page.get_by_role('button',name='导出 JSON').click()
                    assert dl.value.suggested_filename=='model-operations.json';report['checks']['authenticated_export']=True
                    page.screenshot(path=str(OUT/'01-desktop-operations-dashboard.png'),full_page=True);report['screenshots'].append('01-desktop-operations-dashboard.png');page.reload(wait_until='domcontentloaded');page.locator('.sla-grid article').first.locator('strong').get_by_text('50%',exact=True).wait_for();report['checks']['refresh_recovery']=True
                    page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(600)
                    sidebar=page.locator('.app-sidebar')
                    if 'app-sidebar--collapsed' not in (sidebar.get_attribute('class') or ''):page.get_by_role('button',name='收起导航').click();page.wait_for_timeout(500)
                    sidebar_right=sidebar.evaluate('(el)=>el.getBoundingClientRect().right');assert sidebar_right<=1;page.locator('.ops-page h2').get_by_text('Agent 与模型运营',exact=True).wait_for();width=page.evaluate('document.documentElement.scrollWidth');assert width<=390;page.screenshot(path=str(OUT/'02-mobile-operations-dashboard.png'),full_page=True);report['screenshots'].append('02-mobile-operations-dashboard.png');report['checks']['mobile']={'scroll_width':width,'navigation_collapsed':True,'sidebar_right':sidebar_right}
                    report['result']='passed'
                finally:context.close();browser.close()
    except Exception as exc:report['result']='failed';report['error']=f'{type(exc).__name__}: {exc}';raise
    finally:
        report['finished_at']=time.strftime('%Y-%m-%dT%H:%M:%S%z');stop(backend)
        if DB.exists():
            with sqlite3.connect(DB) as src,sqlite3.connect(EVIDENCE) as dst:src.backup(dst);report['checks']['sqlite_integrity']=dst.execute('PRAGMA integrity_check').fetchone()[0]
        (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        files=[{'file':p.name,'bytes':p.stat().st_size,'sha256':digest(p)} for p in sorted(OUT.iterdir()) if p.is_file() and p.name!='manifest.json' and not p.name.endswith(('-wal','-shm'))]
        (OUT/'manifest.json').write_text(json.dumps({'schema_version':'next.nc-gov-04-manifest.v1','files':files},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
