# ingestion.py - COMPLETE REPLACEMENT
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
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
        "\u673a\u5668\u5b66\u4e60",
        "\u76d1\u7763\u5b66\u4e60",
        "\u903b\u8f91\u56de\u5f52",
        "\u6df7\u6dc6\u77e9\u9635",
        "\u8fc7\u62df\u5408",
        "\u6b63\u5219\u5316",
        "\u5377\u79ef\u6838",
        "\u6c60\u5316\u5c42",
        "\u6700\u5927\u6c60\u5316",
        "\u5e73\u5747\u6c60\u5316",
    )
    return tuple(concept for concept in concepts if concept in text)


def _infer_anchors(text: str) -> tuple[str, ...]:
    anchors = re.findall(r"\b[A-Za-z][A-Za-z0-9_.-]{2,}\b", text)
    return tuple(dict.fromkeys(anchors[:8]))
