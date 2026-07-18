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
import numpy as np
import torch
import torch.nn as nn
import queue
import threading


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
        # 🟢 痛点 6 平替：根据概念类别分级设定不同的 Slip 和 Guess 参数，打破静态死锁
        concept_lower = self.concept.lower()
        if any(kw in concept_lower for kw in ("代码", "实现", "沙箱", "函数", "编程", "code", "eval", "sandbox")):
            # 编程实操类：失误率高，猜测率极低
            self.p_slip = 0.15
            self.p_guess = 0.10
        elif any(kw in concept_lower for kw in ("公式", "推导", "数学", "计算", "梯度", "回归", "向量", "math", "grad", "regression", "matrix", "entropy", "divergence")):
            # 数学推导类：中等猜测，高失误率
            self.p_slip = 0.12
            self.p_guess = 0.15
        else:
            # 事实概念类：猜测率高，失误率低
            self.p_slip = 0.08
            self.p_guess = 0.25

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
        
        # Load EKF calibrated parameters
        import os
        import json
        self.f_forward = 0.35
        self.f_backward = 0.0
        try:
            config_path = os.path.join(os.path.dirname(__file__), "data", "ekf_calibrated_params.json")
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f_cfg:
                    cfg = json.load(f_cfg)
                    self.f_forward = cfg.get("f_forward", 0.35)
                    self.f_backward = cfg.get("f_backward", 0.0)
        except Exception:
            pass

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
        dimension: str = "factual",
        duration_seconds: float | None = None
    ) -> float:
        state = self.get_or_create(concept, profile_bkt_states)
        old_mastery = getattr(state, "smoothed_mastery", state.p_mastered)
        new_mastery = state.update(
            correct, cognitive_load, frustration, dimension
        )
        
        # 图拓扑卡尔曼信念传播 (Graph-Kalman Belief Propagation) - 升级为 O(1) 局部子图扩展卡尔曼滤波 (Localized Graph-EKF)
        delta = new_mastery - old_mastery
        if abs(delta) > 1e-4:
            import numpy as np
            try:
                from profile_api import KNOWLEDGE_DAG
            except Exception:
                from agent_swarm import DEFAULT_KNOWLEDGE_DAG as KNOWLEDGE_DAG
            
            # 1. 提取局部活跃节点集 (当前概念 + 直接前置 + 直接后继)
            prereqs = KNOWLEDGE_DAG.get(concept, [])
            successors = [c for c, p_list in KNOWLEDGE_DAG.items() if concept in p_list]
            
            active_concepts = list(set([concept] + prereqs + successors))
            M = len(active_concepts)
            c_to_idx = {c: i for i, c in enumerate(active_concepts)}
            t_idx = c_to_idx[concept]
            
            # 2. 构造局部状态向量 x_local (M, 1) 与协方差 P_local (M, M)
            x_local = np.zeros((M, 1), dtype=np.float32)
            P_local = np.zeros((M, M), dtype=np.float32)
            
            p_diag = np.zeros(M, dtype=np.float32)
            for i, c in enumerate(active_concepts):
                if profile_bkt_states and c in profile_bkt_states:
                    x_local[i, 0] = profile_bkt_states[c].get("smoothed_mastery", BKT_DEFAULTS["p_init"])
                    p_diag[i] = profile_bkt_states[c].get("p_err", 0.1)
                else:
                    c_state = self.get_or_create(c, profile_bkt_states)
                    x_local[i, 0] = getattr(c_state, "smoothed_mastery", c_state.p_mastered)
                    p_diag[i] = getattr(c_state, "p_err", 0.1)
                    
            # 保证目标概念的旧掌握度反映在局部状态向量中以计算差分
            x_local[t_idx, 0] = old_mastery
            
            # 初始化协方差对角阵
            for i in range(M):
                P_local[i, i] = p_diag[i]
                
            # 根据依赖图局部构建物理一致的前向因果与反向纠偏转移矩阵 F_local (M, M)
            F_local = np.eye(M, dtype=np.float32)
            for i, c in enumerate(active_concepts):
                idx_i = c_to_idx[c]
                
                # 1. 前向传播 (prerequisites -> target)
                c_prereqs = KNOWLEDGE_DAG.get(c, [])
                active_prereqs = [p for p in c_prereqs if p in c_to_idx]
                total_prereqs = len(c_prereqs)
                if total_prereqs > 0:
                    F_local[idx_i, idx_i] -= self.f_forward
                    for p in active_prereqs:
                        idx_j = c_to_idx[p]
                        F_local[idx_i, idx_j] = self.f_forward / total_prereqs
                    
                    missing_count = total_prereqs - len(active_prereqs)
                    if missing_count > 0:
                        F_local[idx_i, idx_i] += missing_count * (self.f_forward / total_prereqs)
                
                # 2. 反向纠偏 (successors -> target/prereqs)
                # 找出在活跃子图中的直接后继
                active_successors = [succ for succ, p_list in KNOWLEDGE_DAG.items() if c in p_list and succ in c_to_idx]
                total_successors = len([succ for succ, p_list in KNOWLEDGE_DAG.items() if c in p_list])
                if total_successors > 0:
                    F_local[idx_i, idx_i] -= self.f_backward
                    for succ in active_successors:
                        idx_succ = c_to_idx[succ]
                        F_local[idx_i, idx_succ] = self.f_backward / total_successors
                    
                    missing_succ_count = total_successors - len(active_successors)
                    if missing_succ_count > 0:
                        F_local[idx_i, idx_i] += missing_succ_count * (self.f_backward / total_successors)


            # 4. 执行卡尔曼更新
            q_base = 0.01
            q_penalty = max(0.0, cognitive_load - 0.5) * 0.05 + max(0.0, frustration - 0.3) * 0.03
            Q_local = np.eye(M, dtype=np.float32) * (q_base + q_penalty)
            
            # 预测阶段 (引入全局阻尼系数 eta=0.95 并限制协方差上限，保障数值稳定性)
            eta = 0.95
            x_pred = np.dot(F_local, x_local)
            x_pred = np.clip(x_pred, 0.0, 1.0)
            P_pred = eta * np.dot(np.dot(F_local, P_local), F_local.T) + Q_local
            P_pred = np.clip(P_pred, 0.01, 10.0)
            
            # 观测更新阶段
            H_local = np.zeros((1, M), dtype=np.float32)
            H_local[0, t_idx] = 1.0
            
            r_base = 0.1
            r_penalty = max(0.0, frustration - 0.5) * 0.08
            if duration_seconds is not None:
                if duration_seconds < 3.0:
                    r_penalty += (3.0 - duration_seconds) * 0.15 + 0.2
                elif duration_seconds > 300.0:
                    r_penalty += 0.15
            R_scalar = r_base + r_penalty
            
            z = np.array([[new_mastery]], dtype=np.float32)
            R = np.array([[R_scalar]], dtype=np.float32)
            
            S = np.dot(np.dot(H_local, P_pred), H_local.T) + R
            denom = max(S[0, 0], 1e-6)
            K_gain = P_pred[:, t_idx:t_idx+1] / denom # (M, 1)
            
            residual = z - np.dot(H_local, x_pred)
            x_new = x_pred + K_gain * residual
            x_new = np.clip(x_new, 0.0, 1.0)
            
            P_new = np.dot(np.eye(M) - np.dot(K_gain, H_local), P_pred)
            P_new = 0.5 * (P_new + P_new.T)
            
            # 回写局部更新后的状态
            for i, c in enumerate(active_concepts):
                m_val = float(x_new[i, 0])
                p_val = max(0.01, min(10.0, float(P_new[i, i])))
                
                # 获取该概念在 BKTState 中的真实原始掌握度（防止 float 精度误差）
                if profile_bkt_states and c in profile_bkt_states:
                    orig_val = float(profile_bkt_states[c].get("smoothed_mastery", BKT_DEFAULTS["p_init"]))
                else:
                    c_state_tmp = self.get_or_create(c, profile_bkt_states)
                    orig_val = float(getattr(c_state_tmp, "smoothed_mastery", c_state_tmp.p_mastered))
                if abs(m_val - orig_val) < 1e-5:
                    m_val = orig_val
                
                c_state = self.get_or_create(c, profile_bkt_states)
                c_state.smoothed_mastery = m_val
                c_state.p_mastered = m_val
                c_state.p_err = p_val
                
                if profile_bkt_states and c in profile_bkt_states:
                    profile_bkt_states[c]["smoothed_mastery"] = round(m_val, 4)
                    profile_bkt_states[c]["p_mastered"] = round(m_val, 4)
                    profile_bkt_states[c]["p_err"] = round(p_val, 4)
            
            # 重设 new_mastery 值为 EKF 更新后的目标概念掌握度
            new_mastery = float(x_new[t_idx, 0])
            if profile_bkt_states and concept in profile_bkt_states:
                orig_target_val = float(profile_bkt_states[concept].get("smoothed_mastery", BKT_DEFAULTS["p_init"]))
            else:
                c_state_tmp = self.get_or_create(concept, profile_bkt_states)
                orig_target_val = float(getattr(c_state_tmp, "smoothed_mastery", c_state_tmp.p_mastered))
            if abs(new_mastery - orig_target_val) < 1e-5:
                new_mastery = orig_target_val
                
        return new_mastery

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
    使用高精度数值稳定性防护保护，确保 acosh 输入永远合法且分母不为零。
    """
    eps_guard = 1e-5
    norm_u = math.sqrt(sum(x * x for x in u))
    norm_v = math.sqrt(sum(x * x for x in v))

    if norm_u >= 1.0 - eps_guard:
        u = [x / (norm_u + eps_guard) * (1.0 - eps_guard) for x in u]
    if norm_v >= 1.0 - eps_guard:
        v = [x / (norm_v + eps_guard) * (1.0 - eps_guard) for x in v]

    norm_u_sq = sum(x * x for x in u)
    norm_v_sq = sum(x * x for x in v)

    diff_sq = sum((a - b) ** 2 for a, b in zip(u, v))
    denom = (1.0 - norm_u_sq) * (1.0 - norm_v_sq)
    denom = max(denom, 1e-8)
    
    delta = 1.0 + 2.0 * diff_sq / denom
    delta = max(1.0 + 1e-7, delta)
    return math.acosh(delta)


def project_to_ball(vec: list[float], eps: float = 1e-5) -> list[float]:
    """将向量投影到 Poincaré 单位球内部（用于距离计算）。"""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm >= 1.0:
        return [x / (norm * (1.0 + eps)) for x in vec]
    return list(vec)


class HmdsMlpProxy(nn.Module):
    """轻量级高维双曲到 2D Poincaré 圆盘投影的 MLP 代理网络"""
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(384, 128),
            nn.Tanh(),
            nn.Linear(128, 64),
            nn.Tanh(),
            nn.Linear(64, 2)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        coords = self.net(x)
        norms = torch.norm(coords, p=2, dim=-1, keepdim=True)
        scaled_coords = coords / torch.clamp(norms, min=1.0) * torch.clamp(norms, max=0.95)
        return scaled_coords


import concurrent.futures

_MDS_PROCESS_EXECUTOR = None
_MDS_EXECUTOR_LOCK = threading.Lock()

def _get_mds_process_executor() -> concurrent.futures.ProcessPoolExecutor:
    global _MDS_PROCESS_EXECUTOR
    if _MDS_PROCESS_EXECUTOR is None:
        with _MDS_EXECUTOR_LOCK:
            if _MDS_PROCESS_EXECUTOR is None:
                # Windows 环境下限制最大进程数为 2，避免高并发生成过多空闲 Python 进程
                _MDS_PROCESS_EXECUTOR = concurrent.futures.ProcessPoolExecutor(max_workers=2)
    return _MDS_PROCESS_EXECUTOR


def _poincare_mds_live_optimization_worker(concepts: list[str], high_dim_vecs: list[list[float]], initial_coords: dict[str, list[float]]) -> list[list[float]]:
    """MDS 双曲投影 Adam 优化的子进程 Worker，彻底释放主进程的 GIL 锁"""
    import torch
    import torch.optim as optim
    import numpy as np
    import math

    M = len(concepts)
    Z = torch.tensor(high_dim_vecs, dtype=torch.float32)  # (M, 384)
    dot_z = torch.sum(Z * Z, dim=-1)

    # 1. 计算高维成对双曲距离矩阵
    D_target = torch.zeros((M, M))
    for i in range(M):
        for j in range(i + 1, M):
            diff = torch.sum((Z[i] - Z[j]) ** 2, dim=-1)
            denom = torch.clamp((1.0 - dot_z[i]) * (1.0 - dot_z[j]), min=1e-6)
            delta = 1.0 + 2.0 * diff / denom
            d = torch.log(delta + torch.sqrt(torch.clamp(delta**2 - 1.0, min=1e-6)))
            D_target[i, j] = d
            D_target[j, i] = d

    # 2. 声明 2D 坐标 X，用已存在的缓存或微扰小随机数初始化
    X_data = torch.randn(M, 2) * 0.05
    for i, c in enumerate(concepts):
        if c in initial_coords:
            X_data[i] = torch.tensor(initial_coords[c], dtype=torch.float32)
    X = torch.nn.Parameter(X_data)

    optimizer = optim.Adam([X], lr=0.05)

    # 3. 运行 40 轮 Adam，带边界对数障碍惩罚
    for _ in range(40):
        optimizer.zero_grad()
        norms_sq = torch.sum(X * X, dim=-1)

        loss = 0.0
        for i in range(M):
            for j in range(i + 1, M):
                # 2D双曲距离
                diff_2d = torch.sum((X[i] - X[j])**2)
                denom_2d = torch.clamp((1.0 - norms_sq[i]) * (1.0 - norms_sq[j]), min=1e-6)
                delta_2d = 1.0 + 2.0 * diff_2d / denom_2d
                d_2d = torch.log(delta_2d + torch.sqrt(torch.clamp(delta_2d**2 - 1.0, min=1e-6)))

                # 距离惩罚权重
                weight = 1.0 / torch.clamp(D_target[i, j], min=0.1)
                loss += weight * (D_target[i, j] - d_2d) ** 2

        # 引入边界软惩罚：对数障碍函数
        barrier = -torch.sum(torch.log(1.0 - torch.clamp(norms_sq, max=0.99))) * 0.1
        total_loss = loss + barrier

        total_loss.backward()
        optimizer.step()

    with torch.no_grad():
        norms = torch.norm(X, p=2, dim=1, keepdim=True)
        final_X = X / torch.clamp(norms, min=1.0) * torch.clamp(norms, max=0.95)
        return final_X.numpy().tolist()


def _get_raw_poincare_coordinates(embeddings: dict[str, list[float]]) -> dict[str, list[float]]:
    """使用双曲多维尺度变换 (Hyperbolic MDS) 并结合本地数据库缓存，将高维双曲向量动态投影至 2D 庞加莱圆盘"""
    concepts = list(embeddings.keys())
    M = len(concepts)
    if M == 0:
        return {}
    if M == 1:
        return {concepts[0]: [0.0, 0.0]}

    try:
        from app.database import SessionLocal, DBConceptCoordinate
        db = SessionLocal()
        try:
            # 1. 尝试从数据库批量加载缓存
            cached_records = db.query(DBConceptCoordinate).filter(DBConceptCoordinate.concept_name.in_(concepts)).all()
            coord_map = {r.concept_name: [r.x, r.y] for r in cached_records}
        finally:
            db.close()
    except Exception as e:
        print(f"[HMDS DB Cache Read Error] {e}. Safe fallback to live calculation.")
        coord_map = {}

    missing_concepts = [c for c in concepts if c not in coord_map]
    
    # 2. 如果没有缺失的，直接返回缓存
    if not missing_concepts:
        return coord_map

    # 3. 尝试使用 pre-trained MLP 代理网络进行 O(1) 前向推理投影
    import os
    proxy_weights_path = os.path.join(os.path.dirname(__file__), "data", "hmds_mlp.pth")
    if os.path.exists(proxy_weights_path):
        try:
            proxy = HmdsMlpProxy()
            state_dict = torch.load(proxy_weights_path, map_location="cpu", weights_only=True)
            proxy.load_state_dict(state_dict)
            proxy.eval()
            
            from manifold_alignment import get_dag_depth
            input_vecs = []
            for c in missing_concepts:
                vec = embeddings[c]
                if not vec:
                    vec = [0.0] * 384
                norm_v = math.sqrt(sum(x * x for x in vec))
                if norm_v < 1e-9:
                    ball_vec = [0.0] * 384
                else:
                    direction = [x / norm_v for x in vec]
                    depth = get_dag_depth(c)
                    hyperbolic_norm = 0.82 * (1.0 - 0.72 ** (depth + 1))
                    ball_vec = [x * hyperbolic_norm for x in direction]
                input_vecs.append(ball_vec)
                
            with torch.no_grad():
                X_in = torch.tensor(input_vecs, dtype=torch.float32)
                coords_out = proxy(X_in).numpy()
                
            try:
                from app.database import SessionLocal, DBConceptCoordinate
                db = SessionLocal()
                try:
                    for idx, c in enumerate(missing_concepts):
                        x_val, y_val = float(coords_out[idx, 0]), float(coords_out[idx, 1])
                        coord_map[c] = [x_val, y_val]
                        db.merge(DBConceptCoordinate(concept_name=c, x=x_val, y=y_val))
                    db.commit()
                finally:
                    db.close()
            except Exception as e:
                print(f"[HMDS DB Cache Write Error] {e}")
                
            return {c: coord_map[c] for c in concepts}
        except Exception as e:
            print(f"[HMDS MLP Proxy Error] {e}. Falling back to live Adam optimization.")

    # 4. 如果没有代理网络权重，进行局部 LBFGS / Adam 优化，并应用边界障碍函数约束
    try:
        from manifold_alignment import get_dag_depth
        
        # 1. 准备高维 Poincaré 向量
        high_dim_vecs = []
        for c in concepts:
            vec = embeddings[c]
            if not vec:
                vec = [0.0] * 384
            # 确保在高维 Poincaré 单位球内
            norm_v = math.sqrt(sum(x * x for x in vec))
            if norm_v < 1e-9:
                ball_vec = [0.0] * 384
            else:
                direction = [x / norm_v for x in vec]
                depth = get_dag_depth(c)
                hyperbolic_norm = 0.82 * (1.0 - 0.72 ** (depth + 1))
                ball_vec = [x * hyperbolic_norm for x in direction]
            high_dim_vecs.append(ball_vec)

        # 2. 投递至多进程池执行，避免求导优化死锁 GIL
        executor = _get_mds_process_executor()
        future = executor.submit(_poincare_mds_live_optimization_worker, concepts, high_dim_vecs, coord_map)
        coords_list = future.result(timeout=10.0)
        
        coords_np = np.array(coords_list, dtype=np.float32)

        try:
            from app.database import SessionLocal, DBConceptCoordinate
            db = SessionLocal()
            try:
                for i, c in enumerate(concepts):
                    x_val, y_val = float(coords_np[i, 0]), float(coords_np[i, 1])
                    coord_map[c] = [x_val, y_val]
                    if c in missing_concepts:
                        db.merge(DBConceptCoordinate(concept_name=c, x=x_val, y=y_val))
                db.commit()
            finally:
                db.close()
        except Exception as e:
            print(f"[HMDS DB Cache Write Error] {e}")

        return {c: coord_map[c] for c in concepts}

    except Exception as e:
        # 降级兜底方案：使用确定性哈希角分布
        print(f"[HMDS Fallback] Error in HMDS: {e}. Falling back to deterministic circle layout.")
        coords = {}
        for i, concept in enumerate(concepts):
            vec = embeddings.get(concept)
            hyperbolic_norm = 0.5
            if vec:
                hyperbolic_norm = min(0.95, math.sqrt(sum(v * v for v in vec)))
            angle = (hash(concept) % 360) * math.pi / 180.0
            x = hyperbolic_norm * math.cos(angle)
            y = hyperbolic_norm * math.sin(angle)
            coords[concept] = [x, y]
        return coords


def poincare_to_2d_coordinates(embeddings: dict[str, list[float]]) -> dict[str, list[float]]:
    """将专业领域概念映射至 2D 庞加莱圆盘中，采用同心环深度分布与角度等间距对齐算法，保障极致的排版与疏密排版均匀度"""
    concepts = list(embeddings.keys())
    M = len(concepts)
    if M == 0:
        return {}
    if M == 1:
        return {concepts[0]: [0.0, 0.0]}

    from manifold_alignment import get_dag_depth
    
    # 1. 预先计算所有概念的层级深度并归类
    concept_depths = {}
    depth_groups = {}
    
    for c in concepts:
        depth = get_dag_depth(c)
        if depth == 0 and c != "机器学习":
            # 语义层级离散化避让：若非最底层根概念，但深度算得为0，说明其在 DAG 外，利用 Hash 自动离散分布，避免在圆心堆叠
            depth = (hash(c) % 4) + 1
        concept_depths[c] = depth
        depth_groups.setdefault(depth, []).append(c)

    # 2. 对每个同心圆环（即相同深度组）内的节点，进行角度等间距均匀分布分配
    final_coords = {}
    for depth, group in depth_groups.items():
        # 稳定排序，保障刷新或重算时坐标百分之百确定，不发生位置瞬移跳变
        group.sort()
        N = len(group)
        target_r = min(0.92, 0.22 + 0.16 * depth)
        
        for idx, c in enumerate(group):
            # 等分角度 + 基于深度层级的相位偏移量（staggered phase shift），防止不同圆环的节点在同一直线上重合，并达到极优的疏密均匀度
            angle = (idx / N) * 2.0 * math.pi + (depth * 0.6)
            x = target_r * math.cos(angle)
            y = target_r * math.sin(angle)
            final_coords[c] = [x, y]
            
    return final_coords


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
    """行为信号校验（平滑校准版）：聚合近3次答题正确率，使用 Sigmoid 连续门控调节掌握度，消除跃迁抖动。"""
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
        recent = accuracies[-3:]
        mean_acc = sum(recent) / len(recent)
        checked_count += 1

        # 使用 Sigmoid 连续缩放代替硬上限截断：
        # 当平均正确率低于阈值时，通过平滑的 Sigmoid 门控压制掌握度，同时避免了直接 hard-clamp 导致的零梯度和不连续性
        if mean_acc < accuracy_threshold:
            # 缩放因子：当 mean_acc 越低，缩放越狠；接近 threshold 时缩放因子接近 1
            # sigmoid_gate = 1 / (1 + exp(-k * (mean_acc - c)))
            # 这里 k=15, c=0.45 保证在 0.6 处平滑过渡
            diff = mean_acc - (accuracy_threshold - 0.15)
            sigmoid_scale = 1.0 / (1.0 + math.exp(-15.0 * diff))
            
            if concept in profile.concept_mastery:
                old_mastery = profile.concept_mastery[concept]
                # 连续平滑掌握度压制
                profile.concept_mastery[concept] = round(old_mastery * (sigmoid_scale * 0.5 + 0.5), 4)
            
            capped_concepts.append(concept)
            total_capped += 1

    if total_capped > 0:
        capped_ratio = total_capped / max(checked_count, 1)
        profile.metacognitive_mismatch = min(1.0, profile.metacognitive_mismatch + metacognitive_boost * capped_ratio)
        sanitized = True
    else:
        profile.metacognitive_mismatch = max(0.0, profile.metacognitive_mismatch - 0.05)
        sanitized = False

    report_parts = []
    if capped_concepts:
        report_parts.append(f"检测到 {len(capped_concepts)} 个概念近3次正确率偏低，已执行 Sigmoid 平滑校准限高")
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

        active_dag = self._resolve_active_dag(dag)

        # 获取目标概念的 Embedding
        target_vec = EMBEDDINGS.embed(target_concept)
        if not target_vec:
            return concept_mastery

        new_mastery = dict(concept_mastery)

        # 预计算到目标概念的拓扑距离（通过 BFS 寻找图中最短无向距离）
        topo_dist = self._compute_topo_distances(target_concept, active_dag)

        for concept in concept_mastery:
            if concept == target_concept:
                continue

            # 1. 语义相似度 (用 embedding 的余弦相似度计算)
            c_vec = EMBEDDINGS.embed(concept)
            sim = cosine_similarity(target_vec, c_vec) if c_vec else 0.0

            # 2. 拓扑依赖度计算 (如果 concept 是 target_concept 的直接前置或后继)
            prereq_weight = 0.0
            if concept in active_dag.get(target_concept, []):
                prereq_weight = 0.7  # 直接前置依赖
            elif target_concept in active_dag.get(concept, []):
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

    def _resolve_active_dag(self, dag: dict[str, list[str]]) -> dict[str, list[str]]:
        """Merge caller DAG with GraphRAG dynamic prerequisites when available."""
        active: dict[str, list[str]] = {
            str(concept): [str(item) for item in (prereqs or []) if item]
            for concept, prereqs in (dag or {}).items()
            if concept
        }
        try:
            from rag_engine import graph_rag

            reverse = getattr(graph_rag, "reverse", {}) or {}
            nodes = getattr(graph_rag, "nodes", set()) or set()
            if not nodes or not reverse:
                return active
            for target, prereqs in reverse.items():
                target_text = str(target).strip()
                if not target_text:
                    continue
                merged = active.setdefault(target_text, [])
                for prereq in prereqs or []:
                    prereq_text = str(prereq).strip()
                    if prereq_text and prereq_text != target_text and prereq_text not in merged:
                        merged.append(prereq_text)
                    active.setdefault(prereq_text, active.get(prereq_text, []))
        except Exception:
            return active
        return active

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


import numpy as np
import torch
import torch.nn as nn

# 映射当前系统默认的 26 个核心概念
CONCEPT_TO_INDEX = {
    "池化层": 0,
    "最大池化": 1,
    "平均池化": 2,
    "卷积核": 3,
    "特征图": 4,
    "反向传播": 5,
    "链式法则": 6,
    "梯度下降": 7,
    "逻辑回归": 8,
    "线性回归": 9,
    "决策树": 10,
    "支持向量机": 11,
    "过拟合": 12,
    "正则化": 13,
    "交叉验证": 14,
    "机器学习": 15,
    "监督学习": 16,
    "数据预处理": 17,
    "特征工程": 18,
    "模型评估": 19,
    "混淆矩阵": 20,
    "朴素贝叶斯": 21,
    "Transformer": 22,
    "注意力机制": 23,
    "神经网络": 24,
    "卷积神经网络": 25,
}
NUM_CONCEPTS = len(CONCEPT_TO_INDEX)


class DktRnnEngine(nn.Module):
    """基于双线性认知诊断投影的动态 DKT 网络"""
    def __init__(self, hidden_dim: int = 64):
        super().__init__()
        self.input_dim = 385  # 384D Embedding + 1D Response Accuracy
        self.hidden_dim = hidden_dim
        
        self.rnn = nn.GRU(self.input_dim, hidden_dim, batch_first=True)
        # 将隐藏状态映射到与词向量同维 of 384D 心智状态空间
        self.cognitive_projection = nn.Linear(hidden_dim, 384)
        # 缩放标量因子
        self.scale_factor = nn.Parameter(torch.tensor(5.0))
        
        # 确定性初始化，防止启动后推理结果不一致
        torch.manual_seed(42)
        for name, param in self.named_parameters():
            if 'weight' in name:
                nn.init.xavier_normal_(param.data)
            elif 'bias' in name:
                nn.init.constant_(param.data, 0.0)

        # Trainable Concept Embeddings with warm-start semantic prior
        from embedding_models import EMBEDDINGS
        initial_weights = torch.zeros(NUM_CONCEPTS, 384)
        for concept, idx in CONCEPT_TO_INDEX.items():
            vec = EMBEDDINGS.embed(concept)
            if vec:
                initial_weights[idx] = torch.tensor(vec, dtype=torch.float32)
            else:
                initial_weights[idx] = torch.randn(384) * 0.02
        self.concept_embeddings = nn.Embedding(NUM_CONCEPTS, 384)
        self.concept_embeddings.weight.data.copy_(initial_weights)
        
        # Learnable bilinear mapping matrix W_diag
        self.bilinear = nn.Linear(384, 384, bias=False)
        self.bilinear.weight.data.copy_(torch.eye(384) + torch.randn(384, 384) * 0.01)

    def forward(self, seq_embeddings: torch.Tensor, student_bias: torch.Tensor | None = None) -> torch.Tensor:
        """
        seq_embeddings: (batch_size, seq_len, 385)
        student_bias: (384,) or None -> 预测心智认知状态向量 s_t
        """
        out, _ = self.rnn(seq_embeddings)
        final_hidden = out[:, -1, :] # 提取序列末尾隐特征
        proj = self.cognitive_projection(final_hidden)
        if student_bias is not None:
            # Add batch dimension to student_bias if missing
            if student_bias.dim() == 1:
                student_bias = student_bias.unsqueeze(0)
            proj = proj + student_bias
        s_t = torch.tanh(proj)
        return s_t


class DktService:
    """DKT 推理与增量学习服务单例包装 (二分类 BCE 正确率估计版本 - Option B 个性化偏置)"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance.model = DktRnnEngine()
                cls._instance.optimizer = torch.optim.Adam(cls._instance.model.parameters(), lr=0.001)
                cls._instance.loss_fn = nn.BCEWithLogitsLoss() # 使用 BCE 拟合答题正确率
                cls._instance.model_loaded = True
                
                # 初始化线程安全更新队列与后台消费线程 (用于兼容旧测试)
                cls._instance.update_queue = queue.Queue()
                cls._instance.worker_thread = threading.Thread(target=cls._instance._worker_loop, daemon=True)
                cls._instance.worker_thread.start()
                
                # Load pre-trained weights if they exist
                import os
                weights_path = os.path.join(os.path.dirname(__file__), "data", "dkt_weights.pth")
                if os.path.exists(weights_path):
                    try:
                        # 使用 weights_only=True 安全加载模型，消除 FutureWarning 警告
                        state_dict = torch.load(weights_path, map_location="cpu", weights_only=True)
                        # 检查加载的权重结构是否匹配 (input_dim=385, cognitive_projection.weight shape=[384, 64])
                        proj_key = "cognitive_projection.weight"
                        if proj_key in state_dict and state_dict[proj_key].shape == (384, 64):
                            cls._instance.model.load_state_dict(state_dict, strict=False)
                            print(f"[DKT Service] Successfully loaded dynamic pre-trained weights from {weights_path}")
                        else:
                            print(f"[DKT Service] Shape mismatch in {weights_path}. Initialized a fresh dynamic model.")
                    except Exception as e:
                        print(f"[DKT Service] Failed to load pre-trained weights: {e}. Initialized a fresh dynamic model.")
                else:
                    print(f"[DKT Service] Warning: No pre-trained weights found at {weights_path}. Using initialized weights.")
                    
                cls._instance.model.eval()
        return cls._instance

    def predict_mastery(self, history_records: list[tuple[str, bool]], extra_concepts: list[str] | None = None, student_bias: list[float] | None = None) -> dict[str, float]:
        """根据学生最近 50 次答题序列与学生专属偏置推理最新的概念掌握度，支持动态额外概念追踪"""
        seq_len = min(50, len(history_records))
        target_concepts = set(CONCEPT_TO_INDEX.keys())
        if extra_concepts:
            target_concepts.update(extra_concepts)
        for c, _ in history_records[-seq_len:]:
            target_concepts.add(c)
            
        if seq_len == 0:
            return {c: 0.3 for c in target_concepts}
            
        from embedding_models import EMBEDDINGS
        recent_records = history_records[-seq_len:]
        input_matrix = np.zeros((1, seq_len, 385), dtype=np.float32)
        
        for t, (concept, correct) in enumerate(recent_records):
            vec = EMBEDDINGS.embed(concept) or [0.0] * 384
            input_matrix[0, t, :384] = vec
            input_matrix[0, t, 384] = 1.0 if correct else 0.0
        
        # 封装专属偏置为 Tensor
        if student_bias and len(student_bias) == 384:
            bias_tensor = torch.tensor(student_bias, dtype=torch.float32)
        else:
            bias_tensor = torch.tensor([0.0] * 384, dtype=torch.float32)
        
        # 推理在 torch.no_grad() 下是天然线程安全的，不需要对主模型加互斥锁进行同步
        with torch.no_grad():
            tensor_in = torch.from_numpy(input_matrix)
            s_t = self.model(tensor_in, bias_tensor).squeeze(0) # (384,)
            
        # 计算所有概念在当前信念下的答对概率 (mastery)
        preds = {}
        for concept in target_concepts:
            concept_idx = CONCEPT_TO_INDEX.get(concept)
            c_vec = EMBEDDINGS.embed(concept)
            if concept_idx is not None:
                # Embedding 查表与双线性投影矩阵计算在参数冻结下线程安全
                c_tensor = self.model.concept_embeddings(torch.tensor(concept_idx))
                logit = torch.dot(self.model.bilinear(s_t), c_tensor) * self.model.scale_factor
                preds[concept] = float(torch.sigmoid(logit))
            elif c_vec:
                c_tensor = torch.tensor(c_vec, dtype=torch.float32)
                logit = torch.dot(self.model.bilinear(s_t), c_tensor) * self.model.scale_factor
                preds[concept] = float(torch.sigmoid(logit))
            else:
                preds[concept] = 0.3
        return preds

    def train_incremental(self, history_records: list[tuple[str, bool]], profile: Any = None):
        """在线对比增量微调 (支持单例和个性化偏置双模模式)"""
        if len(history_records) < 2:
            return
        if profile is not None:
            # 方案 B：个性化偏置更新，在调用线程中同步执行 (通常在 asyncio 线程池中)
            self._train_step(history_records, profile)
        else:
            # 兼容模式：推入后台队列
            self.update_queue.put(history_records)

    def _worker_loop(self):
        """后台单线程工作循环"""
        import time
        while True:
            try:
                item = self.update_queue.get()
                if item is None:
                    break
                if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], object) and not isinstance(item[1], list):
                    records, profile = item
                else:
                    records, profile = item, None
                self._train_step(records, profile)
                self.update_queue.task_done()
            except Exception as e:
                print(f"[DKT Service Worker Loop Error] {e}")
                time.sleep(1.0)

    def _train_step(self, history_records: list[tuple[str, bool]], profile: Any = None):
        """真正的个性化偏置梯度更新步骤，只对 student_bias 进行更新"""
        try:
            from embedding_models import EMBEDDINGS
            seq_len = min(50, len(history_records))
            recent_records = history_records[-seq_len:]
            
            # 构造输入序列 X (1, seq_len-1, 385)
            input_matrix = np.zeros((1, seq_len - 1, 385), dtype=np.float32)
            for t in range(seq_len - 1):
                concept, correct = recent_records[t]
                vec = EMBEDDINGS.embed(concept) or [0.0] * 384
                input_matrix[0, t, :384] = vec
                input_matrix[0, t, 384] = 1.0 if correct else 0.0
                
            last_concept, last_correct = recent_records[-1]
            last_vec = torch.tensor(EMBEDDINGS.embed(last_concept) or [0.0] * 384, dtype=torch.float32)
            target_label = torch.tensor([1.0 if last_correct else 0.0], dtype=torch.float32)
            
            # 读取当前学生专属偏置，若无则初始化为全零
            bias_list = getattr(profile, "dkt_bias", None) if profile else None
            if not bias_list or len(bias_list) != 384:
                bias_list = [0.0] * 384
            
            student_bias = torch.tensor(bias_list, dtype=torch.float32, requires_grad=True)
            
            # 冻结全局模型参数，只对 student_bias 向量求偏导
            with self._lock:
                self.model.eval()
                for param in self.model.parameters():
                    param.requires_grad = False
                
                tensor_in = torch.from_numpy(input_matrix)
                s_t = self.model(tensor_in, student_bias).squeeze(0) # (384,)
                
                # 计算最后一步的预测正确率 logit
                concept_idx = CONCEPT_TO_INDEX.get(last_concept)
                if concept_idx is not None:
                    c_tensor = self.model.concept_embeddings(torch.tensor(concept_idx))
                    logit = torch.dot(self.model.bilinear(s_t), c_tensor) * self.model.scale_factor
                else:
                    logit = torch.dot(self.model.bilinear(s_t), last_vec) * self.model.scale_factor
                
                # 使用二分类交叉熵损失进行时序反向传播
                loss = self.loss_fn(logit.unsqueeze(0), target_label)
                loss.backward()
                
                # 手动对 student_bias 执行 SGD 增量更新步骤 (学习率设为 0.05)
                lr = 0.05
                with torch.no_grad():
                    if student_bias.grad is not None:
                        updated_bias = student_bias - lr * student_bias.grad
                        # 限制偏置在合理范围以内防止数值溢出/发散
                        updated_bias = torch.clamp(updated_bias, -1.0, 1.0)
                        new_bias_list = updated_bias.tolist()
                    else:
                        new_bias_list = bias_list
                
            # 将更新后的偏置写回 profile 内存，由调用者在外层事务中 commit 持久化
            if profile:
                profile.dkt_bias = new_bias_list
        except Exception as e:
            print(f"[DKT Service Incremental Training Step Error] {e}")



