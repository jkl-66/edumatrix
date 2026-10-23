from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field

from app.auth import get_current_user
from app.course_sharing import (
    CourseSharingError, create_derived_copy, decide_update, propagate_withdrawals,
    publish_release, workspace,
)
from app.database import DBUser, run_db_op
from app.m2_contracts import StrictModel


router = APIRouter(prefix="/api/v1/course-sharing", tags=["course-sharing"])


class ReleaseInput(StrictModel):
    course_id: str = Field(min_length=1, max_length=128)
    target_type: Literal["class", "organization"]
    target_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=256)


class DecisionInput(StrictModel):
    upstream_release_id: str = Field(min_length=1, max_length=64)
    action: Literal["accept", "ignore"]
    reason: str = Field(min_length=8, max_length=2000)
    expected_version: int = Field(ge=1)


def _http(exc: CourseSharingError) -> HTTPException:
    if exc.code.endswith("unknown"): code = status.HTTP_404_NOT_FOUND
    elif "forbidden" in exc.code: code = status.HTTP_403_FORBIDDEN
    elif any(word in exc.code for word in ("conflict", "stale")): code = status.HTTP_409_CONFLICT
    else: code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(status_code=code, detail={"code": exc.code, "message": str(exc)})


def _operation(callback):
    def wrapped(db):
        try:
            result = callback(db); db.commit(); return result
        except CourseSharingError as exc:
            db.rollback(); raise _http(exc) from exc
    return wrapped


@router.get("/workspace")
async def get_workspace(current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_operation(lambda db: workspace(db, current_user)))


@router.post("/releases", status_code=201)
async def post_release(payload: ReleaseInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_operation(lambda db: publish_release(db, actor=current_user, **payload.model_dump())))


@router.post("/releases/{release_id}/copies", status_code=201)
async def post_copy(release_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_operation(lambda db: create_derived_copy(db, actor=current_user, release_id=release_id)))


@router.post("/copies/{copy_id}/decisions")
async def post_decision(copy_id: str, payload: DecisionInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_operation(lambda db: decide_update(db, actor=current_user, copy_id=copy_id, **payload.model_dump())))


@router.post("/withdrawals/propagate")
async def post_propagate(current_user: DBUser = Depends(get_current_user)):
    if current_user.role not in {"teacher", "admin"}:
        raise HTTPException(status_code=403, detail="teacher or admin role required")
    return await run_db_op(_operation(lambda db: propagate_withdrawals(db, current_user)))
