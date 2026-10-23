from __future__ import annotations

import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.database import (
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
    DBCourseDocument,
    DBChapterVideoLink,
    DBDocumentReadingPosition,
    DBDocumentSelection,
    DBKnowledgePoint,
    DBSourceDocument,
    DBSourceRef,
    DBUser,
    DBStudentProfile,
)
from document_parser import chunk_document, parse_document, parse_uploaded_file
from rag_engine import hybrid_rag


ROOT = Path(__file__).resolve().parent
M0_DIR = ROOT / "outputs" / "M0_阶段0基线与架构契约"
MANIFEST_PATH = M0_DIR / "datasets" / "course_manifest.json"
KNOWLEDGE_POINTS_PATH = M0_DIR / "datasets" / "core_knowledge_points.json"
ALL_CURATED_COURSE_MANIFESTS = (
    ROOT / "data" / "curated" / "machine_learning_foundations_v1" / "course_manifest.json",
    ROOT / "data" / "curated" / "embedded_edge_intelligence_v1" / "course_manifest.json",
    ROOT / "data" / "curated" / "embedded_machine_learning_engineering_v2" / "course_manifest.json",
    ROOT / "data" / "curated" / "ai_deep_learning_agents_v1" / "course_manifest.json",
    ROOT / "data" / "curated" / "data_structures_algorithms_v1" / "course_manifest.json",
)
# Only these two packaged courses are part of the user-facing built-in
# catalog.  The broader registry remains available to explicit migration and
# compatibility tooling, but default startup must never re-seed retired
# RAG/embedded/algorithm courses.
CANONICAL_BUILTIN_COURSE_MANIFESTS = (
    ALL_CURATED_COURSE_MANIFESTS[0],  # 机器学习基础与实践
    ALL_CURATED_COURSE_MANIFESTS[3],  # 人工智能与深度学习：...大模型智能体
)


class _CuratedManifestRegistry:
    """Indexed registry with a two-item iterator for legacy unpack callers.

    Older diagnostic helpers unpacked the original two-domain registry while
    newer seed code needs every packaged course.  Indexing remains complete;
    the explicit ``all`` view is used by production seeding.
    """

    def __init__(self, items: tuple[Path, ...]) -> None:
        self._items = items

    @property
    def all(self) -> tuple[Path, ...]:
        return self._items

    def __getitem__(self, index: int) -> Path:
        return self._items[index]

    def __iter__(self):
        return iter(self._items[:2])

    def __len__(self) -> int:
        return len(self._items)


CURATED_COURSE_MANIFESTS = _CuratedManifestRegistry(ALL_CURATED_COURSE_MANIFESTS)
MASTER_COURSE_ID = "course-ai-deep-learning-agents-v1"
SECONDARY_COURSE_ID = "course-data-structures-algorithms-engineering-v1"
FOUNDATIONS_COURSE_ID = "course-machine-learning-foundations-v1"
BUILTIN_COURSE_IDS = (FOUNDATIONS_COURSE_ID, MASTER_COURSE_ID)
PARSER_VERSION = "edumatrix-parser-v1"
CURATED_MANIFEST_SCHEMA = "edumatrix.course-version-manifest.v1"
COURSE_UPDATE_PREFLIGHT_SCHEMA = "edumatrix.course-update-preflight.v1"


def course_has_knowledge(session: Any, course_id: str) -> bool:
    """Whether a course has material that can actually be selected for study.

    A course remains in the database for history and audit, but selectors must
    not offer an empty or withdrawn shell.  Ready canonical sources are the
    preferred signal; published indexed documents and chapters with source
    references cover older seeded rows that predate course_documents.
    """
    source_ready = session.query(DBSourceDocument.id).filter(
        DBSourceDocument.course_id == course_id,
        DBSourceDocument.processing_status == "ready",
    ).first()
    if source_ready is not None:
        return True
    indexed_document = session.query(DBCourseDocument.id).filter(
        DBCourseDocument.course_id == course_id,
        DBCourseDocument.status == "published",
        DBCourseDocument.chunk_count > 0,
    ).first()
    if indexed_document is not None:
        return True
    chapter_with_source = (
        session.query(DBChapter.id)
        .filter(DBChapter.course_id == course_id, DBChapter.source_document_id.is_not(None))
        .first()
    )
    return chapter_with_source is not None


def course_is_selectable(session: Any, course_or_id: Any) -> bool:
    """Return whether a course may be offered as an active user choice.

    Historical course rows and withdrawn shells remain queryable for audit, but
    every active selector and context boundary uses this single predicate:
    published status plus at least one usable knowledge source.
    """
    course = course_or_id
    if not isinstance(course, DBCourse):
        course = session.get(DBCourse, str(course_or_id or ""))
    return bool(
        course is not None
        and course.status == "published"
        and course_has_knowledge(session, course.id)
    )


class CourseManifestConflict(ValueError):
    def __init__(self, report: dict[str, Any]):
        super().__init__("course_manifest_same_version_conflict")
        self.report = report


class CourseUpdateApprovalRequired(ValueError):
    def __init__(self, report: dict[str, Any]):
        super().__init__("course_version_update_requires_approval")
        self.report = report

# Frozen M0 chapter-to-KP teaching map. A KP may appear in more than one
# chapter; this is a real many-to-many relation rather than a chapter field.
CHAPTER_KP_CODES = {
    0: ("KP-01", "KP-28"),
    1: ("KP-01", "KP-02", "KP-03", "KP-32"),
    2: ("KP-04", "KP-05", "KP-06", "KP-07"),
    3: ("KP-08", "KP-09", "KP-10"),
    4: ("KP-11", "KP-12", "KP-13", "KP-14", "KP-15", "KP-30"),
    5: ("KP-16", "KP-17", "KP-18", "KP-19", "KP-20"),
    6: ("KP-21", "KP-22", "KP-23"),
    7: ("KP-24", "KP-25", "KP-26", "KP-27"),
    8: ("KP-28", "KP-29", "KP-30", "KP-31", "KP-32"),
}


def _document_id(course_id: str, relative_path: str) -> str:
    return hashlib.sha256(f"{course_id}:{relative_path}".encode("utf-8")).hexdigest()[:20]


def _stable_object_id(kind: str, *parts: str) -> str:
    identity = ":".join(str(part) for part in parts)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"{kind}-{digest}"


def _extract_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip() or fallback
    return fallback


def _canonical_manifest_bytes(path: Path, raw: bytes) -> bytes:
    """Return the platform-independent bytes covered by the course manifest."""
    if path.suffix.lower() in {".md", ".txt", ".csv", ".json"}:
        return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return raw


def _canonical_json_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _manifest_file_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for position, item in enumerate(manifest.get("files") or []):
        key = str(item.get("path") or item.get("source_path") or f"position:{position}")
        result[key] = {
            "position": int(item.get("chapter_order", position)),
            "sha256": str(item.get("sha256", "")).lower(),
            "source_sha256": str(item.get("source_sha256", "")).lower(),
            "source_path": str(item.get("source_path", "")),
            "repository_key": str(item.get("repository_key", "")),
            "git_revision": str(item.get("git_revision", "")),
            "parser_version": str(item.get("parser_version", PARSER_VERSION)),
            "license_spdx": str(item.get("license_spdx", "")),
            "license_sha256": str(item.get("license_sha256", "")).lower(),
            "knowledge_point_codes": sorted(str(code) for code in item.get("knowledge_point_codes", [])),
        }
    return result


def _course_manifest_diff(
    current_manifest: dict[str, Any], incoming_manifest: dict[str, Any]
) -> dict[str, Any]:
    current_files = _manifest_file_map(current_manifest)
    incoming_files = _manifest_file_map(incoming_manifest)
    current_keys = set(current_files)
    incoming_keys = set(incoming_files)
    common = sorted(current_keys & incoming_keys)
    content_changed = [
        key for key in common
        if current_files[key]["sha256"] != incoming_files[key]["sha256"]
    ]
    provenance_fields = {
        "source_sha256",
        "source_path",
        "repository_key",
        "git_revision",
        "parser_version",
        "license_spdx",
        "license_sha256",
    }
    provenance_changed = [
        key for key in common
        if any(current_files[key][field] != incoming_files[key][field] for field in provenance_fields)
    ]
    knowledge_mapping_changed = [
        key for key in common
        if current_files[key]["knowledge_point_codes"] != incoming_files[key]["knowledge_point_codes"]
    ]
    reordered = [
        key for key in common
        if current_files[key]["position"] != incoming_files[key]["position"]
    ]

    ignored_metadata = {"files", "knowledge_points", "generated_at", "manifest_version"}
    current_metadata = {
        key: value for key, value in current_manifest.items() if key not in ignored_metadata
    }
    incoming_metadata = {
        key: value for key, value in incoming_manifest.items() if key not in ignored_metadata
    }
    return {
        "added_files": sorted(incoming_keys - current_keys),
        "removed_files": sorted(current_keys - incoming_keys),
        "content_changed": content_changed,
        "provenance_changed": provenance_changed,
        "knowledge_mapping_changed": knowledge_mapping_changed,
        "reordered_files": reordered,
        "knowledge_points_changed": _canonical_json_hash(current_manifest.get("knowledge_points", []))
        != _canonical_json_hash(incoming_manifest.get("knowledge_points", [])),
        "license_changed": str(current_manifest.get("license", ""))
        != str(incoming_manifest.get("license", "")),
        "metadata_changed": _canonical_json_hash(current_metadata)
        != _canonical_json_hash(incoming_metadata),
    }


def preflight_course_bundle_update(session, bundle: dict[str, Any]) -> dict[str, Any]:
    course_data = bundle["course"]
    incoming_manifest = course_data.get("manifest_data")
    if not isinstance(incoming_manifest, dict) or not incoming_manifest:
        raise ValueError("course bundle must include a non-empty manifest_data object")
    incoming_version = str(course_data.get("manifest_version") or course_data.get("version") or "")
    if not incoming_version or incoming_version != str(course_data.get("version") or ""):
        raise ValueError("course bundle version and manifest_version must match")
    if incoming_version != str(incoming_manifest.get("manifest_version") or ""):
        raise ValueError("course bundle version differs from manifest payload")

    course = session.query(DBCourse).filter(DBCourse.id == course_data["id"]).first()
    incoming_hash = _canonical_json_hash(incoming_manifest)
    if course is None:
        return {
            "schema_version": COURSE_UPDATE_PREFLIGHT_SCHEMA,
            "course_id": course_data["id"],
            "status": "new_course",
            "requires_approval": False,
            "current_version": None,
            "incoming_version": incoming_version,
            "current_manifest_sha256": None,
            "incoming_manifest_sha256": incoming_hash,
            "diff": _course_manifest_diff({}, incoming_manifest),
        }

    current_manifest = course.manifest_data if isinstance(course.manifest_data, dict) else {}
    current_version = str(course.manifest_version or course.version or "")
    current_hash = _canonical_json_hash(current_manifest)
    if current_version == incoming_version and current_hash == incoming_hash:
        status = "unchanged"
        requires_approval = False
    elif current_version == incoming_version:
        status = "same_version_conflict"
        requires_approval = True
    else:
        status = "update_available"
        requires_approval = True
    return {
        "schema_version": COURSE_UPDATE_PREFLIGHT_SCHEMA,
        "course_id": course_data["id"],
        "status": status,
        "requires_approval": requires_approval,
        "current_version": current_version,
        "incoming_version": incoming_version,
        "current_manifest_sha256": current_hash,
        "incoming_manifest_sha256": incoming_hash,
        "diff": _course_manifest_diff(current_manifest, incoming_manifest),
    }


def load_m0_course_bundle(manifest_path: Path = MANIFEST_PATH) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    course_id = str(manifest["course_id"])
    documents = []

    for chapter_order, item in enumerate(manifest["files"]):
        relative_path = str(item["path"])
        path = M0_DIR / relative_path
        raw = _canonical_manifest_bytes(path, path.read_bytes())
        actual_hash = hashlib.sha256(raw).hexdigest().upper()
        expected_hash = str(item["sha256"]).upper()
        if len(raw) != int(item["bytes"]) or actual_hash != expected_hash:
            raise ValueError(f"Course manifest mismatch: {relative_path}")

        content = parse_uploaded_file(io.BytesIO(raw), path.name)
        source = f"{course_id}/{path.name}"
        chunks = chunk_document(content, source=source)
        tags = sorted(
            {
                "RAG工程",
                "预置课程",
                *(
                    tag
                    for chunk in chunks
                    for tag in chunk.tags
                    if tag and tag not in {"课程名称", "高校初始课程", "高校课程"}
                ),
            }
        )
        documents.append(
            {
                "id": _document_id(course_id, relative_path),
                "course_id": course_id,
                "chapter_order": chapter_order,
                "filename": path.name,
                "file_type": path.suffix.lstrip(".").lower(),
                "file_size": len(raw),
                "title": _extract_title(content, path.stem),
                "content": content,
                "tags": tags,
                "chunk_count": len(chunks),
                "content_hash": actual_hash,
                "source_path": relative_path,
                "license_text": manifest["license"],
                "status": "published",
                "chunks": chunks,
            }
        )

    return {
        "course": {
            "id": course_id,
            "version": manifest["manifest_version"],
            "title": manifest["title"],
            "subject": "人工智能 / RAG 工程",
            "description": "面向知识库构建、混合检索、引用约束、幻觉评测与故障恢复的完整实训课程。",
            "domain_pack": manifest["domain_pack"],
            "language": manifest["language"],
            "content_origin": manifest["content_origin"],
            "license_text": manifest["license"],
            "visibility": "public",
            "status": "published",
            "manifest_version": manifest["manifest_version"],
            "manifest_data": manifest,
        },
        "documents": documents,
    }


def _resolved_manifest_file(base_dir: Path, relative_path: str) -> Path:
    candidate = (base_dir / relative_path).resolve()
    try:
        candidate.relative_to(base_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"Course manifest path escapes its bundle: {relative_path}") from exc
    if not candidate.is_file():
        raise ValueError(f"Course manifest file is missing: {relative_path}")
    return candidate


def _resolved_curated_asset(base_dir: Path, asset_path: str) -> Path:
    raw_path = Path(asset_path)
    candidate = ((ROOT / raw_path) if raw_path.parts[:1] == ("data",) else (base_dir / raw_path)).resolve()
    try:
        candidate.relative_to(base_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"Curated course asset path escapes its bundle: {asset_path}") from exc
    if not candidate.is_file():
        raise ValueError(f"Curated course asset is missing: {asset_path}")
    return candidate


def _project_or_absolute_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def load_versioned_course_bundle(manifest_path: Path) -> dict[str, Any]:
    """Load one allowlisted curated course without reading its source repository."""
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != CURATED_MANIFEST_SCHEMA:
        raise ValueError("Unsupported curated course manifest schema")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("Curated course manifest must enumerate at least one file")
    orders = [item.get("chapter_order") for item in files]
    if orders != list(range(len(files))):
        raise ValueError("Curated course chapters must be unique and contiguous")
    known_codes = {item["code"] for item in manifest.get("knowledge_points", [])}
    if not known_codes:
        raise ValueError("Curated course must define knowledge points")

    base_dir = manifest_path.parent
    documents = []
    for item in files:
        required = {
            "path",
            "bytes",
            "sha256",
            "source_path",
            "source_sha256",
            "repository_url",
            "git_revision",
            "license_spdx",
            "license_file",
            "license_sha256",
            "knowledge_point_codes",
        }
        if not required.issubset(item):
            raise ValueError(f"Curated course file is missing required provenance: {item.get('path', '<unknown>')}")
        if not set(item["knowledge_point_codes"]).issubset(known_codes):
            raise ValueError(f"Curated course file references an unknown knowledge point: {item['path']}")
        if item["license_spdx"] not in {
            "MIT",
            "BSD-3-Clause",
            "Clear-BSD",
            "CC-BY-4.0",
            "CC-BY-NC-SA-4.0",
            "Apache-2.0",
            "OTHER",
        }:
            raise ValueError(f"Curated course file has an unsupported license: {item['path']}")
        if len(str(item["git_revision"])) != 40:
            raise ValueError(f"Curated course file has an unfrozen revision: {item['path']}")

        license_path = _resolved_manifest_file(base_dir, str(item["license_file"]))
        license_raw = _canonical_manifest_bytes(license_path, license_path.read_bytes())
        if hashlib.sha256(license_raw).hexdigest().lower() != str(item["license_sha256"]).lower():
            raise ValueError(f"Curated course license mismatch: {item['license_file']}")

        path = _resolved_manifest_file(base_dir, str(item["path"]))
        raw = _canonical_manifest_bytes(path, path.read_bytes())
        if len(raw) != int(item["bytes"]) or hashlib.sha256(raw).hexdigest().lower() != str(item["sha256"]).lower():
            raise ValueError(f"Curated course manifest mismatch: {item['path']}")
        index_path = None
        if item.get("index_text_path"):
            index_path = _resolved_manifest_file(base_dir, str(item["index_text_path"]))
            index_raw = _canonical_manifest_bytes(index_path, index_path.read_bytes())
            if len(index_raw) != int(item.get("index_text_bytes") or -1) or hashlib.sha256(index_raw).hexdigest().lower() != str(item.get("index_text_sha256") or "").lower():
                raise ValueError(f"Curated course index text mismatch: {item['index_text_path']}")
            content = parse_uploaded_file(io.BytesIO(index_raw), index_path.name)
        else:
            content = parse_uploaded_file(io.BytesIO(raw), path.name)
        reader_pages = []
        for page in item.get("reader_pages") or []:
            asset_path = _resolved_curated_asset(base_dir, str(page["asset_path"]))
            asset_raw = asset_path.read_bytes()
            if len(asset_raw) != int(page.get("asset_bytes") or -1) or hashlib.sha256(asset_raw).hexdigest().lower() != str(page.get("redacted_image_sha256") or "").lower():
                raise ValueError(f"Curated course reader page mismatch: {page.get('asset_path')}")
            reader_pages.append(dict(page))
        source = f"{manifest['course_id']}/{path.name}"
        chunks = chunk_document(content, source=source)
        source_url = (
            f"{str(item['repository_url']).removesuffix('.git')}/blob/"
            f"{item['git_revision']}/{item['source_path']}"
        )
        documents.append(
            {
                "id": _document_id(manifest["course_id"], str(item["path"])),
                "course_id": manifest["course_id"],
                "chapter_order": int(item["chapter_order"]),
                "filename": path.name,
                "file_type": path.suffix.lstrip(".").lower(),
                "file_size": len(raw),
                "title": str(item.get("title") or _extract_title(content, path.stem)),
                "content": content,
                "tags": list(dict.fromkeys([
                    *manifest.get("tags", []),
                    "预置课程",
                    *item["knowledge_point_codes"],
                ])),
                "chunk_count": len(chunks),
                "content_hash": hashlib.sha256(raw).hexdigest().upper(),
                "source_sha256": str(item["source_sha256"]).lower(),
                "source_path": f"{item['repository_key']}@{item['git_revision']}:{item['source_path']}",
                "source_url": source_url,
                "license_text": manifest["license"],
                "parser_version": str(item["parser_version"]),
                "source_role": str(item.get("source_role") or ""),
                "knowledge_point_codes": list(item["knowledge_point_codes"]),
                "chapter_key": str(item.get("chapter_key") or f"document:{item['path']}"),
                "chapter_position": int(item.get("chapter_position", item["chapter_order"])),
                "parent_chapter_key": str(item.get("parent_chapter_key") or ""),
                "bundle_asset": {
                    "path": _project_or_absolute_path(path),
                    "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                },
                "reader_pages": reader_pages,
                "reader_page_engine": str(item.get("reader_page_engine") or ""),
                "media": dict(item.get("media") or {}),
                "index_text_path": _project_or_absolute_path(index_path) if index_path else "",
                "status": "published",
                "chunks": chunks,
            }
        )

    return {
        "course": {
            "id": manifest["course_id"],
            "version": manifest["manifest_version"],
            "title": manifest["title"],
            "subject": manifest["subject"],
            "description": manifest["description"],
            "domain_pack": manifest["domain_pack"],
            "language": manifest["language"],
            "content_origin": manifest["content_origin"],
            "license_text": manifest["license"],
            "visibility": manifest["visibility"],
            "status": manifest["status"],
            "manifest_version": manifest["manifest_version"],
            "manifest_data": manifest,
        },
        "knowledge_point_version": manifest["knowledge_point_version"],
        "knowledge_points": manifest["knowledge_points"],
        "documents": documents,
    }


def upsert_course_bundle(
    session,
    bundle: dict[str, Any],
    *,
    approve_version_change: bool = False,
    expected_current_version: str | None = None,
    expected_incoming_version: str | None = None,
) -> dict[str, int]:
    preflight = preflight_course_bundle_update(session, bundle)
    if preflight["status"] == "same_version_conflict":
        raise CourseManifestConflict(preflight)
    if preflight["status"] == "update_available":
        if not approve_version_change:
            raise CourseUpdateApprovalRequired(preflight)
        if (
            expected_current_version != preflight["current_version"]
            or expected_incoming_version != preflight["incoming_version"]
        ):
            raise ValueError("course_version_approval_expectation_mismatch")

    course_data = bundle["course"]
    course = session.query(DBCourse).filter(DBCourse.id == course_data["id"]).first()
    if course is None:
        course = DBCourse(id=course_data["id"])
        session.add(course)
    for key, value in course_data.items():
        setattr(course, key, value)

    inserted = 0
    updated = 0
    active_ids = set()
    for item in bundle["documents"]:
        active_ids.add(item["id"])
        document = (
            session.query(DBCourseDocument)
            .filter(DBCourseDocument.id == item["id"])
            .first()
        )
        if document is None:
            document = DBCourseDocument(id=item["id"])
            session.add(document)
            inserted += 1
        else:
            updated += 1
        for key, value in item.items():
            if key in {
                "course_id", "chapter_order", "filename", "file_type", "file_size",
                "title", "content", "tags", "chunk_count", "content_hash", "source_path",
                "license_text", "status",
            }:
                setattr(document, key, value)

    stale = (
        session.query(DBCourseDocument)
        .filter(DBCourseDocument.course_id == course_data["id"])
        .all()
    )
    removed = 0
    for document in stale:
        if document.id not in active_ids:
            session.delete(document)
            removed += 1
    _sync_canonical_course_objects(session, bundle)
    session.commit()
    # Preserve the M0 caller contract. Canonical M1 objects are verified via
    # their repositories/tables rather than extending this legacy result.
    return {"inserted": inserted, "updated": updated, "removed": removed}


def apply_course_bundle_update(
    session,
    bundle: dict[str, Any],
    *,
    expected_current_version: str,
    expected_incoming_version: str,
) -> dict[str, int]:
    """Apply a reviewed version transition with compare-and-set expectations."""
    return upsert_course_bundle(
        session,
        bundle,
        approve_version_change=True,
        expected_current_version=expected_current_version,
        expected_incoming_version=expected_incoming_version,
    )


def _sync_canonical_course_objects(session, bundle: dict[str, Any]) -> dict[str, int]:
    """Idempotently project a course bundle into canonical M1 objects."""
    course = bundle["course"]
    if bundle.get("knowledge_points"):
        domain_id = course["domain_pack"]
        point_version = bundle["knowledge_point_version"]
        point_items = [
            {
                "id": item["code"],
                "title": item["title"],
                "level": item.get("level", "core"),
                "prerequisites": item.get("prerequisites", []),
            }
            for item in bundle["knowledge_points"]
        ]
    else:
        gold = json.loads(KNOWLEDGE_POINTS_PATH.read_text(encoding="utf-8"))
        domain_id = gold["domain_id"]
        point_version = gold["gold_version"]
        point_items = gold["points"]
    points_by_code: dict[str, DBKnowledgePoint] = {}
    for item in point_items:
        point = (
            session.query(DBKnowledgePoint)
            .filter(
                DBKnowledgePoint.domain_pack == domain_id,
                DBKnowledgePoint.code == item["id"],
                DBKnowledgePoint.version == point_version,
            )
            .first()
        )
        if point is None:
            point = DBKnowledgePoint(
                id=_stable_object_id("kp", domain_id, item["id"], point_version),
                domain_pack=domain_id,
                code=item["id"],
                version=point_version,
            )
            session.add(point)
        point.title = item["title"]
        point.level = item["level"]
        point.prerequisites = item.get("prerequisites", [])
        point.status = "active"
        session.flush()
        points_by_code[item["id"]] = point

    source_count = chapter_count = ref_count = relation_count = 0
    chapter_by_key: dict[str, DBChapter] = {}
    parent_key_by_chapter: dict[str, str] = {}
    for item in bundle["documents"]:
        source = (
            session.query(DBSourceDocument)
            .filter(
                DBSourceDocument.course_id == course["id"],
                DBSourceDocument.legacy_document_id == item["id"],
            )
            .first()
        )
        if source is None:
            source = DBSourceDocument(
                id=_stable_object_id("src", course["id"], item["id"]),
                course_id=course["id"], legacy_document_id=item["id"]
            )
            session.add(source)
            source_count += 1
        source.title = item["title"]
        source.filename = item["filename"]
        source.file_format = item["file_type"]
        source.content_hash = item["content_hash"]
        source.source_sha256 = item.get("source_sha256", item["content_hash"])
        source.processed_sha256 = hashlib.sha256(item["content"].encode("utf-8")).hexdigest()
        source.file_size = item["file_size"]
        source.source_path = item["source_path"]
        source.source_url = item.get("source_url", course["content_origin"])
        source.license_text = item["license_text"]
        parser_version = item.get("parser_version", PARSER_VERSION)
        source.parser_version = parser_version
        source.parser_metadata = {
            "origin": "versioned_course_bundle",
            "manifest_version": course.get("manifest_version", course.get("version", "")),
            "bundle_asset": dict(item.get("bundle_asset") or {}),
            "media": dict(item.get("media") or {}),
            "index_text_path": str(item.get("index_text_path") or ""),
            "source_role": str(item.get("source_role") or ""),
        }
        if item.get("reader_pages"):
            source.parser_metadata["ocr"] = {
                "schema_version": "edumatrix.ocr-document.v1",
                "status": "ready",
                "engine": {
                    "name": item.get("reader_page_engine") or "curated_page_assets",
                    "version": "1",
                    "mode": "offline_prebuilt",
                },
                "source_sha256": item.get("bundle_asset", {}).get("sha256", ""),
                "page_count": len(item["reader_pages"]),
                "region_count": sum(len(page.get("regions") or []) for page in item["reader_pages"]),
                "external_model_used": False,
                "pages": list(item["reader_pages"]),
            }
        source.parse_warnings = []
        source.processing_error_code = ""
        source.processing_status = "ready"
        session.flush()

        stable_key = str(item.get("chapter_key") or f"document:{item['id']}")
        chapter = (
            session.query(DBChapter)
            .filter(DBChapter.course_id == course["id"], DBChapter.stable_key == stable_key)
            .first()
        )
        if chapter is None:
            # Older course seeds used the legacy document id as the stable key.
            # Reuse that chapter when a manifest later supplies its canonical
            # chapter key; otherwise startup creates a second chapter for the
            # same source document and collides with the old source reference id.
            legacy_stable_key = f"document:{item['id']}"
            if legacy_stable_key != stable_key:
                chapter = (
                    session.query(DBChapter)
                    .filter(
                        DBChapter.course_id == course["id"],
                        DBChapter.stable_key == legacy_stable_key,
                        DBChapter.source_document_id == source.id,
                    )
                    .first()
                )
                if chapter is not None:
                    chapter.stable_key = stable_key
        if chapter is None:
            chapter = DBChapter(
                id=_stable_object_id("ch", course["id"], stable_key),
                course_id=course["id"],
                source_document_id=source.id,
                stable_key=stable_key,
            )
            session.add(chapter)
            chapter_count += 1
        chapter.source_document_id = source.id
        chapter.title = item["title"]
        chapter.position = int(item.get("chapter_position", item["chapter_order"]))
        chapter.heading_level = 1
        chapter.char_start = 0
        chapter.char_end = len(item["content"])
        session.flush()
        chapter_by_key[stable_key] = chapter
        parent_key_by_chapter[chapter.id] = str(item.get("parent_chapter_key") or "")

        source_ref = (
            session.query(DBSourceRef)
            .filter(
                DBSourceRef.source_document_id == source.id,
                DBSourceRef.chapter_id == chapter.id,
                DBSourceRef.parser_version == parser_version,
            )
            .first()
        )
        if source_ref is None:
            source_ref = DBSourceRef(
                # Include the chapter so one source document can safely expose
                # more than one independently locatable chapter.
                id=_stable_object_id("ref", source.id, chapter.id, parser_version),
                source_document_id=source.id,
                chapter_id=chapter.id,
                parser_version=parser_version,
            )
            session.add(source_ref)
            ref_count += 1
        source_ref.char_start = 0
        source_ref.char_end = len(item["content"])
        source_ref.location_kind = "chapter"
        source_ref.location_index = item["chapter_order"]
        source_ref.location_label = item["title"]
        source_ref.location_metadata = {}
        source_ref.content_hash = source.processed_sha256
        source_ref.quote = item["content"][:300]

        active_point_ids = set()
        chapter_codes = item.get("knowledge_point_codes", CHAPTER_KP_CODES.get(item["chapter_order"], ()))
        for code in chapter_codes:
            point = points_by_code[code]
            active_point_ids.add(point.id)
            relation = (
                session.query(DBChapterKnowledgePoint)
                .filter(
                    DBChapterKnowledgePoint.chapter_id == chapter.id,
                    DBChapterKnowledgePoint.knowledge_point_id == point.id,
                    DBChapterKnowledgePoint.relation_type == "teaches",
                )
                .first()
            )
            if relation is None:
                session.add(
                    DBChapterKnowledgePoint(
                        chapter_id=chapter.id,
                        knowledge_point_id=point.id,
                        relation_type="teaches",
                    )
                )
                relation_count += 1
        for relation in (
            session.query(DBChapterKnowledgePoint)
            .filter(DBChapterKnowledgePoint.chapter_id == chapter.id)
            .all()
        ):
            if relation.knowledge_point_id not in active_point_ids:
                session.delete(relation)

    for chapter_id, parent_key in parent_key_by_chapter.items():
        chapter = session.get(DBChapter, chapter_id)
        if chapter is None:
            continue
        if not parent_key:
            chapter.parent_id = None
            continue
        parent = chapter_by_key.get(parent_key)
        if parent is None:
            raise ValueError(f"Curated course parent chapter is missing: {parent_key}")
        chapter.parent_id = parent.id

    # When a manifest introduces explicit chapter keys after an older seed used
    # ``document:<document_id>``, both keys can temporarily point at the same
    # source. Keep the manifest chapter and remove only unreferenced aliases so
    # graph/path consumers never render duplicate chapters.
    duplicate_chapters_removed = 0
    for item in bundle["documents"]:
        stable_key = str(item.get("chapter_key") or f"document:{item['id']}")
        canonical = chapter_by_key.get(stable_key)
        if canonical is None:
            continue
        duplicate_rows = session.query(DBChapter).filter(
            DBChapter.source_document_id == canonical.source_document_id,
            DBChapter.id != canonical.id,
        ).all()
        for duplicate in duplicate_rows:
            has_user_history = bool(
                session.query(DBDocumentReadingPosition.id).filter_by(section_id=duplicate.id).first()
                or session.query(DBDocumentSelection.id).filter_by(section_id=duplicate.id).first()
                or session.query(DBChapterVideoLink.id).filter_by(chapter_id=duplicate.id).first()
                or session.query(DBChapter.id).filter_by(parent_id=duplicate.id).first()
            )
            if has_user_history:
                continue
            session.query(DBSourceRef).filter(
                DBSourceRef.chapter_id == duplicate.id
            ).delete(synchronize_session=False)
            session.query(DBChapterKnowledgePoint).filter(
                DBChapterKnowledgePoint.chapter_id == duplicate.id
            ).delete(synchronize_session=False)
            session.delete(duplicate)
            duplicate_chapters_removed += 1

    # A course version may replace an earlier manifest whose document IDs were
    # generated differently.  Remove those no-longer-declared canonical rows so
    # graph/path consumers see one chapter per active manifest file.  Preserve
    # any source that already has user-owned reading/selection/video records;
    # those rows are retired rather than deleting learning history.
    incoming_document_ids = {str(item["id"]) for item in bundle["documents"]}
    stale_sources = (
        session.query(DBSourceDocument)
        .filter(
            DBSourceDocument.course_id == course["id"],
            ~DBSourceDocument.legacy_document_id.in_(incoming_document_ids),
        )
        .all()
    )
    stale_removed = stale_retired = 0
    for source in stale_sources:
        stale_chapters = session.query(DBChapter).filter_by(source_document_id=source.id).all()
        chapter_ids = [chapter.id for chapter in stale_chapters]
        has_user_history = bool(
            session.query(DBDocumentReadingPosition.id).filter_by(source_document_id=source.id).first()
            or session.query(DBDocumentSelection.id).filter_by(source_document_id=source.id).first()
            or (
                chapter_ids
                and session.query(DBDocumentSelection.id)
                .filter(DBDocumentSelection.section_id.in_(chapter_ids))
                .first()
            )
            or (
                chapter_ids
                and session.query(DBChapterVideoLink.id)
                .filter(DBChapterVideoLink.chapter_id.in_(chapter_ids))
                .first()
            )
        )
        if has_user_history:
            source.processing_status = "retired"
            stale_retired += 1
            continue
        if chapter_ids:
            session.query(DBSourceRef).filter(
                DBSourceRef.source_document_id == source.id
            ).delete(synchronize_session=False)
            session.query(DBChapterKnowledgePoint).filter(
                DBChapterKnowledgePoint.chapter_id.in_(chapter_ids)
            ).delete(synchronize_session=False)
            session.query(DBChapter).filter(
                DBChapter.id.in_(chapter_ids)
            ).delete(synchronize_session=False)
        session.delete(source)
        stale_removed += 1

    return {
        "source_documents": source_count,
        "chapters": chapter_count,
        "source_refs": ref_count,
        "chapter_kp_relations": relation_count,
        "stale_sources_removed": stale_removed,
        "stale_sources_retired": stale_retired,
        "duplicate_chapters_removed": duplicate_chapters_removed,
    }


def ingest_course_bundle(bundle: dict[str, Any]) -> int:
    from app.m5_source_locator import build_evidence_locations

    course = bundle["course"]
    total = 0
    for document in bundle["documents"]:
        source = f"{course['id']}/{document['filename']}"
        source_document_id = _stable_object_id("src", course["id"], document["id"])
        chapter_id = _stable_object_id("ch", course["id"], f"document:{document['id']}")
        parser_version = document.get("parser_version", PARSER_VERSION)
        source_ref_id = _stable_object_id("ref", source_document_id, parser_version)
        evidence_locations = build_evidence_locations(
            document["content"], document["chunks"]
        )
        locatable_chunks = tuple(
            replace(
                item,
                title=f"{document['title']} / {item.title}",
                tags=tuple(dict.fromkeys((*item.tags, document["title"], *document.get("knowledge_point_codes", [])))),
                metadata={
                    **item.metadata,
                    "source_document_id": source_document_id,
                    "chapter_id": chapter_id,
                    "source_ref_id": source_ref_id,
                    "evidence_char_start": evidence_locations[item.id].char_start,
                    "evidence_char_end": evidence_locations[item.id].char_end,
                    "evidence_fragment_hash": evidence_locations[item.id].fragment_hash,
                    "source_ref_content_hash": hashlib.sha256(
                        document["content"].encode("utf-8")
                    ).hexdigest(),
                    "parser_version": parser_version,
                },
            )
            for item in document["chunks"]
        )
        hybrid_rag.remove_course_documents(source, course["id"])
        hybrid_rag.ingest_course_documents(
            locatable_chunks,
            course_id=course["id"],
            course_metadata={
                "course_title": course["title"],
                "course_version": course["version"],
                "document_id": document["id"],
                "document_title": document["title"],
                "content_hash": document["content_hash"],
                "source_path": document["source_path"],
            },
        )
        total += len(document["chunks"])
    return total


def seed_m0_course(session) -> dict[str, Any]:
    bundle = load_m0_course_bundle()
    result = upsert_course_bundle(session, bundle)
    result["chunks"] = ingest_course_bundle(bundle)
    result["course_id"] = bundle["course"]["id"]
    result["documents"] = len(bundle["documents"])
    try:
        from learning_strategy import invalidate_graph_cache

        invalidate_graph_cache()
    except Exception:
        pass
    return result


def seed_default_courses(session) -> dict[str, Any]:
    """Seed only the two canonical AI foundation courses.

    Retired course manifests stay readable through the explicit registry for
    migration/test tooling, but are intentionally excluded from normal
    startup so a cleanup cannot be undone by the next restart.
    """
    bundles = [load_versioned_course_bundle(path) for path in CANONICAL_BUILTIN_COURSE_MANIFESTS]
    courses = []
    total_documents = total_chunks = 0
    for bundle in bundles:
        preflight = preflight_course_bundle_update(session, bundle)
        if preflight["status"] == "update_available":
            documents = session.query(DBCourseDocument).filter_by(
                course_id=bundle["course"]["id"]
            ).count()
            courses.append(
                {
                    "course_id": bundle["course"]["id"],
                    "status": "update_available",
                    "documents": documents,
                    "chunks": 0,
                    "inserted": 0,
                    "updated": 0,
                    "removed": 0,
                    "preflight": preflight,
                }
            )
            total_documents += documents
            continue
        result = upsert_course_bundle(session, bundle)
        chunks = ingest_course_bundle(bundle)
        documents = len(bundle["documents"])
        courses.append(
            {
                "course_id": bundle["course"]["id"],
                "status": "ready",
                "documents": documents,
                "chunks": chunks,
                **result,
            }
        )
        total_documents += documents
        total_chunks += chunks
    try:
        from learning_strategy import invalidate_graph_cache

        invalidate_graph_cache()
    except Exception:
        pass
    # The unified course is a built-in context for every active account.  The
    # projection is deliberately idempotent so startup and registration can
    # safely call it more than once.
    membership_result = ensure_primary_course_memberships(session)
    courses.append({"course_id": MASTER_COURSE_ID, "status": "memberships_projected", **membership_result})
    return {
        "course_count": len([item for item in courses if item.get("status") != "memberships_projected"]),
        "documents": total_documents,
        "chunks": total_chunks,
        "courses": courses,
    }


def _ensure_builtin_course_memberships(session: Any, user: DBUser) -> int:
    """Ensure one user has every published built-in course in their context."""
    from app.database import DBCourseMembership

    role = str(user.role or "student")
    if role not in {"admin", "teacher", "assistant", "student", "visitor"}:
        role = "student"
    changed = 0
    for course_id in BUILTIN_COURSE_IDS:
        course = session.get(DBCourse, course_id)
        if course is None or course.status != "published":
            continue
        membership = session.query(DBCourseMembership).filter_by(
            course_id=course_id, user_public_id=user.public_id,
        ).first()
        if membership is None:
            session.add(DBCourseMembership(
                course_id=course_id,
                user_public_id=user.public_id,
                role=role,
                status="active",
            ))
            changed += 1
            continue
        repaired = membership.role != role or membership.status != "active"
        membership.role = role
        membership.status = "active"
        changed += int(repaired)
    return changed


def ensure_primary_course_membership(session: Any, user: DBUser) -> bool:
    """Backward-compatible entry point that projects all built-in courses."""
    return bool(_ensure_builtin_course_memberships(session, user))


def ensure_primary_course_memberships(session: Any) -> dict[str, int]:
    """Project the master course onto every active account and clean lzz."""
    from app.database import DBCourseMembership

    users = session.query(DBUser).filter(DBUser.is_active.is_(True)).all()
    created_or_repaired = sum(int(_ensure_builtin_course_memberships(session, user)) for user in users)
    # Keep the historic metric stable for callers that used it as the master
    # projection count, while exposing the complete built-in projection count.
    builtin_created_or_repaired = created_or_repaired
    lzz = next((user for user in users if user.username == "lzz"), None)
    removed = 0
    profile_updated = 0
    course = session.get(DBCourse, MASTER_COURSE_ID)
    if lzz is not None and course is not None:
        other_memberships = session.query(DBCourseMembership).filter(
            DBCourseMembership.user_public_id == lzz.public_id,
            ~DBCourseMembership.course_id.in_(BUILTIN_COURSE_IDS),
            DBCourseMembership.status != "removed",
        ).all()
        for membership in other_memberships:
            membership.status = "removed"
            removed += 1
        profile = session.get(DBStudentProfile, lzz.username)
        if profile is None:
            profile = DBStudentProfile(student_id=lzz.username)
            session.add(profile)
        if profile.target_course != course.title:
            profile.target_course = course.title
            profile_updated = 1
    session.commit()
    return {
        "active_users": len(users),
        "memberships_created_or_repaired": created_or_repaired,
        "builtin_memberships_created_or_repaired": builtin_created_or_repaired,
        "lzz_memberships_removed": removed,
        "lzz_profile_updated": profile_updated,
    }


def published_course_provenance() -> list[dict[str, Any]]:
    """Return published course/document provenance for downstream graph consumers."""
    try:
        from app.database import DBCourse, DBCourseDocument, SessionLocal

        session = SessionLocal()
        try:
            rows = (
                session.query(DBCourse, DBCourseDocument)
                .join(DBCourseDocument, DBCourseDocument.course_id == DBCourse.id)
                .filter(
                    DBCourse.status == "published",
                    DBCourse.visibility == "public",
                    DBCourseDocument.status == "published",
                )
                .order_by(DBCourse.id, DBCourseDocument.chapter_order)
                .all()
            )
            source_roles = {
                source.legacy_document_id: str((source.parser_metadata or {}).get("source_role") or "")
                for source in session.query(DBSourceDocument).filter(
                    DBSourceDocument.course_id.in_({course.id for course, _document in rows})
                ).all()
            }
            return [
                {
                    "course_id": course.id,
                    "course_title": course.title,
                    "course_version": course.version,
                    "document_id": document.id,
                    "document_title": document.title,
                    "chapter_order": document.chapter_order,
                    "source_path": document.source_path,
                    "content_hash": document.content_hash,
                    "source_role": source_roles.get(document.id, ""),
                }
                for course, document in rows
            ]
        finally:
            session.close()
    except Exception:
        return []
