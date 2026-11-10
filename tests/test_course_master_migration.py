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


def test_computational_performance_source_has_matching_title_and_knowledge():
    bundle = load_versioned_course_bundle(MANIFEST)
    document = next(item for item in bundle["documents"] if item["chapter_order"] == 11)
    assert document["title"] == "D2L 计算性能与并行训练"
    assert document["knowledge_point_codes"] == ["AI-KP-21-01", "AI-KP-21-02", "AI-KP-21-03"]
    assert "异步计算" in document["content"] and "多GPU" in document["content"]
    assert "无监督学习与表示" in document["filename"]  # Stable identity, corrected display title.
    # Same upstream files, now concatenated in the textbook's declared order.
    assert document["source_sha256"] == "fc686447b859f4ac20c588d06c26372514b264256753ff14dc627f8718695cff"
    assert document["content"].index("上游文件: chapter_computational-performance/index.md") < document["content"].index("上游文件: chapter_computational-performance/async-computation.md")
    assert bundle["knowledge_point_version"] == "ai-deep-learning-agents-kp-1.0.0"
    assert any(point["code"] == "AI-KP-12" and "无监督学习" in point["title"] for point in bundle["knowledge_points"])


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
        assert db.query(DBChapter).filter(DBChapter.course_id == MASTER_ID, DBChapter.stable_key.startswith("structure:")).count() == len(bundle["course"]["manifest_data"]["teaching_structure"]["chapters"])
        assert db.query(DBSourceRef).join(DBSourceDocument, DBSourceRef.source_document_id == DBSourceDocument.id).filter(DBSourceDocument.course_id == MASTER_ID).count() == len(bundle["documents"]) + len(bundle["course"]["manifest_data"]["teaching_structure"]["chapters"])
        assert db.query(DBKnowledgePoint).filter_by(domain_pack="domain-ai-deep-learning-agents-v1").count() == len(bundle["knowledge_points"])
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


def test_master_bundle_retires_undeclared_bundle_source_and_preserves_its_history():
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
            parser_metadata={"origin": "versioned_course_bundle"},
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

        assert db.get(DBSourceDocument, source.id).parser_metadata["retired_from_catalog"] is True
        assert db.get(DBChapter, chapter_id).source_document_id == source.id
        assert db.get(DBSourceRef, "ref-stale-master").quote == "旧版重复来源"
        assert db.query(DBSourceDocument).filter_by(course_id=MASTER_ID).count() == len(bundle["documents"]) + 1
        assert db.query(DBChapter).filter(DBChapter.course_id == MASTER_ID, DBChapter.stable_key.startswith("structure:")).count() == len(bundle["course"]["manifest_data"]["teaching_structure"]["chapters"])
    finally:
        db.close()
        engine.dispose()
