from __future__ import annotations

import asyncio
from pathlib import Path
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

import app.m5_api as m5_api
from app.competition_demo_seed import seed_competition_demo
from app.database import (
    DBAssessmentAbilityState,
    DBAssessmentAttempt,
    DBAssessmentGradingResult,
    Base,
    DBAssessmentQuestion,
    DBAssessmentQuestionVersion,
    DBCourse,
    DBCourseMembership,
    DBDiagnosticBlueprint,
    DBDiagnosticSession,
    DBDiagnosticReport,
    DBLearningEvent,
    DBLearningPath,
    DBProfileSnapshot,
    DBReviewPlan,
    DBUser,
)
from app.m5_assessment_core import AttemptInput
from app.profile_summary import build_profile_summary


ROOT = Path(__file__).resolve().parents[1]
COURSE_ID = "demo-course-rag-trust-v1"


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def _run(awaitable):
    return asyncio.run(awaitable)


@pytest.mark.parametrize("score", [0.0, 1.0])
@pytest.mark.parametrize("mode", ["diagnostic", "formal"])
def test_profile_graph_uses_completed_subjective_diagnostic_grade_without_mutating_attempt(score, mode):
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        before = build_profile_summary(session, current_user=learner, course_id=COURSE_ID)
        point = next(node for node in before["knowledge_graph"]["nodes"] if node["evidenceCount"] == 0)
        question = DBAssessmentQuestion(id="subjective-graph-q", owner_public_id=learner.public_id,
            course_id=COURSE_ID, question_type="short_answer", origin="manual", status="approved")
        session.add(question); session.flush()
        version = DBAssessmentQuestionVersion(id="subjective-graph-qv", question_id=question.id,
            version_number=1, prompt="说明本节概念的适用条件。", answer_key={"reference_answer": "测试参考答案"},
            scoring_rule={"type": "rubric"}, primary_knowledge_point_id=point["id"],
            content_hash="synthetic-subjective", created_by_public_id=learner.public_id)
        session.add(version); session.flush()
        attempt = DBAssessmentAttempt(id="subjective-graph-attempt", owner_public_id=learner.public_id,
            course_id=COURSE_ID, question_version_id=version.id, idempotency_key="synthetic-subjective",
            mode=mode, answer={"text": "测试作答"}, grading_status="pending", score=None)
        session.add(attempt); session.flush()
        session.add(DBAssessmentGradingResult(attempt_id=attempt.id, owner_public_id=learner.public_id,
            grader_type="human" if mode == "formal" else "ai", status="completed", score=score, correct=score == 1,
            content_hash="synthetic-grade", trace_id="synthetic-grade"))
        session.add(DBDiagnosticBlueprint(id="synthetic-graph-blueprint", owner_public_id=learner.public_id,
            course_id=COURSE_ID, idempotency_key="synthetic-graph", question_version_ids=[version.id],
            question_count=1, estimated_minutes=1, content_hash="synthetic-graph"))
        session.flush()
        session.add(DBDiagnosticSession(id="synthetic-graph-session", owner_public_id=learner.public_id,
            blueprint_id="synthetic-graph-blueprint", status="submitted", current_question_version_id=version.id))
        session.flush()
        snapshot = session.query(DBProfileSnapshot).filter_by(owner_public_id=learner.public_id).first()
        session.add(DBDiagnosticReport(session_id="synthetic-graph-session", owner_public_id=learner.public_id,
            course_id=COURSE_ID, idempotency_key="synthetic-graph", attempt_ids=[attempt.id],
            profile_snapshot_id=snapshot.id, content_hash="synthetic-graph"))
        session.commit()
        after = build_profile_summary(session, current_user=learner, course_id=COURSE_ID)
        node = next(node for node in after["knowledge_graph"]["nodes"] if node["id"] == point["id"])
        assert node["mastery"] == score
        assert node["evidenceCount"] == 1
        expected_route = (f"/workspace/assessment?course_id={COURSE_ID}&blueprint_id=synthetic-graph-blueprint"
                          if mode == "diagnostic" else f"/workspace/assessment/exams?course_id={COURSE_ID}")
        assert node["evidence"][0]["source"]["route"] == expected_route
        assert "尚无" not in node["judgement"]
        assert attempt.score is None and attempt.grading_status == "pending"
    finally:
        session.close(); engine.dispose()


@pytest.mark.parametrize('score,band', [(0.0, 'weak'), (0.67, 'developing')])
def test_graph_uses_current_learning_projection_without_changing_records(score, band):
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username='lzz').one()
        before = build_profile_summary(session, current_user=learner, course_id=COURSE_ID)
        point = next(node for node in before['knowledge_graph']['nodes'] if node['mastery'] is not None)
        snapshot = DBProfileSnapshot(owner_public_id=learner.public_id,
            legacy_student_id=learner.username, profile_version='synthetic-regression',
            snapshot={'kind': 'learning_aggregation_projection', 'course_id': COURSE_ID,
                      'concept_mastery': {point['name']: score}},
            content_hash='synthetic-regression', trace_id='synthetic-regression',
            created_at=datetime.now() + timedelta(seconds=1))
        session.add(snapshot); session.commit()
        after = build_profile_summary(session, current_user=learner, course_id=COURSE_ID)
        projected = next(node for node in after['knowledge_graph']['nodes'] if node['id'] == point['id'])
        assert projected['mastery'] == score
        assert projected['masteryBand'] == band
        assert snapshot.snapshot['concept_mastery'][point['name']] == score
        assert all(item['observedAt'].endswith('+00:00') for item in projected['evidence'] if item['observedAt'])
    finally:
        session.close(); engine.dispose()


def test_diagnostic_rubric_gap_is_not_a_second_score_or_a_conflict_and_reaches_path():
    from copy import deepcopy
    from app.path_draft import _path_learning_snapshot
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username='lzz').one()
        initial = build_profile_summary(session, current_user=learner, course_id=COURSE_ID)
        point = next(node for node in initial['knowledge_graph']['nodes'] if node['evidenceCount'] == 0)
        question = DBAssessmentQuestion(id='gap-question', owner_public_id=learner.public_id,
            course_id=COURSE_ID, question_type='short_answer', origin='manual', status='approved')
        session.add(question); session.flush()
        version = DBAssessmentQuestionVersion(id='gap-version', question_id=question.id,
            version_number=1, prompt='比较两种误差并给出改进方向。',
            primary_knowledge_point_id=point['id'], content_hash='gap-version')
        session.add(version); session.flush()
        now = datetime.now()
        attempt = DBAssessmentAttempt(id='gap-attempt', owner_public_id=learner.public_id,
            course_id=COURSE_ID, question_version_id=version.id, mode='diagnostic',
            idempotency_key='gap-attempt', answer={'text':'计算正确，但把继续降低训练损失当作改进。'},
            grading_status='graded', score=0.85, submitted_at=now)
        session.add(attempt); session.flush()
        grade = DBAssessmentGradingResult(attempt_id=attempt.id, owner_public_id=learner.public_id,
            grader_type='ai', status='completed', score=0.85, correct=True,
            criterion_results=[{'criterion_id':'action', 'score':0.0,
                'justification':'改进方向没有处理过拟合。', 'improvement':'比较验证误差再决定调整。'}],
            content_hash='gap-grade', trace_id='gap-grade')
        session.add(grade)
        payload = {'kind':'diagnostic_evidence_snapshot', 'course_id':COURSE_ID,
            'weak_knowledge_point_ids':[point['id']],
            'mastery_by_knowledge_point':{point['id']:{'score':0.85,'attempt_ids':[attempt.id]}},
            'diagnostic_evidence':{'attempt_ids':[attempt.id], 'created_from_submitted_answers':True}}
        snapshot = DBProfileSnapshot(owner_public_id=learner.public_id, legacy_student_id=learner.username,
            profile_version='gap-snapshot', snapshot=payload, content_hash='unchanged',
            trace_id='gap-snapshot', created_at=now+timedelta(seconds=1))
        session.add(snapshot); session.commit()
        original = deepcopy(snapshot.snapshot)
        summary = build_profile_summary(session,current_user=learner,course_id=COURSE_ID)
        node = next(n for n in summary['knowledge_graph']['nodes'] if n['id']==point['id'])
        assert node['mastery'] == 0.85 and node['masteryBand'] == 'developing'
        assert node['evidenceCount'] == 1, 'Snapshot derived from this answer is not independent evidence'
        assert node['learningNeeds'][0]['criterion_id'] == 'action'
        assert '过拟合' in node['judgement'] and '验证误差' in node['nextAction']['reason']
        path = _path_learning_snapshot(session,user=learner,course_id=COURSE_ID,profile=snapshot,use_current=True)
        assert point['id'] in path['weak_knowledge_point_ids']
        assert point['id'] not in path['mastered_knowledge_point_ids']
        assert path['mastery_by_knowledge_point'][point['id']]['learning_needs']
        assert snapshot.snapshot == original and attempt.score == 0.85

        # Binary marking may coexist with a detailed rubric. The graph should
        # explain the actual gap, not merely say that an answer was compared.
        grade.criterion_results = [
            {'criterion_id':'answer_correctness','score':0.0,
             'justification':'已与正确答案比较。','improvement':'复习错题。'},
            *grade.criterion_results,
        ]
        session.commit()
        ranked=build_profile_summary(session,current_user=learner,course_id=COURSE_ID)
        ranked_node=next(n for n in ranked['knowledge_graph']['nodes'] if n['id']==point['id'])
        assert ranked_node['learningNeeds'][0]['criterion_id']=='action'
        assert '过拟合' in ranked_node['judgement'] and '验证误差' in ranked_node['nextAction']['reason']

        # A different easy question on the same concept does not erase the
        # specific misconception shown in the first answer.
        another = DBAssessmentQuestionVersion(id='gap-another-version', question_id=question.id,
            version_number=2, prompt='读出表中的训练误差。',
            primary_knowledge_point_id=point['id'], content_hash='gap-another-version')
        session.add(another); session.flush()
        session.add(DBAssessmentAttempt(id='gap-other-answer', owner_public_id=learner.public_id,
            course_id=COURSE_ID, question_version_id=another.id, mode='formal',
            idempotency_key='gap-other-answer', answer={'text':'0.1'}, grading_status='graded', score=1.0,
            submitted_at=now+timedelta(minutes=5)))
        session.commit()
        with_other=build_profile_summary(session,current_user=learner,course_id=COURSE_ID)
        with_other_node=next(n for n in with_other['knowledge_graph']['nodes'] if n['id']==point['id'])
        assert with_other_node['mastery']==0.925 and with_other_node['masteryBand']=='developing'
        assert with_other_node['learningNeeds'][0]['criterion_id']=='action'

        # An unrelated accepted learning event used to clear every rubric gap.
        event = DBLearningEvent(id='gap-later-code', owner_public_id=learner.public_id,
            course_id=COURSE_ID, event_type='code_tests_passed', object_type='knowledge_point',
            object_id=point['id'], source='backend', idempotency_key='gap-later-code', trace_id='gap-later-code',
            payload={'knowledge_point_id':point['id']}, evidence_status='accepted',
            mastery_eligible=True, evidence_strength=1.0, occurred_at=now+timedelta(minutes=6))
        session.add(event); session.commit()
        after_code=build_profile_summary(session,current_user=learner,course_id=COURSE_ID)
        after_code_node=next(n for n in after_code['knowledge_graph']['nodes'] if n['id']==point['id'])
        assert after_code_node['learningNeeds'][0]['criterion_id']=='action'
        assert after_code_node['learningNeeds'][0]['attempt_id']==attempt.id
        current_path=_path_learning_snapshot(session,user=learner,course_id=COURSE_ID,
                                            profile=snapshot,use_current=True)
        assert current_path['mastery_by_knowledge_point'][point['id']]['learning_needs']
        session.delete(event); session.commit()

        # Hints and a high total without a matching criterion do not resolve
        # the missing reasoning. A later assessment can still resolve it.
        partial = DBAssessmentAttempt(id='gap-partial', owner_public_id=learner.public_id,
            course_id=COURSE_ID,question_version_id=version.id,mode='formal',idempotency_key='gap-partial',
            answer={'text':'借助提示完成。','used_hints':True},grading_status='graded',score=1.0,
            submitted_at=now+timedelta(minutes=7))
        session.add(partial); session.flush()
        partial_grade=DBAssessmentGradingResult(attempt_id=partial.id,owner_public_id=learner.public_id,
            grader_type='ai',status='completed',score=1.0,correct=True,
            criterion_results=[{'criterion_id':'action','score':1.0,'justification':'正确。'}],
            content_hash='gap-partial-grade',trace_id='gap-partial-grade')
        session.add(partial_grade); session.commit()
        for hinted in (True, False):
            if not hinted:
                partial.answer={'text':'计算完成。'}
                partial_grade.criterion_results=[{'criterion_id':'calculation','score':1.0,'justification':'计算正确。'}]
                session.commit()
            actual=build_profile_summary(session,current_user=learner,course_id=COURSE_ID)
            actual_node=next(n for n in actual['knowledge_graph']['nodes'] if n['id']==point['id'])
            assert actual_node['learningNeeds'][0]['criterion_id']=='action'
        session.delete(partial_grade); session.delete(partial); session.commit()

        # A later independent answer to the same task can establish progress;
        # the old snapshot must not create a permanent conflict.
        later = DBAssessmentAttempt(id='gap-resolved', owner_public_id=learner.public_id,
            course_id=COURSE_ID,question_version_id=version.id,mode='formal',idempotency_key='gap-resolved',
            answer={'text':'比较验证表现，尝试降低复杂度并解释差异。'},grading_status='graded',score=1.0,
            submitted_at=now+timedelta(minutes=10))
        session.add(later);session.flush()
        session.add(DBAssessmentGradingResult(attempt_id=later.id,owner_public_id=learner.public_id,
            grader_type='ai',status='completed',score=1.0,correct=True,
            criterion_results=[{'criterion_id':'action','score':1.0,'justification':'正确。','improvement':''}],
            content_hash='gap-resolved-grade',trace_id='gap-resolved-grade'))
        session.commit()
        updated=build_profile_summary(session,current_user=learner,course_id=COURSE_ID)
        node=next(n for n in updated['knowledge_graph']['nodes'] if n['id']==point['id'])
        assert node['mastery']==0.95 and node['masteryBand']=='mastered'
        assert not node['learningNeeds'] and snapshot.snapshot==original
    finally:
        session.close();engine.dispose()


@pytest.mark.parametrize('label',['mastered_knowledge_point_ids','weak_knowledge_point_ids'])
def test_qualitative_snapshot_label_does_not_invent_numeric_mastery(label):
    engine,session=_session()
    try:
        seed_competition_demo(session)
        learner=session.query(DBUser).filter_by(username='lzz').one()
        initial=build_profile_summary(session,current_user=learner,course_id=COURSE_ID)
        point=next(n for n in initial['knowledge_graph']['nodes'] if n['evidenceCount']==0)
        snapshot=DBProfileSnapshot(owner_public_id=learner.public_id,legacy_student_id=learner.username,
            profile_version='qualitative-only',snapshot={'course_id':COURSE_ID,label:[point['id']]},
            content_hash='qualitative-only',trace_id='qualitative-only',created_at=datetime.now()+timedelta(seconds=1))
        session.add(snapshot);session.commit()
        result=build_profile_summary(session,current_user=learner,course_id=COURSE_ID)
        node=next(n for n in result['knowledge_graph']['nodes'] if n['id']==point['id'])
        assert node['mastery'] is None and node['masteryBand']=='unknown'
        assert node['evidenceCount']==1, 'Keep the actual qualitative record available'
    finally:
        session.close();engine.dispose()


def test_three_profile_summary_uses_existing_evidence_and_changes_after_diagnostic(monkeypatch):
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()

        async def isolated_run_db_op(operation, *args, **kwargs):
            return operation(session, *args, **kwargs)

        monkeypatch.setattr(m5_api, "run_db_op", isolated_run_db_op)
        before = _run(m5_api.get_profile_summary(course_id=COURSE_ID, current_user=learner))
        assert before["schema_version"] == "r3.profile-summary.v1"
        assert [item["key"] for item in before["sections"]] == ["skill", "cognitive", "behavior"]
        assert before["summary"]["diagnostic_response_count"] == 0
        assert before["summary"]["diagnostic_attempt_count"] == 2
        assert before["summary"]["next_action"]["route"].startswith("/workspace")
        assert "课程总评" in before["boundary"]
        graph = before["knowledge_graph"]
        assert graph["schemaVersion"] == "f4.profile-knowledge-graph.v1"
        assert graph["summary"]["nodeCount"] == 12
        # Only the two saved diagnostic answers supply measured mastery;
        # the other demo labels must not become invented numeric scores.
        measured = {node["id"] for node in graph["nodes"] if node["mastery"] is not None}
        assert measured == {"demo-kp-07", "demo-kp-08"}
        assert graph["summary"]["evidenceNodeCount"] == 2
        assert graph["summary"]["unknownNodeCount"] >= 1
        assert {item["relation"] for item in graph["edges"]} == {"prerequisite"}
        assert any(item["source"] == "demo-kp-05" and item["target"] == "demo-kp-07" for item in graph["edges"])
        for node in graph["nodes"]:
            assert {
                "masteryBand", "evidenceCount", "lastEvidenceAt",
                "sourceEventIds", "confidence", "nextAction",
            } <= node.keys()
            assert node["masteryBand"] in {"mastered", "developing", "weak", "unknown", "conflict"}
            assert 0 <= node["confidence"] <= 1
        unknown = next(item for item in graph["nodes"] if item["evidenceCount"] == 0)
        assert unknown["mastery"] is None
        assert unknown["evidenceCount"] == 0
        assert unknown["nextAction"]["title"] == "完成一次短诊断"
        # The frozen resource_opened/reading_started demo events are browsing only.
        assert all(not item["sourceEventIds"] for item in graph["nodes"])
        assert "浏览、搜索、展开和选择节点不改变掌握度" in graph["boundary"]
        for section in before["sections"]:
            assert section["headline"] and section["next_step"]["title"]
            assert section["evidence"]
            for evidence in section["evidence"]:
                assert evidence["source_type"] and evidence["source_id"]
                assert evidence["observed_at"]
                assert evidence["recommendation_impact"]

        question = session.query(DBAssessmentQuestion).filter_by(course_id=COURSE_ID).order_by(
            DBAssessmentQuestion.id,
        ).first()
        version = session.get(DBAssessmentQuestionVersion, question.current_version_id)
        payload = AttemptInput(
            question_version_id=version.id,
            idempotency_key="r3-profile-summary-attempt-001",
            mode="diagnostic",
            answer={"value": version.answer_key["value"]},
        )
        request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
        result = _run(m5_api.submit_assessment_attempt(request, payload, current_user=learner))
        assert result["ability_update"]["applied"] is True

        after = _run(m5_api.get_profile_summary(course_id=COURSE_ID, current_user=learner))
        assert after["summary"]["diagnostic_response_count"] == 1
        assert after["summary"]["diagnostic_attempt_count"] == 3
        skill = next(item for item in after["sections"] if item["key"] == "skill")
        assert any(item["source_type"] == "assessment_ability_state" for item in skill["evidence"])
        assert any(item["source_type"] == "assessment_attempt" for item in skill["evidence"])
        assert after["summary"]["evidence_count"] > before["summary"]["evidence_count"]
        updated_node = next(
            item for item in after["knowledge_graph"]["nodes"]
            if item["id"] == version.primary_knowledge_point_id
        )
        assert updated_node["evidenceCount"] >= 1
        assert any(item["sourceId"] == result["id"] for item in updated_node["evidence"])
    finally:
        session.close()
        engine.dispose()


def test_skill_summary_prefers_named_course_weak_points_over_generic_ability_uncertainty():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        snapshot = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        snapshot_payload = dict(snapshot.snapshot or {})
        snapshot_payload.pop("weak_knowledge_point_ids", None)
        snapshot_payload["weak_points"] = [
            "Coding Agent、MCP 与 Skill",
            "优化算法、正则化与训练稳定性",
        ]
        snapshot.snapshot = snapshot_payload
        session.add(DBAssessmentAbilityState(
            owner_public_id=learner.public_id,
            course_scope=COURSE_ID,
            theta=[0.2, 0.1, -0.2],
            theta_std=[0.8, 0.8, 0.9],
            response_count=8,
        ))
        session.flush()

        result = build_profile_summary(session, current_user=learner, course_id=COURSE_ID)
        skill = next(item for item in result["sections"] if item["key"] == "skill")
        assert skill["difficulties"] == snapshot_payload["weak_points"]
        assert all("仍需更多证据确认" not in item for item in skill["difficulties"])
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize('kind', ['learning_aggregation_projection', 'learning_aggregation_baseline', 'flashcard_mastery_correction'])
def test_course_summary_does_not_borrow_aggregate_weaknesses_or_other_course_reviews(kind):
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username='lzz').one()
        before = build_profile_summary(session, current_user=learner, course_id=COURSE_ID)
        point = next(node for node in before['knowledge_graph']['nodes'] if node['mastery'] is None)
        snapshot = session.get(DBProfileSnapshot, 'demo-profile-lzz-v1')
        payload = dict(snapshot.snapshot or {})
        payload.pop('weak_knowledge_point_ids', None)
        payload.update(kind=kind, course_id=COURSE_ID, weak_points=['摄影曝光量', point['name']])
        snapshot.snapshot = payload
        session.add(DBCourse(id='other-photography-course', version='1', manifest_version='test-v1', title='摄影测试课', domain_pack='photography',
            visibility='public', status='active', owner_public_id=learner.public_id))
        session.flush()
        session.add(DBReviewPlan(student_id=learner.username, concept='摄影曝光量',
            course_id='other-photography-course', priority=0.9))
        session.flush()
        result = build_profile_summary(session, current_user=learner, course_id=COURSE_ID)
        skill = next(section for section in result['sections'] if section['key']=='skill')
        assert skill['difficulties'] == [point['name']]
        behavior = next(section for section in result['sections'] if section['key']=='behavior')
        old_behavior = next(section for section in before['sections'] if section['key']=='behavior')
        assert behavior['difficulties'] == old_behavior['difficulties']
        assert snapshot.snapshot == payload, 'Reading the summary must not alter original facts'
    finally:
        session.close(); engine.dispose()


def test_profile_graph_reads_are_owner_scoped_and_do_not_mutate_learning_state(monkeypatch):
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()

        async def isolated_run_db_op(operation, *args, **kwargs):
            return operation(session, *args, **kwargs)

        monkeypatch.setattr(m5_api, "run_db_op", isolated_run_db_op)

        def counts():
            return {
                "events": session.query(DBLearningEvent).count(),
                "snapshots": session.query(DBProfileSnapshot).count(),
                "paths": session.query(DBLearningPath).count(),
                "reviews": session.query(DBReviewPlan).count(),
            }

        before = counts()
        first = _run(m5_api.get_profile_summary(course_id=COURSE_ID, current_user=learner))
        second = _run(m5_api.get_profile_summary(course_id=COURSE_ID, current_user=learner))
        assert counts() == before
        assert first["knowledge_graph"] == second["knowledge_graph"]
        assert first["owner"]["public_id"] == learner.public_id
        assert all(
            evidence["sourceId"]
            for node in first["knowledge_graph"]["nodes"]
            for evidence in node["evidence"]
        )
    finally:
        session.close()
        engine.dispose()


def test_profile_summary_allows_public_course_but_rejects_private_non_member_and_exposes_shared_panel(monkeypatch):
    engine, session = _session()
    try:
        seed_competition_demo(session)
        outsider = DBUser(
            public_id="usr-r3-profile-outsider",
            username="r3-profile-outsider",
            hashed_password="not-used",
            role="student",
        )
        session.add(outsider)
        session.commit()

        async def isolated_run_db_op(operation, *args, **kwargs):
            return operation(session, *args, **kwargs)

        monkeypatch.setattr(m5_api, "run_db_op", isolated_run_db_op)
        public_summary = _run(m5_api.get_profile_summary(course_id=COURSE_ID, current_user=outsider))
        assert public_summary["course"]["id"] == COURSE_ID
        course = session.get(DBCourse, COURSE_ID)
        course.visibility = "private"
        session.flush()
        with pytest.raises(HTTPException) as forbidden:
            _run(m5_api.get_profile_summary(course_id=COURSE_ID, current_user=outsider))
        assert forbidden.value.status_code == 409
        assert forbidden.value.detail["code"] == "course_unavailable"

        membership = DBCourseMembership(course_id=COURSE_ID,
            user_public_id=outsider.public_id, role="student", status="active")
        session.add(membership)
        session.flush()
        member_summary = _run(m5_api.get_profile_summary(course_id=COURSE_ID, current_user=outsider))
        assert member_summary["owner"]["public_id"] == outsider.public_id
        assert all(node["mastery"] is None for node in member_summary["knowledge_graph"]["nodes"])
        membership.status = "removed"
        session.flush()
        with pytest.raises(HTTPException):
            _run(m5_api.get_profile_summary(course_id=COURSE_ID, current_user=outsider))

        component = (ROOT / "frontend/src/components/ProfileSummaryPanel.vue").read_text(encoding="utf-8")
        assessment = (ROOT / "frontend/src/views/AssessmentWorkspace.vue").read_text(encoding="utf-8")
        profile = (ROOT / "frontend/src/views/StudentAnalysis.vue").read_text(encoding="utf-8")
        for marker in (
            'data-testid="profile-summary"',
            "profile-section-${section.key}",
            "查看来源、时间与推荐影响",
            "recommendation_impact",
        ):
            assert marker in component
        assert "summaryPanel.value?.refresh()" in assessment
        assert "ProfileSummaryPanel" in assessment
        assert "ProfileSummaryPanel" in profile
    finally:
        session.close()
        engine.dispose()
