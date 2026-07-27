"""Export or verify an M4 evaluation evidence package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import DBEvaluationRun, SessionLocal
from app.m4_evaluation import M4EvaluationError, load_frozen_benchmark
from app.m4_evidence import export_evidence_package, verify_evidence_package


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export or verify an M4 evidence package")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="export one persisted evaluation run")
    export.add_argument("--run-id", required=True)
    export.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify", help="verify an existing evidence package")
    verify.add_argument("--input", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "verify":
            manifest = verify_evidence_package(args.input)
        else:
            with SessionLocal() as session:
                run = session.query(DBEvaluationRun).filter_by(id=args.run_id).first()
                if run is None:
                    raise M4EvaluationError("evaluation_run_unknown", "evaluation run does not exist")
                manifest = export_evidence_package(
                    session,
                    run=run,
                    benchmark=load_frozen_benchmark(),
                    output_dir=args.output,
                )
        print(json.dumps({
            "ok": True,
            "run_id": manifest["run"]["id"],
            "result_count": manifest["result_count"],
            "failure_count": manifest["failure_count"],
        }, ensure_ascii=False))
        return 0
    except M4EvaluationError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "message": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
