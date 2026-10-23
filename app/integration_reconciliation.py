"""Versioned cross-adapter reconciliation previews and repair decisions."""
from __future__ import annotations
from typing import Any, Literal
from app.database import (
    DBExternalIdentityMapping, DBHREmployeeProjection, DBHRFieldMappingVersion, DBHRSyncBatch,
    DBHRSyncRecord, DBIntegrationDelivery, DBIntegrationReconciliationRun,
    DBIntegrationRepairDecision, DBLMSAssignmentExchange, DBLMSCatalogExport,
    DBLMSGradeSummary, DBLocalLMSConnection, DBLocalLRSStatement,
    DBLocalSSOMappingVersion, DBLocalSSOProvider, DBLocalWebhookEndpoint,
    DBOrganizationMembership, DBTrainingAssignment, DBUser, DBWebhookEvent, DBWebhookReceipt,
)
from app.m7_integrations import M7IntegrationError, _hash, _now, _require_integration_admin, requeue_dead_letter

class ReconciliationError(ValueError):
    def __init__(self,code,message,status_code=409):super().__init__(message);self.code=code;self.status_code=status_code
def _fail(code,message,status=409):raise ReconciliationError(code,message,status)

def _versions(db,org):
    sso=[]
    for p in db.query(DBLocalSSOProvider).filter_by(organization_id=org).all():
        m=db.query(DBLocalSSOMappingVersion).filter_by(provider_id=p.id,version_number=p.current_mapping_version).first()
        sso.append({'provider_id':p.id,'provider_key':p.provider_key,'version':p.current_mapping_version,'mapping_hash':m.mapping_hash if m else None,'valid':m is not None})
    hr=[{'mapping_id':r.id,'source_key':r.source_key,'version':r.version_number,'mapping_hash':r.mapping_hash,'field_map':r.field_map} for r in db.query(DBHRFieldMappingVersion).filter_by(organization_id=org).order_by(DBHRFieldMappingVersion.source_key,DBHRFieldMappingVersion.version_number).all()]
    lms=[{'connection_id':r.id,'connection_key':r.connection_key,'adapter_version':r.adapter_version,'status':r.status} for r in db.query(DBLocalLMSConnection).filter_by(organization_id=org).all()]
    webhook=[{'endpoint_id':r.id,'destination_key':r.destination_key,'signature_version':'v1','secret_fingerprint':r.secret_fingerprint,'status':r.status} for r in db.query(DBLocalWebhookEndpoint).filter_by(organization_id=org).all()]
    return {'sso':sso,'hr':hr,'lms':lms,'lrs':[{'adapter_version':'xapi-1.0.3-map-v1','receiver':'persistent-local-lrs'}],'webhook':webhook}

def build_reconciliation_preview(db,*,actor:DBUser,organization_id):
    _require_integration_admin(db,actor=actor,organization_id=organization_id)
    members=db.query(DBOrganizationMembership).filter_by(organization_id=organization_id,status='active').count()
    identities=db.query(DBExternalIdentityMapping).filter_by(organization_id=organization_id,status='active').count()
    employees=db.query(DBHREmployeeProjection).filter_by(organization_id=organization_id).count()
    assignments=db.query(DBTrainingAssignment).filter_by(organization_id=organization_id).count()
    exchanges=db.query(DBLMSAssignmentExchange).filter_by(organization_id=organization_id).count()
    xapi=db.query(DBIntegrationDelivery).filter_by(organization_id=organization_id,adapter_type='xapi',status='delivered').count()
    lrs=db.query(DBLocalLRSStatement).filter_by(organization_id=organization_id).count()
    webhook_sent=db.query(DBIntegrationDelivery).filter_by(organization_id=organization_id,adapter_type='webhook',status='delivered').count()
    webhook_received=db.query(DBWebhookReceipt).filter_by(organization_id=organization_id,outcome='accepted').count()
    versions=_versions(db,organization_id)
    source={'sso':{'active_members':members,'active_identity_mappings':identities},'hr':{'latest_batch':None,'employee_projections':employees,'record_outcomes':{}},'lms':{'catalog_exports':db.query(DBLMSCatalogExport).filter_by(organization_id=organization_id).count(),'candidate_grades':db.query(DBLMSGradeSummary).filter_by(organization_id=organization_id,evidence_status='candidate').count()},'lrs':{'delivered_xapi':xapi,'received_statements':lrs},'webhook':{'events':db.query(DBWebhookEvent).filter_by(organization_id=organization_id).count(),'delivered':webhook_sent,'accepted_receipts':webhook_received}}
    batch=db.query(DBHRSyncBatch).filter_by(organization_id=organization_id).order_by(DBHRSyncBatch.source_sequence.desc()).first()
    if batch:
        outcomes={}
        for r in db.query(DBHRSyncRecord).filter_by(batch_id=batch.id).all():outcomes[r.outcome]=outcomes.get(r.outcome,0)+1
        source['hr']['latest_batch']={'id':batch.id,'source_snapshot_id':batch.source_snapshot_id,'source_sequence':batch.source_sequence,'status':batch.status,'source_hash':batch.source_hash};source['hr']['record_outcomes']=outcomes
    counts={'sso':{'source':members,'target':identities},'hr':{'source':employees,'target':members},'lms':{'source':assignments,'target':exchanges},'lrs':{'source':xapi,'target':lrs},'webhook':{'source':webhook_sent,'target':webhook_received}}
    gaps=[]
    for adapter,c in counts.items():
        if c['source']!=c['target']:gaps.append({'key':f'count:{adapter}','adapter':adapter,'kind':'count_mismatch','severity':'warning','source_count':c['source'],'target_count':c['target'],'repair_actions':['acknowledge','dismiss']})
    for adapter in ('sso','hr','lms','webhook'):
        if not versions[adapter]:gaps.append({'key':f'mapping:{adapter}:missing','adapter':adapter,'kind':'mapping_missing','severity':'warning','source_count':0,'target_count':0,'repair_actions':['acknowledge','dismiss']})
    for r in db.query(DBIntegrationDelivery).filter(DBIntegrationDelivery.organization_id==organization_id,DBIntegrationDelivery.status.in_(['failed','dead_letter'])).order_by(DBIntegrationDelivery.created_at).all():
        actions=['acknowledge','dismiss'];actions.insert(0,'requeue') if r.status=='dead_letter' else None
        gaps.append({'key':f'delivery:{r.id}','adapter':r.adapter_type,'kind':'delivery_failure','severity':'error','delivery_id':r.id,'status':r.status,'error_code':r.last_error_code or 'delivery_failed','attempt_count':r.attempt_count,'repair_actions':actions})
    core={'schema_version':'integration-reconciliation-v1','organization_id':organization_id,'mapping_versions':versions,'source_preview':source,'count_snapshot':counts,'discrepancies':gaps}
    return {**core,'preview_hash':_hash(core),'write_performed':False,'truthfulness':{'mode':'local_simulation','data_label':'本地集成对账 · 冻结合成组织数据','real_enterprise_connected':False,'disclaimer':'对账运行验证本地适配器映射、数量、差异和恢复，不代表真实企业系统或外部审计结论。'}}

def create_reconciliation_run(db,*,actor:DBUser,organization_id,run_key,expected_preview_hash):
    p=build_reconciliation_preview(db,actor=actor,organization_id=organization_id)
    if p['preview_hash']!=expected_preview_hash:_fail('reconciliation_preview_stale','reconciliation preview changed; refresh before creating a run')
    old=db.query(DBIntegrationReconciliationRun).filter_by(organization_id=organization_id,run_key=run_key).first()
    if old:
        if old.snapshot_hash!=expected_preview_hash:_fail('reconciliation_run_key_conflict','run key is bound to another snapshot')
        return old,False
    row=DBIntegrationReconciliationRun(organization_id=organization_id,run_key=run_key,mapping_versions=p['mapping_versions'],source_preview=p['source_preview'],count_snapshot=p['count_snapshot'],discrepancies=p['discrepancies'],snapshot_hash=expected_preview_hash,status='open' if p['discrepancies'] else 'resolved',created_by_public_id=actor.public_id,closed_at=None if p['discrepancies'] else _now());db.add(row);db.commit();return row,True

def decide_repair(db,*,actor:DBUser,run_id,discrepancy_key,action:Literal['acknowledge','requeue','dismiss'],reason,expected_lock_version):
    run=db.query(DBIntegrationReconciliationRun).filter_by(id=run_id).first()
    if not run:_fail('reconciliation_run_not_found','reconciliation run does not exist',404)
    _require_integration_admin(db,actor=actor,organization_id=run.organization_id)
    if run.status!='open':_fail('reconciliation_run_closed','reconciliation run is already resolved')
    if run.lock_version!=expected_lock_version:_fail('reconciliation_version_conflict','reconciliation run changed; refresh required')
    gap=next((x for x in run.discrepancies if x.get('key')==discrepancy_key),None)
    if not gap:_fail('reconciliation_discrepancy_not_found','discrepancy is not present in the frozen run',404)
    if action not in gap.get('repair_actions',[]):_fail('reconciliation_action_forbidden','repair action is not allowed for this discrepancy',422)
    if db.query(DBIntegrationRepairDecision).filter_by(run_id=run.id,discrepancy_key=discrepancy_key).first():_fail('reconciliation_discrepancy_already_decided','discrepancy already has an immutable decision')
    before=dict(gap);after={'decision':action,'reason':reason}
    if action=='requeue':
        delivery=db.query(DBIntegrationDelivery).filter_by(id=gap.get('delivery_id')).first()
        if not delivery or delivery.organization_id!=run.organization_id:_fail('reconciliation_delivery_missing','frozen delivery is no longer available')
        try:requeue_dead_letter(db,actor=actor,delivery_id=delivery.id)
        except M7IntegrationError as exc:_fail(exc.code,str(exc))
        after.update({'delivery_id':delivery.id,'status':delivery.status,'attempt_count':delivery.attempt_count})
    row=DBIntegrationRepairDecision(run_id=run.id,organization_id=run.organization_id,discrepancy_key=discrepancy_key,action=action,actor_public_id=actor.public_id,reason=reason,before_snapshot=before,after_snapshot=after,evidence_hash=_hash({'before':before,'after':after,'actor':actor.public_id}));db.add(row);run.lock_version+=1
    if db.query(DBIntegrationRepairDecision).filter_by(run_id=run.id).count()+1>=len(run.discrepancies):run.status='resolved';run.closed_at=_now()
    db.commit();return row,run

def reconciliation_workspace(db,*,actor:DBUser,organization_id=None):
    if actor.role!='admin':_fail('reconciliation_forbidden','only administrators can inspect reconciliation',403)
    memberships=db.query(DBOrganizationMembership).filter_by(user_public_id=actor.public_id,role='admin',status='active').all();orgs=[{'id':x.organization_id} for x in memberships]
    if not orgs:return {'organizations':[],'selected':None}
    org=organization_id or orgs[0]['id'];_require_integration_admin(db,actor=actor,organization_id=org);preview=build_reconciliation_preview(db,actor=actor,organization_id=org);items=[]
    for run in db.query(DBIntegrationReconciliationRun).filter_by(organization_id=org).order_by(DBIntegrationReconciliationRun.created_at.desc()).limit(20).all():
        decisions=db.query(DBIntegrationRepairDecision).filter_by(run_id=run.id).order_by(DBIntegrationRepairDecision.created_at).all()
        items.append({'id':run.id,'run_key':run.run_key,'status':run.status,'lock_version':run.lock_version,'snapshot_hash':run.snapshot_hash,'mapping_versions':run.mapping_versions,'source_preview':run.source_preview,'count_snapshot':run.count_snapshot,'discrepancies':run.discrepancies,'created_at':run.created_at.isoformat(),'closed_at':run.closed_at.isoformat() if run.closed_at else None,'decisions':[{'id':x.id,'discrepancy_key':x.discrepancy_key,'action':x.action,'actor_public_id':x.actor_public_id,'reason':x.reason,'after_snapshot':x.after_snapshot,'evidence_hash':x.evidence_hash,'created_at':x.created_at.isoformat()} for x in decisions]})
    return {'organizations':orgs,'selected':{'organization_id':org,'preview':preview,'runs':items}}
