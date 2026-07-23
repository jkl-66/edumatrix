from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.database import (
    DBArtifact,
    DBArtifactRelation,
    DBArtifactVersion,
    DBTaskEvent,
    DBUser,
    SessionLocal,
)
from app.identity import new_public_id
from app.m1_repository import (
    add_artifact_relation,
    add_artifact_version,
    append_task_event,
    create_artifact_with_version,
    create_generation_task,
    create_task_step,
)
from app.auth import get_password_hash
from fastapi.testclient import TestClient
from app.main import app
from tests.api_test_helpers import auth_headers


def _user(session):
    username = new_public_id("m1-art-user")
    user = DBUser(username=username, hashed_password=get_password_hash("test-password"))
    session.add(user)
    session.flush()
    return user


def test_generation_task_idempotency_and_replayable_timeline():
    with SessionLocal() as session:
        user = _user(session)
        key = new_public_id("idem")
        task, created = create_generation_task(
            session, owner_public_id=user.public_id, capability="resource.generate",
            idempotency_key=key, course_id="course-rag-engineering-m0"
        )
        duplicate, duplicate_created = create_generation_task(
            session, owner_public_id=user.public_id, capability="resource.generate",
            idempotency_key=key, course_id="course-rag-engineering-m0"
        )
        assert created is True
        assert duplicate_created is False
        assert duplicate.id == task.id

        step = create_task_step(
            session, task_id=task.id, sequence=1, agent_role="generator",
            input_summary="Generate a lesson artifact"
        )
        retry = create_task_step(
            session, task_id=task.id, sequence=1, attempt=2, agent_role="generator",
            input_summary="Retry after a transient failure"
        )
        append_task_event(
            session, task_id=task.id, step_id=retry.id, event_type="task_step.completed",
            payload={"status": "completed"}
        )
        session.commit()

        events = (session.query(DBTaskEvent).filter_by(task_id=task.id).order_by(DBTaskEvent.sequence).all())
        assert [event.sequence for event in events] == list(range(1, len(events) + 1))
        assert step.id != retry.id
        assert retry.attempt == 2


def test_artifact_content_is_versioned_instead_of_overwritten():
    with SessionLocal() as session:
        user = _user(session)
        artifact, version1 = create_artifact_with_version(
            session, owner_public_id=user.public_id, artifact_type="lesson",
            title="RAG lesson", content="version one"
        )
        version2 = add_artifact_version(
            session, artifact=artifact, content="version two", created_by_public_id=user.public_id
        )
        session.commit()

        versions = (session.query(DBArtifactVersion).filter_by(artifact_id=artifact.id).order_by(DBArtifactVersion.version_number).all())
        assert [version.version_number for version in versions] == [1, 2]
        assert [version.content for version in versions] == ["version one", "version two"]
        assert artifact.current_version_id == version2.id
        assert version1.content_hash != version2.content_hash


def test_artifact_relations_form_explicit_lineage_and_reject_duplicates():
    with SessionLocal() as session:
        user = _user(session)
        source, _ = create_artifact_with_version(
            session, owner_public_id=user.public_id, artifact_type="lesson", title="Source", content="source"
        )
        derived, _ = create_artifact_with_version(
            session, owner_public_id=user.public_id, artifact_type="quiz", title="Derived", content="derived"
        )
        relation = add_artifact_relation(
            session, source_artifact_id=derived.id, target_artifact_id=source.id,
            relation_type="derived_from", created_by_public_id=user.public_id
        )
        session.commit()
        assert session.query(DBArtifactRelation).filter_by(id=relation.id).one().relation_type == "derived_from"

        with pytest.raises(IntegrityError):
            add_artifact_relation(
                session, source_artifact_id=derived.id, target_artifact_id=source.id,
                relation_type="derived_from", created_by_public_id=user.public_id
            )
        session.rollback()


def test_task_and_artifact_apis_persist_and_enforce_owner_scope():
    with TestClient(app) as client:
        owner_headers = auth_headers(client, new_public_id("m1-api-owner"))
        other_headers = auth_headers(client, new_public_id("m1-api-other"))

        task_request = {
            "capability": "lesson.generate",
            "idempotency_key": new_public_id("request"),
            "course_id": "course-rag-engineering-m0",
        }
        task = client.post("/api/v1/generation-tasks", json=task_request, headers=owner_headers)
        assert task.status_code == 201
        duplicate = client.post("/api/v1/generation-tasks", json=task_request, headers=owner_headers)
        assert duplicate.status_code == 201
        assert duplicate.json()["id"] == task.json()["id"]
        assert duplicate.json()["created"] is False

        restored = client.get(f"/api/v1/generation-tasks/{task.json()['id']}", headers=owner_headers)
        assert restored.status_code == 200
        assert restored.json()["events"][0]["event_type"] == "generation_task.created"
        assert client.get(
            f"/api/v1/generation-tasks/{task.json()['id']}", headers=other_headers
        ).status_code == 403

        artifact = client.post(
            "/api/v1/artifacts",
            json={
                "artifact_type": "lesson",
                "title": "Persistent lesson",
                "content": "v1",
                "course_id": "course-rag-engineering-m0",
                "creating_task_id": task.json()["id"],
            },
            headers=owner_headers,
        )
        assert artifact.status_code == 201
        artifact_id = artifact.json()["id"]
        version = client.post(
            f"/api/v1/artifacts/{artifact_id}/versions",
            json={"content": "v2"},
            headers=owner_headers,
        )
        assert version.status_code == 201
        assert [item["version_number"] for item in version.json()["versions"]] == [1, 2]
        assert client.get(f"/api/v1/artifacts/{artifact_id}", headers=other_headers).status_code == 403


def test_task_and_artifact_lists_are_owner_scoped_filtered_and_cursor_paged():
    with TestClient(app) as client:
        owner_headers = auth_headers(client, new_public_id("m1-list-owner"))
        other_headers = auth_headers(client, new_public_id("m1-list-other"))

        task_ids = []
        artifact_ids = []
        for index in range(2):
            task = client.post(
                "/api/v1/generation-tasks",
                headers=owner_headers,
                json={"capability": "list.test", "idempotency_key": new_public_id("list-key")},
            )
            assert task.status_code == 201
            task_ids.append(task.json()["id"])
            artifact = client.post(
                "/api/v1/artifacts",
                headers=owner_headers,
                json={"artifact_type": "list-test", "title": f"Paged artifact {index}", "content": "body"},
            )
            assert artifact.status_code == 201
            artifact_ids.append(artifact.json()["id"])

        tasks_page = client.get(
            "/api/v1/generation-tasks", headers=owner_headers,
            params={"status": "queued", "limit": 1},
        )
        assert tasks_page.status_code == 200
        assert tasks_page.json()["has_more"] is True
        assert tasks_page.json()["items"][0]["id"] in task_ids
        tasks_next = client.get(
            "/api/v1/generation-tasks", headers=owner_headers,
            params={"status": "queued", "limit": 1, "cursor": tasks_page.json()["next_cursor"]},
        )
        assert tasks_next.status_code == 200
        assert tasks_next.json()["items"][0]["id"] != tasks_page.json()["items"][0]["id"]

        artifacts_page = client.get(
            "/api/v1/artifacts", headers=owner_headers,
            params={"status": "draft", "limit": 1},
        )
        assert artifacts_page.status_code == 200
        assert artifacts_page.json()["has_more"] is True
        assert artifacts_page.json()["items"][0]["id"] in artifact_ids
        assert client.get("/api/v1/artifacts", headers=other_headers).json()["items"] == []

        with SessionLocal() as session:
            archived = session.query(DBArtifact).filter_by(id=artifact_ids[0]).one()
            archived.status = "archived"
            archived.archived_at = archived.updated_at
            session.commit()
        archived_get = client.get(f"/api/v1/artifacts/{artifact_ids[0]}", headers=owner_headers)
        assert archived_get.status_code == 410
        append = client.post(
            f"/api/v1/artifacts/{artifact_ids[0]}/versions",
            headers=owner_headers, json={"content": "should fail"},
        )
        assert append.status_code == 410
