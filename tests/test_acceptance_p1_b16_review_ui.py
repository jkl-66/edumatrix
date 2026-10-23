from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "frontend" / "src" / "components" / "ReviewScheduleBoard.vue"
REVIEW = ROOT / "frontend" / "src" / "views" / "Review.vue"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_review_cards_humanize_internal_schedule_labels() -> None:
    board = source(BOARD)
    review = source(REVIEW)

    assert "function humanTaskType(task)" in board
    assert "humanTaskType(task)" in board
    assert '<div><dt>安排</dt><dd>{{ humanTaskType(task) }}</dd></div>' in board
    assert "{{ task.type }}" not in board
    assert "task.priority" not in board
    assert "SM-2" not in board
    assert "legacy review priority" not in board.lower()
    assert "legacy priority" not in board.lower()
    assert "<ReviewScheduleBoard" in review


def test_review_cards_keep_user_decision_facts_and_actions() -> None:
    board = source(BOARD)

    for marker in (
        "{{ task.knowledge_point_title }}",
        "{{ task.reason }}",
        "<dt>到期</dt>",
        "formatTime(task.due_at)",
        "<dt>方式</dt>",
        "{{ task.method }}",
        "<dt>完成</dt>",
        "{{ task.completion_rule }}",
        "task.action?.enabled",
        "task.action.label",
        "data-testid=\"review-agenda-list\"",
    ):
        assert marker in board


def test_review_card_display_does_not_add_a_second_data_path() -> None:
    board = source(BOARD)

    for forbidden in ("fetch('/v1/review-schedule", "axios.create", "DBReviewPlan", "mastery"):
        assert forbidden not in board
