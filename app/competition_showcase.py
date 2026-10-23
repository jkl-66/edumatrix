"""Thin orchestration for one discoverable, truthful FC5 demonstration context."""
from __future__ import annotations

import hashlib
from typing import Any

from fastapi import HTTPException

from app.auth import get_password_hash
from app.database import (
    DBCourse, DBCourseMembership, DBMarketplaceListing, DBOrganization,
    DBOrganizationMembership, DBStudentProfile, DBTrainingAssignment, DBUser,
)
from app.identity import normalize_role
from app.m6_enterprise import bootstrap_competition_training_demo
from app.marketplace import submit_listing


COURSE_ID = "course-rag-engineering-m0"
DEMO_PASSWORD = "EduMatrix-FC-Demo"
SHOWCASE_VERSION = "fc5.showcase-context.v1"
JOURNEYS = (
    ("student", "学生黄金旅程", "/judge-journey/student", "admin"),
    ("media", "多媒体创作旅程", "/judge-journey/media", "admin"),
    ("teacher", "教师教学旅程", "/judge-journey/teacher", "admin"),
    ("enterprise", "企业培训旅程", "/judge-journey/enterprise", "admin"),
    ("marketplace", "生态市场旅程", "/judge-journey/marketplace", "admin"),
    ("integration", "本地集成旅程", "/judge-journey/integration", "admin"),
)


def _stable_username(role: str, actor: DBUser) -> str:
    digest = hashlib.sha256(actor.public_id.encode("utf-8")).hexdigest()[:10]
    return f"fc_demo_{role}_{digest}"


def _require_admin(actor: DBUser) -> None:
    if normalize_role(actor.role) != "admin":
        raise HTTPException(status_code=403, detail="只有管理员可管理比赛统一演示上下文")


def _membership(db: Any, course_id: str, user: DBUser, role: str) -> DBCourseMembership:
    row = db.query(DBCourseMembership).filter_by(course_id=course_id, user_public_id=user.public_id).first()
    if row is None:
        row = DBCourseMembership(course_id=course_id, user_public_id=user.public_id, role=role, status="active")
        db.add(row)
    else:
        row.role, row.status = role, "active"
    return row


def _role_payload(user: DBUser, label: str, *, include_password: bool = False) -> dict[str, Any]:
    result = {"public_id": user.public_id, "username": user.username, "display_name": user.display_name, "role": normalize_role(user.role), "label": label, "synthetic": True}
    if include_password:
        result["local_demo_password"] = DEMO_PASSWORD
    return result


def showcase_workspace(db: Any, *, actor: DBUser, include_passwords: bool = False) -> dict[str, Any]:
    _require_admin(actor)
    course = db.get(DBCourse, COURSE_ID)
    teacher = db.query(DBUser).filter_by(username=_stable_username("teacher", actor)).first()
    learner = db.query(DBUser).filter_by(username=_stable_username("learner", actor)).first()
    memberships = db.query(DBOrganizationMembership).filter_by(user_public_id=actor.public_id, status="active").all()
    organization = None
    assignment = None
    for member in memberships:
        candidate = db.get(DBOrganization, member.organization_id)
        if candidate and candidate.name.startswith("EduMatrix RAG 工程能力中心") and member.role in {"admin", "manager"}:
            organization = candidate
            assignment = db.query(DBTrainingAssignment).filter_by(organization_id=candidate.id).order_by(DBTrainingAssignment.assigned_at).first()
            if assignment:
                learner = db.query(DBUser).filter_by(public_id=assignment.learner_public_id).first() or learner
                break
    listing = None
    if course:
        listing = db.query(DBMarketplaceListing).filter_by(course_id=course.id, course_version=course.version).order_by(DBMarketplaceListing.created_at.desc()).first()
    context_ready = bool(course and teacher and learner and organization and assignment)
    marketplace_ready = bool(listing and listing.status in {"pending", "approved", "published"} and learner and listing.owner_public_id != learner.public_id)
    readiness = {
        "student": bool(course), "media": bool(course), "teacher": bool(course),
        "enterprise": bool(organization and assignment), "marketplace": marketplace_ready,
        "integration": bool(organization and assignment),
    }
    return {
        "schema_version": SHOWCASE_VERSION,
        "initialized": context_ready and marketplace_ready,
        "truthfulness": {
            "data_label": "冻结合成比赛演示数据",
            "environment": "local_demo",
            "external_network_required": False,
            "claim_boundary": "不代表真实学校、企业、专家认证、协议认证或第三方审计。",
        },
        "roles": {
            "administrator": {"public_id": actor.public_id, "username": actor.username, "display_name": actor.display_name or actor.username, "role": "admin", "label": "当前演示管理员", "synthetic": False},
            "teacher": _role_payload(teacher, "合成演示教师", include_password=include_passwords) if teacher else None,
            "learner": _role_payload(learner, "合成转岗学员", include_password=include_passwords) if learner else None,
        },
        "context": {
            "course": {"id": course.id, "title": course.title, "version": course.version, "manifest_version": course.manifest_version} if course else None,
            "organization": {"id": organization.id, "name": organization.name} if organization else None,
            "assignment_id": assignment.id if assignment else None,
            "marketplace_listing": {"id": listing.id, "title": listing.title, "status": listing.status, "snapshot_hash": listing.snapshot_hash, "owner_public_id": listing.owner_public_id} if listing else None,
        },
        "journeys": [{"key": key, "label": label, "route": route, "required_role": role, "ready": readiness[key]} for key, label, route, role in JOURNEYS],
        "ready_count": sum(readiness.values()),
        "total_count": len(readiness),
    }


def initialize_showcase(db: Any, *, actor: DBUser) -> dict[str, Any]:
    _require_admin(actor)
    course = db.get(DBCourse, COURSE_ID)
    if course is None or course.status != "published":
        raise HTTPException(status_code=409, detail="统一演示课程尚未由正式课程目录完成发布，请先完成应用启动")
    teacher_name = _stable_username("teacher", actor)
    teacher = db.query(DBUser).filter_by(username=teacher_name).first()
    if teacher is None:
        teacher = DBUser(username=teacher_name, display_name="演示教师 周岚", hashed_password=get_password_hash(DEMO_PASSWORD), role="teacher")
        db.add(teacher); db.flush()
    enterprise = bootstrap_competition_training_demo(db, actor=actor)
    learner = db.query(DBUser).filter_by(public_id=enterprise["learner_public_id"]).first()
    if learner is None:
        raise HTTPException(status_code=409, detail="企业演示学员初始化失败")
    # Keep the existing actor-derived username because legacy profile rows use it as a foreign key.
    learner.display_name = "转岗学员 林然"
    learner.hashed_password = get_password_hash(DEMO_PASSWORD)
    learner.role = "student"
    _membership(db, course.id, actor, "admin")
    _membership(db, course.id, teacher, "teacher")
    _membership(db, course.id, learner, "student")
    db.flush()
    profile = db.query(DBStudentProfile).filter_by(student_id=learner.username).first()
    if profile is None:
        profile = DBStudentProfile(student_id=learner.username)
        db.add(profile)
    profile.target_course = course.title
    listing = submit_listing(db, actor=teacher, course_id=course.id, title="RAG 工程可信训练演示课程", summary="来源、许可、版本和学习证据可追溯的冻结合成比赛演示课程。", category="人工智能", tags=["RAG", "可信训练", "合成演示"])
    db.commit()
    result = showcase_workspace(db, actor=actor, include_passwords=True)
    result["bootstrap_status"] = enterprise["status"]
    result["listing_id"] = listing["id"]
    return result
