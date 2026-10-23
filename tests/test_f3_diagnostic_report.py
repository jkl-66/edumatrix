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
    DBDiagnosticReport,
    DBDiagnosticResponseDraft,
    DBLearningPath,
    DBPlanDraft,
    DBPlanVersion,
    DBProfileSnapshot,
    DBUser,
)
from app.diagnostic_report import (
    DiagnosticReportError,
    confirm_report_path,
    diagnostic_report_payload,
    generate_diagnostic_report,
    generate_report_path,
)
from app.diagnostic_session import (
    DiagnosticResponseInput,
    save_diagnostic_response,
    start_or_resume_diagnostic_session,
    submit_diagnostic_session,
)
from app.migrations import MIGRATIONS
from app.main import app
from app.path_draft import PathDraftError


COURSE_ID = "demo-course-rag-trust-v1"
BASE_TIME = datetime(2026, 8, 13, 1, 0, 0)


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


def _submitted_diagnostic(session):
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
        idempotency_key="f3-report-legacy-blueprint-001",
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
        content_hash="f3-report-legacy-blueprint".ljust(64, "0"),
    )
    session.add(blueprint)
    session.flush()
    work, _ = start_or_resume_diagnostic_session(session, user=learner, blueprint_id=blueprint.id)
    expected = []
    for index, question_version_id in enumerate(blueprint.question_version_ids):
        version = session.get(DBAssessmentQuestionVersion, question_version_id)
        question = session.get(DBAssessmentQuestion, version.question_id)
        answer = dict(version.answer_key or {})
        if question.question_type == "true_false" and index == 0:
            answer = {"value": not bool(answer.get("value"))}
        save_diagnostic_response(
            session,
            user=learner,
            session_id=work.id,
            question_version_id=question_version_id,
            response=DiagnosticResponseInput(
                answer=answer,
                understanding_level="clear" if index == 0 else "mostly",
                duration=30 + index,
                confidence=0.9 if index == 0 else 0.7,
                idempotency_key=f"f3-report-response-{index:03d}",
                saved_at=BASE_TIME + timedelta(seconds=index),
            ),
        )
        expected.append(answer)
    submit_diagnostic_session(
        session,
        user=learner,
        session_id=work.id,
        idempotency_key="f3-report-submit-001",
    )
    session.commit()
    return learner, blueprint, work, expected


def test_report_materializes_formal_evidence_once_and_preserves_traceability():
    engine, session = _session()
    try:
        learner, blueprint, work, expected_answers = _submitted_diagnostic(session)
        before = session.query(DBAssessmentAttempt).filter(
            DBAssessmentAttempt.idempotency_key.like(f"diagnostic-session:{work.id}:%")
        ).count()
        row, created = generate_diagnostic_report(
            session,
            user=learner,
            session_id=work.id,
            idempotency_key="f3-diagnostic-report-001",
        )
        session.commit()
        replay, replay_created = generate_diagnostic_report(
            session,
            user=learner,
            session_id=work.id,
            idempotency_key="f3-diagnostic-report-001",
        )
        payload = diagnostic_report_payload(session, user=learner, row=replay)

        assert before == 0
        assert created is True and replay_created is False and replay.id == row.id
        attempts = session.query(DBAssessmentAttempt).filter(
            DBAssessmentAttempt.idempotency_key.like(f"diagnostic-session:{work.id}:%")
        ).order_by(DBAssessmentAttempt.submitted_at, DBAssessmentAttempt.id).all()
        assert len(attempts) == blueprint.question_count == len(row.attempt_ids)
        assert [item.answer for item in attempts] == expected_answers
        assert payload["summary"]["questionCount"] == blueprint.question_count
        assert payload["summary"]["scoredCount"] == blueprint.question_count
        assert payload["blindSpots"][0]["errorType"]["code"] == "confident_misunderstanding"
        assert all(item["attemptIds"] for item in payload["mastery"] if item["status"] == "known")
        assert all(item["sources"] for item in payload["evidence"])
        snapshot = session.get(DBProfileSnapshot, row.profile_snapshot_id)
        assert snapshot.snapshot["mastery_status"] == "initial_evidence_snapshot"
        assert snapshot.snapshot["source_diagnostic_report_id"] == row.id
        assert session.query(DBDiagnosticReport).count() == 1
    finally:
        session.close()
        engine.dispose()


def test_ungraded_subjective_answer_stays_unknown_instead_of_fabricating_score():
    engine, session = _session()
    try:
        learner, blueprint, work, _ = _submitted_diagnostic(session)
        version_id = blueprint.question_version_ids[-1]
        version = session.get(DBAssessmentQuestionVersion, version_id)
        question = session.get(DBAssessmentQuestion, version.question_id)
        question.question_type = "short_answer"
        draft = session.query(DBDiagnosticResponseDraft).filter_by(
            session_id=work.id, question_version_id=version_id,
        ).one()
        draft.answer = {"text": "根据课程来源说明原因。"}
        session.commit()

        row, _ = generate_diagnostic_report(
            session,
            user=learner,
            session_id=work.id,
            idempotency_key="f3-diagnostic-report-unknown-001",
        )
        session.commit()
        payload = diagnostic_report_payload(session, user=learner, row=row)
        evidence = next(item for item in payload["evidence"] if item["questionVersionId"] == version_id)
        mastery = next(item for item in payload["mastery"] if item["knowledgePointId"] == version.primary_knowledge_point_id)

        assert evidence["score"] is None
        assert evidence["gradingStatus"] == "unknown"
        assert evidence["errorType"]["code"] == "insufficient_evidence"
        if mastery["evidenceCount"] == 0:
            assert mastery["score"] is None and mastery["label"] == "未知"
    finally:
        session.close()
        engine.dispose()


def test_report_failure_does_not_mutate_submitted_answers():
    engine, session = _session()
    try:
        learner, _, work, _ = _submitted_diagnostic(session)
        saved = {
            row.question_version_id: dict(row.answer or {})
            for row in session.query(DBDiagnosticResponseDraft).filter_by(session_id=work.id).all()
        }
        session.query(DBDiagnosticResponseDraft).filter_by(session_id=work.id).first().question_version_id = "missing-version"
        with pytest.raises(Exception):
            generate_diagnostic_report(
                session,
                user=learner,
                session_id=work.id,
                idempotency_key="f3-diagnostic-report-failure-001",
            )
        session.rollback()
        current = {
            row.question_version_id: dict(row.answer or {})
            for row in session.query(DBDiagnosticResponseDraft).filter_by(session_id=work.id).all()
        }
        assert current == saved
        assert session.query(DBDiagnosticReport).count() == 0
    finally:
        session.close()
        engine.dispose()


def test_path_generation_retries_same_version_and_confirm_enters_formal_path():
    engine, session = _session()
    try:
        learner, _, work, _ = _submitted_diagnostic(session)
        report, _ = generate_diagnostic_report(
            session,
            user=learner,
            session_id=work.id,
            idempotency_key="f3-diagnostic-report-path-001",
        )
        session.commit()
        first = generate_report_path(
            session, user=learner, report=report, time_budget_minutes=90,
            idempotency_key=f"diagnostic-report-path:{report.id}",
        )
        session.commit()
        second = generate_report_path(
            session, user=learner, report=report, time_budget_minutes=90,
            idempotency_key=f"diagnostic-report-path:{report.id}",
        )
        session.commit()

        assert first["plan"]["id"] == second["plan"]["id"]
        assert first["plan"]["version_number"] == second["plan"]["version_number"] == 1
        assert first["plan"]["profile_snapshot_id"] == report.profile_snapshot_id
        assert all(item["reason"] and item["difficulty"] is not None for item in first["nodes"])
        plan = session.get(DBPlanDraft, first["plan"]["id"])
        version = session.get(DBPlanVersion, plan.current_version_id)
        assert version.content["nodes"][0]["rationale"]
        result = confirm_report_path(session, user=learner, report=report)
        session.commit()
        replay = confirm_report_path(session, user=learner, report=report)
        session.commit()
        assert result == replay
        assert result["route"].startswith(f"/workspace/path?course_id={COURSE_ID}")
        assert session.query(DBLearningPath).filter_by(source_plan_version_id=version.id).count() == 1
    finally:
        session.close()
        engine.dispose()


def test_report_owner_boundary_and_migration_are_idempotent():
    engine, session = _session()
    try:
        learner, _, work, _ = _submitted_diagnostic(session)
        outsider = DBUser(public_id="usr-f3-report-outsider", username="f3-report-outsider", hashed_password="x", role="student")
        session.add(outsider)
        session.commit()
        with pytest.raises(DiagnosticReportError) as forbidden:
            generate_diagnostic_report(
                session,
                user=outsider,
                session_id=work.id,
                idempotency_key="f3-report-forbidden-001",
            )
        assert forbidden.value.status_code == 403
    finally:
        session.close()
        engine.dispose()

    migration_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(migration_engine)
    migration = next(item for item in MIGRATIONS if item.version == "20260813_069")
    with migration_engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE diagnostic_reports")
        migration.apply(connection)
        migration.apply(connection)
    assert "diagnostic_reports" in inspect(migration_engine).get_table_names()
    triggers = {
        row[0]
        for row in migration_engine.connect().exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='diagnostic_reports'"
        )
    }
    assert {"trg_diagnostic_report_no_update", "trg_diagnostic_report_no_delete"} <= triggers
    migration_engine.dispose()


def test_report_api_replay_path_retry_confirm_and_owner_boundary(monkeypatch):
    engine, seed_session = _session()
    maker = sessionmaker(bind=engine)
    try:
        learner, _, work, _ = _submitted_diagnostic(seed_session)
        outsider = DBUser(
            public_id="usr-f3-report-api-outsider",
            username="f3-report-api-outsider",
            hashed_password="not-used",
            role="student",
        )
        seed_session.add(outsider)
        seed_session.commit()

        import app.diagnostic_api as diagnostic_api

        async def fake_run_db_op(operation, *args, **kwargs):
            db = maker()
            try:
                return operation(db, *args, **kwargs)
            finally:
                db.close()

        original_generate_report_path = diagnostic_api.generate_report_path
        path_calls = 0

        def fail_once(*args, **kwargs):
            nonlocal path_calls
            path_calls += 1
            if path_calls == 1:
                raise PathDraftError("diagnostic_path_generation_failed", "模拟路径生成失败。")
            return original_generate_report_path(*args, **kwargs)

        monkeypatch.setattr(diagnostic_api, "run_db_op", fake_run_db_op)
        monkeypatch.setattr(diagnostic_api, "generate_report_path", fail_once)
        app.dependency_overrides[get_current_user] = lambda: learner
        with TestClient(app) as client:
            created = client.post(
                f"/api/v1/diagnostics/sessions/{work.id}/report",
                json={"idempotencyKey": "f3-report-api-create-001"},
            )
            replay = client.post(
                f"/api/v1/diagnostics/sessions/{work.id}/report",
                json={"idempotencyKey": "f3-report-api-create-001"},
            )
            assert created.status_code == 201 and created.json()["created"] is True
            assert replay.status_code == 201 and replay.json()["created"] is False
            assert replay.json()["report"]["id"] == created.json()["report"]["id"]

            failed_path = client.post(
                f"/api/v1/diagnostics/sessions/{work.id}/report/path",
                json={"idempotencyKey": "f3-report-api-path-001", "timeBudgetMinutes": 90},
            )
            assert failed_path.status_code == 409
            assert failed_path.json()["detail"]["code"] == "diagnostic_path_generation_failed"

            readable = client.get(f"/api/v1/diagnostics/sessions/{work.id}/report")
            assert readable.status_code == 200
            assert readable.json()["id"] == created.json()["report"]["id"]
            assert readable.json()["path"]["state"] == "not_generated"

            retried = client.post(
                f"/api/v1/diagnostics/sessions/{work.id}/report/path",
                json={"idempotencyKey": "f3-report-api-path-001", "timeBudgetMinutes": 90},
            )
            assert retried.status_code == 200
            assert retried.json()["path"]["plan"]["profile_snapshot_id"] == readable.json()["profileSnapshotId"]

            confirmed = client.post(
                f"/api/v1/diagnostics/sessions/{work.id}/report/path/confirm",
                json={"idempotencyKey": "f3-report-api-confirm-001"},
            )
            assert confirmed.status_code == 200
            assert confirmed.json()["route"].startswith(f"/workspace/path?course_id={COURSE_ID}")

            app.dependency_overrides[get_current_user] = lambda: outsider
            forbidden = client.get(f"/api/v1/diagnostics/sessions/{work.id}/report")
            assert forbidden.status_code == 403
            assert forbidden.json()["detail"]["code"] == "diagnostic_report_forbidden"
    finally:
        app.dependency_overrides.clear()
        seed_session.close()
        engine.dispose()
