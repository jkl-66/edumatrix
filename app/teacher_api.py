"""Minimal teacher workspace API over canonical course and learning facts."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field

from app.agent_audit import public_agent_runs
from app.auth import get_current_user
from app.course_governance import list_classes
from app.database import (
    DBArtifact,
    DBChapter,
    DBCourse,
    DBCourseMembership,
    DBGenerationTask,
    DBLearningEvent,
    DBLearningPath,
    DBPathNode,
    DBSourceDocument,
    DBTeachingClass,
    DBTeachingTask,
    DBUser,
    run_db_op,
)
from app.identity import normalize_role
from app.m2_contracts import StrictModel
from app.m6_teacher import publish_teacher_intervention
from app.profile_summary import build_profile_summary


router = APIRouter(prefix="/api/v1/teacher", tags=["teacher"])


class InterventionInput(StrictModel):
    course_id: str = Field(min_length=1, max_length=128)
    learner_public_id: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=128)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat(timespec="seconds") + ("Z" if value.tzinfo is None else "")


def _require_teacher_actor(actor: DBUser) -> str:
    try:
        role = normalize_role(actor.role)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="当前账号没有教师工作区权限") from exc
    if role not in {"teacher", "admin"}:
        raise HTTPException(status_code=403, detail="当前账号没有教师工作区权限")
    return role


def _can_read_course(db: Any, actor: DBUser, course: DBCourse) -> bool:
    role = _require_teacher_actor(actor)
    if role == "admin" or course.owner_public_id == actor.public_id:
        return True
    return db.query(DBCourseMembership).filter_by(
        course_id=course.id,
        user_public_id=actor.public_id,
        role="teacher",
        status="active",
    ).first() is not None


def _authorized_courses(db: Any, actor: DBUser) -> list[DBCourse]:
    _require_teacher_actor(actor)
    from course_catalog import course_is_selectable
    return [
        course
        for course in db.query(DBCourse).order_by(DBCourse.title, DBCourse.id).all()
        if _can_read_course(db, actor, course) and course_is_selectable(db, course)
    ]


def _course(db: Any, actor: DBUser, course_id: str) -> DBCourse:
    from course_catalog import course_is_selectable
    row = db.query(DBCourse).filter_by(id=course_id).first()
    if row is None or not _can_read_course(db, actor, row) or not course_is_selectable(db, row):
        raise HTTPException(status_code=404, detail="课程不存在或不在当前教学范围")
    return row


def _student(db: Any, *, course_id: str, learner_public_id: str) -> DBUser:
    membership = db.query(DBCourseMembership).filter_by(
        course_id=course_id,
        user_public_id=learner_public_id,
        role="student",
        status="active",
    ).first()
    learner = db.query(DBUser).filter_by(public_id=learner_public_id, is_active=True).first()
    if membership is None or learner is None:
        raise HTTPException(status_code=404, detail="学员不存在或不在当前课程")
    return learner


def _course_counts(db: Any, course_id: str) -> dict[str, int]:
    class_ids = [
        row[0]
        for row in db.query(DBTeachingClass.id).filter_by(
            course_id=course_id, status="active",
        ).all()
    ]
    return {
        "chapters": db.query(DBChapter).filter_by(course_id=course_id).count(),
        "sources": db.query(DBSourceDocument).filter_by(course_id=course_id).count(),
        "resources": db.query(DBArtifact).filter(
            DBArtifact.course_id == course_id,
            DBArtifact.status != "archived",
        ).count(),
        "students": db.query(DBCourseMembership).filter_by(
            course_id=course_id, role="student", status="active",
        ).count(),
        "classes": len(class_ids),
        "openTasks": db.query(DBTeachingTask).filter(
            DBTeachingTask.class_id.in_(class_ids or [""]),
            DBTeachingTask.status.in_(("draft", "published")),
        ).count(),
    }


def _course_item(db: Any, course: DBCourse) -> dict[str, Any]:
    return {
        "id": course.id,
        "title": course.title,
        "subject": course.subject,
        "description": course.description,
        "version": course.version,
        "status": course.status,
        "visibility": course.visibility,
        "counts": _course_counts(db, course.id),
    }


def _path_projection(db: Any, *, course_id: str, learner_public_id: str) -> dict[str, Any]:
    path = db.query(DBLearningPath).filter(
        DBLearningPath.course_id == course_id,
        DBLearningPath.owner_public_id == learner_public_id,
        DBLearningPath.status.in_(("active", "paused")),
    ).order_by(DBLearningPath.updated_at.desc(), DBLearningPath.id.desc()).first()
    if path is None:
        return {
            "state": "empty",
            "pathId": None,
            "status": "missing",
            "completed": 0,
            "total": 0,
            "completionRate": None,
            "nextTask": None,
        }
    nodes = db.query(DBPathNode).filter_by(learning_path_id=path.id).order_by(
        DBPathNode.sequence,
    ).all()
    completed = sum(node.status == "completed" for node in nodes)
    next_node = next(
        (node for node in nodes if node.status not in {"completed", "skipped"}),
        None,
    )
    return {
        "state": "complete" if nodes else "empty",
        "pathId": path.id,
        "status": path.status,
        "completed": completed,
        "total": len(nodes),
        "completionRate": round(completed / len(nodes), 4) if nodes else None,
        "nextTask": (
            {
                "nodeId": next_node.id,
                "title": next_node.title,
                "status": next_node.status,
                "estimatedMinutes": next_node.estimate_max_minutes,
            }
            if next_node else None
        ),
    }


def _profile_projection(db: Any, *, course_id: str, learner: DBUser) -> dict[str, Any]:
    # The canonical summary is owner-scoped. Authorization is completed before
    # this call, then the learner identity selects the correct evidence graph.
    profile = build_profile_summary(db, current_user=learner, course_id=course_id)
    graph = profile["knowledge_graph"]
    priority = {"conflict": 0, "weak": 1, "developing": 2}
    weak_nodes = sorted(
        (
            node for node in graph["nodes"]
            if node["masteryBand"] in priority
        ),
        key=lambda node: (
            priority[node["masteryBand"]],
            node["mastery"] if node["mastery"] is not None else 1.0,
            node["name"],
        ),
    )
    weak_points = [
        {
            "id": node["id"],
            "title": node["name"],
            "mastery": node["mastery"],
            "masteryBand": node["masteryBand"],
            "confidence": node["confidence"],
            "evidenceCount": node["evidenceCount"],
            "sourceEventIds": list(node["sourceEventIds"]),
            "judgement": node["judgement"],
            "nextAction": node["nextAction"],
        }
        for node in weak_nodes[:6]
    ]
    source_event_ids = list(dict.fromkeys(
        event_id
        for point in weak_points
        for event_id in point["sourceEventIds"]
    ))
    if source_event_ids:
        evidence_state = "sufficient"
        evidence_message = "薄弱点可下钻到已接受的学习事件。"
    elif any(point["evidenceCount"] for point in weak_points):
        evidence_state = "snapshot_only"
        evidence_message = "已有画像或作答快照，但暂无可下钻的有效学习事件。"
    else:
        evidence_state = "insufficient"
        evidence_message = "当前证据不足，暂不形成稳定薄弱点结论。"
    return {
        "state": "complete",
        "evidenceState": evidence_state,
        "evidenceMessage": evidence_message,
        "sourceEventIds": source_event_ids,
        "weakPoints": weak_points,
        "summary": profile["summary"],
        "sections": profile["sections"],
        "knowledgeGraph": graph,
        "boundary": profile["boundary"],
    }


def _recent_evidence(
    db: Any, *, course_id: str, learner_public_id: str, limit: int = 12,
) -> list[dict[str, Any]]:
    rows = db.query(DBLearningEvent).filter_by(
        course_id=course_id,
        owner_public_id=learner_public_id,
    ).order_by(DBLearningEvent.occurred_at.desc(), DBLearningEvent.id.desc()).limit(limit).all()
    return [
        {
            "sourceEventId": row.id,
            "eventType": row.event_type,
            "source": row.source,
            "objectType": row.object_type,
            "objectId": row.object_id,
            "evidenceStatus": row.evidence_status,
            "evidenceStrength": row.evidence_strength,
            "masteryEligible": bool(row.mastery_eligible),
            "occurredAt": _iso(row.occurred_at),
        }
        for row in rows
    ]


def _public_agent_projection(
    db: Any, *, course_id: str, learner_public_id: str,
) -> dict[str, Any]:
    tasks = db.query(DBGenerationTask).filter_by(
        course_id=course_id,
        owner_public_id=learner_public_id,
    ).order_by(DBGenerationTask.created_at.desc(), DBGenerationTask.id.desc()).limit(12).all()
    for task in tasks:
        try:
            runs = public_agent_runs(
                db, task_id=task.id, owner_public_id=learner_public_id,
            )
        except (PermissionError, ValueError):
            return {
                "state": "failed",
                "message": "公开协作证据暂不可用，可稍后重试。",
                "items": [],
            }
        if not runs:
            continue
        return {
            "state": "complete",
            "message": "仅展示公开职责、来源与校验摘要。",
            "items": [
                {
                    "role": run.role,
                    "inputRefs": list(run.input_refs),
                    "candidateSummary": run.candidate_summary,
                    "disagreement": run.disagreement,
                    "validation": run.validation,
                    "revision": run.revision,
                    "decisionSummary": run.decision_summary,
                    "status": run.status,
                }
                for run in runs
            ],
        }
    return {
        "state": "empty",
        "message": "当前没有可公开的 Agent 协作证据。",
        "items": [],
    }


def _student_item(db: Any, *, course_id: str, learner: DBUser) -> dict[str, Any]:
    profile = _profile_projection(db, course_id=course_id, learner=learner)
    path = _path_projection(
        db, course_id=course_id, learner_public_id=learner.public_id,
    )
    weakest = profile["weakPoints"][0] if profile["weakPoints"] else None
    needs_attention = (
        profile["evidenceState"] != "sufficient"
        or bool(weakest and weakest["masteryBand"] in {"weak", "conflict"})
        or (
            path["completionRate"] is not None
            and path["completionRate"] < 0.5
        )
    )
    return {
        "publicId": learner.public_id,
        "username": learner.username,
        "displayName": learner.display_name or learner.username,
        "evidenceState": profile["evidenceState"],
        "evidenceMessage": profile["evidenceMessage"],
        "sourceEventIds": profile["sourceEventIds"],
        "weakestPoint": weakest,
        "path": path,
        "needsAttention": needs_attention,
        "attentionReason": (
            f"优先关注：{weakest['title']}"
            if weakest else profile["evidenceMessage"]
        ),
        "nextAction": profile["summary"]["next_action"],
    }


def _student_rows(db: Any, *, course_id: str) -> list[DBUser]:
    member_ids = [
        row[0]
        for row in db.query(DBCourseMembership.user_public_id).filter_by(
            course_id=course_id, role="student", status="active",
        ).all()
    ]
    return db.query(DBUser).filter(
        DBUser.public_id.in_(member_ids or [""]),
        DBUser.is_active.is_(True),
    ).order_by(DBUser.display_name, DBUser.username).all()


def _course_list_payload(db: Any, actor: DBUser) -> dict[str, Any]:
    items = [_course_item(db, course) for course in _authorized_courses(db, actor)]
    return {
        "schemaVersion": "edumatrix.teacher.courses.v1",
        "state": "complete" if items else "empty",
        "items": items,
    }


def _course_detail_payload(db: Any, actor: DBUser, course_id: str) -> dict[str, Any]:
    course = _course(db, actor, course_id)
    sources = db.query(DBSourceDocument).filter_by(course_id=course.id).order_by(
        DBSourceDocument.title, DBSourceDocument.id,
    ).all()
    chapters = db.query(DBChapter).filter_by(course_id=course.id).order_by(
        DBChapter.position, DBChapter.id,
    ).all()
    resources = db.query(DBArtifact).filter(
        DBArtifact.course_id == course.id,
        DBArtifact.status != "archived",
    ).order_by(DBArtifact.updated_at.desc(), DBArtifact.id.desc()).all()
    classes = list_classes(db, actor, course.id)
    return {
        "schemaVersion": "edumatrix.teacher.course-detail.v1",
        "state": "complete",
        "course": _course_item(db, course),
        "chapters": [
            {
                "id": row.id,
                "title": row.title,
                "position": row.position,
                "headingLevel": row.heading_level,
                "sourceDocumentId": row.source_document_id,
            }
            for row in chapters
        ],
        "sources": [
            {
                "id": row.id,
                "title": row.title,
                "filename": row.filename,
                "fileFormat": row.file_format,
                "processingStatus": row.processing_status,
                "licenseText": row.license_text,
            }
            for row in sources
        ],
        "resources": [
            {
                "id": row.id,
                "title": row.title,
                "type": row.artifact_type,
                "status": row.status,
                "updatedAt": _iso(row.updated_at),
            }
            for row in resources
        ],
        "classes": classes,
    }


def _student_list_payload(
    db: Any, actor: DBUser, *, course_id: str | None, query: str,
) -> dict[str, Any]:
    courses = _authorized_courses(db, actor)
    if not courses:
        return {
            "schemaVersion": "edumatrix.teacher.students.v1",
            "state": "empty",
            "course": None,
            "items": [],
        }
    selected = _course(
        db, actor, course_id or courses[0].id,
    )
    normalized_query = query.strip().lower()
    learners = _student_rows(db, course_id=selected.id)
    if normalized_query:
        learners = [
            learner for learner in learners
            if normalized_query in learner.username.lower()
            or normalized_query in (learner.display_name or "").lower()
        ]
    items = [_student_item(db, course_id=selected.id, learner=row) for row in learners]
    return {
        "schemaVersion": "edumatrix.teacher.students.v1",
        "state": "complete" if items else "empty",
        "course": {"id": selected.id, "title": selected.title},
        "items": items,
    }


def _student_detail_payload(
    db: Any, actor: DBUser, *, course_id: str, learner_public_id: str,
) -> dict[str, Any]:
    course = _course(db, actor, course_id)
    learner = _student(
        db, course_id=course.id, learner_public_id=learner_public_id,
    )
    item = _student_item(db, course_id=course.id, learner=learner)
    return {
        "schemaVersion": "edumatrix.teacher.student-detail.v1",
        "state": "complete",
        "course": {"id": course.id, "title": course.title},
        "student": item,
        "profile": _profile_projection(db, course_id=course.id, learner=learner),
        "evidenceTimeline": _recent_evidence(
            db, course_id=course.id, learner_public_id=learner.public_id,
        ),
        "agentAudit": _public_agent_projection(
            db, course_id=course.id, learner_public_id=learner.public_id,
        ),
        "actions": {
            "canCreateIntervention": True,
            "canEditMastery": False,
        },
    }


def _overview_payload(
    db: Any, actor: DBUser, *, course_id: str | None,
) -> dict[str, Any]:
    courses_payload = _course_list_payload(db, actor)
    if not courses_payload["items"]:
        return {
            "schemaVersion": "edumatrix.teacher.overview.v1",
            "state": "empty",
            "selectedCourse": None,
            "courses": [],
            "weakPoints": [],
            "attentionStudents": [],
            "pendingTasks": [],
            "sectionStates": {
                "courses": "empty",
                "studentEvidence": "empty",
                "teachingTasks": "empty",
            },
            "updatedAt": _iso(datetime.now(timezone.utc)),
        }
    selected = _course(
        db, actor, course_id or courses_payload["items"][0]["id"],
    )
    students = [
        _student_item(db, course_id=selected.id, learner=row)
        for row in _student_rows(db, course_id=selected.id)
    ]
    weak_counts = Counter(
        point["title"]
        for student in students
        for point in ([student["weakestPoint"]] if student["weakestPoint"] else [])
    )
    classes = list_classes(db, actor, selected.id)
    pending_tasks = [
        {
            "id": task["id"],
            "title": task["title"],
            "status": task["status"],
            "dueAt": task["due_at"],
            "classId": classroom["id"],
            "classTitle": classroom["title"],
        }
        for classroom in classes
        for task in classroom["tasks"]
        if task["status"] in {"draft", "published"}
    ]
    attention = [item for item in students if item["needsAttention"]]
    return {
        "schemaVersion": "edumatrix.teacher.overview.v1",
        "state": "complete",
        "selectedCourse": {"id": selected.id, "title": selected.title},
        "courses": courses_payload["items"],
        "summary": {
            "courseCount": len(courses_payload["items"]),
            "studentCount": len(students),
            "attentionCount": len(attention),
            "pendingTaskCount": len(pending_tasks),
        },
        "weakPoints": [
            {"title": title, "studentCount": count}
            for title, count in weak_counts.most_common(8)
        ],
        "attentionStudents": attention[:8],
        "pendingTasks": pending_tasks[:8],
        "sectionStates": {
            "courses": "complete",
            "studentEvidence": "complete" if students else "empty",
            "teachingTasks": "complete" if pending_tasks else "empty",
        },
        "updatedAt": _iso(datetime.now(timezone.utc)),
    }


@router.get("/overview")
async def get_overview(
    course_id: str | None = None,
    current_user: DBUser = Depends(get_current_user),
):
    return await run_db_op(
        lambda db: _overview_payload(db, current_user, course_id=course_id),
    )


@router.get("/courses")
async def get_courses(current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(lambda db: _course_list_payload(db, current_user))


@router.get("/courses/{course_id}")
async def get_course_detail(
    course_id: str,
    current_user: DBUser = Depends(get_current_user),
):
    return await run_db_op(
        lambda db: _course_detail_payload(db, current_user, course_id),
    )


@router.get("/students")
async def get_students(
    course_id: str | None = None,
    query: str = "",
    current_user: DBUser = Depends(get_current_user),
):
    return await run_db_op(
        lambda db: _student_list_payload(
            db, current_user, course_id=course_id, query=query,
        ),
    )


@router.get("/students/{learner_public_id}")
async def get_student_detail(
    learner_public_id: str,
    course_id: str,
    current_user: DBUser = Depends(get_current_user),
):
    return await run_db_op(
        lambda db: _student_detail_payload(
            db,
            current_user,
            course_id=course_id,
            learner_public_id=learner_public_id,
        ),
    )


@router.post("/interventions", status_code=status.HTTP_201_CREATED)
async def post_intervention(
    payload: InterventionInput,
    current_user: DBUser = Depends(get_current_user),
):
    _require_teacher_actor(current_user)
    result = await run_db_op(
        lambda db: publish_teacher_intervention(
            db, actor=current_user, **payload.model_dump(),
        ),
    )
    return {
        "schemaVersion": "edumatrix.teacher.intervention.v1",
        "state": "complete",
        **result,
    }
