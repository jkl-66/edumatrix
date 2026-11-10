"""Synthetic course fixtures; no production learning records or model calls."""
from copy import deepcopy
import hashlib

import pytest
from fastapi.testclient import TestClient

from app.database import (DBChapter, DBChapterKnowledgePoint, DBCourse, DBCourseDocument,
                          DBKnowledgePoint, DBLearningEvent, DBSourceDocument, DBSourceRef,
                          DBUser, SessionLocal)
from app.main import app
from app.canonical_retrieval import retrieve_canonical_sources
from app.m1_repository import M1Repository
from app.path_draft import _course_facts
from app.source_refs import project_source_ref
from tests.api_test_helpers import auth_headers


@pytest.fixture
def course_case():
    import uuid
    suffix = uuid.uuid4().hex[:9]
    with TestClient(app) as client:
        username = 'structure_'+suffix
        headers = auth_headers(client, username)
        cid, sid, did = ('course-'+suffix, 'src-'+suffix, 'doc-'+suffix)
        content = '训练集拟合参数。\n\n验证集选择超参数。\n\n测试集只在最终评估使用。'
        starts = [0, content.index('验证集'), content.index('测试集')]
        ends = starts[1:]+[len(content)]
        ids = [f'ch-{suffix}-{i}' for i in range(3)]
        pids = [f'kp-{suffix}-{i}' for i in range(3)]
        sha = hashlib.sha256(content.encode()).hexdigest()
        with SessionLocal() as db:
            actor = db.query(DBUser).filter_by(username=username).one()
            db.add(DBCourse(id=cid, version='test-v1', title='课程结构合成测试', manifest_version='test-v1',
                visibility='private', status='published', owner_public_id=actor.public_id,
                manifest_data={'kind':'personal_course','keep_existing_manifest':'unchanged'}))
            db.flush()
            db.add(DBCourseDocument(id=did, course_id=cid, chapter_order=1, filename='test.md', title='模型评估测试资料',
                                    file_type='md', content=content, content_hash=sha))
            db.add(DBSourceDocument(id=sid, course_id=cid, legacy_document_id=did, filename='test.md',
                title='模型评估测试资料', file_format='md', content_hash=sha, processed_sha256=sha, source_sha256=sha,
                parser_version='test-v1', processing_status='ready', uploader_public_id=actor.public_id))
            db.flush()
            for i in range(3):
                db.add(DBChapter(id=ids[i],course_id=cid,source_document_id=sid,stable_key=f'original-{i}',
                    title=['模型拟合','拟合模型','最终评估'][i],position=i+1,char_start=starts[i],char_end=ends[i]))
                db.add(DBKnowledgePoint(id=pids[i],domain_pack=cid,code=f'K{i}',version='test-v1',
                    title=['训练误差','经验误差','测试误差'][i],level='core',status='active',prerequisites=[]))
            db.flush()
            for i in range(3):
                db.add(DBChapterKnowledgePoint(chapter_id=ids[i], knowledge_point_id=pids[i]))
                db.add(DBSourceRef(id=f'ref-{suffix}-{i}',source_document_id=sid,chapter_id=ids[i],parser_version='test-v1',
                    content_hash=sha,char_start=starts[i],char_end=ends[i],location_kind='chapter',location_index=i+1,
                    location_label=['模型拟合','拟合模型','最终评估'][i],quote=content[starts[i]:ends[i]]))
            db.add(DBLearningEvent(id='existing-'+suffix, owner_public_id=actor.public_id, course_id=cid,
                event_type='synthetic_prior_learning', trace_id='synthetic-'+suffix, object_type='chapter',
                object_id=ids[0], context_ref={'chapter_id':ids[0],'knowledge_point_ids':[pids[1]]},
                payload={'test_only':True,'answer':'训练集拟合参数','score':75}))
            db.commit()
        yield client, headers, cid, sid, ids, pids


def _state(case):
    client, headers, cid, *_ = case
    response = client.get(f'/api/knowledge/courses/{cid}/structure',headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _save(case, state):
    client, headers, cid, *_ = case
    return client.put(f'/api/knowledge/courses/{cid}/structure', headers=headers, json={
        key:state[key] for key in ('revision','source_fingerprint','structure')})


def _confirm(case, revision):
    client, headers, cid, *_ = case
    return client.post(f'/api/knowledge/courses/{cid}/structure/confirm',headers=headers,json={'revision':revision})


def test_draft_confirm_changes_current_outline_graph_and_path_but_preserves_old_evidence(course_case):
    client, headers, cid, sid, chapters, points = course_case
    state = _state(course_case)
    assert not state['draft_saved'] and not state['issues']
    assert state['suggestions'][0]['kind'] == 'adjacent_chapters'
    edits=state['structure']
    first, second, third=edits['chapters']
    first.update(title='拟合与验证',member_ids=chapters[:2],char_end=second['char_end'],knowledge_point_ids=points[:2])
    edits['chapters']=[first,third]
    next(p for p in edits['concepts'] if p['id']==points[1])['merge_into']=points[0]
    edits['units']=[{'key':'practice','title':'模型评估单元','goal':'区分拟合、选参与最终评估','knowledge_point_ids':[points[0],points[2]]}]
    edits['prerequisites']=[{'prerequisite_id':points[0],'dependent_id':points[2],'basis':'teaching_suggestion'}]
    saved=_save(course_case,state)
    assert saved.status_code==200,saved.text
    assert _state(course_case)['structure']==saved.json()['structure']
    with SessionLocal() as db:
        assert len(M1Repository(db).course_outline(cid))==3
        before_events=db.query(DBLearningEvent).count()
        original_event=db.query(DBLearningEvent).filter_by(object_id=chapters[0]).one()
        original_payload=deepcopy(original_event.payload)
        original_context=deepcopy(original_event.context_ref)
        old_refs=[(r.id,r.quote,r.char_start,r.char_end) for r in db.query(DBSourceRef).filter_by(source_document_id=sid).all()]
    result=_confirm(course_case,saved.json()['revision'])
    assert result.status_code==200,result.text
    assert not result.json()['draft_saved']
    with SessionLocal() as db:
        actor=db.query(DBUser).filter_by(username=client.get('/api/auth/me',headers=headers).json()['username']).one()
        outline=M1Repository(db).course_outline(cid)
        assert [ch['title'] for ch in outline]==['拟合与验证','最终评估']
        assert [p['id'] for ch in outline for p in ch['knowledge_points']]==[points[0],points[2]]
        assert db.get(DBChapter,chapters[0]).title=='模型拟合'
        assert all(db.get(DBSourceRef,rid).quote==quote and (db.get(DBSourceRef,rid).char_start,db.get(DBSourceRef,rid).char_end)==(a,b) for rid,quote,a,b in old_refs)
        assert project_source_ref(db,old_refs[0][0],actor=actor)['available'] is True
        assert db.query(DBLearningEvent).count()==before_events
        kept_event=db.query(DBLearningEvent).filter_by(object_id=chapters[0]).one()
        assert kept_event.payload==original_payload and kept_event.context_ref==original_context
        assert db.get(DBCourse,cid).manifest_data['keep_existing_manifest']=='unchanged'
        facts=_course_facts(db,course_id=cid)
        assert len(facts['chapters'])==2
        assert facts['knowledge'][points[2]].prerequisites==[points[0]]
        assert facts['teaching_units'][0]['title']=='模型评估单元'
    graph=client.get(f'/api/knowledge/courses/{cid}/graph',headers=headers)
    assert graph.status_code==200,graph.text
    assert graph.json()['statistics']['chapterCount']==2
    assert graph.json()['statistics']['knowledgePointCount']==2
    assert any(e['source']=='knowledge:'+points[0] and e['target']=='knowledge:'+points[2] for e in graph.json()['edges'])
    reader=client.get(f'/api/v1/document-reader/documents/{sid}',headers=headers)
    assert reader.status_code==200,reader.text
    assert [ch['title'] for ch in reader.json()['chapters']]==['拟合与验证','最终评估']
    assert len([ref for ref in reader.json()['source_refs'] if ref['location_kind']=='chapter'])==2
    assert _confirm(course_case,saved.json()['revision']).status_code==200
    with SessionLocal() as db:
        assert db.query(DBChapter).filter_by(course_id=cid).count()==5


def test_incomplete_draft_survives_but_cyclic_prerequisites_cannot_replace_current_structure(course_case):
    state=_state(course_case); points=course_case[-1]
    state['structure']['prerequisites']=[{'prerequisite_id':points[0],'dependent_id':points[2]},
                                          {'prerequisite_id':points[2],'dependent_id':points[0]}]
    saved=_save(course_case,state)
    assert saved.status_code==200
    assert any('循环' in issue for issue in saved.json()['issues'])
    confirm=_confirm(course_case,saved.json()['revision'])
    assert confirm.status_code==422 and '循环' in confirm.text
    assert _state(course_case)['draft_saved']
    with SessionLocal() as db:
        assert len(M1Repository(db).course_outline(course_case[2]))==3


def test_stale_or_overlapping_edits_do_not_drop_new_material_or_original_text(course_case):
    state=_state(course_case); stale=deepcopy(state)
    saved=_save(course_case,state)
    assert saved.status_code==200
    assert _save(course_case,stale).status_code==409
    changed=saved.json()
    changed['structure']['chapters'][0]['char_end']-=2
    incomplete=_save(course_case,changed)
    assert incomplete.status_code==200
    assert any('遗漏' in issue for issue in incomplete.json()['issues'])
    assert _confirm(course_case,incomplete.json()['revision']).status_code==422
    with SessionLocal() as db:
        db.get(DBSourceDocument,course_case[3]).processed_sha256='updated-material'
        db.commit()
    assert _state(course_case)['stale']
    assert _confirm(course_case,incomplete.json()['revision']).status_code==409


def test_original_source_required_for_explicit_prerequisite_claim(course_case):
    state=_state(course_case); points=course_case[-1]
    state['structure']['prerequisites']=[{'prerequisite_id':points[0],'dependent_id':points[2],
        'basis':'source_explicit','quote':'这不是原文。'}]
    saved=_save(course_case,state).json()
    assert _confirm(course_case,saved['revision']).status_code==422
    assert any('原文摘录' in issue for issue in _state(course_case)['issues'])


def test_primary_learning_chapters_cover_unit_and_survive_two_confirmations(course_case):
    state = _state(course_case)
    chapters, points = course_case[-2:]
    state['structure']['units'] = [{'key': 'core', 'title': '拟合与评价', 'goal': '独立区分用途',
        'knowledge_point_ids': [points[0], points[2]], 'primary_chapter_keys': [chapters[0]]}]
    state['structure']['chapters'][1]['learning_role']='reference'
    saved = _save(course_case, state).json()
    assert any('全部知识点' in issue for issue in saved['issues'])
    assert _confirm(course_case, saved['revision']).status_code == 422
    saved['structure']['units'][0]['primary_chapter_keys'].append(chapters[2])
    saved = _save(course_case, saved).json()
    first = _confirm(course_case, saved['revision'])
    assert first.status_code == 200, first.text
    result = first.json()
    keys = result['structure']['units'][0]['primary_chapter_keys']
    assert len(keys) == 2 and not set(keys).intersection(chapters)
    assert set(keys).issubset({ch['key'] for ch in result['structure']['chapters']})
    saved = _save(course_case, result).json()
    second = _confirm(course_case, saved['revision'])
    assert second.status_code == 200, second.text
    result = second.json()
    updated = result['structure']['units'][0]['primary_chapter_keys']
    assert len(updated) == 2 and not set(updated).intersection(keys)
    assert set(updated).issubset({ch['key'] for ch in result['structure']['chapters']})
    assert len([ch for ch in result['structure']['chapters'] if ch['learning_role']=='reference'])==1
    with SessionLocal() as db:
        from app.path_draft import _full_course_tasks
        facts=_course_facts(db,course_id=course_case[2])
        assert len(facts['chapters'])==3 and len(_full_course_tasks(facts))==2


def test_shared_concept_rename_is_local_to_this_course(course_case):
    state=_state(course_case); cid=course_case[2]; point_id=course_case[-1][0]
    with SessionLocal() as db:
        original=db.get(DBCourse,cid)
        other=DBCourse(id=cid+'-other',version='test',title='另一门合成测试课',manifest_version='test',status='published',manifest_data={})
        db.add(other);db.flush()
        src=DBSourceDocument(id=course_case[3]+'-other',course_id=other.id,title='另一份资料',filename='other.md',file_format='md',content_hash='test')
        db.add(src);db.flush()
        ch=DBChapter(id='shared-'+cid,course_id=other.id,source_document_id=src.id,stable_key='test',title='另课章节',char_start=0,char_end=1)
        db.add(ch);db.flush();db.add(DBChapterKnowledgePoint(chapter_id=ch.id,knowledge_point_id=point_id));db.commit()
    next(p for p in state['structure']['concepts'] if p['id']==point_id)['title']='训练集上的误差'
    saved=_save(course_case,state).json()
    response=_confirm(course_case,saved['revision'])
    assert response.status_code==200,response.text
    with SessionLocal() as db:
        assert db.get(DBKnowledgePoint,point_id).title=='训练误差'
        assert M1Repository(db).course_outline(cid)[0]['knowledge_points'][0]['title']=='训练集上的误差'


def test_split_and_reorder_keep_precise_ranges_and_source_links(course_case):
    state=_state(course_case)
    first=state['structure']['chapters'][0]
    second=deepcopy(first);second['key']='new-split';second['title']='拟合的补充说明'
    split=first['char_start']+3
    first['char_end']=split;second['char_start']=split
    state['structure']['chapters']=[second,first,*state['structure']['chapters'][1:]]
    saved=_save(course_case,state).json()
    confirmed=_confirm(course_case,saved['revision'])
    assert confirmed.status_code==200,confirmed.text
    with SessionLocal() as db:
        outline=M1Repository(db).course_outline(course_case[2])
        assert [ch['title'] for ch in outline][:2]==['拟合的补充说明','模型拟合']
        assert db.get(DBSourceRef,outline[0]['source_ref_id']).char_start==split


def test_changed_material_can_restart_draft_without_replacing_applied_outline(course_case):
    client,headers,cid,sid,*_=course_case
    state=_state(course_case)
    first_saved=_save(course_case,state).json()
    first_applied=_confirm(course_case,first_saved['revision'])
    assert first_applied.status_code==200,first_applied.text
    assert not first_applied.json()['needs_confirmation']
    state=first_applied.json()
    saved=_save(course_case,state).json()
    with SessionLocal() as db:
        db.get(DBSourceDocument,sid).processed_sha256='updated-material'
        db.commit()
    assert _state(course_case)['stale']
    restarted=client.post(f'/api/knowledge/courses/{cid}/structure/reset',headers=headers,json={'revision':saved['revision']})
    assert restarted.status_code==200,restarted.text
    current=restarted.json()
    assert not current['stale'] and not current['draft_saved'] and not current['issues']
    assert current['needs_confirmation']
    assert _save(course_case,current).status_code==200
    with SessionLocal() as db:
        assert len(M1Repository(db).course_outline(cid))==3


def test_consecutive_merges_keep_aliases_and_do_not_restore_deleted_units(course_case):
    state=_state(course_case); points=course_case[-1]
    next(p for p in state['structure']['concepts'] if p['id']==points[1])['merge_into']=points[0]
    state['structure']['units']=[]
    saved=_save(course_case,state).json()
    first=_confirm(course_case,saved['revision'])
    assert first.status_code==200,first.text
    state=first.json()
    assert state['structure']['units']==[]
    next(p for p in state['structure']['concepts'] if p['id']==points[0])['merge_into']=points[2]
    saved=_save(course_case,state).json()
    second=_confirm(course_case,saved['revision'])
    assert second.status_code==200,second.text
    with SessionLocal() as db:
        aliases=db.get(DBCourse,course_case[2]).manifest_data['structure_workspace']['applied']['concept_aliases']
        assert aliases=={points[0]:points[2],points[1]:points[2]}


def test_document_local_chapter_numbers_do_not_interleave_different_materials(course_case):
    cid,sid=course_case[2:4]
    with SessionLocal() as db:
        db.add(DBCourseDocument(id='second-'+cid,course_id=cid,chapter_order=2,filename='second.md',
                               title='第二份资料',file_type='md',content='第二份资料的第一章。',content_hash='test'))
        db.add(DBSourceDocument(id='second-'+sid,course_id=cid,legacy_document_id='second-'+cid,
                               filename='second.md',title='第二份资料',file_format='md',content_hash='test',processing_status='ready'))
        db.flush()
        db.add(DBChapter(id='second-'+cid,course_id=cid,source_document_id='second-'+sid,
                         stable_key='new-document',title='第二份资料的第一章',position=1,char_start=0,char_end=12))
        db.commit()
    state=_state(course_case)
    assert [ch['key'] for ch in state['structure']['chapters']]==course_case[4]+['second-'+cid]


def test_packaged_structure_checks_source_and_preserves_local_confirmation(course_case):
    from app.course_structure import initialize_curated_structure
    client, headers, cid, sid, chapter_ids, point_ids = course_case
    with SessionLocal() as db:
        course = db.get(DBCourse, cid)
        source = db.get(DBSourceDocument, sid)
        old = [db.get(DBChapter, key) for key in chapter_ids]
        template = {'chapters':[{
            'key':'packaged-'+str(i),'filename':'test.md','title':ch.title,
            'content_sha256':source.processed_sha256,'char_start':ch.char_start,'char_end':ch.char_end,
            'knowledge_point_codes':['K'+str(i)],'learning_role':'reference' if i==1 else 'teaching',
        } for i,ch in enumerate(old)], 'units':[]}
        broken = deepcopy(template);broken['chapters'][0]['content_sha256']='wrong-text'
        with pytest.raises(ValueError,match='does not match source text'):
            initialize_curated_structure(db,course,broken)
        assert not course.manifest_data.get('structure_workspace')
        initialize_curated_structure(db,course,template);db.commit()
        applied = deepcopy(course.manifest_data['structure_workspace'])
        initialize_curated_structure(db,course,template)
        assert course.manifest_data['structure_workspace']==applied
        assert all(db.get(DBChapter,key).stable_key.startswith('structure-history:') for key in chapter_ids)
    state = _state(course_case)
    assert not state['issues'] and state['structure']['chapters'][1]['learning_role']=='reference'
    state['structure']['chapters'][0]['title']='教师调整的章节'
    saved=_save(course_case,state).json()
    assert _confirm(course_case,saved['revision']).status_code==200
    with SessionLocal() as db:
        initialize_curated_structure(db,db.get(DBCourse,cid),template);db.commit()
    assert _state(course_case)['structure']['chapters'][0]['title']=='教师调整的章节'


def test_fresh_packaged_course_keeps_final_document_links_without_autoflush():
    from pathlib import Path
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.database import Base
    from app.path_draft import _full_course_tasks
    from course_catalog import load_versioned_course_bundle, upsert_course_bundle

    manifest = Path(__file__).parents[1] / 'data/curated/ai_deep_learning_agents_v1/course_manifest.json'
    bundle = load_versioned_course_bundle(manifest)
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    try:
        with Session(engine, autoflush=False) as db:
            upsert_course_bundle(db, bundle)
            course = db.get(DBCourse, bundle['course']['id'])
            structure = course.manifest_data['structure_workspace']['applied']['structure']
            facts = _course_facts(db, course_id=course.id)
            assert len(facts['chapters']) == len(bundle['course']['manifest_data']['teaching_structure']['chapters'])
            points = {point.code for point in facts['knowledge'].values()}
            assert set(bundle['documents'][-1]['knowledge_point_codes']) <= points
            assert set(facts['knowledge']) == {point for task in _full_course_tasks(facts) for point in task['knowledge_point_ids']}
            prior = deepcopy(structure)
            upsert_course_bundle(db, bundle)
            assert course.manifest_data['structure_workspace']['applied']['structure'] == prior
    finally:
        engine.dispose()


@pytest.mark.parametrize('assemble_for_task', [False, True])
def test_selected_chapter_retrieval_does_not_use_other_chapters_or_parent_context(course_case, assemble_for_task):
    with SessionLocal() as db:
        result=retrieve_canonical_sources(db,course_id=course_case[2],query='测试集最终评估的公式',
            chapter_ids=[course_case[4][0]],assemble_for_task=assemble_for_task)
        assert result['items']
        evidence=result['items'][0]['evidence']
        assert '测试集' not in evidence.content and '验证集' not in evidence.content
        assert '测试集' not in evidence.metadata.get('parent_content','')
        assert result['low_confidence']


def test_merged_concept_keeps_prior_learning_evidence_without_rewriting_scores(course_case):
    from app.profile_summary import _knowledge_graph
    _, _, cid, _, _, points = course_case
    with SessionLocal() as db:
        prior = db.query(DBLearningEvent).filter_by(course_id=cid).one()
        event = DBLearningEvent(id='alias-test-'+cid, owner_public_id=prior.owner_public_id, course_id=cid,
            event_type='synthetic_prior_learning', trace_id='alias-test-'+cid,
            object_type='knowledge_point', object_id=points[1], mastery_eligible=True, evidence_status='accepted', evidence_strength=.7,
            context_ref={'knowledge_point_ids': [points[0], points[1]]}, payload={'test_only': True, 'score': .67})
        db.add(event)
        db.commit()
        original = (event.id, deepcopy(event.payload), deepcopy(event.context_ref))
    state = _state(course_case)
    state['structure']['concepts'][1]['merge_into'] = points[0]
    state['structure']['prerequisites'] = [{'prerequisite_id': points[0], 'dependent_id': points[2],
        'basis': 'teaching_suggestion', 'source_ref_id': None, 'quote': ''}]
    saved = _save(course_case, state)
    assert saved.status_code == 200
    assert _confirm(course_case, saved.json()['revision']).status_code == 200
    with SessionLocal() as db:
        event = db.get(DBLearningEvent, original[0])
        graph = _knowledge_graph(session=db, course_id=cid, snapshot={'concept_mastery': {'经验误差': .67}},
            snapshot_row=None, attempts=[], grading_by_attempt={}, versions={}, events=[event], profile_evidence_rows=[])
        current = next(node for node in graph['nodes'] if node['id'] == points[0])
        assert current['mastery'] == .67
        assert current['sourceEventIds'] == [event.id] and current['evidenceCount'] == 1
        assert not any(node['id'] == points[1] for node in graph['nodes'])
        assert any(edge['source'] == points[0] and edge['target'] == points[2] for edge in graph['edges'])
        assert (event.id, event.payload, event.context_ref) == original


def test_semantic_analysis_is_saved_but_not_applied_and_invalidates_after_edit(course_case, monkeypatch):
    import knowledge_api
    from types import SimpleNamespace
    original = _state(course_case)
    async def analyze(state, bodies, llm, owner, on_progress=None):
        assert state['course_id'] == course_case[2]
        assert bodies[course_case[3]].startswith('训练集')
        return {'status': 'ready', 'suggestions': [{'id': 'synthetic-proposal'}],
                'batches': [{'key': 'synthetic-original-batch', 'status': 'ready', 'suggestions': []}]}
    monkeypatch.setattr(knowledge_api, 'analyze_structure', analyze)
    monkeypatch.setattr(knowledge_api, 'build_swarm_from_headers', lambda headers: SimpleNamespace(llm=object()))
    client, headers, cid, *_ = course_case
    response = client.post(f'/api/knowledge/courses/{cid}/structure/analyze', headers=headers, json={'revision': original['revision']})
    assert response.status_code == 200, response.text
    current = _state(course_case)
    assert current['semantic_analysis']['suggestions'] == [{'id': 'synthetic-proposal'}]
    assert current['structure'] == original['structure']
    current['structure']['chapters'][0]['title'] = '新的章名'
    assert _save(course_case, current).status_code == 200
    assert _state(course_case)['semantic_analysis'] is None
    # The public response hides stale suggestions, but analysis can still reuse
    # exact matching inputs, including after confirmation changes inventory ids.
    from app.course_structure import prepare_structure_analysis
    with SessionLocal() as db:
        course = db.get(DBCourse, cid)
        actor = db.query(DBUser).filter_by(public_id=course.owner_public_id).one()
        prepared, _ = prepare_structure_analysis(db, actor, cid)
        assert prepared['semantic_analysis'] is None
        assert prepared['_analysis_batches'][0]['key'] == 'synthetic-original-batch'
    assert _confirm(course_case, _state(course_case)['revision']).status_code == 200
    with SessionLocal() as db:
        course = db.get(DBCourse, cid)
        actor = db.query(DBUser).filter_by(public_id=course.owner_public_id).one()
        prepared, _ = prepare_structure_analysis(db, actor, cid)
        assert prepared['semantic_analysis'] is None
        assert prepared['_analysis_batches'][0]['key'] == 'synthetic-original-batch'
    stale = client.post(f'/api/knowledge/courses/{cid}/structure/analyze', headers=headers, json={'revision': original['revision']})
    assert stale.status_code == 409
