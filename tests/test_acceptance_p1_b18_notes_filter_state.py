from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "frontend/src/views/Notes.vue"


def source() -> str:
    return VIEW.read_text(encoding="utf-8")


def test_category_selection_is_route_backed_and_validated() -> None:
    view = source()

    for marker in (
        "const SOURCE_FILTER_IDS = new Set(['all', 'document', 'resource', 'review', 'wrong', 'personal'])",
        "function normalizedSourceFilter(value)",
        "route.query.category",
        "category: nextFilter",
        "@click=\"setSourceFilter(filter.id)\"",
        "category: 'all'",
    ):
        assert marker in view

    assert "activeSourceFilter.value = filter.id" not in view
    assert "getNotes(props.studentId)" in view
    assert "getReviewPlans(props.studentId)" not in view


def test_note_selection_and_scroll_are_preserved_without_new_api_or_learning_writes() -> None:
    view = source()

    for marker in (
        "const notesListRef = ref(null)",
        "function persistNotesListScroll(event)",
        "notes_scroll: scrollTop ? String(scrollTop) : undefined",
        "function restoreNotesListScroll()",
        "notesListRef.value.scrollTop",
        "note_id: selectedNoteId.value || undefined",
        "@scroll.passive=\"persistNotesListScroll\"",
        "router.replace({ query: { ...route.query, note_id: noteId } })",
    ):
        assert marker in view

    for forbidden in (
        "createLearningEvent",
        "updateMastery",
        "api.post('/notes/filter",
        "api.get('/notes/filter",
    ):
        assert forbidden not in view


def test_existing_notes_filters_and_user_visible_boundaries_remain() -> None:
    view = source()

    for marker in (
        "searchQuery",
        "selectedTags",
        "selectedConcepts",
        "filteredNotes",
        "clearFilters",
        "data-testid=\"notes-workspace\"",
        "data-testid=\"notes-document\"",
        "data-testid=\"notes-context\"",
        "搜索正文、概念或标签",
    ):
        assert marker in view
    assert 'data-testid="notes-source"' not in view
    assert 'data-testid="notes-learning-actions"' not in view
