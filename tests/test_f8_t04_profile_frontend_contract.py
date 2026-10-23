from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "frontend" / "src" / "views" / "ProfileDashboard.vue"
HISTORY = ROOT / "frontend" / "src" / "views" / "History.vue"
TREND = ROOT / "frontend" / "src" / "components" / "LearningTrendChart.vue"
API = ROOT / "frontend" / "src" / "api" / "m5.js"
APP = ROOT / "frontend" / "src" / "App.vue"
ROUTER = ROOT / "frontend" / "src" / "router" / "index.js"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_profile_uses_figure_29_reading_order_and_honest_fact_sections() -> None:
    view = source(PROFILE)

    markers = (
        'data-testid="profile-dashboard"',
        'class="identity-band"',
        'class="facts-band"',
        'data-testid="profile-heatmap"',
        'data-testid="profile-trend"',
        'data-testid="profile-activity"',
        'data-testid="profile-summary"',
        'data-testid="profile-report"',
    )
    positions = [view.index(marker) for marker in markers]
    assert positions == sorted(positions)

    for required in (
        "今日学习",
        "近 7 天学习",
        "连续学习",
        "近 30 天学习热力图",
        "仅使用已经处理完成的掌握聚合结果",
        "所选范围内还没有学习记录",
        "当前课程还没有足够的画像证据",
        "查看统计口径与来源",
        "本期来源事件",
        "完整画像",
        "查看报告依据",
    ):
        assert required in view
    assert "activity.profile?.fullProfileRoute, '/profile/learning'" in view
    assert "router.push({ path: '/profile/history'" in view


def test_history_is_a_read_only_three_column_personal_center_deep_link() -> None:
    view = source(HISTORY)

    for marker in (
        'data-testid="profile-history"',
        'data-testid="history-filters"',
        'data-testid="history-timeline"',
        'data-testid="history-detail"',
        "grid-template-columns: 220px minmax(360px, 1fr) 300px",
        "筛选只改变当前视图",
        "查看、筛选和展开历史不会改变掌握度、路径或复习安排",
        "来源与上下文",
        "继续后才按真实动作记录新事件",
        "原学习对象已撤回或不支持直接打开",
        "来源事件",
        "上一页",
        "下一页",
    ):
        assert marker in view
    for forbidden in ("Swarm", "认知流形", "FSM", "rollback", "画像回滚"):
        assert forbidden.lower() not in view.lower()
    for forbidden_write in ("createLearningEvent", "updateMastery", "completePathTask", "unlockExam"):
        assert forbidden_write not in view


def test_personal_activity_api_and_profile_route_ownership_are_stable() -> None:
    api = source(API)
    router = source(ROUTER)

    assert "export function getM5PersonalActivity(params = {})" in api
    assert "api.get('/v1/m5/personal-activity', authConfig(params))" in api
    assert "path: '/profile', name: 'ProfileDashboard'" in router
    assert "path: '/profile/history', name: 'History'" in router
    assert "path: '/profile/learning', name: 'StudentAnalysis'" in router
    assert "legacy('/history', 'LegacyHistory', '/profile/history')" in router


def test_student_navigation_remains_exactly_eight_primary_entries() -> None:
    app = source(APP)
    match = re.search(r"const studentNav = \[(.*?)\n\]", app, flags=re.DOTALL)
    assert match
    entries = re.findall(r"\{ path: '([^']+)', label: '([^']+)', icon: \w+ \}", match.group(1))
    assert entries == [
        ("/", "首页"),
        ("/profile", "个人中心"),
        ("/profile/learning", "学习画像"),
        ("/workspace", "学习空间"),
        ("/learn", "智能对话"),
        ("/knowledge", "知识库"),
        ("/marketplace", "学习市场"),
        ("/settings", "设置"),
    ]
    assert "/profile/history" not in {path for path, _ in entries}


def test_profile_surfaces_keep_the_frozen_light_visual_contract() -> None:
    combined = "\n".join(source(path) for path in (PROFILE, HISTORY, TREND))
    lowered = combined.lower()

    for required in (
        "var(--color-surface)",
        "var(--color-text)",
        "var(--color-accent)",
        "var(--color-border)",
        "var(--font-sans)",
        "border-radius: var(--radius-panel)",
        "border-radius: var(--radius-control)",
    ):
        assert required in combined

    numeric_font_sizes = [int(value) for value in re.findall(r"font-size:\s*(\d+)px", lowered)]
    assert numeric_font_sizes
    assert min(numeric_font_sizes) >= 14

    numeric_radii = [int(value) for value in re.findall(r"border-radius:\s*(\d+)px", lowered)]
    assert numeric_radii
    assert max(numeric_radii) <= 8

    for forbidden in (
        "linear-gradient",
        "radial-gradient",
        "backdrop-filter",
        "#10b981",
        "#22c55e",
        "#16a34a",
        "#15803d",
        "#0ea5e9",
        "#3b82f6",
        "#8b5cf6",
        "#a855f7",
        "#92400e",
        "#b45309",
        "#a16207",
        "green-",
        "emerald-",
        "lime-",
        "orange-",
        "amber-",
        "purple-",
        "indigo-",
    ):
        assert forbidden not in lowered


def test_trend_has_real_empty_state_and_no_decorative_area_fill() -> None:
    chart = source(TREND)

    assert "v-if=\"points.length\"" in chart
    assert "暂无可用于趋势计算的已处理学习证据" in chart
    assert "#253745" in chart
    assert "fontSize: 14" in chart
    assert "areaStyle" not in chart
    assert "gradient" not in chart.lower()
