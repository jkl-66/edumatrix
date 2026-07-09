"""动态三元组抽取与 Neo4j 拓扑图谱并网模块。

职责:
  1. 从文本 Chunk 中通过 LLM 提取 (source)-[relation]->(target) 三元组
  2. 基于 Levenshtein + 余弦相似度完成实体白名单同义词对齐
  3. 通过 Neo4j MERGE 语句构建有向无环图 (DAG)
  4. 当 Neo4j 不可用时, 自动降级到内存图存储
"""
from __future__ import annotations

import json
import re
import time
from collections import defaultdict, deque
from typing import Any, Protocol

from app.utils.exceptions import (
    GraphBuilderError,
    GraphRepositoryError,
    TripletExtractionError,
)
from app.utils.graph_models import (
    AlignedTriplet,
    EntityAlignment,
    GraphBuildReport,
    GraphQueryResult,
    Triplet,
)
from config import CONFIG
from embedding_models import EMBEDDINGS


# ---------------------------------------------------------------------------
# Entity synonym whitelist - 中英文同义词对齐映射
# ---------------------------------------------------------------------------
ENTITY_SYNONYM_WHITELIST: dict[str, str] = {
    "Loss Function": "损失函数",
    "loss function": "损失函数",
    "loss": "损失函数",
    "Gradient Descent": "梯度下降",
    "gradient descent": "梯度下降",
    "Backpropagation": "反向传播",
    "backpropagation": "反向传播",
    "backprop": "反向传播",
    "Logistic Regression": "逻辑回归",
    "logistic regression": "逻辑回归",
    "Linear Regression": "线性回归",
    "linear regression": "线性回归",
    "Overfitting": "过拟合",
    "overfitting": "过拟合",
    "Regularization": "正则化",
    "regularization": "正则化",
    "Cross Validation": "交叉验证",
    "cross validation": "交叉验证",
    "Confusion Matrix": "混淆矩阵",
    "confusion matrix": "混淆矩阵",
    "Pooling": "池化层",
    "pooling": "池化层",
    "Max Pooling": "最大池化",
    "max pooling": "最大池化",
    "Average Pooling": "平均池化",
    "average pooling": "平均池化",
    "Convolution": "卷积",
    "convolution": "卷积",
    "Convolutional Neural Network": "卷积神经网络",
    "CNN": "卷积神经网络",
    "Feature Map": "特征图",
    "feature map": "特征图",
    "Activation Function": "激活函数",
    "activation function": "激活函数",
    "ReLU": "激活函数",
    "Softmax": "激活函数",
    "Sigmoid": "激活函数",
    "Fully Connected Layer": "全连接层",
    "fully connected": "全连接层",
    "Machine Learning": "监督学习",
    "machine learning": "监督学习",
    "ML": "监督学习",
    "Pooling Layer": "池化层",
    "Convolution Kernel": "卷积核",
    "kernel": "卷积核",
    "Stride": "步长",
    "stride": "步长",
    "Partial Derivative": "偏导数",
    "partial derivative": "偏导数",
    "Chain Rule": "链式法则",
    "chain rule": "链式法则",
    "Decision Tree": "决策树",
    "Support Vector Machine": "支持向量机",
    "SVM": "支持向量机",
    "Naive Bayes": "朴素贝叶斯",
    "Feature Engineering": "特征工程",
    "Data Preprocessing": "数据预处理",
    "Model Evaluation": "模型评估",
    "Precision": "精确率",
    "precision": "精确率",
    "Recall": "召回率",
    "recall": "召回率",
    "F1 Score": "F1",
    "Epoch": "训练轮次",
    "Batch Size": "批次大小",
    "Learning Rate": "学习率",
    "learning rate": "学习率",
    "Weight": "权重",
    "Bias": "偏置",
    "bias": "偏置",
}


# ---------------------------------------------------------------------------
# Levenshtein distance (pure Python, no external deps)
# ---------------------------------------------------------------------------
def levenshtein_distance(s1: str, s2: str) -> int:
    """Compute the Levenshtein (edit) distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row
    return prev_row[-1]


def levenshtein_ratio(s1: str, s2: str) -> float:
    """Normalized similarity in [0, 1] based on Levenshtein distance."""
    total = max(len(s1), len(s2))
    if total == 0:
        return 1.0
    return 1.0 - levenshtein_distance(s1, s2) / total


# ---------------------------------------------------------------------------
# Entity alignment — exact / levenshtein / cosine / fallback
# ---------------------------------------------------------------------------
def align_entity(
    raw: str,
    whitelist: dict[str, str] | None = None,
    *,
    levenshtein_threshold: float = 0.72,
    cosine_threshold: float = 0.78,
) -> EntityAlignment:
    """将原始实体名对齐到白名单标准名。优先级: exact > levenshtein > cosine > fallback"""
    candidates = whitelist or ENTITY_SYNONYM_WHITELIST
    raw_stripped = raw.strip()
    if not raw_stripped:
        return EntityAlignment(original=raw, canonical=raw, score=0.0, method="fallback")

    # 1) Exact match (key or value)
    if raw_stripped in candidates:
        return EntityAlignment(original=raw, canonical=candidates[raw_stripped], score=1.0, method="exact")
    canonical_values = set(candidates.values())
    if raw_stripped in canonical_values:
        return EntityAlignment(original=raw, canonical=raw_stripped, score=1.0, method="exact")

    # 2) Levenshtein similarity
    best_lev_score = 0.0
    best_lev_canonical = raw_stripped
    for key, canonical in candidates.items():
        sim = levenshtein_ratio(raw_stripped.lower(), key.lower())
        if sim > best_lev_score:
            best_lev_score = sim
            best_lev_canonical = canonical
    for canonical in canonical_values:
        sim = levenshtein_ratio(raw_stripped.lower(), canonical.lower())
        if sim > best_lev_score:
            best_lev_score = sim
            best_lev_canonical = canonical
    if best_lev_score >= levenshtein_threshold:
        return EntityAlignment(original=raw, canonical=best_lev_canonical, score=best_lev_score, method="levenshtein")

    # 3) Cosine similarity using embedding vectors
    try:
        raw_vec = EMBEDDINGS.embed(raw_stripped)
        best_cos_score = 0.0
        best_cos_canonical = raw_stripped
        for key, canonical in candidates.items():
            key_vec = EMBEDDINGS.embed(key)
            cos_sim = _dot_cosine(raw_vec, key_vec)
            if cos_sim > best_cos_score:
                best_cos_score = cos_sim
                best_cos_canonical = canonical
        for canonical in canonical_values:
            c_vec = EMBEDDINGS.embed(canonical)
            cos_sim = _dot_cosine(raw_vec, c_vec)
            if cos_sim > best_cos_score:
                best_cos_score = cos_sim
                best_cos_canonical = canonical
        if best_cos_score >= cosine_threshold:
            return EntityAlignment(original=raw, canonical=best_cos_canonical, score=best_cos_score, method="cosine")
    except Exception:
        pass

    # 4) Fallback — keep original as canonical
    return EntityAlignment(original=raw, canonical=raw_stripped, score=0.0, method="fallback")


def _dot_cosine(v1: tuple[float, ...] | list[float], v2: tuple[float, ...] | list[float]) -> float:
    """Standard cosine similarity clamped to [0, 1]."""
    import math
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = math.sqrt(sum(a * a for a in v1))
    n2 = math.sqrt(sum(b * b for b in v2))
    if n1 == 0.0 or n2 == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (n1 * n2)))


# ---------------------------------------------------------------------------
# Triplet extraction — LLM prompt + JSON parsing
# ---------------------------------------------------------------------------
TRIPLET_EXTRACTION_SYSTEM_PROMPT = (
    "你是一个知识图谱三元组抽取专家。你的任务是从给定的教材文本中提取概念之间的前置依赖关系 (PREREQUISITE_OF)。\n"
    "规则:\n"
    '1. 每个三元组格式为: {"source": "前提概念", "relation": "PREREQUISITE_OF", "target": "目标概念"}\n'
    "2. source 是 target 的前置知识 (学完 source 才能学 target)\n"
    "3. 只提取明确的前置依赖关系, 不要推测\n"
    "4. 概念名使用中文标准术语\n"
    "5. 返回纯 JSON 数组, 不要包含其他文字\n"
    "示例输出:\n"
    '[{"source": "线性代数", "relation": "PREREQUISITE_OF", "target": "向量表示"}]'
)

TRIPLET_EXTRACTION_USER_TEMPLATE = (
    "请从以下教材段落中提取知识前置依赖三元组:\n"
    "---\n{chunk_text}\n---\n"
    "请返回 JSON 数组格式的三元组列表。"
)


def extract_triplets_from_text(
    chunk_text: str,
    llm: Any | None = None,
) -> tuple[Triplet, ...]:
    """从文本中提取三元组。优先使用 LLM, 降级使用正则规则引擎。"""
    if llm is not None:
        try:
            raw = llm.generate(
                TRIPLET_EXTRACTION_SYSTEM_PROMPT,
                TRIPLET_EXTRACTION_USER_TEMPLATE.format(chunk_text=chunk_text),
                role="图谱构建",
            )
            return _parse_llm_triplets(raw)
        except Exception as exc:
            raise TripletExtractionError(f"LLM 三元组抽取失败: {exc}") from exc
    return _rule_based_triplets(chunk_text)


def _parse_llm_triplets(raw_response: str) -> tuple[Triplet, ...]:
    """Parse LLM response into Triplet objects, tolerating extra text."""
    json_match = re.search(r"\[.*\]", raw_response, re.DOTALL)
    if not json_match:
        raise TripletExtractionError("LLM 响应中未找到 JSON 数组")
    try:
        items = json.loads(json_match.group())
    except json.JSONDecodeError as exc:
        raise TripletExtractionError(f"LLM 响应 JSON 解析失败: {exc}") from exc
    if not isinstance(items, list):
        raise TripletExtractionError("LLM 响应不是 JSON 数组")
    triplets: list[Triplet] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        source = item.get("source", "").strip()
        target = item.get("target", "").strip()
        if not source or not target:
            continue
        relation = item.get("relation", "PREREQUISITE_OF").strip().upper().replace(" ", "_") or "PREREQUISITE_OF"
        confidence = float(item.get("confidence", 1.0))
        evidence = item.get("evidence", "").strip()
        triplets.append(Triplet(source=source, target=target, relation=relation, confidence=confidence, evidence=evidence))
    return tuple(triplets)


def _rule_based_triplets(chunk_text: str) -> tuple[Triplet, ...]:
    """基于正则规则的三元组提取 (LLM 不可用时的降级方案)。

    覆盖 8 类常见中文教材句式：
    1. A 是 B 的重要组成部分 → A 是 B 的前置
    2. 学习 A 之前必须先掌握 B → B 是 A 的前置
    3. A 依赖于 B → B 是 A 的前置
    4. A 基于 B → B 是 A 的前置
    5. A 包括/分为 B、C → B/C 是 A 的后置（不作处理）
    6. 在 A 之后通常(使用/接) B → A 是 B 的前置
    7. A 通过 B (实现/完成) → B 是 A 的前置
    8. 必须先(掌握/理解) A 才能 B → A 是 B 的前置
    """
    triplets: list[Triplet] = []
    seen: set[tuple[str, str]] = set()

    patterns: list[tuple[str, str, int, int]] = [
        # (regex, relation, source_group, target_group)
        # 句式 1: A 是 B 的前置/基础/前提
        (r"(?:学习\s*)?([一-鿿\w]{1,20}?)\s*是\s*([一-鿿\w]{1,20}?)\s*的(?:前置|基础|前提条件|先决条件)", "PREREQUISITE_OF", 2, 1),
        # 句式 2: 学习 A 之前必须先掌握 B  → B 是 A 的前置
        (r"学习\s*([一-鿿\w]{1,20}?)\s*(?:之前|以前|前).*?(?:先|必须|需要).*?(?:掌握|理解|学会|学完)\s*([一-鿿\w]{1,20}?)", "PREREQUISITE_OF", 2, 1),
        # 句式 3: A 依赖于 B
        (r"([一-鿿\w]{1,20}?)\s*依赖(?:于)?\s*([一-鿿\w]{1,20}?)\s*(?:的)?(?:计算|实现|支持)", "PREREQUISITE_OF", 2, 1),
        # 句式 4: A 基于 B
        (r"([一-鿿\w]{1,20}?)\s*基于\s*([一-鿿\w]{1,20}?)\s*(?:的)?(?:原理|思想|方法|算法)", "PREREQUISITE_OF", 2, 1),
        # 句式 6: 在 A 之后通常(使用/接/接上) B
        (r"在\s*([一-鿿\w]{1,20}?)\s*(?:之后|后面|之后通常)\s*(?:使用|接|连接|拼接)\s*([一-鿿\w]{1,20}?)", "PREREQUISITE_OF", 1, 2),
        # 句式 7: A 通过 B (实现/完成/解决)
        (r"([一-鿿\w]{1,20}?)\s*通过\s*([一-鿿\w]{1,20}?)\s*(?:实现|完成|计算|解决|得到)", "PREREQUISITE_OF", 2, 1),
        # 句式 8: 必须先(掌握/理解) A 才能(学习/理解) B
        (r"必须先\s*(?:掌握|理解|学会)\s*([一-鿿\w]{1,20}?)\s*才能\s*(?:学习|理解|掌握|开始)\s*([一-鿿\w]{1,20}?)", "PREREQUISITE_OF", 1, 2),
        # 兜底: A 是 B 的重要组成部分 → "是...的" 后置模式（非 exact 匹配）
        (r"([一-鿿\w]{1,20}?)\s*是\s*([一-鿿\w]{1,20}?)\s*(?:中|里|内部|体系)?的(?:重要|核心|关键|基础|根本)(?:组成)?部分", "PREREQUISITE_OF", 2, 1),
    ]

    for pattern, relation, src_grp, tgt_grp in patterns:
        for match in re.finditer(pattern, chunk_text):
            source = match.group(src_grp).strip()
            target = match.group(tgt_grp).strip()
            # 过滤：非空、不相等、不是无意义的单字、不与已有重复
            if (source and target and source != target
                    and len(source) >= 2 and len(target) >= 2
                    and (source, target) not in seen):
                seen.add((source, target))
                triplets.append(Triplet(
                    source=source, target=target, relation=relation, confidence=0.65
                ))

    return tuple(triplets)


# ---------------------------------------------------------------------------
# Graph Repository — abstract backend (Neo4j / in-memory)
# ---------------------------------------------------------------------------
class GraphRepository(Protocol):
    """图存储后端协议。"""
    def merge_node(self, label: str, name: str) -> None: ...
    def merge_edge(self, source: str, target: str, relation: str) -> None: ...
    def query_prerequisites(self, target: str) -> GraphQueryResult: ...
    def count_nodes(self) -> int: ...
    def count_edges(self) -> int: ...


class InMemoryGraphRepository:
    """内存图存储 (Neo4j 不可用时的降级方案)。"""

    def __init__(self) -> None:
        self.nodes: set[str] = set()
        self.edges: list[tuple[str, str, str]] = []
        self._forward: dict[str, set[str]] = defaultdict(set)
        self._reverse: dict[str, set[str]] = defaultdict(set)

    def merge_node(self, label: str, name: str) -> None:
        self.nodes.add(name)

    def merge_edge(self, source: str, target: str, relation: str) -> None:
        self.nodes.add(source)
        self.nodes.add(target)
        self._forward[source].add(target)
        self._reverse[target].add(source)
        edge = (source, target, relation)
        if edge not in self.edges:
            self.edges.append(edge)

    def query_prerequisites(self, target: str) -> GraphQueryResult:
        visited: set[str] = set()
        queue = deque(self._reverse.get(target, set()))
        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            queue.extend(self._reverse.get(node, set()))
        downstream = tuple(sorted(self._forward.get(target, set())))
        return GraphQueryResult(target=target, prerequisites=tuple(sorted(visited)), downstream=downstream)

    def count_nodes(self) -> int:
        return len(self.nodes)

    def count_edges(self) -> int:
        return len(self.edges)


class Neo4jGraphRepository:
    """Neo4j 图存储后端, 使用 MERGE 语句构建 DAG。"""

    def __init__(
        self,
        uri: str = "",
        user: str = "",
        password: str = "",
        database: str = "neo4j",
    ) -> None:
        self._uri = uri
        self._user = user
        self._password = password
        self._database = database
        self._driver: Any = None
        self._local_fallback = InMemoryGraphRepository()

    def _get_driver(self) -> Any:
        if self._driver is not None:
            return self._driver
        try:
            from neo4j import GraphDatabase
            self._driver = GraphDatabase.driver(self._uri, auth=(self._user, self._password))
            return self._driver
        except ImportError:
            return None

    def _run_query(self, query: str, params: dict | None = None) -> list[dict]:
        driver = self._get_driver()
        if driver is None:
            raise GraphRepositoryError("neo4j 驱动未安装, 无法连接 Neo4j")
        try:
            with driver.session(database=self._database) as session:
                result = session.run(query, params or {})
                return [record.data() for record in result]
        except Exception as exc:
            raise GraphRepositoryError(f"Neo4j 查询执行失败: {exc}") from exc

    def merge_node(self, label: str, name: str) -> None:
        query = "MERGE (n:Concept {name: $name}) SET n.label = $label"
        try:
            self._run_query(query, {"name": name, "label": label})
        except GraphRepositoryError:
            self._local_fallback.merge_node(label, name)

    def merge_edge(self, source: str, target: str, relation: str) -> None:
        safe_rel = _safe_relation(relation)
        query = (
            "MERGE (s:Concept {name: $source}) "
            "MERGE (t:Concept {name: $target}) "
            f"MERGE (s)-[r:{safe_rel}]->(t) "
            "SET r.type = $relation"
        )
        try:
            self._run_query(query, {"source": source, "target": target, "relation": relation})
        except GraphRepositoryError:
            self._local_fallback.merge_edge(source, target, relation)

    def query_prerequisites(self, target: str) -> GraphQueryResult:
        query = (
            "MATCH (t:Concept {name: $target})<-[:PREREQUISITE_OF*1..]-(p:Concept) "
            "RETURN COLLECT(DISTINCT p.name) AS prerequisites"
        )
        downstream_query = (
            "MATCH (s:Concept {name: $target})-[:PREREQUISITE_OF]->(d:Concept) "
            "RETURN COLLECT(DISTINCT d.name) AS downstream"
        )
        try:
            prereq_result = self._run_query(query, {"target": target})
            down_result = self._run_query(downstream_query, {"target": target})
            prerequisites = tuple(prereq_result[0].get("prerequisites", [])) if prereq_result else ()
            downstream = tuple(down_result[0].get("downstream", [])) if down_result else ()
            return GraphQueryResult(target=target, prerequisites=prerequisites, downstream=downstream)
        except GraphRepositoryError:
            return self._local_fallback.query_prerequisites(target)

    def count_nodes(self) -> int:
        try:
            result = self._run_query("MATCH (n:Concept) RETURN COUNT(n) AS cnt")
            return result[0].get("cnt", 0) if result else 0
        except GraphRepositoryError:
            return self._local_fallback.count_nodes()

    def count_edges(self) -> int:
        try:
            result = self._run_query("MATCH ()-[r:PREREQUISITE_OF]->() RETURN COUNT(r) AS cnt")
            return result[0].get("cnt", 0) if result else 0
        except GraphRepositoryError:
            return self._local_fallback.count_edges()

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None


def _safe_relation(relation: str) -> str:
    """Sanitize relation name for Cypher (alphanumeric + underscore only)."""
    return re.sub(r"[^A-Za-z0-9_]", "_", relation.upper()) or "PREREQUISITE_OF"


def create_graph_repository(
    *,
    neo4j_uri: str = "",
    neo4j_user: str = "",
    neo4j_password: str = "",
    neo4j_database: str = "neo4j",
) -> GraphRepository:
    """工厂方法: 优先创建 Neo4j 后端, 失败则降级到内存后端。"""
    uri = neo4j_uri or getattr(CONFIG, "neo4j_uri", "")
    user = neo4j_user or getattr(CONFIG, "neo4j_user", "")
    password = neo4j_password or getattr(CONFIG, "neo4j_password", "")
    database = neo4j_database or getattr(CONFIG, "neo4j_database", "neo4j")
    if uri and user and password:
        try:
            repo = Neo4jGraphRepository(uri=uri, user=user, password=password, database=database)
            repo.count_nodes()  # verify connectivity
            return repo
        except Exception:
            pass
    return InMemoryGraphRepository()


# ---------------------------------------------------------------------------
# GraphBuilder — main orchestrator
# ---------------------------------------------------------------------------
class GraphBuilder:
    """图谱构建器: 三元组抽取 -> 实体对齐 -> Neo4j MERGE 写入。"""

    def __init__(
        self,
        repository: GraphRepository | None = None,
        llm: Any | None = None,
        whitelist: dict[str, str] | None = None,
    ) -> None:
        self.repository = repository or create_graph_repository()
        self.llm = llm
        self.whitelist = whitelist or ENTITY_SYNONYM_WHITELIST

    def build_from_chunks(
        self,
        chunks: tuple[str, ...] | list[str],
        *,
        source: str = "unknown",
    ) -> GraphBuildReport:
        """从文本 Chunk 列表构建图谱, 返回构建报告。"""
        t0 = time.monotonic()
        all_raw: list[Triplet] = []
        all_aligned: list[AlignedTriplet] = []
        written_edges = 0

        for chunk_text in chunks:
            try:
                raw_triplets = extract_triplets_from_text(chunk_text, llm=self.llm)
            except TripletExtractionError:
                raw_triplets = _rule_based_triplets(chunk_text)
            all_raw.extend(raw_triplets)

            for triplet in raw_triplets:
                aligned = self._align_triplet(triplet)
                all_aligned.append(aligned)
                if aligned.both_aligned or aligned.source_alignment.method != "fallback":
                    self._write_triplet(aligned.aligned)
                    written_edges += 1

        duration_ms = int((time.monotonic() - t0) * 1000)
        aligned_count = sum(1 for a in all_aligned if a.both_aligned)
        alignment_rate = aligned_count / len(all_aligned) if all_aligned else 0.0
        backend = "neo4j" if isinstance(self.repository, Neo4jGraphRepository) else "memory"

        return GraphBuildReport(
            source=source,
            chunk_count=len(chunks),
            raw_triplets=len(all_raw),
            aligned_triplets=aligned_count,
            written_edges=written_edges,
            alignment_rate=round(alignment_rate, 4),
            backend=backend,
            duration_ms=duration_ms,
            triplets=tuple(all_raw),
            aligned=tuple(all_aligned),
        )

    def build_from_text(self, text: str, *, source: str = "manual-input") -> GraphBuildReport:
        """从单段文本构建图谱 (自动按段落分割)。"""
        chunks = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not chunks:
            chunks = [text]
        return self.build_from_chunks(tuple(chunks), source=source)

    def query(self, target: str) -> GraphQueryResult:
        """查询某概念的前置依赖与后续应用。"""
        return self.repository.query_prerequisites(target)

    def _align_triplet(self, triplet: Triplet) -> AlignedTriplet:
        source_alignment = align_entity(triplet.source, self.whitelist)
        target_alignment = align_entity(triplet.target, self.whitelist)
        return AlignedTriplet(raw=triplet, source_alignment=source_alignment, target_alignment=target_alignment)

    def _write_triplet(self, triplet: Triplet) -> None:
        self.repository.merge_node("Concept", triplet.source)
        self.repository.merge_node("Concept", triplet.target)
        self.repository.merge_edge(triplet.source, triplet.target, triplet.relation)


def seed_default_graph(builder: GraphBuilder | None = None) -> GraphBuildReport:
    """将内置的机器学习知识图谱边导入图谱存储。"""
    b = builder or GraphBuilder()
    builtin_edges = [
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
    ]
    triplets = tuple(
        Triplet(source=s, target=t, relation="PREREQUISITE_OF")
        for s, t in builtin_edges
    )
    aligned: list[AlignedTriplet] = []
    written = 0
    t0 = time.monotonic()
    for triplet in triplets:
        a = b._align_triplet(triplet)
        aligned.append(a)
        b._write_triplet(a.aligned)
        written += 1
    duration_ms = int((time.monotonic() - t0) * 1000)
    both_aligned = sum(1 for a in aligned if a.both_aligned)
    return GraphBuildReport(
        source="builtin-seed",
        chunk_count=1,
        raw_triplets=len(triplets),
        aligned_triplets=both_aligned,
        written_edges=written,
        alignment_rate=round(both_aligned / len(aligned), 4) if aligned else 0.0,
        backend="neo4j" if isinstance(b.repository, Neo4jGraphRepository) else "memory",
        duration_ms=duration_ms,
        triplets=triplets,
        aligned=tuple(aligned),
    )
