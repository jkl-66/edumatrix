"""Transactional repositories for M1 artifacts and generation tasks."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy import func

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
)


class M1Repository:
    """Central read repository used by the M1 HTTP boundary."""

    def __init__(self, session: Any):
        self.session = session

    def course(self, course_id: str) -> DBCourse | None:
        return self.session.query(DBCourse).filter_by(id=course_id).first()

    def course_outline(self, course_id: str) -> list[dict[str, Any]]:
        chapters = (
            self.session.query(DBChapter).filter_by(course_id=course_id)
            .order_by(DBChapter.position, DBChapter.id).all()
        )
        output = []
        for chapter in chapters:
            source_ref = (
                self.session.query(DBSourceRef).filter_by(chapter_id=chapter.id)
                .order_by(DBSourceRef.created_at.desc()).first()
            )
            points = (
                self.session.query(DBKnowledgePoint)
                .join(DBChapterKnowledgePoint, DBChapterKnowledgePoint.knowledge_point_id == DBKnowledgePoint.id)
                .filter(DBChapterKnowledgePoint.chapter_id == chapter.id)
                .order_by(DBKnowledgePoint.code).all()
            )
            output.append({
                "id": chapter.id, "title": chapter.title, "position": chapter.position,
                "parent_id": chapter.parent_id, "source_document_id": chapter.source_document_id,
                "source_ref_id": source_ref.id if source_ref else "",
                "knowledge_points": [{"id": point.id, "code": point.code, "title": point.title}
                                     for point in points],
            })
        return output

    def source_ref_context(self, source_ref_id: str):
        return (
            self.session.query(DBSourceRef, DBSourceDocument, DBCourse)
            .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
            .join(DBCourse, DBCourse.id == DBSourceDocument.course_id)
            .filter(DBSourceRef.id == source_ref_id).first()
        )

    def task(self, task_id: str) -> DBGenerationTask | None:
        return self.session.query(DBGenerationTask).filter_by(id=task_id).first()

    def task_payload(self, task: DBGenerationTask) -> dict[str, Any]:
        steps = self.session.query(DBTaskStep).filter_by(task_id=task.id).order_by(
            DBTaskStep.sequence, DBTaskStep.attempt
        ).all()
        events = self.session.query(DBTaskEvent).filter_by(task_id=task.id).order_by(
            DBTaskEvent.sequence
        ).all()
        return {
            "id": task.id, "trace_id": task.trace_id, "course_id": task.course_id,
            "capability": task.capability, "model": task.model, "status": task.status,
            "progress": task.progress, "failure_code": task.failure_code,
            "failure_reason": task.failure_reason,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "steps": [{"id": step.id, "sequence": step.sequence, "attempt": step.attempt,
                       "agent_role": step.agent_role, "tool_name": step.tool_name,
                       "status": step.status, "output_artifact_version_id": step.output_artifact_version_id,
                       "error_code": step.error_code} for step in steps],
            "events": [{"id": event.id, "sequence": event.sequence, "step_id": event.step_id,
                        "event_type": event.event_type, "schema_version": event.schema_version,
                        "payload": event.payload or {},
                        "created_at": event.created_at.isoformat() if event.created_at else None}
                       for event in events],
        }

    def list_tasks(self, *, owner_public_id: str, status: str | None = None,
                   course_id: str | None = None, cursor: str | None = None,
                   limit: int = 25) -> dict[str, Any]:
        query = self.session.query(DBGenerationTask).filter_by(owner_public_id=owner_public_id)
        if status:
            query = query.filter_by(status=status)
        if course_id:
            query = query.filter_by(course_id=course_id)
        if cursor:
            query = query.filter(DBGenerationTask.id > cursor)
        rows = query.order_by(DBGenerationTask.id).limit(limit + 1).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        return {"items": [{"id": row.id, "trace_id": row.trace_id, "course_id": row.course_id,
                           "capability": row.capability, "status": row.status,
                           "progress": row.progress,
                           "created_at": row.created_at.isoformat() if row.created_at else None}
                          for row in rows],
                "next_cursor": rows[-1].id if has_more and rows else None,
                "has_more": has_more, "limit": limit}

    def artifact(self, artifact_id: str) -> DBArtifact | None:
        return self.session.query(DBArtifact).filter_by(id=artifact_id).first()

    def artifact_payload(self, artifact: DBArtifact) -> dict[str, Any]:
        versions = self.session.query(DBArtifactVersion).filter_by(artifact_id=artifact.id).order_by(
            DBArtifactVersion.version_number
        ).all()
        relations = self.session.query(DBArtifactRelation).filter(
            (DBArtifactRelation.source_artifact_id == artifact.id)
            | (DBArtifactRelation.target_artifact_id == artifact.id)
        ).all()
        return {"id": artifact.id, "course_id": artifact.course_id,
                "artifact_type": artifact.artifact_type, "title": artifact.title,
                "status": artifact.status, "current_version_id": artifact.current_version_id,
                "creating_task_id": artifact.creating_task_id,
                "versions": [{"id": version.id, "version_number": version.version_number,
                              "content": version.content, "content_format": version.content_format,
                              "content_hash": version.content_hash, "metadata": version.metadata_json or {},
                              "created_task_id": version.created_task_id} for version in versions],
                "relations": [{"id": relation.id, "source_artifact_id": relation.source_artifact_id,
                               "target_artifact_id": relation.target_artifact_id,
                               "relation_type": relation.relation_type} for relation in relations]}

    def list_artifacts(self, *, owner_public_id: str, status: str | None = None,
                       course_id: str | None = None, cursor: str | None = None,
                       include_archived: bool = False, limit: int = 25) -> dict[str, Any]:
        query = self.session.query(DBArtifact).filter_by(owner_public_id=owner_public_id)
        if status:
            query = query.filter_by(status=status)
        elif not include_archived:
            query = query.filter(DBArtifact.archived_at.is_(None))
        if course_id:
            query = query.filter_by(course_id=course_id)
        if cursor:
            query = query.filter(DBArtifact.id > cursor)
        rows = query.order_by(DBArtifact.id).limit(limit + 1).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        return {"items": [{"id": row.id, "course_id": row.course_id,
                           "artifact_type": row.artifact_type, "title": row.title,
                           "status": row.status, "current_version_id": row.current_version_id,
                           "archived_at": row.archived_at.isoformat() if row.archived_at else None,
                           "updated_at": row.updated_at.isoformat() if row.updated_at else None}
                          for row in rows],
                "next_cursor": rows[-1].id if has_more and rows else None,
                "has_more": has_more, "limit": limit}


def create_generation_task(
    session: Any,
    *,
    owner_public_id: str,
    capability: str,
    idempotency_key: str,
    course_id: str | None = None,
    model: str = "",
    trace_id: str | None = None,
) -> tuple[DBGenerationTask, bool]:
    existing = (
        session.query(DBGenerationTask)
        .filter(
            DBGenerationTask.owner_public_id == owner_public_id,
            DBGenerationTask.idempotency_key == idempotency_key,
        )
        .first()
    )
    if existing is not None:
        return existing, False
    task = DBGenerationTask(
        owner_public_id=owner_public_id,
        course_id=course_id,
        trace_id=trace_id or f"trace-{uuid.uuid4().hex}",
        capability=capability,
        model=model,
        idempotency_key=idempotency_key,
    )
    session.add(task)
    session.flush()
    append_task_event(session, task_id=task.id, event_type="generation_task.created", payload={"status": task.status})
    return task, True


def append_task_event(
    session: Any,
    *,
    task_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    step_id: str | None = None,
) -> DBTaskEvent:
    last_sequence = session.query(func.max(DBTaskEvent.sequence)).filter(DBTaskEvent.task_id == task_id).scalar()
    event = DBTaskEvent(
        task_id=task_id,
        step_id=step_id,
        sequence=int(last_sequence or 0) + 1,
        event_type=event_type,
        payload=payload or {},
    )
    session.add(event)
    session.flush()
    return event


def create_task_step(
    session: Any,
    *,
    task_id: str,
    sequence: int,
    agent_role: str = "",
    tool_name: str = "",
    input_summary: str = "",
    parent_step_id: str | None = None,
    attempt: int = 1,
) -> DBTaskStep:
    step = DBTaskStep(
        task_id=task_id, sequence=sequence, agent_role=agent_role, tool_name=tool_name,
        input_summary=input_summary, parent_step_id=parent_step_id, attempt=attempt
    )
    session.add(step)
    session.flush()
    append_task_event(
        session, task_id=task_id, step_id=step.id, event_type="task_step.created",
        payload={"sequence": sequence, "agent_role": agent_role, "attempt": attempt},
    )
    return step


def create_artifact_with_version(
    session: Any,
    *,
    owner_public_id: str,
    artifact_type: str,
    title: str,
    content: str,
    content_format: str = "markdown",
    course_id: str | None = None,
    creating_task_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[DBArtifact, DBArtifactVersion]:
    artifact = DBArtifact(
        owner_public_id=owner_public_id, course_id=course_id, artifact_type=artifact_type,
        title=title, creating_task_id=creating_task_id
    )
    session.add(artifact)
    session.flush()
    version = add_artifact_version(
        session, artifact=artifact, content=content, content_format=content_format,
        created_by_public_id=owner_public_id, created_task_id=creating_task_id, metadata=metadata
    )
    return artifact, version


def add_artifact_version(
    session: Any,
    *,
    artifact: DBArtifact,
    content: str,
    content_format: str = "markdown",
    created_by_public_id: str | None = None,
    created_task_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> DBArtifactVersion:
    last_number = session.query(func.max(DBArtifactVersion.version_number)).filter(DBArtifactVersion.artifact_id == artifact.id).scalar()
    version = DBArtifactVersion(
        artifact_id=artifact.id, version_number=int(last_number or 0) + 1, content=content,
        content_format=content_format, content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        metadata_json=metadata or {}, created_by_public_id=created_by_public_id, created_task_id=created_task_id
    )
    session.add(version)
    session.flush()
    artifact.current_version_id = version.id
    session.flush()
    return version


def add_artifact_relation(
    session: Any, *, source_artifact_id: str, target_artifact_id: str,
    relation_type: str, created_by_public_id: str | None = None
) -> DBArtifactRelation:
    relation = DBArtifactRelation(
        source_artifact_id=source_artifact_id, target_artifact_id=target_artifact_id,
        relation_type=relation_type, created_by_public_id=created_by_public_id
    )
    session.add(relation)
    session.flush()
    return relation
