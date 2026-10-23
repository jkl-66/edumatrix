"""Versioned, replay-safe enterprise integration outbox and xAPI mapping."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Literal

from pydantic import Field

from app.database import (
    DBCmi5Session,
    DBCmi5SessionEvent,
    DBIntegrationDelivery,
    DBIntegrationDeliveryEvent,
    DBLearningEvent,
    DBLocalLRSStatement,
    DBOrganization,
    DBOrganizationMembership,
    DBUser,
    new_public_id,
)
from app.identity import normalize_role
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
    "cmi5_launched": ("http://adlnet.gov/expapi/verbs/launched", "launched"),
    "cmi5_initialized": ("http://adlnet.gov/expapi/verbs/initialized", "initialized"),
    "cmi5_completed": ("http://adlnet.gov/expapi/verbs/completed", "completed"),
    "cmi5_terminated": ("http://adlnet.gov/expapi/verbs/terminated", "terminated"),
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


def _delivery_event(
    session: Any, *, delivery: DBIntegrationDelivery, actor_public_id: str | None,
    action: str, from_status: str, evidence: dict[str, Any],
) -> DBIntegrationDeliveryEvent:
    row = DBIntegrationDeliveryEvent(
        delivery_id=delivery.id, organization_id=delivery.organization_id,
        actor_public_id=actor_public_id, action=action, from_status=from_status,
        to_status=delivery.status, attempt_count=delivery.attempt_count,
        error_code=delivery.last_error_code or "", evidence_snapshot=evidence,
        evidence_hash=_hash(evidence),
    )
    session.add(row)
    return row


def _require_integration_admin(
    session: Any, *, actor: DBUser, organization_id: str
) -> DBOrganization:
    if normalize_role(actor.role) != "admin":
        raise M7IntegrationError("integration_forbidden", "only administrators can manage integration delivery")
    organization = session.query(DBOrganization).filter_by(id=organization_id).first()
    membership = session.query(DBOrganizationMembership).filter_by(
        organization_id=organization_id,
        user_public_id=actor.public_id,
        role="admin",
        status="active",
    ).first()
    if organization is None or membership is None:
        raise M7IntegrationError("integration_forbidden", "administrator does not manage this organization")
    return organization


def enqueue_organization_learning_event(
    session: Any,
    *,
    actor: DBUser,
    organization_id: str,
    event_id: str,
    destination_key: str,
) -> tuple[DBIntegrationDelivery, bool]:
    _require_integration_admin(session, actor=actor, organization_id=organization_id)
    event = session.query(DBLearningEvent).filter_by(id=event_id).first()
    if event is None:
        raise M7IntegrationError("learning_event_not_found", "learning event does not exist")
    learner_membership = session.query(DBOrganizationMembership).filter_by(
        organization_id=organization_id,
        user_public_id=event.owner_public_id,
        status="active",
    ).first()
    if learner_membership is None:
        raise M7IntegrationError(
            "event_organization_mismatch",
            "learning event owner does not belong to the target organization",
        )
    delivery, created = enqueue_learning_event(
        session,
        event=event,
        target=DeliveryTarget(
            organization_id=organization_id,
            destination_key=destination_key,
            adapter_type="xapi",
        ),
    )
    if created:
        _delivery_event(
            session, delivery=delivery, actor_public_id=actor.public_id,
            action="enqueue", from_status="none",
            evidence={"event_id": event.id, "payload_hash": delivery.payload_hash},
        )
    session.commit()
    return delivery, created


def simulate_delivery_attempt(
    session: Any,
    *,
    actor: DBUser,
    delivery_id: str,
    success: bool,
    error_code: str = "mock_lrs_unavailable",
) -> DBIntegrationDelivery:
    delivery = session.query(DBIntegrationDelivery).filter_by(id=delivery_id).first()
    if delivery is None:
        raise M7IntegrationError("delivery_not_found", "integration delivery does not exist")
    _require_integration_admin(
        session, actor=actor, organization_id=delivery.organization_id
    )
    if delivery.status == "dead_letter":
        raise M7IntegrationError(
            "dead_letter_requires_manual_requeue",
            "dead-letter delivery cannot be retried without an explicit requeue workflow",
        )
    previous = delivery.status
    record_delivery_attempt(
        session,
        delivery=delivery,
        success=success,
        error_code="" if success else error_code,
    )
    _delivery_event(
        session, delivery=delivery, actor_public_id=actor.public_id,
        action="attempt_success" if success else "attempt_failure", from_status=previous,
        evidence={"transport": "simulation", "network_sent": False, "error_code": "" if success else error_code},
    )
    session.commit()
    return delivery


def deliver_to_local_lrs(
    session: Any, *, actor: DBUser, delivery_id: str,
) -> tuple[DBIntegrationDelivery, DBLocalLRSStatement, bool]:
    delivery = session.query(DBIntegrationDelivery).filter_by(id=delivery_id).first()
    if delivery is None:
        raise M7IntegrationError("delivery_not_found", "integration delivery does not exist")
    _require_integration_admin(session, actor=actor, organization_id=delivery.organization_id)
    if delivery.adapter_type != "xapi":
        raise M7IntegrationError("adapter_mismatch", "local LRS accepts xAPI deliveries only")
    if delivery.status == "dead_letter":
        raise M7IntegrationError("dead_letter_requires_manual_requeue", "dead-letter delivery requires explicit requeue")
    payload = delivery.payload or {}
    statement_id = str(payload.get("id", "")).strip()
    verb_id = str((payload.get("verb") or {}).get("id", "")).strip()
    object_id = str((payload.get("object") or {}).get("id", "")).strip()
    if not statement_id or not verb_id or not object_id:
        raise M7IntegrationError("invalid_xapi_statement", "xAPI statement requires id, verb.id and object.id")
    statement_hash = _hash(payload)
    existing = session.query(DBLocalLRSStatement).filter_by(
        organization_id=delivery.organization_id,
        destination_key=delivery.destination_key,
        statement_id=statement_id,
    ).first()
    if existing:
        if existing.statement_hash != statement_hash or existing.delivery_id != delivery.id:
            raise M7IntegrationError("lrs_statement_id_conflict", "statement id is bound to another payload")
        return delivery, existing, False
    previous = delivery.status
    row = DBLocalLRSStatement(
        organization_id=delivery.organization_id, destination_key=delivery.destination_key,
        statement_id=statement_id, delivery_id=delivery.id,
        actor_public_id=(payload.get("actor") or {}).get("account", {}).get("name"),
        verb_id=verb_id, object_id=object_id, statement=payload, statement_hash=statement_hash,
    )
    session.add(row)
    record_delivery_attempt(session, delivery=delivery, success=True)
    _delivery_event(
        session, delivery=delivery, actor_public_id=actor.public_id,
        action="local_lrs_accept", from_status=previous,
        evidence={"statement_id": statement_id, "statement_hash": statement_hash, "network_sent": False},
    )
    session.commit()
    return delivery, row, True


def requeue_dead_letter(
    session: Any, *, actor: DBUser, delivery_id: str,
) -> DBIntegrationDelivery:
    delivery = session.query(DBIntegrationDelivery).filter_by(id=delivery_id).first()
    if delivery is None:
        raise M7IntegrationError("delivery_not_found", "integration delivery does not exist")
    _require_integration_admin(session, actor=actor, organization_id=delivery.organization_id)
    if delivery.status != "dead_letter":
        raise M7IntegrationError("delivery_not_dead_letter", "only dead-letter deliveries can be requeued")
    previous = delivery.status
    delivery.status = "pending"
    delivery.last_error_code = ""
    delivery.next_attempt_at = _now()
    _delivery_event(
        session, delivery=delivery, actor_public_id=actor.public_id,
        action="manual_requeue", from_status=previous,
        evidence={"reason": "explicit_admin_requeue", "attempt_count_preserved": delivery.attempt_count},
    )
    session.commit()
    return delivery


def _cmi5_event(
    session: Any, *, row: DBCmi5Session, actor: DBUser,
    action: str, from_status: str, to_status: str,
) -> DBLearningEvent:
    snapshot = {
        "subset": "launch-session-complete-exit-v1", "registration": row.registration,
        "action": action, "from_status": from_status, "to_status": to_status,
        "full_cmi5_conformance_claimed": False,
    }
    session.add(DBCmi5SessionEvent(
        session_id=row.id, organization_id=row.organization_id,
        actor_public_id=actor.public_id, action=action, from_status=from_status,
        to_status=to_status, event_snapshot=snapshot, event_hash=_hash(snapshot),
    ))
    event_type = {
        "launch": "cmi5_launched", "activate": "cmi5_initialized",
        "complete": "cmi5_completed", "exit": "cmi5_terminated",
    }[action]
    event = DBLearningEvent(
        id=new_public_id("le"), owner_public_id=row.learner_public_id,
        course_id=row.course_id, event_type=event_type, schema_version="cmi5-subset-v1",
        idempotency_key=f"cmi5:{row.id}:{action}", source="local_cmi5_simulator",
        trace_id=row.registration, object_type="cmi5_session", object_id=row.id,
        payload=snapshot, occurred_at=_now(),
    )
    session.add(event)
    session.flush()
    enqueue_learning_event(
        session, event=event,
        target=DeliveryTarget(
            organization_id=row.organization_id,
            destination_key="competition-local-lrs",
            adapter_type="xapi",
        ),
    )
    return event


def launch_cmi5_session(
    session: Any, *, actor: DBUser, organization_id: str,
    learner_public_id: str, course_id: str | None, launch_key: str,
) -> tuple[DBCmi5Session, bool]:
    _require_integration_admin(session, actor=actor, organization_id=organization_id)
    membership = session.query(DBOrganizationMembership).filter_by(
        organization_id=organization_id, user_public_id=learner_public_id, status="active",
    ).first()
    if membership is None:
        raise M7IntegrationError("cmi5_learner_mismatch", "learner is not an active organization member")
    existing = session.query(DBCmi5Session).filter_by(
        organization_id=organization_id, launch_key=launch_key,
    ).first()
    if existing:
        if existing.learner_public_id != learner_public_id or existing.course_id != course_id:
            raise M7IntegrationError("cmi5_launch_conflict", "launch key is bound to another learner or course")
        return existing, False
    row = DBCmi5Session(
        organization_id=organization_id, learner_public_id=learner_public_id,
        course_id=course_id, registration=new_public_id("registration"), launch_key=launch_key,
        status="launched", created_by_public_id=actor.public_id,
    )
    session.add(row)
    session.flush()
    _cmi5_event(session, row=row, actor=actor, action="launch", from_status="none", to_status="launched")
    session.commit()
    return row, True


def transition_cmi5_session(
    session: Any, *, actor: DBUser, session_id: str,
    action: str, expected_lock_version: int,
) -> DBCmi5Session:
    row = session.query(DBCmi5Session).filter_by(id=session_id).first()
    if row is None:
        raise M7IntegrationError("cmi5_session_not_found", "cmi5 session does not exist")
    _require_integration_admin(session, actor=actor, organization_id=row.organization_id)
    if row.lock_version != expected_lock_version:
        raise M7IntegrationError("cmi5_version_conflict", "cmi5 session version changed; refresh required")
    transitions = {
        ("launched", "activate"): "active",
        ("active", "complete"): "completed",
        ("active", "exit"): "exited",
        ("completed", "exit"): "exited",
    }
    target = transitions.get((row.status, action))
    if target is None:
        raise M7IntegrationError("cmi5_transition_invalid", f"cannot {action} from {row.status}")
    previous = row.status
    row.status = target
    row.lock_version += 1
    now = _now()
    if action == "activate": row.activated_at = now
    if action == "complete": row.completed_at = now
    if action == "exit": row.exited_at = now
    _cmi5_event(session, row=row, actor=actor, action=action, from_status=previous, to_status=target)
    session.commit()
    return row


def integration_workspace(
    session: Any,
    *,
    actor: DBUser,
    organization_id: str | None = None,
) -> dict[str, Any]:
    if normalize_role(actor.role) != "admin":
        raise M7IntegrationError("integration_forbidden", "only administrators can inspect integrations")
    memberships = session.query(DBOrganizationMembership).filter_by(
        user_public_id=actor.public_id,
        role="admin",
        status="active",
    ).order_by(DBOrganizationMembership.created_at).all()
    organizations = []
    for membership in memberships:
        organization = session.query(DBOrganization).filter_by(id=membership.organization_id).one()
        organizations.append({"id": organization.id, "name": organization.name})
    truthfulness = {
        "mode": "local_simulation",
        "data_label": "本地集成模拟 · 冻结合成组织数据",
        "network_sent": False,
        "real_enterprise_connected": False,
        "real_lrs_compatibility_verified": False,
        "disclaimer": "用于验证映射、幂等队列和故障恢复，不代表已接入真实企业系统或通过真实 LRS 兼容认证。",
    }
    if not organizations:
        return {"truthfulness": truthfulness, "organizations": [], "selected": None}
    selected_id = organization_id or organizations[0]["id"]
    organization = _require_integration_admin(
        session, actor=actor, organization_id=selected_id
    )
    member_ids = [
        item.user_public_id
        for item in session.query(DBOrganizationMembership).filter_by(
            organization_id=selected_id, status="active"
        ).all()
    ]
    events = []
    if member_ids:
        for event in session.query(DBLearningEvent).filter(
            DBLearningEvent.owner_public_id.in_(member_ids)
        ).order_by(DBLearningEvent.occurred_at.desc()).limit(20).all():
            events.append({
                "id": event.id,
                "event_type": event.event_type,
                "owner_public_id": event.owner_public_id,
                "course_id": event.course_id,
                "object_type": event.object_type,
                "object_id": event.object_id,
                "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
            })
    deliveries = []
    for row in session.query(DBIntegrationDelivery).filter_by(
        organization_id=selected_id
    ).order_by(DBIntegrationDelivery.created_at.desc()).limit(50).all():
        deliveries.append({
            "id": row.id,
            "adapter_type": row.adapter_type,
            "adapter_version": row.adapter_version,
            "destination_key": row.destination_key,
            "idempotency_key": row.idempotency_key,
            "source_object_id": row.source_object_id,
            "payload": row.payload,
            "payload_hash": row.payload_hash,
            "status": row.status,
            "attempt_count": row.attempt_count,
            "last_error_code": row.last_error_code or "",
            "next_attempt_at": row.next_attempt_at.isoformat() if row.next_attempt_at else None,
            "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
        })
    statements = [{
        "id": row.id, "statement_id": row.statement_id, "delivery_id": row.delivery_id,
        "destination_key": row.destination_key, "actor_public_id": row.actor_public_id,
        "verb_id": row.verb_id, "object_id": row.object_id,
        "statement_hash": row.statement_hash,
        "received_at": row.received_at.isoformat() if row.received_at else None,
    } for row in session.query(DBLocalLRSStatement).filter_by(
        organization_id=selected_id,
    ).order_by(DBLocalLRSStatement.received_at.desc()).limit(50).all()]
    delivery_events = [{
        "id": row.id, "delivery_id": row.delivery_id, "action": row.action,
        "from_status": row.from_status, "to_status": row.to_status,
        "attempt_count": row.attempt_count, "error_code": row.error_code or "",
        "evidence_hash": row.evidence_hash,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    } for row in session.query(DBIntegrationDeliveryEvent).filter_by(
        organization_id=selected_id,
    ).order_by(DBIntegrationDeliveryEvent.created_at.desc()).limit(100).all()]
    cmi5_sessions = [{
        "id": row.id, "learner_public_id": row.learner_public_id,
        "course_id": row.course_id, "registration": row.registration,
        "launch_key": row.launch_key, "status": row.status,
        "lock_version": row.lock_version,
        "launched_at": row.launched_at.isoformat() if row.launched_at else None,
        "activated_at": row.activated_at.isoformat() if row.activated_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "exited_at": row.exited_at.isoformat() if row.exited_at else None,
    } for row in session.query(DBCmi5Session).filter_by(
        organization_id=selected_id,
    ).order_by(DBCmi5Session.launched_at.desc()).limit(30).all()]
    cmi5_events = [{
        "id": row.id, "session_id": row.session_id, "action": row.action,
        "from_status": row.from_status, "to_status": row.to_status,
        "event_hash": row.event_hash,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    } for row in session.query(DBCmi5SessionEvent).filter_by(
        organization_id=selected_id,
    ).order_by(DBCmi5SessionEvent.created_at.desc()).limit(100).all()]
    return {
        "truthfulness": truthfulness,
        "organizations": organizations,
        "selected": {
            "organization": {"id": organization.id, "name": organization.name},
            "events": events,
            "deliveries": deliveries,
            "lrs_statements": statements,
            "delivery_events": delivery_events,
            "cmi5_sessions": cmi5_sessions,
            "cmi5_events": cmi5_events,
            "transport": {
                "mode": "local_simulation",
                "network_sent": False,
                "capability_claim": "xAPI mapping, persistent local LRS inbox, outbox recovery and cmi5 launch/session/complete/exit subset tested; full conformance not claimed",
                "local_lrs_persistent": True,
                "cmi5_subset": "launch-session-complete-exit-v1",
                "full_cmi5_conformance_claimed": False,
            },
        },
    }
