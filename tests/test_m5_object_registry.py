from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import (
    Base,
    DBAuditLog,
    DBAssessmentAttempt,
    DBAssessmentQuestion,
    DBAssessmentQuestionVersion,
    DBAssessmentRetestTask,
    DBLearningEvent,
    DBLearningEventConsumption,
    DBMisconceptionReview,
    DBModelCall,
    DBTutorContextSession,
    DBUser,
)
from app.m1_object_service import OBJECT_SPECS, object_detail
from app.m5_assessment_core import (
    MisconceptionDecisionInput,
    QuestionVersionInput,
    create_question_version,
    decide_misconception,
)


M5_OBJECT_TYPES = {
    "learning_event_consumption",
    "tutor_context_session",
    "model_call",
    "model_quota_bucket",
    "model_price_version",
    "worker_lease",
    "evaluation_annotation",
    "evaluation_report",
    "integration_delivery",
    "assessment_question",
    "assessment_question_version",
    "assessment_attempt",
    "misconception_review",
    "assessment_retest_task",
}


def _fixture():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    owner = DBUser(
        public_id="registry-owner-public",
        username="registry-owner",
        hashed_password="test",
        role="student",
        is_active=True,
    )
    outsider = DBUser(
        public_id="registry-outsider-public",
        username="registry-outsider",
        hashed_password="test",
        role="student",
        is_active=True,
    )
    session.add_all([owner, outsider])
    session.flush()

    question = DBAssessmentQuestion(
        id="registry-question",
        owner_public_id=owner.public_id,
        question_type="single_choice",
        origin="manual",
        status="draft",
    )
    session.add(question)
    session.flush()
    version = DBAssessmentQuestionVersion(
        id="registry-question-version",
        question_id=question.id,
        version_number=1,
        prompt="private prompt",
        answer_key={"answer": "A"},
        scoring_rule={"type": "exact"},
        content_hash="a" * 64,
        created_by_public_id=owner.public_id,
    )
    session.add(version)
    session.flush()
    question.current_version_id = version.id
    attempt = DBAssessmentAttempt(
        id="registry-attempt",
        owner_public_id=owner.public_id,
        question_version_id=version.id,
        idempotency_key="registry-attempt-key",
        answer={"answer": "B"},
        score=0.0,
        correct=False,
    )
    session.add(attempt)
    session.flush()
    misconception = DBMisconceptionReview(
        id="registry-misconception",
        owner_public_id=owner.public_id,
        attempt_id=attempt.id,
        candidate_category="knowledge_gap",
    )
    session.add(misconception)
    session.flush()
    retest = DBAssessmentRetestTask(
        id="registry-retest",
        owner_public_id=owner.public_id,
        misconception_review_id=misconception.id,
        source_attempt_id=attempt.id,
        question_version_id=version.id,
        due_at=datetime.utcnow() + timedelta(days=1),
    )
    event = DBLearningEvent(
        id="registry-event",
        owner_public_id=owner.public_id,
        event_type="resource_viewed",
        trace_id="registry-trace",
    )
    context = DBTutorContextSession(
        id="registry-context",
        owner_public_id=owner.public_id,
        idempotency_key="registry-context-key",
        primary_object_type="artifact",
        primary_object_id="registry-artifact",
        context_snapshot={},
    )
    model_call = DBModelCall(
        id="registry-model-call",
        trace_id="registry-trace",
        owner_public_id=owner.public_id,
        capability="answer",
        prompt_version="test:1.0",
        provider="test",
        model="test-model",
        status="completed",
        input_summary={"payload_included": False},
    )
    session.add_all([retest, event, context, model_call])
    session.flush()
    consumption = DBLearningEventConsumption(
        id="registry-consumption",
        learning_event_id=event.id,
        consumer="path",
        processor_version="1",
    )
    session.add(consumption)
    session.commit()
    return session, owner, outsider


def test_m5_formal_objects_are_registered_in_uniform_gateway():
    assert M5_OBJECT_TYPES <= set(OBJECT_SPECS)


@pytest.mark.parametrize("object_type,object_id", [
    ("assessment_question_version", "registry-question-version"),
    ("assessment_attempt", "registry-attempt"),
    ("misconception_review", "registry-misconception"),
    ("assessment_retest_task", "registry-retest"),
    ("learning_event_consumption", "registry-consumption"),
    ("tutor_context_session", "registry-context"),
    ("model_call", "registry-model-call"),
])
def test_m5_object_gateway_resolves_owner_and_rejects_outsider(object_type, object_id):
    session, owner, outsider = _fixture()

    detail = object_detail(
        session,
        user=owner,
        object_type=object_type,
        object_id=object_id,
    )
    assert detail["owner_public_id"] == owner.public_id

    with pytest.raises(HTTPException) as exc:
        object_detail(
            session,
            user=outsider,
            object_type=object_type,
            object_id=object_id,
        )
    assert exc.value.status_code == 403


def test_all_m5_routes_require_authenticated_user_dependency():
    from app.auth import get_current_user
    from app.m5_api import router

    assert router.routes
    paths = {route.path for route in router.routes}
    assert {
        "/api/v1/m5/workspace",
        "/api/v1/m5/workspace/actions",
        "/api/v1/m5/workspace/tasks/{task_id}/timeline",
        "/api/v1/m5/workspace/tasks/{task_id}/execute-local-demo",
        "/api/v1/m5/resources/{artifact_id}/versions",
        "/api/v1/m5/model-operations",
        "/api/v1/m5/legacy-migration-governance",
        "/api/v1/m5/model-operations/prices",
        "/api/v1/m5/model-operations/workers/claim",
        "/api/v1/m5/model-operations/workers/leases/{lease_id}/heartbeat",
        "/api/v1/m5/model-operations/workers/leases/{lease_id}/release",
        "/api/v1/m5/model-operations/workers/recover",
        "/api/v1/m5/tasks/{task_id}/cancel",
        "/api/v1/m5/assessment/cat/next",
        "/api/v1/m5/assessment/ability",
        "/api/v1/m5/assessment/attempts/{attempt_id}",
        "/api/v1/m5/learning-events",
        "/api/v1/m5/assessment/exams",
        "/api/v1/m5/assessment/exams/{exam_id}/transition",
        "/api/v1/m5/assessment/exam-sittings/{sitting_id}/responses",
        "/api/v1/m5/assessment/exam-reviews/{review_id}/complete",
        "/api/v1/m5/assessment/exam-reports/{report_id}/export/{format_name}",
    } <= paths
    missing = [
        route.path
        for route in router.routes
        if not any(dependency.call is get_current_user for dependency in route.dependant.dependencies)
    ]
    assert missing == []


def test_assessment_governance_writes_minimal_audit_records():
    session, owner, _ = _fixture()
    question, _ = create_question_version(
        session,
        owner_public_id=owner.public_id,
        course_id=None,
        question_type="single_choice",
        origin="manual",
        version=QuestionVersionInput(
            prompt="PRIVATE_QUESTION_PROMPT",
            options=["A", "B"],
            answer_key={"choice": "A"},
            scoring_rule={"type": "exact"},
        ),
    )
    review = session.query(DBMisconceptionReview).filter_by(
        id="registry-misconception",
    ).one()
    decide_misconception(
        session,
        owner_public_id=owner.public_id,
        review_id=review.id,
        decision=MisconceptionDecisionInput(
            decision="modify",
            category="strategy_error",
            note="PRIVATE_DECISION_NOTE",
        ),
    )
    session.commit()

    rows = session.query(DBAuditLog).order_by(DBAuditLog.created_at, DBAuditLog.id).all()
    assert {row.action for row in rows} == {
        "assessment.question.create",
        "assessment.misconception.decide",
    }
    assert {row.object_id for row in rows} == {question.id, review.id}
    summaries = str([row.metadata_json for row in rows])
    assert "PRIVATE_QUESTION_PROMPT" not in summaries
    assert "PRIVATE_DECISION_NOTE" not in summaries
