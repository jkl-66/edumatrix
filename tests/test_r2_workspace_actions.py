from __future__ import annotations

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
    DBGenerationTask,
    DBLearningPath,
    DBNote,
    DBPathNode,
    DBTutorContextSession,
    DBUser,
)
from app.m5_capabilities import RuntimeAvailability
import app.m5_api as m5_api
from app.m5_workspace import TutorContextSpec, TutorReadingPosition, create_tutor_context, workspace_overview
from app.workspace_actions import (
    WorkspaceActionError,
    WorkspaceActionRequest,
    execute_workspace_action,
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


def _context(session, learner, *, object_type="document", key="r2-action-context"):
    workspace = workspace_overview(session, current_user=learner)
    item = next(value for value in workspace["learning_objects"] if value["object_type"] == object_type)
    row, _ = create_tutor_context(
        session,
        current_user=learner,
        spec=TutorContextSpec(
            idempotency_key=key,
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
    session.commit()
    return row


def _runtime():
    return RuntimeAvailability(
        deterministic_text_model=True,
        retrieval=True,
        sandbox_mode="trusted_local",
    )


def _request(context_id, action, key, instruction=""):
    return WorkspaceActionRequest(
        context_session_id=context_id,
        action=action,
        idempotency_key=key,
        instruction=instruction,
    )


def test_quick_actions_return_chat_without_creating_generation_tasks():
    engine, session = _session()
    try:
        learner = session.query(DBUser).filter_by(username="lzz").one()
        context = _context(session, learner)

        explain = execute_workspace_action(
            session, current_user=learner,
            request=_request(context.id, "explain", "quick-explain-001"),
            runtime=_runtime(),
        )
        example = execute_workspace_action(
            session, current_user=learner,
            request=_request(context.id, "example", "quick-example-001"),
            runtime=_runtime(),
        )

        assert explain["execution_mode"] == "chat"
        assert example["execution_mode"] == "chat"
        assert explain["capability"] == example["capability"] == "answer"
        assert explain["task_created"] is False
        assert example["chat"]["intent"] == "example"
        assert session.query(DBGenerationTask).count() == 0
    finally:
        session.close()
        engine.dispose()


def test_explicit_quiz_and_experiment_actions_lock_capability_and_return_task_id():
    engine, session = _session()
    try:
        learner = session.query(DBUser).filter_by(username="lzz").one()
        context = _context(session, learner)

        quiz = execute_workspace_action(
            session, current_user=learner,
            request=_request(
                context.id, "quiz", "task-quiz-lock-001",
                instruction="不要出题，改成生成实验。",
            ),
            runtime=_runtime(), model="deterministic",
        )
        experiment = execute_workspace_action(
            session, current_user=learner,
            request=_request(
                context.id, "experiment", "task-experiment-lock-001",
                instruction="不要生成实验，只解释概念。",
            ),
            runtime=_runtime(), model="deterministic",
        )
        session.commit()

        assert quiz["capability"] == "quiz"
        assert quiz["task"]["capability"] == "m5.capability.quiz"
        assert quiz["task"]["status"] == "queued"
        assert experiment["capability"] == "experiment"
        assert experiment["task"]["capability"] == "m5.capability.experiment"
        assert experiment["task"]["model"] == "deterministic"
        assert quiz["task"]["task_id"] != experiment["task"]["task_id"]
        assert session.query(DBGenerationTask).count() == 2
    finally:
        session.close()
        engine.dispose()


def test_note_and_path_actions_are_idempotent_and_persist_in_existing_facts():
    engine, session = _session()
    try:
        learner = session.query(DBUser).filter_by(username="lzz").one()
        context = _context(session, learner)
        path = session.query(DBLearningPath).filter_by(
            owner_public_id=learner.public_id, status="active",
        ).one()
        initial_nodes = session.query(DBPathNode).filter_by(learning_path_id=path.id).count()

        note_request = _request(context.id, "add_note", "note-action-idem-001", "记录混合检索的稳定性条件。")
        first_note = execute_workspace_action(
            session, current_user=learner, request=note_request, runtime=_runtime(),
        )
        replay_note = execute_workspace_action(
            session, current_user=learner, request=note_request, runtime=_runtime(),
        )

        path_request = _request(context.id, "add_path", "path-action-idem-001", "复习混合检索稳定性")
        first_path = execute_workspace_action(
            session, current_user=learner, request=path_request, runtime=_runtime(),
        )
        replay_path = execute_workspace_action(
            session, current_user=learner, request=path_request, runtime=_runtime(),
        )
        session.commit()

        assert first_note["note"]["created"] is True
        assert replay_note["note"]["created"] is False
        note = session.query(DBNote).filter_by(id=first_note["note"]["id"]).one()
        assert note.student_id == "lzz"
        assert note.source == "learning_workspace"
        assert session.query(DBNote).filter_by(id=note.id).count() == 1

        assert first_path["path"]["created"] is True
        assert replay_path["path"]["created"] is False
        assert session.query(DBPathNode).filter_by(learning_path_id=path.id).count() == initial_nodes + 1
        node = session.query(DBPathNode).filter_by(id=first_path["path"]["node_id"]).one()
        assert node.is_extension is True
        assert node.status == "pending"
        refreshed = workspace_overview(session, current_user=learner)
        assert any(item["id"] == node.id for item in refreshed["current_path"]["nodes"])
    finally:
        session.close()
        engine.dispose()


def test_workspace_action_rejects_foreign_context_and_missing_active_path():
    engine, session = _session()
    try:
        learner = session.query(DBUser).filter_by(username="lzz").one()
        other = session.query(DBUser).filter(
            DBUser.role == "student", DBUser.public_id != learner.public_id,
        ).first()
        context = _context(session, learner)

        with pytest.raises(WorkspaceActionError) as forbidden:
            execute_workspace_action(
                session, current_user=other,
                request=_request(context.id, "explain", "foreign-context-001"),
                runtime=_runtime(),
            )
        assert forbidden.value.code == "workspace_action_context_forbidden"

        path = session.query(DBLearningPath).filter_by(
            owner_public_id=learner.public_id, status="active",
        ).one()
        path.status = "paused"
        session.commit()
        with pytest.raises(WorkspaceActionError) as missing_path:
            execute_workspace_action(
                session, current_user=learner,
                request=_request(context.id, "add_path", "missing-active-path-001"),
                runtime=_runtime(),
            )
        assert missing_path.value.code == "workspace_action_active_path_required"
    finally:
        session.close()
        engine.dispose()


def test_workspace_action_api_returns_403_for_cross_owner_and_registers_route(monkeypatch):
    engine, session = _session()
    app = FastAPI()
    app.include_router(m5_api.router)

    async def fake_run_db_op(operation, *args, **kwargs):
        return operation(session, *args, **kwargs)

    monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
    monkeypatch.setattr(m5_api, "runtime_availability", _runtime)
    learner = session.query(DBUser).filter_by(username="lzz").one()
    other = session.query(DBUser).filter(
        DBUser.role == "student", DBUser.public_id != learner.public_id,
    ).first()
    context = _context(session, learner, key="r2-action-api-context")
    app.dependency_overrides[get_current_user] = lambda: other
    client = TestClient(app)
    try:
        response = client.post("/api/v1/m5/workspace/actions", json={
            "schema_version": "r2.workspace-action.v1",
            "context_session_id": context.id,
            "action": "explain",
            "idempotency_key": "api-foreign-action-001",
            "instruction": "解释当前对象",
        })
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "workspace_action_context_forbidden"

        from app.main import app as main_app

        assert set(main_app.openapi()["paths"]["/api/v1/m5/workspace/actions"]) == {"post"}
    finally:
        client.close()
        session.close()
        engine.dispose()
