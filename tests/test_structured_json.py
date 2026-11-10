from __future__ import annotations

import pytest

from llm_client import apply_thinking_mode, parse_json_object, requires_json_object


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"value": 7}', {"value": 7}),
        ('```json\n{"value": 7}\n```', {"value": 7}),
        ('```\n{"value": 7}\n```', {"value": 7}),
    ],
)
def test_parse_json_object_accepts_object_and_complete_json_fence(raw, expected):
    assert parse_json_object(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        '[{"value": 7}]',
        'Here is the result: {"value": 7}',
        '{"value": 7}\nextra',
        '```json\n{"value": 7}',
        '```python\n{"value": 7}\n```',
        '```json\n{"value": 7}\n```\nextra',
    ],
)
def test_parse_json_object_rejects_non_object_or_extra_content(raw):
    with pytest.raises((TypeError, ValueError)):
        parse_json_object(raw)


def test_requires_json_object_only_for_explicit_structured_prompts():
    assert requires_json_object("Return JSON only. Use this schema") is True
    assert requires_json_object("JSON Schema: {type: object}") is True


@pytest.mark.parametrize("prompt", [
    "你是学习资源审核者。只输出一个 JSON 对象，不要输出其他内容。",
    "只输出一个JSON对象。",
    "仅输出 JSON 对象，保留教学内容。",
    "只输出符合 JSON Schema 的对象。",
])
def test_requires_json_object_recognizes_generation_and_review_prompts(prompt):
    assert requires_json_object(prompt) is True


@pytest.mark.parametrize("prompt", [
    "请用自然语言解释 JSON 的用途",
    "讲解如何输出一个 JSON 对象，并给出示例。",
])
def test_requires_json_object_does_not_turn_json_lessons_into_structured_output(prompt):
    assert requires_json_object(prompt) is False


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("disabled", {"type": "disabled"}), ("ENABLED", {"type": "enabled"})],
)
def test_apply_thinking_mode_when_explicitly_configured(mode, expected):
    payload = {"model": "test"}
    assert apply_thinking_mode(payload, mode)["thinking"] == expected


@pytest.mark.parametrize("mode", ["", None, "auto", "invalid"])
def test_apply_thinking_mode_preserves_generic_payload_by_default(mode):
    payload = {"model": "test"}
    assert "thinking" not in apply_thinking_mode(payload, mode)
    assert requires_json_object("只输出一个符合给定 JSON Schema 的原始 JSON 对象") is True
    assert requires_json_object("请用自然语言解释 JSON 的用途") is False
