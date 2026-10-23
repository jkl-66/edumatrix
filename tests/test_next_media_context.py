from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DatabaseError

from app.database import DBAuditLog, DBMediaContextResource, DBMediaMessage, SessionLocal
from app.main import app
from tests.api_test_helpers import auth_headers


def _create(client: TestClient, headers: dict[str, str], **overrides):
    payload = {
        "resource_type": "code",
        "title": "RAG reranker lab",
        "language": "python",
        "content": "def rank(items):\n    return sorted(items)\n\nprint(rank([3, 1, 2]))\n",
        "locator": "",
        "duration_ms": 0,
    }
    payload.update(overrides)
    return client.post("/api/v1/media-context/resources", headers=headers, json=payload)


def test_code_and_video_positions_conversations_switch_and_refresh():
    with TestClient(app) as client:
        headers = auth_headers(client, "nc_media_04_owner")
        code = _create(client, headers)
        video = _create(
            client, headers, resource_type="video", title="Vector search walkthrough",
            language="", content="", locator="/media/vector-search.mp4", duration_ms=180_000,
        )
        assert code.status_code == video.status_code == 201
        code_body, video_body = code.json(), video.json()
        assert code_body["content_sha256"] == hashlib.sha256(code_body["content"].encode()).hexdigest()
        assert video_body["content_sha256"] == hashlib.sha256(video_body["locator"].encode()).hexdigest()

        code_position = client.put(
            f"/api/v1/media-context/resources/{code_body['id']}/position", headers=headers,
            json={"expected_lock_version": 1, "line_number": 4, "column_number": 7, "playback_ms": 0, "scroll_ratio": 0.75},
        )
        video_position = client.put(
            f"/api/v1/media-context/resources/{video_body['id']}/position", headers=headers,
            json={"expected_lock_version": 1, "line_number": 1, "column_number": 1, "playback_ms": 42_500, "scroll_ratio": 0.24},
        )
        assert code_position.status_code == video_position.status_code == 200
        assert code_position.json()["line_number"] == 4
        assert video_position.json()["playback_ms"] == 42_500

        conversation = client.post(
            f"/api/v1/media-context/resources/{code_body['id']}/conversations", headers=headers,
            json={"title": "Reranker investigation"},
        )
        assert conversation.status_code == 201
        conversation_id = conversation.json()["id"]
        message = client.post(
            f"/api/v1/media-context/conversations/{conversation_id}/messages", headers=headers,
            json={"expected_lock_version": 1, "role": "note", "content": "Line 4 verifies stable ordering."},
        )
        assert message.status_code == 201
        assert message.json()["messages"][0]["position_snapshot"]["line_number"] == 4

        restored_code = client.get(f"/api/v1/media-context/resources/{code_body['id']}", headers=headers)
        restored_video = client.get(f"/api/v1/media-context/resources/{video_body['id']}", headers=headers)
        assert restored_code.json()["position"]["line_number"] == 4
        assert restored_code.json()["conversations"][0]["messages"][0]["content"] == "Line 4 verifies stable ordering."
        assert restored_video.json()["position"]["playback_ms"] == 42_500
        assert restored_video.json()["conversations"] == []


def test_optimistic_conflicts_validation_and_archive_truth():
    with TestClient(app) as client:
        headers = auth_headers(client, "nc_media_04_conflict")
        resource = _create(client, headers).json()
        first = client.put(
            f"/api/v1/media-context/resources/{resource['id']}/position", headers=headers,
            json={"expected_lock_version": 1, "line_number": 2, "column_number": 1, "playback_ms": 0, "scroll_ratio": 0.2},
        )
        stale = client.put(
            f"/api/v1/media-context/resources/{resource['id']}/position", headers=headers,
            json={"expected_lock_version": 1, "line_number": 3, "column_number": 1, "playback_ms": 0, "scroll_ratio": 0.4},
        )
        outside = client.put(
            f"/api/v1/media-context/resources/{resource['id']}/position", headers=headers,
            json={"expected_lock_version": 2, "line_number": 99, "column_number": 1, "playback_ms": 0, "scroll_ratio": 0.4},
        )
        assert first.status_code == 200
        assert stale.status_code == 409 and stale.json()["detail"]["code"] == "media_position_conflict"
        assert outside.status_code == 422

        bad_url = _create(client, headers, resource_type="video", content="", locator="javascript:alert(1)")
        insecure_url = _create(client, headers, resource_type="video", content="", locator="http://example.com/video.mp4")
        fake_assistant = client.post(
            f"/api/v1/media-context/resources/{resource['id']}/conversations", headers=headers,
            json={"title": "Responsibility boundary"},
        ).json()
        rejected_role = client.post(
            f"/api/v1/media-context/conversations/{fake_assistant['id']}/messages", headers=headers,
            json={"expected_lock_version": 1, "role": "assistant", "content": "fabricated answer"},
        )
        assert bad_url.status_code == insecure_url.status_code == 422
        assert rejected_role.status_code == 422

        archived = client.post(
            f"/api/v1/media-context/conversations/{fake_assistant['id']}/archive", headers=headers,
            json={"expected_lock_version": 1},
        )
        after_archive = client.post(
            f"/api/v1/media-context/conversations/{fake_assistant['id']}/messages", headers=headers,
            json={"expected_lock_version": 2, "role": "note", "content": "late note"},
        )
        assert archived.status_code == 200 and archived.json()["status"] == "archived"
        assert after_archive.status_code == 409


def test_cross_owner_all_reads_and_mutations_are_forbidden():
    with TestClient(app) as client:
        owner = auth_headers(client, "nc_media_04_private_owner")
        other = auth_headers(client, "nc_media_04_private_other")
        resource = _create(client, owner).json()
        conversation = client.post(
            f"/api/v1/media-context/resources/{resource['id']}/conversations", headers=owner,
            json={"title": "Private code notes"},
        ).json()
        attempts = [
            client.get(f"/api/v1/media-context/resources/{resource['id']}", headers=other),
            client.put(f"/api/v1/media-context/resources/{resource['id']}/position", headers=other,
                       json={"expected_lock_version": 1, "line_number": 1, "column_number": 1, "playback_ms": 0, "scroll_ratio": 0}),
            client.post(f"/api/v1/media-context/resources/{resource['id']}/conversations", headers=other,
                        json={"title": "stolen"}),
            client.get(f"/api/v1/media-context/conversations/{conversation['id']}", headers=other),
            client.post(f"/api/v1/media-context/conversations/{conversation['id']}/messages", headers=other,
                        json={"expected_lock_version": 1, "role": "note", "content": "stolen"}),
            client.post(f"/api/v1/media-context/conversations/{conversation['id']}/archive", headers=other,
                        json={"expected_lock_version": 1}),
        ]
        assert [item.status_code for item in attempts] == [403] * len(attempts)
        listing = client.get("/api/v1/media-context/resources", headers=other)
        assert listing.status_code == 200 and listing.json()["items"] == []


def test_messages_and_resources_are_immutable_and_audits_exclude_bodies():
    private_code = "secret_training_value = 42"
    private_note = "Investigate the private training value."
    with TestClient(app) as client:
        headers = auth_headers(client, "nc_media_04_immutable")
        resource = _create(client, headers, content=private_code).json()
        conversation = client.post(
            f"/api/v1/media-context/resources/{resource['id']}/conversations", headers=headers,
            json={"title": "Private investigation"},
        ).json()
        completed = client.post(
            f"/api/v1/media-context/conversations/{conversation['id']}/messages", headers=headers,
            json={"expected_lock_version": 1, "role": "note", "content": private_note},
        ).json()
        message_id = completed["messages"][0]["id"]
        with SessionLocal() as db:
            with pytest.raises(DatabaseError):
                db.query(DBMediaContextResource).filter_by(id=resource["id"]).update({"title": "tampered"})
            db.rollback()
            with pytest.raises(DatabaseError):
                db.query(DBMediaMessage).filter_by(id=message_id).update({"content": "tampered"})
            db.rollback()
            audits = db.query(DBAuditLog).filter(DBAuditLog.object_type.in_(["media_resource", "media_conversation", "media_message"])).all()
            assert audits
            serialized = " ".join(str(item.metadata_json) for item in audits)
            assert private_code not in serialized
            assert private_note not in serialized
            assert "Private investigation" not in serialized
