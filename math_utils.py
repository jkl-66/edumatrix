"""EduMatrix 数学工具库 - 统一余弦相似度实现。

P2-2 重构：集中所有余弦相似度计算，消除四处重复实现。
"""

from __future__ import annotations

import math
import numpy as np


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """余弦相似度，返回 [0, 1] 范围的值。"""
    if not vec_a or not vec_b:
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b + 1e-10)))


def cosine_similarity_np(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """使用 NumPy 的余弦相似度。"""
    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return max(0.0, min(1.0, float(np.dot(vec_a, vec_b) / (norm_a * norm_b + 1e-10))))
