"""Normalized profile-evidence writes with legacy JSON compatibility."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable

from app.database import DBLearningEvent, DBProfileEvidence, DBStudentProfile, DBUser


def _bounded_score(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _observed_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    text = str(value or "").strip()
    if text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
        except ValueError:
            pass
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _legacy_key(student_id: str, index: int, item: dict[str, Any]) -> str:
    identity = {
        "student_id": student_id,
        "index": index,
        "source": item.get("source"),
        "timestamp": item.get("timestamp"),
    }
    raw = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sync_legacy_profile_evidence(
    session: Any,
    profile: DBStudentProfile,
    *,
    trace_id: str | None = None,
) -> list[DBProfileEvidence]:
    """Idempotently project legacy JSON evidence while keeping it untouched."""
    raw_items: Iterable[Any] = profile.profile_evidence or []
    user = session.query(DBUser).filter(
        (DBUser.username == profile.student_id) | (DBUser.public_id == profile.student_id)
    ).first()
    owner_public_id = user.public_id if user else None
    rows: list[DBProfileEvidence] = []
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            continue
        key = _legacy_key(profile.student_id, index, raw_item)
        row = session.query(DBProfileEvidence).filter_by(
            legacy_student_id=profile.student_id, legacy_key=key
        ).first()
        if row is None:
            row = DBProfileEvidence(
                legacy_student_id=profile.student_id,
                legacy_key=key,
            )
            session.add(row)
        row.owner_public_id = owner_public_id
        row.source_type = str(raw_item.get("source") or "legacy_unknown")
        row.source_object_id = raw_item.get("source_object_id") or raw_item.get("source_id")
        row.features = [str(item) for item in (raw_item.get("features") or []) if str(item)]
        row.weight = _bounded_score(raw_item.get("weight"))
        row.confidence = _bounded_score(raw_item.get("confidence"))
        row.evidence_summary = str(raw_item.get("text") or "")[:2048]
        row.observed_at = _observed_at(raw_item.get("timestamp"))
        row.status = "active" if owner_public_id else "legacy_unresolved"
        row.evidence_version = str(raw_item.get("version") or "1")
        row.trace_id = raw_item.get("trace_id") or trace_id
        rows.append(row)
    session.flush()
    return rows


def profile_evidence_compat_view(session: Any, student_id: str) -> list[dict[str, Any]]:
    """Read normalized rows, falling back to the untouched legacy JSON array."""
    rows = session.query(DBProfileEvidence).filter_by(legacy_student_id=student_id).order_by(
        DBProfileEvidence.observed_at, DBProfileEvidence.id
    ).all()
    if rows:
        return [{
            "id": row.id,
            "source": row.source_type,
            "source_object_id": row.source_object_id,
            "features": list(row.features or []),
            "weight": row.weight,
            "confidence": row.confidence,
            "text": row.evidence_summary,
            "timestamp": row.observed_at.isoformat() if row.observed_at else "",
            "status": row.status,
            "version": row.evidence_version,
            "trace_id": row.trace_id,
        } for row in rows]
    profile = session.query(DBStudentProfile).filter_by(student_id=student_id).first()
    return list(profile.profile_evidence or []) if profile else []


def project_learning_event_evidence(
    session: Any, event: DBLearningEvent,
) -> DBProfileEvidence | None:
    """Project accepted event evidence without changing any mastery aggregate."""
    if event.evidence_status != "accepted" or not event.mastery_eligible:
        return None
    user = session.query(DBUser).filter_by(public_id=event.owner_public_id).first()
    student_id = user.username if user else str(event.owner_public_id or "")
    if not student_id:
        return None
    legacy_key = hashlib.sha256(f"learning-event:{event.id}".encode("utf-8")).hexdigest()
    row = session.query(DBProfileEvidence).filter_by(
        legacy_student_id=student_id,
        legacy_key=legacy_key,
    ).first()
    if row is None:
        row = DBProfileEvidence(
            legacy_student_id=student_id,
            legacy_key=legacy_key,
        )
        session.add(row)
    row.owner_public_id = event.owner_public_id
    row.source_type = f"learning_event:{event.action}"[:64]
    row.source_object_id = event.id
    row.features = [event.action, event.object_type, event.object_id]
    row.weight = _bounded_score(event.evidence_strength)
    row.confidence = _bounded_score((event.payload or {}).get("confidence", 1.0))
    row.evidence_summary = (
        f"{event.action} · {event.object_type}:{event.object_id}"
    )[:2048]
    row.observed_at = event.occurred_at
    row.status = "active"
    row.evidence_version = event.payload_version
    row.trace_id = event.trace_id
    session.flush()
    return row
