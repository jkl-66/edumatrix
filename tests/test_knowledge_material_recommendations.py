from __future__ import annotations

import hashlib
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.database import (
    DBChapter,
    DBCourse,
    DBKnowledgeDocument,
    DBSourceDocument,
    DBStudentProfile,
    DBUser,
    SessionLocal,
)
from knowledge_api import _material_recommendations
from tests.api_test_helpers import auth_headers


def _course(course_id: str, *, visibility: str = "public", owner: str | None = None) -> DBCourse:
    return DBCourse(
        id=course_id,
        version="1",
        title=course_id,
        subject="机器学习",
        description="课程资料",
        domain_pack="ai",
        language="zh-CN",
        content_origin="test",
        visibility=visibility,
        status="published",
        owner_public_id=owner,
        manifest_version="test-v1",
        manifest_data={},
    )


def _doc(doc_id: str, owner: str, *, filename: str, content: str, chunks: int) -> DBKnowledgeDocument:
    return DBKnowledgeDocument(
        id=doc_id,
        student_id=owner,
        filename=filename,
        file_type=filename.rsplit(".", 1)[-1],
        file_size=len(content.encode("utf-8")),
        title=filename.rsplit(".", 1)[0],
        content=content,
        tags=["机器学习"],
        chunk_count=chunks,
    )


def _source(source_id: str, course_id: str, doc: DBKnowledgeDocument, status: str = "ready") -> DBSourceDocument:
    digest = hashlib.sha256((doc.content or "").encode("utf-8")).hexdigest()
    return DBSourceDocument(
        id=source_id,
        course_id=course_id,
        legacy_document_id=doc.id,
        title=doc.title,
        filename=doc.filename,
        file_format=doc.file_type,
        content_hash=digest,
        source_sha256=digest,
        processed_sha256=digest,
        file_size=doc.file_size,
        uploader_public_id=None,
        processing_status=status,
    )


def test_material_recommendations_keep_quality_owner_scope_and_shelf_boundary() -> None:
    owner = "material-recommendation-owner"
    actor = SimpleNamespace(username=owner, public_id="actor-material-recommendation")
    content = "机器学习 教材：监督学习、损失函数、梯度下降与模型评估。\n" * 380
    with SessionLocal() as session:
        session.add_all([DBStudentProfile(student_id=owner), DBStudentProfile(student_id="public")])
        shelf_course = _course("material-shelf-course")
        private_course = _course("material-private-course", visibility="private", owner=None)
        session.add_all([shelf_course, private_course])

        textbook = _doc(owner + "-textbook", owner, filename="[下载] Python机器学习.pdf", content=content, chunks=30)
        duplicate = _doc(owner + "-duplicate", owner, filename="duplicate.pdf", content=content, chunks=8)
        web = _doc(owner + "-web", owner, filename="[网页] 机器学习摘录.txt", content=content, chunks=30)
        shelf_doc = _doc(owner + "-shelf", owner, filename="already-in-shelf.pdf", content=content + "shelf", chunks=30)
        private_doc = _doc(owner + "-private", "public", filename="private-source.pdf", content=content + "private", chunks=30)
        failed_doc = _doc(owner + "-failed", owner, filename="failed.pdf", content=content + "failed", chunks=30)
        session.add_all([textbook, duplicate, web, shelf_doc, private_doc, failed_doc])
        session.flush()
        session.add_all([
            _source("material-shelf-source", shelf_course.id, shelf_doc),
            _source("material-private-source", private_course.id, private_doc),
            _source("material-failed-source", "material-private-course", failed_doc, status="failed"),
        ])
        session.flush()

        rows = _material_recommendations(
            session,
            current_user=actor,
            shelf_course_ids={shelf_course.id},
            profile_basis={"labels": ["机器学习"]},
        )
        ids = [row["id"] for row in rows]
        assert textbook.id in ids
        assert duplicate.id not in ids
        assert web.id not in ids
        assert shelf_doc.id not in ids
        assert private_doc.id not in ids
        assert failed_doc.id not in ids
        textbook_row = next(row for row in rows if row["id"] == textbook.id)
        assert textbook_row["open_mode"] == "preview"
        assert textbook_row["traceability"] == "legacy_document"
        assert textbook_row["requires_review"] is True
        assert textbook_row["matched_profile_labels"] == ["机器学习"]
        assert textbook_row["owner_id"] == owner
        assert all(row["owner_scope"] in {"personal", "public"} for row in rows)
        session.rollback()


def test_material_recommendations_can_expose_ready_canonical_reader_link() -> None:
    owner = "material-recommendation-canonical-owner"
    actor = SimpleNamespace(username=owner, public_id="actor-material-canonical")
    content = "深度学习课程资料：神经网络、反向传播、注意力机制和 Transformer。\n" * 250
    with SessionLocal() as session:
        session.add(DBStudentProfile(student_id=owner))
        session.add(DBUser(
            public_id=actor.public_id,
            username=owner,
            hashed_password="test-only",
            role="student",
        ))
        session.flush()
        course = _course("material-canonical-course", owner=actor.public_id)
        doc = _doc(owner + "-canonical", owner, filename="深度学习课程讲义.docx", content=content, chunks=24)
        session.add_all([course, doc])
        session.flush()
        source = _source("material-canonical-source", course.id, doc)
        session.add(source)
        session.flush()
        chapter = DBChapter(
            id="material-canonical-chapter",
            course_id=course.id,
            source_document_id=source.id,
            stable_key="material-canonical",
            title="Transformer",
            position=1,
            heading_level=1,
            char_start=0,
            char_end=len(content),
        )
        session.add(chapter)
        session.flush()

        rows = _material_recommendations(
            session,
            current_user=actor,
            shelf_course_ids=set(),
            profile_basis={"labels": []},
        )
        row = next(item for item in rows if item["id"] == doc.id)
        assert row["open_mode"] == "reader"
        assert row["source_document_id"] == source.id
        assert row["chapter_id"] == chapter.id
        assert row["source_processing_status"] == "ready"
        assert row["owner_id"] == owner
        session.rollback()


def test_course_shelf_payload_always_exposes_backward_compatible_material_array() -> None:
    with TestClient(app) as client:
        headers = auth_headers(client, "material-recommendation-endpoint-owner")
        response = client.get("/api/knowledge/courses", headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert isinstance(payload.get("material_recommendations"), list)
        assert payload["schema_version"] == "edumatrix.knowledge-course-shelf.v1"
