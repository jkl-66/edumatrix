"""Authenticated cross-language course search over persisted canonical documents."""

from __future__ import annotations

from typing import Any

from app.cross_language_retrieval import expand_ml_query
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
        query=normalized_query,
        top_k=max(20, top_k * 4),
        actor=actor,
    )
    if not canonical.get("items"):
        return {
            "query": normalized_query,
            "course_id": course_id,
            "strategy": "canonical-bm25-semantic-rrf-v2",
            "metadata_excluded": True,
            "matched_concepts": [],
            "added_terms": [],
            "low_confidence": True,
            "reason": "course_documents_unavailable",
            "items": [],
        }

    items, by_document = [], {}
    for result in canonical["items"]:
        if not result.get('relevant'):
            continue
        evidence = result["evidence"]
        source = result["source"]
        source_ref = result["source_ref"]
        chapter = result.get("chapter")
        document_id = str(source.legacy_document_id or source.id)
        ranking = result.get('ranking') or {}
        match = {
            'evidence_id': evidence.id, 'source_ref_id': source_ref.get('source_ref_id', ''),
            'content_preview': str(evidence.content or '')[:500],
            'content_excerpt': str(evidence.content or ''),
            'chapter_id': chapter.id if chapter else source_ref.get('chapter_id', ''),
            'chapter_title': chapter.title if chapter else source_ref.get('chapter_title', ''),
            'char_start': evidence.metadata.get('char_start'), 'char_end': evidence.metadata.get('char_end'),
            'match_char_start': evidence.metadata.get('match_char_start'),
            'match_text': evidence.metadata.get('match_text', ''),
            'bm25_rank': ranking.get('lexical_rank'), 'bm25_score': ranking.get('lexical_score'),
            'semantic_rank': ranking.get('semantic_rank'), 'semantic_score': ranking.get('semantic_score'),
            'fused_score': ranking.get('fused_score'),
        }
        if document_id in by_document:
            by_document[document_id]['matches'].append(match)
            continue
        if len(items) >= top_k:
            continue
        item = (
            {
                "document_id": document_id,
                "filename": source.filename,
                "title": source.title or source.filename,
                "content_preview": str(evidence.content or "")[:500],
                'content_excerpt': str(evidence.content or ''),
                "source_ref_id": source_ref.get("source_ref_id", ""),
                "source_document_id": source.id,
                "chapter_id": chapter.id if chapter else source_ref.get("chapter_id", ""),
                "chapter_title": chapter.title if chapter else source_ref.get("chapter_title", ""),
                "evidence_id": evidence.id,
                "match_char_start": evidence.metadata.get("match_char_start"),
                "match_text": evidence.metadata.get("match_text", ""),
                'semantic_rank': ranking.get('semantic_rank'),
                'semantic_score': ranking.get('semantic_score'),
                'bm25_rank': ranking.get('lexical_rank'),
                'bm25_score': ranking.get('lexical_score'),
                'fused_score': ranking.get('fused_score'),
                'matches': [match],
                "locatable": True,
            }
        )
        items.append(item)
        by_document[document_id] = item
    low_confidence = bool(canonical.get("low_confidence"))
    return {
        "query": normalized_query,
        "course_id": course_id,
        "strategy": "canonical-bm25-semantic-rrf-v2",
        "glossary_version": expansion.glossary_version,
        "fusion": {
            "method": (canonical.get('retrieval') or {}).get('method', 'bm25'),
            'semantic_weight': 1.0 if (canonical.get('retrieval') or {}).get('semantic_executed') else 0.0,
            'bm25_weight': 1.0,
            'rank_constant': (canonical.get('retrieval') or {}).get('rank_constant'),
        },
        'retrieval': canonical.get('retrieval') or {},
        "metadata_excluded": True,
        "matched_concepts": list(expansion.matched_concepts),
        "added_terms": list(expansion.added_terms),
        "low_confidence": low_confidence,
        "reason": "no_body_term_match" if low_confidence and expansion.applied else "",
        "items": items if not low_confidence else [],
    }
