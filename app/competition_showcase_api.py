from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.competition_showcase import initialize_showcase, showcase_workspace
from app.database import DBUser, run_db_op


router = APIRouter(prefix="/api/v1/competition-showcase", tags=["fc5-competition-showcase"])


@router.get("")
async def get_showcase(current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(lambda db: showcase_workspace(db, actor=current_user))


@router.post("/bootstrap")
async def bootstrap_showcase(current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(lambda db: initialize_showcase(db, actor=current_user))
