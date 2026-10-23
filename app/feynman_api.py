from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field

from app.auth import get_current_user
from app.database import DBUser, run_db_op
from app.feynman import (
    FeynmanError,
    apply_action,
    create_session,
    get_session,
    list_sessions,
    session_payload,
)
from app.m2_contracts import StrictModel


router = APIRouter(prefix="/api/v1/feynman", tags=["feynman"])


class SessionInput(StrictModel):
    source_resource_id: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=128)


class ActionInput(StrictModel):
    action: Literal[
        "submit_round1",
        "evaluate_round1",
        "begin_question",
        "answer_question",
        "submit_round2",
        "evaluate_round2",
        "apply",
    ]
    text: str | None = Field(default=None, max_length=12_000)
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=128)


def _http(exc: FeynmanError) -> HTTPException:
    if exc.code.startswith("feynman_model_"):
        code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif exc.code.endswith("unknown"):
        code = status.HTTP_404_NOT_FOUND
    elif "forbidden" in exc.code:
        code = status.HTTP_403_FORBIDDEN
    elif "conflict" in exc.code:
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(status_code=code, detail={"code": exc.code, "message": str(exc)})


@router.get("/sessions")
async def sessions(
    source_resource_id: str | None = None,
    current_user: DBUser = Depends(get_current_user),
):
    return await run_db_op(lambda db: {
        "schema_version": "f6.feynman-session-list.v1",
        "items": list_sessions(db, current_user.public_id, source_resource_id),
    })


@router.post("/sessions", status_code=201)
async def post_session(payload: SessionInput, current_user: DBUser = Depends(get_current_user)):
    def operation(db):
        try:
            artifact, version, state, created = create_session(
                db, owner=current_user.public_id, **payload.model_dump(),
            )
            result = session_payload(db, artifact, version, state)
            db.commit()
            return {**result, "created": created}
        except FeynmanError as exc:
            db.rollback()
            raise _http(exc) from exc

    return await run_db_op(operation)


@router.get("/sessions/{session_id}")
async def session(session_id: str, current_user: DBUser = Depends(get_current_user)):
    def operation(db):
        try:
            return get_session(db, session_id, current_user.public_id)
        except FeynmanError as exc:
            raise _http(exc) from exc

    return await run_db_op(operation)


@router.post("/sessions/{session_id}/actions")
async def post_action(
    session_id: str,
    payload: ActionInput,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(db):
        try:
            actor = db.query(DBUser).filter_by(public_id=current_user.public_id).one()
            result, created = apply_action(
                db,
                session_id=session_id,
                actor=actor,
                **payload.model_dump(),
            )
            db.commit()
            return {**result, "action_created": created}
        except FeynmanError as exc:
            db.rollback()
            raise _http(exc) from exc

    return await run_db_op(operation)
