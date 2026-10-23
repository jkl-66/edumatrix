from __future__ import annotations

from typing import Literal
from fastapi import APIRouter,Depends,HTTPException,status
from pydantic import Field
from app.auth import get_current_user
from app.content_review import ContentReviewError,case_payload,queue,submit_review,transition
from app.database import DBUser,run_db_op
from app.m2_contracts import StrictModel

router=APIRouter(prefix="/api/v1/content-review",tags=["content-review"])

class SubmitInput(StrictModel):
    artifact_id:str=Field(min_length=1,max_length=64)
    version_id:str=Field(min_length=1,max_length=64)
    submission_note:str=Field(min_length=4,max_length=2000)
class DecisionInput(StrictModel):
    action:Literal["request_changes","approve","publish","withdraw"]
    reason:str=Field(min_length=4,max_length=2000)
    expected_version:int=Field(ge=1)

def _http(exc:ContentReviewError)->HTTPException:
    if exc.code.endswith("unknown"):code=status.HTTP_404_NOT_FOUND
    elif "forbidden" in exc.code:code=status.HTTP_403_FORBIDDEN
    elif "conflict" in exc.code or "stale" in exc.code:code=status.HTTP_409_CONFLICT
    else:code=status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(status_code=code,detail={"code":exc.code,"message":str(exc)})
def _op(callback):
    def wrapped(db):
        try:result=callback(db);db.commit();return result
        except ContentReviewError as exc:db.rollback();raise _http(exc) from exc
    return wrapped

@router.get("/queue")
async def get_queue(status_filter:str|None=None,current_user:DBUser=Depends(get_current_user)):
    return await run_db_op(_op(lambda db:{"schema_version":"next.content-review-queue.v1","items":queue(db,actor=current_user,status=status_filter)}))
@router.get("/cases/{case_id}")
async def get_case(case_id:str,current_user:DBUser=Depends(get_current_user)):
    def operation(db):
        items=[item for item in queue(db,actor=current_user) if item["id"]==case_id]
        if not items:raise ContentReviewError("review_case_unknown","review case does not exist or is not visible")
        return items[0]
    return await run_db_op(_op(operation))
@router.post("/cases",status_code=201)
async def post_case(payload:SubmitInput,current_user:DBUser=Depends(get_current_user)):
    return await run_db_op(_op(lambda db:case_payload(db,submit_review(db,actor=current_user,**payload.model_dump()))))
@router.post("/cases/{case_id}/decisions")
async def post_decision(case_id:str,payload:DecisionInput,current_user:DBUser=Depends(get_current_user)):
    return await run_db_op(_op(lambda db:case_payload(db,transition(db,actor=current_user,case_id=case_id,**payload.model_dump()))))
