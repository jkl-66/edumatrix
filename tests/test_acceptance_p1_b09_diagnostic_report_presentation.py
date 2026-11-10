from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_VIEW = ROOT / "frontend" / "src" / "components" / "DiagnosticAssessmentSession.vue"


def test_diagnostic_report_prioritizes_conclusion_actions_and_on_demand_evidence():
    source = REPORT_VIEW.read_text(encoding="utf-8")

    for marker in (
        'data-testid="diagnostic-submitted"',
        'data-testid="report-knowledge-progress"',
        'data-testid="report-knowledge-toggle"',
        'data-testid="report-evidence-drawer"',
        'data-testid="report-evidence-toggle"',
        "本次表现",
        "当前强项",
        "需要补齐",
        "逐题回顾",
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

    assert ".report-columns" in source
    assert ".report-section-toggle-row" in source
    assert "@media (max-width: 1180px)" in source
    assert "@media (max-width: 760px)" in source
    assert ".text-button" in source
    assert "font-size: 14px" in source
