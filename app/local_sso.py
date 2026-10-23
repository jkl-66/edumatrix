"""Deterministic local SSO simulator for competition integration demonstrations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any

from app.database import (
    DBExternalIdentityMapping,
    DBLocalSSOEvent,
    DBLocalSSOMappingVersion,
    DBLocalSSOProvider,
    DBLocalSSOSession,
    DBOrganization,
    DBOrganizationMembership,
    DBUser,
)
from app.identity import normalize_role
from app.m1_lifecycle import record_audit


TRUTHFULNESS = {
    "mode": "local_idp_simulation",
    "data_label": "本地模拟 IdP · 冻结合成身份数据",
    "network_sent": False,
    "real_idp_connected": False,
    "oidc_saml_conformance_verified": False,
    "application_access_token_issued": False,
    "disclaimer": "用于演示身份映射、冲突、撤销和应急入口；未连接真实 IdP，也未通过真实 OIDC/SAML 兼容认证。",
}

DEFAULT_GROUP_ROLE_MAP = {
    "edumatrix-admins": "admin",
    "training-managers": "manager",
    "course-mentors": "mentor",
    "learners": "learner",
}
ROLE_PRIORITY = {"learner": 1, "mentor": 2, "manager": 3, "admin": 4}


class LocalSSOError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _require_admin(session: Any, actor: DBUser, organization_id: str) -> DBOrganization:
    if normalize_role(actor.role) != "admin":
        raise LocalSSOError("sso_forbidden", "只有管理员可以管理本地 SSO 模拟器", status_code=403)
    organization = session.query(DBOrganization).filter_by(id=organization_id, status="active").first()
    membership = session.query(DBOrganizationMembership).filter_by(
        organization_id=organization_id, user_public_id=actor.public_id, role="admin", status="active",
    ).first()
    if organization is None or membership is None:
        raise LocalSSOError("sso_forbidden", "管理员不属于该组织或组织不可用", status_code=403)
    return organization


def _event(
    session: Any, *, organization_id: str, provider_id: str | None, actor_public_id: str,
    action: str, outcome: str, subject: str = "", assertion_id: str = "", evidence: dict[str, Any],
) -> DBLocalSSOEvent:
    row = DBLocalSSOEvent(
        organization_id=organization_id, provider_id=provider_id,
        actor_public_id=actor_public_id, action=action, outcome=outcome,
        external_subject=subject, assertion_id=assertion_id,
        evidence_snapshot=evidence, evidence_hash=_hash(evidence),
    )
    session.add(row)
    session.flush()
    return row


def _mapping_version(session: Any, provider: DBLocalSSOProvider) -> DBLocalSSOMappingVersion:
    row = session.query(DBLocalSSOMappingVersion).filter_by(
        provider_id=provider.id, version_number=provider.current_mapping_version,
    ).first()
    if row is None:
        raise LocalSSOError("mapping_version_missing", "当前映射规则版本不存在")
    return row


def _provider(session: Any, organization_id: str, provider_id: str) -> DBLocalSSOProvider:
    row = session.query(DBLocalSSOProvider).filter_by(id=provider_id, organization_id=organization_id).first()
    if row is None:
        raise LocalSSOError("provider_not_found", "本地 SSO provider 不存在", status_code=404)
    return row


def resolve_role(groups: list[str], rule: DBLocalSSOMappingVersion) -> tuple[str, list[dict[str, str]]]:
    role_map = rule.group_role_map or {}
    matches = [{"group": group, "role": role_map[group]} for group in groups if group in role_map]
    role = max((item["role"] for item in matches), key=lambda value: ROLE_PRIORITY[value], default=rule.default_role)
    return role, matches


def ensure_provider(
    session: Any, *, actor: DBUser, organization_id: str, provider_key: str,
    display_name: str, protocol_style: str,
) -> tuple[DBLocalSSOProvider, bool]:
    organization = _require_admin(session, actor, organization_id)
    existing = session.query(DBLocalSSOProvider).filter_by(
        organization_id=organization_id, provider_key=provider_key,
    ).first()
    if existing is not None:
        expected = (display_name, protocol_style)
        actual = (existing.display_name, existing.protocol_style)
        if expected != actual:
            raise LocalSSOError("provider_key_conflict", "provider key 已绑定另一份配置")
        return existing, False
    provider = DBLocalSSOProvider(
        organization_id=organization.id, provider_key=provider_key,
        display_name=display_name, protocol_style=protocol_style,
        issuer=f"https://local-idp.invalid/{organization.id}/{provider_key}",
        created_by_public_id=actor.public_id,
    )
    session.add(provider)
    session.flush()
    rule_data = {
        "subject_claim": "sub", "groups_claim": "groups",
        "group_role_map": DEFAULT_GROUP_ROLE_MAP, "default_role": "learner",
    }
    session.add(DBLocalSSOMappingVersion(
        provider_id=provider.id, version_number=1,
        subject_claim="sub", groups_claim="groups",
        group_role_map=DEFAULT_GROUP_ROLE_MAP, default_role="learner",
        mapping_hash=_hash(rule_data), created_by_public_id=actor.public_id,
    ))
    _event(
        session, organization_id=organization.id, provider_id=provider.id,
        actor_public_id=actor.public_id, action="provider_create", outcome="created",
        evidence={"provider_key": provider_key, "protocol_style": protocol_style, "mapping_version": 1},
    )
    record_audit(
        session, actor_public_id=actor.public_id, action="local_sso.provider_create",
        object_type="local_sso_provider", object_id=provider.id,
        metadata={"organization_id": organization.id, "protocol_style": protocol_style},
    )
    session.commit()
    return provider, True


def set_provider_status(
    session: Any, *, actor: DBUser, organization_id: str, provider_id: str,
    status: str, expected_lock_version: int,
) -> DBLocalSSOProvider:
    _require_admin(session, actor, organization_id)
    provider = _provider(session, organization_id, provider_id)
    if provider.lock_version != expected_lock_version:
        raise LocalSSOError("provider_version_conflict", "provider 已被其他操作更新")
    if provider.status == status:
        return provider
    provider.status = status
    provider.lock_version += 1
    _event(
        session, organization_id=organization_id, provider_id=provider.id,
        actor_public_id=actor.public_id, action="provider_status", outcome=status,
        evidence={"status": status, "lock_version": provider.lock_version},
    )
    session.commit()
    return provider


def preview_assertion(
    session: Any, *, actor: DBUser, organization_id: str, provider_id: str,
    assertion_id: str, subject: str, groups: list[str], target_user_public_id: str,
) -> dict[str, Any]:
    _require_admin(session, actor, organization_id)
    provider = _provider(session, organization_id, provider_id)
    rule = _mapping_version(session, provider)
    role, matches = resolve_role(groups, rule)
    member = session.query(DBOrganizationMembership).filter_by(
        organization_id=organization_id, user_public_id=target_user_public_id, status="active",
    ).first()
    if member is None:
        raise LocalSSOError("target_not_active_member", "目标用户不是该组织有效成员", status_code=422)
    existing = session.query(DBExternalIdentityMapping).filter_by(
        organization_id=organization_id, provider=provider.provider_key, external_subject=subject,
    ).first()
    conflict = None
    if existing and existing.user_public_id != target_user_public_id:
        conflict = "subject_bound_to_another_user"
    elif existing and existing.status == "revoked":
        conflict = "subject_revoked"
    preview = {
        "assertion_id": assertion_id, "subject": subject, "groups": groups,
        "target_user_public_id": target_user_public_id,
        "resolved_role": role, "matched_rules": matches,
        "mapping_version": rule.version_number, "mapping_hash": rule.mapping_hash,
        "can_bind": conflict is None, "conflict_code": conflict,
    }
    _event(
        session, organization_id=organization_id, provider_id=provider.id,
        actor_public_id=actor.public_id, action="assertion_preview",
        outcome="conflict" if conflict else "ready", subject=subject,
        assertion_id=assertion_id, evidence=preview,
    )
    session.commit()
    return preview


def bind_assertion(
    session: Any, *, actor: DBUser, organization_id: str, provider_id: str,
    assertion_id: str, subject: str, groups: list[str], target_user_public_id: str,
) -> tuple[DBExternalIdentityMapping, bool, str]:
    _require_admin(session, actor, organization_id)
    provider = _provider(session, organization_id, provider_id)
    if provider.status != "active":
        raise LocalSSOError("provider_disabled", "provider 已停用，不能绑定身份")
    rule = _mapping_version(session, provider)
    role, matches = resolve_role(groups, rule)
    membership = session.query(DBOrganizationMembership).filter_by(
        organization_id=organization_id, user_public_id=target_user_public_id, status="active",
    ).first()
    if membership is None:
        raise LocalSSOError("target_not_active_member", "目标用户不是该组织有效成员", status_code=422)
    existing = session.query(DBExternalIdentityMapping).filter_by(
        organization_id=organization_id, provider=provider.provider_key, external_subject=subject,
    ).first()
    if existing is not None:
        if existing.user_public_id != target_user_public_id:
            _event(
                session, organization_id=organization_id, provider_id=provider.id,
                actor_public_id=actor.public_id, action="identity_bind", outcome="conflict",
                subject=subject, assertion_id=assertion_id,
                evidence={"code": "subject_bound_to_another_user", "requested_user": target_user_public_id},
            )
            session.commit()
            raise LocalSSOError("subject_bound_to_another_user", "该 subject 已绑定另一名组织成员")
        if existing.status == "revoked":
            raise LocalSSOError("subject_revoked", "该 subject 已撤销，不能通过重复 assertion 恢复")
        if membership.role != role:
            _event(
                session, organization_id=organization_id, provider_id=provider.id,
                actor_public_id=actor.public_id, action="identity_bind", outcome="role_conflict",
                subject=subject, assertion_id=assertion_id,
                evidence={"code": "existing_binding_role_conflict", "current_role": membership.role, "requested_role": role},
            )
            session.commit()
            raise LocalSSOError("existing_binding_role_conflict", "同一绑定的组角色发生变化，请先撤销并由管理员重新确认")
        return existing, False, role
    mapping = DBExternalIdentityMapping(
        organization_id=organization_id, user_public_id=target_user_public_id,
        provider=provider.provider_key, external_subject=subject, status="active",
    )
    session.add(mapping)
    # Applying a mapped organization role is an explicit administrator bind action.
    membership.role = role
    session.flush()
    evidence = {
        "mapping_id": mapping.id, "target_user_public_id": target_user_public_id,
        "resolved_role": role, "matched_rules": matches, "mapping_version": rule.version_number,
    }
    _event(
        session, organization_id=organization_id, provider_id=provider.id,
        actor_public_id=actor.public_id, action="identity_bind", outcome="bound",
        subject=subject, assertion_id=assertion_id, evidence=evidence,
    )
    record_audit(
        session, actor_public_id=actor.public_id, action="local_sso.identity_bind",
        object_type="external_identity_mapping", object_id=mapping.id,
        metadata={"organization_id": organization_id, "provider": provider.provider_key, "resolved_role": role},
    )
    session.commit()
    return mapping, True, role


def simulate_login(
    session: Any, *, actor: DBUser, organization_id: str, provider_id: str,
    assertion_id: str, subject: str, groups: list[str], ttl_minutes: int = 15,
) -> tuple[DBLocalSSOSession, bool]:
    _require_admin(session, actor, organization_id)
    provider = _provider(session, organization_id, provider_id)
    if provider.status != "active":
        raise LocalSSOError("provider_disabled", "本地模拟 IdP 当前不可用")
    assertion = {"assertion_id": assertion_id, "subject": subject, "groups": groups, "provider_id": provider.id}
    assertion_hash = _hash(assertion)
    prior = session.query(DBLocalSSOSession).filter_by(
        organization_id=organization_id, assertion_id=assertion_id,
    ).first()
    if prior is not None:
        if prior.assertion_hash != assertion_hash:
            raise LocalSSOError("assertion_replay_conflict", "assertion ID 已用于不同载荷")
        return prior, False
    mapping = session.query(DBExternalIdentityMapping).filter_by(
        organization_id=organization_id, provider=provider.provider_key,
        external_subject=subject,
    ).first()
    if mapping is None:
        raise LocalSSOError("identity_not_bound", "该 subject 尚未绑定", status_code=404)
    if mapping.status != "active":
        raise LocalSSOError("identity_revoked", "该外部身份已撤销", status_code=403)
    membership = session.query(DBOrganizationMembership).filter_by(
        organization_id=organization_id, user_public_id=mapping.user_public_id, status="active",
    ).first()
    if membership is None:
        raise LocalSSOError("membership_inactive", "绑定用户不再是有效组织成员", status_code=403)
    rule = _mapping_version(session, provider)
    resolved_role, _ = resolve_role(groups, rule)
    if resolved_role != membership.role:
        raise LocalSSOError("role_mapping_drift", "当前 assertion 角色与已应用组织角色不一致，请重新预览并绑定")
    row = DBLocalSSOSession(
        organization_id=organization_id, provider_id=provider.id, mapping_id=mapping.id,
        user_public_id=mapping.user_public_id, assertion_id=assertion_id,
        assertion_hash=assertion_hash, resolved_organization_role=resolved_role,
        login_mode="simulated_sso", status="active", expires_at=_now() + timedelta(minutes=ttl_minutes),
    )
    session.add(row)
    session.flush()
    _event(
        session, organization_id=organization_id, provider_id=provider.id,
        actor_public_id=actor.public_id, action="simulated_login", outcome="accepted",
        subject=subject, assertion_id=assertion_id,
        evidence={"session_id": row.id, "user_public_id": row.user_public_id, "role": resolved_role, "ttl_minutes": ttl_minutes},
    )
    session.commit()
    return row, True


def revoke_mapping(
    session: Any, *, actor: DBUser, organization_id: str, mapping_id: str,
) -> DBExternalIdentityMapping:
    _require_admin(session, actor, organization_id)
    mapping = session.query(DBExternalIdentityMapping).filter_by(
        id=mapping_id, organization_id=organization_id,
    ).first()
    if mapping is None:
        raise LocalSSOError("mapping_not_found", "外部身份映射不存在", status_code=404)
    if mapping.status == "revoked":
        return mapping
    mapping.status = "revoked"
    mapping.revoked_at = _now()
    sessions = session.query(DBLocalSSOSession).filter_by(
        mapping_id=mapping.id, status="active",
    ).all()
    for row in sessions:
        row.status = "revoked"
        row.revoked_at = _now()
    provider = session.query(DBLocalSSOProvider).filter_by(
        organization_id=organization_id, provider_key=mapping.provider,
    ).first()
    _event(
        session, organization_id=organization_id, provider_id=provider.id if provider else None,
        actor_public_id=actor.public_id, action="identity_revoke", outcome="revoked",
        subject=mapping.external_subject,
        evidence={"mapping_id": mapping.id, "revoked_sessions": len(sessions)},
    )
    record_audit(
        session, actor_public_id=actor.public_id, action="local_sso.identity_revoke",
        object_type="external_identity_mapping", object_id=mapping.id,
        metadata={"organization_id": organization_id, "revoked_sessions": len(sessions)},
    )
    session.commit()
    return mapping


def emergency_admin_session(
    session: Any, *, actor: DBUser, organization_id: str, reason: str,
) -> DBLocalSSOSession:
    _require_admin(session, actor, organization_id)
    assertion_id = f"breakglass:{organization_id}:{int(_now().timestamp() * 1000000)}"
    evidence = {"reason": reason.strip(), "actor_public_id": actor.public_id, "provider_bypassed": True}
    row = DBLocalSSOSession(
        organization_id=organization_id, provider_id=None, mapping_id=None,
        user_public_id=actor.public_id, assertion_id=assertion_id,
        assertion_hash=_hash(evidence), resolved_organization_role="admin",
        login_mode="emergency_admin", status="active", expires_at=_now() + timedelta(minutes=10),
    )
    session.add(row)
    session.flush()
    _event(
        session, organization_id=organization_id, provider_id=None,
        actor_public_id=actor.public_id, action="emergency_admin", outcome="accepted",
        assertion_id=assertion_id,
        evidence={"session_id": row.id, "reason": reason.strip(), "ttl_minutes": 10, "provider_bypassed": True},
    )
    record_audit(
        session, actor_public_id=actor.public_id, action="local_sso.emergency_admin",
        object_type="local_sso_session", object_id=row.id,
        metadata={"organization_id": organization_id, "reason": reason.strip()},
    )
    session.commit()
    return row


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def workspace(session: Any, *, actor: DBUser, organization_id: str | None = None) -> dict[str, Any]:
    if normalize_role(actor.role) != "admin":
        raise LocalSSOError("sso_forbidden", "只有管理员可以查看本地 SSO 工作台", status_code=403)
    memberships = session.query(DBOrganizationMembership).filter_by(
        user_public_id=actor.public_id, role="admin", status="active",
    ).order_by(DBOrganizationMembership.created_at).all()
    organizations = []
    for member in memberships:
        org = session.query(DBOrganization).filter_by(id=member.organization_id, status="active").first()
        if org:
            organizations.append({"id": org.id, "name": org.name})
    if not organizations:
        return {"truthfulness": TRUTHFULNESS, "organizations": [], "selected": None}
    selected_id = organization_id or organizations[0]["id"]
    organization = _require_admin(session, actor, selected_id)
    members = []
    for membership in session.query(DBOrganizationMembership).filter_by(
        organization_id=selected_id, status="active",
    ).order_by(DBOrganizationMembership.created_at).all():
        user = session.query(DBUser).filter_by(public_id=membership.user_public_id).one()
        members.append({
            "user_public_id": user.public_id, "username": user.username,
            "display_name": user.display_name or user.username, "organization_role": membership.role,
        })
    providers = []
    for provider in session.query(DBLocalSSOProvider).filter_by(organization_id=selected_id).order_by(DBLocalSSOProvider.created_at).all():
        rule = _mapping_version(session, provider)
        providers.append({
            "id": provider.id, "provider_key": provider.provider_key,
            "display_name": provider.display_name, "protocol_style": provider.protocol_style,
            "issuer": provider.issuer, "status": provider.status,
            "lock_version": provider.lock_version, "mapping_version": rule.version_number,
            "mapping_hash": rule.mapping_hash, "group_role_map": rule.group_role_map,
            "default_role": rule.default_role,
        })
    mappings = []
    for mapping in session.query(DBExternalIdentityMapping).filter_by(organization_id=selected_id).order_by(DBExternalIdentityMapping.bound_at.desc()).all():
        user = session.query(DBUser).filter_by(public_id=mapping.user_public_id).one()
        mappings.append({
            "id": mapping.id, "provider": mapping.provider, "external_subject": mapping.external_subject,
            "user_public_id": mapping.user_public_id, "display_name": user.display_name or user.username,
            "status": mapping.status, "bound_at": _dt(mapping.bound_at), "revoked_at": _dt(mapping.revoked_at),
        })
    sessions = [{
        "id": row.id, "user_public_id": row.user_public_id,
        "resolved_organization_role": row.resolved_organization_role,
        "login_mode": row.login_mode, "status": row.status,
        "assertion_id": row.assertion_id, "issued_at": _dt(row.issued_at), "expires_at": _dt(row.expires_at),
    } for row in session.query(DBLocalSSOSession).filter_by(organization_id=selected_id).order_by(DBLocalSSOSession.issued_at.desc()).limit(30).all()]
    events = [{
        "id": row.id, "action": row.action, "outcome": row.outcome,
        "assertion_id": row.assertion_id, "evidence_hash": row.evidence_hash,
        "created_at": _dt(row.created_at),
    } for row in session.query(DBLocalSSOEvent).filter_by(organization_id=selected_id).order_by(DBLocalSSOEvent.created_at.desc()).limit(30).all()]
    return {
        "truthfulness": TRUTHFULNESS, "organizations": organizations,
        "selected": {"organization": {"id": organization.id, "name": organization.name},
                     "members": members, "providers": providers, "mappings": mappings,
                     "sessions": sessions, "events": events},
    }
