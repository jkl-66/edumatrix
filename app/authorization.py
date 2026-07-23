"""M1 object-level authorization primitives.

Routes can use these helpers instead of implementing ad-hoc username checks.
The policy is intentionally small and explicit so it can be extended when
organization and course objects gain their full lifecycle in later M1 tasks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status

from app.identity import ROLE_ADMIN, ROLE_ASSISTANT, ROLE_TEACHER, ROLE_VISITOR
from app.database import DBCourseMembership


@dataclass(frozen=True)
class ObjectAccess:
    object_type: str
    object_id: str
    owner_public_id: str | None = None
    course_id: str | None = None
    visibility: str = "private"


def can_access_object(
    user: Any,
    obj: ObjectAccess,
    *,
    action: str = "read",
    course_role: str | None = None,
) -> bool:
    """Return whether the authenticated user may perform an object action."""
    role = str(getattr(user, "role", "student") or "student").lower()
    public_id = str(getattr(user, "public_id", "") or "")

    if action == "read" and obj.visibility == "public":
        return True
    if role == ROLE_ADMIN:
        return True
    if obj.owner_public_id and obj.owner_public_id == public_id:
        return True
    if course_role in {ROLE_ADMIN, ROLE_TEACHER, ROLE_ASSISTANT}:
        return action in {"read", "create", "update", "review"}
    if course_role == "student":
        return action in {"read", "create"} and obj.object_type in {
            "course",
            "course_document",
            "artifact",
            "learning_path",
            "assessment",
        }
    if role == ROLE_VISITOR:
        return action == "read" and obj.visibility == "public"
    return False


def require_object_access(
    user: Any,
    obj: ObjectAccess,
    *,
    action: str = "read",
    course_role: str | None = None,
) -> None:
    if not can_access_object(user, obj, action=action, course_role=course_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"无权对{obj.object_type}执行{action}操作",
        )


def active_course_role(session: Any, *, course_id: str, user_public_id: str) -> str | None:
    """Resolve course authority from persisted membership, never request data."""
    membership = (
        session.query(DBCourseMembership)
        .filter(
            DBCourseMembership.course_id == course_id,
            DBCourseMembership.user_public_id == user_public_id,
            DBCourseMembership.status == "active",
        )
        .first()
    )
    return str(membership.role) if membership else None


def require_course_access(
    session: Any,
    user: Any,
    *,
    course_id: str,
    action: str = "read",
    visibility: str = "private",
) -> str | None:
    course_role = active_course_role(
        session, course_id=course_id, user_public_id=str(user.public_id)
    )
    require_object_access(
        user,
        ObjectAccess(
            object_type="course",
            object_id=course_id,
            course_id=course_id,
            visibility=visibility,
        ),
        action=action,
        course_role=course_role,
    )
    return course_role
