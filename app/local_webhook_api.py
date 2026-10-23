"""Authenticated administration and unauthenticated local signed receiver API."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from app.auth import get_current_user
from app.database import DBUser, run_db_op
from app.local_webhook import (
    M7IntegrationError,
    create_webhook_event,
    deliver_webhook_locally,
    enqueue_webhook_event,
    ensure_local_webhook_endpoint,
    receive_signed_webhook,
    webhook_workspace,
)
from app.m2_contracts import StrictModel


router = APIRouter(prefix="/api/v1/local-webhooks", tags=["local-signed-webhooks"])


class EndpointCreate(StrictModel):
    organization_id: str = Field(min_length=1, max_length=64)
    destination_key: str = Field(default="competition-local-webhook", min_length=3, max_length=128)


class EventCreate(StrictModel):
    organization_id: str = Field(min_length=1, max_length=64)
    event_type: Literal[
        "training.assignment.created", "training.assignment.completed",
        "certification.issued", "certification.revoked",
    ]
    source_object_id: str = Field(min_length=1, max_length=64)


class DeliveryCreate(StrictModel):
    event_id: str = Field(min_length=1, max_length=64)
    endpoint_id: str = Field(min_length=1, max_length=64)


class SignedReceive(StrictModel):
    payload: dict
    timestamp: int = Field(gt=0)
    nonce: str = Field(min_length=1, max_length=128)
    signature: str = Field(min_length=3, max_length=128)
    delivery_id: str | None = Field(default=None, max_length=64)


class DeliverySend(StrictModel):
    fault: Literal["none", "invalid_signature", "stale_timestamp"] = "none"


def _http_error(exc: M7IntegrationError) -> HTTPException:
    not_found = {"webhook_source_not_found", "webhook_object_not_found", "webhook_endpoint_not_found", "webhook_delivery_not_found"}
    forbidden = {"integration_forbidden", "webhook_source_forbidden", "webhook_endpoint_forbidden"}
    status = 404 if exc.code in not_found else 403 if exc.code in forbidden else 409
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


@router.get("/workspace")
async def get_workspace(organization_id: str, current_user: DBUser = Depends(get_current_user)):
    try:
        return await run_db_op(lambda session: webhook_workspace(
            session, actor=current_user, organization_id=organization_id,
        ))
    except M7IntegrationError as exc:
        raise _http_error(exc) from exc


@router.post("/endpoints", status_code=201)
async def create_endpoint(payload: EndpointCreate, current_user: DBUser = Depends(get_current_user)):
    def operation(session):
        row, created = ensure_local_webhook_endpoint(session, actor=current_user, **payload.model_dump())
        return {"id": row.id, "destination_key": row.destination_key,
                "secret_fingerprint": row.secret_fingerprint, "created": created,
                "secret_returned": False}
    try:
        return await run_db_op(operation)
    except M7IntegrationError as exc:
        raise _http_error(exc) from exc


@router.post("/events", status_code=201)
async def create_event(payload: EventCreate, current_user: DBUser = Depends(get_current_user)):
    def operation(session):
        row, created = create_webhook_event(session, actor=current_user, **payload.model_dump())
        return {"id": row.id, "event_type": row.event_type, "payload_hash": row.payload_hash, "created": created}
    try:
        return await run_db_op(operation)
    except M7IntegrationError as exc:
        raise _http_error(exc) from exc


@router.post("/deliveries", status_code=201)
async def create_delivery(payload: DeliveryCreate, current_user: DBUser = Depends(get_current_user)):
    def operation(session):
        row, created = enqueue_webhook_event(session, actor=current_user, **payload.model_dump())
        return {"id": row.id, "status": row.status, "created": created}
    try:
        return await run_db_op(operation)
    except M7IntegrationError as exc:
        raise _http_error(exc) from exc


@router.post("/deliveries/{delivery_id}/send")
async def send_delivery(
    delivery_id: str, payload: DeliverySend,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        delivery, receipt, attempted = deliver_webhook_locally(
            session, actor=current_user, delivery_id=delivery_id, fault=payload.fault,
        )
        return {"id": delivery.id, "status": delivery.status, "attempt_count": delivery.attempt_count,
                "receipt_id": receipt.id, "receipt_outcome": receipt.outcome, "attempted": attempted}
    try:
        return await run_db_op(operation)
    except M7IntegrationError as exc:
        raise _http_error(exc) from exc


@router.post("/receive/{endpoint_id}")
async def receive_webhook(endpoint_id: str, request: SignedReceive):
    def operation(session):
        receipt, accepted = receive_signed_webhook(
            session, endpoint_id=endpoint_id, payload=request.payload,
            timestamp_value=request.timestamp, nonce=request.nonce,
            signature=request.signature, delivery_id=request.delivery_id,
        )
        return receipt, accepted
    try:
        receipt, accepted = await run_db_op(operation)
    except M7IntegrationError as exc:
        raise _http_error(exc) from exc
    if not accepted:
        raise HTTPException(status_code=401, detail={"code": receipt.reason_code, "receipt_id": receipt.id})
    return {"accepted": True, "receipt_id": receipt.id, "event_id": receipt.event_id}
