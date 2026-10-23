from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field

from app.auth import get_current_user
from app.database import DBUser, run_db_op
from app.m2_contracts import StrictModel
from app.teaching_animations import (
    TeachingAnimationError, create_project, create_version, get_project,
    list_projects, list_templates, update_playback,
)


router = APIRouter(prefix="/api/v1/teaching-animations", tags=["teaching-animations"])


class ProjectInput(StrictModel):
    title: str = Field(min_length=1, max_length=256)
    template_id: str = Field(min_length=1, max_length=64)
    parameters: dict[str, Any] = Field(default_factory=dict)
    course_id: str | None = Field(default=None, max_length=128)


class VersionInput(StrictModel):
    parameters: dict[str, Any] = Field(default_factory=dict)
    expected_lock_version: int = Field(ge=1)


class PlaybackInput(StrictModel):
    current_frame: int = Field(ge=0)
    playback_status: str = Field(min_length=1, max_length=16)
    expected_lock_version: int = Field(ge=1)


def _http(exc: TeachingAnimationError) -> HTTPException:
    code = exc.code
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
        except TeachingAnimationError as exc:
            db.rollback()
            raise _http(exc) from exc
    return operation


@router.get("/templates")
async def templates(current_user: DBUser = Depends(get_current_user)):
    return list_templates()


@router.get("")
async def projects(current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: list_projects(db, actor=current_user)))


@router.post("", status_code=201)
async def project_create(payload: ProjectInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: create_project(
        db, actor=current_user, title=payload.title, template_id=payload.template_id,
        parameters=payload.parameters, course_id=payload.course_id,
    ), commit=True))


@router.get("/{animation_id}")
async def project_detail(animation_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: get_project(db, actor=current_user, animation_id=animation_id)))


@router.post("/{animation_id}/versions")
async def version_create(animation_id: str, payload: VersionInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: create_version(
        db, actor=current_user, animation_id=animation_id,
        parameters=payload.parameters, expected_lock_version=payload.expected_lock_version,
    ), commit=True))


@router.put("/{animation_id}/playback")
async def playback_update(animation_id: str, payload: PlaybackInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: update_playback(
        db, actor=current_user, animation_id=animation_id,
        current_frame=payload.current_frame, playback_status=payload.playback_status,
        expected_lock_version=payload.expected_lock_version,
    ), commit=True))
