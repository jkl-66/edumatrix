"""Resumable blind benchmark execution without inventing evaluation outputs."""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any, Protocol

from pydantic import ValidationError

from app.database import DBEvaluationCase, DBEvaluationResult, DBEvaluationRun
from app.m4_evaluation import M4EvaluationError
from app.m4_runs import BlindCaseOutput, record_blind_result, seal_blind_run


class BlindCaseExecutor(Protocol):
    async def execute(self, blind_case: dict[str, object]) -> BlindCaseOutput | dict[str, object]: ...


async def execute_blind_batch(
    session: Any,
    *,
    run: DBEvaluationRun,
    executor: BlindCaseExecutor,
    timeout_seconds: float = 120.0,
    limit: int | None = None,
) -> dict[str, object]:
    if run.status != "running":
        raise M4EvaluationError("evaluation_run_not_running", "batch execution requires a running evaluation")
    cases = session.query(DBEvaluationCase).filter_by(case_version=run.data_version).order_by(DBEvaluationCase.case_code).all()
    if len(cases) != 60:
        raise M4EvaluationError("evaluation_case_count_invalid", f"batch execution requires 60 cases, found {len(cases)}")
    completed_case_ids = {
        case.case_code
        for case, _ in (
            session.query(DBEvaluationCase, DBEvaluationResult)
            .join(DBEvaluationResult, DBEvaluationResult.evaluation_case_id == DBEvaluationCase.id)
            .filter(DBEvaluationResult.evaluation_run_id == run.id)
            .all()
        )
    }
    pending = [case for case in cases if case.case_code not in completed_case_ids]
    if limit is not None:
        pending = pending[: max(limit, 0)]

    statuses = Counter()
    for case in pending:
        blind = dict(case.input_data)
        try:
            raw = await asyncio.wait_for(executor.execute(blind), timeout=timeout_seconds)
            output = raw if isinstance(raw, BlindCaseOutput) else BlindCaseOutput.model_validate(raw)
            if output.case_id != case.case_code:
                raise ValueError("executor returned another case_id")
        except asyncio.TimeoutError:
            output = BlindCaseOutput(case_id=case.case_code, status="timeout", error_code="executor_timeout")
        except (ValidationError, ValueError, TypeError):
            output = BlindCaseOutput(case_id=case.case_code, status="failed", error_code="executor_output_invalid")
        except Exception as exc:
            output = BlindCaseOutput(
                case_id=case.case_code,
                status="failed",
                error_code=f"executor_{type(exc).__name__.lower()}",
            )
        record_blind_result(session, run=run, output=output)
        statuses[output.status] += 1

    persisted = session.query(DBEvaluationResult).filter_by(evaluation_run_id=run.id).count()
    sealed = False
    if persisted == 60:
        seal_blind_run(session, run)
        sealed = True
    return {
        "run_id": run.id,
        "attempted": len(pending),
        "status_counts": dict(statuses),
        "persisted": persisted,
        "remaining": 60 - persisted,
        "sealed": sealed,
        "run_status": run.status,
    }
