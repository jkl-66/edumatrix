from __future__ import annotations

import json
import asyncio
from pathlib import Path

import pytest

from app.interactive_lab import (
    InteractiveLabError,
    LabState,
    _computed_series,
    _evaluate,
    _hidden,
    experiment_execution_info,
    get_template,
    list_templates,
    validate_parameters,
)
from app.m5_resources import parse_interactive_model_content
from app.resource_bundles import (
    _deterministic_demo_content,
    _interactive_template_for_knowledge_point,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = (
    ROOT / "data/curated/machine_learning_foundations_v1/course_manifest.json",
    ROOT / "data/curated/ai_deep_learning_agents_v1/course_manifest.json",
    ROOT / "data/curated/data_structures_algorithms_v1/course_manifest.json",
)


def _defaults(template):
    return {
        item.key: int(item.default) if item.kind == "integer" else item.default
        for item in template.parameters
    }


def test_frequency_experiment_samples_reproducibly_and_distinguishes_single_sample_from_variability():
    import math
    template = _interactive_template_for_knowledge_point('频率与概率估计')
    assert template.template_id == 'sample-frequency-estimation'
    assert all(m.higher_is_better is None for m in template.metrics)
    p = _defaults(template)
    small, feedback = _evaluate(template, p)
    large, _ = _evaluate(template, {**p, 'sample_size': 1000})
    assert small == _evaluate(template, p)[0]
    assert small['event_count'] == 12
    assert small['sample_frequency'] == 12 and small['complement_frequency'] == 88
    assert small['theoretical_se'] == pytest.approx(100 * math.sqrt(.11 * .89 / 100), abs=1e-6)
    assert large['theoretical_se'] / small['theoretical_se'] == pytest.approx(1 / math.sqrt(10), abs=1e-6)
    assert large['frequency_sd'] < small['frequency_sd']
    assert '下一次事件仍按设定的总体概率发生' in '\n'.join(feedback)
    assert _evaluate(template, {**p, 'sample_seed': 8})[0] != small
    for probability in (0, 1):
        boundary, boundary_feedback = _evaluate(template, {**p, 'event_probability': probability})
        assert boundary['sample_frequency'] == probability * 100
        assert boundary['frequency_sd'] == boundary['theoretical_se'] == 0
        assert ('都不发生' if probability == 0 else '都发生') in '\n'.join(boundary_feedback)
        assert '标准差恒为0' in '\n'.join(boundary_feedback)
    series = _computed_series(template, p)
    assert {s.key for s in series} == {m.key for m in template.metrics}
    assert experiment_execution_info(template.template_id)['mode'] == 'synthetic_data_statistics'


def test_intro_classification_experiment_uses_actual_threshold_rows_and_boundaries():
    scope = {"knowledge_points": [{"title": title} for title in (
        "监督学习的输入、标签与预测任务", "回归与分类任务", "样本、特征与标签")]}
    template = _interactive_template_for_knowledge_point("从一张表分清样本、特征与标签", scope)
    assert template.template_id == "prediction-score-to-class"
    assert experiment_execution_info(template.template_id)["mode"] == "synthetic_data_statistics"
    at_half, feedback = _evaluate(template, {"decision_threshold": .5})
    at_high, _ = _evaluate(template, {"decision_threshold": .7})
    assert at_half == {"predicted_positive": 4, "predicted_negative": 2, "matched_labels": 5}
    assert at_high == {"predicted_positive": 2, "predicted_negative": 4, "matched_labels": 5}
    assert 'S3：给定分数0.50 → 预测类别1' in '\n'.join(feedback)
    assert '遮住真实标签' in '\n'.join(feedback)
    assert _evaluate(template, {"decision_threshold": 0})[0]["predicted_positive"] == 6
    assert _evaluate(template, {"decision_threshold": 1})[0]["predicted_positive"] == 0
    # Later lessons retain their distinct experiment and historical semantics.
    assert _interactive_template_for_knowledge_point("训练误差与泛化误差").template_id == 'model-complexity-generalization'


def test_builtin_experiment_families_keep_strict_payloads_and_uncovered_topics_are_explicit():
    registered = {item.template_id for item in list_templates()}
    titles = []
    for manifest_path in MANIFESTS:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for index, point in enumerate(manifest["knowledge_points"]):
            title = point["title"]
            template = _interactive_template_for_knowledge_point(title)
            if template is None:
                # The AI course now has fine-grained concepts as well as the
                # original broad families. A matrix-trace simulator cannot
                # honestly stand in for a lesson on transposition, for example.
                assert manifest['course_id'] == 'course-ai-deep-learning-agents-v1'
                assert len(point['code'].split('-')) == 4, title
                from app.resource_bundles import _real_model_payload_async, ResourceBundleError
                class UnusedBackend:
                    async def generate(self, *args, **kwargs):
                        raise AssertionError('Unsupported experiment must be resolved before model generation')
                with pytest.raises(ResourceBundleError) as unavailable:
                    asyncio.run(_real_model_payload_async(UnusedBackend(), resource_type='interactive_model',
                        item={'title': title}, manifest={'context': {'knowledge_point_title': title}}, source_snapshots=[]))
                assert unavailable.value.code == 'resource_generation.interactive_model_inapplicable'
                continue
            assert template.template_id in registered
            titles.append(title)
            generation_manifest = {
                "context": {
                    "course_title": manifest.get("title", "内置课程"),
                    "knowledge_point_title": title,
                    "learning_goal": f"理解{title}",
                    "profile_adaptation": "按当前画像提供分步实验支架。",
                    "mastery_summary": "掌握证据待积累。",
                    "recent_learning_summary": "暂无近期实验记录。",
                },
                "knowledge_point_id": f"coverage-kp-{index}",
            }
            content = _deterministic_demo_content(
                resource_type="interactive_model",
                item={"title": f"{title}实验", "completion_rule": "提交一次参数比较观察。"},
                manifest=generation_manifest,
                source_snapshots=[{"source_ref_id": f"coverage-source-{index}", "title": "课程主教材", "location_label": "章节"}],
            )
            parsed = parse_interactive_model_content(content)
            assert parsed.templateId == template.template_id
            assert {item.key for item in parsed.parameters} == {item.key for item in template.parameters}
            assert {item.key for item in parsed.chart.series} == {item.key for item in template.metrics}
    assert titles


def test_class_counts_are_neutral_in_generation_reading_and_acceptance():
    template = get_template('prediction-score-to-class')
    definitions = {item.key: item for item in template.metrics}
    for key in ('predicted_positive', 'predicted_negative'):
        assert definitions[key].higher_is_better is None
        assert definitions[key].acceptance_threshold is None
    raw = _deterministic_demo_content(resource_type='interactive_model',
        item={'title': '从分数到类别', 'completion_rule': '比较阈值并解释变化。'},
        manifest={'knowledge_point_id': 'threshold-point', 'context': {
            'course_title': '人工智能', 'knowledge_point_title': '回归与分类任务'}},
        source_snapshots=[{'source_ref_id': 'threshold-source', 'title': '原资料', 'location_label': '章节'}])
    current = json.loads(raw)
    assert [item['higherIsBetter'] for item in current['chart']['series']] == [None, None, True]
    # Old versions stay readable without rewriting their stored facts.
    for item in current['chart']['series'][:2]:
        item['higherIsBetter'] = False
    old_raw = json.dumps(current, ensure_ascii=False)
    parsed = parse_interactive_model_content(old_raw)
    assert [item.higherIsBetter for item in parsed.chart.series] == [None, None, True]
    assert json.loads(old_raw)['chart']['series'][0]['higherIsBetter'] is False
    parameters = {'decision_threshold': .5}
    metrics, _ = _evaluate(template, parameters)
    state = LabState(instance_id='neutral-counts', owner_public_id='synthetic',
        template_id=template.template_id, template_version=template.template_version,
        template_sha256=template.template_sha256, title=template.title, parameters=parameters, metrics=metrics)
    result = _hidden(template, state)
    assert result.passed and result.total_count == 1
    assert not any('隐藏' in item for item in template.public_scenarios)


def test_parallel_training_uses_amdahl_and_explicit_communication_cost():
    template = get_template("parallel-training-throughput")
    defaults = _defaults(template)
    assert _interactive_template_for_knowledge_point("计算性能、异步计算与并行训练") == template
    baseline, _ = _evaluate(template, {**defaults, "devices": 1})
    assert baseline == {"step_seconds": 100, "speedup": 1, "parallel_efficiency": 1}
    parallel, _ = _evaluate(template, defaults)
    assert parallel["step_seconds"] == 35.5  # 10 serial + 22.5 parallel + 3 communication
    ideal, _ = _evaluate(template, {**defaults, "devices": 16, "parallel_fraction": 1, "communication_seconds": 0})
    assert ideal == {"step_seconds": 6.25, "speedup": 16, "parallel_efficiency": 1}
    serial, _ = _evaluate(template, {**defaults, "parallel_fraction": 0, "communication_seconds": 0})
    assert serial["speedup"] == 1
    overlap, _ = _evaluate(template, {**defaults, "overlap_fraction": 1})
    assert overlap["step_seconds"] == 32.5
    expensive, _ = _evaluate(template, {**defaults, "communication_seconds": 20, "overlap_fraction": 0})
    assert expensive["step_seconds"] == 92.5
    assert experiment_execution_info(template.template_id)["mode"] == "teaching_simulation"


def test_eda_statistics_reflect_actual_missing_values_and_outliers():
    template = get_template("exploratory-data-distribution")
    baseline = {"outlier_count": 0, "outlier_value": 100, "missing_count": 0}
    metrics, _ = _evaluate(template, baseline)
    assert metrics == {"mean_shift": 0, "median_shift": 0, "available_fraction": 1}
    outlier_metrics, _ = _evaluate(template, {**baseline, "outlier_count": 1})
    assert outlier_metrics["mean_shift"] == round(30 / 41, 4)
    assert outlier_metrics["median_shift"] == 0
    missing_metrics, _ = _evaluate(template, {**baseline, "missing_count": 2})
    assert missing_metrics["mean_shift"] == missing_metrics["median_shift"] == 1
    assert missing_metrics["available_fraction"] == round(39 / 41, 4)


def test_inventory_cases_conserve_demand_and_do_not_confuse_backlogs_with_service():
    template = get_template("inventory-demand-boundary")
    baseline = _defaults(template)
    assert _interactive_template_for_knowledge_point("概率需求库存管理") == template
    assert _interactive_template_for_knowledge_point("缺货延期与缺货丢失假设") == template
    assert _interactive_template_for_knowledge_point("光圈与快门") is None
    metrics, feedback = _evaluate(template, baseline)
    # The ten two-day windows sum to 110 units. Only the 13-unit window
    # exceeds the 12 units on hand, so one unit is unmet, not 10% of units.
    assert metrics == {"immediate_fill_rate": round(109 / 110 * 100, 4),
                       "average_unmet": .1, "average_backlog": 0, "average_lost": .1}
    assert "10、11、12、12、11、10、12、13、10、9" in feedback[0]
    postponed, _ = _evaluate(template, {**baseline, "backorder": 1})
    assert postponed["immediate_fill_rate"] == metrics["immediate_fill_rate"]
    assert postponed["average_backlog"] == .1 and postponed["average_lost"] == 0
    constant, _ = _evaluate(template, {**baseline, "demand_variation": 0})
    assert constant["immediate_fill_rate"] == 100 and constant["average_unmet"] == 0
    empty, _ = _evaluate(template, {**baseline, "initial_stock": 0})
    assert empty["immediate_fill_rate"] == 0 and empty["average_unmet"] == 11
    longer, _ = _evaluate(template, {**baseline, "lead_days": 3})
    assert longer["average_unmet"] == 4.5
    assert longer["immediate_fill_rate"] == round(120 / 165 * 100, 4)
    full, _ = _evaluate(template, {**baseline, "initial_stock": 60, "lead_days": 5, "demand_variation": 2})
    assert full["immediate_fill_rate"] == 100 and full["average_unmet"] == 0
    assert experiment_execution_info(template.template_id)["mode"] == "synthetic_data_statistics"


def test_prediction_input_changes_prediction_but_not_training_or_validation():
    template = get_template("sklearn-fit-predict")
    defaults = _defaults(template)
    metrics, feedback = _evaluate(template, {**defaults, "prediction_x": -2})
    other_metrics, other_feedback = _evaluate(template, {**defaults, "prediction_x": 3})
    assert metrics == other_metrics
    assert feedback[1] != other_feedback[1]
    assert _interactive_template_for_knowledge_point("NumPy 数组与向量化计算").template_id == "data-processing-sensitivity"
    assert experiment_execution_info(template.template_id)["mode"] == "synthetic_data_training"
    assert experiment_execution_info("model-complexity-generalization")["mode"] == "teaching_simulation"


def test_every_new_template_runs_changes_series_and_passes_hidden_checks():
    legacy = {
        "rag-hybrid-tuning", "classifier-threshold-calibration", "data-processing-sensitivity",
        "model-complexity-generalization", "clustering-configuration", "dimensionality-reduction",
        "linear-algebra-probability", "optimization-dynamics",
    }
    for template in list_templates():
        if template.template_id in legacy:
            continue
        defaults = validate_parameters(template, _defaults(template))
        metrics, feedback = _evaluate(template, defaults)
        series = _computed_series(template, defaults)
        assert metrics and all(series_item.points for series_item in series)
        assert feedback
        sweep = next(item for item in template.parameters if item.key == template.sweep_parameter_key)
        changed = dict(defaults)
        other = sweep.maximum if defaults[sweep.key] == sweep.minimum else sweep.minimum
        changed[sweep.key] = int(other) if sweep.kind == "integer" else other
        changed_metrics, _ = _evaluate(template, validate_parameters(template, changed))
        assert changed_metrics != metrics, template.template_id
        state = LabState(
            instance_id="coverage-instance",
            owner_public_id="coverage-owner",
            template_id=template.template_id,
            template_version=template.template_version,
            template_sha256=template.template_sha256,
            title=template.title,
            parameters=defaults,
            metrics=metrics,
        )
        assert _hidden(template, state).passed


def test_invalid_parameters_are_rejected_before_evaluation():
    template = get_template("search-boundary")
    values = _defaults(template)
    values["scenario_scale"] = 99
    with pytest.raises(InteractiveLabError) as error:
        validate_parameters(template, values)
    assert error.value.code == "lab_parameter_out_of_bounds"

