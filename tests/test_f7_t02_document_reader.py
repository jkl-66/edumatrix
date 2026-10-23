from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

from app.database import (
    DBChapter,
    DBCourse,
    DBCourseMembership,
    DBDocumentSelection,
    DBKnowledgeDocument,
    DBLearningEvent,
    DBNote,
    DBProfileSnapshot,
    DBSourceDocument,
    DBSourceRef,
    DBStudentProfile,
    DBTaskEvent,
    DBUser,
    SessionLocal,
)
from app.main import app
from app.multimodal import RegionSelectionError, normalized_rect
from tests.api_test_helpers import auth_headers


FLAGSHIP_COURSE_ID = "course-machine-learning-foundations-v1"


def _flagship_source(client: TestClient, headers: dict[str, str]) -> dict:
    outline = client.get(f"/api/v1/courses/{FLAGSHIP_COURSE_ID}/outline", headers=headers)
    assert outline.status_code == 200, outline.text
    source_id = outline.json()[0]["source_document_id"]
    response = client.get(f"/api/knowledge/sources/{source_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _text_selection_payload(source: dict, key: str) -> dict:
    content = source["content"]
    start = int(source["source_ref_char_start"] or 0)
    end = int(source["source_ref_char_end"] or len(content))
    while start < end and content[start].isspace():
        start += 1
    char_end = min(end, start + 80)
    return {
        "source_document_id": source["source_document_id"],
        "document_version": source["processed_sha256"],
        "selection_type": "text",
        "source_ref_id": source["source_ref_id"],
        "section_id": source["source_chapter_id"],
        "char_start": start,
        "char_end": char_end,
        "quote": content[start:char_end],
        "idempotency_key": key,
    }


def _ensure_profile(username: str) -> None:
    with SessionLocal() as db:
        if db.get(DBStudentProfile, username) is None:
            db.add(DBStudentProfile(student_id=username))
            db.commit()


def _seed_personal_pdf(username: str) -> dict[str, str]:
    content = "卷积层通过局部感受野提取空间特征。"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    with SessionLocal() as db:
        user = db.query(DBUser).filter_by(username=username).one()
        if db.get(DBStudentProfile, username) is None:
            db.add(DBStudentProfile(student_id=username))
            db.flush()
        course = DBCourse(
            id=f"f7-t02-personal-{username}",
            version="1",
            title="个人扫描资料",
            visibility="private",
            status="draft",
            owner_public_id=user.public_id,
            manifest_version="personal-v1",
        )
        document = DBKnowledgeDocument(
            id=f"f7-t02-pdf-{username}",
            student_id=username,
            filename="cnn.pdf",
            file_type="pdf",
            title="卷积网络扫描讲义",
            content=content,
        )
        source = DBSourceDocument(
            id=f"f7-t02-source-{username}",
            course_id=course.id,
            legacy_document_id=document.id,
            title=document.title,
            filename=document.filename,
            file_format="pdf",
            content_hash=digest,
            source_sha256="a" * 64,
            processed_sha256=digest,
            source_path=f"data/uploads/{username}/{document.id}.pdf",
            uploader_public_id=user.public_id,
            parser_version="f7-t02-parser-v1",
            parser_metadata={
                "ocr": {
                    "status": "ready",
                    "pages": [{
                        "page_number": 1,
                        "width_px": 1000,
                        "height_px": 800,
                        "asset_name": "page-1-redacted.png",
                        "redacted_image_sha256": "b" * 64,
                        "regions": [{
                            "region_id": "region-cnn",
                            "bbox": {"x": 0.1, "y": 0.1, "width": 0.35, "height": 0.2},
                            "content": {"text": "卷积层通过局部感受野提取空间特征"},
                            "privacy": {"sensitive": False},
                        }],
                    }],
                }
            },
            processing_status="ready",
        )
        db.add_all([course, document, source])
        db.flush()
        chapter = DBChapter(
            id=f"f7-t02-chapter-{username}",
            course_id=course.id,
            source_document_id=source.id,
            stable_key="cnn-page-1",
            title="卷积层",
            position=1,
            char_start=0,
            char_end=len(content),
        )
        db.add(chapter)
        db.flush()
        ref = DBSourceRef(
            id=f"f7-t02-ref-{username}",
            source_document_id=source.id,
            chapter_id=chapter.id,
            parser_version=source.parser_version,
            page_number=1,
            char_start=0,
            char_end=len(content),
            location_kind="page",
            location_index=1,
            location_label="第 1 页",
            content_hash=digest,
            quote=content,
        )
        membership = DBCourseMembership(
            course_id=course.id,
            user_public_id=user.public_id,
            role="student",
            status="active",
        )
        db.add_all([ref, membership])
        db.commit()
        return {"source_id": source.id, "source_ref_id": ref.id, "chapter_id": chapter.id}


def test_normalized_rect_rejects_invalid_geometry() -> None:
    assert normalized_rect({"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}) == {
        "x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4,
    }
    for invalid in (
        {"x": -0.1, "y": 0.2, "width": 0.3, "height": 0.4},
        {"x": 0.9, "y": 0.2, "width": 0.3, "height": 0.4},
        {"x": 0.1, "y": 0.2, "width": 0.001, "height": 0.001},
        {"x": float("nan"), "y": 0.2, "width": 0.3, "height": 0.4},
    ):
        try:
            normalized_rect(invalid)
        except RegionSelectionError:
            pass
        else:
            raise AssertionError(f"invalid rect accepted: {invalid}")


def test_text_selection_position_answer_note_and_owner_isolation() -> None:
    username = "f7_t02_text_owner"
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        _ensure_profile(username)
        source = _flagship_source(client, headers)
        detail = client.get(
            f"/api/v1/document-reader/documents/{source['source_document_id']}",
            headers=headers,
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["document_version"] == source["processed_sha256"]
        assert detail.json()["content"]
        assert detail.json()["chapters"]
        assert detail.json()["source_refs"][0]["id"] == source["source_ref_id"]
        with SessionLocal() as db:
            user = db.query(DBUser).filter_by(username=username).one()
            events_before = db.query(DBLearningEvent).filter_by(owner_public_id=user.public_id).count()

        position = client.put(
            f"/api/v1/document-reader/positions/{source['source_document_id']}",
            headers=headers,
            json={
                "document_version": source["processed_sha256"],
                "section_id": source["source_chapter_id"],
                "char_offset": int(source["source_ref_char_start"] or 0),
                "scroll_ratio": 0.37,
                "zoom": 1.25,
            },
        )
        assert position.status_code == 200, position.text
        assert position.json()["scroll_ratio"] == 0.37

        created = client.post(
            "/api/v1/document-reader/selections",
            headers=headers,
            json=_text_selection_payload(source, "f7-t02-text-selection-0001"),
        )
        assert created.status_code == 201, created.text
        selection = created.json()
        assert selection["selection_type"] == "text"
        assert selection["source_ref_id"] == source["source_ref_id"]
        assert selection["quote"]

        replay = client.post(
            "/api/v1/document-reader/selections",
            headers=headers,
            json=_text_selection_payload(source, "f7-t02-text-selection-0001"),
        )
        assert replay.status_code == 201, replay.text
        assert replay.json()["created"] is False
        assert replay.json()["id"] == selection["id"]

        answer = client.post(
            f"/api/v1/document-reader/selections/{selection['id']}/ask",
            headers=headers,
            json={"question": "这段原文说明了什么？", "idempotency_key": "f7-t02-answer-0001"},
        )
        assert answer.status_code == 200, answer.text
        assert answer.json()["answer_status"] == "ready"
        assert answer.json()["answer_source_ref_id"] == source["source_ref_id"]
        answer_text = answer.json()["answer_text"]
        assert answer_text.strip()
        assert answer_text != selection["quote"]
        assert "当前选区直接给出的依据" not in answer_text

        note = client.post(
            f"/api/v1/document-reader/selections/{selection['id']}/notes",
            headers=headers,
            json={"content": "记录这一段教材定义。", "idempotency_key": "f7-t02-note-0001"},
        )
        assert note.status_code == 201, note.text
        with SessionLocal() as db:
            saved = db.get(DBNote, note.json()["note_id"])
            assert saved.source == "knowledge_selection"
            assert saved.source_metadata["selection_id"] == selection["id"]
            assert saved.source_metadata["source_ref_id"] == source["source_ref_id"]
            user = db.query(DBUser).filter_by(username=username).one()
            owner_events = db.query(DBLearningEvent).filter_by(owner_public_id=user.public_id)
            assert owner_events.count() == events_before + 1
            note_event = owner_events.filter_by(object_id=saved.id, action="created").one()
            assert note_event.event_type == "note.created"
            assert (note_event.mastery_eligible, note_event.completion_effect) == (False, "none")

        state = client.get(
            f"/api/v1/document-reader/state/{source['source_document_id']}",
            headers=headers,
        )
        assert state.status_code == 200
        assert state.json()["position"]["zoom"] == 1.25
        assert state.json()["selection"]["id"] == selection["id"]

        other_headers = auth_headers(client, "f7_t02_other_reader")
        forbidden = client.post(
            f"/api/v1/document-reader/selections/{selection['id']}/ask",
            headers=other_headers,
            json={"question": "越权读取", "idempotency_key": "f7-t02-answer-other"},
        )
        assert forbidden.status_code == 403


def test_image_selection_ocr_scaling_failure_retry_and_stale_version() -> None:
    username = "f7_t02_image_owner"
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        seeded = _seed_personal_pdf(username)
        payload = {
            "source_document_id": seeded["source_id"],
            "document_version": hashlib.sha256("卷积层通过局部感受野提取空间特征。".encode("utf-8")).hexdigest(),
            "selection_type": "image",
            "source_ref_id": seeded["source_ref_id"],
            "section_id": seeded["chapter_id"],
            "page_number": 1,
            "page_width": 1000,
            "page_height": 800,
            "normalized_rect": {"x": 0.12, "y": 0.12, "width": 0.3, "height": 0.16},
            "idempotency_key": "f7-t02-image-selection-0001",
        }
        created = client.post("/api/v1/document-reader/selections", headers=headers, json=payload)
        assert created.status_code == 201, created.text
        selection = created.json()
        assert selection["ocr_status"] == "ready"
        assert "局部感受野" in selection["ocr_text"]
        assert selection["normalized_rect"] == payload["normalized_rect"]
        assert selection["page_asset_url"].endswith(f"student_id={username}")
        detail = client.get(
            f"/api/v1/document-reader/documents/{seeded['source_id']}",
            headers=headers,
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["pages"] == [{
            "page_number": 1,
            "width": 1000,
            "height": 800,
            "asset_url": f"/api/knowledge/f7-t02-pdf-{username}/ocr/pages/1?student_id={username}",
        }]

        position = client.put(
            f"/api/v1/document-reader/positions/{seeded['source_id']}",
            headers=headers,
            json={
                "document_version": payload["document_version"],
                "page_number": 1,
                "section_id": seeded["chapter_id"],
                "scroll_ratio": 0.5,
                "zoom": 1.6,
            },
        )
        assert position.status_code == 200
        restored = client.get(f"/api/v1/document-reader/state/{seeded['source_id']}", headers=headers)
        assert restored.json()["position"]["zoom"] == 1.6
        assert restored.json()["selection"]["normalized_rect"] == payload["normalized_rect"]

        failed_payload = {
            **payload,
            "normalized_rect": {"x": 0.7, "y": 0.7, "width": 0.2, "height": 0.2},
            "idempotency_key": "f7-t02-image-selection-0002",
        }
        failed = client.post("/api/v1/document-reader/selections", headers=headers, json=failed_payload)
        assert failed.status_code == 201, failed.text
        assert failed.json()["ocr_status"] == "failed"
        retry = client.post(
            f"/api/v1/document-reader/selections/{failed.json()['id']}/ocr/retry",
            headers=headers,
        )
        assert retry.status_code == 200
        assert retry.json()["ocr_status"] == "failed"
        assert retry.json()["normalized_rect"] == failed_payload["normalized_rect"]
        answer = client.post(
            f"/api/v1/document-reader/selections/{failed.json()['id']}/ask",
            headers=headers,
            json={"question": "图里是什么？", "idempotency_key": "f7-t02-image-answer-0001"},
        )
        assert answer.status_code == 200
        assert answer.json()["answer_status"] == "failed"
        assert answer.json()["question_draft"] == "图里是什么？"

        with SessionLocal() as db:
            row = db.get(DBDocumentSelection, selection["id"])
            row.document_version = "0" * 64
            db.commit()
        stale = client.get(f"/api/v1/document-reader/state/{seeded['source_id']}", headers=headers)
        assert stale.status_code == 200
        # The most recently updated failed selection remains active; the changed row is rejected directly.
        rejected = client.post(
            f"/api/v1/document-reader/selections/{selection['id']}/ask",
            headers=headers,
            json={"question": "还能用吗？", "idempotency_key": "f7-t02-stale-answer"},
        )
        assert rejected.status_code == 409


def test_selection_generation_uses_existing_job_and_does_not_add_learning_evidence() -> None:
    username = "f7_t02_generation_owner"
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        source = _flagship_source(client, headers)
        created = client.post(
            "/api/v1/document-reader/selections",
            headers=headers,
            json=_text_selection_payload(source, "f7-t02-generation-selection"),
        )
        assert created.status_code == 201, created.text
        selection = created.json()
        with SessionLocal() as db:
            user = db.query(DBUser).filter_by(username=username).one()
            snapshot_body = {"goal": "理解教材原文", "preference": "图文"}
            db.add(DBProfileSnapshot(
                owner_public_id=user.public_id,
                legacy_student_id=username,
                profile_version="1",
                snapshot=snapshot_body,
                content_hash=hashlib.sha256(str(snapshot_body).encode()).hexdigest(),
                trace_id="f7-t02-generation-profile",
            ))
            events_before = db.query(DBLearningEvent).filter_by(owner_public_id=user.public_id).count()
            db.commit()

        generated = client.post(
            f"/api/v1/document-reader/selections/{selection['id']}/generation-jobs",
            headers=headers,
            json={"resource_type": "handout", "idempotency_key": "f7-t02-generation-job"},
        )
        assert generated.status_code == 201, generated.text
        job = generated.json()["job"]
        assert job["scope"] == "single"
        assert job["items"][0]["type"] == "handout"
        assert job["items"][0]["input"]["source_ref_ids"] == [source["source_ref_id"]]
        replay = client.post(
            f"/api/v1/document-reader/selections/{selection['id']}/generation-jobs",
            headers=headers,
            json={"resource_type": "handout", "idempotency_key": "f7-t02-generation-job"},
        )
        assert replay.status_code == 201, replay.text
        assert replay.json()["job"]["created"] is False
        assert replay.json()["job"]["job_id"] == job["job_id"]

        document_generated = client.post(
            f"/api/v1/document-reader/documents/{source['source_document_id']}/generation-jobs",
            headers=headers,
            json={"resource_type": "quiz", "idempotency_key": "f7-t02-document-generation-job"},
        )
        assert document_generated.status_code == 201, document_generated.text
        document_job = document_generated.json()["job"]
        assert document_job["scope"] == "single"
        assert document_job["items"][0]["type"] == "quiz"
        assert document_job["items"][0]["input"]["source_ref_ids"] == [source["source_ref_id"]]
        document_replay = client.post(
            f"/api/v1/document-reader/documents/{source['source_document_id']}/generation-jobs",
            headers=headers,
            json={"resource_type": "quiz", "idempotency_key": "f7-t02-document-generation-job"},
        )
        assert document_replay.status_code == 201, document_replay.text
        assert document_replay.json()["job"]["created"] is False
        assert document_replay.json()["job"]["job_id"] == document_job["job_id"]
        with SessionLocal() as db:
            binding = db.query(DBTaskEvent).filter_by(
                task_id=job["job_id"], event_type="document_selection.bound",
            ).one()
            assert binding.payload["selection_id"] == selection["id"]
            document_binding = db.query(DBTaskEvent).filter_by(
                task_id=document_job["job_id"], event_type="document_source.bound",
            ).one()
            assert document_binding.payload["source_document_id"] == source["source_document_id"]
            assert document_binding.payload["source_ref_id"] == source["source_ref_id"]
            user = db.query(DBUser).filter_by(username=username).one()
            assert db.query(DBLearningEvent).filter_by(owner_public_id=user.public_id).count() == events_before
