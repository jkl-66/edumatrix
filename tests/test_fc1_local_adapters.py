from fastapi.testclient import TestClient
from sqlalchemy.exc import DatabaseError
from app.main import app
from app.database import DBLocalAdapterEvent,SessionLocal
from tests.api_test_helpers import auth_headers

P={'confidence_threshold':0.65,'inspection_rate':80,'buffer_size':50}
def act(c,h,s,a,key,**kw):return c.post(f"/api/v1/local-adapters/{s['id']}/actions",headers=h,json={'action':a,'expected_lock_version':s['lock_version'],'idempotency_key':key,'parameters':kw.get('parameters'),'fault_type':kw.get('fault_type','none'),'diagnosis':kw.get('diagnosis',''),'recovery_action':kw.get('recovery_action','')})
def create(c,h):
 r=c.post('/api/v1/local-adapters',headers=h,json={'title':'视觉质检技能训练','adapter_id':'vision-quality-line-v1','credential_placeholder':'DEMO-LOCAL-ONLY','parameters':P});assert r.status_code==201,r.text;return r.json()
def test_fault_recovery_hidden_acceptance_and_refresh():
 with TestClient(app) as c:
  h=auth_headers(c,'fc1_009_flow');s=create(c,h);s=act(c,h,s,'connect','connect-001').json();s=act(c,h,s,'inject_fault','fault-001',fault_type='sensor_timeout').json();s=act(c,h,s,'run','run-fail-001').json();assert s['status']=='failed'
  bad=act(c,h,s,'diagnose','diagnose-bad',diagnosis='检查通道',recovery_action='recalibrate_threshold').json();assert bad['status']=='diagnosed' and not bad['recovery_verified'];assert act(c,h,bad,'recover','recover-bad').status_code==422
  s=act(c,h,bad,'reset','reset-001').json();s=act(c,h,s,'connect','connect-002').json();s=act(c,h,s,'inject_fault','fault-002',fault_type='sensor_timeout').json();s=act(c,h,s,'run','run-fail-002').json();s=act(c,h,s,'diagnose','diagnose-good',diagnosis='传感器通道超时',recovery_action='restart_sensor_channel').json();s=act(c,h,s,'recover','recover-good').json();s=act(c,h,s,'rerun','rerun-good').json();s=act(c,h,s,'submit','submit-good').json();assert s['status']=='passed' and s['hidden_acceptance']['passed'];assert s['metrics']['deterministic'] is True
  restored=c.get(f"/api/v1/local-adapters/{s['id']}",headers=h).json();assert restored['status']=='passed' and len(restored['events'])>=10
def test_placeholder_owner_idempotency_and_immutable_event():
 with TestClient(app) as c:
  owner=auth_headers(c,'fc1_009_owner');other=auth_headers(c,'fc1_009_other')
  bad=c.post('/api/v1/local-adapters',headers=owner,json={'title':'bad','adapter_id':'vision-quality-line-v1','credential_placeholder':'real-secret','parameters':P});assert bad.status_code==422
  s=create(c,owner);r=act(c,owner,s,'connect','idem-connect');assert r.status_code==200;replay=act(c,owner,s,'connect','idem-connect');assert replay.status_code==200 and replay.json()['action_created'] is False
  assert c.get(f"/api/v1/local-adapters/{s['id']}",headers=other).status_code==403
  eid=r.json()['events'][0]['id']
 with SessionLocal() as db:
  e=db.get(DBLocalAdapterEvent,eid);e.action='reset'
  try:db.commit();raise AssertionError('immutable trigger missing')
  except DatabaseError:db.rollback()
