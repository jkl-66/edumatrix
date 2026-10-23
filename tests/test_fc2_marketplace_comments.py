from datetime import datetime, timedelta
import app.marketplace as marketplace
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from app.database import DBMarketplaceComment,DBMarketplaceCommentEvent,DBMarketplaceCommentReport,DBMarketplaceListing,SessionLocal
from app.main import app
from tests.api_test_helpers import auth_headers
from tests.test_next_marketplace import fixture,login,publish,submit

@pytest.fixture(autouse=True)
def withdraw_created_listings():
 with SessionLocal() as db:before={row[0] for row in db.query(DBMarketplaceListing.id).all()}
 yield
 with SessionLocal() as db:
  rows=db.query(DBMarketplaceListing).filter(~DBMarketplaceListing.id.in_(before or {'__none__'})).all()
  for row in rows:row.status='withdrawn';row.withdrawn_at=marketplace._now()
  db.commit()

def test_version_binding_edit_window_soft_delete_and_new_listing_isolation(monkeypatch):
 with TestClient(app) as c:
  (teacher,admin,learner),cid=fixture(c,'fc2_comments');row=publish(c,admin,submit(c,teacher,cid))
  created=c.post(f"/api/v1/marketplace/listings/{row['id']}/comments",headers=learner,json={'body':'课程结构清晰，来源说明完整。'});assert created.status_code==201,created.text;comment=created.json();assert comment['course_version']=='1' and comment['listing_snapshot_hash']==row['snapshot_hash'] and comment['can_edit']
  edited=c.put(f"/api/v1/marketplace/comments/{comment['id']}",headers=learner,json={'body':'课程结构清晰，实验步骤也很完整。','expected_version':1});assert edited.status_code==200;comment=edited.json();assert comment['lock_version']==2 and len(comment['events'])==2
  assert c.put(f"/api/v1/marketplace/comments/{comment['id']}",headers=teacher,json={'body':'越权编辑','expected_version':2}).status_code==403
  deadline=datetime.fromisoformat(comment['edit_deadline']);monkeypatch.setattr(marketplace,'_now',lambda:deadline+timedelta(seconds=1))
  assert c.put(f"/api/v1/marketplace/comments/{comment['id']}",headers=learner,json={'body':'窗口外编辑','expected_version':2}).status_code==422
  deleted=c.request('DELETE',f"/api/v1/marketplace/comments/{comment['id']}",headers=learner,json={'expected_version':2});assert deleted.status_code==200 and deleted.json()['status']=='deleted'
  listed=c.get(f"/api/v1/marketplace/listings/{row['id']}/comments",headers=learner).json();assert listed['items'][0]['status']=='deleted' and listed['items'][0]['course_version']=='1'
  with SessionLocal() as db:
   assert db.query(DBMarketplaceCommentEvent).filter_by(comment_id=comment['id']).count()==3
   bound=db.get(DBMarketplaceComment,comment['id']);bound.listing_snapshot_hash='x'*64
   with pytest.raises(DatabaseError,match='immutable'):db.commit()
   db.rollback()

def test_report_teacher_moderation_admin_restore_and_permissions():
 with TestClient(app) as c:
  (teacher,admin,learner),cid=fixture(c,'fc2_moderate');row=publish(c,admin,submit(c,teacher,cid));other=auth_headers(c,'fc2_comment_reporter')
  comment=c.post(f"/api/v1/marketplace/listings/{row['id']}/comments",headers=learner,json={'body':'这是一条待举报评论。'}).json()
  report=c.post(f"/api/v1/marketplace/comments/{comment['id']}/reports",headers=other,json={'category':'accuracy','description':'内容可能误导，请发布教师复核。'});assert report.status_code==201
  assert c.post(f"/api/v1/marketplace/comments/{comment['id']}/reports",headers=learner,json={'category':'other','description':'不能举报自己'}).status_code==422
  assert c.post(f"/api/v1/marketplace/comments/{comment['id']}/moderation",headers=other,json={'action':'hide','reason':'越权隐藏','expected_version':1}).status_code==403
  hidden=c.post(f"/api/v1/marketplace/comment-reports/{report.json()['id']}/decisions",headers=teacher,json={'action':'hide','reason':'发布教师核实后隐藏','expected_version':1});assert hidden.status_code==200 and hidden.json()['comment']['status']=='hidden'
  restored=c.post(f"/api/v1/marketplace/comments/{comment['id']}/moderation",headers=admin,json={'action':'restore','reason':'管理员复核后恢复','expected_version':2});assert restored.status_code==200 and restored.json()['status']=='active'
  outsider=c.get(f"/api/v1/marketplace/listings/{row['id']}/comments",headers=other).json()['items'][0];assert outsider['body'] and outsider['events']==[] and outsider['reports']==[]
  with SessionLocal() as db:
   event=db.query(DBMarketplaceCommentEvent).filter_by(comment_id=comment['id']).first();event.reason='tamper'
   with pytest.raises(DatabaseError,match='immutable'):db.commit()
   db.rollback();rep=db.query(DBMarketplaceCommentReport).filter_by(comment_id=comment['id']).one();assert rep.evidence_snapshot['listing_snapshot_hash']==row['snapshot_hash']
