from fastapi import APIRouter,Depends,HTTPException
from pydantic import Field
from app.auth import get_current_user
from app.competition_journey import JourneyError,create_enterprise_run,create_integration_run,create_marketplace_run,create_run,enterprise_workspace,integration_workspace,marketplace_workspace,payload,record_visit,verify_marketplace_search,workspace
from app.database import DBUser,run_db_op
from app.m2_contracts import StrictModel
router=APIRouter(prefix='/api/v1/competition-journeys',tags=['fc5-competition-journeys'])
class RunCreate(StrictModel):course_id:str|None=Field(default=None,max_length=128);run_key:str=Field(min_length=3,max_length=128)
class VisitCreate(StrictModel):step_key:str=Field(pattern='^(profile|diagnosis|path|resource|lab|formal_exam|retest|path_update)$');route:str=Field(min_length=1,max_length=128)
class MediaVisitCreate(StrictModel):step_key:str=Field(pattern='^(chapter|handout|deck|avatar_audio|video|video_practice|bundle)$');route:str=Field(min_length=1,max_length=128)
class TeacherVisitCreate(StrictModel):step_key:str=Field(pattern='^(course|class_group|task|analytics|intervention|content_review|effect_review)$');route:str=Field(min_length=1,max_length=128)
class EnterpriseRunCreate(StrictModel):organization_id:str=Field(min_length=1,max_length=64);learner_public_id:str=Field(min_length=1,max_length=64);run_key:str=Field(min_length=3,max_length=128)
class EnterpriseVisitCreate(StrictModel):step_key:str=Field(pattern='^(job_standard|role_gap|training_cohort|practical|demo_signoff|certification|retraining)$');route:str=Field(min_length=1,max_length=128)
class MarketplaceRunCreate(StrictModel):listing_id:str=Field(min_length=1,max_length=64);recipient_public_id:str=Field(min_length=1,max_length=64);run_key:str=Field(min_length=3,max_length=128)
class MarketplaceVisitCreate(StrictModel):step_key:str=Field(pattern='^(submission|review_publish|search|engagement|acquisition|fork|update_notification|withdrawal_impact)$');route:str=Field(min_length=1,max_length=128)
class IntegrationRunCreate(StrictModel):organization_id:str=Field(min_length=1,max_length=64);learner_public_id:str=Field(min_length=1,max_length=64);run_key:str=Field(min_length=3,max_length=128)
class IntegrationVisitCreate(StrictModel):step_key:str=Field(pattern='^(sso|hr_lms|xapi_webhook|fault|retry|reconciliation)$');route:str=Field(min_length=1,max_length=128)
def err(exc):return HTTPException(exc.status_code,detail={'code':exc.code,'message':str(exc)})
@router.get('/student')
async def get_student(current_user:DBUser=Depends(get_current_user)):
 try:return await run_db_op(lambda db:workspace(db,actor=current_user))
 except JourneyError as exc:raise err(exc) from exc
@router.post('/student/runs',status_code=201)
async def create_student(body:RunCreate,current_user:DBUser=Depends(get_current_user)):
 try:
  def op(db):row,created=create_run(db,actor=current_user,**body.model_dump());return {**payload(db,current_user,row),'created':created}
  return await run_db_op(op)
 except JourneyError as exc:raise err(exc) from exc
@router.get('/student/runs/{run_id}')
async def get_run(run_id:str,current_user:DBUser=Depends(get_current_user)):
 try:
  def op(db):row=db.get(__import__('app.database',fromlist=['DBCompetitionJourneyRun']).DBCompetitionJourneyRun,run_id);return payload(db,current_user,row) if row else (_ for _ in ()).throw(JourneyError('journey_not_found','journey run does not exist',404))
  return await run_db_op(op)
 except JourneyError as exc:raise err(exc) from exc
@router.post('/student/runs/{run_id}/visits',status_code=201)
async def visit(run_id:str,body:VisitCreate,current_user:DBUser=Depends(get_current_user)):
 try:
  def op(db):row=record_visit(db,actor=current_user,run_id=run_id,**body.model_dump());return {'id':row.id,'step_key':row.step_key,'evidence_hash':row.evidence_hash}
  return await run_db_op(op)
 except JourneyError as exc:raise err(exc) from exc
@router.get('/media')
async def get_media(current_user:DBUser=Depends(get_current_user)):
 try:return await run_db_op(lambda db:workspace(db,actor=current_user,journey_type='media'))
 except JourneyError as exc:raise err(exc) from exc
@router.post('/media/runs',status_code=201)
async def create_media(body:RunCreate,current_user:DBUser=Depends(get_current_user)):
 try:
  def op(db):row,created=create_run(db,actor=current_user,journey_type='media',**body.model_dump());return {**payload(db,current_user,row),'created':created}
  return await run_db_op(op)
 except JourneyError as exc:raise err(exc) from exc
@router.get('/media/runs/{run_id}')
async def get_media_run(run_id:str,current_user:DBUser=Depends(get_current_user)):
 try:
  def op(db):
   row=db.get(__import__('app.database',fromlist=['DBCompetitionJourneyRun']).DBCompetitionJourneyRun,run_id)
   if not row:raise JourneyError('journey_not_found','journey run does not exist',404)
   if row.journey_type!='media':raise JourneyError('journey_type_mismatch','journey is not a media run',404)
   return payload(db,current_user,row)
  return await run_db_op(op)
 except JourneyError as exc:raise err(exc) from exc
@router.post('/media/runs/{run_id}/visits',status_code=201)
async def media_visit(run_id:str,body:MediaVisitCreate,current_user:DBUser=Depends(get_current_user)):
 try:
  def op(db):row=record_visit(db,actor=current_user,run_id=run_id,**body.model_dump());return {'id':row.id,'step_key':row.step_key,'evidence_hash':row.evidence_hash}
  return await run_db_op(op)
 except JourneyError as exc:raise err(exc) from exc
@router.get('/teacher')
async def get_teacher(current_user:DBUser=Depends(get_current_user)):
 try:return await run_db_op(lambda db:workspace(db,actor=current_user,journey_type='teacher'))
 except JourneyError as exc:raise err(exc) from exc
@router.post('/teacher/runs',status_code=201)
async def create_teacher(body:RunCreate,current_user:DBUser=Depends(get_current_user)):
 try:
  def op(db):row,created=create_run(db,actor=current_user,journey_type='teacher',**body.model_dump());return {**payload(db,current_user,row),'created':created}
  return await run_db_op(op)
 except JourneyError as exc:raise err(exc) from exc
@router.get('/teacher/runs/{run_id}')
async def get_teacher_run(run_id:str,current_user:DBUser=Depends(get_current_user)):
 try:
  def op(db):
   row=db.get(__import__('app.database',fromlist=['DBCompetitionJourneyRun']).DBCompetitionJourneyRun,run_id)
   if not row or row.journey_type!='teacher':raise JourneyError('journey_not_found','teacher journey run does not exist',404)
   return payload(db,current_user,row)
  return await run_db_op(op)
 except JourneyError as exc:raise err(exc) from exc
@router.post('/teacher/runs/{run_id}/visits',status_code=201)
async def teacher_visit(run_id:str,body:TeacherVisitCreate,current_user:DBUser=Depends(get_current_user)):
 try:
  def op(db):
   row=db.get(__import__('app.database',fromlist=['DBCompetitionJourneyRun']).DBCompetitionJourneyRun,run_id)
   if not row or row.journey_type!='teacher':raise JourneyError('journey_not_found','teacher journey run does not exist',404)
   visit=record_visit(db,actor=current_user,run_id=run_id,**body.model_dump());return {'id':visit.id,'step_key':visit.step_key,'evidence_hash':visit.evidence_hash}
  return await run_db_op(op)
 except JourneyError as exc:raise err(exc) from exc
@router.get('/enterprise')
async def get_enterprise(current_user:DBUser=Depends(get_current_user)):
 try:return await run_db_op(lambda db:enterprise_workspace(db,actor=current_user))
 except JourneyError as exc:raise err(exc) from exc
@router.post('/enterprise/runs',status_code=201)
async def create_enterprise(body:EnterpriseRunCreate,current_user:DBUser=Depends(get_current_user)):
 try:
  def op(db):row,created=create_enterprise_run(db,actor=current_user,**body.model_dump());return {**payload(db,current_user,row),'created':created}
  return await run_db_op(op)
 except JourneyError as exc:raise err(exc) from exc
@router.get('/enterprise/runs/{run_id}')
async def get_enterprise_run(run_id:str,current_user:DBUser=Depends(get_current_user)):
 try:
  def op(db):
   row=db.get(__import__('app.database',fromlist=['DBCompetitionJourneyRun']).DBCompetitionJourneyRun,run_id)
   if not row or row.journey_type!='enterprise':raise JourneyError('journey_not_found','enterprise journey run does not exist',404)
   return payload(db,current_user,row)
  return await run_db_op(op)
 except JourneyError as exc:raise err(exc) from exc
@router.post('/enterprise/runs/{run_id}/visits',status_code=201)
async def enterprise_visit(run_id:str,body:EnterpriseVisitCreate,current_user:DBUser=Depends(get_current_user)):
 try:
  def op(db):
   row=db.get(__import__('app.database',fromlist=['DBCompetitionJourneyRun']).DBCompetitionJourneyRun,run_id)
   if not row or row.journey_type!='enterprise':raise JourneyError('journey_not_found','enterprise journey run does not exist',404)
   visit=record_visit(db,actor=current_user,run_id=run_id,**body.model_dump());return {'id':visit.id,'step_key':visit.step_key,'evidence_hash':visit.evidence_hash}
  return await run_db_op(op)
 except JourneyError as exc:raise err(exc) from exc
@router.get('/marketplace')
async def get_marketplace(current_user:DBUser=Depends(get_current_user)):
 try:return await run_db_op(lambda db:marketplace_workspace(db,actor=current_user))
 except JourneyError as exc:raise err(exc) from exc
@router.post('/marketplace/runs',status_code=201)
async def create_marketplace(body:MarketplaceRunCreate,current_user:DBUser=Depends(get_current_user)):
 try:
  def op(db):row,created=create_marketplace_run(db,actor=current_user,**body.model_dump());return {**payload(db,current_user,row),'created':created}
  return await run_db_op(op)
 except JourneyError as exc:raise err(exc) from exc
@router.get('/marketplace/runs/{run_id}')
async def get_marketplace_run(run_id:str,current_user:DBUser=Depends(get_current_user)):
 try:
  def op(db):
   row=db.get(__import__('app.database',fromlist=['DBCompetitionJourneyRun']).DBCompetitionJourneyRun,run_id)
   if not row or row.journey_type!='marketplace':raise JourneyError('journey_not_found','marketplace journey run does not exist',404)
   return payload(db,current_user,row)
  return await run_db_op(op)
 except JourneyError as exc:raise err(exc) from exc
@router.post('/marketplace/runs/{run_id}/visits',status_code=201)
async def marketplace_visit(run_id:str,body:MarketplaceVisitCreate,current_user:DBUser=Depends(get_current_user)):
 try:
  def op(db):
   row=db.get(__import__('app.database',fromlist=['DBCompetitionJourneyRun']).DBCompetitionJourneyRun,run_id)
   if not row or row.journey_type!='marketplace':raise JourneyError('journey_not_found','marketplace journey run does not exist',404)
   visit=record_visit(db,actor=current_user,run_id=run_id,**body.model_dump());return {'id':visit.id,'step_key':visit.step_key,'evidence_hash':visit.evidence_hash}
  return await run_db_op(op)
 except JourneyError as exc:raise err(exc) from exc
@router.post('/marketplace/runs/{run_id}/search-verification',status_code=201)
async def marketplace_search_verification(run_id:str,current_user:DBUser=Depends(get_current_user)):
 try:
  def op(db):row,created=verify_marketplace_search(db,actor=current_user,run_id=run_id);return {'id':row.id,'listing_id':row.listing_id,'query':row.query,'result_hash':row.result_hash,'created':created}
  return await run_db_op(op)
 except JourneyError as exc:raise err(exc) from exc

@router.get('/integration')
async def get_integration(current_user:DBUser=Depends(get_current_user)):
 try:return await run_db_op(lambda db:integration_workspace(db,actor=current_user))
 except JourneyError as exc:raise err(exc) from exc

@router.post('/integration/runs',status_code=201)
async def create_integration(body:IntegrationRunCreate,current_user:DBUser=Depends(get_current_user)):
 try:
  def op(db):row,created=create_integration_run(db,actor=current_user,**body.model_dump());return {**payload(db,current_user,row),'created':created}
  return await run_db_op(op)
 except JourneyError as exc:raise err(exc) from exc

@router.get('/integration/runs/{run_id}')
async def get_integration_run(run_id:str,current_user:DBUser=Depends(get_current_user)):
 try:
  def op(db):
   row=db.get(__import__('app.database',fromlist=['DBCompetitionJourneyRun']).DBCompetitionJourneyRun,run_id)
   if not row or row.journey_type!='integration':raise JourneyError('journey_not_found','integration journey run does not exist',404)
   return payload(db,current_user,row)
  return await run_db_op(op)
 except JourneyError as exc:raise err(exc) from exc

@router.post('/integration/runs/{run_id}/visits',status_code=201)
async def integration_visit(run_id:str,body:IntegrationVisitCreate,current_user:DBUser=Depends(get_current_user)):
 try:
  def op(db):
   row=db.get(__import__('app.database',fromlist=['DBCompetitionJourneyRun']).DBCompetitionJourneyRun,run_id)
   if not row or row.journey_type!='integration':raise JourneyError('journey_not_found','integration journey run does not exist',404)
   visit=record_visit(db,actor=current_user,run_id=run_id,**body.model_dump());return {'id':visit.id,'step_key':visit.step_key,'evidence_hash':visit.evidence_hash}
  return await run_db_op(op)
 except JourneyError as exc:raise err(exc) from exc
