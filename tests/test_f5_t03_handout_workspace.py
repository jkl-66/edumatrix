from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, DBArtifactVersion, DBCourse, DBSourceDocument, DBSourceRef
from app.m1_repository import add_artifact_version, create_artifact_with_version
from app.m5_capabilities import M5CapabilityError
from app.m5_resources import (
    ResourceVersionCreateRequest,
    create_resource_version,
    export_resource_version,
    parse_handout_content,
    resource_detail,
)
from app.resource_bundles import _deterministic_demo_content


ROOT = Path(__file__).resolve().parents[1]


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _content(source_ref_id: str = "ref-handout") -> dict:
    return {
        "schemaVersion": "f5.handout.v1",
        "title": "梯度下降个性化讲义",
        "summary": "从机制、例子和反例理解梯度下降。",
        "learningGoal": "解释梯度方向与学习率的作用。",
        "estimatedMinutes": 24,
        "outline": [
            {"id": "concept", "title": "关键概念"},
            {"id": "figure", "title": "公式"},
            {"id": "example", "title": "例子"},
            {"id": "counter", "title": "反例"},
            {"id": "code", "title": "代码"},
            {"id": "quiz", "title": "小测"},
            {"id": "footnote", "title": "来源"},
        ],
        "concepts": [{
            "id": "concept", "title": "负梯度方向", "explanation": "沿负梯度方向更新参数。",
            "sourceRefIds": [source_ref_id],
        }],
        "figures": [{
            "id": "figure", "title": "参数更新公式", "kind": "formula",
            "content": "theta_{t+1}=theta_t-eta grad J(theta_t)", "caption": "学习率控制更新步长。",
            "sourceRefIds": [source_ref_id],
        }],
        "examples": [{
            "id": "example", "title": "二次函数", "body": "从初始点逐步接近极小值。",
            "sourceRefIds": [source_ref_id],
        }],
        "counterExamples": [{
            "id": "counter", "title": "学习率过大", "body": "步长过大可能越过极小值并发散。",
            "sourceRefIds": [source_ref_id],
        }],
        "codeBlocks": [{
            "id": "code", "title": "单步更新", "language": "python",
            "code": "theta -= eta * grad", "explanation": "这里只阅读代码，运行留给代码沙盒。",
        }],
        "miniQuiz": [{
            "id": "quiz", "question": "学习率过大最可能怎样？", "options": ["收敛更稳", "发生振荡或发散"],
            "correctIndex": 1, "explanation": "过大的步长可能反复越过极小值。", "required": True,
        }],
        "footnotes": [{
            "id": "footnote", "sourceRefId": source_ref_id, "label": "[1]",
            "title": "优化算法课程讲义", "location": "第 2 章 梯度下降",
        }],
        "profileAdaptation": {
            "summary": "针对图文与实操偏好，先解释公式再连接代码。",
            "difficulty": "基础到应用",
            "scaffolding": ["先读公式", "再看反例", "最后完成小测"],
        },
    }


def _source(session, *, status: str = "ready") -> tuple[DBCourse, DBSourceRef]:
    course = DBCourse(
        id=f"course-handout-{status}", version="1", title="机器学习基础",
        manifest_version=f"handout-{status}",
    )
    document = DBSourceDocument(
        course_id=course.id, title="优化算法课程讲义", filename="optimization.md",
        file_format="markdown", content_hash="a" * 64, source_sha256="b" * 64,
        processed_sha256="c" * 64, processing_status=status,
    )
    session.add_all([course, document])
    session.flush()
    source_ref = DBSourceRef(
        source_document_id=document.id, parser_version="handout-parser-v1",
        location_kind="section", location_label="第 2 章 梯度下降", content_hash="d" * 64,
    )
    session.add(source_ref)
    session.flush()
    return course, source_ref


def _handout(session, *, source_status: str = "ready"):
    course, source_ref = _source(session, status=source_status)
    content = json.dumps(_content(source_ref.id), ensure_ascii=False)
    artifact, version = create_artifact_with_version(
        session,
        owner_public_id="usr-handout",
        course_id=course.id,
        artifact_type="handout",
        title="梯度下降个性化讲义",
        content=content,
        content_format="json",
        metadata={"resource_type": "handout", "source_ref_ids": [source_ref.id]},
    )
    session.commit()
    return artifact, version, source_ref


def test_handout_schema_requires_every_learning_section_and_rejects_text_wall_json():
    parsed = parse_handout_content(json.dumps(_content(), ensure_ascii=False))
    assert parsed.schemaVersion == "f5.handout.v1"
    assert parsed.outline[-1].id == "footnote"

    with pytest.raises(M5CapabilityError) as exc_info:
        parse_handout_content(json.dumps({
            "schemaVersion": "f5.handout.v1",
            "title": "一段长文本",
            "summary": "正文" * 1000,
        }, ensure_ascii=False))
    assert exc_info.value.code == "handout_content_incomplete"


def test_structured_legacy_and_invalid_handouts_have_honest_projections():
    session = _session()
    artifact, _, source_ref = _handout(session)
    structured = resource_detail(session, artifact)["handout"]["current"]
    assert structured["mode"] == "structured"
    assert structured["source_readiness"]["publishable"] is True
    assert structured["structured"]["miniQuiz"][0]["question"]

    legacy, _ = create_artifact_with_version(
        session, owner_public_id="usr-handout", artifact_type="lesson", title="旧讲义",
        content="# 旧讲义\n\n只保留原有 Markdown。", content_format="markdown",
    )
    invalid, _ = create_artifact_with_version(
        session, owner_public_id="usr-handout", artifact_type="handout", title="待修复讲义",
        content=json.dumps({"schemaVersion": "f5.handout.v1", "title": "待修复"}, ensure_ascii=False),
        content_format="json", metadata={"resource_type": "handout", "source_ref_ids": [source_ref.id]},
    )
    session.commit()

    legacy_projection = resource_detail(session, legacy)["handout"]["current"]
    invalid_projection = resource_detail(session, invalid)["handout"]["current"]
    assert legacy_projection["mode"] == "legacy_markdown"
    assert legacy_projection["legacy"]["markdown"].startswith("# 旧讲义")
    assert legacy_projection["source_readiness"]["publishable"] is False
    assert invalid_projection["mode"] == "invalid_structured"
    assert invalid_projection["invalid"]["raw_content"].startswith("{")
    assert invalid_projection["source_readiness"]["publishable"] is False
    assert invalid_projection["warnings"] == ["当前讲义缺少必需的学习章节，请补齐后重新保存。"]


def test_failed_source_blocks_publish_ready_state():
    session = _session()
    artifact, _, _ = _handout(session, source_status="failed")
    readiness = resource_detail(session, artifact)["handout"]["current"]["source_readiness"]
    assert readiness["recorded"] is True
    assert readiness["available"] is False
    assert readiness["publishable"] is False


def test_missing_source_reference_blocks_publish_ready_state():
    session = _session()
    artifact, current, _ = _handout(session)
    content = _content("missing-source-ref")
    current.content = json.dumps(content, ensure_ascii=False)
    current.metadata_json = {
        **dict(current.metadata_json or {}),
        "source_ref_ids": ["missing-source-ref"],
    }
    session.commit()

    readiness = resource_detail(session, artifact)["handout"]["current"]["source_readiness"]
    assert readiness["recorded"] is True
    assert readiness["available"] is False
    assert readiness["publishable"] is False


def test_historical_handout_edit_appends_version_without_mutating_history():
    session = _session()
    artifact, first, _ = _handout(session)
    second_content = _content(json.loads(first.content)["footnotes"][0]["sourceRefId"])
    second_content["summary"] = "第二版摘要"
    second = add_artifact_version(
        session, artifact=artifact, content=json.dumps(second_content, ensure_ascii=False),
        content_format="json", created_by_public_id="usr-handout", metadata=first.metadata_json,
    )
    session.commit()
    first_before = first.content
    second_before = second.content

    revised = _content(json.loads(first.content)["footnotes"][0]["sourceRefId"])
    revised["summary"] = "从第一版分支出的第三版摘要"
    payload = create_resource_version(
        session,
        artifact=artifact,
        actor_public_id="usr-handout",
        request=ResourceVersionCreateRequest(
            expected_lock_version=artifact.lock_version,
            source_version_id=first.id,
            content=json.dumps(revised, ensure_ascii=False),
            content_format="json",
        ),
    )

    assert payload["handout"]["versions"][-1]["number"] == 3
    assert artifact.current_version_id == payload["handout"]["current_version_id"]
    assert first.content == first_before
    assert second.content == second_before
    assert payload["handout"]["versions"][0]["projection"]["structured"]["summary"] != revised["summary"]


def test_non_handout_historical_edit_creates_a_new_version():
    session = _session()
    artifact, first = create_artifact_with_version(
        session, owner_public_id="usr-handout", artifact_type="mind_map", title="思维导图",
        content="# 第一版",
    )
    second = add_artifact_version(
        session, artifact=artifact, content="# 第二版", created_by_public_id="usr-handout",
    )
    session.commit()

    detail = create_resource_version(
        session,
        artifact=artifact,
        actor_public_id="usr-handout",
        request=ResourceVersionCreateRequest(
            expected_lock_version=artifact.lock_version,
            source_version_id=first.id,
            content="# 从历史版另存的新版本",
            content_format="markdown",
        ),
    )

    current = session.get(DBArtifactVersion, artifact.current_version_id)
    assert current.version_number == 3
    assert current.content == "# 从历史版另存的新版本"
    assert current.metadata_json["revised_from_version_id"] == first.id
    assert session.get(DBArtifactVersion, first.id).content == "# 第一版"
    assert session.get(DBArtifactVersion, second.id).content == "# 第二版"
    assert detail["history"]["items"][0]["is_current"] is True


def test_deterministic_demo_generates_complete_structured_handout():
    for difficulty_band in ("foundation", "scaffolded", "transfer"):
        content = _deterministic_demo_content(
            resource_type="handout",
            item={"title": "梯度下降个性化讲义"},
            manifest={
                "knowledge_point_id": "kp-gradient",
                "context": {
                    "knowledge_point_title": "梯度下降",
                    "learning_goal": "解释梯度下降的更新机制",
                    "profile_adaptation": "偏好图文与实操",
                    "profile_adaptation_plan": {"difficulty_band": difficulty_band},
                    "mastery_summary": "当前掌握度约为 42%",
                    "recent_learning_summary": "近期完成一次基础练习",
                },
            },
            source_snapshots=[{
                "source_ref_id": "ref-demo", "title": "课程讲义", "location_label": "第 2 章",
            }],
        )
        parsed = parse_handout_content(content)
        outline_ids = [section.id for section in parsed.outline]
        assert parsed.title == "梯度下降个性化讲义"
        assert len(outline_ids) == len(set(outline_ids))
        assert parsed.concepts and parsed.figures and parsed.examples and parsed.counterExamples
        assert parsed.codeBlocks and len(parsed.miniQuiz) == 3 and parsed.footnotes


def test_handout_export_preserves_selected_version_content_and_hashes():
    session = _session()
    artifact, version, _ = _handout(session)
    exported = export_resource_version(session, artifact=artifact, version_number=1)
    assert exported["version"]["content"] == version.content
    assert exported["version"]["persisted_content_hash"] == hashlib.sha256(version.content.encode()).hexdigest()
    assert exported["version"]["export_content_hash"] == exported["version"]["persisted_content_hash"]


def test_handout_frontend_contract_has_dedicated_route_full_sections_and_no_mastery_write():
    view = (ROOT / "frontend/src/views/HandoutWorkspace.vue").read_text(encoding="utf-8")
    router = (ROOT / "frontend/src/router/index.js").read_text(encoding="utf-8")
    assert "name: 'HandoutResource', component: HandoutWorkspace" in router
    assert "grid-template-columns: 220px minmax(500px, 1fr) 300px" in view
    for label in (
        "适配摘要", "关键概念", "图表或公式标题", "应用示例", "边界与反例",
        "代码阅读", "学习检查", "来源脚注", "AI 学习伙伴", "阅读位置",
        "保存为新版本", "与当前版本比较", "导出 HTML", "导出版本数据",
    ):
        assert label in view
    assert "prompt: question" in view
    assert "version: selectedVersion.value?.number, question" not in view
    for forbidden in ("createLearningEvent", "mastery", "profileSnapshot", "completePath"):
        assert forbidden not in view
