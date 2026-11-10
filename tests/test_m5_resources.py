import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, DBAuditLog, DBCourse, DBKnowledgePoint, DBLearningEvent
from app.m1_repository import add_artifact_version, create_artifact_with_version
from app.m5_capabilities import M5CapabilityError
from app.m5_resources import (
    RESOURCE_CATALOG_TYPES,
    ResourceVersionCreateRequest,
    create_resource_version,
    compare_resource_versions,
    export_resource_version,
    resource_detail,
    resource_generation_blocker,
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


def test_long_resource_edit_compare_and_export_preserve_the_final_section():
    session, artifact = _resource()
    content = "# 完整学习材料\n" + "\n".join(f"第{i}条：核对来源与适用条件。" for i in range(14000)) + "\n末段：复习安排也须保留。"
    assert len(content) > 200_000
    old_id = artifact.current_version_id
    detail = create_resource_version(session, artifact=artifact, actor_public_id="usr-resource",
        request=ResourceVersionCreateRequest(expected_lock_version=artifact.lock_version,
            source_version_id=old_id, content=content, content_format="markdown"))
    assert detail["current_version_id"] != old_id
    assert export_resource_version(session, artifact=artifact)["version"]["content"] == content
    assert export_resource_version(session, artifact=artifact, version_number=2)["version"]["content"] == "line one\nnew line"
    compared = compare_resource_versions(session, artifact=artifact, left_version=2, right_version=3)
    assert len(compared["diff"]) > 200_000
    assert compared["diff"].endswith("+末段：复习安排也须保留。")
    assert compared["diff_truncated"] is False
    assert session.query(DBLearningEvent).count() == 0


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


def test_resource_catalog_filters_review_topic_before_counting_and_paging():
    session, old = _resource()
    selected, _ = create_artifact_with_version(
        session, owner_public_id="usr-resource", artifact_type="handout",
        title="Selected review topic", content="Review content",
        metadata={"knowledge_point_id": "review-topic"},
    )
    session.flush()
    payload = search_resources(session, owner_public_id="usr-resource", knowledge_point_id="review-topic", limit=1)
    assert [item["id"] for item in payload["items"]] == [selected.id]
    assert payload["total"] == 1 and not payload["has_more"]
    assert sum(payload["type_counts"].values()) == 1
    assert search_resources(session, owner_public_id="usr-resource", knowledge_point_id="missing")["items"] == []


@pytest.mark.parametrize("status", ["draft", "approved", "published", "withdrawn"])
def test_archive_restore_preserves_status_content_and_learning_records(status):
    session, artifact = _resource()
    artifact.status = status
    session.commit()
    before = export_resource_version(session, artifact=artifact)
    for _ in range(2):
        set_resource_archived(session, artifact=artifact, actor_public_id="usr-resource",
                              archived=True, expected_lock_version=artifact.lock_version)
        assert search_resources(session, owner_public_id="usr-resource")["total"] == 0
        assert search_resources(session, owner_public_id="usr-resource", include_archived=True)["total"] == 1
        assert "已归档" in resource_detail(session, artifact)["resource"]["learning_unavailable_reason"]
        assert resource_generation_blocker(session, artifact)
        assert export_resource_version(session, artifact=artifact)["version"] == before["version"]
        set_resource_archived(session, artifact=artifact, actor_public_id="usr-resource",
                              archived=False, expected_lock_version=artifact.lock_version)
        assert artifact.status == status
        assert search_resources(session, owner_public_id="usr-resource")["total"] == 1
        assert resource_generation_blocker(session, artifact) == ""
    assert session.query(DBLearningEvent).count() == 0


@pytest.mark.parametrize("kind,event_type,object_type", [
    ("code_sandbox", "code_tests_passed", "artifact"),
    ("interactive_model", "interactive_model_observation_submitted", "interactive_model"),
])
def test_catalog_completion_uses_the_same_owner_course_and_source_version(kind, event_type, object_type):
    session, _ = _resource()
    artifact, version = create_artifact_with_version(session, owner_public_id="usr-resource",
        artifact_type=kind, title="完成记录核对", content="Test")
    event = DBLearningEvent(id="catalog-completion", owner_public_id="usr-resource", course_id=None,
        event_type=event_type, object_type=object_type, object_id=artifact.id, trace_id="catalog-completion",
        evidence_status="accepted", evidence_strength=0.9, mastery_eligible=True,
        context_ref={"resource_version_id": version.id},
        payload={"resource_version_id": version.id} if kind == "code_sandbox" else {"result_version_id": "lab-result"})
    session.add(event)
    session.flush()
    def completion():
        return next(row for row in search_resources(session, owner_public_id="usr-resource")["items"]
                    if row["id"] == artifact.id)["completion"]["status"]
    assert completion() == "completed"
    event.course_id = "other-course"
    session.flush()
    assert completion() == "not_recorded"
    event.course_id = None
    event.owner_public_id = "other-learner"
    session.flush()
    assert completion() == "not_recorded"
    event.owner_public_id = "usr-resource"
    add_artifact_version(session, artifact=artifact, content="New version", created_by_public_id="usr-resource")
    assert completion() == "not_recorded"


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


@pytest.mark.parametrize("serialize", [str, json.dumps])
def test_resource_completion_projects_legacy_rules_without_rewriting_them(serialize):
    session, artifact = _resource()
    original = serialize({
        "description": "完成三组参数对比。",
        "criteria": [{"id": "complexity_sweep", "description": "比较复杂度1、5、10。"},
                     {"id": "explain", "description": "解释验证表现的变化。"}],
    })
    version = artifact_payload_versions(session, artifact.id)[-1]
    version.metadata_json = {"completion_rule": original}
    session.commit()

    item = search_resources(session, owner_public_id="usr-resource")["items"][0]
    assert item["completion"]["rule"] == original
    assert item["completion"]["display_rule"] == "完成三组参数对比。\n比较复杂度1、5、10。\n解释验证表现的变化。"
    session.refresh(version)
    assert version.metadata_json["completion_rule"] == original


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
