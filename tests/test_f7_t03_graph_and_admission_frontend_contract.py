from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GRAPH = ROOT / "frontend" / "src" / "views" / "KnowledgeGraphWorkspace.vue"
DISCOVERY = ROOT / "frontend" / "src" / "views" / "KnowledgeDiscoveryWorkspace.vue"
EXPLORER = ROOT / "frontend" / "src" / "components" / "KnowledgeGraphExplorer.vue"
KNOWLEDGE_API = ROOT / "frontend" / "src" / "api" / "knowledge.js"
ROUTER = ROOT / "frontend" / "src" / "router" / "index.js"
PROFILE = ROOT / "frontend" / "src" / "views" / "StudentAnalysis.vue"
CHAT = ROOT / "frontend" / "src" / "views" / "Chat.vue"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_graph_and_discovery_use_dedicated_authenticated_knowledge_routes() -> None:
    source = _source(ROUTER)

    assert "const KnowledgeGraphWorkspace = () => import('../views/KnowledgeGraphWorkspace.vue')" in source
    assert "const KnowledgeDiscoveryWorkspace = () => import('../views/KnowledgeDiscoveryWorkspace.vue')" in source
    assert (
        "path: '/knowledge/graph/:courseId', name: 'KnowledgeGraph', "
        "component: KnowledgeGraphWorkspace, beforeEnter: requireAuth"
    ) in source
    assert (
        "path: '/knowledge/discover', name: 'KnowledgeDiscover', "
        "component: KnowledgeDiscoveryWorkspace, beforeEnter: requireAuth"
    ) in source


def test_course_graph_has_stable_75_25_layout_filters_fallback_and_source_deep_link() -> None:
    source = _source(GRAPH)

    for marker in (
        'data-testid="course-graph-75-25-layout"',
        "grid-template-columns: minmax(0, 3fr) minmax(280px, 1fr)",
        'data-testid="graph-chapter-filter"',
        'data-testid="graph-relation-filter"',
        'data-testid="graph-hierarchy-fallback"',
        'data-testid="course-graph-overview"',
        "章节包含",
        "章节讲授",
        "知识先修",
        "来源支撑",
        "打开来源正文",
        "path: `/knowledge/documents/${encodeURIComponent(selectedNode.value.sourceDocumentId)}`",
        "source_ref_id: selectedNode.value.sourceRefId || undefined",
    ):
        assert marker in source
    assert "sourceStatus === 'ready'" in source
    assert "该节点没有当前可访问的正文来源" in source


def test_relationship_projection_changes_layout_without_changing_graph_facts() -> None:
    workspace = _source(GRAPH)
    explorer = _source(EXPLORER)

    assert "layoutMode = ref('graph')" in workspace
    assert "layoutMode = 'relationship_projection'" in workspace
    assert ":nodes=\"filteredNodes\"" in workspace
    assert ":edges=\"filteredEdges\"" in workspace
    assert "layout: props.fixedLayout ? 'none' : (props.fitDenseGraph ? 'none' : (relationshipProjection.value ? 'circular' : 'force'))" in explorer
    assert "data: chartNodes" in explorer
    assert "edges: props.edges" in explorer
    assert "const chartNodes = props.nodes.map" in explorer
    assert "layoutMode: { type: String, default: 'graph' }" in explorer
    assert "fitDenseGraph: { type: Boolean, default: false }" in explorer
    assert "function denseGraphPositions(nodes)" in explorer
    assert "function relationshipProjectionPositions(nodes, edges)" in explorer
    assert "zoom: props.fixedLayout || props.fitDenseGraph ? 0.92 : 1" in explorer
    assert "const denseSymbolSizes = { course: 68, chapter: 58, knowledge_point: 52, source: 38 }" in explorer
    assert "show: props.fixedLayout || !props.fitDenseGraph || showDenseLabel" in explorer
    assert "position: props.fixedLayout || props.fitDenseGraph ? 'inside' : 'bottom'" in explorer
    assert "color: props.fixedLayout ? '#ffffff'" in explorer
    assert "const chartCategories = props.categories.map" in explorer
    assert "categories: chartCategories.length ? chartCategories : undefined" in explorer
    assert "color: categoryColors[index % categoryColors.length]" in explorer
    assert "fit-dense-graph" in workspace


def test_discovery_preserves_query_on_failure_and_exposes_complete_candidate_evidence() -> None:
    source = _source(DISCOVERY)

    assert "searchError.value = errorMessage(error" in source
    assert "搜索词和已有候选已保留" in source
    assert "query.value = ''" not in source
    assert "router.replace({ query:" not in source
    for marker in (
        'data-testid="discovery-search-input"',
        'data-testid="discovery-search-submit"',
        'data-testid="discovery-format-filter"',
        'data-testid="discovery-license-filter"',
        'data-testid="discovery-review-filter"',
        'data-testid="discovery-list-preview-layout"',
        'data-testid="discovery-source-preview"',
        "原站",
        "作者或机构",
        "资料格式",
        "许可状态",
        "可信等级",
        "审核状态",
        "解析影响",
        "用途说明",
    ):
        assert marker in source
    assert "HTTP(S) 原站地址" in source


def test_candidate_admission_is_license_gated_personal_and_reversible() -> None:
    source = _source(DISCOVERY)
    api = _source(KNOWLEDGE_API)

    assert "new Set(['personal_use_allowed', 'open_permissive'])" in source
    assert ":disabled=\"!canSubmitAdmission" in source
    for marker in (
        "确认准入个人参考",
        "拒绝该候选",
        "撤回个人参考",
        "不进入课程图谱、RAG 或资源生成",
        "admitWebSourceCandidate",
        "rejectWebSourceCandidate",
        "withdrawWebSourceCandidate",
        "authorityBoundaryText",
        "候选资料不属于权威课程，不进入课程图谱、RAG 或资源生成",
    ):
        assert marker in source
    for symbol in (
        "discoverKnowledgeMaterials",
        "saveWebSourceCandidate",
        "listWebSourceCandidates",
        "admitWebSourceCandidate",
        "rejectWebSourceCandidate",
        "withdrawWebSourceCandidate",
    ):
        assert f"function {symbol}" in api


def test_profile_graph_keeps_default_behavior_and_chat_has_no_manifold_entry() -> None:
    profile = _source(PROFILE)
    explorer = _source(EXPLORER)
    chat = _source(CHAT)

    assert "<KnowledgeGraphExplorer" in profile
    assert ':nodes="knowledgeGraphNodes"' in profile
    assert ':edges="knowledgeGraphEdges"' in profile
    assert "layout-mode" not in profile
    assert "show-mastery-in-tooltip" not in profile
    assert "layoutMode: { type: String, default: 'graph' }" in explorer
    assert "showMasteryInTooltip: { type: Boolean, default: true }" in explorer
    assert "ManifoldVisualizer" not in chat
    assert "双曲圆盘" not in chat
    assert "rightPanelActiveTab = ref('canvas')" not in chat


def test_graph_and_discovery_browsing_do_not_write_learning_or_mastery_state() -> None:
    source = _source(GRAPH) + _source(DISCOVERY) + _source(EXPLORER)

    for forbidden in (
        "createLearningEvent",
        "updateMastery",
        "saveMastery",
        "completePathTask",
        "unlockExam",
        "sourceEventIds",
    ):
        assert forbidden not in source


def test_new_workspaces_follow_the_frozen_minimal_visual_contract() -> None:
    source = (_source(GRAPH) + _source(DISCOVERY)).lower()

    for required in (
        "var(--color-page)",
        "var(--color-surface)",
        "var(--color-text)",
        "var(--color-accent)",
    ):
        assert required in source
    for forbidden in (
        "linear-gradient",
        "radial-gradient",
        "backdrop-filter",
        "#10b981",
        "#0ea5e9",
        "#8b5cf6",
        "font-size: 10px",
        "font-size: 11px",
        "font-size: 12px",
        "font-size: 13px",
    ):
        assert forbidden not in source
