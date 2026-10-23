from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient

import app.chat_api as chat_api
from app.database import DBSourceDocument, DBSourceRef, SessionLocal
from app.main import app
from tests.api_test_helpers import auth_headers


COURSE_ID = "course-machine-learning-foundations-v1"


def _key(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _source_ref_id() -> str:
    with SessionLocal() as session:
        row = (
            session.query(DBSourceRef)
            .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
            .filter(DBSourceDocument.course_id == COURSE_ID)
            .order_by(DBSourceRef.id)
            .first()
        )
        assert row is not None
        return row.id


def test_selected_course_automatically_freezes_authorized_course_sources() -> None:
    with TestClient(app) as client:
        headers = auth_headers(client, _key("b35-auto-source"))
        conversation = client.post(
            "/api/v1/chat/conversations",
            headers=headers,
            json={"course_id": COURSE_ID, "title": "自动课程来源"},
        )
        assert conversation.status_code == 201, conversation.text
        response = client.post(
            f"/api/v1/chat/conversations/{conversation.json()['id']}/messages",
            headers=headers,
            json={"content": "根据当前课程资料解释这个概念", "idempotency_key": _key("message")},
        )
        assert response.status_code == 201, response.text
        assistant = response.json()["assistantMessage"]
        refs = assistant["sourceRefs"]
        assert refs
        assert all(ref["courseId"] == COURSE_ID for ref in refs)
        assert assistant["contextSnapshot"]["source_ref_ids"]


def test_source_version_conflict_is_preserved_for_level_d_run(monkeypatch) -> None:
    source_ref_id = _source_ref_id()
    original = chat_api.project_source_ref

    def conflicted(*args, **kwargs):
        projection = original(*args, **kwargs)
        if str(args[1]) == source_ref_id:
            projection.update({
                "available": False,
                "reason_code": "source_ref_version_changed",
                "reason": "来源解析版本已变化",
            })
        return projection

    monkeypatch.setattr(chat_api, "project_source_ref", conflicted)
    with TestClient(app) as client:
        headers = auth_headers(client, _key("b35-conflict-source"))
        conversation = client.post(
            "/api/v1/chat/conversations",
            headers=headers,
            json={"course_id": COURSE_ID, "title": "来源冲突"},
        )
        assert conversation.status_code == 201, conversation.text
        response = client.post(
            f"/api/v1/chat/conversations/{conversation.json()['id']}/messages",
            headers=headers,
            json={
                "content": "请严格依据这份课程资料回答",
                "context_refs": [{"courseId": COURSE_ID, "sourceRefId": source_ref_id}],
                "idempotency_key": _key("message"),
            },
        )
        assert response.status_code == 201, response.text
        refs = response.json()["assistantMessage"]["sourceRefs"]
        conflicted_ref = next(ref for ref in refs if ref["sourceRefId"] == source_ref_id)
        assert conflicted_ref["available"] is False
        assert conflicted_ref["reasonCode"] == "source_ref_version_changed"


def test_chat_source_and_attachment_inspector_contract_is_present() -> None:
    source = Path("frontend/src/views/Chat.vue").read_text(encoding="utf-8")
    assert "候选但未采用来源" in source
    assert "打开课程知识库" in source
    assert "重新选择/上传附件" in source
    assert "chat-candidate-source-list" in source
