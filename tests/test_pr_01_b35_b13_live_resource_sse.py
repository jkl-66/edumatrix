from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

import pytest

from fastapi.testclient import TestClient

import stream_api
from app.auth import get_current_user
from app.chat_api import MessageInput, create_message_pair, execute_resource_chat_run
from app.competition_demo_seed import seed_competition_demo
from app.database import DBChatConversation, DBChatMessage, DBProfileSnapshot, DBSourceRef, DBUser
from app.main import app
from app.resource_bundles import GENERATION_RESOURCE_TYPES, retry_generation_item
from tests.test_f6_t03_code_sandbox_resource import _session


@pytest.fixture(autouse=True)
def _fake_web_video_search(monkeypatch):
    async def fake_search(query, max_results=5):
        return [{
            "title": "课程视频候选",
            "url": "https://www.bilibili.com/video/BV1sse123",
            "source": "B站视频",
            "description": "测试用真实网页来源",
        }]

    import web_search_api
    monkeypatch.setattr(web_search_api, "search_videos", fake_search)


def _events(text: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    event_name = ""
    for line in text.splitlines():
        if line.startswith("event: "):
            event_name = line[7:]
        elif line.startswith("data: "):
            events.append((event_name, json.loads(line[6:])))
    return events


class _SlowResourceBackend:
    model = "deepseek-v4-flash"
    provider = "openai"

    def __init__(self, *, fail_types: set[str] | None = None, delay: float = 0.01) -> None:
        self.fail_types = set(fail_types or ())
        self.delay = delay
        self.planner_started = threading.Event()
        self.roles: list[str] = []

    async def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        self.roles.append(role)
        if role == "resource_planner":
            self.planner_started.set()
        await asyncio.sleep(self.delay)
        if role == "resource_planner":
            return json.dumps({
                "summary": "B13 共享语义计划",
                "plan": "依据冻结课程来源生成并审核资源。",
                "resourceBriefs": [],
            }, ensure_ascii=False)
        if role == "resource_reviewer":
            return json.dumps({
                "approved": True,
                "summary": "B13 审核通过",
                "findings": [],
                "rejectedTypes": [],
            }, ensure_ascii=False)
        resource_type = next(
            (value for value in GENERATION_RESOURCE_TYPES if value in user_prompt),
            "handout",
        )
        if resource_type in self.fail_types:
            raise RuntimeError(f"B13 provider failure: {resource_type}")
        return json.dumps({
            "summary": f"B13 {resource_type} 候选摘要",
            "narrative": f"B13 {resource_type} 模型正文，依据冻结课程来源生成。",
            "learningGoal": "完成 B13 资源目标",
            "starterCode": "print('b13')\n",
            "requiredChecks": [
                {"id": "stdout", "label": "输出", "kind": "stdout_contains", "expectedText": "b13"},
            ],
            "environment": ["Python 3"],
            "data": ["B13 课程示例数据"],
            "parameters": [{"key": "learning_rate", "label": "学习率", "kind": "float", "minimum": 0.0, "maximum": 1.0, "step": 0.1, "default": 0.1, "description": "控制每次参数更新幅度。"}],
            "constraints": [{"id": "range", "title": "范围约束", "description": "学习率必须大于 0 且不超过 1。"}],
            "dataset": {"id": "b13-dataset", "title": "课程示例数据", "summary": "用于实时资源测试的课程示例数据。", "sampleCount": 1},
            "chart": {"kind": "line", "xAxisLabel": "训练步", "yAxisLabel": "损失", "series": [{"key": "loss", "label": "损失", "unit": "", "higherIsBetter": False}]},
            "practiceSteps": [
                {"title": "输入", "instruction": "检查输入", "expectedResult": "字段", "errorGuidance": "回查来源"},
                {"title": "机制", "instruction": "说明机制", "expectedResult": "机制", "errorGuidance": "检查边界"},
                {"title": "运行", "instruction": "运行实验", "expectedResult": "输出", "errorGuidance": "保留错误"},
                {"title": "评估", "instruction": "核对结果", "expectedResult": "结论", "errorGuidance": "回查证据"},
            ],
            "quizQuestions": [
                {"prompt": "B13 题目", "options": ["A", "B", "C", "D"], "answer": "A", "explanation": "B13 解析", "bloom": "remember", "difficulty": 0.3}
            ],
            "slides": [
                {"layout": "title", "title": "B13 课程主题", "subtitle": "实时模型"},
                {"layout": "content", "title": "机制", "body": "依据冻结来源解释机制。", "speakerNotes": "回查课程来源。"},
            ],
        }, ensure_ascii=False)


def _create_resource_message(session, learner: DBUser, source_id: str, key: str) -> tuple[str, str]:
    profile = session.query(DBProfileSnapshot).filter_by(owner_public_id=learner.public_id).first()
    conversation = DBChatConversation(
        owner_public_id=learner.public_id,
        course_id="demo-course-rag-trust-v1",
        title="B13 canonical resource SSE",
    )
    session.add(conversation)
    session.commit()
    pair = create_message_pair(
        session,
        learner,
        conversation.id,
        MessageInput(
            content="请生成 B13 资源包",
            idempotency_key=key,
            intent="resource_generation",
            resource_types=["handout", "code_sandbox", "video"],
            context_refs=[{
                "courseId": "demo-course-rag-trust-v1",
                "knowledgePointId": "demo-kp-07",
                "sourceRefId": source_id,
            }],
        ),
    )
    return pair["userMessage"]["id"], pair["assistantMessage"]["id"]


def test_canonical_resource_sse_streams_real_events_and_replays_same_run(monkeypatch) -> None:
    backend = _SlowResourceBackend()
    monkeypatch.setattr("app.resource_bundles._real_model_backend", lambda: backend)
    monkeypatch.setattr(stream_api, "build_swarm_from_headers", lambda _headers: object())
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        source = session.get(DBSourceRef, "demo-ref-07")
        user_id, assistant_id = _create_resource_message(session, learner, source.id, "b13-live-sse-001")

        async def threaded_db_op(operation, *args, **kwargs):
            return await asyncio.to_thread(operation, session, *args, **kwargs)

        monkeypatch.setattr(stream_api, "run_db_op", threaded_db_op)
        app.dependency_overrides[get_current_user] = lambda: learner
        try:
            response = TestClient(app).post(
                "/api/stream/chat",
                json={"user_message_id": user_id, "message": "ignored"},
            )
            assert response.status_code == 200, response.text
            events = _events(response.text)
            assert events
            complete = next(data for name, data in events if name == "complete")
            run_events = complete["run_events"]
            event_types = [event["eventType"] for event in run_events]
            assert "run.started" in event_types
            assert "context.frozen" in event_types
            assert "stage.started" in event_types
            assert "resource.item.started" in event_types
            assert "resource.item.completed" in event_types
            assert "review_gate.started" in event_types
            assert "review_gate.passed" in event_types
            assert "publish.completed" in event_types
            assert "run.completed" in event_types
            assert all(event["runId"] == complete["run_id"] for event in run_events)
            assert all(
                run_events.index(start) < run_events.index(done)
                for resource_type in {"handout", "code_sandbox", "video"}
                for start in run_events
                if start["eventType"] == "resource.item.started" and resource_type in start.get("summary", "")
                for done in run_events
                if done["eventType"] == "resource.item.completed" and resource_type in done.get("summary", "")
            )
            streamed_event_names = [name for name, data in events if data.get("event")]
            assert "resource.item.started" in streamed_event_names
            assert "resource.item.completed" in streamed_event_names
            assert streamed_event_names.index("review_gate.passed") < streamed_event_names.index("publish.completed")

            replay = TestClient(app).post(
                "/api/stream/chat",
                json={"user_message_id": user_id, "message": "ignored again"},
            )
            assert replay.status_code == 200, replay.text
            replay_complete = next(data for name, data in _events(replay.text) if name == "complete")
            assert replay_complete["replayed"] is True
            assert replay_complete["run_id"] == complete["run_id"]
            assert replay_complete["run_events"] == run_events
        finally:
            app.dependency_overrides.pop(get_current_user, None)
    finally:
        session.close()
        engine.dispose()


def test_partial_resource_failure_retries_only_failed_item(monkeypatch) -> None:
    backend = _SlowResourceBackend(fail_types={"video"})
    monkeypatch.setattr("app.resource_bundles._real_model_backend", lambda: backend)
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        source = session.get(DBSourceRef, "demo-ref-07")
        _user_id, assistant_id = _create_resource_message(session, learner, source.id, "b13-partial-001")
        first = execute_resource_chat_run(session, learner, assistant_id)
        assert first["job"]["status"] == "partial_success"
        first_items = {item["type"]: item for item in first["job"]["items"]}
        assert first_items["video"]["state"] == "failed"
        assert first_items["handout"]["state"] == "succeeded"
        calls_before_retry = list(backend.roles)

        retry_generation_item(session, learner, first["job"]["job_id"], "video")
        backend.fail_types.clear()
        second = execute_resource_chat_run(session, learner, assistant_id)
        assert second["job"]["status"] == "succeeded"
        assert all(item["state"] == "succeeded" for item in second["job"]["items"])
        # Planner and already successful resource items are not regenerated.
        assert backend.roles.count("resource_planner") == calls_before_retry.count("resource_planner")
        assert backend.roles.count("resource_reviewer") == calls_before_retry.count("resource_reviewer") + 1
        assert backend.roles.count("resource_generator") == calls_before_retry.count("resource_generator") + 1
        assert next(item for item in second["job"]["items"] if item["type"] == "video")["attempt_history"][-1]["attempt"] == 2
        assert any(event["eventType"] == "publish.completed" for event in second["run_events"])
    finally:
        session.close()
        engine.dispose()


def test_disconnect_keeps_persisted_resource_run_recoverable(monkeypatch) -> None:
    backend = _SlowResourceBackend(delay=0.05)
    monkeypatch.setattr("app.resource_bundles._real_model_backend", lambda: backend)
    monkeypatch.setattr(stream_api, "build_swarm_from_headers", lambda _headers: object())
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        source = session.get(DBSourceRef, "demo-ref-07")
        user_id, assistant_id = _create_resource_message(session, learner, source.id, "b13-disconnect-001")

        async def threaded_db_op(operation, *args, **kwargs):
            return await asyncio.to_thread(operation, session, *args, **kwargs)

        monkeypatch.setattr(stream_api, "run_db_op", threaded_db_op)

        class _Request:
            headers: dict[str, str] = {}

            def __init__(self, payload: dict[str, Any]) -> None:
                self.payload = payload

            async def json(self) -> dict[str, Any]:
                return self.payload

        async def interrupt_stream() -> None:
            response = await stream_api.stream_chat(
                _Request({"user_message_id": user_id, "message": "ignored"}),
                learner,
            )
            iterator = response.body_iterator
            first = await anext(iterator)
            assert "progress" in first
            second = await anext(iterator)
            assert "stage.started" in second
            await asyncio.to_thread(backend.planner_started.wait, 2)
            assert backend.planner_started.is_set()
            await iterator.aclose()
            await asyncio.sleep(1.5)

        asyncio.run(interrupt_stream())
        # The resource task is independent of the SSE iterator and commits its
        # state, so a later connection can replay the terminal run.
        session.expire_all()
        row = session.get(DBChatMessage, assistant_id)
        assert row.status == "completed", (row.status, backend.roles, row.error_code, row.error_message)
        assert row.resource_links
        assert row.stream_checkpoint.get("runEvents")

        app.dependency_overrides[get_current_user] = lambda: learner
        try:
            replay = TestClient(app).post(
                "/api/stream/chat",
                json={"user_message_id": user_id, "message": "reconnect"},
            )
            assert replay.status_code == 200, replay.text
            replay_complete = next(data for name, data in _events(replay.text) if name == "complete")
            assert replay_complete["replayed"] is True
            assert replay_complete["run_events"] == row.stream_checkpoint["runEvents"]
        finally:
            app.dependency_overrides.pop(get_current_user, None)
    finally:
        session.close()
        engine.dispose()
