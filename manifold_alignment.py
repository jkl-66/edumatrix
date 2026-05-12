from __future__ import annotations

import hashlib
import math
import re

import numpy as np

from config import CONFIG
from models import AgentOutput, AlignmentReport


def _hash_embedding(text: str, dim: int = 96) -> np.ndarray:
    vector = np.zeros(dim, dtype=np.float64)
    terms = re.findall(r"[a-zA-Z0-9_+\-.]+|[\u4e00-\u9fff]{2,}", text.lower())
    terms.extend(re.findall(r"nn\.[A-Za-z0-9_]+", text))
    for term in terms:
        digest = hashlib.sha256(term.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = np.linalg.norm(vector)
    if norm == 0:
        return vector
    return vector / norm


def _to_poincare_ball(vector: np.ndarray, radius: float = 0.82) -> np.ndarray:
    norm = np.linalg.norm(vector)
    if norm == 0:
        return vector
    scaled_norm = radius * math.tanh(norm)
    return vector / norm * scaled_norm


def _poincare_distance(u: np.ndarray, v: np.ndarray, eps: float = 1e-9) -> float:
    u_norm = np.linalg.norm(u) ** 2
    v_norm = np.linalg.norm(v) ** 2
    diff_norm = np.linalg.norm(u - v) ** 2
    denom = max(eps, (1.0 - u_norm) * (1.0 - v_norm))
    argument = 1.0 + 2.0 * diff_norm / denom
    return float(np.arccosh(max(1.0 + eps, argument)))


def _semantic_conflicts(text: str, code: str, mermaid: str = "") -> tuple[str, ...]:
    combined_diagram = mermaid.lower()
    text_lower = text.lower()
    code_lower = code.lower()
    conflicts: list[str] = []
    text_max = "最大池化" in text or "max pooling" in text_lower or "局部最大" in text
    text_avg = "平均池化" in text or "average pooling" in text_lower or "均值" in text
    code_max = "maxpool" in code_lower or "torch.max" in code_lower
    code_avg = "avgpool" in code_lower or "mean(" in code_lower
    diagram_max = "最大" in mermaid or "max" in combined_diagram
    diagram_avg = "平均" in mermaid or "avg" in combined_diagram or "均值" in mermaid
    text_primary_max = text_max and not text_avg
    text_primary_avg = text_avg and not text_max
    diagram_primary_max = diagram_max and not diagram_avg
    diagram_primary_avg = diagram_avg and not diagram_max
    if text_primary_max and code_avg and not code_max:
        conflicts.append("讲义强调最大池化，但代码使用平均池化。")
    if text_primary_avg and code_max and not code_avg:
        conflicts.append("讲义强调平均池化，但代码使用最大池化。")
    if diagram_primary_avg and (text_primary_max or code_max) and not diagram_max:
        conflicts.append("导图偏向平均池化，但文本或代码偏向最大池化。")
    if diagram_primary_max and (text_primary_avg or code_avg) and not diagram_avg:
        conflicts.append("导图偏向最大池化，但文本或代码偏向平均池化。")
    return tuple(conflicts)


class ManifoldAlignmentVerifier:
    """Cross-modal semantic consistency gate using a Poincare-ball distance."""

    def __init__(self, threshold: float = CONFIG.alignment_threshold) -> None:
        self.threshold = threshold

    def verify(self, resources: tuple[AgentOutput, ...]) -> AlignmentReport:
        by_type = {resource.resource_type: resource.content for resource in resources}
        text = by_type.get("专业讲义", "")
        code = by_type.get("代码实操案例", "")
        mermaid = by_type.get("思维导图", "")
        reference = "\n".join(content for content in (text, mermaid) if content)
        generated = code or "\n".join(by_type.values())

        ref_point = _to_poincare_ball(_hash_embedding(reference))
        gen_point = _to_poincare_ball(_hash_embedding(generated))
        distance = _poincare_distance(ref_point, gen_point)
        conflicts = _semantic_conflicts(text, code, mermaid)
        passed = distance <= self.threshold and not conflicts
        advice = "通过：文本、代码、导图语义收敛，可以交付。" if passed else self._advice(distance, conflicts)
        return AlignmentReport(
            passed=passed,
            distance=distance,
            threshold=self.threshold,
            conflicts=conflicts,
            advice=advice,
        )

    def _advice(self, distance: float, conflicts: tuple[str, ...]) -> str:
        parts = []
        if distance > self.threshold:
            parts.append(f"双曲测地线距离 {distance:.3f} 超过阈值 {self.threshold:.3f}。")
        parts.extend(conflicts)
        parts.append("请回滚到资源生成 Agent，统一术语、公式、代码 API 与导图节点。")
        return " ".join(parts)


def verify_consistency(text: str, code: str, threshold: float = CONFIG.alignment_threshold) -> bool:
    verifier = ManifoldAlignmentVerifier(threshold=threshold)
    report = verifier.verify(
        (
            AgentOutput("理论教授", "专业讲义", text, ()),
            AgentOutput("极客助教", "代码实操案例", code, ()),
        )
    )
    print(f"流形测地线距离: {report.distance:.4f} | 安全阈值: {report.threshold:.4f}")
    print(report.advice)
    return report.passed
