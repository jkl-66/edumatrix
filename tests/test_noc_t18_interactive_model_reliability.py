from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.competition_demo_seed import seed_competition_demo
from app.database import Base, DBArtifact, DBGenerationTask, DBLearningEvent, DBProfileSnapshot, DBSourceRef, DBUser
from app.interactive_lab import (
    apply_action,
    create_instance,
    get_template,
    list_templates,
    validate_resource_template_content,
)
from app.m5_resources import parse_interactive_model_content, resource_detail
from app.m1_repository import create_artifact_with_version
from app.resource_bundles import (
    ResourceBundleError,
    _generation_manifest,
    _generation_source_snapshots,
    _interactive_template_for_knowledge_point,
    _llm_resource_content,
    _real_model_payload_async,
    _normalize_interactive_constraints,
    complete_generation_item,
    create_generation_job,
    mark_generation_item_running,
)


COURSE_ID = "demo-course-rag-trust-v1"


def _manifest(knowledge_point: str = "混合检索") -> dict:
    return {
        "course_id": COURSE_ID,
        "knowledge_point_id": "kp-test",
        "profile_snapshot_id": "profile-test",
        "context": {
            "course_title": "检索系统课程",
            "knowledge_point_title": knowledge_point,
            "learning_goal": "解释参数变化对实验指标的影响",
            "profile_adaptation": "按当前掌握度提供分步提示",
            "mastery_summary": "正在形成稳定理解",
            "recent_learning_summary": "近期完成一次检索练习",
        },
        "input_snapshot": {},
    }


def _source_snapshots() -> list[dict]:
    return [{
        "source_ref_id": "source-test-01",
        "title": "课程讲义",
        "location_label": "第 2 章 / 第 3 页",
        "location_kind": "page",
        "quote": "冻结课程来源中的实验定义和参数约束。",
        "available": True,
    }]


def _model_payload(template_id: str) -> dict:
    template = get_template(template_id)
    return {
        "summary": f"{template.title}的课程实验摘要",
        "learningGoal": "解释参数变化对实验指标的影响",
        "narrative": "基于课程来源观察参数、约束和指标之间的关系。",
        "practiceSteps": [
            {"title": f"步骤 {index}", "instruction": "按照课程来源完成本步骤。", "expectedResult": "得到可观察的实验结果。", "errorGuidance": "检查参数和来源是否正确。"}
            for index in range(1, 5)
        ],
        "templateId": template_id,
        "parameters": [item.model_dump(mode="json") for item in template.parameters],
        "constraints": [{"id": "constraint-main", "title": "参数边界", "description": "所有参数必须遵守模板范围。"}],
        "dataset": {"id": "dataset-course-01", "title": "冻结课程样本", "summary": "用于本次实验的课程样本。", "sampleCount": 100},
        "chart": {
            "kind": "line",
            "xAxisLabel": "参数取值",
            "yAxisLabel": "指标值",
            "series": [
                {"key": item.key, "label": item.label, "unit": item.unit, "higherIsBetter": item.higher_is_better}
                for item in template.metrics
            ],
        },
        "observationPrompt": "比较不同参数下的曲线和指标，说明你的判断。",
    }


def _content(knowledge_point: str = "混合检索", template_id: str | None = None) -> str:
    selected = template_id or _interactive_template_for_knowledge_point(knowledge_point).template_id
    return _llm_resource_content(
        resource_type="interactive_model",
        item={"title": "课程交互实验", "completion_rule": "提交观察结论"},
        manifest=_manifest(knowledge_point),
        source_snapshots=_source_snapshots(),
        linked_resource_ids=[],
        llm_payload=_model_payload(selected),
    )


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def test_normal_knowledge_points_select_distinct_applicable_templates():
    assert _interactive_template_for_knowledge_point("混合向量检索与重排").template_id == "rag-hybrid-tuning"
    assert _interactive_template_for_knowledge_point("分类模型召回率和阈值校准").template_id == "classifier-threshold-calibration"
    assert _interactive_template_for_knowledge_point("数据清洗与 Pandas 向量化").template_id == "data-processing-sensitivity"
    assert _interactive_template_for_knowledge_point("过拟合、欠拟合与泛化").template_id == "model-complexity-generalization"
    assert _interactive_template_for_knowledge_point("K-Means 聚类稳定性").template_id == "clustering-configuration"
    assert _interactive_template_for_knowledge_point("PCA 主成分降维").template_id == "dimensionality-reduction"
    assert _interactive_template_for_knowledge_point("梯度下降学习率").template_id == "optimization-dynamics"
    assert _interactive_template_for_knowledge_point("课程历史背景") is None
    assert len(list_templates()) >= 7


def test_each_supported_template_produces_content_that_runtime_can_run():
    for template in list_templates():
        knowledge_point = template.applicability.split("、")[0]
        content = parse_interactive_model_content(_content(knowledge_point, template.template_id))
        assert content.templateId == template.template_id
        assert validate_resource_template_content(content).template_id == template.template_id
        assert {item.key for item in content.parameters} == {item.key for item in template.parameters}
        assert {item.key for item in content.chart.series} == {item.key for item in template.metrics}


def test_model_invented_parameter_is_rejected_before_persistence():
    payload = _model_payload("rag-hybrid-tuning")
    payload["parameters"] = _model_payload("optimization-dynamics")["parameters"][:1]
    with pytest.raises(ResourceBundleError) as exc_info:
        _llm_resource_content(
            resource_type="interactive_model",
            item={"title": "错误参数实验", "completion_rule": "提交观察结论"},
            manifest=_manifest("混合检索"),
            source_snapshots=_source_snapshots(),
            linked_resource_ids=[],
            llm_payload=payload,
        )
    assert exc_info.value.code == "resource_generation.interactive_model_template_mismatch"
    assert "拒绝保存" in str(exc_info.value)


class _UnexpectedBackend:
    async def generate(self, *_args, **_kwargs):  # pragma: no cover - must never be called
        raise AssertionError("an inapplicable knowledge point must stop before the model call")


class _StaticBackend:
    def __init__(self, payload: dict):
        self.payload = payload

    async def generate(self, *_args, **_kwargs):
        return json.dumps(self.payload, ensure_ascii=False)


def test_real_model_payload_path_accepts_valid_template_contract():
    import asyncio

    payload = asyncio.run(_real_model_payload_async(
        _StaticBackend(_model_payload("rag-hybrid-tuning")),
        resource_type="interactive_model",
        item={"title": "混合检索实验"},
        manifest=_manifest("混合检索"),
        source_snapshots=_source_snapshots(),
    ))
    content = parse_interactive_model_content(_llm_resource_content(
        resource_type="interactive_model",
        item={"title": "混合检索实验", "completion_rule": "提交观察结论"},
        manifest=_manifest("混合检索"),
        source_snapshots=_source_snapshots(),
        linked_resource_ids=[],
        llm_payload=payload,
    ))
    assert content.templateId == "rag-hybrid-tuning"


def test_interactive_constraint_shape_is_completed_without_replacing_model_text():
    payload = {"constraints": ["参数必须在模板范围内", {"title": "步长", "description": "每次调整按步长变化。"}]}
    normalized = _normalize_interactive_constraints(payload)
    assert normalized["constraints"][0] == {
        "id": "constraint-1", "title": "实验约束 1", "description": "参数必须在模板范围内",
    }
    assert normalized["constraints"][1]["title"] == "步长"


def test_inapplicable_knowledge_point_returns_actionable_chinese_reason():
    with pytest.raises(ResourceBundleError) as exc_info:
        import asyncio

        asyncio.run(_real_model_payload_async(
            _UnexpectedBackend(),
            resource_type="interactive_model",
            item={"title": "历史背景实验"},
            manifest=_manifest("课程历史背景"),
            source_snapshots=_source_snapshots(),
        ))
    assert exc_info.value.code == "resource_generation.interactive_model_inapplicable"
    assert "没有合适的可交互实验模板" in str(exc_info.value)


def test_complete_generation_item_rejects_bad_content_without_creating_artifact():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.query(DBProfileSnapshot).filter_by(owner_public_id=learner.public_id).first()
        source = session.get(DBSourceRef, "demo-ref-07")
        assert profile is not None and source is not None
        job = create_generation_job(
            session,
            learner,
            course_id=COURSE_ID,
            knowledge_point_id="demo-kp-07",
            profile_snapshot_id=profile.id,
            idempotency_key="noc-t18-pre-persist-001",
            scope="single",
            items=[{"type": "interactive_model", "title": "模板校验", "source_ref_ids": [source.id]}],
        )
        mark_generation_item_running(session, learner, job["job_id"], "interactive_model")
        manifest = _generation_manifest(session, job["job_id"])
        task_row = session.get(DBGenerationTask, job["job_id"])
        assert task_row is not None
        snapshots = _generation_source_snapshots(
            session,
            task=task_row,
            manifest=manifest,
            item={"type": "interactive_model", "source_ref_ids": [source.id]},
            resource_type="interactive_model",
        )
        bad = json.loads(_content("混合检索", "rag-hybrid-tuning"))
        bad["parameters"] = _model_payload("optimization-dynamics")["parameters"][:1]
        with pytest.raises(ResourceBundleError) as exc_info:
            complete_generation_item(
                session,
                learner,
                job["job_id"],
                "interactive_model",
                content=json.dumps(bad, ensure_ascii=False),
                content_format="json",
            )
        assert exc_info.value.code == "resource_generation.interactive_model_content_invalid"
        assert session.query(DBArtifact).filter_by(creating_task_id=job["job_id"]).count() == 0
    finally:
        session.close()
        engine.dispose()


def test_invalid_historical_resource_is_projected_as_chinese_unavailable_state():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        bad = json.loads(_content("混合检索", "rag-hybrid-tuning"))
        bad["parameters"] = _model_payload("optimization-dynamics")["parameters"][:1]
        artifact, _ = create_artifact_with_version(
            session,
            owner_public_id=learner.public_id,
            artifact_type="interactive_model",
            title="历史坏模型",
            content=json.dumps(bad, ensure_ascii=False),
            content_format="json",
            course_id=COURSE_ID,
            metadata={"resource_type": "interactive_model", "source_ref_ids": ["demo-ref-07"]},
        )
        projection = resource_detail(session, artifact)["interactive_model"]["current"]
        assert projection["mode"] == "invalid_structured"
        assert projection["source_readiness"]["publishable"] is False
        assert "重新生成" in projection["warnings"][0]
        assert "resource parameters do not match" not in projection["warnings"][0]
    finally:
        session.close()
        engine.dispose()


def test_runtime_run_does_not_create_learning_event_for_valid_model():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        artifact, version = create_artifact_with_version(
            session,
            owner_public_id=learner.public_id,
            artifact_type="interactive_model",
            title="可运行模型",
            content=_content("混合检索", "rag-hybrid-tuning"),
            content_format="json",
            course_id=COURSE_ID,
            metadata={"resource_type": "interactive_model", "source_ref_ids": ["demo-ref-07"], "knowledge_point_id": "demo-kp-07"},
        )
        state, _, _ = create_instance(
            session,
            owner=learner.public_id,
            template_id=None,
            title=None,
            parameters=None,
            linked_media_resource_id=None,
            source_resource_id=artifact.id,
            idempotency_key="noc-t18-run-no-evidence-001",
        )
        baseline = session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count()
        configured, _ = apply_action(
            session,
            instance_id=state.instance_id,
            owner=learner.public_id,
            action="run",
            parameters=None,
            observation=None,
            expected_version=1,
            idempotency_key="noc-t18-run-no-evidence-action-001",
        )
        assert configured["status"] == "evaluated"
        assert session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count() == baseline
    finally:
        session.close()
        engine.dispose()
