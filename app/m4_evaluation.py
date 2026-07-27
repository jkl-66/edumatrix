"""Frozen M4 benchmark loading and official metric calculations."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from app.m2_contracts import StrictModel


ROOT = Path(__file__).resolve().parents[1]
M0_DATASET_DIR = ROOT / "outputs" / "M0_阶段0基线与架构契约" / "datasets"
EVALUATION_CASE_VERSION = "evaluation-case-m0-0.1"
METRIC_VERSION = "metrics-m0-0.1"
REQUIRED_CASE_GROUPS = {
    "knowledge_accuracy": 10,
    "retrieval": 10,
    "generation": 10,
    "profile_adaptation": 10,
    "quality_and_decision": 10,
    "security_recovery": 10,
}


class M4EvaluationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class FrozenEvaluationCase(StrictModel):
    case_id: str = Field(pattern=r"^M0-[A-Z]+\d+$")
    category: Literal[
        "knowledge_accuracy", "retrieval", "generation", "profile_adaptation",
        "quality_review", "decision", "security_recovery",
    ]
    profile_id: str = Field(min_length=8, max_length=128)
    objective: str = Field(min_length=1)
    input: str = Field(min_length=1)
    gold: str = Field(min_length=1)
    kp: tuple[str, ...] = Field(min_length=1)
    difficulty: str = Field(pattern=r"^L[0-4](?:-L[0-4])?$")
    failure_branch: str = Field(min_length=1)

    @model_validator(mode="after")
    def unique_knowledge_points(self) -> "FrozenEvaluationCase":
        if len(set(self.kp)) != len(self.kp):
            raise ValueError("case knowledge points must be unique")
        return self

    def blind_payload(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "profile_id": self.profile_id,
            "objective": self.objective,
            "input": self.input,
        }


class FrozenBenchmark(StrictModel):
    schema_version: Literal["m4.benchmark.v1"] = "m4.benchmark.v1"
    case_version: Literal["evaluation-case-m0-0.1"] = EVALUATION_CASE_VERSION
    knowledge_point_version: Literal["kp-rag-0.1"] = "kp-rag-0.1"
    metric_version: Literal["metrics-m0-0.1"] = METRIC_VERSION
    case_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    knowledge_point_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cases: tuple[FrozenEvaluationCase, ...] = Field(min_length=60, max_length=60)
    core_knowledge_point_ids: tuple[str, ...] = Field(min_length=32, max_length=32)

    def blind_cases(self) -> tuple[dict[str, object], ...]:
        return tuple(case.blind_payload() for case in self.cases)


FactLabel = Literal["supported", "contradicted", "unsupported", "unknown", "non_factual"]
FitLabel = Literal["fit", "partial", "unfit", "unknown"]
AnnotationStatus = Literal["draft", "final", "adjudicated"]


class AtomicFactAnnotation(StrictModel):
    case_id: str
    claim_id: str = Field(min_length=1, max_length=128)
    label: FactLabel
    annotator_ref: str = Field(min_length=1, max_length=128)
    status: AnnotationStatus = "draft"
    rationale: str = Field(default="", max_length=2000)


class AdaptationAnnotation(StrictModel):
    case_id: str
    resource_id: str = Field(min_length=1, max_length=128)
    resource_type: Literal["lesson", "lab_guide", "tiered_quiz"]
    profile_id: str = Field(min_length=8, max_length=128)
    prerequisite_fit: FitLabel
    difficulty_fit: FitLabel
    format_fit: FitLabel
    scaffolding_fit: FitLabel
    assessment_fit: FitLabel
    factual_quality_passed: bool
    annotator_ref: str = Field(min_length=1, max_length=128)
    status: AnnotationStatus = "draft"

    @property
    def passed(self) -> bool:
        other = (self.prerequisite_fit, self.format_fit, self.scaffolding_fit)
        return (
            self.factual_quality_passed
            and self.difficulty_fit == "fit"
            and self.assessment_fit == "fit"
            and "unfit" not in other
        )


class CoverageAnnotation(StrictModel):
    knowledge_point_id: str
    resource_type: Literal["lesson", "lab_guide", "tiered_quiz", "resource_bundle"]
    artifact_version_id: str = Field(min_length=3, max_length=128)
    substantial: bool
    traceable_source_or_original: bool
    semantic_review_passed: bool
    artifact_approved: bool
    annotator_ref: str = Field(min_length=1, max_length=128)
    status: AnnotationStatus = "draft"

    @property
    def valid_coverage(self) -> bool:
        return all((
            self.substantial,
            self.traceable_source_or_original,
            self.semantic_review_passed,
            self.artifact_approved,
        ))


class CaseOutcome(StrictModel):
    case_id: str
    status: Literal["completed", "legal_refusal", "failed", "timeout"]
    citation_count: int = Field(default=0, ge=0)
    locatable_citation_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def citation_counts_are_consistent(self) -> "CaseOutcome":
        if self.locatable_citation_count > self.citation_count:
            raise ValueError("locatable citations cannot exceed all citations")
        return self


class MetricValue(StrictModel):
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    percent: float | None
    status: Literal["calculated", "insufficient"]


class M4MetricReport(StrictModel):
    schema_version: Literal["m4.metric-report.v1"] = "m4.metric-report.v1"
    metric_version: Literal["metrics-m0-0.1"] = METRIC_VERSION
    hallucination_rate: MetricValue
    adaptation_accuracy: MetricValue
    core_coverage: MetricValue
    task_completion_rate: MetricValue
    legal_refusal_rate: MetricValue
    unknown_fact_rate: MetricValue
    citation_locatability: MetricValue
    evaluated_case_count: int = Field(ge=0)
    required_valid_case_count: Literal[50] = 50
    publication_authorized: Literal[False] = False
    publication_blockers: tuple[str, ...]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_frozen_benchmark(dataset_dir: Path = M0_DATASET_DIR) -> FrozenBenchmark:
    case_path = dataset_dir / "evaluation_cases.jsonl"
    kp_path = dataset_dir / "core_knowledge_points.json"
    if not case_path.is_file() or not kp_path.is_file():
        raise M4EvaluationError("benchmark_files_missing", "frozen M0 benchmark files are missing")

    cases = tuple(
        FrozenEvaluationCase.model_validate(json.loads(line))
        for line in case_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    if len(cases) != 60 or len({case.case_id for case in cases}) != 60:
        raise M4EvaluationError("case_set_changed", "benchmark must contain 60 unique cases")

    groups = Counter()
    for case in cases:
        group = "quality_and_decision" if case.category in {"quality_review", "decision"} else case.category
        groups[group] += 1
    if dict(groups) != REQUIRED_CASE_GROUPS:
        raise M4EvaluationError("case_distribution_changed", f"unexpected case distribution: {dict(groups)}")

    kp_data = json.loads(kp_path.read_text(encoding="utf-8"))
    kp_ids = tuple(item["id"] for item in kp_data.get("points", ()))
    if kp_data.get("gold_version") != "kp-rag-0.1" or kp_data.get("coverage_denominator") != 32:
        raise M4EvaluationError("coverage_denominator_changed", "core knowledge denominator must remain kp-rag-0.1/32")
    if len(kp_ids) != 32 or len(set(kp_ids)) != 32:
        raise M4EvaluationError("knowledge_point_set_changed", "benchmark must contain 32 unique core knowledge points")
    unknown_refs = sorted({kp for case in cases for kp in case.kp if kp not in set(kp_ids)})
    if unknown_refs:
        raise M4EvaluationError("case_knowledge_point_unknown", f"unknown knowledge point references: {unknown_refs}")

    return FrozenBenchmark(
        case_file_sha256=_sha256(case_path),
        knowledge_point_file_sha256=_sha256(kp_path),
        cases=cases,
        core_knowledge_point_ids=kp_ids,
    )


def _metric(numerator: int, denominator: int) -> MetricValue:
    if denominator == 0:
        return MetricValue(numerator=numerator, denominator=0, percent=None, status="insufficient")
    return MetricValue(
        numerator=numerator,
        denominator=denominator,
        percent=round(numerator / denominator * 100, 4),
        status="calculated",
    )


def calculate_metric_report(
    benchmark: FrozenBenchmark,
    *,
    outcomes: tuple[CaseOutcome, ...],
    fact_annotations: tuple[AtomicFactAnnotation, ...],
    adaptation_annotations: tuple[AdaptationAnnotation, ...],
    coverage_annotations: tuple[CoverageAnnotation, ...],
) -> M4MetricReport:
    case_ids = {case.case_id for case in benchmark.cases}
    outcome_ids = [item.case_id for item in outcomes]
    if len(outcome_ids) != len(set(outcome_ids)):
        raise M4EvaluationError("duplicate_case_outcome", "each case may have only one outcome per run")
    referenced_cases = set(outcome_ids)
    referenced_cases.update(item.case_id for item in fact_annotations)
    referenced_cases.update(item.case_id for item in adaptation_annotations)
    unknown_cases = sorted(referenced_cases - case_ids)
    if unknown_cases:
        raise M4EvaluationError("unknown_case_reference", f"unknown evaluation cases: {unknown_cases}")

    core_ids = set(benchmark.core_knowledge_point_ids)
    unknown_kps = sorted({item.knowledge_point_id for item in coverage_annotations} - core_ids)
    if unknown_kps:
        raise M4EvaluationError("unknown_coverage_knowledge_point", f"unknown core knowledge points: {unknown_kps}")

    fact_counts = Counter(item.label for item in fact_annotations)
    judgeable = fact_counts["supported"] + fact_counts["contradicted"] + fact_counts["unsupported"]
    hallucinated = fact_counts["contradicted"] + fact_counts["unsupported"]
    adaptation_passed = sum(item.passed for item in adaptation_annotations)
    covered_ids = {item.knowledge_point_id for item in coverage_annotations if item.valid_coverage}
    completed = sum(item.status == "completed" for item in outcomes)
    legal_refusals = sum(item.status == "legal_refusal" for item in outcomes)
    citation_count = sum(item.citation_count for item in outcomes)
    locatable_count = sum(item.locatable_citation_count for item in outcomes)

    blockers = []
    if len(outcomes) < 50:
        blockers.append("fewer_than_50_case_outcomes")
    if any(item.status == "draft" for item in (*fact_annotations, *adaptation_annotations, *coverage_annotations)):
        blockers.append("draft_annotations_present")
    if judgeable == 0:
        blockers.append("no_judgeable_atomic_facts")
    if not adaptation_annotations:
        blockers.append("no_adaptation_annotations")
    if not coverage_annotations:
        blockers.append("no_coverage_annotations")
    blockers.append("independent_evaluation_approval_missing")

    return M4MetricReport(
        hallucination_rate=_metric(hallucinated, judgeable),
        adaptation_accuracy=_metric(adaptation_passed, len(adaptation_annotations)),
        core_coverage=_metric(len(covered_ids), len(benchmark.core_knowledge_point_ids)),
        task_completion_rate=_metric(completed, len(outcomes)),
        legal_refusal_rate=_metric(legal_refusals, len(outcomes)),
        unknown_fact_rate=_metric(fact_counts["unknown"], sum(fact_counts.values())),
        citation_locatability=_metric(locatable_count, citation_count),
        evaluated_case_count=len(outcomes),
        publication_blockers=tuple(blockers),
    )
