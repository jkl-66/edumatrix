"""Frozen M4 benchmark loading and official metric calculations."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from app.m2_contracts import StrictModel
from app.m3_profiles import load_m3_gold_profiles, M3ProfileContractError


ROOT = Path(__file__).resolve().parents[1]
M0_DATASET_DIR = ROOT / "outputs" / "M0_阶段0基线与架构契约" / "datasets"
EVALUATION_CASE_VERSION = "evaluation-case-m0-0.1"
METRIC_VERSION = "metrics-m0-0.1"
DOMAIN_VERSION = "domain-rag-0.1"
COURSE_ID = "course-rag-engineering-m0"
PROFILE_VERSION = "baseline-profile-0.1"
PROFILE_IDS = (
    "profile-m0-beginner",
    "profile-m0-theory",
    "profile-m0-advanced",
)
HALLUCINATION_LIMIT = 5.0
ADAPTATION_TARGET = 85.0
COVERAGE_TARGET = 90.0
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
    course_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    domain_id: Literal["domain-rag-0.1"] = DOMAIN_VERSION
    course_id: Literal["course-rag-engineering-m0"] = COURSE_ID
    profile_version: Literal["baseline-profile-0.1"] = PROFILE_VERSION
    profile_ids: tuple[str, ...] = Field(min_length=3, max_length=3)
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
    publication_authorized: bool = False
    evaluation_status: Literal["blocked", "needs_improvement", "evaluated", "qualified"] = "blocked"
    thresholds: dict[str, Any] = Field(default_factory=dict)
    buckets: dict[str, Any] = Field(default_factory=dict)
    generalization: dict[str, Any] = Field(default_factory=dict)
    failure_case_ids: tuple[str, ...] = ()
    improvement_input: dict[str, Any] = Field(default_factory=dict)
    publication_blockers: tuple[str, ...]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_frozen_context(dataset_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest_path = dataset_dir / "course_manifest.json"
    profile_path = dataset_dir / "baseline_profiles.json"
    if not manifest_path.is_file() or not profile_path.is_file():
        raise M4EvaluationError("fixture_files_missing", "frozen course manifest and profile fixtures are required")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        profiles = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise M4EvaluationError("fixture_invalid", "frozen course/profile fixture is unreadable") from exc
    if manifest.get("course_id") != COURSE_ID or manifest.get("domain_pack") != DOMAIN_VERSION:
        raise M4EvaluationError("domain_fixture_changed", "M4 domain/course fixture changed")
    if profiles.get("schema_version") != PROFILE_VERSION or profiles.get("data_class") != "P2-SYNTHETIC":
        raise M4EvaluationError("profile_fixture_changed", "M4 profile fixture must remain synthetic baseline-profile-0.1")
    items = profiles.get("profiles")
    profile_items = items if isinstance(items, list) else []
    ids = tuple(item.get("profile_id") for item in profile_items)
    if ids != PROFILE_IDS or len({item.get("student_id") for item in profile_items}) != 3:
        raise M4EvaluationError("profile_fixture_changed", f"expected exactly the three frozen profiles {PROFILE_IDS}")
    try:
        load_m3_gold_profiles(profile_path)
    except M3ProfileContractError as exc:
        raise M4EvaluationError("profile_fixture_changed", str(exc)) from exc
    return manifest, profiles


def load_frozen_benchmark(dataset_dir: Path = M0_DATASET_DIR) -> FrozenBenchmark:
    case_path = dataset_dir / "evaluation_cases.jsonl"
    kp_path = dataset_dir / "core_knowledge_points.json"
    if not case_path.is_file() or not kp_path.is_file():
        raise M4EvaluationError("benchmark_files_missing", "frozen M0 benchmark files are missing")

    manifest, profiles = _load_frozen_context(dataset_dir)
    cases = tuple(
        FrozenEvaluationCase.model_validate(json.loads(line))
        for line in case_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    if len(cases) != 60 or len({case.case_id for case in cases}) != 60:
        raise M4EvaluationError("case_set_changed", "benchmark must contain 60 unique cases")
    case_profiles = {case.profile_id for case in cases}
    if case_profiles != set(PROFILE_IDS):
        raise M4EvaluationError("case_profile_distribution_changed", "all three frozen profiles must have evaluation cases")

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
        course_manifest_sha256=_sha256(dataset_dir / "course_manifest.json"),
        profile_file_sha256=_sha256(dataset_dir / "baseline_profiles.json"),
        domain_id=manifest["domain_pack"],
        course_id=manifest["course_id"],
        profile_version=profiles["schema_version"],
        profile_ids=PROFILE_IDS,
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
    independent_evaluation_approval: bool = False,
) -> M4MetricReport:
    case_ids = {case.case_id for case in benchmark.cases}
    case_map = {case.case_id: case for case in benchmark.cases}
    outcome_ids = [item.case_id for item in outcomes]
    if len(outcome_ids) != len(set(outcome_ids)):
        raise M4EvaluationError("duplicate_case_outcome", "each case may have only one outcome per run")
    referenced_cases = set(outcome_ids)
    referenced_cases.update(item.case_id for item in fact_annotations)
    unknown_cases = sorted(referenced_cases - case_ids)
    if unknown_cases:
        raise M4EvaluationError("unknown_case_reference", f"unknown evaluation cases: {unknown_cases}")

    core_ids = set(benchmark.core_knowledge_point_ids)
    unknown_kps = sorted({item.knowledge_point_id for item in coverage_annotations} - core_ids)
    if unknown_kps:
        raise M4EvaluationError("unknown_coverage_knowledge_point", f"unknown core knowledge points: {unknown_kps}")
    unknown_profiles = sorted({item.profile_id for item in adaptation_annotations} - set(benchmark.profile_ids))
    if unknown_profiles:
        raise M4EvaluationError("unknown_profile_reference", f"unknown frozen profiles: {unknown_profiles}")
    fact_keys = [(item.case_id, item.claim_id) for item in fact_annotations]
    if len(fact_keys) != len(set(fact_keys)):
        raise M4EvaluationError("duplicate_claim_annotation", "each case/claim pair may be annotated only once")
    resource_ids = [item.resource_id for item in adaptation_annotations]
    if len(resource_ids) != len(set(resource_ids)):
        raise M4EvaluationError("duplicate_resource_annotation", "each resource instance may be annotated only once")
    coverage_ids_seen = [item.knowledge_point_id for item in coverage_annotations]
    if len(coverage_ids_seen) != len(set(coverage_ids_seen)):
        raise M4EvaluationError("duplicate_coverage_annotation", "each core knowledge point may be annotated only once")

    fact_counts = Counter(item.label for item in fact_annotations)
    judgeable = fact_counts["supported"] + fact_counts["contradicted"] + fact_counts["unsupported"]
    hallucinated = fact_counts["contradicted"] + fact_counts["unsupported"]
    adaptation_passed = sum(item.passed for item in adaptation_annotations)
    covered_ids = {item.knowledge_point_id for item in coverage_annotations if item.valid_coverage}
    completed = sum(item.status == "completed" for item in outcomes)
    legal_refusals = sum(item.status == "legal_refusal" for item in outcomes)
    citation_count = sum(item.citation_count for item in outcomes)
    locatable_count = sum(item.locatable_citation_count for item in outcomes)

    def _counter_bucket(bucket: dict[str, Counter[str]]) -> dict[str, dict[str, int]]:
        return {key: dict(sorted(value.items())) for key, value in sorted(bucket.items())}

    cases_by_profile: dict[str, Counter[str]] = defaultdict(Counter)
    cases_by_category: dict[str, Counter[str]] = defaultdict(Counter)
    outcomes_by_profile: dict[str, Counter[str]] = defaultdict(Counter)
    outcomes_by_category: dict[str, Counter[str]] = defaultdict(Counter)
    facts_by_profile: dict[str, Counter[str]] = defaultdict(Counter)
    facts_by_kp: dict[str, Counter[str]] = defaultdict(Counter)
    adaptation_by_profile: dict[str, Counter[str]] = defaultdict(Counter)
    adaptation_by_resource: dict[str, Counter[str]] = defaultdict(Counter)
    coverage_by_kp: dict[str, Counter[str]] = defaultdict(Counter)
    coverage_by_resource: dict[str, Counter[str]] = defaultdict(Counter)
    for case in benchmark.cases:
        cases_by_profile[case.profile_id]["cases"] += 1
        cases_by_category[case.category]["cases"] += 1
    for outcome in outcomes:
        case = case_map[outcome.case_id]
        outcomes_by_profile[case.profile_id][outcome.status] += 1
        outcomes_by_category[case.category][outcome.status] += 1
    for annotation in fact_annotations:
        case = case_map[annotation.case_id]
        facts_by_profile[case.profile_id][annotation.label] += 1
        for kp_id in case.kp:
            facts_by_kp[kp_id][annotation.label] += 1
    for annotation in adaptation_annotations:
        adaptation_by_profile[annotation.profile_id]["passed" if annotation.passed else "failed"] += 1
        adaptation_by_resource[annotation.resource_type]["passed" if annotation.passed else "failed"] += 1
    for annotation in coverage_annotations:
        coverage_by_kp[annotation.knowledge_point_id]["valid" if annotation.valid_coverage else "invalid"] += 1
        coverage_by_resource[annotation.resource_type]["valid" if annotation.valid_coverage else "invalid"] += 1

    blockers: list[str] = []
    if len(outcomes) < 60:
        blockers.append("fewer_than_60_case_outcomes")
    if completed and len(fact_annotations) < completed:
        blockers.append("fewer_than_one_claim_per_completed_case")
    if any(item.status == "draft" for item in (*fact_annotations, *adaptation_annotations, *coverage_annotations)):
        blockers.append("draft_annotations_present")
    if judgeable == 0:
        blockers.append("no_judgeable_atomic_facts")
    if not adaptation_annotations:
        blockers.append("no_adaptation_annotations")
    if len(adaptation_annotations) != 9:
        blockers.append("adaptation_resource_count_not_9")
    if not coverage_annotations:
        blockers.append("no_coverage_annotations")
    if len(coverage_annotations) != 32:
        blockers.append("coverage_annotation_count_not_32")
    observed_profiles = {
        case_map[item.case_id].profile_id for item in (*outcomes, *fact_annotations)
    } | {item.profile_id for item in adaptation_annotations}
    if observed_profiles != set(benchmark.profile_ids):
        blockers.append("all_three_profiles_not_in_fixture")
    if not independent_evaluation_approval:
        blockers.append("independent_evaluation_approval_missing")

    report_values = {
        "hallucination_rate": _metric(hallucinated, judgeable),
        "adaptation_accuracy": _metric(adaptation_passed, len(adaptation_annotations)),
        "core_coverage": _metric(len(covered_ids), len(benchmark.core_knowledge_point_ids)),
    }
    thresholds = {
        "hallucination_rate": {
            "operator": "<", "target_percent": HALLUCINATION_LIMIT,
            "actual_percent": report_values["hallucination_rate"].percent,
            "passed": report_values["hallucination_rate"].percent is not None
            and report_values["hallucination_rate"].percent < HALLUCINATION_LIMIT,
        },
        "adaptation_accuracy": {
            "operator": ">=", "target_percent": ADAPTATION_TARGET,
            "actual_percent": report_values["adaptation_accuracy"].percent,
            "passed": report_values["adaptation_accuracy"].percent is not None
            and report_values["adaptation_accuracy"].percent >= ADAPTATION_TARGET,
        },
        "core_coverage": {
            "operator": ">=", "target_percent": COVERAGE_TARGET,
            "actual_percent": report_values["core_coverage"].percent,
            "minimum_valid_points": 29,
            "passed": report_values["core_coverage"].numerator >= 29
            and report_values["core_coverage"].denominator == 32,
        },
    }
    for metric_name, threshold in thresholds.items():
        if not threshold["passed"]:
            blockers.append(f"{metric_name}_threshold_not_met")

    failure_case_ids = tuple(sorted(
        outcome.case_id for outcome in outcomes if outcome.status in {"failed", "timeout", "legal_refusal"}
    ))
    improvement_input = {
        "schema_version": "m4.improvement-input.v1",
        "source_metric_version": benchmark.metric_version,
        "profile_ids": list(benchmark.profile_ids),
        "failed_case_ids": list(failure_case_ids),
        "uncovered_knowledge_point_ids": sorted(core_ids - covered_ids),
        "failed_resource_ids": sorted(item.resource_id for item in adaptation_annotations if not item.passed),
        "profile_resource_failures": {
            profile_id: sorted(
                item.resource_id for item in adaptation_annotations
                if item.profile_id == profile_id and not item.passed
            )
            for profile_id in benchmark.profile_ids
        },
        "write_target": "versioned_improvement_input_only",
        "canonical_profile_or_mastery_write": False,
        "learning_event_write": False,
    }
    hard_blockers = [item for item in blockers if not item.endswith("_threshold_not_met")]
    if hard_blockers:
        evaluation_status = "blocked"
    elif any(item.endswith("_threshold_not_met") for item in blockers):
        evaluation_status = "needs_improvement"
    elif independent_evaluation_approval:
        evaluation_status = "qualified"
    else:
        evaluation_status = "evaluated"

    return M4MetricReport(
        hallucination_rate=report_values["hallucination_rate"],
        adaptation_accuracy=report_values["adaptation_accuracy"],
        core_coverage=report_values["core_coverage"],
        task_completion_rate=_metric(completed, len(outcomes)),
        legal_refusal_rate=_metric(legal_refusals, len(outcomes)),
        unknown_fact_rate=_metric(fact_counts["unknown"], sum(fact_counts.values())),
        citation_locatability=_metric(locatable_count, citation_count),
        evaluated_case_count=len(outcomes),
        publication_authorized=bool(independent_evaluation_approval and not blockers),
        evaluation_status=evaluation_status,
        thresholds=thresholds,
        buckets={
            "cases_by_profile": _counter_bucket(cases_by_profile),
            "cases_by_category": _counter_bucket(cases_by_category),
            "outcomes_by_profile": _counter_bucket(outcomes_by_profile),
            "outcomes_by_category": _counter_bucket(outcomes_by_category),
            "facts_by_profile": _counter_bucket(facts_by_profile),
            "facts_by_knowledge_point": _counter_bucket(facts_by_kp),
            "adaptation_by_profile": _counter_bucket(adaptation_by_profile),
            "adaptation_by_resource_type": _counter_bucket(adaptation_by_resource),
            "coverage_by_knowledge_point": _counter_bucket(coverage_by_kp),
            "coverage_by_resource_type": _counter_bucket(coverage_by_resource),
        },
        generalization={
            "status": "not_claimed",
            "domain_id": benchmark.domain_id,
            "evidence_scope": "frozen_single_domain_m0",
            "required_before_claim": ["held_out_domain_cases", "岗位任务迁移案例", "独立复核"],
        },
        failure_case_ids=failure_case_ids,
        improvement_input=improvement_input,
        publication_blockers=tuple(blockers),
    )
