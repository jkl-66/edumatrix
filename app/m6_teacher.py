"""Teacher intervention workflow backed by canonical plans and learning events."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.audit_log import record_backend_audit
from app.authorization import ObjectAccess, active_course_role, require_object_access
from app.database import (
    DBAuditLog,
    DBChapter,
    DBCourse,
    DBCourseMembership,
    DBLearningEvent,
    DBLearningPath,
    DBPathNode,
    DBPlanDraft,
    DBPlanVersion,
    DBStudentProfile,
    DBUser,
)
from app.m5_learning import (
    LearningEventInput,
    PlanNodeSpec,
    PlanSpec,
    confirm_plan,
    create_plan_draft,
    process_path_event,
    record_learning_event,
)


def _require_teacher(session: Any, *, course_id: str, actor: DBUser) -> None:
    course = session.query(DBCourse).filter_by(id=course_id).first()
    if course is None:
        raise HTTPException(status_code=404, detail="课程不存在")
    from course_catalog import course_is_selectable
    if not course_is_selectable(session, course):
        raise HTTPException(status_code=409, detail="课程已停止发布或没有可用学习资料")
    role = active_course_role(session, course_id=course_id, user_public_id=actor.public_id)
    require_object_access(
        actor,
        ObjectAccess(object_type="course", object_id=course.id, course_id=course.id),
        action="review",
        course_role=role,
    )


def _student_member(session: Any, *, course_id: str, learner_public_id: str) -> tuple[DBCourseMembership, DBUser]:
    membership = session.query(DBCourseMembership).filter_by(
        course_id=course_id, user_public_id=learner_public_id,
        role="student", status="active",
    ).first()
    learner = session.query(DBUser).filter_by(public_id=learner_public_id).first()
    if membership is None or learner is None:
        raise HTTPException(status_code=404, detail="目标学员不在当前课程")
    return membership, learner


def publish_teacher_intervention(
    session: Any,
    *,
    actor: DBUser,
    course_id: str,
    learner_public_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    _require_teacher(session, course_id=course_id, actor=actor)
    _, learner = _student_member(
        session, course_id=course_id, learner_public_id=learner_public_id
    )
    profile = session.query(DBStudentProfile).filter_by(student_id=learner.username).first()
    mastery = dict(profile.concept_mastery or {}) if profile else {}
    if not mastery:
        raise HTTPException(status_code=409, detail="缺少可解释的学员掌握度证据")
    concept, score = min(mastery.items(), key=lambda item: float(item[1]))
    chapter = session.query(DBChapter).filter_by(course_id=course_id).order_by(DBChapter.position).first()
    if chapter is None:
        raise HTTPException(status_code=409, detail="课程没有可分配的正式章节")
    spec = PlanSpec(
        goal=f"针对薄弱点“{concept}”完成证据精读并由教师复核",
        assumptions=(f"发布时掌握度={float(score):.2f}", "来源=正式学员画像"),
        nodes=(PlanNodeSpec(
            node_key=f"teacher-intervention-{chapter.id}",
            node_type="chapter",
            target_object_id=chapter.id,
            title=f"教师干预：{concept}证据精读",
            resource_status="existing",
            estimate_min_minutes=20,
            estimate_max_minutes=40,
            risk_level="normal",
        ),),
    )
    plan, version, created = create_plan_draft(
        session,
        owner_public_id=learner.public_id,
        course_id=course_id,
        title=f"教师干预：{concept}",
        idempotency_key=idempotency_key,
        spec=spec,
        actor_public_id=actor.public_id,
    )
    if plan.status == "draft":
        path = confirm_plan(
            session,
            plan=plan,
            owner_public_id=learner.public_id,
            expected_lock_version=plan.lock_version,
            actor_public_id=actor.public_id,
        )
    else:
        path = session.query(DBLearningPath).filter_by(
            source_plan_version_id=version.id
        ).order_by(DBLearningPath.created_at.desc()).first()
    try:
        existing_audit = session.query(DBAuditLog.id).filter_by(
            action="teacher.intervention.publish",
            object_type="plan_draft",
            object_id=plan.id,
        ).first()
        if existing_audit is None:
            record_backend_audit(
                session,
                actor_public_id=actor.public_id,
                action="teacher.intervention.publish",
                object_type="plan_draft",
                object_id=plan.id,
                before_summary={"state": "not_published"},
                after_summary={
                    "state": "published",
                    "courseId": course_id,
                    "learnerPublicId": learner.public_id,
                    "pathId": path.id,
                    "created": created,
                },
            )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return {"plan_id": plan.id, "path_id": path.id, "created": created, "concept": concept, "baseline_mastery": score}


def learner_submit_intervention_evidence(
    session: Any, *, actor: DBUser, path_id: str, active_seconds: int,
) -> dict[str, Any]:
    path = session.query(DBLearningPath).filter_by(id=path_id).first()
    if path is None or path.owner_public_id != actor.public_id:
        raise HTTPException(status_code=403, detail="只能提交自己的干预学习证据")
    node = session.query(DBPathNode).filter_by(learning_path_id=path.id).order_by(DBPathNode.sequence).first()
    event, _ = record_learning_event(
        session,
        owner_public_id=actor.public_id,
        trusted_source=False,
        event=LearningEventInput(
            idempotency_key=f"teacher-intervention-study:{path.id}",
            event_type="reading_threshold",
            course_id=path.course_id,
            object_type="chapter",
            object_id=node.target_object_id,
            source="frontend",
            occurred_at=datetime.now(timezone.utc),
            payload={"active_seconds": active_seconds, "path_id": path.id},
        ),
    )
    process_path_event(session, event=event)
    session.commit()
    return {"event_id": event.id, "path_id": path.id, "node_status": node.status}


def teacher_confirm_intervention(
    session: Any, *, actor: DBUser, path_id: str, learner_event_id: str,
) -> dict[str, Any]:
    path = session.query(DBLearningPath).filter_by(id=path_id).first()
    if path is None:
        raise HTTPException(status_code=404, detail="干预路径不存在")
    _require_teacher(session, course_id=path.course_id, actor=actor)
    learner_event = session.query(DBLearningEvent).filter_by(
        id=learner_event_id, owner_public_id=path.owner_public_id
    ).first()
    if learner_event is None or learner_event.payload.get("path_id") != path.id:
        raise HTTPException(status_code=409, detail="缺少该干预路径的学员学习证据")
    node = session.query(DBPathNode).filter_by(learning_path_id=path.id).order_by(DBPathNode.sequence).first()
    event, _ = record_learning_event(
        session,
        owner_public_id=path.owner_public_id,
        trusted_source=True,
        event=LearningEventInput(
            idempotency_key=f"teacher-intervention-confirm:{path.id}",
            event_type="teacher_confirmed",
            course_id=path.course_id,
            object_type="chapter",
            object_id=node.target_object_id,
            source="teacher",
            occurred_at=datetime.now(timezone.utc),
            payload={"scope": "intervention_completion", "learner_event_id": learner_event.id, "teacher_public_id": actor.public_id},
        ),
    )
    process_path_event(session, event=event)
    session.commit()
    return {"event_id": event.id, "path_id": path.id, "node_status": node.status, "path_status": path.status}


def teacher_intervention_overview(session: Any, *, actor: DBUser, course_id: str) -> dict[str, Any]:
    _require_teacher(session, course_id=course_id, actor=actor)
    members = session.query(DBCourseMembership).filter_by(
        course_id=course_id, role="student", status="active"
    ).all()
    students = []
    for member in members:
        user = session.query(DBUser).filter_by(public_id=member.user_public_id).one()
        profile = session.query(DBStudentProfile).filter_by(student_id=user.username).first()
        mastery = dict(profile.concept_mastery or {}) if profile else {}
        weakest = min(mastery.items(), key=lambda item: float(item[1])) if mastery else ("未形成", 0.0)
        students.append({"public_id": user.public_id, "display_name": user.display_name, "weakest_concept": weakest[0], "mastery": weakest[1]})
    interventions = []
    versions = session.query(DBPlanVersion).filter_by(created_by_public_id=actor.public_id).all()
    for version in versions:
        plan = session.query(DBPlanDraft).filter_by(id=version.plan_draft_id, course_id=course_id).first()
        if plan is None or not plan.title.startswith("教师干预："):
            continue
        path = session.query(DBLearningPath).filter_by(source_plan_version_id=version.id).order_by(DBLearningPath.created_at.desc()).first()
        node = session.query(DBPathNode).filter_by(learning_path_id=path.id).first() if path else None
        learner = session.query(DBUser).filter_by(public_id=plan.owner_public_id).one()
        study_event = None
        if path:
            for candidate in session.query(DBLearningEvent).filter_by(
                owner_public_id=plan.owner_public_id, event_type="reading_threshold"
            ).order_by(DBLearningEvent.occurred_at.desc()).all():
                if (candidate.payload or {}).get("path_id") == path.id:
                    study_event = candidate
                    break
        interventions.append({
            "plan_id": plan.id, "path_id": path.id if path else None,
            "learner_public_id": learner.public_id, "learner_name": learner.display_name,
            "title": plan.title, "node_status": node.status if node else "pending",
            "learner_event_id": study_event.id if study_event else None,
            "teacher_confirmed": bool(node and node.status == "completed"),
        })
    return {"course_id": course_id, "students": students, "interventions": interventions}
