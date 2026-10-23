from __future__ import annotations

import json
from pathlib import Path

from app.learner_output import teacher_text
from app.m5_assessment_core import learner_safe_explanation
from app.resource_bundles import _llm_resource_content, _normalize_handout_title
from llm_client import _deterministic_chat_answer


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = (
    "课文", "依据", "上下文重点", "确定性", "deterministic_local",
    "context_fingerprint", "source_ref_id", "rubric_version", "运行模式",
    "模型模式", "生成模式", "内部编号", "[S1]", "[A1]", "[source_ref]",
)


def _assert_teacher_voice(value: str) -> None:
    assert value.strip()
    assert not any(marker.casefold() in value.casefold() for marker in FORBIDDEN)


def _resource_payload() -> dict:
    return {
        "summary": "依据课程来源解释梯度下降，不显示 deterministic_local。",
        "narrative": "课文的上下文重点是学习率约束；demo-kp-optim 只是内部编号。",
        "learningGoal": "能解释更新方向并比较不同学习率。",
        "starterCode": "theta = 2.0\ngrad = 3.0\nprint(theta - 0.1 * grad)\n",
        "practiceSteps": [
            {"title": "准备数据", "instruction": "设置初值", "expectedResult": "得到数值", "errorGuidance": "检查输入"},
            {"title": "计算梯度", "instruction": "计算更新方向", "expectedResult": "得到梯度", "errorGuidance": "检查公式"},
            {"title": "运行更新", "instruction": "执行一步更新", "expectedResult": "参数变小", "errorGuidance": "检查学习率"},
            {"title": "比较结果", "instruction": "比较不同步长", "expectedResult": "说明差异", "errorGuidance": "检查边界"},
        ],
        "quizQuestions": [{
            "prompt": "学习率过大时最可能出现什么现象？",
            "options": ["损失震荡或发散", "参数始终不变", "一定得到最优解", "训练不需要梯度"],
            "answer": "A",
            "explanation": "正确答案是 A，因为步长过大可能反复跨过低谷。",
        }],
    }


def test_shared_projection_removes_implementation_narration_and_internal_ids() -> None:
    text = teacher_text(
        "依据课程来源，课文的上下文重点受约束；运行模式 deterministic_local，"
        "知识点 source_ref_id: demo-kp-optim，哈希 0123456789abcdef0123456789abcdef。[S1]"
    )
    _assert_teacher_voice(text)
    assert "本轮重点" in text
    assert "限制" in text
    assert all(marker not in text for marker in ("运行模式", "内部编号", "哈希"))


def test_stream_projection_preserves_markdown_chunk_boundaries() -> None:
    chunks = (
        "上一段结束。\n\n### 闭区间规则\n\n",
        "使用 `right = mid - 1` 排除已经比较过的中点。\n\n",
        "- 左边界向右移动\n- 右边界向左移动\n",
    )

    rendered = "".join(teacher_text(chunk, preserve_boundary=True) for chunk in chunks)

    assert "。\n\n### 闭区间规则" in rendered
    assert "`right = mid - 1`" in rendered
    assert "\n\n- 左边界" in rendered


def test_fallback_chat_answers_are_detailed_distinct_and_current_question_first() -> None:
    first = _deterministic_chat_answer("学生当前问题：请详细解释二分查找为什么要写 right = mid - 1？")
    second = _deterministic_chat_answer("学生当前问题：请详细解释梯度下降中学习率过大会怎样？")
    _assert_teacher_voice(first)
    _assert_teacher_voice(second)
    assert len(first) >= 500 and len(second) >= 500
    assert "right = mid - 1" in first
    assert "学习率" in second
    assert first != second


def test_variable_only_binary_follow_up_stays_detailed_and_natural() -> None:
    answer = _deterministic_chat_answer(
        "学生当前问题：那为什么找到中点不相等时，right 要写成 mid - 1，left 要写成 mid + 1？"
    )

    _assert_teacher_voice(answer)
    assert len(answer) >= 800
    assert "right = mid - 1" in answer and "left = mid + 1" in answer


def test_rag_answer_explains_scope_without_internal_filter_names() -> None:
    answer = _deterministic_chat_answer(
        "学生当前问题：请比较关键词检索、向量检索和重排各自解决什么问题。"
    )

    _assert_teacher_voice(answer)
    assert "关键词检索" in answer and "向量检索" in answer and "重排" in answer
    assert "owner/course/version" not in answer
    assert "精确 ID" not in answer


def test_assessment_explanation_teaches_the_question_instead_of_system_process() -> None:
    explanation = learner_safe_explanation(
        "先核对已冻结来源并依据课程来源给出结论。",
        prompt="哪种做法能缓解过拟合？",
        options=("A. 使用 Dropout", "B. 只增加训练轮数", "C. 忽略验证集", "D. 删除损失函数"),
        answer_key={"choice": "A"},
        question_type="single_choice",
        knowledge_point="过拟合与正则化",
    )
    _assert_teacher_voice(explanation)
    assert "正确答案是 A" in explanation
    assert "选项 A" in explanation and "选项 B" in explanation
    assert "过拟合与正则化" in explanation


def test_short_historic_explanation_is_expanded_into_a_teaching_walkthrough() -> None:
    explanation = learner_safe_explanation(
        "负梯度方向对应目标函数在当前位置的局部最速下降方向。",
        prompt="梯度下降更新参数时，为什么要沿负梯度方向？",
        options=("A. 让损失上升", "B. 获得局部最速下降方向"),
        answer_key={"choice": "B"},
        question_type="single_choice",
        knowledge_point="梯度下降",
    )

    _assert_teacher_voice(explanation)
    assert len(explanation) >= 240
    assert "正确答案是 B" in explanation
    assert "选项 A" in explanation and "选项 B" in explanation
    assert "局部最速下降方向" in explanation


def test_repeated_fill_blank_explanation_sentences_are_shown_once() -> None:
    repeated = (
        "这道题要求补出“梯度下降”的关键术语或步骤。参考答案为：反方向。"
        "作答时要结合题目条件解释这个术语的作用，而不是只写一个孤立的名词。"
        "这道题要求补出“梯度下降”的关键术语或步骤。参考答案为：反方向。"
        "作答时要结合题目条件解释这个术语的作用，而不是只写一个孤立的名词。"
    )
    explanation = learner_safe_explanation(
        repeated,
        prompt="填空：梯度下降沿梯度的____方向更新。",
        answer_key={"blanks": ["反方向"]},
        question_type="fill_blank",
    )
    assert explanation.count("参考答案为：反方向") == 1
    assert explanation.count("作答时要结合题目条件") == 1


def test_public_topic_uses_concrete_question_term_without_changing_binding() -> None:
    from app.m5_assessment_core import learner_topic_title

    assert learner_topic_title("梯度下降更新参数时，为什么要沿负梯度方向？", "RAG 评测口径") == "梯度下降"


def test_live_resource_fields_are_humanized_while_code_and_internal_bindings_remain() -> None:
    content = _llm_resource_content(
        resource_type="handout",
        item={"type": "handout", "title": "梯度下降讲义"},
        manifest={
            "course_id": "course-ai",
            "knowledge_point_id": "kp-optim",
            "context": {
                "course_title": "人工智能与深度学习",
                "knowledge_point_title": "梯度下降",
                "learning_goal": "理解梯度下降",
                "profile_adaptation": "适合先看数值例子",
                "mastery_summary": "基础正在建立",
                "recent_learning_summary": "最近学习了损失函数",
            },
        },
        source_snapshots=[{
            "source_ref_id": "source-optim",
            "title": "优化章节",
            "quote": "梯度下降沿负梯度方向更新参数。",
            "location_label": "第 2 章",
        }],
        linked_resource_ids=[],
        llm_payload=_resource_payload(),
    )
    parsed = json.loads(content)
    public_text = json.dumps({
        "summary": parsed["summary"],
        "concepts": parsed["concepts"],
        "miniQuiz": parsed["miniQuiz"],
        "profileAdaptation": parsed["profileAdaptation"],
    }, ensure_ascii=False)
    _assert_teacher_voice(public_text)
    assert parsed["codeBlocks"][0]["code"].startswith("theta = 2.0")
    assert parsed["footnotes"][0]["sourceRefId"] == "source-optim"


def test_handout_projection_removes_generation_instructions_but_keeps_dense_lesson() -> None:
    payload = _resource_payload()
    payload.update({
        "summary": "请输出 JSON 对象，围绕当前知识点要求说明取舍与验证依据。梯度下降的步长决定每次更新的幅度。",
        "narrative": "直接把当前知识点放进课程实践场景的新约束和边界中比较，要求说明取舍与验证依据。梯度下降沿负梯度方向更新参数，学习率决定每一步走多远。先看一个数值例子，再检查收敛条件。",
        "handoutSections": [
            {"id": f"section-{index}", "title": f"第 {index} 节", "kind": "concept", "content": f"围绕当前知识点要求比较方案。第 {index} 节解释参数变化和结果。", "sourceRefIds": ["source-optim"]}
            for index in range(1, 9)
        ],
    })
    content = _llm_resource_content(
        resource_type="handout",
        item={"type": "handout", "title": "梯度下降讲义"},
        manifest={
            "course_id": "course-ai",
            "knowledge_point_id": "kp-optim",
            "context": {
                "course_title": "人工智能与深度学习",
                "knowledge_point_title": "梯度下降",
                "learning_goal": "理解更新方向并比较不同学习率",
                "profile_adaptation": "当前掌握度较高，适合迁移练习",
                "mastery_summary": "进阶迁移",
                "recent_learning_summary": "最近学习了损失函数",
            },
        },
        source_snapshots=[{"source_ref_id": "source-optim", "title": "优化章节", "location_label": "第 2 章"}],
        linked_resource_ids=[],
        llm_payload=payload,
    )
    parsed = json.loads(content)
    public_text = json.dumps(parsed, ensure_ascii=False)
    assert "请输出 JSON" not in public_text
    assert "要求说明取舍" not in public_text
    assert "要求比较方案" not in public_text
    assert "梯度下降沿负梯度方向更新参数" in public_text
    assert "学习率决定每一步走多远" in public_text
    assert "直接把当前知识点" not in public_text
    assert len(parsed["concepts"]) >= 2
    assert len(parsed["outline"]) >= 8
    assert parsed["codeBlocks"] and parsed["miniQuiz"]
    assert parsed["footnotes"][0]["sourceRefId"] == "source-optim"


def test_handout_learning_goal_names_bound_knowledge_point_only_for_placeholders() -> None:
    base_manifest = {
        "course_id": "course-ai",
        "knowledge_point_id": "kp-optim",
        "context": {
            "course_title": "人工智能与深度学习",
            "knowledge_point_title": "梯度下降",
            "learning_goal": "当前学习资源",
            "profile_adaptation": "适合先看数值例子",
            "mastery_summary": "基础正在建立",
            "recent_learning_summary": "最近学习了损失函数",
        },
    }
    generic_payload = _resource_payload()
    generic_payload["learningGoal"] = "完成课程目标"
    generic = json.loads(_llm_resource_content(
        resource_type="handout",
        item={"type": "handout", "title": "梯度下降讲义"},
        manifest=base_manifest,
        source_snapshots=[{"source_ref_id": "source-optim", "title": "优化章节", "location_label": "第 2 章"}],
        linked_resource_ids=[],
        llm_payload=generic_payload,
    ))
    assert "梯度下降" in generic["learningGoal"]
    assert "完成课程目标" not in generic["learningGoal"]

    explicit_payload = _resource_payload()
    explicit_payload["learningGoal"] = "能解释学习率如何影响收敛，并能诊断一次发散"
    explicit = json.loads(_llm_resource_content(
        resource_type="handout",
        item={"type": "handout", "title": "梯度下降讲义"},
        manifest=base_manifest,
        source_snapshots=[{"source_ref_id": "source-optim", "title": "优化章节", "location_label": "第 2 章"}],
        linked_resource_ids=[],
        llm_payload=explicit_payload,
    ))
    assert explicit["learningGoal"] == explicit_payload["learningGoal"]


def test_handout_title_replaces_generic_suffix_but_preserves_custom_title() -> None:
    assert _normalize_handout_title("个性化讲义 · 当前学习资源", "混合检索与重排") == "个性化讲义 · 混合检索与重排"
    assert _normalize_handout_title("个性化讲义 · 当前课程资源", "梯度下降") == "个性化讲义 · 梯度下降"
    assert _normalize_handout_title("我的混合检索复习讲义", "混合检索与重排") == "我的混合检索复习讲义"


def test_student_templates_do_not_render_internal_modes_hashes_or_rule_ids() -> None:
    paths = (
        "frontend/src/views/FeynmanWorkspace.vue",
        "frontend/src/components/FeynmanEvaluationPanel.vue",
        "frontend/src/views/Chat.vue",
        "frontend/src/components/DiagnosticAssessmentSession.vue",
        "frontend/src/views/FormalExamWorkspace.vue",
        "frontend/src/components/ResourceFloatingQa.vue",
        "frontend/src/views/HandoutWorkspace.vue",
    )
    rendered = "\n".join((ROOT / path).read_text(encoding="utf-8") for path in paths)
    for marker in ("deterministic_local", "上下文短哈希", "评价规则", "f6.feynman-rubric.v1"):
        assert marker not in rendered
    assert "老师的回答" in rendered
    assert "详细解析" in rendered
    assert "回答绑定当前课程、资源和来源" not in rendered
    assert "source-details" in rendered


def test_exam_and_wrong_question_statuses_use_learner_language() -> None:
    exam_view = (ROOT / "frontend/src/views/FormalExamWorkspace.vue").read_text(encoding="utf-8")
    wrong_view = (ROOT / "frontend/src/views/WrongQuestionBook.vue").read_text(encoding="utf-8")

    assert "课程语义蓝图组卷" not in exam_view
    assert "已审核题库降级组卷" not in exam_view
    assert "并在作答前冻结" not in exam_view
    assert "强证据已进入学习聚合" not in wrong_view
    assert "回答正确，这次练习已经记录。" in wrong_view
    assert "已有正确证据" not in wrong_view
    assert "形成新的学习证据" not in wrong_view
    assert "查看原题" in wrong_view


def test_resource_entry_pages_do_not_lead_with_internal_generation_language() -> None:
    paths = (
        "frontend/src/views/FeynmanWorkspace.vue",
        "frontend/src/views/LearningPathGraph.vue",
        "frontend/src/views/MindmapWorkspace.vue",
        "frontend/src/views/ResourceBundleWorkspace.vue",
    )
    rendered = "\n".join((ROOT / path).read_text(encoding="utf-8") for path in paths)

    for marker in ("冻结课程来源", "依据课程来源", "形成新的学习证据", "可信学习证据"):
        assert marker not in rendered
    assert "参考材料" in rendered
    assert "学习路径才会更新" in rendered
    assert "结合当前来源说明" not in rendered
    assert "Footnote markers" in (ROOT / "frontend/src/views/HandoutWorkspace.vue").read_text(encoding="utf-8")
