from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "frontend/src/components/ReviewScheduleBoard.vue"
TOOLS = ROOT / "frontend/src/components/ReviewToolsPanel.vue"
HISTORY = ROOT / "frontend/src/components/ReviewHistoryPanel.vue"
REVIEW = ROOT / "frontend/src/views/Review.vue"
CALENDAR = ROOT / "frontend/src/views/RevisionCalendar.vue"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_tools_are_a_real_second_view_inside_the_shared_review_board() -> None:
    board = source(BOARD)
    review = source(REVIEW)
    calendar = source(CALENDAR)

    for marker in (
        "const activeView = ref('calendar')",
        "function setView(view)",
        "emit('view-change', view)",
        ':aria-pressed="activeView === \'calendar\'"',
        ':aria-pressed="activeView === \'tools\'"',
        '<slot name="tools">',
        'data-testid="review-tools-surface"',
    ):
        assert marker in board
    for forbidden in ("advancedToolsId", "openAdvancedTools", "scrollIntoView"):
        assert forbidden not in board
    for view in (review, calendar):
        assert "<template #tools>" in view
        assert "<ReviewToolsPanel" in view
    assert "legacy-review-tools" not in review
    assert "calendar-legacy-tools" not in calendar


def test_tools_use_four_progressive_views_without_internal_engineering_noise() -> None:
    tools = source(TOOLS)

    for label in ("待处理", "闪卡", "计划", "记录"):
        assert f"label: '{label}'" in tools
    for marker in (
        "getM5ReviewQueue",
        "getAllFlashcards",
        "getM5RetestTask",
        "submitM5Retest",
        "reviewFlashcard",
        "createReviewPlan",
        "deleteReviewPlan",
        "exportM5ReviewDiagnosis",
        "<AnkiFlashcard",
        "<ReviewHistoryPanel",
        "困难",
        "一般",
        "简单",
    ):
        assert marker in tools
    for forbidden in (
        "CompetitionDemoContextBand",
        "legacy-review-tools",
        "SM-2 复习计划",
        "E-Factor",
        "easinessText",
        "version_number",
        "content_hash",
        "llm_backend",
        "Visualizer",
        "agent_trace",
        "morphTrace",
    ):
        assert forbidden not in tools


def test_record_panel_preserves_real_checkin_and_history_without_duplicate_plan_lists() -> None:
    history = source(HISTORY)

    for marker in (
        "checkinReview",
        "getCheckinStreak",
        "getCheckinHistory",
        "复习时长趋势",
        "详细记录",
        "historyData",
        "initChart",
        "时长已保存。该记录不会直接改变掌握度。",
        'min="5" max="120"',
    ):
        assert marker in history
    for forbidden in ("deleteReviewPlan", "urgentReviews", "upcomingReviews", "legacy-plan-list"):
        assert forbidden not in history


def test_visible_text_floor_and_calendar_marker_contract_remain() -> None:
    combined = "\n".join(source(path).lower() for path in (BOARD, TOOLS, HISTORY))
    font_sizes = [int(value) for value in re.findall(r"font-size:\s*(\d+)px", combined)]
    assert font_sizes and min(font_sizes) >= 14
    for forbidden in (
        "font-size: 10px",
        "font-size: 11px",
        "font-size: 12px",
        "font-size: 13px",
        "linear-gradient",
        "radial-gradient",
        "backdrop-filter",
    ):
        assert forbidden not in combined
    for marker in (
        ".review-day__marker--today { background: #4f765e; }",
        ".review-day__marker--overdue { background: var(--color-danger); }",
        ".review-day__marker--future { background: #466f91; }",
        'data-testid="review-agenda-list"',
    ):
        assert marker in source(BOARD)
