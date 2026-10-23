from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "frontend/src/views/Knowledge.vue"
SHELF = ROOT / "frontend/src/components/KnowledgeCourseShelf.vue"
READER = ROOT / "frontend/src/views/KnowledgeDocumentReader.vue"
ROUTER = ROOT / "frontend/src/router/index.js"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_knowledge_entry_removes_personal_and_advanced_surface() -> None:
    knowledge = _source(KNOWLEDGE)
    shelf = _source(SHELF)

    for source in (knowledge, shelf):
        for forbidden in (
            "个人资料",
            "高级工具",
            "knowledge-advanced",
            "open-advanced",
            "uploadKnowledgeDocumentsBatch",
            "crossModalSearch",
            "getKnowledgeDocumentOcr",
            "KnowledgeGraphExplorer",
        ):
            assert forbidden not in source

    assert knowledge.count("<KnowledgeCourseShelf") == 1
    assert "openCourseSource" in knowledge
    assert "openCourseSearchResult" in knowledge
    assert "/knowledge/documents/" in knowledge
    assert "source_ref_id" in knowledge


def test_useful_knowledge_capabilities_remain_in_their_formal_locations() -> None:
    shelf = _source(SHELF)
    reader = _source(READER)
    router = _source(ROUTER)

    for marker in (
        "listKnowledgeCourseShelf",
        "getCanonicalCourseOutline",
        "crossLanguageCourseSearch",
        "课程正文检索",
        "打开本章文档",
        "openGraph",
    ):
        assert marker in shelf

    for marker in (
        "SelectionToolbar",
        "image-selection-layer",
        "handleTextSelection",
        "askDocumentSelection",
        "saveDocumentSelectionNote",
        "generateDocumentSelectionResource",
    ):
        assert marker in reader

    for path in (
        "/knowledge",
        "/knowledge/courses/:courseId",
        "/knowledge/documents/:documentId",
        "/knowledge/graph/:courseId",
    ):
        assert f"path: '{path}'" in router


def test_empty_course_state_does_not_redirect_to_personal_tools() -> None:
    shelf = _source(SHELF)
    empty_start = shelf.index('data-testid="course-shelf-empty"')
    empty_end = shelf.index('</section>', empty_start)
    empty_state = shelf[empty_start:empty_end]

    assert "课程资料" in empty_state
    assert "首次使用时上传" in empty_state
    assert "打开" not in empty_state
    assert 'data-testid="create-personal-course-empty"' in empty_state
