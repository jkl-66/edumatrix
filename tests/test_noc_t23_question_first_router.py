import io
import re
from contextlib import redirect_stdout

from llm_client import (
    DeterministicEducationLLM,
    _deterministic_chat_answer,
    _extract_current_question,
    _has_standalone_question_focus,
    _guess_topic,
)


def test_current_question_wins_over_retrieved_topic_for_chat_answer():
    prompt = (
        "已验证来源：混合检索先召回再统一排序。\n"
        "学生当前问题：请解释二分查找的循环不变量。\n"
        "学习者画像适配计划：逐步说明边界。"
    )

    assert _extract_current_question(prompt) == "请解释二分查找的循环不变量。"
    assert _guess_topic(prompt) == "循环不变量"
    answer = _deterministic_chat_answer(prompt)
    assert "二分查找的循环不变量" in answer
    assert "混合检索把两路" not in answer


def test_current_question_wins_in_the_reverse_context_conflict():
    prompt = (
        "课程证据：二分查找的循环不变量保持目标区间。\n"
        "学生当前提问：混合检索为什么需要统一排序？\n"
        "课程上下文：仅供解释时引用。"
    )

    assert _guess_topic(prompt) == "混合检索"
    answer = _deterministic_chat_answer(prompt)
    assert "混合检索把两路" in answer
    assert "二分查找的循环不变量" not in answer


def test_m5_grounded_route_uses_current_question_before_static_context_answer():
    prompt = (
        "[src-hybrid] 混合检索先召回再统一排序。\n"
        "学生当前提问：梯度下降的学习率如何选择？\n"
        "学习者画像适配计划：给出一个小实验。"
    )

    answer = DeterministicEducationLLM().generate(
        "【已验证的 M5 学习上下文】", prompt, role="Subject Expert"
    )
    assert "梯度下降沿损失函数梯度的反方向更新参数" in answer
    assert "混合检索更稳定的原因" not in answer


def test_specialized_deterministic_roles_use_marked_question_topic():
    prompt = (
        "目标知识点：混合检索\n"
        "学生问题：请说明 Transformer 的自注意力。\n"
        "课程证据：混合检索是本章的上一节。"
    )

    assert _guess_topic(prompt) == "Transformer"
    lecture = DeterministicEducationLLM().generate(
        "你是理论教授", prompt, role="理论教授"
    )
    assert "Transformer" in lecture
    assert "混合检索" not in lecture


def test_current_question_stops_before_professional_chain_context():
    prompt = (
        "已验证来源：混合检索先召回再统一排序。\n"
        "学生当前问题：请解释 Transformer 的自注意力。\n\n"
        "课程协作上下文（仅供综合，不要暴露内部过程）：\n"
        "Subject Expert 草稿：混合检索需要统一排序。\n"
        "Evidence Verifier 结果：混合检索来源已核验。"
    )

    assert _extract_current_question(prompt) == "请解释 Transformer 的自注意力。"
    assert _guess_topic(prompt) == "Transformer"
    answer = _deterministic_chat_answer(prompt)
    assert "Q（Query）" in answer
    assert "softmax" in answer
    assert "混合检索把两路" not in answer


def test_question_first_handles_legacy_prompt_sections_after_question():
    prompt = (
        "【历史对话记录】：\n"
        "学生：上一轮讨论混合检索。\n\n"
        "学生当前提问：请说明梯度下降的学习率如何选择。\n"
        "图片解析出的内容：图片包含一个无关的 Transformer 公式。\n"
        "背景知识库匹配证据：混合检索先召回再统一排序。\n"
        "学习者画像适配计划：先给一个最小实验。"
    )

    assert _extract_current_question(prompt) == "请说明梯度下降的学习率如何选择。"
    assert _guess_topic(prompt) == "梯度下降"
    answer = _deterministic_chat_answer(prompt)
    assert "梯度下降沿损失函数梯度的反方向更新参数" in answer
    assert "混合检索把两路" not in answer


def test_binary_search_follow_up_terms_remain_in_current_question_branch():
    prompt = (
        "课程证据：混合检索先召回再重排。\n"
        "学生当前问题：那 left 和 right 在闭区间写法中分别何时移动？\n"
        "会话历史：上一轮讨论二分查找。"
    )

    assert _guess_topic(prompt) in {"闭区间", "left", "right"}
    answer = _deterministic_chat_answer(prompt)
    assert "二分查找的循环不变量" in answer
    assert "混合检索把两路" not in answer


def test_unlisted_explicit_question_still_wins_over_m5_retrieval_context():
    prompt = (
        "[src-hybrid] 混合检索先召回再统一排序。\n"
        "学生当前问题：请解释 KL 散度在模型训练中的作用。\n"
        "背景知识库匹配证据：混合检索更稳定。"
    )

    assert _has_standalone_question_focus("请解释 KL 散度在模型训练中的作用。")
    answer = DeterministicEducationLLM().generate(
        "【已验证的 M5 学习上下文】", prompt, role="Subject Expert"
    )
    assert "KL 散度在模型训练中的作用" in answer
    assert "混合检索更稳定的原因" not in answer


def test_predicate_only_follow_up_keeps_frozen_source_answer():
    assert not _has_standalone_question_focus("为什么更稳定？")
    prompt = (
        "[src-hybrid] 混合检索先召回再统一排序。\n"
        "学生当前问题：为什么更稳定？\n"
        "课程上下文：本轮承接上一问。"
    )
    answer = DeterministicEducationLLM().generate(
        "【已验证的 M5 学习上下文】", prompt, role="Subject Expert"
    )
    assert "混合检索更稳定的原因" in answer


def test_short_follow_up_does_not_invent_hybrid_retrieval_for_other_source():
    prompt = (
        "[src-transformer] 自注意力先计算 Q、K、V 的相关性，再按权重汇聚信息。\n"
        "学生当前问题：为什么更稳定？\n"
        "课程上下文：本轮承接上一问。"
    )
    answer = DeterministicEducationLLM().generate(
        "【已验证的 M5 学习上下文】", prompt, role="Subject Expert"
    )
    assert "自注意力先计算 Q、K、V" in answer
    assert "混合检索更稳定的原因" not in answer


def test_legacy_adaptive_tutor_role_uses_current_question_before_background_context():
    prompt = (
        "背景知识库匹配证据：混合检索先召回再统一排序。\n"
        "学生当前提问：请解释 KL 散度在模型训练中的作用。\n"
        "学习者画像适配计划：先给一个最小例子。"
    )
    answer = DeterministicEducationLLM().generate(
        "旧版流式答疑", prompt, role="自适应助教"
    )
    assert "KL 散度在模型训练中的作用" in answer
    assert "混合检索把两路" not in answer


def test_socratic_follow_up_marker_is_treated_as_the_latest_question():
    prompt = (
        "目标内容：混合检索的排序策略\n"
        "学生追问：请解释二分查找的循环不变量。\n"
        "历史对话：上一轮提到混合检索。"
    )
    assert _extract_current_question(prompt) == "请解释二分查找的循环不变量。"
    answer = DeterministicEducationLLM().generate(
        "苏格拉底答疑", prompt, role="苏格拉底辩手"
    )
    assert "二分查找的循环不变量" in answer
    assert "混合检索把两路" not in answer


def test_binary_first_question_and_boundary_follow_up_are_long_and_distinct():
    first = _deterministic_chat_answer(
        "学生当前问题：请解释二分查找的循环不变量，并给出一个边界条件例子。"
    )
    follow_up = _deterministic_chat_answer(
        "学生当前问题：那 left 和 right 在闭区间写法中分别何时移动？"
    )

    assert first != follow_up
    assert len(first) >= 800
    assert len(follow_up) >= 800
    assert "循环不变量" in first
    assert "[left, right]" in first
    assert "right = mid - 1" in follow_up
    assert "left = mid + 1" in follow_up
    assert "不要混用两种区间" in follow_up


def test_binary_boundary_follow_up_with_only_variable_names_keeps_the_topic():
    answer = _deterministic_chat_answer(
        "学生当前问题：那为什么找到中点不相等时，right 要写成 mid - 1，left 要写成 mid + 1？"
    )

    assert len(answer) >= 800
    assert "二分查找中 left 和 right 的移动规则" in answer
    assert "right = mid - 1" in answer
    assert "left = mid + 1" in answer


def test_deterministic_general_answers_include_a_verifiable_learning_chain():
    answer = _deterministic_chat_answer("学生当前问题：如何判断一个算法是否适合生产环境？")

    assert len(answer) >= 300
    assert "对象、目标和适用前提" in answer
    assert "边界情形" in answer
    assert "常见错误" in answer


def test_deterministic_code_question_returns_runnable_binary_search_contract():
    answer = _deterministic_chat_answer(
        "学生当前问题：请给出 Python 闭区间二分查找的可运行代码，并说明输入、输出、复杂度和三个边界测试。"
    )
    assert "def binary_search" in answer
    assert "left = mid + 1" in answer
    assert "right = mid - 1" in answer
    assert "O(log n)" in answer
    assert "输入、输出与不变量" in answer


def test_deterministic_pooling_question_is_not_hijacked_by_hybrid_context():
    answer = _deterministic_chat_answer(
        "课程证据：混合检索先召回再排序。学生当前问题：请解释卷积神经网络为什么需要池化层，并用 2×2 最大池化算一个例子。"
    )
    assert "池化层" in answer
    assert "卷积" in answer
    assert "[[6, 4], [3, 8]]" in answer
    assert "混合检索把两路互补" not in answer


def test_deterministic_attention_question_explains_qkv_and_softmax():
    answer = _deterministic_chat_answer(
        "学生当前问题：请用 Q、K、V 解释自注意力的计算过程，并说明缩放因子和一个常见误区。"
    )
    assert "Q（Query）" in answer
    assert "K（Key）" in answer
    assert "V（Value）" in answer
    assert "softmax" in answer
    assert "缩放因子" in answer


def test_deterministic_engineering_unknown_topic_is_actionable_without_fake_course_evidence():
    answer = _deterministic_chat_answer(
        "学生当前问题：我想了解 Kubernetes Deployment 的滚动更新、就绪探针和回滚策略，请给出工程化说明。"
    )
    assert "Kubernetes Deployment" in answer
    assert "readinessProbe" in answer
    assert "rollout undo" in answer
    assert "扩展工程知识" in answer


def test_deterministic_casual_message_stays_short_and_conversational():
    answer = _deterministic_chat_answer("学生当前问题：今天心情不错，讲个笑话吧。")
    assert "程序员去面试" in answer
    assert "循环不变量" not in answer
    assert len(answer) < 300


def test_hybrid_retrieval_learning_styles_are_distinct_and_question_specific():
    analogy = _deterministic_chat_answer(
        "课程证据：二分查找按边界缩小区间。学生当前问题：我喜欢先看直观例子，请用生活类比完整解释混合检索。"
    )
    derivation = _deterministic_chat_answer(
        "学生当前问题：请按输入、评分归一化、候选合并、重排和边界条件严格推导混合检索。"
    )
    code = _deterministic_chat_answer(
        "学生当前问题：请给出可直接运行的 Python 代码，比较关键词权重和向量权重对混合检索排序的影响。"
    )
    reflection = _deterministic_chat_answer(
        "学生当前问题：结合我先答错再纠正、完成代码和交互实验、费曼复述以及智能组卷50分的表现，反思掌握情况并给出降低认知负荷的计划。"
    )

    assert len({analogy, derivation, code, reflection}) == 4
    assert all(len(answer) >= 600 for answer in (analogy, derivation, code, reflection))
    assert "图书馆里两位" in analogy
    assert "F_i = λb'_i" in derivation
    assert "边界条件与正确性检查" in derivation
    assert "def rank(keyword_weight)" in code
    assert "预期输出怎么读" in code
    assert all(marker in reflection for marker in ("恢复能力", "程序性掌握", "变量控制", "概念关系", "50 分", "认知负荷"))
    assert "混合检索把两路互补" not in reflection


def test_hybrid_retrieval_python_example_compiles_and_runs():
    answer = _deterministic_chat_answer(
        "学生当前问题：给我一段可以直接运行的 Python 示例，比较关键词权重和向量权重变化对混合检索排序的影响。"
    )
    match = re.search(r"```python\n(.*?)```", answer, re.DOTALL)
    assert match is not None
    output = io.StringIO()
    with redirect_stdout(output):
        exec(compile(match.group(1), "<hybrid-retrieval-example>", "exec"), {})
    rendered = output.getvalue()
    assert "keyword=0.8" in rendered
    assert "('A', 0.8)" in rendered
    assert "keyword=0.2" in rendered
    assert rendered.index("('B',") < rendered.index("('C',", rendered.index("keyword=0.2"))
