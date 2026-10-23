from __future__ import annotations

from types import SimpleNamespace

from app.chat_api import _chat_course_catalog
from app.competition_journey import _course as journey_course
from app.database import (
    Base,
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
    DBCourseDocument,
    DBKnowledgePoint,
    DBSourceDocument,
)
from app.diagnostic_generation import diagnostic_course_catalog
from app.m5_api import _planning_targets
from app.m5_learning import M5LearningError, resolve_learning_context
from app.schemas import ContextRef
from course_catalog import course_is_selectable
from knowledge_api import _course_catalog_payload
from knowledge_api import _profile_conditioned_discovery_context
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def _course(course_id: str, *, status: str = "published") -> DBCourse:
    return DBCourse(
        id=course_id,
        version="1",
        title=f"课程 {course_id}",
        subject="人工智能",
        description="测试课程",
        visibility="public",
        status=status,
        manifest_version="test-v1",
        manifest_data={},
    )


def _ready_material(session, course: DBCourse) -> None:
    content = f"{course.title} 的课程正文，包含可学习的知识点。"
    document = DBCourseDocument(
        id=f"{course.id}-document",
        course_id=course.id,
        chapter_order=0,
        filename="chapter.md",
        file_type="md",
        title="第一章",
        content=content,
        chunk_count=1,
        content_hash="content-hash",
        status="published",
    )
    source = DBSourceDocument(
        id=f"{course.id}-source",
        course_id=course.id,
        legacy_document_id=document.id,
        title=document.title,
        filename=document.filename,
        file_format="md",
        content_hash=document.content_hash,
        source_sha256="source-hash",
        processed_sha256="processed-hash",
        processing_status="ready",
    )
    session.add_all([document, source])


def test_every_active_catalog_uses_the_same_selectable_course_set():
    engine, session = _db()
    try:
        user = SimpleNamespace(public_id="user-1", username="student-1", role="student")
        usable = _course("usable")
        empty = _course("empty")
        withdrawn = _course("withdrawn", status="withdrawn")
        session.add_all([usable, empty, withdrawn])
        _ready_material(session, usable)
        session.flush()
        chapter = DBChapter(
            id="usable-chapter", course_id=usable.id, source_document_id="usable-source",
            stable_key="usable-chapter", title="第一章", position=0, char_start=0, char_end=20,
        )
        point = DBKnowledgePoint(id="usable-point", domain_pack="test", code="KP-1", version="1", title="课程知识点", level="core", prerequisites=[])
        session.add_all([chapter, point])
        session.flush()
        session.add(DBChapterKnowledgePoint(chapter_id=chapter.id, knowledge_point_id=point.id, relation_type="teaches"))
        session.commit()

        expected = {usable.id}
        assert {row.id for row in session.query(DBCourse).all() if course_is_selectable(session, row)} == expected
        assert {row["id"] for row in diagnostic_course_catalog(session, user=user)["courses"]} == expected
        assert {row["id"] for row in _chat_course_catalog(session, user)} == expected
        assert {row["id"] for row in _planning_targets(session, user)["courses"]} == expected
        shelf = _course_catalog_payload(session, user)
        assert {row["id"] for row in shelf["shelf"] + shelf["recommendations"]} == expected
        assert "empty" not in str(shelf)
        assert "withdrawn" not in str(shelf)
    finally:
        session.close()
        engine.dispose()


def test_context_and_journey_reject_empty_or_withdrawn_courses_without_mapping():
    engine, session = _db()
    try:
        user = SimpleNamespace(public_id="user-2", username="student-2", role="student")
        empty = _course("empty")
        withdrawn = _course("withdrawn", status="withdrawn")
        session.add_all([empty, withdrawn])
        session.commit()

        assert course_is_selectable(session, empty) is False
        assert course_is_selectable(session, withdrawn) is False
        for course_id in (empty.id, withdrawn.id):
            try:
                resolve_learning_context(
                    session,
                    user=user,
                    context=ContextRef(user_id=user.public_id, course_id=course_id),
                )
            except M5LearningError as exc:
                assert exc.code == "course_unavailable"
            else:
                raise AssertionError("unavailable course entered learning context")
            try:
                journey_course(session, course_id)
            except Exception as exc:
                assert getattr(exc, "code", "") == "journey_course_unavailable"
            else:
                raise AssertionError("unavailable course entered journey")
    finally:
        session.close()
        engine.dispose()


def test_usable_course_remains_selectable_after_catalog_projection():
    engine, session = _db()
    try:
        usable = _course("usable")
        session.add(usable)
        _ready_material(session, usable)
        session.commit()
        assert course_is_selectable(session, usable)
        payload = _course_catalog_payload(
            session,
            SimpleNamespace(public_id="user-3", username="student-3", role="student"),
        )
        assert any(item["id"] == usable.id for item in payload["shelf"])
        assert payload["shelf"][0]["document_count"] == 1
    finally:
        session.close()
        engine.dispose()


def test_discovery_context_rejects_withdrawn_or_empty_course_ids():
    engine, session = _db()
    try:
        user = SimpleNamespace(public_id="user-discovery", username="student-discovery", role="student")
        empty = _course("empty-discovery")
        withdrawn = _course("withdrawn-discovery", status="withdrawn")
        session.add_all([empty, withdrawn])
        session.commit()
        for course_id in (empty.id, withdrawn.id):
            try:
                _profile_conditioned_discovery_context(session, user, course_id=course_id)
            except HTTPException as exc:
                assert exc.status_code == 409
            else:
                raise AssertionError("unavailable course entered discovery context")
    finally:
        session.close()
        engine.dispose()
