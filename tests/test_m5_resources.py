import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, DBAuditLog, DBCourse, DBKnowledgePoint
from app.m1_repository import add_artifact_version, create_artifact_with_version
from app.m5_capabilities import M5CapabilityError
from app.m5_resources import (
    RESOURCE_CATALOG_TYPES,
    compare_resource_versions,
    export_resource_version,
    resource_route,
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


def test_resource_catalog_has_nine_types_counts_and_deep_links():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    for index, resource_type in enumerate(RESOURCE_CATALOG_TYPES, start=1):
        create_artifact_with_version(
            session,
            owner_public_id="usr-catalog",
            artifact_type=resource_type,
            title=f"资源 {index}",
            content=f"# {resource_type}",
            metadata={"resource_type": resource_type},
        )
    create_artifact_with_version(
        session,
        owner_public_id="usr-catalog",
        artifact_type="lesson",
        title="旧版讲义",
        content="# legacy lesson",
    )
    session.commit()

    catalog = search_resources(session, owner_public_id="usr-catalog", limit=100)

    assert [item["id"] for item in catalog["types"]] == list(RESOURCE_CATALOG_TYPES)
    assert catalog["type_counts"]["handout"] == 2
    assert all(catalog["type_counts"][kind] >= 1 for kind in RESOURCE_CATALOG_TYPES)
    assert {item["type"] for item in catalog["items"]} == set(RESOURCE_CATALOG_TYPES)
    assert all(item["route"] == resource_route(item["type"], item["id"]) for item in catalog["items"])
    assert next(item for item in catalog["items"] if item["title"] == "旧版讲义")["type"] == "handout"


def test_resource_catalog_searches_module_tags_and_knowledge_point_without_writes():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    course = DBCourse(
        id="course-resource-search",
        version="1",
        title="机器学习基础",
        manifest_version="resource-search-v1",
    )
    point = DBKnowledgePoint(
        domain_pack="ml",
        code="resource-search-gradient",
        version="1",
        title="梯度下降",
    )
    session.add_all([course, point])
    session.flush()
    artifact, _ = create_artifact_with_version(
        session,
        owner_public_id="usr-search",
        course_id=course.id,
        artifact_type="lesson",
        title="优化算法讲义",
        content="# 梯度下降\n\n学习率决定更新步长。",
        metadata={
            "module": "第二章 优化",
            "tags": ["优化器", "学习率"],
            "knowledge_point_id": point.id,
            "completion_rule": "阅读关键概念并完成小测",
        },
    )
    session.commit()
    version_count = len(artifact.id and artifact_payload_versions(session, artifact.id))
    audit_count = session.query(DBAuditLog).count()

    for query in ("优化算法", "第二章", "学习率", "梯度下降"):
        result = search_resources(session, owner_public_id="usr-search", query=query)
        assert [item["id"] for item in result["items"]] == [artifact.id]
        assert result["items"][0]["course"]["title"] == "机器学习基础"
        assert result["items"][0]["knowledge_point"]["title"] == "梯度下降"
        assert result["items"][0]["completion"]["status"] == "not_recorded"

    assert len(artifact_payload_versions(session, artifact.id)) == version_count
    assert session.query(DBAuditLog).count() == audit_count


def artifact_payload_versions(session, artifact_id):
    from app.database import DBArtifactVersion

    return session.query(DBArtifactVersion).filter_by(artifact_id=artifact_id).all()


def test_resource_catalog_preview_uses_learner_safe_content():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    content = json.dumps({
        "artifact_type": "tiered_quiz",
        "tiers": [{
            "level": "foundation",
            "questions": [{
                "prompt": "安全问题",
                "answer_key": "catalog-secret-answer",
                "explanation": "catalog-secret-explanation",
            }],
        }],
    })
    create_artifact_with_version(
        session,
        owner_public_id="usr-safe-preview",
        artifact_type="tiered_quiz",
        title="安全测验",
        content=content,
        content_format="json",
    )
    session.commit()

    catalog = search_resources(session, owner_public_id="usr-safe-preview")
    preview = catalog["items"][0]["preview"]["text"]

    assert catalog["items"][0]["type"] == "quiz"
    assert "catalog-secret-answer" not in preview
    assert "catalog-secret-explanation" not in preview
