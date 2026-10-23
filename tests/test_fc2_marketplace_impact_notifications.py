from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.database import (
    DBCourse, DBMarketplaceImpactEvent, DBMarketplaceImpactNotification,
    DBMarketplaceListing, SessionLocal,
)
from app.main import app
from tests.api_test_helpers import auth_headers
from tests.test_next_marketplace import fixture, publish, submit


@pytest.fixture(autouse=True)
def withdraw_created_listings():
    with SessionLocal() as db:
        before = {row[0] for row in db.query(DBMarketplaceListing.id).all()}
    yield
    with SessionLocal() as db:
        for row in db.query(DBMarketplaceListing).filter(~DBMarketplaceListing.id.in_(before or {"__none__"})).all():
            row.status = "withdrawn"
        db.commit()


def test_withdrawal_notifies_only_acquirer_and_preserves_local_copy():
    with TestClient(app) as client:
        (teacher, admin, learner), course_id = fixture(client, "fc2_notice_withdraw")
        outsider = auth_headers(client, "fc2_notice_outsider")
        listing = publish(client, admin, submit(client, teacher, course_id))
        acquisition = client.post(
            f"/api/v1/marketplace/listings/{listing['id']}/acquisitions", headers=learner,
        ).json()

        withdrawn = client.post(
            f"/api/v1/marketplace/listings/{listing['id']}/decisions", headers=admin,
            json={"action": "withdraw", "reason": "来源材料撤回，通知已获取用户保留历史副本", "expected_version": listing["lock_version"]},
        )
        assert withdrawn.status_code == 200, withdrawn.text
        inbox = client.get("/api/v1/marketplace/impact-notifications", headers=learner).json()
        assert inbox["unread_count"] == 1
        notice = inbox["items"][0]
        assert notice["type"] == "withdrawn" and notice["status"] == "unread"
        assert notice["delivery_channel"] == "local_inbox"
        assert "邮件" in inbox["boundary"] and "不宣称" in inbox["boundary"]
        assert client.get("/api/v1/marketplace/impact-notifications", headers=outsider).json()["items"] == []

        with SessionLocal() as db:
            assert db.get(DBCourse, acquisition["derived_course_id"]).status == "published"
            assert db.query(DBMarketplaceImpactEvent).filter_by(source_listing_id=listing["id"]).count() == 1
            assert db.query(DBMarketplaceImpactNotification).filter_by(owner_public_id=notice["id"]).count() == 0

        assert client.post(
            f"/api/v1/marketplace/impact-notifications/{notice['id']}", headers=outsider,
            json={"expected_version": notice["lock_version"]},
        ).status_code == 403
        read = client.post(
            f"/api/v1/marketplace/impact-notifications/{notice['id']}", headers=learner,
            json={"expected_version": notice["lock_version"]},
        )
        assert read.status_code == 200 and read.json()["status"] == "read"
        assert client.post(
            f"/api/v1/marketplace/impact-notifications/{notice['id']}", headers=learner,
            json={"expected_version": notice["lock_version"], "action": "keep_copy"},
        ).status_code == 409
        actioned = client.post(
            f"/api/v1/marketplace/impact-notifications/{notice['id']}", headers=learner,
            json={"expected_version": read.json()["lock_version"], "action": "keep_copy"},
        )
        assert actioned.status_code == 200 and actioned.json()["status"] == "actioned"
        assert actioned.json()["action"] == "keep_copy"


def test_new_version_and_license_change_generate_idempotent_targeted_impacts():
    with TestClient(app) as client:
        (teacher, admin, learner), course_id = fixture(client, "fc2_notice_versions")
        first = publish(client, admin, submit(client, teacher, course_id))
        client.post(f"/api/v1/marketplace/listings/{first['id']}/acquisitions", headers=learner)

        with SessionLocal() as db:
            course = db.get(DBCourse, course_id)
            course.version = "2.0"
            course.description = "重要修复后的第二版课程"
            db.commit()
        second = submit(client, teacher, course_id)
        second = client.post(
            f"/api/v1/marketplace/listings/{second['id']}/decisions", headers=admin,
            json={"action": "approve", "reason": "第二版内容与来源审核通过", "expected_version": second["lock_version"]},
        ).json()
        published_second = client.post(
            f"/api/v1/marketplace/listings/{second['id']}/decisions", headers=admin,
            json={"action": "publish", "reason": "重要错误已修复，建议已获取用户检查更新", "expected_version": second["lock_version"], "impact_kind": "severe_fix"},
        )
        assert published_second.status_code == 200
        notices = client.get("/api/v1/marketplace/impact-notifications", headers=learner).json()["items"]
        assert len(notices) == 1 and notices[0]["type"] == "severe_fix"
        assert notices[0]["target_listing_id"] == second["id"]
        assert f"listing={second['id']}" in notices[0]["source_route"]

        with SessionLocal() as db:
            event = db.query(DBMarketplaceImpactEvent).filter_by(source_listing_id=first["id"], target_listing_id=second["id"]).one()
            assert event.evidence_snapshot["historical_copies_deleted"] == 0
            count = db.query(DBMarketplaceImpactNotification).filter_by(impact_event_id=event.id).count()
            assert count == 1
            event.reason = "tamper"
            with pytest.raises(DatabaseError, match="immutable"):
                db.commit()
            db.rollback()
            notice = db.query(DBMarketplaceImpactNotification).filter_by(impact_event_id=event.id).one()
            notice.title = "tamper"
            with pytest.raises(DatabaseError, match="immutable"):
                db.commit()
            db.rollback()

        # A third listing with a changed frozen license is classified as a license impact,
        # even if the caller labels the release as a normal new version.
        client.post(f"/api/v1/marketplace/listings/{second['id']}/acquisitions", headers=learner)
        with SessionLocal() as db:
            course = db.get(DBCourse, course_id)
            course.version = "3.0"
            course.license_text = "CC BY-SA 4.0"
            db.commit()
        third = submit(client, teacher, course_id)
        third = client.post(
            f"/api/v1/marketplace/listings/{third['id']}/decisions", headers=admin,
            json={"action": "approve", "reason": "第三版许可证与来源已重新审核", "expected_version": third["lock_version"]},
        ).json()
        response = client.post(
            f"/api/v1/marketplace/listings/{third['id']}/decisions", headers=admin,
            json={"action": "publish", "reason": "许可证条款变化，请已获取用户重新检查", "expected_version": third["lock_version"], "impact_kind": "new_version"},
        )
        assert response.status_code == 200
        notices = client.get("/api/v1/marketplace/impact-notifications", headers=learner).json()["items"]
        assert {item["type"] for item in notices} == {"severe_fix", "license_changed"}

