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
    DBTaskEvent,
    DBUser,
    DBSourceDocument,
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


def test_server_freezes_required_path_tasks_and_ignores_optional_extensions():
    session, engine, _, _ = _fixture()
    try:
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


def test_gate_matches_completion_event_to_chapter_knowledge_point_when_node_projection_lags():
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


def test_self_generated_exam_rechecks_gate_before_start_and_submit(monkeypatch):
    session, engine, path, snapshot = _fixture()
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
    assert "可选资源不会阻塞解锁" in exam
    assert "历史试卷与报告" in exam
    assert "font-size:8px" not in exam
    assert "font-size:9px" not in exam
    assert "font-size:10px" not in exam
    assert "#3e674b" not in exam
    assert "path_id: task.path_id" in path
    assert "task_id: task.node_id || task.id" in path
