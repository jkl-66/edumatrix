from __future__ import annotations

import json

import pytest

import app.resource_bundles as resource_bundles


def _manifest() -> dict:
    return {
        "course_id": "course-b13",
        "knowledge_point_id": "kp-b13",
        "context": {
            "course_title": "B13 课程",
            "knowledge_point_title": "模型训练边界",
            "learning_goal": "理解模型训练中的边界条件",
            "profile_adaptation": "按当前画像提供入门解释",
            "mastery_summary": "正在建立基础理解",
            "recent_learning_summary": "最近练习了梯度更新",
        },
    }


def _payload() -> dict:
    return {
        "summary": "MODEL_UNIQUE_SUMMARY_B13",
        "narrative": "MODEL_UNIQUE_NARRATIVE_B13 说明训练边界和验证步骤。",
        "learningGoal": "MODEL_UNIQUE_GOAL_B13",
        "starterCode": "print('MODEL_UNIQUE_CODE_B13')\n",
        "practiceSteps": [
            {
                "title": "模型输入",
                "instruction": "检查模型输入",
                "expectedResult": "得到输入字段",
                "errorGuidance": "回查冻结来源",
            },
            {
                "title": "参数更新",
                "instruction": "观察参数更新",
                "expectedResult": "记录更新结果",
                "errorGuidance": "核对学习率",
            },
            {
                "title": "运行观察",
                "instruction": "运行一次实验",
                "expectedResult": "保存输出",
                "errorGuidance": "保留错误信息",
            },
            {
                "title": "边界验证",
                "instruction": "验证边界条件",
                "expectedResult": "写下适用范围",
                "errorGuidance": "回到课程来源",
            },
        ],
        "quizQuestions": [
            {
                "prompt": "MODEL_UNIQUE_QUESTION_B13",
                "options": ["A", "B", "C", "D"],
                "answer": "A",
                "explanation": "MODEL_UNIQUE_EXPLANATION_B13",
            }
        ],
    }


def test_live_resource_body_uses_model_payload_without_demo_generator(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(**_kwargs):
        raise AssertionError("live resource content must not call deterministic demo content")

    monkeypatch.setattr(resource_bundles, "_deterministic_demo_content", fail_if_called)
    content = resource_bundles._llm_resource_content(
        resource_type="handout",
        item={"type": "handout", "title": "B13 真实讲义"},
        manifest=_manifest(),
        source_snapshots=[
            {
                "source_ref_id": "src-b13",
                "title": "B13 课程来源",
                "quote": "训练边界需要依据课程来源验证。",
                "location_label": "第 1 章 / 第 2 页",
            }
        ],
        linked_resource_ids=[],
        llm_payload=_payload(),
    )

    parsed = json.loads(content)
    assert parsed["summary"] == "MODEL_UNIQUE_SUMMARY_B13"
    assert parsed["concepts"][0]["explanation"].endswith("MODEL_UNIQUE_NARRATIVE_B13 说明训练边界和验证步骤。")
    assert parsed["codeBlocks"][0]["code"].strip() == "print('MODEL_UNIQUE_CODE_B13')"
    assert "MODEL_UNIQUE_SUMMARY_B13" in content
    assert "deterministic" not in content.lower()


def test_live_resource_body_rejects_missing_model_body_instead_of_fabricating(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        resource_bundles,
        "_deterministic_demo_content",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("demo path used")),
    )
    payload = _payload()
    payload["narrative"] = ""
    with pytest.raises(resource_bundles.ResourceBundleError) as exc_info:
        resource_bundles._llm_resource_content(
            resource_type="mind_map",
            item={"type": "mind_map", "title": "B13 真实导图"},
            manifest=_manifest(),
            source_snapshots=[{"source_ref_id": "src-b13", "title": "B13 来源", "quote": "边界"}],
            linked_resource_ids=[],
            llm_payload=payload,
        )
    assert exc_info.value.code == "resource_generation.model_output_invalid"
