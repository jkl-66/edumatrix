from typing import Any,Literal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import Field
from app.auth import get_current_user
from app.database import DBUser,run_db_op
from app.m2_contracts import StrictModel
from app.multilevel_review import MultilevelReviewError,decide,payload,queue,submit
router=APIRouter(prefix='/api/v1/multilevel-review',tags=['multilevel-review'])
class Submit(StrictModel):organization_id:str;object_type:str=Field(min_length=1,max_length=64);object_id:str=Field(min_length=1,max_length=64);object_version:str=Field(min_length=1,max_length=128);evidence_snapshot:dict[str,Any]=Field(default_factory=dict)
class Decision(StrictModel):action:Literal['approve','return'];reason:str=Field(min_length=4,max_length=1000);expected_version:int=Field(ge=1)
def http(e):return HTTPException(status_code=404 if e.code.endswith('unknown') else 403 if 'forbidden' in e.code or 'separation' in e.code else 409,detail={'code':e.code,'message':str(e)})
def op(fn):
 def run(db):
  try:r=fn(db);db.commit();return r
  except MultilevelReviewError as e:db.rollback();raise http(e)
 return run
@router.get('/queue')
async def get_queue(organization_id:str,current_user:DBUser=Depends(get_current_user)):return await run_db_op(op(lambda db:{'items':queue(db,actor=current_user,organization_id=organization_id)}))
@router.post('/cases',status_code=201)
async def post_case(body:Submit,current_user:DBUser=Depends(get_current_user)):
 def run(db):row,created=submit(db,actor=current_user,**body.model_dump());return {'created':created,'case':payload(db,row)}
 return await run_db_op(op(run))
@router.post('/cases/{case_id}/decisions')
async def post_decision(case_id:str,body:Decision,current_user:DBUser=Depends(get_current_user)):return await run_db_op(op(lambda db:payload(db,decide(db,actor=current_user,case_id=case_id,**body.model_dump()))))
