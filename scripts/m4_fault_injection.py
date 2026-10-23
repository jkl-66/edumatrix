"""Prove M4 process-crash durability and cross-process resume on SQLite."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    ROOT / "outputs" / "M4_量化评测与可靠性交付" / "evidence"
    / "fault-injection-20260802"
)
TRACE_ID = "trace-m4-fault-injection-v1"
CRASH_EXIT_CODE = 73
CRASH_AFTER = 13


class DeterministicExecutor:
    async def execute(self, blind_case: dict[str, object]) -> dict[str, object]:
        case_id = str(blind_case["case_id"])
        return {
            "case_id": case_id,
            "status": "completed",
            "response_text": f"fault-injection deterministic output for {case_id}",
            "evidence": {"executor": "deterministic-fault-injection-v1"},
        }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _configure_database(db_path: Path) -> None:
    os.environ["EDUMATRIX_DB_PATH"] = str(db_path.resolve())
    os.environ["EDUMATRIX_ENV"] = "test"
    sys.path.insert(0, str(ROOT))


def _open_run(db_path: Path) -> tuple[Any, Any]:
    _configure_database(db_path)
    from app.database import SessionLocal, init_db
    from app.m1_evidence import seed_rag_domain_pack
    from app.m4_evaluation import load_frozen_benchmark
    from app.m4_runs import start_evaluation_run, sync_frozen_cases

    init_db()
    session = SessionLocal()
    benchmark = load_frozen_benchmark()
    domain = seed_rag_domain_pack(session)
    sync_frozen_cases(session, benchmark=benchmark, domain_version_id=str(domain["domain_version_id"]))
    run = start_evaluation_run(
        session,
        benchmark=benchmark,
        trace_id=TRACE_ID,
        code_version="m4-fault-injection-v1",
        model_version="deterministic-no-network-v1",
    )
    return session, run


def crash_worker(db_path: Path) -> int:
    session, run = _open_run(db_path)
    from app.m4_batch import execute_blind_batch

    summary = asyncio.run(execute_blind_batch(
        session, run=run, executor=DeterministicExecutor(), limit=CRASH_AFTER,
    ))
    if summary["persisted"] != CRASH_AFTER or summary["sealed"]:
        raise RuntimeError(f"unexpected pre-crash state: {summary}")
    # Deliberately skip context-manager cleanup to model sudden process loss
    # after each result transaction has already committed.
    os._exit(CRASH_EXIT_CODE)


def recover_worker(db_path: Path) -> dict[str, object]:
    session, run = _open_run(db_path)
    from app.m4_batch import execute_blind_batch

    before = _result_count(session, run.id)
    summary = asyncio.run(execute_blind_batch(
        session, run=run, executor=DeterministicExecutor(),
    ))
    after = _result_count(session, run.id)
    session.close()
    return {"before": before, "after": after, **summary}


def _result_count(session: Any, run_id: str) -> int:
    from app.database import DBEvaluationResult

    return session.query(DBEvaluationResult).filter_by(evaluation_run_id=run_id).count()


def verify_database(db_path: Path) -> dict[str, object]:
    session, run = _open_run(db_path)
    from sqlalchemy import text
    from app.database import DBEvaluationCase, DBEvaluationResult, engine

    rows = (
        session.query(DBEvaluationCase.case_code, DBEvaluationResult.output_data)
        .join(DBEvaluationResult, DBEvaluationResult.evaluation_case_id == DBEvaluationCase.id)
        .filter(DBEvaluationResult.evaluation_run_id == run.id)
        .order_by(DBEvaluationCase.case_code)
        .all()
    )
    duplicate_count = session.execute(text(
        "SELECT COUNT(*) FROM (SELECT evaluation_case_id FROM evaluation_results "
        "WHERE evaluation_run_id=:run_id GROUP BY evaluation_case_id HAVING COUNT(*) > 1)"
    ), {"run_id": run.id}).scalar_one()
    case_ids = [case_id for case_id, _ in rows]
    output_case_ids = [str(payload.get("case_id", "")) for _, payload in rows]
    run_id = run.id
    run_status = run.status
    session.close()
    engine.dispose()
    with sqlite3.connect(db_path) as connection:
        checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    checks = {
        "sqlite_integrity_ok": integrity == "ok",
        "wal_checkpoint_not_busy": checkpoint[0] == 0,
        "run_sealed": run_status == "awaiting_annotation",
        "result_count_60": len(rows) == 60,
        "unique_case_count_60": len(set(case_ids)) == 60,
        "no_duplicate_results": duplicate_count == 0,
        "output_case_ids_match": case_ids == output_case_ids,
    }
    if not all(checks.values()):
        raise RuntimeError(f"fault-injection verification failed: {checks}")
    return {
        "run_id": run_id,
        "trace_id": TRACE_ID,
        "run_status": run_status,
        "result_count": len(rows),
        "checks": checks,
    }


def orchestrate(output: Path) -> dict[str, object]:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite fault evidence: {output}")
    output.mkdir(parents=True)
    db_path = output / "m4_fault_injection.db"
    command = [sys.executable, str(Path(__file__).resolve()), "worker"]

    crash = subprocess.run(command + ["crash", "--db", str(db_path)], cwd=ROOT, capture_output=True, text=True)
    if crash.returncode != CRASH_EXIT_CODE:
        raise RuntimeError(f"crash worker returned {crash.returncode}: {crash.stderr}")
    post_crash = subprocess.run(command + ["verify-partial", "--db", str(db_path)], cwd=ROOT, capture_output=True, text=True)
    if post_crash.returncode != 0:
        raise RuntimeError(f"partial verifier failed: {post_crash.stderr}")
    partial = json.loads(post_crash.stdout)
    if partial["result_count"] != CRASH_AFTER or partial["run_status"] != "running":
        raise RuntimeError(f"committed crash boundary not preserved: {partial}")

    recovery = subprocess.run(command + ["recover", "--db", str(db_path)], cwd=ROOT, capture_output=True, text=True)
    if recovery.returncode != 0:
        raise RuntimeError(f"recovery worker failed: {recovery.stderr}")
    recovered = json.loads(recovery.stdout)
    final_check = subprocess.run(command + ["verify-final", "--db", str(db_path)], cwd=ROOT, capture_output=True, text=True)
    if final_check.returncode != 0:
        raise RuntimeError(f"final verifier failed: {final_check.stderr}")
    final = json.loads(final_check.stdout)
    if recovered["before"] != CRASH_AFTER or recovered["attempted"] != 60 - CRASH_AFTER:
        raise RuntimeError(f"recovery did not resume at exact boundary: {recovered}")

    report = {
        "schema_version": "m4.fault-injection-evidence.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scenario": "hard_process_exit_after_committed_result_then_new_process_resume",
        "network_used": False,
        "crash": {
            "expected_exit_code": CRASH_EXIT_CODE,
            "actual_exit_code": crash.returncode,
            "committed_before_crash": partial["result_count"],
        },
        "recovery": recovered,
        "verification": final,
        "database": {"file": db_path.name, "bytes": db_path.stat().st_size, "sha256": _sha256(db_path)},
    }
    report_path = output / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": "m4.fault-injection-manifest.v1",
        "files": {
            db_path.name: {"bytes": db_path.stat().st_size, "sha256": _sha256(db_path)},
            report_path.name: {"bytes": report_path.stat().st_size, "sha256": _sha256(report_path)},
        },
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def verify_partial(db_path: Path) -> dict[str, object]:
    session, run = _open_run(db_path)
    count = _result_count(session, run.id)
    status = run.status
    session.close()
    return {"result_count": count, "run_status": status}


def verify_package(output: Path) -> dict[str, object]:
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    actual = {p.name for p in output.iterdir() if p.is_file() and p.name != "manifest.json"}
    if actual != set(manifest["files"]):
        raise ValueError("fault evidence contains missing or unexpected files")
    for name, expected in manifest["files"].items():
        path = output / name
        if path.stat().st_size != expected["bytes"] or _sha256(path) != expected["sha256"]:
            raise ValueError(f"fault evidence changed: {name}")
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    if not all(report["verification"]["checks"].values()):
        raise ValueError("fault evidence contains a failed verification check")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "verify"):
        item = sub.add_parser(name)
        item.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    worker = sub.add_parser("worker")
    worker.add_argument("phase", choices=("crash", "verify-partial", "recover", "verify-final"))
    worker.add_argument("--db", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "run":
        result = orchestrate(args.output.resolve())
    elif args.command == "verify":
        result = verify_package(args.output.resolve())
    elif args.phase == "crash":
        return crash_worker(args.db.resolve())
    elif args.phase == "verify-partial":
        result = verify_partial(args.db.resolve())
    elif args.phase == "verify-final":
        result = verify_database(args.db.resolve())
    else:
        result = recover_worker(args.db.resolve())
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
