"""Verify the FC5 multimedia creation judge journey with an isolated database."""
from __future__ import annotations
import hashlib,json,os,socket,sqlite3,subprocess,sys,time
from pathlib import Path
from playwright.sync_api import Page,sync_playwright

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
OUTPUT=Path(os.environ.get('EDUMATRIX_E2E_OUTPUT_DIR',ROOT/'outputs'/'FC_比赛功能完全体'/'evidence'/'FC5-02A'/'browser-e2e'))
DB_PATH=Path(os.environ.get('EDUMATRIX_E2E_DB_PATH',ROOT/'outputs'/'_fc5_media_journey_runtime.db'))
EVIDENCE_DB=OUTPUT/'fc5_media_journey_evidence.db';PORT=int(os.environ.get('EDUMATRIX_E2E_PORT','8839'));BASE=f'http://127.0.0.1:{PORT}'
USERNAME='fc5_media_journey';PASSWORD='FC5-media-journey-e2e-2026!';COURSE_ID='fc5-media-journey-course'
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
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def shot(page:Page,name):
 path=OUTPUT/f'{name}.png';page.screenshot(path=str(path),full_page=True);return path.name
def manifest():
 files=[{'file':p.name,'bytes':p.stat().st_size,'sha256':digest(p)} for p in sorted(OUTPUT.iterdir()) if p.is_file() and p.name!='manifest.json' and not p.name.endswith(('-wal','-shm'))]
 (OUTPUT/'manifest.json').write_text(json.dumps({'schema_version':'fc5.media-judge-journey-e2e-manifest.v1','files':files},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def seed_course():
 from app.database import DBCourse,SessionLocal,init_db
 init_db()
 with SessionLocal() as db:
  db.add(DBCourse(id=COURSE_ID,version='frozen-demo-v1',title='人工智能多媒体课程（冻结合成演示）',subject='人工智能',status='published',visibility='public',manifest_version='fc5-media-e2e-v1',manifest_data={'data_class':'synthetic_e2e_fixture'}));db.commit()
def seed_media(username):
 from app.database import (DBArtifact,DBArtifactVersion,DBChapter,DBChapterVideoLink,DBSourceDocument,DBUser,DBVideoOutputVersion,DBVideoPracticeSet,DBVideoPracticeVersion,DBVideoProject,DBVideoRenderTask,DBVideoScriptVersion,DBWebDeck,DBWebDeckVersion,SessionLocal)
 with SessionLocal() as db:
  owner=db.query(DBUser).filter_by(username=username).one()
  source=DBSourceDocument(course_id=COURSE_ID,title='第一章来源',filename='chapter.md',file_format='md',content_hash='1'*64,source_sha256='1'*64,processed_sha256='1'*64,processing_status='ready');db.add(source);db.flush()
  chapter=DBChapter(course_id=COURSE_ID,source_document_id=source.id,stable_key='chapter-1',title='第一章 多媒体学习设计',position=1);db.add(chapter);db.flush()
  handout=DBArtifact(owner_public_id=owner.public_id,course_id=COURSE_ID,artifact_type='handout',title='第一章讲义',status='approved');db.add(handout);db.flush()
  hv=DBArtifactVersion(artifact_id=handout.id,version_number=1,content='# 第一章讲义',content_format='markdown',content_hash='2'*64,metadata_json={'data_class':'synthetic_e2e_fixture'},created_by_public_id=owner.public_id);db.add(hv);db.flush();handout.current_version_id=hv.id
  deck=DBWebDeck(owner_public_id=owner.public_id,course_id=COURSE_ID,title='第一章网页课件');db.add(deck);db.flush()
  dv=DBWebDeckVersion(deck_id=deck.id,version_number=1,slides_snapshot=[{'title':'第一章','speaker_notes':'冻结合成演示'}],theme_snapshot={},content_hash='3'*64,created_by_public_id=owner.public_id);db.add(dv);db.flush();deck.current_version_id=dv.id
  project=DBVideoProject(owner_public_id=owner.public_id,course_id=COURSE_ID,title='第一章技能微课');db.add(project);db.flush()
  script=DBVideoScriptVersion(project_id=project.id,version_number=1,scenes=[{'title':'第一章','narration':'冻结合成讲稿','duration_ms':1000}],total_duration_ms=1000,content_hash='4'*64,created_by_public_id=owner.public_id);db.add(script);db.flush();project.current_script_version_id=script.id
  task=DBVideoRenderTask(project_id=project.id,script_version_id=script.id,owner_public_id=owner.public_id,idempotency_key='fc5-media-render',status='completed',progress=100,audio_status='text_only');db.add(task);db.flush()
  output=DBVideoOutputVersion(project_id=project.id,render_task_id=task.id,owner_public_id=owner.public_id,version_number=1,output_manifest={'files':[{'name':'course-video.mp4','bytes':2048,'sha256':'5'*64}]},output_dir='isolated-e2e',mp4_sha256='5'*64,duration_ms=1000,quality_report={'passed':True,'truth_boundary':'synthetic fixture'});db.add(output);db.flush();task.output_version_id=output.id
  link=DBChapterVideoLink(owner_public_id=owner.public_id,course_id=COURSE_ID,chapter_id=chapter.id,video_project_id=project.id,input_hash='6'*64,source_ref_ids=[],knowledge_point_ids=[],learning_objectives=['理解多媒体学习设计'],source_snapshot=[{'data_class':'synthetic_e2e_fixture'}],quality_snapshot={'passed':True},truth_boundary='冻结合成 E2E 夹具');db.add(link);db.flush()
  practice=DBVideoPracticeSet(owner_public_id=owner.public_id,chapter_video_link_id=link.id,course_id=COURSE_ID);db.add(practice);db.flush()
  pv=DBVideoPracticeVersion(practice_set_id=practice.id,version_number=1,question_version_ids=[],interactive_lab_instance_ids=[],binding_snapshot=[{'data_class':'synthetic_e2e_fixture'}],content_hash='7'*64,created_by_public_id=owner.public_id);db.add(pv);db.flush();practice.current_version_id=pv.id;db.commit()
  return {'handout':{'resource_type':'handout','resource_id':handout.id,'resource_version_id':hv.id},'ppt':{'resource_type':'ppt','resource_id':deck.id,'resource_version_id':dv.id},'video':{'resource_type':'video','resource_id':project.id,'resource_version_id':script.id}}
def main():
 OUTPUT.mkdir(parents=True,exist_ok=True)
 for p in OUTPUT.iterdir():
  if p.is_file():p.unlink()
 for suffix in ('','-wal','-shm'):
  p=Path(f'{DB_PATH}{suffix}')
  if p.exists():p.unlink()
 env=os.environ.copy();env.update({'EDUMATRIX_DB_PATH':str(DB_PATH),'EDUMATRIX_AUTH_SECRET_KEY':'fc5-media-journey-isolated-secret','EDUMATRIX_LLM_PROVIDER':'deterministic','EDUMATRIX_LLM_MODEL':'deterministic','EDUMATRIX_LLM_API_KEY':'','EDUMATRIX_LLM_ENDPOINT':'','EDUMATRIX_RELOAD':'0','EDUMATRIX_SANDBOX_MODE':'disabled','EDUMATRIX_HOST':'127.0.0.1','EDUMATRIX_PORT':str(PORT),'PYTHONUNBUFFERED':'1'});os.environ.update(env);seed_course()
 report={'scope':'FC5 media creation journey, visits stay 0/7, six canonical media facts, final bundle through production API, refresh and mobile','fixture_boundary':'First six canonical media facts use an isolated E2E database; the final resource bundle is created through the production API and resolvers.','started_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'checks':{},'screenshots':[]};backend=None
 try:
  with(OUTPUT/'backend.log').open('w',encoding='utf-8')as log:
   backend=subprocess.Popen([sys.executable,'run.py'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT);wait_port(True)
   with sync_playwright()as pw:
    browser=pw.chromium.launch(headless=True);context=browser.new_context(viewport={'width':1440,'height':1000},locale='zh-CN');page=context.new_page()
    try:
     registration=page.request.post(f'{BASE}/api/auth/register',data={'username':USERNAME,'password':PASSWORD,'display_name':'FC5 多媒体旅程验收账号'});assert registration.ok,registration.text();identity=registration.json();headers={'Authorization':f"Bearer {identity['access_token']}"}
     page.goto(f'{BASE}/login',wait_until='networkidle');page.evaluate("""([t,u])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role','student');localStorage.setItem('edumatrix_username',u);localStorage.setItem('edumatrix_display_name','FC5 多媒体旅程验收账号');localStorage.setItem('edumatrix_onboarded','true')}""",[identity['access_token'],USERNAME]);page.goto(f'{BASE}/judge-journey/media',wait_until='networkidle')
     page.get_by_text('尚未开始多媒体创作旅程',exact=True).wait_for(state='visible',timeout=20000);page.get_by_label('目标课程').select_option(COURSE_ID);report['screenshots'].append(shot(page,'01-empty-version-boundary'));page.get_by_role('button',name='新建创作旅程').click();page.get_by_text('0 / 7',exact=True).wait_for(state='visible',timeout=20000);report['screenshots'].append(shot(page,'02-started-zero-of-seven'))
     ws=page.request.get(f'{BASE}/api/v1/competition-journeys/media',headers=headers).json();run=ws['runs'][0];routes=[]
     for step in run['steps']:
      page.goto(f'{BASE}/judge-journey/media',wait_until='networkidle');article=page.locator('.steps article').filter(has=page.locator('.body > span').get_by_text(step['key'],exact=True));article.get_by_role('button').click();page.wait_for_url(f"**{step['route']}**",timeout=20000);routes.append(step['route'])
     visited=page.request.get(f"{BASE}/api/v1/competition-journeys/media/runs/{run['id']}",headers=headers).json();assert visited['progress']['completed']==0 and len(visited['visits'])==7
     page.goto(f'{BASE}/judge-journey/media',wait_until='networkidle');page.get_by_text('0 / 7',exact=True).wait_for(state='visible',timeout=20000);report['screenshots'].append(shot(page,'03-seven-visits-still-zero'))
     items=seed_media(USERNAME);page.get_by_role('button',name='刷新多媒体旅程').click();page.get_by_text('6 / 7',exact=True).wait_for(state='visible',timeout=20000);page.locator('.steps article').filter(has=page.locator('.body > span').get_by_text('bundle',exact=True)).get_by_text('需要冻结至少讲义、课件和视频版本',exact=True).wait_for();report['screenshots'].append(shot(page,'04-six-of-seven-before-bundle'))
     bundle=page.request.post(f'{BASE}/api/v1/resource-bundles',headers=headers,data={'title':'第一章多媒体学习资源包','learning_objective':'完成第一章多媒体学习闭环','course_id':COURSE_ID,'knowledge_point_id':None,'profile':{'data_class':'synthetic_e2e_fixture'},'items':[items['handout'],items['ppt'],items['video']]});assert bundle.ok,bundle.text();bundle_body=bundle.json();assert bundle_body['current_version']['quality']['resource_count']==3
     page.get_by_role('button',name='刷新多媒体旅程').click();page.get_by_text('7 / 7',exact=True).wait_for(state='visible',timeout=20000);page.get_by_text('七步创作闭环完成',exact=True).wait_for(state='visible');report['screenshots'].append(shot(page,'05-completed-seven-of-seven'));page.reload(wait_until='networkidle');page.get_by_text('7 / 7',exact=True).wait_for(state='visible',timeout=20000);page.set_viewport_size({'width':390,'height':844});page.reload(wait_until='networkidle');page.get_by_text('七步创作闭环完成',exact=True).wait_for(state='visible',timeout=20000);doc=page.evaluate('document.documentElement.scrollWidth');assert doc<=390;report['screenshots'].append(shot(page,'06-mobile-refresh-recovery'))
     final=page.request.get(f"{BASE}/api/v1/competition-journeys/media/runs/{run['id']}",headers=headers).json();assert final['status']=='completed' and final['progress']['completed']==7 and all(x['complete']for x in final['steps'])
     report['checks']={'run_id':run['id'],'course_id':COURSE_ID,'initial_progress':0,'visit_count':len(visited['visits']),'progress_after_visits':visited['progress']['completed'],'visited_routes':routes,'fixture_progress':6,'bundle_id':bundle_body['id'],'bundle_resource_types':[x['resource_type']for x in bundle_body['current_version']['items']],'final_progress':7,'final_status':final['status'],'refresh_recovered':True,'mobile':{'width':390,'document_width':doc}};report['result']='passed'
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
    source.backup(target);checks=report.setdefault('checks',{});checks['sqlite_integrity']=target.execute('pragma integrity_check').fetchone()[0];checks['migration_056']=target.execute("select count(*) from schema_migrations where version='20260805_056'").fetchone()[0]==1;checks['journey_runs']=target.execute("select count(*) from competition_journey_runs where journey_type='media'").fetchone()[0];checks['journey_visits']=target.execute('select count(*) from competition_journey_visits').fetchone()[0];checks['resource_bundles']=target.execute('select count(*) from resource_bundles').fetchone()[0];checks['resource_bundle_items']=target.execute('select count(*) from resource_bundle_items').fetchone()[0]
  (OUTPUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');manifest()
 print(json.dumps(report,ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
