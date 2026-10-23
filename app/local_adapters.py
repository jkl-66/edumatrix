"""Deterministic local-only enterprise training adapter sessions."""
from __future__ import annotations
import hashlib,json
from typing import Any
from app.database import DBLocalAdapterEvent,DBLocalAdapterSession,DBUser

ADAPTER_ID='vision-quality-line-v1'
ADAPTER={
 'id':ADAPTER_ID,'title':'输送线视觉质检模拟器','environment':'local_simulation','network_access':False,
 'device_connection':False,'credential_policy':'placeholder_only','credential_example':'DEMO-LOCAL-ONLY',
 'description':'用冻结合成缺陷分布演示质检阈值、吞吐、故障诊断和恢复。',
 'parameters':{
  'confidence_threshold':{'label':'置信阈值','minimum':0.4,'maximum':0.9,'step':0.05,'default':0.65},
  'inspection_rate':{'label':'检测速率','minimum':20,'maximum':120,'step':10,'default':80},
  'buffer_size':{'label':'缓冲容量','minimum':10,'maximum':100,'step':10,'default':50},
 },
 'faults':[
  {'id':'sensor_timeout','label':'传感器超时','recovery':'restart_sensor_channel'},
  {'id':'quality_drift','label':'质量分布漂移','recovery':'recalibrate_threshold'},
  {'id':'queue_backpressure','label':'队列背压','recovery':'drain_and_resize_buffer'},
 ],
 'hidden_expected_values_exposed':False,
}
class LocalAdapterError(ValueError):
 def __init__(self,code,message):super().__init__(message);self.code=code
def fail(c,m):raise LocalAdapterError(c,m)
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(v):return hashlib.sha256(canonical(v).encode()).hexdigest()
def list_adapters():return {'items':[ADAPTER],'count':1,'boundary':'仅连接进程内确定性模拟器；不提供真实设备、企业内网或生产地址输入。'}
def params(values):
 if set(values)!=set(ADAPTER['parameters']):fail('local_adapter.parameters_invalid','参数必须与适配器契约完全匹配')
 out={}
 for k,s in ADAPTER['parameters'].items():
  v=values[k]
  if isinstance(v,bool) or not isinstance(v,(int,float)):fail('local_adapter.parameter_type_invalid',f'{k} 必须是数值')
  if v<s['minimum'] or v>s['maximum'] or abs((v-s['minimum'])/s['step']-round((v-s['minimum'])/s['step']))>1e-7:fail('local_adapter.parameter_out_of_range',f'{k} 超出范围或步长')
  out[k]=int(v) if isinstance(s['default'],int) else round(float(v),6)
 return out
def owned(db,actor,id):
 r=db.get(DBLocalAdapterSession,id)
 if r is None:fail('local_adapter.unknown','适配器会话不存在')
 if r.owner_public_id!=actor.public_id:fail('local_adapter.forbidden','无权访问该适配器会话')
 return r
def payload(db,r):
 events=db.query(DBLocalAdapterEvent).filter_by(session_id=r.id).order_by(DBLocalAdapterEvent.created_at.desc()).limit(30).all()
 return {'id':r.id,'title':r.title,'adapter_id':r.adapter_id,'environment':r.environment,'credential_placeholder':r.credential_placeholder,'status':r.status,'parameters':r.parameters,'metrics':r.metrics,'active_fault':r.active_fault,'diagnosis':r.diagnosis,'recovery_action':r.recovery_action,'recovery_verified':r.recovery_verified,'hidden_acceptance':r.hidden_acceptance,'lock_version':r.lock_version,'events':[{'id':e.id,'action':e.action,'from_status':e.from_status,'to_status':e.to_status,'snapshot':e.snapshot,'created_at':e.created_at} for e in events],'adapter':ADAPTER,'boundary':'本地模拟环境；无网络、无真实设备、无真实企业凭证。'}
def listing(db,actor):
 rows=db.query(DBLocalAdapterSession).filter_by(owner_public_id=actor.public_id).order_by(DBLocalAdapterSession.updated_at.desc()).all();return {'items':[payload(db,r) for r in rows],'count':len(rows)}
def create(db,actor,title,adapter_id,credential_placeholder,parameters):
 if adapter_id!=ADAPTER_ID:fail('local_adapter.adapter_unknown','适配器不存在')
 credential=' '.join(credential_placeholder.split())
 if credential!='DEMO-LOCAL-ONLY':fail('local_adapter.credential_invalid','仅接受占位凭证 DEMO-LOCAL-ONLY；禁止提交真实凭证')
 name=' '.join(title.split())[:256]
 if not name:fail('local_adapter.title_required','会话名称不能为空')
 r=DBLocalAdapterSession(owner_public_id=actor.public_id,title=name,adapter_id=adapter_id,credential_placeholder=credential,parameters=params(parameters));db.add(r);db.flush();return payload(db,r)
def metrics(p):
 t=float(p['confidence_threshold']);rate=int(p['inspection_rate']);buf=int(p['buffer_size'])
 return {'throughput_per_min':round(rate*(.96-abs(t-.65)*.2),2),'false_reject_rate':round(.035+abs(t-.65)*.12,4),'miss_rate':round(max(.01,.075-(t-.4)*.16),4),'queue_utilization':round(min(.99,rate/(buf*2.2)),4),'deterministic':True}
REC={'sensor_timeout':'restart_sensor_channel','quality_drift':'recalibrate_threshold','queue_backpressure':'drain_and_resize_buffer'}
def action(db,actor,id,action,expected_lock_version,idempotency_key,parameters=None,fault_type='none',diagnosis='',recovery_action=''):
 r=owned(db,actor,id);req={'action':action,'parameters':parameters,'fault_type':fault_type,'diagnosis':diagnosis,'recovery_action':recovery_action,'expected':expected_lock_version};h=digest(req)
 old=db.query(DBLocalAdapterEvent).filter_by(owner_public_id=actor.public_id,idempotency_key=idempotency_key).one_or_none()
 if old:
  if old.request_hash!=h:fail('local_adapter.idempotency_conflict','幂等键已绑定到其他动作')
  return {**payload(db,r),'action_created':False}
 if r.lock_version!=expected_lock_version:fail('local_adapter.conflict','会话已更新，请刷新后重试')
 before=r.status
 if action=='connect':
  if r.status!='disconnected':fail('local_adapter.transition_invalid','只有断开状态可以连接')
  r.status='connected'
 elif action=='configure':
  if r.status not in {'connected','recovered','passed'} or parameters is None:fail('local_adapter.transition_invalid','连接后才能配置参数')
  r.parameters=params(parameters);r.status='connected';r.metrics={};r.hidden_acceptance={}
 elif action=='inject_fault':
  if r.status!='connected' or fault_type not in REC:fail('local_adapter.transition_invalid','连接状态才能注入受控故障')
  r.active_fault=fault_type;r.diagnosis='';r.recovery_action='';r.recovery_verified=False
 elif action in {'run','rerun'}:
  if action=='run' and r.status!='connected':fail('local_adapter.transition_invalid','连接状态才能运行')
  if action=='rerun' and r.status!='recovered':fail('local_adapter.transition_invalid','恢复完成后才能重跑')
  r.metrics=metrics(r.parameters);r.status='failed' if r.active_fault!='none' else 'running'
 elif action=='diagnose':
  if r.status!='failed' or not diagnosis or not recovery_action:fail('local_adapter.transition_invalid','失败状态需要诊断和恢复动作')
  r.diagnosis=' '.join(diagnosis.split())[:500];r.recovery_action=recovery_action;r.recovery_verified=recovery_action==REC[r.active_fault];r.status='diagnosed'
 elif action=='recover':
  if r.status!='diagnosed' or not r.recovery_verified:fail('local_adapter.recovery_unverified','必须选择正确恢复动作')
  r.active_fault='none';r.status='recovered'
 elif action=='submit':
  if r.status!='running':fail('local_adapter.transition_invalid','无故障运行完成后才能提交验收')
  m=r.metrics;checks={'throughput':m['throughput_per_min']>=65,'false_reject':m['false_reject_rate']<=.05,'miss_rate':m['miss_rate']<=.04,'local_boundary':r.environment=='local_simulation'};failures=[k for k,v in checks.items() if not v];r.hidden_acceptance={'passed':not failures,'passed_count':sum(checks.values()),'total_count':len(checks),'failure_categories':failures,'checker_version':'local-adapter-hidden-v1','hidden_expected_values_exposed':False};r.status='passed' if not failures else 'connected'
 elif action=='reset':
  r.status='disconnected';r.metrics={};r.active_fault='none';r.diagnosis='';r.recovery_action='';r.recovery_verified=False;r.hidden_acceptance={}
 else:fail('local_adapter.action_unknown','不支持的适配器动作')
 r.lock_version+=1;db.flush();snap={'environment':r.environment,'status':r.status,'active_fault':r.active_fault,'metrics':r.metrics,'recovery_verified':r.recovery_verified,'hidden_acceptance':r.hidden_acceptance};e=DBLocalAdapterEvent(session_id=r.id,owner_public_id=actor.public_id,idempotency_key=idempotency_key,action=action,from_status=before,to_status=r.status,request_hash=h,snapshot=snap);db.add(e);db.flush();return {**payload(db,r),'action_created':True}
