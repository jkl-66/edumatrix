from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from app.database import (
    DBAuditLog, DBLearningEvent, DBMediaContextResource, DBMediaConversation,
    DBMediaMessage, DBMediaReadingPosition,
)
from app.identity import new_public_id


class MediaContextError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _fail(code: str, message: str) -> None:
    raise MediaContextError(code, message)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _audit(db: Any, *, owner: str, action: str, object_type: str, object_id: str, metadata: dict[str, Any]) -> None:
    db.add(DBAuditLog(
        actor_public_id=owner, action=action, object_type=object_type, object_id=object_id,
        trace_id=f"media-context-{new_public_id('trace')}", outcome="success", metadata_json=metadata,
    ))


def validate_locator(locator: str) -> str:
    value = locator.strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if value.startswith("/") and not value.startswith("//") and ".." not in value.split("/"):
        return value
    if parsed.scheme == "https" and parsed.netloc and not parsed.username and not parsed.password:
        return value
    _fail("media_locator_invalid", "video locator must be a safe local path or HTTPS URL")


def create_resource(db: Any, *, owner: str, course_id: str | None, resource_type: str, title: str,
                    language: str, locator: str, content: str, duration_ms: int) -> DBMediaContextResource:
    if resource_type not in {"code", "video"}:
        _fail("media_resource_type_invalid", "resource type must be code or video")
    normalized_content = content.replace("\r\n", "\n")
    normalized_locator = validate_locator(locator) if resource_type == "video" else ""
    if resource_type == "code" and not normalized_content.strip():
        _fail("media_code_empty", "code resource content is required")
    if resource_type == "video" and normalized_content:
        _fail("media_video_content_invalid", "video resource cannot persist code content")
    if duration_ms < 0:
        _fail("media_duration_invalid", "video duration cannot be negative")
    hash_material = normalized_content if resource_type == "code" else normalized_locator
    row = DBMediaContextResource(
        owner_public_id=owner, course_id=course_id, resource_type=resource_type,
        title=title.strip(), language=language.strip()[:32], locator=normalized_locator,
        content=normalized_content, content_sha256=_sha(hash_material),
        duration_ms=duration_ms if resource_type == "video" else 0,
    )
    db.add(row); db.flush()
    db.add(DBMediaReadingPosition(resource_id=row.id, owner_public_id=owner))
    _audit(db, owner=owner, action="media_resource.created", object_type="media_resource", object_id=row.id,
           metadata={"resource_type": resource_type, "course_id": course_id, "content_sha256": row.content_sha256, "content_persisted_in_audit": False})
    db.flush()
    return row


def owned_resource(db: Any, resource_id: str, owner: str) -> DBMediaContextResource:
    row = db.get(DBMediaContextResource, resource_id)
    if row is None:
        _fail("media_resource_unknown", "media resource does not exist")
    if row.owner_public_id != owner:
        _fail("media_resource_forbidden", "media resource belongs to another owner")
    return row


def resource_payload(db: Any, row: DBMediaContextResource, *, include_content: bool = True) -> dict[str, Any]:
    position = db.query(DBMediaReadingPosition).filter_by(resource_id=row.id).one()
    conversations = db.query(DBMediaConversation).filter_by(resource_id=row.id).order_by(DBMediaConversation.created_at).all()
    return {
        "id": row.id, "course_id": row.course_id, "resource_type": row.resource_type,
        "title": row.title, "language": row.language, "locator": row.locator,
        "content": row.content if include_content else "", "content_sha256": row.content_sha256,
        "duration_ms": row.duration_ms, "created_at": row.created_at.isoformat() if row.created_at else "",
        "position": position_payload(position),
        "conversations": [conversation_payload(db, item) for item in conversations],
    }


def position_payload(row: DBMediaReadingPosition) -> dict[str, Any]:
    return {"id": row.id, "line_number": row.line_number, "column_number": row.column_number,
            "playback_ms": row.playback_ms, "scroll_ratio": row.scroll_ratio,
            "lock_version": row.lock_version, "updated_at": row.updated_at.isoformat() if row.updated_at else ""}


def update_position(db: Any, *, row: DBMediaContextResource, owner: str, expected_version: int,
                    line_number: int, column_number: int, playback_ms: int, scroll_ratio: float) -> DBMediaReadingPosition:
    position = db.query(DBMediaReadingPosition).filter_by(resource_id=row.id).one()
    if position.owner_public_id != owner:
        _fail("media_position_forbidden", "media position belongs to another owner")
    if position.lock_version != expected_version:
        _fail("media_position_conflict", "media position version changed")
    if row.resource_type == "code":
        line_count = max(1, len(row.content.splitlines()))
        if line_number > line_count or playback_ms != 0:
            _fail("media_code_position_invalid", "code position is outside the registered content")
    elif playback_ms > row.duration_ms and row.duration_ms > 0:
        _fail("media_video_position_invalid", "video position exceeds registered duration")
    position.line_number = line_number if row.resource_type == "code" else 1
    position.column_number = column_number if row.resource_type == "code" else 1
    position.playback_ms = playback_ms if row.resource_type == "video" else 0
    position.scroll_ratio = scroll_ratio
    position.lock_version += 1
    db.add(DBLearningEvent(
        owner_public_id=owner, course_id=row.course_id, event_type="media.position.saved",
        schema_version="next.media-context.v1", source="media_context", trace_id=f"media-position-{new_public_id('trace')}",
        object_type="media_resource", object_id=row.id,
        payload={"resource_type": row.resource_type, "line_number": position.line_number,
                 "playback_ms": position.playback_ms, "scroll_ratio": position.scroll_ratio,
                 "lock_version": position.lock_version}, occurred_at=_now(),
    ))
    _audit(db, owner=owner, action="media_position.updated", object_type="media_position", object_id=position.id,
           metadata={"resource_id": row.id, "resource_type": row.resource_type, "lock_version": position.lock_version})
    db.flush()
    return position


def create_conversation(db: Any, *, row: DBMediaContextResource, owner: str, title: str) -> DBMediaConversation:
    conversation = DBMediaConversation(resource_id=row.id, owner_public_id=owner, title=title.strip())
    db.add(conversation); db.flush()
    _audit(db, owner=owner, action="media_conversation.created", object_type="media_conversation", object_id=conversation.id,
           metadata={"resource_id": row.id, "title_sha256": _sha(conversation.title), "title_persisted_in_audit": False})
    return conversation


def owned_conversation(db: Any, conversation_id: str, owner: str) -> DBMediaConversation:
    row = db.get(DBMediaConversation, conversation_id)
    if row is None:
        _fail("media_conversation_unknown", "media conversation does not exist")
    if row.owner_public_id != owner:
        _fail("media_conversation_forbidden", "media conversation belongs to another owner")
    return row


def conversation_payload(db: Any, row: DBMediaConversation) -> dict[str, Any]:
    messages = db.query(DBMediaMessage).filter_by(conversation_id=row.id).order_by(DBMediaMessage.sequence).all()
    return {"id": row.id, "resource_id": row.resource_id, "title": row.title, "status": row.status,
            "lock_version": row.lock_version, "created_at": row.created_at.isoformat() if row.created_at else "",
            "messages": [{"id": item.id, "sequence": item.sequence, "role": item.role, "content": item.content,
                          "content_sha256": item.content_sha256, "position_snapshot": item.position_snapshot,
                          "created_at": item.created_at.isoformat() if item.created_at else ""} for item in messages]}


def append_message(db: Any, *, conversation: DBMediaConversation, owner: str, expected_version: int,
                   role: str, content: str) -> DBMediaMessage:
    if conversation.status != "active":
        _fail("media_conversation_archived", "archived conversation cannot accept messages")
    if conversation.lock_version != expected_version:
        _fail("media_conversation_conflict", "media conversation version changed")
    if role not in {"user", "assistant", "note"}:
        _fail("media_message_role_invalid", "message role is invalid")
    position = db.query(DBMediaReadingPosition).filter_by(resource_id=conversation.resource_id).one()
    sequence = db.query(DBMediaMessage).filter_by(conversation_id=conversation.id).count() + 1
    message = DBMediaMessage(
        conversation_id=conversation.id, owner_public_id=owner, sequence=sequence, role=role,
        content=content.strip(), content_sha256=_sha(content.strip()), position_snapshot=position_payload(position),
    )
    db.add(message)
    db.flush()
    conversation.lock_version += 1
    _audit(db, owner=owner, action="media_message.appended", object_type="media_message", object_id=message.id,
           metadata={"conversation_id": conversation.id, "resource_id": conversation.resource_id,
                     "role": role, "sequence": sequence, "content_sha256": message.content_sha256,
                     "content_persisted_in_audit": False})
    db.flush()
    return message


def archive_conversation(db: Any, *, conversation: DBMediaConversation, expected_version: int) -> None:
    if conversation.lock_version != expected_version:
        _fail("media_conversation_conflict", "media conversation version changed")
    conversation.status = "archived"
    conversation.archived_at = _now()
    conversation.lock_version += 1
    db.flush()
