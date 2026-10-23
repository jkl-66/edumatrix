from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "frontend/src/views/LearningPathGraph.vue"


def _subject_css(source: str) -> str:
    start = source.index(".path-subject {")
    end = source.index(".path-budget", start)
    return source[start:end]


def test_learning_path_subject_card_places_title_and_meta_on_separate_wrapping_rows():
    source = VIEW.read_text(encoding="utf-8")
    css = _subject_css(source)
    assert "grid-template-columns: minmax(0, 1fr);" in css
    assert ".path-subject__title" in css
    assert "display: block" in css
    assert "white-space: normal" in css
    assert "overflow-wrap: anywhere" in css
    assert ".path-subject__meta" in css
    assert "grid-column: 1" in css
    assert "line-height: 1.45" in css


def test_learning_path_subject_card_keeps_existing_actions_and_progress_bindings():
    source = VIEW.read_text(encoding="utf-8")
    assert "toggleSubjectPath(subject)" in source
    assert "prepareSubjectAdjustment(subject, 'supplement')" in source
    assert "prepareSubjectAdjustment(subject, 'replan')" in source
    assert ":style=\"{ width: `${subject.progress}%` }\"" in source


def test_completed_return_task_is_visibly_reconciled_before_the_next_day_projection():
    source = VIEW.read_text(encoding="utf-8")
    bundle = (ROOT / "frontend/src/views/ResourceBundleWorkspace.vue").read_text(encoding="utf-8")

    assert "path-completion-receipt" in source
    assert "本轮学习已完成" in source
    assert "当前任务 1/1 完成" in source
    assert "allPathTasks.value.find(item => item.id === requestedTaskId)" in source
    assert "job.value?.manifest?.task_id || route.query.return_task" in bundle
