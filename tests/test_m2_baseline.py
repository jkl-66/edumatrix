from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import (
    Base,
    DBCourseMembership,
    DBProfileSnapshot,
    DBSourceDocument,
    DBSourceRef,
    DBUser,
)
from app.m2_baseline import (
    M2_BASELINE_COURSE_ID,
    M2_BASELINE_OWNER_PUBLIC_ID,
    M2_BASELINE_PROFILE_SNAPSHOT_ID,
    M2_TARGET_KNOWLEDGE_POINT_CODE,
    seed_m2_baseline,
)


def _empty_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def test_m2_baseline_is_idempotent_and_binds_formal_objects():
    engine, session = _empty_session()
    try:
        first = seed_m2_baseline(session)
        second = seed_m2_baseline(session)
        assert second == first
        assert first.target_knowledge_point_code == M2_TARGET_KNOWLEDGE_POINT_CODE
        assert first.generation_context.quality_mode == "verified"
        assert first.generation_context.owner_public_id == M2_BASELINE_OWNER_PUBLIC_ID
        assert first.generation_context.course_id == M2_BASELINE_COURSE_ID
        assert first.required_artifact_types == ("lesson", "lab_guide", "tiered_quiz")
        assert session.query(DBUser).filter_by(public_id=M2_BASELINE_OWNER_PUBLIC_ID).count() == 1
        assert session.query(DBCourseMembership).filter_by(
            course_id=M2_BASELINE_COURSE_ID,
            user_public_id=M2_BASELINE_OWNER_PUBLIC_ID,
        ).count() == 1
        assert session.query(DBProfileSnapshot).filter_by(id=M2_BASELINE_PROFILE_SNAPSHOT_ID).count() == 1
        for source_ref_id in first.generation_context.source_ref_ids:
            source = (
                session.query(DBSourceDocument)
                .join(DBSourceRef, DBSourceRef.source_document_id == DBSourceDocument.id)
                .filter(DBSourceRef.id == source_ref_id)
                .one()
            )
            assert source.course_id == M2_BASELINE_COURSE_ID
    finally:
        session.close()
        engine.dispose()


def test_m2_baseline_ids_are_reproducible_across_empty_databases():
    first_engine, first_session = _empty_session()
    second_engine, second_session = _empty_session()
    try:
        first = seed_m2_baseline(first_session)
        second = seed_m2_baseline(second_session)
        assert first.model_dump() == second.model_dump()
    finally:
        first_session.close()
        second_session.close()
        first_engine.dispose()
        second_engine.dispose()


def test_m2_baseline_refuses_to_overwrite_the_frozen_profile_snapshot():
    engine, session = _empty_session()
    try:
        seed_m2_baseline(session)
        snapshot = session.query(DBProfileSnapshot).filter_by(id=M2_BASELINE_PROFILE_SNAPSHOT_ID).one()
        snapshot.snapshot = {"tampered": True}
        session.commit()
        try:
            seed_m2_baseline(session)
        except ValueError as exc:
            assert "immutable" in str(exc)
        else:
            raise AssertionError("tampered M2 baseline snapshot must be rejected")
    finally:
        session.close()
        engine.dispose()
