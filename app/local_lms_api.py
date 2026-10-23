"""Authenticated API for the deterministic local LMS adapter."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from app.auth import get_current_user
from app.database import DBUser, run_db_op
from app.local_lms import (
    LMSSyncError, bootstrap_demo, ensure_connection, export_catalog,
    import_grade_summary, sync_assignment, workspace,
)
from app.m2_contracts import StrictModel


router = APIRouter(prefix="/api/v1/local-lms", tags=["fc4-local-lms"])


class ConnectionCreate(StrictModel):
    organization_id: str = Field(min_length=1, max_length=64)
    connection_key: str = Field(default="competition-local-lms", min_length=3, max_length=64)
    display_name: str = Field(default="比赛演示 LMS", min_length=1, max_length=128)


class CatalogExportCreate(StrictModel):
    organization_id: str = Field(min_length=1, max_length=64)
    connection_id: str = Field(min_length=1, max_length=64)
    source_type: str = Field(pattern="^(course|cohort)$")
    source_object_id: str = Field(min_length=1, max_length=128)


class AssignmentSyncCreate(StrictModel):
    organization_id: str = Field(min_length=1, max_length=64)
    connection_id: str = Field(min_length=1, max_length=64)
    training_assignment_id: str = Field(min_length=1, max_length=64)


class GradeSummaryCreate(StrictModel):
    organization_id: str = Field(min_length=1, max_length=64)
    connection_id: str = Field(min_length=1, max_length=64)
    external_record_key: str = Field(min_length=3, max_length=160)
    training_assignment_id: str = Field(min_length=1, max_length=64)
    course_id: str | None = Field(default=None, max_length=128)
    completion_status: str = Field(pattern="^(in_progress|completed|failed|withdrawn)$")
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    occurred_at: datetime


def _http_error(exc: LMSSyncError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})


@router.get("/workspace")
async def get_workspace(organization_id: str | None = None, current_user: DBUser = Depends(get_current_user)):
    try:
        return await run_db_op(lambda session: workspace(session, actor=current_user, organization_id=organization_id))
    except LMSSyncError as exc:
        raise _http_error(exc) from exc


@router.post("/demo/bootstrap")
async def create_demo(current_user: DBUser = Depends(get_current_user)):
    try:
        return await run_db_op(lambda session: bootstrap_demo(session, actor=current_user))
    except LMSSyncError as exc:
        raise _http_error(exc) from exc


@router.post("/connections", status_code=201)
async def create_connection(payload: ConnectionCreate, current_user: DBUser = Depends(get_current_user)):
    try:
        def operation(session):
            row, created = ensure_connection(session, actor=current_user, **payload.model_dump())
            return {"id": row.id, "status": row.status, "created": created}
        return await run_db_op(operation)
    except LMSSyncError as exc:
        raise _http_error(exc) from exc


@router.post("/catalog-exports", status_code=201)
async def create_catalog_export(payload: CatalogExportCreate, current_user: DBUser = Depends(get_current_user)):
    try:
        def operation(session):
            row, created = export_catalog(session, actor=current_user, **payload.model_dump())
            return {"id": row.id, "snapshot_hash": row.snapshot_hash,
                    "external_catalog_key": row.external_catalog_key, "created": created}
        return await run_db_op(operation)
    except LMSSyncError as exc:
        raise _http_error(exc) from exc


@router.post("/assignment-exchanges", status_code=201)
async def create_assignment_exchange(payload: AssignmentSyncCreate, current_user: DBUser = Depends(get_current_user)):
    try:
        def operation(session):
            row, changed = sync_assignment(session, actor=current_user, **payload.model_dump())
            return {"id": row.id, "payload_hash": row.payload_hash, "lock_version": row.lock_version,
                    "status": row.status, "changed": changed}
        return await run_db_op(operation)
    except LMSSyncError as exc:
        raise _http_error(exc) from exc


@router.post("/grade-summaries", status_code=201)
async def create_grade_summary(payload: GradeSummaryCreate, current_user: DBUser = Depends(get_current_user)):
    try:
        def operation(session):
            row, created = import_grade_summary(session, actor=current_user, **payload.model_dump())
            return {"id": row.id, "payload_hash": row.payload_hash, "evidence_status": row.evidence_status,
                    "authoritative": False, "created": created}
        return await run_db_op(operation)
    except LMSSyncError as exc:
        raise _http_error(exc) from exc
