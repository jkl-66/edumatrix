from __future__ import annotations

import hashlib
import json
import uuid
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from app.database import (
    DBChatAttachment,
    DBChatMessage,
    DBChapter,
    DBChapterKnowledgePoint,
    DBGenerationTask,
    DBLearningEvent,
    DBProfileSnapshot,
    DBSourceDocument,
    DBSourceRef,
    DBStudentProfile,
    DBUser,
    SessionLocal,
)
from app.main import app
from tests.api_test_helpers import auth_headers


FLAGSHIP_COURSE_ID = "course-machine-learning-foundations-v1"


def _key(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _protected_counts() -> dict[str, int]:
    with SessionLocal() as session:
        return {
            "events": session.query(DBLearningEvent).count(),
            "source_documents": session.query(DBSourceDocument).count(),
            "source_refs": session.query(DBSourceRef).count(),
        }


def _conversation(client: TestClient, headers: dict[str, str], *, course_id: str | None = None) -> dict:
    payload = {"title": "F7 智能对话测试"}
    if course_id:
        payload["course_id"] = course_id
    response = client.post("/api/v1/chat/conversations", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _upload(
    client: TestClient,
    headers: dict[str, str],
    conversation_id: str,
    *,
    filename: str,
    raw: bytes,
    mime_type: str,
) -> dict:
    response = client.post(
        f"/api/v1/chat/conversations/{conversation_id}/attachments",
        headers=headers,
        data={"idempotency_key": _key("attachment")},
        files={"file": (filename, raw, mime_type)},
    )
    assert response.status_code == 201, response.text
    return response.json()["attachment"]


def _parse(client: TestClient, headers: dict[str, str], attachment: dict) -> dict:
    response = client.post(
        f"/api/v1/chat/attachments/{attachment['id']}/parse",
        headers=headers,
        json={"expected_lock_version": attachment["lockVersion"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _course_context() -> dict[str, str]:
    with SessionLocal() as session:
        source_ref = (
            session.query(DBSourceRef)
            .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
            .filter(DBSourceDocument.course_id == FLAGSHIP_COURSE_ID)
            .first()
        )
        relation = (
            session.query(DBChapterKnowledgePoint)
            .join(DBChapter, DBChapter.id == DBChapterKnowledgePoint.chapter_id)
            .filter(DBChapter.course_id == FLAGSHIP_COURSE_ID)
            .first()
        )
        assert source_ref is not None and relation is not None
        return {
            "source_ref_id": source_ref.id,
            "knowledge_point_id": relation.knowledge_point_id,
        }


def _add_profile_snapshot(username: str) -> str:
    with SessionLocal() as session:
        user = session.query(DBUser).filter_by(username=username).one()
        body = {"goal": "理解当前知识点", "preference": "图文与练习"}
        snapshot = DBProfileSnapshot(
            owner_public_id=user.public_id,
            legacy_student_id=username,
            profile_version="f7-t04-resource-v1",
            snapshot=body,
            content_hash=hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest(),
            trace_id=_key("profile"),
        )
        session.add(snapshot)
        session.commit()
        return snapshot.id


def _complete_assistant(assistant_id: str, *, content: str = "这是有来源约束的回答。") -> dict:
    with SessionLocal() as session:
        row = session.get(DBChatMessage, assistant_id)
        assert row is not None
        row.status = "completed"
        row.content = content
        row.content_sha256 = hashlib.sha256(content.encode()).hexdigest()
        row.lock_version += 1
        session.commit()
        session.refresh(row)
        return {"id": row.id, "lockVersion": row.lock_version}


def _learner_state(username: str) -> dict:
    with SessionLocal() as session:
        user = session.query(DBUser).filter_by(username=username).one()
        profile = session.get(DBStudentProfile, username)
        return {
            "events": session.query(DBLearningEvent).filter_by(owner_public_id=user.public_id).count(),
            "profile_snapshots": session.query(DBProfileSnapshot).filter_by(owner_public_id=user.public_id).count(),
            "mastery": json.dumps(
                {
                    "concept_mastery": profile.concept_mastery if profile else {},
                    "dimension_states": profile.dimension_states if profile else {},
                    "weak_points": profile.weak_points if profile else [],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        }


def _answer_message(
    client: TestClient,
    headers: dict[str, str],
    *,
    course_id: str | None,
    context_refs: list[dict],
    complete: bool = True,
) -> dict:
    conversation = _conversation(client, headers, course_id=course_id)
    response = client.post(
        f"/api/v1/chat/conversations/{conversation['id']}/messages",
        headers=headers,
        json={
            "content": "请解释当前知识点。",
            "attachment_ids": [],
            "context_refs": context_refs,
            "idempotency_key": _key("message"),
        },
    )
    assert response.status_code == 201, response.text
    assistant = response.json()["assistantMessage"]
    return _complete_assistant(assistant["id"]) if complete else assistant


def test_attachment_parse_message_recovery_and_owner_scope(monkeypatch) -> None:
    class NoLocalOcr:
        def runtime(self):
            return False, ""

    monkeypatch.setattr("app.media_ocr.RapidOCROfflineAdapter", NoLocalOcr)
    with TestClient(app) as client:
        before = _protected_counts()
        headers = auth_headers(client, _key("f7_t04_owner"))
        other_headers = auth_headers(client, _key("f7_t04_other"))
        conversation = _conversation(client, headers)

        markdown = _upload(
            client,
            headers,
            conversation["id"],
            filename="gradient-descent.md",
            raw="# 梯度下降\n\n学习率控制每次参数更新的步长。".encode("utf-8"),
            mime_type="text/markdown",
        )
        assert markdown["status"] == "queued"
        markdown = _parse(client, headers, markdown)
        assert markdown["status"] == "ready"
        assert markdown["canSend"] is True
        assert "学习率" in markdown["parsedPreview"]

        image_buffer = BytesIO()
        Image.new("RGB", (80, 40), color="white").save(image_buffer, format="PNG")
        image = _upload(
            client,
            headers,
            conversation["id"],
            filename="loss-curve.png",
            raw=image_buffer.getvalue(),
            mime_type="image/png",
        )
        image = _parse(client, headers, image)
        assert image["status"] == "ready"
        assert image["summary"] == {"width": 80, "height": 40, "ocr_region_count": 0}
        assert any("OCR" in item for item in image["warnings"])

        message_key = _key("message")
        message_payload = {
            "content": "结合附件解释学习率过大的表现。",
            "attachment_ids": [markdown["id"], image["id"]],
            "context_refs": [],
            "idempotency_key": message_key,
            "return_to": "/workspace/resources",
        }
        created = client.post(
            f"/api/v1/chat/conversations/{conversation['id']}/messages",
            headers=headers,
            json=message_payload,
        )
        replay = client.post(
            f"/api/v1/chat/conversations/{conversation['id']}/messages",
            headers=headers,
            json=message_payload,
        )
        assert created.status_code == 201, created.text
        assert replay.status_code == 201, replay.text
        assert created.json()["created"] is True
        assert replay.json()["created"] is False
        assert created.json()["userMessage"]["id"] == replay.json()["userMessage"]["id"]
        assert created.json()["assistantMessage"]["status"] == "queued"
        assert len(created.json()["userMessage"]["sourceRefs"]) == 2

        recovered = client.get(
            f"/api/v1/chat/conversations/{conversation['id']}",
            headers=headers,
        )
        assert recovered.status_code == 200, recovered.text
        assert len(recovered.json()["messages"]) == 2
        assert len(recovered.json()["attachments"]) == 2
        assert client.get(
            f"/api/v1/chat/conversations/{conversation['id']}",
            headers=other_headers,
        ).status_code == 404
        assert _protected_counts() == before


def test_failed_parse_blocks_send_and_retry_only_replays_attachment(monkeypatch) -> None:
    calls = {"count": 0}

    def parse_once(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary parser outage")
        return {
            "status": "ready",
            "text": "恢复后的解析正文",
            "parser_version": "test-parser-v1",
            "locations": [{"kind": "document", "index": 1, "label": "notes.txt"}],
            "metadata": {},
            "warnings": [],
        }

    monkeypatch.setattr("app.chat_api._parse_attachment_bytes", parse_once)
    with TestClient(app) as client:
        headers = auth_headers(client, _key("f7_t04_retry"))
        conversation = _conversation(client, headers)
        attachment = _upload(
            client,
            headers,
            conversation["id"],
            filename="notes.txt",
            raw=b"retry me",
            mime_type="text/plain",
        )
        failed = _parse(client, headers, attachment)
        assert failed["status"] == "failed_retryable"
        assert failed["failure"]["code"] == "attachment_parse_failed"
        blocked = client.post(
            f"/api/v1/chat/conversations/{conversation['id']}/messages",
            headers=headers,
            json={
                "content": "解释附件",
                "attachment_ids": [failed["id"]],
                "context_refs": [],
                "idempotency_key": _key("message"),
            },
        )
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "chat_attachment_not_ready"

        recovered = _parse(client, headers, failed)
        assert recovered["status"] == "ready"
        assert recovered["parsedPreview"] == "恢复后的解析正文"
        assert calls["count"] == 2


def test_partial_failure_requires_confirmation_and_removed_is_terminal(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.chat_api._parse_attachment_bytes",
        lambda *_args, **_kwargs: {
            "status": "partial_failed",
            "text": "已读取的部分内容",
            "parser_version": "partial-parser-v1",
            "locations": [{"kind": "page", "index": 1, "label": "第 1 页"}],
            "metadata": {"page_count": 2},
            "warnings": ["第 2 页无法读取"],
            "error_code": "page_parse_partial",
            "error_message": "部分页面解析失败，可确认后使用已读取内容。",
            "retryable": True,
        },
    )
    with TestClient(app) as client:
        headers = auth_headers(client, _key("f7_t04_partial"))
        conversation = _conversation(client, headers)
        attachment = _upload(
            client,
            headers,
            conversation["id"],
            filename="partial.pdf",
            raw=b"synthetic-pdf",
            mime_type="application/pdf",
        )
        partial = _parse(client, headers, attachment)
        assert partial["status"] == "partial_failed"
        assert partial["canSend"] is False

        blocked = client.post(
            f"/api/v1/chat/conversations/{conversation['id']}/messages",
            headers=headers,
            json={
                "content": "使用可用部分回答",
                "attachment_ids": [partial["id"]],
                "context_refs": [],
                "idempotency_key": _key("message"),
            },
        )
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "chat_attachment_partial_confirmation_required"

        confirmed = client.post(
            f"/api/v1/chat/attachments/{partial['id']}/confirm-partial",
            headers=headers,
            json={"expected_lock_version": partial["lockVersion"]},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["canSend"] is True
        sent = client.post(
            f"/api/v1/chat/conversations/{conversation['id']}/messages",
            headers=headers,
            json={
                "content": "使用可用部分回答",
                "attachment_ids": [partial["id"]],
                "context_refs": [],
                "idempotency_key": _key("message"),
            },
        )
        assert sent.status_code == 201, sent.text

        removed = client.post(
            f"/api/v1/chat/attachments/{partial['id']}/remove",
            headers=headers,
            json={"expected_lock_version": confirmed.json()["lockVersion"]},
        )
        assert removed.status_code == 200, removed.text
        assert removed.json()["status"] == "removed"
        assert removed.json()["canSend"] is False
        assert client.post(
            f"/api/v1/chat/attachments/{partial['id']}/parse",
            headers=headers,
            json={"expected_lock_version": removed.json()["lockVersion"]},
        ).status_code == 409
        with SessionLocal() as session:
            row = session.get(DBChatAttachment, partial["id"])
            assert row is not None
            assert row.raw_bytes == b""


def test_context_ref_is_frozen_without_learning_evidence_and_stop_continue_are_recoverable() -> None:
    with TestClient(app) as client:
        before = _protected_counts()
        with SessionLocal() as session:
            source_ref = (
                session.query(DBSourceRef)
                .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
                .filter(DBSourceDocument.course_id == FLAGSHIP_COURSE_ID)
                .first()
            )
            assert source_ref is not None
            source_ref_id = source_ref.id
        headers = auth_headers(client, _key("f7_t04_context"))
        conversation = _conversation(client, headers, course_id=FLAGSHIP_COURSE_ID)
        created = client.post(
            f"/api/v1/chat/conversations/{conversation['id']}/messages",
            headers=headers,
            json={
                "content": "解释这个来源中的核心结论。",
                "attachment_ids": [],
                "context_refs": [{"courseId": FLAGSHIP_COURSE_ID, "sourceRefId": source_ref_id}],
                "idempotency_key": _key("message"),
                "return_to": "/knowledge",
            },
        )
        assert created.status_code == 201, created.text
        payload = created.json()
        assert payload["userMessage"]["contextRefs"][0]["sourceRef"]["id"] == source_ref_id
        assert payload["userMessage"]["sourceRefs"][0]["sourceRefId"] == source_ref_id

        assistant = payload["assistantMessage"]
        stopped = client.post(
            f"/api/v1/chat/messages/{assistant['id']}/stop",
            headers=headers,
            json={"expected_lock_version": assistant["lockVersion"]},
        )
        assert stopped.status_code == 200, stopped.text
        assert stopped.json()["status"] == "stopped"
        continued = client.post(
            f"/api/v1/chat/messages/{assistant['id']}/continue",
            headers=headers,
            json={"expected_lock_version": stopped.json()["lockVersion"]},
        )
        assert continued.status_code == 200, continued.text
        assert continued.json()["status"] == "queued"
        serialized = json.dumps(payload, ensure_ascii=False).lower()
        for forbidden in ("api_key", "chain_of_thought", "reasoning_content", "system_prompt", "raw_log"):
            assert forbidden not in serialized
        assert _protected_counts() == before


def test_legacy_ppt_enters_recoverable_parse_protocol_and_unsupported_format_is_rejected_honestly(monkeypatch) -> None:
    import document_parser

    monkeypatch.setattr(document_parser.shutil, "which", lambda _name: None)
    with TestClient(app) as client:
        headers = auth_headers(client, _key("f7_t04_formats"))
        conversation = _conversation(client, headers)
        legacy = client.post(
            f"/api/v1/chat/conversations/{conversation['id']}/attachments",
            headers=headers,
            data={"idempotency_key": _key("attachment")},
            files={"file": ("legacy.ppt", b"legacy", "application/vnd.ms-powerpoint")},
        )
        assert legacy.status_code == 201, legacy.text
        attachment = legacy.json()["attachment"]
        parsed = client.post(
            f"/api/v1/chat/attachments/{attachment['id']}/parse",
            headers=headers,
            json={"expected_lock_version": attachment["lockVersion"]},
        )
        assert parsed.status_code == 200, parsed.text
        assert parsed.json()["status"] == "failed_retryable"
        assert parsed.json()["failure"]["code"] == "legacy_ppt_converter_unavailable"
        assert parsed.json()["failure"]["retryable"] is True
        unsupported = client.post(
            f"/api/v1/chat/conversations/{conversation['id']}/attachments",
            headers=headers,
            data={"idempotency_key": _key("attachment")},
            files={"file": ("archive.zip", b"zip", "application/zip")},
        )
        assert unsupported.status_code == 422
        assert unsupported.json()["detail"]["code"] == "chat_attachment_format_unsupported"


def test_completed_answer_creates_idempotent_compact_resource_link_without_learning_mutation() -> None:
    username = _key("f7_t04_resource")
    context = _course_context()
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        _add_profile_snapshot(username)
        assistant = _answer_message(
            client,
            headers,
            course_id=FLAGSHIP_COURSE_ID,
            context_refs=[{
                "courseId": FLAGSHIP_COURSE_ID,
                "knowledgePointId": context["knowledge_point_id"],
                "sourceRefId": context["source_ref_id"],
            }],
        )
        before = _learner_state(username)
        first = client.post(
            f"/api/v1/chat/messages/{assistant['id']}/resource-actions",
            headers=headers,
            json={"resource_type": "quiz", "expected_lock_version": assistant["lockVersion"]},
        )
        assert first.status_code == 201, first.text
        first_payload = first.json()
        assert first_payload["created"] is True
        assert first_payload["job"]["scope"] == "single"
        assert first_payload["job"]["items"][0]["type"] == "quiz"
        assert first_payload["job"]["items"][0]["resource"] is None
        link = first_payload["resourceLink"]
        assert link == first_payload["message"]["resourceLinks"][0]
        assert link["kind"] == "generation_job"
        assert link["route"] == f"/workspace/resources/bundles/{link['taskId']}"
        assert "job" not in first_payload["message"]
        assert "items" not in first_payload["message"]

        replay = client.post(
            f"/api/v1/chat/messages/{assistant['id']}/resource-actions",
            headers=headers,
            json={
                "resource_type": "quiz",
                "expected_lock_version": first_payload["message"]["lockVersion"],
            },
        )
        assert replay.status_code == 201, replay.text
        assert replay.json()["created"] is False
        assert replay.json()["resourceLink"] == link
        assert len(replay.json()["message"]["resourceLinks"]) == 1

        stale = client.post(
            f"/api/v1/chat/messages/{assistant['id']}/resource-actions",
            headers=headers,
            json={"resource_type": "handout", "expected_lock_version": assistant["lockVersion"]},
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "chat_message_conflict"
        assert _learner_state(username) == before
        with SessionLocal() as session:
            assert session.query(DBGenerationTask).filter_by(id=link["taskId"]).count() == 1


def test_resource_action_rejects_incomplete_answer_and_missing_context_honestly() -> None:
    context = _course_context()
    with TestClient(app) as client:
        incomplete_user = _key("f7_t04_incomplete")
        incomplete_headers = auth_headers(client, incomplete_user)
        queued = _answer_message(
            client,
            incomplete_headers,
            course_id=FLAGSHIP_COURSE_ID,
            context_refs=[],
            complete=False,
        )
        incomplete = client.post(
            f"/api/v1/chat/messages/{queued['id']}/resource-actions",
            headers=incomplete_headers,
            json={"resource_type": "handout", "expected_lock_version": queued["lockVersion"]},
        )
        assert incomplete.status_code == 409
        assert incomplete.json()["detail"]["code"] == "chat_resource_answer_incomplete"

        no_course_user = _key("f7_t04_no_course")
        no_course_headers = auth_headers(client, no_course_user)
        _add_profile_snapshot(no_course_user)
        no_course_message = _answer_message(
            client,
            no_course_headers,
            course_id=None,
            context_refs=[],
        )
        no_course = client.post(
            f"/api/v1/chat/messages/{no_course_message['id']}/resource-actions",
            headers=no_course_headers,
            json={
                "resource_type": "handout",
                "expected_lock_version": no_course_message["lockVersion"],
                "knowledge_point_id": context["knowledge_point_id"],
            },
        )
        assert no_course.status_code == 422
        assert no_course.json()["detail"]["code"] == "chat_resource_course_required"

        no_point_user = _key("f7_t04_no_point")
        no_point_headers = auth_headers(client, no_point_user)
        _add_profile_snapshot(no_point_user)
        no_point_message = _answer_message(
            client,
            no_point_headers,
            course_id=FLAGSHIP_COURSE_ID,
            context_refs=[{
                "courseId": FLAGSHIP_COURSE_ID,
                "sourceRefId": context["source_ref_id"],
            }],
        )
        no_point = client.post(
            f"/api/v1/chat/messages/{no_point_message['id']}/resource-actions",
            headers=no_point_headers,
            json={"resource_type": "handout", "expected_lock_version": no_point_message["lockVersion"]},
        )
        assert no_point.status_code == 422
        assert no_point.json()["detail"]["code"] == "chat_resource_knowledge_point_required"

        no_source_user = _key("f7_t04_no_source")
        no_source_headers = auth_headers(client, no_source_user)
        _add_profile_snapshot(no_source_user)
        no_source_message = _answer_message(
            client,
            no_source_headers,
            course_id=FLAGSHIP_COURSE_ID,
            context_refs=[{
                "courseId": FLAGSHIP_COURSE_ID,
                "knowledgePointId": context["knowledge_point_id"],
            }],
        )
        no_source = client.post(
            f"/api/v1/chat/messages/{no_source_message['id']}/resource-actions",
            headers=no_source_headers,
            json={"resource_type": "mind_map", "expected_lock_version": no_source_message["lockVersion"]},
        )
        assert no_source.status_code == 422
        assert no_source.json()["detail"]["code"] == "chat_resource_source_required"

        no_profile_user = _key("f7_t04_no_profile")
        no_profile_headers = auth_headers(client, no_profile_user)
        no_profile_message = _answer_message(
            client,
            no_profile_headers,
            course_id=FLAGSHIP_COURSE_ID,
            context_refs=[{
                "courseId": FLAGSHIP_COURSE_ID,
                "knowledgePointId": context["knowledge_point_id"],
                "sourceRefId": context["source_ref_id"],
            }],
        )
        no_profile = client.post(
            f"/api/v1/chat/messages/{no_profile_message['id']}/resource-actions",
            headers=no_profile_headers,
            json={"resource_type": "quiz", "expected_lock_version": no_profile_message["lockVersion"]},
        )
        assert no_profile.status_code == 422
        assert no_profile.json()["detail"]["code"] == "chat_resource_profile_required"
