from __future__ import annotations

import heapq
import math
from typing import Any

from animation_resources import find_animation_dir, load_animation_resource_index
from embedding_models import EMBEDDINGS, cosine_similarity as embedding_cosine_similarity
from models import (
    LearningStateCause,
    LearningStrategyPlan,
    StrategyAction,
    StrategyType,
    StudentProfile,
)
from enum import Enum


class TeachingTier(str, Enum):
    """自适应教学档位（任务 7.3）。"""
    SIMPLIFIED = "simplified"  # 降维解释：掌握度 < 50%
    STANDARD = "standard"      # 标准模式：50% ~ 80%
    ADVANCED = "advanced"      # 进阶挑战：掌握度 > 80%


def detect_teaching_tier(profile: StudentProfile, target: str | None = None) -> TeachingTier:
    """根据目标概念掌握度检测自适应教学档位。

    Args:
        profile: 学生画像
        target: 目标知识点（若为 None 则取最薄弱点）

    Returns:
        教学档位枚举
    """
    if target and target in profile.concept_mastery:
        mastery = profile.concept_mastery[target]
    elif profile.concept_mastery:
        mastery = min(profile.concept_mastery.values())
    else:
        return TeachingTier.STANDARD

    if mastery < 0.50:
        return TeachingTier.SIMPLIFIED
    elif mastery > 0.80:
        return TeachingTier.ADVANCED
    else:
        return TeachingTier.STANDARD


def _clamp_score(value: Any, default: float = 0.0) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = default
    return max(0.0, min(1.0, score))


def _concepts_from_dag(dag: dict[str, list[str]], mastery: dict[str, float] | None = None) -> set[str]:
    concepts: set[str] = set()
    for concept, prereqs in dag.items():
        if concept:
            concepts.add(str(concept))
        for prereq in prereqs or []:
            if prereq:
                concepts.add(str(prereq))
    for concept in (mastery or {}).keys():
        if concept:
            concepts.add(str(concept))
    return concepts


def _safe_unique(values: list[str] | tuple[str, ...] | set[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _has_forward_path(dag: dict[str, list[str]], source: str, target: str) -> bool:
    """Return True if source can already reach target in concept -> prereqs DAG."""
    if source == target:
        return True
    forward: dict[str, set[str]] = {}
    for concept, prereqs in dag.items():
        for prereq in prereqs or []:
            forward.setdefault(prereq, set()).add(concept)
    stack = [source]
    visited: set[str] = set()
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in visited:
            continue
        visited.add(node)
        stack.extend(sorted(forward.get(node, set()) - visited))
    return False


def _merge_prerequisite(
    dag: dict[str, list[str]],
    concept: str,
    prereq: str,
    *,
    source: str,
    edge_sources: dict[tuple[str, str], str],
) -> bool:
    concept = str(concept).strip()
    prereq = str(prereq).strip()
    if not concept or not prereq or concept == prereq:
        return False
    dag.setdefault(concept, [])
    dag.setdefault(prereq, dag.get(prereq, []))
    if prereq in dag[concept]:
        edge_sources.setdefault((prereq, concept), source)
        return False
    if _has_forward_path(dag, concept, prereq):
        return False
    dag[concept].append(prereq)
    dag[concept] = _safe_unique(dag[concept])
    edge_sources[(prereq, concept)] = source
    return True


def _animation_index() -> dict[str, dict[str, Any]]:
    base_dir = find_animation_dir()
    if base_dir is None:
        return {}
    return load_animation_resource_index(str(base_dir))


def _resource_signal(
    concept: str,
    resource_index: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resource_index = resource_index or {}
    item = resource_index.get(concept) or {}
    local_count = int(item.get("local_available_count") or 0)
    video_count = int(item.get("video_count") or item.get("downloaded") or 0)
    image_count = int(item.get("image_count") or 0)
    total_count = int(item.get("count") or local_count or video_count or 0)
    first_video = next(
        (file for file in item.get("local_files", []) if file.get("media_type") == "video"),
        {},
    )
    return {
        "has_animation": video_count > 0,
        "animation_count": max(total_count, local_count, video_count),
        "local_media_count": local_count,
        "video_count": video_count,
        "image_count": image_count,
        "platforms": list(item.get("platforms") or []),
        "media_types": list(item.get("media_types") or []),
        "preview_title": item.get("preview_title", ""),
        "sample_titles": list(item.get("titles") or [])[:3],
        "first_video_url": first_video.get("url", ""),
        "first_video_name": first_video.get("filename", ""),
    }


ANIMATION_PREREQUISITE_HINTS: dict[str, list[str]] = {
    "损失函数": ["线性回归"],
    "梯度下降": ["损失函数"],
    "前向传播": ["线性回归"],
    "激活函数": ["前向传播"],
    "反向传播": ["前向传播", "损失函数"],
    "神经网络": ["激活函数"],
    "欠拟合": ["模型评估"],
    "过拟合": ["模型评估"],
    "卷积神经网络": ["神经网络", "卷积核", "池化层"],
    "Transformer": ["注意力机制", "反向传播"],
}


def build_resource_aware_dag(
    base_dag: dict[str, list[str]],
    *,
    resource_index: dict[str, dict[str, Any]] | None = None,
    include_rag: bool = True,
) -> tuple[dict[str, list[str]], dict[str, Any]]:
    """Fuse static seed, GraphRAG edges and local animation concepts into one DAG."""
    resource_index = resource_index if resource_index is not None else _animation_index()
    active_dag = {str(concept): _safe_unique(tuple(prereqs or ())) for concept, prereqs in base_dag.items()}
    edge_sources: dict[tuple[str, str], str] = {}
    for concept, prereqs in active_dag.items():
        for prereq in prereqs:
            edge_sources[(prereq, concept)] = "seed_dag"

    rag_edges_added = 0
    if include_rag:
        try:
            from rag_engine import graph_rag

            reverse = getattr(graph_rag, "reverse", {}) or {}
            for target, prereqs in reverse.items():
                for prereq in prereqs or []:
                    if _merge_prerequisite(active_dag, str(target), str(prereq), source="graph_rag", edge_sources=edge_sources):
                        rag_edges_added += 1
        except Exception:
            rag_edges_added = 0

    animation_edges_added = 0
    for concept in sorted(resource_index):
        active_dag.setdefault(concept, [])
    for concept, prereqs in ANIMATION_PREREQUISITE_HINTS.items():
        if concept not in active_dag and concept not in resource_index:
            continue
        for prereq in prereqs:
            if prereq not in active_dag and prereq not in resource_index:
                continue
            if _merge_prerequisite(active_dag, concept, prereq, source="animation_resource", edge_sources=edge_sources):
                animation_edges_added += 1

    for concept in active_dag:
        active_dag[concept] = sorted(_safe_unique(tuple(active_dag[concept])))

    metadata = {
        "base_node_count": len(_concepts_from_dag(base_dag)),
        "active_node_count": len(_concepts_from_dag(active_dag)),
        "base_edge_count": sum(len(prereqs or []) for prereqs in base_dag.values()),
        "active_edge_count": sum(len(prereqs or []) for prereqs in active_dag.values()),
        "base_concepts": sorted(_concepts_from_dag(base_dag)),
        "active_concepts": sorted(_concepts_from_dag(active_dag)),
        "rag_edges_added": rag_edges_added,
        "animation_edges_added": animation_edges_added,
        "animation_concepts": sorted(resource_index),
        "animation_concept_count": len(resource_index),
        "animation_dataset_dir": next((item.get("base_dir", "") for item in resource_index.values() if item.get("base_dir")), ""),
        "edge_sources": {f"{source}->{target}": origin for (source, target), origin in edge_sources.items()},
    }
    return active_dag, metadata


def _concept_embedding_text(concept: str, resource_index: dict[str, dict[str, Any]]) -> str:
    resource = resource_index.get(concept) or {}
    parts = [
        concept,
        resource.get("category", ""),
        " ".join(resource.get("categories") or []),
        " ".join(_concept_tags(concept)),
        " ".join(str(title) for title in (resource.get("titles") or [])[:3]),
    ]
    return " ".join(part for part in parts if part)


def _concept_embedding_vectors(
    concepts: set[str],
    resource_index: dict[str, dict[str, Any]],
) -> tuple[dict[str, tuple[float, ...]], str, str]:
    vectors: dict[str, tuple[float, ...]] = {}
    error = ""
    for concept in sorted(concepts):
        text = _concept_embedding_text(concept, resource_index)
        try:
            vectors[concept] = tuple(float(value) for value in EMBEDDINGS.embed(text))
        except Exception as exc:
            error = str(exc)
            fallback = [
                1.0 if _concept_domain(concept) == item else 0.0
                for item in DOMAIN_ORDER
            ]
            fallback.extend([1.0 if tag in _concept_tags(concept) else 0.0 for tag in ("优化", "概率", "图像", "注意力")])
            vectors[concept] = tuple(_normalize_vector(fallback))
    return vectors, getattr(EMBEDDINGS, "name", "unknown"), error


def compute_concept_tiers(
    dag: dict[str, list[str]],
    concepts: set[str] | None = None,
) -> dict[str, int]:
    """Compute stable prerequisite tiers from a concept -> prerequisites graph."""
    all_concepts = set(concepts or _concepts_from_dag(dag))
    all_concepts.discard("")

    concept_tier: dict[str, int] = {}
    remaining = set(all_concepts)
    changed = True
    while remaining and changed:
        changed = False
        for concept in sorted(remaining):
            prereqs = [p for p in dag.get(concept, []) if p in all_concepts]
            if all(p in concept_tier for p in prereqs):
                concept_tier[concept] = (max((concept_tier[p] for p in prereqs), default=-1) + 1)
                remaining.remove(concept)
                changed = True

    # Fallback for any accidental cycle or external concept not covered by the DAG.
    fallback_tier = max(concept_tier.values(), default=-1) + 1
    for concept in sorted(remaining):
        concept_tier[concept] = fallback_tier
    return concept_tier


CROSS_DISCIPLINARY_MICRO_CONCEPTS: dict[str, dict[str, Any]] = {
    "偏导数": {
        "domain": "mathematics",
        "tags": ("梯度", "优化", "微积分"),
        "supports": ("梯度下降", "反向传播"),
    },
    "矩阵乘法": {
        "domain": "mathematics",
        "tags": ("线性代数", "向量", "参数"),
        "supports": ("线性回归", "神经网络"),
    },
    "向量空间": {
        "domain": "mathematics",
        "tags": ("几何", "间隔", "特征"),
        "supports": ("支持向量机", "特征工程"),
    },
    "信息熵": {
        "domain": "statistics",
        "tags": ("不确定性", "划分", "概率"),
        "supports": ("决策树", "模型评估"),
    },
    "贝叶斯定理": {
        "domain": "statistics",
        "tags": ("概率", "先验", "后验"),
        "supports": ("朴素贝叶斯",),
    },
    "概率分布": {
        "domain": "statistics",
        "tags": ("概率", "数据", "评估"),
        "supports": ("交叉验证", "模型评估", "朴素贝叶斯"),
    },
    "滤波器": {
        "domain": "signal_processing",
        "tags": ("卷积", "局部感受野", "图像"),
        "supports": ("卷积核", "卷积神经网络"),
    },
    "图像降采样": {
        "domain": "signal_processing",
        "tags": ("图像", "压缩", "池化"),
        "supports": ("池化层", "最大池化", "平均池化"),
    },
    "电磁场叠加": {
        "domain": "physics",
        "tags": ("叠加", "加权求和", "注意力"),
        "supports": ("注意力机制", "Transformer"),
    },
}

CONCEPT_DOMAIN_HINTS = {
    "链式法则": "mathematics",
    "梯度下降": "mathematics",
    "线性回归": "statistics",
    "逻辑回归": "statistics",
    "朴素贝叶斯": "statistics",
    "交叉验证": "statistics",
    "混淆矩阵": "statistics",
    "模型评估": "statistics",
    "卷积核": "signal_processing",
    "池化层": "signal_processing",
    "最大池化": "signal_processing",
    "平均池化": "signal_processing",
    "特征图": "signal_processing",
}

DOMAIN_ORDER = ("machine_learning", "mathematics", "statistics", "signal_processing", "physics")
DOMAIN_LABELS = {
    "machine_learning": "机器学习",
    "mathematics": "数学",
    "statistics": "统计学",
    "signal_processing": "信号处理",
    "physics": "物理",
}


def _concept_domain(concept: str) -> str:
    if concept in CROSS_DISCIPLINARY_MICRO_CONCEPTS:
        return str(CROSS_DISCIPLINARY_MICRO_CONCEPTS[concept]["domain"])
    return CONCEPT_DOMAIN_HINTS.get(concept, "machine_learning")


def _concept_tags(concept: str) -> set[str]:
    if concept in CROSS_DISCIPLINARY_MICRO_CONCEPTS:
        return set(CROSS_DISCIPLINARY_MICRO_CONCEPTS[concept].get("tags", ()))
    tags = set()
    if "回归" in concept:
        tags.update(("参数", "预测", "优化"))
    if "梯度" in concept or "反向传播" in concept:
        tags.update(("梯度", "优化", "微积分"))
    if "贝叶斯" in concept or "评估" in concept or "矩阵" in concept:
        tags.update(("概率", "统计", "评估"))
    if "卷积" in concept or "池化" in concept or "特征图" in concept:
        tags.update(("图像", "卷积", "局部感受野"))
    if "注意力" in concept or "Transformer" in concept:
        tags.update(("注意力", "加权求和", "序列"))
    return tags


def _normalize_vector(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values))
    if norm <= 1e-9:
        return [0.0 for _ in values]
    return [v / norm for v in values]


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def build_cross_disciplinary_micro_graph(
    dag: dict[str, list[str]],
    mastery: dict[str, float] | None = None,
    *,
    concept_tier: dict[str, int] | None = None,
    cognitive_load: float = 0.45,
    frustration: float = 0.0,
    similarity_threshold: float = 0.78,
    resource_index: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a mixed-domain micro-concept graph with real embedding similarity."""
    mastery = mastery or {}
    resource_index = resource_index if resource_index is not None else _animation_index()
    course_concepts = _concepts_from_dag(dag, mastery)
    concepts = set(course_concepts) | set(CROSS_DISCIPLINARY_MICRO_CONCEPTS.keys()) | set(resource_index.keys())
    tiers = concept_tier or compute_concept_tiers(dag, course_concepts)
    load = _clamp_score(cognitive_load, 0.45)
    affect = _clamp_score(frustration, 0.0)

    cross_edges = []
    for source, meta in CROSS_DISCIPLINARY_MICRO_CONCEPTS.items():
        supported = [target for target in meta.get("supports", ()) if target in concepts]
        target_tiers = [tiers.get(target, 1) for target in supported]
        tiers[source] = max(0, min(target_tiers, default=1) - 1)
        for target in supported:
            target_score = _clamp_score(mastery.get(target, 0.0))
            source_score = _clamp_score(mastery.get(source, 0.0))
            weight = 0.95 + max(0.0, 0.7 - target_score) * 1.05 + max(0.0, 0.4 - source_score) * 0.7
            weight += load * 0.25 + affect * 0.15
            cross_edges.append(
                {
                    "from": source,
                    "to": target,
                    "type": "cross_domain_prerequisite",
                    "weight": round(weight, 3),
                    "source_domain": meta["domain"],
                    "target_domain": _concept_domain(target),
                    "reason": f"「{target}」卡住时，先回补{DOMAIN_LABELS.get(meta['domain'], meta['domain'])}微概念「{source}」",
                }
            )

    prerequisite_edges = []
    for target, prereqs in dag.items():
        for source in prereqs or []:
            if source not in concepts or target not in concepts:
                continue
            prerequisite_edges.append(
                {
                    "from": source,
                    "to": target,
                    "type": "course_prerequisite",
                    "weight": 1.0,
                    "source_domain": _concept_domain(source),
                    "target_domain": _concept_domain(target),
                    "reason": f"课程前置依赖：{source} -> {target}",
                }
            )

    graph_backend = "adjacency"
    try:
        import networkx as nx

        nx_graph = nx.DiGraph()
        for concept in concepts:
            nx_graph.add_node(concept, domain=_concept_domain(concept), tier=tiers.get(concept, 0))
        for edge in prerequisite_edges + cross_edges:
            nx_graph.add_edge(edge["from"], edge["to"], **edge)
        undirected_neighbors = {node: set(nx_graph.predecessors(node)) | set(nx_graph.successors(node)) for node in nx_graph.nodes}
        degree_lookup = dict(nx_graph.degree())
        graph_backend = "networkx"
    except Exception:
        undirected_neighbors: dict[str, set[str]] = {concept: set() for concept in concepts}
        degree_lookup = {concept: 0 for concept in concepts}
        for edge in prerequisite_edges + cross_edges:
            undirected_neighbors.setdefault(edge["from"], set()).add(edge["to"])
            undirected_neighbors.setdefault(edge["to"], set()).add(edge["from"])
            degree_lookup[edge["from"]] = degree_lookup.get(edge["from"], 0) + 1
            degree_lookup[edge["to"]] = degree_lookup.get(edge["to"], 0) + 1

    embeddings, embedding_backend, embedding_error = _concept_embedding_vectors(concepts, resource_index)

    existing_pairs = {(edge["from"], edge["to"]) for edge in prerequisite_edges + cross_edges}
    semantic_edges = []
    ordered_concepts = sorted(concepts, key=lambda item: (tiers.get(item, 99), item))
    for idx, left in enumerate(ordered_concepts):
        for right in ordered_concepts[idx + 1:]:
            if (left, right) in existing_pairs or (right, left) in existing_pairs:
                continue
            left_domain = _concept_domain(left)
            right_domain = _concept_domain(right)
            if left_domain == right_domain:
                continue
            tag_overlap = len(_concept_tags(left) & _concept_tags(right))
            similarity = embedding_cosine_similarity(embeddings[left], embeddings[right])
            if tag_overlap:
                similarity = max(similarity, 0.72 + min(0.2, tag_overlap * 0.06))
            if similarity >= similarity_threshold:
                semantic_edges.append(
                    {
                        "from": left,
                        "to": right,
                        "type": "embedding_similarity",
                        "weight": round(1.0 / max(similarity, 0.01), 3),
                        "similarity": round(similarity, 3),
                        "source_domain": left_domain,
                        "target_domain": right_domain,
                        "reason": f"{embedding_backend} 语义相似度 {similarity:.2f}，可作为跨学科类比补充",
                    }
                )
    semantic_edges = sorted(semantic_edges, key=lambda edge: (-edge["similarity"], edge["from"], edge["to"]))[:24]

    nodes = []
    for concept in ordered_concepts:
        domain = _concept_domain(concept)
        nodes.append(
            {
                "id": concept,
                "concept": concept,
                "domain": domain,
                "domain_label": DOMAIN_LABELS.get(domain, domain),
                "tier": tiers.get(concept, 0),
                "mastery": round(_clamp_score(mastery.get(concept, 0.0)), 2),
                "tags": sorted(_concept_tags(concept)),
                "embedding": [round(value, 4) for value in embeddings[concept][:8]],
                "resource": _resource_signal(concept, resource_index),
            }
        )

    all_edges = prerequisite_edges + cross_edges + semantic_edges
    domains = sorted({node["domain"] for node in nodes})
    return {
        "nodes": nodes,
        "edges": sorted(all_edges, key=lambda edge: (edge["type"], edge["from"], edge["to"])),
        "metadata": {
            "node_count": len(nodes),
            "edge_count": len(all_edges),
            "cross_domain_edge_count": len(cross_edges),
            "semantic_edge_count": len(semantic_edges),
            "domains": domains,
            "graph_backend": graph_backend,
            "embedding_backend": embedding_backend,
            "embedding_algorithm": "semantic cosine similarity via EMBEDDINGS.embed",
            "embedding_error": embedding_error,
            "resource_concept_count": len(resource_index),
            "cognitive_load": round(load, 2),
            "frustration": round(affect, 2),
        },
    }


def suggest_cross_domain_supports(
    cross_graph: dict[str, Any],
    route_concepts: list[str] | tuple[str, ...],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    route_set = set(route_concepts)
    node_lookup = {node["concept"]: node for node in cross_graph.get("nodes", [])}
    supports = []
    for edge in cross_graph.get("edges", []):
        if edge.get("type") != "cross_domain_prerequisite" or edge.get("to") not in route_set:
            continue
        source = node_lookup.get(edge["from"], {})
        target = node_lookup.get(edge["to"], {})
        supports.append(
            {
                "concept": edge["from"],
                "target": edge["to"],
                "domain": source.get("domain", edge.get("source_domain", "")),
                "domain_label": source.get("domain_label", edge.get("source_domain", "")),
                "target_domain": target.get("domain", edge.get("target_domain", "")),
                "target_domain_label": target.get("domain_label", edge.get("target_domain", "")),
                "mastery": source.get("mastery", 0.0),
                "weight": edge.get("weight", 1.0),
                "reason": edge.get("reason", ""),
            }
        )
    return sorted(supports, key=lambda item: (item["weight"], item["concept"], item["target"]))[:limit]


def build_micro_concept_graph(
    dag: dict[str, list[str]],
    mastery: dict[str, float] | None = None,
    *,
    concept_tier: dict[str, int] | None = None,
    cognitive_load: float = 0.45,
    frustration: float = 0.0,
    resource_index: dict[str, dict[str, Any]] | None = None,
    graph_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build weighted prerequisite edges for adaptive path planning."""
    mastery = mastery or {}
    resource_index = resource_index if resource_index is not None else {}
    concepts = _concepts_from_dag(dag, mastery)
    tiers = concept_tier or compute_concept_tiers(dag, concepts)
    load = _clamp_score(cognitive_load, 0.45)
    affect = _clamp_score(frustration, 0.0)

    out_degree = {concept: 0 for concept in concepts}
    in_degree = {concept: 0 for concept in concepts}
    for concept, prereqs in dag.items():
        if concept not in concepts:
            continue
        for prereq in prereqs or []:
            if prereq in concepts:
                out_degree[prereq] = out_degree.get(prereq, 0) + 1
                in_degree[concept] = in_degree.get(concept, 0) + 1

    nodes = []
    for concept in sorted(concepts, key=lambda item: (tiers.get(item, 99), item)):
        score = _clamp_score(mastery.get(concept, 0.0))
        prereqs = [p for p in dag.get(concept, []) if p in concepts]
        prereqs_ready = all(_clamp_score(mastery.get(p, 0.0)) >= 0.4 for p in prereqs)
        mastered = score >= 0.7
        resource = _resource_signal(concept, resource_index)
        nodes.append(
            {
                "id": concept,
                "concept": concept,
                "tier": tiers.get(concept, 0),
                "mastery": round(score, 2),
                "percentage": round(score * 100),
                "status": "mastered" if mastered else ("available" if prereqs_ready else "locked"),
                "prerequisites": prereqs,
                "prereqs_ready": prereqs_ready,
                "out_degree": out_degree.get(concept, 0),
                "in_degree": in_degree.get(concept, 0),
                "weak": score < 0.4,
                "resource": resource,
            }
        )

    edges = []
    for concept in sorted(concepts, key=lambda item: (tiers.get(item, 99), item)):
        target_score = _clamp_score(mastery.get(concept, 0.0))
        target_gap = max(0.0, 0.7 - target_score)
        complexity = min(1.0, (len(dag.get(concept, [])) + out_degree.get(concept, 0)) / 6.0)
        for prereq in sorted(p for p in dag.get(concept, []) if p in concepts):
            prereq_score = _clamp_score(mastery.get(prereq, 0.0))
            prereq_gap = max(0.0, 0.4 - prereq_score)
            weight = 1.0 + target_gap * 1.15 + prereq_gap * 1.4 + load * 0.35 + affect * 0.25 + complexity * 0.3
            resource = _resource_signal(concept, resource_index)
            if resource["has_animation"]:
                weight -= min(0.25, resource["video_count"] * 0.035)
            weight = max(0.65, weight)
            edge_source = (graph_metadata or {}).get("edge_sources", {}).get(f"{prereq}->{concept}", "seed_dag")
            edges.append(
                {
                    "from": prereq,
                    "to": concept,
                    "type": "prerequisite",
                    "weight": round(weight, 3),
                    "prerequisite_mastery": round(prereq_score, 2),
                    "target_mastery": round(target_score, 2),
                    "source": edge_source,
                    "resource": resource,
                    "reason": (
                        f"先稳固「{prereq}」，再进入「{concept}」"
                        + ("；本地动画资源可辅助可视化理解" if resource["has_animation"] else "")
                    ),
                }
            )

    return {
        "nodes": nodes,
        "edges": sorted(edges, key=lambda edge: (tiers.get(edge["from"], 99), edge["from"], edge["to"])),
        "metadata": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "cognitive_load": round(load, 2),
            "frustration": round(affect, 2),
            "resource_concept_count": len(resource_index),
            "graph_fusion": graph_metadata or {},
        },
    }


def _ancestors_for_target(dag: dict[str, list[str]], target: str) -> set[str]:
    ancestors: set[str] = set()

    def visit(concept: str) -> None:
        for prereq in dag.get(concept, []) or []:
            if prereq not in ancestors:
                ancestors.add(prereq)
                visit(prereq)

    visit(target)
    return ancestors


def build_adaptive_astar_route(
    dag: dict[str, list[str]],
    mastery: dict[str, float] | None = None,
    *,
    learning_goals: list[str] | tuple[str, ...] | None = None,
    weak_points: list[str] | tuple[str, ...] | None = None,
    concept_tier: dict[str, int] | None = None,
    cognitive_load: float = 0.45,
    frustration: float = 0.0,
    mastery_threshold: float = 0.7,
    max_steps: int = 8,
    resource_index: dict[str, dict[str, Any]] | None = None,
    graph_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Plan a deterministic multi-constraint A* route over prerequisite edges."""
    mastery = mastery or {}
    resource_index = resource_index if resource_index is not None else {}
    graph_metadata = graph_metadata or {}
    concepts = _concepts_from_dag(dag, mastery)
    tiers = concept_tier or compute_concept_tiers(dag, concepts)
    graph = build_micro_concept_graph(
        dag,
        mastery,
        concept_tier=tiers,
        cognitive_load=cognitive_load,
        frustration=frustration,
        resource_index=resource_index,
        graph_metadata=graph_metadata,
    )
    threshold = _clamp_score(mastery_threshold, 0.7)
    max_steps = max(3, int(max_steps or 8))
    load = _clamp_score(cognitive_load, 0.45)
    affect = _clamp_score(frustration, 0.0)
    goal_set = {g for g in (learning_goals or []) if g}
    weak_set = {w for w in (weak_points or []) if w}
    primary_goal = sorted(goal_set)[0] if goal_set else ""
    goal_related = set(goal_set)
    for goal in goal_set:
        goal_related.update(_ancestors_for_target(dag, goal))
    for weak in weak_set:
        goal_related.update(_ancestors_for_target(dag, weak))

    base_concepts = set(graph_metadata.get("base_concepts") or concepts)
    explicit_concepts = set(mastery.keys()) | goal_set | weak_set
    allowed_targets = base_concepts | explicit_concepts | goal_related

    adjacency: dict[str, list[tuple[str, float]]] = {concept: [] for concept in concepts}
    edge_map: dict[tuple[str, str], dict[str, Any]] = {}
    for edge in graph["edges"]:
        adjacency.setdefault(edge["from"], []).append((edge["to"], float(edge["weight"])))
        edge_map[(edge["from"], edge["to"])] = edge
    for neighbors in adjacency.values():
        neighbors.sort(key=lambda item: (tiers.get(item[0], 99), item[0]))

    def target_priority(concept: str) -> float:
        score = _clamp_score(mastery.get(concept, 0.0))
        tier = tiers.get(concept, 0)
        priority = (1.0 - score) * 1.8 + tier * 0.22
        if concept in weak_set:
            priority += 5.0
        elif concept in goal_set:
            priority += 3.5
        elif concept in goal_related:
            priority += 0.8
        if score < 0.3:
            priority += 0.25
        if len(dag.get(concept, []) or []) >= 2:
            priority += 0.15
        resource = _resource_signal(concept, resource_index)
        if resource["has_animation"] and (concept in goal_related or concept in explicit_concepts):
            priority += min(0.45, 0.08 * resource["video_count"])
        return priority

    def astar(start: str, target: str) -> tuple[list[str], float] | None:
        target_tier = tiers.get(target, 0)

        def heuristic(node: str) -> float:
            tier_gap = max(0, target_tier - tiers.get(node, 0))
            score_gap = max(0.0, threshold - _clamp_score(mastery.get(node, 0.0)))
            return tier_gap * (0.65 + load * 0.2) + score_gap * 0.15

        heap: list[tuple[float, float, str, tuple[str, ...]]] = [(heuristic(start), 0.0, start, (start,))]
        best_cost = {start: 0.0}
        while heap:
            _priority, cost_so_far, node, path = heapq.heappop(heap)
            if node == target:
                return list(path), cost_so_far
            if cost_so_far > best_cost.get(node, float("inf")):
                continue
            for neighbor, edge_cost in adjacency.get(node, []):
                if neighbor in path:
                    continue
                next_cost = cost_so_far + edge_cost
                if next_cost < best_cost.get(neighbor, float("inf")):
                    best_cost[neighbor] = next_cost
                    heapq.heappush(
                        heap,
                        (next_cost + heuristic(neighbor), next_cost, neighbor, (*path, neighbor)),
                    )
        return None

    def expand_required_prereqs(path: list[str]) -> list[str]:
        expanded: list[str] = []

        def add_concept(concept: str) -> None:
            for prereq in sorted(dag.get(concept, []) or [], key=lambda item: (tiers.get(item, 99), item)):
                if _clamp_score(mastery.get(prereq, 0.0)) < threshold and prereq not in expanded:
                    add_concept(prereq)
            if concept not in expanded:
                expanded.append(concept)

        for concept in path:
            add_concept(concept)
        return expanded

    def route_cost(path: list[str]) -> float:
        cost = 0.0
        for idx in range(1, len(path)):
            edge = edge_map.get((path[idx - 1], path[idx]))
            cost += float(edge["weight"]) if edge else 1.5
        return cost

    candidates = [
        concept
        for concept in concepts
        if concept in allowed_targets and _clamp_score(mastery.get(concept, 0.0)) < threshold
    ]
    ranked_targets = sorted(candidates, key=lambda concept: (-target_priority(concept), -tiers.get(concept, 0), concept))

    route_options: list[dict[str, Any]] = []
    overflow_options: list[dict[str, Any]] = []
    for target in ranked_targets[:12]:
        ancestors = _ancestors_for_target(dag, target)
        roots = sorted(
            [concept for concept in (ancestors | {target}) if not dag.get(concept)],
            key=lambda concept: (tiers.get(concept, 99), concept),
        )
        if not roots:
            roots = sorted(concepts, key=lambda concept: (tiers.get(concept, 99), concept))

        best_path: list[str] | None = None
        best_cost = float("inf")
        for root in roots:
            result = astar(root, target)
            if not result:
                continue
            path, cost = result
            first_unmastered = next(
                (idx for idx, concept in enumerate(path) if _clamp_score(mastery.get(concept, 0.0)) < threshold),
                max(0, len(path) - 1),
            )
            path = path[first_unmastered:]
            path = expand_required_prereqs(path)
            cost = route_cost(path)
            if cost < best_cost or (cost == best_cost and path < (best_path or path)):
                best_path = path
                best_cost = cost

        if not best_path:
            continue
        display_path = list(best_path)
        staged_from = ""
        if len(display_path) > max_steps:
            display_path = display_path[:max_steps]
            staged_from = target
        option_bucket = route_options
        length_bonus = 0.75 if 5 <= len(best_path) <= max_steps else 0.2
        overflow_penalty = max(0, len(best_path) - max_steps) * 0.6
        if staged_from and target in goal_set:
            overflow_penalty *= 0.35
        option_score = target_priority(target) + length_bonus - abs(len(display_path) - 6) * 0.05 - overflow_penalty
        option_bucket.append(
            {
                "target": display_path[-1] if staged_from else target,
                "final_goal": primary_goal or target,
                "full_path": best_path,
                "path": display_path,
                "search_cost": route_cost(display_path),
                "option_score": option_score,
                "resource_hits": sum(1 for concept in display_path if _resource_signal(concept, resource_index)["has_animation"]),
                "staged_from": staged_from,
            }
        )

    if not route_options and overflow_options:
        route_options = overflow_options

    if not route_options:
        final_goal = primary_goal
        return {
            "target_concept": "",
            "stage_target_concept": "",
            "final_goal_concept": final_goal,
            "is_staged_route": False,
            "start_concept": "",
            "total_cost": 0.0,
            "estimated_minutes": 0,
            "confidence": 0.0,
            "strategy": "A* 候选草案 + Planner Agent 资源感知审核",
            "candidate_draft": {
                "target": "",
                "final_goal": final_goal,
                "path": [],
                "draft_steps": 0,
                "generated_by": "A* Engine",
            },
            "nodes": [],
            "edges": [],
            "topology_audit": {"passed": True, "checked_edges": 0, "violations": []},
            "planner_trace": [],
            "resource_summary": {
                "matched_route_nodes": 0,
                "animation_dataset_dir": graph_metadata.get("animation_dataset_dir", ""),
                "animation_concept_count": graph_metadata.get("animation_concept_count", len(resource_index)),
            },
            "graph_fusion": {
                "base_node_count": graph_metadata.get("base_node_count", len(concepts)),
                "active_node_count": graph_metadata.get("active_node_count", len(concepts)),
                "rag_edges_added": graph_metadata.get("rag_edges_added", 0),
                "animation_edges_added": graph_metadata.get("animation_edges_added", 0),
            },
            "reasons": ["当前图谱中没有可生成的前置路线"],
            "constraints": {
                "mastery_threshold": threshold,
                "max_steps": max_steps,
                "cognitive_load": round(load, 2),
                "frustration": round(affect, 2),
            },
        }

    selected = sorted(
        route_options,
        key=lambda item: (-item["option_score"], -item["resource_hits"], item["search_cost"], item["target"]),
    )[0]
    candidate_path = list(selected["path"])
    route = list(candidate_path)
    final_goal = selected.get("final_goal") or (sorted(goal_set)[0] if goal_set else selected["target"])
    is_staged = bool(final_goal and final_goal != selected["target"])

    route_nodes: list[dict[str, Any]] = []
    route_edges: list[dict[str, Any]] = []
    cumulative = 0.0
    for idx, concept in enumerate(route):
        score = _clamp_score(mastery.get(concept, 0.0))
        tier = tiers.get(concept, 0)
        resource = _resource_signal(concept, resource_index)
        step_cost = 0.0
        if idx > 0:
            edge = edge_map.get((route[idx - 1], concept))
            if edge:
                step_cost = float(edge["weight"])
                cumulative += step_cost
                route_edges.append(
                    {
                        "from": edge["from"],
                        "to": edge["to"],
                        "weight": edge["weight"],
                        "source": edge.get("source", "seed_dag"),
                        "resource": edge.get("resource", {}),
                        "reason": edge["reason"],
                    }
                )

        if score >= threshold:
            action = "快速复核"
        elif score < 0.35:
            action = "降维重建"
        elif resource["has_animation"]:
            action = "动画助学"
        elif tier >= 4:
            action = "进阶攻克"
        else:
            action = "巩固推进"

        route_nodes.append(
            {
                "step": idx + 1,
                "concept": concept,
                "tier": tier,
                "mastery": round(score, 2),
                "percentage": round(score * 100),
                "action": action,
                "cost_from_previous": round(step_cost, 2),
                "cumulative_cost": round(cumulative, 2),
                "estimated_minutes": int(min(95, max(30, 30 + tier * 5 + (threshold - score) * 35 + load * 10))),
                "resource": resource,
                "planner_mode": (
                    "Simplified Model" if score < 0.35 else ("Visual Micro-lesson" if resource["has_animation"] else "Guided Practice")
                ),
                "reason": (
                    f"当前掌握度 {round(score * 100)}%，"
                    f"{'先补齐前置理解' if score < 0.4 else '适合继续提升迁移能力'}"
                    + (f"；已匹配 {resource['video_count']} 个本地动画资源" if resource["has_animation"] else "")
                ),
            }
        )

    avg_mastery = sum(node["mastery"] for node in route_nodes) / len(route_nodes)
    confidence = max(0.55, min(0.95, 0.9 - load * 0.16 - affect * 0.1 + avg_mastery * 0.08))
    total_minutes = sum(node["estimated_minutes"] for node in route_nodes)
    audit = _audit_route_topology(dag, route)
    resource_count = sum(1 for node in route_nodes if node.get("resource", {}).get("has_animation"))
    planner_trace = _build_planner_trace(
        candidate_path,
        route,
        selected["target"],
        resource_count,
        audit,
        graph_metadata,
    )

    return {
        "target_concept": final_goal,
        "stage_target_concept": selected["target"],
        "final_goal_concept": final_goal,
        "is_staged_route": is_staged,
        "start_concept": route[0],
        "total_cost": round(cumulative, 2),
        "estimated_minutes": total_minutes,
        "confidence": round(confidence, 2),
        "strategy": "A* 候选草案 + Planner Agent 资源感知审核",
        "candidate_draft": {
            "target": selected["target"],
            "final_goal": final_goal,
            "path": candidate_path,
            "full_path": selected.get("full_path", candidate_path),
            "remaining_path": [
                concept
                for concept in selected.get("full_path", candidate_path)
                if concept not in candidate_path
            ],
            "draft_steps": len(candidate_path),
            "generated_by": "A* Engine",
        },
        "nodes": route_nodes,
        "edges": route_edges,
        "topology_audit": audit,
        "planner_trace": planner_trace,
        "resource_summary": {
            "matched_route_nodes": resource_count,
            "animation_dataset_dir": graph_metadata.get("animation_dataset_dir", ""),
            "animation_concept_count": graph_metadata.get("animation_concept_count", len(resource_index)),
        },
        "graph_fusion": {
            "base_node_count": graph_metadata.get("base_node_count", len(concepts)),
            "active_node_count": graph_metadata.get("active_node_count", len(concepts)),
            "rag_edges_added": graph_metadata.get("rag_edges_added", 0),
            "animation_edges_added": graph_metadata.get("animation_edges_added", 0),
        },
        "reasons": [
            "按前置依赖边展开搜索，避免跳过必要基础概念",
            "A* 只输出候选草案，Planner Agent 会按学生画像二次审核学习动作",
            "本地动画资源会参与路线加权，但不会覆盖前置依赖和拓扑顺序",
            f"最终目标「{final_goal}」被拆为当前阶段目标「{selected['target']}」" if is_staged else "当前路线可直接推进到目标概念",
        ],
        "constraints": {
            "mastery_threshold": threshold,
            "max_steps": max_steps,
            "cognitive_load": round(load, 2),
            "frustration": round(affect, 2),
        },
    }


def _audit_route_topology(dag: dict[str, list[str]], route: list[str]) -> dict[str, Any]:
    positions = {concept: idx for idx, concept in enumerate(route)}
    violations: list[dict[str, str]] = []
    checked = 0
    for concept in route:
        for prereq in dag.get(concept, []) or []:
            if prereq not in positions:
                continue
            checked += 1
            if positions[prereq] > positions[concept]:
                violations.append({"prerequisite": prereq, "concept": concept})
    return {
        "passed": not violations,
        "checked_edges": checked,
        "violations": violations,
    }


def _build_planner_trace(
    candidate_path: list[str],
    route: list[str],
    target: str,
    resource_count: int,
    audit: dict[str, Any],
    graph_metadata: dict[str, Any],
) -> list[str]:
    return [
        f"[A* Engine] 生成候选路线草案：{' -> '.join(candidate_path)}",
        f"[Graph Fusion] 已融合 RAG 边 {graph_metadata.get('rag_edges_added', 0)} 条、动画资源边 {graph_metadata.get('animation_edges_added', 0)} 条",
        f"[Resource Router] 路线中 {resource_count} 个节点匹配到本地动画资源",
        f"[Topology Checker] 拓扑审计{'通过' if audit.get('passed') else '需修正'}，检查边 {audit.get('checked_edges', 0)} 条",
        f"[Planner Agent] 确认目标「{target}」，将草案润色为 {len(route)} 步可执行学习动作",
    ]


class PathPlanner:
    """Facade for member 2 micro-graph construction and A* path planning."""

    def __init__(self, dag: dict[str, list[str]]):
        self.dag = dag

    def _active_inputs(self) -> tuple[dict[str, list[str]], dict[str, dict[str, Any]], dict[str, Any], dict[str, int]]:
        resource_index = _animation_index()
        active_dag, graph_metadata = build_resource_aware_dag(self.dag, resource_index=resource_index)
        return active_dag, resource_index, graph_metadata, compute_concept_tiers(active_dag)

    def build_micro_graph(
        self,
        mastery: dict[str, float] | None = None,
        *,
        concept_tier: dict[str, int] | None = None,
        cognitive_load: float = 0.45,
        frustration: float = 0.0,
    ) -> dict[str, Any]:
        active_dag, resource_index, graph_metadata, active_tiers = self._active_inputs()
        return build_micro_concept_graph(
            active_dag,
            mastery,
            concept_tier=active_tiers,
            cognitive_load=cognitive_load,
            frustration=frustration,
            resource_index=resource_index,
            graph_metadata=graph_metadata,
        )

    def build_cross_disciplinary_graph(
        self,
        mastery: dict[str, float] | None = None,
        *,
        concept_tier: dict[str, int] | None = None,
        cognitive_load: float = 0.45,
        frustration: float = 0.0,
        similarity_threshold: float = 0.78,
    ) -> dict[str, Any]:
        active_dag, resource_index, graph_metadata, active_tiers = self._active_inputs()
        return build_cross_disciplinary_micro_graph(
            active_dag,
            mastery,
            concept_tier=active_tiers,
            cognitive_load=cognitive_load,
            frustration=frustration,
            similarity_threshold=similarity_threshold,
            resource_index=resource_index,
        )

    def plan(
        self,
        mastery: dict[str, float] | None = None,
        *,
        learning_goals: list[str] | tuple[str, ...] | None = None,
        weak_points: list[str] | tuple[str, ...] | None = None,
        concept_tier: dict[str, int] | None = None,
        cognitive_load: float = 0.45,
        frustration: float = 0.0,
        mastery_threshold: float = 0.7,
        max_steps: int = 8,
    ) -> dict[str, Any]:
        active_dag, resource_index, graph_metadata, active_tiers = self._active_inputs()
        return build_adaptive_astar_route(
            active_dag,
            mastery,
            learning_goals=learning_goals,
            weak_points=weak_points,
            concept_tier=active_tiers,
            cognitive_load=cognitive_load,
            frustration=frustration,
            mastery_threshold=mastery_threshold,
            max_steps=max_steps,
            resource_index=resource_index,
            graph_metadata=graph_metadata,
        )


class LearningStrategyEngine:
    """Maps learner-state evidence to concrete learning-science interventions."""

    def build_plan(self, profile: StudentProfile, *, target: str) -> LearningStrategyPlan:
        actions: list[StrategyAction] = []
        causes = profile.learning_state_causes

        if LearningStateCause.PREREQUISITE_GAP.value in causes:
            actions.append(
                StrategyAction(
                    strategy=StrategyType.WORKED_EXAMPLE,
                    title="先看 worked example，再做同构题",
                    description=f"围绕“{target}”先给完整示范题，标出前置概念、关键条件和解题触发点。",
                    trigger="前置知识缺口占比升高",
                    priority=1,
                )
            )

        if LearningStateCause.MISCONCEPTION.value in causes:
            actions.append(
                StrategyAction(
                    strategy=StrategyType.MISCONCEPTION_CONTRAST,
                    title="误概念反例辨析",
                    description="用正例、反例和相似概念对照表拆开学生的高频混淆点。",
                    trigger="误概念/易混点证据出现",
                    priority=1,
                )
            )

        if LearningStateCause.COGNITIVE_LOAD.value in causes:
            actions.append(
                StrategyAction(
                    strategy=StrategyType.HINT_LADDER,
                    title="三层提示阶梯",
                    description="先提示题目条件，再提示适用概念，最后只给局部步骤，避免直接暴露完整答案。",
                    trigger="认知负荷或多步骤遗漏风险升高",
                    priority=2,
                )
            )

        if LearningStateCause.STRATEGY_GAP.value in causes:
            actions.append(
                StrategyAction(
                    strategy=StrategyType.RETRIEVAL_PRACTICE,
                    title="检索练习与错因复盘",
                    description="学习后立刻安排 2 道不看资料的检索题，并要求学生写出错因和下次识别线索。",
                    trigger="学习策略不足或看答案依赖",
                    priority=2,
                )
            )

        if LearningStateCause.METACOGNITIVE_MISMATCH.value in causes:
            actions.append(
                StrategyAction(
                    strategy=StrategyType.METACOGNITIVE_CALIBRATION,
                    title="题前自评与题后校准",
                    description="每道关键题先记录自评掌握度，作答后比较表现，更新自我判断准确性。",
                    trigger="自评与真实表现不一致",
                    priority=2,
                )
            )

        # === P1-1 情感感知策略分支 ===
        if profile.frustration_index > 0.4:
            actions.append(
                StrategyAction(
                    strategy=StrategyType.HINT_LADDER,  # 使用 HINT_LADDER 策略型，但内容改为情感安抚
                    title="挫败感缓解与信心重建",
                    description=f"学生挫败感偏高({profile.frustration_index:.2f})。降低第一题难度，先建立成功体验；"
                                f"反馈聚焦具体任务进展而非人格评价；使用积极暗示（'上一题你已经掌握了关键点'）。",
                    trigger=f"挫败感指数{profile.frustration_index:.2f}>0.4",
                    priority=0,  # 最高优先级
                )
            )
        if profile.motivation_type == "无动机":
            actions.append(
                StrategyAction(
                    strategy=StrategyType.RETRIEVAL_PRACTICE,
                    title="动机激活：知识连接与意义发现",
                    description="暂停批量刷题，先通过案例展示当前知识在实际项目/考试中的具体应用场景，"
                                "让学生自己选择学习路径和目标，增强自主感。",
                    trigger="无动机状态",
                    priority=0,
                )
            )

        weakest = min(profile.concept_mastery.items(), key=lambda item: item[1], default=(target, 0.48))
        actions.append(
            StrategyAction(
                strategy=StrategyType.SPACED_REVIEW,
                title="间隔复习队列",
                description=f"把“{weakest[0]}”加入 1 天、3 天、7 天复习队列，每次只做短检索题验证保持率。",
                trigger="固定课程场景下持续巩固薄弱知识点",
                priority=3,
                scheduled_after="1d/3d/7d",
            )
        )

        actions = sorted(actions, key=lambda item: item.priority)
        rationale = (
            "策略引擎依据学生画像中的不会原因占比、知识掌握度和互动偏好，"
            "优先选择 worked example、提示阶梯、检索练习、间隔复习和元认知校准。"
        )
        return LearningStrategyPlan(
            course=profile.target_course,
            target=target,
            actions=tuple(actions),
            rationale=rationale,
        )
