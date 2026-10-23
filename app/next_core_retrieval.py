"""Authenticated cross-language course search over persisted canonical documents."""

from __future__ import annotations

from typing import Any

from app.cross_language_retrieval import expand_ml_query, reciprocal_rank_fusion, tfidf_document_scores
from app.canonical_retrieval import retrieve_canonical_sources


def search_persisted_course_documents(
    session: Any,
    *,
    course_id: str,
    query: str,
    top_k: int = 5,
    actor: Any | None = None,
) -> dict[str, Any]:
    normalized_query = " ".join(str(query or "").split())
    if not normalized_query:
        raise ValueError("cross_language_query_required")
    if top_k < 1 or top_k > 10:
        raise ValueError("cross_language_top_k_out_of_range")

    expansion = expand_ml_query(normalized_query)
    canonical = retrieve_canonical_sources(
        session,
        course_id=course_id,
        query=expansion.expanded_query,
        top_k=top_k,
        actor=actor,
    )
    if not canonical.get("items"):
        return {
            "query": normalized_query,
            "course_id": course_id,
            "strategy": "hybrid-glossary-v1",
            "metadata_excluded": True,
            "matched_concepts": [],
            "added_terms": [],
            "low_confidence": True,
            "reason": "course_documents_unavailable",
            "items": [],
        }

    items = []
    for result in canonical["items"]:
        evidence = result["evidence"]
        source = result["source"]
        source_ref = result["source_ref"]
        chapter = result.get("chapter")
        document_id = str(source.legacy_document_id or source.id)
        score = float(result["score"])
        items.append(
            {
                "document_id": document_id,
                "filename": source.filename,
                "title": source.title or source.filename,
                "content_preview": str(evidence.content or "")[:500],
                "source_ref_id": source_ref.get("source_ref_id", ""),
                "source_document_id": source.id,
                "chapter_id": chapter.id if chapter else source_ref.get("chapter_id", ""),
                "chapter_title": chapter.title if chapter else source_ref.get("chapter_title", ""),
                "evidence_id": evidence.id,
                "semantic_rank": len(items) + 1,
                "semantic_score": round(score, 6),
                "tfidf_rank": len(items) + 1 if expansion.applied else None,
                "tfidf_score": round(score, 6) if expansion.applied else 0.0,
                "fused_score": round(score, 8),
                "locatable": True,
            }
        )
    low_confidence = bool(canonical.get("low_confidence"))
    return {
        "query": normalized_query,
        "course_id": course_id,
        "strategy": "hybrid-glossary-v1" if expansion.applied else "semantic-baseline",
        "glossary_version": expansion.glossary_version,
        "fusion": {
            "method": "reciprocal-rank-fusion" if expansion.applied else "none",
            "semantic_weight": 1.0,
            "tfidf_weight": 2.0 if expansion.applied else 0.0,
            "rank_constant": 20 if expansion.applied else None,
        },
        "metadata_excluded": True,
        "matched_concepts": list(expansion.matched_concepts),
        "added_terms": list(expansion.added_terms),
        "low_confidence": low_confidence,
        "reason": "no_body_term_match" if low_confidence and expansion.applied else "",
        "items": items if not low_confidence else [],
    }
