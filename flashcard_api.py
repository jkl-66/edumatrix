"""Adaptive Anki-style flashcard API.

Endpoints:
- POST /api/flashcard/generate: create a flashcard from a wrong quiz or weak point.
- POST /api/flashcard/review: record review quality and persist SM-2 scheduling.
- GET  /api/flashcard/due: list cards due for review directly from DB.
- GET  /api/flashcard/all: list all cards directly from DB.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.crud import (
    apply_review_feedback,
    build_review_adaptation_payload,
    load_student_profile,
    review_plan_to_dict,
)
from app.database import DBQuizRecord, DBReviewPlan, get_db
from app.auth import enforce_request_student_scope, enforce_student_access, get_current_user

router = APIRouter(prefix="/api/flashcard", tags=["flashcard"], dependencies=[Depends(enforce_request_student_scope)])


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso_utc(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.replace(microsecond=0).isoformat()


@router.post("/generate")
async def generate_flashcard(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> dict[str, Any]:
    """Create or load a flashcard and mirror it into review_plans."""
    payload = await request.json()
    student_id = enforce_student_access(payload.get("student_id"), current_user)
    quiz_id = str(payload.get("quiz_id", "")).strip()

    concept = ""
    front = ""
    back = ""

    if quiz_id:
        record = db.query(DBQuizRecord).filter(
            DBQuizRecord.id == quiz_id,
            DBQuizRecord.student_id == student_id,
        ).first()
        if record:
            concept = record.target_concept or "General Concept"
            accuracy = record.accuracy_score or 0.0
            if accuracy < 0.3:
                front = f"【深度剖析】请详细拆解并阐释「{concept}」的底层计算步骤与核心原理，并指出它的一个常见误区。"
            elif accuracy < 0.6:
                front = f"【对比辨析】请说明「{concept}」与其最邻近前置概念的区别，并用一个实际例子说明它的应用。"
            else:
                front = f"【应用实践】如何在真实的机器学习系统中设计并调用「{concept}」？请写出核心步骤与关键公式。"
            back = (
                f"Reference answer: {record.correct_answer or 'N/A'}\n"
                f"Your answer: {record.student_answer or 'N/A'}\n"
                f"Accuracy: {record.accuracy_score or 0.0:.2f}"
            )
    else:
        profile = load_student_profile(db, student_id)
        if profile.weak_points:
            concept = profile.weak_points[0]
            front = f"【概念重建】请简要叙述「{concept}」的核心直觉、定义以及它所解决的关键问题。"
            back = f"Key points and principle explanation for {concept}."

    if not concept:
        raise HTTPException(status_code=400, detail="No available concept for flashcard generation")

    existing = db.query(DBReviewPlan).filter(
        DBReviewPlan.student_id == student_id,
        DBReviewPlan.concept == concept,
    ).first()

    if existing:
        existing.easiness_factor = existing.easiness_factor or 2.5
        existing.interval_days = existing.interval_days or 1
        existing.last_quality = existing.last_quality or 0
        existing.review_count = existing.review_count or 0
        existing.mastery = max(existing.mastery or 0.0, 0.3)
        existing.priority = existing.priority if existing.priority is not None else 1.0
        
        easiness = existing.easiness_factor
        interval_days = existing.interval_days
        last_quality = existing.last_quality
        review_count = existing.review_count
        next_review_at = _iso_utc(existing.next_review_at)
    else:
        easiness = 2.5
        interval_days = 1
        last_quality = 0
        review_count = 0
        
        # Calculate BKT-based default easiness if BKT state exists
        profile = load_student_profile(db, student_id)
        if profile and getattr(profile, "bkt_states", None) and concept in profile.bkt_states:
            bkt_state = profile.bkt_states[concept]
            p_err = bkt_state.get("p_err", 0.5) if isinstance(bkt_state, dict) else getattr(bkt_state, "p_err", 0.5)
            if p_err > 0.4:
                easiness = max(1.8, 2.5 - (p_err - 0.4) * 1.5)

        plan = DBReviewPlan(
            student_id=student_id,
            concept=concept,
            interval_days=interval_days,
            next_review_at=_utcnow_naive(),
            mastery=0.3,
            review_count=0,
            easiness_factor=easiness,
            last_quality=0,
            priority=1.0,
        )
        db.add(plan)
        db.commit()
        next_review_at = _iso_utc(plan.next_review_at)

    card_dict = {
        "concept": concept,
        "front": front,
        "back": back,
        "source_quiz_id": quiz_id,
        "student_id": student_id,
        "easiness": round(easiness, 2),
        "interval_days": interval_days,
        "review_count": review_count,
        "last_quality": last_quality,
        "next_review_at": next_review_at,
        "tags": ["错题整理", "反思"] if last_quality == 2 else []
    }

    return {"flashcard": card_dict, "concept": concept, "front": front, "back": back}


@router.post("/review")
async def review_flashcard(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> dict[str, Any]:
    """Record review quality and persist the SM-2 schedule in database."""
    payload = await request.json()
    student_id = enforce_student_access(payload.get("student_id"), current_user)
    concept = str(payload.get("concept", "")).strip()
    try:
        quality = int(payload.get("quality", 4))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="quality must be one of 2, 4, 5")

    if quality not in (2, 4, 5):
        raise HTTPException(status_code=400, detail="quality must be one of 2, 4, 5")

    if not concept:
        raise HTTPException(status_code=400, detail="concept is required")

    try:
        plan = apply_review_feedback(db, student_id, concept, quality)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    adaptation = await build_review_adaptation_payload(concept, quality, plan.mastery)
    
    front = f"【概念重建】请简要叙述「{concept}」的核心直觉、定义以及它所解决的关键问题。"
    back = adaptation.get("card_back") if adaptation.get("triggered") else f"Key points and principle explanation for {concept}."

    card_dict = {
        "concept": concept,
        "front": front,
        "back": back,
        "source_quiz_id": "",
        "student_id": student_id,
        "easiness": round(plan.easiness_factor or 2.5, 2),
        "interval_days": plan.interval_days,
        "review_count": plan.review_count or 0,
        "last_quality": plan.last_quality or 0,
        "next_review_at": _iso_utc(plan.next_review_at),
        "tags": ["错题整理", "反思"] if quality == 2 else []
    }

    return {
        "flashcard": card_dict,
        "review_plan": review_plan_to_dict(plan),
        "adaptive_review": adaptation,
        "easiness_new": round(plan.easiness_factor or 2.5, 2),
        "interval_new": plan.interval_days,
        "next_review_at": _iso_utc(plan.next_review_at),
        "message": f"Review recorded. Next review interval: {plan.interval_days} days.",
    }


@router.get("/due")
async def get_due_cards(
    request: Request,
    student_id: str = "default",
    max_count: int = 20,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> dict[str, Any]:
    """Return due cards directly from DB."""
    student_id = enforce_student_access(student_id, current_user)
    now = _utcnow_naive()
    plans = (
        db.query(DBReviewPlan)
        .filter(
            DBReviewPlan.student_id == student_id,
            (DBReviewPlan.next_review_at == None) | (DBReviewPlan.next_review_at <= now)
        )
        .order_by(DBReviewPlan.next_review_at.asc())
        .limit(max_count)
        .all()
    )
    
    due_cards = []
    for plan in plans:
        front = f"【概念重建】请简要叙述「{plan.concept}」的核心直觉、定义以及它所解决的关键问题。"
        back = f"Key points and principle explanation for {plan.concept}."
        
        card_dict = {
            "concept": plan.concept,
            "front": front,
            "back": back,
            "source_quiz_id": "",
            "student_id": student_id,
            "easiness": round(plan.easiness_factor or 2.5, 2),
            "interval_days": plan.interval_days or 1,
            "review_count": plan.review_count or 0,
            "last_quality": plan.last_quality or 0,
            "next_review_at": _iso_utc(plan.next_review_at),
            "tags": ["错题整理", "反思"] if plan.last_quality == 2 else []
        }
        due_cards.append(card_dict)

    return {
        "due_count": len(due_cards),
        "cards": due_cards,
    }


@router.get("/all")
async def get_all_cards(
    request: Request,
    student_id: str = "default",
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> dict[str, Any]:
    """Return all cards directly from DB."""
    student_id = enforce_student_access(student_id, current_user)
    plans = db.query(DBReviewPlan).filter(DBReviewPlan.student_id == student_id).all()
    
    cards = []
    for plan in plans:
        front = f"【概念重建】请简要叙述「{plan.concept}」的核心直觉、定义以及它所解决的关键问题。"
        back = f"Key points and principle explanation for {plan.concept}."
        
        card_dict = {
            "concept": plan.concept,
            "front": front,
            "back": back,
            "source_quiz_id": "",
            "student_id": student_id,
            "easiness": round(plan.easiness_factor or 2.5, 2),
            "interval_days": plan.interval_days or 1,
            "review_count": plan.review_count or 0,
            "last_quality": plan.last_quality or 0,
            "next_review_at": _iso_utc(plan.next_review_at),
            "tags": ["错题整理", "反思"] if plan.last_quality == 2 else []
        }
        cards.append(card_dict)
        
    return {
        "total": len(cards),
        "cards": cards,
    }
