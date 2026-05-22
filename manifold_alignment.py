from __future__ import annotations

import math
from typing import Any

from embedding_models import EMBEDDINGS
from embedding_models import cosine_similarity
from models import AlignmentReport


def _embed_safe(text: str) -> tuple[float, ...]:
    raw = EMBEDDINGS.embed(text)
    if not raw:
        return tuple(0.0 for _ in range(384))
    return raw


def _extract_concept_text(resource: object) -> str:
    if isinstance(resource, str):
        return resource[:500]
    content = getattr(resource, "content", "") or ""
    source = getattr(resource, "source", "") or ""
    title = getattr(resource, "title", "") or ""
    return f"{title} {content[:500]} {source}"


def verify_alignment(
    resources: list[object],
    *,
    base_concept: str = "",
    alignment_threshold: float = 0.65,
) -> AlignmentReport:
    if len(resources) < 2:
        return AlignmentReport(
            passed=True,
            distance=0.0,
            threshold=alignment_threshold,
            conflicts=[],
            advice="资源数量不足，跳过对齐校验。",
        )

    base_vec = _embed_safe(base_concept) if base_concept else _embed_safe("通用机器学习概念")

    conflicts: list[dict[str, Any]] = []
    max_distance = 0.0

    for resource_a in resources:
        for resource_b in resources:
            if resource_a is resource_b:
                continue
            sim = cosine_similarity(
                _embed_safe(_extract_concept_text(resource_a)),
                _embed_safe(_extract_concept_text(resource_b)),
            )
            distance = 1.0 - sim
            max_distance = max(max_distance, distance)
            if distance > alignment_threshold:
                conflicts.append({
                    "type": "跨模态不一致",
                    "resources": [
                        getattr(resource_a, "id", "") or getattr(resource_a, "agent", ""),
                        getattr(resource_b, "id", "") or getattr(resource_b, "agent", ""),
                    ],
                    "distance": round(distance, 3),
                    "suggestion": "检测到跨模态语义不一致，建议统一概念表述后重新生成。",
                })

    for resource in resources:
        r_text = _extract_concept_text(resource)
        r_vec = _embed_safe(r_text)
        sim = cosine_similarity(base_vec, r_vec)
        distance = 1.0 - sim
        max_distance = max(max_distance, distance)
        if distance > alignment_threshold:
            conflicts.append({
                "type": "偏离核心概念",
                "resources": [r_text[:60]],
                "distance": round(distance, 3),
                "suggestion": f"该资源距离核心概念太远(d={distance:.2f})，建议重新生成。",
            })

    passed = len(conflicts) == 0
    advice = (
        "所有资源在双曲空间中一致性良好，无需回滚。"
        if passed
        else f"发现{len(conflicts)}个冲突点，建议携带 correction 回滚重生成。"
    )
    return AlignmentReport(
        passed=passed,
        distance=round(max_distance, 3),
        threshold=alignment_threshold,
        conflicts=conflicts,
        advice=advice,
    )


class ManifoldAlignmentVerifier:
    def __init__(self, threshold: float | None = None) -> None:
        self.threshold = threshold or 0.65

    def verify(self, resources: list[object], *, target: str = "", **kwargs: Any) -> AlignmentReport:
        return verify_alignment(
            resources,
            base_concept=target,
            alignment_threshold=self.threshold,
        )


def verify_consistency(text_resource: object, code_resource: object, threshold: float = 0.65) -> AlignmentReport:
    return verify_alignment([text_resource, code_resource], alignment_threshold=threshold)
