from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.competition_demo_seed import seed_competition_demo
from app.database import (
    Base,
    DBArtifact,
    DBArtifactVersion,
    DBGenerationTask,
    DBModelCall,
    DBQualityCheck,
    DBTaskEvent,
    DBUser,
)
from app.m1_repository import append_task_event
from app.m5_capabilities import RuntimeAvailability
import app.m5_api as m5_api
from app.m5_tasks import (
    complete_capability_step,
    fail_capability_step,
    retry_capability_step,
    schedule_capability_rework,
    start_capability_step,
    start_capability_task,
)
from app.m5_workspace import TutorContextSpec, TutorReadingPosition, create_tutor_context, workspace_overview
from app.workspace_actions import WorkspaceActionRequest, execute_workspace_action
from app.workspace_timeline import WorkspaceTimelineError, build_workspace_task_timeline


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    seed_competition_demo(session)
    session.commit()
    return engine, session


def _runtime():
    return RuntimeAvailability(deterministic_text_model=True, retrieval=True, sandbox_mode="trusted_local")


def _task(session, learner, key="timeline-task-001"):
    workspace = workspace_overview(session, current_user=learner)
    item = next(value for value in workspace["learning_objects"] if value["object_type"] == "experiment")
    context, _ = create_tutor_context(
        session,
        current_user=learner,
        spec=TutorContextSpec(
            idempotency_key=f"{key}-context",
            course_id=workspace["course"]["id"],
            context_mode="current_resource",
            primary_object_type="workspace_object",
            primary_object_id=item["id"],
            selected_source_ref_ids=tuple(item["context"]["source_ref_ids"]),
            selected_text="",
            reading_position=TutorReadingPosition(kind="object", label=item["title"]),
        ),
    )
    result = execute_workspace_action(
        session,
        current_user=learner,
        request=WorkspaceActionRequest(
            context_session_id=context.id,
            action="experiment",
            idempotency_key=key,
        ),
        runtime=_runtime(),
        model="deterministic",
    )
    session.commit()
    return workspace["course"]["id"], result["task"]["task_id"]


def test_timeline_projects_queued_task_without_internal_worker_noise():
    engine, session = _session()
    try:
        learner = session.query(DBUser).filter_by(username="lzz").one()
        course_id, task_id = _task(session, learner)
        append_task_event(
            session,
            task_id=task_id,
            event_type="worker.heartbeat",
            payload={"worker_id": "internal-worker", "lease_seconds": 60},
        )
        session.commit()

        result = build_workspace_task_timeline(
            session, current_user=learner, task_id=task_id, course_id=course_id,
        )

        assert result["task"]["status_label"] == "等待处理"
        assert result["summary"]["stage_count"] == 4
        assert result["summary"]["current_phase"] == "准备学习上下文"
        assert [item["label"] for item in result["items"]][:2] == ["任务已创建", "任务要求已确认"]
        assert all("worker" not in str(item).lower() for item in result["items"])
        assert result["boundaries"] == {
            "internal_worker_events_hidden": True,
            "raw_prompts_hidden": True,
            "raw_error_messages_hidden": True,
        }
    finally:
        session.close()
        engine.dispose()


def test_timeline_exposes_failure_retry_rework_model_and_quality_in_user_language():
    engine, session = _session()
    try:
        learner = session.query(DBUser).filter_by(username="lzz").one()
        course_id, task_id = _task(session, learner, "timeline-rework-001")
        start_capability_task(session, task_id=task_id, owner_public_id=learner.public_id)
        start_capability_step(session, task_id=task_id, owner_public_id=learner.public_id, sequence=1)
        complete_capability_step(session, task_id=task_id, owner_public_id=learner.public_id, sequence=1)
        start_capability_step(session, task_id=task_id, owner_public_id=learner.public_id, sequence=2)
        complete_capability_step(session, task_id=task_id, owner_public_id=learner.public_id, sequence=2)
        schedule_capability_rework(
            session,
            task_id=task_id,
            owner_public_id=learner.public_id,
            sequence=2,
            reason_code="schema_invalid",
        )
        start_capability_step(session, task_id=task_id, owner_public_id=learner.public_id, sequence=2)
        failed = fail_capability_step(
            session,
            task_id=task_id,
            owner_public_id=learner.public_id,
            sequence=2,
            error_code="provider_timeout",
            retryable=True,
        )
        failed.error_message = "secret stack and prompt must never be returned"
        retry_capability_step(session, task_id=task_id, owner_public_id=learner.public_id, sequence=2)
        task = session.query(DBGenerationTask).filter_by(id=task_id).one()
        session.add(DBModelCall(
            trace_id=task.trace_id,
            task_id=task_id,
            owner_public_id=learner.public_id,
            course_id=course_id,
            capability="experiment",
            prompt_version="test-v1",
            provider="local",
            model="deterministic",
            status="failed",
            error_code="provider_timeout",
        ))
        content = '{"kind":"timeline-test"}'
        artifact = DBArtifact(
            id="art-r2-timeline-test",
            owner_public_id=learner.public_id,
            course_id=course_id,
            artifact_type="interactive_skill_artifact",
            title="时间线测试产物",
            status="reviewing",
            creating_task_id=task_id,
        )
        version = DBArtifactVersion(
            id="av-r2-timeline-test",
            artifact_id=artifact.id,
            version_number=1,
            content=content,
            content_format="json",
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            created_by_public_id=learner.public_id,
            created_task_id=task_id,
        )
        artifact.current_version_id = version.id
        session.add_all([artifact, version])
        session.flush()
        session.add(DBQualityCheck(
            artifact_version_id=version.id,
            trace_id=task.trace_id,
            check_type="type_schema",
            checker_version="test-v1",
            status="failed",
            details={"private_debug": "must not be returned"},
        ))
        session.commit()

        result = build_workspace_task_timeline(
            session, current_user=learner, task_id=task_id, course_id=course_id,
        )
        labels = [item["label"] for item in result["items"]]
        details = " ".join(item["detail"] for item in result["items"])

        assert "已安排局部返工" in labels
        assert "已安排重试" in labels
        assert "生成学习内容未完成" in labels
        assert "AI 生成未完成" in labels
        assert "结构检查" in labels
        assert "secret stack" not in details
        assert "private_debug" not in str(result)
        assert "模型服务响应超时" in details
        stage = next(item for item in result["stages"] if item["sequence"] == 2)
        assert stage["attempt_count"] == 3
        assert stage["has_rework"] is True
        assert result["summary"]["failure_count"] >= 2
        assert result["summary"]["rework_count"] == 1
        assert result["summary"]["model_call_count"] == 1
        assert result["summary"]["quality_check_count"] == 1
    finally:
        session.close()
        engine.dispose()


def test_timeline_rejects_cross_owner_and_course_conflict():
    engine, session = _session()
    try:
        learner = session.query(DBUser).filter_by(username="lzz").one()
        other = session.query(DBUser).filter(DBUser.role == "student", DBUser.public_id != learner.public_id).first()
        course_id, task_id = _task(session, learner, "timeline-scope-001")

        with pytest.raises(WorkspaceTimelineError) as forbidden:
            build_workspace_task_timeline(
                session, current_user=other, task_id=task_id, course_id=course_id,
            )
        assert forbidden.value.code == "workspace_timeline_forbidden"

        with pytest.raises(WorkspaceTimelineError) as conflict:
            build_workspace_task_timeline(
                session, current_user=learner, task_id=task_id, course_id="another-course",
            )
        assert conflict.value.code == "workspace_timeline_course_conflict"
    finally:
        session.close()
        engine.dispose()


def test_timeline_api_is_authenticated_and_frontend_uses_user_facing_projection(monkeypatch):
    engine, session = _session()
    app = FastAPI()
    app.include_router(m5_api.router)

    async def fake_run_db_op(operation, *args, **kwargs):
        return operation(session, *args, **kwargs)

    monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
    learner = session.query(DBUser).filter_by(username="lzz").one()
    course_id, task_id = _task(session, learner, "timeline-api-001")
    app.dependency_overrides[get_current_user] = lambda: learner
    client = TestClient(app)
    try:
        response = client.get(
            f"/api/v1/m5/workspace/tasks/{task_id}/timeline",
            params={"course_id": course_id},
        )
        assert response.status_code == 200
        assert response.json()["schema_version"] == "r2.workspace-task-timeline.v1"

        frontend = Path("frontend/src/views/LearningWorkspace.vue").read_text(encoding="utf-8")
        api_source = Path("frontend/src/api/m5.js").read_text(encoding="utf-8")
        assert "workspace-agent-timeline" in frontend
        assert "Agent 任务进度" in frontend
        assert "getM5WorkspaceTaskTimeline" in frontend
        assert "restoreLatestActionTask" in frontend
        assert "workspaceData?.running_tasks?.[0]" in frontend
        assert "/workspace/tasks/${encodeURIComponent(taskId)}/timeline" in api_source
        from app.main import app as main_app

        assert set(main_app.openapi()["paths"]["/api/v1/m5/workspace/tasks/{task_id}/timeline"]) == {"get"}
    finally:
        client.close()
        session.close()
        engine.dispose()
