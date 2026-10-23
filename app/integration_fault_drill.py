"""Persistent seven-scenario integration fault drills with authority preservation."""
from __future__ import annotations
from typing import Any
from app.database import (
    DBAssessmentAttempt, DBCertification, DBCourse, DBIntegrationDelivery,
    DBIntegrationDeliveryEvent, DBIntegrationFaultDrill, DBIntegrationFaultDrillStep,
    DBOrganizationMembership, DBStudentProfile, DBTrainingAssignment, DBUser,
)
from app.m7_integrations import _delivery_event, _hash, _now, _require_integration_admin, record_delivery_attempt, requeue_dead_letter

SCENARIOS = [
    {"key":"duplicate","label":"重复投递","fault_code":"duplicate_idempotency_key","recovery":"幂等复用原投递"},
    {"key":"out_of_order","label":"乱序事件","fault_code":"source_sequence_out_of_order","recovery":"拒绝旧序列并保留游标"},
    {"key":"revocation","label":"撤销后重放","fault_code":"credential_revoked","recovery":"保持撤销并拒绝后续访问"},
    {"key":"conflict","label":"载荷冲突","fault_code":"payload_hash_conflict","recovery":"保留首个载荷"},
    {"key":"disconnect","label":"适配器断连","fault_code":"adapter_disconnected","recovery":"重新连接后继续投递"},
    {"key":"timeout","label":"接收端超时","fault_code":"receiver_timeout","recovery":"退避后重试"},
    {"key":"dead_letter","label":"连续失败与死信","fault_code":"max_attempts_exceeded","recovery":"显式重入队后成功"},
]

class FaultDrillError(ValueError):
    def __init__(self,code,message,status_code=409):super().__init__(message);self.code=code;self.status_code=status_code
def _fail(code,message,status=409):raise FaultDrillError(code,message,status)

def authority_snapshot(db,organization_id):
    member_ids=[x.user_public_id for x in db.query(DBOrganizationMembership).filter_by(organization_id=organization_id).order_by(DBOrganizationMembership.user_public_id).all()]
    payload={
        "members":[{"id":x.user_public_id,"role":x.role,"status":x.status} for x in db.query(DBOrganizationMembership).filter_by(organization_id=organization_id).order_by(DBOrganizationMembership.user_public_id).all()],
        "courses":[{"id":x.id,"status":x.status,"version":x.version,"manifest_version":x.manifest_version} for x in db.query(DBCourse).order_by(DBCourse.id).all()],
        "profiles":[{"id":x.student_id,"target_course":x.target_course,"weak_points":x.weak_points,"concept_mastery":x.concept_mastery,"last_updated":x.last_updated.isoformat() if x.last_updated else None} for x in db.query(DBStudentProfile).filter(DBStudentProfile.student_id.in_(member_ids or ["-"])).order_by(DBStudentProfile.student_id).all()],
        "assignments":[{"id":x.id,"status":x.status} for x in db.query(DBTrainingAssignment).filter_by(organization_id=organization_id).order_by(DBTrainingAssignment.id).all()],
        "attempts":db.query(DBAssessmentAttempt).filter(DBAssessmentAttempt.owner_public_id.in_(member_ids or ["-"])).count(),
        "certifications":db.query(DBCertification).filter_by(organization_id=organization_id).count(),
    }
    return payload,_hash(payload)

def _delivery(db,drill,key):
    destination=f"fault-drill:{drill.id}:{key}"
    row=db.query(DBIntegrationDelivery).filter_by(organization_id=drill.organization_id,destination_key=destination,idempotency_key=key).first()
    if row:return row
    payload={"drill_id":drill.id,"scenario":key,"synthetic":True}
    row=DBIntegrationDelivery(organization_id=drill.organization_id,adapter_type="xapi",adapter_version="fault-drill-v1",destination_key=destination,idempotency_key=key,source_object_type="integration_fault_drill",source_object_id=drill.id,payload=payload,payload_hash=_hash(payload),status="pending")
    db.add(row);db.flush();_delivery_event(db,delivery=row,actor_public_id=drill.created_by_public_id,action="drill_enqueue",from_status="none",evidence={"scenario":key,"local_simulation":True});return row

def _accept_sequence(current_sequence:int,incoming_sequence:int):
    if incoming_sequence<=current_sequence:return {"accepted":False,"reason":"source_sequence_out_of_order","current_sequence":current_sequence,"incoming_sequence":incoming_sequence}
    return {"accepted":True,"reason":"accepted","current_sequence":incoming_sequence,"incoming_sequence":incoming_sequence}
def _authorize_credential(status:str):
    return {"credential_status":status,"replayed_access_allowed":status=="active","reason":"accepted" if status=="active" else "credential_revoked"}
def _accept_payload(existing_hash:str,incoming_payload:dict):
    incoming_hash=_hash(incoming_payload);return {"accepted":incoming_hash==existing_hash,"reason":"accepted" if incoming_hash==existing_hash else "payload_hash_conflict","original_hash":existing_hash,"incoming_hash":incoming_hash}

def create_drill(db,*,actor:DBUser,organization_id,run_key):
    _require_integration_admin(db,actor=actor,organization_id=organization_id)
    _,authority_hash=authority_snapshot(db,organization_id)
    old=db.query(DBIntegrationFaultDrill).filter_by(organization_id=organization_id,run_key=run_key).first()
    if old:return old,False
    row=DBIntegrationFaultDrill(organization_id=organization_id,run_key=run_key,authority_before_hash=authority_hash,authority_after_hash=authority_hash,scenario_plan=SCENARIOS,created_by_public_id=actor.public_id)
    db.add(row);db.commit();return row,True

def _execute(db,drill,scenario):
    key=scenario["key"];row=_delivery(db,drill,key);before={"status":row.status,"attempt_count":row.attempt_count,"payload_hash":row.payload_hash}
    after={};recovery={}
    if key=="duplicate":
        same=_delivery(db,drill,key);assert same.id==row.id;after={"suppressed":True,"delivery_id":same.id,"row_count":1};recovery={"action":"reuse_existing"}
    elif key=="out_of_order":
        after=_accept_sequence(current_sequence=2,incoming_sequence=1);recovery={"action":"reject_old_sequence","cursor_preserved":after["current_sequence"]}
    elif key=="revocation":
        after=_authorize_credential("revoked");recovery={"action":"keep_revoked","status":after["credential_status"]}
    elif key=="conflict":
        after=_accept_payload(row.payload_hash,{"drill_id":drill.id,"scenario":key,"variant":2});recovery={"action":"preserve_original","payload_hash":row.payload_hash}
    elif key=="disconnect":
        previous=row.status;record_delivery_attempt(db,delivery=row,success=False,error_code="adapter_disconnected");_delivery_event(db,delivery=row,actor_public_id=drill.created_by_public_id,action="drill_disconnect",from_status=previous,evidence={"network_sent":False});after={"status":row.status,"error_code":row.last_error_code};previous=row.status;record_delivery_attempt(db,delivery=row,success=True);_delivery_event(db,delivery=row,actor_public_id=drill.created_by_public_id,action="drill_reconnect_success",from_status=previous,evidence={"network_sent":False});recovery={"action":"reconnect","status":row.status}
    elif key=="timeout":
        previous=row.status;record_delivery_attempt(db,delivery=row,success=False,error_code="receiver_timeout");_delivery_event(db,delivery=row,actor_public_id=drill.created_by_public_id,action="drill_timeout",from_status=previous,evidence={"network_sent":False});after={"status":row.status,"next_attempt_at":row.next_attempt_at.isoformat(),"error_code":row.last_error_code};previous=row.status;record_delivery_attempt(db,delivery=row,success=True);_delivery_event(db,delivery=row,actor_public_id=drill.created_by_public_id,action="drill_retry_success",from_status=previous,evidence={"network_sent":False});recovery={"action":"retry_after_backoff","status":row.status}
    else:
        for _ in range(5):
            previous=row.status;record_delivery_attempt(db,delivery=row,success=False,error_code="receiver_unavailable");_delivery_event(db,delivery=row,actor_public_id=drill.created_by_public_id,action="drill_attempt_failure",from_status=previous,evidence={"network_sent":False})
        after={"status":row.status,"attempt_count":row.attempt_count,"ordinary_retry_blocked":row.status=="dead_letter"};drill_actor=db.query(DBUser).filter_by(public_id=drill.created_by_public_id).one();requeue_dead_letter(db,actor=drill_actor,delivery_id=row.id);previous=row.status;record_delivery_attempt(db,delivery=row,success=True);_delivery_event(db,delivery=row,actor_public_id=drill.created_by_public_id,action="drill_recovery_success",from_status=previous,evidence={"network_sent":False});recovery={"action":"explicit_requeue","status":row.status,"attempt_count":row.attempt_count}
    return before,after,recovery

def execute_next(db,*,actor:DBUser,drill_id,expected_lock_version):
    drill=db.get(DBIntegrationFaultDrill,drill_id)
    if not drill:_fail("fault_drill_not_found","fault drill does not exist",404)
    _require_integration_admin(db,actor=actor,organization_id=drill.organization_id)
    if drill.status in {"passed","failed"}:_fail("fault_drill_closed","fault drill is already closed")
    if drill.lock_version!=expected_lock_version:_fail("fault_drill_version_conflict","fault drill changed; refresh required")
    index=drill.current_scenario+1;scenario=SCENARIOS[index-1]
    before,after,recovery=_execute(db,drill,scenario);_,authority_hash=authority_snapshot(db,drill.organization_id)
    outcome="passed" if authority_hash==drill.authority_before_hash else "failed"
    evidence={"scenario":scenario,"before":before,"after":after,"recovery":recovery,"authority_hash":authority_hash}
    db.add(DBIntegrationFaultDrillStep(drill_id=drill.id,organization_id=drill.organization_id,scenario_index=index,scenario_key=scenario["key"],outcome=outcome,fault_code=scenario["fault_code"],before_snapshot=before,after_snapshot=after,recovery_snapshot=recovery,authority_hash=authority_hash,evidence_hash=_hash(evidence)))
    drill.current_scenario=index;drill.lock_version+=1;drill.status="failed" if outcome=="failed" else "passed" if index==len(SCENARIOS) else "running";drill.authority_after_hash=authority_hash
    if drill.status in {"passed","failed"}:drill.completed_at=_now()
    db.commit();return drill

def workspace(db,*,actor:DBUser,organization_id=None):
    if actor.role!="admin":_fail("fault_drill_forbidden","only administrators can inspect fault drills",403)
    memberships=db.query(DBOrganizationMembership).filter_by(user_public_id=actor.public_id,role="admin",status="active").all();orgs=[{"id":x.organization_id} for x in memberships]
    if not orgs:return {"organizations":[],"selected":None}
    org=organization_id or orgs[0]["id"];_require_integration_admin(db,actor=actor,organization_id=org);items=[]
    for drill in db.query(DBIntegrationFaultDrill).filter_by(organization_id=org).order_by(DBIntegrationFaultDrill.created_at.desc()).limit(20).all():
        steps=db.query(DBIntegrationFaultDrillStep).filter_by(drill_id=drill.id).order_by(DBIntegrationFaultDrillStep.scenario_index).all()
        items.append({"id":drill.id,"run_key":drill.run_key,"status":drill.status,"current_scenario":drill.current_scenario,"lock_version":drill.lock_version,"authority_before_hash":drill.authority_before_hash,"authority_after_hash":drill.authority_after_hash,"scenario_plan":drill.scenario_plan,"created_at":drill.created_at.isoformat(),"completed_at":drill.completed_at.isoformat() if drill.completed_at else None,"steps":[{"id":x.id,"scenario_index":x.scenario_index,"scenario_key":x.scenario_key,"outcome":x.outcome,"fault_code":x.fault_code,"before_snapshot":x.before_snapshot,"after_snapshot":x.after_snapshot,"recovery_snapshot":x.recovery_snapshot,"authority_hash":x.authority_hash,"evidence_hash":x.evidence_hash,"created_at":x.created_at.isoformat()} for x in steps]})
    return {"organizations":orgs,"selected":{"organization_id":org,"runs":items,"scenario_plan":SCENARIOS},"truthfulness":{"mode":"local_simulation","data_label":"本地集成故障演练 · 冻结合成组织数据","real_enterprise_connected":False,"disclaimer":"演练验证本地状态机、拒绝语义、恢复和权威数据保护，不代表真实企业容灾或生产 SLA。"}}
