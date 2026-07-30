from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.m5_assessment import (
    AssessmentEvidenceInput,
    normalize_assessment_event,
    record_assessment_evidence,
)


def _evidence(source_type, **updates):
    data = {
        "idempotency_key": f"evidence-{source_type}-001",
        "source_type": source_type,
        "source_object_id": "legacy-record-1",
        "course_id": "course-1",
        "target_object_type": "chapter",
        "target_object_id": "chapter-1",
        "occurred_at": datetime(2026, 7, 28, tzinfo=timezone.utc),
    }
    data.update(updates)
    return AssessmentEvidenceInput(**data)


def test_quiz_and_wrong_question_review_never_claim_mastery():
    quiz = normalize_assessment_event(_evidence("quiz_attempt", correct=True, confidence=0.9))
    review = normalize_assessment_event(_evidence("wrong_question_review"))
    assert quiz.event_type == "quiz_answered"
    assert review.event_type == "wrong_question_reviewed"


def test_code_requires_all_required_or_hidden_tests_for_strong_evidence():
    public = normalize_assessment_event(_evidence(
        "code_execution", passed_count=3, total_count=3, test_scope="public",
    ))
    partial = normalize_assessment_event(_evidence(
        "code_execution", passed_count=2, total_count=3, test_scope="hidden",
    ))
    hidden = normalize_assessment_event(_evidence(
        "code_execution", passed_count=3, total_count=3, test_scope="hidden",
    ))
    assert public.event_type == "code_run"
    assert partial.event_type == "code_run"
    assert hidden.event_type == "code_tests_passed"


def test_delayed_retest_requires_success_and_24_hours():
    early = normalize_assessment_event(_evidence(
        "delayed_retest", correct=True, delay_hours=12,
    ))
    failed = normalize_assessment_event(_evidence(
        "delayed_retest", correct=False, delay_hours=48,
    ))
    stable = normalize_assessment_event(_evidence(
        "delayed_retest", correct=True, delay_hours=48,
    ))
    assert early.event_type == "quiz_answered"
    assert failed.event_type == "quiz_answered"
    assert stable.event_type == "delayed_retest_passed"


def test_normalized_evidence_is_persisted_and_replayed_idempotently():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    evidence = _evidence("code_execution", passed_count=2, total_count=2, test_scope="required")
    first = record_assessment_evidence(session, owner_public_id="usr-assessment", evidence=evidence)
    replay = record_assessment_evidence(session, owner_public_id="usr-assessment", evidence=evidence)
    assert first["created"] is True and replay["created"] is False
    assert first["event_id"] == replay["event_id"]
    assert first["strong_evidence"] is True
    assert first["mastery_changed"] is False
