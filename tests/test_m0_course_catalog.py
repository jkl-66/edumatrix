from __future__ import annotations

from fastapi.testclient import TestClient

from app.database import (
    DBCourse,
    DBCourseDocument,
    DBKnowledgeDocument,
    DBStudentProfile,
    SessionLocal,
    init_db,
)
from app.main import app
from course_catalog import (
    ingest_course_bundle,
    load_m0_course_bundle,
    published_course_provenance,
    upsert_course_bundle,
)
from learning_strategy import build_resource_aware_dag, invalidate_graph_cache
from rag_engine import hybrid_rag
from tests.api_test_helpers import auth_headers


COURSE_ID = "course-rag-engineering-m0"


def test_m0_course_bundle_matches_manifest_and_has_nine_ordered_documents():
    bundle = load_m0_course_bundle()

    assert bundle["course"]["id"] == COURSE_ID
    assert bundle["course"]["status"] == "published"
    assert bundle["course"]["visibility"] == "public"
    assert len(bundle["documents"]) == 9
    assert [item["chapter_order"] for item in bundle["documents"]] == list(range(9))
    assert len({item["id"] for item in bundle["documents"]}) == 9
    assert all(item["content_hash"] and item["chunks"] for item in bundle["documents"])


def test_m0_course_database_seed_is_idempotent():
    init_db()
    bundle = load_m0_course_bundle()
    session = SessionLocal()
    try:
        upsert_course_bundle(session, bundle)
        second = upsert_course_bundle(session, bundle)

        assert session.query(DBCourse).filter(DBCourse.id == COURSE_ID).count() == 1
        assert (
            session.query(DBCourseDocument)
            .filter(DBCourseDocument.course_id == COURSE_ID)
            .count()
            == 9
        )
        assert second == {"inserted": 0, "updated": 9, "removed": 0}
    finally:
        session.close()


def test_published_course_is_visible_to_new_student_and_read_only():
    with TestClient(app) as client:
        headers = auth_headers(client, "m0_course_reader")
        response = client.get(
            "/api/knowledge/list?student_id=m0_course_reader",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        course_documents = [
            item
            for item in response.json()
            if item.get("course_id") == COURSE_ID
        ]
        assert len(course_documents) == 9
        assert [item["chapter_order"] for item in course_documents] == list(range(9))
        assert all(item["scope"] == "course" for item in course_documents)
        assert all(item["deletable"] is False for item in course_documents)

        first = course_documents[0]
        detail = client.get(
            f"/api/knowledge/{first['id']}?student_id=m0_course_reader",
            headers=headers,
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["course_title"] == "RAG 应用开发与幻觉评测实训课"
        assert detail.json()["content_hash"] == first["content_hash"]

        denied = client.delete(
            f"/api/knowledge/{first['id']}?student_id=m0_course_reader",
            headers=headers,
        )
        assert denied.status_code == 403
        assert "只读" in denied.json()["detail"]


def test_course_rag_evidence_is_public_without_exposing_private_evidence():
    bundle = load_m0_course_bundle()
    ingest_course_bundle(bundle)

    all_items = list(hybrid_rag.user_index._items.values())
    visible = hybrid_rag._visible_user_evidence(all_items, "unrelated-student")
    course_items = [
        item
        for item in visible
        if item.metadata.get("course_id") == COURSE_ID
    ]

    assert course_items
    assert all(item.metadata.get("visibility") == "public" for item in course_items)
    assert not [
        item
        for item in visible
        if item.metadata.get("visibility") == "private"
        and item.metadata.get("owner_id") != "unrelated-student"
    ]


def test_frozen_course_question_returns_locatable_course_evidence():
    bundle = load_m0_course_bundle()
    ingest_course_bundle(bundle)

    result = hybrid_rag.retrieve(
        "查询必须同时约束用户、组织、课程和版本范围",
        top_k=5,
        disable_external=True,
    )

    assert result.evidence
    course_hits = [
        item
        for item in result.evidence
        if item.metadata.get("course_id") == COURSE_ID
    ]
    assert course_hits
    assert any(
        item.metadata.get("source_path", "").endswith("03_分块元数据与索引.md")
        and "课程和版本范围" in item.content
        for item in course_hits
    )


def test_learning_path_graph_metadata_preserves_course_and_document_identity():
    init_db()
    bundle = load_m0_course_bundle()
    session = SessionLocal()
    try:
        upsert_course_bundle(session, bundle)
    finally:
        session.close()

    provenance = published_course_provenance()
    _dag, metadata = build_resource_aware_dag(
        {"RAG工程": []}, resource_index={}, include_rag=False
    )

    assert len(provenance) == 9
    assert metadata["course_ids"] == [COURSE_ID]
    assert metadata["course_document_count"] == 9
    assert {item["course_id"] for item in metadata["course_sources"]} == {COURSE_ID}
    assert len({item["document_id"] for item in metadata["course_sources"]}) == 9
    assert all(item["source_path"] for item in metadata["course_sources"])


def test_learning_path_api_exposes_the_same_course_and_document_ids():
    invalidate_graph_cache()
    with TestClient(app) as client:
        headers = auth_headers(client, "m0_course_path_reader")
        response = client.get(
            "/api/profile/m0_course_path_reader/learning-path",
            headers=headers,
        )

    assert response.status_code == 200, response.text
    graph_fusion = response.json()["adaptive_route"]["graph_fusion"]
    assert graph_fusion["course_ids"] == [COURSE_ID]
    assert graph_fusion["course_document_count"] == 9
    assert len(graph_fusion["course_sources"]) == 9
    assert len({item["document_id"] for item in graph_fusion["course_sources"]}) == 9


def test_course_upsert_does_not_touch_legacy_knowledge_documents():
    init_db()
    session = SessionLocal()
    profile_id = "m0_legacy_boundary_owner"
    document_id = "m0_legacy_boundary_document"
    try:
        session.add(DBStudentProfile(student_id=profile_id))
        session.flush()
        session.add(
            DBKnowledgeDocument(
                id=document_id,
                student_id=profile_id,
                filename="legacy.md",
                file_type="md",
                file_size=12,
                title="Legacy material",
                content="legacy material must remain recoverable",
                tags=["legacy"],
                chunk_count=1,
            )
        )
        session.commit()
        before = session.query(DBKnowledgeDocument).count()
        upsert_course_bundle(session, load_m0_course_bundle())
        after = session.query(DBKnowledgeDocument).count()

        assert after == before
        assert session.get(DBKnowledgeDocument, document_id) is not None
    finally:
        legacy = session.get(DBKnowledgeDocument, document_id)
        if legacy is not None:
            session.delete(legacy)
        profile = session.get(DBStudentProfile, profile_id)
        if profile is not None:
            session.delete(profile)
        session.commit()
        session.close()
