# ingestion.py - COMPLETE REPLACEMENT
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import hashlib
import re

from config import CONFIG
from models import Evidence, EvidenceModality
from vector_store import VectorIndex


@dataclass(frozen=True)
class IngestionReport:
    source: str
    chunks: int
    text_chunks: int
    image_patches: int
    target_index: str
    persisted: bool = False
    persist_path: str = ""


@dataclass(frozen=True)
class DocumentChunk:
    id: str
    title: str
    content: str
    source: str
    modality: EvidenceModality
    page: int | None = None
    tags: tuple[str, ...] = ()
    anchors: tuple[str, ...] = ()

    def to_evidence(self) -> Evidence:
        metadata = {}
        if self.page is not None:
            metadata["page"] = self.page
        return Evidence(
            id=self.id,
            title=self.title,
            content=self.content,
            modality=self.modality,
            source=self.source,
            tags=self.tags,
            anchors=self.anchors,
            metadata=metadata,
        )


class DocumentIngestionPipeline:
    """Dataset-ready ingestion pipeline for course material.

    Real PDF rendering/OCR can be plugged into `chunk_document`; the current
    implementation supports plain text and Markdown so teams can validate the
    indexing contract before the final dataset arrives.

    When a FaissVectorIndex is used, the pipeline automatically persists the
    index to ``data/faiss_indexes/<index_name>`` after each ingest call so
    that the FAISS data survives server restarts.
    """

    def __init__(
        self,
        index: VectorIndex,
        *,
        chunk_size: int = 520,
        overlap: int = 80,
        faiss_index_dir: str | Path | None = None,
    ) -> None:
        self.index = index
        self.chunk_size = chunk_size
        self.overlap = overlap
        self._faiss_index_dir = Path(faiss_index_dir or CONFIG.faiss_index_dir)
        if not self._faiss_index_dir.is_absolute():
            self._faiss_index_dir = Path(__file__).resolve().parent / self._faiss_index_dir

    def ingest_text(self, text: str, *, source: str, title: str = "course-material") -> IngestionReport:
        chunks = self.chunk_text(text, source=source, title=title)
        evidence = tuple(chunk.to_evidence() for chunk in chunks)
        self.index.upsert(evidence)
        persisted, persist_path = self._maybe_persist()
        
        # 提取当前文档所有知识点标签，异步触发庞加莱 2D 坐标的双曲 MDS 预计算并写入 DB 缓存
        all_tags = set()
        for chunk in chunks:
            all_tags.update(chunk.tags)
            
        if all_tags:
            try:
                from embedding_models import EMBEDDINGS
                from bkt_engine import poincare_to_2d_coordinates
                import threading
                
                tag_embeddings = {}
                for tag in all_tags:
                    vec = EMBEDDINGS.embed(tag)
                    if vec:
                        tag_embeddings[tag] = vec
                        
                if tag_embeddings:
                    # 在后台 Daemon 线程中异步运行 HMDS，完全不阻塞当前 Ingestion 管道
                    t = threading.Thread(
                        target=poincare_to_2d_coordinates,
                        args=(tag_embeddings,),
                        daemon=True
                    )
                    t.start()
            except Exception as e:
                print(f"[Ingestion HMDS Cache Trigger Error] {e}")

        return IngestionReport(
            source=source,
            chunks=len(chunks),
            text_chunks=len(chunks),
            image_patches=0,
            target_index=self.index.name,
            persisted=persisted,
            persist_path=persist_path,
        )

    def ingest_file(self, path: str | Path) -> IngestionReport:
        file_path = Path(path)
        text = file_path.read_text(encoding="utf-8")
        return self.ingest_text(text, source=str(file_path), title=file_path.stem)

    def chunk_text(self, text: str, *, source: str, title: str) -> tuple[DocumentChunk, ...]:
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            return ()
        chunks: list[DocumentChunk] = []
        start = 0
        index = 1
        while start < len(normalized):
            end = min(len(normalized), start + self.chunk_size)
            content = normalized[start:end].strip()
            chunk_id = _stable_chunk_id(source, index, content)
            chunks.append(
                DocumentChunk(
                    id=chunk_id,
                    title=f"{title} chunk {index}",
                    content=content,
                    source=source,
                    modality=EvidenceModality.TEXT,
                    tags=_infer_tags(content),
                    anchors=_infer_anchors(content),
                )
            )
            if end == len(normalized):
                break
            start = max(end - self.overlap, start + 1)
            index += 1
        return tuple(chunks)

    def _maybe_persist(self) -> tuple[bool, str]:
        """Persist the underlying index to disk if it is a FaissVectorIndex."""
        from vector_store_faiss import FaissVectorIndex

        if not isinstance(self.index, FaissVectorIndex):
            return False, ""

        save_path = self._faiss_index_dir / f"{self.index.name}_index"
        try:
            self.index.save(save_path)
            return True, str(save_path)
        except Exception:
            return False, ""


def _stable_chunk_id(source: str, index: int, content: str) -> str:
    digest = hashlib.sha1(f"{source}:{index}:{content}".encode("utf-8")).hexdigest()[:12]
    return f"DOC_{digest}"


def _infer_tags(text: str) -> tuple[str, ...]:
    concepts = (
        "\u673a\u5668\u5b66\u4e60", "\u76d1\u7763\u5b66\u4e60", "\u903b\u8f91\u56de\u5f52", "\u6df7\u6dc6\u77e9\u9635", "\u8fc7\u62df\u5408",
        "\u6b63\u5219\u5316", "\u5377\u79ef\u6838", "\u6c60\u5316\u5c42", "\u6700\u5927\u6c60\u5316", "\u5e73\u5747\u6c60\u5316",
        "\u68af\u5ea6\u4e0b\u964d", "\u53cd\u5411\u4f20\u64ad", "\u94fe\u5f0f\u6cd5\u5219", "\u6fc0\u6d3b\u51fd\u6570", "\u635f\u5931\u51fd\u6570",
        "\u795e\u7ecf\u7f51\u7edc", "\u51b3\u7b56\u6811", "\u652f\u6301\u5411\u91cf\u673a", "\u7ebf\u6027\u56de\u5f52", "\u4ea4\u53c9\u9a8c\u8bc1",
        "\u7279\u5f81\u56fe", "\u524d\u5411\u4f20\u64ad", "\u6b20\u62df\u5408", "Transformer", "\u6ce8\u610f\u529b\u673a\u5236",
        "\u6a21\u578b\u8bc4\u4f30", "\u5377\u79ef\u795e\u7ecf\u7f51\u7edc",
    )
    return tuple(concept for concept in concepts if concept in text)


def _infer_anchors(text: str) -> tuple[str, ...]:
    anchors = re.findall(r"\b[A-Za-z][A-Za-z0-9_.-]{2,}\b", text)
    return tuple(dict.fromkeys(anchors[:8]))


# ---------------------------------------------------------------------------
# \u53e5\u7ea7\u522b diff & \u589e\u91cf\u56fe\u8c31\u81ea\u751f\u957f (Task 2)
# ---------------------------------------------------------------------------

def _sentence_diff(previous_text: str, new_text: str) -> list[str]:
    """\u5bf9\u4e24\u6bb5\u6587\u672c\u505a\u53e5\u7ea7\u522b diff\uff0c\u8fd4\u56de\u4ec5\u5b58\u5728\u4e8e\u65b0\u6587\u672c\u4e2d\u7684\u53e5\u5b50\u3002

    \u6309\u4e2d\u82f1\u6587\u6807\u70b9\u65ad\u53e5\uff0cHashSet \u6bd4\u8f83\uff0cO(n) \u590d\u6742\u5ea6\u3002
    \u5f53 previous_text \u4e3a\u7a7a\u65f6\uff0c\u8fd4\u56de new_text \u7684\u6240\u6709\u53e5\u5b50\uff08\u9996\u6b21\u4e0a\u4f20\uff09\u3002
    """
    def _split_sentences(text: str) -> list[str]:
        if not text or not text.strip():
            return []
        # \u6309 \u3002\uff01\uff1f\n \u65ad\u53e5\uff0c\u4fdd\u7559\u957f\u5ea6>=4 \u7684\u6709\u610f\u4e49\u53e5\u5b50
        parts = re.split(r"[\u3002\uff01\uff1f\n]+", text)
        return [p.strip() for p in parts if len(p.strip()) >= 4]

    new_sentences = _split_sentences(new_text)
    if not new_sentences:
        return []

    if not previous_text or not previous_text.strip():
        return new_sentences  # \u9996\u6b21\u4e0a\u4f20\uff0c\u5168\u91cf\u8fd4\u56de

    old_set = set(_split_sentences(previous_text))
    # \u8fd4\u56de\u4ec5\u5728 new \u4e2d\u51fa\u73b0\u7684\u65b0\u53e5\u5b50
    diff = [s for s in new_sentences if s not in old_set]
    return diff


# \u61d2\u52a0\u8f7d\u5168\u5c40\u56fe\u8c31\u6784\u5efa\u5668
_graph_builder: Any = None


def _get_graph_builder():
    """\u5ef6\u8fdf\u521d\u59cb\u5316\u56fe\u8c31\u6784\u5efa\u5668\uff08InMemory \u540e\u7aef\uff0c\u79cd\u5b50\u6570\u636e\u9884\u586b\u5145\uff09\u3002"""
    global _graph_builder
    if _graph_builder is not None:
        return _graph_builder
    try:
        from app.utils.graph_builder import GraphBuilder, create_graph_repository, seed_default_graph
        from llm_client import DEFAULT_ASYNC_LLM
        repo = create_graph_repository()
        _graph_builder = GraphBuilder(repository=repo, llm=DEFAULT_ASYNC_LLM)
        seed_default_graph(_graph_builder)
    except Exception as e:
        print(f"  [ingestion] \u56fe\u8c31\u6784\u5efa\u5668\u521d\u59cb\u5316\u5931\u8d25: {e}")
        _graph_builder = None
    return _graph_builder


def build_graph_after_upload(
    evidence_chunks: tuple,
    source: str,
    previous_text: str = "",
) -> Any | None:
    """\u6587\u6863\u4e0a\u4f20\u540e\u89e6\u53d1\u589e\u91cf\u56fe\u8c31\u81ea\u751f\u957f (Task 2)\u3002

    1. \u63d0\u53d6\u65b0\u6587\u672c\u7684\u53e5\u7ea7\u522b diff
    2. \u4ec5\u5bf9\u5dee\u5f02\u53e5\u8c03\u7528 GraphBuilder \u63d0\u53d6\u4e09\u5143\u7ec4
    3. \u65b0\u8fb9\u5408\u5e76\u5230\u56fe\u8c31\u5e76\u540c\u6b65\u5230 RAG \u5f15\u64ce

    Args:
        evidence_chunks: chunk_document \u8f93\u51fa\u7684 Evidence \u5143\u7ec4
        source: \u6587\u4ef6\u540d\uff08\u4f5c\u4e3a\u56fe\u8c31\u6784\u5efa\u7684 source \u6807\u8bc6\uff09
        previous_text: \u540c\u4e00\u6587\u6863\u7684\u65e7\u6587\u672c\uff08\u9996\u6b21\u4e0a\u4f20\u4f20\u7a7a\u5b57\u7b26\u4e32\uff09

    Returns:
        GraphBuildReport \u6216 None\uff08\u56fe\u8c31\u4e0d\u53ef\u7528\u65f6\uff09
    """
    builder = _get_graph_builder()
    if builder is None:
        return None

    # \u7ec4\u88c5\u65b0\u4e0a\u4f20\u6587\u672c
    new_text = "\n".join(
        chunk.content for chunk in evidence_chunks if getattr(chunk, "content", "").strip()
    )
    if not new_text.strip():
        return None

    # \u53e5\u7ea7\u522b diff\uff1a\u53ea\u5bf9\u65b0\u589e\u5185\u5bb9\u63d0\u53d6\u4e09\u5143\u7ec4
    diff_sentences = _sentence_diff(previous_text, new_text)
    if not diff_sentences:
        return None

    try:
        report = builder.build_from_chunks(tuple(diff_sentences), source=source)
        # \u5c06\u65b0\u8fb9\u540c\u6b65\u5230 RAG \u5f15\u64ce
        from rag_engine import hybrid_rag
        if hasattr(builder.repository, "edges") and builder.repository.edges:
            hybrid_rag.graph._load_dynamic_edges(builder.repository)

        # === \u8de8\u6587\u6863\u5171\u73b0\u5173\u8054\uff08CO_OCCUR\uff09===
        try:
            co_occur_count = _build_co_occur_edges(evidence_chunks, source, builder)
        except Exception as e:
            co_occur_count = 0
            print(f"  [CO_OCCUR] \u8de8\u6587\u6863\u5173\u8054\u5931\u8d25\uff08\u975e\u81f4\u547d\uff09: {e}")

        return report
    except Exception as e:
        print(f"  [ingestion] \u56fe\u8c31\u81ea\u751f\u957f\u5931\u8d25\uff08\u975e\u81f4\u547d\uff09: {e}")
        return None


def _build_co_occur_edges(evidence_chunks: tuple, source: str, builder: Any) -> int:
    """\u8de8\u6587\u6863\u5171\u73b0\u5173\u8054\uff1a\u5bf9\u65b0\u5207\u7247\u641c\u7d22\u5df2\u6709\u7d22\u5f15\u4e2d\u76f8\u4f3c\u5ea6>0.85\u7684\u5207\u7247\uff0c\u5efa\u7acb CO_OCCUR \u8fb9\u3002"""
    if not evidence_chunks:
        return 0
    from rag_engine import hybrid_rag
    count = 0
    for chunk in evidence_chunks:
        content = getattr(chunk, "content", "") or ""
        if not content.strip():
            continue
        try:
            results = hybrid_rag.user_index.search(content, top_k=5)
        except Exception:
            continue
        for item in results:
            if getattr(item, "source", "") == source:
                continue
            if item.score >= 0.85:
                src_concept = source[:30]
                tgt_concept = getattr(item, "source", "")[:30] or f"chunk_{item.id[:8]}"
                if hasattr(builder.repository, "merge_edge"):
                    try:
                        builder.repository.merge_edge(src_concept, tgt_concept, "CO_OCCUR")
                        count += 1
                    except Exception:
                        pass
    if count:
        print(f"  [CO_OCCUR] \u8de8\u6587\u6863\u5171\u73b0\u8fb9: {count}")
    return count
