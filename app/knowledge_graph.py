"""Canonical course graph projection for the F7 knowledge workspace."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.authorization import require_course_access
from app.database import (
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
    DBKnowledgePoint,
    DBProfileSnapshot,
    DBSourceDocument,
    DBSourceRef,
    DBUser,
)


def build_course_graph(session: Any, current_user: DBUser, course_id: str) -> dict[str, Any]:
    from course_catalog import course_is_selectable
    course = session.get(DBCourse, course_id)
    if course is None or not course_is_selectable(session, course):
        raise HTTPException(status_code=404, detail="课程不存在或尚未发布")
    require_course_access(
        session,
        current_user,
        course_id=course.id,
        action="read",
        visibility=course.visibility,
    )

    chapters = (
        session.query(DBChapter)
        .filter_by(course_id=course.id)
        .order_by(DBChapter.position, DBChapter.id)
        .all()
    )
    chapter_ids = [chapter.id for chapter in chapters]
    relations = (
        session.query(DBChapterKnowledgePoint)
        .filter(DBChapterKnowledgePoint.chapter_id.in_(chapter_ids))
        .order_by(DBChapterKnowledgePoint.chapter_id, DBChapterKnowledgePoint.knowledge_point_id)
        .all()
        if chapter_ids
        else []
    )
    point_ids = sorted({relation.knowledge_point_id for relation in relations})
    points = (
        session.query(DBKnowledgePoint)
        .filter(DBKnowledgePoint.id.in_(point_ids), DBKnowledgePoint.status == "active")
        .order_by(DBKnowledgePoint.code, DBKnowledgePoint.id)
        .all()
        if point_ids
        else []
    )
    source_ids = sorted({chapter.source_document_id for chapter in chapters})
    sources = (
        session.query(DBSourceDocument)
        .filter(DBSourceDocument.id.in_(source_ids))
        .order_by(DBSourceDocument.filename, DBSourceDocument.id)
        .all()
        if source_ids
        else []
    )
    refs = (
        session.query(DBSourceRef)
        .filter(DBSourceRef.source_document_id.in_(source_ids))
        .order_by(DBSourceRef.created_at.desc(), DBSourceRef.id)
        .all()
        if source_ids
        else []
    )

    diagnostic_snapshot = None
    for candidate in session.query(DBProfileSnapshot).filter_by(
        owner_public_id=current_user.public_id,
    ).order_by(DBProfileSnapshot.created_at.desc(), DBProfileSnapshot.id.desc()).all():
        snapshot = dict(candidate.snapshot or {})
        if snapshot.get("kind") == "diagnostic_evidence_snapshot" and snapshot.get("course_id") == course.id:
            diagnostic_snapshot = candidate
            break
    mastery_by_point = dict((diagnostic_snapshot.snapshot or {}).get("mastery_by_knowledge_point") or {}) if diagnostic_snapshot else {}

    point_by_id = {point.id: point for point in points}
    source_by_id = {source.id: source for source in sources}
    ref_by_chapter: dict[str, DBSourceRef] = {}
    for source_ref in refs:
        if source_ref.chapter_id and source_ref.chapter_id not in ref_by_chapter:
            ref_by_chapter[source_ref.chapter_id] = source_ref
    relations_by_chapter: dict[str, list[DBKnowledgePoint]] = {}
    chapters_by_point: dict[str, list[DBChapter]] = {}
    chapter_by_id = {chapter.id: chapter for chapter in chapters}
    for relation in relations:
        chapter = chapter_by_id.get(relation.chapter_id)
        point = point_by_id.get(relation.knowledge_point_id)
        if chapter is None or point is None:
            continue
        relations_by_chapter.setdefault(chapter.id, []).append(point)
        chapters_by_point.setdefault(point.id, []).append(chapter)

    nodes: list[dict[str, Any]] = [{
        "id": f"course:{course.id}",
        "name": course.title,
        "nodeType": "course",
        "category": 0,
        "categoryName": "课程",
        "summary": course.description or "课程知识结构",
        "courseId": course.id,
        "sourceStatus": "course_scope",
    }]
    edges: list[dict[str, Any]] = []

    for chapter in chapters:
        source = source_by_id.get(chapter.source_document_id)
        source_ref = ref_by_chapter.get(chapter.id)
        nodes.append({
            "id": f"chapter:{chapter.id}",
            "name": chapter.title,
            "nodeType": "chapter",
            "category": 1,
            "categoryName": "章节",
            "summary": f"第 {chapter.position} 章",
            "courseId": course.id,
            "chapterId": chapter.id,
            "sourceDocumentId": source.id if source else "",
            "sourceRefId": source_ref.id if source_ref else "",
            "locationLabel": source_ref.location_label if source_ref else "",
            "sourceStatus": source.processing_status if source else "missing",
        })
        edges.append(_edge(f"course:{course.id}", f"chapter:{chapter.id}", "contains", "包含章节"))
        if source:
            nodes.append({
                "id": f"source:{source.id}",
                "name": source.title,
                "nodeType": "source",
                "category": 3,
                "categoryName": "来源",
                "summary": f"{source.file_format.upper()} · {source.processing_status}",
                "courseId": course.id,
                "chapterId": chapter.id,
                "sourceDocumentId": source.id,
                "sourceRefId": source_ref.id if source_ref else "",
                "locationLabel": source_ref.location_label if source_ref else "",
                "sourceStatus": source.processing_status,
                "sourceUrl": source.source_url or "",
                "license": source.license_text or "",
            })
            edges.append(_edge(f"source:{source.id}", f"chapter:{chapter.id}", "grounds", "来源支撑"))

    for point in points:
        linked_chapters = chapters_by_point.get(point.id, [])
        primary_chapter = linked_chapters[0] if linked_chapters else None
        source = source_by_id.get(primary_chapter.source_document_id) if primary_chapter else None
        source_ref = ref_by_chapter.get(primary_chapter.id) if primary_chapter else None
        nodes.append({
            "id": f"knowledge:{point.id}",
            "name": point.title,
            "nodeType": "knowledge_point",
            "category": 2,
            "categoryName": "知识点",
            "summary": f"{point.code} · {point.level}",
            "courseId": course.id,
            "knowledgePointId": point.id,
            "knowledgePointCode": point.code,
            "chapterId": primary_chapter.id if primary_chapter else "",
            "sourceDocumentId": source.id if source else "",
            "sourceRefId": source_ref.id if source_ref else "",
            "locationLabel": source_ref.location_label if source_ref else "",
            "sourceStatus": source.processing_status if source else "missing",
            "prerequisites": list(point.prerequisites or []),
            "masteryStatus": (mastery_by_point.get(point.id) or {}).get("status", "unknown"),
            "masteryScore": (mastery_by_point.get(point.id) or {}).get("score"),
            "masteryLabel": (mastery_by_point.get(point.id) or {}).get("label", "未知"),
            "masteryEvidenceCount": (mastery_by_point.get(point.id) or {}).get("evidence_item_count", 0),
            "masterySourceRefIds": list((mastery_by_point.get(point.id) or {}).get("source_ref_ids") or []),
            "masteryQuestionVersionIds": list((mastery_by_point.get(point.id) or {}).get("question_version_ids") or []),
            "masteryCrossEvidence": bool((mastery_by_point.get(point.id) or {}).get("cross_evidence")),
        })
    for chapter in chapters:
        for point in relations_by_chapter.get(chapter.id, []):
            edges.append(_edge(f"chapter:{chapter.id}", f"knowledge:{point.id}", "teaches", "讲授"))

    point_by_code = {point.code: point for point in points}
    for point in points:
        for prerequisite_code in point.prerequisites or []:
            prerequisite = point_by_code.get(str(prerequisite_code))
            if prerequisite:
                edges.append(_edge(
                    f"knowledge:{prerequisite.id}",
                    f"knowledge:{point.id}",
                    "prerequisite",
                    "先修",
                ))

    nodes = _deduplicate(nodes, key="id")
    edges = _deduplicate(edges, key="id")
    structure_analysis = _analyze_graph_structure(nodes, edges)
    metrics_by_id = structure_analysis["nodeMetrics"]
    for node in nodes:
        node.update(metrics_by_id.get(node["id"], {}))
    hierarchy = [{
        "chapterId": chapter.id,
        "title": chapter.title,
        "position": chapter.position,
        "sourceDocumentId": chapter.source_document_id,
        "sourceRefId": ref_by_chapter.get(chapter.id).id if ref_by_chapter.get(chapter.id) else "",
        "knowledgePoints": [
            {"id": point.id, "code": point.code, "title": point.title}
            for point in relations_by_chapter.get(chapter.id, [])
        ],
    } for chapter in chapters]
    status = "ready" if nodes and chapters else "empty"
    return {
        "schemaVersion": "edumatrix.course-knowledge-graph.v1",
        "status": status,
        "course": {
            "id": course.id,
            "title": course.title,
            "description": course.description or "",
            "version": course.version,
            "manifestVersion": course.manifest_version,
        },
        "categories": [
            {"name": "课程"},
            {"name": "章节"},
            {"name": "知识点"},
            {"name": "来源"},
        ],
        "nodes": nodes,
        "edges": edges,
        "hierarchy": hierarchy,
        "structureAnalysis": structure_analysis,
        "topicClusters": structure_analysis["topicClusters"],
        "layoutDecision": structure_analysis["layoutDecision"],
        "statistics": {
            "chapterCount": len(chapters),
            "knowledgePointCount": len(points),
            "sourceCount": len(sources),
            "nodeCount": len(nodes),
            "edgeCount": len(edges),
        },
        "masterySnapshot": {
            "status": "available" if diagnostic_snapshot else "not_available",
            "profileSnapshotId": diagnostic_snapshot.id if diagnostic_snapshot else None,
            "courseId": course.id,
        },
        "availability": {
            "status": status,
            "readOnly": True,
            "version": course.version,
            "manifestVersion": course.manifest_version,
            "message": "图谱浏览、搜索、筛选和来源预览不会写入学习证据。",
        },
        "projectionModes": ["graph", "relationship_projection"],
        "displayMode": "hierarchy" if len(nodes) > 300 else "graph",
        "authorityBoundary": "仅展示课程固定版本中的章节、知识点、先修和来源事实；联网候选不会进入本图谱。",
    }


def _edge(source: str, target: str, relation_type: str, label: str) -> dict[str, str]:
    return {
        "id": f"{relation_type}:{source}:{target}",
        "source": source,
        "target": target,
        "relationType": relation_type,
        "label": label,
    }


def _deduplicate(items: list[dict[str, Any]], *, key: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        identifier = str(item[key])
        if identifier in seen:
            continue
        seen.add(identifier)
        output.append(item)
    return output


def _analyze_graph_structure(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    """Describe the current graph so the client can choose a layout from data.

    The projection is deliberately deterministic: it only uses the canonical
    nodes/edges already returned by this endpoint.  It does not invent course
    facts, write learning events, or use a fixed four-cluster template.
    """
    node_ids = [str(node["id"]) for node in nodes]
    node_by_id = {str(node["id"]): node for node in nodes}
    knowledge_ids = [node_id for node_id in node_ids if node_by_id[node_id].get("nodeType") == "knowledge_point"]
    knowledge_set = set(knowledge_ids)
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    prerequisite_edges: list[dict[str, Any]] = []
    relation_counts: dict[str, int] = {}
    for edge in edges:
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        relation_type = str(edge.get("relationType", "unknown"))
        relation_counts[relation_type] = relation_counts.get(relation_type, 0) + 1
        if source in adjacency and target in adjacency:
            adjacency[source].add(target)
            adjacency[target].add(source)
        if relation_type == "prerequisite" and source in knowledge_set and target in knowledge_set:
            prerequisite_edges.append(edge)

    degree = {node_id: len(adjacency[node_id]) for node_id in node_ids}
    max_degree = max(degree.values(), default=1) or 1
    course_id = next((node_id for node_id in node_ids if node_by_id[node_id].get("nodeType") == "course"), None)
    depth: dict[str, int] = {}
    if course_id:
        queue = [course_id]
        depth[course_id] = 0
        while queue:
            current = queue.pop(0)
            for neighbor in sorted(adjacency.get(current, ())):
                if neighbor in depth:
                    continue
                depth[neighbor] = depth[current] + 1
                queue.append(neighbor)

    components: list[list[str]] = []
    remaining = set(knowledge_ids)
    while remaining:
        seed = min(remaining)
        stack = [seed]
        remaining.remove(seed)
        component: list[str] = []
        while stack:
            current = stack.pop()
            component.append(current)
            neighbors = set()
            for edge in prerequisite_edges:
                source = str(edge["source"])
                target = str(edge["target"])
                if source == current:
                    neighbors.add(target)
                elif target == current:
                    neighbors.add(source)
            for neighbor in sorted(neighbors & remaining):
                remaining.remove(neighbor)
                stack.append(neighbor)
        components.append(sorted(component))
    if not components and knowledge_ids:
        components = [sorted(knowledge_ids)]

    chapter_for_node = {
        str(node["id"]): str(node.get("chapterId", ""))
        for node in nodes
        if node.get("nodeType") == "knowledge_point"
    }
    if len(components) == len(knowledge_ids) and len(knowledge_ids) > 1 and not prerequisite_edges:
        by_chapter: dict[str, list[str]] = {}
        for node_id in knowledge_ids:
            by_chapter.setdefault(chapter_for_node.get(node_id, "unassigned"), []).append(node_id)
        components = [sorted(group) for group in by_chapter.values()]

    cluster_by_node: dict[str, str] = {}
    topic_clusters: list[dict[str, Any]] = []
    for index, members in enumerate(sorted(components, key=lambda group: (min(group), len(group)))):
        cluster_id = f"cluster:{index + 1}"
        for member in members:
            cluster_by_node[member] = cluster_id
        center = max(members, key=lambda node_id: (degree.get(node_id, 0), -len(node_id))) if members else ""
        topic_clusters.append({
            "id": cluster_id,
            "title": node_by_id.get(center, {}).get("name", "未命名主题"),
            "memberNodeIds": members,
            "size": len(members),
            "centerNodeId": center,
            "bridgeNodeIds": [],
        })

    cluster_neighbors: dict[str, set[str]] = {cluster["id"]: set() for cluster in topic_clusters}
    bridge_nodes: set[str] = set()
    for edge in prerequisite_edges:
        source_cluster = cluster_by_node.get(str(edge["source"]))
        target_cluster = cluster_by_node.get(str(edge["target"]))
        if source_cluster and target_cluster and source_cluster != target_cluster:
            cluster_neighbors[source_cluster].add(target_cluster)
            cluster_neighbors[target_cluster].add(source_cluster)
            bridge_nodes.update((str(edge["source"]), str(edge["target"])))
    for cluster in topic_clusters:
        cluster["bridgeNodeIds"] = sorted(node_id for node_id in cluster["memberNodeIds"] if node_id in bridge_nodes)

    node_metrics: dict[str, dict[str, Any]] = {}
    for node_id in node_ids:
        node = node_by_id[node_id]
        mastery_score = node.get("masteryScore")
        current_focus = bool(node.get("nodeType") == "knowledge_point" and isinstance(mastery_score, (int, float)) and mastery_score < 0.7)
        importance = round((degree.get(node_id, 0) / max_degree) if node.get("nodeType") == "knowledge_point" else 0.25, 3)
        node_metrics[node_id] = {
            "degree": degree.get(node_id, 0),
            "centrality": importance,
            "importance": importance,
            "hierarchyDepth": depth.get(node_id, 0),
            "topicClusterIds": [cluster_by_node[node_id]] if node_id in cluster_by_node else [],
            "isBridgeNode": node_id in bridge_nodes,
            "isCurrentFocus": current_focus,
            "needsDetailExplanation": bool(node.get("nodeType") in {"course", "chapter", "knowledge_point"} and (importance >= 0.5 or current_focus or node.get("sourceStatus") != "ready")),
        }

    knowledge_count = len(knowledge_ids)
    prereq_count = len(prerequisite_edges)
    density = round(prereq_count / max(knowledge_count * (knowledge_count - 1) / 2, 1), 4)
    cluster_count = len(topic_clusters)
    max_depth = max((node_metrics[node_id]["hierarchyDepth"] for node_id in node_ids), default=0)
    if knowledge_count >= 80:
        strategy = "local_focus"
        reason = "知识点数量达到高密度档位，先突出当前节点及局部邻域，支持搜索和展开其余节点。"
    elif relation_counts.get("prerequisite", 0) and (max_depth >= 3 or prereq_count >= max(2, knowledge_count // 2)):
        strategy = "hierarchical"
        reason = "先修关系形成可辨识层级，按数据层级排列并保留跨层关系。"
    elif cluster_count > 1 and cluster_count < max(knowledge_count, 2):
        strategy = "dynamic_cluster"
        reason = "先修关系或章节归属形成多个数据主题簇，簇数由当前数据决定。"
    elif knowledge_count and max(degree.values(), default=0) >= max(3, knowledge_count // 4):
        strategy = "multi_focus"
        reason = "存在一个或多个高连接节点，采用多焦点布局突出真实中心而非固定中心。"
    else:
        strategy = "constrained_force"
        reason = "当前关系不足以支持单一层级，采用受约束力导向并以边界/标签约束保持可读。"
    density_tier = "20_or_less" if knowledge_count <= 20 else "21_to_40" if knowledge_count <= 40 else "41_to_80" if knowledge_count <= 80 else "over_80"
    return {
        "nodeMetrics": node_metrics,
        "topicClusters": topic_clusters,
        "relationCounts": relation_counts,
        "density": density,
        "densityTier": density_tier,
        "layoutDecision": {
            "strategy": strategy,
            "reason": reason,
            "clusterCount": cluster_count,
            "nodeCount": len(node_ids),
            "knowledgePointCount": knowledge_count,
            "densityTier": density_tier,
            "constraints": ["节点与标签不得重叠", "边不得穿过节点", "布局不得越界", "保留右侧详情面板空间", "缩放/平移不写学习证据"],
            "supports": ["search", "filter", "focus", "collapse", "expand", "zoom", "pan"],
        },
    }
