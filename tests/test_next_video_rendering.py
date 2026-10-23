from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.database import DBVideoOutputVersion, DBVideoRenderTask, DBVideoScriptVersion, SessionLocal
from app.main import app
from app.m1_object_service import OBJECT_SPECS
import app.video_rendering as video_rendering
from app.video_rendering import runtime_status
from tests.api_test_helpers import TEST_PASSWORD, auth_headers


SCENES = [
    {"title": "边缘智能是什么", "narration": "边缘智能把模型推理带到资源受限设备。", "bullets": ["低延迟", "离线可用"], "duration_ms": 1600},
    {"title": "部署工作流", "narration": "先训练和验证，再量化并部署模型。", "bullets": ["验证", "量化", "部署"], "duration_ms": 1600},
]


def login(client, username):
    auth_headers(client, username)
    row = client.post("/api/auth/login", data={"username": username, "password": TEST_PASSWORD})
    return {"Authorization": "Bearer " + row.json()["access_token"]}


def test_offline_render_idempotency_files_quality_and_owner_boundary():
    runtime = runtime_status()
    assert runtime["available"] is True
    assert runtime["offline"] is True and runtime["admin_required"] is False
    assert runtime["package_version"] == "0.6.0"
    assert runtime["ffmpeg_version"] and runtime["binary_bytes"] > 1_000_000
    assert len(runtime["binary_sha256"]) == 64
    with TestClient(app) as client:
        owner, outsider = login(client, "video_owner"), login(client, "video_outsider")
        created = client.post("/api/v1/video-projects", headers=owner, json={"title": "边缘智能微课", "scenes": SCENES})
        assert created.status_code == 201, created.text
        project = created.json(); project_id = project["id"]
        denied = client.get(f"/api/v1/video-projects/{project_id}", headers=outsider)
        assert denied.status_code == 403

        rendered = client.post(f"/api/v1/video-projects/{project_id}/renders", headers=owner, json={"idempotency_key": "render-edge-lesson-001"})
        assert rendered.status_code == 200, rendered.text
        task = rendered.json(); assert task["status"] == "completed" and task["progress"] == 100
        assert task["audio_status"] in {"sapi_zh_cn", "text_only"} and task["output"]["quality_report"]["passed"] is True
        duplicate = client.post(f"/api/v1/video-projects/{project_id}/renders", headers=owner, json={"idempotency_key": "render-edge-lesson-001"})
        assert duplicate.json()["id"] == task["id"]

        output = task["output"]
        for filename in ("course-video.mp4", "subtitles.srt", "subtitles.vtt", "transcript.json"):
            response = client.get(f"/api/v1/video-projects/outputs/{output['id']}/files/{filename}", headers=owner)
            assert response.status_code == 200 and len(response.content) > 10
            assert client.get(f"/api/v1/video-projects/outputs/{output['id']}/files/{filename}", headers=outsider).status_code == 403
            if filename.endswith(".mp4"):
                assert b"ftyp" in response.content[:32]
            if filename.endswith(".srt"):
                assert "边缘智能把模型推理" in response.content.decode("utf-8")

        with SessionLocal() as db:
            assert db.query(DBVideoScriptVersion).filter_by(project_id=project_id).count() == 1
            assert db.query(DBVideoRenderTask).filter_by(project_id=project_id).count() == 1
            assert db.query(DBVideoOutputVersion).filter_by(project_id=project_id).count() == 1


def test_script_versions_conflict_interrupted_recovery_and_cancel():
    with TestClient(app) as client:
        owner = login(client, "video_recovery_owner")
        project = client.post("/api/v1/video-projects", headers=owner, json={"title": "恢复课程", "scenes": SCENES}).json()
        revised = client.post(f"/api/v1/video-projects/{project['id']}/scripts", headers=owner,
            json={"expected_version": 1, "scenes": [{**SCENES[0], "title": "更新后的边缘智能"}]})
        assert revised.status_code == 200 and revised.json()["lock_version"] == 2
        stale = client.post(f"/api/v1/video-projects/{project['id']}/scripts", headers=owner,
            json={"expected_version": 1, "scenes": SCENES})
        assert stale.status_code == 409
        with SessionLocal() as db:
            assert db.query(DBVideoScriptVersion).filter_by(project_id=project["id"]).count() == 2
            task = DBVideoRenderTask(project_id=project["id"], script_version_id=revised.json()["script"]["id"],
                owner_public_id=db.query(DBVideoScriptVersion).filter_by(id=revised.json()["script"]["id"]).one().created_by_public_id,
                idempotency_key="interrupted-render-001", status="running", progress=44)
            db.add(task); db.commit(); task_id = task.id
        detail = client.get(f"/api/v1/video-projects/{project['id']}", headers=owner)
        recovered = next(item for item in detail.json()["tasks"] if item["id"] == task_id)
        assert recovered["status"] == "failed" and recovered["error_code"] == "video.render_interrupted"
        cancelled = client.post(f"/api/v1/video-projects/tasks/{task_id}/cancel", headers=owner)
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"


def test_video_objects_registered_in_uniform_gateway():
    assert {"video_project", "video_script_version", "video_render_task", "video_output_version"} <= set(OBJECT_SPECS)


def test_missing_sapi_voice_falls_back_to_truthful_text_only(monkeypatch):
    runtime = runtime_status()
    monkeypatch.setattr(video_rendering, "runtime_status", lambda: {
        **runtime, "sapi_voice": "", "audio_available": False,
    })
    with TestClient(app) as client:
        owner = login(client, "video_text_only_owner")
        project = client.post(
            "/api/v1/video-projects", headers=owner,
            json={"title": "无语音降级微课", "scenes": [SCENES[0]]},
        ).json()
        rendered = client.post(
            f"/api/v1/video-projects/{project['id']}/renders", headers=owner,
            json={"idempotency_key": "render-text-only-001"},
        )
        assert rendered.status_code == 200, rendered.text
        task = rendered.json()
        assert task["audio_status"] == "text_only"
        assert task["output"]["quality_report"]["audio_error"] == "video.sapi_voice_unavailable"
        assert task["output"]["manifest"]["runtime"]["audio_available"] is False


def test_script_and_output_versions_reject_update_and_delete():
    with TestClient(app) as client:
        owner = login(client, "video_immutable_owner")
        project = client.post(
            "/api/v1/video-projects", headers=owner,
            json={"title": "不可变版本微课", "scenes": [SCENES[0]]},
        ).json()
        rendered = client.post(
            f"/api/v1/video-projects/{project['id']}/renders", headers=owner,
            json={"idempotency_key": "render-immutable-001"},
        ).json()
        script_id = project["script"]["id"]
        output_id = rendered["output"]["id"]

    with SessionLocal() as db:
        statements = (
            ("UPDATE video_script_versions SET content_hash='tampered' WHERE id=:id", script_id),
            ("DELETE FROM video_script_versions WHERE id=:id", script_id),
            ("UPDATE video_output_versions SET mp4_sha256='tampered' WHERE id=:id", output_id),
            ("DELETE FROM video_output_versions WHERE id=:id", output_id),
        )
        for statement, row_id in statements:
            with pytest.raises(DatabaseError, match="immutable"):
                db.execute(text(statement), {"id": row_id})
                db.commit()
            db.rollback()
