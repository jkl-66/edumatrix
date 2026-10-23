"""Adaptive Anki-style flashcard API.

Endpoints:
- POST /api/flashcard/generate: create a flashcard from a wrong quiz or weak point.
- POST /api/flashcard/review: record review quality and persist SM-2 scheduling.
- GET  /api/flashcard/due: list cards due for review directly from DB.
- GET  /api/flashcard/all: list all cards directly from DB.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.crud import (
    ReviewModelError,
    apply_review_feedback,
    build_review_adaptation_payload,
    generate_review_model_json,
    load_student_profile,
    review_plan_to_dict,
)
from app.database import (
    DBFlashcard,
    DBFlashcardVersion,
    DBKnowledgePoint,
    DBLearningEvent,
    DBQuizRecord,
    DBReviewPlan,
    get_db,
)
from app.auth import enforce_request_student_scope, enforce_student_access, get_current_user
from app.legacy_repositories import LegacyReadRepository
from app.m5_assessment import AssessmentEvidenceInput, record_legacy_assessment_evidence

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


def _content_hash(front: str, back: str, source_snapshot: dict[str, Any]) -> str:
    payload = {"front": front, "back": back, "source_snapshot": source_snapshot}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _identity_hash(owner_public_id: str, student_id: str, concept: str, source_quiz_id: str) -> str:
    stable_source = source_quiz_id or f"concept:{concept.strip().casefold()}"
    return hashlib.sha256(f"{owner_public_id}\n{student_id}\n{stable_source}".encode("utf-8")).hexdigest()


def _card_content(
    *,
    concept: str,
    record: DBQuizRecord | None = None,
    generated_answer: str,
    generation_metadata: dict[str, Any] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    if record is None:
        front = f"【概念重建】请简要叙述「{concept}」的核心直觉、定义以及它所解决的关键问题。"
        source_snapshot = {
            "source_type": "review_plan",
            "concept": concept,
            "truth_boundary": "model_generated_review_answer",
        }
    else:
        accuracy = float(record.accuracy_score or 0.0)
        if accuracy < 0.3:
            front = f"【深度剖析】请详细拆解并阐释「{concept}」的底层计算步骤与核心原理，并指出它的一个常见误区。"
        elif accuracy < 0.6:
            front = f"【对比辨析】请说明「{concept}」与其最邻近前置概念的区别，并用一个实际例子说明它的应用。"
        else:
            front = f"【应用实践】如何在真实的机器学习系统中设计并调用「{concept}」？请写出核心步骤与关键公式。"
        source_snapshot = {
            "source_type": "quiz_record",
            "quiz_record_id": str(record.id),
            "concept": concept,
            "accuracy": accuracy,
            "truth_boundary": "model_generated_review_answer",
        }
    source_snapshot.update(generation_metadata or {})
    return front, generated_answer, source_snapshot


def _ensure_card(
    db: Session, *, owner_public_id: str, student_id: str, concept: str,
    review_plan: DBReviewPlan, source_quiz_id: str = "", record: DBQuizRecord | None = None,
    generated_answer: str | None = None,
    generation_metadata: dict[str, Any] | None = None,
) -> tuple[DBFlashcard, DBFlashcardVersion]:
    identity_hash = _identity_hash(owner_public_id, student_id, concept, source_quiz_id)
    card = db.query(DBFlashcard).filter_by(identity_hash=identity_hash).first()
    created = card is None
    if card is None:
        card = DBFlashcard(
            owner_public_id=owner_public_id, student_id=student_id, review_plan_id=review_plan.id,
            concept=concept, source_quiz_id=source_quiz_id, identity_hash=identity_hash,
        )
        db.add(card)
        db.flush()
    current = db.get(DBFlashcardVersion, card.current_version_id) if card.current_version_id else None
    if current is not None:
        return card, current
    if not generated_answer:
        raise ReviewModelError("review_flashcard_answer_missing", "闪卡回答尚未由真实模型生成。")
    front, back, source_snapshot = _card_content(
        concept=concept,
        record=record,
        generated_answer=generated_answer,
        generation_metadata=generation_metadata,
    )
    content_hash = _content_hash(front, back, source_snapshot)
    version_number = (db.query(DBFlashcardVersion).filter_by(flashcard_id=card.id).count() + 1)
    current = DBFlashcardVersion(
        flashcard_id=card.id, version_number=version_number, front=front, back=back,
        source_snapshot=source_snapshot, content_hash=content_hash,
        created_by_public_id=owner_public_id,
    )
    db.add(current)
    db.flush()
    card.current_version_id = current.id
    card.lock_version = 1 if created else int(card.lock_version or 1) + 1
    return card, current


def _card_dict(card: DBFlashcard, version: DBFlashcardVersion, plan: DBReviewPlan) -> dict[str, Any]:
    return {
        "id": card.id, "version_id": version.id, "version_number": version.version_number,
        "content_hash": version.content_hash, "concept": card.concept,
        "front": version.front, "back": version.back, "source_snapshot": version.source_snapshot or {},
        "source_quiz_id": card.source_quiz_id, "student_id": card.student_id,
        "easiness": round(plan.easiness_factor or 2.5, 2),
        "interval_days": plan.interval_days or 1, "review_count": plan.review_count or 0,
        "last_quality": plan.last_quality or 0, "next_review_at": _iso_utc(plan.next_review_at),
        "mastery": plan.mastery or 0.0,
        "tags": ["错题整理", "反思"] if plan.last_quality == 2 else [],
    }


async def _generate_flashcard_answer(
    *,
    concept: str,
    owner_public_id: str,
    course_id: str | None = None,
    record: DBQuizRecord | None = None,
    model_call_context: dict | None = None,
) -> tuple[str, dict[str, Any]]:
    system_prompt = (
        "你是 EduMatrix 的记忆闪卡 Answer Agent。只输出 JSON，不要 Markdown 围栏；"
        "JSON 必须包含 answer 和 explanation 字段；回答必须是基于给定知识点的真实中文解释，并明确一个适用边界或例子；"
        "explanation 必须把知识点降维成学习者能复述的直觉、类比或最小例子，不得使用空泛的鼓励话。"
    )
    user_prompt = f"知识点：{concept}\n"
    if record is not None:
        difficulty = "困难知识点：必须先给出真实降维解释，再给出严谨回答。" if float(record.accuracy_score or 0.0) < 0.6 else "请同时给出严谨回答和简明降维解释。"
        user_prompt += (
            f"该知识点的作答记录：正确答案={record.correct_answer or '未提供'}，"
            f"学习者答案={record.student_answer or '未提供'}。{difficulty}\n"
        )
    else:
        user_prompt += "请按初学者可理解的方式生成回答，并在 explanation 中给出真实降维解释。\n"
    user_prompt += "请生成可直接展示在闪卡背面的完整回答，不要声称引用了不存在的资料。"

    def validate(raw: str) -> dict:
        parsed = json.loads(raw.strip())
        answer = str(parsed.get("answer") or "").strip()
        explanation = str(parsed.get("explanation") or "").strip()
        if len(answer) < 12 or len(explanation) < 12:
            raise ValueError("flashcard answer is unusable")
        return {"answer": answer, "explanation": explanation}

    generated, model, provider = await generate_review_model_json(
        operation="review_flashcard_answer",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        role="记忆闪卡导师",
        owner_public_id=owner_public_id,
        course_id=course_id,
        input_summary={"concept_payload_included": False, "record_bound": record is not None},
        response_validator=validate,
        model_call_context=model_call_context,
    )
    answer = str(generated["answer"]).strip()
    explanation = str(generated.get("explanation") or "").strip()
    if explanation:
        answer = f"{answer}\n\n降维解释：{explanation}"
    return answer, {
        "model": model,
        "provider": provider,
        "thinking": "enabled",
        "reasoning_effort": "max",
        "allow_fallback": False,
        "explanation_generated": bool(explanation),
    }


def _has_completed_learning_evidence(
    db: Session, *, owner_public_id: str, concept: str,
) -> bool:
    """Only accepted, mastery-eligible completion evidence can unlock auto-card creation."""
    normalized = str(concept or "").strip().casefold()
    if not normalized:
        return False
    point = db.query(DBKnowledgePoint).filter(
        (DBKnowledgePoint.id == concept)
        | (DBKnowledgePoint.code == concept)
        | (DBKnowledgePoint.title == concept)
    ).order_by(DBKnowledgePoint.id).first()
    accepted_values = {normalized}
    if point is not None:
        accepted_values.update({str(point.id).casefold(), str(point.code or "").casefold(), str(point.title).casefold()})
    events = db.query(DBLearningEvent).filter_by(
        owner_public_id=owner_public_id,
        evidence_status="accepted",
        mastery_eligible=True,
        completion_effect="complete",
    ).order_by(DBLearningEvent.occurred_at.desc(), DBLearningEvent.id.desc()).all()
    for event in events:
        context = event.context_ref or {}
        payload = event.payload or {}
        values = {
            str(event.object_id or "").casefold(),
            str(context.get("knowledgePointId") or "").casefold(),
            str(context.get("knowledge_point_id") or "").casefold(),
            str(payload.get("knowledge_point_id") or "").casefold(),
            str(payload.get("concept") or "").casefold(),
        }
        if accepted_values.intersection(values):
            return True
    return False


async def _cards_for_plan(
    db: Session, *, owner_public_id: str, student_id: str, plan: DBReviewPlan,
) -> list[tuple[DBFlashcard, DBFlashcardVersion]]:
    cards = db.query(DBFlashcard).filter_by(
        owner_public_id=owner_public_id, student_id=student_id,
        review_plan_id=plan.id, status="active",
    ).order_by(DBFlashcard.created_at.asc(), DBFlashcard.id.asc()).all()
    if not cards:
        if not _has_completed_learning_evidence(
            db, owner_public_id=owner_public_id, concept=plan.concept,
        ):
            return []
        answer, generation_metadata = await _generate_flashcard_answer(
            concept=plan.concept,
            owner_public_id=owner_public_id,
        )
        return [_ensure_card(
            db, owner_public_id=owner_public_id, student_id=student_id,
            concept=plan.concept, review_plan=plan,
            generated_answer=answer,
            generation_metadata=generation_metadata,
        )]
    result = []
    for card in cards:
        version = db.get(DBFlashcardVersion, card.current_version_id)
        if version is None:
            raise HTTPException(status_code=409, detail="flashcard current version is missing")
        result.append((card, version))
    return result


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
    record = None

    if quiz_id:
        record = LegacyReadRepository(db).quiz_record(quiz_id, student_id)
        if record:
            concept = record.target_concept or "General Concept"
    else:
        profile = load_student_profile(db, student_id)
        if profile.weak_points:
            concept = profile.weak_points[0]

    if not concept:
        raise HTTPException(status_code=400, detail="No available concept for flashcard generation")

    identity_hash = _identity_hash(current_user.public_id, student_id, concept, quiz_id)
    existing_card = db.query(DBFlashcard).filter_by(identity_hash=identity_hash).first()
    existing_version = (
        db.get(DBFlashcardVersion, existing_card.current_version_id)
        if existing_card is not None and existing_card.current_version_id else None
    )
    if existing_version is None and not _has_completed_learning_evidence(
        db, owner_public_id=current_user.public_id, concept=concept,
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "flashcard_generation_requires_completion",
                "message": "完成这个知识点的学习并留下合格学习证据后，才能生成记忆闪卡。",
                "retryable": False,
            },
        )

    existing = LegacyReadRepository(db).review_plan(student_id, concept)

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
        db.flush()

    plan = existing or plan
    current_version = (
        db.get(DBFlashcardVersion, existing_card.current_version_id)
        if existing_card is not None and existing_card.current_version_id else None
    )
    generated_answer = None
    generation_metadata = None
    if current_version is None:
        try:
            generated_answer, generation_metadata = await _generate_flashcard_answer(
                concept=concept,
                owner_public_id=current_user.public_id,
                record=record,
            )
        except ReviewModelError as exc:
            raise HTTPException(
                status_code=502,
                detail={"code": exc.code, "message": str(exc), "retryable": True},
            ) from exc
    card, version = _ensure_card(
        db, owner_public_id=current_user.public_id, student_id=student_id, concept=concept,
        review_plan=plan, source_quiz_id=quiz_id, record=record,
        generated_answer=generated_answer,
        generation_metadata=generation_metadata,
    )
    db.commit()
    card_dict = _card_dict(card, version, plan)
    return {"flashcard": card_dict, "concept": concept, "front": version.front, "back": version.back}


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
    card_id = str(payload.get("card_id", "")).strip()
    try:
        quality = int(payload.get("quality", 4))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="quality must be one of 2, 4, 5")

    if quality not in (2, 4, 5):
        raise HTTPException(status_code=400, detail="quality must be one of 2, 4, 5")

    if not concept:
        raise HTTPException(status_code=400, detail="concept is required")

    card = None
    if card_id:
        card = db.get(DBFlashcard, card_id)
        if card is None:
            raise HTTPException(status_code=404, detail="flashcard not found")
        if card.owner_public_id != current_user.public_id or card.student_id != student_id:
            raise HTTPException(status_code=403, detail="flashcard access denied")
        if card.concept != concept:
            raise HTTPException(status_code=409, detail="flashcard concept changed")

    existing_plan = db.query(DBReviewPlan).filter_by(
        student_id=student_id, concept=concept,
    ).first()
    try:
        adaptation = await build_review_adaptation_payload(
            concept,
            quality,
            existing_plan.mastery if existing_plan is not None else 0.3,
            owner_public_id=current_user.public_id,
        )
    except ReviewModelError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": exc.code, "message": str(exc), "retryable": True},
        ) from exc

    try:
        plan = apply_review_feedback(db, student_id, concept, quality)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    evidence = AssessmentEvidenceInput(
        idempotency_key=f"legacy-review-{plan.id}-{plan.review_count or 0}",
        source_type="wrong_question_review",
        source_object_id=str(plan.id),
        target_object_type="review_plan",
        target_object_id=str(plan.id),
    )
    canonical_evidence = record_legacy_assessment_evidence(
        db, student_id=student_id, evidence=evidence,
    )
    db.commit()
    
    if card is None:
        card = db.query(DBFlashcard).filter_by(
            owner_public_id=current_user.public_id, student_id=student_id,
            concept=concept, status="active",
        ).order_by(DBFlashcard.updated_at.desc()).first()
    if card is None:
        card, version = _ensure_card(
            db, owner_public_id=current_user.public_id, student_id=student_id,
            concept=concept, review_plan=plan,
        )
    else:
        version = db.get(DBFlashcardVersion, card.current_version_id)
        if version is None:
            raise HTTPException(status_code=409, detail="flashcard current version is missing")
    card_dict = _card_dict(card, version, plan)
    db.commit()

    return {
        "flashcard": card_dict,
        "review_plan": review_plan_to_dict(plan),
        "adaptive_review": adaptation,
        "easiness_new": round(plan.easiness_factor or 2.5, 2),
        "interval_new": plan.interval_days,
        "next_review_at": _iso_utc(plan.next_review_at),
        "message": f"Review recorded. Next review interval: {plan.interval_days} days.",
        "canonical_evidence": canonical_evidence,
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
    plans = LegacyReadRepository(db).due_review_plans(
        student_id, now=now, limit=max_count
    )
    
    due_cards = []
    try:
        for plan in plans:
            due_cards.extend(
                _card_dict(card, version, plan)
                for card, version in await _cards_for_plan(
                    db, owner_public_id=current_user.public_id, student_id=student_id, plan=plan,
                )
            )
    except ReviewModelError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": exc.code, "message": str(exc), "retryable": True},
        ) from exc
    db.commit()

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
    plans = LegacyReadRepository(db).all_review_plans(student_id)
    
    cards = []
    try:
        for plan in plans:
            cards.extend(
                _card_dict(card, version, plan)
                for card, version in await _cards_for_plan(
                    db, owner_public_id=current_user.public_id, student_id=student_id, plan=plan,
                )
            )
    except ReviewModelError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": exc.code, "message": str(exc), "retryable": True},
        ) from exc
    db.commit()
        
    return {
        "total": len(cards),
        "cards": cards,
    }
