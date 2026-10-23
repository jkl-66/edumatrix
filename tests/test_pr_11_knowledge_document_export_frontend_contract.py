from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
READER = ROOT / "frontend" / "src" / "views" / "KnowledgeDocumentReader.vue"
KNOWLEDGE_API = ROOT / "frontend" / "src" / "api" / "knowledge.js"
TOOLBAR = ROOT / "frontend" / "src" / "components" / "SelectionToolbar.vue"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_reader_export_uses_canonical_blob_route_and_exposes_revision_metadata() -> None:
    api = _source(KNOWLEDGE_API)
    reader = _source(READER)
    assert "function getDocumentReaderExport" in api
    assert "/v1/document-reader/documents/${encodeURIComponent(sourceDocumentId)}/export" in api
    assert "responseType: 'blob'" in api
    for marker in ("exportKnowledgeDocument", "导出知识文件", "知识文件已导出"):
        assert marker in reader
    for marker in ("x-document-revision", "x-source-sha256"):
        assert marker in reader


def test_reader_export_has_recoverable_error_and_stays_separate_from_resource_generation() -> None:
    reader = _source(READER)
    toolbar = _source(TOOLBAR)
    for marker in ("exportBusy", "exportError", "exportNotice", "重试导出", "原文和阅读位置仍可继续使用"):
        assert marker in reader
    for marker in ("generateDocumentResource", "generateDocumentSelectionResource", "生成并归档", "任务已进入资源中心"):
        assert marker in reader
    for action in ("针对选区提问", "把选区记入笔记", "基于选区生成资源", "取消选区"):
        assert action in toolbar
    assert "createLearningEvent" not in reader
    assert "updateMastery" not in reader
