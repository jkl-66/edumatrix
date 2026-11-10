from __future__ import annotations

from datetime import date, datetime
import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import (
    Base,
    DBAssessmentAttempt,
    DBAssessmentGradingResult,
    DBAssessmentQuestion,
    DBAssessmentQuestionVersion,
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
    DBKnowledgePoint,
    DBLearningEvent,
    DBLearningPath,
    DBPathNode,
    DBPlanDraft,
    DBPlanVersion,
    DBProfileSnapshot,
    DBSourceDocument,
    DBSourceRef,
    DBStudentProfile,
    DBUser,
)
from app.m5_learning import multi_course_schedule, transition_path, today_work_items, _schedule_resource_plan
from app.main import app
import app.m5_api as m5_api


def test_schedule_parts_keep_the_actual_task_time_budget():
    for minutes in (1, 2, 5, 14, 19, 33, 90):
        parts = _schedule_resource_plan(expected_minutes=minutes, mastery_state="unknown", preferences=["代码实操"])
        assert sum(item["estimate_minutes"] for item in parts) == minutes
        assert all(item["estimate_minutes"] > 0 for item in parts)
        if minutes >= 5:
            assert [item["type"] for item in parts] == ["practice", "learning", "extension"]


def test_existing_schedule_uses_updated_preferences_without_changing_mastery():
    engine, session = _session()
    try:
        owner = "current-preferences"
        session.add(DBUser(public_id=owner, username=owner, hashed_password="x", role="student"))
        _course(session, "course-a", "机器学习", "a")
        _path(session, owner, "course-a", "a")
        snapshot = _profile(session, owner, "course-a", "profile-current", weak=[], mastered=[], unknown=["a-kp-1"])
        row = DBStudentProfile(student_id=owner, interaction_preferences=["代码实操"], concept_mastery={"a-kp-1": 0.2})
        session.add(row)
        session.commit()
        before = dict(snapshot.snapshot)
        first = multi_course_schedule(session, owner_public_id=owner)["courses"][0]["nodes"][0]
        assert first["resources"][0]["type"] == "practice"
        row.interaction_preferences = ["图示讲解"]
        session.flush()
        second = multi_course_schedule(session, owner_public_id=owner)["courses"][0]["nodes"][0]
        assert second["resources"][0]["type"] == "learning"
        assert first["status"] == second["status"]
        assert snapshot.snapshot == before
        assert row.concept_mastery == {"a-kp-1": 0.2}
        assert session.query(DBLearningEvent).count() == 0
    finally:
        session.close()
        engine.dispose()


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def _course(session, course_id: str, title: str, prefix: str):
    session.add(DBCourse(id=course_id, version="1", title=title, subject=title, manifest_version="1", status="published"))
    source_id = f"source-{prefix}"
    session.add(DBSourceDocument(
        id=source_id, course_id=course_id, title=f"{title}教材", filename=f"{prefix}.md",
        file_format="md", content_hash=(prefix * 64)[:64], processing_status="ready",
    ))
    chapters = [
        DBChapter(id=f"{prefix}-chapter-1", course_id=course_id, source_document_id=source_id, stable_key="one", title=f"{title}基础", position=1),
        DBChapter(id=f"{prefix}-chapter-2", course_id=course_id, source_document_id=source_id, stable_key="two", title=f"{title}分支A", position=2),
        DBChapter(id=f"{prefix}-chapter-3", course_id=course_id, source_document_id=source_id, stable_key="three", title=f"{title}分支B", position=3),
    ]
    points = [
        DBKnowledgePoint(id=f"{prefix}-kp-1", domain_pack=prefix, code="one", version="1", title=f"{title}基础点"),
        DBKnowledgePoint(id=f"{prefix}-kp-2", domain_pack=prefix, code="two", version="1", title=f"{title}分支点A", prerequisites=[f"{prefix}-kp-1"]),
        DBKnowledgePoint(id=f"{prefix}-kp-3", domain_pack=prefix, code="three", version="1", title=f"{title}分支点B", prerequisites=[f"{prefix}-kp-1"]),
    ]
    session.add_all(chapters + points)
    session.flush()
    for index, chapter in enumerate(chapters, start=1):
        session.add(DBChapterKnowledgePoint(
            chapter_id=chapter.id, knowledge_point_id=f"{prefix}-kp-{index}", relation_type="teaches",
        ))
        session.add(DBSourceRef(
            id=f"{prefix}-ref-{index}", source_document_id=source_id, chapter_id=chapter.id,
            parser_version="test", location_label=f"第 {index} 节", content_hash=(f"{prefix}-{index}" * 20)[:64],
        ))
    session.flush()


def _path(session, owner: str, course_id: str, prefix: str, *, node_prefix: str | None = None) -> DBLearningPath:
    node_prefix = node_prefix or prefix
    plan = DBPlanDraft(
        id=f"{prefix}-plan", owner_public_id=owner, course_id=course_id,
        title=f"{prefix} plan", status="confirmed", idempotency_key=f"{prefix}-idem",
    )
    session.add(plan)
    session.flush()
    version = DBPlanVersion(
        id=f"{prefix}-version", plan_draft_id=plan.id, version_number=1,
        content={"schema_version": "m5.plan.v1", "goal": "test", "nodes": []}, content_hash=f"{prefix}-hash",
    )
    session.add(version)
    session.flush()
    path = DBLearningPath(
        id=f"{prefix}-path", owner_public_id=owner, course_id=course_id,
        source_plan_version_id=version.id, status="active",
    )
    session.add(path)
    session.flush()
    chapters = [f"{node_prefix}-chapter-1", f"{node_prefix}-chapter-2", f"{node_prefix}-chapter-3"]
    session.add_all([
        DBPathNode(
            id=f"{prefix}-node-1", learning_path_id=path.id, node_key=f"{prefix}-root", sequence=1,
            node_type="chapter", target_object_id=chapters[0], title="root", prerequisites=[],
            resource_status="existing", estimate_min_minutes=20, estimate_max_minutes=30,
        ),
        DBPathNode(
            id=f"{prefix}-node-2", learning_path_id=path.id, node_key=f"{prefix}-branch-a", sequence=2,
            node_type="chapter", target_object_id=chapters[1], title="branch-a", prerequisites=[f"{prefix}-root"],
            resource_status="existing", estimate_min_minutes=15, estimate_max_minutes=25,
        ),
        DBPathNode(
            id=f"{prefix}-node-3", learning_path_id=path.id, node_key=f"{prefix}-branch-b", sequence=3,
            node_type="chapter", target_object_id=chapters[2], title="branch-b", prerequisites=[f"{prefix}-root"],
            resource_status="existing", estimate_min_minutes=15, estimate_max_minutes=25,
        ),
    ])
    session.flush()
    return path


def _profile(session, owner: str, course_id: str, suffix: str, *, weak: list[str], mastered: list[str], unknown: list[str]):
    row = DBProfileSnapshot(
        id=f"{owner}-{suffix}", owner_public_id=owner, profile_version=f"b14-{suffix}",
        snapshot={
            "course_id": course_id,
            "time_budget_minutes": 35,
            "learning_preferences": {"mode": "代码实操" if weak else "图示讲解"},
            "mastery_by_knowledge_point": {
                item: {"status": "known", "score": 0.9, "evidence_item_count": 2}
                for item in mastered
            },
            "weak_knowledge_point_ids": weak,
            "mastered_knowledge_point_ids": mastered,
            "unknown_knowledge_point_ids": unknown,
        },
        content_hash=f"{suffix}-hash", trace_id=f"{suffix}-trace",
    )
    session.add(row)
    session.flush()
    return row


def test_schedule_keeps_specific_gap_then_uses_later_answer_without_rewriting_path():
    from copy import deepcopy
    engine, session = _session()
    try:
        owner = 'schedule-rubric-gap'
        session.add(DBUser(public_id=owner, username=owner, hashed_password='x', role='student'))
        _course(session, 'course-a', '机器学习', 'a')
        path = _path(session, owner, 'course-a', 'a')
        snapshot = _profile(session, owner, 'course-a', 'original', weak=[],
                            mastered=['a-kp-1'], unknown=['a-kp-2', 'a-kp-3'])
        session.get(DBPlanVersion, path.source_plan_version_id).profile_snapshot_id = snapshot.id
        session.add(DBAssessmentQuestion(id='schedule-gap-q', owner_public_id=owner,
            course_id='course-a', question_type='short_answer', origin='manual', status='approved'))
        session.flush()
        question = DBAssessmentQuestionVersion(id='schedule-gap-qv', question_id='schedule-gap-q',
            version_number=1, prompt='没有标签时能否直接训练指定的预测任务？',
            primary_knowledge_point_id='a-kp-1', content_hash='schedule-gap-qv')
        session.add(question); session.flush()
        from datetime import timedelta
        now = datetime.now()
        attempt = DBAssessmentAttempt(id='schedule-gap-answer', owner_public_id=owner,
            course_id='course-a', question_version_id=question.id, mode='diagnostic',
            idempotency_key='schedule-gap-answer', answer={'text': '能分组，所以能训练指定标签。'},
            grading_status='graded', score=.85, submitted_at=now)
        session.add(attempt); session.flush()
        session.add(DBAssessmentGradingResult(attempt_id=attempt.id, owner_public_id=owner,
            grader_type='ai', status='completed', score=.85, correct=True,
            criterion_results=[{'criterion_id': 'label_requirement', 'score': 0.0,
                'justification': '没有区分相似分组与监督训练。', 'improvement': '核对标签的用途。'}],
            content_hash='schedule-gap-grade', trace_id='schedule-gap-grade'))
        session.commit()
        original = deepcopy(snapshot.snapshot)
        from app.profile_adaptation import build_profile_adaptation, with_current_learning_evidence
        actor = session.query(DBUser).filter_by(public_id=owner).one()
        current_body = with_current_learning_evidence(session, snapshot, actor=actor,
            course_id='course-a', knowledge_point_id='a-kp-1')
        current_plan = build_profile_adaptation(current_body, knowledge_point={'id': 'a-kp-1'})
        assert current_plan['point_mastery'] == .85
        assert current_plan['difficulty_evidence']['kind'] == 'specific_learning_needs'
        assert '核对标签' in current_plan['mastery_focus']
        first = multi_course_schedule(session, owner_public_id=owner)
        root = first['courses'][0]['nodes'][0]
        assert root['status'] == 'pending'
        assert '相似分组' in root['reason']
        assert first['selected']['tasks'][0]['node_key'] == 'a-root'
        assert today_work_items(session, owner_public_id=owner, course_id='course-a')[0]['node_key'] == 'a-root'
        later = DBAssessmentAttempt(id='schedule-gap-resolved', owner_public_id=owner,
            course_id='course-a', question_version_id=question.id, mode='formal',
            idempotency_key='schedule-gap-resolved', answer={'text': '分组只描述相似性；预测指定标签需要相应标注。'},
            grading_status='graded', score=1.0, submitted_at=now + timedelta(minutes=5))
        session.add(later); session.flush()
        session.add(DBAssessmentGradingResult(attempt_id=later.id, owner_public_id=owner,
            grader_type='ai', status='completed', score=1.0, correct=True,
            criterion_results=[{'criterion_id': 'label_requirement', 'score': 1.0,
                'justification': '能区分两项任务。', 'improvement': ''}],
            content_hash='schedule-gap-resolved-grade', trace_id='schedule-gap-resolved-grade'))
        session.commit()
        next_body = with_current_learning_evidence(session, snapshot, actor=actor,
            course_id='course-a', knowledge_point_id='a-kp-1')
        next_plan = build_profile_adaptation(next_body, knowledge_point={'id': 'a-kp-1'})
        assert next_plan['learning_requirements']['diagnostic_followup'] == []
        assert next_plan['difficulty_band'] == 'transfer'
        assert current_plan['learning_requirements']['diagnostic_followup']
        after = multi_course_schedule(session, owner_public_id=owner)
        assert after['courses'][0]['nodes'][0]['status'] == 'skipped'
        assert after['courses'][0]['profile_snapshot_id'] == snapshot.id
        assert snapshot.snapshot == original and attempt.score == .85
        assert session.query(DBLearningEvent).count() == 0
        assert session.get(DBPathNode, 'a-node-1').status != 'completed'
    finally:
        session.close(); engine.dispose()


def test_weak_topic_priority_reaches_its_unfinished_prerequisite():
    engine, session = _session()
    try:
        owner = 'schedule-foundation'
        session.add(DBUser(public_id=owner, username=owner, hashed_password='x', role='student'))
        _course(session, 'course-a', '机器学习', 'a')
        _path(session, owner, 'course-a', 'a')
        _profile(session, owner, 'course-a', 'weak-branches', weak=['a-kp-2', 'a-kp-3'],
                 mastered=[], unknown=['a-kp-1'])
        session.get(DBPathNode, 'a-node-3').prerequisites = []
        session.commit()
        result = multi_course_schedule(session, owner_public_id=owner)
        # The unrelated weak branch must not preempt the foundation of the
        # earlier weak topic. Both priorities remain evidence-driven.
        assert result['selected']['tasks'][0]['node_key'] == 'a-root'
        assert result['courses'][0]['nodes'][0]['priority'] == 100
        assert session.query(DBLearningEvent).count() == 0
    finally:
        session.close(); engine.dispose()


def test_shared_budget_distributes_two_courses_and_today_matches_subject_view():
    engine, session = _session()
    try:
        owner = "shared-budget-student"
        session.add(DBUser(public_id=owner, username=owner, hashed_password="hash", role="student", is_active=True))
        for suffix in ("a", "b"):
            _course(session, f"course-{suffix}", suffix, suffix)
            _path(session, owner, f"course-{suffix}", suffix)
            _profile(session, owner, f"course-{suffix}", f"budget-{suffix}", weak=[], mastered=[], unknown=[])
        session.commit()
        schedule = multi_course_schedule(session, owner_public_id=owner)
        assert schedule["budget_minutes"] == 35
        assert all(day["total_minutes"] <= 35 for day in schedule["days"])
        assert {task["course_id"] for day in schedule["days"][:2] for task in day["tasks"]} == {"course-a", "course-b"}
        for cid in ("course-a", "course-b"):
            subject = multi_course_schedule(session, owner_public_id=owner, course_id=cid)
            assert [task["node_id"] for task in subject["selected"]["tasks"]] == [task["node_id"] for task in schedule["selected"]["tasks"] if task["course_id"] == cid]
            today = today_work_items(session, owner_public_id=owner, course_id=cid, limit=50)
            assert {task["node_id"] for task in today if task["task_kind"] == "path"} == {task["node_id"] for task in subject["selected"]["tasks"]}
        assert session.query(DBLearningEvent).count() == 0
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize("utc_now,expected_today,expected_dates", [
    (datetime(2026, 10, 29, 10), "2026-10-29", ["2026-10-29", "2026-11-03"]),
    (datetime(2026, 10, 30, 10), "2026-10-30", ["2026-11-03", "2026-11-05"]),
    (datetime(2026, 11, 2, 17), "2026-11-03", ["2026-11-03", "2026-11-05"]),
])
def test_confirmed_weekdays_respect_local_date_month_boundary_and_today(monkeypatch, utc_now, expected_today, expected_dates):
    monkeypatch.setattr("app.m5_learning._now", lambda: utc_now)
    engine, session = _session()
    try:
        owner = "weekday-student"
        session.add(DBUser(public_id=owner, username=owner, hashed_password="x", role="student"))
        _course(session, "course-a", "机器学习", "a")
        _path(session, owner, "course-a", "a")
        session.add(DBStudentProfile(student_id=owner, dimension_states={
            "learning_context": {"summary": "周二、周四19:30开始，每次40分钟"},
        }))
        session.commit()
        schedule = multi_course_schedule(session, owner_public_id=owner)
        assert schedule["selected"]["date"] == expected_today
        assert schedule["study_weekdays"] == [1, 3]
        assert [day["date"] for day in schedule["days"] if day["tasks"]] == expected_dates
        assert all(date.fromisoformat(day["date"]).weekday() in (1, 3) for day in schedule["days"] if day["tasks"])
        today = today_work_items(session, owner_public_id=owner, course_id="course-a")
        assert {task["node_id"] for task in today} == {task["node_id"] for task in schedule["selected"]["tasks"]}
        assert session.query(DBLearningEvent).count() == 0
    finally:
        session.close()
        engine.dispose()


def test_study_weekdays_use_only_clear_current_confirmed_arrangements():
    from app.profile_adaptation import confirmed_study_days
    for text, expected in [("周二、四晚上学习", (1, 3)), ("周一至周五晚上学习", (0, 1, 2, 3, 4)),
                           ("周末学习", (5, 6)), ("周二没空，周四可能有空", ())]:
        assert confirmed_study_days({"dimension_states": {"learning_context": {"summary": text}}}) == expected
    assert confirmed_study_days({"dimension_states": {"learning_context": {"summary": "周二学习"}},
                                 "learning_adaptation": {"registration_profile": {"learning_context": "周六学习"}}}) == (5,)


def test_variable_confirmed_sessions_keep_each_day_and_fit_shorter_path_steps():
    from app.profile_adaptation import confirmed_study_minutes, confirmed_study_minutes_by_weekday
    for summary, expected in [
        ('计划16周完成基础；每周二、四各60分钟，周日90分钟。', {1:60,3:60,6:90}),
        ('周一至周五各半小时，周末90分钟', {0:30,1:30,2:30,3:30,4:30,5:90,6:90}),
        ('周二和周四共60分钟，周日90分钟', {}),
        ('周二60分钟或90分钟', {}),
        ('周二60分钟，周四可能90分钟', {}),
        ('现在改为周二30分钟，周六60分钟，替代原来每天90分钟', {1:30,5:60}),
        ('Tuesdays 1 hour, Thursdays 1.5 hours', {1:60,3:90}),
    ]:
        snapshot = {'dimension_states':{'learning_context':{'summary':summary}}}
        assert confirmed_study_minutes_by_weekday(snapshot) == expected
        if expected:
            assert confirmed_study_minutes(snapshot) == min(expected.values())


@pytest.mark.parametrize('chained', [False, True])
def test_calendar_allocates_sixty_sixty_ninety_without_changing_learning_records(monkeypatch, chained):
    monkeypatch.setattr('app.m5_learning._now', lambda: datetime(2026,11,3,10))
    engine, session = _session()
    try:
        owner = 'variable-session-student'
        session.add(DBUser(public_id=owner,username=owner,hashed_password='x',role='student'))
        _course(session,'course-a','机器学习','a')
        path = _path(session,owner,'course-a','a')
        existing = session.query(DBPathNode).filter_by(learning_path_id=path.id).all()
        for node in existing:
            node.prerequisites=[]
            node.estimate_min_minutes=node.estimate_max_minutes=30
        for i in range(4,8):
            session.add(DBPathNode(id=f'variable-{i}',learning_path_id=path.id,node_key=f'variable-{i}',sequence=i,
                node_type='chapter',target_object_id=existing[0].target_object_id,title=f'独立任务{i}',
                prerequisites=[],resource_status='existing',estimate_min_minutes=30,estimate_max_minutes=30))
        session.add(DBStudentProfile(student_id=owner,dimension_states={'learning_context':{
            'confirmed_fields':{'study_schedule':'每周二、四各60分钟，周日90分钟'}}}))
        session.flush()
        ordered = session.query(DBPathNode).filter_by(learning_path_id=path.id).order_by(DBPathNode.sequence).all()
        if chained:
            for i, node in enumerate(ordered):
                node.prerequisites = [ordered[i-1].node_key] if i else []
        session.commit()
        schedule=multi_course_schedule(session,owner_public_id=owner)
        assert [(day['date'],day['budget_minutes'],day['total_minutes']) for day in schedule['days']] == [
            ('2026-11-03',60,60),('2026-11-05',60,60),('2026-11-08',90,90)]
        assert schedule['study_minutes_by_weekday']=={1:60,3:60,6:90}
        assert schedule['courses'][0]['time_budget_minutes']==60
        assert session.query(DBLearningEvent).count()==0
        assert all(n.status=='pending' for n in session.query(DBPathNode).filter_by(learning_path_id=path.id))
        if chained:
            from app.exam_gate import freeze_exam_gate_snapshot
            assert [n['status'] for n in schedule['selected']['tasks']] == ['in_progress', 'pending']
            assert [n['node_id'] for n in today_work_items(session,owner_public_id=owner)] == [ordered[0].id]
            frozen = freeze_exam_gate_snapshot(session, owner_public_id=owner, course_id='course-a',
                                              path_id=path.id, task_id=ordered[0].id)
            assert [n['id'] for n in frozen['required_tasks']] == [n.id for n in ordered[:2]]
    finally:
        session.close();engine.dispose()


def test_completed_predecessor_allows_same_session_successor_without_expanding_assignment(monkeypatch):
    from datetime import timezone, timedelta
    from app.m1_repository import create_generation_task, append_task_event
    from app.m5_learning import LearningEventInput, record_learning_event, process_path_event
    from app.exam_gate import freeze_exam_gate_snapshot
    moment = datetime(2026, 11, 3, 10)
    monkeypatch.setattr('app.m5_learning._now', lambda: moment)
    monkeypatch.setattr('app.exam_gate._now', lambda: moment)
    engine, session = _session()
    try:
        owner = 'continue-same-session'
        session.add(DBUser(public_id=owner, username=owner, hashed_password='x', role='student'))
        _course(session, 'course-a', '机器学习', 'a')
        path = _path(session, owner, 'course-a', 'a')
        nodes = session.query(DBPathNode).filter_by(learning_path_id=path.id).order_by(DBPathNode.sequence).all()
        for i, node in enumerate(nodes):
            node.estimate_min_minutes = node.estimate_max_minutes = 30
            node.prerequisites = [nodes[i-1].node_key] if i else []
        session.add(DBStudentProfile(student_id=owner, dimension_states={'learning_context': {
            'confirmed_fields': {'study_schedule': '每周二60分钟，周四90分钟'}}}))
        session.commit()
        before = multi_course_schedule(session, owner_public_id=owner)
        frozen_before = freeze_exam_gate_snapshot(session, owner_public_id=owner, course_id='course-a',
            path_id=path.id, task_id=nodes[0].id, assigned_at=moment-timedelta(minutes=1))
        task, _ = create_generation_task(session, owner_public_id=owner, course_id='course-a',
            capability='learning_resource_bundle.generate', idempotency_key='same-session-resource', model='synthetic')
        append_task_event(session, task_id=task.id, event_type='resource_generation.requested',
                          payload={'manifest':{'exam_gate':frozen_before}})
        session.commit()
        event, _ = record_learning_event(session, owner_public_id=owner, trusted_source=True,
            event=LearningEventInput(idempotency_key='same-session-code', event_type='code_tests_passed',
                course_id='course-a', object_type='chapter', object_id=nodes[0].target_object_id,
                source='sandbox', occurred_at=moment.replace(tzinfo=timezone.utc),
                payload={'path_id':path.id, 'passed_count':2, 'total_count':2,
                         'test_scope':'hidden', 'run_id':'same-session-run'}))
        process_path_event(session, event=event)
        after = multi_course_schedule(session, owner_public_id=owner)
        assert [n['node_id'] for n in before['selected']['tasks']] == [n['node_id'] for n in after['selected']['tasks']] == [n.id for n in nodes[:2]]
        assert [n['status'] for n in after['selected']['tasks']] == ['completed', 'in_progress']
        assert after['selected']['progress'] == {'completed':1, 'total':2}
        assert [n['node_id'] for n in today_work_items(session,owner_public_id=owner)] == [n.id for n in nodes[:2]]
        frozen = freeze_exam_gate_snapshot(session, owner_public_id=owner, course_id='course-a',
                                          path_id=path.id, task_id=nodes[1].id, assigned_at=moment+timedelta(minutes=1))
        assert [n['id'] for n in frozen['required_tasks']] == [n.id for n in nodes[:2]]
        assert frozen['required_tasks'][0]['assigned_at'] == frozen_before['assigned_at']
        assert 'assigned_at' not in frozen['required_tasks'][1]
        assert nodes[2].status == 'pending' and after['days'][1]['tasks'][0]['node_id'] == nodes[2].id
        assert session.query(DBLearningEvent).count() == 1
    finally:
        session.close(); engine.dispose()


def test_multicourse_schedule_keeps_topology_and_profile_driven_differences():
    engine, session = _session()
    try:
        owner = "b14-owner"
        session.add(DBUser(public_id=owner, username=owner, hashed_password="hash", role="student", is_active=True))
        _course(session, "course-a", "数据结构", "a")
        _course(session, "course-b", "机器学习", "b")
        path_a = _path(session, owner, "course-a", "a")
        _path(session, owner, "course-b", "b")
        profile = _profile(
            session, owner, "course-a", "profile-a",
            weak=["a-kp-2"], mastered=["a-kp-1"], unknown=["a-kp-3"],
        )
        session.commit()

        before_events = session.query(DBLearningEvent).count()
        before_profile = dict(session.get(DBProfileSnapshot, profile.id).snapshot)
        result = multi_course_schedule(session, owner_public_id=owner)

        assert result["read_only"] is True
        assert result["learning_state_written"] is False
        assert {item["course_id"] for item in result["courses"]} == {"course-a", "course-b"}
        course_a = next(item for item in result["courses"] if item["course_id"] == "course-a")
        assert {edge["type"] for edge in course_a["topology"]["edges"]} >= {"path_prerequisite", "knowledge_prerequisite"}
        assert len(course_a["topology"]["modules"]) == 3
        assert next(item for item in course_a["nodes"] if item["node_key"] == "a-root")["status"] == "skipped"
        assert next(item for item in course_a["nodes"] if item["node_key"] == "a-branch-a")["priority"] > next(
            item for item in course_a["nodes"] if item["node_key"] == "a-branch-b"
        )["priority"]
        selected = result["selected"]
        assert selected["tasks"]
        task = next(item for item in selected["tasks"] if item["course_id"] == "course-a")
        assert {item["type"] for item in task["resources"]} == {"learning", "practice", "extension"}
        assert task["generation_context"]["profile_snapshot_id"] == profile.id
        assert task["generation_context"]["schedule_day"] == selected["day"]
        assert session.query(DBLearningEvent).count() == before_events
        assert dict(session.get(DBProfileSnapshot, profile.id).snapshot) == before_profile

        # The same diagnosis-backed exemption must apply to Today and the
        # generation/exam gate, without writing fake completion records.
        today = today_work_items(session, owner_public_id=owner, course_id="course-a", limit=50)
        assert "a-root" not in {item["node_key"] for item in today}
        assert {item["node_key"] for item in today} == {item["node_key"] for item in selected["tasks"] if item["course_id"] == "course-a"}
        from app.exam_gate import freeze_exam_gate_snapshot
        frozen = freeze_exam_gate_snapshot(session, owner_public_id=owner, course_id="course-a", path_id=path_a.id, task_id=task["node_id"])
        assert {item["id"] for item in frozen["required_tasks"]} == {item["node_id"] for item in today if item["required"]}
        assert session.query(DBLearningEvent).count() == before_events

        second_day = multi_course_schedule(session, owner_public_id=owner, selected_day=2)
        assert second_day["selected"]["day"] == 2
        assert second_day["selected"]["date"] != selected["date"]
        assert path_a.status == "active"
    finally:
        session.close()
        engine.dispose()


def test_schedule_changes_for_three_profiles_and_pause_removes_only_subject_work():
    engine, session = _session()
    try:
        _course(session, "course-a", "数据结构", "a")
        for index, owner in enumerate(("profile-low", "profile-mid", "profile-high")):
            session.add(DBUser(public_id=owner, username=owner, hashed_password="hash", role="student", is_active=True))
            _path(session, owner, "course-a", f"a{index}", node_prefix="a")
            if index == 0:
                weak, mastered, unknown = [f"a-kp-2"], [], [f"a-kp-1", f"a-kp-3"]
            elif index == 1:
                weak, mastered, unknown = [], [f"a-kp-1"], [f"a-kp-2", f"a-kp-3"]
            else:
                weak, mastered, unknown = [], [f"a-kp-1", f"a-kp-2"], [f"a-kp-3"]
            _profile(session, owner, "course-a", f"profile-{index}", weak=weak, mastered=mastered, unknown=unknown)
        session.commit()

        schedules = [multi_course_schedule(session, owner_public_id=owner) for owner in ("profile-low", "profile-mid", "profile-high")]
        first_tasks = [schedule["selected"]["tasks"][0]["node_key"] for schedule in schedules]
        assert len(set(first_tasks)) >= 2
        assert schedules[2]["courses"][0]["nodes"][0]["status"] == "skipped"

        paused_owner = "profile-low"
        paused_path = session.query(DBLearningPath).filter_by(owner_public_id=paused_owner).one()
        transition_path(session, path=paused_path, owner_public_id=paused_owner, target_status="paused", expected_lock_version=1)
        session.commit()
        paused_schedule = multi_course_schedule(session, owner_public_id=paused_owner)
        assert paused_schedule["courses"][0]["status"] == "paused"
        assert paused_schedule["selected"]["tasks"] == []
    finally:
        session.close()
        engine.dispose()


def test_schedule_is_owner_scoped_and_does_not_restore_legacy_path_surfaces():
    engine, session = _session()
    try:
        _course(session, "course-a", "数据结构", "a")
        session.add(DBUser(public_id="owner-a", username="owner-a", hashed_password="hash", role="student", is_active=True))
        session.add(DBUser(public_id="owner-b", username="owner-b", hashed_password="hash", role="student", is_active=True))
        _path(session, "owner-a", "course-a", "owner-a", node_prefix="a")
        _path(session, "owner-b", "course-a", "owner-b", node_prefix="a")
        session.commit()
        assert len(multi_course_schedule(session, owner_public_id="owner-a")["courses"]) == 1
        assert len(multi_course_schedule(session, owner_public_id="missing")["courses"]) == 0
    finally:
        session.close()
        engine.dispose()


def test_schedule_api_is_read_only_and_respects_authenticated_owner(monkeypatch):
    engine, session = _session()
    user = DBUser(public_id="api-owner", username="api-owner", hashed_password="hash", role="student", is_active=True)
    try:
        session.add(user)
        _course(session, "course-a", "数据结构", "a")
        _path(session, user.public_id, "course-a", "api", node_prefix="a")
        session.commit()

        async def fake_run_db_op(operation):
            return operation(session)

        monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
        app.dependency_overrides[get_current_user] = lambda: user
        events_before = session.query(DBLearningEvent).count()
        response = TestClient(app).get("/api/v1/m5/schedule?day=2")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["schema_version"] == "m5.multi-course-schedule.v1"
        assert body["read_only"] is True
        assert body["selected_day"] == 2
        assert session.query(DBLearningEvent).count() == events_before
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close()
        engine.dispose()
