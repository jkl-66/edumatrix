"""Read APIs for M1 canonical course and provenance objects."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.auth import get_current_user
from app.identity import normalize_role
from app.authorization import require_course_access
from app.database import (
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
    DBArtifact,
    DBArtifactRelation,
    DBArtifactVersion,
    DBGenerationTask,
    DBKnowledgePoint,
    DBSourceDocument,
    DBSourceRef,
    DBTaskEvent,
    DBTaskStep,
    DBUser,
    run_db_op,
)
from app.authorization import ObjectAccess, require_object_access
from app.m1_repository import (
    M1Repository,
    add_artifact_version,
    create_artifact_with_version,
    create_generation_task,
)
from app.m1_object_service import (
    internal_object_payload as service_internal_object_payload,
    list_internal_inventory,
    list_objects,
    object_detail,
)
from app.m1_evidence import trace_bundle_summary


router = APIRouter(prefix="/api/v1", tags=["m1-foundation"])


def _require_internal_operator(user: DBUser) -> None:
    """Keep trace/object inspection outside ordinary learner accounts."""
    if normalize_role(user.role) not in {"admin", "teacher"}:
        raise HTTPException(status_code=403, detail="仅内部管理员或教师可访问对象检查")


class CourseSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    subject: str
    version: str
    language: str
    visibility: str
    status: str
    domain_pack: str
    membership_role: str | None = None


class ChapterSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    position: int
    parent_id: str | None
    source_document_id: str
    source_ref_id: str
    knowledge_points: list[dict[str, str]]


class SourceRefDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    course_id: str
    source_document_id: str
    chapter_id: str | None
    parser_version: str
    page_number: int | None
    char_start: int | None
    char_end: int | None
    image_region: dict | None
    content_hash: str
    quote: str


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capability: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=128)
    course_id: str | None = None
    model: str = Field(default="", max_length=128)


class ArtifactCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_type: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1)
    content_format: str = Field(default="markdown", max_length=32)
    course_id: str | None = None
    creating_task_id: str | None = None
    metadata: dict = Field(default_factory=dict)


class ArtifactVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1)
    content_format: str = Field(default="markdown", max_length=32)
    created_task_id: str | None = None
    metadata: dict = Field(default_factory=dict)


class CanonicalObjectDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_type: str
    id: str
    title: str
    status: str
    version: str | None
    owner_public_id: str | None
    created_by_public_id: str | None
    course_id: str | None
    organization_id: str | None
    source_ids: dict[str, str]
    created_at: str | None
    updated_at: str | None
    access: str


class CanonicalObjectPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[CanonicalObjectDetail]
    has_more: bool
    next_cursor: str | None
    limit: int
    object_type: str


def _course_payload(course: DBCourse, membership_role: str | None = None) -> dict:
    return {
        "id": course.id,
        "title": course.title,
        "subject": course.subject or "",
        "version": course.version,
        "language": course.language,
        "visibility": course.visibility,
        "status": course.status,
        "domain_pack": course.domain_pack or "",
        "membership_role": membership_role,
    }


@router.get("/courses/{course_id}", response_model=CourseSummary)
async def get_canonical_course(
    course_id: str, current_user: DBUser = Depends(get_current_user)
):
    def fetch(session):
        repository = M1Repository(session)
        course = repository.course(course_id)
        if course is None:
            raise HTTPException(status_code=404, detail="课程不存在")
        membership_role = require_course_access(
            session,
            current_user,
            course_id=course.id,
            action="read",
            visibility=course.visibility,
        )
        return _course_payload(course, membership_role)

    return await run_db_op(fetch)


@router.get("/courses/{course_id}/outline", response_model=list[ChapterSummary])
async def get_course_outline(
    course_id: str, current_user: DBUser = Depends(get_current_user)
):
    def fetch(session):
        repository = M1Repository(session)
        course = repository.course(course_id)
        if course is None:
            raise HTTPException(status_code=404, detail="课程不存在")
        require_course_access(
            session,
            current_user,
            course_id=course.id,
            action="read",
            visibility=course.visibility,
        )
        return repository.course_outline(course.id)

    return await run_db_op(fetch)


@router.get("/source-refs/{source_ref_id}", response_model=SourceRefDetail)
async def get_source_ref(
    source_ref_id: str, current_user: DBUser = Depends(get_current_user)
):
    def fetch(session):
        row = M1Repository(session).source_ref_context(source_ref_id)
        if row is None:
            raise HTTPException(status_code=404, detail="来源引用不存在")
        source_ref, source, course = row
        require_course_access(
            session,
            current_user,
            course_id=course.id,
            action="read",
            visibility=course.visibility,
        )
        return {
            "id": source_ref.id,
            "course_id": course.id,
            "source_document_id": source.id,
            "chapter_id": source_ref.chapter_id,
            "parser_version": source_ref.parser_version,
            "page_number": source_ref.page_number,
            "char_start": source_ref.char_start,
            "char_end": source_ref.char_end,
            "image_region": source_ref.image_region,
            "content_hash": source_ref.content_hash,
            "quote": source_ref.quote or "",
        }

    return await run_db_op(fetch)


@router.get("/objects/{object_type}", response_model=CanonicalObjectPage)
async def list_canonical_objects(
    object_type: str,
    status: str | None = None,
    q: str | None = None,
    cursor: str | None = None,
    limit: int = 25,
    current_user: DBUser = Depends(get_current_user),
):
    """List any registered M1 object through one stable authorization contract."""
    return await run_db_op(
        lambda session: list_objects(
            session, user=current_user, object_type=object_type, status=status,
            q=q, cursor=cursor, limit=limit,
        )
    )


@router.get("/objects/{object_type}/{object_id}", response_model=CanonicalObjectDetail)
async def get_canonical_object(
    object_type: str, object_id: str, current_user: DBUser = Depends(get_current_user)
):
    """Return ownership, scope, version and provenance without sensitive content."""
    return await run_db_op(
        lambda session: object_detail(
            session, user=current_user, object_type=object_type, object_id=object_id
        )
    )


def _internal_object_payload(session, object_type: str, object_id: str) -> dict | None:
    return service_internal_object_payload(session, object_type, object_id)


@router.get("/internal/objects")
async def list_internal_objects(
    object_type: str = "artifact",
    status: str | None = None,
    q: str | None = None,
    cursor: str | None = None,
    limit: int = 25,
    current_user: DBUser = Depends(get_current_user),
):
    """Stable cursor-paged inventory for internal troubleshooting only."""
    _require_internal_operator(current_user)
    limit = max(1, min(limit, 100))

    def fetch(session):
        return list_internal_inventory(
            session, object_type=object_type, status=status, q=q,
            cursor=cursor, limit=limit,
        )

    return await run_db_op(fetch)


@router.get("/internal/objects/{object_type}/{object_id}")
async def inspect_internal_object(
    object_type: str, object_id: str, current_user: DBUser = Depends(get_current_user)
):
    """Inspect ownership, immediate lineage and task references without exposing content."""
    _require_internal_operator(current_user)

    def fetch(session):
        payload = _internal_object_payload(session, object_type, object_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="对象不存在")
        return payload

    return await run_db_op(fetch)


@router.get("/internal/traces/{trace_id}")
async def inspect_internal_trace(
    trace_id: str, current_user: DBUser = Depends(get_current_user)
):
    """Reconstruct one persisted trace without returning evidence bodies or secrets."""
    _require_internal_operator(current_user)

    def fetch(session):
        payload = trace_bundle_summary(session, trace_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="Trace 不存在")
        return payload

    return await run_db_op(fetch)


def _task_payload(session, task: DBGenerationTask) -> dict:
    return M1Repository(session).task_payload(task)


@router.post("/generation-tasks", status_code=201)
async def create_task_endpoint(
    payload: TaskCreate, current_user: DBUser = Depends(get_current_user)
):
    def create(session):
        repository = M1Repository(session)
        if payload.course_id:
            course = repository.course(payload.course_id)
            if course is None:
                raise HTTPException(status_code=404, detail="课程不存在")
            require_course_access(
                session, current_user, course_id=course.id, action="read", visibility=course.visibility
            )
        task, created = create_generation_task(
            session,
            owner_public_id=current_user.public_id,
            capability=payload.capability,
            idempotency_key=payload.idempotency_key,
            course_id=payload.course_id,
            model=payload.model,
        )
        session.commit()
        return {**_task_payload(session, task), "created": created}

    return await run_db_op(create)


@router.get("/generation-tasks/{task_id}")
async def get_task_endpoint(
    task_id: str, current_user: DBUser = Depends(get_current_user)
):
    def fetch(session):
        task = M1Repository(session).task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="生成任务不存在")
        require_object_access(
            current_user,
            ObjectAccess("generation_task", task.id, owner_public_id=task.owner_public_id),
        )
        return _task_payload(session, task)

    return await run_db_op(fetch)


@router.get("/generation-tasks")
async def list_task_endpoint(
    status: str | None = None,
    course_id: str | None = None,
    cursor: str | None = None,
    limit: int = 25,
    current_user: DBUser = Depends(get_current_user),
):
    """Owner-scoped task inventory with stable cursor pagination."""
    limit = max(1, min(limit, 100))

    def fetch(session):
        return M1Repository(session).list_tasks(
            owner_public_id=current_user.public_id, status=status, course_id=course_id,
            cursor=cursor, limit=limit,
        )

    return await run_db_op(fetch)


def _artifact_payload(session, artifact: DBArtifact) -> dict:
    return M1Repository(session).artifact_payload(artifact)


@router.post("/artifacts", status_code=201)
async def create_artifact_endpoint(
    payload: ArtifactCreate, current_user: DBUser = Depends(get_current_user)
):
    def create(session):
        repository = M1Repository(session)
        if payload.course_id:
            course = repository.course(payload.course_id)
            if course is None:
                raise HTTPException(status_code=404, detail="课程不存在")
            require_course_access(
                session, current_user, course_id=course.id, action="read", visibility=course.visibility
            )
        if payload.creating_task_id:
            task = repository.task(payload.creating_task_id)
            if task is None or task.owner_public_id != current_user.public_id:
                raise HTTPException(status_code=403, detail="生成任务不属于当前用户")
        artifact, _ = create_artifact_with_version(
            session,
            owner_public_id=current_user.public_id,
            artifact_type=payload.artifact_type,
            title=payload.title,
            content=payload.content,
            content_format=payload.content_format,
            course_id=payload.course_id,
            creating_task_id=payload.creating_task_id,
            metadata=payload.metadata,
        )
        session.commit()
        return _artifact_payload(session, artifact)

    return await run_db_op(create)


@router.get("/artifacts/{artifact_id}")
async def get_artifact_endpoint(
    artifact_id: str, current_user: DBUser = Depends(get_current_user)
):
    def fetch(session):
        artifact = M1Repository(session).artifact(artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="产物不存在")
        require_object_access(
            current_user, ObjectAccess("artifact", artifact.id, owner_public_id=artifact.owner_public_id)
        )
        if artifact.archived_at is not None or artifact.status == "archived":
            raise HTTPException(status_code=410, detail="产物已归档")
        return _artifact_payload(session, artifact)

    return await run_db_op(fetch)


@router.get("/artifacts")
async def list_artifact_endpoint(
    status: str | None = None,
    course_id: str | None = None,
    cursor: str | None = None,
    include_archived: bool = False,
    limit: int = 25,
    current_user: DBUser = Depends(get_current_user),
):
    """Owner-scoped artifact inventory without returning full content."""
    limit = max(1, min(limit, 100))

    def fetch(session):
        return M1Repository(session).list_artifacts(
            owner_public_id=current_user.public_id, status=status, course_id=course_id,
            cursor=cursor, include_archived=include_archived, limit=limit,
        )

    return await run_db_op(fetch)


@router.post("/artifacts/{artifact_id}/versions", status_code=201)
async def create_artifact_version_endpoint(
    artifact_id: str,
    payload: ArtifactVersionCreate,
    current_user: DBUser = Depends(get_current_user),
):
    def create(session):
        repository = M1Repository(session)
        artifact = repository.artifact(artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="产物不存在")
        require_object_access(
            current_user,
            ObjectAccess("artifact", artifact.id, owner_public_id=artifact.owner_public_id),
            action="update",
        )
        if artifact.archived_at is not None or artifact.status == "archived":
            raise HTTPException(status_code=410, detail="产物已归档，不能追加版本")
        if payload.created_task_id:
            task = repository.task(payload.created_task_id)
            if task is None or task.owner_public_id != current_user.public_id:
                raise HTTPException(status_code=403, detail="生成任务不属于当前用户")
        add_artifact_version(
            session, artifact=artifact, content=payload.content,
            content_format=payload.content_format, created_by_public_id=current_user.public_id,
            created_task_id=payload.created_task_id, metadata=payload.metadata
        )
        session.commit()
        return _artifact_payload(session, artifact)

    return await run_db_op(create)
