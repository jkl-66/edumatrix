from __future__ import annotations

import json
import uuid

from fastapi.testclient import TestClient

import stream_api
from app.database import (
    DBLearningEvent,
    DBSourceDocument,
    DBSourceRef,
    SessionLocal,
)
from app.main import app
from tests.api_test_helpers import auth_headers


FLAGSHIP_COURSE_ID = "course-machine-learning-foundations-v1"


def _key(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _events(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    event_name = ""
    for line in text.splitlines():
        if line.startswith("event: "):
            event_name = line[7:]
        elif line.startswith("data: "):
            events.append((event_name, json.loads(line[6:])))
    return events


def _protected_counts() -> dict[str, int]:
    with SessionLocal() as session:
        return {
            "events": session.query(DBLearningEvent).count(),
            "source_documents": session.query(DBSourceDocument).count(),
            "source_refs": session.query(DBSourceRef).count(),
        }


class _FakeLLM:
    model = "f7-t04-stream-test"
    has_vision = True

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def generate_stream(self, system_prompt, user_prompt, *, role, images):
        self.calls.append({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "role": role,
            "images": images,
        })
        yield "先给出直接回答，"
        yield "再说明依据与下一步。"


class _FakeSwarm:
    def __init__(self, llm: _FakeLLM) -> None:
        self.llm = llm


def test_canonical_stream_uses_persisted_context_and_replays_without_second_model_call(monkeypatch) -> None:
    llm = _FakeLLM()
    monkeypatch.setattr(stream_api, "build_swarm_from_headers", lambda _headers: _FakeSwarm(llm))

    with TestClient(app) as client:
        owner = _key("f7_t04_stream")
        headers = auth_headers(client, owner)
        with SessionLocal() as session:
            source_ref = (
                session.query(DBSourceRef)
                .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
                .filter(DBSourceDocument.course_id == FLAGSHIP_COURSE_ID)
                .first()
            )
            assert source_ref is not None
            source_ref_id = source_ref.id

        conversation_response = client.post(
            "/api/v1/chat/conversations",
            headers=headers,
            json={"title": "canonical stream", "course_id": FLAGSHIP_COURSE_ID},
        )
        assert conversation_response.status_code == 201, conversation_response.text
        conversation = conversation_response.json()

        uploaded = client.post(
            f"/api/v1/chat/conversations/{conversation['id']}/attachments",
            headers=headers,
            data={"idempotency_key": _key("attachment")},
            files={
                "file": (
                    "learning-rate.md",
                    "# 学习率\n\n学习率过大会导致损失震荡。".encode("utf-8"),
                    "text/markdown",
                )
            },
        )
        assert uploaded.status_code == 201, uploaded.text
        attachment = uploaded.json()["attachment"]
        parsed = client.post(
            f"/api/v1/chat/attachments/{attachment['id']}/parse",
            headers=headers,
            json={"expected_lock_version": attachment["lockVersion"]},
        )
        assert parsed.status_code == 200, parsed.text

        created = client.post(
            f"/api/v1/chat/conversations/{conversation['id']}/messages",
            headers=headers,
            json={
                "content": "解释学习率过大时为什么会震荡。",
                "attachment_ids": [attachment["id"]],
                "context_refs": [
                    {"courseId": FLAGSHIP_COURSE_ID, "sourceRefId": source_ref_id}
                ],
                "idempotency_key": _key("message"),
                "return_to": "/knowledge",
            },
        )
        assert created.status_code == 201, created.text
        user_message_id = created.json()["userMessage"]["id"]
        before = _protected_counts()

        legacy_payload = {
            "student_id": owner,
            "user_message_id": user_message_id,
            "message": "/matrix 这段客户端文本不应替换已保存问题",
            "mode": "matrix",
            "images": ["data:image/png;base64,client-payload-must-be-ignored"],
            "active_doc_ids": ["client-document-must-be-ignored"],
        }
        response = client.post(
            "/api/stream/chat", headers=headers, json=legacy_payload
        )
        assert response.status_code == 200, response.text
        events = _events(response.text)
        assert [name for name, _data in events].count("complete") == 1
        complete = next(data for name, data in events if name == "complete")
        assert complete["content"] == "先给出直接回答，再说明理由与下一步。"
        assert complete["resource_links"] == []
        assert complete["source_refs"][0]["sourceRefId"] == source_ref_id
        assert complete["message"]["status"] == "completed"
        assert len(llm.calls) == 1
        call = llm.calls[0]
        assert "解释学习率过大时为什么会震荡" in call["user_prompt"]
        assert "学习率过大会导致损失震荡" in call["user_prompt"]
        assert "[S1]" in call["user_prompt"]
        assert "客户端文本不应替换" not in call["user_prompt"]
        assert call["images"] == []
        assert _protected_counts() == before

        replay = client.post(
            "/api/stream/chat", headers=headers, json=legacy_payload
        )
        assert replay.status_code == 200, replay.text
        replay_events = _events(replay.text)
        replay_complete = next(data for name, data in replay_events if name == "complete")
        assert replay_complete["replayed"] is True
        assert replay_complete["content"] == complete["content"]
        assert len(llm.calls) == 1
        assert _protected_counts() == before

        serialized = (response.text + replay.text).lower()
        for forbidden in (
            "api_key",
            "chain_of_thought",
            "reasoning_content",
            "system_prompt",
            "raw_log",
        ):
            assert forbidden not in serialized
