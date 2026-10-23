"""Verify the versioned web PPT workspace and real exports in system Chrome."""
from __future__ import annotations
import hashlib,json,os,socket,sqlite3,subprocess,sys,time,zipfile
from pathlib import Path
from typing import Any
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]; OUTPUT=ROOT/'outputs'/'FC_比赛功能完全体'/'evidence'/'FC1-008'/'browser-e2e'; DB=ROOT/'outputs'/'_fc1_web_deck_e2e.db'; PORT=8818; URL=f'http://127.0.0.1:{PORT}'; PASSWORD='FC1-web-deck-2026!'
def wait_port(state,timeout=60):
 d=time.monotonic()+timeout
 while time.monotonic()<d:
  with socket.socket() as s: available=s.connect_ex(('127.0.0.1',PORT))==0
  if available is state:return
  time.sleep(.2)
 raise RuntimeError('port timeout')
def stop(p):
 if p and p.poll() is None: subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True,text=True,timeout=15);p.wait(timeout=10);wait_port(False,15)
def main():
 OUTPUT.mkdir(parents=True,exist_ok=True)
 for p in OUTPUT.iterdir():
  if p.is_file():p.unlink()
 for suffix in ('','-wal','-shm'):
  p=Path(str(DB)+suffix)
  if p.exists():p.unlink()
 env=os.environ.copy();env.update({'EDUMATRIX_DB_PATH':str(DB),'EDUMATRIX_AUTH_SECRET_KEY':'fc1-web-deck-e2e','EDUMATRIX_LLM_PROVIDER':'deterministic','EDUMATRIX_LLM_API_KEY':'','EDUMATRIX_MULTIMODAL_LLM_API_KEY':'','EDUMATRIX_EMBEDDING_PROVIDER':'hash','EDUMATRIX_RELOAD':'0','EDUMATRIX_HOST':'127.0.0.1','EDUMATRIX_PORT':str(PORT),'PYTHON_DOTENV_DISABLED':'1'})
 report={'schema_version':'fc1-008.web-deck-browser-e2e.v1','checks':{},'screenshots':[]};backend=None
 try:
  with (OUTPUT/'backend.log').open('w',encoding='utf-8') as log:
   backend=subprocess.Popen([sys.executable,'run.py'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT);wait_port(True)
   with sync_playwright() as pw:
    browser=pw.chromium.launch(channel='chrome',headless=True);ctx=browser.new_context(viewport={'width':1440,'height':1000},locale='zh-CN',accept_downloads=True);page=ctx.new_page();stamp=str(int(time.time()))
    owner=page.request.post(URL+'/api/auth/register',data={'username':'deck_owner_'+stamp,'password':PASSWORD,'display_name':'课件用户'});other=page.request.post(URL+'/api/auth/register',data={'username':'deck_other_'+stamp,'password':PASSWORD,'display_name':'隔离用户'});assert owner.ok and other.ok
    token=owner.json()['access_token']; headers={'Authorization':'Bearer '+token}; other_headers={'Authorization':'Bearer '+other.json()['access_token']};username='deck_owner_'+stamp
    page.goto(URL+'/login');page.evaluate("([t,u])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role','student');localStorage.setItem('edumatrix_username',u);localStorage.setItem('edumatrix_student_id',u);localStorage.setItem('edumatrix_onboarded','true')}",[token,username]);page.goto(URL+'/web-decks',wait_until='domcontentloaded')
    root=page.get_by_test_id('web-deck-workspace');root.wait_for(timeout=30000);root.get_by_role('button',name='创建',exact=True).click();root.get_by_text('首个不可变课件版本已创建。',exact=True).wait_for(timeout=30000);page.get_by_test_id('deck-stage').wait_for(timeout=30000)
    deck=page.request.get(URL+'/api/v1/web-decks',headers=headers).json()['items'][0];did=deck['id'];detail=page.request.get(URL+f'/api/v1/web-decks/{did}',headers=headers).json();assert len(detail['current_version']['slides'])==2
    page.locator('.thumbs button').nth(1).click();page.get_by_label('上移').click();page.get_by_role('textbox',name='标题',exact=True).fill('收敛边界与学习率');root.get_by_role('button',name='保存版本').click();root.get_by_text('新版本已保存。',exact=True).wait_for();detail=page.request.get(URL+f'/api/v1/web-decks/{did}',headers=headers).json();assert detail['current_version']['version_number']==2 and detail['current_version']['slides'][0]['title']=='收敛边界与学习率'
    root.get_by_role('button',name='下一页').click();root.get_by_test_id('deck-stage').get_by_text('2 / 2',exact=True).wait_for(timeout=10000);assert page.request.get(URL+f'/api/v1/web-decks/{did}',headers=headers).json()['current_slide']==1
    page.reload(wait_until='domcontentloaded');root=page.get_by_test_id('web-deck-workspace');root.get_by_test_id('deck-stage').wait_for(timeout=30000);assert '2 / 2' in root.get_by_test_id('deck-stage').inner_text();report['checks']['refresh_slide']=1
    versions=root.get_by_test_id('deck-version');assert versions.count()==2;versions.filter(has_text='v1').click();root.get_by_text('已恢复 v1',exact=True).wait_for();assert page.request.get(URL+f'/api/v1/web-decks/{did}',headers=headers).json()['current_version']['version_number']==1;report['checks']['version_restore']=1
    files={}
    for fmt in ('html','pptx','pdf'):
     r=page.request.get(URL+f'/api/v1/web-decks/{did}/export/{fmt}',headers=headers);assert r.ok,(fmt,r.status,r.text());p=OUTPUT/f'export.{fmt}';p.write_bytes(r.body());files[fmt]=p.stat().st_size
    assert (OUTPUT/'export.html').read_text(encoding='utf-8').count('class="slide"')==2
    with zipfile.ZipFile(OUTPUT/'export.pptx') as z: assert 'ppt/notesSlides/notesSlide1.xml' in z.namelist()
    assert (OUTPUT/'export.pdf').read_bytes().startswith(b'%PDF');report['checks']['exports']=files
    assert page.request.get(URL+f'/api/v1/web-decks/{did}',headers=other_headers).status==403 and page.request.get(URL+f'/api/v1/web-decks/{did}/export/pptx',headers=other_headers).status==403;report['checks']['owner_boundary']=[403,403]
    page.screenshot(path=str(OUTPUT/'01-desktop-web-deck.png'),full_page=True);report['screenshots'].append('01-desktop-web-deck.png');page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(300);width=page.evaluate('document.documentElement.scrollWidth');assert width<=390;report['checks']['mobile_width']=width;page.screenshot(path=str(OUTPUT/'02-mobile-web-deck.png'),full_page=True);report['screenshots'].append('02-mobile-web-deck.png');report['result']='passed';ctx.close();browser.close()
 finally:
  stop(backend)
  if DB.exists():
   with sqlite3.connect(DB) as src,sqlite3.connect(OUTPUT/'web_deck_evidence.db') as out:src.backup(out);report['checks']['sqlite']=out.execute('pragma integrity_check').fetchone()[0];report['checks']['rows']={'decks':out.execute('select count(*) from web_decks').fetchone()[0],'versions':out.execute('select count(*) from web_deck_versions').fetchone()[0],'slides':out.execute('select count(*) from web_slides').fetchone()[0]}
  (OUTPUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');files=[{'file':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(OUTPUT.iterdir()) if p.is_file() and p.name!='manifest.json' and not p.name.endswith(('-wal','-shm'))];(OUTPUT/'manifest.json').write_text(json.dumps({'schema_version':'fc1-008.web-deck-manifest.v1','files':files},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())
