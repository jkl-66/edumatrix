from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.interactive_lab import (
    InteractiveLabError,
    LabState,
    _computed_series,
    _evaluate,
    _hidden,
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
    ROOT / "data/curated/ai_deep_learning_agents_v1/course_manifest.json",
    ROOT / "data/curated/data_structures_algorithms_v1/course_manifest.json",
)


def _defaults(template):
    return {
        item.key: int(item.default) if item.kind == "integer" else item.default
        for item in template.parameters
    }


def test_all_builtin_knowledge_points_have_registered_experiments_and_strict_payloads():
    registered = {item.template_id for item in list_templates()}
    titles = []
    for manifest_path in MANIFESTS:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for index, point in enumerate(manifest["knowledge_points"]):
            title = point["title"]
            template = _interactive_template_for_knowledge_point(title)
            assert template is not None, title
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
    assert len(titles) == 45


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
        changed[sweep.key] = int(sweep.minimum) if sweep.kind == "integer" else sweep.minimum
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

