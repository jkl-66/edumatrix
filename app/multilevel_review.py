from __future__ import annotations
import hashlib
from datetime import datetime,timezone
from typing import Any
from app.database import DBMultilevelReviewCase,DBMultilevelReviewDecision,DBUser
from app.m1_enterprise import organization_role,require_organization_access
class MultilevelReviewError(ValueError):
 def __init__(self,code,message):super().__init__(message);self.code=code
def fail(c,m):raise MultilevelReviewError(c,m)
def now():return datetime.now(timezone.utc).replace(tzinfo=None)
def submit(db,*,actor:DBUser,organization_id,object_type,object_id,object_version,evidence_snapshot):
 role=require_organization_access(db,organization_id=organization_id,user_public_id=actor.public_id,action='read')
 old=db.query(DBMultilevelReviewCase).filter_by(organization_id=organization_id,object_type=object_type,object_id=object_id,object_version=object_version).first()
 if old:return old,False
 row=DBMultilevelReviewCase(organization_id=organization_id,submitter_public_id=actor.public_id,object_type=object_type,object_id=object_id,object_version=object_version,evidence_snapshot=evidence_snapshot,status='level1_pending',current_level=1);db.add(row);db.flush();decision=DBMultilevelReviewDecision(review_case_id=row.id,level=0,action='submit',actor_public_id=actor.public_id,actor_role=role,from_status='new',to_status='level1_pending',reason='提交多级审核',reason_hash=hashlib.sha256('提交多级审核'.encode()).hexdigest(),evidence_snapshot=evidence_snapshot);db.add(decision);db.flush();return row,True
def decide(db,*,actor:DBUser,case_id,action,reason,expected_version):
 case=db.get(DBMultilevelReviewCase,case_id)
 if not case:fail('multilevel_review_unknown','review case does not exist')
 role=organization_role(db,organization_id=case.organization_id,user_public_id=actor.public_id)
 allowed={1:{'mentor','manager','admin'},2:{'manager','admin'},3:{'admin'}}
 if role not in allowed.get(case.current_level,set()):fail('multilevel_review_forbidden','current demonstration role cannot act at this level')
 if actor.public_id==case.submitter_public_id:fail('multilevel_review_self_forbidden','submitter cannot review own case')
 if case.lock_version!=expected_version:fail('multilevel_review_stale','review case version is stale')
 if case.status!=f'level{case.current_level}_pending':fail('multilevel_review_conflict','review case is not pending at current level')
 prior=db.query(DBMultilevelReviewDecision).filter_by(review_case_id=case.id,action='approve').all()
 if any(x.actor_public_id==actor.public_id for x in prior):fail('multilevel_review_separation_required','one account cannot approve multiple levels')
 before=case.status
 if action=='return':case.status='returned';case.resolved_at=now();after='returned'
 elif action=='approve':
  if case.current_level<3:case.current_level+=1;case.status=f'level{case.current_level}_pending';after=case.status
  else:case.status='signed';case.resolved_at=now();after='signed'
 else:fail('multilevel_review_action_invalid','unsupported action')
 case.lock_version+=1;row=DBMultilevelReviewDecision(review_case_id=case.id,level=int(before[5]),action=action,actor_public_id=actor.public_id,actor_role=role,from_status=before,to_status=after,reason=reason,reason_hash=hashlib.sha256(reason.encode()).hexdigest(),evidence_snapshot=case.evidence_snapshot);db.add(row);db.flush();return case
def payload(db,case):
 decisions=db.query(DBMultilevelReviewDecision).filter_by(review_case_id=case.id).order_by(DBMultilevelReviewDecision.created_at,DBMultilevelReviewDecision.id).all();return {'id':case.id,'organization_id':case.organization_id,'submitter_public_id':case.submitter_public_id,'object_type':case.object_type,'object_id':case.object_id,'object_version':case.object_version,'status':case.status,'current_level':case.current_level,'lock_version':case.lock_version,'evidence_snapshot':case.evidence_snapshot,'demo_disclaimer':'演示角色审核流程，不代表外部专家认证。','decisions':[{'id':d.id,'level':d.level,'action':d.action,'actor_public_id':d.actor_public_id,'actor_role':d.actor_role,'from_status':d.from_status,'to_status':d.to_status,'reason':d.reason,'reason_hash':d.reason_hash,'created_at':d.created_at.isoformat()} for d in decisions]}
def queue(db,*,actor:DBUser,organization_id):
 require_organization_access(db,organization_id=organization_id,user_public_id=actor.public_id,action='read');rows=db.query(DBMultilevelReviewCase).filter_by(organization_id=organization_id).order_by(DBMultilevelReviewCase.created_at.desc()).all();return [payload(db,x) for x in rows]
