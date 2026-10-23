from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field

from app.auth import enforce_student_access, get_current_user
from app.database import DBUser, run_db_op
from app.m2_contracts import StrictModel
from app.wrong_question_videos import (
    WrongQuestionVideoError,
    generate_wrong_question_video,
    get_wrong_question_video,
    list_wrong_question_videos,
)


router = APIRouter(prefix="/api/v1/wrong-question-videos", tags=["wrong-question-videos"])


class GenerateInput(StrictModel):
    student_id: str = Field(min_length=1, max_length=64)
    wrong_question_id: int = Field(ge=1)


def _http(exc: WrongQuestionVideoError) -> HTTPException:
    if "forbidden" in exc.code:
        code = status.HTTP_403_FORBIDDEN
    elif exc.code in {
        "wrong_video.wrong_question_unknown",
        "wrong_video.quiz_record_missing",
        "wrong_video.student_owner_missing",
        "wrong_video.link_unknown",
    }:
        code = status.HTTP_404_NOT_FOUND
    else:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(code, detail={"code": exc.code, "message": str(exc)})


def _operation(fn, *, commit: bool = False):
    def operation(db):
        try:
            result = fn(db)
            if commit:
                db.commit()
            return result
        except WrongQuestionVideoError as exc:
            db.rollback()
            raise _http(exc) from exc
    return operation


@router.post("", status_code=status.HTTP_201_CREATED)
async def generate(payload: GenerateInput, current_user: DBUser = Depends(get_current_user)):
    student_id = enforce_student_access(payload.student_id, current_user)
    return await run_db_op(_operation(
        lambda db: generate_wrong_question_video(
            db, actor=current_user, student_id=student_id,
            wrong_question_id=payload.wrong_question_id,
        ),
        commit=True,
    ))


@router.get("")
async def list_links(student_id: str, wrong_question_id: int | None = None, current_user: DBUser = Depends(get_current_user)):
    scope = enforce_student_access(student_id, current_user)
    return await run_db_op(_operation(
        lambda db: list_wrong_question_videos(
            db, actor=current_user, student_id=scope, wrong_question_id=wrong_question_id,
        )
    ))


@router.get("/{link_id}")
async def detail(link_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_operation(
        lambda db: get_wrong_question_video(db, actor=current_user, link_id=link_id)
    ))
