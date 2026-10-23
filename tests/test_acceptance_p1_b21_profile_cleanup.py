from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STUDENT_ANALYSIS = ROOT / "frontend" / "src" / "views" / "StudentAnalysis.vue"
PROFILE_DASHBOARD = ROOT / "frontend" / "src" / "views" / "ProfileDashboard.vue"
ROUTER = ROOT / "frontend" / "src" / "router" / "index.js"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_digital_twin_tab_and_img13_emoji_are_removed_without_deleting_profile_workspaces():
    view = source(STUDENT_ANALYSIS)

    for forbidden in (
        "digital-twin",
        "数字孪生画像",
        "🎨",
        "⚖️",
        "🔍",
        "🛠️",
        "💡",
        "🧠",
        "⚠️",
        "⏳",
        "ℹ️",
    ):
        assert forbidden not in view

    for required in (
        "概览",
        "十维分析",
        "薄弱点归因",
        "成因分析",
        "教学建议",
        "编辑画像",
        "更新学情画像",
        "十维画像、趋势、薄弱点归因、成因分析、建议和可编辑偏好均保留。",
        "role=\"tablist\"",
        "aria-label=\"详细画像视图\"",
    ):
        assert required in view


def test_profile_trend_history_and_learning_profile_deep_links_remain_owned_by_existing_surfaces():
    dashboard = source(PROFILE_DASHBOARD)
    router = source(ROUTER)

    for required in (
        'data-testid="profile-trend"',
        "学习趋势",
        "LearningTrendChart",
        "完整画像",
        "'/profile/learning'",
        "'/profile/history'",
    ):
        assert required in dashboard

    for required in (
        "path: '/profile', name: 'ProfileDashboard'",
        "path: '/profile/learning', name: 'StudentAnalysis'",
        "path: '/profile/history', name: 'History'",
        "requireAuth",
    ):
        assert required in router


def test_profile_view_keeps_readable_tab_and_state_markers_after_cleanup():
    view = source(STUDENT_ANALYSIS)

    for required in (
        "v-if=\"loading\"",
        "v-else-if=\"error\"",
        "profile-map-state",
        "profile-continuous-update",
        "@click=\"openEdit\"",
        "@click=\"openProfileUpdate\"",
        "class=\"profile-tabs overflow-x-auto\"",
        "role=\"tab\"",
        "aria-selected=\"activeTab === 'overview'\"",
    ):
        assert required in view
