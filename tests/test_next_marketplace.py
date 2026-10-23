from __future__ import annotations
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from app.database import (DBCourse,DBCourseDocument,DBCourseMembership,DBMarketplaceAcquisition,
    DBMarketplaceDecision,DBMarketplaceListing,DBMarketplaceReport,DBSourceDocument,DBUser,SessionLocal)
from app.main import app
from tests.api_test_helpers import TEST_PASSWORD,auth_headers

def login(c,n):
 r=c.post('/api/auth/login',data={'username':n,'password':TEST_PASSWORD});return {'Authorization':'Bearer '+r.json()['access_token']}
def fixture(c,s):
 names=[f'market_{x}_{s}' for x in ('teacher','admin','learner')]
 for n in names:auth_headers(c,n)
 with SessionLocal() as db:db.query(DBUser).filter_by(username=names[0]).update({'role':'teacher'});db.query(DBUser).filter_by(username=names[1]).update({'role':'admin'});db.commit()
 hs=[login(c,n) for n in names]
 with SessionLocal() as db:
  teacher=db.query(DBUser).filter_by(username=names[0]).one();cid=f'market-course-{s}'
  db.add(DBCourse(id=cid,version='1',title='AI 可信训练',subject='AI',description='公开课程说明',content_origin='https://example.invalid',license_text='CC BY 4.0',visibility='private',status='published',owner_public_id=teacher.public_id,manifest_version='m1',manifest_data={'commit':'abc'}))
  db.add(DBCourseMembership(course_id=cid,user_public_id=teacher.public_id,role='teacher',status='active'))
  db.add(DBCourseDocument(id=f'md-{s}',course_id=cid,chapter_order=1,filename='a.md',title='A',content='正文',content_hash='h1',license_text='CC BY 4.0'))
  db.add(DBSourceDocument(id=f'ms-{s}',course_id=cid,title='A',filename='a.md',file_format='md',content_hash='h1',source_sha256='s1',processed_sha256='p1',license_text='CC BY 4.0',processing_status='ready'));db.commit()
 return hs,cid
def submit(c,h,cid):
 r=c.post('/api/v1/marketplace/listings',headers=h,json={'course_id':cid,'title':f'AI 可信训练公开版 · {cid}','summary':'用于公开学习的可信训练课程','category':'人工智能','tags':['AI','可信']});assert r.status_code==201,r.text;return r.json()
def publish(c,admin,row):
 row=c.post(f"/api/v1/marketplace/listings/{row['id']}/decisions",headers=admin,json={'action':'approve','reason':'来源许可与内容证据通过审核','expected_version':row['lock_version']}).json()
 return c.post(f"/api/v1/marketplace/listings/{row['id']}/decisions",headers=admin,json={'action':'publish','reason':'批准进入公共学习市场展示','expected_version':row['lock_version']}).json()

def test_review_public_search_and_acquisition_preserve_license():
 with TestClient(app) as c:
  (teacher,admin,learner),cid=fixture(c,'flow');row=submit(c,teacher,cid)
  public_ids={item['id'] for item in c.get('/api/v1/marketplace/public',headers=learner).json()['items']}
  assert row['id'] not in public_ids
  assert c.post(f"/api/v1/marketplace/listings/{row['id']}/decisions",headers=teacher,json={'action':'approve','reason':'教师不能自行完成公开审核','expected_version':row['lock_version']}).status_code==403
  row=publish(c,admin,row);items=c.get('/api/v1/marketplace/public',headers=learner,params={'q':cid,'tag':'AI'}).json()['items'];assert len(items)==1 and items[0]['license']['course_license']=='CC BY 4.0'
  acq=c.post(f"/api/v1/marketplace/listings/{row['id']}/acquisitions",headers=learner);assert acq.status_code==201
  acquired_id=acq.json()['derived_course_id']
  assert c.post('/api/v1/marketplace/listings',headers=learner,json={'course_id':acquired_id,'title':'循环发布','summary':'学习者不得把获取副本重新提交市场','category':'人工智能','tags':['AI']}).status_code==403
  assert c.get('/api/v1/marketplace/workspace',headers=learner).json()['manageable_courses']==[]
  with SessionLocal() as db:
   course=db.get(DBCourse,acq.json()['derived_course_id']);assert course.title.endswith('（市场副本）') and course.license_text=='CC BY 4.0'

def test_report_dismiss_or_withdraw_has_immutable_evidence_and_non_destructive_impact():
 with TestClient(app) as c:
  (teacher,admin,learner),cid=fixture(c,'report');row=publish(c,admin,submit(c,teacher,cid));acq=c.post(f"/api/v1/marketplace/listings/{row['id']}/acquisitions",headers=learner).json()
  report=c.post(f"/api/v1/marketplace/listings/{row['id']}/reports",headers=learner,json={'category':'license','description':'请人工复核许可证与来源署名完整性'});assert report.status_code==201
  assert c.post(f"/api/v1/marketplace/reports/{report.json()['id']}/decisions",headers=teacher,json={'action':'withdraw','reason':'教师不能处置公共市场举报','expected_version':1}).status_code==403
  resolved=c.post(f"/api/v1/marketplace/reports/{report.json()['id']}/decisions",headers=admin,json={'action':'withdraw','reason':'人工复核后决定下架并保留历史','expected_version':1});assert resolved.status_code==200
  public_ids={item['id'] for item in c.get('/api/v1/marketplace/public',headers=learner).json()['items']}
  assert row['id'] not in public_ids
  assert c.post(f"/api/v1/marketplace/listings/{row['id']}/acquisitions",headers=learner).status_code==422
  with SessionLocal() as db:
   assert db.get(DBCourse,acq['derived_course_id']).status=='published'
   assert db.query(DBMarketplaceAcquisition).filter_by(id=acq['id']).one().source_status=='withdrawn'
   assert db.query(DBMarketplaceDecision).filter_by(listing_id=row['id']).count()==4

def test_stale_transitions_and_database_immutability_fail_closed():
 with TestClient(app) as c:
  (teacher,admin,_),cid=fixture(c,'security');row=submit(c,teacher,cid)
  assert c.post(f"/api/v1/marketplace/listings/{row['id']}/decisions",headers=admin,json={'action':'approve','reason':'使用陈旧版本执行审核操作','expected_version':99}).status_code==409
 with SessionLocal() as db:
  listing=db.query(DBMarketplaceListing).first();decision=db.query(DBMarketplaceDecision).first();assert listing and decision
  with pytest.raises(DatabaseError):db.execute(text("update marketplace_listings set title='x' where id=:id"),{'id':listing.id});db.commit()
  db.rollback()
  with pytest.raises(DatabaseError):db.execute(text("delete from marketplace_decisions where id=:id"),{'id':decision.id});db.commit()
  db.rollback()
