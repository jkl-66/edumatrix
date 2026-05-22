from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.crud import load_student_profile, save_student_profile
from swarm_factory import build_swarm_from_headers

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("/{student_id}")
async def get_profile(
    student_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    swarm = build_swarm_from_headers(request.headers)
    profile = swarm.profile_store.get(student_id)

    if not profile:
        profile = load_student_profile(db, student_id)
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


@router.post("/{student_id}")
async def update_profile(
    student_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    payload = await request.json()
    swarm = build_swarm_from_headers(request.headers)
    profile = swarm.profile_store.get(student_id)

    if not profile:
        profile = load_student_profile(db, student_id)
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
    save_student_profile(db, profile)

    return {"status": "updated", "student_id": student_id}
