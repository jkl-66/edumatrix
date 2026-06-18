"""任务 7.8: 真实行为信号回流与学习负荷更新 API

核心公式（认知负荷滑动更新）：
    L_cognitive(t) = 0.75 * L_cognitive(t-1) + 0.25 * min(1.0, T_actual/T_base * (1.0 + 0.15 * E_sandbox_runs))

情绪阻滞判定规则：
    页面停留 < 10s 且答题正确率极低 → affective_barrier 上调 25%
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.crud import load_student_profile, save_student_profile
from app.database import get_db
from models import LearningStateCause, StudentProfile

router = APIRouter(prefix="/api/behavior", tags=["behavior"])


# 标准化参数
T_BASE_SECONDS = 60.0       # 标准基准阅读时长 (秒)
COGNITIVE_MOMENTUM = 0.75   # 滑动平均动量
COGNITIVE_NEW_WEIGHT = 0.25  # 新观测权重
SANDBOX_ERROR_PENALTY = 0.15  # 每次沙盒报错附加系数
AFFECTIVE_STAY_THRESHOLD = 10.0  # 情绪阻滞判定最短停留 (秒)
AFFECTIVE_ACCURACY_THRESHOLD = 0.3  # 极低正确率阈值
AFFECTIVE_BOOST = 0.25  # 情绪阻滞指标上调幅度


def _update_cognitive_load(
    profile: StudentProfile,
    actual_stay_seconds: float,
    sandbox_errors: int,
) -> float:
    """认知负荷滑动更新公式。

    L_cognitive(t) = 0.75 * L_cognitive(t-1) + 0.25 * min(1.0, T_actual/T_base * (1.0 + 0.15 * E))
    """
    t_ratio = actual_stay_seconds / T_BASE_SECONDS if T_BASE_SECONDS > 0 else 1.0
    sandbox_penalty = 1.0 + SANDBOX_ERROR_PENALTY * sandbox_errors
    new_observation = min(1.0, t_ratio * sandbox_penalty)

    old_load = profile.cognitive_load
    updated = COGNITIVE_MOMENTUM * old_load + COGNITIVE_NEW_WEIGHT * new_observation
    return max(0.0, min(1.0, updated))


def _check_affective_block(
    profile: StudentProfile,
    actual_stay_seconds: float,
    accuracy: float,
) -> bool:
    """情绪阻滞判定：停留 < 10s 且正确率 < 0.3 → 上调 affective_barrier。"""
    return actual_stay_seconds < AFFECTIVE_STAY_THRESHOLD and accuracy < AFFECTIVE_ACCURACY_THRESHOLD


def _update_focus_level(
    profile: StudentProfile,
    actual_stay_seconds: float,
    cognitive_load_new: float,
) -> float:
    """专注度同步更新：停留越短/负荷越高 → 专注度下降。"""
    stay_bonus = min(0.1, actual_stay_seconds / T_BASE_SECONDS * 0.05)
    load_penalty = max(0.0, cognitive_load_new - 0.5) * 0.3
    updated = profile.focus_level + stay_bonus - load_penalty
    return max(0.1, min(1.0, updated))


@router.post("/logs")
async def upload_behavior_logs(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """上报前端行为统计数据，批量更新画像负荷和专注度。

    请求体:
        student_id: str
        actual_stay_seconds: float  — 页面实际停留时长 (秒)
        base_stay_seconds: float    — 标准基准阅读时长 (秒, 可选, 默认 60)
        sandbox_errors: int         — 沙盒代码运行失败次数 (可选, 默认 0)
        page_accuracy: float        — 页面答题正确率 (0~1, 可选, 默认 0.5)
        page_id: str                — 页面标识 (可选)

    返回:
        {cognitive_load_new, focus_level_new, affective_block_triggered, ...}
    """
    payload = await request.json()
    student_id = str(payload.get("student_id", "default"))
    actual_stay = float(payload.get("actual_stay_seconds", T_BASE_SECONDS))
    sandbox_errors = int(payload.get("sandbox_errors", 0))
    accuracy = float(payload.get("page_accuracy", 0.5))

    profile = load_student_profile(db, student_id)

    # Step 1: 认知负荷滑动更新
    cognitive_new = _update_cognitive_load(profile, actual_stay, sandbox_errors)
    profile.cognitive_load = cognitive_new

    # Step 2: 专注度同步更新
    focus_new = _update_focus_level(profile, actual_stay, cognitive_new)
    profile.focus_level = focus_new

    # Step 3: 情绪阻滞判定
    affective_triggered = _check_affective_block(profile, actual_stay, accuracy)
    if affective_triggered:
        # 上调 25% affective_barrier
        existing = profile.learning_state_causes.get(
            LearningStateCause.AFFECTIVE_BARRIER.value,
        )
        if existing:
            existing.percentage = min(100.0, existing.percentage + AFFECTIVE_BOOST * 100)
        else:
            from models import CauseBreakdown
            profile.learning_state_causes[LearningStateCause.AFFECTIVE_BARRIER.value] = (
                CauseBreakdown(
                    key=LearningStateCause.AFFECTIVE_BARRIER.value,
                    label="情绪与信心阻滞",
                    percentage=AFFECTIVE_BOOST * 100,
                    confidence=0.6,
                    evidence_count=1,
                    evidence_fragments=[f"停留{actual_stay:.1f}s+正确率{accuracy:.2f}"],
                    recommended_interventions=[
                        "降低第一题难度，先建立可见进步证据",
                        "反馈聚焦下一步行动，不做人格评价",
                    ],
                )
            )

    # Step 4: 持久化
    save_student_profile(db, profile)

    return {
        "cognitive_load_new": round(cognitive_new, 3),
        "focus_level_new": round(focus_new, 3),
        "affective_block_triggered": affective_triggered,
        "actual_stay_seconds": actual_stay,
        "sandbox_errors": sandbox_errors,
        "page_accuracy": accuracy,
    }
