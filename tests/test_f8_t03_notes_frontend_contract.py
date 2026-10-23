from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "frontend" / "src" / "views" / "Notes.vue"
ROUTER = ROOT / "frontend" / "src" / "router" / "index.js"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_three_column_workspace_has_stable_ownership_and_progressive_depth() -> None:
    view = source(VIEW)

    for marker in (
        'data-testid="notes-workspace"',
        'data-testid="notes-explorer"',
        'data-testid="notes-document"',
        'data-testid="notes-context"',
        'data-testid="notes-ai-suggestion"',
        'data-testid="notes-history"',
    ):
        assert marker in view
    assert 'data-testid="notes-source"' not in view
    assert 'data-testid="notes-learning-actions"' not in view
    assert "grid-template-columns: 250px minmax(450px, 1fr) 294px" in view
    assert "左侧选择后即可阅读、编辑和追溯来源" in view
    assert "建议始终独立预览" in view
    assert "保存新版本" in view
    assert "更多操作" in view


def test_document_and_resource_source_data_stays_compatible_without_a_source_module() -> None:
    view = source(VIEW)

    for marker in (
        "knowledge_selection",
        "handout",
        "code_sandbox",
        "review_task",
        "sourceLocation",
    ):
        assert marker in view
    assert 'data-testid="notes-source"' not in view
    assert "返回来源" not in view
    assert "source_context" in view
    assert "完整文件" not in view
    assert "iframe" not in view.lower()


def test_optimistic_save_conflict_draft_and_history_are_explicit() -> None:
    view = source(VIEW)

    for marker in (
        "draftStorageKey",
        "localStorage.setItem",
        "expected_version: note.lock_version",
        "idempotency_key: operationKey('save'",
        "e?.response?.status === 409",
        'data-testid="notes-conflict"',
        "syncConflictBase",
        "discardDraft",
        "getNoteVersions",
        "restoreNoteVersion",
        "历史恢复",
        "恢复到版本",
        "currentHistoryVersion",
    ):
        assert marker in view
    restore = view[view.index("async function restoreVersion"):view.index("function sourceLocation")]
    assert "replaceNote(updated)" in restore
    assert "version_number" in restore
    assert "另存为新版本" not in view


def test_ai_suggestion_never_overwrites_the_user_body_without_confirmation() -> None:
    view = source(VIEW)
    generation = view[view.index("async function triggerAiPolish"):view.index("async function applyAiSuggestion")]
    application = view[view.index("async function applyAiSuggestion"):view.index("async function syncConflictBase")]

    assert "data.note?.ai_suggestion" in generation
    assert "editForm.value.content =" not in generation
    assert "suggestion.content" in application
    assert "change_type: 'ai_suggestion_applied'" in application
    assert "AI 建议已作为版本" in application
    assert "旧正文仍在历史中" in application


def test_protected_720_note_capabilities_remain_reachable() -> None:
    view = source(VIEW)

    for capability in (
        "createNote",
        "updateNote",
        "deleteNote",
        "searchQuery",
        "selectedTags",
        "selectedConcepts",
        "renderMarkdown",
        "exportMarkdown",
        "exportPdf",
        "triggerAiPolish",
    ):
        assert capability in view
    for label in (
        "新建学习笔记",
        "搜索正文、概念或标签",
        "导出 Markdown",
        "导出 PDF",
        "生成排版建议",
    ):
        assert label in view
    assert "学习关联" not in view


def test_note_workspace_does_not_create_parallel_mastery_or_assessment_paths() -> None:
    view = source(VIEW)
    template = view[view.index("<template>"):view.index("<style scoped>")]

    for forbidden in (
        "createLearningEvent",
        "updateMastery",
        "completePathTask",
        "unlockExam",
        "一键测评",
        "艾宾浩斯遗忘曲线监控",
        "editForm.source",
        "<select",
    ):
        assert forbidden not in view
    assert 'data-testid="notes-source"' not in template
    assert 'data-testid="notes-learning-actions"' not in template
    assert "生成对话内练习" not in template


def test_route_visual_and_accessibility_contracts_are_preserved() -> None:
    view = source(VIEW)
    router = source(ROUTER)
    lowered = view.lower()

    assert "path: '/workspace/notes'" in router
    assert "legacy('/notes'" in router
    for required in (
        "var(--color-page)",
        "var(--color-surface)",
        "var(--color-text)",
        "var(--color-accent)",
        "var(--font-sans)",
        "font-size: 14px",
        "border-radius: var(--radius-panel)",
        "aria-label",
        "visually-hidden",
    ):
        assert required in view
    for forbidden in (
        "linear-gradient",
        "radial-gradient",
        "backdrop-filter",
        "green-",
        "orange-",
        "purple-",
        "indigo-",
        "text-[",
        "rounded-xl",
        "rounded-2xl",
        "font-size: 10px",
        "font-size: 11px",
        "font-size: 12px",
        "font-size: 13px",
    ):
        assert forbidden not in lowered
