from __future__ import annotations

from pathlib import Path

from app.knowledge_graph import _analyze_graph_structure


def _graph(point_count: int, *, connect: bool = False):
    nodes = [
        {"id": "course:c", "name": "课程", "nodeType": "course"},
        {"id": "chapter:a", "name": "主题 A", "nodeType": "chapter"},
        {"id": "chapter:b", "name": "主题 B", "nodeType": "chapter"},
    ]
    edges = []
    for index in range(point_count):
        chapter = "chapter:a" if index < max(point_count // 2, 1) else "chapter:b"
        node_id = f"knowledge:{index}"
        nodes.append({
            "id": node_id,
            "name": f"知识点 {index}",
            "nodeType": "knowledge_point",
            "chapterId": chapter,
            "masteryScore": 0.4 if index == 0 else None,
            "sourceStatus": "ready",
        })
        if index in {0, max(point_count // 2, 1)}:
            edges.append({"source": "course:c", "target": chapter, "relationType": "contains"})
        edges.append({"source": chapter, "target": node_id, "relationType": "teaches"})
        if connect and index:
            edges.append({
                "id": f"prerequisite:{index - 1}:{index}",
                "source": f"knowledge:{index - 1}",
                "target": node_id,
                "relationType": "prerequisite",
                "label": "先修",
            })
    return nodes, edges


def test_topic_cluster_count_follows_course_data_not_fixed_four() -> None:
    nodes, edges = _graph(6, connect=False)
    analysis = _analyze_graph_structure(nodes, edges)

    assert analysis["densityTier"] == "20_or_less"
    assert len(analysis["topicClusters"]) == 2
    assert analysis["layoutDecision"]["clusterCount"] == 2
    assert analysis["layoutDecision"]["strategy"] == "dynamic_cluster"


def test_connected_prerequisite_structure_selects_hierarchical_layout() -> None:
    nodes, edges = _graph(8, connect=True)
    analysis = _analyze_graph_structure(nodes, edges)

    assert len(analysis["topicClusters"]) == 1
    assert analysis["layoutDecision"]["strategy"] == "hierarchical"
    assert analysis["nodeMetrics"]["knowledge:0"]["degree"] >= 1
    assert analysis["nodeMetrics"]["knowledge:0"]["isCurrentFocus"] is True


def test_high_density_graph_is_local_focus_and_exposes_constraints() -> None:
    nodes, edges = _graph(81, connect=True)
    analysis = _analyze_graph_structure(nodes, edges)

    assert analysis["densityTier"] == "over_80"
    assert analysis["layoutDecision"]["strategy"] == "local_focus"
    assert "节点与标签不得重叠" in analysis["layoutDecision"]["constraints"]
    assert set(analysis["layoutDecision"]["supports"]) >= {"search", "focus", "collapse", "expand"}


def test_density_matrix_keeps_strategy_data_driven_at_20_40_and_80_points() -> None:
    small_nodes, small_edges = _graph(20, connect=False)
    medium_nodes, medium_edges = _graph(40, connect=True)
    large_nodes, large_edges = _graph(80, connect=True)

    small = _analyze_graph_structure(small_nodes, small_edges)
    medium = _analyze_graph_structure(medium_nodes, medium_edges)
    large = _analyze_graph_structure(large_nodes, large_edges)

    assert small["densityTier"] == "20_or_less"
    assert medium["densityTier"] == "21_to_40"
    assert large["densityTier"] == "41_to_80"
    assert small["layoutDecision"]["strategy"] != large["layoutDecision"]["strategy"]


def test_b29_sources_and_renderer_keep_dynamic_non_mermaid_boundary() -> None:
    backend = Path("app/knowledge_graph.py").read_text(encoding="utf-8")
    workspace = Path("frontend/src/views/KnowledgeGraphWorkspace.vue").read_text(encoding="utf-8")
    explorer = Path("frontend/src/components/KnowledgeGraphExplorer.vue").read_text(encoding="utf-8")

    assert '"layoutDecision"' in backend
    assert '"availability"' in backend
    assert "topicClusters" in backend
    assert "sourceRefId" in workspace
    assert "KnowledgeGraphExplorer" in workspace
    assert "layout-decision" in workspace
    assert "dataDrivenPositions" in explorer
    assert "topicClusters" in explorer
    assert "mermaid" not in explorer.lower()
