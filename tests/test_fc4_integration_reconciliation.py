from __future__ import annotations
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,event,text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import app.integration_reconciliation_api as recon_api
from app.auth import get_current_user,get_password_hash
from app.database import Base,DBIntegrationDelivery,DBIntegrationReconciliationRun,DBIntegrationRepairDecision,DBOrganization,DBOrganizationMembership,DBUser
from app.main import app
from app.migrations import apply_registered_migrations

def _fixture():
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    @event.listens_for(engine,'connect')
    def fk(c,_):c.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine);apply_registered_migrations(engine);db=sessionmaker(bind=engine)()
    admin=DBUser(public_id='recon-admin',username='recon-admin',display_name='对账管理员',hashed_password=get_password_hash('pw'),role='admin')
    outsider=DBUser(public_id='recon-outsider',username='recon-outsider',display_name='外部用户',hashed_password=get_password_hash('pw'),role='student')
    org=DBOrganization(id='recon-org',name='冻结合成对账组织');db.add_all([admin,outsider,org]);db.flush();db.add(DBOrganizationMembership(organization_id=org.id,user_public_id=admin.public_id,role='admin'));db.flush()
    delivery=DBIntegrationDelivery(id='recon-dead-letter',organization_id=org.id,adapter_type='webhook',adapter_version='v1',destination_key='local',idempotency_key='recon-dead',source_object_type='webhook_event',source_object_id='event-1',payload={'id':'event-1'},payload_hash='a'*64,status='dead_letter',attempt_count=5,last_error_code='signature_invalid');db.add(delivery);db.commit();return db,admin,outsider,org,delivery
def _client(monkeypatch,db,user):
    async def fake(op):return op(db)
    monkeypatch.setattr(recon_api,'run_db_op',fake);app.dependency_overrides[get_current_user]=lambda:user;return TestClient(app)

def test_preview_is_read_only_and_run_is_hash_guarded_idempotent(monkeypatch):
    db,admin,_,org,_=_fixture();client=_client(monkeypatch,db,admin)
    try:
        before=db.query(DBIntegrationReconciliationRun).count();preview=client.get('/api/v1/integration-reconciliation/workspace',params={'organization_id':org.id});assert preview.status_code==200,preview.text
        body=preview.json()['selected']['preview'];assert body['write_performed'] is False and db.query(DBIntegrationReconciliationRun).count()==before
        assert any(x['key']=='delivery:recon-dead-letter' and 'requeue' in x['repair_actions'] for x in body['discrepancies'])
        stale=client.post('/api/v1/integration-reconciliation/runs',json={'organization_id':org.id,'run_key':'run-1','expected_preview_hash':'0'*64});assert stale.status_code==409 and stale.json()['detail']['code']=='reconciliation_preview_stale'
        created=client.post('/api/v1/integration-reconciliation/runs',json={'organization_id':org.id,'run_key':'run-1','expected_preview_hash':body['preview_hash']});assert created.status_code==201 and created.json()['created'] is True
        replay=client.post('/api/v1/integration-reconciliation/runs',json={'organization_id':org.id,'run_key':'run-1','expected_preview_hash':body['preview_hash']});assert replay.status_code==201 and replay.json()['created'] is False and replay.json()['id']==created.json()['id']
        run=db.query(DBIntegrationReconciliationRun).one();assert run.snapshot_hash==body['preview_hash'] and run.discrepancies==body['discrepancies']
    finally:app.dependency_overrides.pop(get_current_user,None)

def test_repair_requeues_only_frozen_dead_letter_and_uses_optimistic_lock(monkeypatch):
    db,admin,_,org,delivery=_fixture();client=_client(monkeypatch,db,admin)
    try:
        preview=client.get('/api/v1/integration-reconciliation/workspace',params={'organization_id':org.id}).json()['selected']['preview'];run=client.post('/api/v1/integration-reconciliation/runs',json={'organization_id':org.id,'run_key':'run-repair','expected_preview_hash':preview['preview_hash']}).json()
        repaired=client.post(f"/api/v1/integration-reconciliation/runs/{run['id']}/decisions",json={'discrepancy_key':'delivery:recon-dead-letter','action':'requeue','reason':'管理员确认本地接收端已恢复','expected_lock_version':1});assert repaired.status_code==201,repaired.text
        db.refresh(delivery);assert delivery.status=='pending' and delivery.attempt_count==5
        decision=db.query(DBIntegrationRepairDecision).one();assert decision.after_snapshot['status']=='pending' and decision.action=='requeue'
        duplicate=client.post(f"/api/v1/integration-reconciliation/runs/{run['id']}/decisions",json={'discrepancy_key':'delivery:recon-dead-letter','action':'requeue','reason':'重复执行应拒绝','expected_lock_version':2});assert duplicate.status_code==409 and duplicate.json()['detail']['code']=='reconciliation_discrepancy_already_decided'
        other=next(x for x in preview['discrepancies'] if x['key']!='delivery:recon-dead-letter')
        stale=client.post(f"/api/v1/integration-reconciliation/runs/{run['id']}/decisions",json={'discrepancy_key':other['key'],'action':'acknowledge','reason':'使用旧版本应拒绝','expected_lock_version':1});assert stale.status_code==409 and stale.json()['detail']['code']=='reconciliation_version_conflict'
    finally:app.dependency_overrides.pop(get_current_user,None)

def test_permissions_migration_and_immutable_snapshots(monkeypatch):
    db,_,outsider,org,_=_fixture();client=_client(monkeypatch,db,outsider)
    try:assert client.get('/api/v1/integration-reconciliation/workspace',params={'organization_id':org.id}).status_code==403
    finally:app.dependency_overrides.pop(get_current_user,None)
    with db.bind.begin() as c:
        assert c.execute(text("select count(*) from schema_migrations where version='20260805_053'")).scalar_one()==1
        triggers={x[0] for x in c.execute(text("select name from sqlite_master where type='trigger' and name like 'trg_%recon%' or type='trigger' and name like 'trg_integration_repair_%'"))};assert {'trg_reconciliation_identity_frozen','trg_integration_repair_no_update'}<=triggers
