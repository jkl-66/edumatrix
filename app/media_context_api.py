from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field

from app.auth import get_current_user
from app.authorization import require_course_access
from app.database import DBCourse, DBMediaContextResource, DBUser, run_db_op
from app.m2_contracts import StrictModel
from app.media_context import (
    MediaContextError, append_message, archive_conversation, conversation_payload,
    create_conversation, create_resource, owned_conversation, owned_resource,
    position_payload, resource_payload, update_position,
)


router = APIRouter(prefix="/api/v1/media-context", tags=["media-context"])


class ResourceInput(StrictModel):
    resource_type: str = Field(pattern="^(code|video)$")
    title: str = Field(min_length=1, max_length=256)
    course_id: str | None = Field(default=None, max_length=128)
    language: str = Field(default="", max_length=32)
    locator: str = Field(default="", max_length=2048)
    content: str = Field(default="", max_length=200000)
    duration_ms: int = Field(default=0, ge=0, le=86_400_000)


class PositionInput(StrictModel):
    expected_lock_version: int = Field(ge=1)
    line_number: int = Field(default=1, ge=1, le=1_000_000)
    column_number: int = Field(default=1, ge=1, le=1_000_000)
    playback_ms: int = Field(default=0, ge=0, le=86_400_000)
    scroll_ratio: float = Field(default=0.0, ge=0.0, le=1.0)


class ConversationInput(StrictModel):
    title: str = Field(min_length=1, max_length=256)


class MessageInput(StrictModel):
    expected_lock_version: int = Field(ge=1)
    role: str = Field(default="note", pattern="^(user|note)$")
    content: str = Field(min_length=1, max_length=12000)


class ArchiveInput(StrictModel):
    expected_lock_version: int = Field(ge=1)


def _http(exc: MediaContextError) -> HTTPException:
    if exc.code.endswith("unknown"):
        code = status.HTTP_404_NOT_FOUND
    elif "forbidden" in exc.code:
        code = status.HTTP_403_FORBIDDEN
    elif "conflict" in exc.code or "archived" in exc.code:
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(status_code=code, detail={"code": exc.code, "message": str(exc)})


@router.post("/resources", status_code=201)
async def post_resource(payload: ResourceInput, current_user: DBUser = Depends(get_current_user)):
    def operation(db):
        try:
            if payload.course_id:
                course = db.get(DBCourse, payload.course_id)
                if course is None:
                    raise HTTPException(status_code=404, detail={"code": "media_course_unknown", "message": "course does not exist"})
                from course_catalog import course_is_selectable
                if not course_is_selectable(db, course):
                    raise HTTPException(status_code=409, detail={"code": "media_course_unavailable", "message": "course is not currently selectable"})
                require_course_access(db, current_user, course_id=course.id, action="read", visibility=course.visibility)
            row = create_resource(db, owner=current_user.public_id, **payload.model_dump())
            result = resource_payload(db, row)
            db.commit()
            return result
        except MediaContextError as exc:
            raise _http(exc) from exc
    return await run_db_op(operation)


@router.get("/resources")
async def get_resources(current_user: DBUser = Depends(get_current_user)):
    def operation(db):
        rows = db.query(DBMediaContextResource).filter_by(owner_public_id=current_user.public_id).order_by(DBMediaContextResource.created_at.desc()).all()
        return {"schema_version": "next.media-context-list.v1", "items": [resource_payload(db, row, include_content=False) for row in rows]}
    return await run_db_op(operation)


@router.get("/resources/{resource_id}")
async def get_resource(resource_id: str, current_user: DBUser = Depends(get_current_user)):
    def operation(db):
        try: return resource_payload(db, owned_resource(db, resource_id, current_user.public_id))
        except MediaContextError as exc: raise _http(exc) from exc
    return await run_db_op(operation)


@router.put("/resources/{resource_id}/position")
async def put_position(resource_id: str, payload: PositionInput, current_user: DBUser = Depends(get_current_user)):
    def operation(db):
        try:
            row = owned_resource(db, resource_id, current_user.public_id)
            position = update_position(db, row=row, owner=current_user.public_id,
                                       expected_version=payload.expected_lock_version,
                                       line_number=payload.line_number, column_number=payload.column_number,
                                       playback_ms=payload.playback_ms, scroll_ratio=payload.scroll_ratio)
            result = position_payload(position); db.commit(); return result
        except MediaContextError as exc: raise _http(exc) from exc
    return await run_db_op(operation)


@router.post("/resources/{resource_id}/conversations", status_code=201)
async def post_conversation(resource_id: str, payload: ConversationInput, current_user: DBUser = Depends(get_current_user)):
    def operation(db):
        try:
            resource = owned_resource(db, resource_id, current_user.public_id)
            row = create_conversation(db, row=resource, owner=current_user.public_id, title=payload.title)
            result = conversation_payload(db, row); db.commit(); return result
        except MediaContextError as exc: raise _http(exc) from exc
    return await run_db_op(operation)


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, current_user: DBUser = Depends(get_current_user)):
    def operation(db):
        try: return conversation_payload(db, owned_conversation(db, conversation_id, current_user.public_id))
        except MediaContextError as exc: raise _http(exc) from exc
    return await run_db_op(operation)


@router.post("/conversations/{conversation_id}/messages", status_code=201)
async def post_message(conversation_id: str, payload: MessageInput, current_user: DBUser = Depends(get_current_user)):
    def operation(db):
        try:
            conversation = owned_conversation(db, conversation_id, current_user.public_id)
            append_message(db, conversation=conversation, owner=current_user.public_id,
                           expected_version=payload.expected_lock_version, role=payload.role, content=payload.content)
            result = conversation_payload(db, conversation); db.commit(); return result
        except MediaContextError as exc: raise _http(exc) from exc
    return await run_db_op(operation)


@router.post("/conversations/{conversation_id}/archive")
async def post_archive(conversation_id: str, payload: ArchiveInput, current_user: DBUser = Depends(get_current_user)):
    def operation(db):
        try:
            conversation = owned_conversation(db, conversation_id, current_user.public_id)
            archive_conversation(db, conversation=conversation, expected_version=payload.expected_lock_version)
            result = conversation_payload(db, conversation); db.commit(); return result
        except MediaContextError as exc: raise _http(exc) from exc
    return await run_db_op(operation)
