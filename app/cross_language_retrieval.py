"""Deterministic, auditable query expansion for Chinese-to-English course retrieval."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping


GLOSSARY_VERSION = "ml-zh-en-glossary-1.0.0"


@dataclass(frozen=True)
class GlossaryEntry:
    concept: str
    triggers: tuple[str, ...]
    english_terms: tuple[str, ...]


@dataclass(frozen=True)
class QueryExpansion:
    original_query: str
    expanded_query: str
    strategy: str
    glossary_version: str
    matched_concepts: tuple[str, ...]
    added_terms: tuple[str, ...]

    @property
    def applied(self) -> bool:
        return bool(self.added_terms)


# Entries describe stable public machine-learning vocabulary. They deliberately
# contain no evaluation case IDs, document names, chapter titles or ranking data.
ML_ZH_EN_GLOSSARY: tuple[GlossaryEntry, ...] = (
    GlossaryEntry("python_dictionary", ("字典", "键值对", "通过键"), ("Python dictionary", "key value pair", "access value by key", "add dictionary item")),
    GlossaryEntry("array_shape", ("数组", "形状", "元素总数"), ("NumPy array", "reshape", "shape", "number of elements", "array size")),
    GlossaryEntry("table_selection", ("行列标签", "整数位置", "表格数据", "按标签"), ("pandas DataFrame", "loc label selection", "iloc integer position selection", "rows columns")),
    GlossaryEntry("correlation", ("相关系数", "相关矩阵", "相关性", "变量关系"), ("correlation coefficient", "correlation matrix", "variable relationship")),
    GlossaryEntry("heatmap", ("热力图", "热图", "可视化"), ("heatmap", "seaborn heatmap", "visualize correlation matrix")),
    GlossaryEntry("missing_values", ("缺失值", "缺失数据"), ("missing values", "missing data", "imputation", "fill missing values")),
    GlossaryEntry("categorical_encoding", ("类别变量", "类别字符串", "分类变量", "编码"), ("categorical variable", "categorical string", "encoding", "one hot encoding", "label encoding")),
    GlossaryEntry("feature_scaling", ("数值尺度", "缩放", "标准化"), ("feature scaling", "standardization", "normalization", "scale numerical features")),
    GlossaryEntry("data_preprocessing", ("训练前", "数据准备", "预处理"), ("data preprocessing", "data preparation", "prepare data before model training")),
    GlossaryEntry("supervised_learning", ("有标签学习", "监督学习"), ("supervised learning", "labeled data", "target labels")),
    GlossaryEntry("unsupervised_learning", ("无标签学习", "无监督学习"), ("unsupervised learning", "unlabeled data", "no target labels")),
    GlossaryEntry("decision_tree", ("决策树",), ("decision tree", "scikit learn decision tree")),
    GlossaryEntry("principal_components", ("主成分", "降维"), ("principal component", "PCA", "dimensionality reduction")),
    GlossaryEntry("explained_variance", ("解释方差", "方差占比"), ("explained variance ratio", "cumulative explained variance", "choose number of components")),
)
_GLOSSARY_BY_CONCEPT = {entry.concept: entry for entry in ML_ZH_EN_GLOSSARY}


def contains_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def expand_ml_query(query: str) -> QueryExpansion:
    original = " ".join(str(query or "").split())
    if not original or not contains_chinese(original):
        return QueryExpansion(original, original, "none", GLOSSARY_VERSION, (), ())

    matched: list[str] = []
    terms: list[str] = []
    normalized = original.lower()
    for entry in ML_ZH_EN_GLOSSARY:
        if any(trigger.lower() in normalized for trigger in entry.triggers):
            matched.append(entry.concept)
            for term in entry.english_terms:
                if term.lower() not in {item.lower() for item in terms}:
                    terms.append(term)

    expanded = original if not terms else f"{original} {' '.join(terms)}"
    return QueryExpansion(
        original_query=original,
        expanded_query=expanded,
        strategy="glossary-v1" if terms else "none",
        glossary_version=GLOSSARY_VERSION,
        matched_concepts=tuple(matched),
        added_terms=tuple(terms),
    )


_ENGLISH_STOPWORDS = frozenset(
    {
        "a", "an", "and", "as", "at", "before", "by", "for", "from", "how",
        "in", "into", "is", "it", "no", "of", "on", "or", "the", "to", "use",
        "value", "values", "with",
    }
)


def english_lexical_score(expansion: QueryExpansion, document: str) -> float:
    """Score only expansion terms against document body; never use metadata."""
    if not expansion.applied or not document:
        return 0.0
    lower_document = document.lower()
    document_tokens = set(re.findall(r"[a-z][a-z0-9_+-]*", lower_document))
    concept_scores: list[float] = []
    for concept in expansion.matched_concepts:
        entry = _GLOSSARY_BY_CONCEPT[concept]
        alternative_scores: list[float] = []
        for term in entry.english_terms:
            lower_term = term.lower()
            tokens = {
                token
                for token in re.findall(r"[a-z][a-z0-9_+-]*", lower_term)
                if len(token) > 1 and token not in _ENGLISH_STOPWORDS
            }
            token_coverage = len(tokens & document_tokens) / len(tokens) if tokens else 0.0
            phrase_bonus = 0.25 if len(lower_term.split()) >= 2 and lower_term in lower_document else 0.0
            alternative_scores.append(min(1.0, token_coverage * 0.75 + phrase_bonus))
        concept_scores.append(max(alternative_scores, default=0.0))
    return sum(concept_scores) / len(concept_scores) if concept_scores else 0.0


def reciprocal_rank_fusion(
    semantic_scores: dict[str, float],
    lexical_scores: dict[str, float],
    *,
    rank_constant: int = 20,
    semantic_weight: float = 1.0,
    lexical_weight: float = 2.0,
) -> tuple[list[str], dict[str, dict[str, float | int]]]:
    """Fuse independent rankings without requiring comparable score scales."""
    if set(semantic_scores) != set(lexical_scores):
        raise ValueError("cross_language_fusion_document_sets_must_match")
    semantic_order = sorted(semantic_scores, key=lambda key: (-semantic_scores[key], key))
    lexical_order = sorted(lexical_scores, key=lambda key: (-lexical_scores[key], key))
    semantic_rank = {key: rank for rank, key in enumerate(semantic_order, 1)}
    lexical_rank = {key: rank for rank, key in enumerate(lexical_order, 1)}
    diagnostics: dict[str, dict[str, float | int]] = {}
    for key in semantic_scores:
        fused = semantic_weight / (rank_constant + semantic_rank[key]) + lexical_weight / (rank_constant + lexical_rank[key])
        diagnostics[key] = {
            "semantic_rank": semantic_rank[key],
            "lexical_rank": lexical_rank[key],
            "semantic_score": semantic_scores[key],
            "lexical_score": lexical_scores[key],
            "fused_score": fused,
        }
    ranking = sorted(
        diagnostics,
        key=lambda key: (
            -float(diagnostics[key]["fused_score"]),
            int(diagnostics[key]["semantic_rank"]),
            key,
        ),
    )
    return ranking, diagnostics


def tfidf_document_scores(expansion: QueryExpansion, documents: Mapping[str, str]) -> dict[str, float]:
    """Compute offline corpus-aware lexical scores from document bodies only."""
    if not documents:
        return {}
    keys = list(documents)
    if not expansion.applied:
        return {key: 0.0 for key in keys}
    from sklearn.feature_extraction.text import TfidfVectorizer

    vectorizer = TfidfVectorizer(
        lowercase=True,
        stop_words="english",
        ngram_range=(1, 2),
        sublinear_tf=True,
        max_df=1.0,
    )
    try:
        matrix = vectorizer.fit_transform([documents[key] for key in keys])
    except ValueError as exc:
        message = str(exc).lower()
        if "empty vocabulary" not in message and "no terms remain" not in message:
            raise
        return {key: 0.0 for key in keys}
    query_vector = vectorizer.transform([expansion.expanded_query])
    similarities = (matrix @ query_vector.T).toarray().ravel()
    return {key: float(score) for key, score in zip(keys, similarities)}
