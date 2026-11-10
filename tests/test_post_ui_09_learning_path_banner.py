from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEARNING_PATH = ROOT / "frontend/src/views/LearningPathGraph.vue"
REVIEW = ROOT / "frontend/src/views/Review.vue"
REVIEW_TOOLS = ROOT / "frontend/src/components/ReviewToolsPanel.vue"
CONTEXT_BAND = ROOT / "frontend/src/components/CompetitionDemoContextBand.vue"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_learning_path_uses_current_course_without_competition_context_request() -> None:
    source = _source(LEARNING_PATH)

    assert "CompetitionDemoContextBand" not in source
    assert 'page="path"' not in source
    assert "getCompetitionDemoContext" not in source
    assert "const demoContext = ref(null)" in source


def test_learning_path_core_content_and_actions_remain() -> None:
    source = _source(LEARNING_PATH)

    for marker in (
        "学习空间 / 路径",
        "学习路径",
        'data-testid="path-total-view"',
        'data-testid="path-subject-view"',
        "<PathTaskList",
        "path-progress-summary",
        "学习日历",
        "重新编排",
        "prepareSubjectAdjustment",
        "openPathTask",
    ):
        assert marker in source


def test_review_tools_do_not_show_competition_banner() -> None:
    assert CONTEXT_BAND.exists()

    review = _source(REVIEW)
    review_tools = _source(REVIEW_TOOLS)
    assert "CompetitionDemoContextBand" not in review
    assert "CompetitionDemoContextBand" not in review_tools
    assert 'page="review"' not in review_tools
