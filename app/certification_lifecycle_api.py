from fastapi import APIRouter,Depends,HTTPException
from pydantic import Field
from app.auth import get_current_user
from app.certification_lifecycle import CertificationLifecycleError,mark_read,revoke,scan,workspace
from app.database import DBUser,run_db_op
from app.m2_contracts import StrictModel
router=APIRouter(prefix='/api/v1/certification-lifecycle',tags=['certification-lifecycle'])
class RevokeInput(StrictModel):reason:str=Field(min_length=4,max_length=1000);expected_version:int=Field(ge=1)
class ScanInput(StrictModel):organization_id:str=Field(min_length=1,max_length=64);upcoming_days:int=Field(default=30,ge=1,le=180)
def _http(e):return HTTPException(status_code=404 if e.code.endswith('unknown') else 403 if 'forbidden' in e.code else 409,detail={'code':e.code,'message':str(e)})
def _op(fn):
 def wrapped(db):
  try:r=fn(db);db.commit();return r
  except CertificationLifecycleError as e:db.rollback();raise _http(e)
 return wrapped
@router.get('/workspace')
async def get_workspace(organization_id:str,current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:workspace(db,actor=current_user,organization_id=organization_id)))
@router.post('/certifications/{certification_id}/revoke')
async def post_revoke(certification_id:str,payload:RevokeInput,current_user:DBUser=Depends(get_current_user)):
 def run(db):cert,event,task=revoke(db,actor=current_user,certification_id=certification_id,**payload.model_dump());return {'certification_id':cert.id,'status':cert.status,'lock_version':cert.lock_version,'event_id':event.id,'retraining_task_id':task.id}
 return await run_db_op(_op(run))
@router.post('/scan')
async def post_scan(payload:ScanInput,current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:scan(db,actor=current_user,**payload.model_dump())))
@router.post('/notifications/{notice_id}/read')
async def post_read(notice_id:str,current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:{'id':mark_read(db,actor=current_user,notice_id=notice_id).id,'read':True}))
