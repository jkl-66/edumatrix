"""Verify the FC5 teacher judge journey against an isolated real server."""
from __future__ import annotations

import hashlib,json,os,socket,sqlite3,subprocess,sys,time
from datetime import datetime,timedelta
from pathlib import Path
from playwright.sync_api import Page,sync_playwright

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
OUTPUT=Path(os.environ.get('EDUMATRIX_E2E_OUTPUT_DIR',ROOT/'outputs'/'FC_比赛功能完全体'/'evidence'/'FC5-03A'/'browser-e2e'))
DB_PATH=Path(os.environ.get('EDUMATRIX_E2E_DB_PATH',ROOT/'outputs'/'_fc5_teacher_journey_runtime.db'))
EVIDENCE_DB=OUTPUT/'fc5_teacher_journey_evidence.db';PORT=int(os.environ.get('EDUMATRIX_E2E_PORT','8840'));BASE=f'http://127.0.0.1:{PORT}'
USERNAME='fc5_teacher_journey';PASSWORD='FC5-teacher-journey-e2e-2026!';COURSE_ID='fc5-teacher-journey-course'

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
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
def shot(page:Page,name):
 path=OUTPUT/f'{name}.png';page.screenshot(path=str(path),full_page=True);return path.name
def manifest():
 files=[{'file':p.name,'bytes':p.stat().st_size,'sha256':digest(p)} for p in sorted(OUTPUT.iterdir()) if p.is_file() and p.name!='manifest.json' and not p.name.endswith(('-wal','-shm'))]
 (OUTPUT/'manifest.json').write_text(json.dumps({'schema_version':'fc5.teacher-judge-journey-e2e-manifest.v1','files':files},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def seed_course():
 from app.database import DBCourse,SessionLocal,init_db
 init_db()
 with SessionLocal() as db:
  db.add(DBCourse(id=COURSE_ID,version='frozen-demo-v1',title='人工智能教师治理课程（冻结合成演示）',subject='人工智能',status='published',visibility='public',manifest_version='fc5-teacher-e2e-v1',manifest_data={'data_class':'synthetic_e2e_fixture'}));db.commit()
def promote_teacher(username):
 from app.database import DBCourse,DBCourseMembership,DBUser,SessionLocal
 with SessionLocal() as db:
  teacher=db.query(DBUser).filter_by(username=username).one();teacher.role='teacher'
  course=db.get(DBCourse,COURSE_ID);course.owner_public_id=teacher.public_id
  db.add(DBCourseMembership(course_id=COURSE_ID,user_public_id=teacher.public_id,role='teacher',status='active'));db.commit();return teacher.public_id
def seed_six_steps(teacher_id):
 from app.auth import get_password_hash
 from app.database import (DBArtifact,DBArtifactVersion,DBContentReviewCase,DBCourseMembership,DBLearningEvent,DBLearningPath,DBPlanDraft,DBPlanVersion,DBTeachingAnalyticsReport,DBTeachingClass,DBTeachingClassMember,DBTeachingGroup,DBTeachingTask,DBUser,SessionLocal)
 confirmation_at=datetime.utcnow().replace(microsecond=0)-timedelta(minutes=2)
 with SessionLocal() as db:
  learner=DBUser(public_id='fc5-teacher-synthetic-learner',username='fc5_teacher_synthetic_learner',display_name='冻结合成学员',hashed_password=get_password_hash('not-used'),role='student');db.add(learner);db.flush()
  db.add(DBCourseMembership(course_id=COURSE_ID,user_public_id=learner.public_id,role='student',status='active'));db.flush()
  classroom=DBTeachingClass(course_id=COURSE_ID,title='人工智能 1 班',term='冻结合成演示',owner_public_id=teacher_id);db.add(classroom);db.flush()
  group=DBTeachingGroup(class_id=classroom.id,name='技能提升组',description='冻结合成教学分组');db.add(group);db.flush()
  db.add(DBTeachingClassMember(class_id=classroom.id,user_public_id=learner.public_id,group_id=group.id,role='student',status='active'));db.flush()
  task=DBTeachingTask(class_id=classroom.id,group_id=group.id,title='完成矩阵分解证据精读',idempotency_key='fc5-teacher-e2e-task',status='published',created_by_public_id=teacher_id,published_at=confirmation_at-timedelta(hours=3));db.add(task)
  report=DBTeachingAnalyticsReport(class_id=classroom.id,course_id=COURSE_ID,period_start=confirmation_at-timedelta(days=7),period_end=confirmation_at-timedelta(days=1),metric_version='next.teaching-analytics.demo-v1',report_data={'truthfulness':{'data_kind':'competition_demo_metrics','real_enterprise_data':False}},content_hash='1'*64,created_by_public_id=teacher_id,created_at=confirmation_at-timedelta(hours=2));db.add(report);db.flush()
  plan=DBPlanDraft(owner_public_id=learner.public_id,course_id=COURSE_ID,title='教师干预：矩阵分解',status='confirmed',idempotency_key='fc5-teacher-e2e-intervention',confirmed_at=confirmation_at-timedelta(minutes=30));db.add(plan);db.flush()
  version=DBPlanVersion(plan_draft_id=plan.id,version_number=1,content={'data_class':'synthetic_e2e_fixture'},content_hash='2'*64,created_by_public_id=teacher_id);db.add(version);db.flush();plan.current_version_id=version.id;plan.confirmed_version_id=version.id
  path=DBLearningPath(owner_public_id=learner.public_id,course_id=COURSE_ID,source_plan_version_id=version.id,status='completed',completed_at=confirmation_at);db.add(path);db.flush()
  study=DBLearningEvent(owner_public_id=learner.public_id,course_id=COURSE_ID,event_type='reading_threshold',source='frontend',trace_id='fc5-teacher-study',object_type='chapter',object_id='chapter-demo',payload={'path_id':path.id,'active_seconds':1200},occurred_at=confirmation_at-timedelta(minutes=5));db.add(study);db.flush()
  confirm=DBLearningEvent(owner_public_id=learner.public_id,course_id=COURSE_ID,event_type='teacher_confirmed',source='teacher',trace_id='fc5-teacher-confirm',object_type='chapter',object_id='chapter-demo',payload={'scope':'intervention_completion','path_id':path.id,'learner_event_id':study.id,'teacher_public_id':teacher_id},occurred_at=confirmation_at);db.add(confirm)
  artifact=DBArtifact(owner_public_id=teacher_id,course_id=COURSE_ID,artifact_type='lesson',title='教师审核课程内容',status='approved');db.add(artifact);db.flush()
  av=DBArtifactVersion(artifact_id=artifact.id,version_number=1,content='# 冻结合成课程内容',content_hash='3'*64,metadata_json={'data_class':'synthetic_e2e_fixture'},created_by_public_id=teacher_id);db.add(av);db.flush();artifact.current_version_id=av.id
  db.add(DBContentReviewCase(artifact_id=artifact.id,submitted_version_id=av.id,course_id=COURSE_ID,submitted_by_public_id=teacher_id,status='approved',evidence_snapshot={'data_class':'synthetic_e2e_fixture'},submission_note='演示角色审核',resolved_at=confirmation_at-timedelta(hours=1)));db.commit()
  return {'class_id':classroom.id,'confirmation_at':confirmation_at.isoformat()+'Z'}

def main():
 OUTPUT.mkdir(parents=True,exist_ok=True)
 for p in OUTPUT.iterdir():
  if p.is_file():p.unlink()
 for suffix in ('','-wal','-shm'):
  p=Path(f'{DB_PATH}{suffix}')
  if p.exists():p.unlink()
 env=os.environ.copy();env.update({'EDUMATRIX_DB_PATH':str(DB_PATH),'EDUMATRIX_AUTH_SECRET_KEY':'fc5-teacher-journey-isolated-secret','EDUMATRIX_LLM_PROVIDER':'deterministic','EDUMATRIX_LLM_MODEL':'deterministic','EDUMATRIX_LLM_API_KEY':'','EDUMATRIX_LLM_ENDPOINT':'','EDUMATRIX_RELOAD':'0','EDUMATRIX_SANDBOX_MODE':'disabled','EDUMATRIX_HOST':'127.0.0.1','EDUMATRIX_PORT':str(PORT),'PYTHONUNBUFFERED':'1'});os.environ.update(env);seed_course()
 report={'scope':'FC5 teacher journey, visits stay at permission-only 1/7, six canonical governance facts, post-intervention report through production API, refresh and mobile','fixture_boundary':'Course governance, intervention and review facts use a clearly labelled isolated synthetic E2E database; the final effect report is generated through the production teaching analytics API.','started_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'checks':{},'screenshots':[]};backend=None
 try:
  with(OUTPUT/'backend.log').open('w',encoding='utf-8')as log:
   backend=subprocess.Popen([sys.executable,'run.py'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT);wait_port(True)
   with sync_playwright()as pw:
    browser=pw.chromium.launch(headless=True);context=browser.new_context(viewport={'width':1440,'height':1000},locale='zh-CN');page=context.new_page()
    try:
     registration=page.request.post(f'{BASE}/api/auth/register',data={'username':USERNAME,'password':PASSWORD,'display_name':'FC5 教师旅程验收账号'});assert registration.ok,registration.text();identity=registration.json();teacher_id=promote_teacher(USERNAME);headers={'Authorization':f"Bearer {identity['access_token']}"}
     page.goto(f'{BASE}/login',wait_until='networkidle');page.evaluate("""([t,u])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role','teacher');localStorage.setItem('edumatrix_username',u);localStorage.setItem('edumatrix_display_name','FC5 教师旅程验收账号');localStorage.setItem('edumatrix_onboarded','true')}""",[identity['access_token'],USERNAME]);page.goto(f'{BASE}/judge-journey/teacher',wait_until='networkidle')
     page.get_by_text('尚未开始教师教学旅程',exact=True).wait_for(state='visible',timeout=20000);page.get_by_label('目标课程').select_option(COURSE_ID);report['screenshots'].append(shot(page,'01-empty-teacher-boundary'));page.get_by_role('button',name='新建教学旅程').click();page.get_by_text('1 / 7',exact=True).wait_for(state='visible',timeout=20000);report['screenshots'].append(shot(page,'02-started-permission-only-one-of-seven'))
     ws=page.request.get(f'{BASE}/api/v1/competition-journeys/teacher',headers=headers).json();run=ws['runs'][0];routes=[]
     for step in run['steps']:
      page.goto(f'{BASE}/judge-journey/teacher',wait_until='networkidle');article=page.locator('.steps article').filter(has=page.locator('.body > span').get_by_text(step['key'],exact=True));article.get_by_role('button').click();page.wait_for_url(f"**{step['route']}**",timeout=20000);routes.append(step['route'])
     visited=page.request.get(f"{BASE}/api/v1/competition-journeys/teacher/runs/{run['id']}",headers=headers).json();assert visited['progress']['completed']==1 and len(visited['visits'])==7
     page.goto(f'{BASE}/judge-journey/teacher',wait_until='networkidle');page.get_by_text('1 / 7',exact=True).wait_for(state='visible',timeout=20000);report['screenshots'].append(shot(page,'03-seven-visits-still-one'))
     fixture=seed_six_steps(teacher_id);page.get_by_role('button',name='刷新教师教学旅程').click();page.get_by_text('6 / 7',exact=True).wait_for(state='visible',timeout=20000);page.locator('.steps article').filter(has=page.locator('.body > span').get_by_text('effect_review',exact=True)).get_by_text('需要在干预确认后生成新的分析报告',exact=True).wait_for();report['screenshots'].append(shot(page,'04-six-of-seven-before-effect-report'))
     effect=page.request.post(f'{BASE}/api/v1/teaching-analytics/reports',headers=headers,data={'class_id':fixture['class_id'],'period_start':fixture['confirmation_at'],'period_end':(datetime.utcnow()+timedelta(days=1)).isoformat()+'Z'});assert effect.ok,effect.text();effect_body=effect.json();assert effect_body['created'] is True
     page.get_by_role('button',name='刷新教师教学旅程').click();page.get_by_text('7 / 7',exact=True).wait_for(state='visible',timeout=20000);page.get_by_text('七步教学闭环完成',exact=True).wait_for(state='visible');report['screenshots'].append(shot(page,'05-completed-seven-of-seven'));page.reload(wait_until='networkidle');page.get_by_text('7 / 7',exact=True).wait_for(state='visible',timeout=20000);page.set_viewport_size({'width':390,'height':844});page.reload(wait_until='networkidle');page.get_by_text('七步教学闭环完成',exact=True).wait_for(state='visible',timeout=20000);doc=page.evaluate('document.documentElement.scrollWidth');assert doc<=390;report['screenshots'].append(shot(page,'06-mobile-refresh-recovery'))
     final=page.request.get(f"{BASE}/api/v1/competition-journeys/teacher/runs/{run['id']}",headers=headers).json();assert final['status']=='completed' and final['progress']['completed']==7 and all(x['complete']for x in final['steps']);effect_step=next(x for x in final['steps'] if x['key']=='effect_review');assert effect_step['evidence_id']==effect_body['id']
     report['checks']={'run_id':run['id'],'course_id':COURSE_ID,'initial_progress':1,'visit_count':len(visited['visits']),'progress_after_visits':visited['progress']['completed'],'visited_routes':routes,'fixture_progress':6,'intervention_confirmation_at':fixture['confirmation_at'],'effect_report_id':effect_body['id'],'final_progress':7,'final_status':final['status'],'refresh_recovered':True,'mobile':{'width':390,'document_width':doc}};report['result']='passed'
    except Exception:
     try:report['screenshots'].append(shot(page,'error'))
     except Exception:pass
     raise
    finally:context.close();browser.close()
 except Exception as exc:report['result']='failed';report['error']=f'{type(exc).__name__}: {exc}';raise
 finally:
  report['finished_at']=time.strftime('%Y-%m-%dT%H:%M:%S%z');stop(backend)
  if DB_PATH.exists():
   with sqlite3.connect(DB_PATH)as source,sqlite3.connect(EVIDENCE_DB)as target:
    source.backup(target);checks=report.setdefault('checks',{});checks['sqlite_integrity']=target.execute('pragma integrity_check').fetchone()[0];checks['migration_057']=target.execute("select count(*) from schema_migrations where version='20260805_057'").fetchone()[0]==1;checks['teacher_runs']=target.execute("select count(*) from competition_journey_runs where journey_type='teacher'").fetchone()[0];checks['journey_visits']=target.execute('select count(*) from competition_journey_visits').fetchone()[0];checks['analytics_reports']=target.execute('select count(*) from teaching_analytics_reports').fetchone()[0];checks['teacher_confirmations']=target.execute("select count(*) from learning_events where event_type='teacher_confirmed'").fetchone()[0]
  (OUTPUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');manifest()
 print(json.dumps(report,ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
