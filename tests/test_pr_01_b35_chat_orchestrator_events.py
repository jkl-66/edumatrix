from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.agent_audit import (
    PublicRunEvent,
    append_public_run_event,
    build_chat_agent_audit,
)
from app.main import app
import stream_api
from tests.api_test_helpers import auth_headers


def test_stream_metrics_report_configured_model_identity() -> None:
    source = Path("stream_api.py").read_text(encoding="utf-8")
    assert '"model": "EduMatrix Swarm 1+3+5"' not in source
    assert '"model": str(model or CONFIG.llm_model or "unknown")' in source


def _key(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _events(text: str) -> list[tuple[str, dict]]:
    result: list[tuple[str, dict]] = []
    event_name = ""
    for line in text.splitlines():
        if line.startswith("event: "):
            event_name = line[7:]
        elif line.startswith("data: "):
            result.append((event_name, json.loads(line[6:])))
    return result


def test_public_run_event_projection_is_allow_listed_sanitized_and_idempotent() -> None:
    checkpoint = append_public_run_event(
        {},
        run_id="chat-run-events",
        event_type="run.started",
        public_status="queued",
        owner="Chat Orchestrator",
        summary="accepted system_prompt=private",
        input_refs={"message": "chat:1", "system_prompt": "hidden"},
        progress=0.0,
    )
    checkpoint = append_public_run_event(
        checkpoint,
        run_id="chat-run-events",
        event_type="context.frozen",
        stage_id="context",
        public_status="completed",
        owner="Context Builder",
        summary="课程、来源和附件已经冻结",
        output_refs=["context:1"],
        progress=1.0,
    )
    duplicate = append_public_run_event(
        checkpoint,
        run_id="chat-run-events",
        event_type="context.frozen",
        stage_id="context",
        public_status="completed",
        owner="Context Builder",
        summary="重复事件不应追加",
        progress=1.0,
    )

    events = duplicate["runEvents"]
    assert duplicate["runId"] == "chat-run-events"
    assert len(events) == 2
    assert [item["eventType"] for item in events] == ["run.started", "context.frozen"]
    assert events[0]["inputRefs"] == ["chat:1"]
    assert PublicRunEvent.model_validate(events[1]).event_type == "context.frozen"
    assert "system_prompt" not in json.dumps(events, ensure_ascii=False).lower()


def test_chat_audit_and_message_projection_share_the_same_run_events() -> None:
    events = [
        {
            "eventId": "chat-run-1:event:1",
            "runId": "chat-run-1",
            "eventType": "run.started",
            "publicStatus": "queued",
            "owner": "Chat Orchestrator",
            "summary": "已接收问题",
            "inputRefs": ["chat:user-1"],
            "outputRefs": [],
            "progress": 0.0,
            "retryable": False,
        },
        {
            "eventId": "chat-run-1:event:2",
            "runId": "chat-run-1",
            "eventType": "run.completed",
            "publicStatus": "completed",
            "owner": "Chat Orchestrator",
            "summary": "运行完成",
            "inputRefs": ["chat:user-1"],
            "outputRefs": ["chat:assistant-1"],
            "progress": 1.0,
            "retryable": False,
        },
    ]
    audit = build_chat_agent_audit(
        message_id="assistant-1",
        status="completed",
        source_count=0,
        run_events=events,
    )
    assert [item["eventType"] for item in audit["events"]] == [item["eventType"] for item in events]
    assert [item["runId"] for item in audit["events"]] == [item["runId"] for item in events]
    assert [item["publicStatus"] for item in audit["events"]] == [item["publicStatus"] for item in events]
    assert all(item["runId"].startswith("chat-audit-assistant-1:") for item in audit["items"])


def test_new_chat_message_persists_one_run_and_initial_context_events() -> None:
    with TestClient(app) as client:
        headers = auth_headers(client, _key("b35-events"))
        conversation = client.post(
            "/api/v1/chat/conversations",
            headers=headers,
            json={"title": "B35 event projection"},
        )
        assert conversation.status_code == 201, conversation.text
        created = client.post(
            f"/api/v1/chat/conversations/{conversation.json()['id']}/messages",
            headers=headers,
            json={"content": "请解释一个概念", "idempotency_key": _key("message")},
        )
        assert created.status_code == 201, created.text
        assistant = created.json()["assistantMessage"]
        assert assistant["runId"].startswith("chat-run-")
        assert [item["eventType"] for item in assistant["runEvents"]] == [
            "run.started",
            "context.frozen",
        ]
        assert assistant["agentAudit"]["events"] == assistant["runEvents"]


class _GeneralLLM:
    model = "deepseek-v4-flash"
    has_vision = False

    async def generate_stream(self, system_prompt, user_prompt, *, role, images):
        yield "这是一个通用回答。"


class _GeneralSwarm:
    def __init__(self):
        self.llm = _GeneralLLM()


def test_general_chat_exposes_real_minimal_trace_for_message_and_inspector(monkeypatch) -> None:
    monkeypatch.setattr(stream_api, "build_swarm_from_headers", lambda _headers: _GeneralSwarm())
    with TestClient(app) as client:
        headers = auth_headers(client, _key("b35-general-trace"))
        conversation = client.post(
            "/api/v1/chat/conversations",
            headers=headers,
            json={"title": "普通轨迹"},
        )
        assert conversation.status_code == 201, conversation.text
        created = client.post(
            f"/api/v1/chat/conversations/{conversation.json()['id']}/messages",
            headers=headers,
            json={"content": "今天怎么安排学习时间？", "idempotency_key": _key("message")},
        )
        assert created.status_code == 201, created.text
        response = client.post(
            "/api/stream/chat",
            headers=headers,
            json={"user_message_id": created.json()["userMessage"]["id"]},
        )
        assert response.status_code == 200, response.text
        complete = next(data for name, data in _events(response.text) if name == "complete")
        events = complete["run_events"]
        stages = [event["stageId"] for event in events]
        assert "question_understanding" in stages
        assert "context_check" in stages
        assert "answer_generation" in stages
        assert "safety_boundary" in stages
        assert "answer_organization" in stages
        assert any(event["eventType"] == "run.completed" for event in events)
        assert {event["runId"] for event in events} == {complete["run_id"]}
        assert complete["message"]["runEvents"] == events
        assert complete["message"]["agentAudit"]["events"] == events
