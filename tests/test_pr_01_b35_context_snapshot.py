from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.database import DBChatMessage, SessionLocal
from app.main import app
from tests.api_test_helpers import auth_headers


COURSE_ID = "course-machine-learning-foundations-v1"


def _key(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _source_and_point() -> tuple[str, str]:
    from app.database import DBChapter, DBChapterKnowledgePoint, DBSourceDocument, DBSourceRef

    with SessionLocal() as session:
        source = (
            session.query(DBSourceRef)
            .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
            .filter(DBSourceDocument.course_id == COURSE_ID)
            .first()
        )
        relation = (
            session.query(DBChapterKnowledgePoint)
            .join(DBChapter, DBChapter.id == DBChapterKnowledgePoint.chapter_id)
            .filter(DBChapter.course_id == COURSE_ID)
            .first()
        )
        assert source is not None and relation is not None
        return source.id, relation.knowledge_point_id


def test_context_snapshot_freezes_general_run_boundary() -> None:
    with TestClient(app) as client:
        headers = auth_headers(client, _key("b35-context-general"))
        conversation = client.post(
            "/api/v1/chat/conversations", headers=headers, json={"title": "上下文快照"}
        ).json()
        created = client.post(
            f"/api/v1/chat/conversations/{conversation['id']}/messages",
            headers=headers,
            json={"content": "给我一个学习建议", "idempotency_key": _key("message")},
        )
        assert created.status_code == 201, created.text
        user = created.json()["userMessage"]
        assistant = created.json()["assistantMessage"]
        snapshot = assistant["contextSnapshot"]
        assert snapshot["context_snapshot_id"].startswith("ctx-")
        assert snapshot["course_id"] is None
        assert snapshot["source_ref_ids"] == []
        assert snapshot["attachment_ids"] == []
        assert snapshot["conversation_message_ids"] == [user["id"]]
        assert assistant["streamCheckpoint"]["contextSnapshot"] == snapshot
        assert user["contextSnapshot"] == snapshot


def test_context_snapshot_freezes_course_sources_and_scope() -> None:
    source_ref_id, point_id = _source_and_point()
    with TestClient(app) as client:
        headers = auth_headers(client, _key("b35-context-course"))
        conversation = client.post(
            "/api/v1/chat/conversations",
            headers=headers,
            json={"course_id": COURSE_ID, "title": "课程上下文快照"},
        ).json()
        created = client.post(
            f"/api/v1/chat/conversations/{conversation['id']}/messages",
            headers=headers,
            json={
                "content": "解释这个知识点",
                "context_refs": [{"courseId": COURSE_ID, "knowledgePointId": point_id, "sourceRefId": source_ref_id}],
                "idempotency_key": _key("message"),
            },
        )
        assert created.status_code == 201, created.text
        snapshot = created.json()["assistantMessage"]["contextSnapshot"]
        assert snapshot["course_id"] == COURSE_ID
        assert snapshot["course_ids"] == [COURSE_ID]
        assert snapshot["knowledge_scope"] == [point_id]
        assert snapshot["source_ref_ids"] == [source_ref_id]
        assert snapshot["source_snapshot_hash"]
        assert snapshot["context_snapshot_id"].startswith("ctx-")

        with SessionLocal() as session:
            row = session.get(DBChatMessage, created.json()["assistantMessage"]["id"])
            assert row is not None
            assert row.stream_checkpoint["contextSnapshot"] == snapshot


def test_context_snapshot_is_reused_when_stream_context_is_loaded() -> None:
    with TestClient(app) as client:
        username = _key("b35-context-replay")
        headers = auth_headers(client, username)
        conversation = client.post(
            "/api/v1/chat/conversations", headers=headers, json={"title": "快照恢复"}
        ).json()
        created = client.post(
            f"/api/v1/chat/conversations/{conversation['id']}/messages",
            headers=headers,
            json={"content": "继续解释", "idempotency_key": _key("message")},
        )
        assert created.status_code == 201, created.text
        assistant = created.json()["assistantMessage"]
        with SessionLocal() as session:
            from app.chat_api import load_stream_context
            from app.database import DBUser

            actor = session.query(DBUser).filter_by(username=username).first()
            assert actor is not None
            loaded = load_stream_context(session, actor, created.json()["userMessage"]["id"])
            assert loaded["context_snapshot"] == assistant["contextSnapshot"]
