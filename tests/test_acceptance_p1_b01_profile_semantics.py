from __future__ import annotations

import asyncio

import app.m5_legacy_calls as legacy_calls
import app.profile_onboarding as onboarding
import app.profile_onboarding_api as onboarding_api
import llm_client
from app.database import DBUser


def test_model_candidate_parser_keeps_understanding_evidence_and_confidence():
    result = onboarding._parse_model_candidates(
        '{"understanding":"有人工智能专业背景，想把课程知识用于项目。",'
        '"fields":[{"key":"major","label":"专业方向","value":"人工智能",'
        '"kind":"text","evidence":"我读人工智能专业","confidence":0.93}],'
        '"uncertainties":["年级还需要确认"]}',
        "background",
        "我读人工智能专业，想把课程知识用于项目。",
    )
    assert result["summary"].startswith("有人工智能")
    assert result["fields"] == [{
        "key": "major",
        "label": "专业方向",
        "value": "人工智能",
        "kind": "text",
        "evidence": "我读人工智能专业",
        "confidence": 0.93,
        "source": "deepseek-v4-flash",
    }]
    assert result["uncertainties"] == ["年级还需要确认"]


def test_real_model_extractor_requires_deepseek_max_and_validates_json(monkeypatch):
    calls = {}

    class FakeLLM:
        model = "deepseek-v4-flash"

        async def generate(self, *_args, **_kwargs):
            raise AssertionError("audited call should own model invocation")

    def fake_build_async_llm(**kwargs):
        calls.update(kwargs)
        return FakeLLM()

    async def fake_audited(_llm, *, response_validator, **_kwargs):
        raw = '{"understanding":"我有机器学习基础。","fields":[{"key":"knowledge_base",'
        raw += '"label":"基础自述","value":"机器学习","kind":"text",'
        raw += '"evidence":"我学过机器学习","confidence":0.88}],"uncertainties":[]}'
        response_validator(raw)
        return raw

    monkeypatch.setattr(llm_client, "build_async_llm", fake_build_async_llm)
    monkeypatch.setattr(legacy_calls, "audited_legacy_text_call", fake_audited)

    result = onboarding.llm_extract_candidates(
        "foundation",
        "我学过机器学习。",
        owner_public_id="usr-p1-b01",
    )
    assert result["source"] == "deepseek-v4-flash"
    assert result["modelMeta"]["reasoningEffort"] == "max"
    assert calls == {
        "provider": "openai",
        "model": "deepseek-v4-flash",
        "thinking_mode": "max",
        "reasoning_effort": "max",
        "allow_fallback": False,
    }


def test_onboarding_api_passes_real_model_extractor_with_owner_scope(monkeypatch):
    captured = {}

    async def fake_run_db_op(operation, *args, **kwargs):
        captured["operation"] = operation
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"status": "saved"}

    def fake_extractor(dimension, answer, *, owner_public_id):
        captured["extractor_call"] = (dimension, answer, owner_public_id)
        return {"dimension": dimension, "fields": [], "summary": answer}

    monkeypatch.setattr(onboarding_api, "run_db_op", fake_run_db_op)
    monkeypatch.setattr(onboarding_api, "llm_extract_candidates", fake_extractor)

    user = DBUser(
        public_id="usr-p1-b01-api",
        username="p1-b01-api",
        hashed_password="not-used",
        role="student",
    )
    payload = onboarding_api.TurnInput(
        turn_id="p1-b01-turn",
        question_dimension="background",
        user_answer="我读人工智能专业。",
    )
    result = asyncio.run(onboarding_api.submit_turn(payload, user))

    assert result == {"status": "saved"}
    extractor = captured["kwargs"]["extractor"]
    extractor("background", "我读人工智能专业。")
    assert captured["extractor_call"] == (
        "background",
        "我读人工智能专业。",
        "usr-p1-b01-api",
    )
