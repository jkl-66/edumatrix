from __future__ import annotations

import json
import uuid
import pytest

from fastapi.testclient import TestClient

import stream_api
from app.database import (
    DBLearningEvent,
    DBSourceDocument,
    DBSourceRef,
    SessionLocal,
)
from app.main import app
from tests.api_test_helpers import auth_headers


FLAGSHIP_COURSE_ID = "course-machine-learning-foundations-v1"


def _key(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _events(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    event_name = ""
    for line in text.splitlines():
        if line.startswith("event: "):
            event_name = line[7:]
        elif line.startswith("data: "):
            events.append((event_name, json.loads(line[6:])))
    return events


def _protected_counts() -> dict[str, int]:
    with SessionLocal() as session:
        return {
            "events": session.query(DBLearningEvent).count(),
            "source_documents": session.query(DBSourceDocument).count(),
            "source_refs": session.query(DBSourceRef).count(),
        }


class _FakeLLM:
    model = "f7-t04-stream-test"
    has_vision = True

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def generate_stream(self, system_prompt, user_prompt, *, role, images):
        self.calls.append({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "role": role,
            "images": images,
        })
        yield "先给出直接回答，"
        yield "再说明依据与下一步。"


class _FakeSwarm:
    def __init__(self, llm: _FakeLLM) -> None:
        self.llm = llm


@pytest.mark.parametrize("kind", ["practice", "explanation", "lookup"])
def test_only_explicit_practice_prepares_a_task_and_reuses_it_on_replay(monkeypatch, kind):
    llm = _FakeLLM()
    plans = []
    async def generate(system, user, *, role):
        plans.append(role)
        from llm_client import requires_json_object
        assert requires_json_object(system)
        context = json.loads(user)
        assert set(context) == {"current_request", "teaching_context", "request_context"}
        assert context['current_request'] == '用手机设计一个二十分钟能完成的摄影对比。'
        return json.dumps({"learner_constraints": ["手机，二十分钟。"], "activity": "同一物件拍两张，一张静止一张缓慢移动。",
                           "method": "固定手机和灯光，点击物件对焦。", "self_check": "比较边缘和背景的清晰程度。",
                           "conditions": ["手机没有专业模式，不要求手动调光圈。"]}, ensure_ascii=False)
    llm.generate = generate
    selected = []
    monkeypatch.setattr(stream_api, "build_swarm_from_headers", lambda _headers: _FakeSwarm(llm))

    async def classify(*args, **kwargs):
        return {"is_academic": True, "question_kind": kind}

    def select(backend, *, deep_reasoning, reasoning_effort=None):
        selected.append((deep_reasoning, reasoning_effort))
        return backend

    monkeypatch.setattr(stream_api, "_classify_academic_intent", classify)
    monkeypatch.setattr(stream_api, "for_answer_step", select)
    with TestClient(app) as client:
        headers = auth_headers(client, _key("general-task"))
        conversation = client.post("/api/v1/chat/conversations", headers=headers, json={}).json()
        created = client.post(f"/api/v1/chat/conversations/{conversation['id']}/messages", headers=headers,
            json={"content": "用手机设计一个二十分钟能完成的摄影对比。", "idempotency_key": _key("practice")}).json()
        before = _protected_counts()
        response = client.post("/api/stream/chat", headers=headers,
            json={"user_message_id": created["userMessage"]["id"]})
        complete = next(data for name, data in _events(response.text) if name == "complete")
        assert complete["message"]["status"] == "completed"
        assert selected == ([(False, None), (True, "high")] if kind == "practice" else [(False, None)])
        assert len(llm.calls) == 1
        assert plans == (["Pedagogical"] if kind == "practice" else [])
        if kind == "practice":
            assert "固定手机和灯光" in llm.calls[0]["user_prompt"]
            assert complete["message"]["streamCheckpoint"]["learningTaskPlan"]["activity"]
        assert _protected_counts() == before
        assert "事实边界检查已完成" not in response.text
        replay = client.post("/api/stream/chat", headers=headers,
            json={"user_message_id": created["userMessage"]["id"]})
        assert next(data for name, data in _events(replay.text) if name == "complete")["replayed"] is True
        assert len(llm.calls) == 1
        assert len(plans) == int(kind == "practice")


def test_current_chat_uses_active_personal_memory_and_stops_after_withdrawal(monkeypatch):
    llm = _FakeLLM()
    monkeypatch.setattr(stream_api, "build_swarm_from_headers", lambda _headers: _FakeSwarm(llm))
    with TestClient(app) as client:
        headers = auth_headers(client, _key("memory-current-chat"))
        other_headers = auth_headers(client, _key("memory-other-chat"))
        content = "请用校园图书借阅站举例，并建议一个可收集的借阅字段。"
        memory = client.post("/api/v1/next/core/memories", headers=headers,
            json={"title": "独特场景偏好", "memory_type": "preference", "content": content}).json()

        def ask(request_headers):
            conversation = client.post("/api/v1/chat/conversations", headers=request_headers,
                                       json={"title": "独立记忆验证"}).json()
            message = client.post(f"/api/v1/chat/conversations/{conversation['id']}/messages",
                headers=request_headers, json={"content": "请介绍分类和回归", "idempotency_key": _key("memory-question")})
            assert message.status_code == 201, message.text
            response = client.post("/api/stream/chat", headers=request_headers,
                json={"user_message_id": message.json()["userMessage"]["id"]})
            assert response.status_code == 200
            return llm.calls[-1]["user_prompt"]

        assert content in ask(headers)
        assert content not in ask(other_headers)
        withdrawn = client.post(f"/api/v1/next/core/memories/{memory['id']}/withdraw", headers=headers,
                                json={"expected_version": memory["lock_version"], "reason": "测试撤回"})
        assert withdrawn.status_code == 200
        assert content not in ask(headers)


def test_interrupted_practice_keeps_the_task_when_classification_changes(monkeypatch):
    class InterruptedLLM:
        model = 'practice-resume-test'
        planned = 0
        streamed = 0
        async def generate(self, system, user, *, role):
            self.planned += 1
            return json.dumps({'learner_constraints': ['普通手机独自完成。'], 'activity': '用一只杯子做静止和移动对比。', 'method': '保持同一距离与灯光。',
                               'self_check': '比较杯子边缘和背景。', 'conditions': ['不要求专业模式。']}, ensure_ascii=False)
        async def generate_stream(self, system, user, *, role, images):
            assert '用一只杯子做静止和移动对比' in user
            self.streamed += 1
            if self.streamed == 1:
                yield '先选一只杯子。'
                raise RuntimeError('synthetic interrupted delivery')
            yield '固定手机和灯光，比较两张照片的边缘。'

    llm = InterruptedLLM()
    monkeypatch.setattr(stream_api, 'build_swarm_from_headers', lambda _headers: _FakeSwarm(llm))
    classified = []
    async def classify(*args, **kwargs):
        classified.append(True)
        return {'is_academic': True, 'question_kind': 'practice' if len(classified) == 1 else 'explanation'}
    monkeypatch.setattr(stream_api, '_classify_academic_intent', classify)
    with TestClient(app) as client:
        headers=auth_headers(client,_key('practice-resume'))
        conversation=client.post('/api/v1/chat/conversations',headers=headers,json={}).json()
        created=client.post(f"/api/v1/chat/conversations/{conversation['id']}/messages",headers=headers,
            json={'content':'设计一个手机摄影小对比。','idempotency_key':_key('resume')}).json()
        user_id=created['userMessage']['id'];aid=created['assistantMessage']['id']
        first=client.post('/api/stream/chat',headers=headers,json={'user_message_id':user_id})
        assert any(name=='error' for name,_ in _events(first.text))
        from app.database import DBChatMessage
        with SessionLocal() as db:
            row=db.get(DBChatMessage,aid)
            version=row.lock_version
            assert row.stream_checkpoint['learningTaskPlan']['activity'].startswith('用一只杯子')
        resumed=client.post(f'/api/v1/chat/messages/{aid}/continue',headers=headers,json={'expected_lock_version':version})
        assert resumed.status_code==200,resumed.text
        second=client.post('/api/stream/chat',headers=headers,json={'user_message_id':user_id})
        complete=next(data for name,data in _events(second.text) if name=='complete')
        assert '固定手机和灯光' in complete['content']
        assert llm.planned==1 and llm.streamed==2


def test_current_attachment_selection_is_explicit_when_history_mentions_another_file():
    from types import SimpleNamespace
    context = {
        "user_message": SimpleNamespace(content="忽略上一题的文件，只看本次文件。"),
        "assistant_message": SimpleNamespace(content=""),
        "history": [{"role": "assistant", "content": "上一份材料是07:40，共4题。"}],
        "attachments": [{"filename": "乙.txt", "parsed_text": "20:10，共9题。"}],
    }
    system, prompt, _ = stream_api._canonical_chat_prompts(context, "progressive")
    assert "确实携带了 1 个附件" in system
    current_files = prompt.split("本次附件清单（", 1)[1].split("学生当前问题：", 1)[0]
    assert "20:10" in current_files and "07:40" not in current_files
    assert "07:40" in prompt  # History stays available, but is not a current attachment.
    context["attachments"] = []
    system, prompt, _ = stream_api._canonical_chat_prompts(context, "progressive")
    assert "本次问题没有携带附件" in system
    assert "本次附件清单：空" in prompt


def test_canonical_stream_uses_persisted_context_and_replays_without_second_model_call(monkeypatch) -> None:
    llm = _FakeLLM()
    monkeypatch.setattr(stream_api, "build_swarm_from_headers", lambda _headers: _FakeSwarm(llm))

    with TestClient(app) as client:
        owner = _key("f7_t04_stream")
        headers = auth_headers(client, owner)
        headers['X-EduMatrix-Response-Depth'] = 'detailed'
        with SessionLocal() as session:
            source_ref = (
                session.query(DBSourceRef)
                .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
                .filter(DBSourceDocument.course_id == FLAGSHIP_COURSE_ID)
                .first()
            )
            assert source_ref is not None
            source_ref_id = source_ref.id

        conversation_response = client.post(
            "/api/v1/chat/conversations",
            headers=headers,
            json={"title": "canonical stream", "course_id": FLAGSHIP_COURSE_ID},
        )
        assert conversation_response.status_code == 201, conversation_response.text
        conversation = conversation_response.json()

        uploaded = client.post(
            f"/api/v1/chat/conversations/{conversation['id']}/attachments",
            headers=headers,
            data={"idempotency_key": _key("attachment")},
            files={
                "file": (
                    "learning-rate.md",
                    "# 学习率\n\n学习率过大会导致损失震荡。".encode("utf-8"),
                    "text/markdown",
                )
            },
        )
        assert uploaded.status_code == 201, uploaded.text
        attachment = uploaded.json()["attachment"]
        parsed = client.post(
            f"/api/v1/chat/attachments/{attachment['id']}/parse",
            headers=headers,
            json={"expected_lock_version": attachment["lockVersion"]},
        )
        assert parsed.status_code == 200, parsed.text

        created = client.post(
            f"/api/v1/chat/conversations/{conversation['id']}/messages",
            headers=headers,
            json={
                "content": "解释学习率过大时为什么会震荡。",
                "attachment_ids": [attachment["id"]],
                "context_refs": [
                    {"courseId": FLAGSHIP_COURSE_ID, "sourceRefId": source_ref_id}
                ],
                "idempotency_key": _key("message"),
                "return_to": "/knowledge",
            },
        )
        assert created.status_code == 201, created.text
        user_message_id = created.json()["userMessage"]["id"]
        before = _protected_counts()

        legacy_payload = {
            "student_id": owner,
            "user_message_id": user_message_id,
            "message": "/matrix 这段客户端文本不应替换已保存问题",
            "mode": "matrix",
            "images": ["data:image/png;base64,client-payload-must-be-ignored"],
            "active_doc_ids": ["client-document-must-be-ignored"],
        }
        response = client.post(
            "/api/stream/chat", headers=headers, json=legacy_payload
        )
        assert response.status_code == 200, response.text
        events = _events(response.text)
        assert [name for name, _data in events].count("complete") == 1
        complete = next(data for name, data in events if name == "complete")
        assert complete["content"] == "先给出直接回答，再说明依据与下一步。"
        assert complete["resource_links"] == []
        assert '学生选择详细推导' in llm.calls[0]['system_prompt']
        assert complete["source_refs"][0]["sourceRefId"] == source_ref_id
        assert complete["message"]["status"] == "completed"
        assert len(llm.calls) == 1
        call = llm.calls[0]
        assert "解释学习率过大时为什么会震荡" in call["user_prompt"]
        assert "学习率过大会导致损失震荡" in call["user_prompt"]
        assert "[S1]" in call["user_prompt"]
        assert "客户端文本不应替换" not in call["user_prompt"]
        assert call["images"] == []
        assert _protected_counts() == before

        replay = client.post(
            "/api/stream/chat", headers=headers, json=legacy_payload
        )
        assert replay.status_code == 200, replay.text
        replay_events = _events(replay.text)
        replay_complete = next(data for name, data in replay_events if name == "complete")
        assert replay_complete["replayed"] is True
        assert replay_complete["content"] == complete["content"]
        assert len(llm.calls) == 1
        assert _protected_counts() == before

        serialized = (response.text + replay.text).lower()
        for forbidden in (
            "api_key",
            "chain_of_thought",
            "reasoning_content",
            "system_prompt",
            "raw_log",
        ):
            assert forbidden not in serialized
