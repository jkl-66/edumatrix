from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
READER = ROOT / "frontend" / "src" / "views" / "KnowledgeDocumentReader.vue"
TOOLBAR = ROOT / "frontend" / "src" / "components" / "SelectionToolbar.vue"
KNOWLEDGE_API = ROOT / "frontend" / "src" / "api" / "knowledge.js"
KNOWLEDGE = ROOT / "frontend" / "src" / "views" / "Knowledge.vue"
ROUTER = ROOT / "frontend" / "src" / "router" / "index.js"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_document_route_uses_the_dedicated_reader_from_the_course_entry() -> None:
    router = _source(ROUTER)
    knowledge = _source(KNOWLEDGE)

    assert "const KnowledgeDocumentReader = () => import('../views/KnowledgeDocumentReader.vue')" in router
    assert (
        "path: '/knowledge/documents/:documentId', name: 'KnowledgeDocument', "
        "component: KnowledgeDocumentReader"
    ) in router
    assert "KnowledgeCourseShelf" in knowledge
    assert '@open-source="openCourseSource"' in knowledge
    assert '@open-search-result="openCourseSearchResult"' in knowledge
    assert "sourceDocumentId = item?.source_document_id" in knowledge
    assert "await getCanonicalCourseSource(sourceDocumentId)" in knowledge
    assert "path: `/knowledge/documents/${encodeURIComponent(canonicalDocumentId)}`" in knowledge
    assert "course_id: canonicalCourseId" in knowledge
    assert "source_ref_id: canonicalSourceRefId" in knowledge
    assert "openDocModal" not in knowledge


def test_reader_api_client_exposes_position_selection_source_and_both_generation_scopes() -> None:
    source = _source(KNOWLEDGE_API)

    for symbol in (
        "getDocumentReaderDocument",
        "getDocumentReaderState",
        "saveDocumentReadingPosition",
        "createDocumentSelection",
        "retryDocumentSelectionOcr",
        "askDocumentSelection",
        "saveDocumentSelectionNote",
        "generateDocumentSelectionResource",
        "generateDocumentResource",
    ):
        assert f"function {symbol}" in source
    assert "/v1/document-reader/documents/${encodeURIComponent(sourceDocumentId)}/generation-jobs" in source
    assert "/v1/document-reader/selections/${encodeURIComponent(selectionId)}/generation-jobs" in source


def test_reader_has_large_source_first_layout_and_complete_navigation_tools() -> None:
    source = _source(READER)

    assert "grid-template-columns: minmax(190px, 20fr) minmax(540px, 58fr) minmax(230px, 22fr)" in source
    assert 'aria-label="课程与章节目录"' in source
    assert 'aria-label="来源、问答与笔记"' in source
    assert "document-content" in source
    assert "page-frame" in source
    for label in (
        "在当前文档中搜索",
        "第 {{ activePage }} / {{ readerDoc.pages.length }} 页",
        "放大",
        "缩小",
        "导出解析文本",
        "当前来源",
        "定位当前选区",
    ):
        assert label in source
    for marker in (
        "buildReaderPresentation",
        "displayToSource",
        "sourceOffsetForDisplay",
        "displayOffsetForSource",
    ):
        assert marker in source


def test_text_and_image_selections_share_source_bound_actions_and_recovery() -> None:
    reader = _source(READER)
    toolbar = _source(TOOLBAR)

    for marker in (
        "handleTextSelection",
        "beginImageSelection",
        "moveImageSelection",
        "finishImageSelection",
        "normalized_rect: rect",
        "source_ref_id: ref?.id || null",
        "document_version: readerDoc.value.document_version",
        "retryDocumentSelectionOcr",
        "图片区域已保留",
        "问题和选区均已保留",
        "正文和来源仍保留在这里",
        "String(readerDoc.value?.content || '').slice(start, end)",
    ):
        assert marker in reader
    for action in ("针对选区提问", "把选区记入笔记", "基于选区生成资源", "取消选区"):
        assert action in toolbar
    assert ":selection-type=\"selection?.selection_type || 'text'\"" in reader
    assert "selection.value.selection_type === 'image'" in reader


def test_reader_generates_into_existing_resources_and_never_writes_mastery_evidence() -> None:
    source = _source(READER)

    for marker in (
        "generateDocumentResource",
        "generateDocumentSelectionResource",
        "当前文件",
        "当前选区",
        "生成并归档",
        "任务已进入资源中心",
        "openResourceCenter",
    ):
        assert marker in source
    for forbidden in (
        "createLearningEvent",
        "updateMastery",
        "completePathTask",
        "unlockExam",
        "private_chain_of_thought",
    ):
        assert forbidden not in source


def test_reader_uses_f1_minimal_visual_contract_and_no_small_text() -> None:
    source = (_source(READER) + _source(TOOLBAR)).lower()

    for required in (
        "var(--color-page)",
        "var(--color-surface)",
        "var(--color-text)",
        "var(--color-accent)",
        "border-radius: 8px",
    ):
        assert required in source
    for forbidden in (
        "linear-gradient",
        "radial-gradient",
        "backdrop-filter",
        "#10b981",
        "#0ea5e9",
        "#8b5cf6",
        "font-size: 10px",
        "font-size: 11px",
        "font-size: 12px",
        "font-size: 13px",
    ):
        assert forbidden not in source


def test_reader_keeps_loading_empty_failure_retry_recovery_and_completion_states() -> None:
    source = _source(READER)

    for marker in (
        "正在打开原文",
        "文档暂时无法打开",
        "重新加载",
        "当前文档没有可读正文",
        "正在加载解析页图",
        "重试本页",
        "重试 OCR",
        "已恢复上次位置",
        "已保存，文档位置与选区引用已归档",
        "任务已进入资源中心",
    ):
        assert marker in source
