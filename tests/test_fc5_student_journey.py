from __future__ import annotations
import json
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,event,text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import app.competition_journey_api as journey_api
from app.auth import get_current_user,get_password_hash
from app.database import (
 Base,DBArtifact,DBArtifactVersion,DBAssessmentAttempt,DBAssessmentExam,DBAssessmentExamReport,
 DBAssessmentExamSitting,DBAssessmentExamVersion,DBAssessmentQuestion,DBAssessmentQuestionVersion,
 DBAssessmentRetestTask,DBCompetitionJourneyRun,DBCompetitionJourneyVisit,DBCourse,DBLearningPath,
 DBPathNode,DBPlanDraft,DBPlanVersion,DBProfileSnapshot,DBUser,
)
from app.main import app
from app.migrations import apply_registered_migrations

def fixture():
 engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
 @event.listens_for(engine,'connect')
 def fk(c,_):c.execute('PRAGMA foreign_keys=ON')
 Base.metadata.create_all(engine);apply_registered_migrations(engine);db=sessionmaker(bind=engine)()
 owner=DBUser(public_id='journey-owner',username='journey-owner',display_name='旅程学习者',hashed_password=get_password_hash('pw'),role='student');other=DBUser(public_id='journey-other',username='journey-other',display_name='其他学习者',hashed_password=get_password_hash('pw'),role='student');course=DBCourse(id='journey-course',version='v1',title='人工智能完整课程',status='published',manifest_version='m1');db.add_all([owner,other,course]);db.commit();return db,owner,other,course
def client(monkeypatch,db,user):
 async def fake(op):return op(db)
 monkeypatch.setattr(journey_api,'run_db_op',fake);app.dependency_overrides[get_current_user]=lambda:user;return TestClient(app)

def test_visits_never_fake_completion_and_owner_isolation(monkeypatch):
 db,owner,other,course=fixture();c=client(monkeypatch,db,owner)
 try:
  run=c.post('/api/v1/competition-journeys/student/runs',json={'course_id':course.id,'run_key':'student-journey'});assert run.status_code==201,run.text;body=run.json();assert body['progress']['completed']==0
  for step in body['steps']:
   visit=c.post(f"/api/v1/competition-journeys/student/runs/{body['id']}/visits",json={'step_key':step['key'],'route':step['route']});assert visit.status_code==201,visit.text
  refreshed=c.get(f"/api/v1/competition-journeys/student/runs/{body['id']}");assert refreshed.status_code==200 and refreshed.json()['progress']['completed']==0 and len(refreshed.json()['visits'])==8
  bad=c.post(f"/api/v1/competition-journeys/student/runs/{body['id']}/visits",json={'step_key':'profile','route':'/wrong-route'});assert bad.status_code==422 and bad.json()['detail']['code']=='journey_route_mismatch'
 finally:app.dependency_overrides.pop(get_current_user,None)
 c=client(monkeypatch,db,other)
 try:assert c.get(f"/api/v1/competition-journeys/student/runs/{body['id']}").status_code==403
 finally:app.dependency_overrides.pop(get_current_user,None)

def test_real_evidence_completes_all_steps_and_refresh(monkeypatch):
 db,owner,_,course=fixture();c=client(monkeypatch,db,owner)
 try:run=c.post('/api/v1/competition-journeys/student/runs',json={'course_id':course.id,'run_key':'evidence-journey'}).json()
 finally:app.dependency_overrides.pop(get_current_user,None)
 profile=DBProfileSnapshot(owner_public_id=owner.public_id,profile_version='p1',snapshot={'level':'baseline'},content_hash='1'*64,trace_id='trace-profile')
 question=DBAssessmentQuestion(owner_public_id=owner.public_id,course_id=course.id,question_type='single_choice',origin='manual',status='approved',current_version_id=None)
 db.add_all([profile,question]);db.flush();qv=DBAssessmentQuestionVersion(question_id=question.id,version_number=1,prompt='2+2?',options=['4'],answer_key={'choice':'4'},scoring_rule={'kind':'exact'},explanation='4',misconception_tags=[],bloom_level='understand',irt_parameters={'difficulty':0.1,'discrimination':1.0,'guessing':0.0},source_ref_ids=[],content_hash='2'*64,created_by_public_id=owner.public_id);db.add(qv);db.flush();question.current_version_id=qv.id
 attempt=DBAssessmentAttempt(owner_public_id=owner.public_id,course_id=course.id,question_version_id=qv.id,idempotency_key='journey-diagnosis',mode='diagnostic',answer={'choice':'4'},score=1,correct=True,grading_status='graded')
 plan=DBPlanDraft(owner_public_id=owner.public_id,course_id=course.id,title='个性路径',status='confirmed',idempotency_key='journey-plan');db.add_all([attempt,plan]);db.flush();pv=DBPlanVersion(plan_draft_id=plan.id,version_number=1,profile_snapshot_id=profile.id,content={'nodes':[]},content_hash='3'*64,created_by_public_id=owner.public_id);db.add(pv);db.flush();plan.current_version_id=pv.id;plan.confirmed_version_id=pv.id
 path=DBLearningPath(owner_public_id=owner.public_id,course_id=course.id,source_plan_version_id=pv.id,status='active');db.add(path);db.flush();node=DBPathNode(learning_path_id=path.id,node_key='n1',sequence=1,node_type='chapter',target_object_id=None,title='基础',status='pending',prerequisites=[])
 resources=[]
 for index,kind in enumerate(('lesson','lab_guide','tiered_quiz'),1):
  art=DBArtifact(owner_public_id=owner.public_id,course_id=course.id,artifact_type=kind,title=kind,status='approved');db.add(art);db.flush();ver=DBArtifactVersion(artifact_id=art.id,version_number=1,content='{}',content_format='json',content_hash=str(index+3)*64,created_by_public_id=owner.public_id);db.add(ver);db.flush();art.current_version_id=ver.id;resources.append(art)
 lab=DBArtifact(owner_public_id=owner.public_id,course_id=course.id,artifact_type='interactive_lab_instance',title='实验',status='approved');db.add(lab);db.flush();labv=DBArtifactVersion(artifact_id=lab.id,version_number=1,content=json.dumps({'status':'passed','hidden_acceptance':{'passed':True}}),content_format='json',content_hash='7'*64,created_by_public_id=owner.public_id);db.add(labv);db.flush();lab.current_version_id=labv.id
 exam=DBAssessmentExam(owner_public_id=owner.public_id,course_id=course.id,title='正式考试',status='published',current_version_id=None);db.add(exam);db.flush();ev=DBAssessmentExamVersion(exam_id=exam.id,version_number=1,instructions='',feedback_policy='after_close',total_points=100,manifest_hash='8'*64,created_by_public_id=owner.public_id);db.add(ev);db.flush();exam.current_version_id=ev.id;sitting=DBAssessmentExamSitting(exam_id=exam.id,exam_version_id=ev.id,owner_public_id=owner.public_id,status='released');db.add(sitting);db.flush();report=DBAssessmentExamReport(sitting_id=sitting.id,report_version=1,report_data={'score':100},input_hash='9'*64,content_hash='a'*64,created_by_public_id=owner.public_id)
 retest_attempt=DBAssessmentAttempt(owner_public_id=owner.public_id,course_id=course.id,question_version_id=qv.id,idempotency_key='journey-retest',mode='retest',answer={'choice':'4'},score=1,correct=True,grading_status='graded')
 db.add(retest_attempt);db.flush();retest=DBAssessmentRetestTask(owner_public_id=owner.public_id,misconception_review_id='placeholder',source_attempt_id=attempt.id,question_version_id=qv.id,course_id=course.id,due_at=__import__('datetime').datetime.utcnow(),status='completed',completion_attempt_id=retest_attempt.id)
 # Retest's review FK needs a real review; add it before flushing the task.
 from app.database import DBMisconceptionReview
 review=DBMisconceptionReview(owner_public_id=owner.public_id,attempt_id=attempt.id,candidate_category='knowledge_gap',status='accepted');db.add(review);db.flush();retest.misconception_review_id=review.id
 db.add_all([node,report,retest]);db.commit()
 c=client(monkeypatch,db,owner)
 try:
  mid=c.get(f"/api/v1/competition-journeys/student/runs/{run['id']}").json();assert mid['progress']['completed']==7 and next(x for x in mid['steps'] if x['key']=='path_update')['complete'] is False
  node.status='completed';path.lock_version+=1;db.commit();final=c.get(f"/api/v1/competition-journeys/student/runs/{run['id']}");assert final.status_code==200,final.text;body=final.json();assert body['status']=='completed' and body['progress']['completed']==8 and all(x['complete'] for x in body['steps'])
 finally:app.dependency_overrides.pop(get_current_user,None)

def test_migration_and_visit_immutability(monkeypatch):
 db,owner,_,course=fixture();c=client(monkeypatch,db,owner)
 try:
  run=c.post('/api/v1/competition-journeys/student/runs',json={'course_id':course.id,'run_key':'immutable'}).json();assert c.post(f"/api/v1/competition-journeys/student/runs/{run['id']}/visits",json={'step_key':'profile','route':'/student-analysis'}).status_code==201
 finally:app.dependency_overrides.pop(get_current_user,None)
 assert db.execute(text("select count(*) from schema_migrations where version='20260805_055'")).scalar_one()==1
 visit=db.query(DBCompetitionJourneyVisit).one();visit.route='/changed'
 try:db.commit();raise AssertionError('immutable visit trigger missing')
 except DatabaseError:db.rollback()
