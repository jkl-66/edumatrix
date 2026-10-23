"""Run or resume the frozen 60-case M4 benchmark against the configured real model."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "outputs" / "M4_量化评测与可靠性交付" / "evidence" / "real-run" / "m4_real.db"
REQUIRED_MODEL = "deepseek-v4-flash"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run or resume the real M4 blind benchmark")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--trace-id", default="trace-m4-real-deepseek-v4-flash-v1")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser


def _code_version() -> str:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"], cwd=ROOT, check=True,
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except Exception:
        commit = "unknown"
    try:
        dirty = bool(subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, check=True,
            capture_output=True, text=True, timeout=10,
        ).stdout.strip())
    except Exception:
        dirty = True
    return f"{commit}+{'dirty' if dirty else 'clean'}+m4-real-executor-v2"


def _assert_real_model_policy(config, llm) -> None:
    if config.llm_model != REQUIRED_MODEL or getattr(llm, "model", "") != REQUIRED_MODEL:
        raise RuntimeError(f"real M4 run requires {REQUIRED_MODEL}")
    if config.llm_thinking_mode != "max":
        raise RuntimeError("real M4 run requires thinking=enabled through EDUMATRIX_LLM_THINKING_MODE=max")
    if config.llm_reasoning_effort != "max":
        raise RuntimeError("real M4 run requires reasoning_effort=max")
    if getattr(llm, "thinking_mode", "") != "max":
        raise RuntimeError("real M4 backend requires thinking_mode=max")
    if getattr(llm, "reasoning_effort", "") != "max":
        raise RuntimeError("real M4 backend requires reasoning_effort=max")
    if os.getenv("EDUMATRIX_ALLOW_LLM_FALLBACK", "0") != "0":
        raise RuntimeError("real M4 run requires allow_fallback=false")
    if "Fallback" in type(llm).__name__ or "Deterministic" in type(llm).__name__:
        raise RuntimeError("real M4 run forbids fallback and deterministic model backends")


def main() -> int:
    args = _parser().parse_args()
    db_path = args.db.resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    os.environ["EDUMATRIX_DB_PATH"] = str(db_path)
    os.environ["EDUMATRIX_ALLOW_LLM_FALLBACK"] = "0"
    os.environ["EDUMATRIX_DISABLE_LLM_FALLBACK"] = "1"
    sys.path.insert(0, str(ROOT))

    from app.database import DBEvaluationResult, SessionLocal, init_db
    from app.m1_evidence import seed_rag_domain_pack
    from app.m2_baseline import seed_m2_baseline
    from app.m4_batch import execute_blind_batch
    from app.m4_evaluation import load_frozen_benchmark
    from app.m4_executor import M4RealModelExecutor, load_m4_source_material
    from app.m4_runs import blind_cases_for_run, start_evaluation_run, sync_frozen_cases
    from config import CONFIG
    from llm_client import build_async_llm

    llm = build_async_llm()
    _assert_real_model_policy(CONFIG, llm)
    init_db()
    benchmark = load_frozen_benchmark()
    with SessionLocal() as session:
        fixture = seed_m2_baseline(session)
        domain = seed_rag_domain_pack(session)
        sync_frozen_cases(session, benchmark=benchmark, domain_version_id=str(domain["domain_version_id"]))
        model_version = (
            f"{CONFIG.llm_model};thinking=enabled;thinking_mode={CONFIG.llm_thinking_mode};"
            f"reasoning_effort={CONFIG.llm_reasoning_effort};"
            f"allow_fallback=false;max_tokens={CONFIG.llm_max_tokens}"
        )
        run = start_evaluation_run(
            session,
            benchmark=benchmark,
            trace_id=args.trace_id,
            code_version=_code_version(),
            model_version=model_version,
        )
        if run.status == "awaiting_annotation":
            summary = {
                "run_id": run.id,
                "status": run.status,
                "persisted": session.query(DBEvaluationResult).filter_by(evaluation_run_id=run.id).count(),
                "remaining": 0,
                "resumed": True,
            }
        else:
            executor = M4RealModelExecutor(
                llm, sources=load_m4_source_material(session), session=session, trace_id=run.trace_id,
            )
            executor.preflight(blind_cases_for_run(session, run))
            summary = asyncio.run(execute_blind_batch(
                session,
                run=run,
                executor=executor,
                timeout_seconds=args.timeout,
                limit=args.limit,
            ))
            summary["resumed"] = summary["persisted"] > summary["attempted"]
        summary.update({
            "database": str(db_path.relative_to(ROOT)).replace("\\", "/"),
            "trace_id": args.trace_id,
            "model_version": model_version,
            "gold_visible_to_executor": False,
        })
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
