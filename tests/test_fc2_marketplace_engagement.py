from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.database import (
    DBLearningEvent, DBMarketplaceFavorite, DBMarketplaceListing,
    DBMarketplaceReview, DBMarketplaceReviewEvent, DBUser, SessionLocal,
)
from app.identity import new_public_id
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


def test_favorite_is_separate_from_verified_use_review():
    with TestClient(app) as client:
        (teacher, admin, learner), course_id = fixture(client, "fc2_engagement_separate")
        listing = publish(client, admin, submit(client, teacher, course_id))

        favorite = client.put(
            f"/api/v1/marketplace/listings/{listing['id']}/favorite",
            headers=learner, json={"active": True},
        )
        assert favorite.status_code == 200
        assert favorite.json()["status"] == "active"
        assert favorite.json()["aggregate"]["favorite_count"] == 1
        assert favorite.json()["aggregate"]["review_count"] == 0

        denied = client.put(
            f"/api/v1/marketplace/listings/{listing['id']}/review",
            headers=learner, json={"rating": 5, "body": "尚未使用却尝试评价"},
        )
        assert denied.status_code == 422
        assert denied.json()["detail"]["code"] == "marketplace_review_use_required"

        removed = client.put(
            f"/api/v1/marketplace/listings/{listing['id']}/favorite",
            headers=learner, json={"active": False, "expected_version": favorite.json()["lock_version"]},
        )
        assert removed.status_code == 200
        assert removed.json()["status"] == "removed"


def test_acquisition_qualifies_review_and_updates_append_history():
    with TestClient(app) as client:
        (teacher, admin, learner), course_id = fixture(client, "fc2_engagement_update")
        listing = publish(client, admin, submit(client, teacher, course_id))
        acquisition = client.post(
            f"/api/v1/marketplace/listings/{listing['id']}/acquisitions", headers=learner,
        ).json()

        created = client.put(
            f"/api/v1/marketplace/listings/{listing['id']}/review",
            headers=learner, json={"rating": 4, "body": "已导入课程，结构清晰。"},
        )
        assert created.status_code == 200, created.text
        review = created.json()["review"]
        assert review["verified_use"] is True
        assert review["usage"]["acquisition_id"] == acquisition["id"]
        assert review["usage"]["learning_event_count"] == 0
        assert len(review["events"]) == 1
        assert created.json()["aggregate"]["average_rating"] is None
        assert created.json()["aggregate"]["sample_state"] == "insufficient"

        stale = client.put(
            f"/api/v1/marketplace/listings/{listing['id']}/review",
            headers=learner, json={"rating": 5, "body": "陈旧版本更新", "expected_version": 99},
        )
        assert stale.status_code == 409

        updated = client.put(
            f"/api/v1/marketplace/listings/{listing['id']}/review",
            headers=learner, json={"rating": 5, "body": "完成浏览后更新为五星。", "expected_version": review["lock_version"]},
        )
        assert updated.status_code == 200
        assert updated.json()["review"]["lock_version"] == 2
        assert [event["action"] for event in updated.json()["review"]["events"]] == ["created", "updated"]
        assert updated.json()["review"]["events"][1]["from_rating"] == 4

        with SessionLocal() as db:
            row = db.get(DBMarketplaceReview, review["id"])
            row.listing_snapshot_hash = "x" * 64
            with pytest.raises(DatabaseError, match="immutable"):
                db.commit()
            db.rollback()
            event = db.query(DBMarketplaceReviewEvent).filter_by(review_id=review["id"]).first()
            event.to_rating = 1
            with pytest.raises(DatabaseError, match="immutable"):
                db.commit()
            db.rollback()


def test_minimum_sample_aggregate_and_server_derived_learning_evidence():
    with TestClient(app) as client:
        (teacher, admin, _), course_id = fixture(client, "fc2_engagement_aggregate")
        listing = publish(client, admin, submit(client, teacher, course_id))
        ratings = [5, 4, 3]
        for index, rating in enumerate(ratings):
            headers = auth_headers(client, f"fc2_verified_reviewer_{index}")
            acquisition = client.post(
                f"/api/v1/marketplace/listings/{listing['id']}/acquisitions", headers=headers,
            ).json()
            if index == 2:
                with SessionLocal() as db:
                    user = db.query(DBUser).filter_by(username=f"fc2_verified_reviewer_{index}").one()
                    db.add(DBLearningEvent(owner_public_id=user.public_id, course_id=acquisition["derived_course_id"],
                        event_type="course.resource.opened", schema_version="1.0", source="test",
                        trace_id=new_public_id("trace"), object_type="course", object_id=acquisition["derived_course_id"], payload={}))
                    db.commit()
            response = client.put(
                f"/api/v1/marketplace/listings/{listing['id']}/review", headers=headers,
                json={"rating": rating, "body": f"第 {index + 1} 位已验证使用者评价。"},
            )
            assert response.status_code == 200, response.text
            aggregate = response.json()["aggregate"]
            if index < 2:
                assert aggregate["average_rating"] is None
                assert aggregate["sample_state"] == "insufficient"
            else:
                assert aggregate["review_count"] == 3
                assert aggregate["average_rating"] == 4.0
                assert aggregate["sample_state"] == "published"
                assert response.json()["review"]["usage"]["learning_event_count"] == 1

        public = client.get("/api/v1/marketplace/public", headers=teacher).json()["items"]
        row = next(item for item in public if item["id"] == listing["id"])
        assert row["engagement"]["average_rating"] == 4.0
        assert row["engagement"]["minimum_sample"] == 3

        with SessionLocal() as db:
            assert db.query(DBMarketplaceFavorite).filter_by(listing_id=listing["id"]).count() == 0
            assert db.query(DBMarketplaceReview).filter_by(listing_id=listing["id"]).count() == 3
            assert db.query(DBMarketplaceReviewEvent).count() >= 3
