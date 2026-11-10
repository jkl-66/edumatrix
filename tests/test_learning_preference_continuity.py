from copy import deepcopy
from datetime import timedelta

from app.database import DBCourse, DBKnowledgePoint, DBProfileSnapshot, DBStudentProfile
from app.learning_aggregation import aggregate_learning_event
from app.profile_adaptation import build_profile_adaptation, complete_learning_snapshot
from app.resource_bundles import _generation_context_snapshot, _recent_learning_context
from tests.test_learning_aggregation import _session, _graded_event, BASE_TIME, COURSE, CONCEPT


def test_learning_feedback_keeps_confirmed_preferences_with_new_scores():
    db, owner, _ = _session()
    try:
        profile = db.get(DBStudentProfile, owner.username)
        profile.cognitive_style = '先看最小可运行代码，再解释机制；先不做长推导。'
        profile.interaction_preferences = ['代码', '对照验证']
        profile.knowledge_base = '会Python，导数仍需逐步衔接。'
        profile.learning_goals = ['分析传感器数据']
        before = dict(profile.concept_mastery)
        event = _graded_event('correct'); db.add(event); db.flush()
        result = aggregate_learning_event(db, event=event)
        snapshot = db.get(DBProfileSnapshot, result.result['steps']['profile_snapshot']['profile_snapshot_id'])
        adapted = build_profile_adaptation(snapshot, knowledge_point={'id':'kp-gradient-descent','title':CONCEPT})
        assert adapted['explanation_style'] == profile.cognitive_style
        assert adapted['registration_profile']['interaction_preferences'] == ['代码', '对照验证']
        assert adapted['registration_profile']['knowledge_base'] == profile.knowledge_base
        assert adapted['point_mastery'] > before[CONCEPT]
        frozen = deepcopy(snapshot.snapshot)
        profile.cognitive_style = '以后先看定义'
        assert build_profile_adaptation(snapshot)['explanation_style'] != profile.cognitive_style
        assert snapshot.snapshot == frozen
    finally:
        db.close()


def test_legacy_feedback_uses_same_learner_course_preferences_at_snapshot_time():
    db, owner, other = _session()
    def add(id, when, owner_id, course, **projection):
        row=DBProfileSnapshot(id=id,owner_public_id=owner_id,legacy_student_id=owner.username,
            profile_version='test',content_hash=id,trace_id=id,created_at=BASE_TIME+timedelta(minutes=when),
            snapshot={'course_id':course,'profile_projection':projection})
        db.add(row);return row
    try:
        add('confirmed',0,owner.public_id,COURSE,cognitive_style='先代码再机制',interaction_preferences=['代码'],knowledge_base='会Python',learning_goals=['工程应用'])
        add('other-course',1,owner.public_id,'another-course',cognitive_style='只看反例')
        add('other-user',1,other.public_id,COURSE,cognitive_style='只看图')
        add('future',4,owner.public_id,COURSE,cognitive_style='以后先公式')
        legacy=add('feedback',2,owner.public_id,COURSE)
        legacy.snapshot={'kind':'learning_aggregation_projection','course_id':COURSE,'concept_mastery':{CONCEPT:0.83}}
        db.flush(); original=deepcopy(legacy.snapshot)
        recovered=complete_learning_snapshot(db,legacy)
        assert build_profile_adaptation(recovered)['explanation_style']=='先代码再机制'
        assert recovered['concept_mastery']=={CONCEPT:0.83} and legacy.snapshot==original
        course=db.get(DBCourse,COURSE);point=db.get(DBKnowledgePoint,'kp-gradient-descent')
        context=_generation_context_snapshot(db,actor=owner,course=course,point=point,profile=legacy,learning_goal='本次目标',items=[])
        assert context['profile_adaptation_plan']['explanation_style']=='先代码再机制'
        assert context['profile_adaptation_plan']['point_mastery']==0.83
        add('cleared',3,owner.public_id,COURSE,cognitive_style='',interaction_preferences=[])
        later=add('later-feedback',3.5,owner.public_id,COURSE)
        later.snapshot={'kind':'learning_aggregation_projection','course_id':COURSE}
        db.flush()
        cleared=complete_learning_snapshot(db,later)['profile_projection']
        assert cleared['cognitive_style']=='' and cleared['interaction_preferences']==[]
    finally:
        db.close()


def test_recent_practice_resolves_question_identity_and_excludes_guided_answers():
    db,owner,_=_session()
    try:
        event=_graded_event('correct');event.context_ref={'courseId':COURSE}
        db.add(event);db.flush()
        point=db.get(DBKnowledgePoint,'kp-gradient-descent')
        ids,summary=_recent_learning_context(db,actor=owner,course_id=COURSE,point=point)
        assert ids==[event.id] and '1 条' in summary
        event.mastery_eligible=False;event.evidence_status='none';event.evidence_strength=0;db.flush()
        assert _recent_learning_context(db,actor=owner,course_id=COURSE,point=point)[0]==[]
    finally:
        db.close()
