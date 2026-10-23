from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import Field

from app.auth import get_current_user
from app.course_governance import CourseGovernanceError
from app.database import DBUser, run_db_op
from app.m2_contracts import StrictModel
from app.teaching_analytics import create_report, get_report, list_reports, report_payload

router = APIRouter(prefix="/api/v1/teaching-analytics", tags=["teaching-analytics"])


class ReportInput(StrictModel):
    class_id: str = Field(min_length=1, max_length=64)
    period_start: datetime
    period_end: datetime


def _http(exc: CourseGovernanceError) -> HTTPException:
    if exc.code.endswith("unknown"): code = status.HTTP_404_NOT_FOUND
    elif "forbidden" in exc.code: code = status.HTTP_403_FORBIDDEN
    else: code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(status_code=code, detail={"code": exc.code, "message": str(exc)})


def _operation(callback):
    def wrapped(db):
        try:
            result = callback(db); db.commit(); return result
        except CourseGovernanceError as exc:
            db.rollback(); raise _http(exc) from exc
    return wrapped


@router.post("/reports", status_code=201)
async def post_report(payload: ReportInput, current_user: DBUser = Depends(get_current_user)):
    def operation(db):
        row, created = create_report(db, actor=current_user, **payload.model_dump())
        return {"created": created, **report_payload(row)}
    return await run_db_op(_operation(operation))


@router.get("/reports")
async def get_reports(class_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_operation(lambda db: {"schema_version": "next.teaching-analytics-list.v1", "items": list_reports(db, actor=current_user, class_id=class_id)}))


@router.get("/reports/{report_id}")
async def get_report_detail(report_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_operation(lambda db: report_payload(get_report(db, actor=current_user, report_id=report_id))))


@router.get("/reports/{report_id}/export/{format_name}")
async def export_report(report_id: str, format_name: Literal["json", "csv"], current_user: DBUser = Depends(get_current_user)):
    payload = await run_db_op(_operation(lambda db: report_payload(get_report(db, actor=current_user, report_id=report_id))))
    if format_name == "json":
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        media = "application/json"
    else:
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(["scope", "learner_public_id", "metric", "value", "sample_size", "state", "source"])
        for metric in payload["metrics"]:
            writer.writerow(["class", "", metric["key"], metric["value"], metric["sample_size"], metric["state"], "+".join(metric["sources"])])
        for learner in payload["learners"]:
            writer.writerow(["learner", learner["learner_public_id"], "path_burden_minutes", learner["pending_burden_minutes"], learner["path_node_count"], learner["burden_state"], "learning_paths+path_nodes"])
        body = ("\ufeff" + stream.getvalue()).encode("utf-8")
        media = "text/csv; charset=utf-8"
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="teaching-analytics-{report_id}.{format_name}"', "Cache-Control": "private, no-store"})
