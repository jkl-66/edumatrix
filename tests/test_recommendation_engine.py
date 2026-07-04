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
        hybrid_rag.ingest_user_documents((self.code_evidence,))

    def tearDown(self):
        # 清除 mock 代码 Evidence
        hybrid_rag.remove_user_documents("gradient_descent.py")

        existing = self.db.query(DBStudentProfile).filter_by(student_id=self.student_id).first()
        if existing:
            self.db.delete(existing)
            self.db.commit()
        self.db.close()

    def test_get_recommendations_cold_start(self):
        """测试冷启动时兜底推送"""
        recs = get_smart_recommendations(self.db, self.student_id, limit=3)
        self.assertEqual(len(recs), 3)
        for r in recs:
            self.assertIn("concept", r)
            self.assertIn("score", r)
            self.assertIn("resource_type", r)
            self.assertIn("title", r)

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
        has_video = any(r["resource_type"] == "video" for r in recs)
        self.assertTrue(has_video, "Visual/Video preferences should boost video micro-lessons to be recommended")

    def test_modality_boosting_for_coding_preference(self):
        """测试对代码偏好进行资源加权"""
        # 创建学生画像，偏好设置为代码实操
        profile = DBStudentProfile(
            student_id=self.student_id,
            concept_mastery={"梯度下降": 0.20},
            learning_goals=["梯度下降"],
            weak_points=["梯度下降"],
            interaction_preferences=["代码实操"],
            cognitive_style="代码型",
        )
        self.db.add(profile)
        self.db.commit()

        recs = get_smart_recommendations(self.db, self.student_id, limit=5)
        # 检查首选推荐是否包含 code 资源或高权重的代码资源
        has_code = any(r["resource_type"] == "code" for r in recs)
        self.assertTrue(has_code, "Coding preference should boost code-based resources to be recommended")

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
        self.assertIn("resource_type", first_item)
        self.assertIn("title", first_item)
        self.assertIn("content", first_item)
        self.assertIn("badge", first_item)
        self.assertIn("reason", first_item)
