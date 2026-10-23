from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "src"
SEARCH_FIELD = FRONTEND / "components" / "ui" / "SearchField.vue"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_search_field_has_non_overlapping_icon_padding_focus_and_clear() -> None:
    source = read(SEARCH_FIELD)

    for marker in (
        "<Search class=\"ui-search-field__icon\"",
        'type="search"',
        "@input=\"updateValue\"",
        "@keydown=\"emit('keydown', $event)\"",
        "class=\"ui-search-field__clear\"",
        ".ui-search-field:focus-within",
        ".ui-search-field__icon",
        "gap: 8px",
        "padding: 0;",
    ):
        assert marker in source


def test_all_existing_search_inputs_use_the_shared_control() -> None:
    expected = (
        "views/Notes.vue",
        "views/KnowledgeDocumentReader.vue",
        "components/KnowledgeGraphExplorer.vue",
        "views/History.vue",
        "views/KnowledgeDiscoveryWorkspace.vue",
        "views/MindmapWorkspace.vue",
        "views/ResourceCenter.vue",
        "views/WrongQuestionBook.vue",
        "views/Teacher.vue",
        "views/AdminAccounts.vue",
        "views/MarketplaceWorkspace.vue",
        "components/KnowledgeCourseShelf.vue",
        "components/ReviewHistoryPanel.vue",
        "views/InternalObjectInspector.vue",
    )
    for relative in expected:
        assert "SearchField" in read(FRONTEND / relative)

    raw_inputs = []
    for path in FRONTEND.rglob("*.vue"):
        if path == SEARCH_FIELD:
            continue
        if 'type="search"' in read(path) or "type='search'" in read(path):
            raw_inputs.append(path.relative_to(ROOT).as_posix())
    assert raw_inputs == []


def test_original_search_behaviors_and_accessible_names_remain() -> None:
    checks = {
        "views/Notes.vue": ("v-model=\"searchQuery\"", "aria-label=\"搜索笔记\"", "搜索正文、概念或标签"),
        "views/KnowledgeDocumentReader.vue": ("v-model=\"searchQuery\"", "在当前文档中搜索", "上一个搜索结果", "下一个搜索结果"),
        "components/KnowledgeGraphExplorer.vue": ("v-model=\"searchQuery\"", "@update:model-value=\"doSearch\"", "检索知识点"),
        "views/KnowledgeDiscoveryWorkspace.vue": ("v-model=\"query\"", "data-testid=\"discovery-search-input\"", "联网搜索"),
        "views/MindmapWorkspace.vue": ("v-model=\"query\"", "搜索思维导图节点", "没有找到匹配节点。"),
        "views/ResourceCenter.vue": ("v-model=\"query\"", "clearable", "aria-label=\"搜索资源\""),
    }
    for relative, markers in checks.items():
        source = read(FRONTEND / relative)
        for marker in markers:
            assert marker in source, f"{relative} missing {marker}"
