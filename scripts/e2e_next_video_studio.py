from __future__ import annotations

import hashlib, json, os, socket, sqlite3, subprocess, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs'/'NEXT_完全体主动开发'/'evidence'/'NC-MEDIA-03'/'browser-e2e'
DB=ROOT/'outputs'/'_next_video_studio_e2e.db'; PORT=8805; BASE=f'http://127.0.0.1:{PORT}'; PASSWORD='Video-studio-2026!'

def wait_port(open_,timeout=70):
 end=time.monotonic()+timeout
 while time.monotonic()<end:
  with socket.socket() as s: available=s.connect_ex(('127.0.0.1',PORT))==0
  if available is open_: return
  time.sleep(.2)
 raise RuntimeError('port_timeout')

def auth(page,user,role='student'):
 page.goto(BASE+'/login');page.evaluate("""([t,n,r])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role',r);localStorage.setItem('edumatrix_username',n);localStorage.setItem('edumatrix_student_id',n);localStorage.setItem('edumatrix_onboarded','true')}""",[user['token'],user['name'],role])

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 for p in OUT.glob('*'):
  if p.is_file():p.unlink()
 for suffix in ('','-wal','-shm'):
  p=Path(str(DB)+suffix)
  if p.exists():p.unlink()
 env=os.environ.copy();env.update({'EDUMATRIX_DB_PATH':str(DB),'EDUMATRIX_AUTH_SECRET_KEY':'video-e2e','EDUMATRIX_LLM_PROVIDER':'deterministic','EDUMATRIX_LLM_API_KEY':'','EDUMATRIX_LLM_ENDPOINT':'','EDUMATRIX_MULTIMODAL_LLM_API_KEY':'','EDUMATRIX_MULTIMODAL_LLM_ENDPOINT':'','EDUMATRIX_EMBEDDING_PROVIDER':'hash','EDUMATRIX_RELOAD':'0','EDUMATRIX_PORT':str(PORT),'PYTHONUNBUFFERED':'1','PYTHON_DOTENV_DISABLED':'1'})
 report={'schema_version':'next.nc-media-03-browser-e2e.v1','checks':{},'screenshots':[]};backend=None
 try:
  with (OUT/'backend.log').open('w',encoding='utf-8') as log:
   backend=subprocess.Popen([sys.executable,'run.py'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT);wait_port(True)
   with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True);ctx=browser.new_context(viewport={'width':1440,'height':1000},locale='zh-CN',accept_downloads=True);page=ctx.new_page();stamp=str(int(time.time()));users={}
    for key in ('owner','outsider'):
     name=f'video_{key}_{stamp}';res=page.request.post(BASE+'/api/auth/register',data={'username':name,'password':PASSWORD,'display_name':key});assert res.ok;users[key]={'name':name};users[key]['token']=page.request.post(BASE+'/api/auth/login',form={'username':name,'password':PASSWORD}).json()['access_token'];users[key]['h']={'Authorization':'Bearer '+users[key]['token']}
    auth(page,users['owner']);page.goto(BASE+'/video-studio',wait_until='networkidle');root=page.get_by_test_id('video-studio');root.get_by_role('heading',name='技能微课视频制作').wait_for();root.get_by_text('离线运行时就绪',exact=True).wait_for();assert root.get_by_test_id('video-scene').count()==2
    root.get_by_role('button',name='创建项目').click();root.get_by_text('不可变版本 1',exact=False).wait_for();project=page.request.get(BASE+'/api/v1/video-projects',headers=users['owner']['h']).json()['items'][0];pid=project['id'];assert page.request.get(BASE+f'/api/v1/video-projects/{pid}',headers=users['outsider']['h']).status==403
    root.get_by_label('分镜1标题').fill('边缘智能与本地推理');root.get_by_role('button',name='保存新脚本版本').click();root.get_by_text('不可变版本 2',exact=False).wait_for()
    root.get_by_role('button',name='生成 MP4').click();video=root.get_by_test_id('rendered-video');video.wait_for(timeout=120000);page.wait_for_function("el => el.readyState >= 1 && el.duration > 0",arg=video.element_handle(),timeout=30000);duration=video.evaluate('el=>el.duration');assert duration>=8
    page.screenshot(path=str(OUT/'01-desktop-rendered-video-studio.png'),full_page=False);report['screenshots'].append('01-desktop-rendered-video-studio.png')
    detail=page.request.get(BASE+f'/api/v1/video-projects/{pid}',headers=users['owner']['h']).json();task=detail['tasks'][0];assert task['status']=='completed' and task['output']['quality_report']['passed'];output=task['output'];report['checks'].update({'script_version':detail['script']['version_number'],'duration_seconds':duration,'audio_status':task['audio_status'],'mp4_sha256':output['mp4_sha256']})
    assert page.request.get(BASE+f"/api/v1/video-projects/outputs/{output['id']}/files/course-video.mp4",headers=users['outsider']['h']).status==403
    downloaded=[]
    for label in ('MP4','SRT','VTT','讲稿'):
     with page.expect_download() as info: root.get_by_role('button',name=label,exact=True).click()
     download=info.value;path=OUT/f'download-{download.suggested_filename}';download.save_as(path);assert path.stat().st_size>10;downloaded.append(path.name)
    report['checks']['downloads']=downloaded
    page.reload(wait_until='networkidle');root=page.get_by_test_id('video-studio');root.get_by_text('不可变版本 2',exact=False).wait_for();root.get_by_test_id('rendered-video').wait_for();report['checks']['refresh_recovery']=True
    page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(700);width=page.evaluate('document.documentElement.scrollWidth');assert width<=390;page.screenshot(path=str(OUT/'02-mobile-video-studio.png'),full_page=True);report['screenshots'].append('02-mobile-video-studio.png');report['checks']['mobile_scroll_width']=width
    ctx.close();browser.close();report['result']='passed'
 finally:
  if backend and backend.poll() is None:
   subprocess.run(['taskkill','/PID',str(backend.pid),'/T','/F'],capture_output=True);backend.wait(timeout=10);wait_port(False,20)
  if DB.exists():
   with sqlite3.connect(DB) as src,sqlite3.connect(OUT/'video_studio_evidence.db') as dst:src.backup(dst);report['checks']['sqlite']=dst.execute('pragma integrity_check').fetchone()[0]
  (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');files=[]
  for p in sorted(OUT.glob('*')):
   if p.is_file() and p.name!='manifest.json' and not p.name.endswith(('-wal','-shm')):files.append({'file':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
  (OUT/'manifest.json').write_text(json.dumps({'schema_version':'next.nc-media-03-manifest.v1','files':files},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False));return 0

if __name__=='__main__':raise SystemExit(main())
