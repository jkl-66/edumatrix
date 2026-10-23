from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEARNING_PATH = ROOT / "frontend/src/views/LearningPathGraph.vue"
SHOWCASE = ROOT / "frontend/src/views/CompetitionShowcase.vue"
REVIEW = ROOT / "frontend/src/views/Review.vue"
REVIEW_TOOLS = ROOT / "frontend/src/components/ReviewToolsPanel.vue"
CONTEXT_BAND = ROOT / "frontend/src/components/CompetitionDemoContextBand.vue"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_learning_path_removes_competition_context_banner_only() -> None:
    source = _source(LEARNING_PATH)

    assert "CompetitionDemoContextBand" not in source
    assert 'page="path"' not in source
    assert "getCompetitionDemoContext" in source
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
        "timeBudgetMinutes",
        "调整预算与重建",
        "createGenerationJob",
        "openPathTask",
    ):
        assert marker in source


def test_shared_banner_remains_for_showcase_but_not_review_tools() -> None:
    assert CONTEXT_BAND.exists()

    showcase = _source(SHOWCASE)
    review = _source(REVIEW)
    review_tools = _source(REVIEW_TOOLS)
    assert "CompetitionDemoContextBand" in showcase
    assert 'page="showcase"' in showcase
    assert "CompetitionDemoContextBand" not in review
    assert "CompetitionDemoContextBand" not in review_tools
    assert 'page="review"' not in review_tools
