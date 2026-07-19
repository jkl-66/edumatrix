import unittest
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, DBStudentProfile, run_db_op
from app.utils.recommendation_engine import get_smart_recommendations, CONCEPT_VIDEO_MAP
from models import Evidence, EvidenceModality
from rag_engine import hybrid_rag


class TestRecommendationEngine(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.student_id = "test-recommendation-student"

        # 初始化数据库连接并清除可能残留的旧数据
        self.db = SessionLocal()
        existing = self.db.query(DBStudentProfile).filter_by(student_id=self.student_id).first()
        if existing:
            self.db.delete(existing)
            self.db.commit()

        # 注入用于代码偏好测试的 mock 代码 Evidence
        self.code_evidence = Evidence(
            id="test-code-ev",
            title="梯度下降求解 Py 代码",
            content="```python\ndef gradient_descent():\n    pass\n```",
            modality=EvidenceModality.TEXT,
            source="gradient_descent.py",
            tags=("梯度下降",),
            anchors=()
        )
        hybrid_rag.ingest_user_documents((self.code_evidence,), owner_id=self.student_id)

    def tearDown(self):
        # 清除 mock 代码 Evidence
        hybrid_rag.remove_user_documents("gradient_descent.py", owner_id=self.student_id)

        existing = self.db.query(DBStudentProfile).filter_by(student_id=self.student_id).first()
        if existing:
            self.db.delete(existing)
            self.db.commit()
        self.db.close()

    def test_get_recommendations_cold_start(self):
        """测试冷启动时兜底推送"""
        recs = get_smart_recommendations(self.db, self.student_id, limit=3)
        self.assertGreater(len(recs), 0)
        for r in recs:
            self.assertIn("concept", r)
            self.assertIn("mastery", r)
            self.assertIn("badge", r)
            self.assertIn("reason", r)
            self.assertIn("resources", r)
            self.assertEqual(len(r["resources"]), 5)

    def test_modality_boosting_for_visual_preference(self):
        """测试对图示/视觉偏好进行资源加权"""
        # 创建学生画像，偏好设置为图示演示/视频讲解
        profile = DBStudentProfile(
            student_id=self.student_id,
            concept_mastery={"池化层": 0.25, "逻辑回归": 0.35},
            learning_goals=["池化层", "逻辑回归"],
            weak_points=["池化层"],
            interaction_preferences=["图示演示", "短视频讲解"],
            cognitive_style="图示型",
        )
        self.db.add(profile)
        self.db.commit()

        recs = get_smart_recommendations(self.db, self.student_id, limit=5)
        # 确保推荐资源中包含了视频微课 (CONCEPT_VIDEO_MAP 匹配项)
        has_video = any("video" in r["resources"] for r in recs)
        self.assertTrue(has_video, "Visual/Video preferences should include video micro-lessons in resources")

    def test_modality_boosting_for_coding_preference(self):
        """测试对代码偏好进行资源加权"""
        # 创建学生画像，偏好设置为代码实操
        profile = DBStudentProfile(
            student_id=self.student_id,
            concept_mastery={"机器学习": 0.80, "线性回归": 0.80, "梯度下降": 0.20, "微积分": 0.80, "概率统计": 0.80},
            learning_goals=["梯度下降"],
            weak_points=["梯度下降"],
            interaction_preferences=["代码实操"],
            cognitive_style="代码型",
        )
        self.db.add(profile)
        self.db.commit()

        recs = get_smart_recommendations(self.db, self.student_id, limit=5)
        # 检查首选推荐是否包含 code 资源或高权重的代码资源
        has_code = any("code" in r["resources"] for r in recs)
        self.assertTrue(has_code, "Coding preference should include code-based resources in resources")

    def test_recommendation_api_endpoint(self):
        """测试 /recommendations 路由端点是否正常连通并返回数据"""
        # 写入临时测试账号画像
        profile = DBStudentProfile(
            student_id=self.student_id,
            concept_mastery={"机器学习": 0.30},
            learning_goals=["机器学习"],
            weak_points=["机器学习"],
            interaction_preferences=["代码实操"],
            cognitive_style="代码型",
        )
        self.db.add(profile)
        self.db.commit()

        # 触发 API 请求 (修复前缀错误为 /api/profile)
        response = self.client.get(f"/api/profile/{self.student_id}/recommendations")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 1)

        # 验证 JSON 数据项 schema
        first_item = data[0]
        self.assertIn("concept", first_item)
        self.assertIn("mastery", first_item)
        self.assertIn("badge", first_item)
        self.assertIn("reason", first_item)
        self.assertIn("resources", first_item)

    def test_cognitive_matrix_and_personalized_outlines(self):
        """测试认知矩阵优先级计算、最高掌握度资源标记以及动态大纲编译"""
        profile = DBStudentProfile(
            student_id=self.student_id,
            concept_mastery={"机器学习": 0.80, "线性回归": 0.80, "梯度下降": 0.20, "微积分": 0.80, "概率统计": 0.80},
            learning_goals=["梯度下降"],
            weak_points=["梯度下降"],
            interaction_preferences=["代码实操"],
            cognitive_style="代码型",
            major="计算机科学与技术",
            learning_state_causes={"梯度下降": "公式理解困难，代码调试频繁报错"},
            frustration_index=0.85
        )
        self.db.add(profile)
        self.db.commit()

        recs = get_smart_recommendations(self.db, self.student_id, limit=3)
        self.assertGreater(len(recs), 0)
        
        target_rec = None
        for r in recs:
            if r["concept"] == "梯度下降":
                target_rec = r
                break
        
        self.assertIsNotNone(target_rec)
        resources = target_rec["resources"]
        
        # 1. 验证 5 个维度都已生成，且 priority 在合理区间内
        self.assertEqual(len(resources), 5)
        top_count = 0
        for key, res in resources.items():
            self.assertIn("priority", res)
            self.assertIn("is_top", res)
            self.assertIn("overview", res)
            if res["is_top"]:
                top_count += 1
                
        # 2. 验证有且仅有一个 resource 的 is_top 为 True
        self.assertEqual(top_count, 1, "Should have exactly one top-recommended resource")
        
        # 3. 验证代码型偏好下，is_top 被正确赋予了 "code"
        self.assertTrue(resources["code"]["is_top"], "For coding-style preference, 'code' resource should be is_top")
        
        # 4. 验证 overview 和 reason 是否包含了学科特异性及挫败感诊断特征
        overview_text = resources["code"]["overview"]
        reason_text = target_rec["reason"]
        
        self.assertIn("代码采用规范工程级写法", overview_text, "Overview should incorporate cs major engineering formatting")
        self.assertIn("已提供简易数据输入案例", overview_text, "Overview should contain scaffolding tips based on high frustration index")
        self.assertIn("代码型", reason_text, "Reason should incorporate the student's cognitive style")
