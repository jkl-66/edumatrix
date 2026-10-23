from types import SimpleNamespace

from app.m5_assessment_core import learner_safe_explanation, learner_safe_prompt
from app.m5_exam_core import _dynamic_exam_question_version


def test_provenance_placeholder_becomes_option_specific_learning_explanation():
    explanation = learner_safe_explanation(
        "先核对已冻结来源并绑定课程来源。",
        prompt="在“优化算法、正则化与训练稳定性”中，哪项做法最合理？",
        options=(
            "A. 根据验证集表现调整学习率并观察收敛",
            "B. 只看训练集准确率，不检查泛化",
            "C. 忽略正则化强度，直接增大模型",
            "D. 跳过边界条件，固定使用任意学习率",
        ),
        answer_key={"choice": "A"},
        question_type="single_choice",
    )
    assert "正确答案是 A" in explanation
    assert "选项 A" in explanation and "选项 B" in explanation
    assert "优化算法、正则化与训练稳定性" in explanation
    assert "先核对已冻结来源" not in explanation
    assert "绑定课程来源" not in explanation


def test_good_model_explanation_is_preserved_without_provenance_noise():
    explanation = learner_safe_explanation(
        "正确答案是 B，因为 Adam 同时利用一阶矩和二阶矩估计，能在不同参数方向上自适应调整步长。",
        prompt="哪种优化器会结合一阶矩和二阶矩？",
        options=("A. SGD", "B. Adam", "C. 朴素贝叶斯"),
        answer_key={"choice": "B"},
        question_type="single_choice",
    )
    assert explanation.startswith("正确答案是 B")
    assert "一阶矩" in explanation


def test_all_objective_types_get_question_specific_fallbacks():
    true_false = learner_safe_explanation(
        "答案来自冻结 RAG 课程来源。",
        prompt="判断：Dropout 可以缓解训练集过拟合。",
        answer_key={"value": True},
        question_type="true_false",
    )
    fill_blank = learner_safe_explanation(
        "依据课程来源核对。",
        prompt="填空：梯度下降每次沿梯度的____方向更新。",
        answer_key={"blanks": ["反方向"]},
        question_type="fill_blank",
    )
    short_answer = learner_safe_explanation(
        "绑定来源后完成核验。",
        prompt="请解释反向传播如何利用链式法则计算梯度。",
        answer_key={"reference_answer": "从损失开始沿计算图反向应用链式法则。"},
        question_type="short_answer",
    )
    assert "Dropout" in true_false and "适用条件" in true_false
    assert "最小自检" in true_false and "关键前提" in true_false
    assert len(true_false) >= 120
    assert "反方向" in fill_blank
    assert "链式法则" in short_answer
    assert all("课程来源" not in value for value in (true_false, fill_blank, short_answer))


def test_dynamic_intelligent_exam_question_stores_teaching_explanation():
    point = SimpleNamespace(id="kp-optim", title="优化算法")
    source = SimpleNamespace(id="source-1", location_label="优化章节", quote="学习率和正则化共同影响模型训练的稳定性。")
    blueprint = {
        "theme": "训练稳定性",
        "source_ref_ids": ["source-1"],
        "knowledge_points": [{"id": "kp-optim", "title": "优化算法", "mastery": 0.2}],
        "semantic_input_hash": "a" * 64,
        "difficulty": "adaptive",
    }
    version = _dynamic_exam_question_version(
        question_type="single_choice",
        point=point,
        chapter=None,
        source=source,
        blueprint=blueprint,
        position=0,
    )
    assert "正确答案是 A" in version.explanation
    assert "选项 B" in version.explanation
    assert "生成蓝图" not in version.explanation


def test_dynamic_true_false_explanation_uses_the_frozen_topic_reference():
    point = SimpleNamespace(id="kp-optim", title="优化算法、正则化与训练稳定性")
    source = SimpleNamespace(id="source-1", location_label="优化章节", quote="学习率和正则化共同影响模型训练的稳定性。")
    blueprint = {
        "theme": "训练稳定性",
        "source_ref_ids": ["source-1"],
        "knowledge_points": [{"id": point.id, "title": point.title, "mastery": 0.2}],
        "semantic_input_hash": "a" * 64,
        "difficulty": "adaptive",
    }

    version = _dynamic_exam_question_version(
        question_type="true_false", point=point, chapter=None, source=source,
        blueprint=blueprint, position=0,
    )

    assert "L2 正则化" in version.explanation
    assert point.title in version.explanation
    assert "权重规模" in version.explanation
    assert "验证曲线" in version.explanation
    assert "最佳检查点" in version.explanation
    assert "只改变题干中的一个关键条件" in version.explanation
    assert len(version.explanation) >= 150


def test_learner_prompt_removes_embedded_source_anchor_but_keeps_question():
    prompt = (
        "主题“检索评测”围绕知识点展开。课程来源锚点：“## 课程目标\n"
        "完成来源登记—检索调优—引用约束生成的闭环。”。下列哪项最合理？"
    )
    clean = learner_safe_prompt(prompt, knowledge_point="混合检索")
    assert clean == "主题“检索评测”围绕知识点展开。下列哪项最合理？"
    assert "课程来源锚点" not in clean
    assert "##" not in clean
