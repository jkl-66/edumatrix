"""P0 任务 7.1: 贝叶斯知识追踪引擎 (BKT) + ZPD 动态剪枝 + Poincaré 双曲距离。

技术要点：
1. BKT: HMM 双状态(掌握/未掌握)更新 P(L_t)
2. ZPD 动态剪枝: mastery [0.3, 0.75] 为最近发展区
3. Poincaré 双曲距离: 解决概念间的双曲空间距离
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


# === BKT 参数默认值（来自经典文献） ===
BKT_DEFAULTS = {
    "p_init": 0.3,        # 初始掌握概率
    "p_learn": 0.1,       # 每次学习后未掌握→掌握的概率（学习转化率）
    "p_slip": 0.1,        # 掌握后做错的概率（粗心）
    "p_guess": 0.2,       # 未掌握但做对的概率（猜测）
}


@dataclass
class BKTState:
    """单个知识点的 BKT 状态。"""
    concept: str
    p_mastered: float = BKT_DEFAULTS["p_init"]      # P(L_t) 掌握概率
    p_learn: float = BKT_DEFAULTS["p_learn"]
    p_slip: float = BKT_DEFAULTS["p_slip"]
    p_guess: float = BKT_DEFAULTS["p_guess"]
    history: list[bool] = field(default_factory=list)  # 答题序列 (True=正确)

    def update(self, correct: bool) -> float:
        """根据答题结果更新 P(L_t)，返回更新后的掌握概率。"""
        p_t = self.p_mastered
        if correct:
            # P(correct) = p_t * (1 - slip) + (1 - p_t) * guess
            p_correct = p_t * (1 - self.p_slip) + (1 - p_t) * self.p_guess
            # P(L_t | correct) = p_t * (1 - slip) / P(correct)
            p_mastered_given_obs = (p_t * (1 - self.p_slip)) / max(p_correct, 1e-10)
        else:
            p_wrong = p_t * self.p_slip + (1 - p_t) * (1 - self.p_guess)
            p_mastered_given_obs = (p_t * self.p_slip) / max(p_wrong, 1e-10)

        # HMM 转义：考虑从未掌握到掌握的学习转换
        # P(L_{t+1}) = P(L_t|obs) + (1 - P(L_t|obs)) * p_learn
        self.p_mastered = p_mastered_given_obs + (1 - p_mastered_given_obs) * self.p_learn
        self.p_mastered = max(0.0, min(1.0, self.p_mastered))
        self.history.append(correct)
        return self.p_mastered


class BKTEngine:
    """贝叶斯知识追踪引擎：管理多个知识点的 BKT 状态。"""

    def __init__(self) -> None:
        self.states: dict[str, BKTState] = {}

    def get_or_create(self, concept: str) -> BKTState:
        if concept not in self.states:
            self.states[concept] = BKTState(concept=concept)
        return self.states[concept]

    def update(self, concept: str, correct: bool) -> float:
        return self.get_or_create(concept).update(correct)

    def get_mastery(self, concept: str) -> float:
        return self.states[concept].p_mastered if concept in self.states else BKT_DEFAULTS["p_init"]

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {
            concept: {
                "p_mastered": round(state.p_mastered, 4),
                "attempts": len(state.history),
                "accuracy": sum(state.history) / max(len(state.history), 1),
            }
            for concept, state in self.states.items()
        }


# === ZPD 动态剪枝 ===

# ZPD 区间: 任务7.1要求锚定 [0.3, 0.75] 为最近发展区
ZPD_LOWER = 0.3
ZPD_UPPER = 0.75


def classify_zpd_zone(mastery: float) -> str:
    """根据掌握度将知识点分类到 ZPD 区间。"""
    if mastery < ZPD_LOWER:
        return "below_zpd"  # 前置知识不足，需要补习
    elif mastery <= ZPD_UPPER:
        return "in_zpd"     # 最近发展区，可以教学
    else:
        return "above_zpd"  # 已掌握，需要跳到进阶/复习


def should_rollback_to_prerequisites(
    target_mastery: float,
    prereq_masteries: dict[str, float],
    threshold: float = 0.5,
) -> tuple[bool, list[str]]:
    """任务7.1要求: 当目标概念的前置依赖节点掌握度低于 0.5 时，自动回溯到前置。"""
    weak_prereqs = [
        prereq for prereq, mastery in prereq_masteries.items()
        if mastery < threshold
    ]
    return (len(weak_prereqs) > 0, weak_prereqs)


def get_zpd_path_plan(
    target: str,
    target_mastery: float,
    graph_neighbors: dict[str, list[str]],  # concept -> [prerequisites]
    prereq_masteries: dict[str, float],
) -> dict[str, Any]:
    """生成 ZPD 动态路径规划。

    Returns:
        {
            "path": [concepts in order],
            "rollback_to": [...] or None,
            "difficulty": "basic" | "intermediate" | "advanced",
            "explanation": "..."
        }
    """
    zone = classify_zpd_zone(target_mastery)
    needs_rollback, weak_prereqs = should_rollback_to_prerequisites(
        target_mastery,
        {p: prereq_masteries.get(p, 0.3) for p in graph_neighbors.get(target, [])},
    )

    if needs_rollback:
        return {
            "path": weak_prereqs + [target],
            "rollback_to": weak_prereqs,
            "difficulty": "basic",
            "explanation": f"目标掌握度仅 {target_mastery:.2f}，前置 {weak_prereqs} 掌握不足，先补习前置再进入目标。",
        }

    if zone == "in_zpd":
        return {
            "path": [target],
            "rollback_to": None,
            "difficulty": "intermediate",
            "explanation": f"目标在最近发展区 ({ZPD_LOWER}≤{target_mastery:.2f}≤{ZPD_UPPER})，直接教学。",
        }

    if zone == "above_zpd":
        return {
            "path": [target, "进阶应用"],
            "rollback_to": None,
            "difficulty": "advanced",
            "explanation": f"已掌握目标 ({target_mastery:.2f}>{ZPD_UPPER})，进入进阶应用层。",
        }

    return {
        "path": weak_prereqs + [target],
        "rollback_to": weak_prereqs,
        "difficulty": "basic",
        "explanation": f"目标掌握度 {target_mastery:.2f} 过低，从前置开始。",
    }


# === Poincaré 双曲距离 ===

def poincare_distance(u: list[float], v: list[float], eps: float = 1e-9) -> float:
    """计算单位球内两点 u, v 之间的 Poincaré 双曲距离。

    公式: d(u,v) = arcosh(1 + 2|u-v|^2 / ((1-|u|^2)(1-|v|^2)))
    """
    norm_u_sq = sum(x * x for x in u)
    norm_v_sq = sum(x * x for x in v)

    if norm_u_sq >= 1.0 - eps:
        # 投影到单位球内
        norm_u = math.sqrt(norm_u_sq)
        u = [x / (norm_u * (1.0 + eps)) for x in u]
        norm_u_sq = sum(x * x for x in u)
    if norm_v_sq >= 1.0 - eps:
        norm_v = math.sqrt(norm_v_sq)
        v = [x / (norm_v * (1.0 + eps)) for x in v]
        norm_v_sq = sum(x * x for x in v)

    diff_sq = sum((a - b) ** 2 for a, b in zip(u, v))
    delta = 1.0 + 2.0 * diff_sq / max((1.0 - norm_u_sq) * (1.0 - norm_v_sq), eps)
    delta = max(1.0, delta)
    return math.acosh(delta)


def project_to_ball(vec: list[float], eps: float = 1e-5) -> list[float]:
    """将向量投影到 Poincaré 单位球内部（用于距离计算）。"""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm >= 1.0:
        return [x / (norm * (1.0 + eps)) for x in vec]
    return list(vec)


def poincare_to_2d_coordinates(embeddings: dict[str, list[float]]) -> dict[str, list[float]]:
    """将双曲嵌入映射到 2D 平面坐标（用于前端 ECharts 可视化）。

    使用：保留向量的前两维 + norm 作为半径，越接近原点掌握度越高。
    """
    coords = {}
    for concept, vec in embeddings.items():
        # 安全处理：取前 2 维，钳制在 [-0.99, 0.99]
        x = max(-0.99, min(0.99, vec[0] if len(vec) > 0 else 0.0))
        y = max(-0.99, min(0.99, vec[1] if len(vec) > 1 else 0.0))
        coords[concept] = [x, y]
    return coords


def find_nearest_concept(
    target: str,
    target_embedding: list[float],
    candidates: dict[str, list[float]],
) -> tuple[str, float]:
    """在双曲空间中找到距离目标最近的概念（用于困难时跳转）。"""
    target_in_ball = project_to_ball(target_embedding)
    best_concept = ""
    best_dist = float("inf")
    for candidate, embedding in candidates.items():
        if candidate == target:
            continue
        candidate_in_ball = project_to_ball(embedding)
        dist = poincare_distance(target_in_ball, candidate_in_ball)
        if dist < best_dist:
            best_dist = dist
            best_concept = candidate
    return best_concept, best_dist


# ============================================================
# 任务 7.2: 艾宾浩斯遗忘衰减引擎
# ============================================================

# 默认遗忘衰减系数 beta (Ebbinghaus)
EBBINGHAUS_BETA_DEFAULT = 0.5
EBBINGHAUS_BETA_MIN = 0.3
EBBINGHAUS_BETA_MAX = 0.8


def ebbinghaus_decay(
    mastery_last: float,
    hours_passed: float,
    beta: float = EBBINGHAUS_BETA_DEFAULT,
) -> float:
    """艾宾浩斯遗忘衰减公式。

    M_decayed = M_last * (t_passed / 24.0 + 1.0) ^ (-beta)

    Args:
        mastery_last: 上一次的掌握度 (0~1)
        hours_passed: 自上次更新起经过的小时数
        beta: 衰减速度系数 (0.3~0.8)，认知负荷高时用更快的衰减

    Returns:
        衰减后的掌握度 (0~1)
    """
    beta = max(EBBINGHAUS_BETA_MIN, min(EBBINGHAUS_BETA_MAX, beta))
    decay_factor = (hours_passed / 24.0 + 1.0) ** (-beta)
    return max(0.0, min(1.0, mastery_last * decay_factor))


def compute_decay_beta(cognitive_load: float, frustration_index: float) -> float:
    """根据认知负荷和挫败感动态计算衰减系数 beta。

    认知负荷越高、挫败感越强 → beta 越大 → 衰减越快。
    """
    base_beta = EBBINGHAUS_BETA_DEFAULT
    load_penalty = max(0.0, cognitive_load - 0.5) * 0.6       # 负荷>0.5时加速
    frustration_penalty = max(0.0, frustration_index - 0.3) * 0.4  # 挫败>0.3时加速
    return max(EBBINGHAUS_BETA_MIN, min(EBBINGHAUS_BETA_MAX,
                                         base_beta + load_penalty + frustration_penalty))


class EbbinghausDecayEngine:
    """艾宾浩斯遗忘衰减引擎：管理全知识点衰减调度。"""

    @staticmethod
    def decay_profile(profile: "StudentProfile") -> dict[str, float]:
        """对画像中的全部知识点执行遗忘衰减。

        从 profile.last_update_timestamp 计算经过时间，
        对 profile.concept_mastery 中的每个知识点执行 ebbinghaus_decay。

        Returns:
            dict[concept, new_mastery] — 衰减后的掌握度
        """
        from datetime import datetime, timezone
        from models import StudentProfile

        last_str = profile.last_update_timestamp
        try:
            last_time = datetime.fromisoformat(last_str)
        except (ValueError, TypeError):
            last_time = datetime.now(timezone.utc)

        now = datetime.now(timezone.utc)
        # 确保 last_time 也带时区
        if last_time.tzinfo is None:
            last_time = last_time.replace(tzinfo=timezone.utc)

        hours_passed = max(0.0, (now - last_time).total_seconds() / 3600.0)

        # 无有效时间差，直接返回当前状态
        if hours_passed < 1.0:
            return dict(profile.concept_mastery)

        beta = compute_decay_beta(profile.cognitive_load, profile.frustration_index)
        decayed = {}
        for concept, mastery in profile.concept_mastery.items():
            decayed[concept] = ebbinghaus_decay(mastery, hours_passed, beta)
        return decayed

    @staticmethod
    def apply_decay_to_profile(profile: "StudentProfile") -> None:
        """对 StudentProfile 原地执行遗忘衰减。"""
        decayed = EbbinghausDecayEngine.decay_profile(profile)
        profile.concept_mastery.update(decayed)
        from datetime import datetime, timezone
        profile.last_update_timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ============================================================
# 任务 7.2: 行为信号校验 (认知自洽校验 Sanity Check)
# ============================================================


def behavior_sanity_check(
    profile: "StudentProfile",
    quiz_accuracy: dict[str, list[float]] | None = None,
    accuracy_threshold: float = 0.6,
    metacognitive_boost: float = 0.30,
    mastery_cap: float = 0.5,
) -> dict[str, Any]:
    """行为信号校验：聚合近3次答题正确率，检测"说会了但做不对"的元认知偏差。

    核心逻辑（任务7.2要求）：
    - 聚合近 3 次答题正确率
    - 若均值 < 0.6:
        - 强制将概念掌握上限锁死 mastery_cap (0.5)
        - 上调 metacognitive_mismatch 30%
    - 若均值 >= 0.6: 反向校准，降低 metacognitive_mismatch

    Args:
        profile: 学生画像
        quiz_accuracy: 可选的外部 quiz 正确率数据 (concept -> [最近3次正确率])
                        若为 None 则使用 profile.recent_quiz_accuracy
        accuracy_threshold: 正确率阈值 (默认 0.6)
        metacognitive_boost: 偏差上调比例 (默认 0.30)
        mastery_cap: 掌握度上限 (默认 0.5)

    Returns:
        {
            "sanitized": bool,          # 是否发生制裁
            "capped_concepts": list,     # 被强制限高的知识点
            "metacognitive_mismatch_new": float,
            "report": str               # 诊断报告
        }
    """
    from models import StudentProfile

    data = quiz_accuracy if quiz_accuracy is not None else profile.recent_quiz_accuracy
    if not data:
        return {
            "sanitized": False,
            "capped_concepts": [],
            "metacognitive_mismatch_new": profile.metacognitive_mismatch,
            "report": "无答题数据，跳过行为信号校验。",
        }

    capped_concepts: list[str] = []
    total_capped = 0
    checked_count = 0

    for concept, accuracies in data.items():
        if not accuracies:
            continue
        # 取最近 3 次
        recent = accuracies[-3:]
        mean_acc = sum(recent) / len(recent)
        checked_count += 1

        if mean_acc < accuracy_threshold:
            # 强制锁死掌握上限
            if concept in profile.concept_mastery:
                profile.concept_mastery[concept] = min(profile.concept_mastery[concept], mastery_cap)
            capped_concepts.append(concept)
            total_capped += 1

    # 更新 metacognitive_mismatch
    if total_capped > 0:
        # 需要上调：有概念被制裁
        capped_ratio = total_capped / max(checked_count, 1)
        profile.metacognitive_mismatch = min(1.0, profile.metacognitive_mismatch +
                                             metacognitive_boost * capped_ratio)
        sanitized = True
    else:
        # 一切正常，小幅下调
        profile.metacognitive_mismatch = max(0.0, profile.metacognitive_mismatch - 0.05)
        sanitized = False

    report_parts = []
    if capped_concepts:
        report_parts.append(f"检测到 {len(capped_concepts)} 个概念近3次正确率 < {accuracy_threshold}，"
                            f"掌握度上限锁死 {mastery_cap}")
        report_parts.append(f"认知偏差指标上调至 {profile.metacognitive_mismatch:.2f}")
    else:
        report_parts.append(f"全部 {checked_count} 个概念通过行为信号校验")

    return {
        "sanitized": sanitized,
        "capped_concepts": capped_concepts,
        "metacognitive_mismatch_new": profile.metacognitive_mismatch,
        "report": "；".join(report_parts),
    }
