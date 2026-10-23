"""Authenticated administration endpoints for the frozen competition demo scope."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_user
from app.competition_demo_seed import (
    CompetitionDemoSeedError,
    competition_demo_status,
    competition_demo_students,
    reset_competition_demo,
    seed_competition_demo,
)
from app.competition_demo_context import (
    CompetitionDemoContextAccessError,
    build_competition_demo_context,
)
from app.database import DBUser, run_db_op
from app.identity import normalize_role


router = APIRouter(prefix="/api/v1/competition-demo", tags=["competition-demo"])


def _require_admin(user: DBUser) -> None:
    if normalize_role(user.role) != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "competition_demo_admin_required", "message": "仅管理员可管理比赛演示数据"},
        )


def _conflict(exc: CompetitionDemoSeedError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": "competition_demo_state_conflict", "message": str(exc)},
    )


@router.get("/context")
async def get_competition_demo_context(current_user: DBUser = Depends(get_current_user)):
    try:
        return await run_db_op(build_competition_demo_context, current_user)
    except CompetitionDemoContextAccessError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "competition_demo_scope_required", "message": "当前账号不属于比赛演示课程"},
        ) from exc


@router.get("/status")
async def get_competition_demo_status(current_user: DBUser = Depends(get_current_user)):
    _require_admin(current_user)
    try:
        result = await run_db_op(competition_demo_status)
        return asdict(result)
    except CompetitionDemoSeedError as exc:
        raise _conflict(exc) from exc


@router.post("/initialize")
async def initialize_competition_demo(current_user: DBUser = Depends(get_current_user)):
    _require_admin(current_user)
    try:
        seed_result = await run_db_op(seed_competition_demo)
        current_status = await run_db_op(competition_demo_status)
        students = await run_db_op(competition_demo_students)
        return {
            "seed": asdict(seed_result),
            "status": asdict(current_status),
            "cohort_student_count": len(students),
        }
    except CompetitionDemoSeedError as exc:
        raise _conflict(exc) from exc


@router.post("/reset")
async def reset_competition_demo_state(current_user: DBUser = Depends(get_current_user)):
    _require_admin(current_user)
    try:
        reset_result = await run_db_op(reset_competition_demo)
        current_status = await run_db_op(competition_demo_status)
        students = await run_db_op(competition_demo_students)
        return {
            "reset": asdict(reset_result),
            "status": asdict(current_status),
            "cohort_student_count": len(students),
        }
    except CompetitionDemoSeedError as exc:
        raise _conflict(exc) from exc
