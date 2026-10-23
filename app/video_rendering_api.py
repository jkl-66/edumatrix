from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import Field

from app.auth import get_current_user
from app.database import DBUser, run_db_op
from app.m2_contracts import StrictModel
from app.video_rendering import (
    VideoRenderError, cancel_task, create_project, get_project, list_projects,
    output_file, render_project, revise_script, runtime_status,
)

router = APIRouter(prefix="/api/v1/video-projects", tags=["video-projects"])


class SceneInput(StrictModel):
    title: str = Field(min_length=1, max_length=80)
    narration: str = Field(min_length=1, max_length=500)
    bullets: list[str] = Field(default_factory=list, max_length=5)
    duration_ms: int = Field(default=4000, ge=1500, le=15000)


class CreateInput(StrictModel):
    title: str = Field(min_length=1, max_length=256)
    course_id: str | None = Field(default=None, max_length=128)
    scenes: list[SceneInput] = Field(min_length=1, max_length=12)


class ReviseInput(StrictModel):
    expected_version: int = Field(ge=1)
    scenes: list[SceneInput] = Field(min_length=1, max_length=12)


class RenderInput(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=128)


def _http(exc: VideoRenderError) -> HTTPException:
    if exc.code.endswith("unknown") or exc.code.endswith("missing"):
        code = status.HTTP_404_NOT_FOUND
    elif "forbidden" in exc.code:
        code = status.HTTP_403_FORBIDDEN
    elif "conflict" in exc.code or "not_cancellable" in exc.code:
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(code, detail={"code": exc.code, "message": str(exc)})


def _op(fn, commit: bool = False):
    def operation(db):
        try:
            result = fn(db)
            if commit:
                db.commit()
            return result
        except VideoRenderError as exc:
            db.rollback()
            raise _http(exc) from exc
    return operation


@router.get("/runtime")
async def runtime(current_user: DBUser = Depends(get_current_user)):
    return runtime_status()


@router.get("")
async def listing(current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: list_projects(db, current_user), True))


@router.post("", status_code=201)
async def create(payload: CreateInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: create_project(
        db, actor=current_user, title=payload.title, course_id=payload.course_id,
        scenes=[item.model_dump() for item in payload.scenes],
    ), True))


@router.get("/{project_id}")
async def detail(project_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: get_project(db, actor=current_user, project_id=project_id), True))


@router.post("/{project_id}/scripts")
async def revise(project_id: str, payload: ReviseInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: revise_script(
        db, actor=current_user, project_id=project_id, expected_version=payload.expected_version,
        scenes=[item.model_dump() for item in payload.scenes],
    ), True))


@router.post("/{project_id}/renders")
async def render(project_id: str, payload: RenderInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: render_project(
        db, actor=current_user, project_id=project_id, idempotency_key=payload.idempotency_key,
    )))


@router.post("/tasks/{task_id}/cancel")
async def cancel(task_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: cancel_task(db, actor=current_user, task_id=task_id), True))


@router.get("/outputs/{output_id}/files/{filename}")
async def download(output_id: str, filename: str, current_user: DBUser = Depends(get_current_user)):
    def locate(db):
        path = output_file(db, actor=current_user, output_id=output_id, filename=filename)
        return str(path)
    try:
        path = await run_db_op(locate)
    except VideoRenderError as exc:
        raise _http(exc) from exc
    media = "video/mp4" if filename.endswith(".mp4") else "text/vtt" if filename.endswith(".vtt") else "application/json" if filename.endswith(".json") else "application/x-subrip"
    return FileResponse(path, media_type=media, filename=Path(path).name)
