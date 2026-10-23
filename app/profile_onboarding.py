"""Resumable natural-language onboarding for the initial learner profile."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import (
    DBCourse,
    DBOnboardingPersonalEvidence,
    DBOnboardingSession,
    DBOnboardingTurn,
    DBProfileSnapshot,
    DBStudentProfile,
    DBUser,
)
from document_parser import DocumentParseError, parse_document


DIMENSIONS = ("background", "goal", "foundation", "difficulty", "preference")
DIMENSION_LABELS = {
    "background": "学习背景",
    "goal": "学习目标",
    "foundation": "当前基础",
    "difficulty": "主要困难",
    "preference": "学习偏好",
}
QUESTIONS = {
    "background": "先认识一下你。你目前的学校、年级或专业是什么？",
    "goal": "这门课你最想达成什么目标？可以说说近期任务或更长远的计划。",
    "foundation": "你已经学过哪些相关内容？哪些基础比较有把握？",
    "difficulty": "目前最容易卡住你的是什么？可以是知识点、题型或学习过程。",
    "preference": "你更喜欢怎样学习？例如先看例子、分步推导、画图理解或动手写代码。",
}
KNOWN_MAJORS = (
    "人工智能", "计算机科学与技术", "软件工程", "数据科学与大数据技术",
    "电子信息工程", "自动化", "网络工程", "信息安全",
)
FALLBACK_FIELDS = {
    "background": ("major", "专业方向", "text"),
    "goal": ("learning_goals", "学习目标", "list"),
    "foundation": ("knowledge_base", "基础自述", "text"),
    "difficulty": ("weak_points", "当前困难", "list"),
    "preference": ("interaction_preferences", "学习偏好", "list"),
}
PERSONAL_EVIDENCE_TYPES = {"transcript": "成绩单", "timetable": "课程表"}
PERSONAL_EVIDENCE_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
COURSE_MATERIAL_MARKERS = ("课件", "教材", "课程大纲", "教学大纲", "syllabus", "textbook", "slides")
INITIAL_PROFILE_VERSION = "onboarding.initial.v1"

CONTINUOUS_DIMENSIONS = (
    "knowledge_mastery",
    "misconception_profile",
    "understanding_fluency_transfer",
    "cognitive_processing",
    "learning_strategy",
    "metacognition",
    "motivation_and_purpose",
    "affect_resilience",
    "interaction_preference",
    "learning_context",
)
CONTINUOUS_DIMENSION_LABELS = {
    "knowledge_mastery": "知识基础与掌握度",
    "misconception_profile": "易错点与概念理解",
    "understanding_fluency_transfer": "理解和迁移能力",
    "cognitive_processing": "处理复杂内容的方式",
    "learning_strategy": "学习方法",
    "metacognition": "自我判断和调整",
    "motivation_and_purpose": "学习目标和动力",
    "affect_resilience": "信心和抗挫能力",
    "interaction_preference": "喜欢怎样互动学习",
    "learning_context": "学习环境和安排",
}
CONTINUOUS_ALLOWED_FIELDS = {
    "major", "target_course", "knowledge_base", "cognitive_style", "motivation_type",
    "focus_level", "cognitive_load", "frustration_index", "learning_goals",
    "weak_points", "interaction_preferences", "misconception_patterns",
}

CONTINUOUS_PROFILE_EXTRACTION_PROMPT = """
你是 EduMatrix 的持续学情画像理解 Agent。学生正在用自然语言补充或纠正自己的学习情况。
请只根据学生本轮原话提取有依据的画像变化，不要把猜测当成事实；问题和结论都要用学生看得懂的说法。
你同时是一位耐心的老师：先用一两句自然回应接住学生，再提出一个可以继续聊的开放问题。问题可以一次串起两个或三个相关方面，允许在后续回合再次核对同一件事。不要使用“画像、维度、置信度、证据、上下文、约束、确定性”等系统词，也不要向学生索要字段。

只输出一个 JSON 对象：
{
  "understanding": "用人话概括本轮原话说明了什么变化",
  "assistant_reply": "像老师一样回应学生，具体提到他刚才说的经历，2—4 句",
  "follow_up_question": "下一轮自然、详细、可回答的问题，1—3 句",
  "fields": [
    {"key":"已有字段键", "label":"人话标签", "value":"字段值或字符串数组", "evidence":"原话依据", "confidence":0.0}
  ],
  "dimensions": [
    {"key":"十维键", "label":"人话标签", "value":"这轮反映的状态", "score":0.0, "status":"当前状态", "evidence":"原话依据", "confidence":0.0}
  ],
  "weak_point_attribution": [
    {"weak_point":"薄弱点", "reason":"可能原因", "evidence":"原话依据", "confidence":0.0}
  ],
  "uncertainties": ["还需要学生确认或补充的内容"]
}

fields 只能使用已有字段键；dimensions 只能使用十维键。没有原话依据的内容放入 uncertainties，不能写入 fields 或 dimensions。
""".strip()

CONTINUOUS_UPDATE_REMINDER_DAYS = 3

# The update conversation uses everyday situations instead of exposing the
# internal ten-dimension vocabulary.  A model may return a better follow-up;
# these prompts are the stable floor used when the model has not supplied one.
CONTINUOUS_CONVERSATION_GUIDES = (
    {
        "topics": ("knowledge_mastery", "misconception_profile", "affect_resilience"),
        "question": "最近有没有哪一次学习让你觉得“终于想通了”，或者反复试了几次还是卡住？当时你在做什么，最后怎么收尾的？",
    },
    {
        "topics": ("understanding_fluency_transfer", "cognitive_processing"),
        "question": "如果要把最近学会的一件事讲给同学听，你会怎么举例？换一道没见过的题时，哪一步最需要停下来想一想？",
    },
    {
        "topics": ("learning_strategy", "metacognition"),
        "question": "遇到不会的内容时，你通常会先重看、找例子、动手试，还是换个角度问人？你会用什么信号判断“这次真的会了”，而不只是看懂了？",
    },
    {
        "topics": ("motivation_and_purpose", "learning_context", "cognitive_processing"),
        "question": "接下来一段时间，你最想把所学用到哪里？平时什么时间和场景最适合你学习，怎样安排会让你比较容易进入状态？",
    },
    {
        "topics": ("interaction_preference", "affect_resilience", "learning_strategy"),
        "question": "如果我陪你练习，你更希望先看一个完整例子、边做边提示，还是先自己试再一起复盘？遇到连续出错时，什么样的反馈会让你愿意再试一次？",
    },
    {
        "topics": ("knowledge_mastery", "misconception_profile", "metacognition"),
        "question": "回想最近的一次练习或测验，哪道题的结果和你原先预想的不一样？现在再做一次，你会先检查什么？",
    },
    {
        "topics": ("learning_context", "cognitive_processing", "interaction_preference"),
        "question": "如果今天只有二十分钟，你会怎样分配这段时间？什么情况下你会希望我把内容拆小一点，什么情况下又可以连续挑战几步？",
    },
)

CONTINUOUS_FORBIDDEN_LEARNER_WORDS = ("画像", "维度", "置信度", "证据", "内部", "prompt", "trace", "ID")


def _continuous_candidate_list(turn: DBOnboardingTurn | None) -> list[dict[str, Any]]:
    if not turn:
        return []
    candidate = turn.extracted_candidates or {}
    dimensions = candidate.get("dimensions") or []
    if isinstance(dimensions, dict):
        dimensions = [dimensions]
    return [item for item in dimensions if isinstance(item, dict) and item.get("key") in CONTINUOUS_DIMENSIONS]


def _continuous_coverage(turns: list[DBOnboardingTurn]) -> dict[str, int]:
    coverage = {key: 0 for key in CONTINUOUS_DIMENSIONS}
    for turn in turns:
        for item in _continuous_candidate_list(turn):
            coverage[str(item.get("key"))] += 1
    return coverage


def _continuous_next_question_from_turns(turns: list[DBOnboardingTurn]) -> str:
    coverage = _continuous_coverage(turns)
    for guide in CONTINUOUS_CONVERSATION_GUIDES:
        if any(coverage.get(topic, 0) == 0 for topic in guide["topics"]):
            return guide["question"]
    # Once every angle has one signal, revisit the least explored angle. This
    # keeps the conversation open for richer evidence instead of stopping at
    # an arbitrary number of turns.
    least = min(coverage.values()) if coverage else 0
    for guide in CONTINUOUS_CONVERSATION_GUIDES:
        if any(coverage.get(topic, 0) == least for topic in guide["topics"]):
            return guide["question"]
    return CONTINUOUS_CONVERSATION_GUIDES[0]["question"]


def _continuous_suggested_prompts(turns: list[DBOnboardingTurn]) -> list[str]:
    coverage = _continuous_coverage(turns)
    prompts: list[str] = []
    for guide in CONTINUOUS_CONVERSATION_GUIDES:
        if any(coverage.get(topic, 0) == 0 for topic in guide["topics"]):
            prompts.append(guide["question"].split("？", 1)[0] + "？")
        if len(prompts) >= 3:
            break
    return prompts or ["最近哪一步比以前顺手了？", "哪一次练习让你想再试一次？", "接下来最想把什么用起来？"]


def _learner_safe_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text or any(word.lower() in text.lower() for word in CONTINUOUS_FORBIDDEN_LEARNER_WORDS):
        return ""
    return text[:1200]


def _friendly_continuous_reply(answer: str, understanding: str = "") -> str:
    clean = _learner_safe_text(understanding)
    # Models and the local demo fixture sometimes prefix the summary with a
    # conversational marker.  Strip it before composing the teacher reply so
    # the learner never sees nested echoes such as “我听见你提到：你刚才讲的是：…。。”。
    clean = re.sub(r"^(?:我听见你提到|我听到的是|你刚才讲的是)[:：]\s*", "", clean).strip()
    clean = clean.rstrip("，。；、!?！？ ")
    if clean:
        return f"你提到“{_clip(clean, 96)}”，这让情况清楚多了。我先记住这条线索，接下来会陪你把它变成更合适的练习和安排。"
    excerpt = answer.strip().replace("\n", " ").rstrip("，。；、!?！？ ")[:72]
    return f"谢谢你把这段经历说得这么具体（“{excerpt}”）。我先记住这条线索，再陪你把它讲完整。"


def _demo_continuous_candidates(answer: str, question: str, turn_index: int) -> dict[str, Any]:
    """Small deterministic fixture for the local browser demo only.

    Production keeps the configured model path.  The fixture mirrors the
    student's own words so an offline demo can exercise the same confirmation
    and snapshot protocol without inventing unrelated facts.
    """
    guide = CONTINUOUS_CONVERSATION_GUIDES[min(max(turn_index, 0), len(CONTINUOUS_CONVERSATION_GUIDES) - 1)]
    evidence = answer.strip()[:500]
    dimensions = []

    def dimension_signal(key: str) -> str:
        """Return a human, topic-specific signal for the offline demo.

        The production path uses the configured model.  The local fixture is
        deliberately conservative, but it should still distinguish what the
        learner actually said instead of copying one status to every angle.
        """
        if key == "knowledge_mastery":
            if any(word in answer for word in ("顺手", "独立", "完成", "想通", "会了")):
                return "基础动作已经比较顺手"
            if any(word in answer for word in ("不确定", "卡", "混淆", "不会")):
                return "换一种说法时还需要再核对"
            return "正在建立稳定的把握"
        if key == "misconception_profile":
            if any(word in answer for word in ("混淆", "混在", "不确定", "不太确定", "容易错")):
                return "相近概念容易混在一起，需要做对比练习"
            return "开始能说清关键区别"
        if key == "affect_resilience":
            if any(word in answer for word in ("焦虑", "紧张", "挫折", "出错", "卡")):
                return "遇到难点会紧张，分段练习会更轻松"
            return "愿意在出错后继续尝试"
        if key == "understanding_fluency_transfer":
            if any(word in answer for word in ("项目", "上线", "面试", "讲清楚", "新题")):
                return "正在把学到的东西迁移到项目和表达中"
            return "正在练习把理解说出来、用起来"
        if key == "cognitive_processing":
            if any(word in answer for word in ("例子", "图", "结论", "公式", "拆")):
                return "先看整体，再把复杂内容拆开"
            return "正在找到适合自己的理解节奏"
        if key == "learning_strategy":
            if any(word in answer for word in ("实验", "动手", "先看", "复盘")):
                return "先抓住要点，再用小实验验证"
            return "正在形成自己的练习方法"
        if key == "metacognition":
            if any(word in answer for word in ("告诉我哪里", "判断", "信号", "错了", "检查")):
                return "会用结果和反馈检查自己是否真的掌握"
            return "开始留意自己什么时候算真正会了"
        if key == "motivation_and_purpose":
            if any(word in answer for word in ("项目", "上线", "面试", "目标", "想把")):
                return "希望把所学变成可交付的项目能力"
            return "正在把学习和实际目标连起来"
        if key == "interaction_preference":
            if any(word in answer for word in ("例子", "图", "动手", "提示", "告诉我")):
                return "喜欢先看例子，再自己尝试并及时复盘"
            return "更适合边聊边试、及时调整"
        if key == "learning_context":
            if any(word in answer for word in ("通勤", "碎", "今天只有", "分钟", "时间")):
                return "适合短时、分段、随时可以继续的安排"
            return "正在寻找更容易进入状态的学习时段"
        return "正在形成自己的方法"

    for index, key in enumerate(guide["topics"]):
        status = dimension_signal(key)
        dimensions.append({
            "key": key,
            "label": CONTINUOUS_DIMENSION_LABELS[key],
            "value": status,
            "status": status,
            "score": round(min(0.9, 0.52 + turn_index * 0.04 + index * 0.03), 2),
            "evidence": evidence,
            "confidence": 0.72,
        })
    fields: list[dict[str, Any]] = []
    goal_sentences = [
        part.strip()
        for part in re.split(r"[。！？；;]", answer)
        if part.strip() and any(word in part for word in ("我想", "目标", "计划", "打算", "上线", "面试"))
    ]
    if goal_sentences:
        fields.append({"key": "learning_goals", "label": "接下来想达成的事", "value": ["。".join(goal_sentences)[:180]], "kind": "list", "evidence": evidence, "confidence": 0.72})
    if any(word in answer for word in ("例子", "代码", "画图", "分步", "复盘", "提示")):
        fields.append({"key": "interaction_preferences", "label": "更顺手的学习方式", "value": ["先看具体例子，再动手验证"], "kind": "list", "evidence": evidence, "confidence": 0.72})
    if any(word in answer for word in ("通勤", "碎", "今天只有", "分钟")):
        fields.append({"key": "learning_context", "label": "适合你的学习安排", "value": ["短时、分段完成，随时可以继续"], "kind": "list", "evidence": evidence, "confidence": 0.72})
    understanding = answer.strip().replace(chr(10), " ")[:160]
    return {
        "mode": "continuous_profile_update",
        "summary": understanding,
        "understanding": understanding,
        "fields": fields,
        "dimensions": dimensions,
        "weakPointAttribution": [],
        "uncertainties": [],
        "source": "local-demo-model",
        "originalAnswer": answer,
        "assistantReply": _friendly_continuous_reply(answer, understanding),
        "followUpQuestion": _continuous_next_question_from_turns([]) if turn_index == 0 else guide["question"],
        "question": question,
    }

PROFILE_EXTRACTION_PROMPT = """
你是 EduMatrix 的学习画像理解 Agent。请理解学生的自然语言回答，把明确说出的信息和合理的语义归纳整理为候选画像；不要把没有说过的事实当成事实，也不要输出提示词、推理过程或额外解释。

只输出一个 JSON 对象，结构必须是：
{
  "understanding": "用人话概括本轮回答体现的学习画像",
  "fields": [
    {"key":"字段键", "label":"字段名称", "value":"字段值或字符串数组", "kind":"text 或 list", "evidence":"来自原话的依据", "confidence":0.0}
  ],
  "uncertainties": ["仍需学生确认或补充的内容"]
}

字段只表达本轮问题维度内的信息。value 必须能在学生原话中找到依据；confidence 是 0 到 1 之间的数。没有依据的内容放入 uncertainties，不要写入 fields。
misconception_patterns 的 value 使用对象，键为易混淆主题，值为 0 到 1 之间的混淆程度；不要将该对象转换成字符串。
""".strip()

_ALLOWED_MODEL_FIELDS = {
    "background": {"major", "school", "background_context", "target_course", "learning_context"},
    "goal": {"learning_goals", "motivation_type", "goal_context", "target_course"},
    "foundation": {"knowledge_base", "foundation_context", "focus_level", "cognitive_load"},
    "difficulty": {"weak_points", "difficulty_context", "frustration_index", "cognitive_load", "misconception_patterns"},
    "preference": {"interaction_preferences", "cognitive_style", "preference_context", "focus_level", "cognitive_load"},
}
_LIST_MODEL_FIELDS = {"learning_goals", "weak_points", "interaction_preferences"}
_NUMERIC_MODEL_FIELDS = {"focus_level", "cognitive_load", "frustration_index"}

# The structured prompt names the canonical keys, but a real model can still
# return a clear semantic synonym (for example ``basis_level`` for the
# foundation dimension).  Keep the public/profile schema strict while
# normalizing only an explicit, dimension-scoped set of aliases.  This avoids
# turning a valid natural-language answer into ``extraction_failed`` merely
# because the provider chose a different label, without accepting arbitrary
# unverified fields.
_MODEL_FIELD_ALIASES = {
    "background": {
        "education": "background_context",
        "education_background": "background_context",
        "background": "background_context",
        "background_info": "background_context",
        "grade": "background_context",
        "year": "background_context",
    },
    "goal": {
        "goal": "learning_goals",
        "goals": "learning_goals",
        "learning_goal": "learning_goals",
        "learning_goals": "learning_goals",
        "target": "learning_goals",
        "study_goal": "learning_goals",
    },
    "foundation": {
        "foundation": "knowledge_base",
        "foundation_level": "knowledge_base",
        "basis_level": "knowledge_base",
        "current_basis": "knowledge_base",
        "current_foundation": "knowledge_base",
        "knowledge_level": "knowledge_base",
        "prior_knowledge": "knowledge_base",
    },
    "difficulty": {
        "difficulty": "weak_points",
        "difficulties": "weak_points",
        "main_difficulty": "weak_points",
        "challenge": "weak_points",
        "challenges": "weak_points",
        "weak_point": "weak_points",
    },
    "preference": {
        "preference": "interaction_preferences",
        "learning_preference": "interaction_preferences",
        "learning_preferences": "interaction_preferences",
        "study_preference": "interaction_preferences",
        "study_preferences": "interaction_preferences",
        "style": "cognitive_style",
    },
}


class OnboardingError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _split_items(value: str) -> list[str]:
    items = [item.strip(" -") for item in re.split(r"[\n；;。]+", value) if item.strip(" -")]
    return items or [value.strip()]


def _field(key: str, label: str, value: str, kind: str = "text") -> dict[str, str]:
    return {"key": key, "label": label, "value": value.strip(), "kind": kind}


def _signal_field(
    key: str,
    label: str,
    value: Any,
    *,
    evidence: str,
    kind: str = "text",
    confidence: float = 0.82,
) -> dict[str, Any]:
    """Create a human-readable candidate derived from explicit learner wording.

    Registration is intentionally conservative: these are *candidates* shown for
    confirmation, never silent profile writes.  Numeric controls are included
    only when the wording contains a clear signal (time pressure, confidence,
    anxiety, etc.).
    """
    return {
        "key": key,
        "label": label,
        "value": value,
        "kind": kind,
        "evidence": evidence[:240],
        "confidence": max(0.0, min(1.0, float(confidence))),
        "source": "conversation_signal",
    }


def _derived_signal_fields(dimension: str, text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Derive extra, explainable registration signals from one natural answer."""
    fields: list[dict[str, Any]] = []
    highlights: list[str] = []
    lowered = text.casefold()

    def add(key: str, label: str, value: Any, *, kind: str = "text", confidence: float = 0.82, highlight: str = ""):
        fields.append(_signal_field(key, label, value, evidence=text, kind=kind, confidence=confidence))
        if highlight:
            highlights.append(highlight)

    if dimension == "background":
        if any(token in text for token in ("工作", "公司", "项目", "上线", "实习", "岗位")):
            add("learning_context", "学习情境", "工作/项目驱动", highlight="你更像是在真实项目里边做边学")
        elif any(token in text for token in ("大一", "大二", "大三", "大四", "在校", "学生")):
            add("learning_context", "学习情境", "在校学习", highlight="你当前处在有课程节奏的学习阶段")
        elif any(token in text for token in ("自学", "业余", "下班", "通勤")):
            add("learning_context", "学习情境", "自主/碎片化学习", highlight="你更需要能嵌入日常的学习安排")
        if any(token in lowered for token in ("转行", "就业", "求职", "找工作", "岗位")):
            add("motivation_type", "学习动力", "职业发展", highlight="后续会优先连接到岗位任务")
    elif dimension == "goal":
        if any(token in text for token in ("考试", "成绩", "及格", "考研", "证书")):
            add("motivation_type", "学习动力", "考试/达标", highlight="你希望先把目标拆成可检查的达标节点")
        elif any(token in text for token in ("项目", "上线", "工作", "业务", "落地", "部署")):
            add("motivation_type", "学习动力", "项目/工作", highlight="你更在意学完能在真实任务里用起来")
        elif any(token in text for token in ("转行", "就业", "求职", "岗位")):
            add("motivation_type", "学习动力", "职业发展", highlight="后续会把练习往岗位能力上对齐")
        elif any(token in text for token in ("兴趣", "好奇", "探索", "想了解")):
            add("motivation_type", "学习动力", "兴趣探索", highlight="你会更适合用问题驱动的方式逐步深入")
    elif dimension == "foundation":
        if any(token in text for token in ("时间少", "没时间", "碎片", "通勤", "忙")):
            add("cognitive_load", "单次学习负荷", 0.72, confidence=0.78, highlight="你的可用时间比较碎，我会把任务切成更短的段落")
            add("focus_level", "专注节奏", 0.48, confidence=0.74)
        elif any(token in text for token in ("熟练", "做过", "有经验", "比较有把握", "很熟")):
            add("focus_level", "专注节奏", 0.82, confidence=0.76, highlight="你已有可复用的基础，可以更快进入迁移练习")
            add("cognitive_load", "单次学习负荷", 0.34, confidence=0.7)
    elif dimension == "difficulty":
        if any(token in text for token in ("焦虑", "害怕", "挫败", "总是不会", "一看到就", "不敢")):
            add("frustration_index", "受挫感", 0.72, confidence=0.84, highlight="你提到的卡点带有明显压力感，我会先给更稳的反馈")
            add("cognitive_load", "认知负荷", 0.68, confidence=0.8)
        elif any(token in text for token in ("卡住", "容易错", "分不清", "不会", "难")):
            add("frustration_index", "受挫感", 0.52, confidence=0.76, highlight="你有明确卡点，练习会先围绕这些地方建立信心")
            add("cognitive_load", "认知负荷", 0.58, confidence=0.72)
        if any(token in text for token in ("概念", "定义", "公式", "推导", "区别", "辨析")):
            add("misconception_patterns", "易混淆主题", {"概念辨析": 0.62}, confidence=0.7)
    elif dimension == "preference":
        if any(token in text for token in ("碎片", "短一点", "一次", "每天")):
            add("cognitive_load", "单次学习负荷", 0.5, confidence=0.7, highlight="我会尽量让每次学习都有一个小闭环")
        if any(token in text for token in ("自己想", "先想", "提问", "讨论", "对话")):
            add("interaction_preferences", "互动方式", "先提问再讨论", kind="list", confidence=0.78, highlight="我会多留一点思考和追问空间")

    # Keep the candidate list stable and avoid duplicate keys when a model has
    # already supplied the same field; the model result wins in that case.
    return fields, list(dict.fromkeys(highlights))


def _enrich_candidates(dimension: str, answer: str, candidates: dict[str, Any]) -> dict[str, Any]:
    """Merge deterministic, evidence-backed signals into model or fallback output."""
    result = dict(candidates or {})
    existing = list(result.get("fields") or [])
    existing_keys = {str(item.get("key")) for item in existing if isinstance(item, dict)}
    derived, highlights = _derived_signal_fields(dimension, answer)
    existing.extend(item for item in derived if item.get("key") not in existing_keys)
    result["fields"] = existing
    result["signalHighlights"] = list(dict.fromkeys(list(result.get("signalHighlights") or []) + highlights))
    result["originalAnswer"] = result.get("originalAnswer") or answer
    return result


def _clip(text: str, limit: int = 68) -> str:
    compact = " ".join(str(text or "").split())
    return compact if len(compact) <= limit else compact[:limit].rstrip("，。；、 ") + "…"


def conversational_question(session: DBOnboardingSession) -> str:
    """Return the next question as a contextual conversation, not a form label."""
    current = session.current_dimension or DIMENSIONS[0]
    confirmed = session.confirmed_fields or {}
    if not confirmed:
        return "先不用按栏目回答。最近是什么事情让你想学这门课？从正在做的事、感兴趣的方向或遇到的卡点说起都可以。"
    previous = list(confirmed.values())[-1] if confirmed else {}
    previous_text = _clip(previous.get("summary") or "")
    if current == "goal":
        return f"你刚才提到“{previous_text}”。如果这门课学好，你最想先解决什么问题，或完成什么具体事情？"
    if current == "foundation":
        return f"为了把内容接到你的目标上，你已经接触过哪些相关知识或工具？哪些部分你比较有把握？"
    if current == "difficulty":
        return "在刚才说的基础上，哪一类地方最容易让你停下来？可以说一个最近真实遇到的例子。"
    if current == "preference":
        return "如果把这门课变成你的学习搭档，你希望我怎么陪你学：先看例子、画图、推导、写代码，还是边问边练？"
    return "还有什么会影响你学习节奏的事情想告诉我吗？不确定也没关系，我们可以边学边调整。"


def _decorate_turn_candidates(
    session: DBOnboardingSession,
    dimension: str,
    answer: str,
    candidates: dict[str, Any],
    asked_question: str,
) -> dict[str, Any]:
    result = _enrich_candidates(dimension, answer, candidates)
    summary = str(result.get("understanding") or result.get("summary") or answer).strip()
    highlights = list(result.get("signalHighlights") or [])
    if not highlights:
        highlights = [f"我先记住了：{_clip(summary, 82)}"]
    result["summary"] = summary
    result["understanding"] = summary
    result["question"] = asked_question
    echo = _clip(summary, 96).rstrip("，。；、!?！？ ")
    highlight = highlights[0].rstrip("，。；、!?！？ ") if highlights else ""
    result["assistantReply"] = f"我听到的是：{echo}。" + (f" {highlight}。" if highlight else "")
    result["followUpQuestion"] = conversational_question(session)
    return result


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _initial_snapshot_id(owner_public_id: str) -> str:
    digest = hashlib.sha256(owner_public_id.encode("utf-8")).hexdigest()[:32]
    return f"ps-onboarding-{digest}"


def _ensure_profile_not_finalized(db: Session, user: DBUser) -> None:
    if db.get(DBProfileSnapshot, _initial_snapshot_id(user.public_id)) is not None:
        raise OnboardingError("profile_already_finalized", "初始画像已经确认，不能再修改首次资料。")


def extract_candidates(dimension: str, answer: str) -> dict[str, Any]:
    """Deterministic extraction keeps baseline onboarding independent from external models."""

    text = answer.strip()
    if not text:
        raise OnboardingError("empty_answer", "请先说说你的情况。")

    if dimension == "background":
        major = next((item for item in KNOWN_MAJORS if item in text), "")
        if not major:
            match = re.search(r"(?:主修|专业(?:是|为)?|学的是)\s*([^，。；]{2,24})", text)
            major = match.group(1).strip() if match else ""
        school_match = re.search(r"([^，。；]{2,24}(?:大学|学院|学校))", text)
        fields = [_field("major", "专业方向", major)] if major else []
        if school_match:
            fields.append(_field("school", "学校", school_match.group(1)))
        fields.append(_field("background_context", "背景补充", text))
    elif dimension == "goal":
        fields = [_field("learning_goals", "学习目标", "\n".join(_split_items(text)), "list")]
    elif dimension == "foundation":
        fields = [_field("knowledge_base", "基础自述", text)]
    elif dimension == "difficulty":
        fields = [_field("weak_points", "当前困难", "\n".join(_split_items(text)), "list")]
    elif dimension == "preference":
        style = "分步讲解"
        for keyword, label in (
            ("代码", "代码实操导向"), ("图", "视觉演示导向"),
            ("例子", "案例驱动"), ("推导", "分步推导"),
        ):
            if keyword in text:
                style = label
                break
        fields = [
            _field("interaction_preferences", "学习偏好", "\n".join(_split_items(text)), "list"),
            _field("cognitive_style", "建议讲解方式", style),
        ]
    else:
        raise OnboardingError("invalid_dimension", "画像维度无效。")

    return _enrich_candidates(
        dimension,
        text,
        {"dimension": dimension, "fields": fields, "summary": text},
    )


def _normalize_misconception_patterns(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    patterns: dict[str, float] = {}
    for topic, score in raw.items():
        topic = str(topic).strip()
        if not topic:
            continue
        try:
            patterns[topic] = max(0.0, min(1.0, float(score)))
        except (TypeError, ValueError):
            continue
    return patterns


def _model_field(dimension: str, value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    key = str(value.get("key") or "").strip()
    key = _MODEL_FIELD_ALIASES.get(dimension, {}).get(key, key)
    if key not in _ALLOWED_MODEL_FIELDS.get(dimension, set()):
        return None
    label = str(value.get("label") or key).strip()
    raw = value.get("value")
    if isinstance(raw, list):
        normalized = [str(item).strip() for item in raw if str(item).strip()]
    elif key == "misconception_patterns":
        normalized = _normalize_misconception_patterns(raw)
    elif key in _NUMERIC_MODEL_FIELDS:
        try:
            normalized = str(max(0.0, min(1.0, float(raw))))
        except (TypeError, ValueError):
            return None
    else:
        normalized = str(raw or "").strip()
    if not normalized:
        return None
    if key in _LIST_MODEL_FIELDS and isinstance(normalized, str):
        normalized = _split_items(normalized)
    evidence = str(value.get("evidence") or "").strip()
    if not evidence:
        return None
    try:
        confidence = max(0.0, min(1.0, float(value.get("confidence"))))
    except (TypeError, ValueError):
        return None
    return {
        "key": key,
        "label": label,
        "value": normalized,
        "kind": "list" if key in _LIST_MODEL_FIELDS else "text",
        "evidence": evidence,
        "confidence": confidence,
        "source": "deepseek-v4-flash",
    }


def _parse_model_candidates(raw: str, dimension: str, answer: str) -> dict[str, Any]:
    from llm_client import parse_json_object

    payload = parse_json_object(raw)
    understanding = str(payload.get("understanding") or payload.get("summary") or "").strip()
    if not understanding:
        raise ValueError("画像模型输出缺少 understanding")
    fields = [
        field
        for field in (_model_field(dimension, item) for item in payload.get("fields", []))
        if field is not None
    ]
    if not fields:
        raise ValueError("画像模型输出没有可确认字段")
    uncertainties = payload.get("uncertainties") or []
    if isinstance(uncertainties, str):
        uncertainties = _split_items(uncertainties)
    uncertainties = [str(item).strip() for item in uncertainties if str(item).strip()]
    return {
        "dimension": dimension,
        "summary": understanding,
        "understanding": understanding,
        "fields": fields,
        "uncertainties": uncertainties,
        "source": "deepseek-v4-flash",
        "originalAnswer": answer,
    }


async def _extract_candidates_with_model(
    dimension: str,
    answer: str,
    *,
    owner_public_id: str,
) -> dict[str, Any]:
    from app.m5_legacy_calls import audited_legacy_text_call
    from llm_client import AsyncDeterministicEducationLLM, build_async_llm

    llm = build_async_llm(
        provider="openai",
        model="deepseek-v4-flash",
        thinking_mode="max",
        reasoning_effort="max",
        allow_fallback=False,
    )
    if isinstance(llm, AsyncDeterministicEducationLLM):
        # The local/demo profile flow remains useful without an external key:
        # use the same evidence-backed extractor and still require learner
        # confirmation before any profile write.  A configured external model
        # continues through the audited DeepSeek path below.
        result = extract_candidates(dimension, answer)
        result["source"] = "deterministic_local"
        result["modelMeta"] = {
            "provider": "local",
            "model": "deterministic",
            "thinking": "rule_bounded",
            "reasoningEffort": "n/a",
        }
        return result
    if getattr(llm, "model", "") != "deepseek-v4-flash":
        raise RuntimeError("deepseek-v4-flash 未配置，无法进行真实画像理解。")
    trace_id = f"onboarding-profile-{uuid.uuid4().hex}"
    allowed_keys = ", ".join(sorted(_ALLOWED_MODEL_FIELDS.get(dimension, set())))
    user_prompt = (
        f"本轮维度：{DIMENSION_LABELS.get(dimension, dimension)}\n"
        f"本轮 fields.key 只能从以下规范键中选择：{allowed_keys}\n"
        f"学生原话：{answer}\n\n"
        "请按要求只返回 JSON。"
    )
    validator = lambda text: _parse_model_candidates(text, dimension, answer)
    raw = await audited_legacy_text_call(
        llm,
        system_prompt=PROFILE_EXTRACTION_PROMPT,
        user_prompt=user_prompt,
        role="profile_understanding",
        operation="onboarding_profile_extraction",
        capability="profile",
        owner_public_id=owner_public_id,
        input_summary={"dimension": dimension, "answer_chars": len(answer)},
        trace_id=trace_id,
        response_validator=validator,
    )
    result = _parse_model_candidates(raw, dimension, answer)
    result["modelMeta"] = {
        "provider": "openai-compatible",
        "model": "deepseek-v4-flash",
        "thinking": "enabled",
        "reasoningEffort": "max",
        "traceId": trace_id,
    }
    return result


def llm_extract_candidates(
    dimension: str,
    answer: str,
    *,
    owner_public_id: str,
) -> dict[str, Any]:
    """Synchronously bridge the async real-model call into the DB worker thread."""

    return asyncio.run(_extract_candidates_with_model(
        dimension,
        answer,
        owner_public_id=owner_public_id,
    ))


def _continuous_field(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    key = str(value.get("key") or "").strip()
    if key not in CONTINUOUS_ALLOWED_FIELDS:
        return None
    raw = value.get("value")
    if isinstance(raw, list):
        normalized: Any = [str(item).strip() for item in raw if str(item).strip()]
    else:
        normalized = str(raw or "").strip()
    if not normalized:
        return None
    evidence = str(value.get("evidence") or "").strip()
    if not evidence:
        return None
    try:
        confidence = max(0.0, min(1.0, float(value.get("confidence"))))
    except (TypeError, ValueError):
        return None
    if key in {"learning_goals", "weak_points", "interaction_preferences"} and isinstance(normalized, str):
        normalized = _split_items(normalized)
    return {
        "key": key,
        "label": str(value.get("label") or key).strip(),
        "value": normalized,
        "kind": "list" if isinstance(normalized, list) else "text",
        "evidence": evidence,
        "confidence": confidence,
        "source": "deepseek-v4-flash",
    }


def _continuous_dimension(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    key = str(value.get("key") or "").strip()
    if key not in CONTINUOUS_DIMENSIONS:
        return None
    evidence = str(value.get("evidence") or "").strip()
    state = str(value.get("value") or value.get("status") or "").strip()
    if not evidence or not state:
        return None
    score = value.get("score")
    try:
        score = max(0.0, min(1.0, float(score))) if score is not None else None
    except (TypeError, ValueError):
        score = None
    try:
        confidence = max(0.0, min(1.0, float(value.get("confidence"))))
    except (TypeError, ValueError):
        return None
    return {
        "key": key,
        "label": str(value.get("label") or CONTINUOUS_DIMENSION_LABELS[key]).strip(),
        "value": state,
        "score": score,
        "status": str(value.get("status") or state).strip(),
        "evidence": evidence,
        "confidence": confidence,
        "source": "deepseek-v4-flash",
    }


def _continuous_attribution(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    weak_point = str(value.get("weak_point") or value.get("weakPoint") or "").strip()
    reason = str(value.get("reason") or "").strip()
    evidence = str(value.get("evidence") or "").strip()
    if not weak_point or not reason or not evidence:
        return None
    try:
        confidence = max(0.0, min(1.0, float(value.get("confidence"))))
    except (TypeError, ValueError):
        return None
    return {
        "weakPoint": weak_point,
        "reason": reason,
        "evidence": evidence,
        "confidence": confidence,
        "source": "deepseek-v4-flash",
    }


def _parse_continuous_model_candidates(raw: str, answer: str) -> dict[str, Any]:
    from llm_client import parse_json_object

    payload = parse_json_object(raw)
    understanding = str(payload.get("understanding") or payload.get("summary") or "").strip()
    if not understanding:
        raise ValueError("持续画像模型输出缺少 understanding")
    fields = [item for item in (_continuous_field(value) for value in payload.get("fields", [])) if item]
    dimensions = [item for item in (_continuous_dimension(value) for value in payload.get("dimensions", [])) if item]
    attributions = [item for item in (_continuous_attribution(value) for value in payload.get("weak_point_attribution", [])) if item]
    uncertainties = payload.get("uncertainties") or []
    if isinstance(uncertainties, str):
        uncertainties = _split_items(uncertainties)
    return {
        "mode": "continuous_profile_update",
        "summary": understanding,
        "understanding": understanding,
        "fields": fields,
        "dimensions": dimensions,
        "weakPointAttribution": attributions,
        "uncertainties": [str(item).strip() for item in uncertainties if str(item).strip()],
        "assistantReply": _learner_safe_text(payload.get("assistant_reply") or payload.get("assistantReply")),
        "followUpQuestion": _learner_safe_text(payload.get("follow_up_question") or payload.get("followUpQuestion")),
        "source": "deepseek-v4-flash",
        "originalAnswer": answer,
    }


def _profile_prompt_projection(profile: DBStudentProfile | None) -> dict[str, Any]:
    if profile is None:
        return {}
    return {
        "major": profile.major or "",
        "target_course": profile.target_course or "",
        "knowledge_base": profile.knowledge_base or "",
        "cognitive_style": profile.cognitive_style or "",
        "motivation_type": profile.motivation_type or "",
        "focus_level": profile.focus_level,
        "cognitive_load": profile.cognitive_load,
        "frustration_index": profile.frustration_index,
        "learning_goals": list(profile.learning_goals or []),
        "weak_points": list(profile.weak_points or []),
        "interaction_preferences": list(profile.interaction_preferences or []),
        "dimensions": dict(profile.dimension_states or {}),
    }


async def _extract_continuous_candidates_with_model(
    answer: str,
    *,
    owner_public_id: str,
    profile: DBStudentProfile | None,
    course_context: dict[str, Any],
    question: str = "",
    conversation_history: list[dict[str, Any]] | None = None,
    covered_dimensions: dict[str, int] | None = None,
) -> dict[str, Any]:
    from app.m5_legacy_calls import audited_legacy_text_call
    from llm_client import AsyncDeterministicEducationLLM, build_async_llm

    llm = build_async_llm(
        provider="openai",
        model="deepseek-v4-flash",
        thinking_mode="max",
        reasoning_effort="max",
        allow_fallback=False,
    )
    if isinstance(llm, AsyncDeterministicEducationLLM) or getattr(llm, "model", "") != "deepseek-v4-flash":
        raise RuntimeError("deepseek-v4-flash 未配置，无法进行真实画像更新理解。")
    trace_id = f"profile-update-{uuid.uuid4().hex}"
    user_prompt = (
        f"当前课程：{course_context.get('title') or '当前课程'}（{course_context.get('courseId') or '未指定'}）\n"
        f"已有画像摘要：{json.dumps(_profile_prompt_projection(profile), ensure_ascii=False)}\n"
        f"这轮老师刚刚问：{question or '最近的学习经历'}\n"
        f"此前对话（只用于承接，不要原样复述系统字段）：{json.dumps((conversation_history or [])[-6:], ensure_ascii=False)}\n"
        f"已经聊到的方面计数：{json.dumps(covered_dimensions or {}, ensure_ascii=False)}\n"
        f"学生本轮原话：{answer}\n\n只返回 JSON。"
    )
    validator = lambda text: _parse_continuous_model_candidates(text, answer)
    raw = await audited_legacy_text_call(
        llm,
        system_prompt=CONTINUOUS_PROFILE_EXTRACTION_PROMPT,
        user_prompt=user_prompt,
        role="profile_understanding",
        operation="continuous_profile_update_extraction",
        capability="profile",
        owner_public_id=owner_public_id,
        input_summary={"course_id": course_context.get("courseId"), "answer_chars": len(answer)},
        trace_id=trace_id,
        response_validator=validator,
    )
    result = _parse_continuous_model_candidates(raw, answer)
    result["modelMeta"] = {
        "provider": "openai-compatible",
        "model": "deepseek-v4-flash",
        "thinking": "enabled",
        "reasoningEffort": "max",
        "allowFallback": False,
        "traceId": trace_id,
    }
    return result


def llm_extract_continuous_candidates(
    answer: str,
    *,
    owner_public_id: str,
    profile: DBStudentProfile | None,
    course_context: dict[str, Any],
    question: str = "",
    conversation_history: list[dict[str, Any]] | None = None,
    covered_dimensions: dict[str, int] | None = None,
) -> dict[str, Any]:
    return asyncio.run(_extract_continuous_candidates_with_model(
        answer,
        owner_public_id=owner_public_id,
        profile=profile,
        course_context=course_context,
        question=question,
        conversation_history=conversation_history,
        covered_dimensions=covered_dimensions,
    ))


def _continuous_state(session: DBOnboardingSession) -> dict[str, Any]:
    context = dict(session.course_context or {})
    state = context.get("continuousUpdate")
    return dict(state) if isinstance(state, dict) else {}


def _set_continuous_state(session: DBOnboardingSession, state: dict[str, Any]) -> None:
    context = dict(session.course_context or {})
    context["continuousUpdate"] = state
    session.course_context = context


def _continuous_course_context(
    db: Session,
    user: DBUser,
    course_id: str | None = None,
) -> dict[str, Any]:
    if not course_id:
        return _course_context(db, user, db.get(DBStudentProfile, user.username))
    course = db.get(DBCourse, course_id)
    if course is None:
        raise OnboardingError("course_not_found", "所选课程不存在或已被移除。")
    from course_catalog import course_is_selectable
    if not course_is_selectable(db, course):
        raise OnboardingError("course_unavailable", "当前课程画像上下文暂不可用。")
    if (
        course.visibility != "public"
        and course.owner_public_id != user.public_id
        and str(getattr(user, "role", "")) != "admin"
    ):
        raise OnboardingError("course_unavailable", "当前课程画像上下文暂不可用。")
    return {"courseId": course.id, "title": course.title, "source": "课程知识库"}


def _snapshot_course_id(row: DBProfileSnapshot) -> str | None:
    body = row.snapshot or {}
    return str(body.get("course_id") or (body.get("course_context") or {}).get("courseId") or "") or None


def _latest_profile_snapshot(
    db: Session,
    owner_public_id: str,
    course_id: str | None,
) -> DBProfileSnapshot | None:
    rows = db.query(DBProfileSnapshot).filter_by(owner_public_id=owner_public_id).order_by(
        DBProfileSnapshot.created_at.desc(), DBProfileSnapshot.id.desc(),
    ).all()
    if course_id:
        rows = [row for row in rows if _snapshot_course_id(row) in {None, course_id}]
    return rows[0] if rows else None


def latest_profile_snapshot_for_course(
    db: Session,
    owner_public_id: str,
    course_id: str | None = None,
) -> DBProfileSnapshot | None:
    """Return the newest canonical snapshot that is valid for the requested course."""

    return _latest_profile_snapshot(db, owner_public_id, course_id)


def profile_influence_summary(snapshot: DBProfileSnapshot | None) -> list[str]:
    """Expose a small, user-readable explanation of how the current profile is used."""

    if snapshot is None:
        return ["当前还没有可用的已确认画像快照，先按课程默认难度安排。"]
    body = snapshot.snapshot or {}
    projection = body.get("profile_projection") or {}
    messages: list[str] = []
    weak_points = list(
        body.get("weak_points")
        or body.get("weak_knowledge_point_ids")
        or projection.get("weak_points")
        or []
    )
    if weak_points:
        messages.append(f"优先安排薄弱点：{'、'.join(str(item) for item in weak_points[:3])}。")
    load = projection.get("cognitive_load")
    if isinstance(load, (int, float)) and load >= 0.66:
        messages.append("当前认知负荷偏高，内容会拆成更小步骤并减少一次性题量。")
    frustration = projection.get("frustration_index")
    if isinstance(frustration, (int, float)) and frustration >= 0.5:
        messages.append("近期挫败感偏高，先安排有明确反馈的基础练习。")
    preferences = list(projection.get("interaction_preferences") or [])
    if preferences:
        messages.append(f"讲义和练习会优先采用你的互动偏好：{'、'.join(str(item) for item in preferences[:2])}。")
    goals = list(projection.get("learning_goals") or [])
    if goals:
        messages.append(f"资源目标参考：{str(goals[0])[:80]}。")
    return messages or ["本轮按已确认画像和课程证据保持当前学习节奏。"]


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=None)


def _continuous_last_confirmed_at(
    db: Session,
    session: DBOnboardingSession,
    course_id: str | None,
) -> datetime | None:
    state = _continuous_state(session)
    last = _parse_iso_datetime(state.get("lastConfirmedAt"))
    if last is not None:
        return last
    snapshot = _latest_profile_snapshot(db, session.owner_public_id, course_id)
    if snapshot is not None and snapshot.created_at is not None:
        return snapshot.created_at
    return session.confirmed_at


def continuous_update_reminder(
    db: Session,
    user: DBUser,
    *,
    course_id: str | None = None,
) -> dict[str, Any]:
    """Compute the three-day reminder without writing on read."""

    session = get_or_create_session(db, user, feature_enabled=True)
    context = _continuous_course_context(db, user, course_id)
    state = _continuous_state(session)
    baseline = _continuous_last_confirmed_at(db, session, context.get("courseId"))
    if baseline is None:
        return {
            "schemaVersion": "profile.continuous-update-reminder.v1",
            "due": False,
            "dismissed": False,
            "courseContext": context,
            "lastConfirmedAt": None,
            "ageDays": 0,
            "message": "完成一次画像确认后，系统会在三天未更新时提醒你。",
        }
    age = max(0, (_now() - baseline).total_seconds() / 86400)
    baseline_key = baseline.isoformat()
    dismissed = state.get("reminderDismissedFor") == baseline_key
    active = bool(state.get("active"))
    due = age >= CONTINUOUS_UPDATE_REMINDER_DAYS and not dismissed and not active
    return {
        "schemaVersion": "profile.continuous-update-reminder.v1",
        "due": due,
        "dismissed": dismissed,
        "courseContext": context,
        "lastConfirmedAt": baseline_key,
        "ageDays": round(age, 2),
        "message": "已有三天没有人工更新学情画像，花一分钟补充最近的学习变化吧。",
    }


def dismiss_continuous_update_reminder(
    db: Session,
    user: DBUser,
    *,
    course_id: str | None = None,
) -> dict[str, Any]:
    """Dismiss only the reminder for the current confirmation baseline."""

    session = get_or_create_session(db, user, feature_enabled=True)
    context = _continuous_course_context(db, user, course_id)
    baseline = _continuous_last_confirmed_at(db, session, context.get("courseId"))
    state = _continuous_state(session)
    if baseline is not None:
        state["reminderDismissedFor"] = baseline.isoformat()
        _set_continuous_state(session, state)
        db.commit()
    return continuous_update_reminder(db, user, course_id=course_id)


def _continuous_turn_payload(turn: DBOnboardingTurn) -> dict[str, Any]:
    extracted = turn.extracted_candidates or {}
    return {
        "turnId": turn.turn_id,
        "questionDimension": turn.question_dimension,
        "userAnswer": turn.user_answer,
        "extractedCandidates": extracted,
        "confirmedFields": turn.confirmed_fields or {},
        "status": turn.status,
        "error": turn.error or "",
        "question": extracted.get("question") or "",
        "assistantReply": extracted.get("assistantReply") or "",
        "followUpQuestion": extracted.get("followUpQuestion") or "",
        "signalHighlights": list(extracted.get("signalHighlights") or []),
        "createdAt": turn.created_at.isoformat() if turn.created_at else None,
        "confirmedAt": turn.confirmed_at.isoformat() if turn.confirmed_at else None,
    }


def continuous_update_session_payload(
    db: Session,
    session: DBOnboardingSession,
    *,
    feature_enabled: bool = True,
) -> dict[str, Any]:
    state = _continuous_state(session)
    course_context = {
        "courseId": state.get("courseId") or (session.course_context or {}).get("courseId"),
        "title": state.get("courseTitle") or (session.course_context or {}).get("title"),
        "source": (session.course_context or {}).get("source") or "课程知识库",
    }
    turns = db.query(DBOnboardingTurn).filter_by(
        session_id=session.id,
        question_dimension="continuous",
    ).order_by(DBOnboardingTurn.created_at.asc(), DBOnboardingTurn.id.asc()).all()
    snapshot = _latest_profile_snapshot(db, session.owner_public_id, course_context.get("courseId"))
    profile = db.get(DBStudentProfile, session.student_id)
    dimensions = dict((snapshot.snapshot if snapshot else {}).get("dimension_states") or {})
    if not dimensions and profile:
        dimensions = dict(profile.dimension_states or {})
    next_question = _continuous_next_question_from_turns(turns)
    explored = _continuous_coverage(turns)
    explored_count = sum(1 for value in explored.values() if value)
    return {
        "schemaVersion": "profile.continuous-update.v1",
        "featureEnabled": feature_enabled,
        "sessionId": session.id,
        "status": "in_progress" if state.get("active") else "confirmed",
        "active": bool(state.get("active")),
        "question": next_question,
        "assistantOpening": "我们不做表格问答。你可以从最近一次真正动手学习的经历说起，我会顺着你的话，一点点把接下来的安排聊清楚。",
        "suggestedPrompts": _continuous_suggested_prompts(turns),
        "conversationProgress": {
            "rounds": len(turns),
            "exploredCount": explored_count,
            "totalAngles": len(CONTINUOUS_DIMENSIONS),
            "message": f"已经聊到 {len(turns)} 段，继续说下去会让安排更贴合你。" if turns else "先从一段最近的学习经历开始就好。",
        },
        "turns": [_continuous_turn_payload(turn) for turn in turns],
        "courseContext": course_context,
        "dimensions": [
            {
                "key": key,
                "label": CONTINUOUS_DIMENSION_LABELS[key],
                **dict(dimensions.get(key) or {}),
            }
            for key in CONTINUOUS_DIMENSIONS
        ],
        "weakPoints": list((snapshot.snapshot if snapshot else {}).get("weak_points") or (profile.weak_points if profile else []) or []),
        "profileSnapshotId": snapshot.id if snapshot else None,
        "profileVersion": snapshot.profile_version if snapshot else None,
        "lastConfirmedAt": state.get("lastConfirmedAt"),
        "lastError": session.last_error or "",
    }


def start_continuous_update(
    db: Session,
    user: DBUser,
    *,
    course_id: str | None = None,
    feature_enabled: bool = True,
) -> dict[str, Any]:
    session = get_or_create_session(db, user, feature_enabled=feature_enabled)
    context = _continuous_course_context(db, user, course_id)
    state = _continuous_state(session)
    if state.get("active") and state.get("courseId") not in {None, context.get("courseId")}:
        raise OnboardingError("update_in_progress_course", "请先完成当前课程的画像更新，再切换课程。")
    state.update({
        "active": True,
        "courseId": context.get("courseId"),
        "courseTitle": context.get("title"),
        "startedAt": state.get("startedAt") or _now().isoformat(),
        "lastError": "",
    })
    # Keep the selected course in the session projection even when the user
    # has no membership row.  This is read-only context; it never creates or
    # changes a course membership.
    session.course_context = {
        **dict(session.course_context or {}),
        "courseId": context.get("courseId"),
        "title": context.get("title"),
        "source": context.get("source") or "课程知识库",
    }
    _set_continuous_state(session, state)
    session.current_dimension = "continuous"
    session.missing_fields = []
    session.status = "in_progress"
    session.last_error = ""
    session.version += 1
    db.commit()
    return continuous_update_session_payload(db, session, feature_enabled=feature_enabled)


def record_continuous_turn(
    db: Session,
    user: DBUser,
    *,
    turn_id: str,
    user_answer: str,
    course_id: str | None = None,
    feature_enabled: bool = True,
    extractor: Callable[[str, DBStudentProfile | None, dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    session = get_or_create_session(db, user, feature_enabled=feature_enabled)
    state = _continuous_state(session)
    if not state.get("active"):
        start_continuous_update(db, user, course_id=course_id, feature_enabled=feature_enabled)
        session = db.query(DBOnboardingSession).filter_by(owner_public_id=user.public_id).one()
        state = _continuous_state(session)
    elif course_id and state.get("courseId") not in {None, course_id}:
        raise OnboardingError("update_in_progress_course", "请先完成当前课程的画像更新，再切换课程。")
    context = _continuous_course_context(db, user, course_id or state.get("courseId"))
    prior_turns = db.query(DBOnboardingTurn).filter_by(
        session_id=session.id,
        question_dimension="continuous",
    ).order_by(DBOnboardingTurn.created_at.asc(), DBOnboardingTurn.id.asc()).all()
    asked_question = _continuous_next_question_from_turns(prior_turns)
    existing = db.query(DBOnboardingTurn).filter_by(session_id=session.id, turn_id=turn_id).first()
    if existing:
        return continuous_update_session_payload(db, session, feature_enabled=feature_enabled)
    answer = user_answer.strip()
    if not answer:
        raise OnboardingError("empty_answer", "请先说说最近的学习情况。")
    turn = DBOnboardingTurn(
        session_id=session.id,
        turn_id=turn_id,
        question_dimension="continuous",
        user_answer=answer,
        status="saved",
    )
    db.add(turn)
    db.commit()  # 原话先落库，模型失败也必须可以人工复核。
    db.refresh(turn)
    profile = db.get(DBStudentProfile, session.student_id)
    try:
        if extractor is None:
            extractor = lambda text, current, course: llm_extract_continuous_candidates(
                text,
                owner_public_id=user.public_id,
                profile=current,
                course_context=course,
                question=asked_question,
                conversation_history=[
                    {
                        "question": (item.extracted_candidates or {}).get("question") or "",
                        "answer": item.user_answer,
                        "reply": (item.extracted_candidates or {}).get("assistantReply") or "",
                    }
                    for item in prior_turns[-6:]
                ],
                covered_dimensions=_continuous_coverage(prior_turns),
            )
        candidates = extractor(answer, profile, context)
        candidates = dict(candidates or {})
        candidates.setdefault("question", asked_question)
        candidates["assistantReply"] = _learner_safe_text(candidates.get("assistantReply")) or _friendly_continuous_reply(
            answer,
            candidates.get("understanding") or candidates.get("summary") or "",
        )
        candidates.setdefault("signalHighlights", [])
        turn.extracted_candidates = candidates
        future_turns = prior_turns + [turn]
        candidates["followUpQuestion"] = _learner_safe_text(candidates.get("followUpQuestion")) or _continuous_next_question_from_turns(future_turns)
        turn.status = "awaiting_confirmation"
        turn.error = ""
        session.last_error = ""
    except Exception as exc:
        # Offline/demo runs still exercise the real turn, confirmation and
        # snapshot protocol. They use a small local mirror of the learner's
        # own words only when the configured external model is unavailable;
        # production model failures remain explicit and recoverable.
        try:
            from config import CONFIG
            if CONFIG.demo_mode:
                candidates = _demo_continuous_candidates(answer, asked_question, len(prior_turns))
                turn.extracted_candidates = candidates
                turn.status = "awaiting_confirmation"
                turn.error = ""
                session.last_error = ""
            else:
                raise RuntimeError("demo fallback disabled")
        except Exception:
            turn.extracted_candidates = {
                "mode": "continuous_profile_update",
                "summary": "模型暂时没有完成整理。",
                "understanding": "",
                "fields": [],
                "dimensions": [],
                "weakPointAttribution": [],
                "uncertainties": ["可以换一种说法再聊一次。"],
                "source": "manual_review_after_model_failure",
                "originalAnswer": answer,
                "question": asked_question,
            }
            turn.status = "extraction_failed"
            turn.error = "刚才那句话没有整理完整，你的原话已保留，可以换一种说法再试。"
            session.last_error = str(exc)
    db.commit()
    return continuous_update_session_payload(db, session, feature_enabled=feature_enabled)


def _normalize_continuous_fields(fields: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, raw in (fields or {}).items():
        if key not in CONTINUOUS_ALLOWED_FIELDS:
            continue
        if isinstance(raw, list):
            value: Any = [str(item).strip() for item in raw if str(item).strip()]
        elif key == "misconception_patterns" and isinstance(raw, dict):
            value = _normalize_misconception_patterns(raw)
        elif key in {"focus_level", "cognitive_load", "frustration_index"}:
            try:
                value = max(0.0, min(1.0, float(raw)))
            except (TypeError, ValueError):
                continue
        else:
            value = str(raw or "").strip()
        if value not in ("", [], {}):
            normalized[key] = value
    return normalized


def _normalize_continuous_dimensions(dimensions: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in dimensions or []:
        item = _continuous_dimension(raw)
        if item:
            normalized.append(item)
    return normalized


def _normalize_continuous_attributions(attributions: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in attributions or []:
        item = _continuous_attribution(raw)
        if item:
            normalized.append(item)
    return normalized


def _profile_update_projection(profile: DBStudentProfile) -> dict[str, Any]:
    return {
        "major": profile.major or "",
        "target_course": profile.target_course or "",
        "knowledge_base": profile.knowledge_base or "",
        "cognitive_style": profile.cognitive_style or "",
        "motivation_type": profile.motivation_type or "",
        "focus_level": profile.focus_level,
        "cognitive_load": profile.cognitive_load,
        "frustration_index": profile.frustration_index,
        "learning_goals": list(profile.learning_goals or []),
        "weak_points": list(profile.weak_points or []),
        "interaction_preferences": list(profile.interaction_preferences or []),
        "misconception_patterns": dict(profile.misconception_patterns or {}),
        "dimension_states": dict(profile.dimension_states or {}),
        "learning_state_causes": dict(profile.learning_state_causes or {}),
        "concept_mastery": dict(profile.concept_mastery or {}),
        "knowledge_traces": dict(profile.knowledge_traces or {}),
        "bkt_states": dict(profile.bkt_states or {}),
        "history_logs": profile.history_logs or "",
        "mental_state_history": list(profile.mental_state_history or []),
    }


def _apply_continuous_projection(
    profile: DBStudentProfile,
    *,
    fields: dict[str, Any],
    dimensions: list[dict[str, Any]],
    attributions: list[dict[str, Any]],
    answer: str,
    turn_id: str,
    course_context: dict[str, Any],
) -> list[dict[str, Any]]:
    field_attrs = {
        "major": "major",
        "target_course": "target_course",
        "knowledge_base": "knowledge_base",
        "cognitive_style": "cognitive_style",
        "motivation_type": "motivation_type",
        "focus_level": "focus_level",
        "cognitive_load": "cognitive_load",
        "frustration_index": "frustration_index",
        "learning_goals": "learning_goals",
        "weak_points": "weak_points",
        "interaction_preferences": "interaction_preferences",
        "misconception_patterns": "misconception_patterns",
    }
    for key, value in fields.items():
        attr = field_attrs.get(key)
        if not attr:
            continue
        if key == "weak_points":
            prior = [str(item) for item in (getattr(profile, attr, None) or [])]
            value = list(dict.fromkeys(prior + list(value if isinstance(value, list) else [value])))[:20]
        elif key == "misconception_patterns":
            prior = dict(getattr(profile, attr, None) or {})
            prior.update(value if isinstance(value, dict) else {})
            value = prior
        setattr(profile, attr, value)
    states = dict(profile.dimension_states or {})
    evidence_records: list[dict[str, Any]] = []
    for item in dimensions:
        key = item["key"]
        prior = dict(states.get(key) or {})
        evidence = str(item["evidence"])
        state = {
            **prior,
            "key": key,
            "label": item.get("label") or CONTINUOUS_DIMENSION_LABELS[key],
            "status": item.get("status") or item.get("value") or prior.get("status") or "待确认",
            "summary": item.get("value") or prior.get("summary") or "",
            "confidence": item.get("confidence", prior.get("confidence", 0.0)),
            "evidence_count": int(prior.get("evidence_count") or 0) + 1,
            "evidence_fragments": list(dict.fromkeys(list(prior.get("evidence_fragments") or []) + [evidence]))[-5:],
            "last_updated": _now().isoformat(),
            "source_course_id": course_context.get("courseId"),
            "source_turn_id": turn_id,
        }
        if item.get("score") is not None:
            state["score"] = item["score"]
        states[key] = state
        evidence_records.append({
            "dimension": key,
            "text": evidence,
            "confidence": item["confidence"],
        })
    profile.dimension_states = states
    for item in attributions:
        weak_point = item["weakPoint"]
        profile.weak_points = list(dict.fromkeys(list(profile.weak_points or []) + [weak_point]))[:20]
        evidence_records.append({
            "weakPoint": weak_point,
            "reason": item["reason"],
            "text": item["evidence"],
            "confidence": item["confidence"],
        })
    for key, value in fields.items():
        evidence_records.append({
            "field": key,
            "text": answer,
            "value": value,
            "confidence": 1.0,
        })
    legacy_evidence = list(profile.profile_evidence or [])
    for record in evidence_records:
        legacy_evidence.append({
            "source": "student_message",
            "source_object_id": turn_id,
            "features": ["continuous_profile_update", record.get("dimension") or record.get("field") or record.get("weakPoint") or "profile"],
            "weight": float(record.get("confidence") or 0.0),
            "confidence": float(record.get("confidence") or 0.0),
            "text": str(record.get("text") or record.get("reason") or answer)[:2048],
            "timestamp": _now().isoformat(),
            "course_id": course_context.get("courseId"),
            "version": "continuous.v1",
            "trace_id": turn_id,
        })
    profile.profile_evidence = legacy_evidence
    profile.narrative_report = ""
    return evidence_records


def _create_continuous_snapshot(
    db: Session,
    user: DBUser,
    profile: DBStudentProfile,
    *,
    course_context: dict[str, Any],
    turn_id: str,
    evidence_records: list[dict[str, Any]],
) -> DBProfileSnapshot:
    previous = _latest_profile_snapshot(db, user.public_id, course_context.get("courseId"))
    numbers = []
    for row in db.query(DBProfileSnapshot).filter_by(owner_public_id=user.public_id).all():
        match = re.search(r"profile\.continuous\.v(\d+)$", row.profile_version or "")
        if match:
            numbers.append(int(match.group(1)))
    version = f"profile.continuous.v{(max(numbers) if numbers else 0) + 1}"
    data = {
        "kind": "continuous_profile_update",
        "owner_public_id": user.public_id,
        "legacy_student_id": user.username,
        "course_id": course_context.get("courseId"),
        "course_context": course_context,
        "source_turn_id": turn_id,
        "previous_snapshot_id": previous.id if previous else None,
        "profile_projection": _profile_update_projection(profile),
        "dimension_states": dict(profile.dimension_states or {}),
        "weak_points": list(profile.weak_points or []),
        "weak_knowledge_point_ids": list(profile.weak_points or []),
        "profile_version": None,
        "weak_point_attribution": [item for item in evidence_records if item.get("weakPoint")],
        "evidence": evidence_records,
        "updated_at": _now().isoformat(),
    }
    row = DBProfileSnapshot(
        id=f"ps-profile-update-{uuid.uuid4().hex[:24]}",
        owner_public_id=user.public_id,
        legacy_student_id=user.username,
        profile_version=version,
        snapshot=data,
        content_hash=_canonical_hash(data),
        trace_id=turn_id,
    )
    data["profile_version"] = version
    row.snapshot = data
    row.content_hash = _canonical_hash(data)
    db.add(row)
    db.flush()
    return row


def confirm_continuous_turn(
    db: Session,
    user: DBUser,
    *,
    turn_id: str,
    fields: dict[str, Any] | None = None,
    dimensions: list[dict[str, Any]] | None = None,
    attributions: list[dict[str, Any]] | None = None,
    continue_conversation: bool = False,
    feature_enabled: bool = True,
) -> dict[str, Any]:
    session = db.query(DBOnboardingSession).filter_by(owner_public_id=user.public_id).first()
    if session is None:
        raise OnboardingError("update_session_not_found", "还没有开始画像更新会话。")
    turn = db.query(DBOnboardingTurn).filter_by(session_id=session.id, turn_id=turn_id).first()
    if turn is None or turn.question_dimension != "continuous":
        raise OnboardingError("turn_not_found", "没有找到这轮画像更新。")
    candidate = turn.extracted_candidates or {}
    normalized_fields = _normalize_continuous_fields(fields or {})
    normalized_dimensions = _normalize_continuous_dimensions(dimensions or [])
    normalized_attributions = _normalize_continuous_attributions(attributions or [])
    if not normalized_fields and not normalized_dimensions and not normalized_attributions and not continue_conversation:
        raise OnboardingError("empty_confirmation", "请至少确认一项画像变化、十维状态或薄弱点归因。")
    if turn.status == "confirmed" and (turn.confirmed_fields or {}) == {
        "fields": normalized_fields,
        "dimensions": normalized_dimensions,
        "weakPointAttribution": normalized_attributions,
    }:
        return continuous_update_session_payload(db, session, feature_enabled=feature_enabled)
    state = _continuous_state(session)
    course_context = _continuous_course_context(db, user, state.get("courseId"))
    profile = db.get(DBStudentProfile, session.student_id)
    if profile is None:
        profile = DBStudentProfile(student_id=session.student_id)
        db.add(profile)
        db.flush()
    turn.confirmed_fields = {
        "fields": normalized_fields,
        "dimensions": normalized_dimensions,
        "weakPointAttribution": normalized_attributions,
    }
    turn.status = "projecting"
    turn.error = ""
    db.commit()
    try:
        if not normalized_fields and not normalized_dimensions and not normalized_attributions:
            # A learner may simply say “继续聊聊” when a round contained no
            # stable profile signal. Keep the conversation alive without
            # creating a meaningless snapshot.
            turn.status = "confirmed"
            turn.confirmed_at = _now()
            turn.error = ""
            state.update({"active": True, "lastError": ""})
            _set_continuous_state(session, state)
            session.status = "in_progress"
            session.last_error = ""
            session.version += 1
            db.commit()
            return continuous_update_session_payload(db, session, feature_enabled=feature_enabled)
        evidence_records = _apply_continuous_projection(
            profile,
            fields=normalized_fields,
            dimensions=normalized_dimensions,
            attributions=normalized_attributions,
            answer=turn.user_answer,
            turn_id=turn.turn_id,
            course_context=course_context,
        )
        profile.last_updated = _now()
        snapshot = _create_continuous_snapshot(
            db,
            user,
            profile,
            course_context=course_context,
            turn_id=turn.turn_id,
            evidence_records=evidence_records,
        )
        turn.status = "confirmed"
        turn.confirmed_at = _now()
        turn.error = ""
        state.update({
            "active": bool(continue_conversation),
            "lastConfirmedAt": _now().isoformat(),
            "lastSnapshotId": snapshot.id,
            "lastProfileVersion": snapshot.profile_version,
        })
        _set_continuous_state(session, state)
        session.status = "in_progress" if continue_conversation else "confirmed"
        session.last_error = ""
        session.version += 1
        db.commit()
    except Exception as exc:
        db.rollback()
        turn = db.query(DBOnboardingTurn).filter_by(session_id=session.id, turn_id=turn_id).one()
        session = db.get(DBOnboardingSession, session.id)
        turn.status = "projection_failed"
        turn.error = "画像保存暂时失败，你的原话和候选已经保留，可以再次确认。"
        session.last_error = str(exc)
        db.commit()
    return continuous_update_session_payload(db, session, feature_enabled=feature_enabled)


def complete_continuous_update(
    db: Session,
    user: DBUser,
    *,
    feature_enabled: bool = True,
) -> dict[str, Any]:
    """Close an open conversation after the learner has saved the rounds they want."""
    session = db.query(DBOnboardingSession).filter_by(owner_public_id=user.public_id).first()
    if session is None:
        raise OnboardingError("update_session_not_found", "还没有开始画像更新会话。")
    pending = db.query(DBOnboardingTurn).filter_by(
        session_id=session.id,
        question_dimension="continuous",
    ).filter(DBOnboardingTurn.status.in_(["awaiting_confirmation", "projecting", "projection_failed", "extraction_failed"])).first()
    if pending is not None:
        raise OnboardingError("pending_confirmation", "请先处理刚才那一轮，再结束这次聊天。")
    state = _continuous_state(session)
    state["active"] = False
    state["lastError"] = ""
    _set_continuous_state(session, state)
    session.status = "confirmed"
    session.last_error = ""
    session.version += 1
    db.commit()
    return continuous_update_session_payload(db, session, feature_enabled=feature_enabled)


def _course_context(db: Session, user: DBUser, profile: DBStudentProfile | None) -> dict[str, str]:
    # The profile flow must not use course membership as its course-context
    # source.  Resolve a previously saved course label directly to a published
    # course the account may read; explicit course_id requests use the stricter
    # checks in _continuous_course_context().
    saved_title = str(profile.target_course or "").strip() if profile else ""
    if saved_title:
        candidates = (
            db.query(DBCourse)
            .filter(DBCourse.title == saved_title, DBCourse.status == "published")
            .order_by(DBCourse.title.asc(), DBCourse.id.asc())
            .all()
        )
        is_admin = str(getattr(user, "role", "")) == "admin"
        from course_catalog import course_is_selectable
        for course in candidates:
            if course_is_selectable(db, course) and (
                course.visibility == "public"
                or course.owner_public_id == user.public_id
                or is_admin
            ):
                return {"courseId": course.id, "title": course.title, "source": "课程知识库"}
        return {"courseId": "", "title": saved_title, "source": "已保存的课程信息，等待课程确认"}
    return {"courseId": "", "title": "", "source": "尚未选择课程"}


def legacy_profile_complete(profile: DBStudentProfile | None) -> bool:
    if not profile:
        return False
    customized = set(profile.customized_fields or [])
    explicitly_initialized = {
        "major", "target_course", "learning_goals", "interaction_preferences",
    }.issubset(customized)
    evidence_initialized = bool(profile.target_course and profile.profile_evidence)
    return explicitly_initialized or evidence_initialized


def onboarding_status(db: Session, user: DBUser, *, feature_enabled: bool) -> dict[str, Any]:
    session = db.query(DBOnboardingSession).filter_by(owner_public_id=user.public_id).first()
    profile = db.get(DBStudentProfile, user.username)
    snapshot = db.get(DBProfileSnapshot, _initial_snapshot_id(user.public_id))
    # The three profile_demo_* accounts are seeded with a complete, immutable
    # profile-demo snapshot rather than the conversational onboarding snapshot.
    # Treat that explicit demo artifact as finalized so login does not restart
    # the initial profile conversation for the seeded learning personas.
    demo_snapshot = _profile_demo_snapshot(db, user.public_id, user.username)
    effective_snapshot = snapshot or demo_snapshot
    return {
        "featureEnabled": feature_enabled,
        "exists": session is not None,
        "status": session.status if session else None,
        "finalized": effective_snapshot is not None,
        "profileSnapshotId": effective_snapshot.id if effective_snapshot else None,
        "legacyComplete": legacy_profile_complete(profile),
    }


def _profile_demo_snapshot(db: Session, owner_public_id: str, username: str) -> DBProfileSnapshot | None:
    if not username.startswith("profile_demo_"):
        return None
    return db.query(DBProfileSnapshot).filter_by(
        owner_public_id=owner_public_id,
        profile_version="profile-demo.v1",
    ).order_by(DBProfileSnapshot.created_at.desc(), DBProfileSnapshot.id.desc()).first()


def get_or_create_session(db: Session, user: DBUser, *, feature_enabled: bool = True) -> DBOnboardingSession:
    session = db.query(DBOnboardingSession).filter_by(owner_public_id=user.public_id).first()
    if session:
        return session
    profile = db.get(DBStudentProfile, user.username)
    if profile is None:
        profile = DBStudentProfile(student_id=user.username)
        db.add(profile)
        db.flush()
    session = DBOnboardingSession(
        owner_public_id=user.public_id,
        student_id=user.username,
        current_dimension=DIMENSIONS[0],
        missing_fields=list(DIMENSIONS),
        course_context=_course_context(db, user, profile),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _turn_payload(turn: DBOnboardingTurn) -> dict[str, Any]:
    extracted = turn.extracted_candidates or {}
    return {
        "turnId": turn.turn_id,
        "questionDimension": turn.question_dimension,
        "userAnswer": turn.user_answer,
        "extractedCandidates": extracted,
        "confirmedFields": turn.confirmed_fields or {},
        "status": turn.status,
        "error": turn.error or "",
        "question": extracted.get("question") or QUESTIONS.get(turn.question_dimension, ""),
        "assistantReply": extracted.get("assistantReply") or "",
        "followUpQuestion": extracted.get("followUpQuestion") or "",
        "signalHighlights": list(extracted.get("signalHighlights") or []),
        "createdAt": turn.created_at.isoformat() if turn.created_at else None,
    }


def _evidence_payload(row: DBOnboardingPersonalEvidence) -> dict[str, Any]:
    return {
        "evidenceId": row.id,
        "evidenceType": row.evidence_type,
        "evidenceLabel": PERSONAL_EVIDENCE_TYPES[row.evidence_type],
        "filename": row.filename,
        "fileFormat": row.file_format,
        "fileSize": row.file_size,
        "sourceSha256": row.source_sha256,
        "parserVersion": row.parser_version,
        "candidates": row.extracted_candidates or [],
        "confirmedFields": row.confirmed_fields or [],
        "status": row.status,
        "error": row.error or "",
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "confirmedAt": row.confirmed_at.isoformat() if row.confirmed_at else None,
    }


def _onboarding_profile_signals(profile: DBStudentProfile | None) -> list[dict[str, str]]:
    """Project a compact, learner-facing view of the confirmed profile.

    Keep engineering metadata, source references and confidence scores out of
    this projection; those remain available to the audit trail and reviewer UI.
    """
    if profile is None:
        return []
    signals: list[dict[str, str]] = []
    if profile.motivation_type and profile.motivation_type != "未诊断":
        signals.append({"key": "motivation", "label": "学习动力", "value": str(profile.motivation_type)})
    goals = list(profile.learning_goals or [])
    if goals:
        signals.append({"key": "goal", "label": "想达成的事", "value": str(goals[0])[:100]})
    preferences = list(profile.interaction_preferences or [])
    if preferences:
        signals.append({"key": "preference", "label": "更顺手的学习方式", "value": "、".join(str(item) for item in preferences[:3])[:100]})
    style = str(profile.cognitive_style or "").strip()
    if style:
        signals.append({"key": "style", "label": "讲解节奏", "value": style[:100]})
    dimensions = dict(profile.dimension_states or {})
    context = dimensions.get("learning_context") or {}
    context_value = context.get("summary") or context.get("value") if isinstance(context, dict) else context
    if context_value:
        signals.append({"key": "context", "label": "学习情境", "value": str(context_value)[:100]})
    if profile.cognitive_load is not None and float(profile.cognitive_load) >= 0.5:
        signals.append({"key": "load", "label": "学习节奏", "value": "拆成更短的小段，减少一次性负荷"})
    elif profile.focus_level is not None and float(profile.focus_level) >= 0.8:
        signals.append({"key": "focus", "label": "学习节奏", "value": "可以安排更连续的深度练习"})
    if profile.frustration_index is not None and float(profile.frustration_index) >= 0.5:
        signals.append({"key": "support", "label": "陪学方式", "value": "先给明确反馈，再逐步增加挑战"})
    return signals[:8]


def session_payload(db: Session, session: DBOnboardingSession, *, feature_enabled: bool = True) -> dict[str, Any]:
    turns = (
        db.query(DBOnboardingTurn)
        .filter_by(session_id=session.id)
        .order_by(DBOnboardingTurn.created_at.asc(), DBOnboardingTurn.id.asc())
        .all()
    )
    evidence = (
        db.query(DBOnboardingPersonalEvidence)
        .filter_by(session_id=session.id, owner_public_id=session.owner_public_id)
        .order_by(DBOnboardingPersonalEvidence.created_at.asc(), DBOnboardingPersonalEvidence.id.asc())
        .all()
    )
    snapshot = db.get(DBProfileSnapshot, _initial_snapshot_id(session.owner_public_id))
    snapshot = snapshot or _profile_demo_snapshot(db, session.owner_public_id, session.student_id)
    profile = db.get(DBStudentProfile, session.student_id)
    current = session.current_dimension if session.status != "confirmed" else None
    question = conversational_question(session) if current else "画像已确认，可以继续入学诊断。"
    return {
        "schemaVersion": "onboarding.session.v3",
        "featureEnabled": feature_enabled,
        "sessionId": session.id,
        "status": session.status,
        "questionDimension": current,
        "question": question,
        "conversationMode": "adaptive",
        "assistantOpening": "我不会让你按表格填资料。你可以从最近在学什么、为什么想学、遇到什么卡点开始说，我会顺着你的话继续了解你。",
        "suggestedPrompts": ["我最近在做的事", "我最想解决的问题", "我比较有把握的基础", "我希望怎么学"],
        "profileSignals": _onboarding_profile_signals(profile),
        "turns": [_turn_payload(turn) for turn in turns],
        "confirmedFields": session.confirmed_fields or {},
        "missingFields": session.missing_fields or [],
        "checkpoint": session.checkpoint,
        "version": session.version,
        "progress": {"completed": len(session.confirmed_fields or {}), "total": len(DIMENSIONS)},
        "dimensions": [
            {"key": key, "label": DIMENSION_LABELS[key], "status": "confirmed" if key in (session.confirmed_fields or {}) else ("current" if key == current else "pending")}
            for key in DIMENSIONS
        ],
        "courseContext": session.course_context or {},
        "personalEvidence": [_evidence_payload(row) for row in evidence],
        "finalized": snapshot is not None,
        "profileSnapshotId": snapshot.id if snapshot else None,
        "lastError": session.last_error or "",
    }


def record_turn(
    db: Session,
    user: DBUser,
    *,
    turn_id: str,
    question_dimension: str,
    user_answer: str,
    feature_enabled: bool = True,
    extractor: Callable[[str, str], dict[str, Any]] = extract_candidates,
) -> dict[str, Any]:
    session = get_or_create_session(db, user, feature_enabled=feature_enabled)
    existing = db.query(DBOnboardingTurn).filter_by(session_id=session.id, turn_id=turn_id).first()
    if existing:
        return session_payload(db, session, feature_enabled=feature_enabled)
    if question_dimension not in DIMENSIONS:
        raise OnboardingError("invalid_dimension", "画像维度无效。")
    if question_dimension != session.current_dimension and question_dimension not in (session.confirmed_fields or {}):
        raise OnboardingError("unexpected_dimension", "请先完成当前问题。")
    answer = user_answer.strip()
    if not answer:
        raise OnboardingError("empty_answer", "请先说说你的情况。")

    asked_question = conversational_question(session)
    turn = DBOnboardingTurn(
        session_id=session.id,
        turn_id=turn_id,
        question_dimension=question_dimension,
        user_answer=answer,
        status="saved",
    )
    db.add(turn)
    try:
        db.commit()  # The learner answer is durable before extraction or profile projection.
    except IntegrityError:
        db.rollback()
        existing = db.query(DBOnboardingTurn).filter_by(session_id=session.id, turn_id=turn_id).one()
        return session_payload(db, session, feature_enabled=feature_enabled)
    db.refresh(turn)

    try:
        candidates = extractor(question_dimension, answer)
        turn.extracted_candidates = _decorate_turn_candidates(
            session, question_dimension, answer, candidates, asked_question,
        )
        prior = (session.confirmed_fields or {}).get(question_dimension)
        turn.status = "conflict" if prior and prior.get("summary") != turn.extracted_candidates.get("summary") else "awaiting_confirmation"
        turn.error = ""
    except Exception as exc:
        key, label, kind = FALLBACK_FIELDS[question_dimension]
        try:
            fallback = extract_candidates(question_dimension, answer)
        except Exception:
            fallback = {
                "dimension": question_dimension,
                "summary": answer,
                "understanding": "",
                "fields": [_field(key, label, answer, kind)],
                "uncertainties": [],
            }
        fallback.update({
            "source": "manual_review_after_model_failure",
            "uncertainties": list(fallback.get("uncertainties") or []) + ["模型未能完成整理，请根据原话检查并确认字段。"],
            "originalAnswer": answer,
        })
        turn.extracted_candidates = _decorate_turn_candidates(
            session, question_dimension, answer, fallback, asked_question,
        )
        turn.status = "extraction_failed"
        turn.error = "自动整理暂不可用，请直接检查并编辑候选字段。"
        session.last_error = str(exc)
    db.commit()
    return session_payload(db, session, feature_enabled=feature_enabled)


def _normalize_fields(fields: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, raw in fields.items():
        if isinstance(raw, list):
            value = [str(item).strip() for item in raw if str(item).strip()]
        elif key == "misconception_patterns":
            value = _normalize_misconception_patterns(raw)
        else:
            value = str(raw or "").strip()
        if value:
            normalized[key] = value
    if not normalized:
        raise OnboardingError("empty_confirmation", "至少确认一个画像字段。")
    return normalized


def project_confirmed_fields(db: Session, student_id: str, dimension: str, fields: dict[str, Any]) -> None:
    profile = db.get(DBStudentProfile, student_id)
    if profile is None:
        profile = DBStudentProfile(student_id=student_id)
        db.add(profile)

    def items(key: str) -> list[str]:
        value = fields.get(key, [])
        if isinstance(value, list):
            return value
        return _split_items(str(value)) if value else []

    if dimension == "background":
        if fields.get("major"):
            profile.major = str(fields["major"])
        if fields.get("target_course"):
            profile.target_course = str(fields["target_course"])
        if fields.get("motivation_type"):
            profile.motivation_type = str(fields["motivation_type"]).strip()
    elif dimension == "goal":
        profile.learning_goals = items("learning_goals")
        if fields.get("motivation_type"):
            profile.motivation_type = str(fields["motivation_type"]).strip()
        if fields.get("target_course"):
            profile.target_course = str(fields["target_course"]).strip()
    elif dimension == "foundation" and fields.get("knowledge_base"):
        profile.knowledge_base = str(fields["knowledge_base"])
    elif dimension == "difficulty":
        profile.weak_points = items("weak_points")
    elif dimension == "preference":
        profile.interaction_preferences = items("interaction_preferences")
        if fields.get("cognitive_style"):
            profile.cognitive_style = str(fields["cognitive_style"])

    # Natural-language registration can also provide explicit learning-state
    # signals.  They are still candidate fields requiring confirmation, and
    # they reuse the existing profile columns consumed by adaptation.
    for key in ("focus_level", "cognitive_load", "frustration_index"):
        if key in fields:
            try:
                setattr(profile, key, max(0.0, min(1.0, float(fields[key]))))
            except (TypeError, ValueError):
                pass
    if fields.get("misconception_patterns"):
        prior = dict(profile.misconception_patterns or {})
        incoming = fields["misconception_patterns"]
        if isinstance(incoming, dict):
            prior.update(incoming)
        profile.misconception_patterns = prior

    states = dict(profile.dimension_states or {})
    state_map = {
        "background": ("learning_context", "学习情境", fields.get("learning_context") or fields.get("background_context") or fields.get("major")),
        "goal": ("motivation_and_purpose", "学习目标和动力", fields.get("motivation_type") or fields.get("learning_goals")),
        "foundation": ("knowledge_mastery", "知识基础与掌握度", fields.get("knowledge_base") or fields.get("foundation_context")),
        "difficulty": ("affect_resilience", "信心和抗挫能力", fields.get("difficulty_context") or fields.get("weak_points")),
        "preference": ("interaction_preference", "喜欢怎样互动学习", fields.get("cognitive_style") or fields.get("interaction_preferences")),
    }
    state_key, state_label, state_value = state_map.get(dimension, ("", "", ""))
    if state_key and state_value:
        if isinstance(state_value, list):
            state_value = "、".join(str(item) for item in state_value)
        states[state_key] = {
            **dict(states.get(state_key) or {}),
            "key": state_key,
            "label": state_label,
            "summary": str(state_value)[:240],
            "status": "已从注册对话确认",
            "confidence": 1.0,
            "evidence_count": int((states.get(state_key) or {}).get("evidence_count") or 0) + 1,
            "last_updated": _now().isoformat(),
            "source": "initial_onboarding",
        }
    profile.dimension_states = states

    customized = list(profile.customized_fields or [])
    for key in fields:
        if key in {"major", "target_course", "learning_goals", "motivation_type", "knowledge_base", "weak_points", "interaction_preferences", "cognitive_style", "focus_level", "cognitive_load", "frustration_index", "misconception_patterns"} and key not in customized:
            customized.append(key)
    profile.customized_fields = customized
    profile.narrative_report = ""
    db.commit()
    from swarm_factory import _swarm_cache
    for swarm in _swarm_cache.values():
        swarm.profile_store.pop(student_id, None)


def confirm_turn(
    db: Session,
    user: DBUser,
    *,
    turn_id: str,
    fields: dict[str, Any],
    resolve_conflict: bool = False,
    feature_enabled: bool = True,
    projector: Callable[[Session, str, str, dict[str, Any]], None] = project_confirmed_fields,
) -> dict[str, Any]:
    session = get_or_create_session(db, user, feature_enabled=feature_enabled)
    turn = db.query(DBOnboardingTurn).filter_by(session_id=session.id, turn_id=turn_id).first()
    if not turn:
        raise OnboardingError("turn_not_found", "没有找到这轮回答，请重新发送。")
    normalized = _normalize_fields(fields)
    if turn.status == "confirmed" and (turn.confirmed_fields or {}) == normalized:
        return session_payload(db, session, feature_enabled=feature_enabled)
    if turn.status == "conflict" and not resolve_conflict:
        raise OnboardingError("field_conflict", "本次回答与已确认画像不同，请明确选择是否更新。")

    turn.confirmed_fields = normalized
    turn.status = "projecting"
    turn.error = ""
    db.commit()
    try:
        projector(db, session.student_id, turn.question_dimension, normalized)
    except Exception:
        db.rollback()
        turn = db.query(DBOnboardingTurn).filter_by(session_id=session.id, turn_id=turn_id).one()
        session = db.get(DBOnboardingSession, session.id)
        turn.status = "projection_failed"
        turn.error = "画像保存暂时失败，你的回答已经保留，可以再次确认。"
        session.last_error = turn.error
        db.commit()
        return session_payload(db, session, feature_enabled=feature_enabled)

    session = db.get(DBOnboardingSession, session.id)
    turn = db.query(DBOnboardingTurn).filter_by(session_id=session.id, turn_id=turn_id).one()
    confirmed = dict(session.confirmed_fields or {})
    summary = str((turn.extracted_candidates or {}).get("summary") or turn.user_answer)
    confirmed[turn.question_dimension] = {
        "label": DIMENSION_LABELS[turn.question_dimension],
        "summary": summary,
        "values": normalized,
        "source": "学生自述并确认",
        "turnId": turn.turn_id,
        "confirmedAt": _now().isoformat(),
    }
    missing = [key for key in DIMENSIONS if key not in confirmed]
    session.confirmed_fields = confirmed
    session.missing_fields = missing
    session.checkpoint = len(confirmed)
    session.version += 1
    session.current_dimension = missing[0] if missing else DIMENSIONS[-1]
    session.status = "in_progress" if missing else "confirmed"
    session.confirmed_at = None if missing else _now()
    session.last_error = ""
    turn.status = "confirmed"
    turn.confirmed_at = _now()
    turn.error = ""
    db.commit()
    return session_payload(db, session, feature_enabled=feature_enabled)


def _source_reference(parsed: Any, value: str) -> str:
    position = parsed.text.find(value)
    location = next(
        (
            item for item in parsed.locations
            if position >= 0 and item.char_start <= position < item.char_end
        ),
        parsed.locations[0] if parsed.locations else None,
    )
    if location is None:
        return parsed.filename
    if location.page_number:
        return f"{parsed.filename} · 第 {location.page_number} 页"
    if location.slide_number:
        return f"{parsed.filename} · 第 {location.slide_number} 页"
    return f"{parsed.filename} · {location.label}"


def _document_candidate(
    parsed: Any,
    *,
    key: str,
    label: str,
    value: Any,
    confidence: float,
    evidence_type: str,
    kind: str = "text",
) -> dict[str, Any]:
    reference_value = value[0] if isinstance(value, list) and value else str(value)
    return {
        "key": key,
        "label": label,
        "value": value,
        "kind": kind,
        "confidence": confidence,
        "sourceType": evidence_type,
        "sourceRef": _source_reference(parsed, str(reference_value)),
        "confirmedAt": None,
    }


def extract_personal_evidence_candidates(parsed: Any, evidence_type: str) -> list[dict[str, Any]]:
    text = parsed.text.strip()
    candidates: list[dict[str, Any]] = []
    school_match = re.search(r"([^\n，。；]{2,30}(?:大学|学院|学校))", text)
    major_match = re.search(r"(?:专业(?:名称)?|主修)\s*[：:]?\s*([^\n，。；]{2,30})", text)
    if school_match:
        candidates.append(_document_candidate(
            parsed, key="school", label="学校", value=school_match.group(1).strip(),
            confidence=0.9, evidence_type=evidence_type,
        ))
    if major_match:
        candidates.append(_document_candidate(
            parsed, key="major", label="专业方向", value=major_match.group(1).strip(),
            confidence=0.88, evidence_type=evidence_type,
        ))

    if evidence_type == "transcript":
        gpa_match = re.search(r"(?:GPA|平均绩点|绩点)\s*[：:]?\s*([0-9]+(?:\.[0-9]+)?)", text, re.I)
        course_scores: list[str] = []
        for line in text.splitlines():
            clean = re.sub(r"\s+", " ", line).strip()
            match = re.search(r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9+（）()· -]{1,36})\s*[：:]?\s*([0-9]{2,3}(?:\.[0-9]+)?)\s*$", clean)
            if match and 0 <= float(match.group(2)) <= 100:
                course_scores.append(f"{match.group(1).strip()} {match.group(2)}")
        course_scores = list(dict.fromkeys(course_scores))[:12]
        if gpa_match:
            candidates.append(_document_candidate(
                parsed, key="gpa", label="平均绩点", value=gpa_match.group(1),
                confidence=0.94, evidence_type=evidence_type,
            ))
        if course_scores:
            candidates.append(_document_candidate(
                parsed, key="completed_courses", label="已修课程与成绩", value=course_scores,
                confidence=0.86, evidence_type=evidence_type, kind="list",
            ))
    else:
        courses: list[str] = []
        schedule: list[str] = []
        for line in text.splitlines():
            clean = re.sub(r"\s+", " ", line).strip()
            if not clean:
                continue
            if re.search(r"(?:周一|周二|周三|周四|周五|周六|周日|星期[一二三四五六日天])", clean):
                schedule.append(clean[:100])
                course = re.sub(r"^(?:周[一二三四五六日]|星期[一二三四五六日天])\s*", "", clean)
                course = re.split(r"\s+(?:第?\d+[节周]|\d{1,2}[:：]\d{2})", course, maxsplit=1)[0].strip()
                if len(course) >= 2:
                    courses.append(course)
        courses = list(dict.fromkeys(courses))[:12]
        schedule = list(dict.fromkeys(schedule))[:12]
        if courses:
            candidates.append(_document_candidate(
                parsed, key="current_courses", label="本学期课程", value=courses,
                confidence=0.82, evidence_type=evidence_type, kind="list",
            ))
        if schedule:
            candidates.append(_document_candidate(
                parsed, key="weekly_schedule", label="每周课程安排", value=schedule,
                confidence=0.8, evidence_type=evidence_type, kind="list",
            ))
    return candidates


def _mark_candidate_conflicts(
    session: DBOnboardingSession,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    current: dict[str, dict[str, Any]] = {}
    for dimension in (session.confirmed_fields or {}).values():
        for key, value in (dimension.get("values") or {}).items():
            current[key] = {
                "value": value,
                "source": dimension.get("source") or "已确认自述",
                "sourceRef": dimension.get("turnId") or "",
            }
    output: list[dict[str, Any]] = []
    for candidate in candidates:
        existing = current.get(candidate["key"])
        conflict = bool(existing and existing["value"] != candidate["value"])
        output.append({
            **candidate,
            "conflict": conflict,
            "currentValue": existing["value"] if conflict else None,
            "currentSource": existing["source"] if conflict else None,
            "currentSourceRef": existing["sourceRef"] if conflict else None,
        })
    return output


def upload_personal_evidence(
    db: Session,
    user: DBUser,
    *,
    evidence_type: str,
    filename: str,
    raw: bytes,
    feature_enabled: bool = True,
) -> dict[str, Any]:
    _ensure_profile_not_finalized(db, user)
    if evidence_type not in PERSONAL_EVIDENCE_TYPES:
        raise OnboardingError("invalid_evidence_type", "只支持选择成绩单或课程表。")
    clean_filename = Path(filename or "").name[:256]
    extension = Path(clean_filename).suffix.lower()
    if extension not in PERSONAL_EVIDENCE_EXTENSIONS:
        raise OnboardingError("unsupported_personal_file", "个人资料仅支持 PDF、DOCX、TXT 或 Markdown。")
    if any(marker.lower() in clean_filename.lower() for marker in COURSE_MATERIAL_MARKERS):
        raise OnboardingError("course_material_not_allowed", "这里不能上传课件、教材或课程大纲。课程库已由团队预先构建。")
    if not raw:
        raise OnboardingError("empty_personal_file", "请选择非空的个人资料文件。")

    session = get_or_create_session(db, user, feature_enabled=feature_enabled)
    source_sha256 = hashlib.sha256(raw).hexdigest()
    existing = db.query(DBOnboardingPersonalEvidence).filter_by(
        session_id=session.id,
        owner_public_id=user.public_id,
        evidence_type=evidence_type,
        source_sha256=source_sha256,
    ).first()
    if existing:
        return session_payload(db, session, feature_enabled=feature_enabled)

    row = DBOnboardingPersonalEvidence(
        session_id=session.id,
        owner_public_id=user.public_id,
        evidence_type=evidence_type,
        filename=clean_filename,
        file_format=extension.lstrip("."),
        file_size=len(raw),
        source_sha256=source_sha256,
    )
    try:
        parsed = parse_document(raw, clean_filename)
        content_head = parsed.text[:2000].lower()
        if any(marker.lower() in content_head for marker in COURSE_MATERIAL_MARKERS):
            raise OnboardingError(
                "course_material_not_allowed",
                "这里不能上传课件、教材或课程大纲。课程库已由团队预先构建。",
            )
        candidates = _mark_candidate_conflicts(
            session, extract_personal_evidence_candidates(parsed, evidence_type),
        )
        row.parser_version = parsed.parser_version
        row.extracted_candidates = candidates
        if candidates:
            row.status = "parsed"
        else:
            row.status = "parse_failed"
            row.error = "文件已读取，但没有识别出可确认的个人学习字段。你仍可继续对话。"
    except OnboardingError:
        raise
    except DocumentParseError:
        row.status = "parse_failed"
        row.error = "文件无法解析，请确认格式正确，或重新导出后再试。"
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(DBOnboardingPersonalEvidence).filter_by(
            session_id=session.id,
            owner_public_id=user.public_id,
            evidence_type=evidence_type,
            source_sha256=source_sha256,
        ).one()
        session = db.get(DBOnboardingSession, existing.session_id)
    return session_payload(db, session, feature_enabled=feature_enabled)


def _owned_evidence(db: Session, user: DBUser, evidence_id: str) -> DBOnboardingPersonalEvidence:
    row = db.get(DBOnboardingPersonalEvidence, evidence_id)
    if row is None:
        raise OnboardingError("evidence_not_found", "没有找到这份个人资料。")
    if row.owner_public_id != user.public_id:
        raise OnboardingError("evidence_forbidden", "无权访问这份个人资料。")
    return row


def confirm_personal_evidence(
    db: Session,
    user: DBUser,
    *,
    evidence_id: str,
    fields: dict[str, Any],
    feature_enabled: bool = True,
) -> dict[str, Any]:
    _ensure_profile_not_finalized(db, user)
    row = _owned_evidence(db, user, evidence_id)
    if row.status == "parse_failed":
        raise OnboardingError("evidence_not_confirmable", "这份资料没有可确认字段，可以忽略后继续。")
    candidates = {item["key"]: item for item in (row.extracted_candidates or [])}
    normalized_values: dict[str, Any] = {}
    for key, raw_value in fields.items():
        candidate = candidates.get(key)
        if candidate is None:
            raise OnboardingError("unknown_evidence_field", "资料中不存在这个候选字段。")
        if candidate.get("kind") == "list":
            value = raw_value if isinstance(raw_value, list) else _split_items(str(raw_value))
            value = [str(item).strip() for item in value if str(item).strip()]
        else:
            value = str(raw_value or "").strip()
        if value:
            normalized_values[key] = value
    if not normalized_values:
        raise OnboardingError("empty_evidence_confirmation", "至少确认一个资料字段。")
    if row.status == "confirmed":
        saved_values = {item["key"]: item.get("value") for item in (row.confirmed_fields or [])}
        if saved_values == normalized_values:
            session = db.get(DBOnboardingSession, row.session_id)
            return session_payload(db, session, feature_enabled=feature_enabled)

    confirmed: list[dict[str, Any]] = []
    confirmed_at = _now()
    for key, value in normalized_values.items():
        candidate = candidates[key]
        confirmed.append({**candidate, "value": value, "confirmedAt": confirmed_at.isoformat()})
    row.confirmed_fields = confirmed
    row.status = "confirmed"
    row.confirmed_at = confirmed_at
    row.error = ""
    profile = db.get(DBStudentProfile, user.username)
    if profile is None:
        profile = DBStudentProfile(student_id=user.username)
        db.add(profile)
    for field in confirmed:
        if field["key"] == "major" and field["value"]:
            profile.major = str(field["value"])
    db.commit()
    session = db.get(DBOnboardingSession, row.session_id)
    return session_payload(db, session, feature_enabled=feature_enabled)


def discard_personal_evidence(
    db: Session,
    user: DBUser,
    *,
    evidence_id: str,
    feature_enabled: bool = True,
) -> dict[str, Any]:
    _ensure_profile_not_finalized(db, user)
    row = _owned_evidence(db, user, evidence_id)
    row.status = "discarded"
    row.confirmed_fields = []
    row.confirmed_at = None
    db.commit()
    session = db.get(DBOnboardingSession, row.session_id)
    return session_payload(db, session, feature_enabled=feature_enabled)


def finalize_initial_profile(
    db: Session,
    user: DBUser,
    *,
    feature_enabled: bool = True,
) -> dict[str, Any]:
    session = get_or_create_session(db, user, feature_enabled=feature_enabled)
    if session.status != "confirmed":
        raise OnboardingError("conversation_incomplete", "请先完成五轮画像对话。")
    unresolved = db.query(DBOnboardingPersonalEvidence).filter_by(
        session_id=session.id, owner_public_id=user.public_id, status="parsed",
    ).count()
    if unresolved:
        raise OnboardingError("evidence_confirmation_required", "请先确认或忽略已解析的个人资料。")
    snapshot_id = _initial_snapshot_id(user.public_id)
    existing = db.get(DBProfileSnapshot, snapshot_id)
    if existing:
        return session_payload(db, session, feature_enabled=feature_enabled)

    profile = db.get(DBStudentProfile, user.username)
    evidence = db.query(DBOnboardingPersonalEvidence).filter_by(
        session_id=session.id, owner_public_id=user.public_id, status="confirmed",
    ).order_by(DBOnboardingPersonalEvidence.created_at.asc()).all()
    snapshot_data = {
        "kind": "initial_learner_profile",
        "owner_public_id": user.public_id,
        "legacy_student_id": user.username,
        "course_context": session.course_context or {},
        "self_report": session.confirmed_fields or {},
        "initial_fields": [
            {
                "key": key,
                "value": value,
                "confidence": 1.0,
                "sourceType": "self_report",
                "sourceRef": dimension.get("turnId") or "",
                "confirmedAt": dimension.get("confirmedAt"),
            }
            for dimension in (session.confirmed_fields or {}).values()
            for key, value in (dimension.get("values") or {}).items()
        ] + [
            field
            for row in evidence
            for field in (row.confirmed_fields or [])
        ],
        "personal_evidence": [
            {
                "evidence_id": row.id,
                "evidence_type": row.evidence_type,
                "filename": row.filename,
                "source_sha256": row.source_sha256,
                "confirmed_fields": row.confirmed_fields or [],
            }
            for row in evidence
        ],
        "profile_projection": {
            "major": profile.major if profile else "",
            "target_course": profile.target_course if profile else "",
            "knowledge_base": profile.knowledge_base if profile else "",
            "learning_goals": list(profile.learning_goals or []) if profile else [],
            "weak_points": list(profile.weak_points or []) if profile else [],
            "interaction_preferences": list(profile.interaction_preferences or []) if profile else [],
            "cognitive_style": profile.cognitive_style if profile else "",
            "motivation_type": profile.motivation_type if profile else "",
            "focus_level": profile.focus_level if profile else 0.72,
            "cognitive_load": profile.cognitive_load if profile else 0.45,
            "frustration_index": profile.frustration_index if profile else 0.0,
            "misconception_patterns": dict(profile.misconception_patterns or {}) if profile else {},
            "dimension_states": dict(profile.dimension_states or {}) if profile else {},
            "mental_state_history": list(profile.mental_state_history or []) if profile else [],
        },
        "mastery_status": "awaiting_admission_assessment",
        "mastery_evidence": [],
    }
    db.add(DBProfileSnapshot(
        id=snapshot_id,
        owner_public_id=user.public_id,
        legacy_student_id=user.username,
        profile_version=INITIAL_PROFILE_VERSION,
        snapshot=snapshot_data,
        content_hash=_canonical_hash(snapshot_data),
        trace_id=f"onboarding-final:{session.id}",
    ))
    db.commit()
    return session_payload(db, session, feature_enabled=feature_enabled)
