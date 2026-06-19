from __future__ import annotations

from models import (
    LearningStateCause,
    LearningStrategyPlan,
    StrategyAction,
    StrategyType,
    StudentProfile,
)
from enum import Enum


class TeachingTier(str, Enum):
    """自适应教学档位（任务 7.3）。"""
    SIMPLIFIED = "simplified"  # 降维解释：掌握度 < 50%
    STANDARD = "standard"      # 标准模式：50% ~ 80%
    ADVANCED = "advanced"      # 进阶挑战：掌握度 > 80%


def detect_teaching_tier(profile: StudentProfile, target: str | None = None) -> TeachingTier:
    """根据目标概念掌握度检测自适应教学档位。

    Args:
        profile: 学生画像
        target: 目标知识点（若为 None 则取最薄弱点）

    Returns:
        教学档位枚举
    """
    if target and target in profile.concept_mastery:
        mastery = profile.concept_mastery[target]
    elif profile.concept_mastery:
        mastery = min(profile.concept_mastery.values())
    else:
        return TeachingTier.STANDARD

    if mastery < 0.50:
        return TeachingTier.SIMPLIFIED
    elif mastery > 0.80:
        return TeachingTier.ADVANCED
    else:
        return TeachingTier.STANDARD


class LearningStrategyEngine:
    """Maps learner-state evidence to concrete learning-science interventions."""

    def build_plan(self, profile: StudentProfile, *, target: str) -> LearningStrategyPlan:
        actions: list[StrategyAction] = []
        causes = profile.learning_state_causes

        if LearningStateCause.PREREQUISITE_GAP.value in causes:
            actions.append(
                StrategyAction(
                    strategy=StrategyType.WORKED_EXAMPLE,
                    title="先看 worked example，再做同构题",
                    description=f"围绕“{target}”先给完整示范题，标出前置概念、关键条件和解题触发点。",
                    trigger="前置知识缺口占比升高",
                    priority=1,
                )
            )

        if LearningStateCause.MISCONCEPTION.value in causes:
            actions.append(
                StrategyAction(
                    strategy=StrategyType.MISCONCEPTION_CONTRAST,
                    title="误概念反例辨析",
                    description="用正例、反例和相似概念对照表拆开学生的高频混淆点。",
                    trigger="误概念/易混点证据出现",
                    priority=1,
                )
            )

        if LearningStateCause.COGNITIVE_LOAD.value in causes:
            actions.append(
                StrategyAction(
                    strategy=StrategyType.HINT_LADDER,
                    title="三层提示阶梯",
                    description="先提示题目条件，再提示适用概念，最后只给局部步骤，避免直接暴露完整答案。",
                    trigger="认知负荷或多步骤遗漏风险升高",
                    priority=2,
                )
            )

        if LearningStateCause.STRATEGY_GAP.value in causes:
            actions.append(
                StrategyAction(
                    strategy=StrategyType.RETRIEVAL_PRACTICE,
                    title="检索练习与错因复盘",
                    description="学习后立刻安排 2 道不看资料的检索题，并要求学生写出错因和下次识别线索。",
                    trigger="学习策略不足或看答案依赖",
                    priority=2,
                )
            )

        if LearningStateCause.METACOGNITIVE_MISMATCH.value in causes:
            actions.append(
                StrategyAction(
                    strategy=StrategyType.METACOGNITIVE_CALIBRATION,
                    title="题前自评与题后校准",
                    description="每道关键题先记录自评掌握度，作答后比较表现，更新自我判断准确性。",
                    trigger="自评与真实表现不一致",
                    priority=2,
                )
            )

        # === P1-1 情感感知策略分支 ===
        if profile.frustration_index > 0.4:
            actions.append(
                StrategyAction(
                    strategy=StrategyType.HINT_LADDER,  # 使用 HINT_LADDER 策略型，但内容改为情感安抚
                    title="挫败感缓解与信心重建",
                    description=f"学生挫败感偏高({profile.frustration_index:.2f})。降低第一题难度，先建立成功体验；"
                                f"反馈聚焦具体任务进展而非人格评价；使用积极暗示（'上一题你已经掌握了关键点'）。",
                    trigger=f"挫败感指数{profile.frustration_index:.2f}>0.4",
                    priority=0,  # 最高优先级
                )
            )
        if profile.motivation_type == "无动机":
            actions.append(
                StrategyAction(
                    strategy=StrategyType.RETRIEVAL_PRACTICE,
                    title="动机激活：知识连接与意义发现",
                    description="暂停批量刷题，先通过案例展示当前知识在实际项目/考试中的具体应用场景，"
                                "让学生自己选择学习路径和目标，增强自主感。",
                    trigger="无动机状态",
                    priority=0,
                )
            )

        weakest = min(profile.concept_mastery.items(), key=lambda item: item[1], default=(target, 0.48))
        actions.append(
            StrategyAction(
                strategy=StrategyType.SPACED_REVIEW,
                title="间隔复习队列",
                description=f"把“{weakest[0]}”加入 1 天、3 天、7 天复习队列，每次只做短检索题验证保持率。",
                trigger="固定课程场景下持续巩固薄弱知识点",
                priority=3,
                scheduled_after="1d/3d/7d",
            )
        )

        actions = sorted(actions, key=lambda item: item.priority)
        rationale = (
            "策略引擎依据学生画像中的不会原因占比、知识掌握度和互动偏好，"
            "优先选择 worked example、提示阶梯、检索练习、间隔复习和元认知校准。"
        )
        return LearningStrategyPlan(
            course=profile.target_course,
            target=target,
            actions=tuple(actions),
            rationale=rationale,
        )
