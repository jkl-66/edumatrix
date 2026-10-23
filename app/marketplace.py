"""Governed public learning marketplace over frozen canonical course snapshots."""

from __future__ import annotations

import copy, hashlib, json, math, re
from datetime import datetime, timedelta, timezone
from typing import Any

from app.course_governance import require_manager
from app.course_sharing import _apply_snapshot, _changes, _snapshot
from app.database import (
    DBAuditLog, DBCourse, DBMarketplaceAcquisition, DBMarketplaceDecision,
    DBMarketplaceListing, DBMarketplaceReport, DBMarketplaceComment,
    DBMarketplaceCommentEvent, DBMarketplaceCommentReport, DBMarketplaceFavorite,
    DBMarketplaceReview, DBMarketplaceReviewEvent, DBLearningEvent, DBUser,
    DBMarketplaceImpactEvent, DBMarketplaceImpactNotification,
    DBMarketplaceFork, DBMarketplaceForkVersion, DBMarketplaceForkDecision,
    DBMarketplaceRecommendationRun, DBMarketplaceRecommendationResult,
    DBProfileSnapshot, DBStudentProfile, DBArtifact, DBArtifactVersion, DBQualityCheck,
    DBMarketplacePersonalCopy, DBResourceBundle, DBResourceBundleVersion,
    DBResourceBundleItem, DBPlanDraft, DBPlanVersion, DBLearningPath, DBPathNode,
)
from app.identity import new_public_id, normalize_role
from app.m5_resources import canonical_resource_type, resource_route


class MarketplaceError(ValueError):
    def __init__(self, code: str, message: str): super().__init__(message); self.code = code


def _fail(code: str, message: str) -> None: raise MarketplaceError(code, message)
def _now() -> datetime: return datetime.now(timezone.utc).replace(tzinfo=None)
def _canonical(value: Any) -> str: return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
def _hash(value: Any) -> str: return hashlib.sha256((value if isinstance(value, str) else _canonical(value)).encode()).hexdigest()
def _stable(prefix: str, *parts: str) -> str: return f"{prefix}-{hashlib.sha256(chr(31).join(parts).encode()).hexdigest()[:32]}"


def _audit(db: Any, actor: DBUser, action: str, object_type: str, object_id: str, metadata: dict[str, Any]) -> None:
    db.add(DBAuditLog(actor_public_id=actor.public_id, action=action, object_type=object_type, object_id=object_id,
        trace_id=new_public_id("trace"), outcome="success", metadata_json=metadata))


def _listing(db: Any, listing_id: str) -> DBMarketplaceListing:
    row = db.get(DBMarketplaceListing, listing_id)
    if row is None: _fail("marketplace_listing_unknown", "marketplace listing does not exist")
    return row


def _admin(actor: DBUser) -> None:
    if normalize_role(actor.role) != "admin": _fail("marketplace_forbidden", "marketplace review requires an administrator")


MARKETPLACE_ITEM_TYPES = ("course", "resource", "resource_bundle", "learning_path")
MARKETPLACE_LEARNING_OBJECT_TYPES = MARKETPLACE_ITEM_TYPES[1:]
_SENSITIVE_PREVIEW_KEYS = {
    "answer", "answer_key", "correct_answer", "correct_answers", "rubric", "scoring_rule",
    "system_prompt", "developer_prompt", "prompt", "private_reasoning", "chain_of_thought",
    "api_key", "secret", "raw_log", "agent_log", "trace", "trace_id",
}


def _course_provenance(snapshot: dict[str, Any], licenses: dict[str, Any]) -> dict[str, Any]:
    course = dict(snapshot.get("course") or {})
    manifest = dict(course.get("manifest_data") or {})
    origin = str(licenses.get("course_origin") or course.get("content_origin") or "").strip()
    license_text = str(licenses.get("course_license") or "").strip()
    demo_value = manifest.get("demo_scope") or manifest.get("demo_data") or manifest.get("is_demo_data")
    is_demo = bool(demo_value) or origin.casefold().startswith(("demo:", "demo://", "synthetic:", "synthetic://"))
    missing = []
    if not str(course.get("title") or "").strip(): missing.append("course_title")
    if not origin and not is_demo: missing.append("course_origin")
    if not license_text and not is_demo: missing.append("course_license")
    return {
        "schema_version": "f9.marketplace-provenance.v1",
        "course_id": str(course.get("id") or ""),
        "course_title": str(course.get("title") or ""),
        "course_version": str(course.get("version") or ""),
        "source_label": origin or ("团队冻结合成演示数据" if is_demo else ""),
        "license_label": license_text or ("演示数据，仅用于比赛功能验证" if is_demo else ""),
        "is_demo_data": is_demo,
        "demo_label": str(demo_value or "演示/合成数据") if is_demo else "",
        "complete": not missing,
        "missing_fields": missing,
        "legal_boundary": "来源与许可证字段已冻结展示；系统不自动作出法律或专家认证结论。",
    }


def _listing_provenance(row: DBMarketplaceListing) -> dict[str, Any]:
    if row.item_type in MARKETPLACE_LEARNING_OBJECT_TYPES:
        return copy.deepcopy((row.snapshot_data or {}).get("provenance") or {})
    return _course_provenance(row.snapshot_data or {}, row.license_snapshot or {})


def _require_complete_provenance(provenance: dict[str, Any]) -> None:
    if provenance.get("complete") is True: return
    missing = ", ".join(str(item) for item in provenance.get("missing_fields") or []) or "unknown"
    _fail("marketplace_provenance_incomplete", f"marketplace source information is incomplete: {missing}")


def _safe_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _safe_metadata(item)
            for key, item in value.items()
            if str(key).casefold() not in _SENSITIVE_PREVIEW_KEYS
        }
    if isinstance(value, list): return [_safe_metadata(item) for item in value]
    return copy.deepcopy(value)


def _safe_excerpt(content: str, resource_type: str, limit: int = 320) -> str:
    if resource_type in {"quiz", "exercise", "feynman"}: return "该资源包含受限作答内容，保存个人副本后可在学习空间查看。"
    try:
        structured = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        structured = None
    if isinstance(structured, dict):
        safe = _safe_metadata(structured)
        text = " ".join(str(safe.get(key) or "") for key in ("title", "summary", "abstract", "learningGoal", "learning_objective"))
    else:
        lines = []
        for line in str(content or "").splitlines():
            lowered = line.casefold()
            if any(token in lowered for token in ("answer:", "answer_key", "correct_answer", "正确答案", "评分规则", "system prompt")):
                continue
            lines.append(line)
        text = " ".join(lines)
    clean = " ".join(text.replace("#", " ").split())
    return clean[:limit] + ("..." if len(clean) > limit else "")


def _course_for_object(db: Any, course_id: str | None) -> tuple[DBCourse, dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not course_id: _fail("marketplace_course_required", "learning object must belong to a course")
    course = db.get(DBCourse, course_id)
    if course is None: _fail("marketplace_course_unknown", "course does not exist")
    from course_catalog import course_is_selectable
    if not course_is_selectable(db, course):
        _fail("marketplace_course_unavailable", "course is not currently selectable")
    course_snapshot, licenses = _snapshot(db, course)
    return course, course_snapshot, licenses, _course_provenance(course_snapshot, licenses)


def _resource_market_snapshot(db: Any, actor: DBUser, source_object_id: str) -> tuple[DBCourse, str, dict[str, Any], dict[str, Any]]:
    artifact = db.get(DBArtifact, source_object_id)
    if artifact is None: _fail("marketplace_resource_unknown", "resource does not exist")
    if artifact.owner_public_id != actor.public_id: _fail("marketplace_forbidden", "resource belongs to another owner")
    if artifact.status in {"archived", "withdrawn"} or not artifact.current_version_id:
        _fail("marketplace_resource_unavailable", "resource has no available current version")
    version = db.get(DBArtifactVersion, artifact.current_version_id)
    if version is None or version.artifact_id != artifact.id:
        _fail("marketplace_resource_version_unknown", "resource current version does not exist")
    course, course_snapshot, licenses, provenance = _course_for_object(db, artifact.course_id)
    resource_type = canonical_resource_type(artifact.artifact_type, version.metadata_json or {})
    preview = {
        "kind": "resource", "resource_type": resource_type, "title": artifact.title,
        "summary": _safe_excerpt(version.content, resource_type), "content_format": version.content_format,
        "included_items": [{"type": resource_type, "title": artifact.title}],
    }
    snapshot = {
        "schema_version": "f9.marketplace-learning-object.v1", "item_type": "resource",
        "source": {"object_id": artifact.id, "version_id": version.id},
        "course_snapshot": course_snapshot,
        "object": {
            "artifact": {"artifact_type": artifact.artifact_type, "title": artifact.title, "status": artifact.status},
            "version": {"content": version.content, "content_format": version.content_format,
                "content_hash": version.content_hash, "metadata": _safe_metadata(version.metadata_json or {})},
        },
        "preview": preview, "provenance": provenance,
    }
    return course, version.id, snapshot, licenses


def _bundle_market_snapshot(db: Any, actor: DBUser, source_object_id: str) -> tuple[DBCourse, str, dict[str, Any], dict[str, Any]]:
    bundle = db.get(DBResourceBundle, source_object_id)
    if bundle is None: _fail("marketplace_resource_bundle_unknown", "resource bundle does not exist")
    if bundle.owner_public_id != actor.public_id: _fail("marketplace_forbidden", "resource bundle belongs to another owner")
    if bundle.status != "active" or not bundle.current_version_id:
        _fail("marketplace_resource_bundle_unavailable", "resource bundle has no available current version")
    version = db.get(DBResourceBundleVersion, bundle.current_version_id)
    if version is None or version.bundle_id != bundle.id:
        _fail("marketplace_resource_bundle_version_unknown", "resource bundle current version does not exist")
    course, course_snapshot, licenses, provenance = _course_for_object(db, bundle.course_id)
    items = []
    for row in db.query(DBResourceBundleItem).filter_by(bundle_version_id=version.id).order_by(DBResourceBundleItem.position).all():
        reference = None
        artifact = db.get(DBArtifact, row.resource_id)
        artifact_version = db.get(DBArtifactVersion, row.resource_version_id)
        if artifact is not None and artifact.owner_public_id == actor.public_id and artifact_version is not None and artifact_version.artifact_id == artifact.id:
            reference = {
                "kind": "artifact",
                "artifact": {"artifact_type": artifact.artifact_type, "title": artifact.title, "status": artifact.status},
                "version": {"content": artifact_version.content, "content_format": artifact_version.content_format,
                    "content_hash": artifact_version.content_hash, "metadata": _safe_metadata(artifact_version.metadata_json or {})},
            }
        items.append({
            "position": row.position, "resource_type": row.resource_type,
            "resource_id": row.resource_id, "resource_version_id": row.resource_version_id,
            "frozen_snapshot": copy.deepcopy(row.frozen_snapshot or {}), "reference": reference,
        })
    preview_items = [{"type": item["resource_type"], "title": str(item["frozen_snapshot"].get("title") or item["resource_type"])} for item in items]
    snapshot = {
        "schema_version": "f9.marketplace-learning-object.v1", "item_type": "resource_bundle",
        "source": {"object_id": bundle.id, "version_id": version.id},
        "course_snapshot": course_snapshot,
        "object": {
            "bundle": {"title": bundle.title, "learning_objective": bundle.learning_objective, "status": bundle.status},
            "version": {"quality_summary": copy.deepcopy(version.quality_summary or {}),
                "content_hash": version.content_hash, "change_summary": version.change_summary},
            "items": items,
        },
        "preview": {"kind": "resource_bundle", "title": bundle.title, "summary": bundle.learning_objective,
            "item_count": len(items), "included_items": preview_items},
        "provenance": provenance,
    }
    return course, version.id, snapshot, licenses


def _path_market_snapshot(db: Any, actor: DBUser, source_object_id: str) -> tuple[DBCourse, str, dict[str, Any], dict[str, Any]]:
    path = db.get(DBLearningPath, source_object_id)
    if path is None: _fail("marketplace_learning_path_unknown", "learning path does not exist")
    if path.owner_public_id != actor.public_id: _fail("marketplace_forbidden", "learning path belongs to another owner")
    if path.status == "archived": _fail("marketplace_learning_path_unavailable", "archived learning path cannot be published")
    version = db.get(DBPlanVersion, path.source_plan_version_id)
    plan = db.get(DBPlanDraft, version.plan_draft_id) if version else None
    if version is None or plan is None or plan.owner_public_id != actor.public_id:
        _fail("marketplace_learning_path_version_unknown", "learning path source version does not exist")
    course, course_snapshot, licenses, provenance = _course_for_object(db, path.course_id)
    nodes = db.query(DBPathNode).filter_by(learning_path_id=path.id).order_by(DBPathNode.sequence).all()
    node_snapshots = [{
        "node_key": row.node_key, "sequence": row.sequence, "node_type": row.node_type,
        "target_object_id": row.target_object_id, "title": row.title,
        "prerequisites": copy.deepcopy(row.prerequisites or []), "is_extension": row.is_extension,
        "resource_status": row.resource_status, "estimate_min_minutes": row.estimate_min_minutes,
        "estimate_max_minutes": row.estimate_max_minutes,
    } for row in nodes]
    snapshot = {
        "schema_version": "f9.marketplace-learning-object.v1", "item_type": "learning_path",
        "source": {"object_id": path.id, "version_id": version.id},
        "course_snapshot": course_snapshot,
        "object": {
            "plan": {"title": plan.title, "content": copy.deepcopy(version.content or {}), "content_hash": version.content_hash},
            "path": {"status": path.status, "nodes": node_snapshots},
        },
        "preview": {"kind": "learning_path", "title": plan.title,
            "summary": str((version.content or {}).get("goal") or "按顺序完成学习路径中的任务。"),
            "node_count": len(nodes), "estimated_minutes": sum(row.estimate_max_minutes for row in nodes),
            "included_items": [{"type": row.node_type, "title": row.title} for row in nodes[:8]]},
        "provenance": provenance,
    }
    return course, version.id, snapshot, licenses


def _learning_object_snapshot(db: Any, actor: DBUser, item_type: str, source_object_id: str) -> tuple[DBCourse, str, dict[str, Any], dict[str, Any]]:
    if item_type == "resource": return _resource_market_snapshot(db, actor, source_object_id)
    if item_type == "resource_bundle": return _bundle_market_snapshot(db, actor, source_object_id)
    if item_type == "learning_path": return _path_market_snapshot(db, actor, source_object_id)
    _fail("marketplace_item_type_invalid", "unsupported marketplace item type")


def submit_listing(db: Any, *, actor: DBUser, title: str, summary: str, category: str, tags: list[str],
                   item_type: str = "course", course_id: str | None = None,
                   source_object_id: str | None = None, source_version_id: str | None = None) -> dict[str, Any]:
    if item_type not in MARKETPLACE_ITEM_TYPES: _fail("marketplace_item_type_invalid", "unsupported marketplace item type")
    if item_type == "course":
        if normalize_role(actor.role) not in {"teacher", "admin"}:
            _fail("marketplace_forbidden", "course marketplace submission requires a teacher or administrator")
        if not course_id: _fail("marketplace_course_required", "course id is required")
        course = db.get(DBCourse, course_id)
        if course is None: _fail("marketplace_course_unknown", "course does not exist")
        require_manager(db, course.id, actor)
        from course_catalog import course_is_selectable
        if not course_is_selectable(db, course): _fail("marketplace_course_not_published", "only a published course with usable material can enter marketplace review")
        snapshot, licenses = _snapshot(db, course)
        actual_source_object_id, actual_source_version_id = course.id, course.version
        provenance = _course_provenance(snapshot, licenses)
    else:
        if normalize_role(actor.role) not in {"student", "teacher", "admin"}:
            _fail("marketplace_forbidden", "marketplace submission is unavailable for this role")
        if not source_object_id: _fail("marketplace_source_required", "a personal learning object is required")
        course, actual_source_version_id, snapshot, licenses = _learning_object_snapshot(db, actor, item_type, source_object_id)
        actual_source_object_id = source_object_id
        provenance = snapshot["provenance"]
        if course_id and course_id != course.id: _fail("marketplace_course_conflict", "source object belongs to another course")
    if source_version_id and source_version_id != actual_source_version_id:
        _fail("marketplace_source_version_conflict", "source object changed; refresh before publishing")
    _require_complete_provenance(provenance)
    digest = _hash({"item_type": item_type, "snapshot": snapshot, "licenses": licenses})
    existing = db.query(DBMarketplaceListing).filter_by(
        item_type=item_type, source_object_id=actual_source_object_id,
        source_version_id=actual_source_version_id, snapshot_hash=digest,
        owner_public_id=actor.public_id,
    ).first()
    if existing: return listing_payload(db, existing, actor)
    row = DBMarketplaceListing(course_id=course.id, course_version=course.version, item_type=item_type,
        source_object_id=actual_source_object_id, source_version_id=actual_source_version_id,
        title=title.strip(), summary=summary.strip(), category=category.strip(),
        tags=sorted(set(x.strip() for x in tags if x.strip())), snapshot_data=snapshot,
        license_snapshot=licenses, snapshot_hash=digest, owner_public_id=actor.public_id)
    db.add(row); db.flush(); _decision(db, row, actor, "submit", "pending", "submitted for public marketplace review", {"snapshot_hash": digest})
    return listing_payload(db, row, actor)


def _decision(db: Any, listing: DBMarketplaceListing, actor: DBUser, action: str, status: str, reason: str, evidence: dict[str, Any]) -> None:
    before = listing.status
    db.add(DBMarketplaceDecision(listing_id=listing.id, action=action, from_status=before, to_status=status,
        actor_public_id=actor.public_id, actor_role=normalize_role(actor.role), reason=reason.strip(), reason_sha256=_hash(reason.strip()),
        evidence_snapshot=evidence))
    listing.status = status; listing.lock_version += 1
    if status == "published": listing.published_at = _now()
    if status == "withdrawn": listing.withdrawn_at = _now()
    _audit(db, actor, f"marketplace.{action}", "marketplace_listing", listing.id,
        {"from_status": before, "to_status": status, "reason_sha256": _hash(reason.strip()), **evidence})


def review_listing(db: Any, *, actor: DBUser, listing_id: str, action: str, reason: str, expected_version: int,
                   impact_kind: str | None = None) -> dict[str, Any]:
    _admin(actor); row = _listing(db, listing_id)
    if row.lock_version != expected_version: _fail("marketplace_version_conflict", "marketplace listing has changed")
    rules = {"request_changes": ({"pending"}, "changes_requested"), "approve": ({"pending"}, "approved"),
             "publish": ({"approved"}, "published"), "withdraw": ({"published"}, "withdrawn")}
    allowed, target = rules[action]
    if row.status not in allowed: _fail("marketplace_transition_invalid", f"cannot {action} from {row.status}")
    if target == "published": _require_complete_provenance(_listing_provenance(row))
    open_reports = db.query(DBMarketplaceReport).filter_by(listing_id=row.id, status="open").count()
    _decision(db, row, actor, action, target, reason, {"open_report_count": open_reports, "snapshot_hash": row.snapshot_hash})
    if target == "withdrawn":
        db.query(DBMarketplaceAcquisition).filter_by(listing_id=row.id).update({"source_status": "withdrawn"})
        db.query(DBMarketplacePersonalCopy).filter_by(listing_id=row.id).update({"source_status": "withdrawn"})
        emit_marketplace_impact(db, actor=actor, source=row, impact_type="withdrawn", reason=reason)
    elif target == "published":
        previous = db.query(DBMarketplaceListing).filter(
            DBMarketplaceListing.course_id == row.course_id, DBMarketplaceListing.id != row.id,
            DBMarketplaceListing.published_at.isnot(None),
        ).order_by(DBMarketplaceListing.published_at.desc()).first()
        if previous:
            changed_license = _canonical(previous.license_snapshot) != _canonical(row.license_snapshot)
            kind = "license_changed" if changed_license else (impact_kind or "new_version")
            emit_marketplace_impact(db, actor=actor, source=previous, target=row, impact_type=kind, reason=reason)
    return listing_payload(db, row, actor)


def _personal_copy(db: Any, row: DBMarketplaceListing, actor: DBUser | None) -> DBMarketplacePersonalCopy | None:
    if actor is None or row.item_type not in MARKETPLACE_LEARNING_OBJECT_TYPES: return None
    return db.query(DBMarketplacePersonalCopy).filter_by(listing_id=row.id, recipient_public_id=actor.public_id).first()


def _saved_state(db: Any, row: DBMarketplaceListing, actor: DBUser | None) -> dict[str, Any] | None:
    if actor is None: return None
    if row.item_type == "course":
        acquired = db.query(DBMarketplaceAcquisition).filter_by(listing_id=row.id, recipient_public_id=actor.public_id).first()
        if acquired is None: return None
        return {"id": acquired.id, "source_status": acquired.source_status,
            "open_route": f"/knowledge/courses/{acquired.derived_course_id}", "item_type": "course"}
    personal = _personal_copy(db, row, actor)
    if personal is None: return None
    return {"id": personal.id, "source_status": personal.source_status,
        "open_route": personal.open_route, "item_type": personal.item_type}


def _public_preview(row: DBMarketplaceListing) -> dict[str, Any]:
    if row.item_type in MARKETPLACE_LEARNING_OBJECT_TYPES:
        return _safe_metadata(copy.deepcopy((row.snapshot_data or {}).get("preview") or {}))
    snapshot = row.snapshot_data or {}
    course = snapshot.get("course") or {}
    documents = snapshot.get("documents") or []
    return {"kind": "course", "title": row.title, "summary": row.summary,
        "document_count": len(documents), "included_items": [
            {"type": "document", "title": str(item.get("title") or item.get("filename") or "课程文档")}
            for item in documents[:8]
        ], "course_title": str(course.get("title") or "")}


def public_search(db: Any, *, query: str = "", category: str = "", tag: str = "",
                  item_type: str = "", actor: DBUser | None = None) -> list[dict[str, Any]]:
    rows = db.query(DBMarketplaceListing).filter_by(status="published").order_by(DBMarketplaceListing.published_at.desc()).all()
    needle = query.strip().casefold(); category = category.strip().casefold(); tag = tag.strip().casefold(); item_type = item_type.strip()
    if item_type and item_type not in MARKETPLACE_ITEM_TYPES: _fail("marketplace_item_type_invalid", "unsupported marketplace item type")
    result = []
    for row in rows:
        if item_type and row.item_type != item_type: continue
        if needle and needle not in f"{row.title} {row.summary} {row.category} {' '.join(row.tags or [])}".casefold(): continue
        if category and row.category.casefold() != category: continue
        if tag and tag not in {x.casefold() for x in row.tags or []}: continue
        result.append(public_payload(row, engagement_summary(db, row, actor), _saved_state(db, row, actor)))
    return result


def public_payload(row: DBMarketplaceListing, engagement: dict[str, Any] | None = None,
                   saved_copy: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": row.id, "item_type": row.item_type, "course_version": row.course_version,
        "title": row.title, "summary": row.summary,
        "category": row.category, "tags": row.tags or [], "status": row.status, "snapshot_hash": row.snapshot_hash,
        "author": {"public_id": row.owner_public_id}, "preview": _public_preview(row),
        "provenance": _listing_provenance(row), "saved_copy": copy.deepcopy(saved_copy),
        "license": {"course_license": row.license_snapshot.get("course_license", ""), "course_origin": row.license_snapshot.get("course_origin", ""),
                    "legal_review_state": row.license_snapshot.get("legal_review_state", "not_automatically_determined")},
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "engagement": engagement or {"favorite_count": 0, "review_count": 0, "average_rating": None, "minimum_sample": 3, "sample_state": "insufficient"}}


def listing_payload(db: Any, row: DBMarketplaceListing, actor: DBUser) -> dict[str, Any]:
    if normalize_role(actor.role) != "admin" and row.owner_public_id != actor.public_id and row.status != "published":
        _fail("marketplace_forbidden", "marketplace listing is not visible")
    decisions = db.query(DBMarketplaceDecision).filter_by(listing_id=row.id).order_by(DBMarketplaceDecision.created_at).all()
    reports = db.query(DBMarketplaceReport).filter_by(listing_id=row.id).order_by(DBMarketplaceReport.created_at.desc()).all()
    own_or_admin = normalize_role(actor.role) == "admin" or row.owner_public_id == actor.public_id
    return {**public_payload(row, engagement_summary(db, row, actor), _saved_state(db, row, actor)),
        "course_id": row.course_id, "source_object_id": row.source_object_id,
        "source_version_id": row.source_version_id, "owner_public_id": row.owner_public_id,
        "lock_version": row.lock_version, "report_count": len(reports), "open_report_count": sum(x.status == "open" for x in reports),
        "decisions": [{"id": x.id, "action": x.action, "from_status": x.from_status, "to_status": x.to_status,
            "actor_role": x.actor_role, "reason": x.reason, "created_at": x.created_at.isoformat()} for x in decisions] if own_or_admin else [],
        "reports": [report_payload(x) for x in reports] if normalize_role(actor.role) == "admin" else []}


def _publishable_sources(db: Any, actor: DBUser) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {item_type: [] for item_type in MARKETPLACE_LEARNING_OBJECT_TYPES}
    sources: list[tuple[str, str]] = []
    sources.extend(("resource", row.id) for row in db.query(DBArtifact).filter_by(owner_public_id=actor.public_id).filter(
        DBArtifact.current_version_id.isnot(None), DBArtifact.archived_at.is_(None)).order_by(DBArtifact.updated_at.desc()).all())
    sources.extend(("resource_bundle", row.id) for row in db.query(DBResourceBundle).filter_by(
        owner_public_id=actor.public_id, status="active").filter(DBResourceBundle.current_version_id.isnot(None)).order_by(DBResourceBundle.updated_at.desc()).all())
    sources.extend(("learning_path", row.id) for row in db.query(DBLearningPath).filter_by(
        owner_public_id=actor.public_id).filter(DBLearningPath.status != "archived").order_by(DBLearningPath.updated_at.desc()).all())
    for item_type, object_id in sources:
        try:
            course, version_id, snapshot, _licenses = _learning_object_snapshot(db, actor, item_type, object_id)
        except MarketplaceError:
            continue
        result[item_type].append({"id": object_id, "version_id": version_id,
            "title": str((snapshot.get("preview") or {}).get("title") or "未命名学习内容"),
            "course": {"id": course.id, "title": course.title, "version": course.version},
            "preview": _safe_metadata(snapshot.get("preview") or {}),
            "provenance": copy.deepcopy(snapshot.get("provenance") or {})})
    return result


def personal_copy_payload(row: DBMarketplacePersonalCopy, listing: DBMarketplaceListing | None = None) -> dict[str, Any]:
    return {"id": row.id, "listing_id": row.listing_id, "item_type": row.item_type,
        "copy_object_id": row.copy_object_id, "copy_version_id": row.copy_version_id,
        "open_route": row.open_route, "provenance": copy.deepcopy(row.provenance_snapshot or {}),
        "source_status": row.source_status, "created_at": row.created_at.isoformat() if row.created_at else None,
        "title": listing.title if listing else "", "summary": listing.summary if listing else "",
        "preview": _public_preview(listing) if listing else {}}


def workspace(db: Any, actor: DBUser) -> dict[str, Any]:
    from course_catalog import course_is_selectable
    published = public_search(db, actor=actor); managed = []
    for row in db.query(DBMarketplaceListing).order_by(DBMarketplaceListing.created_at.desc()).all():
        if normalize_role(actor.role) == "admin" or row.owner_public_id == actor.public_id: managed.append(listing_payload(db, row, actor))
    courses = []
    if normalize_role(actor.role) in {"teacher", "admin"}:
        for course in db.query(DBCourse).order_by(DBCourse.title).all():
            if not course_is_selectable(db, course):
                continue
            try: require_manager(db, course.id, actor); courses.append({"id": course.id, "title": course.title, "version": course.version})
            except Exception: pass
    personal_copies = db.query(DBMarketplacePersonalCopy).filter_by(recipient_public_id=actor.public_id).order_by(
        DBMarketplacePersonalCopy.created_at.desc()).all()
    return {"schema_version": "f9.marketplace-workspace.v1", "truth_label": "学习市场 · 发现并保存可学习内容",
        "disclaimer": "所有内容按发布时版本冻结；来源与许可可查，保存后形成独立个人副本。",
        "published": published, "managed": managed, "manageable_courses": courses,
        "publishable_sources": _publishable_sources(db, actor),
        "personal_copies": [personal_copy_payload(row, db.get(DBMarketplaceListing, row.listing_id)) for row in personal_copies],
        "is_admin": normalize_role(actor.role) == "admin"}


MARKETPLACE_RECOMMENDATION_ALGORITHM = "fc.marketplace-recommendation.v1"
MARKETPLACE_RECOMMENDATION_WEIGHTS = {
    "teaching_fit": 0.28,
    "difficulty_fit": 0.22,
    "license_traceability": 0.15,
    "quality_evidence": 0.15,
    "verified_use": 0.12,
    "recency": 0.06,
    "popularity": 0.02,
}


def _terms(values: list[str]) -> list[str]:
    terms: list[str] = []
    for value in values:
        normalized = re.sub(r"[^\w\u4e00-\u9fff]+", " ", str(value).casefold()).strip()
        for token in normalized.split():
            if len(token) >= 2 and token not in terms:
                terms.append(token)
    return terms[:40]


def _profile_context(db: Any, actor: DBUser) -> tuple[str | None, dict[str, Any], list[str]]:
    latest = db.query(DBProfileSnapshot).filter_by(owner_public_id=actor.public_id).order_by(DBProfileSnapshot.created_at.desc()).first()
    snapshot = copy.deepcopy(latest.snapshot or {}) if latest else {}
    missing: list[str] = []
    legacy = db.get(DBStudentProfile, actor.username)
    if legacy:
        snapshot.setdefault("target_course", legacy.target_course or "")
        snapshot.setdefault("knowledge_base", legacy.knowledge_base or "")
        snapshot.setdefault("learning_goals", list(legacy.learning_goals or []))
        snapshot.setdefault("weak_points", list(legacy.weak_points or []))
        snapshot.setdefault("cognitive_load", legacy.cognitive_load)
        snapshot.setdefault("major", legacy.major or "")
    if not latest:
        missing.append("当前用户没有规范画像快照，已使用兼容画像或中性先验")
    if not snapshot:
        missing.append("当前用户没有可用画像字段")
    return (latest.id if latest else None), snapshot, missing


def _difficulty_value(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0.0, min(1.0, float(value)))
    text = str(value or "").casefold()
    bands = {
        "beginner": 0.2, "basic": 0.25, "introductory": 0.25, "初级": 0.25, "入门": 0.2,
        "intermediate": 0.5, "medium": 0.5, "中级": 0.5,
        "advanced": 0.8, "expert": 0.9, "高级": 0.8, "进阶": 0.72,
        "l0-l1": 0.2, "l1-l2": 0.45, "l2-l4": 0.75,
    }
    for key, score in bands.items():
        if key in text:
            return score
    return None


def _nested_values(value: Any, keys: set[str]) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in keys:
                found.append(item)
            found.extend(_nested_values(item, keys))
    elif isinstance(value, list):
        for item in value:
            found.extend(_nested_values(item, keys))
    return found


def _profile_difficulty(profile: dict[str, Any], requested: float | None) -> tuple[float, str, bool]:
    if requested is not None:
        return max(0.0, min(1.0, float(requested))), "本次明确目标难度", True
    for key in ("target_difficulty", "difficulty", "difficulty_band", "knowledge_base"):
        score = _difficulty_value(profile.get(key))
        if score is not None:
            return score, f"画像字段 {key}", True
    load = _difficulty_value(profile.get("cognitive_load"))
    if load is not None:
        return max(0.15, min(0.85, 0.7 - load * 0.25)), "画像认知负荷保守推断", True
    return 0.5, "无难度画像，采用中性先验", False


def _listing_difficulty(row: DBMarketplaceListing) -> tuple[float, str, bool]:
    values = _nested_values(row.snapshot_data or {}, {"difficulty", "difficulty_band", "level", "target_level"})
    for value in values:
        score = _difficulty_value(value)
        if score is not None:
            return score, f"冻结课程字段 {value}", True
    text_score = _difficulty_value(" ".join([row.title, row.summary, *list(row.tags or [])]))
    if text_score is not None:
        return text_score, "市场标题/摘要明确难度", True
    return 0.5, "冻结课程未声明难度，采用中性先验", False


def _listing_quality(db: Any, row: DBMarketplaceListing) -> tuple[float, dict[str, Any], bool]:
    snapshot = row.snapshot_data or {}
    documents = list(snapshot.get("documents") or [])
    sources = list(snapshot.get("sources") or [])
    ready_sources = sum(str(item.get("processing_status", "ready")) == "ready" for item in sources)
    source_ratio = ready_sources / len(sources) if sources else 0.0
    hashed_docs = sum(bool(item.get("content_hash")) for item in documents)
    document_ratio = hashed_docs / len(documents) if documents else 0.0
    checks = db.query(DBQualityCheck).join(DBArtifactVersion, DBQualityCheck.artifact_version_id == DBArtifactVersion.id).join(
        DBArtifact, DBArtifactVersion.artifact_id == DBArtifact.id).filter(DBArtifact.course_id == row.course_id).all()
    passed = sum(item.status in {"passed", "pass", "approved"} for item in checks)
    check_ratio = passed / len(checks) if checks else None
    score = 0.55 * source_ratio + 0.45 * document_ratio
    if check_ratio is not None:
        score = 0.55 * score + 0.45 * check_ratio
    evidence = {"source_count": len(sources), "ready_source_count": ready_sources,
        "document_count": len(documents), "hashed_document_count": hashed_docs,
        "quality_check_count": len(checks), "passed_quality_check_count": passed,
        "boundary": "质量检查仅计入与课程生成物版本真实关联的记录；来源完整性不等于专家质量认证。"}
    return round(score, 6), evidence, bool(sources or documents or checks)


def _license_score(row: DBMarketplaceListing) -> tuple[float, dict[str, Any], bool]:
    license_data = row.license_snapshot or {}
    documents = list(license_data.get("documents") or [])
    sources = list(license_data.get("sources") or [])
    fields = [bool(license_data.get("course_license")), bool(license_data.get("course_origin"))]
    fields.extend(bool(item.get("license_text")) and bool(item.get("content_hash")) for item in documents)
    fields.extend(bool(item.get("license_text")) and bool(item.get("source_sha256") or item.get("processed_sha256")) for item in sources)
    score = sum(fields) / len(fields) if fields else 0.0
    evidence = {"course_license_present": bool(license_data.get("course_license")),
        "course_origin_present": bool(license_data.get("course_origin")), "document_count": len(documents),
        "source_count": len(sources), "complete_units": sum(fields), "checked_units": len(fields),
        "legal_review_state": license_data.get("legal_review_state", "not_automatically_determined"),
        "boundary": "仅核对冻结许可证与来源字段完整性，不自动裁决法律兼容性。"}
    return round(score, 6), evidence, bool(fields)


def _usage_evidence(db: Any, row: DBMarketplaceListing) -> tuple[float, dict[str, Any]]:
    acquisitions = db.query(DBMarketplaceAcquisition).filter_by(listing_id=row.id).all()
    course_ids = [item.derived_course_id for item in acquisitions]
    event_count = db.query(DBLearningEvent).filter(DBLearningEvent.course_id.in_(course_ids)).count() if course_ids else 0
    reviews = db.query(DBMarketplaceReview).filter_by(listing_id=row.id, status="active").count()
    favorites = db.query(DBMarketplaceFavorite).filter_by(listing_id=row.id, status="active").count()
    use_score = min(1.0, 0.3 * min(len(acquisitions), 3) / 3 + 0.45 * min(event_count, 10) / 10 + 0.25 * min(reviews, 3) / 3)
    return round(use_score, 6), {"acquisition_count": len(acquisitions), "learning_event_count": event_count,
        "verified_review_count": reviews, "favorite_count": favorites,
        "boundary": "获取、学习事件与使用后评价分别计数；收藏不作为真实使用证据。"}


def _feature(label: str, score: float, weight: float, evidence: dict[str, Any], available: bool = True) -> dict[str, Any]:
    return {"label": label, "score": round(score, 6), "weight": weight,
        "contribution": round(score * weight, 6), "evidence_available": available, "evidence": evidence}


def _recommendation_inputs(db: Any, actor: DBUser, *, learning_goals: list[str], topics: list[str], target_difficulty: float | None) -> dict[str, Any]:
    profile_id, profile, profile_missing = _profile_context(db, actor)
    inherited_goals = list(profile.get("learning_goals") or []) + list(profile.get("weak_points") or [])
    target = {"learning_goals": [str(x).strip() for x in (learning_goals or inherited_goals) if str(x).strip()][:20],
        "topics": [str(x).strip() for x in topics if str(x).strip()][:20], "target_difficulty": target_difficulty}
    listings = db.query(DBMarketplaceListing).filter_by(status="published").order_by(DBMarketplaceListing.id).all()
    evidence_version = []
    for row in listings:
        engagement = _usage_evidence(db, row)[1]
        quality = _listing_quality(db, row)[1]
        evidence_version.append({"listing_id": row.id, "snapshot_hash": row.snapshot_hash,
            "published_at": row.published_at.isoformat() if row.published_at else None,
            "quality_check_count": quality["quality_check_count"],
            "passed_quality_check_count": quality["passed_quality_check_count"], **engagement})
    evaluation_date = _now().date().isoformat()
    frozen_input = {"algorithm": MARKETPLACE_RECOMMENDATION_ALGORITHM, "evaluation_date": evaluation_date, "profile_id": profile_id,
        "profile": profile, "target": target, "weights": MARKETPLACE_RECOMMENDATION_WEIGHTS,
        "listings": evidence_version}
    return {"profile_id": profile_id, "profile": profile, "profile_missing": profile_missing,
        "target": target, "listings": listings, "evidence_version": evidence_version,
        "evaluation_date": evaluation_date, "input_hash": _hash(frozen_input)}


def _recommendation_result(db: Any, row: DBMarketplaceListing, *, profile: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    target_terms = _terms(list(target["learning_goals"]) + list(target["topics"]) + [profile.get("target_course", ""), profile.get("major", "")])
    listing_text = " ".join([row.title, row.summary, row.category, *list(row.tags or []), _canonical(row.snapshot_data.get("course", {}).get("manifest_data", {}))]).casefold()
    matched = [term for term in target_terms if term in listing_text]
    teaching_available = bool(target_terms)
    teaching_score = len(matched) / len(target_terms) if target_terms else 0.5
    profile_difficulty, profile_basis, profile_difficulty_available = _profile_difficulty(profile, target.get("target_difficulty"))
    resource_difficulty, resource_basis, resource_difficulty_available = _listing_difficulty(row)
    difficulty_score = max(0.0, 1.0 - abs(profile_difficulty - resource_difficulty) / 0.6)
    license_value, license_evidence, license_available = _license_score(row)
    quality_value, quality_evidence, quality_available = _listing_quality(db, row)
    usage_value, usage_evidence = _usage_evidence(db, row)
    age_days = max(0, (_now() - row.published_at).days) if row.published_at else 3650
    recency_value = max(0.0, math.exp(-age_days / 540))
    popularity_value = min(1.0, math.log1p(usage_evidence["favorite_count"]) / math.log(11))
    features = {
        "teaching_fit": _feature("教学目标与主题适配", teaching_score, MARKETPLACE_RECOMMENDATION_WEIGHTS["teaching_fit"],
            {"target_terms": target_terms, "matched_terms": matched}, teaching_available),
        "difficulty_fit": _feature("画像与难度适配", difficulty_score, MARKETPLACE_RECOMMENDATION_WEIGHTS["difficulty_fit"],
            {"target_difficulty": round(profile_difficulty, 4), "target_basis": profile_basis,
             "resource_difficulty": round(resource_difficulty, 4), "resource_basis": resource_basis},
            profile_difficulty_available and resource_difficulty_available),
        "license_traceability": _feature("许可证与来源完整性", license_value, MARKETPLACE_RECOMMENDATION_WEIGHTS["license_traceability"], license_evidence, license_available),
        "quality_evidence": _feature("可核验质量证据", quality_value, MARKETPLACE_RECOMMENDATION_WEIGHTS["quality_evidence"], quality_evidence, quality_available),
        "verified_use": _feature("真实使用证据", usage_value, MARKETPLACE_RECOMMENDATION_WEIGHTS["verified_use"], usage_evidence, bool(usage_evidence["acquisition_count"] or usage_evidence["learning_event_count"] or usage_evidence["verified_review_count"])),
        "recency": _feature("更新时间", recency_value, MARKETPLACE_RECOMMENDATION_WEIGHTS["recency"], {"published_at": row.published_at.isoformat() if row.published_at else None, "age_days": age_days}, bool(row.published_at)),
        "popularity": _feature("收藏热度（辅助）", popularity_value, MARKETPLACE_RECOMMENDATION_WEIGHTS["popularity"], {"favorite_count": usage_evidence["favorite_count"], "boundary": "热度权重固定为最低 2%，不能替代教学与难度适配。"}, True),
    }
    total = round(sum(item["contribution"] for item in features.values()), 6)
    evidence_weight = sum(item["weight"] for item in features.values() if item["evidence_available"])
    confidence = round(evidence_weight, 6)
    missing = [f"{item['label']}缺少直接证据" for item in features.values() if not item["evidence_available"]]
    unsuitable: list[str] = []
    if teaching_available and teaching_score < 0.25: unsuitable.append("与当前学习目标或主题重合较少")
    if difficulty_score < 0.45: unsuitable.append("课程难度与当前画像目标差距较大")
    if license_value < 0.5: unsuitable.append("许可证或来源字段不完整，使用前需要人工复核")
    if confidence < 0.6: unsuitable.append("可用于判断的直接证据不足")
    if license_value < 0.25:
        suitability = "not_applicable"
    elif total >= 0.72 and teaching_score >= 0.45 and difficulty_score >= 0.55:
        suitability = "recommended"
    elif total >= 0.52:
        suitability = "consider"
    else:
        suitability = "limited"
    reasons = []
    if matched: reasons.append(f"匹配学习目标/主题：{'、'.join(matched[:5])}")
    if difficulty_score >= 0.7: reasons.append("课程难度与当前目标区间接近")
    if license_value >= 0.75: reasons.append("许可证与来源字段较完整")
    if usage_evidence["learning_event_count"]: reasons.append(f"已有 {usage_evidence['learning_event_count']} 条真实学习事件")
    if not reasons: reasons.append("当前仅具备有限适配证据，建议先查看课程详情")
    return {"listing": {"id": row.id, "title": row.title, "summary": row.summary, "category": row.category,
            "tags": list(row.tags or []), "course_version": row.course_version, "snapshot_hash": row.snapshot_hash,
            "license": public_payload(row)["license"], "published_at": row.published_at.isoformat() if row.published_at else None},
        "total_score": total, "confidence": confidence, "suitability": suitability, "features": features,
        "recommendation_reasons": reasons, "unsuitable_reasons": unsuitable,
        "evidence_state": {"missing_evidence": missing, "usage": usage_evidence,
            "boundary": "确定性比赛推荐，不调用外部模型；分数是系统适配建议，不是专家认证或教学质量结论。"}}


def _recommendation_payload(db: Any, run: DBMarketplaceRecommendationRun, actor: DBUser) -> dict[str, Any]:
    if run.owner_public_id != actor.public_id:
        _fail("marketplace_recommendation_forbidden", "recommendation run belongs to another user")
    rows = db.query(DBMarketplaceRecommendationResult).filter_by(run_id=run.id).order_by(DBMarketplaceRecommendationResult.rank).all()
    return {"schema_version": "fc.marketplace-recommendation-run.v1", "id": run.id,
        "algorithm_version": run.algorithm_version, "profile_snapshot_id": run.profile_snapshot_id,
        "profile_snapshot": run.profile_snapshot, "target_snapshot": run.target_snapshot,
        "weights": run.weights_snapshot, "run_evidence": run.evidence_snapshot,
        "input_hash": run.input_hash, "result_count": run.result_count,
        "created_at": run.created_at.isoformat(),
        "truth_label": "系统可解释适配建议 · 非专家认证",
        "boundary": "热度固定为最低权重；数据不足会降低置信度并逐项标出。",
        "items": [{"id": item.id, "rank": item.rank, "total_score": item.total_score,
            "confidence": item.confidence, "suitability": item.suitability,
            "listing": item.evidence_state.get("listing", {}), "features": item.feature_contributions,
            "recommendation_reasons": item.recommendation_reasons,
            "unsuitable_reasons": item.unsuitable_reasons,
            "evidence_state": {key: value for key, value in item.evidence_state.items() if key != "listing"}}
            for item in rows]}


def run_marketplace_recommendation(db: Any, *, actor: DBUser, learning_goals: list[str], topics: list[str], target_difficulty: float | None) -> dict[str, Any]:
    inputs = _recommendation_inputs(db, actor, learning_goals=learning_goals, topics=topics, target_difficulty=target_difficulty)
    existing = db.query(DBMarketplaceRecommendationRun).filter_by(owner_public_id=actor.public_id,
        algorithm_version=MARKETPLACE_RECOMMENDATION_ALGORITHM, input_hash=inputs["input_hash"]).first()
    if existing:
        return _recommendation_payload(db, existing, actor)
    scored = [_recommendation_result(db, row, profile=inputs["profile"], target=inputs["target"]) for row in inputs["listings"]]
    scored.sort(key=lambda item: (-item["total_score"], -item["confidence"], item["listing"]["id"]))
    run = DBMarketplaceRecommendationRun(owner_public_id=actor.public_id, algorithm_version=MARKETPLACE_RECOMMENDATION_ALGORITHM,
        profile_snapshot_id=inputs["profile_id"], profile_snapshot=inputs["profile"], target_snapshot=inputs["target"],
        weights_snapshot=MARKETPLACE_RECOMMENDATION_WEIGHTS, evidence_snapshot={"profile_missing": inputs["profile_missing"],
            "evaluation_date": inputs["evaluation_date"], "published_listing_evidence": inputs["evidence_version"]},
        input_hash=inputs["input_hash"], result_count=len(scored))
    db.add(run); db.flush()
    for rank, result in enumerate(scored, 1):
        db.add(DBMarketplaceRecommendationResult(run_id=run.id, listing_id=result["listing"]["id"],
            listing_snapshot_hash=result["listing"]["snapshot_hash"], rank=rank, total_score=result["total_score"],
            confidence=result["confidence"], suitability=result["suitability"], feature_contributions=result["features"],
            recommendation_reasons=result["recommendation_reasons"], unsuitable_reasons=result["unsuitable_reasons"],
            evidence_state={**result["evidence_state"], "listing": result["listing"]}))
    db.flush(); _audit(db, actor, "marketplace.recommendation.created", "marketplace_recommendation_run", run.id,
        {"algorithm_version": MARKETPLACE_RECOMMENDATION_ALGORITHM, "input_hash": inputs["input_hash"], "result_count": len(scored)})
    return _recommendation_payload(db, run, actor)


def get_marketplace_recommendation(db: Any, *, actor: DBUser, run_id: str | None = None) -> dict[str, Any]:
    if run_id:
        run = db.get(DBMarketplaceRecommendationRun, run_id)
        if run is None: _fail("marketplace_recommendation_unknown", "recommendation run does not exist")
    else:
        run = db.query(DBMarketplaceRecommendationRun).filter_by(owner_public_id=actor.public_id).order_by(DBMarketplaceRecommendationRun.created_at.desc()).first()
        if run is None:
            return {"schema_version": "fc.marketplace-recommendation-run.v1", "items": [], "truth_label": "系统可解释适配建议 · 非专家认证", "boundary": "尚未生成推荐运行。"}
    return _recommendation_payload(db, run, actor)


def create_report(db: Any, *, actor: DBUser, listing_id: str, category: str, description: str) -> dict[str, Any]:
    row = _listing(db, listing_id)
    if row.status != "published": _fail("marketplace_listing_unavailable", "only a published listing can be reported")
    evidence = {"listing_id": row.id, "snapshot_hash": row.snapshot_hash, "course_version": row.course_version,
        "title": row.title, "license": row.license_snapshot, "reported_status": row.status}
    report = DBMarketplaceReport(listing_id=row.id, reporter_public_id=actor.public_id, category=category,
        description=description.strip(), evidence_snapshot=evidence, evidence_hash=_hash(evidence))
    db.add(report); db.flush(); _audit(db, actor, "marketplace.reported", "marketplace_report", report.id,
        {"listing_id": row.id, "category": category, "evidence_hash": report.evidence_hash})
    return report_payload(report)


def report_payload(row: DBMarketplaceReport) -> dict[str, Any]:
    return {"id": row.id, "listing_id": row.listing_id, "reporter_public_id": row.reporter_public_id,
        "category": row.category, "description": row.description, "evidence_hash": row.evidence_hash,
        "status": row.status, "lock_version": row.lock_version, "created_at": row.created_at.isoformat() if row.created_at else None}


def decide_report(db: Any, *, actor: DBUser, report_id: str, action: str, reason: str, expected_version: int) -> dict[str, Any]:
    _admin(actor); report = db.get(DBMarketplaceReport, report_id)
    if report is None: _fail("marketplace_report_unknown", "marketplace report does not exist")
    if report.lock_version != expected_version: _fail("marketplace_version_conflict", "marketplace report has changed")
    if report.status != "open": _fail("marketplace_report_resolved", "marketplace report is already resolved")
    listing = _listing(db, report.listing_id)
    if action == "dismiss": report.status = "dismissed"
    elif action == "withdraw":
        report.status = "resolved"
        if listing.status == "published":
            _decision(db, listing, actor, "withdraw", "withdrawn", reason,
                {"report_id": report.id, "report_evidence_hash": report.evidence_hash})
            db.query(DBMarketplaceAcquisition).filter_by(listing_id=listing.id).update({"source_status": "withdrawn"})
            db.query(DBMarketplacePersonalCopy).filter_by(listing_id=listing.id).update({"source_status": "withdrawn"})
            emit_marketplace_impact(db, actor=actor, source=listing, impact_type="withdrawn", reason=reason)
    else: _fail("marketplace_action_invalid", "report action must be dismiss or withdraw")
    report.lock_version += 1; report.resolved_at = _now()
    _audit(db, actor, f"marketplace.report_{action}", "marketplace_report", report.id,
        {"listing_id": listing.id, "reason_sha256": _hash(reason.strip()), "listing_status": listing.status})
    return report_payload(report)


def get_listing(db: Any, *, actor: DBUser, listing_id: str) -> dict[str, Any]:
    return listing_payload(db, _listing(db, listing_id), actor)


def _create_personal_course(db: Any, actor: DBUser, listing: DBMarketplaceListing) -> DBCourse:
    snapshot = listing.snapshot_data if listing.item_type == "course" else (listing.snapshot_data or {}).get("course_snapshot")
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("course"), dict):
        _fail("marketplace_snapshot_invalid", "listing does not contain a frozen course context")
    course_id = _stable("market-course", listing.id, actor.public_id)
    existing = db.get(DBCourse, course_id)
    if existing is not None:
        if existing.owner_public_id != actor.public_id: _fail("marketplace_copy_conflict", "recipient course identity already exists")
        return existing
    source = snapshot["course"]
    course = DBCourse(id=course_id, version=source["version"], title=f"{source['title']}（市场副本）", subject=source["subject"],
        description=source["description"], domain_pack=source["domain_pack"], language=source["language"], content_origin=source["content_origin"],
        license_text=listing.license_snapshot.get("course_license", ""), visibility="private", status="published", owner_public_id=actor.public_id,
        manifest_version=source["manifest_version"], manifest_data=source["manifest_data"])
    db.add(course); db.flush(); _apply_snapshot(db, course, snapshot, listing.license_snapshot, actor)
    course.title = f"{source['title']}（市场副本）"; course.visibility = "private"
    return course


def _clone_artifact(db: Any, actor: DBUser, listing: DBMarketplaceListing, course: DBCourse,
                    artifact_data: dict[str, Any], version_data: dict[str, Any], identity: str) -> tuple[DBArtifact, DBArtifactVersion]:
    artifact_id = _stable("market-art", listing.id, actor.public_id, identity)
    version_id = _stable("market-av", listing.id, actor.public_id, identity, str(version_data.get("content_hash") or ""))
    artifact = db.get(DBArtifact, artifact_id)
    version = db.get(DBArtifactVersion, version_id)
    if artifact is not None or version is not None: _fail("marketplace_copy_conflict", "recipient resource identity already exists")
    metadata = _safe_metadata(version_data.get("metadata") or {})
    metadata["marketplace_source"] = {"listing_id": listing.id, "listing_snapshot_hash": listing.snapshot_hash,
        "source_object_id": listing.source_object_id, "source_version_id": listing.source_version_id}
    artifact = DBArtifact(id=artifact_id, owner_public_id=actor.public_id, course_id=course.id,
        artifact_type=str(artifact_data.get("artifact_type") or "handout"),
        title=f"{str(artifact_data.get('title') or listing.title)}（个人副本）",
        status="approved", current_version_id=version_id)
    version = DBArtifactVersion(id=version_id, artifact_id=artifact.id, version_number=1,
        content=str(version_data.get("content") or ""), content_format=str(version_data.get("content_format") or "markdown"),
        content_hash=str(version_data.get("content_hash") or _hash(str(version_data.get("content") or ""))),
        metadata_json=metadata, created_by_public_id=actor.public_id)
    db.add(artifact); db.add(version); db.flush()
    return artifact, version


def _clone_resource(db: Any, actor: DBUser, listing: DBMarketplaceListing, course: DBCourse) -> tuple[str, str, str]:
    body = (listing.snapshot_data or {}).get("object") or {}
    artifact, version = _clone_artifact(db, actor, listing, course, body.get("artifact") or {}, body.get("version") or {}, "resource")
    resource_type = canonical_resource_type(artifact.artifact_type, version.metadata_json or {})
    route = resource_route(resource_type, artifact.id) or f"/workspace/resources?resource_id={artifact.id}"
    return artifact.id, version.id, route


def _clone_bundle(db: Any, actor: DBUser, listing: DBMarketplaceListing, course: DBCourse) -> tuple[str, str, str]:
    body = (listing.snapshot_data or {}).get("object") or {}
    bundle_data = body.get("bundle") or {}; version_data = body.get("version") or {}
    bundle_id = _stable("market-bundle", listing.id, actor.public_id)
    version_id = _stable("market-bundlever", listing.id, actor.public_id, str(version_data.get("content_hash") or ""))
    if db.get(DBResourceBundle, bundle_id) is not None or db.get(DBResourceBundleVersion, version_id) is not None:
        _fail("marketplace_copy_conflict", "recipient resource bundle identity already exists")
    bundle = DBResourceBundle(id=bundle_id, owner_public_id=actor.public_id, course_id=course.id,
        knowledge_point_id=None, title=f"{str(bundle_data.get('title') or listing.title)}（个人副本）",
        learning_objective=str(bundle_data.get("learning_objective") or listing.summary), current_version_id=version_id,
        status="active")
    version = DBResourceBundleVersion(id=version_id, bundle_id=bundle.id, version_number=1,
        profile_snapshot={"scope": "marketplace_copy", "publisher_profile_removed": True},
        quality_summary=copy.deepcopy(version_data.get("quality_summary") or {}),
        content_hash=str(version_data.get("content_hash") or _hash(body)),
        change_summary="从学习市场保存的独立个人副本", created_by_public_id=actor.public_id)
    db.add(bundle); db.add(version); db.flush()
    for item in body.get("items") or []:
        resource_id = str(item.get("resource_id") or "")
        resource_version_id = str(item.get("resource_version_id") or "")
        frozen = copy.deepcopy(item.get("frozen_snapshot") or {})
        reference = item.get("reference") or {}
        if reference.get("kind") == "artifact":
            cloned_artifact, cloned_version = _clone_artifact(
                db, actor, listing, course, reference.get("artifact") or {}, reference.get("version") or {},
                f"bundle:{int(item.get('position') or 0)}",
            )
            resource_id, resource_version_id = cloned_artifact.id, cloned_version.id
            canonical_type = canonical_resource_type(cloned_artifact.artifact_type, cloned_version.metadata_json or {})
            frozen.update({"title": cloned_artifact.title, "route": resource_route(canonical_type, cloned_artifact.id),
                "marketplace_copy_status": "independent_personal_copy"})
        else:
            frozen["marketplace_copy_status"] = "frozen_reference_only"
            frozen["marketplace_copy_notice"] = "该组成项保留发布时快照；当前没有可独立克隆的个人资源对象。"
        db.add(DBResourceBundleItem(bundle_version_id=version.id, position=int(item.get("position") or 0),
            resource_type=str(item.get("resource_type") or "handout"), resource_id=resource_id,
            resource_version_id=resource_version_id, frozen_snapshot=frozen))
    db.flush()
    return bundle.id, version.id, f"/workspace/resources/bundles/{bundle.id}?mode=personal-copy"


def _clone_learning_path(db: Any, actor: DBUser, listing: DBMarketplaceListing, course: DBCourse) -> tuple[str, str, str]:
    body = (listing.snapshot_data or {}).get("object") or {}
    plan_data = body.get("plan") or {}; path_data = body.get("path") or {}
    plan_id = _stable("market-plan", listing.id, actor.public_id)
    version_id = _stable("market-planver", listing.id, actor.public_id, str(plan_data.get("content_hash") or ""))
    path_id = _stable("market-path", listing.id, actor.public_id)
    if db.get(DBPlanDraft, plan_id) is not None or db.get(DBPlanVersion, version_id) is not None or db.get(DBLearningPath, path_id) is not None:
        _fail("marketplace_copy_conflict", "recipient learning path identity already exists")
    plan = DBPlanDraft(id=plan_id, owner_public_id=actor.public_id, course_id=course.id,
        title=f"{str(plan_data.get('title') or listing.title)}（个人副本）", status="confirmed",
        idempotency_key=f"marketplace-copy:{listing.id}:{actor.public_id}", current_version_id=version_id,
        confirmed_version_id=version_id, confirmed_at=_now())
    version = DBPlanVersion(id=version_id, plan_draft_id=plan.id, version_number=1, profile_snapshot_id=None,
        content=copy.deepcopy(plan_data.get("content") or {}),
        content_hash=str(plan_data.get("content_hash") or _hash(plan_data.get("content") or {})),
        created_by_public_id=actor.public_id)
    path = DBLearningPath(id=path_id, owner_public_id=actor.public_id, course_id=course.id,
        source_plan_version_id=version.id, status="active")
    db.add(plan); db.flush()
    db.add(version); db.flush()
    db.add(path); db.flush()
    for item in path_data.get("nodes") or []:
        db.add(DBPathNode(learning_path_id=path.id, node_key=str(item.get("node_key") or ""),
            sequence=int(item.get("sequence") or 1), node_type=str(item.get("node_type") or "chapter"),
            target_object_id=item.get("target_object_id"), title=str(item.get("title") or "学习任务"),
            status="pending", prerequisites=copy.deepcopy(item.get("prerequisites") or []),
            is_extension=bool(item.get("is_extension")), resource_status=str(item.get("resource_status") or "existing"),
            estimate_min_minutes=max(1, int(item.get("estimate_min_minutes") or 1)),
            estimate_max_minutes=max(1, int(item.get("estimate_max_minutes") or 1)),
            actual_minutes=None, blocked_reason=""))
    db.flush()
    return path.id, version.id, f"/workspace/path?path_id={path.id}"


def _acquire_course(db: Any, actor: DBUser, listing: DBMarketplaceListing) -> dict[str, Any]:
    existing = db.query(DBMarketplaceAcquisition).filter_by(listing_id=listing.id, recipient_public_id=actor.public_id).first()
    if existing: return acquisition_payload(existing)
    course = _create_personal_course(db, actor, listing)
    acquired = DBMarketplaceAcquisition(listing_id=listing.id, recipient_public_id=actor.public_id,
        derived_course_id=course.id, listing_snapshot_hash=listing.snapshot_hash)
    db.add(acquired); db.flush(); _audit(db, actor, "marketplace.acquired", "marketplace_acquisition", acquired.id,
        {"listing_id": listing.id, "derived_course_id": course.id, "snapshot_hash": listing.snapshot_hash})
    return acquisition_payload(acquired)


def acquire(db: Any, *, actor: DBUser, listing_id: str) -> dict[str, Any]:
    listing = _listing(db, listing_id)
    if listing.status != "published": _fail("marketplace_listing_unavailable", "listing is not available")
    if listing.item_type == "course": return _acquire_course(db, actor, listing)
    existing = _personal_copy(db, listing, actor)
    if existing: return personal_copy_payload(existing, listing)
    course = _create_personal_course(db, actor, listing)
    if listing.item_type == "resource": object_id, version_id, route = _clone_resource(db, actor, listing, course)
    elif listing.item_type == "resource_bundle": object_id, version_id, route = _clone_bundle(db, actor, listing, course)
    elif listing.item_type == "learning_path": object_id, version_id, route = _clone_learning_path(db, actor, listing, course)
    else: _fail("marketplace_item_type_invalid", "unsupported marketplace item type")
    personal = DBMarketplacePersonalCopy(listing_id=listing.id, recipient_public_id=actor.public_id,
        item_type=listing.item_type, copy_object_id=object_id, copy_version_id=version_id,
        open_route=route, listing_snapshot_hash=listing.snapshot_hash,
        provenance_snapshot=_listing_provenance(listing), source_status="available")
    db.add(personal); db.flush(); _audit(db, actor, "marketplace.personal_copy_created", "marketplace_personal_copy", personal.id,
        {"listing_id": listing.id, "item_type": listing.item_type, "copy_object_id": object_id,
            "copy_version_id": version_id, "snapshot_hash": listing.snapshot_hash})
    return personal_copy_payload(personal, listing)


def acquisition_payload(row: DBMarketplaceAcquisition) -> dict[str, Any]:
    return {"id": row.id, "listing_id": row.listing_id, "derived_course_id": row.derived_course_id,
        "recipient_public_id": row.recipient_public_id, "listing_snapshot_hash": row.listing_snapshot_hash,
        "source_status": row.source_status, "created_at": row.created_at.isoformat() if row.created_at else None}


_FORK_COURSE_FIELDS = {"title", "subject", "description", "domain_pack", "language", "content_origin", "manifest_version", "manifest_data"}
_FORK_DOCUMENT_FIELDS = {"title", "content", "tags", "status"}


def _fork(db: Any, fork_id: str) -> DBMarketplaceFork:
    row = db.get(DBMarketplaceFork, fork_id)
    if row is None: _fail("marketplace_fork_unknown", "marketplace fork does not exist")
    return row


def _require_fork_owner(row: DBMarketplaceFork, actor: DBUser) -> None:
    if row.owner_public_id != actor.public_id:
        _fail("marketplace_fork_forbidden", "marketplace fork belongs to another recipient")


def _fork_version(db: Any, row: DBMarketplaceFork) -> DBMarketplaceForkVersion:
    version = db.get(DBMarketplaceForkVersion, row.current_version_id) if row.current_version_id else None
    if version is None: _fail("marketplace_fork_version_unknown", "marketplace fork has no current version")
    return version


def _apply_fork_patch(snapshot: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(snapshot)
    course_patch = patch.get("course") or {}
    unknown = set(course_patch) - _FORK_COURSE_FIELDS
    if unknown: _fail("marketplace_fork_patch_invalid", f"unsupported course fields: {', '.join(sorted(unknown))}")
    for key, value in course_patch.items():
        if key == "manifest_data" and not isinstance(value, dict):
            _fail("marketplace_fork_patch_invalid", "manifest_data must be an object")
        if key != "manifest_data" and (not isinstance(value, str) or not value.strip()):
            _fail("marketplace_fork_patch_invalid", f"course.{key} must be a non-empty string")
        result["course"][key] = value.strip() if isinstance(value, str) else value
    documents = {item["filename"]: item for item in result.get("documents", [])}
    for document_patch in patch.get("documents") or []:
        filename = document_patch.get("filename", "")
        if filename not in documents: _fail("marketplace_fork_document_unknown", "fork document does not exist")
        unknown = set(document_patch) - ({"filename"} | _FORK_DOCUMENT_FIELDS)
        if unknown: _fail("marketplace_fork_patch_invalid", f"unsupported document fields: {', '.join(sorted(unknown))}")
        for key, value in document_patch.items():
            if key == "filename": continue
            if key == "tags":
                if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
                    _fail("marketplace_fork_patch_invalid", "document tags must be a string list")
                documents[filename][key] = sorted(set(x.strip() for x in value if x.strip()))
            elif key == "status":
                if value not in {"published", "withdrawn"}: _fail("marketplace_fork_patch_invalid", "document status is invalid")
                documents[filename][key] = value
            elif not isinstance(value, str): _fail("marketplace_fork_patch_invalid", f"document {key} must be text")
            else:
                documents[filename][key] = value
                if key == "content":
                    documents[filename]["content_hash"] = _hash(value)
                    documents[filename]["file_size"] = len(value.encode("utf-8"))
    return result


def _persist_fork_version(db: Any, *, fork: DBMarketplaceFork, actor: DBUser, snapshot: dict[str, Any],
                          summary: str, baseline_listing: DBMarketplaceListing,
                          inherited_license: dict[str, Any]) -> DBMarketplaceForkVersion:
    digest = _hash(snapshot)
    existing = db.query(DBMarketplaceForkVersion).filter_by(
        fork_id=fork.id, baseline_listing_id=baseline_listing.id, local_snapshot_hash=digest,
    ).first()
    if existing:
        fork.current_version_id = existing.id
        return existing
    latest = db.query(DBMarketplaceForkVersion).filter_by(fork_id=fork.id).order_by(DBMarketplaceForkVersion.version_number.desc()).first()
    version = DBMarketplaceForkVersion(
        fork_id=fork.id, version_number=(latest.version_number + 1 if latest else 1),
        parent_version_id=fork.current_version_id, baseline_listing_id=baseline_listing.id,
        baseline_snapshot_hash=baseline_listing.snapshot_hash, baseline_snapshot=baseline_listing.snapshot_data,
        inherited_license_snapshot=inherited_license, local_snapshot=snapshot, local_snapshot_hash=digest,
        modification_summary=summary.strip(), modification_summary_hash=_hash(summary.strip()),
        created_by_public_id=actor.public_id,
    )
    db.add(version); db.flush(); fork.current_version_id = version.id
    return version


def create_fork(db: Any, *, actor: DBUser, listing_id: str, modification_summary: str) -> dict[str, Any]:
    listing = _listing(db, listing_id)
    acquisition = db.query(DBMarketplaceAcquisition).filter_by(listing_id=listing.id, recipient_public_id=actor.public_id).first()
    if acquisition is None or acquisition.listing_snapshot_hash != listing.snapshot_hash:
        _fail("marketplace_fork_acquisition_required", "current listing version must be acquired before it can be forked")
    existing = db.query(DBMarketplaceFork).filter_by(acquisition_id=acquisition.id).first()
    if existing: return fork_payload(db, existing, actor)
    local_snapshot = _snapshot(db, db.get(DBCourse, acquisition.derived_course_id))[0]
    source_title = listing.snapshot_data["course"]["title"]
    if local_snapshot["course"].get("title") == f"{source_title}（市场副本）":
        local_snapshot["course"]["title"] = source_title
    row = DBMarketplaceFork(
        acquisition_id=acquisition.id, source_listing_id=listing.id, applied_upstream_listing_id=listing.id,
        derived_course_id=acquisition.derived_course_id, owner_public_id=actor.public_id,
        baseline_snapshot=listing.snapshot_data, baseline_license_snapshot=listing.license_snapshot,
        baseline_hash=listing.snapshot_hash,
    )
    db.add(row); db.flush()
    version = _persist_fork_version(db, fork=row, actor=actor, snapshot=local_snapshot,
        summary=modification_summary, baseline_listing=listing, inherited_license=listing.license_snapshot)
    course = db.get(DBCourse, acquisition.derived_course_id)
    _apply_snapshot(db, course, local_snapshot, listing.license_snapshot, actor)
    course.visibility = "private"
    db.flush(); _audit(db, actor, "marketplace.fork_created", "marketplace_fork", row.id,
        {"acquisition_id": acquisition.id, "source_listing_id": listing.id, "version_id": version.id,
         "baseline_hash": listing.snapshot_hash, "license_inherited": True})
    return fork_payload(db, row, actor)


def create_fork_version(db: Any, *, actor: DBUser, fork_id: str, expected_version: int,
                        modification_summary: str, patch: dict[str, Any]) -> dict[str, Any]:
    row = _fork(db, fork_id); _require_fork_owner(row, actor)
    if row.lock_version != expected_version: _fail("marketplace_fork_version_conflict", "marketplace fork has changed")
    current = _fork_version(db, row); snapshot = _apply_fork_patch(current.local_snapshot, patch)
    baseline_listing = _listing(db, row.applied_upstream_listing_id)
    version = _persist_fork_version(db, fork=row, actor=actor, snapshot=snapshot,
        summary=modification_summary, baseline_listing=baseline_listing,
        inherited_license=current.inherited_license_snapshot)
    if version.id == current.id: return fork_payload(db, row, actor)
    course = db.get(DBCourse, row.derived_course_id)
    _apply_snapshot(db, course, snapshot, current.inherited_license_snapshot, actor)
    course.visibility = "private"; row.lock_version += 1; db.flush()
    _audit(db, actor, "marketplace.fork_version_created", "marketplace_fork", row.id,
        {"version_id": version.id, "version_number": version.version_number,
         "local_snapshot_hash": version.local_snapshot_hash, "summary_hash": version.modification_summary_hash})
    return fork_payload(db, row, actor)


def _latest_upstream(db: Any, row: DBMarketplaceFork) -> DBMarketplaceListing:
    source = _listing(db, row.source_listing_id)
    latest = db.query(DBMarketplaceListing).filter(
        DBMarketplaceListing.course_id == source.course_id,
        DBMarketplaceListing.published_at.isnot(None),
    ).order_by(DBMarketplaceListing.published_at.desc(), DBMarketplaceListing.created_at.desc()).first()
    return latest or source


def _merge_non_conflicting(base: dict[str, Any], local: dict[str, Any], upstream: dict[str, Any], conflicts: set[str]) -> dict[str, Any]:
    result = copy.deepcopy(local)
    for path in _changes(base, upstream):
        if path in conflicts: continue
        section, key = path.split(".", 1)
        if section == "course": result["course"][key] = copy.deepcopy(upstream["course"].get(key))
        else:
            values = {item["filename"]: item for item in upstream.get(section, [])}
            current = {item["filename"]: item for item in result.get(section, [])}
            if key in values: current[key] = copy.deepcopy(values[key])
            else: current.pop(key, None)
            result[section] = [current[name] for name in sorted(current)]
    return result


def fork_update_preview(db: Any, row: DBMarketplaceFork, actor: DBUser) -> dict[str, Any] | None:
    _require_fork_owner(row, actor); latest = _latest_upstream(db, row)
    if latest.id == row.applied_upstream_listing_id:
        row.upstream_status = "withdrawn" if latest.status == "withdrawn" else "current"
        return None
    decided = db.query(DBMarketplaceForkDecision).filter_by(fork_id=row.id, upstream_listing_id=latest.id).first()
    local = _fork_version(db, row).local_snapshot; base = row.baseline_snapshot; upstream = latest.snapshot_data
    local_changes, upstream_changes = _changes(base, local), _changes(base, upstream)
    conflicts = sorted(set(local_changes) & set(upstream_changes))
    row.upstream_status = "withdrawn" if latest.status == "withdrawn" else ("current" if decided else "update_available")
    return {"upstream_listing": public_payload(latest), "baseline_snapshot_hash": row.baseline_hash,
        "local_snapshot_hash": _hash(local), "upstream_snapshot_hash": latest.snapshot_hash,
        "local_changes": local_changes, "upstream_changes": upstream_changes, "conflicts": conflicts,
        "conflict_count": len(conflicts), "decision": fork_decision_payload(decided) if decided else None}


def _fork_version_payload(row: DBMarketplaceForkVersion) -> dict[str, Any]:
    return {"id": row.id, "version_number": row.version_number, "parent_version_id": row.parent_version_id,
        "baseline_listing_id": row.baseline_listing_id, "baseline_snapshot_hash": row.baseline_snapshot_hash,
        "local_snapshot_hash": row.local_snapshot_hash, "modification_summary": row.modification_summary,
        "modification_summary_hash": row.modification_summary_hash,
        "inherited_license": {"course_license": row.inherited_license_snapshot.get("course_license", ""),
            "course_origin": row.inherited_license_snapshot.get("course_origin", ""),
            "legal_review_state": row.inherited_license_snapshot.get("legal_review_state", "not_automatically_determined")},
        "course": {key: row.local_snapshot["course"].get(key) for key in ("version", "title", "subject", "description")},
        "document_count": len(row.local_snapshot.get("documents", [])),
        "created_at": row.created_at.isoformat() if row.created_at else None}


def fork_decision_payload(row: DBMarketplaceForkDecision | None) -> dict[str, Any] | None:
    if row is None: return None
    return {"id": row.id, "upstream_listing_id": row.upstream_listing_id, "action": row.action,
        "resulting_version_id": row.resulting_version_id, "reason": row.reason, "reason_hash": row.reason_hash,
        "conflicts": row.conflict_snapshot.get("conflicts", []), "created_at": row.created_at.isoformat() if row.created_at else None}


def fork_payload(db: Any, row: DBMarketplaceFork, actor: DBUser) -> dict[str, Any]:
    _require_fork_owner(row, actor); current = _fork_version(db, row); preview = fork_update_preview(db, row, actor)
    versions = db.query(DBMarketplaceForkVersion).filter_by(fork_id=row.id).order_by(DBMarketplaceForkVersion.version_number.desc()).all()
    decisions = db.query(DBMarketplaceForkDecision).filter_by(fork_id=row.id).order_by(DBMarketplaceForkDecision.created_at.desc()).all()
    return {"id": row.id, "acquisition_id": row.acquisition_id, "source_listing_id": row.source_listing_id,
        "applied_upstream_listing_id": row.applied_upstream_listing_id, "derived_course_id": row.derived_course_id,
        "owner_public_id": row.owner_public_id, "baseline_hash": row.baseline_hash,
        "upstream_status": row.upstream_status, "lock_version": row.lock_version,
        "current_version": _fork_version_payload(current), "versions": [_fork_version_payload(x) for x in versions],
        "decisions": [fork_decision_payload(x) for x in decisions], "update_preview": preview,
        "boundary": "许可证按所选上游版本原样冻结；系统不自动判断修改后的法律兼容性。冲突字段不会被静默覆盖。"}


def fork_workspace(db: Any, *, actor: DBUser) -> dict[str, Any]:
    rows = db.query(DBMarketplaceFork).filter_by(owner_public_id=actor.public_id).order_by(DBMarketplaceFork.updated_at.desc()).all()
    acquisitions = db.query(DBMarketplaceAcquisition).filter_by(recipient_public_id=actor.public_id).order_by(DBMarketplaceAcquisition.created_at.desc()).all()
    acquisition_items = []
    for acquisition in acquisitions:
        listing = _listing(db, acquisition.listing_id)
        acquisition_items.append({**acquisition_payload(acquisition), "listing": public_payload(listing),
            "has_fork": any(item.acquisition_id == acquisition.id for item in rows)})
    return {"schema_version": "fc.marketplace-forks.v1",
        "truth_label": "正式资源分叉 · 独立不可变版本线 · 三方差异",
        "boundary": "分叉只来源于本人真实市场副本；来源、版本、许可证和修改摘要均可追溯。冲突必须显式处理。",
        "acquisitions": acquisition_items, "forks": [fork_payload(db, x, actor) for x in rows]}


def decide_fork_update(db: Any, *, actor: DBUser, fork_id: str, upstream_listing_id: str,
                       action: str, reason: str, expected_version: int) -> dict[str, Any]:
    row = _fork(db, fork_id); _require_fork_owner(row, actor)
    if row.lock_version != expected_version: _fail("marketplace_fork_version_conflict", "marketplace fork has changed")
    preview = fork_update_preview(db, row, actor)
    if preview is None or preview["upstream_listing"]["id"] != upstream_listing_id:
        _fail("marketplace_fork_update_stale", "upstream listing is no longer current")
    existing = db.query(DBMarketplaceForkDecision).filter_by(fork_id=row.id, upstream_listing_id=upstream_listing_id).first()
    if existing: return fork_payload(db, row, actor)
    upstream = _listing(db, upstream_listing_id); current = _fork_version(db, row)
    frozen = {"baseline": row.baseline_snapshot, "local": current.local_snapshot, "upstream": upstream.snapshot_data,
        "local_changes": preview["local_changes"], "upstream_changes": preview["upstream_changes"],
        "conflicts": preview["conflicts"], "license_before": current.inherited_license_snapshot,
        "license_upstream": upstream.license_snapshot}
    resulting_version = None
    if action in {"accept_non_conflicting", "keep_local"}:
        snapshot = current.local_snapshot if action == "keep_local" else _merge_non_conflicting(
            row.baseline_snapshot, current.local_snapshot, upstream.snapshot_data, set(preview["conflicts"]))
        inherited_license = current.inherited_license_snapshot if action == "keep_local" else upstream.license_snapshot
        resulting_version = _persist_fork_version(db, fork=row, actor=actor, snapshot=snapshot,
            summary=f"上游 {upstream.course_version}：{reason.strip()}", baseline_listing=upstream,
            inherited_license=inherited_license)
        _apply_snapshot(db, db.get(DBCourse, row.derived_course_id), snapshot, inherited_license, actor)
        db.get(DBCourse, row.derived_course_id).visibility = "private"
        row.applied_upstream_listing_id = upstream.id; row.baseline_snapshot = upstream.snapshot_data
        row.baseline_license_snapshot = upstream.license_snapshot; row.baseline_hash = upstream.snapshot_hash
    elif action != "ignore": _fail("marketplace_fork_action_invalid", "fork update action is invalid")
    decision = DBMarketplaceForkDecision(fork_id=row.id, upstream_listing_id=upstream.id, action=action,
        conflict_snapshot=frozen, resulting_version_id=resulting_version.id if resulting_version else None,
        actor_public_id=actor.public_id, reason=reason.strip(), reason_hash=_hash(reason.strip()))
    db.add(decision)
    row.upstream_status = "current"; row.lock_version += 1; db.flush()
    _audit(db, actor, f"marketplace.fork_update_{action}", "marketplace_fork", row.id,
        {"upstream_listing_id": upstream.id, "conflict_count": len(preview["conflicts"]),
         "resulting_version_id": decision.resulting_version_id, "reason_hash": decision.reason_hash})
    return fork_payload(db, row, actor)


def _impact_title(impact_type: str) -> str:
    return {"withdrawn": "已获取的市场课程来源已撤回", "new_version": "市场课程已有新版本",
            "severe_fix": "市场课程发布重要修复", "license_changed": "市场课程许可证发生变化"}[impact_type]


def emit_marketplace_impact(db: Any, *, actor: DBUser, source: DBMarketplaceListing,
                            impact_type: str, reason: str, target: DBMarketplaceListing | None = None) -> tuple[DBMarketplaceImpactEvent, int]:
    target_id = target.id if target else None; target_hash = target.snapshot_hash if target else None
    existing = db.query(DBMarketplaceImpactEvent).filter_by(source_listing_id=source.id,
        target_listing_id=target_id, impact_type=impact_type, target_snapshot_hash=target_hash).first()
    if existing:
        return existing, 0
    evidence = {"source_listing_id": source.id, "source_course_version": source.course_version,
        "source_snapshot_hash": source.snapshot_hash, "source_license": source.license_snapshot,
        "target_listing_id": target_id, "target_course_version": target.course_version if target else None,
        "target_snapshot_hash": target_hash, "target_license": target.license_snapshot if target else None,
        "historical_copies_deleted": 0, "delivery_channel": "local_inbox"}
    event = DBMarketplaceImpactEvent(source_listing_id=source.id, target_listing_id=target_id,
        impact_type=impact_type, actor_public_id=actor.public_id, source_snapshot_hash=source.snapshot_hash,
        target_snapshot_hash=target_hash, evidence_snapshot=evidence, evidence_hash=_hash(evidence),
        reason=reason.strip(), reason_hash=_hash(reason.strip()))
    db.add(event); db.flush(); made = 0
    for acquisition in db.query(DBMarketplaceAcquisition).filter_by(listing_id=source.id).all():
        key = f"impact:{event.id}:acquisition:{acquisition.id}"
        old = db.query(DBMarketplaceImpactNotification).filter_by(owner_public_id=acquisition.recipient_public_id,
            idempotency_key=key).first()
        if old: continue
        title = _impact_title(impact_type)
        target_text = f"可检查课程 v{target.course_version}。" if target else "历史副本仍保留，可选择继续保留。"
        notice = DBMarketplaceImpactNotification(impact_event_id=event.id, acquisition_id=acquisition.id,
            owner_public_id=acquisition.recipient_public_id, source_listing_id=source.id,
            target_listing_id=target_id, notification_type=impact_type, idempotency_key=key, title=title,
            body=f"{source.title}（课程 v{source.course_version}）：{reason.strip()}。{target_text}",
            source_route=f"/marketplace?listing={target_id or source.id}&impact={event.id}")
        db.add(notice); made += 1
    _audit(db, actor, "marketplace.impact_emitted", "marketplace_impact_event", event.id,
        {"impact_type": impact_type, "source_listing_id": source.id, "target_listing_id": target_id,
         "recipient_count": made, "evidence_hash": event.evidence_hash})
    db.flush(); return event, made


def _impact_notice_payload(row: DBMarketplaceImpactNotification) -> dict[str, Any]:
    return {"id": row.id, "impact_event_id": row.impact_event_id, "type": row.notification_type,
        "title": row.title, "body": row.body, "source_listing_id": row.source_listing_id,
        "target_listing_id": row.target_listing_id, "source_route": row.source_route,
        "status": row.status, "lock_version": row.lock_version, "action": row.action,
        "read_at": row.read_at.isoformat() if row.read_at else None,
        "actioned_at": row.actioned_at.isoformat() if row.actioned_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "delivery_channel": "local_inbox"}


def impact_inbox(db: Any, *, actor: DBUser) -> dict[str, Any]:
    rows = db.query(DBMarketplaceImpactNotification).filter_by(owner_public_id=actor.public_id).order_by(
        DBMarketplaceImpactNotification.created_at.desc()).all()
    return {"schema_version": "fc.marketplace-impact-inbox.v1", "items": [_impact_notice_payload(row) for row in rows],
        "unread_count": sum(row.status == "unread" for row in rows),
        "boundary": "仅保证写入本地收件箱，不宣称邮件、短信或企业消息已送达。"}


def update_impact_notice(db: Any, *, actor: DBUser, notice_id: str, expected_version: int,
                         action: str | None = None) -> dict[str, Any]:
    row = db.get(DBMarketplaceImpactNotification, notice_id)
    if row is None: _fail("marketplace_notification_unknown", "影响通知不存在")
    if row.owner_public_id != actor.public_id: _fail("marketplace_forbidden", "通知属于其他用户")
    if row.lock_version != expected_version: _fail("marketplace_version_conflict", "通知状态已变化")
    if action is not None and action not in {"view_source", "keep_copy", "review_update"}:
        _fail("marketplace_notification_action_invalid", "通知处理动作无效")
    if row.read_at is None: row.read_at = _now()
    if action is None:
        row.status = "read"
    else:
        row.status = "actioned"; row.action = action; row.actioned_at = _now()
    row.lock_version += 1
    _audit(db, actor, "marketplace.impact_notification_updated", "marketplace_impact_notification", row.id,
        {"status": row.status, "action": row.action or "read", "impact_event_id": row.impact_event_id})
    db.flush(); return _impact_notice_payload(row)


def engagement_summary(db: Any, listing: DBMarketplaceListing, actor: DBUser | None = None) -> dict[str, Any]:
    favorites = db.query(DBMarketplaceFavorite).filter_by(listing_id=listing.id, status="active").count()
    reviews = db.query(DBMarketplaceReview).filter_by(listing_id=listing.id, status="active").all()
    minimum = 3; count = len(reviews)
    average = round(sum(row.rating for row in reviews) / count, 2) if count >= minimum else None
    mine_favorite = None; mine_review = None
    if actor is not None:
        mine_favorite = db.query(DBMarketplaceFavorite).filter_by(listing_id=listing.id, owner_public_id=actor.public_id).first()
        mine_review = db.query(DBMarketplaceReview).filter_by(listing_id=listing.id, owner_public_id=actor.public_id).first()
    return {"favorite_count": favorites, "review_count": count, "average_rating": average,
        "minimum_sample": minimum, "sample_state": "published" if average is not None else "insufficient",
        "is_favorited": bool(mine_favorite and mine_favorite.status == "active"),
        "my_review_id": mine_review.id if mine_review else None}


def set_favorite(db: Any, *, actor: DBUser, listing_id: str, active: bool, expected_version: int | None = None) -> dict[str, Any]:
    listing = _listing(db, listing_id)
    if listing.status not in {"published", "withdrawn"}: _fail("marketplace_listing_unavailable", "该市场条目不可收藏")
    row = db.query(DBMarketplaceFavorite).filter_by(listing_id=listing.id, owner_public_id=actor.public_id).first()
    target = "active" if active else "removed"
    if row is None:
        if not active: _fail("marketplace_favorite_unknown", "尚未收藏该版本")
        row = DBMarketplaceFavorite(listing_id=listing.id, listing_snapshot_hash=listing.snapshot_hash,
            owner_public_id=actor.public_id, status="active")
        db.add(row); db.flush(); action = "created"
    else:
        if expected_version is not None and row.lock_version != expected_version: _fail("marketplace_version_conflict", "收藏状态已变化")
        if row.listing_snapshot_hash != listing.snapshot_hash: _fail("marketplace_snapshot_conflict", "收藏绑定的市场版本不一致")
        if row.status == target: action = "unchanged"
        else: row.status = target; row.lock_version += 1; db.flush(); action = "restored" if active else "removed"
    _audit(db, actor, f"marketplace.favorite_{action}", "marketplace_favorite", row.id,
        {"listing_id": listing.id, "snapshot_hash": listing.snapshot_hash, "status": row.status})
    return {"id": row.id, "listing_id": row.listing_id, "listing_snapshot_hash": row.listing_snapshot_hash,
        "status": row.status, "lock_version": row.lock_version, "created_at": row.created_at.isoformat() if row.created_at else None,
        "aggregate": engagement_summary(db, listing, actor)}


def _review_evidence(db: Any, actor: DBUser, listing: DBMarketplaceListing) -> tuple[DBMarketplaceAcquisition, dict[str, Any]]:
    acquisition = db.query(DBMarketplaceAcquisition).filter_by(listing_id=listing.id, recipient_public_id=actor.public_id).first()
    if acquisition is None or acquisition.listing_snapshot_hash != listing.snapshot_hash:
        _fail("marketplace_review_use_required", "评价前必须先获取当前市场版本的课程副本")
    event_count = db.query(DBLearningEvent).filter_by(owner_public_id=actor.public_id, course_id=acquisition.derived_course_id).count()
    evidence = {"kind": "verified_marketplace_acquisition", "acquisition_id": acquisition.id,
        "listing_id": listing.id, "listing_snapshot_hash": listing.snapshot_hash,
        "derived_course_id": acquisition.derived_course_id,
        "acquired_at": acquisition.created_at.isoformat() if acquisition.created_at else None,
        "learning_event_count": event_count,
        "boundary": "获取副本证明已导入；学习事件数量用于区分是否已有进一步学习活动。"}
    return acquisition, evidence


def _review_events(db: Any, review_id: str) -> list[dict[str, Any]]:
    rows = db.query(DBMarketplaceReviewEvent).filter_by(review_id=review_id).order_by(DBMarketplaceReviewEvent.created_at).all()
    return [{"id": row.id, "action": row.action, "from_rating": row.from_rating, "to_rating": row.to_rating,
        "body_hash": row.body_hash, "evidence_hash": row.evidence_hash,
        "created_at": row.created_at.isoformat() if row.created_at else None} for row in rows]


def review_payload(db: Any, row: DBMarketplaceReview, actor: DBUser, include_history: bool = False) -> dict[str, Any]:
    listing = _listing(db, row.listing_id); own = row.owner_public_id == actor.public_id; manager = _comment_manager(actor, listing)
    return {"id": row.id, "listing_id": row.listing_id, "listing_snapshot_hash": row.listing_snapshot_hash,
        "course_version": row.course_version, "rating": row.rating, "body": row.body,
        "verified_use": True, "usage": {"acquisition_id": row.acquisition_id,
            "derived_course_id": row.derived_course_id, "learning_event_count": row.evidence_snapshot.get("learning_event_count", 0)},
        "lock_version": row.lock_version, "is_mine": own,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "events": _review_events(db, row.id) if include_history and (own or manager) else []}


def marketplace_engagement(db: Any, *, actor: DBUser, listing_id: str) -> dict[str, Any]:
    listing = _listing(db, listing_id)
    if listing.status not in {"published", "withdrawn"} and not _comment_manager(actor, listing):
        _fail("marketplace_forbidden", "该市场条目的互动数据不可见")
    favorite = db.query(DBMarketplaceFavorite).filter_by(listing_id=listing.id, owner_public_id=actor.public_id).first()
    own_review = db.query(DBMarketplaceReview).filter_by(listing_id=listing.id, owner_public_id=actor.public_id).first()
    acquisition = db.query(DBMarketplaceAcquisition).filter_by(listing_id=listing.id, recipient_public_id=actor.public_id).first()
    public_reviews = db.query(DBMarketplaceReview).filter_by(listing_id=listing.id, status="active").order_by(DBMarketplaceReview.updated_at.desc()).all()
    return {"listing_id": listing.id, "course_version": listing.course_version, "snapshot_hash": listing.snapshot_hash,
        "aggregate": engagement_summary(db, listing, actor),
        "favorite": ({"id": favorite.id, "status": favorite.status, "lock_version": favorite.lock_version} if favorite else None),
        "eligibility": {"can_review": bool(acquisition and acquisition.listing_snapshot_hash == listing.snapshot_hash),
            "reason": "已获取当前版本课程副本" if acquisition and acquisition.listing_snapshot_hash == listing.snapshot_hash else "请先获取当前版本课程副本"},
        "my_review": review_payload(db, own_review, actor, True) if own_review else None,
        "reviews": [review_payload(db, row, actor, False) for row in public_reviews],
        "boundary": "收藏不代表使用；评价仅来自已获取当前版本副本的账号。少于 3 个合格评价时不公开均分。"}


def upsert_review(db: Any, *, actor: DBUser, listing_id: str, rating: int, body: str, expected_version: int | None = None) -> dict[str, Any]:
    listing = _listing(db, listing_id)
    if listing.status not in {"published", "withdrawn"}: _fail("marketplace_listing_unavailable", "该市场条目不可评价")
    acquisition, evidence = _review_evidence(db, actor, listing)
    clean = " ".join(body.split())
    if len(clean) < 2: _fail("marketplace_review_invalid", "使用后评价至少需要 2 个字符")
    row = db.query(DBMarketplaceReview).filter_by(listing_id=listing.id, owner_public_id=actor.public_id).first()
    old_rating = None
    if row is None:
        if expected_version is not None: _fail("marketplace_version_conflict", "评价尚不存在")
        row = DBMarketplaceReview(listing_id=listing.id, listing_snapshot_hash=listing.snapshot_hash,
            course_version=listing.course_version, owner_public_id=actor.public_id, acquisition_id=acquisition.id,
            derived_course_id=acquisition.derived_course_id, rating=rating, body=clean, body_hash=_hash(clean),
            evidence_snapshot=evidence, evidence_hash=_hash(evidence))
        db.add(row); db.flush(); action = "created"
    else:
        if expected_version is None or row.lock_version != expected_version: _fail("marketplace_version_conflict", "评价已变化，请刷新后重试")
        if row.listing_snapshot_hash != listing.snapshot_hash: _fail("marketplace_snapshot_conflict", "评价绑定的市场版本不一致")
        old_rating = row.rating; row.rating = rating; row.body = clean; row.body_hash = _hash(clean); row.lock_version += 1
        db.flush(); action = "updated"
    event = DBMarketplaceReviewEvent(review_id=row.id, actor_public_id=actor.public_id, action=action,
        from_rating=old_rating, to_rating=row.rating, body_hash=row.body_hash, evidence_hash=row.evidence_hash,
        snapshot={"listing_id": listing.id, "snapshot_hash": listing.snapshot_hash,
                  "course_version": listing.course_version, "lock_version": row.lock_version})
    db.add(event); _audit(db, actor, f"marketplace.review_{action}", "marketplace_review", row.id,
        {"listing_id": listing.id, "snapshot_hash": listing.snapshot_hash, "rating": row.rating,
         "evidence_hash": row.evidence_hash, "learning_event_count": evidence["learning_event_count"]})
    db.flush()
    return {"review": review_payload(db, row, actor, True), "aggregate": engagement_summary(db, listing, actor)}


def _comment(db: Any, comment_id: str) -> DBMarketplaceComment:
    row = db.get(DBMarketplaceComment, comment_id)
    if row is None: _fail("marketplace_comment_unknown", "评论不存在")
    return row


def _comment_manager(actor: DBUser, listing: DBMarketplaceListing) -> bool:
    return normalize_role(actor.role) == "admin" or listing.owner_public_id == actor.public_id


def _comment_event(db: Any, row: DBMarketplaceComment, actor: DBUser, action: str, before: str, reason: str = "") -> None:
    db.add(DBMarketplaceCommentEvent(comment_id=row.id, actor_public_id=actor.public_id, action=action,
        from_status=before, to_status=row.status, body_hash=row.body_hash, reason=reason.strip(),
        snapshot={"listing_id": row.listing_id, "listing_snapshot_hash": row.listing_snapshot_hash,
                  "course_version": row.course_version, "lock_version": row.lock_version}))
    _audit(db, actor, f"marketplace.comment_{action}", "marketplace_comment", row.id,
        {"listing_id": row.listing_id, "from_status": before, "to_status": row.status,
         "body_hash": row.body_hash, "reason_sha256": _hash(reason.strip()) if reason.strip() else ""})
    db.flush()


def comment_payload(db: Any, row: DBMarketplaceComment, actor: DBUser, include_events: bool = False) -> dict[str, Any]:
    listing = _listing(db, row.listing_id); manager = _comment_manager(actor, listing); own = row.author_public_id == actor.public_id
    visible_body = row.body if row.status == "active" or own or manager else ""
    reports = db.query(DBMarketplaceCommentReport).filter_by(comment_id=row.id).order_by(DBMarketplaceCommentReport.created_at.desc()).all()
    events = db.query(DBMarketplaceCommentEvent).filter_by(comment_id=row.id).order_by(DBMarketplaceCommentEvent.created_at).all() if include_events and (own or manager) else []
    return {"id": row.id, "listing_id": row.listing_id, "listing_snapshot_hash": row.listing_snapshot_hash,
        "course_version": row.course_version, "author_public_id": row.author_public_id, "body": visible_body,
        "status": row.status, "lock_version": row.lock_version, "edit_deadline": row.edit_deadline.isoformat(),
        "can_edit": own and row.status == "active" and _now() <= row.edit_deadline,
        "can_delete": own and row.status == "active", "can_moderate": manager,
        "open_report_count": sum(x.status == "open" for x in reports),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "events": [{"id": x.id, "action": x.action, "from_status": x.from_status, "to_status": x.to_status,
                   "body_hash": x.body_hash, "reason": x.reason, "created_at": x.created_at.isoformat()} for x in events],
        "reports": [{"id": x.id, "category": x.category, "description": x.description, "status": x.status,
                    "lock_version": x.lock_version, "evidence_hash": x.evidence_hash} for x in reports] if manager else [],
        "binding_label": f"课程 v{row.course_version} · {row.listing_snapshot_hash[:12]}"}


def list_comments(db: Any, *, actor: DBUser, listing_id: str) -> dict[str, Any]:
    listing = _listing(db, listing_id)
    if listing.status not in {"published", "withdrawn"} and not _comment_manager(actor, listing):
        _fail("marketplace_forbidden", "该市场条目的评论不可见")
    rows = db.query(DBMarketplaceComment).filter_by(listing_id=listing.id).order_by(DBMarketplaceComment.created_at.desc()).all()
    visible = [row for row in rows if row.status == "active" or row.author_public_id == actor.public_id or _comment_manager(actor, listing)]
    return {"listing_id": listing.id, "course_version": listing.course_version, "snapshot_hash": listing.snapshot_hash,
            "items": [comment_payload(db, row, actor, True) for row in visible], "count": len(visible),
            "boundary": "评论永久绑定当前条目快照；新课程版本或新市场条目不会迁移旧评论。"}


def create_comment(db: Any, *, actor: DBUser, listing_id: str, body: str) -> dict[str, Any]:
    listing = _listing(db, listing_id)
    if listing.status != "published": _fail("marketplace_listing_unavailable", "只有已发布条目可以评论")
    clean = " ".join(body.split())
    if len(clean) < 2: _fail("marketplace_comment_invalid", "评论至少需要 2 个字符")
    row = DBMarketplaceComment(listing_id=listing.id, listing_snapshot_hash=listing.snapshot_hash,
        course_version=listing.course_version, author_public_id=actor.public_id, body=clean,
        body_hash=_hash(clean), edit_deadline=_now() + timedelta(minutes=30))
    db.add(row); db.flush(); _comment_event(db, row, actor, "created", "active")
    return comment_payload(db, row, actor, True)


def edit_comment(db: Any, *, actor: DBUser, comment_id: str, body: str, expected_version: int) -> dict[str, Any]:
    row = _comment(db, comment_id)
    if row.author_public_id != actor.public_id: _fail("marketplace_forbidden", "只能编辑自己的评论")
    if row.lock_version != expected_version: _fail("marketplace_version_conflict", "评论已变化")
    if row.status != "active": _fail("marketplace_comment_inactive", "评论当前不可编辑")
    if _now() > row.edit_deadline: _fail("marketplace_comment_edit_expired", "评论编辑窗口已结束")
    clean = " ".join(body.split())
    if len(clean) < 2: _fail("marketplace_comment_invalid", "评论至少需要 2 个字符")
    before = row.status; row.body = clean; row.body_hash = _hash(clean); row.lock_version += 1; db.flush(); _comment_event(db, row, actor, "edited", before)
    return comment_payload(db, row, actor, True)


def delete_comment(db: Any, *, actor: DBUser, comment_id: str, expected_version: int) -> dict[str, Any]:
    row = _comment(db, comment_id)
    if row.author_public_id != actor.public_id: _fail("marketplace_forbidden", "只能删除自己的评论")
    if row.lock_version != expected_version: _fail("marketplace_version_conflict", "评论已变化")
    if row.status != "active": _fail("marketplace_comment_inactive", "评论已不可删除")
    before = row.status; row.status = "deleted"; row.deleted_at = _now(); row.lock_version += 1; db.flush(); _comment_event(db, row, actor, "deleted", before)
    return comment_payload(db, row, actor, True)


def moderate_comment(db: Any, *, actor: DBUser, comment_id: str, action: str, reason: str, expected_version: int) -> dict[str, Any]:
    row = _comment(db, comment_id); listing = _listing(db, row.listing_id)
    if not _comment_manager(actor, listing): _fail("marketplace_forbidden", "只有发布教师或管理员可以管理评论")
    if row.lock_version != expected_version: _fail("marketplace_version_conflict", "评论已变化")
    target = {"hide": "hidden", "restore": "active"}.get(action)
    if target is None or row.status == target or row.status == "deleted": _fail("marketplace_transition_invalid", "评论管理状态转换无效")
    before = row.status; row.status = target; row.lock_version += 1; db.flush(); _comment_event(db, row, actor, action, before, reason)
    return comment_payload(db, row, actor, True)


def report_comment(db: Any, *, actor: DBUser, comment_id: str, category: str, description: str) -> dict[str, Any]:
    row = _comment(db, comment_id)
    if row.status != "active": _fail("marketplace_comment_inactive", "只能举报可见评论")
    if row.author_public_id == actor.public_id: _fail("marketplace_comment_self_report", "不能举报自己的评论")
    existing = db.query(DBMarketplaceCommentReport).filter_by(comment_id=row.id, reporter_public_id=actor.public_id).first()
    if existing: return {"id": existing.id, "status": existing.status, "created": False}
    evidence = {"comment_id": row.id, "listing_id": row.listing_id, "listing_snapshot_hash": row.listing_snapshot_hash,
                "course_version": row.course_version, "body_hash": row.body_hash, "comment_status": row.status}
    report = DBMarketplaceCommentReport(comment_id=row.id, listing_id=row.listing_id, reporter_public_id=actor.public_id,
        category=category, description=" ".join(description.split()), evidence_snapshot=evidence, evidence_hash=_hash(evidence))
    db.add(report); db.flush(); _audit(db, actor, "marketplace.comment_reported", "marketplace_comment_report", report.id,
        {"comment_id": row.id, "listing_id": row.listing_id, "evidence_hash": report.evidence_hash})
    return {"id": report.id, "comment_id": row.id, "status": report.status, "lock_version": report.lock_version, "created": True}


def decide_comment_report(db: Any, *, actor: DBUser, report_id: str, action: str, reason: str, expected_version: int) -> dict[str, Any]:
    report = db.get(DBMarketplaceCommentReport, report_id)
    if report is None: _fail("marketplace_comment_report_unknown", "评论举报不存在")
    row = _comment(db, report.comment_id); listing = _listing(db, row.listing_id)
    if not _comment_manager(actor, listing): _fail("marketplace_forbidden", "无权处置该评论举报")
    if report.lock_version != expected_version: _fail("marketplace_version_conflict", "评论举报已变化")
    if report.status != "open": _fail("marketplace_report_resolved", "评论举报已处置")
    before = row.status
    if action == "dismiss": report.status = "dismissed"
    elif action == "hide":
        report.status = "resolved"
        if row.status == "active": row.status = "hidden"; row.lock_version += 1; db.flush(); _comment_event(db, row, actor, "hide", before, reason)
    else: _fail("marketplace_action_invalid", "评论举报只能 dismiss 或 hide")
    report.lock_version += 1; report.resolved_at = _now(); _audit(db, actor, f"marketplace.comment_report_{action}", "marketplace_comment_report", report.id,
        {"comment_id": row.id, "reason_sha256": _hash(reason.strip()), "comment_status": row.status})
    return {"id": report.id, "status": report.status, "lock_version": report.lock_version, "comment": comment_payload(db, row, actor, True)}
