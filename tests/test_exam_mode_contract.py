from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import app.m5_api as m5_api
import app.m5_exam_core as exam_core
from app.auth import get_current_user
from app.main import app
from app.m5_exam_core import FormalExamError, IntelligentExamConfigInput

from tests.test_f6_t06_formal_exam import _configuration, _demo_configuration, _fixture


class GovernedLLM:
    model = "deepseek-v4-flash"
    thinking_mode = "enabled"
    reasoning_effort = "max"


def _patch_db_and_user(monkeypatch, session, learner):
    async def fake_run_db_op(operation):
        return operation(session)

    monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: learner
    return TestClient(app)


def _patch_config(monkeypatch, **overrides):
    monkeypatch.setattr(m5_api, "CONFIG", replace(m5_api.CONFIG, **overrides))


def test_demo_mode_exposes_objective_contract_and_rejects_subjective_exam(monkeypatch):
    session, engine, learner, _completion = _fixture()
    _patch_config(
        monkeypatch,
        demo_mode=True,
        llm_provider="deterministic",
        llm_model="deterministic",
    )
    client = _patch_db_and_user(monkeypatch, session, learner)
    try:
        context = client.get(
            "/api/v1/m5/assessment/intelligent-exams/context",
            params={"course_id": "course-f6"},
        )
        assert context.status_code == 200, context.text
        body = context.json()
        assert body["external_model_required"] is False
        assert body["llm_generation_required"] is False
        assert body["question_type_counts"]["short_answer"] == 0

        unsupported = client.post(
            "/api/v1/m5/assessment/intelligent-exams",
            json={"configuration": _configuration("demo-subjective-rejected")},
        )
        assert unsupported.status_code == 422, unsupported.text
        assert unsupported.json()["detail"]["code"] == (
            "intelligent_exam_demo_subjective_unsupported"
        )
        assert session.query(exam_core.DBAssessmentExam).count() == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close()
        engine.dispose()


def test_production_context_keeps_live_model_contract(monkeypatch):
    session, engine, learner, _completion = _fixture()
    _patch_config(
        monkeypatch,
        demo_mode=False,
        llm_provider="openai",
        llm_model="deepseek-v4-flash",
    )
    client = _patch_db_and_user(monkeypatch, session, learner)
    try:
        context = client.get(
            "/api/v1/m5/assessment/intelligent-exams/context",
            params={"course_id": "course-f6"},
        )
        assert context.status_code == 200, context.text
        body = context.json()
        assert body["external_model_required"] is True
        assert body["llm_generation_required"] is True
        assert body["question_type_counts"]["short_answer"] == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close()
        engine.dispose()


def test_production_model_failure_is_explicit_and_never_falls_back(monkeypatch):
    session, engine, learner, _completion = _fixture()
    _patch_config(
        monkeypatch,
        demo_mode=False,
        llm_provider="openai",
        llm_model="deepseek-v4-flash",
    )
    client = _patch_db_and_user(monkeypatch, session, learner)
    monkeypatch.setattr(m5_api, "_build_governed_assessment_llm", lambda: GovernedLLM())

    async def failing_gateway(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(exam_core, "execute_registered_structured_call", failing_gateway)
    monkeypatch.setattr(
        exam_core,
        "_generate_dynamic_exam_items",
        lambda *_args, **_kwargs: pytest.fail("production mode must not use the deterministic fallback"),
    )
    try:
        response = client.post(
            "/api/v1/m5/assessment/intelligent-exams",
            json={"configuration": _configuration("production-failure-explicit")},
        )
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["code"] == "intelligent_exam_generation_failed"
        assert session.query(exam_core.DBAssessmentExam).count() == 0
        assert session.query(exam_core.DBAssessmentQuestion).filter_by(
            origin="ai_generated",
        ).count() == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close()
        engine.dispose()


def test_core_rejects_invalid_live_model_without_local_blueprint(monkeypatch):
    session, engine, learner, _completion = _fixture()

    async def failing_gateway(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(exam_core, "execute_registered_structured_call", failing_gateway)
    try:
        with pytest.raises(FormalExamError) as error:
            exam_core.build_intelligent_exam_input(
                session,
                owner_public_id=learner.public_id,
                config=IntelligentExamConfigInput(
                    **_configuration("core-production-failure")
                ),
                llm=GovernedLLM(),
            )
        assert error.value.code == "intelligent_exam_generation_failed"
        assert session.query(exam_core.DBAssessmentQuestion).filter_by(
            origin="ai_generated",
        ).count() == 0
    finally:
        session.close()
        engine.dispose()
