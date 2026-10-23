from __future__ import annotations

import json
from pathlib import Path

from app.database import DBLearningEvent
from app.m1_repository import create_artifact_with_version
from app.m5_resources import _legacy_mindmap_hierarchy, resource_detail
from tests.test_f5_t04_mindmap_workspace import _session, _source


ROOT = Path(__file__).resolve().parents[1]


def test_legacy_adapter_preserves_mermaid_like_hierarchy_and_shapes():
    rows = _legacy_mindmap_hierarchy(
        "mindmap\n"
        "  root((梯度下降))\n"
        "    direction[负梯度方向]\n"
        "      chain{{链式法则}}\n"
        "    rate(学习率)\n",
        "备用标题",
    )

    assert [row["label"] for row in rows] == ["梯度下降", "负梯度方向", "链式法则", "学习率"]
    assert [row["depth"] for row in rows] == [0, 1, 2, 1]
    assert rows[0]["parentNodeId"] is None
    assert rows[2]["parentNodeId"] == rows[1]["nodeId"]
    assert len({row["nodeId"] for row in rows}) == len(rows)


def test_legacy_projection_uses_canonical_binding_and_explicit_render_profile():
    session = _session()
    try:
        course, source_ref = _source(session)
        artifact, _ = create_artifact_with_version(
            session,
            owner_public_id="usr-mindmap",
            course_id=course.id,
            artifact_type="mindmap",
            title="旧版梯度下降导图",
            content="mindmap\n  root((梯度下降))\n    rate(学习率)\n",
            content_format="markdown",
            metadata={"resource_type": "mind_map", "source_ref_ids": [source_ref.id]},
        )
        session.commit()

        projection = resource_detail(session, artifact)["mindmap"]["current"]
        binding = projection["canonical_binding"]
        assert projection["mode"] == "legacy_markdown"
        assert projection["legacy"]["render_profile"] == "legacy-compatible-v1"
        assert [row["label"] for row in projection["legacy"]["hierarchy"]] == ["梯度下降", "学习率"]
        assert binding["artifact_id"] == artifact.id
        assert binding["artifact_version_id"]
        assert binding["artifact_version_number"] == 1
        assert binding["course_id"] == course.id
        assert binding["source_ref_ids"] == [source_ref.id]
        assert projection["source_readiness"]["publishable"] is False
    finally:
        session.close()


def test_invalid_structured_projection_keeps_safe_legacy_canvas_profile():
    session = _session()
    try:
        artifact, _ = create_artifact_with_version(
            session,
            owner_public_id="usr-mindmap",
            artifact_type="mind_map",
            title="损坏导图",
            content=json.dumps({"schemaVersion": "f5.mindmap.v1", "title": "损坏"}, ensure_ascii=False),
            content_format="json",
            metadata={"resource_type": "mind_map"},
        )
        session.commit()

        projection = resource_detail(session, artifact)["mindmap"]["current"]
        assert projection["mode"] == "invalid_structured"
        assert projection["invalid"]["render_profile"] == "legacy-compatible-v1"
        assert projection["invalid"]["hierarchy"][0]["label"] == "损坏导图"
        assert projection["source_readiness"]["publishable"] is False
    finally:
        session.close()


def test_mindmap_projection_is_read_only_for_learning_evidence():
    session = _session()
    try:
        course, source_ref = _source(session)
        artifact, _ = create_artifact_with_version(
            session,
            owner_public_id="usr-mindmap",
            course_id=course.id,
            artifact_type="mindmap",
            title="只读旧导图",
            content="# 只读导图\n- 分支",
            content_format="markdown",
            metadata={"resource_type": "mind_map", "source_ref_ids": [source_ref.id]},
        )
        session.commit()
        before = session.query(DBLearningEvent).count()
        resource_detail(session, artifact)
        after = session.query(DBLearningEvent).count()
        assert after == before
    finally:
        session.close()


def test_mindmap_frontend_uses_migrated_layout_in_canonical_workspace():
    component = (ROOT / "frontend" / "src" / "components" / "CollapsibleMindmap.vue").read_text(encoding="utf-8")
    workspace = (ROOT / "frontend" / "src" / "views" / "MindmapWorkspace.vue").read_text(encoding="utf-8")

    assert "layout = d3.tree().nodeSize([104, 220])" in component
    assert "applyInitialCollapse" in component
    assert "depth >= 2" in component
    assert "scaleExtent([0.25, 3.2])" in component
    assert "labelWidth" in component
    assert "compatibility-note" in workspace
    assert "projection.value?.legacy?.hierarchy" in workspace
    assert ":root-node-id=\"graphRootNodeId\"" in workspace
    assert "foreignObject" not in component
    assert "v-html" not in component
    for forbidden in ("recordLearningEvent", "completeWorkItem", "updateProfile", "unlockExam"):
        assert forbidden not in workspace
