from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.database import DBTeachingAnimationVersion, SessionLocal
from app.main import app
from app.m1_object_service import OBJECT_SPECS
from tests.api_test_helpers import auth_headers


DEFAULTS = {
    "initial_x": 8,
    "target_x": 1,
    "learning_rate": 0.15,
    "curvature": 1,
    "step_count": 6,
}


def _create(client: TestClient, headers: dict[str, str], *, parameters=None):
    response = client.post("/api/v1/teaching-animations", headers=headers, json={
        "title": "梯度下降参数实验",
        "template_id": "gradient-descent-2d-v1",
        "parameters": parameters or DEFAULTS,
        "course_id": None,
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_server_computes_formula_and_rejects_invalid_or_client_frames():
    with TestClient(app) as client:
        owner = auth_headers(client, "fc1_007_formula_owner")
        templates = client.get("/api/v1/teaching-animations/templates", headers=owner)
        assert templates.status_code == 200
        template = templates.json()["items"][0]
        assert template["formula"]["engine_version"] == "edumatrix-deterministic-gradient-v1"
        assert template["data_boundary"].startswith("所有帧由服务端")

        project = _create(client, owner)
        frames = project["current_version"]["frames"]
        assert len(frames) == 7
        assert frames[0] == {
            "index": 0, "x": 8.0, "loss": 49.0, "gradient": 14.0,
            "distance_to_target": 7.0, "state": "optimizing",
        }
        assert frames[1]["x"] == pytest.approx(5.9)
        assert frames[1]["loss"] == pytest.approx(24.01)
        assert frames[1]["gradient"] == pytest.approx(9.8)
        assert project["current_version"]["quality"]["deterministic"] is True
        assert project["current_version"]["quality"]["randomness"] is False

        unstable = client.post("/api/v1/teaching-animations", headers=owner, json={
            "title": "不稳定组合", "template_id": "gradient-descent-2d-v1",
            "parameters": {**DEFAULTS, "learning_rate": 1, "curvature": 1},
        })
        assert unstable.status_code == 422
        assert unstable.json()["detail"]["code"] == "teaching_animation.unstable_parameters"

        injected = client.post("/api/v1/teaching-animations", headers=owner, json={
            "title": "客户端帧注入", "template_id": "gradient-descent-2d-v1",
            "parameters": DEFAULTS, "frames": [{"x": 999}],
        })
        assert injected.status_code == 422


def test_versions_are_idempotent_immutable_and_registered():
    with TestClient(app) as client:
        owner = auth_headers(client, "fc1_007_version_owner")
        project = _create(client, owner)
        animation_id = project["id"]
        first_version = project["current_version"]["id"]
        assert project["lock_version"] == 2

        replay = client.post(f"/api/v1/teaching-animations/{animation_id}/versions", headers=owner, json={
            "parameters": DEFAULTS, "expected_lock_version": 2,
        })
        assert replay.status_code == 200, replay.text
        assert replay.json()["version_created"] is False
        assert replay.json()["lock_version"] == 2
        assert len(replay.json()["versions"]) == 1

        changed = client.post(f"/api/v1/teaching-animations/{animation_id}/versions", headers=owner, json={
            "parameters": {**DEFAULTS, "learning_rate": 0.1},
            "expected_lock_version": 2,
        })
        assert changed.status_code == 200, changed.text
        assert changed.json()["version_created"] is True
        assert changed.json()["current_version"]["version_number"] == 2
        assert changed.json()["lock_version"] == 3
        assert len(changed.json()["versions"]) == 2

        stale = client.post(f"/api/v1/teaching-animations/{animation_id}/versions", headers=owner, json={
            "parameters": {**DEFAULTS, "learning_rate": 0.12},
            "expected_lock_version": 2,
        })
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "teaching_animation.conflict"

    assert OBJECT_SPECS["teaching_animation"].model.__tablename__ == "teaching_animations"
    assert OBJECT_SPECS["teaching_animation_version"].model.__tablename__ == "teaching_animation_versions"
    with SessionLocal() as db:
        row = db.get(DBTeachingAnimationVersion, first_version)
        row.content_hash = "0" * 64
        with pytest.raises(DatabaseError, match="immutable"):
            db.commit()
        db.rollback()
        with pytest.raises(DatabaseError, match="immutable"):
            db.execute(text("DELETE FROM teaching_animation_versions WHERE id=:id"), {"id": first_version})
            db.commit()
        db.rollback()


def test_playback_optimistic_lock_refresh_recovery_and_owner_isolation():
    with TestClient(app) as client:
        owner = auth_headers(client, "fc1_007_playback_owner")
        outsider = auth_headers(client, "fc1_007_playback_outsider")
        project = _create(client, owner)
        animation_id = project["id"]

        started = client.put(f"/api/v1/teaching-animations/{animation_id}/playback", headers=owner, json={
            "current_frame": 2, "playback_status": "playing", "expected_lock_version": 2,
        })
        assert started.status_code == 200, started.text
        assert started.json()["current_frame"] == 2
        assert started.json()["playback_status"] == "playing"
        assert started.json()["lock_version"] == 3

        stale = client.put(f"/api/v1/teaching-animations/{animation_id}/playback", headers=owner, json={
            "current_frame": 3, "playback_status": "paused", "expected_lock_version": 2,
        })
        assert stale.status_code == 409

        restored = client.get(f"/api/v1/teaching-animations/{animation_id}", headers=owner)
        assert restored.status_code == 200
        assert restored.json()["current_frame"] == 2
        assert restored.json()["current_version"]["frames"][2]["index"] == 2

        assert client.get(f"/api/v1/teaching-animations/{animation_id}", headers=outsider).status_code == 403
        assert client.put(f"/api/v1/teaching-animations/{animation_id}/playback", headers=outsider, json={
            "current_frame": 0, "playback_status": "paused", "expected_lock_version": 3,
        }).status_code == 403
        listing = client.get("/api/v1/teaching-animations", headers=outsider)
        assert listing.status_code == 200
        assert listing.json()["count"] == 0
