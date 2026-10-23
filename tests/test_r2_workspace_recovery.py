from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.competition_demo_seed import seed_competition_demo
from app.database import Base, DBGenerationTask, DBTaskStep, DBTutorContextSession, DBUser
from app.m5_operations import cancel_task
from app.m5_tasks import retry_capability_step
from app.m5_workspace import (
    TutorContextSpec,
    TutorReadingPosition,
    create_tutor_context,
    workspace_overview,
)


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    seed_competition_demo(session)
    session.commit()
    return engine, session


def _context_spec(workspace, item, *, key, position):
    return TutorContextSpec(
        idempotency_key=key,
        course_id=workspace["course"]["id"],
        context_mode="current_resource",
        primary_object_type="workspace_object",
        primary_object_id=item["id"],
        selected_source_ref_ids=tuple(item["context"]["source_ref_ids"]),
        reading_position=position,
    )


def test_workspace_restores_latest_owned_object_position_and_code_content():
    engine, session = _session()
    try:
        learner = session.query(DBUser).filter_by(username="lzz").one()
        workspace = workspace_overview(session, current_user=learner)
        document = next(item for item in workspace["learning_objects"] if item["object_type"] == "document")
        code = next(item for item in workspace["learning_objects"] if item["object_type"] == "code")

        first, _ = create_tutor_context(
            session,
            current_user=learner,
            spec=_context_spec(
                workspace,
                document,
                key="r2-10-document-position",
                position=TutorReadingPosition(kind="section", label=document["render"]["section"]),
            ),
        )
        second, _ = create_tutor_context(
            session,
            current_user=learner,
            spec=_context_spec(
                workspace,
                code,
                key="r2-10-code-position",
                position=TutorReadingPosition(kind="line", label="代码第 4 行", line_number=4),
            ),
        )
        first.last_used_at = datetime.utcnow() - timedelta(minutes=5)
        second.last_used_at = datetime.utcnow()
        session.commit()

        restored = workspace_overview(session, current_user=learner)
        restore = restored["restore"]["context"]
        restored_code = next(item for item in restored["learning_objects"] if item["id"] == restore["object_id"])

        assert restore["context_session_id"] == second.id
        assert restore["object_id"] == code["id"]
        assert restore["reading_position"] == {
            "kind": "line",
            "label": "代码第 4 行",
            "line_number": 4,
            "char_offset": None,
            "timestamp_seconds": None,
        }
        assert restored_code["render"]["content"] == code["render"]["content"]

        outsider = session.query(DBUser).filter(
            DBUser.role == "student", DBUser.public_id != learner.public_id,
        ).first()
        outsider_workspace = workspace_overview(session, current_user=outsider)
        assert outsider_workspace["restore"]["context"] is None
    finally:
        session.close()
        engine.dispose()


def test_workspace_projects_cancel_and_retry_capabilities_from_existing_task_state():
    engine, session = _session()
    try:
        learner = session.query(DBUser).filter_by(username="lzz").one()
        task = DBGenerationTask(
            id="r2-10-recovery-task",
            owner_public_id=learner.public_id,
            course_id="demo-course-rag-trust-v1",
            trace_id="r2-10-recovery-trace",
            status="running",
            progress=0.25,
            capability="m5.capability.experiment",
            model="deterministic",
            idempotency_key="r2-10-recovery-task-key",
        )
        resource_bundle_task = DBGenerationTask(
            id="r2-10-newer-resource-bundle-task",
            owner_public_id=learner.public_id,
            course_id="demo-course-rag-trust-v1",
            trace_id="r2-10-resource-bundle-trace",
            status="running",
            progress=0.5,
            capability="learning_resource_bundle.generate",
            model="deterministic",
            idempotency_key="r2-10-resource-bundle-task-key",
            updated_at=datetime.utcnow() + timedelta(minutes=1),
        )
        session.add_all([task, resource_bundle_task])
        session.flush()
        session.add_all([
            DBTaskStep(
                task_id=task.id,
                sequence=1,
                attempt=1,
                agent_role="context_assembler",
                status="completed",
            ),
            DBTaskStep(
                task_id=task.id,
                sequence=2,
                attempt=1,
                agent_role="capability_agent",
                status="failed",
                error_code="provider_timeout",
            ),
        ])
        session.commit()

        overview = workspace_overview(session, current_user=learner)
        projected = overview["restore"]["task"]
        assert projected["id"] == task.id
        assert projected["can_cancel"] is True
        assert projected["retryable_step_sequences"] == [2]
        assert [item["id"] for item in overview["restore"]["recent_tasks"]] == [task.id]
        assert [item["id"] for item in overview["running_tasks"]] == [task.id]

        retry_capability_step(
            session, task_id=task.id, owner_public_id=learner.public_id, sequence=2,
        )
        session.commit()
        retried = workspace_overview(session, current_user=learner)["restore"]["task"]
        assert retried["retryable_step_sequences"] == []

        cancel_task(session, task_id=task.id, owner_public_id=learner.public_id)
        session.commit()
        cancelled = workspace_overview(session, current_user=learner)["restore"]["task"]
        assert cancelled["status"] == "cancelled"
        assert cancelled["can_cancel"] is False
    finally:
        session.close()
        engine.dispose()


def test_frontend_uses_server_restore_url_state_and_formal_task_controls():
    frontend = Path("frontend/src/views/LearningWorkspace.vue").read_text(encoding="utf-8")
    api_source = Path("frontend/src/api/m5.js").read_text(encoding="utf-8")

    assert "workspaceData.restore?.context" in frontend
    assert "workspaceData?.restore?.recent_tasks" in frontend
    assert "const restoredPosition = restoredReadingPosition.value?.position" in frontend
    assert "typeof restoredPosition === 'object'" in frontend
    assert "object_id" in frontend
    assert "task_id" in frontend
    assert "persistWorkspacePosition" in frontend
    assert "cancelWorkspaceTask" in frontend
    assert "retryWorkspaceTaskStep" in frontend
    assert "workspace-task-cancel" in frontend
    assert "workspace-task-retry-" in frontend
    assert "/tasks/${encodeURIComponent(taskId)}/cancel" in api_source
    assert "/steps/${sequence}/retry" in api_source
