from __future__ import annotations
import hashlib,json,os,socket,sqlite3,subprocess,sys,time
from pathlib import Path

R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R));O=R/'outputs'/'FC_比赛功能完全体'/'evidence'/'FC1-010'/'browser-e2e';D=R/'outputs'/'_fc1_resource_bundle_e2e.db';PORT=8820;U=f'http://127.0.0.1:{PORT}'
TYPES=('handout','mind_map','code','exercise','video','ppt','animation','lab')
def wait(state):
 for _ in range(300):
  with socket.socket() as s:ok=s.connect_ex(('127.0.0.1',PORT))==0
  if ok is state:return
  time.sleep(.2)
 raise RuntimeError('port wait failed')
def prepare(env):
 os.environ.update(env)
 from app.auth import get_password_hash
 from app.database import (init_db,SessionLocal,DBUser,DBCourse,DBCourseMembership,DBKnowledgePoint,DBArtifact,DBArtifactVersion,DBAssessmentQuestion,DBAssessmentQuestionVersion,DBVideoProject,DBVideoScriptVersion,DBWebDeck,DBWebDeckVersion,DBTeachingAnimation,DBTeachingAnimationVersion)
 init_db()
 with SessionLocal() as db:
  user=DBUser(username='fc1_bundle_e2e',hashed_password=get_password_hash('Bundle-2026!'),role='student',display_name='资源包演示用户');other=DBUser(username='fc1_bundle_other',hashed_password=get_password_hash('Bundle-2026!'),role='student',display_name='隔离用户');db.add_all([user,other]);db.flush();course=DBCourse(id='fc1-resource-bundle-course',version='1.0',title='机器学习技能训练',subject='人工智能',domain_pack='ml',visibility='private',status='published',owner_public_id=user.public_id,manifest_version='fc1-bundle-v1',manifest_data={'demo':True});kp=DBKnowledgePoint(domain_pack='ml',code='gradient-e2e',version='1',title='梯度下降');db.add_all([course,kp]);db.flush();db.add(DBCourseMembership(course_id=course.id,user_public_id=user.public_id,role='student',status='active'))
  for kind,atype,title in [('handout','lesson','梯度下降讲义'),('mind_map','mindmap','优化算法导图'),('code','code_example','梯度下降代码'),('lab','interactive_lab_instance','参数调优实验')]:
   a=DBArtifact(owner_public_id=user.public_id,course_id=course.id,artifact_type=atype,title=title,status='approved');db.add(a);db.flush();v=DBArtifactVersion(artifact_id=a.id,version_number=1,content=kind,content_format='markdown',content_hash=hashlib.sha256(kind.encode()).hexdigest(),metadata_json={'source_ref_ids':[f'ref-{kind}'],'quality':{'status':'checked'},'profile':{'modality':kind}},created_by_public_id=user.public_id);db.add(v);db.flush();a.current_version_id=v.id
  q=DBAssessmentQuestion(course_id=course.id,owner_public_id=user.public_id,question_type='single_choice',origin='manual',status='approved');db.add(q);db.flush();qv=DBAssessmentQuestionVersion(question_id=q.id,version_number=1,prompt='学习率过大最可能导致什么？',options=['稳定收敛','震荡'],answer_key={'correct':[1]},scoring_rule={'type':'exact'},explanation='步长过大',primary_knowledge_point_id=kp.id,bloom_level='analyze',expert_difficulty=.6,source_ref_ids=['ref-exercise'],content_hash='e'*64,created_by_public_id=user.public_id);db.add(qv);db.flush();q.current_version_id=qv.id
  video=DBVideoProject(owner_public_id=user.public_id,course_id=course.id,title='梯度下降讲解视频');db.add(video);db.flush();vv=DBVideoScriptVersion(project_id=video.id,version_number=1,scenes=[{'title':'目标'}],total_duration_ms=30000,content_hash='v'*64,created_by_public_id=user.public_id);db.add(vv);db.flush();video.current_script_version_id=vv.id
  deck=DBWebDeck(owner_public_id=user.public_id,course_id=course.id,title='梯度下降网页课件');db.add(deck);db.flush();dv=DBWebDeckVersion(deck_id=deck.id,version_number=1,slides_snapshot=[{'title':'梯度下降'}],theme_snapshot={},content_hash='p'*64,created_by_public_id=user.public_id);db.add(dv);db.flush();deck.current_version_id=dv.id
  animation=DBTeachingAnimation(owner_public_id=user.public_id,course_id=course.id,title='梯度下降轨迹',template_id='gradient-descent-2d-v1');db.add(animation);db.flush();av=DBTeachingAnimationVersion(animation_id=animation.id,version_number=1,parameters={'learning_rate':.1},frame_data=[{'index':0}],formula_snapshot={},quality_snapshot={'deterministic':True},content_hash='a'*64,created_by_public_id=user.public_id);db.add(av);db.flush();animation.current_version_id=av.id;db.commit()
def main():
 O.mkdir(parents=True,exist_ok=True)
 for p in O.iterdir():
  if p.is_file():p.unlink()
 for suffix in ('','-wal','-shm'):
  p=Path(str(D)+suffix)
  if p.exists():p.unlink()
 env=os.environ.copy();env.update({'EDUMATRIX_DB_PATH':str(D),'EDUMATRIX_AUTH_SECRET_KEY':'fc1-bundle','EDUMATRIX_LLM_API_KEY':'','EDUMATRIX_MULTIMODAL_LLM_API_KEY':'','EDUMATRIX_EMBEDDING_PROVIDER':'hash','EDUMATRIX_RELOAD':'0','EDUMATRIX_PORT':str(PORT),'PYTHON_DOTENV_DISABLED':'1'});prepare(env);rep={'checks':{},'screenshots':[]};proc=None
 try:
  with(O/'backend.log').open('w',encoding='utf-8')as log:
   proc=subprocess.Popen([sys.executable,'run.py'],cwd=R,env=env,stdout=log,stderr=subprocess.STDOUT);wait(True)
   from playwright.sync_api import sync_playwright
   with sync_playwright()as pw:
    browser=pw.chromium.launch(channel='chrome',headless=True);ctx=browser.new_context(viewport={'width':1440,'height':1000},locale='zh-CN');page=ctx.new_page();login=page.request.post(U+'/api/auth/login',form={'username':'fc1_bundle_e2e','password':'Bundle-2026!'});other=page.request.post(U+'/api/auth/login',form={'username':'fc1_bundle_other','password':'Bundle-2026!'});token=login.json()['access_token'];headers={'Authorization':'Bearer '+token};oh={'Authorization':'Bearer '+other.json()['access_token']};page.goto(U+'/login');page.evaluate("t=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role','student');localStorage.setItem('edumatrix_username','fc1_bundle_e2e');localStorage.setItem('edumatrix_onboarded','true')}",token);page.goto(U+'/resource-bundles');root=page.get_by_test_id('resource-bundle-workspace');root.wait_for(timeout=30000);root.get_by_label('课程').select_option('fc1-resource-bundle-course');root.get_by_test_id('bundle-coverage').get_by_text('8 / 8',exact=True).wait_for();root.get_by_role('button',name='创建资源包').click();root.get_by_text('资源包新版本已冻结。',exact=True).wait_for();root.get_by_text('v1',exact=True).first.wait_for();bundle=page.request.get(U+'/api/v1/resource-bundles',headers=headers).json()['items'][0];bid=bundle['id'];detail=page.request.get(U+f'/api/v1/resource-bundles/{bid}',headers=headers).json();assert len(detail['current_version']['items'])==8 and detail['current_version']['quality']['coverage']==1.0;rep['checks']['types']=[x['resource_type']for x in detail['current_version']['items']]
    root.locator('article[data-kind="handout"]').get_by_title('下移讲义').click();root.get_by_role('button',name='冻结新版本').click();root.get_by_text('资源包新版本已冻结。',exact=True).wait_for();root.get_by_text('v2',exact=True).first.wait_for();v2=page.request.get(U+f'/api/v1/resource-bundles/{bid}',headers=headers).json();assert v2['current_version']['version_number']==2;root.get_by_role('button',name='v1 初始资源包 恢复此版本').click();root.get_by_text('已恢复资源包 v1',exact=True).wait_for();page.reload();root=page.get_by_test_id('resource-bundle-workspace');root.get_by_test_id('bundle-coverage').get_by_text('8 / 8',exact=True).wait_for(timeout=30000);restored=page.request.get(U+f'/api/v1/resource-bundles/{bid}',headers=headers).json();assert restored['current_version']['version_number']==1;rep['checks']['refresh_restore']='v1';assert page.request.get(U+f'/api/v1/resource-bundles/{bid}',headers=oh).status==403;rep['checks']['owner']=403;page.screenshot(path=str(O/'01-desktop-resource-bundle.png'),full_page=True);rep['screenshots'].append('01-desktop-resource-bundle.png');page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(400);assert page.evaluate('document.documentElement.scrollWidth')<=390;page.screenshot(path=str(O/'02-mobile-resource-bundle.png'),full_page=True);rep['screenshots'].append('02-mobile-resource-bundle.png');rep['result']='passed';ctx.close();browser.close()
 finally:
  if proc and proc.poll()is None:subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True);proc.wait();wait(False)
  if D.exists():
   with sqlite3.connect(D)as source,sqlite3.connect(O/'resource_bundle_evidence.db')as target:source.backup(target);rep['checks']['sqlite']=target.execute('pragma integrity_check').fetchone()[0];rep['checks']['bundles']=target.execute('select count(*) from resource_bundles').fetchone()[0];rep['checks']['versions']=target.execute('select count(*) from resource_bundle_versions').fetchone()[0];rep['checks']['items']=target.execute('select count(*) from resource_bundle_items').fetchone()[0]
  (O/'report.json').write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');files=[{'file':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}for p in sorted(O.iterdir())if p.is_file()and p.name!='manifest.json'and not p.name.endswith(('-wal','-shm'))];(O/'manifest.json').write_text(json.dumps({'files':files},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(rep,ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())
