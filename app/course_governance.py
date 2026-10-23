"""Canonical class, group, teaching-task, and course-withdrawal governance."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.database import (
    DBAuditLog, DBCourse, DBCourseMembership, DBCourseWithdrawal, DBTeachingClass,
    DBTeachingClassMember, DBTeachingGroup, DBTeachingTask, DBUser,
)
from app.identity import new_public_id, normalize_role


class CourseGovernanceError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message); self.code = code


def _fail(code: str, message: str) -> None: raise CourseGovernanceError(code, message)
def _now() -> datetime: return datetime.now(timezone.utc).replace(tzinfo=None)
def _hash(value: str) -> str: return hashlib.sha256(value.encode("utf-8")).hexdigest()
def _stable(prefix: str, *parts: str) -> str: return f"{prefix}-{hashlib.sha256(chr(31).join(parts).encode()).hexdigest()[:32]}"


def _audit(db: Any, *, actor: str, action: str, object_type: str, object_id: str, metadata: dict[str, Any]) -> None:
    db.add(DBAuditLog(actor_public_id=actor, action=action, object_type=object_type, object_id=object_id,
                      trace_id=new_public_id("trace"), outcome="success", metadata_json=metadata))


def _course(db: Any, course_id: str) -> DBCourse:
    row = db.get(DBCourse, course_id)
    if row is None: _fail("governance_course_unknown", "course does not exist")
    return row


def _course_role(db: Any, course_id: str, actor: DBUser) -> str | None:
    if normalize_role(actor.role) == "admin": return "admin"
    course = _course(db, course_id)
    if course.owner_public_id == actor.public_id: return "owner"
    membership = db.query(DBCourseMembership).filter_by(course_id=course_id, user_public_id=actor.public_id, status="active").first()
    return membership.role if membership else None


def require_manager(db: Any, course_id: str, actor: DBUser) -> str:
    role = _course_role(db, course_id, actor)
    if role not in {"admin", "owner", "teacher", "assistant"}:
        _fail("governance_forbidden", "course management requires an active teacher role")
    return role


def _class(db: Any, class_id: str) -> DBTeachingClass:
    row = db.get(DBTeachingClass, class_id)
    if row is None: _fail("governance_class_unknown", "teaching class does not exist")
    return row


def _member(db: Any, class_id: str, user_id: str) -> DBTeachingClassMember | None:
    return db.query(DBTeachingClassMember).filter_by(class_id=class_id, user_public_id=user_id).first()


def require_class_read(db: Any, row: DBTeachingClass, actor: DBUser) -> None:
    if _course_role(db, row.course_id, actor) in {"admin", "owner", "teacher", "assistant"}: return
    member = _member(db, row.id, actor.public_id)
    if member is None or member.status != "active": _fail("governance_forbidden", "class is not visible to this user")


def _user_payload(user: DBUser) -> dict[str, str]:
    return {"public_id": user.public_id, "username": user.username, "display_name": user.display_name, "role": user.role}


def class_payload(db: Any, row: DBTeachingClass, actor: DBUser) -> dict[str, Any]:
    require_class_read(db, row, actor)
    groups = db.query(DBTeachingGroup).filter_by(class_id=row.id).order_by(DBTeachingGroup.created_at).all()
    members = db.query(DBTeachingClassMember).filter_by(class_id=row.id).order_by(DBTeachingClassMember.joined_at).all()
    tasks = db.query(DBTeachingTask).filter_by(class_id=row.id).order_by(DBTeachingTask.created_at.desc()).all()
    users = {item.public_id: item for item in db.query(DBUser).filter(DBUser.public_id.in_([m.user_public_id for m in members] or [""])).all()}
    management = _course_role(db, row.course_id, actor) in {"admin", "owner", "teacher", "assistant"}
    if not management:
        own = _member(db, row.id, actor.public_id)
        members = [own] if own else []
        tasks = [item for item in tasks if item.status == "published" and (item.group_id is None or item.group_id == own.group_id)]
    return {
        "schema_version": "next.course-governance-class.v1", "id": row.id, "course_id": row.course_id,
        "title": row.title, "term": row.term, "owner_public_id": row.owner_public_id, "status": row.status,
        "lock_version": row.lock_version, "can_manage": management,
        "groups": [{"id": g.id, "name": g.name, "description": g.description, "status": g.status, "lock_version": g.lock_version} for g in groups],
        "members": [{"id": m.id, "role": m.role, "status": m.status, "group_id": m.group_id,
                     "lock_version": m.lock_version, "user": _user_payload(users[m.user_public_id])} for m in members],
        "tasks": [{"id": t.id, "title": t.title, "instructions": t.instructions, "group_id": t.group_id,
                   "status": t.status, "lock_version": t.lock_version, "due_at": t.due_at.isoformat() if t.due_at else None,
                   "published_at": t.published_at.isoformat() if t.published_at else None,
                   "withdrawn_at": t.withdrawn_at.isoformat() if t.withdrawn_at else None} for t in tasks],
    }


def list_classes(db: Any, actor: DBUser, course_id: str | None = None) -> list[dict[str, Any]]:
    if course_id:
        course = _course(db, course_id)
        from course_catalog import course_is_selectable
        if not course_is_selectable(db, course):
            _fail("governance_course_unavailable", "course is not currently available for selection")
    query = db.query(DBTeachingClass)
    if course_id: query = query.filter_by(course_id=course_id)
    rows = query.order_by(DBTeachingClass.created_at.desc()).all()
    visible = []
    for row in rows:
        try: visible.append(class_payload(db, row, actor))
        except CourseGovernanceError as exc:
            if exc.code != "governance_forbidden": raise
    return visible


def governance_catalog(db: Any, actor: DBUser) -> dict[str, Any]:
    from course_catalog import course_is_selectable
    role = normalize_role(actor.role)
    courses = [
        item for item in db.query(DBCourse).order_by(DBCourse.title).all()
        if course_is_selectable(db, item)
    ]
    if role != "admin":
        courses = [item for item in courses if _course_role(db, item.id, actor) in {"owner", "teacher", "assistant"}]
    if role not in {"admin", "teacher", "assistant"} and not courses:
        _fail("governance_forbidden", "governance catalog requires a teaching role")
    user_query = db.query(DBUser).filter_by(is_active=True)
    if role != "admin":
        course_ids = [item.id for item in courses]
        member_ids = [item[0] for item in db.query(DBCourseMembership.user_public_id).filter(
            DBCourseMembership.course_id.in_(course_ids or [""]), DBCourseMembership.status == "active",
        ).distinct().all()]
        user_query = user_query.filter(DBUser.public_id.in_(member_ids or [""]))
    users = user_query.order_by(DBUser.display_name, DBUser.username).all()
    return {
        "schema_version": "next.course-governance-catalog.v1",
        "courses": [{"id": item.id, "title": item.title, "version": item.version, "status": item.status,
                     "visibility": item.visibility} for item in courses],
        "candidate_members": [_user_payload(item) for item in users if normalize_role(item.role) in {"student", "teacher", "assistant"}],
    }


def create_class(db: Any, *, actor: DBUser, course_id: str, title: str, term: str) -> dict[str, Any]:
    course = _course(db, course_id); require_manager(db, course_id, actor)
    from course_catalog import course_is_selectable
    if not course_is_selectable(db, course): _fail("governance_course_unavailable", "course is not currently available for selection")
    existing = db.query(DBTeachingClass).filter_by(course_id=course_id, title=title.strip(), term=term.strip()).first()
    if existing: return class_payload(db, existing, actor)
    row = DBTeachingClass(course_id=course_id, title=title.strip(), term=term.strip(), owner_public_id=actor.public_id)
    db.add(row); db.flush()
    _audit(db, actor=actor.public_id, action="teaching_class.created", object_type="teaching_class", object_id=row.id,
           metadata={"course_id": course_id, "term": term.strip(), "title_sha256": _hash(title.strip())})
    return class_payload(db, row, actor)


def create_group(db: Any, *, actor: DBUser, class_id: str, name: str, description: str) -> dict[str, Any]:
    classroom = _class(db, class_id); require_manager(db, classroom.course_id, actor)
    if classroom.status != "active": _fail("governance_class_inactive", "group requires an active class")
    existing = db.query(DBTeachingGroup).filter_by(class_id=class_id, name=name.strip()).first()
    if existing: return class_payload(db, classroom, actor)
    row = DBTeachingGroup(class_id=class_id, name=name.strip(), description=description.strip())
    db.add(row); db.flush()
    _audit(db, actor=actor.public_id, action="teaching_group.created", object_type="teaching_group", object_id=row.id,
           metadata={"class_id": class_id, "name_sha256": _hash(name.strip())})
    return class_payload(db, classroom, actor)


def upsert_member(db: Any, *, actor: DBUser, class_id: str, user_public_id: str, role: str,
                  group_id: str | None, expected_version: int | None) -> dict[str, Any]:
    classroom = _class(db, class_id); require_manager(db, classroom.course_id, actor)
    user = db.query(DBUser).filter_by(public_id=user_public_id).first()
    if user is None: _fail("governance_user_unknown", "user does not exist")
    if group_id:
        group = db.get(DBTeachingGroup, group_id)
        if group is None or group.class_id != class_id: _fail("governance_group_scope_invalid", "group does not belong to the class")
    row = _member(db, class_id, user_public_id)
    if row:
        if expected_version is None or row.lock_version != expected_version: _fail("governance_version_conflict", "class member has changed")
        row.role, row.group_id, row.status, row.lock_version = role, group_id, "active", row.lock_version + 1
    else:
        if expected_version is not None: _fail("governance_version_conflict", "new member must not provide a version")
        row = DBTeachingClassMember(class_id=class_id, user_public_id=user_public_id, role=role, group_id=group_id)
        db.add(row)
    membership = db.query(DBCourseMembership).filter_by(course_id=classroom.course_id, user_public_id=user_public_id).first()
    course_role = role if role in {"teacher", "assistant"} else "student"
    if membership is None: db.add(DBCourseMembership(course_id=classroom.course_id, user_public_id=user_public_id, role=course_role, status="active"))
    else: membership.role, membership.status = course_role, "active"
    db.flush()
    _audit(db, actor=actor.public_id, action="teaching_member.upserted", object_type="teaching_class_member", object_id=row.id,
           metadata={"class_id": class_id, "role": role, "group_id": group_id or "", "lock_version": row.lock_version})
    return class_payload(db, classroom, actor)


def create_task(db: Any, *, actor: DBUser, class_id: str, group_id: str | None, title: str,
                instructions: str, due_at: datetime | None, idempotency_key: str) -> dict[str, Any]:
    classroom = _class(db, class_id); require_manager(db, classroom.course_id, actor)
    if classroom.status != "active": _fail("governance_class_inactive", "task requires an active class")
    if group_id:
        group = db.get(DBTeachingGroup, group_id)
        if group is None or group.class_id != class_id: _fail("governance_group_scope_invalid", "group does not belong to the class")
    existing = db.query(DBTeachingTask).filter_by(class_id=class_id, idempotency_key=idempotency_key).first()
    request_hash = _hash(json.dumps({"group": group_id, "title": title.strip(), "instructions": instructions.strip(),
                                     "due": due_at.isoformat() if due_at else None}, sort_keys=True, ensure_ascii=False))
    if existing:
        existing_hash = _hash(json.dumps({"group": existing.group_id, "title": existing.title,
                                           "instructions": existing.instructions,
                                           "due": existing.due_at.isoformat() if existing.due_at else None},
                                          sort_keys=True, ensure_ascii=False))
        if existing_hash != request_hash:
            _fail("governance_idempotency_conflict", "idempotency key is bound to another teaching task")
        return class_payload(db, classroom, actor)
    row = DBTeachingTask(class_id=class_id, group_id=group_id, title=title.strip(), instructions=instructions.strip(),
                         due_at=due_at, idempotency_key=idempotency_key, created_by_public_id=actor.public_id)
    db.add(row); db.flush()
    _audit(db, actor=actor.public_id, action="teaching_task.created", object_type="teaching_task", object_id=row.id,
           metadata={"class_id": class_id, "group_id": group_id or "", "request_sha256": request_hash})
    return class_payload(db, classroom, actor)


def publish_task(db: Any, *, actor: DBUser, task_id: str, expected_version: int) -> dict[str, Any]:
    task = db.get(DBTeachingTask, task_id)
    if task is None: _fail("governance_task_unknown", "teaching task does not exist")
    classroom = _class(db, task.class_id); require_manager(db, classroom.course_id, actor)
    if task.lock_version != expected_version: _fail("governance_version_conflict", "teaching task has changed")
    if task.status != "draft": _fail("governance_task_transition_invalid", "only draft tasks can be published")
    task.status, task.published_at, task.lock_version = "published", _now(), task.lock_version + 1
    db.flush(); _audit(db, actor=actor.public_id, action="teaching_task.published", object_type="teaching_task", object_id=task.id,
                      metadata={"class_id": classroom.id, "lock_version": task.lock_version})
    return class_payload(db, classroom, actor)


def withdraw_course(db: Any, *, actor: DBUser, course_id: str, reason: str, expected_status: str) -> dict[str, Any]:
    course = _course(db, course_id); require_manager(db, course_id, actor)
    existing = db.query(DBCourseWithdrawal).filter_by(course_id=course_id).first()
    if existing: return withdrawal_payload(existing)
    if course.status != expected_status or course.status == "withdrawn": _fail("governance_course_status_conflict", "course status has changed")
    classes = db.query(DBTeachingClass).filter_by(course_id=course_id).all()
    class_ids = [item.id for item in classes]
    members = db.query(DBTeachingClassMember).filter(DBTeachingClassMember.class_id.in_(class_ids or [""]), DBTeachingClassMember.status == "active").all()
    tasks = db.query(DBTeachingTask).filter(DBTeachingTask.class_id.in_(class_ids or [""]), DBTeachingTask.status.in_(["draft", "published"])).all()
    memberships = db.query(DBCourseMembership).filter_by(course_id=course_id, status="active").all()
    learner_memberships = [item for item in memberships if item.role in {"student", "visitor"}]
    impact = {"class_ids": class_ids, "class_count": len(classes), "class_member_count": len(members),
              "course_membership_count": len(memberships),
              "learner_membership_suspended_count": len(learner_memberships),
              "manager_membership_preserved_count": len(memberships) - len(learner_memberships),
              "task_ids": [item.id for item in tasks], "task_count": len(tasks),
              "historical_learning_evidence_deleted": 0}
    row = DBCourseWithdrawal(course_id=course_id, previous_status=course.status, reason=reason.strip(),
                             reason_sha256=_hash(reason.strip()), impact_snapshot=impact, actor_public_id=actor.public_id)
    db.add(row); db.flush(); course.status = "withdrawn"
    for item in classes: item.status, item.lock_version = "withdrawn", item.lock_version + 1
    for item in members: item.status, item.lock_version = "suspended", item.lock_version + 1
    for item in learner_memberships: item.status = "suspended"
    now = _now()
    for item in tasks: item.status, item.withdrawn_at, item.lock_version = "withdrawn", now, item.lock_version + 1
    db.flush(); _audit(db, actor=actor.public_id, action="course.withdrawn", object_type="course", object_id=course_id,
                      metadata={"reason_sha256": row.reason_sha256, **{key: value for key, value in impact.items() if not key.endswith("_ids")}})
    return withdrawal_payload(row)


def withdrawal_payload(row: DBCourseWithdrawal) -> dict[str, Any]:
    return {"schema_version": "next.course-withdrawal.v1", "id": row.id, "course_id": row.course_id,
            "previous_status": row.previous_status, "status": "withdrawn", "reason": row.reason,
            "reason_sha256": row.reason_sha256, "impact_snapshot": row.impact_snapshot,
            "actor_public_id": row.actor_public_id, "created_at": row.created_at.isoformat() if row.created_at else None}
