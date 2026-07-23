"""Plan, learning-event, memory and governance lifecycle operations."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func

from app.database import (
    DBAuditLog,
    DBArtifact,
    DBLearningEvent,
    DBLearningPath,
    DBMemoryItem,
    DBPathNode,
    DBPlanDraft,
    DBPlanVersion,
    DBPublication,
    DBReviewDecision,
    DBUser,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def record_audit(
    session: Any, *, actor_public_id: str | None, action: str,
    object_type: str, object_id: str, trace_id: str | None = None,
    outcome: str = "success", metadata: dict[str, Any] | None = None
) -> DBAuditLog:
    sanitized = {
        key: value for key, value in (metadata or {}).items()
        if key.lower() not in {"password", "token", "api_key", "secret", "content"}
    }
    row = DBAuditLog(
        actor_public_id=actor_public_id, action=action, object_type=object_type,
        object_id=object_id, trace_id=trace_id or f"trace-{uuid.uuid4().hex}",
        outcome=outcome, metadata_json=sanitized
    )
    session.add(row)
    session.flush()
    return row


def add_plan_version(
    session: Any, *, plan: DBPlanDraft, content: dict[str, Any],
    created_by_public_id: str, profile_snapshot_id: str | None = None
) -> DBPlanVersion:
    number = session.query(func.max(DBPlanVersion.version_number)).filter_by(plan_draft_id=plan.id).scalar()
    canonical = __import__("json").dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    version = DBPlanVersion(
        plan_draft_id=plan.id, version_number=int(number or 0) + 1,
        profile_snapshot_id=profile_snapshot_id, content=content,
        content_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        created_by_public_id=created_by_public_id
    )
    session.add(version)
    session.flush()
    return version


def publish_learning_path(
    session: Any, *, owner_public_id: str, course_id: str | None,
    plan_version: DBPlanVersion, nodes: list[dict[str, Any]]
) -> DBLearningPath:
    path = DBLearningPath(
        owner_public_id=owner_public_id, course_id=course_id,
        source_plan_version_id=plan_version.id
    )
    session.add(path)
    session.flush()
    for sequence, item in enumerate(nodes, start=1):
        session.add(DBPathNode(
            learning_path_id=path.id, sequence=sequence,
            node_type=item["node_type"], target_object_id=item.get("target_object_id"),
            title=item["title"], prerequisites=item.get("prerequisites", [])
        ))
    session.flush()
    return path


def persist_legacy_learning_event(session: Any, event: Any, event_type: str) -> DBLearningEvent:
    student_id = str(getattr(event, "student_id", "") or "")
    user = session.query(DBUser).filter(DBUser.username == student_id).first() if student_id else None
    payload = asdict(event) if is_dataclass(event) else dict(event)
    row = DBLearningEvent(
        owner_public_id=user.public_id if user else None,
        legacy_student_id=student_id or None,
        event_type=event_type,
        trace_id=f"trace-{uuid.uuid4().hex}",
        object_type="quiz" if event_type == "quiz_attempted" else "profile",
        object_id=str(payload.get("quiz_id", "") or student_id),
        payload=payload,
    )
    session.add(row)
    session.commit()
    return row


def update_artifact_title(
    session: Any, *, artifact_id: str, owner_public_id: str,
    expected_version: int, title: str
) -> DBArtifact:
    updated = (
        session.query(DBArtifact)
        .filter(
            DBArtifact.id == artifact_id,
            DBArtifact.owner_public_id == owner_public_id,
            DBArtifact.lock_version == expected_version,
            DBArtifact.archived_at.is_(None),
        )
        .update({DBArtifact.title: title, DBArtifact.lock_version: expected_version + 1})
    )
    if updated != 1:
        raise HTTPException(status_code=409, detail="对象版本冲突或已归档")
    session.flush()
    return session.query(DBArtifact).filter_by(id=artifact_id).one()


def set_artifact_archived(
    session: Any, *, artifact: DBArtifact, actor_public_id: str, archived: bool
) -> None:
    artifact.archived_at = utcnow() if archived else None
    artifact.status = "archived" if archived else "draft"
    artifact.lock_version += 1
    record_audit(
        session, actor_public_id=actor_public_id,
        action="artifact.archive" if archived else "artifact.restore",
        object_type="artifact", object_id=artifact.id,
        metadata={"archived": archived}
    )


def create_review_and_publication(
    session: Any, *, artifact_version_id: str, reviewer_public_id: str,
    decision: str, rationale: str = "", visibility: str = "private"
) -> tuple[DBReviewDecision, DBPublication | None]:
    review = DBReviewDecision(
        artifact_version_id=artifact_version_id, review_type="human",
        reviewer_public_id=reviewer_public_id, decision=decision, rationale=rationale
    )
    session.add(review)
    session.flush()
    publication = None
    if decision == "approved":
        publication = DBPublication(
            artifact_version_id=artifact_version_id, review_decision_id=review.id,
            visibility=visibility, published_by_public_id=reviewer_public_id
        )
        session.add(publication)
        session.flush()
    return review, publication
