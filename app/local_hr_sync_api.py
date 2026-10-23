"""Authenticated FC4 synthetic HR synchronization API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from app.auth import get_current_user
from app.database import DBUser, run_db_op
from app.local_hr_sync import HRSyncError, apply_sync, ensure_mapping, frozen_snapshot, preview_sync, workspace
from app.m2_contracts import StrictModel


router = APIRouter(prefix="/api/v1/local-hr", tags=["fc4-local-hr"])


class MappingCreate(StrictModel):
    organization_id: str = Field(min_length=1, max_length=64)
    source_key: str = Field(default="competition-synthetic-hr", min_length=3, max_length=64)
    field_map: dict[str, str] | None = None


class PreviewCreate(StrictModel):
    organization_id: str = Field(min_length=1, max_length=64)
    mapping_version_id: str = Field(min_length=1, max_length=64)
    source_snapshot_id: str = Field(min_length=3, max_length=128)
    source_sequence: int = Field(ge=1)
    records: list[dict] = Field(min_length=1, max_length=500)


class ApplyCreate(StrictModel):
    organization_id: str = Field(min_length=1, max_length=64)
    expected_lock_version: int = Field(ge=1)


def _http_error(exc: HRSyncError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})


@router.get("/workspace")
async def get_workspace(organization_id: str | None = None, current_user: DBUser = Depends(get_current_user)):
    try:
        return await run_db_op(lambda session: workspace(session, actor=current_user, organization_id=organization_id))
    except HRSyncError as exc:
        raise _http_error(exc) from exc


@router.get("/frozen-snapshot")
async def get_frozen_snapshot(sequence: int = 1, offboard_existing: bool = False, current_user: DBUser = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail={"code": "hr_sync_forbidden", "message": "只有管理员可以读取 HR 演示快照"})
    return frozen_snapshot(sequence, offboard_existing)


@router.post("/mappings", status_code=201)
async def create_mapping(payload: MappingCreate, current_user: DBUser = Depends(get_current_user)):
    try:
        def operation(session):
            row, created = ensure_mapping(session, actor=current_user, **payload.model_dump())
            return {"id": row.id, "version_number": row.version_number, "mapping_hash": row.mapping_hash, "created": created}
        return await run_db_op(operation)
    except HRSyncError as exc:
        raise _http_error(exc) from exc


@router.post("/previews", status_code=201)
async def create_preview(payload: PreviewCreate, current_user: DBUser = Depends(get_current_user)):
    try:
        def operation(session):
            row, created = preview_sync(session, actor=current_user, **payload.model_dump())
            return {"id": row.id, "status": row.status, "lock_version": row.lock_version,
                    "preview": row.preview_snapshot, "source_hash": row.source_hash, "created": created}
        return await run_db_op(operation)
    except HRSyncError as exc:
        raise _http_error(exc) from exc


@router.post("/batches/{batch_id}/apply")
async def apply_batch(batch_id: str, payload: ApplyCreate, current_user: DBUser = Depends(get_current_user)):
    try:
        def operation(session):
            row, applied = apply_sync(session, actor=current_user, batch_id=batch_id, **payload.model_dump())
            return {"id": row.id, "status": row.status, "lock_version": row.lock_version,
                    "applied_at": row.applied_at.isoformat() if row.applied_at else None, "applied": applied}
        return await run_db_op(operation)
    except HRSyncError as exc:
        raise _http_error(exc) from exc
