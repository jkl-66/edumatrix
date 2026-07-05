import random
from typing import Any, Dict, List, Optional

ACTIONS = ["lecture", "mindmap", "code", "quiz", "video"]

class QLearningPathPlanner:
    @staticmethod
    def get_state_key(mastery: float, load: float, frustration: float) -> str:
        """
        将连续的学情特征离散化为 12 种状态组合
        """
        if mastery < 0.35:
            m_cat = "LOW"
        elif mastery < 0.75:
            m_cat = "MID"
        else:
            m_cat = "HIGH"

        l_cat = "HIGH" if load >= 0.6 else "NORMAL"
        f_cat = "HIGH" if frustration >= 0.4 else "LOW"

        return f"{m_cat}_{l_cat}_{f_cat}"

    @staticmethod
    def calculate_reward(
        old_mastery: float,
        new_mastery: float,
        correct: Optional[bool],
        frustration: float,
        load: float
    ) -> float:
        """
        根据学习交互前后的学情变化以及认知开销计算即时奖励值 R
        """
        # 核心学情掌握度提升奖励
        reward = (new_mastery - old_mastery) * 100.0

        # 答题正误奖励/惩罚
        if correct is True:
            reward += 10.0
        elif correct is False:
            reward -= 10.0

        # 心智开销惩罚 (情绪挫败与认知过载)
        reward -= (5.0 * frustration + 2.0 * load)

        return round(reward, 2)

    @staticmethod
    def update_q_value(
        profile: Any,
        state_before: str,
        action: str,
        state_after: str,
        reward: float,
        alpha: float = 0.1,
        gamma: float = 0.9
    ) -> None:
        """
        执行 Q-learning 强化更新步骤 (TD-learning)
        """
        if not hasattr(profile, "rl_q_table") or profile.rl_q_table is None:
            profile.rl_q_table = {}

        # 初始化当前状态的动作价值
        if state_before not in profile.rl_q_table:
            profile.rl_q_table[state_before] = {act: 0.0 for act in ACTIONS}

        # 初始化目标状态的动作价值
        if state_after not in profile.rl_q_table:
            profile.rl_q_table[state_after] = {act: 0.0 for act in ACTIONS}

        current_q = profile.rl_q_table[state_before].get(action, 0.0)

        # 找出目标状态的最大估算 Q 值
        next_q_values = profile.rl_q_table[state_after].values()
        max_next_q = max(next_q_values) if next_q_values else 0.0

        # TD-target 与 TD-error 计算
        td_target = reward + gamma * max_next_q
        new_q = current_q + alpha * (td_target - current_q)

        profile.rl_q_table[state_before][action] = round(new_q, 4)

    @staticmethod
    def get_best_action(
        profile: Any,
        state_key: str,
        epsilon: float = 0.15
    ) -> Optional[str]:
        """
        获取当前学情状态下的最优推荐资源类型 (Epsilon-Greedy 决策)
        """
        if not hasattr(profile, "rl_q_table") or profile.rl_q_table is None:
            profile.rl_q_table = {}

        if state_key not in profile.rl_q_table:
            profile.rl_q_table[state_key] = {act: 0.0 for act in ACTIONS}

        # Epsilon 随机探索
        if random.random() < epsilon:
            return random.choice(ACTIONS)

        # Greedy 贪婪决策：选择最大 Q 值的动作
        q_dict = profile.rl_q_table[state_key]
        
        # 若所有动作价值仍为 0 (初始态)，则返回 None 让传统推荐规则起效，避免冷启动盲目推荐
        if all(val == 0.0 for val in q_dict.values()):
            return None

        # 选择最大值对应的 Action
        best_act = max(q_dict, key=q_dict.get)
        return best_act
