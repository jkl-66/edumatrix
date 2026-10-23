from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field

from app.auth import get_current_user
from app.database import DBUser, run_db_op
from app.m2_contracts import StrictModel
from app.spatial_workspace import SpatialWorkspaceError, apply_action, create_workspace, get_workspace, list_workspaces, parse_command

router = APIRouter(prefix="/api/v1/spatial-workspaces", tags=["spatial-workspaces"])

class CreateInput(StrictModel):
    title: str = Field(min_length=1, max_length=256)

class ActionInput(StrictModel):
    action: str = Field(min_length=1, max_length=32)
    arguments: dict = Field(default_factory=dict)
    expected_version: int = Field(ge=1)

class CommandInput(StrictModel):
    command: str = Field(min_length=1, max_length=256)
    expected_version: int = Field(ge=1)

def _http(exc: SpatialWorkspaceError):
    code = status.HTTP_404_NOT_FOUND if exc.code.endswith("unknown") else status.HTTP_403_FORBIDDEN if "forbidden" in exc.code else status.HTTP_409_CONFLICT if "conflict" in exc.code else status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(code, detail={"code": exc.code, "message": str(exc)})

def _op(fn, commit=False):
    def operation(db):
        try:
            result = fn(db)
            if commit: db.commit()
            return result
        except SpatialWorkspaceError as exc:
            db.rollback(); raise _http(exc) from exc
    return operation

@router.get("")
async def listing(current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: list_workspaces(db, current_user)))

@router.post("", status_code=201)
async def create(payload: CreateInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: create_workspace(db, actor=current_user, title=payload.title), True))

@router.get("/{workspace_id}")
async def detail(workspace_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: get_workspace(db, actor=current_user, workspace_id=workspace_id)))

@router.post("/{workspace_id}/actions")
async def action(workspace_id: str, payload: ActionInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: apply_action(db, actor=current_user, workspace_id=workspace_id, **payload.model_dump()), True))

@router.post("/{workspace_id}/commands")
async def command(workspace_id: str, payload: CommandInput, current_user: DBUser = Depends(get_current_user)):
    try: action_name, arguments = parse_command(payload.command)
    except SpatialWorkspaceError as exc: raise _http(exc) from exc
    return await run_db_op(_op(lambda db: apply_action(db, actor=current_user, workspace_id=workspace_id, action=action_name, arguments=arguments, expected_version=payload.expected_version), True))
