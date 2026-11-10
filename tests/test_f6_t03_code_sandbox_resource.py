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
from app.m1_repository import add_artifact_version
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


def _resource(session, learner: DBUser, key: str = "f6-t03-resource-001", completion_rule: str = "保存代码，完成一次通过全部必需检查的真实运行，再明确提交完成。") -> DBArtifact:
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
            "completion_rule": completion_rule,
        }],
        learning_goal="通过真实代码运行理解分类阈值、混淆矩阵和误差边界",
    )
    session.commit()
    executed = execute_generation_job_demo(session, learner, job["job_id"])
    session.commit()
    item = executed["items"][0]
    assert item["state"] == "succeeded"
    return session.get(DBArtifact, item["resource"]["resource_id"])


def test_generated_default_completion_rule_remains_runnable_and_legacy_missing_rule_is_repaired():
    from app.migrations import _repair_generated_resource_completion_rules

    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        artifact = _resource(session, learner, completion_rule="")
        version = session.get(DBArtifactVersion, artifact.current_version_id)
        rule = parse_code_sandbox_content(version.content).completionRule
        original_content, original_hash = version.content, version.content_hash
        assert version.metadata_json["completion_rule"] == rule
        assert resource_detail(session, artifact)["code_sandbox"]["current"]["source_readiness"]["publishable"]

        # Reproduce the historical omission, then run the actual startup repair.
        version.metadata_json = {**version.metadata_json, "completion_rule": ""}
        session.commit()
        assert not resource_detail(session, artifact)["code_sandbox"]["current"]["source_readiness"]["publishable"]
        with engine.begin() as connection:
            _repair_generated_resource_completion_rules(connection)
        session.expire_all()
        assert version.metadata_json["completion_rule"] == rule
        assert (version.content, version.content_hash) == (original_content, original_hash)
        assert resource_detail(session, artifact)["code_sandbox"]["current"]["source_readiness"]["publishable"]

        # An explicit conflicting rule is not an omission and must remain blocked.
        version.metadata_json = {**version.metadata_json, "completion_rule": "另一项要求"}
        session.commit()
        with engine.begin() as connection:
            _repair_generated_resource_completion_rules(connection)
        session.expire_all()
        assert version.metadata_json["completion_rule"] == "另一项要求"
        assert not resource_detail(session, artifact)["code_sandbox"]["current"]["source_readiness"]["publishable"]
    finally:
        session.close()
        engine.dispose()


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


def test_multifile_run_imports_helpers_and_relative_packages(monkeypatch):
    _runtime(monkeypatch, timeout=8)
    state = _state("import stats.mean\nfrom stats import calculate\nprint(stats.mean.average([1, 2, 3]), calculate([2, 4]))", run_id="multifile", timeout=8)
    files = [
        code_sandbox.CodeSandboxFile(path="stats/__init__.py", content="from .mean import average as calculate"),
        code_sandbox.CodeSandboxFile(path="stats/mean.py", content="def average(values):\n    return sum(values) / len(values)"),
    ]
    state = state.model_copy(update={"files": tuple(files)})
    result = asyncio.run(LocalPythonExecutor().execute(state))
    assert result.status == "success", result.stderr
    assert result.stdout.strip() == "2.0 3.0"


def test_multifile_validation_checks_helper_code_and_runtime_errors(monkeypatch):
    _runtime(monkeypatch, timeout=8)
    state = _state("from helpers import result\nprint(result)", run_id="multifile-errors", timeout=8)
    for helper, expected in [("import os\nresult = 1", "os"), ("result = 1 / 0", "ZeroDivisionError")]:
        candidate = state.model_copy(update={"files": (code_sandbox.CodeSandboxFile(path="helpers.py", content=helper),)})
        result = asyncio.run(LocalPythonExecutor().execute(candidate))
        assert result.status == "runtime_error"
        assert expected in result.stderr


def test_multifile_run_freezes_saved_helpers_for_execution_and_review(monkeypatch):
    from app.code_review import _model_payload, _focus_strategy
    _runtime(monkeypatch, timeout=8)
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        artifact = _resource(session, learner, key="multifile-version")
        version = session.get(DBArtifactVersion, artifact.current_version_id)
        content = json.loads(version.content)
        entry = "from helpers import result\nprint(result)"
        content["files"] = [{"path": "main.py", "language": "python", "content": entry}, {"path": "helpers.py", "language": "python", "content": "result = 42"}]
        add_artifact_version(session, artifact=artifact, content=json.dumps(content), content_format="json", created_by_public_id=learner.public_id, metadata=version.metadata_json)
        run, _ = prepare_run(session, owner=learner.public_id, resource_id=artifact.id, resource_version_id=artifact.current_version_id, code=entry, standard_input="", idempotency_key="multifile-frozen-run")
        content["files"][1]["content"] = "result = 99"
        add_artifact_version(session, artifact=artifact, content=json.dumps(content), content_format="json", created_by_public_id=learner.public_id, metadata=version.metadata_json)
        result = asyncio.run(LocalPythonExecutor().execute(run))
        assert result.status == "success", result.stderr
        assert result.stdout.strip() == "42"
        payload = _model_payload(run, _focus_strategy(""))
        assert payload["run"]["files"][1]["content"] == "result = 42"
        assert "helpers" in payload["runtime"]["projectModules"]
    finally:
        session.close()
        engine.dispose()


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
        assert completed["evidenceStatus"] == "none"
        event = session.query(DBLearningEvent).filter_by(id=completed["eventId"]).one()
        assert event.context_ref["pathId"] == path.id
        assert completed["masteryEligible"] is False
        assert completed["completionEffect"] == "progress"
        event = session.get(DBLearningEvent, completed["eventId"])
        assert event.event_type == "code_tests_passed"
        assert event.payload["run_id"] == final.runAttemptId
        assert event.payload["test_scope"] == "required"
        assert event.payload["knowledge_point_id"] == "demo-kp-07"
        from app.learning_aggregation import _event_concept, _event_observations, _mastery_events
        assert event.payload["evidence_kind"] == "guided_practice"
        assert _event_concept(session, event)[0] == "demo-kp-07"
        assert _event_observations(session, event) == []
        assert event.id not in {row[0].id for row in _mastery_events(session, event)}
        # Older completions omitted the point; their frozen resource version is authoritative.
        old_payload = dict(event.payload)
        event.payload = {key: value for key, value in old_payload.items() if key != "knowledge_point_id"}
        assert _event_concept(session, event)[0] == "demo-kp-07"
        event.payload = old_payload
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
        workspace = resource_detail(session, artifact)["code_sandbox"]
        old_projection = next(item["projection"] for item in workspace["versions"] if item["id"] == version.id)
        assert old_projection["completion"]["status"] == "completed"
        assert old_projection["completion"]["run_attempt_id"] == final.runAttemptId
        assert workspace["current"]["completion"]["status"] == "not_recorded"

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


def test_optional_standard_input_handles_empty_and_supplied_values(monkeypatch):
    import asyncio
    from app.code_sandbox import LocalPythonExecutor
    _runtime(monkeypatch, timeout=8)
    code = "try:\n    text = input()\nexcept EOFError:\n    text = 'first attempt'\nprint(text)"
    for value, expected in [("", "first attempt"), ('{"degree": 3}', '{"degree": 3}')]:
        result = asyncio.run(LocalPythonExecutor().execute(
            _state(code, run_id="optional-stdin", timeout=8, standard_input=value)))
        assert result.status == "success" and not result.stderr
        assert result.stdout.strip() == expected


def test_standard_base_initializers_run_without_exposing_dunder_attributes(monkeypatch):
    import asyncio
    from app.code_sandbox import LocalPythonExecutor, validate_code

    _runtime(monkeypatch, timeout=8)
    code = '''class Base:
    def __init__(self, value):
        self.value = value
class Modern(Base):
    def __init__(self, value):
        super().__init__(value)
class Explicit(Base):
    def __init__(self, value):
        super(Explicit, self).__init__(value)
print(Modern(4).value + Explicit(5).value)
'''
    assert validate_code(code) is None
    result = asyncio.run(LocalPythonExecutor().execute(_state(code, run_id='base-initializers', timeout=8)))
    assert result.status == 'success' and result.stdout.strip() == '9'
    for forbidden in ('value.__class__', 'super().__getattribute__("value")',
                      'saved = super().__init__', 'value.__init__()'):
        assert validate_code(forbidden)


def test_memory_buffers_support_csv_and_model_parameter_roundtrips(monkeypatch):
    _runtime(monkeypatch, timeout=30)
    code = '''import io
from io import StringIO
import pandas as pd
import torch
frame = pd.read_csv(StringIO("x,y\\n1,2\\n3,4\\n"))
assert frame["y"].sum() == 6
tensor = torch.tensor([1., 2.])
for original in [tensor, [tensor], {"weights": tensor}]:
    buffer = io.BytesIO()
    torch.save(original, buffer)
    buffer.seek(0)
    restored = torch.load(buffer, weights_only=True)
    actual = restored[0] if isinstance(restored, list) else restored["weights"] if isinstance(restored, dict) else restored
    assert torch.equal(actual, tensor)
model = torch.nn.Linear(2, 1)
inputs = torch.tensor([[1., 2.], [3., 4.]])
expected = model(inputs).detach()
buffer = io.BytesIO()
torch.save(model.state_dict(), buffer)
buffer.seek(0)
copy = torch.nn.Linear(2, 1)
copy.load_state_dict(torch.load(buffer, weights_only=True))
assert torch.equal(copy(inputs).detach(), expected)
print("CSV, tensor, list, dictionary and model predictions restored")
'''
    result = asyncio.run(LocalPythonExecutor().execute(_state(code, run_id='memory-roundtrip', timeout=30)))
    assert result.status == 'success', result.stderr
    assert result.stdout.strip() == 'CSV, tensor, list, dictionary and model predictions restored'


def test_memory_io_does_not_add_disk_file_operations(monkeypatch):
    _runtime(monkeypatch, timeout=8)
    result = asyncio.run(LocalPythonExecutor().execute(_state(
        'import io\nprint(hasattr(io, "open"), hasattr(io, "FileIO"))',
        run_id='memory-only-io', timeout=8)))
    assert result.status == 'success', result.stderr
    assert result.stdout.strip() == 'False False'
    result = asyncio.run(LocalPythonExecutor().execute(_state(
        'from io import open', run_id='no-io-open', timeout=8)))
    assert result.status == 'runtime_error' and 'ImportError' in result.stderr

