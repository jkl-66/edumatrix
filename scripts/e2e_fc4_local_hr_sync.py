"""Verify FC4 synthetic HR preview, apply, change and offboarding in Chromium."""
from __future__ import annotations
import hashlib,json,os,socket,sqlite3,subprocess,sys,time
from pathlib import Path
from playwright.sync_api import Page,sync_playwright

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
OUTPUT=Path(os.environ.get('EDUMATRIX_E2E_OUTPUT_DIR',ROOT/'outputs'/'FC_比赛功能完全体'/'evidence'/'FC4-02A'/'browser-e2e'))
DB_PATH=Path(os.environ.get('EDUMATRIX_E2E_DB_PATH',ROOT/'outputs'/'_fc4_local_hr_runtime.db'))
EVIDENCE_DB=OUTPUT/'fc4_local_hr_evidence.db';PORT=int(os.environ.get('EDUMATRIX_E2E_PORT','8832'));BASE=f'http://127.0.0.1:{PORT}'
USERNAME='fc4_hr_admin';PASSWORD='FC4-local-hr-e2e-2026!'

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
    (OUTPUT/'manifest.json').write_text(json.dumps({'schema_version':'fc4.local-hr-e2e-manifest.v1','files':files},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def login(page):
    r=page.request.post(f'{BASE}/api/auth/login',form={'username':USERNAME,'password':PASSWORD});assert r.ok,r.text();return r.json()

def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    for p in OUTPUT.iterdir():
        if p.is_file():p.unlink()
    for suffix in ('','-wal','-shm'):
        p=Path(f'{DB_PATH}{suffix}')
        if p.exists():p.unlink()
    env=os.environ.copy();env.update({'EDUMATRIX_DB_PATH':str(DB_PATH),'EDUMATRIX_AUTH_SECRET_KEY':'fc4-hr-isolated-secret','EDUMATRIX_LLM_PROVIDER':'deterministic','EDUMATRIX_LLM_MODEL':'deterministic','EDUMATRIX_LLM_API_KEY':'','EDUMATRIX_LLM_ENDPOINT':'','EDUMATRIX_RELOAD':'0','EDUMATRIX_HOST':'127.0.0.1','EDUMATRIX_PORT':str(PORT),'PYTHONUNBUFFERED':'1'});os.environ.update(env)
    from app.auth import get_password_hash
    from app.database import DBUser,SessionLocal,init_db
    init_db()
    with SessionLocal() as db:db.add(DBUser(username=USERNAME,hashed_password=get_password_hash(PASSWORD),role='admin',display_name='FC4 HR 管理员'));db.commit()
    report={'scope':'frozen synthetic HR field mapping, preview-only diff, idempotent apply, update, offboarding, history retention, refresh and mobile','started_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'checks':{},'screenshots':[]};backend=None
    try:
        with (OUTPUT/'backend.log').open('w',encoding='utf-8') as log:
            backend=subprocess.Popen([sys.executable,'run.py'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT);wait_port(True)
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True);context=browser.new_context(viewport={'width':1440,'height':1000},locale='zh-CN');page=context.new_page()
                try:
                    admin=login(page);headers={'Authorization':f"Bearer {admin['access_token']}"};bootstrap=page.request.post(f'{BASE}/api/v1/m6/demo/bootstrap',headers=headers).json()
                    page.goto(f'{BASE}/login',wait_until='networkidle');page.evaluate("""([t,u])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role','admin');localStorage.setItem('edumatrix_username',u);localStorage.setItem('edumatrix_display_name','FC4 HR 管理员');localStorage.setItem('edumatrix_onboarded','true')}""",[admin['access_token'],USERNAME]);page.goto(f'{BASE}/local-hr',wait_until='networkidle')
                    page.get_by_text('冻结合成 HR 主数据 · 本地入站模拟',exact=True).wait_for(state='visible',timeout=20000);page.get_by_role('button',name='创建字段映射').click();page.get_by_text('字段映射 v1 已冻结',exact=True).wait_for(state='visible',timeout=20000);report['screenshots'].append(shot(page,'01-field-mapping'))
                    page.get_by_role('button',name='预览初始批次').click();page.get_by_text('尚未写入员工主数据',exact=False).wait_for(state='visible',timeout=20000);page.get_by_role('button',name='确认应用该预览').wait_for(state='visible');before=page.request.get(f'{BASE}/api/v1/local-hr/workspace',headers=headers).json();assert before['selected']['employees']==[];assert before['selected']['batches'][0]['preview']['counts']['create']==2;report['screenshots'].append(shot(page,'02-preview-before-write'))
                    page.get_by_role('button',name='确认应用该预览').click();page.get_by_text('预览批次已应用，员工投影与审计已更新',exact=True).wait_for(state='visible',timeout=20000);page.get_by_text('合成员工 林淼',exact=True).wait_for(state='visible');report['screenshots'].append(shot(page,'03-initial-applied'))
                    first=page.request.get(f'{BASE}/api/v1/local-hr/workspace',headers=headers).json()['selected']['batches'][0];replay=page.request.post(f"{BASE}/api/v1/local-hr/batches/{first['id']}/apply",headers=headers,data={'organization_id':bootstrap['organization_id'],'expected_lock_version':1});assert replay.ok and replay.json()['applied'] is False
                    page.get_by_role('button',name='预览变更批次').click();page.get_by_role('button',name='确认应用该预览').wait_for(state='visible',timeout=20000);change_preview=page.request.get(f'{BASE}/api/v1/local-hr/workspace',headers=headers).json()['selected']['batches'][0]['preview'];assert change_preview['counts']['offboard']==1;report['screenshots'].append(shot(page,'04-change-preview'));page.get_by_role('button',name='确认应用该预览').click();page.get_by_text('已离职 · 访问移除',exact=True).wait_for(state='visible',timeout=20000);page.reload(wait_until='networkidle');page.get_by_text('已离职 · 访问移除',exact=True).wait_for(state='visible');report['screenshots'].append(shot(page,'05-offboard-refresh'))
                    old=page.request.post(f'{BASE}/api/v1/local-hr/previews',headers=headers,data={'organization_id':bootstrap['organization_id'],'mapping_version_id':page.request.get(f'{BASE}/api/v1/local-hr/workspace',headers=headers).json()['selected']['mappings'][0]['id'],'source_snapshot_id':'stale-browser-snapshot','source_sequence':1,'records':page.request.get(f'{BASE}/api/v1/local-hr/frozen-snapshot?sequence=1',headers=headers).json()['records']});assert old.status==409 and old.json()['detail']['code']=='snapshot_out_of_order'
                    page.set_viewport_size({'width':390,'height':844});page.reload(wait_until='networkidle');page.get_by_text('已离职 · 访问移除',exact=True).wait_for(state='visible',timeout=20000);doc=page.evaluate('document.documentElement.scrollWidth');assert doc<=390;report['screenshots'].append(shot(page,'06-mobile-offboard'))
                    final=page.request.get(f'{BASE}/api/v1/local-hr/workspace',headers=headers).json();leave=next(e for e in final['selected']['employees'] if e['external_employee_id']=='SYN-1001');changed=next(e for e in final['selected']['employees'] if e['external_employee_id']=='SYN-1002');report['checks']={'truthfulness':final['truthfulness'],'preview_before_write':True,'idempotent_reapply':True,'stale_sequence_denied':'snapshot_out_of_order','employee_count':len(final['selected']['employees']),'leave_employee':leave,'changed_department':changed['department'],'refresh_recovered':True,'mobile':{'width':390,'document_width':doc}}
                    assert final['truthfulness']['real_hr_connected'] is False and final['truthfulness']['real_employee_data'] is False;assert leave['membership_status']=='removed' and changed['department']=='学习发展部';report['result']='passed'
                finally:context.close();browser.close()
    except Exception as exc:report['result']='failed';report['error']=f'{type(exc).__name__}: {exc}';raise
    finally:
        report['finished_at']=time.strftime('%Y-%m-%dT%H:%M:%S%z');stop(backend)
        if DB_PATH.exists():
            with sqlite3.connect(DB_PATH) as source,sqlite3.connect(EVIDENCE_DB) as target:
                source.backup(target);report.setdefault('checks',{})['sqlite_integrity']=target.execute('PRAGMA integrity_check').fetchone()[0];report['checks']['migration_049']=target.execute("SELECT COUNT(*) FROM schema_migrations WHERE version='20260805_049'").fetchone()[0]==1;report['checks']['users_preserved']=target.execute("SELECT COUNT(*) FROM users WHERE username='synthetic_hr_1001'").fetchone()[0]==1;report['checks']['sync_records']=target.execute('SELECT COUNT(*) FROM hr_sync_records').fetchone()[0]
        (OUTPUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');manifest()
    print(json.dumps(report,ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
