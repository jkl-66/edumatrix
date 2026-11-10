import asyncio
import hashlib
import json
import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base, DBCourse, DBCourseDocument, DBSourceDocument, DBSourceRef, DBUser
from app.resource_bundles import (
    _generation_task_evidence, _resource_prompt_sources, _source_snapshots,
    _source_snapshot_hash, _real_model_prompt, _shared_semantic_plan_async,
)


def test_initial_request_survives_lossy_plan_but_is_retired_after_revision():
    import app.resource_bundles as bundles
    from app.resource_review_context import requirements_snapshot

    request = '复算训练和验证误差，解释选模依据；必须恰好两句话。'
    class Planner:
        async def generate(self, system, user, **kwargs):
            # Reproduce the observed omission in a model-produced summary.
            return json.dumps({'plan': '计算验证误差', 'activeRequirements': {
                'learning_goal': '比较模型', 'shared': ['计算验证误差'], 'by_resource': {}}})
    initial = {'user_instruction': request, 'selected_resource_types': ['handout'], 'context': {}}
    plan = asyncio.run(_shared_semantic_plan_async(Planner(), manifest=initial, source_snapshots=[]))
    current = requirements_snapshot(plan['active_requirements'])
    assert current['source_request'] == request
    _, user = _real_model_prompt(resource_type='handout', item={},
        manifest={**initial, 'active_requirements': current}, source_snapshots=[])
    assert json.loads(user)['active_requirements']['source_request'] == request

    class Reviewer:
        async def generate(self, system, user, **kwargs):
            assert json.loads(user)['active_requirements']['source_request'] == request
            return json.dumps({'approved': True, 'findings': [], 'conditionReview': [], 'rejectedTypes': []})
    asyncio.run(bundles._resource_review_async(Reviewer(), manifest={**initial, 'active_requirements': current},
        semantic_plan='计算验证误差', candidates=[{'type': 'handout', 'version_id': 'v1', 'content': '{}'}], _grouped=True))

    revised = asyncio.run(_shared_semantic_plan_async(Planner(), manifest={**initial,
        'active_requirements': current, 'teaching_revision': {'feedback': '取消句数限制', 'resource_types': ['handout']}}, source_snapshots=[]))
    assert 'source_request' not in revised['active_requirements']
    _, user = _real_model_prompt(resource_type='handout', item={},
        manifest={**initial, 'active_requirements': revised['active_requirements']}, source_snapshots=[])
    assert '必须恰好两句话' not in user


@pytest.mark.parametrize('selected,dependencies,wants_template', [
    (['handout'], [], False),
    (['quiz', 'mind_map'], [], False),
    (['training_task'], [], True),
    (['interactive_model', 'handout'], [], True),
    (['deck'], [{'type': 'interactive_model', 'content': '实际配套实验'}], True),
])
@pytest.mark.parametrize('stage', ['planner', 'reviewer'])
def test_teaching_roles_receive_only_selected_actions_and_relevant_lab(monkeypatch, selected, dependencies, wants_template, stage):
    import app.resource_bundles as bundles
    monkeypatch.setattr(bundles, '_interactive_template_for_knowledge_point', lambda *args: {'id': 'actual-lab'})
    monkeypatch.setattr(bundles, '_interactive_template_directory', lambda value: value)
    class Backend:
        async def generate(self, system, user, **kwargs):
            captured = json.loads(user)
            assert set(captured['learning_actions']) == set(selected)
            assert captured['dependency_resources'] == dependencies
            assert bool(captured['interactive_template']) == wants_template
            assert not captured.get('user_instruction')
            assert captured['active_requirements']['shared'] == ['保持原题完整']
            assert all(captured['active_requirements']['by_resource'][kind] ==
                       ['可以用角色表辅助两项理由，不以句数评分'] for kind in selected)
            if stage == 'reviewer':
                assert not captured.get('teaching_revision')
                assert '必须恰好两句话' not in user
            return json.dumps({'plan': '对应当前资源的计划', 'summary': '学习安排', 'resourceBriefs': [],
                               'activeRequirements': manifest['active_requirements'],
                               'approved':True, 'findings':[], 'rejectedTypes':[]})
    manifest={
        'items': [{'type': kind} for kind in selected], 'selected_resource_types': selected,
        'context': {'knowledge_point_title': '正则化'}, 'dependency_resources': dependencies,
        'user_instruction': '保持原题完整',
        'active_requirements': {'learning_goal': '理解正则化', 'shared': ['保持原题完整'],
            'by_resource': {kind: ['可以用角色表辅助两项理由，不以句数评分'] for kind in selected}},
        'teaching_revision_history': [{'feedback': '必须恰好两句话'}],
        'teaching_revision': {'feedback': '可以用角色表辅助两项理由，不以句数评分',
                             'resource_types': selected}}
    if stage=='planner':
        asyncio.run(_shared_semantic_plan_async(Backend(), manifest=manifest, source_snapshots=[]))
    else:
        # A review group must use its actual candidates, even when the larger
        # generation job contains additional types.
        manifest['selected_resource_types']=list(set(selected+['video','interactive_model']))
        asyncio.run(bundles._resource_review_async(Backend(),manifest=manifest,semantic_plan='当前教学计划',
            candidates=[{'type':kind,'version_id':kind+'-v1','content':'{}'} for kind in selected],_grouped=True))


def test_generation_retrieves_late_selected_material_and_freezes_it():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    prefix = '\n\n'.join(f'## 预备章节{i}\n数组用于保存数字，矩阵用于组织数据。' * 6 for i in range(100))
    tail = '\n\n## 权重衰减\n权重衰减在损失中增加平方范数惩罚。\n$$L=E+\\lambda\\|w\\|^2/2$$\n其中正则强度lambda非负；偏置通常不参与惩罚。\n合成示例DemoAPI.weight_decay用于演示正则强度。'
    body = prefix + tail
    assert len(prefix) > 12000  # Exercise the former whole-source truncation.
    digest = hashlib.sha256(body.encode()).hexdigest()
    with Session(engine) as db:
        actor = DBUser(public_id='owner', username='owner', hashed_password='test', role='student')
        course = DBCourse(id='course', title='深度学习', version='1', status='published', manifest_version='1', owner_public_id='owner')
        document = DBCourseDocument(id='doc', course_id='course', chapter_order=1, filename='book.md', content=body, content_hash=digest)
        source = DBSourceDocument(id='src', course_id='course', legacy_document_id='doc', title='教材', filename='book.md', file_format='markdown', content_hash=digest, processed_sha256=digest, parser_version='v1', processing_status='ready')
        ref = DBSourceRef(id='selected', source_document_id='src', char_start=0, char_end=len(body), location_kind='chapter', parser_version='v1', content_hash=digest, quote=body[:200])
        # An unselected source has a more conspicuous match, but must stay out.
        outsider = DBSourceDocument(id='other', course_id='course', title='未选材料', filename='other.md', file_format='markdown', content_hash='other', processed_sha256='other', parser_version='v1', processing_status='ready')
        outside_ref = DBSourceRef(id='unselected', source_document_id='other', location_kind='chapter', parser_version='v1', content_hash='other', quote='权重衰减公式不应从这份资料取用')
        db.add_all([actor, course, document, source, ref, outsider, outside_ref]); db.flush()
        frozen = _source_snapshots(db, course_id='course', source_ref_ids=['selected'], require_available=True)
        assert frozen[0]['quote'] == body
        before = _source_snapshot_hash(frozen)
        evidence = _generation_task_evidence(db, actor=actor, course_id='course',
            context={'knowledge_point_title': '权重衰减', 'learning_goal': '解释权重衰减公式与参数适用条件'},
            sources_by_type={'handout': frozen, 'quiz': frozen}, user_instruction='说明lambda和偏置的条件')
        assert evidence['handout'] == evidence['quiz']
        passages = evidence['handout']['passages']
        assert passages and any('偏置通常不参与惩罚' in p['quote'] for p in passages)
        assert all(p['source_ref_id'] == 'selected' for p in passages)
        assert any(p['char_start'] > 6000 for p in passages)
        for p in passages:
            assert body[p['char_start']:p['char_end']] == p['quote']
        assert before == _source_snapshot_hash(frozen)
        manifest = {'input_snapshot': {'task_evidence': evidence}}
        model_sources = _resource_prompt_sources(manifest, frozen, 'handout')
        assert model_sources[0]['scope'] == 'task_passages'
        assert 'quote' not in model_sources[0]  # No unrelated whole-book prefix.
        assert '偏置通常不参与惩罚' in json.dumps(model_sources, ensure_ascii=False)
        # Frozen evidence is read without a new query when retrying/reviewing.
        assert model_sources == _resource_prompt_sources(manifest, frozen, 'quiz')
        # Explicit document selection in ordinary chat must read the same
        # whole chosen source, rather than its short citation preview.
        from app.chat_api import _context_source_refs
        from app.database import DBChatConversation
        chat_refs = _context_source_refs(db, actor, DBChatConversation(id='chat', owner_public_id='owner', course_id='course'),
            [{'sourceRef': {'id': 'selected', 'courseId': 'course'}}], question='说明权重衰减公式、lambda和偏置的条件')
        assert chat_refs and any('偏置通常不参与惩罚' in p['quote'] for p in chat_refs)
        assert all(p['sourceRefId'] == 'selected' for p in chat_refs)
        assert any(p['charStart'] > 12000 for p in chat_refs)
        assert all(body[p['charStart']:p['charEnd']] == p['quote'] for p in chat_refs)
        from app.chat_api import _stream_source_materials
        replayed = _stream_source_materials(db, actor, DBChatConversation(id='chat', owner_public_id='owner', course_id='course'), chat_refs)
        assert [(p['charStart'], p['charEnd'], p['quote']) for p in replayed] == [
            (p['charStart'], p['charEnd'], p['quote']) for p in chat_refs]
        # Fragment selection stays exact, even if a different document matches.
        fragment = DBSourceRef(id='fragment', source_document_id='src', char_start=len(prefix), char_end=len(body), location_kind='selection', parser_version='v1', content_hash=digest, quote=tail)
        db.add(fragment);db.flush()
        exact = _context_source_refs(db, actor, DBChatConversation(id='chat', owner_public_id='owner', course_id='course'),
            [{'sourceRef': {'id': 'fragment', 'courseId': 'course'}}], question='概括所选内容')
        assert len(exact) == 1 and exact[0]['quote'] == tail
        # An old parser's chapter must not hide the current document from
        # automatic course retrieval merely because its ID sorts first.
        stale = DBSourceRef(id='000-old', source_document_id='src', char_start=0,
            char_end=len(body), location_kind='chapter', parser_version='v0',
            content_hash=digest, quote=body[:200])
        db.add(stale);db.flush()
        from app.canonical_retrieval import list_canonical_source_refs, retrieve_canonical_sources
        current = list_canonical_source_refs(db, course_id='course', actor=actor)
        assert '000-old' not in {p['source_ref_id'] for p in current}
        automatic = retrieve_canonical_sources(db, course_id='course', query='权重衰减公式与偏置', actor=actor)
        assert not automatic['low_confidence']
        assert any('偏置通常不参与惩罚' in p['evidence'].content for p in automatic['items'])
        historical = retrieve_canonical_sources(db, course_id='course', query='权重衰减公式与偏置', actor=actor, source_ref_ids=['000-old'])
        assert historical['low_confidence']  # No silent upgrade of explicit old citation.
        absent = retrieve_canonical_sources(db, course_id='course',
            query='根据所选资料解释DataGauge2027的权重衰减公式和适用条件', actor=actor,
            source_ref_ids=['selected'], assemble_for_task=True)
        assert absent['items']  # Related teaching material is retained for context.
        assert absent['low_confidence']
        assert 'datagauge2027' in absent['retrieval']['unmatched_query_identifiers']
        attribute = retrieve_canonical_sources(db, course_id='course',
            query='weight_decay正则强度', actor=actor, source_ref_ids=['selected'])
        assert not attribute['low_confidence']
        assert not attribute['retrieval']['unmatched_query_identifiers']
    engine.dispose()


def test_small_sources_and_explicit_selection_are_not_cut_or_retrieved(monkeypatch):
    import app.canonical_retrieval as retrieval
    def unexpected(*args, **kwargs):
        raise AssertionError('Selected short text must not trigger a second selection')
    monkeypatch.setattr(retrieval, 'retrieve_canonical_sources', unexpected)
    sources = [{'source_ref_id': 'small', 'quote': '教学正文' * 100},
               {'source_ref_id': 'selection', 'location_kind': 'selection', 'quote': '所选原文' * 5000 + '最后条件'}]
    result = _generation_task_evidence(None, actor=None, course_id='course', context={}, sources_by_type={'handout': sources}, user_instruction='')
    assert result == {}
    projected = _resource_prompt_sources({}, sources, 'handout')
    assert [item['quote'] for item in projected] == [item['quote'] for item in sources]


@pytest.mark.parametrize('resource_type', ['handout', 'mind_map', 'quiz', 'code_sandbox',
                                        'interactive_model', 'training_task', 'feynman', 'deck', 'video'])
def test_generation_and_plan_keep_instruction_and_late_plan_requirements(resource_type):
    brief = {'type': resource_type, 'goal': '在本页完成分配的学习片段',
             'dependencies': ['前一步已有记录'], 'qualityChecks': ['最后要求：核对适用条件']}
    manifest = {'context': {'knowledge_point_title': '权重衰减'},
                'resource_briefs': [brief, {'type': 'unrelated', 'goal': '其他页的任务'}],
                'user_instruction': '完整学习要求\n' * 900 + '最后要求：比较偏置是否正则化'}
    plan = '完整安排\n' * 3000 + '最后环节：检查参数适用条件'
    source = {'source_ref_id': 'ref', 'quote': '教材正文\n' * 1600 + '最后原文条件'}
    _, user = _real_model_prompt(resource_type=resource_type, item={'title': '学习材料'},
        manifest=manifest, source_snapshots=[source], semantic_plan=plan)
    payload = json.loads(user)
    assert payload['user_instruction'] == manifest['user_instruction']
    assert payload['shared_semantic_plan'] == plan
    assert payload['resource_brief'] == brief
    assert payload['sources'][0]['quote'] == source['quote']
    class Backend:
        async def generate(self, system, user, **kwargs):
            captured = json.loads(user)
            assert captured['user_instruction'] == manifest['user_instruction']
            assert captured['sources'][0]['quote'] == source['quote']
            return json.dumps({'plan': plan, 'summary': '课程安排', 'resourceBriefs': []})
    result = asyncio.run(_shared_semantic_plan_async(Backend(), manifest=manifest, source_snapshots=[source]))
    assert result['plan'] == plan
