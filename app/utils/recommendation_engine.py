from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session
from app.database import DBStudentProfile, DBKnowledgeDocument
from rag_engine import hybrid_rag
from models import Evidence, EvidenceModality

# 概念对应视频微课配置表
CONCEPT_VIDEO_MAP = {
    "池化层": {
        "title": "最大池化与下采样三维演示微课",
        "url": "/api/v1/video/stream?concept=池化层",
        "duration": "03:45",
    },
    "最大池化": {
        "title": "最大池化局部计算演算微课",
        "url": "/api/v1/video/stream?concept=最大池化",
        "duration": "02:15",
    },
    "平均池化": {
        "title": "平均池化在图像特征提取中的应用视频",
        "url": "/api/v1/video/stream?concept=平均池化",
        "duration": "02:50",
    },
    "逻辑回归": {
        "title": "逻辑回归与分类决策边界直观几何演示",
        "url": "/api/v1/video/stream?concept=逻辑回归",
        "duration": "05:10",
    },
    "梯度下降": {
        "title": "梯度下降收敛过程与学习率（步长）效应演示",
        "url": "/api/v1/video/stream?concept=梯度下降",
        "duration": "04:30",
    },
    "反向传播": {
        "title": "反向传播算法中链式求导手算与计算图演示",
        "url": "/api/v1/video/stream?concept=反向传播",
        "duration": "06:15",
    },
    "过拟合": {
        "title": "过拟合、欠拟合与正则化惩罚项直观演示视频",
        "url": "/api/v1/video/stream?concept=过拟合",
        "duration": "04:12",
    },
    "机器学习": {
        "title": "机器学习全流程概览与数据流图示",
        "url": "/api/v1/video/stream?concept=机器学习",
        "duration": "05:00",
    },
    "监督学习": {
        "title": "监督学习中的分类与回归边界区分微课",
        "url": "/api/v1/video/stream?concept=监督学习",
        "duration": "03:20",
    },
    "线性回归": {
        "title": "一元线性回归与最小二乘拟合演算微课",
        "url": "/api/v1/video/stream?concept=线性回归",
        "duration": "04:05",
    }
}


def get_smart_recommendations(
    db: Session,
    student_id: str,
    limit: int = 3
) -> list[dict[str, Any]]:
    """根据学生认知掌握度、薄弱点与交互偏好，自适应推送匹配的学习资源"""
    # 1. 读取学生画像
    profile = db.query(DBStudentProfile).filter(
        DBStudentProfile.student_id == student_id
    ).first()

    if not profile:
        # 兜底 fallback 画像
        class DummyProfile:
            concept_mastery = {"机器学习": 0.35, "线性回归": 0.40}
            learning_goals = ["机器学习", "线性回归"]
            weak_points = ["机器学习"]
            interaction_preferences = ["图示演示"]
            cognitive_style = "图示型"
        profile = DummyProfile()

    mastery = profile.concept_mastery or {}
    goals = profile.learning_goals or []
    weak_points = profile.weak_points or []
    preferences = profile.interaction_preferences or []
    cognitive_style = getattr(profile, "cognitive_style", "") or ""

    # 2. 确定待推荐的目标概念 (ZPD & Weak concepts)
    target_concepts = []
    # 优先选择掌握度较低且属于薄弱点/学习目标的概念
    for c, score in sorted(mastery.items(), key=lambda item: item[1]):
        if score < 0.60:
            target_concepts.append(c)

    # 辅以 weak_points 和 goals
    for wp in weak_points:
        if wp not in target_concepts:
            target_concepts.append(wp)
    for g in goals:
        if g not in target_concepts:
            target_concepts.append(g)

    # 如果都没有，给默认机器学习经典入门概念
    if not target_concepts:
        target_concepts = ["机器学习", "线性回归", "逻辑回归", "梯度下降"]

    # 3. 收集候选资源
    candidates = []

    # 偏好特征判定
    prefers_code = "代码" in preferences or "代码实操" in preferences or "代码型" in cognitive_style
    prefers_visual = "图示" in preferences or "图示演示" in preferences or "视觉" in preferences or "图示型" in cognitive_style
    prefers_video = "短视频" in preferences or "短视频讲解" in preferences or "视频" in preferences or "视频型" in cognitive_style

    for concept in target_concepts[:3]:
        # 3.1 从 Hybrid RAG 检索候选 Evidence (禁用外网检索，加速仪表盘加载)
        bundle = hybrid_rag.retrieve(concept, target=concept, top_k=4, disable_external=True)
        for item in bundle.evidence:
            # 基础分来自 RAG 检索的相关度 score
            base_score = item.score if hasattr(item, "score") else 0.5
            
            # 计算交互风格/模态加权 (Modality Boost)
            boost = 1.0
            resource_type = "document"
            
            # 判定资源类型并加权
            is_code_resource = (
                "code" in item.id.lower() or 
                "python" in item.source.lower() or 
                "```python" in item.content
            )
            
            if is_code_resource:
                resource_type = "code"
                if prefers_code:
                    boost *= 1.50
            elif item.modality == EvidenceModality.IMAGE:
                resource_type = "document" # 图片文档
                if prefers_visual:
                    boost *= 1.50
            else:
                # 默认纯文本讲义/文献
                if prefers_code or prefers_visual or prefers_video:
                    # 匹配度稍降，给特定匹配留出空间
                    boost *= 0.90

            final_score = base_score * boost
            
            candidates.append({
                "concept": concept,
                "score": final_score,
                "resource_type": resource_type,
                "title": item.title,
                "content": item.content,
                "url": item.metadata.get("raw_image_ref") or "",
                "source_name": item.source,
                "badge": "🔥 薄弱强化" if mastery.get(concept, 1.0) < 0.4 else "💡 探索进阶",
                "reason": f"检测到您在概念【{concept}】上掌握度为 {int(mastery.get(concept, 0.4)*100)}%，结合您的学习风格偏好为您定制推送："
            })

        # 3.2 针对弱项概念，如果开启了视频偏好，或者概念有匹配的微课，则插入微课推荐
        if concept in CONCEPT_VIDEO_MAP:
            vinfo = CONCEPT_VIDEO_MAP[concept]
            v_score = 0.75
            if prefers_video:
                v_score *= 1.50  # 视频偏好极大提权
            
            candidates.append({
                "concept": concept,
                "score": v_score,
                "resource_type": "video",
                "title": vinfo["title"],
                "content": f"时长 {vinfo['duration']} · 动态微视频课程，帮助以更直观的方式透彻理解【{concept}】概念的核心机制与图像意义。",
                "url": vinfo["url"],
                "source_name": "EduMatrix 智能微课课件库",
                "badge": "⚡ 微课视频",
                "reason": f"针对概念【{concept}】，根据您的『视频讲解』偏好，为您特别推荐直观微视频课程："
            })

    # 4. 根据排序得分（score）去重并输出前 limit 个结果
    # 按照得分高低从大到小排序
    candidates.sort(key=lambda x: x["score"], reverse=True)
    
    seen_titles = set()
    unique_recommendations = []
    for c in candidates:
        if c["title"] not in seen_titles:
            seen_titles.add(c["title"])
            unique_recommendations.append(c)
            if len(unique_recommendations) >= limit:
                break

    # 如果推荐数量不足，插入默认兜底机器学习项目资源
    if len(unique_recommendations) < limit:
        default_items = [
            {
                "concept": "机器学习",
                "score": 0.1,
                "resource_type": "document",
                "title": "机器学习实践指南",
                "content": "机器学习的核心是从数据中自我学习。在入门阶段，请首先掌握特征工程和模型评估混淆矩阵的概念。",
                "url": "",
                "source_name": "实践指南.md",
                "badge": "💡 探索进阶",
                "reason": "为您推荐机器学习通识性必修讲义："
            },
            {
                "concept": "梯度下降",
                "score": 0.05,
                "resource_type": "code",
                "title": "手动实现梯度下降优化求解器",
                "content": "```python\ndef gradient_descent(x_init, lr, steps):\n    x = x_init\n    for _ in range(steps):\n        grad = 2 * x # 目标函数为 y = x^2\n        x = x - lr * grad\n    return x\n```",
                "url": "",
                "source_name": "梯度下降演算.py",
                "badge": "🔥 薄弱强化",
                "reason": "为您推荐直观的代码演算实操资源："
            }
        ]
        for di in default_items:
            if len(unique_recommendations) >= limit:
                break
            if di["title"] not in seen_titles:
                seen_titles.add(di["title"])
                unique_recommendations.append(di)

    return unique_recommendations
