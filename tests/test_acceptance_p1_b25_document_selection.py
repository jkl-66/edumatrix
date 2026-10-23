from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from tests.api_test_helpers import auth_headers
from tests.test_f7_t02_document_reader import _seed_personal_pdf


ROOT = Path(__file__).resolve().parents[1]
READER = ROOT / "frontend/src/views/KnowledgeDocumentReader.vue"
TOOLBAR = ROOT / "frontend/src/components/SelectionToolbar.vue"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_reader_selection_serialization_exposes_text_layer_and_retry_contract() -> None:
    reader = _source(READER)
    toolbar = _source(TOOLBAR)

    for marker in (
        "selection_text_regions",
        "activePageTextRegions",
        "page-text-layer",
        "data-selection-region",
        "textSelectionBounds",
        "pageSelectionBounds",
        "trimSourceSelection",
        "@mouseup=\"handleTextSelection\"",
        "error-message",
        "@retry=\"retryTextSelection\"",
    ):
        assert marker in reader
    for marker in ("errorMessage", "selection-toolbar__retry", "重新选择", "emit('retry')"):
        assert marker in toolbar
    assert "if (hasPages.value) return" not in reader[reader.index("async function handleTextSelection") : reader.index("function normalizedPointer")]


def test_paginated_text_selection_uses_exact_source_quote_and_rejects_empty_selection() -> None:
    username = "p1_b25_text_layer"
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        seeded = _seed_personal_pdf(username)
        detail = client.get(
            f"/api/v1/document-reader/documents/{seeded['source_id']}",
            headers=headers,
        )
        assert detail.status_code == 200, detail.text
        document = detail.json()
        regions = document["selection_text_regions"]
        assert regions
        region = regions[0]
        assert region["source_ref_id"] == seeded["source_ref_id"]
        assert region["char_start"] == 0
        assert document["content"][region["char_start"] : region["char_end"]] == region["text"]

        created = client.post(
            "/api/v1/document-reader/selections",
            headers=headers,
            json={
                "source_document_id": seeded["source_id"],
                "document_version": document["document_version"],
                "selection_type": "text",
                "source_ref_id": region["source_ref_id"],
                "section_id": seeded["chapter_id"],
                "page_number": region["page_number"],
                "char_start": region["char_start"],
                "char_end": region["char_end"],
                "quote": region["text"],
                "idempotency_key": "p1-b25-text-layer-0001",
            },
        )
        assert created.status_code == 201, created.text
        selection = created.json()
        assert selection["selection_type"] == "text"
        assert selection["page_number"] == 1
        assert selection["quote"] == region["text"]
        assert selection["source_ref_id"] == seeded["source_ref_id"]

        empty = client.post(
            "/api/v1/document-reader/selections",
            headers=headers,
            json={
                "source_document_id": seeded["source_id"],
                "document_version": document["document_version"],
                "selection_type": "text",
                "source_ref_id": seeded["source_ref_id"],
                "section_id": seeded["chapter_id"],
                "page_number": 1,
                "char_start": 0,
                "char_end": 1,
                "quote": " ",
                "idempotency_key": "p1-b25-empty-selection",
            },
        )
        assert empty.status_code in {409, 422}

