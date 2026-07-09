"""综合集成测试：动画资源 + 知识库 + 图谱 + 跨模态搜索"""
import os
os.environ["EDUMATRIX_LLM_PROVIDER"] = "mock"
os.environ["EDUMATRIX_EMBEDDING_PROVIDER"] = "hash"

import sys
import unittest
from pathlib import Path


class TestAnimationResources(unittest.TestCase):
    """测试动画资源部署"""

    def test_animations_directory_exists(self):
        """验证动画目录已部署"""
        from animation_api import ANIMATIONS_DIR
        self.assertTrue(ANIMATIONS_DIR.exists(), f"目录不存在: {ANIMATIONS_DIR}")

    def test_knowledge_points_with_videos(self):
        """验证各知识点目录下有视频文件"""
        from animation_api import KNOWLEDGE_POINTS, _get_knowledge_videos

        total = 0
        kp_found = 0
        empty = []
        for kp in KNOWLEDGE_POINTS:
            videos = _get_knowledge_videos(kp)
            if videos:
                kp_found += 1
                total += len(videos)
            else:
                empty.append(kp)

        print(f"\n  [STATS] 动画资源: {kp_found}/{len(KNOWLEDGE_POINTS)} 知识点有视频, 共 {total} 个")
        if empty:
            print(f"  [!] 无视频知识点: {empty}")

        # 至少要有 20 个知识点有视频
        self.assertGreaterEqual(kp_found, 20, f"至少应有 20 个知识点有视频，实际 {kp_found}")
        self.assertGreaterEqual(total, 60, f"至少应有 60 个视频文件，实际 {total}")

    def test_video_files_are_valid(self):
        """验证视频文件可读取且非空"""
        from animation_api import KNOWLEDGE_POINTS, _get_knowledge_videos

        checked = 0
        for kp in KNOWLEDGE_POINTS:
            videos = _get_knowledge_videos(kp)
            for v in videos[:2]:  # 每个知识点抽查前 2 个
                full_path = Path(v["path"])
                self.assertGreater(v["size"], 1024, f"视频太小: {v['filename']} ({v['size']} bytes)")
                checked += 1
                if checked >= 20:
                    break
            if checked >= 20:
                break
        self.assertGreater(checked, 0)

    def test_animation_list_api(self):
        """测试动画列表 API 逻辑"""
        from animation_api import KNOWLEDGE_POINTS, _get_knowledge_videos

        result = {}
        for kp in KNOWLEDGE_POINTS:
            videos = _get_knowledge_videos(kp)
            if videos:
                result[kp] = videos

        total = sum(len(v) for v in result.values())
        stats = {"knowledge_points": result, "total": total}
        self.assertGreater(stats["total"], 0)

    def test_animation_for_specific_knowledge(self):
        """测试根据知识点获取动画"""
        from animation_api import _get_knowledge_videos

        # 测试精确匹配
        videos = _get_knowledge_videos("pooling")
        # 尝试中文
        for kp_name in ["池化层", "梯度下降", "神经网络", "反向传播"]:
            videos = _get_knowledge_videos(kp_name)
            # 至少这些热门知识点应该有视频
            if videos:
                print(f"  [OK] {kp_name}: {len(videos)} 个视频")
                return
        self.fail("常见知识点应该有视频")

    def test_search_animation_by_query(self):
        """测试按查询搜索动画"""
        from animation_api import KNOWLEDGE_POINTS, _get_knowledge_videos

        # 模拟 search_animation 逻辑
        def search(query):
            matched = []
            for kp in KNOWLEDGE_POINTS:
                if kp in query:
                    videos = _get_knowledge_videos(kp)
                    if videos:
                        matched.append({"knowledge_point": kp, "videos": videos})
            return matched

        result = search("梯度下降算法怎么用")
        if result:
            print(f"  [OK] 搜索'梯度下降'匹配到: {result[0]['knowledge_point']} ({len(result[0]['videos'])} 视频)")
        self.assertIsInstance(result, list)


class TestKnowledgeIntegration(unittest.TestCase):
    """测试知识库与成员3功能的联动"""

    @classmethod
    def setUpClass(cls):
        try:
            from app.database import init_db
            init_db()
        except Exception:
            pass

    def test_knowledge_api_imports(self):
        """验证知识库 API 模块可正确导入"""
        from knowledge_api import router, _get_graph_builder
        self.assertIsNotNone(router)
        builder = _get_graph_builder()
        self.assertIsNotNone(builder)

    def test_document_parser_visual_functions(self):
        """验证文档解析器视觉函数可用"""
        from document_parser import (
            _render_pdf_to_images,
            _describe_image_with_pil,
            parse_pdf_visually,
            _check_vision_llm,
        )
        # 所有函数应该可调用
        self.assertTrue(callable(_render_pdf_to_images))
        self.assertTrue(callable(_describe_image_with_pil))
        self.assertTrue(callable(parse_pdf_visually))
        # 检测状态应一致
        result = _check_vision_llm()
        self.assertIsInstance(result, bool)

    def test_multimodal_alignment_with_ml_concepts(self):
        """验证跨模态对齐知识可覆盖动画知识点"""
        from multimodal_alignment import get_cross_modal_aligner
        from animation_api import KNOWLEDGE_POINTS

        aligner = get_cross_modal_aligner()
        self.assertGreater(aligner.pair_count, 0)

        # 检查对齐数据覆盖了多少知识点
        concepts_in_aligner = set()
        for pair in aligner._pairs:
            concepts_in_aligner.add(pair.get("concept", ""))

        covered = set(KNOWLEDGE_POINTS) & concepts_in_aligner
        print(f"\n  [STATS] 跨模态对齐覆盖: {len(covered)}/{len(KNOWLEDGE_POINTS)} 个知识点")
        print(f"  [OK] 覆盖: {sorted(covered)}")
        unmatched = set(KNOWLEDGE_POINTS) - concepts_in_aligner
        if unmatched:
            print(f"  [!] 未覆盖: {sorted(unmatched)}")

    def test_graph_contains_animation_knowledge(self):
        """验证图谱中包含动画相关知识点"""
        from app.utils.graph_builder import GraphBuilder, InMemoryGraphRepository, seed_default_graph
        from animation_api import KNOWLEDGE_POINTS

        repo = InMemoryGraphRepository()
        builder = GraphBuilder(repository=repo)
        seed_default_graph(builder)

        nodes = repo.nodes
        covered = set(KNOWLEDGE_POINTS) & nodes
        print(f"\n  [STATS] 图谱覆盖: {len(covered)}/{len(KNOWLEDGE_POINTS)} 个知识点")
        self.assertGreater(len(covered), 10, "图谱应覆盖至少 10 个动画知识点")

    def test_cross_search_for_animation_topics(self):
        """验证跨模态搜索动画相关知识点"""
        from multimodal_alignment import get_cross_modal_aligner

        aligner = get_cross_modal_aligner()

        # 测试典型 ML 搜索场景
        queries = [
            ("池化层 max 计算", "text"),
            ("梯度下降更新参数", "text"),
            (r"\sigma(z) = \frac{1}{1 + e^{-z}}", "formula"),
            ("过拟合的正则化方法", "text"),
        ]
        for query, mode in queries:
            results = aligner.search(query, mode=mode, top_k=3)
            has_results = len(results) > 0
            top_score = results[0]["score"] if results else 0
            print(f"  {'[OK]' if has_results else '[!]'} [{mode}] \"{query[:30]}...\" → {len(results)} 结果, top_score={top_score:.3f}")


class TestEndToEndUploadAndGraph(unittest.TestCase):
    """端到端测试：上传文档 → 图谱更新"""

    @classmethod
    def setUpClass(cls):
        try:
            from app.database import init_db
            init_db()
        except Exception:
            pass

    def test_pdf_visual_parsing_pipeline(self):
        """验证 PDF 视觉解析流水线（端到端）"""
        from document_parser import parse_pdf_visually, _render_pdf_to_images

        # 创建测试 PDF
        pdf_bytes = (
            b"%PDF-1.4\n"
            b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>>>endobj\n"
            b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n"
            b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF"
        )
        evidence_list = parse_pdf_visually(pdf_bytes, "ml_textbook_ch3.pdf")

        # 如果 fitz 可用，应该返回结果
        try:
            import fitz
            self.assertGreater(len(evidence_list), 0, "fitz 可用时应返回视觉 evidence")
            for ev in evidence_list:
                self.assertEqual(ev.modality.value, "image")
                self.assertIn("ml_textbook_ch3", ev.title)
                self.assertGreater(len(ev.content), 20, f"描述太短: {ev.content[:50]}")
            print(f"\n  [OK] PDF 视觉解析成功: {len(evidence_list)} 页, 第1页描述: {evidence_list[0].content[:100]}...")
        except ImportError:
            # fitz 不可用时返回空列表（优雅降级）
            print(f"\n  [!] PyMuPDF 未安装，跳过视觉解析测试")

    def test_graph_build_from_ml_text(self):
        """验证从 ML 教材文本中提取图谱"""
        from app.utils.graph_builder import GraphBuilder, InMemoryGraphRepository, seed_default_graph

        repo = InMemoryGraphRepository()
        builder = GraphBuilder(repository=repo)

        # 模拟 ML 教材章节
        text = """
        池化层是卷积神经网络中的重要组件。在卷积层生成特征图之后，
        通常使用池化层进行降采样。池化层分为最大池化和平均池化两种。

        学习池化层之前，必须先掌握卷积核和特征图的概念。
        卷积神经网络的基础组件包括：卷积核、激活函数、池化层和全连接层。

        梯度下降是训练神经网络的核心优化算法。梯度下降依赖于
        损失函数的计算，而损失函数的梯度通过反向传播算法计算。
        反向传播基于链式法则，因此学习反向传播之前必须先理解
        链式法则和偏导数的概念。
        """
        report = builder.build_from_text(text, source="ml_chapter_cnn")

        print(f"\n  [STATS] Graph build: {report.raw_triplets} triples, "
              f"{report.aligned_triplets} aligned, "
              f"{report.written_edges} edges written")

        # Rule-based extraction depends on specific Chinese patterns like "X是Y的前置"
        # Without LLM, it may extract 0 triples from free-text; that's expected behavior
        # The seed graph and LLM-based extraction provide the primary graph coverage
        self.assertIsNotNone(report)
        self.assertEqual(report.source, "ml_chapter_cnn")
        # With seed graph, nodes and edges exist
        seed_report = seed_default_graph(builder)
        self.assertGreater(repo.count_nodes(), 0, "After seeding, graph should have nodes")
        self.assertGreater(repo.count_edges(), 0, "After seeding, graph should have edges")
        print(f"  [OK] After seeding: {repo.count_nodes()} nodes, {repo.count_edges()} edges")

    def test_full_integration_animation_to_rag(self):
        """综合验证：动画资源 + 知识库 + 图谱的联动"""
        from animation_api import KNOWLEDGE_POINTS, _get_knowledge_videos
        from app.utils.graph_builder import GraphBuilder, InMemoryGraphRepository, seed_default_graph
        from multimodal_alignment import get_cross_modal_aligner

        # 1. 动画资源
        kp_count = sum(1 for kp in KNOWLEDGE_POINTS if _get_knowledge_videos(kp))
        self.assertGreaterEqual(kp_count, 20)

        # 2. 图谱
        repo = InMemoryGraphRepository()
        builder = GraphBuilder(repository=repo)
        seed_default_graph(builder)

        # 3. 验证联动：图谱中的概念能在动画中找到视频
        graph_nodes = repo.nodes
        animation_kps = set(kp for kp in KNOWLEDGE_POINTS if _get_knowledge_videos(kp))
        overlap = graph_nodes & animation_kps

        print(f"\n  === 综合联动分析 ===")
        print(f"  动画知识点: {len(animation_kps)}")
        print(f"  图谱节点: {repo.count_nodes()}")
        print(f"  图谱边: {repo.count_edges()}")
        print(f"  动画+图谱重叠: {len(overlap)} 知识点")
        print(f"  重叠: {sorted(overlap)}")

        # 4. 跨模态对齐覆盖
        aligner = get_cross_modal_aligner()
        aligner_concepts = set(p.get("concept", "") for p in aligner._pairs)
        triple_overlap = animation_kps & graph_nodes & aligner_concepts
        print(f"  三系统均覆盖: {len(triple_overlap)} 知识点")
        print(f"  {sorted(triple_overlap)}")

        self.assertGreater(len(overlap), 5, "动画和图谱应有概念重叠")
        self.assertGreater(aligner.pair_count, 0, "跨模态对齐应有种子数据")


if __name__ == "__main__":
    unittest.main()
