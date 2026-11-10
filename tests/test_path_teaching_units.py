"""Synthetic course/learning records and model responses; no live model calls."""
import json
from types import SimpleNamespace

import pytest

from app import path_draft
from app import path_sequence
from app.database import (DBCourse, DBChapterKnowledgePoint, DBKnowledgePoint,
                          DBLearningEvent, DBModelCall, DBPathNode, DBPlanVersion, DBUser)
from app.m5_capabilities import Capability
from app.m5_gateway import GatewayResult
from app.m5_learning import (PlanSpec, _generation_context, _publish_path,
                             _schedule_course_projection, confirm_plan)
from app.learning_aggregation import _event_matches_node, _node_completion_supported, _node_predecessors
from tests.test_acceptance_p1_b11_personalized_path import COURSE_ID, _session, _profile, _RealPathBackend


@pytest.fixture
def case():
    engine, db = _session()
    user = db.query(DBUser).filter_by(username='lzz').one()
    course = db.get(DBCourse, COURSE_ID)
    facts = path_draft._course_facts(db, course_id=COURSE_ID)
    chapter = facts['chapters'][0]
    first = facts['kp_by_chapter'][chapter.id][0].id
    second = 'unit-synthetic-second-point'
    db.add(DBKnowledgePoint(id=second, domain_pack=COURSE_ID, code='UNIT_SECOND',
                           version='1', title='第二个独立学习内容', level='core', status='active'))
    db.flush()
    db.add(DBChapterKnowledgePoint(chapter_id=chapter.id, knowledge_point_id=second))
    units = [{'key':'first-unit', 'title':'先掌握基础', 'goal':'能解释基础概念', 'knowledge_point_ids':[first]},
             {'key':'second-unit', 'title':'再学习应用', 'goal':'能够应用所学概念', 'knowledge_point_ids':[second]}]
    course.manifest_data = {**(course.manifest_data or {}), 'structure_workspace': {'applied': {'structure': {
        'units':units, 'prerequisites':[{'prerequisite_id':first, 'dependent_id':second}]}}}}
    db.flush()
    profile = _profile(db, user, 'unit-scope')
    yield db, user, course, profile, chapter, first, second
    db.close(); engine.dispose()


def test_completed_model_batch_does_not_claim_a_complete_path(case):
    db, user, course, profile, *_ = case
    row = DBModelCall(trace_id='synthetic-partial-path', owner_public_id=user.public_id,
        course_id=course.id, capability='plan', prompt_version='path-batch:1',
        provider='synthetic', model='synthetic', status='completed', input_summary={})
    db.add(row); db.flush()
    payload = path_draft.textbook_path_draft_payload(db, current_user=user,
        course_id=course.id, profile_snapshot_id=profile.id)
    assert payload['plan'] is None and payload['nodes'] == []
    assert payload['generation']['status'] == 'partial'
    assert row.status == 'completed'  # preserve the individual call fact


def test_stage_shorthand_resolves_only_within_its_unit_and_preserves_code(case):
    db, _, course, _, chapter, *_ = case
    node = {'node_key': 'unit-a-part-2', 'target_object_id': chapter.id,
            'title': '比较实验', 'teaching_goal': '沿part-1的输入比较结果。代码变量`part-1`保持原样。',
            'rationale': '检查part-1中的预测。'}
    names = {'unit-a-part-1': '1 · 认识输入和输出', 'unit-b-part-1': '8 · 另一个单元'}
    result = path_draft._node_projection(path_draft._course_facts(db, course_id=course.id),
        node=node, reasons={}, weak_ids=set(), names=names)
    assert '1 · 认识输入和输出' in result['teaching_goal']
    assert '另一个单元' not in result['teaching_goal']
    assert '`part-1`' in result['teaching_goal']
    assert node['teaching_goal'].startswith('沿part-1')


def patch_model(monkeypatch, *, split_first=False):
    calls=[]
    async def generate(db, **kwargs):
        request=json.loads(kwargs['user_prompt'])
        is_overview=kwargs['role']=='全程学习安排'
        is_sequence=kwargs['role']=='近期学习成果安排'
        assigned=request.get('required_learning_tasks', [])
        nodes=[{**task, 'prerequisites':[], 'node_type':'chapter', 'resource_status':'existing',
                'estimate_min_minutes':15, 'estimate_max_minutes':20, 'difficulty':.4,
                'rationale':'依据本单元的学习范围安排讲解与练习。'} for task in assigned]
        if split_first and not calls and nodes:
            first=nodes.pop(0)
            nodes[0:0]=[{**first,'node_key':first['node_key']+f'-part-{i}', 'teaching_goal':goal}
                        for i,goal in enumerate(('解释概念并判断适用条件','独立完成应用并检验结果'),1)]
        is_review=kwargs['role'] in {'学习路径教学复核', '学习路径修订独立核验'}
        payload=({'findings':[], 'revised_path':None} if is_review else
                 {'plan':{'goal':request['context']['learning_goal'], 'assumptions':['先完成目标成果，完整课程继续深入。'], 'nodes':nodes}, 'personalization_summary':'根据当前学习范围和先修安排逐步学习。'})
        if is_overview:
            payload={'goal':request['context']['learning_goal'],
                     'stages':[{'title':'完整学习成果', 'outcome':request['learning_steps'][-1]['teaching_goal'] or request['learning_steps'][-1]['title'],
                                'end_node_key':request['learning_steps'][-1]['node_key']}],
                     'assumptions':['先完成目标成果，完整课程继续深入。'],
                     'personalization_summary':'根据完整路线的实际学习步骤与当前学习条件安排。'}
        if is_sequence:
            payload={'near_term_outcome':request['context']['learning_goal'], 'early_tasks':[],
                     'basis':'合成课程按当前已确认先修顺序安排。'}
        kwargs['response_validator'](payload)
        row=DBModelCall(trace_id='synthetic-unit',owner_public_id=kwargs['owner_public_id'],course_id=kwargs['course_id'],
                        capability='plan',prompt_version=kwargs['operation']+':1.0',provider='synthetic',
                        model='deepseek-v4-flash',status='completed',input_summary={})
        db.add(row); db.flush()
        if not is_review and not is_overview and not is_sequence:
            calls.append(request)
        return GatewayResult(trace_id='synthetic-unit',call_id=row.id,capability=Capability.PLAN,status='completed',
            structured_output=payload,model='deepseek-v4-flash',prompt_version=kwargs['operation']+':1.0',
            input_tokens=1,output_tokens=1,token_source='estimated',estimated_cost=0)
    monkeypatch.setattr(path_draft,'execute_registered_structured_call',generate)
    monkeypatch.setattr(path_sequence,'execute_registered_structured_call',generate)
    return calls


def test_path_retains_late_partial_misconception_despite_overall_passing_grade(case):
    db, user, course, profile, _, first, second = case
    feedback = [{"knowledge_point_id": first, "grading": {"score": 1, "correct": True,
        "feedback": "本题概念判断正确", "improvementAdvice": []}} for _ in range(32)]
    explanation = "已经能分别计算两轮点击比例。" * 30 + "仍把样本频率等同于真实概率，需要补充随机波动与估计的区别。"
    advice = ["保留已会的除法", "对照不同样本量", "观察重复样本的波动，不能把单次频率当成确定的真实概率。"]
    criterion = {"criterion_id": "parameter", "score": 0.0, "justification": "仍把0.21视为真实概率"}
    feedback.append({"knowledge_point_id": second, "grading": {"score": .625, "correct": True,
        "feedback": explanation, "improvementAdvice": advice, "criterionResults": [criterion]}})
    snapshot = {**profile.snapshot, "diagnostic_evidence": {"grading_feedback": feedback}}
    context = path_draft._path_model_context(path_draft._course_facts(db, course_id=course.id),
        course=course, profile=profile, snapshot=snapshot, time_budget_minutes=30)
    received = context['initial_learning_evidence']['diagnostic_evidence']['grading_feedback'][-1]
    assert received['knowledge_point_id'] == second
    assert received['correct'] is True and received['score'] == .625
    assert received['feedback'] == explanation
    assert received['improvement_advice'] == advice
    assert received['criterion_results'] == [criterion]


def generate_and_confirm(case, monkeypatch):
    db,user,course,profile,*_=case
    patch_model(monkeypatch)
    plan,_=path_draft.generate_textbook_path_draft(db,current_user=user,course_id=course.id,profile_snapshot_id=profile.id,
        time_budget_minutes=45,full_coverage=True,llm=_RealPathBackend(),idempotency_key='synthetic-unit-plan')
    path=confirm_plan(db,plan=plan,owner_public_id=user.public_id,expected_lock_version=plan.lock_version)
    return plan,path


def test_draft_prose_resolves_step_references_without_rewriting_saved_model_plan(case, monkeypatch):
    from copy import deepcopy
    db, user, course, profile, *_ = case
    patch_model(monkeypatch, split_first=True)
    plan, _ = path_draft.generate_textbook_path_draft(
        db, current_user=user, course_id=course.id, profile_snapshot_id=profile.id,
        time_budget_minutes=45, full_coverage=True, llm=_RealPathBackend())
    version = db.get(DBPlanVersion, plan.current_version_id)
    raw = deepcopy(version.content)
    target = raw['nodes'][1]
    raw['goal'] = f"Continue {target['node_key']} with the original table."
    raw['assumptions'] = [f"The first table belongs to {target['node_key']}; later work refines it."]
    raw['nodes'][2]['teaching_goal'] = f"Use the table from {target['node_key']}; calculate Q/2."
    version.content = raw
    db.flush()
    result = path_draft.textbook_path_draft_payload(db, current_user=user, course_id=course.id)
    reference = f"2 · {target['title']}"
    assert reference in result['plan']['goal']
    assert reference in result['plan']['assumptions'][0]
    assert reference in result['nodes'][2]['teaching_goal']
    assert 'Q/2' in result['nodes'][2]['teaching_goal']
    assert result['nodes'][1]['node_key'] == target['node_key']
    assert version.content == raw
    path = confirm_plan(db, plan=plan, owner_public_id=user.public_id, expected_lock_version=plan.lock_version)
    schedule = _schedule_course_projection(db, owner_public_id=user.public_id, path=path)
    assert reference in schedule['nodes'][2]['teaching_goal']
    assert version.content == raw


def test_prepare_scheduled_resource_on_rest_day_keeps_future_exam_evidence_window(case, monkeypatch):
    from datetime import date, datetime
    from app import exam_gate, m5_learning
    from app.database import DBStudentProfile, DBLearningPath
    from app.resource_bundles import create_generation_job, _generation_manifest
    db, user, course, _, _, point_a, point_b = case
    course.manifest_data = {**course.manifest_data, 'structure_workspace': {'applied': {'structure': {
        'units': [{'key': 'combined-unit', 'title': '两项概念的完整学习', 'goal': '分别理解并应用两项概念',
                   'knowledge_point_ids': [point_a, point_b]}], 'prerequisites': []}}}}
    _, path = generate_and_confirm(case, monkeypatch)
    # This scenario tests a scheduled two-concept unit, not the demo learner's
    # independent priority for a later weak chapter. Make its prerequisite explicit.
    ordered = db.query(DBPathNode).filter_by(learning_path_id=path.id).order_by(DBPathNode.sequence).all()
    for later in ordered[1:]:
        later.prerequisites = [ordered[0].node_key]
    for other in db.query(DBLearningPath).filter_by(owner_public_id=user.public_id).all():
        if other.id != path.id:
            other.status = 'paused'
    profile = db.get(DBStudentProfile, user.username)
    profile.dimension_states = {'learning_context': {'confirmed_fields': {'study_schedule': '每周六45分钟'}}}
    db.flush()
    monkeypatch.setattr(m5_learning, '_learning_today', lambda: date(2026, 11, 4))
    monkeypatch.setattr(exam_gate, '_learning_today', lambda: date(2026, 11, 4))
    monkeypatch.setattr(exam_gate, '_now', lambda: datetime(2026, 11, 4, 8))
    schedule = m5_learning.multi_course_schedule(db, owner_public_id=user.public_id, course_id=course.id)
    assert not schedule['days'][0]['tasks']
    first = next(day for day in schedule['days'] if day['tasks'])
    node = db.get(DBPathNode, first['tasks'][0]['node_id'])
    from app.path_scope import path_node_scope
    assert set(path_node_scope(db, node)) == {point_a, point_b}
    context = _generation_context(db, owner_public_id=user.public_id, course_id=course.id, node=node)
    before = db.query(DBLearningEvent).count()
    job = create_generation_job(db, user, course_id=course.id, knowledge_point_id=context['knowledge_point_id'],
        profile_snapshot_id=context['profile_snapshot_id'], path_id=path.id, task_id=node.id,
        idempotency_key='synthetic-prepare-future', scope='single', learning_goal='先准备下次学习',
        items=[{'type': 'handout', 'title': '学习材料', 'source_ref_ids': context['source_ref_ids'], 'completion_rule': '完成学习检查'}])
    manifest = _generation_manifest(db, job['job_id'])
    gate = manifest['exam_gate']
    assert gate['assignment_date'] == first['date'] == '2026-11-07'
    assert exam_gate._parse_timestamp(gate['assigned_at']) == datetime(2026, 11, 4, 8)
    assert all(exam_gate._parse_timestamp(item['assigned_at']) == datetime(2026, 11, 6, 16)
               for item in gate['required_tasks'])
    assert gate['selected_task_id'] == node.id
    assert manifest['context']['teaching_scope']['path_version_id'] == path.source_plan_version_id
    assert not exam_gate.exam_gate_status(db, owner_public_id=user.public_id, course_id=course.id)['unlocked']
    assert db.query(DBLearningEvent).count() == before
    assert '学习时段' in schedule['days'][0]['budget_note']
    # The preparation route remains bound to this learner's real scheduled task.
    with pytest.raises(exam_gate.ExamGateError) as rejected:
        exam_gate.freeze_exam_gate_snapshot(db, owner_public_id='another-learner', course_id=course.id,
                                           path_id=path.id, task_id=node.id, allow_scheduled_preparation=True)
    assert rejected.value.code == 'exam_gate.path_unknown'
    with pytest.raises(exam_gate.ExamGateError) as rejected:
        exam_gate.freeze_exam_gate_snapshot(db, owner_public_id=user.public_id, course_id=course.id,
                                           path_id=path.id, task_id='not-in-this-path', allow_scheduled_preparation=True)
    assert rejected.value.code == 'exam_gate.task_not_today'
    monkeypatch.setattr(m5_learning, '_learning_today', lambda: date(2026, 11, 7))
    monkeypatch.setattr(exam_gate, '_learning_today', lambda: date(2026, 11, 7))
    def answer(point, when, *, eligible=True):
        db.add(DBLearningEvent(owner_public_id=user.public_id, course_id=course.id,
            event_type='quiz_answered', object_type='knowledge_point', object_id=point,
            context_ref={'taskId': node.id}, payload={'correct': True, 'path_id': path.id},
            completion_effect='complete', evidence_status='accepted' if eligible else 'none', mastery_eligible=eligible,
            evidence_strength=.8, occurred_at=when, trace_id='synthetic-future-unit'))
        db.flush()
    def complete():
        return node.id in exam_gate.exam_gate_status(db, owner_public_id=user.public_id,
                                                     course_id=course.id)['completed_task_ids']
    answer(point_a, datetime(2026, 11, 4, 9))
    answer(point_b, datetime(2026, 11, 4, 9))
    assert not complete()  # Earlier results do not pass a new day's assignment.
    answer(point_a, datetime(2026, 11, 7, 9))
    assert not complete()  # One point must not complete the whole two-point unit.
    answer(point_b, datetime(2026, 11, 7, 9), eligible=False)
    assert not complete()
    answer(point_b, datetime(2026, 11, 7, 9))
    assert complete()


def test_confirmed_units_reach_full_path_schedule_and_generation_without_omitting_chapters(case,monkeypatch):
    db,user,course,_,chapter,first,second=case
    facts=path_draft._course_facts(db,course_id=course.id)
    before=db.query(DBLearningEvent).count()
    plan,path=generate_and_confirm(case,monkeypatch)
    content=db.get(DBPlanVersion,plan.current_version_id).content
    PlanSpec.model_validate(content)
    assert {node['target_object_id'] for node in content['nodes']}=={item.id for item in facts['chapters']}
    split=[node for node in content['nodes'] if node['target_object_id']==chapter.id]
    assert len(split)==2
    assert split[1]['prerequisites']==[split[0]['node_key']]
    assert split[0]['knowledge_point_ids']==[first]
    assert split[1]['knowledge_point_ids']==[second]
    schedule=_schedule_course_projection(db,owner_public_id=user.public_id,path=path)
    for projected in schedule['nodes'][:2]:
        expected=next(node for node in split if node['node_key']==projected['node_key'])
        assert [point['id'] for point in projected['knowledge_points']]==expected['knowledge_point_ids']
        context=projected['generation_context']
        assert context['knowledge_point_id']==expected['knowledge_point_ids'][0]
        assert context['teaching_goal']==expected['teaching_goal']
        assert context['chapter_title']==chapter.title
        assert projected['completion_criteria']=='完成本单元各知识点的学习检查。'
    assert db.query(DBLearningEvent).count()==before
    from app.resource_bundles import create_generation_job, _generation_manifest, _real_model_prompt
    first_task=db.query(DBPathNode).filter_by(learning_path_id=path.id,node_key=split[0]['node_key']).one()
    context=_generation_context(db,owner_public_id=user.public_id,course_id=course.id,node=first_task)
    job=create_generation_job(db,user,course_id=course.id,knowledge_point_id=first,
        profile_snapshot_id=context['profile_snapshot_id'],path_id=path.id,task_id=first_task.id,
        idempotency_key='synthetic-unit-resource',scope='single',learning_goal='理解基础',
        items=[{'type':'handout','title':'理解基础','source_ref_ids':context['source_ref_ids'],'completion_rule':'完成学习检查'}])
    manifest=_generation_manifest(db,job['job_id'])
    scope=manifest['context']['teaching_scope']
    assert scope['goal']=='能解释基础概念'
    assert scope['path_version_id']==path.source_plan_version_id
    assert scope['knowledge_points'][0]['id']==first
    assert manifest['input_snapshot']['teaching_scope']==scope
    _,prompt=_real_model_prompt(resource_type='handout',item=manifest['items'][0],manifest=manifest,
        source_snapshots=manifest['input_snapshot']['source_snapshots']['handout'])
    assert json.loads(prompt)['course']['teaching_scope']==scope


def test_old_chapter_completion_does_not_complete_split_units_or_transfer_unrelated_event(case,monkeypatch):
    db,user,course,_,chapter,first,second=case
    plan,path=generate_and_confirm(case,monkeypatch)
    nodes=db.query(DBPathNode).filter_by(learning_path_id=path.id,target_object_id=chapter.id).order_by(DBPathNode.sequence).all()
    event=DBLearningEvent(owner_public_id=user.public_id,course_id=course.id,event_type='quiz_answered',
        object_type='knowledge_point',object_id=first,context_ref={'taskId':nodes[0].id,'knowledgePointId':first},
        payload={'path_id':path.id,'correct':True},completion_effect='complete',trace_id='synthetic-unit',evidence_status='accepted')
    assert _event_matches_node(db,event,nodes[0])
    assert not _event_matches_node(db,event,nodes[1])
    assert _node_completion_supported(db,nodes[0],[event])
    assert not _node_completion_supported(db,nodes[1],[event])
    # Expand the second task's scope in a NEW frozen version, keeping prior scores.
    from copy import deepcopy
    old_version=db.get(DBPlanVersion,path.source_plan_version_id)
    revised=deepcopy(old_version.content)
    for item in revised['nodes']:
        if item['node_key']==nodes[1].node_key:
            item['knowledge_point_ids']=[first,second]
    version=DBPlanVersion(plan_draft_id=plan.id,version_number=2,content=revised,content_hash='synthetic-new-scope')
    db.add(version); db.flush()
    nodes[1].status='completed'
    new_path=_publish_path(db,plan=plan,version=version,previous_path=path)
    new_node=db.query(DBPathNode).filter_by(learning_path_id=new_path.id,node_key=nodes[1].node_key).one()
    assert new_node.status=='pending'
    assert not _node_predecessors(db,new_node)
    assert not _node_completion_supported(db,new_node,[event])


def test_unit_scope_cannot_include_another_chapters_concept(case,monkeypatch):
    db,user,course,_,chapter,first,second=case
    plan,_=generate_and_confirm(case,monkeypatch)
    content=db.get(DBPlanVersion,plan.current_version_id).content
    from copy import deepcopy
    invalid=deepcopy(content)
    other=next(point for item in invalid['nodes'][2:] for point in item['knowledge_point_ids'])
    invalid['nodes'][0]['knowledge_point_ids'].append(other)
    from app.m5_learning import _validate_plan_targets, M5LearningError
    with pytest.raises(M5LearningError):
        _validate_plan_targets(db,owner_public_id=user.public_id,course_id=course.id,spec=PlanSpec.model_validate(invalid))


def test_many_tasks_are_not_truncated_at_the_old_500_node_limit():
    spec=PlanSpec(goal='覆盖全部学习任务',nodes=tuple({
        'node_key':f'task-{i}', 'node_type':'chapter','target_object_id':f'chapter-{i}',
        'title':f'学习内容 {i}','resource_status':'existing','estimate_min_minutes':10,'estimate_max_minutes':20,
    } for i in range(510)))
    assert len(spec.nodes)==510


def test_primary_reading_avoids_duplicate_unit_but_retains_uncovered_concepts_and_distinct_practice():
    a, b, c = [SimpleNamespace(id=key, title=key, prerequisites=[]) for key in ('a','b','c')]
    chapters = [SimpleNamespace(id=key, title=key) for key in ('main','reference','practice')]
    facts = {'chapters':chapters, 'knowledge':{p.id:p for p in (a,b,c)},
        'kp_by_chapter':{'main':[a], 'reference':[a,b], 'practice':[a,c]},
        'teaching_units':[
            {'key':'understand','title':'理解与判断','knowledge_point_ids':['a','b'],
             'primary_chapter_keys':['main','reference']},
            {'key':'experiment','title':'独立实验','knowledge_point_ids':['a','c'],
             'primary_chapter_keys':['practice']}]}
    tasks = path_draft._full_course_tasks(facts)
    assert [(task['target_object_id'],task['teaching_unit_key']) for task in tasks] == [
        ('main','understand'),('reference','understand'),('practice','experiment')]
    # Both selected sections are intentional; an extra reference does not add
    # another task, while a previously uncovered concept still needs teaching.
    extra = SimpleNamespace(id='extra',title='补充原文')
    facts['chapters'].append(extra)
    facts['kp_by_chapter']['extra']=[a]
    assert path_draft._full_course_tasks(facts) == tasks
    d = SimpleNamespace(id='d',title='新增内容',prerequisites=[])
    facts['knowledge']['d']=d
    facts['kp_by_chapter']['extra'].append(d)
    remaining = path_draft._full_course_tasks(facts)[-1]
    assert remaining['target_object_id']=='extra' and remaining['knowledge_point_ids']==['d']
    facts['reference_chapter_ids']=['extra']
    assert path_draft._full_course_tasks(facts)==tasks
    facts['teaching_units'][0]['primary_chapter_keys']=['missing']
    with pytest.raises(path_draft.PathDraftError):
        path_draft._full_course_tasks(facts)


def test_generated_path_uses_primary_source_and_keeps_reference_available(case,monkeypatch):
    from app.database import DBChapter, DBSourceRef
    db,user,course,profile,chapter,first,second = case
    original = path_draft._course_facts(db,course_id=course.id)
    existing_ids = {ch.id for ch in original['chapters']}
    ref_chapter = DBChapter(id='synthetic-extra-reference',course_id=course.id,
        source_document_id=chapter.source_document_id, stable_key='extra-reference',title='同一概念的补充原文',
        position=999, char_start=chapter.char_start,char_end=chapter.char_end)
    db.add(ref_chapter);db.flush()
    db.add(DBChapterKnowledgePoint(chapter_id=ref_chapter.id,knowledge_point_id=first))
    manifest = json.loads(json.dumps(course.manifest_data))
    for unit in manifest['structure_workspace']['applied']['structure']['units']:
        unit['primary_chapter_keys']=[chapter.id]
    course.manifest_data=manifest;db.flush()
    calls=patch_model(monkeypatch)
    plan,_=path_draft.generate_textbook_path_draft(db,current_user=user,course_id=course.id,
        profile_snapshot_id=profile.id,time_budget_minutes=45,full_coverage=True,llm=_RealPathBackend(),
        idempotency_key='primary-reference-plan')
    content=db.get(DBPlanVersion,plan.current_version_id).content
    assert {n['target_object_id'] for n in content['nodes']}==existing_ids
    assert db.get(DBChapter,ref_chapter.id).title=='同一概念的补充原文'
    same,created=path_draft.generate_textbook_path_draft(db,current_user=user,course_id=course.id,
        profile_snapshot_id=profile.id,time_budget_minutes=45,full_coverage=True,llm=_RealPathBackend(),
        idempotency_key='primary-reference-plan')
    assert same.id==plan.id and not created
    assert len(calls)==(len(path_draft._full_course_tasks(path_draft._course_facts(db,course_id=course.id)))+3)//4


def test_full_path_keeps_the_learners_specific_goal_after_batch_merge(case,monkeypatch):
    db,user,course,profile,*_=case
    goal='In eight weeks build a replenishment sheet for ten shop products.'
    profile.snapshot={**profile.snapshot,'learning_goal':goal}
    plan,_=generate_and_confirm(case,monkeypatch)
    assert db.get(DBPlanVersion,plan.current_version_id).content['goal']==goal


def test_path_model_gets_current_chapter_evidence_and_previous_stages(case,monkeypatch):
    db,user,course,profile,*_=case
    calls=patch_model(monkeypatch)
    path_draft.generate_textbook_path_draft(db,current_user=user,course_id=course.id,profile_snapshot_id=profile.id,
        time_budget_minutes=30,full_coverage=True,llm=_RealPathBackend(),idempotency_key='source-grounded-path')
    from app.source_refs import source_ref_teaching_text
    from app.database import DBSourceRef
    for request in calls:
        for chapter in request['context']['course_graph']['chapters']:
            reading=chapter['reading']
            ref=db.get(DBSourceRef,reading['source_ref_id'])
            assert reading['text']==source_ref_teaching_text(db,ref,max_chars=None)
    assert len(calls)>1
    assert calls[1]['earlier_learning_steps']
    assert calls[1]['earlier_maximum_minutes']==80
    assert calls[1]['earlier_stage_notes']==['先完成目标成果，完整课程继续深入。']


def test_unit_can_be_split_into_real_sessions_without_losing_scope():
    task={'node_key':'unit-test','target_object_id':'chapter-test','knowledge_point_ids':['kp-a','kp-b'],
          'teaching_unit_key':'teaching-unit','teaching_goal':'Understand and apply both ideas','prerequisites':[]}
    nodes=[{**task,'node_key':f'unit-test-part-{i}','title':f'Learning step {i}',
            'node_type':'chapter','resource_status':'existing','knowledge_point_ids':[point],
            'estimate_min_minutes':20,'estimate_max_minutes':30,'teaching_goal':f'Apply {point}'}
           for i,point in enumerate(['kp-a','kp-b'],1)]
    output=path_draft.PathDraftModelOutput(plan=PlanSpec(goal='Prepare a usable result',nodes=nodes),
        personalization_summary='两个小步骤分别学习当前单元的两个概念。')
    assert path_draft._validate_task_batch(output,[task],time_budget_minutes=30)==output
    from copy import deepcopy
    invalid=deepcopy(output.model_dump())
    invalid['plan']['nodes'][1]['knowledge_point_ids']=['kp-outside']
    with pytest.raises(path_draft.PathDraftError):
        path_draft._validate_task_batch(path_draft.PathDraftModelOutput.model_validate(invalid),[task],time_budget_minutes=30)
    overlong=deepcopy(output.model_dump());overlong['plan']['nodes'][0]['estimate_max_minutes']=45
    with pytest.raises(path_draft.PathDraftError):
        path_draft._validate_task_batch(path_draft.PathDraftModelOutput.model_validate(overlong),[task],time_budget_minutes=30)


def test_split_stages_keep_dependencies_resource_goal_and_separate_completion(case,monkeypatch):
    db,user,course,profile,chapter,first,second=case
    patch_model(monkeypatch,split_first=True)
    plan,_=path_draft.generate_textbook_path_draft(db,current_user=user,course_id=course.id,profile_snapshot_id=profile.id,
        time_budget_minutes=30,full_coverage=True,llm=_RealPathBackend(),idempotency_key='synthetic-split-stages')
    path=confirm_plan(db,plan=plan,owner_public_id=user.public_id,expected_lock_version=plan.lock_version)
    content=db.get(DBPlanVersion,plan.current_version_id).content
    assert content['assumptions'][-1]=='先完成目标成果，完整课程继续深入。'
    assert content['assumptions'][0].startswith(f"1–{len(content['nodes'])} · 完整学习成果：")
    nodes=db.query(DBPathNode).filter_by(learning_path_id=path.id).order_by(DBPathNode.sequence).all()
    assert nodes[1].prerequisites==[nodes[0].node_key]
    assert nodes[2].prerequisites==[nodes[1].node_key]
    context=_generation_context(db,owner_public_id=user.public_id,course_id=course.id,node=nodes[1])
    assert context['teaching_goal']=='独立完成应用并检验结果'
    event=DBLearningEvent(owner_public_id=user.public_id,course_id=course.id,event_type='quiz_answered',
        object_type='knowledge_point',object_id=first,context_ref={'taskId':nodes[0].id,'knowledgePointId':first},
        payload={'path_id':path.id,'correct':True},completion_effect='complete',trace_id='synthetic-stages',evidence_status='accepted')
    assert _event_matches_node(db,event,nodes[0])
    assert not _event_matches_node(db,event,nodes[1])
    event.context_ref={'knowledgePointId':first}
    assert not _event_matches_node(db,event,nodes[1])
    nodes[0].status='completed'
    from copy import deepcopy
    revised=deepcopy(content)
    revised['nodes'][1]['teaching_goal']='比较两个新场景中的应用结果'
    version=DBPlanVersion(plan_draft_id=plan.id,version_number=2,content=revised,content_hash='synthetic-staged-revision')
    db.add(version);db.flush()
    new_path=_publish_path(db,plan=plan,version=version,previous_path=path)
    new_nodes=db.query(DBPathNode).filter_by(learning_path_id=new_path.id).order_by(DBPathNode.sequence).all()
    assert new_nodes[0].status=='completed'
    assert new_nodes[1].status=='pending'
    assert not _node_predecessors(db,new_nodes[1])


def test_unit_quiz_keeps_each_questions_concept_and_does_not_truncate_extra_questions(case,monkeypatch):
    from app.resource_bundles import _create_quiz_resource_content, ResourceBundleError
    from app.database import DBAssessmentQuestionVersion
    from app.learning_aggregation import _event_concept
    db,user,course,_,chapter,first,second=case
    manifest={'knowledge_point_id':first,'context':{'knowledge_point_title':'单元入口',
        'teaching_scope':{'knowledge_points':[{'id':first,'title':'基础概念'},{'id':second,'title':'应用判断'}]}}}
    questions=[{'prompt':f'计算{index}+1的结果。','options':[str(index+1),'100','200','300'],
        'answer':'A','explanation':f'{index}+1={index+1}。','knowledgePointId':point}
        for index,point in enumerate([first,second,first,second],start=1)]
    content=json.loads(_create_quiz_resource_content(db,actor=user,task=SimpleNamespace(course_id=course.id),
        item={'title':'单元学习检查'},manifest=manifest,source_snapshots=[{'source_ref_id':'demo-ref-07'}],
        llm_payload={'learningGoal':'检查两个知识点','quizQuestions':questions,'summary':'四题检查',
            'studySessions':[{'startQuestion':1,'endQuestion':2,'estimatedMinutes':15},
                             {'startQuestion':3,'endQuestion':4,'estimatedMinutes':15}]}))
    assert len(content['questions'])==4 and content['requiredQuestionCount']==4
    from app.m5_resources import parse_quiz_content
    parsed = parse_quiz_content(json.dumps(content))
    assert [(s.startQuestion,s.endQuestion) for s in parsed.studySessions]==[(1,2),(3,4)]
    versions=[db.get(DBAssessmentQuestionVersion,item['questionVersionId']) for item in content['questions']]
    assert [item.primary_knowledge_point_id for item in versions]==[first,second,first,second]
    events=[DBLearningEvent(owner_public_id=user.public_id,course_id=course.id,event_type='quiz_answered',
        object_type='assessment_question_version',object_id=item.id,context_ref={},payload={'correct':True},
        completion_effect='complete',evidence_status='accepted',trace_id='synthetic-unit-quiz') for item in versions]
    assert [_event_concept(db,item)[0] for item in events]==[first,second,first,second]
    monkeypatch.setattr('app.path_scope.path_node_scope',lambda _db,_node:(first,second))
    assert not _node_completion_supported(db,SimpleNamespace(),events[:1])
    assert _node_completion_supported(db,SimpleNamespace(),events[:2])
    before=db.query(DBAssessmentQuestionVersion).count()
    for sessions in (
        [{'startQuestion':1,'endQuestion':3,'estimatedMinutes':15}],
        [{'startQuestion':1,'endQuestion':3,'estimatedMinutes':15},
         {'startQuestion':3,'endQuestion':4,'estimatedMinutes':15}],
        [{'startQuestion':1,'endQuestion':4,'estimatedMinutes':0}],
    ):
        with pytest.raises(ResourceBundleError):
            _create_quiz_resource_content(db,actor=user,task=SimpleNamespace(course_id=course.id),
                item={'title':'单元检查'},manifest=manifest,source_snapshots=[{'source_ref_id':'demo-ref-07'}],
                llm_payload={'learningGoal':'检查两个知识点','quizQuestions':questions,'studySessions':sessions})
    assert db.query(DBAssessmentQuestionVersion).count()==before
    for bad in ([{**q,'knowledgePointId':first} for q in questions],
                [{**q,'knowledgePointId':'other-course-point'} for q in questions],
                [questions[0], 'incomplete question', questions[2]]):
        with pytest.raises(ResourceBundleError) as rejected:
            _create_quiz_resource_content(db,actor=user,task=SimpleNamespace(course_id=course.id),
                item={'title':'单元检查'},manifest=manifest,source_snapshots=[{'source_ref_id':'demo-ref-07'}],
                llm_payload={'learningGoal':'检查两个知识点','quizQuestions':bad})
        assert rejected.value.code=='resource_generation.quiz_scope_incomplete'
    assert db.query(DBAssessmentQuestionVersion).count()==before


def test_single_point_quiz_uses_confirmed_scope_or_entry_not_model_selected_foreign_point(case):
    from app.resource_bundles import _create_quiz_resource_content
    from app.database import DBAssessmentQuestionVersion
    db,user,course,_,chapter,first,second=case
    questions=[{'prompt':f'{i}+1等于多少？','options':[str(i+1),'100','200','300'],
        'answer':'A','explanation':f'{i}+1={i+1}。','knowledgePointId':'foreign-point'} for i in range(3)]
    for scope, expected in (({},first),({'knowledge_points':[{'id':second,'title':'第二个知识点'}]},second)):
        content=json.loads(_create_quiz_resource_content(db,actor=user,task=SimpleNamespace(course_id=course.id),
            item={'title':'练习'},manifest={'knowledge_point_id':first,'context':{'teaching_scope':scope}},
            source_snapshots=[{'source_ref_id':'demo-ref-07'}],llm_payload={
                'learningGoal':'核对计算','quizQuestions':[
                    {**q,'knowledgePointId':''} if scope else q for q in questions]}))
        assert {db.get(DBAssessmentQuestionVersion,q['questionVersionId']).primary_knowledge_point_id
                for q in content['questions']}=={expected}


def test_failed_later_batch_reuses_successful_scope_identical_batches(case,monkeypatch):
    db,user,course,profile,*_=case
    calls=patch_model(monkeypatch)
    original=path_draft.execute_registered_structured_call
    interrupted=False
    from app.m5_capabilities import M5CapabilityError
    async def interrupted_once(db,**kwargs):
        nonlocal interrupted
        if json.loads(kwargs['user_prompt']).get('batch_index')==2 and not interrupted:
            interrupted=True
            raise M5CapabilityError('provider_call_failed','synthetic one-time network failure')
        return await original(db,**kwargs)
    monkeypatch.setattr(path_draft,'execute_registered_structured_call',interrupted_once)
    kwargs=dict(current_user=user,course_id=course.id,profile_snapshot_id=profile.id,time_budget_minutes=45,
                full_coverage=True,llm=_RealPathBackend(),idempotency_key='synthetic-resume')
    with pytest.raises(path_draft.PathDraftError):
        path_draft.generate_textbook_path_draft(db,**kwargs)
    db.rollback()
    assert len(calls)==1
    plan,changed=path_draft.generate_textbook_path_draft(db,**kwargs)
    assert changed
    assert sum(request['batch_index']==1 for request in calls)==1
    tasks=path_draft._full_course_tasks(path_draft._course_facts(db,course_id=course.id))
    assert len(calls)==(len(tasks)+3)//4
    assert len(db.get(DBPlanVersion,plan.current_version_id).content['nodes'])==len(tasks)


def test_review_retry_reuses_draft_and_passes_corrected_tasks_to_later_batches(case,monkeypatch):
    from copy import deepcopy
    from app.m5_capabilities import M5CapabilityError
    db,user,course,profile,*_=case
    calls=patch_model(monkeypatch)
    original=path_draft.execute_registered_structured_call
    reviews=[]
    async def review_with_one_interruption(db,**kwargs):
        assert kwargs['backend'].max_tokens >= 32768
        request=json.loads(kwargs['user_prompt'])
        if kwargs['role']!='学习路径教学复核':
            return await original(db,**kwargs)
        reviews.append(request)
        if len(reviews)==1:
            raise M5CapabilityError('provider_call_failed','synthetic review interruption')
        result=await original(db,**kwargs)
        if request['batch_index']==1:
            revised=deepcopy(request['candidate'])
            revised['plan']['goal']='Build and check a usable result in eight weeks.'
            revised['plan']['nodes'][0]['teaching_goal']='先核对概念的适用条件，再完成可检查的对照表。'
            revised['plan']['nodes'][0]['prerequisites']=['stray-cross-batch-edge']
            payload={'findings':[{'node_key':revised['plan']['nodes'][0]['node_key'],
                     'problem':'原任务缺少适用条件检查','correction':'先核对条件再应用'}], 'revised_path':revised}
            kwargs['response_validator'](payload)
            return SimpleNamespace(call_id=result.call_id, structured_output=payload)
        return result
    monkeypatch.setattr(path_draft,'execute_registered_structured_call',review_with_one_interruption)
    diagnostic_backend=_RealPathBackend();diagnostic_backend.max_tokens=16384
    kwargs=dict(current_user=user,course_id=course.id,profile_snapshot_id=profile.id,time_budget_minutes=45,
                full_coverage=True,llm=diagnostic_backend,idempotency_key='synthetic-review-resume')
    with pytest.raises(path_draft.PathDraftError):
        path_draft.generate_textbook_path_draft(db,**kwargs)
    db.rollback()
    assert len(calls)==1
    plan,changed=path_draft.generate_textbook_path_draft(db,**kwargs)
    assert changed and sum(request['batch_index']==1 for request in calls)==1
    content=db.get(DBPlanVersion,plan.current_version_id).content
    assert content['goal']==profile.snapshot['learning_goal']  # the full overview, not a batch's deadline
    assert content['nodes'][0]['teaching_goal'].startswith('先核对概念')
    assert content['nodes'][0]['prerequisites']==[]
    assert content['nodes'][1]['prerequisites']==[content['nodes'][0]['node_key']]
    assert calls[1]['earlier_learning_steps'][0]['teaching_goal']==content['nodes'][0]['teaching_goal']
    first=db.query(DBModelCall).filter_by(prompt_version='p1_b11_personalized_learning_path_batch:1.0').first()
    assert first.input_summary['path_batch_result']['output']['plan']['nodes'][0]['teaching_goal']!=content['nodes'][0]['teaching_goal']
    assert first.input_summary['path_teaching_review']['findings'][0]['problem']=='原任务缺少适用条件检查'
    review_id=first.input_summary['path_teaching_review']['call_id']
    assert db.get(DBModelCall,review_id).input_summary['path_teaching_review_result']['output']['plan']['nodes'][0]['teaching_goal']==content['nodes'][0]['teaching_goal']
    before=(len(calls),len(reviews))
    _,changed=path_draft.generate_textbook_path_draft(db,**kwargs)
    assert not changed and before==(len(calls),len(reviews))
    assert diagnostic_backend.max_tokens==16384
    monkeypatch.setattr(path_draft,'PATH_PLANNING_REVISION','synthetic-new-teaching-policy')
    _,changed=path_draft.generate_textbook_path_draft(db,**kwargs)
    assert changed and len(calls)>before[0] and len(reviews)>before[1]


def test_review_policy_change_reuses_drafts_but_reconciles_new_earlier_steps(case,monkeypatch):
    from copy import deepcopy
    db,user,course,profile,*_=case
    generated=patch_model(monkeypatch)
    original=path_draft.execute_registered_structured_call
    reviews=[]
    update=False
    async def gateway(db,**kwargs):
        request=json.loads(kwargs['user_prompt'])
        result=await original(db,**kwargs)
        if kwargs['role']=='学习路径教学复核':
            reviews.append(request)
            if update and request['batch_index']==1:
                revised=deepcopy(request['candidate'])
                revised['plan']['nodes'][0]['teaching_goal']='先用给定预测表完成验证比较，再学习训练实现。'
                value={'findings':[{'node_key':revised['plan']['nodes'][0]['node_key'],
                    'problem':'阶段成果需要提前接入','correction':'先完成可用比较初版'}], 'revised_path':revised}
                kwargs['response_validator'](value)
                return SimpleNamespace(call_id=result.call_id,structured_output=value)
        return result
    monkeypatch.setattr(path_draft,'execute_registered_structured_call',gateway)
    kwargs=dict(current_user=user,course_id=course.id,profile_snapshot_id=profile.id,time_budget_minutes=45,
                full_coverage=True,llm=_RealPathBackend(),idempotency_key='synthetic-review-policy-change')
    plan,_=path_draft.generate_textbook_path_draft(db,**kwargs)
    original_candidates={row.id:deepcopy(row.input_summary['path_batch_result']) for row in db.query(DBModelCall)
        if 'path_batch_result' in row.input_summary}
    first_review_ids={row.id for row in db.query(DBModelCall) if 'path_teaching_review_result' in row.input_summary}
    count=len(generated)
    assert count>1
    reviews.clear();update=True
    monkeypatch.setattr(path_draft,'PATH_REVIEW_INSTRUCTION',path_draft.PATH_REVIEW_INSTRUCTION+'核对首阶段成果。')
    _,changed=path_draft.generate_textbook_path_draft(db,**kwargs)
    assert changed and len(generated)==count and len(reviews)==count
    assert 'candidate_reuse' in reviews[1]
    assert reviews[1]['earlier_learning_steps'][0]['teaching_goal'].startswith('先用给定预测表')
    assert db.get(DBPlanVersion,plan.current_version_id).content['nodes'][0]['teaching_goal'].startswith('先用给定预测表')
    assert all(db.get(DBModelCall,key).input_summary['path_batch_result']==value for key,value in original_candidates.items())
    assert all(db.get(DBModelCall,key) for key in first_review_ids)


def test_targeted_review_keeps_other_nodes_and_passes_the_repair_forward(case, monkeypatch):
    from copy import deepcopy
    db, user, course, profile, *_ = case
    generated = patch_model(monkeypatch)
    original = path_draft.execute_registered_structured_call
    preserved = {}

    async def gateway(db, **kwargs):
        request = json.loads(kwargs['user_prompt'])
        result = await original(db, **kwargs)
        if kwargs['role'] != '学习路径教学复核' or request['batch_index'] != 1:
            return result
        candidate = path_draft.PathDraftModelOutput.model_validate(request['candidate'])
        preserved.update(deepcopy(request['candidate']))
        key = candidate.plan.nodes[0].node_key
        repaired = '等分时核对简单平均，不等分时按样本数加权，再与整批结果比较。'
        value = {'findings': [{'node_key': key, 'problem': '遗漏等分特例',
                              'correction': '分别检查等分与不等分'}],
                 'node_updates': [{'node_key': key, 'teaching_goal': repaired}],
                 'revised_path': None}
        # Unknown, repeated, blank and unimplemented edits must not silently
        # change another lesson or discard a reported teaching problem.
        invalid = [
            {**value, 'node_updates': [{'node_key': 'foreign-node', 'teaching_goal': repaired}]},
            {**value, 'node_updates': value['node_updates'] * 2},
            {**value, 'node_updates': [{'node_key': key, 'teaching_goal': ' '}]},
            {**value, 'node_updates': []},
            {**value, 'findings': value['findings'] + [{'node_key': 'another-node',
                'problem': '另一处问题', 'correction': '也需要处理'}]},
            {**value, 'revised_path': request['candidate']},
        ]
        for bad in invalid:
            with pytest.raises(ValueError):
                kwargs['response_validator'](bad)
        assert candidate.model_dump(mode='json') == preserved
        kwargs['response_validator'](value)
        return SimpleNamespace(call_id=result.call_id, structured_output=value)

    monkeypatch.setattr(path_draft, 'execute_registered_structured_call', gateway)
    plan, _ = path_draft.generate_textbook_path_draft(db, current_user=user,
        course_id=course.id, profile_snapshot_id=profile.id, time_budget_minutes=45,
        full_coverage=True, llm=_RealPathBackend(), idempotency_key='synthetic-scoped-edit')
    content = db.get(DBPlanVersion, plan.current_version_id).content
    first = db.query(DBModelCall).filter_by(prompt_version='p1_b11_personalized_learning_path_batch:1.0').first()
    reviewed = first.input_summary['path_teaching_review']['output']['plan']['nodes']
    for before, after in zip(preserved['plan']['nodes'], reviewed):
        for field in before:
            if before['node_key'] == reviewed[0]['node_key'] and field == 'teaching_goal':
                assert after[field] != before[field]
            elif field != 'prerequisites':  # existing batch normalizer owns edges
                assert after[field] == before[field]
    assert generated[1]['earlier_learning_steps'][0]['teaching_goal'] == content['nodes'][0]['teaching_goal']
    assert first.input_summary['path_batch_result']['output']['plan']['nodes'][0]['teaching_goal'] == preserved['plan']['nodes'][0]['teaching_goal']
    assert first.input_summary['path_teaching_review']['node_updates'][0]['teaching_goal'] == reviewed[0]['teaching_goal']


def test_failed_review_keeps_public_repair_and_feedback_for_later_retry(case, monkeypatch):
    from app.m5_capabilities import M5CapabilityError
    db, user, course, profile, *_ = case
    generated = patch_model(monkeypatch)
    original = path_draft.execute_registered_structured_call
    reviews = []
    async def gateway(db, **kwargs):
        request = json.loads(kwargs['user_prompt'])
        if kwargs['role'] != '学习路径教学复核' or request['batch_index'] != 1:
            return await original(db, **kwargs)
        reviews.append(request)
        if len(reviews) <= 2:
            key = request['candidate']['plan']['nodes'][0]['node_key']
            value = {'findings': [{'node_key': key, 'problem': '需纠正原条件',
                'correction': '保留此前正确修订', 'source_ref_id': 'not-in-current-reading',
                'evidence_quote': '这不是本批提供的引文。'}],
                'node_updates': [{'node_key': key, 'teaching_goal': '已整理的公开教学修订仍应保留。'}],
                'revised_path': None}
            try:
                kwargs['response_validator'](value)
            except ValueError as exc:
                raise M5CapabilityError('structured_output_invalid', 'synthetic invalid quote') from exc
        assert request['previous_review']['node_updates'][0]['teaching_goal'] == '已整理的公开教学修订仍应保留。'
        assert '来源不在本批reading' in request['validation_feedback']
        result = await original(db, **kwargs)
        repaired = request['previous_review']
        repaired['findings'][0].update(source_ref_id='', evidence_quote='')
        kwargs['response_validator'](repaired)
        return SimpleNamespace(call_id=result.call_id, structured_output=repaired)
    monkeypatch.setattr(path_draft, 'execute_registered_structured_call', gateway)
    kwargs = dict(current_user=user, course_id=course.id, profile_snapshot_id=profile.id,
        time_budget_minutes=45, full_coverage=True, llm=_RealPathBackend(), idempotency_key='synthetic-review-feedback')
    with pytest.raises(path_draft.PathDraftError):
        path_draft.generate_textbook_path_draft(db, **kwargs)
    db.rollback()
    first = db.query(DBModelCall).filter_by(prompt_version='p1_b11_personalized_learning_path_batch:1.0').first()
    assert len(first.input_summary['path_teaching_review_failures']) == 2
    assert len(generated) == 1
    plan, _ = path_draft.generate_textbook_path_draft(db, **kwargs)
    assert sum(r['batch_index'] == 1 for r in generated) == 1
    assert db.get(DBPlanVersion, plan.current_version_id).content['nodes'][0]['teaching_goal'] == '已整理的公开教学修订仍应保留。'
    assert len(first.input_summary['path_teaching_review_failures']) == 2


def test_editor_error_is_independently_corrected_before_later_batches(case, monkeypatch):
    from app.m5_capabilities import M5CapabilityError
    db, user, course, profile, *_ = case
    generated = patch_model(monkeypatch)
    original = path_draft.execute_registered_structured_call
    editorial_calls, checks = [], []
    wrong = '用三角形C3与五边形C5说明图级1-WL无法区分任意两个2正则图。'
    correct = '比较C3与C5的初始标签频数3与5，确认图级1-WL可区分；再比较C6与两个C3的并。'
    original_versions = {row.id for row in db.query(DBPlanVersion)}

    async def gateway(db, **kwargs):
        request = json.loads(kwargs['user_prompt'])
        if request.get('batch_index') != 1:
            return await original(db, **kwargs)
        role = kwargs['role']
        if role not in {'学习路径教学复核', '学习路径修订独立核验'}:
            return await original(db, **kwargs)
        key = request['candidate']['plan']['nodes'][0]['node_key']
        if role == '学习路径教学复核':
            editorial_calls.append(request)
            value = {'findings': [{'node_key': key, 'problem': '需要一个不能区分的反例',
                                  'correction': '比较两个度相同的环图'}],
                     'node_updates': [{'node_key': key, 'teaching_goal': wrong}]}
        else:
            checks.append(request)
            # The verifier sees the public tasks, not the editor's proposed
            # answer/reasoning or an instruction to accept that conclusion.
            assert 'previous_review' not in request
            assert 'findings' not in request and 'node_updates' not in request
            if len(checks) == 1:
                raise M5CapabilityError('provider_call_failed', 'synthetic verification interruption')
            if request['candidate']['plan']['nodes'][0]['teaching_goal'] == wrong:
                value = {'findings': [{'node_key': key,
                    'problem': '图级比较是标签多重集合；初始计数3与5已不同。',
                    'correction': '保留可区分的结果，不将颜色种类相同误作频数相同。'}],
                    'node_updates': [{'node_key': key, 'teaching_goal': correct}]}
            else:
                assert request['candidate']['plan']['nodes'][0]['teaching_goal'] == correct
                value = {'findings': [], 'node_updates': []}
        result = await original(db, **kwargs)
        kwargs['response_validator'](value)
        return SimpleNamespace(call_id=result.call_id, structured_output=value)

    monkeypatch.setattr(path_draft, 'execute_registered_structured_call', gateway)
    args = dict(current_user=user, course_id=course.id, profile_snapshot_id=profile.id,
                time_budget_minutes=45, full_coverage=True, llm=_RealPathBackend(),
                idempotency_key='synthetic-independent-revision')
    with pytest.raises(path_draft.PathDraftError):
        path_draft.generate_textbook_path_draft(db, **args)
    db.rollback()
    assert len(generated) == 1  # no unverified proposal reaches the next batch
    assert {row.id for row in db.query(DBPlanVersion)} == original_versions
    plan, _ = path_draft.generate_textbook_path_draft(db, **args)
    assert len(editorial_calls) == 1  # preserved first edit, no regeneration
    assert len(checks) == 3
    assert generated[1]['earlier_learning_steps'][0]['teaching_goal'] == correct
    first = db.query(DBModelCall).filter_by(prompt_version='p1_b11_personalized_learning_path_batch:1.0').first()
    assert first.input_summary['path_teaching_review']['output']['plan']['nodes'][0]['teaching_goal'] == wrong
    verified = first.input_summary['path_teaching_verified_result']
    assert len(verified['verification_call_ids']) == 2
    assert verified['output']['plan']['nodes'][0]['teaching_goal'] == correct
    assert len(first.input_summary['path_teaching_verification_0_failures']) == 1
    assert db.get(DBPlanVersion, plan.current_version_id).content['nodes'][0]['teaching_goal'] == correct
    before = (len(checks), len(generated), len(editorial_calls))
    path_draft.generate_textbook_path_draft(db, **args)
    assert before == (len(checks), len(generated), len(editorial_calls))


def test_review_output_limit_recovers_only_review_and_reuses_the_result(case, monkeypatch):
    from app.m5_capabilities import M5CapabilityError
    from llm_client import ModelOutputLimitError
    db, user, course, profile, *_ = case
    generated = patch_model(monkeypatch)
    original = path_draft.execute_registered_structured_call
    budgets = []

    async def gateway(db, **kwargs):
        request = json.loads(kwargs['user_prompt'])
        if kwargs['role'] == '学习路径教学复核' and request['batch_index'] == 1:
            budgets.append(kwargs['backend'].max_tokens)
            if len(budgets) == 1:
                try:
                    raise ModelOutputLimitError('synthetic output exhaustion')
                except ModelOutputLimitError as exc:
                    raise M5CapabilityError('all_model_routes_failed', 'synthetic provider failure') from exc
        return await original(db, **kwargs)

    monkeypatch.setattr(path_draft, 'execute_registered_structured_call', gateway)
    backend = _RealPathBackend()
    backend.max_tokens = 16384
    kwargs = dict(current_user=user, course_id=course.id, profile_snapshot_id=profile.id,
        time_budget_minutes=45, full_coverage=True, llm=backend,
        idempotency_key='synthetic-review-output-recovery')
    path_draft.generate_textbook_path_draft(db, **kwargs)
    assert budgets == [32768, 65536]
    assert sum(r['batch_index'] == 1 for r in generated) == 1
    call = db.query(DBModelCall).filter_by(prompt_version='p1_b11_personalized_learning_path_batch:1.0').first()
    assert call.input_summary['path_teaching_review']['output_limit_recovery']
    assert call.input_summary['path_teaching_review_failures'][0]['output_limit']
    path_draft.generate_textbook_path_draft(db, **kwargs)
    assert budgets == [32768, 65536]


def test_candidate_reuse_ignores_unrelated_edition_but_not_changed_reading(case,monkeypatch):
    db,user,course,profile,*_=case
    generated=patch_model(monkeypatch)
    kwargs=dict(current_user=user,course_id=course.id,profile_snapshot_id=profile.id,time_budget_minutes=45,
                full_coverage=True,llm=_RealPathBackend(),idempotency_key='synthetic-source-edition')
    path_draft.generate_textbook_path_draft(db,**kwargs)
    count=len(generated)
    original=path_draft._course_facts
    changed_reading=False
    target=generated[-1]['context']['course_graph']['chapters'][-1]['id']
    def facts(db,**kwargs):
        value=original(db,**kwargs)
        value['sources']['unrelated-source']=SimpleNamespace(id='unrelated-source',title='其它补充资料',
            filename='extra.md',license_text='test',content_hash='new-edition')
        if changed_reading:
            value['chapter_readings'][target]={**value['chapter_readings'][target], 'text':'本章更新后的完整教学正文。'}
        return value
    monkeypatch.setattr(path_draft,'_course_facts',facts)
    course.version='synthetic-edition-2';db.commit()
    _,changed=path_draft.generate_textbook_path_draft(db,**kwargs)
    assert changed and len(generated)==count
    changed_reading=True
    _,changed=path_draft.generate_textbook_path_draft(db,**kwargs)
    assert changed and len(generated)==count+1
    assert target in generated[-1]['batch_chapter_ids']


def test_full_overview_failure_resumes_without_regenerating_or_reauditing_steps(case, monkeypatch):
    from app.m5_capabilities import M5CapabilityError
    db, user, course, profile, *_ = case
    generated = patch_model(monkeypatch)
    original = path_draft.execute_registered_structured_call
    reviews, overviews = [], []

    async def gateway(db, **kwargs):
        request = json.loads(kwargs['user_prompt'])
        if kwargs['role'] == '学习路径教学复核':
            reviews.append(request)
        if kwargs['role'] == '全程学习安排':
            overviews.append(request)
            if len(overviews) == 1:
                raise M5CapabilityError('provider_call_failed', 'synthetic overview interruption')
        return await original(db, **kwargs)

    monkeypatch.setattr(path_draft, 'execute_registered_structured_call', gateway)
    kwargs = dict(current_user=user, course_id=course.id, profile_snapshot_id=profile.id,
                  time_budget_minutes=40, full_coverage=True, llm=_RealPathBackend(), idempotency_key='overview-resume')
    with pytest.raises(path_draft.PathDraftError, match='全程安排尚未整理'):
        path_draft.generate_textbook_path_draft(db, **kwargs)
    db.rollback()
    counts = (len(generated), len(reviews))
    assert counts[0] > 1 and counts[0] == counts[1]
    plan, changed = path_draft.generate_textbook_path_draft(db, **kwargs)
    assert changed and counts == (len(generated), len(reviews))
    assert overviews[0] == overviews[1]
    assert db.get(DBPlanVersion, plan.current_version_id).content['nodes'] == overviews[-1]['learning_steps']
    assert len(overviews[-1]['learning_steps']) == sum(len(r['required_learning_tasks']) for r in generated)
    assert 'course_graph' not in overviews[-1]['context']  # summarize steps, don't send textbooks again
    assert 'recent_learning_evidence' in overviews[-1]['context']
    assert 'initial_learning_evidence' in overviews[-1]['context']
    projected = path_draft.textbook_path_draft_payload(db, current_user=user, course_id=course.id,
                                                      plan_id=plan.id)
    assert projected['plan']['id'] == plan.id  # an older active path must not replace this report's draft
    assert projected['plan']['total_min_minutes'] == sum(n['estimate_min_minutes'] for n in overviews[-1]['learning_steps'])
    assert projected['plan']['total_minutes'] == sum(n['estimate_max_minutes'] for n in overviews[-1]['learning_steps'])
    other = db.query(DBUser).filter(DBUser.public_id != user.public_id).first()
    with pytest.raises(path_draft.PathDraftError):
        path_draft.textbook_path_draft_payload(db, current_user=other, course_id=course.id, plan_id=plan.id)
    again, changed = path_draft.generate_textbook_path_draft(db, **kwargs)
    assert again.id == plan.id and not changed and len(overviews) == 2


def test_overview_policy_change_preserves_steps_and_keeps_long_localized_summary(case, monkeypatch):
    db, user, course, profile, *_ = case
    generated = patch_model(monkeypatch)
    original = path_draft.execute_registered_structured_call
    overviews, reviews = [], []
    long_summary = ('Each step preserves the learner’s confirmed language and independent task. ' * 40).strip()
    full_goal = 'Use the complete learning route to build and check a usable result.'

    async def gateway(db, **kwargs):
        result = await original(db, **kwargs)
        if kwargs['role'] == '学习路径教学复核':
            reviews.append(result.call_id)
        if kwargs['role'] == '全程学习安排':
            request = json.loads(kwargs['user_prompt'])
            overviews.append(request)
            value = {**result.structured_output, 'goal': full_goal, 'personalization_summary': long_summary}
            kwargs['response_validator'](value)
            return SimpleNamespace(call_id=result.call_id, structured_output=value)
        return result

    monkeypatch.setattr(path_draft, 'execute_registered_structured_call', gateway)
    kwargs = dict(current_user=user, course_id=course.id, profile_snapshot_id=profile.id,
                  time_budget_minutes=40, full_coverage=True, llm=_RealPathBackend(), idempotency_key='overview-policy')
    plan, _ = path_draft.generate_textbook_path_draft(db, **kwargs)
    nodes = db.get(DBPlanVersion, plan.current_version_id).content['nodes']
    counts = (len(generated), len(reviews))
    monkeypatch.setattr(path_draft, 'PATH_OVERVIEW_INSTRUCTION', path_draft.PATH_OVERVIEW_INSTRUCTION + '保留最终成果。')
    plan, changed = path_draft.generate_textbook_path_draft(db, **kwargs)
    assert changed and counts == (len(generated), len(reviews)) and len(overviews) == 2
    assert db.get(DBPlanVersion, plan.current_version_id).content['nodes'] == nodes
    assert db.get(DBPlanVersion, plan.current_version_id).content['goal'] == full_goal
    saved = [r.input_summary['path_overview_result']['output'] for r in db.query(DBModelCall)
             if 'path_overview_result' in r.input_summary]
    assert len(saved) == 2 and all(r['personalization_summary'] == long_summary for r in saved)


def test_full_path_workload_respects_both_time_capacity_and_prerequisite_sessions():
    nodes = [path_draft.PlanNodeSpec(node_key=f'node-{i}', node_type='chapter', target_object_id='chapter',
             title=f'Step {i}', resource_status='existing', estimate_min_minutes=10, estimate_max_minutes=20,
             prerequisites=(f'node-{i-1}',) if i else ()) for i in range(12)]
    snapshot = {'learning_adaptation': {'learning_requirements': {'study_schedule': '每周一、三、五，各40分钟'}}}
    timing = path_draft._path_timing(nodes, snapshot=snapshot, time_budget_minutes=40)
    assert timing['total_min_minutes'] == 120 and timing['total_max_minutes'] == 240
    assert timing['weekly_capacity_minutes'] == 120
    assert timing['minimum_sessions'] == 3 and timing['minimum_weeks'] == 1
    # No confirmed time allowance retains the one-frontier calendar rule.
    unconfirmed = path_draft._path_timing(nodes, snapshot={}, time_budget_minutes=40)
    assert unconfirmed['minimum_sessions'] == 12 and unconfirmed['minimum_weeks'] is None
    # Parallel work still consumes actual time; no calendar is inferred without confirmed days.
    independent = [n.model_copy(update={'prerequisites': (), 'estimate_min_minutes': 35, 'estimate_max_minutes': 40}) for n in nodes]
    timing = path_draft._path_timing(independent, snapshot={}, time_budget_minutes=40)
    assert timing['minimum_sessions'] == 11
    assert timing['minimum_weeks'] is None and timing['weekly_capacity_minutes'] is None
    variable = {'learning_adaptation': {'learning_requirements': {
        'study_schedule': '每周二、四各60分钟，周日90分钟'}}}
    timing = path_draft._path_timing(independent, snapshot=variable, time_budget_minutes=60)
    assert timing['study_minutes_by_weekday'] == {1:60,3:60,6:90}
    assert timing['weekly_capacity_minutes'] == 210
    assert timing['minimum_sessions'] == 5 and timing['minimum_weeks'] == 2


def test_default_calendar_keeps_tasks_beyond_sixty_days(case,monkeypatch):
    from app import m5_learning
    db,user,course,*_=case
    _,path=generate_and_confirm(case,monkeypatch)
    def projection(_db,*,owner_public_id,path):
        nodes=[{'id':f'synthetic-{i}','node_key':f'synthetic-{i}','title':f'任务{i}',
                'status':'pending','completed_today':False,'prerequisites':[f'synthetic-{i-1}'] if i else [],
                'priority':80,'sequence':i,'estimate_minutes':10,'continue_route':'/workspace/path'} for i in range(75)]
        return {'path_id':path.id,'course_id':course.id,'course':{'title':course.title},'status':'active',
                'time_budget_minutes':10,'time_budget_confirmed':True,'study_weekdays':[],
                'nodes':nodes if path.id==selected_path else []}
    selected_path=path.id
    monkeypatch.setattr(m5_learning,'_schedule_course_projection',projection)
    schedule=m5_learning.multi_course_schedule(db,owner_public_id=user.public_id,course_id=course.id,selected_day=75)
    assert schedule['total_days']==75
    assert schedule['selected']['tasks'][0]['node_key']=='synthetic-74'


def test_early_outcome_splits_training_without_skipping_conceptual_prerequisites():
    from copy import deepcopy
    knowledge = {key: SimpleNamespace(title=key, prerequisites=before) for key, before in {
        'data': [], 'calculus': [], 'prediction': ['data'], 'loss': ['prediction'],
        'gradient': ['loss', 'calculus'], 'validation': ['loss'],
    }.items()}
    tasks = [{'node_key': key, 'target_object_id': 'chapter-'+key, 'title': key,
              'knowledge_point_ids': points, 'teaching_unit_key': 'unit-'+key,
              'teaching_goal': goal, 'prerequisites': []} for key, points, goal in [
        ('intro', ['data'], '认识数据'), ('math', ['calculus'], '理解变化率'),
        ('linear', ['prediction', 'loss', 'gradient'], '从预测到参数更新'),
        ('compare', ['validation'], '比较模型与选择边界'),
    ]]
    before = deepcopy(tasks)
    output = path_sequence.PathSequenceOutput(near_term_outcome='根据给定预测表作一次验证选择', basis='会读表但不会编程',
        early_tasks=(path_sequence.EarlyLearningTask(task_key='linear', knowledge_point_ids=('prediction','loss'),
                     teaching_goal='先逐行核算给定预测误差'),
                     path_sequence.EarlyLearningTask(task_key='compare', knowledge_point_ids=('validation',),
                     teaching_goal='按同一验证数据选择，测试集留到最后')))
    result = path_sequence.apply_task_sequence(tasks, knowledge, output)
    assert [t['knowledge_point_ids'] for t in result] == [
        ['data'], ['prediction','loss'], ['validation'], ['calculus'], ['gradient']]
    assert result[-1]['prerequisites'] == [result[1]['node_key'], 'math']
    assert result[2]['prerequisites'] == [result[1]['node_key']]
    assert result[1]['target_object_id'] == result[-1]['target_object_id'] == 'chapter-linear'
    assert result[1]['teaching_unit_key'] == result[-1]['teaching_unit_key'] == 'unit-linear'
    assert '从预测到参数更新' in result[-1]['teaching_goal']
    assert 'prediction、loss' in result[-1]['teaching_goal']
    assert result[3]['teaching_goal'] == '理解变化率'
    assert tasks == before
    assert {(t['teaching_unit_key'], p) for t in tasks for p in t['knowledge_point_ids']} == {
        (t['teaching_unit_key'], p) for t in result for p in t['knowledge_point_ids']}
    # Selecting the outcome alone must not pull the entire training unit
    # (and calculus) forward just because its loss prerequisite lives there.
    outcome_only = output.model_copy(update={'early_tasks': (output.early_tasks[1],)})
    automatic = path_sequence.apply_task_sequence(tasks, knowledge, outcome_only)
    assert [t['knowledge_point_ids'] for t in automatic] == [
        ['data'], ['prediction','loss'], ['validation'], ['calculus'], ['gradient']]
    for changes in [
        [output.early_tasks[0], output.early_tasks[0]],
        [output.early_tasks[0].model_copy(update={'knowledge_point_ids': ('foreign',)})],
        [output.early_tasks[0].model_copy(update={'task_key': 'foreign'})],
    ]:
        with pytest.raises(ValueError):
            path_sequence.apply_task_sequence(tasks, knowledge, output.model_copy(update={'early_tasks': tuple(changes)}))


def test_early_scope_reaches_resource_context_and_is_reused_after_restart(case, monkeypatch):
    from copy import deepcopy
    db, user, course, profile, chapter, first, second = case
    structure = deepcopy(course.manifest_data['structure_workspace']['applied']['structure'])
    structure['units'] = [{'key':'combined', 'title':'从基础到应用', 'goal':'先判断再应用',
                          'knowledge_point_ids':[first, second]}]
    course.manifest_data = {**course.manifest_data, 'structure_workspace':{'applied':{'structure':structure}}}
    db.flush()
    generated = patch_model(monkeypatch)
    original = path_sequence.execute_registered_structured_call
    sequence_requests = []

    async def choose(db, **kwargs):
        request = json.loads(kwargs['user_prompt'])
        sequence_requests.append(request)
        task = next(t for t in request['course_tasks'] if t['teaching_unit_key'] == 'combined')
        result = await original(db, **kwargs)
        result.structured_output.update({'early_tasks':[
            {'task_key':task['node_key'], 'knowledge_point_ids':[first], 'teaching_goal':'根据给定例子独立解释基础判断'}]})
        return result

    monkeypatch.setattr(path_sequence, 'execute_registered_structured_call', choose)
    kwargs = dict(current_user=user, course_id=course.id, profile_snapshot_id=profile.id,
                  time_budget_minutes=30, full_coverage=True, llm=_RealPathBackend(), idempotency_key='early-scope')
    plan, _ = path_draft.generate_textbook_path_draft(db, **kwargs)
    path = confirm_plan(db, plan=plan, owner_public_id=user.public_id, expected_lock_version=plan.lock_version)
    nodes = db.query(DBPathNode).filter_by(learning_path_id=path.id).order_by(DBPathNode.sequence).all()
    first_node = next(n for n in nodes if n.target_object_id == chapter.id)
    ctx = _generation_context(db, owner_public_id=user.public_id, course_id=course.id, node=first_node)
    assert ctx['knowledge_point_ids'] == [first]
    assert ctx['teaching_goal'] == '根据给定例子独立解释基础判断'
    assert ctx['source_ref_ids'] and ctx['teaching_unit_key'] == 'combined'
    assert generated[0]['near_term_learning']['early_tasks'][0]['knowledge_point_ids'] == [first]
    later_node = next(n for n in nodes if n.target_object_id == chapter.id and n.id != first_node.id)
    later_ctx = _generation_context(db, owner_public_id=user.public_id, course_id=course.id, node=later_node)
    assert later_ctx['knowledge_point_ids'] == [second]
    assert '先判断再应用' in later_ctx['teaching_goal']
    assert later_ctx['source_ref_ids'] and later_ctx['teaching_unit_key'] == 'combined'
    # A subsequent overview policy change continues from the same saved choice and batches.
    count = len(generated)
    monkeypatch.setattr(path_draft, 'PATH_OVERVIEW_INSTRUCTION', path_draft.PATH_OVERVIEW_INSTRUCTION + '合成更新')
    path_draft.generate_textbook_path_draft(db, **kwargs)
    assert len(sequence_requests) == 1 and len(generated) == count


def test_batch_reviewer_gets_teaching_order_even_when_model_uses_catalogue_order():
    tasks = [{'node_key':key, 'target_object_id':'chapter-'+key, 'title':key,
              'knowledge_point_ids':[key], 'teaching_unit_key':'unit-'+key,
              'teaching_goal':'完成当前学习任务', 'prerequisites':[]} for key in ['compare','program']]
    nodes = [path_draft.PlanNodeSpec(**task, node_type='chapter', resource_status='existing',
             estimate_min_minutes=10, estimate_max_minutes=20) for task in reversed(tasks)]
    output = path_draft.PathDraftModelOutput(plan=PlanSpec(goal='先判断再实现', nodes=tuple(nodes)),
                                           personalization_summary='依据学习目标先判断，再补实现准备。')
    result = path_draft._validate_task_batch(output, tasks, time_budget_minutes=30)
    assert [n.node_key for n in result.plan.nodes] == ['compare','program']
    assert [n.node_key for n in output.plan.nodes] == ['program','compare']


def test_selected_middle_concept_does_not_create_a_false_cycle_with_remainder():
    knowledge={key:SimpleNamespace(title=key,prerequisites=before) for key,before in {
        'loss':[], 'generalization':['loss'], 'split':['generalization'], 'choice':['split'],
    }.items()}
    tasks=[{'node_key':key,'target_object_id':'chapter-'+key,'title':key,'knowledge_point_ids':points,
            'teaching_unit_key':'unit-'+key,'teaching_goal':'理解并应用','prerequisites':[]} for key,points in [
        ('loss',['loss']),('validation',['generalization','split','choice'])]]
    output=path_sequence.PathSequenceOutput(near_term_outcome='能解释训练验证测试分工',basis='具体误解',
        early_tasks=(path_sequence.EarlyLearningTask(task_key='validation',knowledge_point_ids=('split',),
                                                    teaching_goal='按用途划分数据'),))
    result=path_sequence.apply_task_sequence(tasks,knowledge,output)
    assert [t['knowledge_point_ids'] for t in result]==[['loss'],['generalization'],['split'],['choice']]
