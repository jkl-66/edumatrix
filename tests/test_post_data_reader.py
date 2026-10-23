from __future__ import annotations

from fastapi.testclient import TestClient

from app.database import (
    DBChapter,
    DBCourse,
    DBLearningEvent,
    DBSourceDocument,
    DBSourceRef,
    SessionLocal,
)
from app.main import app
from tests.api_test_helpers import auth_headers


COURSE_ID = "course-embedded-machine-learning-engineering-v2"


def _source(file_format: str) -> tuple[DBSourceDocument, DBChapter, DBSourceRef]:
    with SessionLocal() as db:
        source = db.query(DBSourceDocument).filter_by(course_id=COURSE_ID, file_format=file_format).one()
        chapter = db.query(DBChapter).filter_by(source_document_id=source.id).one()
        ref = db.query(DBSourceRef).filter_by(source_document_id=source.id).one()
        db.expunge(source)
        db.expunge(chapter)
        db.expunge(ref)
        return source, chapter, ref


def test_curated_course_outline_reader_pdf_selection_and_video_are_real() -> None:
    with TestClient(app) as client:
        headers = auth_headers(client, "post_data_reader")
        with SessionLocal() as db:
            course = db.get(DBCourse, COURSE_ID)
            assert course is not None
            events_before = db.query(DBLearningEvent).count()

        outline_response = client.get(f"/api/v1/courses/{COURSE_ID}/outline", headers=headers)
        assert outline_response.status_code == 200, outline_response.text
        outline = outline_response.json()
        assert len(outline) == 26
        assert sum(item["parent_id"] is None for item in outline) == 9
        assert sum(item["parent_id"] is not None for item in outline) == 17

        pdf_source, pdf_chapter, pdf_ref = _source("pdf")
        detail = client.get(f"/api/v1/document-reader/documents/{pdf_source.id}", headers=headers)
        assert detail.status_code == 200, detail.text
        payload = detail.json()
        assert payload["file_type"] == "pdf"
        assert len(payload["pages"]) == 28
        assert payload["pages"][0]["asset_url"].endswith(f"/{pdf_source.id}/pages/1")

        page = client.get(f"/api/v1/document-reader/documents/{pdf_source.id}/pages/1", headers=headers)
        assert page.status_code == 200, page.text
        assert page.headers["content-type"].startswith("image/png")
        assert len(page.content) > 10_000

        first_page = pdf_source.parser_metadata["ocr"]["pages"][0]
        first_region = first_page["regions"][0]
        selection = client.post(
            "/api/v1/document-reader/selections",
            headers=headers,
            json={
                "source_document_id": pdf_source.id,
                "document_version": pdf_source.processed_sha256,
                "selection_type": "image",
                "source_ref_id": pdf_ref.id,
                "section_id": pdf_chapter.id,
                "page_number": 1,
                "page_width": first_page["width_px"],
                "page_height": first_page["height_px"],
                "normalized_rect": first_region["bbox"],
                "idempotency_key": "post-data-pdf-region-0001",
            },
        )
        assert selection.status_code == 201, selection.text
        selected = selection.json()
        assert selected["ocr_status"] == "ready"
        assert "课程目标" in selected["ocr_text"]
        assert selected["page_asset_url"].endswith(f"/{pdf_source.id}/pages/1")

        answer = client.post(
            f"/api/v1/document-reader/selections/{selected['id']}/ask",
            headers=headers,
            json={"question": "这一区域要求我掌握什么？", "idempotency_key": "post-data-pdf-answer-0001"},
        )
        assert answer.status_code == 200, answer.text
        assert answer.json()["answer_status"] == "ready"
        assert "课程目标" in answer.json()["answer_text"]

        video_source, _video_chapter, _video_ref = _source("mp4")
        video_detail = client.get(f"/api/v1/document-reader/documents/{video_source.id}", headers=headers)
        assert video_detail.status_code == 200, video_detail.text
        assert video_detail.json()["media"]["kind"] == "video"
        assert "本地视频为 EduMatrix 团队制作" in video_detail.json()["content"]
        media = client.get(f"/api/v1/document-reader/documents/{video_source.id}/media", headers=headers)
        assert media.status_code == 200, media.text
        assert media.headers["content-type"].startswith("video/mp4")
        assert len(media.content) > 50_000

        assert client.get(f"/api/v1/document-reader/documents/{pdf_source.id}/pages/1").status_code == 401
        assert client.get(f"/api/v1/document-reader/documents/{video_source.id}/media").status_code == 401
        with SessionLocal() as db:
            assert db.query(DBLearningEvent).count() == events_before


def test_reader_frontend_exposes_grouped_materials_pdf_pages_and_video_player() -> None:
    api_source = open("frontend/src/api/knowledge.js", encoding="utf-8").read()
    reader_source = open("frontend/src/views/KnowledgeDocumentReader.vue", encoding="utf-8").read()
    shelf_source = open("frontend/src/components/KnowledgeCourseShelf.vue", encoding="utf-8").read()

    assert "function getDocumentReaderPage" in api_source
    assert "function getDocumentReaderMedia" in api_source
    assert "v-else-if=\"isVideo\"" in reader_source
    assert "<video v-else" in reader_source
    assert "视频说明与可检索文字" in reader_source
    assert "const rootChapters" in shelf_source
    assert "const selectedMaterials" in shelf_source
    assert "本章资料" in shelf_source
