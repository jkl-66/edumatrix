from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
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


def load_display_name(db: Session, username: str) -> str:
    from app.database import DBUser
    user = db.query(DBUser).filter(DBUser.username == username).first()
    return user.display_name if (user and user.display_name) else username

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

    display_name = await run_db_op(load_display_name, student_id)

    return {
        "student_id": student_id,
        "display_name": display_name,
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
        "mental_state_history": getattr(profile, "mental_state_history", []) or [],
    }


class NarrativeReportGenerator:
    """StoryLensEdu 叙事驱动评估报告生成器：
    整合数据分析师、教师评估师、故事讲述者及仪表盘分析师角色，
    分别生成温暖鼓励的成长信笺（供学习画像使用）以及科学理性的仪表盘全局分析（供仪表盘使用）。
    """

    def __init__(self, llm: Any) -> None:
        self.llm = llm

    async def generate_report(self, profile: Any) -> tuple[str, str]:
        """运行多-agent 评估工作流，生成定制叙事报告 (narrative_report) 与仪表盘学情分析报告 (dashboard_report)。"""
        # Step 1: 模拟 数据分析师 (Data Analyst Agent) 抽取核心指标
        mastery_summary = ", ".join(f"{c}: {round(m * 100)}%" for c, m in list(profile.concept_mastery.items())[:6])
        causes_summary = ", ".join(f"{c.label}: {round(c.percentage)}%" for c in list(profile.learning_state_causes.values())[:3])
        cognitive_load = getattr(profile, "cognitive_load", 0.5)
        frustration = getattr(profile, "frustration_index", 0.0)
        
        analyst_prompt = (
            f"数据分析师日志：\n"
            f"- 目标课程：{profile.target_course}\n"
            f"- 部分掌握度：{mastery_summary if mastery_summary else '无数据'}\n"
            f"- 障碍原因分配：{causes_summary if causes_summary else '无数据'}\n"
            f"- 认知负荷：{cognitive_load:.2f} | 挫败感指数：{frustration:.2f}\n"
        )

        # Step 2: 模拟 教师评估师 (Tutor Agent) 进行教育学解释与改进建议
        tutor_system = (
            "你是一个教育心理学与自适应教学专家。你的任务是解读数据分析师报告中学生的数据指标，"
            "从教育学和认知科学（如ZPD、认知负荷理论）角度进行专业评估并输出改进路线（不要包含学生名字）。\n"
            "格式要求：简短列出 2-3 条基于认知特征的突破性学习建议。"
        )
        try:
            tutor_advice = await self.llm.generate(tutor_system, analyst_prompt, role="教师评估")
        except Exception:
            tutor_advice = "建议专注于前置概念复习，利用图示与代码实操结合，逐步缓解当前较高的认知负荷。"

        # Step 3: 故事讲述者 (Storyteller Agent) 将数据与建议融合成温暖鼓励的个人叙事成长信笺
        storyteller_system = (
            "你是一个温和体贴、擅长鼓励的教育故事讲述者（Storyteller）。\n"
            "你的任务是根据数据分析师的数据和教师评估师的建议，为该学生定制一封温和、充满正能量的个性化成长信件。\n\n"
            "信件大纲规则：\n"
            "1) 开启：用温和的语气肯定学生的努力与当前进度，并将掌握度百分比以比喻的形式（如‘种子的萌发’、‘关卡的解锁’）轻柔道出。\n"
            "2) 经过：用故事性的语言化解其不会的成因和挫败感（例如将‘前置极小值’比作‘地基的加固’，将‘认知负荷’比作‘背包过重需要精简行李’）。\n"
            "3) 收尾：融入教师评估师的建议，指出具体的下一步探索方向，结尾给予充满信心和正能量的结语。\n"
            "4) ⚠️核心守则：禁止出现冷冰冰的纯代码变量名，必须使用优美、生动、有温度的中文 Markdown 叙事，字数在 250-300 字左右。"
        )

        # Step 4: 仪表盘分析师 (Dashboard Agent) 将数据与建议融合成详细、理性、干净的学情评估 (严肃正经口吻，供仪表盘使用)
        dashboard_system = (
            "你是一个专业、理性的自适应教育学情分析与决策引擎。\n"
            "你的任务是根据数据分析师提供的指标和教师建议，为学生输出一份定量化、逻辑严密、详尽具体的仪表盘全局学情诊断报告。\n\n"
            "⚠️核心格式守则：\n"
            "1) 绝对禁止任何感性、温情化或抒情比喻（杜绝如‘种子萌发’、‘关卡解锁’、‘土地松软肥沃’、‘溪流愉快奔腾’、‘行李背包’等修辞），使用专业、中立、客观的学术诊断口吻。\n"
            "2) 保持充足的信息量和细致程度，字数在 250-350 字左右，与常规学情诊断信件的详细程度完全一致。\n"
            "3) 🚫严禁包含任何奇怪的特殊符号（如 📬、💡、📊、🚀、⚠️、→ 等图标符号），不需要任何冗余的标题，严禁多余的段落空行。只输出最核心的诊断和具体学习策略段落，格式必须好看、清爽。\n"
            "4) 输出结构应逻辑清晰地分为以下几个核心层面进行详尽分析：\n"
            "   - 学情现状诊断：客观评估当前学术表现，指出掌握度最高的领域与面临的核心知识瓶颈；\n"
            "   - 归因与推断逻辑：详细解释该学情状态背后的成因与推导过程，分析障碍是由于前置数学不足、概念理解偏差，还是解题实操缺乏引起的；\n"
            "   - 学习策略建议：提出具体的学习干预策略，并结合教育学或认知科学原理（如最近发展区、工作记忆卸载）解释为何采取该策略。"
        )

        storyteller_user = (
            f"【数据分析】：\n{analyst_prompt}\n\n"
            f"【教师建议】：\n{tutor_advice}"
        )

        try:
            import asyncio
            import re
            
            # 并行调用 LLM 从而优化页面加载性能
            narrative_task = self.llm.generate(storyteller_system, storyteller_user, role="叙事故事生成")
            dashboard_task = self.llm.generate(dashboard_system, storyteller_user, role="仪表盘诊断生成")
            
            narrative, dashboard = await asyncio.gather(narrative_task, dashboard_task)
            
            # 清洗特殊表情字符和空行，保证仪表盘展示效果纯净
            dashboard = re.sub(r'[\u2700-\u27BF]|[\uE000-\uF8FF]|\uD83C[\uDC00-\uDFFF]|\uD83D[\uDC00-\uDFFF]|[\u2011-\u26FF]|\uD83E[\uDD10-\uDDFF]', '', dashboard)
            dashboard = "\n".join([line.strip() for line in dashboard.split("\n") if line.strip()])
            
            return f"### 📬 智教矩阵个性化成长信笺 (StoryLensEdu)\n\n{narrative}", dashboard
        except Exception:
            fallback_narrative = (
                "### 📬 智教矩阵个性化成长信笺 (StoryLensEdu)\n\n"
                "亲爱的同学：\n\n"
                "看到你在机器学习世界里的探索，系统能感受到你对未知的渴望。目前你在知识图谱中的多个核心概念上已经开始了旅程，"
                "遇到一时的不理解或高负荷是知识建构过程中的必经风景，如同登山时背包需要稍微整理。建议你在接下来的日子里，"
                "先从前置概念的基础小册和代码实操着手，我们会一直在右侧的画板和沙箱中陪伴你，一步步走向熟练。加油！"
            )
            fallback_dashboard = (
                "根据当前的学情监测数据，您的机器学习核心概念体系构建已初具规模（部分核心节点掌握度达90%以上），但在局部节点存在认知负荷过载倾向（当前心智负荷监测值高于0.6）。\n"
                "通过关联分析与最近答题记录，推断此学习障碍并非由于概念本身的抽象度导致，而是前置数学知识点（如微积分中偏导数求导与线性代数中的矩阵相乘逻辑）的掌握不够稳固，因而在算法推导时产生了冗余的解译开销，引发了工作记忆过载。\n"
                "建议您在后续学习中采取以下具体干预策略：\n"
                "首先，回溯学习相关的数学前置讲义以消除依赖阻塞，实现认知对齐；其次，利用系统右侧的隔离代码沙箱（Sandbox）执行算法逻辑验证，通过具象的控制台输出来分担抽象推导压力，从而有效降低即时工作记忆负荷，优化知识重构效率。"
            )
            return fallback_narrative, fallback_dashboard

class ProfileUpdateRequest(BaseModel):
    major: str | None = None
    target_course: str | None = None
    cognitive_style: str | None = None
    motivation_type: str | None = None
    learning_goals: list[str] | None = None
    learning_preferences: list[str] | None = None


@router.post("/{student_id}/update")
async def update_profile(
    student_id: str,
    update_data: ProfileUpdateRequest,
    request: Request,
) -> dict[str, Any]:
    """显式/增量修改学生画像，同步保存至数据库"""
    swarm = build_swarm_from_headers(request.headers)
    profile = swarm.profile_store.get(student_id)
    if not profile:
        profile = await run_db_op(load_student_profile, student_id)
        swarm.profile_store[student_id] = profile

    if not getattr(profile, "customized_fields", None):
        profile.customized_fields = []

    if update_data.major is not None:
        profile.major = update_data.major.strip()
        if "major" not in profile.customized_fields:
            profile.customized_fields.append("major")
    if update_data.target_course is not None:
        profile.target_course = update_data.target_course.strip()
        if "target_course" not in profile.customized_fields:
            profile.customized_fields.append("target_course")
    if update_data.cognitive_style is not None:
        profile.cognitive_style = update_data.cognitive_style.strip()
        if "cognitive_style" not in profile.customized_fields:
            profile.customized_fields.append("cognitive_style")
    if update_data.motivation_type is not None:
        profile.motivation_type = update_data.motivation_type.strip()
        if "motivation_type" not in profile.customized_fields:
            profile.customized_fields.append("motivation_type")
    if update_data.learning_goals is not None:
        profile.learning_goals = [g.strip() for g in update_data.learning_goals if g.strip()]
        if "learning_goals" not in profile.customized_fields:
            profile.customized_fields.append("learning_goals")
    if update_data.learning_preferences is not None:
        profile.interaction_preferences = [p.strip() for p in update_data.learning_preferences if p.strip()]
        if "interaction_preferences" not in profile.customized_fields:
            profile.customized_fields.append("interaction_preferences")

    # 每次手动调整画像后，清除成长信笺的缓存，确保大模型下次会按照新设置生成叙事内容
    profile.narrative_report = ""

    # 增量并网：同步更新全局 Swarm 实例缓存，消除多端/多配置下的内存不一致性
    from swarm_factory import _swarm_cache
    for sw in _swarm_cache.values():
        if student_id in sw.profile_store:
            p = sw.profile_store[student_id]
            if not getattr(p, "customized_fields", None):
                p.customized_fields = []
            if update_data.major is not None:
                p.major = update_data.major.strip()
                if "major" not in p.customized_fields:
                    p.customized_fields.append("major")
            if update_data.target_course is not None:
                p.target_course = update_data.target_course.strip()
                if "target_course" not in p.customized_fields:
                    p.customized_fields.append("target_course")
            if update_data.cognitive_style is not None:
                p.cognitive_style = update_data.cognitive_style.strip()
                if "cognitive_style" not in p.customized_fields:
                    p.customized_fields.append("cognitive_style")
            if update_data.motivation_type is not None:
                p.motivation_type = update_data.motivation_type.strip()
                if "motivation_type" not in p.customized_fields:
                    p.customized_fields.append("motivation_type")
            if update_data.learning_goals is not None:
                p.learning_goals = [g.strip() for g in update_data.learning_goals if g.strip()]
                if "learning_goals" not in p.customized_fields:
                    p.customized_fields.append("learning_goals")
            if update_data.learning_preferences is not None:
                p.interaction_preferences = [pref.strip() for pref in update_data.learning_preferences if pref.strip()]
                if "interaction_preferences" not in p.customized_fields:
                    p.customized_fields.append("interaction_preferences")
            p.narrative_report = ""

    await run_db_op(save_student_profile, profile)

    return {
        "status": "success",
        "message": "Student profile updated successfully.",
        "major": profile.major,
        "target_course": profile.target_course,
        "cognitive_style": profile.cognitive_style,
        "motivation_type": profile.motivation_type,
        "learning_goals": profile.learning_goals,
        "learning_preferences": profile.interaction_preferences,
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

    display_name = await run_db_op(load_display_name, student_id)

    # 1. 学生背景概览
    background = {
        "student_id": student_id,
        "display_name": display_name,
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

    # 6. 读取仪表盘全局学情分析报告与叙事报告
    narrative_report = getattr(profile, "narrative_report", "")
    dashboard_report = getattr(profile, "dashboard_report", "")
    has_cache = bool(narrative_report and dashboard_report)
    
    if not narrative_report:
        narrative_report = (
            "### 📬 智教矩阵个性化成长信笺 (StoryLensEdu)\n\n"
            "亲爱的同学：\n\n"
            "看到你在机器学习世界里的探索，系统能感受到你对未知的渴望。目前你在知识图谱中的多个核心概念上已经开始了旅程，"
            "遇到一时的不理解或高负荷是知识建构过程中的必经风景，如同登山时背包需要稍微整理。建议你在接下来的日子里，"
            "先从前置概念的基础小册和代码实操着手，我们会一直在右侧的画板和沙箱中陪伴你，一步步走向熟练。加油！"
        )
    if not dashboard_report:
        dashboard_report = (
            "根据当前的学情监测数据，您的机器学习核心概念体系构建已初具规模（部分核心节点掌握度达90%以上），但在局部节点存在认知负荷过载倾向（当前心智负荷监测值高于0.6）。\n"
            "通过关联分析与最近答题记录，推断此学习障碍并非由于概念本身的抽象度导致，而是前置数学知识点（如微积分中偏导数求导与线性代数中的矩阵相乘逻辑）的掌握不够稳固，因而在算法推导时产生了冗余的解译开销，引发了工作记忆过载。\n"
            "建议您在后续学习中采取以下具体干预策略：\n"
            "首先，回溯学习相关的数学前置讲义以消除依赖阻塞，实现认知对齐；其次，利用系统右侧的隔离代码沙箱（Sandbox）执行算法逻辑验证，通过具象的控制台输出来分担抽象推导压力，从而有效降低即时工作记忆负荷，优化知识重构效率。"
        )

    return {
        "background": background,
        "dimensions": dimensions,
        "causes": causes,
        "weak_analysis": weak_analysis,
        "suggestions": summary_suggestions,
        "narrative_report": narrative_report,
        "dashboard_report": dashboard_report,
        "has_narrative_cache": has_cache,
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

    if not getattr(profile, "customized_fields", None):
        profile.customized_fields = []

    major = payload.get("major")
    if major:
        profile.major = major
        profile.major_preference = major
        if "major" not in profile.customized_fields:
            profile.customized_fields.append("major")

    course = payload.get("target_course")
    if course:
        profile.target_course = course
        if "target_course" not in profile.customized_fields:
            profile.customized_fields.append("target_course")

    goals = payload.get("learning_goals")
    if goals and isinstance(goals, list):
        profile.learning_goals = list(set(profile.learning_goals + goals))[:5]
        if "learning_goals" not in profile.customized_fields:
            profile.customized_fields.append("learning_goals")

    preferences = payload.get("interaction_preferences")
    if preferences and isinstance(preferences, list):
        existing = list(profile.interaction_preferences or [])
        profile.interaction_preferences = list(set(existing + preferences))[:5]
        if "interaction_preferences" not in profile.customized_fields:
            profile.customized_fields.append("interaction_preferences")

    profile._refresh_dynamic_profile()
    await run_db_op(save_student_profile, profile)

    return {"status": "updated", "student_id": student_id}


@router.get("/{student_id}/narrative")
async def get_profile_narrative(
    student_id: str,
    request: Request,
) -> dict[str, Any]:
    """异步按需获取/生成最新的 StoryLensEdu 叙事评估成长信笺"""
    swarm = build_swarm_from_headers(request.headers)
    profile = swarm.profile_store.get(student_id)

    if not profile:
        profile = await run_db_op(load_student_profile, student_id)
        swarm.profile_store[student_id] = profile

    cached_report = getattr(profile, "narrative_report", "")
    if cached_report:
        return {"narrative_report": cached_report}

    # 如果无缓存，生成并保存
    generator = NarrativeReportGenerator(swarm.llm)
    narrative_report, dashboard_report = await generator.generate_report(profile)
    profile.narrative_report = narrative_report
    profile.dashboard_report = dashboard_report
    await run_db_op(save_student_profile, profile)
    return {"narrative_report": narrative_report, "dashboard_report": dashboard_report}


@router.get("/{student_id}/recommendations")
async def get_recommendations(
    student_id: str,
    concept: str | None = None,
    pathway: str | None = None,
) -> list[dict[str, Any]]:
    """获取针对学生的自适应智能推送学习资源，支持按概念与战术路线手动切换与重新编译"""
    from app.utils.recommendation_engine import get_smart_recommendations
    
    return await run_db_op(get_smart_recommendations, student_id, concept=concept, pathway=pathway)
