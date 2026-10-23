from typing import Literal
from fastapi import APIRouter,Depends,HTTPException,status
from pydantic import Field
from app.auth import get_current_user
from app.database import DBUser,run_db_op
from app.m2_contracts import StrictModel
from app.organization_marketplace import OrganizationMarketplaceError,acquire,catalog,organizations,publish,withdraw
router=APIRouter(prefix='/api/v1/organization-marketplace',tags=['organization-marketplace'])
class Listing(StrictModel):
 organization_id:str=Field(min_length=1,max_length=64);course_id:str=Field(min_length=1,max_length=128);title:str=Field(min_length=1,max_length=256);summary:str=Field(min_length=8,max_length=4000);category:str=Field(min_length=1,max_length=128);tags:list[str]=Field(default_factory=list,max_length=20)
class Withdraw(StrictModel):reason:str=Field(min_length=8,max_length=2000);expected_version:int=Field(ge=1)
def http(e):
 c=status.HTTP_404_NOT_FOUND if e.code.endswith('unknown') else status.HTTP_403_FORBIDDEN if 'forbidden' in e.code else status.HTTP_409_CONFLICT if 'conflict' in e.code else status.HTTP_422_UNPROCESSABLE_CONTENT;return HTTPException(c,detail={'code':e.code,'message':str(e)})
def op(f):
 def x(db):
  try:r=f(db);db.commit();return r
  except OrganizationMarketplaceError as e:db.rollback();raise http(e) from e
 return x
@router.get('/organizations')
async def get_orgs(current_user:DBUser=Depends(get_current_user)):return await run_db_op(op(lambda db:{'items':organizations(db,current_user)}))
@router.get('/organizations/{organization_id}')
async def get_catalog(organization_id:str,q:str='',current_user:DBUser=Depends(get_current_user)):return await run_db_op(op(lambda db:catalog(db,actor=current_user,organization_id=organization_id,query=q)))
@router.post('/listings',status_code=201)
async def post_listing(p:Listing,current_user:DBUser=Depends(get_current_user)):return await run_db_op(op(lambda db:publish(db,actor=current_user,**p.model_dump())))
@router.post('/listings/{listing_id}/acquisitions',status_code=201)
async def post_acquire(listing_id:str,current_user:DBUser=Depends(get_current_user)):return await run_db_op(op(lambda db:acquire(db,actor=current_user,listing_id=listing_id)))
@router.post('/listings/{listing_id}/withdraw')
async def post_withdraw(listing_id:str,p:Withdraw,current_user:DBUser=Depends(get_current_user)):return await run_db_op(op(lambda db:withdraw(db,actor=current_user,listing_id=listing_id,**p.model_dump())))
