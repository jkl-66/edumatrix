from __future__ import annotations

from app.database import (
    DBChapter,
    DBChapterKnowledgePoint,
    DBKnowledgePoint,
    DBSourceDocument,
    DBSourceRef,
    SessionLocal,
)
from course_catalog import (
    CHAPTER_KP_CODES,
    PARSER_VERSION,
    load_m0_course_bundle,
    upsert_course_bundle,
)
from fastapi.testclient import TestClient
from app.main import app
from tests.api_test_helpers import auth_headers


COURSE_ID = "course-rag-engineering-m0"


def test_course_bundle_projects_to_canonical_sources_idempotently():
    bundle = load_m0_course_bundle()
    with SessionLocal() as session:
        upsert_course_bundle(session, bundle)
        first_ids = {row.id for row in session.query(DBSourceDocument).filter_by(course_id=COURSE_ID)}
        upsert_course_bundle(session, bundle)
        second_ids = {row.id for row in session.query(DBSourceDocument).filter_by(course_id=COURSE_ID)}

        assert first_ids == second_ids
        assert len(second_ids) == 9
        assert session.query(DBChapter).filter_by(course_id=COURSE_ID).count() == 9
        assert session.query(DBSourceRef).count() >= 9


def test_frozen_knowledge_points_have_stable_business_codes_and_opaque_ids():
    with SessionLocal() as session:
        points = (
            session.query(DBKnowledgePoint)
            .filter_by(domain_pack="domain-rag-0.1", version="kp-rag-0.1")
            .all()
        )
        assert len(points) == 32
        assert {point.code for point in points} == {f"KP-{index:02d}" for index in range(1, 33)}
        assert all(point.id.startswith("kp-") and point.id != point.code for point in points)


def test_chapters_and_knowledge_points_are_many_to_many():
    with SessionLocal() as session:
        expected_relations = sum(len(codes) for codes in CHAPTER_KP_CODES.values())
        chapters = session.query(DBChapter).filter_by(course_id=COURSE_ID).all()
        chapter_ids = {chapter.id for chapter in chapters}
        relations = (
            session.query(DBChapterKnowledgePoint)
            .filter(DBChapterKnowledgePoint.chapter_id.in_(chapter_ids))
            .all()
        )
        assert len(relations) == expected_relations
        kp_28 = session.query(DBKnowledgePoint).filter_by(code="KP-28").one()
        assert sum(item.knowledge_point_id == kp_28.id for item in relations) == 2


def test_source_ref_preserves_parser_and_precise_text_locator():
    with SessionLocal() as session:
        chapter = (
            session.query(DBChapter)
            .filter_by(course_id=COURSE_ID)
            .order_by(DBChapter.position)
            .first()
        )
        source_ref = session.query(DBSourceRef).filter_by(chapter_id=chapter.id).one()
        assert source_ref.parser_version == PARSER_VERSION
        assert source_ref.char_start == 0
        assert source_ref.char_end == chapter.char_end
        assert len(source_ref.content_hash) == 64
        assert source_ref.quote.strip()


def test_canonical_course_outline_and_source_ref_are_authorized_read_apis():
    with TestClient(app) as client:
        headers = auth_headers(client, "m1-course-api-reader")
        course = client.get(f"/api/v1/courses/{COURSE_ID}", headers=headers)
        assert course.status_code == 200
        assert course.json()["subject"] == "人工智能 / RAG 工程"

        outline = client.get(f"/api/v1/courses/{COURSE_ID}/outline", headers=headers)
        assert outline.status_code == 200
        assert len(outline.json()) == 9
        assert outline.json()[0]["knowledge_points"]

        source_ref_id = outline.json()[0]["source_ref_id"]
        source_ref = client.get(f"/api/v1/source-refs/{source_ref_id}", headers=headers)
        assert source_ref.status_code == 200
        assert source_ref.json()["course_id"] == COURSE_ID
        assert len(source_ref.json()["content_hash"]) == 64

        assert client.get(f"/api/v1/courses/{COURSE_ID}").status_code == 401
