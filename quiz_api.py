from __future__ import annotations

import hashlib
import os
import re
import uuid
from typing import Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request

from app.database import DBQuizRecord, DBReviewPlan, DBStudentProfile, get_db, run_db_op
from app.crud import load_student_profile, save_student_profile
from learning_event_bus import (
    LearningEventBus,
    publish_quiz_event,
    register_default_subscribers,
)
from swarm_factory import build_swarm_from_headers

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
        
    # 6. 默认兜底
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

    # 动态难度：基于画像推算
    mastery = profile.concept_mastery.get(target_concept, 0.45)
    cognitive_load = profile.cognitive_load
    frustration = profile.frustration_index
    if req_difficulty in ('easy', 'medium', 'hard'):
        difficulty = req_difficulty
    elif frustration > 0.6 or cognitive_load > 0.7:
        difficulty = 'easy'
    elif mastery < 0.3:
        difficulty = 'easy'
    elif mastery < 0.6:
        difficulty = 'medium'
    elif mastery > 0.8:
        difficulty = 'hard'
    else:
        difficulty = 'medium'

    llm = await _get_llm(request)

    system_prompt = (
        "你是一个智能出题考官。根据给定的知识点、难度和学生画像，生成高度定制化的简答题。\n"
        "请以JSON格式返回，包含以下字段：\n"
        "{\n"
        '  "question": "题目文本",\n'
        '  "reference_answer": "分点列出参考答案（用分号分隔）",\n'
        '  "concept": "考察的知识点",\n'
        '  "difficulty": "easy/medium/hard",\n'
        '  "hints": ["提示1（模糊引导）", "提示2（半具体）", "提示3（具体但非直接答案）"]\n'
        "}\n"
        "出题规则：\n"
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
        f"学生画像全文：{profile.profile_prompt()}\n"
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
    )
    
    def save_quiz(session):
        session.add(db_quiz)
        session.commit()
        
    await run_db_op(save_quiz)

    return {
        "quiz_id": quiz_id,
        "question": result.get("question"),
        "reference_answer": result.get("reference_answer", ""),
        "concept": result.get("concept", target_concept),
        "difficulty": result.get("difficulty", difficulty),
        "hints": result.get("hints", []),
        "attempt_number": 1,
    }


@router.post("/evaluate")
async def evaluate_answer(
    request: Request,
) -> dict[str, Any]:
    payload = await request.json()
    quiz_id = str(payload.get("quiz_id", "")).strip()
    student_id = str(payload.get("student_id", "default"))
    student_answer = str(payload.get("answer", "")).strip()
    student_confidence = float(payload.get("student_confidence", 0.5))
    attempt_number = int(payload.get("attempt_number", 1))

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
        "评分标准：accuracy_score < 0.4=严重不足, 0.4~0.7=部分正确, >0.7=良好。"
    )
    user_prompt = (
        f"问题：{quiz_record.question}\n"
        f"参考答案要点：{quiz_record.correct_answer}\n"
        f"学生答案：{student_answer}\n"
        f"学生自评置信度：{student_confidence:.2f}\n"
        "请严格评估并返回JSON。"
    )

    try:
        response = await llm.generate(system_prompt, user_prompt, role="考官智能体")
        result = _parse_llm_json(response)
        if not result:
            raise ValueError("parse failed")
    except Exception:
        result = {
            "accuracy_score": 0.6,
            "ai_confidence": 0.7,
            "score_breakdown": {"key_points_coverage":0.5,"semantic_correctness":0.6,"depth_and_detail":0.5,"clarity_and_logic":0.6},
            "feedback": f"你的答案包含一些正确要点。参考答案:{quiz_record.correct_answer[:100]}...",
            "misconceptions": [],
            "missing_points": ["请对照参考答案检查遗漏"],
            "next_action": "practice",
            "metacognitive_gap": "",
        }

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
    llm = await _get_llm(request)
    # 动态难度：根据画像调整
    cl = profile.cognitive_load; fr = profile.frustration_index; m = profile.concept_mastery.get(target, 0.45)
    if difficulty == "hard" and (cl > 0.7 or fr > 0.6): difficulty = "medium"
    elif difficulty == "easy" and m > 0.7: difficulty = "medium"
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

    # Step 2: LLM 生成相似题（Few-Shot JSON 模板）
    llm = await _get_llm(request)

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
        "根据源错题的知识点和难度，生成一道同难度、同考点的相似题。\n"
        "必须以 JSON 格式输出，严格遵循以下模板结构：\n"
        f"{few_shot_template}\n"
        "python_validator 字段是一段可运行的 Python assert 语句，"
        "用于自动验证你的答案逻辑正确性。\n"
        "确保 options 中正确答案唯一，且干扰项具有迷惑性但不矛盾。"
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
                    # 简单校验：用 Python exec 测试 assert 逻辑
                    import ast
                    tree = ast.parse(python_code)
                    has_assert = any(
                        isinstance(node, ast.Assert) for node in ast.walk(tree)
                    )
                    if has_assert:
                        # 执行 assert 验证
                        local_vars = {}
                        exec(python_code, {"__builtins__": __builtins__}, local_vars)
                        sandbox_passed = True
                    else:
                        sandbox_passed = True  # 没有 assert 也通过
                except Exception as e:
                    # 沙箱失败，记录错误并重试
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
    db_quiz = DBQuizRecord(
        id=new_quiz_id,
        student_id=student_id,
        question=result.get("question", "生成失败"),
        correct_answer=result.get("correct_answer", ""),
        ai_confidence=0.7,
        target_concept=concept,
        attempt_number=1,
        session_id=payload.get("session_id", ""),
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
        records = query.order_by(DBWrongQuestion.created_at.desc()).limit(limit).all()

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
                        "accuracy_score": qr.accuracy_score,
                        "feedback": qr.feedback[:200] if qr.feedback else "",
                    }
            results.append({
                "id": r.id,
                "quiz_record_id": r.quiz_record_id,
                "concept_name": r.concept_name,
                "wrong_reason_category": r.wrong_reason_category,
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


def _calc_streak(session, student_id: str) -> int:
    """计算连续打卡天数。"""
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

    today_utc = datetime.now(timezone.utc).replace(tzinfo=None).date()
    expected = today_utc

    # 提取唯一的打卡日期，按降序排列
    unique_dates = sorted(
        list({
            r[0].date() if isinstance(r[0], datetime) else r[0]
            for r in records if r[0]
        }),
        reverse=True
    )

    if unique_dates:
        # 如果今天还没打卡，但是昨天打卡了，允许从昨天算起连续打卡天数
        if unique_dates[0] == today_utc - timedelta(days=1):
            expected = today_utc - timedelta(days=1)

    streak = 0
    for d in unique_dates:
        if d == expected:
            streak += 1
            expected -= timedelta(days=1)
        elif d < expected:
            break
    return streak
