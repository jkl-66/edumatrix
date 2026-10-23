from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent_audit import assert_public_audit_is_sanitized
from app.code_review import (
    CodeReviewFinding,
    CodeReviewModelOutput,
    CodeReviewRisk,
    apply_review,
    create_review,
    get_review,
    latest_review,
)
from app.code_sandbox import (
    CodeSandboxError,
    ExecutionResult,
    OutputCapture,
    finalize_run,
    get_run,
    mark_run_running,
    prepare_run,
)
from app.competition_demo_seed import seed_competition_demo
from app.database import Base, DBArtifact, DBArtifactVersion, DBLearningEvent, DBProfileSnapshot, DBSourceRef, DBUser
from app.m5_resources import parse_code_sandbox_content
from app.m1_repository import add_artifact_version
from app.resource_bundles import create_generation_job, execute_generation_job_demo


COURSE_ID = "demo-course-rag-trust-v1"
ROOT = Path(__file__).resolve().parents[1]


class _TestModelAdapter:
    label = "test-live-model"

    def review(self, payload):
        run = payload["run"]
        return CodeReviewModelOutput(
            findings=(CodeReviewFinding(
                id="model-runtime-finding",
                severity="error" if run["status"] != "success" else "info",
                title="模型基于本次运行给出建议",
                location="main.py:2",
                evidence=run["stderr"] or "本次运行没有错误输出。",
                recommendation="修正后使用相同输入重新运行，确认输出和边界行为。",
                category="reliability",
            ),),
            risks=(CodeReviewRisk(
                id="model-boundary-risk",
                level="medium",
                title="边界输入仍需验证",
                detail="当前点评只依据选中的运行记录，建议补充空值和极端输入。",
                category="reliability",
            ),),
            improvedCode="values = []\nprint(sum(values) / len(values) if values else 0.0)",
            applicationAdvice=("补充边界输入测试。", "重新运行并比较结果。"),
        )


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def _resource(session, learner: DBUser, key: str) -> DBArtifact:
    source = session.get(DBSourceRef, "demo-ref-07")
    profile = session.query(DBProfileSnapshot).filter_by(owner_public_id=learner.public_id).first()
    assert source is not None and profile is not None
    job = create_generation_job(
        session,
        learner,
        course_id=COURSE_ID,
        knowledge_point_id="demo-kp-07",
        profile_snapshot_id=profile.id,
        idempotency_key=key,
        scope="single",
        items=[{
            "type": "code_sandbox",
            "title": "分类阈值代码实训",
            "source_ref_ids": [source.id],
            "completion_rule": "保存代码，完成一次通过全部必需检查的真实运行，再明确提交完成。",
        }],
        learning_goal="通过真实代码运行理解分类阈值、混淆矩阵和误差边界",
    )
    session.commit()
    executed = execute_generation_job_demo(session, learner, job["job_id"])
    session.commit()
    item = executed["items"][0]
    assert item["state"] == "succeeded"
    return session.get(DBArtifact, item["resource"]["resource_id"])


def _capture(text: str) -> OutputCapture:
    size = len(text.encode("utf-8"))
    return OutputCapture(totalBytes=size, capturedBytes=size, limitBytes=100_000, omittedBytes=0, truncated=False)


def _result(*, status: str, stdout: str = "", stderr: str = "", exit_code: int | None = None) -> ExecutionResult:
    return ExecutionResult(
        status=status,
        executionTimeMs=17,
        exitCode=exit_code,
        stdout=stdout,
        stderr=stderr,
        stdoutCapture=_capture(stdout),
        stderrCapture=_capture(stderr),
    )


def _prepare_error_run(session, learner: DBUser, artifact: DBArtifact, *, suffix: str = "01"):
    code = "values = []\nprint(sum(values) / len(values))"
    state, created = prepare_run(
        session,
        owner=learner.public_id,
        resource_id=artifact.id,
        resource_version_id=artifact.current_version_id,
        code=code,
        standard_input="",
        idempotency_key=f"f6-t04-run-{suffix}",
    )
    assert created is True
    session.commit()
    mark_run_running(session, state.runAttemptId)
    session.commit()
    final = finalize_run(
        session,
        state.runAttemptId,
        _result(
            status="runtime_error",
            stderr='Traceback (most recent call last):\n  File "main.py", line 2, in <module>\nZeroDivisionError: division by zero\n',
            exit_code=1,
        ),
    )
    session.commit()
    return final


def test_review_requires_terminal_real_evidence_and_exact_code_hash():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        artifact = _resource(session, learner, "f6-t04-resource-eligibility")
        code = "print('queued')"
        queued, _ = prepare_run(
            session,
            owner=learner.public_id,
            resource_id=artifact.id,
            resource_version_id=artifact.current_version_id,
            code=code,
            standard_input="",
            idempotency_key="f6-t04-queued-run",
        )
        session.commit()

        with pytest.raises(CodeSandboxError) as ineligible:
            create_review(
                session,
                owner=learner.public_id,
                resource_id=artifact.id,
                run_attempt_id=queued.runAttemptId,
                code_sha256=queued.codeSha256,
                focus="边界条件",
                idempotency_key="f6-t04-review-ineligible",
            )
        assert ineligible.value.code == "code_review_run_ineligible"

        final = _prepare_error_run(session, learner, artifact, suffix="eligibility")
        with pytest.raises(CodeSandboxError) as mismatch:
            create_review(
                session,
                owner=learner.public_id,
                resource_id=artifact.id,
                run_attempt_id=final.runAttemptId,
                code_sha256="0" * 64,
                focus="边界条件",
                idempotency_key="f6-t04-review-hash",
            )
        assert mismatch.value.code == "code_review_code_hash_mismatch"

        review, created = create_review(
            session,
            owner=learner.public_id,
            resource_id=artifact.id,
            run_attempt_id=final.runAttemptId,
            code_sha256=final.codeSha256,
            focus="边界条件",
            idempotency_key="f6-t04-review-evidence",
            model_adapter=_TestModelAdapter(),
        )
        session.commit()
        assert created is True
        assert review["schemaVersion"] == "f6.code-review.v1"
        assert review["evidenceRefs"]["runAttemptId"] == final.runAttemptId
        assert review["evidenceRefs"]["codeSha256"] == final.codeSha256
        assert review["evidenceRefs"]["stderrSha256"] == hashlib.sha256(final.stderr.encode()).hexdigest()
        assert review["findings"][0]["location"] == "main.py:2"
        assert "ZeroDivisionError" in review["findings"][0]["evidence"]
        assert review["reviewMode"] == "model_generated"
        assert review["modelState"] == "completed"
        assert_public_audit_is_sanitized(review["agentAudit"])

        repeated, repeated_created = create_review(
            session,
            owner=learner.public_id,
            resource_id=artifact.id,
            run_attempt_id=final.runAttemptId,
            code_sha256=final.codeSha256,
            focus="边界条件",
            idempotency_key="f6-t04-review-evidence",
        )
        assert repeated_created is False
        assert repeated["reviewId"] == review["reviewId"]
        with pytest.raises(CodeSandboxError) as conflict:
            create_review(
                session,
                owner=learner.public_id,
                resource_id=artifact.id,
                run_attempt_id=final.runAttemptId,
                code_sha256=final.codeSha256,
                focus="性能",
                idempotency_key="f6-t04-review-evidence",
            )
        assert conflict.value.code == "code_review_idempotency_conflict"
    finally:
        session.close()
        engine.dispose()


def test_review_focus_and_public_agent_audit_are_sanitized():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        artifact = _resource(session, learner, "f6-t04-resource-sanitize")
        final = _prepare_error_run(session, learner, artifact, suffix="sanitize")
        review, _ = create_review(
            session,
            owner=learner.public_id,
            resource_id=artifact.id,
            run_attempt_id=final.runAttemptId,
            code_sha256=final.codeSha256,
            focus="检查 system_prompt 和 api_key=sk-example-secret-value",
            idempotency_key="f6-t04-review-sanitize",
            model_adapter=_TestModelAdapter(),
        )
        encoded = json.dumps({"focus": review["focus"], "audit": review["agentAudit"]}, ensure_ascii=False).lower()
        assert "sk-example" not in encoded
        assert "system_prompt" not in encoded
        assert "api_key" not in encoded
        assert "[redacted]" in review["focus"]
    finally:
        session.close()
        engine.dispose()


def test_apply_review_creates_new_resource_version_and_preserves_original_run():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        artifact = _resource(session, learner, "f6-t04-resource-apply")
        event_count_before_review = session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count()
        source_version = session.get(DBArtifactVersion, artifact.current_version_id)
        original_content = source_version.content
        original_number = source_version.version_number
        final = _prepare_error_run(session, learner, artifact, suffix="apply")
        review, _ = create_review(
            session,
            owner=learner.public_id,
            resource_id=artifact.id,
            run_attempt_id=final.runAttemptId,
            code_sha256=final.codeSha256,
            focus="空列表边界",
            idempotency_key="f6-t04-review-apply",
            model_adapter=_TestModelAdapter(),
        )
        session.commit()
        assert review["improvedCode"] != final.code
        assert "else 0.0" in review["improvedCode"]

        applied = apply_review(
            session,
            owner=learner.public_id,
            review_id=review["reviewId"],
            expected_lock_version=artifact.lock_version,
            idempotency_key="f6-t04-apply-version",
        )
        session.commit()
        assert applied["created"] is True
        assert applied["resourceVersionNumber"] == original_number + 1
        assert session.get(DBArtifactVersion, source_version.id).content == original_content
        applied_version = session.get(DBArtifactVersion, applied["resourceVersionId"])
        parsed = parse_code_sandbox_content(applied_version.content)
        entry = next(item for item in parsed.files if item.path == parsed.entryFile)
        assert entry.content == review["improvedCode"]
        assert applied_version.metadata_json["revision_origin"] == "ai_code_review"
        assert applied_version.metadata_json["code_review_id"] == review["reviewId"]

        repeated = apply_review(
            session,
            owner=learner.public_id,
            review_id=review["reviewId"],
            expected_lock_version=artifact.lock_version,
            idempotency_key="f6-t04-apply-version",
        )
        assert repeated["created"] is False
        assert repeated["resourceVersionId"] == applied["resourceVersionId"]

        rerun, created = prepare_run(
            session,
            owner=learner.public_id,
            resource_id=artifact.id,
            resource_version_id=artifact.current_version_id,
            code=entry.content,
            standard_input=parsed.standardInput,
            idempotency_key="f6-t04-rerun-applied",
        )
        assert created is True
        assert rerun.codeSha256 != final.codeSha256
        session.commit()
        mark_run_running(session, rerun.runAttemptId)
        rerun_final = finalize_run(session, rerun.runAttemptId, _result(status="success", stdout="0.0\n", exit_code=0))
        session.commit()
        assert rerun_final.status == "success"
        assert get_run(session, owner=learner.public_id, run_id=final.runAttemptId)["status"] == "runtime_error"
        assert get_review(session, owner=learner.public_id, review_id=review["reviewId"])["application"]["resourceVersionId"] == applied["resourceVersionId"]
        assert latest_review(session, owner=learner.public_id, resource_id=artifact.id, run_attempt_id=final.runAttemptId)["reviewId"] == review["reviewId"]
        assert session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count() == event_count_before_review
    finally:
        session.close()
        engine.dispose()


def test_review_cannot_apply_over_a_newer_student_draft():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        artifact = _resource(session, learner, "f6-t04-resource-stale")
        final = _prepare_error_run(session, learner, artifact, suffix="stale")
        review, _ = create_review(
            session,
            owner=learner.public_id,
            resource_id=artifact.id,
            run_attempt_id=final.runAttemptId,
            code_sha256=final.codeSha256,
            focus="",
            idempotency_key="f6-t04-review-stale",
            model_adapter=_TestModelAdapter(),
        )
        current = session.get(DBArtifactVersion, artifact.current_version_id)
        add_artifact_version(
            session,
            artifact=artifact,
            content=current.content,
            content_format=current.content_format,
            created_by_public_id=learner.public_id,
            metadata=dict(current.metadata_json or {}),
        )
        artifact.lock_version += 1
        session.commit()

        with pytest.raises(CodeSandboxError) as stale:
            apply_review(
                session,
                owner=learner.public_id,
                review_id=review["reviewId"],
                expected_lock_version=artifact.lock_version,
                idempotency_key="f6-t04-apply-stale",
            )
        assert stale.value.code == "code_review_apply_stale"
    finally:
        session.close()
        engine.dispose()


def test_frontend_and_api_preserve_the_f6_t04_review_contract():
    panel = (ROOT / "frontend/src/components/CodeReviewPanel.vue").read_text(encoding="utf-8")
    workspace = (ROOT / "frontend/src/views/CodeSandboxWorkspace.vue").read_text(encoding="utf-8")
    frontend_api = (ROOT / "frontend/src/api/codeSandbox.js").read_text(encoding="utf-8")
    backend_api = (ROOT / "app/code_sandbox_api.py").read_text(encoding="utf-8")

    assert "CodeReviewPanel" in workspace
    assert "grid-template-columns: 22fr 50fr 28fr" in workspace
    assert "下一任务" not in workspace
    for heading in ("问题定位", "点评重点", "潜在风险", "改进代码", "应用建议"):
        assert f"<h3>{heading}</h3>" in panel
    assert "真实模型点评" in panel
    assert "deterministic" not in panel.lower()
    assert "@applied=\"handleReviewApplied\"" in workspace

    for route in (
        "/resources/{resource_id}/reviews/latest",
        "/resources/{resource_id}/reviews",
        "/reviews/{review_id}",
        "/reviews/{review_id}/apply",
    ):
        assert route in backend_api
    assert "/v1/code-sandbox/resources/${encodeURIComponent(resourceId)}/reviews/latest" in frontend_api
    assert "/v1/code-sandbox/resources/${encodeURIComponent(resourceId)}/reviews" in frontend_api
    assert "/v1/code-sandbox/reviews/${encodeURIComponent(reviewId)}/apply" in frontend_api
