from __future__ import annotations

import asyncio
import json

import app.profile_onboarding as onboarding
import app.profile_onboarding_api as onboarding_api
import llm_client
import app.m5_legacy_calls as legacy_calls
from app.database import DBUser


def _raw_field(key: str, value: object = "我什么都不会") -> str:
    return json.dumps(
        {
            "understanding": "学生明确说明了自己的当前情况。",
            "fields": [
                {
                    "key": key,
                    "label": "模型返回的字段",
                    "value": value,
                    "evidence": "学生原话：我什么都不会",
                    "confidence": 0.95,
                }
            ],
            "uncertainties": [],
        },
        ensure_ascii=False,
    )


def test_real_model_aliases_are_normalized_for_each_initial_dimension():
    aliases = {
        "background": ("grade", "background_context"),
        "goal": ("learning_goal", "learning_goals"),
        "foundation": ("basis_level", "knowledge_base"),
        "difficulty": ("main_difficulty", "weak_points"),
        "preference": ("learning_preference", "interaction_preferences"),
    }
    for dimension, (alias, canonical) in aliases.items():
        result = onboarding._parse_model_candidates(_raw_field(alias), dimension, "我什么都不会")
        assert result["fields"][0]["key"] == canonical
        assert result["fields"][0]["source"] == "deepseek-v4-flash"


def test_unknown_model_field_is_still_rejected_instead_of_becoming_unverified_profile_data():
    raw = _raw_field("invented_profile_fact")
    try:
        onboarding._parse_model_candidates(raw, "foundation", "我什么都不会")
    except ValueError as exc:
        assert "没有可确认字段" in str(exc)
    else:  # pragma: no cover - the assertion documents the safety boundary
        raise AssertionError("unknown model fields must not be accepted")


def test_real_model_misconceptions_preserve_topic_scores_including_zero():
    patterns = {"过拟合与欠拟合": 0.62, "训练集与测试集": 0.0}
    result = onboarding._parse_model_candidates(
        _raw_field("misconception_patterns", patterns), "difficulty", "容易混淆过拟合与欠拟合。",
    )
    assert result["fields"][0]["value"] == patterns


def test_real_model_extractor_keeps_deepseek_max_and_exposes_canonical_prompt(monkeypatch):
    calls = {}

    class FakeLLM:
        model = "deepseek-v4-flash"

    def fake_build_async_llm(**kwargs):
        calls.update(kwargs)
        return FakeLLM()

    async def fake_audited(_llm, *, system_prompt, user_prompt, response_validator, **_kwargs):
        calls["system_prompt"] = system_prompt
        calls["user_prompt"] = user_prompt
        raw = _raw_field("basis_level")
        response_validator(raw)
        return raw

    monkeypatch.setattr(llm_client, "build_async_llm", fake_build_async_llm)
    monkeypatch.setattr(legacy_calls, "audited_legacy_text_call", fake_audited)
    result = onboarding.llm_extract_candidates("foundation", "我什么都不会", owner_public_id="noc-t05")

    assert result["fields"][0]["key"] == "knowledge_base"
    assert calls["model"] == "deepseek-v4-flash"
    assert calls["thinking_mode"] == "max"
    assert calls["reasoning_effort"] == "max"
    assert calls["allow_fallback"] is False
    assert "knowledge_base" in calls["user_prompt"]


def test_onboarding_api_still_binds_owner_scoped_real_model_extractor(monkeypatch):
    captured = {}

    async def fake_run_db_op(operation, *args, **kwargs):
        captured["operation"] = operation
        captured["kwargs"] = kwargs
        return {"status": "saved"}

    def fake_extractor(dimension, answer, *, owner_public_id):
        captured["extractor_call"] = (dimension, answer, owner_public_id)
        return {"dimension": dimension, "fields": [], "summary": answer}

    monkeypatch.setattr(onboarding_api, "run_db_op", fake_run_db_op)
    monkeypatch.setattr(onboarding_api, "llm_extract_candidates", fake_extractor)
    user = DBUser(public_id="noc-t05-api", username="noc-t05-api", hashed_password="unused", role="student")
    payload = onboarding_api.TurnInput(turn_id="noc-t05-turn", question_dimension="foundation", user_answer="我什么都不会")

    assert asyncio.run(onboarding_api.submit_turn(payload, user)) == {"status": "saved"}
    captured["kwargs"]["extractor"]("foundation", "我什么都不会")
    assert captured["extractor_call"] == ("foundation", "我什么都不会", "noc-t05-api")
