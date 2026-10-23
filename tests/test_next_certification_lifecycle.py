from datetime import datetime,timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.auth import get_current_user,get_password_hash
from app.certification_lifecycle import CertificationLifecycleError,mark_read,revoke,scan,workspace
from app.database import Base,DBCertification,DBCertificationLifecycleEvent,DBJobFamily,DBJobLevel,DBLocalNotification,DBOrganization,DBOrganizationMembership,DBRetrainingTask,DBUser
from app.main import app
import app.certification_lifecycle_api as lifecycle_api

NOW=datetime(2026,8,4,3,0)
def fixture():
 engine=create_engine('sqlite:///:memory:',connect_args={'check_same_thread':False},poolclass=StaticPool);Base.metadata.create_all(engine);db=sessionmaker(bind=engine)()
 manager=DBUser(public_id='cl-manager',username='cl-manager',hashed_password=get_password_hash('pw'),role='teacher');learner=DBUser(public_id='cl-learner',username='cl-learner',hashed_password=get_password_hash('pw'),role='student');other=DBUser(public_id='cl-other',username='cl-other',hashed_password=get_password_hash('pw'),role='student');org=DBOrganization(id='cl-org',name='Demo Org');db.add_all([manager,learner,other,org]);db.flush();db.add_all([DBOrganizationMembership(organization_id=org.id,user_public_id=manager.public_id,role='admin'),DBOrganizationMembership(organization_id=org.id,user_public_id=learner.public_id,role='learner'),DBOrganizationMembership(organization_id=org.id,user_public_id=other.public_id,role='learner')]);family=DBJobFamily(id='cl-family',organization_id=org.id,code='RAG',title='RAG');db.add(family);db.flush();level=DBJobLevel(id='cl-level',job_family_id=family.id,level_code='L2',version='1',title='RAG Engineer');db.add(level);db.flush();cert=DBCertification(id='cl-cert',organization_id=org.id,learner_public_id=learner.public_id,job_level_id=level.id,standard_snapshot={'version':'demo'},evidence_ids=['ev-1'],issuer_public_id=manager.public_id,status='active',issued_at=NOW-timedelta(days=300),expires_at=NOW-timedelta(days=1),retraining_rule={'completion_days':14});soon=DBCertification(id='cl-soon',organization_id=org.id,learner_public_id=other.public_id,job_level_id=level.id,standard_snapshot={'version':'demo'},evidence_ids=['ev-2'],issuer_public_id=manager.public_id,status='active',issued_at=NOW-timedelta(days=300),expires_at=NOW+timedelta(days=10),retraining_rule={});db.add_all([cert,soon]);db.commit();return db,engine,manager,learner,other,cert,soon
def test_revoke_is_versioned_audited_and_creates_single_retraining_notice():
 db,_,manager,learner,_,cert,_=fixture();cert.expires_at=NOW+timedelta(days=20);db.commit();row,event,task=revoke(db,actor=manager,certification_id=cert.id,reason='岗位标准重大变更，安排复训',expected_version=1,now=NOW);db.commit();assert row.status=='revoked' and row.lock_version==2 and event.actor_role=='admin' and len(event.reason_hash)==64;assert task.trigger_type=='revoked' and task.due_at==NOW+timedelta(days=14);notice=db.query(DBLocalNotification).one();assert notice.owner_public_id==learner.public_id and notice.delivery_channel=='local_inbox'
 with pytest.raises(CertificationLifecycleError):revoke(db,actor=manager,certification_id=cert.id,reason='duplicate revoke',expected_version=1,now=NOW)
 assert db.query(DBRetrainingTask).count()==1 and db.query(DBCertificationLifecycleEvent).count()==1
def test_expiry_scan_and_upcoming_notice_are_idempotent():
 db,_,manager,_,_,cert,soon=fixture();first=scan(db,actor=manager,organization_id='cl-org',now=NOW);db.commit();second=scan(db,actor=manager,organization_id='cl-org',now=NOW);db.commit();assert first=={'expired':1,'upcoming_notified':1,'retraining_created':1,'notifications_created':2};assert second=={'expired':0,'upcoming_notified':0,'retraining_created':0,'notifications_created':0};assert cert.status=='expired' and soon.status=='active';assert db.query(DBRetrainingTask).count()==1 and db.query(DBLocalNotification).count()==2
def test_learner_scope_and_notification_owner():
 db,_,manager,learner,other,_,_=fixture();scan(db,actor=manager,organization_id='cl-org',now=NOW);db.commit();view=workspace(db,actor=learner,organization_id='cl-org');assert len(view['certifications'])==1 and all(n['type']=='certification_expired' for n in view['notifications']);notice=db.query(DBLocalNotification).filter_by(owner_public_id=learner.public_id).one();assert mark_read(db,actor=learner,notice_id=notice.id).read_at is not None
 with pytest.raises(CertificationLifecycleError) as exc:mark_read(db,actor=other,notice_id=notice.id)
 assert exc.value.code=='notification_forbidden'
def test_api_and_immutable_event_trigger(monkeypatch):
 db,engine,manager,learner,_,cert,_=fixture();identity={'user':manager}
 with engine.begin() as c:c.exec_driver_sql("CREATE TRIGGER IF NOT EXISTS trg_cert_lifecycle_event_no_update BEFORE UPDATE ON certification_lifecycle_events BEGIN SELECT RAISE(ABORT, 'certification lifecycle event is immutable'); END")
 async def fake(op):return op(db)
 monkeypatch.setattr(lifecycle_api,'run_db_op',fake);app.dependency_overrides[get_current_user]=lambda:identity['user'];client=TestClient(app)
 try:
  scanned=client.post('/api/v1/certification-lifecycle/scan',json={'organization_id':'cl-org','upcoming_days':30});assert scanned.status_code==200 and scanned.json()['expired']==1
  identity['user']=learner;view=client.get('/api/v1/certification-lifecycle/workspace?organization_id=cl-org');assert view.status_code==200 and len(view.json()['certifications'])==1
  notice_id=view.json()['notifications'][0]['id'];assert client.post(f'/api/v1/certification-lifecycle/notifications/{notice_id}/read').status_code==200
 finally:app.dependency_overrides.pop(get_current_user,None)
 with pytest.raises(DatabaseError):db.query(DBCertificationLifecycleEvent).update({'reason':'tampered'})
