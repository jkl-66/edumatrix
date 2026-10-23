from __future__ import annotations

from fastapi.testclient import TestClient

import knowledge_api
from app.database import (
    DBCourse,
    DBLearningEvent,
    DBPathNode,
    DBProfileSnapshot,
    DBSourceDocument,
    DBSourceRef,
    DBUser,
    SessionLocal,
)
from app.main import app
from tests.api_test_helpers import auth_headers


SEARCH_QUERY = "MIT OpenCourseWare"
EXPECTED_SOURCE_HOST = "ocw.mit.edu"


def _protected_counts() -> dict[str, int]:
    with SessionLocal() as session:
        return {
            "events": session.query(DBLearningEvent).count(),
            "snapshots": session.query(DBProfileSnapshot).count(),
            "path_nodes": session.query(DBPathNode).count(),
        }


def test_live_search_download_parse_and_course_import(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(knowledge_api, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(knowledge_api, "build_graph_after_upload", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        knowledge_api.hybrid_rag,
        "ingest_user_documents",
        lambda *args, **kwargs: None,
    )

    async def no_guide(**_kwargs):
        return None

    monkeypatch.setattr(knowledge_api, "_generate_doc_guide_for_document", no_guide)

    username = "post_data_live_network_owner"
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        before = _protected_counts()

        search = client.get(
            "/api/knowledge/discovery/search",
            params={"q": SEARCH_QUERY, "max_results": 10},
            headers=headers,
        )
        assert search.status_code == 200, search.text
        search_payload = search.json()
        selected = next(
            item
            for item in search_payload["items"]
            if item["sourceDomain"] == EXPECTED_SOURCE_HOST
        )
        assert selected["url"].startswith("https://ocw.mit.edu/")
        assert selected["licenseStatus"] == "unknown"
        assert selected["reviewStatus"] == "not_saved"

        course = client.post(
            "/api/knowledge/courses",
            headers=headers,
            json={
                "title": "开放课程资料现场导入验证",
                "subject": "嵌入式机器学习",
                "description": "验证搜索、许可确认、下载、解析和课程归属的真实公网闭环",
            },
        )
        assert course.status_code == 201, course.text
        course_id = course.json()["course"]["id"]

        candidate = client.post(
            "/api/knowledge/discovery/candidates",
            headers=headers,
            json={
                "query": search_payload["query"],
                "title": selected["title"],
                "url": selected["url"],
                "snippet": selected["snippet"],
            },
        )
        assert candidate.status_code == 200, candidate.text
        candidate_id = candidate.json()["candidate"]["id"]

        imported = client.post(
            f"/api/knowledge/discovery/candidates/{candidate_id}/admit",
            headers=headers,
            json={
                "course_id": course_id,
                "author_or_organization": "MIT OpenCourseWare",
                "license_status": "personal_use_allowed",
                "license_text": "Creative Commons BY-NC-SA; source terms remain authoritative",
                "usage_hint": "仅用于本地非商业学习演示，保留原站链接与署名",
                "trust_level": "source_declared",
            },
        )
        assert imported.status_code == 200, imported.text
        payload = imported.json()
        assert payload["candidate"]["reviewStatus"] == "imported"
        assert payload["candidate"]["importResult"]["status"] == "ready"
        assert payload["document"]["course_id"] == course_id
        assert payload["document"]["source_processing_status"] == "ready"
        assert payload["document"]["source_ref_count"] > 0
        assert payload["document"]["file_size"] > 100_000
        assert payload["document"]["content_preview"]

        source_id = payload["document"]["source_document_id"]
        source = client.get(f"/api/knowledge/sources/{source_id}", headers=headers)
        reader = client.get(
            f"/api/v1/document-reader/documents/{source_id}", headers=headers
        )
        assert source.status_code == 200, source.text
        assert source.json()["course_id"] == course_id
        assert "MIT OpenCourseWare" in source.json()["content"]
        assert reader.status_code == 200, reader.text
        assert reader.json()["course"]["id"] == course_id

        with SessionLocal() as session:
            owner = session.query(DBUser).filter_by(username=username).one()
            owned_course = session.get(DBCourse, course_id)
            canonical = session.get(DBSourceDocument, source_id)
            assert owned_course is not None
            assert owned_course.owner_public_id == owner.public_id
            assert canonical is not None
            assert canonical.course_id == course_id
            assert canonical.uploader_public_id == owner.public_id
            assert canonical.processing_status == "ready"
            assert canonical.source_url.startswith("https://ocw.mit.edu/")
            assert session.query(DBSourceRef).filter_by(
                source_document_id=source_id
            ).count() > 0

        assert _protected_counts() == before
        assert not list((tmp_path / "uploads").rglob("*.tmp"))
