from __future__ import annotations

import subprocess
from pathlib import Path

import imageio_ffmpeg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.database import DBVideoAssetVersion, SessionLocal
from app.main import app
from app.m1_object_service import OBJECT_SPECS
from tests.api_test_helpers import auth_headers


def _video_bytes(tmp_path: Path) -> bytes:
    target = tmp_path / "probe.mp4"
    result = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-f", "lavfi", "-i", "color=c=0x17342b:s=320x180:d=1",
         "-vf", "fps=10,format=yuv420p", "-c:v", "libx264", "-movflags", "+faststart", str(target)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return target.read_bytes()


def _upload(client, headers, raw, *, subtitle: bytes, subtitle_name="lesson.vtt", **fields):
    data = {
        "title": "边缘智能导入课",
        "language": "zh-CN",
        "source_url": "https://example.edu/course/video",
        "source_author": "比赛演示课程团队",
        "license_status": "owner_provided",
        "license_text": "上传者声明拥有本地教学演示使用权",
        **fields,
    }
    files = {"video": ("lesson.mp4", raw, "video/mp4")}
    if subtitle_name:
        files["subtitle"] = (subtitle_name, subtitle, "text/vtt")
    return client.post("/api/v1/video-imports", headers=headers, data=data, files=files)


def test_real_import_hash_probe_subtitle_idempotency_version_and_owner(tmp_path):
    raw = _video_bytes(tmp_path)
    first_subtitle = b"WEBVTT\n\n00:00:00.000 --> 00:00:00.900\nEdge intelligence.\n"
    second_subtitle = b"WEBVTT\n\n00:00:00.000 --> 00:00:00.900\nUpdated subtitle.\n"
    with TestClient(app) as client:
        owner = auth_headers(client, "fc_video_import_owner")
        outsider = auth_headers(client, "fc_video_import_outsider")
        created = _upload(client, owner, raw, subtitle=first_subtitle)
        assert created.status_code == 201, created.text
        asset = created.json()
        version = asset["current_version"]
        assert asset["lock_version"] == 1 and asset["idempotent"] is False
        assert version["version_number"] == 1 and version["probe_status"] == "verified_local_ffmpeg"
        assert version["duration_ms"] >= 900 and version["width"] == 320 and version["height"] == 180
        assert len(version["source_sha256"]) == len(version["subtitle_sha256"]) == 64

        duplicate = _upload(client, owner, raw, subtitle=first_subtitle)
        assert duplicate.status_code == 201
        assert duplicate.json()["id"] == asset["id"] and duplicate.json()["idempotent"] is True
        assert len(duplicate.json()["versions"]) == 1

        revised = _upload(
            client, owner, raw, subtitle=second_subtitle,
            asset_id=asset["id"], expected_lock_version="1",
        )
        assert revised.status_code == 201, revised.text
        updated = revised.json()
        assert updated["lock_version"] == 2
        assert updated["current_version"]["version_number"] == 2
        assert len(updated["versions"]) == 2

        stale = _upload(
            client, owner, raw, subtitle=b"WEBVTT\n\n00:00:00.000 --> 00:00:00.900\nThird.\n",
            asset_id=asset["id"], expected_lock_version="1",
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "video_import.version_conflict"

        video_url = f"/api/v1/video-imports/{asset['id']}/versions/{version['id']}/files/video"
        subtitle_url = f"/api/v1/video-imports/{asset['id']}/versions/{version['id']}/files/subtitle"
        assert client.get(video_url, headers=owner).content == raw
        assert client.get(subtitle_url, headers=owner).content == first_subtitle
        assert client.get(video_url, headers=outsider).status_code == 403
        assert client.get(f"/api/v1/video-imports/{asset['id']}", headers=outsider).status_code == 403
        assert client.get("/api/v1/video-imports", headers=outsider).json()["items"] == []


def test_invalid_media_subtitle_source_and_registered_objects(tmp_path):
    raw = _video_bytes(tmp_path)
    with TestClient(app) as client:
        headers = auth_headers(client, "fc_video_import_rejections")
        bad_magic = _upload(client, headers, b"not-video", subtitle=b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nX\n")
        assert bad_magic.status_code == 422
        assert bad_magic.json()["detail"]["code"] == "video_import.media_signature_invalid"
        bad_subtitle = _upload(client, headers, raw, subtitle=b"WEBVTT\nmissing timeline\n")
        assert bad_subtitle.status_code == 422
        insecure = _upload(
            client, headers, raw, subtitle=b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nX\n",
            source_url="http://insecure.example/video",
        )
        assert insecure.status_code == 422
    assert {"video_asset", "video_asset_version"} <= set(OBJECT_SPECS)


def test_video_asset_versions_are_database_immutable(tmp_path):
    raw = _video_bytes(tmp_path)
    subtitle = b"WEBVTT\n\n00:00:00.000 --> 00:00:00.900\nImmutable.\n"
    with TestClient(app) as client:
        headers = auth_headers(client, "fc_video_import_immutable")
        asset = _upload(client, headers, raw, subtitle=subtitle).json()
        version_id = asset["current_version"]["id"]
    with SessionLocal() as db:
        assert db.get(DBVideoAssetVersion, version_id) is not None
        with pytest.raises(DatabaseError, match="immutable"):
            db.execute(text("UPDATE video_asset_versions SET source_sha256='tampered' WHERE id=:id"), {"id": version_id})
            db.commit()
        db.rollback()
        with pytest.raises(DatabaseError, match="immutable"):
            db.execute(text("DELETE FROM video_asset_versions WHERE id=:id"), {"id": version_id})
            db.commit()
        db.rollback()
