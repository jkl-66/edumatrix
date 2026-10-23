"""Hash-bound offline annotation and adjudication for the M4 evidence streams."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from typing import Any, Literal

from pydantic import ConfigDict, Field, model_validator

from app.m2_contracts import StrictModel
from app.m4_evaluation import (
    ADAPTATION_TARGET,
    COVERAGE_TARGET,
    HALLUCINATION_LIMIT,
    PROFILE_IDS,
)


TaskType = Literal["case_validity", "atomic_fact", "adaptation", "artifact_approval", "coverage"]
AnnotationStatus = Literal["final", "adjudicated"]


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class OfflineAnnotationTask(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["m4.annotation-task.v1"] = "m4.annotation-task.v1"
    task_id: str = Field(pattern=r"^(case|claim|adapt|approval|coverage):")
    task_type: TaskType
    subject_id: str = Field(min_length=1, max_length=256)
    payload: dict[str, Any]
    rubric: dict[str, Any]
    task_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def hash_matches_content(self) -> "OfflineAnnotationTask":
        body = self.model_dump(mode="json", exclude={"task_hash"})
        if content_hash(body) != self.task_hash:
            raise ValueError("annotation task hash mismatch")
        return self


class OfflineAnnotationRecord(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["m4.annotation-record.v1"] = "m4.annotation-record.v1"
    task_id: str
    task_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_type: TaskType
    annotator_ref: str = Field(min_length=3, max_length=128)
    status: AnnotationStatus
    labels: dict[str, Any]
    rationale: str = Field(min_length=3, max_length=4000)
    evidence_refs: tuple[str, ...] = Field(min_length=1)


def make_task(*, task_id: str, task_type: TaskType, subject_id: str, payload: dict[str, Any], rubric: dict[str, Any]) -> OfflineAnnotationTask:
    body = {
        "schema_version": "m4.annotation-task.v1",
        "task_id": task_id,
        "task_type": task_type,
        "subject_id": subject_id,
        "payload": payload,
        "rubric": rubric,
    }
    return OfflineAnnotationTask(**body, task_hash=content_hash(body))


def _require_exact_keys(labels: dict[str, Any], expected: set[str]) -> None:
    if set(labels) != expected:
        raise ValueError(f"annotation labels must contain exactly {sorted(expected)}")


def validate_annotation(task: OfflineAnnotationTask, record: OfflineAnnotationRecord) -> None:
    if record.task_id != task.task_id or record.task_hash != task.task_hash or record.task_type != task.task_type:
        raise ValueError("annotation record does not match its frozen task")
    labels = record.labels
    if task.task_type == "case_validity":
        _require_exact_keys(labels, {"validity", "failure_type"})
        if labels["validity"] not in {"valid", "invalid", "unknown"}:
            raise ValueError("invalid case validity label")
        if not isinstance(labels["failure_type"], str):
            raise ValueError("case failure_type must be a string")
    elif task.task_type == "atomic_fact":
        _require_exact_keys(labels, {"label"})
        if labels["label"] not in {"supported", "contradicted", "unsupported", "unknown", "non_factual"}:
            raise ValueError("invalid atomic fact label")
    elif task.task_type == "adaptation":
        keys = {
            "prerequisite_fit", "difficulty_fit", "format_fit", "scaffolding_fit",
            "assessment_fit", "factual_quality_passed",
        }
        _require_exact_keys(labels, keys)
        for key in keys - {"factual_quality_passed"}:
            if labels[key] not in {"fit", "partial", "unfit", "unknown"}:
                raise ValueError(f"invalid adaptation label: {key}")
        if not isinstance(labels["factual_quality_passed"], bool):
            raise ValueError("factual_quality_passed must be boolean")
    elif task.task_type == "artifact_approval":
        keys = {"semantic_quality_passed", "source_traceability_passed", "version_integrity_passed", "approved"}
        _require_exact_keys(labels, keys)
        if any(not isinstance(labels[key], bool) for key in keys):
            raise ValueError("artifact approval labels must be boolean")
        expected_approval = all(labels[key] for key in keys - {"approved"})
        if labels["approved"] is not expected_approval:
            raise ValueError("approved must equal the conjunction of approval gates")
    else:
        keys = {"substantial", "traceable_source_or_original", "semantic_review_passed", "artifact_approved"}
        _require_exact_keys(labels, keys)
        if any(not isinstance(labels[key], bool) for key in keys):
            raise ValueError("coverage labels must be boolean")


def annotation_signature(record: OfflineAnnotationRecord) -> str:
    labels = dict(record.labels)
    if record.task_type == "case_validity" and labels.get("validity") != "invalid":
        labels["failure_type"] = ""
    return canonical_json(labels)


def primary_category(record: OfflineAnnotationRecord) -> str:
    if record.task_type == "case_validity":
        return str(record.labels["validity"])
    if record.task_type == "atomic_fact":
        return str(record.labels["label"])
    return annotation_signature(record)


def nominal_kappa(left: list[str], right: list[str]) -> float | None:
    if len(left) != len(right) or not left:
        return None
    observed = sum(a == b for a, b in zip(left, right, strict=True)) / len(left)
    left_counts = Counter(left)
    right_counts = Counter(right)
    labels = set(left_counts) | set(right_counts)
    expected = sum((left_counts[label] / len(left)) * (right_counts[label] / len(right)) for label in labels)
    if expected == 1.0:
        return 1.0 if observed == 1.0 else None
    return round((observed - expected) / (1.0 - expected), 6)


def agreement_report(
    tasks: tuple[OfflineAnnotationTask, ...],
    first: tuple[OfflineAnnotationRecord, ...],
    second: tuple[OfflineAnnotationRecord, ...],
) -> dict[str, Any]:
    task_map = {task.task_id: task for task in tasks}
    first_map = {record.task_id: record for record in first}
    second_map = {record.task_id: record for record in second}
    if set(first_map) != set(task_map) or set(second_map) != set(task_map):
        raise ValueError("both annotators must complete every frozen task exactly once")
    if len(first_map) != len(first) or len(second_map) != len(second):
        raise ValueError("duplicate annotation task IDs are forbidden")
    if {record.annotator_ref for record in first} & {record.annotator_ref for record in second}:
        raise ValueError("independent annotation passes require distinct annotator refs")

    disagreements = []
    by_type: dict[str, list[tuple[str, str, str, str]]] = {
        kind: [] for kind in ("case_validity", "atomic_fact", "adaptation", "artifact_approval", "coverage")
    }
    for task_id, task in task_map.items():
        a, b = first_map[task_id], second_map[task_id]
        validate_annotation(task, a)
        validate_annotation(task, b)
        sa, sb = annotation_signature(a), annotation_signature(b)
        by_type[task.task_type].append((sa, sb, primary_category(a), primary_category(b)))
        if sa != sb:
            disagreements.append({
                "task_id": task_id,
                "task_hash": task.task_hash,
                "task_type": task.task_type,
                "subject_id": task.subject_id,
                "first_labels": a.labels,
                "second_labels": b.labels,
            })

    summaries = {}
    for task_type, pairs in by_type.items():
        same = sum(a == b for a, b, _ca, _cb in pairs)
        summaries[task_type] = {
            "count": len(pairs),
            "agreement_count": same,
            "agreement_rate": round(same / len(pairs) * 100, 4) if pairs else None,
            "cohen_kappa": nominal_kappa([ca for _a, _b, ca, _cb in pairs], [cb for _a, _b, _ca, cb in pairs]),
        }
    return {
        "schema_version": "m4.annotation-agreement.v1",
        "annotators": [first[0].annotator_ref, second[0].annotator_ref] if first else [],
        "task_count": len(tasks),
        "disagreement_count": len(disagreements),
        "by_type": summaries,
        "disagreements": disagreements,
    }


def resolve_annotations(
    tasks: tuple[OfflineAnnotationTask, ...],
    first: tuple[OfflineAnnotationRecord, ...],
    second: tuple[OfflineAnnotationRecord, ...],
    adjudications: tuple[OfflineAnnotationRecord, ...],
) -> tuple[OfflineAnnotationRecord, ...]:
    report = agreement_report(tasks, first, second)
    disagreements = {item["task_id"] for item in report["disagreements"]}
    adjudication_map = {record.task_id: record for record in adjudications}
    if set(adjudication_map) != disagreements or len(adjudication_map) != len(adjudications):
        raise ValueError("adjudication set must match the disagreement set exactly")
    task_map = {task.task_id: task for task in tasks}
    first_map = {record.task_id: record for record in first}
    second_map = {record.task_id: record for record in second}
    resolved = []
    for task in tasks:
        if task.task_id in disagreements:
            record = adjudication_map[task.task_id]
            if record.status != "adjudicated":
                raise ValueError("disagreement resolutions must use adjudicated status")
            validate_annotation(task, record)
            resolved.append(record)
        else:
            resolved.append(first_map[task.task_id])
            if annotation_signature(first_map[task.task_id]) != annotation_signature(second_map[task.task_id]):
                raise AssertionError("agreement report and resolution diverged")
    return tuple(resolved)


def calculate_offline_metrics(
    tasks: tuple[OfflineAnnotationTask, ...],
    resolved: tuple[OfflineAnnotationRecord, ...],
    *,
    method: str,
    human_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if len({task.task_id for task in tasks}) != len(tasks):
        raise ValueError("duplicate annotation task IDs are forbidden")
    task_map = {task.task_id: task for task in tasks}
    if len({record.task_id for record in resolved}) != len(resolved):
        raise ValueError("duplicate resolved annotation task IDs are forbidden")
    if {record.task_id for record in resolved} != set(task_map):
        raise ValueError("resolved annotations must cover every frozen task")
    labels_by_type: dict[str, list[dict[str, Any]]] = {
        kind: [] for kind in ("case_validity", "atomic_fact", "adaptation", "artifact_approval", "coverage")
    }
    coverage_ids = set()
    case_by_category: dict[str, Counter[str]] = defaultdict(Counter)
    case_by_profile: dict[str, Counter[str]] = defaultdict(Counter)
    adaptation_by_profile: dict[str, Counter[str]] = defaultdict(Counter)
    adaptation_by_resource: dict[str, Counter[str]] = defaultdict(Counter)
    coverage_by_kp: dict[str, Counter[str]] = defaultdict(Counter)
    coverage_by_resource: dict[str, Counter[str]] = defaultdict(Counter)
    execution_status = Counter()
    citation_count = 0
    locatable_citation_count = 0
    failure_case_ids: set[str] = set()
    for record in resolved:
        task = task_map[record.task_id]
        validate_annotation(task, record)
        labels_by_type[record.task_type].append(record.labels)
        if record.task_type == "coverage" and all(record.labels.values()):
            coverage_ids.add(task.subject_id)
        if record.task_type == "coverage":
            coverage_by_kp[task.subject_id]["valid" if all(record.labels.values()) else "invalid"] += 1
            coverage_by_resource[str(task.payload.get("resource_type", "mixed"))]["valid" if all(record.labels.values()) else "invalid"] += 1
        if record.task_type == "case_validity":
            category = str(task.payload.get("case", {}).get("category", "unknown"))
            case_by_category[category][str(record.labels["validity"])] += 1
            profile_id = str(task.payload.get("case", {}).get("profile_id", "unknown"))
            case_by_profile[profile_id][str(record.labels["validity"])] += 1
            response = task.payload.get("response", {})
            response_status = str(response.get("status", "unknown"))
            execution_status[response_status] += 1
            if response_status in {"failed", "timeout", "legal_refusal"}:
                failure_case_ids.add(task.subject_id)
            citation_count += int(response.get("citation_count", 0) or 0)
            locatable_citation_count += int(response.get("locatable_citation_count", 0) or 0)

    cases = Counter(item["validity"] for item in labels_by_type["case_validity"])
    facts = Counter(item["label"] for item in labels_by_type["atomic_fact"])
    judgeable = facts["supported"] + facts["contradicted"] + facts["unsupported"]
    hallucinated = facts["contradicted"] + facts["unsupported"]
    adaptations = labels_by_type["adaptation"]
    adaptation_passed = 0
    for record in resolved:
        if record.task_type != "adaptation":
            continue
        item = record.labels
        passed = (
            item["factual_quality_passed"]
            and item["difficulty_fit"] == "fit"
            and item["assessment_fit"] == "fit"
            and "unfit" not in (item["prerequisite_fit"], item["format_fit"], item["scaffolding_fit"])
        )
        adaptation_passed += passed
        task = task_map[record.task_id]
        adaptation_by_profile[str(task.payload.get("profile_id", "unknown"))]["passed" if passed else "failed"] += 1
        adaptation_by_resource[str(task.payload.get("artifact_type", task.payload.get("resource_type", "unknown")))]["passed" if passed else "failed"] += 1

    def metric(numerator: int, denominator: int) -> dict[str, Any]:
        return {
            "numerator": numerator,
            "denominator": denominator,
            "percent": round(numerator / denominator * 100, 4) if denominator else None,
        }

    blockers = []
    if sum(cases.values()) != 60:
        blockers.append("case_annotation_count_not_60")
    if cases.total() and len(labels_by_type["atomic_fact"]) < cases.total():
        blockers.append("fewer_than_one_claim_per_case")
    if judgeable == 0:
        blockers.append("no_judgeable_atomic_facts")
    if len(adaptations) != 9:
        blockers.append("adaptation_resource_count_not_9")
    if len(labels_by_type["coverage"]) != 32:
        blockers.append("coverage_denominator_not_32")
    if set(case_by_profile) != set(PROFILE_IDS):
        blockers.append("all_three_profiles_not_annotated")
    if method != "two_independent_human_annotators" or human_validation is None:
        blockers.append("independent_human_validation_missing")
    else:
        if human_validation.get("schema_version") != "m4.human-validation.v1":
            blockers.append("human_validation_manifest_invalid")
        if human_validation.get("completed") is not True:
            blockers.append("human_validation_incomplete")
        if not str(human_validation.get("attestation", "")).strip():
            blockers.append("human_validation_attestation_missing")
        reviewer_refs = tuple(human_validation.get("annotator_refs") or ())
        if len(reviewer_refs) != 2 or len(set(reviewer_refs)) != 2:
            blockers.append("independent_human_reviewer_count_insufficient")
        if human_validation.get("agreement_verified") is not True:
            blockers.append("human_agreement_not_verified")
        if any(
            str(value).strip().lower().startswith(("ai-", "deepseek-"))
            for value in reviewer_refs
        ):
            blockers.append("human_reviewer_identity_not_independent")
        adjudicator_ref = str(human_validation.get("adjudicator_ref") or "").strip().lower()
        if adjudicator_ref.startswith(("ai-", "deepseek-")):
            blockers.append("human_adjudicator_identity_not_independent")
    hallucination = metric(hallucinated, judgeable)
    adaptation = metric(adaptation_passed, len(adaptations))
    coverage = metric(len(coverage_ids), 32)
    thresholds = {
        "hallucination_rate": {
            "operator": "<", "target_percent": HALLUCINATION_LIMIT,
            "actual_percent": hallucination["percent"],
            "passed": hallucination["percent"] is not None and hallucination["percent"] < HALLUCINATION_LIMIT,
        },
        "adaptation_accuracy": {
            "operator": ">=", "target_percent": ADAPTATION_TARGET,
            "actual_percent": adaptation["percent"],
            "passed": adaptation["percent"] is not None and adaptation["percent"] >= ADAPTATION_TARGET,
        },
        "core_coverage": {
            "operator": ">=", "target_percent": COVERAGE_TARGET, "minimum_valid_points": 29,
            "actual_percent": coverage["percent"],
            "passed": coverage["numerator"] >= 29 and coverage["denominator"] == 32,
        },
    }
    for metric_name, threshold in thresholds.items():
        if not threshold["passed"]:
            blockers.append(f"{metric_name}_threshold_not_met")
    feedback = {
        "schema_version": "m4.improvement-input.v1",
        "profile_ids": list(PROFILE_IDS),
        "failed_case_ids": sorted(failure_case_ids),
        "uncovered_knowledge_point_ids": [f"KP-{index:02d}" for index in range(1, 33) if f"KP-{index:02d}" not in coverage_ids],
        "failed_resource_ids": sorted(
            str(task_map[record.task_id].subject_id) for record in resolved
            if record.task_type == "adaptation" and not (
                record.labels["factual_quality_passed"]
                and record.labels["difficulty_fit"] == "fit"
                and record.labels["assessment_fit"] == "fit"
                and "unfit" not in (record.labels["prerequisite_fit"], record.labels["format_fit"], record.labels["scaffolding_fit"])
            )
        ),
        "write_target": "versioned_improvement_input_only",
        "canonical_profile_or_mastery_write": False,
        "learning_event_write": False,
    }
    hard_blockers = [item for item in blockers if not item.endswith("_threshold_not_met")]
    evaluation_status = "blocked" if hard_blockers else ("needs_improvement" if blockers else "qualified")
    publication_authorized = (
        evaluation_status == "qualified"
        and human_validation is not None
        and human_validation.get("completed") is True
    )
    return {
        "schema_version": "m4.offline-metric-report.v1",
        "evaluation_method": method,
        "publication_authorized": publication_authorized,
        "human_validation": human_validation or {
            "schema_version": "m4.human-validation.v1",
            "completed": False,
            "annotator_refs": [],
            "agreement_verified": False,
        },
        "case_validity": {
            **metric(cases["valid"], sum(cases.values())), "distribution": dict(cases),
            "by_category": {key: dict(value) for key, value in sorted(case_by_category.items())},
        },
        "hallucination_rate": {**hallucination, "label_distribution": dict(facts)},
        "adaptation_accuracy": {
            **adaptation,
            "by_profile": {key: dict(value) for key, value in sorted(adaptation_by_profile.items())},
            "by_resource_type": {key: dict(value) for key, value in sorted(adaptation_by_resource.items())},
        },
        "core_coverage": {
            **coverage, "covered_ids": sorted(coverage_ids),
            "by_knowledge_point": {key: dict(value) for key, value in sorted(coverage_by_kp.items())},
            "by_resource_type": {key: dict(value) for key, value in sorted(coverage_by_resource.items())},
        },
        "auxiliary_metrics": {
            "execution_status": dict(execution_status),
            "task_completion_rate": metric(execution_status["completed"], sum(execution_status.values())),
            "citation_locatability": metric(locatable_citation_count, citation_count),
            "unknown_fact_rate": metric(facts["unknown"], sum(facts.values())),
        },
        "domain_id": "domain-rag-0.1",
        "profile_ids": list(PROFILE_IDS),
        "thresholds": thresholds,
        "generalization": {
            "status": "not_claimed",
            "domain_id": "domain-rag-0.1",
            "evidence_scope": "frozen_single_domain_m0",
            "required_before_claim": ["held_out_domain_cases", "岗位任务迁移案例", "独立复核"],
        },
        "evaluation_status": evaluation_status,
        "failure_case_ids": sorted(failure_case_ids),
        "buckets": {
            "case_by_profile": {key: dict(value) for key, value in sorted(case_by_profile.items())},
            "case_by_category": {key: dict(value) for key, value in sorted(case_by_category.items())},
        },
        "improvement_input": feedback,
        "interpretation_limits": [
            "same configured model family produced and evaluated the outputs",
            "isolated passes reduce order leakage but do not provide cross-model or human independence",
            "structured generation required explicit source citations and may make this benchmark easier than open-ended production traffic",
            "adaptation denominator contains 9 frozen M3 resources for one shared RAG task",
            "coverage denominator uses the compact project-original M0 course plus frozen assessments, not a semester-scale external curriculum",
        ],
        "publication_blockers": blockers,
    }
