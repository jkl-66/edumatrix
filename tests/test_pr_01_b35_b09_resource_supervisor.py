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
            "title": f"{query} · 课程视频候选",
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
        self.inputs = []
        self.active = 0
        self.max_active = 0

    async def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        self.roles.append(role)
        self.inputs.append((role, json.loads(user_prompt)))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0)
            if role == "resource_reviewer":
                if self.fail_review:
                    raise RuntimeError("reviewer unavailable")
                local_approved = self.review_approved or not any(item["type"] == "handout" for item in json.loads(user_prompt)["candidates"])
                return json.dumps({
                    "approved": local_approved,
                    "summary": "审核通过" if local_approved else "讲义需要补充课程边界",
                    "findings": [] if local_approved else [{"resourceType": "handout", "reason": "缺少边界"}, {"resourceType": "quiz", "reason": "其他资源意见"}, {"type": "计数错误", "issue": "重复数值不能漏算"}],
                    "rejectedTypes": [] if local_approved else ["handout"],
                    "conditionReview": [{"claimId": claim['id'], "status": "valid",
                        "reason": "合成测试中的参数限制与给定范围一致；此替身仅用于编排流程回归。", "fix": ""}
                        for claim in json.loads(user_prompt).get('condition_claims', [])],
                }, ensure_ascii=False)
            if role == "resource_planner":
                return json.dumps({
                    "summary": "共享计划：所有资源围绕冻结课程来源生成",
                    "plan": "先提炼课程核心概念，再分别生成解释、练习、实验与复述，并统一校验来源。",
                    "resourceBriefs": [{"type": item, "goal": "依据来源生成", "dependencies": []} for item in RESOURCE_TYPES],
                }, ensure_ascii=False)
            return json.dumps({
                "summary": "候选资源摘要",
                "selectedVideoIds": [candidate['id'] for candidate in json.loads(user_prompt).get('video_candidates', [])],
                "learningGoal": "完成课程目标",
                "narrative": "依据冻结课程来源生成的候选内容，包含条件、机制和验证边界。",
                "rootNodeId": "topic",
                "nodes": [
                    {"nodeId":"topic","parentNodeId":None,"label":"课程知识","summary":"核对知识的机制与适用范围。","relation":"主题","depth":0},
                    {"nodeId":"conditions","parentNodeId":"topic","label":"适用条件","summary":"方法需要满足相应条件。","relation":"前提","depth":1},
                ],
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
                "estimatedMinutes": 35,
                "data": ["冻结课程示例数据"],
                "parameters": (json.loads(user_prompt).get("interactive_template") or {}).get("parameters", []),
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
        assert result["status"] == "succeeded", json.dumps({i["type"]: i.get("failure") for i in result["items"] if i["state"] == "failed"}, ensure_ascii=False)
        quiz = result["items"][0]
        version_id = quiz["resource"]["version"]["id"]
        content = json.loads(session.get(DBArtifactVersion, version_id).content)
        assert content["adaptation"]["learningGoal"] == "完成课程目标"
        assert content["semanticContext"]["learning_goal"] == "完成课程目标"
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
        assert result["status"] == "succeeded", json.dumps({i["type"]: i.get("failure") for i in result["items"] if i["state"] == "failed"}, ensure_ascii=False)
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
        assert result["status"] == "succeeded", json.dumps({i["type"]: i.get("failure") for i in result["items"] if i["state"] == "failed"}, ensure_ascii=False)
        assert result["manifest"]["conversation_id"] == "conv-b09"
        assert result["planner"]["status"] == "completed"
        assert result["review_gate"]["status"] == "passed"
        assert result["publish_gate"]["status"] == "completed"
        assert backend.roles.count("resource_planner") == 1
        assert backend.roles.count("resource_reviewer") == 10
        reviewed_types = {candidate["type"] for role, data in backend.inputs if role == "resource_reviewer" for candidate in data["candidates"]}
        assert reviewed_types == set(resource_bundles.GENERATION_RESOURCE_TYPES)
        assert backend.roles.count("resource_generator") == 9
        assert backend.max_active >= 2
        review_input = next(data for role, data in backend.inputs if role == "resource_reviewer")
        planner_input = next(data for role, data in backend.inputs if role == "resource_planner")
        runtime = planner_input["runtime"]
        assert runtime["networkAvailable"] is False
        assert runtime["fileAccessAvailable"] is False
        assert "sklearn" in runtime["supportedModules"]
        assert "不得编造真实样本" in runtime["datasetPolicy"]
        assert review_input["runtime"] == {key: value for key, value in runtime.items()
                                            if key not in {"scope", "scopeDescription"}}
        video_review = next(data for role, data in backend.inputs if role == "resource_reviewer"
                            and any(item["type"] == "video" for item in data["candidates"]))
        assert video_review["runtime"] == runtime
        assert all(data["runtime"] == runtime for role, data in backend.inputs if role == "resource_generator")
        quiz_review = next(data for role, data in backend.inputs if role == "resource_reviewer"
                          and [c["type"] for c in data["candidates"]] == ["quiz"])
        quiz_candidate = quiz_review["candidates"][0]
        question_details = json.loads(quiz_candidate["content"])["question_details"]
        assert [q["prompt"] for q in question_details] == ["题一", "题二", "题三"]
        assert all(q["answer_key"] and len(q["options"]) == 4 for q in question_details)
        training_input = next(data for role, data in backend.inputs if role == "resource_generator" and data["resource_type"] == "training_task")
        assert {d["type"] for d in training_input["dependency_resources"]} == {"code_sandbox", "interactive_model"}
        assert "supervisor-generated" in training_input["dependency_resources"][0]["content"]
        practical_review = next(data for role, data in backend.inputs if role == "resource_reviewer"
                                and any(c["type"] == "training_task" for c in data["candidates"]))
        training_candidate = next(c for c in practical_review["candidates"] if c["type"] == "training_task")
        companions = {c["type"]: c for c in [*practical_review["dependency_resources"], *practical_review["candidates"]]}
        assert set(companions) == {"training_task", "code_sandbox", "interactive_model"}
        connection = next(data for role, data in backend.inputs if role == "resource_reviewer"
                          and data.get("review_scope", {}).get("stage") == "consistency")
        assert {c["type"] for c in connection["candidates"]} == set(resource_bundles.GENERATION_RESOURCE_TYPES)
        assert {c["version_id"] for c in practical_review["candidates"]}.isdisjoint(
            c["version_id"] for c in practical_review["dependency_resources"])
        assert {b["type"] for b in training_candidate["dependency_bindings"]} == {"code_sandbox", "interactive_model"}
        for binding in training_candidate["dependency_bindings"]:
            assert binding["resource_id"] == companions[binding["type"]]["resource_id"]
            assert binding["version_id"] == companions[binding["type"]]["version_id"]
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


def test_single_training_reuses_matching_published_versions_and_reviews_their_content(monkeypatch):
    backend = _SupervisorBackend()
    monkeypatch.setattr(resource_bundles, "_real_model_backend", lambda: backend)
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        source = session.get(DBSourceRef, "demo-ref-07")
        job = _job(session, learner, profile, source, "training-reuse-prerequisites")
        original = execute_generation_job(session, learner, job["job_id"])
        deps = {item["type"]: item["resource"] for item in original["items"]
                if item["type"] in {"code_sandbox", "interactive_model"}}
        backend.inputs.clear()
        single = create_generation_job(session, learner,
            course_id="demo-course-rag-trust-v1", knowledge_point_id="demo-kp-07", profile_snapshot_id=profile.id,
            idempotency_key="training-only-reuse", scope="single",
            items=[{"type": "training_task", "title": "单项实训", "source_ref_ids": [source.id]}])
        result = execute_generation_job(session, learner, single["job_id"])
        assert result["status"] == "succeeded"
        assert len(result["items"]) == 1
        generated = [data for role, data in backend.inputs if role == "resource_generator"]
        assert len(generated) == 1 and generated[0]["resource_type"] == "training_task"
        expected = {value["version"]["id"] for value in deps.values()}
        planned = next(data for role, data in backend.inputs if role == "resource_planner")
        assert {item["version_id"] for item in planned["dependency_resources"]} == expected
        assert {item["version_id"] for item in generated[0]["dependency_resources"]} == expected
        reviewed = next(data for role, data in backend.inputs if role == "resource_reviewer")
        assert {item["version_id"] for item in reviewed["dependency_resources"]} == expected
        version = session.get(DBArtifactVersion, result["items"][0]["resource"]["version"]["id"])
        assert {item["version_id"] for item in version.metadata_json["training_dependencies"]} == expected

        # An otherwise published resource with different topic/source/owner cannot substitute.
        for kind, field, value in [("code_sandbox", "knowledge_point_id", "demo-kp-01"),
                                    ("interactive_model", "source_snapshot_hash", "changed")]:
            dep = session.get(DBArtifactVersion, deps[kind]["version"]["id"])
            dep.metadata_json = {**dep.metadata_json, field: value}
        blocked = create_generation_job(session, learner,
            course_id="demo-course-rag-trust-v1", knowledge_point_id="demo-kp-07", profile_snapshot_id=profile.id,
            idempotency_key="training-mismatched-prerequisites", scope="single",
            items=[{"type": "training_task", "title": "不可串用", "source_ref_ids": [source.id]}])
        failed = execute_generation_job(session, learner, blocked["job_id"])
        assert failed["status"] == "failed"
        assert "同时选择这三类资源" in failed["items"][0]["failure"]["message"]
    finally:
        session.close()
        engine.dispose()


def test_authored_code_checks_the_actual_runtime_before_saving(monkeypatch):
    monkeypatch.setattr(resource_bundles, "_real_model_backend", lambda: _SupervisorBackend())
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        source = session.get(DBSourceRef, "demo-ref-07")
        job = _job(session, learner, profile, source, "authored-code-runtime")
        original = execute_generation_job(session, learner, job["job_id"])
        resource = next(i["resource"] for i in original["items"] if i["type"] == "code_sandbox")
        body = json.loads(session.get(DBArtifactVersion, resource["version"]["id"]).content)
        single = create_generation_job(session, learner, course_id="demo-course-rag-trust-v1",
            knowledge_point_id="demo-kp-07", profile_snapshot_id=profile.id,
            idempotency_key="authored-code-new", scope="single",
            items=[{"type": "code_sandbox", "title": "输入练习", "source_ref_ids": [source.id]}])
        body["files"][0]["content"] = "import sys\nprint(sys.stdin.read())"
        with pytest.raises(resource_bundles.ResourceBundleError, match="sys"):
            resource_bundles.complete_generation_item(session, learner, single["job_id"], "code_sandbox",
                content=json.dumps(body), content_format="json", generation_mode="agent_revision")
        body["files"][0]["content"] = "try:\n    text = input()\nexcept EOFError:\n    text = ''\nprint(text)"
        result = resource_bundles.complete_generation_item(session, learner, single["job_id"], "code_sandbox",
            content=json.dumps(body), content_format="json", generation_mode="agent_revision")
        assert result["items"][0]["state"] == "succeeded"
        assert result["publish_gate"]["status"] != "published"
    finally:
        session.close()
        engine.dispose()


def test_authored_training_revision_opens_the_same_versions_given_to_review(monkeypatch):
    from app.m5_resources import _training_task_projection

    monkeypatch.setattr(resource_bundles, "_real_model_backend", lambda: _SupervisorBackend())
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        source = session.get(DBSourceRef, "demo-ref-07")
        job = _job(session, learner, profile, source, "training-authored-bindings")
        original = execute_generation_job(session, learner, job["job_id"])
        resources = {item["type"]: item["resource"] for item in original["items"]}
        old = session.get(DBArtifactVersion, resources["training_task"]["version"]["id"])
        old_content = old.content
        body = json.loads(old_content)
        body["linkedSandboxId"] = "old-writing-reference"
        body["linkedModelId"] = "old-model-reference"
        dependencies = [{"type": kind, "resource_id": resources[kind]["resource_id"],
                         "version_id": resources[kind]["version"]["id"], "source_ref_ids": [source.id]}
                        for kind in ("code_sandbox", "interactive_model")]
        single = create_generation_job(session, learner,
            course_id="demo-course-rag-trust-v1", knowledge_point_id="demo-kp-07", profile_snapshot_id=profile.id,
            idempotency_key="training-authored-new", scope="single",
            items=[{"type": "training_task", "title": "修订实训", "source_ref_ids": [source.id]}])
        result = resource_bundles.complete_generation_item(session, learner, single["job_id"], "training_task",
            content=json.dumps(body), content_format="json", training_dependencies=dependencies)
        version = session.get(DBArtifactVersion, result["items"][0]["resource"]["version"]["id"])
        stored = json.loads(version.content)
        assert stored["steps"] == body["steps"]
        assert stored["linkedSandboxId"] == dependencies[0]["resource_id"]
        assert stored["linkedModelId"] == dependencies[1]["resource_id"]
        projection = _training_task_projection(session, session.get(DBArtifact, version.artifact_id), version)
        assert {(link["id"], link["resource_version_id"]) for link in projection["linked_resources"]} == {
            (dep["resource_id"], dep["version_id"]) for dep in dependencies}
        assert version.metadata_json["training_dependencies"] == dependencies
        assert old.content == old_content
    finally:
        session.close()
        engine.dispose()


def test_single_experiment_uses_actual_published_code_and_keeps_teaching_body(monkeypatch):
    backend = _SupervisorBackend()
    monkeypatch.setattr(resource_bundles, "_real_model_backend", lambda: backend)
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        source = session.get(DBSourceRef, "demo-ref-07")
        job = _job(session, learner, profile, source, "experiment-published-code")
        original = execute_generation_job(session, learner, job["job_id"])
        code = next(item["resource"] for item in original["items"] if item["type"] == "code_sandbox")
        backend.inputs.clear()
        single = create_generation_job(session, learner,
            course_id="demo-course-rag-trust-v1", knowledge_point_id="demo-kp-07", profile_snapshot_id=profile.id,
            idempotency_key="experiment-only-reuse", scope="single",
            items=[{"type": "interactive_model", "title": "单项实验", "source_ref_ids": [source.id]}])
        result = execute_generation_job(session, learner, single["job_id"])
        assert result["status"] == "succeeded"
        for role in ("resource_planner", "resource_generator"):
            supplied = next(data for input_role, data in backend.inputs if input_role == role)["dependency_resources"]
            assert [dep["version_id"] for dep in supplied] == [code["version"]["id"]]
            assert "supervisor-generated" in supplied[0]["content"]
        version = session.get(DBArtifactVersion, result["items"][0]["resource"]["version"]["id"])
        assert version.metadata_json["practical_dependencies"][0]["version_id"] == code["version"]["id"]
        review = next(data for role, data in backend.inputs if role == "resource_reviewer")
        assert review["dependency_resources"] == []
        teaching_body = json.loads(version.content)["explanation"]
        assert "包含条件、机制和验证边界" in teaching_body
        projected = resource_bundles.parse_interactive_model_content(version.content)
        assert projected.explanation == teaching_body
    finally:
        session.close()
        engine.dispose()


def test_resource_generation_freezes_active_memory_and_updates_new_requests_after_withdrawal():
    from app.next_core_memory import create_memory, withdraw_memory
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        source = session.get(DBSourceRef, "demo-ref-07")
        memory = create_memory(session, owner_public_id=learner.public_id, title="图书借阅站",
                               memory_type="preference", content="使用图书借阅站作为相关学习例子")
        first = _job(session, learner, profile, source, "resource-active-memory")
        before = resource_bundles._generation_manifest(session, first["job_id"])
        assert resource_bundles._public_generation_context(before)["long_term_memory"]["items"][0]["content"] == memory.content
        withdraw_memory(session, owner_public_id=learner.public_id, memory_id=memory.id,
                        expected_version=memory.lock_version, reason="验证撤回")
        second = _job(session, learner, profile, source, "resource-withdrawn-memory")
        after = resource_bundles._generation_manifest(session, second["job_id"])
        assert after["context"]["long_term_memory"]["items"] == []
        assert before["input_snapshot"]["input_snapshot_hash"] != after["input_snapshot"]["input_snapshot_hash"]
        assert resource_bundles._generation_manifest(session, first["job_id"])["context"]["long_term_memory"]["items"]
    finally:
        session.close()
        engine.dispose()


def test_training_refreshes_changed_dependency_even_after_more_own_retries(monkeypatch):
    class Backend(_SupervisorBackend):
        reviews = 0

        async def generate(self, system_prompt, user_prompt, *, role):
            raw = await super().generate(system_prompt, user_prompt, role=role)
            if role == "resource_reviewer" and not json.loads(user_prompt).get("review_scope") and any(item["type"] == "training_task" for item in json.loads(user_prompt)["candidates"]):
                rejected = ["training_task", "training_task", "interactive_model", None][self.reviews]
                self.reviews += 1
                if rejected:
                    return json.dumps({**json.loads(raw), "approved": False, "summary": "核对配套步骤", "rejectedTypes": [rejected], "findings": []})
            return raw

    backend = Backend()
    monkeypatch.setattr(resource_bundles, "_real_model_backend", lambda: backend)
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        source = session.get(DBSourceRef, "demo-ref-07")
        job = _job(session, learner, profile, source, "dependency-after-training-retries")
        result = execute_generation_job(session, learner, job["job_id"])
        for kind in ("training_task", "training_task", "interactive_model"):
            retry_generation_item(session, learner, job["job_id"], kind)
            result = execute_generation_job(session, learner, job["job_id"])
        assert result["status"] == "succeeded"
        resources = {item["type"]: item["resource"] for item in result["items"]}
        training = session.get(DBArtifactVersion, resources["training_task"]["version"]["id"])
        bound = {item["type"]: item["version_id"] for item in training.metadata_json["training_dependencies"]}
        assert bound["interactive_model"] == resources["interactive_model"]["version"]["id"]
        assert len([data for role, data in backend.inputs if role == "resource_generator" and data["resource_type"] == "training_task"]) == 4
    finally:
        session.close()
        engine.dispose()


def test_revision_preserves_an_unselected_rejected_draft_for_review(monkeypatch):
    backend = _SupervisorBackend(review_approved=False)
    monkeypatch.setattr(resource_bundles, '_real_model_backend', lambda: backend)
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username='lzz').one()
        profile = session.get(DBProfileSnapshot, 'demo-profile-lzz-v1')
        source = session.get(DBSourceRef, 'demo-ref-07')
        job = _job(session, learner, profile, source, 'revision-preserve-review-output')
        first = execute_generation_job(session, learner, job['job_id'])
        assert first['review_gate']['status'] == 'failed'
        _, steps = resource_bundles._task_steps(session, job['job_id'])
        video = steps[RESOURCE_TYPES.index('video')+1]
        video.status = 'failed'
        video.error_code = 'resource_generation.review_rejected'
        video.error_message = '误将代码环境视作浏览器离线'
        preserved = (video.id, video.attempt, video.output_artifact_version_id)
        generator_count = backend.roles.count('resource_generator')
        amended = resource_bundles.revise_generation_job(session, learner, job['job_id'],
            feedback='只修讲义，视频重新核对实际网络条件。', resource_types=['handout'],
            idempotency_key='preserve-rejected-video',
            active_requirements={'learning_goal':'理解课程概念', 'shared':[], 'by_resource':{
                'video':['代码沙盒离线不代表浏览器离线。']}})
        _, after = resource_bundles._task_steps(session, job['job_id'])
        assert preserved == (after[6].id, after[6].attempt, after[6].output_artifact_version_id)
        assert amended['review_gate']['status'] == 'pending'
        assert amended['publish_gate']['status'] == 'pending'
        backend.review_approved = True
        final = execute_generation_job(session, learner, job['job_id'])
        assert final['review_gate']['status'] == 'passed'
        assert backend.roles.count('resource_generator') == generator_count + 1
        assert next(i for i in final['items'] if i['type']=='video')['resource']['version']['id'] == preserved[2]
    finally:
        session.close()
        engine.dispose()


def test_revision_updates_only_explicit_sources_and_preserves_old_versions(monkeypatch):
    backend = _SupervisorBackend()
    monkeypatch.setattr(resource_bundles, "_real_model_backend", lambda: backend)
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        source = session.get(DBSourceRef, "demo-ref-07")
        job = _job(session, learner, profile, source, "revision-explicit-sources")
        execute_generation_job(session, learner, job['job_id'])
        before = resource_bundles._generation_manifest(session, job['job_id'])
        _, steps = resource_bundles._task_steps(session, job['job_id'])
        old_versions = {n: step.output_artifact_version_id for n, step in steps.items()}
        old_content = session.get(DBArtifactVersion, old_versions[1]).content
        kwargs = dict(feedback='按新版来源修订讲义，其他资源保持。', resource_types=['handout'],
            idempotency_key='explicit-source-revision', source_ref_ids_by_type={'handout':['demo-ref-06']},
            active_requirements=before.get('active_requirements'))
        with pytest.raises(resource_bundles.ResourceBundleError, match='同时选择'):
            resource_bundles.revise_generation_job(session, learner, job['job_id'],
                **{**kwargs, 'source_ref_ids_by_type':{'quiz':['demo-ref-06']}})
        resource_bundles.revise_generation_job(session, learner, job['job_id'], **kwargs)
        # An exact repeated request reuses the same revision, a different source does not.
        resource_bundles.revise_generation_job(session, learner, job['job_id'], **kwargs)
        with pytest.raises(resource_bundles.ResourceBundleError, match='已对应其他内容'):
            resource_bundles.revise_generation_job(session, learner, job['job_id'],
                **{**kwargs, 'source_ref_ids_by_type':{'handout':['demo-ref-07']}})
        after = resource_bundles._generation_manifest(session, job['job_id'])
        assert after['input_snapshot']['source_snapshots']['handout'][0]['source_ref_id']=='demo-ref-06'
        for kind in RESOURCE_TYPES[1:]:
            assert after['input_snapshot']['source_snapshots'][kind]==before['input_snapshot']['source_snapshots'][kind]
        _, revised = resource_bundles._task_steps(session, job['job_id'])
        assert resource_bundles._step_input(revised[1])['source_ref_ids']==['demo-ref-06']
        assert all(revised[n].output_artifact_version_id==vid for n,vid in old_versions.items() if n!=1)
        assert session.get(DBArtifactVersion,old_versions[1]).content==old_content
        final = execute_generation_job(session, learner, job['job_id'])
        assert final['review_gate']['status']=='passed'
        _, revised = resource_bundles._task_steps(session, job['job_id'])
        current = session.get(DBArtifactVersion,revised[1].output_artifact_version_id)
        assert current.metadata_json['source_snapshot'][0]['source_ref_id']=='demo-ref-06'
        assert current.metadata_json['source_snapshot_hash']!=session.get(DBArtifactVersion,old_versions[1]).metadata_json['source_snapshot_hash']
    finally:
        session.close()
        engine.dispose()


def test_reviewer_failure_blocks_publish_and_retry_only_rejected_item(monkeypatch):
    class LongFeedbackBackend(_SupervisorBackend):
        async def generate(self, system_prompt, user_prompt, *, role):
            raw = await super().generate(system_prompt, user_prompt, role=role)
            if role == 'resource_reviewer' and not self.review_approved:
                data = json.loads(raw)
                if data["approved"]:
                    return raw
                data['findings'].append({'resourceType':'handout', 'issue':'核对较长的全部解释。' * 280,
                                        'fix':'末尾要求：保留全部原题，只修正解释。'})
                return json.dumps(data,ensure_ascii=False)
            return raw
    backend = LongFeedbackBackend(review_approved=False)
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
        failed_item = next(item for item in first["items"] if item["type"] == "handout")
        assert "缺少边界" in failed_item["failure"]["message"]
        assert "resourceType" not in failed_item["failure"]["message"]
        assert all("resourceType" not in event["summary"] for event in first["events"])
        from app.m5_resources import resource_detail, validate_resource_completion
        from app.m5_capabilities import M5CapabilityError
        from app.code_sandbox import _owned_resource, CodeSandboxError
        from app.interactive_lab import _resource_contract, InteractiveLabError
        from app.feynman import _source_resource, FeynmanError
        for item in first["items"]:
            artifact = session.get(DBArtifact, item["resource"]["resource_id"])
            detail = resource_detail(session, artifact)
            assert detail["resource"]["status"] == "generation_pending"
            assert detail["resource"]["generation_job_id"] == job["job_id"]
            version = session.get(DBArtifactVersion, artifact.current_version_id)
            with pytest.raises(M5CapabilityError, match="还没有完成核对"):
                validate_resource_completion(session, artifact=artifact, resource_version_id=version.id,
                    completion_rule=version.metadata_json["completion_rule"])
            checker = {"code_sandbox": (_owned_resource, CodeSandboxError),
                       "interactive_model": (_resource_contract, InteractiveLabError),
                       "feynman": (_source_resource, FeynmanError)}.get(item["type"])
            if checker:
                with pytest.raises(checker[1], match="还没有完成核对"):
                    checker[0](session, artifact.id, learner.public_id)
        generator_calls_before_retry = backend.roles.count("resource_generator")
        assert generator_calls_before_retry == 9
        _, latest = resource_bundles._task_steps(session, job["job_id"])
        failed_step = next(step for step in latest.values() if step.status == "failed")
        rejected_version_id = failed_step.output_artifact_version_id
        rejected_content = session.get(DBArtifactVersion, rejected_version_id).content
        failed_step.input_summary = json.dumps({**resource_bundles._step_input(failed_step),
                                               "revision_feedback": "前次要求：迁移练习不能再次执行最终测试。"}, ensure_ascii=False)
        queued = retry_generation_item(session, learner, job["job_id"], "handout")
        assert queued["review_gate"]["status"] == "pending"
        from app.database import DBGenerationTask
        retry_task = session.get(DBGenerationTask, job["job_id"])
        assert retry_task.status == "queued" and retry_task.completed_at is None
        # Enqueuing a retry has not executed its generation or review yet.
        assert backend.roles.count("resource_generator") == generator_calls_before_retry
        assert not retry_task.failure_reason
        assert any(event["event_type"] == "review_gate.failed" for event in queued["events"])
        backend.review_approved = True
        second = execute_generation_job(session, learner, job["job_id"])
        assert second["status"] == "succeeded"
        assert backend.roles.count("resource_planner") == 1
        assert backend.roles.count("resource_generator") == generator_calls_before_retry + 1
        retried_input = [data for role, data in backend.inputs if role == "resource_generator"][-1]
        assert retried_input["revision_source"]["version_id"] == rejected_version_id
        assert json.loads(retried_input["revision_source"]["content"]) == {key:value for key,value in json.loads(rejected_content).items() if key != "semanticContext"}
        assert session.get(DBArtifactVersion, rejected_version_id).content == rejected_content
        assert "讲义需要补充课程边界" in retried_input["revision_feedback"]
        assert "缺少边界" in retried_input["revision_feedback"]
        assert "重复数值不能漏算" in retried_input["revision_feedback"]
        assert "末尾要求：保留全部原题，只修正解释。" in retried_input["revision_feedback"]
        assert "迁移练习不能再次执行最终测试" not in retried_input["revision_feedback"]
        assert "迁移练习不能再次执行最终测试" in resource_bundles._step_input(failed_step)["revision_feedback"]
        assert "其他资源意见" not in retried_input["revision_feedback"]
        reviews = session.query(DBTaskEvent).filter_by(task_id=job["job_id"], event_type="resource_generation.review_result").all()
        assert len(reviews) == 2
        assert reviews[0].payload["review"]["findings"][1]["reason"] == "其他资源意见"
        assert all(event["event_type"] != "resource_generation.review_result" for event in second["events"])
        assert second["review_gate"]["status"] == "passed"
        assert second["publish_gate"]["status"] == "completed"
        assert any(event["event_type"] == "publish.completed" for event in second["events"])
        assert all(item["state"] == "succeeded" for item in second["items"])
        handout = next(item for item in second["items"] if item["type"] == "handout")
        assert len(handout["attempt_history"]) == 2
        for item in second["items"]:
            artifact = session.get(DBArtifact, item["resource"]["resource_id"])
            assert resource_detail(session, artifact)["resource"]["status"] == "available"
        rejected_artifact = session.get(DBArtifact, failed_item["resource"]["resource_id"])
        assert resource_detail(session, rejected_artifact)["resource"]["status"] == "generation_pending"
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize("unavailable", ["failed", "archived"])
def test_existing_practice_sessions_cannot_continue_unreviewed_resource_versions(monkeypatch, unavailable):
    from app.database import DBTaskStep
    from app.interactive_lab import create_instance, apply_action as lab_action, get_instance, InteractiveLabError
    from app.feynman import create_session, apply_action as feynman_action, get_session, FeynmanError
    monkeypatch.setattr(resource_bundles, "_real_model_backend", lambda: _SupervisorBackend())
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        job = _job(session, learner, session.get(DBProfileSnapshot, "demo-profile-lzz-v1"),
                   session.get(DBSourceRef, "demo-ref-07"), "existing-practice-candidates")
        result = execute_generation_job(session, learner, job["job_id"])
        resources = {item["type"]: item["resource"] for item in result["items"]}
        lab, lab_version, _ = create_instance(session, owner=learner.public_id,
            template_id=None, title=None, parameters=None, linked_media_resource_id=None,
            source_resource_id=resources["interactive_model"]["resource_id"], idempotency_key="before-rejection")
        _, feynman_version, feynman, _ = create_session(session, owner=learner.public_id,
            source_resource_id=resources["feynman"]["resource_id"], idempotency_key="before-rejection")
        # Represents sessions created by the old UI before its review gate was enforced.
        for kind in ("interactive_model", "feynman"):
            if unavailable == "failed":
                step = session.query(DBTaskStep).filter_by(output_artifact_version_id=resources[kind]["version"]["id"]).one()
                step.status = "failed"
            else:
                from app.m5_resources import set_resource_archived
                artifact = session.get(DBArtifact, resources[kind]["resource_id"])
                set_resource_archived(session, artifact=artifact, actor_public_id=learner.public_id,
                                      archived=True, expected_lock_version=artifact.lock_version)
        session.flush()
        before = session.query(DBLearningEvent).count()
        assert get_instance(session, lab.instance_id, learner.public_id)["status"] == "configured"
        assert get_session(session, feynman.session_id, learner.public_id)["status"] == "draft"
        reason = "还没有完成核对" if unavailable == "failed" else "已归档"
        with pytest.raises(InteractiveLabError, match=reason):
            lab_action(session, instance_id=lab.instance_id, owner=learner.public_id, action="run",
                parameters=None, observation=None, expected_version=lab_version.version_number, idempotency_key="blocked-run")
        with pytest.raises(FeynmanError, match=reason):
            feynman_action(session, session_id=feynman.session_id, actor=learner, action="submit_round1",
                text="先把材料读懂，再用自己的话说明条件、例子、机制和边界。" * 3,
                expected_version=feynman_version.version_number, idempotency_key="blocked-submit")
        assert session.query(DBLearningEvent).count() == before
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize("corrected", [True, False])
def test_planner_malformed_response_gets_only_one_real_correction(corrected):
    calls = []

    class PlannerBackend:
        async def generate(self, system, user, *, role):
            calls.append((system, user, role))
            if len(calls) == 1 or not corrected:
                return '{"plan":"incomplete'
            return json.dumps({"summary": "离线数据示例", "plan": "使用已提供的实际代码并区分模拟实验。", "resourceBriefs": []})

    call = resource_bundles._shared_semantic_plan_async(PlannerBackend(),
        manifest={"context": {"knowledge_point_title": "决策树分类"}, "selected_resource_types": ["interactive_model"],
                  "dependency_resources": [{"version_id": "actual-code", "content": "240 samples"}]}, source_snapshots=[])
    if corrected:
        result = asyncio.run(call)
        assert result["format_corrections"] == 1
        assert "实际代码" in result["plan"]
    else:
        with pytest.raises(resource_bundles.ResourceBundleError, match="资源规划模型调用失败"):
            asyncio.run(call)
    assert len(calls) == 2
    assert calls[0][1] == calls[1][1]
    assert all(role == "resource_planner" for _, _, role in calls)


def test_generation_failure_keeps_diagnostics_out_of_learning_feedback():
    from app.learner_output import resource_failure_feedback
    raw = "资源规划模型调用失败：Expecting ',' delimiter: line 1 column 3559"
    feedback = resource_failure_feedback(raw)
    assert "请重试" in feedback and "仍会保留" in feedback
    assert "delimiter" not in feedback and "3559" not in feedback
    review = resource_failure_feedback('需调整。具体审核意见：[{"issue":"checkpoint-3缺少dependency_resources的requiredChecks", "fix":"先核对code_sandbox的step-3和rubric-run"}]')
    assert "先核对代码练习的第3步和评分要求" in review
    assert "配套内容的运行检查" in review
    code = '```python\nsteps = [1, 2]\nprint(steps)\n```'
    visible = resource_failure_feedback(f'objective与steps、rubric和deliverables不一致。\n{code}')
    assert "学习目标与实践步骤、评分要求和交付内容不一致" in visible
    assert code in visible


@pytest.mark.parametrize("resume", ["item", "job"])
def test_invalid_cached_structure_retries_with_feedback_and_keeps_original(monkeypatch, resume):
    class InvalidTreeBackend(_SupervisorBackend):
        async def generate(self, system_prompt, user_prompt, *, role):
            result = json.loads(await super().generate(system_prompt, user_prompt, role=role))
            if role == "resource_generator" and not json.loads(user_prompt).get("revision_feedback"):
                result["nodes"][1]["parentNodeId"] = "missing-parent"
            return json.dumps(result, ensure_ascii=False)

    backend = InvalidTreeBackend()
    monkeypatch.setattr(resource_bundles, "_real_model_backend", lambda: backend)
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        job = create_generation_job(session, learner, course_id="demo-course-rag-trust-v1",
            knowledge_point_id="demo-kp-07", profile_snapshot_id="demo-profile-lzz-v1",
            idempotency_key=f"invalid-tree-cache-{resume}", scope="single",
            items=[{"type": "mind_map", "title": "课程概念关系", "source_ref_ids": ["demo-ref-07"]}])
        first = execute_generation_job(session, learner, job["job_id"])
        assert first["items"][0]["state"] == "failed"
        _, latest = resource_bundles._task_steps(session, job["job_id"])
        original = next(iter(latest.values()))
        assert original.error_code == "resource_generation.mind_map_invalid"
        cached = session.query(DBTaskEvent).filter_by(task_id=job["job_id"], event_type="resource_generation.part_result").all()
        assert cached, "the invalid candidate must exist to exercise cache recovery"
        before = [json.dumps(event.payload, sort_keys=True) for event in cached]
        if resume == "item":
            retry_generation_item(session, learner, job["job_id"], "mind_map")
        else:
            resource_bundles.recover_generation_job(session, learner, job["job_id"])
        second = execute_generation_job(session, learner, job["job_id"])
        assert second["status"] == "succeeded"
        assert backend.roles.count("resource_generator") == 2
        assert backend.roles.count("resource_planner") == 1
        assert [data for role, data in backend.inputs if role == "resource_generator"][-1]["revision_feedback"] == original.error_message
        assert original.status == "failed"
        assert [json.dumps(event.payload, sort_keys=True) for event in cached] == before
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
        original_versions = {item["type"]: item["resource"]["version"]["id"] for item in result["items"]}
        queued = resource_bundles.recover_generation_job(session, learner, job["job_id"])
        assert queued["status"] == "running"
        assert queued["review_gate"]["status"] == "pending"
        assert not queued["failure_reason"]
        assert all(item["state"] == "succeeded" for item in queued["items"])
        backend.fail_review = False
        resumed = execute_generation_job(session, learner, job["job_id"])
        assert resumed["status"] == "succeeded"
        assert resumed["publish_gate"]["status"] == "completed"
        assert {item["type"]: item["resource"]["version"]["id"] for item in resumed["items"]} == original_versions
        assert backend.roles.count("resource_planner") == 1
        assert backend.roles.count("resource_generator") == 9
        assert backend.roles.count("resource_reviewer") == 19
        assert any(event["event_type"] == "review_gate.failed" for event in resumed["events"])
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize('resource_types', [('handout',), ('handout', 'quiz')])
def test_bundle_review_has_its_own_output_budget(resource_types):
    class Backend:
        max_tokens = 32768
        reasoning_effort = "max"

        async def generate(self, system_prompt, user_prompt, *, role):
            data = json.loads(user_prompt)
            assert self.max_tokens == 65536
            assert self.reasoning_effort == ('low' if (data.get('review_scope') or {}).get('stage') == 'consistency' else 'high')
            assert role == "resource_reviewer"
            data = json.loads(user_prompt)
            assert len(data["candidates"]) == (len(resource_types) if data.get("review_scope") else 1)
            return '{"approved":false,"summary":"题目需更正","rejectedTypes":["quiz"]}'

    backend = Backend()
    result = asyncio.run(resource_bundles._resource_review_async(
        backend, manifest={}, semantic_plan="核对同主题资源",
        candidates=[{"type": kind} for kind in resource_types],
    ))
    assert result["approved"] is False
    assert backend.max_tokens == 32768


def test_large_review_keeps_whole_contents_and_reuses_completed_groups_after_failure():
    class Backend:
        max_tokens = 32768
        reasoning_effort = "max"

        def __init__(self):
            self.calls = []
            self.fail_practice = True

        async def generate(self, system_prompt, user_prompt, *, role):
            data = json.loads(user_prompt)
            kinds = {item["type"] for item in data["candidates"]}
            self.calls.append(data)
            complete = [*data["candidates"], *data["dependency_resources"]]
            available = {item["type"] for item in complete}
            if (data.get("review_scope") or {}).get("stage") == "consistency":
                assert available == set(resource_bundles.GENERATION_RESOURCE_TYPES)
            else:
                assert len(kinds) == 1
                assert available == (kinds | {"code_sandbox", "interactive_model"} if 'training_task' in kinds else kinds)
            assert data["shared_semantic_plan"].endswith("计划末尾")
            assert data["sources"][0]["quote"].endswith("原文末尾")
            assert data["learner_adaptation"]["assessment_target"] == {"task": "辨认条件并完成一个变式"}
            assert all(item["content"].endswith("正文末尾") for item in complete)
            if "training_task" in kinds:
                assert {"code_sandbox", "interactive_model"}.issubset(available)
                if self.fail_practice:
                    raise RuntimeError("network interruption")
            return json.dumps({"approved": True, "summary": "本组已核对", "findings": [], "rejectedTypes": [],
                "teachingReview": [{"resourceType": kind, "observedLevel": "foundation", "matchesTarget": True,
                    "evidence": "题目要求解释条件并算一个变式"} for kind in kinds]})

    backend = Backend()
    candidates = [{"type": kind, "version_id": "v-" + kind, "content": kind * 50 + "正文末尾"}
                  for kind in resource_bundles.GENERATION_RESOURCE_TYPES]
    next(item for item in candidates if item['type']=='training_task')['dependency_bindings'] = [
        {'type':kind,'version_id':'v-'+kind,'purpose':'learner_link'} for kind in ['code_sandbox','interactive_model']]
    manifest = {"context": {"profile_adaptation_plan": {"assessment_target": {"task": "辨认条件并完成一个变式"}}},
                "input_snapshot": {"source_snapshots": {"handout": [
        {"source_ref_id": "source", "quote": "依据" * 4000 + "原文末尾"}
    ]}}}
    cache = {}
    def run():
        return asyncio.run(resource_bundles._resource_review_async(
            backend, manifest=manifest, semantic_plan="计划" * 7000 + "计划末尾",
            candidates=candidates, completed_reviews=cache, save_review=cache.__setitem__,
        ))

    with pytest.raises(resource_bundles.ResourceBundleError):
        run()
    successful = [value for value in cache.values() if value.get("approved")]
    failed = [value for value in cache.values() if value.get("review_failed")]
    assert len(successful) == 8
    assert len(failed) == 1
    assert failed[0]["error_type"] == "RuntimeError"
    assert failed[0]["execution"]["seconds"] >= 0
    assert len(backend.calls) == 9
    backend.fail_practice = False
    result = run()
    assert result["approved"] is True
    assert len(backend.calls) == 11
    assert {item["resourceType"] for item in result["teachingReview"]} == set(resource_bundles.GENERATION_RESOURCE_TYPES)
    assert len(result["sectionReviews"]) == 10
    # Only code, its actual training link and final connections need review.
    next(item for item in candidates if item["type"] == "code_sandbox")["version_id"] = "code-v2"
    next(item for item in candidates if item['type']=='training_task')['dependency_bindings'][0]['version_id']='code-v2'
    assert run()["approved"] is True
    assert len(backend.calls) == 14


@pytest.mark.parametrize("initial_budget", [32768, 65536])
def test_resource_output_exhaustion_uses_one_larger_retry_then_stops(initial_budget):
    class Backend:
        max_tokens = initial_budget

        def __init__(self):
            self.calls = []

        async def generate(self, system_prompt, user_prompt, *, role):
            self.calls.append(self.max_tokens)
            if len(self.calls) == 1:
                raise resource_bundles.ModelOutputLimitError("output exhausted")
            return json.dumps({"summary": "复述数组索引", "narrative": "用一个例子解释行列索引。"})

    backend = Backend()
    call = resource_bundles._real_model_payload_async(
        backend, resource_type="feynman", item={}, manifest={}, source_snapshots=[],
    )
    if initial_budget == 32768:
        result = asyncio.run(call)
        assert result["summary"] == "复述数组索引"
        assert backend.calls == [32768, 65536]
        assert backend.max_tokens == initial_budget
    else:
        with pytest.raises(resource_bundles.ResourceBundleError):
            asyncio.run(call)
        assert backend.calls == [65536]


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


def test_python_source_storage_does_not_become_rag_exercise():
    sources = [{"quote": "Variables provide storage for values in a Python program."}]
    assert resource_bundles._practical_focus("Python 机器学习编程基础", sources) == "Python 数据类型、控制流程、函数与数据处理验证"
    assert "检索" not in resource_bundles._practical_focus("变量", sources)
    assert resource_bundles._practical_focus("知识问答", [{"quote": "RAG retrieval"}]) == "知识问答的实践与结果解释"
    assert "检索" in resource_bundles._practical_focus("", [{"quote": "RAG retrieval"}])


@pytest.mark.parametrize('topic', ['监督学习的输入、标签与预测任务', '样本、特征与标签', '摄影曝光', '现金流量表'])
def test_named_topic_is_not_replaced_by_other_chapters_in_source(topic):
    sources = [{'quote': '全书还讨论RAG检索、梯度优化、分类和回归。'}]
    assert resource_bundles._practical_focus(topic, sources) == topic + '的实践与结果解释'


@pytest.mark.parametrize("kind", ["handout", "mind_map", "training_task", "feynman", "interactive_model"])
def test_live_content_is_not_rewritten_with_off_topic_demo_variants(kind):
    template = resource_bundles._interactive_template_for_knowledge_point("Python 机器学习编程基础")
    raw = asyncio.run(_SupervisorBackend().generate("", json.dumps({
        "interactive_template": resource_bundles._interactive_template_directory(template),
    }), role="resource_generator"))
    payload = json.loads(raw)
    if kind == "handout":
        for question in payload["quizQuestions"]:
            question["options"] = dict(zip("ABCD", question["options"]))
    payload["chart"]["series"] = resource_bundles._interactive_template_directory(template)["metrics"]
    payload["narrative"] = "用列表和函数过滤空值，再逐条计算读数。"
    payload["prerequisites"] = ["能读取Python列表并调用简单函数。"]
    payload["observationPrompt"] = "比较模拟条件下的处理趋势，不能当作实测性能。"
    payload["completionRule"] = "保存两组模拟参数并解释吞吐量趋势。"
    for step, title in zip(payload["practiceSteps"], ["读取列表", "检查空值", "调用函数", "核对结果"]):
        step["title"] = title
    payload["practiceSteps"][-1]["expectedResult"] = "len(scores)=9"
    content = resource_bundles._llm_resource_content(
        resource_type=kind, item={"title": "Python 基础"},
        manifest={"course_id": "course-test", "knowledge_point_id": "kp-python", "context": {
            "knowledge_point_title": "Python 机器学习编程基础",
            "profile_adaptation_plan": {"content_focus": "过拟合与欠拟合", "difficulty_label": "基础应用"},
        }},
        source_snapshots=[{"source_ref_id": "ref-python", "title": "Python", "quote": "Python lists and functions"}],
        linked_resource_ids=[], llm_payload=payload,
    )
    if kind == "feynman":
        assert "过拟合" not in content
        assert payload["narrative"] in content
        return
    result = json.loads(content)
    prose = {"handout": lambda: result["concepts"][0]["explanation"],
             "mind_map": lambda: result["nodes"][0]["summary"],
             "training_task": lambda: result["objective"],
             "interactive_model": lambda: result["summary"]}[kind]()
    assert "过拟合" not in prose
    if kind == "mind_map":
        assert all(node["masteryBand"] == "unknown" for node in result["nodes"])
    if kind == "training_task":
        assert result["prerequisites"] == payload["prerequisites"]
        assert result["prerequisites"] != [payload["learningGoal"]]
    if kind == "handout":
        assert result["miniQuiz"][0]["options"] == list(payload["quizQuestions"][0]["options"].values())
        assert result["figures"][0]["content"] == "读取列表 → 检查空值 → 调用函数 → 核对结果"
        assert "梯度" not in result["figures"][0]["content"]
        assert result["miniQuiz"][0]["question"] == payload["quizQuestions"][0]["prompt"]
    if kind == "interactive_model":
        assert result["completionRule"] == payload["completionRule"]
        assert result["observationPrompt"]["completionRule"] == payload["completionRule"]
        assert "scores" not in result["completionRule"]
