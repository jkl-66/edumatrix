import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.auth import get_current_user,get_password_hash
from app.database import Base,DBMultilevelReviewDecision,DBOrganization,DBOrganizationMembership,DBUser
from app.main import app
from app.multilevel_review import MultilevelReviewError,decide,queue,submit
import app.multilevel_review_api as api
def fixture():
 e=create_engine('sqlite:///:memory:',connect_args={'check_same_thread':False},poolclass=StaticPool);Base.metadata.create_all(e);db=sessionmaker(bind=e)();users={}
 for key,role in [('author','learner'),('mentor','mentor'),('manager','manager'),('admin','admin'),('other','learner')]:users[key]=DBUser(public_id=f'mr-{key}',username=f'mr-{key}',hashed_password=get_password_hash('pw'),role='teacher' if role!='learner' else 'student');db.add(users[key])
 org=DBOrganization(id='mr-org',name='Review Org');db.add(org);db.flush()
 for key,role in [('author','learner'),('mentor','mentor'),('manager','manager'),('admin','admin')]:db.add(DBOrganizationMembership(organization_id=org.id,user_public_id=users[key].public_id,role=role))
 db.commit();return db,e,users
def test_three_levels_require_distinct_roles_and_accounts():
 db,_,u=fixture();case,created=submit(db,actor=u['author'],organization_id='mr-org',object_type='certification',object_id='cert-1',object_version='v1',evidence_snapshot={'evidence_ids':['e1']});assert created
 case=decide(db,actor=u['mentor'],case_id=case.id,action='approve',reason='一级证据检查通过',expected_version=1);assert case.status=='level2_pending'
 with pytest.raises(MultilevelReviewError):decide(db,actor=u['mentor'],case_id=case.id,action='approve',reason='不能重复批准',expected_version=2)
 case=decide(db,actor=u['manager'],case_id=case.id,action='approve',reason='二级风险复核通过',expected_version=2);case=decide(db,actor=u['admin'],case_id=case.id,action='approve',reason='最终演示签核通过',expected_version=3);db.commit();assert case.status=='signed' and len(queue(db,actor=u['author'],organization_id='mr-org')[0]['decisions'])==4
def test_self_review_return_and_new_version():
 db,_,u=fixture();case,_=submit(db,actor=u['author'],organization_id='mr-org',object_type='artifact',object_id='a1',object_version='v1',evidence_snapshot={})
 with pytest.raises(MultilevelReviewError):decide(db,actor=u['author'],case_id=case.id,action='approve',reason='self review',expected_version=1)
 case=decide(db,actor=u['mentor'],case_id=case.id,action='return',reason='证据来源需要补充',expected_version=1);assert case.status=='returned'
 same,created=submit(db,actor=u['author'],organization_id='mr-org',object_type='artifact',object_id='a1',object_version='v1',evidence_snapshot={});assert not created and same.id==case.id
 new,created=submit(db,actor=u['author'],organization_id='mr-org',object_type='artifact',object_id='a1',object_version='v2',evidence_snapshot={});assert created and new.id!=case.id
def test_api_outsider_and_immutable_decision(monkeypatch):
 db,e,u=fixture();identity={'user':u['author']}
 async def fake(fn):return fn(db)
 monkeypatch.setattr(api,'run_db_op',fake);app.dependency_overrides[get_current_user]=lambda:identity['user'];client=TestClient(app)
 try:
  made=client.post('/api/v1/multilevel-review/cases',json={'organization_id':'mr-org','object_type':'artifact','object_id':'a2','object_version':'v1','evidence_snapshot':{'hash':'abc'}});assert made.status_code==201
  identity['user']=u['other'];assert client.get('/api/v1/multilevel-review/queue?organization_id=mr-org').status_code==403
 finally:app.dependency_overrides.pop(get_current_user,None)
 with e.begin() as c:c.exec_driver_sql("CREATE TRIGGER IF NOT EXISTS trg_multilevel_decision_no_update BEFORE UPDATE ON multilevel_review_decisions BEGIN SELECT RAISE(ABORT, 'immutable'); END")
 with pytest.raises(DatabaseError):db.query(DBMultilevelReviewDecision).update({'reason':'tampered'})
