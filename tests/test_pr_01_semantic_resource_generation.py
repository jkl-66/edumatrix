from __future__ import annotations

import json
import pytest

from app.competition_demo_seed import seed_competition_demo
from app.database import (
    DBArtifact,
    DBArtifactVersion,
    DBLearningEvent,
    DBProfileSnapshot,
    DBSourceRef,
    DBUser,
)
from app.m5_resources import parse_code_sandbox_content, parse_interactive_model_content
from app.resource_bundles import (
    _deterministic_demo_content,
    _source_semantic_anchor,
    _version_generation_metadata,
    create_generation_job,
    execute_generation_job_demo,
    generation_job_payload,
    execute_generation_job,
)
from tests.test_f6_t03_code_sandbox_resource import _session


@pytest.fixture(autouse=True)
def _fake_web_video_search(monkeypatch):
    async def fake_search(query, max_results=5):
        return [{
            "title": "课程视频候选",
            "url": "https://www.bilibili.com/video/BV1test123",
            "source": "B站视频",
            "description": "测试用真实网页来源",
        }]

    import web_search_api
    monkeypatch.setattr(web_search_api, "search_videos", fake_search)


def _manifest(
    *, knowledge_point: str, profile: str, mastery: str,
    source_hash: str = "source-hash", profile_plan: dict | None = None,
) -> dict:
    return {
        "knowledge_point_id": "kp-pr01",
        "profile_snapshot_id": "profile-pr01",
        "context": {
            "course_title": "PR-01 课程",
            "knowledge_point_title": knowledge_point,
            "learning_goal": f"掌握 {knowledge_point} 并能完成实践验证",
            "profile_adaptation": profile,
            "mastery_summary": mastery,
            "recent_learning_summary": "最近完成一次来源核对。",
            "profile_adaptation_plan": profile_plan or {},
        },
        "input_snapshot": {
            "profile_snapshot_hash": f"profile-{profile}",
            "recent_event_cursor": "event-cursor-pr01",
            "input_snapshot_hash": f"input-{profile}",
            "source_snapshot_hashes": {"training_task": source_hash},
        },
    }


def _source(*, source_ref_id: str, title: str, quote: str) -> dict:
    return {
        "source_ref_id": source_ref_id,
        "title": title,
        "location_label": "第 2 章 / 实验段",
        "location_kind": "section",
        "quote": quote,
        "available": True,
        "reason_code": "",
        "reason": "",
    }


def test_public_source_anchor_keeps_teaching_content_without_repository_metadata():
    anchor = _source_semantic_anchor([_source(
        source_ref_id="src-public-anchor",
        title="优化算法课程章节",
        quote=(
            "上游仓库：d2l-zh（固定版本 e6b18dbde18b491201110fde7323312a848c26e8）\n"
            "文件路径：chapter_optimization/sgd.md\n"
            "学习率过大会使损失振荡，正则化用于约束模型复杂度。"
        ),
    )])

    assert "学习率过大会使损失振荡" in anchor
    for internal in ("上游仓库", "固定版本", "e6b18dbde18b491201110fde7323312a848c26e8", "文件路径"):
        assert internal not in anchor


def test_same_knowledge_point_changes_content_for_profile_and_source_inputs():
    classification = [_source(
        source_ref_id="src-classifier",
        title="分类课程章节",
        quote="分类阈值、混淆矩阵、precision 和 recall 的取舍。",
    )]
    retrieval = [_source(
        source_ref_id="src-retrieval",
        title="检索课程章节",
        quote="向量 embedding、top-k 召回和重排阈值决定检索质量。",
    )]
    base = _manifest(knowledge_point="模型评估", profile="需要分步脚手架", mastery="掌握度仍在发展")
    advanced = _manifest(knowledge_point="模型评估", profile="可以直接比较边界条件", mastery="已掌握基础")

    handout_base = _deterministic_demo_content(
        resource_type="handout", item={"title": "讲义", "id": "handout", "label": "来源"},
        manifest=base, source_snapshots=classification,
    )
    handout_profile = _deterministic_demo_content(
        resource_type="handout", item={"title": "讲义", "id": "handout", "label": "来源"},
        manifest=advanced, source_snapshots=classification,
    )
    handout_source = _deterministic_demo_content(
        resource_type="handout", item={"title": "讲义", "id": "handout", "label": "来源"},
        manifest=base, source_snapshots=retrieval,
    )

    assert handout_base != handout_profile
    assert handout_base != handout_source
    assert "需要分步脚手架" in handout_base
    assert "可以直接比较边界条件" in handout_profile
    assert "混合检索与证据质量评估" in handout_source
    assert "deterministic_fallback" not in json.loads(handout_base)


def test_unrelated_profile_focus_cannot_replace_the_current_resource_topic():
    manifest = _manifest(
        knowledge_point="优化算法、正则化与训练稳定性",
        profile="需要更多迁移练习",
        mastery="掌握度仍在发展",
        profile_plan={
            "difficulty_band": "transfer",
            "content_focus": "召回率、精确率、向量检索和关键词检索的边界",
            "example_context": "混合检索重排项目",
        },
    )
    sources = [_source(
        source_ref_id="src-optimization",
        title="优化课程章节",
        quote="学习率、正则化强度与早停共同影响训练稳定性和泛化能力。",
    )]

    handout = _deterministic_demo_content(
        resource_type="handout", item={"title": "优化讲义", "id": "handout", "label": "来源"},
        manifest=manifest, source_snapshots=sources,
    )
    mind_map = _deterministic_demo_content(
        resource_type="mind_map", item={"title": "优化导图", "id": "mindmap", "label": "来源"},
        manifest=manifest, source_snapshots=sources,
    )

    for content in (handout, mind_map):
        assert "优化算法、正则化与训练稳定性" in content
        assert "混合检索重排项目" not in content
        assert "向量检索和关键词检索" not in content


def test_ai_ml_workspaces_share_semantics_but_keep_distinct_responsibilities():
    source = [_source(
        source_ref_id="src-retrieval",
        title="检索课程章节",
        quote="向量 embedding、top-k 召回和重排阈值决定检索质量。",
    )]
    manifest = _manifest(knowledge_point="混合检索", profile="先完成基线再调参", mastery="需要巩固")
    item = {"title": "AI/ML 实训", "id": "training", "label": "来源", "completion_rule": "完成真实运行并提交观察。"}
    training = json.loads(_deterministic_demo_content(
        resource_type="training_task", item=item, manifest=manifest, source_snapshots=source,
        linked_resource_ids=["sandbox-1", "model-1"],
    ))
    sandbox = json.loads(_deterministic_demo_content(
        resource_type="code_sandbox", item=item, manifest=manifest, source_snapshots=source,
    ))
    model_content = _deterministic_demo_content(
        resource_type="interactive_model", item=item, manifest=manifest, source_snapshots=source,
    )
    model = json.loads(model_content)

    assert [step["id"] for step in training["steps"]] == ["step-data", "step-model", "step-run", "step-evaluate"]
    assert all(step["sourceRefIds"] == ["src-retrieval"] for step in training["steps"])
    assert training["linkedSandboxId"] == "sandbox-1"
    assert training["linkedModelId"] == "model-1"
    assert training["semanticContext"]["practical_focus"] == "混合检索与证据质量评估"
    assert sandbox["semanticContext"]["source_ref_ids"] == ["src-retrieval"]
    assert model["semanticContext"]["source_ref_ids"] == ["src-retrieval"]
    assert sandbox["entryFile"] == "main.py"
    assert model["parameters"]
    assert training["semanticContext"]["semantic_input_fingerprint"] == sandbox["semanticContext"]["semantic_input_fingerprint"] == model["semanticContext"]["semantic_input_fingerprint"]
    assert parse_code_sandbox_content(json.dumps(sandbox)).schemaVersion == "f6.code-sandbox.v1"
    assert parse_interactive_model_content(model_content).schemaVersion == "f6.interactive-model.v1"


def test_generation_versions_share_fingerprints_and_do_not_write_learning_events():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        source = session.get(DBSourceRef, "demo-ref-07")
        assert profile is not None and source is not None
        before = session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count()
        job = create_generation_job(
            session, learner, course_id="demo-course-rag-trust-v1", knowledge_point_id="demo-kp-07",
            profile_snapshot_id=profile.id, idempotency_key="pr01-single-metadata-001", scope="single",
            items=[{"type": "code_sandbox", "title": "语义沙盒", "source_ref_ids": [source.id], "completion_rule": "完成运行。"}],
            learning_goal="验证来源驱动的检索实践",
        )
        result = execute_generation_job_demo(session, learner, job["job_id"])
        after = session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count()
        assert before == after
        item = result["items"][0]
        artifact = session.get(DBArtifact, item["resource"]["resource_id"])
        version = session.get(DBArtifactVersion, artifact.current_version_id)
        assert version is not None
        metadata = version.metadata_json
        assert metadata["generation_mode"] == "deterministic_fallback"
        assert metadata["input_snapshot_hash"]
        assert metadata["source_snapshot_hash"]
        assert metadata["profile_snapshot_hash"]
        assert metadata["recent_event_cursor"]
        assert metadata["semantic_input_fingerprint"]
        assert metadata["content_semantic_fingerprint"]
        assert item["resource"]["generation"]["mode"] == "deterministic_fallback"
        assert item["resource"]["generation"]["input_snapshot_hash"] == metadata["input_snapshot_hash"]
        assert parse_code_sandbox_content(version.content).schemaVersion == "f6.code-sandbox.v1"
    finally:
        session.close()
        engine.dispose()


def test_nine_resource_versions_share_one_frozen_input_snapshot():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        source = session.get(DBSourceRef, "demo-ref-07")
        assert profile is not None and source is not None
        resource_types = ["handout", "mind_map", "quiz", "training_task", "code_sandbox", "video", "deck", "interactive_model", "feynman"]
        job = create_generation_job(
            session, learner, course_id="demo-course-rag-trust-v1", knowledge_point_id="demo-kp-07",
            profile_snapshot_id=profile.id, idempotency_key="pr01-bundle-fingerprint-001", scope="bundle",
            items=[{"type": resource_type, "title": resource_type, "source_ref_ids": [source.id]} for resource_type in resource_types],
            learning_goal="验证九类资源共享同一课程语义",
        )
        result = execute_generation_job_demo(session, learner, job["job_id"])
        assert result["status"] == "succeeded"
        versions = []
        for item in result["items"]:
            assert item["state"] == "succeeded"
            artifact = session.get(DBArtifact, item["resource"]["resource_id"])
            versions.append(session.get(DBArtifactVersion, artifact.current_version_id))
        keys = ["input_snapshot_hash", "source_snapshot_hash", "profile_snapshot_hash", "recent_event_cursor", "semantic_input_fingerprint"]
        for key in keys:
            assert len({version.metadata_json[key] for version in versions}) == 1, key
        assert {version.metadata_json["generation_mode"] for version in versions} == {"deterministic_fallback"}
        assert all(version.metadata_json["source_ref_ids"] == [source.id] for version in versions)
    finally:
        session.close()
        engine.dispose()


class _FakeLiveBackend:
    model = "deepseek-v4-flash"
    provider = "openai"

    async def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        assert "只输出一个 JSON 对象" in system_prompt
        return json.dumps({
            "summary": "模型生成的课程摘要",
            "learningGoal": "模型生成的学习目标",
            "narrative": "模型依据冻结来源生成的正文，包含条件、机制和验证边界。",
            "practiceSteps": [
                {"title": "数据", "instruction": "模型生成的数据检查步骤", "expectedResult": "字段清单", "errorGuidance": "记录缺失"},
                {"title": "模型", "instruction": "模型生成的模型选择步骤", "expectedResult": "基线方案", "errorGuidance": "回查来源"},
                {"title": "训练", "instruction": "模型生成的训练步骤", "expectedResult": "可复现输出", "errorGuidance": "保留错误"},
                {"title": "评估", "instruction": "模型生成的评估步骤", "expectedResult": "证据结论", "errorGuidance": "检查指标"},
            ],
            "starterCode": "print('model-generated')\n",
            "requiredChecks": [
                {"id": "stdout", "label": "输出", "kind": "stdout_contains", "expectedText": "model-generated"},
            ],
            "environment": ["Python 3"],
            "data": ["冻结课程示例数据"],
            "parameters": [{"key": "learning_rate", "label": "学习率", "kind": "float", "minimum": 0.0, "maximum": 1.0, "step": 0.1, "default": 0.1, "description": "控制每次参数更新幅度。"}],
            "constraints": [{"id": "range", "title": "范围约束", "description": "学习率必须大于 0 且不超过 1。"}],
            "dataset": {"id": "course-demo-dataset", "title": "课程示例数据", "summary": "用于观察参数变化的课程示例数据。", "sampleCount": 1},
            "chart": {"kind": "line", "xAxisLabel": "训练步", "yAxisLabel": "损失", "series": [{"key": "loss", "label": "损失", "unit": "", "higherIsBetter": False}]},
            "observationPrompt": "模型生成的参数观察提示",
            "quizQuestions": [
                {"prompt": "模型题一", "options": ["A1", "B1", "C1", "D1"], "answer": "A", "explanation": "题一解析", "bloom": "remember", "difficulty": 0.3},
                {"prompt": "模型题二", "options": ["A2", "B2", "C2", "D2"], "answer": "B", "explanation": "题二解析", "bloom": "understand", "difficulty": 0.5},
                {"prompt": "模型题三", "options": ["A3", "B3", "C3", "D3"], "answer": "C", "explanation": "题三解析", "bloom": "apply", "difficulty": 0.7},
            ],
            "slides": [
                {"layout": "title", "title": "课程主题", "subtitle": "模型生成"},
                {"layout": "content", "title": "机制", "body": "依据冻结来源解释机制。", "speakerNotes": "回查课程来源。"},
            ],
        }, ensure_ascii=False)


def test_live_generation_uses_real_model_and_preserves_resource_protocol(monkeypatch):
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        source = session.get(DBSourceRef, "demo-ref-07")
        assert profile is not None and source is not None
        monkeypatch.setattr("app.resource_bundles._real_model_backend", lambda: _FakeLiveBackend())
        job = create_generation_job(
            session, learner, course_id="demo-course-rag-trust-v1", knowledge_point_id="demo-kp-07",
            profile_snapshot_id=profile.id, idempotency_key="pr01-live-model-001", scope="single",
            items=[{"type": "code_sandbox", "title": "模型沙盒", "source_ref_ids": [source.id], "completion_rule": "完成运行。"}],
            learning_goal="验证真实模型资源生成",
        )
        result = execute_generation_job(session, learner, job["job_id"])
        assert result["status"] == "succeeded"
        item = result["items"][0]
        version = session.get(DBArtifactVersion, session.get(DBArtifact, item["resource"]["resource_id"]).current_version_id)
        assert version.metadata_json["generation_mode"] == "llm"
        assert version.metadata_json["model"] == "deepseek-v4-flash"
        assert version.metadata_json["reasoning_effort"] == "max"
        assert "model-generated" in version.content
        assert "deterministic_fallback" not in version.content
    finally:
        session.close()
        engine.dispose()


def test_live_generation_failure_is_explicit_and_creates_no_success_version(monkeypatch):
    class _FailingBackend(_FakeLiveBackend):
        async def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
            raise RuntimeError("provider unavailable")

    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        source = session.get(DBSourceRef, "demo-ref-07")
        assert profile is not None and source is not None
        monkeypatch.setattr("app.resource_bundles._real_model_backend", lambda: _FailingBackend())
        job = create_generation_job(
            session, learner, course_id="demo-course-rag-trust-v1", knowledge_point_id="demo-kp-07",
            profile_snapshot_id=profile.id, idempotency_key="pr01-live-failure-001", scope="single",
            items=[{"type": "handout", "title": "失败讲义", "source_ref_ids": [source.id]}],
            learning_goal="验证失败状态",
        )
        result = execute_generation_job(session, learner, job["job_id"])
        assert result["status"] == "failed"
        assert result["items"][0]["state"] == "failed"
        assert result["items"][0]["resource"] is None
    finally:
        session.close()
        engine.dispose()


def test_live_bundle_keeps_one_model_loop_and_completes_all_nine_resources(monkeypatch):
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        source = session.get(DBSourceRef, "demo-ref-07")
        assert profile is not None and source is not None
        monkeypatch.setattr("app.resource_bundles._real_model_backend", lambda: _FakeLiveBackend())
        resource_types = ["handout", "mind_map", "quiz", "training_task", "code_sandbox", "video", "deck", "interactive_model", "feynman"]
        job = create_generation_job(
            session, learner, course_id="demo-course-rag-trust-v1", knowledge_point_id="demo-kp-07",
            profile_snapshot_id=profile.id, idempotency_key="pr01-live-bundle-001", scope="bundle",
            items=[{"type": resource_type, "title": resource_type, "source_ref_ids": [source.id]} for resource_type in resource_types],
            learning_goal="验证整包真实模型生成",
        )
        result = execute_generation_job(session, learner, job["job_id"])
        assert result["status"] == "succeeded"
        assert all(item["state"] == "succeeded" for item in result["items"])
        assert all(item["resource"]["generation"]["mode"] == "llm" for item in result["items"])
    finally:
        session.close()
        engine.dispose()
