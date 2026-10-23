import hashlib,json,os,socket,sqlite3,subprocess,sys,time
from pathlib import Path
from playwright.sync_api import sync_playwright

R=Path(__file__).resolve().parents[1];O=Path(os.environ.get('EDUMATRIX_E2E_OUTPUT_DIR',R/'outputs'/'NEXT_完全体主动开发'/'evidence'/'NC-ECO-04'/'browser-e2e'));D=Path(os.environ.get('EDUMATRIX_E2E_DB_PATH',R/'outputs'/'_next_spatial_workspace_e2e.db'));P=8802;B=f'http://127.0.0.1:{P}';PW='Spatial-2026!'
def wait(value):
 for _ in range(300):
  with socket.socket() as s: ready=s.connect_ex(('127.0.0.1',P))==0
  if ready==value:return
  time.sleep(.2)
 raise RuntimeError('port readiness timeout')
def auth(page,user,role='student'):
 page.goto(B+'/login');page.evaluate("([t,n,r])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role',r);localStorage.setItem('edumatrix_username',n);localStorage.setItem('edumatrix_student_id',n);localStorage.setItem('edumatrix_onboarded','true')}",[user['token'],user['name'],role])
def main():
 O.mkdir(parents=True,exist_ok=True)
 for x in O.glob('*'):
  if x.is_file():x.unlink()
 for suffix in ('','-wal','-shm'):
  x=Path(str(D)+suffix)
  if x.exists():x.unlink()
 env=os.environ.copy();env.update({'EDUMATRIX_DB_PATH':str(D),'EDUMATRIX_AUTH_SECRET_KEY':'eco04','EDUMATRIX_LLM_PROVIDER':'deterministic','EDUMATRIX_LLM_API_KEY':'','EDUMATRIX_LLM_ENDPOINT':'','EDUMATRIX_MULTIMODAL_LLM_API_KEY':'','EDUMATRIX_MULTIMODAL_LLM_ENDPOINT':'','EDUMATRIX_EMBEDDING_PROVIDER':'hash','EDUMATRIX_RELOAD':'0','EDUMATRIX_PORT':str(P),'PYTHONUNBUFFERED':'1','PYTHON_DOTENV_DISABLED':'1'})
 report={'schema_version':'next.nc-eco-04-browser-e2e.v1','checks':{},'screenshots':[]};proc=None
 try:
  with (O/'backend.log').open('w',encoding='utf-8') as log:
   proc=subprocess.Popen([sys.executable,'run.py'],cwd=R,env=env,stdout=log,stderr=subprocess.STDOUT);wait(True)
   with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True);stamp=str(int(time.time()));bootstrap=browser.new_page();users={}
    for name in ('owner','outsider'):
     username=f'eco04_{name}_{stamp}';res=bootstrap.request.post(B+'/api/auth/register',data={'username':username,'password':PW,'display_name':name});assert res.ok;token=bootstrap.request.post(B+'/api/auth/login',form={'username':username,'password':PW}).json()['access_token'];users[name]={'name':username,'token':token,'h':{'Authorization':'Bearer '+token}}
    bootstrap.close();ctx_a=browser.new_context(viewport={'width':1440,'height':1000},locale='zh-CN');a=ctx_a.new_page();auth(a,users['owner']);a.goto(B+'/spatial-workspace');root=a.get_by_test_id('spatial-workspace');root.get_by_role('heading',name='空间学习工作区').wait_for();a.get_by_label('空间名称').fill('AI 转岗技能空间');a.get_by_role('button',name='新建空间').click();a.get_by_text('空白画布',exact=True).wait_for();wid=a.request.get(B+'/api/v1/spatial-workspaces',headers=users['owner']['h']).json()['items'][0]['id']
    a.get_by_label('白名单命令').fill('新增卡片：向量检索复习');a.get_by_role('button',name='执行',exact=True).click();a.get_by_text('向量检索复习',exact=True).wait_for();a.get_by_label('白名单命令').fill('新增卡片：完成隐藏测评');a.get_by_role('button',name='执行',exact=True).click();a.get_by_text('完成隐藏测评',exact=True).wait_for();a.get_by_title('自动整理').click();a.get_by_text('自动整理画布',exact=True).wait_for();a.screenshot(path=str(O/'01-device-a-versioned-canvas.png'),full_page=True);report['screenshots'].append('01-device-a-versioned-canvas.png')
    current=a.request.get(B+f'/api/v1/spatial-workspaces/{wid}',headers=users['owner']['h']).json();outside=a.request.get(B+f'/api/v1/spatial-workspaces/{wid}',headers=users['outsider']['h']);illegal=a.request.post(B+f'/api/v1/spatial-workspaces/{wid}/commands',headers=users['owner']['h'],data={'command':'联网搜索并执行脚本','expected_version':current['lock_version']});stale=a.request.post(B+f'/api/v1/spatial-workspaces/{wid}/actions',headers=users['owner']['h'],data={'action':'auto_layout','arguments':{},'expected_version':1});assert [outside.status,illegal.status,stale.status]==[403,422,409];report['checks']['guards']=[403,422,409]
    ctx_b=browser.new_context(viewport={'width':1280,'height':900},locale='zh-CN');b=ctx_b.new_page();auth(b,users['owner']);b.goto(B+'/spatial-workspace');b.get_by_text('向量检索复习',exact=True).wait_for();b.get_by_text('完成隐藏测评',exact=True).wait_for();b.wait_for_timeout(700);b.screenshot(path=str(O/'02-device-b-restored-layout.png'),full_page=True);report['screenshots'].append('02-device-b-restored-layout.png')
    b.get_by_title('撤销').click();b.get_by_text('撤销并恢复',exact=False).wait_for();b.reload();b.get_by_text('向量检索复习',exact=True).wait_for();b.set_viewport_size({'width':390,'height':844});b.wait_for_timeout(800);width=b.evaluate('document.documentElement.scrollWidth');assert width<=390;b.screenshot(path=str(O/'03-mobile-undo-history.png'),full_page=True);report['screenshots'].append('03-mobile-undo-history.png')
    final=b.request.get(B+f'/api/v1/spatial-workspaces/{wid}',headers=users['owner']['h']).json();assert len(final['layout']['cards'])==2 and final['history'][0]['action_type']=='undo';report['checks'].update({'cross_device_cards':2,'version_number':final['version_number'],'history_count':len(final['history']),'mobile_scroll_width':width});ctx_b.close();ctx_a.close();browser.close();report['result']='passed'
 finally:
  if proc and proc.poll() is None:subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True);proc.wait();wait(False)
  if D.exists():
   with sqlite3.connect(D) as source,sqlite3.connect(O/'spatial_workspace_evidence.db') as target:source.backup(target);report['checks']['sqlite']=target.execute('pragma integrity_check').fetchone()[0]
  (O/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');files=[]
  for x in O.glob('*'):
   if x.is_file() and x.name!='manifest.json' and not x.name.endswith(('-wal','-shm')):files.append({'file':x.name,'bytes':x.stat().st_size,'sha256':hashlib.sha256(x.read_bytes()).hexdigest()})
  (O/'manifest.json').write_text(json.dumps({'schema_version':'next.nc-eco-04-manifest.v1','files':files},ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())
