from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

import knowledge_api
from app.database import DBSourceDocument, DBSourceRef, SessionLocal
from app.main import app
from app.media_ocr import RapidOCROfflineAdapter, run_pdf_ocr
from tests.api_test_helpers import auth_headers


def _font(size: int = 48):
    path = Path(r"C:\Windows\Fonts\arial.ttf")
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default()


def _scanned_pdf_bytes() -> bytes:
    image = Image.new("RGB", (1400, 620), "white")
    draw = ImageDraw.Draw(image)
    font = _font()
    draw.text((70, 70), "EduMatrix Offline OCR", font=font, fill="black")
    draw.text((70, 180), "score = 95 + 3", font=font, fill="black")
    draw.text((70, 290), "student@example.com", font=font, fill="black")
    buffer = BytesIO()
    output = canvas.Canvas(buffer, pagesize=(700, 310))
    output.drawImage(ImageReader(image), 0, 0, width=700, height=310)
    output.save()
    return buffer.getvalue()


class _SyntheticEngine:
    def __call__(self, _image):
        return (
            [
                [[[20, 20], [220, 20], [220, 60], [20, 60]], "score = 7 + 2", 0.98],
                [[[20, 100], [180, 100], [180, 140], [20, 140]], "metric", 0.97],
                [[[300, 100], [430, 100], [430, 140], [300, 140]], "value", 0.96],
                [[[20, 180], [180, 180], [180, 220], [20, 220]], "accuracy", 0.95],
                [[[300, 180], [430, 180], [430, 220], [300, 220]], "0.95", 0.94],
            ],
            [0.01, 0.01, 0.01],
        )


def test_region_contract_normalizes_formula_and_spatial_table():
    image = Image.new("RGB", (500, 300), "white")
    adapter = RapidOCROfflineAdapter(engine_factory=lambda: _SyntheticEngine())
    regions = adapter.recognize(
        image,
        page_number=1,
        source_sha256="a" * 64,
        page_image_sha256="b" * 64,
    )
    formula = next(region for region in regions if region.region_type == "formula")
    table = next(region for region in regions if region.region_type == "table")
    payload = formula.to_dict()
    assert payload["schema_version"] == "edumatrix.ocr-region.v1"
    assert payload["coordinate_space"] == "normalized_top_left"
    assert all(0 <= value <= 1 for point in payload["polygon"] for value in point)
    assert payload["content"]["recognition_status"] == "formula_candidate"
    assert payload["content"]["latex"] == ""
    assert table.table["row_count"] == 2
    assert table.table["column_count"] == 2
    assert table.table["rows"] == [["metric", "value"], ["accuracy", "0.95"]]


def test_missing_runtime_is_explicitly_unavailable(monkeypatch):
    adapter = RapidOCROfflineAdapter()
    monkeypatch.setattr(adapter, "runtime", lambda: (False, ""))
    result = run_pdf_ocr(
        _scanned_pdf_bytes(),
        source_sha256="c" * 64,
        page_numbers=[1],
        adapter=adapter,
    )
    assert result.status == "unavailable"
    assert result.failure_code == "offline_ocr_runtime_unavailable"
    assert result.pages == ()


def test_scanned_pdf_ocr_persists_redacted_owner_scoped_regions(tmp_path, monkeypatch):
    upload_root = tmp_path / "uploads"
    monkeypatch.setattr(knowledge_api, "UPLOAD_DIR", upload_root)
    monkeypatch.setattr(knowledge_api, "build_graph_after_upload", lambda *args, **kwargs: None)
    monkeypatch.setattr(knowledge_api.hybrid_rag, "ingest_user_documents", lambda *args, **kwargs: None)
    monkeypatch.setattr(knowledge_api.hybrid_rag, "remove_user_documents", lambda *args, **kwargs: None)

    async def no_guide(**kwargs):
        return None

    monkeypatch.setattr(knowledge_api, "_generate_doc_guide_for_document", no_guide)

    def raw_visual_must_not_run(*args, **kwargs):
        raise AssertionError("sensitive scanned page reached unredacted visual pipeline")

    monkeypatch.setattr(knowledge_api, "parse_pdf_visually", raw_visual_must_not_run)

    with TestClient(app) as client:
        owner = "nc_media_01_owner"
        other = "nc_media_01_other"
        owner_headers = auth_headers(client, owner)
        other_headers = auth_headers(client, other)
        upload = client.post(
            f"/api/knowledge/upload?student_id={owner}",
            headers=owner_headers,
            files={"file": ("scan.pdf", _scanned_pdf_bytes(), "application/pdf")},
        )
        assert upload.status_code == 200, upload.text
        payload = upload.json()
        assert payload["ocr"]["status"] == "ready"
        assert payload["ocr"]["page_count"] == 1
        assert payload["ocr"]["region_count"] >= 3
        assert payload["ocr"]["sensitive_region_count"] >= 1
        document_id = payload["id"]
        source_document_id = payload["source_document_id"]

        detail = client.get(
            f"/api/knowledge/{document_id}?student_id={owner}", headers=owner_headers
        )
        assert detail.status_code == 200
        body = detail.json()
        assert "student@example.com" not in body["content"]
        region_locations = [
            item for item in body["source_locations"] if item["kind"] == "ocr_region"
        ]
        assert region_locations
        assert all(item["image_region"]["schema_version"] == "edumatrix.ocr-region.v1" for item in region_locations)

        report = client.get(
            f"/api/knowledge/{document_id}/ocr?student_id={owner}", headers=owner_headers
        )
        assert report.status_code == 200
        report_body = report.json()
        assert report_body["privacy_boundary"]["raw_page_api_available"] is False
        assert report_body["privacy_boundary"]["served_assets"] == "redacted_only"
        assert "student@example.com" not in report.text

        page = client.get(
            f"/api/knowledge/{document_id}/ocr/pages/1?student_id={owner}",
            headers=owner_headers,
        )
        assert page.status_code == 200
        assert page.headers["content-type"].startswith("image/png")
        assert page.headers["cache-control"] == "private, no-store"

        gate = client.get(
            f"/api/knowledge/{document_id}/ocr/externalization-check?student_id={owner}",
            headers=owner_headers,
        )
        assert gate.status_code == 200
        assert gate.json()["raw_page_allowed"] is False
        assert gate.json()["redacted_page_allowed"] is True

        denied = client.get(
            f"/api/knowledge/{document_id}/ocr?student_id={owner}", headers=other_headers
        )
        assert denied.status_code == 403

        with SessionLocal() as session:
            source = session.get(DBSourceDocument, source_document_id)
            assert source is not None
            refs = session.query(DBSourceRef).filter_by(source_document_id=source_document_id).all()
            assert any(ref.image_region for ref in refs)
            assert "student@example.com" not in source.parser_metadata.__repr__()

        asset_root = upload_root / owner / document_id
        assert any(asset_root.rglob("page-0001-redacted.png"))
        deleted = client.delete(
            f"/api/knowledge/{document_id}?student_id={owner}", headers=owner_headers
        )
        assert deleted.status_code == 200
        assert not asset_root.exists()
