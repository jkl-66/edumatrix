"""Frozen synthetic HR inbound preview and idempotent projection service."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import secrets
from typing import Any

from app.auth import get_password_hash
from app.database import (
    DBDepartment, DBExternalIdentityMapping, DBHREmployeeProjection,
    DBHRFieldMappingVersion, DBHRSyncBatch, DBHRSyncRecord,
    DBJobFamily, DBJobLevel, DBLocalSSOSession, DBOrganization,
    DBOrganizationMembership, DBUser,
)
from app.identity import normalize_role
from app.m1_lifecycle import record_audit


TRUTHFULNESS = {
    "mode": "synthetic_hr_simulation",
    "data_label": "冻结合成 HR 主数据 · 本地入站模拟",
    "network_sent": False,
    "real_hr_connected": False,
    "real_employee_data": False,
    "disclaimer": "用于演示字段映射、预览、幂等、离职撤销、冲突与乱序保护；不含真实员工数据，未连接真实 HR 系统。",
}

CANONICAL_FIELDS = (
    "external_employee_id", "display_name", "username", "department",
    "job_family_code", "job_title", "employment_status",
)
DEFAULT_FIELD_MAP = {
    "employee_no": "external_employee_id",
    "name": "display_name",
    "account": "username",
    "department_name": "department",
    "job_code": "job_family_code",
    "job_name": "job_title",
    "status": "employment_status",
}
FROZEN_DATASET = [
    {"employee_no": "SYN-1001", "name": "合成员工 林淼", "account": "synthetic_hr_1001", "department_name": "智能学习研发部", "job_code": "AI-LEARN", "job_name": "智能学习工程师", "status": "active"},
    {"employee_no": "SYN-1002", "name": "合成员工 周岚", "account": "synthetic_hr_1002", "department_name": "培训运营部", "job_code": "TRAIN-OPS", "job_name": "培训运营专员", "status": "active"},
    {"employee_no": "SYN-1003", "name": "合成员工 陈启", "account": "synthetic_hr_1003", "department_name": "智能学习研发部", "job_code": "AI-LEARN", "job_name": "智能学习工程师", "status": "leave"},
]


class HRSyncError(ValueError):
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
        raise HRSyncError("hr_sync_forbidden", "只有管理员可以管理 HR 同步", status_code=403)
    organization = session.query(DBOrganization).filter_by(id=organization_id, status="active").first()
    membership = session.query(DBOrganizationMembership).filter_by(
        organization_id=organization_id, user_public_id=actor.public_id, role="admin", status="active",
    ).first()
    if organization is None or membership is None:
        raise HRSyncError("hr_sync_forbidden", "管理员不属于该组织或组织不可用", status_code=403)
    return organization


def ensure_mapping(
    session: Any, *, actor: DBUser, organization_id: str,
    source_key: str = "competition-synthetic-hr", field_map: dict[str, str] | None = None,
) -> tuple[DBHRFieldMappingVersion, bool]:
    _require_admin(session, actor, organization_id)
    mapping = field_map or DEFAULT_FIELD_MAP
    if set(mapping.values()) != set(CANONICAL_FIELDS) or len(mapping) != len(CANONICAL_FIELDS):
        raise HRSyncError("invalid_field_mapping", "字段映射必须完整且一对一覆盖规范员工字段", status_code=422)
    if any(not str(key).strip() for key in mapping):
        raise HRSyncError("invalid_field_mapping", "源字段名不能为空", status_code=422)
    mapping_hash = _hash(mapping)
    existing = session.query(DBHRFieldMappingVersion).filter_by(
        organization_id=organization_id, source_key=source_key, mapping_hash=mapping_hash,
    ).first()
    if existing:
        return existing, False
    latest = session.query(DBHRFieldMappingVersion).filter_by(
        organization_id=organization_id, source_key=source_key,
    ).order_by(DBHRFieldMappingVersion.version_number.desc()).first()
    row = DBHRFieldMappingVersion(
        organization_id=organization_id, source_key=source_key,
        version_number=(latest.version_number + 1) if latest else 1,
        field_map=mapping, mapping_hash=mapping_hash, created_by_public_id=actor.public_id,
    )
    session.add(row)
    session.flush()
    record_audit(
        session, actor_public_id=actor.public_id, action="hr_sync.mapping_create",
        object_type="hr_field_mapping_version", object_id=row.id,
        metadata={"organization_id": organization_id, "source_key": source_key, "version": row.version_number},
    )
    session.commit()
    return row, True


def _normalize(record: dict[str, Any], mapping: DBHRFieldMappingVersion) -> dict[str, str]:
    output: dict[str, str] = {}
    for source_field, target_field in mapping.field_map.items():
        value = str(record.get(source_field, "")).strip()
        output[target_field] = value
    missing = [field for field in CANONICAL_FIELDS if not output.get(field)]
    if missing:
        raise HRSyncError("source_record_invalid", f"源记录缺少字段：{', '.join(missing)}", status_code=422)
    if output["employment_status"] not in {"active", "leave"}:
        raise HRSyncError("source_record_invalid", "employment_status 只能是 active 或 leave", status_code=422)
    if len(output["username"]) > 64:
        raise HRSyncError("source_record_invalid", "映射后的 username 超过 64 字符", status_code=422)
    return output


def _decision(session: Any, organization_id: str, source_key: str, record: dict[str, str], source_sequence: int) -> dict[str, Any]:
    projection = session.query(DBHREmployeeProjection).filter_by(
        organization_id=organization_id, source_key=source_key,
        external_employee_id=record["external_employee_id"],
    ).first()
    user_by_name = session.query(DBUser).filter_by(username=record["username"]).first()
    if projection is None and user_by_name is not None:
        membership = session.query(DBOrganizationMembership).filter_by(
            organization_id=organization_id, user_public_id=user_by_name.public_id,
        ).first()
        if membership is None:
            return {"external_employee_id": record["external_employee_id"], "action": "conflict", "reason": "username_owned_outside_hr_projection", "record": record}
    if projection is not None:
        projected_user = session.query(DBUser).filter_by(public_id=projection.user_public_id).one()
        if record["username"] != projected_user.username:
            reason = "username_owned_by_another_user" if user_by_name is not None else "projected_username_changed"
            return {"external_employee_id": record["external_employee_id"], "action": "conflict", "reason": reason, "record": record}
    if projection and source_sequence < projection.source_sequence:
        return {"external_employee_id": record["external_employee_id"], "action": "out_of_order", "reason": "record_sequence_older_than_projection", "record": record}
    record_hash = _hash(record)
    if projection is None:
        action = "skip_leave" if record["employment_status"] == "leave" else "create"
    elif projection.source_record_hash == record_hash:
        action = "noop"
    elif record["employment_status"] == "leave":
        action = "offboard"
    else:
        action = "update"
    return {"external_employee_id": record["external_employee_id"], "action": action, "reason": "", "record": record, "record_hash": record_hash}


def preview_sync(
    session: Any, *, actor: DBUser, organization_id: str, mapping_version_id: str,
    source_snapshot_id: str, source_sequence: int, records: list[dict[str, Any]],
) -> tuple[DBHRSyncBatch, bool]:
    _require_admin(session, actor, organization_id)
    mapping = session.query(DBHRFieldMappingVersion).filter_by(
        id=mapping_version_id, organization_id=organization_id,
    ).first()
    if mapping is None:
        raise HRSyncError("mapping_not_found", "HR 字段映射版本不存在", status_code=404)
    if not records or len(records) > 500:
        raise HRSyncError("invalid_snapshot", "HR 快照必须包含 1-500 条记录", status_code=422)
    source_hash = _hash(records)
    existing = session.query(DBHRSyncBatch).filter_by(
        organization_id=organization_id, source_key=mapping.source_key,
        source_snapshot_id=source_snapshot_id,
    ).first()
    if existing:
        if existing.source_hash != source_hash or existing.source_sequence != source_sequence or existing.mapping_version_id != mapping.id:
            raise HRSyncError("snapshot_id_conflict", "snapshot ID 已绑定另一份源数据或序列")
        return existing, False
    latest_applied = session.query(DBHRSyncBatch).filter_by(
        organization_id=organization_id, source_key=mapping.source_key, status="applied",
    ).order_by(DBHRSyncBatch.source_sequence.desc()).first()
    if latest_applied and source_sequence <= latest_applied.source_sequence:
        raise HRSyncError("snapshot_out_of_order", "源序列不高于已应用批次，拒绝乱序写入")
    normalized = [_normalize(record, mapping) for record in records]
    ids = [item["external_employee_id"] for item in normalized]
    usernames = [item["username"] for item in normalized]
    if len(set(ids)) != len(ids) or len(set(usernames)) != len(usernames):
        raise HRSyncError("duplicate_source_identity", "同一快照包含重复员工编号或账号", status_code=422)
    decisions = [_decision(session, organization_id, mapping.source_key, item, source_sequence) for item in normalized]
    counts: dict[str, int] = {}
    for item in decisions:
        counts[item["action"]] = counts.get(item["action"], 0) + 1
    preview = {"counts": counts, "records": decisions, "blocking_conflicts": counts.get("conflict", 0) + counts.get("out_of_order", 0)}
    row = DBHRSyncBatch(
        organization_id=organization_id, source_key=mapping.source_key,
        source_snapshot_id=source_snapshot_id, source_sequence=source_sequence,
        mapping_version_id=mapping.id, source_snapshot=records,
        preview_snapshot=preview, source_hash=source_hash,
        status="previewed", created_by_public_id=actor.public_id,
    )
    session.add(row)
    session.flush()
    record_audit(
        session, actor_public_id=actor.public_id, action="hr_sync.preview",
        object_type="hr_sync_batch", object_id=row.id,
        metadata={"organization_id": organization_id, "source_sequence": source_sequence, "counts": counts},
    )
    session.commit()
    return row, True


def _department(session: Any, organization_id: str, name: str) -> DBDepartment:
    row = session.query(DBDepartment).filter_by(organization_id=organization_id, name=name).first()
    if row is None:
        row = DBDepartment(organization_id=organization_id, name=name)
        session.add(row)
        session.flush()
    return row


def _job_level(session: Any, organization_id: str, code: str, title: str) -> DBJobLevel:
    family = session.query(DBJobFamily).filter_by(organization_id=organization_id, code=code).first()
    if family is None:
        family = DBJobFamily(organization_id=organization_id, code=code, title=title)
        session.add(family)
        session.flush()
    level = session.query(DBJobLevel).filter_by(job_family_id=family.id, level_code="CURRENT", version="hr-demo-v1").first()
    if level is None:
        level = DBJobLevel(job_family_id=family.id, level_code="CURRENT", version="hr-demo-v1", title=title, responsibilities=[], status="published")
        session.add(level)
        session.flush()
    return level


def _append_record(session: Any, batch: DBHRSyncBatch, decision: dict[str, Any], outcome: str, user_id: str | None, evidence: dict[str, Any]) -> None:
    session.add(DBHRSyncRecord(
        batch_id=batch.id, organization_id=batch.organization_id,
        external_employee_id=decision["external_employee_id"], action=decision["action"],
        outcome=outcome, user_public_id=user_id,
        evidence_snapshot=evidence, evidence_hash=_hash(evidence),
    ))


def apply_sync(
    session: Any, *, actor: DBUser, organization_id: str, batch_id: str,
    expected_lock_version: int,
) -> tuple[DBHRSyncBatch, bool]:
    _require_admin(session, actor, organization_id)
    batch = session.query(DBHRSyncBatch).filter_by(id=batch_id, organization_id=organization_id).first()
    if batch is None:
        raise HRSyncError("batch_not_found", "HR 同步批次不存在", status_code=404)
    if batch.status == "applied":
        return batch, False
    if batch.status != "previewed":
        raise HRSyncError("batch_not_applicable", "该批次当前不可应用")
    if batch.lock_version != expected_lock_version:
        raise HRSyncError("batch_version_conflict", "HR 批次已被其他操作更新")
    if batch.preview_snapshot.get("blocking_conflicts", 0):
        raise HRSyncError("preview_has_conflicts", "预览包含阻断冲突，不能写入")
    later = session.query(DBHRSyncBatch).filter(
        DBHRSyncBatch.organization_id == organization_id,
        DBHRSyncBatch.source_key == batch.source_key,
        DBHRSyncBatch.status == "applied",
        DBHRSyncBatch.source_sequence >= batch.source_sequence,
    ).first()
    if later:
        raise HRSyncError("batch_out_of_order", "已有相同或更高序列批次写入，拒绝乱序应用")
    for decision in batch.preview_snapshot["records"]:
        record = decision["record"]
        action = decision["action"]
        projection = session.query(DBHREmployeeProjection).filter_by(
            organization_id=organization_id, source_key=batch.source_key,
            external_employee_id=decision["external_employee_id"],
        ).first()
        if action == "skip_leave":
            _append_record(session, batch, decision, "skipped", None, {"reason": "unknown_employee_already_leave"})
            continue
        if action == "noop":
            _append_record(session, batch, decision, "unchanged", projection.user_public_id if projection else None, {"record_hash": decision["record_hash"]})
            continue
        if action == "create":
            user = session.query(DBUser).filter_by(username=record["username"]).first()
            if user is None:
                user = DBUser(
                    username=record["username"], display_name=record["display_name"], role="student",
                    hashed_password=get_password_hash(secrets.token_urlsafe(32)), is_active=True,
                )
                session.add(user)
                session.flush()
            membership = session.query(DBOrganizationMembership).filter_by(
                organization_id=organization_id, user_public_id=user.public_id,
            ).first()
            if membership is None:
                membership = DBOrganizationMembership(organization_id=organization_id, user_public_id=user.public_id, role="learner", status="active")
                session.add(membership)
            department = _department(session, organization_id, record["department"])
            level = _job_level(session, organization_id, record["job_family_code"], record["job_title"])
            projection = DBHREmployeeProjection(
                organization_id=organization_id, source_key=batch.source_key,
                external_employee_id=record["external_employee_id"], user_public_id=user.public_id,
                department_id=department.id, job_level_id=level.id, employment_status="active",
                source_sequence=batch.source_sequence, source_record_hash=decision["record_hash"], last_batch_id=batch.id,
            )
            session.add(projection)
            _append_record(session, batch, decision, "created", user.public_id, {"department_id": department.id, "job_level_id": level.id})
            continue
        if projection is None:
            raise HRSyncError("projection_missing_during_apply", "预览后的员工投影发生变化")
        user = session.query(DBUser).filter_by(public_id=projection.user_public_id).one()
        membership = session.query(DBOrganizationMembership).filter_by(
            organization_id=organization_id, user_public_id=user.public_id,
        ).first()
        if action == "offboard":
            projection.employment_status = "leave"
            if membership:
                membership.status = "removed"
            revoked = 0
            for mapping in session.query(DBExternalIdentityMapping).filter_by(
                organization_id=organization_id, user_public_id=user.public_id, status="active",
            ).all():
                mapping.status = "revoked"
                mapping.revoked_at = _now()
                revoked += 1
                for sso_session in session.query(DBLocalSSOSession).filter_by(mapping_id=mapping.id, status="active").all():
                    sso_session.status = "revoked"
                    sso_session.revoked_at = _now()
            evidence = {"membership_status": "removed", "external_identities_revoked": revoked, "user_deleted": False, "learning_evidence_deleted": False}
            _append_record(session, batch, decision, "offboarded", user.public_id, evidence)
        elif action == "update":
            user.display_name = record["display_name"]
            department = _department(session, organization_id, record["department"])
            level = _job_level(session, organization_id, record["job_family_code"], record["job_title"])
            projection.department_id = department.id
            projection.job_level_id = level.id
            projection.employment_status = "active"
            if membership:
                membership.status = "active"
            _append_record(session, batch, decision, "updated", user.public_id, {"department_id": department.id, "job_level_id": level.id})
        projection.source_sequence = batch.source_sequence
        projection.source_record_hash = decision["record_hash"]
        projection.last_batch_id = batch.id
        projection.lock_version += 1
    batch.status = "applied"
    batch.applied_at = _now()
    batch.lock_version += 1
    record_audit(
        session, actor_public_id=actor.public_id, action="hr_sync.apply",
        object_type="hr_sync_batch", object_id=batch.id,
        metadata={"organization_id": organization_id, "source_sequence": batch.source_sequence, "counts": batch.preview_snapshot["counts"]},
    )
    session.commit()
    return batch, True


def frozen_snapshot(sequence: int = 1, offboard_existing: bool = False) -> dict[str, Any]:
    records = [dict(item) for item in FROZEN_DATASET]
    if offboard_existing:
        records[0]["status"] = "leave"
        records[1]["department_name"] = "学习发展部"
    return {"source_snapshot_id": f"competition-hr-snapshot-{sequence}", "source_sequence": sequence, "records": records}


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def workspace(session: Any, *, actor: DBUser, organization_id: str | None = None) -> dict[str, Any]:
    if normalize_role(actor.role) != "admin":
        raise HRSyncError("hr_sync_forbidden", "只有管理员可以查看 HR 同步工作台", status_code=403)
    memberships = session.query(DBOrganizationMembership).filter_by(user_public_id=actor.public_id, role="admin", status="active").all()
    organizations = []
    for member in memberships:
        org = session.query(DBOrganization).filter_by(id=member.organization_id, status="active").first()
        if org:
            organizations.append({"id": org.id, "name": org.name})
    if not organizations:
        return {"truthfulness": TRUTHFULNESS, "organizations": [], "selected": None}
    selected_id = organization_id or organizations[0]["id"]
    organization = _require_admin(session, actor, selected_id)
    mappings = [{"id": row.id, "source_key": row.source_key, "version_number": row.version_number, "field_map": row.field_map, "mapping_hash": row.mapping_hash}
                for row in session.query(DBHRFieldMappingVersion).filter_by(organization_id=selected_id).order_by(DBHRFieldMappingVersion.version_number.desc()).all()]
    batches = [{"id": row.id, "source_snapshot_id": row.source_snapshot_id, "source_sequence": row.source_sequence, "status": row.status,
                "lock_version": row.lock_version, "preview": row.preview_snapshot, "source_hash": row.source_hash, "created_at": _dt(row.created_at), "applied_at": _dt(row.applied_at)}
               for row in session.query(DBHRSyncBatch).filter_by(organization_id=selected_id).order_by(DBHRSyncBatch.created_at.desc()).limit(20).all()]
    employees = []
    for row in session.query(DBHREmployeeProjection).filter_by(organization_id=selected_id).order_by(DBHREmployeeProjection.external_employee_id).all():
        user = session.query(DBUser).filter_by(public_id=row.user_public_id).one()
        department = session.query(DBDepartment).filter_by(id=row.department_id).first()
        level = session.query(DBJobLevel).filter_by(id=row.job_level_id).first()
        membership = session.query(DBOrganizationMembership).filter_by(organization_id=selected_id, user_public_id=row.user_public_id).first()
        employees.append({"external_employee_id": row.external_employee_id, "user_public_id": row.user_public_id,
                          "display_name": user.display_name, "department": department.name if department else "",
                          "job_title": level.title if level else "", "employment_status": row.employment_status,
                          "membership_status": membership.status if membership else "missing", "source_sequence": row.source_sequence})
    return {"truthfulness": TRUTHFULNESS, "organizations": organizations,
            "selected": {"organization": {"id": organization.id, "name": organization.name},
                         "mappings": mappings, "batches": batches, "employees": employees,
                         "frozen_samples": {"initial": frozen_snapshot(1), "change": frozen_snapshot(2, True)}}}
