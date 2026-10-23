"""Authenticated API for the initial natural-language learner profile."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.database import DBOnboardingTurn, DBUser, run_db_op
from app.identity import normalize_role
from app.profile_onboarding import (
    OnboardingError,
    confirm_continuous_turn,
    complete_continuous_update,
    confirm_personal_evidence,
    confirm_turn,
    discard_personal_evidence,
    finalize_initial_profile,
    get_or_create_session,
    llm_extract_candidates,
    llm_extract_continuous_candidates,
    onboarding_status,
    record_continuous_turn,
    record_turn,
    session_payload,
    continuous_update_session_payload,
    continuous_update_reminder,
    dismiss_continuous_update_reminder,
    start_continuous_update,
    upload_personal_evidence,
)
from config import CONFIG


router = APIRouter(prefix="/api/v1/onboarding", tags=["profile-onboarding"])


class TurnInput(BaseModel):
    turn_id: str = Field(min_length=1, max_length=128)
    question_dimension: str = Field(min_length=1, max_length=32)
    user_answer: str = Field(min_length=1, max_length=4000)


class ConfirmInput(BaseModel):
    fields: dict[str, Any]
    resolve_conflict: bool = False


class EvidenceConfirmInput(BaseModel):
    fields: dict[str, Any]


class ContinuousStartInput(BaseModel):
    course_id: str | None = Field(default=None, max_length=128)


class ContinuousTurnInput(BaseModel):
    turn_id: str = Field(min_length=1, max_length=128)
    user_answer: str = Field(min_length=1, max_length=4000)
    course_id: str | None = Field(default=None, max_length=128)


class ContinuousConfirmInput(BaseModel):
    fields: dict[str, Any] = Field(default_factory=dict)
    dimensions: list[dict[str, Any]] = Field(default_factory=list)
    weak_point_attribution: list[dict[str, Any]] = Field(default_factory=list)
    continue_conversation: bool = False


def _student(user: DBUser) -> DBUser:
    if normalize_role(user.role) != "student":
        raise HTTPException(status_code=403, detail="仅学生可以建立初始画像。")
    return user


def _raise(error: OnboardingError) -> None:
    if error.code in {"field_conflict", "evidence_confirmation_required", "update_in_progress_course"}:
        status_code = 409
    elif error.code == "evidence_forbidden":
        status_code = 403
    elif error.code in {"evidence_not_found", "course_not_found"}:
        status_code = 404
    else:
        status_code = 400
    raise HTTPException(status_code=status_code, detail={"code": error.code, "message": error.message})


@router.get("/status")
async def get_status(current_user: DBUser = Depends(get_current_user)):
    user = _student(current_user)
    return await run_db_op(onboarding_status, user, feature_enabled=CONFIG.onboarding_v2)


@router.get("/session")
async def get_session(current_user: DBUser = Depends(get_current_user)):
    user = _student(current_user)

    def operation(db):
        session = get_or_create_session(db, user, feature_enabled=CONFIG.onboarding_v2)
        return session_payload(db, session, feature_enabled=CONFIG.onboarding_v2)

    return await run_db_op(operation)


@router.post("/turns")
async def submit_turn(payload: TurnInput, current_user: DBUser = Depends(get_current_user)):
    user = _student(current_user)
    try:
        return await run_db_op(
            record_turn,
            user,
            turn_id=payload.turn_id,
            question_dimension=payload.question_dimension,
            user_answer=payload.user_answer,
            feature_enabled=CONFIG.onboarding_v2,
            extractor=lambda dimension, answer: llm_extract_candidates(
                dimension,
                answer,
                owner_public_id=user.public_id,
            ),
        )
    except OnboardingError as error:
        _raise(error)


@router.post("/turns/{turn_id}/confirm")
async def confirm_candidate(
    turn_id: str,
    payload: ConfirmInput,
    current_user: DBUser = Depends(get_current_user),
):
    user = _student(current_user)
    try:
        return await run_db_op(
            confirm_turn,
            user,
            turn_id=turn_id,
            fields=payload.fields,
            resolve_conflict=payload.resolve_conflict,
            feature_enabled=CONFIG.onboarding_v2,
        )
    except OnboardingError as error:
        _raise(error)


@router.post("/personal-evidence")
async def upload_evidence(
    evidence_type: str = Form(...),
    file: UploadFile = File(...),
    current_user: DBUser = Depends(get_current_user),
):
    user = _student(current_user)
    raw = await file.read(CONFIG.max_upload_bytes + 1)
    if len(raw) > CONFIG.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail={"code": "personal_evidence_too_large", "message": "个人资料文件过大。"},
        )
    try:
        return await run_db_op(
            upload_personal_evidence,
            user,
            evidence_type=evidence_type,
            filename=file.filename or "",
            raw=raw,
            feature_enabled=CONFIG.onboarding_v2,
        )
    except OnboardingError as error:
        _raise(error)


@router.post("/personal-evidence/{evidence_id}/confirm")
async def confirm_evidence(
    evidence_id: str,
    payload: EvidenceConfirmInput,
    current_user: DBUser = Depends(get_current_user),
):
    user = _student(current_user)
    try:
        return await run_db_op(
            confirm_personal_evidence,
            user,
            evidence_id=evidence_id,
            fields=payload.fields,
            feature_enabled=CONFIG.onboarding_v2,
        )
    except OnboardingError as error:
        _raise(error)


@router.post("/personal-evidence/{evidence_id}/discard")
async def discard_evidence(
    evidence_id: str,
    current_user: DBUser = Depends(get_current_user),
):
    user = _student(current_user)
    try:
        return await run_db_op(
            discard_personal_evidence,
            user,
            evidence_id=evidence_id,
            feature_enabled=CONFIG.onboarding_v2,
        )
    except OnboardingError as error:
        _raise(error)


@router.post("/finalize")
async def finalize_profile(current_user: DBUser = Depends(get_current_user)):
    user = _student(current_user)
    try:
        return await run_db_op(
            finalize_initial_profile,
            user,
            feature_enabled=CONFIG.onboarding_v2,
        )
    except OnboardingError as error:
        _raise(error)


@router.get("/update/session")
async def get_continuous_update_session(current_user: DBUser = Depends(get_current_user)):
    user = _student(current_user)

    def operation(db):
        session = get_or_create_session(db, user, feature_enabled=CONFIG.onboarding_v2)
        state = (session.course_context or {}).get("continuousUpdate")
        has_update_turn = db.query(DBOnboardingTurn).filter_by(
            session_id=session.id,
            question_dimension="continuous",
        ).first() is not None
        if isinstance(state, dict) and (state.get("active") or has_update_turn):
            return continuous_update_session_payload(db, session, feature_enabled=CONFIG.onboarding_v2)
        return {
            "schemaVersion": "profile.continuous-update.v1",
            "featureEnabled": CONFIG.onboarding_v2,
            "active": False,
            "available": True,
            "sessionId": session.id,
            "message": "可以开始一次新的学情画像更新。",
        }

    return await run_db_op(operation)


@router.post("/update/session")
async def start_profile_update(
    payload: ContinuousStartInput,
    current_user: DBUser = Depends(get_current_user),
):
    user = _student(current_user)
    try:
        return await run_db_op(
            start_continuous_update,
            user,
            course_id=payload.course_id,
            feature_enabled=CONFIG.onboarding_v2,
        )
    except OnboardingError as error:
        _raise(error)


@router.get("/update/reminder")
async def get_profile_update_reminder(
    course_id: str | None = None,
    current_user: DBUser = Depends(get_current_user),
):
    user = _student(current_user)
    try:
        return await run_db_op(continuous_update_reminder, user, course_id=course_id)
    except OnboardingError as error:
        _raise(error)


@router.post("/update/reminder/dismiss")
async def dismiss_profile_update_reminder(
    course_id: str | None = None,
    current_user: DBUser = Depends(get_current_user),
):
    user = _student(current_user)
    try:
        return await run_db_op(dismiss_continuous_update_reminder, user, course_id=course_id)
    except OnboardingError as error:
        _raise(error)


@router.post("/update/turns")
async def submit_profile_update_turn(
    payload: ContinuousTurnInput,
    current_user: DBUser = Depends(get_current_user),
):
    user = _student(current_user)
    try:
        return await run_db_op(
            record_continuous_turn,
            user,
            turn_id=payload.turn_id,
            user_answer=payload.user_answer,
            course_id=payload.course_id,
            feature_enabled=CONFIG.onboarding_v2,
        )
    except OnboardingError as error:
        _raise(error)


@router.post("/update/turns/{turn_id}/confirm")
async def confirm_profile_update_turn(
    turn_id: str,
    payload: ContinuousConfirmInput,
    current_user: DBUser = Depends(get_current_user),
):
    user = _student(current_user)
    try:
        return await run_db_op(
            confirm_continuous_turn,
            user,
            turn_id=turn_id,
            fields=payload.fields,
            dimensions=payload.dimensions,
            attributions=payload.weak_point_attribution,
            continue_conversation=payload.continue_conversation,
            feature_enabled=CONFIG.onboarding_v2,
        )
    except OnboardingError as error:
        _raise(error)


@router.post("/update/complete")
async def complete_profile_update(current_user: DBUser = Depends(get_current_user)):
    user = _student(current_user)
    try:
        return await run_db_op(
            complete_continuous_update,
            user,
            feature_enabled=CONFIG.onboarding_v2,
        )
    except OnboardingError as error:
        _raise(error)
