from __future__ import annotations

import math
from typing import Any
from dataclasses import dataclass, field


@dataclass
class IRTItemParams:
    alpha: float = 1.0
    beta: float = 0.0
    gamma: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {"alpha": self.alpha, "beta": self.beta, "gamma": self.gamma}

    @classmethod
    def from_dict(cls, d: dict[str, float]) -> IRTItemParams:
        return cls(
            alpha=float(d.get("alpha", 1.0)),
            beta=float(d.get("beta", 0.0)),
            gamma=float(d.get("gamma", 0.0)),
        )


@dataclass
class AdaptiveTestEstimator:
    theta: float = 0.0
    theta_std: float = 1.0
    prior_mean: float = 0.0
    prior_std: float = 1.0
    response_history: list[dict[str, Any]] = field(default_factory=list)

    def _logistic(self, x: float) -> float:
        if x > 700:
            return 1.0
        if x < -700:
            return 0.0
        return 1.0 / (1.0 + math.exp(-x))

    def _probability_correct(self, theta: float, item: IRTItemParams) -> float:
        gamma = item.gamma
        alpha = item.alpha
        beta = item.beta
        z = alpha * (theta - beta)
        return gamma + (1.0 - gamma) * self._logistic(z)

    def _probability_derivative(self, theta: float, item: IRTItemParams) -> float:
        gamma = item.gamma
        alpha = item.alpha
        beta = item.beta
        z = alpha * (theta - beta)
        p_logistic = self._logistic(z)
        return (1.0 - gamma) * alpha * p_logistic * (1.0 - p_logistic)

    def fisher_information(self, theta: float, item: IRTItemParams) -> float:
        P = self._probability_correct(theta, item)
        P_prime = self._probability_derivative(theta, item)
        if P <= 0.0 or P >= 1.0:
            return 0.0
        return (P_prime * P_prime) / (P * (1.0 - P))

    def compute_log_likelihood(self, theta: float) -> float:
        ll = 0.0
        for entry in self.response_history:
            item = entry["item"]
            correct = entry["correct"]
            P = self._probability_correct(theta, item)
            if P <= 0.0:
                P = 1e-15
            if P >= 1.0:
                P = 1.0 - 1e-15
            if correct:
                ll += math.log(P)
            else:
                ll += math.log(1.0 - P)
        return ll

    def compute_log_prior(self, theta: float) -> float:
        z = (theta - self.prior_mean) / self.prior_std
        return -0.5 * z * z - math.log(self.prior_std * math.sqrt(2.0 * math.pi))

    def compute_log_posterior(self, theta: float) -> float:
        return self.compute_log_likelihood(theta) + self.compute_log_prior(theta)

    def _estimate_theta_map(self, theta_init: float, step: float = 0.5, iterations: int = 50) -> float:
        theta = theta_init
        for _ in range(iterations):
            grad = self._posterior_gradient(theta)
            if abs(grad) < 0.001:
                break
            theta += step * grad
            if theta > 4.0:
                theta = 4.0
            if theta < -4.0:
                theta = -4.0
            step *= 0.95
        return theta

    def _posterior_gradient(self, theta: float) -> float:
        grad = 0.0
        for entry in self.response_history:
            item = entry["item"]
            correct = entry["correct"]
            P = self._probability_correct(theta, item)
            P_prime = self._probability_derivative(theta, item)
            if P <= 0.0:
                P = 1e-15
            if P >= 1.0:
                P = 1.0 - 1e-15
            if correct:
                grad += P_prime / P
            else:
                grad -= P_prime / (1.0 - P)
        prior_grad = -(theta - self.prior_mean) / (self.prior_std * self.prior_std)
        return grad + prior_grad

    def update_ability(self, item: IRTItemParams, correct: bool) -> float:
        self.response_history.append({"item": item, "correct": correct})
        self.theta = self._estimate_theta_map(self.theta)
        self.theta_std = self._estimate_std()
        return self.theta

    def _estimate_std(self) -> float:
        total_info = 0.0
        for entry in self.response_history:
            item = entry["item"]
            total_info += self.fisher_information(self.theta, item)
        prior_info = 1.0 / (self.prior_std * self.prior_std)
        total_info += prior_info
        if total_info <= 0.0:
            return 1.0
        return 1.0 / math.sqrt(total_info)

    def select_next_item(
        self,
        candidate_items: list[dict[str, Any]],
        exclude_ids: set[str] | None = None,
    ) -> dict[str, Any] | None:
        if not candidate_items:
            return None
        exclude = exclude_ids or set()
        best_item = None
        best_info = -1.0
        for item_data in candidate_items:
            if item_data.get("id") in exclude:
                continue
            irt_params = self._extract_irt_params(item_data)
            info = self.fisher_information(self.theta, irt_params)
            if info > best_info:
                best_info = info
                best_item = item_data
        return best_item

    def _extract_irt_params(self, item_data: dict[str, Any]) -> IRTItemParams:
        irt_raw = item_data.get("irt_params", {})
        if isinstance(irt_raw, dict):
            return IRTItemParams.from_dict(irt_raw)
        return IRTItemParams(
            alpha=float(item_data.get("discrimination", 1.0)),
            beta=float(item_data.get("difficulty_beta", 0.0)),
            gamma=float(item_data.get("guessing_gamma", 0.0)),
        )

    def get_estimated_difficulty_label(self) -> str:
        theta = self.theta
        if theta < -0.5:
            return "easy"
        elif theta < 0.5:
            return "medium"
        else:
            return "hard"

    def get_theta_confidence_interval(self) -> tuple[float, float]:
        return (self.theta - 1.96 * self.theta_std, self.theta + 1.96 * self.theta_std)

    def to_dict(self) -> dict[str, Any]:
        return {
            "theta": round(self.theta, 4),
            "theta_std": round(self.theta_std, 4),
            "confidence_interval": [
                round(v, 4) for v in self.get_theta_confidence_interval()
            ],
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
    alpha = 1.0 + 0.5 * math.log(max(attempts, 1) + 1)
    
    # 修正：难度 beta 应该与题目难度直接正向对齐，而非反向估计
    if difficulty:
        beta = {"easy": -1.0, "medium": 0.0, "hard": 1.0}.get(difficulty.lower(), 0.0)
    else:
        # 如果没有指定 difficulty，则根据 mastery 正向预测难度范围
        beta = (mastery - 0.5) * 3.0  # 正向：高掌握度对应高难度区间
        
    gamma = max(0.05, 0.25 - 0.05 * attempts)
    if accuracy_history:
        avg_acc = sum(accuracy_history) / len(accuracy_history)
        alpha += 0.3 * avg_acc
        beta += (avg_acc - 0.5) * 1.5 # 正向调整
    return IRTItemParams(
        alpha=round(alpha, 4),
        beta=round(beta, 4),
        gamma=round(gamma, 4),
    )