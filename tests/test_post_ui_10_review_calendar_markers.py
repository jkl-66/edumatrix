from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "frontend/src/components/ReviewScheduleBoard.vue"


def _source() -> str:
    return BOARD.read_text(encoding="utf-8")


def test_calendar_cells_use_date_and_status_marker_without_repeated_text() -> None:
    source = _source()
    cell_start = source.index('class="review-day"')
    cell_end = source.index("</button>", cell_start)
    cell = source[cell_start:cell_end]

    assert 'class="review-day__number"' in cell
    assert 'class="review-day__marker"' in cell
    assert 'v-if="dayMarkerState(day)"' in cell
    assert "review-day__status" not in cell
    assert "review-day__empty" not in cell
    assert "dayStateLabels" not in source
    assert "<strong" not in cell


def test_calendar_marker_states_match_the_requested_colors() -> None:
    source = _source()

    for marker in (
        "if (day.state === 'today') return 'today'",
        "if (day.state === 'overdue') return 'overdue'",
        "if (day.state === 'future' && day.counts?.total) return 'future'",
        ".review-day__marker--today { background: #2f9e64; }",
        ".review-day__marker--overdue { background: var(--color-danger); }",
        ".review-day__marker--future { background: #466f91; }",
    ):
        assert marker in source

    assert "legend-dot--completed" not in source


def test_calendar_interaction_and_accessible_status_details_remain() -> None:
    source = _source()

    for marker in (
        ':aria-label="`${formatDate(day.date, { month: \'long\', day: \'numeric\' })}，${daySummary(day)}`"',
        ':aria-pressed="day.date === selectedDate"',
        '@click="selectDate(day)"',
        'data-testid="review-agenda-list"',
        "selectedTasks",
        "taskStatus(task)",
    ):
        assert marker in source

    selected_start = source.index(".review-day.is-selected")
    selected_end = source.index(".review-day.is-outside", selected_start)
    selected_rule = source[selected_start:selected_end]
    assert "background: var(--color-surface)" in selected_rule
    assert "box-shadow: inset 0 0 0 2px var(--color-accent)" in selected_rule
    assert "background: var(--color-accent)" not in selected_rule
