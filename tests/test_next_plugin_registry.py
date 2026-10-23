import shutil
from pathlib import Path
from fastapi.testclient import TestClient
from app.database import DBDomainPack,DBDomainVersion,DBPluginLifecycleEvent,DBPluginRegistration,DBUser,SessionLocal
from app.main import app
from app.plugin_registry import ROOT
from app.m1_object_service import OBJECT_SPECS
from tests.api_test_helpers import TEST_PASSWORD,auth_headers

def login(client,name,role=None):
 auth_headers(client,name)
 if role:
  with SessionLocal() as db:db.query(DBUser).filter_by(username=name).update({'role':role});db.commit()
 row=client.post('/api/auth/login',data={'username':name,'password':TEST_PASSWORD})
 return {'Authorization':'Bearer '+row.json()['access_token']}

def test_admin_installs_and_disables_verified_data_plugin_with_history():
 with TestClient(app) as client:
  admin=login(client,'plugin_admin','admin');student=login(client,'plugin_student')
  catalog=client.get('/api/v1/plugins',headers=student);assert catalog.status_code==200
  plugin=next(x for x in catalog.json()['items'] if x['plugin_id']=='robotics-skill-demo')
  assert plugin['status']=='available' and plugin['allowed_actions']==['validate_data','register_domain']
  assert client.post('/api/v1/plugins/robotics-skill-demo/install',headers=student).status_code==403
  installed=client.post('/api/v1/plugins/robotics-skill-demo/install',headers=admin);assert installed.status_code==200,installed.text
  row=installed.json();assert row['status']=='installed' and len(row['verification']['verified_assets'])==2
  with SessionLocal() as db:
   reg=db.query(DBPluginRegistration).filter_by(plugin_id='robotics-skill-demo').one();pack=db.get(DBDomainPack,reg.domain_pack_id);version=db.get(DBDomainVersion,pack.current_version_id)
   assert pack.status=='active' and version.content_hash==reg.package_hash
  disabled=client.post('/api/v1/plugins/robotics-skill-demo/uninstall',headers=admin,json={'expected_version':row['lock_version']});assert disabled.status_code==200
  assert disabled.json()['status']=='disabled' and len(disabled.json()['events'])==2
  with SessionLocal() as db:assert db.query(DBDomainVersion).count()>=1 and db.query(DBPluginLifecycleEvent).filter_by(plugin_id='robotics-skill-demo').count()==2

def test_tampered_bundled_plugin_fails_in_isolation_and_records_event():
 source=ROOT/'robotics-skill-demo';target=ROOT/'robotics-tamper-demo'
 if target.exists():shutil.rmtree(target)
 shutil.copytree(source,target)
 try:
  manifest=(target/'plugin.json').read_text(encoding='utf-8').replace('robotics-skill-demo','robotics-tamper-demo')
  (target/'plugin.json').write_text(manifest,encoding='utf-8');(target/'chapters.json').write_text('{"tampered":true}',encoding='utf-8')
  with TestClient(app) as client:
   admin=login(client,'plugin_tamper_admin','admin');response=client.post('/api/v1/plugins/robotics-tamper-demo/install',headers=admin)
   assert response.status_code==422
   with SessionLocal() as db:
    assert db.query(DBPluginRegistration).filter_by(plugin_id='robotics-tamper-demo').count()==0
    event=db.query(DBPluginLifecycleEvent).filter_by(plugin_id='robotics-tamper-demo').one();assert event.outcome=='failed'
 finally:
  if target.exists():shutil.rmtree(target)

def test_plugin_objects_are_registered_in_uniform_gateway():
 assert {'plugin_registration','plugin_lifecycle_event'}<=set(OBJECT_SPECS)
