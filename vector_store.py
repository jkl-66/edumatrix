from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from embedding_models import EMBEDDINGS, EmbeddingBackend
from models import Evidence


class VectorIndex(Protocol):
    name: str

    def upsert(self, items: tuple[Evidence, ...]) -> None:
        ...

    def search(self, query: str, *, top_k: int) -> tuple[Evidence, ...]:
        ...

    def count(self) -> int:
        ...


@dataclass
class InMemoryVectorIndex:
    name: str
    embedding_backend: EmbeddingBackend = field(default_factory=lambda: EMBEDDINGS)
    _items: dict[str, Evidence] = field(default_factory=dict)
    _vectors: dict[str, tuple[float, ...]] = field(default_factory=dict)

    def upsert(self, items: tuple[Evidence, ...]) -> None:
        for item in items:
            self._items[item.id] = item
            self._vectors[item.id] = self.embedding_backend.embed(evidence_to_text(item))

    def search(self, query: str, *, top_k: int) -> tuple[Evidence, ...]:
        query_vector = self.embedding_backend.embed(query)
        scored = []
        for evidence_id, item in self._items.items():
            vector = self._vectors[evidence_id]
            score = _cosine_01(query_vector, vector)
            scored.append(item.with_score(score))
        ranked = sorted(scored, key=lambda item: item.score, reverse=True)
        return tuple(item for item in ranked[:top_k] if item.score > 0.0)

    def count(self) -> int:
        return len(self._items)


def evidence_to_text(item: Evidence) -> str:
    return " ".join((item.title, item.content, " ".join(item.tags), " ".join(item.anchors)))


def _cosine_01(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    import math

    if not left or not right:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return max(0.0, min(1.0, (dot / (left_norm * right_norm) + 1.0) / 2.0))


def create_index(name: str, use_faiss: bool = False) -> VectorIndex:
    if use_faiss:
        from vector_store_faiss import FaissVectorIndex
        return FaissVectorIndex(name)
    return InMemoryVectorIndex(name)
