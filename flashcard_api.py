"""任务 7.5: 自适应 Anki 间隔记忆闪卡 API

前端交互：
- POST /api/flashcard/generate — 从错题生成闪卡
- POST /api/flashcard/review — 提交复习质量反馈 (q={2,4,5})
- GET  /api/flashcard/due — 获取到期待复习的闪卡列表
- GET  /api/flashcard/all — 获取全部闪卡
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from anki_engine import FlashCard, get_sm2_engine
from app.database import DBQuizRecord, DBReviewPlan, get_db
from app.crud import load_student_profile, save_student_profile

router = APIRouter(prefix="/api/flashcard", tags=["flashcard"])


@router.post("/generate")
async def generate_flashcard(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """从错题自动生成闪卡。

    请求体:
        student_id: str
        quiz_id: str (可选，指定来源答题记录)

    返回:
        {flashcard: {...}, concept, front, back}
    """
    payload = await request.json()
    student_id = str(payload.get("student_id", "default"))
    quiz_id = str(payload.get("quiz_id", "")).strip()

    concept = ""
    front = ""
    back = ""

    if quiz_id:
        # 从指定答题记录提取知识点
        record = db.query(DBQuizRecord).filter(
            DBQuizRecord.id == quiz_id,
            DBQuizRecord.student_id == student_id,
        ).first()
        if record:
            concept = record.target_concept or "通用概念"
            front = f"请解释 {concept} 的核心概念和关键原理"
            back = (
                f"参考答案要点：{record.correct_answer or '暂无'}\n"
                f"你的回答：{record.student_answer or '未记录'}\n"
                f"正确率：{record.accuracy_score or 0.0:.2f}"
            )
    else:
        # 无 quiz_id 时从画像薄弱点生成
        profile = load_student_profile(db, student_id)
        if profile.weak_points:
            concept = profile.weak_points[0]
            front = f"请解释 {concept} 的核心概念"
            back = f"{concept} 的关键要点和原理解析"
        else:
            raise HTTPException(status_code=400, detail="无可用知识点生成闪卡")

    engine = get_sm2_engine()
    card = engine.get_or_create(
        concept=concept,
        front=front,
        back=back,
        student_id=student_id,
        source_quiz_id=quiz_id,
    )

    # 同步到数据库 review_plans 表
    existing = db.query(DBReviewPlan).filter(
        DBReviewPlan.student_id == student_id,
        DBReviewPlan.concept == concept,
    ).first()
    if existing:
        existing.easiness_factor = card.easiness
        existing.interval_days = card.interval_days
        existing.last_quality = card.last_quality
        existing.review_count = card.review_count
        existing.mastery = max(existing.mastery or 0.0, 0.3)
    else:
        now = datetime.now(timezone.utc)
        plan = DBReviewPlan(
            student_id=student_id,
            concept=concept,
            interval_days=card.interval_days,
            next_review_at=now,
            mastery=0.3,
            review_count=0,
            easiness_factor=card.easiness,
            last_quality=0,
            priority=1.0,
        )
        db.add(plan)
    db.commit()

    return {"flashcard": card.to_dict(), "concept": concept, "front": front, "back": back}


@router.post("/review")
async def review_flashcard(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """提交复习质量反馈，触发 SM-2 调度更新。

    请求体:
        student_id: str
        concept: str
        quality: int  — {2=困难, 4=一般, 5=简单}

    返回:
        {flashcard: 更新后的闪卡, easiness_new, interval_new, next_review_at}
    """
    payload = await request.json()
    student_id = str(payload.get("student_id", "default"))
    concept = str(payload.get("concept", "")).strip()
    quality = int(payload.get("quality", 4))

    if quality not in (2, 4, 5):
        raise HTTPException(status_code=400, detail="质量评分必须为 2(困难), 4(一般) 或 5(简单)")

    engine = get_sm2_engine()
    card = engine.review(concept, student_id, quality)
    if card is None:
        raise HTTPException(status_code=404, detail=f"概念 '{concept}' 的闪卡不存在，请先生成")

    # 同步到数据库
    plan = db.query(DBReviewPlan).filter(
        DBReviewPlan.student_id == student_id,
        DBReviewPlan.concept == concept,
    ).first()
    if plan:
        plan.easiness_factor = card.easiness
        plan.interval_days = card.interval_days
        plan.last_quality = quality
        plan.review_count = card.review_count
        plan.mastery = min(1.0, (plan.mastery or 0.0) + 0.05 if quality >= 4 else max(0.0, (plan.mastery or 0.0) - 0.1))
        try:
            plan.next_review_at = datetime.fromisoformat(card.next_review_at)
        except (ValueError, TypeError):
            from datetime import timezone
            plan.next_review_at = datetime.now(timezone.utc) + __import__('datetime').timedelta(days=card.interval_days)
        db.commit()

    return {
        "flashcard": card.to_dict(),
        "easiness_new": round(card.easiness, 2),
        "interval_new": card.interval_days,
        "next_review_at": card.next_review_at,
        "message": f"复习成功！下次复习间隔 {card.interval_days} 天",
    }


@router.get("/due")
async def get_due_cards(
    request: Request,
    student_id: str = "default",
    max_count: int = 20,
) -> dict[str, Any]:
    """获取到期待复习的闪卡列表。"""
    engine = get_sm2_engine()
    due = engine.get_due_cards(student_id, max_count)
    return {
        "due_count": len(due),
        "cards": [card.to_dict() for card in due],
    }


@router.get("/all")
async def get_all_cards(
    request: Request,
    student_id: str = "default",
) -> dict[str, Any]:
    """获取全部闪卡（含 SM-2 参数）。"""
    engine = get_sm2_engine()
    cards = engine.get_all_cards(student_id)
    return {
        "total": len(cards),
        "cards": [card.to_dict() for card in cards],
    }
