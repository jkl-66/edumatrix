from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHELF = ROOT / "frontend" / "src" / "components" / "KnowledgeCourseShelf.vue"
KNOWLEDGE = ROOT / "frontend" / "src" / "views" / "Knowledge.vue"
ROUTER = ROOT / "frontend" / "src" / "router" / "index.js"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_course_first_home_order_and_preloaded_course_contract() -> None:
    source = _source(SHELF)

    assert source.index("我的书架") < source.index("智能推荐") < source.index("联网发现")
    assert "listKnowledgeCourseShelf" in source
    assert "无需先上传教材" in source
    assert "requires_course_upload" not in source
    assert 'data-testid="my-course-shelf"' in source
    assert "chapter_count" in source
    assert "document_count" in source
    assert "knowledge_point_count" in source
    assert "source_count" in source
    assert "source_health" in source
    assert "index_status" in source


def test_course_workspace_reuses_reading_and_search_boundaries() -> None:
    shelf = _source(SHELF)
    knowledge = _source(KNOWLEDGE)

    assert "getCanonicalCourseOutline" in shelf
    assert "crossLanguageCourseSearch" in shelf
    assert 'emit("open-source"' not in shelf  # Vue source uses single quotes consistently.
    assert "emit('open-source'" in shelf
    assert "emit('open-search-result'" in shelf
    assert "openCourseSource" in knowledge
    assert "openCourseSearchResult" in knowledge
    assert "source_document_id" in knowledge
    assert "/knowledge/documents/" in knowledge
    for removed in (
        "getCanonicalCourseSource",
        "openDocModal",
        "getKnowledgeDocumentOcr",
        "crossModalSearch",
        "KnowledgeGraphExplorer",
    ):
        assert removed not in knowledge


def test_discovery_and_graph_coordination_do_not_overclaim_authority() -> None:
    source = _source(SHELF)

    assert "候选资料不会自动进入课程" in source
    assert "许可或用途信息缺失时，不允许进入权威课程" in source
    assert "浏览不会改变学习掌握度" in source
    assert 'data-testid="knowledge-discovery-boundary"' in source
    assert 'data-testid="course-graph-contract"' in source
    assert "downloadWebFile" not in source
    assert "addWebSource" not in source


def test_all_required_frontend_states_and_recovery_actions_are_present() -> None:
    source = _source(SHELF)

    for marker in (
        'data-testid="course-shelf-loading"',
        'data-testid="course-shelf-error"',
        'data-testid="course-shelf-empty"',
        'data-testid="course-outline-loading"',
        'data-testid="course-outline-error"',
        'data-testid="course-outline-empty"',
        'data-testid="course-search-results"',
    ):
        assert marker in source
    assert "重新加载" in source
    assert "重试" in source
    assert "部分资料仍在整理" in source
    assert "没有找到足够匹配的内容" in source


def test_legacy_capabilities_are_removed_from_the_course_entry() -> None:
    source = _source(KNOWLEDGE)

    assert "<KnowledgeCourseShelf" in source
    assert "@open-source" in source
    assert "@open-search-result" in source
    for removed in (
        "knowledge-advanced-tools",
        "advancedTools",
        "个人资料",
        "高级工具",
        "uploadKnowledgeDocumentsBatch",
        "getKnowledgeDocumentOcr",
        "crossModalSearch",
        "KnowledgeGraphExplorer",
        "knowledge-modal",
    ):
        assert removed not in source


def test_knowledge_routes_stay_inside_the_student_knowledge_space() -> None:
    source = _source(ROUTER)

    for path in (
        "/knowledge",
        "/knowledge/courses/:courseId",
        "/knowledge/documents/:documentId",
        "/knowledge/graph/:courseId",
        "/knowledge/discover",
    ):
        assert f"path: '{path}'" in source
    assert "component: Knowledge" in source
    assert "navigationLevel: 'primary'" in source


def test_new_default_surface_uses_the_frozen_minimal_visual_contract() -> None:
    source = _source(SHELF).lower()

    for token in ("#f5f7f7", "#ffffff", "#06141b", "#11212d"):
        assert token in source
    for forbidden in (
        "linear-gradient",
        "radial-gradient",
        "backdrop-filter",
        "#10b981",
        "#0ea5e9",
        "#8b5cf6",
        "font-size: 12px",
        "font-size: 13px",
    ):
        assert forbidden not in source
    assert "border-radius: 8px" in source
    assert "1440" not in source  # Viewport validation belongs to browser evidence, not runtime copy.


def test_course_document_entry_delegates_to_the_dedicated_reader() -> None:
    source = _source(KNOWLEDGE)

    assert "KnowledgeCourseShelf" in source
    assert "openCourseSource" in source
    assert "openCourseSearchResult" in source
    assert "sourceError" in source
    assert "path: `/knowledge/documents/${encodeURIComponent(sourceDocumentId)}`" in source
    assert "knowledge-modal" not in source
