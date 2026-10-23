from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPLORER = ROOT / "frontend" / "src" / "components" / "KnowledgeGraphExplorer.vue"
PROFILE = ROOT / "frontend" / "src" / "views" / "StudentAnalysis.vue"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_profile_graph_uses_opt_in_fixed_layout_without_changing_default_graph_behavior() -> None:
    explorer = _source(EXPLORER)
    profile = _source(PROFILE)

    required_explorer_markers = (
        "fixedLayout: { type: Boolean, default: false }",
        "function fixedProfilePositions(nodes, edges)",
        "function fixedProfileAnchor(nodes, edges)",
        "function profileGraphLayout(nodes, edges)",
        "function profileEdgeData(edges, positions, groups = new Map())",
        "role = 'upstream'",
        "role = 'downstream'",
        "role = 'independent'",
        "type: longEdge ? 'dashed' : 'solid'",
        "layout: props.fixedLayout ? 'none'",
        "roam: !props.fixedLayout",
        "draggable: !props.fixedLayout",
        "animationDuration: props.fixedLayout ? 0 : 550",
        "animationDurationUpdate: props.fixedLayout ? 0 : 550",
        "animation: !props.fixedLayout",
        "if (!props.fixedLayout) chartInstance?.dispatchAction({ type: 'restore' })",
    )
    for marker in required_explorer_markers:
        assert marker in explorer

    assert "layout: props.fixedLayout ? 'none' : (props.fitDenseGraph ? 'none' : (relationshipProjection.value ? 'circular' : 'force'))" in explorer
    assert "roam: true" not in explorer
    assert "draggable: true" not in explorer
    assert ':fixed-layout="true"' in profile
    assert 'chart-subtitle=' in profile
    assert '@node-select="selectKnowledgeNode"' in profile


def test_fixed_profile_positions_are_not_derived_from_selection_or_search_state() -> None:
    explorer = _source(EXPLORER)
    fixed_function = explorer.split("function fixedProfilePositions", 1)[1].split("function buildOption", 1)[0]
    build_function = explorer.split("function buildOption", 1)[1].split("function relatedNodeIds", 1)[0]

    assert "selectedNode" not in fixed_function
    assert "searchQuery" not in fixed_function
    assert "highlightedNodes" not in fixed_function
    assert "profileGraphLayout(props.nodes, props.edges)" in build_function
    assert "...(densePositions.get(props.fixedLayout ? String(node.id) : node.id) || {})" in build_function


def test_profile_layout_has_separate_visual_lanes_for_main_branches_and_independent_nodes() -> None:
    explorer = _source(EXPLORER)
    layout_function = explorer.split("function profileGraphLayout", 1)[1].split("function profileGraphPositions", 1)[0]

    assert "const neighbors = new Map(nodes.map((node) => [String(node.id), new Set()]))" in layout_function
    assert "function neighborY(node)" in layout_function
    assert "function centeredLanes(count, rowGap = 144)" in layout_function
    assert "placeLayer('upstream', 1, -250)" in layout_function
    assert "placeLayer('upstream', 2, -500)" in layout_function
    assert "placeLayer('downstream', 1, 250)" in layout_function
    assert "placeLayer('downstream', 2, 500)" in layout_function
    assert "positions.set(String(node.id), { x: [-420, -210, 0, 210, 420][column], y: 360 + row * 144 })" in layout_function


def test_profile_edges_deemphasize_long_cross_group_relationships_without_removing_data() -> None:
    explorer = _source(EXPLORER)
    edge_function = explorer.split("function profileEdgeData", 1)[1].split("function compactNodeLabel", 1)[0]

    assert "const crossGroup = sourceGroup && targetGroup && sourceGroup.role !== targetGroup.role" in edge_function
    assert "const longEdge = horizontalDistance >= 450" in edge_function
    assert "color: longEdge ? '#c8beb4' : '#a99a8c'" in edge_function
    assert "opacity: longEdge ? 0.42 : 0.68" in edge_function
    assert "const stableBias = ((String(edge.id || `${edge.source}-${edge.target}-${index}`).length % 3) - 1) * 0.025" in edge_function
    assert "const sameColumn = horizontalDistance < 40 && Math.abs(verticalDelta) > 40" in edge_function
    assert "(verticalDelta > 0 ? 1 : -1) * (0.5 + stableBias)" in edge_function
    assert "return edges.map((edge, index) =>" in edge_function


def test_knowledge_graph_independent_views_keep_their_existing_interaction_contract() -> None:
    explorer = _source(EXPLORER)

    assert "layoutMode: { type: String, default: 'graph' }" in explorer
    assert "fitDenseGraph: { type: Boolean, default: false }" in explorer
    assert "relationshipProjectionPositions(nodes, edges)" in explorer
    assert "roam: !props.fixedLayout" in explorer
    assert "draggable: !props.fixedLayout" in explorer
