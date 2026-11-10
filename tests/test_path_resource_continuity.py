"""Synthetic records and model doubles: actual path/version continuity contracts."""
from copy import deepcopy
import hashlib
import json
import pytest

from app import resource_bundles
from app.database import (
    DBArtifact, DBArtifactVersion, DBGenerationTask, DBLearningEvent,
    DBPathNode, DBPlanVersion, DBTaskEvent, DBUser,
)
from app.m5_learning import _generation_context, _publish_path
from app.path_learning_context import preceding_learning_context
from tests.test_path_teaching_units import case, generate_and_confirm
from tests.test_pr_01_b35_b09_resource_supervisor import _SupervisorBackend


def _prior(db, user, course, path, node, *, suffix='first', owner=None, version_id=None):
    task = DBGenerationTask(owner_public_id=owner or user.public_id, course_id=course.id,
        trace_id='synthetic-continuity', capability=resource_bundles.GENERATION_CAPABILITY,
        idempotency_key='prior-'+suffix, status='completed')
    db.add(task); db.flush()
    db.add(DBTaskEvent(task_id=task.id, sequence=1, event_type='resource_generation.requested', payload={
        'manifest': {'exam_gate': {'path_id':path.id, 'path_version_id':version_id or path.source_plan_version_id,
                                 'selected_task_id':node.id}}}))
    artifact = DBArtifact(owner_public_id=owner or user.public_id, course_id=course.id,
        artifact_type='code_sandbox', title='原表格与代码', status='published', creating_task_id=task.id)
    db.add(artifact); db.flush()
    version = _version(db, artifact, task.id, 'data = [4, 7, 9]\nprint(sum(data))', 1)
    return artifact, version, task


def _version(db, artifact, task_id, code, number):
    content = json.dumps({'starterCode':code}, ensure_ascii=False)
    version = DBArtifactVersion(artifact_id=artifact.id, version_number=number,
        content=content, content_format='json', content_hash=hashlib.sha256(content.encode()).hexdigest(),
        created_task_id=task_id, metadata_json={'resource_type':'code_sandbox', 'generation_job_id':task_id})
    db.add(version); db.flush(); artifact.current_version_id=version.id; db.flush()
    return version


def _target(case, path, node, key):
    db, user, course, *_ = case
    ctx = _generation_context(db,owner_public_id=user.public_id,course_id=course.id,node=node)
    return resource_bundles.create_generation_job(db,user,course_id=course.id,
        knowledge_point_id=ctx['knowledge_point_id'], profile_snapshot_id=ctx['profile_snapshot_id'],
        path_id=path.id,task_id=node.id,idempotency_key=key,scope='single',
        items=[{'type':'handout','title':'继续学习','source_ref_ids':ctx['source_ref_ids']}])


def _event(db, user, course, node, artifact, version, **kwargs):
    row=DBLearningEvent(owner_public_id=user.public_id,course_id=course.id,event_type='code_tests_passed',
        object_type='artifact',object_id=artifact.id,context_ref={'taskId':node.id},
        payload={'resource_version_id':version.id, **kwargs},trace_id='synthetic-continuity',
        evidence_status='accepted',mastery_eligible=True,evidence_strength=.8,completion_effect='complete')
    db.add(row); db.flush(); return row


def _nodes(case, path):
    return case[0].query(DBPathNode).filter_by(learning_path_id=path.id).order_by(DBPathNode.sequence).all()


def test_prepared_inputs_are_frozen_without_manufacturing_learning(case, monkeypatch):
    db,user,course,*_=case
    _,path=generate_and_confirm(case,monkeypatch)
    first,second,*_=_nodes(case,path)
    artifact,version,task=_prior(db,user,course,path,first)
    before=db.query(DBLearningEvent).count()
    job=_target(case,path,second,'frozen-continuity')
    manifest=resource_bundles._generation_manifest(db,job['job_id'])
    context=manifest['context']['path_learning_context']
    previous=context['prior_steps'][0]
    assert previous['task_id']==first.id
    assert previous['resources'][0]['version_id']==version.id
    assert previous['resources'][0]['use']=='prepared_material'
    assert '4, 7, 9' in previous['resources'][0]['content']
    assert previous['learning_results']==[] and not previous['completion_supported']
    assert db.query(DBLearningEvent).count()==before
    assert manifest['input_snapshot']['path_learning_context']==context
    assert manifest['input_snapshot']['semantic_context']['path_learning_context']==context
    plan_content=db.get(DBPlanVersion,path.source_plan_version_id).content
    assert context['path_goal']==plan_content['goal']
    assert context['path_conditions']==plan_content['assumptions']
    _version(db,artifact,task.id,'data = [100, 200]',2)
    again=_target(case,path,second,'frozen-continuity')
    assert again['created'] is False and again['job_id']==job['job_id']
    assert resource_bundles._generation_manifest(db,job['job_id'])['context']['path_learning_context']==context
    changed=_target(case,path,second,'updated-continuity')
    current=resource_bundles._generation_manifest(db,changed['job_id'])
    assert current['input_snapshot']['input_snapshot_hash']!=manifest['input_snapshot']['input_snapshot_hash']
    assert '100, 200' in current['context']['path_learning_context']['prior_steps'][0]['resources'][0]['content']


def test_actual_old_version_and_submitted_code_reach_all_model_roles(case,monkeypatch):
    db,user,course,_,_,point,*_=case
    _,path=generate_and_confirm(case,monkeypatch)
    first,second,*_=_nodes(case,path)
    artifact,version,task=_prior(db,user,course,path,first)
    from app.code_sandbox import RUN_ARTIFACT_TYPE
    run=DBArtifact(owner_public_id=user.public_id,course_id=course.id,artifact_type=RUN_ARTIFACT_TYPE,
                   title='真实运行记录的合成夹具',status='approved')
    db.add(run); db.flush()
    run_content=json.dumps({'sourceResourceId':artifact.id,'sourceResourceVersionId':version.id,
        'ownerPublicId':user.public_id,'code':'data=[4,7,9]\nprint(sum(data)/len(data))',
        'stdout':'preview','stdoutComplete':{'available':True,'text':'6.666666666666667\n','capture':{'truncated':False}},
        'status':'success','checks':[{'passed':True}],'passedCount':1,'totalCount':1})
    rv=DBArtifactVersion(artifact_id=run.id,version_number=1,content=run_content,content_format='json',content_hash='synthetic')
    db.add(rv); db.flush();run.current_version_id=rv.id
    event=_event(db,user,course,first,artifact,version,run_id=run.id,knowledge_point_id=point)
    _version(db,artifact,task.id,'data=[999]',2)
    job=_target(case,path,second,'learned-continuity')
    manifest=resource_bundles._generation_manifest(db,job['job_id'])
    before=deepcopy(manifest['context']['path_learning_context'])
    previous=before['prior_steps'][0]
    assert previous['completion_supported']
    assert [item['version_id'] for item in previous['resources']]==[version.id]
    work=previous['learning_results'][0]
    assert work['event_id']==event.id and work['code_run']['version_id']==rv.id
    assert work['code_run']['stdout']=='6.666666666666667\n'
    assert 'sum(data)/len(data)' in work['code_run']['code']
    assert all('data=[999]' not in item['content'] for item in previous['resources'])
    backend=_SupervisorBackend()
    monkeypatch.setattr(resource_bundles,'_real_model_backend',lambda:backend)
    result=resource_bundles.execute_generation_job(db,user,job['job_id'])
    assert result['status']=='succeeded'
    for role in ('resource_planner','resource_generator','resource_reviewer'):
        received=next(data for actual,data in backend.inputs if actual==role)
        expected = ({key: value for key, value in before.items()
                     if key not in {'path_goal', 'path_conditions'}}
                    if role == 'resource_reviewer' else before)
        assert received['course']['path_learning_context'] == expected


def test_other_owners_unrelated_steps_and_different_path_versions_are_excluded(case,monkeypatch):
    db,user,course,*_=case
    _,path=generate_and_confirm(case,monkeypatch)
    first,second,unrelated,*_=_nodes(case,path)
    good,version,_=_prior(db,user,course,path,first)
    from app.database import DBUser
    other=db.query(DBUser).filter(DBUser.public_id!=user.public_id).first()
    _prior(db,user,course,path,first,suffix='other',owner=other.public_id)
    _prior(db,user,course,path,first,suffix='wrong-version',version_id='another-plan-version')
    _prior(db,user,course,path,unrelated,suffix='future')
    context=preceding_learning_context(db,owner_public_id=user.public_id,course_id=course.id,path_id=path.id,task_id=second.id)
    assert [row['task_id'] for row in context['prior_steps']]==[first.id]
    assert [row['version_id'] for row in context['prior_steps'][0]['resources']]==[version.id]
    assert preceding_learning_context(db,owner_public_id=other.public_id,course_id=course.id,path_id=path.id,task_id=second.id) is None
    assert preceding_learning_context(db,owner_public_id=user.public_id,course_id='another-course',path_id=path.id,task_id=second.id) is None


def test_compatible_replan_keeps_the_actual_preceding_resource(case,monkeypatch):
    db,user,course,*_=case
    plan,path=generate_and_confirm(case,monkeypatch)
    first,second,*_=_nodes(case,path)
    _,version,_=_prior(db,user,course,path,first)
    old=db.get(DBPlanVersion,path.source_plan_version_id)
    revised=DBPlanVersion(plan_draft_id=plan.id,version_number=2,content=deepcopy(old.content),content_hash='synthetic-replan')
    db.add(revised);db.flush()
    new_path=_publish_path(db,plan=plan,version=revised,previous_path=path)
    new_first,new_second,*_=_nodes(case,new_path)
    result=preceding_learning_context(db,owner_public_id=user.public_id,course_id=course.id,
        path_id=new_path.id,task_id=new_second.id)
    assert result['path_version_id']==revised.id
    assert result['prior_steps'][0]['task_id']==new_first.id
    assert result['prior_steps'][0]['resources'][0]['version_id']==version.id


def test_same_topic_does_not_make_another_steps_code_a_current_companion(case,monkeypatch):
    db,user,course,*_=case
    _,path=generate_and_confirm(case,monkeypatch)
    first,second,*_=_nodes(case,path)
    current,current_version,_=_prior(db,user,course,path,second,suffix='current-step')
    wrong,wrong_version,_=_prior(db,user,course,path,first,suffix='different-step')
    job=_target(case,path,second,'companion-scope')
    manifest=resource_bundles._generation_manifest(db,job['job_id'])
    # Identical source and concept alone used to select the other task's code.
    for version in (current_version,wrong_version):
        request = db.query(DBTaskEvent).filter_by(task_id=version.created_task_id,
            event_type='resource_generation.requested').one()
        # Current companions also share the learning contract, beyond the
        # topic/source coincidence intentionally set up by this fixture.
        request.payload = {'manifest': {**request.payload['manifest'],
            'input_snapshot': manifest['input_snapshot'], 'context': manifest['context'],
            'user_instruction':manifest.get('user_instruction', '')}}
        version.metadata_json={**version.metadata_json,
            'knowledge_point_id':manifest['knowledge_point_id'],
            'source_ref_ids':manifest['items'][0]['source_ref_ids'],
            'source_snapshot_hash':manifest['input_snapshot']['source_snapshot_hashes']['handout']}
    db.flush()
    task=db.get(DBGenerationTask,job['job_id'])
    _,latest=resource_bundles._task_steps(db,task.id)
    deps=resource_bundles._practical_dependencies(db,task,latest,resource_type='handout')
    assert [item['version_id'] for item in deps]==[current_version.id]
    assert manifest['context']['path_learning_context']['prior_steps'][0]['resources'][0]['version_id']==wrong_version.id


def test_predecessor_parts_keep_original_inputs_and_unscoped_experiment_feedback(case,monkeypatch):
    from app import path_draft
    from app.m5_learning import confirm_plan
    from tests.test_path_teaching_units import patch_model, _RealPathBackend
    db,user,course,profile,*_=case
    patch_model(monkeypatch,split_first=True)
    plan,_=path_draft.generate_textbook_path_draft(db,current_user=user,course_id=course.id,
        profile_snapshot_id=profile.id,time_budget_minutes=45,full_coverage=True,
        llm=_RealPathBackend(),idempotency_key='split-continuity')
    path=confirm_plan(db,plan=plan,owner_public_id=user.public_id,expected_lock_version=plan.lock_version)
    first,second,following,*_=_nodes(case,path)
    artifact,version,_=_prior(db,user,course,path,first)
    point=db.get(DBPlanVersion,path.source_plan_version_id).content['nodes'][0]['knowledge_point_ids'][0]
    artifact.artifact_type='interactive_model'
    version.content=json.dumps({'dataset':{'values':[4,7,9]},'parameters':[{'key':'learning_rate','value':.1}]})
    version.content_hash=hashlib.sha256(version.content.encode()).hexdigest()
    version.metadata_json={**version.metadata_json,'resource_type':'interactive_model','knowledge_point_id':point}
    event=DBLearningEvent(owner_public_id=user.public_id,course_id=course.id,
        event_type='interactive_model_observation_submitted',object_type='interactive_model',object_id=artifact.id,
        context_ref={'resource_version_id':version.id,'knowledge_point_id':point},
        payload={'observation':'保持同一数据，只改变步长后损失上升。','hint_count':2},
        trace_id='synthetic-continuity',evidence_status='accepted',mastery_eligible=True,evidence_strength=.5,
        completion_effect='complete')
    db.add(event);db.flush()
    context=preceding_learning_context(db,owner_public_id=user.public_id,course_id=course.id,
                                      path_id=path.id,task_id=following.id)
    assert [item['task_id'] for item in context['prior_steps']]==[first.id,second.id]
    original=context['prior_steps'][0]
    assert [item['version_id'] for item in original['resources']]==[version.id]
    assert [item['event_id'] for item in original['learning_results']]==[event.id]
    assert original['learning_results'][0]['payload']['hint_count']==2
    assert original['completion_supported']
    assert context['prior_steps'][1]['learning_results']==[]
    assert not context['prior_steps'][1]['completion_supported']


@pytest.mark.parametrize('kind', ['code_tests_passed', 'interactive_model_observation_submitted', 'feynman_submitted'])
def test_resource_version_connects_actual_work_to_exact_stage_without_route_context(case, monkeypatch, kind):
    from app import path_draft
    from app.m5_learning import confirm_plan
    from app.learning_aggregation import _event_matches_node, _project_path
    from tests.test_path_teaching_units import patch_model, _RealPathBackend

    db, user, course, profile, *_ = case
    patch_model(monkeypatch, split_first=True)
    plan, _ = path_draft.generate_textbook_path_draft(db, current_user=user, course_id=course.id,
        profile_snapshot_id=profile.id, time_budget_minutes=45, full_coverage=True,
        llm=_RealPathBackend(), idempotency_key='resource-stage-'+kind)
    path = confirm_plan(db, plan=plan, owner_public_id=user.public_id, expected_lock_version=plan.lock_version)
    first, second, *_ = _nodes(case, path)
    artifact, version, task = _prior(db, user, course, path, first)
    point = db.get(DBPlanVersion, path.source_plan_version_id).content['nodes'][0]['knowledge_point_ids'][0]
    version.metadata_json = {**version.metadata_json, 'knowledge_point_id': point}
    event = _event(db, user, course, first, artifact, version, knowledge_point_id=point)
    event.event_type = kind
    event.context_ref = {}
    if kind == 'interactive_model_observation_submitted':
        event.context_ref = {'resource_version_id': version.id}
        event.payload = {'knowledge_point_id': point, 'observation': '仅作观察，不代表已经独立掌握。'}
    elif kind == 'feynman_submitted':
        event.payload = {'knowledge_point_id': point, 'source_resource_version_id': version.id, 'rubric_score': .9}
    if kind != 'feynman_submitted':
        event.evidence_status = 'none'
        event.mastery_eligible = False
        event.evidence_strength = 0
        event.completion_effect = 'progress'
        event.payload = {**event.payload, 'evidence_kind': 'guided_practice'}
    db.flush()
    assert _event_matches_node(db, event, first)
    assert not _event_matches_node(db, event, second)
    _project_path(db, event)
    assert first.status == ('completed' if kind == 'feynman_submitted' else 'in_progress')
    assert second.status == 'pending'
    context = preceding_learning_context(db, owner_public_id=user.public_id, course_id=course.id,
                                         path_id=path.id, task_id=second.id)
    assert context['prior_steps'][0]['learning_results'][0]['event_id'] == event.id
    assert context['prior_steps'][0]['completion_supported'] == (kind == 'feynman_submitted')

    # A compatible replan retains the exact studied version and its stage.
    old = db.get(DBPlanVersion, path.source_plan_version_id)
    revised = DBPlanVersion(plan_draft_id=plan.id, version_number=2, content=deepcopy(old.content), content_hash='replan-resource')
    db.add(revised); db.flush()
    new_path = _publish_path(db, plan=plan, version=revised, previous_path=path)
    new_first, new_second, *_ = _nodes(case, new_path)
    assert _event_matches_node(db, event, new_first)
    assert not _event_matches_node(db, event, new_second)

    event.context_ref = {**event.context_ref, 'taskId': second.id}
    assert not _event_matches_node(db, event, first)
    event.context_ref = {key: value for key, value in event.context_ref.items() if key != 'taskId'}
    for attribute, bad_value in [('object_id', 'unrelated-resource'), ('course_id', 'unrelated-course'),
                                 ('owner_public_id', 'unrelated-owner')]:
        original = getattr(event, attribute)
        with db.no_autoflush:
            setattr(event, attribute, bad_value)
            assert not _event_matches_node(db, event, first)
            setattr(event, attribute, original)
    request = db.query(DBTaskEvent).filter_by(task_id=task.id, event_type='resource_generation.requested').one()
    changed = deepcopy(request.payload)
    changed['manifest']['exam_gate']['path_version_id'] = 'unrelated-plan-version'
    request.payload = changed
    assert not _event_matches_node(db, event, first)


@pytest.mark.parametrize('used_hints,first_correct', [(False, True), (True, True), (False, False)])
def test_quiz_attempt_keeps_actual_resource_version_and_stage_with_its_grade(case, monkeypatch, used_hints, first_correct):
    from types import SimpleNamespace
    from app import path_draft
    from app.m5_learning import confirm_plan
    from app.m5_assessment_core import AttemptInput, AssessmentCoreError, record_attempt
    from app.m5_assessment import record_canonical_attempt_evidence
    from tests.test_path_teaching_units import patch_model, _RealPathBackend

    db, user, course, profile, *_ = case
    patch_model(monkeypatch, split_first=True)
    plan, _ = path_draft.generate_textbook_path_draft(db, current_user=user, course_id=course.id,
        profile_snapshot_id=profile.id, time_budget_minutes=45, full_coverage=True,
        llm=_RealPathBackend(), idempotency_key='quiz-source-stage')
    path = confirm_plan(db, plan=plan, owner_public_id=user.public_id, expected_lock_version=plan.lock_version)
    first, second, *_ = _nodes(case, path)
    point = db.get(DBPlanVersion, path.source_plan_version_id).content['nodes'][0]['knowledge_point_ids'][0]
    artifact, version, _ = _prior(db, user, course, path, first)
    artifact.artifact_type = 'quiz'
    version.content = resource_bundles._create_quiz_resource_content(db, actor=user,
        task=SimpleNamespace(course_id=course.id), item={'title': '已确认单元的学习检查'},
        manifest={'knowledge_point_id': point, 'context': {'knowledge_point_title': '单元学习'}},
        source_snapshots=[{'source_ref_id': 'demo-ref-07'}], llm_payload={
            'learningGoal': '独立完成计算并核对理由', 'summary': '学习检查',
            'quizQuestions': [{'prompt': f'{index}+1等于多少？', 'options': [str(index+1),'10','20','30'],
                'answer': 'A', 'explanation': f'{index}+1={index+1}。'} for index in range(3)]})
    version.metadata_json = {**version.metadata_json, 'resource_type': 'quiz', 'knowledge_point_id': point,
                             'source_ref_ids': ['demo-ref-07']}
    question_id = json.loads(version.content)['questions'][0]['questionVersionId']
    original_version_id = version.id
    request = AttemptInput(question_version_id=question_id, idempotency_key='quiz-stage-evidence',
        answer={'choice': 'A' if first_correct else 'B', 'resource_version_id': version.id, 'used_hints': used_hints})
    attempt, _ = record_attempt(db, owner_public_id=user.public_id, attempt=request)
    result = record_canonical_attempt_evidence(db, attempt=attempt, user=user)
    event = db.get(DBLearningEvent, result['event_id'])
    assert event.context_ref['taskId'] == first.id
    assert event.context_ref['knowledgePointId'] == point
    assert event.payload['resource_version_id'] == original_version_id
    assert event.mastery_eligible == (not used_hints)
    assert first.status == 'in_progress'  # one correct answer cannot finish the three-question task
    assert second.status == 'pending'
    assert attempt.correct == first_correct and attempt.score == int(first_correct)

    question_refs = json.loads(version.content)['questions']
    for index, reference in enumerate(question_refs[1:], 1):
        more, _ = record_attempt(db, owner_public_id=user.public_id, attempt=AttemptInput(
            question_version_id=reference['questionVersionId'], idempotency_key=f'quiz-stage-{index}',
            answer={'choice': 'A', 'resource_version_id': version.id}))
        record_canonical_attempt_evidence(db, attempt=more, user=user)
        if index == 1:
            assert first.status == 'in_progress'
    # The hinted answer is still useful progress, but does not prove independent completion.
    assert first.status == ('completed' if first_correct and not used_hints else 'in_progress')
    assert second.status == 'pending'

    if not first_correct or used_hints:
        correction, _ = record_attempt(db, owner_public_id=user.public_id, attempt=AttemptInput(
            question_version_id=question_id, idempotency_key='quiz-stage-correction',
            answer={'choice': 'A', 'resource_version_id': version.id}))
        correction_result = record_canonical_attempt_evidence(db, attempt=correction, user=user)
        assert correction.score == 1 and first.status == 'in_progress'
        corrected_event = db.get(DBLearningEvent, correction_result['event_id'])
        assert not corrected_event.mastery_eligible
        assert corrected_event.payload['evidence_kind'] == 'correction'

        from app.quiz_practice import create_quiz_practice
        new_job = create_quiz_practice(db, user, resource_id=artifact.id, version_id=version.id)
        manifest = resource_bundles._generation_manifest(db, new_job['job_id'])
        assert manifest['exam_gate']['selected_task_id'] == first.id
        assert manifest['exam_gate']['path_id'] == path.id
        assert manifest['items'][0]['source_ref_ids'] == ['demo-ref-07']
        assert manifest['knowledge_point_id'] == point
        assert 'correction' in manifest['user_instruction'] and '0+1' in manifest['user_instruction']
        again = create_quiz_practice(db, user, resource_id=artifact.id, version_id=version.id)
        assert again['job_id'] == new_job['job_id'] and not again['created']

        # A model double delivers different tasks. They retain the original
        # stage, and only completing the full new group advances it.
        task = db.get(DBGenerationTask, new_job['job_id'])
        fresh_artifact = DBArtifact(owner_public_id=user.public_id, course_id=course.id,
            artifact_type='quiz', title='新题检验', status='published', creating_task_id=task.id)
        db.add(fresh_artifact); db.flush()
        fresh_version = _version(db, fresh_artifact, task.id, '', 1)
        fresh_version.content = resource_bundles._create_quiz_resource_content(db, actor=user,
            task=task, item={'title': '新题检验'}, manifest=manifest,
            source_snapshots=[{'source_ref_id': 'demo-ref-07'}], llm_payload={
                'learningGoal': '独立完成计算并核对理由', 'summary': '学习检查',
                'quizQuestions': [{'prompt': f'{index}+4等于多少？', 'options': [str(index+4),'10','20','30'],
                    'answer': 'A', 'explanation': f'{index}+4={index+4}。'} for index in range(3)]})
        fresh_version.metadata_json = {**fresh_version.metadata_json, 'resource_type':'quiz', 'knowledge_point_id':point}
        task.status = 'completed'; db.flush()
        for index, reference in enumerate(json.loads(fresh_version.content)['questions']):
            fresh_attempt, _ = record_attempt(db, owner_public_id=user.public_id, attempt=AttemptInput(
                question_version_id=reference['questionVersionId'], idempotency_key=f'fresh-stage-{index}',
                answer={'choice':'A', 'resource_version_id':fresh_version.id}))
            fresh_result = record_canonical_attempt_evidence(db, attempt=fresh_attempt, user=user)
            assert db.get(DBLearningEvent, fresh_result['event_id']).mastery_eligible
            assert first.status == ('completed' if index == 2 else 'in_progress')
        assert second.status == 'pending'

    # A new page version cannot overwrite the source of the existing answer.
    replacement = _version(db, artifact, version.created_task_id, 'unrelated later draft', 2)
    same, created = record_attempt(db, owner_public_id=user.public_id, attempt=request)
    replay = record_canonical_attempt_evidence(db, attempt=same, user=user)
    assert not created and not replay['created']
    assert replay['event_id'] == event.id and event.payload['resource_version_id'] == original_version_id
    with pytest.raises(AssessmentCoreError, match='当前学习资料不对应'):
        record_attempt(db, owner_public_id=user.public_id,
            attempt=request.model_copy(update={'idempotency_key':'different-resource-version',
                'answer': {'choice':'A', 'resource_version_id':replacement.id}}))
    other = db.query(DBUser).filter(DBUser.public_id != user.public_id).first()
    with pytest.raises(AssessmentCoreError, match='当前学习资料不对应'):
        record_attempt(db, owner_public_id=other.public_id,
            attempt=request.model_copy(update={'idempotency_key':'foreign-resource-version'}))
