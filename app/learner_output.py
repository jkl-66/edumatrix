"""Learner-facing wording shared by generated teaching surfaces."""

from __future__ import annotations

import ast
import json
import re
from typing import Any

LEARNER_FEEDBACK_INSTRUCTION = (
    "面向学习者的标题、点评、解释、建议和推荐理由使用自然的学习语言，遵守本次明确要求或已确认的讲解语言；未指定时使用中文。像老师反馈学习情况一样，"
    "说明已经理解什么、哪里还需练习以及下一步怎么做，结论必须与真实作答和资料一致。"
    "不要在这些正文中展示字段名、布尔值、英文状态枚举、内部编号、哈希、日志、接口或模型参数。"
    "例如correct=true应表述为本题回答正确，graded应表述为已完成评分；章节和知识点用名称，不用ID。"
    "只写帮助学习者理解、判断和完成当前任务的信息；标题清楚时不再补通用导语，不复述备课策略或反复说明工具用途。"
    "数据性质就地简洁说明一次，如‘练习数据’或‘固定模拟分数’；不再附‘不是你的实测记录，也不是行业标准’等防御性说明。"
    "相关基础知识直接教清定义与条件，题目前不加‘通用拓展’、‘共同核心题’、‘画像增补题’等备课标签。"
    "题设推导与教材原话在审核依据中分清，不给未被来源支持的结论伪造引文；仅在确实影响理解时就地说明适用范围。"
    "不因假设性风险缩小学习目标、降低专业深度或增加无用确认；实际限制简要说明并给出可执行的办法。"
    "必要数学条件、预测时点、任务规则和概念辨析仍完整讲清，不用删知识、变浅小字或免责声明替代教学。"
    "上述要求仅针对展示正文；JSON结构、关联ID和状态字段仍严格遵守协议，教学所需的代码和公式保持原意。"
)


_PHRASE_REPLACEMENTS = (
    ("依据课程来源", "从学习内容来看"),
    ("根据课程来源", "结合当前学习内容"),
    ("基于课程来源", "结合当前学习内容"),
    ("本地确定性演示", "可复现演示"),
    ("本地确定性", "可复现"),
    ("上下文重点", "本轮重点"),
    ("冻结课程来源", "已选课程内容"),
    ("课程来源", "课程内容"),
    ("来源版本", "材料范围"),
    ("来源片段", "相关片段"),
    ("证据不足", "现有信息还不够"),
    ("证据链", "核对过程"),
    ("学习证据", "学习记录"),
    ("评分证据", "评分记录"),
)

_INTERNAL_LABEL = re.compile(
    r"(?i)\b(?:source[_ -]?ref(?:[_ -]?id)?|knowledge[_ -]?point[_ -]?id|"
    r"context[_ -]?fingerprint|content[_ -]?hash|rubric[_ -]?version|"
    r"generation[_ -]?mode|run[_ -]?id|message[_ -]?id|event[_ -]?id)\b"
    r"\s*[:=：]?\s*[A-Za-z0-9_.:-]*"
)
_INTERNAL_TOKEN = re.compile(
    r"(?i)\b(?:demo-)?(?:kp|ch|ref|src|qv|art|snapshot|source|event|trace|run|claim|chat|task)-[a-z0-9-]{4,}\b|"
    r"\bf\d+\.[a-z0-9_.-]+\.v\d+\b|\b[a-f0-9]{24,}\b|"
    r"\b(?:deterministic_local|llm_grounded|reasoning_content)\b"
)


_TEACHING_CODE = re.compile(r"(^```[^\n]*\n.*?(?:^```[ \t]*(?=\n|$)|\Z)|^~~~[^\n]*\n.*?(?:^~~~[ \t]*(?=\n|$)|\Z)|`[^`\n]+`)", re.MULTILINE | re.DOTALL)


def feynman_material_text(content: str) -> str:
    """Remove repeated document wrappers, never rewrite teaching or saved work."""
    text = content.strip()
    repeated_title = re.compile(r"\A(# [^\n]+)\n+(?:## 复述任务\n+)?\1(?=\n|$)")
    while repeated_title.match(text):
        text = repeated_title.sub(r"\1", text, count=1)
    # Older assembly put an empty task heading before the model's own sections.
    text = re.sub(r"\A(# [^\n]+)\n+## 复述任务\n+(?=## )", r"\1\n\n", text, count=1)
    code_spans = [(match.start(), match.end()) for match in _TEACHING_CODE.finditer(text)]
    goals = [match for match in re.finditer(r"^## 学习目标\s*\n", text, re.M)
             if not any(start <= match.start() < end for start, end in code_spans)]
    while len(goals) > 1:
        earlier, later = goals[-2:]
        if text[earlier.end():later.start()].strip() != text[later.end():].strip():
            break
        text = text[:later.start()].rstrip()
        goals.pop()
    return text


def teacher_text(value: Any, *, preserve_boundary: bool = False, names: dict[str, str] | None = None) -> str:
    """Clean explanatory prose while preserving Markdown teaching code byte for byte."""
    result = map_teaching_prose(value, lambda part: _teacher_prose(part, preserve_boundary=True, names=names))
    return result if preserve_boundary else result.strip()


def resource_failure_feedback(value: Any) -> str:
    """Display review findings as feedback; retain stored details for retries."""
    text = str(value or "")
    def learning_prose(part: str) -> str:
        # Reviewers use these paths to locate a passage internally. Keep the
        # useful location, but speak in the learner's displayed order (1-based).
        labels = {
            "concepts": "概念", "sections": "章节", "slides": "幻灯片",
            "examples": "示例", "questions": "题目", "quiz": "小测",
            "exercises": "练习", "steps": "实践步骤", "practiceSteps": "实践步骤",
            "explanation": "讲解", "description": "说明", "title": "标题",
            "answer": "答案", "solution": "解答", "question": "题干",
            "stem": "题干", "options": "选项", "code": "代码",
            "starterCode": "练习代码", "output": "运行结果", "content": "正文",
        }
        def passage_name(match: re.Match) -> str:
            parts = []
            for field, index in re.findall(r"\.([A-Za-z_][A-Za-z0-9_]*)(?:\[(\d+)\])?", match[0]):
                label = labels.get(field, "对应内容")
                parts.append(f"第{int(index) + 1}项{label}" if index else label)
            return "的".join(parts)
        part = re.sub(r"(?<![A-Za-z0-9_.])content(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[\d+\])?)+", passage_name, part)
        for field, label in (("dependency_resources", "配套内容"), ("code_sandbox", "代码练习"),
                             ("requiredChecks", "运行检查"), ("interactive_model", "交互实验"),
                             ("training_task", "实训任务书"), ("objective", "学习目标"),
                             ("practiceSteps", "实践步骤"), ("steps", "实践步骤"),
                             ("checkpoints", "检查点"), ("rubric", "评分要求"),
                             ("deliverables", "交付内容")):
            part = re.sub(r"(?<![A-Za-z0-9_])" + field + r"(?![A-Za-z0-9_-])", label, part)
        part = re.sub(r"(?<![A-Za-z0-9_])checkpoint-(\d+)(?![A-Za-z0-9_])", r"检查点\1", part)
        part = re.sub(r"(?<![A-Za-z0-9_])step-(\d+)(?![A-Za-z0-9_])", r"第\1步", part)
        part = re.sub(r"(?<![A-Za-z0-9_])rubric-[a-z0-9_]+(?![A-Za-z0-9_])", "评分要求", part)
        part = re.sub(r"(?<![A-Za-z0-9_])deliverable-[a-z0-9_]+(?![A-Za-z0-9_])", "报告交付要求", part)
        return part

    def feedback_text(value: str) -> str:
        return teacher_text(map_teaching_prose(value, learning_prose))
    for prefix, message in (
        ("资源规划模型调用失败：", "这次学习安排没有完整准备好，请重试。你选择的课程和学习要求仍会保留。"),
        ("资源审核模型调用失败：", "这次内容核对未能完成，请重试。已准备的内容仍会保留。"),
        ("真实模型生成失败：", "学习内容暂时没有完整生成，请重试。"),
        ("真实模型结构化重试失败：", "学习内容暂时没有完整生成，请重试。"),
    ):
        if text.startswith(prefix):
            return message
    summary, marker, raw = text.partition("具体审核意见：")
    if not marker:
        return feedback_text(text)
    parts = [summary.strip()]
    try:
        findings = json.loads(raw)
    except (ValueError, TypeError):
        # Historical timeline events may have truncated the JSON mid-field.
        findings = []
    for finding in findings if isinstance(findings, list) else []:
        if isinstance(finding, str):
            parts.append(finding)
        elif isinstance(finding, dict):
            for key in ("issue", "reason", "requiredFix", "fix", "recommendation"):
                if isinstance(finding.get(key), str):
                    parts.append(finding[key])
    return feedback_text("\n".join(dict.fromkeys(part for part in parts if part))) or "这份内容还需要调整，请重试。"


def completion_description(value: Any) -> str:
    """Project legacy structured completion rules without changing saved evidence."""
    if isinstance(value, str):
        text = value.strip()
        if text.startswith(("{", "[")):
            try:
                value = json.loads(text)
            except (ValueError, TypeError):
                try:
                    value = ast.literal_eval(text)
                except (ValueError, SyntaxError):
                    return "请打开资源查看具体学习要求。"
        else:
            return teacher_text(text)
    if isinstance(value, dict):
        parts = [value.get("description") or value.get("summary") or "", value.get("criteria") or []]
    elif isinstance(value, list):
        parts = value
    else:
        return ""
    return "\n".join(dict.fromkeys(text for part in parts if (text := completion_description(part))))


def video_recommendation_reason(value: Any, *, title: str = "") -> str:
    """Keep useful source descriptions without presenting platform promotion as advice."""
    text = teacher_text(value)
    promotion = re.compile(
        r"三连|跪求|求赞|点赞|投币|抽奖|赠书|赠送活动|评论统计|留言总计|"
        r"随机抽|片头|制作不易|置顶评论|关注不迷路|一键关注|订阅我的|规则稍微有点绕|"
        r"资源见评论区|(?:评论区|留言).{0,12}(?:领取|获取资料)|"
        r"欢迎咨询客服|报名咨询|购课咨询|课程咨询|手把手带学|不走弯路|听话必出分|"
        r"课程效果.{0,15}(?:独一档|保证)|专辑有很多知识点精讲|(?:微信号|客服微信)\s*[:：]|"
        r"来\s*源\s*[:：]\s*https?://|原视频\s*[:：]|原作者\s*[:：]|"
        r"(?:字幕|配音).{0,30}(?:AI|人工智能|制作|完成)|"
        r"评论区留言|发布日期|如有不准确之|(?:^|\s)v=[\w-]{6,}|https?://|[\\\\]|"
        r"联网检索结果第\s*\d+\s*条"
    )
    parts = re.split(r"(?<=[。！？!?；;])\s*|[\r\n]+", text)
    cleaned = " ".join(part.strip() for part in parts if part.strip() and not promotion.search(part))
    return cleaned


def map_teaching_prose(value: Any, transform) -> str:
    """Apply a wording transform outside teaching code, preserving its bytes."""
    parts = _TEACHING_CODE.split(str(value or ""))
    return "".join(part if index % 2 else transform(part) for index, part in enumerate(parts))


def teaching_text(value: Any, *, names: dict[str, str] | None = None) -> str:
    """Hide explicit report metadata; never paraphrase an explanation or strip bare numbers."""
    def prose(part: str) -> str:
        for identifier, title in sorted((names or {}).items(), key=lambda pair: len(pair[0]), reverse=True):
            if identifier and title:
                part = re.sub(r"(?<![A-Za-z0-9_-])" + re.escape(identifier) + r"(?![A-Za-z0-9_-])", lambda _: title, part)
        part = re.sub(r'["\']?\bcorrect["\']?\s*[:=]\s*["\']?(true|false|null)\b["\']?',
            lambda m: {"true": "本题回答正确", "false": "本题尚未答对", "null": "本题尚未完成评分"}[m[1].lower()], part, flags=re.I)
        part = re.sub(r'["\']?\bgrading_?status["\']?\s*[:=]\s*["\']?(graded|pending_grading|ungraded)\b["\']?',
            lambda m: "已完成评分" if m[1].lower() == "graded" else "等待评分", part, flags=re.I)
        return re.sub(r'["\']?\b(?:source_?ref_?id|knowledge_?point_?id|chapter_?id|trace_?id|content_?hash|profile_?snapshot_?id|schema_?version|rubric_?version|lock_?version)\b["\']?\s*[:=：]\s*["\']?[\w.:-]+["\']?', '', part, flags=re.I)

    # Code spans/fences use the common protector; math and indented code are
    # teaching content too, even when they contain an internal-looking name.
    def outside_math(part: str) -> str:
        parts = re.split(r'(\$\$[\s\S]*?\$\$|\$[^\n$]+\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|^(?: {4}|\t)[^\n]*(?:\n(?: {4}|\t)[^\n]*)*)', part, flags=re.M)
        return ''.join(piece if i % 2 else prose(piece) for i, piece in enumerate(parts))
    return map_teaching_prose(value, outside_math)


def _teacher_prose(value: Any, *, preserve_boundary: bool = False, names: dict[str, str] | None = None) -> str:
    """Remove implementation narration from prose shown to a learner.

    This is deliberately a narrow projection step. It does not inspect or
    rewrite code, answer keys, source records, or audit payloads.
    """

    text = str(value or "")
    if not text:
        return ""
    for identifier, title in sorted((names or {}).items(), key=lambda pair: len(pair[0]), reverse=True):
        if identifier and title:
            text = re.sub(r"(?<![A-Za-z0-9_-])" + re.escape(identifier) + r"(?![A-Za-z0-9_-])", lambda _: title, text)
    text = re.sub(
        r"[\"']?\bcorrect[\"']?\s*[:=]\s*[\"']?(true|false|null)\b[\"']?",
        lambda match: {"true": "本题回答正确", "false": "本题尚未答对", "null": "本题尚未完成评分"}[match[1].lower()],
        text, flags=re.IGNORECASE,
    )
    state_labels = {
        "graded": "已完成评分", "pending_grading": "等待评分", "needs_review": "需要进一步确认",
        "insufficient_evidence": "还需要更多学习记录", "partially_supported": "部分内容仍需确认",
        "completed": "已完成", "failed": "暂未完成", "pending": "等待处理",
    }
    text = re.sub(
        r"[\"']?\b(?:grading_status|gradingStatus|status)[\"']?\s*[:=]\s*[\"']?([a-z_]+)\b[\"']?",
        lambda match: state_labels.get(match[1].lower(), ""), text, flags=re.IGNORECASE,
    )
    text = re.sub(r"\b(?:graded|pending_grading|needs_review|insufficient_evidence|partially_supported)\b", lambda match: state_labels[match[0]], text)
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
    text = re.sub(r"\s+([，。！？；：,.!?;:])", r"\1", text)
    text = re.sub(r"[，,]\s*(?=[，,。；;])", "", text)
    text = re.sub(r"(?:；|，|,)?\s*(?:模型模式|生成模式|评分规则)\s*(?:为|是)?\s*[A-Za-z0-9_.-]*", "", text)
    return text if preserve_boundary else text.strip()
