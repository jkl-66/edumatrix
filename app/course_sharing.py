"""Immutable course releases, recipient-owned copies, and explicit upstream updates."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.course_governance import require_manager
from app.database import (
    DBAuditLog, DBCourse, DBCourseDerivedCopy, DBCourseDocument, DBCourseShareDecision,
    DBCourseShareRelease, DBCourseWithdrawal, DBOrganization, DBOrganizationMembership,
    DBSourceDocument, DBTeachingClass, DBTeachingClassMember, DBUser,
)
from app.identity import new_public_id, normalize_role


class CourseSharingError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message); self.code = code


def _fail(code: str, message: str) -> None: raise CourseSharingError(code, message)
def _now() -> datetime: return datetime.now(timezone.utc).replace(tzinfo=None)
def _canonical(value: Any) -> str: return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
def _hash(value: Any) -> str: return hashlib.sha256((_canonical(value) if not isinstance(value, str) else value).encode("utf-8")).hexdigest()
def _stable(prefix: str, *parts: str) -> str: return f"{prefix}-{hashlib.sha256(chr(31).join(parts).encode()).hexdigest()[:32]}"


def _audit(db: Any, actor: DBUser, action: str, object_type: str, object_id: str, metadata: dict[str, Any]) -> None:
    db.add(DBAuditLog(actor_public_id=actor.public_id, action=action, object_type=object_type, object_id=object_id,
                      trace_id=new_public_id("trace"), outcome="success", metadata_json=metadata))


def _course(db: Any, course_id: str) -> DBCourse:
    row = db.get(DBCourse, course_id)
    if row is None: _fail("course_share_course_unknown", "course does not exist")
    from course_catalog import course_is_selectable
    if not course_is_selectable(db, row): _fail("course_share_course_unavailable", "course is not currently available for selection")
    return row


def _org_role(db: Any, organization_id: str, actor: DBUser) -> str | None:
    if normalize_role(actor.role) == "admin": return "admin"
    row = db.query(DBOrganizationMembership).filter_by(
        organization_id=organization_id, user_public_id=actor.public_id, status="active").first()
    return row.role if row else None


def _target(db: Any, target_type: str, target_id: str) -> Any:
    if target_type == "class": row = db.get(DBTeachingClass, target_id)
    elif target_type == "organization": row = db.get(DBOrganization, target_id)
    else: _fail("course_share_target_invalid", "target type must be class or organization")
    if row is None: _fail("course_share_target_unknown", "share target does not exist")
    return row


def _require_target_publish(db: Any, target_type: str, target_id: str, actor: DBUser) -> None:
    row = _target(db, target_type, target_id)
    if row.status != "active": _fail("course_share_target_inactive", "share target is not active")
    if target_type == "class": require_manager(db, row.course_id, actor)
    elif _org_role(db, target_id, actor) not in {"manager", "admin"}:
        _fail("course_share_forbidden", "organization sharing requires manager access")


def _require_target_read(db: Any, target_type: str, target_id: str, actor: DBUser) -> None:
    row = _target(db, target_type, target_id)
    if target_type == "class":
        try: require_manager(db, row.course_id, actor); return
        except Exception as exc:
            if getattr(exc, "code", "") != "governance_forbidden": raise
        member = db.query(DBTeachingClassMember).filter(
            DBTeachingClassMember.class_id == target_id,
            DBTeachingClassMember.user_public_id == actor.public_id,
            DBTeachingClassMember.status.in_(["active", "suspended"]),
        ).first()
        if member is None: _fail("course_share_forbidden", "class share is not visible to this user")
    elif _org_role(db, target_id, actor) is None:
        _fail("course_share_forbidden", "organization share is not visible to this user")


def _snapshot(db: Any, course: DBCourse) -> tuple[dict[str, Any], dict[str, Any]]:
    docs = db.query(DBCourseDocument).filter_by(course_id=course.id).order_by(DBCourseDocument.chapter_order, DBCourseDocument.id).all()
    sources = db.query(DBSourceDocument).filter_by(course_id=course.id).order_by(DBSourceDocument.id).all()
    data = {
        "schema_version": "next.course-share-snapshot.v1",
        "course": {key: getattr(course, key) for key in ("id", "version", "title", "subject", "description", "domain_pack", "language", "content_origin", "visibility", "status", "manifest_version", "manifest_data")},
        "documents": [{key: getattr(row, key) for key in ("chapter_order", "filename", "file_type", "file_size", "title", "content", "tags", "chunk_count", "content_hash", "source_path", "license_text", "status")} for row in docs],
        "sources": [{key: getattr(row, key) for key in ("title", "filename", "file_format", "content_hash", "source_sha256", "processed_sha256", "file_size", "source_url", "source_path", "license_text", "parser_version", "parser_metadata", "parse_warnings", "processing_error_code", "processing_status")} for row in sources],
    }
    licenses = {
        "schema_version": "next.course-license-snapshot.v1", "course_license": course.license_text,
        "course_origin": course.content_origin,
        "documents": [{"filename": row.filename, "license_text": row.license_text, "source_path": row.source_path, "content_hash": row.content_hash} for row in docs],
        "sources": [{"filename": row.filename, "license_text": row.license_text, "source_url": row.source_url, "source_path": row.source_path,
                     "source_sha256": row.source_sha256, "processed_sha256": row.processed_sha256} for row in sources],
        "legal_review_state": "not_automatically_determined",
    }
    return data, licenses


def publish_release(db: Any, *, actor: DBUser, course_id: str, target_type: str, target_id: str, title: str) -> dict[str, Any]:
    course = _course(db, course_id); require_manager(db, course_id, actor); _require_target_publish(db, target_type, target_id, actor)
    if course.status != "published": _fail("course_share_course_not_published", "only a published course can be shared")
    snapshot, licenses = _snapshot(db, course); snapshot_hash = _hash({"snapshot": snapshot, "licenses": licenses})
    existing = db.query(DBCourseShareRelease).filter_by(source_course_id=course.id, source_course_version=course.version,
        target_type=target_type, target_id=target_id, snapshot_hash=snapshot_hash).first()
    if existing: return release_payload(existing)
    row = DBCourseShareRelease(source_course_id=course.id, source_course_version=course.version,
        source_manifest_version=course.manifest_version, target_type=target_type, target_id=target_id,
        title=title.strip(), snapshot_data=snapshot, license_snapshot=licenses, snapshot_hash=snapshot_hash,
        created_by_public_id=actor.public_id)
    db.add(row); db.flush(); _audit(db, actor, "course_share.published", "course_share_release", row.id,
        {"course_id": course.id, "target_type": target_type, "target_id": target_id, "snapshot_hash": snapshot_hash})
    return release_payload(row)


def _visible_releases(db: Any, actor: DBUser) -> list[DBCourseShareRelease]:
    rows = db.query(DBCourseShareRelease).order_by(DBCourseShareRelease.created_at.desc()).all(); visible = []
    for row in rows:
        try: _require_target_read(db, row.target_type, row.target_id, actor); visible.append(row)
        except CourseSharingError as exc:
            if exc.code != "course_share_forbidden": raise
    return visible


def release_payload(row: DBCourseShareRelease) -> dict[str, Any]:
    return {"id": row.id, "source_course_id": row.source_course_id, "source_course_version": row.source_course_version,
        "source_manifest_version": row.source_manifest_version, "target_type": row.target_type, "target_id": row.target_id,
        "title": row.title, "snapshot_hash": row.snapshot_hash, "status": row.status,
        "license_snapshot": row.license_snapshot, "created_by_public_id": row.created_by_public_id,
        "created_at": row.created_at.isoformat() if row.created_at else None, "withdrawn_at": row.withdrawn_at.isoformat() if row.withdrawn_at else None}


def _copy_id(source_id: str, actor_id: str) -> str: return _stable("course-copy", source_id, actor_id)


def _apply_snapshot(db: Any, course: DBCourse, snapshot: dict[str, Any], licenses: dict[str, Any], actor: DBUser) -> None:
    src = snapshot["course"]
    for key in ("version", "title", "subject", "description", "domain_pack", "language", "content_origin", "manifest_version", "manifest_data"):
        setattr(course, key, src[key])
    course.license_text = licenses.get("course_license", ""); course.status = "published"
    existing_docs = {row.filename: row for row in db.query(DBCourseDocument).filter_by(course_id=course.id).all()}
    seen = set()
    for item in snapshot["documents"]:
        seen.add(item["filename"]); row = existing_docs.get(item["filename"])
        if row is None:
            row = DBCourseDocument(id=_stable("cdoc", course.id, item["filename"]), course_id=course.id); db.add(row)
        for key, value in item.items(): setattr(row, key, value)
    for name, row in existing_docs.items():
        if name not in seen: row.status = "withdrawn"
    existing_sources = {row.filename: row for row in db.query(DBSourceDocument).filter_by(course_id=course.id).all()}
    for item in snapshot["sources"]:
        row = existing_sources.get(item["filename"])
        if row is None:
            row = DBSourceDocument(id=_stable("src", course.id, item["filename"]), course_id=course.id, uploader_public_id=actor.public_id); db.add(row)
        for key, value in item.items(): setattr(row, key, value)


def create_derived_copy(db: Any, *, actor: DBUser, release_id: str) -> dict[str, Any]:
    release = db.get(DBCourseShareRelease, release_id)
    if release is None: _fail("course_share_release_unknown", "share release does not exist")
    _require_target_read(db, release.target_type, release.target_id, actor)
    if release.status != "published": _fail("course_share_release_withdrawn", "withdrawn release cannot create a new copy")
    existing = db.query(DBCourseDerivedCopy).filter_by(release_id=release.id, recipient_public_id=actor.public_id).first()
    if existing: return copy_payload(db, existing, actor)
    course_id = _copy_id(release.source_course_id, actor.public_id)
    if db.get(DBCourse, course_id): _fail("course_share_copy_conflict", "recipient already has a derived course for this source")
    src = release.snapshot_data["course"]
    course = DBCourse(id=course_id, version=src["version"], title=f"{src['title']}（派生副本）", subject=src["subject"],
        description=src["description"], domain_pack=src["domain_pack"], language=src["language"], content_origin=src["content_origin"],
        license_text=release.license_snapshot.get("course_license", ""), visibility="private", status="published",
        owner_public_id=actor.public_id, manifest_version=src["manifest_version"], manifest_data=src["manifest_data"])
    db.add(course); db.flush(); _apply_snapshot(db, course, release.snapshot_data, release.license_snapshot, actor)
    course.title = f"{release.snapshot_data['course']['title']}（派生副本）"; course.visibility = "private"
    row = DBCourseDerivedCopy(release_id=release.id, derived_course_id=course.id, recipient_public_id=actor.public_id,
        applied_release_id=release.id, baseline_snapshot=release.snapshot_data, baseline_hash=release.snapshot_hash)
    db.add(row); db.flush(); _audit(db, actor, "course_share.copy_created", "course_derived_copy", row.id,
        {"release_id": release.id, "derived_course_id": course.id, "license_inherited": True})
    return copy_payload(db, row, actor)


def _local_snapshot(db: Any, copy: DBCourseDerivedCopy) -> dict[str, Any]: return _snapshot(db, _course(db, copy.derived_course_id))[0]


def _changes(base: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for key in ("version", "title", "subject", "description", "domain_pack", "language", "content_origin", "manifest_version", "manifest_data"):
        before, after = base["course"].get(key), candidate["course"].get(key)
        if before != after: result[f"course.{key}"] = {"before": before, "after": after}
    for section in ("documents", "sources"):
        left = {x["filename"]: x for x in base[section]}; right = {x["filename"]: x for x in candidate[section]}
        for name in sorted(set(left) | set(right)):
            if left.get(name) != right.get(name): result[f"{section}.{name}"] = {"before_hash": _hash(left.get(name)), "after_hash": _hash(right.get(name))}
    return result


def update_preview(db: Any, copy: DBCourseDerivedCopy, actor: DBUser) -> dict[str, Any] | None:
    if copy.recipient_public_id != actor.public_id and normalize_role(actor.role) != "admin": _fail("course_share_forbidden", "derived copy belongs to another recipient")
    applied = db.get(DBCourseShareRelease, copy.applied_release_id)
    latest = db.query(DBCourseShareRelease).filter_by(source_course_id=applied.source_course_id,
        target_type=applied.target_type, target_id=applied.target_id).order_by(
            DBCourseShareRelease.created_at.desc(), DBCourseShareRelease.id.desc()).first()
    if latest is None or latest.id == applied.id: return None
    decided = db.query(DBCourseShareDecision).filter_by(derived_copy_id=copy.id, upstream_release_id=latest.id).first()
    base, local, upstream = copy.baseline_snapshot, _local_snapshot(db, copy), latest.snapshot_data
    local_changes, upstream_changes = _changes(base, local), _changes(base, upstream)
    conflicts = sorted(set(local_changes) & set(upstream_changes))
    copy.upstream_status = "withdrawn" if latest.status == "withdrawn" else ("current" if decided else "update_available")
    return {"release": release_payload(latest), "local_changes": local_changes, "upstream_changes": upstream_changes,
        "conflicts": conflicts, "conflict_count": len(conflicts), "decision": decision_payload(decided) if decided else None}


def copy_payload(db: Any, row: DBCourseDerivedCopy, actor: DBUser) -> dict[str, Any]:
    if row.recipient_public_id != actor.public_id and normalize_role(actor.role) != "admin": _fail("course_share_forbidden", "derived copy belongs to another recipient")
    course = _course(db, row.derived_course_id); preview = update_preview(db, row, actor)
    source_withdrawn = db.query(DBCourseWithdrawal).filter_by(course_id=db.get(DBCourseShareRelease, row.applied_release_id).source_course_id).first()
    if source_withdrawn: row.upstream_status = "withdrawn"
    return {"id": row.id, "release_id": row.release_id, "applied_release_id": row.applied_release_id,
        "derived_course": {"id": course.id, "version": course.version, "title": course.title, "description": course.description,
                           "license_text": course.license_text, "visibility": course.visibility, "status": course.status},
        "recipient_public_id": row.recipient_public_id, "baseline_hash": row.baseline_hash,
        "upstream_status": row.upstream_status, "lock_version": row.lock_version, "update_preview": preview}


def workspace(db: Any, actor: DBUser) -> dict[str, Any]:
    from course_catalog import course_is_selectable
    releases = _visible_releases(db, actor)
    copies = db.query(DBCourseDerivedCopy).filter_by(recipient_public_id=actor.public_id).order_by(DBCourseDerivedCopy.created_at.desc()).all()
    classes = db.query(DBTeachingClass).filter_by(status="active").all()
    organizations = db.query(DBOrganization).filter_by(status="active").all()
    manageable_classes = []
    for row in classes:
        try: require_manager(db, row.course_id, actor); manageable_classes.append({"id": row.id, "title": row.title, "course_id": row.course_id})
        except Exception: pass
    manageable_orgs = [{"id": row.id, "name": row.name} for row in organizations if _org_role(db, row.id, actor) in {"manager", "admin"}]
    courses = []
    for row in db.query(DBCourse).order_by(DBCourse.title).all():
        if not course_is_selectable(db, row):
            continue
        try: require_manager(db, row.id, actor); courses.append({"id": row.id, "title": row.title, "version": row.version})
        except Exception: pass
    return {"schema_version": "next.course-sharing-workspace.v1",
        "truth_label": "不可变发布快照 · 派生副本 · 显式更新决定",
        "disclaimer": "许可证按来源原样继承并保留署名；系统不自动给出法律兼容性结论。上游撤回不会删除接收方历史。",
        "manageable_courses": courses, "manageable_classes": manageable_classes, "manageable_organizations": manageable_orgs,
        "releases": [release_payload(x) for x in releases], "copies": [copy_payload(db, x, actor) for x in copies]}


def decide_update(db: Any, *, actor: DBUser, copy_id: str, upstream_release_id: str, action: str,
                  reason: str, expected_version: int) -> dict[str, Any]:
    copy = db.get(DBCourseDerivedCopy, copy_id)
    if copy is None: _fail("course_share_copy_unknown", "derived copy does not exist")
    if copy.recipient_public_id != actor.public_id: _fail("course_share_forbidden", "only the recipient can decide an update")
    if copy.lock_version != expected_version: _fail("course_share_version_conflict", "derived copy has changed")
    preview = update_preview(db, copy, actor)
    if preview is None or preview["release"]["id"] != upstream_release_id: _fail("course_share_update_stale", "upstream release is no longer current")
    existing = db.query(DBCourseShareDecision).filter_by(derived_copy_id=copy.id, upstream_release_id=upstream_release_id).first()
    if existing: return copy_payload(db, copy, actor)
    frozen = {"baseline": copy.baseline_snapshot, "local": _local_snapshot(db, copy), "upstream": db.get(DBCourseShareRelease, upstream_release_id).snapshot_data,
              "local_changes": preview["local_changes"], "upstream_changes": preview["upstream_changes"], "conflicts": preview["conflicts"]}
    row = DBCourseShareDecision(derived_copy_id=copy.id, upstream_release_id=upstream_release_id, action=action,
        conflict_snapshot=frozen, actor_public_id=actor.public_id, reason=reason.strip(), reason_sha256=_hash(reason.strip()))
    db.add(row)
    if action == "accept":
        release = db.get(DBCourseShareRelease, upstream_release_id)
        if release.status != "published": _fail("course_share_release_withdrawn", "withdrawn update cannot be applied")
        _apply_snapshot(db, _course(db, copy.derived_course_id), release.snapshot_data, release.license_snapshot, actor)
        _course(db, copy.derived_course_id).title = f"{release.snapshot_data['course']['title']}（派生副本）"
        copy.applied_release_id, copy.baseline_snapshot, copy.baseline_hash = release.id, release.snapshot_data, release.snapshot_hash
        copy.upstream_status = "current"
    elif action == "ignore": copy.upstream_status = "current"
    else: _fail("course_share_action_invalid", "action must be accept or ignore")
    copy.lock_version += 1; db.flush(); _audit(db, actor, f"course_share.update_{action}", "course_derived_copy", copy.id,
        {"upstream_release_id": upstream_release_id, "conflict_count": len(preview["conflicts"]), "reason_sha256": row.reason_sha256})
    return copy_payload(db, copy, actor)


def decision_payload(row: DBCourseShareDecision) -> dict[str, Any]:
    return {"id": row.id, "upstream_release_id": row.upstream_release_id, "action": row.action,
        "actor_public_id": row.actor_public_id, "reason": row.reason, "reason_sha256": row.reason_sha256,
        "conflicts": row.conflict_snapshot.get("conflicts", []), "created_at": row.created_at.isoformat() if row.created_at else None}


def propagate_withdrawals(db: Any, actor: DBUser) -> dict[str, int]:
    releases = db.query(DBCourseShareRelease).filter_by(status="published").all(); releases_changed = copies_changed = 0
    for release in releases:
        if db.query(DBCourseWithdrawal).filter_by(course_id=release.source_course_id).first():
            release.status, release.withdrawn_at = "withdrawn", _now(); releases_changed += 1
            for copy in db.query(DBCourseDerivedCopy).filter_by(release_id=release.id).all():
                copy.upstream_status = "withdrawn"; copy.lock_version += 1; copies_changed += 1
    if releases_changed: _audit(db, actor, "course_share.withdrawal_propagated", "course_share_release", "batch",
        {"release_count": releases_changed, "copy_count": copies_changed, "historical_copies_deleted": 0})
    return {"release_count": releases_changed, "copy_count": copies_changed, "historical_copies_deleted": 0}
