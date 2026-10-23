from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.database import (
    Base,
    DBArtifact,
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
    DBCourseMembership,
    DBGenerationTask,
    DBKnowledgePoint,
    DBLearningPath,
    DBPathNode,
    DBSourceDocument,
    DBSourceRef,
    DBUser,
)
import app.m5_api as m5_api
from app.m5_learning import resolve_learning_context
from app.models import ContextResolutionError
from app.schemas import ContextRef


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    owner = DBUser(
        public_id="usr-context-owner",
        username="context-owner",
        hashed_password="hash",
        role="student",
    )
    other = DBUser(
        public_id="usr-context-other",
        username="context-other",
        hashed_password="hash",
        role="student",
    )
    course = DBCourse(
        id="course-context",
        version="course-v1",
        title="Context Course",
        visibility="private",
        status="published",
        manifest_version="manifest-v1",
    )
    other_course = DBCourse(
        id="course-other",
        version="course-v1",
        title="Other Course",
        visibility="public",
        status="published",
        manifest_version="manifest-v1",
    )
    session.add_all([owner, other, course, other_course])
    session.add(
        DBCourseMembership(
            id="cm-context-owner",
            course_id=course.id,
            user_public_id=owner.public_id,
            role="student",
            status="active",
        )
    )
    source = DBSourceDocument(
        id="src-context",
        course_id=course.id,
        title="Source",
        filename="source.md",
        file_format="md",
        content_hash="a" * 64,
    )
    # Both courses must be selectable before testing object ownership/mismatch.
    # A published course without any usable source is rejected earlier.
    session.add(DBSourceDocument(
        id="src-other-context",
        course_id=other_course.id,
        title="Other course source",
        filename="other-source.md",
        file_format="md",
        content_hash="c" * 64,
    ))
    chapter = DBChapter(
        id="chapter-context",
        course_id=course.id,
        source_document_id=source.id,
        stable_key="chapter-1",
        title="Chapter 1",
        position=1,
    )
    knowledge = DBKnowledgePoint(
        id="kp-context",
        domain_pack="ml",
        code="gradient-descent",
        version="kp-v1",
        title="Gradient Descent",
        status="active",
    )
    session.add_all([source, chapter, knowledge])
    session.flush()
    session.add(
        DBChapterKnowledgePoint(
            id="ckp-context",
            chapter_id=chapter.id,
            knowledge_point_id=knowledge.id,
            relation_type="teaches",
        )
    )
    source_ref = DBSourceRef(
        id="ref-context",
        source_document_id=source.id,
        chapter_id=chapter.id,
        parser_version="parser-v1",
        location_kind="section",
        location_label="Gradient section",
        content_hash="b" * 64,
    )
    task = DBGenerationTask(
        id="task-context",
        owner_public_id=owner.public_id,
        course_id=course.id,
        trace_id="trace-context",
        status="queued",
        capability="lesson.generate",
        idempotency_key="context-task-key",
    )
    resource = DBArtifact(
        id="resource-context",
        owner_public_id=owner.public_id,
        course_id=course.id,
        artifact_type="lesson",
        title="Gradient lesson",
        status="draft",
        current_version_id="resource-version-v1",
    )
    other_resource = DBArtifact(
        id="resource-other-user",
        owner_public_id=other.public_id,
        course_id=other_course.id,
        artifact_type="lesson",
        title="Other lesson",
        status="draft",
    )
    session.add_all([source_ref, task, resource, other_resource])
    path = DBLearningPath(
        id="path-context",
        owner_public_id=owner.public_id,
        course_id=course.id,
        source_plan_version_id="plan-version-context",
        status="active",
    )
    session.add(path)
    session.flush()
    session.add(
        DBPathNode(
            id="path-task-context",
            learning_path_id=path.id,
            node_key="path-node-context",
            sequence=1,
            node_type="chapter",
            target_object_id=chapter.id,
            title="Path chapter",
            status="pending",
            prerequisites=[],
        )
    )
    session.flush()
    return session, owner, other


def test_context_ref_requires_course_for_scoped_objects():
    with pytest.raises(ValueError, match="courseId is required"):
        ContextRef(resourceId="resource-context")


def test_context_resolution_preserves_and_validates_learning_path():
    session, owner, _ = _session()
    resolution = resolve_learning_context(
        session,
        user=owner,
        context=ContextRef(
            courseId="course-context",
            pathId="path-context",
            taskId="path-task-context",
        ),
    )

    assert resolution.context.path_id == "path-context"
    assert resolution.context.model_dump(mode="json", by_alias=True)["pathId"] == "path-context"
    assert resolution.task.object_type == "path_node"


def test_context_resolution_validates_all_supplied_objects_and_version():
    session, owner, _ = _session()
    resolution = resolve_learning_context(
        session,
        user=owner,
        context=ContextRef(
            courseId="course-context",
            chapterId="chapter-context",
            knowledgePointId="kp-context",
            taskId="task-context",
            resourceId="resource-context",
            sourceRefId="ref-context",
        ),
    )

    assert resolution.context.user_id == owner.public_id
    assert resolution.context.version.startswith("ctx-")
    assert resolution.course.id == "course-context"
    assert resolution.knowledge_point.id == "kp-context"
    assert resolution.task.object_type == "generation_task"
    assert resolution.resource.version == "resource-version-v1"
    assert resolution.source_ref.id == "ref-context"

    replay = resolve_learning_context(
        session,
        user=owner,
        context=resolution.context,
    )
    assert replay.context.version == resolution.context.version

    with pytest.raises(ContextResolutionError) as stale:
        resolve_learning_context(
            session,
            user=owner,
            context=resolution.context.model_copy(update={"version": "ctx-stale"}),
        )
    assert stale.value.code == "context_version_stale"
    assert stale.value.status_code == 409


def test_context_resolution_distinguishes_not_found_forbidden_and_cross_user():
    session, owner, other = _session()

    with pytest.raises(ContextResolutionError) as missing:
        resolve_learning_context(
            session,
            user=owner,
            context=ContextRef(courseId="course-context", resourceId="missing"),
        )
    assert missing.value.code == "context_object_not_found"
    assert missing.value.status_code == 404

    with pytest.raises(ContextResolutionError) as forbidden:
        resolve_learning_context(
            session,
            user=other,
            context=ContextRef(courseId="course-context"),
        )
    assert forbidden.value.code == "context_forbidden"

    with pytest.raises(ContextResolutionError) as cross_user:
        resolve_learning_context(
            session,
            user=owner,
            context=ContextRef(
                courseId="course-other",
                resourceId="resource-other-user",
            ),
        )
    assert cross_user.value.code == "context_cross_user"
    assert cross_user.value.status_code == 403


def test_context_resolution_rejects_course_mismatch_without_creating_objects():
    session, owner, _ = _session()
    artifact_count = session.query(DBArtifact).count()

    with pytest.raises(ContextResolutionError) as mismatch:
        resolve_learning_context(
            session,
            user=owner,
            context=ContextRef(
                courseId="course-other",
                resourceId="resource-context",
            ),
        )

    assert mismatch.value.code == "context_course_mismatch"
    assert session.query(DBArtifact).count() == artifact_count


def test_context_resolve_api_returns_aliases_and_preserves_structured_errors(monkeypatch):
    session, owner, _ = _session()

    async def fake_run_db_op(operation):
        return operation(session)

    monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
    api = FastAPI()
    api.include_router(m5_api.router)
    api.dependency_overrides[get_current_user] = lambda: owner

    with TestClient(api) as client:
        resolved = client.post(
            "/api/v1/m5/context/resolve",
            json={
                "context": {
                    "courseId": "course-context",
                    "chapterId": "chapter-context",
                    "knowledgePointId": "kp-context",
                    "resourceId": "resource-context",
                }
            },
        )
        assert resolved.status_code == 200, resolved.text
        payload = resolved.json()
        assert payload["context"]["userId"] == owner.public_id
        assert payload["context"]["courseId"] == "course-context"
        assert payload["knowledgePoint"]["id"] == "kp-context"

        stale = client.post(
            "/api/v1/m5/context/resolve",
            json={
                "context": {
                    "courseId": "course-context",
                    "version": "ctx-stale",
                }
            },
        )
        assert stale.status_code == 409
        assert stale.json()["detail"] == {
            "code": "context_version_stale",
            "message": "学习上下文已经更新，请从最近保存位置继续",
            "field": "version",
        }
