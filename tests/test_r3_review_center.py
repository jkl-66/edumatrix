from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.database import Base, DBReviewPlan, DBStudentProfile, DBUser
from app.m5_assessment_core import (
    AttemptInput, MisconceptionCandidateInput, QuestionVersionInput,
    create_question_version, propose_misconception, record_attempt,
)
from app.main import app
import app.m5_api as m5_api


def _isolated_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)()


def test_review_queue_projects_explicit_status_and_next_action():
    engine, session = _isolated_session()
    try:
        session.add(DBUser(public_id="review-owner", username="review-learner", hashed_password="x"))
        session.add(DBStudentProfile(student_id="review-learner"))
        session.flush()
        session.add(DBReviewPlan(student_id="review-learner", concept="混合检索", priority=0.2))
        session.commit()
        item = m5_api.review_queue(session, owner_public_id="review-owner")[0]
        assert item["source_type"] == "sm2_review_plan"
        assert item["status"] == "scheduled"
        assert item["evidence_strength"] == "algorithmic_schedule"
        assert item["next_action"] == "rate_review_quality"
    finally:
        session.close()
        engine.dispose()


def test_unconfirmed_misconception_candidate_is_excluded_from_review_center():
    engine, session = _isolated_session()
    try:
        version = create_question_version(
            session, owner_public_id="candidate-owner", course_id=None,
            question_type="single_choice", origin="manual",
            version=QuestionVersionInput(
                prompt="Which option is correct?", options=("A", "B"),
                answer_key={"choice": "B"}, scoring_rule={"type": "exact"},
            ),
        )[1]
        attempt, _ = record_attempt(
            session, owner_public_id="candidate-owner",
            attempt=AttemptInput(
                question_version_id=version.id,
                idempotency_key="r3-08-candidate-only",
                answer={"choice": "A"},
            ),
        )
        propose_misconception(
            session, owner_public_id="candidate-owner", attempt_id=attempt.id,
            candidate=MisconceptionCandidateInput(category="concept_confusion"),
        )
        assert m5_api.review_queue(session, owner_public_id="candidate-owner") == ()
    finally:
        session.close()
        engine.dispose()


def test_review_export_is_user_scoped_and_does_not_expose_answers(monkeypatch):
    engine, session = _isolated_session()
    identity = {"user": None}

    async def isolated_run_db_op(operation, *args, **kwargs):
        return operation(session, *args, **kwargs)

    monkeypatch.setattr(m5_api, "run_db_op", isolated_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: identity["user"]
    try:
        owner = DBUser(public_id="export-owner", username="export-learner", hashed_password="x")
        other = DBUser(public_id="export-other", username="other-learner", hashed_password="x")
        session.add_all([owner, other, DBStudentProfile(student_id="export-learner"), DBStudentProfile(student_id="other-learner")])
        session.add(DBReviewPlan(student_id="export-learner", concept="来源核验", priority=0.3))
        session.commit()
        identity["user"] = owner
        with TestClient(app) as client:
            response = client.get("/api/v1/m5/review-export")
        assert response.status_code == 200, response.text
        assert "复习诊疗材料" in response.text
        assert "来源核验" in response.text
        assert "answer" not in response.text.lower()
        assert "api_key" not in response.text.lower()
        assert "other-learner" not in response.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close()
        engine.dispose()
