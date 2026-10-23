from fastapi import APIRouter,Depends,HTTPException
from pydantic import Field
from app.auth import get_current_user
from app.database import DBUser,run_db_op
from app.integration_fault_drill import FaultDrillError,create_drill,execute_next,workspace
from app.m2_contracts import StrictModel
from app.m7_integrations import M7IntegrationError
router=APIRouter(prefix="/api/v1/integration-fault-drills",tags=["fc4-integration-fault-drills"])
class DrillCreate(StrictModel):organization_id:str=Field(min_length=1,max_length=64);run_key:str=Field(min_length=3,max_length=128)
class StepCreate(StrictModel):expected_lock_version:int=Field(ge=1)
def err(exc):return HTTPException(getattr(exc,"status_code",403 if getattr(exc,"code","")=="integration_forbidden" else 409),detail={"code":exc.code,"message":str(exc)})
@router.get("/workspace")
async def get_workspace(organization_id:str|None=None,current_user:DBUser=Depends(get_current_user)):
    try:return await run_db_op(lambda db:workspace(db,actor=current_user,organization_id=organization_id))
    except (FaultDrillError,M7IntegrationError) as exc:raise err(exc) from exc
@router.post("/runs",status_code=201)
async def create(payload:DrillCreate,current_user:DBUser=Depends(get_current_user)):
    try:
        def op(db):row,created=create_drill(db,actor=current_user,**payload.model_dump());return {"id":row.id,"status":row.status,"lock_version":row.lock_version,"created":created}
        return await run_db_op(op)
    except (FaultDrillError,M7IntegrationError) as exc:raise err(exc) from exc
@router.post("/runs/{drill_id}/next")
async def next_step(drill_id:str,payload:StepCreate,current_user:DBUser=Depends(get_current_user)):
    try:
        def op(db):row=execute_next(db,actor=current_user,drill_id=drill_id,**payload.model_dump());return {"id":row.id,"status":row.status,"current_scenario":row.current_scenario,"lock_version":row.lock_version,"authority_preserved":row.authority_before_hash==row.authority_after_hash}
        return await run_db_op(op)
    except (FaultDrillError,M7IntegrationError) as exc:raise err(exc) from exc
