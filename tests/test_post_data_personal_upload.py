from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

import knowledge_api
from app.database import (
    DBChapter,
    DBCourse,
    DBKnowledgeDocument,
    DBLearningEvent,
    DBLearningPath,
    DBProfileSnapshot,
    DBReviewPlan,
    DBSourceDocument,
    DBSourceRef,
    DBUser,
    SessionLocal,
)
from app.main import app
from tests.api_test_helpers import auth_headers


ROOT = Path(__file__).resolve().parents[1]
COURSE_FILES = {
    "pdf": ROOT / "data/curated/embedded_machine_learning_engineering_v2/materials/嵌入式机器学习与边缘智能工程手册.pdf",
    "docx": ROOT / "data/curated/embedded_machine_learning_engineering_v2/materials/module-07/7.1.5.digging-deeper-into-object-detection.2.docx",
    "pptx": ROOT / "data/curated/embedded_machine_learning_engineering_v2/materials/module-02/2.2.1.introduction-to-neural-networks.1.pptx",
    "mp4": ROOT / "data/curated/embedded_machine_learning_engineering_v2/media/课程导览_嵌入式机器学习工程实践.mp4",
}
RETRY_DOCX = ROOT / "data/curated/embedded_machine_learning_engineering_v2/materials/module-05/5.1.1.introduction-to-anomaly-detection.3.docx"
BATCH_DOCX = ROOT / "data/curated/embedded_machine_learning_engineering_v2/materials/module-08/8.1.5.keyword-spotting-application-architecture.3.docx"
MIME_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "mp4": "video/mp4",
}


def _protected_learning_state(username: str) -> dict[str, object]:
    with SessionLocal() as session:
        owner = session.query(DBUser).filter_by(username=username).one()
        return {
            "learning_events": session.query(DBLearningEvent).filter_by(
                owner_public_id=owner.public_id
            ).count(),
            "profile_snapshots": session.query(DBProfileSnapshot).filter_by(
                owner_public_id=owner.public_id
            ).count(),
            "paths": [
                (row.id, row.status, row.lock_version)
                for row in session.query(DBLearningPath)
                .filter_by(owner_public_id=owner.public_id)
                .order_by(DBLearningPath.id)
                .all()
            ],
            "reviews": [
                (row.id, row.review_count, row.mastery, row.next_review_at)
                for row in session.query(DBReviewPlan)
                .filter_by(student_id=username)
                .order_by(DBReviewPlan.id)
                .all()
            ],
        }


def _canonical_counts(course_id: str) -> tuple[int, int, int, int]:
    with SessionLocal() as session:
        source_ids = [
            row.id for row in session.query(DBSourceDocument).filter_by(course_id=course_id).all()
        ]
        return (
            len(source_ids),
            session.query(DBChapter).filter_by(course_id=course_id).count(),
            session.query(DBSourceRef)
            .filter(DBSourceRef.source_document_id.in_(source_ids))
            .count()
            if source_ids
            else 0,
            session.query(DBKnowledgeDocument)
            .filter(DBKnowledgeDocument.id.in_([
                row.legacy_document_id
                for row in session.query(DBSourceDocument).filter_by(course_id=course_id).all()
                if row.legacy_document_id
            ]))
            .count(),
        )


def test_personal_course_real_multiformat_upload_and_failure_recovery(monkeypatch, tmp_path) -> None:
    username = "post_data_personal_upload_owner"
    monkeypatch.setattr(knowledge_api, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(knowledge_api, "build_graph_after_upload", lambda *args, **kwargs: None)
    monkeypatch.setattr(knowledge_api, "parse_pdf_visually", lambda *args, **kwargs: [])
    monkeypatch.setattr(knowledge_api.hybrid_rag, "ingest_user_documents", lambda *args, **kwargs: None)

    async def no_guide(**_kwargs):
        return None

    monkeypatch.setattr(knowledge_api, "_generate_doc_guide_for_document", no_guide)

    with TestClient(app) as client:
        headers = auth_headers(client, username)
        outsider_headers = auth_headers(client, "post_data_personal_upload_outsider")
        protected_before = _protected_learning_state(username)

        created = client.post(
            "/api/knowledge/courses",
            headers=headers,
            json={
                "title": "边缘智能现场调试个人课程",
                "subject": "嵌入式机器学习",
                "description": "验证学生自建课程和真实多格式资料上传闭环",
            },
        )
        assert created.status_code == 201, created.text
        course_id = created.json()["course"]["id"]
        assert created.json()["created"] is True
        assert created.json()["course"]["document_count"] == 0
        empty_shelf = client.get("/api/knowledge/courses", headers=headers)
        assert empty_shelf.status_code == 200, empty_shelf.text
        empty_course = next(item for item in empty_shelf.json()["shelf"] if item["id"] == course_id)
        assert empty_course["requires_upload"] is True
        assert empty_course["can_manage"] is True
        empty_outline = client.get(f"/api/v1/courses/{course_id}/outline", headers=headers)
        assert empty_outline.status_code == 200, empty_outline.text
        assert empty_outline.json() == []

        uploaded: dict[str, dict[str, object]] = {}
        for file_type, path in COURSE_FILES.items():
            raw = path.read_bytes()
            response = client.post(
                f"/api/knowledge/upload?student_id={username}&course_id={course_id}",
                headers=headers,
                files={"file": (path.name, raw, MIME_TYPES[file_type])},
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["duplicate"] is False
            assert payload["file_type"] == file_type
            assert payload["course_id"] == course_id
            assert payload["source_processing_status"] == "ready"
            assert payload["source_sha256"] == hashlib.sha256(raw).hexdigest()
            assert payload["source_ref_count"] >= 1
            uploaded[file_type] = payload

            source = client.get(
                f"/api/knowledge/sources/{payload['source_document_id']}", headers=headers
            )
            assert source.status_code == 200, source.text
            assert source.json()["course_id"] == course_id
            assert source.json()["content"]
            reader = client.get(
                f"/api/v1/document-reader/documents/{payload['source_document_id']}",
                headers=headers,
            )
            assert reader.status_code == 200, reader.text
            assert reader.json()["course"]["id"] == course_id

        with SessionLocal() as session:
            course = session.get(DBCourse, course_id)
            assert course is not None
            assert course.owner_public_id == session.query(DBUser).filter_by(username=username).one().public_id
            assert {
                row.file_format
                for row in session.query(DBSourceDocument).filter_by(course_id=course_id).all()
            } == {"pdf", "docx", "pptx", "mp4"}
            assert all(
                row.processing_status == "ready"
                for row in session.query(DBSourceDocument).filter_by(course_id=course_id).all()
            )

        shelf = client.get("/api/knowledge/courses", headers=headers)
        assert shelf.status_code == 200, shelf.text
        personal = next(item for item in shelf.json()["shelf"] if item["id"] == course_id)
        assert personal["document_count"] == 4
        assert personal["source_count"] == 4
        assert personal["ready_source_count"] == 4
        assert personal["index_status"] == "ready"
        assert client.post(
            f"/api/knowledge/upload?student_id=post_data_personal_upload_outsider&course_id={course_id}",
            headers=outsider_headers,
            files={"file": (COURSE_FILES["docx"].name, COURSE_FILES["docx"].read_bytes(), MIME_TYPES["docx"])},
        ).status_code == 403

        counts_before_duplicate = _canonical_counts(course_id)
        duplicate = client.post(
            f"/api/knowledge/upload?student_id={username}&course_id={course_id}",
            headers=headers,
            files={"file": (COURSE_FILES["docx"].name, COURSE_FILES["docx"].read_bytes(), MIME_TYPES["docx"])},
        )
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()["duplicate"] is True
        assert duplicate.json()["id"] == uploaded["docx"]["id"]
        assert _canonical_counts(course_id) == counts_before_duplicate

        unsupported = client.post(
            f"/api/knowledge/upload?student_id={username}&course_id={course_id}",
            headers=headers,
            files={"file": ("unsupported.exe", b"not-supported", "application/octet-stream")},
        )
        assert unsupported.status_code == 400
        assert "不支持的文件类型" in unsupported.json()["detail"]

        batch_raw = BATCH_DOCX.read_bytes()
        batch = client.post(
            f"/api/knowledge/upload-batch?student_id={username}&course_id={course_id}",
            headers=headers,
            files=[
                ("files", (BATCH_DOCX.name, batch_raw, MIME_TYPES["docx"])),
                ("files", ("broken.pdf", b"broken-pdf", "application/pdf")),
            ],
        )
        assert batch.status_code == 200, batch.text
        batch_payload = batch.json()
        assert (batch_payload["total"], batch_payload["succeeded"], batch_payload["failed"]) == (2, 1, 1)
        assert [item["status"] for item in batch_payload["results"]] == ["ready", "failed"]
        assert batch_payload["results"][0]["document"]["source_processing_status"] == "ready"
        assert batch_payload["results"][1]["error"]["code"] in {
            "document_limit_rejected",
            "pdf_parse_failed",
        }
        with SessionLocal() as session:
            assert session.query(DBSourceDocument).filter_by(
                course_id=course_id,
                source_sha256=hashlib.sha256(batch_raw).hexdigest(),
                processing_status="ready",
            ).count() == 1
            assert session.query(DBSourceDocument).filter_by(
                course_id=course_id, filename="broken.pdf"
            ).count() == 0

        failed_retry = client.post(
            f"/api/knowledge/upload?student_id={username}&course_id={course_id}",
            headers=headers,
            files={"file": ("retry.docx", b"broken-docx", MIME_TYPES["docx"])},
        )
        assert failed_retry.status_code == 422
        retry_raw = RETRY_DOCX.read_bytes()
        repaired_retry = client.post(
            f"/api/knowledge/upload?student_id={username}&course_id={course_id}",
            headers=headers,
            files={"file": ("retry.docx", retry_raw, MIME_TYPES["docx"])},
        )
        assert repaired_retry.status_code == 200, repaired_retry.text
        assert repaired_retry.json()["duplicate"] is False
        assert repaired_retry.json()["source_processing_status"] == "ready"
        assert repaired_retry.json()["source_sha256"] == hashlib.sha256(retry_raw).hexdigest()

        final_shelf = client.get("/api/knowledge/courses", headers=headers).json()
        final_personal = next(item for item in final_shelf["shelf"] if item["id"] == course_id)
        assert final_personal["document_count"] == 6
        assert final_personal["source_count"] == 6
        assert final_personal["ready_source_count"] == 6
        assert _protected_learning_state(username) == protected_before
        assert not list((tmp_path / "uploads").rglob("*.tmp"))
