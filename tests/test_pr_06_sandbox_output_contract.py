from __future__ import annotations

import asyncio

from app.code_sandbox import (
    LocalPythonExecutor,
    finalize_run,
    get_run,
    mark_run_running,
    prepare_run,
)
from app.competition_demo_seed import seed_competition_demo
from app.database import DBArtifactVersion, DBLearningEvent, DBUser
from tests.test_f6_t03_code_sandbox_resource import _resource, _runtime, _session, _state


def test_large_stdout_keeps_preview_and_controlled_complete_result(monkeypatch):
    _runtime(monkeypatch, timeout=8, output_limit=4096)
    code = "print('START_MARKER')\nprint('x' * 12000)\nprint('END_MARKER')"

    result = asyncio.run(LocalPythonExecutor().execute(
        _state(code, run_id="pr06-large-output", timeout=8),
    ))

    assert result.stdoutCapture.truncated is True
    assert result.stdoutComplete is not None
    assert result.stdoutComplete.available is True
    assert result.stdoutComplete.capture.truncated is False
    assert "START_MARKER" in result.stdout
    assert "END_MARKER" in result.stdout
    assert "x" * 12000 in result.stdoutComplete.text
    assert result.stdoutComplete.capture.totalBytes > result.stdoutCapture.capturedBytes


def test_stderr_and_plots_remain_independent_complete_results(monkeypatch):
    _runtime(monkeypatch, timeout=8, output_limit=4096)
    code = """import matplotlib.pyplot as plt
plt.plot([0, 1, 2], [0, 1, 4])
plt.title('pr06')
raise RuntimeError('PR06_STDERR_MARKER')
"""

    result = asyncio.run(LocalPythonExecutor().execute(
        _state(code, run_id="pr06-stderr-plot", timeout=8),
    ))

    assert result.status == "runtime_error"
    assert result.stderrComplete is not None
    assert result.stderrComplete.available is True
    assert "PR06_STDERR_MARKER" in result.stderrComplete.text
    assert len(result.plots) == 1
    assert result.stdoutComplete is not None
    assert result.stdoutComplete.text == ""


def test_run_detail_can_restore_complete_output_without_learning_write(monkeypatch):
    _runtime(monkeypatch, timeout=8, output_limit=4096)
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        artifact = _resource(session, learner, "pr06-run-detail-001")
        version = session.get(DBArtifactVersion, artifact.current_version_id)
        before = session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count()

        queued, created = prepare_run(
            session,
            owner=learner.public_id,
            resource_id=artifact.id,
            resource_version_id=version.id,
            code="print('PR06_PERSISTED_OUTPUT')",
            standard_input="",
            idempotency_key="pr06-run-detail-idempotency-001",
        )
        assert created is True
        running = mark_run_running(session, queued.runAttemptId)
        result = asyncio.run(LocalPythonExecutor().execute(running))
        final = finalize_run(session, queued.runAttemptId, result)
        session.commit()

        preview = get_run(session, owner=learner.public_id, run_id=final.runAttemptId)
        assert preview["completeOutputIncluded"] is False
        assert preview["stdoutComplete"]["available"] is True
        assert preview["stdoutComplete"]["text"] == ""

        restored = get_run(
            session,
            owner=learner.public_id,
            run_id=final.runAttemptId,
            include_complete=True,
        )
        assert restored["completeOutputIncluded"] is True
        assert "PR06_PERSISTED_OUTPUT" in restored["stdoutComplete"]["text"]
        assert session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count() == before
    finally:
        session.close()
        engine.dispose()
