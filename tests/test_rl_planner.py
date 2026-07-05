import pytest
from app.database import SessionLocal, DBStudentProfile, run_db_op
from app.crud import load_student_profile, save_student_profile
from app.utils.rl_planner import QLearningPathPlanner, ACTIONS
from models import StudentProfile

class TestRLPathPlanner:
    def test_state_discretization(self):
        # 低掌握度，正常负载，低挫败
        state = QLearningPathPlanner.get_state_key(0.2, 0.3, 0.1)
        assert state == "LOW_NORMAL_LOW"

        # 中等掌握度，高负载，高挫败
        state = QLearningPathPlanner.get_state_key(0.5, 0.8, 0.6)
        assert state == "MID_HIGH_HIGH"

        # 高掌握度，正常负载，高挫败
        state = QLearningPathPlanner.get_state_key(0.85, 0.2, 0.95)
        assert state == "HIGH_NORMAL_HIGH"

    def test_reward_computation(self):
        # 正确答题且掌握度提升
        r1 = QLearningPathPlanner.calculate_reward(0.3, 0.45, True, 0.1, 0.2)
        # delta = 0.15 * 100 = 15.0, correct = +10.0, load/frustration = -0.5 - 0.4 = -0.9 -> 24.1
        assert r1 == 24.1

        # 答错题且挫败感与认知过载
        r2 = QLearningPathPlanner.calculate_reward(0.5, 0.48, False, 0.7, 0.8)
        # delta = -2.0, correct = -10.0, cost = -3.5 - 1.6 = -5.1 -> -17.1
        assert r2 == -17.1

    def test_q_table_updates_and_greedy_actions(self):
        class MockProfile:
            def __init__(self):
                self.rl_q_table = {}

        profile = MockProfile()
        state_before = "LOW_NORMAL_LOW"
        state_after = "MID_NORMAL_LOW"

        # 刚开始没有任何 Q 值，最佳决策应该返回 None
        best = QLearningPathPlanner.get_best_action(profile, state_before, epsilon=0.0)
        assert best is None

        # 执行一次高额奖励的更新
        QLearningPathPlanner.update_q_value(
            profile=profile,
            state_before=state_before,
            action="code",
            state_after=state_after,
            reward=50.0,
            alpha=0.1,
            gamma=0.9
        )

        assert state_before in profile.rl_q_table
        assert profile.rl_q_table[state_before]["code"] == 5.0  # 0.1 * 50 = 5.0

        # 现在由于 "code" 的 Q 值最大 (5.0 > 0.0)，最佳动作应该选择 "code"
        best = QLearningPathPlanner.get_best_action(profile, state_before, epsilon=0.0)
        assert best == "code"

    def test_persistence_integration(self):
        db = SessionLocal()
        student_id = "test-rl-persist-student"
        try:
            # 清理历史数据
            existing = db.query(DBStudentProfile).filter_by(student_id=student_id).first()
            if existing:
                db.delete(existing)
                db.commit()

            # 1. 加载并更新 Q 表和心智历史
            profile = load_student_profile(db, student_id)
            assert profile.rl_q_table == {}
            assert profile.mental_state_history == []

            profile.rl_q_table = {"LOW_NORMAL_LOW": {"lecture": 1.5, "code": 3.2}}
            profile.mental_state_history = [{"timestamp": "2026-07-05T00:00:00", "frustration": 0.2, "cognitive_load": 0.4}]
            save_student_profile(db, profile)

            # 2. 从数据库重新加载以断言持久化成功
            db.close()
            db = SessionLocal()
            loaded = load_student_profile(db, student_id)
            assert loaded.rl_q_table == {"LOW_NORMAL_LOW": {"lecture": 1.5, "code": 3.2}}
            assert len(loaded.mental_state_history) == 1
            assert loaded.mental_state_history[0]["frustration"] == 0.2

        finally:
            existing = db.query(DBStudentProfile).filter_by(student_id=student_id).first()
            if existing:
                db.delete(existing)
                db.commit()
            db.close()
