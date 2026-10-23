from typing import Any
from fastapi import APIRouter,Depends,HTTPException,status
from pydantic import Field
from app.auth import get_current_user
from app.database import DBUser,run_db_op
from app.m2_contracts import StrictModel
from app.local_adapters import LocalAdapterError,action,create,list_adapters,listing,owned,payload
router=APIRouter(prefix='/api/v1/local-adapters',tags=['local-adapters'])
class CreateInput(StrictModel):
 title:str=Field(min_length=1,max_length=256);adapter_id:str=Field(min_length=1,max_length=64);credential_placeholder:str=Field(min_length=1,max_length=128);parameters:dict[str,Any]
class ActionInput(StrictModel):
 action:str=Field(pattern='^(connect|configure|inject_fault|run|diagnose|recover|rerun|submit|reset)$');expected_lock_version:int=Field(ge=1);idempotency_key:str=Field(min_length=8,max_length=128);parameters:dict[str,Any]|None=None;fault_type:str='none';diagnosis:str=Field(default='',max_length=500);recovery_action:str=Field(default='',max_length=64)
def http(e):
 code=status.HTTP_404_NOT_FOUND if e.code.endswith('unknown') else status.HTTP_403_FORBIDDEN if 'forbidden' in e.code else status.HTTP_409_CONFLICT if 'conflict' in e.code else status.HTTP_422_UNPROCESSABLE_CONTENT;return HTTPException(code,detail={'code':e.code,'message':str(e)})
def op(fn,commit=False):
 def f(db):
  try:
   r=fn(db)
   if commit:db.commit()
   return r
  except LocalAdapterError as e:db.rollback();raise http(e) from e
 return f
@router.get('/catalog')
async def catalog(user:DBUser=Depends(get_current_user)):return list_adapters()
@router.get('')
async def sessions(user:DBUser=Depends(get_current_user)):return await run_db_op(op(lambda db:listing(db,user)))
@router.post('',status_code=201)
async def session_create(data:CreateInput,user:DBUser=Depends(get_current_user)):return await run_db_op(op(lambda db:create(db,user,**data.model_dump()),True))
@router.get('/{session_id}')
async def detail(session_id:str,user:DBUser=Depends(get_current_user)):return await run_db_op(op(lambda db:payload(db,owned(db,user,session_id))))
@router.post('/{session_id}/actions')
async def session_action(session_id:str,data:ActionInput,user:DBUser=Depends(get_current_user)):return await run_db_op(op(lambda db:action(db,user,session_id,**data.model_dump()),True))
