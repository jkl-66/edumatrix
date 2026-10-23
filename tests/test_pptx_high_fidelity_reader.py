from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app import document_selection
from app.database import DBSourceDocument


ROOT = Path(__file__).resolve().parents[1]
CURATED = ROOT / "data" / "curated" / "embedded_machine_learning_engineering_v2"


def _source(path: Path) -> DBSourceDocument:
    relative = path.relative_to(ROOT).as_posix()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return DBSourceDocument(
        id="pptx-high-fidelity-test",
        source_path=f"versioned-course@revision:{path.name}",
        filename=path.name,
        file_format="pptx",
        source_sha256=digest,
        parser_metadata={"bundle_asset": {"path": relative, "sha256": digest}},
    )


def test_pptx_high_fidelity_preview_is_rendered_and_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if document_selection._libreoffice_executable() is None:
        pytest.skip("LibreOffice is not installed")
    monkeypatch.setenv("EDUMATRIX_PPTX_PREVIEW_DIR", str(tmp_path))
    path = CURATED / "materials" / "module-02" / "2.2.1.introduction-to-neural-networks.1.pptx"
    source = _source(path)

    first = document_selection._pptx_preview_payload(source)
    assert first["status"] == "ready"
    assert len(first["slides"]) == 1
    assert first["slides"][0]["asset_url"].endswith("/slide-previews/1")
    assert first["slides"][0]["width"] > first["slides"][0]["height"] > 0
    rendered = list(tmp_path.rglob("slide-*.png"))
    assert len(rendered) == 1
    assert rendered[0].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    modified = rendered[0].stat().st_mtime_ns

    second = document_selection._pptx_preview_payload(source)
    assert second == first
    assert rendered[0].stat().st_mtime_ns == modified


def test_pptx_high_fidelity_preview_has_honest_unavailable_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDUMATRIX_PPTX_PREVIEW_DIR", str(tmp_path))
    monkeypatch.setattr(document_selection, "_libreoffice_executable", lambda: None)
    path = CURATED / "materials" / "module-02" / "2.2.1.introduction-to-neural-networks.1.pptx"
    source = _source(path)

    slides, preview = document_selection._pptx_slides_with_previews(source)
    assert preview["status"] == "unavailable"
    assert preview["slides"] == []
    assert len(slides) == 1
    assert "preview_url" not in slides[0]


def test_pptx_high_fidelity_preview_contains_unexpected_converter_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    path = CURATED / "materials" / "module-02" / "2.2.1.introduction-to-neural-networks.1.pptx"
    source = _source(path)

    def fail_source(_source: DBSourceDocument) -> tuple[Path, str]:
        raise PermissionError("private path")

    monkeypatch.setattr(document_selection, "_verified_pptx_source", fail_source)
    preview = document_selection._pptx_preview_payload(source)

    assert preview == {
        "status": "failed",
        "message": "原版幻灯片暂时无法生成，你仍可查看文字阅读版或下载原文件。",
        "slides": [],
    }


def test_pptx_reader_uses_authenticated_preview_blobs_as_primary_canvas() -> None:
    api_source = (ROOT / "frontend" / "src" / "api" / "knowledge.js").read_text(encoding="utf-8")
    reader_source = (ROOT / "frontend" / "src" / "views" / "KnowledgeDocumentReader.vue").read_text(encoding="utf-8")

    assert "getDocumentReaderSlidePreview" in api_source
    assert "/slide-previews/" in api_source
    assert 'v-if="activeSlideAssetUrl"' in reader_source
    assert 'class="pptx-slide-canvas__page"' in reader_source
    assert ':style="pptxThumbnailStyle(slide)"' in reader_source
    assert 'v-if="hasSlides" class="pptx-reader__layout"' in reader_source
    assert "全屏查看幻灯片" in reader_source
    assert ".pptx-reader__stage:fullscreen .pptx-slide-canvas__page" in reader_source
    assert "max-height: calc(100vh - 124px)" in reader_source
    assert "按原始版式查看演示文稿" in reader_source
