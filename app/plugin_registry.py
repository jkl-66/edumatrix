"""Governed registry for bundled, non-executable vertical-domain data plugins."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
from typing import Any
from app.database import DBAuditLog,DBDomainPack,DBDomainVersion,DBPluginLifecycleEvent,DBPluginRegistration,DBUser
from app.m7_plugins import DomainPluginError,DomainPluginManifest,validate_plugin_package

ROOT=Path(__file__).resolve().parents[1]/"data"/"domain_plugins"
class PluginRegistryError(ValueError):
 def __init__(self,code,message):super().__init__(message);self.code=code
def _admin(actor):
 if actor.role!='admin':raise PluginRegistryError('plugin.forbidden','仅管理员可安装或卸载插件')
def _root(plugin_id):
 if not plugin_id or any(x in plugin_id for x in ('/','\\','..')):raise PluginRegistryError('plugin.unknown','插件不存在')
 root=(ROOT/plugin_id).resolve()
 if ROOT.resolve() not in root.parents or not root.is_dir():raise PluginRegistryError('plugin.unknown','插件不存在')
 return root
def _manifest(root):return DomainPluginManifest.model_validate_json((root/'plugin.json').read_text(encoding='utf-8'))
def _event(db,*,row,plugin_id,actor,action,outcome,reason,evidence):
 db.add(DBPluginLifecycleEvent(registration_id=row.id if row else None,plugin_id=plugin_id,actor_public_id=actor.public_id if actor else None,action=action,outcome=outcome,reason=reason,evidence_snapshot=evidence))
 db.add(DBAuditLog(actor_public_id=actor.public_id if actor else None,action=f'plugin.{action}',object_type='plugin_registration',object_id=row.id if row else plugin_id,trace_id=f'plugin-{plugin_id}-{action}',outcome=outcome,metadata_json={'plugin_id':plugin_id,'package_hash':evidence.get('package_hash','')}))
def discover(db,actor):
 items=[]
 if ROOT.exists():
  for root in sorted(x for x in ROOT.iterdir() if x.is_dir()):
   try:
    report=validate_plugin_package(root);manifest=_manifest(root);row=db.query(DBPluginRegistration).filter_by(plugin_id=manifest.plugin_id).first()
    items.append({'plugin_id':manifest.plugin_id,'plugin_version':manifest.plugin_version,'domain_key':manifest.domain_key,'title':manifest.title,'license':manifest.license,'attribution':manifest.attribution,'source_url':manifest.source_url,'source_version':manifest.source_version,'allowed_actions':list(manifest.allowed_actions),'package_hash':report['package_hash'],'status':row.status if row else 'available','lock_version':row.lock_version if row else 0,'registration_id':row.id if row else None})
   except Exception:continue
 return {'schema_version':'next.plugin-registry.v1','truth_label':'预置纯数据插件 · 不执行第三方代码','items':items}
def install(db,*,actor,plugin_id):
 _admin(actor);root=_root(plugin_id)
 try:report=validate_plugin_package(root);manifest=_manifest(root)
 except DomainPluginError as exc:
  _event(db,row=None,plugin_id=plugin_id,actor=actor,action='validate',outcome='failed',reason=str(exc),evidence={'error_code':exc.code});raise PluginRegistryError(exc.code,str(exc)) from exc
 row=db.query(DBPluginRegistration).filter_by(plugin_id=manifest.plugin_id).first()
 if row and row.package_hash!=report['package_hash']:raise PluginRegistryError('plugin.version_conflict','同一插件 ID 的冻结包 hash 不一致')
 pack=db.query(DBDomainPack).filter_by(domain_key=manifest.domain_key).first()
 if not pack:pack=DBDomainPack(domain_key=manifest.domain_key,title=manifest.title,status='active');db.add(pack);db.flush()
 version=db.query(DBDomainVersion).filter_by(domain_pack_id=pack.id,version=manifest.plugin_version).first()
 assets={a.purpose:json.loads((root/a.path).read_text(encoding='utf-8')) if a.media_type=='application/json' else (root/a.path).read_text(encoding='utf-8') for a in manifest.assets}
 if not version:
  version=DBDomainVersion(domain_pack_id=pack.id,version=manifest.plugin_version,ontology=assets.get('knowledge_points',{}),rules={'license':manifest.license,'source_url':manifest.source_url},templates={'chapters':assets.get('chapters',{})},checkers=[x.model_dump(mode='json') for x in manifest.checkers],evaluation_set=assets.get('evaluation_cases',{}),dependencies=[],content_hash=report['package_hash']);db.add(version);db.flush()
 pack.current_version_id=version.id;pack.status='active'
 if not row:
  row=DBPluginRegistration(plugin_id=manifest.plugin_id,plugin_version=manifest.plugin_version,domain_key=manifest.domain_key,title=manifest.title,manifest_snapshot=manifest.model_dump(mode='json'),verification_snapshot=report,package_hash=report['package_hash'],license=manifest.license,attribution=manifest.attribution,source_url=manifest.source_url,source_version=manifest.source_version,allowed_actions=list(manifest.allowed_actions),domain_pack_id=pack.id);db.add(row);db.flush()
 row.status='installed';row.domain_pack_id=pack.id;row.installed_by_public_id=actor.public_id;row.lock_version+=1
 _event(db,row=row,plugin_id=plugin_id,actor=actor,action='install',outcome='success',reason='管理员安装已验证数据插件',evidence={'package_hash':report['package_hash'],'assets':report['verified_assets'],'capability_boundary':report['capability_boundary']});db.flush();return detail(db,actor=actor,plugin_id=plugin_id)
def uninstall(db,*,actor,plugin_id,expected_version):
 _admin(actor);row=db.query(DBPluginRegistration).filter_by(plugin_id=plugin_id).first()
 if not row:raise PluginRegistryError('plugin.unknown','插件尚未注册')
 if row.lock_version!=expected_version:raise PluginRegistryError('plugin.version_conflict','插件状态已更新，请刷新')
 row.status='disabled';row.lock_version+=1
 if row.domain_pack_id:
  pack=db.get(DBDomainPack,row.domain_pack_id)
  if pack:pack.status='inactive'
 _event(db,row=row,plugin_id=plugin_id,actor=actor,action='uninstall',outcome='success',reason='禁用插件但保留领域版本和审计历史',evidence={'package_hash':row.package_hash});db.flush();return detail(db,actor=actor,plugin_id=plugin_id)
def detail(db,*,actor,plugin_id):
 row=db.query(DBPluginRegistration).filter_by(plugin_id=plugin_id).first()
 if not row:raise PluginRegistryError('plugin.unknown','插件尚未注册')
 events=db.query(DBPluginLifecycleEvent).filter_by(registration_id=row.id).order_by(DBPluginLifecycleEvent.created_at.desc()).all()
 return {'id':row.id,'plugin_id':row.plugin_id,'plugin_version':row.plugin_version,'domain_key':row.domain_key,'title':row.title,'status':row.status,'lock_version':row.lock_version,'package_hash':row.package_hash,'license':row.license,'attribution':row.attribution,'source_url':row.source_url,'source_version':row.source_version,'allowed_actions':row.allowed_actions,'manifest':row.manifest_snapshot,'verification':row.verification_snapshot,'events':[{'id':x.id,'action':x.action,'outcome':x.outcome,'reason':x.reason,'evidence':x.evidence_snapshot} for x in events]}
