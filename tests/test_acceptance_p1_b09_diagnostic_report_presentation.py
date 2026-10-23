from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_VIEW = ROOT / "frontend" / "src" / "components" / "DiagnosticAssessmentSession.vue"


def test_diagnostic_report_prioritizes_conclusion_actions_and_on_demand_evidence():
    source = REPORT_VIEW.read_text(encoding="utf-8")

    for marker in (
        'data-testid="diagnostic-submitted"',
        'data-testid="report-next-step"',
        'data-testid="report-knowledge-progress"',
        'data-testid="report-knowledge-toggle"',
        'data-testid="report-evidence-drawer"',
        'data-testid="report-evidence-toggle"',
        "先看结论",
        "下一步先做什么",
        "薄弱环节",
        "默认收起，按需展开",
        "pathError",
        "重新生成报告",
    ):
        assert marker in source

    assert "showEvidence = !showEvidence" in source
    assert "showKnowledgeDetails = !showKnowledgeDetails" in source
    assert "openEvidenceForKnowledgePoint" in source
    assert "reasoning_content" not in source
    assert "api_key" not in source


def test_diagnostic_report_layout_keeps_desktop_density_and_small_viewport_reflow():
    source = REPORT_VIEW.read_text(encoding="utf-8")

    assert ".report-action-grid" in source
    assert ".report-section-toggle-row" in source
    assert "@media (max-width: 1180px)" in source
    assert "@media (max-width: 760px)" in source
    assert ".text-button" in source
    assert "font-size: 14px" in source
