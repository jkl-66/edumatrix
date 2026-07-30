"""Unified resource-center operations over canonical artifact objects."""

from __future__ import annotations

import difflib
import hashlib
from typing import Any, Literal

from app.database import DBArtifact, DBArtifactVersion
from app.m1_lifecycle import set_artifact_archived
from app.m1_repository import M1Repository, learner_safe_artifact_content
from app.m2_contracts import StrictModel
from app.m5_capabilities import M5CapabilityError


class ResourceArchiveRequest(StrictModel):
    archived: bool
    expected_lock_version: int


def search_resources(
    session: Any,
    *,
    owner_public_id: str,
    query: str = "",
    artifact_type: str | None = None,
    course_id: str | None = None,
    status: str | None = None,
    include_archived: bool = False,
    cursor: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    limit = max(1, min(limit, 100))
    rows = session.query(DBArtifact).filter_by(owner_public_id=owner_public_id)
    if query.strip():
        rows = rows.filter(DBArtifact.title.ilike(f"%{query.strip()}%"))
    if artifact_type:
        rows = rows.filter_by(artifact_type=artifact_type)
    if course_id:
        rows = rows.filter_by(course_id=course_id)
    if status:
        rows = rows.filter_by(status=status)
    elif not include_archived:
        rows = rows.filter(DBArtifact.archived_at.is_(None))
    if cursor:
        rows = rows.filter(DBArtifact.id > cursor)
    items = rows.order_by(DBArtifact.id).limit(limit + 1).all()
    has_more = len(items) > limit
    items = items[:limit]
    return {
        "items": [{
            "id": item.id,
            "course_id": item.course_id,
            "artifact_type": item.artifact_type,
            "title": item.title,
            "status": item.status,
            "current_version_id": item.current_version_id,
            "lock_version": item.lock_version,
            "archived": item.archived_at is not None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        } for item in items],
        "next_cursor": items[-1].id if has_more and items else None,
        "has_more": has_more,
        "limit": limit,
    }


def resource_detail(session: Any, artifact: DBArtifact) -> dict[str, Any]:
    payload = M1Repository(session).artifact_payload(artifact)
    payload["lock_version"] = artifact.lock_version
    payload["archived"] = artifact.archived_at is not None
    return payload


def compare_resource_versions(
    session: Any,
    *,
    artifact: DBArtifact,
    left_version: int,
    right_version: int,
) -> dict[str, Any]:
    versions = session.query(DBArtifactVersion).filter(
        DBArtifactVersion.artifact_id == artifact.id,
        DBArtifactVersion.version_number.in_((left_version, right_version)),
    ).all()
    by_number = {item.version_number: item for item in versions}
    if left_version not in by_number or right_version not in by_number:
        raise M5CapabilityError("resource_version_unknown", "requested artifact version does not exist")
    left = by_number[left_version]
    right = by_number[right_version]
    diff = "\n".join(difflib.unified_diff(
        left.content.splitlines(), right.content.splitlines(),
        fromfile=f"v{left_version}", tofile=f"v{right_version}", lineterm="",
    ))
    return {
        "artifact_id": artifact.id,
        "left": {"version": left_version, "content_hash": left.content_hash},
        "right": {"version": right_version, "content_hash": right.content_hash},
        "changed": left.content_hash != right.content_hash,
        "diff": diff[:200000],
        "diff_truncated": len(diff) > 200000,
    }


def export_resource_version(
    session: Any,
    *,
    artifact: DBArtifact,
    version_number: int | None = None,
) -> dict[str, Any]:
    query = session.query(DBArtifactVersion).filter_by(artifact_id=artifact.id)
    version = (
        query.filter_by(version_number=version_number).first()
        if version_number is not None
        else query.filter_by(id=artifact.current_version_id).first()
    )
    if version is None:
        raise M5CapabilityError("resource_version_unknown", "artifact has no exportable version")
    actual_hash = hashlib.sha256(version.content.encode("utf-8")).hexdigest()
    if actual_hash != version.content_hash:
        raise M5CapabilityError("resource_hash_mismatch", "artifact content differs from its persisted hash")
    export_content = learner_safe_artifact_content(artifact.artifact_type, version.content)
    export_hash = hashlib.sha256(export_content.encode("utf-8")).hexdigest()
    return {
        "schema_version": "m5.resource-export.v1",
        "artifact": {
            "id": artifact.id,
            "type": artifact.artifact_type,
            "title": artifact.title,
            "course_id": artifact.course_id,
            "status": artifact.status,
        },
        "version": {
            "id": version.id,
            "number": version.version_number,
            "content_format": version.content_format,
            "persisted_content_hash": version.content_hash,
            "export_content_hash": export_hash,
            "metadata": version.metadata_json or {},
            "content": export_content,
        },
    }


def set_resource_archived(
    session: Any,
    *,
    artifact: DBArtifact,
    actor_public_id: str,
    archived: bool,
    expected_lock_version: int,
) -> dict[str, Any]:
    if artifact.lock_version != expected_lock_version:
        raise M5CapabilityError("resource_version_conflict", "resource lock version changed")
    if (artifact.archived_at is not None) == archived:
        return resource_detail(session, artifact)
    set_artifact_archived(
        session, artifact=artifact, actor_public_id=actor_public_id, archived=archived,
    )
    session.commit()
    return resource_detail(session, artifact)
