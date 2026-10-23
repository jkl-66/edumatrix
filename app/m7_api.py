"""Authenticated M7 integration sandbox API."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from app.auth import get_current_user
from app.database import DBUser, run_db_op
from app.m2_contracts import StrictModel
from app.m7_integrations import (
    M7IntegrationError,
    enqueue_organization_learning_event,
    integration_workspace,
    deliver_to_local_lrs,
    launch_cmi5_session,
    requeue_dead_letter,
    simulate_delivery_attempt,
    transition_cmi5_session,
)


router = APIRouter(prefix="/api/v1/m7", tags=["m7-integration-sandbox"])


class DeliveryCreate(StrictModel):
    organization_id: str = Field(min_length=1, max_length=64)
    event_id: str = Field(min_length=1, max_length=64)
    destination_key: str = Field(default="competition-mock-lrs", min_length=3, max_length=128)


class DeliveryAttempt(StrictModel):
    outcome: Literal["success", "failure"]
    error_code: str = Field(default="mock_lrs_unavailable", max_length=64)


class Cmi5Launch(StrictModel):
    organization_id: str = Field(min_length=1, max_length=64)
    learner_public_id: str = Field(min_length=1, max_length=64)
    course_id: str | None = Field(default=None, max_length=128)
    launch_key: str = Field(min_length=3, max_length=128)


class Cmi5Transition(StrictModel):
    action: Literal["activate", "complete", "exit"]
    expected_lock_version: int = Field(ge=1)


def _http_error(exc: M7IntegrationError) -> HTTPException:
    status = 404 if exc.code in {"learning_event_not_found", "delivery_not_found", "cmi5_session_not_found"} else 409
    if exc.code == "integration_forbidden":
        status = 403
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


@router.get("/integrations/workspace")
async def get_integration_workspace(
    organization_id: str | None = None,
    current_user: DBUser = Depends(get_current_user),
):
    try:
        return await run_db_op(lambda session: integration_workspace(
            session, actor=current_user, organization_id=organization_id,
        ))
    except M7IntegrationError as exc:
        raise _http_error(exc) from exc


@router.post("/integrations/deliveries/{delivery_id}/local-lrs")
async def deliver_integration_to_local_lrs(
    delivery_id: str, current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        delivery, statement, created = deliver_to_local_lrs(
            session, actor=current_user, delivery_id=delivery_id,
        )
        return {"delivery_id": delivery.id, "status": delivery.status,
                "statement_id": statement.statement_id,
                "statement_hash": statement.statement_hash, "created": created}
    try:
        return await run_db_op(operation)
    except M7IntegrationError as exc:
        raise _http_error(exc) from exc


@router.post("/integrations/deliveries/{delivery_id}/requeue")
async def requeue_integration_delivery(
    delivery_id: str, current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        row = requeue_dead_letter(session, actor=current_user, delivery_id=delivery_id)
        return {"id": row.id, "status": row.status, "attempt_count": row.attempt_count,
                "next_attempt_at": row.next_attempt_at.isoformat() if row.next_attempt_at else None}
    try:
        return await run_db_op(operation)
    except M7IntegrationError as exc:
        raise _http_error(exc) from exc


@router.post("/integrations/cmi5/sessions", status_code=201)
async def create_cmi5_session(
    payload: Cmi5Launch, current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        row, created = launch_cmi5_session(session, actor=current_user, **payload.model_dump())
        return {"id": row.id, "registration": row.registration, "status": row.status,
                "lock_version": row.lock_version, "created": created}
    try:
        return await run_db_op(operation)
    except M7IntegrationError as exc:
        raise _http_error(exc) from exc


@router.post("/integrations/cmi5/sessions/{session_id}/transition")
async def update_cmi5_session(
    session_id: str, payload: Cmi5Transition,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        row = transition_cmi5_session(
            session, actor=current_user, session_id=session_id, **payload.model_dump(),
        )
        return {"id": row.id, "status": row.status, "lock_version": row.lock_version}
    try:
        return await run_db_op(operation)
    except M7IntegrationError as exc:
        raise _http_error(exc) from exc


@router.post("/integrations/deliveries", status_code=201)
async def create_integration_delivery(
    payload: DeliveryCreate,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        row, created = enqueue_organization_learning_event(
            session,
            actor=current_user,
            organization_id=payload.organization_id,
            event_id=payload.event_id,
            destination_key=payload.destination_key,
        )
        return {"id": row.id, "status": row.status, "created": created}
    try:
        return await run_db_op(operation)
    except M7IntegrationError as exc:
        raise _http_error(exc) from exc


@router.post("/integrations/deliveries/{delivery_id}/attempt")
async def attempt_integration_delivery(
    delivery_id: str,
    payload: DeliveryAttempt,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(session):
        row = simulate_delivery_attempt(
            session,
            actor=current_user,
            delivery_id=delivery_id,
            success=payload.outcome == "success",
            error_code=payload.error_code,
        )
        return {
            "id": row.id,
            "status": row.status,
            "attempt_count": row.attempt_count,
            "last_error_code": row.last_error_code or "",
        }
    try:
        return await run_db_op(operation)
    except M7IntegrationError as exc:
        raise _http_error(exc) from exc
