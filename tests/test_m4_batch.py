import asyncio

from app.m4_batch import execute_blind_batch
from app.m4_evaluation import load_frozen_benchmark
from app.m4_runs import start_evaluation_run, sync_frozen_cases
from tests.test_m4_runs import _session


class _Executor:
    def __init__(self):
        self.calls = 0

    async def execute(self, blind_case):
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("injected provider failure")
        return {
            "case_id": blind_case["case_id"],
            "status": "completed",
            "response_text": "structured test output",
        }


def test_m4_batch_persists_failures_and_resumes_without_duplicate_results():
    session, version = _session()
    benchmark = load_frozen_benchmark()
    sync_frozen_cases(session, benchmark=benchmark, domain_version_id=version.id)
    run = start_evaluation_run(
        session,
        benchmark=benchmark,
        trace_id="trace-m4-batch-001",
        code_version="test-tree",
        model_version="test-double",
    )

    executor = _Executor()
    first = asyncio.run(execute_blind_batch(session, run=run, executor=executor, limit=2))
    second = asyncio.run(execute_blind_batch(session, run=run, executor=executor, limit=1))

    assert first["persisted"] == 2
    assert first["status_counts"] == {"completed": 1, "failed": 1}
    assert second["persisted"] == 3
    assert second["attempted"] == 1
    assert second["remaining"] == 57
