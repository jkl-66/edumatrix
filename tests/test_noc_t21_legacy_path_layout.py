from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_legacy_path_layout_is_adapted_to_current_canonical_graph_inputs():
    explorer = (ROOT / "frontend/src/components/KnowledgeGraphExplorer.vue").read_text(encoding="utf-8")
    workspace = (ROOT / "frontend/src/views/KnowledgeGraphWorkspace.vue").read_text(encoding="utf-8")
    profile = (ROOT / "frontend/src/views/StudentAnalysis.vue").read_text(encoding="utf-8")

    for marker in (
        "legacyPathLayout: { type: Boolean, default: false }",
        "function legacyPathLayoutModel(nodes, edges)",
        "const focusCandidates = nodes.filter((node) => node.nodeType === 'knowledge_point')",
        "const directIds = new Set((groups.get(1) || []).map((node) => String(node.id)))",
        "const ringGap = Math.max(300",
        "const minimumDistance = leftRadius + rightRadius + 28",
        "const usesLegacyPathLayout = props.legacyPathLayout && nodes.length <= 40",
        "layout: usesDynamicLayout || props.fixedLayout || props.fitDenseGraph ? 'none'",
        "symbol: 'circle'",
    ):
        assert marker in explorer

    assert "legacy-path-layout" in workspace
    assert "legacy-path-layout" in profile
    # The adapter must not carry the historical demo concepts into canonical data.
    assert "cross_domain_micro_graph" not in explorer
    assert "semantic_similarity" not in explorer

