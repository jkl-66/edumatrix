from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESOURCE_CENTER = ROOT / "frontend/src/views/ResourceCenter.vue"


def source() -> str:
    return RESOURCE_CENTER.read_text(encoding="utf-8")


def test_search_field_has_no_visible_placeholder_but_keeps_search_behavior() -> None:
    view = source()
    search_start = view.index('<SearchField ')
    search_end = view.index('/>', search_start) + 2
    search = view[search_start:search_end]

    assert 'v-model="query"' in search
    assert 'clearable' in search
    assert 'aria-label="搜索资源"' in search
    assert 'SearchField' in search

    shared = (ROOT / "frontend/src/components/ui/SearchField.vue").read_text(encoding="utf-8")
    assert 'type="search"' in shared
    assert 'title="清除搜索"' in shared
    assert '@click.prevent="clearValue"' in shared


def test_toolbar_shrinks_from_the_search_side_and_keeps_right_controls_fixed() -> None:
    view = source()

    for marker in (
        ".catalog-toolbar { display: flex; align-items: center;",
        ".search-field { display: flex; min-width: 44px; height: 40px; flex: 1 1 160px;",
        ".catalog-toolbar > select { width: 118px; flex: 0 1 118px; }",
        ".view-switch { display: grid; width: 90px; flex: 0 0 90px; grid-template-columns: repeat(2, 44px);",
        ".refresh-button { width: 42px; flex: 0 0 42px;",
        ".catalog-toolbar > select { width: auto; flex: 1 1 100px; }",
    ):
        assert marker in view

    assert "grid-template-columns: minmax(220px, 1fr) 118px 124px auto 76px 42px" not in view
    assert "grid-template-columns: minmax(210px, 1fr) 112px 118px 76px 42px" not in view


def test_grid_list_refresh_controls_and_accessible_labels_remain() -> None:
    view = source()

    for marker in (
        'class="view-switch" aria-label="资源布局"',
        'title="网格视图"',
        'title="列表视图"',
        "@click=\"setView('grid')\"",
        "@click=\"setView('list')\"",
        'class="refresh-button" title="刷新资源"',
        "@click=\"loadResources()\"",
        ".view-switch button.active { background: #11212d; color: #fff; }",
        ".archive-toggle { display: none; }",
    ):
        assert marker in view
