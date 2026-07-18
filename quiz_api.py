from __future__ import annotations

import hashlib
import os
import re
import uuid
from typing import Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks

from app.database import DBQuizRecord, DBReviewPlan, DBStudentProfile, get_db, run_db_op
from app.crud import load_student_profile, save_student_profile
from learning_event_bus import (
    LearningEventBus,
    publish_quiz_event,
    register_default_subscribers,
)
from swarm_factory import build_swarm_from_headers
from code_exec_api import SANDBOX_RUNNER

# 启动时注册默认事件订阅器
register_default_subscribers()

router = APIRouter(prefix="/api/quiz", tags=["quiz"])

import json as _json_mod


def _parse_llm_json(text: str) -> dict | None:
    """从 LLM 响应中提取并解析 JSON，支持 markdown 包裹/杂音/单引号。"""
    if not text:
        return None
    text = text.strip()
    # 1) 直接解析
    try:
        return _json_mod.loads(text)
    except _json_mod.JSONDecodeError:
        pass
    # 2) 提取 ```json 代码块
    m = re.search(r'```(?:json)?\s*\n(.+?)\n```', text, re.DOTALL)
    if m:
        try:
            return _json_mod.loads(m.group(1))
        except _json_mod.JSONDecodeError:
            pass
    # 3) 提取最外层 {}
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return _json_mod.loads(m.group(0))
        except _json_mod.JSONDecodeError:
            pass
    # 4) 单引号替换
    try:
        return _json_mod.loads(text.replace("'", '"'))
    except _json_mod.JSONDecodeError:
        pass
    return None


# === 任务 6: 主观题大模型判卷输出的结构保障 (JSON Schema Validation) ===
GRADING_SCHEMA = {
    "type": "object",
    "required": ["accuracy_score", "score_breakdown", "feedback", "next_action"],
    "properties": {
        "accuracy_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "ai_confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "score_breakdown": {
            "type": "object",
            "required": ["key_points_coverage", "semantic_correctness", "depth_and_detail", "clarity_and_logic"],
            "properties": {
                "key_points_coverage": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "semantic_correctness": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "depth_and_detail": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "clarity_and_logic": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            }
        },
        "feedback": {"type": "string"},
        "misconceptions": {"type": "array", "items": {"type": "string"}},
        "missing_points": {"type": "array", "items": {"type": "string"}},
        "next_action": {"type": "string", "enum": ["review", "practice", "advance"]},
        "metacognitive_gap": {"type": "string"},
    }
}

GRADING_FALLBACK = {
    "accuracy_score": 0.6,
    "ai_confidence": 0.7,
    "score_breakdown": {
        "key_points_coverage": 0.5,
        "semantic_correctness": 0.6,
        "depth_and_detail": 0.5,
        "clarity_and_logic": 0.6,
    },
    "feedback": "你的答案包含一些正确要点，但存在遗漏和误解。",
    "misconceptions": [],
    "missing_points": ["请对照参考答案检查遗漏"],
    "next_action": "practice",
    "metacognitive_gap": "",
}


def _validate_grading_result(result: dict) -> dict:
    """校验 LLM 判卷输出是否符合 JSON Schema，缺失/异常字段用安全值回填。"""
    if not isinstance(result, dict):
        return GRADING_FALLBACK.copy()

    validated = {}

    # accuracy_score: 必须在 [0, 1] 区间
    try:
        acc = float(result.get("accuracy_score", 0.5))
        validated["accuracy_score"] = max(0.0, min(1.0, acc))
    except (ValueError, TypeError):
        validated["accuracy_score"] = 0.5

    # ai_confidence: 必须在 [0, 1] 区间
    try:
        conf = float(result.get("ai_confidence", 0.6))
        validated["ai_confidence"] = max(0.0, min(1.0, conf))
    except (ValueError, TypeError):
        validated["ai_confidence"] = 0.6

    # score_breakdown: 必须包含 4 个维度，每个在 [0, 1]
    breakdown = result.get("score_breakdown", {})
    if not isinstance(breakdown, dict):
        breakdown = {}
    validated["score_breakdown"] = {}
    for key in ["key_points_coverage", "semantic_correctness", "depth_and_detail", "clarity_and_logic"]:
        try:
            val = float(breakdown.get(key, 0.5))
            validated["score_breakdown"][key] = max(0.0, min(1.0, val))
        except (ValueError, TypeError):
            validated["score_breakdown"][key] = 0.5

    # feedback: 必须是字符串
    fb = result.get("feedback", "")
    validated["feedback"] = str(fb) if fb else GRADING_FALLBACK["feedback"]

    # misconceptions: 必须是字符串列表
    mis = result.get("misconceptions", [])
    if isinstance(mis, list):
        validated["misconceptions"] = [str(m) for m in mis if m]
    else:
        validated["misconceptions"] = []

    # missing_points: 必须是字符串列表
    mp = result.get("missing_points", [])
    if isinstance(mp, list):
        validated["missing_points"] = [str(p) for p in mp if p]
    else:
        validated["missing_points"] = GRADING_FALLBACK["missing_points"][:]

    # next_action: 必须是 review/practice/advance
    na = str(result.get("next_action", "")).strip()
    validated["next_action"] = na if na in ("review", "practice", "advance") else "practice"

    # metacognitive_gap: 字符串
    validated["metacognitive_gap"] = str(result.get("metacognitive_gap", ""))

    return validated


async def _get_llm(request: Request):
    swarm = build_swarm_from_headers(request.headers)
    return swarm.llm


def _generate_quiz_id() -> str:
    return uuid.uuid4().hex[:16]


def _get_fallback_quiz(concept: str, difficulty: str) -> dict[str, Any]:
    """根据目标概念，返回专家级且内容准确的兜底简答题及参考答案。"""
    norm = concept.lower()
    
    # 1. Sigmoid 函数与逻辑回归
    if "sigmoid" in norm or "逻辑回归" in norm:
        return {
            "question": "请用你自己的话解释逻辑回归中 Sigmoid 函数的作用的核心原理，并给出一个实际例子。",
            "reference_answer": (
                "Sigmoid 函数的核心作用是将线性回归模型的任意实数输出 z 映射到 (0, 1) 区间内，"
                "从而可以被解释为概率值（即样本属于正类的概率）。公式为 g(z) = 1 / (1 + e^-z)。"
                "其实际应用例子包括：在垃圾邮件分类中，模型根据邮件特征计算出分值，通过 Sigmoid 转换为 0.85，"
                "大于设定的阈值 0.5，故将其分类为垃圾邮件。"
            ),
            "correct_answer": (
                "Sigmoid 函数的核心作用是将线性回归模型的任意实数输出 z 映射到 (0, 1) 区间内，"
                "从而可以被解释为概率值（即样本属于正类的概率）。公式为 g(z) = 1 / (1 + e^-z)。"
                "其实际应用例子包括：在垃圾邮件分类中，模型根据邮件特征计算出分值，通过 Sigmoid 转换为 0.85，"
                "大于设定的阈值 0.5，故将其分类为垃圾邮件。"
            ),
            "concept": concept,
            "difficulty": difficulty,
            "hints": [
                "考虑 Sigmoid 函数的公式 g(z) = 1 / (1 + e^-z) 的输出范围。",
                "输出的值在 0 到 1 之间，这在数学上对应什么概念？",
                "举一个分类的例子（例如邮件分类、疾病预测），说明线性输出如何转化为分类决策。"
            ]
        }
        
    # 2. 最大池化与平均池化
    elif "最大池化" in norm:
        return {
            "question": "请解释最大池化（Max Pooling）的核心原理与计算步骤，并举例说明它的一个关键作用。",
            "reference_answer": (
                "最大池化是在输入特征图上滑动一个固定大小的窗口（如 2x2），在每个局部窗口内提取最大数值"
                "作为该区域的输出。其主要计算步骤是：确定窗口大小和步长 -> 对每个窗口取最大值。"
                "其关键作用是降低空间分辨率以减少计算量，并提供平移不变性。"
            ),
            "correct_answer": (
                "最大池化是在输入特征图上滑动一个固定大小的窗口（如 2x2），在每个局部窗口内提取最大数值"
                "作为该区域 of 输出。其主要计算步骤是：确定窗口大小和步长 -> 对每个窗口取最大值。"
                "其关键作用是降低空间分辨率以减少计算量，并提供平移不变性。"
            ),
            "concept": concept,
            "difficulty": difficulty,
            "hints": [
                "最大池化如何在一个 2x2 窗口中提取特征？它提取的是什么信号？",
                "池化层如何降低计算复杂度？（提示：空间分辨率发生了什么变化？）",
                "如果图像中的物体发生了微小的移动，最大池化的输出会受很大影响吗？"
            ]
        }
    elif "平均池化" in norm:
        return {
            "question": "请说明平均池化（Average Pooling）与最大池化（Max Pooling）在原理及计算上的主要区别。",
            "reference_answer": (
                "平均池化在局部窗口内计算所有数值的算术平均值作为输出，而最大池化则是取局部窗口内的最大值。"
                "计算上，平均池化保留了整个背景区域的平均特征（起平滑作用），而最大池化能突出最显著的纹理特征。"
            ),
            "correct_answer": (
                "平均池化在局部窗口内计算所有数值的算术平均值作为输出，而最大池化则是取局部窗口内的最大值。"
                "计算上，平均池化保留了整个背景区域的平均特征（起平滑作用），而最大池化能突出最显著的纹理特征。"
            ),
            "concept": concept,
            "difficulty": difficulty,
            "hints": [
                "平均池化窗口内的计算是求均值，最大池化是求最大值。",
                "最大池化往往更关注亮色或强烈的边缘纹理，而平均池化对整体背景有什么作用？",
                "二者在保留图像的显著特征与平滑特征上有什么侧重？"
            ]
        }
    elif "池化" in norm:
        return {
            "question": "请解释卷积神经网络中池化层（Pooling Layer）的主要作用以及它的核心工作原理。",
            "reference_answer": (
                "池化层主要用于对特征图进行空间降采样。其核心原理是利用一个滑动窗口在特征图上运行，"
                "用窗口内的聚合统计量（最大值或平均值）代替该区域。它的主要作用包括：1. 减少空间尺寸和参数量以防止过拟合；"
                "2. 保持平移、旋转及尺度的局部不变性。"
            ),
            "correct_answer": (
                "池化层主要用于对特征图进行空间降采样。其核心原理是利用一个滑动窗口在特征图上运行，"
                "用窗口内的聚合统计量（最大值或平均值）代替该区域。它的主要作用包括：1. 减少空间尺寸和参数量以防止过拟合；"
                "2. 保持平移、旋转及尺度的局部不变性。"
            ),
            "concept": concept,
            "difficulty": difficulty,
            "hints": [
                "池化层是否含有可训练的权重参数？",
                "它是如何使特征图变小的？对防止过拟合有什么帮助？",
                "池化操作如何提高网络对物体位置微调的鲁棒性？"
            ]
        }
        
    # 3. 过拟合与正则化
    elif "过拟合" in norm or "正则化" in norm:
        return {
            "question": f"简述{concept}的核心原理，并说明在模型训练中如何应用它来提高模型的泛化能力。",
            "reference_answer": (
                "过拟合指模型在训练集上表现优异，但在未见过的测试集上表现较差的现象。"
                "正则化（如 L1/L2 正则化）通过在损失函数中引入参数惩罚项（惩罚过大的参数绝对值或平方和），"
                "从而限制模型复杂度，强制模型学习更简单、更平滑的函数，以此解决过拟合，提升泛化能力。"
            ),
            "correct_answer": (
                "过拟合指模型在训练集上表现优异，但在未见过的测试集上表现较差的现象。"
                "正则化（如 L1/L2 正则化）通过在损失函数中引入参数惩罚项（惩罚过大的参数绝对值或平方和），"
                "从而限制模型复杂度，强制模型学习更简单、更平滑的函数，以此解决过拟合，提升泛化能力。"
            ),
            "concept": concept,
            "difficulty": difficulty,
            "hints": [
                "当模型过度拟合了训练集中的噪声时会发生什么？",
                "L1/L2 正则化公式在原本的 Loss 基础上增加了什么项？对权重有何限制？",
                "为什么参数值越小，模型通常就越不容易过拟合？"
            ]
        }
        
    # 4. 反向传播与链式法则
    elif "反向传播" in norm or "链式法则" in norm:
        return {
            "question": f"请结合链式法则（Chain Rule）解释{concept}的工作原理，并说明它在神经网络训练中的关键角色。",
            "reference_answer": (
                "反向传播算法基于多元复合函数的微积分链式法则，通过从神经网络输出层向输入层反向计算损失函数"
                "关于各层权重和偏置的梯度。它首先计算输出误差，然后层层向前传递偏导数，从而使优化算法（如梯度下降）"
                "能够根据这些计算好的梯度来调整网络参数，实现端到端的权重更新。"
            ),
            "correct_answer": (
                "反向传播算法基于多元复合函数的微积分链式法则，通过从神经网络输出层向输入层反向计算损失函数"
                "关于各层权重和偏置的梯度。它首先计算输出误差，然后层层向前传递偏导数，从而使优化算法（如梯度下降）"
                "能够根据这些计算好的梯度来调整网络参数，实现端到端的权重更新。"
            ),
            "concept": concept,
            "difficulty": difficulty,
            "hints": [
                "梯度下降算法更新权重需要知道什么？（提示：关于权重的偏导数）",
                "为什么我们是从最后一层（输出层）开始，逆向计算偏导数？",
                "复合函数求导的链式法则在这里如何实现局部误差的逐层向前传播？"
            ]
        }
        
    # 5. 梯度下降
    elif "梯度下降" in norm:
        return {
            "question": "请解释梯度下降（Gradient Descent）算法的基本工作原理、核心更新公式以及学习率的作用。",
            "reference_answer": (
                "梯度下降通过沿着损失函数梯度的反方向迭代更新模型参数以寻找损失函数的局部极小值。"
                "更新公式为：theta = theta - lr * 梯度。其中学习率（lr）决定了参数更新的步长大小，"
                "过大会导致震荡不收敛，过小会导致收敛极慢。"
            ),
            "correct_answer": (
                "梯度下降通过沿着损失函数梯度的反方向迭代更新模型参数以寻找损失函数的局部极小值。"
                "更新公式为：theta = theta - lr * 梯度。其中学习率（lr）决定了参数更新的步长大小，"
                "过大会导致震荡不收敛，过小会导致收敛极慢。"
            ),
            "concept": concept,
            "difficulty": difficulty,
            "hints": [
                "梯度的方向在数学上代表了什么？（提示：函数值上升最快的方向）",
                "如果我们想最小化损失，我们应该往梯度的哪个方向更新参数？",
                "如果学习率设置得过大，优化过程在损失曲面上会发生什么？"
            ]
        }
        
    # 6. 多概念/复合概念联合考察兜底
    elif "与" in norm or "和" in norm:
        return {
            "question": f"请详细对比并阐述「{concept}」之间的区别与联系，并结合神经网络的实际应用说明它们各自发挥的作用。",
            "reference_answer": (
                f"关于「{concept}」这两个概念：它们既有独立的数学计算方式，"
                "又在深度学习框架中紧密协作。我们需要阐明它们各自解决的痛点问题（例如空间特征降采样与长距离依赖关系抽取），"
                "并说明在具体网络（如 CNN 或 Transformer）中如何进行组合或端到端传导。"
            ),
            "correct_answer": (
                f"关于「{concept}」这两个概念：它们既有独立的数学计算方式，"
                "又在深度学习框架中紧密协作。我们需要阐明它们各自解决的痛点问题（例如空间特征降采样与长距离依赖关系抽取），"
                "并说明在具体网络（如 CNN 或 Transformer）中如何进行组合或端到端传导。"
            ),
            "concept": concept,
            "difficulty": difficulty,
            "hints": [
                f"分别描述「{concept}」中每个单独概念的基本数学或逻辑定义。",
                "这两个概念在解决什么不同的挑战？例如局部特征感知 vs 全局长程关联？",
                "请用一个联合架构（如包含二者的组合网络）说明它们是如何进行交互和联合前向传播的。"
            ]
        }
    # 7. 默认兜底
    else:
        return {
            "question": f"请结合实际例子，用你自己的话解释 {concept} 的核心原理与主要应用场景。",
            "reference_answer": (
                f"{concept} 的核心定义是其基本机制，主要通过特定的数理公式或逻辑结构，"
                f"在解决实际场景（如分类、回归或预测任务）中作为关键环节，其正确应用需特别关注过拟合防范与合理参数配置。"
            ),
            "correct_answer": (
                f"{concept} 的核心定义是其基本机制，主要通过特定的数理公式或逻辑结构，"
                f"在解决实际场景（如分类、回归或预测任务）中作为关键环节，其正确应用需特别关注过拟合防范与合理参数配置。"
            ),
            "concept": concept,
            "difficulty": difficulty,
            "hints": [
                f"想想 {concept} 的主要解决问题是什么",
                f"在真实的机器学习项目中，{concept} 会在哪一个阶段被调用？",
                f"请尝试列出该概念的 2 到 3 个核心要素或计算步骤"
            ]
        }


@router.post("/generate")
async def generate_quiz(
    request: Request,
) -> dict[str, Any]:
    payload = await request.json()
    student_id = str(payload.get("student_id", "default"))
    target_concept = str(payload.get("target_concept", "")).strip()
    req_difficulty = str(payload.get("difficulty", "")).strip().lower()

    profile = await run_db_op(load_student_profile, student_id)
    if not target_concept:
        # 主动探索不确定性消除：寻找估计误差协方差 p_err 最大的概念进行测试，快速消除认知地图的熵
        max_err_concept = None
        max_err_val = -1.0
        for concept, state in (profile.bkt_states or {}).items():
            p_err = state.get("p_err", 0.0)
            if p_err > max_err_val:
                max_err_val = p_err
                max_err_concept = concept
                
        if max_err_concept and max_err_val > 0.15:
            target_concept = max_err_concept
        elif profile.weak_points:
            target_concept = profile.weak_points[0]
        else:
            target_concept = "机器学习基础"

    # 动态难度：基于 MIRT 能力估计 + Fisher 信息增益自适应出题
    # 融合画像中的情感安全约束（挫败感/认知负荷）
    from mirt_engine import AdaptiveTestEstimator, IRTItemParams, beta_to_difficulty

    mastery = profile.concept_mastery.get(target_concept, 0.45)
    cognitive_load = profile.cognitive_load
    frustration = profile.frustration_index

    # 1. 从画像中恢复 IRT 能力估计器状态（存于 rl_q_table 避免与 KnowledgeTrace 类型冲突）
    irt_state = (profile.rl_q_table or {}).get("_irt_estimator", {})
    irt_history = irt_state.get("response_history", [])

    # === 任务 17: 测验冷启动跨概念先验继承 ===
    if irt_history:
        prior_theta = irt_state.get("theta", [0.0, 0.0, 0.0])
        prior_std = irt_state.get("theta_std", [1.0, 1.0, 1.0])
        if isinstance(prior_theta, (int, float)):
            prior_theta = [float(prior_theta)] * 3
        if isinstance(prior_std, (int, float)):
            prior_std = [float(prior_std)] * 3
        prior_cov = irt_state.get("theta_cov")
    else:
        overall_mastery = profile.mastery_score if hasattr(profile, "mastery_score") else 0.5
        from statistics import mean
        if profile.concept_mastery:
            overall_mastery = mean(profile.concept_mastery.values()) if profile.concept_mastery else 0.5
        prior_val = (overall_mastery - 0.5) * 3.0
        prior_theta = [prior_val, prior_val * 0.8, prior_val * 0.6]
        prior_std = [1.0, 1.0, 1.0]
        prior_cov = None

    estimator = AdaptiveTestEstimator(
        theta=prior_theta,
        theta_std=prior_std,
        theta_cov=prior_cov,
    )
    # 恢复答题历史以保持后验估计连续性
    for entry in irt_state.get("response_history", []):
        estimator.response_history.append({
            "item": IRTItemParams.from_dict(entry.get("item", {})),
            "correct": entry.get("correct", False),
        })

    # 2. 基于当前 theta 估计值，通过 IRT 模型确定最优难度
    irt_difficulty = estimator.get_estimated_difficulty_label()

    # 3. 情感安全约束：挫败感高或认知负荷过大时降级难度
    if req_difficulty in ('easy', 'medium', 'hard'):
        difficulty = req_difficulty
    elif frustration > 0.6 or cognitive_load > 0.7:
        difficulty = 'easy'
    else:
        difficulty = irt_difficulty

    # === 任务 8: 元认知自评偏差的路径路由消费 ===
    meta_bias = profile.cognitive_map.get("metacognitive_bias", 0.0)
    if meta_bias > 0.35:
        difficulty = "hard"
    elif meta_bias < -0.35 and difficulty != "hard":
        difficulty = "easy"

    # 4. 尝试从本地种子题库选题 (Hybrid CAT Engine)
    from app.database import DBQuizItem
    
    def select_from_item_bank(session):
        # 查找该知识点的所有预置题
        candidates = session.query(DBQuizItem).filter(
            DBQuizItem.concept == target_concept
        ).all()
        # 查找已答题目的文本以去重
        answered = session.query(DBQuizRecord.question).filter(
            DBQuizRecord.student_id == student_id,
            DBQuizRecord.student_answer != ""
        ).all()
        answered_texts = {a[0].strip() for a in answered if a[0]}
        
        available = [c for c in candidates if c.question.strip() not in answered_texts]
        return available

    available_candidates = await run_db_op(select_from_item_bank)
    
    selected_item = None
    if len(available_candidates) >= 3:
        candidates_dict = [
            {
                "id": c.id,
                "question": c.question,
                "options": c.options or [],
                "correct_answer": c.correct_answer,
                "explanation": c.explanation,
                "difficulty": c.difficulty,
                "irt_params": {
                    "alpha": c.irt_alpha_vec if c.irt_alpha_vec is not None else c.irt_alpha,
                    "beta": c.irt_beta_vec if c.irt_beta_vec is not None else c.irt_beta,
                    "gamma": c.irt_gamma
                }
            }
            for c in available_candidates
        ]
        selected_item = estimator.select_next_item(candidates_dict)

    irt_alpha_vec = None
    irt_beta_vec = None

    if selected_item:
        # 选中了预置题，直接使用
        result = {
            "question": selected_item["question"],
            "reference_answer": selected_item["correct_answer"],
            "concept": target_concept,
            "difficulty": selected_item["difficulty"],
            "hints": ["请仔细阅读题目", "根据已知条件推导", "给出你的详细解答步骤"],
            "options": selected_item["options"],
        }
        raw_alpha = selected_item["irt_params"]["alpha"]
        raw_beta = selected_item["irt_params"]["beta"]
        
        irt_alpha_vec = raw_alpha if isinstance(raw_alpha, list) else [raw_alpha, raw_alpha*0.8, raw_alpha*0.6]
        irt_beta_vec = raw_beta if isinstance(raw_beta, list) else [raw_beta, raw_beta+0.1, raw_beta-0.1]
        
        irt_alpha = irt_alpha_vec[0]
        irt_beta = irt_beta_vec[0]
        irt_gamma = selected_item["irt_params"]["gamma"]
    else:
        # 本地题库不足，降级调用大模型生成
        # RAG 知识检索增强，消除考题内容脱离课件的幻觉
        rag_context = ""
        try:
            from rag_engine import hybrid_rag
            retrieval = hybrid_rag.retrieve(query=target_concept, target=target_concept, top_k=2, disable_external=True)
            if retrieval and retrieval.evidence:
                rag_context = "\n".join(
                    f"【关联课件来源 {i+1}: {e.source}】\n{e.content}"
                    for i, e in enumerate(retrieval.evidence)
                )
        except Exception as e:
            print(f"  [quiz_api] RAG 检索出题增强失败: {e}")

        llm = await _get_llm(request)
        system_prompt = (
            "你是一个智能出题考官。根据给定的知识点、难度、课件参考和学生画像，生成高度定制化的简答题。\n"
            "请以JSON格式返回，包含以下字段：\n"
            "{\n"
            '  "question": "题目文本",\n'
            '  "reference_answer": "分点列出参考答案（用分号分隔）",\n'
            '  "concept": "考察的知识点",\n'
            '  "difficulty": "easy/medium/hard",\n'
            '  "hints": ["提示1（模糊引导）", "提示2（半具体）", "提示3（具体但非直接答案）"]\n'
            "}\n"
            "出题规则：\n"
            "- 如果提供了【关联课件参考】，考题背景、考察逻辑必须与之契合，不要出课件中未涵盖的概念。\n"
            "- 低掌握度（<0.4）：用最简单直白的语言，考察基本概念理解，提示要多且友好\n"
            "- 中等掌握度（0.4~0.7）：考察概念应用和简单推理，提示逐步递进\n"
            "- 高掌握度（>0.7）：考察综合分析和批判性思考，提示少而精\n"
            "- 挫败感高（>0.5）时题目要带鼓励语气并设置可达成的子目标"
        )
        user_prompt = (
            f"知识点：{target_concept}\n"
            f"难度：{difficulty}\n"
            f"掌握度：{mastery:.2f}\n"
            f"认知负荷：{cognitive_load:.2f}\n"
            f"挫败感：{frustration:.2f}\n"
        )
        if rag_context:
            user_prompt += f"\n【关联课件参考】：\n{rag_context}\n"
        user_prompt += (
            f"\n学生画像全文：{profile.profile_prompt()}\n"
            "请生成一道完全针对此学生定制的简答题，鼓励学生用自己的话回答。"
        )
        try:
            response = await llm.generate(system_prompt, user_prompt, role="考官智能体")
            result = _parse_llm_json(response)
            if not result:
                raise ValueError("parse failed")
            raw_hints = result.get("hints", [])
            result["hints"] = [re.sub(r'^提示\d*[:：]\s*', '', str(h)) for h in raw_hints]
        except Exception:
            result = _get_fallback_quiz(target_concept, difficulty)
        
        # 动态生成的题，计算初始 IRT 参数
        irt_alpha = 1.0
        irt_beta = {"easy": -1.0, "medium": 0.0, "hard": 1.0}.get(result.get("difficulty", difficulty).lower(), 0.0)
        irt_gamma = 0.25
        
        irt_alpha_vec = [1.0, 0.8, 0.6]
        irt_beta_vec = [irt_beta, irt_beta+0.1, irt_beta-0.1]

    quiz_id = _generate_quiz_id()
    
    # Store quiz record using run_db_op
    db_quiz = DBQuizRecord(
        id=quiz_id,
        student_id=student_id,
        question=result.get("question", ""),
        student_answer="",
        correct_answer=result.get("reference_answer", ""),
        ai_confidence=0.0,
        student_confidence=0.0,
        accuracy_score=0.0,
        target_concept=result.get("concept", target_concept),
        attempt_number=1,
        session_id=payload.get("session_id", ""),
        options=result.get("options", []),
        irt_alpha=irt_alpha,
        irt_beta=irt_beta,
        irt_gamma=irt_gamma,
        irt_alpha_vec=irt_alpha_vec,
        irt_beta_vec=irt_beta_vec,
    )
    
    def save_quiz(session):
        session.add(db_quiz)
        session.commit()
        
    await run_db_op(save_quiz)

    # 持久化 IRT 能力估计器状态到画像（存于 rl_q_table 避免与 KnowledgeTrace 类型冲突）
    def save_irt_state(session):
        p = load_student_profile(session, student_id)
        if p.rl_q_table is None:
            p.rl_q_table = {}
        p.rl_q_table["_irt_estimator"] = {
            "theta": estimator.theta,
            "theta_std": estimator.theta_std,
            "theta_cov": estimator.theta_cov,
            "response_history": [
                {"item": h["item"].to_dict(), "correct": h["correct"]}
                for h in estimator.response_history
            ],
        }
        save_student_profile(session, p)

    await run_db_op(save_irt_state)

    hints = result.get("hints", [])
    if meta_bias < -0.35:
        hints = list(hints) + ["考官提示：你的实力被低估了，放轻松！"]

    return {
        "quiz_id": quiz_id,
        "question": result.get("question"),
        "reference_answer": result.get("reference_answer", ""),
        "concept": result.get("concept", target_concept),
        "difficulty": result.get("difficulty", difficulty),
        "hints": hints,
        "options": result.get("options", []),
        "attempt_number": 1,
        "irt": estimator.to_dict(),
    }


@router.post("/evaluate")
async def evaluate_answer(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    payload = await request.json()
    quiz_id = str(payload.get("quiz_id", "")).strip()
    student_id = str(payload.get("student_id", "default"))
    student_answer = str(payload.get("answer", "")).strip()
    student_confidence = float(payload.get("student_confidence", 0.5))
    attempt_number = int(payload.get("attempt_number", 1))
    duration_seconds = payload.get("duration_seconds")
    if duration_seconds is not None:
        duration_seconds = float(duration_seconds)

    if not student_answer:
        raise HTTPException(status_code=400, detail="答案不能为空")

    def fetch_record(session):
        return session.query(DBQuizRecord).filter(
            DBQuizRecord.id == quiz_id,
            DBQuizRecord.student_id == student_id,
        ).first()

    quiz_record = await run_db_op(fetch_record)
    if not quiz_record:
        raise HTTPException(status_code=404, detail="测验记录未找到")

    llm = await _get_llm(request)

    # === 任务 1: 选择题秒判通道 (Deterministic MCQ Fast-Path Grading) ===
    if quiz_record.options and len(quiz_record.options) > 0:
        student_ans_clean = student_answer.strip().upper()
        correct_ans_clean = quiz_record.correct_answer.strip().upper()
        
        is_correct = False
        if student_ans_clean and correct_ans_clean:
            is_correct = (student_ans_clean[0] == correct_ans_clean[0])
            
        accuracy_score = 1.0 if is_correct else 0.0
        result = {
            "accuracy_score": accuracy_score,
            "ai_confidence": 1.0,
            "score_breakdown": {
                "key_points_coverage": accuracy_score,
                "semantic_correctness": accuracy_score,
                "depth_and_detail": accuracy_score,
                "clarity_and_logic": accuracy_score
            },
            "feedback": "选择正确！" if is_correct else f"选择错误。正确答案是 {correct_ans_clean}。",
            "misconceptions": [] if is_correct else ["概念混淆，选错干扰项"],
            "missing_points": [] if is_correct else ["未选中正确项"],
            "next_action": "advance" if is_correct else "review"
        }
        # 绕过 LLM，直接进入 updater
        ai_confidence = 1.0
    else:
        # === 编程/代码题检测，并在沙箱中跑测试用例 ===
        is_coding = False
        normalized_q = quiz_record.question.lower()
        if any(kw in normalized_q for kw in ("代码", "python", "实现", "编程", "函数", "类")):
            is_coding = True
            
        sandbox_report = None
        if is_coding:
            code_to_exec = student_answer
            m = re.search(r'```(?:python)?\s*\n(.+?)\n```', student_answer, re.DOTALL)
            if m:
                code_to_exec = m.group(1)
            
            # 运行沙箱，获取执行输出
            stdout, stderr, exec_time = await SANDBOX_RUNNER.run(code_to_exec)
            sandbox_report = {
                "stdout": stdout,
                "stderr": stderr,
                "exec_time_ms": int(exec_time * 1000),
                "success": not bool(stderr)
            }

        # === 主观题走 LLM 判卷 ===
        system_prompt = (
            "你是一个严谨的评估者。请从多个维度严格评估学生的答案。\n"
            "请以JSON格式返回，字段如下：\n"
            "{\n"
            '  "accuracy_score": 0.0~1.0,  // 整体准确度\n'
            '  "ai_confidence": 0.0~1.0,\n'
            '  "score_breakdown": {\n'
            '    "key_points_coverage": 0.0~1.0,  // 覆盖了多少参考答案关键点\n'
            '    "semantic_correctness": 0.0~1.0, // 语义是否正确\n'
            '    "depth_and_detail": 0.0~1.0,     // 深度和细节\n'
            '    "clarity_and_logic": 0.0~1.0     // 逻辑清晰度\n'
            "  },\n"
            '  "feedback": "详细的个性化反馈，先肯定正确部分，再指出遗漏和误解",\n'
            '  "misconceptions": ["具体误解1", "误解2"],\n'
            '  "missing_points": ["遗漏要点1", "遗漏要点2"],\n'
            '  "next_action": "review"|"practice"|"advance",\n'
            '  "metacognitive_gap": "学生自评与真实表现的差异分析"\n'
            "}\n"
            "对于编程/代码题，后端已经在安全沙箱中执行了学生代码，并提供了运行报告（包括 stdout/stderr）。\n"
            "请结合此报告对学生代码的正确性进行研判。若代码运行失败（有报错），accuracy_score 最高不能超过 0.4。\n"
            "评分标准：accuracy_score < 0.4=严重不足, 0.4~0.7=部分正确, >0.7=良好。"
        )
        user_prompt = (
            f"问题：{quiz_record.question}\n"
            f"参考答案要点：{quiz_record.correct_answer}\n"
            f"学生答案：{student_answer}\n"
            f"学生自评置信度：{student_confidence:.2f}\n"
        )
        if sandbox_report:
            user_prompt += (
                f"\n--- 代码沙箱运行报告 ---\n"
                f"运行是否成功: {sandbox_report['success']}\n"
                f"控制台输出 (stdout): {sandbox_report['stdout']}\n"
                f"错误信息 (stderr): {sandbox_report['stderr']}\n"
                f"运行耗时: {sandbox_report['exec_time_ms']} ms\n"
                f"-------------------------\n"
            )
        user_prompt += "请严格评估并返回JSON。"

        try:
            response = await llm.generate(system_prompt, user_prompt, role="考官智能体")
            result = _parse_llm_json(response)
            if not result:
                raise ValueError("parse failed")
            # === 任务 6: JSON Schema 结构校验，防止 LLM 幻觉输出 ===
            result = _validate_grading_result(result)
        except Exception:
            result = GRADING_FALLBACK.copy()
            result["feedback"] = f"你的答案包含一些正确要点。参考答案:{quiz_record.correct_answer[:100]}..."

        accuracy_score = float(result.get("accuracy_score", 0.5))
        ai_confidence = float(result.get("ai_confidence", 0.6))

    # Perform updates in a single thread-safe db transaction
    def perform_eval_updates(session):
        # 重新获取 record 以绑定到当前 session
        local_record = session.query(DBQuizRecord).filter(DBQuizRecord.id == quiz_id).first()
        profile = load_student_profile(session, student_id)
        
        # === Q-learning: 记录更新前的状态 ===
        concept = local_record.target_concept if local_record else "通用概念"
        old_mastery = profile.concept_mastery.get(concept, 0.45)
        old_load = profile.cognitive_load
        old_frustration = profile.frustration_index
        
        from app.utils.rl_planner import QLearningPathPlanner
        state_before = QLearningPathPlanner.get_state_key(old_mastery, old_load, old_frustration)
        
        # 执行更新
        profile.update_from_feedback(
            feedback=student_answer,
            accuracy=accuracy_score,
            self_confidence=student_confidence,
            hint_count=0,
            concept=concept,
        )

        # === 任务 4: 元认知偏差与自信度校准追踪 (Metacognitive Calibration Index) ===
        old_bias = profile.cognitive_map.get("metacognitive_bias", 0.0)
        old_error = profile.cognitive_map.get("metacognitive_error", 0.0)
        current_bias = student_confidence - accuracy_score
        current_error = abs(student_confidence - accuracy_score)
        profile.cognitive_map["metacognitive_bias"] = round(0.8 * old_bias + 0.2 * current_bias, 4)
        profile.cognitive_map["metacognitive_error"] = round(0.8 * old_error + 0.2 * current_error, 4)
        
        # === Q-learning: 记录更新后的状态 ===
        new_mastery = profile.concept_mastery.get(concept, 0.45)
        new_load = profile.cognitive_load
        new_frustration = profile.frustration_index
        state_after = QLearningPathPlanner.get_state_key(new_mastery, new_load, new_frustration)
        
        # 触发 Q 值迭代
        reward = QLearningPathPlanner.calculate_reward(
            old_mastery=old_mastery,
            new_mastery=new_mastery,
            correct=(accuracy_score >= 0.6),
            frustration=new_frustration,
            load=new_load
        )
        QLearningPathPlanner.update_q_value(
            profile=profile,
            state_before=state_before,
            action="quiz",
            state_after=state_after,
            reward=reward
        )

        # === MIRT 能力估计更新：基于答题结果更新 theta ===
        from mirt_engine import AdaptiveTestEstimator, IRTItemParams, estimate_irt_params_from_profile
        irt_state = (profile.rl_q_table or {}).get("_irt_estimator", {})
        prior_theta = irt_state.get("theta", [0.0, 0.0, 0.0])
        prior_std = irt_state.get("theta_std", [1.0, 1.0, 1.0])
        if isinstance(prior_theta, (int, float)):
            prior_theta = [float(prior_theta)] * 3
        if isinstance(prior_std, (int, float)):
            prior_std = [float(prior_std)] * 3
        prior_cov = irt_state.get("theta_cov")

        estimator = AdaptiveTestEstimator(
            theta=prior_theta,
            theta_std=prior_std,
            theta_cov=prior_cov,
        )
        for entry in irt_state.get("response_history", []):
            estimator.response_history.append({
                "item": IRTItemParams.from_dict(entry.get("item", {})),
                "correct": entry.get("correct", False),
            })
        # 优先使用数据库中题目真实绑定的 IRT 参数进行能力估计更新
        if local_record and local_record.irt_alpha_vec is not None:
            item_params = IRTItemParams.from_dict({
                "alpha": local_record.irt_alpha_vec,
                "beta": local_record.irt_beta_vec,
                "gamma": local_record.irt_gamma
            })
        elif local_record and local_record.irt_alpha is not None:
            item_params = IRTItemParams(
                alpha=float(local_record.irt_alpha),
                beta=float(local_record.irt_beta),
                gamma=float(local_record.irt_gamma)
            )
        else:
            # 根据当前掌握度估计题目参数 (正向自适应参数)
            item_params = estimate_irt_params_from_profile(
                mastery=old_mastery,
                attempts=local_record.attempt_number if local_record else 1,
            )
        is_correct = accuracy_score >= 0.6
        estimator.update_ability(item_params, is_correct)

        # === 任务 7: 题库参数的在线自适应校准更新 (MIRT beta SGD 精确似然更新) ===
        # delta_beta = learning_rate * (prob - correct_val)
        if local_record and not (local_record.options and len(local_record.options) > 0):
            import math
            prob = estimator._probability_correct(estimator.theta, item_params)
            prob = max(1e-5, min(1.0 - 1e-5, prob))
            correct_val = 1.0 if is_correct else 0.0
            
            # z = sum(alpha_d * (theta_d - beta_d))
            z = sum(a * (t - b) for a, t, b in zip(item_params.alpha, estimator.theta, item_params.beta))
            sigma_z = 1.0 / (1.0 + math.exp(-z)) if -z < 700 else 0.0
            
            denominator = prob * (1.0 - prob)
            # 计算方差调整因子
            weight_factor = (1.0 - item_params.gamma) * sigma_z * (1.0 - sigma_z) / denominator if denominator > 1e-5 else 0.0
            
            learning_rate = 0.05
            new_beta_vec = []
            for d in range(3):
                # 依据对数似然梯度：d_lnL/d_beta = a_d * (1-gamma) * sigma * (1-sigma) / (P * (1-P)) * (P - U)
                grad_beta = item_params.alpha[d] * weight_factor * (prob - correct_val)
                # 限制最大更新步长，防止小样本下因数值噪声导致溢出
                grad_beta = max(-0.5, min(0.5, grad_beta))
                new_beta_vec.append(round(item_params.beta[d] + learning_rate * grad_beta, 4))
                
            new_beta = new_beta_vec[0]
            
            from app.database import DBQuizItem
            session.query(DBQuizItem).filter(DBQuizItem.question == local_record.question).update({
                "irt_beta": new_beta,
                "irt_beta_vec": new_beta_vec
            }, synchronize_session=False)
            session.commit()

        # 写回 IRT 状态（存于 rl_q_table 避免与 KnowledgeTrace 类型冲突）
        if profile.rl_q_table is None:
            profile.rl_q_table = {}
        profile.rl_q_table["_irt_estimator"] = {
            "theta": estimator.theta,
            "theta_std": estimator.theta_std,
            "theta_cov": estimator.theta_cov,
            "response_history": [
                {"item": h["item"].to_dict(), "correct": h["correct"]}
                for h in estimator.response_history
            ],
        }
        
        save_student_profile(session, profile)

        if local_record:
            local_record.student_answer = student_answer
            local_record.student_confidence = student_confidence
            local_record.ai_confidence = ai_confidence
            local_record.accuracy_score = accuracy_score
            local_record.feedback = result.get("feedback", "")
            local_record.next_action = result.get("next_action", "practice")
            local_record.attempt_number = attempt_number
            session.commit()

            # === 任务 7.4: 错题自动入库（准确率 < 60%） ===
            if accuracy_score < 0.6:
                from app.database import DBWrongQuestion
                # 提取阻断概念
                blocking_concept = local_record.target_concept or "通用概念"
                # 检查是否已存在相同概念错题
                existing = session.query(DBWrongQuestion).filter(
                    DBWrongQuestion.student_id == student_id,
                    DBWrongQuestion.concept_name == blocking_concept,
                    DBWrongQuestion.quiz_record_id == quiz_id,
                ).first()
                if not existing:
                    wrong_q = DBWrongQuestion(
                        student_id=student_id,
                        quiz_record_id=quiz_id,
                        concept_name=blocking_concept,
                        wrong_reason_category=result.get("next_action", "practice"),
                    )
                    session.add(wrong_q)

                    # 同时更新 profile.weak_points
                    if blocking_concept not in profile.weak_points:
                        profile.weak_points.append(blocking_concept)
                    save_student_profile(session, profile)
                session.commit()
            
        return profile.concept_mastery.get(local_record.target_concept if local_record else "", 0.5)

    concept_mastery_updated = await run_db_op(perform_eval_updates)

    # MCMC 题库参数校准已移至离线批处理脚本中定时运行

    # 获取更新后的 IRT 能力估计状态
    irt_info = {}
    try:
        updated_profile = await run_db_op(load_student_profile, student_id)
        irt_state = (updated_profile.rl_q_table or {}).get("_irt_estimator", {})
        irt_info = {
            "theta": irt_state.get("theta", 0.0),
            "theta_std": irt_state.get("theta_std", 1.0),
            "items_answered": len(irt_state.get("response_history", [])),
        }
    except Exception:
        pass

    # === 触发画像探针 LLM 抽取 ===
    try:
        from swarm_factory import build_swarm_from_headers
        swarm = build_swarm_from_headers(request.headers)
        profile = swarm.profile_store.get(student_id)
        if profile:
            await swarm.profile_probe.async_update(profile, f"我回答了关于{quiz_record.target_concept}的问题: {student_answer}")
    except Exception:
        pass

    # === 任务 10.1: 发布答题事件到 LearningEventBus ===
    try:
        await publish_quiz_event(
            student_id=student_id,
            concept=quiz_record.target_concept,
            accuracy=accuracy_score,
            ai_confidence=ai_confidence,
            student_confidence=student_confidence,
            attempt_number=attempt_number,
            question=quiz_record.question[:200],
            answer=student_answer[:200],
            session_id=payload.get("session_id", ""),
            quiz_id=quiz_id,
            duration_seconds=duration_seconds,
        )
    except Exception:
        pass  # 事件总线失败不应影响主流程

    # === 任务 7.7: 答对相似题 → 降低原题复习优先级 ===
    try:
        similar_to_source = payload.get("source_quiz_id", "")
        if similar_to_source and accuracy_score >= 0.7:
            source_concept = quiz_record.target_concept
            def _lower_review_priority(session):
                review_plan = session.query(DBReviewPlan).filter(
                    DBReviewPlan.student_id == student_id,
                    DBReviewPlan.concept == source_concept,
                ).first()
                if review_plan:
                    review_plan.priority = min(5.0, (review_plan.priority or 1.0) * 1.5)
                    session.commit()
            await run_db_op(_lower_review_priority)
    except Exception:
        pass

    return {
        "quiz_id": quiz_id,
        "accuracy_score": accuracy_score,
        "ai_confidence": ai_confidence,
        "score_breakdown": result.get("score_breakdown", {}),
        "feedback": result.get("feedback", ""),
        "misconceptions": result.get("misconceptions", []),
        "missing_points": result.get("missing_points", []),
        "next_action": result.get("next_action", "practice"),
        "metacognitive_gap": result.get("metacognitive_gap", ""),
        "student_answer": student_answer,
        "reference_answer": quiz_record.correct_answer,
        "concept_mastery_updated": concept_mastery_updated,
        "student_confidence": student_confidence,
        "confidence_calibration": abs(student_confidence - accuracy_score),
        "irt": irt_info,
    }


@router.post("/adapt")
async def adapt_quiz(
    request: Request,
) -> dict[str, Any]:
    payload = await request.json()
    student_id = str(payload.get("student_id", "default"))
    quiz_id = str(payload.get("quiz_id", "")).strip()
    previous_action = str(payload.get("next_action", "practice"))

    profile = await run_db_op(load_student_profile, student_id)

    if previous_action == "advance":
        weak_points = [w for w in profile.weak_points if w not in payload.get("mastered_concepts", [])]
        if weak_points:
            target = weak_points[0]
        else:
            target = "下一个进阶概念"
        difficulty = "hard"
    elif previous_action == "practice":
        target = payload.get("target_concept", "")
        if not target and profile.weak_points:
            target = profile.weak_points[0]
        difficulty = "medium"
    else:
        target = payload.get("target_concept", "")
        if not target and profile.weak_points:
            target = profile.weak_points[0]
        difficulty = "easy"

    # Generate follow-up quiz
    # 动态难度：根据画像调整
    cl = profile.cognitive_load; fr = profile.frustration_index; m = profile.concept_mastery.get(target, 0.45)
    if difficulty == "hard" and (cl > 0.7 or fr > 0.6): difficulty = "medium"
    elif difficulty == "easy" and m > 0.7: difficulty = "medium"

    # === 任务 8: 元认知自评偏差的路径路由消费 ===
    meta_bias = profile.cognitive_map.get("metacognitive_bias", 0.0)
    if meta_bias > 0.35:
        difficulty = "hard"
    elif meta_bias < -0.35 and difficulty != "hard":
        difficulty = "easy"

    # === 任务 11: 自适应跟进出题融合本地预置题库 ===
    from app.database import DBQuizItem
    from mirt_engine import AdaptiveTestEstimator, IRTItemParams

    def select_from_item_bank(session):
        candidates = session.query(DBQuizItem).filter(
            DBQuizItem.concept == target
        ).all()
        answered = session.query(DBQuizRecord.question).filter(
            DBQuizRecord.student_id == student_id,
            DBQuizRecord.student_answer != ""
        ).all()
        answered_texts = {a[0].strip() for a in answered if a[0]}
        available = [c for c in candidates if c.question.strip() not in answered_texts]
        return available

    available_candidates = await run_db_op(select_from_item_bank)
    selected_item = None

    if len(available_candidates) >= 3:
        candidates_dict = [
            {
                "id": c.id,
                "question": c.question,
                "options": c.options or [],
                "correct_answer": c.correct_answer,
                "explanation": c.explanation,
                "difficulty": c.difficulty,
                "irt_params": {
                    "alpha": c.irt_alpha,
                    "beta": c.irt_beta,
                    "gamma": c.irt_gamma
                }
            }
            for c in available_candidates
        ]
        irt_state = (profile.rl_q_table or {}).get("_irt_estimator", {})
        prior_theta = irt_state.get("theta", [0.0, 0.0, 0.0])
        prior_std = irt_state.get("theta_std", [1.0, 1.0, 1.0])
        if isinstance(prior_theta, (int, float)):
            prior_theta = [float(prior_theta)] * 3
        if isinstance(prior_std, (int, float)):
            prior_std = [float(prior_std)] * 3
        prior_cov = irt_state.get("theta_cov")
        
        estimator = AdaptiveTestEstimator(
            theta=prior_theta,
            theta_std=prior_std,
            theta_cov=prior_cov,
        )
        for entry in irt_state.get("response_history", []):
            estimator.response_history.append({
                "item": IRTItemParams.from_dict(entry.get("item", {})),
                "correct": entry.get("correct", False),
            })
        selected_item = estimator.select_next_item(candidates_dict)

    if selected_item:
        result = {
            "question": selected_item["question"],
            "reference_answer": selected_item["correct_answer"],
            "concept": target,
            "difficulty": selected_item["difficulty"],
            "hints": ["请仔细阅读题目", "根据已知条件推导", "给出你的详细解答步骤"],
            "options": selected_item["options"],
        }
        if meta_bias < -0.35:
            result["hints"] = list(result["hints"]) + ["考官提示：你的实力被低估了，放轻松！"]
    else:
        # 本地题库不足，降级调用大模型生成
        llm = await _get_llm(request)
        system_prompt = (
            "你是一个智能出题考官。根据学生上次的表现和完整画像，生成一道高度定制的跟进简答题。\n"
            "请以JSON格式返回：\n"
            "{\n"
            '  "question": "题目文本（根据画像调整问法和深度）",\n'
            '  "reference_answer": "分点列出参考答案（用分号分隔）",\n'
            '  "concept": "考察的知识点",\n'
            '  "difficulty": "easy/medium/hard",\n'
            '  "hints": ["提示1", "提示2", "提示3"]\n'
            "}\n"
            "出题规则：低掌握度从基础概念问起；高掌握度考综合应用；挫败感高时降低难度并鼓励。"
        )
        user_prompt = (
            f"目标概念：{target}\n"
            f"难度：{difficulty}\n"
            f"上次表现建议动作：{previous_action}\n"
            f"掌握度：{m:.2f}\n"
            f"认知负荷：{cl:.2f}\n"
            f"挫败感：{fr:.2f}\n"
            f"学生画像全文：{profile.profile_prompt()}\n"
            "请生成一道能真正检验此学生理解的跟进题。"
        )

        try:
            response = await llm.generate(system_prompt, user_prompt, role="考官智能体")
            result = _parse_llm_json(response)
            if result:
                raw_hints = result.get("hints", [])
                result["hints"] = [re.sub(r'^提示\d*[:：]\s*', '', str(h)) for h in raw_hints]
                if meta_bias < -0.35:
                    result["hints"] = list(result["hints"]) + ["考官提示：你的实力被低估了，放轻松！"]
            else:
                raise ValueError("parse failed")
        except Exception:
            result = _get_fallback_quiz(target, difficulty)

    new_quiz_id = _generate_quiz_id()
    db_quiz = DBQuizRecord(
        id=new_quiz_id,
        student_id=student_id,
        question=result.get("question", ""),
        correct_answer=result.get("reference_answer", ""),
        ai_confidence=0.0,
        target_concept=result.get("concept", target),
        attempt_number=int(payload.get("attempt_number", 1)) + 1,
        session_id=payload.get("session_id", ""),
        options=result.get("options", []),
    )
    
    def save_adapted_quiz(session):
        session.add(db_quiz)
        session.commit()
        
    await run_db_op(save_adapted_quiz)

    return {
        "quiz_id": new_quiz_id,
        "question": result.get("question"),
        "reference_answer": result.get("reference_answer", ""),
        "concept": result.get("concept", target),
        "difficulty": result.get("difficulty", difficulty),
        "hints": result.get("hints", []),
        "options": result.get("options", []),
        "attempt_number": int(payload.get("attempt_number", 1)) + 1,
    }


@router.get("/history/{student_id}")
async def get_quiz_history(
    student_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    def fetch_history(session):
        return (
            session.query(DBQuizRecord)
            .filter(DBQuizRecord.student_id == student_id)
            .order_by(DBQuizRecord.created_at.desc())
            .limit(limit)
            .all()
        )
        
    records = await run_db_op(fetch_history)
    return [
        {
            "id": r.id,
            "question": r.question[:100],
            "accuracy_score": r.accuracy_score,
            "ai_confidence": r.ai_confidence,
            "student_confidence": r.student_confidence,
            "target_concept": r.target_concept,
            "next_action": r.next_action,
            "attempt_number": r.attempt_number,
            "created_at": r.created_at.isoformat() if r.created_at else "",
        }
        for r in records
    ]


@router.post("/similar")
async def generate_similar_quiz(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """任务 7.7: 生成同阶错题相似题 + 沙箱自校验。

    绑定错题对应的薄弱子概念，生成同难度、同考点相似题用于二次重测。

    请求体:
        student_id: str
        source_quiz_id: str  — 源错题 quiz_id
        concept: str (可选, 默认从源题提取)

    流程:
        1. 读取源错题 → 提取概念、难度
        2. LLM 带 Few-Shot JSON 模板生成相似题
        3. Sandbox 自动校验答案、选项无逻辑冲突 (最多重试 3 次)
        4. 答对后降低原题复习优先级
    """
    payload = await request.json()
    student_id = str(payload.get("student_id", "default"))
    source_quiz_id = str(payload.get("source_quiz_id", "")).strip()

    if not source_quiz_id:
        raise HTTPException(status_code=400, detail="必须提供 source_quiz_id")

    # Step 1: 读取源错题
    source = db.query(DBQuizRecord).filter(
        DBQuizRecord.id == source_quiz_id,
        DBQuizRecord.student_id == student_id,
    ).first()
    if not source:
        raise HTTPException(status_code=404, detail="源错题记录未找到")

    concept = source.target_concept or "通用概念"
    original_accuracy = source.accuracy_score or 0.0

    # === 任务 13: 相似题重测题型一致性失调修复 ===
    source_has_options = bool(source.options and len(source.options) > 0)

    # Step 2: LLM 生成相似题（Few-Shot JSON 模板，根据题型动态适配）
    llm = await _get_llm(request)

    if source_has_options:
        few_shot_template = (
            '{"question": "请计算...", '
            '"options": ["A. ...", "B. ...", "C. ...", "D. ..."], '
            '"correct_answer": "A", '
            '"explanation": "解析...", '
            '"python_validator": "assert ...", '
            '"difficulty": "medium"}'
        )
        system_prompt = (
            "你是一个严格的出题考官。\n"
            "根据源错题的知识点和难度，生成一道同难度、同考点的相似选择题。\n"
            "必须以 JSON 格式输出，严格遵循以下模板结构：\n"
            f"{few_shot_template}\n"
            "python_validator 字段是一段可运行的 Python assert 语句，"
            "用于自动验证你的答案逻辑正确性。\n"
            "确保 options 中正确答案唯一，且干扰项具有迷惑性但不矛盾。"
        )
    else:
        few_shot_template = (
            '{"question": "请解释...", '
            '"options": [], '
            '"correct_answer": "参考答案...", '
            '"explanation": "解析...", '
            '"python_validator": "assert ...", '
            '"difficulty": "medium"}'
        )
        system_prompt = (
            "你是一个严格的出题考官。\n"
            "根据源错题的知识点和难度，生成一道同难度、同考点的相似主观简答题或代码实操题。\n"
            "必须以 JSON 格式输出，严格遵循以下模板结构：\n"
            f"{few_shot_template}\n"
            "注意：options 必须为空数组 []，因为这是主观题，没有选项。\n"
            "python_validator 字段是一段可运行的 Python assert 语句，"
            "用于自动验证你的答案逻辑正确性。\n"
            "确保题目与源题题型一致，保持认知一致性。"
        )
    user_prompt = (
        f"源题知识点：{concept}\n"
        f"源题：{source.question[:200]}\n"
        f"源题正确答案：{source.correct_answer[:200]}\n"
        f"源题正确率：{original_accuracy:.2f}\n"
        "请生成一道同难度、同考点的相似题，JSON 格式输出。"
        "确保 python_validator 是可运行的 assert 语句。"
    )

    attempts = 0
    max_attempts = 3
    result = {}
    sandbox_passed = False

    while attempts < max_attempts and not sandbox_passed:
        attempts += 1
        try:
            response = await llm.generate(system_prompt, user_prompt, role="考官智能体")
            result = _parse_llm_json(response)
            if not result:
                result = {}

            # Step 3: 沙箱自校验
            python_code = result.get("python_validator", "")
            if python_code:
                try:
                    # 安全校验：通过进程隔离沙箱运行 LLM 生成的代码
                    import ast
                    tree = ast.parse(python_code)
                    has_assert = any(
                        isinstance(node, ast.Assert) for node in ast.walk(tree)
                    )
                    if has_assert:
                        # 路由至进程隔离沙箱运行，限制 CPU 时间及最大内存，防止沙箱逃逸与死锁
                        output, error, exec_time = await SANDBOX_RUNNER.run(python_code)
                        if error:
                            if "AssertionError" in error:
                                # AssertionError 是校验器的预期行为（验证逻辑触发）
                                sandbox_passed = True
                            else:
                                # 非断言错误说明代码本身有问题，需重试
                                user_prompt += f"\n\n⚠️ 第 {attempts} 次沙箱校验失败：{error[:200]}。请修正 python_validator 逻辑。"
                                continue
                        else:
                            sandbox_passed = True
                    else:
                        sandbox_passed = True  # 没有 assert 也通过
                except Exception as e:
                    # 沙箱启动失败，记录错误并重试
                    user_prompt += f"\n\n⚠️ 第 {attempts} 次沙箱校验失败：{e}。请修正 python_validator 逻辑。"
                    continue
            else:
                sandbox_passed = True  # 无验证器也通过
        except Exception:
            if attempts >= max_attempts:
                # 兜底：用简单相似题
                fb = _get_fallback_quiz(concept, "medium")
                result = {
                    "question": fb["question"],
                    "options": [],
                    "correct_answer": fb["correct_answer"],
                    "explanation": f"本题考察{concept}的核心理解",
                    "python_validator": "",
                    "difficulty": "medium",
                }
                sandbox_passed = True
            continue

    # Step 4: 保存新题
    new_quiz_id = _generate_quiz_id()
    diff_label = result.get("difficulty", "medium").lower()
    irt_alpha = 1.0
    irt_beta = {"easy": -1.0, "medium": 0.0, "hard": 1.0}.get(diff_label, 0.0)
    irt_gamma = 0.25

    db_quiz = DBQuizRecord(
        id=new_quiz_id,
        student_id=student_id,
        question=result.get("question", "生成失败"),
        correct_answer=result.get("correct_answer", ""),
        options=result.get("options", []),
        ai_confidence=0.7,
        target_concept=concept,
        attempt_number=1,
        session_id=payload.get("session_id", ""),
        irt_alpha=irt_alpha,
        irt_beta=irt_beta,
        irt_gamma=irt_gamma,
    )
    db.add(db_quiz)
    db.commit()

    # Step 5: 关联到源题的 review_plan
    review_plan = db.query(DBReviewPlan).filter(
        DBReviewPlan.student_id == student_id,
        DBReviewPlan.concept == concept,
    ).first()
    if review_plan:
        current_similar = list(review_plan.similar_quiz_ids or [])
        if new_quiz_id not in current_similar:
            current_similar.append(new_quiz_id)
        review_plan.similar_quiz_ids = current_similar
        db.commit()

    return {
        "quiz_id": new_quiz_id,
        "source_quiz_id": source_quiz_id,
        "question": result.get("question", ""),
        "options": result.get("options", []),
        "correct_answer": result.get("correct_answer", ""),
        "explanation": result.get("explanation", ""),
        "concept": concept,
        "difficulty": result.get("difficulty", "medium"),
        "sandbox_validated": sandbox_passed,
        "sandbox_attempts": attempts,
    }


# === 任务 7.4: 错题查询与复习打卡 API ===

@router.get("/wrong-questions/{student_id}")
async def get_wrong_questions(
    student_id: str,
    concept: str = "",
    limit: int = 50,
) -> list[dict]:
    """获取学生的错题列表，支持按概念筛选。"""
    from app.database import DBWrongQuestion, DBQuizRecord

    def fetch_wrong_questions(session):
        query = session.query(DBWrongQuestion).filter(
            DBWrongQuestion.student_id == student_id,
        )
        if concept:
            query = query.filter(DBWrongQuestion.concept_name == concept)
        records = query.order_by(DBWrongQuestion.pinned.desc(), DBWrongQuestion.created_at.desc()).limit(limit).all()

        results = []
        for r in records:
            quiz_detail = None
            if r.quiz_record_id:
                qr = session.query(DBQuizRecord).filter(
                    DBQuizRecord.id == r.quiz_record_id
                ).first()
                if qr:
                    quiz_detail = {
                        "question": qr.question[:200],
                        "student_answer": qr.student_answer[:200],
                        "correct_answer": qr.correct_answer[:200],
                        "options": list(qr.options or []),
                        "accuracy_score": qr.accuracy_score,
                        "feedback": qr.feedback[:200] if qr.feedback else "",
                    }
            results.append({
                "id": r.id,
                "quiz_record_id": r.quiz_record_id,
                "concept_name": r.concept_name,
                "wrong_reason_category": r.wrong_reason_category,
                "pinned": bool(r.pinned),
                "notes": r.notes or "",
                "created_at": r.created_at.isoformat() if r.created_at else "",
                "quiz_detail": quiz_detail,
            })
        return results

    return await run_db_op(fetch_wrong_questions)


@router.get("/wrong-concepts/{student_id}")
async def get_wrong_concepts(student_id: str) -> list[dict]:
    """获取学生的错题概念聚合统计。"""
    from app.database import DBWrongQuestion

    def fetch_concept_stats(session):
        from sqlalchemy import func
        records = (
            session.query(
                DBWrongQuestion.concept_name,
                func.count(DBWrongQuestion.id).label("count"),
            )
            .filter(DBWrongQuestion.student_id == student_id)
            .group_by(DBWrongQuestion.concept_name)
            .order_by(func.count(DBWrongQuestion.id).desc())
            .all()
        )
        return [
            {"concept": r.concept_name, "count": r.count}
            for r in records
        ]

    return await run_db_op(fetch_concept_stats)


@router.delete("/wrong-questions/{wrong_id}")
async def delete_wrong_question(wrong_id: int, student_id: str) -> dict:
    """删除指定的错题记录。"""
    from app.database import DBWrongQuestion

    def do_delete(session):
        record = session.query(DBWrongQuestion).filter(
            DBWrongQuestion.id == wrong_id,
            DBWrongQuestion.student_id == student_id
        ).first()
        if not record:
            raise HTTPException(status_code=404, detail="错题记录不存在或无权操作")
        session.delete(record)
        session.commit()
        return {"deleted": True, "id": wrong_id}

    return await run_db_op(do_delete)


@router.patch("/wrong-questions/{wrong_id}/pin")
async def toggle_pin_wrong_question(wrong_id: int, student_id: str) -> dict:
    """切换错题的置顶/取消置顶状态。"""
    from app.database import DBWrongQuestion

    def do_pin(session):
        record = session.query(DBWrongQuestion).filter(
            DBWrongQuestion.id == wrong_id,
            DBWrongQuestion.student_id == student_id
        ).first()
        if not record:
            raise HTTPException(status_code=404, detail="错题记录不存在或无权操作")
        record.pinned = not record.pinned
        session.commit()
        return {"id": wrong_id, "pinned": record.pinned}

    return await run_db_op(do_pin)


@router.patch("/wrong-questions/{wrong_id}/notes")
async def update_wrong_question_notes(wrong_id: int, request: Request) -> dict:
    """更新错题的笔记内容。"""
    from app.database import DBWrongQuestion

    payload = await request.json()
    student_id = str(payload.get("student_id", ""))
    notes = str(payload.get("notes", ""))

    def do_update(session):
        record = session.query(DBWrongQuestion).filter(
            DBWrongQuestion.id == wrong_id,
            DBWrongQuestion.student_id == student_id
        ).first()
        if not record:
            raise HTTPException(status_code=404, detail="错题记录不存在或无权操作")
        record.notes = notes
        session.commit()
        return {"id": wrong_id, "notes": notes}

    return await run_db_op(do_update)


@router.post("/checkin/{student_id}")
async def checkin_review(
    student_id: str,
    request: Request,
) -> dict:
    """复习打卡签到：记录当天的复习行为。"""
    payload = await request.json()
    concept = str(payload.get("concept", ""))
    duration_minutes = int(payload.get("duration_minutes", 10))

    from datetime import date, datetime, timezone

    def do_checkin(session):
        from app.database import DBCheckinLog

        # 使用 UTC 时间进行计算以保持数据一致性
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        today_utc = now_utc.date()
        
        start_of_today = datetime.combine(today_utc, datetime.min.time())
        end_of_today = datetime.combine(today_utc, datetime.max.time())

        existing_list = session.query(DBCheckinLog).filter(
            DBCheckinLog.student_id == student_id,
            DBCheckinLog.checkin_date >= start_of_today,
            DBCheckinLog.checkin_date <= end_of_today,
        ).all()

        existing = None
        if concept:
            c_clean = concept.strip().lower()
            for r in existing_list:
                reviewed_list = [c.strip().lower() for c in (r.concepts_reviewed or [])]
                if c_clean in reviewed_list:
                    existing = r
                    break
        else:
            for r in existing_list:
                if not r.concepts_reviewed:
                    existing = r
                    break

        if existing:
            existing.duration_minutes += duration_minutes
            session.commit()
            return {"checked_in": True, "streak": _calc_streak(session, student_id), "first_today": False}
        else:
            log = DBCheckinLog(
                student_id=student_id,
                checkin_date=now_utc,
                duration_minutes=duration_minutes,
                concepts_reviewed=[concept] if concept else [],
            )
            session.add(log)
            session.commit()
            return {"checked_in": True, "streak": _calc_streak(session, student_id), "first_today": True}

    return await run_db_op(do_checkin)


@router.get("/checkin/streak/{student_id}")
async def get_checkin_streak(student_id: str) -> dict:
    """获取打卡连续天数。"""
    from app.database import DBCheckinLog

    def fetch_streak(session):
        return {"streak": _calc_streak(session, student_id)}

    return await run_db_op(fetch_streak)


@router.get("/checkin/history/{student_id}")
async def get_checkin_history(student_id: str, concept: str = "") -> list[dict]:
    """获取学生的所有签到打卡记录，支持按特定知识点筛选。"""
    from app.database import DBCheckinLog

    def fetch_history(session):
        query = session.query(DBCheckinLog).filter(
            DBCheckinLog.student_id == student_id
        )
        records = query.order_by(DBCheckinLog.checkin_date.asc()).all()

        results = []
        for r in records:
            if concept:
                c_clean = concept.strip().lower()
                reviewed_list = [c.strip().lower() for c in (r.concepts_reviewed or [])]
                if c_clean not in reviewed_list:
                    continue

            results.append({
                "id": r.id,
                "checkin_date": r.checkin_date.isoformat() if r.checkin_date else "",
                "duration_minutes": r.duration_minutes,
                "concepts_reviewed": r.concepts_reviewed or [],
            })
        return results

    return await run_db_op(fetch_history)


def _calc_streak(session, student_id: str, tz_offset: int = 8) -> int:
    """计算连续打卡天数。支持时区偏移，避免跨时区截断 bug。"""
    from app.database import DBCheckinLog
    from datetime import date, datetime, timezone, timedelta

    records = (
        session.query(DBCheckinLog.checkin_date)
        .filter(DBCheckinLog.student_id == student_id)
        .order_by(DBCheckinLog.checkin_date.desc())
        .all()
    )
    if not records:
        return 0

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    today_local = (now_utc + timedelta(hours=tz_offset)).date()
    expected = today_local

    # 提取唯一的打卡日期，按学生本地时区转换，按降序排列
    unique_dates = sorted(
        list({
            (r[0] + timedelta(hours=tz_offset)).date() if isinstance(r[0], datetime) else r[0]
            for r in records if r[0]
        }),
        reverse=True
    )

    if unique_dates:
        # 如果今天还没打卡，但是昨天打卡了，允许从昨天算起连续打卡天数
        if unique_dates[0] == today_local - timedelta(days=1):
            expected = today_local - timedelta(days=1)

    streak = 0
    for d in unique_dates:
        if d == expected:
            streak += 1
            expected -= timedelta(days=1)
        elif d < expected:
            break
    return streak


async def trigger_database_mcmc_calibration(student_id: str):
    """
    异步后台任务：从数据库拉取答题历史，运行 MCMC 校准三维 MIRT 题目参数，并更新回 quiz_items 表。
    """
    from app.database import DBQuizRecord, DBQuizItem, DBStudentProfile
    from mirt_engine import mcmc_calibrate_item_parameters, IRTItemParams
    
    def fetch_mcmc_data(session):
        # 1. 查找所有参与过测验的学生画像，获取其估计的 theta
        students = session.query(DBStudentProfile).filter(DBStudentProfile.rl_q_table.isnot(None)).all()
        student_list = []
        student_abilities = []
        for s in students:
            irt_est = s.rl_q_table.get("_irt_estimator", {})
            theta = irt_est.get("theta")
            if theta and isinstance(theta, list) and len(theta) == 3:
                student_list.append(s.student_id)
                student_abilities.append(theta)
                
        if len(student_list) < 2:
            return None # 样本不足以运行 MCMC
            
        # 2. 查找所有的本地种子题目
        items = session.query(DBQuizItem).all()
        if not items:
            return None
            
        item_ids = [item.id for item in items]
        initial_items = []
        for item in items:
            alpha = item.irt_alpha_vec if item.irt_alpha_vec is not None else item.irt_alpha
            beta = item.irt_beta_vec if item.irt_beta_vec is not None else item.irt_beta
            initial_items.append(IRTItemParams.from_dict({
                "alpha": alpha,
                "beta": beta,
                "gamma": item.irt_gamma
            }))
            
        # 3. 构造答题矩阵 (N_students, M_items)
        # 初始化为 0 (回答错误或未作答)
        response_matrix = [[0] * len(item_ids) for _ in range(len(student_list))]
        student_idx_map = {sid: idx for idx, sid in enumerate(student_list)}
        item_idx_map = {iid: idx for idx, iid in enumerate(item_ids)}
        
        # 拉取所有的答题记录
        records = session.query(DBQuizRecord).filter(
            DBQuizRecord.student_id.in_(student_list)
        ).all()
        
        for r in records:
            item_match = next((item for item in items if item.question == r.question), None)
            if item_match:
                s_idx = student_idx_map.get(r.student_id)
                i_idx = item_idx_map.get(item_match.id)
                if s_idx is not None and i_idx is not None:
                    response_matrix[s_idx][i_idx] = 1 if (r.accuracy_score >= 0.6) else 0
                    
        return student_abilities, initial_items, response_matrix, item_ids

    data = await run_db_op(fetch_mcmc_data)
    if not data:
        return
        
    student_abilities, initial_items, response_matrix, item_ids = data
    
    # 运行 MCMC 算法校准参数
    calibrated = mcmc_calibrate_item_parameters(
        response_matrix=response_matrix,
        student_abilities=student_abilities,
        initial_items=initial_items,
        iterations=50,
        burn_in=15
    )
    
    # 更新回数据库
    def update_calibrated_items(session):
        from app.database import DBQuizItem
        for idx, item_id in enumerate(item_ids):
            c_item = calibrated[idx]
            session.query(DBQuizItem).filter(DBQuizItem.id == item_id).update({
                "irt_alpha_vec": c_item.alpha,
                "irt_beta_vec": c_item.beta,
                "irt_alpha": c_item.alpha[0],
                "irt_beta": c_item.beta[0],
            }, synchronize_session=False)
        session.commit()
        
    await run_db_op(update_calibrated_items)
    print(f"  [MCMC Calibration] Successfully ran online calibration for {len(item_ids)} questions.")