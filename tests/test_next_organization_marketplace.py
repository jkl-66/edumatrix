from fastapi.testclient import TestClient
from app.database import DBCourse,DBCourseDocument,DBCourseMembership,DBOrganization,DBOrganizationMembership,DBOrganizationResourceAcquisition,DBSourceDocument,DBUser,SessionLocal
from app.main import app
from tests.api_test_helpers import TEST_PASSWORD,auth_headers
def login(c,n):
 r=c.post('/api/auth/login',data={'username':n,'password':TEST_PASSWORD});return {'Authorization':'Bearer '+r.json()['access_token']}
def fixture(c,s):
 ns=[f'orgm_{x}_{s}' for x in ('manager','learner','outsider')]
 for n in ns:auth_headers(c,n)
 with SessionLocal() as d:d.query(DBUser).filter_by(username=ns[0]).update({'role':'teacher'});d.commit()
 hs=[login(c,n) for n in ns]
 with SessionLocal() as d:
  us=[d.query(DBUser).filter_by(username=n).one() for n in ns];o1=DBOrganization(name='合成企业甲',sharing_policy={'copy_enabled':True,'allowed_copy_roles':['learner','manager']});o2=DBOrganization(name='合成企业乙',sharing_policy={'copy_enabled':False,'allowed_copy_roles':['manager']});d.add_all([o1,o2]);d.flush()
  d.add_all([DBOrganizationMembership(organization_id=o1.id,user_public_id=us[0].public_id,role='manager',status='active'),DBOrganizationMembership(organization_id=o1.id,user_public_id=us[1].public_id,role='learner',status='active'),DBOrganizationMembership(organization_id=o2.id,user_public_id=us[2].public_id,role='manager',status='active')]);cid=f'orgm-course-{s}';d.add(DBCourse(id=cid,version='1',title='企业 AI 内训',subject='AI',description='合成内训',license_text='CC BY 4.0',visibility='private',status='published',owner_public_id=us[0].public_id,manifest_version='v1'));d.add(DBCourseMembership(course_id=cid,user_public_id=us[0].public_id,role='teacher',status='active'));d.add(DBCourseDocument(id=f'od-{s}',course_id=cid,chapter_order=1,filename='a.md',title='A',content='正文',content_hash='h',license_text='CC BY 4.0'));d.add(DBSourceDocument(id=f'os-{s}',course_id=cid,title='A',filename='a.md',file_format='md',content_hash='h',source_sha256='s',processed_sha256='p',license_text='CC BY 4.0',processing_status='ready'));d.commit();return hs,cid,o1.id,o2.id
def publish(c,h,cid,oid):
 r=c.post('/api/v1/organization-marketplace/listings',headers=h,json={'organization_id':oid,'course_id':cid,'title':'企业 AI 内训资源','summary':'组织内部可追溯学习资源','category':'转岗培训','tags':['AI']});assert r.status_code==201,r.text;return r.json()
def test_private_catalog_policy_copy_and_cross_tenant_rejection():
 with TestClient(app) as c:
  (manager,learner,outsider),cid,o1,o2=fixture(c,'flow');row=publish(c,manager,cid,o1)
  assert c.get(f'/api/v1/organization-marketplace/organizations/{o1}',headers=learner).status_code==200
  assert c.get(f'/api/v1/organization-marketplace/organizations/{o1}',headers=outsider).status_code==403
  acq=c.post(f"/api/v1/organization-marketplace/listings/{row['id']}/acquisitions",headers=learner);assert acq.status_code==201
  assert c.post(f"/api/v1/organization-marketplace/listings/{row['id']}/acquisitions",headers=outsider).status_code==403
  with SessionLocal() as d:assert d.get(DBCourse,acq.json()['derived_course_id']).license_text=='CC BY 4.0'
def test_frozen_policy_and_withdrawal_preserve_member_copy():
 with TestClient(app) as c:
  (manager,learner,outsider),cid,o1,o2=fixture(c,'withdraw');row=publish(c,manager,cid,o1);acq=c.post(f"/api/v1/organization-marketplace/listings/{row['id']}/acquisitions",headers=learner).json()
  with SessionLocal() as d:d.get(DBOrganization,o1).sharing_policy={'copy_enabled':False,'allowed_copy_roles':[]};d.commit()
  # Existing listing retains the publication-time policy snapshot.
  assert c.post(f"/api/v1/organization-marketplace/listings/{row['id']}/acquisitions",headers=learner).status_code==201
  assert c.post(f"/api/v1/organization-marketplace/listings/{row['id']}/withdraw",headers=outsider,json={'reason':'跨组织不得撤回私有资源','expected_version':1}).status_code==403
  out=c.post(f"/api/v1/organization-marketplace/listings/{row['id']}/withdraw",headers=manager,json={'reason':'组织管理员停止后续获取并保留历史','expected_version':1});assert out.status_code==200
  with SessionLocal() as d:
   assert d.get(DBCourse,acq['derived_course_id']).status=='published';assert d.query(DBOrganizationResourceAcquisition).filter_by(id=acq['id']).one().source_status=='withdrawn'
