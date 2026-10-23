import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOKENS = ROOT / "frontend/src/styles/tokens.css"
BASE = ROOT / "frontend/src/styles/base.css"
HEADER = ROOT / "frontend/src/components/PageHeader.vue"
SHELL = ROOT / "frontend/src/components/AppShell.vue"
PROFILE = ROOT / "frontend/src/views/ProfileDashboard.vue"
WORKSPACE = ROOT / "frontend/src/views/LearningWorkspace.vue"
VIEWS = ROOT / "frontend/src/views"
COMPONENTS = ROOT / "frontend/src/components"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_heading_tokens_and_shared_header_use_one_sans_heading_system():
    tokens = read(TOKENS)
    header = read(HEADER)
    base = read(BASE)

    for marker in (
        "--font-heading: var(--font-sans)",
        "--line-height-heading: 1.3",
        "--font-size-page-title: 24px",
        "--font-size-page-title-compact: 20px",
        "--space-panel-inline: 24px",
        "--space-row-inline: 16px",
    ):
        assert marker in tokens
    assert "font-family: var(--font-heading)" in header
    assert "padding: 2px 0" in header
    assert "font-size: var(--font-size-page-title-compact)" in header
    assert "font-family: var(--font-heading)" in base


def test_shell_and_target_pages_keep_text_inside_bordered_regions():
    shell = read(SHELL)
    profile = read(PROFILE)
    workspace = read(WORKSPACE)

    for marker in (
        "padding: 6px 24px",
        "padding: 18px 16px",
        "padding: 12px 8px",
        "padding: 10px",
    ):
        assert marker in shell
    for marker in (
        "font-family: var(--font-heading)",
        "padding: 24px var(--space-panel-inline)",
        "padding: 26px var(--space-panel-inline)",
        "padding: var(--space-panel-inline)",
        "padding: 20px 18px",
    ):
        assert marker in profile
    for marker in (
        "font-family: var(--font-heading)",
        "padding: 12px var(--space-1) 24px",
        "padding: 28px 32px 32px",
        "padding: 14px var(--space-row-inline)",
        "padding: 9px 4px 9px 12px",
        "padding: 20px var(--space-row-inline)",
        "padding-inline: var(--space-1)",
    ):
        assert marker in workspace


def test_typography_fix_does_not_reintroduce_display_font_or_negative_spacing():
    combined = "\n".join(read(path) for path in (HEADER, SHELL, PROFILE, WORKSPACE)).lower()

    assert "font-family: var(--font-display)" not in combined
    assert "letter-spacing: -" not in combined
    assert "linear-gradient" not in combined
    assert "radial-gradient" not in combined


def test_all_desktop_views_use_sans_for_ordinary_page_titles():
    ordinary_title_pattern = re.compile(
        r"(?:dashboard-heading|page-header|page-head|path-page__heading|header-copy|"
        r"legacy-onboarding|empty-conversation)[^{]*\{[^}]*font-family:\s*var\(--font-display\)",
        re.DOTALL,
    )
    for path in sorted(VIEWS.glob("*.vue")):
        source = read(path)
        assert not ordinary_title_pattern.search(source), f"ordinary page title uses display font: {path.name}"
        assert not re.search(r"letter-spacing\s*:\s*-", source), f"negative spacing in {path.name}"

    expected_heading_files = (
        "Dashboard.vue",
        "HandoutWorkspace.vue",
        "MarketplaceWorkspace.vue",
        "MindmapWorkspace.vue",
        "Onboarding.vue",
        "ResourceBundleWorkspace.vue",
        "TrainingTaskWorkspace.vue",
        "VideoRecommendationWorkspace.vue",
        "WebDeckWorkspace.vue",
        "LearningPathGraph.vue",
        "Chat.vue",
    )
    for name in expected_heading_files:
        compact = re.sub(r"\s+", "", read(VIEWS / name))
        assert "font-family:var(--font-heading)" in compact, name


def test_global_text_boundaries_cover_controls_modals_states_and_rows_safely():
    tokens = read(TOKENS)
    base = read(BASE)

    for marker in (
        "--space-panel-block: 20px",
        "--space-state-block: 32px",
        "--space-control-inline: 12px",
    ):
        assert marker in tokens
    for marker in (
        "padding-inline: var(--space-control-inline)",
        "padding: 10px var(--space-control-inline)",
        ".ui-modal__body",
        "padding: var(--space-panel-block) var(--space-panel-inline)",
        ".loading-state",
        ".empty-state",
        ".error-state",
        ".profile-radar-empty",
        ".setting-row",
        ".connection-row",
        "padding-inline: var(--space-row-inline)",
        "overflow-wrap: anywhere",
    ):
        assert marker in base

    # The shared inset rules must remain text-container-specific.
    css_without_comments = re.sub(r"/\*.*?\*/", "", base, flags=re.DOTALL)
    for protected_surface in (
        ".app-content .monaco-editor",
        ".app-content canvas",
        ".app-content video",
        ".app-content iframe",
        ".app-content .pdf-page",
    ):
        assert protected_surface not in css_without_comments


def test_global_audit_covers_every_view_and_page_component_source():
    audited = sorted(VIEWS.glob("*.vue")) + sorted(COMPONENTS.glob("*.vue"))
    assert len(audited) >= 100
    for path in audited:
        source = read(path)
        assert not re.search(r"letter-spacing\s*:\s*-", source), path.name
