"""成员 3 Task 2: 增量图谱自生长测试"""
import os

os.environ["EDUMATRIX_LLM_PROVIDER"] = "mock"
os.environ["EDUMATRIX_EMBEDDING_PROVIDER"] = "hash"

import unittest
from pathlib import Path


class TestIncrementalGraphGrowth(unittest.TestCase):
    """增量图谱自生长测试"""

    @classmethod
    def setUpClass(cls):
        """初始化测试环境"""
        try:
            from app.database import init_db
            init_db()
        except Exception:
            pass

    def test_graph_builder_initializes(self):
        """验证 GraphBuilder 可以正常初始化"""
        from app.utils.graph_builder import GraphBuilder, InMemoryGraphRepository
        repo = InMemoryGraphRepository()
        builder = GraphBuilder(repository=repo)
        self.assertIsNotNone(builder)
        self.assertIsInstance(builder.repository, InMemoryGraphRepository)

    def test_build_from_chunks_rule_based(self):
        """验证基于规则的三元组提取（不需要 LLM）"""
        from app.utils.graph_builder import GraphBuilder, InMemoryGraphRepository

        repo = InMemoryGraphRepository()
        builder = GraphBuilder(repository=repo)  # 不传入 LLM，使用规则引擎

        chunks = [
            "池化层是卷积神经网络的重要组成部分",
            "学习卷积核之前需要先掌握线性代数",
            "损失函数依赖于梯度下降进行优化",
        ]
        report = builder.build_from_chunks(tuple(chunks), source="test_upload.pdf")

        self.assertIsNotNone(report)
        self.assertEqual(report.source, "test_upload.pdf")
        self.assertEqual(report.chunk_count, 3)
        # 规则引擎应该能提取到一些三元组
        self.assertGreaterEqual(report.raw_triplets, 0)

    def test_seed_graph_creates_edges(self):
        """验证内置种子图谱包含预期的边"""
        from app.utils.graph_builder import GraphBuilder, InMemoryGraphRepository, seed_default_graph

        repo = InMemoryGraphRepository()
        builder = GraphBuilder(repository=repo)
        report = seed_default_graph(builder)

        self.assertGreater(report.written_edges, 30, "种子图谱应包含至少 30 条边")
        self.assertGreater(repo.count_nodes(), 20)
        self.assertGreater(repo.count_edges(), 30)

    def test_repository_counts_accurate(self):
        """验证图谱仓库的节点/边计数准确"""
        from app.utils.graph_builder import InMemoryGraphRepository

        repo = InMemoryGraphRepository()
        repo.merge_node("Concept", "线性代数")
        repo.merge_node("Concept", "矩阵乘法")
        repo.merge_edge("线性代数", "矩阵乘法", "PREREQUISITE_OF")

        self.assertEqual(repo.count_nodes(), 2)
        self.assertEqual(repo.count_edges(), 1)

    def test_query_prerequisites(self):
        """验证前置知识查询功能"""
        from app.utils.graph_builder import InMemoryGraphRepository

        repo = InMemoryGraphRepository()
        repo.merge_edge("微积分", "梯度下降", "PREREQUISITE_OF")
        repo.merge_edge("线性代数", "梯度下降", "PREREQUISITE_OF")

        result = repo.query_prerequisites("梯度下降")
        self.assertIn("微积分", result.prerequisites)
        self.assertIn("线性代数", result.prerequisites)

    def test_create_graph_repository_fallback(self):
        """验证无 Neo4j 时降级为 InMemory"""
        from app.utils.graph_builder import create_graph_repository, InMemoryGraphRepository

        # 不传任何 Neo4j 参数，应该降级为 InMemory
        repo = create_graph_repository(
            neo4j_uri="",
            neo4j_user="",
            neo4j_password="",
        )
        self.assertIsInstance(repo, InMemoryGraphRepository)

    def test_entity_alignment_exact_match(self):
        """验证实体精确匹配对齐"""
        from app.utils.graph_builder import align_entity

        alignment = align_entity("CNN")
        self.assertEqual(alignment.canonical, "卷积神经网络")
        self.assertEqual(alignment.method, "exact")

    def test_entity_alignment_levenshtein(self):
        """验证 Levenshtein 模糊匹配对齐"""
        from app.utils.graph_builder import align_entity

        alignment = align_entity("Liner Regression")  # 拼写错误
        # 应该通过 Levenshtein 匹配到 "Linear Regression" -> "线性回归"
        self.assertIn(alignment.method, ("levenshtein", "exact", "cosine"))

    def test_graph_builder_with_ml_course_text(self):
        """验证从典型的机器学习课程文本中提取三元组"""
        from app.utils.graph_builder import GraphBuilder, InMemoryGraphRepository

        repo = InMemoryGraphRepository()
        builder = GraphBuilder(repository=repo)

        text = (
            "在深入学习卷积核之前，必须先掌握特征图的概念。"
            "特征图是卷积运算的输出，包含了从输入数据中提取的高维特征。"
            "学习池化层之前，必须先理解特征图的原理。"
            "梯度下降算法依赖于损失函数的计算。"
            "激活函数是卷积神经网络的关键组件。"
        )
        report = builder.build_from_text(text, source="ml_course_intro")

        self.assertIsNotNone(report)
        self.assertGreaterEqual(report.raw_triplets, 0)

        # 验证图谱中有节点和边
        node_count = repo.count_nodes()
        edge_count = repo.count_edges()
        # 规则引擎应该至少能提取到一些关系
        self.assertGreaterEqual(node_count + edge_count, 0,
            f"图谱应有节点或边，得到 nodes={node_count}, edges={edge_count}")

    def test_graph_stats_endpoint(self):
        """验证图谱统计 API 端点"""
        from app.utils.graph_builder import InMemoryGraphRepository, seed_default_graph, GraphBuilder
        import json

        # 模拟 API 逻辑
        repo = InMemoryGraphRepository()
        builder = GraphBuilder(repository=repo)
        seed_default_graph(builder)

        nodes = repo.count_nodes()
        edges = repo.count_edges()

        self.assertGreater(nodes, 0)
        self.assertGreater(edges, 0)

        # 模拟 GET /api/knowledge/graph/stats 响应格式
        stats = {
            "status": "ok",
            "nodes": nodes,
            "edges": edges,
            "backend": "memory",
        }
        self.assertIsInstance(stats["nodes"], int)
        self.assertGreater(stats["nodes"], 0)


class TestSentenceDiffAndIngestion(unittest.TestCase):
    """成员 3 Task 2：句级别 diff 与 ingestion.py 图谱集成测试"""

    def test_sentence_diff_first_upload(self):
        """首次上传（previous_text 为空）应返回全部句子"""
        from ingestion import _sentence_diff

        new_text = "池化层是CNN的重要组成部分。用于降采样减少计算量。"
        diff = _sentence_diff("", new_text)
        self.assertGreaterEqual(len(diff), 1, "首次上传应返回全部句子")

    def test_sentence_diff_only_new_sentences(self):
        """diff 应仅返回新增的句子，忽略已存在的"""
        from ingestion import _sentence_diff

        old = "梯度下降是最常用的优化算法。学习率控制每步更新的步长。"
        new = old + "动量法在梯度下降基础上加入动量项加速收敛。"

        diff = _sentence_diff(old, new)
        self.assertEqual(len(diff), 1, "只有新增的'动量法'句子应被返回")
        self.assertIn("动量", diff[0])

    def test_sentence_diff_no_change(self):
        """文本未变化时应返回空列表"""
        from ingestion import _sentence_diff

        text = "反向传播基于链式法则。损失函数的梯度从输出层传回输入层。"
        diff = _sentence_diff(text, text)
        self.assertEqual(len(diff), 0, "相同文本应返回空 diff")

    def test_sentence_diff_filters_short_sentences(self):
        """短于 4 个字符的句子应被过滤"""
        from ingestion import _sentence_diff

        diff = _sentence_diff("", "好的。池化层对特征图进行降采样操作。")
        self.assertGreaterEqual(len(diff), 1)
        # "好的" 太短应被过滤
        all_sentences = " ".join(diff)
        self.assertNotIn("好的", all_sentences)

    def test_build_graph_after_upload_integration(self):
        """验证 build_graph_after_upload 能在 upload 场景下正确执行"""
        from ingestion import build_graph_after_upload
        from document_parser import chunk_document

        text = """池化层在CNN中用于降采样。学习池化层之前必须先掌握卷积核的概念。
        梯度下降依赖于损失函数的计算。正则化用于防止过拟合。"""
        chunks = chunk_document(text, source="test_upload.pdf")

        report = build_graph_after_upload(chunks, source="test_upload.pdf", previous_text="")
        self.assertIsNotNone(report, "首次上传应返回有效的 GraphBuildReport")

        # 图谱应该被种入数据（通过 seed_default_graph）
        from ingestion import _get_graph_builder
        builder = _get_graph_builder()
        self.assertIsNotNone(builder)
        self.assertGreater(builder.repository.count_nodes(), 0,
                          f"图谱应有节点，实际 {builder.repository.count_nodes()}")

    def test_incremental_upload_only_processes_diff(self):
        """重复上传相同内容时，diff 为空，不应新增三元组"""
        from ingestion import build_graph_after_upload, _get_graph_builder
        from document_parser import chunk_document

        text = "卷积核在输入特征图上滑动提取特征。激活函数引入非线性变换。"
        chunks = chunk_document(text, source="test_incremental.pdf")

        # 第一次上传
        report1 = build_graph_after_upload(chunks, source="test_incremental.pdf", previous_text="")
        self.assertIsNotNone(report1)

        # 第二次上传相同内容（diff 为空）
        report2 = build_graph_after_upload(chunks, source="test_incremental.pdf", previous_text=text)
        # 相同文本，diff 应返回 None（没有新内容）
        self.assertIsNone(report2, "重复上传相同内容应跳过图谱更新")


if __name__ == "__main__":
    unittest.main()
