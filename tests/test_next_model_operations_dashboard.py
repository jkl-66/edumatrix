from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user, get_password_hash
from app.database import Base, DBCourse, DBCourseMembership, DBGenerationTask, DBModelCall, DBModelQuotaBucket, DBUser
from app.main import app
from app.model_operations_dashboard import dashboard
import app.model_operations_dashboard_api as dashboard_api


def fixture():
    engine=create_engine('sqlite:///:memory:',connect_args={'check_same_thread':False},poolclass=StaticPool);Base.metadata.create_all(engine);db=sessionmaker(bind=engine)()
    teacher=DBUser(public_id='ops-teacher',username='ops-teacher',hashed_password=get_password_hash('pw'),role='teacher')
    outsider=DBUser(public_id='ops-outsider',username='ops-outsider',hashed_password=get_password_hash('pw'),role='teacher')
    admin=DBUser(public_id='ops-admin',username='ops-admin',hashed_password=get_password_hash('pw'),role='admin')
    student=DBUser(public_id='ops-student',username='ops-student',hashed_password=get_password_hash('pw'),role='student')
    managed=DBCourse(id='ops-managed',version='1',title='Managed',manifest_version='1',owner_public_id=teacher.public_id)
    hidden=DBCourse(id='ops-hidden',version='1',title='Hidden',manifest_version='1',owner_public_id=outsider.public_id)
    db.add_all([teacher,outsider,admin,student,managed,hidden]);db.flush();db.add(DBCourseMembership(course_id=managed.id,user_public_id=teacher.public_id,role='teacher',status='active'))
    now=datetime.utcnow()
    db.add_all([
        DBModelCall(id='ops-ok',trace_id='trace-ok',owner_public_id=student.public_id,course_id=managed.id,capability='quiz',prompt_version='1',provider='demo',model='m1',status='completed',input_summary={'fields':['course_id'],'content_included':False},input_tokens=100,output_tokens=25,estimated_cost=.001,pricing_version='price-1',duration_ms=1000,created_at=now,completed_at=now),
        DBModelCall(id='ops-fail',trace_id='trace-fail',owner_public_id=student.public_id,course_id=managed.id,capability='quiz',prompt_version='1',provider='demo',model='m1',status='failed',input_summary={'content_included':False},input_tokens=50,output_tokens=0,estimated_cost=0,pricing_version='unpriced',duration_ms=20000,error_code='provider_timeout',created_at=now,completed_at=now),
        DBModelCall(id='ops-hidden-call',trace_id='trace-hidden',owner_public_id=student.public_id,course_id=hidden.id,capability='report',prompt_version='1',provider='other',model='secret',status='completed',input_summary={'content_included':False},input_tokens=999,output_tokens=999,duration_ms=5,created_at=now,completed_at=now),
        DBGenerationTask(id='ops-stale',owner_public_id=student.public_id,course_id=managed.id,trace_id='trace-task',status='running',capability='quiz',idempotency_key='ops-stale',created_at=now-timedelta(minutes=20),updated_at=now-timedelta(minutes=20)),
        DBModelQuotaBucket(scope_type='course',scope_key=managed.id,utc_day=now.date().isoformat(),call_count=2,reserved_tokens=175,reserved_cost=.001),
        DBModelQuotaBucket(scope_type='course',scope_key=hidden.id,utc_day=now.date().isoformat(),call_count=1,reserved_tokens=1998,reserved_cost=9),
    ]);db.commit();return db,teacher,outsider,admin,student


def test_teacher_scope_sla_cost_alerts_and_privacy():
    db,teacher,_,_,_=fixture();result=dashboard(db,actor=teacher,days=7)
    assert result['scope']=={'type':'managed_courses','course_ids':['ops-managed'],'course_count':1}
    assert result['summary']['calls']==2 and result['summary']['input_tokens']==150
    assert result['sla']['sample_size']==2 and result['sla']['metrics']['success_rate']['value']==50.0
    assert result['sla']['metrics']['p95_latency_ms']['value']==20000
    assert {item['code'] for item in result['alerts']}=={'success_rate_below_demo_threshold','latency_above_demo_threshold','stale_running_tasks','unpriced_calls'}
    assert result['quota_buckets'][0]['utilization'] is None and result['quota_buckets'][0]['configured_limit'] is None
    assert all(call['course_id']=='ops-managed' for call in result['recent_calls'])
    assert result['truthfulness']['raw_prompts_included'] is False and result['truthfulness']['raw_outputs_included'] is False
    assert result['recent_calls'][0]['input_summary']['summary_fields_disclosed'] and 'secret' not in str(result)


def test_admin_global_and_empty_teacher_do_not_fabricate_samples():
    db,_,outsider,admin,_=fixture();global_result=dashboard(db,actor=admin,days=7)
    assert global_result['scope']['type']=='global' and global_result['summary']['calls']==3
    # Outsider owns the hidden course and therefore sees exactly its one call.
    own=dashboard(db,actor=outsider,days=7);assert own['summary']['calls']==1 and own['sla']['sample_size']==1
    unassigned=DBUser(public_id='ops-empty',username='ops-empty',hashed_password=get_password_hash('pw'),role='teacher');db.add(unassigned);db.commit()
    empty=dashboard(db,actor=unassigned,days=7);assert empty['summary']['calls']==0 and empty['sla']['sample_size']==0
    assert empty['sla']['metrics']['success_rate']['value'] is None and empty['alerts']==[]


def test_api_role_scope_and_json_csv_exports(monkeypatch):
    db,teacher,_,_,student=fixture();identity={'user':teacher}
    async def fake(operation):return operation(db)
    monkeypatch.setattr(dashboard_api,'run_db_op',fake);app.dependency_overrides[get_current_user]=lambda:identity['user'];client=TestClient(app)
    try:
        response=client.get('/api/v1/model-operations-dashboard?days=7');assert response.status_code==200 and response.json()['summary']['calls']==2
        csv_response=client.get('/api/v1/model-operations-dashboard/export/csv?days=7');assert csv_response.status_code==200 and 'demo/m1' not in csv_response.text and 'provider,model,capability' in csv_response.text
        json_response=client.get('/api/v1/model-operations-dashboard/export/json?days=7');assert json_response.status_code==200 and json_response.json()['truthfulness']['provider_invoice'] is False
        identity['user']=student;assert client.get('/api/v1/model-operations-dashboard').status_code==403
    finally:app.dependency_overrides.pop(get_current_user,None)
