"""Verify the FC4 seven-scenario integration fault drill and recovery UI."""
from __future__ import annotations
import hashlib,json,os,socket,sqlite3,subprocess,sys,time
from pathlib import Path
from playwright.sync_api import Page,sync_playwright

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
OUTPUT=Path(os.environ.get('EDUMATRIX_E2E_OUTPUT_DIR',ROOT/'outputs'/'FC_比赛功能完全体'/'evidence'/'FC4-07A'/'browser-e2e'))
DB_PATH=Path(os.environ.get('EDUMATRIX_E2E_DB_PATH',ROOT/'outputs'/'_fc4_fault_drill_runtime.db'))
EVIDENCE_DB=OUTPUT/'fc4_fault_drill_evidence.db';PORT=int(os.environ.get('EDUMATRIX_E2E_PORT','8837'));BASE=f'http://127.0.0.1:{PORT}'
USERNAME='fc4_fault_drill_admin';PASSWORD='FC4-fault-drill-e2e-2026!'
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
 (OUTPUT/'manifest.json').write_text(json.dumps({'schema_version':'fc4.integration-fault-drill-e2e-manifest.v1','files':files},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def main():
 OUTPUT.mkdir(parents=True,exist_ok=True)
 for p in OUTPUT.iterdir():
  if p.is_file():p.unlink()
 for suffix in ('','-wal','-shm'):
  p=Path(f'{DB_PATH}{suffix}')
  if p.exists():p.unlink()
 env=os.environ.copy();env.update({'EDUMATRIX_DB_PATH':str(DB_PATH),'EDUMATRIX_AUTH_SECRET_KEY':'fc4-fault-drill-isolated-secret','EDUMATRIX_LLM_PROVIDER':'deterministic','EDUMATRIX_LLM_MODEL':'deterministic','EDUMATRIX_LLM_API_KEY':'','EDUMATRIX_LLM_ENDPOINT':'','EDUMATRIX_RELOAD':'0','EDUMATRIX_HOST':'127.0.0.1','EDUMATRIX_PORT':str(PORT),'PYTHONUNBUFFERED':'1'});os.environ.update(env)
 from app.auth import get_password_hash
 from app.database import DBUser,SessionLocal,init_db
 init_db()
 with SessionLocal() as db:db.add(DBUser(username=USERNAME,hashed_password=get_password_hash(PASSWORD),role='admin',display_name='FC4 故障演练管理员'));db.commit()
 report={'scope':'seven serial integration faults, real persisted recovery states, authority preservation, refresh and mobile','started_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'checks':{},'screenshots':[]};backend=None
 try:
  with (OUTPUT/'backend.log').open('w',encoding='utf-8') as log:
   backend=subprocess.Popen([sys.executable,'run.py'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT);wait_port(True)
   with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True);context=browser.new_context(viewport={'width':1440,'height':1000},locale='zh-CN');page=context.new_page()
    try:
     login=page.request.post(f'{BASE}/api/auth/login',form={'username':USERNAME,'password':PASSWORD});assert login.ok,login.text();admin=login.json();headers={'Authorization':f"Bearer {admin['access_token']}"}
     bootstrap=page.request.post(f'{BASE}/api/v1/m6/demo/bootstrap',headers=headers);assert bootstrap.ok,bootstrap.text();org_id=bootstrap.json()['organization_id']
     page.goto(f'{BASE}/login',wait_until='networkidle');page.evaluate("""([t,u])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role','admin');localStorage.setItem('edumatrix_username',u);localStorage.setItem('edumatrix_display_name','FC4 故障演练管理员');localStorage.setItem('edumatrix_onboarded','true')}""",[admin['access_token'],USERNAME]);page.goto(f'{BASE}/integration-fault-drills',wait_until='networkidle')
     page.get_by_text('尚未建立故障演练',exact=True).wait_for(state='visible',timeout=20000);page.get_by_text('本地集成故障演练 · 冻结合成组织数据',exact=True).wait_for(state='visible');report['screenshots'].append(shot(page,'01-empty-local-boundary'))
     page.get_by_role('button',name='新建演练').click();page.get_by_text('内部权威数据未改变',exact=True).wait_for(state='visible',timeout=20000);assert page.locator('.scenario-grid article').count()==7;report['screenshots'].append(shot(page,'02-seven-scenario-plan'))
     labels=['重复投递','乱序事件','撤销后重放','载荷冲突','适配器断连','接收端超时','连续失败与死信']
     for index,label in enumerate(labels,1):
      page.get_by_role('button',name='执行下一场景').click();page.get_by_text(f'{label} 已执行并完成恢复校验',exact=True).wait_for(state='visible',timeout=20000);page.locator('.steps>article').nth(index-1).wait_for(state='visible')
      if index==4:report['screenshots'].append(shot(page,'03-four-rejection-scenarios'))
     page.locator('.authority').get_by_text('passed',exact=True).wait_for(state='visible',timeout=20000);assert page.locator('.steps>article').count()==7;report['screenshots'].append(shot(page,'04-seven-scenarios-passed'))
     api=page.request.get(f'{BASE}/api/v1/integration-fault-drills/workspace?organization_id={org_id}',headers=headers);assert api.ok,api.text();final=api.json()['selected']['runs'][0];assert final['status']=='passed' and len(final['steps'])==7;assert final['authority_before_hash']==final['authority_after_hash'];assert all(x['authority_hash']==final['authority_before_hash'] and x['outcome']=='passed' for x in final['steps'])
     dead=final['steps'][-1];assert dead['after_snapshot']['status']=='dead_letter' and dead['after_snapshot']['attempt_count']==5;assert dead['recovery_snapshot']['status']=='delivered' and dead['recovery_snapshot']['attempt_count']==6
     page.reload(wait_until='networkidle');page.locator('.authority').get_by_text('passed',exact=True).wait_for(state='visible',timeout=20000);assert page.locator('.steps>article').count()==7
     page.set_viewport_size({'width':390,'height':844});page.reload(wait_until='networkidle');page.get_by_text('内部权威数据未改变',exact=True).wait_for(state='visible',timeout=20000);doc=page.evaluate('document.documentElement.scrollWidth');assert doc<=390;report['screenshots'].append(shot(page,'05-mobile-refresh-recovery'))
     report['checks']={'organization_id':org_id,'scenario_keys':[x['scenario_key'] for x in final['steps']],'step_count':len(final['steps']),'status':final['status'],'authority_preserved':final['authority_before_hash']==final['authority_after_hash'],'all_steps_passed':all(x['outcome']=='passed' for x in final['steps']),'dead_letter_attempts':dead['after_snapshot']['attempt_count'],'dead_letter_recovery_status':dead['recovery_snapshot']['status'],'recovery_attempts':dead['recovery_snapshot']['attempt_count'],'refresh_recovered':True,'mobile':{'width':390,'document_width':doc}};report['result']='passed'
    finally:context.close();browser.close()
 except Exception as exc:report['result']='failed';report['error']=f'{type(exc).__name__}: {exc}';raise
 finally:
  report['finished_at']=time.strftime('%Y-%m-%dT%H:%M:%S%z');stop(backend)
  if DB_PATH.exists():
   with sqlite3.connect(DB_PATH) as source,sqlite3.connect(EVIDENCE_DB) as target:
    source.backup(target);checks=report.setdefault('checks',{});checks['sqlite_integrity']=target.execute('PRAGMA integrity_check').fetchone()[0];checks['migration_054']=target.execute("SELECT COUNT(*) FROM schema_migrations WHERE version='20260805_054'").fetchone()[0]==1;checks['drills']=target.execute('SELECT COUNT(*) FROM integration_fault_drills').fetchone()[0];checks['steps']=target.execute('SELECT COUNT(*) FROM integration_fault_drill_steps').fetchone()[0];checks['delivery_events']=target.execute('SELECT COUNT(*) FROM integration_delivery_events').fetchone()[0]
  (OUTPUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');manifest()
 print(json.dumps(report,ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
