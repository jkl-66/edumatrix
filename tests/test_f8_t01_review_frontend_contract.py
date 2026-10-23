from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "frontend" / "src" / "components" / "ReviewScheduleBoard.vue"
REVIEW = ROOT / "frontend" / "src" / "views" / "Review.vue"
CALENDAR = ROOT / "frontend" / "src" / "views" / "RevisionCalendar.vue"
TOOLS = ROOT / "frontend" / "src" / "components" / "ReviewToolsPanel.vue"
HISTORY = ROOT / "frontend" / "src" / "components" / "ReviewHistoryPanel.vue"
ROUTER = ROOT / "frontend" / "src" / "router" / "index.js"
API = ROOT / "frontend" / "src" / "api" / "path.js"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_real_calendar_and_selected_day_agenda_are_the_primary_surface() -> None:
    board = source(BOARD)
    for marker in (
        'data-testid="review-schedule-board"',
        'data-testid="review-calendar-grid"',
        'data-testid="review-agenda-list"',
        'data-testid="review-agenda-empty"',
        "schedule.days",
        ':data-date="day.date"',
        ':data-task-id="task.id"',
        "selectedTasks",
        "changeMonth(-1)",
        "changeMonth(1)",
        "returnToday",
        "changeCourse",
        "route.query.review_course || route.query.course_id",
        "query.review_course = 'unclassified'",
        "Asia/Shanghai",
    ):
        assert marker in board
    assert "grid-template-columns: minmax(0, 1.38fr) minmax(380px, 1fr)" in board
    assert "delete query.course_id" in board
    for state in ("今日", "逾期", "已完成", "未来安排", "无安排"):
        assert state in board


def test_task_actions_use_real_completion_retest_resource_and_exam_contracts() -> None:
    board = source(BOARD)
    api = source(API)
    for action in (
        "completeReviewScheduleTask",
        "getM5RetestTask",
        "submitM5Retest",
        "createReviewResourceJob",
        "executeGenerationJob",
        "retryFailedAction",
        "failedAction",
        "routeActionNotice(route.query.review_notice)",
        "return router.replace({ query }).catch(() => {})",
        "review_notice: noticeCode",
        "review_notice: 'retest-completed'",
        "loadSchedule({ keepNotice: Boolean(actionNotice.value) })",
        "openResources",
        "openChat",
        "openExam",
    ):
        assert action in board
    assert "await syncQuery({ review_task: null, retest_id: null, review_notice: noticeCode })" in board
    assert "await syncQuery({ review_task: null, retest_id: null, review_notice: 'retest-completed' })" in board
    assert "await loadSchedule({ keepNotice: true })" not in board
    start_task = board[board.index("async function startTask"):board.index("function closeTask")]
    assert "if (sync) {\n    await syncQuery(" in start_task
    assert start_task.index("await syncQuery(") < start_task.index("activeTaskId.value = task.id")
    assert "task.exam_gate?.unlocked" in board
    assert "复习页不会增加或绕过任何解锁条件" in board
    assert "切换月份、课程或日期只改变当前视图，不会写入学习证据" in board
    assert "/v1/review-schedule" in api


def test_both_routes_share_the_calendar_and_integrated_review_tools() -> None:
    review = source(REVIEW)
    calendar = source(CALENDAR)
    tools = source(TOOLS)
    history = source(HISTORY)
    router = source(ROUTER)

    for view in (review, calendar):
        assert "<ReviewScheduleBoard" in view
        assert "<template #tools>" in view
        assert "<ReviewToolsPanel" in view
    assert "legacy-review-tools" not in review
    assert "calendar-legacy-tools" not in calendar
    for marker in ("reviewFlashcard", "getM5RetestTask", "submitM5Retest", "exportM5ReviewDiagnosis"):
        assert marker in tools
    assert "deleteReviewPlan" in tools
    for marker in ("checkinReview", "getCheckinHistory", "getCheckinStreak", "initChart"):
        assert marker in history
    for path in (
        "/workspace/review",
        "/workspace/review/calendar",
        "/workspace/review/wrong-questions",
        "/workspace/assessment/entry",
        "/workspace/assessment/exams",
        "/workspace/resources",
    ):
        assert f"path: '{path}'" in router
    assert "name: 'ReviewCalendar'" in router


def test_frozen_light_visual_contract_and_accessible_text_floor() -> None:
    combined = "\n".join(source(path).lower() for path in (BOARD, REVIEW, CALENDAR, TOOLS, HISTORY))
    for forbidden in (
        "linear-gradient",
        "radial-gradient",
        "backdrop-filter",
        "#10b981",
        "#0ea5e9",
        "#8b5cf6",
        "font-size: 10px",
        "font-size: 11px",
        "font-size: 12px",
        "font-size: 13px",
    ):
        assert forbidden not in combined
    assert "var(--font-sans)" in combined
    assert "aria-label=\"真实复习月历\"" in combined
    assert "aria-pressed" in combined
    assert "fieldset" in combined
