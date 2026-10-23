from __future__ import annotations

import asyncio
import json

import pytest

import app.resource_bundles as resource_bundles
from app.competition_demo_seed import seed_competition_demo
from app.database import (
    DBArtifact,
    DBArtifactVersion,
    DBAssessmentQuestionVersion,
    DBLearningEvent,
    DBProfileSnapshot,
    DBSourceRef,
    DBTaskEvent,
    DBUser,
)
from app.resource_bundles import create_generation_job, execute_generation_job, retry_generation_item
from tests.test_f6_t03_code_sandbox_resource import _session


RESOURCE_TYPES = [
    "handout", "mind_map", "quiz", "training_task", "code_sandbox",
    "video", "deck", "interactive_model", "feynman",
]


@pytest.fixture(autouse=True)
def _fake_web_video_search(monkeypatch):
    async def fake_search(query, max_results=5):
        return [{
            "title": "课程视频候选",
            "url": "https://www.bilibili.com/video/BV1supervisor",
            "source": "B站视频",
            "description": "测试用真实网页来源",
        }]

    import web_search_api
    monkeypatch.setattr(web_search_api, "search_videos", fake_search)


class _SupervisorBackend:
    model = "deepseek-v4-flash"
    provider = "openai"

    def __init__(self, *, review_approved: bool = True, fail_review: bool = False):
        self.review_approved = review_approved
        self.fail_review = fail_review
        self.roles: list[str] = []
        self.active = 0
        self.max_active = 0

    async def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        self.roles.append(role)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0)
            if role == "resource_reviewer":
                if self.fail_review:
                    raise RuntimeError("reviewer unavailable")
                return json.dumps({
                    "approved": self.review_approved,
                    "summary": "审核通过" if self.review_approved else "讲义需要补充课程边界",
                    "findings": [] if self.review_approved else [{"type": "handout", "reason": "缺少边界"}],
                    "rejectedTypes": [] if self.review_approved else ["handout"],
                }, ensure_ascii=False)
            if role == "resource_planner":
                return json.dumps({
                    "summary": "共享计划：所有资源围绕冻结课程来源生成",
                    "plan": "先提炼课程核心概念，再分别生成解释、练习、实验与复述，并统一校验来源。",
                    "resourceBriefs": [{"type": item, "goal": "依据来源生成", "dependencies": []} for item in RESOURCE_TYPES],
                }, ensure_ascii=False)
            return json.dumps({
                "summary": "候选资源摘要",
                "learningGoal": "完成课程目标",
                "narrative": "依据冻结课程来源生成的候选内容，包含条件、机制和验证边界。",
                "practiceSteps": [
                    {"title": "数据", "instruction": "检查数据", "expectedResult": "字段清单", "errorGuidance": "回查来源"},
                    {"title": "模型", "instruction": "选择基线", "expectedResult": "基线方案", "errorGuidance": "记录依据"},
                    {"title": "训练", "instruction": "运行训练", "expectedResult": "可复现输出", "errorGuidance": "保留错误"},
                 {"title": "评估", "instruction": "核对指标", "expectedResult": "证据结论", "errorGuidance": "检查边界"},
                ],
                "starterCode": "print('supervisor-generated')\n",
                "requiredChecks": [
                    {"id": "stdout", "label": "输出", "kind": "stdout_contains", "expectedText": "supervisor-generated"},
                ],
                "environment": ["Python 3"],
                "data": ["冻结课程示例数据"],
                "parameters": [{"key": "learning_rate", "label": "学习率", "kind": "float", "minimum": 0.0, "maximum": 1.0, "step": 0.1, "default": 0.1, "description": "控制每次参数更新幅度。"}],
                "constraints": [{"id": "range", "title": "范围约束", "description": "学习率必须大于 0 且不超过 1。"}],
                "dataset": {"id": "supervisor-dataset", "title": "课程示例数据", "summary": "用于审核资源的课程示例数据。", "sampleCount": 1},
                "chart": {"kind": "line", "xAxisLabel": "训练步", "yAxisLabel": "损失", "series": [{"key": "loss", "label": "损失", "unit": "", "higherIsBetter": False}]},
                "observationPrompt": "观察参数变化",
                "quizQuestions": [
                    {"prompt": "题一", "options": ["选项一", "选项二", "选项三", "选项四"], "answer": "A", "explanation": "解析一", "bloom": "remember", "difficulty": 0.3},
                    {"prompt": "题二", "options": ["选项甲", "选项乙", "选项丙", "选项丁"], "answer": "B", "explanation": "解析二", "bloom": "understand", "difficulty": 0.5},
                     {"prompt": "题三", "options": ["选项甲一", "选项乙二", "选项丙三", "选项丁四"], "answer": "C", "explanation": "解析三", "bloom": "apply", "difficulty": 0.7},
                ],
                "slides": [
                    {"layout": "title", "title": "课程主题", "subtitle": "Supervisor"},
                    {"layout": "content", "title": "机制", "body": "依据冻结来源解释机制。", "speakerNotes": "回查课程来源。"},
                ],
            }, ensure_ascii=False)
        finally:
            self.active -= 1


def _job(session, learner, profile, source, key: str, **kwargs):
    return create_generation_job(
        session,
        learner,
        course_id="demo-course-rag-trust-v1",
        knowledge_point_id="demo-kp-07",
        profile_snapshot_id=profile.id,
        idempotency_key=key,
        scope="bundle",
        items=[{"type": item, "title": item, "source_ref_ids": [source.id]} for item in RESOURCE_TYPES],
        learning_goal="验证 Supervisor 资源任务图",
        conversation_id="conv-b09",
        message_id="msg-b09",
        resource_intent="custom_bundle",
        user_instruction="请按当前课程资料生成并审核资源包",
        context_snapshot_id="ctx-b09",
        selected_resource_types=RESOURCE_TYPES,
        **kwargs,
    )


def _single_quiz_job(session, learner, profile, source, key: str):
    return create_generation_job(
        session,
        learner,
        course_id="demo-course-rag-trust-v1",
        knowledge_point_id="demo-kp-07",
        profile_snapshot_id=profile.id,
        idempotency_key=key,
        scope="single",
        items=[{"type": "quiz", "title": "quiz", "source_ref_ids": [source.id]}],
        learning_goal="验证 quiz 难度元数据适配",
        conversation_id="conv-b30",
        message_id=f"msg-{key}",
        resource_intent="custom_resource",
        user_instruction="请按当前课程资料生成测验题",
        context_snapshot_id="ctx-b30",
        selected_resource_types=["quiz"],
    )


@pytest.mark.parametrize(
    ("difficulties", "expected"),
    [
        (("简单", "中等", "困难"), (0.3, 0.5, 0.7)),
        (("基础", "标准", "进阶"), (0.3, 0.5, 0.7)),
        ((0.25, "0.5", 0.75), (0.25, 0.5, 0.75)),
    ],
)
def test_live_quiz_generation_normalizes_model_difficulty_values(monkeypatch, difficulties, expected):
    backend = _SupervisorBackend()
    monkeypatch.setattr("app.resource_bundles._real_model_backend", lambda: backend)
    original_payload = resource_bundles._real_model_payload_async

    async def payload_with_difficulty_values(backend_instance, *, resource_type, item, manifest, source_snapshots, semantic_plan, role="resource_generator"):
        payload = await original_payload(
            backend_instance,
            resource_type=resource_type,
            item=item,
            manifest=manifest,
            source_snapshots=source_snapshots,
            semantic_plan=semantic_plan,
            role=role,
        )
        if resource_type == "quiz" and role == "resource_generator":
            payload["quizQuestions"] = [
                {**question, "difficulty": difficulty}
                for question, difficulty in zip(payload["quizQuestions"], difficulties)
            ]
        return payload

    monkeypatch.setattr(resource_bundles, "_real_model_payload_async", payload_with_difficulty_values)
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        source = session.get(DBSourceRef, "demo-ref-07")
        job = _single_quiz_job(session, learner, profile, source, f"b30-normalize-{expected[0]}")
        result = execute_generation_job(session, learner, job["job_id"])
        assert result["status"] == "succeeded"
        quiz = result["items"][0]
        version_id = quiz["resource"]["version"]["id"]
        content = json.loads(session.get(DBArtifactVersion, version_id).content)
        question_versions = [
            session.get(DBAssessmentQuestionVersion, ref["questionVersionId"])
            for ref in content["questions"]
        ]
        assert [version.expert_difficulty for version in question_versions] == list(expected)
        assert [version.prompt for version in question_versions] == ["题一", "题二", "题三"]
    finally:
        session.close()
        engine.dispose()


def test_live_quiz_generation_rejects_unknown_difficulty_label(monkeypatch):
    backend = _SupervisorBackend()
    monkeypatch.setattr("app.resource_bundles._real_model_backend", lambda: backend)
    original_payload = resource_bundles._real_model_payload_async

    async def payload_with_unknown_difficulty(backend_instance, *, resource_type, item, manifest, source_snapshots, semantic_plan, role="resource_generator"):
        payload = await original_payload(
            backend_instance,
            resource_type=resource_type,
            item=item,
            manifest=manifest,
            source_snapshots=source_snapshots,
            semantic_plan=semantic_plan,
            role=role,
        )
        if resource_type == "quiz" and role == "resource_generator":
            payload["quizQuestions"][0] = {**payload["quizQuestions"][0], "difficulty": "未知等级"}
        return payload

    monkeypatch.setattr(resource_bundles, "_real_model_payload_async", payload_with_unknown_difficulty)
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        source = session.get(DBSourceRef, "demo-ref-07")
        job = _single_quiz_job(session, learner, profile, source, "b30-unknown-label")
        result = execute_generation_job(session, learner, job["job_id"])
        assert result["status"] == "failed"
        assert result["items"][0]["state"] == "failed"
        assert result["items"][0]["failure"]["code"] == "resource_generation.model_output_invalid"
        assert "未知等级" in result["items"][0]["failure"]["message"]
    finally:
        session.close()
        engine.dispose()


def test_live_quiz_generation_normalizes_model_bloom_labels(monkeypatch):
    backend = _SupervisorBackend()
    monkeypatch.setattr("app.resource_bundles._real_model_backend", lambda: backend)
    original_payload = resource_bundles._real_model_payload_async

    async def payload_with_bloom_labels(backend_instance, *, resource_type, item, manifest, source_snapshots, semantic_plan, role="resource_generator"):
        payload = await original_payload(
            backend_instance,
            resource_type=resource_type,
            item=item,
            manifest=manifest,
            source_snapshots=source_snapshots,
            semantic_plan=semantic_plan,
            role=role,
        )
        if resource_type == "quiz" and role == "resource_generator":
            payload["quizQuestions"] = [
                {**question, "bloom": bloom}
                for question, bloom in zip(payload["quizQuestions"], ("记忆", "理解", "应用"))
            ]
        return payload

    monkeypatch.setattr(resource_bundles, "_real_model_payload_async", payload_with_bloom_labels)
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        source = session.get(DBSourceRef, "demo-ref-07")
        job = _single_quiz_job(session, learner, profile, source, "b31-bloom-labels")
        result = execute_generation_job(session, learner, job["job_id"])
        assert result["status"] == "succeeded"
        version_id = result["items"][0]["resource"]["version"]["id"]
        content = json.loads(session.get(DBArtifactVersion, version_id).content)
        question_versions = [
            session.get(DBAssessmentQuestionVersion, ref["questionVersionId"])
            for ref in content["questions"]
        ]
        assert [version.bloom_level for version in question_versions] == ["remember", "understand", "apply"]
        assert [version.prompt for version in question_versions] == ["题一", "题二", "题三"]
    finally:
        session.close()
        engine.dispose()


def test_live_quiz_generation_rejects_unknown_bloom_label(monkeypatch):
    backend = _SupervisorBackend()
    monkeypatch.setattr("app.resource_bundles._real_model_backend", lambda: backend)
    original_payload = resource_bundles._real_model_payload_async

    async def payload_with_unknown_bloom(backend_instance, *, resource_type, item, manifest, source_snapshots, semantic_plan, role="resource_generator"):
        payload = await original_payload(
            backend_instance,
            resource_type=resource_type,
            item=item,
            manifest=manifest,
            source_snapshots=source_snapshots,
            semantic_plan=semantic_plan,
            role=role,
        )
        if resource_type == "quiz" and role == "resource_generator":
            payload["quizQuestions"][0] = {**payload["quizQuestions"][0], "bloom": "未知层级"}
        return payload

    monkeypatch.setattr(resource_bundles, "_real_model_payload_async", payload_with_unknown_bloom)
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        source = session.get(DBSourceRef, "demo-ref-07")
        job = _single_quiz_job(session, learner, profile, source, "b31-unknown-bloom")
        result = execute_generation_job(session, learner, job["job_id"])
        assert result["status"] == "failed"
        assert result["items"][0]["state"] == "failed"
        assert result["items"][0]["failure"]["code"] == "resource_generation.model_output_invalid"
        assert "未知层级" in result["items"][0]["failure"]["message"]
    finally:
        session.close()
        engine.dispose()


def test_supervisor_parallel_plan_dependency_review_and_publish(monkeypatch):
    backend = _SupervisorBackend()
    monkeypatch.setattr("app.resource_bundles._real_model_backend", lambda: backend)
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        source = session.get(DBSourceRef, "demo-ref-07")
        before_events = session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count()
        job = _job(session, learner, profile, source, "b09-supervisor-success")
        result = execute_generation_job(session, learner, job["job_id"])
        assert result["status"] == "succeeded"
        assert result["manifest"]["conversation_id"] == "conv-b09"
        assert result["planner"]["status"] == "completed"
        assert result["review_gate"]["status"] == "passed"
        assert result["publish_gate"]["status"] == "completed"
        assert backend.roles.count("resource_planner") == 1
        assert backend.roles.count("resource_reviewer") == 1
        assert backend.roles.count("resource_generator") == 9
        assert backend.max_active >= 2
        event_types = [event["event_type"] for event in result["events"]]
        assert "resource.item.started" in event_types
        assert "resource.item.completed" in event_types
        assert "review_gate.passed" in event_types
        assert "publish.completed" in event_types
        assert "run.completed" in event_types
        assert all(item["state"] == "succeeded" for item in result["items"])
        assert all(item["resource"]["status"] == "available" for item in result["items"])
        assert session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count() == before_events
        training = next(item for item in result["items"] if item["type"] == "training_task")
        training_started = next(event for event in result["events"] if event["resource_type"] == "training_task" and event["event_type"] == "resource.item.started" and any(ref.startswith("artifact-version:") for ref in event["input_refs"]))
        assert any(ref.startswith("artifact-version:") for ref in training_started["input_refs"])
        artifact = session.get(DBArtifact, training["resource"]["resource_id"])
        version = session.get(DBArtifactVersion, training["resource"]["version"]["id"])
        assert artifact.status == "published"
        assert version is not None
    finally:
        session.close()
        engine.dispose()


def test_reviewer_failure_blocks_publish_and_retry_only_rejected_item(monkeypatch):
    backend = _SupervisorBackend(review_approved=False)
    monkeypatch.setattr("app.resource_bundles._real_model_backend", lambda: backend)
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        source = session.get(DBSourceRef, "demo-ref-07")
        job = _job(session, learner, profile, source, "b09-supervisor-review-fail")
        first = execute_generation_job(session, learner, job["job_id"])
        assert first["status"] == "partial_success"
        assert first["review_gate"]["status"] == "failed"
        assert first["publish_gate"]["status"] == "pending"
        assert any(event["event_type"] == "run.failed" and event["retryable"] for event in first["events"])
        assert not any(event["event_type"] == "publish.completed" for event in first["events"])
        generator_calls_before_retry = backend.roles.count("resource_generator")
        assert generator_calls_before_retry == 9
        retry_generation_item(session, learner, job["job_id"], "handout")
        backend.review_approved = True
        second = execute_generation_job(session, learner, job["job_id"])
        assert second["status"] == "succeeded"
        assert backend.roles.count("resource_planner") == 1
        assert backend.roles.count("resource_generator") == generator_calls_before_retry + 1
        assert second["review_gate"]["status"] == "passed"
        assert second["publish_gate"]["status"] == "completed"
        assert any(event["event_type"] == "publish.completed" for event in second["events"])
        assert all(item["state"] == "succeeded" for item in second["items"])
        handout = next(item for item in second["items"] if item["type"] == "handout")
        assert len(handout["attempt_history"]) == 2
    finally:
        session.close()
        engine.dispose()


def test_reviewer_model_failure_is_explicit(monkeypatch):
    backend = _SupervisorBackend(fail_review=True)
    monkeypatch.setattr("app.resource_bundles._real_model_backend", lambda: backend)
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        source = session.get(DBSourceRef, "demo-ref-07")
        job = _job(session, learner, profile, source, "b09-supervisor-review-outage")
        result = execute_generation_job(session, learner, job["job_id"])
        assert result["status"] == "failed"
        assert result["review_gate"]["status"] == "failed"
        assert result["publish_gate"]["status"] == "pending"
        assert any(event["event_type"] == "review_gate.failed" and event["retryable"] for event in result["events"])
        assert any(event["event_type"] == "run.failed" and event["retryable"] for event in result["events"])
        assert not any(event["event_type"] == "publish.completed" for event in result["events"])
    finally:
        session.close()
        engine.dispose()


def test_resource_item_failure_emits_run_failed_terminal_event(monkeypatch):
    backend = _SupervisorBackend()
    monkeypatch.setattr("app.resource_bundles._real_model_backend", lambda: backend)
    original_payload = resource_bundles._real_model_payload_async

    async def fail_handout(backend_instance, *, resource_type, item, manifest, source_snapshots, semantic_plan):
        if resource_type == "handout":
            raise RuntimeError("handout provider unavailable")
        return await original_payload(
            backend_instance,
            resource_type=resource_type,
            item=item,
            manifest=manifest,
            source_snapshots=source_snapshots,
            semantic_plan=semantic_plan,
        )

    monkeypatch.setattr(resource_bundles, "_real_model_payload_async", fail_handout)
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        source = session.get(DBSourceRef, "demo-ref-07")
        job = _job(session, learner, profile, source, "b09-supervisor-item-failure")
        result = execute_generation_job(session, learner, job["job_id"])
        assert result["status"] == "partial_success"
        assert any(event["event_type"] == "resource.item.failed" and event["resource_type"] == "handout" for event in result["events"])
        assert any(event["event_type"] == "run.failed" and event["retryable"] for event in result["events"])
    finally:
        session.close()
        engine.dispose()
