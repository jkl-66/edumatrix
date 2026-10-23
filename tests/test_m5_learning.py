from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import (
    Base,
    DBAssessmentQuestion,
    DBAssessmentQuestionVersion,
    DBChapter,
    DBCourse,
    DBLearningEvent,
    DBLearningPath,
    DBPathNode,
    DBPlanDraft,
    DBSourceDocument,
)
from app.m5_learning import (
    LearningEventInput,
    M5LearningError,
    PlanNodeSpec,
    PlanSpec,
    confirm_plan,
    create_plan_draft,
    process_path_event,
    propose_plan_revision,
    record_learning_event,
    today_work_items,
    multi_course_schedule,
    transition_path,
    _mastery_state,
)


OWNER = "usr-m5-learning"
COURSE = "course-m5-learning"


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(DBCourse(
        id=COURSE, version="1", title="M5 Learning", manifest_version="1",
    ))
    session.add(DBSourceDocument(
        id="src-m5-learning", course_id=COURSE, title="Source", filename="source.md",
        file_format="md", content_hash="a" * 64,
    ))
    session.add_all([
        DBChapter(
            id="chapter-1", course_id=COURSE, source_document_id="src-m5-learning",
            stable_key="chapter-1", title="Chapter 1", position=1,
        ),
        DBChapter(
            id="chapter-2", course_id=COURSE, source_document_id="src-m5-learning",
            stable_key="chapter-2", title="Chapter 2", position=2,
        ),
    ])
    session.flush()
    return session


def _node(key, target, *, prerequisites=()):
    return PlanNodeSpec(
        node_key=key, node_type="chapter", target_object_id=target,
        title=key, prerequisites=prerequisites, resource_status="existing",
        estimate_min_minutes=10, estimate_max_minutes=20,
    )


def _spec(*nodes, goal="Finish the course"):
    return PlanSpec(goal=goal, nodes=nodes or (_node("node-1", "chapter-1"),))


def _draft(session, key="plan-key-001", spec=None):
    return create_plan_draft(
        session, owner_public_id=OWNER, course_id=COURSE, title="My plan",
        idempotency_key=key, spec=spec or _spec(),
    )


def _event(key, event_type, object_id="chapter-1", payload=None, source="frontend"):
    return LearningEventInput(
        idempotency_key=key, event_type=event_type, course_id=COURSE,
        object_type="chapter", object_id=object_id, source=source,
        occurred_at=datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc),
        payload=payload or {},
    )


def test_draft_is_idempotent_and_does_not_create_path():
    session = _session()
    plan, version, created = _draft(session)
    replay, replay_version, replay_created = _draft(session)

    assert created is True and replay_created is False
    assert replay.id == plan.id and replay_version.id == version.id
    assert session.query(DBLearningPath).count() == 0
    with pytest.raises(M5LearningError, match="another plan draft"):
        _draft(session, spec=_spec(goal="Changed goal"))


def test_plan_targets_require_course_membership_or_explicit_extension():
    session = _session()
    with pytest.raises(M5LearningError, match="confirmed course"):
        _draft(session, spec=_spec(_node("bad-node", "missing-chapter")))

    extension = PlanNodeSpec(
        node_key="ext-node", node_type="extension", title="External practice",
        resource_status="external_dependency", estimate_min_minutes=5,
        estimate_max_minutes=15, extension_reason="Needed for the learner goal",
    )
    plan, _, created = _draft(session, key="extension-key", spec=_spec(extension))
    assert created is True and plan.status == "draft"


def test_confirmation_revision_diff_and_lineage_replacement():
    session = _session()
    original = _spec(
        _node("node-1", "chapter-1"),
        _node("node-2", "chapter-2", prerequisites=("node-1",)),
    )
    plan, _, _ = _draft(session, spec=original)
    first_path = confirm_plan(
        session, plan=plan, owner_public_id=OWNER, expected_lock_version=1,
    )
    assert first_path.status == "active"
    assert session.query(DBPathNode).filter_by(learning_path_id=first_path.id).count() == 2

    revised = _spec(
        _node("node-2", "chapter-2"),
        _node("node-3", "chapter-1", prerequisites=("node-2",)),
    )
    _, diff = propose_plan_revision(
        session, plan=plan, owner_public_id=OWNER,
        expected_lock_version=2, spec=revised,
    )
    assert diff["added"] == ["node-3"]
    assert diff["removed"] == ["node-1"]
    assert diff["moved"] == ["node-2"]

    replacement = confirm_plan(
        session, plan=plan, owner_public_id=OWNER, expected_lock_version=3,
    )
    assert replacement.supersedes_path_id == first_path.id
    assert first_path.status == "archived"
    assert plan.confirmed_version_id == plan.current_version_id


def test_path_pause_resume_locking_and_no_manual_completion():
    session = _session()
    plan, _, _ = _draft(session)
    path = confirm_plan(session, plan=plan, owner_public_id=OWNER, expected_lock_version=1)

    transition_path(
        session, path=path, owner_public_id=OWNER,
        target_status="paused", expected_lock_version=1,
    )
    with pytest.raises(M5LearningError, match="lock version changed"):
        transition_path(
            session, path=path, owner_public_id=OWNER,
            target_status="active", expected_lock_version=1,
        )
    transition_path(
        session, path=path, owner_public_id=OWNER,
        target_status="active", expected_lock_version=2,
    )
    with pytest.raises(M5LearningError, match="cannot transition"):
        transition_path(
            session, path=path, owner_public_id=OWNER,
            target_status="completed", expected_lock_version=3,  # type: ignore[arg-type]
        )


def test_events_are_idempotent_and_only_strong_unblocked_evidence_completes():
    session = _session()
    spec = _spec(
        _node("node-1", "chapter-1"),
        _node("node-2", "chapter-2", prerequisites=("node-1",)),
    )
    plan, _, _ = _draft(session, spec=spec)
    path = confirm_plan(session, plan=plan, owner_public_id=OWNER, expected_lock_version=1)

    opened, created = record_learning_event(
        session, owner_public_id=OWNER, event=_event("event-open-001", "resource_opened"),
    )
    replay, replay_created = record_learning_event(
        session, owner_public_id=OWNER, event=_event("event-open-001", "resource_opened"),
    )
    assert created is True and replay_created is False and replay.id == opened.id
    first_consumption = process_path_event(session, event=opened)
    assert first_consumption.result["new_status"] == "in_progress"
    assert process_path_event(session, event=opened).id == first_consumption.id

    marked, _ = record_learning_event(
        session, owner_public_id=OWNER,
        event=_event("event-mark-001", "user_marked_complete"),
    )
    assert process_path_event(session, event=marked).result["new_status"] == "in_progress"

    blocked, _ = record_learning_event(
        session, owner_public_id=OWNER,
        trusted_source=True,
        event=_event(
            "event-strong-002", "delayed_retest_passed", "chapter-2",
            {"correct": True, "delay_hours": 24, "attempt_id": "attempt-blocked"},
            "backend",
        ),
    )
    assert process_path_event(session, event=blocked).result["prerequisite_blocked"] is True

    passed, _ = record_learning_event(
        session, owner_public_id=OWNER, trusted_source=True,
        event=_event(
            "event-strong-001", "code_tests_passed",
            payload={
                "passed_count": 2, "total_count": 2,
                "test_scope": "hidden", "run_id": "run-strong-001",
            },
            source="sandbox",
        ),
    )
    process_path_event(session, event=passed)
    passed_second, _ = record_learning_event(
        session, owner_public_id=OWNER, trusted_source=True,
        event=_event(
            "event-strong-003", "teacher_confirmed", "chapter-2",
            {"scope": "chapter", "teacher_public_id": "usr-teacher"},
            "teacher",
        ),
    )
    process_path_event(session, event=passed_second)
    assert path.status == "completed"

    with pytest.raises(M5LearningError, match="different data"):
        record_learning_event(
            session, owner_public_id=OWNER,
            event=_event("event-open-001", "reading_started"),
        )


def test_today_work_excludes_completed_and_prerequisite_blocked_nodes():
    session = _session()
    plan, _, _ = _draft(session, spec=_spec(
        _node("node-1", "chapter-1"),
        _node("node-2", "chapter-2", prerequisites=("node-1",)),
    ))
    path = confirm_plan(session, plan=plan, owner_public_id=OWNER, expected_lock_version=1)
    assert [item["node_key"] for item in today_work_items(session, owner_public_id=OWNER)] == ["node-1"]

    session.query(DBPathNode).filter_by(learning_path_id=path.id, node_key="node-1").one().status = "completed"
    assert [item["node_key"] for item in today_work_items(session, owner_public_id=OWNER)] == ["node-2"]


def test_today_completion_receipt_stays_on_today_and_next_node_waits_for_next_day():
    session = _session()
    session.get(DBCourse, COURSE).status = "published"
    plan, _, _ = _draft(session, spec=_spec(
        _node("node-1", "chapter-1"),
        _node("node-2", "chapter-2", prerequisites=("node-1",)),
    ))
    path = confirm_plan(session, plan=plan, owner_public_id=OWNER, expected_lock_version=1)
    event, _ = record_learning_event(
        session,
        owner_public_id=OWNER,
        trusted_source=True,
        event=LearningEventInput(
            idempotency_key="today-completion-001",
            event_type="code_tests_passed",
            course_id=COURSE,
            object_type="chapter",
            object_id="chapter-1",
            source="sandbox",
            occurred_at=datetime.now(timezone.utc),
            payload={"passed_count": 2, "total_count": 2, "test_scope": "hidden", "run_id": "run-today-001"},
        ),
    )
    process_path_event(session, event=event)

    today = list(today_work_items(session, owner_public_id=OWNER))
    assert [item["node_key"] for item in today] == ["node-1"]
    assert today[0]["status"] == "completed"

    day_one = multi_course_schedule(session, owner_public_id=OWNER, selected_day=1)
    assert [item["node_key"] for item in day_one["selected"]["tasks"]] == ["node-1"]
    assert day_one["selected"]["tasks"][0]["status"] == "completed"
    day_two = multi_course_schedule(session, owner_public_id=OWNER, selected_day=2)
    assert [item["node_key"] for item in day_two["selected"]["tasks"]] == ["node-2"]


def test_plan_assessment_node_requires_a_frozen_available_question_version():
    session = _session()
    question = DBAssessmentQuestion(
        id="assessment-question", owner_public_id=OWNER, course_id=COURSE,
        question_type="single_choice", origin="manual", status="approved",
    )


    session.add(question)
    session.flush()
    version = DBAssessmentQuestionVersion(
        id="assessment-version", question_id=question.id, version_number=1,
        prompt="Choose B", options=["A", "B"], answer_key={"choice": "B"},
        scoring_rule={"type": "exact"}, content_hash="d" * 64,
        created_by_public_id=OWNER,
    )
    session.add(version)
    session.flush()
    question.current_version_id = version.id
    assessment = PlanNodeSpec(
        node_key="assessment-node", node_type="assessment", target_object_id=version.id,
        title="Delayed retest", resource_status="existing",
        estimate_min_minutes=5, estimate_max_minutes=10,
    )
    plan, _, created = _draft(session, key="assessment-plan", spec=_spec(assessment))
    assert created is True and plan.status == "draft"
    bad = assessment.model_copy(update={"target_object_id": "missing-version"})
    with pytest.raises(M5LearningError, match="assessment version is unavailable"):
        _draft(session, key="assessment-plan-bad", spec=_spec(bad))


def test_weak_flag_overrides_contradictory_known_label_for_path_projection():
    profile = {
        "mastery": {"kp-weak": {"status": "known", "score": 0.0, "evidence_item_count": 1, "source_ref_ids": ["ref-1"]}},
        "weak_ids": {"kp-weak"}, "mastered_ids": set(), "unknown_ids": set(),
    }
    assert _mastery_state("kp-weak", profile=profile)[0] == "weak"


def test_known_label_without_high_score_does_not_skip_path_node():
    profile = {
        "mastery": {"kp-developing": {"status": "known", "score": 0.35, "evidence_item_count": 2, "source_ref_ids": ["ref-1"]}},
        "weak_ids": set(), "mastered_ids": set(), "unknown_ids": set(),
    }
    assert _mastery_state("kp-developing", profile=profile)[0] == "developing"

