from __future__ import annotations
import hashlib,json,os,socket,sqlite3,subprocess,sys,time
from pathlib import Path
from playwright.sync_api import sync_playwright
R=Path(__file__).resolve().parents[1];O=R/'outputs'/'FC_比赛功能完全体'/'evidence'/'FC1-009'/'browser-e2e';D=R/'outputs'/'_fc1_local_adapter_e2e.db';PORT=8819;U=f'http://127.0.0.1:{PORT}'
def wait(s):
 for _ in range(300):
  with socket.socket() as x:a=x.connect_ex(('127.0.0.1',PORT))==0
  if a is s:return
  time.sleep(.2)
 raise RuntimeError('port')
def main():
 O.mkdir(parents=True,exist_ok=True)
 for p in O.iterdir():
  if p.is_file():p.unlink()
 for q in ('','-wal','-shm'):
  p=Path(str(D)+q)
  if p.exists():p.unlink()
 e=os.environ.copy();e.update({'EDUMATRIX_DB_PATH':str(D),'EDUMATRIX_AUTH_SECRET_KEY':'fc1-adapter','EDUMATRIX_LLM_API_KEY':'','EDUMATRIX_MULTIMODAL_LLM_API_KEY':'','EDUMATRIX_EMBEDDING_PROVIDER':'hash','EDUMATRIX_RELOAD':'0','EDUMATRIX_PORT':str(PORT),'PYTHON_DOTENV_DISABLED':'1'});rep={'checks':{},'screenshots':[]};b=None
 try:
  with(O/'backend.log').open('w',encoding='utf-8')as log:
   b=subprocess.Popen([sys.executable,'run.py'],cwd=R,env=e,stdout=log,stderr=subprocess.STDOUT);wait(True)
   with sync_playwright()as w:
    z=w.chromium.launch(channel='chrome',headless=True);c=z.new_context(viewport={'width':1440,'height':1000},locale='zh-CN');p=c.new_page();t=str(int(time.time()));o=p.request.post(U+'/api/auth/register',data={'username':'adapter_'+t,'password':'Adapter-2026!','display_name':'实验用户'});x=p.request.post(U+'/api/auth/register',data={'username':'other_'+t,'password':'Adapter-2026!','display_name':'隔离用户'});token=o.json()['access_token'];h={'Authorization':'Bearer '+token};oh={'Authorization':'Bearer '+x.json()['access_token']};p.goto(U+'/login');p.evaluate("([t,u])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role','student');localStorage.setItem('edumatrix_username',u);localStorage.setItem('edumatrix_onboarded','true')}",[token,'adapter_'+t]);p.goto(U+'/local-adapter-lab');root=p.get_by_test_id('local-adapter-workspace');root.wait_for(timeout=30000);root.get_by_role('button',name='创建本地会话').click();root.get_by_text('本地模拟会话已创建，尚未连接。',exact=True).wait_for();sid=p.request.get(U+'/api/v1/local-adapters',headers=h).json()['items'][0]['id']
    root.get_by_role('button',name='连接模拟器').click();root.get_by_text('connected',exact=True).first.wait_for();root.get_by_role('button',name='注入故障').click();root.get_by_role('button',name='运行',exact=True).click();root.get_by_text('failed',exact=True).first.wait_for();root.get_by_role('button',name='提交诊断').click();root.get_by_role('button',name='执行恢复').wait_for();root.get_by_role('button',name='执行恢复').click();root.get_by_role('button',name='恢复后重跑').click();root.get_by_role('button',name='隐藏验收').click();root.get_by_text('隐藏验收 4/4',exact=True).wait_for();state=p.request.get(U+f'/api/v1/local-adapters/{sid}',headers=h).json();flow=[event['action'] for event in reversed(state['events'])];assert state['status']=='passed' and flow==['connect','inject_fault','run','diagnose','recover','rerun','submit'];rep['checks']['flow']=flow
    p.reload();root=p.get_by_test_id('local-adapter-workspace');root.get_by_text('隐藏验收 4/4',exact=True).wait_for(timeout=30000);rep['checks']['refresh']='passed';assert p.request.get(U+f'/api/v1/local-adapters/{sid}',headers=oh).status==403;rep['checks']['owner']=403;p.screenshot(path=str(O/'01-desktop-local-adapter.png'),full_page=True);rep['screenshots'].append('01-desktop-local-adapter.png');p.set_viewport_size({'width':390,'height':844});p.wait_for_timeout(300);assert p.evaluate('document.documentElement.scrollWidth')<=390;p.screenshot(path=str(O/'02-mobile-local-adapter.png'),full_page=True);rep['screenshots'].append('02-mobile-local-adapter.png');rep['result']='passed';c.close();z.close()
 finally:
  if b and b.poll() is None:subprocess.run(['taskkill','/PID',str(b.pid),'/T','/F'],capture_output=True);b.wait();wait(False)
  if D.exists():
   with sqlite3.connect(D)as a,sqlite3.connect(O/'local_adapter_evidence.db')as q:a.backup(q);rep['checks']['sqlite']=q.execute('pragma integrity_check').fetchone()[0];rep['checks']['events']=q.execute('select count(*) from local_adapter_events').fetchone()[0]
  (O/'report.json').write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');fs=[{'file':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}for p in sorted(O.iterdir())if p.is_file()and p.name!='manifest.json'and not p.name.endswith(('-wal','-shm'))];(O/'manifest.json').write_text(json.dumps({'files':fs},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(rep,ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())
