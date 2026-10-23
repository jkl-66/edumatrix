from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field

from app.auth import get_current_user
from app.database import DBUser, run_db_op
from app.m2_contracts import StrictModel
from app.m5_assessment_core import AssessmentCoreError, AttemptInput
from app.video_practices import (
    VideoPracticeError, bind_practice, get_video_practice, link_attempt,
    link_lab, practice_context, submit_objective_attempt, update_watch,
)


router = APIRouter(prefix="/api/v1/video-practices", tags=["video-practices"])


class BindingInput(StrictModel):
    question_version_ids: list[str] = Field(default_factory=list, max_length=20)
    lab_instance_ids: list[str] = Field(default_factory=list, max_length=10)
    expected_lock_version: int | None = Field(default=None, ge=0)


class WatchInput(StrictModel):
    watched_seconds: float = Field(ge=0)
    duration_seconds: float = Field(ge=0)
    completed: bool = False
    expected_lock_version: int = Field(ge=0)


class AttemptLinkInput(StrictModel):
    attempt_id: str = Field(min_length=1, max_length=64)


class LabLinkInput(StrictModel):
    lab_instance_id: str = Field(min_length=1, max_length=64)


def _http(exc: Exception) -> HTTPException:
    code = getattr(exc, "code", "video_practice.invalid")
    if code.endswith("unknown"):
        status_code = status.HTTP_404_NOT_FOUND
    elif "forbidden" in code:
        status_code = status.HTTP_403_FORBIDDEN
    elif "conflict" in code:
        status_code = status.HTTP_409_CONFLICT
    else:
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(status_code, detail={"code": code, "message": str(exc)})


def _op(fn, *, commit: bool = False):
    def operation(db):
        try:
            result = fn(db)
            if commit:
                db.commit()
            return result
        except (VideoPracticeError, AssessmentCoreError) as exc:
            db.rollback()
            raise _http(exc) from exc
    return operation


@router.get("/context/{link_id}")
async def context(link_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: practice_context(db, actor=current_user, link_id=link_id)))


@router.get("/{link_id}")
async def detail(link_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: get_video_practice(db, actor=current_user, link_id=link_id)))


@router.put("/{link_id}/bindings")
async def bindings(link_id: str, payload: BindingInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: bind_practice(
        db, actor=current_user, link_id=link_id,
        question_version_ids=payload.question_version_ids,
        lab_instance_ids=payload.lab_instance_ids,
        expected_lock_version=payload.expected_lock_version,
    ), commit=True))


@router.put("/{link_id}/watch-progress")
async def watch_progress(link_id: str, payload: WatchInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: update_watch(
        db, actor=current_user, link_id=link_id,
        watched_seconds=payload.watched_seconds, duration_seconds=payload.duration_seconds,
        completed=payload.completed, expected_lock_version=payload.expected_lock_version,
    ), commit=True))


@router.post("/{link_id}/attempts", status_code=201)
async def attempts(link_id: str, payload: AttemptInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: submit_objective_attempt(
        db, actor=current_user, link_id=link_id, attempt_input=payload,
    ), commit=True))


@router.post("/{link_id}/attempt-links", status_code=201)
async def attempt_links(link_id: str, payload: AttemptLinkInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: link_attempt(
        db, actor=current_user, link_id=link_id, attempt_id=payload.attempt_id,
    ), commit=True))


@router.post("/{link_id}/lab-links", status_code=201)
async def lab_links(link_id: str, payload: LabLinkInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: link_lab(
        db, actor=current_user, link_id=link_id, instance_id=payload.lab_instance_id,
    ), commit=True))
