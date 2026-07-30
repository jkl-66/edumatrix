import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, DBAuditLog
from app.m1_repository import add_artifact_version, create_artifact_with_version
from app.m5_capabilities import M5CapabilityError
from app.m5_resources import (
    compare_resource_versions,
    export_resource_version,
    search_resources,
    set_resource_archived,
)


def _resource():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    artifact, _ = create_artifact_with_version(
        session, owner_public_id="usr-resource", artifact_type="lesson",
        title="RAG Recall Lesson", content="line one\nold line",
    )
    add_artifact_version(
        session, artifact=artifact, content="line one\nnew line",
        created_by_public_id="usr-resource",
    )
    session.commit()
    return session, artifact


def test_m5_resource_center_search_compare_and_hash_checked_export():
    session, artifact = _resource()
    found = search_resources(session, owner_public_id="usr-resource", query="recall")
    compared = compare_resource_versions(session, artifact=artifact, left_version=1, right_version=2)
    exported = export_resource_version(session, artifact=artifact)

    assert [item["id"] for item in found["items"]] == [artifact.id]
    assert compared["changed"] is True
    assert "-old line" in compared["diff"] and "+new line" in compared["diff"]
    assert exported["version"]["number"] == 2
    assert len(exported["version"]["persisted_content_hash"]) == 64
    assert len(exported["version"]["export_content_hash"]) == 64


def test_m5_resource_archive_is_audited_and_optimistically_locked():
    session, artifact = _resource()
    archived = set_resource_archived(
        session, artifact=artifact, actor_public_id="usr-resource",
        archived=True, expected_lock_version=1,
    )
    assert archived["archived"] is True
    assert archived["lock_version"] == 2
    assert session.query(DBAuditLog).filter_by(object_id=artifact.id, action="artifact.archive").count() == 1
    with pytest.raises(M5CapabilityError, match="lock version"):
        set_resource_archived(
            session, artifact=artifact, actor_public_id="usr-resource",
            archived=False, expected_lock_version=1,
        )


def test_m5_resource_export_does_not_expose_tiered_quiz_answer_keys():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    levels = ("foundation", "application", "advanced")
    content = json.dumps({
        "artifact_type": "tiered_quiz",
        "schema_version": "m2.tiered_quiz.v1",
        "title": "Safe quiz",
        "instructions": "Answer all questions.",
        "tiers": [{
            "level": level,
            "questions": [{
                "id": f"q-{index}", "prompt": "Question", "knowledge_point_ids": ["kp-1"],
                "bloom_level": "understand", "difficulty_basis": "L2",
                "scoring_rule": "one point", "answer_key": "secret answer",
                "explanation": "secret explanation", "source_ref_ids": ["ref-1"],
            }],
        } for index, level in enumerate(levels, start=1)],
        "pass_rules": {level: "pass one" for level in levels},
    })
    artifact, _ = create_artifact_with_version(
        session, owner_public_id="usr-resource", artifact_type="tiered_quiz",
        title="Safe quiz", content=content, content_format="json",
    )
    session.commit()

    exported = export_resource_version(session, artifact=artifact)

    assert "secret answer" not in exported["version"]["content"]
    assert "answer_key" not in exported["version"]["content"]
    assert exported["version"]["persisted_content_hash"] != exported["version"]["export_content_hash"]
