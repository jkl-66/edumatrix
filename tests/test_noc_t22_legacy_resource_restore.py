from __future__ import annotations

import json
from pathlib import Path

import app.resource_bundles as resource_bundles
from instruct_rag import LEGACY_LEARNING_STRATEGY_PROMPTS, LEGACY_RESOURCE_PROMPTS
from app.interactive_lab import get_template


ROOT = Path(__file__).resolve().parents[1]


def _manifest() -> dict:
    return {
        "course_id": "course-t22",
        "knowledge_point_id": "kp-t22",
        "context": {
            "course_title": "T22 课程",
            "knowledge_point_title": "模型评估",
            "learning_goal": "理解指标并能在项目中选择合适的评估方法",
            "profile_adaptation": "偏好实践；当前基础为入门；重点巩固召回率",
            "mastery_summary": "掌握度约 42%，需要分步巩固",
            "recent_learning_summary": "近期完成过一次指标练习",
        },
    }


def _payload() -> dict:
    return {
        "summary": "模型评估的完整学习路线",
        "narrative": "先理解指标含义，再比较适用条件，最后完成一次迁移练习。",
        "learningGoal": "能够解释并选择模型评估指标",
        "starterCode": "print('evaluate')\n",
        "practiceSteps": [
            {"title": "背景", "instruction": "明确任务", "expectedResult": "写出目标", "errorGuidance": "回看来源"},
            {"title": "机制", "instruction": "比较指标", "expectedResult": "说出差异", "errorGuidance": "检查条件"},
            {"title": "应用", "instruction": "运行示例", "expectedResult": "得到结果", "errorGuidance": "查看输出"},
            {"title": "边界", "instruction": "验证反例", "expectedResult": "说明限制", "errorGuidance": "区分相关与因果"},
        ],
        "quizQuestions": [
            {"prompt": "哪个指标关注漏检？", "options": ["精确率", "召回率", "准确率", "损失"], "answer": "B", "explanation": "召回率衡量真实正例被找回的比例。"}
        ],
        "handoutSections": [
            {"id": "background", "title": "行业背景", "kind": "concept", "content": "在风控和医疗筛查中，漏检代价会影响指标选择。", "sourceRefIds": ["src-t22"]},
            {"id": "example", "title": "项目例子", "kind": "example", "content": "比较高召回和高精确率的两种阈值策略。", "sourceRefIds": ["src-t22"]},
            {"id": "misconception", "title": "常见误区", "kind": "counterexample", "content": "不能只看准确率就判断模型适合不平衡数据。", "sourceRefIds": ["not-a-real-source"]},
        ],
    }


def test_restored_role_and_strategy_prompts_are_available() -> None:
    assert {"理论教授", "逻辑画师", "极客助教", "考官智能体", "视频推荐官"} <= set(LEGACY_RESOURCE_PROMPTS)
    assert {"WORKED_EXAMPLE", "HINT_LADDER", "RETRIEVAL_PRACTICE", "MISCONCEPTION_CONTRAST", "METACOGNITIVE_CALIBRATION", "SPACED_REVIEW"} <= set(LEGACY_LEARNING_STRATEGY_PROMPTS)
    system, user = resource_bundles._real_model_prompt(
        resource_type="handout",
        item={"title": "讲义"},
        manifest=_manifest(),
        source_snapshots=[{"source_ref_id": "src-t22", "title": "指标来源", "location_label": "第 1 章", "quote": "指标定义"}],
    )
    assert "理论教授" in system
    assert "通用基础知识补足" in system
    assert "handoutSections" in system
    assert "src-t22" in user


def test_handout_consumes_model_sections_without_fabricating_source_refs() -> None:
    content = resource_bundles._llm_resource_content(
        resource_type="handout",
        item={"type": "handout", "title": "T22 讲义"},
        manifest=_manifest(),
        source_snapshots=[{"source_ref_id": "src-t22", "title": "指标来源", "location_label": "第 1 章", "quote": "指标定义"}],
        linked_resource_ids=[],
        llm_payload=_payload(),
    )
    parsed = json.loads(content)
    assert any(item["title"] == "行业背景" for item in parsed["concepts"])
    assert any(item["title"] == "项目例子" for item in parsed["examples"])
    misconception = next(item for item in parsed["counterExamples"] if item["title"] == "常见误区")
    assert misconception["sourceRefIds"] == []
    assert len(parsed["outline"]) >= 8


def test_interactive_model_allows_missing_unit_when_template_unit_is_empty() -> None:
    template = get_template("rag-hybrid-tuning")
    payload = {
        "summary": "混合检索参数实验",
        "narrative": "比较关键词与向量权重对召回和延迟的影响。",
        "learningGoal": "能够解释检索权重的取舍。",
        "practiceSteps": [
            {"title": f"步骤 {index}", "instruction": "按模板运行实验。", "expectedResult": "得到可观察结果。", "errorGuidance": "回查参数边界。"}
            for index in range(1, 5)
        ],
        "templateId": template.template_id,
        "parameters": [
            {key: value for key, value in item.model_dump(mode="json").items() if key != "unit" or item.unit}
            for item in template.parameters
        ],
        "constraints": [{"id": "constraint-main", "title": "参数边界", "description": "遵守模板范围。"}],
        "dataset": {"id": "dataset-01", "title": "课程样本", "summary": "用于实验的课程样本。", "sampleCount": 10},
        "chart": {
            "kind": "line", "xAxisLabel": "参数", "yAxisLabel": "指标",
            "series": [
                {"key": metric.key, "label": metric.label, "unit": metric.unit, "higherIsBetter": metric.higher_is_better}
                for metric in template.metrics
            ],
        },
        "observationPrompt": "比较不同权重下的召回质量与延迟变化。",
    }
    content = resource_bundles._llm_resource_content(
        resource_type="interactive_model",
        item={"title": "混合检索实验"},
        manifest={**_manifest(), "context": {**_manifest()["context"], "knowledge_point_title": "混合检索"}},
        source_snapshots=[{"source_ref_id": "src-t22", "title": "检索来源", "location_label": "第 1 章"}],
        linked_resource_ids=[],
        llm_payload=payload,
    )
    assert json.loads(content)["templateId"] == template.template_id


def test_mindmap_component_uses_legacy_d3_features_with_structured_compatibility() -> None:
    component = (ROOT / "frontend/src/components/CollapsibleMindmap.vue").read_text(encoding="utf-8")
    for marker in ("structuredTree", "legacyTree", "foreignObject", "window.katex", "toggleFullscreen", "collapseAll", "expandAll", "zoomBy", "sourceRefs", "masteryBand", "view-change"):
        assert marker in component
    assert "Math.random" not in component
    assert "v-if=\"isFullscreen\"" in component
    for sizing_contract in (
        "rootHeight: 46",
        "regularHeight: 40",
        "minWidth: 142",
        "horizontalGap: 380",
        "verticalGap: 96",
        "toggleRadius: 11",
    ):
        assert sizing_contract in component
