"""Versioned, replay-safe enterprise integration outbox and xAPI mapping."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Literal

from pydantic import Field

from app.database import DBIntegrationDelivery, DBLearningEvent
from app.m2_contracts import StrictModel


class M7IntegrationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class DeliveryTarget(StrictModel):
    organization_id: str = Field(min_length=1, max_length=64)
    destination_key: str = Field(min_length=1, max_length=128)
    adapter_type: Literal["xapi", "webhook", "lms", "hr"]


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


VERBS = {
    "resource_opened": ("http://activitystrea.ms/schema/1.0/access", "accessed"),
    "quiz_answered": ("http://adlnet.gov/expapi/verbs/answered", "answered"),
    "code_tests_passed": ("http://adlnet.gov/expapi/verbs/passed", "passed"),
    "delayed_retest_passed": ("http://adlnet.gov/expapi/verbs/passed", "passed"),
    "teacher_confirmed": ("https://w3id.org/xapi/dod-isd/verbs/verified", "verified"),
}


def learning_event_to_xapi(event: DBLearningEvent) -> dict[str, Any]:
    verb_id, display = VERBS.get(
        event.event_type, ("http://adlnet.gov/expapi/verbs/experienced", "experienced"),
    )
    payload = event.payload or {}
    result: dict[str, Any] = {}
    if isinstance(payload.get("correct"), bool):
        result["success"] = payload["correct"]
    if payload.get("actual_minutes") is not None:
        result["duration"] = f"PT{int(payload['actual_minutes'])}M"
    return {
        "id": event.id,
        "actor": {"account": {"homePage": "https://edumatrix.local", "name": event.owner_public_id}},
        "verb": {"id": verb_id, "display": {"en-US": display}},
        "object": {
            "id": f"https://edumatrix.local/objects/{event.object_type}/{event.object_id}",
            "objectType": "Activity",
            "definition": {"type": f"https://edumatrix.local/activity-types/{event.object_type}"},
        },
        "result": result,
        "context": {
            "extensions": {
                "https://edumatrix.local/extensions/internal-event-id": event.id,
                "https://edumatrix.local/extensions/course-id": event.course_id,
                "https://edumatrix.local/extensions/schema-version": event.schema_version,
            }
        },
        "timestamp": event.occurred_at.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def enqueue_learning_event(
    session: Any, *, event: DBLearningEvent, target: DeliveryTarget,
) -> tuple[DBIntegrationDelivery, bool]:
    if target.adapter_type != "xapi":
        raise M7IntegrationError("adapter_mismatch", "learning event mapping currently supports xapi only")
    payload = learning_event_to_xapi(event)
    key = f"xapi:{event.id}:v1"
    existing = session.query(DBIntegrationDelivery).filter_by(
        organization_id=target.organization_id, destination_key=target.destination_key, idempotency_key=key,
    ).first()
    if existing is not None:
        if existing.payload_hash != _hash(payload):
            raise M7IntegrationError("delivery_idempotency_conflict", "delivery key is bound to another payload")
        return existing, False
    row = DBIntegrationDelivery(
        organization_id=target.organization_id, adapter_type="xapi", adapter_version="xapi-1.0.3-map-v1",
        destination_key=target.destination_key, idempotency_key=key, source_object_type="learning_event",
        source_object_id=event.id, payload=payload, payload_hash=_hash(payload), status="pending",
    )
    session.add(row)
    session.flush()
    return row, True


def record_delivery_attempt(
    session: Any, *, delivery: DBIntegrationDelivery, success: bool, error_code: str = "", max_attempts: int = 5,
) -> DBIntegrationDelivery:
    if delivery.status == "delivered":
        return delivery
    delivery.attempt_count += 1
    if success:
        delivery.status = "delivered"
        delivery.delivered_at = _now()
        delivery.last_error_code = ""
        delivery.next_attempt_at = None
    else:
        delivery.last_error_code = error_code or "delivery_failed"
        if delivery.attempt_count >= max_attempts:
            delivery.status = "dead_letter"
            delivery.next_attempt_at = None
        else:
            delivery.status = "failed"
            delivery.next_attempt_at = _now() + timedelta(minutes=min(60, 2 ** delivery.attempt_count))
    session.flush()
    return delivery
