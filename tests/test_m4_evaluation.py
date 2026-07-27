import json

import pytest

from app.m4_evaluation import (
    AdaptationAnnotation,
    AtomicFactAnnotation,
    CaseOutcome,
    CoverageAnnotation,
    M4EvaluationError,
    calculate_metric_report,
    load_frozen_benchmark,
)


def test_frozen_benchmark_has_blind_sixty_case_contract():
    benchmark = load_frozen_benchmark()

    assert len(benchmark.cases) == 60
    assert len(benchmark.core_knowledge_point_ids) == 32
    assert len(benchmark.case_file_sha256) == 64
    assert all("gold" not in item and "failure_branch" not in item for item in benchmark.blind_cases())


def test_metric_formulas_keep_exact_frozen_denominators():
    benchmark = load_frozen_benchmark()
    facts = (
        AtomicFactAnnotation(case_id="M0-K01", claim_id="c1", label="supported", annotator_ref="ann-1", status="final"),
        AtomicFactAnnotation(case_id="M0-K01", claim_id="c2", label="contradicted", annotator_ref="ann-1", status="final"),
        AtomicFactAnnotation(case_id="M0-K01", claim_id="c3", label="unsupported", annotator_ref="ann-1", status="final"),
        AtomicFactAnnotation(case_id="M0-K01", claim_id="c4", label="unknown", annotator_ref="ann-1", status="final"),
    )
    adaptation = (
        AdaptationAnnotation(
            case_id="M0-P01", resource_id="r1", resource_type="lesson", profile_id="profile-m0-beginner",
            prerequisite_fit="fit", difficulty_fit="fit", format_fit="partial", scaffolding_fit="fit",
            assessment_fit="fit", factual_quality_passed=True, annotator_ref="ann-1", status="final",
        ),
        AdaptationAnnotation(
            case_id="M0-P02", resource_id="r2", resource_type="lab_guide", profile_id="profile-m0-theory",
            prerequisite_fit="fit", difficulty_fit="unfit", format_fit="fit", scaffolding_fit="fit",
            assessment_fit="fit", factual_quality_passed=True, annotator_ref="ann-1", status="final",
        ),
    )
    coverage = (
        CoverageAnnotation(
            knowledge_point_id="KP-01", resource_type="resource_bundle", artifact_version_id="av-001",
            substantial=True, traceable_source_or_original=True, semantic_review_passed=True,
            artifact_approved=True, annotator_ref="ann-1", status="final",
        ),
        CoverageAnnotation(
            knowledge_point_id="KP-02", resource_type="lesson", artifact_version_id="av-002",
            substantial=False, traceable_source_or_original=True, semantic_review_passed=True,
            artifact_approved=True, annotator_ref="ann-1", status="final",
        ),
    )
    outcomes = tuple(
        CaseOutcome(case_id=case.case_id, status="completed", citation_count=1, locatable_citation_count=1)
        for case in benchmark.cases[:50]
    )

    report = calculate_metric_report(
        benchmark,
        outcomes=outcomes,
        fact_annotations=facts,
        adaptation_annotations=adaptation,
        coverage_annotations=coverage,
    )

    assert (report.hallucination_rate.numerator, report.hallucination_rate.denominator) == (2, 3)
    assert report.hallucination_rate.percent == 66.6667
    assert report.adaptation_accuracy.percent == 50.0
    assert (report.core_coverage.numerator, report.core_coverage.denominator) == (1, 32)
    assert report.task_completion_rate.percent == 100.0
    assert report.publication_authorized is False
    assert "independent_evaluation_approval_missing" in report.publication_blockers


def test_metric_report_fails_closed_for_unknown_case_and_empty_annotations():
    benchmark = load_frozen_benchmark()
    with pytest.raises(M4EvaluationError, match="unknown evaluation cases"):
        calculate_metric_report(
            benchmark,
            outcomes=(CaseOutcome(case_id="M0-NOT-REAL", status="failed"),),
            fact_annotations=(),
            adaptation_annotations=(),
            coverage_annotations=(),
        )

    report = calculate_metric_report(
        benchmark,
        outcomes=(),
        fact_annotations=(),
        adaptation_annotations=(),
        coverage_annotations=(),
    )
    assert report.hallucination_rate.status == "insufficient"
    assert report.adaptation_accuracy.status == "insufficient"
    assert report.core_coverage.denominator == 32
    assert report.publication_authorized is False
