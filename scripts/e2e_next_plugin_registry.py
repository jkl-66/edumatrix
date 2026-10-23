import hashlib,json,os,socket,sqlite3,subprocess,sys,time
from pathlib import Path
from playwright.sync_api import sync_playwright
R=Path(__file__).resolve().parents[1];O=Path(os.environ.get('EDUMATRIX_E2E_OUTPUT_DIR',R/'outputs'/'NEXT_完全体主动开发'/'evidence'/'NC-ECO-05'/'browser-e2e'));D=Path(os.environ.get('EDUMATRIX_E2E_DB_PATH',R/'outputs'/'_next_plugin_registry_e2e.db'));P=8803;B=f'http://127.0.0.1:{P}';PW='Plugin-2026!'
def wait(v):
 for _ in range(300):
  with socket.socket() as s:r=s.connect_ex(('127.0.0.1',P))==0
  if r==v:return
  time.sleep(.2)
 raise RuntimeError('port')
def auth(q,u,r):q.goto(B+'/login');q.evaluate("([t,n,r])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role',r);localStorage.setItem('edumatrix_username',n);localStorage.setItem('edumatrix_student_id',n);localStorage.setItem('edumatrix_onboarded','true')}",[u['token'],u['name'],r])
def main():
 O.mkdir(parents=True,exist_ok=True)
 for x in O.glob('*'):
  if x.is_file():x.unlink()
 for s in ('','-wal','-shm'):
  x=Path(str(D)+s)
  if x.exists():x.unlink()
 e=os.environ.copy();e.update({'EDUMATRIX_DB_PATH':str(D),'EDUMATRIX_AUTH_SECRET_KEY':'eco05','EDUMATRIX_LLM_PROVIDER':'deterministic','EDUMATRIX_LLM_API_KEY':'','EDUMATRIX_LLM_ENDPOINT':'','EDUMATRIX_MULTIMODAL_LLM_API_KEY':'','EDUMATRIX_MULTIMODAL_LLM_ENDPOINT':'','EDUMATRIX_EMBEDDING_PROVIDER':'hash','EDUMATRIX_RELOAD':'0','EDUMATRIX_PORT':str(P),'PYTHONUNBUFFERED':'1','PYTHON_DOTENV_DISABLED':'1'});rep={'schema_version':'next.nc-eco-05-browser-e2e.v1','checks':{},'screenshots':[]};p=None
 try:
  with (O/'backend.log').open('w',encoding='utf-8') as log:
   p=subprocess.Popen([sys.executable,'run.py'],cwd=R,env=e,stdout=log,stderr=subprocess.STDOUT);wait(1)
   with sync_playwright() as w:
    br=w.chromium.launch(headless=True);c=br.new_context(viewport={'width':1360,'height':950},locale='zh-CN');q=c.new_page();stamp=str(int(time.time()));users={}
    for k in ('admin','student'):
     n=f'eco05_{k}_{stamp}';z=q.request.post(B+'/api/auth/register',data={'username':n,'password':PW,'display_name':k});assert z.ok;users[k]={'name':n,'id':z.json()['user_id']}
    with sqlite3.connect(D) as d:d.execute("update users set role='admin' where public_id=?",(users['admin']['id'],));d.commit()
    for k,u in users.items():u['token']=q.request.post(B+'/api/auth/login',form={'username':u['name'],'password':PW}).json()['access_token'];u['h']={'Authorization':'Bearer '+u['token']}
    auth(q,users['student'],'student');q.goto(B+'/plugins');q.get_by_test_id('plugin-registry').get_by_role('heading',name='领域插件注册中心').wait_for();q.get_by_text('普通用户可核对插件来源与能力边界',exact=False).wait_for();deny=q.request.post(B+'/api/v1/plugins/robotics-skill-demo/install',headers=users['student']['h']);assert deny.status==403;rep['checks']['student_install']=403
    auth(q,users['admin'],'admin');q.goto(B+'/plugins');q.get_by_role('button',name='验证并安装').wait_for();q.get_by_role('button',name='验证并安装').click();q.get_by_text('校验通过',exact=True).wait_for();q.get_by_text('2 个资产',exact=False).wait_for();q.wait_for_timeout(500);q.screenshot(path=str(O/'01-admin-installed-verified-plugin.png'),full_page=True);rep['screenshots'].append('01-admin-installed-verified-plugin.png')
    detail=q.request.get(B+'/api/v1/plugins/robotics-skill-demo',headers=users['admin']['h']).json();assert detail['status']=='installed' and len(detail['events'])==1;rep['checks']['package_hash']=detail['package_hash']
    q.get_by_role('button',name='禁用并保留历史').click();q.get_by_text('uninstall · success',exact=True).wait_for();q.reload();q.get_by_text('uninstall · success',exact=True).wait_for();q.set_viewport_size({'width':390,'height':844});q.wait_for_timeout(700);width=q.evaluate('document.documentElement.scrollWidth');assert width<=390;q.screenshot(path=str(O/'02-mobile-disabled-history.png'),full_page=True);rep['screenshots'].append('02-mobile-disabled-history.png')
    with sqlite3.connect(D) as d:state=d.execute("select r.status,p.status,(select count(*) from domain_versions),(select count(*) from plugin_lifecycle_events) from plugin_registrations r join domain_packs p on p.id=r.domain_pack_id where r.plugin_id='robotics-skill-demo'").fetchone()
    assert state==('disabled','inactive',1,2);rep['checks'].update({'disabled_history':list(state),'mobile_scroll_width':width});c.close();br.close();rep['result']='passed'
 finally:
  if p and p.poll() is None:subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True);p.wait();wait(0)
  if D.exists():
   with sqlite3.connect(D) as a,sqlite3.connect(O/'plugin_registry_evidence.db') as z:a.backup(z);rep['checks']['sqlite']=z.execute('pragma integrity_check').fetchone()[0]
  (O/'report.json').write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8');fs=[]
  for x in O.glob('*'):
   if x.is_file() and x.name!='manifest.json' and not x.name.endswith(('-wal','-shm')):fs.append({'file':x.name,'bytes':x.stat().st_size,'sha256':hashlib.sha256(x.read_bytes()).hexdigest()})
  (O/'manifest.json').write_text(json.dumps({'schema_version':'next.nc-eco-05-manifest.v1','files':fs},ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(rep,ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())
