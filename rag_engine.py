from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import replace
from pathlib import Path
from typing import Any
import math
import re
import concurrent.futures
from datetime import datetime, timedelta, timezone

from config import CONFIG
from app.cross_language_retrieval import english_lexical_score, expand_ml_query
from embedding_models import EMBEDDINGS
from knowledge_base import load_evidence_from_file, load_seed_evidence
from math_utils import cosine_similarity
from models import Evidence, EvidenceModality, GraphContext, RetrievalBundle
from observability import TELEMETRY, timed_span
from vector_store import create_index
from vector_store import InMemoryVectorIndex, VectorIndex

PROJECT_ROOT = Path(__file__).resolve().parent
PATCHES_ROOT = PROJECT_ROOT / "data" / "patches"

def _tokens(text: str) -> set[str]:
    lower = text.lower()
    words = set(re.findall(r"[a-zA-Z0-9_+\-.]+|[\u4e00-\u9fff]{2,}", lower))
    chinese = re.findall(r"[\u4e00-\u9fff]", text)
    words.update("".join(chinese[i : i + 2]) for i in range(max(0, len(chinese) - 1)))
    return {word for word in words if word.strip()}


class VectorMath:
    @staticmethod
    def dot_product(v1: list[float], v2: list[float]) -> float:
        return sum(x * y for x, y in zip(v1, v2))

    @staticmethod
    def cosine_similarity(v1: list[float], v2: list[float]) -> float:
        dot = sum(a * b for a, b in zip(v1, v2))
        n1 = math.sqrt(sum(a * a for a in v1))
        n2 = math.sqrt(sum(b * b for b in v2))
        if n1 == 0.0 or n2 == 0.0:
            return 0.0
        return max(-1.0, min(1.0, dot / (n1 * n2)))


def _encode_vector(text: str) -> list[float]:
    return list(EMBEDDINGS.embed(text))


def colpali_maxsim(query: str, evidence: Evidence) -> float:
    tokens = [t.strip().lower() for t in re.split(r"[，。！、\s]+", query) if t.strip()]
    if not tokens:
        tokens = [query]
    
    q_vecs = [_encode_vector(t) for t in tokens]
    
    patches = [
        evidence.title,
        evidence.content,
        " ".join(evidence.tags),
        " ".join(evidence.anchors)
    ]
    patches = [p for p in patches if p.strip()]
    if not patches:
        patches = [evidence.content]
        
    d_vecs = [_encode_vector(p) for p in patches]
    
    total_maxsim = 0.0
    for q_v in q_vecs:
        max_sim = max(VectorMath.dot_product(q_v, d_v) for d_v in d_vecs)
        total_maxsim += max_sim
        
    avg_maxsim = total_maxsim / len(q_vecs) if q_vecs else 0.0
    
    anchor_boost = sum(1 for anchor in evidence.anchors if anchor and anchor in query) * 0.18
    tag_boost = sum(1 for tag in evidence.tags if tag and tag.lower() in query.lower()) * 0.12
    
    return min(1.0, max(0.0, avg_maxsim + anchor_boost + tag_boost))


def jinaclip_text_similarity(query: str, evidence: Evidence) -> float:
    q_vec = _encode_vector(query)
    doc_text = " ".join((evidence.title, evidence.content, " ".join(evidence.tags), " ".join(evidence.anchors)))
    d_vec = _encode_vector(doc_text)
    
    cos_sim = VectorMath.cosine_similarity(q_vec, d_vec)
    
    anchor_boost = sum(1 for anchor in evidence.anchors if anchor and anchor in query) * 0.18
    tag_boost = sum(1 for tag in evidence.tags if tag and tag.lower() in query.lower()) * 0.12
    
    return min(1.0, max(0.0, cos_sim + anchor_boost + tag_boost))


def _similarity(query: str, item: Evidence) -> float:
    query_tokens = _tokens(query)
    doc_text = _evidence_text(item)
    doc_tokens = _tokens(doc_text)
    if not query_tokens or not doc_tokens:
        return 0.0
    overlap = len(query_tokens & doc_tokens)
    jaccard = overlap / len(query_tokens | doc_tokens)
    embedding_score = EMBEDDINGS.score(query, doc_text)
    jina_score = jinaclip_text_similarity(query, item)
    anchor_boost = sum(1 for anchor in item.anchors if anchor and anchor in query) * 0.18
    tag_boost = sum(1 for tag in item.tags if tag and tag.lower() in query.lower()) * 0.12
    return min(1.0, embedding_score * 0.35 + jina_score * 0.35 + jaccard * 0.20 + anchor_boost + tag_boost)


def _course_similarity(query: str, item: Evidence) -> float:
    expansion = expand_ml_query(query)
    scoring_query = expansion.expanded_query
    query_tokens = _tokens(scoring_query)
    doc_text = _evidence_text(item)
    doc_tokens = _tokens(doc_text)
    if not query_tokens or not doc_tokens:
        return 0.0
    overlap = len(query_tokens & doc_tokens)
    jaccard = overlap / len(query_tokens | doc_tokens)
    query_coverage = overlap / len(query_tokens)
    embedding_score = EMBEDDINGS.score(scoring_query, doc_text)
    jina_score = jinaclip_text_similarity(scoring_query, item)
    anchor_boost = sum(1 for anchor in item.anchors if anchor and anchor in query) * 0.18
    tag_boost = sum(1 for tag in item.tags if tag and tag.lower() in query.lower()) * 0.12
    lexical_score = english_lexical_score(expansion, item.content)
    return min(
        1.0,
        embedding_score * 0.18
        + jina_score * 0.18
        + jaccard * 0.12
        + query_coverage * 0.32
        + lexical_score * 0.20
        + anchor_boost
        + tag_boost,
    )


def _evidence_text(item: Evidence) -> str:
    return " ".join((item.title, item.content, " ".join(item.tags), " ".join(item.anchors)))


class GraphRAG:
    def __init__(self, repository: Any | None = None) -> None:
        self.nodes: set[str] = set()
        self.forward: dict[str, set[str]] = defaultdict(set)
        self.reverse: dict[str, set[str]] = defaultdict(set)
        self._build_professional_knowledge_graph()
        # === F1 修复与启动并网：若 repository 为 None，自动拉取数据库中的默认图数据库连接以加载自生长边 ===
        if repository is None:
            try:
                from app.utils.graph_builder import create_graph_repository
                repository = create_graph_repository()
            except Exception as exc:
                print(f"  [GraphRAG] 自动加载默认图数据库仓库失败: {exc}")
        # === F1 修复：从动态图谱仓库加载边，与硬编码边合并 ===
        if repository is not None:
            self._load_dynamic_edges(repository)

    def _add_edge(self, source: str, target: str) -> None:
        self.nodes.add(source)
        self.nodes.add(target)
        self.forward[source].add(target)
        self.reverse[target].add(source)

    def _load_dynamic_edges(self, repository: Any) -> None:
        """F1 修复：从动态图谱仓库（Neo4j/内存）加载边，与硬编码图谱合并。"""
        try:
            # InMemoryGraphRepository 和 Neo4jGraphRepository 都有 edges 属性或可用 query_prerequisites
            if hasattr(repository, "edges"):
                for source, target, relation in repository.edges:
                    if relation == "PREREQUISITE_OF":
                        self._add_edge(source, target)
            elif hasattr(repository, "query_prerequisites"):
                # 如果仓库支持查询，尝试遍历所有已知节点
                if hasattr(repository, "nodes"):
                    for node in repository.nodes:
                        result = repository.query_prerequisites(node)
                        for prereq in result.prerequisites:
                            self._add_edge(prereq, node)
                        for down in result.downstream:
                            self._add_edge(node, down)
        except Exception as exc:
            print(f"  [GraphRAG] 动态图谱加载失败，使用硬编码图谱: {exc}")

    def _build_professional_knowledge_graph(self) -> None:
        edges = [
            ("机器学习", "监督学习"), ("机器学习", "数据预处理"), ("机器学习", "模型评估"),
            ("机器学习", "交叉验证"),
            ("Python编程", "数据预处理"), ("线性代数", "向量表示"), ("概率统计", "模型评估"),
            ("概率统计", "朴素贝叶斯"), ("微积分", "梯度下降"), ("数据预处理", "特征工程"),
            ("特征工程", "监督学习"), ("监督学习", "线性回归"), ("监督学习", "逻辑回归"),
            ("监督学习", "决策树"), ("监督学习", "支持向量机"), ("监督学习", "朴素贝叶斯"),
            ("线性回归", "损失函数"), ("逻辑回归", "分类阈值"), ("分类阈值", "模型评估"),
            ("模型评估", "混淆矩阵"), ("决策树", "过拟合"), ("支持向量机", "间隔最大化"),
            ("损失函数", "梯度下降"), ("过拟合", "正则化"), ("正则化", "模型泛化"),
            ("模型评估", "交叉验证"), ("交叉验证", "模型选择"), ("模型泛化", "模型选择"),
            ("模型选择", "机器学习项目实践"), ("线性代数", "矩阵乘法"), ("矩阵乘法", "张量运算"),
            ("张量运算", "特征图"), ("微积分", "导数"), ("导数", "偏导数"),
            ("偏导数", "链式法则"), ("链式法则", "反向传播"), ("损失函数", "反向传播"),
            ("反向传播", "梯度下降"), ("卷积核", "卷积运算"), ("步长", "卷积运算"),
            ("填充", "卷积运算"), ("卷积运算", "特征图"), ("特征图", "池化层"),
            ("池化层", "最大池化"), ("池化层", "平均池化"), ("池化层", "全连接层"),
            ("激活函数", "卷积神经网络"), ("全连接层", "卷积神经网络"),
            ("反向传播", "神经网络"), ("梯度下降", "神经网络"),
            ("神经网络", "注意力机制"), ("神经网络", "卷积神经网络"),
            ("卷积核", "卷积神经网络"), ("池化层", "卷积神经网络"),
            ("注意力机制", "Transformer"), ("反向传播", "Transformer"),
        ]
        for source, target in edges:
            self._add_edge(source, target)

    def _normalize_target(self, target: str) -> str:
        aliases = {
            "Pooling": "池化层", "pooling": "池化层", "池化": "池化层",
            "CNN": "卷积神经网络", "Feature Map": "特征图", "ReLU": "激活函数",
            "ML": "机器学习", "机器学习": "机器学习", "machine learning": "机器学习",
            "Machine Learning": "机器学习", "分类": "逻辑回归", "回归": "线性回归",
            "过拟合": "过拟合",
        }
        if target in self.nodes:
            return target
        for alias, node in aliases.items():
            if alias in target:
                return node
        for node in self.nodes:
            if target in node or node in target:
                return node
        return target

    def _ancestors(self, target: str) -> set[str]:
        visited: set[str] = set()
        queue = deque(self.reverse.get(target, set()))
        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            queue.extend(self.reverse.get(node, set()))
        return visited

    def _descendants(self, target: str, depth: int = 1) -> set[str]:
        visited: set[str] = set()
        queue = deque((child, 1) for child in self.forward.get(target, set()))
        while queue:
            node, current_depth = queue.popleft()
            if node in visited or current_depth > depth:
                continue
            visited.add(node)
            queue.extend((child, current_depth + 1) for child in self.forward.get(node, set()))
        return visited

    def get_path(self, target: str) -> list[str]:
        target = self._normalize_target(target)
        if target not in self.nodes:
            return [target]
        selected = self._ancestors(target) | {target}
        indegree = {node: 0 for node in selected}
        for source in selected:
            for dest in self.forward.get(source, set()):
                if dest in selected:
                    indegree[dest] += 1
        queue = deque(sorted(node for node, degree in indegree.items() if degree == 0))
        ordered: list[str] = []
        while queue:
            node = queue.popleft()
            ordered.append(node)
            for dest in sorted(self.forward.get(node, set())):
                if dest not in indegree:
                    continue
                indegree[dest] -= 1
                if indegree[dest] == 0:
                    queue.append(dest)
        return ordered

    def get_context(self, target: str) -> GraphContext:
        normalized = self._normalize_target(target)
        path = tuple(self.get_path(normalized))
        prereq_edges = []
        for source in path:
            for dest in self.forward.get(source, set()):
                if dest in path:
                    prereq_edges.append((source, dest))
        downstream = tuple((normalized, child) for child in sorted(self.forward.get(normalized, set())))
        return GraphContext(
            target=normalized,
            learning_path=path,
            prerequisite_edges=tuple(prereq_edges),
            downstream_edges=downstream,
        )

    def get_subgraph_context(self, target: str) -> str:
        return self.get_context(target).to_prompt()


class VisRAG:
    def __init__(self, index: VectorIndex | None = None) -> None:
        seed_evidence = load_seed_evidence()
        self.patch_db = self._verified_image_evidence(tuple(seed_evidence))
        self.index = index or InMemoryVectorIndex("visrag-image-patches")
        self.index.upsert(self.patch_db)

    @staticmethod
    def _verified_image_evidence(items: tuple[Evidence, ...]) -> tuple[Evidence, ...]:
        project_root = PROJECT_ROOT
        patches_root = PATCHES_ROOT.resolve()
        verified = []
        for item in items:
            if item.modality != EvidenceModality.IMAGE or not item.source.strip():
                continue
            raw_ref = str(item.metadata.get("raw_image_ref", "")).strip()
            if not raw_ref:
                continue
            image_path = Path(raw_ref)
            if not image_path.is_absolute():
                image_path = project_root / image_path
            try:
                image_path.resolve().relative_to(patches_root)
            except ValueError:
                continue
            if image_path.is_file():
                verified.append(item)
        return tuple(verified)

    def search(self, query: str, top_k: int = 3) -> list[dict[str, object]]:
        ranked = self.search_evidence(query, top_k)
        return [
            {"text": item.content, "metadata": {"id": item.id, "img": item.metadata.get("raw_image_ref")}}
            for item in ranked
        ]

    def search_evidence(self, query: str, top_k: int = 3) -> tuple[Evidence, ...]:
        vector_hits = self.index.search(query, top_k=max(top_k * 3, top_k))
        ranked = sorted((item.with_score(colpali_maxsim(query, item)) for item in vector_hits), key=lambda item: item.score, reverse=True)
        return tuple(item for item in ranked[:top_k] if item.score > 0.0)


class TextKnowledgeIndex:
    def __init__(self, index: VectorIndex | None = None) -> None:
        file_evidence = load_seed_evidence()
        self.documents = ()
        if file_evidence:
            self.documents = tuple(e for e in file_evidence if e.modality == EvidenceModality.TEXT)
        if not self.documents:
            self.documents = self._builtin_text_evidence()
        self.index = index or InMemoryVectorIndex("text-knowledge")
        self.index.upsert(self.documents)

    @staticmethod
    def _builtin_text_evidence() -> tuple[Evidence, ...]:
        return (
            Evidence(id="TXT_POOL_DEF_01", title="池化层定义与作用", content="池化层对特征图进行局部聚合，常见形式包括最大池化和平均池化，可降低空间维度并提升局部平移鲁棒性。", modality=EvidenceModality.TEXT, source="课程知识库:CNN/Pooling", tags=("池化层","特征图","最大池化","平均池化"), anchors=("降采样","局部聚合","平移鲁棒性")),
            Evidence(id="TXT_POOL_ERR_01", title="池化层易错点", content="最大池化取窗口最大值，平均池化取窗口均值；讲义、代码和导图必须保持同一种池化类型，否则会造成跨模态不一致。", modality=EvidenceModality.TEXT, source="课程知识库:CNN/Misconceptions", tags=("池化层","最大池化","平均池化","易错点"), anchors=("MaxPool2d","AvgPool2d","一致性")),
            Evidence(id="TXT_CONV_PRE_01", title="池化层前置知识", content="池化层通常接在卷积层生成的特征图之后，因此理解卷积核、步长和特征图是理解池化层的前置条件。", modality=EvidenceModality.TEXT, source="课程知识库:CNN/Prerequisite", tags=("卷积核","步长","特征图","池化层"), anchors=("前置知识","特征图")),
            Evidence(id="TXT_BACKPROP_01", title="反向传播基本逻辑", content="反向传播基于链式法则将损失函数的梯度从输出层传回参数层，是神经网络训练的核心算法。", modality=EvidenceModality.TEXT, source="课程知识库:Optimization/Backprop", tags=("反向传播","链式法则","梯度下降"), anchors=("梯度","损失函数")),
            Evidence(id="TXT_ML_OVERVIEW_01", title="机器学习导论课程边界", content="机器学习导论课程覆盖数据预处理、监督学习、回归、分类、模型评估、过拟合与正则化，并通过实践项目训练完整建模流程。", modality=EvidenceModality.TEXT, source="机器学习课程知识库:Overview", tags=("机器学习","监督学习","模型评估","实践项目"), anchors=("数据预处理","模型泛化","交叉验证")),
            Evidence(id="TXT_ML_PREPROCESS_01", title="数据预处理与特征工程", content="数据预处理包括缺失值处理、数值缩放、类别编码和训练测试划分；特征工程决定模型能否从数据中学习有效规律。", modality=EvidenceModality.TEXT, source="机器学习课程知识库:Preprocessing", tags=("数据预处理","特征工程","训练测试划分"), anchors=("missing values","scaling","encoding","train_test_split")),
            Evidence(id="TXT_ML_LOGREG_01", title="逻辑回归与分类阈值", content="逻辑回归使用 sigmoid 将线性组合映射为概率，分类阈值会影响 precision、recall 与 F1，不应只看 accuracy。", modality=EvidenceModality.TEXT, source="机器学习课程知识库:Classification", tags=("逻辑回归","分类阈值","模型评估"), anchors=("sigmoid","precision","recall","F1")),
            Evidence(id="TXT_ML_OVERFIT_01", title="过拟合、正则化与交叉验证", content="过拟合表现为训练集效果好但验证集效果差；可通过 L1/L2 正则化、交叉验证、早停和降低模型复杂度提升泛化能力。", modality=EvidenceModality.TEXT, source="机器学习课程知识库:Generalization", tags=("过拟合","正则化","交叉验证","模型泛化"), anchors=("L1","L2","validation","generalization")),
            Evidence(id="TXT_ML_EVAL_01", title="模型评估指标", content="分类任务需结合混淆矩阵理解 accuracy、precision、recall、F1 和 ROC-AUC；类别不均衡时 accuracy 可能产生误导。", modality=EvidenceModality.TEXT, source="机器学习课程知识库:Evaluation", tags=("模型评估","混淆矩阵","分类指标"), anchors=("accuracy","precision","recall","F1","ROC-AUC")),
        )

    def search(self, query: str, top_k: int = 4) -> tuple[Evidence, ...]:
        vector_hits = self.index.search(query, top_k=max(top_k * 3, top_k))
        ranked = sorted((item.with_score(_similarity(query, item)) for item in vector_hits), key=lambda item: item.score, reverse=True)
        return tuple(item for item in ranked[:top_k] if item.score > 0.0)


def pre_filter_index(
    index: Any,
    query: str,
    query_with_graph: str,
    doc_constraints: list[str] | str | None,
    top_k: int,
    *,
    course_id: str | None = None,
    owner_id: str = "",
    allow_cross_course: bool = False,
) -> list[Evidence]:
    """Helper to pre-filter items of an index by doc_constraints and compute similarities."""
    matches = []
    
    # Standardize doc_constraints to a list of lowercased strings
    constraints_list = []
    if doc_constraints:
        if isinstance(doc_constraints, str):
            constraints_list = [doc_constraints.lower()]
        elif isinstance(doc_constraints, list):
            constraints_list = [c.lower() for c in doc_constraints if c]

    # If it is a FAISSIndexSet, recurse on each of its loaded indexes
    if hasattr(index, "indexes") and isinstance(index.indexes, dict):
        for sub_index in index.indexes.values():
            matches.extend(
                pre_filter_index(
                    sub_index,
                    query,
                    query_with_graph,
                    constraints_list,
                    top_k,
                    course_id=course_id,
                    owner_id=owner_id,
                    allow_cross_course=allow_cross_course,
                )
            )
        return sorted(matches, key=lambda x: x.score, reverse=True)[:top_k]

    # For InMemoryVectorIndex or FaissVectorIndex, get items from _items
    items = []
    if hasattr(index, "_items") and isinstance(index._items, dict):
        items = list(index._items.values())
    elif hasattr(index, "documents") and isinstance(index.documents, tuple):
        items = list(index.documents)

    for item in items:
        visibility = item.metadata.get("visibility")
        item_owner = str(item.metadata.get("owner_id") or "")
        item_course = str(item.metadata.get("course_id") or "")
        if visibility == "private" and (not owner_id or item_owner != owner_id):
            continue
        if course_id and not allow_cross_course:
            is_current_course = item_course == course_id
            is_authorized_private = visibility == "private" and item_owner == owner_id
            if not is_current_course and not is_authorized_private:
                continue
        source_val = (item.source or "").lower()
        title_val = (item.title or "").lower()
        # If constraints list is empty, treat as matching all items
        if not constraints_list or any(c in source_val or c in title_val for c in constraints_list):
            score_fn = _course_similarity if course_id else _similarity
            score = score_fn(query_with_graph, item)
            matches.append(item.with_score(score))

    return sorted(matches, key=lambda x: x.score, reverse=True)[:top_k]


class HybridRAGPipeline:
    def __init__(
        self,
        graph: GraphRAG | None = None,
        visual_index: VisRAG | None = None,
        text_index: TextKnowledgeIndex | None = None,
        faiss_indexes: FAISSIndexSet | None = None,
        formula_rag: Any | None = None,
    ) -> None:
        self.graph = graph or GraphRAG()
        self.visual_index = visual_index or VisRAG()
        self.faiss_indexes = faiss_indexes

        if faiss_indexes is not None:
            self.text_index = None
        else:
            self.text_index = text_index or TextKnowledgeIndex()

        self.user_index = InMemoryVectorIndex("user-documents")

        # === F2 修复：接入公式双轨检索 ===
        self.formula_rag = formula_rag
        if self.formula_rag is None:
            try:
                from app.utils.formula_rag import FormulaRAG, seed_formula_index
                _fr = FormulaRAG()
                seed_formula_index(_fr)
                self.formula_rag = _fr
            except Exception:
                self.formula_rag = None

    def ingest_user_documents(self, evidence: tuple[Evidence, ...], owner_id: str = "") -> None:
        if not evidence:
            return
        if not owner_id:
            raise ValueError("owner_id is required for user document ingestion")
        owned_evidence = tuple(
            replace(item, metadata={**item.metadata, "owner_id": owner_id, "visibility": "private"})
            for item in evidence
        )
        self.user_index.upsert(owned_evidence)
        TELEMETRY.record_metric("user_index.documents_ingested", len(evidence))

    def ingest_course_documents(
        self,
        evidence: tuple[Evidence, ...],
        course_id: str,
        course_metadata: dict[str, object] | None = None,
    ) -> None:
        if not evidence:
            return
        if not course_id:
            raise ValueError("course_id is required for course document ingestion")
        shared_metadata = course_metadata or {}
        course_evidence = tuple(
            replace(
                item,
                metadata={
                    **item.metadata,
                    **shared_metadata,
                    "owner_type": "course",
                    "owner_id": course_id,
                    "course_id": course_id,
                    "visibility": "public",
                },
            )
            for item in evidence
        )
        self.user_index.upsert(course_evidence)
        TELEMETRY.record_metric("course_index.documents_ingested", len(evidence))

    @staticmethod
    def _visible_user_evidence(items: list[Evidence], owner_id: str) -> list[Evidence]:
        return [
            item
            for item in items
            if item.metadata.get("visibility") == "public"
            or (owner_id and item.metadata.get("owner_id") == owner_id)
        ]

    def remove_user_documents(self, source: str, owner_id: str = "") -> None:
        if not owner_id:
            raise ValueError("owner_id is required for user document removal")
        matching_ids = [
            item.id
            for item in self.user_index._items.values()
            if item.source == source and item.metadata.get("owner_id") == owner_id
        ]
        removed = 0
        for item_id in matching_ids:
            if self.user_index._items.pop(item_id, None) is not None:
                removed += 1
        if removed > 0:
            TELEMETRY.record_metric("user_index.documents_removed", removed)

    def remove_course_documents(self, source: str, course_id: str) -> None:
        if not course_id:
            raise ValueError("course_id is required for course document removal")
        matching_ids = [
            item.id
            for item in self.user_index._items.values()
            if item.source == source
            and item.metadata.get("owner_type") == "course"
            and item.metadata.get("course_id") == course_id
        ]
        for item_id in matching_ids:
            self.user_index._items.pop(item_id, None)
        if matching_ids:
            TELEMETRY.record_metric("course_index.documents_removed", len(matching_ids))

    def retrieve(
        self,
        query: str,
        target: str | None = None,
        top_k: int = CONFIG.retrieval_top_k,
        profile: Any | None = None,
        disable_external: bool = False,
        doc_constraint: str | list[str] | None = None,
        course_id: str | None = None,
        allow_cross_course: bool = False,
        actor: Any | None = None,
    ) -> RetrievalBundle:
        # === 关键修复：延迟加载，打破循环导入 ===
        from web_search_api import search_arxiv

        # Mock mode is an explicit offline contract used by deterministic tests.
        # External fallback would make those tests depend on DNS and public APIs.
        disable_external = disable_external or CONFIG.llm_provider.lower() == "mock"
        
        with timed_span(TELEMETRY, "hybrid_rag.retrieve", top_k=top_k):
            # 清洗 query，避免将 "一键生成资源包: " 动作前缀和 "(知识点: ...)" 传入检索与向量搜索中
            cleaned_query = query.strip()
            if cleaned_query.startswith("一键生成资源包:"):
                cleaned_query = cleaned_query[8:].strip()
                import re
                cleaned_query = re.sub(r"\((?:知识点|指定概念):\s*.+?\)|\[指定概念:\s*.+?\]", "", cleaned_query).strip()

            out_of_domain = not self._is_ml_concept(cleaned_query)
            if out_of_domain:
                graph_context = GraphContext(
                    target=cleaned_query,
                    learning_path=(),
                    prerequisite_edges=(),
                    downstream_edges=(),
                )
                query_with_graph = cleaned_query
            else:
                target = target or self._infer_target(cleaned_query)
                graph_context = self.graph.get_context(target)
                # The legacy graph covers the original ML demo curriculum. A
                # scoped course owns a separate canonical KP graph, so injecting
                # the legacy fallback path (often pooling) would pollute ranking.
                query_with_graph = (
                    cleaned_query
                    if course_id
                    else f"{cleaned_query} {' '.join(graph_context.learning_path)}"
                )

            owner_id = getattr(profile, "student_id", "") if profile else ""
            prefilter_k = top_k * 5 if course_id else top_k

            # Course-grounded retrieval has one source of truth: ready
            # canonical DBSourceDocument/DBSourceRef rows.  The legacy in-memory
            # indexes remain available for general questions and explicitly
            # cross-course exploration, but cannot bypass the canonical status
            # and locator contract for a scoped course query.
            if course_id and not allow_cross_course:
                from app.canonical_retrieval import retrieve_canonical_sources
                from app.database import SessionLocal

                try:
                    with SessionLocal() as canonical_session:
                        canonical = retrieve_canonical_sources(
                            canonical_session,
                            course_id=course_id,
                            query=query_with_graph,
                            top_k=top_k,
                            actor=actor,
                        )
                except Exception as exc:
                    print(f"  [RAG] canonical course retrieval failed: {exc}")
                    canonical = {"evidence": (), "low_confidence": True}

                canonical_evidence = list(canonical.get("evidence") or ())
                # A learner's own notes are still valid auxiliary context, but
                # they are not presented as canonical course citations.
                personal = self._visible_user_evidence(
                    pre_filter_index(
                        self.user_index,
                        query,
                        query_with_graph,
                        doc_constraint,
                        top_k,
                        owner_id=owner_id,
                        allow_cross_course=True,
                    ),
                    owner_id,
                )
                personal = [
                    item.with_content(item.content)
                    for item in personal
                    if (
                        owner_id
                        and item.metadata.get("visibility") == "private"
                        and item.metadata.get("owner_id") == owner_id
                        and not item.metadata.get("canonical_source")
                    )
                ]
                final_evidence = sorted(
                    [*canonical_evidence, *personal],
                    key=lambda item: item.score,
                    reverse=True,
                )[:top_k]
                result = RetrievalBundle(
                    query=query,
                    target=graph_context.target,
                    graph_context=graph_context,
                    evidence=tuple(final_evidence),
                    low_confidence=bool(canonical.get("low_confidence")) and not personal,
                    out_of_domain=out_of_domain,
                )
                TELEMETRY.record_metric("retrieval.evidence_count", len(result.evidence), target=result.target)
                return result

            if doc_constraint:
                # Convert string or list to doc_constraints list
                doc_constraints = []
                if isinstance(doc_constraint, str):
                    doc_constraints = [doc_constraint]
                elif isinstance(doc_constraint, list):
                    doc_constraints = doc_constraint

                # 1. 前置过滤 visual_index
                candidates = pre_filter_index(
                    self.visual_index,
                    query,
                    query_with_graph,
                    doc_constraints,
                    prefilter_k,
                    course_id=course_id,
                    owner_id=owner_id,
                    allow_cross_course=allow_cross_course,
                )
                
                # 2. 前置过滤本地文本库
                if self.faiss_indexes is not None:
                    local_hits = pre_filter_index(
                        self.faiss_indexes,
                        query,
                        query_with_graph,
                        doc_constraints,
                        prefilter_k,
                        course_id=course_id,
                        owner_id=owner_id,
                        allow_cross_course=allow_cross_course,
                    )
                else:
                    local_hits = pre_filter_index(
                        self.text_index,
                        query,
                        query_with_graph,
                        doc_constraints,
                        prefilter_k,
                        course_id=course_id,
                        owner_id=owner_id,
                        allow_cross_course=allow_cross_course,
                    )
                candidates.extend(local_hits)
                
                # 3. 前置过滤 user_index
                user_hits = self._visible_user_evidence(
                    pre_filter_index(
                        self.user_index,
                        query,
                        query_with_graph,
                        doc_constraints,
                        prefilter_k,
                        course_id=course_id,
                        owner_id=owner_id,
                        allow_cross_course=allow_cross_course,
                    ),
                    owner_id,
                )
                candidates.extend(user_hits)
            elif course_id and not allow_cross_course:
                # Course-scoped retrieval filters before ranking so evidence from
                # another public course cannot crowd the current course out of top-k.
                candidates = pre_filter_index(
                    self.visual_index,
                    query,
                    query_with_graph,
                    None,
                    prefilter_k,
                    course_id=course_id,
                    owner_id=owner_id,
                )
                local_index = self.faiss_indexes if self.faiss_indexes is not None else self.text_index
                candidates.extend(
                    pre_filter_index(
                        local_index,
                        query,
                        query_with_graph,
                        None,
                        prefilter_k,
                        course_id=course_id,
                        owner_id=owner_id,
                    )
                )
                candidates.extend(
                    pre_filter_index(
                        self.user_index,
                        query,
                        query_with_graph,
                        None,
                        prefilter_k,
                        course_id=course_id,
                        owner_id=owner_id,
                    )
                )
            else:
                candidates = list(self.visual_index.search_evidence(query_with_graph, top_k=top_k))

                # === 核心修改区：并发拉取本地库和外网 arXiv ===
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                    # 提交本地检索任务
                    if self.faiss_indexes is not None:
                        future_local = executor.submit(self.faiss_indexes.search, query_with_graph, top_k)
                    else:
                        future_local = executor.submit(self.text_index.search, query_with_graph, top_k)
                    
                    # 仅在非禁用外部搜索时提交外网 arXiv 检索任务
                    future_arxiv = None
                    if not disable_external:
                        future_arxiv = executor.submit(search_arxiv, query, 2) 

                    # 收集结果
                    try:
                        candidates.extend(future_local.result())
                    except Exception as e:
                        print(f"  [RAG] Local search failed: {e}")
                    
                    if future_arxiv is not None:
                        try:
                            candidates.extend(future_arxiv.result())
                        except Exception as e:
                            print(f"  [RAG] arXiv search failed: {e}")
                # === 修改区结束 ===

                user_results = self._visible_user_evidence(
                    self.user_index.search(query_with_graph, top_k=top_k),
                    owner_id,
                )
                candidates.extend(user_results)

                # === 视频推荐数据接入 ===
                # Do not inject generic fallback videos for an out-of-domain
                # query: their fixed score could turn irrelevant evidence into
                # a false high-confidence retrieval result.
                if not disable_external and not out_of_domain:
                    try:
                        # 优先采用清洗后的具体查询进行检索，若无结果，再降级使用目标概念进行保底检索
                        videos = _search_videos_sync(cleaned_query, max_results=top_k)
                        if not videos and target:
                            videos = _search_videos_sync(target, max_results=top_k)
                            
                        for idx, v in enumerate(videos):
                            from models import EvidenceModality
                            ev = Evidence(
                                id=f"video_{idx}_{hash(v['url']) % 10000}",
                                title=v["title"],
                                content=f"视频地址={v['url']}｜描述={v['description']}",
                                modality=EvidenceModality.TEXT,
                                source=v["source"],
                                tags=(target or "视频",),
                                anchors=(v["title"],),
                            ).with_score(0.85)
                            candidates.append(ev)
                    except Exception as e:
                        print(f"  [RAG] Video search injection failed: {e}")

                # === F2 修复：公式双轨检索结果合并 ===
                # 仅在查询明确涉及公式/数学/偏导/损失函数等时触发，避免噪声注入
                _formula_keywords = ("公式", "偏导", "损失函数", "交叉熵", "sigmoid", "softmax", 
                                    "梯度下降", "MSE", "正则化", "导数", "微积分", "数学", "LaTeX")
                if self.formula_rag is not None and any(kw in query for kw in _formula_keywords):
                    try:
                        formula_evidence = self.formula_rag.search_as_evidence(query, top_k=min(2, top_k))
                        candidates.extend(formula_evidence)
                    except Exception as e:
                        print(f"  [RAG] Formula RAG search failed: {e}")

            if doc_constraint:
                doc_constraints = []
                if isinstance(doc_constraint, str):
                    doc_constraints = [doc_constraint]
                elif isinstance(doc_constraint, list):
                    doc_constraints = doc_constraint

                constraints_lower = [c.lower() for c in doc_constraints if c]
                if constraints_lower:
                    candidates = [
                        c for c in candidates
                        if any(l_c in (c.source or "").lower() or l_c in (c.title or "").lower() for l_c in constraints_lower)
                    ]

            dedup: dict[str, Evidence] = {}
            for item in candidates:
                existing = dedup.get(item.id)
                if existing is None or item.score > existing.score:
                    dedup[item.id] = item
            ranked = sorted(dedup.values(), key=lambda item: item.score, reverse=True)

            # 确保在有图像匹配时，保底保留高评分的图像证据，防止被学术文献或纯文本切片淹没
            from models import EvidenceModality
            images = [item for item in ranked if item.modality == EvidenceModality.IMAGE]
            
            final_evidence = []
            if images:
                final_evidence.append(images[0])
                if len(images) > 1 and top_k > 4:
                    final_evidence.append(images[1])

            pre_expansion_limit = prefilter_k if course_id else top_k
            for item in ranked:
                if len(final_evidence) >= pre_expansion_limit:
                    break
                if item not in final_evidence:
                    final_evidence.append(item)
                    
            # 按检索相关度得分重新排序
            final_evidence.sort(key=lambda item: item.score, reverse=True)

            # === 父子分块：子块匹配 + 父块替换（保持上下文完整性）===
            parent_expanded: dict[tuple[str, int], Evidence] = {}
            parent_best_score: dict[tuple[str, int], float] = {}
            for item in final_evidence:
                parent_content = item.metadata.get("parent_content", "")
                if parent_content:
                    parent_idx = item.metadata.get("parent_index", 0)
                    key = (item.source, parent_idx)
                    if key not in parent_expanded:
                        parent_expanded[key] = item.with_content(parent_content)
                        parent_best_score[key] = item.score
                    else:
                        # 保留同一父块中子块的最高分
                        if item.score > parent_best_score[key]:
                            parent_best_score[key] = item.score
                            parent_expanded[key] = parent_expanded[key].with_score(item.score)
                else:
                    dummy_key = (item.source, id(item))
                    parent_expanded[dummy_key] = item
            final_evidence = sorted(
                parent_expanded.values(), key=lambda x: x.score, reverse=True
            )
            if course_id:
                final_evidence = final_evidence[:top_k]

            # === F3 修复：学生画像感知的个性化重排序 ===
            if profile is not None and hasattr(profile, "concept_mastery"):
                final_evidence = self._personalized_rerank(final_evidence, profile, target)

            # 置信度评估：无证据或最高分低于阈值 -> 触发幻觉拒答
            top_score = final_evidence[0].score if final_evidence else 0.0
            if course_id and final_evidence:
                query_tokens = _tokens(expand_ml_query(cleaned_query).expanded_query)
                lexical_coverage = max(
                    (
                        len(query_tokens & _tokens(_evidence_text(item))) / len(query_tokens)
                        if query_tokens
                        else 0.0
                    )
                    for item in final_evidence
                )
                low_confidence = top_score < 0.20 or lexical_coverage < 0.08
            else:
                low_confidence = (not final_evidence) or top_score < 0.30

            result = RetrievalBundle(
                query=query,
                target=graph_context.target,
                graph_context=graph_context,
                evidence=tuple(final_evidence),
                low_confidence=low_confidence,
                out_of_domain=out_of_domain,
            )
            TELEMETRY.record_metric("retrieval.evidence_count", len(result.evidence), target=result.target)
            TELEMETRY.record_metric(
                "retrieval.image_count",
                sum(1 for item in result.evidence if item.modality == EvidenceModality.IMAGE),
                target=result.target,
            )
            return result

    def _personalized_rerank(self, evidence: list[Evidence], profile: Any, target: str | None) -> list[Evidence]:
        """F3 修复：基于学生概念掌握度的个性化重排序。
        - 薄弱知识点（mastery < 0.5）的证据 boost +15%
        - 已掌握知识点（mastery > 0.8）的证据 downweight -10%
        - 误概念相关证据额外 boost（概念辨析需求）
        """
        mastery = getattr(profile, "concept_mastery", {})
        misconception = getattr(profile, "misconception_patterns", {})
        if not mastery:
            return evidence

        reranked = []
        for item in evidence:
            boost = 1.0
            text_lower = (item.title + " " + item.content).lower()

            # 对每个概念检查掌握度
            for concept, level in mastery.items():
                if concept.lower() in text_lower or concept in item.tags:
                    if level < 0.5:
                        boost *= 1.15  # 薄弱概念的证据 boost
                    elif level > 0.8:
                        boost *= 0.90  # 已掌握概念的证据降权

            # 误概念相关证据额外 boost
            for pattern, strength in misconception.items():
                if any(kw in text_lower for kw in pattern.split("与")):
                    boost *= 1.10

            reranked.append(item.with_score(round(item.score * boost, 4)))

        reranked.sort(key=lambda item: item.score, reverse=True)
        return reranked

    def _infer_target(self, query: str) -> str:
        found_concepts = []
        for concept in sorted(self.graph.nodes, key=len, reverse=True):
            if concept in query:
                # 避免子字符串包含匹配冲突（例如 "卷积神经网络" 已经包含 "卷积核"）
                if not any(concept in existing for existing in found_concepts):
                    found_concepts.append(concept)
        if found_concepts:
            # 按照它们在查询中的出现顺序排序，提升可读性
            found_concepts.sort(key=lambda c: query.find(c))
            return "与".join(found_concepts)

        if "Pooling" in query or "池化" in query:
            return "池化层"
        if "过拟合" in query or "正则化" in query:
            return "过拟合"
        if "逻辑回归" in query or "分类" in query or "混淆矩阵" in query:
            return "逻辑回归"
        if "线性回归" in query or "回归" in query:
            return "线性回归"
        if "机器学习" in query or "监督学习" in query or "模型评估" in query:
            return "监督学习"
        if "CNN" in query or "卷积神经网络" in query:
            return "卷积神经网络"
        return "池化层"

    def _is_ml_concept(self, query: str) -> bool:
        """判断查询是否落在机器学习/深度学习学科范畴。

        非 ML 查询触发 out-of-domain 优雅降级（清空 GraphContext.learning_path），
        从而绕过默认的图谱锁定回退到通用文本/外网检索。

        判定规则（任一命中即视为 ML）：
        1. 命中知识图谱节点（包含其英文别名 Pooling/CNN/ReLU/...）
        2. 命中 ML 关键字白名单（中英）
        """
        if not query:
            return False
        q = query.strip()
        if not q:
            return False
        q_lower = q.lower()

        # 0) 垃圾查询前置过滤：纯数字/字母乱序/无意义字符串
        import re
        # 如果查询中没有常见的中文字符和英文单词模式
        has_chinese = any('\u4e00' <= c <= '\u9fff' for c in q)
        has_english_word = bool(re.search(r'[a-zA-Z]{3,}', q))
        # 纯数字+标点的查询或长度>15的连续无意义字符
        garbage_pattern = bool(re.match(r'^[a-z0-9\s\-_.,!?;:]+$', q_lower)) if not has_chinese else False
        if (not has_chinese and not has_english_word) or (garbage_pattern and len(q) > 8 and not has_chinese):
            return False

        # 1) 图谱节点直接命中
        for node in self.graph.nodes:
            if node and node in q:
                return True

        # 2) ML/DL 关键字白名单（节点别名 + 通用术语 + 常见英文缩写）
        ml_keywords = (
            # 中文
            "机器学习", "深度学习", "神经网络", "卷积", "池化", "回归", "分类",
            "聚类", "决策树", "支持向量", "朴素贝叶斯", "随机森林", "梯度",
            "反向传播", "激活函数", "正则化", "过拟合", "欠拟合", "损失函数",
            "交叉熵", "softmax", "sigmoid", "特征", "训练", "验证", "测试集",
            "超参数", "学习率", "批量", "迭代", "embedding", "嵌入", "注意力",
            "transformer", "强化学习", "自监督", "预训练", "微调",
            # 英文/缩写（大小写不敏感，下方做 lower 比较）
            "machine learning", "deep learning", "neural network", "cnn",
            "rnn", "lstm", "gru", "mlp", "svm", "knn", "pca", "pooling",
            "convolution", "regression", "classification", "clustering",
            "gradient", "backprop", "relu", "tensor", "feature map",
            "loss function", "optimizer", "adam", "sgd",
        )
        for kw in ml_keywords:
            if kw.lower() in q_lower:
                return True

        return False


class FAISSIndexSet:
    def __init__(self, index_dir: str | Path | None = None) -> None:
        from vector_store_faiss import FaissVectorIndex

        index_dir = Path(index_dir or CONFIG.faiss_index_dir)
        if not index_dir.is_absolute():
            index_dir = Path(__file__).resolve().parent / index_dir

        self.indexes: dict[str, FaissVectorIndex] = {}
        self.categories = ["courseware", "code", "textbook", "dataset", "ppt"]

        candidates = {cat: index_dir / f"{cat}_index" for cat in self.categories}
        if index_dir.is_dir():
            for faiss_file in index_dir.glob("*.faiss"):
                stem = faiss_file.stem
                if (index_dir / f"{stem}.json").is_file():
                    candidates.setdefault(stem.removesuffix("_index"), index_dir / stem)

        for cat, index_path in candidates.items():
            faiss_file = index_path.with_suffix(".faiss")
            meta_file = index_path.with_suffix(".json")
            if faiss_file.exists() and meta_file.exists():
                try:
                    self.indexes[cat] = FaissVectorIndex.load(index_path)
                    print(f"  [FAISS] Loaded {cat} index: {self.indexes[cat].count()} vectors")
                except Exception as e:
                    print(f"  [FAISS] Failed to load {cat} index: {e}")

        print(f"  [FAISS] Total: {sum(idx.count() for idx in self.indexes.values())} vectors across {len(self.indexes)} categories")

    def search(self, query: str, top_k: int = 6, category_boost: dict[str, float] | None = None) -> tuple[Evidence, ...]:
        boosts = category_boost or {
            "courseware": 1.0,
            "code": 1.05,
            "textbook": 1.0,
            "dataset": 0.6,
            "ppt": 0.8,
            "licensed_ml_course": 1.1,
        }

        all_results = []
        for cat, index in self.indexes.items():
            boost = boosts.get(cat, 1.0)
            results = index.search(query, top_k=top_k)
            for item in results:
                scored = item.with_score(item.score * boost)
                all_results.append(scored)

        ranked = sorted(all_results, key=lambda item: item.score, reverse=True)
        return tuple(ranked[:top_k])

    def search_by_category(self, query: str, category: str, top_k: int = 4) -> tuple[Evidence, ...]:
        if category in self.indexes:
            return self.indexes[category].search(query, top_k=top_k)
        return ()


def _search_videos_sync(query: str, max_results: int = 5) -> list[dict]:
    """同步包装异步视频搜索函数，支持在各种上下文下（有/无运行中的event loop）正确运行"""
    from web_search_api import search_videos
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        if loop.is_running():
            future = asyncio.run_coroutine_threadsafe(search_videos(query, max_results), loop)
            return future.result(timeout=10.0)
    except RuntimeError:
        pass
    # 降级：启动独立事件循环运行
    try:
        return asyncio.run(search_videos(query, max_results))
    except Exception as e:
        print(f"  [RAG] Synchronous video search failed: {e}")
        return []


def build_rag_pipeline(repository: Any | None = None) -> HybridRAGPipeline:
    """构建混合 RAG 管线。
    
    Args:
        repository: 可选的动态图谱仓库（InMemoryGraphRepository/Neo4jGraphRepository），
                    传入后 GraphRAG 会从中加载动态构建的边。
    """
    graph = GraphRAG(repository=repository)
    vis_rag = VisRAG()

    if CONFIG.use_faiss:
        faiss_set = FAISSIndexSet()
        return HybridRAGPipeline(graph=graph, visual_index=vis_rag, faiss_indexes=faiss_set)
    else:
        text_index = TextKnowledgeIndex()
        return HybridRAGPipeline(graph=graph, visual_index=vis_rag, text_index=text_index)


graph_rag = GraphRAG()
vis_rag = VisRAG()
hybrid_rag = build_rag_pipeline()


# === 任务 2.4: arXiv 联网学术检索本地缓存 ===
import hashlib


def _query_hash(query: str) -> str:
    return hashlib.sha256(query.lower().strip().encode("utf-8")).hexdigest()[:16]


def check_arxiv_cache(query: str) -> list[dict] | None:
    """检查 arXiv 缓存表是否命中。

    Args:
        query: 用户搜索词

    Returns:
        缓存结果列表（若命中），否则 None
    """
    try:
        from app.database import DBArxivCache, SessionLocal
        session = SessionLocal()


        qh = _query_hash(query)
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            seconds=CONFIG.cache_ttl_seconds
        )
        session.query(DBArxivCache).filter(DBArxivCache.cached_at < cutoff).delete(
            synchronize_session=False
        )
        cached = session.query(DBArxivCache).filter(
            DBArxivCache.query_hash == qh,
            DBArxivCache.cached_at >= cutoff,
        ).order_by(DBArxivCache.cached_at.desc()).limit(10).all()
        session.commit()

        session.close()

        if cached:
            return [
                {
                    "arxiv_id": c.arxiv_id,
                    "title": c.title,
                    "authors": c.authors,
                    "abstract": c.abstract[:300],
                    "pdf_url": c.pdf_url,
                    "published": c.published_at.isoformat() if c.published_at else "",
                }
                for c in cached
            ]
        return None
    except Exception:
        return None


def save_arxiv_cache(query: str, results: list[dict]) -> None:
    """将 arXiv 检索结果写入本地缓存表。

    Args:
        query: 用户搜索词
        results: arXiv API 返回的论文列表
    """
    try:
        from app.database import DBArxivCache, SessionLocal
        session = SessionLocal()


        qh = _query_hash(query)

        for paper in results:
            # 检查是否已存在相同 arxiv_id
            existing = session.query(DBArxivCache).filter(
                DBArxivCache.query_hash == qh,
                DBArxivCache.arxiv_id == paper.get("arxiv_id", ""),
            ).first()
            if existing:
                continue

            entry = DBArxivCache(
                query_hash=qh,
                arxiv_id=paper.get("arxiv_id", ""),
                title=paper.get("title", "")[:500],
                authors=str(paper.get("authors", ""))[:1000],
                abstract=paper.get("abstract", "")[:2000],
                pdf_url=paper.get("pdf_url", "")[:500],
                published_at=datetime.fromisoformat(paper["published"].replace("Z", "+00:00")) if paper.get("published") else None,
            )
            session.add(entry)

        # Keep this durable RAG cache bounded as well as time-limited.
        keep_ids = [
            row.id
            for row in session.query(DBArxivCache.id)
            .order_by(DBArxivCache.cached_at.desc())
            .limit(CONFIG.cache_max_entries)
            .all()
        ]
        if keep_ids:
            session.query(DBArxivCache).filter(~DBArxivCache.id.in_(keep_ids)).delete(
                synchronize_session=False
            )
        session.commit()
        session.close()
    except Exception:
        pass
