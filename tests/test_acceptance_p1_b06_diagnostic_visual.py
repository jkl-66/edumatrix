from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "frontend" / "src" / "components" / "DiagnosticAssessmentSession.vue"
TOKENS = ROOT / "frontend" / "src" / "styles" / "tokens.css"


def test_diagnostic_visuals_use_global_tokens_and_no_brown_theme():
    component = COMPONENT.read_text(encoding="utf-8")
    tokens = TOKENS.read_text(encoding="utf-8")

    for color in ("#3b3029", "#211c18", "#211f1d", "#332d29", "#403a35", "#bdb4ad"):
        assert color not in component.lower()
    assert "--radius-card: 14px;" in tokens
    assert "border-radius: var(--radius-card)" in component
    assert ".report-hero" in component and "background: var(--color-surface)" in component
    assert ".report-main" in component and "border-radius: var(--radius-card)" in component
    assert ".difficulty-panel, .path-panel" in component
    assert "background: var(--color-accent)" in component


def test_diagnostic_visual_state_contract_remains_present():
    component = COMPONENT.read_text(encoding="utf-8")

    for marker in (
        "diagnostic-session-loading",
        "session-failure",
        "save-failure",
        "diagnostic-report-loading",
        "diagnostic-report-error",
        "report-workspace",
        "report-main",
        "difficulty-panel",
        "path-panel",
        "report-boundary",
    ):
        assert marker in component

    # Visual-only batch must not replace the functional report/session actions.
    for action in (
        "saveDiagnosticResponse",
        "submitDiagnosticSession",
        "createDiagnosticReport",
        "generateDiagnosticReportPath",
        "confirmDiagnosticReportPath",
        "toggleEvidence",
    ):
        assert action in component


def test_diagnostic_visuals_keep_readable_type_and_responsive_breakpoint():
    component = COMPONENT.read_text(encoding="utf-8")
    assert "font-size: 14px" in component
    assert "@media (max-width: 1180px)" in component
    assert ".report-side { position: static; }" in component
