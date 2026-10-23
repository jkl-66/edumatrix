"""Verify FC4 local LMS course, assignment and candidate grade exchange."""
from __future__ import annotations
import hashlib,json,os,socket,sqlite3,subprocess,sys,time
from pathlib import Path
from playwright.sync_api import Page,sync_playwright

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
OUTPUT=Path(os.environ.get('EDUMATRIX_E2E_OUTPUT_DIR',ROOT/'outputs'/'FC_比赛功能完全体'/'evidence'/'FC4-03A'/'browser-e2e'))
DB_PATH=Path(os.environ.get('EDUMATRIX_E2E_DB_PATH',ROOT/'outputs'/'_fc4_local_lms_runtime.db'))
EVIDENCE_DB=OUTPUT/'fc4_local_lms_evidence.db';PORT=int(os.environ.get('EDUMATRIX_E2E_PORT','8833'));BASE=f'http://127.0.0.1:{PORT}'
USERNAME='fc4_lms_admin';PASSWORD='FC4-local-lms-e2e-2026!'

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
    (OUTPUT/'manifest.json').write_text(json.dumps({'schema_version':'fc4.local-lms-e2e-manifest.v1','files':files},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def login(page):
    r=page.request.post(f'{BASE}/api/auth/login',form={'username':USERNAME,'password':PASSWORD});assert r.ok,r.text();return r.json()
def auth_counts(page,headers,org_id):
    selected=page.request.get(f'{BASE}/api/v1/local-lms/workspace?organization_id={org_id}',headers=headers).json()['selected']
    return selected['assignments'][0]['authority_counts']

def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    for p in OUTPUT.iterdir():
        if p.is_file():p.unlink()
    for suffix in ('','-wal','-shm'):
        p=Path(f'{DB_PATH}{suffix}')
        if p.exists():p.unlink()
    env=os.environ.copy();env.update({'EDUMATRIX_DB_PATH':str(DB_PATH),'EDUMATRIX_AUTH_SECRET_KEY':'fc4-lms-isolated-secret','EDUMATRIX_LLM_PROVIDER':'deterministic','EDUMATRIX_LLM_MODEL':'deterministic','EDUMATRIX_LLM_API_KEY':'','EDUMATRIX_LLM_ENDPOINT':'','EDUMATRIX_RELOAD':'0','EDUMATRIX_HOST':'127.0.0.1','EDUMATRIX_PORT':str(PORT),'PYTHONUNBUFFERED':'1'});os.environ.update(env)
    from app.auth import get_password_hash
    from app.database import DBUser,SessionLocal,init_db
    init_db()
    with SessionLocal() as db:db.add(DBUser(username=USERNAME,hashed_password=get_password_hash(PASSWORD),role='admin',display_name='FC4 LMS 管理员'));db.commit()
    report={'scope':'local LMS course/cohort export, assignment exchange, candidate grade isolation, idempotency conflict, permissions, refresh and mobile','started_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'checks':{},'screenshots':[]};backend=None
    try:
        with (OUTPUT/'backend.log').open('w',encoding='utf-8') as log:
            backend=subprocess.Popen([sys.executable,'run.py'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT);wait_port(True)
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True);context=browser.new_context(viewport={'width':1440,'height':1000},locale='zh-CN');page=context.new_page()
                try:
                    admin=login(page);headers={'Authorization':f"Bearer {admin['access_token']}"}
                    page.goto(f'{BASE}/login',wait_until='networkidle');page.evaluate("""([t,u])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role','admin');localStorage.setItem('edumatrix_username',u);localStorage.setItem('edumatrix_display_name','FC4 LMS 管理员');localStorage.setItem('edumatrix_onboarded','true')}""",[admin['access_token'],USERNAME]);page.goto(f'{BASE}/local-lms',wait_until='networkidle')
                    page.get_by_text('冻结合成 LMS 交换数据 · 本地适配器',exact=True).wait_for(state='visible',timeout=20000);report['screenshots'].append(shot(page,'01-empty-boundary'))
                    page.get_by_role('button',name='初始化演示闭环').click();page.get_by_text('冻结合成培训数据和本地 LMS 连接已就绪',exact=True).wait_for(state='visible',timeout=30000)
                    ws=page.request.get(f'{BASE}/api/v1/local-lms/workspace',headers=headers).json();org_id=ws['selected']['organization']['id'];connection=ws['selected']['connections'][0];course=ws['selected']['courses'][0];cohort=ws['selected']['cohorts'][0];assignment=ws['selected']['assignments'][0]
                    before=auth_counts(page,headers,org_id);report['screenshots'].append(shot(page,'02-ready-workspace'))
                    page.get_by_role('button',name='导出冻结快照').click();page.get_by_text('课程快照已导出',exact=True).wait_for(state='visible',timeout=20000)
                    page.get_by_role('button',name='导出批次摘要').click();page.get_by_text('批次快照已导出',exact=True).wait_for(state='visible',timeout=20000)
                    page.get_by_role('button',name='同步分配').click();page.get_by_text('培训分配已幂等同步',exact=True).wait_for(state='visible',timeout=20000);report['screenshots'].append(shot(page,'03-outbound-exchange'))
                    export_replay=page.request.post(f'{BASE}/api/v1/local-lms/catalog-exports',headers=headers,data={'organization_id':org_id,'connection_id':connection['id'],'source_type':'course','source_object_id':course['id']});assert export_replay.ok and export_replay.json()['created'] is False
                    assign_replay=page.request.post(f'{BASE}/api/v1/local-lms/assignment-exchanges',headers=headers,data={'organization_id':org_id,'connection_id':connection['id'],'training_assignment_id':assignment['id']});assert assign_replay.ok and assign_replay.json()['changed'] is False
                    page.get_by_role('button',name='导入候选成绩').click();page.get_by_text('0.95 外部成绩已保存为候选证据，内部事实未改写',exact=True).wait_for(state='visible',timeout=20000);page.get_by_text('候选 · 非权威',exact=True).wait_for(state='visible');report['screenshots'].append(shot(page,'04-candidate-grade'))
                    after=auth_counts(page,headers,org_id);assert after==before
                    grade={'organization_id':org_id,'connection_id':connection['id'],'external_record_key':'competition-lms-grade-001','training_assignment_id':assignment['id'],'course_id':course['id'],'completion_status':'completed','score':0.95,'occurred_at':'2026-08-05T08:00:00'}
                    replay=page.request.post(f'{BASE}/api/v1/local-lms/grade-summaries',headers=headers,data=grade);assert replay.ok and replay.json()['created'] is False
                    grade['score']=0.61;conflict=page.request.post(f'{BASE}/api/v1/local-lms/grade-summaries',headers=headers,data=grade);assert conflict.status==409 and conflict.json()['detail']['code']=='lms_grade_idempotency_conflict'
                    page.reload(wait_until='networkidle');page.get_by_text('候选 · 非权威',exact=True).wait_for(state='visible',timeout=20000);assert auth_counts(page,headers,org_id)==before
                    cross=page.request.post(f'{BASE}/api/v1/local-lms/connections',headers=headers,data={'organization_id':'missing-organization'});assert cross.status==403
                    page.set_viewport_size({'width':390,'height':844});page.reload(wait_until='networkidle');page.get_by_text('候选 · 非权威',exact=True).wait_for(state='visible',timeout=20000);doc=page.evaluate('document.documentElement.scrollWidth');assert doc<=390;report['screenshots'].append(shot(page,'05-mobile-refresh'))
                    final=page.request.get(f'{BASE}/api/v1/local-lms/workspace',headers=headers).json();selected=final['selected'];assert len(selected['exports'])==2 and len(selected['assignment_exchanges'])==1 and len(selected['grade_summaries'])==1;assert selected['grade_summaries'][0]['score']==0.95 and selected['grade_summaries'][0]['evidence_status']=='candidate';assert final['truthfulness']['real_lms_connected'] is False and final['truthfulness']['external_grades_are_authoritative'] is False
                    report['checks']={'truthfulness':final['truthfulness'],'course_exports':len(selected['exports']),'assignment_exchanges':len(selected['assignment_exchanges']),'candidate_grades':len(selected['grade_summaries']),'authority_counts_before':before,'authority_counts_after':after,'idempotent_export':True,'idempotent_assignment':True,'idempotent_grade':True,'conflict_code':'lms_grade_idempotency_conflict','cross_organization_status':cross.status,'refresh_recovered':True,'mobile':{'width':390,'document_width':doc}};report['result']='passed'
                finally:context.close();browser.close()
    except Exception as exc:report['result']='failed';report['error']=f'{type(exc).__name__}: {exc}';raise
    finally:
        report['finished_at']=time.strftime('%Y-%m-%dT%H:%M:%S%z');stop(backend)
        if DB_PATH.exists():
            with sqlite3.connect(DB_PATH) as source,sqlite3.connect(EVIDENCE_DB) as target:
                source.backup(target);report.setdefault('checks',{})['sqlite_integrity']=target.execute('PRAGMA integrity_check').fetchone()[0];report['checks']['migration_050']=target.execute("SELECT COUNT(*) FROM schema_migrations WHERE version='20260805_050'").fetchone()[0]==1;report['checks']['grade_rows']=target.execute('SELECT COUNT(*) FROM lms_grade_summaries').fetchone()[0];report['checks']['authoritative_grade_writes']=target.execute("SELECT COUNT(*) FROM lms_grade_summaries WHERE evidence_status!='candidate'").fetchone()[0]
        (OUTPUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');manifest()
    print(json.dumps(report,ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
