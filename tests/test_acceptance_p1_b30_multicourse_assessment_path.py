from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.diagnostic_api as diagnostic_api
import app.multicourse_diagnostic as multicourse
import app.diagnostic_generation as diagnostic_generation
from app.auth import get_current_user
from app.database import (
    Base,
    DBAssessmentAbilityState,
    DBAssessmentAttempt,
    DBAssessmentQuestion,
    DBAssessmentQuestionVersion,
    DBCourse,
    DBCourseMembership,
    DBDiagnosticBlueprint,
    DBDiagnosticReport,
    DBDiagnosticSession,
    DBLearningEvent,
    DBPlanDraft,
    DBProfileSnapshot,
    DBSourceDocument,
    DBUser,
)
from app.diagnostic_generation import DiagnosticGenerationError
from app.diagnostic_report import DiagnosticReportError, generate_diagnostic_report
from app.diagnostic_session import (
    DiagnosticResponseInput,
    save_diagnostic_response,
    start_or_resume_diagnostic_session,
    submit_diagnostic_session,
)
from app.main import app
from app.path_draft import PathDraftError


ROOT = Path(__file__).resolve().parents[1]


class _PolicyLLM:
    provider = "openai"
    model = "deepseek-v4-flash"
    thinking_mode = "enabled"
    reasoning_effort = "max"


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def _node(key: str, *, sequence: int = 1, estimate=15, prerequisites=(), course_title: str | None = None):
    return {
        "id": f"node-{key}",
        "node_key": key,
        "sequence": sequence,
        "title": course_title or key,
        "prerequisites": list(prerequisites),
        "estimate_minutes": estimate,
        "priority": 1,
        "status": "pending",
    }


def _legacy_diagnostic_fixture(*, question_type: str = "single_choice", source_ref_ids: tuple[str, ...] = ()):
    """Build one submitted/submit-ready diagnostic without invoking a model.

    The legacy marker is only a fixture boundary: it exercises report/session
    evidence gates while keeping this test independent from the provider.
    """
    engine, session = _session()
    owner = DBUser(
        public_id="b30-evidence-owner",
        username="b30-evidence-owner",
        hashed_password="hash",
        role="student",
        is_active=True,
    )
    course = DBCourse(
        id="b30-evidence-course",
        owner_public_id=owner.public_id,
        version="1",
        title="B30 evidence course",
        visibility="private",
        status="published",
        manifest_version="1",
    )
    profile = DBProfileSnapshot(
        id="b30-evidence-profile",
        owner_public_id=owner.public_id,
        legacy_student_id=owner.username,
        profile_version="b30-evidence-profile-v1",
        snapshot={"course_id": course.id, "mastery_by_knowledge_point": {}},
        content_hash="p" * 64,
        trace_id="b30-evidence-profile-trace",
    )
    from app.database import DBKnowledgePoint

    point = DBKnowledgePoint(
        id="b30-evidence-kp",
        domain_pack="b30",
        code="evidence",
        version="1",
        title="B30 evidence point",
    )
    question = DBAssessmentQuestion(
        id="b30-evidence-question",
        owner_public_id=owner.public_id,
        course_id=course.id,
        question_type=question_type,
        origin="derived",
        status="approved",
    )
    answer_key = (
        {"choice": "A"}
        if question_type == "single_choice"
        else {"reference_answer": "证据充分的参考答案"}
    )
    version = DBAssessmentQuestionVersion(
        id="b30-evidence-question-v1",
        question_id=question.id,
        version_number=1,
        prompt="B30 evidence question",
        options=["A", "B"] if question_type == "single_choice" else [],
        answer_key=answer_key,
        scoring_rule={"version": "objective-v1"},
        explanation="",
        misconception_tags=[],
        primary_knowledge_point_id=point.id,
        secondary_knowledge_point_ids=[],
        bloom_level="understand",
        expert_difficulty=0.4,
        measured_difficulty=None,
        irt_parameters={},
        sample_size=0,
        source_ref_ids=list(source_ref_ids),
        content_hash="q" * 64,
        created_by_public_id=owner.public_id,
    )
    question.current_version_id = version.id
    blueprint = DBDiagnosticBlueprint(
        id="b30-evidence-blueprint",
        owner_public_id=owner.public_id,
        course_id=course.id,
        idempotency_key="b30-evidence-blueprint-key",
        version_number=1,
        status="ready",
        profile_snapshot_id=profile.id,
        question_version_ids=[version.id],
        knowledge_point_coverage=[{"id": point.id, "title": point.title}],
        difficulty_bands={"targetDifficulty": 0.4},
        source_refs=[],
        review_decision={
            "contextSnapshot": {
                "course": {
                    "id": course.id,
                    "title": course.title,
                    "version": course.version,
                    "manifestVersion": course.manifest_version,
                }
            }
        },
        generation_stages=[{"key": "legacy", "status": "completed"}],
        question_count=1,
        estimated_minutes=2,
        content_hash="b" * 64,
    )
    session.add_all([owner, course, profile, point, question, version, blueprint])
    session.flush()
    work, _ = start_or_resume_diagnostic_session(
        session, user=owner, blueprint_id=blueprint.id,
    )
    return engine, session, owner, course, profile, point, version, work


def test_total_schedule_keeps_same_named_nodes_separate_and_reports_conflicts():
    result = multicourse.validate_total_schedule(
        [
            {"course_id": "course-a", "path_id": "path-a", "nodes": [
                _node("intro", sequence=1, estimate={"min": 20, "max": 30}),
                _node("model", sequence=2, estimate=[20, 25], prerequisites=("intro",)),
            ]},
            {"course_id": "course-b", "path_id": "path-b", "nodes": [
                _node("intro", sequence=1, estimate=20),
                _node("model", sequence=2, estimate=20, prerequisites=("missing",)),
            ]},
        ],
        time_budget_minutes=30,
        max_days=2,
    )

    assert result["status"] == "invalid"
    assert result["course_ids"] == ["course-a", "course-b"]
    assert {task["aggregate_key"] for day in result["days"] for task in day["tasks"]} >= {
        "course-a::intro", "course-b::intro",
    }
    assert any(issue["code"] == "unreachable_node" and issue["course_id"] == "course-b" for issue in result["issues"])
    assert any(issue["code"] == "timeout" for issue in result["issues"])
    assert result["read_only"] is True
    assert result["learning_state_written"] is False


def test_multicourse_blueprints_isolates_one_model_failure_and_scopes_keys(monkeypatch):
    engine, session = _session()
    try:
        user = DBUser(public_id="b30-owner", username="b30-owner", hashed_password="hash", role="student", is_active=True)
        session.add(user)
        session.flush()
        calls = []

        def fake_generate(_session, *, user, request, llm):
            calls.append((request.course_id, request.idempotency_key, llm.model, llm.reasoning_effort))
            if request.course_id == "course-failed":
                raise DiagnosticGenerationError("provider_call_failed", "模型暂时不可用。", status_code=503)
            return SimpleNamespace(id=f"blueprint-{request.course_id}"), True

        monkeypatch.setattr(multicourse, "generate_diagnostic_blueprint", fake_generate)
        monkeypatch.setattr(
            multicourse,
            "diagnostic_blueprint_payload",
            lambda _session, row: {"id": row.id, "course": {"id": row.id.split("blueprint-", 1)[-1]}},
        )

        result = multicourse.generate_multicourse_blueprints(
            session,
            user=user,
            request=multicourse.MultiCourseBlueprintRequest(
                course_ids=("course-ok", "course-failed"),
                idempotency_key="b30-run-001",
            ),
            llm=_PolicyLLM(),
        )

        assert result["status"] == "partial"
        assert result["ready_count"] == 1
        assert result["failed_count"] == 1
        assert result["items"][0]["status"] == "ready"
        assert result["items"][1]["error"]["code"] == "provider_call_failed"
        assert calls[0][1] != calls[1][1]
        assert all(len(item[1]) <= 128 for item in calls)
        assert calls[0][2:] == ("deepseek-v4-flash", "max")
    finally:
        session.close()
        engine.dispose()


def test_multicourse_paths_keep_success_when_another_subject_path_fails(monkeypatch):
    engine, session = _session()
    try:
        owner = DBUser(public_id="b30-path-owner", username="b30-path-owner", hashed_password="hash", role="student", is_active=True)
        session.add(owner)
        session.add_all([
            DBProfileSnapshot(id="profile-a", owner_public_id=owner.public_id, profile_version="b30-a", snapshot={}, content_hash="p" * 64, trace_id="trace-a"),
            DBProfileSnapshot(id="profile-b", owner_public_id=owner.public_id, profile_version="b30-b", snapshot={}, content_hash="q" * 64, trace_id="trace-b"),
        ])
        session.add_all([
            DBDiagnosticReport(
                id="report-a", session_id="session-a", owner_public_id=owner.public_id,
                course_id="course-a", idempotency_key="report-a-key", report_version="v1",
                profile_snapshot_id="profile-a", report_data={"mastery": [{"knowledgePointId": "a-kp", "score": 0.4}]},
                content_hash="a" * 64,
            ),
            DBDiagnosticReport(
                id="report-b", session_id="session-b", owner_public_id=owner.public_id,
                course_id="course-b", idempotency_key="report-b-key", report_version="v1",
                profile_snapshot_id="profile-b", report_data={"mastery": [{"knowledgePointId": "b-kp", "score": 0.8}]},
                content_hash="b" * 64,
            ),
        ])
        session.flush()

        def fake_path(_session, *, report, **_kwargs):
            if report.id == "report-b":
                raise PathDraftError("path_draft_model_failed", "模型路径生成失败。")
            return {
                "course": {"id": report.course_id, "title": report.course_id},
                "state": "draft",
                "plan": {"id": "subject-plan-a"},
                "nodes": [{
                    "node_key": "extension-a", "node_type": "extension",
                    "title": "补充任务", "estimate_min_minutes": 10,
                    "estimate_max_minutes": 15, "prerequisites": [],
                    "extension_reason": "由诊断证据触发",
                }],
            }

        monkeypatch.setattr(multicourse, "generate_report_path", fake_path)
        result = multicourse.generate_multicourse_paths(
            session,
            user=owner,
            request=multicourse.MultiCoursePathRequest(
                report_ids=("report-a", "report-b"),
                idempotency_key="b30-path-run-001",
                time_budget_minutes=90,
            ),
            llm=_PolicyLLM(),
        )

        assert result["status"] == "partial"
        assert [item["status"] for item in result["subjects"]] == ["ready", "failed"]
        assert result["subjects"][1]["error"]["code"] == "path_draft_model_failed"
        assert result["total_plan"]["course_id"] is None
        assert result["total_plan"]["nodes"][0]["node_key"].startswith("course-a::")
    finally:
        session.close()
        engine.dispose()


def test_invalid_total_schedule_does_not_create_aggregate_draft(monkeypatch):
    engine, session = _session()
    try:
        owner = DBUser(public_id="b30-invalid-owner", username="b30-invalid-owner", hashed_password="hash", role="student", is_active=True)
        session.add(owner)
        session.add(DBProfileSnapshot(id="profile-invalid", owner_public_id=owner.public_id, profile_version="b30-invalid", snapshot={}, content_hash="r" * 64, trace_id="trace-invalid"))
        session.add(DBDiagnosticReport(
            id="report-invalid", session_id="session-invalid", owner_public_id=owner.public_id,
            course_id="course-invalid", idempotency_key="report-invalid-key", report_version="v1",
            profile_snapshot_id="profile-invalid", report_data={}, content_hash="c" * 64,
        ))
        session.flush()

        monkeypatch.setattr(
            multicourse,
            "generate_report_path",
            lambda *_args, **_kwargs: {
                "course": {"id": "course-invalid"}, "state": "draft", "plan": {"id": "plan-invalid"},
                "nodes": [_node("late", sequence=2, prerequisites=("missing",), estimate=60)],
            },
        )
        result = multicourse.generate_multicourse_paths(
            session,
            user=owner,
            request=multicourse.MultiCoursePathRequest(
                report_ids=("report-invalid",), idempotency_key="b30-invalid-run", time_budget_minutes=30,
            ),
            llm=_PolicyLLM(),
        )

        assert result["total_validation"]["status"] == "invalid"
        assert result["total_plan"] is None
        assert session.query(DBPlanDraft).count() == 0
        assert result["subjects"][0]["status"] == "ready"
    finally:
        session.close()
        engine.dispose()


def test_multicourse_api_commits_result_and_uses_governed_model(monkeypatch):
    engine, session = _session()
    user = DBUser(public_id="b30-api-owner", username="b30-api-owner", hashed_password="hash", role="student", is_active=True)
    session.add(user)
    session.commit()

    async def fake_run_db_op(operation):
        return operation(session)

    def fake_build_llm():
        return _PolicyLLM()

    def fake_orchestrate(current_session, **_kwargs):
        current_session.add(DBPlanDraft(
            owner_public_id=user.public_id, course_id=None,
            title="b30 marker", status="draft", idempotency_key="b30-api-marker",
        ))
        return {"schema_version": "p1-b30.multicourse-blueprints.v1", "status": "completed", "items": []}

    monkeypatch.setattr(diagnostic_api, "run_db_op", fake_run_db_op)
    monkeypatch.setattr(diagnostic_api, "build_diagnostic_llm", fake_build_llm)
    monkeypatch.setattr(diagnostic_api, "generate_multicourse_blueprints", fake_orchestrate)
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        response = TestClient(app).post(
            "/api/v1/diagnostics/multi-course/blueprints",
            json={"courseIds": ["course-a"], "idempotencyKey": "b30-api-run-001"},
        )
        assert response.status_code == 201, response.text
        assert session.query(DBPlanDraft).filter_by(idempotency_key="b30-api-marker").count() == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close()
        engine.dispose()


def test_multicourse_frontend_contract_exposes_selection_subject_progress_and_total_validation():
    entry = (ROOT / "frontend/src/views/EntryDiagnostic.vue").read_text(encoding="utf-8")
    session_view = (ROOT / "frontend/src/components/DiagnosticAssessmentSession.vue").read_text(encoding="utf-8")
    api = (ROOT / "frontend/src/api/diagnostics.js").read_text(encoding="utf-8")
    for marker in (
        "selectedCourseIds",
        "course-choice-list",
        "createMulticourseDiagnosticBlueprints",
        "multi_run_id",
        "每门课程的题目、知识点和来源都独立冻结",
    ):
        assert marker in entry
    for marker in (
        "createMulticourseDiagnosticPaths",
        "继续下一门课程",
        "生成并验证多科总路径",
        "multicourse-total-path-result",
    ):
        assert marker in session_view
    assert "/v1/diagnostics/multi-course/blueprints" in api
    assert "/v1/diagnostics/multi-course/paths" in api


def test_aggregate_plan_deep_link_uses_canonical_plan_endpoint_and_renders_draft():
    path_view = (ROOT / "frontend/src/views/LearningPathGraph.vue").read_text(encoding="utf-8")
    m5_api = (ROOT / "frontend/src/api/m5.js").read_text(encoding="utf-8")
    session_view = (ROOT / "frontend/src/components/DiagnosticAssessmentSession.vue").read_text(encoding="utf-8")
    for marker in (
        "getM5Plan",
        "aggregate_plan_id",
        "aggregate-plan-draft",
        "aggregatePlanContent",
        "aggregatePlanNodes",
        "aggregatePlanCourseIds",
    ):
        assert marker in path_view
    assert "`/v1/m5/plans/${encodeURIComponent(planId)}`" in m5_api
    assert "aggregate_plan_id: aggregateResult.total_plan.id" in session_view


def test_unsubmitted_diagnostic_cannot_create_report_or_learning_state():
    engine, session, owner, _course, _profile, _point, _version, work = _legacy_diagnostic_fixture()
    try:
        events_before = session.query(DBLearningEvent).count()
        profiles_before = session.query(DBProfileSnapshot).count()
        attempts_before = session.query(DBAssessmentAttempt).count()
        with pytest.raises(DiagnosticReportError) as exc_info:
            generate_diagnostic_report(
                session,
                user=owner,
                session_id=work.id,
                idempotency_key="b30-unsubmitted-report",
                llm=None,
            )
        assert exc_info.value.code == "diagnostic_report_not_ready"
        assert session.query(DBDiagnosticReport).count() == 0
        assert session.query(DBLearningEvent).count() == events_before
        assert session.query(DBProfileSnapshot).count() == profiles_before
        assert session.query(DBAssessmentAttempt).count() == attempts_before
        assert session.get(DBDiagnosticSession, work.id).status == "active"
    finally:
        session.close()
        engine.dispose()


def test_submitted_but_ungraded_answer_is_unknown_and_does_not_feed_mastery_or_events():
    engine, session, owner, _course, _profile, point, version, work = _legacy_diagnostic_fixture(
        question_type="short_answer",
    )
    try:
        save_diagnostic_response(
            session,
            user=owner,
            session_id=work.id,
            question_version_id=version.id,
            response=DiagnosticResponseInput(
                answer={"text": "待评分答案"},
                understanding_level="partial",
                duration=30,
                confidence=0.4,
                idempotency_key="b30-ungraded-response",
                saved_at=datetime.now(timezone.utc),
            ),
        )
        submit_diagnostic_session(
            session,
            user=owner,
            session_id=work.id,
            idempotency_key="b30-ungraded-submit",
        )
        events_before = session.query(DBLearningEvent).count()
        report, created = generate_diagnostic_report(
            session,
            user=owner,
            session_id=work.id,
            idempotency_key="b30-ungraded-report",
            llm=None,
        )
        assert created is True
        mastery = next(item for item in report.report_data["mastery"] if item["knowledgePointId"] == point.id)
        assert mastery["score"] is None
        assert mastery["status"] == "unknown"
        assert mastery["evidenceCount"] == 0
        assert session.query(DBAssessmentAbilityState).count() == 0
        assert session.query(DBLearningEvent).count() == events_before
        snapshot = session.get(DBProfileSnapshot, report.profile_snapshot_id)
        assert snapshot.snapshot["mastery_by_knowledge_point"][point.id]["score"] is None
    finally:
        session.close()
        engine.dispose()


def test_no_source_answer_never_becomes_accepted_mastery():
    engine, session, owner, _course, _profile, point, version, work = _legacy_diagnostic_fixture(
        question_type="single_choice",
        source_ref_ids=(),
    )
    try:
        save_diagnostic_response(
            session,
            user=owner,
            session_id=work.id,
            question_version_id=version.id,
            response=DiagnosticResponseInput(
                answer={"choice": "A"},
                understanding_level="clear",
                duration=12,
                confidence=0.9,
                idempotency_key="b30-no-source-response",
                saved_at=datetime.now(timezone.utc),
            ),
        )
        submit_diagnostic_session(
            session,
            user=owner,
            session_id=work.id,
            idempotency_key="b30-no-source-submit",
        )
        report, _ = generate_diagnostic_report(
            session,
            user=owner,
            session_id=work.id,
            idempotency_key="b30-no-source-report",
            llm=None,
        )
        item = next(entry for entry in report.report_data["mastery"] if entry["knowledgePointId"] == point.id)
        assert item["score"] is None
        assert item["status"] == "unknown"
        assert item["sourceRefIds"] == []
        assert report.report_data["summary"]["score"] is None
        assert session.query(DBLearningEvent).count() == 0
    finally:
        session.close()
        engine.dispose()


def test_catalog_and_course_guard_filter_private_and_expired_courses_and_keep_profiles_scoped():
    engine, session = _session()
    try:
        learner = DBUser(public_id="b30-catalog-learner", username="b30-catalog-learner", hashed_password="hash", role="student", is_active=True)
        owner = DBUser(public_id="b30-catalog-owner", username="b30-catalog-owner", hashed_password="hash", role="student", is_active=True)
        public = DBCourse(id="b30-public", owner_public_id=owner.public_id, version="v1", title="Public course", visibility="public", status="published", manifest_version="m1")
        member = DBCourse(id="b30-member", owner_public_id=owner.public_id, version="v2", title="Member course", visibility="private", status="published", manifest_version="m2")
        hidden = DBCourse(id="b30-hidden", owner_public_id=owner.public_id, version="v3", title="Hidden course", visibility="private", status="published", manifest_version="m3")
        expired = DBCourse(id="b30-expired", owner_public_id=owner.public_id, version="v4", title="Expired course", visibility="public", status="archived", manifest_version="m4")
        session.add_all([learner, owner, public, member, hidden, expired])
        session.add(DBCourseMembership(course_id=member.id, user_public_id=learner.public_id, role="student", status="active"))
        session.add(DBSourceDocument(id="b30-public-source", course_id=public.id, title="Public source", filename="public.md", file_format="md", content_hash="s" * 64, processing_status="ready"))
        session.add(DBSourceDocument(id="b30-member-source", course_id=member.id, title="Member source", filename="member.md", file_format="md", content_hash="t" * 64, processing_status="processing"))
        session.add_all([
            DBProfileSnapshot(id="b30-profile-public", owner_public_id=learner.public_id, legacy_student_id=learner.username, profile_version="course-public-v1", snapshot={"course_id": public.id}, content_hash="a" * 64, trace_id="trace-public"),
            DBProfileSnapshot(id="b30-profile-member", owner_public_id=learner.public_id, legacy_student_id=learner.username, profile_version="course-member-v1", snapshot={"course_id": member.id}, content_hash="b" * 64, trace_id="trace-member"),
        ])
        session.flush()

        catalog = diagnostic_generation.diagnostic_course_catalog(session, user=learner)
        catalog_ids = {item["id"] for item in catalog["courses"]}
        assert catalog_ids == {public.id, member.id}
        member_item = next(item for item in catalog["courses"] if item["id"] == member.id)
        assert member_item["version"] == "v2"
        assert member_item["sourceSummary"]["readyDocuments"] == 0
        assert diagnostic_generation._readable_course(session, course_id=member.id, user=learner).id == member.id
        with pytest.raises(DiagnosticGenerationError) as hidden_error:
            diagnostic_generation._readable_course(session, course_id=hidden.id, user=learner)
        assert hidden_error.value.code == "course_forbidden"
        with pytest.raises(DiagnosticGenerationError) as expired_error:
            diagnostic_generation._readable_course(session, course_id=expired.id, user=learner)
        assert expired_error.value.code == "course_unavailable"
        assert diagnostic_generation._latest_profile(session, learner.public_id, public.id).id == "b30-profile-public"
        assert diagnostic_generation._latest_profile(session, learner.public_id, member.id).id == "b30-profile-member"
    finally:
        session.close()
        engine.dispose()


def test_multicourse_blueprint_replay_is_idempotent_per_course_and_no_duplicate_rows(monkeypatch):
    engine, session = _session()
    try:
        owner = DBUser(public_id="b30-replay-owner", username="b30-replay-owner", hashed_password="hash", role="student", is_active=True)
        session.add(owner)
        session.flush()
        calls = []

        def fake_generate(current_session, *, user, request, llm):
            calls.append(request.course_id)
            row = DBDiagnosticBlueprint(
                owner_public_id=user.public_id,
                course_id=request.course_id,
                idempotency_key=request.idempotency_key,
                profile_snapshot_id=None,
                question_version_ids=[],
                knowledge_point_coverage=[],
                difficulty_bands={},
                source_refs=[],
                review_decision={},
                generation_stages=[],
                question_count=1,
                estimated_minutes=1,
                content_hash=(request.course_id[0] * 64),
            )
            current_session.add(row)
            current_session.flush()
            return row, True

        monkeypatch.setattr(multicourse, "generate_diagnostic_blueprint", fake_generate)
        monkeypatch.setattr(multicourse, "diagnostic_blueprint_payload", lambda _session, row: {"id": row.id, "course": {"id": row.course_id}})
        request = multicourse.MultiCourseBlueprintRequest(course_ids=("course-a", "course-b"), idempotency_key="b30-replay-run")
        first = multicourse.generate_multicourse_blueprints(session, user=owner, request=request, llm=_PolicyLLM())
        session.flush()

        def replay_generate(current_session, *, user, request, llm):
            existing = current_session.query(DBDiagnosticBlueprint).filter_by(owner_public_id=user.public_id, course_id=request.course_id, idempotency_key=request.idempotency_key).one()
            calls.append(f"replay:{request.course_id}")
            return existing, False

        monkeypatch.setattr(multicourse, "generate_diagnostic_blueprint", replay_generate)
        second = multicourse.generate_multicourse_blueprints(session, user=owner, request=request, llm=_PolicyLLM())
        assert [item["created"] for item in first["items"]] == [True, True]
        assert [item["created"] for item in second["items"]] == [False, False]
        assert session.query(DBDiagnosticBlueprint).count() == 2
        assert calls == ["course-a", "course-b", "replay:course-a", "replay:course-b"]
    finally:
        session.close()
        engine.dispose()


def test_empty_total_schedule_is_invalid_not_needs_review_and_is_read_only():
    result = multicourse.validate_total_schedule([], time_budget_minutes=90, max_days=2)
    assert result["status"] == "invalid"
    assert any(issue["code"] == "empty_day" for issue in result["issues"])
    assert result["read_only"] is True
    assert result["learning_state_written"] is False


def test_multicourse_paths_reject_foreign_reports_without_generating_subject_or_total_path():
    engine, session = _session()
    try:
        owner = DBUser(public_id="b30-report-owner", username="b30-report-owner", hashed_password="hash", role="student", is_active=True)
        foreign = DBUser(public_id="b30-report-foreign", username="b30-report-foreign", hashed_password="hash", role="student", is_active=True)
        session.add_all([owner, foreign])
        session.add(DBProfileSnapshot(id="b30-foreign-profile", owner_public_id=owner.public_id, legacy_student_id=owner.username, profile_version="b30-foreign-profile-v1", snapshot={}, content_hash="f" * 64, trace_id="b30-foreign-profile-trace"))
        session.add(DBDiagnosticReport(
            id="b30-foreign-report",
            session_id="b30-foreign-session",
            owner_public_id=owner.public_id,
            course_id="course-private",
            idempotency_key="b30-foreign-report-key",
            report_version="v1",
            profile_snapshot_id="b30-foreign-profile",
            report_data={},
            content_hash="r" * 64,
        ))
        session.flush()
        result = multicourse.generate_multicourse_paths(
            session,
            user=foreign,
            request=multicourse.MultiCoursePathRequest(
                report_ids=("b30-foreign-report",),
                idempotency_key="b30-foreign-path-key",
                time_budget_minutes=90,
            ),
            llm=_PolicyLLM(),
        )
        assert result["status"] == "failed"
        assert result["subjects"][0]["error"]["code"] == "diagnostic_report_forbidden"
        assert result["total_plan"] is None
        assert session.query(DBPlanDraft).count() == 0
    finally:
        session.close()
        engine.dispose()


def test_multicourse_total_plan_replay_reuses_canonical_draft(monkeypatch):
    engine, session = _session()
    try:
        owner = DBUser(public_id="b30-total-replay-owner", username="b30-total-replay-owner", hashed_password="hash", role="student", is_active=True)
        session.add(owner)
        session.add(DBProfileSnapshot(id="b30-total-replay-profile", owner_public_id=owner.public_id, legacy_student_id=owner.username, profile_version="b30-total-replay-profile-v1", snapshot={}, content_hash="g" * 64, trace_id="b30-total-replay-profile-trace"))
        session.add_all([
            DBDiagnosticReport(id="b30-total-report-a", session_id="b30-total-session-a", owner_public_id=owner.public_id, course_id="course-a", idempotency_key="b30-total-report-a-key", report_version="v1", profile_snapshot_id="b30-total-replay-profile", report_data={}, content_hash="a" * 64),
            DBDiagnosticReport(id="b30-total-report-b", session_id="b30-total-session-b", owner_public_id=owner.public_id, course_id="course-b", idempotency_key="b30-total-report-b-key", report_version="v1", profile_snapshot_id="b30-total-replay-profile", report_data={}, content_hash="b" * 64),
        ])
        session.flush()
        calls = []

        def fake_path(_session, *, report, **_kwargs):
            calls.append(report.id)
            return {
                "course": {"id": report.course_id, "title": report.course_id},
                "state": "draft",
                "plan": {"id": f"subject-{report.course_id}"},
                "nodes": [{
                    "node_key": "extension",
                    "node_type": "extension",
                    "title": f"{report.course_id} 补充任务",
                    "prerequisites": [],
                    "estimate_min_minutes": 10,
                    "estimate_max_minutes": 10,
                    "required": True,
                }],
            }

        monkeypatch.setattr(multicourse, "generate_report_path", fake_path)
        request = multicourse.MultiCoursePathRequest(
            report_ids=("b30-total-report-a", "b30-total-report-b"),
            idempotency_key="b30-total-replay-key",
            time_budget_minutes=90,
        )
        first = multicourse.generate_multicourse_paths(session, user=owner, request=request, llm=_PolicyLLM())
        session.flush()
        second = multicourse.generate_multicourse_paths(session, user=owner, request=request, llm=_PolicyLLM())
        assert first["status"] == "completed"
        assert second["status"] == "completed"
        assert first["total_plan"]["id"] == second["total_plan"]["id"]
        assert session.query(DBPlanDraft).count() == 1
        assert session.query(DBPlanDraft).one().idempotency_key == request.idempotency_key
        assert calls == ["b30-total-report-a", "b30-total-report-b", "b30-total-report-a", "b30-total-report-b"]
    finally:
        session.close()
        engine.dispose()


def test_diagnostic_model_policy_rejects_non_max_or_fallback_backend():
    with pytest.raises(DiagnosticGenerationError) as wrong_reasoning:
        diagnostic_generation._require_model_policy(SimpleNamespace(
            model="deepseek-v4-flash",
            thinking_mode="enabled",
            reasoning_effort="high",
        ))
    assert wrong_reasoning.value.code == "diagnostic_model_policy_invalid"

    with pytest.raises(DiagnosticGenerationError) as wrong_model:
        diagnostic_generation._require_model_policy(SimpleNamespace(
            model="some-other-model",
            thinking_mode="enabled",
            reasoning_effort="max",
        ))
    assert wrong_model.value.code == "diagnostic_model_policy_invalid"
