from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import m5_resources
from app.database import (
    Base,
    DBArtifactVersion,
    DBCourse,
    DBSourceDocument,
    DBSourceRef,
    DBUser,
)
from app.m1_repository import add_artifact_version, create_artifact_with_version
from app.m5_api import _owned_resource
from app.m5_resources import (
    ResourceVersionCreateRequest,
    ResourceVersionRestoreRequest,
    compare_resource_versions,
    create_resource_version,
    resource_detail,
    restore_resource_version,
)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _user(session, public_id: str) -> DBUser:
    user = DBUser(
        public_id=public_id,
        username=public_id,
        hashed_password="test-only",
        role="student",
        display_name=public_id,
    )
    session.add(user)
    session.flush()
    return user


def _resource(session, owner_public_id: str = "usr-history"):
    course = DBCourse(id="course-history", version="1", title="ML Systems", manifest_version="history-v1")
    document = DBSourceDocument(
        course_id=course.id,
        title="Optimization Notes",
        filename="optimization.md",
        file_format="markdown",
        content_hash="a" * 64,
        source_sha256="b" * 64,
        processed_sha256="c" * 64,
        source_url="https://example.edu/optimization",
        license_text="Course material",
        processing_status="ready",
    )
    session.add_all([course, document])
    session.flush()
    source_ref = DBSourceRef(
        source_document_id=document.id,
        parser_version="history-parser-v1",
        location_kind="section",
        location_label="Gradient descent",
        content_hash="d" * 64,
    )
    session.add(source_ref)
    session.flush()
    artifact, first = create_artifact_with_version(
        session,
        owner_public_id=owner_public_id,
        course_id=course.id,
        artifact_type="mind_map",
        title="Gradient descent map",
        content="# Version 1",
        metadata={
            "resource_type": "mind_map",
            "knowledge_point_id": "kp-gradient",
            "source_ref_ids": [source_ref.id],
        },
    )
    session.commit()
    return artifact, first, document, source_ref


def test_history_projection_is_descending_read_only_and_source_aware():
    session = _session()
    _user(session, "usr-history")
    artifact, first, document, source_ref = _resource(session)
    second = add_artifact_version(
        session,
        artifact=artifact,
        content="# Version 2",
        created_by_public_id="usr-history",
        metadata={
            "resource_type": "mind_map",
            "knowledge_point_id": "kp-gradient",
            "source_ref_ids": [source_ref.id],
            "revision_origin": "learning_workspace",
            "revised_from_version_id": first.id,
        },
    )
    session.commit()

    history = resource_detail(session, artifact)["history"]
    assert history["current_version_id"] == second.id
    assert [item["number"] for item in history["items"]] == [2, 1]
    assert history["items"][0]["is_current"] is True
    assert history["items"][0]["revised_from_version_id"] == first.id
    assert history["items"][0]["source_refs"][0]["source_ref_id"] == source_ref.id
    assert history["items"][0]["source_status"] == "available"

    history["items"][0]["content_hash"] = "mutated-projection"
    assert session.get(DBArtifactVersion, second.id).content_hash != "mutated-projection"

    document.processing_status = "failed"
    session.commit()
    unavailable = resource_detail(session, artifact)["history"]["items"]
    assert all(item["source_status"] == "source_unavailable" for item in unavailable)


def test_historical_edit_and_restore_create_new_versions_without_mutating_old_versions():
    session = _session()
    owner = _user(session, "usr-history")
    artifact, first, _, _ = _resource(session)
    second = add_artifact_version(
        session,
        artifact=artifact,
        content="# Version 2",
        created_by_public_id=owner.public_id,
        metadata=first.metadata_json,
    )
    session.commit()

    create_resource_version(
        session,
        artifact=artifact,
        actor_public_id=owner.public_id,
        request=ResourceVersionCreateRequest(
            expected_lock_version=artifact.lock_version,
            source_version_id=first.id,
            content="# Version 3 from version 1",
            content_format="markdown",
        ),
    )
    third = session.get(DBArtifactVersion, artifact.current_version_id)
    restored = restore_resource_version(
        session,
        artifact=artifact,
        actor_public_id=owner.public_id,
        request=ResourceVersionRestoreRequest(
            expected_lock_version=artifact.lock_version,
            version_id=second.id,
        ),
    )
    fourth = session.get(DBArtifactVersion, artifact.current_version_id)

    assert [first.content, second.content, third.content, fourth.content] == [
        "# Version 1",
        "# Version 2",
        "# Version 3 from version 1",
        "# Version 2",
    ]
    assert third.metadata_json["revised_from_version_id"] == first.id
    assert fourth.metadata_json["restored_from_version_id"] == second.id
    assert fourth.metadata_json["previous_current_version_id"] == third.id
    assert restored["history"]["items"][0]["id"] == fourth.id
    assert restored["history"]["items"][0]["revision_origin"] == "history_restore"

    comparison = compare_resource_versions(
        session,
        artifact=artifact,
        left_version=1,
        right_version=3,
    )
    assert comparison["changed"] is True
    assert "Version 1" in comparison["diff"]
    assert session.get(DBArtifactVersion, first.id).content == "# Version 1"


def test_restore_failure_and_archived_resource_preserve_current_version(monkeypatch):
    session = _session()
    owner = _user(session, "usr-history")
    artifact, first, _, _ = _resource(session)
    second = add_artifact_version(
        session,
        artifact=artifact,
        content="# Version 2",
        created_by_public_id=owner.public_id,
        metadata=first.metadata_json,
    )
    session.commit()
    current_id = artifact.current_version_id
    version_count = session.query(DBArtifactVersion).filter_by(artifact_id=artifact.id).count()

    def fail_version_write(*args, **kwargs):
        raise RuntimeError("injected version write failure")

    monkeypatch.setattr(m5_resources, "add_artifact_version", fail_version_write)
    with pytest.raises(RuntimeError, match="injected"):
        restore_resource_version(
            session,
            artifact=artifact,
            actor_public_id=owner.public_id,
            request=ResourceVersionRestoreRequest(
                expected_lock_version=artifact.lock_version,
                version_id=first.id,
            ),
        )
    assert artifact.current_version_id == current_id
    assert session.query(DBArtifactVersion).filter_by(artifact_id=artifact.id).count() == version_count

    artifact.archived_at = artifact.updated_at
    session.commit()
    with pytest.raises(m5_resources.M5CapabilityError) as exc_info:
        restore_resource_version(
            session,
            artifact=artifact,
            actor_public_id=owner.public_id,
            request=ResourceVersionRestoreRequest(
                expected_lock_version=artifact.lock_version,
                version_id=first.id,
            ),
        )
    assert exc_info.value.code == "resource_archived"
    assert artifact.current_version_id == second.id


def test_resource_owner_isolation_applies_to_history_and_update_entrypoints():
    session = _session()
    owner = _user(session, "usr-history")
    stranger = _user(session, "usr-stranger")
    artifact, _, _, _ = _resource(session, owner.public_id)

    assert _owned_resource(session, artifact.id, owner, action="update").id == artifact.id
    with pytest.raises(HTTPException) as exc_info:
        _owned_resource(session, artifact.id, stranger, action="read")
    assert exc_info.value.status_code == 403

