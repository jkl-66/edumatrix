from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

from fastapi import HTTPException
from sqlalchemy import and_, or_, select

from app.authorization import ObjectAccess, active_course_role, require_object_access
from app.database import DBChapter, DBCourse, DBCourseDocument, DBDocumentSelection, DBKnowledgeDocument, DBSourceDocument, DBSourceRef, DBUser
from app.identity import normalize_role


UNAVAILABLE_REASONS = {
    "source_ref_missing": "来源引用已移除",
    "source_document_missing": "来源文档已移除",
    "course_missing": "来源课程已移除",
    "course_conflict": "来源不属于当前课程",
    "permission_changed": "当前账号已无权查看该来源",
    "source_unavailable": "来源已撤回或暂不可用",
    "source_ref_version_changed": "来源解析版本已变化",
    "source_ref_content_changed": "来源内容版本已变化",
    "source_document_changed": "来源文档身份已变化",
    "document_version_changed": "原文版本已变化",
    "selection_stale": "选区对应的原文版本已变化",
}


def document_original_location(source_url: str, source_path: str, content: str = "") -> dict[str, Any]:
    """Resolve bundled files from recorded repository/revision and source boundaries.

    Older bundles put semicolon-separated paths into one blob URL. Project a
    valid repository/file link without rewriting source text or frozen citations.
    Ordinary web URLs (including valid semicolons) are left unchanged.
    """
    result = {"url": str(source_url or ""), "parts": []}
    provenance = re.fullmatch(r"[^@]+@([0-9a-fA-F]{40}):(.+)", str(source_path or ""))
    if not provenance:
        return result
    revision, raw_paths = provenance.groups()
    split = urlsplit(result["url"])
    repository = re.fullmatch(r"/([^/]+/[^/]+)/(?:blob|tree)/" + re.escape(revision) + r"(?:/.*)?", split.path)
    if split.scheme != "https" or split.netloc != "github.com" or not repository:
        return result
    base = f"https://github.com/{repository[1]}"
    paths = list(dict.fromkeys(path.strip() for path in raw_paths.split(";") if path.strip()))
    markers = list(re.finditer(r"^<!-- 上游文件:\s*(.+?)\s*-->\s*$", content, re.MULTILINE))
    for path in paths:
        ranges = [(marker.start(), markers[index + 1].start() if index + 1 < len(markers) else len(content))
                  for index, marker in enumerate(markers) if marker[1] == path]
        start, end = ranges[0] if len(ranges) == 1 else (0, len(content)) if len(paths) == 1 else (None, None)
        heading = re.search(r"^#{1,6}\s+(.+?)\s*$", content[start:end], re.MULTILINE) if start is not None else None
        result["parts"].append({"url": f"{base}/blob/{revision}/{quote(path, safe='/')}",
                                "title": heading[1] if heading else path.rsplit('/', 1)[-1],
                                "char_start": start, "char_end": end})
    if result["parts"]:
        result["url"] = result["parts"][0]["url"] if len(paths) == 1 else f"{base}/tree/{revision}"
    return result


def current_source_clause():
    """Browse/search the latest reading; keep old citations directly readable."""
    replacement = DBSourceDocument.parser_metadata["replaced_by_source_id"].as_string()
    retired = DBSourceDocument.parser_metadata["retired_from_catalog"].as_boolean()
    return and_(or_(replacement.is_(None), replacement == ""), or_(retired.is_(None), retired.is_(False)))


def current_chapter_clause():
    """Structure revisions keep historical chapter IDs readable by explicit links."""
    return ~DBChapter.stable_key.startswith('structure-history:')


def current_structure_ref_clause():
    """Retain page anchors; use only the current parser's active chapters."""
    history = select(DBChapter.id).where(~current_chapter_clause())
    current_parser = select(DBSourceDocument.id).where(
        DBSourceDocument.id == DBSourceRef.source_document_id,
        DBSourceDocument.parser_version == DBSourceRef.parser_version,
    ).correlate(DBSourceRef).exists()
    return and_(DBSourceRef.location_kind.not_in(('selection', 'reader_document')),
        or_(DBSourceRef.location_kind != 'chapter', and_(current_parser,
            or_(DBSourceRef.chapter_id.is_(None), DBSourceRef.chapter_id.not_in(history)))))


def _value(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value is not None and value != "":
            return value
    return None


def _document_version(source: DBSourceDocument | None) -> str:
    if source is None:
        return ""
    return str(source.processed_sha256 or source.content_hash or "")


def source_ref_teaching_text(db: Any, ref: DBSourceRef, *, max_chars: int | None = 12000) -> str:
    """Read a chapter's version-bound text, not its short citation preview.

    Fragment/image references keep their recorded quote. Never expand them to
    unrelated document text or silently substitute a changed document version.
    """
    source = db.get(DBSourceDocument, ref.source_document_id)
    if source is None or source.processing_status != "ready":
        return ""
    quote = str(ref.quote or "")
    if ref.location_kind in {"selection", "reader_document"} and ref.content_hash != _document_version(source):
        return ""
    if ref.location_kind != "chapter" or not source.legacy_document_id:
        return quote[:max_chars]
    document = db.get(DBCourseDocument, source.legacy_document_id)
    if document is not None and document.course_id != source.course_id:
        return ""
    if document is None:
        document = db.get(DBKnowledgeDocument, source.legacy_document_id)
    if document is None:
        return quote[:max_chars]
    content = str(document.content or "")
    version = _document_version(source)
    if hashlib.sha256(content.encode("utf-8")).hexdigest() != version:
        return ""
    if ref.content_hash != version or ref.parser_version != source.parser_version:
        return ""
    start, end = ref.char_start, ref.char_end
    if start is None or end is None or not 0 <= start < end <= len(content):
        return ""
    text = content[start:end]
    # Curated chapters retain provenance in the source, outside teaching text.
    marker = "## 精选教材内容"
    if marker in text:
        text = text.split(marker, 1)[1].lstrip()
    return text[:max_chars]


def _snapshot_value(snapshot: dict[str, Any], *keys: str, fallback: Any = None) -> Any:
    value = _value(snapshot, *keys)
    return fallback if value is None else value


def _authorize_source(db: Any, actor: DBUser, course: DBCourse, source: DBSourceDocument | None) -> None:
    if normalize_role(actor.role) == "admin":
        return
    public_id = str(actor.public_id)
    if course.owner_public_id == public_id or (source is not None and source.uploader_public_id == public_id):
        return
    role = active_course_role(db, course_id=course.id, user_public_id=public_id)
    require_object_access(
        actor,
        ObjectAccess(
            object_type="course",
            object_id=course.id,
            owner_public_id=course.owner_public_id,
            course_id=course.id,
            visibility="public" if course.visibility == "public" and course.status == "published" else "private",
        ),
        action="read",
        course_role=role,
    )


def _reader_route(projection: dict[str, Any]) -> str:
    document_id = str(projection.get("source_document_id") or "")
    if not document_id:
        return ""
    query = {
        "course_id": projection.get("course_id"),
        "source_ref_id": projection.get("source_ref_id"),
        "page": projection.get("page_number"),
        "chapter_id": projection.get("chapter_id"),
        "char_start": projection.get("char_start"),
    }
    encoded = urlencode({key: value for key, value in query.items() if value is not None and value != ""})
    route = f"/knowledge/documents/{document_id}"
    return f"{route}?{encoded}" if encoded else route


def _unavailable(projection: dict[str, Any], code: str) -> None:
    if projection.get("available") is False:
        return
    projection["available"] = False
    projection["reason_code"] = code
    projection["reason"] = UNAVAILABLE_REASONS[code]


def project_source_ref(
    db: Any,
    source_ref_id: str,
    *,
    actor: DBUser | None = None,
    expected_course_id: str | None = None,
    frozen: dict[str, Any] | None = None,
    permission_as_unavailable: bool = False,
    allow_missing_ref: bool = False,
) -> dict[str, Any]:
    """Project a current or frozen source reference without rewriting its history."""
    snapshot = dict(frozen or {})
    source_ref = db.get(DBSourceRef, source_ref_id) if source_ref_id else None
    source = db.get(DBSourceDocument, source_ref.source_document_id) if source_ref is not None else None
    frozen_document_id = str(_value(snapshot, "source_document_id", "sourceDocumentId", "documentId") or "")
    if source_ref is None and source is None and frozen_document_id:
        source = db.get(DBSourceDocument, frozen_document_id)
    course_id = str(
        _value(snapshot, "course_id", "courseId")
        or (source.course_id if source is not None else expected_course_id or "")
    )
    course = db.get(DBCourse, course_id) if course_id else None
    raw_chapter_id = (
        _value(snapshot, "chapter_id", "chapterId", "section_id", "sectionId")
        or (source_ref.chapter_id if source_ref is not None else None)
    )
    chapter_id = str(raw_chapter_id) if raw_chapter_id not in (None, "", "None") else None
    chapter = db.get(DBChapter, chapter_id) if chapter_id else None
    current_document_version = _document_version(source)
    frozen_parser_version = str(_value(snapshot, "parser_version", "parserVersion", "version") or "")
    frozen_content_hash = str(_value(snapshot, "content_hash", "contentHash") or "")
    frozen_document_version = str(_value(snapshot, "document_version", "documentVersion") or "")
    # A recovered original may have a new storage ID. Resolve only its recorded
    # predecessor and exact version; never redirect a frozen citation to new text.
    metadata = dict(source.parser_metadata or {}) if source is not None else {}
    frozen_versions = [v for v in (frozen_content_hash, frozen_document_version) if v]
    restored_original = bool(
        source is not None and source_ref is not None and frozen_document_id
        and frozen_document_id == metadata.get("restored_from_source_id")
        and frozen_versions and all(v == current_document_version for v in frozen_versions)
        and source_ref.content_hash == current_document_version
        and source_ref.parser_version == source.parser_version
        and (not frozen_parser_version or frozen_parser_version == source.parser_version)
    )
    if restored_original:
        chapter_id = (metadata.get("restored_chapter_ids") or {}).get(chapter_id, chapter_id)
        chapter = db.get(DBChapter, chapter_id) if chapter_id else None
    projection = {
        "schema_version": "edumatrix.source-ref.v1",
        "kind": "canonical_source",
        "source_ref_id": str(source_ref_id or _value(snapshot, "source_ref_id", "sourceRefId", "id") or ""),
        "course_id": course_id,
        "source_document_id": str(
            source.id if restored_original else frozen_document_id or (source.id if source is not None else "")
        ),
        "document_version": frozen_document_version or current_document_version,
        "chapter_id": chapter_id,
        "chapter_title": str(_value(snapshot, "chapter_title", "chapterTitle", "section_title", "sectionTitle") or (chapter.title if chapter else "")),
        "parser_version": frozen_parser_version or (source_ref.parser_version if source_ref is not None else ""),
        "page_number": _snapshot_value(snapshot, "page_number", "pageNumber", fallback=source_ref.page_number if source_ref else None),
        "char_start": _snapshot_value(snapshot, "char_start", "charStart", fallback=source_ref.char_start if source_ref else None),
        "char_end": _snapshot_value(snapshot, "char_end", "charEnd", fallback=source_ref.char_end if source_ref else None),
        "image_region": _snapshot_value(snapshot, "image_region", "imageRegion", "normalized_rect", "normalizedRect", fallback=source_ref.image_region if source_ref else None),
        "location_kind": str(_value(snapshot, "location_kind", "locationKind") or (source_ref.location_kind if source_ref else "")),
        "location_index": _snapshot_value(snapshot, "location_index", "locationIndex", fallback=source_ref.location_index if source_ref else None),
        "location_label": str(_value(snapshot, "location_label", "locationLabel") or (source_ref.location_label if source_ref else "")),
        "location_metadata": dict(_snapshot_value(snapshot, "location_metadata", "locationMetadata", fallback=source_ref.location_metadata if source_ref else {}) or {}),
        "content_hash": frozen_content_hash or (source_ref.content_hash if source_ref is not None else ""),
        "title": str(_value(snapshot, "title") or (source.title if source is not None else "来源")),
        "filename": str(_value(snapshot, "filename") or (source.filename if source is not None else "")),
        "quote": str(_value(snapshot, "quote") or (source_ref.quote if source_ref is not None else "")),
        "processing_status": str(source.processing_status if source is not None else _value(snapshot, "processing_status", "processingStatus") or "missing"),
        "available": True,
        "reason_code": "",
        "reason": "",
        "historical": bool(snapshot),
    }
    if source_ref is None and not (allow_missing_ref and source is not None):
        _unavailable(projection, "source_ref_missing")
    elif source is None:
        _unavailable(projection, "source_document_missing")
    elif course is None:
        _unavailable(projection, "course_missing")
    elif expected_course_id and course.id != expected_course_id:
        _unavailable(projection, "course_conflict")
    if source is not None and frozen_document_id and frozen_document_id != source.id and not restored_original:
        _unavailable(projection, "source_document_changed")
    if source is not None and course_id and source.course_id != course_id:
        _unavailable(projection, "course_conflict")
    if course is not None and actor is not None:
        try:
            _authorize_source(db, actor, course, source)
        except HTTPException:
            if not permission_as_unavailable:
                raise
            _unavailable(projection, "permission_changed")
    if source is not None and source.processing_status != "ready":
        _unavailable(projection, "source_unavailable")
    if source is not None and source_ref is not None and source_ref.location_kind == 'chapter' and source_ref.parser_version != source.parser_version:
        _unavailable(projection, "source_ref_version_changed")
    if source is not None and source_ref is not None and source_ref.location_kind == 'chapter' and source_ref.content_hash != current_document_version:
        _unavailable(projection, "source_ref_content_changed")
    if source is not None and source_ref is not None and source_ref.location_kind in {'selection', 'reader_document'} and source_ref.content_hash != current_document_version:
        _unavailable(projection, "document_version_changed")
    if source_ref is not None and frozen_parser_version and frozen_parser_version != source_ref.parser_version:
        _unavailable(projection, "source_ref_version_changed")
    if source_ref is not None and frozen_content_hash and frozen_content_hash != source_ref.content_hash:
        _unavailable(projection, "source_ref_content_changed")
    if source is not None and frozen_document_version and frozen_document_version != current_document_version:
        _unavailable(projection, "document_version_changed")
    projection["route"] = _reader_route(projection)
    return projection


def require_source_ref_projection(db: Any, actor: DBUser, source_ref_id: str) -> dict[str, Any]:
    projection = project_source_ref(db, source_ref_id, actor=actor)
    if projection["reason_code"] == "source_ref_missing":
        raise HTTPException(status_code=404, detail="来源引用不存在")
    return projection


def project_selection(
    db: Any,
    actor: DBUser,
    selection: DBDocumentSelection,
) -> dict[str, Any]:
    if selection.owner_public_id != actor.public_id:
        raise HTTPException(status_code=403, detail="无权读取该选区")
    frozen = {
        "source_document_id": selection.source_document_id,
        "document_version": selection.document_version,
        "chapter_id": selection.section_id,
        "page_number": selection.page_number,
        "char_start": selection.char_start,
        "char_end": selection.char_end,
        "image_region": selection.normalized_rect,
        "quote": selection.quote or selection.ocr_text or "",
    }
    projection = project_source_ref(
        db,
        str(selection.source_ref_id or ""),
        actor=actor,
        frozen=frozen,
        permission_as_unavailable=True,
        allow_missing_ref=True,
    )
    projection.update({
        "selection_id": selection.id,
        "selection_type": selection.selection_type,
        "image_region": selection.normalized_rect,
        "quote": selection.quote or selection.ocr_text or projection["quote"],
    })
    source = db.get(DBSourceDocument, selection.source_document_id)
    if selection.status == "stale" or source is None or _document_version(source) != selection.document_version:
        _unavailable(projection, "selection_stale")
    projection["route"] = _reader_route(projection)
    return projection


def chat_source_ref(projection: dict[str, Any]) -> dict[str, Any]:
    """Freeze the canonical projection in the existing Chat camel-case contract."""
    return {
        "kind": "canonical_source",
        "sourceRefId": projection["source_ref_id"],
        "courseId": projection["course_id"],
        "sourceDocumentId": projection["source_document_id"],
        "documentVersion": projection["document_version"],
        "chapterId": projection["chapter_id"],
        "chapterTitle": projection["chapter_title"],
        "parserVersion": projection["parser_version"],
        "version": projection["parser_version"],
        "pageNumber": projection["page_number"],
        "charStart": projection["char_start"],
        "charEnd": projection["char_end"],
        "imageRegion": projection["image_region"],
        "locationKind": projection["location_kind"],
        "locationIndex": projection["location_index"],
        "locationLabel": projection["location_label"],
        "locationMetadata": projection["location_metadata"],
        "contentHash": projection["content_hash"],
        "title": projection["title"],
        "filename": projection["filename"],
        "quote": projection["quote"],
        "available": projection["available"],
        "reasonCode": projection["reason_code"],
        "reason": projection["reason"],
        "route": projection["route"],
    }
