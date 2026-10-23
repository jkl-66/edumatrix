"""Signed local webhook adapter with minimal envelopes and replay protection."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import secrets
from typing import Any, Literal

from app.database import (
    DBCertification,
    DBCertificationLifecycleEvent,
    DBIntegrationDelivery,
    DBIntegrationDeliveryEvent,
    DBLocalWebhookEndpoint,
    DBOrganizationMembership,
    DBTrainingAssignment,
    DBUser,
    DBWebhookAcceptedNonce,
    DBWebhookEvent,
    DBWebhookReceipt,
)
from app.m7_integrations import (
    M7IntegrationError,
    _delivery_event,
    _hash,
    _now,
    _require_integration_admin,
    record_delivery_attempt,
)


WebhookEventType = Literal[
    "training.assignment.created",
    "training.assignment.completed",
    "certification.issued",
    "certification.revoked",
]


def _canonical(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _timestamp(value: datetime) -> int:
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return int(aware.timestamp())


def _sign(secret: str, timestamp_value: int, nonce: str, payload: dict[str, Any]) -> str:
    message = f"{timestamp_value}.{nonce}.{_canonical(payload)}".encode("utf-8")
    return "v1=" + hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _receipt(
    session: Any, *, endpoint: DBLocalWebhookEndpoint, delivery_id: str | None,
    event_id: str, nonce: str, timestamp_value: int, signature: str,
    payload_hash: str, outcome: str, reason_code: str,
) -> DBWebhookReceipt:
    row = DBWebhookReceipt(
        endpoint_id=endpoint.id, organization_id=endpoint.organization_id,
        delivery_id=delivery_id, event_id=event_id, nonce=nonce,
        timestamp_value=timestamp_value, signature_prefix=(signature or "")[:20],
        payload_hash=payload_hash, outcome=outcome, reason_code=reason_code,
    )
    session.add(row)
    session.flush()
    return row


def ensure_local_webhook_endpoint(
    session: Any, *, actor: DBUser, organization_id: str,
    destination_key: str = "competition-local-webhook",
) -> tuple[DBLocalWebhookEndpoint, bool]:
    _require_integration_admin(session, actor=actor, organization_id=organization_id)
    existing = session.query(DBLocalWebhookEndpoint).filter_by(
        organization_id=organization_id, destination_key=destination_key,
    ).first()
    if existing is not None:
        return existing, False
    secret = secrets.token_urlsafe(32)
    row = DBLocalWebhookEndpoint(
        organization_id=organization_id, name="比赛本地签名接收端",
        destination_key=destination_key, signing_secret=secret,
        secret_fingerprint=hashlib.sha256(secret.encode("utf-8")).hexdigest(),
        created_by_public_id=actor.public_id,
    )
    session.add(row)
    session.commit()
    return row, True


def _source_snapshot(
    session: Any, *, organization_id: str, event_type: WebhookEventType, source_object_id: str,
) -> tuple[str, dict[str, Any], datetime]:
    if event_type.startswith("training.assignment"):
        row = session.query(DBTrainingAssignment).filter_by(id=source_object_id).first()
        if row is None:
            raise M7IntegrationError("webhook_source_not_found", "training assignment does not exist")
        if row.organization_id != organization_id:
            raise M7IntegrationError("webhook_source_forbidden", "training assignment belongs to another organization")
        if event_type.endswith("completed") and row.status != "completed":
            raise M7IntegrationError("webhook_source_state_invalid", "training assignment is not completed")
        if event_type.endswith("created") and row.status not in {"assigned", "in_progress", "completed"}:
            raise M7IntegrationError("webhook_source_state_invalid", "training assignment cannot emit a created event")
        return "training_assignment", {
            "assignment_id": row.id,
            "cohort_id": row.cohort_id,
            "learner_public_id": row.learner_public_id,
            "status": row.status,
        }, row.assigned_at or _now()

    row = session.query(DBCertification).filter_by(id=source_object_id).first()
    if row is None:
        raise M7IntegrationError("webhook_source_not_found", "certification does not exist")
    if row.organization_id != organization_id:
        raise M7IntegrationError("webhook_source_forbidden", "certification belongs to another organization")
    if event_type == "certification.issued" and row.status not in {"active", "revoked", "expired"}:
        raise M7IntegrationError("webhook_source_state_invalid", "certification has not been issued")
    occurred_at = row.issued_at or _now()
    status = "active"
    if event_type == "certification.revoked":
        lifecycle = session.query(DBCertificationLifecycleEvent).filter_by(
            certification_id=row.id, action="revoke",
        ).order_by(DBCertificationLifecycleEvent.created_at.desc()).first()
        if lifecycle is None or row.status != "revoked":
            raise M7IntegrationError("webhook_source_state_invalid", "certification has no canonical revocation event")
        occurred_at = lifecycle.created_at or row.revoked_at or _now()
        status = "revoked"
    return "certification", {
        "certification_id": row.id,
        "job_level_id": row.job_level_id,
        "learner_public_id": row.learner_public_id,
        "status": status,
    }, occurred_at


def create_webhook_event(
    session: Any, *, actor: DBUser, organization_id: str,
    event_type: WebhookEventType, source_object_id: str,
) -> tuple[DBWebhookEvent, bool]:
    _require_integration_admin(session, actor=actor, organization_id=organization_id)
    source_type, data, occurred_at = _source_snapshot(
        session, organization_id=organization_id, event_type=event_type,
        source_object_id=source_object_id,
    )
    existing = session.query(DBWebhookEvent).filter_by(
        organization_id=organization_id, event_type=event_type,
        source_object_type=source_type, source_object_id=source_object_id,
    ).first()
    if existing is not None:
        return existing, False
    event_id = f"whevt_{hashlib.sha256(f'{organization_id}:{event_type}:{source_object_id}'.encode()).hexdigest()[:24]}"
    payload = {
        "id": event_id,
        "type": event_type,
        "schema_version": "webhook-envelope-v1",
        "occurred_at": occurred_at.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
        "organization_id": organization_id,
        "data": data,
    }
    row = DBWebhookEvent(
        id=event_id, organization_id=organization_id, event_type=event_type,
        source_object_type=source_type, source_object_id=source_object_id,
        payload=payload, payload_hash=_hash(payload), occurred_at=occurred_at,
        created_by_public_id=actor.public_id,
    )
    session.add(row)
    session.commit()
    return row, True


def enqueue_webhook_event(
    session: Any, *, actor: DBUser, event_id: str, endpoint_id: str,
) -> tuple[DBIntegrationDelivery, bool]:
    event = session.query(DBWebhookEvent).filter_by(id=event_id).first()
    endpoint = session.query(DBLocalWebhookEndpoint).filter_by(id=endpoint_id).first()
    if event is None or endpoint is None:
        raise M7IntegrationError("webhook_object_not_found", "webhook event or endpoint does not exist")
    _require_integration_admin(session, actor=actor, organization_id=event.organization_id)
    if endpoint.organization_id != event.organization_id:
        raise M7IntegrationError("webhook_endpoint_forbidden", "endpoint belongs to another organization")
    if endpoint.status != "active":
        raise M7IntegrationError("webhook_endpoint_disabled", "webhook endpoint is disabled")
    key = f"webhook:{event.id}:v1"
    existing = session.query(DBIntegrationDelivery).filter_by(
        organization_id=event.organization_id, destination_key=endpoint.destination_key,
        idempotency_key=key,
    ).first()
    if existing is not None:
        if existing.payload_hash != event.payload_hash:
            raise M7IntegrationError("delivery_idempotency_conflict", "webhook delivery key has another payload")
        return existing, False
    row = DBIntegrationDelivery(
        organization_id=event.organization_id, adapter_type="webhook",
        adapter_version="hmac-sha256-envelope-v1", destination_key=endpoint.destination_key,
        idempotency_key=key, source_object_type="webhook_event",
        source_object_id=event.id, payload=event.payload, payload_hash=event.payload_hash,
        status="pending",
    )
    session.add(row)
    session.flush()
    _delivery_event(
        session, delivery=row, actor_public_id=actor.public_id, action="webhook_enqueue",
        from_status="none", evidence={"event_id": event.id, "payload_hash": event.payload_hash},
    )
    session.commit()
    return row, True


def receive_signed_webhook(
    session: Any, *, endpoint_id: str, payload: dict[str, Any], timestamp_value: int,
    nonce: str, signature: str, delivery_id: str | None = None, now: datetime | None = None,
) -> tuple[DBWebhookReceipt, bool]:
    endpoint = session.query(DBLocalWebhookEndpoint).filter_by(id=endpoint_id).first()
    if endpoint is None:
        raise M7IntegrationError("webhook_endpoint_not_found", "webhook endpoint does not exist")
    event_id = str(payload.get("id") or "")
    payload_hash = _hash(payload)
    current = now or _now()
    current_ts = _timestamp(current)
    reason = "accepted"
    if endpoint.status != "active":
        reason = "endpoint_disabled"
    elif not event_id or not nonce:
        reason = "headers_or_event_missing"
    elif abs(current_ts - timestamp_value) > endpoint.replay_window_seconds:
        reason = "timestamp_outside_window"
    elif not hmac.compare_digest(_sign(endpoint.signing_secret, timestamp_value, nonce, payload), signature):
        reason = "signature_invalid"
    elif session.query(DBWebhookAcceptedNonce).filter_by(endpoint_id=endpoint.id, nonce=nonce).first():
        reason = "nonce_replayed"
    elif session.query(DBWebhookAcceptedNonce).filter_by(endpoint_id=endpoint.id, event_id=event_id).first():
        reason = "event_replayed"
    event = session.query(DBWebhookEvent).filter_by(id=event_id, organization_id=endpoint.organization_id).first()
    if reason == "accepted" and (event is None or event.payload_hash != payload_hash):
        reason = "event_payload_unknown"
    accepted = reason == "accepted"
    receipt = _receipt(
        session, endpoint=endpoint, delivery_id=delivery_id, event_id=event_id or "missing",
        nonce=nonce or "missing", timestamp_value=timestamp_value, signature=signature,
        payload_hash=payload_hash, outcome="accepted" if accepted else "rejected", reason_code=reason,
    )
    if accepted:
        session.add(DBWebhookAcceptedNonce(
            endpoint_id=endpoint.id, event_id=event_id, nonce=nonce,
            signature_hash=hashlib.sha256(signature.encode("utf-8")).hexdigest(),
        ))
    session.commit()
    return receipt, accepted


def deliver_webhook_locally(
    session: Any, *, actor: DBUser, delivery_id: str, nonce: str | None = None,
    timestamp_value: int | None = None,
    fault: Literal["none", "invalid_signature", "stale_timestamp"] = "none",
) -> tuple[DBIntegrationDelivery, DBWebhookReceipt, bool]:
    delivery = session.query(DBIntegrationDelivery).filter_by(id=delivery_id).first()
    if delivery is None or delivery.adapter_type != "webhook":
        raise M7IntegrationError("webhook_delivery_not_found", "webhook delivery does not exist")
    _require_integration_admin(session, actor=actor, organization_id=delivery.organization_id)
    if delivery.status == "dead_letter":
        raise M7IntegrationError("dead_letter_requires_manual_requeue", "dead-letter delivery requires explicit requeue")
    existing = session.query(DBWebhookReceipt).filter_by(delivery_id=delivery.id, outcome="accepted").first()
    if delivery.status == "delivered" and existing is not None:
        return delivery, existing, False
    endpoint = session.query(DBLocalWebhookEndpoint).filter_by(
        organization_id=delivery.organization_id, destination_key=delivery.destination_key,
    ).one()
    sent_at = timestamp_value if timestamp_value is not None else _timestamp(_now())
    if fault == "stale_timestamp":
        sent_at -= endpoint.replay_window_seconds + 1
    request_nonce = nonce or secrets.token_urlsafe(18)
    signature = _sign(endpoint.signing_secret, sent_at, request_nonce, delivery.payload)
    if fault == "invalid_signature":
        signature = "v1=" + ("0" * 64)
    receipt, accepted = receive_signed_webhook(
        session, endpoint_id=endpoint.id, payload=delivery.payload,
        timestamp_value=sent_at, nonce=request_nonce, signature=signature,
        delivery_id=delivery.id,
    )
    previous = delivery.status
    record_delivery_attempt(
        session, delivery=delivery, success=accepted,
        error_code="" if accepted else receipt.reason_code,
    )
    _delivery_event(
        session, delivery=delivery, actor_public_id=actor.public_id,
        action="webhook_accept" if accepted else "webhook_reject", from_status=previous,
        evidence={"receipt_id": receipt.id, "reason_code": receipt.reason_code,
                  "signature_version": "v1", "secret_exposed": False},
    )
    session.commit()
    return delivery, receipt, True


def webhook_workspace(session: Any, *, actor: DBUser, organization_id: str) -> dict[str, Any]:
    _require_integration_admin(session, actor=actor, organization_id=organization_id)
    endpoints = session.query(DBLocalWebhookEndpoint).filter_by(organization_id=organization_id).all()
    events = session.query(DBWebhookEvent).filter_by(organization_id=organization_id).order_by(DBWebhookEvent.created_at.desc()).limit(30).all()
    deliveries = session.query(DBIntegrationDelivery).filter_by(
        organization_id=organization_id, adapter_type="webhook",
    ).order_by(DBIntegrationDelivery.created_at.desc()).limit(30).all()
    receipts = session.query(DBWebhookReceipt).filter_by(organization_id=organization_id).order_by(DBWebhookReceipt.received_at.desc()).limit(50).all()
    candidates: list[dict[str, Any]] = []
    for row in session.query(DBTrainingAssignment).filter_by(organization_id=organization_id).order_by(DBTrainingAssignment.assigned_at.desc()).limit(10).all():
        candidates.append({
            "event_type": "training.assignment.created", "source_object_id": row.id,
            "source_object_type": "training_assignment", "status": row.status,
            "label": f"培训分配 · {row.id}", "eligible": row.status in {"assigned", "in_progress", "completed"},
        })
        candidates.append({
            "event_type": "training.assignment.completed", "source_object_id": row.id,
            "source_object_type": "training_assignment", "status": row.status,
            "label": f"培训完成 · {row.id}", "eligible": row.status == "completed",
        })
    for row in session.query(DBCertification).filter_by(organization_id=organization_id).order_by(DBCertification.issued_at.desc()).limit(10).all():
        candidates.append({
            "event_type": "certification.issued", "source_object_id": row.id,
            "source_object_type": "certification", "status": row.status,
            "label": f"认证签发 · {row.id}", "eligible": row.status in {"active", "revoked", "expired"},
        })
        lifecycle = session.query(DBCertificationLifecycleEvent).filter_by(certification_id=row.id, action="revoke").first()
        candidates.append({
            "event_type": "certification.revoked", "source_object_id": row.id,
            "source_object_type": "certification", "status": row.status,
            "label": f"认证撤销 · {row.id}", "eligible": row.status == "revoked" and lifecycle is not None,
        })
    return {
        "endpoints": [{
            "id": row.id, "name": row.name, "destination_key": row.destination_key,
            "secret_fingerprint": row.secret_fingerprint, "status": row.status,
            "replay_window_seconds": row.replay_window_seconds, "lock_version": row.lock_version,
        } for row in endpoints],
        "events": [{
            "id": row.id, "event_type": row.event_type,
            "source_object_type": row.source_object_type, "source_object_id": row.source_object_id,
            "payload": row.payload, "payload_hash": row.payload_hash,
            "occurred_at": row.occurred_at.isoformat(),
        } for row in events],
        "deliveries": [{
            "id": row.id, "event_id": row.source_object_id, "destination_key": row.destination_key,
            "status": row.status, "attempt_count": row.attempt_count,
            "last_error_code": row.last_error_code or "", "payload_hash": row.payload_hash,
        } for row in deliveries],
        "receipts": [{
            "id": row.id, "delivery_id": row.delivery_id, "event_id": row.event_id,
            "nonce": row.nonce, "timestamp": row.timestamp_value,
            "signature_prefix": row.signature_prefix, "payload_hash": row.payload_hash,
            "outcome": row.outcome, "reason_code": row.reason_code,
            "received_at": row.received_at.isoformat(),
        } for row in receipts],
        "candidates": candidates,
        "security": {
            "algorithm": "HMAC-SHA256", "signature_version": "v1",
            "replay_guards": ["timestamp_window", "nonce_once", "event_once"],
            "secret_returned_by_api": False,
            "minimal_fields": ["organization_id", "object_id", "learner_public_id", "status", "occurred_at"],
            "excluded_fields": ["name", "email", "score", "evidence_body", "api_key"],
        },
    }
