from __future__ import annotations

from dataclasses import dataclass

from models import RetrievalBundle
from rag_engine import HybridRAGPipeline


@dataclass(frozen=True)
class RetrievalEvalCase:
    query: str
    expected_evidence_ids: tuple[str, ...]
    target: str | None = None


@dataclass(frozen=True)
class RetrievalEvalReport:
    cases: int
    recall_at_k: float
    mean_reciprocal_rank: float
    misses: tuple[str, ...]


def evaluate_retrieval(
    pipeline: HybridRAGPipeline,
    cases: tuple[RetrievalEvalCase, ...],
    *,
    top_k: int = 6,
) -> RetrievalEvalReport:
    if not cases:
        return RetrievalEvalReport(cases=0, recall_at_k=0.0, mean_reciprocal_rank=0.0, misses=())

    recall_hits = 0
    reciprocal_ranks = []
    misses = []
    for case in cases:
        bundle = pipeline.retrieve(case.query, target=case.target, top_k=top_k)
        ranked_ids = [item.id for item in bundle.evidence]
        hit_ranks = [
            ranked_ids.index(expected_id) + 1
            for expected_id in case.expected_evidence_ids
            if expected_id in ranked_ids
        ]
        if hit_ranks:
            recall_hits += 1
            reciprocal_ranks.append(1 / min(hit_ranks))
        else:
            reciprocal_ranks.append(0.0)
            misses.append(_miss_label(case, bundle))
    return RetrievalEvalReport(
        cases=len(cases),
        recall_at_k=recall_hits / len(cases),
        mean_reciprocal_rank=sum(reciprocal_ranks) / len(reciprocal_ranks),
        misses=tuple(misses),
    )


def _miss_label(case: RetrievalEvalCase, bundle: RetrievalBundle) -> str:
    retrieved = ",".join(item.id for item in bundle.evidence) or "none"
    expected = ",".join(case.expected_evidence_ids)
    return f"query={case.query}; expected={expected}; retrieved={retrieved}"
