from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field

from app.auth import get_current_user
from app.code_sandbox import (
    CODE_SANDBOX_EXECUTOR,
    CODE_SANDBOX_RUN_COORDINATOR,
    FINAL_RUN_STATUSES,
    CodeSandboxError,
    complete_run_learning,
    get_run,
    list_runs,
    prepare_run,
    _owned_resource,
)
from app.code_review import (
    apply_review,
    configured_code_review_adapter,
    create_review,
    get_review,
    latest_review,
)
from app.database import DBUser, run_db_op
from app.m2_contracts import StrictModel
from app.models import ContextResolutionError


router = APIRouter(prefix="/api/v1/code-sandbox", tags=["code-sandbox"])
CODE_REVIEW_MODEL_ADAPTER = configured_code_review_adapter()


class RunInput(StrictModel):
    resource_version_id: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=1, max_length=50_000)
    standard_input: str = Field(default="", max_length=20_000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class CompleteInput(StrictModel):
    run_attempt_id: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=128)
    context: dict[str, Any] | None = None
    actual_minutes: int | None = Field(default=None, ge=0, le=10080)


class ReviewInput(StrictModel):
    run_attempt_id: str = Field(min_length=1, max_length=64)
    code_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    focus: str = Field(default="", max_length=1000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class ApplyReviewInput(StrictModel):
    expected_lock_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=128)


def _http(exc: CodeSandboxError) -> HTTPException:
    if exc.code.endswith("unknown"):
        code = status.HTTP_404_NOT_FOUND
    elif "forbidden" in exc.code:
        code = status.HTTP_403_FORBIDDEN
    elif exc.code.startswith("code_review_model_"):
        code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif "runtime_unavailable" in exc.code:
        code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif any(token in exc.code for token in ("conflict", "stale", "incomplete", "unavailable")):
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(status_code=code, detail={"code": exc.code, "message": str(exc)})


@router.get("/status")
async def runtime_status(current_user: DBUser = Depends(get_current_user)):
    return CODE_SANDBOX_EXECUTOR.status()


@router.get("/resources/{resource_id}/runs")
async def resource_runs(
    resource_id: str,
    limit: int = 20,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(db):
        try:
            _owned_resource(db, resource_id, current_user.public_id)
            return {
                "schemaVersion": "f6.code-sandbox-run-list.v1",
                "items": list_runs(
                    db,
                    owner=current_user.public_id,
                    resource_id=resource_id,
                    limit=max(1, min(limit, 50)),
                ),
            }
        except CodeSandboxError as exc:
            raise _http(exc) from exc

    return await run_db_op(operation)


@router.post("/resources/{resource_id}/runs", status_code=202)
async def start_run(
    resource_id: str,
    payload: RunInput,
    current_user: DBUser = Depends(get_current_user),
):
    if not CODE_SANDBOX_EXECUTOR.enabled:
        raise _http(CodeSandboxError(
            "code_sandbox_runtime_unavailable",
            CODE_SANDBOX_EXECUTOR.status()["message"],
        ))

    def operation(db):
        try:
            state, created = prepare_run(
                db,
                owner=current_user.public_id,
                resource_id=resource_id,
                **payload.model_dump(),
            )
            db.commit()
            return state, created
        except CodeSandboxError as exc:
            db.rollback()
            raise _http(exc) from exc

    state, created = await run_db_op(operation)
    if state.status not in FINAL_RUN_STATUSES:
        try:
            await CODE_SANDBOX_RUN_COORDINATOR.schedule(state.runAttemptId)
        except CodeSandboxError as exc:
            raise _http(exc) from exc
    return {**state.model_dump(mode="json"), "created": created}


@router.get("/runs/{run_id}")
async def run_detail(
    run_id: str,
    include_complete: bool = False,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(db):
        try:
            return get_run(
                db,
                owner=current_user.public_id,
                run_id=run_id,
                include_complete=include_complete,
            )
        except CodeSandboxError as exc:
            raise _http(exc) from exc

    return await run_db_op(operation)


@router.post("/runs/{run_id}/stop")
async def stop_run(run_id: str, current_user: DBUser = Depends(get_current_user)):
    try:
        current = await run_db_op(lambda db: get_run(db, owner=current_user.public_id, run_id=run_id))
    except CodeSandboxError as exc:
        raise _http(exc) from exc
    if current["status"] in FINAL_RUN_STATUSES:
        return {**current, "stopRequested": False}
    await CODE_SANDBOX_RUN_COORDINATOR.stop(run_id)
    return {**current, "stopRequested": True}


@router.post("/resources/{resource_id}/complete", status_code=201)
async def complete_resource(
    resource_id: str,
    payload: CompleteInput,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(db):
        try:
            result = complete_run_learning(
                db,
                owner=current_user.public_id,
                user=current_user,
                resource_id=resource_id,
                run_id=payload.run_attempt_id,
                idempotency_key=payload.idempotency_key,
                context=payload.context,
                actual_minutes=payload.actual_minutes,
            )
            db.commit()
            return result
        except CodeSandboxError as exc:
            db.rollback()
            raise _http(exc) from exc
        except ContextResolutionError as exc:
            db.rollback()
            raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc

    return await run_db_op(operation)


@router.get("/resources/{resource_id}/reviews/latest")
async def latest_resource_review(
    resource_id: str,
    run_attempt_id: str,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(db):
        try:
            return {
                "schemaVersion": "f6.code-review-latest.v1",
                "item": latest_review(
                    db,
                    owner=current_user.public_id,
                    resource_id=resource_id,
                    run_attempt_id=run_attempt_id,
                ),
            }
        except CodeSandboxError as exc:
            raise _http(exc) from exc

    return await run_db_op(operation)


@router.post("/resources/{resource_id}/reviews", status_code=201)
async def create_resource_review(
    resource_id: str,
    payload: ReviewInput,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(db):
        try:
            review, created = create_review(
                db,
                owner=current_user.public_id,
                resource_id=resource_id,
                model_adapter=CODE_REVIEW_MODEL_ADAPTER,
                **payload.model_dump(),
            )
            db.commit()
            return {**review, "created": created}
        except CodeSandboxError as exc:
            db.rollback()
            raise _http(exc) from exc

    return await run_db_op(operation)


@router.get("/reviews/{review_id}")
async def review_detail(review_id: str, current_user: DBUser = Depends(get_current_user)):
    def operation(db):
        try:
            return get_review(db, owner=current_user.public_id, review_id=review_id)
        except CodeSandboxError as exc:
            raise _http(exc) from exc

    return await run_db_op(operation)


@router.post("/reviews/{review_id}/apply", status_code=201)
async def apply_review_draft(
    review_id: str,
    payload: ApplyReviewInput,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(db):
        try:
            result = apply_review(
                db,
                owner=current_user.public_id,
                review_id=review_id,
                **payload.model_dump(),
            )
            db.commit()
            return result
        except CodeSandboxError as exc:
            db.rollback()
            raise _http(exc) from exc

    return await run_db_op(operation)
