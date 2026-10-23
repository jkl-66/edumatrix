from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_app_shell_uses_shared_content_side_inset():
    source = (ROOT / "frontend" / "src" / "components" / "AppShell.vue").read_text(encoding="utf-8")
    marker = ".app-content__page"
    start = source.index(marker)
    block = source[start:source.index("}", start) + 1]
    assert "box-sizing: border-box" in block
    assert "padding-inline: var(--space-panel-inline)" in block


def test_dashboard_keeps_top_spacing_token():
    source = (ROOT / "frontend" / "src" / "views" / "Dashboard.vue").read_text(encoding="utf-8")
    start = source.index(".dashboard-page {")
    block = source[start:source.index("}", start) + 1]
    assert "padding-top: var(--space-6)" in block
