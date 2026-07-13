from __future__ import annotations

import asyncio
import json
import math
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import faiss
import numpy as np

from embedding_models import EMBEDDINGS, EmbeddingBackend, cosine_similarity
from models import Evidence
from vector_store import VectorIndex


@dataclass
class FaissVectorIndex:
    name: str
    embedding_backend: EmbeddingBackend = field(default_factory=lambda: EMBEDDINGS)
    dim: int = 0
    _items: dict[str, Evidence] = field(default_factory=dict)
    _id_to_idx: dict[str, int] = field(default_factory=dict)
    _idx_to_id: dict[int, str] = field(default_factory=dict)
    _next_idx: int = 0
    _index: faiss.Index = None
    _use_ivf: bool = False
    _write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self):
        if self.dim == 0:
            sample = self.embedding_backend.embed("auto-detect-dim")
            self.dim = len(sample)
        if self._index is None:
            self._index = faiss.IndexFlatIP(self.dim)

    def _ensure_index(self, n: int):
        if self._use_ivf:
            return
        if n >= 256:
            self._use_ivf = True
            nlist = max(1, int(math.sqrt(n)))
            quantizer = faiss.IndexFlatIP(self.dim)
            ivf = faiss.IndexIVFFlat(quantizer, self.dim, nlist, faiss.METRIC_INNER_PRODUCT)
            ivf.train(self._get_all_vectors())
            ivf.add(self._get_all_vectors())
            self._index = ivf
            ivf.nprobe = min(nlist, 10)

    def _get_all_vectors(self) -> np.ndarray:
        vectors = []
        for idx in range(self._next_idx):
            ev_id = self._idx_to_id.get(idx)
            if ev_id and ev_id in self._items:
                vec = self._embed(self._items[ev_id])
                vectors.append(vec)
        return np.array(vectors, dtype=np.float32) if vectors else np.zeros((0, self.dim), dtype=np.float32)

    def _embed(self, item: Evidence) -> np.ndarray:
        text = " ".join((item.title, item.content, " ".join(item.tags), " ".join(item.anchors)))
        vec = self.embedding_backend.embed(text)
        return np.array(vec, dtype=np.float32)

    def _embed_text(self, text: str) -> np.ndarray:
        vec = self.embedding_backend.embed(text)
        return np.array(vec, dtype=np.float32).reshape(1, -1)

    def upsert(self, items: tuple[Evidence, ...]) -> None:
        new_vectors = []
        new_ids = []
        for item in items:
            if item.id in self._items:
                old_idx = self._id_to_idx[item.id]
                self._items[item.id] = item
                vec = self._embed(item)
                faiss.normalize_L2(vec.reshape(1, -1))
                self._index.reconstruct(old_idx)[:] = vec
            else:
                self._items[item.id] = item
                idx = self._next_idx
                self._id_to_idx[item.id] = idx
                self._idx_to_id[idx] = item.id
                self._next_idx += 1
                vec = self._embed(item)
                faiss.normalize_L2(vec.reshape(1, -1))
                new_vectors.append(vec)
                new_ids.append(idx)

        if new_vectors:
            vectors_np = np.array(new_vectors, dtype=np.float32)
            self._index.add(vectors_np)
            self._ensure_index(self._next_idx)

    async def upsert_async(self, items: tuple[Evidence, ...]) -> None:
        """异步安全的写入接口，使用 asyncio.Lock 防止并发竞态。"""
        async with self._write_lock:
            self.upsert(items)

    def search(self, query: str, *, top_k: int) -> tuple[Evidence, ...]:
        if self._next_idx == 0:
            return ()

        q_vec = self._embed_text(query)
        faiss.normalize_L2(q_vec)

        k = min(top_k, self._next_idx)
        distances, indices = self._index.search(q_vec, k)

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx == -1:
                continue
            ev_id = self._idx_to_id.get(int(idx))
            if ev_id and ev_id in self._items:
                item = self._items[ev_id]
                score = max(0.0, min(1.0, float(dist)))
                results.append(item.with_score(score))

        return tuple(results)

    def count(self) -> int:
        return self._next_idx

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        faiss.write_index(self._index, str(path.with_suffix(".faiss")))

        meta = {
            "name": self.name,
            "dim": self.dim,
            "next_idx": self._next_idx,
            "id_to_idx": self._id_to_idx,
            "idx_to_id": {str(k): v for k, v in self._idx_to_id.items()},
            "items": {
                eid: {
                    "id": ev.id,
                    "title": ev.title,
                    "content": ev.content,
                    "modality": ev.modality.value,
                    "source": ev.source,
                    "tags": list(ev.tags),
                    "anchors": list(ev.anchors),
                    "score": ev.score,
                    "metadata": ev.metadata,
                }
                for eid, ev in self._items.items()
            },
        }
        with open(path.with_suffix(".json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> FaissVectorIndex:
        path = Path(path)

        index = faiss.read_index(str(path.with_suffix(".faiss")))

        with open(path.with_suffix(".json"), "r", encoding="utf-8") as f:
            meta = json.load(f)

        items = {}
        for eid, edata in meta["items"].items():
            items[eid] = Evidence(
                id=edata["id"],
                title=edata["title"],
                content=edata["content"],
                modality=EvidenceModality(edata["modality"]),
                source=edata["source"],
                tags=tuple(edata["tags"]),
                anchors=tuple(edata["anchors"]),
                score=edata.get("score", 0.0),
                metadata=edata.get("metadata", {}),
            )

        idx_to_id = {int(k): v for k, v in meta["idx_to_id"].items()}

        instance = cls(
            name=meta["name"],
            dim=meta["dim"],
            _items=items,
            _id_to_idx=meta["id_to_idx"],
            _idx_to_id=idx_to_id,
            _next_idx=meta["next_idx"],
            _index=index,
        )

        if instance._next_idx >= 256 and not instance._use_ivf:
            instance._ensure_index(instance._next_idx)

        return instance


from models import EvidenceModality
