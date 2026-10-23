"""Governed content review queue over canonical artifact versions."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from app.agent_audit import assert_public_audit_is_sanitized, build_public_agent_run
from app.audit_log import record_backend_audit
from app.authorization import active_course_role
from app.database import (
    DBArtifact, DBArtifactVersion, DBChapter, DBClaimCheck,
    DBContentReviewCase, DBContentReviewDecision, DBQualityCheck,
    DBSourceDocument, DBSourceRef, DBUser,
)
from app.identity import normalize_role


class ContentReviewError(ValueError):
    def __init__(self, code: str, message: str): super().__init__(message); self.code=code

def _fail(code:str,message:str)->None: raise ContentReviewError(code,message)
def _now()->datetime:return datetime.now(timezone.utc).replace(tzinfo=None)
def _hash(value:str)->str:return hashlib.sha256(value.encode("utf-8")).hexdigest()

def _artifact(db:Any,artifact_id:str)->DBArtifact:
    row=db.get(DBArtifact,artifact_id)
    if row is None:_fail("review_artifact_unknown","artifact does not exist")
    return row

def _version(db:Any,version_id:str)->DBArtifactVersion:
    row=db.get(DBArtifactVersion,version_id)
    if row is None:_fail("review_version_unknown","artifact version does not exist")
    return row

def _can_submit(db:Any,artifact:DBArtifact,actor:DBUser)->bool:
    role = normalize_role(actor.role)
    return role=="admin" or (role in {"student","teacher"} and artifact.owner_public_id==actor.public_id) or (role=="teacher" and artifact.course_id and active_course_role(db,course_id=artifact.course_id,user_public_id=actor.public_id)=="teacher")

def _can_review(db:Any,artifact:DBArtifact,actor:DBUser)->bool:
    role = normalize_role(actor.role)
    return role=="admin" or (role=="teacher" and artifact.course_id and active_course_role(db,course_id=artifact.course_id,user_public_id=actor.public_id)=="teacher")

def _source_payload(db: Any, source_ref_id: str) -> dict[str, Any]:
    source_ref = db.get(DBSourceRef, source_ref_id)
    if source_ref is None:
        return {
            "id": source_ref_id,
            "available": False,
            "location_label": "来源记录当前不可用",
        }
    document = db.get(DBSourceDocument, source_ref.source_document_id)
    chapter = db.get(DBChapter, source_ref.chapter_id) if source_ref.chapter_id else None
    return {
        "id": source_ref.id,
        "available": document is not None,
        "document_id": source_ref.source_document_id,
        "document_title": document.title if document else "来源文档不可用",
        "filename": document.filename if document else "",
        "chapter_title": chapter.title if chapter else "",
        "page_number": source_ref.page_number,
        "location_label": source_ref.location_label,
        "quote": (source_ref.quote or "")[:500],
    }


def _evidence(db: Any, version_id: str) -> dict[str, Any]:
    quality = db.query(DBQualityCheck).filter_by(
        artifact_version_id=version_id,
    ).order_by(DBQualityCheck.created_at).all()
    claims = db.query(DBClaimCheck).filter_by(
        artifact_version_id=version_id,
    ).order_by(DBClaimCheck.created_at).all()
    source_ref_ids: list[str] = []
    for check in quality:
        source_ref_ids.extend(str(item) for item in (check.source_ref_ids or []) if item)
    source_ref_ids.extend(str(check.source_ref_id) for check in claims if check.source_ref_id)
    unique_source_ref_ids = list(dict.fromkeys(source_ref_ids))
    return {
        "quality_checks": [
            {
                "id": check.id,
                "type": check.check_type,
                "status": check.status,
                "score": check.score,
                "checker_version": check.checker_version,
                "source_ref_ids": [str(item) for item in (check.source_ref_ids or []) if item],
            }
            for check in quality
        ],
        "claim_checks": [
            {
                "id": check.id,
                "claim": check.atomic_claim[:500],
                "support_status": check.support_status,
                "verdict": check.verdict,
                "source_ref_id": check.source_ref_id,
            }
            for check in claims
        ],
        "sources": [_source_payload(db, source_ref_id) for source_ref_id in unique_source_ref_ids],
        "summary": {
            "quality_total": len(quality),
            "quality_passed": sum(
                1 for check in quality if check.status in {"passed", "pass", "completed"}
            ),
            "claims_total": len(claims),
            "claims_supported": sum(
                1 for check in claims if check.support_status in {"supported", "verified"}
            ),
        },
    }


def _review_agent_audit(
    *,
    case: DBContentReviewCase,
    version: DBArtifactVersion,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    summary = evidence["summary"]
    source_ids = [source["id"] for source in evidence.get("sources", [])]
    input_refs = source_ids or [f"version:{version.id}"]
    unsupported = max(0, summary["claims_total"] - summary["claims_supported"])
    if not summary["claims_total"]:
        disagreement = "当前版本尚无声明校验记录。"
    elif unsupported:
        disagreement = f"有 {unsupported} 条声明尚未获得来源支持。"
    else:
        disagreement = "已记录的声明均获得来源支持。"
    revision = {
        "changes_requested": "审核者已要求创建新的不可变版本后重新提交。",
        "pending": "等待审核者根据来源和校验结果决定是否返工。",
    }.get(case.status, "当前版本没有待处理的返工要求。")
    decision = {
        "pending": "等待审核决定。",
        "changes_requested": "当前版本已退回返工。",
        "approved": "当前版本已批准，等待发布。",
        "published": "当前版本已发布。",
        "withdrawn": "当前版本已下架，历史记录继续保留。",
    }[case.status]
    validation_status = "completed" if (
        summary["quality_total"] or summary["claims_total"]
    ) else "pending"
    items = [
        build_public_agent_run(
            run_id=f"review:{case.id}:analysis",
            role="analysis",
            input_refs=input_refs,
            candidate_summary=(
                f"已读取提交版本 v{version.version_number}、"
                f"{len(source_ids)} 条可定位来源和冻结校验快照。"
            ),
            validation="版本标识、内容摘要和来源引用已经冻结。",
            decision_summary="进入质量与声明交叉校验。",
            status="completed",
        ).model_dump(mode="json", by_alias=True),
        build_public_agent_run(
            run_id=f"review:{case.id}:validation",
            role="validation",
            input_refs=input_refs,
            candidate_summary=(
                f"质量检查通过 {summary['quality_passed']}/{summary['quality_total']}；"
                f"声明支持 {summary['claims_supported']}/{summary['claims_total']}。"
            ),
            disagreement=disagreement,
            validation="只采用已保存的质量检查、声明检查和来源定位结果。",
            revision=revision,
            decision_summary="校验结果已提交给审核者。",
            status=validation_status,
        ).model_dump(mode="json", by_alias=True),
        build_public_agent_run(
            run_id=f"review:{case.id}:decision",
            role="decision",
            input_refs=input_refs,
            candidate_summary="审核决定由有权限的人员确认并写入不可变责任记录。",
            validation="页面不会根据模型建议自动发布或下架内容。",
            revision=revision,
            decision_summary=decision,
            status="pending" if case.status == "pending" else "completed",
        ).model_dump(mode="json", by_alias=True),
    ]
    payload = {
        "status": "pending" if validation_status == "pending" else "completed",
        "items": items,
    }
    assert_public_audit_is_sanitized(payload)
    return payload

def _decision(db:Any,*,case:DBContentReviewCase,artifact:DBArtifact,actor:DBUser,action:str,to_status:str,reason:str)->None:
    snapshot=_evidence(db,case.submitted_version_id);before=case.status
    db.add(DBContentReviewDecision(review_case_id=case.id,action=action,from_status=before,to_status=to_status,actor_public_id=actor.public_id,actor_role=normalize_role(actor.role),reason=reason.strip(),reason_sha256=_hash(reason.strip()),evidence_snapshot=snapshot))
    case.status=to_status;case.lock_version+=1
    if to_status in {"approved","published","withdrawn"}:case.resolved_at=_now()
    record_backend_audit(
        db,
        actor_public_id=actor.public_id,
        action=f"content_review.{action}",
        object_type="content_review_case",
        object_id=case.id,
        before_summary={"status": before},
        after_summary={"status": to_status},
        context={
            "artifactId": artifact.id,
            "versionId": case.submitted_version_id,
            "reasonSha256": _hash(reason.strip()),
        },
    )

def submit_review(db:Any,*,actor:DBUser,artifact_id:str,version_id:str,submission_note:str)->DBContentReviewCase:
    artifact=_artifact(db,artifact_id);version=_version(db,version_id)
    if version.artifact_id!=artifact.id:_fail("review_version_scope_invalid","version does not belong to artifact")
    if not _can_submit(db,artifact,actor):_fail("review_forbidden","artifact submission is not allowed")
    if artifact.current_version_id!=version.id:_fail("review_version_stale","only current immutable version can be submitted")
    existing=db.query(DBContentReviewCase).filter_by(artifact_id=artifact.id,submitted_version_id=version.id).first()
    if existing:
        if existing.status == "pending": return existing
        _fail("review_version_stale","a resolved or returned version cannot be submitted again; create a new immutable version")
    if artifact.status not in {"draft","approved"}:_fail("review_transition_invalid","artifact is not submittable")
    case=DBContentReviewCase(artifact_id=artifact.id,submitted_version_id=version.id,course_id=artifact.course_id,submitted_by_public_id=actor.public_id,evidence_snapshot=_evidence(db,version.id),submission_note=submission_note.strip())
    db.add(case);db.flush();artifact.status="reviewing";artifact.lock_version+=1
    _decision(db,case=case,artifact=artifact,actor=actor,action="submit",to_status="pending",reason=submission_note or "submit for review")
    return case

def transition(db:Any,*,actor:DBUser,case_id:str,action:str,reason:str,expected_version:int)->DBContentReviewCase:
    case=db.get(DBContentReviewCase,case_id)
    if case is None:_fail("review_case_unknown","review case does not exist")
    artifact=_artifact(db,case.artifact_id)
    if not _can_review(db,artifact,actor):_fail("review_forbidden","review action requires a course reviewer")
    if case.lock_version!=expected_version:_fail("review_version_conflict","review case has changed")
    rules={"request_changes":({"pending"},"changes_requested","draft"),"approve":({"pending"},"approved","approved"),"publish":({"approved"},"published","published"),"withdraw":({"published"},"withdrawn","withdrawn")}
    allowed,to_status,artifact_status=rules[action]
    if case.status not in allowed:_fail("review_transition_invalid",f"cannot {action} from {case.status}")
    _decision(db,case=case,artifact=artifact,actor=actor,action=action,to_status=to_status,reason=reason)
    artifact.status=artifact_status;artifact.lock_version+=1
    if artifact_status in {"withdrawn"}:artifact.archived_at=_now()
    return case

def case_payload(db:Any,case:DBContentReviewCase)->dict[str,Any]:
    artifact=_artifact(db,case.artifact_id);version=_version(db,case.submitted_version_id)
    decisions=db.query(DBContentReviewDecision).filter_by(review_case_id=case.id).order_by(DBContentReviewDecision.created_at).all()
    evidence = case.evidence_snapshot
    return {"schema_version":"next.content-review-case.v1","id":case.id,"status":case.status,"lock_version":case.lock_version,"course_id":case.course_id,"submitted_at":case.submitted_at.isoformat(),"submission_note":case.submission_note,"artifact":{"id":artifact.id,"title":artifact.title,"type":artifact.artifact_type,"status":artifact.status,"owner_public_id":artifact.owner_public_id},"version":{"id":version.id,"number":version.version_number,"content_hash":version.content_hash,"format":version.content_format,"preview":version.content[:2000]},"evidence":evidence,"agent_audit":_review_agent_audit(case=case,version=version,evidence=evidence),"decisions":[{"id":d.id,"action":d.action,"from_status":d.from_status,"to_status":d.to_status,"actor_public_id":d.actor_public_id,"actor_role":d.actor_role,"reason":d.reason,"reason_sha256":d.reason_sha256,"created_at":d.created_at.isoformat()} for d in decisions]}

def queue(db:Any,*,actor:DBUser,status:str|None=None)->list[dict[str,Any]]:
    query=db.query(DBContentReviewCase)
    if status:query=query.filter_by(status=status)
    rows=query.order_by(DBContentReviewCase.submitted_at.desc()).all();visible=[]
    for case in rows:
        artifact=_artifact(db,case.artifact_id)
        if _can_review(db,artifact,actor) or artifact.owner_public_id==actor.public_id:visible.append(case_payload(db,case))
    return visible
