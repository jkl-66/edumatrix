from datetime import datetime
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import Field
from app.auth import get_current_user
from app.database import DBUser,run_db_op
from app.enterprise_risk import EnterpriseRiskError,create_report,decide,payload,workspace
from app.m2_contracts import StrictModel
router=APIRouter(prefix='/api/v1/enterprise-risk',tags=['enterprise-risk'])
class ReportCreate(StrictModel):organization_id:str;period_start:datetime;period_end:datetime
class DecisionCreate(StrictModel):action:Literal['acknowledge','close'];reason:str=Field(min_length=4,max_length=1000);expected_version:int=Field(ge=1)
def http(e):return HTTPException(status_code=404 if e.code.endswith('unknown') else 403 if 'forbidden' in e.code else 409,detail={'code':e.code,'message':str(e)})
def op(fn):
 def run(db):
  try:r=fn(db);db.commit();return r
  except EnterpriseRiskError as e:db.rollback();raise http(e)
 return run
@router.get('/workspace')
async def get_workspace(organization_id:str,current_user:DBUser=Depends(get_current_user)):return await run_db_op(op(lambda db:workspace(db,actor=current_user,organization_id=organization_id)))
@router.post('/reports',status_code=201)
async def post_report(body:ReportCreate,current_user:DBUser=Depends(get_current_user)):
 def run(db):row,created=create_report(db,actor=current_user,**body.model_dump());return {'created':created,'report':payload(db,row)}
 return await run_db_op(op(run))
@router.post('/reports/{report_id}/decisions')
async def post_decision(report_id:str,body:DecisionCreate,current_user:DBUser=Depends(get_current_user)):return await run_db_op(op(lambda db:payload(db,decide(db,actor=current_user,report_id=report_id,**body.model_dump()))))
