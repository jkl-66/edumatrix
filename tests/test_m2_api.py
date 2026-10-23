from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

import app.m2_api as m2_api
from app.auth import create_access_token, get_password_hash
from app.database import DBUser, SessionLocal
from app.identity import new_public_id
from app.main import app
from app.m2_baseline import seed_m2_baseline
from app.m2_contracts import M2Capability
from tests.test_m2_artifacts import FakeStructuredLLM, _payloads


def _headers(user: DBUser) -> dict[str, str]:
    token = create_access_token(
        {
            "sub": user.public_id,
            "uid": user.public_id,
            "username": user.username,
            "role": user.role,
        }
    )
    return {"Authorization": f"Bearer {token}"}


def test_m2_authenticated_api_runs_golden_loop_and_hides_quiz_answers(monkeypatch):
    with TestClient(app) as client:
        with SessionLocal() as session:
            baseline = seed_m2_baseline(session)
            owner = session.query(DBUser).filter_by(
                public_id=baseline.generation_context.owner_public_id
            ).one()
            owner_headers = _headers(owner)
            outsider = DBUser(
                username=new_public_id("m2-api-outsider"),
                hashed_password=get_password_hash("test-password"),
            )
            session.add(outsider)
            session.commit()
            outsider_headers = _headers(outsider)

        context = baseline.generation_context.model_dump(mode="json")
        fake = FakeStructuredLLM(_payloads(baseline.generation_context))
        monkeypatch.setattr(m2_api, "_llm_from_request", lambda request: fake)

        baseline_response = client.get("/api/v1/m2/baseline", headers=owner_headers)
        assert baseline_response.status_code == 200
        assert baseline_response.json()["generation_context"] == context
        assert client.get("/api/v1/m2/baseline", headers=outsider_headers).status_code == 403

        idempotency_key = f"m2-api-{uuid4().hex}"
        create_payload = {
            "context": context,
            "idempotency_key": idempotency_key,
            "model": "structured-test-double",
        }
        created = client.post(
            "/api/v1/m2/golden-tasks", json=create_payload, headers=owner_headers
        )
        assert created.status_code == 201
        task_id = created.json()["task_id"]
        duplicate = client.post(
            "/api/v1/m2/golden-tasks", json=create_payload, headers=owner_headers
        )
        assert duplicate.status_code == 201
        assert duplicate.json()["created"] is False
        assert duplicate.json()["task_id"] == task_id
        assert client.get(
            f"/api/v1/m2/golden-tasks/{task_id}", headers=outsider_headers
        ).status_code == 403

        started = client.post(
            f"/api/v1/m2/golden-tasks/{task_id}/start", headers=owner_headers
        )
        assert started.status_code == 200
        assert started.json()["status"] == "running"

        resource_ids = {}
        for capability in M2Capability:
            response = client.post(
                f"/api/v1/m2/golden-tasks/{task_id}/generate/{capability.value}",
                json={"context": context},
                headers=owner_headers,
            )
            assert response.status_code == 200, response.text
            body = response.json()
            resource_ids[body["artifact_type"]] = body["id"]
            if body["artifact_type"] == "tiered_quiz":
                assert "answer_key" not in body["versions"][0]["content"]
                assert "explanation" not in body["versions"][0]["content"]
        assert set(resource_ids) == {"lesson", "lab_guide", "tiered_quiz"}

        quality = client.post(
            f"/api/v1/m2/golden-tasks/{task_id}/quality",
            json={"context": context},
            headers=owner_headers,
        )
        assert quality.status_code == 200, quality.text
        assert quality.json()["passed"] is True
        assert quality.json()["manifest_version_id"]

        before_feedback = client.get(
            f"/api/v1/m2/golden-tasks/{task_id}/bundle", headers=owner_headers
        )
        assert before_feedback.status_code == 200
        quiz = next(
            item for item in before_feedback.json()["resources"]
            if item["artifact_type"] == "tiered_quiz"
        )
        assert "answer_key" not in quiz["versions"][0]["content"]
        quiz_version_id = quiz["versions"][0]["id"]

        feedback_payload = {
            "context": context,
            "feedback": {
                "idempotency_key": f"m2-api-feedback-{uuid4().hex}",
                "artifact_version_id": quiz_version_id,
                "activity_type": "quiz_attempt",
                "completed": True,
                "accuracy": 0.67,
                "help_requests": 2,
                "self_reported_difficulty": 4,
                "observed_seconds": 720,
                "occurred_at": datetime(2026, 7, 26, 7, 0, tzinfo=timezone.utc).isoformat(),
                "note": "需要更多原子事实拆分练习",
            },
        }
        feedback = client.post(
            f"/api/v1/m2/golden-tasks/{task_id}/feedback",
            json=feedback_payload,
            headers=owner_headers,
        )
        assert feedback.status_code == 200, feedback.text
        assert feedback.json()["task_status"] == "completed"
        assert feedback.json()["mastery_state"] == "unchanged_pending_evidence"
        replay = client.post(
            f"/api/v1/m2/golden-tasks/{task_id}/feedback",
            json=feedback_payload,
            headers=owner_headers,
        )
        assert replay.status_code == 200
        assert replay.json()["created"] is False

        bundle = client.get(
            f"/api/v1/m2/golden-tasks/{task_id}/bundle", headers=owner_headers
        )
        assert bundle.status_code == 200
        body = bundle.json()
        assert body["task"]["status"] == "completed"
        assert len(body["resources"]) == 3
        assert len(body["quality_checks"]) == 9
        assert len(body["feedback_events"]) == 1
        assert len(body["decisions"]) == 1
        assert body["decisions"][0]["status"] == "proposed"
        assert body["decisions"][0]["execution_impact"]["mastery_update"] == "none"
        assert client.get(
            f"/api/v1/m2/golden-tasks/{task_id}/bundle", headers=outsider_headers
        ).status_code == 403


def test_m2_api_retries_only_the_failed_step_with_owner_authorization(monkeypatch):
    with TestClient(app) as client:
        with SessionLocal() as session:
            baseline = seed_m2_baseline(session)
            owner = session.query(DBUser).filter_by(
                public_id=baseline.generation_context.owner_public_id
            ).one()
            owner_headers = _headers(owner)
            outsider = DBUser(
                username=new_public_id("m2-api-retry-outsider"),
                hashed_password=get_password_hash("test-password"),
            )
            session.add(outsider)
            session.commit()
            outsider_headers = _headers(outsider)

        context = baseline.generation_context.model_dump(mode="json")
        payloads = _payloads(baseline.generation_context)
        payloads["理论教授"] = "not-an-object"
        monkeypatch.setattr(
            m2_api,
            "_llm_from_request",
            lambda request: FakeStructuredLLM(payloads),
        )

        created = client.post(
            "/api/v1/m2/golden-tasks",
            json={
                "context": context,
                "idempotency_key": f"m2-api-retry-{uuid4().hex}",
                "model": "structured-test-double",
            },
            headers=owner_headers,
        )
        assert created.status_code == 201
        task_id = created.json()["task_id"]
        assert client.post(
            f"/api/v1/m2/golden-tasks/{task_id}/start", headers=owner_headers
        ).status_code == 200

        failed = client.post(
            f"/api/v1/m2/golden-tasks/{task_id}/generate/{M2Capability.LESSON.value}",
            json={"context": context},
            headers=owner_headers,
        )
        assert failed.status_code == 422
        assert failed.json()["detail"]["code"] == "invalid_generator_json"
        state = client.get(
            f"/api/v1/m2/golden-tasks/{task_id}", headers=owner_headers
        ).json()
        assert state["latest_steps"][0]["status"] == "failed"
        assert state["latest_steps"][0]["attempt"] == 1

        forbidden = client.post(
            f"/api/v1/m2/golden-tasks/{task_id}/steps/1/retry",
            headers=outsider_headers,
        )
        assert forbidden.status_code == 403
        invalid = client.post(
            f"/api/v1/m2/golden-tasks/{task_id}/steps/5/retry",
            headers=owner_headers,
        )
        assert invalid.status_code == 422

        retried = client.post(
            f"/api/v1/m2/golden-tasks/{task_id}/steps/1/retry",
            headers=owner_headers,
        )
        assert retried.status_code == 200
        assert retried.json()["attempt"] == 2
        assert retried.json()["status"] == "pending"

        monkeypatch.setattr(
            m2_api,
            "_llm_from_request",
            lambda request: FakeStructuredLLM(_payloads(baseline.generation_context)),
        )
        recovered = client.post(
            f"/api/v1/m2/golden-tasks/{task_id}/generate/{M2Capability.LESSON.value}",
            json={"context": context},
            headers=owner_headers,
        )
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["artifact_type"] == "lesson"
        state = client.get(
            f"/api/v1/m2/golden-tasks/{task_id}", headers=owner_headers
        ).json()
        assert state["latest_steps"][0]["status"] == "completed"
        assert state["latest_steps"][0]["attempt"] == 2
