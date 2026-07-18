import unittest
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, DBStudentProfile

class TestGoalRecommendations(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.student_id = "test-goals-student"
        
        self.db = SessionLocal()
        existing = self.db.query(DBStudentProfile).filter_by(student_id=self.student_id).first()
        if existing:
            self.db.delete(existing)
            self.db.commit()
            
        # Create student profile with some mastered/unmastered nodes
        profile = DBStudentProfile(
            student_id=self.student_id,
            concept_mastery={"机器学习": 0.80, "线性回归": 0.80, "梯度下降": 0.20},
            learning_goals=["梯度下降"],
            weak_points=["梯度下降"],
            interaction_preferences=["代码实操"],
            cognitive_style="代码型",
            major="计算机科学与技术"
        )
        self.db.add(profile)
        self.db.commit()

    def tearDown(self):
        existing = self.db.query(DBStudentProfile).filter_by(student_id=self.student_id).first()
        if existing:
            self.db.delete(existing)
            self.db.commit()
        self.db.close()

    def test_goal_recommendations_endpoint(self):
        response = self.client.get(f"/api/profile/{self.student_id}/goal-recommendations")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        
        # Verify structure
        first_path = data[0]
        self.assertIn("pathway_name", first_path)
        self.assertIn("target_concept", first_path)
        self.assertIn("description", first_path)
        self.assertIn("nodes", first_path)
        self.assertIn("completion_rate", first_path)
        self.assertIn("expected_minutes", first_path)
        self.assertIn("cognitive_load_index", first_path)
        
        # Verify completion rate and expected minutes are numeric
        self.assertIsInstance(first_path["completion_rate"], int)
        self.assertIsInstance(first_path["expected_minutes"], int)
        self.assertIsInstance(first_path["cognitive_load_index"], str)
        
        # Check node objects have mastered and percentage fields
        self.assertGreater(len(first_path["nodes"]), 0)
        first_node = first_path["nodes"][0]
        self.assertIn("concept", first_node)
        self.assertIn("percentage", first_node)
        self.assertIn("mastered", first_node)
        self.assertIn("is_ellipsis", first_node)
        self.assertIn("is_target", first_node)
