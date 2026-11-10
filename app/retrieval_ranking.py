"""Independent BM25 and configured semantic ranking for canonical source chunks."""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
import math
import re
import time

from app.cross_language_retrieval import reciprocal_rank_fusion
from cache_utils import TTLBoundedCache

RANKING_VERSION = 'canonical-bm25-semantic-rrf-v8'
CANDIDATES_PER_ROUTE = 20
RRF_CONSTANT = 60
_matrices = TTLBoundedCache(maxsize=8, ttl_seconds=900)
_QUERY_FILLER = frozenset({'如何', '什么', '怎样', '哪些', '多少', '根据', '请给', '给出',
                          '一个', '这个', '当前', '其中', '以及', '是否', '能够', '应该',
                          '不是', '是只', '而不', '只看', '回答',
                          'the', 'and', 'or', 'of', 'to', 'from', 'for', 'in', 'on', 'at', 'by', 'with', 'as',
                          'is', 'are', 'was', 'were', 'be', 'been', 'being', 'it', 'its', 'this', 'that', 'these', 'those',
                          'how', 'why', 'what', 'which', 'when', 'where', 'who', 'should', 'would', 'could', 'can', 'may',
                          'will', 'shall', 'do', 'does', 'did', 'have', 'has', 'had', 'into', 'about', 'you', 'your', 'we', 'our', 'they', 'their'})
@lru_cache(maxsize=16)
def _han_filler_pattern(stop_terms):
    return re.compile('|'.join(re.escape(word) for word in sorted(
        (word for word in _QUERY_FILLER | stop_terms
         if len(word) > 1 and re.fullmatch(r'[\u4e00-\u9fff]+', word)),
        key=lambda word: (-len(word), word))))


def retrieval_tokens(text, *, stop_terms=frozenset()):
    normalized = str(text or '').lower()
    tokens = re.findall(r'[a-z0-9_+.-]{2,}', normalized)
    # Keep the qualified spelling, and also index its attribute/file parts:
    # asking for explained_variance_ratio_ must find pca.explained_variance_ratio_.
    tokens.extend(part for token in list(tokens) if '.' in token
                  for part in token.split('.') if len(part) >= 2)
    # Remove question scaffolding before making bigrams. Removing only the
    # finished token leaves spurious neighbours such as 类如 / 何通 in 聚类如何通过.
    # Replace with a boundary so the words on either side never join together.
    for run in re.findall(r'[\u4e00-\u9fff]+', _han_filler_pattern(frozenset(stop_terms)).sub(' ', normalized)):
        tokens.extend(run[i:i+2] for i in range(len(run)-1))
    return [token for token in tokens if token not in _QUERY_FILLER and token not in stop_terms]


class BM25Index:
    def __init__(self, documents):
        self.counts = [Counter(retrieval_tokens(text)) for text in documents]
        self.lengths = [sum(count.values()) for count in self.counts]
        self.average = sum(self.lengths) / max(1, len(self.lengths))
        frequencies = Counter(term for count in self.counts for term in count)
        self.idf = {term: math.log(1 + (len(documents)-count+.5)/(count+.5))
                    for term, count in frequencies.items()}

    def scores(self, query):
        terms = set(retrieval_tokens(query))
        values = []
        for counts, length in zip(self.counts, self.lengths):
            normalizer = 1.2 * (.25 + .75 * length / max(1, self.average))
            values.append(sum(self.idf.get(term, 0) * counts[term] * 2.2 / (counts[term] + normalizer)
                              for term in terms if counts[term]))
        return values


@lru_cache(maxsize=16)
def _lexical_index(documents):
    return BM25Index(documents)


def indexing_text(chunk):
    """Headings supply context to ranking, but are not appended to quoted evidence."""
    titles = ' > '.join(str(title) for title in chunk.metadata.get('title_path', []))
    context = str(chunk.metadata.get('document_context') or '')
    return '\n'.join(dict.fromkeys(part for part in [context, titles, chunk.content] if part))


def _diversify_related_topics(order, diagnostics, chunks, query):
    """Keep complementary passages for explicit comparisons/relationships.

    Ordinary lookup retains the original order. MMR uses relative ranking and
    passage overlap, without treating either value as factual confidence.
    """
    requested = bool(re.search(r'比较|对比|区别|异同|关联|结合|串联|跨章节|compare|contrast|relationship', query, re.I))
    if not requested or len(order) < 3:
        return order, False
    by_id = {chunk.id: chunk for chunk in chunks}
    counts = {key: Counter(retrieval_tokens(indexing_text(by_id[key]))) for key in order}
    norms = {key: math.sqrt(sum(value * value for value in count.values())) for key, count in counts.items()}
    relevance = {key: diagnostics[key].get('fused_score') or diagnostics[key].get('lexical_score') or 0 for key in order}
    maximum = max(relevance.values(), default=0)
    if maximum <= 0:
        return order, False

    def similarity(left, right):
        return sum(value * counts[right][term] for term, value in counts[left].items()) / max(1e-12, norms[left] * norms[right])

    pending, selected = list(order), []
    while pending:
        candidate = max(pending, key=lambda key: 0.5 * relevance[key] / maximum - 0.5 * max(
            (similarity(key, previous) for previous in selected), default=0))
        pending.remove(candidate)
        selected.append(candidate)
    return selected, True


def rank_chunks(chunks, *, query, expanded_query, embeddings):
    """RRF scores order candidates; they are never used as confidence probabilities."""
    started = time.monotonic()
    ids = [chunk.id for chunk in chunks]
    documents = tuple(indexing_text(chunk) for chunk in chunks)
    bm25 = _lexical_index(documents).scores(expanded_query)
    lexical = dict(sorted(((key, score) for key, score in zip(ids, bm25) if score > 0),
                          key=lambda pair: (-pair[1], pair[0]))[:CANDIDATES_PER_ROUTE])
    identity = embeddings.identity()
    semantic, all_semantic = {}, {}
    error = None
    if embeddings.semantic_capable:
        try:
            import numpy as np
            matrix_key = (documents, tuple(sorted(identity.items())))
            matrix = _matrices.get(matrix_key)
            if matrix is None:
                matrix = np.asarray(embeddings.embed_many(list(documents)), dtype=np.float32)
                if matrix.ndim != 2 or not np.isfinite(matrix).all():
                    raise ValueError('embedding_vectors_invalid')
                norms = np.linalg.norm(matrix, axis=1, keepdims=True)
                matrix = matrix / np.maximum(norms, 1e-12)
                _matrices[matrix_key] = matrix
            vector = np.asarray(embeddings.embed(query), dtype=np.float32)
            if vector.ndim != 1 or matrix.shape[1] != vector.shape[0] or not np.isfinite(vector).all():
                raise ValueError('embedding_query_invalid')
            raw_scores = matrix @ (vector / max(float(np.linalg.norm(vector)), 1e-12))
            all_semantic = {key: float(score) for key, score in zip(ids, raw_scores)}
            semantic = dict(sorted(all_semantic.items(), key=lambda pair: (-pair[1], pair[0]))[:CANDIDATES_PER_ROUTE])
        except Exception as exc:
            # A missing model must be observable, without losing lexical search.
            error = type(exc).__name__
    if semantic:
        order, diagnostics = reciprocal_rank_fusion(semantic, lexical, rank_constant=RRF_CONSTANT,
                                                    semantic_weight=1.0, lexical_weight=1.0)
    else:
        order = list(lexical)
        diagnostics = {key: {'semantic_rank': None, 'semantic_score': None, 'lexical_rank': rank,
                             'lexical_score': score, 'fused_score': None}
                       for rank, (key, score) in enumerate(lexical.items(), 1)}
    # Retain locatable low-confidence context for existing callers' missing-evidence flow.
    if not order:
        order = sorted(ids)[:CANDIDATES_PER_ROUTE]
        diagnostics = {key: {'semantic_rank': None, 'semantic_score': None, 'lexical_rank': None,
                             'lexical_score': 0.0, 'fused_score': None} for key in order}
    order, diversified = _diversify_related_topics(order, diagnostics, chunks, query)
    return order, diagnostics, {
        'version': RANKING_VERSION, 'method': 'reciprocal-rank-fusion' if semantic else 'bm25',
        'embedding': identity, 'semantic_executed': bool(semantic), 'semantic_error': error,
        'lexical_method': 'bm25', 'lexical_candidates': len(lexical), 'semantic_candidates': len(semantic),
        'candidate_limit_per_route': CANDIDATES_PER_ROUTE,
        'rank_constant': RRF_CONSTANT if semantic else None, 'reranker_executed': False,
        'chunk_count': len(chunks), 'ranking_seconds': round(time.monotonic()-started, 4),
        'diversification_applied': diversified,
        'selection_method': 'maximal-marginal-relevance' if diversified else 'rank-order',
    }
