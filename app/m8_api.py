"""Authenticated M8 operational readiness API."""

from fastapi import APIRouter, Depends

from app.auth import get_current_teacher
from app.database import DBUser
from app.m8_preflight import deployment_preflight


router = APIRouter(prefix="/api/v1/m8", tags=["m8-operations"])


@router.get("/deployment-preflight")
async def get_deployment_preflight(current_user: DBUser = Depends(get_current_teacher)):
    return deployment_preflight()
