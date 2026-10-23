from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.competition_demo_seed import seed_competition_demo
from app.auth import get_current_user
from app.database import (
    Base,
    DBAssessmentAttempt,
    DBAssessmentQuestion,
    DBAssessmentQuestionVersion,
    DBDiagnosticBlueprint,
    DBDiagnosticResponseDraft,
    DBDiagnosticSession,
    DBProfileSnapshot,
    DBUser,
)
from app.diagnostic_session import (
    DiagnosticResponseInput,
    DiagnosticSessionError,
    diagnostic_session_payload,
    save_diagnostic_response,
    start_or_resume_diagnostic_session,
    submit_diagnostic_session,
)
from app.migrations import MIGRATIONS
from app.main import app


COURSE_ID = "demo-course-rag-trust-v1"
BASE_SAVED_AT = datetime(2026, 8, 12, 12, 0, 0)


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def _fixture(session):
    seed_competition_demo(session)
    learner = session.query(DBUser).filter_by(username="lzz").one()
    questions = session.query(DBAssessmentQuestion).filter_by(
        course_id=COURSE_ID,
        status="approved",
    ).order_by(DBAssessmentQuestion.id).limit(5).all()
    versions = [session.get(DBAssessmentQuestionVersion, item.current_version_id) for item in questions]
    profile = session.query(DBProfileSnapshot).filter_by(
        owner_public_id=learner.public_id,
    ).order_by(DBProfileSnapshot.created_at.desc(), DBProfileSnapshot.id.desc()).first()
    blueprint = DBDiagnosticBlueprint(
        owner_public_id=learner.public_id,
        course_id=COURSE_ID,
        idempotency_key="f3-session-blueprint-001",
        profile_snapshot_id=profile.id,
        question_version_ids=[item.id for item in versions],
        knowledge_point_coverage=[
            {"id": item.primary_knowledge_point_id, "title": item.primary_knowledge_point_id}
            for item in versions
        ],
        difficulty_bands={"questionKinds": {"theory": 2, "application": 2, "engineering_judgment": 1}},
        source_refs=[],
        review_decision={"status": "approved", "decisionSummary": "历史五题蓝图兼容 fixture。"},
        generation_stages=[{"key": "legacy", "label": "历史题组", "status": "completed"}],
        question_count=5,
        estimated_minutes=10,
        content_hash="f3-session-legacy-blueprint".ljust(64, "0"),
    )
    session.add(blueprint)
    session.commit()
    return learner, blueprint


def _response(
    key: str,
    *,
    choice: str = "A",
    level: str | None = "partial",
    duration: int = 20,
    saved_at: datetime = BASE_SAVED_AT,
):
    return DiagnosticResponseInput(
        answer={"choice": choice},
        understanding_level=level,
        duration=duration,
        confidence=0.45 if level else None,
        idempotency_key=key,
        saved_at=saved_at,
    )


def _complete_response(
    session,
    question_version_id: str,
    key: str,
    *,
    saved_at: datetime = BASE_SAVED_AT,
):
    version = session.get(DBAssessmentQuestionVersion, question_version_id)
    question = session.get(DBAssessmentQuestion, version.question_id)
    if question.question_type == "multiple_choice":
        answer = {"choices": ["A"]}
    elif question.question_type == "true_false":
        answer = {"value": True}
    elif question.question_type == "fill_blank":
        blanks = (version.answer_key or {}).get("blanks", (version.answer_key or {}).get("answers", []))
        answer = {"blanks": ["测试答案"] * max(1, len(blanks))}
    elif question.question_type == "code":
        answer = {"code": "def solution():\n    return True"}
    elif question.question_type in {"short_answer", "open_task"}:
        answer = {"text": "基于课程来源完成的诊断作答。"}
    else:
        answer = {"choice": "A"}
    return DiagnosticResponseInput(answer, "clear", 30, 0.9, key, saved_at)


def test_session_start_resume_save_update_and_refresh_restore_without_formal_attempts():
    engine, session = _session()
    try:
        learner, blueprint = _fixture(session)
        attempt_count = session.query(DBAssessmentAttempt).count()
        work, created = start_or_resume_diagnostic_session(
            session, user=learner, blueprint_id=blueprint.id,
        )
        session.commit()
        resumed, resumed_created = start_or_resume_diagnostic_session(
            session, user=learner, blueprint_id=blueprint.id,
        )
        assert created is True and resumed_created is False and resumed.id == work.id

        question_id = blueprint.question_version_ids[0]
        first, first_created = save_diagnostic_response(
            session,
            user=learner,
            session_id=work.id,
            question_version_id=question_id,
            response=_complete_response(session, question_id, "f3-response-save-001"),
        )
        session.commit()
        replay, replay_created = save_diagnostic_response(
            session,
            user=learner,
            session_id=work.id,
            question_version_id=question_id,
            response=_complete_response(session, question_id, "f3-response-save-001"),
        )
        assert replay_created is False and replay.id == first.id

        updated, updated_created = save_diagnostic_response(
            session,
            user=learner,
            session_id=work.id,
            question_version_id=question_id,
            response=DiagnosticResponseInput(
                _complete_response(session, question_id, "unused").answer,
                "mostly",
                47,
                0.75,
                "f3-response-save-002",
                BASE_SAVED_AT + timedelta(seconds=1),
            ),
        )
        session.commit()
        restored = diagnostic_session_payload(session, session.get(DBDiagnosticSession, work.id))

        assert first_created is True and updated_created is False
        assert session.query(DBDiagnosticResponseDraft).count() == 1
        assert session.query(DBAssessmentAttempt).count() == attempt_count
        assert restored["currentQuestionVersionId"] == question_id
        assert restored["savedCount"] == 1 and restored["completedCount"] == 1
        assert restored["responses"][0]["answer"] == _complete_response(session, question_id, "unused").answer
        assert restored["responses"][0]["understandingLevel"] == "mostly"
        assert restored["responses"][0]["duration"] == 47
        assert restored["responses"][0]["clientSavedAt"] == "2026-08-12T12:00:01Z"
    finally:
        session.close()
        engine.dispose()


def test_owner_blueprint_and_question_boundaries_preserve_existing_draft_on_failure():
    engine, session = _session()
    try:
        learner, blueprint = _fixture(session)
        outsider = DBUser(
            public_id="usr-f3-session-outsider",
            username="f3-session-outsider",
            hashed_password="not-used",
            role="student",
        )
        session.add(outsider)
        work, _ = start_or_resume_diagnostic_session(session, user=learner, blueprint_id=blueprint.id)
        question_id = blueprint.question_version_ids[0]
        saved, _ = save_diagnostic_response(
            session,
            user=learner,
            session_id=work.id,
            question_version_id=question_id,
            response=_response("f3-boundary-save-001", choice="A"),
        )
        session.commit()

        with pytest.raises(DiagnosticSessionError) as forbidden:
            start_or_resume_diagnostic_session(session, user=outsider, blueprint_id=blueprint.id)
        assert forbidden.value.status_code == 403
        with pytest.raises(DiagnosticSessionError) as wrong_owner:
            save_diagnostic_response(
                session,
                user=outsider,
                session_id=work.id,
                question_version_id=question_id,
                response=_response("f3-boundary-save-002"),
            )
        assert wrong_owner.value.status_code == 403
        with pytest.raises(DiagnosticSessionError) as mismatch:
            save_diagnostic_response(
                session,
                user=learner,
                session_id=work.id,
                question_version_id="aqv-not-in-blueprint",
                response=_response("f3-boundary-save-003", choice="D"),
            )
        assert mismatch.value.code == "diagnostic_question_mismatch"
        assert session.get(DBDiagnosticResponseDraft, saved.id).answer == {"choice": "A"}
        assert session.query(DBDiagnosticResponseDraft).count() == 1
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (_response("f3-invalid-level", level="guessing"), "diagnostic_understanding_invalid"),
        (_response("f3-invalid-duration", duration=-1), "diagnostic_duration_invalid"),
        (DiagnosticResponseInput({"choice": "A"}, "partial", 2, 1.2, "f3-invalid-confidence", BASE_SAVED_AT), "diagnostic_confidence_invalid"),
    ],
)
def test_response_validation_rejects_invalid_understanding_duration_and_confidence(response, code):
    engine, session = _session()
    try:
        learner, blueprint = _fixture(session)
        attempt_count = session.query(DBAssessmentAttempt).count()
        work, _ = start_or_resume_diagnostic_session(session, user=learner, blueprint_id=blueprint.id)
        with pytest.raises(DiagnosticSessionError) as invalid:
            save_diagnostic_response(
                session,
                user=learner,
                session_id=work.id,
                question_version_id=blueprint.question_version_ids[0],
                response=response,
            )
        assert invalid.value.code == code and invalid.value.status_code == 422
        assert session.query(DBDiagnosticResponseDraft).count() == 0
    finally:
        session.close()
        engine.dispose()


def test_submit_requires_every_answer_and_understanding_then_freezes_session_only():
    engine, session = _session()
    try:
        learner, blueprint = _fixture(session)
        attempt_count = session.query(DBAssessmentAttempt).count()
        work, _ = start_or_resume_diagnostic_session(session, user=learner, blueprint_id=blueprint.id)
        first_question = blueprint.question_version_ids[0]
        save_diagnostic_response(
            session,
            user=learner,
            session_id=work.id,
            question_version_id=first_question,
            response=_response("f3-submit-first-001", level=None),
        )
        session.commit()
        with pytest.raises(DiagnosticSessionError) as incomplete:
            submit_diagnostic_session(
                session, user=learner, session_id=work.id, idempotency_key="f3-submit-incomplete-001",
            )
        assert incomplete.value.code == "diagnostic_answers_incomplete"
        assert first_question in incomplete.value.details["missingQuestionVersionIds"]

        for index, question_id in enumerate(blueprint.question_version_ids):
            save_diagnostic_response(
                session,
                user=learner,
                session_id=work.id,
                question_version_id=question_id,
                response=_complete_response(
                    session,
                    question_id,
                    f"f3-submit-complete-{index:03d}",
                    saved_at=BASE_SAVED_AT + timedelta(seconds=index + 1),
                ),
            )
        submitted = submit_diagnostic_session(
            session, user=learner, session_id=work.id, idempotency_key="f3-submit-complete-001",
        )
        session.commit()
        replay = submit_diagnostic_session(
            session, user=learner, session_id=work.id, idempotency_key="f3-submit-complete-001",
        )

        assert submitted.status == "submitted" and replay.id == submitted.id
        assert diagnostic_session_payload(session, submitted)["canSubmit"] is True
        assert session.query(DBAssessmentAttempt).count() == attempt_count
        with pytest.raises(DiagnosticSessionError) as frozen:
            save_diagnostic_response(
                session,
                user=learner,
                session_id=work.id,
                question_version_id=first_question,
                response=_response("f3-submit-after-freeze-001", choice="C"),
            )
        assert frozen.value.code == "diagnostic_session_submitted"
    finally:
        session.close()
        engine.dispose()


def test_older_response_replay_cannot_overwrite_a_newer_saved_answer():
    engine, session = _session()
    try:
        learner, blueprint = _fixture(session)
        work, _ = start_or_resume_diagnostic_session(session, user=learner, blueprint_id=blueprint.id)
        question_id = blueprint.question_version_ids[0]
        first = _response(
            "f3-order-save-001",
            choice="A",
            saved_at=BASE_SAVED_AT,
        )
        newer = _response(
            "f3-order-save-002",
            choice="C",
            level="clear",
            duration=44,
            saved_at=BASE_SAVED_AT + timedelta(seconds=2),
        )
        save_diagnostic_response(
            session,
            user=learner,
            session_id=work.id,
            question_version_id=question_id,
            response=first,
        )
        save_diagnostic_response(
            session,
            user=learner,
            session_id=work.id,
            question_version_id=question_id,
            response=newer,
        )
        stale, created = save_diagnostic_response(
            session,
            user=learner,
            session_id=work.id,
            question_version_id=question_id,
            response=first,
        )
        session.commit()

        assert created is False
        assert stale.answer == {"choice": "C"}
        assert stale.understanding_level == "clear"
        assert stale.duration_seconds == 44
        assert stale.idempotency_key == "f3-order-save-002"
        assert stale.client_saved_at == BASE_SAVED_AT + timedelta(seconds=2)
    finally:
        session.close()
        engine.dispose()


def test_diagnostic_session_api_start_resume_save_validation_and_owner_isolation(monkeypatch):
    engine, seed_session = _session()
    maker = sessionmaker(bind=engine)
    try:
        learner, blueprint = _fixture(seed_session)
        outsider = DBUser(
            public_id="usr-f3-api-outsider",
            username="f3-api-outsider",
            hashed_password="not-used",
            role="student",
        )
        seed_session.add(outsider)
        seed_session.commit()
        learner_id = learner.public_id
        outsider_id = outsider.public_id
        blueprint_id = blueprint.id
        question_id = blueprint.question_version_ids[0]

        import app.diagnostic_api as diagnostic_api

        async def fake_run_db_op(operation, *args, **kwargs):
            db = maker()
            try:
                return operation(db, *args, **kwargs)
            finally:
                db.close()

        monkeypatch.setattr(diagnostic_api, "run_db_op", fake_run_db_op)
        app.dependency_overrides[get_current_user] = lambda: learner
        with TestClient(app) as client:
            started = client.post(f"/api/v1/diagnostics/blueprints/{blueprint_id}/sessions")
            resumed = client.post(f"/api/v1/diagnostics/blueprints/{blueprint_id}/sessions")
            assert started.status_code == 200 and started.json()["created"] is True
            assert resumed.status_code == 200 and resumed.json()["created"] is False
            session_id = started.json()["session"]["id"]
            assert resumed.json()["session"]["id"] == session_id

            invalid_time = client.put(
                f"/api/v1/diagnostics/sessions/{session_id}/responses/{question_id}",
                json={
                    "questionVersionId": question_id,
                    "answer": {"choice": "A"},
                    "understandingLevel": "partial",
                    "duration": 5,
                    "confidence": 0.5,
                    "idempotencyKey": "f3-api-invalid-time-001",
                },
            )
            assert invalid_time.status_code == 422

            mismatch = client.put(
                f"/api/v1/diagnostics/sessions/{session_id}/responses/{question_id}",
                json={
                    "questionVersionId": "aqv-different-question",
                    "answer": {"choice": "A"},
                    "understandingLevel": "partial",
                    "duration": 5,
                    "confidence": 0.5,
                    "savedAt": "2026-08-12T12:00:00Z",
                    "idempotencyKey": "f3-api-mismatch-001",
                },
            )
            assert mismatch.status_code == 422
            assert mismatch.json()["detail"]["code"] == "diagnostic_question_mismatch"

            saved = client.put(
                f"/api/v1/diagnostics/sessions/{session_id}/responses/{question_id}",
                json={
                    "questionVersionId": question_id,
                    "answer": {"choice": "A"},
                    "understandingLevel": "partial",
                    "duration": 5,
                    "confidence": 0.5,
                    "savedAt": "2026-08-12T12:00:00Z",
                    "idempotencyKey": "f3-api-save-001",
                },
            )
            assert saved.status_code == 200
            assert saved.json()["session"]["responses"][0]["clientSavedAt"] == "2026-08-12T12:00:00Z"

            app.dependency_overrides[get_current_user] = lambda: outsider
            forbidden = client.get(f"/api/v1/diagnostics/sessions/{session_id}")
            assert forbidden.status_code == 403
            assert forbidden.json()["detail"]["code"] == "diagnostic_session_forbidden"
    finally:
        app.dependency_overrides.clear()
        seed_session.close()
        engine.dispose()


def test_latest_migrations_install_diagnostic_session_tables_and_ordering_idempotently():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_migration = next(item for item in MIGRATIONS if item.version == "20260812_067")
    ordering_migration = next(item for item in MIGRATIONS if item.version == "20260812_068")
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE diagnostic_response_drafts")
        connection.exec_driver_sql("DROP TABLE diagnostic_sessions")
        session_migration.apply(connection)
        session_migration.apply(connection)
        connection.exec_driver_sql("ALTER TABLE diagnostic_response_drafts DROP COLUMN client_saved_at")
        ordering_migration.apply(connection)
        ordering_migration.apply(connection)
    tables = set(inspect(engine).get_table_names())
    assert {"diagnostic_sessions", "diagnostic_response_drafts"} <= tables
    assert "client_saved_at" in {
        column["name"] for column in inspect(engine).get_columns("diagnostic_response_drafts")
    }
    engine.dispose()
