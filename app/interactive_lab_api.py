from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field

from app.auth import get_current_user
from app.database import DBArtifact, DBUser, run_db_op
from app.interactive_lab import (InteractiveLabError, apply_action, create_instance, get_instance,
                                 instance_payload, list_instances, list_templates)
from app.m2_contracts import StrictModel


router = APIRouter(prefix="/api/v1/interactive-lab", tags=["interactive-lab"])


class InstanceInput(StrictModel):
    template_id: str | None = Field(default=None, min_length=1, max_length=80)
    title: str | None = Field(default=None, min_length=1, max_length=256)
    parameters: dict[str, int | float] | None = None
    linked_media_resource_id: str | None = Field(default=None, max_length=64)
    source_resource_id: str | None = Field(default=None, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=128)


class ActionInput(StrictModel):
    action: str = Field(pattern="^(configure|run|submit|request_hint|reset)$")
    parameters: dict[str, int | float] | None = None
    observation: str | None = Field(default=None, max_length=8_000)
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=128)


def _http(exc: InteractiveLabError) -> HTTPException:
    if exc.code.endswith("unknown"):
        code = status.HTTP_404_NOT_FOUND
    elif "forbidden" in exc.code:
        code = status.HTTP_403_FORBIDDEN
    elif "conflict" in exc.code:
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(status_code=code, detail={"code": exc.code, "message": str(exc)})


@router.get("/templates")
async def templates(current_user: DBUser = Depends(get_current_user)):
    return {"schema_version": "next.interactive-template-list.v1",
            "items": [item.model_dump(mode="json") for item in list_templates()]}


@router.get("/instances")
async def instances(current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(lambda db: {"schema_version": "next.interactive-instance-list.v1",
                                       "items": list_instances(db, current_user.public_id)})


@router.post("/instances", status_code=201)
async def post_instance(payload: InstanceInput, current_user: DBUser = Depends(get_current_user)):
    def operation(db):
        try:
            state, version, created = create_instance(db, owner=current_user.public_id, **payload.model_dump())
            artifact = db.get(DBArtifact, state.instance_id)
            result = instance_payload(artifact, version, state); db.commit()
            return {**result, "created": created}
        except InteractiveLabError as exc:
            db.rollback(); raise _http(exc) from exc
    return await run_db_op(operation)


@router.get("/instances/{instance_id}")
async def instance(instance_id: str, current_user: DBUser = Depends(get_current_user)):
    def operation(db):
        try: return get_instance(db, instance_id, current_user.public_id)
        except InteractiveLabError as exc: raise _http(exc) from exc
    return await run_db_op(operation)


@router.post("/instances/{instance_id}/actions")
async def post_action(instance_id: str, payload: ActionInput, current_user: DBUser = Depends(get_current_user)):
    def operation(db):
        try:
            result, created = apply_action(db, instance_id=instance_id, owner=current_user.public_id, **payload.model_dump())
            db.commit(); return {**result, "action_created": created}
        except InteractiveLabError as exc:
            db.rollback(); raise _http(exc) from exc
    return await run_db_op(operation)
