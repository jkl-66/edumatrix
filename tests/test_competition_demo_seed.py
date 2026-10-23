from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_password_hash, verify_password
from app.competition_demo_seed import (
    CompetitionDemoSeedError,
    load_competition_demo_manifest,
    seed_competition_demo,
)
from app.database import (
    Base,
    DBAuditLog,
    DBArtifact,
    DBChapter,
    DBCourse,
    DBLearningEvent,
    DBSourceRef,
    DBTeachingClassMember,
    DBUser,
)


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def test_competition_demo_seed_is_idempotent_and_complete():
    engine, session = _session()
    try:
        first = seed_competition_demo(session)
        counts = dict(first.object_counts)
        second = seed_competition_demo(session)

        assert first.status == "created"
        assert second.status == "unchanged"
        assert second.created_count == 0
        assert second.object_counts == counts
        assert counts == {
            "courses": 1,
            "source_documents": 9,
            "chapters": 12,
            "course_memberships": 19,
            "class_members": 17,
            "profile_snapshots": 15,
            "plans": 2,
            "paths": 2,
            "path_nodes": 4,
            "artifacts": 3,
            "assessment_questions": 5,
            "learning_events": 127,
        }
        assert session.query(DBAuditLog).filter_by(action="competition_demo.seed.applied").count() == 1
        assert session.query(DBAuditLog).filter_by(action="competition_demo.seed.repaired").count() == 0
        chapter = session.query(DBChapter).filter_by(id="demo-ch-07").one()
        source_ref = session.query(DBSourceRef).filter_by(id="demo-ref-07").one()
        assert len(source_ref.quote) >= 80
        assert "混合检索先合并候选" in source_ref.quote
        assert (chapter.char_start, chapter.char_end) == (source_ref.char_start, source_ref.char_end)
        assert chapter.char_end - chapter.char_start == len(source_ref.quote)
    finally:
        session.close()
        engine.dispose()


def test_competition_demo_seed_repairs_one_missing_object_without_duplicates():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        session.query(DBLearningEvent).filter_by(id="demo-event-stu-002-activity-01").delete()
        session.commit()

        repaired = seed_competition_demo(session)
        assert repaired.status == "repaired"
        assert repaired.repaired_count == 1
        assert repaired.object_counts["learning_events"] == 127
        assert session.query(DBAuditLog).filter_by(action="competition_demo.seed.repaired").count() == 1
    finally:
        session.close()
        engine.dispose()


def test_existing_named_accounts_are_bound_without_password_or_public_id_rewrite():
    engine, session = _session()
    try:
        original_hash = get_password_hash("user-owned-password")
        session.add(DBUser(
            public_id="usr-existing-lzz", username="lzz", hashed_password=original_hash,
            role="student", display_name="用户自有账号",
        ))
        session.commit()

        result = seed_competition_demo(session)
        user = session.query(DBUser).filter_by(username="lzz").one()
        assert result.identity_bindings["usr-demo-lzz"] == "usr-existing-lzz"
        assert user.public_id == "usr-existing-lzz"
        assert user.display_name == "用户自有账号"
        assert verify_password("user-owned-password", user.hashed_password)
        assert session.query(DBUser).filter_by(username="lzz").count() == 1
    finally:
        session.close()
        engine.dispose()


def test_demo_seed_rejects_conflicting_canonical_course():
    engine, session = _session()
    try:
        session.add(DBCourse(
            id="demo-course-rag-trust-v1", version="other", title="conflict",
            manifest_version="other", manifest_data={"other": True},
        ))
        session.commit()
        with pytest.raises(CompetitionDemoSeedError, match="conflicts"):
            seed_competition_demo(session)
        assert session.query(DBTeachingClassMember).count() == 0
    finally:
        session.close()
        engine.dispose()


def test_demo_seed_fails_closed_for_modified_manifest(tmp_path):
    manifest = load_competition_demo_manifest()
    manifest["demo_scope"] = "another-demo"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    engine, session = _session()
    try:
        with pytest.raises(CompetitionDemoSeedError, match="unsupported"):
            seed_competition_demo(session, path)
        assert session.query(DBArtifact).count() == 0
    finally:
        session.close()
        engine.dispose()
