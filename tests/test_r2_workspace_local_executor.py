from __future__ import annotations

from dataclasses import replace

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
    DBQualityCheck,
    DBTaskEvent,
    DBTaskStep,
    DBUser,
)
from app.m5_capabilities import RuntimeAvailability
import app.m5_api as m5_api
from app.m5_workspace import TutorContextSpec, TutorReadingPosition, create_tutor_context, workspace_overview
from app.workspace_actions import WorkspaceActionRequest, execute_workspace_action
from app.workspace_local_executor import (
    WorkspaceLocalExecutionError,
    execute_deterministic_workspace_task,
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


def _runtime():
    return RuntimeAvailability(
        deterministic_text_model=True,
        retrieval=True,
        sandbox_mode="trusted_local",
    )


def _experiment_task(session, learner, *, key: str, model: str = "deterministic"):
    workspace = workspace_overview(session, current_user=learner)
    item = next(value for value in workspace["learning_objects"] if value["object_type"] == "document")
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
            selected_text=(item["render"].get("excerpt") or "")[:40],
            reading_position=TutorReadingPosition(
                kind="section", label=item["render"].get("section") or item["title"],
            ),
        ),
    )
    result = execute_workspace_action(
        session,
        current_user=learner,
        request=WorkspaceActionRequest(
            context_session_id=context.id,
            action="experiment",
            idempotency_key=key,
            instruction="生成混合检索 Recall@K 调优实验。",
        ),
        runtime=_runtime(),
        model=model,
    )
    session.commit()
    return result["task"]["task_id"]


def test_local_executor_records_failure_retry_quality_and_completed_artifact():
    engine, session = _session()
    try:
        learner = session.query(DBUser).filter_by(username="lzz").one()
        task_id = _experiment_task(session, learner, key="r2-local-executor-001")

        result = execute_deterministic_workspace_task(
            session, task_id=task_id, owner_public_id=learner.public_id,
        )
        session.commit()

        task = session.query(DBGenerationTask).filter_by(id=task_id).one()
        artifact = session.query(DBArtifact).filter_by(id=result["artifact_id"]).one()
        version = session.query(DBArtifactVersion).filter_by(id=result["version_id"]).one()
        steps = session.query(DBTaskStep).filter_by(task_id=task_id).order_by(
            DBTaskStep.sequence, DBTaskStep.attempt,
        ).all()
        events = session.query(DBTaskEvent).filter_by(task_id=task_id).order_by(DBTaskEvent.sequence).all()
        checks = session.query(DBQualityCheck).filter_by(artifact_version_id=version.id).all()

        assert task.status == "completed"
        assert task.progress == 1.0
        assert artifact.status == "approved"
        assert artifact.creating_task_id == task_id
        assert artifact.current_version_id == version.id
        assert version.content_format == "json"
        quality_attempts = [step for step in steps if step.agent_role == "quality_checker"]
        assert [(step.attempt, step.status, step.error_code) for step in quality_attempts] == [
            (1, "failed", "source_ref_missing"),
            (2, "completed", ""),
        ]
        assert any(event.event_type == "task_step.retry_scheduled" for event in events)
        assert any(event.event_type == "generation_task.completed" for event in events)
        assert any(
            check.check_type == "source_binding"
            and check.status == "failed"
            and "局部返工" in (check.details or {}).get("public_summary", "")
            for check in checks
        )
        assert {
            (check.check_type, check.status)
            for check in checks
            if check.status == "passed"
        } == {
            ("source_binding", "passed"),
            ("type_schema", "passed"),
            ("runtime", "passed"),
        }

        replay = execute_deterministic_workspace_task(
            session, task_id=task_id, owner_public_id=learner.public_id,
        )
        assert replay == {"task_id": task_id, "artifact_id": artifact.id, "created": False}
        assert session.query(DBArtifact).filter_by(creating_task_id=task_id).count() == 1
    finally:
        session.close()
        engine.dispose()


def test_local_executor_rejects_foreign_owner_and_non_deterministic_task():
    engine, session = _session()
    try:
        learner = session.query(DBUser).filter_by(username="lzz").one()
        other = session.query(DBUser).filter(
            DBUser.role == "student", DBUser.public_id != learner.public_id,
        ).first()
        task_id = _experiment_task(session, learner, key="r2-local-owner-001")

        with pytest.raises(WorkspaceLocalExecutionError) as forbidden:
            execute_deterministic_workspace_task(
                session, task_id=task_id, owner_public_id=other.public_id,
            )
        assert forbidden.value.code == "workspace_local_task_forbidden"

        external_task_id = _experiment_task(
            session, learner, key="r2-local-model-001", model="external-model",
        )
        with pytest.raises(WorkspaceLocalExecutionError) as unsupported:
            execute_deterministic_workspace_task(
                session, task_id=external_task_id, owner_public_id=learner.public_id,
            )
        assert unsupported.value.code == "workspace_local_model_required"
    finally:
        session.close()
        engine.dispose()


def test_local_executor_api_maps_cross_owner_to_403(monkeypatch):
    engine, session = _session()
    app = FastAPI()
    app.include_router(m5_api.router)

    async def fake_run_db_op(operation, *args, **kwargs):
        return operation(session, *args, **kwargs)

    learner = session.query(DBUser).filter_by(username="lzz").one()
    other = session.query(DBUser).filter(
        DBUser.role == "student", DBUser.public_id != learner.public_id,
    ).first()
    task_id = _experiment_task(session, learner, key="r2-local-api-owner-001")
    monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
    monkeypatch.setattr(
        m5_api,
        "CONFIG",
        replace(
            m5_api.CONFIG,
            demo_mode=True,
            llm_provider="deterministic",
            llm_model="deterministic",
        ),
    )
    app.dependency_overrides[get_current_user] = lambda: other
    client = TestClient(app)
    try:
        response = client.post(f"/api/v1/m5/workspace/tasks/{task_id}/execute-local-demo")
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "workspace_local_task_forbidden"
    finally:
        client.close()
        session.close()
        engine.dispose()
