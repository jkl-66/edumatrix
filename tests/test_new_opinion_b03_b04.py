from __future__ import annotations

from pathlib import Path
import asyncio
import inspect
import json

import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, DBCourse, DBLearningPath, DBPathNode, DBPlanDraft, DBPlanVersion, DBUser
from app.m5_learning import multi_course_schedule, today_work_items
from app.resource_bundles import (
    ResourceBundleError,
    _real_model_payload_async,
    _live_video_recommendations,
    _llm_resource_content,
)
from app.chat_api import _resource_links_from_job
from app.feynman import FeynmanContextSnapshot, FeynmanState, SourceSnapshot, _live_answer_question, _live_evaluate
import app.feynman as feynman_module


ROOT = Path(__file__).resolve().parents[1]


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def _path(db, owner: str, course_id: str, prefix: str) -> None:
    db.add(DBCourse(
        id=course_id,
        owner_public_id=owner,
        version="1",
        title=f"课程 {prefix}",
        subject="测试课程",
        manifest_version="1",
        status="published",
        visibility="private",
    ))
    plan = DBPlanDraft(
        id=f"plan-{prefix}", owner_public_id=owner, course_id=course_id,
        title=f"计划 {prefix}", status="confirmed", idempotency_key=f"idem-{prefix}",
    )
    db.add(plan)
    db.flush()
    version = DBPlanVersion(
        id=f"version-{prefix}", plan_draft_id=plan.id, version_number=1,
        content={"schema_version": "m5.plan.v1"}, content_hash=f"hash-{prefix}",
    )
    db.add(version)
    db.flush()
    plan.current_version_id = version.id
    plan.confirmed_version_id = version.id
    path = DBLearningPath(
        id=f"path-{prefix}", owner_public_id=owner, course_id=course_id,
        source_plan_version_id=version.id, status="active",
    )
    db.add(path)
    db.flush()
    db.add_all([
        DBPathNode(
            id=f"node-{prefix}-1", learning_path_id=path.id, node_key=f"{prefix}-1",
            sequence=1, node_type="workspace_action", title=f"{prefix} 第一项",
            status="pending", prerequisites=[], estimate_min_minutes=5, estimate_max_minutes=10,
        ),
        DBPathNode(
            id=f"node-{prefix}-2", learning_path_id=path.id, node_key=f"{prefix}-2",
            sequence=2, node_type="workspace_action", title=f"{prefix} 第二项",
            status="pending", prerequisites=[f"{prefix}-1"], estimate_min_minutes=5, estimate_max_minutes=10,
        ),
    ])


def test_today_items_round_robin_all_active_courses_before_limit():
    engine, db = _session()
    try:
        owner = "today-owner"
        db.add(DBUser(public_id=owner, username=owner, hashed_password="hash", role="student", is_active=True))
        _path(db, owner, "course-a", "a")
        _path(db, owner, "course-b", "b")
        db.commit()

        items = today_work_items(db, owner_public_id=owner, limit=2)

        assert len(items) == 2
        assert {item["course_id"] for item in items} == {"course-a", "course-b"}
        assert {item["path_id"] for item in items} == {"path-a", "path-b"}
        assert all(item["course_title"] for item in items)
    finally:
        db.close()
        engine.dispose()


def test_today_items_filters_course_and_excludes_paused_path():
    engine, db = _session()
    try:
        owner = "today-filter-owner"
        db.add(DBUser(public_id=owner, username=owner, hashed_password="hash", role="student", is_active=True))
        _path(db, owner, "course-a", "a")
        _path(db, owner, "course-b", "b")
        db.commit()

        selected = today_work_items(db, owner_public_id=owner, course_id="course-b", limit=10)
        assert selected and {item["course_id"] for item in selected} == {"course-b"}

        db.query(DBLearningPath).filter_by(id="path-b").one().status = "paused"
        db.commit()
        active = today_work_items(db, owner_public_id=owner, limit=10)
        assert active and {item["course_id"] for item in active} == {"course-a"}
    finally:
        db.close()
        engine.dispose()


def test_schedule_marks_unblocked_today_nodes_as_learnable_not_locked():
    engine, db = _session()
    try:
        owner = "path-state-owner"
        db.add(DBUser(public_id=owner, username=owner, hashed_password="hash", role="student", is_active=True))
        _path(db, owner, "course-a", "a")
        db.commit()

        result = multi_course_schedule(db, owner_public_id=owner)
        course = result["courses"][0]
        root = next(item for item in course["nodes"] if item["node_key"] == "a-1")
        blocked = next(item for item in course["nodes"] if item["node_key"] == "a-2")

        assert root["status"] == "pending"
        assert blocked["status"] == "pending"
        assert result["selected"]["tasks"][0]["status"] == "in_progress"
        assert result["selected"]["tasks"][0]["scheduled_day"] == 1
    finally:
        db.close()
        engine.dispose()


def test_learning_workspace_projects_course_group_and_empty_states():
    source = (ROOT / "frontend/src/views/LearningWorkspace.vue").read_text(encoding="utf-8")
    assert "正在学习的课程" in source
    assert "today-learning-courses" in source
    assert "今日学习" in source
    assert "today-learning-empty" in source


def _video_manifest():
    return {
        "user_instruction": "推荐当前知识点的公开视频",
        "context": {"course_title": "机器学习导论", "knowledge_point_title": "梯度下降"},
        "input_snapshot": {
            "source_snapshots": {
                "video": [{"source_ref_id": "ref-gradient"}],
            },
        },
    }


def test_video_recommendations_only_publish_real_https_web_results(monkeypatch):
    async def fake_search(query, max_results=5):
        assert "梯度下降" in query
        return [
            {"title": "B站梯度下降讲解", "url": "https://www.bilibili.com/video/BV123", "source": "B站视频", "description": "真实网页候选"},
            {"title": "本地占位", "url": "/api/v1/animations/video/demo.mp4", "source": "本地动画"},
            {"title": "无效链接", "url": "", "source": "网络视频"},
        ]

    import web_search_api
    monkeypatch.setattr(web_search_api, "search_videos", fake_search)
    recommendations = asyncio.run(_live_video_recommendations(manifest=_video_manifest()))
    assert len(recommendations) == 1
    item = recommendations[0]
    assert item["sourceKind"] == "external_url"
    assert item["availability"] == "external_only"
    assert item["url"].startswith("https://")
    assert item["sourceRefIds"] == ["ref-gradient"]

    payload = {
        "summary": "依据课程来源整理的视频学习建议",
        "learningGoal": "理解梯度下降的更新机制",
        "narrative": "先观察梯度，再理解参数如何沿下降方向更新。",
    }
    content = _llm_resource_content(
        resource_type="video",
        item={"title": "梯度下降视频推荐"},
        manifest=_video_manifest(),
        source_snapshots=[{"source_ref_id": "ref-gradient", "title": "教材", "location_label": "第1节", "quote": "梯度下降"}],
        linked_resource_ids=[],
        llm_payload=payload,
        video_recommendations=recommendations,
    )
    structured = json.loads(content)
    assert structured["recommendations"][0]["url"] == "https://www.bilibili.com/video/BV123"


def test_video_generation_fails_honestly_when_network_has_no_candidates(monkeypatch):
    async def empty_search(query, max_results=5):
        return []

    import web_search_api
    monkeypatch.setattr(web_search_api, "search_videos", empty_search)
    with pytest.raises(ResourceBundleError) as exc_info:
        asyncio.run(_live_video_recommendations(manifest=_video_manifest()))
    assert exc_info.value.code == "resource_generation.video_search_empty"


def test_video_recommendations_skip_unrelated_search_hits_and_try_next_query(monkeypatch):
    calls = []

    async def search_with_unrelated_first(query, max_results=5):
        calls.append(query)
        if len(calls) == 1:
            return [{
                "title": "有机化学基础",
                "url": "https://www.bilibili.com/video/BVorganic",
                "source": "B站视频",
                "snippet": "有机化学反应入门",
            }]
        return [{
            "title": "梯度下降讲解",
            "url": "https://www.bilibili.com/video/BVgradient",
            "source": "B站视频",
            "snippet": "梯度下降与学习率",
        }]

    import web_search_api
    monkeypatch.setattr(web_search_api, "search_videos", search_with_unrelated_first)
    recommendations = asyncio.run(_live_video_recommendations(manifest=_video_manifest()))

    assert len(calls) == 2
    assert recommendations[0]["title"] == "梯度下降讲解"


def test_youtube_search_parser_keeps_only_concrete_video_pages():
    import web_search_api

    html = (
        '{"videoRenderer":{"videoId":"ABCDEFGHIJK","thumbnail":{},'
        '"title":{"runs":[{"text":"梯度下降\\u8bb2\\u89e3"}]}}}'
        '{"videoRenderer":{"videoId":"ABCDEFGHIJK","title":{"runs":[{"text":"重复结果"}]}}}'
        '{"videoRenderer":{"videoId":"LMNOPQRSTUV","title":{"runs":[{"text":"优化算法边界"}]}}}'
    )
    results = web_search_api._parse_youtube_search_html(html, max_results=5)

    assert results == [
        {
            "title": "梯度下降讲解",
            "url": "https://www.youtube.com/watch?v=ABCDEFGHIJK",
            "snippet": "梯度下降讲解",
        },
        {
            "title": "优化算法边界",
            "url": "https://www.youtube.com/watch?v=LMNOPQRSTUV",
            "snippet": "优化算法边界",
        },
    ]


def test_bilibili_embed_conversion_returns_publishable_https_url():
    import web_search_api

    assert web_search_api.to_embedded_player_url(
        "https://www.bilibili.com/video/BV1AbC2DeFgH"
    ) == "https://player.bilibili.com/player.html?bvid=BV1AbC2DeFgH&high_quality=1&as_wide=1"


def test_live_resource_retries_once_when_model_returns_malformed_json():
    calls = []

    class FlakyBackend:
        async def generate(self, system, user, *, role):
            calls.append(system)
            if len(calls) == 1:
                return '{"summary":"截断'
            return json.dumps({
                "summary": "模型摘要",
                "learningGoal": "理解当前知识点",
                "narrative": "依据冻结课程来源生成的正文。",
            }, ensure_ascii=False)

    payload = asyncio.run(_real_model_payload_async(
        FlakyBackend(),
        resource_type="feynman",
        item={"title": "费曼复述"},
        manifest=_video_manifest(),
        source_snapshots=[{
            "source_ref_id": "ref-gradient",
            "title": "课程教材",
            "location_label": "第 1 节",
            "quote": "梯度下降沿负梯度方向更新参数。",
        }],
    ))

    assert payload["summary"] == "模型摘要"
    assert len(calls) == 2
    assert "JSON 无法解析" in calls[1]


def test_live_resource_retries_missing_structured_fields_without_local_defaults():
    steps = [
        {"title": f"步骤 {index}", "instruction": "按课程来源执行本步骤。", "expectedResult": "得到可核对的结果。", "errorGuidance": "回到来源检查前提。"}
        for index in range(1, 5)
    ]
    common = {"summary": "模型摘要", "narrative": "依据冻结课程来源生成的正文。", "practiceSteps": steps}
    cases = {
        "handout": (
            {**common},
            {**common, "starterCode": "print('course evidence')"},
        ),
        "mind_map": (
            {**common, "practiceSteps": []},
            {**common},
        ),
        "training_task": (
            {**common, "environment": [], "data": []},
            {**common, "environment": ["Python"], "data": ["课程数据"]},
        ),
        "code_sandbox": (
            {**common, "starterCode": "print('course evidence')", "requiredChecks": []},
            {**common, "starterCode": "print('course evidence')", "requiredChecks": [{"id": "stdout", "label": "输出", "kind": "stdout_contains", "expectedText": "course evidence"}]},
        ),
        "interactive_model": (
            {**common},
            {**common, "parameters": [{"key": "weight", "label": "权重", "kind": "float", "minimum": 0.0, "maximum": 1.0, "step": 0.1, "default": 0.1, "description": "观察权重变化。"}], "constraints": [{"id": "range", "title": "范围", "description": "权重保持在 0 到 1。"}], "dataset": {"id": "dataset", "title": "课程数据", "summary": "用于观察参数变化。", "sampleCount": 1}, "chart": {"kind": "line", "xAxisLabel": "步骤", "yAxisLabel": "损失", "series": [{"key": "loss", "label": "损失", "higherIsBetter": False}]}, "observationPrompt": "比较两组结果并解释差异。"},
        ),
        "deck": (
            {**common, "slides": []},
            {**common, "slides": [{"layout": "title", "title": "课程主题"}, {"layout": "content", "title": "机制", "body": "依据来源解释机制。"}]},
        ),
    }

    for resource_type, (invalid, corrected) in cases.items():
        calls = []

        class Backend:
            async def generate(self, system, user, *, role):
                calls.append((system, role))
                return json.dumps(invalid if len(calls) == 1 else corrected, ensure_ascii=False)

        payload = asyncio.run(_real_model_payload_async(
            Backend(),
            resource_type=resource_type,
            item={"title": resource_type},
            manifest=_video_manifest(),
            source_snapshots=[{"source_ref_id": "ref-gradient", "title": "课程教材", "location_label": "第1节", "quote": "梯度下降"}],
        ))
        assert len(calls) == 2, resource_type
        assert payload == corrected


def test_live_resource_content_rejects_missing_structured_fields_instead_of_fabricating():
    manifest = _video_manifest()
    sources = [{"source_ref_id": "ref-gradient", "title": "课程教材", "location_label": "第1节", "quote": "梯度下降"}]
    common = {"summary": "模型摘要", "narrative": "依据冻结课程来源生成的正文。", "learningGoal": "理解当前知识点", "practiceSteps": [
        {"title": f"步骤 {index}", "instruction": "按课程来源执行本步骤。", "expectedResult": "得到可核对的结果。", "errorGuidance": "回到来源检查前提。"}
        for index in range(1, 5)
    ]}
    missing_payloads = {
        "training_task": {**common, "environment": [], "data": []},
        "code_sandbox": {**common, "starterCode": "print('course evidence')", "requiredChecks": []},
        "interactive_model": {**common},
        "deck": {**common, "slides": []},
    }
    for resource_type, payload in missing_payloads.items():
        with pytest.raises(ResourceBundleError) as exc_info:
            _llm_resource_content(
                resource_type=resource_type,
                item={"title": resource_type},
                manifest=manifest,
                source_snapshots=sources,
                linked_resource_ids=[],
                llm_payload=payload,
            )
        assert exc_info.value.code == "resource_generation.model_output_invalid", resource_type


def test_feynman_live_evaluation_and_question_use_deepseek_max(monkeypatch):
    calls = []
    backend_source = inspect.getsource(feynman_module._live_model_backend)

    class FakeBackend:
        async def generate(self, system, user, *, role):
            calls.append((system, json.loads(user), role))
            if role == "feynman_tutor":
                return json.dumps({"answer": "依据课程来源，先确认前提，再解释机制和边界。"}, ensure_ascii=False)
            return json.dumps({
                "score": 82,
                "dimensions": [
                    {"key": "core_meaning", "label": "核心含义", "score": 21, "evidence": "能够说明概念用途。"},
                    {"key": "mechanism", "label": "机制与步骤", "score": 21, "evidence": "说明了主要步骤。"},
                    {"key": "conditions", "label": "成立条件", "score": 16, "evidence": "提到成立前提。"},
                    {"key": "example", "label": "适用例子", "score": 12, "evidence": "给出了课程场景。"},
                    {"key": "boundary", "label": "边界与反例", "score": 12, "evidence": "指出了限制。"},
                ],
                "strengths": ["机制表达清楚"],
                "gaps": ["还可补充边界条件"],
                "omissions": [],
            }, ensure_ascii=False)

    monkeypatch.setattr(feynman_module, "_live_model_backend", lambda: FakeBackend())
    context = FeynmanContextSnapshot(
        course_id="course-live", course_title="机器学习导论",
        knowledge_point_id="kp-live", knowledge_point_title="梯度下降",
        source_ref_ids=("ref-live",), context_fingerprint="fingerprint-live", generation_mode="llm",
    )
    state = FeynmanState(
        session_id="session-live", owner_public_id="owner-live",
        source_resource_id="resource-live", source_resource_version_id="version-live",
        source_resource_content_sha256="a" * 64, title="梯度下降 · 费曼复述",
        course_id="course-live", course_title="机器学习导论",
        knowledge_point_id="kp-live", knowledge_point_title="梯度下降",
        source_refs=(SourceSnapshot(source_ref_id="ref-live", title="课程教材", location_label="第1节", quote="梯度下降沿负梯度方向更新参数。"),),
        task_prompt="解释梯度下降", adaptation_note="关注成立条件",
        context_snapshot=context,
    )
    evaluation = _live_evaluate("梯度下降通过梯度更新参数，并说明条件、例子和边界。", state, round_number=1)
    assert evaluation.evaluation_mode == "llm"
    assert evaluation.score == 82
    answered = _live_answer_question(state.model_copy(update={"round1_evaluation": evaluation}), "为什么要沿负梯度方向更新？")
    assert answered.answer_mode == "llm_grounded"
    assert answered.source_ref_ids == ("ref-live",)
    assert [call[2] for call in calls] == ["feynman_evaluator", "feynman_tutor"]
    assert "deepseek-v4-flash" in backend_source
    assert "reasoning_effort=\"max\"" in backend_source
    assert "allow_fallback=False" in backend_source


def test_resource_center_generation_requires_selected_course_point_and_routes_context():
    source = (ROOT / "frontend/src/views/ResourceCenter.vue").read_text(encoding="utf-8")
    assert "选择课程、知识点和辅助要求" in source
    assert "path: '/chat'" in source
    assert "intent: 'resource_generation'" in source
    assert "knowledge_point_id: pointId" in source
    assert "source_ref_ids: sourceIds.length ? sourceIds.join(',') : undefined" in source
    assert "generationContext.value?.source_ref_ids" in source
    assert "RAG 应用开发与负责任评测实训" not in source


def test_partial_success_keeps_successful_resource_subspace_links():
    links = _resource_links_from_job({
        "job_id": "job-partial-001",
        "status": "partial_success",
        "items": [
            {
                "type": "handout",
                "title": "个性化讲义",
                "state": "succeeded",
                "resource": {
                    "resource_id": "artifact-handout-001",
                    "route": "/workspace/resources/handouts/artifact-handout-001",
                    "version": {"id": "version-handout-001"},
                },
            },
            {
                "type": "video",
                "title": "视频推荐",
                "state": "failed",
                "resource": None,
            },
        ],
    })
    successful, failed = links
    assert successful["status"] == "completed"
    assert successful["route"] == "/workspace/resources/handouts/artifact-handout-001"
    assert successful["resourceId"] == "artifact-handout-001"
    assert failed["status"] == "failed"
    assert failed["route"] == "/workspace/resources/bundles/job-partial-001"


def test_resource_floating_qa_is_in_resource_and_has_failure_retry():
    floating = (ROOT / "frontend/src/components/ResourceFloatingQa.vue").read_text(encoding="utf-8")
    quiz = (ROOT / "frontend/src/views/QuizResourceWorkspace.vue").read_text(encoding="utf-8")
    for text in (
        "useChatStore",
        "intent: 'course_qa'",
        "resourceId",
        "sourceRefIds",
        "AgentTimeline",
        "runEvents",
        "claims",
        "sourceRefs",
        "chatStore.continueResponse",
        "chatStore.retryPendingMessage",
        "重试",
    ):
        assert text in floating
    assert "ResourceFloatingQa" in quiz
    assert "qaOpen" in quiz
    assert "资源内提问" in quiz
    assert ":resource-id=\"resourceId\"" in quiz
    assert ":source-ref-ids=\"qaSourceRefIds\"" in quiz
    assert ":run-events=\"runEvents\"" in floating
    assert ":claims=\"claims\"" in floating
    assert ":source-refs=\"sourceRefs\"" in floating
