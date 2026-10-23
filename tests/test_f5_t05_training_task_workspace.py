from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, DBCourse, DBSourceDocument, DBSourceRef
from app.m1_repository import create_artifact_with_version
from app.m5_capabilities import M5CapabilityError
from app.m5_resources import resource_detail
from app.resource_bundles import _deterministic_demo_content
from app.training_tasks import parse_training_task_content


ROOT = Path(__file__).resolve().parents[1]


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _content(source_ref_id: str = "ref-training", sandbox_id: str | None = "sandbox", model_id: str | None = "model") -> dict:
    return {
        "schemaVersion": "f5.training-task.v1",
        "title": "梯度下降实训任务书",
        "objective": "完成数据检查、模型训练、评估和排错。",
        "difficulty": "基础到应用",
        "estimatedMinutes": 55,
        "prerequisites": ["理解梯度和学习率"],
        "environment": ["Python 3.11", "EduMatrix 代码沙盒"],
        "data": ["预置二分类样本"],
        "steps": [
            {
                "id": "step-data", "title": "检查数据", "instruction": "确认字段与划分。",
                "expectedResult": "得到数据检查清单。", "errorGuidance": "数据缺失时停止训练。",
                "sourceRefIds": [source_ref_id],
            },
            {
                "id": "step-run", "title": "训练与评估", "instruction": "在沙盒运行基线。",
                "expectedResult": "得到真实指标或错误。", "errorGuidance": "检查数据形状和参数。",
                "sourceRefIds": [],
            },
        ],
        "checkpoints": [
            {
                "id": "check-data", "afterStepId": "step-data", "title": "数据可用",
                "verification": "核对字段与划分。", "passCondition": "不存在未解释字段。",
            },
            {
                "id": "check-run", "afterStepId": "step-run", "title": "结果可重现",
                "verification": "相同输入重跑。", "passCondition": "输出或错误一致。",
            },
        ],
        "deliverables": [
            {"id": "deliverable-code", "title": "代码", "description": "可复现实验。", "format": "Python"},
            {"id": "deliverable-report", "title": "报告", "description": "指标和排错过程。", "format": "Markdown"},
        ],
        "rubric": [
            {"id": "rubric-data", "criterion": "数据处理", "evidence": "检查清单。", "points": 25},
            {"id": "rubric-model", "criterion": "模型选择", "evidence": "选择理由。", "points": 25},
            {"id": "rubric-run", "criterion": "真实运行", "evidence": "输出或错误。", "points": 30},
            {"id": "rubric-analysis", "criterion": "分析改进", "evidence": "结论与建议。", "points": 20},
        ],
        "sourceRefs": [source_ref_id],
        "linkedSandboxId": sandbox_id,
        "linkedModelId": model_id,
    }


def _source(session):
    course = DBCourse(id="course-training", version="1", title="机器学习工程", manifest_version="training-v1")
    document = DBSourceDocument(
        course_id=course.id, title="优化算法课程讲义", filename="optimization.md",
        file_format="markdown", content_hash="a" * 64, source_sha256="b" * 64,
        processed_sha256="c" * 64, processing_status="ready",
    )
    session.add_all([course, document])
    session.flush()
    source_ref = DBSourceRef(
        source_document_id=document.id, parser_version="training-parser-v1",
        location_kind="section", location_label="第 2 章 梯度下降", content_hash="d" * 64,
    )
    session.add(source_ref)
    session.flush()
    return course, source_ref


def _training_task(session):
    course, source_ref = _source(session)
    sandbox, _ = create_artifact_with_version(
        session, owner_public_id="usr-training", course_id=course.id, artifact_type="code_sandbox",
        title="梯度下降代码沙盒", content="# sandbox", metadata={"resource_type": "code_sandbox"},
    )
    model, _ = create_artifact_with_version(
        session, owner_public_id="usr-training", course_id=course.id, artifact_type="interactive_model",
        title="梯度下降交互模型", content="# model", metadata={"resource_type": "interactive_model"},
    )
    content = _content(source_ref.id, sandbox.id, model.id)
    artifact, version = create_artifact_with_version(
        session, owner_public_id="usr-training", course_id=course.id, artifact_type="training_task",
        title=content["title"], content=json.dumps(content, ensure_ascii=False), content_format="json",
        metadata={"resource_type": "training_task", "source_ref_ids": [source_ref.id]},
    )
    session.commit()
    return artifact, version, source_ref, sandbox, model


def test_training_task_schema_requires_complete_execution_contract():
    parsed = parse_training_task_content(json.dumps(_content(), ensure_ascii=False))
    assert parsed.schemaVersion == "f5.training-task.v1"
    assert sum(item.points for item in parsed.rubric) == 100

    wrong_total = _content()
    wrong_total["rubric"][0]["points"] = 20
    with pytest.raises(M5CapabilityError) as exc_info:
        parse_training_task_content(json.dumps(wrong_total, ensure_ascii=False))
    assert exc_info.value.code == "training_task_content_incomplete"

    bad_checkpoint = _content()
    bad_checkpoint["checkpoints"][0]["afterStepId"] = "missing"
    with pytest.raises(M5CapabilityError):
        parse_training_task_content(json.dumps(bad_checkpoint, ensure_ascii=False))


def test_structured_training_task_projects_sources_and_distinct_linked_tools():
    session = _session()
    artifact, _, source_ref, sandbox, model = _training_task(session)
    projection = resource_detail(session, artifact)["training_task"]["current"]

    assert projection["mode"] == "structured"
    assert projection["source_readiness"]["publishable"] is True
    assert projection["structured"]["sourceRefs"] == [source_ref.id]
    linked = {item["type"]: item for item in projection["linked_resources"]}
    assert linked["code_sandbox"]["id"] == sandbox.id
    assert linked["code_sandbox"]["route"] == f"/workspace/code/{sandbox.id}"
    assert linked["interactive_model"]["id"] == model.id
    assert linked["interactive_model"]["route"] == f"/workspace/resources/models/{model.id}"


def test_cross_owner_or_wrong_type_link_is_not_exposed_as_available():
    session = _session()
    artifact, version, _, _, _ = _training_task(session)
    foreign, _ = create_artifact_with_version(
        session, owner_public_id="usr-other", course_id=artifact.course_id, artifact_type="code_sandbox",
        title="他人沙盒", content="# private", metadata={"resource_type": "code_sandbox"},
    )
    payload = json.loads(version.content)
    payload["linkedSandboxId"] = foreign.id
    payload["linkedModelId"] = foreign.id
    version.content = json.dumps(payload, ensure_ascii=False)
    session.commit()

    linked = resource_detail(session, artifact)["training_task"]["current"]["linked_resources"]
    assert linked == [
        {"id": foreign.id, "type": "code_sandbox", "available": False},
        {"id": foreign.id, "type": "interactive_model", "available": False},
    ]


def test_legacy_lab_guide_and_invalid_json_are_preserved_honestly():
    session = _session()
    course, source_ref = _source(session)
    legacy_payload = {
        "artifact_type": "lab_guide", "schema_version": "m2.lab_guide.v1",
        "title": "旧实验说明", "objective": "验证模型结果", "environment": ["Python"],
        "safety_boundary": "只使用课程数据",
        "steps": [{
            "step_number": 1, "title": "运行", "instruction": "执行基线", "command_or_action": "python train.py",
            "expected_result": "输出指标", "rollback": "恢复输入", "risk_level": "low", "source_ref_ids": [source_ref.id],
        }],
        "acceptance_criteria": ["结果可重现"],
        "failure_branches": [{"symptom": "无输出", "likely_cause": "输入缺失", "recovery_steps": ["检查输入"]}],
    }
    legacy, _ = create_artifact_with_version(
        session, owner_public_id="usr-training", course_id=course.id, artifact_type="lab_guide",
        title="旧实验说明", content=json.dumps(legacy_payload, ensure_ascii=False), content_format="json",
        metadata={"resource_type": "lab_guide", "source_ref_ids": [source_ref.id]},
    )
    invalid, _ = create_artifact_with_version(
        session, owner_public_id="usr-training", course_id=course.id, artifact_type="training_task",
        title="损坏任务书", content=json.dumps({"schemaVersion": "f5.training-task.v1", "title": "损坏"}),
        content_format="json", metadata={"resource_type": "training_task", "source_ref_ids": [source_ref.id]},
    )
    session.commit()

    legacy_projection = resource_detail(session, legacy)["training_task"]["current"]
    invalid_projection = resource_detail(session, invalid)["training_task"]["current"]
    assert legacy_projection["mode"] == "legacy_lab_guide"
    assert legacy_projection["legacy"]["steps"][0]["expectedResult"] == "输出指标"
    assert invalid_projection["mode"] == "invalid_structured"
    assert invalid_projection["warnings"] == ["当前实训任务书缺少环境、检查点、提交物或评分标准。"]


def test_deterministic_demo_generates_complete_ai_ml_training_task():
    content = _deterministic_demo_content(
        resource_type="training_task",
        item={"title": "梯度下降实训任务书"},
        manifest={
            "knowledge_point_id": "kp-gradient",
            "context": {"knowledge_point_title": "梯度下降", "learning_goal": "解释并应用梯度下降"},
        },
        source_snapshots=[{"source_ref_id": "ref-demo", "title": "课程讲义", "location_label": "第 2 章"}],
        linked_resource_ids=["sandbox-demo", "model-demo"],
    )
    parsed = parse_training_task_content(content)
    assert parsed.linkedSandboxId == "sandbox-demo"
    assert parsed.linkedModelId == "model-demo"
    assert [item.title for item in parsed.steps] == ["检查数据与任务边界", "选择模型与评价指标", "训练并保存真实结果", "评估、诊断与改进"]

    adapted = _deterministic_demo_content(
        resource_type="training_task",
        item={"title": "梯度下降实训任务书"},
        manifest={
            "knowledge_point_id": "kp-gradient",
            "context": {
                "knowledge_point_title": "梯度下降",
                "profile_adaptation": "需要更多分步支架",
                "mastery_summary": "当前为入门难度",
                "recent_learning_summary": "最近在数据划分上出现错误",
            },
        },
        source_snapshots=[{"source_ref_id": "ref-demo", "title": "课程讲义", "location_label": "第 2 章"}],
        linked_resource_ids=["sandbox-demo", "model-demo"],
    )
    assert adapted != content
    adapted_content = parse_training_task_content(adapted)
    assert adapted_content.difficulty == "当前为入门难度"
    assert "需要更多分步支架" in adapted_content.prerequisites
    assert "最近在数据划分上出现错误" in adapted_content.steps[-1].instruction


def test_frontend_contract_uses_dedicated_workspace_and_never_writes_learning_evidence():
    router = (ROOT / "frontend/src/router/index.js").read_text(encoding="utf-8")
    view = (ROOT / "frontend/src/views/TrainingTaskWorkspace.vue").read_text(encoding="utf-8")
    golden = (ROOT / "frontend/src/views/GoldenLoop.vue").read_text(encoding="utf-8")

    assert "const TrainingTaskWorkspace" in router
    assert "name: 'TrainingTaskResource', component: TrainingTaskWorkspace" in router
    for label in ("前置知识", "运行环境", "数据与输入", "任务步骤", "检查点", "提交物", "评分标准", "进入代码沙盒", "打开可交互模型", "步骤进行中", "提交待验证", "已完成"):
        assert label in view
    assert "实操指南" not in golden
    for forbidden in ("createM5LearningEvent", "recordLearningEvent", "completeWorkItem", "unlockExam", "updateProfile"):
        assert forbidden not in view
