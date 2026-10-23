from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import Field

from app.auth import get_current_user
from app.chapter_videos import (
    ChapterVideoError,
    chapter_video_context,
    generate_chapter_video,
    get_chapter_video,
    list_chapter_videos,
)
from app.database import DBUser, run_db_op
from app.m2_contracts import StrictModel


router = APIRouter(prefix="/api/v1/chapter-videos", tags=["chapter-videos"])


class GenerateInput(StrictModel):
    course_id: str = Field(min_length=1, max_length=128)
    chapter_id: str = Field(min_length=1, max_length=64)
    profile_snapshot_id: str | None = Field(default=None, max_length=64)


def _http(exc: ChapterVideoError) -> HTTPException:
    if exc.code.endswith("unknown"):
        code = status.HTTP_404_NOT_FOUND
    elif "forbidden" in exc.code:
        code = status.HTTP_403_FORBIDDEN
    elif "mismatch" in exc.code:
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(code, detail={"code": exc.code, "message": str(exc)})


def _op(fn, *, commit: bool = False):
    def operation(db):
        try:
            result = fn(db)
            if commit:
                db.commit()
            return result
        except ChapterVideoError as exc:
            db.rollback()
            raise _http(exc) from exc
    return operation


@router.get("/context")
async def context(
    course_id: str | None = Query(default=None, max_length=128),
    current_user: DBUser = Depends(get_current_user),
):
    return await run_db_op(_op(lambda db: chapter_video_context(db, actor=current_user, course_id=course_id)))


@router.get("")
async def listing(
    course_id: str | None = Query(default=None, max_length=128),
    chapter_id: str | None = Query(default=None, max_length=64),
    current_user: DBUser = Depends(get_current_user),
):
    return await run_db_op(_op(lambda db: list_chapter_videos(db, actor=current_user, course_id=course_id, chapter_id=chapter_id)))


@router.post("", status_code=201)
async def generate(payload: GenerateInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: generate_chapter_video(
        db, actor=current_user, course_id=payload.course_id,
        chapter_id=payload.chapter_id, profile_snapshot_id=payload.profile_snapshot_id,
    ), commit=True))


@router.get("/{link_id}")
async def detail(link_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: get_chapter_video(db, actor=current_user, link_id=link_id)))
