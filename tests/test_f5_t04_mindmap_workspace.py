from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, DBCourse, DBSourceDocument, DBSourceRef
from app.m1_repository import add_artifact_version, create_artifact_with_version
from app.m5_capabilities import M5CapabilityError
from app.m5_resources import parse_mindmap_content, resource_detail
from app.resource_bundles import _deterministic_demo_content


ROOT = Path(__file__).resolve().parents[1]


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _source(session, *, status: str = "ready") -> tuple[DBCourse, DBSourceRef]:
    course = DBCourse(
        id=f"course-mindmap-{status}", version="1", title="机器学习基础",
        manifest_version=f"mindmap-{status}",
    )
    document = DBSourceDocument(
        course_id=course.id, title="优化算法课程讲义", filename="optimization.md",
        file_format="markdown", content_hash="a" * 64, source_sha256="b" * 64,
        processed_sha256="c" * 64, processing_status=status,
    )
    session.add_all([course, document])
    session.flush()
    source_ref = DBSourceRef(
        source_document_id=document.id, parser_version="mindmap-parser-v1",
        location_kind="section", location_label="第 2 章 梯度下降", content_hash="d" * 64,
    )
    session.add(source_ref)
    session.flush()
    return course, source_ref


def _content(source_ref_id: str = "ref-mindmap", linked_id: str | None = None) -> dict:
    linked = [linked_id] if linked_id else []
    return {
        "schemaVersion": "f5.mindmap.v1",
        "title": "梯度下降思维导图",
        "summary": "从概念、机制和验证方法理解梯度下降。",
        "learningGoal": "解释梯度方向和学习率之间的关系。",
        "rootNodeId": "root",
        "nodes": [
            {
                "nodeId": "root", "parentNodeId": None, "label": "梯度下降",
                "summary": "沿负梯度方向迭代更新参数。", "relation": "主题", "depth": 0,
                "sourceRefs": [source_ref_id], "masteryBand": "developing",
                "linkedResourceIds": linked,
            },
            {
                "nodeId": "gradient", "parentNodeId": "root", "label": "负梯度方向",
                "summary": "梯度给出局部上升最快方向。", "relation": "组成", "depth": 1,
                "sourceRefs": [source_ref_id], "masteryBand": "secure",
                "linkedResourceIds": linked,
            },
            {
                "nodeId": "rate", "parentNodeId": "root", "label": "学习率",
                "summary": "学习率控制单次参数更新步长。", "relation": "组成", "depth": 1,
                "sourceRefs": [source_ref_id], "masteryBand": "needs_work",
                "linkedResourceIds": [],
            },
            {
                "nodeId": "check", "parentNodeId": "rate", "label": "收敛检查",
                "summary": "观察损失变化并识别振荡或发散。", "relation": "验证", "depth": 2,
                "sourceRefs": [source_ref_id], "masteryBand": "unknown",
                "linkedResourceIds": [],
            },
        ],
    }


def _mindmap(session, *, source_status: str = "ready", content: dict | None = None):
    course, source_ref = _source(session, status=source_status)
    handout, _ = create_artifact_with_version(
        session, owner_public_id="usr-mindmap", course_id=course.id,
        artifact_type="handout", title="梯度下降个性化讲义", content="# 讲义",
        metadata={"resource_type": "handout", "source_ref_ids": [source_ref.id]},
    )
    payload = content or _content(source_ref.id, handout.id)
    artifact, version = create_artifact_with_version(
        session, owner_public_id="usr-mindmap", course_id=course.id,
        artifact_type="mind_map", title="梯度下降思维导图",
        content=json.dumps(payload, ensure_ascii=False), content_format="json",
        metadata={"resource_type": "mind_map", "source_ref_ids": [source_ref.id]},
    )
    session.commit()
    return artifact, version, source_ref, handout


def test_mindmap_schema_requires_one_connected_acyclic_tree():
    parsed = parse_mindmap_content(json.dumps(_content(), ensure_ascii=False))
    assert parsed.rootNodeId == "root"
    assert len(parsed.nodes) == 4

    invalid_payloads = []
    duplicate = _content()
    duplicate["nodes"][1]["nodeId"] = "root"
    invalid_payloads.append(duplicate)
    orphan = _content()
    orphan["nodes"][1]["parentNodeId"] = "missing"
    invalid_payloads.append(orphan)
    wrong_depth = _content()
    wrong_depth["nodes"][2]["depth"] = 3
    invalid_payloads.append(wrong_depth)
    cycle = _content()
    cycle["nodes"][0]["parentNodeId"] = "check"
    invalid_payloads.append(cycle)

    for payload in invalid_payloads:
        with pytest.raises(M5CapabilityError) as exc_info:
            parse_mindmap_content(json.dumps(payload, ensure_ascii=False))
        assert exc_info.value.code == "mindmap_content_incomplete"


def test_structured_mindmap_projects_sources_and_safe_resource_links():
    session = _session()
    artifact, _, source_ref, handout = _mindmap(session)
    projection = resource_detail(session, artifact)["mindmap"]["current"]

    assert projection["mode"] == "structured"
    assert projection["source_readiness"]["publishable"] is True
    assert projection["structured"]["nodes"][0]["sourceRefs"] == [source_ref.id]
    assert projection["linked_resources"] == [{
        "id": handout.id,
        "title": handout.title,
        "type": "handout",
        "type_label": "个性化讲义",
        "route": f"/workspace/resources/handouts/{handout.id}",
        "available": True,
    }]


def test_missing_or_cross_owner_links_are_not_exposed_as_available():
    session = _session()
    artifact, current, _, _ = _mindmap(session)
    payload = json.loads(current.content)
    payload["nodes"][0]["linkedResourceIds"] = ["missing-resource"]
    current.content = json.dumps(payload, ensure_ascii=False)
    session.commit()

    linked = resource_detail(session, artifact)["mindmap"]["current"]["linked_resources"]
    by_id = {item["id"]: item for item in linked}
    assert by_id["missing-resource"] == {"id": "missing-resource", "available": False}
    assert any(item.get("type") == "handout" and item["available"] is True for item in linked)


def test_failed_source_blocks_publish_ready_state_without_hiding_tree():
    session = _session()
    artifact, _, _, _ = _mindmap(session, source_status="failed")
    projection = resource_detail(session, artifact)["mindmap"]["current"]

    assert projection["mode"] == "structured"
    assert projection["structured"]["nodes"]
    assert projection["source_readiness"]["available"] is False
    assert projection["source_readiness"]["publishable"] is False


def test_legacy_and_invalid_mindmaps_have_honest_hierarchy_fallbacks():
    session = _session()
    legacy, _ = create_artifact_with_version(
        session, owner_public_id="usr-mindmap", artifact_type="mindmap", title="旧导图",
        content="# 旧导图\n- 核心概念\n  - 子概念", content_format="markdown",
    )
    invalid, _ = create_artifact_with_version(
        session, owner_public_id="usr-mindmap", artifact_type="mind_map", title="损坏导图",
        content=json.dumps({"schemaVersion": "f5.mindmap.v1", "title": "损坏"}, ensure_ascii=False),
        content_format="json", metadata={"resource_type": "mind_map"},
    )
    session.commit()

    legacy_projection = resource_detail(session, legacy)["mindmap"]["current"]
    invalid_projection = resource_detail(session, invalid)["mindmap"]["current"]
    assert legacy_projection["mode"] == "legacy_markdown"
    assert [item["label"] for item in legacy_projection["legacy"]["hierarchy"]] == ["旧导图", "核心概念", "子概念"]
    assert invalid_projection["mode"] == "invalid_structured"
    assert invalid_projection["invalid"]["hierarchy"][0]["label"] == "损坏导图"
    assert invalid_projection["warnings"] == ["当前思维导图的节点层级或关系不完整，已切换为安全阅读状态。"]


def test_mindmap_versions_remain_read_only_in_workspace_projection():
    session = _session()
    artifact, first, source_ref, handout = _mindmap(session)
    second_content = _content(source_ref.id, handout.id)
    second_content["summary"] = "第二版导图摘要"
    second = add_artifact_version(
        session, artifact=artifact, content=json.dumps(second_content, ensure_ascii=False),
        content_format="json", created_by_public_id="usr-mindmap", metadata=first.metadata_json,
    )
    session.commit()

    payload = resource_detail(session, artifact)["mindmap"]
    assert payload["current_version_id"] == second.id
    assert [item["number"] for item in payload["versions"]] == [1, 2]
    assert first.content != second.content


def test_deterministic_demo_generates_complete_structured_mindmap():
    content = _deterministic_demo_content(
        resource_type="mind_map",
        item={"title": "梯度下降思维导图"},
        manifest={
            "knowledge_point_id": "kp-gradient",
            "context": {
                "knowledge_point_title": "梯度下降",
                "learning_goal": "解释梯度下降更新机制",
            },
        },
        source_snapshots=[{
            "source_ref_id": "ref-gradient", "title": "优化算法课程讲义",
            "location_label": "第 2 章 梯度下降",
        }],
        linked_resource_ids=["artifact-handout"],
    )
    parsed = parse_mindmap_content(content)
    assert parsed.schemaVersion == "f5.mindmap.v1"
    assert parsed.rootNodeId == "root"
    assert parsed.nodes[0].linkedResourceIds == ["artifact-handout"]
    assert {node.relation for node in parsed.nodes} >= {"主题", "组成", "前置", "验证", "应用"}


def test_frontend_contract_uses_dedicated_workspace_and_no_evidence_write_calls():
    router = (ROOT / "frontend" / "src" / "router" / "index.js").read_text(encoding="utf-8")
    workspace_path = ROOT / "frontend" / "src" / "views" / "MindmapWorkspace.vue"
    assert "const MindmapWorkspace" in router
    assert "name: 'MindmapResource', component: MindmapWorkspace" in router
    workspace = workspace_path.read_text(encoding="utf-8")
    assert "getM5Resource" in workspace
    assert "CollapsibleMindmap" in workspace
    assert "canonical_source_id: source.source_document_id" in workspace
    knowledge = (ROOT / "frontend" / "src" / "views" / "Knowledge.vue").read_text(encoding="utf-8")
    assert "resolveCanonicalSourceDeepLink" in knowledge
    assert "getCanonicalCourseSource(sourceDocumentId)" in knowledge
    for forbidden in ("recordLearningEvent", "completeWorkItem", "updateProfile", "unlockExam"):
        assert forbidden not in workspace
