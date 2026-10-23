"""Read-only composition of the frozen competition demonstration context."""

from __future__ import annotations

from typing import Any

from app.competition_demo_seed import load_competition_demo_manifest
from app.database import (
    DBChapter,
    DBCourse,
    DBCourseMembership,
    DBKnowledgePoint,
    DBLearningPath,
    DBPathNode,
    DBProfileSnapshot,
    DBReviewPlan,
    DBSourceDocument,
    DBTeachingClass,
    DBTeachingClassMember,
    DBUser,
)
from app.identity import normalize_role


class CompetitionDemoContextAccessError(PermissionError):
    pass


def _page_contracts(
    initialized: bool,
    *,
    course_id: str = "",
    chapter_id: str = "",
) -> dict[str, dict[str, Any]]:
    recovery = {
        "label": "初始化演示数据",
        "route": "/competition-showcase",
    }
    if not initialized:
        return {
            key: {
                "status": "演示数据尚未初始化",
                "next_step": "请由管理员完成一次演示数据初始化。",
                "primary_action": recovery,
            }
            for key in ("dashboard", "knowledge", "path", "profile", "review", "teacher", "showcase")
        }
    course_route = f"/knowledge?course_id={course_id}&chapter_id={chapter_id}"
    workspace_route = f"/workspace?course_id={course_id}&chapter_id={chapter_id}"
    return {
        "dashboard": {
            "status": "正在学习第 7 章：混合检索、重排与 Recall@K",
            "next_step": "先确认主课程来源与许可，再从推荐章节进入学习空间。",
            "primary_action": {"label": "查看主课程与来源", "route": course_route},
        },
        "knowledge": {
            "status": "9 份冻结课程来源已就绪",
            "next_step": "核对许可和固定版本后，从第 7 章进入统一学习空间。",
            "primary_action": {"label": "从第 7 章开始学习", "route": workspace_route},
        },
        "path": {
            "status": "当前路径包含 3 个连续任务",
            "next_step": "完成“精读混合检索来源”后解锁实验与短测。",
            "primary_action": {"label": "继续当前任务", "route": workspace_route},
        },
        "profile": {
            "status": "当前掌握度 58%，已确认 2 个薄弱知识点",
            "next_step": "围绕向量检索和混合检索补齐证据，再观察画像变化。",
            "primary_action": {"label": "查看学习路径", "route": "/learning-path"},
        },
        "review": {
            "status": "2 项复习任务已进入统一复习队列",
            "next_step": "先复习“混合检索与重排”，再处理引用约束与拒答。",
            "primary_action": {"label": "开始当前复习", "route": "/review#competition-demo-reviews"},
        },
        "teacher": {
            "status": "15 人演示班中有 4 人需要关注",
            "next_step": "进入焦点学生证据页，查看薄弱点和可解释干预依据。",
            "primary_action": {"label": "查看焦点学生", "route": "/student-analysis?student_id=lzz"},
        },
        "showcase": {
            "status": "学生、教师、技术证据三条主旅程已具备统一起点",
            "next_step": "选择一条旅程，以真实角色账号完成 UI-only 操作。",
            "primary_action": {"label": "进入学生旅程", "route": "/"},
        },
    }


def _require_demo_access(db: Any, user: DBUser, course_id: str) -> None:
    if normalize_role(user.role) == "admin":
        return
    membership = db.query(DBCourseMembership).filter_by(
        course_id=course_id,
        user_public_id=user.public_id,
        status="active",
    ).first()
    if membership is None:
        raise CompetitionDemoContextAccessError("current user is outside the competition demo course")


def build_competition_demo_context(db: Any, user: DBUser) -> dict[str, Any]:
    """Compose one role-aware response from canonical competition demo facts."""

    manifest = load_competition_demo_manifest()
    course_id = manifest["course"]["id"]
    course = db.get(DBCourse, course_id)
    from course_catalog import course_is_selectable
    if course is not None and not course_is_selectable(db, course):
        raise CompetitionDemoContextAccessError("competition demo course is not currently selectable")
    if course is None:
        if normalize_role(user.role) != "admin":
            raise CompetitionDemoContextAccessError("competition demo is not initialized")
        return {
            "demo_scope": manifest["demo_scope"],
            "manifest_version": manifest["manifest_version"],
            "initialized": False,
            "issues": ["course_missing"],
            "viewer": {"username": user.username, "role": normalize_role(user.role)},
            "course": None,
            "sources": [],
            "chapters": [],
            "knowledge_points": [],
            "focus_student": None,
            "path": None,
            "reviews": [],
            "cohort": None,
            "truthfulness": manifest["truthfulness"],
            "page_contracts": _page_contracts(False),
        }

    _require_demo_access(db, user, course_id)

    sources = db.query(DBSourceDocument).filter_by(course_id=course_id).order_by(DBSourceDocument.filename).all()
    chapters = db.query(DBChapter).filter_by(course_id=course_id).order_by(DBChapter.position).all()
    knowledge_point_specs = manifest["knowledge_points"]
    knowledge_point_ids = [item["id"] for item in knowledge_point_specs]
    knowledge_points = db.query(DBKnowledgePoint).filter(DBKnowledgePoint.id.in_(knowledge_point_ids)).all()
    knowledge_by_id = {item.id: item for item in knowledge_points}

    focus_username = next(
        item["username"] for item in manifest["users"] if item["id"] == manifest["focus_student"]["user_id"]
    )
    focus_user = db.query(DBUser).filter_by(username=focus_username).first()
    role = normalize_role(user.role)
    can_view_focus = role in {"admin", "teacher", "assistant"} or user.username == focus_username

    profile = None
    path = None
    reviews: list[dict[str, Any]] = []
    focus_payload = None
    if focus_user is not None and can_view_focus:
        profile = db.query(DBProfileSnapshot).filter_by(
            owner_public_id=focus_user.public_id,
            profile_version="competition.demo.profile.v1",
        ).order_by(DBProfileSnapshot.created_at.desc()).first()
        path = db.query(DBLearningPath).filter_by(
            owner_public_id=focus_user.public_id,
            course_id=course_id,
            status="active",
        ).order_by(DBLearningPath.created_at.desc()).first()
        path_nodes = [] if path is None else db.query(DBPathNode).filter_by(
            learning_path_id=path.id,
        ).order_by(DBPathNode.sequence).all()
        review_rows = [
            row
            for row in db.query(DBReviewPlan).filter_by(student_id=focus_username).order_by(DBReviewPlan.priority, DBReviewPlan.id).all()
            if any(str(value).startswith("logical:demo-review-") for value in (row.similar_quiz_ids or []))
        ]
        for row in review_rows:
            reviews.append({
                "id": row.id,
                "knowledge_point_id": row.concept,
                "knowledge_point_title": knowledge_by_id.get(row.concept).title if row.concept in knowledge_by_id else row.concept,
                "mastery": row.mastery,
                "interval_days": row.interval_days,
                "review_count": row.review_count,
                "next_review_at": row.next_review_at.isoformat() if row.next_review_at else None,
                "priority": row.priority,
            })
        snapshot = dict(profile.snapshot or {}) if profile is not None else {}
        focus_payload = {
            "username": focus_username,
            "public_id": focus_user.public_id,
            "display_name": focus_user.display_name,
            "profile_snapshot_id": profile.id if profile else None,
            "mastery": snapshot.get("mastery"),
            "mastered_knowledge_points": [
                {"id": item_id, "title": knowledge_by_id[item_id].title}
                for item_id in snapshot.get("mastered_knowledge_point_ids", []) if item_id in knowledge_by_id
            ],
            "weak_knowledge_points": [
                {"id": item_id, "title": knowledge_by_id[item_id].title}
                for item_id in snapshot.get("weak_knowledge_point_ids", []) if item_id in knowledge_by_id
            ],
            "misconception": snapshot.get("misconception"),
        }
        path_payload = None if path is None else {
            "id": path.id,
            "status": path.status,
            "course_id": path.course_id,
            "tasks": [
                {
                    "id": node.id,
                    "sequence": node.sequence,
                    "type": node.node_type,
                    "target_object_id": node.target_object_id,
                    "title": node.title,
                    "status": node.status,
                    "prerequisites": list(node.prerequisites or []),
                    "estimate_minutes": node.estimate_max_minutes,
                }
                for node in path_nodes
            ],
        }
    else:
        path_payload = None

    profile_rows = db.query(DBProfileSnapshot).filter_by(profile_version="competition.demo.profile.v1").all()
    cohort_snapshots = [dict(row.snapshot or {}) for row in profile_rows if (row.snapshot or {}).get("course_id") == course_id]
    classroom = db.get(DBTeachingClass, manifest["cohort"]["class_id"])
    student_count = 0
    if classroom is not None:
        student_count = db.query(DBTeachingClassMember).filter_by(
            class_id=classroom.id,
            role="student",
            status="active",
        ).count()
    mastery_values = [float(item.get("mastery", 0.0)) for item in cohort_snapshots]
    cohort = {
        "id": manifest["cohort"]["id"],
        "class_id": classroom.id if classroom else manifest["cohort"]["class_id"],
        "title": classroom.title if classroom else manifest["cohort"]["title"],
        "student_count": student_count,
        "participated_count": sum(bool(item.get("participated")) for item in cohort_snapshots),
        "participation_rate": round(sum(bool(item.get("participated")) for item in cohort_snapshots) / len(cohort_snapshots), 4) if cohort_snapshots else 0.0,
        "attention_count": sum(bool(item.get("attention")) for item in cohort_snapshots),
        "average_mastery": round(sum(mastery_values) / len(mastery_values), 4) if mastery_values else 0.0,
        "metric_source": "15 份冻结合成画像快照的确定性聚合",
        "time_window": manifest["metric_contract"]["time_window"],
    }

    issues = []
    if len(sources) != len(manifest["source_documents"]):
        issues.append("source_count_mismatch")
    if len(chapters) != manifest["course"]["chapter_count"]:
        issues.append("chapter_count_mismatch")
    if len(knowledge_points) != manifest["course"]["knowledge_point_count"]:
        issues.append("knowledge_point_count_mismatch")
    if student_count != manifest["metric_contract"]["cohort_size"]:
        issues.append("cohort_count_mismatch")
    if can_view_focus and (profile is None or path is None or len(reviews) != 2):
        issues.append("focus_student_context_incomplete")

    source_chapter_counts: dict[str, int] = {}
    for chapter in chapters:
        source_chapter_counts[chapter.source_document_id] = source_chapter_counts.get(chapter.source_document_id, 0) + 1
    recommended_chapter = next((item for item in chapters if item.position == 7), chapters[0] if chapters else None)

    return {
        "demo_scope": manifest["demo_scope"],
        "manifest_version": manifest["manifest_version"],
        "initialized": not issues,
        "issues": issues,
        "viewer": {"username": user.username, "role": role},
        "course": {
            "id": course.id,
            "title": course.title,
            "version": course.version,
            "subject": course.subject,
            "description": course.description,
            "license": course.license_text,
            "source_count": len(sources),
            "chapter_count": len(chapters),
            "knowledge_point_count": len(knowledge_points),
        },
        "entry": {
            "course_id": course.id,
            "chapter_id": recommended_chapter.id if recommended_chapter else "",
            "chapter_title": recommended_chapter.title if recommended_chapter else "",
            "course_route": f"/knowledge?course_id={course.id}&chapter_id={recommended_chapter.id if recommended_chapter else ''}",
            "workspace_route": f"/workspace?course_id={course.id}&chapter_id={recommended_chapter.id if recommended_chapter else ''}",
            "data_label": "冻结合成演示数据",
        },
        "sources": [
            {
                "id": item.id,
                "title": item.title,
                "filename": item.filename,
                "file_format": item.file_format,
                "status": item.processing_status,
                "source_path": item.source_path,
                "license": item.license_text,
                "content_hash": item.content_hash,
                "chapter_count": source_chapter_counts.get(item.id, 0),
            }
            for item in sources
        ],
        "chapters": [
            {"id": item.id, "title": item.title, "position": item.position, "source_document_id": item.source_document_id}
            for item in chapters
        ],
        "knowledge_points": [
            {
                "id": item_id,
                "code": knowledge_by_id[item_id].code,
                "title": knowledge_by_id[item_id].title,
                "prerequisites": list(knowledge_by_id[item_id].prerequisites or []),
            }
            for item_id in knowledge_point_ids if item_id in knowledge_by_id
        ],
        "focus_student": focus_payload,
        "path": path_payload,
        "reviews": reviews,
        "cohort": cohort,
        "truthfulness": manifest["truthfulness"],
        "page_contracts": _page_contracts(
            not issues,
            course_id=course.id,
            chapter_id=recommended_chapter.id if recommended_chapter else "",
        ),
        "showcase": {
            "ready_count": 3 if not issues else 0,
            "total_count": 3,
            "journeys": [
                {"key": "student", "label": "学生学习闭环", "route": "/", "ready": not issues},
                {"key": "teacher", "label": "教师证据闭环", "route": "/teacher", "ready": not issues},
                {"key": "evidence", "label": "技术证据与高级能力", "route": "/advanced-capabilities", "ready": not issues},
            ],
        },
    }
