"""Authenticated HTTP API for the FC4 local SSO simulator."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from app.auth import get_current_user
from app.database import DBUser, run_db_op
from app.local_sso import (
    LocalSSOError, bind_assertion, emergency_admin_session, ensure_provider,
    preview_assertion, revoke_mapping, set_provider_status, simulate_login, workspace,
)
from app.m2_contracts import StrictModel


router = APIRouter(prefix="/api/v1/local-sso", tags=["fc4-local-sso"])


class ProviderCreate(StrictModel):
    organization_id: str = Field(min_length=1, max_length=64)
    provider_key: str = Field(default="competition-local-idp", pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    display_name: str = Field(default="EduMatrix 本地身份提供方", min_length=2, max_length=128)
    protocol_style: Literal["oidc", "saml"] = "oidc"


class ProviderStatus(StrictModel):
    organization_id: str = Field(min_length=1, max_length=64)
    status: Literal["active", "disabled"]
    expected_lock_version: int = Field(ge=1)


class AssertionInput(StrictModel):
    organization_id: str = Field(min_length=1, max_length=64)
    provider_id: str = Field(min_length=1, max_length=64)
    assertion_id: str = Field(min_length=3, max_length=128)
    subject: str = Field(min_length=1, max_length=256)
    groups: list[str] = Field(default_factory=list, max_length=16)
    target_user_public_id: str = Field(min_length=1, max_length=64)


class LoginInput(StrictModel):
    organization_id: str = Field(min_length=1, max_length=64)
    provider_id: str = Field(min_length=1, max_length=64)
    assertion_id: str = Field(min_length=3, max_length=128)
    subject: str = Field(min_length=1, max_length=256)
    groups: list[str] = Field(default_factory=list, max_length=16)


class RevokeInput(StrictModel):
    organization_id: str = Field(min_length=1, max_length=64)


class EmergencyInput(StrictModel):
    organization_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=8, max_length=256)


def _http_error(exc: LocalSSOError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})


@router.get("/workspace")
async def get_workspace(organization_id: str | None = None, current_user: DBUser = Depends(get_current_user)):
    try:
        return await run_db_op(lambda session: workspace(session, actor=current_user, organization_id=organization_id))
    except LocalSSOError as exc:
        raise _http_error(exc) from exc


@router.post("/providers", status_code=201)
async def create_provider(payload: ProviderCreate, current_user: DBUser = Depends(get_current_user)):
    try:
        def operation(session):
            row, created = ensure_provider(session, actor=current_user, **payload.model_dump())
            return {"id": row.id, "status": row.status, "lock_version": row.lock_version, "created": created}
        return await run_db_op(operation)
    except LocalSSOError as exc:
        raise _http_error(exc) from exc


@router.post("/providers/{provider_id}/status")
async def update_provider_status(provider_id: str, payload: ProviderStatus, current_user: DBUser = Depends(get_current_user)):
    try:
        def operation(session):
            row = set_provider_status(session, actor=current_user, provider_id=provider_id, **payload.model_dump())
            return {"id": row.id, "status": row.status, "lock_version": row.lock_version}
        return await run_db_op(operation)
    except LocalSSOError as exc:
        raise _http_error(exc) from exc


@router.post("/assertions/preview")
async def preview(payload: AssertionInput, current_user: DBUser = Depends(get_current_user)):
    try:
        return await run_db_op(lambda session: preview_assertion(session, actor=current_user, **payload.model_dump()))
    except LocalSSOError as exc:
        raise _http_error(exc) from exc


@router.post("/assertions/bind", status_code=201)
async def bind(payload: AssertionInput, current_user: DBUser = Depends(get_current_user)):
    try:
        def operation(session):
            row, created, role = bind_assertion(session, actor=current_user, **payload.model_dump())
            return {"id": row.id, "status": row.status, "resolved_role": role, "created": created}
        return await run_db_op(operation)
    except LocalSSOError as exc:
        raise _http_error(exc) from exc


@router.post("/sessions", status_code=201)
async def login(payload: LoginInput, current_user: DBUser = Depends(get_current_user)):
    try:
        def operation(session):
            row, created = simulate_login(session, actor=current_user, **payload.model_dump())
            return {"id": row.id, "status": row.status, "login_mode": row.login_mode,
                    "resolved_organization_role": row.resolved_organization_role,
                    "expires_at": row.expires_at.isoformat(), "created": created,
                    "application_access_token_issued": False}
        return await run_db_op(operation)
    except LocalSSOError as exc:
        raise _http_error(exc) from exc


@router.post("/mappings/{mapping_id}/revoke")
async def revoke(mapping_id: str, payload: RevokeInput, current_user: DBUser = Depends(get_current_user)):
    try:
        def operation(session):
            row = revoke_mapping(session, actor=current_user, mapping_id=mapping_id, **payload.model_dump())
            return {"id": row.id, "status": row.status, "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None}
        return await run_db_op(operation)
    except LocalSSOError as exc:
        raise _http_error(exc) from exc


@router.post("/emergency-admin", status_code=201)
async def emergency(payload: EmergencyInput, current_user: DBUser = Depends(get_current_user)):
    try:
        def operation(session):
            row = emergency_admin_session(session, actor=current_user, **payload.model_dump())
            return {"id": row.id, "status": row.status, "login_mode": row.login_mode,
                    "expires_at": row.expires_at.isoformat(), "provider_bypassed": True,
                    "application_access_token_issued": False}
        return await run_db_op(operation)
    except LocalSSOError as exc:
        raise _http_error(exc) from exc
