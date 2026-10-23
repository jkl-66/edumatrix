from __future__ import annotations

import csv
import io
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.auth import get_current_user
from app.database import DBUser, run_db_op
from app.identity import normalize_role
from app.model_operations_dashboard import dashboard

router = APIRouter(prefix="/api/v1/model-operations-dashboard", tags=["model-operations-dashboard"])


def _require_operator(user: DBUser) -> None:
    if normalize_role(user.role) not in {"teacher", "admin"}:
        raise HTTPException(status_code=403, detail={"code": "model_operations_operator_required", "message": "teacher or admin role required"})


@router.get("")
async def get_dashboard(days: int = Query(7, ge=1, le=90), current_user: DBUser = Depends(get_current_user)):
    _require_operator(current_user)
    return await run_db_op(lambda db: dashboard(db, actor=current_user, days=days))


@router.get("/export/{format_name}")
async def export_dashboard(format_name: Literal["json", "csv"], days: int = Query(7, ge=1, le=90), current_user: DBUser = Depends(get_current_user)):
    _require_operator(current_user)
    payload = await run_db_op(lambda db: dashboard(db, actor=current_user, days=days))
    if format_name == "json":
        return Response(json.dumps(payload, ensure_ascii=False, indent=2), media_type="application/json", headers={"Content-Disposition": "attachment; filename=model-operations.json"})
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=["provider", "model", "capability", "call_count", "success_rate", "input_tokens", "output_tokens", "p95_latency_ms", "estimated_by_currency"])
    writer.writeheader()
    for row in payload["breakdown"]:
        writer.writerow({**row, "estimated_by_currency": json.dumps(row["estimated_by_currency"], ensure_ascii=False, sort_keys=True)})
    return Response("\ufeff" + stream.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=model-operations.csv"})
