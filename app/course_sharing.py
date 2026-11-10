"""Immutable course releases, recipient-owned copies, and explicit upstream updates."""

from __future__ import annotations

from app.source_refs import current_chapter_clause

import copy as copy_module
import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from app.course_governance import require_manager
from app.database import (
    DBAuditLog, DBCourse, DBCourseDerivedCopy, DBCourseDocument, DBCourseShareDecision,
    DBCourseShareRelease, DBCourseWithdrawal, DBOrganization, DBOrganizationMembership,
    DBSourceDocument, DBSourceRef, DBChapter, DBChapterKnowledgePoint,
    DBTeachingClass, DBTeachingClassMember, DBUser, DBKnowledgeDocument,
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
    # Uploads store their parsed body in knowledge_documents. Freeze that body
    # too, so a recipient does not depend on the author's original upload file.
    document_ids = {row.id for row in docs}
    for source in sources:
        if not source.legacy_document_id or source.legacy_document_id in document_ids:
            continue
        uploaded = db.get(DBKnowledgeDocument, source.legacy_document_id)
        if uploaded is None:
            continue
        docs.append(SimpleNamespace(
            id=uploaded.id, chapter_order=len(docs)+1, filename=uploaded.filename,
            file_type=uploaded.file_type, file_size=uploaded.file_size, title=uploaded.title,
            content=uploaded.content, tags=uploaded.tags, chunk_count=uploaded.chunk_count,
            content_hash=source.processed_sha256 or source.content_hash,
            source_path=source.source_path, license_text=source.license_text, status="published",
        ))
        document_ids.add(uploaded.id)
    data = {
        "schema_version": "next.course-share-snapshot.v1",
        "course": {key: getattr(course, key) for key in ("id", "version", "title", "subject", "description", "domain_pack", "language", "content_origin", "visibility", "status", "manifest_version", "manifest_data")},
        "documents": [{key: getattr(row, key) for key in ("chapter_order", "filename", "file_type", "file_size", "title", "content", "tags", "chunk_count", "content_hash", "source_path", "license_text", "status")} for row in docs],
        "sources": [{key: getattr(row, key) for key in ("title", "filename", "file_format", "content_hash", "source_sha256", "processed_sha256", "file_size", "source_url", "source_path", "license_text", "parser_version", "parser_metadata", "parse_warnings", "processing_error_code", "processing_status")} for row in sources],
        "source_graph": _source_graph(db, docs, sources),
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


def _source_graph(db: Any, docs: list, sources: list) -> dict[str, Any]:
    source_ids = [row.id for row in sources]
    chapters = db.query(DBChapter).filter(DBChapter.source_document_id.in_(source_ids), current_chapter_clause()).order_by(DBChapter.position, DBChapter.id).all()
    refs = db.query(DBSourceRef).filter(DBSourceRef.source_document_id.in_(source_ids)).order_by(DBSourceRef.id).all()
    return {
        "documents": [{"id": row.id, "filename": row.filename, "content_hash": row.content_hash} for row in docs],
        "sources": [{"id": row.id, "filename": row.filename, "content_hash": row.content_hash, "legacy_document_id": row.legacy_document_id} for row in sources],
        "chapters": [{key: getattr(row, key) for key in ("id", "source_document_id", "parent_id", "stable_key", "title", "position", "heading_level", "char_start", "char_end")} for row in chapters],
        "source_refs": [{key: getattr(row, key) for key in ("id", "source_document_id", "chapter_id", "parser_version", "page_number", "char_start", "char_end", "image_region", "location_kind", "location_index", "location_label", "location_metadata", "content_hash", "quote")} for row in refs],
        "knowledge_points": [{"chapter_id": row.chapter_id, "knowledge_point_id": row.knowledge_point_id, "relation_type": row.relation_type}
                             for row in db.query(DBChapterKnowledgePoint).filter(DBChapterKnowledgePoint.chapter_id.in_([ch.id for ch in chapters]))],
    }


def snapshot_source_graph(db: Any, snapshot: dict[str, Any]) -> dict[str, Any]:
    if isinstance(snapshot.get("source_graph"), dict):
        return snapshot["source_graph"]
    # Old releases did not freeze locators. Reuse only sources whose complete
    # parsed content still matches the released material, never a newer text.
    original_course_id = snapshot.get("course", {}).get("id")
    docs = []
    for item in snapshot.get("documents", []):
        row = db.query(DBCourseDocument).filter_by(course_id=original_course_id, filename=item["filename"]).first()
        if row is not None and row.content == item.get("content") and row.content_hash == item.get("content_hash"):
            docs.append(row)
    filenames = {row.filename for row in docs}
    sources = []
    for item in snapshot.get("sources", []):
        row = db.query(DBSourceDocument).filter_by(course_id=original_course_id, filename=item["filename"]).first()
        keys = ("content_hash", "source_sha256", "processed_sha256", "parser_version")
        if row is not None and row.filename in filenames and all(getattr(row, key) == item.get(key) for key in keys):
            sources.append(row)
    return _source_graph(db, docs, sources)


def _material_entries(snapshot: dict[str, Any], graph: dict[str, Any], section: str) -> list[tuple[dict, dict]]:
    """Pair frozen content with its identity, including old snapshots without hashes."""
    remaining = list(graph.get(section, [])); entries = []
    for item in snapshot.get(section, []):
        candidates = [entry for entry in remaining if entry['filename'] == item['filename']]
        identity = next((entry for entry in candidates if entry.get('content_hash') == item.get('content_hash')), None)
        identity = identity or (candidates[0] if candidates else {})
        if identity: remaining.remove(identity)
        entries.append((item, identity))
    return entries


def _material_mapping(db: Any, course: DBCourse, snapshot: dict[str, Any], *, actor: DBUser | None = None) -> dict[str, str]:
    """Copy each frozen body once; filenames are labels, not version identities."""
    graph = snapshot_source_graph(db, snapshot)
    mapping = {snapshot['course']['id']: course.id}
    documents = list(db.query(DBCourseDocument).filter_by(course_id=course.id))
    copied_docs = []
    for item, identity in _material_entries(snapshot, graph, 'documents'):
        row = next((row for row in documents if row.filename == item['filename']
                    and row.content == item.get('content') and row.content_hash == item.get('content_hash')), None)
        if row is None and actor is not None:
            row = DBCourseDocument(id=_stable('cdoc', course.id, identity.get('id') or item['filename'], _hash(item.get('content') or '')),
                                   course_id=course.id)
            db.add(row); documents.append(row)
        if row is None: continue
        if actor is not None:
            for key, value in item.items(): setattr(row, key, value)
        copied_docs.append(row)
        if identity: mapping[identity['id']] = row.id
    sources = list(db.query(DBSourceDocument).filter_by(course_id=course.id))
    for item, identity in _material_entries(snapshot, graph, 'sources'):
        document_id = mapping.get(identity.get('legacy_document_id'))
        if document_id is None:
            candidates = [doc for doc in copied_docs if doc.filename == item['filename']]
            exact = [doc for doc in candidates if doc.content_hash in {item.get('processed_sha256'), item.get('content_hash')}]
            document_id = exact[0].id if len(exact) == 1 else (candidates[0].id if len(candidates) == 1 else None)
        keys = ('filename', 'content_hash', 'processed_sha256', 'source_sha256', 'parser_version')
        row = next((row for row in sources if all(getattr(row, key) == item.get(key) for key in keys)
                    and row.legacy_document_id == document_id), None)
        # Older copies may not yet have their document link attached.
        if row is None:
            row = next((row for row in sources if row.legacy_document_id is None
                        and all(getattr(row, key) == item.get(key) for key in keys)), None)
        if row is None and actor is not None:
            row = DBSourceDocument(id=_stable('src', course.id, identity.get('id') or item['filename'],
                _hash([document_id, *[item.get(key) for key in keys]])), course_id=course.id, uploader_public_id=actor.public_id)
            db.add(row); sources.append(row)
        if row is None: continue
        if actor is not None:
            for key, value in item.items(): setattr(row, key, value)
            row.legacy_document_id = document_id
        if identity: mapping[identity['id']] = row.id
    if actor is not None: db.flush()
    return mapping


def _copied_chapter(db: Any, course_id: str, item: dict, source_id: str) -> tuple[str, str]:
    # Keep already-issued links when their source version still matches.
    previous = db.query(DBChapter).filter_by(course_id=course_id, stable_key=item['stable_key'], source_document_id=source_id).first()
    if previous: return previous.id, previous.stable_key
    key = _stable('chapter', source_id, item['stable_key'])
    return _stable('ch', course_id, key), key


def _copied_ref(db: Any, course_id: str, item: dict, source_id: str) -> str:
    previous = db.get(DBSourceRef, _stable('ref', course_id, item['id']))
    if previous and previous.source_document_id == source_id and previous.content_hash == item['content_hash']:
        return previous.id
    return _stable('ref', course_id, source_id, item['id'], _hash(item))


def copied_source_mapping(db: Any, course: DBCourse, snapshot: dict[str, Any]) -> dict[str, str]:
    """Resolve frozen links without overwriting recipient content or old citations."""
    graph = snapshot_source_graph(db, snapshot)
    mapping = _material_mapping(db, course, snapshot)
    for item in graph.get('chapters', []):
        source_id = mapping.get(item['source_document_id'])
        if source_id:
            chapter_id, _ = _copied_chapter(db, course.id, item, source_id)
            if db.get(DBChapter, chapter_id): mapping[item['id']] = chapter_id
    for item in graph.get('source_refs', []):
        source_id = mapping.get(item['source_document_id'])
        if source_id:
            ref_id = _copied_ref(db, course.id, item, source_id)
            if db.get(DBSourceRef, ref_id): mapping[item['id']] = ref_id
    return mapping


def apply_source_graph(db: Any, course: DBCourse, snapshot: dict[str, Any]) -> dict[str, str]:
    graph = snapshot_source_graph(db, snapshot)
    mapping = _material_mapping(db, course, snapshot)
    chapters = [item for item in graph.get("chapters", []) if item["source_document_id"] in mapping]
    chapter_keys = {}
    for item in chapters:
        chapter_id, key = _copied_chapter(db, course.id, item, mapping[item['source_document_id']])
        mapping[item['id']], chapter_keys[item['id']] = chapter_id, key
    for item in chapters:
        row = db.get(DBChapter, mapping[item["id"]])
        if row is None:
            row = DBChapter(id=mapping[item["id"]], course_id=course.id)
            db.add(row)
        for key, value in item.items():
            if key not in {"id", "source_document_id", "parent_id", "stable_key"}:
                setattr(row, key, value)
        row.stable_key = chapter_keys[item['id']]
        row.source_document_id = mapping[item["source_document_id"]]
        row.parent_id = None
    db.flush()
    for item in chapters:
        db.get(DBChapter, mapping[item["id"]]).parent_id = mapping.get(item.get("parent_id"))
    for item in graph.get("source_refs", []):
        if item["source_document_id"] not in mapping:
            continue
        ref_id = _copied_ref(db, course.id, item, mapping[item['source_document_id']])
        row = db.get(DBSourceRef, ref_id)
        if row is None:
            row = DBSourceRef(id=ref_id)
            db.add(row)
        for key, value in item.items():
            if key not in {"id", "source_document_id", "chapter_id"}:
                setattr(row, key, value)
        row.source_document_id = mapping[item["source_document_id"]]
        row.chapter_id = mapping.get(item.get("chapter_id"))
        mapping[item["id"]] = row.id
    db.flush()
    for item in graph.get("knowledge_points", []):
        chapter_id = mapping.get(item["chapter_id"])
        if chapter_id and not db.query(DBChapterKnowledgePoint).filter_by(chapter_id=chapter_id, knowledge_point_id=item["knowledge_point_id"], relation_type=item["relation_type"]).first():
            db.add(DBChapterKnowledgePoint(chapter_id=chapter_id, knowledge_point_id=item["knowledge_point_id"], relation_type=item["relation_type"]))
    db.flush()
    return mapping


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
    _material_mapping(db, course, snapshot, actor=actor)
    apply_source_graph(db, course, snapshot)


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


def _local_snapshot(db: Any, copy: DBCourseDerivedCopy) -> dict[str, Any]:
    snapshot = _snapshot(db, _course(db, copy.derived_course_id))[0]
    original_title = copy.baseline_snapshot['course']['title']
    if snapshot['course']['title'] == f'{original_title}（派生副本）':
        snapshot['course']['title'] = original_title
    return snapshot


def _changes(base: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for key in ("version", "title", "subject", "description", "domain_pack", "language", "content_origin", "manifest_version", "manifest_data"):
        before, after = base["course"].get(key), candidate["course"].get(key)
        if before != after: result[f"course.{key}"] = {"before": before, "after": after}
    for section in ("documents", "sources"):
        def grouped(snapshot):
            result = {}
            for item in snapshot[section]: result.setdefault(item['filename'], []).append(item)
            return {name: sorted(items, key=_canonical) for name, items in result.items()}
        left, right = grouped(base), grouped(candidate)
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
    details = []
    labels = {"title":"课程名称", "subject":"学习方向", "description":"课程说明", "version":"课程版本", "language":"资料语言", "content_origin":"课程来源说明"}
    for path in upstream_changes:
        section, key = path.split('.', 1)
        if section == 'course':
            if key not in labels:
                continue
            label = labels[key]
            values = [str(s['course'].get(key) or '未填写') for s in (base, local, upstream)]
        elif section == 'documents':
            label = f'资料：{key}'
            values = []
            for snapshot in (base, local, upstream):
                documents = [item for item in snapshot['documents'] if item['filename'] == key]
                values.append('\n\n—— 同名的另一份资料 ——\n\n'.join(str(document.get('content') or '这份资料暂无正文') for document in documents) if documents else '尚未包含这份资料')
        elif section == 'sources' and f'documents.{key}' not in upstream_changes:
            label = f'来源说明：{key}'
            values = []
            for snapshot in (base, local, upstream):
                source = next((item for item in snapshot['sources'] if item['filename'] == key), None)
                values.append('\n'.join(str(source.get(field) or '') for field in ('title','source_url','license_text')).strip() or '课程内资料' if source else '尚未包含这份来源')
        else:
            continue
        details.append({'label':label, 'before':values[0], 'local':values[1], 'after':values[2], 'conflict':path in conflicts})
    return {"release": release_payload(latest), "local_changes": local_changes, "upstream_changes": upstream_changes,
        "change_details": details,
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
        merged = copy_module.deepcopy(release.snapshot_data)
        # Accept the teacher's changes while retaining unrelated personal edits.
        for path in preview['local_changes']:
            if path in preview['upstream_changes']: continue
            section, key = path.split('.', 1)
            if section == 'course': merged['course'][key] = frozen['local']['course'].get(key)
        _apply_snapshot(db, _course(db, copy.derived_course_id), merged, release.license_snapshot, actor)
        title = merged['course']['title']
        if title == release.snapshot_data['course']['title']: title = f'{title}（派生副本）'
        _course(db, copy.derived_course_id).title = title
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
