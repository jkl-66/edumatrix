from __future__ import annotations

import hashlib
from pathlib import Path

from app.database import DBSourceDocument
from app.document_selection import _pptx_slides, _reader_mode, _source_file_path


ROOT = Path(__file__).resolve().parents[1]
CURATED = ROOT / "data" / "curated" / "embedded_machine_learning_engineering_v2"


def _source(path: Path, *, file_format: str) -> DBSourceDocument:
    relative = path.relative_to(ROOT).as_posix()
    return DBSourceDocument(
        source_path=f"versioned-course@revision:{path.name}",
        file_format=file_format,
        source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        parser_metadata={"bundle_asset": {"path": relative}},
    )


def test_versioned_bundle_asset_resolves_original_file() -> None:
    path = CURATED / "materials" / "嵌入式机器学习与边缘智能工程手册.pdf"
    source = _source(path, file_format="pdf")
    assert _source_file_path(source) == path.resolve()
    assert _reader_mode(source, has_pages=True, has_media=False) == "native_pages"


def test_pptx_projection_contains_slides_and_preserves_blank_slide() -> None:
    multi = CURATED / "materials" / "module-03" / "3.3.5.how-to-evaluate-a-model.1.pptx"
    blank = CURATED / "materials" / "module-02" / "2.2.1.introduction-to-neural-networks.1.pptx"
    multi_source = _source(multi, file_format="pptx")
    blank_source = _source(blank, file_format="pptx")
    slides = _pptx_slides(multi_source)
    blank_slides = _pptx_slides(blank_source)
    assert len(slides) >= 2
    assert any(str(item.get("text") or "").strip() for item in slides)
    assert len(blank_slides) == 1
    assert blank_slides[0]["text"] == ""
    assert _reader_mode(multi_source, has_pages=False, has_media=False, has_slides=True) == "native_slides"
