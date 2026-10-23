from __future__ import annotations

import hashlib
import json
from typing import Any

from app.authorization import ObjectAccess, active_course_role, can_access_object
from app.database import (
    DBChapter,
    DBChapterKnowledgePoint,
    DBChapterVideoLink,
    DBCourse,
    DBKnowledgePoint,
    DBProfileSnapshot,
    DBSourceDocument,
    DBSourceRef,
    DBUser,
)
from app.video_rendering import create_project, get_project


class ChapterVideoError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise ChapterVideoError(code, message)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _trim(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _course_allowed(db: Any, actor: DBUser, course: DBCourse) -> bool:
    role = active_course_role(db, course_id=course.id, user_public_id=actor.public_id)
    return can_access_object(
        actor,
        ObjectAccess(
            "course", course.id, owner_public_id=course.owner_public_id,
            course_id=course.id, visibility=course.visibility,
        ),
        action="read",
        course_role=role,
    )


def _course(db: Any, actor: DBUser, course_id: str) -> DBCourse:
    from course_catalog import course_is_selectable
    row = db.get(DBCourse, course_id)
    if row is None:
        _fail("chapter_video.course_unknown", "课程不存在")
    if not _course_allowed(db, actor, row):
        _fail("chapter_video.course_forbidden", "无权访问该课程")
    if not course_is_selectable(db, row):
        _fail("chapter_video.course_unavailable", "这门课程当前没有可用学习资料")
    return row


def _chapter(db: Any, course_id: str, chapter_id: str) -> DBChapter:
    row = db.get(DBChapter, chapter_id)
    if row is None:
        _fail("chapter_video.chapter_unknown", "章节不存在")
    if row.course_id != course_id:
        _fail("chapter_video.chapter_course_mismatch", "章节不属于所选课程")
    return row


def _knowledge_points(db: Any, chapter_id: str) -> list[DBKnowledgePoint]:
    rows = (
        db.query(DBKnowledgePoint)
        .join(DBChapterKnowledgePoint, DBChapterKnowledgePoint.knowledge_point_id == DBKnowledgePoint.id)
        .filter(
            DBChapterKnowledgePoint.chapter_id == chapter_id,
            DBChapterKnowledgePoint.relation_type == "teaches",
            DBKnowledgePoint.status == "active",
        )
        .order_by(DBKnowledgePoint.code.asc(), DBKnowledgePoint.id.asc())
        .all()
    )
    if not rows:
        _fail("chapter_video.knowledge_points_missing", "章节没有可追溯的授课知识点，不能生成孤立视频")
    return rows


def _sources(db: Any, chapter: DBChapter) -> list[dict[str, Any]]:
    rows = (
        db.query(DBSourceRef, DBSourceDocument)
        .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
        .filter(
            DBSourceRef.chapter_id == chapter.id,
            DBSourceDocument.course_id == chapter.course_id,
            DBSourceDocument.processing_status == "ready",
        )
        .order_by(DBSourceRef.created_at.asc(), DBSourceRef.id.asc())
        .all()
    )
    snapshots = []
    for ref, document in rows:
        quote = _trim(ref.quote, 420)
        if not quote:
            continue
        snapshots.append({
            "source_ref_id": ref.id,
            "source_document_id": document.id,
            "document_title": document.title,
            "filename": document.filename,
            "source_url": document.source_url or "",
            "license_text": _trim(document.license_text, 300),
            "parser_version": ref.parser_version,
            "content_hash": ref.content_hash,
            "location_kind": ref.location_kind,
            "location_label": ref.location_label or chapter.title,
            "page_number": ref.page_number,
            "char_range": [ref.char_start, ref.char_end],
            "quote": quote,
        })
        if len(snapshots) >= 6:
            break
    if not snapshots:
        _fail("chapter_video.source_refs_missing", "章节没有包含原文摘录的真实来源引用，不能生成孤立视频")
    return snapshots


def _manifest_objectives(course: DBCourse, chapter: DBChapter) -> list[str]:
    manifest = course.manifest_data if isinstance(course.manifest_data, dict) else {}
    candidates: list[dict[str, Any]] = []
    for key in ("chapters", "sections", "modules"):
        value = manifest.get(key)
        if isinstance(value, list):
            candidates.extend(item for item in value if isinstance(item, dict))
    for item in candidates:
        identity = {str(item.get(key, "")) for key in ("id", "chapter_id", "stable_key", "title")}
        if not ({chapter.id, chapter.stable_key, chapter.title} & identity):
            continue
        for key in ("learning_objectives", "objectives", "learningGoals"):
            value = item.get(key)
            if isinstance(value, list):
                result = [_trim(entry, 180) for entry in value if _trim(entry, 180)]
                if result:
                    return result[:5]
            if isinstance(value, str) and _trim(value, 180):
                return [_trim(value, 180)]
    return []


def _objectives(course: DBCourse, chapter: DBChapter, points: list[DBKnowledgePoint]) -> tuple[list[str], str]:
    declared = _manifest_objectives(course, chapter)
    if declared:
        return declared, "course_manifest"
    titles = [_trim(point.title, 80) for point in points[:4]]
    return [
        f"能够解释{title}的核心含义与适用边界" for title in titles
    ] + [f"能够依据课程原文复述“{_trim(chapter.title, 60)}”的关键结论"], "system_draft"


def _profile(db: Any, actor: DBUser, profile_snapshot_id: str | None) -> tuple[DBProfileSnapshot | None, dict[str, Any]]:
    if not profile_snapshot_id:
        return None, {
            "mode": "baseline",
            "explanation_order": "concept_then_evidence_then_practice",
            "example_density": "standard",
            "pace": "standard",
            "fact_policy": "课程事实、来源范围和质量标准不因画像变化",
        }
    row = db.get(DBProfileSnapshot, profile_snapshot_id)
    if row is None:
        _fail("chapter_video.profile_unknown", "画像快照不存在")
    if row.owner_public_id != actor.public_id:
        _fail("chapter_video.profile_forbidden", "无权使用该画像快照")
    source = row.snapshot if isinstance(row.snapshot, dict) else {}
    style = _trim(source.get("cognitive_style") or source.get("learning_style"), 80)
    preferences = source.get("interaction_preferences")
    if not isinstance(preferences, list):
        preferences = []
    load = source.get("cognitive_load")
    try:
        load_value = float(load)
    except (TypeError, ValueError):
        load_value = 0.5
    visual_code = "视觉" in style or "代码" in style or any("视觉" in str(item) or "代码" in str(item) for item in preferences)
    return row, {
        "mode": "frozen_profile_snapshot",
        "profile_snapshot_id": row.id,
        "profile_version": row.profile_version,
        "profile_content_hash": row.content_hash,
        "cognitive_style": style or "未声明",
        "interaction_preferences": [_trim(item, 60) for item in preferences[:5]],
        "explanation_order": "evidence_then_example_then_concept" if visual_code else "concept_then_evidence_then_practice",
        "example_density": "high" if visual_code else "standard",
        "pace": "measured" if load_value >= 0.65 else "standard",
        "fact_policy": "课程事实、来源范围和质量标准不因画像变化",
    }


def _scenes(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    points = snapshot["knowledge_points"]
    sources = snapshot["sources"]
    objectives = snapshot["learning_objectives"]
    strategy = snapshot["personalization"]
    point_text = "、".join(item["title"] for item in points[:4])
    source = sources[0]
    source_label = source["location_label"] or source["document_title"]
    objective_text = "；".join(objectives[:3])
    example_note = "本段提高示例密度并采用先证据后概念的顺序。" if strategy["example_density"] == "high" else "本段按概念、证据、实践的顺序展开。"
    return [
        {"title": "章节目标与边界", "narration": _trim(f"本节学习{snapshot['chapter']['title']}。目标是：{objective_text}。这些目标的来源类型为{snapshot['objective_origin_label']}。", 500), "bullets": [f"课程：{snapshot['course']['title']}", f"章节：{snapshot['chapter']['title']}", snapshot["truth_boundary"]], "duration_ms": 5500},
        {"title": "核心概念", "narration": _trim(f"本章可追溯的授课知识点包括：{point_text}。讲解只覆盖这些已绑定知识点，不扩展未经课程来源支持的事实。", 500), "bullets": [item["title"] for item in points[:4]], "duration_ms": 5500},
        {"title": "来源驱动讲解", "narration": _trim(f"课程来源“{source_label}”的原文摘录是：{source['quote']}。请将这一段作为本章结论的可定位依据。", 500), "bullets": [f"文档：{source['document_title']}", f"定位：{source_label}", f"引用：{source['source_ref_id']}"], "duration_ms": 6500},
        {"title": "画像适配实践", "narration": _trim(f"{example_note}围绕{points[0]['title']}，先从课程摘录识别关键条件，再用自己的话解释概念，最后完成一个可验证练习。画像只调整节奏与呈现顺序。", 500), "bullets": [f"顺序：{strategy['explanation_order']}", f"节奏：{strategy['pace']}", "事实标准保持一致"], "duration_ms": 6000},
        {"title": "小结与后续练习", "narration": _trim(f"回顾{point_text}。请依据来源摘录完成一次概念复述和一个应用判断，并在课程测评中验证掌握情况。本视频共绑定{len(sources)}条来源引用。", 500), "bullets": ["回看来源摘录", "完成概念复述", "用测评形成学习证据"], "duration_ms": 5500},
    ]


def chapter_video_context(db: Any, *, actor: DBUser, course_id: str | None = None) -> dict[str, Any]:
    from course_catalog import course_is_selectable
    courses = db.query(DBCourse).filter(DBCourse.status != "withdrawn").order_by(DBCourse.title.asc()).all()
    available = [row for row in courses if _course_allowed(db, actor, row) and course_is_selectable(db, row)]
    if course_id:
        selected = _course(db, actor, course_id)
        available = [selected]
    items = []
    for course in available:
        chapters = db.query(DBChapter).filter_by(course_id=course.id).order_by(DBChapter.position.asc(), DBChapter.id.asc()).all()
        items.append({
            "id": course.id, "title": course.title, "version": course.version,
            "visibility": course.visibility,
            "chapters": [{"id": row.id, "title": row.title, "position": row.position} for row in chapters],
        })
    profiles = db.query(DBProfileSnapshot).filter_by(owner_public_id=actor.public_id).order_by(DBProfileSnapshot.created_at.desc()).limit(8).all()
    return {
        "schema_version": "fc1.chapter-video-context.v1",
        "courses": items,
        "profiles": [{"id": row.id, "profile_version": row.profile_version, "content_hash": row.content_hash, "created_at": row.created_at.isoformat() if row.created_at else ""} for row in profiles],
        "truth_boundary": "学习目标如无课程清单正式字段，将明确标记为系统整理目标草案。",
    }


def generate_chapter_video(db: Any, *, actor: DBUser, course_id: str, chapter_id: str, profile_snapshot_id: str | None = None) -> dict[str, Any]:
    course = _course(db, actor, course_id)
    chapter = _chapter(db, course.id, chapter_id)
    points = _knowledge_points(db, chapter.id)
    sources = _sources(db, chapter)
    objectives, objective_origin = _objectives(course, chapter, points)
    profile_row, personalization = _profile(db, actor, profile_snapshot_id)
    truth_boundary = (
        "脚本仅使用当前课程章节、授课知识点和可定位来源摘录；"
        + ("学习目标来自课程清单。" if objective_origin == "course_manifest" else "学习目标为系统整理草案，不宣称是课程官方目标。")
        + "画像只调整呈现策略，不改变事实、来源和质量标准。"
    )
    snapshot = {
        "schema_version": "fc1.chapter-video-input.v1",
        "course": {"id": course.id, "version": course.version, "manifest_version": course.manifest_version, "title": course.title},
        "chapter": {"id": chapter.id, "stable_key": chapter.stable_key, "title": chapter.title, "position": chapter.position},
        "knowledge_points": [{"id": row.id, "code": row.code, "version": row.version, "title": row.title, "level": row.level} for row in points],
        "sources": sources,
        "learning_objectives": objectives,
        "objective_origin": objective_origin,
        "objective_origin_label": "课程清单正式字段" if objective_origin == "course_manifest" else "系统整理目标草案",
        "personalization": personalization,
        "truth_boundary": truth_boundary,
    }
    input_hash = hashlib.sha256(_canonical(snapshot).encode("utf-8")).hexdigest()
    existing = db.query(DBChapterVideoLink).filter_by(
        owner_public_id=actor.public_id, course_id=course.id,
        chapter_id=chapter.id, input_hash=input_hash,
    ).first()
    if existing:
        result = _payload(db, existing, actor)
        result["idempotent"] = True
        return result
    scenes = _scenes(snapshot)
    project = create_project(db, actor=actor, title=f"章节微课：{chapter.title}", course_id=course.id, scenes=scenes)
    quality = {
        "script_schema_valid": len(scenes) == 5,
        "source_bound": bool(sources),
        "knowledge_point_bound": bool(points),
        "objective_origin": objective_origin,
        "personalization_fact_policy_locked": True,
        "render_quality_report_location": "project.tasks[].output.quality_report",
    }
    row = DBChapterVideoLink(
        owner_public_id=actor.public_id, course_id=course.id, chapter_id=chapter.id,
        profile_snapshot_id=profile_row.id if profile_row else None,
        video_project_id=project["id"], input_hash=input_hash,
        source_ref_ids=[item["source_ref_id"] for item in sources],
        knowledge_point_ids=[item.id for item in points], learning_objectives=objectives,
        personalization_snapshot=personalization, source_snapshot=sources,
        quality_snapshot=quality, truth_boundary=truth_boundary,
    )
    db.add(row)
    db.flush()
    result = _payload(db, row, actor)
    result["idempotent"] = False
    return result


def _payload(db: Any, row: DBChapterVideoLink, actor: DBUser) -> dict[str, Any]:
    project = get_project(db, actor=actor, project_id=row.video_project_id)
    return {
        "id": row.id, "course_id": row.course_id, "chapter_id": row.chapter_id,
        "profile_snapshot_id": row.profile_snapshot_id, "video_project_id": row.video_project_id,
        "input_hash": row.input_hash, "source_ref_ids": row.source_ref_ids,
        "knowledge_point_ids": row.knowledge_point_ids, "learning_objectives": row.learning_objectives,
        "personalization": row.personalization_snapshot, "sources": row.source_snapshot,
        "quality": row.quality_snapshot, "truth_boundary": row.truth_boundary,
        "project": project, "created_at": row.created_at.isoformat() if row.created_at else "",
    }


def list_chapter_videos(db: Any, *, actor: DBUser, course_id: str | None = None, chapter_id: str | None = None) -> dict[str, Any]:
    query = db.query(DBChapterVideoLink).filter_by(owner_public_id=actor.public_id)
    if course_id:
        _course(db, actor, course_id)
        query = query.filter_by(course_id=course_id)
    if chapter_id:
        query = query.filter_by(chapter_id=chapter_id)
    rows = query.order_by(DBChapterVideoLink.created_at.desc()).all()
    return {"schema_version": "fc1.chapter-video-list.v1", "items": [_payload(db, row, actor) for row in rows]}


def get_chapter_video(db: Any, *, actor: DBUser, link_id: str) -> dict[str, Any]:
    row = db.get(DBChapterVideoLink, link_id)
    if row is None:
        _fail("chapter_video.link_unknown", "章节视频记录不存在")
    if row.owner_public_id != actor.public_id:
        _fail("chapter_video.link_forbidden", "无权访问该章节视频")
    return _payload(db, row, actor)
