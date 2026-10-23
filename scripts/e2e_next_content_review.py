from __future__ import annotations
import hashlib,json,os,socket,sqlite3,subprocess,sys,time
from pathlib import Path
from typing import Any
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];OUT=Path(os.environ.get('EDUMATRIX_E2E_OUTPUT_DIR',ROOT/'outputs'/'NEXT_完全体主动开发'/'evidence'/'NC-GOV-03'/'browser-e2e'));DB=Path(os.environ.get('EDUMATRIX_E2E_DB_PATH',ROOT/'outputs'/'_next_content_review_e2e.db'));EVID=OUT/'content_review_evidence.db';PORT=8795;BASE=f'http://127.0.0.1:{PORT}';PW='Next-content-review-2026!'
def wait(open_:bool,t=60):
 d=time.monotonic()+t
 while time.monotonic()<d:
  with socket.socket() as s:s.settimeout(.2);ok=s.connect_ex(('127.0.0.1',PORT))==0
  if ok is open_:return
  time.sleep(.2)
 raise RuntimeError('port timeout')
def stop(p):
 if p and p.poll() is None:subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True);p.wait(timeout=8);wait(False,15)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 for p in OUT.iterdir():
  if p.is_file():p.unlink()
 for s in ('','-wal','-shm'):
  p=Path(f'{DB}{s}')
  if p.exists():p.unlink()
 env=os.environ.copy();env.update({'EDUMATRIX_DB_PATH':str(DB),'EDUMATRIX_AUTH_SECRET_KEY':'review-e2e','EDUMATRIX_LLM_PROVIDER':'deterministic','EDUMATRIX_LLM_API_KEY':'','EDUMATRIX_LLM_ENDPOINT':'','EDUMATRIX_EMBEDDING_PROVIDER':'hash','EDUMATRIX_RELOAD':'0','EDUMATRIX_HOST':'127.0.0.1','EDUMATRIX_PORT':str(PORT),'PYTHONUNBUFFERED':'1'})
 rep={'schema_version':'next.content-review-e2e.v1','checks':{},'screenshots':[]};proc=None
 try:
  with (OUT/'backend.log').open('w',encoding='utf-8') as log:
   proc=subprocess.Popen([sys.executable,'run.py'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT);wait(True)
   with sync_playwright() as pw:
    b=pw.chromium.launch(headless=True);ctx=b.new_context(viewport={'width':1440,'height':1000},locale='zh-CN');page=ctx.new_page()
    try:
     suf=str(int(time.time()));names=[f'review_teacher_{suf}',f'review_student_{suf}',f'review_outsider_{suf}'];ids={};tokens={}
     for n in names:
      r=page.request.post(f'{BASE}/api/auth/register',data={'username':n,'password':PW,'display_name':n});assert r.ok;ids[n]=r.json()['user_id']
     teacher,student,outsider=names;course=f'review-course-{suf}'
     with sqlite3.connect(DB) as d:
      d.execute("update users set role='teacher' where public_id in (?,?)",(ids[teacher],ids[outsider]));d.execute("insert into courses(id,version,title,visibility,status,owner_public_id,manifest_version,manifest_data,created_at) values(?,?,?,?,?,?,?,?,current_timestamp)",(course,'1','内容审核课程','private','published',ids[teacher],'1','{}'))
      for rid,uid,role in ((f'cm-t-{suf}',ids[teacher],'teacher'),(f'cm-s-{suf}',ids[student],'student')):d.execute("insert into course_memberships(id,course_id,user_public_id,role,status,created_at,updated_at) values(?,?,?,?,?,current_timestamp,current_timestamp)",(rid,course,uid,role,'active'))
      for i,title in enumerate(('可信 RAG 课程讲义','检索实验说明')):
       art=f'art-{i}-{suf}';ver=f'av-{i}-{suf}';content=f'{title}: 所有结论均附规范来源。';h=hashlib.sha256(content.encode()).hexdigest();d.execute("insert into artifacts(id,owner_public_id,course_id,artifact_type,title,status,current_version_id,lock_version,created_at,updated_at) values(?,?,?,?,?,?,?,?,current_timestamp,current_timestamp)",(art,ids[student],course,'lesson',title,'draft',ver,1));d.execute("insert into artifact_versions(id,artifact_id,version_number,content,content_format,content_hash,created_by_public_id,created_at) values(?,?,?,?,?,?,?,current_timestamp)",(ver,art,1,content,'markdown',h,ids[student]));d.execute("insert into quality_checks(id,artifact_version_id,trace_id,check_type,checker_version,status,score,details,source_ref_ids,created_at) values(?,?,?,?,?,?,?,?,?,current_timestamp)",(f'qc-{i}',ver,f'trace-{i}','citation','1','passed',.9,'{}','[]'));d.execute("insert into claim_checks(id,artifact_version_id,trace_id,atomic_claim,support_status,verdict,rationale,created_at) values(?,?,?,?,?,?,?,current_timestamp)",(f'claim-{i}',ver,f'trace-{i}','结论有证据','supported','supported','canonical evidence'))
      d.commit()
     for n in names:
      r=page.request.post(f'{BASE}/api/auth/login',form={'username':n,'password':PW});assert r.ok;tokens[n]=r.json()['access_token']
     hs={n:{'Authorization':f'Bearer {tokens[n]}'} for n in names}
     cases=[]
     for i in range(2):
      r=page.request.post(f'{BASE}/api/v1/content-review/cases',headers=hs[student],data={'artifact_id':f'art-{i}-{suf}','version_id':f'av-{i}-{suf}','submission_note':'提交规范证据供课程教师审核'});assert r.ok;cases.append(r.json())
     denied=page.request.post(f"{BASE}/api/v1/content-review/cases/{cases[0]['id']}/decisions",headers=hs[student],data={'action':'approve','reason':'学生不能自审内容','expected_version':cases[0]['lock_version']});assert denied.status==403
     page.goto(f'{BASE}/login',wait_until='domcontentloaded');page.evaluate("([t,n])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role','teacher');localStorage.setItem('edumatrix_username',n);localStorage.setItem('edumatrix_student_id',n);localStorage.setItem('edumatrix_onboarded','true')}",[tokens[teacher],teacher]);page.goto(f'{BASE}/content-review',wait_until='domcontentloaded');page.get_by_test_id('review-case').first.wait_for(timeout=30000)
     page.get_by_test_id('review-case').filter(has_text='检索实验说明').click();page.get_by_role('button',name='要求返工').click();page.get_by_test_id('review-detail').get_by_text('changes_requested',exact=True).wait_for(timeout=30000)
     page.get_by_test_id('review-case').filter(has_text='可信 RAG 课程讲义').click();page.get_by_role('button',name='批准内容',exact=True).click();page.get_by_test_id('review-detail').get_by_role('button',name='发布',exact=True).click();page.get_by_test_id('review-detail').get_by_text('published',exact=True).wait_for(timeout=30000)
     page.screenshot(path=str(OUT/'01-published-with-responsibility.png'),full_page=True);rep['screenshots'].append('01-published-with-responsibility.png')
     page.reload(wait_until='domcontentloaded');page.get_by_test_id('review-case').filter(has_text='可信 RAG 课程讲义').click();page.get_by_test_id('review-detail').get_by_role('button',name='下架',exact=True).click();page.get_by_test_id('review-detail').get_by_text('withdrawn',exact=True).wait_for(timeout=30000)
     outq=page.request.get(f'{BASE}/api/v1/content-review/queue',headers=hs[outsider]);assert outq.ok and outq.json()['items']==[]
     page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(300);geo=page.evaluate("()=>({viewport:innerWidth,documentWidth:document.documentElement.scrollWidth,panel:document.querySelector('[data-testid=content-review-page]').getBoundingClientRect().width})");assert geo['documentWidth']<=391;page.screenshot(path=str(OUT/'02-mobile-withdrawn-history.png'),full_page=True);rep['screenshots'].append('02-mobile-withdrawn-history.png')
     with sqlite3.connect(DB) as d:statuses=dict(d.execute('select status,count(*) from content_review_cases group by status').fetchall());decisions=d.execute('select count(*) from content_review_decisions').fetchone()[0]
     rep['checks']={'student_approve_status':403,'outsider_visible_cases':0,'statuses':statuses,'immutable_decision_count':decisions,'refresh_recovery':True,'mobile':geo};rep['result']='passed'
    finally:ctx.close();b.close()
 except Exception as e:rep['result']='failed';rep['error']=f'{type(e).__name__}: {e}';raise
 finally:
  stop(proc)
  if DB.exists():
   with sqlite3.connect(DB) as s,sqlite3.connect(EVID) as t:s.backup(t);rep['checks']['sqlite_integrity']=t.execute('pragma integrity_check').fetchone()[0]
  (OUT/'report.json').write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');files=[{'file':p.name,'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(OUT.iterdir()) if p.is_file() and p.name!='manifest.json' and not p.name.endswith(('-wal','-shm'))];(OUT/'manifest.json').write_text(json.dumps({'schema_version':'next.content-review-manifest.v1','files':files},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(rep,ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
