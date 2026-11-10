import asyncio
import json

import pytest

from app import resource_bundles as bundles
from app.resource_review_parts import document_review_scopes, split_review_scope, conditional_teaching_claims, apply_condition_review


def test_bundle_connections_retain_numerical_claims_from_local_reviews(monkeypatch):
    from app import numerical_verification
    candidates = [{'type': kind, 'version_id': kind + '-v',
                   'content': json.dumps({'body': '参考实现的数值秩为8。'}, ensure_ascii=False)}
                  for kind in ('handout', 'deck')]
    calls, cache = [], {}
    async def verify(backend, candidate, **kwargs):
        return {'plan': {'not_computed': [{'path': 'content.body', 'quote': '参考实现的数值秩为8。',
                                          'reason': '未指定矩阵和容差。'}]}, 'findings': []}
    monkeypatch.setattr(numerical_verification, 'verify_numerical_content', verify)
    class Reviewer:
        async def generate(self, system, user, *, role):
            data = json.loads(user)
            calls.append(data)
            if data.get('review_scope', {}).get('stage') == 'consistency':
                assert all(c['runtime_verification']['numerical'] for c in data['candidates'])
                assert not data['condition_claims']
            return json.dumps({'approved': not data['condition_claims'], 'findings': [],
                'rejectedTypes': [], 'conditionReview': [
                    {'claimId': c['id'], 'status': 'incorrect', 'reason': '矩阵未定义。',
                     'fix': '明确矩阵、接口及容差后给出秩。'} for c in data['condition_claims']]})
    def run():
        return asyncio.run(bundles._resource_review_async(Reviewer(),
            manifest={'automated_calculation_check': True}, semantic_plan='', candidates=candidates,
            completed_reviews=cache, save_review=cache.__setitem__))
    result = run()
    assert not result['approved'] and set(result['rejectedTypes']) == {'handout', 'deck'}
    assert len(result['conditionReview']) == 2
    assert all(':uncomputed:' in check['claimId'] for check in result['conditionReview'])
    count = len(calls)
    assert run() == result and len(calls) == count
    assert all('runtime_verification' not in candidate for candidate in candidates)


def test_exhausted_field_split_preserves_complete_code_and_every_condition():
    body = {'steps': [{'instruction': '只有条件成立才能使用本式。',
                      'expectedResult': '结果不一定增加。', 'errorGuidance': '检查已知条件。'}],
            'files': [{'path':'main.py', 'content':'print("unchanged")\n'*2000}]}
    candidates = [{'type':'training_task', 'version_id':'scope-split', 'content':json.dumps(body,ensure_ascii=False)}]
    scope = {'stage':'section', 'candidate_index':0, 'index':0, 'paths':['content.steps[0]']}
    split = split_review_scope(candidates, scope)
    assert len(split) == 2
    paths = [path for part in split for path in part['paths']]
    assert paths == ['content.steps[0].instruction','content.steps[0].expectedResult','content.steps[0].errorGuidance']
    assert [claim for part in split for claim in conditional_teaching_claims(candidates,part)] == conditional_teaching_claims(candidates,scope)
    assert split_review_scope(candidates,{**scope,'paths':['content.files[0].content']}) == []
    consistency = split_review_scope(candidates, {'stage':'consistency'})
    assert len(consistency) == 2 and sum(len(item['checks']) for item in consistency) == 4
    assert split_review_scope(candidates, {'stage':'consistency', 'checks':['one remaining check']}) == []
    assert json.loads(candidates[0]['content']) == body


def test_exhausted_local_review_splits_and_resumes_only_missing_work():
    original = [{'type':'training_task','version_id':'adaptive-review','content':json.dumps({
        'steps':[{'instruction':'只有保留真实标签才能检验本次预测。',
                  'expectedResult':'只要阈值改变，类别一定改变。'}]},ensure_ascii=False)}]
    scope = {'stage':'section','candidate_index':0,'index':4,'paths':['content.steps[0]']}
    cache, calls = {}, []
    class AdaptiveReviewer:
        fail_second = True
        async def generate(self, system, user, *, role):
            data=json.loads(user)
            assert data['candidates'] == original
            current=data['review_scope']['paths']
            calls.append(current)
            if current == ['content.steps[0]']:
                raise bundles.ModelOutputLimitError('exhausted section')
            if current == ['content.steps[0].expectedResult'] and self.fail_second:
                raise RuntimeError('temporary scoped connection failure')
            rejected = current == ['content.steps[0].expectedResult']
            return json.dumps({'approved':not rejected,'rejectedTypes':['training_task'] if rejected else [],
                'findings':[{'resourceType':'training_task','issue':'阈值变化不保证跨过某个分数。','fix':'补充是否跨过分数的条件。'}] if rejected else [],
                'conditionReview':[{'claimId':claim['id'],'status':'incorrect' if rejected else 'valid',
                    'reason':'阈值未跨过分数时类别保持不变。' if rejected else '条件成立。',
                    'fix':'不保证改变。' if rejected else ''} for claim in data['condition_claims']]})
    backend=AdaptiveReviewer()
    def run():
        return asyncio.run(bundles._resource_review_async(backend,manifest={},semantic_plan='完整审核',
            candidates=original,_grouped=True,_review_scope=scope,completed_reviews=cache,save_review=cache.__setitem__))
    with pytest.raises(bundles.ResourceBundleError,match='connection failure'):
        run()
    assert any(value.get('reason')=='output_limit' for value in cache.values())
    done=len(calls)
    backend.fail_second=False
    result=run()
    assert calls[done:] == [['content.steps[0].expectedResult']]
    assert not result['approved'] and result['rejectedTypes']==['training_task']
    assert {item['claimId'] for item in result['conditionReview']} == {item['id'] for item in conditional_teaching_claims(original,scope)}
    done=len(calls)
    assert run()==result and len(calls)==done


def test_review_uses_actual_student_versions_and_excludes_old_writing_references():
    old = {'type':'code_sandbox','resource_id':'old','version_id':'old-v','content':'old writing reference'}
    code = {'type':'code_sandbox','resource_id':'code','version_id':'code-v','content':'current executable'}
    experiment = {'type':'interactive_model','resource_id':'lab','version_id':'lab-v','content':'current lab',
        'dependency_bindings':[dict(old, purpose='generation_reference')]}
    training = {'type':'training_task','resource_id':'task','version_id':'task-v','content':'use the linked program',
        'dependency_bindings':[dict(code, purpose='learner_link'),dict(experiment, purpose='learner_link')]}
    original = json.loads(json.dumps([old,code,experiment,training]))
    calls=[]
    class Reviewer:
        async def generate(self, system, user, *, role):
            data=json.loads(user); calls.append(data)
            available={item['version_id']:item for item in data['candidates']+data['dependency_resources']}
            assert 'old-v' not in available
            if 'code-v' in available:
                assert available['code-v']['content']=='current executable'
            if 'lab-v' in available:
                assert available['lab-v']['dependency_bindings']==[]
            if 'task-v' in available:
                assert available['task-v']['dependency_bindings'][0]['version_id']=='code-v'
            return json.dumps({'approved':True,'rejectedTypes':[],'findings':[],'conditionReview':[]})
    result=asyncio.run(bundles._resource_review_async(Reviewer(),manifest={'dependency_resources':[old]},
        semantic_plan='one task',candidates=[code,experiment,training]))
    assert result['approved'] and len(calls)==4
    assert [old,code,experiment,training]==original


def test_revision_rechecks_only_changed_resource_then_connections():
    kinds=['handout','quiz','code_sandbox','interactive_model','training_task']
    candidates=[{'type':kind,'resource_id':kind,'version_id':kind+'-v1','content':'full '+kind} for kind in kinds]
    manifest={'active_requirements':{'learning_goal':'same core task','shared':['same source'],
                                    'by_resource':{kind:['complete '+kind] for kind in kinds}}}
    calls=[]; cache={}
    class Reviewer:
        async def generate(self, system, user, *, role):
            data=json.loads(user); calls.append(data)
            global_check=(data.get('review_scope') or {}).get('stage')=='consistency'
            if global_check:
                assert {item['type'] for item in data['candidates']}==set(kinds)
            else:
                assert len(data['candidates'])==1
            conflict=global_check and any(item['content']=='wrong connection' for item in data['candidates'])
            return json.dumps({'approved':not conflict,'rejectedTypes':['training_task'] if conflict else [],
                'findings':[{'resourceType':'training_task','location':'step 2','issue':'wrong connection',
                             'evidence':'different output','fix':'use the actual output'}] if conflict else [],'conditionReview':[]})
    def run():
        return asyncio.run(bundles._resource_review_async(Reviewer(),manifest=manifest,semantic_plan='plan',
            candidates=candidates,completed_reviews=cache,save_review=cache.__setitem__))
    assert run()['approved'] and len(calls)==6
    assert run()['approved'] and len(calls)==6
    candidates[1]={**candidates[1],'version_id':'quiz-v2','content':'two corrected explanations'}
    assert run()['approved'] and len(calls)==8
    assert [item['type'] for item in calls[-2]['candidates']]==['quiz']
    candidates[4]={**candidates[4],'version_id':'training-v2','content':'wrong connection'}
    result=run()
    assert len(calls)==10 and not result['approved']
    assert result['findings'][0]['location']=='step 2' and result['findings'][0]['issue_id']


def test_current_requirements_replace_retired_history_and_metadata():
    legacy = '必须恰好两句话'
    current = {'learning_goal': '解释训练标签和预测输入', 'shared': ['评价概念与理由，不限句数'],
               'by_resource': {'training_task': ['可用角色表解释']}}
    manifest = {'active_requirements': current, 'user_instruction': legacy,
                'teaching_revision_history': [{'feedback': legacy}],
                'context': {'learning_goal': legacy, 'teaching_scope': {'goal': legacy},
                            'path_learning_context': {'path_goal': legacy, 'path_conditions': [legacy], 'predecessors': []}}}
    candidate = {'type': 'training_task', 'version_id': 'current-training',
                 'content': json.dumps({'steps': ['按列说明理由'], 'semanticContext': {'learning_goal': legacy}})}
    calls = []
    class Reviewer:
        async def generate(self, system, user, *, role):
            assert legacy not in user
            data = json.loads(user); calls.append(data)
            assert data['active_requirements'] == current
            return json.dumps({'approved': True, 'rejectedTypes': [], 'findings': [], 'conditionReview': []})
    assert asyncio.run(bundles._resource_review_async(Reviewer(), manifest=manifest,
        semantic_plan=legacy, candidates=[candidate]))['approved']
    assert len(calls) == 1 and json.loads(candidate['content'])['semanticContext']['learning_goal'] == legacy


def test_completed_reasoning_review_survives_call_control_change():
    import hashlib
    calls, cache = [], {}
    class Reviewer:
        model = 'same-model'
        reasoning_effort = 'max'
        thinking_mode = 'enabled'
        max_tokens = 65536
        async def generate(self, system, user, *, role):
            assert self.thinking_mode == 'enabled' and self.reasoning_effort == 'high'
            calls.append((system,user))
            return json.dumps({'approved': True, 'findings': [], 'rejectedTypes': [], 'conditionReview': []})
    def run():
        return asyncio.run(bundles._resource_review_async(Reviewer(),manifest={},semantic_plan='same',
            candidates=[{'type':'quiz','version_id':'same-version','content':'same teaching content'}],
            completed_reviews=cache,save_review=cache.__setitem__))
    result=run()
    system,user=calls[0]
    previous_key=hashlib.sha256(bundles._canonical({'system':system,'user':user,'model':'same-model',
        'reasoning':'high','max_tokens':32768}).encode()).hexdigest()
    cache.clear();cache[previous_key]=result
    assert run()==result and len(calls)==1
    high_key=hashlib.sha256(bundles._canonical({'system':system,'user':user,'model':'same-model',
        'reasoning':'high','thinking_mode':'enabled','max_tokens':32768}).encode()).hexdigest()
    cache.clear();cache[high_key]=result
    assert run()==result and len(calls)==1


def test_unresolved_condition_keeps_deep_review_without_regenerating_content():
    calls=[]
    class Reviewer:
        reasoning_effort='max'
        thinking_mode='enabled'
        max_tokens=65536
        async def generate(self, system, user, *, role):
            data=json.loads(user); calls.append((self.reasoning_effort,data['candidates']))
            assert 'previous_review' in data if len(calls)>1 else 'previous_review' not in data
            return json.dumps({'approved':True,'findings':[],'rejectedTypes':[],
                'conditionReview':[{'claimId':c['id'],'status':'uncertain' if len(calls)==1 else 'valid',
                                   'reason':'需要代入确认' if len(calls)==1 else '已按题设验证','fix':''}
                                  for c in data['condition_claims']]})
    candidate={'type':'handout','version_id':'same-v','content':json.dumps(
        {'concepts':[{'explanation':'只有在分母不为零时才进行本次除法。'}]},ensure_ascii=False)}
    result=asyncio.run(bundles._resource_review_async(Reviewer(),manifest={},semantic_plan='',candidates=[candidate]))
    assert result['approved'] and [c[0] for c in calls]==['high','high']
    assert calls[0][1]==calls[1][1]


def test_empty_condition_schema_clarification_reuses_already_valid_verdict():
    import hashlib
    cache, calls = {}, []
    class Reviewer:
        async def generate(self, system, user, *, role):
            calls.append((system, user))
            assert 'conditionReview必须返回空数组[]' in system
            return json.dumps({'approved': True, 'findings': [], 'rejectedTypes': [], 'conditionReview': []})
    def run():
        return asyncio.run(bundles._resource_review_async(Reviewer(), manifest={}, semantic_plan='',
            candidates=[{'type': 'video', 'version_id': 'same-video', 'content': '课程补充视频'}],
            completed_reviews=cache, save_review=cache.__setitem__))
    result = run()
    system, user = calls[0]
    system = system.replace('本次condition_claims为空，conditionReview必须返回空数组[]；其他疑点写findings，不把适配说明写成conditionReview对象。', '')
    old_key = hashlib.sha256(bundles._canonical({'system': system, 'user': user, 'model': '',
        'reasoning': '', 'thinking_mode': '', 'max_tokens': None}).encode()).hexdigest()
    cache.clear(); cache[old_key] = result
    assert run() == result and len(calls) == 1
    # Malformed old output is still rechecked, never coerced into approval.
    cache[old_key] = {**result, 'conditionReview': {'learnerFit': '原始格式错误'}}
    assert run()['approved'] and len(calls) == 2


def test_indivisible_review_starts_with_supported_budget_and_reuses_success():
    cache, calls = {}, []
    class Reviewer:
        max_tokens = 32768
        reasoning_effort = 'high'
        async def generate(self, system, user, *, role):
            data = json.loads(user)
            calls.append(self.max_tokens)
            if self.max_tokens == 32768:
                raise bundles.ModelOutputLimitError('output exhausted')
            return json.dumps({'approved': True, 'rejectedTypes': [], 'findings': [],
                               'conditionReview': [], 'teachingReview': []})
    def run():
        return asyncio.run(bundles._resource_review_async(Reviewer(), manifest={}, semantic_plan='',
            candidates=[{'type': 'quiz', 'version_id': 'q', 'content': '完整原题与答案'}],
            _grouped=True, _review_scope={'stage': 'section', 'candidate_index': 0, 'paths': ['content']},
            completed_reviews=cache, save_review=cache.__setitem__))
    assert run()['approved']
    assert calls == [65536]
    assert not any(value.get('reason') == 'output_limit' for value in cache.values())
    assert run()['approved'] and calls == [65536]


def test_large_bundle_checks_connections_without_first_exhausting_and_resumes_only_failure():
    candidates = [
        {'type': 'handout', 'version_id': 'long-handout', 'content': '教学正文。' * 6000},
        {'type': 'quiz', 'version_id': 'quiz-current', 'content': '题目、答案及评分。'},
    ]
    calls, cache = [], {}
    state = {'fail': True}
    class Reviewer:
        max_tokens = 32768
        reasoning_effort = 'high'
        thinking_mode = 'enabled'
        async def generate(self, system, user, *, role):
            data = json.loads(user)
            assert data['candidates'] == candidates
            assert data['completed_section_reviews']
            assert data['condition_claims'] == []
            assert self.max_tokens == 65536 and self.thinking_mode == 'enabled'
            checks = data['review_scope']['checks']
            assert len(checks) == 1
            calls.append(checks)
            if '评分' in checks[0] and state['fail']:
                raise RuntimeError('connection network loss')
            return json.dumps({'approved': True, 'findings': [], 'rejectedTypes': [],
                               'conditionReview': [], 'teachingReview': []})
    def run():
        return asyncio.run(bundles._resource_review_async(Reviewer(), manifest={},
            semantic_plan='', candidates=candidates, _grouped=True,
            _review_scope={'stage': 'consistency'}, _section_reviews=[{'approved': True}],
            completed_reviews=cache, save_review=cache.__setitem__))
    with pytest.raises(bundles.ResourceBundleError, match='network loss'):
        run()
    assert len(calls) == 4
    assert len({check for group in calls for check in group}) == 4
    state['fail'] = False
    assert run()['approved'] is True
    assert len(calls) == 5 and '评分' in calls[-1][0]
    assert run()['approved'] is True and len(calls) == 5


def test_terminal_connection_exhaustion_keeps_failure_scope_and_successful_cache():
    cache = {'previous-success': {'approved': True}}
    class Reviewer:
        max_tokens = 65536
        async def generate(self, system, user, *, role):
            raise bundles.ModelOutputLimitError('provider output allowance exhausted')
    scope = {'stage': 'consistency', 'checks': ['先修、工具与时间']}
    with pytest.raises(bundles.ResourceBundleError):
        asyncio.run(bundles._resource_review_async(Reviewer(), manifest={}, semantic_plan='',
            candidates=[{'type': 'quiz', 'version_id': 'q', 'content': '完整原题'}],
            _grouped=True, _review_scope=scope, _section_reviews=[{'approved': True}],
            completed_reviews=cache, save_review=cache.__setitem__))
    failure = next(v for v in cache.values() if v.get('review_failed'))
    assert failure['reason'] == 'output_limit'
    assert failure['execution']['scope'] == scope and failure['execution']['max_tokens'] == 65536
    assert cache['previous-success'] == {'approved': True}


def test_exhausted_connections_resume_only_failed_relationship_check():
    candidates = [{'type': 'handout', 'version_id': 'h', 'content': '解释'},
                  {'type': 'quiz', 'version_id': 'q', 'content': '检查'}]
    cache, calls = {}, []
    class Reviewer:
        fail_once = True
        async def generate(self, system, user, *, role):
            data = json.loads(user); scope = data.get('review_scope') or {}
            calls.append(scope)
            if scope.get('stage') == 'consistency':
                assert len(data['candidates']) == 2
                assert len(data['completed_section_reviews']) == 2
                if not scope.get('checks'):
                    raise bundles.ModelOutputLimitError('connection output exhausted')
                if self.fail_once and '先修' in ''.join(scope['checks']):
                    raise RuntimeError('temporary connection failure')
            return json.dumps({'approved': True, 'rejectedTypes': [], 'findings': [], 'conditionReview': []})
    backend = Reviewer()
    def run():
        return asyncio.run(bundles._resource_review_async(backend, manifest={}, semantic_plan='same',
            candidates=candidates, completed_reviews=cache, save_review=cache.__setitem__))
    with pytest.raises(bundles.ResourceBundleError, match='temporary connection'):
        run()
    finished = len(calls)
    backend.fail_once = False
    assert run()['approved']
    assert len(calls) == finished + 1
    assert calls[-1].get('checks')


@pytest.mark.parametrize('sentence', [
    '本次提供的课程摘录未完整展示方差分母，按题设计算。',
    '所选资料没有给出该公式。',
    '当前材料并未说明训练集统计量。',
])
def test_source_scope_absence_assertions_must_be_reviewed(sentence):
    found = conditional_teaching_claims([{'type': 'answer', 'version_id': 'v1', 'content': sentence}])
    assert len(found) == 1 and found[0]['quote'] == sentence
    assert found[0]['kind'] == 'source_scope'
    assert not conditional_teaching_claims([{'type': 'answer', 'content': '```python\ntext = '+repr(sentence)+'\n```'}])


def candidate(version="v1"):
    return {"type": "handout", "version_id": version, "content": json.dumps({
        "title": "长讲义", "outline": [{"id": str(i), "title": f"章节{i}"} for i in range(9)],
        "concepts": [{"id": str(i), "explanation": "完整正文" * 600 + f"结论{i}"} for i in range(9)],
        "codeBlocks": [{"id": "code", "code": "print(18)"}], "miniQuiz": [],
    }, ensure_ascii=False)}


def test_generation_provenance_is_context_not_an_extra_teaching_section():
    content = {'instructions': '完整教学正文' * 1500,
               'starterCode': 'print(42)',
               'adaptation': {'summary': '本次先手算，再检查输出。'},
               'semanticContext': {'profile_snapshot': '完整冻结画像' * 2000}}
    item = {'type': 'code_sandbox', 'version_id': 'provenance',
            'content': json.dumps(content, ensure_ascii=False)}
    original = item['content']
    scopes = document_review_scopes([item])
    paths = [path for scope in scopes for path in scope['paths']]
    assert paths == ['content.instructions', 'content.starterCode', 'content.adaptation']
    assert item['content'] == original
    assert json.loads(item['content'])['semanticContext'] == content['semanticContext']


def test_quiz_progress_does_not_turn_frozen_profile_provenance_into_wrong_teaching():
    from app.resource_review_context import teaching_candidate
    body = {'summary': '计算训练和验证误差',
            'adaptation': {'learningGoal': '独立计算并选择', 'profileSummary': '生成时掌握度73%',
                           'masterySummary': '生成时的基础', 'recentLearningSummary': '上次诊断'},
            'questions': [{'questionVersionId': 'unchanged', 'hints': ['先平方再平均']}],
            'requiredQuestionCount': 1}
    original = {'type': 'quiz', 'version_id': 'frozen-quiz', 'content': json.dumps(body)}
    reviewed = json.loads(teaching_candidate(original)['content'])
    assert reviewed['adaptation'] == {'learningGoal': '独立计算并选择'}
    assert reviewed['questions'] == body['questions']
    assert reviewed['summary'] == body['summary'] and reviewed['requiredQuestionCount'] == 1
    assert json.loads(original['content']) == body


def test_connection_approval_keeps_known_local_defect_open_without_repeating_it():
    class Reviewer:
        async def generate(self, system, user, *, role):
            data = json.loads(user)
            if data.get('review_scope', {}).get('stage') == 'consistency':
                assert 'approved只表示本次衔接检查是否发现新问题' in system
                assert any(not x['approved'] for x in data['completed_section_reviews'])
                return json.dumps({'approved': True, 'findings': [], 'rejectedTypes': [], 'conditionReview': []})
            bad = data['candidates'][0]['type'] == 'quiz'
            return json.dumps({'approved': not bad, 'rejectedTypes': ['quiz'] if bad else [],
                'findings': [{'resourceType': 'quiz', 'location': '第1题', 'issue': '答案与题干矛盾',
                              'evidence': '题干要求最大值，答案选最小值', 'fix': '更正答案'}] if bad else [], 'conditionReview': []})
    result = asyncio.run(bundles._resource_review_async(Reviewer(), manifest={}, semantic_plan='',
        candidates=[{'type': 'handout', 'version_id': 'h', 'content': '比较大小'},
                    {'type': 'quiz', 'version_id': 'q', 'content': '找最大值'}]))
    assert not result['approved'] and result['rejectedTypes'] == ['quiz']
    assert len(result['findings']) == 1 and result['findings'][0]['location'] == '第1题'


def test_parallel_sections_share_capacity_keep_successes_and_wait_before_consistency():
    kinds = ['handout', 'code_sandbox', 'training_task']
    current = [{'type': kind, 'version_id': 'parallel-' + kind,
                'content': json.dumps({f'part{i}': '完整学习记录。' * 1200 for i in range(4)},
                                      ensure_ascii=False)} for kind in kinds]

    class ParallelReviewer:
        def __init__(self):
            self.active = self.peak = 0
            self.calls = []
            self.connection_checks = []
            self.done = {kind: set() for kind in kinds}
            self.fail = True

        async def generate(self, system, user, *, role):
            data = json.loads(user)
            kind = data['candidates'][0]['type']
            scope = data['review_scope']
            self.calls.append((kind, scope['stage'], scope.get('index')))
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                await asyncio.sleep(0.002)
                if scope['stage'] == 'section':
                    if self.fail and kind == 'handout' and scope['index'] == 1:
                        raise RuntimeError('one section interrupted')
                    self.done[kind].add(scope['index'])
                else:
                    assert all(value == {0, 1, 2, 3} for value in self.done.values()) if len(data['candidates']) > 1 else self.done[kind] == {0,1,2,3}
                    assert len(data['completed_section_reviews']) == (3 if len(data['candidates']) > 1 else 4)
                    if len(data['candidates']) > 1:
                        self.connection_checks.extend(scope['checks'])
                return json.dumps({'approved': True, 'findings': [], 'rejectedTypes': [],
                                   'summary': '全文与配套已核对', 'conditionReview': []})
            finally:
                self.active -= 1

    backend, cache = ParallelReviewer(), {}
    def run():
        return asyncio.run(bundles._resource_review_async(backend, manifest={},
            semantic_plan='一份共同成果', candidates=current,
            completed_reviews=cache, save_review=cache.__setitem__))

    with pytest.raises(bundles.ResourceBundleError, match='one section interrupted'):
        run()
    assert backend.peak == 2 and backend.active == 0
    assert backend.done == {'handout': {0, 2, 3}, 'code_sandbox': {0, 1, 2, 3},
                            'training_task': {0, 1, 2, 3}}
    assert ('handout', 'consistency', None) not in backend.calls
    initial_count = len(backend.calls)
    backend.fail = False
    assert run()['approved'] is True
    assert backend.calls[initial_count:] == [('handout', 'section', 1),
                                              ('handout', 'consistency', None),
                                              *[('handout', 'consistency', None)] * 4]
    assert len(backend.connection_checks) == len(set(backend.connection_checks)) == 4


@pytest.mark.parametrize('sentence', [
    '平方项非负，所以累计值只增不减。',
    '该序列单调递减。',
    'The moving average is non-decreasing.',
    '累计值不会减小；若输入非零则增加。',
    '非负增量只会提高累计值。',
    'The accumulated value will not decrease.',
    '平均值并不是不会下降，当前值可能低于上一期。',
])
def test_monotonicity_claims_are_explicitly_reviewed(sentence):
    found = conditional_teaching_claims([{'type':'answer','version_id':'v1','content':sentence}])
    assert len(found)==1 and found[0]['quote']==sentence


@pytest.mark.parametrize('sentence', [
    '如果权重全相等，加权均方误差就退化为普通均方误差。',
    '各输入相同时，归一化公式化简为零。',
    '共同的比例因子约去后，结果保持不变。',
    '整体缩放不影响归一化结果。',
    'With equal weights the result reduces to the ordinary mean.',
    'The normalized result is invariant under scaling.',
])
def test_reduction_and_invariance_claims_are_located_without_deciding_truth(sentence):
    found = conditional_teaching_claims([{'type':'answer','version_id':'v1','content':sentence}])
    assert len(found)==1 and found[0]['quote']==sentence


def test_reduction_locator_keeps_definition_context_and_excludes_teaching_code():
    text = ('本题权重均为正。\n如果权重全相等，加权平均退化为普通平均。\n'
            '```python\nprint("退化为普通平均")\n```')
    found = conditional_teaching_claims([{'type':'answer','content':text}])
    assert len(found)==1 and found[0]['quote']=='如果权重全相等，加权平均退化为普通平均。'
    # A locator is not a verdict: the existing reviewer still sees the whole
    # candidate and may accept this implication under the stated domain.


def test_output_blocks_are_reviewed_even_when_a_later_note_corrects_them():
    text = '实际输出：\n```text\n1.3440\n```\n上面输出应改为：\n```text\n0.9760\n```'
    found = conditional_teaching_claims([{'type':'answer','version_id':'v1','content':text}])
    assert len(found)==2
    assert all(item['kind']=='program_output' for item in found)
    assert '1.3440' in found[0]['quote'] and '0.9760' in found[1]['quote']
    assert conditional_teaching_claims([{'type':'answer','content':'说明：\n```text\n普通摘录\n```'}])==[]


@pytest.mark.parametrize('sentence', [
    '完整梯度比无正则梯度少了0.75（从−2变为−1.25）。',
    '数据梯度−4远大于惩罚梯度+0.5，所以完整更新向右。',
    '数据梯度−4的绝对值大于惩罚梯度+0.5的绝对值。',
    '温度从−6上升到−2，数值增加4而绝对值减少4。',
])
def test_numeric_comparison_prose_gets_an_explicit_review_without_assuming_it_is_wrong(sentence):
    found=conditional_teaching_claims([{'type':'handout','content':sentence}])
    assert len(found)==1 and found[0]['quote']==sentence
    assert found[0]['kind']=='numeric_comparison'


def test_comparison_locator_keeps_code_and_incorrect_options_separate_from_adopted_claims():
    body={'codeBlocks':[{'code':'print("−4大于0.5")'}],
          'miniQuiz':[{'options':['−4大于0.5'], 'explanation':'“−4大于0.5”不成立；负数应放在数轴左侧。'}]}
    found=conditional_teaching_claims([{'type':'handout','content':json.dumps(body,ensure_ascii=False)}])
    assert len(found)==1 and found[0]['path'].endswith('.explanation')
    assert '不成立' in found[0]['quote']


class Reviewer:
    max_tokens = 32768
    reasoning_effort = "max"
    model = "test"

    def __init__(self):
        self.state = {"calls": [], "fail_index": 2, "reject": None}

    async def generate(self, system, user, *, role):
        data = json.loads(user)
        scope = data.get("review_scope")
        self.state["calls"].append(scope)
        if scope is None:
            raise bundles.ModelOutputLimitError("review output exhausted")
        # Every request sees the complete original source, including the tail.
        assert "结论8" in data["candidates"][0]["content"]
        assert data["runtime"]["installedVersions"]
        if scope.get("index") == self.state["fail_index"]:
            raise RuntimeError("temporary network loss")
        rejected = scope["stage"] == self.state["reject"]
        return json.dumps({"approved": not rejected, "summary": "前后结果不一致" if rejected else "核对完成",
            "findings": [{"resourceType": "handout", "issue": "例子和答案不一致", "fix": "核对同一条件"}] if rejected else [],
            "rejectedTypes": ["handout"] if rejected else []})


def test_review_scopes_cover_every_field_and_whole_code_without_truncation():
    scopes = document_review_scopes([candidate()])
    paths = [p for scope in scopes for p in scope["paths"]]
    assert len(paths) == len(set(paths))
    assert "content.title" in paths and "content.miniQuiz" in paths
    assert all(f"content.concepts[{i}]" in paths for i in range(9))
    assert "content.codeBlocks[0]" in paths


def test_outline_and_small_fields_share_a_real_teaching_section():
    content = {'schemaVersion': '1', 'title': '读表选模', 'estimatedMinutes': 30,
               'outline': [{'id': f'c{i}', 'title': f'第{i}段'} for i in range(50)],
               'concepts': [{'id': f'c{i}', 'explanation': '完整解释。' * 500} for i in range(5)],
               'miniQuiz': [], 'profileAdaptation': {'summary': '先解释再练习'}}
    scopes = document_review_scopes([{'type':'handout','content':json.dumps(content,ensure_ascii=False)}])
    assert scopes
    assert all(any(p.startswith('content.concepts[') for p in s['paths']) for s in scopes)
    paths = [p for s in scopes for p in s['paths']]
    assert paths.count('content.outline') == 1 and 'content.miniQuiz' in paths
    assert all(paths.count(f'content.concepts[{i}]') == 1 for i in range(5))


def test_same_quoted_condition_is_one_actionable_finding():
    claims=[{'id':'condition-1','resourceType':'handout','path':'content.concepts[0]',
             'quote':'训练误差最低就一定最好。'}]
    result={'approved':False,'rejectedTypes':['handout'],
            'findings':[{'resourceType':'handout','location':'定义段',
                         'issue':'训练误差不能替代验证表现',
                         'evidence':'原文：“训练误差最低就一定最好。”', 'fix':'按验证表现比较。'}],
            'conditionReview':[{'claimId':'condition-1','status':'incorrect',
                                'reason':'训练表现不能直接外推。','fix':'按验证表现比较。'}]}
    actual=apply_condition_review(result,claims)
    assert len(actual['findings'])==1 and len(actual['conditionReview'])==1
    assert actual['approved'] is False and actual['rejectedTypes']==['handout']


@pytest.mark.parametrize('location,fix,count', [
    ('第3题D项及解析', '改为“再减学习率乘数据项梯度”，或写出完整更新式。', 1),
    ('第4题D项及解析', '改为“再减学习率乘数据项梯度”，或写出完整更新式。', 2),
    ('第3题D项及解析', '改为“梯度必须在同一个旧参数点计算”。', 2),
])
def test_condition_repair_matches_question_without_hiding_other_defects(location, fix, count):
    claims = [{'id': 'quiz-v1:content.question_details[2].explanation:1',
               'resourceType': 'quiz', 'path': 'content.question_details[2].explanation',
               'quote': 'L2更新可写成先乘衰减系数再减数据项梯度。'}]
    result = {'approved': False, 'rejectedTypes': ['quiz'], 'findings': [
        {'resourceType': 'quiz', 'location': location, 'issue': '更新式漏学习率。',
         'fix': '在选项D和解析中改为“再减学习率乘数据项梯度”，或直接写出完整更新式。'}],
        'conditionReview': [{'claimId': claims[0]['id'], 'status': 'incorrect',
                             'reason': '更新步骤需修正。', 'fix': fix}]}
    actual = apply_condition_review(result, claims)
    assert len(actual['findings']) == count
    assert len(actual['conditionReview']) == 1
    assert actual['approved'] is False
    if count == 1:
        assert actual['findings'][0]['conditionClaimIds'] == [claims[0]['id']]


@pytest.mark.parametrize('location,quote,count', [
    ('content.counterExamples[0].body（泄漏判断开头）', '让验证或测试信息进入……选择过程', 1),
    ('content.counterExamples[1].body（另一个情境）', '让验证或测试信息进入……选择过程', 2),
    ('content.counterExamples[0].body（同段另一错误）', '先把误差相加再平方可以得到均方误差', 2),
])
def test_shortened_quote_links_the_same_condition_without_merging_other_defects(location, quote, count):
    claim = {'id': 'v:content.counterExamples[0].body:0', 'resourceType': 'handout',
             'path': 'content.counterExamples[0].body',
             'quote': '让验证或测试信息进入本应只靠训练数据完成的拟合、预处理或选择过程都是泄漏。'}
    result = {'approved': False, 'findings': [{'resourceType': 'handout', 'location': location,
              'issue': '这句话过度概括。', 'evidence': f'原句“{quote}”。',
              'fix': '区分正常选择方案与训练拟合。'}],
              'conditionReview': [{'claimId': claim['id'], 'status': 'incorrect',
                                  'reason': '验证用于选模是正常用途。',
                                  'fix': '验证集可用于比较候选和超参数。'}]}
    actual = apply_condition_review(result, [claim])
    assert len(actual['findings']) == count
    assert actual['conditionReview'] == result['conditionReview']
    if count == 1:
        assert actual['findings'][0]['conditionClaimIds'] == [claim['id']]


@pytest.mark.parametrize('kind', ['code_sandbox', 'interactive_model', 'training_task'])
def test_practical_review_scopes_keep_every_step_and_complete_code(kind):
    body = {
        'title': '完整实践', 'objective': '比较改变阈值前后的结果。',
        'starterCode': 'print(18)\n' * 800,
        'steps': [{'instruction': f'第{i}步：' + '完整操作' * 500,
                   'expectedResult': '条件满足时结论才成立。'} for i in range(8)],
        'rubric': [{'criterion': '解释最后一步', 'points': 100}], 'dependencies': [],
    }
    current = [{'type': kind, 'version_id': 'practical-v1', 'content': json.dumps(body, ensure_ascii=False)}]
    original = current[0]['content']
    scopes = document_review_scopes(current)
    paths = [path for scope in scopes for path in scope['paths']]
    expected = ['content.title', 'content.objective', 'content.starterCode',
                *[f'content.steps[{i}]' for i in range(8)], 'content.rubric[0]', 'content.dependencies']
    assert sorted(paths) == sorted(expected)
    assert current[0]['content'] == original
    scoped_claims = [claim for scope in scopes
                     for claim in conditional_teaching_claims(current, {'stage': 'section', **scope})]
    assert scoped_claims == conditional_teaching_claims(current)


def test_mindmap_identifiers_are_not_teaching_claims_but_visible_text_is():
    body = {'rootNodeId': '必要条件', 'nodes': [{
        'nodeId': '必要条件', 'parentNodeId': '充分条件',
        'label': '必要条件', 'summary': '只要阈值改变，类别一定改变。',
    }]}
    claims = conditional_teaching_claims([{'type': 'mind_map', 'content': json.dumps(body, ensure_ascii=False)}])
    assert [claim['path'] for claim in claims] == ['content.nodes[0].label', 'content.nodes[0].summary']


def test_large_practice_reviews_each_condition_once_then_checks_full_consistency():
    body = {
        'objective': '完整任务',
        'steps': [{'instruction': '操作记录。' * 800 + f'第{i}步结论必须满足已给条件。',
                   'expectedResult': '观察结果'} for i in range(10)],
        'files': [{'path': 'main.py', 'content': 'print(18)\n' * 200}],
    }
    current = [{'type': 'training_task', 'version_id': 'large-practice-v1',
                'content': json.dumps(body, ensure_ascii=False)}]
    local_claims = []
    class ScopedReviewer:
        async def generate(self, system, user, *, role):
            data = json.loads(user)
            assert data['candidates'] == current
            scope = data['review_scope']  # Start in sections, before an output exhaustion.
            if scope['stage'] == 'section':
                assert 'completed_section_reviews' not in data
                claims = data['condition_claims']
                local_claims.extend(claim['id'] for claim in claims)
                return json.dumps({'approved': True, 'rejectedTypes': [], 'findings': [],
                    'conditionReview': [{'claimId': claim['id'], 'status': 'valid', 'reason': '条件已给出。', 'fix': ''}
                                        for claim in claims]})
            assert data['condition_claims'] == []
            prior = [check['claimId'] for part in data['completed_section_reviews']
                     for check in part.get('conditionReview', [])]
            assert prior == local_claims
            return json.dumps({'approved': False, 'conditionReview': [],
                'rejectedTypes': ['training_task'], 'summary': '跨段依赖不一致',
                'findings': [{'resourceType': 'training_task', 'issue': '后段引用了前段未提供的结果。',
                              'fix': '提供对应前段输出。'}]})
    result = asyncio.run(bundles._resource_review_async(ScopedReviewer(), manifest={},
        semantic_plan='完整实践', candidates=current))
    expected = [claim['id'] for claim in conditional_teaching_claims(current)]
    assert local_claims == expected and len(local_claims) == len(set(local_claims))
    assert [check['claimId'] for check in result['conditionReview']] == expected
    assert result['approved'] is False and result['rejectedTypes'] == ['training_task']


def test_exhausted_review_resumes_successful_sections_and_invalidates_changed_version():
    backend = Reviewer(); cache = {}; current = [candidate()]
    def run():
        return asyncio.run(bundles._resource_review_async(backend, manifest={}, semantic_plan="完整讲解",
            candidates=current, completed_reviews=cache, save_review=cache.__setitem__))
    with pytest.raises(bundles.ResourceBundleError, match="network loss"):
        run()
    count = len(backend.state["calls"]); backend.state["fail_index"] = -1
    result = run()
    resumed = backend.state["calls"][count:]
    assert resumed[0]["index"] == 2
    assert all(scope is not None for scope in resumed)
    assert resumed[-1] == {"stage": "consistency"}
    assert result["approved"] is True and result["sectionReviews"]
    count = len(backend.state["calls"])
    assert run()["approved"] is True and len(backend.state["calls"]) == count
    current[0] = candidate("v2"); run()
    assert backend.state["calls"][count] is None


@pytest.mark.parametrize("stage", ["section", "consistency"])
def test_any_local_or_cross_section_rejection_blocks_publication(stage):
    backend = Reviewer(); backend.state.update(fail_index=-1, reject=stage)
    result = asyncio.run(bundles._resource_review_async(backend, manifest={}, semantic_plan="完整讲解", candidates=[candidate()]))
    assert result["approved"] is False
    assert result["rejectedTypes"] == ["handout"]
    assert result["findings"]


def test_condition_review_preserves_context_and_excludes_code_and_distractors():
    value = {"type": "handout", "version_id": "conditional-v1", "content": json.dumps({
        "concepts": [{"explanation": "只有保持固定步长，逐步更新公式才成立。"},
                     {"explanation": "固定步长是本例设置，不是该公式的必要条件。"}],
        "codeBlocks": [{"code": "print('always')", "explanation": "实现不一定适合所有目标。"}],
        "miniQuiz": [{"options": ["只要增加深度，验证表现一定提升。"],
                      "explanation": "上述选项不成立，增加深度不一定改善验证表现。"}],
    }, ensure_ascii=False)}
    claims = conditional_teaching_claims([value])
    assert len(claims) == 4
    assert all('print' not in claim['quote'] and '.options' not in claim['path'] for claim in claims)
    subset = conditional_teaching_claims([value], {"stage": "section", "candidate_index": 0,
                                                  "paths": ["content.concepts[1]"]})
    assert subset == [claims[1]]
    # Selection is diagnostic, never a keyword-based correctness verdict.
    accepted = {"approved": True, "findings": [], "rejectedTypes": [], "conditionReview": [
        {"claimId": claims[1]['id'], "status": "valid", "reason": "原句正确否定必要性。", "fix": ""}]}
    assert apply_condition_review(accepted, [claims[1]])['approved'] is True


def test_adverse_condition_decision_blocks_approval_and_survives_group_review():
    class ConditionReviewer:
        async def generate(self, system, user, *, role):
            data = json.loads(user)
            claim = data['condition_claims'][0]
            assert claim['quote'] in data['candidates'][0]['content']
            return json.dumps({"approved": True, "summary": "数值核对通过", "findings": [],
                "rejectedTypes": [], "conditionReview": [{"claimId": claim['id'], "status": "overstated",
                "reason": "在每一步使用当步步长时等式仍成立，固定步长并非必要。",
                "fix": "说明固定步长仅是本例迭代的设置。"}]})
    current = [{"type": "handout", "version_id": "condition-v2", "content": json.dumps({
        "concepts": [{"explanation": "只有保持固定步长，逐步更新公式才成立。"}]}, ensure_ascii=False)}]
    cache = {}
    result = asyncio.run(bundles._resource_review_async(ConditionReviewer(), manifest={},
        semantic_plan="逐步更新", candidates=current, completed_reviews=cache, save_review=cache.__setitem__))
    assert result['approved'] is False and result['rejectedTypes'] == ['handout']
    assert '当步步长' in result['findings'][0]['issue']
    assert next(iter(cache.values()))['approved'] is False
    from app.resource_review_parts import combine_document_reviews
    combined = combine_document_reviews([{"approved": True}, result])
    assert combined['approved'] is False and combined['conditionReview'] == result['conditionReview']


def test_condition_finding_must_refer_to_a_current_claim():
    with pytest.raises(ValueError, match='本次讲解'):
        apply_condition_review({'approved': True, 'conditionReview': [
            {'claimId': 'another-version', 'status': 'incorrect', 'reason': '错误', 'fix': '修改'}]}, [])


def test_uncertain_missing_premise_with_exact_finding_goes_to_repair_not_endless_review():
    from app.resource_review_parts import resource_review_condition_feedback
    claim = {'id':'condition-a', 'resourceType':'code_sandbox', 'path':'instructions[2]',
             'quote':'P未列出预处理条件。'}
    result = {'approved':True, 'rejectedTypes':[], 'conditionReview':[
        {'claimId':'condition-a','status':'uncertain','reason':'不能确定公平可比','fix':'补预处理范围'}],
        'findings':[{'resourceType':'code_sandbox','location':'instructions[2]',
            'issue':'要求唯一比较但缺必要条件','evidence':'原句：P未列出预处理条件。',
            'fix':'明确预处理只在训练行拟合。'}]}
    assert resource_review_condition_feedback(result, [claim]) == []
    repaired = apply_condition_review(result, [claim])
    assert repaired['approved'] is False and repaired['rejectedTypes'] == ['code_sandbox']
    assert repaired['conditionReview'][0]['status'] == 'uncertain'
    assert repaired['findings'][0]['conditionClaimIds'] == ['condition-a']
    result['findings'][0]['evidence'] = '另一个未定位的句子'
    assert resource_review_condition_feedback(result, [claim])
    with pytest.raises(ValueError, match='尚未确认'):
        apply_condition_review(result, [claim])



@pytest.mark.parametrize('location,evidence,actionable', [
    ('content.instructions 新场景表', 'P/Q/R 行均写“表中未列出额外条件”', True),
    ('content.checkpoints', 'P/Q/R 行均写“表中未列出额外条件”', False),
    ('content.instructions', '这里只写“条件”', False),
    ('content.instructions', '其它行写“只在训练集拟合预处理”', False),
])
def test_condition_missing_table_cell_uses_located_verbatim_evidence(location, evidence, actionable):
    from app.resource_review_parts import resource_review_condition_feedback
    claim = {'id':'table-p', 'resourceType':'code_sandbox', 'path':'content.instructions',
             'quote':'| P | 1 | 0.31 | 0.36 | 表中未列出额外条件 |'}
    result = {'approved':False, 'conditionReview':[{'claimId':'table-p', 'status':'uncertain',
        'reason':'缺少预处理条件', 'fix':'补齐拟合范围'}],
        'findings':[{'resourceType':'code_sandbox', 'location':location, 'evidence':evidence,
                     'issue':'要求唯一选模却缺条件', 'fix':'明确拟合仅使用训练行'}]}
    assert bool(resource_review_condition_feedback(result, [claim])) is not actionable
    if actionable:
        assert apply_condition_review(result, [claim])['findings'][0]['conditionClaimIds'] == ['table-p']

@pytest.mark.parametrize('stays_uncertain', [False, True])
def test_uncertain_condition_is_rechecked_without_fabricating_a_teaching_error(stays_uncertain):
    class UncertainReviewer:
        calls = 0

        async def generate(self, system, user, *, role):
            self.calls += 1
            data = json.loads(user)
            claim = data['condition_claims'][0]
            if self.calls == 2:
                assert data['previous_review']['conditionReview'][0]['status'] == 'uncertain'
                assert data['review_condition_feedback'][0]['claimId'] == claim['id']
                assert data['candidates'] == candidates
            return json.dumps({'approved': True, 'summary': '总体通过', 'findings': [], 'rejectedTypes': [],
                'conditionReview': [{'claimId': claim['id'],
                    'status': 'uncertain' if self.calls == 1 or stays_uncertain else 'valid',
                    'reason': '尚未核实条件。' if self.calls == 1 or stays_uncertain else '非负平方和加到累计值上不会使其下降。',
                    'fix': ''}]}, ensure_ascii=False)

    candidates = [{'type': 'handout', 'version_id': 'uncertain370-v1', 'content': json.dumps({
        'concepts': [{'explanation': '非负平方项的累计值单调不减。'}]}, ensure_ascii=False)}]
    reviewer, cache = UncertainReviewer(), {}
    def run():
        return asyncio.run(bundles._resource_review_async(reviewer, manifest={}, semantic_plan='累计平方',
            candidates=candidates, completed_reviews=cache, save_review=cache.__setitem__))
    if stays_uncertain:
        with pytest.raises(bundles.ResourceBundleError, match='尚未确认'):
            run()
        assert not any(value.get('approved') is True for value in cache.values())
    else:
        result = run()
        assert result['approved'] is True and result['rejectedTypes'] == [] and result['findings'] == []
        assert result['conditionReview'][0]['status'] == 'valid'
        assert result['conditionReviewAttempts'][0]['review']['conditionReview'][0]['status'] == 'uncertain'
        assert run() == result  # Completed, resolved review is safely reused.
        # A previously cached approved summary must not bypass an unresolved
        # detailed verdict when restored.
        result['conditionReview'][0]['status'] = 'uncertain'
        reviewer.calls = 0
        assert run()['conditionReview'][0]['status'] == 'valid'
    assert reviewer.calls == 2
    history = [value for key, value in cache.items() if key.endswith(':conditions')]
    assert len(history) == 1
    # Both original and resumed checks remain in the saved history.
    assert len(history[0]['conditionReviewAttempts']) == 2
    assert all(not attempt['review']['findings'] for attempt in history[0]['conditionReviewAttempts'])


def test_unresolved_condition_cannot_be_applied_as_approved():
    claims = conditional_teaching_claims([{'type': 'answer', 'content': '该序列一定收敛。'}])
    with pytest.raises(ValueError, match='尚未确认'):
        apply_condition_review({'approved': True, 'conditionReview': [
            {'claimId': claims[0]['id'], 'status': 'uncertain', 'reason': '缺少条件', 'fix': ''}]}, claims)


@pytest.mark.parametrize('repeat_error', [False, True])
def test_reviewer_cannot_send_its_own_wrong_arithmetic_to_generation(repeat_error):
    class ArithmeticReviewer:
        def __init__(self):
            self.calls = 0

        async def generate(self, system, user, *, role):
            self.calls += 1
            data = json.loads(user)
            assert data['candidates'][0]['content'] == '通用数学示例：0.2×0.8=0.16。'
            if self.calls > 1:
                assert data['review_calculation_feedback']
                assert data['previous_review']['findings'][0]['fix'] == '请改为0.2×0.8=0.18。'
            if self.calls == 1 or repeat_error:
                return json.dumps({'approved': False, 'summary': '修改计算结果', 'rejectedTypes': ['handout'],
                    'findings': [{'resourceType': 'handout', 'issue': '结果需要改写。', 'fix': '请改为0.2×0.8=0.18。'}]})
            return json.dumps({'approved': True, 'summary': '已复核：0.2×0.8=0.16，原说明正确。',
                               'rejectedTypes': [], 'findings': []})

    backend=ArithmeticReviewer();cache={}
    def run():
        return asyncio.run(bundles._resource_review_async(backend, manifest={}, semantic_plan='只核对短说明',
            candidates=[{'type':'handout','version_id':'arithmetic-original','content':'通用数学示例：0.2×0.8=0.16。'}],
            completed_reviews=cache, save_review=cache.__setitem__))
    if repeat_error:
        with pytest.raises(bundles.ResourceBundleError, match='计算|核对'):
            run()
        assert not any(value.get('approved') is True for value in cache.values())
        saved_attempts = next(iter(cache.values()))['calculationReviewAttempts']
        assert len(saved_attempts) == 2
        assert all(item['feedback'] for item in saved_attempts)
    else:
        result=run()
        assert result['approved'] is True and result['findings']==[]
        assert result['calculationReviewAttempts'][0]['review']['findings'][0]['fix']=='请改为0.2×0.8=0.18。'
        assert run()['approved'] is True
    assert backend.calls==2


@pytest.mark.parametrize('field,key', [
    ('findings', 'issue'), ('findings', 'fix'), ('conditionReview', 'reason'),
    ('conditionReview', 'fix'), ('teachingReview', 'evidence'),
])
def test_review_arithmetic_covers_each_explanation_field(field, key):
    from app.resource_review_parts import resource_review_calculation_feedback
    result = {'approved': True, field: [{key: '复算结果：0.3×0.7=0.24。'}]}
    feedback = resource_review_calculation_feedback(result)
    assert len(feedback) == 1 and feedback[0]['location'] == f'{field}[0]'
    assert feedback[0]['calculationChecks'][0]['calculated'] == '0.21'


def test_invalid_cached_arithmetic_is_rechecked_without_erasing_other_rejection():
    class Reviewer:
        calls = 0

        async def generate(self, system, user, *, role):
            self.calls += 1
            return json.dumps({'approved': False, 'summary': '算术正确，结论的条件仍需修改。',
                'rejectedTypes': ['handout'], 'findings': [{'resourceType': 'handout',
                'issue': '0.2×0.8=0.16，但一个参数下的计算不能证明所有参数下的结论。',
                'fix': '说明结果对应本例参数，不声称其他参数也具有相同结果。'}]})

    backend = Reviewer()
    cache = {}

    def run():
        return asyncio.run(bundles._resource_review_async(backend, manifest={}, semantic_plan='核对原结论',
            candidates=[{'type': 'handout', 'version_id': 'cache-arithmetic',
                         'content': '通用数学示例：0.2×0.8=0.16，其他参数也有相同结果。'}],
            completed_reviews=cache, save_review=cache.__setitem__))

    result = run()
    assert result['approved'] is False and backend.calls == 1
    key = next(iter(cache))
    # Simulate an old cached verdict, created before arithmetic checking existed.
    cache[key] = {'approved': True, 'summary': '核算通过：0.2×0.8=0.18。',
                  'findings': [], 'rejectedTypes': []}
    result = run()
    assert result['approved'] is False and result['rejectedTypes'] == ['handout']
    assert '所有参数' in result['findings'][0]['issue'] and backend.calls == 2
    assert run()['approved'] is False and backend.calls == 2


def test_resource_arithmetic_check_leaves_negated_examples_and_symbolic_steps_to_semantic_review():
    class Reviewer:
        calls=0
        async def generate(self, system, user, *, role):
            self.calls+=1
            return json.dumps({'approved':True,'summary':'不能使用错误等式0.2×0.8=0.18；应得0.2×0.8=0.16。',
                'findings':[], 'rejectedTypes':[], 'teachingReview':[{'evidence':'a*(b+c)=a*b+a*c；约0.33。'}]})
    backend=Reviewer()
    result=asyncio.run(bundles._resource_review_async(backend,manifest={},semantic_plan='只核对原说明',
        candidates=[{'type':'handout','version_id':'valid-arithmetic','content':'通用示例：0.2×0.8=0.16。'}]))
    assert result['approved'] is True and backend.calls==1


@pytest.mark.parametrize('response', ['missing', 'partial', 'duplicate'])
def test_incomplete_condition_verdict_cannot_approve_a_resource(response):
    claims = conditional_teaching_claims([{'type': 'handout', 'version_id': 'v-condition-complete',
        'content': '只要a=b，就有a+1=b+1。\n只有x=0，x的平方才等于0。'}])
    checks = [{'claimId': c['id'], 'status': 'valid', 'reason': '由给定等式成立。', 'fix': ''}
              for c in claims]
    payload = {'approved': True, 'findings': [], 'rejectedTypes': []}
    if response != 'missing':
        payload['conditionReview'] = checks[:1] if response == 'partial' else [checks[0], checks[0]]
    with pytest.raises(ValueError, match='核对|本次讲解'):
        apply_condition_review(payload, claims)


def test_retry_incomplete_review_and_do_not_reuse_its_cached_approval():
    class IncompleteReviewer:
        def __init__(self):
            self.calls = 0

        async def generate(self, system, user, *, role):
            self.calls += 1
            checks = [{'claimId': c['id'], 'status': 'valid', 'reason': '等式成立。', 'fix': ''}
                      for c in json.loads(user)['condition_claims']]
            return json.dumps({'approved': True, 'summary': '核对完成', 'findings': [],
                               'rejectedTypes': [], 'conditionReview': checks[:1] if self.calls == 1 else checks})

    backend = IncompleteReviewer(); cache = {}
    current = [{'type': 'handout', 'version_id': 'retry-condition-complete', 'content':
                '只要a=b，就有a+1=b+1。\n只有x=0，x的平方才等于0。'}]
    def run():
        return asyncio.run(bundles._resource_review_async(backend, manifest={}, semantic_plan='核对两个等式',
            candidates=current, completed_reviews=cache, save_review=cache.__setitem__))
    assert run()['approved'] is True and backend.calls == 2
    assert any(value.get('conditionReviewAttempts') for value in cache.values())
    assert run()['approved'] is True and backend.calls == 2
    # A resumed run must not trust a previously stored partial approval.
    next(value for value in cache.values() if value.get('approved'))['conditionReview'].pop()
    assert run()['approved'] is True and backend.calls == 3


def test_section_and_whole_review_keep_one_complete_verdict_without_hiding_rejection():
    from app.resource_review_parts import combine_document_reviews, validate_condition_review
    claims = conditional_teaching_claims([{'type': 'handout', 'version_id': 'condition-parts',
        'content': '只要a=b，就有a+1=b+1。'}])
    valid = {'claimId': claims[0]['id'], 'status': 'valid', 'reason': '局部核对', 'fix': ''}
    adverse = {**valid, 'status': 'incorrect', 'reason': '本测试模拟整份审核发现矛盾', 'fix': '核对上下文'}
    results = [{'approved': True, 'conditionReview': [valid]},
               {'approved': False, 'rejectedTypes': ['handout'], 'conditionReview': [adverse]}]
    combined = combine_document_reviews(results)
    assert combined['approved'] is False
    assert validate_condition_review(combined, claims) == [adverse]
    assert combined['sectionReviews'] == results


def test_stability_and_equivalence_locator_preserves_actual_context():
    current = [{"type": "handout", "content": json.dumps({
        "explanation": "误差在这个初值下不发散。\n除以x后两式是否等价，要看x能否为0。\n整个分布不变才能保证这个统计量不变。",
        "code": "print('diverge')",
        "options": ["所有初值都发散"],
    }, ensure_ascii=False)}]
    claims = conditional_teaching_claims(current)
    assert [c['quote'] for c in claims] == [
        "误差在这个初值下不发散。", "除以x后两式是否等价，要看x能否为0。", "整个分布不变才能保证这个统计量不变。"]


@pytest.mark.parametrize('heading', [
    '需要的条件与说明：', '哪些条件与口径不能省', '这些设置不可缺少', '以下条件缺一不可',
])
def test_conditional_list_heading_is_not_lost_when_qualifier_is_only_in_heading(heading):
    current = [{'type': 'answer', 'version_id': 'current', 'content':
                heading + '\n1. 决策规则固定。\n2. 各类条件分布不变。'}]
    claims = conditional_teaching_claims(current)
    assert [c['quote'] for c in claims] == [heading]
    # The heading is a review target; the full candidate remains the context.
    assert claims[0]['id'].startswith('current:content:')


def test_multiplicative_shrinkage_claim_is_included_in_condition_review():
    candidates = [{'type': 'handout', 'content': '参数乘上(1-αλ)，即直接收缩参数。'}]
    claims = conditional_teaching_claims(candidates)
    assert any('直接收缩参数' in str(item) for item in claims)


def test_local_reviews_keep_complete_resource_and_dependencies_then_reject_cross_resource_conflict():
    current = [
        {'type': 'handout', 'version_id': 'long-handout', 'content': json.dumps({
            'sections': [{'body': '完整讲解。' * 650 + f'正文末尾{i}'} for i in range(10)]}, ensure_ascii=False)},
        {'type': 'quiz', 'version_id': 'quiz-actual', 'content': '与前文矛盾的题干，须在整体核对发现'},
    ]
    code = {'type': 'code_sandbox', 'version_id': 'actual-code', 'content': 'print(18)'}
    optional = {'type': 'video', 'version_id': 'optional-video', 'content': '补充视频全文'}
    checked = set()
    class ScopedReviewer:
        async def generate(self, system, user, *, role):
            data = json.loads(user)
            scope = data['review_scope']
            if scope['stage'] == 'section':
                assert len(data['candidates']) == 1 and scope['candidate_index'] == 0
                own = data['candidates'][0]
                assert own in current  # full, unchanged text including the tail
                assert data['dependency_resources'] == []
                checked.add(own['version_id'])
                return json.dumps({'approved': True, 'rejectedTypes': [], 'findings': [],
                    'conditionReview': [{'claimId': claim['id'], 'status': 'valid', 'reason': '已核对', 'fix': ''}
                                        for claim in data['condition_claims']]})
            assert data['candidates'] == current
            assert data['dependency_resources'] == [code, optional]
            assert checked == {'long-handout', 'quiz-actual'}
            assert data['completed_section_reviews']
            return json.dumps({'approved': False, 'conditionReview': [], 'rejectedTypes': ['quiz'],
                'summary': '题干与讲义冲突', 'findings': [{'resourceType': 'quiz',
                    'issue': '同一条件下题干与讲义给出不同结论', 'fix': '核对共同来源后更正题干'}]})
    result = asyncio.run(bundles._resource_review_async(ScopedReviewer(),
        manifest={'dependency_resources': [code, optional]}, semantic_plan='共同学习目标',
        candidates=current, _grouped=True))
    assert result['approved'] is False and result['rejectedTypes'] == ['quiz']
def test_refutation_exercise_is_not_an_assertion_of_the_refuted_proposition():
    from app.resource_review_parts import conditional_teaching_claims
    question = '3. 回答：如果有人说“C 的训练误差最小，所以 C 预测一定最好”，用这张表如何反驳？'
    assert not conditional_teaching_claims([{'type': 'answer', 'version_id': 'v1', 'content': question}])
    assertion = 'C 的训练误差最小，所以 C 预测一定最好。'
    assert conditional_teaching_claims([{'type': 'answer', 'version_id': 'v1', 'content': assertion}])

