from __future__ import annotations
import hashlib,json,os,socket,sqlite3,subprocess,sys,time
from pathlib import Path
from playwright.sync_api import sync_playwright
R=Path(__file__).resolve().parents[1];O=R/'outputs'/'FC_比赛功能完全体'/'evidence'/'FC2-001'/'browser-e2e';D=R/'outputs'/'_fc2_marketplace_comments_e2e.db';PORT=8821;U=f'http://127.0.0.1:{PORT}';PW='MarketComment-2026!'
def wait(state):
 for _ in range(300):
  with socket.socket()as s:ok=s.connect_ex(('127.0.0.1',PORT))==0
  if ok is state:return
  time.sleep(.2)
 raise RuntimeError('port')
def auth(page,name,role):
 r=page.request.post(U+'/api/auth/register',data={'username':name,'password':PW,'display_name':name});assert r.ok
 with sqlite3.connect(D)as db:db.execute('update users set role=? where username=?',(role,name));db.commit()
 z=page.request.post(U+'/api/auth/login',form={'username':name,'password':PW});return z.json()['access_token'],r.json()['user_id']
def state(page,token,name,role):
 page.goto(U+'/login');page.evaluate("([t,n,r])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role',r);localStorage.setItem('edumatrix_username',n);localStorage.setItem('edumatrix_onboarded','true')}",[token,name,role])
def main():
 O.mkdir(parents=True,exist_ok=True)
 for p in O.iterdir():
  if p.is_file():p.unlink()
 for s in ('','-wal','-shm'):
  p=Path(str(D)+s)
  if p.exists():p.unlink()
 env=os.environ.copy();env.update({'EDUMATRIX_DB_PATH':str(D),'EDUMATRIX_AUTH_SECRET_KEY':'fc2-comments','EDUMATRIX_LLM_API_KEY':'','EDUMATRIX_MULTIMODAL_LLM_API_KEY':'','EDUMATRIX_EMBEDDING_PROVIDER':'hash','EDUMATRIX_RELOAD':'0','EDUMATRIX_PORT':str(PORT),'PYTHON_DOTENV_DISABLED':'1'});rep={'checks':{},'screenshots':[]};proc=None
 try:
  with(O/'backend.log').open('w',encoding='utf-8')as log:
   proc=subprocess.Popen([sys.executable,'run.py'],cwd=R,env=env,stdout=log,stderr=subprocess.STDOUT);wait(True)
   with sync_playwright()as pw:
    browser=pw.chromium.launch(channel='chrome',headless=True);ctx=browser.new_context(viewport={'width':1440,'height':1000},locale='zh-CN');page=ctx.new_page();stamp=str(int(time.time()));teacher=f'fc2_teacher_{stamp}';learner=f'fc2_learner_{stamp}';reporter=f'fc2_reporter_{stamp}';tt,tid=auth(page,teacher,'teacher');lt,lid=auth(page,learner,'student');rt,rid=auth(page,reporter,'student');cid=f'fc2-comment-course-{stamp}'
    with sqlite3.connect(D)as db:
     db.execute("insert into courses(id,version,title,subject,description,content_origin,license_text,visibility,status,owner_public_id,manifest_version,manifest_data,created_at) values(?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",(cid,'1.0','AI 可信训练评论版','人工智能','版本评论演示','https://example.invalid','CC BY 4.0','private','published',tid,'fc2-v1','{}'));db.execute("insert into course_memberships(id,course_id,user_public_id,role,status,created_at,updated_at) values(?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",(f'cm-{stamp}',cid,tid,'teacher','active'));db.commit()
    th={'Authorization':'Bearer '+tt};lh={'Authorization':'Bearer '+lt};rh={'Authorization':'Bearer '+rt};listing=page.request.post(U+'/api/v1/marketplace/listings',headers=th,data={'course_id':cid,'title':'AI 可信训练公开评论版','summary':'用于验证版本绑定评论流程','category':'人工智能','tags':['AI','评论']}).json()
    with sqlite3.connect(D)as db:db.execute("update users set role='admin' where public_id=?",(tid,));db.commit()
    tt=page.request.post(U+'/api/auth/login',form={'username':teacher,'password':PW}).json()['access_token'];th={'Authorization':'Bearer '+tt};listing=page.request.post(U+f"/api/v1/marketplace/listings/{listing['id']}/decisions",headers=th,data={'action':'approve','reason':'冻结内容与许可证审核通过','expected_version':listing['lock_version']}).json();listing=page.request.post(U+f"/api/v1/marketplace/listings/{listing['id']}/decisions",headers=th,data={'action':'publish','reason':'批准发布并开放版本评论','expected_version':listing['lock_version']}).json()
    state(page,lt,learner,'student');page.goto(U+'/marketplace');root=page.get_by_test_id('marketplace-workspace');card=root.get_by_test_id('market-card').filter(has_text='AI 可信训练公开评论版');card.wait_for(timeout=30000);card.get_by_title('查看版本评论').click();comments=card.get_by_test_id('market-comments');comments.get_by_text('当前版本尚无评论',exact=True).wait_for();comments.get_by_label('评论内容').fill('课程结构清晰，来源说明完整。');comments.get_by_role('button',name='发布评论').click();comments.get_by_text('active',exact=False).first.wait_for();comments.get_by_text('绑定课程 v1.0',exact=False).first.wait_for();comments.get_by_role('button',name='编辑',exact=True).click();comments.get_by_label('编辑评论').fill('课程结构清晰，实验步骤和来源说明都很完整。');comments.get_by_role('button',name='保存编辑').click();comments.get_by_text('实验步骤和来源说明都很完整',exact=False).wait_for();comment=page.request.get(U+f"/api/v1/marketplace/listings/{listing['id']}/comments",headers=lh).json()['items'][0];assert comment['listing_snapshot_hash']==listing['snapshot_hash'] and len(comment['events'])==2;rep['checks']['binding']={'course_version':comment['course_version'],'snapshot_hash':comment['listing_snapshot_hash'],'events':2};page.screenshot(path=str(O/'01-learner-version-comment.png'),full_page=True);rep['screenshots'].append('01-learner-version-comment.png')
    state(page,rt,reporter,'student');page.goto(U+'/marketplace');card=page.get_by_test_id('market-card').filter(has_text='AI 可信训练公开评论版');card.get_by_title('查看版本评论').click();comments=card.get_by_test_id('market-comments');comments.get_by_role('button',name='举报评论').click();comments.get_by_text('举报 1',exact=False).wait_for();report=page.request.get(U+f"/api/v1/marketplace/listings/{listing['id']}/comments",headers=th).json()['items'][0]['reports'][0]
    denied=page.request.post(U+f"/api/v1/marketplace/comments/{comment['id']}/moderation",headers=rh,data={'action':'hide','reason':'越权管理评论','expected_version':comment['lock_version']});assert denied.status==403;rep['checks']['outsider_moderation']=403
    state(page,tt,teacher,'admin');page.goto(U+'/marketplace');card=page.get_by_test_id('market-card').filter(has_text='AI 可信训练公开评论版');card.get_by_title('查看版本评论').click();comments=card.get_by_test_id('market-comments');comments.get_by_role('button',name='核实并隐藏').click();comments.get_by_text('hidden',exact=False).first.wait_for();comments.get_by_role('button',name='恢复',exact=True).click();comments.get_by_text('active',exact=False).first.wait_for();page.reload();card=page.get_by_test_id('market-card').filter(has_text='AI 可信训练公开评论版');card.get_by_title('查看版本评论').click();comments=card.get_by_test_id('market-comments');comments.get_by_text('实验步骤和来源说明都很完整',exact=False).wait_for(timeout=30000);page.set_viewport_size({'width':390,'height':844});comments.scroll_into_view_if_needed();page.wait_for_timeout(500);width=page.evaluate('document.documentElement.scrollWidth');assert width<=390;page.screenshot(path=str(O/'02-mobile-comment-moderation.png'));rep['screenshots'].append('02-mobile-comment-moderation.png');rep['checks']['mobile_width']=width;rep['result']='passed';ctx.close();browser.close()
 finally:
  if proc and proc.poll()is None:subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True);proc.wait();wait(False)
  if D.exists():
   with sqlite3.connect(D)as src,sqlite3.connect(O/'marketplace_comment_evidence.db')as dst:src.backup(dst);rep['checks']['sqlite']=dst.execute('pragma integrity_check').fetchone()[0];rep['checks']['comments']=dst.execute('select count(*) from marketplace_comments').fetchone()[0];rep['checks']['events']=dst.execute('select count(*) from marketplace_comment_events').fetchone()[0];rep['checks']['reports']=dst.execute('select count(*) from marketplace_comment_reports').fetchone()[0]
  (O/'report.json').write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');files=[{'file':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}for p in sorted(O.iterdir())if p.is_file()and p.name!='manifest.json'and not p.name.endswith(('-wal','-shm'))];(O/'manifest.json').write_text(json.dumps({'files':files},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(rep,ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())
