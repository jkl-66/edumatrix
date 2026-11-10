from copy import deepcopy

import pytest
from fastapi import HTTPException

from app.database import DBCourse, DBLearningEvent
from app.note_workspace import (create_note_record, prepare_source_metadata, related_notes_payload,
    set_note_relation, restore_note_version, note_payload)
from tests.test_f8_t03_notes import _session


def test_template_course_and_relations_preserve_provenance_history_and_non_mastery():
    db, owner, other = _session()
    try:
        db.add_all([DBCourse(id=cid, title=cid, version='1', manifest_version='1', visibility='public')
                    for cid in ['ai-course', 'other-course']]); db.flush()
        def create(key, person=owner, course='ai-course', concept='共享参数', template='knowledge'):
            kind, metadata = prepare_source_metadata(db, actor=person, source_type='manual',
                metadata={'course_id':course, 'template_id':template, 'route':'untrusted-route'})
            note,_=create_note_record(db, student_id=person.username, actor=person, source=kind,
                content=f'# {key}\n\n同一个参数沿两条路径使用，梯度需要累加。', concepts=[concept],
                source_metadata=metadata, idempotency_key=key)
            return note
        first=create('first-note'); second=create('method-note',template='method')
        foreign=create('foreign-note',person=other); elsewhere=create('other-course-note',course='other-course')
        db.commit()
        original=deepcopy(first.source_metadata)
        assert original == {'course_id':'ai-course','template_id':'knowledge'}
        result=related_notes_payload(db,actor=owner,note_id=first.id)
        assert [row['id'] for row in result['suggestions']] == [second.id]
        assert result['suggestions'][0]['template']=='方法'
        assert result['suggestions'][0]['preview']==second.content
        assert result['suggestions'][0]['route'].startswith('/workspace/notes?')
        current=set_note_relation(db,actor=owner,note_id=first.id,target_id=second.id,
            action='accept',expected_version=1,idempotency_key='link-first-second');db.commit()
        assert current.lock_version==2 and current.content==first.content
        assert current.source_metadata['course_id']=='ai-course'
        assert related_notes_payload(db,actor=owner,note_id=second.id)['linked'][0]['id']==first.id
        replay=set_note_relation(db,actor=owner,note_id=first.id,target_id=second.id,
            action='accept',expected_version=1,idempotency_key='link-first-second')
        assert replay.lock_version==2
        for invalid in [foreign,elsewhere]:
            with pytest.raises(HTTPException):
                set_note_relation(db,actor=owner,note_id=first.id,target_id=invalid.id,
                    action='accept',expected_version=2,idempotency_key='invalid-link')
        restored,_=restore_note_version(db,note_id=first.id,version_number=1,actor=owner,
            expected_version=2,idempotency_key='restore-before-links')
        assert restored.source_metadata==original
        assert not related_notes_payload(db,actor=owner,note_id=second.id)['linked']
        assert note_payload(db,actor=owner,note=first)['course']=={'id':'ai-course','title':'ai-course'}
        assert all(not event.mastery_eligible and event.evidence_strength==0 for event in db.query(DBLearningEvent).all())
    finally:
        db.close()


def test_ignored_note_is_not_suggested_again_after_reload():
    db,owner,_=_session()
    try:
        notes=[]
        for key in ['note-one','note-two']:
            note,_=create_note_record(db,student_id=owner.username,source='manual',content=f'# {key}\n链式法则的两条路径',
                concepts=['链式法则'],actor=owner,idempotency_key=key);notes.append(note)
        db.commit()
        set_note_relation(db,actor=owner,note_id=notes[0].id,target_id=notes[1].id,action='dismiss',
            expected_version=1,idempotency_key='dismiss-related-note');db.commit();db.expire_all()
        assert not related_notes_payload(db,actor=owner,note_id=notes[0].id)['suggestions']
    finally:
        db.close()


def test_wrong_question_reflection_returns_to_owned_original_question_without_changing_score():
    from tests.test_f8_t02_wrong_questions import _canonical_session
    from app.database import DBWrongQuestion
    db, owner, version, wrong_id = _canonical_session()
    try:
        wrong = db.get(DBWrongQuestion, wrong_id)
        wrong.source_object_id = version.id
        db.commit()
        kind, metadata = prepare_source_metadata(db, actor=owner, source_type='wrong_question_reflection',
            metadata={'question_version_id': version.id, 'template_id': 'reflection'})
        note, _ = create_note_record(db, student_id=owner.username, actor=owner, source=kind,
            content='# 梯度方向复盘\n先检查更新方向。', source_metadata=metadata,
            idempotency_key='question-reflection')
        db.commit()
        source = note_payload(db, actor=owner, note=note)['source_context']
        assert source['kind'] == 'wrong_question' and source['available']
        assert 'question_version_id=' + version.id in source['route']
        assert source['location_label'] == '返回这道题'
        assert version.answer_key == {'choice': 'B'}
        assert not db.query(DBLearningEvent).filter_by(mastery_eligible=True).count()
    finally:
        db.close()
def test_old_reader_auto_tags_are_readable_without_changing_user_tags():
    from app.note_workspace import visible_note_tags
    tags = ['知识库', 'course-example', 'text', '待复习']
    assert visible_note_tags(tags, 'knowledge_selection', {'selection_type':'text'}, 'course-example') == ['原文摘录','待复习']
    assert tags == ['知识库', 'course-example', 'text', '待复习']
    assert visible_note_tags(tags, 'manual', {}, 'course-example') == tags
    assert visible_note_tags(['text','图片研究'], 'knowledge_selection', {'selection_type':'text'}, 'course-example') == ['text','图片研究']

