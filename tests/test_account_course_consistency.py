from __future__ import annotations

import hashlib
from types import SimpleNamespace

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import (
    Base,
    DBChapter,
    DBCourse,
    DBCourseDocument,
    DBCourseMembership,
    DBKnowledgeDocument,
    DBSourceDocument,
    DBSourceRef,
    DBStudentProfile,
    DBUser,
)
from app.legacy_migration_governance import KnowledgeSourceNoteCanonicalReader
from app.legacy_repositories import LegacyReadRepository
from course_catalog import MASTER_COURSE_ID
from knowledge_api import _course_catalog_payload


DEFAULT_COURSE_ID = "course-machine-learning-foundations-v1"


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def _public_course(course_id: str, title: str) -> DBCourse:
    return DBCourse(
        id=course_id,
        version="1",
        title=title,
        subject="人工智能",
        description="公开课程",
        visibility="public",
        status="published",
        manifest_version="test-v1",
        manifest_data={},
    )


def _course_document(course: DBCourse, index: int) -> DBCourseDocument:
    content = f"{course.title} 第 {index} 章：公开课程正文。"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return DBCourseDocument(
        id=f"{course.id}-doc-{index}",
        course_id=course.id,
        chapter_order=index,
        filename=f"chapter-{index}.md",
        file_type="md",
        title=f"第 {index} 章",
        content=content,
        chunk_count=1,
        content_hash=digest,
        status="published",
    )


def test_lzz_and_demo_student_share_course_and_public_material_projection():
    engine, session = _session()
    try:
        users = [
            DBUser(public_id="usr-lzz", username="lzz", hashed_password="x", role="student", is_active=True),
            DBUser(public_id="usr-demo", username="demo-student", hashed_password="x", role="student", is_active=True),
        ]
        session.add_all(users)
        session.add_all([
            DBStudentProfile(student_id="lzz"),
            DBStudentProfile(student_id="demo-student"),
            DBStudentProfile(student_id="public"),
            DBStudentProfile(student_id="system"),
            _public_course(MASTER_COURSE_ID, "统一主课程"),
            _public_course(DEFAULT_COURSE_ID, "机器学习基础"),
        ])
        session.flush()
        session.add_all([
            DBCourseMembership(course_id=MASTER_COURSE_ID, user_public_id="usr-lzz", role="student", status="active"),
            DBCourseMembership(course_id=MASTER_COURSE_ID, user_public_id="usr-demo", role="student", status="active"),
        ])
        shared_content = "机器学习教材：监督学习、神经网络、模型评估与实践。\n" * 120
        session.add(DBKnowledgeDocument(
            id="public-textbook",
            student_id="public",
            filename="公开教材.md",
            file_type="md",
            title="公开教材",
            content=shared_content,
            chunk_count=30,
            file_size=len(shared_content.encode("utf-8")),
        ))
        session.add(DBKnowledgeDocument(
            id="lzz-private-textbook",
            student_id="lzz",
            filename="lzz私有教材.md",
            file_type="md",
            title="lzz私有教材",
            content=shared_content,
            chunk_count=30,
            file_size=len(shared_content.encode("utf-8")),
        ))
        session.commit()

        lzz = SimpleNamespace(username="lzz", public_id="usr-lzz")
        demo = SimpleNamespace(username="demo-student", public_id="usr-demo")
        lzz_payload = _course_catalog_payload(session, lzz)
        demo_payload = _course_catalog_payload(session, demo)

        assert [item["id"] for item in lzz_payload["shelf"]] == [item["id"] for item in demo_payload["shelf"]]
        assert [item["id"] for item in lzz_payload["recommendations"]] == [item["id"] for item in demo_payload["recommendations"]]
        assert [item["id"] for item in lzz_payload["material_recommendations"]] == [item["id"] for item in demo_payload["material_recommendations"]]
        assert "lzz-private-textbook" not in {item["id"] for item in lzz_payload["material_recommendations"]}
        assert lzz_payload["material_recommendations_scope"] == "shared_public_system"
    finally:
        session.close()
        engine.dispose()


def test_legacy_course_readers_use_the_same_public_boundary_for_lzz_and_demo_student():
    engine, session = _session()
    try:
        master = _public_course(MASTER_COURSE_ID, "统一主课程")
        extra = _public_course("public-course-extra", "公开扩展课程")
        session.add_all([master, extra])
        session.flush()
        for course in (master, extra):
            doc = _course_document(course, 1)
            session.add(doc)
            session.flush()
            source = DBSourceDocument(
                id=f"{course.id}-source",
                course_id=course.id,
                legacy_document_id=doc.id,
                title=doc.title,
                filename=doc.filename,
                file_format="md",
                content_hash=doc.content_hash,
                source_sha256=doc.content_hash,
                processed_sha256=doc.content_hash,
                processing_status="ready",
            )
            session.add(source)
            session.flush()
            chapter = DBChapter(
                id=f"{course.id}-chapter",
                course_id=course.id,
                source_document_id=source.id,
                stable_key=f"{course.id}-chapter",
                title=doc.title,
                position=1,
                char_start=0,
                char_end=len(doc.content),
            )
            session.add(chapter)
            session.flush()
            session.add(DBSourceRef(
                id=f"{course.id}-ref",
                source_document_id=source.id,
                chapter_id=chapter.id,
                parser_version="test-v1",
                char_start=0,
                char_end=len(doc.content),
                content_hash=doc.content_hash,
                quote=doc.content,
            ))
        session.commit()

        legacy = LegacyReadRepository(session)
        canonical = KnowledgeSourceNoteCanonicalReader(session)
        for reader in (legacy, canonical):
            lzz_rows = reader.knowledge_library_rows("lzz")
            demo_rows = reader.knowledge_library_rows("demo-student")
            lzz_courses = [row[1].id for row in lzz_rows[1]]
            demo_courses = [row[1].id for row in demo_rows[1]]
            assert lzz_courses == demo_courses
            assert set(lzz_courses) == {MASTER_COURSE_ID, "public-course-extra"}
    finally:
        session.close()
        engine.dispose()
