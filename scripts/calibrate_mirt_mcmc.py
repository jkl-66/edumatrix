from __future__ import annotations

import math
import random
import sqlite3
import json
from typing import Any
from dataclasses import dataclass, field
from collections import defaultdict


@dataclass
class VirtualStudent:
    student_id: str
    theta: float
    responses: list[dict[str, Any]] = field(default_factory=list)

    def answer_probability(self, alpha: float, beta: float, gamma: float) -> float:
        z = alpha * (self.theta - beta)
        logistic = 1.0 / (1.0 + math.exp(-z))
        return gamma + (1.0 - gamma) * logistic

    def simulate_response(self, alpha: float, beta: float, gamma: float) -> bool:
        p = self.answer_probability(alpha, beta, gamma)
        return random.random() < p


@dataclass
class ItemCalibration:
    item_id: str
    concept: str
    alpha: float = 1.0
    beta: float = 0.0
    gamma: float = 0.25
    response_count: int = 0
    correct_count: int = 0


def generate_virtual_students(n: int = 1000, seed: int = 42) -> list[VirtualStudent]:
    random.seed(seed)
    students = []
    for i in range(n):
        theta = random.gauss(0.0, 1.0)
        theta = max(-4.0, min(4.0, theta))
        students.append(VirtualStudent(
            student_id=f"virtual_{i:04d}",
            theta=theta,
        ))
    return students


def load_items_from_db(db_path: str, concept_filter: str | None = None) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = """
        SELECT qr.id, qr.target_concept, qr.correct_answer, qr.accuracy_score,
               COALESCE(sp.knowledge_traces, '{}') as knowledge_traces
        FROM quiz_records qr
        LEFT JOIN student_profiles sp ON qr.student_id = sp.student_id
        WHERE qr.correct_answer IS NOT NULL AND qr.correct_answer != ''
    """
    if concept_filter:
        query += f" AND qr.target_concept = ?"
        cursor.execute(query, (concept_filter,))
    else:
        cursor.execute(query)

    rows = cursor.fetchall()
    conn.close()

    items = []
    seen = set()
    for row in rows:
        item_id = row["id"]
        concept = row["target_concept"] or "unknown"
        if item_id in seen:
            continue
        seen.add(item_id)

        knowledge_traces = {}
        try:
            knowledge_traces = json.loads(row["knowledge_traces"])
        except (json.JSONDecodeError, TypeError):
            pass

        irt_state = knowledge_traces.get("irt_estimator", {})
        items.append({
            "id": item_id,
            "concept": concept,
            "correct_answer": row["correct_answer"] or "",
            "accuracy_score": row["accuracy_score"] or 0.5,
            "irt_params": irt_state.get("item_params", {}),
        })

    return items


def run_simulation(
    students: list[VirtualStudent],
    items: list[dict[str, Any]],
    db_path: str,
) -> dict[str, ItemCalibration]:
    calibrations: dict[str, ItemCalibration] = {}

    for item in items:
        item_id = item["id"]
        irt_raw = item.get("irt_params", {})
        alpha = float(irt_raw.get("alpha", 1.0)) if isinstance(irt_raw, dict) else 1.0
        beta = float(irt_raw.get("beta", 0.0)) if isinstance(irt_raw, dict) else 0.0
        gamma = float(irt_raw.get("gamma", 0.25)) if isinstance(irt_raw, dict) else 0.25

        calibrations[item_id] = ItemCalibration(
            item_id=item_id,
            concept=item.get("concept", "unknown"),
            alpha=alpha,
            beta=beta,
            gamma=gamma,
        )

    for student in students:
        for item in items:
            cal = calibrations[item["id"]]
            correct = student.simulate_response(cal.alpha, cal.beta, cal.gamma)
            cal.response_count += 1
            if correct:
                cal.correct_count += 1
            student.responses.append({
                "item_id": item["id"],
                "correct": correct,
            })

    return calibrations


def em_estimate_parameters(
    responses: list[dict[str, bool]],
    n_iterations: int = 50,
    n_quad_points: int = 21,
) -> tuple[float, float, float]:
    if not responses:
        return 1.0, 0.0, 0.25

    theta_points = [
        -4.0 + i * 8.0 / (n_quad_points - 1)
        for i in range(n_quad_points)
    ]
    weights = [
        math.exp(-0.5 * t * t) / math.sqrt(2.0 * math.pi)
        for t in theta_points
    ]
    total_weight = sum(weights)
    weights = [w / total_weight for w in weights]

    n_correct = sum(1 for r in responses if r["correct"])
    n_total = len(responses)

    alpha = 1.0
    beta = 0.0
    gamma = max(0.05, n_correct / max(n_total, 1) * 0.25)

    for iteration in range(n_iterations):
        posteriors = []
        for k, theta_k in enumerate(theta_points):
            z = alpha * (theta_k - beta)
            logistic = 1.0 / (1.0 + math.exp(-z))
            P = gamma + (1.0 - gamma) * logistic
            Q = 1.0 - P

            log_lik = 0.0
            for r in responses:
                if r["correct"]:
                    log_lik += math.log(max(P, 1e-15))
                else:
                    log_lik += math.log(max(Q, 1e-15))

            posterior = weights[k] * math.exp(log_lik)
            posteriors.append(posterior)

        post_sum = sum(posteriors)
        if post_sum > 0:
            posteriors = [p / post_sum for p in posteriors]

        r_k = [0.0] * n_quad_points
        for k in range(n_quad_points):
            theta_k = theta_points[k]
            z = alpha * (theta_k - beta)
            logistic = 1.0 / (1.0 + math.exp(-z))
            P = gamma + (1.0 - gamma) * logistic

            num = 0.0
            den = 0.0
            for r in responses:
                if r["correct"]:
                    num += posteriors[k]
                den += posteriors[k]
            if den > 0:
                r_k[k] = num / den if den > 0 else 0.0

        grad_alpha = 0.0
        grad_beta = 0.0
        for k in range(n_quad_points):
            theta_k = theta_points[k]
            z = alpha * (theta_k - beta)
            logistic = 1.0 / (1.0 + math.exp(-z))
            P = gamma + (1.0 - gamma) * logistic
            Q = 1.0 - P
            if P <= 0.0 or Q <= 0.0:
                continue

            dP_dalpha = (1.0 - gamma) * (theta_k - beta) * logistic * (1.0 - logistic)
            dP_dbeta = -(1.0 - gamma) * alpha * logistic * (1.0 - logistic)

            grad_alpha += posteriors[k] * (r_k[k] - P) * dP_dalpha / (P * Q + 1e-15)
            grad_beta += posteriors[k] * (r_k[k] - P) * dP_dbeta / (P * Q + 1e-15)

        lr = 0.1 / (1.0 + 0.01 * iteration)
        alpha += lr * grad_alpha
        beta += lr * grad_beta

        alpha = max(0.2, min(5.0, alpha))
        beta = max(-4.0, min(4.0, beta))

    gamma = max(0.05, min(0.5, n_correct / max(n_total, 1) * 0.25))

    return round(alpha, 4), round(beta, 4), round(gamma, 4)


def run_mcmc_calibration(
    db_path: str = "data/edumatrix.db",
    n_virtual_students: int = 1000,
    concept_filter: str | None = None,
    seed: int = 42,
) -> dict[str, Any]:
    print(f"\n{'='*60}")
    print(f"  MCMC 参数自校准模拟器")
    print(f"  数据库: {db_path}")
    print(f"  虚拟学生数: {n_virtual_students}")
    print(f"{'='*60}\n")

    print("[1/4] 从数据库加载题目...")
    items = load_items_from_db(db_path, concept_filter)
    if not items:
        print("  ⚠️ 数据库中没有找到题目记录，使用模拟数据")
        items = _generate_mock_items(20)

    print(f"  加载了 {len(items)} 道题目")

    print(f"\n[2/4] 生成 {n_virtual_students} 个虚拟学生 (θ ~ N(0,1))...")
    students = generate_virtual_students(n_virtual_students, seed)
    print(f"  生成了 {len(students)} 个虚拟学生")

    print(f"\n[3/4] 运行自适应答题模拟...")
    calibrations = run_simulation(students, items, db_path)

    print(f"\n[4/4] EM 算法拟合 ICC 曲线，估计题目参数...")
    student_responses_by_item: dict[str, list[dict[str, bool]]] = defaultdict(list)
    for student in students:
        for resp in student.responses:
            student_responses_by_item[resp["item_id"]].append(resp)

    results = {}
    for item_id, cal in calibrations.items():
        responses = student_responses_by_item.get(item_id, [])
        old_alpha, old_beta, old_gamma = cal.alpha, cal.beta, cal.gamma
        new_alpha, new_beta, new_gamma = em_estimate_parameters(responses)

        results[item_id] = {
            "concept": cal.concept,
            "old_params": {"alpha": old_alpha, "beta": old_beta, "gamma": old_gamma},
            "new_params": {"alpha": new_alpha, "beta": new_beta, "gamma": new_gamma},
            "response_count": cal.response_count,
            "correct_rate": round(cal.correct_count / max(cal.response_count, 1), 4),
        }

    print(f"\n{'='*60}")
    print(f"  校准结果摘要")
    print(f"{'='*60}")
    print(f"  {'题目ID':<20} {'α(旧→新)':<20} {'β(旧→新)':<20} {'γ(旧→新)':<20}")
    print(f"  {'-'*60}")
    for item_id, res in list(results.items())[:10]:
        old = res["old_params"]
        new = res["new_params"]
        print(f"  {item_id[:18]:<20} {old['alpha']:.2f}→{new['alpha']:.2f}        {old['beta']:.2f}→{new['beta']:.2f}        {old['gamma']:.2f}→{new['gamma']:.2f}")

    if len(results) > 10:
        print(f"  ... 共 {len(results)} 道题目，仅显示前 10 道")

    summary = {
        "total_items": len(items),
        "total_students": n_virtual_students,
        "total_responses": sum(r["response_count"] for r in results.values()),
        "average_alpha_change": round(
            sum(abs(r["new_params"]["alpha"] - r["old_params"]["alpha"]) for r in results.values()) / max(len(results), 1), 4
        ),
        "average_beta_change": round(
            sum(abs(r["new_params"]["beta"] - r["old_params"]["beta"]) for r in results.values()) / max(len(results), 1), 4
        ),
        "calibrated_items": results,
    }

    print(f"\n  平均 α 变化: {summary['average_alpha_change']:.4f}")
    print(f"  平均 β 变化: {summary['average_beta_change']:.4f}")
    print(f"{'='*60}\n")

    return summary


def write_calibrated_params_to_db(
    db_path: str,
    results: dict[str, Any],
) -> int:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    updated = 0
    for item_id, res in results.get("calibrated_items", {}).items():
        new_params = res["new_params"]
        # 1. 更新答题历史记录表 (quiz_records) 中的参数快照
        cursor.execute(
            """UPDATE quiz_records 
               SET irt_alpha = ?, irt_beta = ?, irt_gamma = ?
               WHERE id = ?""",
            (new_params["alpha"], new_params["beta"], new_params["gamma"], item_id),
        )
        if cursor.rowcount > 0:
            updated += 1

        # 2. 更新预置种子题库表 (quiz_items) 中的参数
        cursor.execute(
            """UPDATE quiz_items 
               SET irt_alpha = ?, irt_beta = ?, irt_gamma = ?
               WHERE id = ?""",
            (new_params["alpha"], new_params["beta"], new_params["gamma"], item_id),
        )

    conn.commit()
    conn.close()

    print(f"  已更新 {updated} 条记录/题目的 IRT 参数到数据库")
    return updated


def _generate_mock_items(n: int = 20) -> list[dict[str, Any]]:
    concepts = [
        "逻辑回归", "梯度下降", "反向传播", "过拟合", "正则化",
        "最大池化", "平均池化", "Sigmoid函数", "链式法则", "损失函数",
        "激活函数", "卷积神经网络", "决策树", "支持向量机", "线性回归",
    ]
    items = []
    for i in range(n):
        concept = concepts[i % len(concepts)]
        items.append({
            "id": f"mock_{i:04d}",
            "concept": concept,
            "correct_answer": f"{concept}的参考答案",
            "accuracy_score": 0.5 + random.random() * 0.3,
            "irt_params": {
                "alpha": round(0.5 + random.random() * 2.0, 2),
                "beta": round(random.gauss(0.0, 1.0), 2),
                "gamma": round(0.1 + random.random() * 0.2, 2),
            },
        })
    return items


if __name__ == "__main__":
    import sys
    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/edumatrix.db"
    n_students = int(sys.argv[2]) if len(sys.argv) > 2 else 200

    results = run_mcmc_calibration(
        db_path=db_path,
        n_virtual_students=n_students,
        seed=42,
    )

    write_calibrated_params_to_db(db_path, results)
    print("✅ MCMC 参数自校准完成！")