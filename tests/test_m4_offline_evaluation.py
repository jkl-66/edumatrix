from __future__ import annotations

import pytest

from app.m4_offline_evaluation import (
    OfflineAnnotationRecord,
    agreement_report,
    calculate_offline_metrics,
    make_task,
    resolve_annotations,
)
from scripts.m4_annotation_workflow import _annotation_prompt, _exclusive_output_lock


def _record(task, annotator, labels, *, status="final"):
    return OfflineAnnotationRecord(
        task_id=task.task_id,
        task_hash=task.task_hash,
        task_type=task.task_type,
        annotator_ref=annotator,
        status=status,
        labels=labels,
        rationale="evidence-based review",
        evidence_refs=(task.subject_id,),
    )


def _tasks():
    return (
        make_task(task_id="case:M0-K01", task_type="case_validity", subject_id="M0-K01", payload={}, rubric={}),
        make_task(task_id="claim:M0-K01:c1", task_type="atomic_fact", subject_id="M0-K01:c1", payload={}, rubric={}),
        make_task(task_id="adapt:artifact-1", task_type="adaptation", subject_id="artifact-1", payload={}, rubric={}),
        make_task(task_id="coverage:KP-01", task_type="coverage", subject_id="KP-01", payload={}, rubric={}),
    )


def test_offline_double_annotation_requires_exact_tasks_and_distinct_annotators():
    tasks = _tasks()
    labels = (
        {"validity": "valid", "failure_type": ""},
        {"label": "supported"},
        {
            "prerequisite_fit": "fit", "difficulty_fit": "fit", "format_fit": "fit",
            "scaffolding_fit": "fit", "assessment_fit": "fit", "factual_quality_passed": True,
        },
        {
            "substantial": True, "traceable_source_or_original": True,
            "semantic_review_passed": True, "artifact_approved": True,
        },
    )
    first = tuple(_record(task, "ai-pass-a", label) for task, label in zip(tasks, labels, strict=True))
    second = tuple(_record(task, "ai-pass-b", label) for task, label in zip(tasks, labels, strict=True))
    report = agreement_report(tasks, first, second)
    assert report["disagreement_count"] == 0
    assert report["by_type"]["atomic_fact"]["cohen_kappa"] == 1.0

    with pytest.raises(ValueError, match="distinct"):
        agreement_report(tasks, first, tuple(_record(task, "ai-pass-a", label) for task, label in zip(tasks, labels, strict=True)))


def test_offline_disagreement_requires_exact_adjudication_set():
    tasks = _tasks()[:2]
    first = (
        _record(tasks[0], "ai-pass-a", {"validity": "valid", "failure_type": ""}),
        _record(tasks[1], "ai-pass-a", {"label": "supported"}),
    )
    second = (
        _record(tasks[0], "ai-pass-b", {"validity": "valid", "failure_type": ""}),
        _record(tasks[1], "ai-pass-b", {"label": "unsupported"}),
    )
    report = agreement_report(tasks, first, second)
    assert [item["task_id"] for item in report["disagreements"]] == [tasks[1].task_id]
    adjudication = (_record(tasks[1], "ai-adjudicator", {"label": "supported"}, status="adjudicated"),)
    resolved = resolve_annotations(tasks, first, second, adjudication)
    assert [item.labels for item in resolved] == [first[0].labels, adjudication[0].labels]

    with pytest.raises(ValueError, match="exactly"):
        resolve_annotations(tasks, first, second, ())


def test_valid_case_failure_description_does_not_create_false_disagreement():
    task = make_task(task_id="case:M0-K01", task_type="case_validity", subject_id="M0-K01", payload={}, rubric={})
    first = (_record(task, "ai-pass-a", {"validity": "valid", "failure_type": "none"}),)
    second = (_record(task, "ai-pass-b", {"validity": "valid", "failure_type": ""}),)
    report = agreement_report((task,), first, second)
    assert report["disagreement_count"] == 0
    assert report["by_type"]["case_validity"]["cohen_kappa"] == 1.0


def test_offline_metrics_keep_ai_review_unpublished_and_preserve_denominators():
    tasks = []
    records = []
    for index in range(60):
        task = make_task(task_id=f"case:M0-X{index:02d}", task_type="case_validity", subject_id=f"M0-X{index:02d}", payload={}, rubric={})
        tasks.append(task)
        records.append(_record(task, "ai-adjudicator", {"validity": "valid" if index < 55 else "invalid", "failure_type": ""}, status="adjudicated"))
    for index, label in enumerate(("supported", "supported", "unsupported", "non_factual")):
        task = make_task(task_id=f"claim:M0-X00:c{index}", task_type="atomic_fact", subject_id=f"claim-{index}", payload={}, rubric={})
        tasks.append(task)
        records.append(_record(task, "ai-adjudicator", {"label": label}, status="adjudicated"))
    adaptation_labels = {
        "prerequisite_fit": "fit", "difficulty_fit": "fit", "format_fit": "fit",
        "scaffolding_fit": "fit", "assessment_fit": "fit", "factual_quality_passed": True,
    }
    for index in range(9):
        task = make_task(task_id=f"adapt:artifact-{index}", task_type="adaptation", subject_id=f"artifact-{index}", payload={}, rubric={})
        tasks.append(task)
        records.append(_record(task, "ai-adjudicator", adaptation_labels, status="adjudicated"))
    coverage_labels = {
        "substantial": True, "traceable_source_or_original": True,
        "semantic_review_passed": True, "artifact_approved": True,
    }
    for index in range(32):
        task = make_task(task_id=f"coverage:KP-{index + 1:02d}", task_type="coverage", subject_id=f"KP-{index + 1:02d}", payload={}, rubric={})
        tasks.append(task)
        records.append(_record(task, "ai-adjudicator", coverage_labels, status="adjudicated"))

    report = calculate_offline_metrics(tuple(tasks), tuple(records), method="two_isolated_ai_passes_with_ai_adjudication")
    assert report["case_validity"]["numerator"] == 55
    assert report["hallucination_rate"]["numerator"] == 1
    assert report["hallucination_rate"]["denominator"] == 3
    assert report["hallucination_rate"]["percent"] == 33.3333
    assert report["hallucination_rate"]["label_distribution"] == {
        "supported": 2, "unsupported": 1, "non_factual": 1,
    }
    assert report["adaptation_accuracy"]["denominator"] == 9
    assert report["core_coverage"]["denominator"] == 32
    assert report["publication_authorized"] is False
    assert "independent_human_validation_missing" in report["publication_blockers"]


def test_annotation_output_lock_rejects_concurrent_writer(tmp_path):
    output = tmp_path / "annotations.jsonl"
    with _exclusive_output_lock(output):
        with pytest.raises(RuntimeError, match="already locked"):
            with _exclusive_output_lock(output):
                pass
    assert not output.with_suffix(".jsonl.lock").exists()


def test_artifact_approval_requires_conjunction():
    task = make_task(task_id="approval:artifact-1", task_type="artifact_approval", subject_id="artifact-1", payload={}, rubric={})
    valid = _record(task, "ai-pass-a", {
        "semantic_quality_passed": True, "source_traceability_passed": True,
        "version_integrity_passed": True, "approved": True,
    })
    agreement_report((task,), (valid,), (_record(task, "ai-pass-b", valid.labels),))
    invalid = valid.model_copy(update={"labels": {**valid.labels, "semantic_quality_passed": False}})
    with pytest.raises(ValueError, match="conjunction"):
        agreement_report((task,), (invalid,), (_record(task, "ai-pass-b", invalid.labels),))


@pytest.mark.parametrize("task_id,task_type", [
    ("case:M0-K01", "case_validity"),
    ("claim:M0-K01:c1", "atomic_fact"),
    ("adapt:artifact-1", "adaptation"),
    ("approval:artifact-1", "artifact_approval"),
    ("coverage:KP-01", "coverage"),
])
def test_every_offline_task_type_has_a_strict_prompt_example(task_id, task_type):
    task = make_task(task_id=task_id, task_type=task_type, subject_id="subject", payload={}, rubric={})
    system, prompt = _annotation_prompt([task], annotator_ref="ai-pass-a", status="final")
    assert "exactly these keys" in system
    assert task_id in prompt
