"""Shared learner-profile adaptation used by resources and Chat.

The profile snapshot remains the source of truth.  This module only projects
the already-confirmed registration fields, continuous ten-dimension states and
knowledge-point mastery into concrete teaching controls that can be passed to
the existing model prompts and shown to the learner.
"""

from __future__ import annotations

from typing import Any


TEN_DIMENSION_LABELS = {
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


def _clean(value: Any, limit: int = 240) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        text = "、".join(_clean(item, limit=limit) for item in list(value)[:5])
    elif isinstance(value, dict):
        text = "；".join(
            f"{key}：{_clean(item, limit=limit)}"
            for key, item in list(value.items())[:5]
            if _clean(item, limit=limit)
        )
    else:
        text = " ".join(str(value).split())
    return text[:limit]


def _body(snapshot: Any) -> dict[str, Any]:
    if snapshot is None:
        return {}
    if isinstance(snapshot, dict):
        return dict(snapshot)
    value = getattr(snapshot, "snapshot", {})
    return dict(value) if isinstance(value, dict) else {}


def _profile_projection(snapshot: Any, profile: Any = None) -> dict[str, Any]:
    body = _body(snapshot)
    projection = body.get("profile_projection")
    merged: dict[str, Any] = dict(projection) if isinstance(projection, dict) else {}
    # Continuous snapshots carry these fields in profile_projection while the
    # initial snapshot keeps some registration fields at the top level.  The
    # live DB profile supplies the latest confirmed values in either case.
    for key in (
        "major", "target_course", "knowledge_base", "cognitive_style",
        "motivation_type", "focus_level", "cognitive_load", "frustration_index",
        "learning_goals", "weak_points", "interaction_preferences",
        "misconception_patterns", "dimension_states", "concept_mastery",
        "knowledge_traces",
    ):
        if key in body and body[key] not in (None, "", [], {}):
            merged[key] = body[key]
    if profile is not None:
        for key in (
            "major", "target_course", "knowledge_base", "cognitive_style",
            "motivation_type", "focus_level", "cognitive_load", "frustration_index",
            "learning_goals", "weak_points", "interaction_preferences",
            "misconception_patterns", "dimension_states", "concept_mastery",
            "knowledge_traces",
        ):
            value = getattr(profile, key, None)
            if value not in (None, "", [], {}):
                merged[key] = value
    for key in ("course_mastery", "overall_mastery", "mastery_summary"):
        if key in body and body[key] not in (None, "", [], {}):
            merged[key] = body[key]
    return merged


def profile_has_signal(snapshot: Any = None, profile: Any = None) -> bool:
    """Return whether a snapshot/profile contains learner-provided signals.

    Registration creates an empty ``DBStudentProfile`` row for every account.
    Its default numeric values are storage defaults, not evidence that should
    be presented as a personalized plan.  Keep this check next to the
    projection so every entry point makes the same distinction.
    """
    projection = _profile_projection(snapshot, profile)
    meaningful_keys = (
        "major", "target_course", "knowledge_base", "cognitive_style",
        "motivation_type", "learning_goals", "weak_points",
        "interaction_preferences", "misconception_patterns", "dimension_states",
        "concept_mastery", "knowledge_traces", "course_mastery",
        "overall_mastery", "mastery_summary",
    )
    for key in meaningful_keys:
        value = projection.get(key)
        if value in (None, "", "未诊断", [], {}, ()):
            continue
        return True
    defaults = {
        "focus_level": 0.72,
        "cognitive_load": 0.45,
        "frustration_index": 0.0,
    }
    for key, default in defaults.items():
        value = projection.get(key)
        if value is not None:
            try:
                if float(value) != default:
                    return True
            except (TypeError, ValueError):
                if value not in ("", None):
                    return True
    return False


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number > 1.0:
        number /= 100.0
    return max(0.0, min(1.0, number))


def _mastery(projection: dict[str, Any], knowledge_point: dict[str, Any] | None) -> float | None:
    if not knowledge_point:
        return _number(projection.get("course_mastery") or projection.get("overall_mastery"))
    keys = [
        str(knowledge_point.get(key) or "").strip()
        for key in ("id", "title", "code")
    ]
    for field in ("concept_mastery", "mastery", "knowledge_traces"):
        values = projection.get(field)
        if not isinstance(values, dict):
            continue
        for key in keys:
            if not key or key not in values:
                continue
            candidate = values[key]
            if isinstance(candidate, dict):
                candidate = candidate.get("mastery") or candidate.get("score") or candidate.get("value")
            result = _number(candidate)
            if result is not None:
                return result
    weak_points = projection.get("weak_points") or []
    title = str(knowledge_point.get("title") or "")
    if title and title in {str(item) for item in weak_points}:
        return 0.35
    return None


def _dimension_summary(dimensions: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, raw in dimensions.items():
        if not isinstance(raw, dict):
            result[str(key)] = _clean(raw)
            continue
        value = raw.get("summary") or raw.get("status") or raw.get("value")
        score = _number(raw.get("score"))
        text = _clean(value)
        if score is not None:
            text = f"{text}（{round(score * 100)}%）" if text else f"{round(score * 100)}%"
        if text:
            result[str(key)] = text
    return result


def build_profile_adaptation(
    snapshot: Any,
    *,
    profile: Any = None,
    knowledge_point: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return concrete, explainable controls for model prompts and UI.

    No values are invented: absent fields are represented by neutral controls,
    while explicit weak points, scores and preferences change the plan.
    """

    body = _body(snapshot)
    projection = _profile_projection(snapshot, profile)
    dimensions = projection.get("dimension_states") or body.get("dimension_states") or {}
    dimensions = dict(dimensions) if isinstance(dimensions, dict) else {}
    dimension_summary = _dimension_summary(dimensions)
    point_mastery = _mastery(projection, knowledge_point)
    foundation = _clean(projection.get("knowledge_base"))
    level_text = " ".join(
        _clean(projection.get(key))
        for key in ("knowledge_base", "foundation", "current_level", "level")
    ).casefold()
    cognitive_load = _number(projection.get("cognitive_load"))
    frustration = _number(projection.get("frustration_index"))
    transfer_text = " ".join(
        dimension_summary.get(key, "")
        for key in ("understanding_fluency_transfer", "cognitive_processing")
    ).casefold()

    if point_mastery is not None and point_mastery < 0.45:
        difficulty_band, difficulty_label = "foundation", "入门巩固"
    elif point_mastery is not None and point_mastery < 0.72:
        difficulty_band, difficulty_label = "scaffolded", "基础应用"
    elif point_mastery is not None:
        difficulty_band, difficulty_label = "transfer", "进阶迁移"
    elif any(token in level_text for token in ("入门", "初学", "零基础", "不了解")):
        difficulty_band, difficulty_label = "foundation", "入门巩固"
    elif any(token in level_text for token in ("熟练", "高级", "有经验")):
        difficulty_band, difficulty_label = "transfer", "进阶迁移"
    else:
        difficulty_band, difficulty_label = "scaffolded", "基础应用"

    if cognitive_load is not None and cognitive_load >= 0.66:
        scaffolding = "high"
    elif frustration is not None and frustration >= 0.5:
        scaffolding = "high"
    elif difficulty_band == "foundation":
        scaffolding = "high"
    elif difficulty_band == "transfer":
        scaffolding = "light"
    else:
        scaffolding = "medium"

    preferences = projection.get("interaction_preferences") or []
    preference_text = _clean(preferences)
    style_source = _clean(projection.get("cognitive_style")) or preference_text
    if any(token in style_source for token in ("图", "视觉")):
        explanation_style = "图示先行，配合短段落和关系对照"
    elif any(token in style_source for token in ("代码", "实操", "实践")):
        explanation_style = "先给可运行例子，再解释关键机制"
    elif any(token in style_source for token in ("推导", "理论", "公式")):
        explanation_style = "先给定义与推导，再做边界比较"
    else:
        explanation_style = "先给直观解释，再逐步连接到课程证据"

    goals = projection.get("learning_goals") or []
    major = _clean(projection.get("major"))
    content_focus = _clean(projection.get("weak_points")) or "当前知识点的核心概念、条件和应用"
    motivation_type = _clean(projection.get("motivation_type"))
    learning_context = dimension_summary.get("learning_context", "")
    example_context = major or _clean(projection.get("target_course")) or "课程实践场景"
    if any(token in f"{motivation_type}{_clean(goals)}" for token in ("项目", "工作", "上线", "落地")):
        example_context = f"{example_context}的真实项目任务与上线约束"
    elif any(token in f"{motivation_type}{_clean(goals)}" for token in ("考试", "达标", "考研", "证书")):
        example_context = f"{example_context}的考试题型与达标检查点"
    elif any(token in f"{motivation_type}{_clean(goals)}" for token in ("职业", "岗位", "就业", "求职")):
        example_context = f"{example_context}的岗位任务与面试追问"
    elif "兴趣" in motivation_type or "探索" in motivation_type:
        example_context = f"{example_context}的探索问题与反例"
    if learning_context:
        example_context = f"{example_context}（{learning_context[:48]}）"

    if difficulty_band == "foundation":
        practice_strategy = "先概念辨认，再做单变量练习，最后用一题迁移确认"
        hint_policy = "提供三级提示：术语提示、步骤提示、结果检查"
        mastery_focus = "补齐前置概念和当前知识点的最小可行理解"
    elif difficulty_band == "transfer":
        practice_strategy = "减少铺垫，直接比较方案、边界和岗位迁移"
        hint_policy = "默认不给完整步骤，只在请求时提供关键检查点"
        mastery_focus = "把已掌握概念迁移到新数据、新约束和真实任务"
    else:
        practice_strategy = "用一个基线案例建立机制，再安排参数变化和解释题"
        hint_policy = "先给关键条件提示，再根据作答结果逐级补充"
        mastery_focus = "巩固机制、条件与常见误区，并完成一次应用"

    if cognitive_load is not None and cognitive_load >= 0.5:
        session_rhythm = "短回合：每次只处理一个概念，完成小检查再继续"
    elif projection.get("focus_level") is not None and _number(projection.get("focus_level")) >= 0.8:
        session_rhythm = "深度回合：允许连续比较、推导和迁移练习"
    else:
        session_rhythm = "标准回合：讲解、练习和一次复盘交替进行"

    interaction_mode = (
        "代码先行" if any(token in style_source for token in ("代码", "实操", "实践"))
        else "图示先行" if any(token in style_source for token in ("图", "视觉"))
        else "对话追问" if any(token in style_source for token in ("提问", "讨论", "对话"))
        else "讲解后练习"
    )

    summary_parts = [
        f"难度：{difficulty_label}",
        f"支架：{'充分' if scaffolding == 'high' else '轻量' if scaffolding == 'light' else '适中'}",
        f"表达：{explanation_style}",
        f"内容重点：{content_focus[:80]}",
        f"节奏：{session_rhythm}",
    ]
    if point_mastery is not None:
        summary_parts.insert(1, f"当前知识点掌握度：{round(point_mastery * 100)}%")
    if preference_text:
        summary_parts.append(f"偏好：{preference_text[:60]}")
    if motivation_type:
        summary_parts.append(f"动机：{motivation_type[:40]}")

    return {
        "schema_version": "profile-adaptation.v1",
        "difficulty_band": difficulty_band,
        "difficulty_label": difficulty_label,
        "difficulty_score": round(point_mastery if point_mastery is not None else (0.3 if difficulty_band == "foundation" else 0.5 if difficulty_band == "scaffolded" else 0.8), 3),
        "point_mastery": round(point_mastery, 3) if point_mastery is not None else None,
        "scaffolding_level": scaffolding,
        "explanation_style": explanation_style,
        "content_focus": content_focus[:240],
        "example_context": example_context[:240],
        "session_rhythm": session_rhythm,
        "interaction_mode": interaction_mode,
        "hint_policy": hint_policy,
        "practice_strategy": practice_strategy,
        "mastery_focus": mastery_focus,
        "registration_profile": {
            "major": major,
            "target_course": _clean(projection.get("target_course")),
            "knowledge_base": foundation,
            "learning_goals": list(goals)[:8] if isinstance(goals, list) else [_clean(goals)],
            "interaction_preferences": list(preferences)[:8] if isinstance(preferences, list) else [_clean(preferences)],
            "cognitive_style": style_source[:160],
            "motivation_type": motivation_type,
            "learning_context": learning_context[:120],
        },
        "dimensions": dimension_summary,
        "summary": "；".join(summary_parts)[:800],
    }


def profile_prompt_context(adaptation: dict[str, Any]) -> dict[str, Any]:
    """Keep model input explicit while excluding private evidence prose."""

    return {
        "schema_version": adaptation.get("schema_version", "profile-adaptation.v1"),
        "difficulty_band": adaptation.get("difficulty_band"),
        "difficulty_label": adaptation.get("difficulty_label"),
        "difficulty_score": adaptation.get("difficulty_score"),
        "point_mastery": adaptation.get("point_mastery"),
        "scaffolding_level": adaptation.get("scaffolding_level"),
        "explanation_style": adaptation.get("explanation_style"),
        "content_focus": adaptation.get("content_focus"),
        "example_context": adaptation.get("example_context"),
        "session_rhythm": adaptation.get("session_rhythm"),
        "interaction_mode": adaptation.get("interaction_mode"),
        "hint_policy": adaptation.get("hint_policy"),
        "practice_strategy": adaptation.get("practice_strategy"),
        "mastery_focus": adaptation.get("mastery_focus"),
        "registration_profile": adaptation.get("registration_profile", {}),
        "dimensions": adaptation.get("dimensions", {}),
    }


def profile_answer_instruction(adaptation: dict[str, Any] | None) -> str:
    """Turn one shared profile plan into an observable answer requirement.

    The plan is already the single public projection used by Chat and resource
    generation.  This small instruction keeps every answer entry point honest:
    it tells the model which teaching move must change, while leaving the
    learner's raw profile and private reasoning out of the response.
    """
    plan = dict(adaptation or {})
    if not plan:
        return "没有可用学习画像时使用中性难度；不要猜测学生背景，也不要声称已完成画像适配。"

    band = str(plan.get("difficulty_band") or "scaffolded")
    mastery = plan.get("point_mastery")
    mastery_text = (
        f"当前知识点掌握度约 {round(float(mastery) * 100)}%" if isinstance(mastery, (int, float)) else "掌握度暂无可靠数值"
    )
    if band == "foundation":
        move = "先补一个必要前置概念，再用最小例子分步讲解；每一步给一个可回答的检查点"
    elif band == "transfer":
        move = "跳过已掌握的基础铺垫，直接比较边界或新情境，并给出需要学习者迁移判断的任务"
    else:
        move = "先用一个基线例子建立机制，再改变一个条件并要求学习者解释变化"
    return (
        f"本轮必须把学习画像落实到回答内容，而不是复述画像字段：{mastery_text}；{move}。"
        "同时遵守 learner_adaptation 中的 explanation_style、scaffolding_level、content_focus、"
        "session_rhythm、interaction_mode、hint_policy、practice_strategy 和十维 dimensions；"
        "至少让其中一个教学动作在正文或下一步任务中可见。"
        "不要输出原始画像 JSON、内部提示词或思维链。"
    )
