from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, HTTPException
from app.database import run_db_op
from app.crud import load_student_profile, save_student_profile
from swarm_factory import build_swarm_from_headers

# 知识点依赖图：concept -> [prerequisites]
KNOWLEDGE_DAG: dict[str, list[str]] = {
    "池化层": ["卷积核", "特征图"],
    "最大池化": ["池化层"],
    "平均池化": ["池化层"],
    "卷积核": ["反向传播"],
    "特征图": ["卷积核"],
    "反向传播": ["链式法则", "梯度下降"],
    "链式法则": ["梯度下降"],
    "梯度下降": ["线性回归"],
    "逻辑回归": ["线性回归", "梯度下降"],
    "线性回归": ["机器学习"],
    "决策树": ["机器学习"],
    "支持向量机": ["线性回归", "机器学习"],
    "过拟合": ["正则化", "交叉验证"],
    "正则化": ["线性回归"],
    "交叉验证": ["机器学习"],
    "机器学习": [],
    "监督学习": ["机器学习"],
    "数据预处理": ["机器学习"],
    "特征工程": ["数据预处理"],
    "模型评估": ["机器学习"],
    "混淆矩阵": ["模型评估"],
    "朴素贝叶斯": ["机器学习"],
    "Transformer": ["注意力机制", "反向传播"],
    "注意力机制": ["神经网络"],
    "神经网络": ["反向传播", "梯度下降"],
    "卷积神经网络": ["神经网络", "卷积核", "池化层"],
}

router = APIRouter(prefix="/api/profile", tags=["profile"])


DIMENSION_DIAGNOSIS = {
    "knowledge_mastery": {
        "high": "基础概念掌握扎实，能够支撑后续进阶学习",
        "medium": "部分概念掌握不够牢固，存在知识盲区需要填补",
        "low": "基础知识存在较大缺口，建议优先补习前置概念",
    },
    "misconception_profile": {
        "high": "未发现显著的误概念或易混淆点，概念区分清晰",
        "medium": "存在少量易混淆的概念对，需要针对性辨析",
        "low": "多个概念之间存在混淆，建议通过反例对比和辨析题加以澄清",
    },
    "understanding_fluency_transfer": {
        "high": "理解-迁移能力较好，能够将所学知识应用到新场景",
        "medium": "理解层面尚可，但知识迁移能力有待加强",
        "low": "停留在记忆层面，难以将知识迁移到实际问题中",
    },
    "cognitive_processing": {
        "high": "认知负荷适中，能够有效处理多步骤推理任务",
        "medium": "认知负荷略高，复杂多步推理时容易遗漏条件",
        "low": "认知负荷明显偏高，建议将复杂任务拆解为小步骤",
    },
    "learning_strategy": {
        "high": "具备有效的学习策略，能够进行主动检索和复盘",
        "medium": "学习策略有待改进，存在依赖看答案或被动学习的倾向",
        "low": "缺乏有效的学习策略，需要显式训练检索练习和间隔复习方法",
    },
    "metacognition": {
        "high": "元认知能力较强，自我评估与实际表现较为一致",
        "medium": "自我评估偶有偏差，需要加强题前自评和题后校准训练",
        "low": "自我判断与实际表现差距较大，建议每次答题前先记录自评置信度",
    },
    "motivation_and_purpose": {
        "high": "学习目标明确，有较强的内在驱动力",
        "medium": "有基本的学习动机，但目标感可以进一步强化",
        "low": "学习目标不够清晰，需要帮助建立知识与个人发展的连接",
    },
    "affect_resilience": {
        "high": "情绪状态稳定，学习信心充足",
        "medium": "偶有挫败感，需要及时的正向反馈和成功体验积累",
        "low": "挫败感较为明显，建议降低当前任务难度，先建立成功体验",
    },
    "interaction_preference": {
        "high": "已明确捕捉到有效的互动偏好，可按偏好切换教学方式",
        "medium": "互动偏好尚在形成中，需要在教学中进一步观察",
        "low": "互动偏好信息不足，建议主动询问学生的喜好学习方式",
    },
    "learning_context": {
        "high": "学习情境明确，有助于制定贴合实际的计划",
        "medium": "学习情境部分明确，可以进一步了解可用时间和课程要求",
        "low": "学习情境信息不足，建议了解学生的课程安排和可用学习时间",
    },
}


def _build_dimension_analysis(dimension_key: str, state) -> dict[str, Any]:
    """构建单个维度的分析文本"""
    score = state.score if state else 0.5
    if score >= 0.66:
        level = "high"
    elif score >= 0.33:
        level = "medium"
    else:
        level = "low"

    diagnosis = DIMENSION_DIAGNOSIS.get(dimension_key, {}).get(level, "状态待评估")
    label = state.label if state else dimension_key

    evidence_fragments = state.evidence_fragments[:3] if state and hasattr(state, 'evidence_fragments') else []
    interventions = state.recommended_interventions[:3] if state and hasattr(state, 'recommended_interventions') else []

    return {
        "key": dimension_key,
        "label": label,
        "score": round(score, 2),
        "level": level,
        "diagnosis": diagnosis,
        "evidence": evidence_fragments,
        "suggestions": interventions,
    }


def _build_weak_point_analysis(profile) -> list[dict[str, Any]]:
    """分析薄弱点的根因"""
    weak_points = profile.weak_points or []
    mastery = profile.concept_mastery or {}
    causes = profile.learning_state_causes or {}

    # 根因映射
    cause_map = {
        "prerequisite_gap": "前置知识缺口: 该概念依赖的前置知识未掌握",
        "misconception": "概念混淆: 存在相似概念的混淆，需要对比辨析",
        "cognitive_load": "认知负荷过高: 概念复杂度较高，需要分步拆解",
        "strategy_gap": "学习策略不足: 需要更有效的学习和复习方法",
        "affective_barrier": "情绪阻滞: 挫败感影响了学习信心",
    }

    results = []
    for point in weak_points:
        score = mastery.get(point, 0.0)
        # 找到最匹配的根因
        root_causes = []
        sorted_causes = sorted(causes.values(), key=lambda c: c.percentage, reverse=True)
        for cause in sorted_causes[:2]:
            if cause.key in cause_map:
                root_causes.append({
                    "cause": cause.label,
                    "detail": cause_map[cause.key],
                    "percentage": cause.percentage,
                })

        results.append({
            "concept": point,
            "mastery": round(score, 2),
            "root_causes": root_causes or [{"cause": "待诊断", "detail": "需要更多交互数据来准确诊断根因", "percentage": 0}],
        })

    return results


@router.get("/{student_id}")
async def get_profile(
    student_id: str,
    request: Request,
) -> dict[str, Any]:
    swarm = build_swarm_from_headers(request.headers)
    profile = swarm.profile_store.get(student_id)

    if not profile:
        profile = await run_db_op(load_student_profile, student_id)
        swarm.profile_store[student_id] = profile

    return {
        "student_id": student_id,
        "major": getattr(profile, "major", ""),
        "target_course": getattr(profile, "target_course", "机器学习导论"),
        "cognitive_style": getattr(profile, "cognitive_style", ""),
        "learning_goals": getattr(profile, "learning_goals", [])[:5],
        "weak_points": getattr(profile, "weak_points", [])[:8],
        "interaction_preferences": getattr(profile, "interaction_preferences", [])[:5],
        "concept_mastery": {
            k: round(v, 2) for k, v in (getattr(profile, "concept_mastery", {}) or {}).items()
        },
        "dimensions": {
            k: {"score": round(v.score, 2), "status": v.status, "label": v.label}
            for k, v in (getattr(profile, "dimension_states", {}) or {}).items()
        },
        "causes": {
            k: {"percentage": round(v.percentage, 1), "label": v.label}
            for k, v in (getattr(profile, "learning_state_causes", {}) or {}).items()
        },
        "cognitive_load": round(getattr(profile, "cognitive_load", 0.0), 2),
        "focus_level": round(getattr(profile, "focus_level", 0.0), 2),
        "knowledge_traces": {
            k: {"mastery": round(v.mastery, 2), "attempts": v.attempts, "correct": v.correct_attempts}
            for k, v in (getattr(profile, "knowledge_traces", {}) or {}).items()
        } if hasattr(profile, "knowledge_traces") else {},
        "misconception_patterns": getattr(profile, "misconception_patterns", {}),
    }


@router.get("/{student_id}/analysis")
async def get_profile_analysis(
    student_id: str,
    request: Request,
) -> dict[str, Any]:
    """获取学生画像的多维度文本分析报告"""
    swarm = build_swarm_from_headers(request.headers)
    profile = swarm.profile_store.get(student_id)

    if not profile:
        profile = await run_db_op(load_student_profile, student_id)
        swarm.profile_store[student_id] = profile

    # 1. 学生背景概览
    background = {
        "student_id": student_id,
        "major": profile.major or profile.major_preference or "未设置",
        "target_course": profile.target_course or "未设置",
        "cognitive_style": profile.cognitive_style or "未诊断",
        "learning_goals": profile.learning_goals[:5] if profile.learning_goals else [],
        "learning_preferences": profile.interaction_preferences[:5] if profile.interaction_preferences else [],
        "motivation_type": profile.motivation_type or "未诊断",
        "frustration_index": round(profile.frustration_index, 2),
        "engagement_level": round(profile.engagement_level, 2),
    }

    # 2. 各维度分析
    dimensions = {}
    for key in DIMENSION_DIAGNOSIS:
        state = profile.dimension_states.get(key)
        dimensions[key] = _build_dimension_analysis(key, state)

    # 3. 学习状态成因分析
    causes = {}
    sorted_causes = sorted(
        profile.learning_state_causes.values(),
        key=lambda c: c.percentage,
        reverse=True,
    )
    for cause in sorted_causes:
        causes[cause.key] = {
            "label": cause.label,
            "percentage": round(cause.percentage, 1),
            "confidence": round(cause.confidence, 2),
            "evidence_fragments": cause.evidence_fragments[:3],
            "interventions": cause.recommended_interventions[:3],
        }

    # 4. 薄弱点根因分析
    weak_analysis = _build_weak_point_analysis(profile)

    # 5. 个性化教学建议汇总
    summary_suggestions = []
    for dim_key, dim_data in dimensions.items():
        if dim_data["level"] == "low":
            summary_suggestions.append(f"[{dim_data['label']}] {dim_data['diagnosis']}")
            for s in dim_data["suggestions"]:
                summary_suggestions.append(f"  → {s}")
    if not summary_suggestions:
        summary_suggestions.append("当前各维度状态良好，建议保持当前学习节奏。")

    return {
        "background": background,
        "dimensions": dimensions,
        "causes": causes,
        "weak_analysis": weak_analysis,
        "suggestions": summary_suggestions,
        "updated_at": profile.last_update_timestamp if hasattr(profile, 'last_update_timestamp') else "",
    }


@router.get("/{student_id}/learning-path")
async def get_learning_path(
    student_id: str,
    request: Request,
) -> dict[str, Any]:
    """获取结构化学习路径分析（基于拓扑排序链条式推进）"""
    swarm = build_swarm_from_headers(request.headers)
    profile = swarm.profile_store.get(student_id)

    if not profile:
        profile = await run_db_op(load_student_profile, student_id)
        swarm.profile_store[student_id] = profile

    mastery = profile.concept_mastery or {}

    # === 拓扑排序：计算每个概念的学习层级 ===
    all_concepts = set(mastery.keys()) | set(KNOWLEDGE_DAG.keys())
    all_concepts.discard("")
    all_concepts.discard(None)

    concept_tier: dict[str, int] = {}
    remaining = set(all_concepts)
    changed = True
    while remaining and changed:
        changed = False
        for c in list(remaining):
            prereqs = KNOWLEDGE_DAG.get(c, [])
            prereq_tiers = [concept_tier.get(p, -1) for p in prereqs]
            if all(pt >= 0 for pt in prereq_tiers):
                max_pt = max(prereq_tiers) if prereq_tiers else -1
                concept_tier[c] = max_pt + 1
                remaining.remove(c)
                changed = True

    # 按层级分组
    tiers: dict[int, list[dict]] = {}
    for c, t in concept_tier.items():
        if t not in tiers:
            tiers[t] = []
        score = mastery.get(c, 0.0)
        prereqs = KNOWLEDGE_DAG.get(c, [])
        prereqs_ready = all(mastery.get(p, 0) >= 1 if p == "无" else mastery.get(p, 0) >= 0.4 for p in prereqs)
        mastered = score >= 0.7

        bloom = "记忆" if score < 0.20 else "理解" if score < 0.40 else "应用" if score < 0.60 else "分析" if score < 0.75 else "评价" if score < 0.90 else "创造"

        tiers[t].append({
            "concept": c,
            "mastery": round(score, 2),
            "percentage": round(score * 100),
            "bloom_level": bloom,
            "prerequisites": prereqs,
            "prereqs_ready": prereqs_ready,
            "mastered": mastered,
            "status": "已完成" if mastered else ("当前可学" if prereqs_ready else "前置未完成"),
        })

    # 概念指引库（每个概念对应的学习引导）
    CONCEPT_GUIDANCE = {
        "机器学习": {"summary": "机器学习的基础概念和分类", "strategy": "先理解监督/无监督/强化学习的区别，再看典型应用场景", "verify": "能说出三种学习类型的定义和至少一个典型算法"},
        "线性回归": {"summary": "使用线性模型拟合连续值输出", "strategy": "从最小二乘法入手，理解损失函数和梯度下降的关系", "verify": "能手动推导一元线性回归的闭式解"},
        "梯度下降": {"summary": "通过梯度迭代优化模型参数", "strategy": "理解学习率的影响，观察不同学习率下的收敛行为", "verify": "能用代码实现批量梯度下降和随机梯度下降"},
        "逻辑回归": {"summary": "利用Sigmoid函数做二分类", "strategy": "理解为什么用交叉熵而非均方误差作为损失函数", "verify": "能对比逻辑回归和线性回归的异同"},
        "反向传播": {"summary": "链式法则在神经网络参数更新中的应用", "strategy": "先手算一个2层网络的完整反向传播过程", "verify": "能写出任意层数的反向传播伪代码"},
        "链式法则": {"summary": "复合函数求导的核心法则", "strategy": "复习微积分中的链式法则，理解计算图的概念", "verify": "能在计算图上标出每条路径的梯度"},
        "决策树": {"summary": "基于树结构的分类与回归方法", "strategy": "理解信息增益和基尼系数的计算，对比ID3和CART", "verify": "能手动计算一个简单数据集的最优划分特征"},
        "支持向量机": {"summary": "通过最大化间隔寻找最优分类超平面", "strategy": "从线性可分SVM开始，理解间隔最大化的几何意义", "verify": "能说明核函数的作用和常见核函数的适用场景"},
        "过拟合": {"summary": "模型过度学习训练数据导致泛化能力下降", "strategy": "理解偏差-方差权衡，学会用学习曲线诊断", "verify": "能列出3种以上缓解过拟合的方法"},
        "正则化": {"summary": "通过约束参数大小防止过拟合", "strategy": "对比L1和L2正则化的效果差异", "verify": "能说明L1为什么会产生稀疏解"},
        "交叉验证": {"summary": "通过数据划分更可靠地评估模型性能", "strategy": "理解K折交叉验证的原理和分层抽样", "verify": "能说明K折交叉验证和留出法的优缺点"},
        "模型评估": {"summary": "使用多种指标全面评价模型性能", "strategy": "掌握混淆矩阵、精确率、召回率、F1、AUC等指标", "verify": "能在不同业务场景下选择合适的评估指标"},
        "混淆矩阵": {"summary": "分类模型预测结果的二维统计表", "strategy": "理解TP/FP/TN/FN的含义以及派生指标", "verify": "能从混淆矩阵计算出精确率和召回率"},
        "朴素贝叶斯": {"summary": "基于贝叶斯定理和条件独立假设的分类器", "strategy": "理解先验概率、似然和后验概率的关系", "verify": "能说明独立性假设在什么情况下不成立"},
        "神经网络": {"summary": "由多层神经元组成的非线性模型", "strategy": "从感知机开始，理解激活函数的作用", "verify": "能用框架搭建一个简单的全连接网络"},
        "卷积神经网络": {"summary": "专门处理网格状数据的深度网络", "strategy": "理解卷积核、池化层、特征图的概念", "verify": "能计算任意输入经过卷积后的输出尺寸"},
        "池化层": {"summary": "对特征图进行降采样的操作", "strategy": "理解最大池化和平均池化的区别", "verify": "能说明池化层为什么能提供平移不变性"},
        "最大池化": {"summary": "取局部区域的最大值作为输出", "strategy": "对比最大池化和平均池化的适用场景", "verify": "能手算2×2最大池化的输出"},
        "平均池化": {"summary": "取局部区域的平均值作为输出", "strategy": "理解平均池化在全局特征聚合中的作用", "verify": "能说明平均池化为什么能保留背景信息"},
        "卷积核": {"summary": "对输入进行特征提取的滤波器", "strategy": "理解卷积运算的数学定义和滑动窗口机制", "verify": "能说明1×1卷积核的作用"},
        "特征图": {"summary": "卷积操作后输出的特征表示", "strategy": "理解通道数、尺寸变化与卷积核数量的关系", "verify": "能计算卷积前后特征图的尺寸变化"},
        "Transformer": {"summary": "基于自注意力机制的序列模型", "strategy": "从注意力机制开始，理解QKV的计算过程", "verify": "能说明多头注意力的优势"},
        "注意力机制": {"summary": "让模型动态关注输入中的重要部分", "strategy": "理解self-attention和cross-attention的区别", "verify": "能写出缩放点积注意力的公式"},
        "数据预处理": {"summary": "对原始数据进行清洗和转换", "strategy": "掌握缺失值处理、标准化、归一化的方法", "verify": "能说明StandardScaler和MinMaxScaler的区别"},
        "特征工程": {"summary": "从原始数据中构造更有预测力的特征", "strategy": "理解特征选择、特征提取和特征构造的区别", "verify": "能列出3种以上特征选择方法"},
        "监督学习": {"summary": "使用标注数据训练模型的学习范式", "strategy": "对比分类和回归任务的区别", "verify": "能列举5种以上监督学习算法"},
        "卷积运算": {"summary": "卷积核在输入上滑动计算点积的操作", "strategy": "理解卷积和互相关的区别", "verify": "能手动计算一次2D卷积运算"},
    }

    # 添加引导信息到每个节点
    guidance = CONCEPT_GUIDANCE
    for t in sorted(tiers.keys()):
        for node in tiers[t]:
            g = guidance.get(node["concept"], {})
            node["guidance"] = {
                "summary": g.get("summary", f"学习 {node['concept']}"),
                "strategy": g.get("strategy", "结合理论学习和代码实践"),
                "verify": g.get("verify", "能用自己的话解释核心概念"),
            }
            # 学习时长估算（基于层级和复杂度）
            if t <= 1:
                node["estimated_minutes"] = 45
            elif t <= 3:
                node["estimated_minutes"] = 60
            else:
                node["estimated_minutes"] = 90

    # 完整链条
    learning_chain = []
    step = 0
    for t in sorted(tiers.keys()):
        for node in tiers[t]:
            step += 1
            learning_chain.append({"step": step, "tier": t, **node})

    # 缺口链追溯
    gap_chains = []
    for node in learning_chain:
        if node["mastered"] or node["prereqs_ready"]:
            continue

        def _trace_gaps(c, visited=None, depth=0):
            if visited is None:
                visited = set()
            if depth > 4 or c in visited:
                return []
            visited.add(c)
            results = []
            for p in KNOWLEDGE_DAG.get(c, []):
                if mastery.get(p, 0) < 0.4:
                    results.append({"concept": p, "mastery": round(mastery.get(p, 0), 2), "depth": depth + 1, "action": f"需先掌握「{p}」"})
                    results.extend(_trace_gaps(p, visited, depth + 1))
            return results

        gaps = _trace_gaps(node["concept"])
        if gaps:
            gap_chains.append({"target": node["concept"], "chain": gaps})

    # 下一步推荐
    next_steps = [n for n in learning_chain if not n["mastered"] and n["prereqs_ready"]]

    # 三阶段
    stages = [
        {"name": "入门基础", "range": "Tier 0-1", "concepts": [n["concept"] for n in learning_chain if n["tier"] <= 1]},
        {"name": "核心算法", "range": "Tier 2-3", "concepts": [n["concept"] for n in learning_chain if 2 <= n["tier"] <= 3]},
        {"name": "进阶应用", "range": "Tier 4+", "concepts": [n["concept"] for n in learning_chain if n["tier"] >= 4]},
    ]

    # 策略建议（只针对当前可学的薄弱点）
    strategy_suggestions = []
    for node in next_steps[:5]:
        if node["mastery"] < 0.4:
            s = []
            if node["mastery"] < 0.3:
                s.append("先用示范题建立基本理解")
            else:
                s.append("用对比辨析消除混淆")
                s.append("做 2-3 道变式题验证")
            strategy_suggestions.append({"concept": node["concept"], "mastery": node["percentage"], "step": node["step"], "suggestions": s})

    # 进度摘要（教师看板用）
    progress_summary = {
        "total_concepts": len(learning_chain),
        "mastered": sum(1 for n in learning_chain if n["mastered"]),
        "in_progress": sum(1 for n in learning_chain if not n["mastered"] and n["prereqs_ready"]),
        "locked": sum(1 for n in learning_chain if not n["mastered"] and not n["prereqs_ready"]),
        "next_up": [n["concept"] for n in next_steps[:3]],
    }

    return {
        "student_id": student_id,
        "learning_chain": learning_chain,
        "stages": stages,
        "next_steps": next_steps[:5],
        "gap_chains": gap_chains[:5],
        "strategy_suggestions": strategy_suggestions[:5],
        "progress_summary": progress_summary,
        "concept_tiers": {str(k): [n["concept"] for n in v] for k, v in sorted(tiers.items())},
        "updated_at": profile.last_update_timestamp if hasattr(profile, 'last_update_timestamp') else "",
    }


@router.post("/{student_id}")
async def update_profile(
    student_id: str,
    request: Request,
) -> dict[str, str]:
    payload = await request.json()
    swarm = build_swarm_from_headers(request.headers)
    profile = swarm.profile_store.get(student_id)

    if not profile:
        profile = await run_db_op(load_student_profile, student_id)
        swarm.profile_store[student_id] = profile

    major = payload.get("major")
    if major:
        profile.major = major
        profile.major_preference = major

    course = payload.get("target_course")
    if course:
        profile.target_course = course

    goals = payload.get("learning_goals")
    if goals and isinstance(goals, list):
        profile.learning_goals = list(set(profile.learning_goals + goals))[:5]

    preferences = payload.get("interaction_preferences")
    if preferences and isinstance(preferences, list):
        existing = list(profile.interaction_preferences or [])
        profile.interaction_preferences = list(set(existing + preferences))[:5]

    profile._refresh_dynamic_profile()
    await run_db_op(save_student_profile, profile)

    return {"status": "updated", "student_id": student_id}
