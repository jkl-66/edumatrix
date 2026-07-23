"""Uniform, non-secret read gateway for M1 foundation objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_

from app.authorization import ObjectAccess, require_course_access, require_object_access
from app.database import (
    DBAgentRun, DBArtifact, DBArtifactRelation, DBArtifactVersion, DBAuditLog,
    DBCertification, DBChapter, DBChapterKnowledgePoint, DBClaimCheck,
    DBCompetencyStandard, DBCourse, DBCourseMembership, DBDebateRound,
    DBDecisionRecord, DBDepartment, DBDomainPack, DBDomainVersion,
    DBEvaluationCase, DBEvaluationResult, DBEvaluationRun, DBExemptionRequest,
    DBExternalIdentityMapping, DBGenerationTask, DBJobFamily, DBJobLevel,
    DBJobTask, DBKnowledgePoint, DBLearningEvent, DBLearningPath, DBMemoryItem,
    DBOrganization, DBOrganizationMembership, DBPathNode, DBPlanDraft,
    DBPlanVersion, DBProfileEvidence, DBProfileSnapshot, DBPublication, DBQualityCheck,
    DBReviewDecision, DBSkillEvidence, DBSkillStandard, DBSourceDocument,
    DBSourceRef, DBTaskEvent, DBTaskStep, DBTrainingAssignment, DBTrainingCohort,
    DBTrainingProgram, DBUser,
)
from app.identity import normalize_role
from app.m1_enterprise import require_organization_access


@dataclass(frozen=True)
class ObjectSpec:
    model: Any
    public_reference: bool = False
    internal_only: bool = False


OBJECT_SPECS: dict[str, ObjectSpec] = {
    "course": ObjectSpec(DBCourse), "course_membership": ObjectSpec(DBCourseMembership),
    "source_document": ObjectSpec(DBSourceDocument), "chapter": ObjectSpec(DBChapter),
    "chapter_knowledge_point": ObjectSpec(DBChapterKnowledgePoint),
    "knowledge_point": ObjectSpec(DBKnowledgePoint, public_reference=True),
    "source_ref": ObjectSpec(DBSourceRef), "generation_task": ObjectSpec(DBGenerationTask),
    "artifact": ObjectSpec(DBArtifact), "artifact_version": ObjectSpec(DBArtifactVersion),
    "artifact_relation": ObjectSpec(DBArtifactRelation), "task_step": ObjectSpec(DBTaskStep),
    "task_event": ObjectSpec(DBTaskEvent), "plan_draft": ObjectSpec(DBPlanDraft),
    "plan_version": ObjectSpec(DBPlanVersion), "learning_path": ObjectSpec(DBLearningPath),
    "path_node": ObjectSpec(DBPathNode), "learning_event": ObjectSpec(DBLearningEvent),
    "memory_item": ObjectSpec(DBMemoryItem), "review_decision": ObjectSpec(DBReviewDecision),
    "publication": ObjectSpec(DBPublication), "audit_log": ObjectSpec(DBAuditLog),
    "domain_pack": ObjectSpec(DBDomainPack, public_reference=True),
    "domain_version": ObjectSpec(DBDomainVersion, public_reference=True),
    "job_task": ObjectSpec(DBJobTask, public_reference=True),
    "skill_standard": ObjectSpec(DBSkillStandard, public_reference=True),
    "profile_snapshot": ObjectSpec(DBProfileSnapshot),
    "profile_evidence": ObjectSpec(DBProfileEvidence), "agent_run": ObjectSpec(DBAgentRun),
    "quality_check": ObjectSpec(DBQualityCheck), "claim_check": ObjectSpec(DBClaimCheck),
    "debate_round": ObjectSpec(DBDebateRound), "decision_record": ObjectSpec(DBDecisionRecord),
    "evaluation_case": ObjectSpec(DBEvaluationCase, public_reference=True),
    "evaluation_run": ObjectSpec(DBEvaluationRun, internal_only=True),
    "evaluation_result": ObjectSpec(DBEvaluationResult, internal_only=True),
    "organization": ObjectSpec(DBOrganization),
    "organization_membership": ObjectSpec(DBOrganizationMembership),
    "department": ObjectSpec(DBDepartment), "job_family": ObjectSpec(DBJobFamily),
    "job_level": ObjectSpec(DBJobLevel), "competency_standard": ObjectSpec(DBCompetencyStandard),
    "training_program": ObjectSpec(DBTrainingProgram), "training_cohort": ObjectSpec(DBTrainingCohort),
    "training_assignment": ObjectSpec(DBTrainingAssignment),
    "exemption_request": ObjectSpec(DBExemptionRequest), "skill_evidence": ObjectSpec(DBSkillEvidence),
    "certification": ObjectSpec(DBCertification),
    "external_identity_mapping": ObjectSpec(DBExternalIdentityMapping),
}


def _operator(user: DBUser) -> bool:
    return normalize_role(user.role) in {"admin", "teacher"}


def _artifact_from_version(session: Any, version_id: str | None) -> DBArtifact | None:
    if not version_id:
        return None
    version = session.query(DBArtifactVersion).filter_by(id=version_id).first()
    return session.query(DBArtifact).filter_by(id=version.artifact_id).first() if version else None


def _task(session: Any, task_id: str | None) -> DBGenerationTask | None:
    return session.query(DBGenerationTask).filter_by(id=task_id).first() if task_id else None


def _resolve_scope(session: Any, object_type: str, row: Any) -> dict[str, Any]:
    owner = getattr(row, "owner_public_id", None)
    course_id = getattr(row, "course_id", None)
    organization_id = getattr(row, "organization_id", None)
    created_by = next((getattr(row, name, None) for name in (
        "created_by_public_id", "uploader_public_id", "actor_public_id",
        "requester_public_id", "reviewer_public_id", "issuer_public_id",
    ) if getattr(row, name, None)), None)

    if object_type == "course":
        course_id = row.id
    elif object_type == "organization":
        organization_id = row.id
    elif object_type == "chapter_knowledge_point":
        chapter = session.query(DBChapter).filter_by(id=row.chapter_id).first()
        course_id = chapter.course_id if chapter else None
    elif object_type == "source_ref":
        source = session.query(DBSourceDocument).filter_by(id=row.source_document_id).first()
        course_id = source.course_id if source else None
        created_by = source.uploader_public_id if source else None
    elif object_type == "artifact_version":
        artifact = session.query(DBArtifact).filter_by(id=row.artifact_id).first()
        if artifact:
            owner, course_id = artifact.owner_public_id, artifact.course_id
    elif object_type == "artifact_relation":
        artifact = session.query(DBArtifact).filter_by(id=row.source_artifact_id).first()
        if artifact:
            owner, course_id = artifact.owner_public_id, artifact.course_id
    elif object_type in {"task_step", "task_event", "agent_run", "debate_round"}:
        task = _task(session, row.task_id)
        if task:
            owner, course_id = task.owner_public_id, task.course_id
    elif object_type == "plan_version":
        plan = session.query(DBPlanDraft).filter_by(id=row.plan_draft_id).first()
        owner = plan.owner_public_id if plan else None
    elif object_type == "path_node":
        path = session.query(DBLearningPath).filter_by(id=row.learning_path_id).first()
        if path:
            owner, course_id = path.owner_public_id, path.course_id
    elif object_type in {"review_decision", "publication"}:
        artifact = _artifact_from_version(session, row.artifact_version_id)
        if artifact:
            owner, course_id = artifact.owner_public_id, artifact.course_id
    elif object_type in {"quality_check", "claim_check"}:
        artifact = _artifact_from_version(session, row.artifact_version_id)
        if artifact:
            owner, course_id = artifact.owner_public_id, artifact.course_id
    elif object_type == "audit_log":
        owner = row.actor_public_id
    elif object_type == "course_membership":
        owner = row.user_public_id
    elif object_type == "organization_membership":
        owner = row.user_public_id
    elif hasattr(row, "learner_public_id"):
        owner = row.learner_public_id
    elif object_type == "external_identity_mapping":
        owner = row.user_public_id
    elif object_type == "job_level":
        family = session.query(DBJobFamily).filter_by(id=row.job_family_id).first()
        organization_id = family.organization_id if family else None
    elif object_type == "competency_standard":
        level = session.query(DBJobLevel).filter_by(id=row.job_level_id).first()
        family = session.query(DBJobFamily).filter_by(id=level.job_family_id).first() if level else None
        organization_id = family.organization_id if family else None

    return {"owner_public_id": owner, "created_by_public_id": created_by,
            "course_id": course_id, "organization_id": organization_id}


def require_registered_object_access(
    session: Any, *, user: DBUser, object_type: str, row: Any
) -> dict[str, Any]:
    spec = OBJECT_SPECS[object_type]
    scope = _resolve_scope(session, object_type, row)
    if spec.internal_only:
        if not _operator(user):
            raise HTTPException(status_code=403, detail="该对象仅内部人员可访问")
        return scope
    if spec.public_reference:
        return scope
    if scope["owner_public_id"] == user.public_id or _operator(user):
        return scope
    if scope["organization_id"]:
        require_organization_access(
            session, organization_id=scope["organization_id"],
            user_public_id=user.public_id, action="read",
        )
        return scope
    if scope["course_id"]:
        course = session.query(DBCourse).filter_by(id=scope["course_id"]).first()
        if course is None:
            raise HTTPException(status_code=404, detail="对象所属课程不存在")
        require_course_access(
            session, user, course_id=course.id, action="read", visibility=course.visibility
        )
        return scope
    raise HTTPException(status_code=403, detail="对象缺少可验证的访问边界")


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def object_detail(session: Any, *, user: DBUser, object_type: str, object_id: str) -> dict[str, Any]:
    spec = OBJECT_SPECS.get(object_type)
    if spec is None:
        raise HTTPException(status_code=400, detail="不支持的对象类型")
    row = session.query(spec.model).filter(spec.model.id == object_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="对象不存在")
    scope = require_registered_object_access(session, user=user, object_type=object_type, row=row)
    status = getattr(row, "status", getattr(row, "processing_status", "")) or ""
    version = next((getattr(row, name, None) for name in (
        "version", "version_number", "profile_version", "schema_version",
        "current_version_id", "parser_version", "model_version", "agent_version",
    ) if getattr(row, name, None) is not None), None)
    source_ids = {}
    for column in row.__table__.columns:
        if column.name.endswith("_id") and column.name not in {
            "id", "owner_public_id", "user_public_id", "learner_public_id",
            "actor_public_id", "requester_public_id", "reviewer_public_id",
            "issuer_public_id", "approver_public_id", "expert_signer_public_id",
        }:
            value = getattr(row, column.name, None)
            if value is not None:
                source_ids[column.name] = value
    title = next((getattr(row, name, None) for name in (
        "title", "name", "capability", "code", "event_type", "decision_type",
        "atomic_claim", "provider", "source_type",
    ) if getattr(row, name, None)), object_id)
    return {
        "object_type": object_type, "id": str(row.id), "title": str(title),
        "status": str(status), "version": str(version) if version is not None else None,
        "owner_public_id": scope["owner_public_id"],
        "created_by_public_id": scope["created_by_public_id"],
        "course_id": scope["course_id"], "organization_id": scope["organization_id"],
        "source_ids": source_ids,
        "created_at": _iso(getattr(row, "created_at", None)),
        "updated_at": _iso(getattr(row, "updated_at", None)),
        "access": "internal" if spec.internal_only else (
            "public_reference" if spec.public_reference else "owner_or_scope_member"
        ),
    }


def list_objects(
    session: Any, *, user: DBUser, object_type: str, status: str | None = None,
    q: str | None = None, cursor: str | None = None, limit: int = 25,
) -> dict[str, Any]:
    spec = OBJECT_SPECS.get(object_type)
    if spec is None:
        raise HTTPException(status_code=400, detail="不支持的对象类型")
    if spec.internal_only and not _operator(user):
        raise HTTPException(status_code=403, detail="该对象仅内部人员可访问")
    model = spec.model
    limit = max(1, min(limit, 100))
    query = session.query(model)
    status_column = getattr(model, "status", getattr(model, "processing_status", None))
    if status and status_column is not None:
        query = query.filter(status_column == status)
    if q:
        columns = [getattr(model, name) for name in ("title", "name", "capability", "code")
                   if hasattr(model, name)]
        if columns:
            query = query.filter(or_(*[column.ilike(f"%{q}%") for column in columns]))
    scan_cursor = cursor
    visible: list[dict[str, Any]] = []
    exhausted = False
    while len(visible) <= limit and not exhausted:
        batch_query = query
        if scan_cursor:
            batch_query = batch_query.filter(model.id > scan_cursor)
        rows = batch_query.order_by(model.id).limit(100).all()
        exhausted = len(rows) < 100
        if not rows:
            break
        for row in rows:
            scan_cursor = str(row.id)
            try:
                visible.append(object_detail(
                    session, user=user, object_type=object_type, object_id=str(row.id)
                ))
            except HTTPException as exc:
                if exc.status_code not in {403, 404}:
                    raise
            if len(visible) > limit:
                break
    has_more = len(visible) > limit
    items = visible[:limit]
    return {"items": items, "has_more": has_more,
            "next_cursor": items[-1]["id"] if has_more and items else None,
            "limit": limit, "object_type": object_type}


def internal_object_payload(session: Any, object_type: str, object_id: str) -> dict | None:
    """Richer internal lineage view; still excludes object content and credentials."""
    if object_type == "course":
        row = session.query(DBCourse).filter_by(id=object_id).first()
        if row is None:
            return None
        return {"object_type": object_type, "object_id": row.id,
                "owner_public_id": row.owner_public_id, "status": row.status,
                "version": row.version, "title": row.title,
                "permissions": {"visibility": row.visibility},
                "lineage": {"sources": session.query(DBSourceDocument.id).filter_by(course_id=row.id).count()},
                "tasks": [{"id": item[0]} for item in session.query(DBGenerationTask.id)
                          .filter_by(course_id=row.id).order_by(DBGenerationTask.id).all()]}
    if object_type == "source_document":
        row = session.query(DBSourceDocument).filter_by(id=object_id).first()
        if row is None:
            return None
        return {"object_type": object_type, "object_id": row.id,
                "owner_public_id": row.uploader_public_id, "status": row.processing_status,
                "version": row.parser_version, "title": row.title,
                "permissions": {"course_id": row.course_id},
                "lineage": {"course_id": row.course_id, "legacy_document_id": row.legacy_document_id},
                "tasks": []}
    if object_type == "generation_task":
        row = session.query(DBGenerationTask).filter_by(id=object_id).first()
        if row is None:
            return None
        return {"object_type": object_type, "object_id": row.id,
                "owner_public_id": row.owner_public_id, "status": row.status,
                "version": row.model, "title": row.capability,
                "permissions": {"owner_public_id": row.owner_public_id},
                "lineage": {"course_id": row.course_id, "trace_id": row.trace_id},
                "tasks": [{"id": row.id, "status": row.status}]}
    if object_type == "artifact":
        row = session.query(DBArtifact).filter_by(id=object_id).first()
        if row is None:
            return None
        relations = session.query(DBArtifactRelation).filter(
            (DBArtifactRelation.source_artifact_id == row.id)
            | (DBArtifactRelation.target_artifact_id == row.id)
        ).order_by(DBArtifactRelation.id).all()
        return {"object_type": object_type, "object_id": row.id,
                "owner_public_id": row.owner_public_id, "status": row.status,
                "version": row.current_version_id, "title": row.title,
                "permissions": {"owner_public_id": row.owner_public_id, "course_id": row.course_id},
                "lineage": {"creating_task_id": row.creating_task_id,
                            "relations": [{"id": item.id, "source": item.source_artifact_id,
                                           "target": item.target_artifact_id, "type": item.relation_type}
                                          for item in relations]},
                "tasks": ([{"id": row.creating_task_id}] if row.creating_task_id else [])}
    return None


def list_internal_inventory(
    session: Any, *, object_type: str, status: str | None = None,
    q: str | None = None, cursor: str | None = None, limit: int = 25,
) -> dict[str, Any]:
    allowed = {"course": DBCourse, "source_document": DBSourceDocument,
               "generation_task": DBGenerationTask, "artifact": DBArtifact}
    model = allowed.get(object_type)
    if model is None:
        raise HTTPException(status_code=400, detail="不支持的对象类型")
    limit = max(1, min(limit, 100))
    query = session.query(model)
    status_column = getattr(model, "status", getattr(model, "processing_status", None))
    if status and status_column is not None:
        query = query.filter(status_column == status)
    if q:
        searchable = [getattr(model, name) for name in ("title", "capability", "filename")
                      if hasattr(model, name)]
        if searchable:
            query = query.filter(or_(*[column.ilike(f"%{q}%") for column in searchable]))
    if cursor:
        query = query.filter(model.id > cursor)
    rows = query.order_by(model.id).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {"items": [{"id": row.id,
                       "status": getattr(row, "status", getattr(row, "processing_status", "")),
                       "title": getattr(row, "title", getattr(row, "capability", getattr(row, "filename", ""))),
                       "owner_public_id": getattr(row, "owner_public_id", getattr(row, "uploader_public_id", None))}
                      for row in rows],
            "next_cursor": rows[-1].id if has_more and rows else None,
            "has_more": has_more, "limit": limit, "object_type": object_type}
