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
from app.database import Base, DBAuditLog, DBArtifact, DBArtifactVersion, DBGenerationTask, DBUser
import app.m5_api as m5_api
from app.m5_capabilities import M5CapabilityError
from app.m5_resources import ResourceVersionCreateRequest, create_resource_version
from app.m5_workspace import workspace_overview


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    seed_competition_demo(session)
    session.commit()
    return engine, session


def test_workspace_artifact_shelf_projects_version_status_and_source():
    engine, session = _session()
    try:
        learner = session.query(DBUser).filter_by(username="lzz").one()
        payload = workspace_overview(session, current_user=learner)

        assert len(payload["recent_artifacts"]) == 3
        assert all(item["current_version"]["number"] == 1 for item in payload["recent_artifacts"])
        assert all(item["current_version"]["content_format"] == "json" for item in payload["recent_artifacts"])
        assert all(item["source"]["kind"] == "chapter" for item in payload["recent_artifacts"])
        assert all(item["source"]["workspace_object_id"].startswith("workspace-document:") for item in payload["recent_artifacts"])
        assert all(item["source"]["learning_object"]["object_type"] == "document" for item in payload["recent_artifacts"])
        assert all(item["source"]["learning_object"]["title"] == item["source"]["label"] for item in payload["recent_artifacts"])
    finally:
        session.close()
        engine.dispose()


def test_new_generation_artifact_appears_in_workspace_without_a_second_sync_step():
    engine, session = _session()
    try:
        learner = session.query(DBUser).filter_by(username="lzz").one()
        task = DBGenerationTask(
            id="r2-08-completed-generation-task",
            owner_public_id=learner.public_id,
            course_id="demo-course-rag-trust-v1",
            trace_id="r2-08-generated-artifact-trace",
            status="completed",
            progress=1.0,
            capability="generate_experiment",
            model="deterministic",
            idempotency_key="r2-08-generated-artifact",
        )
        session.add(task)
        session.flush()
        artifact = DBArtifact(
            id="r2-08-new-generated-artifact",
            owner_public_id=learner.public_id,
            course_id="demo-course-rag-trust-v1",
            artifact_type="lesson_guide",
            title="新生成产物自动回架",
            status="approved",
            creating_task_id=task.id,
        )
        session.add(artifact)
        session.flush()
        content = '{"chapter_id":"demo-ch-08","result":"generated"}'
        version = DBArtifactVersion(
            artifact_id=artifact.id,
            version_number=1,
            content=content,
            content_format="json",
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            metadata_json={"chapter_id": "demo-ch-08", "generation_result": "succeeded"},
            created_by_public_id=learner.public_id,
            created_task_id=task.id,
        )
        session.add(version)
        session.flush()
        artifact.current_version_id = version.id
        session.commit()

        payload = workspace_overview(session, current_user=learner)
        projected = next(item for item in payload["recent_artifacts"] if item["id"] == artifact.id)
        assert projected["creating_task_id"] == task.id
        assert projected["current_version"]["number"] == 1
        assert projected["source"]["chapter_id"] == "demo-ch-08"
    finally:
        session.close()
        engine.dispose()


def test_workspace_resource_revision_creates_new_version_and_rejects_stale_editor():
    engine, session = _session()
    try:
        learner = session.query(DBUser).filter_by(username="lzz").one()
        artifact = session.query(DBArtifact).filter_by(owner_public_id=learner.public_id).first()
        source_version_id = artifact.current_version_id
        detail = create_resource_version(
            session,
            artifact=artifact,
            actor_public_id=learner.public_id,
            request=ResourceVersionCreateRequest(
                expected_lock_version=artifact.lock_version,
                source_version_id=source_version_id,
                content='{"updated":"workspace revision"}',
                content_format="json",
            ),
        )

        assert detail["status"] == "draft"
        assert detail["lock_version"] == 2
        assert [item["version_number"] for item in detail["versions"]] == [1, 2]
        assert detail["versions"][-1]["metadata"]["revision_origin"] == "learning_workspace"
        assert detail["versions"][-1]["metadata"]["revised_from_version_id"] == source_version_id
        refreshed = workspace_overview(session, current_user=learner)
        revised_shelf_item = next(item for item in refreshed["recent_artifacts"] if item["id"] == artifact.id)
        assert revised_shelf_item["source"]["kind"] == "chapter"
        assert revised_shelf_item["source"]["learning_object"]["id"].startswith("workspace-document:")
        audit = session.query(DBAuditLog).filter_by(action="artifact.version.create").one()
        assert audit.object_id == detail["current_version_id"]

        with pytest.raises(M5CapabilityError) as stale:
            create_resource_version(
                session,
                artifact=artifact,
                actor_public_id=learner.public_id,
                request=ResourceVersionCreateRequest(
                    expected_lock_version=1,
                    source_version_id=source_version_id,
                    content="stale content",
                    content_format="text",
                ),
            )
        assert stale.value.code == "resource_version_conflict"
    finally:
        session.close()
        engine.dispose()


def test_resource_revision_api_is_authenticated_owner_scoped_and_registered(monkeypatch):
    engine, session = _session()
    app = FastAPI()
    app.include_router(m5_api.router)

    async def fake_run_db_op(operation, *args, **kwargs):
        return operation(session, *args, **kwargs)

    monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
    learner = session.query(DBUser).filter_by(username="lzz").one()
    outsider = session.query(DBUser).filter(DBUser.role == "student", DBUser.public_id != learner.public_id).first()
    artifact = session.query(DBArtifact).filter_by(owner_public_id=learner.public_id).first()
    payload = {
        "expected_lock_version": artifact.lock_version,
        "source_version_id": artifact.current_version_id,
        "content": "workspace api revision",
        "content_format": "markdown",
    }
    client = TestClient(app)
    try:
        app.dependency_overrides[get_current_user] = lambda: outsider
        forbidden = client.post(f"/api/v1/m5/resources/{artifact.id}/versions", json=payload)
        assert forbidden.status_code == 403

        app.dependency_overrides[get_current_user] = lambda: learner
        created = client.post(f"/api/v1/m5/resources/{artifact.id}/versions", json=payload)
        assert created.status_code == 201
        assert created.json()["versions"][-1]["version_number"] == 2

        from app.main import app as main_app

        assert set(main_app.openapi()["paths"]["/api/v1/m5/resources/{artifact_id}/versions"]) == {"post"}
    finally:
        client.close()
        session.close()
        engine.dispose()


def test_workspace_frontend_exposes_artifact_shelf_revision_and_source_return():
    frontend = Path("frontend/src/views/LearningWorkspace.vue").read_text(encoding="utf-8")
    api_source = Path("frontend/src/api/m5.js").read_text(encoding="utf-8")

    assert "workspace-artifact-shelf" in frontend
    assert "workspace-artifact-dialog" in frontend
    assert "saveWorkspaceArtifactVersion" in frontend
    assert "returnToArtifactSource" in frontend
    assert "artifactSourceObject" in frontend
    assert "source_chapter_id" in frontend
    assert "currentQueryValue('artifact_id')" in frontend
    assert "window.history.replaceState" in frontend
    assert "createM5ResourceVersion" in frontend
    assert "/resources/${encodeURIComponent(artifactId)}/versions" in api_source
