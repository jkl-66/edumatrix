from fastapi import APIRouter,Depends,HTTPException,status
from pydantic import Field
from app.auth import get_current_user
from app.database import DBUser,run_db_op
from app.m2_contracts import StrictModel
from app.plugin_registry import PluginRegistryError,detail,discover,install,uninstall
router=APIRouter(prefix='/api/v1/plugins',tags=['plugin-registry'])
class Remove(StrictModel):expected_version:int=Field(ge=1)
def http(e):return HTTPException(status.HTTP_404_NOT_FOUND if e.code.endswith('unknown') else status.HTTP_403_FORBIDDEN if 'forbidden' in e.code else status.HTTP_409_CONFLICT if 'conflict' in e.code else status.HTTP_422_UNPROCESSABLE_CONTENT,detail={'code':e.code,'message':str(e)})
def op(fn,commit=False):
 def run(db):
  try:r=fn(db);db.commit() if commit else None;return r
  except PluginRegistryError as e:
   if e.code.startswith('plugin_'):db.commit()
   else:db.rollback()
   raise http(e) from e
 return run
@router.get('')
async def listing(current_user:DBUser=Depends(get_current_user)):return await run_db_op(op(lambda db:discover(db,current_user)))
@router.get('/{plugin_id}')
async def get(plugin_id:str,current_user:DBUser=Depends(get_current_user)):return await run_db_op(op(lambda db:detail(db,actor=current_user,plugin_id=plugin_id)))
@router.post('/{plugin_id}/install')
async def post_install(plugin_id:str,current_user:DBUser=Depends(get_current_user)):return await run_db_op(op(lambda db:install(db,actor=current_user,plugin_id=plugin_id),True))
@router.post('/{plugin_id}/uninstall')
async def post_uninstall(plugin_id:str,p:Remove,current_user:DBUser=Depends(get_current_user)):return await run_db_op(op(lambda db:uninstall(db,actor=current_user,plugin_id=plugin_id,expected_version=p.expected_version),True))
