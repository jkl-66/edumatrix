"""Restorable, source-bound context for the M5 current-resource tutor."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Literal

from pydantic import Field, model_validator

from app.authorization import ObjectAccess, active_course_role, can_access_object
from app.database import (
    DBArtifact,
    DBChapter,
    DBCourse,
    DBPathNode,
    DBLearningPath,
    DBSourceDocument,
    DBSourceRef,
    DBTutorContextSession,
)
from app.m1_lifecycle import record_audit
from app.m2_contracts import StrictModel


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


class TutorContextSpec(StrictModel):
    schema_version: Literal["m5.tutor-context.v1"] = "m5.tutor-context.v1"
    idempotency_key: str = Field(min_length=8, max_length=128)
    course_id: str | None = Field(default=None, max_length=128)
    context_mode: Literal["current_resource", "current_course", "personal_resources", "external_allowed"]
    primary_object_type: Literal["chapter", "artifact", "source_ref", "path_node"]
    primary_object_id: str = Field(min_length=1, max_length=64)
    selected_source_ref_ids: tuple[str, ...] = Field(default=(), max_length=8)
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
    else:
        row = session.query(DBPathNode, DBLearningPath).join(
            DBLearningPath, DBLearningPath.id == DBPathNode.learning_path_id,
        ).filter(DBPathNode.id == spec.primary_object_id).first()
        if row is None or row[1].owner_public_id != current_user.public_id:
            _fail("tutor_path_node_forbidden", "path node is unavailable to the current user")
        if resolved_course_id and row[1].course_id != resolved_course_id:
            _fail("tutor_path_node_invalid", "path node is outside the selected course")
        resolved_course_id = resolved_course_id or row[1].course_id
        title = row[0].title

    sources = [
        _source_snapshot(session, source_ref_id=item, course_id=resolved_course_id)
        for item in spec.selected_source_ref_ids
    ]
    if spec.primary_object_type == "source_ref" and spec.primary_object_id not in spec.selected_source_ref_ids:
        sources.insert(0, _source_snapshot(
            session, source_ref_id=spec.primary_object_id, course_id=resolved_course_id,
        ))
    return {
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
        "formula_latex": spec.formula_latex,
        "video_timestamp_seconds": spec.video_timestamp_seconds,
        "retrieval_scope": {
            "current_resource_only": spec.context_mode == "current_resource",
            "course_allowed": spec.context_mode in {"current_course", "external_allowed"},
            "personal_resources_allowed": spec.context_mode in {"personal_resources", "external_allowed"},
            "external_allowed": spec.context_mode == "external_allowed",
        },
    }


def create_tutor_context(
    session: Any, *, current_user: Any, spec: TutorContextSpec,
) -> tuple[DBTutorContextSession, bool]:
    snapshot = resolve_tutor_context(session, current_user=current_user, spec=spec)
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
