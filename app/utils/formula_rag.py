"""公式 LaTeX 双轨增强检索模块。

职责:
  1. 将公式源码和自然语言语义同时嵌入向量空间 (bge-m3 双轨)
  2. 存入 ChromaDB 向量库 (降级: InMemoryVectorIndex)
  3. 检索时对公式源码和语义双轨召回并融合排序
  4. 验收: "损失函数对权重的偏导数" -> 召回含 ∂L/∂W 的 Chunk (cos > 0.88)
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.utils.exceptions import FormulaIndexError
from app.utils.formula_extractor import (
    ExtractedFormula,
    FormulaExtractor,
    _latex_to_semantic,
)
from config import CONFIG
from embedding_models import EMBEDDINGS
from models import Evidence, EvidenceModality


# ---------------------------------------------------------------------------
# Dual-track embedding
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DualTrackVector:
    """公式双轨向量: 源码轨道 + 语义轨道。"""
    chunk_id: str
    latex_vector: tuple[float, ...]
    semantic_vector: tuple[float, ...]
    latex_source: str
    semantic_text: str
    metadata: dict[str, Any] = field(default_factory=dict)


def encode_dual_track(formula: ExtractedFormula, chunk_id: str = "") -> DualTrackVector:
    """对公式生成双轨嵌入向量。

    Track-1: LaTeX 源码嵌入 (保留公式结构信息)
    Track-2: 自然语言语义嵌入 (保留语义信息)
    """
    fid = chunk_id or f"DUAL_{hash(formula.latex_source) % 100000:05d}"

    # Track-1: LaTeX source embedding
    latex_text = formula.latex_source.strip()
    if not latex_text:
        latex_text = "empty_formula"
    latex_vector = tuple(EMBEDDINGS.embed(latex_text))

    # Track-2: Semantic text embedding
    semantic_text = formula.semantic_text.strip()
    if not semantic_text:
        semantic_text = _latex_to_semantic(formula.latex_source)
    semantic_vector = tuple(EMBEDDINGS.embed(semantic_text))

    return DualTrackVector(
        chunk_id=fid,
        latex_vector=latex_vector,
        semantic_vector=semantic_vector,
        latex_source=formula.latex_source,
        semantic_text=semantic_text,
        metadata={
            "bbox": list(formula.bbox),
            "confidence": formula.confidence,
            "source_file": formula.source_file,
        },
    )


def _cosine_similarity(v1: tuple[float, ...] | list[float], v2: tuple[float, ...] | list[float]) -> float:
    """Standard cosine similarity in [-1, 1], clamped to [0, 1]."""
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = math.sqrt(sum(a * a for a in v1))
    n2 = math.sqrt(sum(b * b for b in v2))
    if n1 == 0.0 or n2 == 0.0:
        return 0.0
    return max(0.0, min(1.0, (dot / (n1 * n2) + 1.0) / 2.0))


# ---------------------------------------------------------------------------
# Formula vector store (ChromaDB with in-memory fallback)
# ---------------------------------------------------------------------------
class FormulaVectorStore(Protocol):
    """公式向量存储协议。"""
    def upsert(self, vectors: tuple[DualTrackVector, ...]) -> int: ...
    def search(self, query: str, *, top_k: int, min_similarity: float) -> tuple[FormulaSearchHit, ...]: ...
    def count(self) -> int: ...


@dataclass(frozen=True)
class FormulaSearchHit:
    """公式检索命中结果。"""
    chunk_id: str
    latex_source: str
    semantic_text: str
    score: float
    track: str  # "latex" / "semantic" / "fused"
    metadata: dict[str, Any] = field(default_factory=dict)


class InMemoryFormulaStore:
    """内存公式向量存储 (ChromaDB 不可用时的降级方案)。"""

    def __init__(self) -> None:
        self._vectors: dict[str, DualTrackVector] = {}

    def upsert(self, vectors: tuple[DualTrackVector, ...]) -> int:
        count = 0
        for v in vectors:
            self._vectors[v.chunk_id] = v
            count += 1
        return count

    def search(self, query: str, *, top_k: int = 6, min_similarity: float = 0.5) -> tuple[FormulaSearchHit, ...]:
        query_vec = tuple(EMBEDDINGS.embed(query))
        hits: list[FormulaSearchHit] = []
        for v in self._vectors.values():
            latex_score = _cosine_similarity(query_vec, v.latex_vector)
            semantic_score = _cosine_similarity(query_vec, v.semantic_vector)
            # Fused score: weighted combination
            fused = 0.4 * latex_score + 0.6 * semantic_score
            best_track = "fused"
            best_score = fused
            if latex_score > best_score:
                best_score = latex_score
                best_track = "latex"
            if semantic_score > best_score:
                best_score = semantic_score
                best_track = "semantic"
            if best_score >= min_similarity:
                hits.append(FormulaSearchHit(
                    chunk_id=v.chunk_id,
                    latex_source=v.latex_source,
                    semantic_text=v.semantic_text,
                    score=round(best_score, 4),
                    track=best_track,
                    metadata=v.metadata,
                ))
        hits.sort(key=lambda h: h.score, reverse=True)
        return tuple(hits[:top_k])

    def count(self) -> int:
        return len(self._vectors)


class ChromaDBFormulaStore:
    """ChromaDB 公式向量存储。"""

    def __init__(self, collection_name: str = "edumatrix_formulas", persist_dir: str = "") -> None:
        self._collection_name = collection_name
        self._persist_dir = persist_dir or getattr(CONFIG, "chroma_persist_dir", "data/chroma_db")
        self._client: Any = None
        self._collection: Any = None
        self._fallback = InMemoryFormulaStore()

    def _get_collection(self) -> Any:
        if self._collection is not None:
            return self._collection
        try:
            import chromadb
            self._client = chromadb.PersistentClient(path=self._persist_dir)
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            return self._collection
        except ImportError:
            return None

    def upsert(self, vectors: tuple[DualTrackVector, ...]) -> int:
        collection = self._get_collection()
        if collection is None:
            return self._fallback.upsert(vectors)
        try:
            ids = []
            latex_embeddings = []
            semantic_embeddings = []
            documents = []
            metadatas = []
            for v in vectors:
                ids.append(v.chunk_id)
                latex_embeddings.append(list(v.latex_vector))
                semantic_embeddings.append(list(v.semantic_vector))
                documents.append(f"[LaTeX_Source: $${v.latex_source}$$] (公式语义解释: {v.semantic_text})")
                meta = dict(v.metadata)
                meta["latex_source"] = v.latex_source
                meta["semantic_text"] = v.semantic_text
                metadatas.append(meta)

            # Store with semantic vectors (primary track)
            collection.upsert(
                ids=ids,
                embeddings=semantic_embeddings,
                documents=documents,
                metadatas=metadatas,
            )
            # Also store latex track in a separate set
            latex_ids = [f"{id_}_latex" for id_ in ids]
            latex_metadatas = [dict(m, track="latex") for m in metadatas]
            collection.upsert(
                ids=latex_ids,
                embeddings=latex_embeddings,
                documents=documents,
                metadatas=latex_metadatas,
            )
            return len(vectors)
        except Exception as exc:
            raise FormulaIndexError(f"ChromaDB 写入失败: {exc}") from exc

    def search(self, query: str, *, top_k: int = 6, min_similarity: float = 0.5) -> tuple[FormulaSearchHit, ...]:
        collection = self._get_collection()
        if collection is None:
            return self._fallback.search(query, top_k=top_k, min_similarity=min_similarity)
        try:
            query_embedding = list(EMBEDDINGS.embed(query))
            # Search semantic track
            sem_results = collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                include=["documents", "metadatas", "distances"],
                where={"track": {"$ne": "latex"}} if collection.count() > top_k else None,
            )
            # Search latex track
            latex_results = collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                include=["documents", "metadatas", "distances"],
                where={"track": "latex"} if collection.count() > top_k else None,
            )

            hits: list[FormulaSearchHit] = []
            seen: set[str] = set()

            for ids, distances, metas in zip(
                sem_results.get("ids", [[]]),
                sem_results.get("distances", [[]]),
                sem_results.get("metadatas", [[]]),
            ):
                for id_, dist, meta in zip(ids, distances, metas):
                    chunk_id = id_.replace("_latex", "")
                    if chunk_id in seen:
                        continue
                    seen.add(chunk_id)
                    score = max(0.0, 1.0 - dist)
                    if score >= min_similarity:
                        hits.append(FormulaSearchHit(
                            chunk_id=chunk_id,
                            latex_source=meta.get("latex_source", ""),
                            semantic_text=meta.get("semantic_text", ""),
                            score=round(score, 4),
                            track="semantic",
                            metadata=meta,
                        ))

            for ids, distances, metas in zip(
                latex_results.get("ids", [[]]),
                latex_results.get("distances", [[]]),
                latex_results.get("metadatas", [[]]),
            ):
                for id_, dist, meta in zip(ids, distances, metas):
                    chunk_id = id_.replace("_latex", "")
                    score = max(0.0, 1.0 - dist)
                    if chunk_id in seen:
                        # Fuse: take max score
                        for h in hits:
                            if h.chunk_id == chunk_id:
                                fused = 0.4 * score + 0.6 * h.score
                                object.__setattr__(h, "score", round(max(fused, h.score, score), 4))
                                object.__setattr__(h, "track", "fused")
                                break
                    else:
                        seen.add(chunk_id)
                        if score >= min_similarity:
                            hits.append(FormulaSearchHit(
                                chunk_id=chunk_id,
                                latex_source=meta.get("latex_source", ""),
                                semantic_text=meta.get("semantic_text", ""),
                                score=round(score, 4),
                                track="latex",
                                metadata=meta,
                            ))

            hits.sort(key=lambda h: h.score, reverse=True)
            return tuple(hits[:top_k])
        except Exception as exc:
            return self._fallback.search(query, top_k=top_k, min_similarity=min_similarity)

    def count(self) -> int:
        collection = self._get_collection()
        if collection is None:
            return self._fallback.count()
        try:
            return collection.count()
        except Exception:
            return self._fallback.count()


def create_formula_store(
    *,
    use_chroma: bool | None = None,
    collection_name: str = "edumatrix_formulas",
    persist_dir: str = "",
) -> FormulaVectorStore:
    """工厂方法: 优先使用 ChromaDB, 降级使用内存存储。"""
    if use_chroma is None:
        use_chroma = getattr(CONFIG, "use_chromadb", False)
    if use_chroma:
        try:
            store = ChromaDBFormulaStore(collection_name=collection_name, persist_dir=persist_dir)
            store.count()  # verify connectivity
            return store
        except Exception:
            pass
    return InMemoryFormulaStore()


# ---------------------------------------------------------------------------
# FormulaRAG — dual-track formula retrieval
# ---------------------------------------------------------------------------
class FormulaRAG:
    """公式 LaTeX 双轨增强检索系统。

    检索流程:
      1. 用户查询 -> 嵌入向量
      2. 双轨搜索: LaTeX 源码轨道 + 语义轨道
      3. 融合排序 -> 返回 Top-K 结果
    """

    def __init__(
        self,
        store: FormulaVectorStore | None = None,
        extractor: FormulaExtractor | None = None,
    ) -> None:
        self.store = store or create_formula_store()
        self.extractor = extractor or FormulaExtractor()

    def index_formulas(
        self,
        formulas: tuple[ExtractedFormula, ...],
        *,
        source: str = "",
    ) -> int:
        """将提取的公式批量索引到向量库。"""
        vectors: list[DualTrackVector] = []
        for i, formula in enumerate(formulas):
            chunk_id = f"FORMULA_{hashlib.sha256(f'{source}:{i}:{formula.latex_source[:32]}'.encode()).hexdigest()[:12]}"
            v = encode_dual_track(formula, chunk_id=chunk_id)
            vectors.append(v)
        return self.store.upsert(tuple(vectors))

    def index_from_image(self, image_input: Any, *, source_file: str = "") -> int:
        """从图像提取公式并索引。"""
        formulas = self.extractor.extract_from_image(image_input, source_file=source_file)
        return self.index_formulas(formulas, source=source_file)

    def index_from_text(self, text: str, *, source_file: str = "") -> int:
        """从文本提取 LaTeX 公式并索引。"""
        formulas = self.extractor.extract_from_text(text, source_file=source_file)
        return self.index_formulas(formulas, source=source_file)

    def search(
        self,
        query: str,
        *,
        top_k: int = 6,
        min_similarity: float = 0.5,
    ) -> tuple[FormulaSearchHit, ...]:
        """双轨检索公式。"""
        return self.store.search(query, top_k=top_k, min_similarity=min_similarity)

    def search_as_evidence(
        self,
        query: str,
        *,
        top_k: int = 4,
        min_similarity: float = 0.5,
    ) -> tuple[Evidence, ...]:
        """检索公式并转换为 Evidence 对象 (供 HybridRAGPipeline 使用)。"""
        hits = self.search(query, top_k=top_k, min_similarity=min_similarity)
        return tuple(
            Evidence(
                id=hit.chunk_id,
                title=f"公式: {hit.semantic_text[:60]}",
                content=f"[LaTeX_Source: $${hit.latex_source}$$] (公式语义解释: {hit.semantic_text})",
                modality=EvidenceModality.IMAGE,
                source=hit.metadata.get("source_file", "formula-rag"),
                tags=("公式", "LaTeX"),
                anchors=(hit.latex_source[:40],),
                score=hit.score,
                metadata=hit.metadata,
            )
            for hit in hits
        )


# ---------------------------------------------------------------------------
# Seed formula index with built-in ML formulas
# ---------------------------------------------------------------------------
def seed_formula_index(rag: FormulaRAG | None = None) -> int:
    """将内置的机器学习公式导入向量库。"""
    r = rag or FormulaRAG()
    builtin_formulas = (
        ExtractedFormula(
            latex_source=r"\frac{\partial L}{\partial W}",
            semantic_text="损失函数对权重的偏导数",
            bbox=(0, 0, 200, 50),
            confidence=1.0,
        ),
        ExtractedFormula(
            latex_source=r"\frac{\partial L}{\partial b}",
            semantic_text="损失函数对偏置的偏导数",
            bbox=(0, 0, 200, 50),
            confidence=1.0,
        ),
        ExtractedFormula(
            latex_source=r"L = -\sum_{i} y_i \log(\hat{y}_i)",
            semantic_text="交叉熵损失函数",
            bbox=(0, 0, 300, 50),
            confidence=1.0,
        ),
        ExtractedFormula(
            latex_source=r"\sigma(z) = \frac{1}{1 + e^{-z}}",
            semantic_text="Sigmoid 激活函数",
            bbox=(0, 0, 250, 50),
            confidence=1.0,
        ),
        ExtractedFormula(
            latex_source=r"\hat{y} = \text{softmax}(z)_j = \frac{e^{z_j}}{\sum_{k} e^{z_k}}",
            semantic_text="Softmax 函数",
            bbox=(0, 0, 350, 50),
            confidence=1.0,
        ),
        ExtractedFormula(
            latex_source=r"W := W - \alpha \frac{\partial L}{\partial W}",
            semantic_text="梯度下降权重更新公式",
            bbox=(0, 0, 300, 50),
            confidence=1.0,
        ),
        ExtractedFormula(
            latex_source=r"\text{MSE} = \frac{1}{n}\sum_{i=1}^{n}(y_i - \hat{y}_i)^2",
            semantic_text="均方误差损失函数",
            bbox=(0, 0, 350, 50),
            confidence=1.0,
        ),
        ExtractedFormula(
            latex_source=r"J(\theta) = \frac{1}{2m}\sum_{i=1}^{m}(h_\theta(x^{(i)}) - y^{(i)})^2 + \frac{\lambda}{2m}\sum_{j=1}^{n}\theta_j^2",
            semantic_text="正则化代价函数 (L2 正则化)",
            bbox=(0, 0, 500, 50),
            confidence=1.0,
        ),
    )
    return r.index_formulas(builtin_formulas, source="builtin-seed")
