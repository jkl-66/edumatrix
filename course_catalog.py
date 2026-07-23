from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any

from app.database import (
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
    DBCourseDocument,
    DBKnowledgePoint,
    DBSourceDocument,
    DBSourceRef,
)
from document_parser import chunk_document, parse_uploaded_file
from rag_engine import hybrid_rag


ROOT = Path(__file__).resolve().parent
M0_DIR = ROOT / "outputs" / "M0_阶段0基线与架构契约"
MANIFEST_PATH = M0_DIR / "datasets" / "course_manifest.json"
KNOWLEDGE_POINTS_PATH = M0_DIR / "datasets" / "core_knowledge_points.json"
PARSER_VERSION = "edumatrix-parser-v1"

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


def _extract_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip() or fallback
    return fallback


def load_m0_course_bundle(manifest_path: Path = MANIFEST_PATH) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    course_id = str(manifest["course_id"])
    documents = []

    for chapter_order, item in enumerate(manifest["files"]):
        relative_path = str(item["path"])
        path = M0_DIR / relative_path
        raw = path.read_bytes()
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


def upsert_course_bundle(session, bundle: dict[str, Any]) -> dict[str, int]:
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
            if key != "chunks":
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


def _sync_canonical_course_objects(session, bundle: dict[str, Any]) -> dict[str, int]:
    """Idempotently project the M0 compatibility tables into M1 objects."""
    course = bundle["course"]
    gold = json.loads(KNOWLEDGE_POINTS_PATH.read_text(encoding="utf-8"))
    points_by_code: dict[str, DBKnowledgePoint] = {}
    for item in gold["points"]:
        point = (
            session.query(DBKnowledgePoint)
            .filter(
                DBKnowledgePoint.domain_pack == gold["domain_id"],
                DBKnowledgePoint.code == item["id"],
                DBKnowledgePoint.version == gold["gold_version"],
            )
            .first()
        )
        if point is None:
            point = DBKnowledgePoint(
                domain_pack=gold["domain_id"],
                code=item["id"],
                version=gold["gold_version"],
            )
            session.add(point)
        point.title = item["title"]
        point.level = item["level"]
        point.prerequisites = item.get("prerequisites", [])
        point.status = "active"
        session.flush()
        points_by_code[item["id"]] = point

    source_count = chapter_count = ref_count = relation_count = 0
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
                course_id=course["id"], legacy_document_id=item["id"]
            )
            session.add(source)
            source_count += 1
        source.title = item["title"]
        source.filename = item["filename"]
        source.file_format = item["file_type"]
        source.content_hash = item["content_hash"]
        source.file_size = item["file_size"]
        source.source_path = item["source_path"]
        source.source_url = course["content_origin"]
        source.license_text = item["license_text"]
        source.parser_version = PARSER_VERSION
        source.processing_status = "ready"
        session.flush()

        stable_key = f"document:{item['id']}"
        chapter = (
            session.query(DBChapter)
            .filter(DBChapter.course_id == course["id"], DBChapter.stable_key == stable_key)
            .first()
        )
        if chapter is None:
            chapter = DBChapter(
                course_id=course["id"],
                source_document_id=source.id,
                stable_key=stable_key,
            )
            session.add(chapter)
            chapter_count += 1
        chapter.source_document_id = source.id
        chapter.title = item["title"]
        chapter.position = item["chapter_order"]
        chapter.heading_level = 1
        chapter.char_start = 0
        chapter.char_end = len(item["content"])
        session.flush()

        source_ref = (
            session.query(DBSourceRef)
            .filter(
                DBSourceRef.source_document_id == source.id,
                DBSourceRef.chapter_id == chapter.id,
                DBSourceRef.parser_version == PARSER_VERSION,
            )
            .first()
        )
        if source_ref is None:
            source_ref = DBSourceRef(
                source_document_id=source.id,
                chapter_id=chapter.id,
                parser_version=PARSER_VERSION,
            )
            session.add(source_ref)
            ref_count += 1
        source_ref.char_start = 0
        source_ref.char_end = len(item["content"])
        source_ref.content_hash = item["content_hash"]
        source_ref.quote = item["content"][:300]

        active_point_ids = set()
        for code in CHAPTER_KP_CODES.get(item["chapter_order"], ()):
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

    return {
        "source_documents": source_count,
        "chapters": chapter_count,
        "source_refs": ref_count,
        "chapter_kp_relations": relation_count,
    }


def ingest_course_bundle(bundle: dict[str, Any]) -> int:
    course = bundle["course"]
    total = 0
    for document in bundle["documents"]:
        source = f"{course['id']}/{document['filename']}"
        hybrid_rag.remove_course_documents(source, course["id"])
        hybrid_rag.ingest_course_documents(
            document["chunks"],
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
                }
                for course, document in rows
            ]
        finally:
            session.close()
    except Exception:
        return []
