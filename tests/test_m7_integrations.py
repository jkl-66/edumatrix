from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, DBLearningEvent, DBOrganization
from app.m7_integrations import DeliveryTarget, enqueue_learning_event, learning_event_to_xapi, record_delivery_attempt


def _session_event():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    org = DBOrganization(id="org-m7", name="M7 Org")
    event = DBLearningEvent(
        id="le-m7", owner_public_id="usr-m7", course_id="course-m7",
        event_type="quiz_answered", schema_version="m5.learning-event.v1",
        idempotency_key="event-m7-001", source="backend", trace_id="trace-m7",
        object_type="assessment", object_id="assessment-1", payload={"correct": True},
        occurred_at=datetime(2026, 7, 28, 8, 0),
    )
    session.add_all([org, event]); session.flush()
    return session, event


def test_xapi_mapping_retains_internal_event_and_no_private_content():
    _, event = _session_event()
    statement = learning_event_to_xapi(event)
    assert statement["id"] == event.id
    assert statement["result"]["success"] is True
    assert statement["context"]["extensions"]["https://edumatrix.local/extensions/internal-event-id"] == event.id
    assert "query" not in str(statement).lower()


def test_outbox_is_idempotent_and_external_failure_does_not_change_event():
    session, event = _session_event()
    target = DeliveryTarget(organization_id="org-m7", destination_key="mock-lrs", adapter_type="xapi")
    delivery, created = enqueue_learning_event(session, event=event, target=target)
    replay, replay_created = enqueue_learning_event(session, event=event, target=target)
    record_delivery_attempt(session, delivery=delivery, success=False, error_code="lrs_unavailable")
    assert created is True and replay_created is False and replay.id == delivery.id
    assert delivery.status == "failed" and delivery.attempt_count == 1
    assert event.event_type == "quiz_answered"


def test_delivery_retries_then_dead_letters_and_success_is_terminal():
    session, event = _session_event()
    delivery, _ = enqueue_learning_event(
        session, event=event,
        target=DeliveryTarget(organization_id="org-m7", destination_key="mock-lrs", adapter_type="xapi"),
    )
    record_delivery_attempt(session, delivery=delivery, success=False, max_attempts=2)
    record_delivery_attempt(session, delivery=delivery, success=False, max_attempts=2)
    assert delivery.status == "dead_letter"
    delivery.status = "failed"
    record_delivery_attempt(session, delivery=delivery, success=True, max_attempts=3)
    assert delivery.status == "delivered"
    attempts = delivery.attempt_count
    record_delivery_attempt(session, delivery=delivery, success=False)
    assert delivery.attempt_count == attempts and delivery.status == "delivered"
