"""Shared learner-profile adaptation used by resources and Chat.

The profile snapshot remains the source of truth.  This module only projects
the already-confirmed registration fields, continuous ten-dimension states and
knowledge-point mastery into concrete teaching controls that can be passed to
the existing model prompts and shown to the learner.
"""

from __future__ import annotations

from typing import Any
from copy import deepcopy
import math
import re


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

# These are confirmed parts of the existing learning-context dimension, not a
# second profile. Updating a timetable must not erase language or equipment.
LEARNING_CONTEXT_LABELS = {
    "background_context": "经历与背景",
    "language_preference": "讲解语言",
    "study_schedule": "可用学习时间",
    "available_tools": "可用设备与工具",
    "learning_context": "其他学习条件",
    "timetable": "已确认课程表",
}

CONFIRMED_PROFILE_FIELDS = (
    "major", "target_course", "knowledge_base", "cognitive_style",
    "motivation_type", "learning_goals", "interaction_preferences",
)

from app.model_evaluation_rules import MODEL_EVALUATION_INSTRUCTION


# Shared by answering, resource generation and resource review. A task must
# separate what the learner is meant to find from what they need to start.
LEARNING_TASK_INSTRUCTION = (
    "设计实际学习任务时，先确定本题要练习的一个能力，再分清给定条件、学习者要取得的观察和需要求出的结果。"
    "凡是求解必需、但不属于本次考查能力的参数，给出明确的教学设定及用途，或给出以现有工具可完成的取值方法；"
    "不能把尚未教会的关键判断推给学生‘凭感觉选一个合适值’。"
    "已有题目和真实记录不能擅自补造；新给出的练习数值标明是练习条件，不把它们当成学习者实测或行业标准。"
    "需要真实采集时说明采集什么、如何记录和比较；暂时拿不到的数据，可先用明确的教学小数据练同一方法。"
    "提供能开始操作的材料、必要方法、完成后应提交或观察的结果，以及不泄露待求答案的自查办法。"
    "题目要用的数据表、数值和判断条件必须出现在该页或实际可打开的配套中；解析不能新增题干未给出的条件。"
    "要求唯一判断或公平比较时，逐项给出影响答案的条件，例如同一验证集、指标口径和预处理拟合范围；‘未列出额外条件’不能代替实际条件。"
    "若本题考查辨认信息不足，则允许答案指出缺什么，并安排可执行的核对步骤；不能一边缺条件一边要求唯一选模。"
    "独立作答的每道题保留求解所需的模型、公式与参数，不用‘仍取’或‘同上’代替前题条件。"
    "有共同核心与画像附加题的测验，先让共同题覆盖共同核心的计算和判断；不能只在某一画像附加题的解析中补一个共同要求，却声称各组已接受同一核心检查。"
    "请求包含多个计算或判断时逐项落实，不能只算验证误差就声称已复算训练与验证误差；已给最终值不等于完成了要求的计算。"
    "需要从头计算时提供相应原始值与预测或其它必要输入，基础薄弱者可用表格或手算，不能只有尚未掌握的代码入口。"
    "新表独立判断要有未讲解过的数据或问题；只将旧例换名、调序或遮住已公布的答案不算新任务。"
    "判断预测输入时写清预测发生的时点及那时已知的列，不能从历史表有这一列就推定预测时也能取得。"
    "逐步核对学习者在现有设备、地点、时间和人手条件下能否独立执行：一个人不能同时承担互相冲突的操作。"
    "把动手步骤按实际先后写清：先布置什么、人在什么位置、怎样触发或记录、何时改变对象。"
    "需要同时操作两处时，改用够得着的布置、设备已有的延时功能或能自行持续的运动，并说明具体做法；不要只写‘同时操作’。"
    "明确要求独自完成时，不安排家人、同伴或教师协助；用可自行控制的对象或步骤实现同一学习目标。"
    "涉及状态量和判断阈值，分清实际比较的量、计量口径、单位与适用条件，不能为简化讲解改掉概念定义。"
    "数学判断按本题固定条件计算或推导：允许等价变形；某性质在一般情形不保证，不等于在当前特例也不能成立。解析和自查的正反判定须与题目一致。"
    "区分保证某结果的充分条件与必要条件；前提改变后应重新核对，不能直接断言结果必变。比较计数与比率时检查同比缩放是否抵消，条件概率不能交换条件方向。"
    "数学说明与实际计算逐项对应：区分梯度、负梯度方向、学习率乘梯度的更新量，以及乘性因子与参数变化量。比较两种算法是否等价时核对取值点、执行顺序、参数范围和系数定义，不能只比最终公式外观。"
    "实验中的损失、特征筛选和评价方法须符合目标类型；回归与分类的评分函数不能混用。数值单位随运算变化，平方误差使用原量的平方单位。"
    "讲解训练与评估时，区分拟合参数和选择方案：预处理及模型参数在训练部分拟合，验证结果可以选择超参数、特征方案与候选模型；"
    "交叉验证的每折也如此。方案和超参数选定后，可以合并训练与验证数据重新拟合最终模型及预处理；"
    "合并本身不是泄漏，但原验证行已参与最终拟合，其旧分数不能当作该模型的独立最终测试成绩。"
    "最终测试独立于这些拟合与选择，不能把正常验证选模或最终重拟合说成泄漏，也不能把选模后的验证分数当成未参与选择的最终测试。"
    "让学生先尝试时，方法不等于答案：可给关系式、单位和对照方式，不提前给出该题最终数值或替学生做完关键判断。"
    "按已确认的设备、基础、语言和时段安排任务；未确认的设备功能不能断言支持或不支持，必要时给出能执行的条件分支。"
    "对比任务先写能观察到什么，再说明它支持什么判断；同一现象可能有多种原因时，安排可实行的下一步区分，"
    "不能在开头把后面仍需检验的线索说成已经能唯一判因。"
    "让学习者用少量关键记录完成比较；相同布置和条件只交代一次，记录表直接给出，避免反复解释同一限制。"
    "围绕本次能力选择工具复杂度；仅需观察数据或按给定阈值判断时，先完成该判断，不为了演示专业性额外要求尚未学习的模型训练、概率变换或编程语法。"
    "仅在本次请求或资源本身需要练习时应用这些要求，不给普通短问答自动加题。"
    + MODEL_EVALUATION_INSTRUCTION
)


TEACHING_ADAPTATION_INSTRUCTION = (
    "先从当前学习依据和已确认条件选出本次最有影响的教学决定，再落实到实际内容顺序、任务和检查。"
    "当前任务的实际完成依据决定哪些内容需要再教；注册时的‘新公式先看示例’等偏好只决定尚需教学部分的讲法，不能覆盖后来已掌握的同一能力。"
    "已独立掌握的同一能力从新任务或简短检查开始，完整示例可保留作按需回看；未掌握或仅经提示完成的步骤先示范或给局部支架，再撤去提示。"
    "已确认缺少新概念基础时，用可复算的小变化或已会的方法连接概念含义和公式，再进入应用；不只给结论让学生照抄。基础练习放在首次需要它的任务之前。"
    "逐项区分已会的判断、仍需补的计算与尚未验证的迁移，不把总体‘迁移待验证’当作重讲所有基础的理由。"
    "对已掌握的定义与选择依据，不再安排必做的基础复述和逐题概念提示；将新情境判断放在前面，必要的新计算示范只覆盖未学步骤。"
    "assessment_target.independence_evidence描述已有完成方式，只用于其中明确涉及的能力；其它诊断缺口仍须处理，不能把独立完成一题扩成全课掌握。"
    "目标要求操作或交接时，给实际操作步骤和可交付记录；不能只换一个职业案例或写一张已填好的结论卡。"
    "可用时间决定每段的停止位置、应保存的记录和下次从哪一步继续，estimatedMinutes按工作量估算；时间更长可合并片段，不增加重复基础。"
    "工具能减少本任务操作负担时，提供对应输入与操作方法；新增电脑或Python环境不代表已经会编程，可给可运行骨架或表格步骤。"
    "资源页面没有内嵌运行器，不等于已确认的本地工具不可用；可给完整代码和本地执行步骤，或电子表格公式。未提供交互实验模板也不取消这些计算途径。"
    "用同一专业核心检查学习结果，按已确认语言解释。上述安排写入实际任务位置，内部画像依据不重复展示成页面导语。"
)


def confirmed_profile_fields(profile: Any) -> dict[str, Any]:
    """Keep confirmed choices beside new learning facts, including cleared values."""
    fields = {key: deepcopy(getattr(profile, key, None)) for key in CONFIRMED_PROFILE_FIELDS}
    detail = _initial_preference_detail(profile=profile)
    if detail:
        fields["interaction_preferences"] = list(dict.fromkeys([*(fields.get("interaction_preferences") or []), detail]))
    return fields


def _initial_preference_detail(snapshot: Any = None, *, profile: Any = None) -> str:
    """Read an old confirmed preference explanation that was not projected.

    No historical row is rewritten. A later explicit preference, including a
    cleared one, takes precedence over the initial conversation.
    """
    if profile is not None:
        if {"interaction_preferences", "cognitive_style"}.intersection(getattr(profile, "customized_fields", None) or []):
            return ""
        from app.database import DBOnboardingSession, DBStudentProfile
        from sqlalchemy.orm import object_session
        if not isinstance(profile, DBStudentProfile) or (db := object_session(profile)) is None:
            return ""
        session = db.query(DBOnboardingSession).filter_by(student_id=profile.student_id).first()
        report = session.confirmed_fields if session else {}
    else:
        body = _body(snapshot)
        report = body.get("self_report") or {}
        if not isinstance(report, dict):
            return ""
    values = (report.get("preference") or {}).get("values") or {}
    return _clean(values.get("preference_context"), limit=None)


def interpreted_dimension_states(db: Any, dimensions: dict[str, Any], *,
                                 student_id: str = "", owner_public_id: str = "",
                                 concept_mastery: Any = None) -> dict[str, Any]:
    """Read unscored confirmations consistently without changing old records.

    Older report saves inserted zero into verbal descriptions. Only the same
    learner's original confirmation can identify that zero as a copied default;
    a later observation or actual subject mastery retains its recorded score.
    """
    states = deepcopy(dimensions or {})
    turn_ids = {v.get("source_turn_id") for v in states.values() if isinstance(v, dict)} - {None, ""}
    turns = {}
    if db is not None and turn_ids and (student_id or owner_public_id):
        from app.database import DBOnboardingTurn, DBOnboardingSession
        query = db.query(DBOnboardingTurn).join(DBOnboardingSession).filter(
            DBOnboardingTurn.turn_id.in_(turn_ids), DBOnboardingTurn.status == "confirmed")
        query = query.filter(DBOnboardingSession.student_id == student_id) if student_id else query.filter(
            DBOnboardingSession.owner_public_id == owner_public_id)
        turns = {row.turn_id: row for row in query.all()}
    for key, state in states.items():
        if not isinstance(state, dict):
            continue
        turn = turns.get(state.get("source_turn_id"))
        description = next((item for item in (turn.confirmed_fields or {}).get("dimensions", [])
                            if item.get("key") == key and item.get("score") is None), None) if turn else None
        verbal_zero = (
            state.get("score") == 0 and description is not None and turn.confirmed_at
            and state.get("last_updated") and state["last_updated"] <= turn.confirmed_at.isoformat()
            and not (key == "knowledge_mastery" and concept_mastery)
        )
        if state.get("score") is None or verbal_zero:
            state["qualitative"] = True
            state["self_report"] = state.get("self_report") or (description or {}).get("value") or state.get("summary") or state.get("status") or ""
    return states


def complete_learning_snapshot(db: Any, snapshot: Any) -> dict[str, Any]:
    """Read old feedback snapshots with the preferences confirmed at that time.

    Old aggregation snapshots omitted registration fields. Resolve those fields
    from an earlier snapshot of this learner/course, without rewriting history
    or borrowing today's preferences for an old resource.
    """
    body = deepcopy(_body(snapshot))
    for projection in (body, body.get("profile_projection") or {}):
        if projection.get("dimension_states"):
            projection["dimension_states"] = interpreted_dimension_states(
                db, projection["dimension_states"], owner_public_id=getattr(snapshot, "owner_public_id", ""),
                concept_mastery=projection.get("concept_mastery"))
    if body.get("kind") not in {"learning_aggregation_projection", "learning_aggregation_baseline", "flashcard_mastery_correction"}:
        return body
    projection = dict(body.get("profile_projection") or {})
    missing = set(CONFIRMED_PROFILE_FIELDS) - projection.keys() - body.keys()
    if not missing or not getattr(snapshot, "owner_public_id", None) or not getattr(snapshot, "created_at", None):
        return body
    from app.database import DBProfileSnapshot
    previous = db.query(DBProfileSnapshot).filter(
        DBProfileSnapshot.owner_public_id == snapshot.owner_public_id,
        DBProfileSnapshot.created_at <= snapshot.created_at,
        DBProfileSnapshot.id != snapshot.id,
    ).order_by(DBProfileSnapshot.created_at.desc(), DBProfileSnapshot.id.desc())
    for row in previous:
        earlier = row.snapshot or {}
        course = earlier.get("course_id") or (earlier.get("course_context") or {}).get("courseId")
        if course not in {None, body.get("course_id")}:
            continue
        fields = dict(earlier.get("profile_projection") or {})
        fields.update({key: earlier[key] for key in CONFIRMED_PROFILE_FIELDS if key in earlier})
        for key in list(missing):
            if key in fields:
                projection[key] = deepcopy(fields[key])
                missing.remove(key)
        if not missing:
            break
    body["profile_projection"] = projection
    return body


def _clean(value: Any, limit: int | None = 240) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        text = "、".join(_clean(item, limit=limit) for item in (list(value)[:5] if limit is not None else value))
    elif isinstance(value, dict):
        text = "；".join(
            f"{key}：{_clean(item, limit=limit)}"
            for key, item in (list(value.items())[:5] if limit is not None else value.items())
            if _clean(item, limit=limit)
        )
    else:
        text = " ".join(str(value).split())
    return text[:limit] if limit is not None else text


def _body(snapshot: Any) -> dict[str, Any]:
    if snapshot is None:
        return {}
    if isinstance(snapshot, dict):
        return dict(snapshot)
    value = getattr(snapshot, "snapshot", {})
    return dict(value) if isinstance(value, dict) else {}


def grading_learning_needs(grading: dict[str, Any] | None, *, explanation: str = "") -> list[dict[str, Any]]:
    """Keep actionable rubric gaps visible even when the total score passes."""
    grading = grading or {}
    if grading.get("status") != "completed":
        return []
    needs = []
    for criterion in grading.get("criterionResults", grading.get("criterion_results", [])) or []:
        score = criterion.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
            continue
        if 0 <= score < 0.7:
            objective_explanation = explanation.strip() if criterion.get("criterion_id") == "answer_correctness" else ""
            needs.append({
                "criterion_id": criterion.get("criterion_id"), "score": score,
                "basis": objective_explanation or str(criterion.get("justification") or ""),
                "next_step": ("结合原题核对：" + objective_explanation) if objective_explanation else str(criterion.get("improvement") or ""),
            })
    return sorted(needs, key=lambda item: item["score"])


def diagnostic_followup(snapshot: Any, knowledge_point_id: str | None = None) -> list[dict[str, Any]]:
    """Project original diagnostic gaps, to compare with later learning evidence."""
    body = _body(snapshot)
    current = body.get("current_learning_evidence") or {}
    result = []
    for item in (body.get("diagnostic_evidence") or {}).get("grading_feedback", []):
        if knowledge_point_id and item.get("knowledge_point_id") != knowledge_point_id:
            continue
        if item.get("knowledge_point_id") in current:
            continue
        needs = grading_learning_needs(item.get("grading"), explanation=str(item.get("explanation") or ""))
        if needs:
            result.append({"knowledge_point_id": item.get("knowledge_point_id"),
                           "attempt_id": item.get("attempt_id"), "learning_needs": needs})
    for point_id, evidence in current.items():
        if knowledge_point_id and point_id != knowledge_point_id:
            continue
        if evidence.get("learning_needs"):
            result.append({"knowledge_point_id": point_id, "source": "current_learning_evidence",
                           "learning_needs": deepcopy(evidence["learning_needs"])})
    represented = {item["knowledge_point_id"] for item in result} | current.keys()
    for point_id, evidence in (body.get("mastery_by_knowledge_point") or {}).items():
        if point_id in represented or (knowledge_point_id and point_id != knowledge_point_id):
            continue
        if isinstance(evidence, dict) and evidence.get("learning_needs"):
            result.append({"knowledge_point_id": point_id,
                           "learning_needs": deepcopy(evidence["learning_needs"])})
    return result


def with_current_learning_evidence(db: Any, snapshot: Any, *, actor: Any,
                                   course_id: str, knowledge_point_id: str) -> dict[str, Any]:
    """Freeze current same-course observations beside a chosen historical profile.

    New teaching uses the graph's current answer/evidence interpretation; the
    selected registration profile, original grades and old resources stay intact.
    """
    body = deepcopy(_body(snapshot))
    from app.database import DBCourse
    from course_catalog import course_is_selectable
    course = db.get(DBCourse, course_id)
    # Legacy/archived courses can still receive feedback for saved resources.
    # The public graph requires a ready course; retain that snapshot's evidence
    # when no current course graph is available instead of blocking feedback.
    if course is None or not course_is_selectable(db, course):
        return body
    from app.profile_summary import build_profile_summary
    graph = build_profile_summary(db, current_user=actor, course_id=course_id)["knowledge_graph"]
    for point in graph["nodes"]:
        if point["id"] != knowledge_point_id:
            continue
        actual_evidence = bool(point.get("sourceEventIds")) or any(
            item.get("sourceType") == "assessment_attempt" for item in point.get("evidence", [])
        )
        if actual_evidence and point.get("mastery") is not None:
            body["current_learning_evidence"] = {knowledge_point_id: {
                "score": point["mastery"], "status": point["masteryBand"],
                "learning_needs": deepcopy(point.get("learningNeeds", [])),
                "source_event_ids": list(point.get("sourceEventIds", [])),
                "assessment_attempt_ids": [item["sourceId"] for item in point.get("evidence", [])
                                           if item.get("sourceType") == "assessment_attempt"],
                "observed_at": point.get("lastEvidenceAt"),
            }}
        break
    return body


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
        "knowledge_traces", "mastery", "mastery_by_knowledge_point", "current_learning_evidence",
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
        # Raw ORM profiles are used by chat and planning; reports use an
        # already interpreted dataclass. Both must expose the same evidence.
        from app.database import DBStudentProfile
        if isinstance(profile, DBStudentProfile):
            from sqlalchemy.orm import object_session
            merged["dimension_states"] = interpreted_dimension_states(
                object_session(profile), merged.get("dimension_states") or {},
                student_id=profile.student_id, concept_mastery=merged.get("concept_mastery"))
    for key in ("course_mastery", "overall_mastery", "mastery_summary"):
        if key in body and body[key] not in (None, "", [], {}):
            merged[key] = body[key]
    # A newly confirmed explanation replaces an old inferred current signal,
    # while the stored scalar and historical snapshots remain untouched.
    for state in (merged.get("dimension_states") or {}).values():
        scores = state.get("confirmed_state_scores") if isinstance(state, dict) else getattr(state, "confirmed_state_scores", None)
        for name, value in (scores or {}).items():
            if name in {"frustration_index", "cognitive_load", "focus_level"}:
                merged[name] = value
    detail = _initial_preference_detail(snapshot, profile=profile)
    if detail:
        merged["interaction_preferences"] = list(dict.fromkeys([*(merged.get("interaction_preferences") or []), detail]))
    if profile is not None and "interaction_preferences" in (getattr(profile, "customized_fields", None) or []):
        # Explicit clearing must not restore an older snapshot's preference.
        merged["interaction_preferences"] = list(getattr(profile, "interaction_preferences", None) or [])
    return merged


def current_learning_state(profile: Any) -> dict[str, dict[str, Any]]:
    """Share the currently confirmed interpretation with reports and views.

    Stored scalars remain historical facts. A later verbal confirmation can
    supersede their use without turning that description into a new number.
    """
    projection = _profile_projection({}, profile)
    dimensions = projection.get("dimension_states") or {}
    result = {}
    for field, dimension in (("frustration_index", "affect_resilience"),
                             ("cognitive_load", "cognitive_processing"),
                             ("focus_level", "cognitive_processing")):
        state = dimensions.get(dimension) or {}
        qualitative = state.get("qualitative") if isinstance(state, dict) else getattr(state, "qualitative", False)
        report = state.get("self_report", "") if isinstance(state, dict) else getattr(state, "self_report", "")
        result[field] = {"value": projection.get(field), "description": report if qualitative else ""}
    return result


def _confirmed_learning_context(snapshot: Any) -> str:
    body = _body(snapshot)
    adaptation = body.get("learning_adaptation") or {}
    adapted_schedule = (adaptation.get("learning_requirements") or {}).get("study_schedule")
    if adapted_schedule:
        return _current_schedule_text(str(adapted_schedule))
    adapted_context = (adaptation.get("registration_profile") or {}).get("learning_context")
    if adapted_context:
        return _current_schedule_text(str(adapted_context))
    projection = _profile_projection(snapshot)
    context = (projection.get("dimension_states") or {}).get("learning_context") or {}
    if isinstance(context, dict):
        schedule = (context.get("confirmed_fields") or {}).get("study_schedule")
        if schedule:
            return _current_schedule_text(str(schedule))
    summary = str(context.get("summary") or context.get("status") or "") if isinstance(context, dict) else ""
    return _current_schedule_text(summary)


def _current_schedule_text(summary: str) -> str:
    """Read an explicit replacement without counting the replaced arrangement.

    The confirmed sentence and its history remain intact. Ambiguous/conditional
    availability still receives no invented calendar days.
    """
    if re.search(r"如果|可能|不确定|\b(?:if|maybe|might|unless)\b", summary, flags=re.I):
        return summary
    current = re.split(r"(?:从现在起|现在改为|现改为|现为|现在可以|\bfrom now on\b)", summary, flags=re.I)
    active = current[-1] if len(current) > 1 else summary
    return re.split(r"[，,；;]?\s*(?:替代(?:原来|之前)?的?|取代(?:原来|之前)?的?|而不是|\binstead of\b|\brather than\b)", active, maxsplit=1, flags=re.I)[0]


def _learning_requirements(projection: dict[str, Any]) -> dict[str, Any]:
    state = (projection.get("dimension_states") or {}).get("learning_context") or {}
    state = state if isinstance(state, dict) else {}
    confirmed = state.get("confirmed_fields") or {}
    return {
        **{key: _clean(confirmed.get(key), limit=None) for key in LEARNING_CONTEXT_LABELS},
        "learning_goal": _clean(projection.get("learning_goals"), limit=None),
        "confirmed_context": _clean(state.get("summary"), limit=None),
        "application": {
            "background": "用已确认的经历搭桥解释，不由职业、学历或国家推定当前课程的掌握程度。",
            "goal": "围绕想做成的任务选择例子、练习和完成标准，保留完成任务必需的领域知识。",
            "language": "按明确的讲解语言与术语要求编写主体；未指定时沿用本次提问语言。",
            "schedule": "按明确的可用时间拆成能完成的小段，保留整个目标及后续接续，不因时间少降低能力判断。",
            "tools": "给出在已有设备与工具上可完成的操作、输入和检查结果；不假设有电脑、编程环境或付费软件。",
        },
    }


def confirmed_study_days(snapshot: Any) -> tuple[int, ...]:
    """Read explicit weekly availability from the confirmed learning arrangement."""
    summary = _confirmed_learning_context(snapshot)
    # A negative or conditional sentence is not a positive availability list.
    if re.search(r"不能|没空|不方便|不确定|不再|除外|以外|如果|可能|以前|原来|\b(?:not|except|unless|cannot|can't|unavailable)\b", summary, flags=re.I):
        return ()
    if "每天" in summary or "每日" in summary:
        return tuple(range(7))
    labels = "一二三四五六日"
    days: set[int] = set()
    for start, end in re.findall(r"(?:周|星期|礼拜)([一二三四五六日天])\s*(?:到|至|[-—~～])\s*(?:周|星期|礼拜)?([一二三四五六日天])", summary):
        first, last = labels.index(start.replace("天", "日")), labels.index(end.replace("天", "日"))
        days.update((first + offset) % 7 for offset in range((last - first) % 7 + 1))
    for group in re.findall(r"(?:周|星期|礼拜)([一二三四五六日天](?:\s*[、和及,，]\s*[一二三四五六日天])*)", summary):
        days.update(labels.index(day.replace("天", "日")) for day in re.findall(r"[一二三四五六日天]", group))
    if "工作日" in summary:
        days.update(range(5))
    if "周末" in summary:
        days.update((5, 6))
    english = summary.casefold()
    if re.search(r"\b(?:daily|every day|each day)\b", english):
        days.update(range(7))
    for index, name in enumerate(("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")):
        if re.search(rf"\b{name}s?\b", english):
            days.add(index)
    if re.search(r"\bweekdays?\b", english):
        days.update(range(5))
    if re.search(r"\bweekends?\b", english):
        days.update((5, 6))
    return tuple(sorted(days))


def confirmed_study_minutes_by_weekday(snapshot: Any) -> dict[int, int]:
    """Keep durations attached to explicitly confirmed weekdays, without averaging."""
    summary = _confirmed_learning_context(snapshot).replace('半小时', '30分钟')
    days = confirmed_study_days(snapshot)
    if not days:
        return {}
    result = {}
    end = 0
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(分钟|小时|minutes?\b|hours?\b)", summary, flags=re.I):
        clause = summary[end:match.start()]
        end = match.end()
        if re.search(r'共|合计|总计|总共|\btotal\b', clause, flags=re.I):
            return {}
        attached_days = confirmed_study_days({'dimension_states': {'learning_context': {'summary': clause}}})
        minutes = round(float(match[1]) * (60 if match[2].lower() in {'小时','hour','hours'} else 1))
        if not attached_days or not 15 <= minutes <= 480:
            return {}
        for day in attached_days:
            if day in result and result[day] != minutes:
                return {}
            result[day] = minutes
    return result if set(result) == set(days) else {}


def confirmed_study_minutes(snapshot: Any) -> int | None:
    """Read one unambiguous confirmed study duration; never infer from grades or clocks."""
    body = _body(snapshot)
    summary = _confirmed_learning_context(snapshot).replace('半小时', '30分钟')
    durations = {
        round(float(amount) * (60 if unit.lower() in {"小时", "hour", "hours"} else 1))
        for amount, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(分钟|小时|minutes?\b|hours?\b)", summary, flags=re.I)
    }
    if len(durations) == 1:
        value = next(iter(durations))
        return value if 15 <= value <= 480 else None
    if len(durations) > 1:
        # The path splits work to fit even the shorter confirmed session;
        # the calendar retains each day's full capacity separately.
        weekly = confirmed_study_minutes_by_weekday(snapshot)
        return min(weekly.values()) if weekly else None
    for value in (body.get("time_budget_minutes"), (body.get("profile_projection") or {}).get("time_budget_minutes")):
        try:
            minutes = int(value)
            if 15 <= minutes <= 480:
                return minutes
        except (TypeError, ValueError):
            pass
    return None


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
        "concept_mastery", "knowledge_traces", "mastery", "mastery_by_knowledge_point",
        "current_learning_evidence", "course_mastery",
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
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if number > 1.0:
        number /= 100.0
    return max(0.0, min(1.0, number))


def _mastery(projection: dict[str, Any], knowledge_point: dict[str, Any] | None) -> float | None:
    if not knowledge_point:
        return next((score for key in ("course_mastery", "overall_mastery")
                     if (score := _number(projection.get(key))) is not None), None)
    keys = [
        str(knowledge_point.get(key) or "").strip()
        for key in ("id", "title", "code")
    ]
    for field in ("current_learning_evidence", "mastery_by_knowledge_point", "concept_mastery", "mastery", "knowledge_traces"):
        values = projection.get(field)
        if not isinstance(values, dict):
            continue
        for key in keys:
            if not key or key not in values:
                continue
            candidate = values[key]
            if isinstance(candidate, dict):
                candidate = next((score for field in ("mastery", "score", "value")
                                  if (score := _number(candidate.get(field))) is not None), None)
            result = _number(candidate)
            if result is not None:
                return result
            if field in {"current_learning_evidence", "mastery_by_knowledge_point"}:
                # Explicit unmeasured course evidence must not fall through to
                # an older generic profile value for a similarly named topic.
                return None
    return None


def _dimension_summary(dimensions: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, raw in dimensions.items():
        if not isinstance(raw, dict):
            from dataclasses import asdict, is_dataclass
            if is_dataclass(raw):
                raw = asdict(raw)
            else:
                result[str(key)] = _clean(raw)
                continue
        if raw.get("qualitative"):
            result[str(key)] = _clean(raw.get("self_report") or raw.get("summary"))
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
    point_keys = {str((knowledge_point or {}).get(key) or "") for key in ("id", "title", "code")} - {""}
    weak_reports = [str(item) for item in projection.get("weak_points") or []]
    reported_weakness = bool(point_keys.intersection(weak_reports))
    reported_starts = [item for item in body.get("self_reported_learning_start_points", []) if isinstance(item, dict)]
    # Actual later mastery takes precedence below. A self-reported starting
    # point requests scaffolding without inventing a zero score.
    reported_weakness = reported_weakness or any(
        point_keys.intersection({str(item.get("knowledgePointId") or ""), str(item.get("title") or "")})
        for item in reported_starts
    )
    point_title = str((knowledge_point or {}).get("title") or "").strip()
    if point_title and not reported_weakness:
        # Confirmed difficulties often retain a full sentence, not a bare KP ID.
        # Match the current topic, while keeping resolved/negated difficulties out.
        pattern = re.escape(point_title)
        if point_title.isascii():
            pattern = rf"(?<!\w){pattern}(?!\w)"
        reported_weakness = any(
            re.search(pattern, statement, re.I)
            and not re.search(r"不再|已(?:经)?解决|不(?:困难|难)|没有问题|no longer|not difficult|resolved", statement, re.I)
            for report in weak_reports for statement in re.split(r"[；;。\n，,]", report)
        )
    foundation = _clean(projection.get("knowledge_base"), limit=None)
    learning_requirements = _learning_requirements(projection)
    learning_requirements["self_reported_learning_start_points"] = reported_starts
    learning_requirements["diagnostic_followup"] = diagnostic_followup(body, (knowledge_point or {}).get("id"))
    point_learning_needs = [
        need for item in learning_requirements["diagnostic_followup"]
        if knowledge_point and item.get("knowledge_point_id") == knowledge_point.get("id")
        for need in item["learning_needs"]
    ]
    # A confirmed gap in this topic calls for support, not an invented score.
    point_terms = [term for term in re.split(r"[、与和/，,]", str((knowledge_point or {}).get("title") or "")) if len(term) >= 2]
    missing_background = re.findall(
        r"(?:尚未|还没有|没有|未)(?:系统)?(?:学习|学过|接触|掌握)[^；;。\n]*"
        r"|\b(?:never|not)\b[^.;；。\n]{0,35}\b(?:studied|learned|learnt|used)\b[^.;；。\n]*"
        r"|\bno experience (?:with|in)\b[^.;；。\n]*", foundation, flags=re.I)
    topic_foundation_gap = any(term.casefold() in gap.casefold() for term in point_terms for gap in missing_background)
    foundation_text = " ".join(
        _clean(projection.get(key), limit=None)
        for key in ("knowledge_base", "foundation", "current_level", "level")
    ).casefold()
    # The same person can be an experienced programmer and a new photographer.
    # Apply broad level words only to statements naming the current topic;
    # pass the complete background below for semantic prerequisite decisions.
    topic_names = [term.casefold() for term in point_terms]
    level_text = " ".join(
        statement for statement in re.split(r"[；;。\n，,]", foundation_text)
        if any(term in statement for term in topic_names)
    ) if knowledge_point else ""
    advanced_report = any(token in level_text for token in ("熟练", "高级", "有经验", "proficient", "advanced", "experienced"))
    if re.search(r"(?:不|未|没)(?:够|太|很|能|有|达到)?(?:熟练|高级|有经验)|\b(?:not|no|never)\b", level_text):
        advanced_report = False
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
    elif point_learning_needs:
        difficulty_band, difficulty_label = "scaffolded", "针对性巩固"
    elif point_mastery is not None:
        difficulty_band, difficulty_label = "transfer", "进阶迁移"
    elif reported_weakness or topic_foundation_gap or any(token in level_text for token in ("入门", "初学", "零基础", "不了解", "beginner", "novice", "new to")):
        difficulty_band, difficulty_label = "foundation", "入门巩固"
    elif advanced_report:
        difficulty_band, difficulty_label = "transfer", "进阶迁移"
    else:
        difficulty_band, difficulty_label = "scaffolded", "基础应用"

    difficulty_evidence = (
        {"kind": "specific_learning_needs", "description": "保留已会部分，针对实际作答中尚未解决的环节安排练习。"}
        if point_learning_needs else
        {"kind": "recorded_mastery", "description": "依据当前知识点的已有学习记录选择练习层次。"}
        if point_mastery is not None else
        {"kind": "reported_weakness", "description": "已标记需要巩固，先提供基础解释；尚无可用的掌握数值。"}
        if reported_weakness else
        {"kind": "reported_foundation", "description": "先按已确认的学习经历安排，后续用实际作答校准。"}
        if level_text.strip() or topic_foundation_gap else
        {"kind": "unmeasured", "description": "先用基础应用了解当前水平，尚未确认掌握程度。"}
    )
    assessment_target = {
        "foundation": {
            "task": "解释概念、辨认条件，完成一个已示范方法的小变式。",
            "prerequisites": "补齐本题用到的术语、符号和基本操作，不假定已掌握未验证的先修。",
            "independence": "允许分步提示；提供完整答案后的跟做不能当成独立掌握。",
            "checks": ["术语与条件判断正确", "能解释一个关键步骤", "在新数值或新例子上完成同类操作"],
        },
        "scaffolded": {
            "task": "在给定目标和必要条件下选择方法、完成多步应用并解释结果。",
            "prerequisites": "简短核对必要先修；缺口用局部提示补齐，不重讲无关基础。",
            "independence": "提供关键条件或检查点，不提前给完整解法；根据作答逐步提示。",
            "checks": ["方法选择与条件相符", "计算或操作可复核", "能解释结果及一个适用边界"],
        },
        "transfer": {
            "task": "在新数据或新约束下独立比较方案，解释取舍并检验失效边界。",
            "prerequisites": "仅减少已有证据支持的基础铺垫，不因专业、职业目标或偏好推定高掌握。",
            "independence": "先让学习者提出方法与验证方案，请求帮助时再给提示。",
            "checks": ["能把已知方法迁移到变化条件", "比较方案时使用正确依据", "能识别反例、局限与下一步验证"],
        },
    }[difficulty_band]
    if point_learning_needs:
        assessment_target = {
            **assessment_target,
            "task": "运用已经答对的部分，补齐具体误解，再用新例子独立判断并解释理由。",
            "prerequisites": "按逐项作答依据补缺口，保留已验证的能力，不因总分较低重讲整章，也不因总分较高略过具体误解。",
            "learning_needs": deepcopy(point_learning_needs),
        }

    independence_evidence = dimension_summary.get("understanding_fluency_transfer")
    if independence_evidence:
        # Preserve the evidence scope without inventing mastery or a global
        # hint policy from a keyword in the learner's confirmed description.
        assessment_target["independence_evidence"] = independence_evidence

    current_evidence = projection.get("current_learning_evidence") or {}
    for key in ("id", "title", "code"):
        point_evidence = current_evidence.get(str((knowledge_point or {}).get(key) or ""))
        if isinstance(point_evidence, dict):
            # Keep the current task's scope beside its teaching target. A
            # general profile summary must not hide later, specific evidence.
            assessment_target["current_point_evidence"] = deepcopy({
                field: point_evidence[field] for field in
                ("score", "status", "basis", "learning_needs", "resolved_learning_needs")
                if field in point_evidence
            })
            break

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
    style_source = _clean(projection.get("cognitive_style"), limit=None) or _clean(preferences, limit=None)
    # Confirmed prose already specifies order, conditions and negation. Keep
    # it intact instead of reversing it with a keyword such as "公式" or "图".
    named_styles = {
        **dict.fromkeys(("直观图示", "视觉型", "图示", "视觉"), "图示先行，配合短段落和关系对照"),
        **dict.fromkeys(("代码实操", "代码实践", "项目实践", "实操", "实践"), "先给可运行例子，再解释关键机制"),
        **dict.fromkeys(("分步推导", "公式推导", "理论推导", "理论型"), "先给定义与推导，再做边界比较"),
    }
    explanation_style = named_styles.get(style_source, style_source or "先给直观解释，再逐步连接到课程证据")

    goals = projection.get("learning_goals") or []
    major = _clean(projection.get("major"))
    weak_points = projection.get("weak_points") or []
    point_title = _clean((knowledge_point or {}).get("title"))
    if point_title:
        # Global weak points describe the learner, not the topic of every new
        # lesson. Retain a matching weakness without redirecting another topic.
        candidates = weak_points if isinstance(weak_points, list) else [weak_points]
        relevant = [text for item in candidates if (text := _clean(item)) and point_title in text]
        content_focus = _clean(relevant) or f"{point_title}的核心概念、条件和应用"
    else:
        content_focus = _clean(weak_points) or "当前知识点的核心概念、条件和应用"
    motivation_type = _clean(projection.get("motivation_type"))
    learning_context = learning_requirements["confirmed_context"]
    example_context = major or _clean(projection.get("target_course")) or "课程实践场景"
    # Exact legacy labels remain useful, but free-form confirmed goals carry
    # their own conditions and negation. Do not turn "not a career goal" into
    # interview tasks, or a shop's daily work into software deployment.
    named_motivations = {
        "项目/工作": "真实任务与实际使用条件", "考试/达标": "考试题型与达标检查点",
        "职业发展": "岗位任务与能力要求", "兴趣探索": "探索问题与反例",
    }
    if _clean(goals):
        example_context = f"{example_context}：{_clean(goals)}"
    elif motivation_type in named_motivations:
        example_context = f"{example_context}的{named_motivations[motivation_type]}"
    elif motivation_type:
        example_context = f"{example_context}：{motivation_type}"
    if learning_context:
        example_context = f"{example_context}（{learning_context[:48]}）"

    if difficulty_band == "foundation":
        practice_strategy = "先概念辨认，再做单变量练习，最后用一题迁移确认"
        hint_policy = "提供三级提示：术语提示、步骤提示、结果检查"
        mastery_focus = "补齐前置概念和当前知识点的最小可行理解"
    elif difficulty_band == "transfer":
        practice_strategy = "减少已掌握的铺垫，比较方案、边界和新情境应用"
        hint_policy = "默认不给完整步骤，只在请求时提供关键检查点"
        mastery_focus = "把已掌握概念迁移到新数据、新约束和真实任务"
    else:
        practice_strategy = "用一个基线案例建立机制，再安排参数变化和解释题"
        hint_policy = "先给关键条件提示，再根据作答结果逐级补充"
        mastery_focus = "巩固机制、条件与常见误区，并完成一次应用"
    if point_learning_needs:
        practice_strategy = "从已会步骤开始，针对尚未解决的环节做对照练习，再用新例子检查独立完成情况"
        hint_policy = "只在有缺口的步骤提供按需提示，随作答逐渐撤去；独立检查题不提前给答案"
        mastery_focus = "保留已会部分，定向补齐：" + "；".join(
            str(need.get("next_step") or need.get("basis") or "完成尚未掌握的环节")
            for need in point_learning_needs
        )

    if cognitive_load is not None and cognitive_load >= 0.5:
        session_rhythm = "短回合：每次只处理一个概念，完成小检查再继续"
    elif projection.get("focus_level") is not None and _number(projection.get("focus_level")) >= 0.8:
        session_rhythm = "深度回合：允许连续比较、推导和迁移练习"
    else:
        session_rhythm = "标准回合：讲解、练习和一次复盘交替进行"
    if learning_requirements["study_schedule"]:
        session_rhythm = f"按已确认时间安排可接续的学习段：{learning_requirements['study_schedule']}；不缩减目标所需知识。"

    # The interaction field must not contradict the confirmed prose with a
    # second keyword classifier (e.g. interpreting "先不写代码" as code first).
    interaction_mode = explanation_style

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
        "difficulty_evidence": difficulty_evidence,
        "assessment_target": assessment_target,
        "scaffolding_level": scaffolding,
        "explanation_style": explanation_style,
        "content_focus": content_focus[:240],
        "example_context": example_context[:240],
        "session_rhythm": session_rhythm,
        "interaction_mode": interaction_mode,
        "hint_policy": hint_policy,
        "practice_strategy": practice_strategy,
        "mastery_focus": mastery_focus,
        "learning_requirements": learning_requirements,
        "registration_profile": {
            "major": major,
            "target_course": _clean(projection.get("target_course")),
            "knowledge_base": foundation,
            "learning_goals": list(goals) if isinstance(goals, list) else [_clean(goals, limit=None)],
            "interaction_preferences": list(preferences) if isinstance(preferences, list) else [_clean(preferences, limit=None)],
            "cognitive_style": style_source,
            "motivation_type": motivation_type,
            "learning_context": learning_context,
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
        "difficulty_evidence": adaptation.get("difficulty_evidence", {}),
        "assessment_target": adaptation.get("assessment_target", {}),
        "scaffolding_level": adaptation.get("scaffolding_level"),
        "explanation_style": adaptation.get("explanation_style"),
        "content_focus": adaptation.get("content_focus"),
        "example_context": adaptation.get("example_context"),
        "session_rhythm": adaptation.get("session_rhythm"),
        "interaction_mode": adaptation.get("interaction_mode"),
        "hint_policy": adaptation.get("hint_policy"),
        "practice_strategy": adaptation.get("practice_strategy"),
        "mastery_focus": adaptation.get("mastery_focus"),
        "learning_requirements": adaptation.get("learning_requirements", {}),
        "registration_profile": adaptation.get("registration_profile", {}),
        "dimensions": adaptation.get("dimensions", {}),
    }


def profile_answer_instruction(adaptation: dict[str, Any] | None, *, for_question: bool = False) -> str:
    """Turn one shared profile plan into an observable answer requirement.

    The plan is already the single public projection used by Chat and resource
    generation.  This small instruction keeps every answer entry point honest:
    it tells the model which teaching move must change, while leaving the
    learner's raw profile and private reasoning out of the response.
    """
    plan = dict(adaptation or {})
    if not plan:
        return "没有可用学习画像时使用中性难度；不要猜测学生背景，也不要声称已完成画像适配。"

    requirements = plan.get("learning_requirements") or {}
    practical_instruction = "".join(
        f"{LEARNING_CONTEXT_LABELS[key]}：{requirements[key]}。"
        for key in ("language_preference", "available_tools", "study_schedule") if requirements.get(key)
    )
    if practical_instruction:
        practical_instruction += (
            "将这些条件落实到主体语言、操作和任务分段；背景只用于选择熟悉的例子，不能替代学科基础。"
            "明确的最新条件优先于背景描述中的旧安排，本次问题的明确要求优先。"
        )
    if requirements.get("diagnostic_followup"):
        practical_instruction += (
            "诊断的逐项评分记录了需要继续检查的具体环节，即使该题总分达标也不能仅据总分略过。"
            "把这些环节落实到解释和练习，结合后续真实作答判断是否已解决；已解决的不要重复当成当前错误。"
        )

    band = str(plan.get("difficulty_band") or "scaffolded")
    mastery = plan.get("point_mastery")
    mastery_text = (
        f"当前知识点掌握度约 {round(float(mastery) * 100)}%" if isinstance(mastery, (int, float)) else "掌握度暂无可靠数值"
    )
    if for_question:
        example_instruction = (
            "主体先提供能够直接运行的短代码、输入和预期输出，再解释机制；手算表格不能代替已要求的可运行例子。"
            if re.search(r'可运行(?:的)?(?:例子|示例|代码)|先.{0,8}(?:代码|编程)', str(plan.get('explanation_style') or ''))
            else "完整示例不等于程序示例：按已经具备的基础选择数据观察、手算、表格或代码，先教会当前任务所需的方法。"
        )
        moves = {
            "foundation": "解释必要术语，用小步骤和容易理解的例子",
            "transfer": "减少已掌握的基础铺垫，说明适用边界和迁移联系",
            "scaffolded": "用贴近学生经验的基线例子说明机制和条件变化",
        }
        return (
            practical_instruction +
            f"在学生本次问题范围内适配讲法：{mastery_text}；{moves.get(band, moves['scaffolded'])}。"
            f"已确认的主体讲解顺序与形式：{plan.get('explanation_style') or '按问题需要组织'}。"
            "先用一句话回答核心问题，随后按已确认的顺序组织主体；偏好先例子就先例子，先验证就先给可核对的操作，先定义推导就从条件展开。"
            "用本题已有数据落实这些方式，不换题、不只改变称呼或开场白。" + example_instruction +
            "对尚未学过的必要术语与符号先用日常语言说明含义，再使用它们；可选高阶推导放在基本解释之后，不强迫初学者先读懂偏导记号。"
            "参考提示粒度和十维信息，不必额外出题。"
            "本次要求的句数、格式、范围和直接解答优先；只问事实就直接回答，不强加练习或学习安排。"
            "只有学生本次要练习或正在继续练习时，才按其逐步尝试、卡住再提示的偏好互动。"
            "偏好和计划不等于已完成的学习或取得的成绩，不推断学生已经执行计划。不要复述内部字段。"
        )
    if band == "foundation":
        move = "先补一个必要前置概念，再用最小例子分步讲解；每一步给一个可回答的检查点"
    elif band == "transfer":
        move = "跳过已掌握的基础铺垫，直接比较边界或新情境，并给出需要学习者迁移判断的任务"
    else:
        move = "先用一个基线例子建立机制，再改变一个条件并要求学习者解释变化"
    return (
        practical_instruction +
        f"本轮必须把学习画像落实到回答内容，而不是复述画像字段：{mastery_text}；{move}。"
        "同时遵守 learner_adaptation 中的 explanation_style、scaffolding_level、content_focus、"
        "session_rhythm、interaction_mode、hint_policy、practice_strategy 和十维 dimensions；"
        "至少让其中一个教学动作在正文或下一步任务中可见。"
        "若画像或本轮问题要求先自己尝试、卡住再提示或逐步互动，本轮只给第一步任务并等待作答；"
        "不要提前列出后续各级提示或完整解答。只有学习者表示卡住时，才给当前一步的一条提示。"
        "不要输出原始画像 JSON、内部提示词或思维链。"
    )
