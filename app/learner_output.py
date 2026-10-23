"""Learner-facing wording shared by generated teaching surfaces."""

from __future__ import annotations

import re
from typing import Any


_PHRASE_REPLACEMENTS = (
    ("依据课程来源", "从学习内容来看"),
    ("根据课程来源", "结合当前学习内容"),
    ("基于课程来源", "结合当前学习内容"),
    ("本地确定性演示", "可复现演示"),
    ("本地确定性", "可复现"),
    ("确定性回答", "明确回答"),
    ("确定性结论", "明确结论"),
    ("确定性", "可复现性"),
    ("上下文重点", "本轮重点"),
    ("冻结课程来源", "已选课程内容"),
    ("课程来源", "课程内容"),
    ("来源版本", "材料范围"),
    ("来源片段", "相关片段"),
    ("来源", "参考材料"),
    ("证据不足", "现有信息还不够"),
    ("证据链", "核对过程"),
    ("学习证据", "学习记录"),
    ("评分证据", "评分记录"),
    ("证据", "可核对信息"),
    ("课文", "学习内容"),
    ("依据", "理由"),
    ("约束条件", "限制条件"),
    ("约束", "限制"),
    ("冻结", "已保存"),
)

_INTERNAL_LABEL = re.compile(
    r"(?i)\b(?:source[_ -]?ref(?:[_ -]?id)?|knowledge[_ -]?point[_ -]?id|"
    r"context[_ -]?fingerprint|content[_ -]?hash|rubric[_ -]?version|"
    r"generation[_ -]?mode|run[_ -]?id|message[_ -]?id|event[_ -]?id)\b"
    r"\s*[:=：]?\s*[A-Za-z0-9_.:-]*"
)
_INTERNAL_TOKEN = re.compile(
    r"(?i)\b(?:demo-)?(?:kp|source|event|trace|run|claim|chat|task)-[a-z0-9-]{4,}\b|"
    r"\bf\d+\.[a-z0-9_.-]+\.v\d+\b|\b[a-f0-9]{24,}\b|"
    r"\b(?:deterministic_local|llm_grounded|reasoning_content)\b"
)


def teacher_text(value: Any, *, preserve_boundary: bool = False) -> str:
    """Remove implementation narration from prose shown to a learner.

    This is deliberately a narrow projection step. It does not inspect or
    rewrite code, answer keys, source records, or audit payloads.
    """

    text = str(value or "")
    if not text:
        return ""
    text = re.sub(
        r"(?:运行|模型|生成|回答)模式\s*[:：]?\s*[A-Za-z0-9_.-]+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(?:知识点\s*)?(?:内部编号|哈希|指纹)\s*[:：]?\s*[A-Za-z0-9_.-]*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    for old, new in _PHRASE_REPLACEMENTS:
        text = text.replace(old, new)
    text = _INTERNAL_LABEL.sub("", text)
    text = _INTERNAL_TOKEN.sub("", text)
    text = re.sub(r"(?i)\[(?:S|A)\d+\]|\[source[_ -]?ref\]", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([，。！？；：,.!?;:])", r"\1", text)
    text = re.sub(r"[，,]\s*(?=[，,。；;])", "", text)
    text = re.sub(r"(?:；|，|,)?\s*(?:模型模式|生成模式|评分规则)\s*(?:为|是)?\s*[A-Za-z0-9_.-]*", "", text)
    return text if preserve_boundary else text.strip()
