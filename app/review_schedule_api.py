from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import Field

from app.auth import get_current_user
from app.database import DBUser, run_db_op
from app.m2_contracts import StrictModel
from app.review_schedule import (
    ReviewScheduleError,
    build_review_schedule,
    complete_review_task,
    create_review_resource_job,
)


router = APIRouter(prefix="/api/v1/review-schedule", tags=["review-schedule"])


class ReviewCompletionInput(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    recall_score: float = Field(ge=0.0, le=1.0)
    duration_minutes: int = Field(default=10, ge=1, le=240)
    assessment_attempt_id: str | None = Field(default=None, min_length=8, max_length=64)
    assessment_event_id: str | None = Field(default=None, min_length=8, max_length=64)


class ReviewResourceInput(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=128)


def _http(exc: ReviewScheduleError) -> HTTPException:
    if exc.code.endswith("unknown"):
        code = status.HTTP_404_NOT_FOUND
    elif "forbidden" in exc.code:
        code = status.HTTP_403_FORBIDDEN
    elif "conflict" in exc.code:
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(code, detail={"code": exc.code, "message": str(exc)})


@router.get("")
async def review_schedule(
    month: str = Query(pattern=r"^\d{4}-\d{2}$"),
    course_id: str = Query(default="all", max_length=128),
    current_user: DBUser = Depends(get_current_user),
):
    try:
        return await run_db_op(
            lambda db: build_review_schedule(
                db, actor=current_user, month=month, course_id=course_id,
            )
        )
    except ReviewScheduleError as exc:
        raise _http(exc) from exc


@router.post("/tasks/{task_id}/complete")
async def review_task_complete(
    task_id: str,
    payload: ReviewCompletionInput,
    current_user: DBUser = Depends(get_current_user),
):
    try:
        return await run_db_op(
            lambda db: complete_review_task(
                db,
                actor=current_user,
                task_id=task_id,
                idempotency_key=payload.idempotency_key,
                recall_score=payload.recall_score,
                duration_minutes=payload.duration_minutes,
                assessment_attempt_id=payload.assessment_attempt_id,
                assessment_event_id=payload.assessment_event_id,
            )
        )
    except ReviewScheduleError as exc:
        raise _http(exc) from exc


@router.post("/tasks/{task_id}/resource-jobs", status_code=201)
async def review_resource_job(
    task_id: str,
    payload: ReviewResourceInput,
    current_user: DBUser = Depends(get_current_user),
):
    try:
        return await run_db_op(
            lambda db: create_review_resource_job(
                db,
                actor=current_user,
                task_id=task_id,
                idempotency_key=payload.idempotency_key,
            )
        )
    except ReviewScheduleError as exc:
        raise _http(exc) from exc
