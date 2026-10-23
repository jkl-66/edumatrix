"""Authenticated API for synthetic job-standard upgrade impact governance."""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from app.auth import get_current_user
from app.database import DBUser, run_db_op
from app.job_standard_impact import (
    JobStandardImpactError, confirm_preview, create_preview, prepare_demo_upgrade,
    preview_payload, workspace,
)
from app.m2_contracts import StrictModel


router = APIRouter(prefix="/api/v1/job-standard-impact", tags=["job-standard-impact"])


class PreviewCreate(StrictModel):
    organization_id: str
    source_job_level_id: str
    target_job_level_id: str


class PreviewConfirm(StrictModel):
    preview_hash: str = Field(min_length=64, max_length=64)
    reason: str = Field(min_length=4, max_length=1000)


class DemoUpgradePrepare(StrictModel):
    organization_id: str
    source_job_level_id: str
    target_version: str = Field(default="2026.2", min_length=1, max_length=64)


def _http(error: JobStandardImpactError) -> HTTPException:
    status = 404 if error.code.endswith("unknown") else 403 if "forbidden" in error.code else 409
    return HTTPException(status_code=status, detail={"code": error.code, "message": str(error)})


def _operation(function):
    def run(db):
        try:
            result = function(db)
            db.commit()
            return result
        except JobStandardImpactError as error:
            db.rollback()
            raise _http(error)
    return run


@router.get("/workspace")
async def get_workspace(organization_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_operation(lambda db: workspace(
        db, actor=current_user, organization_id=organization_id,
    )))


@router.post("/previews", status_code=201)
async def post_preview(body: PreviewCreate, current_user: DBUser = Depends(get_current_user)):
    def run(db):
        row, created = create_preview(db, actor=current_user, **body.model_dump())
        return {"created": created, "preview": preview_payload(db, row)}
    return await run_db_op(_operation(run))


@router.post("/demo/prepare", status_code=201)
async def post_demo_upgrade(body: DemoUpgradePrepare, current_user: DBUser = Depends(get_current_user)):
    def run(db):
        row, created = prepare_demo_upgrade(db, actor=current_user, **body.model_dump())
        return {
            "created": created, "job_level_id": row.id, "version": row.version,
            "standard_source": "frozen_synthetic_competition_demo",
            "truth_label": "冻结合成岗位标准 · 比赛演示数据",
        }
    return await run_db_op(_operation(run))


@router.post("/previews/{preview_id}/confirm")
async def post_confirmation(
    preview_id: str, body: PreviewConfirm, current_user: DBUser = Depends(get_current_user),
):
    def run(db):
        preview, confirmation, created = confirm_preview(
            db, actor=current_user, preview_id=preview_id, **body.model_dump(),
        )
        return {"created": created, "preview": preview_payload(db, preview)}
    return await run_db_op(_operation(run))
