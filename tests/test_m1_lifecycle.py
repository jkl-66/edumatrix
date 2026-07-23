from __future__ import annotations

import asyncio
from datetime import timedelta

from app.auth import get_password_hash
from app.database import (
    DBArtifact,
    DBAuditLog,
    DBLearningEvent,
    DBMemoryItem,
    DBPlanDraft,
    DBPublication,
    DBReviewDecision,
    DBUser,
    SessionLocal,
)
from app.identity import new_public_id
from app.m1_lifecycle import (
    add_plan_version,
    create_review_and_publication,
    publish_learning_path,
    record_audit,
    update_artifact_title,
    set_artifact_archived,
    utcnow,
)


def _user(session):
    user = DBUser(username=new_public_id("m1-life-user"), hashed_password=get_password_hash("test-password"))
    session.add(user)
    session.flush()
    return user


def test_plan_versions_paths_audit_and_optimistic_concurrency():
    with SessionLocal() as session:
        user = _user(session)
        plan = DBPlanDraft(owner_public_id=user.public_id, title="Initial path")
        session.add(plan)
        session.flush()
        version = add_plan_version(
            session, plan=plan, content={"nodes": [{"title": "Retrieval"}]},
            created_by_public_id=user.public_id
        )
        path = publish_learning_path(
            session, owner_public_id=user.public_id, course_id="course-rag-engineering-m0",
            plan_version=version, nodes=[{"node_type": "chapter", "title": "Retrieval"}]
        )
        record_audit(
            session, actor_public_id=user.public_id, action="path.publish",
            object_type="learning_path", object_id=path.id, metadata={"content": "secret"}
        )
        session.commit()
        assert version.version_number == 1
        assert path.id.startswith("path-")
        audit = session.query(DBAuditLog).filter_by(object_id=path.id).one()
        assert "content" not in (audit.metadata_json or {})

        artifact = DBArtifact(
            owner_public_id=user.public_id, artifact_type="lesson", title="before"
        )
        session.add(artifact)
        session.commit()
        update_artifact_title(
            session, artifact_id=artifact.id, owner_public_id=user.public_id,
            expected_version=1, title="after"
        )
        session.commit()
        assert artifact.lock_version == 2
        try:
            update_artifact_title(
                session, artifact_id=artifact.id, owner_public_id=user.public_id,
                expected_version=1, title="stale"
            )
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 409
        else:
            raise AssertionError("stale version must be rejected")

        set_artifact_archived(
            session, artifact=artifact, actor_public_id=user.public_id, archived=True
        )
        session.commit()
        assert artifact.archived_at is not None
        assert artifact.status == "archived"
        set_artifact_archived(
            session, artifact=artifact, actor_public_id=user.public_id, archived=False
        )
        session.commit()
        assert artifact.archived_at is None


def test_review_publish_and_memory_lifecycle_are_separate():
    with SessionLocal() as session:
        user = _user(session)
        from app.m1_repository import create_artifact_with_version
        artifact, version = create_artifact_with_version(
            session, owner_public_id=user.public_id, artifact_type="lesson",
            title="Reviewable", content="content"
        )
        review, publication = create_review_and_publication(
            session, artifact_version_id=version.id, reviewer_public_id=user.public_id,
            decision="approved", visibility="public"
        )
        memory = DBMemoryItem(
            owner_public_id=user.public_id, memory_type="preference", content="prefers code",
            source_type="feedback", source_id=version.id, confidence=0.9,
            expires_at=utcnow() + timedelta(days=30)
        )
        session.add(memory)
        session.commit()
        assert session.query(DBReviewDecision).filter_by(id=review.id).one().decision == "approved"
        assert session.query(DBPublication).filter_by(id=publication.id).one().visibility == "public"
        assert session.query(DBMemoryItem).filter_by(id=memory.id).one().sensitivity == "personal"


def test_legacy_learning_event_is_durable_without_breaking_event_shape():
    from learning_event_bus import QuizAttemptedEvent, LearningEventBus

    event = QuizAttemptedEvent(
        student_id=new_public_id("legacy-student"), concept="KP-11", accuracy=1.0,
        ai_confidence=0.9, student_confidence=0.8, attempt_number=1
    )
    asyncio.run(LearningEventBus.get_instance().publish(event))
    with SessionLocal() as session:
        row = session.query(DBLearningEvent).filter_by(event_type="quiz_attempted").order_by(DBLearningEvent.recorded_at.desc()).first()
        assert row is not None
        assert row.schema_version == "1.0"
        assert row.payload["concept"] == "KP-11"
