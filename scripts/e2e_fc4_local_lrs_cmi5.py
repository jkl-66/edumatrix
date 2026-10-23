"""Verify FC4 local LRS persistence, dead-letter recovery and cmi5 subset."""
from __future__ import annotations
import hashlib,json,os,socket,sqlite3,subprocess,sys,time
from pathlib import Path
from playwright.sync_api import Page,sync_playwright

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
OUTPUT=Path(os.environ.get('EDUMATRIX_E2E_OUTPUT_DIR',ROOT/'outputs'/'FC_比赛功能完全体'/'evidence'/'FC4-04A'/'browser-e2e'))
DB_PATH=Path(os.environ.get('EDUMATRIX_E2E_DB_PATH',ROOT/'outputs'/'_fc4_local_lrs_runtime.db'))
EVIDENCE_DB=OUTPUT/'fc4_local_lrs_evidence.db';PORT=int(os.environ.get('EDUMATRIX_E2E_PORT','8834'));BASE=f'http://127.0.0.1:{PORT}'
USERNAME='fc4_lrs_admin';PASSWORD='FC4-local-lrs-e2e-2026!'
def wait_port(open_,timeout=45):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        with socket.socket() as s:s.settimeout(.25);available=s.connect_ex(('127.0.0.1',PORT))==0
        if available is open_:return
        time.sleep(.2)
    raise RuntimeError(f'port {PORT} state timeout')
def stop(process):
    if not process or process.poll() is not None:return
    subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,text=True,timeout=15)
    try:process.wait(timeout=5)
    except subprocess.TimeoutExpired:pass
    wait_port(False,15)
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def shot(page:Page,name):
    path=OUTPUT/f'{name}.png';page.screenshot(path=str(path),full_page=True);return path.name
def manifest():
    files=[{'file':p.name,'bytes':p.stat().st_size,'sha256':digest(p)} for p in sorted(OUTPUT.iterdir()) if p.is_file() and p.name!='manifest.json' and not p.name.endswith(('-wal','-shm'))]
    (OUTPUT/'manifest.json').write_text(json.dumps({'schema_version':'fc4.local-lrs-cmi5-e2e-manifest.v1','files':files},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def login(page,username=USERNAME,password=PASSWORD):
    r=page.request.post(f'{BASE}/api/auth/login',form={'username':username,'password':password});assert r.ok,r.text();return r.json()
def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    for p in OUTPUT.iterdir():
        if p.is_file():p.unlink()
    for suffix in ('','-wal','-shm'):
        p=Path(f'{DB_PATH}{suffix}')
        if p.exists():p.unlink()
    env=os.environ.copy();env.update({'EDUMATRIX_DB_PATH':str(DB_PATH),'EDUMATRIX_AUTH_SECRET_KEY':'fc4-lrs-isolated-secret','EDUMATRIX_LLM_PROVIDER':'deterministic','EDUMATRIX_LLM_MODEL':'deterministic','EDUMATRIX_LLM_API_KEY':'','EDUMATRIX_LLM_ENDPOINT':'','EDUMATRIX_RELOAD':'0','EDUMATRIX_HOST':'127.0.0.1','EDUMATRIX_PORT':str(PORT),'PYTHONUNBUFFERED':'1'});os.environ.update(env)
    from app.auth import get_password_hash
    from app.database import DBUser,SessionLocal,init_db
    init_db()
    with SessionLocal() as db:db.add(DBUser(username=USERNAME,hashed_password=get_password_hash(PASSWORD),role='admin',display_name='FC4 LRS 管理员'));db.commit()
    report={'scope':'persistent local LRS, xAPI idempotency, five-attempt dead letter, explicit requeue, cmi5 launch-active-completed-exited subset, refresh and mobile','started_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'checks':{},'screenshots':[]};backend=None
    try:
        with (OUTPUT/'backend.log').open('w',encoding='utf-8') as log:
            backend=subprocess.Popen([sys.executable,'run.py'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT);wait_port(True)
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True);context=browser.new_context(viewport={'width':1440,'height':1000},locale='zh-CN');page=context.new_page()
                try:
                    admin=login(page);headers={'Authorization':f"Bearer {admin['access_token']}"};bootstrap=page.request.post(f'{BASE}/api/v1/m6/demo/bootstrap',headers=headers).json()
                    learner_id=bootstrap['learner_public_id'];org_id=bootstrap['organization_id']
                    from app.database import SessionLocal as RuntimeSession,DBLearningEvent
                    with RuntimeSession() as db:
                        event=DBLearningEvent(id='fc4-lrs-browser-event',owner_public_id=learner_id,course_id='course-rag-engineering-m0',event_type='quiz_answered',schema_version='v1',idempotency_key='fc4-lrs-browser-event',source='learner',trace_id='fc4-lrs-browser',object_type='assessment',object_id='quiz-browser',payload={'correct':True});db.add(event);db.commit()
                    page.goto(f'{BASE}/login',wait_until='networkidle');page.evaluate("""([t,u])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role','admin');localStorage.setItem('edumatrix_username',u);localStorage.setItem('edumatrix_display_name','FC4 LRS 管理员');localStorage.setItem('edumatrix_onboarded','true')}""",[admin['access_token'],USERNAME]);page.goto(f'{BASE}/integration-sandbox',wait_until='networkidle')
                    page.get_by_text('本地集成模拟 · 冻结合成组织数据',exact=True).wait_for(state='visible',timeout=20000);row=page.locator('.event-row').filter(has_text='fc4-lrs-browser-event');row.wait_for(state='visible');report['screenshots'].append(shot(page,'01-event-ready'))
                    row.get_by_role('button',name='映射并入队').click();page.get_by_text('等待发送',exact=True).wait_for(state='visible',timeout=20000);report['screenshots'].append(shot(page,'02-outbox-pending'))
                    workspace=page.request.get(f'{BASE}/api/v1/m7/integrations/workspace',headers=headers).json()['selected'];delivery=next(x for x in workspace['deliveries'] if x['source_object_id']=='fc4-lrs-browser-event')
                    for _ in range(5):
                        r=page.request.post(f"{BASE}/api/v1/m7/integrations/deliveries/{delivery['id']}/attempt",headers=headers,data={'outcome':'failure','error_code':'local_lrs_fault'});assert r.ok
                    page.reload(wait_until='networkidle');page.get_by_text('死信',exact=True).wait_for(state='visible',timeout=20000);report['screenshots'].append(shot(page,'03-dead-letter'))
                    page.get_by_role('button',name='显式重入队').click();page.get_by_text('等待发送',exact=True).wait_for(state='visible',timeout=20000);page.get_by_role('button',name='写入本地 LRS').click();page.get_by_text('已接收',exact=True).wait_for(state='visible',timeout=20000);report['screenshots'].append(shot(page,'04-local-lrs-accepted'))
                    accepted=page.request.post(f"{BASE}/api/v1/m7/integrations/deliveries/{delivery['id']}/local-lrs",headers=headers);assert accepted.ok and accepted.json()['created'] is False
                    cmi5_state=page.locator('.cmi5-facts').locator('div').filter(has_text='状态').locator('strong')
                    page.get_by_role('button',name='启动 cmi5 会话').click();cmi5_state.get_by_text('launched',exact=True).wait_for(state='visible',timeout=20000);page.get_by_role('button',name='进入学习会话').click();cmi5_state.get_by_text('active',exact=True).wait_for(state='visible',timeout=20000);page.get_by_role('button',name='标记完成').click();cmi5_state.get_by_text('completed',exact=True).wait_for(state='visible',timeout=20000);page.get_by_role('button',name='退出会话').click();cmi5_state.get_by_text('exited',exact=True).wait_for(state='visible',timeout=20000);report['screenshots'].append(shot(page,'05-cmi5-exited'))
                    page.reload(wait_until='networkidle');cmi5_state=page.locator('.cmi5-facts').locator('div').filter(has_text='状态').locator('strong');cmi5_state.get_by_text('exited',exact=True).wait_for(state='visible',timeout=20000);page.get_by_text('已接收',exact=True).wait_for(state='visible')
                    final=page.request.get(f'{BASE}/api/v1/m7/integrations/workspace',headers=headers).json();selected=final['selected'];cmi5=selected['cmi5_sessions'][0];assert cmi5['status']=='exited' and len(selected['cmi5_events'])==4;assert len([x for x in selected['deliveries'] if x['destination_key']=='competition-local-lrs'])==4;assert len(selected['lrs_statements'])==1;assert selected['transport']['full_cmi5_conformance_claimed'] is False
                    page.set_viewport_size({'width':390,'height':844});page.reload(wait_until='networkidle');cmi5_state=page.locator('.cmi5-facts').locator('div').filter(has_text='状态').locator('strong');cmi5_state.get_by_text('exited',exact=True).wait_for(state='visible',timeout=20000);doc=page.evaluate('document.documentElement.scrollWidth');assert doc<=390;report['screenshots'].append(shot(page,'06-mobile-refresh'))
                    report['checks']={'truthfulness':final['truthfulness'],'local_lrs_statements':len(selected['lrs_statements']),'delivery_attempt_count':next(x for x in selected['deliveries'] if x['id']==delivery['id'])['attempt_count'],'delivery_events':len([x for x in selected['delivery_events'] if x['delivery_id']==delivery['id']]),'dead_letter_requeued':True,'local_lrs_replay_idempotent':True,'cmi5_status':cmi5['status'],'cmi5_events':len(selected['cmi5_events']),'cmi5_deliveries':len([x for x in selected['deliveries'] if x['destination_key']=='competition-local-lrs']),'refresh_recovered':True,'mobile':{'width':390,'document_width':doc}};report['result']='passed'
                finally:context.close();browser.close()
    except Exception as exc:report['result']='failed';report['error']=f'{type(exc).__name__}: {exc}';raise
    finally:
        report['finished_at']=time.strftime('%Y-%m-%dT%H:%M:%S%z');stop(backend)
        if DB_PATH.exists():
            with sqlite3.connect(DB_PATH) as source,sqlite3.connect(EVIDENCE_DB) as target:
                source.backup(target);report.setdefault('checks',{})['sqlite_integrity']=target.execute('PRAGMA integrity_check').fetchone()[0];report['checks']['migration_051']=target.execute("SELECT COUNT(*) FROM schema_migrations WHERE version='20260805_051'").fetchone()[0]==1;report['checks']['lrs_rows']=target.execute('SELECT COUNT(*) FROM local_lrs_statements').fetchone()[0];report['checks']['cmi5_event_rows']=target.execute('SELECT COUNT(*) FROM cmi5_session_events').fetchone()[0]
        (OUTPUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');manifest()
    print(json.dumps(report,ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
