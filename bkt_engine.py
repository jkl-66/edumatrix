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


class KalmanFilter:
    """一维自适应卡尔曼滤波器，用于学情状态防抖平滑。"""
    
    def __init__(self, x_init: float = 0.3, p_init: float = 1.0) -> None:
        self.x = x_init  # 状态估计值 (掌握度)
        self.p = p_init  # 误差协方差
        
    def step(self, z: float, q: float, r: float) -> tuple[float, float]:
        """运行一步预测与更新。
        z: 观测值 (当前测量到的掌握度)
        q: 系统噪声协方差 (State Transition Noise)
        r: 测量噪声协方差 (Measurement Noise)
        """
        # 1. 预测 (Prediction)
        p_pred = self.p + q
        
        # 2. 更新 (Update)
        k_gain = p_pred / (p_pred + r)
        self.x = self.x + k_gain * (z - self.x)
        self.x = max(0.0, min(1.0, self.x))
        self.p = (1.0 - k_gain) * p_pred
        return self.x, k_gain


@dataclass
class BKTState:
    """单个知识点的 BKT 状态，整合卡尔曼滤波器。"""
    concept: str
    p_mastered: float = BKT_DEFAULTS["p_init"]      # P(L_t) 掌握概率
    p_learn: float = BKT_DEFAULTS["p_learn"]
    p_slip: float = BKT_DEFAULTS["p_slip"]
    p_guess: float = BKT_DEFAULTS["p_guess"]
    history: list[bool] = field(default_factory=list)  # 答题序列 (True=正确)

    # 新增 Kalman 状态存储字段（便于序列化与持久化）
    smoothed_mastery: float = BKT_DEFAULTS["p_init"]
    p_err: float = 0.1
    layers: dict[str, dict[str, Any]] = field(default_factory=dict)  # dimension -> {p_mastered, smoothed_mastery, p_err}

    kf: KalmanFilter = field(init=False, default=None)

    def __post_init__(self):
        self.kf = KalmanFilter(x_init=self.smoothed_mastery, p_init=self.p_err)
        if not self.layers:
            self.layers = {
                l: {
                    "p_mastered": self.p_mastered,
                    "smoothed_mastery": self.smoothed_mastery,
                    "p_err": self.p_err
                }
                for l in ("factual", "math", "code", "transfer")
            }

    def update(self, correct: bool, cognitive_load: float = 0.45, frustration: float = 0.0, dimension: str = "factual") -> float:
        """根据答题结果更新 BKT 状态，并通过自适应卡尔曼滤波器进行防抖平滑，支持特定认知层级维度。"""
        # 1. 更新全局主状态
        p_t = self.p_mastered
        if correct:
            p_correct = p_t * (1.0 - self.p_slip) + (1.0 - p_t) * self.p_guess
            p_mastered_given_obs = (p_t * (1.0 - self.p_slip)) / max(p_correct, 1e-10)
        else:
            p_wrong = p_t * self.p_slip + (1.0 - p_t) * (1.0 - self.p_guess)
            p_mastered_given_obs = (p_t * self.p_slip) / max(p_wrong, 1e-10)

        # HMM 状态转移
        raw_bkt_mastery = p_mastered_given_obs + (1.0 - p_mastered_given_obs) * self.p_learn
        raw_bkt_mastery = max(0.0, min(1.0, raw_bkt_mastery))
        
        self.p_mastered = raw_bkt_mastery
        self.history.append(correct)

        # 自适应协方差调整
        q_base = 0.01
        q_penalty = max(0.0, cognitive_load - 0.5) * 0.05 + max(0.0, frustration - 0.3) * 0.03
        q = q_base + q_penalty

        r_base = 0.1
        r_penalty = max(0.0, frustration - 0.5) * 0.08
        r = r_base + r_penalty

        # 执行卡尔曼滤波防抖更新
        if getattr(self, "kf", None) is None:
            self.kf = KalmanFilter(x_init=self.smoothed_mastery, p_init=self.p_err)
            
        x_smooth, k_gain = self.kf.step(raw_bkt_mastery, q, r)
        self.smoothed_mastery = x_smooth
        self.p_err = self.kf.p

        # 2. 更新指定认知层级（factual, math, code, transfer）
        if not self.layers:
            self.layers = {
                l: {
                    "p_mastered": BKT_DEFAULTS["p_init"],
                    "smoothed_mastery": BKT_DEFAULTS["p_init"],
                    "p_err": 0.1
                }
                for l in ("factual", "math", "code", "transfer")
            }
        
        if dimension not in self.layers:
            self.layers[dimension] = {
                "p_mastered": BKT_DEFAULTS["p_init"],
                "smoothed_mastery": BKT_DEFAULTS["p_init"],
                "p_err": 0.1
            }
            
        layer_state = self.layers[dimension]
        p_t_l = layer_state.get("p_mastered", BKT_DEFAULTS["p_init"])
        
        if correct:
            p_correct_l = p_t_l * (1.0 - self.p_slip) + (1.0 - p_t_l) * self.p_guess
            p_mastered_given_obs_l = (p_t_l * (1.0 - self.p_slip)) / max(p_correct_l, 1e-10)
        else:
            p_wrong_l = p_t_l * self.p_slip + (1.0 - p_t_l) * (1.0 - self.p_guess)
            p_mastered_given_obs_l = (p_t_l * self.p_slip) / max(p_wrong_l, 1e-10)
            
        raw_bkt_l = p_mastered_given_obs_l + (1.0 - p_mastered_given_obs_l) * self.p_learn
        raw_bkt_l = max(0.0, min(1.0, raw_bkt_l))
        layer_state["p_mastered"] = raw_bkt_l
        
        # 执行图层 Kalman 估计
        layer_kf = KalmanFilter(
            x_init=layer_state.get("smoothed_mastery", BKT_DEFAULTS["p_init"]),
            p_init=layer_state.get("p_err", 0.1)
        )
        x_smooth_l, _ = layer_kf.step(raw_bkt_l, q, r)
        layer_state["smoothed_mastery"] = x_smooth_l
        layer_state["p_err"] = layer_kf.p
        self.layers[dimension] = layer_state

        return self.smoothed_mastery


class BKTEngine:
    """贝叶斯知识追踪引擎：管理多个知识点的 BKT 状态。"""

    def __init__(self) -> None:
        self.states: dict[str, BKTState] = {}

    def get_or_create(self, concept: str, profile_bkt_states: dict[str, Any] | None = None) -> BKTState:
        if concept not in self.states:
            # 冷启动容错：若内存中没有，但数据库 Profile 缓存中存有历史状态快照，则进行反序列化重置
            if profile_bkt_states and concept in profile_bkt_states:
                snap = profile_bkt_states[concept]
                state = BKTState(
                    concept=concept,
                    p_mastered=snap.get("p_mastered", BKT_DEFAULTS["p_init"]),
                    p_learn=snap.get("p_learn", BKT_DEFAULTS["p_learn"]),
                    p_slip=snap.get("p_slip", BKT_DEFAULTS["p_slip"]),
                    p_guess=snap.get("p_guess", BKT_DEFAULTS["p_guess"]),
                    history=snap.get("history", []),
                    smoothed_mastery=snap.get("smoothed_mastery", snap.get("p_mastered", BKT_DEFAULTS["p_init"])),
                    p_err=snap.get("p_err", 0.1),
                    layers=snap.get("layers", {})
                )
                self.states[concept] = state
            else:
                self.states[concept] = BKTState(concept=concept)
        return self.states[concept]

    def update(
        self,
        concept: str,
        correct: bool,
        cognitive_load: float = 0.45,
        frustration: float = 0.0,
        profile_bkt_states: dict[str, Any] | None = None,
        dimension: str = "factual"
    ) -> float:
        return self.get_or_create(concept, profile_bkt_states).update(correct, cognitive_load, frustration, dimension)

    def get_mastery(self, concept: str, profile_bkt_states: dict[str, Any] | None = None) -> float:
        state = self.get_or_create(concept, profile_bkt_states)
        return getattr(state, "smoothed_mastery", state.p_mastered)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {
            concept: {
                "p_mastered": round(state.p_mastered, 4),
                "smoothed_mastery": round(getattr(state, "smoothed_mastery", state.p_mastered), 4),
                "p_err": round(getattr(state, "p_err", 0.1), 4),
                "attempts": len(state.history),
                "accuracy": sum(state.history) / max(len(state.history), 1),
                "layers": getattr(state, "layers", {})
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


class KnowledgeDiffusionEngine:
    """LMCD 知识扩散引擎：解决冷启动，自动将某个概念的掌握度变化向关联概念传播。"""

    def __init__(self, alpha: float = 0.4, gamma: float = 0.6) -> None:
        self.alpha = alpha     # 语义相似度权重 (余弦相似度)，其余为前置拓扑依赖权重
        self.gamma = gamma     # 拓扑距离衰减系数

    def diffuse(
        self,
        concept_mastery: dict[str, float],
        target_concept: str,
        delta: float,
        dag: dict[str, list[str]],
    ) -> dict[str, float]:
        """对知识点掌握度执行扩散。

        Args:
            concept_mastery: 当前所有的概念掌握度字典。
            target_concept: 发生变化的目标概念。
            delta: 掌握度变化量（如 +0.15 或 -0.1）。
            dag: DAG 知识依赖图。

        Returns:
            扩散更新后的概念掌握度字典。
        """
        if not concept_mastery or target_concept not in concept_mastery or abs(delta) < 1e-5:
            return concept_mastery

        from embedding_models import EMBEDDINGS, cosine_similarity

        # 获取目标概念的 Embedding
        target_vec = EMBEDDINGS.embed(target_concept)
        if not target_vec:
            return concept_mastery

        new_mastery = dict(concept_mastery)

        # 预计算到目标概念的拓扑距离（通过 BFS 寻找图中最短无向距离）
        topo_dist = self._compute_topo_distances(target_concept, dag)

        for concept in concept_mastery:
            if concept == target_concept:
                continue

            # 1. 语义相似度 (用 embedding 的余弦相似度计算)
            c_vec = EMBEDDINGS.embed(concept)
            sim = cosine_similarity(target_vec, c_vec) if c_vec else 0.0

            # 2. 拓扑依赖度计算 (如果 concept 是 target_concept 的直接前置或后继)
            prereq_weight = 0.0
            if concept in dag.get(target_concept, []):
                prereq_weight = 0.7  # 直接前置依赖
            elif target_concept in dag.get(concept, []):
                prereq_weight = 0.5  # 直接后继影响

            # 3. 转移概率权重
            p_ij = self.alpha * sim + (1 - self.alpha) * prereq_weight

            # 4. 拓扑距离衰减
            dist = topo_dist.get(concept, 4)  # 找不到距离时默认设定为 4 (远距离)
            decay = self.gamma ** dist

            # 5. 更新改变量
            diffusion_delta = delta * p_ij * decay
            new_val = concept_mastery[concept] + diffusion_delta
            new_mastery[concept] = max(0.0, min(1.0, new_val))

        return new_mastery

    def _compute_topo_distances(self, start: str, dag: dict[str, list[str]]) -> dict[str, int]:
        """通过无向 BFS 计算目标点到图中其他各概念的拓扑最短距离。"""
        # 构建无向图邻接表
        adj: dict[str, set[str]] = {}
        all_nodes = set(dag.keys())
        for parents in dag.values():
            all_nodes.update(parents)

        for node in all_nodes:
            adj[node] = set()

        for node, parents in dag.items():
            for p in parents:
                adj[node].add(p)
                adj[p].add(node)

        # BFS 算距离
        distances = {start: 0}
        queue = [start]
        head = 0
        while head < len(queue):
            curr = queue[head]
            head += 1
            curr_dist = distances[curr]
            for neighbor in adj.get(curr, []):
                if neighbor not in distances:
                    distances[neighbor] = curr_dist + 1
                    queue.append(neighbor)
        return distances

