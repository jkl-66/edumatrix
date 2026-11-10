from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
READER = ROOT / "frontend" / "src" / "views" / "KnowledgeDocumentReader.vue"
KNOWLEDGE_API = ROOT / "frontend" / "src" / "api" / "knowledge.js"
TOOLBAR = ROOT / "frontend" / "src" / "components" / "SelectionToolbar.vue"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_reader_export_uses_canonical_blob_route_without_exposing_internal_hashes() -> None:
    api = _source(KNOWLEDGE_API)
    reader = _source(READER)
    assert "function getDocumentReaderExport" in api
    assert "/v1/document-reader/documents/${encodeURIComponent(sourceDocumentId)}/export" in api
    assert "responseType: 'blob'" in api
    for marker in ("exportKnowledgeDocument", "导出知识文件", "已导出，与本次阅读的资料版本一致"):
        assert marker in reader
    assert "源哈希" not in reader
    # The response continues to preserve headers for filename/integrity consumers.
    assert "headers: r.headers" in api


def test_reader_export_has_recoverable_error_and_stays_separate_from_resource_generation() -> None:
    reader = _source(READER)
    toolbar = _source(TOOLBAR)
    for marker in ("exportBusy", "exportError", "exportNotice", "重试导出", "原文和阅读位置仍可继续使用"):
        assert marker in reader
    for marker in ("generateDocumentResource", "generateDocumentSelectionResource", "生成并归档", "学习资源任务已保存"):
        assert marker in reader
    for action in ("针对选区提问", "把选区记入笔记", "基于选区生成资源", "取消选区"):
        assert action in toolbar
    assert "createLearningEvent" not in reader
    assert "updateMastery" not in reader
