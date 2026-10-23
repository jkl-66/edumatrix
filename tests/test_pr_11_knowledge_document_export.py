from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import DBKnowledgeDocument, DBLearningEvent, DBSourceDocument, DBUser, SessionLocal
from app.main import app
from tests.api_test_helpers import auth_headers
from tests.test_f7_t02_document_reader import _flagship_source, _seed_personal_pdf


def test_authorized_reader_export_returns_revision_hash_and_does_not_write_learning_events() -> None:
    username = "pr11_export_owner"
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        source = _flagship_source(client, headers)
        with SessionLocal() as db:
            user = db.query(DBUser).filter_by(username=username).one()
            before = db.query(DBLearningEvent).filter_by(owner_public_id=user.public_id).count()

        response = client.get(
            f"/api/v1/document-reader/documents/{source['source_document_id']}/export",
            headers=headers,
        )

        assert response.status_code == 200, response.text
        assert response.headers["x-document-revision"] == source["processed_sha256"]
        assert response.headers["x-source-sha256"]
        assert response.headers["x-knowledge-export-mode"] in {"original-file", "parsed-text"}
        assert response.content
        with SessionLocal() as db:
            user = db.query(DBUser).filter_by(username=username).one()
            assert db.query(DBLearningEvent).filter_by(owner_public_id=user.public_id).count() == before

        personal = _seed_personal_pdf(username)
        other_headers = auth_headers(client, "pr11_export_other")
        forbidden = client.get(
            f"/api/v1/document-reader/documents/{personal['source_id']}/export",
            headers=other_headers,
        )
        assert forbidden.status_code == 403


def test_personal_pdf_export_prefers_verified_original_file() -> None:
    username = "pr11_original_owner"
    with TestClient(app) as client:
        auth_headers(client, username)
    seeded = _seed_personal_pdf(username)
    raw = b"%PDF-1.4\nPR-11 original source\n"
    path = Path("data") / "uploads" / username / f"f7-t02-pdf-{username}.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    with SessionLocal() as db:
        source = db.get(DBSourceDocument, seeded["source_id"])
        assert source is not None
        source.source_sha256 = digest
        db.commit()

    try:
        with TestClient(app) as client:
            headers = auth_headers(client, username)
            response = client.get(
                f"/api/v1/document-reader/documents/{seeded['source_id']}/export",
                headers=headers,
            )
            assert response.status_code == 200, response.text
            assert response.content == raw
            assert response.headers["x-knowledge-export-mode"] == "original-file"
            assert response.headers["x-source-sha256"] == digest
            assert "cnn.pdf" in response.headers["content-disposition"]
    finally:
        path.unlink(missing_ok=True)


def test_original_export_preserves_pdf_docx_pptx_and_image_source_bytes() -> None:
    username = "pr11_format_owner"
    with TestClient(app) as client:
        auth_headers(client, username)
    seeded = _seed_personal_pdf(username)
    samples = {
        "pdf": b"%PDF-1.4\nformat sample\n",
        "docx": b"PK\x03\x04docx-format-sample",
        "pptx": b"PK\x03\x04pptx-format-sample",
        "png": b"\x89PNG\r\n\x1a\nimage-format-sample",
    }
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        for extension, raw in samples.items():
            path = Path("data") / "uploads" / username / f"pr11-format-{extension}.{extension}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            try:
                with SessionLocal() as db:
                    source = db.get(DBSourceDocument, seeded["source_id"])
                    assert source is not None
                    source.filename = f"knowledge.{extension}"
                    source.file_format = extension
                    source.source_path = str(path)
                    source.source_sha256 = digest
                    db.commit()
                response = client.get(
                    f"/api/v1/document-reader/documents/{seeded['source_id']}/export",
                    headers=headers,
                )
                assert response.status_code == 200, response.text
                assert response.content == raw
                assert response.headers["x-knowledge-export-mode"] == "original-file"
                assert response.headers["x-source-sha256"] == digest
            finally:
                path.unlink(missing_ok=True)


def test_export_failure_is_explicit_and_reader_content_remains_recoverable() -> None:
    username = "pr11_export_failure"
    with TestClient(app) as client:
        auth_headers(client, username)
    seeded = _seed_personal_pdf(username)
    with SessionLocal() as db:
        document = db.get(DBKnowledgeDocument, f"f7-t02-pdf-{username}")
        source = db.get(DBSourceDocument, seeded["source_id"])
        assert document is not None and source is not None
        document.content = ""
        source.processed_sha256 = "f" * 64
        source.content_hash = "f" * 64
        db.commit()

    with TestClient(app) as client:
        headers = auth_headers(client, username)
        response = client.get(
            f"/api/v1/document-reader/documents/{seeded['source_id']}/export",
            headers=headers,
        )
        assert response.status_code == 409
        assert "导出" in response.json()["detail"] or "版本" in response.json()["detail"]
        detail = client.get(
            f"/api/v1/document-reader/documents/{seeded['source_id']}",
            headers=headers,
        )
        assert detail.status_code == 409
