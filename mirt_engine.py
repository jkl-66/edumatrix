from __future__ import annotations

import math
import random
from typing import Any, List, Dict
from dataclasses import dataclass, field


@dataclass
class IRTItemParams:
    alpha: list[float] = field(default_factory=lambda: [1.0, 1.0, 1.0])  # 3D 区分度向量 (Theory, Coding, Math)
    beta: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])   # 3D 难度向量 (Theory, Coding, Math)
    gamma: float = 0.25                                                 # 猜测率

    def __post_init__(self):
        if isinstance(self.alpha, (int, float)):
            self.alpha = [float(self.alpha), float(self.alpha) * 0.8, float(self.alpha) * 0.6]
        if isinstance(self.beta, (int, float)):
            self.beta = [float(self.beta), float(self.beta) + 0.1, float(self.beta) - 0.1]

    def to_dict(self) -> dict[str, Any]:
        return {"alpha": self.alpha, "beta": self.beta, "gamma": self.gamma}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> IRTItemParams:
        # 兼容老版标量格式与新版列表格式
        raw_alpha = d.get("alpha", 1.0)
        if isinstance(raw_alpha, (int, float)):
            alpha = [float(raw_alpha), float(raw_alpha) * 0.8, float(raw_alpha) * 0.6]
        else:
            if isinstance(raw_alpha, str):
                try:
                    import json
                    raw_alpha = json.loads(raw_alpha)
                except Exception:
                    raw_alpha = [1.0, 1.0, 1.0]
            alpha = [float(x) for x in raw_alpha]

        raw_beta = d.get("beta", 0.0)
        if isinstance(raw_beta, (int, float)):
            beta = [float(raw_beta), float(raw_beta) + 0.1, float(raw_beta) - 0.1]
        else:
            if isinstance(raw_beta, str):
                try:
                    import json
                    raw_beta = json.loads(raw_beta)
                except Exception:
                    raw_beta = [0.0, 0.0, 0.0]
            beta = [float(x) for x in raw_beta]

        return cls(
            alpha=alpha,
            beta=beta,
            gamma=float(d.get("gamma", 0.25)),
        )


@dataclass
class AdaptiveTestEstimator:
    theta: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])      # 3D 能力估计向量 (Theory, Coding, Math)
    theta_std: list[float] = field(default_factory=lambda: [1.0, 1.0, 1.0])  # 3D 能力估计标准差
    prior_mean: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0]) # 3D 先验均值
    prior_std: list[float] = field(default_factory=lambda: [1.0, 1.0, 1.0])  # 3D 先验标准差
    response_history: list[dict[str, Any]] = field(default_factory=list)
    theta_cov: list[list[float]] = None

    def __post_init__(self):
        if isinstance(self.theta, (int, float)):
            self.theta = [float(self.theta), float(self.theta) * 0.8, float(self.theta) * 0.6]
        if isinstance(self.theta_std, (int, float)):
            self.theta_std = [float(self.theta_std), float(self.theta_std), float(self.theta_std)]
        if isinstance(self.prior_mean, (int, float)):
            self.prior_mean = [float(self.prior_mean), float(self.prior_mean), float(self.prior_mean)]
        if isinstance(self.prior_std, (int, float)):
            self.prior_std = [float(self.prior_std), float(self.prior_std), float(self.prior_std)]

        if self.theta_cov is None:
            self.theta_cov = [
                [self.theta_std[0]**2, 0.0, 0.0],
                [0.0, self.theta_std[1]**2, 0.0],
                [0.0, 0.0, self.theta_std[2]**2]
            ]

    def _logistic(self, x: float) -> float:
        if x > 700:
            return 1.0
        if x < -700:
            return 0.0
        return 1.0 / (1.0 + math.exp(-x))

    def _probability_correct(self, theta: list[float], item: IRTItemParams) -> float:
        """3D MIRT 多维补偿性 3PL 模型概率计算公式"""
        # z = sum(alpha_d * (theta_d - beta_d))
        z = sum(a * (t - b) for a, t, b in zip(item.alpha, theta, item.beta))
        return item.gamma + (1.0 - item.gamma) * self._logistic(z)

    def _probability_derivative(self, theta: list[float], item: IRTItemParams, dim: int) -> float:
        """P 对 theta_dim 维度的偏导数"""
        z = sum(a * (t - b) for a, t, b in zip(item.alpha, theta, item.beta))
        p_logistic = self._logistic(z)
        # dP/d_theta_d = (1-gamma) * alpha_d * L(z) * (1 - L(z))
        return (1.0 - item.gamma) * item.alpha[dim] * p_logistic * (1.0 - p_logistic)

    def fisher_information(self, theta: list[float], item: IRTItemParams) -> float:
        """计算 MIRT 的 Fisher 信息量标量指标 (基于 trace 迹优化，即三维信息量之和)"""
        P = self._probability_correct(theta, item)
        if P <= 0.0 or P >= 1.0:
            return 0.0
        
        info_sum = 0.0
        for d in range(3):
            P_prime = self._probability_derivative(theta, item, d)
            info_sum += (P_prime * P_prime) / (P * (1.0 - P))
        return info_sum

    def compute_log_likelihood(self, theta: list[float]) -> float:
        ll = 0.0
        for entry in self.response_history:
            item = entry["item"]
            correct = entry["correct"]
            P = self._probability_correct(theta, item)
            P = max(1e-15, min(1.0 - 1e-15, P))
            if correct:
                ll += math.log(P)
            else:
                ll += math.log(1.0 - P)
        return ll

    def compute_log_prior(self, theta: list[float]) -> float:
        log_prior = 0.0
        for d in range(3):
            z = (theta[d] - self.prior_mean[d]) / self.prior_std[d]
            log_prior += -0.5 * z * z - math.log(self.prior_std[d] * math.sqrt(2.0 * math.pi))
        return log_prior

    def compute_log_posterior(self, theta: list[float]) -> float:
        return self.compute_log_likelihood(theta) + self.compute_log_prior(theta)

    def _estimate_theta_map(self, theta_init: list[float], step: float = 0.5, iterations: int = 50) -> list[float]:
        """多维 MAP (最大后验估计) 能力向量更新 (3D 梯度下降)"""
        theta = list(theta_init)
        for _ in range(iterations):
            grad = self._posterior_gradient(theta)
            grad_norm = math.sqrt(sum(g * g for g in grad))
            if grad_norm < 0.001:
                break
            # 沿梯度更新每一维能力值
            for d in range(3):
                theta[d] += step * grad[d]
                # 限制能力取值区间在 [-4.0, 4.0]
                theta[d] = max(-4.0, min(4.0, theta[d]))
            step *= 0.95
        return theta

    def _posterior_gradient(self, theta: list[float]) -> list[float]:
        grad = [0.0, 0.0, 0.0]
        # 1) 似然部分梯度
        for entry in self.response_history:
            item = entry["item"]
            correct = entry["correct"]
            P = self._probability_correct(theta, item)
            P = max(1e-15, min(1.0 - 1e-15, P))
            
            for d in range(3):
                P_prime = self._probability_derivative(theta, item, d)
                if correct:
                    grad[d] += P_prime / P
                else:
                    grad[d] -= P_prime / (1.0 - P)
        # 2) 先验部分梯度
        for d in range(3):
            prior_grad = -(theta[d] - self.prior_mean[d]) / (self.prior_std[d] * self.prior_std[d])
            grad[d] += prior_grad
        return grad

    def update_ability(self, item: IRTItemParams, correct: bool) -> list[float]:
        self.response_history.append({"item": item, "correct": correct})
        self.theta = self._estimate_theta_map(self.theta)
        self.theta_std = self._estimate_std()
        return self.theta

    def _estimate_std(self) -> list[float]:
        # Compute the full 3x3 information matrix Omega
        omega = [[0.0, 0.0, 0.0] for _ in range(3)]
        
        # 1) Add prior information (diagonal)
        for d in range(3):
            omega[d][d] = 1.0 / max(1e-5, self.prior_std[d] * self.prior_std[d])
            
        # 2) Add likelihood information from response history
        for entry in self.response_history:
            item = entry["item"]
            P = self._probability_correct(self.theta, item)
            P = max(1e-15, min(1.0 - 1e-15, P))
            
            # gradient vector g
            g = [self._probability_derivative(self.theta, item, d) for d in range(3)]
            
            # info = g * g^T / (P * (1 - P))
            for r in range(3):
                for s in range(3):
                    omega[r][s] += (g[r] * g[s]) / (P * (1.0 - P))
                    
        # 3) Invert Omega to get Covariance Matrix Sigma
        det = (
            omega[0][0] * (omega[1][1] * omega[2][2] - omega[1][2]**2)
            - omega[0][1] * (omega[0][1] * omega[2][2] - omega[0][2] * omega[1][2])
            + omega[0][2] * (omega[0][1] * omega[1][2] - omega[0][2] * omega[1][1])
        )
        
        # If matrix is singular or near singular, add a ridge factor (L2 regularization)
        if abs(det) < 1e-9:
            ridge = 1e-4
            for d in range(3):
                omega[d][d] += ridge
            # Recompute determinant
            det = (
                omega[0][0] * (omega[1][1] * omega[2][2] - omega[1][2]**2)
                - omega[0][1] * (omega[0][1] * omega[2][2] - omega[0][2] * omega[1][2])
                + omega[0][2] * (omega[0][1] * omega[1][2] - omega[0][2] * omega[1][1])
            )
            
        det = max(1e-15, det)
        
        # Compute cofactor elements for symmetric inverse
        c00 = omega[1][1] * omega[2][2] - omega[1][2]**2
        c01 = -(omega[0][1] * omega[2][2] - omega[0][2] * omega[1][2])
        c02 = omega[0][1] * omega[1][2] - omega[0][2] * omega[1][1]
        c11 = omega[0][0] * omega[2][2] - omega[0][2]**2
        c12 = -(omega[0][0] * omega[1][2] - omega[0][1] * omega[0][2])
        c22 = omega[0][0] * omega[1][1] - omega[0][1]**2
        
        cov = [
            [c00 / det, c01 / det, c02 / det],
            [c01 / det, c11 / det, c12 / det],
            [c02 / det, c12 / det, c22 / det]
        ]
        
        # Update self.theta_cov
        self.theta_cov = cov
        
        # Update and return self.theta_std (square roots of diagonal elements of covariance matrix)
        stds = [
            math.sqrt(max(1e-5, cov[0][0])),
            math.sqrt(max(1e-5, cov[1][1])),
            math.sqrt(max(1e-5, cov[2][2]))
        ]
        return stds

    def compute_d_optimality(self, theta: list[float], item: IRTItemParams) -> float:
        """计算三维 MIRT 的 Bayesian D-optimality (行列式最大化) 选题指标，包含协方差项"""
        P = self._probability_correct(theta, item)
        P = max(1e-5, min(1.0 - 1e-5, P))
        
        # 偏导数 g_d = dP/d_theta_d
        g = [self._probability_derivative(theta, item, i) for i in range(3)]
        
        # 计算 g^T * Sigma * g
        g_t_cov_g = 0.0
        for r in range(3):
            for s in range(3):
                g_t_cov_g += g[r] * self.theta_cov[r][s] * g[s]
                
        # 计算当前的 det_info (1 / det_cov)
        det_cov = (
            self.theta_cov[0][0] * (self.theta_cov[1][1] * self.theta_cov[2][2] - self.theta_cov[1][2]**2)
            - self.theta_cov[0][1] * (self.theta_cov[0][1] * self.theta_cov[2][2] - self.theta_cov[0][2] * self.theta_cov[1][2])
            + self.theta_cov[0][2] * (self.theta_cov[0][1] * self.theta_cov[1][2] - self.theta_cov[0][2] * self.theta_cov[1][1])
        )
        det_info = 1.0 / max(1e-15, det_cov)
        
        return det_info * (1.0 + g_t_cov_g / (P * (1.0 - P)))

    def select_next_item(
        self,
        candidate_items: list[dict[str, Any]],
        exclude_ids: set[str] | None = None,
        use_d_optimality: bool = True,
    ) -> dict[str, Any] | None:
        if not candidate_items:
            return None
        exclude = exclude_ids or set()
        best_item = None
        best_metric = -1.0
        for item_data in candidate_items:
            if str(item_data.get("id")) in exclude:
                continue
            irt_params = self._extract_irt_params(item_data)
            if use_d_optimality:
                metric = self.compute_d_optimality(self.theta, irt_params)
            else:
                metric = self.fisher_information(self.theta, irt_params)
            if metric > best_metric:
                best_metric = metric
                best_item = item_data
        return best_item

    def _extract_irt_params(self, item_data: dict[str, Any]) -> IRTItemParams:
        # Check flat keys first (prioritizing vector versions if they exist)
        a_val = item_data.get("irt_alpha_vec")
        if a_val is None:
            a_val = item_data.get("discrimination", item_data.get("irt_alpha", 1.0))
            
        b_val = item_data.get("irt_beta_vec")
        if b_val is None:
            b_val = item_data.get("difficulty_beta", item_data.get("irt_beta", 0.0))
            
        g_val = float(item_data.get("guessing_gamma", item_data.get("irt_gamma", 0.25)))
        
        # Check nested dict
        irt_raw = item_data.get("irt_params", {})
        if isinstance(irt_raw, dict) and irt_raw:
            # Prioritize JSON vector if they exist in irt_raw
            a_raw = irt_raw.get("alpha_vec", irt_raw.get("alpha"))
            b_raw = irt_raw.get("beta_vec", irt_raw.get("beta"))
            g_raw = irt_raw.get("gamma", g_val)
            return IRTItemParams.from_dict({"alpha": a_raw, "beta": b_raw, "gamma": g_raw})
            
        return IRTItemParams.from_dict({"alpha": a_val, "beta": b_val, "gamma": g_val})

    def get_estimated_difficulty_label(self) -> str:
        # 基于三维能力的均值给出难度标签
        avg_theta = sum(self.theta) / 3.0
        if avg_theta < -0.5:
            return "easy"
        elif avg_theta < 0.5:
            return "medium"
        else:
            return "hard"

    def get_theta_confidence_interval(self) -> list[list[float]]:
        # 分维度返回 95% 置信区间
        intervals = []
        for d in range(3):
            intervals.append([
                self.theta[d] - 1.96 * self.theta_std[d],
                self.theta[d] + 1.96 * self.theta_std[d]
            ])
        return intervals

    def to_dict(self) -> dict[str, Any]:
        return {
            "theta": [round(t, 4) for t in self.theta],
            "theta_std": [round(s, 4) for s in self.theta_std],
            "theta_cov": [[round(x, 4) for x in row] for row in self.theta_cov] if self.theta_cov else None,
            "items_answered": len(self.response_history),
            "difficulty_label": self.get_estimated_difficulty_label(),
        }


def difficulty_to_beta(label: str) -> float:
    mapping = {"easy": -1.0, "medium": 0.0, "hard": 1.0}
    return mapping.get(label.lower(), 0.0)


def beta_to_difficulty(beta: float) -> str:
    if beta < -0.5:
        return "easy"
    elif beta < 0.5:
        return "medium"
    else:
        return "hard"


def estimate_irt_params_from_profile(
    mastery: float,
    attempts: int = 1,
    accuracy_history: list[float] | None = None,
    difficulty: str | None = None,
) -> IRTItemParams:
    """根据学情画像与题型特征，自适应投射三维 MIRT 题目参数"""
    alpha_base = 1.0 + 0.5 * math.log(max(attempts, 1) + 1)
    
    if difficulty:
        b_val = {"easy": -1.0, "medium": 0.0, "hard": 1.0}.get(difficulty.lower(), 0.0)
    else:
        b_val = (mastery - 0.5) * 3.0
        
    gamma = max(0.05, 0.25 - 0.05 * attempts)
    if accuracy_history:
        avg_acc = sum(accuracy_history) / len(accuracy_history)
        alpha_base += 0.3 * avg_acc
        b_val += (avg_acc - 0.5) * 1.5

    # 默认投影：三维 [Theory, Coding, Math] 对等
    alpha = [round(alpha_base, 4), round(alpha_base * 0.8, 4), round(alpha_base * 0.6, 4)]
    beta = [round(b_val, 4), round(b_val + 0.1, 4), round(b_val - 0.1, 4)]

    return IRTItemParams(alpha=alpha, beta=beta, gamma=round(gamma, 4))


def mcmc_calibrate_item_parameters(
    response_matrix: list[list[int]],        # 答题矩阵: 行=学生(N人)，列=题目(M道)
    student_abilities: list[list[float]],    # 学生的3D能力估计: 形状 (N, 3)
    initial_items: list[IRTItemParams],      # 题目的初始参数: 长度 M
    iterations: int = 100,
    burn_in: int = 30,
) -> list[IRTItemParams]:
    """
    基于 Metropolis-Hastings MCMC 采样法校准三维 MIRT 题目参数 (alpha, beta)。
    通过马尔可夫链状态抽样，估计参数的后验分布均值。
    """
    num_students = len(response_matrix)
    num_items = len(initial_items)
    if num_students == 0 or num_items == 0:
        return initial_items

    calibrated_items = []

    for j in range(num_items):
        item = initial_items[j]
        # 对当前第 j 道题的 alpha (3D) 和 beta (3D) 进行 MH 抽样
        alpha_samples = []
        beta_samples = []
        
        current_alpha = list(item.alpha)
        current_beta = list(item.beta)
        current_gamma = item.gamma
        
        def calculate_item_log_posterior(a: list[float], b: list[float]) -> float:
            # 似然值计算
            log_lik = 0.0
            for i in range(num_students):
                resp = response_matrix[i][j]
                theta = student_abilities[i]
                z = sum(ai * (ti - bi) for ai, ti, bi in zip(a, theta, b))
                # 3PL 概率
                P = current_gamma + (1.0 - current_gamma) * (1.0 / (1.0 + math.exp(-z) if -z < 700 else 0.0))
                P = max(1e-15, min(1.0 - 1e-15, P))
                if resp == 1:
                    log_lik += math.log(P)
                else:
                    log_lik += math.log(1.0 - P)
            # 先验值计算 (假设 alpha ~ N(1, 0.5^2), beta ~ N(0, 1))
            log_prior = 0.0
            for d in range(3):
                # alpha 必须大于 0
                if a[d] <= 0:
                    return -float('inf')
                log_prior += -0.5 * ((a[d] - 1.0) / 0.5) ** 2
                log_prior += -0.5 * (b[d] / 1.5) ** 2
            return log_lik + log_prior

        for _ in range(iterations):
            # 1. 提案新状态 (随机游走)
            prop_alpha = [current_alpha[d] + random.normalvariate(0, 0.1) for d in range(3)]
            prop_beta = [current_beta[d] + random.normalvariate(0, 0.1) for d in range(3)]
            
            log_post_curr = calculate_item_log_posterior(current_alpha, current_beta)
            log_post_prop = calculate_item_log_posterior(prop_alpha, prop_beta)
            
            # Metropolis 接受概率
            try:
                alpha_prob = math.exp(max(-700.0, min(0.0, log_post_prop - log_post_curr)))
            except Exception:
                alpha_prob = 0.0
                
            if random.random() < alpha_prob:
                current_alpha = prop_alpha
                current_beta = prop_beta
                
            alpha_samples.append(current_alpha)
            beta_samples.append(current_beta)

        # 2. 烧入期后求平均值作为估计值
        final_alpha = [0.0, 0.0, 0.0]
        final_beta = [0.0, 0.0, 0.0]
        valid_samples = iterations - burn_in
        
        for d in range(3):
            val_alpha = sum(s[d] for s in alpha_samples[burn_in:]) / valid_samples
            val_beta = sum(s[d] for s in beta_samples[burn_in:]) / valid_samples
            # 引入夹逼范围，防止冷启动小样本时参数过度发散
            final_alpha[d] = round(max(0.2, min(3.0, val_alpha)), 4)
            final_beta[d] = round(max(-3.0, min(3.0, val_beta)), 4)

        calibrated_items.append(IRTItemParams(alpha=final_alpha, beta=final_beta, gamma=current_gamma))

    return calibrated_items