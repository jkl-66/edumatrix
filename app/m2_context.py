"""Server-side verified context assembly for M2 generation capabilities."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import HTTPException

from app.authorization import require_course_access
from app.database import (
    DBChapterKnowledgePoint,
    DBCourse,
    DBDomainPack,
    DBDomainVersion,
    DBKnowledgePoint,
    DBProfileSnapshot,
    DBSourceDocument,
    DBSourceRef,
    DBUser,
)
from app.m2_contracts import GenerationContext


class M2ContextAssemblyError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _fail(code: str, message: str) -> None:
    raise M2ContextAssemblyError(code, message)


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def assemble_verified_context(
    session: Any,
    *,
    owner_public_id: str,
    course_id: str,
    domain_version_id: str,
    profile_snapshot_id: str,
    target_knowledge_point_ids: list[str],
    source_ref_ids: list[str],
    language: str = "zh-CN",
) -> GenerationContext:
    """Resolve and authorize every object before creating a verified context."""
    try:
        requested = GenerationContext(
            owner_public_id=owner_public_id,
            course_id=course_id,
            domain_version_id=domain_version_id,
            profile_snapshot_id=profile_snapshot_id,
            target_knowledge_point_ids=target_knowledge_point_ids,
            source_ref_ids=source_ref_ids,
            language=language,
        )
    except ValueError as exc:
        raise M2ContextAssemblyError("invalid_context_shape", str(exc)) from exc

    user = session.query(DBUser).filter_by(public_id=requested.owner_public_id, is_active=True).first()
    if user is None:
        _fail("owner_not_found", "active context owner does not exist")
    course = session.query(DBCourse).filter_by(id=requested.course_id).first()
    if course is None or course.status != "published":
        _fail("course_not_available", "published course does not exist")
    from course_catalog import course_is_selectable
    if not course_is_selectable(session, course):
        _fail("course_not_available", "course has no usable learning material")
    try:
        require_course_access(
            session,
            user,
            course_id=course.id,
            action="read",
            visibility=course.visibility,
        )
    except HTTPException as exc:
        raise M2ContextAssemblyError("course_forbidden", "owner cannot read course") from exc

    domain_row = (
        session.query(DBDomainVersion, DBDomainPack)
        .join(DBDomainPack, DBDomainPack.id == DBDomainVersion.domain_pack_id)
        .filter(DBDomainVersion.id == requested.domain_version_id)
        .first()
    )
    if domain_row is None:
        _fail("domain_version_not_found", "domain version does not exist")
    domain_version, domain_pack = domain_row
    if (
        domain_pack.status != "active"
        or domain_pack.current_version_id != domain_version.id
        or course.domain_pack != domain_pack.domain_key
    ):
        _fail("domain_version_mismatch", "course is not bound to the active domain version")

    snapshot = session.query(DBProfileSnapshot).filter_by(id=requested.profile_snapshot_id).first()
    if snapshot is None:
        _fail("profile_snapshot_not_found", "profile snapshot does not exist")
    if snapshot.owner_public_id != requested.owner_public_id:
        _fail("profile_snapshot_forbidden", "profile snapshot belongs to another owner")
    if snapshot.content_hash != _canonical_hash(snapshot.snapshot):
        _fail("profile_snapshot_tampered", "profile snapshot hash does not match its content")

    points = session.query(DBKnowledgePoint).filter(
        DBKnowledgePoint.id.in_(requested.target_knowledge_point_ids)
    ).all()
    points_by_id = {point.id: point for point in points}
    if set(points_by_id) != set(requested.target_knowledge_point_ids):
        _fail("knowledge_point_not_found", "one or more target knowledge points do not exist")
    if any(
        point.domain_pack != domain_pack.domain_key
        or point.version != domain_version.version
        or point.status != "active"
        for point in points
    ):
        _fail("knowledge_point_domain_mismatch", "target knowledge point is outside the active domain version")

    source_rows = (
        session.query(DBSourceRef, DBSourceDocument)
        .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
        .filter(DBSourceRef.id.in_(requested.source_ref_ids))
        .all()
    )
    sources_by_id = {source_ref.id: (source_ref, document) for source_ref, document in source_rows}
    if set(sources_by_id) != set(requested.source_ref_ids):
        _fail("source_ref_not_found", "one or more source references do not exist")
    if any(
        document.course_id != course.id or document.processing_status != "ready"
        for _source_ref, document in sources_by_id.values()
    ):
        _fail("source_ref_course_mismatch", "source reference is not readable in the selected course")

    covered_pairs = {
        (relation.knowledge_point_id, source_ref.id)
        for relation, source_ref in (
            session.query(DBChapterKnowledgePoint, DBSourceRef)
            .join(DBSourceRef, DBSourceRef.chapter_id == DBChapterKnowledgePoint.chapter_id)
            .filter(
                DBChapterKnowledgePoint.knowledge_point_id.in_(requested.target_knowledge_point_ids),
                DBSourceRef.id.in_(requested.source_ref_ids),
                DBChapterKnowledgePoint.relation_type == "teaches",
            )
            .all()
        )
    }
    covered_points = {point_id for point_id, _source_ref_id in covered_pairs}
    covered_sources = {source_ref_id for _point_id, source_ref_id in covered_pairs}
    if covered_points != set(requested.target_knowledge_point_ids):
        _fail("target_without_source", "every target knowledge point must have a selected teaching source")
    if covered_sources != set(requested.source_ref_ids):
        _fail("source_not_relevant", "every selected source must teach a target knowledge point")

    frozen = snapshot.snapshot or {}
    planning = frozen.get("planning_constraints") or {}
    frozen_target_ids = (
        frozen.get("focus_knowledge_point_ids")
        or frozen.get("weak_knowledge_point_ids")
        or []
    )
    if (
        frozen.get("course_id") != requested.course_id
        or frozen.get("domain_version_id") != requested.domain_version_id
        or not set(requested.target_knowledge_point_ids).issubset(
            set(frozen_target_ids)
        )
        or not set(requested.source_ref_ids).issubset(set(planning.get("source_ref_ids") or []))
    ):
        _fail("profile_context_mismatch", "profile snapshot does not freeze the requested generation context")
    return requested
