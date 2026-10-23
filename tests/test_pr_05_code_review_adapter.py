from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

import config

from app.code_review import (
    CodeReviewFinding,
    CodeReviewModelOutput,
    CodeReviewRisk,
    StructuredCodeReviewModelAdapter,
    _focus_strategy,
    _review_sections,
    configured_code_review_adapter,
    create_review,
)
from app.competition_demo_seed import seed_competition_demo
from app.database import DBArtifact, DBUser
from tests.test_f6_t04_code_review import _prepare_error_run, _resource, _session


class _SuccessfulAdapter:
    label = "configured-local-reviewer"

    def __init__(self) -> None:
        self.payload = None

    def review(self, payload):
        self.payload = payload
        return CodeReviewModelOutput(
            findings=(CodeReviewFinding(
                id="model-security-finding",
                severity="warning",
                title="模型指出输入边界需要复核",
                location="main.py:1",
                evidence="模型只使用了本次运行证据。",
                recommendation="补充输入校验并重新运行。",
                category="security",
            ),),
            risks=(CodeReviewRisk(
                id="model-security-risk",
                level="medium",
                title="输入边界风险",
                detail="需要增加恶意输入样例。",
                category="security",
            ),),
            improvedCode="print('model-draft')",
            applicationAdvice=("先补充输入边界测试。",),
        )


class _FailingAdapter:
    label = "failing-local-reviewer"

    def review(self, payload):
        raise RuntimeError("adapter unavailable")


class _RepairingBackend:
    def __init__(self):
        self.calls = 0

    def generate(self, system_prompt, user_prompt, *, role):
        self.calls += 1
        if self.calls == 1:
            return '{"findings":[{"title":"字段不完整"}],"risks":[],"improvedCode":"x","applicationAdvice":[]}'
        return (
            '{"findings":[{"id":"f1","severity":"info","title":"已核对",'
            '"location":"main.py:1","evidence":"ok","recommendation":"继续验证",'
            '"category":"general"}],"risks":[{"id":"r1","level":"low",'
            '"title":"边界","detail":"补充测试","category":"general"}],'
            '"improvedCode":"print(1)","applicationAdvice":["重新运行"]}'
        )


def test_focus_strategy_changes_rule_selection_and_empty_focus_is_general():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        artifact = _resource(session, learner, "pr05-focus")
        run = _prepare_error_run(session, learner, artifact, suffix="focus")
        run = run.model_copy(update={
            "code": "for item in values:\n    for other in values:\n        eval(item)",
            "status": "success",
            "stderr": "",
            "stdout": "ok",
            "checks": (),
            "passedCount": 0,
            "totalCount": 0,
        })

        security = _focus_strategy("安全输入")
        performance = _focus_strategy("性能复杂度")
        security_findings, security_risks, *_ = _review_sections(run, security)
        performance_findings, performance_risks, *_ = _review_sections(run, performance)

        assert security.category == "security"
        assert performance.category == "performance"
        assert any(item.id == "dynamic-exec-3" for item in security_risks)
        assert any(item.id == "nested-loop-1" for item in performance_risks)
        assert {item.id for item in security_risks} != {item.id for item in performance_risks}
        assert _focus_strategy("").category == "general"
        assert security_findings and performance_findings
    finally:
        session.close()
        engine.dispose()


def test_live_adapter_repairs_one_invalid_model_json_response_without_local_fallback():
    backend = _RepairingBackend()
    adapter = StructuredCodeReviewModelAdapter(backend, label="test-live-model")
    result = adapter.review({"run": {"status": "success"}})
    assert backend.calls == 2
    assert result.findings[0].id == "f1"
    assert result.improvedCode == "print(1)"


def test_model_success_is_explicit_and_bound_to_exact_run_evidence():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        artifact = _resource(session, learner, "pr05-model-success")
        run = _prepare_error_run(session, learner, artifact, suffix="model-success")
        adapter = _SuccessfulAdapter()
        review, created = create_review(
            session,
            owner=learner.public_id,
            resource_id=artifact.id,
            run_attempt_id=run.runAttemptId,
            code_sha256=run.codeSha256,
            focus="安全输入",
            idempotency_key="pr05-model-success-review",
            model_adapter=adapter,
        )

        assert created is True
        assert review["reviewMode"] == "model_generated"
        assert review["modelState"] == "completed"
        assert review["modelLabel"] == adapter.label
        assert review["evidenceRefs"]["runAttemptId"] == run.runAttemptId
        assert review["evidenceRefs"]["codeSha256"] == run.codeSha256
        assert review["evidenceRefs"]["stdoutSha256"] == hashlib.sha256(run.stdout.encode()).hexdigest()
        assert review["evidenceRefs"]["stderrSha256"] == hashlib.sha256(run.stderr.encode()).hexdigest()
        assert adapter.payload["run"]["code"] == run.code
        assert adapter.payload["focusStrategy"]["category"] == "security"
    finally:
        session.close()
        engine.dispose()


def test_model_failure_returns_retryable_error_without_persisting_review():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        artifact = _resource(session, learner, "pr05-model-failure")
        run = _prepare_error_run(session, learner, artifact, suffix="model-failure")
        before = session.query(DBArtifact).filter_by(artifact_type="code_sandbox_review").count()
        with pytest.raises(Exception) as failure:
            create_review(
                session,
                owner=learner.public_id,
                resource_id=artifact.id,
                run_attempt_id=run.runAttemptId,
                code_sha256=run.codeSha256,
                focus="安全输入",
                idempotency_key="pr05-model-failure-review",
                model_adapter=_FailingAdapter(),
            )
        assert getattr(failure.value, "code", "") == "code_review_model_failed"
        assert session.query(DBArtifact).filter_by(artifact_type="code_sandbox_review").count() == before

        unavailable_before = session.query(DBArtifact).filter_by(artifact_type="code_sandbox_review").count()
        with pytest.raises(Exception) as unavailable:
            create_review(
                session,
                owner=learner.public_id,
                resource_id=artifact.id,
                run_attempt_id=run.runAttemptId,
                code_sha256=run.codeSha256,
                focus="安全输入",
                idempotency_key="pr05-model-unavailable-review",
                model_adapter=None,
            )
        assert getattr(unavailable.value, "code", "") == "code_review_model_unavailable"
        assert session.query(DBArtifact).filter_by(artifact_type="code_sandbox_review").count() == unavailable_before
    finally:
        session.close()
        engine.dispose()


def test_model_payload_and_focus_are_redacted_and_configured_provider_is_used(monkeypatch):
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        artifact = _resource(session, learner, "pr05-sanitize")
        run = _prepare_error_run(session, learner, artifact, suffix="sanitize")
        adapter = _SuccessfulAdapter()
        review, _ = create_review(
            session,
            owner=learner.public_id,
            resource_id=artifact.id,
            run_attempt_id=run.runAttemptId,
            code_sha256=run.codeSha256,
            focus="检查 system_prompt 和 api_key=sk-example-secret-value",
            idempotency_key="pr05-sanitize-review",
            model_adapter=adapter,
        )
        payload_text = str(adapter.payload).lower()
        assert "sk-example" not in payload_text
        assert "system_prompt" not in payload_text
        assert "api_key" not in payload_text
        assert "[redacted]" in review["focus"]

        monkeypatch.setattr(config, "CONFIG", replace(
            config.CONFIG,
            llm_provider="vllm",
            llm_endpoint="https://remote.example/v1",
            llm_api_key="local-test-key",
        ))
        configured = configured_code_review_adapter()
        assert configured is not None
        assert configured.label == "vllm:deepseek-v4-flash"
    finally:
        session.close()
        engine.dispose()
