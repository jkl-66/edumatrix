from __future__ import annotations
import hashlib,json,os,socket,sqlite3,subprocess,sys,time
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];OUT=Path(os.environ.get('EDUMATRIX_E2E_OUTPUT_DIR',ROOT/'outputs'/'NEXT_完全体主动开发'/'evidence'/'NC-GOV-05'/'browser-e2e'));DB=Path(os.environ.get('EDUMATRIX_E2E_DB_PATH',ROOT/'outputs'/'_next_gov_cert_e2e.db'));EVIDENCE=OUT/'certification_lifecycle_evidence.db';PORT=8795;BASE=f'http://127.0.0.1:{PORT}';PW='Next-gov-cert-2026!'
def wait(open_,timeout=45):
 end=time.monotonic()+timeout
 while time.monotonic()<end:
  with socket.socket() as s:available=s.connect_ex(('127.0.0.1',PORT))==0
  if available is open_:return
  time.sleep(.2)
 raise RuntimeError('port timeout')
def stop(p):
 if p and p.poll() is None:subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True,timeout=15);p.wait(timeout=5);wait(False,15)
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def session(page,token,username,role,name):page.goto(f'{BASE}/login');page.evaluate("([t,u,r,n])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role',r);localStorage.setItem('edumatrix_username',u);localStorage.setItem('edumatrix_student_id',u);localStorage.setItem('edumatrix_display_name',n);localStorage.setItem('edumatrix_onboarded','true')}",[token,username,role,name])
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 for p in OUT.iterdir():
  if p.is_file():p.unlink()
 for suffix in ('','-wal','-shm'):
  p=Path(str(DB)+suffix)
  if p.exists():p.unlink()
 env=os.environ.copy();env.update({'EDUMATRIX_DB_PATH':str(DB),'EDUMATRIX_AUTH_SECRET_KEY':'nc-gov-05-e2e','EDUMATRIX_DEMO_MODE':'1','EDUMATRIX_LLM_PROVIDER':'deterministic','EDUMATRIX_LLM_MODEL':'deterministic','EDUMATRIX_LLM_API_KEY':'','EDUMATRIX_LLM_ENDPOINT':'','EDUMATRIX_RELOAD':'0','EDUMATRIX_HOST':'127.0.0.1','EDUMATRIX_PORT':str(PORT),'PYTHONUNBUFFERED':'1'});report={'schema_version':'next.nc-gov-05-browser-e2e.v1','checks':{},'screenshots':[]};backend=None
 try:
  with (OUT/'backend.log').open('w',encoding='utf-8') as log:
   backend=subprocess.Popen([sys.executable,'run.py'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT);wait(True)
   with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True);context=browser.new_context(viewport={'width':1440,'height':1000},locale='zh-CN');page=context.new_page()
    try:
     stamp=str(int(time.time()));users={}
     for key in ('manager','learner','outsider'):
      username=f'cert_{key}_{stamp}';r=page.request.post(f'{BASE}/api/auth/register',data={'username':username,'password':PW,'display_name':key});assert r.ok;users[key]={'username':username,'token':r.json()['access_token']}
     with sqlite3.connect(DB) as db:
      db.execute("UPDATE users SET role='teacher' WHERE username=?",(users['manager']['username'],));ids={u:p for u,p in db.execute('SELECT username,public_id FROM users')};manager,learner,outsider=(ids[users[k]['username']] for k in ('manager','learner','outsider'));users['manager']['id']=manager;users['learner']['id']=learner
      db.execute("INSERT INTO organizations(id,name,organization_type,status,sharing_policy,created_at) VALUES('cert-org','认证演示组织','enterprise','active','{}',CURRENT_TIMESTAMP)")
      db.executemany("INSERT INTO organization_memberships(id,organization_id,user_public_id,role,status,created_at) VALUES(?, 'cert-org', ?, ?, 'active', CURRENT_TIMESTAMP)",[('om-m',manager,'admin'),('om-l',learner,'learner')])
      db.execute("INSERT INTO job_families(id,organization_id,code,title,created_at) VALUES('cert-family','cert-org','RAG','RAG工程',CURRENT_TIMESTAMP)");db.execute("INSERT INTO job_levels(id,job_family_id,level_code,version,title,responsibilities,status,created_at) VALUES('cert-level','cert-family','L2','demo-1','RAG应用工程师','[]','active',CURRENT_TIMESTAMP)")
      for cid,expiry in [('cert-expired','-1 day'),('cert-active','+40 day')]:db.execute("INSERT INTO certifications(id,organization_id,learner_public_id,job_level_id,standard_snapshot,evidence_ids,issuer_public_id,status,issued_at,expires_at,retraining_rule,lock_version) VALUES(?,?,?,?,?,?,?,?,datetime('now','-300 day'),datetime('now',?),?,1)",(cid,'cert-org',learner,'cert-level','{"version":"demo-1"}','["demo-evidence"]',manager,'active',expiry,'{"completion_days":14}'))
      db.commit()
     denied=page.request.get(f'{BASE}/api/v1/certification-lifecycle/workspace?organization_id=cert-org',headers={'Authorization':f"Bearer {users['outsider']['token']}"});assert denied.status==403;report['checks']['outsider_forbidden']=403
     session(page,users['manager']['token'],users['manager']['username'],'teacher','认证管理员');page.goto(f'{BASE}/certification-lifecycle',wait_until='domcontentloaded');page.locator('.cert-page h2').wait_for(timeout=20000);page.get_by_role('button',name='运行到期扫描').click();page.get_by_text('expired · 版本 2',exact=False).wait_for();page.locator('.cert').filter(has_text='cert-active').get_by_role('button',name='撤销').click();page.get_by_text('revoked · 版本 2',exact=False).wait_for();page.get_by_text('2',exact=True).nth(1).wait_for();report['checks']['manager_flow']={'expired':1,'revoked':1,'tasks':2};page.screenshot(path=str(OUT/'01-manager-expiry-revocation.png'),full_page=True);report['screenshots'].append('01-manager-expiry-revocation.png')
     session(page,users['learner']['token'],users['learner']['username'],'student','复训学员');page.goto(f'{BASE}/certification-lifecycle',wait_until='domcontentloaded');page.get_by_text('当前角色 learner',exact=False).wait_for(timeout=20000);assert page.locator('.cert').count()==2 and page.locator('.notice').count()==2;page.locator('.notice.unread').first.click();page.get_by_text('已读',exact=True).wait_for();report['checks']['learner_scope']={'certificates':2,'tasks':2,'notifications':2,'read':True};page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(600);width=page.evaluate('document.documentElement.scrollWidth');assert width<=390;page.screenshot(path=str(OUT/'02-learner-mobile-inbox.png'),full_page=True);report['screenshots'].append('02-learner-mobile-inbox.png');report['checks']['mobile']={'scroll_width':width};report['result']='passed'
    finally:context.close();browser.close()
 except Exception as e:report['result']='failed';report['error']=f'{type(e).__name__}: {e}';raise
 finally:
  stop(backend)
  if DB.exists():
   with sqlite3.connect(DB) as src,sqlite3.connect(EVIDENCE) as dst:src.backup(dst);report['checks']['sqlite_integrity']=dst.execute('PRAGMA integrity_check').fetchone()[0]
  (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');files=[{'file':p.name,'bytes':p.stat().st_size,'sha256':digest(p)} for p in sorted(OUT.iterdir()) if p.is_file() and p.name!='manifest.json' and not p.name.endswith(('-wal','-shm'))];(OUT/'manifest.json').write_text(json.dumps({'schema_version':'next.nc-gov-05-manifest.v1','files':files},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
