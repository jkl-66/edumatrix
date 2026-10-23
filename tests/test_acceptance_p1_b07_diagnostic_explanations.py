from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.diagnostic_report as diagnostic_report
from app.diagnostic_report import DiagnosticReportError, generate_diagnostic_report
from tests.test_f3_diagnostic_report import _session, _submitted_diagnostic


class _ApprovedExplanationLLM:
    model = "deepseek-v4-flash"
    thinking_mode = "enabled"
    reasoning_effort = "max"


def _fake_gateway(*_args, **kwargs):
    async def call():
        items = json.loads(kwargs["user_prompt"])["items"]
        payload = {
            "status": "completed",
            "items": [
                {
                    "question_version_id": item["question_version_id"],
                    "claim": "模型已结合本次作答与课程来源给出结论。",
                    "judgment_basis": "模型逐项核对作答、评分状态和授权课程片段后形成判断。",
                    "explanation": "模型解释本题为何与来源一致或不一致，并给出下一步核对方向。",
                    "source_ref_ids": [item["sources"][0]["id"]] if item["sources"] else [],
                    "confidence": 0.91 if item["sources"] else 0.35,
                    "status": "supported" if item["sources"] else "insufficient_evidence",
                }
                for item in items
            ],
        }
        return SimpleNamespace(
            model="deepseek-v4-flash",
            call_id="mcall-fb07-test",
            structured_output=payload,
        )

    return call()


def test_new_report_uses_model_bound_item_claims_and_public_evidence(monkeypatch):
    engine, session = _session()
    try:
        learner, blueprint, work, _ = _submitted_diagnostic(session)
        blueprint.generation_stages = [{"key": "p1_b05", "label": "真实生成", "status": "completed"}]
        session.commit()
        monkeypatch.setattr(diagnostic_report, "execute_registered_structured_call", _fake_gateway)

        row, created = generate_diagnostic_report(
            session,
            user=learner,
            session_id=work.id,
            idempotency_key="fb07-report-model-001",
            llm=_ApprovedExplanationLLM(),
        )
        payload = diagnostic_report.diagnostic_report_payload(session, user=learner, row=row)

        assert created is True
        assert payload["evaluation"] == {
            "status": "completed",
            "completedCount": blueprint.question_count,
            "totalCount": blueprint.question_count,
            "model": "deepseek-v4-flash",
        }
        assert all(item["evaluation"]["claim"].startswith("模型已结合") for item in payload["evidence"])
        assert all(item["judgmentBasis"].startswith("模型逐项") for item in payload["evidence"])
        assert all(item["explanation"].startswith("模型解释") for item in payload["evidence"])
        assert all(
            set(item["evaluation"]["sourceRefIds"]).issubset({source["id"] for source in item["sources"]})
            for item in payload["evidence"]
        )
        assert all(source["documentId"] and source["locationLabel"] for item in payload["evidence"] for source in item["sources"])
        public = json.dumps(payload, ensure_ascii=False)
        assert "reasoning_content" not in public and "api_key" not in public and "system_prompt" not in public
    finally:
        session.close()
        engine.dispose()


def test_explanation_model_policy_rejects_wrong_backend():
    with pytest.raises(DiagnosticReportError) as error:
        diagnostic_report._require_explanation_model(
            SimpleNamespace(model="deterministic", thinking_mode="disabled", reasoning_effort="standard")
        )
    assert error.value.code == "diagnostic_explanation_model_policy_invalid"


def test_invalid_item_source_cannot_publish_report(monkeypatch):
    engine, session = _session()
    try:
        learner, blueprint, work, _ = _submitted_diagnostic(session)
        blueprint.generation_stages = [{"key": "p1_b05", "label": "真实生成", "status": "completed"}]
        session.commit()

        async def invalid_gateway(*_args, **kwargs):
            items = json.loads(kwargs["user_prompt"])["items"]
            return SimpleNamespace(
                model="deepseek-v4-flash",
                call_id="mcall-fb07-invalid-source",
                structured_output={
                    "status": "completed",
                    "items": [
                        {
                            "question_version_id": item["question_version_id"],
                            "claim": "模型结论。",
                            "judgment_basis": "模型依据。",
                            "explanation": "模型解释说明并核对课程来源。",
                            "source_ref_ids": ["source-not-authorized"],
                            "confidence": 0.9,
                            "status": "supported",
                        }
                        for item in items
                    ],
                },
            )

        monkeypatch.setattr(diagnostic_report, "execute_registered_structured_call", invalid_gateway)
        with pytest.raises(DiagnosticReportError) as error:
            generate_diagnostic_report(
                session,
                user=learner,
                session_id=work.id,
                idempotency_key="fb07-report-invalid-source-001",
                llm=_ApprovedExplanationLLM(),
            )
        assert error.value.code == "diagnostic_explanation_source_mismatch"
        session.rollback()
        assert session.query(diagnostic_report.DBDiagnosticReport).count() == 0
    finally:
        session.close()
        engine.dispose()


def test_model_failure_keeps_answers_without_publishing_report_or_profile(monkeypatch):
    engine, session = _session()
    try:
        learner, blueprint, work, _ = _submitted_diagnostic(session)
        blueprint.generation_stages = [{"key": "p1_b05", "label": "真实生成", "status": "completed"}]
        session.commit()
        before_profiles = session.query(diagnostic_report.DBProfileSnapshot).count()
        saved_answers = {
            item.question_version_id: dict(item.answer or {})
            for item in session.query(diagnostic_report.DBDiagnosticResponseDraft).filter_by(session_id=work.id).all()
        }

        async def failing_gateway(*_args, **_kwargs):
            raise RuntimeError("provider unavailable")

        monkeypatch.setattr(diagnostic_report, "execute_registered_structured_call", failing_gateway)
        with pytest.raises(DiagnosticReportError) as error:
            generate_diagnostic_report(
                session,
                user=learner,
                session_id=work.id,
                idempotency_key="fb07-report-provider-failure-001",
                llm=_ApprovedExplanationLLM(),
            )
        assert error.value.code == "diagnostic_explanation_generation_failed"
        session.rollback()
        assert session.query(diagnostic_report.DBDiagnosticReport).count() == 0
        assert session.query(diagnostic_report.DBProfileSnapshot).count() == before_profiles
        current_answers = {
            item.question_version_id: dict(item.answer or {})
            for item in session.query(diagnostic_report.DBDiagnosticResponseDraft).filter_by(session_id=work.id).all()
        }
        assert current_answers == saved_answers
    finally:
        session.close()
        engine.dispose()


def test_report_replay_reuses_published_result_without_second_model_call(monkeypatch):
    engine, session = _session()
    calls = 0
    try:
        learner, blueprint, work, _ = _submitted_diagnostic(session)
        blueprint.generation_stages = [{"key": "p1_b05", "label": "真实生成", "status": "completed"}]
        session.commit()

        async def counting_gateway(*args, **kwargs):
            nonlocal calls
            calls += 1
            return await _fake_gateway(*args, **kwargs)

        monkeypatch.setattr(diagnostic_report, "execute_registered_structured_call", counting_gateway)
        first, first_created = generate_diagnostic_report(
            session,
            user=learner,
            session_id=work.id,
            idempotency_key="fb07-report-replay-001",
            llm=_ApprovedExplanationLLM(),
        )
        session.commit()
        replay, replay_created = generate_diagnostic_report(
            session,
            user=learner,
            session_id=work.id,
            idempotency_key="fb07-report-replay-001",
            llm=_ApprovedExplanationLLM(),
        )

        assert first_created is True and replay_created is False
        assert first.id == replay.id
        assert calls == 1
        assert session.query(diagnostic_report.DBDiagnosticReport).count() == 1
    finally:
        session.close()
        engine.dispose()


def test_partial_first_pass_retries_only_missing_item_without_overwriting_success(monkeypatch):
    engine, session = _session()
    requested_ids = []
    try:
        learner, blueprint, work, _ = _submitted_diagnostic(session)
        blueprint.generation_stages = [{"key": "p1_b05", "label": "真实生成", "status": "completed"}]
        session.commit()

        async def partial_gateway(*_args, **kwargs):
            items = json.loads(kwargs["user_prompt"])["items"]
            requested_ids.append([item["question_version_id"] for item in items])
            selected = items[:-1] if len(requested_ids) == 1 else items
            label = "首轮保留" if len(requested_ids) == 1 else "缺失题重试"
            return SimpleNamespace(
                model="deepseek-v4-flash",
                call_id=f"mcall-fb07-partial-{len(requested_ids)}",
                structured_output={
                    "status": "partial" if len(requested_ids) == 1 else "completed",
                    "items": [
                        {
                            "question_version_id": item["question_version_id"],
                            "claim": f"{label}模型结论。",
                            "judgment_basis": f"{label}逐项判断依据。",
                            "explanation": f"{label}完成本题系统解析并核对授权课程来源。",
                            "source_ref_ids": [item["sources"][0]["id"]] if item["sources"] else [],
                            "confidence": 0.88,
                            "status": "supported" if item["sources"] else "insufficient_evidence",
                        }
                        for item in selected
                    ],
                },
            )

        monkeypatch.setattr(diagnostic_report, "execute_registered_structured_call", partial_gateway)
        row, created = generate_diagnostic_report(
            session,
            user=learner,
            session_id=work.id,
            idempotency_key="fb07-report-partial-retry-001",
            llm=_ApprovedExplanationLLM(),
        )
        payload = diagnostic_report.diagnostic_report_payload(session, user=learner, row=row)

        assert created is True
        assert len(requested_ids) == 2
        assert len(requested_ids[0]) == blueprint.question_count
        assert requested_ids[1] == [requested_ids[0][-1]]
        assert all(item["evaluation"]["claim"].startswith("首轮保留") for item in payload["evidence"][:-1])
        assert payload["evidence"][-1]["evaluation"]["claim"].startswith("缺失题重试")
        assert payload["evaluation"]["completedCount"] == blueprint.question_count
    finally:
        session.close()
        engine.dispose()


def test_legacy_report_is_readable_without_claiming_new_model_evaluation():
    engine, session = _session()
    try:
        learner, blueprint, work, _ = _submitted_diagnostic(session)
        row, created = generate_diagnostic_report(
            session,
            user=learner,
            session_id=work.id,
            idempotency_key="fb07-report-legacy-001",
        )
        payload = diagnostic_report.diagnostic_report_payload(session, user=learner, row=row)

        assert created is True
        assert payload["evaluation"] == {
            "status": "legacy_compatibility",
            "completedCount": 0,
            "totalCount": blueprint.question_count,
            "model": None,
        }
        assert all("evaluation" not in item for item in payload["evidence"])
        public = json.dumps(payload, ensure_ascii=False)
        assert "reasoning_content" not in public
        assert "system_prompt" not in public
        assert "api_key" not in public
    finally:
        session.close()
        engine.dispose()


def test_frontend_exposes_evaluating_retry_and_item_evidence_without_private_trace():
    source = Path("frontend/src/components/DiagnosticAssessmentSession.vue").read_text(encoding="utf-8")

    for expected in (
        "评估中：正在生成逐题解析",
        "报告生成失败，答案仍已保存",
        "重新生成报告",
        "历史报告 · 未重新执行模型评估",
        "item.judgmentBasis",
        "item.evaluation.confidence",
        "item.evaluation.claim",
        "item.sources",
        "SourceCitation",
        "router.currentRoute.value.fullPath",
    ):
        assert expected in source
    assert "reasoning_content" not in source
    assert "api_key" not in source
