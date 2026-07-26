from __future__ import annotations

from app.database import DBDecisionRecord, DBLearningEvent
from app.m3_decisions import build_m3_decision_comparison, persist_m3_decision_comparison
from app.m3_matching import build_m3_matching_report, persist_m3_matching_report
from tests.test_m3_matching import _prepare


def _event(session, task, **payload):
    row = DBLearningEvent(
        owner_public_id=task.owner_public_id,
        course_id=task.course_id,
        event_type="m3.interactive.acceptance_observed",
        trace_id=task.trace_id,
        object_type="interactive_artifact",
        object_id=f"session-{task.id}",
        payload=payload,
    )
    session.add(row)
    session.flush()
    return row


def test_rule_first_decisions_cover_prerequisite_downgrade_and_advance(db_session_m3):
    session, fixtures = db_session_m3
    observations = [
        {"accuracy": 0.35, "help_requests": 3, "consecutive_failures": 2, "self_reported_difficulty": 5},
        {"accuracy": 0.45, "help_requests": 1, "consecutive_failures": 1, "self_reported_difficulty": 4},
        {"accuracy": 0.95, "help_requests": 0, "hidden_acceptance_passed": True, "delayed_retest_passed": True},
    ]
    expected = ["prerequisite_remediation", "downgrade_explanation", "advance_challenge"]
    comparisons = []
    for fixture, observation, selected in zip(fixtures, observations, expected):
        task = _prepare(session, fixture)
        _event(session, task, **observation)
        report = build_m3_matching_report(session, task_id=task.id, owner_public_id=task.owner_public_id)
        persist_m3_matching_report(session, report=report)
        comparison = build_m3_decision_comparison(session, task_id=task.id, owner_public_id=task.owner_public_id)
        decision, artifact, version, created = persist_m3_decision_comparison(session, comparison=comparison)
        assert created is True
        replay = persist_m3_decision_comparison(session, comparison=comparison)
        assert replay[0].id == decision.id and replay[1].id == artifact.id and replay[2].id == version.id
        assert comparison.selected_decision_type == selected
        comparisons.append(comparison)

    assert session.query(DBDecisionRecord).count() == 3
    for comparison in comparisons:
        assert {candidate.decision_type for candidate in comparison.candidates} == {
            "collect_more_evidence",
            "downgrade_explanation",
            "prerequisite_remediation",
            "maintain_and_consolidate",
            "advance_challenge",
        }
        row = session.query(DBDecisionRecord).filter_by(task_id=comparison.task_id).one()
        assert row.status == "proposed"
        assert row.user_confirmed is False
        assert row.execution_impact["mastery_update"] == "none"
        assert row.after_version_id is None


def test_insufficient_and_conflicting_evidence_choose_more_evidence(db_session_m3):
    session, fixtures = db_session_m3
    first_task = _prepare(session, fixtures[0])
    report = build_m3_matching_report(session, task_id=first_task.id, owner_public_id=first_task.owner_public_id)
    persist_m3_matching_report(session, report=report)
    insufficient = build_m3_decision_comparison(
        session, task_id=first_task.id, owner_public_id=first_task.owner_public_id
    )
    assert insufficient.evidence_state == "insufficient"
    assert insufficient.selected_decision_type == "collect_more_evidence"

    second_task = _prepare(session, fixtures[1])
    _event(
        session,
        second_task,
        accuracy=0.92,
        help_requests=3,
        self_reported_difficulty=5,
    )
    report = build_m3_matching_report(session, task_id=second_task.id, owner_public_id=second_task.owner_public_id)
    persist_m3_matching_report(session, report=report)
    conflicting = build_m3_decision_comparison(
        session, task_id=second_task.id, owner_public_id=second_task.owner_public_id
    )
    assert conflicting.evidence_state == "conflicting"
    assert conflicting.selected_decision_type == "collect_more_evidence"


# Local fixture avoids coupling M3 tests to the application's global database.
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.m3_baseline import seed_m3_profile_baselines


@pytest.fixture
def db_session_m3():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session, seed_m3_profile_baselines(session).fixtures
    finally:
        session.close()
        engine.dispose()
