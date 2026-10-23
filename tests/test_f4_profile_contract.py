from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8-sig")


def test_f4_profile_keeps_legacy_views_below_the_explainable_graph():
    source = _source("frontend/src/views/StudentAnalysis.vue")
    assert 'data-testid="profile-knowledge-map"' in source
    assert 'data-testid="profile-node-evidence"' in source
    assert "grid-template-columns: minmax(0, 74fr) minmax(300px, 26fr)" in source
    assert '<section v-if="!isTeacher" class="profile-map-section"' in source
    assert "KnowledgeGraphExplorer" in source
    assert ":show-details=\"false\"" in source
    assert "普通浏览不会被算作掌握" in source
    assert "activeKnowledgeNode.nextAction" in source

    for tab in ("overview", "digital-twin", "dimensions", "weakness", "causes", "suggestions"):
        assert f"activeTab === '{tab}'" in source
    for protected_capability in (
        "MasteryRadar", "数字孪生画像", "十维分析", "薄弱点归因",
        "成因分析", "教学建议", "openEdit", "一键生成个性化资源",
    ):
        assert protected_capability in source


def test_f4_shared_graph_exposes_local_selection_without_writing_learning_state():
    graph = _source("frontend/src/components/KnowledgeGraphExplorer.vue")
    profile = _source("frontend/src/views/StudentAnalysis.vue")
    summary = _source("app/profile_summary.py")

    assert "defineEmits(['node-select', 'reset'])" in graph
    assert "emit('node-select', selectedNode.value)" in graph
    assert "window.addEventListener('resize', resizeChart)" in graph
    assert "window.removeEventListener('resize', resizeChart)" in graph
    assert "@node-select=\"selectKnowledgeNode\"" in profile
    assert "@reset=\"selectedKnowledgeNode = null\"" in profile
    assert "mastery_eligible" in summary and 'evidence_status != "accepted"' in summary
    assert "f4.profile-knowledge-graph.v1" in summary
    assert "sourceEventIds" in summary
    assert "浏览、搜索、展开和选择节点不改变掌握度" in summary


def test_f4_profile_visual_contract_rejects_cold_ai_styling_and_broken_classes():
    paths = (
        "frontend/src/views/StudentAnalysis.vue",
        "frontend/src/components/KnowledgeGraphExplorer.vue",
        "frontend/src/components/MasteryRadar.vue",
    )
    combined = "\n".join(_source(path) for path in paths)
    template = combined.split("<style", 1)[0].lower()

    assert not re.search(r"(?:bg|text|border|from|to|via)-\[[^\]]+\][a-z0-9]", combined)
    assert not re.search(r"\b(?:green|emerald|teal|cyan|blue|indigo|purple)-", template)
    assert "lineargradient(" not in combined.lower()
    assert "radial-gradient" not in combined.lower()
    assert "bg-gradient" not in template
    assert "🟢" not in combined
    assert ".profile-detail-section :deep(.text-xs) { font-size: 14px" in combined


def test_f4_profile_route_has_one_transition_root_and_distilled_summary():
    profile = _source("frontend/src/views/StudentAnalysis.vue")
    summary = _source("frontend/src/components/ProfileSummaryPanel.vue")

    template = profile.split("<template>", 1)[1].split("</template>", 1)[0].strip()
    assert template.startswith('<div class="profile-view">')
    assert template.endswith("</div>")
    assert 'data-testid="profile-compact-focus"' in summary
    assert "当前学习重点" in summary
    assert "当前薄弱点" in summary
    assert "建议下一步" in summary
    assert "查看画像依据" in summary
    assert "compact-evidence-disclosure" in summary
    assert "compactWeakPoint" in summary
    assert 'data-testid="competition-demo-profile-evidence"' not in profile
    assert "正式演示课程" not in profile
    assert "当前薄弱知识点" not in profile
    assert "已确认误区" not in profile


def test_f4_minimal_palette_uses_semantic_ink_tokens():
    tokens = _source("frontend/src/styles/tokens.css")
    summary = _source("frontend/src/components/ProfileSummaryPanel.vue")
    profile = _source("frontend/src/views/StudentAnalysis.vue")

    for marker in (
        "--color-page: #f5f7f7",
        "--color-text: #06141b",
        "--color-accent: #11212d",
        "--color-text-secondary: #4a5c6a",
        "--color-border-strong: #ccd0cf",
    ):
        assert marker in tokens
    assert not re.search(r"#(?:4b382d|5b4030|6f4e37|73533e|f3ece6)\b", summary, re.I)
    assert "--profile-accent-dark: #11212d" in profile
