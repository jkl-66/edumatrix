from __future__ import annotations
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import Field
from app.auth import get_current_user
from app.database import DBUser,run_db_op
from app.integration_reconciliation import ReconciliationError,create_reconciliation_run,decide_repair,reconciliation_workspace
from app.m2_contracts import StrictModel
from app.m7_integrations import M7IntegrationError
router=APIRouter(prefix='/api/v1/integration-reconciliation',tags=['fc4-integration-reconciliation'])
class RunCreate(StrictModel):
    organization_id:str=Field(min_length=1,max_length=64);run_key:str=Field(min_length=3,max_length=128);expected_preview_hash:str=Field(min_length=64,max_length=64)
class RepairCreate(StrictModel):
    discrepancy_key:str=Field(min_length=1,max_length=160);action:Literal['acknowledge','requeue','dismiss'];reason:str=Field(min_length=3,max_length=500);expected_lock_version:int=Field(ge=1)
def _error(exc):return HTTPException(status_code=getattr(exc,'status_code',403 if getattr(exc,'code','')=='integration_forbidden' else 409),detail={'code':exc.code,'message':str(exc)})
@router.get('/workspace')
async def get_workspace(organization_id:str|None=None,current_user:DBUser=Depends(get_current_user)):
    try:return await run_db_op(lambda db:reconciliation_workspace(db,actor=current_user,organization_id=organization_id))
    except (ReconciliationError,M7IntegrationError) as exc:raise _error(exc) from exc
@router.post('/runs',status_code=201)
async def create_run(payload:RunCreate,current_user:DBUser=Depends(get_current_user)):
    try:
        def op(db):
            row,created=create_reconciliation_run(db,actor=current_user,**payload.model_dump());return {'id':row.id,'status':row.status,'lock_version':row.lock_version,'snapshot_hash':row.snapshot_hash,'created':created}
        return await run_db_op(op)
    except (ReconciliationError,M7IntegrationError) as exc:raise _error(exc) from exc
@router.post('/runs/{run_id}/decisions',status_code=201)
async def create_decision(run_id:str,payload:RepairCreate,current_user:DBUser=Depends(get_current_user)):
    try:
        def op(db):
            row,run=decide_repair(db,actor=current_user,run_id=run_id,**payload.model_dump());return {'id':row.id,'action':row.action,'evidence_hash':row.evidence_hash,'run_status':run.status,'lock_version':run.lock_version}
        return await run_db_op(op)
    except (ReconciliationError,M7IntegrationError) as exc:raise _error(exc) from exc
