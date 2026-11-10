"""Choose an early learning outcome inside the existing full-course path."""

from copy import deepcopy
import hashlib
import json

from pydantic import Field

from app.database import DBModelCall, DBGenerationTask, DBTaskEvent
from app.m2_contracts import StrictModel
from app.m5_capabilities import Capability, M5CapabilityError, OutputConstraints
from app.m5_gateway import execute_registered_structured_call


class EarlyLearningTask(StrictModel):
    task_key: str
    knowledge_point_ids: tuple[str, ...] = Field(min_length=1)
    teaching_goal: str = Field(min_length=1)


class PathSequenceOutput(StrictModel):
    near_term_outcome: str = Field(min_length=1)
    early_tasks: tuple[EarlyLearningTask, ...] = ()
    basis: str = Field(min_length=1)


PATH_SEQUENCE_INSTRUCTION = (
    "你是课程教学设计者。先为当前学习者选择最早有用的学习成果，再安排完整课程。只输出Schema要求的JSON。"
    "结合已确认目标、分项基础、具体诊断、持续学习、工具与单次时间，选择early_tasks；职业或学历不能代表掌握。"
    "near_term_outcome必须是学习者能实际完成和检查的成果，basis说明选择依据，不许编造学过、做过或已掌握。"
    "从course_tasks选择实现该成果所需的少量任务，按希望学习的顺序列出；无明确优先目标时可留空并说明依据。"
    "每项task_key必须来自输入，knowledge_point_ids只能选该任务的知识范围；不新增课程外内容。"
    "一个教学单元若同时含预测解释、损失计算和训练实现，可选其中能先学的知识子集，后续仍会保留其余内容。"
    "同一任务可分次选不同知识子集，不能重复选择同一点；不为凑差异拆碎一切。"
    "系统按原知识先修自动补齐必需任务，不能假定选择顺序能跳过先修，也不能把未测基础当会。"
    "不要机械地把全部数学和全部编程准备排在首个应用之前。已会读表、比例或均值时，"
    "可用给定数据与预测先解释损失、验证与选择，再逐步实现训练；明确此阶段是输出分析，不冒称训练模型。"
    "能实际实现的学习者可以用已有编程能力做小实验，但具体统计误解仍须解决；不能统一退为看表或纸上讨论。"
    "比较模型时先只给训练与验证结果，学习者保存选择及理由后才展示所选模型的测试结果；不能先展示全部测试分数再要求忽略。"
    "只将原作答/评分明确支持的问题写成已发现缺口；尚未教过的记号或主动设计的自查项目不能反写成诊断已犯的错误。"
    "teaching_goal写当前范围内要做什么、交付什么和怎样检查；区分已给模型输出的比较与自主拟合后的实验。"
    "保留共同专业核心和独立检查标准；浅层类比不是最终成果，强者也不只增加术语。"
    "其余所有课程任务会继续保留；本次不用列全课，不计算周数，不生成教学正文或答案。"
    "目录仅用于选择，随后每批规划和复核会拿实际原文核验。不要把目录标题当作已读到的事实依据。"
)


def order_course_tasks(tasks, knowledge, *, priorities=()):
    """Respect conceptual prerequisites while bringing a goal's ancestors forward."""
    tasks = deepcopy(tasks)
    by_point = {}
    for task in tasks:
        task['prerequisites'] = []
        for key in task['knowledge_point_ids']:
            by_point.setdefault(key, []).append(task)
    for task in tasks:
        for key in task['knowledge_point_ids']:
            for before in knowledge[key].prerequisites or []:
                if before in task['knowledge_point_ids']:
                    continue
                candidates = [item for item in by_point.get(before, []) if item is not task]
                if candidates:
                    dependency = candidates[0]['node_key']
                    if dependency not in task['prerequisites']:
                        task['prerequisites'].append(dependency)
    by_key = {task['node_key']: task for task in tasks}
    ordered, seen, visiting = [], set(), set()

    def visit(key):
        if key in seen:
            return
        if key in visiting:
            raise ValueError('教学单元的先修顺序互相冲突，请在课程结构中调整知识点分组。')
        visiting.add(key)
        for before in by_key[key]['prerequisites']:
            visit(before)
        visiting.remove(key)
        seen.add(key)
        ordered.append(by_key[key])

    for key in priorities:
        visit(key)
    # Preserve the existing stable catalogue order among the other ready tasks.
    while len(seen) < len(tasks):
        ready = next((t for t in tasks if t['node_key'] not in seen and set(t['prerequisites']) <= seen), None)
        if ready is None:
            raise ValueError('教学单元的先修顺序互相冲突，请在课程结构中调整知识点分组。')
        visit(ready['node_key'])
    return ordered


def apply_task_sequence(tasks, knowledge, output):
    originals = {task['node_key']: task for task in tasks}
    selected, consumed = [], {}

    def scoped(task, points, goal):
        item = deepcopy(task)
        item['knowledge_point_ids'] = [p for p in task['knowledge_point_ids'] if p in points]
        item['teaching_goal'] = goal
        if set(points) != set(task['knowledge_point_ids']):
            digest = hashlib.sha256(json.dumps(sorted(points)).encode()).hexdigest()[:16]
            item['node_key'] = task['node_key'] + '-scope-' + digest
        return item

    for selection in output.early_tasks:
        original = originals.get(selection.task_key)
        points = set(selection.knowledge_point_ids)
        if original is None or not points <= set(original['knowledge_point_ids']):
            raise ValueError('近期任务须选择当前课程已有任务及其知识范围。')
        used = consumed.setdefault(selection.task_key, set())
        if len(points) != len(selection.knowledge_point_ids) or used & points:
            raise ValueError('同一任务的近期知识范围不能重复安排。')
        used.update(points)
        selected.append(scoped(original, points, selection.teaching_goal))
    # Prerequisites belong to concepts, not every other concept in the same
    # chapter. Pulling the whole loss+gradient unit would reintroduce calculus
    # before an output-comparison task even when the model chose that task well.
    needed = set()
    def require(point):
        if point in needed or point not in knowledge:
            return
        needed.add(point)
        for before in knowledge[point].prerequisites or []:
            require(before)
    for task in selected:
        for point in task['knowledge_point_ids']:
            require(point)
    selected_points = {p for task in selected for p in task['knowledge_point_ids']}
    early_points = set(selected_points)
    preparation_scopes = {}
    for original in tasks:
        points = set(original['knowledge_point_ids']) & (needed - selected_points)
        if points:
            # Keep adjacent basics together when that adds no further
            # prerequisite chain; splitting every easy concept adds needless work.
            available = (needed - early_points) | points
            changed = True
            while changed:
                changed = False
                for point in original['knowledge_point_ids']:
                    if point not in points and point not in consumed.get(original['node_key'], set()) and set(knowledge[point].prerequisites or []) <= available:
                        points.add(point)
                        available.add(point)
                        changed = True
            preparation_scopes[original['node_key']] = points
            selected_points.update(points)
    preparations = []
    for key, points in preparation_scopes.items():
        original = originals[key]
        consumed.setdefault(key, set()).update(points)
        names = '、'.join(knowledge[p].title for p in original['knowledge_point_ids'] if p in points)
        preparations.append(scoped(original, points,
            f"围绕近期任务核对{names}；依据已有作答补足具体缺口，已经掌握的内容简短核对后进入应用。"))
    remaining = []
    for original in tasks:
        used = consumed.get(original['node_key'], set())
        if not used:
            remaining.append(deepcopy(original))
            continue
        points = set(original['knowledge_point_ids']) - used
        if points:
            names = '、'.join(knowledge[key].title for key in original['knowledge_point_ids'] if key in points)
            earlier = '、'.join(knowledge[key].title for key in original['knowledge_point_ids'] if key in used)
            goal = str(original.get('teaching_goal') or '').strip().rstrip('。')
            # Splitting out an early prediction/interpretation task must not
            # erase the unit's later implementation and verification outcome.
            # Earlier items are scheduled learning, not evidence of mastery.
            remaining.append(scoped(original, points,
                f"本段继续学习{names}，承接前面已安排的{earlier}。"
                + (f"完成本单元原定成果：{goal}。" if goal else "完成当前知识范围的实际任务并独立检查结果。")
                + "沿用前段产出并补齐本段操作，不重复前段教学，也不把已安排当作已经掌握。"))
    return order_course_tasks(selected + preparations + remaining, knowledge,
                              priorities=[task['node_key'] for task in selected])


def saved_task_path_calls(session, *, user, course, field):
    """Locate this request's saved work, including pre-linkage call records.

    Legacy calls are tied to this task by its validated public component output,
    never by a matching title or another learner's results. Batch candidates
    remain subject to the current source/runtime and teaching review.
    """
    from app.learning_generation_jobs import CURRENT_JOB
    current = CURRENT_JOB.get() or {}
    task = session.get(DBGenerationTask, current.get('task_id')) if current.get('task_id') else None
    if not task or task.capability != 'path.prepare' or (task.owner_public_id, task.course_id) != (user.public_id, course.id):
        return []
    def encode(value):
        try:
            if field == 'path_sequence_result':
                value = PathSequenceOutput.model_validate(value).model_dump(mode='json')
            else:
                from app.path_draft import PathDraftModelOutput
                value = deepcopy(value)
                for node in (value.get('plan') or {}).get('nodes', []):
                    if isinstance(node, dict):
                        node['prerequisites'] = []
                value = PathDraftModelOutput.model_validate(value).model_dump(mode='json')
                # Batch validation applies teaching order and builds edges
                # itself. Ignore only these deterministic normalizations.
                value['plan']['nodes'].sort(key=lambda node: node['node_key'])
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except ValueError:
            return None
    outputs = {encode(row.payload['value']['output']) for row in session.query(DBTaskEvent).filter_by(
        task_id=task.id, event_type='learning_generation.component')
        if (row.payload.get('value') or {}).get('valid') and 'output' in row.payload['value']}
    outputs.discard(None)
    return [call for call in session.query(DBModelCall).filter_by(owner_public_id=user.public_id,
        course_id=course.id, capability=Capability.PLAN.value, status='completed').order_by(DBModelCall.created_at)
        if (saved := (call.input_summary or {}).get(field)) and saved.get('output')
        and (saved.get('task_id') == task.id or encode(saved['output']) in outputs)]


def current_path_task_id():
    from app.learning_generation_jobs import CURRENT_JOB
    return (CURRENT_JOB.get() or {}).get('task_id')


async def prepare_task_sequence(session, *, llm, user, course, context, tasks, knowledge):
    """Persist the model choice on the existing call record; retries reuse it."""
    from llm_client import for_answer_step
    llm = for_answer_step(llm, deep_reasoning=True, reasoning_effort='high')
    request = {
        'context': {key: value for key, value in context.items() if key not in {'course_graph', 'teaching_units'}},
        'sources': context['course_graph']['sources'],
        'course_tasks': tasks,
        'knowledge': [{'id': key, 'title': point.title, 'prerequisites': point.prerequisites or []}
                      for key, point in knowledge.items()],
        'output_schema': PathSequenceOutput.model_json_schema(),
    }
    input_hash = hashlib.sha256(json.dumps({
        'instruction': PATH_SEQUENCE_INSTRUCTION, 'input': request,
        'model': llm.model, 'thinking': llm.thinking_mode, 'reasoning': llm.reasoning_effort,
    }, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def validate(value):
        output = PathSequenceOutput.model_validate(value)
        apply_task_sequence(tasks, knowledge, output)
        return output

    # A deployment changes model/runtime instructions, not the learner's
    # already selected outcome. Preserve that choice within this request;
    # current full batch review still checks feasibility and teaching quality.
    for call in saved_task_path_calls(session, user=user, course=course, field='path_sequence_result'):
        try:
            output = validate(call.input_summary['path_sequence_result']['output'])
        except ValueError:
            continue  # A changed catalogue can invalidate an old task scope.
        return apply_task_sequence(tasks, knowledge, output), output, call.id

    for call in session.query(DBModelCall).filter_by(owner_public_id=user.public_id,
            course_id=course.id, capability=Capability.PLAN.value, status='completed').order_by(DBModelCall.created_at.desc()).all():
        saved = (call.input_summary or {}).get('path_sequence_result') or {}
        if saved.get('input_hash') == input_hash and saved.get('output'):
            output = validate(saved['output'])
            return apply_task_sequence(tasks, knowledge, output), output, call.id
    feedback = ''
    for attempt in range(2):
        try:
            result = await execute_registered_structured_call(
                session, backend=llm, capability=Capability.PLAN,
                system_prompt=PATH_SEQUENCE_INSTRUCTION,
                user_prompt=json.dumps({**request, **({'validation_feedback': feedback} if feedback else {})}, ensure_ascii=False, sort_keys=True),
                role='近期学习成果安排', operation='p1_b11_learning_path_sequence',
                response_model=PathSequenceOutput, response_validator=validate,
                owner_public_id=user.public_id, course_id=course.id,
                output_constraints=OutputConstraints(language='auto', format='json'),
            )
            output = validate(result.structured_output or {})
            call = session.get(DBModelCall, result.call_id)
            if call is None:
                raise ValueError('近期学习安排尚未保存，请重试。')
            call.input_summary = {**(call.input_summary or {}), 'path_sequence_result': {
                'input_hash': input_hash, 'output': output.model_dump(mode='json'),
                'task_id': current_path_task_id()}}
            session.commit()
            return apply_task_sequence(tasks, knowledge, output), output, call.id
        except M5CapabilityError as exc:
            feedback = str(exc.__cause__ or exc)
            if exc.code == 'structured_output_invalid' and attempt == 0:
                continue
            raise
