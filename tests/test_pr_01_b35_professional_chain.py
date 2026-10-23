from __future__ import annotations

import json
import uuid

from fastapi.testclient import TestClient

import stream_api
from app.database import DBSourceDocument, DBSourceRef, SessionLocal
from app.main import app
from tests.api_test_helpers import auth_headers


COURSE_ID = "course-machine-learning-foundations-v1"


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


class _ProfessionalLLM:
    model = "deepseek-v4-flash"
    has_vision = False

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def generate(self, system_prompt, user_prompt, *, role):
        self.calls.append({"role": role, "system": system_prompt, "user": user_prompt})
        if role == "Evidence Verifier":
            return json.dumps({
                "claims": [{
                    "claim_id": "claim-01",
                    "claim": "学习率过大可能导致损失震荡",
                    "support": "supported",
                    "source_ref_ids": [self.source_ref_id],
                    "quote": "学习率过大会导致损失震荡。",
                    "location": "来源片段",
                    "confidence": 0.94,
                    "review": {
                        "challenger": "未发现概念混淆",
                        "verifier": "通过",
                        "revision": "",
                    },
                }]
            }, ensure_ascii=False)
        return f"{role} 已完成当前步骤。"

    async def generate_stream(self, system_prompt, user_prompt, *, role, images):
        self.calls.append({"role": role, "system": system_prompt, "user": user_prompt})
        yield "根据课程证据，学习率过大可能导致损失震荡。"


class _Swarm:
    def __init__(self, llm):
        self.llm = llm


class _FailingProfessionalLLM(_ProfessionalLLM):
    async def generate(self, system_prompt, user_prompt, *, role):
        self.calls.append({"role": role, "system": system_prompt, "user": user_prompt})
        raise RuntimeError("provider unavailable")


def _source_ref_id() -> str:
    with SessionLocal() as session:
        row = (
            session.query(DBSourceRef)
            .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
            .filter(DBSourceDocument.course_id == COURSE_ID)
            .first()
        )
        assert row is not None
        return row.id


def test_professional_stream_runs_real_agent_stages_and_claim_projection(monkeypatch) -> None:
    llm = _ProfessionalLLM()
    monkeypatch.setattr(stream_api, "build_swarm_from_headers", lambda _headers: _Swarm(llm))

    with TestClient(app) as client:
        source_ref_id = _source_ref_id()
        llm.source_ref_id = source_ref_id
        headers = auth_headers(client, _key("b35-professional"))
        conversation = client.post(
            "/api/v1/chat/conversations",
            headers=headers,
            json={"course_id": COURSE_ID, "title": "专业链"},
        )
        assert conversation.status_code == 201, conversation.text
        created = client.post(
            f"/api/v1/chat/conversations/{conversation.json()['id']}/messages",
            headers=headers,
            json={
                "content": "解释学习率过大时为什么会震荡。",
                "context_refs": [{"courseId": COURSE_ID, "sourceRefId": source_ref_id}],
                "idempotency_key": _key("message"),
            },
        )
        assert created.status_code == 201, created.text
        response = client.post(
            "/api/stream/chat",
            headers=headers,
            json={"user_message_id": created.json()["userMessage"]["id"], "message": "ignored"},
        )
        assert response.status_code == 200, response.text
        parsed = _events(response.text)
        complete = next(data for name, data in parsed if name == "complete")
        run_events = complete["run_events"]
        event_types = [item["eventType"] for item in run_events]
        assert "source.bound" in event_types
        assert event_types.index("stage.started") < event_types.index("source.bound")
        roles = [item["role"] for item in llm.calls]
        assert len(roles) == 6
        assert roles[1:5] == ["Subject Expert", "Challenger", "Evidence Verifier", "Pedagogical"]
        assert complete["message"]["orchestration"]["mode"] == "course_professional"
        assert complete["message"]["orchestration"]["groundingLevel"] == "A"
        claims = complete["message"]["claims"]
        assert claims[0]["support"] == "supported"
        assert claims[0]["sourceRefIds"] == [source_ref_id]
        claim_events = [item for item in run_events if item["eventType"] == "claim.checked"]
        assert len(claim_events) == 1
        assert claim_events[0]["stageId"] == "claim:claim-01"
        assert claim_events[0]["outputRefs"] == ["claim:claim-01", f"source:{source_ref_id}"]
        assert complete["message"]["runId"] == complete["run_id"]
        assert "system_prompt" not in response.text.lower()
        assert "reasoning_content" not in response.text.lower()


def test_course_without_materials_still_returns_general_answer_with_boundary_notice(monkeypatch) -> None:
    llm = _ProfessionalLLM()
    monkeypatch.setattr(stream_api, "build_swarm_from_headers", lambda _headers: _Swarm(llm))
    with TestClient(app) as client:
        headers = auth_headers(client, _key("b35-course-empty"))
        conversation = client.post(
            "/api/v1/chat/conversations",
            headers=headers,
            json={"course_id": COURSE_ID, "title": "课程资料不足"},
        ).json()
        created = client.post(
            f"/api/v1/chat/conversations/{conversation['id']}/messages",
            headers=headers,
            json={"content": "解释 Transformer 是什么", "idempotency_key": _key("message")},
        )
        response = client.post(
            "/api/stream/chat",
            headers=headers,
            json={"user_message_id": created.json()["userMessage"]["id"]},
        )
        assert response.status_code == 200, response.text
        complete = next(data for name, data in _events(response.text) if name == "complete")
        assert "超出了当前课程已经讲到的范围" in complete["content"]
        assert complete["message"]["orchestration"]["groundingLevel"] == "C"


def test_high_risk_without_materials_exposes_insufficient_evidence_boundary(monkeypatch) -> None:
    llm = _ProfessionalLLM()
    monkeypatch.setattr(stream_api, "build_swarm_from_headers", lambda _headers: _Swarm(llm))
    with TestClient(app) as client:
        headers = auth_headers(client, _key("b35-course-risk"))
        conversation = client.post(
            "/api/v1/chat/conversations",
            headers=headers,
            json={"course_id": COURSE_ID, "title": "证据边界"},
        ).json()
        created = client.post(
            f"/api/v1/chat/conversations/{conversation['id']}/messages",
            headers=headers,
            json={
                "content": "请给出必须依据原文的精确规范条款",
                "idempotency_key": _key("message"),
            },
        )
        response = client.post(
            "/api/stream/chat",
            headers=headers,
            json={"user_message_id": created.json()["userMessage"]["id"]},
        )
        assert response.status_code == 200, response.text
        complete = next(data for name, data in _events(response.text) if name == "complete")
        assert "现有内容还不足以回答得很肯定" in complete["content"]
        assert complete["message"]["orchestration"]["groundingLevel"] == "D"


def test_explicit_general_qa_bypasses_course_debate_for_level_d_continue_action(monkeypatch) -> None:
    llm = _ProfessionalLLM()
    monkeypatch.setattr(stream_api, "build_swarm_from_headers", lambda _headers: _Swarm(llm))
    with TestClient(app) as client:
        source_ref_id = _source_ref_id()
        headers = auth_headers(client, _key("b35-general-qa"))
        conversation = client.post(
            "/api/v1/chat/conversations",
            headers=headers,
            json={"course_id": COURSE_ID, "title": "通用继续"},
        ).json()
        created = client.post(
            f"/api/v1/chat/conversations/{conversation['id']}/messages",
            headers=headers,
            json={
                "content": "请用通用知识继续解释 Transformer。",
                "intent": "general_qa",
                "context_refs": [{"courseId": COURSE_ID, "sourceRefId": source_ref_id}],
                "idempotency_key": _key("message"),
            },
        )
        assert created.status_code == 201, created.text
        response = client.post(
            "/api/stream/chat",
            headers=headers,
            json={"user_message_id": created.json()["userMessage"]["id"]},
        )
        assert response.status_code == 200, response.text
        complete = next(data for name, data in _events(response.text) if name == "complete")
        assert complete["message"]["orchestration"]["mode"] == "general"
        assert not any(call["role"] == "Subject Expert" for call in llm.calls)


def test_grounding_levels_keep_answerability_separate_from_course_evidence() -> None:
    class Message:
        content = "请解释一个概念"

    course_without_sources = {
        "context_snapshot": {"course_ids": ["course-a"]},
        "source_materials": [],
        "user_message": Message(),
    }
    assert stream_api._professional_grounding(course_without_sources)["level"] == "C"
    assert stream_api._professional_grounding(course_without_sources)["answerability"] == "answerable"

    high_risk = {
        **course_without_sources,
        "user_message": type("Message", (), {"content": "请给出必须依据原文的精确规范条款"})(),
    }
    classified = stream_api._professional_grounding(high_risk)
    assert classified["level"] == "D"
    assert classified["answerability"] == "needs_input"


def test_low_quality_and_changed_sources_are_classified_without_silent_refusal() -> None:
    class Message:
        content = "请解释这个课程概念"

    low_quality = stream_api._professional_grounding({
        "context_snapshot": {"course_ids": ["course-a"]},
        "source_materials": [{"sourceRefId": "source-a", "available": True, "quote": ""}],
        "user_message": Message(),
    })
    assert low_quality["level"] == "C"
    assert low_quality["answerability"] == "answerable"
    assert low_quality["quality_limited"]

    conflicted = stream_api._professional_grounding({
        "context_snapshot": {"course_ids": ["course-a"]},
        "source_materials": [{
            "sourceRefId": "source-a",
            "available": False,
            "reasonCode": "source_document_changed",
            "reason": "课程文档版本已变化",
        }],
        "user_message": Message(),
    })
    assert conflicted["level"] == "D"
    assert conflicted["conflicted"] is True
    assert conflicted["answerability"] == "answerable"
    mixed_conflict = stream_api._professional_grounding({
        "context_snapshot": {"course_ids": ["course-a"]},
        "source_materials": [
            {"sourceRefId": "source-good", "available": True, "quote": "可用片段"},
            {"sourceRefId": "source-old", "available": True, "quote": "旧片段", "reasonCode": "source_ref_version_changed"},
        ],
        "user_message": Message(),
    })
    assert mixed_conflict["level"] == "D"
    assert mixed_conflict["conflicted"] is True


def test_unrelated_chinese_question_does_not_match_generic_course_words() -> None:
    class Message:
        content = "请解释一个与本课程完全无关的量子物理概念"

    classified = stream_api._professional_grounding({
        "context_snapshot": {"course_ids": ["course-a"]},
        "source_materials": [{
            "sourceRefId": "source-a",
            "available": True,
            "title": "课程说明",
            "quote": "本课程介绍 RAG 检索、来源登记和证据边界。",
        }],
        "user_message": Message(),
    })

    assert classified["relevant"] == []
    assert classified["level"] == "C"
    assert classified["answerability"] == "answerable"


def test_only_levels_a_and_b_with_usable_sources_enter_professional_chain() -> None:
    assert stream_api._should_run_professional_chain({
        "level": "A",
        "course_ids": ["course-a"],
        "available": [{"sourceRefId": "source-a"}],
    }) is True
    assert stream_api._should_run_professional_chain({
        "level": "B",
        "course_ids": ["course-a"],
        "available": [{"sourceRefId": "source-a"}],
    }) is True
    for level in ("C", "D"):
        assert stream_api._should_run_professional_chain({
            "level": level,
            "course_ids": ["course-a"],
            "available": [{"sourceRefId": "source-a"}],
        }) is False
    assert stream_api._should_run_professional_chain({
        "level": "A",
        "course_ids": ["course-a"],
        "available": [],
    }) is False


def test_professional_model_failure_is_persisted_and_retryable(monkeypatch) -> None:
    llm = _FailingProfessionalLLM()
    monkeypatch.setattr(stream_api, "build_swarm_from_headers", lambda _headers: _Swarm(llm))
    with TestClient(app) as client:
        source_ref_id = _source_ref_id()
        headers = auth_headers(client, _key("b35-professional-failure"))
        conversation = client.post(
            "/api/v1/chat/conversations",
            headers=headers,
            json={"course_id": COURSE_ID, "title": "专业链失败"},
        ).json()
        created = client.post(
            f"/api/v1/chat/conversations/{conversation['id']}/messages",
            headers=headers,
            json={
                "content": "请严格依据课程资料解释。",
                "context_refs": [{"courseId": COURSE_ID, "sourceRefId": source_ref_id}],
                "idempotency_key": _key("message"),
            },
        )
        response = client.post(
            "/api/stream/chat",
            headers=headers,
            json={"user_message_id": created.json()["userMessage"]["id"]},
        )
        assert response.status_code == 200
        parsed = _events(response.text)
        error = next(data for name, data in parsed if name == "error")
        assert error["code"] == "chat_professional_chain_failed"
        assert any(item["eventType"] == "run.failed" for item in error["run_events"])
        stored = client.get(
            f"/api/v1/chat/conversations/{conversation['id']}", headers=headers
        ).json()
        assistant = stored["messages"][-1]
        assert assistant["status"] == "failed"
        assert assistant["failure"]["code"] == "chat_professional_chain_failed"


def test_claim_projection_rejects_unknown_sources_and_invalid_support_states() -> None:
    claims = stream_api._normalize_claims(
        json.dumps({
            "claims": [{
                "claim_id": "c1",
                "claim": "结论",
                "support": "invented",
                "source_ref_ids": ["not-allowed"],
                "confidence": 2,
            }]
        }),
        [{"sourceRefId": "source-1", "available": True}],
    )
    assert claims[0]["support"] == "unsupported"
    assert claims[0]["sourceRefIds"] == []
    assert claims[0]["confidence"] == 1.0


def test_claim_projection_requires_source_quote_and_location_for_publishable_states() -> None:
    materials = [{
        "sourceRefId": "source-1",
        "available": True,
        "title": "课程资料",
    }]
    raw = json.dumps({
        "claims": [
            {
                "claim_id": "missing-quote",
                "claim": "缺少原文引文的结论",
                "support": "supported",
                "source_ref_ids": ["source-1"],
                "location": "第 1 页",
                "confidence": 0.9,
                "review": {"revision": "模型备注"},
            },
            {
                "claim_id": "missing-location",
                "claim": "缺少位置的部分结论",
                "support": "partially_supported",
                "source_ref_ids": ["source-1"],
                "quote": "课程原文片段",
                "confidence": 0.8,
            },
            {
                "claim_id": "complete",
                "claim": "证据完整的结论",
                "support": "supported",
                "source_ref_ids": ["source-1"],
                "quote": "课程原文片段",
                "location": "第 2 页",
                "confidence": 0.95,
            },
        ]
    }, ensure_ascii=False)

    claims = stream_api._normalize_claims(raw, materials)

    assert [claim["support"] for claim in claims] == [
        "unsupported",
        "unsupported",
        "supported",
    ]
    assert claims[0]["sourceRefIds"] == ["source-1"]
    assert claims[1]["sourceRefIds"] == ["source-1"]
    assert claims[2]["sourceRefIds"] == ["source-1"]
    assert "缺少完整 source_ref" in claims[0]["review"]["revision"]
    assert "模型备注" in claims[0]["review"]["revision"]
    assert "缺少完整 source_ref" in claims[1]["review"]["revision"]
    assert claims[2]["review"]["revision"] == ""


def test_claim_projection_downgrades_claims_bound_to_unavailable_sources() -> None:
    claims = stream_api._normalize_claims(
        json.dumps({
            "claims": [{
                "claim_id": "unavailable-source",
                "claim": "来源已撤回的结论",
                "support": "contradicted",
                "source_ref_ids": ["source-1"],
                "quote": "旧版本原文",
                "location": "第 3 页",
                "confidence": 0.7,
            }]
        }, ensure_ascii=False),
        [{"sourceRefId": "source-1", "available": False}],
    )

    assert claims[0]["support"] == "unsupported"
    assert claims[0]["sourceRefIds"] == []
    assert "缺少完整 source_ref" in claims[0]["review"]["revision"]
