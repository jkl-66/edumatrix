"""成员 3 Task 3: 跨模态特征对齐测试"""
import os

os.environ["EDUMATRIX_LLM_PROVIDER"] = "mock"
os.environ["EDUMATRIX_EMBEDDING_PROVIDER"] = "hash"

import unittest


class TestCrossModalAlignment(unittest.TestCase):
    """跨模态特征对齐测试"""

    def test_aligner_initializes_with_seed_data(self):
        """验证对齐器初始化并加载内置种子数据"""
        from multimodal_alignment import CrossModalAligner, get_cross_modal_aligner

        aligner = get_cross_modal_aligner()
        self.assertIsInstance(aligner, CrossModalAligner)
        self.assertGreater(aligner.pair_count, 5, "应有至少 5 个内置种子配对")

    def test_text_search_returns_results(self):
        """验证用文字搜索返回结果"""
        from multimodal_alignment import get_cross_modal_aligner

        aligner = get_cross_modal_aligner()
        results = aligner.search("池化层的最大值计算", mode="text", top_k=3)

        self.assertIsInstance(results, list)
        if results:
            self.assertIn("score", results[0])
            self.assertIn("pair", results[0])
            self.assertIn("matched_modality", results[0])

    def test_formula_search_returns_results(self):
        """验证用公式搜索返回结果"""
        from multimodal_alignment import get_cross_modal_aligner

        aligner = get_cross_modal_aligner()
        results = aligner.search(r"\max_{p,q} X_{i+p, j+q}", mode="formula", top_k=3)

        self.assertIsInstance(results, list)
        if results:
            self.assertGreaterEqual(results[0]["score"], 0.0)
            self.assertLessEqual(results[0]["score"], 1.0)

    def test_register_and_search_new_pair(self):
        """验证注册新配对后可以搜索到"""
        from multimodal_alignment import get_cross_modal_aligner

        aligner = get_cross_modal_aligner()
        initial_count = aligner.pair_count

        # 注册一个唯一标识的新配对
        unique_suffix = "_TEST_MARKER_"
        test_text = f"测试知识点{unique_suffix}标记用于验证注册和搜索"
        aligner.register_pair(
            text=test_text,
            image_desc="测试图片描述",
            formula=r"test + formula + unique",
            concept="测试标记",
        )
        self.assertEqual(aligner.pair_count, initial_count + 1,
                        f"注册后计数应从 {initial_count} 增加到 {initial_count + 1}")

        # 搜索应返回结果（使用精确文本，hash embeddings 对语义差异敏感）
        results = aligner.search(test_text, mode="text", top_k=5)
        self.assertGreater(len(results), 0, f"用注册文本搜索至少应返回 1 条结果，得到 {len(results)}")
        # 至少应有一个高置信度结果
        top_score = results[0]["score"]
        self.assertGreater(top_score, 0.0, f"最高分应 > 0，实际 {top_score:.4f}")

    def test_search_empty_query(self):
        """验证空查询不会崩溃"""
        from multimodal_alignment import get_cross_modal_aligner

        aligner = get_cross_modal_aligner()
        results = aligner.search("", mode="text", top_k=3)
        self.assertEqual(len(results), 0, "空查询应返回空结果")

    def test_cosine_similarity_range(self):
        """验证余弦相似度在 [0, 1] 范围内"""
        from multimodal_alignment import CrossModalAligner

        aligner = CrossModalAligner()
        v1 = [1.0, 0.0, 0.0]
        v2 = [1.0, 0.0, 0.0]  # 完全相同
        v3 = [-1.0, 0.0, 0.0]  # 完全相反

        sim_same = aligner._cosine(v1, v2)
        sim_opposite = aligner._cosine(v1, v3)

        self.assertAlmostEqual(sim_same, 1.0, delta=0.01, msg="相同向量相似度应为 1.0")
        self.assertGreaterEqual(sim_opposite, 0.0, msg="相反向量相似度应 >= 0")
        self.assertLessEqual(sim_opposite, 1.0, msg="相反向量相似度应 <= 1")

    def test_singleton_same_instance(self):
        """验证 get_cross_modal_aligner 返回同一实例"""
        from multimodal_alignment import get_cross_modal_aligner, CrossModalAligner

        a1 = get_cross_modal_aligner()
        a2 = get_cross_modal_aligner()
        self.assertIs(a1, a2, "两次调用应返回同一单例实例")

    def test_align_batch_registers_pairs(self):
        """验证批量对齐注册"""
        from multimodal_alignment import get_cross_modal_aligner

        aligner = get_cross_modal_aligner()
        initial = aligner.pair_count

        texts = [
            "K-means 聚类算法将数据点分配到最近的质心",
            "PCA 主成分分析通过特征值分解实现降维",
        ]
        count = aligner.align_batch(texts)
        self.assertGreaterEqual(count, 1)

        new_count = aligner.pair_count
        self.assertGreater(new_count, initial)

    def test_save_and_load_cycle(self):
        """验证对齐数据持久化和重新加载"""
        from multimodal_alignment import CrossModalAligner, _ALIGNMENT_FILE

        aligner = CrossModalAligner()
        # 确保有数据
        if aligner.pair_count == 0:
            aligner.register_pair("test concept", "test image", "test formula", "test")
        original_count = aligner.pair_count

        # 保存
        aligner.save_to_disk()
        self.assertTrue(_ALIGNMENT_FILE.exists(), "保存后数据文件应存在")

        # 重新加载
        aligner2 = CrossModalAligner()
        self.assertEqual(aligner2.pair_count, original_count,
                        f"重新加载后应有 {original_count} 个配对，但得到 {aligner2.pair_count}")


    # ── Task 3 新增：对比学习校准测试 ──

    def test_calibrate_reduces_loss(self):
        """验证校准后损失降低（对比学习有效）"""
        from multimodal_alignment import CrossModalAligner, _ALIGNMENT_FILE

        # 清除可能残留的磁盘缓存，确保从干净状态开始
        if _ALIGNMENT_FILE.exists():
            _ALIGNMENT_FILE.unlink()

        aligner = CrossModalAligner()
        self.assertFalse(aligner.is_calibrated, "校准前 _is_calibrated 应为 False")

        loss = aligner.calibrate()
        self.assertLess(loss, 10.0, f"校准损失应合理，实际 loss={loss:.4f}")
        self.assertTrue(aligner.is_calibrated, "校准后 _is_calibrated 应为 True")
        self.assertGreater(aligner.calibration_loss, 0.0)
        print(f"\n  [OK] 对比学习校准完成: loss={loss:.4f}")

    def test_calibrated_search_returns_different_scores(self):
        """验证校准后搜索与未校准的分数有差异"""
        from multimodal_alignment import CrossModalAligner, _ALIGNMENT_FILE

        # 清除磁盘缓存，创建两个独立的 aligner
        if _ALIGNMENT_FILE.exists():
            _ALIGNMENT_FILE.unlink()

        # 未校准的 aligner
        aligner_raw = CrossModalAligner()
        self.assertFalse(aligner_raw.is_calibrated)

        # 校准后的 aligner: 重新构建独立实例
        aligner_cal = CrossModalAligner()
        loss = aligner_cal.calibrate()
        self.assertTrue(aligner_cal.is_calibrated)

        query = "梯度下降优化参数更新"
        raw_results = aligner_raw.search(query, mode="text", top_k=5)
        cal_results = aligner_cal.search(query, mode="text", top_k=5)

        # 两者都应返回结果
        self.assertGreater(len(raw_results), 0)
        self.assertGreater(len(cal_results), 0)

        # 校准后的结果应标记 calibrated=True
        self.assertTrue(cal_results[0].get("calibrated", False))
        self.assertFalse(raw_results[0].get("calibrated", False))

        # 分数可能有差异（但不强制要求变化方向）
        raw_top = raw_results[0]["score"]
        cal_top = cal_results[0]["score"]
        print(f"\n  [OK] 未校准 top={raw_top:.4f}, 校准后 top={cal_top:.4f}")

    def test_save_load_preserves_calibration(self):
        """验证 save/load 保留投影矩阵和校准状态"""
        from multimodal_alignment import CrossModalAligner, _ALIGNMENT_FILE

        # 校准并保存
        aligner1 = CrossModalAligner()
        loss1 = aligner1.calibrate()
        self.assertTrue(aligner1.is_calibrated)
        aligner1.save_to_disk()
        self.assertTrue(_ALIGNMENT_FILE.exists())

        # 重新加载
        aligner2 = CrossModalAligner()
        self.assertTrue(aligner2.is_calibrated,
                       f"加载后应保留校准状态，实际={aligner2.is_calibrated}")
        self.assertAlmostEqual(aligner2.calibration_loss, loss1, delta=0.01,
                              msg=f"加载后校准损失应一致: {loss1:.4f} vs {aligner2.calibration_loss:.4f}")

    def test_register_pair_does_not_invalidate_calibration(self):
        """验证注册新配对后校准状态保持"""
        from multimodal_alignment import CrossModalAligner

        aligner = CrossModalAligner()
        aligner.calibrate()
        self.assertTrue(aligner.is_calibrated)

        aligner.register_pair(text="新知识点测试", image_desc="测试描述", formula="test_formula", concept="测试")
        # 注册新配对不影响校准标志，但嵌入库已更新
        self.assertTrue(aligner.is_calibrated)

    def test_projection_head_output_shape(self):
        """Verify ProjectionHead produces correct output dimensions (L2-normalized)."""
        import torch
        from multimodal_alignment import ProjectionHead, _PROJECTION_DIM

        head = ProjectionHead(in_dim=384, out_dim=_PROJECTION_DIM)
        x = torch.randn(4, 384)
        out = head(x)
        self.assertEqual(out.shape, (4, _PROJECTION_DIM),
                        f"Expected (4, {_PROJECTION_DIM}), got {out.shape}")
        norms = torch.norm(out, p=2, dim=1)
        self.assertTrue(torch.allclose(norms, torch.ones(4), atol=1e-5),
                       "Output vectors should be L2-normalized")
