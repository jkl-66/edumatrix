from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.database import (
    Base,
    DBAssessmentQuestion,
    DBAssessmentQuestionVersion,
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
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
    DBStudentProfile,
    DBUser,
    DBWrongQuestion,
)
from app.learning_aggregation import (
    AGGREGATION_STEPS,
    _STEP_HANDLERS,
    aggregate_learning_event,
)
import app.m5_api as m5_api
from app.migrations import _install_f2_replayable_aggregation


OWNER = "usr-f2-aggregation-owner"
OTHER = "usr-f2-aggregation-other"
COURSE = "course-f2-aggregation"
CONCEPT = "Gradient Descent"
BASE_TIME = datetime(2026, 8, 12, 1, 0)


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    owner = DBUser(
        public_id=OWNER,
        username="f2-aggregation-owner",
        hashed_password="hash",
        role="student",
    )
    other = DBUser(
        public_id=OTHER,
        username="f2-aggregation-other",
        hashed_password="hash",
        role="student",
    )
    course = DBCourse(
        id=COURSE,
        owner_public_id=OWNER,
        version="1",
        title="F2 Aggregation Course",
        visibility="private",
        status="published",
        manifest_version="1",
    )
    profile = DBStudentProfile(
        student_id=owner.username,
        concept_mastery={CONCEPT: 0.4},
    )
    point = DBKnowledgePoint(
        id="kp-gradient-descent",
        domain_pack="machine-learning",
        code="gradient_descent",
        version="1",
        title=CONCEPT,
    )
    question = DBAssessmentQuestion(
        id="question-f2-aggregation",
        owner_public_id=OWNER,
        course_id=COURSE,
        question_type="single_choice",
        origin="manual",
        status="approved",
    )
    session.add_all([owner, other, course, profile, point, question])
    session.flush()

    wrong_version = DBAssessmentQuestionVersion(
        id="question-version-wrong",
        question_id=question.id,
        version_number=1,
        prompt="Wrong attempt",
        options=["A", "B"],
        answer_key={"choice": "B"},
        scoring_rule={"type": "exact"},
        primary_knowledge_point_id=point.id,
        content_hash="a" * 64,
        created_by_public_id=OWNER,
    )
    correct_version = DBAssessmentQuestionVersion(
        id="question-version-correct",
        question_id=question.id,
        version_number=2,
        prompt="Correct attempt",
        options=["A", "B"],
        answer_key={"choice": "B"},
        scoring_rule={"type": "exact"},
        primary_knowledge_point_id=point.id,
        content_hash="b" * 64,
        created_by_public_id=OWNER,
    )
    session.add_all([wrong_version, correct_version])
    session.flush()
    question.current_version_id = correct_version.id

    plan = DBPlanDraft(
        id="plan-f2-aggregation",
        owner_public_id=OWNER,
        course_id=COURSE,
        title="Aggregation path",
        status="confirmed",
    )
    session.add(plan)
    session.flush()
    version = DBPlanVersion(
        id="plan-version-f2-aggregation",
        plan_draft_id=plan.id,
        version_number=1,
        content={"goal": "Complete the canonical assessment"},
        content_hash="c" * 64,
        created_by_public_id=OWNER,
    )
    session.add(version)
    session.flush()
    plan.current_version_id = version.id
    plan.confirmed_version_id = version.id
    path = DBLearningPath(
        id="path-f2-aggregation",
        owner_public_id=OWNER,
        course_id=COURSE,
        source_plan_version_id=version.id,
        status="active",
    )
    session.add(path)
    session.flush()
    node = DBPathNode(
        id="node-f2-aggregation",
        learning_path_id=path.id,
        node_key="assessment",
        sequence=1,
        node_type="assessment",
        target_object_id=correct_version.id,
        title="Canonical assessment",
        status="pending",
        resource_status="existing",
        estimate_min_minutes=5,
        estimate_max_minutes=10,
    )
    session.add(node)
    session.commit()
    return session, owner, other


def _graded_event(name: str) -> DBLearningEvent:
    correct = name == "correct"
    return DBLearningEvent(
        id=f"event-{name}",
        owner_public_id=OWNER,
        course_id=COURSE,
        event_type="quiz_answered",
        schema_version="m5.learning-event.v2",
        idempotency_key=f"aggregation-{name}",
        source="backend",
        trace_id=f"trace-{name}",
        object_type="assessment_question_version",
        object_id=f"question-version-{name}",
        action="assessment_completed",
        context_ref={"courseId": COURSE, "knowledgePointId": "kp-gradient-descent"},
        evidence_strength=0.8,
        evidence_status="accepted",
        evidence_reason="server graded canonical attempt",
        mastery_eligible=True,
        completion_effect="complete" if correct else "none",
        payload_version="1",
        payload={"graded": True, "correct": correct, "score": 1.0 if correct else 0.0},
        occurred_at=BASE_TIME + (timedelta(minutes=10) if correct else timedelta()),
    )


@pytest.mark.parametrize("quality", [2, 4, 5])
def test_flashcard_familiarity_changes_schedule_without_changing_measured_mastery(quality):
    from app.crud import apply_review_feedback

    session, owner, _ = _session()
    profile = session.get(DBStudentProfile, owner.username)
    profile.weak_points = [CONCEPT]
    session.commit()
    before = dict(profile.concept_mastery)
    plan = apply_review_feedback(session, owner.username, CONCEPT, quality)
    session.refresh(profile)
    assert plan.review_count == 1 and plan.next_review_at is not None
    assert plan.mastery != 0.3
    assert profile.concept_mastery == before
    assert profile.weak_points == [CONCEPT]


@pytest.mark.parametrize("legacy_trace", [False, True])
def test_legacy_self_rating_repair_keeps_grades_and_old_snapshots_and_is_repeatable(legacy_trace):
    from app.learning_aggregation import repair_self_rated_mastery

    session, owner, _ = _session()
    event = _graded_event("correct")
    session.add(event)
    session.flush()
    aggregate_learning_event(session, event=event)
    session.commit()
    profile = session.get(DBStudentProfile, owner.username)
    actual = dict(profile.concept_mastery)
    if legacy_trace:
        trace = dict(profile.knowledge_traces[CONCEPT])
        trace.pop("source_event_id")
        profile.knowledge_traces = {CONCEPT: trace}
    snapshots = {row.id: row.content_hash for row in session.query(DBProfileSnapshot).all()}
    count = session.query(DBLearningEvent).count()
    # Isolated historical fixture: the old flashcard code wrote familiarity
    # directly into mastery while leaving the accepted trace and grade intact.
    profile.concept_mastery = {CONCEPT: 0.34}
    session.add(DBReviewPlan(student_id=owner.username, concept=CONCEPT, mastery=0.34, review_count=1, last_quality=4))
    session.commit()
    assert repair_self_rated_mastery(session) == 1
    session.commit()
    assert profile.concept_mastery == actual
    assert session.query(DBLearningEvent).count() == count
    assert event.payload["score"] == 1.0
    assert all(session.get(DBProfileSnapshot, key).content_hash == value for key, value in snapshots.items())
    correction = session.query(DBProfileSnapshot).filter_by(profile_version="flashcard-score-repair-v1").one()
    assert correction.snapshot["concept_mastery"] == actual
    assert correction.snapshot["source_event_id"] == event.id
    assert repair_self_rated_mastery(session) == 0
    session.commit()
    assert session.query(DBProfileSnapshot).count() == len(snapshots) + 1


def test_self_rating_repair_does_not_guess_without_a_frozen_graded_trace():
    from app.learning_aggregation import repair_self_rated_mastery

    session, owner, _ = _session()
    profile = session.get(DBStudentProfile, owner.username)
    session.add(DBReviewPlan(student_id=owner.username, concept=CONCEPT, mastery=0.4, review_count=1, last_quality=4))
    session.commit()
    assert repair_self_rated_mastery(session) == 0
    assert profile.concept_mastery == {CONCEPT: 0.4}


def test_missed_retests_repair_current_feedback_without_rewriting_old_learning(monkeypatch):
    import app.learning_aggregation as aggregation

    session, owner, _ = _session()
    original_resolver = aggregation._event_concept
    monkeypatch.setattr(aggregation, "_event_concept", lambda db, event:
                        None if event.event_type == "delayed_retest_passed"
                        else original_resolver(db, event))
    events = []
    for index in range(2):
        event = _graded_event("correct")
        event.id = f"delayed-{index}"
        event.idempotency_key = event.id
        event.event_type = "delayed_retest_passed"
        event.object_type = "assessment"
        event.context_ref = {"courseId": COURSE}
        event.payload = {"correct": True, "stable_retest": True, "delay_hours": 24}
        event.occurred_at = BASE_TIME + timedelta(days=1, minutes=index)
        session.add(event)
        session.flush()
        aggregation.aggregate_learning_event(session, event=event)
        events.append(event)
    profile = session.get(DBStudentProfile, owner.username)
    assert profile.concept_mastery == {CONCEPT: 0.4}
    # A later real observation must remain part of the corrected calculation.
    later = _graded_event("correct")
    later.occurred_at = BASE_TIME + timedelta(days=2)
    session.add(later)
    session.flush()
    aggregation.aggregate_learning_event(session, event=later)
    old_mastery = dict(profile.concept_mastery)
    snapshots = {row.id: (row.content_hash, dict(row.snapshot))
                 for row in session.query(DBProfileSnapshot).all()}
    original_events = [(row.id, dict(row.payload), row.occurred_at)
                       for row in session.query(DBLearningEvent).order_by(DBLearningEvent.id)]
    monkeypatch.setattr(aggregation, "_event_concept", original_resolver)
    assert aggregation.repair_delayed_retest_projection(session) == 2
    session.commit()
    corrected_mastery = dict(profile.concept_mastery)
    assert corrected_mastery[CONCEPT] > old_mastery[CONCEPT]
    assert profile.knowledge_traces[CONCEPT]["attempts"] == 3
    assert profile.knowledge_traces[CONCEPT]["source_event_id"] == later.id
    plan = session.query(DBReviewPlan).filter_by(student_id=owner.username).one()
    assert plan.review_count == 2

    assert plan.next_review_at == later.occurred_at + timedelta(days=plan.interval_days)
    correction = session.query(DBProfileSnapshot).filter_by(profile_version="delayed-retest-repair-v1").one()
    assert correction.snapshot["corrected_event_ids"] == [event.id for event in events]
    assert correction.snapshot["concept_mastery"] == corrected_mastery
    feedback = aggregation.get_learning_aggregation(session, event_id=later.id)
    assert feedback.result["steps"]["profile_snapshot"]["profile_snapshot_id"] == correction.id
    assert all(session.get(DBProfileSnapshot, key).content_hash == value[0]
               and session.get(DBProfileSnapshot, key).snapshot == value[1] for key, value in snapshots.items())
    assert [(row.id, dict(row.payload), row.occurred_at)
            for row in session.query(DBLearningEvent).order_by(DBLearningEvent.id)] == original_events
    assert aggregation.repair_delayed_retest_projection(session) == 0
    assert profile.concept_mastery == corrected_mastery
    assert plan.review_count == 2


def test_removed_wrong_question_stays_removed_until_a_new_wrong_answer():
    session, owner, _ = _session()
    wrong = _graded_event("wrong")
    session.add(wrong)
    session.flush()
    aggregate_learning_event(session, event=wrong)
    session.delete(session.query(DBWrongQuestion).one())
    session.commit()
    correct = _graded_event("correct")
    session.add(correct)
    session.flush()
    aggregate_learning_event(session, event=correct)
    assert session.query(DBWrongQuestion).count() == 0
    assert session.get(DBLearningEvent, wrong.id).payload["score"] == 0.0
    aggregate_learning_event(session, event=correct)
    assert session.query(DBWrongQuestion).count() == 0
    wrong_again = _graded_event("wrong")
    wrong_again.id = "wrong-again"
    wrong_again.idempotency_key = "wrong-again"
    wrong_again.occurred_at = BASE_TIME + timedelta(minutes=20)
    session.add(wrong_again)
    session.flush()
    aggregate_learning_event(session, event=wrong_again)
    assert session.query(DBWrongQuestion).one().source_event_id == wrong_again.id


@pytest.mark.parametrize("mastery,weak_ids,expected", [
    ({"status": "known", "score": 0.95, "evidence_item_count": 2}, [], "completed"),
    ({"status": "known", "score": 0.95}, [], "in_progress"),
    ({"status": "unknown", "score": 0.95}, [], "in_progress"),
    ({"status": "known", "score": 0.95, "evidence_item_count": 2}, ["kp-prerequisite"], "in_progress"),
])
@pytest.mark.parametrize("explicit_context", [True, False])
def test_diagnosed_prerequisite_allows_real_completion_without_faking_prior_learning(mastery, weak_ids, expected, explicit_context):
    from app.learning_aggregation import _project_path
    from app.m5_learning import _completed_node_ids_today
    from app.migrations import _repair_path_completion_projection

    session, owner, _ = _session()
    session.add(DBKnowledgePoint(id="kp-prerequisite", domain_pack="test", code="prior", version="1", title="Prior"))
    session.add(DBSourceDocument(id="src-prerequisite", course_id=COURSE, title="Prerequisite source",
                                 filename="source.md", file_format="md", content_hash="d" * 64))
    session.add_all([
        DBChapter(id="chapter-prior", course_id=COURSE, source_document_id="src-prerequisite", stable_key="prior", title="Prior", position=0),
        DBChapter(id="chapter-current", course_id=COURSE, source_document_id="src-prerequisite", stable_key="current", title="Current", position=1),
    ])
    session.flush()
    session.add_all([
        DBChapterKnowledgePoint(chapter_id="chapter-prior", knowledge_point_id="kp-prerequisite"),
        DBChapterKnowledgePoint(chapter_id="chapter-current", knowledge_point_id="kp-gradient-descent"),
        DBPathNode(id="node-prior", learning_path_id="path-f2-aggregation", node_key="prior", sequence=0,
                   node_type="chapter", target_object_id="chapter-prior", title="Prior", status="pending"),
        DBProfileSnapshot(owner_public_id=OWNER, profile_version="diagnostic", trace_id="diagnostic",
            content_hash="e" * 64, snapshot={"course_id": COURSE,
                "mastery_by_knowledge_point": {"kp-prerequisite": mastery}, "weak_knowledge_point_ids": weak_ids}),
    ])
    node = session.get(DBPathNode, "node-f2-aggregation")
    node.node_type = "chapter"
    node.target_object_id = "chapter-current"
    node.prerequisites = ["prior"]
    event = _graded_event("correct")
    if not explicit_context:
        event.context_ref = {"courseId": COURSE}
    event.occurred_at = datetime.utcnow()
    session.add(event)
    session.commit()
    before_mastery = dict(session.query(DBStudentProfile).filter_by(student_id=owner.username).one().concept_mastery)
    _project_path(session, event)
    session.commit()
    assert node.status == expected
    assert session.get(DBPathNode, "node-prior").status == "pending"
    assert _completed_node_ids_today(session, owner_public_id=OWNER, course_id=COURSE, nodes=[node]) == (
        {node.id} if expected == "completed" else set()
    )
    # Repair a previously blocked projection, including idempotent startup replay.
    node.status = "in_progress"
    session.commit()
    with session.bind.begin() as connection:
        _repair_path_completion_projection(connection)
        _repair_path_completion_projection(connection)
    session.expire_all()
    assert node.status == expected
    assert session.query(DBLearningEvent).count() == 1
    assert session.query(DBStudentProfile).filter_by(student_id=owner.username).one().concept_mastery == before_mastery


def _projection(order: tuple[str, ...]) -> dict:
    session, _, _ = _session()
    last_consumption = None
    for name in order:
        event = _graded_event(name)
        session.add(event)
        session.flush()
        last_consumption = aggregate_learning_event(session, event=event)
    profile = session.query(DBStudentProfile).filter_by(student_id="f2-aggregation-owner").one()
    node = session.query(DBPathNode).filter_by(id="node-f2-aggregation").one()
    review = session.query(DBReviewPlan).filter_by(
        student_id=profile.student_id,
        concept=CONCEPT,
    ).one()
    dashboard = dict(last_consumption.result["steps"]["dashboard"]["summary"])
    dashboard.pop("source_event_id", None)
    return {
        "mastery": profile.concept_mastery,
        "weak_points": profile.weak_points,
        "node_status": node.status,
        "wrong_sources": sorted(
            row.source_event_id for row in session.query(DBWrongQuestion).all()
        ),
        "review": (
            review.interval_days,
            review.next_review_at,
            review.mastery,
            review.review_count,
        ),
        "activity_count": dashboard["activity_count"],
        "dashboard": dashboard,
        "snapshot_count": session.query(DBProfileSnapshot).count(),
    }


def test_ordered_and_out_of_order_events_reach_the_same_projection():
    ordered = _projection(("wrong", "correct"))
    out_of_order = _projection(("correct", "wrong"))

    assert ordered == out_of_order
    assert ordered["node_status"] == "completed"
    assert ordered["wrong_sources"] == ["event-wrong"]
    assert ordered["snapshot_count"] == 3


def test_duplicate_event_replay_does_not_duplicate_projection_rows():
    session, _, _ = _session()
    event = _graded_event("wrong")
    session.add(event)
    session.flush()

    first = aggregate_learning_event(session, event=event)
    mastery = dict(session.query(DBStudentProfile).filter_by(
        student_id="f2-aggregation-owner",
    ).one().concept_mastery)
    second = aggregate_learning_event(session, event=event)

    assert second.id == first.id
    assert second.attempt == 1
    assert second.result["completed_steps"] == list(AGGREGATION_STEPS)
    assert session.query(DBWrongQuestion).count() == 1
    assert session.query(DBReviewPlan).count() == 1
    assert session.query(DBProfileSnapshot).count() == 2
    assert session.query(DBStudentProfile).filter_by(
        student_id="f2-aggregation-owner",
    ).one().concept_mastery == mastery


@pytest.mark.parametrize("failed_step", AGGREGATION_STEPS)
def test_failed_step_keeps_checkpoint_and_recovery_skips_completed_steps(
    monkeypatch,
    failed_step,
):
    session, _, _ = _session()
    event = _graded_event("wrong")
    session.add(event)
    session.flush()
    original_handler = _STEP_HANDLERS[failed_step]

    def fail_step(_session, _event):
        raise RuntimeError(f"injected {failed_step} failure")

    monkeypatch.setitem(_STEP_HANDLERS, failed_step, fail_step)
    with pytest.raises(RuntimeError, match=f"injected {failed_step} failure"):
        aggregate_learning_event(session, event=event)

    failed = session.query(DBLearningEventConsumption).filter_by(
        learning_event_id=event.id,
        consumer="learning_aggregation",
    ).one()
    completed_before_failure = list(AGGREGATION_STEPS[:AGGREGATION_STEPS.index(failed_step)])
    assert failed.status == "failed"
    assert failed.result["completed_steps"] == completed_before_failure
    assert failed.result["next_step"] == failed_step

    monkeypatch.setitem(_STEP_HANDLERS, failed_step, original_handler)

    def completed_step_must_not_run(_session, _event):
        raise AssertionError("a completed aggregation step ran again")

    for completed_step in completed_before_failure:
        monkeypatch.setitem(_STEP_HANDLERS, completed_step, completed_step_must_not_run)
    recovered = aggregate_learning_event(session, event=event)

    assert recovered.status == "processed"
    assert recovered.attempt == 2
    assert recovered.result["completed_steps"] == list(AGGREGATION_STEPS)
    assert "recovered" in recovered.result["state_history"]
    assert recovered.result["aggregate_status"] == "completed"
    assert session.query(DBProfileSnapshot).count() == 2
    assert session.query(DBWrongQuestion).count() == 1


def test_browser_activity_is_replayed_without_changing_mastery():
    session, _, _ = _session()
    event = DBLearningEvent(
        id="event-browser-open",
        owner_public_id=OWNER,
        course_id=COURSE,
        event_type="resource_opened",
        schema_version="m5.learning-event.v2",
        idempotency_key="aggregation-browser-open",
        source="frontend",
        trace_id="trace-browser-open",
        object_type="knowledge_point",
        object_id="kp-gradient-descent",
        action="resource_opened",
        context_ref={"courseId": COURSE, "knowledgePointId": "kp-gradient-descent"},
        evidence_strength=0.0,
        evidence_status="none",
        evidence_reason="browser activity is not mastery evidence",
        mastery_eligible=False,
        completion_effect="progress",
        payload_version="1",
        payload={},
        occurred_at=BASE_TIME,
    )
    session.add(event)
    session.flush()

    aggregate_learning_event(session, event=event)
    profile = session.query(DBStudentProfile).filter_by(
        student_id="f2-aggregation-owner",
    ).one()

    assert profile.concept_mastery == {CONCEPT: 0.4}
    assert session.query(DBWrongQuestion).count() == 0
    assert session.query(DBReviewPlan).count() == 0


def test_replayable_aggregation_migration_is_repeatable_and_unique():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE learning_events (id VARCHAR(64) PRIMARY KEY)"
        ))
        connection.execute(text(
            "CREATE TABLE wrong_questions (id INTEGER PRIMARY KEY, student_id VARCHAR(64))"
        ))
        _install_f2_replayable_aggregation(connection)
        _install_f2_replayable_aggregation(connection)

        columns = {item["name"] for item in inspect(connection).get_columns("wrong_questions")}
        assert "source_event_id" in columns
        connection.execute(text("INSERT INTO learning_events(id) VALUES ('event-1')"))
        connection.execute(text(
            "INSERT INTO wrong_questions(id,student_id,source_event_id) "
            "VALUES (1,'student','event-1')"
        ))
        with pytest.raises(IntegrityError):
            connection.execute(text(
                "INSERT INTO wrong_questions(id,student_id,source_event_id) "
                "VALUES (2,'student','event-1')"
            ))


def test_aggregation_status_endpoint_is_owner_scoped(monkeypatch):
    session, owner, other = _session()
    event = _graded_event("correct")
    session.add(event)
    session.flush()
    consumption = aggregate_learning_event(session, event=event)

    async def fake_run_db_op(operation):
        return operation(session)

    identity = {"user": owner}
    monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
    app = FastAPI()
    app.include_router(m5_api.router)
    app.dependency_overrides[get_current_user] = lambda: identity["user"]

    with TestClient(app) as client:
        response = client.get(f"/api/v1/m5/learning-events/{event.id}/aggregation")
        assert response.status_code == 200
        assert response.json()["aggregation"]["id"] == consumption.id
        assert response.json()["aggregation"]["result"]["aggregate_status"] == "completed"

        identity["user"] = other
        forbidden = client.get(f"/api/v1/m5/learning-events/{event.id}/aggregation")
        assert forbidden.status_code == 403
