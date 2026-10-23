from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_password_hash
from app.database import Base, DBChapter, DBChapterKnowledgePoint, DBCourse, DBCourseMembership, DBKnowledgePoint, DBProfileSnapshot, DBSourceDocument, DBSourceRef, DBStudentProfile, DBUser
from course_catalog import ensure_primary_course_memberships, load_versioned_course_bundle, upsert_course_bundle


MANIFEST = Path("data/curated/ai_deep_learning_agents_v1/course_manifest.json")
MASTER_ID = "course-ai-deep-learning-agents-v1"


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _fk(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def test_master_bundle_projects_canonical_structure_and_lzz_cleanup():
    engine, db = _session()
    try:
        users = [
            DBUser(public_id="usr-lzz", username="lzz", hashed_password=get_password_hash("x"), role="student", is_active=True),
            DBUser(public_id="usr-teacher", username="teacher", hashed_password=get_password_hash("x"), role="teacher", is_active=True),
            DBUser(public_id="usr-visitor", username="visitor", hashed_password=get_password_hash("x"), role="visitor", is_active=True),
        ]
        old = DBCourse(id="legacy-course", version="1", title="旧课程", manifest_version="legacy-v1", status="published")
        placeholder = DBCourse(id=MASTER_ID, version="0", title="待导入", manifest_version="placeholder-v0", status="draft")
        db.add_all(users + [old, placeholder, DBStudentProfile(student_id="lzz", target_course="旧课程")])
        db.flush()
        db.add_all([
            DBCourseMembership(course_id="legacy-course", user_public_id="usr-lzz", role="student", status="active"),
            DBCourseMembership(course_id=MASTER_ID, user_public_id="usr-lzz", role="student", status="removed"),
        ])
        db.commit()

        bundle = load_versioned_course_bundle(MANIFEST)
        result = upsert_course_bundle(
            db,
            bundle,
            approve_version_change=True,
            expected_current_version="placeholder-v0",
            expected_incoming_version=bundle["course"]["version"],
        )
        assert result["inserted"] == len(bundle["documents"])
        assert db.get(DBCourse, MASTER_ID).title == "人工智能与深度学习：从机器学习基础到大模型智能体"
        assert db.query(DBSourceDocument).filter_by(course_id=MASTER_ID).count() == len(bundle["documents"])
        assert db.query(DBChapter).filter_by(course_id=MASTER_ID).count() == len(bundle["documents"])
        assert db.query(DBSourceRef).join(DBSourceDocument, DBSourceRef.source_document_id == DBSourceDocument.id).filter(DBSourceDocument.course_id == MASTER_ID).count() == len(bundle["documents"])
        assert db.query(DBKnowledgePoint).filter_by(domain_pack="domain-ai-deep-learning-agents-v1").count() == 20
        primary_source = db.query(DBSourceDocument).filter_by(course_id=MASTER_ID, legacy_document_id=bundle["documents"][0]["id"]).one()
        assert primary_source.parser_metadata["source_role"] == bundle["documents"][0]["source_role"]

        first = ensure_primary_course_memberships(db)
        assert first["active_users"] == 3
        assert first["memberships_created_or_repaired"] == 3
        assert first["lzz_memberships_removed"] == 1
        assert db.query(DBCourseMembership).filter_by(course_id=MASTER_ID, status="active").count() == 3
        assert db.query(DBCourseMembership).filter_by(course_id="legacy-course", user_public_id="usr-lzz").one().status == "removed"
        assert db.get(DBStudentProfile, "lzz").target_course == db.get(DBCourse, MASTER_ID).title

        second = ensure_primary_course_memberships(db)
        assert second["memberships_created_or_repaired"] == 0
        assert second["lzz_memberships_removed"] == 0
    finally:
        db.close()
        engine.dispose()


def test_master_bundle_prunes_undeclared_legacy_canonical_source():
    engine, db = _session()
    try:
        bundle = load_versioned_course_bundle(MANIFEST)
        upsert_course_bundle(db, bundle)
        source = DBSourceDocument(
            id="src-stale-master",
            course_id=MASTER_ID,
            legacy_document_id="legacy-master-doc",
            title="旧版重复来源",
            filename="old-master.md",
            file_format="md",
            content_hash="a" * 64,
            source_sha256="a" * 64,
            processed_sha256="a" * 64,
            source_path="legacy:old-master.md",
            source_url="https://example.invalid/old-master",
            license_text="test",
            parser_version="edumatrix-course-source-v1",
            processing_status="ready",
        )
        db.add(source)
        db.flush()
        chapter = DBChapter(
            id="ch-stale-master",
            course_id=MASTER_ID,
            source_document_id=source.id,
            stable_key="legacy-master-chapter",
            title="旧版重复章节",
            position=999,
            char_start=0,
            char_end=10,
        )
        chapter_id = chapter.id
        db.add(chapter)
        db.flush()
        db.add(DBSourceRef(
            id="ref-stale-master",
            source_document_id=source.id,
            chapter_id=chapter.id,
            parser_version="edumatrix-course-source-v1",
            char_start=0,
            char_end=10,
            content_hash="a" * 64,
            quote="旧版重复来源",
        ))
        point = db.query(DBKnowledgePoint).filter_by(
            domain_pack="domain-ai-deep-learning-agents-v1"
        ).first()
        db.add(DBChapterKnowledgePoint(
            chapter_id=chapter.id,
            knowledge_point_id=point.id,
            relation_type="teaches",
        ))
        db.commit()

        upsert_course_bundle(db, bundle)

        assert db.get(DBSourceDocument, source.id) is None
        assert db.get(DBChapter, chapter_id) is None
        assert db.get(DBSourceRef, "ref-stale-master") is None
        assert db.query(DBSourceDocument).filter_by(course_id=MASTER_ID).count() == len(bundle["documents"])
        assert db.query(DBChapter).filter_by(course_id=MASTER_ID).count() == len(bundle["documents"])
    finally:
        db.close()
        engine.dispose()
