"""Server-authoritative post-login destinations for supported EduMatrix roles."""

from __future__ import annotations

from typing import Any

from app.database import DBCourse, DBCourseMembership
from app.identity import VALID_ROLES, normalize_role
from course_catalog import course_is_selectable


def resolve_login_landing(db: Any, user: Any) -> str | None:
    try:
        role = normalize_role(user.role)
    except ValueError:
        return None
    if role not in VALID_ROLES:
        return None
    if role == "admin":
        return "/admin/system"
    if role == "teacher":
        return "/teacher/overview"
    memberships = db.query(DBCourseMembership).filter_by(
        user_public_id=user.public_id,
        role="student",
        status="active",
    ).all()
    return "/" if any(
        course_is_selectable(db, db.get(DBCourse, membership.course_id))
        for membership in memberships
    ) else None
