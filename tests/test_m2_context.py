from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, DBProfileSnapshot, DBSourceRef
from app.m2_baseline import seed_m2_baseline
from app.m2_context import M2ContextAssemblyError, assemble_verified_context


def _seeded_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    baseline = seed_m2_baseline(session)
    return engine, session, baseline


def _assemble(session, baseline, **changes):
    payload = baseline.generation_context.model_dump(exclude={"quality_mode"})
    payload.update(changes)
    return assemble_verified_context(session, **payload)


def test_verified_context_resolves_every_frozen_baseline_object():
    engine, session, baseline = _seeded_session()
    try:
        context = _assemble(session, baseline)
        assert context == baseline.generation_context
        assert context.quality_mode == "verified"
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"owner_public_id": "usr-missing-owner"}, "owner_not_found"),
        ({"domain_version_id": "dv-missing"}, "domain_version_not_found"),
        ({"target_knowledge_point_ids": ["kp-missing"]}, "knowledge_point_not_found"),
        ({"source_ref_ids": ["ref-missing"]}, "source_ref_not_found"),
    ],
)
def test_verified_context_rejects_missing_or_unbound_authority_objects(change, code):
    engine, session, baseline = _seeded_session()
    try:
        with pytest.raises(M2ContextAssemblyError) as raised:
            _assemble(session, baseline, **change)
        assert raised.value.code == code
    finally:
        session.close()
        engine.dispose()


def test_verified_context_rejects_irrelevant_course_source():
    engine, session, baseline = _seeded_session()
    try:
        relevant_ids = set(baseline.generation_context.source_ref_ids)
        irrelevant = session.query(DBSourceRef).filter(~DBSourceRef.id.in_(relevant_ids)).first()
        assert irrelevant is not None
        with pytest.raises(M2ContextAssemblyError) as raised:
            _assemble(session, baseline, source_ref_ids=[irrelevant.id])
        assert raised.value.code in {"target_without_source", "source_not_relevant"}
    finally:
        session.close()
        engine.dispose()


def test_verified_context_rejects_tampered_or_cross_owner_snapshot():
    engine, session, baseline = _seeded_session()
    try:
        snapshot = session.query(DBProfileSnapshot).filter_by(
            id=baseline.generation_context.profile_snapshot_id
        ).one()
        snapshot.owner_public_id = "usr-unrelated-owner"
        session.commit()
        with pytest.raises(M2ContextAssemblyError) as raised:
            _assemble(session, baseline)
        assert raised.value.code == "profile_snapshot_forbidden"

        snapshot.owner_public_id = baseline.generation_context.owner_public_id
        snapshot.snapshot = {**snapshot.snapshot, "course_id": "course-tampered"}
        session.commit()
        with pytest.raises(M2ContextAssemblyError) as raised:
            _assemble(session, baseline)
        assert raised.value.code == "profile_snapshot_tampered"
    finally:
        session.close()
        engine.dispose()
