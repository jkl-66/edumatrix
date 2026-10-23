"""Owner-scoped long-term memory governance and profile projections."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.database import (
    DBAuditLog,
    DBMemoryItem,
    DBMemorySubscription,
    DBStudentProfile,
    DBTutorContextSession,
    DBUser,
)
from app.m1_lifecycle import record_audit


ALLOWED_MEMORY_TYPES = frozenset({"preference", "goal", "constraint", "learning_context"})
PROFILE_FIELD_TYPES = {
    "major": "learning_context",
    "target_course": "learning_context",
    "cognitive_style": "preference",
    "motivation_type": "preference",
    "learning_goals": "goal",
    "interaction_preferences": "preference",
    "weak_points": "learning_context",
}


class MemoryGovernanceError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _fail(code: str, message: str) -> None:
    raise MemoryGovernanceError(code, message)


def _content(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def memory_payload(row: DBMemoryItem) -> dict[str, Any]:
    return {
        "id": row.id,
        "memory_key": row.memory_key,
        "title": row.title,
        "memory_type": row.memory_type,
        "content": row.content,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "confidence": row.confidence,
        "sensitivity": row.sensitivity,
        "status": row.status,
        "lock_version": row.lock_version,
        "withdrawal_reason": row.withdrawal_reason or "",
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "withdrawn_at": row.withdrawn_at.isoformat() if row.withdrawn_at else None,
    }


def subscription_payload(row: DBMemorySubscription) -> dict[str, Any]:
    return {
        "id": row.id,
        "subscriber_type": row.subscriber_type,
        "subscriber_key": row.subscriber_key,
        "profile_fields": list(row.profile_fields or []),
        "memory_types": list(row.memory_types or []),
        "status": row.status,
        "lock_version": row.lock_version,
        "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "revoke_reason": row.revoke_reason or "",
    }


def _owned_memory(session: Any, *, owner_public_id: str, memory_id: str) -> DBMemoryItem:
    row = session.query(DBMemoryItem).filter_by(id=memory_id).first()
    if row is None:
        _fail("memory_unknown", "memory item does not exist")
    if row.owner_public_id != owner_public_id:
        _fail("memory_forbidden", "memory item belongs to another owner")
    return row


def active_memory_projection(session: Any, *, owner_public_id: str) -> dict[str, Any]:
    rows = session.query(DBMemoryItem).filter_by(
        owner_public_id=owner_public_id, status="active",
    ).order_by(DBMemoryItem.memory_type, DBMemoryItem.created_at, DBMemoryItem.id).all()
    return {
        "schema_version": "next.long-term-memory.v1",
        "items": [
            {
                "id": row.id,
                "title": row.title,
                "memory_type": row.memory_type,
                "content": row.content,
                "source_type": row.source_type,
                "version": row.lock_version,
            }
            for row in rows
        ],
    }


def attach_memory_projection(
    session: Any, *, owner_public_id: str, snapshot: dict[str, Any],
) -> dict[str, Any]:
    result = dict(snapshot)
    result["long_term_memory"] = active_memory_projection(
        session, owner_public_id=owner_public_id,
    )
    return result


def refresh_tutor_contexts(session: Any, *, owner_public_id: str) -> int:
    projection = active_memory_projection(session, owner_public_id=owner_public_id)
    rows = session.query(DBTutorContextSession).filter_by(
        owner_public_id=owner_public_id, status="active",
    ).all()
    for row in rows:
        snapshot = dict(row.context_snapshot or {})
        snapshot["long_term_memory"] = projection
        row.context_snapshot = snapshot
        row.lock_version += 1
        row.updated_at = _now()
    return len(rows)


def list_memories(
    session: Any, *, owner_public_id: str, include_withdrawn: bool = False,
) -> list[dict[str, Any]]:
    query = session.query(DBMemoryItem).filter_by(owner_public_id=owner_public_id)
    if not include_withdrawn:
        query = query.filter_by(status="active")
    return [memory_payload(row) for row in query.order_by(DBMemoryItem.updated_at.desc(), DBMemoryItem.id).all()]


def create_memory(
    session: Any, *, owner_public_id: str, title: str, memory_type: str,
    content: str, sensitivity: str = "personal",
) -> DBMemoryItem:
    title = title.strip()
    content = content.strip()
    if not title or not content:
        _fail("memory_content_required", "title and content are required")
    if memory_type not in ALLOWED_MEMORY_TYPES:
        _fail("memory_type_invalid", "unsupported memory type")
    row = DBMemoryItem(
        owner_public_id=owner_public_id,
        memory_key=f"manual:{uuid.uuid4().hex}",
        title=title,
        memory_type=memory_type,
        content=content,
        source_type="manual",
        source_id=owner_public_id,
        confidence=1.0,
        sensitivity=sensitivity,
    )
    session.add(row)
    session.flush()
    affected = refresh_tutor_contexts(session, owner_public_id=owner_public_id)
    record_audit(
        session, actor_public_id=owner_public_id, action="memory.created",
        object_type="memory_item", object_id=row.id,
        metadata={"memory_type": memory_type, "content_hash": _content_hash(content), "contexts_refreshed": affected},
    )
    return row


def update_memory(
    session: Any, *, owner_public_id: str, memory_id: str, expected_version: int,
    title: str | None = None, content: str | None = None,
) -> DBMemoryItem:
    row = _owned_memory(session, owner_public_id=owner_public_id, memory_id=memory_id)
    if row.status != "active":
        _fail("memory_not_active", "withdrawn memory cannot be updated")
    if row.lock_version != expected_version:
        _fail("memory_version_conflict", "memory version changed")
    if row.source_type == "profile":
        _fail("memory_profile_managed", "profile-derived memory must be updated from the profile")
    if title is not None:
        if not title.strip():
            _fail("memory_content_required", "title cannot be empty")
        row.title = title.strip()
    if content is not None:
        if not content.strip():
            _fail("memory_content_required", "content cannot be empty")
        row.content = content.strip()
    row.lock_version += 1
    row.updated_at = _now()
    session.flush()
    affected = refresh_tutor_contexts(session, owner_public_id=owner_public_id)
    record_audit(
        session, actor_public_id=owner_public_id, action="memory.updated",
        object_type="memory_item", object_id=row.id,
        metadata={"version": row.lock_version, "content_hash": _content_hash(row.content), "contexts_refreshed": affected},
    )
    return row


def withdraw_memory(
    session: Any, *, owner_public_id: str, memory_id: str,
    expected_version: int, reason: str,
) -> DBMemoryItem:
    row = _owned_memory(session, owner_public_id=owner_public_id, memory_id=memory_id)
    if row.lock_version != expected_version:
        _fail("memory_version_conflict", "memory version changed")
    if row.status == "withdrawn":
        return row
    row.status = "withdrawn"
    row.withdrawn_at = _now()
    row.withdrawal_reason = reason.strip() or "user_withdrawn"
    row.lock_version += 1
    session.flush()
    affected = refresh_tutor_contexts(session, owner_public_id=owner_public_id)
    record_audit(
        session, actor_public_id=owner_public_id, action="memory.withdrawn",
        object_type="memory_item", object_id=row.id,
        metadata={
            "reason_hash": _content_hash(row.withdrawal_reason),
            "reason_provided": bool(reason.strip()),
            "version": row.lock_version,
            "contexts_refreshed": affected,
        },
    )
    return row


def _sync_profile_memories(
    session: Any, *, owner_public_id: str, username: str,
    subscription: DBMemorySubscription,
) -> int:
    profile = session.query(DBStudentProfile).filter_by(student_id=username).first()
    selected = set(subscription.profile_fields or [])
    changed = 0
    for field in sorted(PROFILE_FIELD_TYPES):
        key = f"profile:{field}"
        row = session.query(DBMemoryItem).filter_by(
            owner_public_id=owner_public_id, memory_key=key,
        ).first()
        if field not in selected:
            if row is not None and row.status == "active":
                row.status = "withdrawn"
                row.withdrawn_at = _now()
                row.withdrawal_reason = "profile_subscription_removed"
                row.lock_version += 1
                changed += 1
            continue
        value = getattr(profile, field, None) if profile is not None else None
        content = _content(value)
        if not content or content in {"[]", "{}", "null"}:
            if row is not None and row.status == "active":
                row.status = "withdrawn"
                row.withdrawn_at = _now()
                row.withdrawal_reason = "profile_value_empty"
                row.lock_version += 1
                changed += 1
            continue
        if row is None:
            row = DBMemoryItem(
                owner_public_id=owner_public_id,
                memory_key=key,
                title=field.replace("_", " "),
                memory_type=PROFILE_FIELD_TYPES[field],
                content=content,
                source_type="profile",
                source_id=f"{username}:{field}",
                confidence=1.0,
                sensitivity="personal",
            )
            session.add(row)
            changed += 1
        elif row.content != content or row.status != "active":
            row.content = content
            row.status = "active"
            row.withdrawn_at = None
            row.withdrawal_reason = ""
            row.lock_version += 1
            row.updated_at = _now()
            changed += 1
    subscription.last_synced_at = _now()
    session.flush()
    affected = refresh_tutor_contexts(session, owner_public_id=owner_public_id)
    record_audit(
        session, actor_public_id=owner_public_id, action="memory.profile_synced",
        object_type="memory_subscription", object_id=subscription.id,
        metadata={"fields": sorted(selected), "changed": changed, "contexts_refreshed": affected},
    )
    return changed


def upsert_profile_subscription(
    session: Any, *, owner_public_id: str, username: str,
    profile_fields: list[str], expected_version: int | None = None,
) -> tuple[DBMemorySubscription, int]:
    fields = sorted(set(profile_fields))
    invalid = sorted(set(fields) - set(PROFILE_FIELD_TYPES))
    if invalid:
        _fail("memory_profile_field_invalid", f"unsupported profile fields: {', '.join(invalid)}")
    row = session.query(DBMemorySubscription).filter_by(
        owner_public_id=owner_public_id, subscriber_type="tutor", subscriber_key="profile",
    ).first()
    if row is None:
        if expected_version not in {None, 0}:
            _fail("memory_subscription_version_conflict", "subscription does not exist")
        row = DBMemorySubscription(
            owner_public_id=owner_public_id,
            subscriber_type="tutor",
            subscriber_key="profile",
            profile_fields=fields,
            memory_types=sorted({PROFILE_FIELD_TYPES[field] for field in fields}),
        )
        session.add(row)
        session.flush()
    else:
        if expected_version is not None and row.lock_version != expected_version:
            _fail("memory_subscription_version_conflict", "subscription version changed")
        row.profile_fields = fields
        row.memory_types = sorted({PROFILE_FIELD_TYPES[field] for field in fields})
        row.status = "active"
        row.revoked_at = None
        row.revoke_reason = ""
        row.lock_version += 1
    changed = _sync_profile_memories(
        session, owner_public_id=owner_public_id, username=username, subscription=row,
    )
    record_audit(
        session, actor_public_id=owner_public_id, action="memory.subscription_updated",
        object_type="memory_subscription", object_id=row.id,
        metadata={"fields": fields, "version": row.lock_version},
    )
    return row, changed


def sync_profile_subscription_for_owner(
    session: Any, *, owner_public_id: str, username: str,
) -> int:
    row = session.query(DBMemorySubscription).filter_by(
        owner_public_id=owner_public_id, subscriber_type="tutor",
        subscriber_key="profile", status="active",
    ).first()
    if row is None:
        return 0
    changed = _sync_profile_memories(
        session, owner_public_id=owner_public_id, username=username, subscription=row,
    )
    session.commit()
    return changed


def sync_profile_subscriptions_for_student(session: Any, *, username: str) -> int:
    """Refresh the student's own subscription after a legacy profile write."""
    user = session.query(DBUser).filter_by(username=username).first()
    if user is None:
        return 0
    return sync_profile_subscription_for_owner(
        session, owner_public_id=user.public_id, username=username,
    )


def revoke_profile_subscription(
    session: Any, *, owner_public_id: str, expected_version: int, reason: str,
) -> DBMemorySubscription:
    row = session.query(DBMemorySubscription).filter_by(
        owner_public_id=owner_public_id, subscriber_type="tutor", subscriber_key="profile",
    ).first()
    if row is None:
        _fail("memory_subscription_unknown", "profile subscription does not exist")
    if row.lock_version != expected_version:
        _fail("memory_subscription_version_conflict", "subscription version changed")
    if row.status != "revoked":
        row.status = "revoked"
        row.revoked_at = _now()
        row.revoke_reason = reason.strip() or "user_revoked"
        row.lock_version += 1
        rows = session.query(DBMemoryItem).filter_by(
            owner_public_id=owner_public_id, source_type="profile", status="active",
        ).all()
        for memory in rows:
            memory.status = "withdrawn"
            memory.withdrawn_at = _now()
            memory.withdrawal_reason = "profile_subscription_revoked"
            memory.lock_version += 1
        session.flush()
        affected = refresh_tutor_contexts(session, owner_public_id=owner_public_id)
        record_audit(
            session, actor_public_id=owner_public_id, action="memory.subscription_revoked",
            object_type="memory_subscription", object_id=row.id,
            metadata={
                "reason_hash": _content_hash(row.revoke_reason),
                "reason_provided": bool(reason.strip()),
                "memories_withdrawn": len(rows),
                "contexts_refreshed": affected,
            },
        )
    return row


def list_subscriptions(session: Any, *, owner_public_id: str) -> list[dict[str, Any]]:
    rows = session.query(DBMemorySubscription).filter_by(
        owner_public_id=owner_public_id,
    ).order_by(DBMemorySubscription.created_at).all()
    return [subscription_payload(row) for row in rows]


def list_memory_audit(session: Any, *, owner_public_id: str, limit: int = 50) -> list[dict[str, Any]]:
    rows = session.query(DBAuditLog).filter(
        DBAuditLog.actor_public_id == owner_public_id,
        DBAuditLog.action.like("memory.%"),
    ).order_by(DBAuditLog.created_at.desc()).limit(max(1, min(limit, 100))).all()
    return [
        {
            "id": row.id,
            "action": row.action,
            "object_type": row.object_type,
            "object_id": row.object_id,
            "outcome": row.outcome,
            "metadata": row.metadata_json or {},
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]
