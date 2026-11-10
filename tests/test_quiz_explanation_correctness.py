from types import SimpleNamespace

from app.m5_assessment_core import learner_option_texts, learner_safe_explanation, learner_safe_prompt


def test_old_data_disclaimer_projection_preserves_conditions_and_teaching_code():
    old = '（练习条件，不是你的实测记录，也不是行业标准）'
    conditions = '\n| 分数 | 0.3 | 0.5 |\n|---|---|---|\n分数≥0.5判1；未知目标可以预测，预测时未知的结果不能作输入。'
    code = '\n```python\ncaption = "' + old + '"\n```'
    prompt = '表T' + old + conditions + code
    assert learner_safe_prompt(prompt) == '表T（练习数据）' + conditions + code
    assert old in prompt  # presentation does not rewrite the saved question


def test_old_preparation_labels_preserve_task_conditions_and_quoted_content():
    task = '采用inverted dropout，0≤p<1；训练时保留的激活除以1−p，推理时关闭Dropout。'
    assert learner_safe_prompt('共同核心题6：通用拓展：'+task) == task
    assert learner_safe_prompt('画像增补题2（通用拓展）：'+task) == task
    assert learner_safe_prompt('通用拓展（课程基础，不是题中分布表的推算）：'+task) == task
    assert learner_safe_prompt('以下为加练题（通用拓展），固定练习题设：'+task) == '补充练习：'+task
    quoted = '解释“通用拓展：”这段标签的用途。\n```text\n共同核心题6：通用拓展：原代码\n```'
    assert learner_safe_prompt(quoted) == quoted
from app.m5_exam_core import _dynamic_exam_question_version, learner_report_data


def test_known_historical_sum_gets_visible_erratum_without_changing_original_answer():
    prompt = '判断：arr1 = np.arange(0, 5)，arr2 = np.arange(6, 11)，arr1 + arr2 得到 array([6, 8, 10, 12, 14])。'
    original = '逐元素结果正确，整体求和则是 np.sum(arr1 + arr2)（本例结果为40）。'
    key = {'value': True}
    result = learner_safe_explanation(original, prompt=prompt, answer_key=key, question_type='true_false')
    assert result.startswith('勘误：')
    assert '应为50' in result and '本例结果为40' in result
    assert key == {'value': True} and '本例结果为40' in original
    assert learner_safe_explanation(result, prompt=prompt, answer_key=key, question_type='true_false').count('勘误：') == 1
    unrelated = learner_safe_explanation(original, prompt='另一道题', answer_key=key, question_type='true_false')
    assert '勘误：' not in unrelated
    corrected = learner_safe_explanation(original.replace('为40','为50'), prompt=prompt, answer_key=key, question_type='true_false')
    assert '勘误：' not in corrected


def test_saved_report_displays_erratum_but_retains_original_evidence():
    from copy import deepcopy

    original = {
        'earned_points': 83.33,
        'items': [{
            'position': 4, 'score': 1.0, 'question_type': 'true_false',
            'prompt': '判断：执行 `arr1 = np.arange(0, 5)`、`arr2 = np.arange(6, 11)` 后，'
                      '`arr1 + arr2` 会按元素逐个相加，结果为 `array([6, 8, 10, 12, 14])`',
            'explanation': '正确。整体求和则是 `np.sum(arr1 + arr2)`（本例结果为 40）。',
            'learner_answer': {'value': True}, 'correct_answer': {'value': True},
        }],
    }
    report = SimpleNamespace(report_data=deepcopy(original))
    projected = learner_report_data(report)
    assert projected['items'][0]['explanation'].startswith('勘误：')
    assert '应为50' in projected['items'][0]['explanation']
    assert '本例结果为 40' in projected['items'][0]['explanation']
    assert report.report_data == original
    for field in ('prompt', 'learner_answer', 'correct_answer', 'score'):
        assert projected['items'][0][field] == original['items'][0][field]
    assert projected['earned_points'] == 83.33
    repeated = learner_report_data(SimpleNamespace(report_data=projected))
    assert repeated['items'][0]['explanation'].count('勘误：') == 1


def test_provenance_placeholder_discloses_missing_reasoning_without_faking_it():
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
    assert "参考答案：A" in explanation
    assert "暂未保存详细解析" in explanation and "选项 B" not in explanation
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


def test_complete_concise_option_explanations_are_not_padded_with_generic_advice():
    original = (
        "正确答案是 B。逗号左边1:4取行下标1、2、3，右边1取第二列，得到85、88、65。"
        "A是第一列全部五行；C是第二行整行；D是行下标1到3的第三列。"
    )
    result = learner_safe_explanation(
        original, prompt="scores[1:4, 1]的结果是？",
        options=("[80,60,90,70,85]", "[85,88,65]", "[60,85,70]", "[70,95,80]"),
        answer_key={"choice": "B"}, question_type="single_choice",
    )
    assert "85、88、65" in result and "第一列全部五行" in result
    assert "没有同时满足题干" not in result
    assert "最小例子验证" not in result
    assert result.count("正确答案是 B") == 1


def test_missing_reasoning_only_uses_saved_answers_for_each_question_type():
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
    assert "参考答案：正确" in true_false and "暂未保存详细解析" in true_false
    assert "理由是" not in true_false and "最小自检" not in true_false
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
    assert "选项 B" not in version.explanation
    assert "验证" in version.explanation
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


def test_learner_prompt_preserves_matrix_rows_paragraphs_and_teaching_code():
    prompt = (
        "两个查询位置的分数如下：\n"
        "查询位置1：0，0，−∞，−∞\n查询位置2：1，0，−1，−∞\n\n"
        "逐行 softmax 后的矩阵是什么？\n"
        "```python\n# source_ref 是本题代码中的变量\nsource_ref = [1, 0, -1]\n"
        "for value in source_ref:\n    print(value)\n```"
    )
    assert learner_safe_prompt(prompt) == prompt
    assignment = SimpleNamespace(options=["source_ref = [1, 2]", "source_ref = None"], prompt="选择赋值语句")
    assert learner_option_texts(assignment) == assignment.options


def test_learner_options_keep_multiline_code_and_answer_labels():
    from app.m5_assessment_core import learner_option_texts

    options = ["A. 第一行 [0.5, 0.5]\n第二行 [0.67, 0.33]",
               "B. ```python\nsource_ref = [1, 2]\nfor value in source_ref:\n    print(value)\n```"]
    version = SimpleNamespace(options=options, prompt="哪项正确？", answer_key={"choice": "A"})
    assert learner_option_texts(version) == [options[0][3:], options[1][3:]]
    assert version.options == options and version.answer_key == {"choice": "A"}


def test_teaching_terms_are_not_replaced_by_generic_learning_choices():
    from app.m5_assessment_core import learner_option_texts

    options = [
        "A. Git commit 保存当前暂存区的快照。",
        "B. 性能 profile 可以帮助定位耗时。",
        "C. 学习画像中的偏好不能代替掌握依据。",
        "D. manifest 用于描述应用配置；source_ref 是本题讨论的变量名。",
    ]
    version = SimpleNamespace(options=options, prompt="哪些表述正确？", answer_key={"choices": ["A", "B", "C", "D"]})
    assert learner_option_texts(version) == [item[3:] for item in options]
    assert version.options == options
    prompt = "manifest 描述应用配置；source_ref 是本题讨论的变量名。请判断约束条件和学习画像依据。"
    assert learner_safe_prompt(prompt) == prompt


def test_missing_or_provenance_options_are_not_invented_from_the_answer_key():
    from app.m5_assessment_core import learner_option_texts

    for options in ([], ["A. 实际选项", "B. "], ["A. 实际选项", "B. source_ref: src-old-material"]):
        version = SimpleNamespace(options=options, prompt="下列哪项正确？", answer_key={"choice": "D"})
        assert learner_option_texts(version) == []
        assert version.options == options and version.answer_key == {"choice": "D"}


def test_concise_explanation_is_not_expanded_into_unverified_option_reasoning():
    original = "材料先用 model.fit(X, y) 训练模型，再对测试数组调用 model.predict 做预测。"
    assert learner_safe_explanation(original, prompt="用哪个方法训练？",
        options=["model.predict(X)", "model.fit(X, y)"], answer_key={"choice": "B"}) == original


def test_explanation_preserves_teaching_code_layout_and_variable_names():
    original = "逐行计算得到结果：\n```python\nsource_ref = [1, 2]\nfor x in source_ref:\n    print(x * 2)\n```\n\n输出为 2 和 4。"
    assert learner_safe_explanation(original, prompt="解释输出", answer_key={"reference_answer": "2 和 4"},
        question_type="short_answer") == original


def test_missing_explanation_shows_only_saved_answer_without_invented_reason():
    result = learner_safe_explanation("", prompt="哪项正确？", options=["候选一", "候选二"], answer_key={"choice": "B"})
    assert "参考答案：B" in result and "暂未保存详细解析" in result
    assert "与题干条件一致" not in result and "选项 A" not in result and "不正确" not in result


def test_known_legacy_footer_with_old_course_heading_does_not_replace_actual_reason():
    from app.m5_assessment_core import _fallback_learner_explanation
    kwargs = dict(prompt="如何划分训练集？", options=["用于训练", "用于评估"],
        answer_key={"choice": "A"}, question_type="single_choice")
    original = "训练集用于拟合参数；测试集用于最终评估。"
    old = _fallback_learner_explanation(**kwargs, legacy_topic="“旧课程名称”")
    assert learner_safe_explanation(original + " " + old, **kwargs) == original
    kwargs["options"] = ["仍有不确定性", "一定正确"]
    original = "叶节点不纯，预测仍有不确定性。"
    old = _fallback_learner_explanation(**kwargs, legacy_topic="“旧课程名称”").replace("确定性", "可复现性")
    assert learner_safe_explanation(original + " " + old, **kwargs) == original
