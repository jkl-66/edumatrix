from __future__ import annotations

from io import BytesIO
from fastapi import HTTPException
from fastapi.testclient import TestClient
from zipfile import ZipFile

import pytest

import document_parser
import knowledge_api
from app.database import DBWebSourceCandidate
from app.main import app
from app.source_admission import (
    _infer_format_details,
    _parsing_impact,
    _update_pipeline,
    serialize_candidate,
)
from tests.api_test_helpers import auth_headers


def _candidate(file_format: str = "html") -> DBWebSourceCandidate:
    return DBWebSourceCandidate(
        owner_public_id="b26-owner",
        title="FB-26 fixture",
        url="https://example.org/fixture",
        url_sha256="fixture-url-sha256",
        source_domain="example.org",
        file_format=file_format,
        license_status="open_permissive",
        usage_hint="isolated test use",
        parsing_impact=_parsing_impact(file_format),
    )


def test_format_detection_uses_content_type_or_signature_and_does_not_guess_unknown_url_as_html() -> None:
    assert _infer_format_details("https://example.org/course/no-extension")[0] == "unknown"
    assert _infer_format_details(
        "https://example.org/course/no-extension",
        content_type="application/pdf; charset=binary",
    ) == ("pdf", {"confidence": "declared", "method": "content_type"})
    assert _infer_format_details("https://example.org/download", raw=b"%PDF-1.7\n") == (
        "pdf",
        {"confidence": "signature", "method": "pdf_magic"},
    )
    package = BytesIO()
    with ZipFile(package, "w") as archive:
        archive.writestr("word/document.xml", "<w:document/>")
    assert _infer_format_details("https://example.org/download", raw=package.getvalue())[0] == "docx"


def test_html_images_are_preserved_as_assets_not_silently_dropped() -> None:
    raw = """
    <html><body><h1>公开课程</h1><p>正文内容</p>
    <figure><img src="/assets/diagram.png" alt="流程图"><figcaption>流程图说明</figcaption></figure>
    </body></html>
    """.encode("utf-8")
    parsed = document_parser.parse_document(raw, "lesson.html", base_url="https://example.org/course/page")

    assert parsed.file_format == "html"
    assert "正文内容" in parsed.text
    assert "网页图片 1" in parsed.text
    assert parsed.metadata["image_count"] == 1
    asset = parsed.metadata["image_assets"][0]
    assert asset["url"] == "https://example.org/assets/diagram.png"
    assert asset["alt"] == "流程图"
    assert asset["citation_ready"] is False
    assert asset["ocr_status"] == "pending_authorized_fetch"
    assert parsed.locations[0].kind == "html_image"
    assert "html_images_require_authorized_fetch_or_ocr" in parsed.warnings


def test_video_metadata_does_not_masquerade_as_transcript(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        document_parser,
        "_transcribe_video",
        lambda _raw, filename: f"[视频 {filename}] 已检测到音轨，本地语音转写未启用；仅元数据: 4.0s (640, 360)",
    )
    parsed = document_parser.parse_document(b"not-a-real-video-but-isolated-fixture", "lesson.mp4")

    assert parsed.metadata["media"]["metadata_status"] == "available"
    assert parsed.metadata["media"]["transcript_status"] == "unavailable"
    assert parsed.metadata["media"]["citation_ready"] is False
    assert "video_transcript_unavailable_metadata_only" in parsed.warnings
    assert "仅元数据" in parsed.text


def test_docx_and_pptx_structured_parsers_keep_text_and_image_capability() -> None:
    docx = pytest.importorskip("docx")
    doc = docx.Document()
    doc.add_paragraph("DOCX 正文 fixture")
    docx_bytes = BytesIO()
    doc.save(docx_bytes)
    parsed_docx = document_parser.parse_document(docx_bytes.getvalue(), "lesson.docx")
    assert "DOCX 正文 fixture" in parsed_docx.text
    assert parsed_docx.metadata["engine"] == "python-docx"

    pptx = pytest.importorskip("pptx")
    presentation = pptx.Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.title.text = "PPTX 正文 fixture"
    pptx_bytes = BytesIO()
    presentation.save(pptx_bytes)
    parsed_pptx = document_parser.parse_document(pptx_bytes.getvalue(), "lesson.pptx")
    assert "PPTX 正文 fixture" in parsed_pptx.text
    assert parsed_pptx.metadata["engine"] == "python-pptx"


def test_candidate_pipeline_separates_stages_and_retains_retryable_failure() -> None:
    candidate = _candidate("pdf")
    _update_pipeline(
        candidate,
        download={"status": "failed", "code": "download_timeout", "message": "原站下载超时"},
        parse={"status": "blocked", "code": "", "message": "等待下载重试"},
    )
    payload = serialize_candidate(candidate)
    assert payload["processingStatus"] == "failed"
    assert payload["processingPipeline"]["download"]["status"] == "failed"
    assert payload["processingPipeline"]["parse"]["status"] == "blocked"
    assert payload["citationStatus"] == "blocked"
    assert payload["retryable"] is True
    assert payload["failure"]["code"] == "download_timeout"

    _update_pipeline(
        candidate,
        download={"status": "completed", "code": "", "message": "下载完成"},
        parse={"status": "completed", "code": "", "message": "解析完成"},
        citation={"status": "ready", "code": "", "message": "可引用"},
        admission={"status": "admitted", "code": "", "message": "已准入"},
    )
    payload = serialize_candidate(candidate)
    assert payload["processingStatus"] == "admitted"
    assert payload["citationStatus"] == "ready"
    assert payload["failure"] is None


def test_canonical_admission_persists_download_failure_for_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(app) as client:
        headers = auth_headers(client, "b26-real-admission-failure")
        course = client.post(
            "/api/knowledge/courses",
            headers=headers,
            json={"title": "B26 失败投影课程", "subject": "联网资料"},
        )
        assert course.status_code == 201, course.text
        course_id = course.json()["course"]["id"]
        created = client.post(
            "/api/knowledge/discovery/candidates",
            headers=headers,
            json={
                "query": "多格式资料",
                "title": "B26 下载失败 fixture",
                "url": "https://open.example.org/course/lesson.pdf",
                "snippet": "下载失败阶段投影",
            },
        )
        assert created.status_code == 200, created.text
        candidate_id = created.json()["candidate"]["id"]

        async def fail_download(**_kwargs):
            raise HTTPException(status_code=504, detail="原站下载超时")

        monkeypatch.setattr(knowledge_api, "_download_remote_material", fail_download)
        failed = client.post(
            f"/api/knowledge/discovery/candidates/{candidate_id}/admit",
            headers=headers,
            json={
                "course_id": course_id,
                "author_or_organization": "开放课程组织",
                "license_status": "open_permissive",
                "license_text": "CC BY 4.0",
                "usage_hint": "允许个人学习引用并保留署名",
                "trust_level": "source_declared",
            },
        )
        assert failed.status_code == 504, failed.text

        listed = client.get("/api/knowledge/discovery/candidates", headers=headers)
        assert listed.status_code == 200, listed.text
        item = next(row for row in listed.json()["items"] if row["id"] == candidate_id)
        assert item["reviewStatus"] == "pending_review"
        assert item["processingPipeline"]["download"]["status"] == "failed"
        assert item["processingPipeline"]["download"]["code"] == "download_timeout"
        assert item["processingStatus"] == "failed"
        assert item["retryable"] is True
        assert item["failure"]["code"] == "download_timeout"
