"""Unit tests for Task 2.1 (GraphBuilder) and Task 2.2 (FormulaRAG)."""
from __future__ import annotations

import sys
import os
import pytest

# Ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.graph_models import Triplet, EntityAlignment, AlignedTriplet, GraphBuildReport, GraphQueryResult
from app.utils.graph_builder import (
    GraphBuilder,
    InMemoryGraphRepository,
    levenshtein_distance,
    levenshtein_ratio,
    align_entity,
    ENTITY_SYNONYM_WHITELIST,
    extract_triplets_from_text,
    _parse_llm_triplets,
    _rule_based_triplets,
    seed_default_graph,
)
from app.utils.formula_extractor import (
    ExtractedFormula,
    FormulaExtractor,
    _latex_to_semantic,
)
from app.utils.formula_rag import (
    FormulaRAG,
    FormulaSearchHit,
    InMemoryFormulaStore,
    encode_dual_track,
    seed_formula_index,
)


# ===================== Task 2.1 Tests =====================

class TestLevenshtein:
    def test_identical_strings(self):
        assert levenshtein_distance("abc", "abc") == 0

    def test_empty_string(self):
        assert levenshtein_distance("", "abc") == 3

    def test_insertion(self):
        assert levenshtein_distance("abc", "abdc") == 1

    def test_deletion(self):
        assert levenshtein_distance("abdc", "abc") == 1

    def test_ratio_identical(self):
        assert levenshtein_ratio("Loss Function", "Loss Function") == 1.0

    def test_ratio_similar(self):
        assert levenshtein_ratio("Loss Function", "loss function") > 0.7


class TestEntityAlignment:
    def test_exact_key_match(self):
        result = align_entity("Loss Function")
        assert result.canonical == "损失函数"
        assert result.method == "exact"

    def test_exact_value_match(self):
        result = align_entity("损失函数")
        assert result.canonical == "损失函数"
        assert result.method == "exact"

    def test_levenshtein_fuzzy_match(self):
        result = align_entity("Loss Funcion")  # typo
        assert result.canonical == "损失函数"
        assert result.method in ("levenshtein", "exact")

    def test_fallback_unknown_entity(self):
        result = align_entity("量子纠缠")
        assert result.canonical == "量子纠缠"
        assert result.method == "fallback"

    def test_empty_string_fallback(self):
        result = align_entity("")
        assert result.method == "fallback"


class TestTripletExtraction:
    def test_parse_llm_json(self):
        raw = '[{"source": "线性代数", "relation": "PREREQUISITE_OF", "target": "向量表示"}]'
        triplets = _parse_llm_triplets(raw)
        assert len(triplets) == 1
        assert triplets[0].source == "线性代数"
        assert triplets[0].target == "向量表示"

    def test_parse_llm_with_surrounding_text(self):
        raw = 'Here are the results:\n[{"source": "微积分", "relation": "PREREQUISITE_OF", "target": "梯度下降"}]\nEnd.'
        triplets = _parse_llm_triplets(raw)
        assert len(triplets) == 1
        assert triplets[0].source == "微积分"

    def test_rule_based_extraction(self):
        text = "线性代数是向量表示的基础"
        triplets = _rule_based_triplets(text)
        assert len(triplets) >= 1
        assert any(t.source == "线性代数" for t in triplets)

    def test_rule_based_prerequisite(self):
        text = "学习梯度下降之前需要先掌握微积分"
        triplets = _rule_based_triplets(text)
        assert len(triplets) >= 1


class TestInMemoryGraphRepository:
    def test_merge_and_query(self):
        repo = InMemoryGraphRepository()
        repo.merge_node("Concept", "微积分")
        repo.merge_node("Concept", "梯度下降")
        repo.merge_edge("微积分", "梯度下降", "PREREQUISITE_OF")
        assert repo.count_nodes() == 2
        assert repo.count_edges() == 1
        result = repo.query_prerequisites("梯度下降")
        assert "微积分" in result.prerequisites


class TestGraphBuilder:
    def test_build_from_text(self):
        repo = InMemoryGraphRepository()
        builder = GraphBuilder(repository=repo)
        report = builder.build_from_text(
            "线性代数是向量表示的基础\n\n概率统计是朴素贝叶斯的基础",
            source="test",
        )
        assert isinstance(report, GraphBuildReport)
        assert report.chunk_count == 2
        assert report.raw_triplets > 0

    def test_build_from_chunks_with_llm_json(self):
        repo = InMemoryGraphRepository()
        builder = GraphBuilder(repository=repo)
        # Simulate LLM output by using rule-based as fallback
        chunks = [
            '[{"source": "线性代数", "relation": "PREREQUISITE_OF", "target": "向量表示"}]',
        ]
        # This will use rule-based since no LLM is provided, but the chunk
        # contains valid JSON that rule-based won't match
        report = builder.build_from_chunks(tuple(chunks), source="test-llm")
        assert isinstance(report, GraphBuildReport)

    def test_alignment_rate_90_percent(self):
        """验收标准: 同义词对齐率 >= 90%"""
        repo = InMemoryGraphRepository()
        builder = GraphBuilder(repository=repo)
        # Use triplet extraction with known synonyms
        triplets = (
            Triplet(source="Loss Function", target="Gradient Descent", relation="PREREQUISITE_OF"),
            Triplet(source="Backpropagation", target="Gradient Descent", relation="PREREQUISITE_OF"),
            Triplet(source="Logistic Regression", target="Overfitting", relation="PREREQUISITE_OF"),
            Triplet(source="Linear Regression", target="Loss Function", relation="PREREQUISITE_OF"),
            Triplet(source="Convolutional Neural Network", target="Pooling", relation="PREREQUISITE_OF"),
            Triplet(source="微积分", target="梯度下降", relation="PREREQUISITE_OF"),
            Triplet(source="损失函数", target="反向传播", relation="PREREQUISITE_OF"),
            Triplet(source="池化层", target="最大池化", relation="PREREQUISITE_OF"),
            Triplet(source="Feature Engineering", target="监督学习", relation="PREREQUISITE_OF"),
            Triplet(source="Chain Rule", target="反向传播", relation="PREREQUISITE_OF"),
        )
        aligned_count = 0
        for t in triplets:
            a = builder._align_triplet(t)
            if a.both_aligned:
                aligned_count += 1
        rate = aligned_count / len(triplets)
        assert rate >= 0.9, f"Alignment rate {rate:.2%} < 90%"

    def test_seed_default_graph(self):
        report = seed_default_graph()
        assert report.written_edges > 0
        assert report.raw_triplets > 30


# ===================== Task 2.2 Tests =====================

class TestLatexSemantic:
    def test_fraction(self):
        result = _latex_to_semantic(r"\frac{\partial L}{\partial W}")
        assert "偏导数" in result
        assert "除以" in result

    def test_sum(self):
        result = _latex_to_semantic(r"\sum_{i=1}^{n}")
        assert "求和" in result

    def test_integral(self):
        result = _latex_to_semantic(r"\int_0^1 f(x) dx")
        assert "积分" in result

    def test_empty(self):
        assert _latex_to_semantic("") == "未知公式"


class TestExtractedFormula:
    def test_enhanced_text(self):
        f = ExtractedFormula(
            latex_source=r"\frac{\partial L}{\partial W}",
            semantic_text="损失函数对权重的偏导数",
            bbox=(0, 0, 200, 50),
            confidence=0.95,
        )
        enhanced = f.enhanced_text()
        assert "[LaTeX_Source:" in enhanced
        assert "公式语义解释:" in enhanced
        assert "损失函数对权重的偏导数" in enhanced


class TestFormulaExtractor:
    def test_extract_from_text(self):
        extractor = FormulaExtractor()
        text = "梯度下降的更新规则为 $$W := W - \\alpha \\frac{\\partial L}{\\partial W}$$"
        formulas = extractor.extract_from_text(text)
        assert len(formulas) >= 1
        assert "partial L" in formulas[0].latex_source

    def test_formula_to_evidence(self):
        extractor = FormulaExtractor()
        formula = ExtractedFormula(
            latex_source=r"\frac{\partial L}{\partial W}",
            semantic_text="损失函数对权重的偏导数",
            bbox=(0, 0, 200, 50),
            confidence=0.95,
        )
        evidence = extractor.formula_to_evidence(formula, chunk_id="TEST_001")
        assert evidence.id == "TEST_001"
        assert "LaTeX_Source" in evidence.content


class TestDualTrackEmbedding:
    def test_encode_dual_track(self):
        formula = ExtractedFormula(
            latex_source=r"\frac{\partial L}{\partial W}",
            semantic_text="损失函数对权重的偏导数",
            bbox=(0, 0, 200, 50),
            confidence=0.95,
        )
        vec = encode_dual_track(formula, chunk_id="TEST_DUAL")
        assert vec.chunk_id == "TEST_DUAL"
        assert len(vec.latex_vector) > 0
        assert len(vec.semantic_vector) > 0
        assert vec.latex_source == r"\frac{\partial L}{\partial W}"


class TestInMemoryFormulaStore:
    def test_upsert_and_search(self):
        store = InMemoryFormulaStore()
        formula = ExtractedFormula(
            latex_source=r"\frac{\partial L}{\partial W}",
            semantic_text="损失函数对权重的偏导数",
            bbox=(0, 0, 200, 50),
            confidence=1.0,
        )
        vec = encode_dual_track(formula, chunk_id="FORMULA_TEST_01")
        store.upsert((vec,))
        assert store.count() == 1
        hits = store.search("损失函数对权重的偏导数", top_k=3, min_similarity=0.3)
        assert len(hits) >= 1
        assert hits[0].chunk_id == "FORMULA_TEST_01"


class TestFormulaRAG:
    def test_index_and_search(self):
        rag = FormulaRAG(store=InMemoryFormulaStore())
        formula = ExtractedFormula(
            latex_source=r"\frac{\partial L}{\partial W}",
            semantic_text="损失函数对权重的偏导数",
            bbox=(0, 0, 200, 50),
            confidence=1.0,
        )
        count = rag.index_formulas((formula,), source="test")
        assert count == 1
        hits = rag.search("损失函数对权重的偏导数", top_k=3)
        assert len(hits) >= 1

    def test_search_as_evidence(self):
        rag = FormulaRAG(store=InMemoryFormulaStore())
        formula = ExtractedFormula(
            latex_source=r"\frac{\partial L}{\partial W}",
            semantic_text="损失函数对权重的偏导数",
            bbox=(0, 0, 200, 50),
            confidence=1.0,
        )
        rag.index_formulas((formula,), source="test")
        evidence = rag.search_as_evidence("损失函数对权重的偏导数", top_k=3)
        assert len(evidence) >= 1
        assert "LaTeX_Source" in evidence[0].content

    def test_index_from_text(self):
        rag = FormulaRAG(store=InMemoryFormulaStore())
        text = "梯度下降公式为 $$W := W - \\alpha \\frac{\\partial L}{\\partial W}$$"
        count = rag.index_from_text(text, source_file="test.md")
        assert count >= 1
        hits = rag.search("损失函数对权重的偏导数", top_k=3)
        assert len(hits) >= 1

    def test_seed_formula_index(self):
        count = seed_formula_index()
        assert count >= 8

    def test_formula_recall_cosine_threshold(self):
        """验收标准: 检索相关度 (Cosine Similarity) > 0.88"""
        rag = FormulaRAG(store=InMemoryFormulaStore())
        seed_formula_index(rag)
        hits = rag.search("损失函数对权重的偏导数", top_k=3, min_similarity=0.0)
        assert len(hits) >= 1
        # The top hit should contain partial L / partial W
        top = hits[0]
        assert r"\frac{\partial L}{\partial W}" in top.latex_source
        assert top.score >= 0.88, f"Score {top.score} < 0.88 threshold"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
