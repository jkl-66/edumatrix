from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, DBCourseMembership, DBProfileSnapshot, DBUser
from app.m2_context import M2ContextAssemblyError, assemble_verified_context
from app.m3_baseline import seed_m3_profile_baselines, seed_m3_profile_for_owner


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def test_three_gold_profiles_persist_as_distinct_immutable_verified_contexts():
    engine, session = _session()
    try:
        baseline = seed_m3_profile_baselines(session)
        contexts = [fixture.generation_context for fixture in baseline.fixtures]

        assert len(contexts) == 3
        assert len({context.owner_public_id for context in contexts}) == 3
        assert len({context.profile_snapshot_id for context in contexts}) == 3
        assert len({context.course_id for context in contexts}) == 1
        assert len({context.domain_version_id for context in contexts}) == 1
        assert len({tuple(context.target_knowledge_point_ids) for context in contexts}) == 1
        assert len({tuple(context.source_ref_ids) for context in contexts}) == 1
        assert session.query(DBUser).filter(DBUser.public_id.in_([c.owner_public_id for c in contexts])).count() == 3
        assert session.query(DBCourseMembership).filter(
            DBCourseMembership.user_public_id.in_([c.owner_public_id for c in contexts])
        ).count() == 3
        assert session.query(DBProfileSnapshot).filter(
            DBProfileSnapshot.id.in_([c.profile_snapshot_id for c in contexts])
        ).count() == 3

        repeated = seed_m3_profile_baselines(session)
        assert repeated == baseline
    finally:
        session.close()
        engine.dispose()


def test_verified_assembly_accepts_focus_targets_and_rejects_cross_owner_snapshot():
    engine, session = _session()
    try:
        fixtures = seed_m3_profile_baselines(session).fixtures
        first, second = fixtures[0], fixtures[1]
        context = first.generation_context

        rebuilt = assemble_verified_context(
            session,
            owner_public_id=context.owner_public_id,
            course_id=context.course_id,
            domain_version_id=context.domain_version_id,
            profile_snapshot_id=context.profile_snapshot_id,
            target_knowledge_point_ids=context.target_knowledge_point_ids,
            source_ref_ids=context.source_ref_ids,
        )
        assert rebuilt == context

        with pytest.raises(M2ContextAssemblyError) as raised:
            assemble_verified_context(
                session,
                owner_public_id=second.generation_context.owner_public_id,
                course_id=context.course_id,
                domain_version_id=context.domain_version_id,
                profile_snapshot_id=context.profile_snapshot_id,
                target_knowledge_point_ids=context.target_knowledge_point_ids,
                source_ref_ids=context.source_ref_ids,
            )
        assert raised.value.code == "profile_snapshot_forbidden"
    finally:
        session.close()
        engine.dispose()


def test_tampered_gold_snapshot_is_not_silently_reseeded():
    engine, session = _session()
    try:
        baseline = seed_m3_profile_baselines(session)
        snapshot_id = baseline.fixtures[0].generation_context.profile_snapshot_id
        snapshot = session.query(DBProfileSnapshot).filter_by(id=snapshot_id).one()
        snapshot.snapshot = {**snapshot.snapshot, "synthetic_data": False}
        session.commit()

        with pytest.raises(ValueError, match="immutable"):
            seed_m3_profile_baselines(session)
    finally:
        session.close()
        engine.dispose()


def test_authenticated_owner_gets_server_assembled_gold_profile_copy():
    engine, session = _session()
    try:
        baselines = seed_m3_profile_baselines(session)
        owner = baselines.fixtures[0].generation_context.owner_public_id
        selected = seed_m3_profile_for_owner(
            session,
            owner_public_id=owner,
            source_profile_id="profile-m0-advanced",
        )
        repeated = seed_m3_profile_for_owner(
            session,
            owner_public_id=owner,
            source_profile_id="profile-m0-advanced",
        )

        assert selected == repeated
        assert selected.generation_context.owner_public_id == owner
        assert selected.gold_profile.source_profile.profile_id == "profile-m0-advanced"
        assert selected.generation_context.profile_snapshot_id != (
            baselines.fixtures[2].generation_context.profile_snapshot_id
        )
        snapshot = session.query(DBProfileSnapshot).filter_by(
            id=selected.generation_context.profile_snapshot_id
        ).one()
        assert snapshot.snapshot["synthetic_data"] is True
        assert snapshot.snapshot["source_profile_id"] == "profile-m0-advanced"
    finally:
        session.close()
        engine.dispose()
