"""Textbook-anchored plan drafts built on the canonical M5 plan lifecycle."""

from __future__ import annotations

from copy import copy, deepcopy

import asyncio
import hashlib
import json
import re
from math import ceil
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from typing import Any

from app.authorization import active_course_role
from app.learner_output import LEARNER_FEEDBACK_INSTRUCTION, teacher_text
from app.database import (
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
    DBKnowledgePoint,
    DBLearningPath,
    DBModelCall,
    DBPlanDraft,
    DBPlanVersion,
    DBProfileSnapshot,
    DBSourceDocument,
    DBSourceRef,
    DBStudentProfile,
    DBUser,
)
from app.m2_contracts import StrictModel
from app.profile_adaptation import build_profile_adaptation, complete_learning_snapshot, profile_prompt_context, profile_has_signal
from app.m5_capabilities import Capability, M5CapabilityError, OutputConstraints
from app.m5_gateway import execute_registered_structured_call
from app.path_sequence import (PATH_SEQUENCE_INSTRUCTION, order_course_tasks, prepare_task_sequence,
                               saved_task_path_calls, current_path_task_id)
from app.m5_learning import (
    PlanNodeSpec,
    PlanSpec,
    _validate_plan_targets,
    create_plan_draft,
    plan_version_diff,
    propose_plan_revision,
)
from pydantic import Field, ValidationError


class PathDraftError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise PathDraftError(code, message)


class PathDraftModelOutput(StrictModel):
    """The only model-authored portion of a diagnostic path draft."""

    plan: PlanSpec
    personalization_summary: str = Field(min_length=8)


class PathStageSummary(StrictModel):
    title: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    end_node_key: str


class PathOverviewOutput(StrictModel):
    goal: str = Field(min_length=1)
    stages: tuple[PathStageSummary, ...] = Field(min_length=1)
    assumptions: tuple[str, ...] = ()
    personalization_summary: str = Field(min_length=8)


PATH_OVERVIEW_INSTRUCTION = (
    "你是课程学习顾问。依据完整路线，写给学习者一份清楚的全程安排，只输出Schema要求的JSON。"
    "本次不修改或扩写学习节点；先检查全部节点，再归纳目标、阶段成果和必要条件。"
    "具体目标、语言、基础、工具和时间以context中的已确认信息为准；职业不代表能力。"
    "goal说明学习者要做成什么，不能照搬首批目标或把完整课程周期套进个人目标期限。"
    "stages按实际学习顺序组织，通常用少量有实质成果的阶段，不按每批或每章机械分段。"
    "阶段按学习者逐步做成的成果划分，以约五至七个阶段作为阅读组织参考；确有独立成果可增加，不设置数量截断。"
    "把服务同一成果的相邻任务合起来，不把全课的学科目录改写一遍。"
    "第一个阶段应到最早能满足学习者核心目标的实际成果为止，基础准备属于达到该成果的方法，不为每项基础另立阶段。"
    "outcome通常一两句：核心产出、独立完成的方式和检查标准；不堆算法名、公式清单与操作细目，这些已保留在步骤中。"
    "每个阶段结束于已有end_node_key，必须逐段覆盖到最后一个节点。outcome写能做成和检查什么，"
    "依据该阶段真实teaching_goal；已有模型输出分析不能写成独立训练，模板演示不能写成自主大模型协作。"
    "保留评价对象和证据种类：合成画像测试仍称合成画像测试，不能省略合成条件后写成用户试用或真人学习效果。"
    "首个阶段突出最早的可用成果，后续阶段说明如何深化，不把所有成果推到学完整课之后。"
    "若现有步骤只能提供准备工作，明确其实际产出和后续承接，不在总结中凭空补出未安排的实验或成果。"
    "时间以timing的完整任务估时和已确认时段为准，不能只看批次说明。minimum_sessions是工作量和实际排程规则得到的下界，"
    "不是日历排程结果；不能把分钟相除所得下界写成保证完成周期。未确认每周安排时不猜测周数。"
    "若全部内容超过目标期限，清楚区分近期可用成果与完整深化所需投入，不降低估时或假称期限内完成。"
    "利用progress_to_step核对近期成果所在位置与累计投入，区分近期核心成果与后续深化。"
    "自然语言不要计算或重复预计分钟、小时、次数、周数，也不输出数值完成期限；"
    "页面会依据实际节点统一显示精确工作量和日程。不能把估时数字的改写交给文字推算。"
    "单人任务优先自行核对，不额外要求同伴才能完成。"
    "用直接的学习安排表达，例如近期完成哪些成果、随后投入多少时间深化；避免反复用不承诺、不保证组织正文。"
    "assumptions只保留影响实际操作的必要条件；各阶段成果已在stages表达，不重复。"
    "batch_notes只供核对，重复、矛盾或失效的分批许诺不能照搬。personalization_summary解释有依据的安排，"
    "讲清怎样用已有优势、补具体缺口并逐渐独立，不重复职业身份或泛泛表扬。"
    + LEARNER_FEEDBACK_INSTRUCTION
)


def _path_timing(nodes, *, snapshot, time_budget_minutes):
    """Workload and prerequisite lower bounds, not a promised calendar."""
    from app.profile_adaptation import confirmed_study_days, confirmed_study_minutes, confirmed_study_minutes_by_weekday
    depth = {}
    for node in nodes:
        depth[node.node_key] = 1 + max((depth[key] for key in node.prerequisites), default=0)
    minimum = sum(node.estimate_min_minutes for node in nodes)
    maximum = sum(node.estimate_max_minutes for node in nodes)
    days = confirmed_study_days(snapshot)
    weekly = confirmed_study_minutes_by_weekday(snapshot)
    capacity = sum(weekly.values()) if weekly else (len(days) * time_budget_minutes if days else None)
    sessions = ceil(minimum / max(weekly.values(), default=time_budget_minutes))
    if confirmed_study_minutes(snapshot) is None:
        sessions = max(max(depth.values(), default=0), sessions)
    return {
        "node_count": len(nodes), "total_min_minutes": minimum, "total_max_minutes": maximum,
        "session_budget_minutes": time_budget_minutes, "minimum_sessions": sessions,
        "confirmed_study_weekdays": list(days),
        "study_minutes_by_weekday": weekly,
        "weekly_capacity_minutes": capacity,
        "minimum_weeks": max(ceil(sessions / len(days)), ceil(minimum / capacity)) if days and capacity else None,
    }


async def _summarize_full_path(session, *, llm, user, course, context, nodes, batch_notes):
    """Summarize preserved teaching steps once; a retry reuses this exact result."""
    from llm_client import for_answer_step
    llm = for_answer_step(llm, deep_reasoning=True, reasoning_effort="high")
    context = {key: value for key, value in context.items() if key != "course_graph"}
    request = {
        "task": "full_learning_path_overview", "context": context,
        "timing": _path_timing(nodes, snapshot=context, time_budget_minutes=context["time_budget_minutes"]),
        "learning_steps": [node.model_dump(mode="json") for node in nodes],
        "batch_notes": batch_notes, "output_schema": PathOverviewOutput.model_json_schema(),
    }
    minimum = maximum = 0
    progress = []
    for index, node in enumerate(nodes, 1):
        minimum += node.estimate_min_minutes
        maximum += node.estimate_max_minutes
        progress.append({"node_key": node.node_key, "step_number": index,
                         "cumulative_min_minutes": minimum, "cumulative_max_minutes": maximum})
    request["progress_to_step"] = progress
    input_hash = hashlib.sha256(json.dumps({
        "instruction": PATH_OVERVIEW_INSTRUCTION, "input": request,
        "model": llm.model, "thinking": llm.thinking_mode, "reasoning": llm.reasoning_effort,
    }, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    positions = {node.node_key: index for index, node in enumerate(nodes)}

    def validate(value):
        output = PathOverviewOutput.model_validate(value)
        ends = [positions.get(stage.end_node_key, -1) for stage in output.stages]
        if ends[0] < 0 or any(right <= left for left, right in zip(ends, ends[1:])) or ends[-1] != len(nodes) - 1:
            raise ValueError("各阶段须依次结束于已有学习步骤，并覆盖至完整路线的最后一步。")
        return output

    for call in session.query(DBModelCall).filter_by(owner_public_id=user.public_id,
            course_id=course.id, capability=Capability.PLAN.value, status="completed").order_by(DBModelCall.created_at.desc()).all():
        saved = (call.input_summary or {}).get("path_overview_result") or {}
        if saved.get("input_hash") == input_hash and saved.get("output"):
            return validate(saved["output"]), call.id
    feedback = ""
    for attempt in range(2):
        try:
            result = await execute_registered_structured_call(
                session, backend=llm, capability=Capability.PLAN,
                system_prompt=PATH_OVERVIEW_INSTRUCTION,
                user_prompt=json.dumps({**request, **({"validation_feedback": feedback} if feedback else {})},
                                       ensure_ascii=False, sort_keys=True),
                role="全程学习安排", operation="p1_b11_learning_path_overview",
                response_model=PathOverviewOutput, response_validator=validate,
                owner_public_id=user.public_id, course_id=course.id,
                output_constraints=OutputConstraints(language="auto", format="json"),
            )
            output = validate(result.structured_output or {})
            call = session.get(DBModelCall, result.call_id)
            if call is None:
                _fail("path_draft_model_audit_missing", "全程安排尚未保存，请重试。")
            call.input_summary = {**(call.input_summary or {}), "path_overview_result": {
                "input_hash": input_hash, "output": output.model_dump(mode="json"), "timing": request["timing"]}}
            session.commit()
            return output, result.call_id
        except M5CapabilityError as exc:
            feedback = str(exc.__cause__ or exc)
            if exc.code == "structured_output_invalid" and attempt == 0:
                continue
            raise PathDraftError("path_overview_failed", "学习步骤已保存，全程安排尚未整理完成。重试会继续使用已有步骤。") from exc


PATH_PLANNING_REVISION = "391-r144-goal-and-concept-sequence"


def _path_output_budget(backend):
    """Use the path allowance even when entering from a diagnostic report.

    Diagnostic generation supplies its own shared backend. Copy it before
    raising this request's output allowance, keeping its pool and model policy.
    """
    if hasattr(backend, 'max_tokens') and backend.max_tokens < 32768:
        backend = copy(backend)
        backend.max_tokens = 32768
    return backend


class PathTeachingFinding(StrictModel):
    node_key: str = ""
    problem: str = Field(min_length=1)
    correction: str = Field(min_length=1)
    source_ref_id: str = ""
    evidence_quote: str = ""


class PathTeachingNodeUpdate(StrictModel):
    node_key: str = Field(min_length=1)
    title: str | None = None
    teaching_goal: str | None = None
    rationale: str | None = None
    estimate_min_minutes: int | None = None
    estimate_max_minutes: int | None = None


class PathTeachingReview(StrictModel):
    findings: tuple[PathTeachingFinding, ...]
    node_updates: tuple[PathTeachingNodeUpdate, ...] = ()
    revised_path: PathDraftModelOutput | None = None


def _apply_path_review(review, candidate, validate_batch):
    """Keep untouched teaching tasks verbatim; structural edits still use the full plan."""
    if review.node_updates and review.revised_path is not None:
        raise ValueError("节点修改与完整结构修订只能选择一种，避免互相覆盖。")
    if review.findings and not review.node_updates and review.revised_path is None:
        raise ValueError("发现的问题必须落实到node_updates或revised_path，不能只给意见。")
    if not review.node_updates:
        return review.revised_path or candidate
    value = candidate.model_dump(mode="json")
    nodes = {node['node_key']: node for node in value['plan']['nodes']}
    findings = {finding.node_key for finding in review.findings}
    seen = set()
    for update in review.node_updates:
        if update.node_key not in nodes or update.node_key in seen:
            raise ValueError("节点修改必须唯一对应当前候选中的node_key。")
        if update.node_key not in findings:
            raise ValueError("节点修改需要对应的具体审核意见，不能改写未发现问题的任务。")
        changes = {key: val for key, val in update.model_dump().items()
                   if key != 'node_key' and val is not None}
        if not changes or any(isinstance(val, str) and not val.strip() for val in changes.values()):
            raise ValueError("节点修改须提供有效内容，不能清空学习目标或标题。")
        if all(nodes[update.node_key].get(key) == val for key, val in changes.items()):
            raise ValueError("节点修改与原稿相同，请落实具体修订或移除无须修改的意见。")
        nodes[update.node_key].update(changes)
        seen.add(update.node_key)
    if findings - seen:
        raise ValueError("每项审核意见都需落实到对应节点；跨节点结构问题请使用完整revised_path。")
    return validate_batch(value)


PATH_REVIEW_INSTRUCTION = (
    "你是课程教学编辑。依据原文和学习者条件审阅学习路线，不评价文字是否华丽。只输出符合Schema的JSON对象。"
    "检查定义方向、概率/比例的分母、单位与时间范围、公式成立条件、先修和实际操作，"
    "逐项核对所有列举的边界值：若边界另有返回值或定义，不能仍宣称它满足一般公式、期望或等价关系。修订后的句子也要重新核对适用域。"
    "保持术语的明确方向，例如事件发生与不发生的概率不能用含混简称替换；"
    "同一符号跨章沿用时，核对本批与earlier_learning_steps中的定义、量纲和分母。"
    "跨分片合并损失或梯度时，明确输入是各分片总和还是均值：总和相加后除总样本数；"
    "只有分片均值才按各自样本数加权。掩码后的零项是否仍进入平均分母也须与实际实现一致。"
    "引用结论时保留邻近原文的输入形状、统计轴和适用对象；每组参与统计的元素个数不一定等于批量大小，"
    "不能将全连接、卷积或不同归约轴的特殊结论相互套用。手算定义与实际框架的有效输入要求须分别核对。"
    "模型退化为另一模型、门控保留或忽略历史等结论，核对全部共同成立的条件；"
    "只改变一个门或参数时，不能假定其他门、参数或路径也自动取到相应边界。"
    "原文若以同一符号表示比例和绝对量，要明确换算关系并在本课选择统一记号；"
    "不能一处含某乘数另一处去掉乘数，却只说各自单位正确而不解释二者如何等价。"
    "表格标题或缩写不能替代准确含义，尤其明确概率指哪个事件，不能把互补事件混称。"
    "相对某参照的比值相等不表示绝对量相等；偏好判定概率与策略生成概率等不同对象须分别计算，不能相互代替。"
    "参数范围按定义和条件判断，不能默认所有分位、偏差和标准化量均非负。"
    "避免把经验规律强制当作每个小样本应有的结果；资料有矛盾时说明具体冲突并安排核对，不照抄错误结论。"
    "核对每步是否具有可获得的输入、实际动作、可检查产出；不要把查看目录当学习，也不要提前填写习题答案。"
    "多步搜索与迭代比较须提供各步所需的状态、可展开分支或条件分布；只有首步表或最终分数不能冒充完整可执行输入。"
    "一个知识点可跨多个教学单元；每个单元按本段原文和自身任务推进，不重复要求完成该知识点的全部内容。"
    "本段未展开而course_learning_outline已有后续专门单元的内容，承接该单元；"
    "不要凭知识点总标题添加缺乏本段依据的猜想任务，再用通用拓展或待核对标签替代课程已有的正式教学。"
    "对学习者目标检查完整执行路线：期限内的第一个可用成果必须落在具体节点，不能仅在assumptions许诺。"
    "earlier_learning_steps是之前安排的步骤而非已完成记录；后续章节是继续完善，不应将初版成果无限推迟。"
    "首个可用成果要回答学习者实际想解决的问题，不能每批只交出准备材料并把目标继续推后；"
    "可先用已给的模型输出或小表完成有依据的比较初版，再学习其训练原理与实现，明确初版做了什么、尚未做什么，不冒充完成训练。"
    "prerequisites由系统依据required_learning_tasks和分段顺序连接，输出空数组是正确约定，不能把空数组当教学缺陷；"
    "应检查教学内容有无实际先修缺口，系统内部边不要重写。"
    "已确认时段内可顺序完成多个短任务，先修完成后才进入下一段；不能仅用总分钟除单次时间来许诺周数。"
    "若时间紧，合并同一required_learning_task内重复的准备/检查，保留真实必要任务和合理时长；"
    "可用简单初版先实现目标，再按完整知识范围深化。不能靠删知识点、虚构基础或降低时间估计过关。"
    "按已确认的语言、设备与基础表达，检查工具是否真能做、任务是否需要额外人手或资料。"
    "按context.runtime核对课程内实际可运行条件：允许的模块不等于已提供教材数据；不可下载的数据、未安装框架和长训练不能列为现有必做操作。"
    "应改成保留同一专业目标的小规模真实实验，明确给出数据来源或标明合成数据；日志阅读不能冒充实际训练，初学者不能跳过首次代码运行准备。"
    "原教学单元明确要求实现、训练或工具执行时，整单元不能只剩算参数、看给定输出和写流程图；在实际环境中完成相应小规模操作并检查结果。"
    "各次代码运行不共享内存或文件时，后段承接可重现的前段代码、数据和种子，在同次运行保存比较状态，不假定已有持久检查点。"
    "沿前后步骤核对数据隔离：先固定训练/验证/测试划分，再拟合预处理或更新模型；"
    "若前一示范已在全表上更新参数，正式比较须在划分后从未接触留出数据的初始模型重新训练，不能沿用示范参数。"
    "核对从示例到独做的实际跨度：尚未练过循环、函数或索引的学习者不能突然被要求从空白编写数据迭代器或训练循环；"
    "先在可运行骨架上补一处、改输入并核对，再逐步撤去骨架，保留最终独立实现与解释要求。"
    "核对实现步骤中的对象生命周期：参数层须先创建并注册，再在前向计算中使用，不能每次前向计算重新创建待训练参数；"
    "可复现比较保持初始化策略、随机种子等条件一致，不强求不同形状的网络使用同一组权重。"
    "从曲线或单次结果推断原因时区分迹象与确诊，安排控制变量实验排查，不能把下降慢、震荡或验证停滞直接当作唯一原因的证明。"
    "结果分析不能以人为调数据直到出现预期现象为完成条件；没有错例或趋势不明显时记录真实结果，"
    "用另行标注的教学反例练习分析，不改测试样本凑结论，也不把合成数据生成机制当作某个预测错误的已证实原因。"
    "对已给预测表也落实测试隔离：选型步骤只提供训练/验证列，保存选择和理由后再提供所选模型的测试结果。"
    "先展示各候选的测试分数再要求不看、只记录不用，仍须改成分步揭示。"
    "训练与验证都差可能涉及优化未完成或数据问题；过拟合/欠拟合判断要说明比较口径、基线及训练条件，"
    "不是把两列大小机械对应成唯一病因；对缺少条件的结果写出待检验解释和下一步检查。"
    "事实诊断与教学自查分开：没有分母或符号换算的原答证据时，不得说学习者已犯这些错误；可以安排预防性核对。"
    "根据原题原答区分已会的步骤和未解决的子问题：主体练习放在具体缺口，已正确的部分直接用于新任务或简短核对。"
    "不能因同一知识点有一项失分就从头重教全部定义，也不能为了缩短安排而降低该课程的最终独立要求。"
    "resource_status=existing表示已有课程来源，不表示教学示例已全部生成。合理的本地可验证示例属于资源任务，"
    "不能只因教材没有逐字写到就取消本知识范围的有用对照，也不能把新例子冒称原文事实。"
    "节点顺序以required_learning_tasks为准，段内再递进；说明中用实际学习标题承接，避免写随后可能变化的绝对段号。"
    "只记录有实际影响的问题，不为了显得审查严格而强行改写正确内容；rationale简短，assumptions不重复列身份和免责声明。"
    "核对修订本身：用最小数值例、完整步骤或实际实现检查改动是否仍保留正确特例和所有必要分支；"
    "一般加权公式不能被写成禁止其等权特例。比较实验只固定未被比较的因素，不能同时固定本来要改变的条件。"
    "来源同时有解释文字和可运行代码时，先明确本任务采用哪个版本与规则，再对照二者；"
    "文字简述不能替代代码的实际处理顺序，不能把另一种常见算法的规则混入本课实现。"
    "若有问题，在findings中列出具体问题、核验依据与解决办法；"
    "通常用node_updates仅返回有问题节点需改的字段，未改字段省略或null，revised_path为null。"
    "每个node_update须对应同node_key的finding，所有意见都要落实，正确节点不重写。"
    "只有需要拆分、合并、重排节点或修改全局条件时，才返回完整revised_path并令node_updates为空。"
    "涉及事实时给出当前reading中的source_ref_id和单段连续原文短引，不用省略号拼接片段，若原文无依据不可捏造引文。"
    "引文必须逐字来自该reading，保持原公式和符号；不能把candidate中的任务说明充作教材原句。"
    "学习节奏、数据可用性等依据来自学习条件或候选任务时，直接说明依据，source_ref_id和evidence_quote均留空。"
    "无须修改则findings和node_updates为空、revised_path为null。保留任务对应、知识范围和先修约定，必要时按原node_key分段规则合并或拆分。"
    "新稿仍只设计学习任务，不能扩写成长篇教材或完整解答。"
)


def _restore_path_quote_typography(value, payload):
    """Restore an exact source span when only whitespace/full-stop glyphs differ.

    Digits, decimal points, signs, wording and conditions stay exact. Matching
    never joins passages; the saved quote contains the original source text.
    """
    if not isinstance(value, dict) or not isinstance(value.get('findings'), (list, tuple)):
        return value
    readings = {item['reading']['source_ref_id']: item['reading'].get('text', '')
                for item in payload.get('context', {}).get('course_graph', {}).get('chapters', [])
                if item.get('reading', {}).get('source_ref_id')}

    def compact(text):
        positions = [i for i, char in enumerate(text) if not char.isspace()]
        chars = [text[i] for i in positions]
        return ''.join('.' if char in '。．' and not (
            i > 0 and i + 1 < len(chars) and chars[i-1].isdigit() and chars[i+1].isdigit()
        ) else char for i, char in enumerate(chars)), positions

    restored = deepcopy(value)
    for finding in restored.get('findings', []):
        if not isinstance(finding, dict):
            continue
        source = readings.get(finding.get('source_ref_id'), '')
        quote = finding.get('evidence_quote') or ''
        if not isinstance(quote, str) or not quote or not source:
            continue
        needle, _ = compact(quote)
        haystack, positions = compact(source)
        index = haystack.find(needle) if needle else -1
        if index >= 0:
            finding['evidence_quote'] = source[positions[index]:positions[index + len(needle) - 1] + 1]
    return restored


def _validate_path_review_sources(review: PathTeachingReview, payload):
    readings = {
        item['reading']['source_ref_id']: item['reading'].get('text', '')
        for item in payload.get('context', {}).get('course_graph', {}).get('chapters', [])
        if item.get('reading', {}).get('source_ref_id')
    }
    for index, finding in enumerate(review.findings, 1):
        reference, quote = finding.source_ref_id.strip(), finding.evidence_quote.strip()
        if not reference and not quote:
            continue  # Practical constraints may be established by learner/runtime inputs.
        if not reference or reference not in readings:
            raise ValueError(f'第{index}条意见引用的来源不在本批reading中；请使用本批真实来源，或说明非原文依据并留空引文。')
        if not quote or re.sub(r'\s+', '', quote) not in re.sub(r'\s+', '', readings[reference]):
            # Give the editor the actual differing source line. Repeating only
            # "not verbatim" made otherwise useful repairs miss the same word.
            # Similarity locates evidence; it never makes an invalid quote pass.
            from difflib import get_close_matches
            source_lines = {re.sub(r'\s+', '', line): line
                            for line in readings[reference].splitlines() if line.strip()}
            suggestions = []
            for line in quote.splitlines():
                clean = re.sub(r'\s+', '', line)
                if not clean or clean in source_lines:
                    continue
                matches = get_close_matches(clean, source_lines, n=1, cutoff=0.85)
                if matches:
                    suggestions.append({'引用行': line, '原文相近行': source_lines[matches[0]]})
            hint = (' 原文定位：' + json.dumps(suggestions, ensure_ascii=False)
                    + '。这些行仅帮助定位；核对依据后复制连续原文，不拼接或改写引文。') if suggestions else (
                ' 本批原文中未定位到可支持该引文的连续段落，不要继续缩短或拼接同一段记忆中的引文。'
                '若依据是自行复算的数学定义、数值反例或当前候选任务，请在problem或correction中直接给出推导/反例，'
                'source_ref_id和evidence_quote均留空；不要把未提供的辅助函数实现冒称本批原文。'
            )
            raise ValueError(f'第{index}条意见的evidence_quote不是所指reading的连续原文。请复制真实原句，不能引用候选任务充作教材；非原文依据请留空两项来源字段。' + hint)


def _path_review_output_limit(exc):
    from llm_client import ModelOutputLimitError
    seen = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, ModelOutputLimitError):
            return True
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__
    return False


PATH_REVISION_CHECK_INSTRUCTION = (
    "你是独立的课程任务核验者。输入是待发布任务与资料，不提供前位编辑的判断或理由。"
    "从定义和题设自行检查任务中的具体结论、例子和操作是否成立；不能因为文字流畅就接受预设结论。"
    "尤其把例子实际代入规则：对象数量、集合与多重集合、统计频数、归一化、必要条件分别核对，"
    "不能用局部表示相同推断整体判定相同。需要反例时先独立算出例子，再决定是否修改。"
    "仅修正知识错误、任务无法执行或实际教学适配失效；正确内容保持原样，不增补可选润色。"
    "若需修改，在problem/correction记录可核对的公开依据或短计算，并落实到对应字段；"
    "无实质问题就返回空findings和node_updates、revised_path=null。"
)


async def _review_path_batch(session, *, llm, user, course, payload, candidate,
                             generator_call, validate_batch):
    """Independently check editorial changes before they feed the next batch."""
    args = dict(llm=llm, user=user, course=course, payload=payload,
                generator_call=generator_call, validate_batch=validate_batch)
    output, call_id = await _review_path_candidate(session, candidate=candidate, **args)
    if output == candidate:
        return output, call_id
    versions = [candidate.model_dump(mode="json")]
    check_ids = []
    while True:
        value = output.model_dump(mode="json")
        # A changing draft is retained on every round. On a repeated version,
        # explicitly resolve competing public task statements from the sources
        # instead of replaying the same editorial judgment indefinitely.
        conflicts = versions if value in versions else None
        versions.append(value)
        checked, check_id = await _review_path_candidate(
            session, candidate=output, verification_round=len(check_ids),
            conflicting_versions=conflicts, **args)
        check_ids.append(check_id)
        if checked == output:
            generator_call.input_summary = {**(generator_call.input_summary or {}),
                "path_teaching_verified_result": {
                    "editor_call_id": call_id, "verification_call_ids": check_ids,
                    "output": checked.model_dump(mode="json"),
                }}
            session.commit()
            return checked, check_id
        output = checked


async def _review_path_candidate(session, *, llm, user, course, payload, candidate,
                                 generator_call, validate_batch, verification_round=None,
                                 conflicting_versions=None):
    """Edit teaching errors before a batch feeds later planning; reuse saved work."""
    from llm_client import for_answer_step
    # This is an edit of an existing plan, not another open-ended planning task.
    # Keep deep reasoning but leave output room for the corrected public draft.
    llm = _path_output_budget(for_answer_step(llm, deep_reasoning=True,
        reasoning_effort="max" if conflicting_versions else "high"))
    independent = verification_round is not None
    instruction = PATH_REVIEW_INSTRUCTION + (PATH_REVISION_CHECK_INSTRUCTION if independent else "")
    operation = "p1_b11_learning_path_revision_check" if independent else "p1_b11_learning_path_teaching_review"
    role = "学习路径修订独立核验" if independent else "学习路径教学复核"
    cache_key = f"path_teaching_verification_{verification_round}" if independent else "path_teaching_review"
    review_input = {**payload, "candidate": candidate.model_dump(mode="json")}
    if conflicting_versions:
        review_input["conflicting_task_versions"] = conflicting_versions
        review_input["resolution_instruction"] = (
            "任务曾在这些公开表述间往返。依据原文、定义和可复算小例子重新判定，"
            "说明成立条件并落实到当前任务；不要靠投票或简单采用最近一个版本。")
    review_hash = hashlib.sha256(json.dumps({
        "revision": PATH_PLANNING_REVISION, "instruction": instruction,
        "schema": PathTeachingReview.model_json_schema(),
        "input": review_input, "model": llm.model,
        "thinking": llm.thinking_mode, "reasoning": llm.reasoning_effort,
        "max_tokens": getattr(llm, 'max_tokens', None),
    }, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    saved = (generator_call.input_summary or {}).get(cache_key) or {}
    if saved.get("input_hash") == review_hash and saved.get("output"):
        return validate_batch(saved["output"]), saved["call_id"]

    failed_review = (generator_call.input_summary or {}).get(cache_key + '_failure') or {}
    same_failed_input = failed_review.get('input_hash') == review_hash
    rejected_review = deepcopy(failed_review.get('previous_review')) if same_failed_input else None
    output_limit = bool(same_failed_input and failed_review.get('output_limit'))
    if same_failed_input and 'output_limit' not in failed_review:
        # Older saved failures contain the provider exception types on the
        # actual call. Restore that fact without treating every failure alike.
        previous_call = session.query(DBModelCall).filter_by(
            owner_public_id=user.public_id, course_id=course.id,
            prompt_version=operation + ':1.0', status='failed',
        ).filter(DBModelCall.created_at >= generator_call.created_at).order_by(DBModelCall.created_at.desc()).first()
        output_limit = bool(previous_call and 'ModelOutputLimitError' in (
            (previous_call.input_summary or {}).get('provider_failure') or {}).get('exception_types', []))

    def validate_review(value):
        nonlocal rejected_review
        value = _restore_path_quote_typography(value, payload)
        rejected_review = value
        if isinstance(value, dict) and isinstance(value.get("revised_path"), dict):
            value = {**value, "revised_path": validate_batch(value["revised_path"]).model_dump(mode="json")}
        review = PathTeachingReview.model_validate(value)
        if review.revised_path is not None:
            validate_batch(review.revised_path.model_dump(mode="json"))
        _validate_path_review_sources(review, payload)
        output = _apply_path_review(review, candidate, validate_batch)
        if review.findings and output == candidate:
            raise ValueError("具体问题仍未落实到修改，不能用不变的完整方案表示已解决。")
        rejected_review = None
        return review

    feedback = failed_review.get('feedback', '') if same_failed_input else ''
    if rejected_review:
        try:
            _validate_path_review_sources(PathTeachingReview.model_validate(rejected_review), payload)
        except ValueError as exc:
            feedback = str(exc)
    for attempt in range(2):
        call_backend = copy(llm) if output_limit else llm
        if output_limit:
            call_backend.max_tokens = max(getattr(llm, 'max_tokens', 32768) * 2, 65536)
        request = {**review_input, "output_schema": PathTeachingReview.model_json_schema()}
        if feedback:
            request["validation_feedback"] = feedback
            if rejected_review is not None:
                request["previous_review"] = rejected_review
                request["retry_instruction"] = "按校验意见纠正上一稿，保留已落实的正确教学修订，不重新丢弃它们。"
        try:
            result = await execute_registered_structured_call(
                session, backend=call_backend, capability=Capability.PLAN,
                system_prompt=instruction,
                user_prompt=json.dumps(request, ensure_ascii=False, sort_keys=True),
                role=role, operation=operation,
                response_model=PathTeachingReview, response_validator=validate_review,
                owner_public_id=user.public_id, course_id=course.id,
                output_constraints=OutputConstraints(language="auto", format="json"),
            )
            review = validate_review(result.structured_output or {})
            output = _apply_path_review(review, candidate, validate_batch)
            review_record = {
                "input_hash": review_hash, "call_id": result.call_id,
                "findings": [item.model_dump(mode="json") for item in review.findings],
                "node_updates": [item.model_dump(mode="json", exclude_none=True) for item in review.node_updates],
                "output": output.model_dump(mode="json"),
                "max_tokens": getattr(call_backend, 'max_tokens', None),
                "output_limit_recovery": output_limit,
                "independent_verification": independent,
            }
            review_call = session.get(DBModelCall, result.call_id)
            if review_call is not None:
                review_call.input_summary = {**(review_call.input_summary or {}),
                    "path_teaching_review_result": {**review_record, "candidate_call_id": generator_call.id}}
            generator_call.input_summary = {**(generator_call.input_summary or {}), cache_key: review_record}
            session.commit()
            return output, result.call_id
        except M5CapabilityError as exc:
            feedback = str(exc.__cause__ or exc)
            # Keep the public proposed plan and validation feedback on its own
            # generation record. A later retry can correct it rather than repeat
            # the same blind review. Provider reasoning is never captured here.
            failure = {'input_hash': review_hash, 'code': exc.code, 'feedback': feedback,
                       'previous_review': deepcopy(rejected_review),
                       'output_limit': _path_review_output_limit(exc),
                       'max_tokens': getattr(call_backend, 'max_tokens', None)}
            history = list((generator_call.input_summary or {}).get(cache_key + '_failures') or [])
            history.append(failure)
            generator_call.input_summary = {**(generator_call.input_summary or {}),
                cache_key + '_failure': failure, cache_key + '_failures': history}
            session.commit()
            if exc.code == "structured_output_invalid" and attempt == 0:
                continue
            if failure['output_limit'] and not output_limit and attempt == 0:
                output_limit = True
                continue
            raise PathDraftError("path_draft_model_failed", "学习安排还未核对完成，正在保留已完成内容并继续核对。") from exc


def _require_path_model(llm: Any) -> None:
    model = str(getattr(llm, "model", "")).strip()
    thinking = str(getattr(llm, "thinking_mode", "")).strip().lower()
    reasoning = str(getattr(llm, "reasoning_effort", "")).strip().lower()
    backend_name = llm.__class__.__name__.lower()
    if (
        model != "deepseek-v4-flash"
        or thinking != "enabled"
        or reasoning != "max"
        or "deterministic" in backend_name
        or "fallback" in backend_name
        or bool(getattr(llm, "allow_fallback", False))
    ):
        _fail(
            "path_draft_model_policy_invalid",
            "学习路径定制必须使用 deepseek-v4-flash、thinking enabled、reasoning max，且不允许回退模型。",
        )


def _build_path_model():
    """Build the governed production backend at the boundary that owns the call."""
    from config import CONFIG
    from llm_client import build_async_llm

    return build_async_llm(
        CONFIG,
        model="deepseek-v4-flash",
        thinking_mode="enabled",
        reasoning_effort="max",
        # Keep enough room for both deep reasoning and the public plan.
        # This request-specific allowance does not change normal chat limits.
        max_tokens=max(CONFIG.llm_max_tokens, 32768),
        allow_fallback=False,
    )


def _run_model_sync(coro_factory):
    """Run the async gateway from both thread-backed endpoints and direct callers."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        running_loop = False
    else:
        running_loop = True
    # Run outside the except block: otherwise asyncio can attach the expected
    # "no running event loop" probe to a provider failure and mask its category.
    if not running_loop:
        return asyncio.run(coro_factory())
    with ThreadPoolExecutor(max_workers=1) as pool:
        from contextvars import copy_context
        return pool.submit(copy_context().run, lambda: asyncio.run(coro_factory())).result()


def _authorize(session: Any, *, current_user: DBUser, course: DBCourse) -> None:
    from course_catalog import course_is_selectable
    if not course_is_selectable(session, course):
        _fail("course_unavailable", "课程已停止发布或没有可用学习资料")
    role = active_course_role(
        session, course_id=course.id, user_public_id=current_user.public_id,
    )
    if current_user.role != "admin" and course.owner_public_id != current_user.public_id and role is None:
        _fail("course_forbidden", "当前账号不是该课程成员")


def _latest_profile(
    session: Any, *, owner_public_id: str, course_id: str, profile_snapshot_id: str | None = None,
) -> DBProfileSnapshot | None:
    if profile_snapshot_id:
        row = session.get(DBProfileSnapshot, profile_snapshot_id)
        if row is None or row.owner_public_id != owner_public_id:
            return None
        return row if (row.snapshot or {}).get("course_id") in {None, course_id} else None
    rows = session.query(DBProfileSnapshot).filter_by(owner_public_id=owner_public_id).order_by(
        DBProfileSnapshot.created_at.desc(), DBProfileSnapshot.id.desc(),
    ).all()
    return next(
        (row for row in rows if (row.snapshot or {}).get("course_id") in {None, course_id}),
        None,
    )


def _course_facts(session: Any, *, course_id: str) -> dict[str, Any]:
    from types import SimpleNamespace
    from app.source_refs import current_chapter_clause, current_source_clause, source_ref_teaching_text
    from app.course_structure import confirmed_structure, prerequisite_ids
    course = session.get(DBCourse, course_id)
    chapters = session.query(DBChapter).join(DBSourceDocument, DBSourceDocument.id == DBChapter.source_document_id).filter(
        DBChapter.course_id == course_id, current_chapter_clause(), current_source_clause(),
    ).order_by(
        DBChapter.position, DBChapter.id,
    ).all()
    chapter_ids = [item.id for item in chapters]
    links = session.query(DBChapterKnowledgePoint).filter(
        DBChapterKnowledgePoint.chapter_id.in_(chapter_ids or ["-"]),
    ).all()
    kp_ids = sorted({item.knowledge_point_id for item in links})
    knowledge = {
        item.id: SimpleNamespace(**{**{column.name: getattr(item, column.name) for column in DBKnowledgePoint.__table__.columns},
                                   'prerequisites': prerequisite_ids(course, item)}) for item in session.query(DBKnowledgePoint).filter(
            DBKnowledgePoint.id.in_(kp_ids or ["-"]),
        ).all()
    }
    # Curated manifests use stable concept codes; confirmed editable
    # structures use canonical IDs. Resolve both before ordering path tasks.
    point_aliases = {alias: point.id for point in knowledge.values() for alias in (point.id, point.code)}
    for point in knowledge.values():
        point.prerequisites = [point_aliases.get(str(before), str(before)) for before in point.prerequisites or []]
    chapter_by_kp: dict[str, DBChapter] = {}
    kp_by_chapter: dict[str, list[DBKnowledgePoint]] = defaultdict(list)
    chapter_by_id = {item.id: item for item in chapters}
    references = set(confirmed_structure(course).get('reference_chapter_ids', []))
    ranks = {chapter.id: (chapter.id in references, i) for i, chapter in enumerate(chapters)}
    for link in sorted(links, key=lambda item: ranks[item.chapter_id]):
        chapter = chapter_by_id.get(link.chapter_id)
        kp = knowledge.get(link.knowledge_point_id)
        if chapter is None or kp is None:
            continue
        chapter_by_kp.setdefault(kp.id, chapter)
        kp_by_chapter[chapter.id].append(kp)
    sources = {
        item.id: item for item in session.query(DBSourceDocument).filter(
            DBSourceDocument.course_id == course_id, current_source_clause(),
        ).all()
    }
    refs = session.query(DBSourceRef).filter(
        DBSourceRef.chapter_id.in_(chapter_ids or ["-"]),
    ).order_by(DBSourceRef.created_at, DBSourceRef.id).all()
    ref_by_chapter = {item.chapter_id: item for item in refs if item.chapter_id}
    # Prefer the version-bound full chapter over a page/selection preview.
    ref_by_chapter.update({item.chapter_id: item for item in refs if item.chapter_id and item.location_kind == "chapter"})
    return {
        "teaching_units": confirmed_structure(course).get('units', []),
        "reference_chapter_ids": confirmed_structure(course).get('reference_chapter_ids', []),
        "chapters": chapters,
        "chapter_by_kp": chapter_by_kp,
        "kp_by_chapter": kp_by_chapter,
        "knowledge": knowledge,
        "sources": sources,
        "ref_by_chapter": ref_by_chapter,
        "chapter_readings": {key: {"source_ref_id": ref.id,
                                  "text": source_ref_teaching_text(session, ref, max_chars=None)}
                             for key, ref in ref_by_chapter.items()},
    }


def _path_learning_snapshot(session: Any, *, user: DBUser, course_id: str,
                            profile: DBProfileSnapshot, use_current: bool) -> dict[str, Any]:
    """Reuse confirmed preferences and the same course evidence shown in the profile."""
    snapshot = complete_learning_snapshot(session, profile)
    profile_row = session.get(DBStudentProfile, user.username)
    adaptation = profile_prompt_context(build_profile_adaptation(
        snapshot, profile=profile_row if use_current or not profile_has_signal(snapshot) else None,
    ))
    registration = adaptation.get("registration_profile") or {}
    snapshot["learning_adaptation"] = adaptation
    snapshot.setdefault("learning_goal", snapshot.get("goal") or "；".join(registration.get("learning_goals") or []))
    snapshot.setdefault("learning_preferences", snapshot.get("preferences") or {
        "interaction_preferences": registration.get("interaction_preferences") or [],
        "cognitive_style": registration.get("cognitive_style") or "",
    })
    if use_current:
        from app.profile_summary import build_profile_summary
        summary = build_profile_summary(session, current_user=user, course_id=course_id)
        nodes = summary["knowledge_graph"]["nodes"]
        snapshot["mastery_by_knowledge_point"] = {
            node["id"]: {"score": node["mastery"], "status": node["masteryBand"],
                         "evidence_count": node["evidenceCount"], "last_evidence_at": node["lastEvidenceAt"],
                         "learning_needs": node.get("learningNeeds", [])}
            for node in nodes
        }
        snapshot["mastered_knowledge_point_ids"] = [node["id"] for node in nodes if node["masteryBand"] == "mastered"]
        snapshot["weak_knowledge_point_ids"] = [node["id"] for node in nodes
            if node["masteryBand"] in {"weak", "conflict"} or node.get("learningNeeds")]
        snapshot["unknown_knowledge_point_ids"] = [node["id"] for node in nodes if node["mastery"] is None]
        snapshot["recent_learning_evidence"] = {
            "accepted_event_count": len({event for node in nodes for event in node["sourceEventIds"]}),
            "diagnostic_attempt_count": summary["summary"]["diagnostic_attempt_count"],
        }
        if not snapshot.get("diagnostic_evidence"):
            rows = session.query(DBProfileSnapshot).filter_by(owner_public_id=user.public_id).order_by(DBProfileSnapshot.created_at.desc()).all()
            diagnostic = next((row.snapshot for row in rows if (row.snapshot or {}).get("course_id") == course_id
                               and (row.snapshot or {}).get("diagnostic_evidence")), {})
            snapshot["diagnostic_evidence"] = diagnostic.get("diagnostic_evidence", {})
    # Historical snapshots retain their original grading. Add the frozen
    # question solution only to this read projection so objective errors can
    # guide teaching without another model call or invented misconception.
    diagnostic = deepcopy(snapshot.get("diagnostic_evidence") or {})
    from app.database import DBAssessmentQuestionVersion
    for item in diagnostic.get("grading_feedback") or []:
        if not item.get("explanation") and item.get("question_version_id"):
            question = session.get(DBAssessmentQuestionVersion, item["question_version_id"])
            if question:
                item["explanation"] = question.explanation or ""
    snapshot["diagnostic_evidence"] = diagnostic
    return snapshot


def _path_model_context(
    facts: dict[str, Any], *, course: DBCourse, profile: DBProfileSnapshot,
    snapshot: dict[str, Any], time_budget_minutes: int,
) -> dict[str, Any]:
    """Build the smallest serializable, course-scoped input for the path model."""
    from app.teaching_runtime import teaching_runtime_context
    from app.profile_adaptation import confirmed_study_minutes_by_weekday
    mastery = snapshot.get("mastery_by_knowledge_point") or {}
    chapters = []
    for chapter in facts["chapters"]:
        chapters.append({
            "id": chapter.id,
            "title": chapter.title,
            "position": chapter.position,
            "source_document_id": chapter.source_document_id,
            "reading": (facts.get("chapter_readings") or {}).get(chapter.id, {}),
            "learning_role": "reference" if chapter.id in facts.get("reference_chapter_ids", []) else "teaching",
            "knowledge_points": [
                {
                    "id": kp.id,
                    "title": kp.title,
                    "prerequisites": [str(item) for item in (kp.prerequisites or [])],
                    "mastery": mastery.get(kp.id, {}),
                }
                for kp in facts["kp_by_chapter"].get(chapter.id, [])
            ],
        })
    sources = [
        {
            "id": source.id,
            "title": source.title,
            "filename": source.filename,
            "license": source.license_text,
            "content_hash": source.content_hash,
        }
        for source in facts["sources"].values()
    ]
    raw_diagnostic = snapshot.get("diagnostic_evidence") or {}
    from app.profile_adaptation import diagnostic_followup
    compact_feedback = []
    for item in raw_diagnostic.get("grading_feedback") or []:
        grading = item.get("grading") or {}
        advice = grading.get("improvementAdvice") or []
        compact_feedback.append({
            "knowledge_point_id": item.get("knowledge_point_id"),
            "score": grading.get("score"),
            "correct": grading.get("correct"),
            "feedback": str(grading.get("feedback") or ""),
            "improvement_advice": [str(value) for value in advice],
            "criterion_results": list(grading.get("criterionResults") or []),
        })
    diagnostic_evidence = {
        "source_ref_ids": list(raw_diagnostic.get("source_ref_ids") or []),
        "attempt_count": len(raw_diagnostic.get("attempt_ids") or []),
        "grading_feedback": compact_feedback,
        "followup": diagnostic_followup(snapshot),
        "followup_policy": "总分达标仍可能有具体误解；结合后续真实作答判断逐项缺口是否已解决，未解决的进入路径和练习，不仅按总分略过。",
    }
    return {
        "course": {"id": course.id, "title": course.title, "version": course.version},
        "teaching_units": facts.get("teaching_units", []),
        "profile_snapshot_id": profile.id,
        "initial_learning_evidence": {
            "mastery_by_knowledge_point": mastery,
            "mastered_knowledge_point_ids": [str(item) for item in snapshot.get("mastered_knowledge_point_ids") or []],
            "weak_knowledge_point_ids": [str(item) for item in snapshot.get("weak_knowledge_point_ids") or []],
            "unknown_knowledge_point_ids": [str(item) for item in snapshot.get("unknown_knowledge_point_ids") or []],
            "self_reported_learning_start_points": list(snapshot.get("self_reported_learning_start_points") or []),
            "diagnostic_evidence": diagnostic_evidence,
        },
        "learning_goal": snapshot.get("learning_goal") or snapshot.get("goal") or "完成当前课程的可验证学习目标",
        "learning_preferences": snapshot.get("learning_preferences") or snapshot.get("preferences") or {},
        "learning_adaptation": snapshot.get("learning_adaptation") or {},
        "recent_learning_evidence": snapshot.get("recent_learning_evidence") or {},
        "time_budget_minutes": time_budget_minutes,
        "study_minutes_by_weekday": confirmed_study_minutes_by_weekday(snapshot),
        "runtime": teaching_runtime_context(),
        "course_graph": {"chapters": chapters, "sources": sources},
    }


def _full_course_tasks(facts: dict[str, Any]) -> list[dict[str, Any]]:
    """Use confirmed units, retaining each chapter's remaining reading/concepts.

    One unit may use several chapters; each part keeps its real source chapter.
    The existing path version freezes these scopes without a second plan system.
    """
    units = facts.get("teaching_units") or []
    tasks = []
    chapter_ids = {chapter.id for chapter in facts['chapters']} - set(facts.get('reference_chapter_ids', []))
    for unit in units:
        primary = set(unit.get('primary_chapter_keys') or [])
        if primary:
            covered = {point.id for key in primary for point in facts['kp_by_chapter'].get(key, [])}
            if not primary.issubset(chapter_ids) or not set(unit.get('knowledge_point_ids', [])).issubset(covered):
                _fail('path_unit_source_changed', '学习单元的主学习章节已变化，请在课程结构中更新后继续。')
    primary_points = {key for unit in units if unit.get('primary_chapter_keys')
                      for key in unit.get('knowledge_point_ids', [])}
    for chapter in facts["chapters"]:
        if chapter.id not in chapter_ids:
            continue
        points = [point.id for point in facts["kp_by_chapter"].get(chapter.id, [])]
        assigned = set()
        for unit in units:
            if unit.get('primary_chapter_keys') and chapter.id not in unit['primary_chapter_keys']:
                continue
            scope = [key for key in unit.get("knowledge_point_ids", []) if key in points]
            if not scope:
                continue
            key = hashlib.sha256(json.dumps([unit["key"], chapter.id, sorted(scope)]).encode()).hexdigest()[:24]
            tasks.append({"node_key": f"unit-{key}", "target_object_id": chapter.id,
                          "title": unit["title"], "knowledge_point_ids": scope,
                          "teaching_unit_key": unit["key"], "teaching_goal": unit.get("goal", ""),
                          "prerequisites": []})
            assigned.update(scope)
        # Explicit primary chapters carry the learning task. Other sources
        # remain in the course and retrieval pool, without repeating that unit.
        remaining = [key for key in points if key not in assigned and key not in primary_points]
        if remaining or not points:
            tasks.append({"node_key": chapter.id, "target_object_id": chapter.id,
                          "title": chapter.title, "knowledge_point_ids": remaining,
                          "teaching_unit_key": None, "teaching_goal": "", "prerequisites": []})
    try:
        return order_course_tasks(tasks, facts['knowledge'])
    except ValueError as exc:
        _fail('path_unit_order_conflict', str(exc))


def _task_node_groups(output, tasks):
    expected = {item["node_key"]: item for item in tasks}
    grouped = defaultdict(list)
    for node in output.plan.nodes:
        key = re.sub(r"-part-[1-9][0-9]*$", "", node.node_key)
        if key not in expected:
            # Older whole-chapter outputs may choose their own node key. They
            # still identify one unambiguous chapter, never a confirmed unit.
            matches = [item for item in tasks if item["target_object_id"] == node.target_object_id
                       and not item["teaching_unit_key"] and not node.teaching_unit_key]
            key = matches[0]["node_key"] if len(matches) == 1 else None
        if key not in expected:
            _fail("path_unit_scope_invalid", "学习任务与确认的知识范围不一致，请重新生成。")
        grouped[key].append(node)
    if set(grouped) != set(expected):
        _fail("path_unit_scope_invalid", "路径遗漏了已确认的教学单元，请重新生成。")
    return grouped


def _validate_session_budget(output, time_budget_minutes):
    if time_budget_minutes and any(node.estimate_max_minutes > time_budget_minutes for node in output.plan.nodes):
        _fail("path_session_too_long", f"有学习任务超过单次可用的{time_budget_minutes}分钟，请按实际学习内容拆分，保留完整范围和真实时长。")
    return output


def _validate_task_batch(output, tasks, *, time_budget_minutes=None):
    grouped = _task_node_groups(output, tasks)
    _validate_session_budget(output, time_budget_minutes)
    for item in tasks:
        nodes = grouped[item["node_key"]]
        expected_points = set(item["knowledge_point_ids"])
        covered = set()
        stages = set()
        for node in nodes:
            points = set(node.knowledge_point_ids)
            if not points and len(nodes) == 1 and not item["teaching_unit_key"]:
                points = expected_points  # A legacy whole-chapter node includes its chapter.
            if (node.node_type != "chapter" or node.target_object_id != item["target_object_id"] or
                    not points.issubset(expected_points) or (expected_points and not points) or
                    node.teaching_unit_key != item["teaching_unit_key"]):
                _fail("path_unit_scope_invalid", "学习任务与确认的知识范围不一致，请重新生成。")
            if len(nodes) > 1:
                stage = (tuple(sorted(points)), node.teaching_goal.strip())
                if (not re.fullmatch(re.escape(item["node_key"]) + r"-part-[1-9][0-9]*", node.node_key)
                        or not node.teaching_goal.strip() or stage in stages):
                    _fail("path_unit_scope_invalid", "分次学习需要各自明确且不重复的学习目标，请重新安排。")
                stages.add(stage)
            covered.update(points)
        if covered != expected_points:
            _fail("path_unit_scope_invalid", "分次学习遗漏了当前单元的知识内容，请补齐。")
    # Course chapters arrive in catalogue order; the chosen teaching sequence
    # must already be the order seen by the reviewer, not only the final merge.
    return output.model_copy(update={'plan': output.plan.model_copy(update={
        'nodes': tuple(node for item in tasks for node in grouped[item['node_key']]),
    })})


def _validate_model_plan_output(
    payload: dict[str, Any], *, facts: dict[str, Any], owner_public_id: str,
    course_id: str, session: Any, require_full_coverage: bool = False,
    required_chapter_ids: set[str] | None = None,
) -> PathDraftModelOutput:
    payload = _coerce_model_payload(payload, facts=facts)
    try:
        output = PathDraftModelOutput.model_validate(payload)
    except Exception as exc:
        _fail("path_draft_model_output_invalid", "模型返回的路径草稿不符合正式结构，请重试。")
        raise AssertionError from exc
    allowed_chapters = {item.id for item in facts["chapters"]}
    for node in output.plan.nodes:
        if node.node_type == "chapter" and node.target_object_id not in allowed_chapters:
            _fail("path_draft_model_scope_invalid", "模型草稿包含不属于当前课程的章节。")
    try:
        _validate_plan_targets(
            session, owner_public_id=owner_public_id, course_id=course_id,
            spec=output.plan,
        )
    except PathDraftError:
        raise
    except Exception as exc:
        _fail("path_draft_model_targets_invalid", "模型草稿的课程或资源授权校验失败，请重试。")
        raise AssertionError from exc
    covered_chapters = {str(node.target_object_id) for node in output.plan.nodes if node.node_type == "chapter"}
    if require_full_coverage:
        required = {task['target_object_id'] for task in _full_course_tasks(facts)}
        missing_chapters = required - covered_chapters
        if missing_chapters:
            _fail("path_draft_model_scope_invalid", "模型草稿没有覆盖当前课程的全部章节。")
    if required_chapter_ids and not required_chapter_ids.issubset(covered_chapters):
        _fail("path_draft_model_scope_invalid", "模型批次没有覆盖分配的章节。")
    return output


def _coerce_model_payload(payload: dict[str, Any], *, facts: dict[str, Any]) -> dict[str, Any]:
    """Normalize a legacy model envelope before the strict PlanSpec boundary.

    Older providers have returned the same model-authored plan with names such as
    ``plan_schema``, knowledge-point node keys, ordinal difficulties and resource
    availability objects.  Those fields can be mapped to the current course graph;
    an unmappable node or prerequisite is a real model-output failure and must not
    be handed to Pydantic (or replaced with a deterministic path).
    """
    if not isinstance(payload, dict):
        _fail("path_draft_model_output_invalid", "模型返回的路径草稿不是对象。")
    wrapper = dict(payload)
    raw_plan = wrapper.get("plan", wrapper)
    if not isinstance(raw_plan, dict):
        _fail("path_draft_model_output_invalid", "模型返回的路径计划不是对象。")
    plan = dict(raw_plan)
    if plan.get("schema_version") != "m5.plan.v1":
        plan["schema_version"] = plan.get("plan_schema") or plan.get("schema") or "m5.plan.v1"

    chapters = {item.id: item for item in facts["chapters"]}
    knowledge = facts["knowledge"]
    chapter_by_kp = facts["chapter_by_kp"]
    chapter_ids = set(chapters)
    valid_node_types = {"chapter", "artifact", "assessment", "interactive", "review", "extension"}

    def resolve_chapter(node: dict[str, Any]) -> tuple[str, DBChapter]:
        candidates: list[str] = []
        for key in (
            "target_object_id", "knowledge_point_id", "target_knowledge_point_id",
            "chapter_id", "target_id", "id", "node_key",
        ):
            value = node.get(key)
            if isinstance(value, dict):
                value = value.get("id") or value.get("key") or value.get("knowledge_point_id")
            if value is not None and str(value).strip():
                candidates.append(str(value).strip())
        for candidate in candidates:
            if candidate in chapters:
                return candidate, chapters[candidate]
            if candidate in chapter_by_kp:
                chapter = chapter_by_kp[candidate]
                return candidate, chapter
        # Some older outputs use a display key (for example learn-kp-04) rather
        # than the canonical knowledge-point id.  Only accept an unambiguous
        # suffix match from the current course graph.
        suffix_matches: dict[str, DBChapter] = {}
        for candidate in candidates:
            suffix = candidate.rsplit("-", 1)[-1].lower()
            matches = [
                (kp_id, chapter)
                for kp_id, chapter in chapter_by_kp.items()
                if kp_id.rsplit("-", 1)[-1].lower() == suffix
            ]
            if len(matches) == 1:
                return matches[0]
            suffix_matches.update(matches)
        if len(suffix_matches) == 1:
            return next(iter(suffix_matches.items()))
        _fail("path_draft_model_scope_invalid", "模型草稿包含无法映射到当前课程图谱的节点。")
        raise AssertionError

    def normalize_status(node: dict[str, Any], chapter: DBChapter) -> str:
        value = node.get("resource_status")
        if isinstance(value, dict):
            value = value.get("status") or value.get("availability") or value.get("state")
        value = str(value or "").strip().lower()
        if value in {"existing", "available", "ready", "published", "source_available"}:
            return "existing"
        if value in {"to_generate", "generate", "missing", "pending", "not_available"}:
            return "to_generate"
        if value in {"external", "external_dependency", "dependency"}:
            return "external_dependency"
        # ``weak``/``not_learned`` are mastery labels emitted by an older path
        # prompt.  Resource availability remains a course fact, not a mastery
        # conclusion, so use the chapter's admitted source when present.
        if value in {"", "unknown", "not_learned", "weak", "incomplete"}:
            return "existing" if chapter.source_document_id in facts["sources"] else "to_generate"
        _fail("path_draft_model_output_invalid", "模型草稿包含无法识别的资源状态。")
        raise AssertionError

    def normalize_difficulty(value: Any) -> float | None:
        if value is None or value == "":
            return None
        if isinstance(value, str):
            text = value.strip().lower()
            value = {
                "easy": 0.3, "basic": 0.3, "beginner": 0.25,
                "medium": 0.5, "intermediate": 0.55,
                "hard": 0.75, "advanced": 0.8,
                "简单": 0.3, "基础": 0.3, "入门": 0.25,
                "中等": 0.5, "中级": 0.55,
                "困难": 0.75, "进阶": 0.8,
            }.get(text, text)
        try:
            number = float(value)
        except (TypeError, ValueError):
            _fail("path_draft_model_output_invalid", "模型草稿包含无法识别的难度。")
            raise AssertionError
        # Legacy prompts used 1..5 ordinal difficulty while the current contract
        # uses [0, 1].  Preserve model intent without letting an ordinal through.
        if number > 1:
            number = {2.0: 0.3, 3.0: 0.55, 4.0: 0.75, 5.0: 0.9}.get(number, -1)
        if not 0 <= number <= 1:
            _fail("path_draft_model_output_invalid", "模型草稿的难度超出有效范围。")
        return round(number, 3)

    def normalize_minutes(node: dict[str, Any]) -> tuple[int, int]:
        minimum = node.get("estimate_min_minutes")
        maximum = node.get("estimate_max_minutes")
        estimate = node.get("estimate_minutes") or node.get("estimated_minutes")
        estimate = estimate or node.get("estimated_time_minutes") or node.get("duration_minutes")
        if isinstance(estimate, dict):
            minimum = minimum or estimate.get("min") or estimate.get("minimum")
            maximum = maximum or estimate.get("max") or estimate.get("maximum")
        minimum = minimum or estimate or 15
        maximum = maximum or estimate or minimum
        try:
            minimum, maximum = int(minimum), int(maximum)
        except (TypeError, ValueError):
            _fail("path_draft_model_output_invalid", "模型草稿包含无法识别的学习时长。")
            raise AssertionError
        if minimum < 1 or maximum < minimum:
            _fail("path_draft_model_output_invalid", "模型草稿的学习时长无效。")
        return minimum, maximum

    normalized_nodes: list[dict[str, Any]] = []
    aliases: dict[str, str] = {}
    selected_chapter_ids: set[str] = set()
    for raw in plan.get("nodes") or []:
        if not isinstance(raw, dict):
            _fail("path_draft_model_output_invalid", "模型草稿包含无效的路径节点。")
        node = dict(raw)
        target, chapter = resolve_chapter(node)
        node_key = str(node.get("node_key") or f"model-{chapter.id}").strip()
        if not node_key:
            _fail("path_draft_model_output_invalid", "模型草稿节点缺少唯一标识。")
        node_type = str(node.get("node_type") or "chapter").strip().lower()
        if node_type not in valid_node_types or target not in chapter_ids:
            node_type = "chapter"
        minimum, maximum = normalize_minutes(node)
        normalized = {
            "node_key": node_key,
            "node_type": node_type,
            "target_object_id": chapter.id,
            "title": str(node.get("title") or chapter.title),
            "prerequisites": list(node.get("prerequisites") or []),
            "resource_status": normalize_status(node, chapter),
            "estimate_min_minutes": minimum,
            "estimate_max_minutes": maximum,
            "difficulty": normalize_difficulty(node.get("difficulty")),
            "rationale": str(node.get("rationale") or node.get("reason") or "模型依据本次初始学情安排该步骤。"),
            "knowledge_point_ids": list(node.get("knowledge_point_ids") or []),
            "teaching_unit_key": node.get("teaching_unit_key"),
            "teaching_goal": str(node.get("teaching_goal") or ""),
        }
        aliases[node_key] = node_key
        aliases[target] = node_key
        aliases[chapter.id] = node_key
        selected_chapter_ids.add(chapter.id)
        for kp_id, mapped_chapter in chapter_by_kp.items():
            if mapped_chapter.id == chapter.id:
                aliases[kp_id] = node_key
                point = knowledge.get(kp_id)
                if point is not None:
                    if point.code:
                        aliases[str(point.code)] = node_key
                    if point.title:
                        aliases[str(point.title)] = node_key
        normalized_nodes.append(normalized)

    if not normalized_nodes:
        _fail("path_draft_model_output_invalid", "模型草稿没有可用的路径节点。")
    selected_aliases = dict(aliases)

    def course_chapter_for_alias(value: str) -> DBChapter | None:
        if value in chapters:
            return chapters[value]
        if value in chapter_by_kp:
            return chapter_by_kp[value]
        suffix = value.rsplit("-", 1)[-1].lower()
        matches = [
            chapter for kp_id, chapter in chapter_by_kp.items()
            if kp_id.rsplit("-", 1)[-1].lower() == suffix
        ]
        return matches[0] if len({item.id for item in matches}) == 1 else None

    seen: set[str] = set()
    for node in normalized_nodes:
        prerequisites: list[str] = []
        for prerequisite in node["prerequisites"]:
            if isinstance(prerequisite, dict):
                prerequisite = prerequisite.get("node_key") or prerequisite.get("target_object_id") or prerequisite.get("knowledge_point_id")
            key = str(prerequisite or "").strip()
            mapped = selected_aliases.get(key)
            if mapped is None:
                suffix = key.rsplit("-", 1)[-1].lower()
                suffix_values = {
                    value for alias, value in selected_aliases.items()
                    if alias.rsplit("-", 1)[-1].lower() == suffix
                }
                mapped = next(iter(suffix_values)) if len(suffix_values) == 1 else None
            if mapped is None:
                prerequisite_chapter = course_chapter_for_alias(key)
                # A mastered/external prerequisite is a course fact, not a node
                # that must be repeated in this learner's path.  It remains in
                # the model rationale and graph input but is omitted from the
                # PlanSpec edge set.  Unknown aliases are still rejected.
                if prerequisite_chapter is not None and prerequisite_chapter.id not in selected_chapter_ids:
                    continue
            if mapped is None or mapped not in seen:
                _fail("path_draft_model_topology_invalid", "模型草稿包含无法验证或顺序错误的先修关系。")
            if mapped not in prerequisites:
                prerequisites.append(mapped)
        node["prerequisites"] = prerequisites
        seen.add(node["node_key"])

    plan = {
        key: plan[key] for key in ("schema_version", "goal", "deadline", "assumptions") if key in plan
    }
    plan.setdefault("schema_version", "m5.plan.v1")
    plan.setdefault("goal", "完成当前课程的可验证学习目标")
    plan.setdefault("assumptions", [])
    plan["nodes"] = normalized_nodes
    return {
        "plan": plan,
        "personalization_summary": str(
            wrapper.get("personalization_summary")
            or plan.get("personalization_summary")
            or "模型依据当前初始学情生成了定制学习路径。"
        ),
    }


async def _generate_model_path(
    session: Any, *, llm: Any, user: DBUser, course: DBCourse,
    profile: DBProfileSnapshot, snapshot: dict[str, Any], facts: dict[str, Any],
    time_budget_minutes: int, idempotency_key: str | None, full_coverage: bool = False,
    progress=None,
) -> tuple[PathDraftModelOutput, dict[str, Any]]:
    _require_path_model(llm)
    if full_coverage:
        return await _generate_model_path_in_batches(
            session, llm=llm, user=user, course=course, profile=profile,
            snapshot=snapshot, facts=facts, time_budget_minutes=time_budget_minutes,
            idempotency_key=idempotency_key, progress=progress,
        )
    if progress:
        progress({"stage": "generation", "completed": 0, "total": 0})
    context = _path_model_context(
        facts, course=course, profile=profile, snapshot=snapshot,
        time_budget_minutes=time_budget_minutes,
    )
    system_prompt = (
        "你是 EduMatrix 的个性化学习路径规划专家。只能输出符合 JSON Schema 的原始 JSON 对象，不要 Markdown。"
        "必须根据输入的初始诊断证据、学习目标、偏好、时间预算、当前课程图谱和授权来源生成真实定制路径；"
        "不得复制固定章节模板，不得臆造课程外节点，不得把 unknown 证据当作已掌握。"
        "同时参考已确认的初始偏好、持续画像和当前课程真实学习记录；没有入学诊断不等于没有任何学习。"
        "偏好只影响讲法、练习方式和节奏，不得把自述当成绩；已有实践只支持对应知识点，不推广到全课程。"
        "具体目标、讲解语言、设备和日程以learning_adaptation.learning_requirements为准。每个节点须能在单次time_budget_minutes内独立完成，"
        "参考阅读章节用于查阅和补充证据，不默认安排为必修；优先使用教学单元指定的主学习章节。"
        "实验按context.runtime及已确认工具安排，优先提供可运行的小数据实验；原文下载步骤和未提供数据不能直接当作已具备，编程初学者先安排运行与改输入的准备。"
        "较大的学习内容拆成有明确teaching_goal和knowledge_point_ids的小步骤，不能只降低估时或在理由里写可拆分。"
        "机器学习任务需明确训练集拟合、验证集或交叉验证选参数、测试集最后评估；不得建议根据测试分数调参。"
        "输出的 plan 必须是 m5.plan.v1，节点顺序必须满足先修关系；每个节点的 rationale 必须说明本次画像为何需要它。"
        "最终 content 必须是包含 plan.nodes 的结果对象，不要返回 JSON Schema 定义、字段说明或 schema 片段。"
        + LEARNER_FEEDBACK_INSTRUCTION
    )
    prompt_payload = {
        "task": "diagnostic_personalized_learning_path",
        "idempotency_key": idempotency_key,
        "context": context,
        "output_requirements": {
            "plan_schema": "m5.plan.v1",
            "minimum_nodes": 1,
            "must_include": ["goal", "assumptions", "nodes", "node_key", "prerequisites", "resource_status", "estimate_min_minutes", "estimate_max_minutes", "difficulty", "rationale"],
            "shape_example": {
                "plan": {"schema_version": "m5.plan.v1", "goal": "根据当前证据安排学习", "assumptions": [], "nodes": [{"node_key": "chapter-1", "node_type": "chapter", "target_object_id": "使用输入图谱中的章节 id", "title": "使用输入图谱中的章节标题", "prerequisites": [], "resource_status": "existing", "estimate_min_minutes": 20, "estimate_max_minutes": 30, "difficulty": 0.45, "rationale": "说明该节点与当前诊断证据的关系"}]},
                "personalization_summary": "说明路径如何结合当前诊断证据调整"
            },
            "do_not_include": ["api_key", "prompt", "reasoning_content", "private_agent_log"],
        },
    }
    result = None
    for attempt in range(2):
        request_payload = dict(prompt_payload)
        if attempt:
            request_payload["retry_instruction"] = (
                "上一次返回未通过结构校验。请重新生成，严格只输出一个原始 JSON 对象，"
                "不要 Markdown、解释文字或代码围栏；所有节点和先修关系必须来自输入课程图谱。"
            )
        user_prompt = json.dumps(
            request_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        try:
            result = await execute_registered_structured_call(
                session,
                backend=llm,
                capability=Capability.PLAN,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                role="诊断结果个性化路径规划",
                operation="p1_b11_personalized_learning_path",
                response_model=PathDraftModelOutput,
                owner_public_id=user.public_id,
                course_id=course.id,
                output_constraints=OutputConstraints(
                    language="auto", format="json", max_length=20000,
                    source_scope=tuple(sorted(facts["sources"])),
                    safety_boundary="仅可使用当前课程和授权来源；不发布未确认草稿。",
                ),
                response_validator=lambda value: _validate_session_budget(_validate_model_plan_output(
                    value, facts=facts, owner_public_id=user.public_id,
                    course_id=course.id, session=session,
                    require_full_coverage=False,
                ), time_budget_minutes),
            )
            break
        except M5CapabilityError as exc:
            if exc.code == "structured_output_invalid" and attempt == 0:
                continue
            raise PathDraftError("path_draft_model_failed", "真实模型未能完成学习路径定制，请稍后重试。") from exc
        except PathDraftError:
            raise
        except Exception as exc:
            raise PathDraftError("path_draft_model_failed", "学习路径定制暂时失败，请稍后重试。") from exc
    if result is None:
        _fail("path_draft_model_failed", "真实模型未能完成学习路径定制，请稍后重试。")
    if result.fallback_used or result.model != "deepseek-v4-flash":
        _fail("path_draft_model_policy_invalid", "路径定制未使用受治理的 deepseek-v4-flash 模型。")
    output = _validate_session_budget(_validate_model_plan_output(
        result.structured_output or {}, facts=facts, owner_public_id=user.public_id,
        course_id=course.id, session=session,
    ), time_budget_minutes)
    return output, {
        "status": "completed",
        "call_id": result.call_id,
        "model": result.model,
        "prompt_version": result.prompt_version,
        "personalization_summary": output.personalization_summary,
    }


def _path_candidate_basis(payload, *, system_prompt, llm):
    """Identify a reusable *draft*, not an approval under a new earlier plan.

    Source bodies, learner evidence, tools, task scope and course outline stay
    bound. Previous generated steps are reconciled by the current full review.
    A document elsewhere in the course changing edition need not regenerate
    this candidate, but still changes the review's complete input hash.
    """
    basis = deepcopy(payload)
    for key in ('earlier_learning_steps', 'earlier_maximum_minutes', 'earlier_stage_notes'):
        basis.pop(key, None)
    context = basis['context']
    context['course'].pop('version', None)
    graph = context['course_graph']
    relevant_sources = {ch['source_document_id'] for ch in graph['chapters']}
    graph['sources'] = [source for source in graph['sources'] if source['id'] in relevant_sources]
    return hashlib.sha256(json.dumps({
        'scope': 'path-candidate-basis-v1', 'version': PATH_PLANNING_REVISION,
        'system': system_prompt, 'payload': basis, 'model': llm.model,
        'thinking': llm.thinking_mode, 'reasoning': llm.reasoning_effort,
    }, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


async def _generate_model_path_in_batches(
    session: Any, *, llm: Any, user: DBUser, course: DBCourse,
    profile: DBProfileSnapshot, snapshot: dict[str, Any], facts: dict[str, Any],
    time_budget_minutes: int, idempotency_key: str | None, progress=None,
) -> tuple[PathDraftModelOutput, dict[str, Any]]:
    """Generate a full-course path through bounded model batches, then merge."""
    tasks = _full_course_tasks(facts)
    if progress:
        progress({'stage': 'analysis', 'completed': 0, 'total': len(tasks)})
    try:
        tasks, sequence, sequence_call_id = await prepare_task_sequence(
            session, llm=llm, user=user, course=course,
            context=_path_model_context(facts, course=course, profile=profile, snapshot=snapshot,
                                        time_budget_minutes=time_budget_minutes),
            tasks=tasks, knowledge=facts['knowledge'],
        )
    except (M5CapabilityError, ValueError) as exc:
        raise PathDraftError('path_sequence_failed', '近期学习安排尚未完成，请重试；已保存的学习步骤会继续保留。') from exc
    all_nodes: list[PlanNodeSpec] = []
    summaries: list[str] = []
    assumptions: list[str] = []
    model_goals: list[str] = []
    call_ids: list[str] = []
    review_call_ids: list[str] = []
    batch_size = 4
    task_tails: dict[str, str] = {}
    reusable = {}
    reusable_candidates = {}
    task_candidates = saved_task_path_calls(session, user=user, course=course, field='path_batch_result')
    for call in session.query(DBModelCall).filter_by(owner_public_id=user.public_id, course_id=course.id,
            capability=Capability.PLAN.value, status="completed").order_by(DBModelCall.created_at.desc()).all():
        saved = (call.input_summary or {}).get("path_batch_result") or {}
        if saved.get("input_hash") and saved.get("output"):
            reusable.setdefault(saved["input_hash"], (call, saved["output"]))
            if saved.get('candidate_basis_hash'):
                reusable_candidates.setdefault(saved['candidate_basis_hash'], (call, saved['output']))
    for batch_index in range(0, len(tasks), batch_size):
        assigned = tasks[batch_index:batch_index + batch_size]
        if progress:
            progress({"stage": "generation", "completed": batch_index, "total": len(tasks)})
        batch_ids = {item["target_object_id"] for item in assigned}
        batch = [item for item in facts["chapters"] if item.id in batch_ids]
        batch_facts = {
            **facts,
            "chapters": batch,
            "kp_by_chapter": {key: value for key, value in facts["kp_by_chapter"].items() if key in batch_ids},
            "chapter_by_kp": {key: value for key, value in facts["chapter_by_kp"].items() if value.id in batch_ids},
            "teaching_units": [unit for unit in facts.get("teaching_units", [])
                               if unit["key"] in {item["teaching_unit_key"] for item in assigned}],
        }
        relevant_ids = {point.id for points in batch_facts["kp_by_chapter"].values() for point in points}
        relevant_ids.update(str(before) for key in list(relevant_ids) for before in facts["knowledge"][key].prerequisites or [])
        batch_snapshot = {**snapshot, "mastery_by_knowledge_point": {
            key: value for key, value in (snapshot.get("mastery_by_knowledge_point") or {}).items() if key in relevant_ids}}
        for field in ("mastered_knowledge_point_ids", "weak_knowledge_point_ids", "unknown_knowledge_point_ids"):
            batch_snapshot[field] = [key for key in snapshot.get(field, []) if key in relevant_ids]
        context = _path_model_context(
            batch_facts, course=course, profile=profile, snapshot=batch_snapshot,
            time_budget_minutes=time_budget_minutes,
        )
        system_prompt = (
            "你是 EduMatrix 的个性化学习路径规划专家。只能输出一个原始 JSON 对象，不要 Markdown 或 JSON Schema。"
            "当前是完整课程路径的一个批次；必须覆盖分配的学习任务，不能遗漏、重复或臆造章节。"
            "节点顺序遵循输入章节顺序，rationale结合原题原答与当前诊断证据。已正确的部分直接用于新任务或简短核对，"
            "主体学习补具体失分子问题，不因同点部分失分从头重教全部定义；只有真实缩减重复任务才能减少时长，最终独立要求不降低。"
            "结合learning_adaptation中的初始偏好、持续画像及recent_learning_evidence安排讲法和节奏；没有诊断不等于没有学习，自述不能冒充掌握。"
            "learning_requirements中的具体目标决定练习与成果；已确认的语言、设备和时间决定任务表述、可执行操作和分段，不因职业或学历直接判定学科能力。"
            "非编程课程按本领域实际学习动作安排，不强制写代码；现有设备不能执行的操作应改成同样能检验目标的可行任务。"
            "课程内代码按context.runtime实际模块、数据访问和运行时长安排；教材使用的框架或数据集不等于本产品已经提供。"
            "将大型下载/训练改成可内嵌小数据或明确标注合成数据的真实实验，保留专业问题、验证和误差分析；不把日志阅读当作完成训练。"
            "编程初学者首次代码任务先安排运行、修改输入、识别输出和常见错误的准备，并纳入合理时长和先修；不能只写先看示例就要求独立实现复杂函数。"
            "机器学习任务需明确训练集拟合、验证集或交叉验证选参数、测试集最后评估；不得建议根据测试分数调参。"
            "difficulty 必须是 0 到 1 之间的数值，时长为正整数分钟。"
            "required_learning_tasks给出本批任务及完整知识范围。每项可生成一个或多个chapter节点；"
            "若整项无法在单次time_budget_minutes内合理完成，必须按真实知识子集或学习阶段拆分，不能压低估时或仅写可分次。"
            "未拆分时照录node_key；拆分时使用原node_key-part-1、-part-2等，按学习顺序输出。"
            "target_object_id、teaching_unit_key保持不变，各段knowledge_point_ids必须来自原任务且合并后完整覆盖原范围。"
            "每段teaching_goal写出本次能完成和检查的具体成果；同一概念确需多阶段时，各阶段的任务和检查必须有实质区别。"
            "每段estimate_max_minutes不得超过单次可用时间。标题、目标和rationale应表达本段学习内容，不重复安排整章。"
            "prerequisites输出空数组，系统将连接各段并应用已确认的先修关系。"
            "plan.goal保留学习者的具体目标，不换成完成课程；assumptions说明阶段成果与完整课程的关系。"
            "全课可能超过个人目标期限，不能许诺在期限内学完全部内容；结合course_learning_outline说明先实现什么成果、哪些内容继续深入。"
            "按course_graph.chapters.reading中的实际原文核对定义、量的含义、假设与先修，不仅凭知识点名称设计。"
            "同一知识点跨多个单元时，本段只承担当前原文覆盖的部分，结合course_learning_outline承接后续专门单元；"
            "不要按知识点总标题在每个单元重复教完全部内容，也不要用未经资料支持的拓展任务替代后续已有教材。"
            "这是学习路线设计：每段teaching_goal用一两句交代要做什么、产出什么、怎样检查；本次不解答教材习题，"
            "不预先计算和填写标准答案，不把完整公式课或解题过程塞进路线。需要的讲解、数值例题和解析在学习该节点时生成。"
            "学习目标中若包含公式或操作结论，保留决定其成立的条件；引用原文的具体概念，不编造未展示的课程内容。"
            "用户要做成的成果须落实进已有节点teaching_goal，例如已有基础足以做初版时就形成可检查成果，后续再用进阶内容修订。"
            "near_term_learning给出本次先实现的成果及画像依据；任务已按真实知识先修重新编排，可能从同一教学单元拆出近期子范围。"
            "以required_learning_tasks的知识子范围与目标为准，不因原文章节还讲训练或复杂推导就提前要求完成整章。"
            "若当前任务是分析已给预测，提供可核对的同一数据表和不同模型输出；实际训练在后续相应任务完成。"
            "首批就安排第一个实际可用成果；明确在哪一步、哪次学习时段形成什么，不要每批把成果推给后文。"
            "已确认时段可顺序容纳多个短任务，先完成前置任务再继续；相同任务内可合并过细准备，但不要压低合理时长。"
            "利用earlier_learning_steps承接已经安排的内容与实际累计时长，不能每批重新从零开始，不能把具体成果降成笼统的朝目标进展。"
            "rationale用一两句说明这一段怎样帮助当前目标，不在每个节点反复说没有诊断、没有成绩或未证明掌握。"
            "assumptions只写本批影响学习安排的具体条件或阶段成果，用清楚短句；不重复已有批次、常规身份约束或泛泛免责声明。"
            + LEARNER_FEEDBACK_INSTRUCTION
            + f"输出 JSON Schema：{json.dumps(PathDraftModelOutput.model_json_schema(), ensure_ascii=False)}"
        )
        payload = {
            "task": "diagnostic_personalized_learning_path_batch",
            "batch_index": batch_index // batch_size + 1,
            "batch_chapter_ids": [item.id for item in batch],
            "context": context,
            "near_term_learning": sequence.model_dump(mode='json'),
            "required_learning_tasks": assigned,
            "earlier_learning_steps": [{"node_key": node.node_key, "title": node.title,
                                        "teaching_goal": node.teaching_goal,
                                        "estimate_max_minutes": node.estimate_max_minutes} for node in all_nodes],
            "earlier_maximum_minutes": sum(node.estimate_max_minutes for node in all_nodes),
            "earlier_stage_notes": assumptions,
            "course_learning_outline": [{key: item[key] for key in ("node_key", "title", "teaching_goal", "prerequisites")}
                                        for item in tasks],
            "output_requirements": {
                "plan_schema": "m5.plan.v1",
                "minimum_nodes": len(assigned),
                "session_budget_minutes": time_budget_minutes,
                "must_include_every_batch_chapter": True,
                "must_include": ["goal", "assumptions", "nodes", "node_key", "prerequisites", "resource_status", "estimate_min_minutes", "estimate_max_minutes", "difficulty", "rationale"],
                "do_not_include": ["api_key", "prompt", "reasoning_content", "private_agent_log"],
            },
        }
        def validate_batch(value):
            # Batch edges are constructed below from the confirmed task graph.
            # A model's stray cross-batch edge must neither replace that graph
            # nor make an otherwise usable teaching revision fail local schema.
            if isinstance(value, dict) and isinstance(value.get("plan"), dict):
                value = {**value, "plan": {**value["plan"], "nodes": [
                    {**node, "prerequisites": []} if isinstance(node, dict) else node
                    for node in value["plan"].get("nodes", [])
                ]}}
            output = _validate_model_plan_output(
                value, facts=facts, owner_public_id=user.public_id, course_id=course.id,
                session=session, required_chapter_ids=batch_ids,
            )
            return _validate_task_batch(output, assigned, time_budget_minutes=time_budget_minutes)
        result = None
        batch_hash = hashlib.sha256(json.dumps({"version":PATH_PLANNING_REVISION,"system":system_prompt,"payload":payload,
            "model":llm.model,"thinking":llm.thinking_mode,"reasoning":llm.reasoning_effort},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        candidate_basis = _path_candidate_basis(payload, system_prompt=system_prompt, llm=llm)
        exact_cached = reusable.get(batch_hash)
        cached = exact_cached or reusable_candidates.get(candidate_basis)
        if not cached:
            # Reuse this task's actual saved draft across a deployment. This
            # does not reuse its old approval: the complete current payload,
            # sources and runtime still go through the ordinary review below.
            for previous in reversed(task_candidates):
                saved = previous.input_summary
                candidate = (saved.get('path_teaching_verified_result') or
                             saved.get('path_teaching_review') or saved['path_batch_result']).get('output')
                if not candidate:
                    continue
                try:
                    candidate = validate_batch(candidate).model_dump(mode='json')
                except (PathDraftError, ValueError):
                    continue
                cached = (previous, candidate)
                break
        if cached:
            from types import SimpleNamespace
            cached_call, cached_output = cached
            validate_batch(cached_output)
            result = SimpleNamespace(call_id=cached_call.id, structured_output=cached_output)
        validation_feedback = ""
        for attempt in range(2):
            if result is not None:
                break
            request_payload = dict(payload)
            if attempt:
                request_payload["retry_instruction"] = "上一批输出未通过校验。请只输出分配章节的实际 plan.nodes JSON，不要输出 Schema 定义。"
                request_payload["validation_feedback"] = validation_feedback
            try:
                result = await execute_registered_structured_call(
                    session, backend=llm, capability=Capability.PLAN,
                    system_prompt=system_prompt,
                    user_prompt=json.dumps(request_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    role="诊断结果个性化路径规划",
                    operation="p1_b11_personalized_learning_path_batch",
                    response_model=PathDraftModelOutput,
                    owner_public_id=user.public_id, course_id=course.id,
                    output_constraints=OutputConstraints(language="auto", format="json", max_length=14000, source_scope=tuple(sorted(facts["sources"])), safety_boundary="仅可使用当前课程和授权来源；不发布未确认草稿。"),
                    response_validator=validate_batch,
                )
                break
            except M5CapabilityError as exc:
                validation_feedback = str(exc.__cause__ or exc)
                if exc.code == "structured_output_invalid" and attempt == 0:
                    continue
                raise PathDraftError("path_draft_model_failed", "真实模型未能完成完整课程路径的分批定制，请稍后重试。") from exc
        if result is None:
            _fail("path_draft_model_failed", "真实模型未能完成完整课程路径的分批定制，请稍后重试。")
        parsed = validate_batch(result.structured_output or {})
        if not cached:
            call = session.get(DBModelCall, result.call_id)
            if call is not None:
                call.input_summary = {**(call.input_summary or {}), "path_batch_result": {
                    "input_hash": batch_hash, "candidate_basis_hash": candidate_basis,
                    "output": parsed.model_dump(mode="json"), "task_id": current_path_task_id()}}
                # The gateway already commits calls individually. Preserve the public
                # validated plan for retry before proceeding to another model batch.
                session.commit()
        call = session.get(DBModelCall, result.call_id)
        if call is None:
            _fail("path_draft_model_audit_missing", "路径生成记录尚未保存，请重试。")
        if exact_cached and not (call.input_summary.get('path_batch_result') or {}).get('candidate_basis_hash'):
            # An exact legacy input match proves the basis; never guess it for
            # an older draft whose complete input can no longer be reproduced.
            call.input_summary = {**call.input_summary, 'path_batch_result': {
                **call.input_summary['path_batch_result'], 'candidate_basis_hash': candidate_basis}}
            session.commit()
        if progress:
            progress({"stage": "review", "completed": batch_index, "total": len(tasks)})
        review_payload = payload
        if cached and not exact_cached:
            review_payload = {**payload, 'candidate_reuse': {
                'original_input_hash': call.input_summary['path_batch_result']['input_hash'],
                'current_input_hash': batch_hash,
                'instruction': '这是同一学习者、资料与任务范围的已保存候选；之前的学习安排或全课版本已变化。'
                    '按当前earlier_learning_steps、累计时长和本批原文重新核对并修订衔接、先修、阶段成果与数据/模型状态；旧审核结论不代表本次通过。'}}
        parsed, review_call_id = await _review_path_batch(
            session, llm=llm, user=user, course=course, payload=review_payload,
            candidate=parsed, generator_call=call, validate_batch=validate_batch,
        )
        review_call_ids.append(review_call_id)
        grouped = _task_node_groups(parsed, assigned)
        batch_nodes = []
        for item in assigned:
            previous = None
            for node in grouped[item["node_key"]]:
                before = [previous] if previous else [task_tails[key] for key in item["prerequisites"]]
                batch_nodes.append(node.model_copy(update={
                    "prerequisites": tuple(before),
                    "knowledge_point_ids": node.knowledge_point_ids or tuple(item["knowledge_point_ids"]),
                    "teaching_goal": node.teaching_goal or item["teaching_goal"],
                }))
                previous = node.node_key
            task_tails[item["node_key"]] = previous
        all_nodes.extend(batch_nodes)
        assumptions.extend(value for value in parsed.plan.assumptions if value and value not in assumptions)
        model_goals.append(parsed.plan.goal)
        summaries.append(parsed.personalization_summary)
        call_ids.append(result.call_id)
        if progress:
            progress({"stage": "saved", "completed": batch_index + len(assigned), "total": len(tasks)})
    if progress:
        progress({"stage": "summary", "completed": len(tasks), "total": len(tasks)})
    overview, overview_call_id = await _summarize_full_path(
        session, llm=llm, user=user, course=course,
        context=_path_model_context(facts, course=course, profile=profile, snapshot=snapshot,
                                    time_budget_minutes=time_budget_minutes),
        nodes=all_nodes, batch_notes={"goals": model_goals, "assumptions": assumptions, "summaries": summaries},
    )
    positions = {node.node_key: index for index, node in enumerate(all_nodes, 1)}
    stage_notes = []
    start = 1
    for stage in overview.stages:
        end = positions[stage.end_node_key]
        stage_notes.append(f"{start}–{end} · {stage.title}：{stage.outcome}")
        start = end + 1
    merged = PlanSpec(
        schema_version="m5.plan.v1",
        goal=overview.goal,
        assumptions=tuple(stage_notes) + overview.assumptions,
        nodes=tuple(all_nodes),
    )
    final = PathDraftModelOutput(
        plan=merged,
        personalization_summary=overview.personalization_summary,
    )
    _validate_model_plan_output(
        final.model_dump(mode="json"), facts=facts, owner_public_id=user.public_id,
        course_id=course.id, session=session, require_full_coverage=True,
    )
    return final, {"status": "completed", "call_id": call_ids[-1], "call_ids": call_ids,
                   "sequence_call_id": sequence_call_id,
                   "review_call_ids": review_call_ids, "overview_call_id": overview_call_id,
                   "model": "deepseek-v4-flash", "prompt_version": "p1_b11_personalized_learning_path_batch:1.0",
                   "personalization_summary": final.personalization_summary}


def _latest_path_generation(
    session: Any, *, owner_public_id: str, course_id: str,
) -> dict[str, Any] | None:
    row = session.query(DBModelCall).filter_by(
        owner_public_id=owner_public_id, course_id=course_id,
        capability=Capability.PLAN.value,
    ).order_by(DBModelCall.created_at.desc(), DBModelCall.id.desc()).first()
    if row is None:
        return None
    return {
        "status": row.status,
        "call_id": row.id,
        "provider": row.provider,
        "model": row.model,
        "error_code": row.error_code or None,
        "prompt_version": row.prompt_version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _prerequisite_closure(knowledge: dict[str, DBKnowledgePoint], targets: list[str]) -> set[str]:
    selected: set[str] = set()

    def visit(kp_id: str) -> None:
        if kp_id in selected or kp_id not in knowledge:
            return
        for prerequisite in knowledge[kp_id].prerequisites or []:
            visit(str(prerequisite))
        selected.add(kp_id)

    for target in targets:
        visit(target)
    return selected


def _draft_spec(
    facts: dict[str, Any], *, snapshot: dict[str, Any], time_budget_minutes: int,
) -> tuple[PlanSpec, dict[str, str]]:
    weak_ids = [str(item) for item in snapshot.get("weak_knowledge_point_ids") or []]
    mastered_ids = {str(item) for item in snapshot.get("mastered_knowledge_point_ids") or []}
    available_weak = [item for item in weak_ids if item in facts["chapter_by_kp"]]
    if not available_weak:
        available_weak = [
            kp.id for chapter in facts["chapters"]
            for kp in facts["kp_by_chapter"].get(chapter.id, [])
            if kp.id not in mastered_ids
        ][:1]
    selected_kps = _prerequisite_closure(facts["knowledge"], available_weak)
    selected_kps -= mastered_ids
    selected_chapter_ids = {
        facts["chapter_by_kp"][kp_id].id for kp_id in selected_kps
        if kp_id in facts["chapter_by_kp"]
    }
    ordered = [item for item in facts["chapters"] if item.id in selected_chapter_ids]
    if ordered:
        last_position = max(item.position for item in ordered)
        successor = next((item for item in facts["chapters"] if item.position > last_position), None)
        if successor is not None:
            ordered.append(successor)
    ordered = ordered[:6]
    if not ordered:
        _fail("path_draft_evidence_missing", "课程缺少可用于路径草稿的章节与画像证据")

    minutes = max(10, min(30, time_budget_minutes // len(ordered)))
    key_by_chapter = {item.id: f"textbook-{item.id}" for item in ordered}
    selected_ids = set(key_by_chapter)
    reasons: dict[str, str] = {}
    nodes = []
    target_difficulty = float(snapshot.get("difficulty_target") or 0.48)
    for index, chapter in enumerate(ordered):
        chapter_kps = facts["kp_by_chapter"].get(chapter.id, [])
        kp = chapter_kps[0] if chapter_kps else None
        prerequisite_keys = []
        if kp is not None:
            for prerequisite in kp.prerequisites or []:
                prerequisite_chapter = facts["chapter_by_kp"].get(str(prerequisite))
                if prerequisite_chapter and prerequisite_chapter.id in selected_ids:
                    prerequisite_keys.append(key_by_chapter[prerequisite_chapter.id])
        if kp and kp.id in available_weak:
            reason = "画像薄弱点：优先补齐当前课程证据不足或答题暴露的知识点。"
        elif kp and kp.id in selected_kps:
            reason = "薄弱点先修：先补齐教材中的前置知识，再进入目标章节。"
        else:
            reason = "巩固后衔接：完成薄弱点后进入相邻教材章节，验证迁移能力。"
        reasons[key_by_chapter[chapter.id]] = reason
        nodes.append(PlanNodeSpec(
            node_key=key_by_chapter[chapter.id],
            node_type="chapter",
            target_object_id=chapter.id,
            title=chapter.title,
            prerequisites=tuple(prerequisite_keys),
            resource_status="existing",
            estimate_min_minutes=minutes,
            estimate_max_minutes=minutes,
            difficulty=round(max(0.2, min(0.85, target_difficulty + index * 0.04)), 3),
            rationale=reason,
        ))
    assumptions = (
        "只使用当前课程的真实章节、canonical 来源和已记录画像证据。",
        "薄弱点与先修关系只影响草稿排序，不等同课程总评或专家结论。",
        f"本轮可用时间预算为 {time_budget_minutes} 分钟。",
    )
    return PlanSpec(
        goal="补齐当前薄弱知识点，并沿教材先修关系进入下一可验证章节",
        assumptions=assumptions,
        nodes=tuple(nodes),
    ), reasons


def _find_plan(session: Any, *, owner_public_id: str, course_id: str) -> DBPlanDraft | None:
    plans = session.query(DBPlanDraft).filter_by(
        owner_public_id=owner_public_id, course_id=course_id,
    ).filter(DBPlanDraft.archived_at.is_(None)).order_by(
        DBPlanDraft.updated_at.desc(), DBPlanDraft.id.desc(),
    ).all()
    pending = next((item for item in plans if item.status == "replan_pending"), None)
    if pending is not None:
        return pending
    active_path = session.query(DBLearningPath).filter(
        DBLearningPath.owner_public_id == owner_public_id,
        DBLearningPath.course_id == course_id,
        DBLearningPath.status.in_(("active", "paused")),
    ).order_by(DBLearningPath.updated_at.desc(), DBLearningPath.id.desc()).first()
    if active_path is not None:
        source_version = session.get(DBPlanVersion, active_path.source_plan_version_id)
        active_plan = session.get(DBPlanDraft, source_version.plan_draft_id) if source_version else None
        if active_plan is not None and active_plan.archived_at is None:
            return active_plan
    return plans[0] if plans else None


def generate_textbook_path_draft(
    session: Any, *, current_user: DBUser, course_id: str, time_budget_minutes: int | None,
    profile_snapshot_id: str | None = None, idempotency_key: str | None = None,
    llm: Any | None = None, full_coverage: bool = False, progress=None,
    learning_snapshot: dict[str, Any] | None = None,
) -> tuple[DBPlanDraft, bool]:
    course = session.query(DBCourse).filter_by(id=course_id).first()
    if course is None:
        _fail("course_not_found", "课程不存在")
    _authorize(session, current_user=current_user, course=course)
    profile = _latest_profile(
        session, owner_public_id=current_user.public_id, course_id=course_id,
        profile_snapshot_id=profile_snapshot_id,
    )
    if profile is None:
        _fail("path_draft_profile_missing", "尚无可用于路径草稿的课程画像")
    facts = _course_facts(session, course_id=course_id)
    # Background requests freeze their learner inputs at submission. Continued
    # learning while a long path runs must not restart its already saved work.
    snapshot = deepcopy(learning_snapshot) if learning_snapshot is not None else _path_learning_snapshot(
        session, user=current_user, course_id=course_id,
        profile=profile, use_current=not bool(profile_snapshot_id))
    if time_budget_minutes is None:
        from app.profile_adaptation import confirmed_study_minutes
        time_budget_minutes = confirmed_study_minutes(snapshot) or 90
    learning_input_hash = hashlib.sha256(json.dumps(_path_model_context(
        facts, course=course, profile=profile, snapshot=snapshot, time_budget_minutes=time_budget_minutes,
    ) | {"path_scope_version": PATH_PLANNING_REVISION,
         "path_overview": PATH_OVERVIEW_INSTRUCTION if full_coverage else None,
         "path_sequence": PATH_SEQUENCE_INSTRUCTION if full_coverage else None,
         "teaching_review": hashlib.sha256(PATH_REVIEW_INSTRUCTION.encode()).hexdigest()},
        ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    plan = (
        session.query(DBPlanDraft).filter_by(
            owner_public_id=current_user.public_id,
            idempotency_key=idempotency_key,
        ).first()
        if idempotency_key else
        _find_plan(session, owner_public_id=current_user.public_id, course_id=course_id)
    )
    call_summary = {
        "profile_snapshot_id": profile.id,
        "learning_input_hash": learning_input_hash,
        "time_budget_minutes": int(time_budget_minutes),
        "idempotency_key": idempotency_key,
    }
    if plan is not None and plan.status in {"draft", "replan_pending", "confirmed"}:
        current = session.get(DBPlanVersion, plan.current_version_id)
        matching_call = next(
            (
                item for item in session.query(DBModelCall).filter_by(
                    owner_public_id=current_user.public_id,
                    course_id=course_id,
                    capability=Capability.PLAN.value,
                    status="completed",
                ).filter(DBModelCall.prompt_version.in_((
                    "p1_b11_personalized_learning_path:1.0", "p1_b11_personalized_learning_path_batch:1.0",
                ))).order_by(DBModelCall.created_at.desc(), DBModelCall.id.desc()).all()
                if (item.input_summary or {}).get("profile_snapshot_id") == profile.id
                and (item.input_summary or {}).get("learning_input_hash") == learning_input_hash
                and (item.input_summary or {}).get("time_budget_minutes") == int(time_budget_minutes)
                and (not idempotency_key or (item.input_summary or {}).get("idempotency_key") == idempotency_key)
            ),
            None,
        )
        current_chapters = {node.get("target_object_id") for node in (current.content or {}).get("nodes", []) if node.get("node_type") == "chapter"} if current is not None else set()
        scope_matches = not full_coverage or {task['target_object_id'] for task in _full_course_tasks(facts)}.issubset(current_chapters)
        if current is not None and current.profile_snapshot_id == profile.id and matching_call is not None and scope_matches:
            return plan, False
    backend = _path_output_budget(llm or _build_path_model())
    from app.learning_generation_jobs import course_generation_basis, assert_course_generation_basis
    basis_scope = {'course_id':course_id, 'owner_public_id':current_user.public_id,
                   'profile_snapshot_id':profile_snapshot_id}
    basis = course_generation_basis(session, **basis_scope)
    try:
        generated, generation_meta = _run_model_sync(lambda: _generate_model_path(
            session,
            llm=backend,
            user=current_user,
            course=course,
            profile=profile,
            snapshot=snapshot,
            facts=facts,
            time_budget_minutes=time_budget_minutes,
            idempotency_key=idempotency_key,
            full_coverage=full_coverage,
            progress=progress,
        ))
    except PathDraftError:
        raise
    from app.learning_generation_jobs import assert_generation_owner
    assert_generation_owner(session)
    assert_course_generation_basis(session, basis, **basis_scope)
    spec = generated.plan
    payload = spec.model_dump(mode="json")
    model_call = session.get(DBModelCall, generation_meta.get("call_id"))
    if model_call is not None and (
        model_call.owner_public_id != current_user.public_id
        or model_call.course_id != course_id
        or model_call.status != "completed"
    ):
        model_call = None
    if model_call is None:
        _fail("path_draft_model_audit_missing", "路径模型调用没有留下可追溯审计记录，请重试。")
    model_call.input_summary = {**(model_call.input_summary or {}), **call_summary,
                               "overview_call_id": generation_meta.get("overview_call_id"),
                               "sequence_call_id": generation_meta.get("sequence_call_id"),
                               "review_call_ids": generation_meta.get("review_call_ids", [])}
    for review_id in [*generation_meta.get("review_call_ids", []), generation_meta.get("overview_call_id"),
                      generation_meta.get("sequence_call_id")]:
        if not review_id:
            continue
        review_call = session.get(DBModelCall, review_id)
        if review_call is not None:
            review_call.input_summary = {**(review_call.input_summary or {}), **call_summary}
    if plan is None:
        plan, _, created = create_plan_draft(
            session,
            owner_public_id=current_user.public_id,
            course_id=course_id,
            title=f"{course.title} · 诊断定制路径",
            idempotency_key=idempotency_key or f"r3-04:{current_user.public_id}:{course_id}",
            spec=spec,
            profile_snapshot_id=profile.id,
        )
        return plan, created
    propose_plan_revision(
        session,
        plan=plan,
        owner_public_id=current_user.public_id,
        expected_lock_version=plan.lock_version,
        spec=spec,
        profile_snapshot_id=profile.id,
    )
    return plan, True


def _node_projection(
    facts: dict[str, Any], *, node: dict[str, Any], reasons: dict[str, str], weak_ids: set[str],
    names: dict[str, str] | None = None,
) -> dict[str, Any]:
    names = {**{item.id: item.title for item in facts["chapters"]},
             **{kp.id: kp.title for points in facts["kp_by_chapter"].values() for kp in points},
             **(names or {})}
    # A reviewer may refer to a sibling stage as "part-1". Resolve that
    # shorthand only inside this teaching unit; other units reuse the suffix.
    stage = re.fullmatch(r"(.+-)(part-[1-9][0-9]*)", str(node.get("node_key") or ""))
    if stage:
        names.update({key[len(stage[1]):]: title for key, title in list(names.items())
                      if key.startswith(stage[1]) and re.fullmatch(r"part-[1-9][0-9]*", key[len(stage[1]):])})
    # Read projection only: keep model drafts and all linking keys unchanged.
    node = {**node, **{key: teacher_text(node.get(key), names=names)
                       for key in ("title", "teaching_goal", "rationale", "extension_reason")}}
    chapter = next((item for item in facts["chapters"] if item.id == node.get("target_object_id")), None)
    if chapter is None:
        return {**node, "chapter": None, "source": None, "knowledge_points": [], "reason": "保留既有非教材任务。"}
    source = facts["sources"].get(chapter.source_document_id)
    source_ref = facts["ref_by_chapter"].get(chapter.id)
    kps = facts["kp_by_chapter"].get(chapter.id, [])
    if node.get("knowledge_point_ids"):
        kps = [point for point in kps if point.id in node["knowledge_point_ids"]]
    reason = teacher_text(node.get("rationale") or reasons.get(str(node.get("node_key")), "按当前学习安排继续。"), names=names)
    if node.get("prerequisites"):
        reason = f"{reason} 开始前，请先完成前面安排的基础内容。"
    return {
        **node,
        "chapter": {"id": chapter.id, "title": chapter.title, "position": chapter.position},
        "source": {
            "document_id": source.id if source else chapter.source_document_id,
            "title": source.title if source else "课程教材",
            "filename": source.filename if source else "",
            "license": source.license_text if source else "",
            "content_hash": source.content_hash if source else "",
            "source_ref_id": source_ref.id if source_ref else None,
            "route": f"/knowledge?course_id={chapter.course_id}&chapter_id={chapter.id}",
        },
        "knowledge_points": [
            {"id": kp.id, "title": kp.title, "is_weak": kp.id in weak_ids}
            for kp in kps
        ],
        "reason": reason,
    }


def textbook_path_draft_payload(
    session: Any, *, current_user: DBUser, course_id: str, profile_snapshot_id: str | None = None,
    plan_id: str | None = None,
) -> dict[str, Any]:
    course = session.query(DBCourse).filter_by(id=course_id).first()
    if course is None:
        _fail("course_not_found", "课程不存在")
    _authorize(session, current_user=current_user, course=course)
    profile = _latest_profile(
        session, owner_public_id=current_user.public_id, course_id=course_id,
        profile_snapshot_id=profile_snapshot_id,
    )
    snapshot = dict(profile.snapshot or {}) if profile else {}
    weak_ids = {str(item) for item in snapshot.get("weak_knowledge_point_ids") or []}
    facts = _course_facts(session, course_id=course_id)
    if plan_id:
        plan = session.query(DBPlanDraft).filter_by(id=plan_id, owner_public_id=current_user.public_id,
            course_id=course_id, archived_at=None).one_or_none()
        if plan is None:
            _fail("path_draft_not_found", "没有找到这份学习安排，请从课程或诊断报告重新打开。")
        selected_version = session.get(DBPlanVersion, plan.current_version_id)
        if selected_version and selected_version.profile_snapshot_id:
            profile = _latest_profile(session, owner_public_id=current_user.public_id, course_id=course_id,
                                      profile_snapshot_id=selected_version.profile_snapshot_id)
            snapshot = dict(profile.snapshot or {}) if profile else {}
            weak_ids = {str(item) for item in snapshot.get("weak_knowledge_point_ids") or []}
    elif profile_snapshot_id:
        plan = (
            session.query(DBPlanDraft)
            .join(DBPlanVersion, DBPlanVersion.plan_draft_id == DBPlanDraft.id)
            .filter(
                DBPlanDraft.owner_public_id == current_user.public_id,
                DBPlanDraft.course_id == course_id,
                DBPlanDraft.archived_at.is_(None),
                DBPlanVersion.profile_snapshot_id == profile_snapshot_id,
                DBPlanVersion.id == DBPlanDraft.current_version_id,
            )
            .order_by(DBPlanDraft.updated_at.desc(), DBPlanDraft.id.desc())
            .first()
        )
    else:
        plan = _find_plan(session, owner_public_id=current_user.public_id, course_id=course_id)
    if plan is None:
        generation = _latest_path_generation(
            session, owner_public_id=current_user.public_id, course_id=course_id,
        ) or {"status": "not_started", "model": None}
        if generation["status"] == "completed":
            # A completed model batch is not a completed course path.
            generation = {**generation, "status": "partial"}
        return {
            "schema_version": "r3.diagnostic-personalized-path-draft.v2",
            "course": {"id": course.id, "title": course.title, "version": course.version},
            "state": "not_generated",
            "plan": None,
            "nodes": [],
            "diff": None,
            "generation": generation,
            "boundary": "完成诊断并取得当前课程画像后，路径才会由真实模型定制；用户确认前仅为草稿。",
        }
    current = session.get(DBPlanVersion, plan.current_version_id)
    confirmed = session.get(DBPlanVersion, plan.confirmed_version_id) if plan.confirmed_version_id else None
    # Persisted demo paths may predate the strict m5.plan.v1 schema. Normalize
    # the legacy envelope at this read boundary so a valid course cannot be
    # blocked by textbook-path-draft validation.
    # Current-schema plans may legitimately include resource/assessment tasks.
    # Only legacy model envelopes need chapter-based normalization.
    try:
        spec = PlanSpec.model_validate(current.content)
    except ValidationError:
        normalized_content = _coerce_model_payload(current.content, facts=facts)
        spec = PlanSpec.model_validate(normalized_content["plan"])
    _, reasons = _draft_spec(facts, snapshot=snapshot, time_budget_minutes=sum(
        int(item.estimate_max_minutes) for item in spec.nodes
    )) if current.profile_snapshot_id == (profile.id if profile else None) else (spec, {})
    diff = plan_version_diff(confirmed, current) if confirmed and confirmed.id != current.id else None
    title_by_key = {item.node_key: item.title for item in spec.nodes}
    from app.path_scope import plan_step_names
    display_names = {**{item.id: item.title for item in facts["chapters"]},
                     **{kp.id: kp.title for points in facts["kp_by_chapter"].values() for kp in points},
                     **plan_step_names(spec.model_dump())}
    diff_payload = None if diff is None else {
        **diff,
        "added_titles": [title_by_key.get(item, item) for item in diff["added"]],
        "removed_count": len(diff["removed"]),
        "moved_count": len(diff["moved"]),
        "changed_count": len(diff["changed"]),
        "summary": f"新增 {len(diff['added'])} 项，移除 {len(diff['removed'])} 项，调整顺序 {len(diff['moved'])} 项，修改 {len(diff['changed'])} 项。",
    }
    generation = _latest_path_generation(
        session, owner_public_id=current_user.public_id, course_id=course_id,
    )
    return {
        "schema_version": "r3.diagnostic-personalized-path-draft.v2",
        "course": {"id": course.id, "title": course.title, "version": course.version},
        "state": "draft_ready" if plan.status in {"draft", "replan_pending"} else "confirmed",
        "plan": {
            "id": plan.id,
            "title": plan.title,
            "status": plan.status,
            "lock_version": plan.lock_version,
            "current_version_id": plan.current_version_id,
            "confirmed_version_id": plan.confirmed_version_id,
            "version_number": current.version_number,
            "profile_snapshot_id": current.profile_snapshot_id,
            "goal": teacher_text(spec.goal, names=display_names),
            "assumptions": [teacher_text(item, names=display_names) for item in spec.assumptions],
            "total_min_minutes": sum(int(item.estimate_min_minutes) for item in spec.nodes),
            "total_minutes": sum(int(item.estimate_max_minutes) for item in spec.nodes),
        },
        "nodes": [
            _node_projection(
                facts, node=item.model_dump(mode="json"), reasons=reasons, weak_ids=weak_ids,
                names=display_names,
            )
            for item in spec.nodes
        ],
        "diff": diff_payload,
        "evidence": {
            "profile_snapshot_id": profile.id if profile else None,
            "weak_knowledge_point_ids": sorted(weak_ids),
            "chapter_count": len(facts["chapters"]),
            "canonical_source_count": len(facts["sources"]),
        },
        "generation": generation or {
            "status": "legacy",
            "model": None,
            "message": "这是已有路径版本，未记录新的模型定制调用。",
        },
        "boundary": "路径由当前初始学情、目标、偏好、时间和课程图谱定制；用户确认前仅为草稿。模型失败不会用模板冒充成功，旧正式路径仍可读取。",
    }
