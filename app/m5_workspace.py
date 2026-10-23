"""Restorable, source-bound context for the M5 current-resource tutor."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Literal

from pydantic import Field, model_validator

from app.authorization import ObjectAccess, active_course_role, can_access_object
from app.database import (
    DBAssessmentQuestion,
    DBAssessmentQuestionVersion,
    DBArtifact,
    DBArtifactVersion,
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
    DBCourseMembership,
    DBGenerationTask,
    DBKnowledgePoint,
    DBPathNode,
    DBLearningPath,
    DBProfileSnapshot,
    DBQualityCheck,
    DBReviewPlan,
    DBSourceDocument,
    DBSourceRef,
    DBTaskStep,
    DBTutorContextSession,
)
from app.m1_lifecycle import record_audit
from app.m2_contracts import StrictModel
from app.m5_tasks import M5_TASK_CAPABILITY_PREFIX
from app.m5_assessment_core import learner_option_texts, learner_safe_explanation, learner_safe_prompt
from app.next_core_memory import attach_memory_projection


_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
_TOKEN_RE = re.compile(r"(?i)\b(?:bearer\s+|sk-[A-Za-z0-9_-]{12,}|api[_-]?key\s*[:=]\s*)\S+")


class M5WorkspaceError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise M5WorkspaceError(code, message)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _redact_selected_text(value: str) -> tuple[str, tuple[str, ...]]:
    text = _normalized_text(value)[:1600]
    redactions: list[str] = []
    for name, pattern, replacement in (
        ("email", _EMAIL_RE, "[REDACTED_EMAIL]"),
        ("phone", _PHONE_RE, "[REDACTED_PHONE]"),
        ("credential", _TOKEN_RE, "[REDACTED_CREDENTIAL]"),
    ):
        text, count = pattern.subn(replacement, text)
        if count:
            redactions.append(name)
    return text[:1200], tuple(redactions)


def _object_searchable_text(item: dict[str, Any]) -> str:
    values: list[str] = [str(item.get("title") or ""), str(item.get("subtitle") or "")]

    def collect(value: Any) -> None:
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, dict):
            for child in value.values():
                collect(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                collect(child)

    collect(item.get("render") or {})
    return _normalized_text(" ".join(values))


def _minimal_profile_summary(profile: dict[str, Any] | None) -> dict[str, Any]:
    profile = profile or {}
    mastery = profile.get("mastery")
    return {
        "mastery": round(float(mastery), 4) if isinstance(mastery, (int, float)) else None,
        "weak_knowledge_points": [
            str(item.get("title") or item.get("id") or "")[:120]
            for item in list(profile.get("weak_knowledge_points") or [])[:3]
            if item.get("title") or item.get("id")
        ],
        "has_misconception": bool(profile.get("misconception")),
        "updated_at": profile.get("updated_at"),
    }


def _workspace_course(session: Any, *, current_user: Any, course_id: str) -> DBCourse:
    from course_catalog import course_is_selectable
    course = session.query(DBCourse).filter_by(id=course_id).first()
    if course is None:
        _fail("workspace_course_unknown", "course does not exist")
    role = active_course_role(session, course_id=course.id, user_public_id=current_user.public_id)
    allowed = can_access_object(
        current_user,
        ObjectAccess(
            "course", course.id, owner_public_id=course.owner_public_id,
            course_id=course.id, visibility=course.visibility,
        ),
        action="read",
        course_role=role,
    )
    if not allowed:
        _fail("workspace_course_forbidden", "course is not readable by the current user")
    if not course_is_selectable(session, course):
        _fail("workspace_course_unavailable", "course has no usable learning material")
    return course


def _default_workspace_course(session: Any, *, current_user: Any) -> DBCourse | None:
    from course_catalog import MASTER_COURSE_ID, course_is_selectable

    # The unified course is the deterministic default once it is available;
    # an existing active path still wins because it represents an explicit
    # learner action.
    path = session.query(DBLearningPath).filter(
        DBLearningPath.owner_public_id == current_user.public_id,
        DBLearningPath.course_id.is_not(None),
        DBLearningPath.status.in_(("active", "paused")),
    ).order_by(DBLearningPath.updated_at.desc(), DBLearningPath.id).first()
    if path is not None:
        return _workspace_course(session, current_user=current_user, course_id=path.course_id)

    master_membership = session.query(DBCourseMembership).filter_by(
        course_id=MASTER_COURSE_ID,
        user_public_id=current_user.public_id,
        status="active",
    ).first()
    if master_membership is not None:
        return _workspace_course(session, current_user=current_user, course_id=MASTER_COURSE_ID)

    membership = session.query(DBCourseMembership).filter_by(
        user_public_id=current_user.public_id, status="active",
    ).order_by(DBCourseMembership.created_at, DBCourseMembership.id).first()
    if membership is not None:
        return _workspace_course(session, current_user=current_user, course_id=membership.course_id)

    owned = session.query(DBCourse).filter_by(owner_public_id=current_user.public_id).order_by(
        DBCourse.created_at, DBCourse.id,
    ).first()
    return owned if owned is not None and course_is_selectable(session, owned) else None


def _workspace_path_payload(session: Any, path: DBLearningPath | None) -> dict[str, Any] | None:
    if path is None:
        return None
    nodes = session.query(DBPathNode).filter_by(learning_path_id=path.id).order_by(
        DBPathNode.sequence, DBPathNode.id,
    ).all()
    return {
        "id": path.id,
        "course_id": path.course_id,
        "status": path.status,
        "lock_version": path.lock_version,
        "source_plan_version_id": path.source_plan_version_id,
        "nodes": [{
            "id": item.id,
            "node_key": item.node_key,
            "sequence": item.sequence,
            "node_type": item.node_type,
            "target_object_id": item.target_object_id,
            "title": item.title,
            "status": item.status,
            "prerequisites": item.prerequisites or [],
            "resource_status": item.resource_status,
            "estimate_minutes": [item.estimate_min_minutes, item.estimate_max_minutes],
        } for item in nodes],
    }


def _json_content(value: str) -> tuple[dict[str, Any], str]:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}, "对象内容不是可解析的 JSON，已进入只读错误边界。"
    if not isinstance(parsed, dict):
        return {}, "对象内容不是结构化对象，已进入只读错误边界。"
    return parsed, ""


def _workspace_source_payload(source: DBSourceDocument | None, *, location: str = "") -> dict[str, Any] | None:
    if source is None:
        return None
    return {
        "id": source.id,
        "title": source.title,
        "filename": source.filename,
        "file_format": source.file_format,
        "license": source.license_text,
        "location": location,
        "processing_status": source.processing_status,
    }


_QUALITY_CATEGORIES = {
    "integrity": "structure", "type_schema": "structure", "schema": "structure", "structure": "structure",
    "source_binding": "source", "cross_artifact_binding": "source", "citation": "source", "source": "source",
    "topicality": "topic", "topic": "topic", "relevance": "topic",
    "runnability": "runnable", "execution": "runnable", "code_execution": "runnable", "runtime": "runnable",
}
_QUALITY_LABELS = {
    "structure": "结构检查", "source": "来源检查", "topic": "主题检查", "runnable": "可运行性检查",
}
_QUALITY_RANK = {
    "failed": 4, "manual_required": 3, "pending": 2, "not_recorded": 1,
    "not_applicable": 0, "passed": 0,
}


def _workspace_evidence_panel(
    session: Any,
    *,
    course: DBCourse,
    object_type: str,
    source_ref_ids: list[str],
    expected_chapter_id: str | None,
    artifact_version_id: str | None = None,
    truth_boundary: str = "",
    error_boundary: str = "",
) -> dict[str, Any]:
    """Compose canonical source and quality facts without duplicating governance state."""

    requested_ids = list(dict.fromkeys(str(item) for item in source_ref_ids if item))
    rows = session.query(DBSourceRef, DBSourceDocument).join(
        DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id,
    ).filter(DBSourceRef.id.in_(requested_ids)).all() if requested_ids else []
    rows_by_id = {source_ref.id: (source_ref, source) for source_ref, source in rows}
    expected_chapter = session.get(DBChapter, expected_chapter_id) if expected_chapter_id else None
    sources: list[dict[str, Any]] = []
    invalid_count = 0
    missing_license_count = 0
    for source_ref_id in requested_ids:
        row = rows_by_id.get(source_ref_id)
        if row is None:
            invalid_count += 1
            continue
        source_ref, source = row
        if (
            source.course_id != course.id
            or (expected_chapter_id and source_ref.chapter_id != expected_chapter_id)
            or (expected_chapter is not None and source.id != expected_chapter.source_document_id)
        ):
            invalid_count += 1
            continue
        if not (source.license_text or "").strip():
            missing_license_count += 1
        sources.append({
            "source_ref_id": source_ref.id,
            "document_id": source.id,
            "document_title": source.title,
            "filename": source.filename,
            "file_format": source.file_format,
            "license": source.license_text or "未记录许可信息",
            "location": source_ref.location_label or "未记录文档位置",
            "page_number": source_ref.page_number,
            "char_range": [source_ref.char_start, source_ref.char_end],
            "parser_version": source_ref.parser_version,
            "content_hash": source_ref.content_hash,
            "quote": _normalized_text(source_ref.quote)[:240],
            "processing_status": source.processing_status,
        })

    checks_by_category: dict[str, list[dict[str, Any]]] = {key: [] for key in _QUALITY_LABELS}
    quality_source_ids: list[str] = []
    if artifact_version_id:
        checks = session.query(DBQualityCheck).filter_by(
            artifact_version_id=artifact_version_id,
        ).order_by(DBQualityCheck.created_at.desc(), DBQualityCheck.id.desc()).all()
        seen_types: set[str] = set()
        for check in checks:
            if check.check_type in seen_types:
                continue
            seen_types.add(check.check_type)
            category = _QUALITY_CATEGORIES.get(check.check_type)
            if category is None:
                continue
            checks_by_category[category].append({
                "check_type": check.check_type,
                "status": check.status,
                "score": check.score,
                "checker_version": check.checker_version,
                "recorded_at": check.created_at.isoformat() if check.created_at else None,
            })
            quality_source_ids.extend(str(item) for item in (check.source_ref_ids or []) if item)

    valid_source_ids = {item["source_ref_id"] for item in sources}
    invalid_quality_source_count = len(set(quality_source_ids) - valid_source_ids)
    source_status = "passed" if sources and not invalid_count and not invalid_quality_source_count and not missing_license_count else "failed"
    processing_statuses = {item["processing_status"] for item in sources}
    if not sources:
        structure_status = "not_recorded"
    elif processing_statuses == {"ready"}:
        structure_status = "passed"
    elif processing_statuses & {"failed", "error"}:
        structure_status = "failed"
    else:
        structure_status = "pending"

    derived = {
        "structure": {"status": structure_status, "basis": "canonical_source_processing"},
        "source": {"status": source_status, "basis": "canonical_source_ref_validation"},
    }
    normalized_checks: list[dict[str, Any]] = []
    blockers: list[str] = []
    for category, label in _QUALITY_LABELS.items():
        recorded = checks_by_category[category]
        statuses = [item["status"] for item in recorded]
        if category in derived:
            statuses.append(derived[category]["status"])
        if statuses:
            status = max(statuses, key=lambda item: _QUALITY_RANK.get(item, 2))
        else:
            status = "not_applicable" if category == "runnable" and object_type in {"document", "exercise"} else "not_recorded"
        normalized_checks.append({
            "category": category,
            "label": label,
            "status": status,
            "records": recorded,
            "basis": derived.get(category, {}).get("basis", "quality_check" if recorded else "not_recorded"),
        })
        if status in {"failed", "manual_required"}:
            blockers.append(f"{category}_check_{status}")

    if not requested_ids:
        blockers.append("source_evidence_missing")
    if invalid_count:
        blockers.append("source_reference_invalid")
    if invalid_quality_source_count:
        blockers.append("quality_source_reference_invalid")
    if missing_license_count:
        blockers.append("source_license_missing")
    if error_boundary:
        blockers.append("object_render_error")
    runnable = next(item for item in normalized_checks if item["category"] == "runnable")
    if object_type in {"code", "experiment"} and runnable["status"] != "passed":
        blockers.append("runnability_not_verified")

    boundary = truth_boundary or {
        "document": "展示课程 canonical 来源摘录；只陈述系统已记录的解析与质量事实。",
        "code": "教学代码预览不等同已执行程序，只有正式可运行性检查通过后才视为可运行。",
        "experiment": "展示当前实验产物版本；未记录的质量检查不视为已经通过。",
        "exercise": "题目来自当前课程题库；本面板不等同真人专家或第三方审核。",
    }.get(object_type, "只展示当前系统可核查的来源和质量事实。")
    blockers = sorted(set(blockers))
    return {
        "schema_version": "r2.workspace-evidence-panel.v1",
        "ready": not blockers,
        "readiness": "ready" if not blockers else "blocked",
        "sources": sources,
        "source_summary": "已验证 canonical 来源" if sources and not invalid_count else (
            "来源引用不可验证，已关闭证据状态" if invalid_count else "当前对象未记录可核查来源"
        ),
        "invalid_reference_count": invalid_count + invalid_quality_source_count,
        "missing_license_count": missing_license_count,
        "checks": normalized_checks,
        "blockers": blockers,
        "truth_boundary": boundary,
    }


def _attach_workspace_evidence(session: Any, *, course: DBCourse, item: dict[str, Any]) -> None:
    context = item.get("context") or {}
    version = item.get("version") or {}
    item["evidence_panel"] = _workspace_evidence_panel(
        session,
        course=course,
        object_type=str(item.get("object_type") or ""),
        source_ref_ids=list(context.get("source_ref_ids") or []),
        expected_chapter_id=context.get("chapter_id"),
        artifact_version_id=version.get("id") if item.get("object_type") == "experiment" else None,
        truth_boundary=str(item.get("truth_boundary") or ""),
        error_boundary=str(item.get("error_boundary") or ""),
    )


def _workspace_document_object(
    *,
    course: DBCourse,
    chapter: DBChapter,
    source: DBSourceDocument | None,
    source_ref: DBSourceRef | None,
    subtitle: str,
) -> dict[str, Any]:
    location = source_ref.location_label if source_ref else ""
    excerpt = (source_ref.quote or "").strip() if source_ref else ""
    if not excerpt:
        excerpt = course.description or f"本节围绕“{chapter.title}”展开，正文来源见课程教材。"
    return {
        "id": f"workspace-document:{chapter.id}",
        "object_type": "document",
        "title": chapter.title,
        "subtitle": subtitle,
        "status": source.processing_status if source else "source_missing",
        "source": _workspace_source_payload(source, location=location),
        "version": {
            "id": source.id if source else chapter.id,
            "label": course.version or "当前课程版本",
            "content_hash": source.content_hash if source else "",
        },
        "render": {
            "kind": "document",
            "excerpt": excerpt,
            "section": location or chapter.title,
        },
        "context": {
            "chapter_id": chapter.id,
            "source_ref_ids": [source_ref.id] if source_ref else [],
            "reading_anchor": location or chapter.title,
        },
        "error_boundary": "" if source else "当前章节未绑定可读取的课程来源。",
    }


def _workspace_learning_objects(
    session: Any,
    *,
    current_user: Any,
    course: DBCourse,
    chapters: list[DBChapter],
    source_documents: dict[str, DBSourceDocument],
    path: DBLearningPath | None,
    today: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project canonical facts into the fixed R2 learning-object renderer contract."""

    path_nodes = session.query(DBPathNode).filter_by(learning_path_id=path.id).order_by(
        DBPathNode.sequence, DBPathNode.id,
    ).all() if path is not None else []
    current_node = next((item for item in path_nodes if item.status != "completed"), None)
    current_chapter_id = next((
        item.get("target_object_id") for item in today if item.get("node_type") == "chapter"
    ), None)
    if not current_chapter_id and current_node is not None and current_node.node_type == "chapter":
        current_chapter_id = current_node.target_object_id
    current_chapter = next((item for item in chapters if item.id == current_chapter_id), None)
    current_chapter = current_chapter or (chapters[0] if chapters else None)
    source = source_documents.get(current_chapter.source_document_id) if current_chapter else None
    source_ref = session.query(DBSourceRef).filter_by(
        chapter_id=current_chapter.id,
    ).order_by(DBSourceRef.location_index, DBSourceRef.id).first() if current_chapter else None
    location = source_ref.location_label if source_ref else ""
    source_payload = _workspace_source_payload(source, location=location)
    object_context = {
        "chapter_id": current_chapter.id if current_chapter else None,
        "source_ref_ids": [source_ref.id] if source_ref else [],
        "reading_anchor": location or (current_chapter.title if current_chapter else ""),
    }
    objects: list[dict[str, Any]] = []

    if current_chapter is not None:
        objects.append(_workspace_document_object(
            course=course,
            chapter=current_chapter,
            source=source,
            source_ref=source_ref,
            subtitle="当前章节教材",
        ))

        code = "\n".join((
            "def hybrid_search(query, keyword_weight=0.5, vector_weight=0.5, top_k=3):",
            "    candidates = merge_candidates(query, top_k=top_k)",
            "    scored = rerank(candidates, keyword_weight, vector_weight)",
            "    return enforce_access_scope(scored[:top_k])",
        ))
        objects.append({
            "id": f"workspace-code:{current_chapter.id}",
            "object_type": "code",
            "title": "混合检索最小代码骨架",
            "subtitle": f"配套章节：{current_chapter.title}",
            "status": "derived_preview",
            "source": source_payload,
            "version": {
                "id": f"{current_chapter.id}:code-preview-v1",
                "label": "教学骨架 v1",
                "content_hash": hashlib.sha256(code.encode("utf-8")).hexdigest(),
            },
            "render": {"kind": "code", "language": "python", "content": code},
            "context": object_context,
            "truth_boundary": "基于当前课程章节形成的只读教学代码骨架，未执行且不是学生提交。",
            "error_boundary": "",
        })

    artifacts = session.query(DBArtifact).filter(
        DBArtifact.owner_public_id == current_user.public_id,
        DBArtifact.course_id == course.id,
        DBArtifact.archived_at.is_(None),
        DBArtifact.artifact_type.in_(("interactive_lab", "interactive_lab_instance")),
    ).order_by(DBArtifact.updated_at.desc(), DBArtifact.id).all()
    for artifact in artifacts[:3]:
        version = session.query(DBArtifactVersion).filter_by(id=artifact.current_version_id).first()
        payload, parse_error = _json_content(version.content) if version else ({}, "实验当前版本不存在。")
        objects.append({
            "id": artifact.id,
            "object_type": "experiment",
            "title": artifact.title,
            "subtitle": "交互实验",
            "status": payload.get("status") or artifact.status,
            "source": source_payload,
            "version": {
                "id": version.id if version else "",
                "label": f"v{version.version_number}" if version else "版本缺失",
                "content_hash": version.content_hash if version else "",
            },
            "render": {
                "kind": "experiment",
                "template": payload.get("template_id") or artifact.title or "课程交互实验",
                "parameters": payload.get("parameters") or {},
                "metrics": payload.get("metrics") or {},
                "feedback": payload.get("feedback") or [],
            },
            "context": object_context,
            "error_boundary": parse_error,
        })

    questions = session.query(DBAssessmentQuestion, DBAssessmentQuestionVersion).join(
        DBAssessmentQuestionVersion,
        DBAssessmentQuestionVersion.id == DBAssessmentQuestion.current_version_id,
    ).filter(
        DBAssessmentQuestion.course_id == course.id,
        DBAssessmentQuestion.status == "approved",
    ).order_by(DBAssessmentQuestion.updated_at.desc(), DBAssessmentQuestion.id).limit(5).all()
    for question, version in questions:
        question_source_ids = list(version.source_ref_ids or []) or list(object_context["source_ref_ids"])
        question_source_ref = session.query(DBSourceRef).filter(
            DBSourceRef.id.in_(question_source_ids),
        ).order_by(DBSourceRef.location_index, DBSourceRef.id).first() if question_source_ids else None
        question_source = source_documents.get(question_source_ref.source_document_id) if question_source_ref else source
        question_location = question_source_ref.location_label if question_source_ref else location
        question_context = {
            **object_context,
            "chapter_id": question_source_ref.chapter_id if question_source_ref else object_context["chapter_id"],
            "source_ref_ids": question_source_ids,
            "reading_anchor": question_location or object_context["reading_anchor"],
        }
        objects.append({
            "id": version.id,
            "object_type": "exercise",
            "title": learner_safe_prompt(version.prompt),
            "subtitle": "课程练习",
            "status": question.status,
            "source": _workspace_source_payload(question_source, location=question_location),
            "version": {
                "id": version.id,
                "label": f"v{version.version_number}",
                "content_hash": version.content_hash,
            },
            "render": {
                "kind": "exercise",
                "question_version_id": version.id,
                "question_type": question.question_type,
                "prompt": learner_safe_prompt(version.prompt),
                "options": learner_option_texts(version, question),
                "bloom_level": version.bloom_level,
                "explanation": learner_safe_explanation(
                    version.explanation,
                    prompt=version.prompt,
                    options=version.options,
                    answer_key=version.answer_key,
                    question_type=question.question_type,
                ),
                "misconception_tags": list(version.misconception_tags or []),
            },
            "context": question_context,
            "error_boundary": "",
        })
    for item in objects:
        _attach_workspace_evidence(session, course=course, item=item)
    return objects


def _workspace_artifact_payload(
    artifact: DBArtifact,
    version: DBArtifactVersion | None,
    chapters_by_id: dict[str, DBChapter],
    source_objects_by_chapter: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    metadata = dict(version.metadata_json or {}) if version is not None else {}
    chapter = chapters_by_id.get(str(metadata.get("chapter_id") or ""))
    if chapter is not None:
        source = {
            "kind": "chapter",
            "label": chapter.title,
            "chapter_id": chapter.id,
            "workspace_object_id": f"workspace-document:{chapter.id}",
            "learning_object": source_objects_by_chapter.get(chapter.id),
        }
    elif artifact.creating_task_id:
        source = {
            "kind": "generation_task",
            "label": "生成任务",
            "task_id": artifact.creating_task_id,
        }
    else:
        source = {
            "kind": "unknown",
            "label": "未记录可定位来源" if version is not None else "当前版本不可用",
        }
    return {
        "id": artifact.id,
        "title": artifact.title,
        "artifact_type": artifact.artifact_type,
        "status": artifact.status,
        "current_version_id": artifact.current_version_id,
        "current_version": ({
            "id": version.id,
            "number": version.version_number,
            "content_format": version.content_format,
            "created_at": version.created_at.isoformat() if version.created_at else None,
        } if version is not None else None),
        "source": source,
        "creating_task_id": artifact.creating_task_id,
        "updated_at": artifact.updated_at.isoformat() if artifact.updated_at else None,
    }


def _workspace_restore_payload(
    session: Any,
    *,
    current_user: Any,
    course: DBCourse,
    learning_objects: list[dict[str, Any]],
) -> dict[str, Any]:
    object_ids = {str(item.get("id") or "") for item in learning_objects}
    context = None
    context_rows = session.query(DBTutorContextSession).filter_by(
        owner_public_id=current_user.public_id,
        course_id=course.id,
        status="active",
        primary_object_type="workspace_object",
    ).order_by(
        DBTutorContextSession.last_used_at.desc(),
        DBTutorContextSession.updated_at.desc(),
        DBTutorContextSession.id.desc(),
    ).limit(20).all()
    for row in context_rows:
        snapshot = row.context_snapshot or {}
        current_object = snapshot.get("current_object") or {}
        object_id = str(current_object.get("id") or row.primary_object_id or "")
        if object_id not in object_ids:
            continue
        context = {
            "context_session_id": row.id,
            "object_id": object_id,
            "object_type": current_object.get("object_type") or "",
            "reading_position": snapshot.get("reading_position") or {},
            "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        }
        break

    tasks = session.query(DBGenerationTask).filter(
        DBGenerationTask.owner_public_id == current_user.public_id,
        DBGenerationTask.course_id == course.id,
        DBGenerationTask.capability.like(f"{M5_TASK_CAPABILITY_PREFIX}%"),
    ).order_by(DBGenerationTask.updated_at.desc(), DBGenerationTask.id.desc()).limit(8).all()
    task_ids = [item.id for item in tasks]
    steps = session.query(DBTaskStep).filter(DBTaskStep.task_id.in_(task_ids)).order_by(
        DBTaskStep.task_id, DBTaskStep.sequence, DBTaskStep.attempt,
    ).all() if task_ids else []
    latest_steps: dict[str, dict[int, DBTaskStep]] = {}
    for step in steps:
        latest_steps.setdefault(step.task_id, {})[step.sequence] = step

    task_items = []
    for task in tasks:
        task_steps = latest_steps.get(task.id, {})
        retryable_steps = sorted(
            sequence for sequence, step in task_steps.items()
            if task.status == "running" and step.status == "failed"
        )
        task_items.append({
            "id": task.id,
            "capability": task.capability,
            "status": task.status,
            "progress": task.progress,
            "failure_code": task.failure_code,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            "can_cancel": task.status in {"queued", "running"},
            "retryable_step_sequences": retryable_steps,
        })
    current_task = next(
        (item for item in task_items if item["status"] in {"queued", "running"}),
        task_items[0] if task_items else None,
    )
    return {
        "context": context,
        "task": current_task,
        "recent_tasks": task_items,
    }


def workspace_overview(
    session: Any, *, current_user: Any, course_id: str | None = None,
) -> dict[str, Any]:
    """Compose the existing learning facts needed for the workspace first screen."""

    course = (
        _workspace_course(session, current_user=current_user, course_id=course_id)
        if course_id else _default_workspace_course(session, current_user=current_user)
    )
    if course is None:
        return {
            "schema_version": "r2.workspace-overview.v1",
            "state": "course_required",
            "course": None,
            "chapters": [],
            "current_path": None,
            "today_tasks": [],
            "profile": None,
            "running_tasks": [],
            "recent_artifacts": [],
            "learning_objects": [],
            "restore": {"context": None, "task": None, "recent_tasks": []},
            "review": {"due_count": 0, "items": []},
            "next_action": {"label": "选择课程", "route": "/knowledge"},
        }

    chapters = session.query(DBChapter).filter_by(course_id=course.id).order_by(
        DBChapter.position, DBChapter.id,
    ).all()
    chapter_ids = [item.id for item in chapters]
    source_document_ids = {item.source_document_id for item in chapters}
    source_documents = {
        item.id: item for item in session.query(DBSourceDocument).filter(
            DBSourceDocument.id.in_(source_document_ids),
        ).all()
    } if source_document_ids else {}
    knowledge_point_ids = {
        row[0] for row in session.query(DBChapterKnowledgePoint.knowledge_point_id).filter(
            DBChapterKnowledgePoint.chapter_id.in_(chapter_ids),
        ).all()
    } if chapter_ids else set()
    knowledge_point_titles = {
        row.id: row.title for row in session.query(DBKnowledgePoint).filter(
            DBKnowledgePoint.id.in_(knowledge_point_ids),
        ).all()
    } if knowledge_point_ids else {}

    path = session.query(DBLearningPath).filter(
        DBLearningPath.owner_public_id == current_user.public_id,
        DBLearningPath.course_id == course.id,
        DBLearningPath.status.in_(("active", "paused")),
    ).order_by(DBLearningPath.updated_at.desc(), DBLearningPath.id).first()

    from app.m5_learning import today_work_items

    # The default workspace keeps a single selected course for the reader,
    # while the Today view also needs a read-only projection of every course
    # with an active learning path.  Do not create or mutate a second
    # learning-state source here.
    active_paths_query = session.query(DBLearningPath).filter(
        DBLearningPath.owner_public_id == current_user.public_id,
        DBLearningPath.status == "active",
        DBLearningPath.course_id.is_not(None),
    )
    if course_id:
        active_paths_query = active_paths_query.filter(DBLearningPath.course_id == course_id)
    active_paths = active_paths_query.order_by(
        DBLearningPath.course_id, DBLearningPath.updated_at.desc(), DBLearningPath.id.desc(),
    ).all()
    course_summaries: list[dict[str, Any]] = []
    seen_course_ids: set[str] = set()
    for active_path in active_paths:
        if active_path.course_id in seen_course_ids:
            continue
        course_row = session.query(DBCourse).filter_by(id=active_path.course_id).first()
        if course_row is None:
            continue
        from course_catalog import course_is_selectable
        if not course_is_selectable(session, course_row):
            continue
        course_nodes = session.query(DBPathNode).filter_by(
            learning_path_id=active_path.id,
        ).order_by(DBPathNode.sequence, DBPathNode.id).all()
        seen_course_ids.add(course_row.id)
        course_summaries.append({
            "id": course_row.id,
            "title": course_row.title,
            "version": course_row.version,
            "subject": course_row.subject,
            "path_id": active_path.id,
            "path_status": active_path.status,
            "completed_nodes": sum(1 for node in course_nodes if node.status == "completed"),
            "total_nodes": len(course_nodes),
        })

    today = list(today_work_items(
        session,
        owner_public_id=current_user.public_id,
        course_id=course.id if course_id else None,
        limit=3 if course_id else max(3, len(active_paths) * 20),
    ))

    profile = None
    from app.profile_onboarding import profile_influence_summary
    snapshots = session.query(DBProfileSnapshot).filter_by(
        owner_public_id=current_user.public_id,
    ).order_by(DBProfileSnapshot.created_at.desc(), DBProfileSnapshot.id.desc()).all()
    for row in snapshots:
        snapshot = row.snapshot or {}
        if snapshot.get("course_id") not in {None, course.id}:
            continue
        weak_ids = list(snapshot.get("weak_knowledge_point_ids") or [])
        profile = {
            "snapshot_id": row.id,
            "profile_version": row.profile_version,
            "profile_influence": profile_influence_summary(row),
            "mastery": snapshot.get("mastery"),
            "participated": snapshot.get("participated"),
            "attention": snapshot.get("attention"),
            "weak_knowledge_points": [
                {"id": item, "title": knowledge_point_titles.get(item, item)} for item in weak_ids
            ],
            "misconception": snapshot.get("misconception"),
            "updated_at": row.created_at.isoformat() if row.created_at else None,
        }
        break

    running_tasks = session.query(DBGenerationTask).filter(
        DBGenerationTask.owner_public_id == current_user.public_id,
        DBGenerationTask.course_id == course.id,
        DBGenerationTask.capability.like(f"{M5_TASK_CAPABILITY_PREFIX}%"),
        DBGenerationTask.status.in_(("queued", "running")),
    ).order_by(DBGenerationTask.updated_at.desc(), DBGenerationTask.id).limit(5).all()
    artifacts = session.query(DBArtifact).filter(
        DBArtifact.owner_public_id == current_user.public_id,
        DBArtifact.course_id == course.id,
        DBArtifact.archived_at.is_(None),
    ).order_by(DBArtifact.updated_at.desc(), DBArtifact.id).limit(6).all()
    artifact_version_ids = [item.current_version_id for item in artifacts if item.current_version_id]
    artifact_versions = {
        item.id: item for item in session.query(DBArtifactVersion).filter(
            DBArtifactVersion.id.in_(artifact_version_ids),
        ).all()
    } if artifact_version_ids else {}
    chapters_by_id = {item.id: item for item in chapters}
    artifact_source_objects: dict[str, dict[str, Any]] = {}
    for version in artifact_versions.values():
        chapter_id = str((version.metadata_json or {}).get("chapter_id") or "")
        chapter = chapters_by_id.get(chapter_id)
        if chapter is None or chapter.id in artifact_source_objects:
            continue
        source_ref = session.query(DBSourceRef).filter_by(chapter_id=chapter.id).order_by(
            DBSourceRef.location_index, DBSourceRef.id,
        ).first()
        artifact_source_objects[chapter.id] = _workspace_document_object(
            course=course,
            chapter=chapter,
            source=source_documents.get(chapter.source_document_id),
            source_ref=source_ref,
            subtitle="产物来源章节",
        )
    reviews = session.query(DBReviewPlan).filter_by(student_id=current_user.username).order_by(
        DBReviewPlan.priority, DBReviewPlan.next_review_at, DBReviewPlan.id,
    ).all()
    due_reviews = [
        row for row in reviews
        if row.concept in knowledge_point_ids
        and (row.next_review_at is None or row.next_review_at <= _now())
    ]
    review_items = due_reviews[:6]

    state = "ready" if path is not None else "path_required"
    if today:
        next_action = {"label": "继续今日任务", "route": f"/workspace?node_id={today[0]['node_id']}"}
    elif path is None:
        next_action = {"label": "创建学习路径", "route": "/learning-path"}
    else:
        next_action = {"label": "查看学习路径", "route": "/learning-path"}

    learning_objects = _workspace_learning_objects(
        session,
        current_user=current_user,
        course=course,
        chapters=chapters,
        source_documents=source_documents,
        path=path,
        today=today,
    )
    restore = _workspace_restore_payload(
        session,
        current_user=current_user,
        course=course,
        learning_objects=learning_objects,
    )

    return {
        "schema_version": "r2.workspace-overview.v1",
        "state": state,
        "course": {
            "id": course.id,
            "title": course.title,
            "version": course.version,
            "subject": course.subject,
            "description": course.description,
            "license": course.license_text,
            "visibility": course.visibility,
            "status": course.status,
        },
        "courses": course_summaries or [{
            "id": course.id,
            "title": course.title,
            "version": course.version,
            "subject": course.subject,
            "path_id": path.id if path else None,
            "path_status": path.status if path else None,
            "completed_nodes": sum(1 for node in (session.query(DBPathNode).filter_by(learning_path_id=path.id).all() if path else []) if node.status == "completed"),
            "total_nodes": session.query(DBPathNode).filter_by(learning_path_id=path.id).count() if path else 0,
        }],
        "chapters": [{
            "id": item.id,
            "title": item.title,
            "position": item.position,
            "parent_id": item.parent_id,
            "source_document_id": item.source_document_id,
            "source": ({
                "id": source_documents[item.source_document_id].id,
                "title": source_documents[item.source_document_id].title,
                "filename": source_documents[item.source_document_id].filename,
                "file_format": source_documents[item.source_document_id].file_format,
                "license": source_documents[item.source_document_id].license_text,
                "processing_status": source_documents[item.source_document_id].processing_status,
            } if item.source_document_id in source_documents else None),
        } for item in chapters],
        "current_path": _workspace_path_payload(session, path),
        "today_tasks": today,
        "profile": profile,
        "running_tasks": [{
            "id": item.id,
            "capability": item.capability,
            "status": item.status,
            "progress": item.progress,
            "failure_code": item.failure_code,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        } for item in running_tasks],
        "recent_artifacts": [
            _workspace_artifact_payload(
                item,
                artifact_versions.get(item.current_version_id),
                chapters_by_id,
                artifact_source_objects,
            )
            for item in artifacts
        ],
        "learning_objects": learning_objects,
        "restore": restore,
        "review": {
            "due_count": len(due_reviews),
            "items": [{
                "id": item.id,
                "knowledge_point_id": item.concept,
                "title": knowledge_point_titles.get(item.concept, item.concept),
                "mastery": item.mastery,
                "interval_days": item.interval_days,
                "next_review_at": item.next_review_at.isoformat() if item.next_review_at else None,
                "priority": item.priority,
            } for item in review_items],
        },
        "next_action": next_action,
    }


class TutorReadingPosition(StrictModel):
    kind: Literal["section", "line", "question", "object", "video"] = "object"
    label: str = Field(default="", max_length=240)
    line_number: int | None = Field(default=None, ge=1)
    char_offset: int | None = Field(default=None, ge=0)
    timestamp_seconds: float | None = Field(default=None, ge=0)


class TutorContextSpec(StrictModel):
    schema_version: Literal["m5.tutor-context.v1"] = "m5.tutor-context.v1"
    idempotency_key: str = Field(min_length=8, max_length=128)
    course_id: str | None = Field(default=None, max_length=128)
    context_mode: Literal["current_resource", "current_course", "personal_resources", "external_allowed"]
    primary_object_type: Literal["chapter", "artifact", "source_ref", "path_node", "workspace_object"]
    primary_object_id: str = Field(min_length=1, max_length=64)
    selected_source_ref_ids: tuple[str, ...] = Field(default=(), max_length=8)
    selected_text: str = Field(default="", max_length=2000)
    reading_position: TutorReadingPosition = Field(default_factory=TutorReadingPosition)
    formula_latex: str = Field(default="", max_length=4000)
    video_timestamp_seconds: float | None = Field(default=None, ge=0)
    teaching_style: Literal["progressive", "socratic", "case_based", "close_reading", "practice_along"] = "progressive"
    explanation_depth: Literal["concise", "standard", "deep"] = "standard"
    guidance_mode: Literal["socratic", "direct"] = "socratic"

    @model_validator(mode="after")
    def valid_scope(self) -> "TutorContextSpec":
        if self.context_mode in {"current_resource", "current_course"} and not self.course_id:
            raise ValueError("resource and course context modes require course_id")
        if len(set(self.selected_source_ref_ids)) != len(self.selected_source_ref_ids):
            raise ValueError("selected_source_ref_ids must be unique")
        return self


class TutorPromptPreflight(StrictModel):
    question: str = Field(min_length=1, max_length=12000)
    intent: Literal["explain", "example", "challenge", "quiz", "note", "compare"] = "explain"
    comparison_context_ids: tuple[str, ...] = Field(default=(), max_length=4)


def _course(session: Any, *, current_user: Any, course_id: str | None) -> DBCourse | None:
    from course_catalog import course_is_selectable
    if not course_id:
        return None
    course = session.query(DBCourse).filter_by(id=course_id).first()
    if course is None:
        _fail("tutor_course_unknown", "course does not exist")
    role = active_course_role(session, course_id=course.id, user_public_id=current_user.public_id)
    allowed = can_access_object(
        current_user,
        ObjectAccess(
            "course", course.id, owner_public_id=course.owner_public_id,
            course_id=course.id, visibility=course.visibility,
        ),
        action="read",
        course_role=role,
    )
    if not allowed:
        _fail("tutor_course_forbidden", "course is not readable by the current user")
    if not course_is_selectable(session, course):
        _fail("tutor_course_unavailable", "course has no usable learning material")
    return course


def _source_snapshot(session: Any, *, source_ref_id: str, course_id: str | None) -> dict[str, Any]:
    row = session.query(DBSourceRef, DBSourceDocument).join(
        DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id,
    ).filter(DBSourceRef.id == source_ref_id).first()
    if row is None or (course_id and row[1].course_id != course_id):
        _fail("tutor_source_ref_invalid", "source reference is outside the selected course")
    source_ref, source = row
    return {
        "source_ref_id": source_ref.id,
        "source_document_id": source.id,
        "chapter_id": source_ref.chapter_id,
        "page_number": source_ref.page_number,
        "char_range": [source_ref.char_start, source_ref.char_end],
        "image_region": source_ref.image_region,
        "quote": source_ref.quote or "",
        "content_hash": source_ref.content_hash,
        "parser_version": source_ref.parser_version,
    }


def resolve_tutor_context(
    session: Any, *, current_user: Any, spec: TutorContextSpec,
) -> dict[str, Any]:
    course = _course(session, current_user=current_user, course_id=spec.course_id)
    title = ""
    resolved_course_id = spec.course_id
    workspace_object: dict[str, Any] | None = None
    if spec.primary_object_type == "chapter":
        row = session.query(DBChapter).filter_by(id=spec.primary_object_id).first()
        if row is None or (resolved_course_id and row.course_id != resolved_course_id):
            _fail("tutor_chapter_invalid", "chapter is outside the selected course")
        resolved_course_id = row.course_id
        title = row.title
    elif spec.primary_object_type == "artifact":
        row = session.query(DBArtifact).filter_by(id=spec.primary_object_id).first()
        if row is None or row.owner_public_id != current_user.public_id:
            _fail("tutor_artifact_forbidden", "artifact is unavailable to the current user")
        if resolved_course_id and row.course_id not in {None, resolved_course_id}:
            _fail("tutor_artifact_invalid", "artifact is outside the selected course")
        resolved_course_id = resolved_course_id or row.course_id
        title = row.title
    elif spec.primary_object_type == "source_ref":
        source = _source_snapshot(session, source_ref_id=spec.primary_object_id, course_id=resolved_course_id)
        resolved_course_id = resolved_course_id or session.query(DBSourceDocument).filter_by(
            id=source["source_document_id"],
        ).one().course_id
        title = source["quote"][:120] or source["source_document_id"]
    elif spec.primary_object_type == "path_node":
        row = session.query(DBPathNode, DBLearningPath).join(
            DBLearningPath, DBLearningPath.id == DBPathNode.learning_path_id,
        ).filter(DBPathNode.id == spec.primary_object_id).first()
        if row is None or row[1].owner_public_id != current_user.public_id:
            _fail("tutor_path_node_forbidden", "path node is unavailable to the current user")
        if resolved_course_id and row[1].course_id != resolved_course_id:
            _fail("tutor_path_node_invalid", "path node is outside the selected course")
        resolved_course_id = resolved_course_id or row[1].course_id
        title = row[0].title
    else:
        if not resolved_course_id:
            _fail("tutor_workspace_course_required", "workspace context requires course_id")
        overview = workspace_overview(
            session, current_user=current_user, course_id=resolved_course_id,
        )
        workspace_object = next((
            item for item in overview.get("learning_objects", [])
            if item.get("id") == spec.primary_object_id
        ), None)
        if workspace_object is None:
            _fail("tutor_workspace_object_forbidden", "workspace object is unavailable to the current user")
        title = str(workspace_object.get("title") or "")

        allowed_refs = tuple((workspace_object.get("context") or {}).get("source_ref_ids") or ())
        if any(item not in allowed_refs for item in spec.selected_source_ref_ids):
            _fail("tutor_workspace_source_invalid", "source reference is outside the current workspace object")

        selected_raw = _normalized_text(spec.selected_text)
        if selected_raw and selected_raw not in _object_searchable_text(workspace_object):
            _fail("tutor_selected_text_invalid", "selected text is not part of the current workspace object")

    requested_source_ids = list(spec.selected_source_ref_ids)
    if workspace_object is not None:
        for source_ref_id in (workspace_object.get("context") or {}).get("source_ref_ids") or []:
            if source_ref_id not in requested_source_ids:
                requested_source_ids.append(source_ref_id)
    sources = [
        _source_snapshot(session, source_ref_id=item, course_id=resolved_course_id)
        for item in requested_source_ids[:8]
    ]
    if spec.primary_object_type == "source_ref" and spec.primary_object_id not in spec.selected_source_ref_ids:
        sources.insert(0, _source_snapshot(
            session, source_ref_id=spec.primary_object_id, course_id=resolved_course_id,
        ))
    selected_text, redactions = _redact_selected_text(spec.selected_text)
    result = {
        "schema_version": spec.schema_version,
        "course_id": resolved_course_id,
        "course_title": course.title if course else "",
        "context_mode": spec.context_mode,
        "primary": {
            "object_type": spec.primary_object_type,
            "object_id": spec.primary_object_id,
            "title": title,
        },
        "sources": sources,
        "reading_position": spec.reading_position.model_dump(mode="json"),
        "selected_text": selected_text,
        "formula_latex": spec.formula_latex,
        "video_timestamp_seconds": spec.video_timestamp_seconds,
        "retrieval_scope": {
            "current_resource_only": spec.context_mode == "current_resource",
            "course_allowed": spec.context_mode in {"current_course", "external_allowed"},
            "personal_resources_allowed": spec.context_mode in {"personal_resources", "external_allowed"},
            "external_allowed": spec.context_mode == "external_allowed",
        },
        "data_minimization": {
            "selected_text_limit": 1200,
            "redactions": list(redactions),
            "full_profile_included": False,
            "other_owner_resources_included": False,
        },
    }
    if workspace_object is not None:
        overview_profile = overview.get("profile")
        result["current_object"] = {
            "id": workspace_object.get("id"),
            "object_type": workspace_object.get("object_type"),
            "title": workspace_object.get("title"),
            "chapter_id": (workspace_object.get("context") or {}).get("chapter_id"),
            "source": workspace_object.get("source"),
            "version": workspace_object.get("version"),
        }
        result["profile_summary"] = _minimal_profile_summary(overview_profile)
    return result


def create_tutor_context(
    session: Any, *, current_user: Any, spec: TutorContextSpec,
) -> tuple[DBTutorContextSession, bool]:
    snapshot = resolve_tutor_context(session, current_user=current_user, spec=spec)
    if spec.primary_object_type != "workspace_object":
        snapshot = attach_memory_projection(
            session, owner_public_id=current_user.public_id, snapshot=snapshot,
        )
    existing = session.query(DBTutorContextSession).filter_by(
        owner_public_id=current_user.public_id, idempotency_key=spec.idempotency_key,
    ).first()
    requested = {
        "snapshot": snapshot,
        "teaching_style": spec.teaching_style,
        "explanation_depth": spec.explanation_depth,
        "guidance_mode": spec.guidance_mode,
    }
    if existing is not None:
        persisted = {
            "snapshot": existing.context_snapshot,
            "teaching_style": existing.teaching_style,
            "explanation_depth": existing.explanation_depth,
            "guidance_mode": existing.guidance_mode,
        }
        if _hash(requested) != _hash(persisted):
            _fail("tutor_context_idempotency_conflict", "idempotency key is bound to another tutor context")
        existing.last_used_at = _now()
        return existing, False
    row = DBTutorContextSession(
        owner_public_id=current_user.public_id,
        course_id=snapshot["course_id"],
        idempotency_key=spec.idempotency_key,
        context_mode=spec.context_mode,
        primary_object_type=spec.primary_object_type,
        primary_object_id=spec.primary_object_id,
        context_snapshot=snapshot,
        teaching_style=spec.teaching_style,
        explanation_depth=spec.explanation_depth,
        guidance_mode=spec.guidance_mode,
    )
    session.add(row)
    session.flush()
    record_audit(
        session, actor_public_id=current_user.public_id, action="tutor_context.created",
        object_type="tutor_context", object_id=row.id,
        metadata={"course_id": row.course_id, "primary_object_type": row.primary_object_type},
    )
    session.flush()
    return row, True


def tutor_context_payload(row: DBTutorContextSession) -> dict[str, Any]:
    return {
        "id": row.id,
        "course_id": row.course_id,
        "context_mode": row.context_mode,
        "primary_object_type": row.primary_object_type,
        "primary_object_id": row.primary_object_id,
        "context": row.context_snapshot,
        "teaching_style": row.teaching_style,
        "explanation_depth": row.explanation_depth,
        "guidance_mode": row.guidance_mode,
        "status": row.status,
        "lock_version": row.lock_version,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
    }


def archive_tutor_context(
    session: Any, *, row: DBTutorContextSession, owner_public_id: str, expected_lock_version: int,
) -> DBTutorContextSession:
    if row.owner_public_id != owner_public_id:
        _fail("tutor_context_forbidden", "tutor context belongs to another owner")
    if row.lock_version != expected_lock_version:
        _fail("tutor_context_version_conflict", "tutor context lock version changed")
    if row.status == "archived":
        return row
    row.status = "archived"
    row.archived_at = _now()
    row.lock_version += 1
    record_audit(
        session, actor_public_id=owner_public_id, action="tutor_context.archived",
        object_type="tutor_context", object_id=row.id,
    )
    session.flush()
    return row


def tutor_prompt_envelope(
    session: Any, *, row: DBTutorContextSession, owner_public_id: str,
    request: TutorPromptPreflight,
) -> dict[str, Any]:
    if row.owner_public_id != owner_public_id:
        _fail("tutor_context_forbidden", "tutor context belongs to another owner")
    if row.status != "active":
        _fail("tutor_context_archived", "archived tutor context cannot accept questions")
    comparisons = []
    for context_id in request.comparison_context_ids:
        comparison = session.query(DBTutorContextSession).filter_by(id=context_id).first()
        if comparison is None or comparison.owner_public_id != owner_public_id or comparison.status != "active":
            _fail("tutor_comparison_invalid", "comparison context is unavailable")
        comparisons.append(comparison.context_snapshot)
    row.last_used_at = _now()
    session.flush()
    return {
        "schema_version": "m5.tutor-request.v1",
        "context_session_id": row.id,
        "question": request.question,
        "intent": request.intent,
        "context": row.context_snapshot,
        "comparison_contexts": comparisons,
        "teaching": {
            "style": row.teaching_style,
            "depth": row.explanation_depth,
            "guidance_mode": row.guidance_mode,
        },
        "generation_started": False,
    }
