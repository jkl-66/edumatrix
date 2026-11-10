import asyncio
import json

import pytest

from app.resource_generation_parts import generate_document_parts
import app.resource_bundles as bundles


def test_segmented_path_review_retains_schema_permitted_null_and_cached_siblings(monkeypatch):
    from app.path_draft import PathTeachingReview
    from app import resource_generation_parts as parts
    from app.resource_generation_parts import generate_structured_parts
    cache, calls = {}, []
    class Backend:
        async def generate(self, system, user, *, role):
            req = json.loads(user)['part_request']; calls.append(req)
            if req['stage'] == 'plan':
                # Actual saved plan called this an object even though the schema
                # and original review instruction allow null when no rewrite is needed.
                return json.dumps({'entries':[
                    {'key':'findings','kind':'array','objective':'实际问题'},
                    {'key':'node_updates','kind':'array','objective':'局部修改'},
                    {'key':'revised_path','kind':'object','objective':'必要时完整改写，否则null'}], 'complete':True})
            return json.dumps({'value':None if req['path']==['revised_path'] else []})
    def run():
        return asyncio.run(generate_structured_parts(Backend(),resource_type='path_review',system='原审核',
            user=json.dumps({'output_schema':PathTeachingReview.model_json_schema()}),
            completed=cache,save=cache.__setitem__))
    with monkeypatch.context() as old_validator:
        old_validator.setattr(parts, '_schema_allows_null', lambda *_:False)
        with pytest.raises(ValueError,match='类型为object'):
            run()
    assert len(calls)==5  # saved siblings plus the two original false rejections
    result = run()
    assert PathTeachingReview.model_validate(result).revised_path is None
    assert result == {'findings':[], 'node_updates':[], 'revised_path':None}
    assert len(calls)==5
    assert run()==result and len(calls)==5


def test_segmented_required_object_still_rejects_null():
    from app.resource_generation_parts import generate_structured_parts
    cache = {}
    class Backend:
        async def generate(self, system, user, *, role):
            req=json.loads(user)['part_request']
            if req['stage']=='plan':
                return json.dumps({'entries':[{'key':'question','kind':'object','objective':'完整题目'}], 'complete':True})
            return '{"value":null}'
    with pytest.raises(ValueError,match='类型为object'):
        asyncio.run(generate_structured_parts(Backend(),resource_type='quiz',system='题目',
            user=json.dumps({'output_schema':{'type':'object','properties':{'question':{'type':'object'}}}}),
            completed=cache,save=cache.__setitem__))


def test_malformed_structured_part_is_corrected_and_never_cached_as_success():
    from app.resource_generation_parts import generate_structured_parts
    cache, calls = {}, []
    class Backend:
        async def generate(self, system, user, *, role):
            data = json.loads(user)
            calls.append(data)
            req = data['part_request']
            if req['stage'] == 'plan':
                return json.dumps({'entries':[{'key':'summary','kind':'string','objective':'说明'}], 'complete':True})
            if 'part_correction' not in data:
                return '{"value": 42}'
            assert '类型为string' in data['part_correction']['error']
            assert data['part_correction']['raw'] == '{"value": 42}'
            return '{"value": "完整讲解"}'
    def run():
        return asyncio.run(generate_structured_parts(Backend(), resource_type='feynman', system='说明',
            user='{}', completed=cache, save=cache.__setitem__))
    assert run() == {'summary':'完整讲解'}
    assert len(calls) == 3
    assert any(value.get('raw') == '{"value": 42}' for value in cache.values())
    assert run() == {'summary':'完整讲解'} and len(calls) == 3


def test_structured_plan_and_long_text_shrink_batches_without_truncating():
    from app.resource_generation_parts import generate_structured_parts
    cache, calls = {}, []
    class Backend:
        async def generate(self, system, user, *, role):
            req = json.loads(user)['part_request']; calls.append(req)
            if req['stage'] == 'plan':
                if req['batch_size'] > 1:
                    raise bundles.ModelOutputLimitError('plan full')
                return json.dumps({'entries':[{'key':'code','kind':'string','objective':'完整代码'}], 'complete':True})
            if req['stage'] == 'value' or req['suggested_characters'] > 3000:
                raise bundles.ModelOutputLimitError('text full')
            return json.dumps({'text': 'first\n' if req['chunk_number'] == 0 else 'second\n',
                               'complete':req['chunk_number'] == 1})
    result = asyncio.run(generate_structured_parts(Backend(), resource_type='code_sandbox', system='说明',
        user='{}', completed=cache, save=cache.__setitem__))
    assert result['code'] == 'first\nsecond\n'
    assert [req['batch_size'] for req in calls if req['stage'] == 'plan'] == [4,2,1]


def test_non_document_overflow_splits_fields_and_reuses_siblings_after_disconnect():
    from app.resource_generation_parts import generate_structured_parts
    cache, calls = {}, []
    state = {"disconnect": True}
    class Backend:
        async def generate(self, system, user, *, role):
            req = json.loads(user)["part_request"]
            calls.append((req["stage"], req["path"]))
            path, stage = req["path"], req["stage"]
            if stage == "plan":
                entries = ([{"key": "summary", "kind": "string", "objective": "介绍"},
                            {"key": "quizQuestions", "kind": "array", "objective": "两道完整题"}]
                           if not path else [{"key": i, "kind": "object", "objective": f"完整第{i+1}题"} for i in range(2)])
                return json.dumps({"entries": entries, "complete": True})
            if path == ["summary"]:
                return json.dumps({"value": "练习泛化与验证"})
            if path == ["quizQuestions"]:
                raise bundles.ModelOutputLimitError("array too long")
            if path == ["quizQuestions", 1] and state["disconnect"]:
                raise RuntimeError("HTTP 503")
            return json.dumps({"value": {"prompt": f"题{path[-1]+1}", "answer": "A", "explanation": "完整解释"}})
    def run():
        return asyncio.run(generate_structured_parts(Backend(), resource_type="quiz", system="原字段要求",
            user='{}', completed=cache, save=cache.__setitem__))
    with pytest.raises(RuntimeError, match="503"):
        run()
    first = len(calls)
    state["disconnect"] = False
    result = run()
    assert [q["prompt"] for q in result["quizQuestions"]] == ["题1", "题2"]
    assert ("value", ["summary"]) not in calls[first:]
    assert ("value", ["quizQuestions", 0]) not in calls[first:]


def test_complete_candidate_survives_delivery_retry_but_changed_feedback_regenerates():
    cache, calls = {}, []
    class Backend:
        async def generate(self, system, user, *, role):
            calls.append(json.loads(user))
            return json.dumps({'summary': '解释模型边界', 'learningGoal': '核对假设',
                               'narrative': '这里是已生成的完整教学正文。'})
    token = bundles._RESOURCE_PARTS.set((cache, cache.__setitem__))
    def generate(item, briefs=()):
        return asyncio.run(bundles._real_model_payload_async(Backend(), resource_type='feynman', item=item,
                                                           manifest={'resource_briefs': list(briefs)}, source_snapshots=[]))
    try:
        first = generate({'title': '模型假设'})
        assert generate({'title': '模型假设'}) == first and len(calls) == 1
        generate({'title': '模型假设', 'revision_feedback': '区分缺货延期与销售丢失。'})
        assert len(calls) == 2
        assert len(cache) == 2
        brief = {'type': 'feynman', 'goal': '结合已有实验只解释阈值改判',
                 'dependencies': ['interactive_model'], 'qualityChecks': ['保留两个改判行的实际数据']}
        revised = generate({'title': '模型假设'}, [brief])
        assert calls[-1]['resource_brief'] == brief and len(calls) == 3
        assert generate({'title': '模型假设'}, [brief]) == revised and len(calls) == 3
    finally:
        bundles._RESOURCE_PARTS.reset(token)


class PartsBackend:
    model = "test"
    max_tokens = 32768
    reasoning_effort = "max"

    def __init__(self, total=19, fail_at=None, limit_pairs=False):
        self.total = total
        self.state = {"calls": [], "fail_at": fail_at, "limit_pairs": limit_pairs}

    async def generate(self, system, user, *, role):
        data = json.loads(user)
        req = data.get("part_request")
        self.state["calls"].append(req)
        if req is None:
            raise bundles.ModelOutputLimitError("whole document exceeds output capacity")
        assert self.max_tokens == 65536 and self.reasoning_effort == "max"
        stage = req["stage"]
        if stage == "overview":
            result = {"summary": "全部章节", "learningGoal": "核对首尾", "narrative": "内容完整。", "estimatedMinutes": 20}
        elif stage == "plan":
            end = min(self.total, req["start_index"] + req["batch_size"])
            result = {"section_plan": [{"index": i, "title": f"第{i+1}节", "kind": "concept", "objective": f"目标{i+1}"}
                                        for i in range(req["start_index"], end)], "complete": end == self.total}
        elif stage == "sections":
            rows = req["sections_to_write"]
            if self.state["limit_pairs"] and len(rows) > 1:
                raise bundles.ModelOutputLimitError("split this pair")
            if self.state["fail_at"] in [row["index"] for row in rows]:
                raise RuntimeError("temporary connection loss")
            result = {req["return_field"]: [
                {**row, "content": "完整正文" + str(row["index"]),
                 "body": "末尾数据与公式仍在"} for row in rows]}
        elif stage == "practice":
            result = {"starterCode": "print(18)", "codeExplanation": "18",
                      "practiceSteps": [{"title": f"步骤{i}", "instruction": "核对", "expectedResult": "18", "errorGuidance": "相加"} for i in range(4)]}
        else:
            result = {"quizQuestions": [{"prompt": f"题{i}", "options": ["18", "12", "6", "36"], "answer": "A", "explanation": "12+6=18"} for i in range(3)]}
        return json.dumps(result, ensure_ascii=False)


def test_one_long_document_section_continues_fields_and_keeps_prior_sections():
    class LongSection(PartsBackend):
        async def generate(self, system, user, *, role):
            data = json.loads(user)
            req = data['part_request']
            if 'document_part_request' in data:
                self.state['calls'].append(req)
                if req['stage'] == 'plan':
                    return json.dumps({'entries': [{'key': 'handoutSections', 'kind': 'array',
                        'objective': '完整第二节'}], 'complete': True})
                return json.dumps({'value': [{'index': 1, 'title': '长章节', 'content': '完整前段\n完整后段'}]})
            if req['stage'] == 'sections' and any(row['index'] == 1 for row in req['sections_to_write']):
                self.state['calls'].append(req)
                raise bundles.ModelOutputLimitError('single section overflow')
            return await super().generate(system, user, role=role)
    backend = LongSection(total=2); cache = {}
    def run():
        return asyncio.run(generate_document_parts(backend, resource_type='handout', system='原要求',
            user='{}', completed=cache, save=cache.__setitem__))
    result = run()
    assert [row['content'] for row in result['handoutSections']] == ['完整正文0', '完整前段\n完整后段']
    count = len(backend.state['calls'])
    assert run() == result and len(backend.state['calls']) == count


def test_invalid_document_json_is_saved_and_corrected_with_original_draft():
    class BadHeader(PartsBackend):
        async def generate(self, system, user, *, role):
            data = json.loads(user)
            if data['part_request']['stage'] == 'overview' and 'part_correction' not in data:
                return '{"summary":"未闭合'
            if data['part_request']['stage'] == 'overview':
                assert data['part_correction']['raw'] == '{"summary":"未闭合'
            return await super().generate(system, user, role=role)
    cache = {}
    result = asyncio.run(generate_document_parts(BadHeader(total=1), resource_type='deck', system='要求',
        user='{}', completed=cache, save=cache.__setitem__))
    assert len(result['slides']) == 1
    assert any(value.get('raw') == '{"summary":"未闭合' for value in cache.values())


def test_complete_long_resource_keeps_all_sections_and_does_not_mutate_backend():
    backend = PartsBackend(total=25);cache={}
    payload = asyncio.run(generate_document_parts(backend, resource_type="handout", system="教学约束", user='{"source":"原文末尾"}', completed=cache, save=cache.__setitem__))
    assert len(payload["handoutSections"]) == 25
    assert payload["handoutSections"][-1]["content"] == "完整正文24"
    assert [item["id"] for item in payload["handoutSections"]] == [f"section-{i+1}" for i in range(25)]
    assert len(payload["quizQuestions"]) == 3
    assert backend.max_tokens == 32768


def test_opening_task_survives_overflow_continuation_and_publication():
    from app.m5_resources import parse_handout_content

    class TaskParts(PartsBackend):
        async def generate(self, system, user, *, role):
            result = json.loads(await super().generate(system, user, role=role))
            req = json.loads(user).get('part_request', {})
            if req.get('stage') == 'sections':
                for row in result['handoutSections']:
                    if row['index'] == 0:
                        row.update(kind='task', content='甲乙验证误差为0.12和0.08。选哪个？',
                                   hint='比较验证误差。', successCheck='选乙，0.08较低。')
            return json.dumps(result,ensure_ascii=False)

    backend=TaskParts(total=3, fail_at=2);cache={}
    def generate():
        return asyncio.run(generate_document_parts(backend, resource_type='handout', system='按掌握安排',
            user='{}', completed=cache, save=cache.__setitem__))
    with pytest.raises(RuntimeError, match='connection'):
        generate()
    count=len(backend.state['calls']);backend.state['fail_at']=None
    payload=generate()
    assert not any(r['stage']=='sections' and r['sections_to_write'][0]['index']==0
                   for r in backend.state['calls'][count:])
    assert payload['handoutSections'][0]['successCheck']=='选乙，0.08较低。'
    content=bundles._llm_resource_content(resource_type='handout', item={'title':'先做新任务'}, manifest={},
        source_snapshots=[{'source_ref_id':'src-selection', 'title':'验证选模',
                           'quote':'按验证误差比较候选。', 'available':True}],
        linked_resource_ids=[], llm_payload=payload)
    published=parse_handout_content(content)
    assert published.outline[0].id=='legacy-section-1'
    assert published.transferTasks[0].id==published.outline[0].id
    assert published.transferTasks[0].successCheck=='选乙，0.08较低。'
    assert all('选乙，0.08较低。' not in c.explanation for c in published.concepts)


def test_complete_plan_larger_than_suggested_batch_is_kept_without_reasking():
    class CompletePlan(PartsBackend):
        async def generate(self, system, user, *, role):
            data = json.loads(user)
            request = data.get("part_request") or {}
            if request.get("stage") == "plan":
                data["part_request"]["batch_size"] = self.total
            return await super().generate(system, json.dumps(data), role=role)
    backend = CompletePlan(total=12); cache = {}
    payload = asyncio.run(generate_document_parts(backend, resource_type="deck", system="12页",
        user="{}", completed=cache, save=cache.__setitem__))
    assert len(payload["slides"]) == 12
    assert sum(call["stage"] == "plan" for call in backend.state["calls"]) == 1


def test_non_programming_handout_continuation_does_not_demand_code():
    class NoCodeBackend(PartsBackend):
        async def generate(self, system, user, *, role):
            result = json.loads(await super().generate(system, user, role=role))
            result.pop('starterCode', None)
            result.pop('codeExplanation', None)
            return json.dumps(result, ensure_ascii=False)
    backend = NoCodeBackend(total=3); cache = {}
    result = asyncio.run(generate_document_parts(backend, resource_type='handout', system='摄影，不需要代码',
        user='{}', completed=cache, save=cache.__setitem__))
    assert len(result['handoutSections']) == 3 and len(result['quizQuestions']) == 3
    assert not result.get('starterCode')
    assert sum(call['stage'] == 'practice' for call in backend.state['calls']) == 1


def test_later_sections_receive_all_prior_content_for_consistency():
    backend = PartsBackend(total=5); cache = {}
    asyncio.run(generate_document_parts(backend, resource_type="handout", system="课程",
        user="{}", completed=cache, save=cache.__setitem__))
    calls = [row for row in backend.state['calls'] if row['stage'] == 'sections']
    for row in calls:
        start = row['sections_to_write'][0]['index']
        previous = row['completed_content']['handoutSections']
        assert len(previous) == start
        assert [part['content'] for part in previous] == [f'完整正文{i}' for i in range(start)]


def test_failure_resumes_completed_batches_and_changed_source_invalidates_them():
    backend=PartsBackend(total=7,fail_at=4);cache={}
    def run(source):
        return asyncio.run(generate_document_parts(backend, resource_type="deck", system="课程", user=json.dumps({"source":source}), completed=cache, save=cache.__setitem__))
    with pytest.raises(RuntimeError, match="connection"):
        run("原版")
    before=len(backend.state["calls"]);backend.state["fail_at"]=None
    payload=run("原版")
    resumed=backend.state["calls"][before:]
    assert all(r["stage"]=="sections" for r in resumed)
    assert resumed[0]["sections_to_write"][0]["index"]==4
    assert len(payload["slides"])==7
    before=len(backend.state["calls"]);run("新版本")
    assert backend.state["calls"][before]["stage"]=="overview"


def test_single_batch_capacity_failure_splits_the_batch_without_losing_sections():
    backend=PartsBackend(total=5,limit_pairs=True);cache={}
    payload=asyncio.run(generate_document_parts(backend,resource_type="deck",system="课程",user="{}",completed=cache,save=cache.__setitem__))
    assert len(payload["slides"])==5
    assert sum(r["stage"]=="sections" for r in backend.state["calls"])==6


@pytest.mark.parametrize("resource_type", ["handout", "deck"])
def test_missing_section_indices_get_specific_correction_without_repeating_completed_work(resource_type):
    class MissingIndexBackend(PartsBackend):
        async def generate(self, system, user, *, role):
            request = json.loads(user).get('part_request') or {}
            result = json.loads(await super().generate(system, user, role=role))
            if request.get('stage') == 'sections' and request['sections_to_write'][0]['index'] == 2:
                if '上一部分结构不完整' not in system:
                    for row in result[request['return_field']]:
                        row['id'] = f"lesson-{row.pop('index')}"
                else:
                    field = request['return_field']
                    assert f'{field}[0].index缺失或不匹配，必须为数值2' in system
                    assert f'{field}[1].index缺失或不匹配，必须为数值3' in system
                    self.state['specific_correction_seen'] = True
            return json.dumps(result, ensure_ascii=False)

    backend = MissingIndexBackend(total=4); cache = {}
    result = asyncio.run(generate_document_parts(backend, resource_type=resource_type,
        system='课程要求', user='{}', completed=cache, save=cache.__setitem__))
    field = 'handoutSections' if resource_type == 'handout' else 'slides'
    assert backend.state['specific_correction_seen']
    assert [row['content'] for row in result[field]] == [f'完整正文{i}' for i in range(4)]
    calls = [c for c in backend.state['calls'] if c['stage'] == 'sections']
    assert [c['sections_to_write'][0]['index'] for c in calls] == [0, 2, 2]


def test_current_generator_resumes_parts_and_still_validates_normal_resource_shape():
    backend=PartsBackend(total=5,fail_at=2);cache={}
    token=bundles._RESOURCE_PARTS.set((cache,cache.__setitem__))
    def run():
        return asyncio.run(bundles._real_model_payload_async(backend,resource_type="handout",item={},manifest={},source_snapshots=[]))
    try:
        with pytest.raises(bundles.ResourceBundleError):run()
        before=len(backend.state["calls"]);backend.state["fail_at"]=None
        result=run()
        assert all(r is not None for r in backend.state["calls"][before:])
        assert len(result["handoutSections"])==5
        assert len(result["practiceSteps"])==4
    finally:bundles._RESOURCE_PARTS.reset(token)


def test_shape_correction_overflow_resumes_without_regenerating_original():
    class ShapeBackend(PartsBackend):
        async def generate(self, system, user, *, role):
            if "part_request" not in json.loads(user):
                self.state["whole_calls"] = self.state.get("whole_calls", 0) + 1
                if "结构不满足" in system:
                    raise bundles.ModelOutputLimitError("correction too long")
                return json.dumps({"summary": "未完成课件", "narrative": "要补齐页面", "slides": []})
            return await super().generate(system, user, role=role)

    backend = ShapeBackend(total=5, fail_at=2); cache = {}
    token = bundles._RESOURCE_PARTS.set((cache, cache.__setitem__))
    def run():
        return asyncio.run(bundles._real_model_payload_async(backend, resource_type="deck", item={}, manifest={}, source_snapshots=[]))
    try:
        with pytest.raises(bundles.ResourceBundleError): run()
        assert backend.state["whole_calls"] == 2
        backend.state["fail_at"] = None
        result = run()
        assert backend.state["whole_calls"] == 2
        assert len(result["slides"]) == 5
    finally:
        bundles._RESOURCE_PARTS.reset(token)


def test_task_retry_reuses_persisted_parts_instead_of_restarting_the_document(monkeypatch):
    from app.competition_demo_seed import seed_competition_demo
    from app.database import DBUser, DBProfileSnapshot, DBTaskEvent
    from tests.test_f6_t03_code_sandbox_resource import _session

    brief = {'type':'deck', 'goal':'完整阅读', 'dependencies': [],
             'qualityChecks':['保留首尾章节及各章例子，作为讲义的替代阅读']}
    seen_roles = []
    class TaskBackend(PartsBackend):
        async def generate(self, system, user, *, role):
            request = json.loads(user)
            seen_roles.append(role)
            if role == 'resource_planner':
                return json.dumps({'summary':'按章节讲解','plan':'依次核对每章的条件与例子。','resourceBriefs':[brief]})
            if role == 'resource_reviewer':
                assert request['resource_briefs'] == []
                assert request['active_requirements']['by_resource']['deck'] == [brief['goal'], *brief['qualityChecks']]
                return json.dumps({'approved':True,'summary':'内容已核对','findings':[],'rejectedTypes':[],
                    'conditionReview': [{'claimId': claim['id'], 'status': 'valid',
                        'reason': '合成结构回归的条件已核对。', 'fix': ''}
                        for claim in request.get('condition_claims', [])]})
            assert request['resource_brief'] == brief
            return await super().generate(system,user,role=role)

    backend=TaskBackend(total=5,fail_at=2)
    monkeypatch.setattr(bundles,'_real_model_backend',lambda:backend)
    engine,db=_session()
    try:
        seed_competition_demo(db)
        actor=db.query(DBUser).filter_by(username='lzz').one()
        profile=db.get(DBProfileSnapshot,'demo-profile-lzz-v1')
        job=bundles.create_generation_job(db,actor,course_id='demo-course-rag-trust-v1',knowledge_point_id='demo-kp-07',
            profile_snapshot_id=profile.id,idempotency_key='resume-saved-resource-parts',scope='single',
            items=[{'type':'deck','title':'完整课件','source_ref_ids':['demo-ref-07']}],selected_resource_types=['deck'],
            learning_goal='核对首尾章节',resource_intent='custom_resource',user_instruction='完整讲解')
        first=bundles.execute_generation_job(db,actor,job['job_id'])
        assert first['status']=='failed'
        assert db.query(DBTaskEvent).filter_by(task_id=job['job_id'],event_type='resource_generation.part_result').count()>2
        count=len(backend.state['calls']);backend.state['fail_at']=None
        bundles.retry_generation_item(db,actor,job['job_id'],'deck')
        resumed=bundles.execute_generation_job(db,actor,job['job_id'])
        assert resumed['status']=='succeeded', json.dumps([
            (event.event_type, event.payload) for event in db.query(DBTaskEvent).filter_by(task_id=job['job_id']).all()
            if 'review' in event.event_type], ensure_ascii=False)
        remaining=backend.state['calls'][count:]
        assert remaining and all(r is not None and r['stage']=='sections' for r in remaining)
        assert remaining[0]['sections_to_write'][0]['index']==2
        assert seen_roles.count('resource_planner') == 1
        assert 'resource_reviewer' in seen_roles
    finally:
        db.close();engine.dispose()
