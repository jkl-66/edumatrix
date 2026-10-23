from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field

from app.auth import get_current_user
from app.course_governance import (CourseGovernanceError, class_payload, create_class, create_group, create_task,
                                   governance_catalog, list_classes, publish_task, upsert_member, withdraw_course)
from app.database import DBTeachingClass, DBUser, run_db_op
from app.m2_contracts import StrictModel


router = APIRouter(prefix="/api/v1/course-governance", tags=["course-governance"])


class ClassInput(StrictModel):
    course_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=256)
    term: str = Field(min_length=1, max_length=64)


class GroupInput(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)


class MemberInput(StrictModel):
    user_public_id: str = Field(min_length=1, max_length=64)
    role: Literal["teacher", "assistant", "student"] = "student"
    group_id: str | None = Field(default=None, max_length=64)
    expected_version: int | None = Field(default=None, ge=1)


class TaskInput(StrictModel):
    title: str = Field(min_length=1, max_length=256)
    instructions: str = Field(default="", max_length=12000)
    group_id: str | None = Field(default=None, max_length=64)
    due_at: datetime | None = None
    idempotency_key: str = Field(min_length=8, max_length=128)


class VersionInput(StrictModel): expected_version: int = Field(ge=1)


class WithdrawalInput(StrictModel):
    reason: str = Field(min_length=8, max_length=2000)
    expected_status: str = Field(min_length=1, max_length=32)


def _http(exc: CourseGovernanceError) -> HTTPException:
    if exc.code.endswith("unknown"): code = status.HTTP_404_NOT_FOUND
    elif "forbidden" in exc.code: code = status.HTTP_403_FORBIDDEN
    elif "conflict" in exc.code: code = status.HTTP_409_CONFLICT
    else: code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(status_code=code, detail={"code": exc.code, "message": str(exc)})


def _operation(callback):
    def wrapped(db):
        try:
            result = callback(db); db.commit(); return result
        except CourseGovernanceError as exc:
            db.rollback(); raise _http(exc) from exc
    return wrapped


@router.get("/classes")
async def get_classes(course_id: str | None = None, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_operation(lambda db: {"schema_version":"next.course-governance-list.v1", "items":list_classes(db,current_user,course_id)}))


@router.get("/catalog")
async def get_catalog(current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_operation(lambda db: governance_catalog(db, current_user)))


@router.get("/classes/{class_id}")
async def get_class(class_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_operation(lambda db: class_payload(db, db.get(DBTeachingClass,class_id) or (_ for _ in ()).throw(CourseGovernanceError("governance_class_unknown","teaching class does not exist")), current_user)))


@router.post("/classes", status_code=201)
async def post_class(payload: ClassInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_operation(lambda db: create_class(db, actor=current_user, **payload.model_dump())))


@router.post("/classes/{class_id}/groups", status_code=201)
async def post_group(class_id: str, payload: GroupInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_operation(lambda db: create_group(db, actor=current_user,class_id=class_id,**payload.model_dump())))


@router.put("/classes/{class_id}/members")
async def put_member(class_id: str, payload: MemberInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_operation(lambda db: upsert_member(db,actor=current_user,class_id=class_id,**payload.model_dump())))


@router.post("/classes/{class_id}/tasks", status_code=201)
async def post_task(class_id: str, payload: TaskInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_operation(lambda db: create_task(db,actor=current_user,class_id=class_id,**payload.model_dump())))


@router.post("/tasks/{task_id}/publish")
async def post_publish(task_id: str, payload: VersionInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_operation(lambda db: publish_task(db,actor=current_user,task_id=task_id,**payload.model_dump())))


@router.post("/courses/{course_id}/withdraw")
async def post_withdraw(course_id: str, payload: WithdrawalInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_operation(lambda db: withdraw_course(db,actor=current_user,course_id=course_id,**payload.model_dump())))
