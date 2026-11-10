"""Shared retrieval over the canonical course source graph.

All course-grounded callers share source/status/location checks and the same
chunk-level BM25/semantic rankings. Hash embeddings are not semantic retrieval.
"""

from __future__ import annotations

import re
from dataclasses import replace
from functools import lru_cache
from typing import Any

from app.database import (
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
    DBCourseDocument,
    DBKnowledgeDocument,
    DBKnowledgePoint,
    DBSourceDocument,
    DBSourceRef,
)
from app.source_refs import project_source_ref, current_source_clause, current_structure_ref_clause
from app.cross_language_retrieval import english_lexical_score, expand_ml_query
from app.retrieval_ranking import indexing_text, rank_chunks, retrieval_tokens
from document_parser import chunk_document
from embedding_models import EMBEDDINGS
from models import Evidence, EvidenceModality


def _terms(value: str) -> set[str]:
    # Match the ranking tokenizer: do not invent Han bigrams across English,
    # punctuation or separate words, or treat question filler as subject evidence.
    return set(retrieval_tokens(value, stop_terms=_QUERY_STOP_TERMS))


_QUERY_STOP_TERMS = frozenset(
    {
        "课程", "根据", "这门", "材料", "具体", "如何", "什么", "请给", "给出",
        "其中", "以及", "是否", "能够", "需要", "当前", "问题", "为什么", "怎样",
        "哪些", "多少", "一个", "各自", "不同", "同一", "同时", "应该", "系统",
        "学习", "资源", "内容", "用户", "学生", "知识", "回答", "实现", "进行",
        "相关", "完整", "使用", "包含", "范围", "这个", "处理", "结果", "模型",
        "之前", "还有", "关于", "请", "提供", "聚合", "不是", "是只", "而不", "只看",
    }
)


def _lexical_overlap(query: str, content: str) -> int:
    """Count query terms that are present in the retrieved chunk.

    The embedding backend is intentionally left configurable for this task.  A
    small lexical signal is still required before a course source is treated as
    evidence; otherwise hash/semantic similarity can surface an unrelated
    document for an out-of-scope question.
    """
    overlap = _terms(query) & _terms(content)
    return len(overlap - _QUERY_STOP_TERMS)


def teaching_sections(text: str, headings: list[str]) -> str:
    """Read curated concept sections in source order, excluding code headings.

    These selectors describe where a concept is taught; they never provide
    replacement text or generated evidence. A missing selector yields no text.
    """
    def normalized(value):
        return re.sub(r'[\s*`\[\]]+', '', value).strip('#')

    targets = {normalized(value) for value in headings}
    records, offset, fence = [], 0, None
    for line in text.splitlines(keepends=True):
        marker = re.match(r'^\s*(`{3,}|~{3,})', line)
        if marker:
            value = marker[1]
            if fence is None:
                fence = value
            elif value[0] == fence[0] and len(value) >= len(fence):
                fence = None
        elif fence is None:
            heading = re.match(r'^\s{0,3}(#{1,6})\s+(.+)', line)
            if heading:
                records.append((offset, len(heading[1]), normalized(heading[2])))
        offset += len(line)
    spans = []
    for index, (start, level, title) in enumerate(records):
        if title not in targets:
            continue
        end = next((pos for pos, depth, _ in records[index + 1:] if depth <= level), len(text))
        if spans and start < spans[-1][1]:
            continue
        spans.append((start, end))
    return '\n\n'.join(text[start:end].strip() for start, end in spans)


def teaching_excerpt(text: str, *, topics: list[str], max_chars: int, prefer_explanations: bool = False) -> str:
    """Keep topic-bearing passages from the whole verified text, including its end."""
    if not prefer_explanations and (len(text) <= max_chars or not topics):
        return text[:max_chars]
    chunks = (_cached_chunks(text, "verified-teaching-text") if prefer_explanations
              else chunk_document(text, source="verified-teaching-text"))
    if prefer_explanations:
        # A question in an unsolved exercise is not an answer source, even
        # when it repeats the concept's name more often than the explanation.
        chunks, _ = _answer_passages(chunks, "")
        chunks = [chunk for chunk in chunks if not (
            re.search(r"(?m)^\s*(?:习题|练习题)\s*\d+\s*[-.－—]\s*\d+", chunk.content)
            and not re.search(r"(?m)^\s*(?:解答|参考答案|解[:：]|证明[:：])", chunk.content)
        )]
    if not chunks:
        return "" if prefer_explanations else text[:max_chars]
    ranked = []
    for topic in topics or [""]:
        query = expand_ml_query(topic).expanded_query
        terms = _terms(query) - _QUERY_STOP_TERMS
        phrases = [part.strip().lower() for part in re.split(r"[、，,与]", topic) if len(part.strip()) > 2]
        ranked.append(sorted(chunks, key=lambda chunk: (
            sum(phrase in chunk.content.lower() for phrase in phrases) if prefer_explanations else 0,
            _lexical_overlap(topic, " ".join(chunk.metadata.get('title_path') or [])) if prefer_explanations else 0,
            _lexical_overlap(query, chunk.content),
            sum(min(3, chunk.content.lower().count(term)) for term in terms),
            len(chunk.content),
        ), reverse=True))
    if prefer_explanations and len(ranked) == 1:
        # A compact authored section can explain a whole operation (read CSV,
        # handle missing values, convert data). Keep it together rather than
        # selecting scattered paragraphs that merely repeat the topic title.
        first_path = ranked[0][0].metadata.get('title_path') or []
        if len(first_path) > 1:
            section = [chunk for chunk in chunks if (chunk.metadata.get('title_path') or [''])[0] == first_path[0]]
            section_text = "\n\n".join(dict.fromkeys(chunk.content for chunk in section))
            if len(section_text) <= max_chars:
                return section_text
    selected, seen, used = [], set(), 0
    # Give every attached knowledge point a passage before taking more context.
    for index in range(max(len(items) for items in ranked)):
        for items in ranked:
            if index >= len(items):
                continue
            chunk = items[index]
            if chunk.content in seen:
                continue
            remaining = max_chars - used - (2 if selected else 0)
            if remaining <= 0:
                return "\n\n".join(selected)
            selected.append(chunk.content[:remaining])
            seen.add(chunk.content)
            used += len(selected[-1]) + (2 if len(selected) > 1 else 0)
    return "\n\n".join(selected)


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


def canonical_sources_available(session: Any, *, course_id: str | None = None,
                                actor: Any | None = None) -> bool:
    """Check readable current sources without requiring a legacy FAISS index.

    This is readiness, not a claim of successful retrieval for a particular
    question or of executed semantic ranking. The same source projection used
    by retrieval still checks hashes, locations and optional actor access.
    """
    query = (session.query(DBSourceRef, DBSourceDocument)
        .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
        .filter(DBSourceDocument.processing_status == 'ready', current_source_clause(),
                current_structure_ref_clause()))
    if course_id is not None:
        query = query.filter(DBSourceDocument.course_id == course_id)
    bodies = {}
    for ref, source in query.yield_per(50):
        if source.id not in bodies:
            bodies[source.id] = bool(_document_body(session, source).strip())
        if bodies[source.id] and project_source_ref(session, ref.id, actor=actor,
                expected_course_id=course_id, permission_as_unavailable=True).get('available'):
            return True
    return False


def _source_ref_for_chunk(refs: list[DBSourceRef], chunk: Evidence, *, offset: int | None = None) -> DBSourceRef | None:
    if not refs:
        return None
    if offset is not None:
        containing = [ref for ref in refs if ref.char_start is not None and ref.char_end is not None
                      and ref.char_start <= offset < ref.char_end]
        if containing:
            return min(containing, key=lambda ref: ref.char_end - ref.char_start)
    content = str(chunk.content or "")
    for ref in refs:
        quote = str(ref.quote or "").strip()
        if quote and (quote[:120] in content or content[:120] in quote):
            return ref
    return sorted(refs, key=lambda item: (item.location_index or 0, item.id))[0]


@lru_cache(maxsize=64)
def _cached_chunks(body: str, source_name: str) -> tuple[Evidence, ...]:
    if source_name.lower().endswith('.py'):
        return chunk_document(body, source=source_name)
    headings, stack, offset, fenced = [], [], 0, False
    exercise_level = None
    for line in body.splitlines(keepends=True):
        if re.match(r'^\s*(```|~~~)', line):
            fenced = not fenced
        heading = re.match(r'^(#{1,6})\s+(.+)', line) if not fenced else None
        if heading:
            level, title = len(heading[1]), heading[2].strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            if exercise_level is not None and level <= exercise_level:
                exercise_level = None
            if re.search(r'练习|习题|思考题|问题与讨论|实训检查', title):
                exercise_level = level
            headings.append((offset, [text for _, text in stack], 'exercise_prompt' if exercise_level else 'text'))
        offset += len(line)
    sections = [(0, [], 'text')] if not headings or headings[0][0] else []
    sections.extend(headings)
    document_title = headings[0][1][0] if headings else ''
    objectives = []
    for index, (start, titles, _) in enumerate(sections):
        if titles and re.fullmatch(r'本章(?:学习)?目标|学习目标|课程目标', titles[-1]):
            end = sections[index+1][0] if index+1 < len(sections) else len(body)
            objectives.append(re.sub(r'^#{1,6}\s+.*$', '', body[start:end], flags=re.M).strip())
    document_context = '\n'.join([document_title, *objectives]).strip()
    chunks = []
    for index, (start, titles, kind) in enumerate(sections):
        end = sections[index+1][0] if index+1 < len(sections) else len(body)
        section = body[start:end]
        if kind == 'text':
            prose = re.sub(r'^#{1,6}\s+.*$', '', section, flags=re.M).strip()
            if not prose:
                kind = 'heading_only'
            elif any(re.fullmatch(r'本章(?:学习)?目标|学习目标|课程目标|章节|(?:(?:章节|课程|内容|本书)\s*)?目录|table of contents|contents', title, re.I) for title in titles):
                kind = 'course_outline'
            elif titles and re.fullmatch(r'怎么选|如何阅读本书|阅读路径建议|本书结构|适合读者|先从哪里开始', titles[-1]):
                kind = 'source_note'
            elif re.search(r'下载\s*(?:PDF|电子书)|章节目录|系列主站|统一入口.{0,30}电子稿', prose, re.I) and re.search(r'<a\s|\]\(https?://', prose):
                kind = 'source_note'
            elif (lines := [line.strip() for line in prose.splitlines() if line.strip()]) and all(
                re.match(r'^(?:[-*+]\s*)?第\s*[\d一二三四五六七八九十]+\s*[章节部]', line)
                for line in lines
            ):
                kind = 'course_outline'
            elif all(line.lstrip().startswith('>') for line in prose.splitlines() if line.strip()):
                kind = 'source_note' if re.search(r'上游来源|许可证|固定版本|转换说明', prose) else kind
        for chunk in chunk_document(section, source=f'section-{start}/{source_name}'):
            chunks.append(replace(chunk, metadata={**chunk.metadata,
                'char_start': start + int(chunk.metadata.get('char_start', 0)),
                'char_end': start + int(chunk.metadata.get('char_end', end-start)),
                'title_path': titles, 'evidence_kind': kind, 'document_context': document_context,
                'document_source': source_name}))
    return tuple(chunks)


def _answer_passages(chunks: list[Evidence], query: str) -> tuple[list[Evidence], dict[str, int]]:
    """Goals and exercise prompts locate a course, but do not explain its topic."""
    exercise_requested = bool(re.search(r'练习|习题|思考题|第.{0,5}题|题目|解题|实训|检查|验收|作业', query))
    outline_requested = bool(re.search(r'目录|大纲|学习目标|课程目标|章节安排|课程.*(?:概览|概括|主要内容)|(?:概览|概括|总结).*(?:全课|课程)', query))
    source_requested = bool(re.search(r'来源|版权|许可|作者|版本|转换', query))
    excluded = set()
    if not exercise_requested:
        excluded.add('exercise_prompt')
    if not outline_requested:
        excluded.update({'heading_only', 'course_outline'})
    if not source_requested:
        excluded.add('source_note')
    counts = {kind: sum(chunk.metadata.get('evidence_kind') == kind for chunk in chunks) for kind in excluded}
    return [chunk for chunk in chunks if chunk.metadata.get('evidence_kind') not in excluded], counts


def _source_chunks(body: str, source_name: str, refs: list[DBSourceRef], *, scoped: bool) -> tuple[Evidence, ...]:
    """An explicit chapter/page selection constrains both child and parent text."""
    if not scoped:
        return _cached_chunks(body, source_name)
    ranges = sorted((max(0, int(ref.char_start or 0)),
                     min(len(body), int(ref.char_end if ref.char_end is not None else len(body))))
                    for ref in refs)
    merged = []
    for start, end in ranges:
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    chunks = []
    for start, end in merged:
        for chunk in _cached_chunks(body[start:end], f'scope-{start}/{source_name}'):
            metadata = {**chunk.metadata,
                        'char_start': start + int(chunk.metadata.get('char_start', 0)),
                        'char_end': start + int(chunk.metadata.get('char_end', end-start))}
            chunks.append(replace(chunk, metadata=metadata))
    return tuple(chunks)


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
    if not source_ref_ids:
        query = query.filter(current_source_clause(), current_structure_ref_clause())
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


def prepare_canonical_embeddings(session: Any, *, source_document_ids: list[str] | None = None) -> dict[str, Any]:
    """Warm the existing vector cache at startup/import, before a learner's query."""
    if not EMBEDDINGS.semantic_capable:
        return {'prepared_chunks': 0, 'semantic': False}
    EMBEDDINGS.prepare()
    sources = session.query(DBSourceDocument).filter(DBSourceDocument.processing_status == 'ready', current_source_clause())
    if source_document_ids is not None:
        sources = sources.filter(DBSourceDocument.id.in_(source_document_ids))
    count = 0
    for source in sources:
        body = _document_body(session, source)
        if not body.strip():
            continue
        name = f'{source.course_id}/{source.id}/{source.processed_sha256}/{source.filename}'
        chunks = _cached_chunks(body, name)
        EMBEDDINGS.embed_many([indexing_text(chunk) for chunk in chunks])
        count += len(chunks)
    return {'prepared_chunks': count, 'semantic': True, 'embedding': EMBEDDINGS.identity()}


def retrieve_canonical_sources(
    session: Any,
    *,
    course_id: str,
    query: str,
    top_k: int = 5,
    actor: Any | None = None,
    source_ref_ids: list[str] | None = None,
    chapter_ids: list[str] | None = None,
    assemble_for_task: bool = False,
    retrieval_mode: str = "hybrid",
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
    if not source_ref_ids:
        refs_query = refs_query.filter(current_source_clause(), current_structure_ref_clause())
    refs = refs_query.order_by(DBSourceRef.location_index, DBSourceRef.id).all()

    refs_by_source: dict[str, list[DBSourceRef]] = {}
    for ref in refs:
        refs_by_source.setdefault(ref.source_document_id, []).append(ref)

    candidates, origins = [], {}
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
        chunks = _source_chunks(body, f"{course_id}/{source.id}/{source.processed_sha256}/{source.filename}", source_refs,
                                scoped=bool(chapter_ids or source_ref_ids))
        for chunk in chunks:
            candidates.append(chunk)
            origins[chunk.id] = (source, source_refs, body)

    if not candidates:
        return {'course_id': course_id, 'query': normalized_query, 'items': [], 'evidence': (),
                'low_confidence': True, 'reason': 'no_ready_canonical_source'}
    answer_candidates, excluded_kinds = _answer_passages(candidates, normalized_query)
    if answer_candidates:
        candidates = answer_candidates
    if retrieval_mode == "hipporag2":
        from app.associative_retrieval import rank_associative_chunks
        order, rankings, execution = rank_associative_chunks(
            candidates, query=normalized_query, embeddings=EMBEDDINGS, course_id=course_id)
    elif retrieval_mode == "hybrid":
        order, rankings, execution = rank_chunks(candidates, query=normalized_query,
                                                 expanded_query=retrieval_query, embeddings=EMBEDDINGS)
    else:
        raise ValueError(f"Unknown retrieval mode: {retrieval_mode}")
    execution['unanswered_exercise_chunks_excluded'] = excluded_kinds.get('exercise_prompt', 0)
    execution['non_answer_chunks_excluded'] = excluded_kinds
    if assemble_for_task and retrieval_mode == "hybrid":
        from app.task_evidence import assemble_task_evidence
        current_chapters = {ref.chapter_id for ref in refs if ref.chapter_id}
        titles = [row[0] for row in session.query(DBKnowledgePoint.title).join(
            DBChapterKnowledgePoint, DBChapterKnowledgePoint.knowledge_point_id == DBKnowledgePoint.id,
        ).filter(DBChapterKnowledgePoint.chapter_id.in_(current_chapters)).distinct().all()]
        order, rankings, assembly = assemble_task_evidence(candidates, order, rankings,
            query=normalized_query, embeddings=EMBEDDINGS, concept_titles=titles, top_k=top_k)
        execution['task_evidence'] = assembly
    by_id = {chunk.id: chunk for chunk in candidates}
    items: list[dict[str, Any]] = []
    for chunk_id in order:
        best_chunk = by_id[chunk_id]
        source, source_refs, body = origins[chunk_id]
        ranking = rankings[chunk_id]
        terms = _terms(retrieval_query) - _QUERY_STOP_TERMS
        overlap = _lexical_overlap(retrieval_query, best_chunk.content)
        lexical_coverage = overlap / max(1, len(terms))
        semantic_score = ranking.get('semantic_score')
        # Compatibility relevance score is separate from the RRF ordering score.
        # Neither is a probability that the passage supports an answer.
        score = min(1.0, lexical_coverage * .7 + ((float(semantic_score)+1)/2*.3 if semantic_score is not None else 0.0))
        chunk_start = best_chunk.metadata.get("char_start")
        if chunk_start is None:
            chunk_start = body.find(best_chunk.content)
        match_start = None
        match_text = ""
        # A short document can occupy one chunk but still contain several pages.
        # Locate the actual query within that chunk before choosing its reference.
        for term in [normalized_query, *expansion.added_terms, *sorted(_terms(normalized_query) - _QUERY_STOP_TERMS, key=lambda term: (-len(term), term))]:
            match = re.search(re.escape(term), best_chunk.content, flags=re.IGNORECASE)
            if match and chunk_start >= 0:
                match_start = int(chunk_start) + match.start()
                match_text = match.group()
                break
        source_ref = _source_ref_for_chunk(source_refs, best_chunk, offset=match_start if match_start is not None else chunk_start if chunk_start >= 0 else None)
        if match_start is None and chunk_start >= 0:
            match_start = chunk_start
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
            "char_start": chunk_start,
            "char_end": best_chunk.metadata.get('char_end', chunk_start + len(best_chunk.content)),
            "source_ref_char_start": ref_projection.get("char_start"),
            "source_ref_char_end": ref_projection.get("char_end"),
            "quote": ref_projection.get("quote", ""),
            "source_route": ref_projection.get("route", ""),
            "query_term_overlap": _lexical_overlap(normalized_query, best_chunk.content),
            "source_max_query_term_overlap": overlap,
            "query_expansion_applied": expansion.applied,
            "query_expansion_terms": list(expansion.added_terms),
            "match_char_start": match_start,
            "match_text": match_text,
            "retrieval_ranking": ranking,
            "retrieval_execution": execution,
            "lexical_coverage": lexical_coverage,
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
            "ranking": ranking,
            'relevant': (lexical_coverage >= .30
                         or english_lexical_score(expansion, best_chunk.content) >= .4
                         or bool(ranking.get('task_topic_matches'))
                         or bool(ranking.get('task_facet_matches'))
                         or float(semantic_score or 0) >= .60),
        })
        if len(items) >= top_k:
            break
    selected = items[:top_k]
    # Relevance is assessed on actual passages, independently of RRF rank.
    # A weaker first item cannot erase relevant evidence elsewhere in the set.
    # Multiple passages may jointly cover a question. Three common bigrams in
    # a long, otherwise unrelated query are not sufficient evidence on their
    # own (for example, '基础/训练' does not cover GPU-cluster topology).
    query_terms = _terms(retrieval_query) - _QUERY_STOP_TERMS
    covered_terms = set().union(*(_terms(item['evidence'].content) & query_terms for item in selected))
    combined_coverage = len(covered_terms) / max(1, len(query_terms))
    # A union of weak fragments must not invent support for an absent named
    # product/API. In mixed-language questions these literal identifiers carry
    # the subject; generic words such as "average" or "real" cannot replace it.
    identifiers = set(re.findall(r'[a-z][a-z0-9_+.-]{2,}', normalized_query.lower())) if re.search(r'[\u4e00-\u9fff]', normalized_query) else set()
    if re.search(r'许可|版权|准入|上传格式|文件格式', normalized_query):
        # A general source-admission question applies to material from any
        # named host; it does not ask for that host's product-specific facts.
        origin_labels = re.findall(r'([a-z][a-z0-9_+.-]{2,})\s*(?:材料|资料|文档|课件|教材|网页|仓库)',
                                   normalized_query.lower())
        identifiers.difference_update(origin_labels)
    # A comparison may be answered by different passages in one textbook.
    # Judge their shared source before a file-search caller filters each item;
    # otherwise a usable evidence set becomes an empty document result.
    source_groups: dict[str, list[dict[str, Any]]] = {}
    for item in selected:
        source_groups.setdefault(item['source'].id, []).append(item)
    for group in source_groups.values():
        body_terms = set().union(*(_terms(item['evidence'].content) for item in group))
        group_coverage = len(body_terms & query_terms) / max(1, len(query_terms))
        if group_coverage >= .30 and not (identifiers - body_terms):
            for item in group:
                if _terms(item['evidence'].content) & query_terms:
                    item['relevant'] = True
    context_text = '\n'.join(indexing_text(item['evidence']) for item in selected)
    # Attribute names and file stems can occur as model.attribute or LICENSE.md.
    # Match their literal boundaries rather than requiring identical tokenizer
    # tokens; a different longer identifier still cannot stand in for them.
    def missing_names(text):
        return sorted(name for name in identifiers if not re.search(
            r'(?<![a-z0-9_])' + re.escape(name) + r'(?![a-z0-9_])', text, re.I))
    passage_missing_identifiers = missing_names(context_text)
    # A dataset/API name may be introduced earlier in the same chosen source.
    # Resolve it within the already permitted candidate scope, never another
    # document/course or outside an explicit selection. This is still only a
    # retrieval hint, not proof of every requested fact about that name.
    selected_source_ids = {item['source'].id for item in selected}
    scope_text = '\n'.join(indexing_text(chunk) for chunk in candidates
                           if origins[chunk.id][0].id in selected_source_ids)
    missing_identifiers = missing_names(scope_text) if passage_missing_identifiers else []
    low_confidence = bool(missing_identifiers) or not answer_candidates or not (
        any(item['relevant'] for item in selected) or (combined_coverage >= .30 and not missing_identifiers)
    )
    execution['selected_lexical_coverage'] = combined_coverage
    execution['unmatched_query_identifiers'] = missing_identifiers
    execution['unmatched_passage_identifiers'] = passage_missing_identifiers
    return {
        "course_id": course_id,
        "query": normalized_query,
        "retrieval_query": retrieval_query,
        "items": selected,
        "evidence": tuple(item["evidence"] for item in selected),
        "low_confidence": low_confidence,
        "retrieval": execution,
        "reason": (
            "no_ready_canonical_source"
            if not selected
            else "no_body_term_match"
            if low_confidence
            else ""
        ),
    }
