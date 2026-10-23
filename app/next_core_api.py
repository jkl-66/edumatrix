"""NEXT-cycle core learning APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.authorization import require_course_access
from app.database import DBCourse, DBUser, run_db_op
from app.next_core_retrieval import search_persisted_course_documents
from app.next_core_memory import (
    MemoryGovernanceError,
    create_memory,
    list_memories,
    list_memory_audit,
    list_subscriptions,
    memory_payload,
    revoke_profile_subscription,
    subscription_payload,
    update_memory,
    upsert_profile_subscription,
    withdraw_memory,
)


router = APIRouter(prefix="/api/v1/next/core", tags=["next-core"])


class MemoryCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    memory_type: str = Field(min_length=1, max_length=32)
    content: str = Field(min_length=1, max_length=12000)
    sensitivity: str = Field(default="personal", pattern="^(personal|private)$")


class MemoryUpdateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=256)
    content: str | None = Field(default=None, min_length=1, max_length=12000)


class MemoryWithdrawRequest(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(default="user_withdrawn", max_length=500)


class ProfileSubscriptionRequest(BaseModel):
    profile_fields: list[str] = Field(default_factory=list, max_length=7)
    expected_version: int | None = Field(default=None, ge=0)


class SubscriptionRevokeRequest(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(default="user_revoked", max_length=500)


def _memory_http_error(exc: MemoryGovernanceError) -> HTTPException:
    if exc.code.endswith("unknown"):
        code = status.HTTP_404_NOT_FOUND
    elif "forbidden" in exc.code:
        code = status.HTTP_403_FORBIDDEN
    elif "conflict" in exc.code or "not_active" in exc.code or "profile_managed" in exc.code:
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    return HTTPException(status_code=code, detail={"code": exc.code, "message": str(exc)})


@router.get("/memories")
async def get_long_term_memories(
    include_withdrawn: bool = False,
    current_user: DBUser = Depends(get_current_user),
):
    items = await run_db_op(
        lambda session: list_memories(
            session, owner_public_id=current_user.public_id,
            include_withdrawn=include_withdrawn,
        )
    )
    return {"schema_version": "next.memory-list.v1", "items": items}


@router.post("/memories", status_code=201)
async def create_long_term_memory(
    payload: MemoryCreateRequest,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        row = create_memory(
            session, owner_public_id=current_user.public_id,
            title=payload.title, memory_type=payload.memory_type,
            content=payload.content, sensitivity=payload.sensitivity,
        )
        session.commit()
        return memory_payload(row)

    try:
        return await run_db_op(operation)
    except MemoryGovernanceError as exc:
        raise _memory_http_error(exc) from exc


@router.patch("/memories/{memory_id}")
async def update_long_term_memory(
    memory_id: str, payload: MemoryUpdateRequest,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        row = update_memory(
            session, owner_public_id=current_user.public_id,
            memory_id=memory_id, expected_version=payload.expected_version,
            title=payload.title, content=payload.content,
        )
        session.commit()
        return memory_payload(row)

    try:
        return await run_db_op(operation)
    except MemoryGovernanceError as exc:
        raise _memory_http_error(exc) from exc


@router.post("/memories/{memory_id}/withdraw")
async def withdraw_long_term_memory(
    memory_id: str, payload: MemoryWithdrawRequest,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        row = withdraw_memory(
            session, owner_public_id=current_user.public_id,
            memory_id=memory_id, expected_version=payload.expected_version,
            reason=payload.reason,
        )
        session.commit()
        return memory_payload(row)

    try:
        return await run_db_op(operation)
    except MemoryGovernanceError as exc:
        raise _memory_http_error(exc) from exc


@router.get("/memory-subscriptions")
async def get_memory_subscriptions(current_user: DBUser = Depends(get_current_user)):
    items = await run_db_op(
        lambda session: list_subscriptions(session, owner_public_id=current_user.public_id)
    )
    return {"schema_version": "next.memory-subscription-list.v1", "items": items}


@router.put("/memory-subscriptions/profile")
async def put_profile_memory_subscription(
    payload: ProfileSubscriptionRequest,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        row, changed = upsert_profile_subscription(
            session, owner_public_id=current_user.public_id,
            username=current_user.username, profile_fields=payload.profile_fields,
            expected_version=payload.expected_version,
        )
        session.commit()
        return {**subscription_payload(row), "memories_changed": changed}

    try:
        return await run_db_op(operation)
    except MemoryGovernanceError as exc:
        raise _memory_http_error(exc) from exc


@router.post("/memory-subscriptions/profile/revoke")
async def revoke_current_profile_subscription(
    payload: SubscriptionRevokeRequest,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        row = revoke_profile_subscription(
            session, owner_public_id=current_user.public_id,
            expected_version=payload.expected_version, reason=payload.reason,
        )
        session.commit()
        return subscription_payload(row)

    try:
        return await run_db_op(operation)
    except MemoryGovernanceError as exc:
        raise _memory_http_error(exc) from exc


@router.get("/memory-audit")
async def get_memory_audit(
    limit: int = Query(default=50, ge=1, le=100),
    current_user: DBUser = Depends(get_current_user),
):
    items = await run_db_op(
        lambda session: list_memory_audit(
            session, owner_public_id=current_user.public_id, limit=limit,
        )
    )
    return {"schema_version": "next.memory-audit-list.v1", "items": items}


@router.get("/courses/{course_id}/cross-language-search")
async def cross_language_course_search(
    course_id: str,
    q: str = Query(min_length=1, max_length=500),
    top_k: int = Query(default=5, ge=1, le=10),
    current_user: DBUser = Depends(get_current_user),
):
    def search(session):
        course = session.get(DBCourse, course_id)
        if course is None:
            raise HTTPException(status_code=404, detail="课程不存在")
        from course_catalog import course_is_selectable
        if not course_is_selectable(session, course):
            raise HTTPException(status_code=409, detail="课程已停止发布或没有可用学习资料")
        require_course_access(
            session,
            current_user,
            course_id=course.id,
            action="read",
            visibility=course.visibility,
        )
        try:
            return search_persisted_course_documents(
                session,
                course_id=course.id,
                query=q,
                top_k=top_k,
                actor=current_user,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return await run_db_op(search)
