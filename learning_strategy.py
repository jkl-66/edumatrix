from __future__ import annotations

import heapq
import hashlib
import math
import re
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
import threading

_GRAPH_CACHE_LOCK = threading.Lock()
_GRAPH_CACHE = {
    "active_dag": None,
    "resource_index": None,
    "graph_metadata": None,
    "active_tiers": None,
    "valid": False
}

def invalidate_graph_cache() -> None:
    """Invalidate the global graph cache for learning strategy planning."""
    global _GRAPH_CACHE
    with _GRAPH_CACHE_LOCK:
        _GRAPH_CACHE["valid"] = False
        _GRAPH_CACHE["active_dag"] = None
        _GRAPH_CACHE["resource_index"] = None
        _GRAPH_CACHE["graph_metadata"] = None
        _GRAPH_CACHE["active_tiers"] = None


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


def _resource_text(concept: str, resource_index: dict[str, dict[str, Any]] | None = None) -> str:
    resource = (resource_index or {}).get(concept) or {}
    parts = [
        concept,
        resource.get("category", ""),
        " ".join(resource.get("categories") or []),
        " ".join(str(title) for title in (resource.get("titles") or [])[:5]),
    ]
    return " ".join(part for part in parts if part)


def _concept_tags(concept: str, resource_index: dict[str, dict[str, Any]] | None = None) -> set[str]:
    """Extract lightweight semantic tags from concept/resource text instead of static concept maps."""
    text = _resource_text(concept, resource_index)
    tags = set(re.findall(r"[a-zA-Z0-9_+\-.]+|[\u4e00-\u9fff]{2,}", text.lower()))
    tags.update((resource_index or {}).get(concept, {}).get("categories") or [])

    signal_keywords = (
        "优化", "梯度", "导数", "微积分", "矩阵", "向量", "概率", "统计", "贝叶斯",
        "回归", "分类", "监督", "评估", "验证", "卷积", "池化", "图像", "滤波",
        "神经网络", "传播", "激活", "注意力", "Transformer", "特征", "序列",
    )
    for keyword in signal_keywords:
        if keyword.lower() in text.lower():
            tags.add(keyword)
    return {tag for tag in tags if tag and len(tag) <= 18}


def _concept_domain(concept: str, resource_index: dict[str, dict[str, Any]] | None = None) -> str:
    """Infer a display domain from resource metadata and generic lexical signals.

    This intentionally avoids the old concept-by-concept static domain table so
    uploaded GraphRAG entities and animation folders can form new domains.
    """
    resource = (resource_index or {}).get(concept) or {}
    category = str(resource.get("category") or "").strip()
    if category:
        return f"resource:{category}"

    text = _resource_text(concept, resource_index)
    lowered = text.lower()
    if any(key in text for key in ("导数", "微积分", "矩阵", "向量", "线性代数", "概率", "统计", "贝叶斯")):
        return "inferred:数学/统计基础"
    if any(key in text for key in ("卷积", "池化", "图像", "滤波", "特征图")):
        return "inferred:视觉/信号处理"
    if any(key in lowered for key in ("transformer", "attention")) or any(key in text for key in ("神经网络", "传播", "激活", "注意力")):
        return "inferred:深度学习"
    if any(key in text for key in ("回归", "分类", "监督", "决策树", "支持向量", "交叉验证", "模型评估")):
        return "inferred:机器学习方法"
    return "course:课程图谱"


def _domain_label(domain: str) -> str:
    if ":" in domain:
        return domain.split(":", 1)[1]
    return domain or "课程图谱"


def _infer_resource_prerequisite_edges(
    active_dag: dict[str, list[str]],
    resource_index: dict[str, dict[str, Any]],
    edge_sources: dict[tuple[str, str], str],
    *,
    protected_concepts: set[str] | None = None,
) -> int:
    """Infer missing resource prerequisites from metadata/embedding similarity.

    Resource edges are only added for concepts that do not already have known
    prerequisites, so local videos can enrich cold-start topics without
    overriding GraphRAG or course topology.
    """
    if not resource_index:
        return 0

    protected_concepts = protected_concepts or set()
    concepts = _concepts_from_dag(active_dag) | set(resource_index)
    tiers = compute_concept_tiers(active_dag, concepts)
    embeddings, _, _ = _concept_embedding_vectors(concepts, resource_index)
    added = 0

    for concept in sorted(resource_index):
        active_dag.setdefault(concept, [])
        if concept in protected_concepts:
            continue
        if active_dag.get(concept):
            continue

        concept_tags = _concept_tags(concept, resource_index)
        concept_text = _resource_text(concept, resource_index)
        candidates: list[tuple[float, str]] = []
        for prereq in sorted(concepts):
            if prereq == concept or prereq not in active_dag:
                continue
            if _has_forward_path(active_dag, concept, prereq):
                continue
            if tiers.get(prereq, 0) > tiers.get(concept, 99):
                continue

            overlap = len(concept_tags & _concept_tags(prereq, resource_index))
            similarity = embedding_cosine_similarity(embeddings[concept], embeddings[prereq])
            if prereq in concept_text:
                similarity = max(similarity, 0.9)
            if overlap:
                similarity = max(similarity, 0.68 + min(0.22, overlap * 0.04))
            if similarity >= 0.82:
                candidates.append((similarity, prereq))

        for _similarity, prereq in sorted(candidates, key=lambda item: (-item[0], tiers.get(item[1], 99), item[1]))[:1]:
            if _merge_prerequisite(active_dag, concept, prereq, source="animation_resource_inferred", edge_sources=edge_sources):
                added += 1

    return added


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
    protected_concepts = _concepts_from_dag(active_dag)
    for concept in sorted(resource_index):
        active_dag.setdefault(concept, [])
    animation_edges_added = _infer_resource_prerequisite_edges(
        active_dag,
        resource_index,
        edge_sources,
        protected_concepts=protected_concepts,
    )

    # Tarjan cycle defense / NetworkX cycle check to break cyclical dependencies
    try:
        import networkx as nx
        temp_g = nx.DiGraph()
        for node in active_dag:
            temp_g.add_node(node)
        for concept, prereqs in active_dag.items():
            for p in prereqs:
                if p:
                    temp_g.add_edge(p, concept)
        
        cycles = list(nx.simple_cycles(temp_g))
        if cycles:
            for cycle in cycles:
                cycle_edges = list(zip(cycle, cycle[1:] + [cycle[0]]))
                removed = False
                for u, v in cycle_edges:
                    # u is prereq of v (meaning the dependency edge is u -> v)
                    edge_origin = edge_sources.get((u, v))
                    if edge_origin and edge_origin != "seed_dag":
                        if u in active_dag.get(v, []):
                            active_dag[v].remove(u)
                            edge_sources.pop((u, v), None)
                            removed = True
                            break
                if not removed and cycle_edges:
                    u, v = cycle_edges[-1]
                    if u in active_dag.get(v, []):
                        active_dag[v].remove(u)
                        edge_sources.pop((u, v), None)
    except Exception:
        pass

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
        "resource_edges_inferred": animation_edges_added,
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
        " ".join(_concept_tags(concept, resource_index)),
        " ".join(str(title) for title in (resource.get("titles") or [])[:3]),
    ]
    return " ".join(part for part in parts if part)


_EMBEDDING_CACHE: dict[str, tuple[float, ...]] = {}

def _concept_embedding_vectors(
    concepts: set[str],
    resource_index: dict[str, dict[str, Any]],
) -> tuple[dict[str, tuple[float, ...]], str, str]:
    global _EMBEDDING_CACHE
    vectors: dict[str, tuple[float, ...]] = {}
    error = ""
    
    # 提取所有概念的分词，构建词表以用于 TF-IDF 备用向量空间
    concept_tokens = {}
    all_tokens = set()
    for c in concepts:
        tokens = list(_concept_tags(c, resource_index) | {c})
        concept_tokens[c] = tokens
        all_tokens.update(tokens)
    
    vocab = sorted(all_tokens)
    vocab_index = {word: idx for idx, word in enumerate(vocab)}
    dim = len(vocab) if vocab else 32

    use_fallback = False
    for concept in sorted(concepts):
        text = _concept_embedding_text(concept, resource_index)
        if text in _EMBEDDING_CACHE:
            vectors[concept] = _EMBEDDING_CACHE[text]
            continue
        try:
            vec = tuple(float(value) for value in EMBEDDINGS.embed(text))
            _EMBEDDING_CACHE[text] = vec
            vectors[concept] = vec
        except Exception as exc:
            error = str(exc)
            use_fallback = True
            break

    if use_fallback:
        # 降维平替：当 Embedding 服务异常时，使用真实的 TF-IDF 分词向量空间
        # 所有概念统一使用相同维度的 TF-IDF 向量，防止余弦相似度计算时发生维度截断
        for concept in sorted(concepts):
            fallback = [0.0] * dim
            for token in concept_tokens[concept]:
                if token in vocab_index:
                    fallback[vocab_index[token]] += 1.0
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


def _normalize_vector(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values))
    if norm <= 1e-9:
        return [0.0 for _ in values]
    return [v / norm for v in values]


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
    """Build a mixed-domain micro-concept graph with real embedding similarity.

    The graph is derived from the active DAG, GraphRAG/resource concepts and
    embeddings. It no longer injects a static cross-disciplinary micro-concept
    dictionary; prerequisite-like bridges are inferred from domain differences,
    topology order and semantic closeness.
    """
    mastery = mastery or {}
    resource_index = resource_index if resource_index is not None else _animation_index()
    course_concepts = _concepts_from_dag(dag, mastery)
    concepts = set(course_concepts) | set(resource_index.keys())
    tiers = concept_tier or compute_concept_tiers(dag, concepts)
    load = _clamp_score(cognitive_load, 0.45)
    affect = _clamp_score(frustration, 0.0)

    prerequisite_edges = []
    for target, prereqs in dag.items():
        for source in prereqs or []:
            if source not in concepts or target not in concepts:
                continue
            source_domain = _concept_domain(source, resource_index)
            target_domain = _concept_domain(target, resource_index)
            prerequisite_edges.append(
                {
                    "from": source,
                    "to": target,
                    "type": "course_prerequisite",
                    "weight": 1.0,
                    "source_domain": source_domain,
                    "target_domain": target_domain,
                    "reason": f"课程前置依赖：{source} -> {target}",
                }
            )

    graph_backend = "adjacency"
    try:
        import networkx as nx

        nx_graph = nx.DiGraph()
        for concept in concepts:
            nx_graph.add_node(concept, domain=_concept_domain(concept, resource_index), tier=tiers.get(concept, 0))
        for edge in prerequisite_edges:
            nx_graph.add_edge(edge["from"], edge["to"], **edge)
        undirected_neighbors = {node: set(nx_graph.predecessors(node)) | set(nx_graph.successors(node)) for node in nx_graph.nodes}
        degree_lookup = dict(nx_graph.degree())
        graph_backend = "networkx"
    except Exception:
        undirected_neighbors: dict[str, set[str]] = {concept: set() for concept in concepts}
        degree_lookup = {concept: 0 for concept in concepts}
        for edge in prerequisite_edges:
            undirected_neighbors.setdefault(edge["from"], set()).add(edge["to"])
            undirected_neighbors.setdefault(edge["to"], set()).add(edge["from"])
            degree_lookup[edge["from"]] = degree_lookup.get(edge["from"], 0) + 1
            degree_lookup[edge["to"]] = degree_lookup.get(edge["to"], 0) + 1

    embeddings, embedding_backend, embedding_error = _concept_embedding_vectors(concepts, resource_index)

    existing_pairs = {(edge["from"], edge["to"]) for edge in prerequisite_edges}
    cross_edges = []
    semantic_edges = []
    similarity_log = []
    ordered_concepts = sorted(concepts, key=lambda item: (tiers.get(item, 99), item))
    # 第一遍扫描：收集所有跨学科概念对的相似度，以便动态计算自适应分位数阈值
    all_cross_similarities = []
    pairs_data = []
    for idx, left in enumerate(ordered_concepts):
        for right in ordered_concepts[idx + 1:]:
            left_domain = _concept_domain(left, resource_index)
            right_domain = _concept_domain(right, resource_index)
            if left_domain == right_domain:
                continue
            tag_overlap = len(_concept_tags(left, resource_index) & _concept_tags(right, resource_index))
            similarity = embedding_cosine_similarity(embeddings[left], embeddings[right])
            if tag_overlap:
                similarity = max(similarity, 0.72 + min(0.2, tag_overlap * 0.06))
            all_cross_similarities.append(similarity)
            pairs_data.append((left, right, left_domain, right_domain, similarity, tag_overlap))

    # 动态分位数自适应计算
    if all_cross_similarities:
        sorted_sims = sorted(all_cross_similarities)
        # 对应原始 0.78 语义边缘，取 85% 分位数作为过滤阈值，并设置合理下限安全防线
        pct_idx_high = int(len(sorted_sims) * 0.85)
        computed_similarity_threshold = max(0.68, min(0.85, sorted_sims[min(len(sorted_sims) - 1, pct_idx_high)]))
        # 对应原始 0.62 跨域回退阈值，取 65% 分位数，并设置下限安全防线
        pct_idx_low = int(len(sorted_sims) * 0.65)
        computed_low_threshold = max(0.55, min(0.72, sorted_sims[min(len(sorted_sims) - 1, pct_idx_low)]))
    else:
        computed_similarity_threshold = similarity_threshold
        computed_low_threshold = 0.62

    for left, right, left_domain, right_domain, similarity, tag_overlap in pairs_data:
        source, target = (left, right) if tiers.get(left, 99) <= tiers.get(right, 99) else (right, left)
        source_domain = _concept_domain(source, resource_index)
        target_domain = _concept_domain(target, resource_index)
        target_score = _clamp_score(mastery.get(target, 0.0))
        source_score = _clamp_score(mastery.get(source, 0.0))
        source_degree = degree_lookup.get(source, 0)

        if similarity >= 0.66 or tag_overlap:
            similarity_log.append(
                {
                    "source": source,
                    "target": target,
                    "similarity": round(similarity, 3),
                    "source_domain_label": _domain_label(source_domain),
                    "target_domain_label": _domain_label(target_domain),
                    "evidence": "embedding" if not tag_overlap else f"embedding+{tag_overlap} shared tags",
                }
            )

        topology_support = (source, target) in existing_pairs or source in _ancestors_for_target(dag, target)
        if target in course_concepts and topology_support and (similarity >= computed_low_threshold or tag_overlap):
            weight = 0.95 + max(0.0, 0.7 - target_score) * 0.95 + max(0.0, 0.4 - source_score) * 0.45
            weight += load * 0.18 + affect * 0.12 + min(0.25, source_degree * 0.03)
            cross_edges.append(
                {
                    "from": source,
                    "to": target,
                    "type": "cross_domain_prerequisite",
                    "weight": round(weight, 3),
                    "similarity": round(similarity, 3),
                    "source_domain": source_domain,
                    "target_domain": target_domain,
                    "reason": (
                        f"「{target}」卡住时，先回补{_domain_label(source_domain)}节点「{source}」；"
                        f"语义相似度 {similarity:.2f}"
                    ),
                }
            )

        if (left, right) in existing_pairs or (right, left) in existing_pairs:
            continue
        if similarity >= computed_similarity_threshold:
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

    if not cross_edges:
        for edge in prerequisite_edges:
            if edge["source_domain"] == edge["target_domain"]:
                continue
            target_score = _clamp_score(mastery.get(edge["to"], 0.0))
            cross_edges.append(
                {
                    "from": edge["from"],
                    "to": edge["to"],
                    "type": "cross_domain_prerequisite",
                    "weight": round(1.0 + max(0.0, 0.7 - target_score) + load * 0.12, 3),
                    "similarity": None,
                    "source_domain": edge["source_domain"],
                    "target_domain": edge["target_domain"],
                    "reason": (
                        f"图谱显示「{edge['from']}」是「{edge['to']}」的跨域前置，"
                        f"优先补齐{_domain_label(edge['source_domain'])}基础"
                    ),
                }
            )

    semantic_edges = sorted(semantic_edges, key=lambda edge: (-edge["similarity"], edge["from"], edge["to"]))[:24]
    cross_edges = sorted(cross_edges, key=lambda edge: (edge["weight"], edge["from"], edge["to"]))[:24]
    similarity_log = sorted(similarity_log, key=lambda item: (-item["similarity"], item["source"], item["target"]))[:12]

    nodes = []
    for concept in ordered_concepts:
        domain = _concept_domain(concept, resource_index)
        nodes.append(
            {
                "id": concept,
                "concept": concept,
                "domain": domain,
                "domain_label": _domain_label(domain),
                "tier": tiers.get(concept, 0),
                "mastery": round(_clamp_score(mastery.get(concept, 0.0)), 2),
                "tags": sorted(_concept_tags(concept, resource_index))[:10],
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
            "similarity_log": similarity_log,
            "resource_concept_count": len(resource_index),
            "cognitive_load": round(load, 2),
            "frustration": round(affect, 2),
        },
    }


def astar_search(
    start: str,
    target: str,
    adjacency: dict[str, list[tuple[str, float]]],
    tiers: dict[str, int],
    mastery: dict[str, float],
    threshold: float,
    load: float,
) -> tuple[list[str], float] | None:
    """通用 A* 启发式寻路算法。"""
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


def suggest_cross_domain_supports(
    cross_graph: dict[str, Any],
    route_concepts: list[str] | tuple[str, ...],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    route_set = set(route_concepts)
    node_lookup = {node["concept"]: node for node in cross_graph.get("nodes", [])}
    mastery = {node["concept"]: node.get("mastery", 0.0) for node in cross_graph.get("nodes", [])}
    tiers = {node["concept"]: node.get("tier", 0) for node in cross_graph.get("nodes", [])}
    cognitive_load = cross_graph.get("metadata", {}).get("cognitive_load", 0.45)
    
    # 建立跨学科邻接图
    cross_adjacency: dict[str, list[tuple[str, float]]] = {}
    for node in cross_graph.get("nodes", []):
        cross_adjacency[node["concept"]] = []
    for edge in cross_graph.get("edges", []):
        cross_adjacency.setdefault(edge["from"], []).append((edge["to"], float(edge["weight"])))
        
    supports = []
    threshold = 0.7
    
    # 针对路线中掌握度低于 threshold 的概念
    for target in route_concepts:
        if target not in node_lookup:
            continue
        target_node = node_lookup[target]
        target_domain = target_node.get("domain", "")
        
        # 寻找其他领域已掌握或较好掌握的起点 (mastery >= 0.5)
        candidates = []
        for start_concept, start_node in node_lookup.items():
            if start_concept == target:
                continue
            if start_node.get("domain", "") == target_domain:
                continue
            if mastery.get(start_concept, 0.0) >= 0.5:
                candidates.append(start_concept)
                
        # 对每个已掌握的跨学科起点运行 A* 寻路
        for start in candidates:
            res = astar_search(
                start=start,
                target=target,
                adjacency=cross_adjacency,
                tiers=tiers,
                mastery=mastery,
                threshold=threshold,
                load=cognitive_load,
            )
            if res:
                path, cost = res
                source_node = node_lookup[start]
                supports.append(
                    {
                        "concept": start,
                        "target": target,
                        "domain": source_node.get("domain", ""),
                        "domain_label": source_node.get("domain_label", ""),
                        "target_domain": target_node.get("domain", ""),
                        "target_domain_label": target_node.get("domain_label", ""),
                        "mastery": round(mastery.get(start, 0.7), 2),
                        "weight": round(cost, 3),
                        "reason": f"A* 寻得跨学科类比支撑路径: {' → '.join(path)} (A* 路径代价值: {cost:.2f})",
                    }
                )
                
    # 如果 A* 没有寻得任何路径，使用原来的直接跨学科边提取作为兜底
    if not supports:
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
            
    # 按路径代价值（权重）排序，返回前 limit 个支持
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


def _repair_route_topology(dag: dict[str, list[str]], route: list[str], tiers: dict[str, int]) -> list[str]:
    """Applies Kahn's algorithm / topological sort to repair a route that violates dependency order."""
    nodes_set = set(route)
    sub_dag: dict[str, list[str]] = {node: [] for node in nodes_set}
    in_degree = {node: 0 for node in nodes_set}

    for concept in nodes_set:
        for prereq in dag.get(concept, []) or []:
            if prereq in nodes_set:
                sub_dag[prereq].append(concept)
                in_degree[concept] += 1

    queue = [node for node in nodes_set if in_degree[node] == 0]
    queue.sort(key=lambda node: (tiers.get(node, 99), node))

    reordered: list[str] = []
    while queue:
        queue.sort(key=lambda node: (tiers.get(node, 99), node))
        curr = queue.pop(0)
        reordered.append(curr)
        for neighbor in sub_dag[curr]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(reordered) < len(route):
        remaining = nodes_set - set(reordered)
        reordered.extend(sorted(remaining, key=lambda node: (tiers.get(node, 99), node)))

    return reordered


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
    
    # 过滤出存在于课程图谱中的真实目标概念，供 A* 寻路进行精确终点匹配
    real_goals = {g for g in goal_set if g in concepts}
    primary_goal = sorted(real_goals)[0] if real_goals else (sorted(goal_set)[0] if goal_set else "")
    
    goal_related = set(goal_set)
    for goal in goal_set:
        if goal in concepts:
            goal_related.update(_ancestors_for_target(dag, goal))
    for weak in weak_set:
        if weak in concepts:
            goal_related.update(_ancestors_for_target(dag, weak))
            
    # 如果目标集合不为空，但全是非物理概念（广泛诉求，如期末复习冲刺），则自动关联度数最高的核心骨干节点，维持路线连续性
    if goal_set and not real_goals:
        core_backbones = sorted(concepts, key=lambda c: (-len(dag.get(c, []) or []), c))
        goal_related.update(core_backbones[:3])

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
        return astar_search(
            start=start,
            target=target,
            adjacency=adjacency,
            tiers=tiers,
            mastery=mastery,
            threshold=threshold,
            load=load,
        )

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

        # 降维平替（有向依赖前置子图）：利用已有的深度优先拓扑展开逻辑，直接以 target 为起点生成符合前置依赖的拓扑排序路径
        best_path = expand_required_prereqs([target])
        best_cost = route_cost(best_path)

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
            "planner_review": {
                "agent": "Planner Agent",
                "decision": "no_route",
                "personalized_guidance": "当前图谱中没有足够前置边生成可执行路线。",
                "action_dispatch": [],
                "llm_backend": "not-called",
            },
            "session_plan": {"today_concepts": [], "today_minutes": 0, "stage_total_minutes": 0},
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

    # Audit and repair topology before building node payload
    audit = _audit_route_topology(dag, route)
    if not audit.get("passed"):
        route = _repair_route_topology(dag, route, tiers)
        audit = _audit_route_topology(dag, route)
        audit["self_healed"] = True
    else:
        audit["self_healed"] = False

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
    resource_count = sum(1 for node in route_nodes if node.get("resource", {}).get("has_animation"))
    session_plan = _build_session_plan(route_nodes, total_minutes)
    planner_review = _review_candidate_route_with_planner(
        candidate_path=candidate_path,
        route_nodes=route_nodes,
        target=selected["target"],
        final_goal=final_goal,
        cognitive_load=load,
        frustration=affect,
        audit=audit,
        session_plan=session_plan,
    )
    
    # 运行 A* 寻路寻找已掌握起点到本阶段目标的辅助最优路径，用于 Swarm Terminal 日志的可观测性呈现
    starts = [c for c, m in mastery.items() if m >= 0.5 and c in concepts]
    astar_path_desc = ""
    if starts and selected["target"]:
        start_node = sorted(starts, key=lambda c: (tiers.get(c, 0), c))[0]
        if start_node != selected["target"]:
            res = astar(start_node, selected["target"])
            if res:
                path, cost = res
                astar_path_desc = f"{' → '.join(path)} (代价值: {cost:.2f})"

    planner_trace = _build_planner_trace(
        candidate_path,
        route,
        selected["target"],
        resource_count,
        audit,
        graph_metadata,
        planner_review,
        astar_path_desc=astar_path_desc,
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
            "generated_by": "Hybrid Routing Engine (DFS Topology + A* Scaffolding)",
        },
        "nodes": route_nodes,
        "edges": route_edges,
        "topology_audit": audit,
        "planner_trace": planner_trace,
        "planner_review": planner_review,
        "session_plan": session_plan,
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
            "按前置依赖边展开搜索（DFS 拓扑展开），保障硬性依赖安全性",
            "在跨学科/语义关联图上运行 A* 启发式寻路，寻找最小认知负荷过渡支架",
            "结合 Planner Agent 基于学生画像进行二次调度与教学活动节奏二次审核",
            f"最终目标「{final_goal}」被拆为当前阶段目标「{selected['target']}」" if is_staged else "当前路线可直接推进到目标概念",
        ],
        "constraints": {
            "mastery_threshold": threshold,
            "max_steps": max_steps,
            "cognitive_load": round(load, 2),
            "frustration": round(affect, 2),
        },
    }


def _build_session_plan(route_nodes: list[dict[str, Any]], total_minutes: int) -> dict[str, Any]:
    today_concepts = []
    today_minutes = 0
    for node in route_nodes:
        node_minutes = int(node.get("estimated_minutes") or 0)
        if today_concepts and today_minutes + node_minutes > 90:
            break
        today_concepts.append(node["concept"])
        today_minutes += node_minutes
        if today_minutes >= 60:
            break
    if not today_concepts and route_nodes:
        today_concepts = [route_nodes[0]["concept"]]
        today_minutes = int(route_nodes[0].get("estimated_minutes") or 30)

    return {
        "today_concepts": today_concepts,
        "today_minutes": today_minutes,
        "stage_total_minutes": total_minutes,
        "rhythm": "今日先完成 1-2 个低掌握节点，后续阶段继续承接最终目标",
        "max_daily_minutes": 90,
    }

def _review_candidate_route_with_planner(
    *,
    candidate_path: list[str],
    route_nodes: list[dict[str, Any]],
    target: str,
    final_goal: str,
    cognitive_load: float,
    frustration: float,
    audit: dict[str, Any],
    session_plan: dict[str, Any],
) -> dict[str, Any]:
    action_dispatch = [
        {
            "concept": node["concept"],
            "action": node["action"],
            "mode": node.get("planner_mode", "Guided Practice"),
            "reason": node.get("reason", ""),
        }
        for node in route_nodes
    ]
    fallback_guidance = (
        f"先把当前阶段目标「{target}」拆成 {len(route_nodes)} 个可执行节点；"
        f"今天建议只完成 {'、'.join(session_plan.get('today_concepts') or [])}，"
        f"再根据复习反馈决定是否继续推进到「{final_goal}」。"
    )
    llm_backend = "deterministic-fallback"
    guidance = fallback_guidance
    try:
        from llm_client import DEFAULT_LLM

        llm_backend = getattr(DEFAULT_LLM, "__class__", type(DEFAULT_LLM)).__name__
        prompt = (
            f"候选路线: {' -> '.join(candidate_path)}\n"
            f"当前阶段目标: {target}\n最终目标: {final_goal}\n"
            f"认知负荷: {cognitive_load:.2f}; 挫败感: {frustration:.2f}\n"
            f"今日切片: {session_plan.get('today_concepts', [])}\n"
            "请用一句话审核路线，并说明今天的执行建议。"
        )
        guidance = DEFAULT_LLM.generate(
            "你是 EduMatrix 的路径规划师，负责审核候选路线，不改变拓扑顺序。",
            prompt,
            role="路径规划师",
        )
    except Exception:
        guidance = fallback_guidance

    return {
        "agent": "Planner Agent",
        "decision": "accepted" if audit.get("passed") else "needs_topology_repair",
        "llm_backend": llm_backend,
        "personalized_guidance": guidance,
        "action_dispatch": action_dispatch,
        "today_slice": session_plan,
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
    planner_review: dict[str, Any] | None = None,
    astar_path_desc: str = "",
) -> list[str]:
    backend = (planner_review or {}).get("llm_backend", "deterministic-fallback")
    decision = (planner_review or {}).get("decision", "accepted")
    passed_label = "通过（已自动重排修正）" if audit.get("self_healed") else ("通过" if audit.get("passed") else "需修正")
    trace = [
        f"[A* Engine] 生成候选路线草案：{' -> '.join(candidate_path)}",
        f"[Graph Fusion] 已融合 RAG 边 {graph_metadata.get('rag_edges_added', 0)} 条、动画资源边 {graph_metadata.get('animation_edges_added', 0)} 条",
    ]
    if astar_path_desc:
        trace.append(f"[A* Engine] 寻得学科关联辅助路径：{astar_path_desc}")
    trace.extend([
        f"[Resource Router] 路线中 {resource_count} 个节点匹配到本地动画资源",
        f"[Topology Checker] 拓扑审计{passed_label}，检查边 {audit.get('checked_edges', 0)} 条",
        f"[Planner Agent] {backend} 审核结果 {decision}：确认目标「{target}」，将草案润色为 {len(route)} 步可执行学习动作",
    ])
    return trace


class PathPlanner:
    """Facade for member 2 micro-graph construction and A* path planning."""

    def __init__(self, dag: dict[str, list[str]]):
        self.dag = dag

    def _active_inputs(self) -> tuple[dict[str, list[str]], dict[str, dict[str, Any]], dict[str, Any], dict[str, int]]:
        global _GRAPH_CACHE
        with _GRAPH_CACHE_LOCK:
            if _GRAPH_CACHE["valid"]:
                return (
                    _GRAPH_CACHE["active_dag"],
                    _GRAPH_CACHE["resource_index"],
                    _GRAPH_CACHE["graph_metadata"],
                    _GRAPH_CACHE["active_tiers"]
                )
            
            # Cache miss: compute and populate cache
            resource_index = _animation_index()
            active_dag, graph_metadata = build_resource_aware_dag(self.dag, resource_index=resource_index)
            active_tiers = compute_concept_tiers(active_dag)
            
            _GRAPH_CACHE["active_dag"] = active_dag
            _GRAPH_CACHE["resource_index"] = resource_index
            _GRAPH_CACHE["graph_metadata"] = graph_metadata
            _GRAPH_CACHE["active_tiers"] = active_tiers
            _GRAPH_CACHE["valid"] = True
            
            return active_dag, resource_index, graph_metadata, active_tiers

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
