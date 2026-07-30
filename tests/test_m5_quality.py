import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, DBQualityCheck
from app.m1_repository import create_artifact_with_version
from app.m5_quality import run_artifact_quality_checks


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _lesson():
    return {
        "artifact_type": "lesson",
        "schema_version": "m2.lesson.v1",
        "title": "Recall lesson",
        "objective": "Understand recall",
        "prerequisites": [],
        "sections": [{
            "heading": "Definition", "body_markdown": "Recall is...",
            "knowledge_point_ids": ["kp-1"], "source_ref_ids": ["ref-1"],
        }],
        "retrieval_questions": [],
        "summary": "Recall measures coverage.",
    }


def test_m5_quality_persists_idempotent_checks_for_known_schema():
    session = _session()
    artifact, version = create_artifact_with_version(
        session, owner_public_id="usr-quality", artifact_type="lesson",
        title="Lesson", content=json.dumps(_lesson()), content_format="json",
    )
    session.commit()
    first = run_artifact_quality_checks(session, artifact=artifact, version=version)
    second = run_artifact_quality_checks(session, artifact=artifact, version=version)
    session.commit()

    assert first.status == "passed" and first.ready_for_review is True
    assert second.check_ids == first.check_ids
    assert session.query(DBQualityCheck).filter_by(artifact_version_id=version.id).count() == 3


def test_m5_quality_unknown_type_requires_manual_review_and_verified_needs_sources():
    session = _session()
    unknown, unknown_version = create_artifact_with_version(
        session, owner_public_id="usr-quality", artifact_type="custom_report",
        title="Custom", content="body",
    )
    verified, verified_version = create_artifact_with_version(
        session, owner_public_id="usr-quality", artifact_type="lesson",
        title="Verified", content=json.dumps(_lesson()), content_format="json",
        metadata={"quality_mode": "verified", "source_ref_ids": []},
    )
    session.commit()

    manual = run_artifact_quality_checks(session, artifact=unknown, version=unknown_version)
    failed = run_artifact_quality_checks(session, artifact=verified, version=verified_version)

    assert manual.status == "manual_required" and manual.ready_for_review is False
    assert "artifact_type_checker_unregistered" in manual.blockers
    assert failed.status == "failed"
    assert "verified_source_refs_required" in failed.blockers
