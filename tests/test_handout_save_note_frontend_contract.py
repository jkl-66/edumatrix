from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "frontend" / "src" / "views" / "HandoutWorkspace.vue"
TOOLBAR = ROOT / "frontend" / "src" / "components" / "ResourceToolbar.vue"


def test_handout_saves_complete_content_and_reuses_notes_flow():
    view = VIEW.read_text(encoding="utf-8")
    toolbar = TOOLBAR.read_text(encoding="utf-8")

    assert "handoutNoteMarkdown" in view
    assert "orderedHandoutSections(content).map(handoutSectionMarkdown)" in view
    order = (VIEW.parents[1] / "utils/handoutReadingOrder.js").read_text(encoding="utf-8")
    for kind in ("concepts", "examples", "counterExamples", "codeBlocks", "miniQuiz", "transferTasks"):
        assert kind in order
    for heading in ("学习目标", "参考材料"):
        assert heading in view
    assert "createNote, getNotes, updateNote" in view
    assert "handout-note-upgrade-" in view
    assert "name: 'Notes'" in view
    assert "window.location.assign(notesUrl)" in view
    assert "保存到笔记本" in toolbar


def test_handout_save_preserves_source_version_and_idempotency_contract():
    view = VIEW.read_text(encoding="utf-8")
    assert "resource_version_id: selectedVersion.value.id" in view
    assert "idempotency_key: idempotencyKey" in view
    assert "expected_version: legacyNote.lock_version" in view
