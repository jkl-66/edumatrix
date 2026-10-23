from __future__ import annotations

from datetime import date, datetime, timedelta
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.learning_aggregation as aggregation
import app.m5_api as m5_api
from app.auth import get_current_user
from app.database import (
    Base,
    DBAssessmentAttempt,
    DBAssessmentExam,
    DBAssessmentExamResponseDraft,
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
    DBCourseMembership,
    DBGenerationTask,
    DBKnowledgePoint,
    DBLearningEvent,
    DBLearningEventConsumption,
    DBLearningPath,
    DBPathNode,
    DBPlanDraft,
    DBPlanVersion,
    DBProfileSnapshot,
    DBReviewPlan,
    DBSourceDocument,
    DBSourceRef,
    DBTaskEvent,
    DBUser,
    DBWrongQuestion,
)
from app.m5_assessment_core import QuestionVersionInput, create_question_version
from app.main import app
from app.migrations import apply_registered_migrations


def _add_question(
    session,
    *,
    teacher_id: str,
    question_type: str,
    prompt: str,
    point_id: str,
    source_ref_id: str,
    answer_key: dict,
    scoring_rule: dict,
    options: tuple[str, ...] = (),
):
    question, version = create_question_version(
        session,
        owner_public_id=teacher_id,
        course_id="course-f6",
        question_type=question_type,
        origin="manual",
        version=QuestionVersionInput(
            prompt=prompt,
            options=options,
            answer_key=answer_key,
            scoring_rule=scoring_rule,
            explanation=f"Explanation for {prompt}",
            misconception_tags=(f"gap-{point_id}",),
            primary_knowledge_point_id=point_id,
            expert_difficulty=0.5,
            source_ref_ids=(source_ref_id,),
        ),
    )
    question.status = "approved"
    return version


def _fixture():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    assert apply_registered_migrations(engine)
    assert apply_registered_migrations(engine) == []
    session = sessionmaker(bind=engine)()
    teacher = DBUser(
        public_id="teacher-f6",
        username="teacher-f6",
        hashed_password="x",
        role="teacher",
        is_active=True,
    )
    learner = DBUser(
        public_id="learner-f6",
        username="learner-f6",
        hashed_password="x",
        role="student",
        is_active=True,
    )
    course = DBCourse(
        id="course-f6",
        version="1",
        title="F6 deterministic course",
        visibility="private",
        status="published",
        manifest_version="1",
        owner_public_id=teacher.public_id,
    )
    session.add_all([teacher, learner, course])
    session.add_all([
        DBCourseMembership(
            course_id=course.id,
            user_public_id=teacher.public_id,
            role="teacher",
            status="active",
        ),
        DBCourseMembership(
            course_id=course.id,
            user_public_id=learner.public_id,
            role="student",
            status="active",
        ),
    ])
    document = DBSourceDocument(
        id="source-f6",
        course_id=course.id,
        title="Frozen textbook",
        filename="course.md",
        file_format="md",
        content_hash="a" * 64,
    )
    chapter = DBChapter(
        id="chapter-f6",
        course_id=course.id,
        source_document_id=document.id,
        stable_key="chapter-f6",
        title="Core concepts",
        position=1,
    )
    points = [
        DBKnowledgePoint(
            id="kp-f6-a",
            domain_pack="f6",
            code="concept-a",
            version="1",
            title="Concept A",
            status="active",
        ),
        DBKnowledgePoint(
            id="kp-f6-b",
            domain_pack="f6",
            code="concept-b",
            version="1",
            title="Concept B",
            status="active",
        ),
    ]
    session.add_all([document, chapter, *points])
    session.flush()
    session.add_all([
        DBChapterKnowledgePoint(
            id="chapter-point-f6-a",
            chapter_id=chapter.id,
            knowledge_point_id=points[0].id,
            relation_type="teaches",
        ),
        DBChapterKnowledgePoint(
            id="chapter-point-f6-b",
            chapter_id=chapter.id,
            knowledge_point_id=points[1].id,
            relation_type="teaches",
        ),
    ])
    refs = [DBSourceRef(
        id="source-ref-f6",
        source_document_id=document.id,
        chapter_id=chapter.id,
        parser_version="1",
        location_kind="section",
        location_label="Core concepts section",
        quote="Frozen source excerpt for concepts A and B.",
        content_hash="b" * 64,
    )]
    session.add_all(refs)
    session.flush()
    _add_question(
        session,
        teacher_id=teacher.public_id,
        question_type="single_choice",
        prompt="Choose B for concept A",
        point_id=points[0].id,
        source_ref_id=refs[0].id,
        options=("A", "B"),
        answer_key={"choice": "B"},
        scoring_rule={"type": "exact", "version": "objective-v1"},
    )
    _add_question(
        session,
        teacher_id=teacher.public_id,
        question_type="single_choice",
        prompt="Choose B for concept B",
        point_id=points[1].id,
        source_ref_id=refs[0].id,
        options=("A", "B"),
        answer_key={"choice": "B"},
        scoring_rule={"type": "exact", "version": "objective-v1"},
    )
    _add_question(
        session,
        teacher_id=teacher.public_id,
        question_type="true_false",
        prompt="Concept A is in the frozen course",
        point_id=points[0].id,
        source_ref_id=refs[0].id,
        answer_key={"value": True},
        scoring_rule={"type": "exact", "version": "objective-v1"},
    )
    _add_question(
        session,
        teacher_id=teacher.public_id,
        question_type="short_answer",
        prompt="Explain the key relation in concept B",
        point_id=points[1].id,
        source_ref_id=refs[0].id,
        answer_key={"reference_answer": "Concept B links input evidence to a deterministic result."},
        scoring_rule={
            "version": "rubric-v1",
            "correct_threshold": 0.6,
            "criteria": [{"id": "coverage", "label": "Key concept coverage", "weight": 1.0}],
        },
    )

    plan = DBPlanDraft(
        id="plan-f6",
        owner_public_id=learner.public_id,
        course_id=course.id,
        title="Today plan",
        status="confirmed",
        idempotency_key="plan-f6-key",
    )
    session.add(plan)
    session.flush()
    plan_version = DBPlanVersion(
        id="plan-version-f6",
        plan_draft_id=plan.id,
        version_number=1,
        content={"schema_version": "m5.plan.v1", "goal": "Finish today", "nodes": []},
        content_hash="d" * 64,
    )
    session.add(plan_version)
    session.flush()
    path = DBLearningPath(
        id="path-f6",
        owner_public_id=learner.public_id,
        course_id=course.id,
        source_plan_version_id=plan_version.id,
        status="active",
    )
    session.add(path)
    session.flush()
    node = DBPathNode(
        id="today-required-f6",
        learning_path_id=path.id,
        node_key="today-required-f6",
        sequence=1,
        node_type="assessment",
        target_object_id="today-target-f6",
        title="Required prerequisite task",
        status="completed",
        prerequisites=[],
        is_extension=False,
        resource_status="existing",
        estimate_min_minutes=10,
        estimate_max_minutes=15,
    )
    session.add(node)
    session.flush()
    assigned_at = datetime.utcnow() - timedelta(minutes=10)
    snapshot = {
        "schema_version": "f4.intelligent-exam-gate.v1",
        "assignment_date": date.today().isoformat(),
        "assigned_at": assigned_at.isoformat() + "Z",
        "course_id": course.id,
        "path_id": path.id,
        "path_version_id": plan_version.id,
        "selected_task_id": node.id,
        "required_tasks": [{
            "id": node.id,
            "node_key": node.node_key,
            "title": node.title,
            "node_type": node.node_type,
            "target_object_id": node.target_object_id,
            "completion_criteria": "Server accepted evidence",
            "route": f"/workspace/path?course_id={course.id}&node_id={node.id}",
        }],
        "optional_task_ids": [],
    }
    task = DBGenerationTask(
        id="generation-f6",
        owner_public_id=learner.public_id,
        course_id=course.id,
        trace_id="generation-f6-trace",
        status="completed",
        progress=1,
        capability="learning_resource_bundle.generate",
        idempotency_key="generation-f6-key",
    )
    session.add(task)
    session.flush()
    session.add(DBTaskEvent(
        id="generation-f6-requested",
        task_id=task.id,
        sequence=1,
        event_type="resource_generation.requested",
        payload={"manifest": {"exam_gate": snapshot}},
    ))
    completion = DBLearningEvent(
        id="gate-completion-f6",
        owner_public_id=learner.public_id,
        course_id=course.id,
        event_type="quiz_answered",
        schema_version="m5.learning-event.v1",
        idempotency_key="gate-completion-f6-key",
        source="backend",
        trace_id="gate-completion-f6-trace",
        object_type="path_target",
        object_id=node.target_object_id,
        action="assessment.answered",
        context_ref={"userId": learner.public_id, "courseId": course.id, "taskId": node.id},
        evidence_strength=0.8,
        evidence_status="accepted",
        evidence_reason="server graded evidence",
        mastery_eligible=True,
        completion_effect="complete",
        payload_version="1",
        payload={"graded": True, "correct": True, "attempt_id": "gate-attempt-f6"},
        occurred_at=assigned_at + timedelta(minutes=1),
    )
    session.add(completion)
    session.commit()
    return session, engine, learner, completion


def _configuration(key: str = "f6-exam-generation-key") -> dict:
    return {
        "idempotency_key": key,
        "course_id": "course-f6",
        "title": "Contextual formal exam",
        "theme": "Core concept verification",
        "duration_minutes": 30,
        "chapter_ids": ["chapter-f6"],
        "knowledge_point_ids": ["kp-f6-a", "kp-f6-b"],
        "difficulty": "balanced",
        "question_type_counts": {
            "single_choice": 2,
            "true_false": 1,
            "short_answer": 1,
        },
        "source_limit": 1,
    }


def _demo_configuration(key: str = "f6-exam-generation-key") -> dict:
    """Use only objectively gradable items in the explicit local demo mode."""
    configuration = _configuration(key)
    configuration["question_type_counts"] = {
        "single_choice": 2,
        "true_false": 1,
        "fill_blank": 1,
    }
    return configuration


def test_f6_t06_contextual_exam_drafts_submission_and_recovery(monkeypatch):
    session, engine, learner, completion = _fixture()

    monkeypatch.setattr(
        m5_api,
        "CONFIG",
        replace(
            m5_api.CONFIG,
            demo_mode=True,
            llm_provider="deterministic",
            llm_model="deterministic",
        ),
    )

    async def fake_run_db_op(operation):
        return operation(session)

    monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
    monkeypatch.setattr(
        m5_api,
        "_call_quiz_model",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("external model must not run")),
    )
    app.dependency_overrides[get_current_user] = lambda: learner
    client = TestClient(app)
    try:
        completion.evidence_status = "rejected"
        completion.mastery_eligible = False
        completion.completion_effect = "none"
        session.commit()
        locked = client.post(
            "/api/v1/m5/assessment/intelligent-exams",
            json={"configuration": _demo_configuration("f6-locked-generation-key")},
        )
        assert locked.status_code == 409
        assert locked.json()["detail"]["code"] == "exam_gate.locked"
        assert session.query(DBAssessmentExam).count() == 0

        completion.evidence_status = "accepted"
        completion.mastery_eligible = True
        completion.completion_effect = "complete"
        session.commit()
        context = client.get(
            "/api/v1/m5/assessment/intelligent-exams/context",
            params={"course_id": "course-f6"},
        )
        assert context.status_code == 200, context.text
        assert context.json()["external_model_required"] is False
        assert context.json()["llm_generation_required"] is False
        assert context.json()["approved_question_count"] == 4
        assert context.json()["gate"]["unlocked"] is True

        created = client.post(
            "/api/v1/m5/assessment/intelligent-exams",
            json={"configuration": _demo_configuration()},
        )
        assert created.status_code == 201, created.text
        created_data = created.json()
        assert created_data["created"] is True
        assert created_data["version"]["coverage"]["question_type_counts"] == {
            "single_choice": 2,
            "fill_blank": 1,
            "true_false": 1,
        }
        assert created_data["version"]["coverage"]["source_ref_count"] == 1
        assert len(created_data["items"]) == 4
        assert all("answer_key" not in item for item in created_data["items"])
        assert all(item["source_refs"] for item in created_data["items"])

        replayed = client.post(
            "/api/v1/m5/assessment/intelligent-exams",
            json={"configuration": _demo_configuration()},
        )
        assert replayed.status_code == 201
        assert replayed.json()["id"] == created_data["id"]
        assert replayed.json()["created"] is False
        conflict_config = _demo_configuration()
        conflict_config["theme"] = "Different theme"
        conflict = client.post(
            "/api/v1/m5/assessment/intelligent-exams",
            json={"configuration": conflict_config},
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "intelligent_exam_idempotency_conflict"

        sitting = created_data["sitting"]
        started = client.post(
            f"/api/v1/m5/assessment/exam-sittings/{sitting['id']}/start",
            json={"expected_lock_version": sitting["lock_version"]},
        )
        assert started.status_code == 200, started.text
        first_item = created_data["items"][0]
        first_save = client.post(
            f"/api/v1/m5/assessment/exam-sittings/{sitting['id']}/responses",
            json={
                "exam_item_id": first_item["id"],
                "idempotency_key": "f6-answer-first-revision",
                "answer": {"choice": "A"},
            },
        )
        assert first_save.status_code == 201, first_save.text
        stored_draft = session.query(DBAssessmentExamResponseDraft).filter_by(
            id=first_save.json()["draft"]["id"],
        ).one()
        stored_draft.answer = {"choice": "B"}
        with pytest.raises(Exception, match="immutable"):
            session.commit()
        session.rollback()
        second_save = client.post(
            f"/api/v1/m5/assessment/exam-sittings/{sitting['id']}/responses",
            json={
                "exam_item_id": first_item["id"],
                "idempotency_key": "f6-answer-second-revision",
                "answer": {"choice": "B"},
            },
        )
        assert second_save.status_code == 201
        assert second_save.json()["draft"]["revision"] == 2
        replay_save = client.post(
            f"/api/v1/m5/assessment/exam-sittings/{sitting['id']}/responses",
            json={
                "exam_item_id": first_item["id"],
                "idempotency_key": "f6-answer-second-revision",
                "answer": {"choice": "B"},
            },
        )
        assert replay_save.status_code == 201
        assert replay_save.json()["created"] is False

        for item in created_data["items"][1:]:
            if item["question_type"] == "single_choice":
                answer = {"choice": "A"}
            elif item["question_type"] == "true_false":
                answer = {"value": True}
            elif item["question_type"] == "fill_blank":
                answer = {"blanks": ["Unrelated response"]}
            else:
                answer = {"text": "Unrelated response"}
            saved = client.post(
                f"/api/v1/m5/assessment/exam-sittings/{sitting['id']}/responses",
                json={
                    "exam_item_id": item["id"],
                    "idempotency_key": f"f6-answer-{item['id']}",
                    "answer": answer,
                },
            )
            assert saved.status_code == 201, saved.text

        detail = client.get(f"/api/v1/m5/assessment/exams/{created_data['id']}")
        assert detail.status_code == 200
        drafts = {item["exam_item_id"]: item for item in detail.json()["drafts"]}
        assert drafts[first_item["id"]]["answer"] == {"choice": "B"}
        assert drafts[first_item["id"]]["revision"] == 2
        assert session.query(DBAssessmentExamResponseDraft).count() == 5
        assert session.query(DBAssessmentAttempt).count() == 0
        assert session.query(DBLearningEvent).filter_by(event_type="formal_exam_submitted").count() == 0

        original_process = m5_api.process_path_event
        failed_once = {"value": False}

        def fail_during_path_projection(db, *, event):
            if failed_once["value"]:
                return original_process(db, event=event)
            failed_once["value"] = True
            original_handler = aggregation._STEP_HANDLERS["path_task"]

            def fail_path(_session, _event):
                raise RuntimeError("injected path projection failure")

            aggregation._STEP_HANDLERS["path_task"] = fail_path
            try:
                return original_process(db, event=event)
            finally:
                aggregation._STEP_HANDLERS["path_task"] = original_handler

        monkeypatch.setattr(m5_api, "process_path_event", fail_during_path_projection)
        submitted = client.post(
            f"/api/v1/m5/assessment/exam-sittings/{sitting['id']}/submit",
            json={"expected_lock_version": started.json()["lock_version"]},
        )
        assert submitted.status_code == 200, submitted.text
        submitted_data = submitted.json()
        assert submitted_data["recoverable"] is True
        assert submitted_data["aggregation"]["status"] == "failed"
        assert submitted_data["aggregation"]["result"]["completed_steps"] == ["profile_snapshot"]
        assert submitted_data["report"]["report"]["external_model_used"] is False

        monkeypatch.setattr(m5_api, "process_path_event", original_process)
        recovered = client.post(
            f"/api/v1/m5/assessment/exam-sittings/{sitting['id']}/submit",
            json={"expected_lock_version": started.json()["lock_version"]},
        )
        assert recovered.status_code == 200, recovered.text
        recovered_data = recovered.json()
        assert recovered_data["recoverable"] is False
        assert recovered_data["aggregation"]["status"] == "processed"
        assert recovered_data["aggregation"]["result"]["aggregate_status"] == "completed"
        assert recovered_data["feedback_updates"]["profile"] == "completed"
        assert recovered_data["feedback_updates"]["path"] == "completed"
        assert recovered_data["feedback_updates"]["next_day_schedule"]
        assert len(recovered_data["feedback_updates"]["wrong_question_ids"]) == 2
        assert len(recovered_data["feedback_updates"]["review_plans"]) == 2

        report = recovered_data["report"]["report"]
        assert report["pending_item_count"] == 0
        assert report["wrong_question_count"] == 2
        assert len(report["coverage"]) == 2
        assert all(item["correct_answer"] is not None for item in report["items"])
        assert all(item["explanation"] for item in report["items"])
        assert all(item["source_refs"] for item in report["items"])
        assert all("error_reason" in item for item in report["items"])
        wrong_items = [item for item in report["items"] if item["score"] is not None and item["score"] < 0.6]
        assert wrong_items
        assert all("仍需巩固" in item["error_reason"] for item in wrong_items)
        assert all("kp-" not in item["error_reason"].lower() for item in wrong_items)

        submission_events = session.query(DBLearningEvent).filter_by(
            event_type="formal_exam_submitted",
        ).all()
        assert len(submission_events) == 1
        assert len(submission_events[0].payload["knowledge_point_scores"]) == 2
        assert len(submission_events[0].payload["item_results"]) == 4
        assert session.query(DBLearningEventConsumption).filter_by(
            learning_event_id=submission_events[0].id,
        ).count() == 1
        assert session.query(DBWrongQuestion).count() == 2
        assert session.query(DBReviewPlan).count() == 2
        assert session.query(DBProfileSnapshot).filter(
            DBProfileSnapshot.trace_id == submission_events[0].trace_id,
        ).count() == 1
        assert session.query(DBAssessmentAttempt).count() == 4

        report_response = client.get(
            f"/api/v1/m5/assessment/exam-reports/{recovered_data['report']['id']}"
        )
        assert report_response.status_code == 200
        assert report_response.json()["event_id"] == submission_events[0].id
        assert report_response.json()["aggregation"]["status"] == "processed"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close()
        engine.dispose()
