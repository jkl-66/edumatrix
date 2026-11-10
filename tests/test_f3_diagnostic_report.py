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


def test_report_background_path_returns_owned_resumable_task(monkeypatch):
    from fastapi import FastAPI
    from app import diagnostic_api, path_tasks
    engine, db = _session()
    try:
        learner, _, work, _ = _submitted_diagnostic(db)
        report, _ = generate_diagnostic_report(db, user=learner, session_id=work.id,
                                               idempotency_key='background-path-report')
        db.commit()
        maker = sessionmaker(bind=engine)
        scheduled = []

        async def run_db(operation):
            with maker() as state:
                return operation(state)

        monkeypatch.setattr(diagnostic_api, 'run_db_op', run_db)
        monkeypatch.setattr(path_tasks, 'execute_path_task', lambda task_id, factory: scheduled.append(task_id))
        isolated = FastAPI()
        isolated.include_router(diagnostic_api.router)
        isolated.dependency_overrides[get_current_user] = lambda: learner
        with TestClient(isolated) as client:
            response = client.post(f'/api/v1/diagnostics/sessions/{work.id}/report/path',
                json={'idempotencyKey':'background-path-report-request', 'background':True})
            assert response.status_code == 200, response.text
            task = response.json()['task']
            assert task['status'] == 'queued' and scheduled == []
            assert task['automation']['state'] == 'queued'
            assert task['request']['report_id'] == report.id
            assert task['request']['profile_snapshot_id'] == report.profile_snapshot_id
            assert task['request']['full_coverage'] is True
            before = len(scheduled)
            isolated.dependency_overrides[get_current_user] = lambda: DBUser(public_id='another-learner', role='student')
            forbidden = client.post(f'/api/v1/diagnostics/sessions/{work.id}/report/path',
                json={'idempotencyKey':'foreign-path-report-request', 'background':True})
            assert forbidden.status_code == 403
            assert len(scheduled) == before
    finally:
        db.close()
        engine.dispose()


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
        for item in payload["evidence"]:
            frozen = session.get(DBAssessmentQuestionVersion, item["questionVersionId"])
            assert item["options"] == (frozen.options or [])
        assert all("options" not in item for item in row.report_data["evidence"])
        snapshot = session.get(DBProfileSnapshot, row.profile_snapshot_id)
        assert snapshot.snapshot["mastery_status"] == "initial_evidence_snapshot"
        assert snapshot.snapshot["source_diagnostic_report_id"] == row.id
        assert session.query(DBDiagnosticReport).count() == 1
    finally:
        session.close()
        engine.dispose()


def test_explicit_not_yet_restores_submits_and_preserves_unknown_mastery(monkeypatch):
    from app.database import DBAssessmentAbilityState, DBAssessmentGradingResult
    from app.diagnostic_session import diagnostic_session_payload
    from app import diagnostic_report as reports
    from tests.test_acceptance_p1_b07_diagnostic_explanations import _ApprovedExplanationLLM, _fake_gateway

    engine, session = _session()
    try:
        learner, blueprint, work, _ = _submitted_diagnostic(session)
        # This fixture has never materialized a report/score. Reopen only the
        # synthetic session to exercise saving the newly supported response.
        work.status = "active"
        blueprint.generation_stages = [{"key": "p1_b05", "status": "completed"}]
        for index, question_id in enumerate(blueprint.question_version_ids):
            if index == 0:
                version = session.get(DBAssessmentQuestionVersion, question_id)
                session.get(DBAssessmentQuestion, version.question_id).question_type = "short_answer"
            save_diagnostic_response(session, user=learner, session_id=work.id, question_version_id=question_id,
                response=DiagnosticResponseInput({"response_status": "not_yet"}, "unfamiliar", 12, 0.2,
                    f"not-yet-{index}", BASE_TIME + timedelta(days=1, seconds=index)))
        session.commit()
        session.expire_all()
        restored = diagnostic_session_payload(session, work)
        assert restored["canSubmit"] and restored["completedCount"] == len(blueprint.question_version_ids)
        assert all(item["answer"] == {"response_status": "not_yet"} for item in restored["responses"])
        submit_diagnostic_session(session, user=learner, session_id=work.id, idempotency_key="not-yet-submit")

        calls = []
        def explanations_only(*args, **kwargs):
            calls.append(kwargs["operation"])
            assert kwargs["operation"] == "p1_b07_diagnostic_explanations"  # no grading a non-answer
            return _fake_gateway(*args, **kwargs)
        monkeypatch.setattr(reports, "execute_registered_structured_call", explanations_only)
        row, created = generate_diagnostic_report(session, user=learner, session_id=work.id,
            idempotency_key="not-yet-report", llm=_ApprovedExplanationLLM())
        assert created and calls
        data = row.report_data
        assert data["summary"]["score"] is None
        assert data["summary"]["scoredCount"] == 0
        assert data["summary"]["notYetCount"] == blueprint.question_count
        assert all(item["score"] is None and not item["masteryEligible"] for item in data["evidence"])
        assert all(item["errorType"]["code"] == "not_yet_learned" for item in data["evidence"])
        assert all(item["status"] == "unknown" for item in data["mastery"])
        snapshot = session.get(DBProfileSnapshot, row.profile_snapshot_id).snapshot
        assert snapshot["self_reported_learning_start_points"] == data["learningStarts"]
        from app.profile_adaptation import build_profile_adaptation, profile_prompt_context
        point = data['learningStarts'][0]
        adaptation = build_profile_adaptation(snapshot, knowledge_point={'id': point['knowledgePointId'], 'title': point['title']})
        assert adaptation['point_mastery'] is None
        assert adaptation['difficulty_evidence']['kind'] == 'reported_weakness'
        assert adaptation['scaffolding_level'] == 'high'
        assert profile_prompt_context(adaptation)['learning_requirements']['self_reported_learning_start_points']
        assert not snapshot["mastered_knowledge_point_ids"] and not snapshot["weak_knowledge_point_ids"]
        assert session.query(DBAssessmentGradingResult).count() == 0
        assert session.query(DBAssessmentAbilityState).filter_by(owner_public_id=learner.public_id).count() == 0
        replay, created = generate_diagnostic_report(session, user=learner, session_id=work.id,
            idempotency_key="not-yet-report", llm=_ApprovedExplanationLLM())
        assert not created and replay.id == row.id
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


@pytest.fixture
def governed_path_gateway(monkeypatch):
    """Exercise path persistence with explicit model output, without external I/O."""
    import app.diagnostic_api as diagnostic_api
    import app.path_draft as path_draft
    from tests.test_acceptance_p1_b11_personalized_path import _RealPathBackend, _patch_model

    monkeypatch.setattr(path_draft, "_build_path_model", _RealPathBackend)
    monkeypatch.setattr(diagnostic_api, "build_diagnostic_llm", _RealPathBackend)
    _patch_model(monkeypatch, None)


def test_path_generation_retries_same_version_and_confirm_enters_formal_path(governed_path_gateway):
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


def test_report_api_replay_path_retry_confirm_and_owner_boundary(monkeypatch, governed_path_gateway):
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


def test_stage_report_retains_previous_course_evidence_and_keeps_later_topics_unknown():
    from app.diagnostic_report import _create_profile_snapshot
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username='lzz').one()
        previous = DBProfileSnapshot(owner_public_id=learner.public_id, profile_version='earlier-stage',
            snapshot={'course_id': COURSE_ID, 'mastery_by_knowledge_point': {
                'observed-earlier': {'title': '已有证据', 'score': 0.8, 'status': 'known', 'evidence_item_count': 2},
            }}, content_hash='earlier'.ljust(64, '0'), trace_id='earlier-stage')
        session.add(previous)
        session.flush()
        blueprint = DBDiagnosticBlueprint(course_id=COURSE_ID, profile_snapshot_id=previous.id)
        report = {'sessionId': 'stage-session', 'contextSnapshot': {'assessmentScope': {
            'selected': {'id': 'entry'}, 'courseKnowledgePoints': [
                {'id': 'observed-earlier', 'title': '已有证据'}, {'id': 'now', 'title': '当前知识'},
                {'id': 'later', 'title': '后续专业知识'},
            ]}}, 'mastery': [{
                'knowledgePointId': 'now', 'title': '当前知识', 'score': 0.5, 'status': 'known',
                'attemptIds': ['real-attempt'], 'sourceRefIds': ['source-now'], 'questionVersionIds': ['q-now'],
                'evidenceItemCount': 1, 'crossEvidence': False, 'coverageStatus': 'verified',
            }], 'difficultyFit': {'target': 0.4}, 'evidence': []}
        row = _create_profile_snapshot(session, user=learner, blueprint=blueprint,
            report_id='stage-profile-test', report_data=report)
        assert row.snapshot['mastery_by_knowledge_point']['observed-earlier']['score'] == 0.8
        assert row.snapshot['unknown_knowledge_point_ids'] == ['later']
        assert row.snapshot['mastery_by_knowledge_point']['later']['score'] is None
        assert row.snapshot['weak_knowledge_point_ids'] == ['now']
        assert row.snapshot['diagnostic_stage']['id'] == 'entry'
    finally:
        session.close()
        engine.dispose()


def test_passing_total_does_not_hide_test_set_misconception_or_change_grades():
    from copy import deepcopy
    from app.diagnostic_report import _apply_learning_focus
    from app.profile_adaptation import build_profile_adaptation, profile_answer_instruction
    grading = {"status": "completed", "score": 0.73, "correct": True, "criterionResults": [
        {"criterion_id": "meaning", "score": 1.0, "justification": "已分清训练与测试误差"},
        {"criterion_id": "selection", "score": 0.1,
         "justification": "认为测试记录没有进入fit就能反复看测试分数选模型",
         "improvement": "用验证集比较模型，测试集留到最终评估。"},
    ]}
    evidence = {"questionVersionId": "q-evaluation", "attemptId": "a-evaluation",
        "answer": {"text": "反复看测试分数选模型没有泄漏"}, "correct": True, "score": 0.73,
        "masteryEligible": True, "understandingLevel": "mostly", "grading": grading,
        "knowledgePoint": {"id": "evaluation", "title": "模型评价"},
        "errorType": {"code": "evidence_consistent"}}
    report = {"summary": {"score": 0.94}, "mastery": [
        {"knowledgePointId": "evaluation", "title": "模型评价", "score": 0.73},
        {"knowledgePointId": "data", "title": "数据与特征", "score": 1.0}], "evidence": [evidence]}
    original = deepcopy(report)
    projected = _apply_learning_focus(deepcopy(report))
    assert projected["summary"]["score"] == 0.94
    assert projected["evidence"][0]["grading"] == original["evidence"][0]["grading"]
    assert projected["evidence"][0]["correct"] is True
    assert projected["weaknesses"][0]["knowledgePointId"] == "evaluation"
    assert [p["knowledgePointId"] for p in projected["strengths"]] == ["data"]
    assert len(projected["blindSpots"]) == 1
    assert "验证集比较" in projected["summary"]["coreAdvice"]
    snapshot = {"diagnostic_evidence": {"grading_feedback": [{
        "knowledge_point_id": "evaluation", "attempt_id": "a-evaluation", "grading": grading}]}}
    plan = build_profile_adaptation(snapshot, knowledge_point={"id": "evaluation", "title": "模型评价"})
    assert plan["learning_requirements"]["diagnostic_followup"][0]["learning_needs"][0]["score"] == 0.1
    assert "已解决的不要重复" in profile_answer_instruction(plan)
    unrelated = build_profile_adaptation(snapshot, knowledge_point={"id": "matrix", "title": "矩阵"})
    assert unrelated["learning_requirements"]["diagnostic_followup"] == []


def test_report_prefers_specific_rubric_action_over_binary_wrong_answer():
    from copy import deepcopy
    from app.diagnostic_report import _apply_learning_focus
    evidence = []
    for identifier, score, action in [
        ('answer_correctness', 0.0, '如果没有答对，请结合逐题解析复习遗漏或误选的部分。'),
        ('probability-meaning', 0.0, '比较样本频率与未知真实概率，说明为什么一次新观察不能保证结果。'),
        ('empty-action', 0.0, ''),
    ]:
        evidence.append({'knowledgePoint': {'id': 'probability'}, 'masteryEligible': True,
            'score': score, 'grading': {'status': 'completed', 'criterionResults': [
                {'criterion_id': identifier, 'score': score, 'justification': '本题证据', 'improvement': action}]}})
    report = {'summary': {'score': .88}, 'mastery': [
        {'knowledgePointId': 'probability', 'title': '频率与概率', 'score': .305}], 'evidence': evidence}
    original = deepcopy(report)
    projected = _apply_learning_focus(deepcopy(report))
    assert '比较样本频率' in projected['summary']['coreAdvice']
    assert len(projected['mastery'][0]['learningNeeds']) == 3
    assert projected['summary']['score'] == .88
    assert [e['grading'] for e in projected['evidence']] == [e['grading'] for e in original['evidence']]


def test_objective_gap_uses_frozen_solution_and_lower_mastery_sets_priority():
    from app.diagnostic_report import _apply_learning_focus
    from app.profile_adaptation import grading_learning_needs
    grading={'status':'completed','criterionResults':[{'criterion_id':'answer_correctness',
        'score':0.0,'justification':'已比较答案','improvement':'如果错了请复习'}]}
    explanation='数值编码本身不能决定回归或分类，要看预测目标。'
    needs=grading_learning_needs(grading,explanation=explanation)
    assert needs[0]['basis']==explanation and explanation in needs[0]['next_step']
    report={'summary':{'score':.66},'mastery':[
        {'knowledgePointId':'types','title':'任务类型','score':.5},
        {'knowledgePointId':'generalization','title':'泛化','score':0.0}],
        'evidence':[{'knowledgePoint':{'id':'types'},'masteryEligible':True,'grading':grading,'explanation':explanation},
                    {'knowledgePoint':{'id':'generalization'},'masteryEligible':True,'grading':grading,
                     'explanation':'训练误差不能保证未见数据表现。'}]}
    result=_apply_learning_focus(report)
    assert result['summary']['weakest']=='泛化'
    assert '训练误差不能保证' in result['summary']['coreAdvice']


def test_historical_report_uses_frozen_solution_without_rewriting_stored_report():
    from copy import deepcopy
    engine, session = _session()
    try:
        learner, blueprint, work, _ = _submitted_diagnostic(session)
        row, _ = generate_diagnostic_report(session, user=learner, session_id=work.id,
            idempotency_key="historical-solution-projection")
        original = deepcopy(row.report_data)
        original["evidence"][0]["explanation"] = "错误的再次改写：2的平方是1。"
        row.report_data = original
        session.flush()
        before_hash = row.content_hash
        payload = diagnostic_report_payload(session, user=learner, row=row)
        version = session.get(DBAssessmentQuestionVersion, blueprint.question_version_ids[0])
        assert "2的平方是1" not in payload["evidence"][0]["explanation"]
        assert payload["evidence"][0]["learningFeedback"] == original["evidence"][0]["explanation"]
        assert row.report_data == original and row.content_hash == before_hash
        assert payload["summary"]["score"] == original["summary"]["score"]
        assert version.explanation
    finally:
        session.close()
        engine.dispose()
