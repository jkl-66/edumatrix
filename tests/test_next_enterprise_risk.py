import json
from datetime import datetime, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.auth import get_current_user, get_password_hash
from app.database import Base,DBCertification,DBEnterpriseRiskDecision,DBEnterpriseRiskReport,DBOrganization,DBOrganizationMembership,DBRetrainingTask,DBTrainingAssignment,DBTrainingCohort,DBTrainingProgram,DBUser
from app.enterprise_risk import EnterpriseRiskError,build_snapshot,create_report,decide,payload,workspace
from app.main import app
import app.enterprise_risk_api as risk_api

NOW=datetime(2026,8,4,12,0,0)
def fixture(count=3):
 e=create_engine('sqlite:///:memory:',connect_args={'check_same_thread':False},poolclass=StaticPool);Base.metadata.create_all(e);db=sessionmaker(bind=e)()
 admin=DBUser(public_id='risk-admin',username='risk-admin',hashed_password=get_password_hash('pw'),role='admin',display_name='Admin');outsider=DBUser(public_id='risk-outsider',username='risk-outsider',hashed_password=get_password_hash('pw'),role='teacher',display_name='Out');org=DBOrganization(id='risk-org',name='合成企业',organization_type='enterprise');other=DBOrganization(id='other-org',name='其他组织',organization_type='enterprise');db.add_all([admin,outsider,org,other]);db.flush();db.add_all([DBOrganizationMembership(organization_id=org.id,user_public_id=admin.public_id,role='admin'),DBOrganizationMembership(organization_id=other.id,user_public_id=outsider.public_id,role='admin')]);db.flush()
 program=DBTrainingProgram(id='risk-program',organization_id=org.id,target_job_level_id='demo-level',title='演示培训',version='1');cohort=DBTrainingCohort(id='risk-cohort',organization_id=org.id,training_program_id=program.id,standard_snapshot={'version':'1'});db.add_all([program,cohort]);db.flush();learners=[]
 for index in range(count):
  user=DBUser(public_id=f'risk-learner-{index}',username=f'risk-learner-{index}',hashed_password=get_password_hash('pw'),role='student',display_name=f'Learner {index}');db.add(user);db.flush();db.add(DBOrganizationMembership(organization_id=org.id,user_public_id=user.public_id,role='learner'));assignment=DBTrainingAssignment(id=f'risk-assignment-{index}',organization_id=org.id,cohort_id=cohort.id,learner_public_id=user.public_id,assignment_source='organization',status='completed' if index==0 else 'assigned',assigned_at=NOW-timedelta(days=20));db.add(assignment);learners.append(user)
  if index==0:db.add(DBCertification(id='risk-cert-0',organization_id=org.id,learner_public_id=user.public_id,job_level_id='demo-level',standard_snapshot={'version':'1'},status='active',issued_at=NOW-timedelta(days=10),expires_at=NOW+timedelta(days=30)))
  if index==1:db.add(DBRetrainingTask(id='risk-task-1',certification_id='missing-cert',organization_id=org.id,learner_public_id=user.public_id,trigger_type='expired',trigger_key='risk',title='复训',due_at=NOW-timedelta(days=2),status='assigned',created_at=NOW-timedelta(days=10)))
 db.commit();return db,admin,outsider,org,learners

def test_small_sample_suppresses_values_and_drilldown():
 db,admin,_,org,learners=fixture(2);snap=build_snapshot(db,actor=admin,organization_id=org.id,period_start=NOW-timedelta(days=30),period_end=NOW)
 assert snap['privacy']['sample_state']=='suppressed' and snap['learners']==[] and snap['risks']==[]
 assert all(row['value'] is None and row['numerator'] is None and row['denominator'] is None for row in snap['metrics'])
 assert not any(user.public_id in json.dumps(snap) for user in learners)

def test_sufficient_sample_uses_unlinkable_aliases_and_explainable_metrics():
 db,admin,_,org,learners=fixture(3);snap=build_snapshot(db,actor=admin,organization_id=org.id,period_start=NOW-timedelta(days=30),period_end=NOW)
 assert snap['privacy']=={'minimum_sample':3,'population_size':3,'sample_state':'sufficient','raw_identity_fields_included':False,'pseudonyms_linkable_across_reports':False}
 aliases=[row['learner_alias'] for row in snap['learners']];assert len(set(aliases))==3 and all(x.startswith('EMP-') for x in aliases)
 encoded=json.dumps(snap,ensure_ascii=False);assert not any(user.public_id in encoded or user.username in encoded for user in learners)
 metrics={row['key']:row for row in snap['metrics']};assert metrics['training_completion_rate']['value']==0.3333;assert metrics['active_certification_coverage']['value']==0.3333;assert metrics['overdue_retraining_rate']['value']==1.0
 assert all(row['formula'] and row['sources'] and row['threshold_basis'] for row in snap['metrics'])
 assert all('不得据此自动' in risk['recommendation'] for risk in snap['risks'])

def test_report_is_idempotent_and_decisions_are_append_only():
 db,admin,_,org,_=fixture();start=NOW-timedelta(days=30);row,created=create_report(db,actor=admin,organization_id=org.id,period_start=start,period_end=NOW);same,again=create_report(db,actor=admin,organization_id=org.id,period_start=start,period_end=NOW);assert created and not again and row.id==same.id
 decide(db,actor=admin,report_id=row.id,action='acknowledge',reason='已核对风险来源和演示阈值',expected_version=1);decide(db,actor=admin,report_id=row.id,action='close',reason='已完成人工跟进并保留责任记录',expected_version=2);db.commit();assert row.status=='closed' and db.query(DBEnterpriseRiskDecision).count()==2
 with pytest.raises(EnterpriseRiskError) as stale:decide(db,actor=admin,report_id=row.id,action='close',reason='重复关闭',expected_version=2)
 assert stale.value.code=='enterprise_risk_stale'

def test_learner_and_other_organization_are_forbidden():
 db,admin,outsider,org,learners=fixture()
 with pytest.raises(EnterpriseRiskError) as learner:workspace(db,actor=learners[0],organization_id=org.id)
 with pytest.raises(EnterpriseRiskError) as other:workspace(db,actor=outsider,organization_id=org.id)
 assert learner.value.code==other.value.code=='enterprise_risk_forbidden'

def test_http_report_and_decision(monkeypatch):
 db,admin,_,org,learners=fixture();identity={'user':learners[0]}
 async def fake(operation):return operation(db)
 monkeypatch.setattr(risk_api,'run_db_op',fake);app.dependency_overrides[get_current_user]=lambda:identity['user'];client=TestClient(app)
 try:
  assert client.get('/api/v1/enterprise-risk/workspace',params={'organization_id':org.id}).status_code==403
  identity['user']=admin;made=client.post('/api/v1/enterprise-risk/reports',json={'organization_id':org.id,'period_start':(NOW-timedelta(days=30)).isoformat()+'Z','period_end':NOW.isoformat()+'Z'});assert made.status_code==201,made.text;report=made.json()['report'];done=client.post(f"/api/v1/enterprise-risk/reports/{report['id']}/decisions",json={'action':'acknowledge','reason':'主管已核对演示风险','expected_version':1});assert done.status_code==200 and done.json()['status']=='acknowledged'
 finally:app.dependency_overrides.pop(get_current_user,None)
