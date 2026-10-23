from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.evaluate_cross_language_body_retrieval import (
    DEFAULT_COURSE_DIR,
    DEFAULT_DATASET,
    _body_chunks,
    _load_dataset,
    evaluate,
)
from app.cross_language_retrieval import (
    GLOSSARY_VERSION,
    english_lexical_score,
    expand_ml_query,
    reciprocal_rank_fusion,
    tfidf_document_scores,
)


def test_cross_language_dataset_excludes_course_metadata_and_covers_unique_documents():
    dataset = _load_dataset(DEFAULT_DATASET)
    chunks = _body_chunks(DEFAULT_COURSE_DIR, dataset)

    assert len(dataset["cases"]) == 8
    assert len({item["id"] for item in dataset["cases"]}) == 8
    assert len({item["relevant_document"] for item in dataset["cases"]}) == 8
    assert chunks
    assert all("课程：机器学习基础与实践" not in text for _, text in chunks)
    assert all("本章目标" not in text for _, text in chunks)


def test_hash_cross_language_report_is_reproducible_and_does_not_claim_pass():
    first = evaluate(
        dataset_path=DEFAULT_DATASET,
        course_dir=DEFAULT_COURSE_DIR,
        backend="hash",
        model_path=None,
        e5_prefixes=False,
    )
    second = evaluate(
        dataset_path=DEFAULT_DATASET,
        course_dir=DEFAULT_COURSE_DIR,
        backend="hash",
        model_path=None,
        e5_prefixes=False,
    )

    assert first == second
    assert first["metadata_excluded"] is True
    assert first["passed"] is False
    assert first["passed_at_rank_threshold"] < first["case_count"]


def test_cross_language_dataset_rejects_unknown_relevant_document(tmp_path: Path):
    dataset = _load_dataset(DEFAULT_DATASET)
    dataset["cases"][0]["relevant_document"] = "missing.md"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown_relevant_document"):
        evaluate(
            dataset_path=path,
            course_dir=DEFAULT_COURSE_DIR,
            backend="hash",
            model_path=None,
            e5_prefixes=False,
        )


def test_glossary_expansion_is_versioned_auditable_and_contains_no_gold_metadata():
    expansion = expand_ml_query("如何用相关系数矩阵和热力图检查变量关系")

    assert expansion.applied is True
    assert expansion.strategy == "glossary-v1"
    assert expansion.glossary_version == GLOSSARY_VERSION
    assert {"correlation", "heatmap"}.issubset(expansion.matched_concepts)
    assert "correlation matrix" in expansion.added_terms
    assert "heatmap" in expansion.added_terms
    assert ".md" not in expansion.expanded_query
    assert "ZHEN-" not in expansion.expanded_query


def test_glossary_expansion_preserves_non_chinese_and_unknown_queries():
    english = expand_ml_query("How does PCA choose components?")
    unknown = expand_ml_query("校园食堂今天供应什么")

    assert english.applied is False
    assert english.expanded_query == english.original_query
    assert unknown.applied is False
    assert unknown.expanded_query == unknown.original_query


def test_glossary_strategy_is_explicit_in_report_and_baseline_remains_unchanged():
    baseline = evaluate(
        dataset_path=DEFAULT_DATASET,
        course_dir=DEFAULT_COURSE_DIR,
        backend="hash",
        model_path=None,
        e5_prefixes=False,
    )
    enhanced = evaluate(
        dataset_path=DEFAULT_DATASET,
        course_dir=DEFAULT_COURSE_DIR,
        backend="hash",
        model_path=None,
        e5_prefixes=False,
        query_strategy="glossary-v1",
    )

    assert baseline["query_strategy"] == "baseline"
    assert baseline["passed_at_rank_threshold"] == 5
    assert enhanced["query_strategy"] == "glossary-v1"
    assert enhanced["fusion"]["method"] == "none"
    assert all(item["matched_concepts"] for item in enhanced["case_results"])


def test_english_lexical_score_reads_body_terms_without_metadata():
    expansion = expand_ml_query("如何用相关系数矩阵和热力图检查变量关系")
    relevant = english_lexical_score(
        expansion,
        "Use a correlation matrix and a seaborn heatmap to inspect relationships between variables.",
    )
    unrelated = english_lexical_score(expansion, "Fit a decision tree classifier and predict test labels.")

    assert relevant >= 0.4
    assert relevant > unrelated
    assert unrelated == 0.0


def test_reciprocal_rank_fusion_is_deterministic_and_requires_same_documents():
    ranking, diagnostics = reciprocal_rank_fusion(
        {"a": 0.9, "b": 0.8, "c": 0.7},
        {"a": 0.1, "b": 0.9, "c": 0.2},
        lexical_weight=1.0,
    )

    assert ranking == ["b", "a", "c"]
    assert diagnostics["b"]["semantic_rank"] == 2
    assert diagnostics["b"]["lexical_rank"] == 1
    with pytest.raises(ValueError, match="document_sets_must_match"):
        reciprocal_rank_fusion({"a": 1.0}, {"b": 1.0})


def test_tfidf_document_scores_use_body_corpus_and_preserve_document_keys():
    expansion = expand_ml_query("训练前为什么要处理缺失值、类别变量和数值尺度")
    documents = {
        "preparation": "Handle missing values, encode categorical features, and standardize numeric features before training.",
        "tree": "A decision tree recursively splits samples to reduce impurity.",
    }
    scores = tfidf_document_scores(expansion, documents)

    assert set(scores) == set(documents)
    assert scores["preparation"] > scores["tree"]
    assert scores["preparation"] > 0
