from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]
PAGE = ROOT / "frontend" / "src" / "views" / "AdvancedCapabilities.vue"
ROUTER = ROOT / "frontend" / "src" / "router" / "index.js"
APP = ROOT / "frontend" / "src" / "App.vue"


def test_advanced_capability_directory_covers_required_domains_and_boundaries():
    source = PAGE.read_text(encoding="utf-8")
    for heading in ("企业治理", "媒体创作", "生态市场", "本地集成", "技术运营"):
        assert heading in source
    for required in ("认证与复训", "模型运营", "领域插件", "视频制作", "公共学习市场", "本地 SSO"):
        assert required in source
    for boundary in ("冻结合成", "演示角色", "不代表外部专家认证", "不连接真实企业系统", "不是供应商账单"):
        assert boundary in source


def test_advanced_capability_routes_exist_and_primary_navigation_stays_small():
    page = PAGE.read_text(encoding="utf-8")
    router = ROUTER.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")
    assert "path: '/advanced-capabilities'" in router
    assert "roles: ['teacher', 'admin', 'assistant']" in router
    assert app.count("path: '/advanced-capabilities'") == 2
    for path in (
        "/enterprise-training", "/certification-lifecycle", "/video-studio",
        "/marketplace", "/plugins", "/integration-sandbox", "/local-sso",
        "/model-operations", "/content-review", "/internal/objects",
    ):
        assert f"path: '{path}'" in page
        assert f"path: '{path}'" in router


def test_integration_entries_are_admin_only_in_directory():
    source = PAGE.read_text(encoding="utf-8")
    for title in ("集成沙箱", "本地 SSO", "HR 主数据", "LMS 同步", "集成对账", "故障演练", "本地适配器"):
        line = next(line for line in source.splitlines() if f"title: '{title}'" in line)
        assert "roles: ['admin']" in line
