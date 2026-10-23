from __future__ import annotations
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,event,text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import app.integration_fault_drill_api as drill_api
from app.auth import get_current_user,get_password_hash
from app.database import Base,DBIntegrationDelivery,DBIntegrationFaultDrill,DBIntegrationFaultDrillStep,DBOrganization,DBOrganizationMembership,DBUser
from app.main import app
from app.migrations import apply_registered_migrations

def fixture():
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    @event.listens_for(engine,'connect')
    def fk(c,_):c.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine);apply_registered_migrations(engine);db=sessionmaker(bind=engine)()
    admin=DBUser(public_id='drill-admin',username='drill-admin',display_name='演练管理员',hashed_password=get_password_hash('pw'),role='admin')
    outsider=DBUser(public_id='drill-outsider',username='drill-outsider',display_name='外部用户',hashed_password=get_password_hash('pw'),role='student')
    org=DBOrganization(id='drill-org',name='冻结合成故障演练组织');db.add_all([admin,outsider,org]);db.flush();db.add(DBOrganizationMembership(organization_id=org.id,user_public_id=admin.public_id,role='admin'));db.commit();return db,admin,outsider,org
def client(monkeypatch,db,user):
    async def fake(op):return op(db)
    monkeypatch.setattr(drill_api,'run_db_op',fake);app.dependency_overrides[get_current_user]=lambda:user;return TestClient(app)

def test_all_seven_faults_preserve_authority_and_recover(monkeypatch):
    db,admin,_,org=fixture();c=client(monkeypatch,db,admin)
    try:
        created=c.post('/api/v1/integration-fault-drills/runs',json={'organization_id':org.id,'run_key':'seven-scenarios'});assert created.status_code==201,created.text;run=created.json();assert run['created'] is True
        duplicate=c.post('/api/v1/integration-fault-drills/runs',json={'organization_id':org.id,'run_key':'seven-scenarios'});assert duplicate.status_code==201 and duplicate.json()['created'] is False
        stale=c.post(f"/api/v1/integration-fault-drills/runs/{run['id']}/next",json={'expected_lock_version':99});assert stale.status_code==409 and stale.json()['detail']['code']=='fault_drill_version_conflict'
        for index in range(1,8):
            step=c.post(f"/api/v1/integration-fault-drills/runs/{run['id']}/next",json={'expected_lock_version':index});assert step.status_code==200,step.text;body=step.json();assert body['current_scenario']==index and body['authority_preserved'] is True
        ws=c.get('/api/v1/integration-fault-drills/workspace',params={'organization_id':org.id});assert ws.status_code==200;final=ws.json()['selected']['runs'][0];assert final['status']=='passed' and len(final['steps'])==7
        assert [x['scenario_key'] for x in final['steps']]==['duplicate','out_of_order','revocation','conflict','disconnect','timeout','dead_letter']
        assert all(x['outcome']=='passed' and x['authority_hash']==final['authority_before_hash'] for x in final['steps'])
        dead=final['steps'][-1];assert dead['after_snapshot']['status']=='dead_letter' and dead['after_snapshot']['ordinary_retry_blocked'] is True;assert dead['recovery_snapshot']['status']=='delivered' and dead['recovery_snapshot']['attempt_count']==6
        assert final['authority_before_hash']==final['authority_after_hash']
        assert db.query(DBIntegrationDelivery).filter_by(organization_id=org.id).count()==7
    finally:app.dependency_overrides.pop(get_current_user,None)

def test_permissions_migration_and_immutable_step(monkeypatch):
    db,admin,outsider,org=fixture();c=client(monkeypatch,db,outsider)
    try:assert c.get('/api/v1/integration-fault-drills/workspace',params={'organization_id':org.id}).status_code==403
    finally:app.dependency_overrides.pop(get_current_user,None)
    c=client(monkeypatch,db,admin)
    try:
        run=c.post('/api/v1/integration-fault-drills/runs',json={'organization_id':org.id,'run_key':'immutable'}).json();assert c.post(f"/api/v1/integration-fault-drills/runs/{run['id']}/next",json={'expected_lock_version':1}).status_code==200
    finally:app.dependency_overrides.pop(get_current_user,None)
    assert db.execute(text("select count(*) from schema_migrations where version='20260805_054'")).scalar_one()==1
    row=db.query(DBIntegrationFaultDrillStep).one();row.outcome='failed'
    try:db.commit();raise AssertionError('immutable step trigger missing')
    except DatabaseError:db.rollback()
    triggers={x[0] for x in db.execute(text("select name from sqlite_master where type='trigger' and name like 'trg_fault_drill%'")).all()};assert {'trg_fault_drill_identity_frozen','trg_fault_drill_step_no_update'}<=triggers
