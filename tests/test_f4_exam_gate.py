from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.database import (
    Base,
    DBAssessmentQuestion,
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
    DBCourseMembership,
    DBGenerationTask,
    DBLearningEvent,
    DBLearningPath,
    DBKnowledgePoint,
    DBPathNode,
    DBPlanDraft,
    DBPlanVersion,
    DBProfileSnapshot,
    DBTaskEvent,
    DBUser,
    DBSourceDocument,
    DBReviewPlan,
)
from app.exam_gate import ExamGateError, exam_gate_status, require_exam_gate
from app.exam_gate import freeze_exam_gate_snapshot
from app.m5_assessment_core import QuestionVersionInput, create_question_version
from app.m5_exam_core import (
    ExamCreateInput,
    ExamItemInput,
    assign_sitting,
    create_exam,
    transition_exam,
)
from app.main import app
import app.m5_api as m5_api


def _fixture():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([
        DBUser(public_id="teacher", username="f4-gate-teacher", hashed_password="x", role="teacher", is_active=True),
        DBUser(public_id="learner", username="f4-gate-learner", hashed_password="x", role="student", is_active=True),
        DBCourse(id="course-a", version="1", title="课程 A", visibility="private", manifest_version="1", owner_public_id="teacher"),
        DBCourse(id="course-b", version="1", title="课程 B", visibility="private", manifest_version="1", owner_public_id="teacher"),
        DBCourseMembership(course_id="course-a", user_public_id="teacher", role="teacher", status="active"),
        DBCourseMembership(course_id="course-a", user_public_id="learner", role="student", status="active"),
        DBCourseMembership(course_id="course-b", user_public_id="learner", role="student", status="active"),
    ])
    session.flush()
    plan = DBPlanDraft(
        id="plan-a",
        owner_public_id="learner",
        course_id="course-a",
        title="今日路径",
        status="confirmed",
        idempotency_key="f4-gate-plan",
    )
    session.add(plan)
    session.flush()
    version = DBPlanVersion(
        id="plan-version-a",
        plan_draft_id=plan.id,
        version_number=1,
        content={"schema_version": "m5.plan.v1", "goal": "完成今日任务", "nodes": []},
        content_hash="a" * 64,
    )
    session.add(version)
    session.flush()
    path = DBLearningPath(
        id="path-a",
        owner_public_id="learner",
        course_id="course-a",
        source_plan_version_id=version.id,
        status="active",
    )
    session.add(path)
    session.flush()
    session.add_all([
        DBPathNode(
            id="required-1", learning_path_id=path.id, node_key="required-1", sequence=1,
            node_type="assessment", target_object_id="target-1", title="完成概念测验",
            status="completed", prerequisites=[], is_extension=False,
            resource_status="existing", estimate_min_minutes=10, estimate_max_minutes=15,
        ),
        DBPathNode(
            id="required-2", learning_path_id=path.id, node_key="required-2", sequence=2,
            node_type="interactive", target_object_id="target-2", title="完成交互实验",
            status="pending", prerequisites=["required-1"], is_extension=False,
            resource_status="existing", estimate_min_minutes=15, estimate_max_minutes=20,
        ),
        DBPathNode(
            id="optional-1", learning_path_id=path.id, node_key="optional-1", sequence=3,
            node_type="extension", target_object_id=None, title="可选拓展阅读",
            status="pending", prerequisites=[], is_extension=True,
            resource_status="existing", estimate_min_minutes=5, estimate_max_minutes=10,
        ),
    ])
    session.flush()
    assigned_at = datetime.utcnow() - timedelta(minutes=5)
    snapshot = {
        "schema_version": "f4.intelligent-exam-gate.v1",
        "assignment_date": date.today().isoformat(),
        "assigned_at": assigned_at.isoformat() + "Z",
        "course_id": "course-a",
        "path_id": path.id,
        "path_version_id": version.id,
        "selected_task_id": "required-1",
        "required_tasks": [
            {
                "id": "required-1", "node_key": "required-1", "title": "完成概念测验",
                "node_type": "assessment", "target_object_id": "target-1",
                "completion_criteria": "服务端判分通过", "route": "/workspace/path?course_id=course-a&node_id=required-1",
            },
            {
                "id": "required-2", "node_key": "required-2", "title": "完成交互实验",
                "node_type": "interactive", "target_object_id": "target-2",
                "completion_criteria": "全部检查通过", "route": "/workspace/path?course_id=course-a&node_id=required-2",
            },
        ],
        "optional_task_ids": ["optional-1"],
    }
    task = DBGenerationTask(
        id="generation-a",
        owner_public_id="learner",
        course_id="course-a",
        trace_id="trace-generation-a",
        status="completed",
        progress=1,
        capability="learning_resource_bundle.generate",
        idempotency_key="generation-a-key",
    )
    session.add(task)
    session.flush()
    session.add(DBTaskEvent(
        id="generation-a-requested",
        task_id=task.id,
        sequence=1,
        event_type="resource_generation.requested",
        payload={"manifest": {"exam_gate": snapshot}},
    ))
    _complete(session, "required-1", "target-1", assigned_at + timedelta(minutes=1))
    session.commit()
    return session, engine, path, snapshot


def _complete(session, task_id: str, object_id: str, occurred_at: datetime):
    event = DBLearningEvent(
        id=f"evidence-{task_id}-{int(occurred_at.timestamp())}",
        owner_public_id="learner",
        course_id="course-a",
        event_type="quiz_answered",
        schema_version="m5.learning-event.v1",
        idempotency_key=f"evidence-key-{task_id}-{int(occurred_at.timestamp())}",
        source="backend",
        trace_id=f"trace-{task_id}-{int(occurred_at.timestamp())}",
        object_type="path_target",
        object_id=object_id,
        action="assessment.answered",
        context_ref={"userId": "learner", "courseId": "course-a", "taskId": task_id},
        evidence_strength=0.8,
        evidence_status="accepted",
        evidence_reason="服务端有效证据",
        mastery_eligible=True,
        completion_effect="complete",
        payload_version="1",
        payload={"graded": True, "correct": True, "attempt_id": f"attempt-{task_id}"},
        occurred_at=occurred_at,
    )
    session.add(event)
    session.flush()
    return event


def test_gate_unlocks_only_after_all_frozen_required_tasks_complete():
    session, engine, path, snapshot = _fixture()
    try:
        locked = exam_gate_status(session, owner_public_id="learner", course_id="course-a")
        assert locked["unlocked"] is False
        assert locked["completed_task_ids"] == ["required-1"]
        assert locked["missing_task_ids"] == ["required-2"]
        assert locked["missing_tasks"][0]["route"].endswith("node_id=required-2")
        assert "optional-1" not in locked["missing_task_ids"]

        session.get(DBPathNode, "required-2").status = "completed"
        _complete(
            session,
            "required-2",
            "target-2",
            datetime.fromisoformat(snapshot["assigned_at"].removesuffix("Z")) + timedelta(minutes=2),
        )
        path.status = "completed"
        path.completed_at = datetime.utcnow()
        session.commit()

        unlocked = exam_gate_status(session, owner_public_id="learner", course_id="course-a")
        assert unlocked["unlocked"] is True
        assert unlocked["completed_task_ids"] == ["required-1", "required-2"]
        assert unlocked["missing_tasks"] == []
        assert unlocked["optional_task_ids"] == ["optional-1"]
    finally:
        session.close()
        engine.dispose()


def _make_following_task_available(session):
    course = session.get(DBCourse, "course-a")
    course.status = "published"
    session.add(DBSourceDocument(
        id="freeze-source", course_id=course.id, title="课程资料", filename="course.md",
        file_format="md", content_hash="d" * 64, source_sha256="d" * 64,
        processed_sha256="d" * 64,
    ))
    # Today's completed prerequisites remain on today's projection; this
    # scenario starts the next task after completing its prerequisite yesterday.
    session.query(DBLearningEvent).filter_by(object_id="target-1").one().occurred_at = datetime.utcnow() - timedelta(days=1)
    session.flush()


def test_server_freezes_required_path_tasks_and_ignores_optional_extensions():
    session, engine, _, _ = _fixture()
    try:
        _make_following_task_available(session)
        snapshot = freeze_exam_gate_snapshot(
            session,
            owner_public_id="learner",
            course_id="course-a",
            path_id="path-a",
            task_id="required-2",
        )
        assert snapshot["path_version_id"] == "plan-version-a"
        assert [item["id"] for item in snapshot["required_tasks"]] == ["required-2"]
        assert snapshot["optional_task_ids"] == ["optional-1"]
        assert snapshot["required_tasks"][0]["route"].endswith("node_id=required-2")
    finally:
        session.close()
        engine.dispose()


def test_snapshot_uses_only_current_today_tasks_and_starts_evidence_window_at_request():
    session, engine, path, _ = _fixture()
    try:
        _make_following_task_available(session)
        stale_time = datetime.utcnow() - timedelta(minutes=1)
        _complete(session, "required-2", "target-2", stale_time)
        session.flush()
        snapshot = freeze_exam_gate_snapshot(
            session,
            owner_public_id="learner",
            course_id="course-a",
            path_id=path.id,
            task_id="required-2",
        )
        assert [item["id"] for item in snapshot["required_tasks"]] == ["required-2"]
        assigned_at = datetime.fromisoformat(snapshot["assigned_at"].removesuffix("Z"))
        assert assigned_at > stale_time
        session.get(DBTaskEvent, "generation-a-requested").payload = {
            "manifest": {"exam_gate": snapshot},
        }
        session.get(DBPathNode, "required-2").status = "completed"
        session.commit()

        assert exam_gate_status(
            session, owner_public_id="learner", course_id="course-a",
        )["unlocked"] is False
        _complete(session, "required-2", "target-2", assigned_at + timedelta(seconds=1))
        session.commit()
        assert exam_gate_status(
            session, owner_public_id="learner", course_id="course-a",
        )["unlocked"] is True
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize('explicit_context', [True, False])
def test_gate_matches_completion_event_to_chapter_knowledge_point_when_node_projection_lags(explicit_context):
    session, engine, path, snapshot = _fixture()
    try:
        source = DBSourceDocument(
            id="source-course-a",
            course_id="course-a",
            title="课程来源",
            filename="course.md",
            file_format="md",
            content_hash="c" * 64,
            source_sha256="c" * 64,
            processed_sha256="c" * 64,
        )
        chapter = DBChapter(
            id="target-2",
            course_id="course-a",
            source_document_id=source.id,
            stable_key="target-2",
            title="目标章节",
            position=1,
        )
        point = DBKnowledgePoint(
            id="kp-target-2",
            domain_pack="test",
            code="target-2",
            version="1",
            title="目标知识点",
        )
        session.add_all([source, chapter, point])
        session.flush()
        session.add(DBChapterKnowledgePoint(
            id="chapter-point-target-2",
            chapter_id=chapter.id,
            knowledge_point_id=point.id,
        ))
        session.get(DBPathNode, "required-2").node_type = "chapter"
        event = _complete(
            session,
            "required-2",
            "resource-artifact",
            datetime.fromisoformat(snapshot["assigned_at"].removesuffix("Z")) + timedelta(minutes=2),
        )
        event.context_ref = {"userId": "learner", "courseId": "course-a", "knowledgePointId": point.id}
        if not explicit_context:
            _, version = create_question_version(
                session, owner_public_id='teacher', course_id='course-a',
                question_type='single_choice', origin='manual',
                version=QuestionVersionInput(
                    prompt='合成测试：请选择正确项', options=('A. 正确', 'B. 错误'),
                    answer_key={'choice': 'A'}, scoring_rule={'type': 'exact', 'version': 'objective-v1'},
                    primary_knowledge_point_id=point.id,
                ),
            )
            event.context_ref = {'userId': 'learner', 'courseId': 'course-a'}
            event.object_type = 'assessment_question_version'
            event.object_id = version.id
        session.commit()

        status = exam_gate_status(session, owner_public_id="learner", course_id="course-a")
        assert status["unlocked"] is True
        assert status["completed_task_ids"] == ["required-1", "required-2"]
    finally:
        session.close()
        engine.dispose()


def test_gate_isolates_course_and_path_version_and_relocks_after_evidence_revocation():
    session, engine, path, snapshot = _fixture()
    try:
        other_course = exam_gate_status(session, owner_public_id="learner", course_id="course-b")
        assert other_course["unlocked"] is False
        assert other_course["reason"] == "active_path_required"

        replacement = DBPlanVersion(
            id="plan-version-b",
            plan_draft_id="plan-a",
            version_number=2,
            content={"schema_version": "m5.plan.v1", "goal": "新路径", "nodes": []},
            content_hash="b" * 64,
        )
        session.add(replacement)
        session.flush()
        path.source_plan_version_id = replacement.id
        session.commit()
        replaced = exam_gate_status(session, owner_public_id="learner", course_id="course-a")
        assert replaced["unlocked"] is False
        assert replaced["reason"] == "today_snapshot_required"

        path.source_plan_version_id = snapshot["path_version_id"]
        node = session.get(DBPathNode, "required-2")
        node.status = "completed"
        second = _complete(session, "required-2", "target-2", datetime.utcnow())
        session.commit()
        assert exam_gate_status(session, owner_public_id="learner", course_id="course-a")["unlocked"] is True

        second.evidence_status = "rejected"
        second.mastery_eligible = False
        second.completion_effect = "none"
        session.commit()
        relocked = exam_gate_status(session, owner_public_id="learner", course_id="course-a")
        assert relocked["unlocked"] is False
        assert relocked["missing_task_ids"] == ["required-2"]
    finally:
        session.close()
        engine.dispose()


def test_gate_does_not_reuse_a_snapshot_from_another_day():
    session, engine, _, _ = _fixture()
    try:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        status = exam_gate_status(
            session,
            owner_public_id="learner",
            course_id="course-a",
            assignment_date=yesterday,
        )
        assert status["unlocked"] is False
        assert status["reason"] == "today_snapshot_required"
        assert status["assignment_date"] == yesterday
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize("new_task", [False, True])
def test_continue_yesterday_resources_requires_today_completion_and_all_today_tasks(new_task):
    session, engine, path, snapshot = _fixture()
    try:
        _make_following_task_available(session)
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        old_snapshot = {**snapshot, "assignment_date": yesterday,
                        "assigned_at": (datetime.utcnow() - timedelta(days=1)).isoformat() + "Z"}
        original_event = session.get(DBTaskEvent, "generation-a-requested")
        original_event.payload = {"manifest": {"exam_gate": old_snapshot}}
        session.query(DBLearningEvent).one().occurred_at = datetime.utcnow() - timedelta(days=1)
        if new_task:
            session.add(DBPathNode(id="new-today", learning_path_id=path.id, node_key="new-today", sequence=4,
                node_type="assessment", target_object_id="new-target", title="新的今日任务", status="pending",
                prerequisites=[], is_extension=False, resource_status="missing", estimate_min_minutes=5, estimate_max_minutes=10))
        session.commit()
        before = exam_gate_status(session, owner_public_id="learner", course_id="course-a")
        assert not before["unlocked"]
        assert "required-2" in before["missing_task_ids"]
        completed = _complete(session, "required-2", "target-2", datetime.utcnow())
        session.get(DBPathNode, "required-2").status = "completed"
        session.commit()
        after = exam_gate_status(session, owner_public_id="learner", course_id="course-a")
        assert after["completed_task_ids"] == ["required-2"]
        assert after["unlocked"] is (not new_task)
        assert after["missing_task_ids"] == (["new-today"] if new_task else [])
        assert original_event.payload["manifest"]["exam_gate"] == old_snapshot
        completed.evidence_status = "rejected"
        completed.mastery_eligible = False
        completed.completion_effect = "none"
        session.commit()
        assert not exam_gate_status(session, owner_public_id="learner", course_id="course-a")["unlocked"]
    finally:
        session.close()
        engine.dispose()


def test_gate_before_generation_does_not_send_review_items_to_path_generation(monkeypatch):
    import app.exam_gate as gates
    session, engine, path, _ = _fixture()
    try:
        session.get(DBTaskEvent, "generation-a-requested").payload = {}
        items = [
            {"path_id": path.id, "node_id": "required-2", "title": "今日学习", "task_kind": "path", "node_type": "interactive", "required": True},
            {"path_id": path.id, "node_id": "review-1", "title": "到期复习", "task_kind": "review", "node_type": "review", "required": True},
        ]
        monkeypatch.setattr(gates, "today_work_items", lambda *args, **kwargs: items)
        status = exam_gate_status(session, owner_public_id="learner", course_id="course-a")
        assert status["missing_task_ids"] == ["required-2"]
        assert status["missing_tasks"][0]["route"].endswith("node_id=required-2")
    finally:
        session.close()
        engine.dispose()


def _replan_gate_fixture(session, previous, *, add_task=False):
    from app.m5_learning import _publish_path
    old_nodes = session.query(DBPathNode).filter_by(learning_path_id=previous.id, is_extension=False).all()
    nodes = [{
        "node_key": f"replanned-{node.node_key}", "node_type": node.node_type,
        "target_object_id": node.target_object_id, "title": node.title,
        "prerequisites": [], "resource_status": "existing",
        "estimate_min_minutes": 10, "estimate_max_minutes": 15,
    } for node in old_nodes]
    if add_task:
        nodes.append({**nodes[0], "node_key": "new-required", "target_object_id": "new-target", "title": "新增学习任务"})
    count = session.query(DBPlanVersion).count() + 1
    version = DBPlanVersion(
        id=f"replan-version-{count}", plan_draft_id="plan-a", version_number=count,
        content={"schema_version": "m5.plan.v1", "goal": "重新安排今日学习", "nodes": nodes},
        content_hash=str(count) * 64,
    )
    session.add(version)
    session.flush()
    previous.status = "archived"
    replacement = _publish_path(session, plan=session.get(DBPlanDraft, "plan-a"), version=version, previous_path=previous)
    session.commit()
    return replacement


@pytest.mark.parametrize("add_task", [False, True])
def test_same_day_replan_preserves_real_completions_but_requires_new_tasks(add_task):
    from copy import deepcopy
    from app.m5_learning import _completed_node_ids_today
    session, engine, path, snapshot = _fixture()
    try:
        _make_following_task_available(session)
        first = session.query(DBLearningEvent).filter_by(object_id="target-1").one()
        first.occurred_at = datetime.utcnow() - timedelta(minutes=2)
        first.payload = {**first.payload, "path_id": path.id}
        second = _complete(session, "required-2", "target-2", datetime.utcnow() - timedelta(minutes=1))
        second.payload = {**second.payload, "path_id": path.id}
        session.get(DBPathNode, "required-2").status = "completed"
        session.commit()
        original_payloads = [deepcopy(first.payload), deepcopy(second.payload)]
        assert exam_gate_status(session, owner_public_id="learner", course_id="course-a")["unlocked"]
        replacement = _replan_gate_fixture(session, path, add_task=add_task)
        nodes = session.query(DBPathNode).filter_by(learning_path_id=replacement.id).all()
        inherited = {node.id for node in nodes if node.target_object_id in {"target-1", "target-2"}}
        assert _completed_node_ids_today(session, owner_public_id="learner", course_id="course-a", nodes=nodes) == inherited
        status = exam_gate_status(session, owner_public_id="learner", course_id="course-a")
        assert set(status["completed_task_ids"]) == inherited
        assert status["unlocked"] is (not add_task)
        if add_task:
            new_node = next(node for node in nodes if node.target_object_id == "new-target")
            assert status["missing_task_ids"] == [new_node.id]
            # A new generation request must retain already-earned completions,
            # while the added task still needs new valid learning evidence.
            new_snapshot = freeze_exam_gate_snapshot(session, owner_public_id="learner", course_id="course-a", path_id=replacement.id, task_id=new_node.id)
            generation = DBGenerationTask(id="generation-new", owner_public_id="learner", course_id="course-a", trace_id="new", status="completed", progress=1, capability="learning_resource_bundle.generate", idempotency_key="new")
            session.add(generation)
            session.flush()
            session.add(DBTaskEvent(id="request-new", task_id=generation.id, sequence=1, event_type="resource_generation.requested", payload={"manifest": {"exam_gate": new_snapshot}}))
            session.commit()
            assert set(exam_gate_status(session, owner_public_id="learner", course_id="course-a")["completed_task_ids"]) == inherited
            _complete(session, new_node.id, "new-target", datetime.utcnow() + timedelta(seconds=1))
            session.commit()
            assert exam_gate_status(session, owner_public_id="learner", course_id="course-a")["unlocked"]
        else:
            second.evidence_status = "rejected"
            second.mastery_eligible = False
            second.completion_effect = "none"
            session.commit()
            assert not exam_gate_status(session, owner_public_id="learner", course_id="course-a")["unlocked"]
        assert [first.payload, second.payload] == original_payloads
        assert session.get(DBTaskEvent, "generation-a-requested").payload["manifest"]["exam_gate"] == snapshot
        assert not exam_gate_status(session, owner_public_id="learner", course_id="course-a", assignment_date=(date.today()+timedelta(days=1)).isoformat())["unlocked"]
    finally:
        session.close()
        engine.dispose()


def test_replan_does_not_reuse_an_unrelated_or_removed_target_history():
    from app.learning_aggregation import _event_matches_node
    session, engine, path, _ = _fixture()
    try:
        first = session.query(DBLearningEvent).filter_by(object_id="target-1").one()
        first.payload = {**first.payload, "path_id": path.id}
        replacement = _replan_gate_fixture(session, path)
        node = session.query(DBPathNode).filter_by(learning_path_id=replacement.id, target_object_id="target-1").one()
        assert _event_matches_node(session, first, node)
        replacement.supersedes_path_id = None
        session.flush()
        assert not _event_matches_node(session, first, node)
        assert not exam_gate_status(session, owner_public_id="learner", course_id="course-a")["completed_task_ids"]
        replacement.supersedes_path_id = path.id
        node.target_object_id = "changed-target"
        session.flush()
        latest = _replan_gate_fixture(session, replacement)
        restored = session.query(DBPathNode).filter_by(learning_path_id=latest.id, target_object_id="changed-target").one()
        restored.target_object_id = "target-1"
        session.flush()
        assert not _event_matches_node(session, first, restored)
    finally:
        session.close()
        engine.dispose()


def test_replan_does_not_keep_tomorrows_unfinished_task_in_todays_exam_gate():
    from app.m5_learning import multi_course_schedule, today_work_items
    session, engine, path, _ = _fixture()
    try:
        _make_following_task_available(session)
        first = session.query(DBLearningEvent).filter_by(object_id="target-1").one()
        first.occurred_at = datetime.utcnow() - timedelta(minutes=1)
        first.payload = {**first.payload, "path_id": path.id}
        session.commit()
        assert not exam_gate_status(session, owner_public_id="learner", course_id="course-a")["unlocked"]
        session.add(DBProfileSnapshot(
            id="replan-budget", owner_public_id="learner", profile_version="budget-v1",
            snapshot={"time_budget_minutes": 15}, content_hash="b" * 64, trace_id="budget",
        ))
        replacement = _replan_gate_fixture(session, path)
        today = today_work_items(session, owner_public_id="learner", course_id="course-a", limit=50)
        assert [item["target_object_id"] for item in today] == ["target-1"]
        schedule = multi_course_schedule(session, owner_public_id="learner", course_id="course-a")
        assert schedule["days"][1]["tasks"][0]["target_object_id"] == "target-2"
        status = exam_gate_status(session, owner_public_id="learner", course_id="course-a")
        assert status["unlocked"] is True
        assert status["required_task_ids"] == [today[0]["node_id"]]
        assert session.query(DBPathNode).filter_by(learning_path_id=replacement.id, target_object_id="target-2").one().status == "pending"
    finally:
        session.close()
        engine.dispose()


def test_self_generated_exam_rechecks_gate_before_start_and_submit(monkeypatch):
    session, engine, path, snapshot = _fixture()
    session.get(DBCourse, "course-a").status = "published"
    session.add(DBSourceDocument(
        id="gate-report-source", course_id="course-a", title="测评资料", filename="exam.md",
        file_format="md", content_hash="1" * 64, processing_status="ready",
    ))
    learner = session.query(DBUser).filter_by(public_id="learner").one()
    teacher = session.query(DBUser).filter_by(public_id="teacher").one()
    question, version = create_question_version(
        session,
        owner_public_id=teacher.public_id,
        course_id="course-a",
        question_type="single_choice",
        origin="manual",
        version=QuestionVersionInput(
            prompt="门禁复检题",
            options=("A. 错误", "B. 正确"),
            answer_key={"choice": "B"},
            scoring_rule={"type": "exact", "version": "objective-v1"},
        ),
    )
    question.status = "approved"
    required = session.get(DBPathNode, "required-2")
    required.status = "completed"
    completion = _complete(
        session,
        "required-2",
        "target-2",
        datetime.fromisoformat(snapshot["assigned_at"].removesuffix("Z")) + timedelta(minutes=2),
    )
    path.status = "completed"
    path.completed_at = datetime.utcnow()
    session.commit()

    async def fake_run_db_op(operation):
        return operation(session)

    monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: learner
    client = TestClient(app)
    try:
        created = client.post("/api/v1/m5/assessment/intelligent-exams", json={
            "course_id": "course-a",
            "title": "门禁复检试卷",
            "duration_minutes": 30,
            "question_version_ids": [version.id],
        })
        assert created.status_code == 201, created.text
        sitting = created.json()["sitting"]

        completion.evidence_status = "rejected"
        completion.mastery_eligible = False
        completion.completion_effect = "none"
        session.commit()
        denied_start = client.post(
            f"/api/v1/m5/assessment/exam-sittings/{sitting['id']}/start",
            json={"expected_lock_version": sitting["lock_version"]},
        )
        assert denied_start.status_code == 409
        assert denied_start.json()["detail"]["code"] == "exam_gate.locked"

        completion.evidence_status = "accepted"
        completion.mastery_eligible = True
        completion.completion_effect = "complete"
        session.commit()
        started = client.post(
            f"/api/v1/m5/assessment/exam-sittings/{sitting['id']}/start",
            json={"expected_lock_version": sitting["lock_version"]},
        )
        assert started.status_code == 200, started.text
        answered = client.post(
            f"/api/v1/m5/assessment/exam-sittings/{sitting['id']}/responses",
            json={
                "exam_item_id": created.json()["items"][0]["id"],
                "idempotency_key": "f4-gate-recheck-answer",
                "answer": {"choice": "B"},
            },
        )
        assert answered.status_code == 201, answered.text

        completion.evidence_status = "rejected"
        completion.mastery_eligible = False
        completion.completion_effect = "none"
        session.commit()
        denied_submit = client.post(
            f"/api/v1/m5/assessment/exam-sittings/{sitting['id']}/submit",
            json={"expected_lock_version": started.json()["lock_version"]},
        )
        assert denied_submit.status_code == 409
        assert denied_submit.json()["detail"]["code"] == "exam_gate.locked"

        completion.evidence_status = "accepted"
        completion.mastery_eligible = True
        completion.completion_effect = "complete"
        session.commit()
        submitted = client.post(
            f"/api/v1/m5/assessment/exam-sittings/{sitting['id']}/submit",
            json={"expected_lock_version": started.json()["lock_version"]},
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["sitting"]["status"] in {"submitted", "released"}

        # A later day's tasks (or revoked prior evidence) must not hide an
        # already submitted result, nor create another score on report reopen.
        completion.evidence_status = "rejected"
        completion.mastery_eligible = False
        completion.completion_effect = "none"
        session.commit()
        with pytest.raises(ExamGateError):
            require_exam_gate(session, owner_public_id="learner", course_id="course-a")
        report = client.post(f"/api/v1/m5/assessment/exam-sittings/{sitting['id']}/reports")
        assert report.status_code == 200, report.text
        assert report.json()["report"]["final_ratio"] == 1.0
        again = client.post(f"/api/v1/m5/assessment/exam-sittings/{sitting['id']}/reports")
        assert again.status_code == 200, again.text
        assert again.json()["id"] == report.json()["id"]
        assert session.query(DBLearningEvent).filter_by(
            owner_public_id="learner", idempotency_key=f"formal-exam-submission:{sitting['id']}",
        ).count() == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close()
        engine.dispose()


def test_locked_gate_rejects_new_exam_but_keeps_historical_exam_visible(monkeypatch):
    session, engine, _, _ = _fixture()
    learner = session.query(DBUser).filter_by(public_id="learner").one()
    teacher = session.query(DBUser).filter_by(public_id="teacher").one()
    question, version = create_question_version(
        session,
        owner_public_id=teacher.public_id,
        course_id="course-a",
        question_type="single_choice",
        origin="manual",
        version=QuestionVersionInput(
            prompt="请选择正确答案",
            options=("A. 错误", "B. 正确"),
            answer_key={"choice": "B"},
            scoring_rule={"type": "exact", "version": "objective-v1"},
        ),
    )
    question.status = "approved"
    historical, _, _ = create_exam(
        session,
        owner_public_id=teacher.public_id,
        payload=ExamCreateInput(
            course_id="course-a",
            title="历史试卷",
            items=(ExamItemInput(question_version_id=version.id, points=100),),
        ),
    )
    transition_exam(session, exam=historical, target="published", expected_lock_version=1, actor_public_id=teacher.public_id)
    assign_sitting(session, exam=historical, learner_public_id=learner.public_id, actor_public_id=teacher.public_id)
    session.commit()

    async def fake_run_db_op(operation):
        return operation(session)

    monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: learner
    client = TestClient(app)
    try:
        rejected = client.post("/api/v1/m5/assessment/intelligent-exams", json={
            "course_id": "course-a",
            "title": "绕过门禁",
            "duration_minutes": 30,
            "question_version_ids": [version.id],
        })
        assert rejected.status_code == 409
        assert rejected.json()["detail"]["code"] == "exam_gate.locked"

        catalog = client.get("/api/v1/m5/assessment/exams")
        assert catalog.status_code == 200
        assert [item["title"] for item in catalog.json()["items"]] == ["历史试卷"]
        detail = client.get(f"/api/v1/m5/assessment/exams/{historical.id}")
        assert detail.status_code == 200

        with pytest.raises(ExamGateError, match="今日全部必做任务"):
            require_exam_gate(session, owner_public_id="learner", course_id="course-a")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close()
        engine.dispose()


def test_f4_assessment_pages_keep_center_boundary_and_student_split_layout():
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    assessment = (root / "frontend/src/views/AssessmentWorkspace.vue").read_text(encoding="utf-8")
    exam = (root / "frontend/src/views/FormalExamWorkspace.vue").read_text(encoding="utf-8")
    path = (root / "frontend/src/views/LearningPathGraph.vue").read_text(encoding="utf-8")

    assert 'data-testid="assessment-center"' in assessment
    assert 'data-testid="entry-diagnostic"' in assessment
    assert 'data-testid="intelligent-exam-entry"' in assessment
    assert "route.name === 'AssessmentCenter' && !blueprintId.value" in assessment
    assert "测验题资源属于学习空间" in assessment
    assert 'data-testid="exam-gate-locked"' in exam
    assert 'data-testid="exam-builder-unlocked"' in exam
    assert 'data-testid="exam-preview"' in exam
    assert "grid-template-columns:minmax(340px,35fr) minmax(0,65fr)" in exam
    assert "完成下方练习并提交结果后，即可开始组卷" in exam
    assert "先建立本课程的学习路径" in exam
    assert "当前没有可用于组卷的学习任务" in exam
    assert 'v-if="requiredCount || missingTaskCount"' in exam
    assert "历史试卷与报告" in exam
    assert "font-size:8px" not in exam
    assert "font-size:9px" not in exam
    assert "font-size:10px" not in exam
    assert "#3e674b" not in exam
    assert "path_id: task.path_id" in path
    assert "task_id: task.node_id || task.id" in path


def test_review_exam_context_uses_owned_course_scoped_task_without_unlocking_normal_exam(monkeypatch):
    session, engine, _, _ = _fixture()
    try:
        session.query(DBCourse).filter_by(id="course-a").one().status = "published"
        source = DBSourceDocument(id="review-source", course_id="course-a", title="课程资料", filename="review.md", file_format="md", content_hash="a" * 64)
        chapter = DBChapter(id="review-chapter", course_id="course-a", source_document_id=source.id, stable_key="review", title="循环", position=1)
        point = DBKnowledgePoint(id="review-point", domain_pack="test", code="loop", version="1", title="循环")
        plan = DBReviewPlan(student_id="f4-gate-learner", course_id="course-a", knowledge_point_id=point.id, concept=point.title)
        session.add_all([source, chapter, point, plan])
        session.flush()
        session.add(DBChapterKnowledgePoint(chapter_id=chapter.id, knowledge_point_id=point.id))
        session.commit()
        actor = session.query(DBUser).filter_by(public_id="learner").one()
        async def operation(callback):
            return callback(session)
        monkeypatch.setattr(m5_api, "run_db_op", operation)
        app.dependency_overrides[get_current_user] = lambda: actor
        with TestClient(app) as client:
            ordinary = client.get('/api/v1/m5/assessment/intelligent-exams/context', params={"course_id": "course-a"})
            assert ordinary.status_code == 200, ordinary.text
            assert ordinary.json()["gate"]["unlocked"] is False
            review = client.get('/api/v1/m5/assessment/intelligent-exams/context', params={"course_id": "course-a", "review_task_id": f"review-plan:{plan.id}"})
            assert review.status_code == 200, review.text
            assert review.json()["gate"]["unlocked"] is True
            assert [item["id"] for item in review.json()["knowledge_points"]] == [point.id]
            from app.m5_exam_core import FormalExamError
            with pytest.raises(FormalExamError):
                m5_api._review_exam_scope(session, actor, f"review-plan:{plan.id}", "course-b")
            with pytest.raises(FormalExamError):
                m5_api._review_exam_scope(session, actor, "review-plan:99999", "course-a")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close()
        engine.dispose()
