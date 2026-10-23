from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.m5_api as m5_api
from app.competition_demo_seed import seed_competition_demo
from app.dashboard_summary import build_dashboard_summary
from app.database import (
    Base,
    DBCourseMembership,
    DBAssessmentQuestionVersion,
    DBDiagnosticBlueprint,
    DBDiagnosticReport,
    DBDiagnosticSession,
    DBLearningEvent,
    DBLearningPath,
    DBPathNode,
    DBProfileSnapshot,
    DBReviewPlan,
    DBUser,
)
from app.m5_workspace import workspace_overview


ROOT = Path(__file__).resolve().parents[1]
COURSE_ID = "demo-course-rag-trust-v1"


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def _run(awaitable):
    return asyncio.run(awaitable)


def test_today_tasks_are_capped_explainable_and_shared_by_api_and_workspace(monkeypatch):
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()

        async def isolated_run_db_op(operation, *args, **kwargs):
            return operation(session, *args, **kwargs)

        monkeypatch.setattr(m5_api, "run_db_op", isolated_run_db_op)
        workspace = workspace_overview(session, current_user=learner, course_id=COURSE_ID)
        api = _run(m5_api.get_today_work(course_id=COURSE_ID, current_user=learner))
        tasks = workspace["today_tasks"]

        assert 1 <= len(tasks) <= 3
        assert [item["node_id"] for item in tasks] == [item["node_id"] for item in api["items"]]
        assert tasks[0]["node_id"] == "demo-task-lzz-read-01"
        assert tasks[0]["task_kind"] == "path"
        assert tasks[0]["continue_route"] == "/workspace?node_id=demo-task-lzz-read-01"
        assert [item["task_kind"] for item in tasks[1:]] == ["review", "review"]
        assert all(item["estimate_minutes"] for item in tasks)
        assert all(item["completion_criteria"] for item in tasks)
        assert all(item["recommendation_reason"] for item in tasks)
        assert all(item["continue_route"] for item in tasks)
        assert workspace["next_action"]["route"] == tasks[0]["continue_route"]

        summary = build_dashboard_summary(
            session, current_user=learner, course_id=COURSE_ID,
        )
        assert summary["state"] == "ready"
        assert summary["primary_action"]["route"] == workspace["next_action"]["route"]
        assert summary["primary_task"]["strategy"]
        assert summary["primary_task"]["recommended_resource"]
        assert summary["primary_task"]["estimate_minutes"]
        assert summary["primary_task"]["completion_criteria"]
        assert summary["primary_task"]["source_refs"]
        assert all(item["source_refs"] for item in summary["metrics"][:3])

        first = session.get(DBPathNode, "demo-task-lzz-read-01")
        first.status = "completed"
        session.commit()
        advanced = workspace_overview(session, current_user=learner, course_id=COURSE_ID)
        assert advanced["today_tasks"][0]["node_id"] == "demo-task-lzz-lab-01"
        assert advanced["next_action"]["route"] == "/workspace?node_id=demo-task-lzz-lab-01"
    finally:
        session.close()
        engine.dispose()


def test_dashboard_summary_handles_course_onboarding_diagnostic_and_path_boundaries():
    engine, session = _session()
    try:
        learner = DBUser(
            public_id="usr-dashboard-boundary", username="dashboard-boundary",
            hashed_password="hash", role="student",
        )
        session.add(learner)
        session.commit()

        summary = build_dashboard_summary(session, current_user=learner)
        assert summary["state"] == "course_required"
        assert summary["primary_action"] == {
            "label": "选择预置课程", "route": "/knowledge",
        }

        seed_competition_demo(session)
        session.add(
            DBCourseMembership(
                id="cm-dashboard-boundary", course_id=COURSE_ID,
                user_public_id=learner.public_id, role="student", status="active",
            )
        )
        session.commit()

        summary = build_dashboard_summary(
            session, current_user=learner, course_id=COURSE_ID,
        )
        assert summary["state"] == "onboarding_required"
        assert summary["primary_action"]["route"] == "/onboarding"

        session.add(DBProfileSnapshot(
            id="ps-dashboard-onboarding", owner_public_id=learner.public_id,
            profile_version="onboarding.initial.v1", snapshot={"course_id": COURSE_ID},
            content_hash="onboarding", trace_id="trace-onboarding",
        ))
        session.commit()
        summary = build_dashboard_summary(
            session, current_user=learner, course_id=COURSE_ID,
        )
        assert summary["state"] == "diagnostic_required"
        assert summary["primary_action"]["route"] == (
            f"/workspace/assessment/entry?course_id={COURSE_ID}"
        )

        question_version_id = session.query(DBAssessmentQuestionVersion.id).first()[0]
        session.add_all([
            DBDiagnosticBlueprint(
                id="diagbp-dashboard", owner_public_id=learner.public_id,
                course_id=COURSE_ID, idempotency_key="dashboard-blueprint",
                profile_snapshot_id="ps-dashboard-onboarding",
                question_version_ids=[question_version_id], question_count=1,
                estimated_minutes=5, content_hash="blueprint",
            ),
            DBDiagnosticSession(
                id="diagsession-dashboard", owner_public_id=learner.public_id,
                blueprint_id="diagbp-dashboard", status="submitted",
                current_question_version_id=question_version_id,
            ),
        ])
        session.commit()
        session.add(
            DBDiagnosticReport(
                id="diagreport-dashboard", session_id="diagsession-dashboard",
                owner_public_id=learner.public_id, course_id=COURSE_ID,
                idempotency_key="dashboard-report", attempt_ids=[],
                profile_snapshot_id="ps-dashboard-onboarding", report_data={},
                content_hash="report",
            )
        )
        session.commit()
        summary = build_dashboard_summary(
            session, current_user=learner, course_id=COURSE_ID,
        )
        assert summary["state"] == "path_required"
        assert summary["primary_action"]["route"] == (
            f"/workspace/path?course_id={COURSE_ID}"
        )
    finally:
        session.close()
        engine.dispose()


def test_dashboard_summary_is_read_only_and_api_uses_authenticated_owner(monkeypatch):
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        tracked_models = (
            DBLearningEvent, DBProfileSnapshot, DBLearningPath, DBReviewPlan,
        )
        before = {model.__tablename__: session.query(model).count() for model in tracked_models}

        first = build_dashboard_summary(
            session, current_user=learner, course_id=COURSE_ID,
        )
        second = build_dashboard_summary(
            session, current_user=learner, course_id=COURSE_ID,
        )
        session.expire_all()
        after = {model.__tablename__: session.query(model).count() for model in tracked_models}

        assert first == second
        assert first["read_only"] is True
        assert before == after

        seen = {}

        async def isolated_run_db_op(operation, *args, **kwargs):
            seen["payload"] = operation(session, *args, **kwargs)
            return seen["payload"]

        monkeypatch.setattr(m5_api, "run_db_op", isolated_run_db_op)
        response = _run(m5_api.get_dashboard_summary(
            course_id=COURSE_ID, current_user=learner,
        ))
        assert response == seen["payload"]
        assert response["traceability"]["learning_path_id"]

        from app.main import app

        assert set(app.openapi()["paths"]["/api/v1/m5/dashboard"]) == {"get"}
    finally:
        session.close()
        engine.dispose()


def test_dashboard_and_workspace_render_the_same_today_task_contract():
    dashboard = (ROOT / "frontend/src/views/Dashboard.vue").read_text(encoding="utf-8")
    workspace = (ROOT / "frontend/src/views/LearningWorkspace.vue").read_text(encoding="utf-8")
    api = (ROOT / "frontend/src/api/m5.js").read_text(encoding="utf-8")

    assert "getM5WorkspaceOverview" in dashboard
    assert "getM5DashboardSummary" in dashboard
    assert 'data-testid="dashboard-today-tasks"' in dashboard
    assert dashboard.count('data-testid="dashboard-primary-action"') == 1
    assert "focus.completion_criteria" in dashboard
    assert "focus.reason" in dashboard
    assert "openPrimaryAction" in dashboard
    assert "dashboardSummary.value?.trend || []" in dashboard
    assert "较上周稳步提升" not in dashboard
    assert "24, 31, 39, 47, 58, 66, 72" not in dashboard
    assert "getM5TodayWork(courseId = '')" in api
    assert "workspace-today-task-${index}" in workspace
    assert "item.completion_criteria" in workspace
    assert "item.recommendation_reason" in workspace
    assert "item.task_kind === 'review'" in workspace
