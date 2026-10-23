from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DatabaseError

from app.database import (
    DBCourse, DBMarketplaceFork, DBMarketplaceForkDecision,
    DBMarketplaceForkVersion, DBMarketplaceListing, SessionLocal,
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
        query = db.query(DBMarketplaceListing)
        if before:
            query = query.filter(~DBMarketplaceListing.id.in_(before))
        for row in query.all():
            row.status = "withdrawn"
        db.commit()


def _acquire(client: TestClient, learner: dict[str, str], listing: dict) -> dict:
    response = client.post(
        f"/api/v1/marketplace/listings/{listing['id']}/acquisitions", headers=learner,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _publish_v2(client: TestClient, teacher: dict[str, str], admin: dict[str, str], course_id: str) -> dict:
    with SessionLocal() as db:
        course = db.get(DBCourse, course_id)
        course.version = "2.0"
        course.title = "AI 可信训练上游新版"
        course.description = "上游第二版描述"
        db.commit()
    return publish(client, admin, submit(client, teacher, course_id))


def test_fork_requires_acquisition_and_creates_immutable_independent_versions():
    with TestClient(app) as client:
        (teacher, admin, learner), course_id = fixture(client, "fc2_fork_versions")
        outsider = auth_headers(client, "fc2_fork_outsider")
        listing = publish(client, admin, submit(client, teacher, course_id))
        denied = client.post(
            f"/api/v1/marketplace/listings/{listing['id']}/forks", headers=outsider,
            json={"modification_summary": "没有获取副本不能建立分叉"},
        )
        assert denied.status_code == 422
        acquisition = _acquire(client, learner, listing)

        response = client.post(
            f"/api/v1/marketplace/listings/{listing['id']}/forks", headers=learner,
            json={"modification_summary": "建立独立版本线并保留上游来源"},
        )
        assert response.status_code == 201, response.text
        fork = response.json()
        assert fork["acquisition_id"] == acquisition["id"]
        assert fork["current_version"]["version_number"] == 1
        assert fork["current_version"]["inherited_license"]["course_license"] == "CC BY 4.0"
        assert "法律兼容性" in fork["boundary"]

        changed = client.post(
            f"/api/v1/marketplace/forks/{fork['id']}/versions", headers=learner,
            json={
                "expected_version": fork["lock_version"],
                "modification_summary": "增加本地案例并改写课程说明",
                "patch": {
                    "course": {"description": "本地分叉描述"},
                    "documents": [{"filename": "a.md", "content": "正文与本地案例"}],
                },
            },
        )
        assert changed.status_code == 201, changed.text
        fork = changed.json()
        assert [item["version_number"] for item in fork["versions"]] == [2, 1]
        assert fork["current_version"]["course"]["description"] == "本地分叉描述"
        assert client.post(
            f"/api/v1/marketplace/forks/{fork['id']}/versions", headers=outsider,
            json={"expected_version": fork["lock_version"], "modification_summary": "越权修改", "patch": {"course": {"title": "x"}}},
        ).status_code == 403
        assert client.post(
            f"/api/v1/marketplace/forks/{fork['id']}/versions", headers=learner,
            json={"expected_version": 1, "modification_summary": "陈旧写入", "patch": {"course": {"title": "x"}}},
        ).status_code == 409
        assert client.post(
            f"/api/v1/marketplace/forks/{fork['id']}/versions", headers=learner,
            json={"expected_version": fork["lock_version"], "modification_summary": "伪造来源", "patch": {"course": {"license_text": "fake"}}},
        ).status_code == 422

        workspace = client.get("/api/v1/marketplace/forks", headers=learner).json()
        assert len(workspace["forks"]) == 1
        with SessionLocal() as db:
            row = db.get(DBMarketplaceFork, fork["id"])
            assert row.derived_course_id == acquisition["derived_course_id"]
            version = db.query(DBMarketplaceForkVersion).filter_by(fork_id=row.id).first()
            version.modification_summary = "tamper"
            with pytest.raises(DatabaseError, match="immutable"):
                db.commit()
            db.rollback()


def test_three_way_preview_and_non_conflicting_merge_preserve_local_conflicts():
    with TestClient(app) as client:
        (teacher, admin, learner), course_id = fixture(client, "fc2_fork_merge")
        first = publish(client, admin, submit(client, teacher, course_id))
        _acquire(client, learner, first)
        fork = client.post(
            f"/api/v1/marketplace/listings/{first['id']}/forks", headers=learner,
            json={"modification_summary": "从市场副本建立本地分叉"},
        ).json()
        fork = client.post(
            f"/api/v1/marketplace/forks/{fork['id']}/versions", headers=learner,
            json={"expected_version": fork["lock_version"], "modification_summary": "本地改写课程描述",
                  "patch": {"course": {"description": "本地分叉描述"}}},
        ).json()
        second = _publish_v2(client, teacher, admin, course_id)

        fork = client.get("/api/v1/marketplace/forks", headers=learner).json()["forks"][0]
        preview = fork["update_preview"]
        assert preview["upstream_listing"]["id"] == second["id"]
        assert "course.description" in preview["conflicts"]
        assert "course.title" in preview["upstream_changes"]
        assert fork["upstream_status"] == "update_available"

        stale = client.post(
            f"/api/v1/marketplace/forks/{fork['id']}/decisions", headers=learner,
            json={"upstream_listing_id": second["id"], "action": "accept_non_conflicting",
                  "reason": "合并无冲突字段并保留本地冲突", "expected_version": 1},
        )
        assert stale.status_code == 409
        merged = client.post(
            f"/api/v1/marketplace/forks/{fork['id']}/decisions", headers=learner,
            json={"upstream_listing_id": second["id"], "action": "accept_non_conflicting",
                  "reason": "合并无冲突字段并保留本地冲突", "expected_version": fork["lock_version"]},
        )
        assert merged.status_code == 200, merged.text
        result = merged.json()
        assert result["current_version"]["course"]["title"] == "AI 可信训练上游新版"
        assert result["current_version"]["course"]["description"] == "本地分叉描述"
        assert result["baseline_hash"] == second["snapshot_hash"]
        assert result["update_preview"] is None
        assert result["decisions"][0]["action"] == "accept_non_conflicting"
        assert "course.description" in result["decisions"][0]["conflicts"]

        with SessionLocal() as db:
            decision = db.query(DBMarketplaceForkDecision).filter_by(fork_id=result["id"]).one()
            assert decision.resulting_version_id == result["current_version"]["id"]
            decision.reason = "tamper"
            with pytest.raises(DatabaseError, match="immutable"):
                db.commit()
            db.rollback()
            course = db.get(DBCourse, result["derived_course_id"])
            assert course.title == "AI 可信训练上游新版"
            assert course.description == "本地分叉描述"


@pytest.mark.parametrize("action", ["keep_local", "ignore"])
def test_keep_local_and_ignore_are_explicit_non_destructive_decisions(action: str):
    with TestClient(app) as client:
        (teacher, admin, learner), course_id = fixture(client, f"fc2_fork_{action}")
        first = publish(client, admin, submit(client, teacher, course_id))
        _acquire(client, learner, first)
        fork = client.post(
            f"/api/v1/marketplace/listings/{first['id']}/forks", headers=learner,
            json={"modification_summary": "建立本地独立版本线"},
        ).json()
        fork = client.post(
            f"/api/v1/marketplace/forks/{fork['id']}/versions", headers=learner,
            json={"expected_version": fork["lock_version"], "modification_summary": "保留本地课程说明",
                  "patch": {"course": {"description": "必须保留的本地说明"}}},
        ).json()
        second = _publish_v2(client, teacher, admin, course_id)
        fork = client.get("/api/v1/marketplace/forks", headers=learner).json()["forks"][0]
        decided = client.post(
            f"/api/v1/marketplace/forks/{fork['id']}/decisions", headers=learner,
            json={"upstream_listing_id": second["id"], "action": action,
                  "reason": "显式保留本地内容，不接受静默覆盖", "expected_version": fork["lock_version"]},
        )
        assert decided.status_code == 200, decided.text
        result = decided.json()
        assert result["current_version"]["course"]["description"] == "必须保留的本地说明"
        assert result["decisions"][0]["action"] == action
        assert result["upstream_status"] == "current"
        if action == "keep_local":
            assert result["baseline_hash"] == second["snapshot_hash"]
            assert result["update_preview"] is None
            assert result["current_version"]["version_number"] == 3
        else:
            assert result["baseline_hash"] == first["snapshot_hash"]
            assert result["update_preview"]["decision"]["action"] == "ignore"
            assert result["current_version"]["version_number"] == 2
