from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.m4_evaluation import (
    AdaptationAnnotation,
    AtomicFactAnnotation,
    CaseOutcome,
    CoverageAnnotation,
    calculate_metric_report,
    load_frozen_benchmark,
    M4EvaluationError,
)
from app.m4_executor import M4RealModelExecutor
from app.m4_offline_evaluation import (
    OfflineAnnotationRecord,
    agreement_report,
    calculate_offline_metrics,
    make_task,
)
from scripts.m4_annotation_workflow import (
    _annotation_prompt,
    _load_human_validation_manifest,
    report as annotation_report,
)
from scripts.run_m4_real_evaluation import _assert_real_model_policy
from tests.test_m4_executor import _M4LLM, _case, _session


PROFILE_IDS = (
    "profile-m0-beginner",
    "profile-m0-theory",
    "profile-m0-advanced",
)


def _record(task, labels, *, annotator="human-a", status="final"):
    return OfflineAnnotationRecord(
        task_id=task.task_id,
        task_hash=task.task_hash,
        task_type=task.task_type,
        annotator_ref=annotator,
        status=status,
        labels=labels,
        rationale="独立标注依据冻结案例和资源证据",
        evidence_refs=(task.subject_id,),
    )


def _real_policy_config(**overrides):
    values = {
        "llm_model": "deepseek-v4-flash",
        "llm_thinking_mode": "max",
        "llm_reasoning_effort": "max",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _real_policy_backend(class_name="AsyncOpenAIChatLLM", **overrides):
    values = {
        "model": "deepseek-v4-flash",
        "thinking_mode": "max",
        "reasoning_effort": "max",
    }
    values.update(overrides)
    return type(class_name, (), values)()


def test_b04_real_runner_accepts_only_exact_deepseek_max_policy(monkeypatch):
    monkeypatch.setenv("EDUMATRIX_ALLOW_LLM_FALLBACK", "0")
    _assert_real_model_policy(_real_policy_config(), _real_policy_backend())


@pytest.mark.parametrize(
    ("config_overrides", "backend_overrides", "message"),
    [
        ({"llm_model": "deepseek-chat"}, {}, "deepseek-v4-flash"),
        ({}, {"model": "deepseek-chat"}, "deepseek-v4-flash"),
        ({"llm_thinking_mode": "enabled"}, {}, "THINKING_MODE=max"),
        ({"llm_reasoning_effort": "high"}, {}, "reasoning_effort=max"),
        ({}, {"thinking_mode": "enabled"}, "thinking_mode=max"),
        ({}, {"reasoning_effort": "high"}, "reasoning_effort=max"),
    ],
)
def test_b04_real_runner_rejects_model_or_reasoning_drift(
    monkeypatch, config_overrides, backend_overrides, message,
):
    monkeypatch.setenv("EDUMATRIX_ALLOW_LLM_FALLBACK", "0")
    with pytest.raises(RuntimeError, match=message):
        _assert_real_model_policy(
            _real_policy_config(**config_overrides),
            _real_policy_backend(**backend_overrides),
        )


def test_b04_real_runner_rejects_enabled_fallback(monkeypatch):
    monkeypatch.setenv("EDUMATRIX_ALLOW_LLM_FALLBACK", "1")
    with pytest.raises(RuntimeError, match="allow_fallback=false"):
        _assert_real_model_policy(_real_policy_config(), _real_policy_backend())


@pytest.mark.parametrize("class_name", ["FallbackAsyncLLMWrapper", "AsyncDeterministicEducationLLM"])
def test_b04_real_runner_rejects_non_real_backend(monkeypatch, class_name):
    monkeypatch.setenv("EDUMATRIX_ALLOW_LLM_FALLBACK", "0")
    with pytest.raises(RuntimeError, match="forbids fallback and deterministic"):
        _assert_real_model_policy(_real_policy_config(), _real_policy_backend(class_name))


def test_b04_freezes_domain_three_profiles_and_blind_case_contract():
    benchmark = load_frozen_benchmark()

    assert benchmark.domain_id == "domain-rag-0.1"
    assert benchmark.course_id == "course-rag-engineering-m0"
    assert benchmark.profile_ids == PROFILE_IDS
    assert len(benchmark.cases) == 60
    assert len(benchmark.core_knowledge_point_ids) == 32
    assert all("gold" not in case and "failure_branch" not in case for case in benchmark.blind_cases())


def test_b04_annotation_prompt_withholds_hidden_gold_and_failure_branch():
    task = make_task(
        task_id="claim:M0-X01:c1",
        task_type="atomic_fact",
        subject_id="M0-X01:c1",
        payload={
            "claim": {"text": "公开 claim"},
            "gold": "隐藏金标",
            "failure_branch": "隐藏失败分支",
            "nested": {"failure_branch": "仍然隐藏", "excerpt": "公开来源片段"},
        },
        rubric={},
    )
    _system, prompt = _annotation_prompt([task], annotator_ref="human-a", status="final")
    outbound = json.loads(prompt)
    serialized = json.dumps(outbound, ensure_ascii=False)
    assert "隐藏金标" not in serialized
    assert "隐藏失败分支" not in serialized
    assert "仍然隐藏" not in serialized
    assert "公开来源片段" in serialized


def test_b04_structured_case_evidence_links_profile_and_source_snapshots():
    llm = _M4LLM()
    engine, session = _session()
    try:
        output = __import__("asyncio").run(M4RealModelExecutor(
            llm,
            sources=({"source_ref_id": "ref-allowed", "title": "course", "excerpt": "source"},),
            session=session,
            trace_id="m4-b04-snapshot-link",
        ).execute(_case()))
        context = output.evidence["evaluation_context"]
        assert context["domain_id"] == "domain-rag-0.1"
        assert context["course_id"] == "course-rag-engineering-m0"
        assert context["profile_snapshot"]["profile_id"] == "profile-m0-beginner"
        assert context["profile_snapshot"]["id"].startswith("baseline-profile-0.1:")
        assert context["source_snapshot"]["case_version"] == "evaluation-case-m0-0.1"
        assert context["source_snapshot"]["course_manifest_sha256"]
    finally:
        session.close()
        engine.dispose()


def test_b04_metric_report_keeps_failure_denominators_buckets_and_feedback():
    benchmark = load_frozen_benchmark()
    outcomes = tuple(
        CaseOutcome(
            case_id=case.case_id,
            status=("failed" if index == 5 else "timeout" if index == 6 else "legal_refusal" if index == 7 else "completed"),
            citation_count=1,
            locatable_citation_count=1,
        )
        for index, case in enumerate(benchmark.cases)
    )
    facts = tuple(
        AtomicFactAnnotation(
            case_id=case.case_id,
            claim_id=f"claim-{index}",
            label=("unsupported" if index == 0 else "supported"),
            annotator_ref="human-a",
            status="final",
        )
        for index, case in enumerate(benchmark.cases[:31])
    )
    adaptations = tuple(
        AdaptationAnnotation(
            case_id=f"resource-{index}",
            resource_id=f"resource-{index}",
            resource_type=("lesson", "lab_guide", "tiered_quiz")[index % 3],
            profile_id=PROFILE_IDS[index % 3],
            prerequisite_fit="fit",
            difficulty_fit="fit" if index != 19 else "partial",
            format_fit="partial",
            scaffolding_fit="fit",
            assessment_fit="fit",
            factual_quality_passed=True,
            annotator_ref="human-a",
            status="final",
        )
        for index in range(20)
    )
    coverage = tuple(
        CoverageAnnotation(
            knowledge_point_id=f"KP-{index:02d}",
            resource_type=("lesson", "lab_guide", "tiered_quiz", "resource_bundle")[index % 4],
            artifact_version_id=f"artifact-{index}",
            substantial=index <= 29,
            traceable_source_or_original=index <= 29,
            semantic_review_passed=index <= 29,
            artifact_approved=index <= 29,
            annotator_ref="human-a",
            status="final",
        )
        for index in range(1, 33)
    )

    report = calculate_metric_report(
        benchmark,
        outcomes=outcomes,
        fact_annotations=facts,
        adaptation_annotations=adaptations,
        coverage_annotations=coverage,
    )

    assert report.hallucination_rate.percent == 3.2258
    assert report.adaptation_accuracy.percent == 95.0
    assert report.core_coverage.numerator == 29
    assert report.thresholds["hallucination_rate"]["passed"] is True
    assert report.thresholds["adaptation_accuracy"]["passed"] is True
    assert report.thresholds["core_coverage"]["passed"] is True
    assert report.generalization["status"] == "not_claimed"
    assert "held_out_domain_cases" in report.generalization["required_before_claim"]
    assert report.evaluation_status == "blocked"  # independent approval is intentionally absent
    assert report.failure_case_ids == ("M0-K06", "M0-K07", "M0-K08")
    assert set(report.buckets["cases_by_profile"]) == set(PROFILE_IDS)
    assert set(report.buckets["adaptation_by_profile"]) == set(PROFILE_IDS)
    assert report.improvement_input["canonical_profile_or_mastery_write"] is False
    assert report.improvement_input["learning_event_write"] is False


def test_b04_rejects_duplicate_claim_resource_and_coverage_annotations():
    benchmark = load_frozen_benchmark()
    fact = AtomicFactAnnotation(case_id="M0-K01", claim_id="same", label="supported", annotator_ref="a", status="final")
    with pytest.raises(M4EvaluationError, match="case/claim pair"):
        calculate_metric_report(
            benchmark,
            outcomes=(),
            fact_annotations=(fact, fact),
            adaptation_annotations=(),
            coverage_annotations=(),
        )

    adaptation = AdaptationAnnotation(
        case_id="resource", resource_id="same", resource_type="lesson", profile_id=PROFILE_IDS[0],
        prerequisite_fit="fit", difficulty_fit="fit", format_fit="fit", scaffolding_fit="fit",
        assessment_fit="fit", factual_quality_passed=True, annotator_ref="a", status="final",
    )
    with pytest.raises(M4EvaluationError, match="resource instance"):
        calculate_metric_report(
            benchmark,
            outcomes=(),
            fact_annotations=(),
            adaptation_annotations=(adaptation, adaptation),
            coverage_annotations=(),
        )

    coverage = CoverageAnnotation(
        knowledge_point_id="KP-01", resource_type="lesson", artifact_version_id="av-1",
        substantial=True, traceable_source_or_original=True, semantic_review_passed=True,
        artifact_approved=True, annotator_ref="a", status="final",
    )
    with pytest.raises(M4EvaluationError, match="core knowledge point"):
        calculate_metric_report(
            benchmark,
            outcomes=(),
            fact_annotations=(),
            adaptation_annotations=(),
            coverage_annotations=(coverage, coverage),
        )


def test_b04_offline_metrics_preserve_failures_and_versioned_feedback():
    tasks = []
    records = []
    for index in range(60):
        case_id = f"M0-X{index:02d}"
        task = make_task(
            task_id=f"case:{case_id}",
            task_type="case_validity",
            subject_id=case_id,
            payload={
                "case": {"category": "profile_adaptation", "profile_id": PROFILE_IDS[index % 3]},
                "response": {"status": "failed" if index == 4 else "completed", "citation_count": 1, "locatable_citation_count": 1},
            },
            rubric={},
        )
        tasks.append(task)
        records.append(_record(task, {"validity": "valid", "failure_type": ""}))
    for index, label in enumerate(["unsupported", *(["supported"] * 20)]):
        task = make_task(
            task_id=f"claim:M0-X00:c{index}", task_type="atomic_fact", subject_id=f"claim-{index}", payload={}, rubric={},
        )
        tasks.append(task)
        records.append(_record(task, {"label": label}))
    adaptation_labels = {
        "prerequisite_fit": "fit", "difficulty_fit": "fit", "format_fit": "fit",
        "scaffolding_fit": "fit", "assessment_fit": "fit", "factual_quality_passed": True,
    }
    for index in range(9):
        task = make_task(
            task_id=f"adapt:artifact-{index}", task_type="adaptation", subject_id=f"artifact-{index}",
            payload={"profile_id": PROFILE_IDS[index % 3], "artifact_type": ("lesson", "lab_guide", "tiered_quiz")[index % 3]}, rubric={},
        )
        tasks.append(task)
        records.append(_record(task, adaptation_labels))
    for index in range(1, 33):
        task = make_task(
            task_id=f"coverage:KP-{index:02d}", task_type="coverage", subject_id=f"KP-{index:02d}",
            payload={"resource_type": "lesson"}, rubric={},
        )
        tasks.append(task)
        records.append(_record(task, {
            "substantial": index <= 29,
            "traceable_source_or_original": index <= 29,
            "semantic_review_passed": index <= 29,
            "artifact_approved": index <= 29,
        }))

    report = calculate_offline_metrics(tuple(tasks), tuple(records), method="two_independent_human_annotators")

    assert report["domain_id"] == "domain-rag-0.1"
    assert report["profile_ids"] == list(PROFILE_IDS)
    assert report["failure_case_ids"] == ["M0-X04"]
    assert report["core_coverage"]["numerator"] == 29
    assert report["thresholds"]["core_coverage"]["passed"] is True
    assert report["generalization"]["status"] == "not_claimed"
    assert report["improvement_input"]["canonical_profile_or_mastery_write"] is False
    assert report["buckets"]["case_by_profile"]
    assert report["publication_authorized"] is False


def test_b04_complete_human_validation_manifest_is_the_only_publication_path():
    tasks = []
    records = []
    for index in range(60):
        case_id = f"M0-H{index:02d}"
        task = make_task(
            task_id=f"case:{case_id}",
            task_type="case_validity",
            subject_id=case_id,
            payload={
                "case": {"category": "knowledge_accuracy", "profile_id": PROFILE_IDS[index % 3]},
                "response": {"status": "completed", "citation_count": 1, "locatable_citation_count": 1},
            },
            rubric={},
        )
        tasks.append(task)
        records.append(_record(task, {"validity": "valid", "failure_type": ""}))
        claim = make_task(
            task_id=f"claim:{case_id}:c1",
            task_type="atomic_fact",
            subject_id=f"{case_id}:c1",
            payload={},
            rubric={},
        )
        tasks.append(claim)
        records.append(_record(claim, {"label": "supported"}))

    for index in range(9):
        task = make_task(
            task_id=f"adapt:human-resource-{index}",
            task_type="adaptation",
            subject_id=f"human-resource-{index}",
            payload={
                "profile_id": PROFILE_IDS[index % 3],
                "artifact_type": ("lesson", "lab_guide", "tiered_quiz")[index % 3],
            },
            rubric={},
        )
        tasks.append(task)
        records.append(_record(task, {
            "prerequisite_fit": "fit", "difficulty_fit": "fit", "format_fit": "fit",
            "scaffolding_fit": "fit", "assessment_fit": "fit", "factual_quality_passed": True,
        }))

    for index in range(1, 33):
        task = make_task(
            task_id=f"coverage:KP-{index:02d}",
            task_type="coverage",
            subject_id=f"KP-{index:02d}",
            payload={"resource_type": "lesson"},
            rubric={},
        )
        tasks.append(task)
        records.append(_record(task, {
            "substantial": True, "traceable_source_or_original": True,
            "semantic_review_passed": True, "artifact_approved": True,
        }))

    human_validation = {
        "schema_version": "m4.human-validation.v1",
        "completed": True,
        "annotator_refs": ["human-reviewer-a", "human-reviewer-b"],
        "agreement_verified": True,
        "attestation": "two independent reviewers completed the frozen task set",
    }
    report = calculate_offline_metrics(
        tuple(tasks),
        tuple(records),
        method="two_independent_human_annotators",
        human_validation=human_validation,
    )

    assert report["evaluation_status"] == "qualified"
    assert report["publication_authorized"] is True
    assert report["human_validation"]["annotator_refs"] == ["human-reviewer-a", "human-reviewer-b"]

    blocked = calculate_offline_metrics(
        tuple(tasks),
        tuple(records),
        method="two_independent_human_annotators",
    )
    assert blocked["evaluation_status"] == "blocked"
    assert blocked["publication_authorized"] is False
    assert "independent_human_validation_missing" in blocked["publication_blockers"]


def test_b04_human_validation_manifest_binds_real_reviewer_refs(tmp_path):
    task = make_task(
        task_id="case:M0-HUMAN",
        task_type="case_validity",
        subject_id="M0-HUMAN",
        payload={},
        rubric={},
    )
    first = (_record(task, {"validity": "valid", "failure_type": ""}, annotator="reviewer-a"),)
    second = (_record(task, {"validity": "valid", "failure_type": ""}, annotator="reviewer-b"),)
    agreement = agreement_report((task,), first, second)
    manifest_path = tmp_path / "human-validation.json"
    manifest_path.write_text(json.dumps({
        "schema_version": "m4.human-validation.v1",
        "completed": True,
        "annotator_refs": ["reviewer-a", "reviewer-b"],
        "attestation": "two independent reviewers completed the frozen task set",
    }), encoding="utf-8")

    evidence = _load_human_validation_manifest(manifest_path, agreement, first, second, ())
    assert evidence["agreement_verified"] is True
    assert evidence["annotator_refs"] == ["reviewer-a", "reviewer-b"]

    manifest_path.write_text(json.dumps({
        "schema_version": "m4.human-validation.v1",
        "completed": True,
        "annotator_refs": ["deepseek-annotator-a-v1", "reviewer-b"],
        "attestation": "not human evidence",
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="AI annotator refs"):
        _load_human_validation_manifest(manifest_path, agreement, first, second, ())


def test_b04_human_report_entrypoint_keeps_incomplete_fixture_blocked(tmp_path):
    task = make_task(
        task_id="case:M0-HUMAN-CLI",
        task_type="case_validity",
        subject_id="M0-HUMAN-CLI",
        payload={},
        rubric={},
    )
    first = _record(task, {"validity": "valid", "failure_type": ""}, annotator="reviewer-a")
    second = _record(task, {"validity": "valid", "failure_type": ""}, annotator="reviewer-b")
    tasks_path = tmp_path / "tasks.jsonl"
    first_path = tmp_path / "first.jsonl"
    second_path = tmp_path / "second.jsonl"
    adjudications_path = tmp_path / "adjudications.jsonl"
    manifest_path = tmp_path / "human-validation.json"
    output_path = tmp_path / "report"
    tasks_path.write_text(json.dumps(task.model_dump(mode="json"), ensure_ascii=False) + "\n", encoding="utf-8")
    first_path.write_text(json.dumps(first.model_dump(mode="json"), ensure_ascii=False) + "\n", encoding="utf-8")
    second_path.write_text(json.dumps(second.model_dump(mode="json"), ensure_ascii=False) + "\n", encoding="utf-8")
    adjudications_path.write_text("", encoding="utf-8")
    manifest_path.write_text(json.dumps({
        "schema_version": "m4.human-validation.v1",
        "completed": True,
        "annotator_refs": ["reviewer-a", "reviewer-b"],
        "attestation": "two independent reviewers completed the frozen task set",
    }), encoding="utf-8")

    assert annotation_report(SimpleNamespace(
        tasks=tasks_path,
        first=first_path,
        second=second_path,
        adjudications=adjudications_path,
        output=output_path,
        method="two_independent_human_annotators",
        human_validation_manifest=manifest_path,
    )) == 0
    report = json.loads((output_path / "metrics.json").read_text(encoding="utf-8"))
    assert report["evaluation_method"] == "two_independent_human_annotators"
    assert report["human_validation"]["agreement_verified"] is True
    assert report["evaluation_status"] == "blocked"
    assert report["publication_authorized"] is False


def test_b03_b04_joint_closure_binds_profile_content_and_keeps_ai_report_blocked():
    root = Path(__file__).resolve().parents[1]
    evidence_path = (
        root
        / "outputs"
        / "原系统融合重构执行"
        / "evidence"
        / "acceptance_feedback"
        / "P1-B04"
        / "B03-B04_joint_closure.json"
    )
    assert evidence_path.is_file()
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert evidence["model_policy"] == {
        "provider": "openai-compatible DeepSeek",
        "model": "deepseek-v4-flash",
        "thinking": "enabled",
        "reasoning_effort": "max",
        "allow_fallback": False,
    }
    lineage = evidence["b03_to_b04_lineage"]
    assert lineage["three_profile_count"] == 3
    assert lineage["frozen_profile_snapshots_are_input_to_resources"] is True
    for profile in lineage["profile_resource_records"]:
        resources = profile["resources"]
        assert set(resources) == {"lesson", "lab_guide", "tiered_quiz"}
        assert all(item["profile_snapshot_id"] for item in resources.values())
        assert all(item["source_ref_ids"] for item in resources.values())
    beginner = next(
        item for item in lineage["profile_resource_records"]
        if item["owner_public_id"] == "usr-m3-gold-beginner-v1"
    )
    theory = next(
        item for item in lineage["profile_resource_records"]
        if item["owner_public_id"] == "usr-m3-gold-theory-v1"
    )
    assert beginner["resources"]["lab_guide"]["step_count"] >= 4
    assert beginner["resources"]["lab_guide"]["runnable_step_count"] == beginner["resources"]["lab_guide"]["step_count"]
    assert theory["resources"]["lesson"]["retrieval_question_count"] >= 1

    metrics = evidence["b04_regenerated_metrics"]
    assert metrics["adaptation_accuracy"] == {
        "numerator": 9,
        "denominator": 9,
        "percent": 100.0,
        "by_profile": {
            "profile-m0-advanced": {"passed": 3},
            "profile-m0-beginner": {"passed": 3},
            "profile-m0-theory": {"passed": 3},
        },
        "by_resource_type": {
            "lab_guide": {"passed": 3},
            "lesson": {"passed": 3},
            "tiered_quiz": {"passed": 3},
        },
    }
    assert metrics["failed_resource_ids"] == []
    assert metrics["evaluation_status"] == "blocked"
    assert metrics["publication_authorized"] is False
    assert metrics["human_validation"]["completed"] is False
    assert metrics["improvement_input"]["canonical_profile_or_mastery_write"] is False
    assert metrics["improvement_input"]["learning_event_write"] is False
    assert evidence["old_evidence_preserved"]["original_failed_adaptation_percent"] == "7/9"
