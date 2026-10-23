"""Tenant-private organization resource catalog with enforced copy policy."""
from __future__ import annotations
import hashlib,json
from datetime import datetime,timezone
from typing import Any
from app.course_governance import require_manager
from app.course_sharing import _apply_snapshot,_snapshot
from app.database import (DBAuditLog,DBCourse,DBOrganization,DBOrganizationMembership,
    DBOrganizationResourceAcquisition,DBOrganizationResourceListing,DBUser)
from app.identity import new_public_id,normalize_role

class OrganizationMarketplaceError(ValueError):
 def __init__(self,code,message):super().__init__(message);self.code=code
def fail(c,m):raise OrganizationMarketplaceError(c,m)
def now():return datetime.now(timezone.utc).replace(tzinfo=None)
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(v):return hashlib.sha256((v if isinstance(v,str) else canonical(v)).encode()).hexdigest()
def stable(p,*x):return f"{p}-{hashlib.sha256(chr(31).join(x).encode()).hexdigest()[:32]}"
def org(db,oid):
 r=db.get(DBOrganization,oid)
 if not r:fail('org_market_org_unknown','organization does not exist')
 if r.status!='active':fail('org_market_org_inactive','organization is not active')
 return r
def role(db,oid,a):
 if normalize_role(a.role)=='admin':return 'platform_admin'
 r=db.query(DBOrganizationMembership).filter_by(organization_id=oid,user_public_id=a.public_id,status='active').first()
 if not r:fail('org_market_forbidden','active organization membership is required')
 return r.role
def manage(db,oid,a):
 r=role(db,oid,a)
 if r not in {'manager','admin','platform_admin'}:fail('org_market_forbidden','organization manager access is required')
 return r
def policy(o):
 raw=o.sharing_policy or {};allowed=raw.get('allowed_copy_roles',['manager','admin'])
 allowed=[x for x in allowed if x in {'learner','mentor','manager','admin'}]
 return {'schema_version':'next.organization-sharing-policy.v1','copy_enabled':bool(raw.get('copy_enabled',False)),'allowed_copy_roles':sorted(set(allowed)),'source':'organization.sharing_policy'}
def audit(db,a,act,obj,oid,meta):db.add(DBAuditLog(actor_public_id=a.public_id,action=act,object_type=obj,object_id=oid,trace_id=new_public_id('trace'),outcome='success',metadata_json=meta))
def publish(db,*,actor,organization_id,course_id,title,summary,category,tags):
 o=org(db,organization_id);manage(db,o.id,actor);c=db.get(DBCourse,course_id)
 if not c:fail('org_market_course_unknown','course does not exist')
 from course_catalog import course_is_selectable
 if not course_is_selectable(db,c):fail('org_market_course_unavailable','only a published course with usable material can be listed')
 require_manager(db,c.id,actor)
 if c.status!='published':fail('org_market_course_unavailable','only published courses can be listed')
 snap,lic=_snapshot(db,c);h=digest({'snapshot':snap,'licenses':lic});existing=db.query(DBOrganizationResourceListing).filter_by(organization_id=o.id,course_id=c.id,course_version=c.version,snapshot_hash=h).first()
 if existing:return payload(existing)
 r=DBOrganizationResourceListing(organization_id=o.id,course_id=c.id,course_version=c.version,title=title.strip(),summary=summary.strip(),category=category.strip(),tags=sorted(set(tags)),snapshot_data=snap,license_snapshot=lic,snapshot_hash=h,policy_snapshot=policy(o),owner_public_id=actor.public_id)
 db.add(r);db.flush();audit(db,actor,'organization_marketplace.published','organization_resource_listing',r.id,{'organization_id':o.id,'snapshot_hash':h,'policy':r.policy_snapshot});return payload(r)
def payload(r):return {'id':r.id,'organization_id':r.organization_id,'course_id':r.course_id,'course_version':r.course_version,'title':r.title,'summary':r.summary,'category':r.category,'tags':r.tags or [],'snapshot_hash':r.snapshot_hash,'license':{'course_license':r.license_snapshot.get('course_license',''),'course_origin':r.license_snapshot.get('course_origin','')},'policy':r.policy_snapshot,'status':r.status,'lock_version':r.lock_version}
def catalog(db,*,actor,organization_id,query=''):
 o=org(db,organization_id);r=role(db,o.id,actor);needle=query.strip().casefold();rows=db.query(DBOrganizationResourceListing).filter_by(organization_id=o.id).order_by(DBOrganizationResourceListing.created_at.desc()).all()
 items=[payload(x) for x in rows if not needle or needle in f"{x.title} {x.summary} {x.category} {' '.join(x.tags or [])}".casefold()]
 return {'schema_version':'next.organization-marketplace.v1','organization':{'id':o.id,'name':o.name,'role':r},'policy':policy(o),'items':items,'truth_label':'组织私有学习市场 · 冻结合成企业边界','disclaimer':'仅活动组织成员可见；不宣称真实企业租户、SSO 或 HR 集成。'}
def acquire(db,*,actor,listing_id):
 r=db.get(DBOrganizationResourceListing,listing_id)
 if not r:fail('org_market_listing_unknown','organization resource listing does not exist')
 member_role=role(db,r.organization_id,actor);policy_role='admin' if member_role=='platform_admin' else member_role
 if r.status!='active':fail('org_market_listing_withdrawn','withdrawn listing cannot be acquired')
 p=r.policy_snapshot
 if not p.get('copy_enabled') or policy_role not in set(p.get('allowed_copy_roles',[])):fail('org_market_copy_forbidden','organization copy policy rejects this role')
 old=db.query(DBOrganizationResourceAcquisition).filter_by(listing_id=r.id,recipient_public_id=actor.public_id).first()
 if old:return acquisition(old)
 cid=stable('org-course',r.id,actor.public_id);src=r.snapshot_data['course'];c=DBCourse(id=cid,version=src['version'],title=f"{src['title']}（组织副本）",subject=src['subject'],description=src['description'],domain_pack=src['domain_pack'],language=src['language'],content_origin=src['content_origin'],license_text=r.license_snapshot.get('course_license',''),visibility='private',status='published',owner_public_id=actor.public_id,manifest_version=src['manifest_version'],manifest_data=src['manifest_data']);db.add(c);db.flush();_apply_snapshot(db,c,r.snapshot_data,r.license_snapshot,actor);c.title=f"{src['title']}（组织副本）";c.visibility='private'
 a=DBOrganizationResourceAcquisition(listing_id=r.id,organization_id=r.organization_id,recipient_public_id=actor.public_id,derived_course_id=c.id,listing_snapshot_hash=r.snapshot_hash);db.add(a);db.flush();audit(db,actor,'organization_marketplace.acquired','organization_resource_acquisition',a.id,{'organization_id':r.organization_id,'listing_id':r.id,'policy':p});return acquisition(a)
def acquisition(a):return {'id':a.id,'listing_id':a.listing_id,'organization_id':a.organization_id,'recipient_public_id':a.recipient_public_id,'derived_course_id':a.derived_course_id,'listing_snapshot_hash':a.listing_snapshot_hash,'source_status':a.source_status}
def withdraw(db,*,actor,listing_id,reason,expected_version):
 r=db.get(DBOrganizationResourceListing,listing_id)
 if not r:fail('org_market_listing_unknown','organization resource listing does not exist')
 manage(db,r.organization_id,actor)
 if r.lock_version!=expected_version:fail('org_market_version_conflict','organization listing has changed')
 if r.status!='active':fail('org_market_listing_withdrawn','listing is already withdrawn')
 r.status='withdrawn';r.lock_version+=1;r.withdrawn_at=now();db.query(DBOrganizationResourceAcquisition).filter_by(listing_id=r.id).update({'source_status':'withdrawn'});audit(db,actor,'organization_marketplace.withdrawn','organization_resource_listing',r.id,{'organization_id':r.organization_id,'reason_sha256':digest(reason.strip()),'historical_copies_deleted':0});return payload(r)
def organizations(db,actor):
 if normalize_role(actor.role)=='admin':rows=db.query(DBOrganization).filter_by(status='active').all()
 else:
  ids=[x[0] for x in db.query(DBOrganizationMembership.organization_id).filter_by(user_public_id=actor.public_id,status='active').all()];rows=db.query(DBOrganization).filter(DBOrganization.id.in_(ids or [''])).all()
 return [{'id':x.id,'name':x.name,'role':role(db,x.id,actor),'policy':policy(x)} for x in rows]
