"""Confirmed background and practical conditions survive the learning pipeline."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, DBStudentProfile
from app.profile_adaptation import build_profile_adaptation, confirmed_study_days, confirmed_study_minutes, profile_prompt_context
from app.profile_onboarding import (
    _apply_continuous_projection, _derived_signal_fields, _model_field,
    project_confirmed_fields,
)


@pytest.mark.parametrize("detail", [
    "同一模型选择题先看分步提示后完成，独立完成尚未验证。",
    "同一模型选择题独立完成，未查看提示；其它误解仍需核对。",
    "能独立读表，但链式法则仍需逐步提示。",
])
def test_task_independence_evidence_preserves_scope_scores_and_remaining_gaps(detail):
    snapshot = {
        "mastery_by_knowledge_point": {"selection": {"score": .65, "learning_needs": [
            {"criterion_id": "leakage", "score": .2, "basis": "把全量标准化当作无泄漏", "next_step": "核对折内拟合"}]}},
        "dimension_states": {"understanding_fluency_transfer": {
            "qualitative": True, "self_report": detail, "summary": "旧摘要"}},
    }
    original = deepcopy(snapshot)
    plan = build_profile_adaptation(snapshot, knowledge_point={"id": "selection", "title": "模型选择"})
    public = profile_prompt_context(plan)
    assert public["assessment_target"]["independence_evidence"] == detail
    assert public["point_mastery"] == .65
    assert public["assessment_target"]["learning_needs"][0]["criterion_id"] == "leakage"
    assert snapshot == original


@pytest.mark.parametrize("score,status", [(.86, "mastered"), (None, "unknown")])
def test_specific_current_evidence_reaches_teaching_target_without_borrowing_other_topics(score, status):
    snapshot = {
        "current_learning_evidence": {
            "selection": {"score": score, "status": status,
                          "basis": "仅核对模型选择，MSE计算尚未测量。", "learning_needs": []},
            "backprop": {"score": .95, "basis": "已独立推导梯度"}},
        "mastery_by_knowledge_point": {"selection": {"score": .99}},
        "dimension_states": {"understanding_fluency_transfer": {"summary": "迁移待观察"}},
    }
    original = deepcopy(snapshot)
    target = profile_prompt_context(build_profile_adaptation(
        snapshot, knowledge_point={"id": "selection", "title": "模型选择"}))
    assert target["point_mastery"] == score
    assert target["assessment_target"]["current_point_evidence"] == snapshot["current_learning_evidence"]["selection"]
    assert "已独立推导梯度" not in json.dumps(target["assessment_target"], ensure_ascii=False)
    assert snapshot == original


def test_diagnostic_score_keeps_specific_gaps_and_untested_topics_distinct():
    snapshot = {"mastery_by_knowledge_point": {
        "task-types": {"score": .91, "learning_needs": [{"criterion_id": "unlabelled",
            "score": .2, "basis": "将无标签分组当成监督预测", "next_step": "比较分组与预测所需的标签"}]},
        "matrix": {"score": None, "status": "unknown"}},
        "concept_mastery": {"matrix": .9}}
    original = deepcopy(snapshot)
    plan = build_profile_adaptation(snapshot, knowledge_point={"id": "task-types", "title": "任务类型"})
    assert plan["point_mastery"] == .91
    assert plan["difficulty_band"] == "scaffolded"
    assert plan["difficulty_evidence"]["kind"] == "specific_learning_needs"
    assert "比较分组" in plan["mastery_focus"]
    assert "保留已会" in plan["mastery_focus"]
    assert "新例子" in plan["assessment_target"]["task"]
    assert build_profile_adaptation(snapshot, knowledge_point={"id": "matrix"})["point_mastery"] is None
    assert snapshot == original


def test_current_answer_evidence_supersedes_old_gaps_without_rewriting_history():
    snapshot = {"mastery_by_knowledge_point": {"types": {"score": .8}},
        "diagnostic_evidence": {"grading_feedback": [{"knowledge_point_id": "types",
            "attempt_id": "original-answer", "grading": {"status": "completed", "criterionResults": [
                {"criterion_id": "labels", "score": .2, "improvement": "辨认预测需要的标签"}]}}]},
        "current_learning_evidence": {"types": {"score": .95, "learning_needs": []}}}
    original = deepcopy(snapshot)
    plan = build_profile_adaptation(snapshot, knowledge_point={"id": "types"})
    assert plan["point_mastery"] == .95
    assert plan["difficulty_band"] == "transfer"
    assert plan["learning_requirements"]["diagnostic_followup"] == []
    assert snapshot == original


@pytest.fixture
def learner():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        profile = DBStudentProfile(student_id="synthetic-shop-owner", concept_mastery={})
        db.add(profile)
        db.commit()
        yield db, profile
    engine.dispose()


def test_new_chat_freezes_current_same_course_evidence_without_rewriting_prior_turn(learner, monkeypatch):
    from types import SimpleNamespace
    import app.chat_api as chats
    import app.profile_summary as summaries
    import course_catalog
    from app.database import DBCourse, DBKnowledgePoint, DBProfileSnapshot, DBUser

    db, profile = learner
    actor = DBUser(public_id='usr-chat-context', username=profile.student_id, hashed_password='test', role='student')
    course = DBCourse(id='course-chat-context', title='课程', version='v1', status='published',
                      visibility='public', manifest_version='v1')
    point = DBKnowledgePoint(id='kp-chat-context', domain_pack='ctx', code='C1', version='v1', title='训练与验证')
    old_body = {'course_id': course.id, 'concept_mastery': {point.id: .9}}
    snapshot = DBProfileSnapshot(id='ps-chat-context', owner_public_id=actor.public_id,
        legacy_student_id=profile.student_id, profile_version='v1', snapshot=old_body,
        content_hash='fixture', trace_id='trace-context')
    db.add_all([actor, course, point, snapshot]); db.commit()
    monkeypatch.setattr(chats, '_latest_profile_snapshot_for_course', lambda *_: snapshot)
    monkeypatch.setattr(course_catalog, 'course_is_selectable', lambda *_: True)
    graph = {'knowledge_graph': {'nodes': [{'id': point.id, 'mastery': .3, 'masteryBand': 'weak',
        'learningNeeds': [{'criterion_id': 'heldout', 'score': 0, 'basis': '将测试集用于选模', 'next_step': '区分验证与最终测试'}],
        'sourceEventIds': ['event-new'], 'evidence': [{'sourceType': 'assessment_attempt', 'sourceId': 'answer-new'}],
        'lastEvidenceAt': '2026-11-06'}]}}
    calls = []
    def current_graph(session, *, current_user, course_id):
        calls.append((session, current_user.public_id, course_id))
        return deepcopy(graph)
    monkeypatch.setattr(summaries, 'build_profile_summary', current_graph)
    args = (db, actor, SimpleNamespace(course_id=course.id),
            [{'course': {'id': course.id}, 'knowledgePoint': {'id': point.id}}], [], [], [])
    before = chats._context_snapshot(*args)
    assert before['profile_adaptation_plan']['point_mastery'] == .3
    assert before['profile_adaptation_plan']['difficulty_evidence']['kind'] == 'specific_learning_needs'
    assert '区分验证' in before['profile_adaptation_plan']['mastery_focus']
    graph['knowledge_graph']['nodes'][0].update(mastery=.88, masteryBand='mastered', learningNeeds=[])
    after = chats._context_snapshot(*args)
    assert after['profile_adaptation_plan']['point_mastery'] == .88
    assert after['profile_adaptation_plan']['learning_requirements']['diagnostic_followup'] == []
    assert before['profile_adaptation_plan']['point_mastery'] == .3
    assert before['context_snapshot_id'] != after['context_snapshot_id']
    assert snapshot.snapshot == old_body and profile.concept_mastery == {}
    assert calls == [(db, actor.public_id, course.id)] * 2


def test_concrete_background_is_not_replaced_by_a_generic_category(learner):
    db, profile = learner
    background = "我在肯尼亚经营小商店，没有上过大学，会用表格记账，想自己判断补货数量。"
    project_confirmed_fields(db, profile.student_id, "background", {
        "background_context": background, "learning_context": "工作/项目驱动",
    })
    db.expire_all()
    plan = build_profile_adaptation({}, profile=profile)
    assert background in str(profile.dimension_states["learning_context"])
    assert background in str(profile_prompt_context(plan))
    assert plan["point_mastery"] is None
    assert profile.concept_mastery == {}


def test_confirmed_preference_explanation_reaches_teaching_and_feedback_snapshot(learner):
    from app.profile_adaptation import confirmed_profile_fields
    db, profile = learner
    detail = "新公式先看完整示例，之后先独做，再按需查看提示。"
    project_confirmed_fields(db, profile.student_id, "preference", {"preference_context": detail})
    db.expire_all()
    context = profile_prompt_context(build_profile_adaptation({}, profile=profile))
    assert detail in context["explanation_style"]
    assert detail in context["registration_profile"]["interaction_preferences"]
    assert detail in confirmed_profile_fields(profile)["interaction_preferences"]
    assert profile.concept_mastery == {}


def test_legacy_confirmed_preference_is_read_without_rewriting_or_reviving_cleared_choice(learner):
    from copy import deepcopy
    from app.database import DBOnboardingSession
    from app.profile_adaptation import confirmed_profile_fields
    db, profile = learner
    detail = "概率从数量表开始，编程先给骨架，再独立修改。"
    report = {"preference": {"values": {"preference_context": detail}}}
    db.add(DBOnboardingSession(id="legacy-preference-session",owner_public_id="synthetic-owner",
        student_id=profile.student_id,confirmed_fields=report,status="confirmed"))
    db.commit()
    snapshot = {"self_report": deepcopy(report), "profile_projection": {"interaction_preferences": []}}
    original = deepcopy(snapshot)
    assert detail in build_profile_adaptation(snapshot)["explanation_style"]
    assert detail in build_profile_adaptation({}, profile=profile)["explanation_style"]
    assert detail in confirmed_profile_fields(profile)["interaction_preferences"]
    assert snapshot == original
    assert profile.interaction_preferences == []
    project_confirmed_fields(db, profile.student_id, "preference", {"interaction_preferences": []})
    assert detail not in build_profile_adaptation(snapshot, profile=profile)["explanation_style"]
    assert confirmed_profile_fields(profile)["interaction_preferences"] == []


@pytest.mark.parametrize("dimension", ["background", "goal", "foundation", "difficulty", "preference"])
def test_conditions_can_be_confirmed_in_any_conversation_round(dimension):
    for key, value in {
        "language_preference": "用英语解释，专业词同时标中文",
        "study_schedule": "每周二和周四晚上各30分钟",
        "available_tools": "只有安卓手机和纸笔，不能安装电脑软件",
    }.items():
        item = _model_field(dimension, {"key": key, "label": "学习条件", "value": value,
            "evidence": value, "confidence": 1.0})
        assert item is not None, (dimension, key)
        assert item["value"] == value


def test_later_round_conditions_reach_shared_teaching_plan_without_truncation(learner):
    db, profile = learner
    background = "社区工作者，服务刚到当地的家庭；" + "有多年访谈和组织活动的经历；" * 20 + "没有编程经历。"
    project_confirmed_fields(db, profile.student_id, "background", {"background_context": background})
    conditions = {"language_preference": "英语为主，关键术语附中文",
        "study_schedule": "每周二和周四各30分钟", "available_tools": "安卓手机、纸笔，无电脑"}
    project_confirmed_fields(db, profile.student_id, "preference", {
        "interaction_preferences": ["先尝试，再给反馈"], **conditions,
    })
    db.expire_all()
    plan = build_profile_adaptation({}, profile=profile)
    context = profile_prompt_context(plan)
    assert background in str(context)
    for value in conditions.values():
        assert value in str(context)
    assert confirmed_study_minutes({"profile_projection": {"dimension_states": profile.dimension_states}}) == 30
    assert plan["learning_requirements"]["available_tools"] == conditions["available_tools"]
    assert plan["learning_requirements"]["language_preference"] == conditions["language_preference"]


def test_schedule_update_keeps_background_language_and_tools(learner):
    db, profile = learner
    project_confirmed_fields(db, profile.student_id, "background", {
        "background_context": "社区摄影志愿者", "language_preference": "英语",
        "study_schedule": "每天30分钟", "available_tools": "手机相机，无电脑",
    })
    _apply_continuous_projection(profile, fields={"study_schedule": "每周二和周四各45分钟"},
        dimensions=[{"key": "learning_context", "value": "每周二和周四各45分钟",
                     "evidence": "现在改为周二和周四各45分钟", "confidence": 1.0}],
        attributions=[], answer="现在改为周二和周四各45分钟", turn_id="updated-schedule", course_context={})
    db.commit()
    db.expire_all()
    plan = build_profile_adaptation({}, profile=profile)
    for value in ("社区摄影志愿者", "英语", "手机相机，无电脑", "45分钟"):
        assert value in str(profile_prompt_context(plan))
    assert "每天30分钟" not in plan["registration_profile"]["learning_context"]
    assert confirmed_study_minutes({"profile_projection": {"dimension_states": profile.dimension_states}}) == 45
    assert profile.concept_mastery == {}


def test_free_time_or_job_experience_does_not_invent_cognitive_scores():
    for dimension, answer in [("foundation", "我很忙，通勤时只有20分钟"),
                              ("foundation", "我有经验，熟练用表格记账"),
                              ("preference", "每天只学20分钟")]:
        fields, _ = _derived_signal_fields(dimension, answer)
        assert not {"cognitive_load", "focus_level"}.intersection(item["key"] for item in fields)


def test_foundation_details_do_not_drop_unlearned_prerequisites(learner):
    db, profile = learner
    project_confirmed_fields(db, profile.student_id, "foundation", {
        "knowledge_base": ["加减法", "百分比", "销售表"],
        "foundation_context": "会加减法、百分比和销售表；从未学过概率、正式统计学或编程。",
    })
    db.expire_all()
    plan = build_profile_adaptation({}, profile=profile)
    assert "从未学过概率、正式统计学或编程" in plan["registration_profile"]["knowledge_base"]
    assert "['" not in profile.knowledge_base
    assert profile.concept_mastery == {}


def test_english_schedule_uses_confirmed_time_not_unrelated_background_durations(learner):
    db, profile = learner
    project_confirmed_fields(db, profile.student_id, "background", {
        "background_context": "曾教过60分钟一节的课程，现在没有电脑。",
        "study_schedule": "Tuesday and Thursday evenings, 30 minutes each",
        "available_tools": "cannot install desktop software",
    })
    snapshot = {"profile_projection": {"dimension_states": profile.dimension_states}}
    assert confirmed_study_days(snapshot) == (1, 3)
    assert confirmed_study_minutes(snapshot) == 30


@pytest.mark.parametrize("schedule", [
    "从现在起，周六上午可学习45分钟，替代原来的周二、周四晚上；学习目标和设备保持不变。",
    "以前周二学习30分钟，现在改为周六上午45分钟",
    "From now on Saturday mornings for 45 minutes, instead of Tuesday and Thursday for 30 minutes",
])
def test_explicit_schedule_replacement_does_not_keep_old_days_or_minutes(schedule):
    snapshot = {"dimension_states": {"learning_context": {"confirmed_fields": {"study_schedule": schedule}}}}
    assert confirmed_study_days(snapshot) == (5,)
    assert confirmed_study_minutes(snapshot) == 45


def test_path_uses_current_confirmed_schedule_when_old_snapshot_is_retained():
    snapshot = {
        "profile_projection": {"dimension_states": {"learning_context": {
            "confirmed_fields": {"study_schedule": "周二和周四各30分钟"},
        }}},
        "learning_adaptation": {"learning_requirements": {"study_schedule": "周六上午45分钟"}},
    }
    assert confirmed_study_days(snapshot) == (5,)
    assert confirmed_study_minutes(snapshot) == 45


def test_experience_in_one_subject_does_not_set_another_subjects_difficulty():
    snapshot = {"knowledge_base": "熟练使用Python处理表格；摄影零基础；尚未学过ISO和快门。"}
    python = build_profile_adaptation(snapshot, knowledge_point={"id": "py", "title": "Python"})
    photo = build_profile_adaptation(snapshot, knowledge_point={"id": "photo", "title": "摄影"})
    inventory = build_profile_adaptation(snapshot, knowledge_point={"id": "stock", "title": "安全库存"})
    assert python["difficulty_band"] == "transfer"
    assert photo["difficulty_band"] == "foundation"
    assert inventory["difficulty_band"] == "scaffolded"
    assert all(plan["point_mastery"] is None for plan in (python, photo, inventory))
    assert "Python" in inventory["registration_profile"]["knowledge_base"]


def test_negated_skill_is_not_read_as_advanced():
    plan = build_profile_adaptation({"knowledge_base": "并不熟练使用Python，需要逐步查语法。"},
                                    knowledge_point={"id": "py", "title": "Python"})
    assert plan["difficulty_band"] != "transfer"
    assert plan["point_mastery"] is None


@pytest.mark.parametrize("motivation,goal", [
    ("非职业、非考证导向，面向社区活动的实际拍摄与作品集完成", "用手机拍清社区活动，整理十张照片"),
    ("经营自用，不以软件工程项目或考试证书为目标", "为十个商品完成可执行补货表"),
])
def test_specific_motivation_does_not_turn_negation_into_career_or_software_tasks(motivation,goal):
    plan=build_profile_adaptation({'motivation_type':motivation,'learning_goals':[goal], 'target_course':'自主学习'})
    assert goal in plan['example_context']
    assert '面试追问' not in plan['example_context']
    assert '上线约束' not in plan['example_context']


def test_natural_topic_difficulty_provides_support_without_emotional_score():
    snapshot = {"weak_points": ["我在公式推导和概念区别上卡住", "对焦现在已经解决"]}
    formula = build_profile_adaptation(snapshot, knowledge_point={"title": "公式推导"})
    photo = build_profile_adaptation(snapshot, knowledge_point={"title": "对焦"})
    unrelated = build_profile_adaptation(snapshot, knowledge_point={"title": "安全库存"})
    assert formula["difficulty_band"] == "foundation"
    assert formula["scaffolding_level"] == "high"
    assert photo["difficulty_band"] == unrelated["difficulty_band"] == "scaffolded"
    assert formula["point_mastery"] is None


def test_confirmed_qualitative_states_reach_teaching_and_survive_other_updates(learner):
    db, profile = learner
    statement = "长题会紧张，短题很轻松，希望先分段尝试；不是所有学习都焦虑。"
    project_confirmed_fields(db, profile.student_id, "difficulty", {
        "weak_points": ["长题分步理解"], "affect_context": statement,
    })
    db.expire_all()
    plan = build_profile_adaptation({}, profile=profile)
    assert statement in str(profile_prompt_context(plan))
    assert profile.frustration_index == 0
    assert profile.concept_mastery == {}
    _apply_continuous_projection(profile, fields={"cognitive_context": "两步比较能跟上，多变量比较需要先画表"},
        dimensions=[], attributions=[], answer="想先画表", turn_id="qualitative", course_context={})
    db.commit(); db.expire_all()
    assert profile.dimension_states["affect_resilience"]["summary"] == statement
    assert "多变量" in build_profile_adaptation({}, profile=profile)["dimensions"]["cognitive_processing"]


def test_new_qualitative_confirmation_supersedes_old_inferred_scores_without_rewriting_them(learner):
    from app.crud import load_student_profile
    from profile_api import _build_dimension_analysis
    db,profile=learner
    profile.frustration_index=.72
    profile.cognitive_load=.68
    profile.dimension_states={'affect_resilience':{'score':.28,'evidence_count':1,'evidence_fragments':['旧规则推断']}}
    db.commit()
    project_confirmed_fields(db,profile.student_id,'difficulty',{
        'affect_context':'我现在并不焦虑，遇到陌生概念也愿意尝试',
        'cognitive_context':'短题可以自己比较，只需要核对新术语',
    })
    db.expire_all()
    assert profile.frustration_index==.72 and profile.cognitive_load==.68
    plan=build_profile_adaptation({},profile=profile,knowledge_point={'title':'新的主题'})
    assert plan['scaffolding_level']=='medium'
    state=load_student_profile(db,profile.student_id).dimension_states['affect_resilience']
    shown=_build_dimension_analysis('affect_resilience',state)
    assert shown['score'] is None and '并不焦虑' in shown['diagnosis']
    _apply_continuous_projection(profile,fields={'frustration_index':.8},dimensions=[],attributions=[],
        answer='今天焦虑评分0.8',turn_id='explicit-state',course_context={})
    assert build_profile_adaptation({},profile=profile)['scaffolding_level']=='high'


def test_confirmed_dimension_only_self_report_replaces_old_inferred_teaching_signal(learner):
    from app.crud import load_student_profile
    from profile_api import _build_dimension_analysis
    db, profile = learner
    profile.frustration_index = .72
    profile.cognitive_load = .68
    profile.dimension_states = {'affect_resilience': {'score': .28}}
    dimensions = [
        {'key': 'affect_resilience', 'value': '对拍照不紧张，愿意自己试',
         'evidence': '我现在对拍照并不紧张，愿意自己试', 'confidence': .95, 'score': None},
        {'key': 'cognitive_processing', 'value': '两步比较能跟上，多条件比较希望先画表',
         'evidence': '短的两步比较能跟上，多条件同时比较时希望先画表', 'confidence': .93, 'score': None},
    ]
    _apply_continuous_projection(profile, fields={}, dimensions=dimensions, attributions=[],
        answer='我不紧张，想先画表', turn_id='dimension-confirmation', course_context={})
    db.commit(); db.expire_all()
    assert profile.frustration_index == .72 and profile.cognitive_load == .68
    assert profile.concept_mastery == {}
    plan = build_profile_adaptation({}, profile=profile, knowledge_point={'title': '新的主题'})
    assert plan['scaffolding_level'] == 'medium'
    assert '不紧张' in str(profile_prompt_context(plan))
    state = load_student_profile(db, profile.student_id).dimension_states['affect_resilience']
    shown = _build_dimension_analysis('affect_resilience', state)
    assert shown['score'] is None and '不紧张' in shown['diagnosis']

    from app.profile_adaptation import current_learning_state
    view = current_learning_state(load_student_profile(db, profile.student_id))
    assert view['frustration_index']['value'] is None
    assert view['cognitive_load']['value'] is None
    assert view['focus_level']['value'] is None
    assert '不紧张' in view['frustration_index']['description']
    assert '先画表' in view['cognitive_load']['description']
    from app.profile_onboarding import _profile_prompt_projection
    next_conversation = _profile_prompt_projection(profile)
    assert next_conversation['frustration_index'] is None
    assert next_conversation['cognitive_load'] is None
    assert '不紧张' in str(next_conversation['dimensions'])


def test_learning_feedback_keeps_current_confirmed_conditions_after_baseline(learner,monkeypatch):
    from copy import deepcopy
    from types import SimpleNamespace
    from app.database import DBLearningEvent
    from app import learning_aggregation
    db,profile=learner
    project_confirmed_fields(db,profile.student_id,'preference',{
        'language_preference':'Plain English','available_tools':'Android phone and paper',
        'study_schedule':'周二晚上30分钟','cognitive_context':'两步比较能跟上，长题先画表',
    })
    baseline=SimpleNamespace(snapshot={'focus_level':.72,'cognitive_load':.45,'frustration_index':0,
                                      'dimension_states':deepcopy(profile.dimension_states)})
    _apply_continuous_projection(profile,fields={'study_schedule':'改为周六上午45分钟'},dimensions=[],attributions=[],
        answer='改为周六上午45分钟',turn_id='new-schedule',course_context={})
    event=DBLearningEvent(id='test-feedback',event_type='quiz_answered',object_type='knowledge_point',object_id='new-concept',
                          payload={'score':.8},context_ref={})
    monkeypatch.setattr(learning_aggregation,'_profile_feedback_events',lambda *_:[event])
    learning_aggregation._project_behavior_profile(db,event=event,profile=profile,baseline=baseline,current_mastery={})
    db.commit();db.expire_all()
    plan=build_profile_adaptation({},profile=profile)
    requirements=plan['learning_requirements']
    assert requirements['language_preference']=='Plain English'
    assert requirements['available_tools']=='Android phone and paper'
    assert requirements['study_schedule']=='改为周六上午45分钟'
    assert '两步比较能跟上' in str(profile.dimension_states)


def test_legacy_profile_save_keeps_confirmed_detail_fields(learner):
    from app.crud import load_student_profile,save_student_profile
    db,profile=learner
    project_confirmed_fields(db,profile.student_id,'preference',{
        'language_preference':'Plain English','available_tools':'Android phone and paper',
        'study_schedule':'周六上午45分钟',
    })
    loaded=load_student_profile(db,profile.student_id)
    loaded.dashboard_report='依据本次学习形成的报告'
    save_student_profile(db,loaded)
    db.expire_all()
    requirements=build_profile_adaptation({},profile=profile)['learning_requirements']
    assert requirements['language_preference']=='Plain English'
    assert requirements['available_tools']=='Android phone and paper'
    assert requirements['study_schedule']=='周六上午45分钟'


@pytest.mark.parametrize("score", [None, 0.0, .8])
def test_profile_roundtrip_distinguishes_description_from_measured_zero(learner, score):
    from app.crud import load_student_profile, save_student_profile
    from profile_api import _build_dimension_analysis
    db, profile = learner
    state = {"summary": "对焦与运动模糊还需要练习", "evidence_count": 1,
             "evidence_fragments": ["学生确认的描述"]}
    if score is not None:
        state.update(score=score, status="练习结果", evidence_fragments=["实际作答结果"])
    profile.dimension_states = {"knowledge_mastery": state}
    db.commit()
    for _ in range(2):
        loaded = load_student_profile(db, profile.student_id)
        shown = _build_dimension_analysis("knowledge_mastery", loaded.dimension_states["knowledge_mastery"])
        assert shown["score"] == score
        if score is None:
            assert "还需要练习" in shown["diagnosis"]
        save_student_profile(db, loaded)
        db.expire_all()


def test_actual_subject_feedback_can_replace_qualitative_display_without_erasing_self_report(learner, monkeypatch):
    from copy import deepcopy
    from types import SimpleNamespace
    from app import learning_aggregation
    from app.database import DBLearningEvent
    from app.crud import load_student_profile
    from profile_api import _build_dimension_analysis
    db, profile = learner
    profile.dimension_states = {"knowledge_mastery": {
        "summary": "需要练习对焦", "self_report": "需要练习对焦", "qualitative": True,
    }}
    baseline = SimpleNamespace(snapshot={"dimension_states": deepcopy(profile.dimension_states)})
    event = DBLearningEvent(id="actual-subject-feedback", event_type="quiz_answered",
        object_type="knowledge_point", object_id="focus", payload={"score": .8}, context_ref={})
    monkeypatch.setattr(learning_aggregation, "_profile_feedback_events", lambda *_: [event])
    learning_aggregation._project_behavior_profile(db, event=event, profile=profile,
        baseline=baseline, current_mastery={"focus": .8})
    db.commit()
    loaded = load_student_profile(db, profile.student_id)
    state = loaded.dimension_states["knowledge_mastery"]
    assert _build_dimension_analysis("knowledge_mastery", state)["score"] == .8
    assert state.self_report == "需要练习对焦"


@pytest.mark.parametrize("original_score,later_observation,expected", [(None, False, None), (0.0, False, 0.0), (None, True, 0.0)])
def test_legacy_narrative_default_zero_is_recovered_only_with_exact_original_evidence(learner, original_score, later_observation, expected):
    from datetime import datetime
    from app.database import DBOnboardingSession, DBOnboardingTurn
    from app.crud import load_student_profile
    from profile_api import _build_dimension_analysis
    db, profile = learner
    state = {"summary": "偏好先画表", "last_updated": "2026-11-04T10:00:00", "source_turn_id": "confirmed-words",
             "evidence_count": 1, "evidence_fragments": ["喜欢先画表"]}
    db.add(DBOnboardingSession(id="verbal-session", owner_public_id="synthetic-owner", student_id=profile.student_id))
    db.add(DBOnboardingTurn(id="verbal-turn", session_id="verbal-session", turn_id="confirmed-words",
        question_dimension="continuous", user_answer="喜欢先画表", status="confirmed",
        confirmed_at=datetime(2026, 11, 4, 10, 0, 1), confirmed_fields={"dimensions": [
            {"key": "learning_strategy", "value": "偏好先画表", "score": original_score}]}))
    state.update(score=0.0, qualitative=False)
    if later_observation:
        state["last_updated"] = "2026-11-04T11:00:00"
    profile.dimension_states = {"learning_strategy": state}
    db.commit()
    shown = _build_dimension_analysis("learning_strategy", load_student_profile(db, profile.student_id).dimension_states["learning_strategy"])
    assert shown["score"] == expected
    teaching = build_profile_adaptation({}, profile=profile)["dimensions"]["learning_strategy"]
    assert ("0%" in teaching) is (expected == 0.0)

    # New resource/path requests read the saved snapshot without rewriting it
    # or borrowing a later learner's current profile.
    from copy import deepcopy
    from types import SimpleNamespace
    from app.profile_adaptation import complete_learning_snapshot
    original = {"profile_projection": {"dimension_states": deepcopy(profile.dimension_states)}}
    snapshot = SimpleNamespace(snapshot=original, owner_public_id="synthetic-owner")
    context = complete_learning_snapshot(db, snapshot)
    teaching = build_profile_adaptation(context)["dimensions"]["learning_strategy"]
    assert ("0%" in teaching) is (expected == 0.0)
    assert original["profile_projection"]["dimension_states"]["learning_strategy"]["score"] == 0.0
    assert original["profile_projection"]["dimension_states"]["learning_strategy"]["qualitative"] is False


def test_later_verbal_update_does_not_carry_default_zero_into_report(learner):
    from app.crud import load_student_profile, save_student_profile
    from profile_api import _build_dimension_analysis
    db, profile = learner
    profile.dimension_states = {"learning_strategy": {"score": 0.0, "qualitative": False}}
    _apply_continuous_projection(profile, fields={}, dimensions=[{
        "key": "learning_strategy", "value": "多条件先画表", "evidence": "喜欢先画表",
        "score": None, "confidence": .9,
    }], attributions=[], answer="喜欢先画表", turn_id="new-description", course_context={})
    db.commit()
    loaded = load_student_profile(db, profile.student_id)
    save_student_profile(db, loaded)
    db.expire_all()
    shown = _build_dimension_analysis("learning_strategy", load_student_profile(db, profile.student_id).dimension_states["learning_strategy"])
    assert shown["score"] is None and shown["diagnosis"] == "多条件先画表"


@pytest.mark.parametrize("answer", [
    "我分不清是对焦还是人动造成的，想通过两张照片对比。",
    "我不会概率，但并不焦虑，愿意慢慢学。",
    "公式对我并不难，我现在只是想学新的应用。",
])
def test_knowledge_gap_does_not_invent_emotion_or_confusion_scores(answer):
    from app.profile_onboarding import _derived_signal_fields
    fields, _ = _derived_signal_fields("difficulty", answer)
    assert not {"frustration_index", "cognitive_load", "misconception_patterns"}.intersection(
        field["key"] for field in fields
    )


def test_model_emotion_estimate_stays_qualitative_in_initial_and_continuous_profile():
    from app.profile_onboarding import _parse_model_candidates, _parse_continuous_model_candidates
    answer = "我一看到长题就焦虑，但做短题很轻松，想先分段练习。"
    raw = json.dumps({"understanding": answer, "fields": [
        {"key": "weak_points", "label": "学习卡点", "value": ["长题分步理解"], "evidence": answer, "confidence": .9},
        {"key": "frustration_index", "label": "受挫感", "value": .72, "evidence": answer, "confidence": .9},
        {"key": "cognitive_load", "label": "认知负荷", "value": .68, "evidence": answer, "confidence": .9},
    ], "dimensions": [{"key": "affect_resilience", "value": answer, "evidence": answer, "score": .72, "confidence": .9}]}, ensure_ascii=False)
    for parsed in (_parse_model_candidates(raw, "difficulty", answer), _parse_continuous_model_candidates(raw, answer)):
        fields = {field["key"]: field["value"] for field in parsed["fields"]}
        assert "frustration_index" not in fields and "cognitive_load" not in fields
        assert fields["affect_context"] == answer
        assert fields["cognitive_context"] == answer
        assert all(item.get("score") is None for item in parsed.get("dimensions", []))


def test_confirmed_conversation_continues_its_actual_followup_after_reload():
    from types import SimpleNamespace
    from app.profile_onboarding import _continuous_next_question_from_turns
    question = "上次那张模糊的照片，拍摄时人物正在走动吗？"
    turns = [SimpleNamespace(status="confirmed", extracted_candidates={"followUpQuestion": question}, confirmed_fields={})]
    assert _continuous_next_question_from_turns(turns) == question

