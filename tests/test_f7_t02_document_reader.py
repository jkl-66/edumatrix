from __future__ import annotations

import hashlib
import pytest
from fastapi import HTTPException

from fastapi.testclient import TestClient

from app.database import (
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
    DBCourseDocument,
    DBCourseMembership,
    DBDocumentSelection,
    DBKnowledgeDocument,
    DBKnowledgePoint,
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


def test_bundled_original_links_use_recorded_files_and_exact_unicode_ranges():
    from app.source_refs import document_original_location
    revision = "a" * 40
    paths = "first.md;课件/末章.md"
    source_path = f"course@{revision}:{paths}"
    prefix = f"https://github.com/example/course/blob/{revision}/"
    content = "𝒘引言\n\n<!-- 上游文件: first.md -->\n\n# 起步\n第一章\n\n<!-- 上游文件: 课件/末章.md -->\n\n# 收敛\n末章正文"
    links = document_original_location(prefix + paths, source_path, content)
    assert links["url"] == f"https://github.com/example/course/tree/{revision}"
    assert len(links["parts"]) == 2
    first, last = links["parts"]
    assert first["title"] == "起步" and last["title"] == "收敛"
    assert first["char_end"] == last["char_start"] == content.index('<!-- 上游文件: 课件')
    assert last["url"].endswith('/%E8%AF%BE%E4%BB%B6/%E6%9C%AB%E7%AB%A0.md')
    assert content[last["char_start"]:last["char_end"]].endswith('末章正文')
    assert document_original_location(links["url"], source_path, content) == links
    assert document_original_location(prefix+'first.md', f'course@{revision}:first.md', '# 起步')["url"] == prefix+'first.md'


def test_original_links_do_not_guess_unmapped_positions_or_rewrite_ordinary_web_urls():
    from app.source_refs import document_original_location
    revision = "b" * 40
    url = f"https://github.com/example/course/blob/{revision}/first.md;last.md"
    source = f'course@{revision}:first.md;last.md'
    result = document_original_location(url, source, 'No recorded file boundaries')
    assert all(part['char_start'] is None and part['char_end'] is None for part in result['parts'])
    ordinary = 'https://example.org/a;b?chapter=2'
    assert document_original_location(ordinary, 'uploads/source.html', '正文') == {'url':ordinary,'parts':[]}
    assert document_original_location(url, f'course@{"c" * 40}:first.md;last.md')["url"] == url


def test_reader_generation_covers_its_document_without_narrowing_to_first_topic():
    from tests.test_f2_resource_generation_protocol import _seed

    username = "reader_generation_source_scope"
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        seed = _seed(username, "reader-source-scope")
        with SessionLocal() as db:
            ref = db.get(DBSourceRef, seed["source_ref_id"])
            selected_source = db.get(DBSourceDocument, seed["source_document_id"])
            full_text = "# 梯度下降\n沿负梯度方向更新参数。\n\n# 末章收敛\n步长过大可能导致发散，不能只检查第一章。"
            digest = hashlib.sha256(full_text.encode()).hexdigest()
            document = DBCourseDocument(id="reader-whole-document", course_id=seed["course_id"], chapter_order=1, filename="gradient-descent.md", content=full_text, content_hash=digest)
            db.add(document); db.flush()
            selected_source.legacy_document_id = document.id
            selected_source.content_hash = selected_source.processed_sha256 = digest
            selected_source.parser_version = ref.parser_version
            ref.content_hash = digest
            chapter = db.get(DBChapter, ref.chapter_id)
            chapter.position = 2
            ref.chapter_id = None  # Whole-document references need not name a chapter.
            unrelated = DBKnowledgePoint(domain_pack="ml", code="reader-other-topic", version="1", title="分类评估")
            source = DBSourceDocument(course_id=seed["course_id"], title="另一份教材", filename="other.md", file_format="markdown", content_hash="a" * 64)
            db.add_all([unrelated, source])
            db.flush()
            earlier = DBChapter(course_id=seed["course_id"], source_document_id=source.id, stable_key="reader-earlier", title="分类评估", position=1)
            db.add(earlier)
            db.flush()
            tail_point = DBKnowledgePoint(domain_pack="ml", code="reader-tail-topic", version="1", title="末章收敛")
            tail_chapter = DBChapter(course_id=seed["course_id"], source_document_id=selected_source.id, stable_key="reader-tail", title="末章收敛", position=3, char_start=full_text.index("# 末章"),char_end=len(full_text))
            db.add_all([tail_point,tail_chapter]);db.flush()
            db.add(DBChapterKnowledgePoint(chapter_id=tail_chapter.id,knowledge_point_id=tail_point.id))
            tail_point_id=tail_point.id
            db.add_all([
                DBChapterKnowledgePoint(chapter_id=earlier.id, knowledge_point_id=unrelated.id),
                DBChapterKnowledgePoint(id="aaa-reader-secondary", chapter_id=chapter.id, knowledge_point_id=unrelated.id),
            ])
            db.commit()
        result = client.post(
            f"/api/v1/document-reader/documents/{seed['source_document_id']}/generation-jobs",
            headers=headers,
            json={"resource_type": "quiz", "idempotency_key": "reader-document-scope-job"},
        )
        assert result.status_code == 201, result.text
        job = result.json()["job"]
        assert job["knowledge_point_id"] is None
        generated_ref_id=job["items"][0]["input"]["source_ref_ids"][0]
        with SessionLocal() as db:
            from app.resource_bundles import _generation_manifest, _resource_prompt_sources
            manifest=_generation_manifest(db,job["job_id"])
            frozen=manifest["input_snapshot"]["source_snapshots"]["quiz"]
            assert len(frozen)==1 and frozen[0]["quote"]==full_text
            assert frozen[0]["location_kind"]=="reader_document"
            assert _resource_prompt_sources(manifest,frozen,"quiz")[0]["quote"]==full_text
            assert db.get(DBSourceRef,generated_ref_id).char_end==len(full_text)
        assert tail_point_id in {point["id"] for point in job["context"]["teaching_scope"]["knowledge_points"]}
        assert seed["source_document_id"] not in job["context"]["learning_goal"]


def test_reader_accepts_configured_upload_root_and_rejects_sibling_paths(monkeypatch, tmp_path):
    from app.document_selection import _source_file_path
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    allowed = upload_root / "lesson.md"
    allowed.write_text("# Lesson", encoding="utf-8")
    outside = tmp_path / "private.md"
    outside.write_text("not a course asset", encoding="utf-8")
    monkeypatch.setenv("EDUMATRIX_UPLOAD_DIR", str(upload_root))
    source = DBSourceDocument(source_path=str(allowed))
    assert _source_file_path(source) == allowed.resolve()
    source.source_path = str(upload_root / ".." / "private.md")
    with pytest.raises(HTTPException) as exc:
        _source_file_path(source)
    assert exc.value.status_code == 409


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


def _seed_personal_pdf(username: str, content: str = "卷积层通过局部感受野提取空间特征。") -> dict[str, str]:
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


def test_long_selection_preserves_exact_range_answer_evidence_and_source_note(monkeypatch) -> None:
    from app import document_selection
    quote = "  完整选区开始。\n" + "材料中的比较必须保持评价条件一致。\n" * 800 + "末段关键条件：只有同一评价集与同一指标才可直接比较。\n"
    assert len(quote) > 12_000
    observed = []
    async def answer(*args, **kwargs):
        observed.append(kwargs["user_prompt"])
        return "末段规定：必须使用同一评价集与同一指标。"
    monkeypatch.setattr(document_selection, "audited_legacy_text_call", answer)
    with TestClient(app) as client:
        username = "f7_t02_long_selection"
        headers = auth_headers(client, username)
        seeded = _seed_personal_pdf(username, quote)
        payload = {"source_document_id":seeded["source_id"], "document_version":hashlib.sha256(quote.encode()).hexdigest(),
            "selection_type":"text", "source_ref_id":seeded["source_ref_id"], "section_id":seeded["chapter_id"],
            "char_start":0, "char_end":len(quote), "quote":quote, "idempotency_key":"long-source-selection"}
        selected = client.post("/api/v1/document-reader/selections", headers=headers, json=payload)
        assert selected.status_code == 201
        assert selected.json()["quote"] == quote
        sid = selected.json()["id"]
        response = client.post(f"/api/v1/document-reader/selections/{sid}/ask", headers=headers,
            json={"question":"只说明最后一段限定的条件", "idempotency_key":"long-source-answer"})
        assert response.status_code == 200 and response.json()["answer_status"] == "ready"
        assert len(observed) == 1 and quote in observed[0]
        note = client.post(f"/api/v1/document-reader/selections/{sid}/notes", headers=headers,
            json={"content":quote, "idempotency_key":"long-source-note"})
        assert note.status_code == 201
        restored = client.get(f"/api/v1/document-reader/state/{seeded['source_id']}", headers=headers).json()["selection"]
        assert restored["quote"] == quote and restored["char_end"] == len(quote)
        with SessionLocal() as db:
            saved_note = db.get(DBNote, note.json()["note_id"])
            assert saved_note.content == quote.strip()
            assert saved_note.source_metadata["quote"] == quote
            owner = db.query(DBUser).filter_by(username=username).one().public_id
            assert db.query(DBLearningEvent).filter_by(owner_public_id=owner, mastery_eligible=True).count() == 0


def test_long_selection_answer_restores_full_provider_output(monkeypatch) -> None:
    from app import document_selection
    content = "完整教学说明。\n" * 26000 + "末尾结论：条件必须保持一致。"
    assert len(content) > 200_000
    async def answer(*args, **kwargs):
        return content
    monkeypatch.setattr(document_selection, "audited_legacy_text_call", answer)
    with TestClient(app) as client:
        username = "f7_t02_long_answer"
        headers = auth_headers(client, username)
        _ensure_profile(username)
        source = _flagship_source(client, headers)
        selected = client.post("/api/v1/document-reader/selections", headers=headers,
            json=_text_selection_payload(source, "long-selection-tail"))
        assert selected.status_code == 201
        response = client.post(f"/api/v1/document-reader/selections/{selected.json()['id']}/ask", headers=headers,
            json={"question": "完整说明适用条件", "idempotency_key": "long-answer-tail"})
        assert response.status_code == 200
        assert response.json()["answer_text"] == content
        restored = client.get(f"/api/v1/document-reader/state/{source['source_document_id']}", headers=headers)
        assert restored.json()["selection"]["answer_text"] == content


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
            assert saved.tags == ["原文摘录"]
            assert saved.source_metadata["selection_id"] == selection["id"]
            assert saved.source_metadata["source_ref_id"] == source["source_ref_id"]
            user = db.query(DBUser).filter_by(username=username).one()
            owner_events = db.query(DBLearningEvent).filter_by(owner_public_id=user.public_id)
            assert owner_events.count() == events_before + 1
            note_event = owner_events.filter_by(object_id=saved.id, action="created").one()
            assert note_event.event_type == "note.created"
            assert note_event.course_id == source["course_id"]
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
            "image_selection": True,
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


@pytest.mark.parametrize("legacy_ref_missing", [False, True])
def test_selection_generation_uses_existing_job_and_does_not_add_learning_evidence(legacy_ref_missing) -> None:
    username = f"f7_t02_generation_owner_{int(legacy_ref_missing)}"
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
            if legacy_ref_missing:
                # An exact saved range does not require a separately indexed
                # chapter citation; generation creates its own range binding.
                db.get(DBDocumentSelection, selection["id"]).source_ref_id = None
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
        assert job["knowledge_point_id"] is None
        assert job["context"]["knowledge_point_title"] == "当前教材选区"
        selected_ref_id = job["items"][0]["input"]["source_ref_ids"][0]
        assert selected_ref_id != source["source_ref_id"]
        with SessionLocal() as db:
            from app.source_refs import source_ref_teaching_text
            from app.canonical_retrieval import list_canonical_source_refs
            from app.resource_bundles import _generation_manifest, _resource_prompt_sources
            ref = db.get(DBSourceRef, selected_ref_id)
            assert ref.location_kind == "selection"
            from app.source_refs import project_source_ref
            projected=project_source_ref(db, selected_ref_id)
            assert projected["chapter_id"] is None and "chapter_id=None" not in projected["route"]
            assert (ref.char_start, ref.char_end) == (selection["char_start"], selection["char_end"])
            assert source_ref_teaching_text(db, ref, max_chars=None) == selection["quote"]
            manifest = _generation_manifest(db, job["job_id"])
            frozen = manifest["input_snapshot"]["source_snapshots"]["handout"]
            assert len(frozen) == 1 and frozen[0]["quote"] == selection["quote"]
            assert _resource_prompt_sources(manifest, frozen, "handout")[0]["quote"] == selection["quote"]
            assert selected_ref_id not in {r["source_ref_id"] for r in list_canonical_source_refs(db,course_id=job["course_id"])}
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
        document_ref_id = document_job["items"][0]["input"]["source_ref_ids"][0]
        with SessionLocal() as db:
            document_ref = db.get(DBSourceRef, document_ref_id)
            assert document_ref.location_kind == "reader_document"
            assert document_ref.quote == source["content"]
            assert document_ref.char_start == 0 and document_ref.char_end == len(source["content"])
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
            assert document_binding.payload["source_ref_id"] == document_ref_id
            user = db.query(DBUser).filter_by(username=username).one()
            assert db.query(DBLearningEvent).filter_by(owner_public_id=user.public_id).count() == events_before


def test_text_pdf_pages_render_without_ocr_and_preserve_source_and_learning_records(monkeypatch, tmp_path):
    import fitz

    monkeypatch.setenv("EDUMATRIX_UPLOAD_DIR", str(tmp_path))
    username = "reader_native_pdf"
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        seed = _seed_personal_pdf(username)
        path = tmp_path / "lesson.pdf"
        with fitz.open() as document:
            for text in ("Training and validation", "Accuracy is 80 percent", "Prevent data leakage"):
                page = document.new_page()
                page.insert_text((60, 80), text)
            document.save(path)
        with SessionLocal() as db:
            source = db.get(DBSourceDocument, seed["source_id"])
            source.source_path = str(path)
            source.source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            source.parser_metadata = {}
            actor = db.query(DBUser).filter_by(username=username).one()
            actor_id = actor.public_id
            before = db.query(DBLearningEvent).filter_by(owner_public_id=actor_id).count()
            db.commit()
        base = f"/api/v1/document-reader/documents/{seed['source_id']}"
        payload = client.get(base, headers=headers).json()
        assert payload["reader_mode"] == "native_pages"
        assert [page["page_number"] for page in payload["pages"]] == [1, 2, 3]
        assert not payload["pages"][0]["image_selection"]
        images = []
        for page in payload["pages"]:
            response = client.get(page["asset_url"], headers=headers)
            assert response.status_code == 200, response.text
            assert response.content.startswith(b"\x89PNG")
            image = fitz.Pixmap(response.content)
            assert abs(image.width - page["width"]) <= 1
            assert abs(image.height - page["height"]) <= 1
            images.append(response.content)
        assert len(set(images)) == 3
        assert client.get(base + "/pages/4", headers=headers).status_code == 404
        stranger = auth_headers(client, "reader_native_pdf_stranger")
        assert client.get(base + "/pages/1", headers=stranger).status_code == 403
        with SessionLocal() as db:
            assert db.query(DBLearningEvent).filter_by(owner_public_id=actor_id).count() == before
        path.write_bytes(b"changed original")
        changed = client.get(base + "/pages/1", headers=headers)
        assert changed.status_code == 409
        readable = client.get(base, headers=headers)
        assert readable.status_code == 200
        assert readable.json()["content"] == payload["content"]
        assert readable.json()["pdf_preview_message"]
