"""图谱构建相关的领域模型（dataclass 不可变值对象）。

按 backend.md 第 1/2 条：业务领域模型集中定义，repository / service 仅依赖
这些类型，不直接依赖 ORM 行或外部 SDK 对象。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class Triplet:
    """前置依赖三元组：source -[relation]-> target。

    relation 默认 ``PREREQUISITE_OF``：A 是 B 的前置（学完 A 才能学 B）。
    """

    source: str
    target: str
    relation: str = "PREREQUISITE_OF"
    confidence: float = 1.0
    evidence: str = ""

    def normalized(self) -> "Triplet":
        return Triplet(
            source=self.source.strip(),
            target=self.target.strip(),
            relation=self.relation.strip().upper().replace(" ", "_") or "PREREQUISITE_OF",
            confidence=max(0.0, min(1.0, float(self.confidence))),
            evidence=self.evidence.strip(),
        )


@dataclass(frozen=True)
class EntityAlignment:
    """实体对齐结果。"""

    original: str
    canonical: str
    score: float
    method: str  # exact / levenshtein / cosine / fallback


@dataclass(frozen=True)
class AlignedTriplet:
    """对齐后的三元组（source/target 替换为白名单标准词）。"""

    raw: Triplet
    source_alignment: EntityAlignment
    target_alignment: EntityAlignment

    @property
    def aligned(self) -> Triplet:
        return Triplet(
            source=self.source_alignment.canonical,
            target=self.target_alignment.canonical,
            relation=self.raw.relation,
            confidence=self.raw.confidence,
            evidence=self.raw.evidence,
        )

    @property
    def both_aligned(self) -> bool:
        return (
            self.source_alignment.method != "fallback"
            and self.target_alignment.method != "fallback"
        )


@dataclass(frozen=True)
class GraphBuildReport:
    """图谱构建一次执行的统计快照。"""

    source: str
    chunk_count: int
    raw_triplets: int
    aligned_triplets: int
    written_edges: int
    alignment_rate: float  # 0.0 - 1.0
    backend: str  # neo4j / memory
    duration_ms: int
    timestamp: str = field(default_factory=_utc_now_iso)
    triplets: tuple[Triplet, ...] = ()
    aligned: tuple[AlignedTriplet, ...] = ()


@dataclass(frozen=True)
class GraphQueryResult:
    """图谱查询返回值。"""

    target: str
    prerequisites: tuple[str, ...]
    downstream: tuple[str, ...]
    metadata: Mapping[str, object] = field(default_factory=dict)


__all__ = (
    "Triplet",
    "EntityAlignment",
    "AlignedTriplet",
    "GraphBuildReport",
    "GraphQueryResult",
)
