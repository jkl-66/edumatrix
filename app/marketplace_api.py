from __future__ import annotations

from typing import Any, Literal
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import Field

from app.auth import get_current_user
from app.database import DBUser, run_db_op
from app.m2_contracts import StrictModel
from app.marketplace import (MarketplaceError, acquire, create_report, decide_report, public_search,
    review_listing, submit_listing, workspace, get_listing, list_comments, create_comment, edit_comment,
    delete_comment, moderate_comment, report_comment, decide_comment_report,
    marketplace_engagement, set_favorite, upsert_review, impact_inbox, update_impact_notice,
    create_fork, create_fork_version, decide_fork_update, fork_workspace,
    get_marketplace_recommendation, run_marketplace_recommendation)

router = APIRouter(prefix="/api/v1/marketplace", tags=["marketplace"])

class ListingInput(StrictModel):
    item_type: Literal["course","resource","resource_bundle","learning_path"] = "course"
    course_id: str | None = Field(default=None,min_length=1,max_length=128)
    source_object_id: str | None = Field(default=None,min_length=1,max_length=128)
    source_version_id: str | None = Field(default=None,min_length=1,max_length=128)
    title: str = Field(min_length=1,max_length=256)
    summary: str = Field(min_length=8,max_length=4000); category: str = Field(min_length=1,max_length=128)
    tags: list[str] = Field(default_factory=list,max_length=20)
class ReviewInput(StrictModel):
    action: Literal["request_changes","approve","publish","withdraw"]
    reason: str = Field(min_length=8,max_length=2000); expected_version: int = Field(ge=1)
    impact_kind: Literal["new_version","severe_fix"] | None = None
class ReportInput(StrictModel):
    category: Literal["license","accuracy","safety","privacy","other"]
    description: str = Field(min_length=8,max_length=4000)
class ReportDecisionInput(StrictModel):
    action: Literal["dismiss","withdraw"]; reason: str = Field(min_length=8,max_length=2000); expected_version: int = Field(ge=1)
class CommentInput(StrictModel): body: str = Field(min_length=2,max_length=2000)
class CommentEditInput(CommentInput): expected_version: int = Field(ge=1)
class CommentVersionInput(StrictModel): expected_version: int = Field(ge=1)
class CommentModerationInput(StrictModel):
    action: Literal["hide","restore"]; reason: str = Field(min_length=4,max_length=1000); expected_version: int = Field(ge=1)
class CommentReportInput(StrictModel):
    category: Literal["abuse","spam","accuracy","privacy","other"]; description: str = Field(min_length=4,max_length=2000)
class CommentReportDecisionInput(StrictModel):
    action: Literal["dismiss","hide"]; reason: str = Field(min_length=4,max_length=1000); expected_version: int = Field(ge=1)
class FavoriteInput(StrictModel):
    active: bool; expected_version: int | None = Field(default=None,ge=1)
class MarketplaceReviewInput(StrictModel):
    rating: int = Field(ge=1,le=5); body: str = Field(min_length=2,max_length=2000)
    expected_version: int | None = Field(default=None,ge=1)
class ImpactNotificationInput(StrictModel):
    expected_version: int = Field(ge=1)
    action: Literal["view_source","keep_copy","review_update"] | None = None
class MarketplaceForkInput(StrictModel):
    modification_summary: str = Field(min_length=4,max_length=2000)
class MarketplaceForkVersionInput(StrictModel):
    expected_version: int = Field(ge=1)
    modification_summary: str = Field(min_length=4,max_length=2000)
    patch: dict[str, Any]
class MarketplaceForkDecisionInput(StrictModel):
    upstream_listing_id: str = Field(min_length=1,max_length=64)
    action: Literal["accept_non_conflicting","keep_local","ignore"]
    reason: str = Field(min_length=4,max_length=2000)
    expected_version: int = Field(ge=1)
class MarketplaceRecommendationInput(StrictModel):
    learning_goals: list[str] = Field(default_factory=list,max_length=20)
    topics: list[str] = Field(default_factory=list,max_length=20)
    target_difficulty: float | None = Field(default=None,ge=0,le=1)

def _http(exc: MarketplaceError)->HTTPException:
    if exc.code.endswith("unknown"): code=status.HTTP_404_NOT_FOUND
    elif "forbidden" in exc.code: code=status.HTTP_403_FORBIDDEN
    elif any(x in exc.code for x in ("conflict","resolved")): code=status.HTTP_409_CONFLICT
    else: code=status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(code,detail={"code":exc.code,"message":str(exc)})
def _op(callback):
    def wrapped(db):
        try:r=callback(db);db.commit();return r
        except MarketplaceError as exc:db.rollback();raise _http(exc) from exc
    return wrapped

@router.get("/public")
async def get_public(q:str=Query("",max_length=128),category:str=Query("",max_length=128),tag:str=Query("",max_length=64),
                     item_type:Literal["course","resource","resource_bundle","learning_path"]|None=Query(default=None),
                     current_user:DBUser=Depends(get_current_user)):
    return await run_db_op(_op(lambda db:{"schema_version":"f9.marketplace-public.v1","items":public_search(
        db,query=q,category=category,tag=tag,item_type=item_type or "",actor=current_user)}))
@router.get("/workspace")
async def get_workspace(current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:workspace(db,current_user)))
@router.post("/listings",status_code=201)
async def post_listing(payload:ListingInput,current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:submit_listing(db,actor=current_user,**payload.model_dump())))
@router.get("/listings/{listing_id}")
async def get_listing_detail(listing_id:str,current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:get_listing(db,actor=current_user,listing_id=listing_id)))
@router.post("/listings/{listing_id}/decisions")
async def post_review(listing_id:str,payload:ReviewInput,current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:review_listing(db,actor=current_user,listing_id=listing_id,**payload.model_dump())))
@router.post("/listings/{listing_id}/reports",status_code=201)
async def post_report(listing_id:str,payload:ReportInput,current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:create_report(db,actor=current_user,listing_id=listing_id,**payload.model_dump())))
@router.post("/reports/{report_id}/decisions")
async def post_report_decision(report_id:str,payload:ReportDecisionInput,current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:decide_report(db,actor=current_user,report_id=report_id,**payload.model_dump())))
@router.post("/listings/{listing_id}/acquisitions",status_code=201)
async def post_acquire(listing_id:str,current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:acquire(db,actor=current_user,listing_id=listing_id)))
@router.get("/listings/{listing_id}/comments")
async def get_comments(listing_id:str,current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:list_comments(db,actor=current_user,listing_id=listing_id)))
@router.post("/listings/{listing_id}/comments",status_code=201)
async def post_comment(listing_id:str,payload:CommentInput,current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:create_comment(db,actor=current_user,listing_id=listing_id,body=payload.body)))
@router.put("/comments/{comment_id}")
async def put_comment(comment_id:str,payload:CommentEditInput,current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:edit_comment(db,actor=current_user,comment_id=comment_id,body=payload.body,expected_version=payload.expected_version)))
@router.delete("/comments/{comment_id}")
async def remove_comment(comment_id:str,payload:CommentVersionInput,current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:delete_comment(db,actor=current_user,comment_id=comment_id,expected_version=payload.expected_version)))
@router.post("/comments/{comment_id}/moderation")
async def post_comment_moderation(comment_id:str,payload:CommentModerationInput,current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:moderate_comment(db,actor=current_user,comment_id=comment_id,**payload.model_dump())))
@router.post("/comments/{comment_id}/reports",status_code=201)
async def post_comment_report(comment_id:str,payload:CommentReportInput,current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:report_comment(db,actor=current_user,comment_id=comment_id,**payload.model_dump())))
@router.post("/comment-reports/{report_id}/decisions")
async def post_comment_report_decision(report_id:str,payload:CommentReportDecisionInput,current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:decide_comment_report(db,actor=current_user,report_id=report_id,**payload.model_dump())))
@router.get("/listings/{listing_id}/engagement")
async def get_engagement(listing_id:str,current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:marketplace_engagement(db,actor=current_user,listing_id=listing_id)))
@router.put("/listings/{listing_id}/favorite")
async def put_favorite(listing_id:str,payload:FavoriteInput,current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:set_favorite(db,actor=current_user,listing_id=listing_id,**payload.model_dump())))
@router.put("/listings/{listing_id}/review")
async def put_review(listing_id:str,payload:MarketplaceReviewInput,current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:upsert_review(db,actor=current_user,listing_id=listing_id,**payload.model_dump())))
@router.get("/impact-notifications")
async def get_impact_notifications(current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:impact_inbox(db,actor=current_user)))
@router.post("/impact-notifications/{notice_id}")
async def post_impact_notification(notice_id:str,payload:ImpactNotificationInput,current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:update_impact_notice(db,actor=current_user,notice_id=notice_id,**payload.model_dump())))
@router.get("/forks")
async def get_forks(current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:fork_workspace(db,actor=current_user)))
@router.post("/listings/{listing_id}/forks",status_code=201)
async def post_fork(listing_id:str,payload:MarketplaceForkInput,current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:create_fork(db,actor=current_user,listing_id=listing_id,**payload.model_dump())))
@router.post("/forks/{fork_id}/versions",status_code=201)
async def post_fork_version(fork_id:str,payload:MarketplaceForkVersionInput,current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:create_fork_version(db,actor=current_user,fork_id=fork_id,**payload.model_dump())))
@router.post("/forks/{fork_id}/decisions")
async def post_fork_decision(fork_id:str,payload:MarketplaceForkDecisionInput,current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:decide_fork_update(db,actor=current_user,fork_id=fork_id,**payload.model_dump())))
@router.get("/recommendations/latest")
async def get_latest_recommendation(current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:get_marketplace_recommendation(db,actor=current_user)))
@router.get("/recommendations/{run_id}")
async def get_recommendation(run_id:str,current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:get_marketplace_recommendation(db,actor=current_user,run_id=run_id)))
@router.post("/recommendations",status_code=201)
async def post_recommendation(payload:MarketplaceRecommendationInput,current_user:DBUser=Depends(get_current_user)):return await run_db_op(_op(lambda db:run_marketplace_recommendation(db,actor=current_user,**payload.model_dump())))
