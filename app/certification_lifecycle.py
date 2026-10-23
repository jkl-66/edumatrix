"""Governed certification revocation, expiry, retraining and local notices."""
from __future__ import annotations
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any
from app.database import DBCertification,DBCertificationLifecycleEvent,DBJobLevel,DBLocalNotification,DBOrganizationMembership,DBRetrainingTask,DBUser
from app.m1_enterprise import organization_role,require_organization_access

class CertificationLifecycleError(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code
def _now(value=None):
    current=value or datetime.now(timezone.utc)
    return current if current.tzinfo is None else current.astimezone(timezone.utc).replace(tzinfo=None)
def _fail(code,message):raise CertificationLifecycleError(code,message)
def _cert(db,certification_id):
    row=db.query(DBCertification).filter_by(id=certification_id).first()
    if not row:_fail('certification_unknown','certification does not exist')
    return row
def _notice(db,*,owner,org,kind,key,title,body,obj_type,obj_id):
    row=db.query(DBLocalNotification).filter_by(owner_public_id=owner,idempotency_key=key).first()
    if row:return row,False
    row=DBLocalNotification(owner_public_id=owner,organization_id=org,notification_type=kind,idempotency_key=key,title=title,body=body,object_type=obj_type,object_id=obj_id);db.add(row);db.flush();return row,True
def _event(db,*,cert,actor,role,action,old,new,reason,now):
    row=DBCertificationLifecycleEvent(certification_id=cert.id,organization_id=cert.organization_id,actor_public_id=actor,actor_role=role,action=action,from_status=old,to_status=new,reason=reason,reason_hash=hashlib.sha256(reason.encode()).hexdigest(),evidence_snapshot={'standard_snapshot':cert.standard_snapshot,'evidence_ids':list(cert.evidence_ids or []),'expires_at':cert.expires_at.isoformat() if cert.expires_at else None},created_at=now);db.add(row);db.flush();return row
def _retraining(db,cert,trigger,now):
    key=f'{trigger}:{cert.expires_at.date().isoformat() if cert.expires_at else now.date().isoformat()}'
    existing=db.query(DBRetrainingTask).filter_by(certification_id=cert.id,trigger_key=key).first()
    if existing:return existing,False
    rule=dict(cert.retraining_rule or {});days=max(1,min(int(rule.get('completion_days',30)),365));level=db.query(DBJobLevel).filter_by(id=cert.job_level_id).first()
    row=DBRetrainingTask(certification_id=cert.id,organization_id=cert.organization_id,learner_public_id=cert.learner_public_id,trigger_type=trigger,trigger_key=key,title=f"{level.title if level else '岗位能力'}复训",due_at=now+timedelta(days=days),rule_snapshot=rule);db.add(row);db.flush();return row,True
def revoke(db,*,actor:DBUser,certification_id,reason,expected_version,now=None):
    cert=_cert(db,certification_id);role=require_organization_access(db,organization_id=cert.organization_id,user_public_id=actor.public_id,action='approve')
    if cert.lock_version!=expected_version:_fail('certification_stale','certification version is stale')
    if cert.status!='active':_fail('certification_transition_conflict','only active certification can be revoked')
    current=_now(now);old=cert.status;cert.status='revoked';cert.revoked_at=current;cert.lock_version+=1
    event=_event(db,cert=cert,actor=actor.public_id,role=role,action='revoke',old=old,new='revoked',reason=reason,now=current);task,_=_retraining(db,cert,'revoked',current);_notice(db,owner=cert.learner_public_id,org=cert.organization_id,kind='certification_revoked',key=f'cert:{cert.id}:revoked',title='认证已撤销',body=f'认证已撤销，原因：{reason}。已生成复训任务。',obj_type='certification',obj_id=cert.id);return cert,event,task
def scan(db,*,actor:DBUser,organization_id,upcoming_days=30,now=None):
    role=require_organization_access(db,organization_id=organization_id,user_public_id=actor.public_id,action='approve');current=_now(now);expired=upcoming=tasks=notices=0
    rows=db.query(DBCertification).filter_by(organization_id=organization_id,status='active').all()
    for cert in rows:
        if not cert.expires_at:continue
        if cert.expires_at<=current:
            cert.status='expired';cert.lock_version+=1;_event(db,cert=cert,actor=actor.public_id,role=role,action='expire',old='active',new='expired',reason='到期扫描：证书有效期已结束',now=current);_,made=_retraining(db,cert,'expired',current);tasks+=made;_,made_notice=_notice(db,owner=cert.learner_public_id,org=cert.organization_id,kind='certification_expired',key=f'cert:{cert.id}:expired',title='认证已到期',body='认证已到期，复训任务已进入本地工作台。',obj_type='certification',obj_id=cert.id);notices+=made_notice;expired+=1
        elif cert.expires_at<=current+timedelta(days=upcoming_days):
            _,made=_notice(db,owner=cert.learner_public_id,org=cert.organization_id,kind='certification_expiring',key=f'cert:{cert.id}:expiring:{cert.expires_at.date()}',title='认证即将到期',body=f'认证将于 {cert.expires_at.date().isoformat()} 到期。',obj_type='certification',obj_id=cert.id);notices+=made;upcoming+=made
    return {'expired':expired,'upcoming_notified':upcoming,'retraining_created':tasks,'notifications_created':notices}
def workspace(db,*,actor:DBUser,organization_id):
    role=require_organization_access(db,organization_id=organization_id,user_public_id=actor.public_id,action='read');query=db.query(DBCertification).filter_by(organization_id=organization_id)
    if role=='learner':query=query.filter_by(learner_public_id=actor.public_id)
    certs=query.order_by(DBCertification.issued_at.desc()).all();ids=[c.id for c in certs]
    events=db.query(DBCertificationLifecycleEvent).filter(DBCertificationLifecycleEvent.certification_id.in_(ids)).order_by(DBCertificationLifecycleEvent.created_at.desc()).all() if ids else []
    tasks=db.query(DBRetrainingTask).filter_by(organization_id=organization_id)
    if role=='learner':tasks=tasks.filter_by(learner_public_id=actor.public_id)
    notices=db.query(DBLocalNotification).filter_by(owner_public_id=actor.public_id,organization_id=organization_id).order_by(DBLocalNotification.created_at.desc()).all()
    return {'schema_version':'next.certification-lifecycle.v1','organization_id':organization_id,'role':role,'demo_role_disclaimer':'演示角色签核，不代表外部专家认证。','certifications':[{'id':c.id,'learner_public_id':c.learner_public_id,'job_level_id':c.job_level_id,'status':c.status,'issued_at':c.issued_at.isoformat(),'expires_at':c.expires_at.isoformat() if c.expires_at else None,'revoked_at':c.revoked_at.isoformat() if c.revoked_at else None,'lock_version':c.lock_version,'issuer_public_id':c.issuer_public_id,'retraining_rule':c.retraining_rule or {}} for c in certs],'events':[{'id':e.id,'certification_id':e.certification_id,'actor_public_id':e.actor_public_id,'actor_role':e.actor_role,'action':e.action,'from_status':e.from_status,'to_status':e.to_status,'reason':e.reason,'reason_hash':e.reason_hash,'created_at':e.created_at.isoformat()} for e in events],'retraining_tasks':[{'id':t.id,'certification_id':t.certification_id,'learner_public_id':t.learner_public_id,'title':t.title,'trigger_type':t.trigger_type,'status':t.status,'due_at':t.due_at.isoformat() if t.due_at else None} for t in tasks.all()],'notifications':[{'id':n.id,'type':n.notification_type,'title':n.title,'body':n.body,'object_id':n.object_id,'read_at':n.read_at.isoformat() if n.read_at else None,'created_at':n.created_at.isoformat()} for n in notices]}
def mark_read(db,*,actor:DBUser,notice_id):
    row=db.query(DBLocalNotification).filter_by(id=notice_id).first()
    if not row:_fail('notification_unknown','notification does not exist')
    if row.owner_public_id!=actor.public_id:_fail('notification_forbidden','notification belongs to another user')
    if not row.read_at:row.read_at=_now()
    return row
