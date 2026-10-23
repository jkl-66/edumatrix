from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.code_sandbox as code_sandbox
from app.code_sandbox import (
    CodeSandboxError,
    CodeSandboxRunState,
    LocalPythonExecutor,
    complete_run_learning,
    finalize_run,
    mark_run_running,
    prepare_run,
)
from app.competition_demo_seed import seed_competition_demo
from app.database import (
    Base,
    DBArtifact,
    DBArtifactVersion,
    DBLearningEvent,
    DBLearningPath,
    DBProfileSnapshot,
    DBSourceRef,
    DBUser,
)
from app.m5_resources import (
    ResourceVersionCreateRequest,
    ResourceVersionRestoreRequest,
    create_resource_version,
    parse_code_sandbox_content,
    resource_detail,
    restore_resource_version,
)
from app.resource_bundles import (
    _deterministic_code_contract,
    create_generation_job,
    execute_generation_job_demo,
)


ROOT = Path(__file__).resolve().parents[1]
COURSE_ID = "demo-course-rag-trust-v1"


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


def _resource(session, learner: DBUser, key: str = "f6-t03-resource-001") -> DBArtifact:
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


def _runtime(monkeypatch, *, timeout: float = 3.0, output_limit: int = 100_000):
    monkeypatch.setattr(
        code_sandbox,
        "CONFIG",
        replace(
            code_sandbox.CONFIG,
            sandbox_mode="trusted_local",
            sandbox_timeout=timeout,
            sandbox_max_output_bytes=output_limit,
            sandbox_max_visual_bytes=5_000_000,
        ),
    )


def _state(code: str, *, run_id: str, timeout: int = 3, standard_input: str = "") -> CodeSandboxRunState:
    return CodeSandboxRunState(
        runAttemptId=run_id,
        ownerPublicId="usr-test",
        sourceResourceId="resource-test",
        sourceResourceVersionId="version-test",
        courseId=COURSE_ID,
        knowledgePointId="demo-kp-07",
        entryFile="main.py",
        runtimeBoundary="本地研究模式，不具备 Docker 容器隔离。",
        timeoutSeconds=timeout,
        code=code,
        codeSha256=code_sandbox.hashlib.sha256(code.encode("utf-8")).hexdigest(),
        standardInput=standard_input,
        requiredChecks=(),
        status="running",
        createdAt="2026-08-14T00:00:00Z",
        startedAt="2026-08-14T00:00:01Z",
    )


def test_generation_creates_strict_code_sandbox_resource_and_projection():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        artifact = _resource(session, learner)
        version = session.get(DBArtifactVersion, artifact.current_version_id)
        parsed = parse_code_sandbox_content(version.content)
        detail = resource_detail(session, artifact)

        assert version.content_format == "json"
        assert parsed.schemaVersion == "f6.code-sandbox.v1"
        assert parsed.entryFile == "main.py"
        assert parsed.standardInput == "0.50"
        assert len(parsed.checkpoints) == 3
        assert {item.kind for item in parsed.requiredChecks} == {
            "exit_code_zero", "stdout_contains", "plot_count_at_least",
        }
        assert detail["catalog"]["route"] == f"/workspace/code/{artifact.id}"
        projection = detail["code_sandbox"]["current"]
        assert projection["mode"] == "structured"
        assert projection["source_readiness"]["publishable"] is True
        assert projection["structured"]["runtime"]["mode"] == "trusted_local"
        assert "不具备 Docker" in projection["structured"]["runtime"]["boundary"]
    finally:
        session.close()
        engine.dispose()


def test_optimization_resource_runs_real_regularization_experiment_with_plot(monkeypatch):
    _runtime(monkeypatch, timeout=8)
    code, standard_input, checks = _deterministic_code_contract(
        knowledge_point="优化算法、正则化与训练稳定性",
        practical_focus="优化过程、收敛观察与参数诊断实验",
        learning_goal="比较学习率与 L2 正则化对损失收敛和模型权重的影响",
    )

    assert standard_input == "0.08,0.03,80"
    assert "knowledge_point=" not in code
    assert {item["kind"] for item in checks} == {
        "exit_code_zero", "stdout_contains", "plot_count_at_least",
    }

    result = asyncio.run(
        LocalPythonExecutor().execute(
            _state(code, run_id="optimization-resource-run", timeout=8, standard_input=standard_input)
        )
    )

    assert result.status == "success"
    assert "final_loss=" in result.stdout
    assert "weight_shrinkage=" in result.stdout
    assert "converged=True" in result.stdout
    assert len(result.plots) == 1


def test_code_versions_save_and_restore_without_overwriting_history():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        artifact = _resource(session, learner, "f6-t03-resource-history-001")
        first = session.get(DBArtifactVersion, artifact.current_version_id)
        revised = json.loads(first.content)
        revised["files"][0]["content"] += "\nprint('saved-version-2')\n"
        detail = create_resource_version(
            session,
            artifact=artifact,
            actor_public_id=learner.public_id,
            request=ResourceVersionCreateRequest(
                expected_lock_version=artifact.lock_version,
                source_version_id=first.id,
                content=json.dumps(revised, ensure_ascii=False),
                content_format="json",
            ),
        )
        second = session.get(DBArtifactVersion, artifact.current_version_id)
        assert second.version_number == 2
        assert len(detail["code_sandbox"]["versions"]) == 2

        restored = restore_resource_version(
            session,
            artifact=artifact,
            actor_public_id=learner.public_id,
            request=ResourceVersionRestoreRequest(
                expected_lock_version=artifact.lock_version,
                version_id=first.id,
            ),
        )
        current = session.get(DBArtifactVersion, artifact.current_version_id)
        assert current.version_number == 3
        assert current.content == first.content
        assert len(restored["code_sandbox"]["versions"]) == 3
        assert session.get(DBArtifactVersion, second.id).content == second.content
    finally:
        session.close()
        engine.dispose()


def test_real_run_requires_explicit_completion_before_evidence(monkeypatch):
    _runtime(monkeypatch, timeout=8)
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        artifact = _resource(session, learner, "f6-t03-resource-evidence-001")
        version = session.get(DBArtifactVersion, artifact.current_version_id)
        content = parse_code_sandbox_content(version.content)
        baseline = session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count()

        queued, created = prepare_run(
            session,
            owner=learner.public_id,
            resource_id=artifact.id,
            resource_version_id=version.id,
            code=content.files[0].content,
            standard_input=content.standardInput,
            idempotency_key="f6-t03-run-evidence-001",
        )
        assert created is True and queued.status == "queued"
        running = mark_run_running(session, queued.runAttemptId)
        result = asyncio.run(LocalPythonExecutor().execute(running))
        final = finalize_run(session, queued.runAttemptId, result)
        assert final.status == "success"
        assert final.passedCount == final.totalCount == 4
        assert "validation_accuracy=" in final.stdout
        assert "confusion_matrix=" in final.stdout
        assert len(final.plots) == 1
        assert session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count() == baseline
        path = session.query(DBLearningPath).filter_by(
            owner_public_id=learner.public_id,
            course_id=COURSE_ID,
        ).first()
        assert path is not None

        completed = complete_run_learning(
            session,
            owner=learner.public_id,
            user=learner,
            resource_id=artifact.id,
            run_id=final.runAttemptId,
            idempotency_key="f6-t03-complete-evidence-001",
            context={
                "userId": learner.public_id,
                "courseId": COURSE_ID,
                "pathId": path.id,
            },
            actual_minutes=12,
        )
        session.commit()
        assert completed["created"] is True
        assert completed["evidenceStatus"] == "accepted"
        event = session.query(DBLearningEvent).filter_by(id=completed["eventId"]).one()
        assert event.context_ref["pathId"] == path.id
        assert completed["masteryEligible"] is True
        event = session.get(DBLearningEvent, completed["eventId"])
        assert event.event_type == "code_tests_passed"
        assert event.payload["run_id"] == final.runAttemptId
        assert event.payload["test_scope"] == "required"
        completion_projection = resource_detail(session, artifact)["code_sandbox"]["completion"]
        assert completion_projection["status"] == "completed"
        assert completion_projection["run_attempt_id"] == final.runAttemptId

        replay = complete_run_learning(
            session,
            owner=learner.public_id,
            user=learner,
            resource_id=artifact.id,
            run_id=final.runAttemptId,
            idempotency_key="f6-t03-complete-evidence-001",
            context={"userId": learner.public_id, "courseId": COURSE_ID},
            actual_minutes=12,
        )
        assert replay["created"] is False
        assert session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count() == baseline + 1

        revised = json.loads(version.content)
        revised["files"][0]["content"] += "\n# saved after completion\n"
        create_resource_version(
            session,
            artifact=artifact,
            actor_public_id=learner.public_id,
            request=ResourceVersionCreateRequest(
                expected_lock_version=artifact.lock_version,
                source_version_id=version.id,
                content=json.dumps(revised, ensure_ascii=False),
                content_format="json",
            ),
        )
        current_projection = resource_detail(session, artifact)["code_sandbox"]["completion"]
        assert current_projection["status"] == "not_recorded"
        assert current_projection["event_id"] is None

        with pytest.raises(CodeSandboxError) as exc_info:
            complete_run_learning(
                session,
                owner=learner.public_id,
                user=learner,
                resource_id=artifact.id,
                run_id=final.runAttemptId,
                idempotency_key="f6-t03-complete-stale-version-001",
                context={"userId": learner.public_id, "courseId": COURSE_ID},
                actual_minutes=12,
            )
        assert exc_info.value.code == "code_sandbox_run_stale"
    finally:
        session.close()
        engine.dispose()


def test_failed_or_stale_run_cannot_complete(monkeypatch):
    _runtime(monkeypatch)
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        artifact = _resource(session, learner, "f6-t03-resource-failure-001")
        version = session.get(DBArtifactVersion, artifact.current_version_id)
        queued, _ = prepare_run(
            session,
            owner=learner.public_id,
            resource_id=artifact.id,
            resource_version_id=version.id,
            code="print(1 / 0)",
            standard_input="",
            idempotency_key="f6-t03-run-failure-001",
        )
        running = mark_run_running(session, queued.runAttemptId)
        result = asyncio.run(LocalPythonExecutor().execute(running))
        final = finalize_run(session, queued.runAttemptId, result)
        assert final.status == "runtime_error"
        assert "ZeroDivisionError" in final.stderr

        with pytest.raises(CodeSandboxError) as exc_info:
            complete_run_learning(
                session,
                owner=learner.public_id,
                user=learner,
                resource_id=artifact.id,
                run_id=final.runAttemptId,
                idempotency_key="f6-t03-complete-failure-001",
                context=None,
                actual_minutes=None,
            )
        assert exc_info.value.code == "code_sandbox_run_incomplete"
    finally:
        session.close()
        engine.dispose()


def test_executor_preserves_large_output_head_tail_and_plot(monkeypatch):
    _runtime(monkeypatch, timeout=8, output_limit=4096)
    executor = LocalPythonExecutor()
    code = """import matplotlib.pyplot as plt
print('START_MARKER')
print('x' * 12000)
print('END_MARKER')
plt.plot([0, 1, 2], [0, 1, 4])
plt.title('bounded output')
plt.show()
"""
    result = asyncio.run(executor.execute(_state(code, run_id="run-large-output", timeout=8)))
    assert result.status == "success"
    assert result.stdoutCapture.truncated is True
    assert result.stdoutCapture.omittedBytes > 0
    assert "START_MARKER" in result.stdout
    assert "END_MARKER" in result.stdout
    assert "中间输出已省略" in result.stdout
    assert len(result.plots) == 1


def test_executor_reports_timeout_and_supports_user_stop(monkeypatch):
    _runtime(monkeypatch, timeout=1)
    timeout_result = asyncio.run(LocalPythonExecutor().execute(
        _state("while True:\n    pass", run_id="run-timeout", timeout=1),
    ))
    assert timeout_result.status == "timeout"
    assert timeout_result.stopReason == "timeout"

    async def stop_case():
        executor = LocalPythonExecutor()
        task = asyncio.create_task(executor.execute(
            _state("while True:\n    pass", run_id="run-stop", timeout=3),
        ))
        await asyncio.sleep(0.25)
        await executor.stop("run-stop")
        result = await task
        assert executor._processes == {}
        return result

    stopped = asyncio.run(stop_case())
    assert stopped.status == "stopped"
    assert stopped.stopReason == "user_requested"


def test_frontend_route_uses_formal_workspace_contract():
    router = (ROOT / "frontend/src/router/index.js").read_text(encoding="utf-8")
    assert "name: 'CodeSandbox', component: CodeSandboxWorkspace" in router
    view = (ROOT / "frontend/src/views/CodeSandboxWorkspace.vue").read_text(encoding="utf-8")
    assert "grid-template-columns: 22fr 50fr 28fr" in view
    assert "runAttemptId" in view
    assert "标准输入" in view
    assert "AI 点评" in view
    assert "selectedRun.value?.status === 'success'" in view
    assert "const stderrLabel = computed(() => stderrIsWarning.value ? '警告' : '错误')" in view
    assert "{{ stderrLabel }}" in view
    assert "'error-output': !stderrIsWarning" in view
