"""Shared retrieval over the canonical course source graph.

All course-grounded callers use this module for the same source/status/location
semantics.  It deliberately leaves embedding implementation to the configured
backend; this task only unifies the data boundary and chunk projection.
"""

from __future__ import annotations

import re
from typing import Any

from app.database import (
    DBChapter,
    DBCourse,
    DBCourseDocument,
    DBKnowledgeDocument,
    DBSourceDocument,
    DBSourceRef,
)
from app.source_refs import project_source_ref
from app.cross_language_retrieval import english_lexical_score, expand_ml_query
from document_parser import chunk_document
from embedding_models import EMBEDDINGS
from models import Evidence, EvidenceModality


def _terms(value: str) -> set[str]:
    normalized = str(value or "").lower()
    words = set(re.findall(r"[a-z0-9_+.-]{2,}|[\u4e00-\u9fff]{2,}", normalized))
    han = re.findall(r"[\u4e00-\u9fff]", normalized)
    words.update("".join(han[index : index + 2]) for index in range(max(0, len(han) - 1)))
    return {item for item in words if item.strip()}


_QUERY_STOP_TERMS = frozenset(
    {
        "课程", "根据", "这门", "材料", "具体", "如何", "什么", "请给", "给出",
        "其中", "以及", "是否", "能够", "需要", "当前", "问题", "为什么", "怎样",
        "哪些", "多少", "一个", "各自", "不同", "同一", "同时", "应该", "系统",
        "学习", "资源", "内容", "用户", "学生", "知识", "回答", "实现", "进行",
        "相关", "完整", "使用", "包含", "范围", "这个", "处理", "结果", "模型",
        "训练", "之前", "还有", "关于", "请", "聚合",
    }
)


def _score(query: str, content: str) -> float:
    q_terms = _terms(query)
    d_terms = _terms(content)
    if not q_terms or not d_terms:
        return 0.0
    overlap = len(q_terms & d_terms)
    lexical = overlap / len(q_terms)
    embedding = float(EMBEDDINGS.score(query, content))
    return min(1.0, lexical * 0.7 + embedding * 0.3)


def _lexical_overlap(query: str, content: str) -> int:
    """Count query terms that are present in the retrieved chunk.

    The embedding backend is intentionally left configurable for this task.  A
    small lexical signal is still required before a course source is treated as
    evidence; otherwise hash/semantic similarity can surface an unrelated
    document for an out-of-scope question.
    """
    overlap = _terms(query) & _terms(content)
    return len(overlap - _QUERY_STOP_TERMS)


def _document_body(session: Any, source: DBSourceDocument) -> str:
    """Read body through the canonical source's legacy identity."""
    legacy_id = str(source.legacy_document_id or "")
    if not legacy_id:
        return ""
    document = session.get(DBCourseDocument, legacy_id)
    if document is not None:
        return str(document.content or "")
    personal = session.get(DBKnowledgeDocument, legacy_id)
    return str(personal.content or "") if personal is not None else ""


def _source_ref_for_chunk(refs: list[DBSourceRef], chunk: Evidence) -> DBSourceRef | None:
    if not refs:
        return None
    content = str(chunk.content or "")
    for ref in refs:
        quote = str(ref.quote or "").strip()
        if quote and (quote[:120] in content or content[:120] in quote):
            return ref
    return sorted(refs, key=lambda item: (item.location_index or 0, item.id))[0]


def list_canonical_source_refs(
    session: Any,
    *,
    course_id: str,
    actor: Any | None = None,
    chapter_ids: list[str] | None = None,
    source_ref_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Project ready course references through the shared source boundary.

    This is the non-ranking companion to :func:`retrieve_canonical_sources` for
    callers that need to freeze a course context (for example canonical Chat).
    It deliberately queries only ready canonical documents and returns the same
    ``project_source_ref`` shape used by ranked retrieval.
    """
    query = (
        session.query(DBSourceRef)
        .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
        .filter(
            DBSourceDocument.course_id == course_id,
            DBSourceDocument.processing_status == "ready",
        )
    )
    if chapter_ids:
        query = query.filter(DBSourceRef.chapter_id.in_(list(dict.fromkeys(chapter_ids))))
    if source_ref_ids:
        query = query.filter(DBSourceRef.id.in_(list(dict.fromkeys(source_ref_ids))))
    projections: list[dict[str, Any]] = []
    for source_ref in query.order_by(DBSourceRef.location_index, DBSourceRef.id).all():
        projection = project_source_ref(
            session,
            str(source_ref.id),
            actor=actor,
            expected_course_id=course_id,
            permission_as_unavailable=True,
        )
        projections.append(projection)
    return projections


def retrieve_canonical_sources(
    session: Any,
    *,
    course_id: str,
    query: str,
    top_k: int = 5,
    actor: Any | None = None,
    source_ref_ids: list[str] | None = None,
    chapter_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Return locatable Evidence from ready canonical sources only.

    ``actor`` is passed to the existing source projection so course membership,
    ownership and visibility rules remain the same for every caller.
    """
    normalized_query = " ".join(str(query or "").split())
    if not normalized_query:
        return {"course_id": course_id, "query": "", "items": [], "low_confidence": True}
    if top_k < 1:
        return {"course_id": course_id, "query": normalized_query, "items": [], "low_confidence": True}
    expansion = expand_ml_query(normalized_query)
    retrieval_query = expansion.expanded_query

    course = session.get(DBCourse, course_id)
    if course is None:
        return {"course_id": course_id, "query": normalized_query, "items": [], "low_confidence": True, "reason": "course_unavailable"}

    refs_query = (
        session.query(DBSourceRef)
        .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
        .filter(
            DBSourceDocument.course_id == course_id,
            DBSourceDocument.processing_status == "ready",
        )
    )
    if source_ref_ids:
        refs_query = refs_query.filter(DBSourceRef.id.in_(list(dict.fromkeys(source_ref_ids))))
    if chapter_ids:
        refs_query = refs_query.filter(DBSourceRef.chapter_id.in_(list(dict.fromkeys(chapter_ids))))
    refs = refs_query.order_by(DBSourceRef.location_index, DBSourceRef.id).all()

    refs_by_source: dict[str, list[DBSourceRef]] = {}
    for ref in refs:
        refs_by_source.setdefault(ref.source_document_id, []).append(ref)

    items: list[dict[str, Any]] = []
    for source_id, source_refs in refs_by_source.items():
        source = session.get(DBSourceDocument, source_id)
        if source is None or source.processing_status != "ready":
            continue
        body = _document_body(session, source)
        if not body.strip():
            continue
        try:
            projection = project_source_ref(
                session,
                source_refs[0].id,
                actor=actor,
                expected_course_id=course_id,
                permission_as_unavailable=True,
            )
        except Exception:
            continue
        if not projection.get("available"):
            continue
        chunks = chunk_document(body, source=f"{course_id}/{source.filename}")
        if not chunks:
            continue
        # A document header can receive a high similarity score while carrying
        # none of the terms that answer the question.  Select the child chunk
        # with the strongest lexical signal first, then use the configured
        # embedding score as the tie breaker; the parser still owns all chunk
        # boundaries and parent metadata.
        def chunk_rank(item: Evidence) -> tuple[float, int, float, str]:
            english_signal = english_lexical_score(expansion, item.content) if expansion.applied else 0.0
            return (
                english_signal,
                _lexical_overlap(retrieval_query, item.content),
                _score(retrieval_query, item.content),
                item.id,
            )

        best_chunk = max(chunks, key=chunk_rank)
        score = _score(retrieval_query, best_chunk.content)
        source_overlap = max(_lexical_overlap(retrieval_query, item.content) for item in chunks)
        source_ref = _source_ref_for_chunk(source_refs, best_chunk)
        if source_ref is None:
            continue
        ref_projection = project_source_ref(
            session,
            source_ref.id,
            actor=actor,
            expected_course_id=course_id,
            permission_as_unavailable=True,
        )
        if not ref_projection.get("available"):
            continue
        # Keep the matched child as the evidence body.  The parent remains
        # available in metadata for callers that need surrounding context, but
        # replacing the child here would hide the terms that justified the hit
        # and would make citations/low-confidence checks disagree with ranking.
        evidence_metadata = {
            **dict(best_chunk.metadata or {}),
            "child_content": best_chunk.content,
            "parent_content": best_chunk.metadata.get("parent_content", ""),
            "course_id": course_id,
            "source_document_id": source.id,
            "source_ref_id": source_ref.id,
            "chapter_id": source_ref.chapter_id,
            "source_ref_content_hash": source_ref.content_hash,
            "parser_version": source_ref.parser_version,
            "document_version": ref_projection.get("document_version", ""),
            "location_kind": ref_projection.get("location_kind", ""),
            "location_index": ref_projection.get("location_index"),
            "location_label": ref_projection.get("location_label", ""),
            "page_number": ref_projection.get("page_number"),
            "char_start": ref_projection.get("char_start"),
            "char_end": ref_projection.get("char_end"),
            "quote": ref_projection.get("quote", ""),
            "source_route": ref_projection.get("route", ""),
            "query_term_overlap": _lexical_overlap(normalized_query, best_chunk.content),
            "source_max_query_term_overlap": source_overlap,
            "query_expansion_applied": expansion.applied,
            "query_expansion_terms": list(expansion.added_terms),
        }
        evidence = Evidence(
            id=best_chunk.id,
            title=f"{source.title} / {best_chunk.title}",
            content=best_chunk.content,
            modality=EvidenceModality.CODE if source.file_format == "py" else EvidenceModality.TEXT,
            source=source.filename,
            tags=best_chunk.tags,
            anchors=best_chunk.anchors,
            metadata=evidence_metadata,
        ).with_score(score)
        chapter = session.get(DBChapter, source_ref.chapter_id) if source_ref.chapter_id else None
        items.append({
            "evidence": evidence,
            "score": score,
            "source_ref": ref_projection,
            "source": source,
            "chapter": chapter,
        })

    items.sort(key=lambda item: (-float(item["score"]), str(item["evidence"].id)))
    selected = items[:top_k]
    overlap_count = (
        int(selected[0]["evidence"].metadata.get("source_max_query_term_overlap") or 0)
        if selected
        else 0
    )
    # Require a concrete lexical signal in addition to the configured score.
    # Three matching terms is deliberately modest for the course corpus and
    # rejects hash-similarity-only hits for material the course does not cover.
    top_score = float(selected[0]["score"]) if selected else 0.0
    low_confidence = (
        not selected
        or (top_score < 0.30 and overlap_count < 3)
    )
    return {
        "course_id": course_id,
        "query": normalized_query,
        "retrieval_query": retrieval_query,
        "items": selected,
        "evidence": tuple(item["evidence"] for item in selected),
        "low_confidence": low_confidence,
        "reason": (
            "no_ready_canonical_source"
            if not selected
            else "no_body_term_match"
            if low_confidence
            else ""
        ),
    }
