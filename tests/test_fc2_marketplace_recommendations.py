import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.database import (
    DBLearningEvent, DBMarketplaceRecommendationResult,
    DBMarketplaceRecommendationRun, DBProfileSnapshot, DBUser, SessionLocal,
)
from app.main import app
from tests.api_test_helpers import auth_headers
from tests.test_next_marketplace import fixture, publish, submit


def _profile(username: str, suffix: str) -> None:
    with SessionLocal() as db:
        user = db.query(DBUser).filter_by(username=username).one()
        db.add(DBProfileSnapshot(
            id=f"ps-fc2-rec-{suffix}", owner_public_id=user.public_id,
            legacy_student_id=username, profile_version="fc2-rec-v1",
            snapshot={
                "target_course": "AI 可信训练",
                "learning_goals": ["可信训练", "人工智能"],
                "knowledge_base": "中级",
                "cognitive_load": 0.4,
            }, content_hash=(suffix * 64)[:64], trace_id=f"trace-fc2-rec-{suffix}",
        ))
        db.commit()


def test_explainable_recommendation_is_ranked_idempotent_and_evidence_versioned():
    with TestClient(app) as client:
        (teacher, admin, learner), course_id = fixture(client, "fc2_rec_rank")
        listing = publish(client, admin, submit(client, teacher, course_id))
        username = "market_learner_fc2_rec_rank"
        _profile(username, "rank")

        payload = {
            "learning_goals": ["可信训练", "人工智能"],
            "topics": ["AI"],
            "target_difficulty": 0.5,
        }
        first = client.post("/api/v1/marketplace/recommendations", headers=learner, json=payload)
        assert first.status_code == 201, first.text
        run = first.json()
        assert run["algorithm_version"] == "fc.marketplace-recommendation.v1"
        assert run["run_evidence"]["evaluation_date"]
        assert run["result_count"] >= 1
        item = next(row for row in run["items"] if row["listing"]["id"] == listing["id"])
        assert item["rank"] >= 1
        assert 0 <= item["total_score"] <= 1
        assert item["features"]["teaching_fit"]["weight"] == 0.28
        assert item["features"]["difficulty_fit"]["weight"] == 0.22
        assert item["features"]["popularity"]["weight"] == 0.02
        assert item["features"]["popularity"]["weight"] < item["features"]["teaching_fit"]["weight"]
        assert item["recommendation_reasons"]
        assert "专家认证" in run["truth_label"]

        repeated = client.post("/api/v1/marketplace/recommendations", headers=learner, json=payload)
        assert repeated.status_code == 201
        assert repeated.json()["id"] == run["id"]
        assert client.get("/api/v1/marketplace/recommendations/latest", headers=learner).json()["id"] == run["id"]

        acquisition = client.post(
            f"/api/v1/marketplace/listings/{listing['id']}/acquisitions", headers=learner,
        ).json()
        with SessionLocal() as db:
            user = db.query(DBUser).filter_by(username=username).one()
            db.add(DBLearningEvent(
                owner_public_id=user.public_id, course_id=acquisition["derived_course_id"],
                event_type="marketplace.study.completed", trace_id="trace-fc2-rec-use",
                object_type="course", object_id=acquisition["derived_course_id"],
                payload={"verified": True},
            ))
            db.commit()
        changed = client.post("/api/v1/marketplace/recommendations", headers=learner, json=payload)
        assert changed.status_code == 201
        assert changed.json()["id"] != run["id"]
        changed_item = next(row for row in changed.json()["items"] if row["listing"]["id"] == listing["id"])
        assert changed_item["features"]["verified_use"]["evidence"]["learning_event_count"] == 1
        assert changed_item["features"]["verified_use"]["contribution"] > item["features"]["verified_use"]["contribution"]


def test_recommendation_owner_isolation_missing_evidence_and_immutable_rows():
    with TestClient(app) as client:
        (teacher, admin, learner), course_id = fixture(client, "fc2_rec_security")
        listing = publish(client, admin, submit(client, teacher, course_id))
        created = client.post(
            "/api/v1/marketplace/recommendations", headers=learner,
            json={"learning_goals": [], "topics": [], "target_difficulty": None},
        )
        assert created.status_code == 201, created.text
        run = created.json()
        item = next(row for row in run["items"] if row["listing"]["id"] == listing["id"])
        assert item["evidence_state"]["missing_evidence"]
        assert item["confidence"] < 1

        outsider = auth_headers(client, "fc2_rec_outsider")
        denied = client.get(f"/api/v1/marketplace/recommendations/{run['id']}", headers=outsider)
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == "marketplace_recommendation_forbidden"

        with SessionLocal() as db:
            db_run = db.get(DBMarketplaceRecommendationRun, run["id"])
            db_result = db.query(DBMarketplaceRecommendationResult).filter_by(run_id=run["id"]).first()
            assert db_run and db_result
            db_run.result_count = 999
            with pytest.raises(DatabaseError, match="immutable"):
                db.commit()
            db.rollback()
            db_result.total_score = 0
            with pytest.raises(DatabaseError, match="immutable"):
                db.commit()
            db.rollback()
            assert db.execute(text("PRAGMA integrity_check")).scalar() == "ok"
