"""Explainable, privacy-gated enterprise training risk reports."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone
from typing import Any

from app.database import (
    DBCertification, DBEnterpriseRiskDecision, DBEnterpriseRiskReport,
    DBJobStandardImpactConfirmation, DBOrganizationMembership, DBRetrainingTask,
    DBTrainingAssignment, DBUser,
)
from app.m1_enterprise import organization_role


METRIC_VERSION = "enterprise-demo-risk-metrics-1.0.0"
MINIMUM_SAMPLE = 3
METRICS = (
    {"key":"training_completion_rate","name":"培训完成率","unit":"ratio","formula":"截至窗口结束，completed 培训分配数 / 全部有效成员培训分配数","sources":["training_assignments","organization_memberships"],"threshold":0.70,"direction":"gte","threshold_basis":"比赛演示阈值：低于 70% 提示主管检查培训阻塞，不来自真实企业绩效制度。"},
    {"key":"active_certification_coverage","name":"有效认证覆盖率","unit":"ratio","formula":"窗口结束时至少有 1 项 active 认证的活动学习者数 / 活动学习者总数","sources":["certifications","organization_memberships"],"threshold":0.60,"direction":"gte","threshold_basis":"比赛演示阈值：低于 60% 提示检查认证路径，不是上岗或淘汰标准。"},
    {"key":"overdue_retraining_rate","name":"逾期复训率","unit":"ratio","formula":"窗口结束时 due_at 已过且未 completed/cancelled 的复训任务数 / 全部到期复训任务数","sources":["retraining_tasks"],"threshold":0.20,"direction":"lte","threshold_basis":"比赛演示阈值：高于 20% 提示跟进复训，不来自真实企业 SLA。"},
    {"key":"standard_upgrade_coverage","name":"标准升级复训覆盖率","unit":"ratio","formula":"岗位升级确认后已获得 retraining 分配的受影响活动学习者数 / 受影响活动学习者数","sources":["job_standard_impact_confirmations","training_assignments"],"threshold":0.90,"direction":"gte","threshold_basis":"比赛演示阈值：低于 90% 提示检查升级调度遗漏，不代表真实岗位合规认定。"},
)


class EnterpriseRiskError(ValueError):
    def __init__(self, code: str, message: str): super().__init__(message); self.code = code


def _fail(code: str, message: str) -> None: raise EnterpriseRiskError(code, message)


def _role(db: Any, actor: DBUser, organization_id: str) -> str:
    role = organization_role(db, organization_id=organization_id, user_public_id=actor.public_id)
    if role not in {"manager", "admin"}: _fail("enterprise_risk_forbidden", "only organization managers or admins may view enterprise risk reports")
    return role


def _iso(value: datetime | None) -> str | None: return value.isoformat(timespec="seconds") + ("Z" if value and value.tzinfo is None else "") if value else None
def _utc_naive(value: datetime) -> datetime: return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
def _hash(value: Any) -> str: return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
def _alias(salt: bytes, public_id: str) -> str: return "EMP-" + hmac.new(salt, public_id.encode(), hashlib.sha256).hexdigest()[:10].upper()


def _metric(definition: dict[str, Any], numerator: int, denominator: int, *, suppressed: bool) -> dict[str, Any]:
    value = None if suppressed or denominator == 0 else round(numerator / denominator, 4)
    if suppressed: state = "suppressed"
    elif value is None: state = "unavailable"
    elif definition["direction"] == "gte": state = "attention" if value < definition["threshold"] else "within_demo_threshold"
    else: state = "attention" if value > definition["threshold"] else "within_demo_threshold"
    return {**definition, "value": value, "numerator": None if suppressed else numerator, "denominator": None if suppressed else denominator, "sample_state":"suppressed" if suppressed else "sufficient", "minimum_sample":MINIMUM_SAMPLE, "state":state}


def build_snapshot(db: Any, *, actor: DBUser, organization_id: str, period_start: datetime, period_end: datetime) -> dict[str, Any]:
    _role(db, actor, organization_id)
    period_start, period_end = _utc_naive(period_start), _utc_naive(period_end)
    if period_end <= period_start: _fail("enterprise_risk_period_invalid", "period end must be after period start")
    members = db.query(DBOrganizationMembership).filter_by(organization_id=organization_id, role="learner", status="active").order_by(DBOrganizationMembership.user_public_id).all()
    owners = [row.user_public_id for row in members]; suppressed = len(owners) < MINIMUM_SAMPLE
    assignments = db.query(DBTrainingAssignment).filter(DBTrainingAssignment.organization_id==organization_id, DBTrainingAssignment.learner_public_id.in_(owners or [""]), DBTrainingAssignment.assigned_at < period_end).all()
    certifications = db.query(DBCertification).filter(DBCertification.organization_id==organization_id, DBCertification.learner_public_id.in_(owners or [""]), DBCertification.issued_at < period_end).all()
    tasks = db.query(DBRetrainingTask).filter(DBRetrainingTask.organization_id==organization_id, DBRetrainingTask.learner_public_id.in_(owners or [""]), DBRetrainingTask.created_at < period_end).all()
    confirmations = db.query(DBJobStandardImpactConfirmation).filter(DBJobStandardImpactConfirmation.organization_id==organization_id, DBJobStandardImpactConfirmation.created_at < period_end).all()
    completed_assignments = sum(row.status == "completed" for row in assignments)
    active_cert_owners = {row.learner_public_id for row in certifications if row.status == "active" and (row.expires_at is None or row.expires_at >= period_end)}
    due_tasks = [row for row in tasks if row.due_at and row.due_at < period_end]
    overdue_tasks = [row for row in due_tasks if row.status not in {"completed","cancelled"}]
    upgrade_affected = set(); upgrade_assigned = set()
    for confirmation in confirmations:
        scheduling = confirmation.scheduling_snapshot or {}
        for assignment_id in scheduling.get("assignment_ids_created", []):
            row = next((item for item in assignments if item.id == assignment_id), None)
            if row: upgrade_assigned.add(row.learner_public_id); upgrade_affected.add(row.learner_public_id)
        upgrade_affected.update(scheduling.get("skipped_inactive_learner_public_ids", []))
    metric_rows = [
        _metric(METRICS[0], completed_assignments, len(assignments), suppressed=suppressed),
        _metric(METRICS[1], len(active_cert_owners), len(owners), suppressed=suppressed),
        _metric(METRICS[2], len(overdue_tasks), len(due_tasks), suppressed=suppressed),
        _metric(METRICS[3], len(upgrade_assigned), len(upgrade_affected), suppressed=suppressed),
    ]
    learner_rows = []; risks = []
    if not suppressed:
        salt = secrets.token_bytes(32)
        for owner in owners:
            own_assignments = [row for row in assignments if row.learner_public_id == owner]
            own_tasks = [row for row in overdue_tasks if row.learner_public_id == owner]
            alias = _alias(salt, owner); evidence = []
            if own_assignments and not any(row.status == "completed" for row in own_assignments): evidence.append("no_completed_training_assignment")
            if owner not in active_cert_owners: evidence.append("no_active_certification")
            if own_tasks: evidence.append(f"overdue_retraining_tasks:{len(own_tasks)}")
            level = "high" if len(evidence) >= 3 else "attention" if evidence else "normal"
            learner_rows.append({"learner_alias":alias,"training_assignments":len(own_assignments),"completed_assignments":sum(row.status=="completed" for row in own_assignments),"active_certifications":sum(row.learner_public_id==owner and row.status=="active" for row in certifications),"overdue_retraining_tasks":len(own_tasks),"risk_level":level})
            if evidence: risks.append({"learner_alias":alias,"risk_level":level,"evidence":evidence,"recommendation":"由主管核对培训与认证证据并联系学习者；不得据此自动处分、调岗、晋升或淘汰。"})
    return {"schema_version":"next.enterprise-risk-report.v1","metric_version":METRIC_VERSION,"truthfulness":{"data_kind":"competition_demo_metrics","real_enterprise_data":False,"thresholds_are_demonstration_only":True,"automatic_personnel_decisions":False},"privacy":{"minimum_sample":MINIMUM_SAMPLE,"population_size":len(owners),"sample_state":"suppressed" if suppressed else "sufficient","raw_identity_fields_included":False,"pseudonyms_linkable_across_reports":False},"period":{"start":_iso(period_start),"end":_iso(period_end),"end_exclusive":True},"metrics":metric_rows,"learners":learner_rows,"risks":risks,"source_counts":{"organization_memberships":len(members),"training_assignments":len(assignments),"certifications":len(certifications),"retraining_tasks":len(tasks),"job_standard_confirmations":len(confirmations)}}


def create_report(db: Any, *, actor: DBUser, organization_id: str, period_start: datetime, period_end: datetime) -> tuple[DBEnterpriseRiskReport,bool]:
    _role(db, actor, organization_id)
    period_start, period_end = _utc_naive(period_start), _utc_naive(period_end)
    existing=db.query(DBEnterpriseRiskReport).filter_by(organization_id=organization_id,period_start=period_start,period_end=period_end,metric_version=METRIC_VERSION).first()
    if existing:return existing,False
    snapshot=build_snapshot(db,actor=actor,organization_id=organization_id,period_start=period_start,period_end=period_end)
    row=DBEnterpriseRiskReport(organization_id=organization_id,period_start=period_start,period_end=period_end,metric_version=METRIC_VERSION,minimum_sample=MINIMUM_SAMPLE,report_data=snapshot,content_hash=_hash(snapshot),created_by_public_id=actor.public_id);db.add(row);db.flush();return row,True


def _decision_payload(row): return {"id":row.id,"actor_public_id":row.actor_public_id,"actor_role":row.actor_role,"action":row.action,"from_status":row.from_status,"to_status":row.to_status,"reason":row.reason,"reason_hash":row.reason_hash,"created_at":_iso(row.created_at)}
def payload(db:Any,row:DBEnterpriseRiskReport):
    decisions=db.query(DBEnterpriseRiskDecision).filter_by(report_id=row.id).order_by(DBEnterpriseRiskDecision.created_at).all()
    return {"id":row.id,"organization_id":row.organization_id,"status":row.status,"lock_version":row.lock_version,"content_hash":row.content_hash,"created_at":_iso(row.created_at),"closed_at":_iso(row.closed_at),**dict(row.report_data or {}),"decisions":[_decision_payload(item) for item in decisions]}


def workspace(db:Any,*,actor:DBUser,organization_id:str):
    role=_role(db,actor,organization_id);rows=db.query(DBEnterpriseRiskReport).filter_by(organization_id=organization_id).order_by(DBEnterpriseRiskReport.created_at.desc()).all()
    return {"schema_version":"next.enterprise-risk-workspace.v1","organization_id":organization_id,"role":role,"metric_dictionary":list(METRICS),"truth_label":"可解释企业演示指标 · 非真实生产数据","disclaimer":"风险仅供演示角色主管人工核对，不自动触发处分、调岗、晋升或淘汰。","reports":[payload(db,row) for row in rows]}


def decide(db:Any,*,actor:DBUser,report_id:str,action:str,reason:str,expected_version:int):
    row=db.query(DBEnterpriseRiskReport).filter_by(id=report_id).first()
    if not row:_fail("enterprise_risk_report_unknown","enterprise risk report does not exist")
    role=_role(db,actor,row.organization_id)
    if row.lock_version!=expected_version:_fail("enterprise_risk_stale","report version is stale")
    transitions={"acknowledge":({"open"},"acknowledged"),"close":({"open","acknowledged"},"closed")}
    allowed,target=transitions[action]
    if row.status not in allowed:_fail("enterprise_risk_transition_conflict","risk report transition is not allowed")
    reason=reason.strip()
    if len(reason)<4:_fail("enterprise_risk_reason_invalid","decision reason is too short")
    old=row.status;row.status=target;row.lock_version+=1;now=datetime.utcnow();row.closed_at=now if target=="closed" else None
    decision=DBEnterpriseRiskDecision(report_id=row.id,organization_id=row.organization_id,actor_public_id=actor.public_id,actor_role=role,action=action,from_status=old,to_status=target,reason=reason,reason_hash=hashlib.sha256(reason.encode()).hexdigest(),evidence_snapshot={"content_hash":row.content_hash,"risk_count":len((row.report_data or {}).get("risks",[])),"automatic_source_mutation":False});db.add(decision);db.flush();return row
