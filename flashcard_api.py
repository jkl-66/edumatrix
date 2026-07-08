"""Adaptive Anki-style flashcard API.

Endpoints:
- POST /api/flashcard/generate: create a flashcard from a wrong quiz or weak point.
- POST /api/flashcard/review: record review quality and persist SM-2 scheduling.
- GET  /api/flashcard/due: list in-memory cards due for review.
- GET  /api/flashcard/all: list all in-memory cards.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from anki_engine import get_sm2_engine
from app.crud import (
    apply_review_feedback,
    build_review_adaptation_payload,
    load_student_profile,
    review_plan_to_dict,
)
from app.database import DBQuizRecord, DBReviewPlan, get_db

router = APIRouter(prefix="/api/flashcard", tags=["flashcard"])


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
async def generate_flashcard(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Create or load a flashcard and mirror it into review_plans."""
    payload = await request.json()
    student_id = str(payload.get("student_id", "default"))
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
            front = f"Explain the core idea and key principle of {concept}."
            back = (
                f"Reference answer: {record.correct_answer or 'N/A'}\n"
                f"Your answer: {record.student_answer or 'N/A'}\n"
                f"Accuracy: {record.accuracy_score or 0.0:.2f}"
            )
    else:
        profile = load_student_profile(db, student_id)
        if profile.weak_points:
            concept = profile.weak_points[0]
            front = f"Explain the core idea of {concept}."
            back = f"Key points and principle explanation for {concept}."

    if not concept:
        raise HTTPException(status_code=400, detail="No available concept for flashcard generation")

    engine = get_sm2_engine()
    card = engine.get_or_create(
        concept=concept,
        front=front,
        back=back,
        student_id=student_id,
        source_quiz_id=quiz_id,
    )

    existing = db.query(DBReviewPlan).filter(
        DBReviewPlan.student_id == student_id,
        DBReviewPlan.concept == concept,
    ).first()
    if existing:
        existing.easiness_factor = existing.easiness_factor or card.easiness
        existing.interval_days = existing.interval_days or card.interval_days
        existing.last_quality = existing.last_quality or card.last_quality
        existing.review_count = existing.review_count or card.review_count
        existing.mastery = max(existing.mastery or 0.0, 0.3)
        existing.priority = existing.priority if existing.priority is not None else 1.0
    else:
        plan = DBReviewPlan(
            student_id=student_id,
            concept=concept,
            interval_days=card.interval_days,
            next_review_at=_utcnow_naive(),
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
    """Record review quality and persist the SM-2 schedule."""
    payload = await request.json()
    student_id = str(payload.get("student_id", "default"))
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

    # SQLite is the source of truth; the in-memory card is only a fast mirror.
    engine = get_sm2_engine()
    card = engine.get_or_create(concept=concept, student_id=student_id)
    card.easiness = plan.easiness_factor or card.easiness
    card.interval_days = plan.interval_days or card.interval_days
    card.last_quality = plan.last_quality or quality
    card.review_count = plan.review_count or 0
    card.next_review_at = _iso_utc(plan.next_review_at)
    adaptation = build_review_adaptation_payload(concept, quality, plan.mastery)
    if adaptation.get("triggered"):
        card.back = adaptation.get("card_back", card.back)

    return {
        "flashcard": card.to_dict(),
        "review_plan": review_plan_to_dict(plan),
        "adaptive_review": adaptation,
        "easiness_new": round(plan.easiness_factor or card.easiness, 2),
        "interval_new": plan.interval_days,
        "next_review_at": _iso_utc(plan.next_review_at),
        "message": f"Review recorded. Next review interval: {plan.interval_days} days.",
    }


@router.get("/due")
async def get_due_cards(
    request: Request,
    student_id: str = "default",
    max_count: int = 20,
) -> dict[str, Any]:
    """Return due in-memory cards."""
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
    """Return all in-memory cards for a student."""
    engine = get_sm2_engine()
    cards = engine.get_all_cards(student_id)
    return {
        "total": len(cards),
        "cards": [card.to_dict() for card in cards],
    }
