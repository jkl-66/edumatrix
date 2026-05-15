from __future__ import annotations

from collections import defaultdict, deque
import math
import re

from config import CONFIG
from models import Evidence, EvidenceModality, GraphContext, RetrievalBundle


def _tokens(text: str) -> set[str]:
    lower = text.lower()
    words = set(re.findall(r"[a-zA-Z0-9_+\-.]+|[\u4e00-\u9fff]{2,}", lower))
    chinese = re.findall(r"[\u4e00-\u9fff]", text)
    words.update("".join(chinese[i : i + 2]) for i in range(max(0, len(chinese) - 1)))
    return {word for word in words if word.strip()}


def _similarity(query: str, item: Evidence) -> float:
    query_tokens = _tokens(query)
    doc_tokens = _tokens(" ".join((item.title, item.content, " ".join(item.tags), " ".join(item.anchors))))
    if not query_tokens or not doc_tokens:
        return 0.0
    overlap = len(query_tokens & doc_tokens)
    jaccard = overlap / len(query_tokens | doc_tokens)
    anchor_boost = sum(1 for anchor in item.anchors if anchor and anchor in query) * 0.18
    tag_boost = sum(1 for tag in item.tags if tag and tag.lower() in query.lower()) * 0.12
    return min(1.0, jaccard + anchor_boost + tag_boost)


class GraphRAG:
    """Course concept graph used to recall complete knowledge boundaries."""

    def __init__(self) -> None:
        self.nodes: set[str] = set()
        self.forward: dict[str, set[str]] = defaultdict(set)
        self.reverse: dict[str, set[str]] = defaultdict(set)
        self._build_professional_knowledge_graph()

    def _add_edge(self, source: str, target: str) -> None:
        self.nodes.add(source)
        self.nodes.add(target)
        self.forward[source].add(target)
        self.reverse[target].add(source)

    def _build_professional_knowledge_graph(self) -> None:
        edges = [
            ("Python编程", "数据预处理"),
            ("线性代数", "向量表示"),
            ("概率统计", "模型评估"),
            ("概率统计", "朴素贝叶斯"),
            ("微积分", "梯度下降"),
            ("数据预处理", "特征工程"),
            ("特征工程", "监督学习"),
            ("监督学习", "线性回归"),
            ("监督学习", "逻辑回归"),
            ("监督学习", "决策树"),
            ("监督学习", "支持向量机"),
            ("监督学习", "朴素贝叶斯"),
            ("线性回归", "损失函数"),
            ("逻辑回归", "分类阈值"),
            ("分类阈值", "模型评估"),
            ("模型评估", "混淆矩阵"),
            ("决策树", "过拟合"),
            ("支持向量机", "间隔最大化"),
            ("损失函数", "梯度下降"),
            ("过拟合", "正则化"),
            ("正则化", "模型泛化"),
            ("模型评估", "交叉验证"),
            ("交叉验证", "模型选择"),
            ("模型泛化", "模型选择"),
            ("模型选择", "机器学习项目实践"),
            ("线性代数", "矩阵乘法"),
            ("矩阵乘法", "张量运算"),
            ("张量运算", "特征图"),
            ("微积分", "导数"),
            ("导数", "偏导数"),
            ("偏导数", "链式法则"),
            ("链式法则", "反向传播"),
            ("损失函数", "反向传播"),
            ("反向传播", "梯度下降"),
            ("卷积核", "卷积运算"),
            ("步长", "卷积运算"),
            ("填充", "卷积运算"),
            ("卷积运算", "特征图"),
            ("特征图", "池化层"),
            ("池化层", "最大池化"),
            ("池化层", "平均池化"),
            ("池化层", "全连接层"),
            ("激活函数", "卷积神经网络"),
            ("全连接层", "卷积神经网络"),
        ]
        for source, target in edges:
            self._add_edge(source, target)

    def _normalize_target(self, target: str) -> str:
        aliases = {
            "Pooling": "池化层",
            "pooling": "池化层",
            "池化": "池化层",
            "CNN": "卷积神经网络",
            "Feature Map": "特征图",
            "ReLU": "激活函数",
            "ML": "监督学习",
            "机器学习": "监督学习",
            "machine learning": "监督学习",
            "Machine Learning": "监督学习",
            "分类": "逻辑回归",
            "回归": "线性回归",
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
    """Image-patch retrieval over textbook pages and diagrams.

    In production this class is the seam for a multimodal vector store. The
    local implementation keeps the same metadata contract and deterministic
    ranking so the rest of the system is already integration-ready.
    """

    def __init__(self) -> None:
        self.patch_db: tuple[Evidence, ...] = (
            Evidence(
                id="IMG_PATCH_POOL_01",
                title="2x2 最大池化矩阵演算图",
                content="4x4 输入特征图经 2x2 Max Pooling 和 stride=2 变为 2x2 输出矩阵，窗口输出等于局部最大值。",
                modality=EvidenceModality.IMAGE,
                source="教材图像切片 PDF:P45",
                tags=("池化层", "Pooling", "最大池化", "特征图"),
                anchors=("MaxPool2d", "2x2", "局部最大值"),
                metadata={"raw_image_ref": "data/patches/pooling_2x2.png", "page": 45},
            ),
            Evidence(
                id="IMG_PATCH_POOL_02",
                title="平均池化对照图",
                content="Average Pooling 对窗口内数值求均值，适合说明它与最大池化的语义差异。",
                modality=EvidenceModality.IMAGE,
                source="教材图像切片 PDF:P46",
                tags=("池化层", "平均池化", "Pooling"),
                anchors=("AvgPool2d", "mean", "均值"),
                metadata={"raw_image_ref": "data/patches/avg_pooling.png", "page": 46},
            ),
            Evidence(
                id="IMG_PATCH_CONV_01",
                title="卷积核滑动与步长示意图",
                content="卷积核在输入特征图上按 stride 滑动，对局部区域做点积累加形成新的特征图。",
                modality=EvidenceModality.IMAGE,
                source="教材图像切片 PDF:P42",
                tags=("卷积核", "卷积运算", "步长", "特征图"),
                anchors=("kernel", "stride", "dot product"),
                metadata={"raw_image_ref": "data/patches/conv_stride.png", "page": 42},
            ),
            Evidence(
                id="IMG_PATCH_MATH_01",
                title="反向传播链式法则推导",
                content="保留微积分公式原始排版，展示损失函数对参数求导时的链式法则展开。",
                modality=EvidenceModality.IMAGE,
                source="数学手册图像切片 P12",
                tags=("反向传播", "链式法则", "偏导数"),
                anchors=("gradient", "partial derivative"),
                metadata={"raw_image_ref": "data/patches/backprop_math.png", "page": 12},
            ),
            Evidence(
                id="IMG_PATCH_ML_PIPELINE_01",
                title="机器学习项目流程图",
                content="机器学习实践通常从数据理解、数据预处理、特征工程开始，随后训练模型、验证泛化能力并迭代选择模型。",
                modality=EvidenceModality.IMAGE,
                source="机器学习课程图像切片 ML:P03",
                tags=("机器学习", "数据预处理", "特征工程", "模型评估"),
                anchors=("pipeline", "train-test split", "cross validation"),
                metadata={"raw_image_ref": "data/patches/ml_pipeline.png", "page": 3},
            ),
            Evidence(
                id="IMG_PATCH_OVERFIT_01",
                title="过拟合与欠拟合曲线",
                content="训练误差持续下降而验证误差上升时通常意味着过拟合，可通过正则化、交叉验证和简化模型缓解。",
                modality=EvidenceModality.IMAGE,
                source="机器学习课程图像切片 ML:P18",
                tags=("过拟合", "正则化", "交叉验证", "模型泛化"),
                anchors=("overfitting", "validation error", "regularization"),
                metadata={"raw_image_ref": "data/patches/overfit_curve.png", "page": 18},
            ),
            Evidence(
                id="IMG_PATCH_CONFUSION_01",
                title="混淆矩阵与分类指标图",
                content="混淆矩阵展示 TP、FP、FN、TN，可进一步计算 accuracy、precision、recall 和 F1。",
                modality=EvidenceModality.IMAGE,
                source="机器学习课程图像切片 ML:P25",
                tags=("模型评估", "混淆矩阵", "分类指标", "逻辑回归"),
                anchors=("precision", "recall", "F1", "confusion matrix"),
                metadata={"raw_image_ref": "data/patches/confusion_matrix.png", "page": 25},
            ),
        )

    def search(self, query: str, top_k: int = 3) -> list[dict[str, object]]:
        ranked = self.search_evidence(query, top_k)
        return [
            {"text": item.content, "metadata": {"id": item.id, "img": item.metadata.get("raw_image_ref")}}
            for item in ranked
        ]

    def search_evidence(self, query: str, top_k: int = 3) -> tuple[Evidence, ...]:
        ranked = sorted(
            (item.with_score(_similarity(query, item)) for item in self.patch_db),
            key=lambda item: item.score,
            reverse=True,
        )
        return tuple(item for item in ranked[:top_k] if item.score > 0.0)


class TextKnowledgeIndex:
    def __init__(self) -> None:
        self.documents: tuple[Evidence, ...] = (
            Evidence(
                id="TXT_POOL_DEF_01",
                title="池化层定义与作用",
                content="池化层对特征图进行局部聚合，常见形式包括最大池化和平均池化，可降低空间维度并提升局部平移鲁棒性。",
                modality=EvidenceModality.TEXT,
                source="课程知识库:CNN/Pooling",
                tags=("池化层", "特征图", "最大池化", "平均池化"),
                anchors=("降采样", "局部聚合", "平移鲁棒性"),
            ),
            Evidence(
                id="TXT_POOL_ERR_01",
                title="池化层易错点",
                content="最大池化取窗口最大值，平均池化取窗口均值；讲义、代码和导图必须保持同一种池化类型，否则会造成跨模态不一致。",
                modality=EvidenceModality.TEXT,
                source="课程知识库:CNN/Misconceptions",
                tags=("池化层", "最大池化", "平均池化", "易错点"),
                anchors=("MaxPool2d", "AvgPool2d", "一致性"),
            ),
            Evidence(
                id="TXT_CONV_PRE_01",
                title="池化层前置知识",
                content="池化层通常接在卷积层生成的特征图之后，因此理解卷积核、步长和特征图是理解池化层的前置条件。",
                modality=EvidenceModality.TEXT,
                source="课程知识库:CNN/Prerequisite",
                tags=("卷积核", "步长", "特征图", "池化层"),
                anchors=("前置知识", "特征图"),
            ),
            Evidence(
                id="TXT_BACKPROP_01",
                title="反向传播基本逻辑",
                content="反向传播基于链式法则将损失函数的梯度从输出层传回参数层，是神经网络训练的核心算法。",
                modality=EvidenceModality.TEXT,
                source="课程知识库:Optimization/Backprop",
                tags=("反向传播", "链式法则", "梯度下降"),
                anchors=("梯度", "损失函数"),
            ),
            Evidence(
                id="TXT_ML_OVERVIEW_01",
                title="机器学习导论课程边界",
                content="机器学习导论课程覆盖数据预处理、监督学习、回归、分类、模型评估、过拟合与正则化，并通过实践项目训练完整建模流程。",
                modality=EvidenceModality.TEXT,
                source="机器学习课程知识库:Overview",
                tags=("机器学习", "监督学习", "模型评估", "实践项目"),
                anchors=("数据预处理", "模型泛化", "交叉验证"),
            ),
            Evidence(
                id="TXT_ML_PREPROCESS_01",
                title="数据预处理与特征工程",
                content="数据预处理包括缺失值处理、数值缩放、类别编码和训练测试划分；特征工程决定模型能否从数据中学习有效规律。",
                modality=EvidenceModality.TEXT,
                source="机器学习课程知识库:Preprocessing",
                tags=("数据预处理", "特征工程", "训练测试划分"),
                anchors=("missing values", "scaling", "encoding", "train_test_split"),
            ),
            Evidence(
                id="TXT_ML_LOGREG_01",
                title="逻辑回归与分类阈值",
                content="逻辑回归使用 sigmoid 将线性组合映射为概率，分类阈值会影响 precision、recall 与 F1，不应只看 accuracy。",
                modality=EvidenceModality.TEXT,
                source="机器学习课程知识库:Classification",
                tags=("逻辑回归", "分类阈值", "模型评估"),
                anchors=("sigmoid", "precision", "recall", "F1"),
            ),
            Evidence(
                id="TXT_ML_OVERFIT_01",
                title="过拟合、正则化与交叉验证",
                content="过拟合表现为训练集效果好但验证集效果差；可通过 L1/L2 正则化、交叉验证、早停和降低模型复杂度提升泛化能力。",
                modality=EvidenceModality.TEXT,
                source="机器学习课程知识库:Generalization",
                tags=("过拟合", "正则化", "交叉验证", "模型泛化"),
                anchors=("L1", "L2", "validation", "generalization"),
            ),
            Evidence(
                id="TXT_ML_EVAL_01",
                title="模型评估指标",
                content="分类任务需结合混淆矩阵理解 accuracy、precision、recall、F1 和 ROC-AUC；类别不均衡时 accuracy 可能产生误导。",
                modality=EvidenceModality.TEXT,
                source="机器学习课程知识库:Evaluation",
                tags=("模型评估", "混淆矩阵", "分类指标"),
                anchors=("accuracy", "precision", "recall", "F1", "ROC-AUC"),
            ),
        )

    def search(self, query: str, top_k: int = 4) -> tuple[Evidence, ...]:
        ranked = sorted(
            (item.with_score(_similarity(query, item)) for item in self.documents),
            key=lambda item: item.score,
            reverse=True,
        )
        return tuple(item for item in ranked[:top_k] if item.score > 0.0)


class HybridRAGPipeline:
    def __init__(
        self,
        graph: GraphRAG | None = None,
        visual_index: VisRAG | None = None,
        text_index: TextKnowledgeIndex | None = None,
    ) -> None:
        self.graph = graph or GraphRAG()
        self.visual_index = visual_index or VisRAG()
        self.text_index = text_index or TextKnowledgeIndex()

    def retrieve(self, query: str, target: str | None = None, top_k: int = CONFIG.retrieval_top_k) -> RetrievalBundle:
        target = target or self._infer_target(query)
        graph_context = self.graph.get_context(target)
        query_with_graph = f"{query} {' '.join(graph_context.learning_path)}"
        candidates = list(self.visual_index.search_evidence(query_with_graph, top_k=top_k))
        candidates.extend(self.text_index.search(query_with_graph, top_k=top_k))
        dedup: dict[str, Evidence] = {}
        for item in candidates:
            existing = dedup.get(item.id)
            if existing is None or item.score > existing.score:
                dedup[item.id] = item
        ranked = sorted(dedup.values(), key=lambda item: item.score, reverse=True)
        return RetrievalBundle(
            query=query,
            target=graph_context.target,
            graph_context=graph_context,
            evidence=tuple(ranked[:top_k]),
        )

    def _infer_target(self, query: str) -> str:
        for concept in sorted(self.graph.nodes, key=len, reverse=True):
            if concept in query:
                return concept
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


graph_rag = GraphRAG()
vis_rag = VisRAG()
hybrid_rag = HybridRAGPipeline(graph_rag, vis_rag)
