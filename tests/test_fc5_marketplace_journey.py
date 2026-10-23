from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import DBCourse, DBCompetitionJourneyRun, DBLearningEvent, DBMarketplaceJourneySearchVerification, DBMarketplaceListing, DBUser, SessionLocal
from app.identity import new_public_id
from app.main import app
from tests.api_test_helpers import auth_headers
from tests.test_next_marketplace import fixture, login, submit


@pytest.fixture(autouse=True)
def withdraw_created_listings():
    with SessionLocal() as db:
        before = {row[0] for row in db.query(DBMarketplaceListing.id).all()}
    yield
    with SessionLocal() as db:
        query = db.query(DBMarketplaceListing)
        if before:
            query = query.filter(~DBMarketplaceListing.id.in_(before))
        for row in query.all():
            row.status = "withdrawn"
        db.commit()


def _journey(client, admin, listing, recipient_public_id, run_key="marketplace-journey"):
    response = client.post(
        "/api/v1/competition-journeys/marketplace/runs",
        headers=admin,
        json={"listing_id": listing["id"], "recipient_public_id": recipient_public_id, "run_key": run_key},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _decision(client, admin, listing, action, reason, impact_kind=None):
    payload = {"action": action, "reason": reason, "expected_version": listing["lock_version"]}
    if impact_kind:
        payload["impact_kind"] = impact_kind
    response = client.post(
        f"/api/v1/marketplace/listings/{listing['id']}/decisions", headers=admin, json=payload
    )
    assert response.status_code == 200, response.text
    return response.json()


def _publish(client, admin, listing, impact_kind=None):
    listing = _decision(client, admin, listing, "approve", "冻结来源与许可字段审核通过")
    return _decision(client, admin, listing, "publish", "批准进入比赛演示公共市场", impact_kind)


def test_marketplace_journey_scope_search_and_visits_do_not_complete():
    with TestClient(app) as client:
        (teacher, admin, learner), course_id = fixture(client, "fc5_market_scope")
        listing = submit(client, teacher, course_id)
        with SessionLocal() as db:
            recipient = db.query(DBUser).filter_by(username="market_learner_fc5_market_scope").one()
            recipient_id = recipient.public_id
        run = _journey(client, admin, listing, recipient_id)
        assert run["progress"] == {"completed": 1, "total": 8, "percent": 12}
        assert run["marketplace_context"]["listing_snapshot_hash"] == listing["snapshot_hash"]

        for step in run["steps"]:
            response = client.post(
                f"/api/v1/competition-journeys/marketplace/runs/{run['id']}/visits",
                headers=admin, json={"step_key": step["key"], "route": step["route"]},
            )
            assert response.status_code == 201, response.text
        current = client.get(
            f"/api/v1/competition-journeys/marketplace/runs/{run['id']}", headers=admin
        ).json()
        assert current["progress"]["completed"] == 1 and len(current["visits"]) == 8
        assert client.post(
            f"/api/v1/competition-journeys/marketplace/runs/{run['id']}/search-verification",
            headers=admin,
        ).status_code == 409

        repeated = _journey(client, admin, listing, recipient_id)
        assert repeated["id"] == run["id"] and repeated["created"] is False
        outsider_admin = auth_headers(client, "fc5_market_outsider_admin")
        with SessionLocal() as db:
            db.query(DBUser).filter_by(username="fc5_market_outsider_admin").update({"role": "admin"})
            db.commit()
        outsider_admin = login(client, "fc5_market_outsider_admin")
        assert client.get(
            f"/api/v1/competition-journeys/marketplace/runs/{run['id']}", headers=outsider_admin
        ).status_code == 403
        assert client.get("/api/v1/competition-journeys/marketplace", headers=learner).status_code == 403


def test_marketplace_evidence_closes_only_on_same_listing_version_and_recipient():
    with TestClient(app) as client:
        (teacher, admin, learner), course_id = fixture(client, "fc5_market_lifecycle")
        listing = submit(client, teacher, course_id)
        with SessionLocal() as db:
            recipient = db.query(DBUser).filter_by(username="market_learner_fc5_market_lifecycle").one()
            recipient_id = recipient.public_id
        run = _journey(client, admin, listing, recipient_id, "marketplace-lifecycle")
        listing = _publish(client, admin, listing)
        verified = client.post(
            f"/api/v1/competition-journeys/marketplace/runs/{run['id']}/search-verification",
            headers=admin,
        )
        assert verified.status_code == 201, verified.text
        assert client.post(
            f"/api/v1/competition-journeys/marketplace/runs/{run['id']}/search-verification",
            headers=admin,
        ).json()["created"] is False

        favorite = client.put(
            f"/api/v1/marketplace/listings/{listing['id']}/favorite", headers=learner,
            json={"active": True},
        )
        assert favorite.status_code == 200
        acquisition = client.post(
            f"/api/v1/marketplace/listings/{listing['id']}/acquisitions", headers=learner
        ).json()
        review = client.put(
            f"/api/v1/marketplace/listings/{listing['id']}/review", headers=learner,
            json={"rating": 5, "body": "已导入并完成课程结构检查。"},
        )
        assert review.status_code == 200, review.text
        before_usage = client.get(
            f"/api/v1/competition-journeys/marketplace/runs/{run['id']}", headers=admin
        ).json()
        assert before_usage["progress"]["completed"] == 4
        with SessionLocal() as db:
            db.add(DBLearningEvent(
                owner_public_id=recipient_id, course_id=acquisition["derived_course_id"],
                event_type="course.resource.completed", schema_version="1.0", source="fc5-test",
                trace_id=new_public_id("trace"), object_type="course", object_id=acquisition["derived_course_id"], payload={},
            ))
            db.commit()
        current = client.get(
            f"/api/v1/competition-journeys/marketplace/runs/{run['id']}", headers=admin
        ).json()
        assert current["progress"]["completed"] == 5

        fork = client.post(
            f"/api/v1/marketplace/listings/{listing['id']}/forks", headers=learner,
            json={"modification_summary": "建立比赛演示独立版本线"},
        )
        assert fork.status_code == 201, fork.text
        assert fork.json()["acquisition_id"] == acquisition["id"]
        assert client.get(
            f"/api/v1/competition-journeys/marketplace/runs/{run['id']}", headers=admin
        ).json()["progress"]["completed"] == 6

        with SessionLocal() as db:
            course = db.get(DBCourse, course_id)
            course.version = "2"
            course.title = "AI 可信训练更新版"
            course.description = "包含新的上游安全修复"
            db.commit()
        listing_v2 = _publish(client, admin, submit(client, teacher, course_id), "severe_fix")
        after_update = client.get(
            f"/api/v1/competition-journeys/marketplace/runs/{run['id']}", headers=admin
        ).json()
        assert after_update["progress"]["completed"] == 7
        assert next(x for x in after_update["steps"] if x["key"] == "update_notification")["complete"]

        withdrawn = _decision(client, admin, listing, "withdraw", "旧版完成生命周期撤回并保留派生副本")
        assert withdrawn["status"] == "withdrawn" and listing_v2["status"] == "published"
        final = client.get(
            f"/api/v1/competition-journeys/marketplace/runs/{run['id']}", headers=admin
        ).json()
        assert final["status"] == "completed"
        assert final["progress"] == {"completed": 8, "total": 8, "percent": 100}
        assert all(step["complete"] for step in final["steps"])

        with SessionLocal() as db:
            proof = db.query(DBMarketplaceJourneySearchVerification).filter_by(run_id=run["id"]).one()
            assert proof.listing_id == listing["id"] and proof.recipient_public_id == recipient_id
            assert proof.result_snapshot["matched_ids"] == [listing["id"]]


def test_migration_059_preserves_all_five_journey_types():
    with SessionLocal() as db:
        assert db.execute(text("select count(*) from schema_migrations where version='20260805_059'")).scalar_one() == 1
        owner = db.query(DBUser).first()
        assert owner is not None
        rows = [
            DBCompetitionJourneyRun(
                owner_public_id=owner.public_id, course_id=None, journey_type=kind,
                run_key=f"fc5-059-preserved-{kind}", baseline_snapshot={"kind": kind},
                baseline_hash=str(index) * 64,
            )
            for index, kind in enumerate(("student", "media", "teacher", "enterprise", "marketplace"), 1)
        ]
        db.add_all(rows)
        db.commit()
        assert {row.journey_type for row in rows} == {"student", "media", "teacher", "enterprise", "marketplace"}
