"""Domain resolution for the unified course and learning-object context."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Any

from fastapi import HTTPException

from app.authorization import require_course_access
from app.database import (
    DBAssessmentAttempt,
    DBArtifact,
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
    DBGenerationTask,
    DBKnowledgePoint,
    DBLearningPath,
    DBPathNode,
    DBSourceDocument,
    DBSourceRef,
    DBUser,
)
from app.schemas import ContextObjectSummary, ContextRef, ContextResolution


class ContextResolutionError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        field: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.field = field

    def detail(self) -> dict[str, str]:
        value = {"code": self.code, "message": str(self)}
        if self.field:
            value["field"] = self.field
        return value


def _error(
    code: str, message: str, *, status_code: int, field: str | None = None
) -> None:
    raise ContextResolutionError(code, message, status_code=status_code, field=field)


def _version_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def _summary(
    *,
    object_type: str,
    object_id: str,
    title: str,
    course_id: str | None = None,
    owner_user_id: str | None = None,
    version: Any = None,
    status: Any = None,
) -> ContextObjectSummary:
    return ContextObjectSummary(
        object_type=object_type,
        id=object_id,
        title=title,
        course_id=course_id,
        owner_user_id=owner_user_id,
        version=_version_text(version),
        status=_version_text(status),
    )


def _assert_owner(owner_public_id: str | None, user: DBUser, field: str) -> None:
    if owner_public_id and owner_public_id != user.public_id:
        _error(
            "context_cross_user",
            "链接中的学习对象属于其他用户，不能在当前账号中打开",
            status_code=403,
            field=field,
        )


def _assert_course(actual: str | None, expected: str, field: str) -> None:
    if actual and actual != expected:
        _error(
            "context_course_mismatch",
            "链接中的对象不属于当前课程，请重新选择课程或从原页面进入",
            status_code=409,
            field=field,
        )


def _context_version(material: dict[str, Any]) -> str:
    canonical = json.dumps(
        material, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return "ctx-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def resolve_context_ref(
    session: Any, *, user: DBUser, context: ContextRef
) -> ContextResolution:
    """Resolve every supplied ID against one user, course and version boundary."""
    if context.user_id and context.user_id != user.public_id:
        _error(
            "context_cross_user",
            "链接中的用户身份与当前登录账号不一致",
            status_code=403,
            field="userId",
        )
    if not context.course_id:
        _error(
            "context_course_required",
            "当前页面需要先选择课程",
            status_code=422,
            field="courseId",
        )

    course = session.query(DBCourse).filter_by(id=context.course_id).first()
    if course is None:
        _error(
            "context_object_not_found",
            "课程不存在或已被移除",
            status_code=404,
            field="courseId",
        )
    from course_catalog import course_is_selectable
    if not course_is_selectable(session, course):
        _error(
            "context_course_unavailable",
            "这门课程当前没有可用学习资料，或已停止发布",
            status_code=409,
            field="courseId",
        )
    try:
        require_course_access(
            session,
            user,
            course_id=course.id,
            action="read",
            visibility=course.visibility,
        )
    except HTTPException as exc:
        _error(
            "context_forbidden",
            "当前账号没有访问这门课程的权限",
            status_code=403,
            field="courseId",
        )

    course_summary = _summary(
        object_type="course",
        object_id=course.id,
        title=course.title,
        course_id=course.id,
        owner_user_id=course.owner_public_id,
        version=course.version,
        status=course.status,
    )
    chapter_summary = None
    knowledge_summary = None
    task_summary = None
    resource_summary = None
    source_summary = None
    attempt_summary = None
    material: dict[str, Any] = {
        "userId": user.public_id,
        "course": {
            "id": course.id,
            "version": course.version,
            "manifestVersion": course.manifest_version,
            "status": course.status,
        },
    }

    context_path = None
    if context.path_id:
        context_path = session.query(DBLearningPath).filter_by(id=context.path_id).first()
        if context_path is None:
            _error(
                "context_object_not_found",
                "学习路径不存在",
                status_code=404,
                field="pathId",
            )
        _assert_owner(context_path.owner_public_id, user, "pathId")
        _assert_course(context_path.course_id, course.id, "pathId")
        material["path"] = {
            "id": context_path.id,
            "version": context_path.lock_version,
            "status": context_path.status,
        }

    chapter = None
    if context.chapter_id:
        chapter = session.query(DBChapter).filter_by(id=context.chapter_id).first()
        if chapter is None:
            _error(
                "context_object_not_found",
                "章节不存在",
                status_code=404,
                field="chapterId",
            )
        _assert_course(chapter.course_id, course.id, "chapterId")
        chapter_summary = _summary(
            object_type="chapter",
            object_id=chapter.id,
            title=chapter.title,
            course_id=chapter.course_id,
            version=chapter.stable_key,
            status="available",
        )
        material["chapter"] = {
            "id": chapter.id,
            "stableKey": chapter.stable_key,
            "position": chapter.position,
        }

    if context.knowledge_point_id:
        knowledge = (
            session.query(DBKnowledgePoint)
            .filter_by(id=context.knowledge_point_id)
            .first()
        )
        if knowledge is None:
            _error(
                "context_object_not_found",
                "知识点不存在",
                status_code=404,
                field="knowledgePointId",
            )
        relation_query = session.query(DBChapterKnowledgePoint).join(
            DBChapter, DBChapter.id == DBChapterKnowledgePoint.chapter_id
        )
        relation_query = relation_query.filter(
            DBChapterKnowledgePoint.knowledge_point_id == knowledge.id,
            DBChapter.course_id == course.id,
        )
        if chapter is not None:
            relation_query = relation_query.filter(
                DBChapterKnowledgePoint.chapter_id == chapter.id
            )
        if relation_query.first() is None:
            _error(
                "context_course_mismatch",
                "知识点不属于当前课程或章节",
                status_code=409,
                field="knowledgePointId",
            )
        knowledge_summary = _summary(
            object_type="knowledge_point",
            object_id=knowledge.id,
            title=knowledge.title,
            course_id=course.id,
            version=knowledge.version,
            status=knowledge.status,
        )
        material["knowledgePoint"] = {
            "id": knowledge.id,
            "version": knowledge.version,
            "status": knowledge.status,
        }

    if context.task_id:
        generation_task = (
            session.query(DBGenerationTask).filter_by(id=context.task_id).first()
        )
        if generation_task is not None:
            _assert_owner(generation_task.owner_public_id, user, "taskId")
            _assert_course(generation_task.course_id, course.id, "taskId")
            task_summary = _summary(
                object_type="generation_task",
                object_id=generation_task.id,
                title=generation_task.capability,
                course_id=generation_task.course_id,
                owner_user_id=generation_task.owner_public_id,
                version=generation_task.updated_at,
                status=generation_task.status,
            )
            material["task"] = {
                "id": generation_task.id,
                "kind": "generation_task",
                "status": generation_task.status,
                "updatedAt": _version_text(generation_task.updated_at),
            }
        else:
            path_node = session.query(DBPathNode).filter_by(id=context.task_id).first()
            path = (
                session.query(DBLearningPath)
                .filter_by(id=path_node.learning_path_id)
                .first()
                if path_node is not None
                else None
            )
            if path_node is None or path is None:
                _error(
                    "context_object_not_found",
                    "学习任务不存在",
                    status_code=404,
                    field="taskId",
                )
            if context_path is not None and path.id != context_path.id:
                _error(
                    "context_object_mismatch",
                    "学习任务不属于指定学习路径",
                    status_code=409,
                    field="taskId",
                )
            _assert_owner(path.owner_public_id, user, "taskId")
            _assert_course(path.course_id, course.id, "taskId")
            task_summary = _summary(
                object_type="path_node",
                object_id=path_node.id,
                title=path_node.title,
                course_id=path.course_id,
                owner_user_id=path.owner_public_id,
                version=path.lock_version,
                status=path_node.status,
            )
            material["task"] = {
                "id": path_node.id,
                "kind": "path_node",
                "pathId": path.id,
                "pathVersion": path.lock_version,
                "status": path_node.status,
            }

    if context.resource_id:
        artifact = session.query(DBArtifact).filter_by(id=context.resource_id).first()
        if artifact is None:
            _error(
                "context_object_not_found",
                "学习资源不存在",
                status_code=404,
                field="resourceId",
            )
        _assert_owner(artifact.owner_public_id, user, "resourceId")
        _assert_course(artifact.course_id, course.id, "resourceId")
        if artifact.archived_at is not None or artifact.status in {"archived", "withdrawn"}:
            _error(
                "context_object_unavailable",
                "学习资源已归档或撤回",
                status_code=410,
                field="resourceId",
            )
        resource_summary = _summary(
            object_type="resource",
            object_id=artifact.id,
            title=artifact.title,
            course_id=artifact.course_id,
            owner_user_id=artifact.owner_public_id,
            version=artifact.current_version_id or artifact.lock_version,
            status=artifact.status,
        )
        material["resource"] = {
            "id": artifact.id,
            "currentVersionId": artifact.current_version_id,
            "lockVersion": artifact.lock_version,
            "status": artifact.status,
        }

    if context.source_ref_id:
        source_ref = session.query(DBSourceRef).filter_by(id=context.source_ref_id).first()
        source = (
            session.query(DBSourceDocument)
            .filter_by(id=source_ref.source_document_id)
            .first()
            if source_ref is not None
            else None
        )
        if source_ref is None or source is None:
            _error(
                "context_object_not_found",
                "来源引用不存在",
                status_code=404,
                field="sourceRefId",
            )
        _assert_course(source.course_id, course.id, "sourceRefId")
        if chapter is not None and source_ref.chapter_id not in {None, chapter.id}:
            _error(
                "context_course_mismatch",
                "来源引用不属于当前章节",
                status_code=409,
                field="sourceRefId",
            )
        source_summary = _summary(
            object_type="source_ref",
            object_id=source_ref.id,
            title=source_ref.location_label or source.title,
            course_id=source.course_id,
            version=source_ref.parser_version,
            status="available",
        )
        material["sourceRef"] = {
            "id": source_ref.id,
            "parserVersion": source_ref.parser_version,
            "contentHash": source_ref.content_hash,
        }

    if context.attempt_id:
        attempt = (
            session.query(DBAssessmentAttempt).filter_by(id=context.attempt_id).first()
        )
        if attempt is None:
            _error(
                "context_object_not_found",
                "作答记录不存在",
                status_code=404,
                field="attemptId",
            )
        _assert_owner(attempt.owner_public_id, user, "attemptId")
        _assert_course(attempt.course_id, course.id, "attemptId")
        attempt_summary = _summary(
            object_type="assessment_attempt",
            object_id=attempt.id,
            title="测评作答记录",
            course_id=attempt.course_id,
            owner_user_id=attempt.owner_public_id,
            version=attempt.submitted_at,
            status=attempt.grading_status,
        )
        material["attempt"] = {
            "id": attempt.id,
            "submittedAt": _version_text(attempt.submitted_at),
            "gradingStatus": attempt.grading_status,
        }

    resolved_version = _context_version(material)
    if context.version and context.version != resolved_version:
        _error(
            "context_version_stale",
            "学习上下文已经更新，请从最近保存位置继续",
            status_code=409,
            field="version",
        )
    resolved_ref = context.model_copy(
        update={"user_id": user.public_id, "version": resolved_version}
    )
    return ContextResolution(
        context=resolved_ref,
        course=course_summary,
        chapter=chapter_summary,
        knowledge_point=knowledge_summary,
        task=task_summary,
        resource=resource_summary,
        source_ref=source_summary,
        attempt=attempt_summary,
    )
