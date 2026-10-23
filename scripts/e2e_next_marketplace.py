import os,sys,time,socket,sqlite3,subprocess,json,hashlib
from pathlib import Path
from playwright.sync_api import sync_playwright
R=Path(__file__).resolve().parents[1];O=Path(os.environ.get('EDUMATRIX_E2E_OUTPUT_DIR',R/'outputs'/'NEXT_完全体主动开发'/'evidence'/'NC-ECO-02'/'browser-e2e'));D=Path(os.environ.get('EDUMATRIX_E2E_DB_PATH',R/'outputs'/'_next_marketplace_e2e.db'));P=8800;B=f'http://127.0.0.1:{P}';PW='Marketplace-2026!'
def wait(x):
 for _ in range(300):
  with socket.socket() as s:a=s.connect_ex(('127.0.0.1',P))==0
  if a==x:return
  time.sleep(.2)
 raise RuntimeError('port timeout')
def state(q,t,n,r):
 q.goto(B+'/login');q.evaluate("([t,n,r])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role',r);localStorage.setItem('edumatrix_username',n);localStorage.setItem('edumatrix_student_id',n);localStorage.setItem('edumatrix_onboarded','true')}",[t,n,r])
def main():
 O.mkdir(parents=True,exist_ok=True)
 for x in O.glob('*'):
  if x.is_file():x.unlink()
 for s in ('','-wal','-shm'):
  x=Path(str(D)+s)
  if x.exists():x.unlink()
 e=os.environ.copy();e.update({'EDUMATRIX_DB_PATH':str(D),'EDUMATRIX_AUTH_SECRET_KEY':'eco02','EDUMATRIX_LLM_PROVIDER':'deterministic','EDUMATRIX_LLM_API_KEY':'','EDUMATRIX_LLM_ENDPOINT':'','EDUMATRIX_MULTIMODAL_LLM_API_KEY':'','EDUMATRIX_MULTIMODAL_LLM_ENDPOINT':'','EDUMATRIX_EMBEDDING_PROVIDER':'hash','EDUMATRIX_RELOAD':'0','EDUMATRIX_PORT':str(P),'PYTHONUNBUFFERED':'1','PYTHON_DOTENV_DISABLED':'1'});rep={'schema_version':'next.nc-eco-02-browser-e2e.v1','checks':{},'screenshots':[]};p=None
 try:
  with (O/'backend.log').open('w',encoding='utf-8') as log:
   p=subprocess.Popen([sys.executable,'run.py'],cwd=R,env=e,stdout=log,stderr=subprocess.STDOUT);wait(1)
   with sync_playwright() as w:
    b=w.chromium.launch(headless=True);c=b.new_context(viewport={'width':1440,'height':1000},locale='zh-CN');q=c.new_page();stamp=str(int(time.time()));users={}
    for k in ('teacher','admin','learner'):
     n=f'eco02_{k}_{stamp}';z=q.request.post(B+'/api/auth/register',data={'username':n,'password':PW,'display_name':k});assert z.ok;users[k]={'name':n,'id':z.json()['user_id']}
    cid=f'eco02-course-{stamp}'
    with sqlite3.connect(D) as d:
     d.execute("update users set role='teacher' where public_id=?",(users['teacher']['id'],));d.execute("update users set role='admin' where public_id=?",(users['admin']['id'],))
     d.execute("insert into courses(id,version,title,subject,description,content_origin,license_text,visibility,status,owner_public_id,manifest_version,manifest_data,created_at) values(?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",(cid,'1.0','AI 可信训练','人工智能','公开课程说明','https://example.invalid/ml','CC BY 4.0','private','published',users['teacher']['id'],'eco02-v1','{"commit":"abc"}'))
     d.execute("insert into course_memberships(id,course_id,user_public_id,role,status,created_at,updated_at) values(?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",(f'cm-{stamp}',cid,users['teacher']['id'],'teacher','active'))
     d.execute("insert into course_documents(id,course_id,chapter_order,filename,file_type,file_size,title,content,tags,chunk_count,content_hash,source_path,license_text,status,created_at,updated_at) values(?,?,1,'chapter.md','md',10,'第一章','可信训练正文','[]',1,'h1','repo/chapter.md','CC BY 4.0','published',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",(f'doc-{stamp}',cid))
     d.execute("insert into source_documents(id,course_id,title,filename,file_format,content_hash,source_sha256,processed_sha256,file_size,source_url,source_path,license_text,uploader_public_id,parser_version,parser_metadata,parse_warnings,processing_error_code,processing_status,created_at,updated_at) values(?,?,'第一章','chapter.md','md','h1','s1','p1',10,'https://example.invalid/chapter','repo/chapter.md','CC BY 4.0',?,'e2e-v1','{}','[]','','ready',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",(f'src-{stamp}',cid,users['teacher']['id']));d.commit()
    for k,v in users.items():
     z=q.request.post(B+'/api/auth/login',form={'username':v['name'],'password':PW});assert z.ok;v['token']=z.json()['access_token'];v['h']={'Authorization':'Bearer '+v['token']}
    state(q,users['teacher']['token'],users['teacher']['name'],'teacher');q.goto(B+'/marketplace');q.locator('.market-page h2').wait_for(timeout=30000);q.get_by_label('入市课程').select_option(cid);q.get_by_label('市场标题').fill('AI 可信训练公开版');q.get_by_role('button',name='提交审核').click();q.get_by_text('已提交管理员审核',exact=True).wait_for();pending=q.request.get(B+'/api/v1/marketplace/workspace',headers=users['teacher']['h']).json()['managed'][0]
    denied=q.request.post(B+f"/api/v1/marketplace/listings/{pending['id']}/decisions",headers=users['teacher']['h'],data={'action':'approve','reason':'教师不能自行审核公开条目','expected_version':pending['lock_version']});assert denied.status==403;rep['checks']['teacher_self_review_forbidden']=403
    state(q,users['admin']['token'],users['admin']['name'],'admin');q.goto(B+'/marketplace');q.locator('.market-page h2').wait_for();q.get_by_text('pending · 举报 0',exact=True).wait_for();q.get_by_role('button',name='批准',exact=True).click();q.get_by_text('approved · 举报 0',exact=True).wait_for();q.get_by_role('button',name='发布',exact=True).click();q.get_by_text('published · 举报 0',exact=True).wait_for();q.wait_for_timeout(700);q.screenshot(path=str(O/'01-admin-published-market-listing.png'),full_page=True);rep['screenshots'].append('01-admin-published-market-listing.png')
    state(q,users['learner']['token'],users['learner']['name'],'student');q.goto(B+'/marketplace');q.locator('.market-page h2').wait_for();assert q.get_by_role('button',name='提交审核').count()==0;card=q.get_by_test_id('market-card').filter(has_text='AI 可信训练公开版');card.wait_for();assert 'CC BY 4.0' in card.inner_text();q.get_by_label('市场搜索').fill('可信');q.get_by_role('button',name='筛选').click();card.wait_for();card.get_by_title('获取课程副本').click();q.get_by_text('课程副本已创建：',exact=False).wait_for();acquired=q.request.post(B+'/api/v1/marketplace/listings',headers=users['learner']['h'],data={'course_id':cid,'title':'越权循环发布','summary':'学习者不得提交市场条目','category':'人工智能','tags':['AI']});assert acquired.status==403;rep['checks']['learner_submission_forbidden']=403;card.get_by_title('举报该条目').click();q.get_by_text('举报证据已冻结并进入人工队列',exact=True).wait_for();q.wait_for_timeout(700);q.screenshot(path=str(O/'02-learner-acquired-and-reported.png'),full_page=True);rep['screenshots'].append('02-learner-acquired-and-reported.png')
    admin_ws=q.request.get(B+'/api/v1/marketplace/workspace',headers=users['admin']['h']).json();listing=admin_ws['managed'][0];report=listing['reports'][0];bad=q.request.post(B+f"/api/v1/marketplace/reports/{report['id']}/decisions",headers=users['teacher']['h'],data={'action':'withdraw','reason':'教师不能处置公共举报案件','expected_version':1});assert bad.status==403;rep['checks']['teacher_moderation_forbidden']=403
    state(q,users['admin']['token'],users['admin']['name'],'admin');q.goto(B+'/marketplace');q.locator('.market-page h2').wait_for();q.get_by_text('published · 举报 1',exact=True).click();q.get_by_role('button',name='核实并下架').click();q.get_by_text('withdrawn · 举报 0',exact=True).wait_for();q.reload();q.get_by_text('withdrawn · 举报 0',exact=True).wait_for(timeout=30000);q.set_viewport_size({'width':390,'height':844});q.wait_for_timeout(800);width=q.evaluate('document.documentElement.scrollWidth');assert width<=390;q.screenshot(path=str(O/'03-mobile-withdrawn-history.png'),full_page=True);rep['screenshots'].append('03-mobile-withdrawn-history.png')
    with sqlite3.connect(D) as d:
     acq=d.execute('select derived_course_id,source_status from marketplace_acquisitions').fetchone();status=d.execute('select status from courses where id=?',(acq[0],)).fetchone()[0];docs=d.execute('select count(*) from course_documents where course_id=?',(acq[0],)).fetchone()[0];decs=d.execute('select count(*) from marketplace_decisions').fetchone()[0]
    assert (acq[1],status,docs)==('withdrawn','published',1);rep['checks'].update({'published_search_license':'CC BY 4.0','decision_count':decs,'withdrawal_history':{'acquisition_source_status':acq[1],'derived_course_status':status,'document_count':docs},'mobile_scroll_width':width});c.close();b.close();rep['result']='passed'
 finally:
  if p and p.poll() is None:subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True);p.wait();wait(0)
  if D.exists():
   with sqlite3.connect(D) as a,sqlite3.connect(O/'marketplace_evidence.db') as z:a.backup(z);rep['checks']['sqlite']=z.execute('pragma integrity_check').fetchone()[0]
  (O/'report.json').write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8');fs=[]
  for x in O.glob('*'):
   if x.is_file() and x.name!='manifest.json' and not x.name.endswith(('-wal','-shm')):fs.append({'file':x.name,'bytes':x.stat().st_size,'sha256':hashlib.sha256(x.read_bytes()).hexdigest()})
  (O/'manifest.json').write_text(json.dumps({'schema_version':'next.nc-eco-02-manifest.v1','files':fs},ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(rep,ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())
