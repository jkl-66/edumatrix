#!/usr/bin/env python3
"""Record incremental F6-T05 implementation and verification evidence."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER = next(
    (
        ROOT
        / "outputs"
        / "原系统融合重构执行"
        / "evidence"
        / "context_recovery"
        / "atomic_requirement_ledgers"
        / "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION"
    ).glob("F6-T05_*.json")
)

BATCHES = {
    "backend": {
        "atoms": [
            "G18-R01", "G18-R02", "G18-R04", "G18-R05", "G18-R06", "G18-R07",
            "G18-R08", "G18-R10", "G18-R11", "G18-R12", "G18-R13",
            "G22-R02", "G22-R03", "G22-R04", "G22-R05", "G22-R06", "G22-R08",
            "G22-R09", "G22-R10", "G22-R11", "G22-R13", "G22-R14", "G22-R15", "G22-R16",
        ],
        "files": ["app/feynman.py", "app/feynman_api.py", "app/main.py"],
        "result": (
            "Implemented owned versioned Feynman sessions, dynamic frozen task context, strict transitions, "
            "deterministic two-round rubric, grounded learner question answer, record-based comparison, "
            "idempotency, and final shared learning-event aggregation."
        ),
        "verification": [
            "python -m py_compile app/feynman.py app/feynman_api.py app/main.py",
            ".venv/Scripts/python.exe -m pytest -q tests/test_f6_t05_feynman.py -k not dedicated_frontend: 3 passed",
        ],
    },
    "frontend": {
        "atoms": [
            "G18-R01", "G18-R02", "G18-R03", "G18-R04", "G18-R05", "G18-R06",
            "G18-R07", "G18-R08", "G18-R09", "G18-R12", "G18-R14",
            "G22-R07", "G22-R08", "G22-R09", "G22-R10", "G22-R11", "G22-R12",
            "G22-R13", "G22-R16",
        ],
        "files": [
            "frontend/src/api/feynman.js",
            "frontend/src/api/index.js",
            "frontend/src/router/index.js",
            "frontend/src/components/FeynmanEvaluationPanel.vue",
            "frontend/src/views/FeynmanWorkspace.vue",
        ],
        "result": (
            "Replaced the Chat route reuse with a dedicated five-stage workspace containing persistent progress, "
            "current-stage focus, collapsed completed summaries, draft recovery, optional speech input, source and history disclosure."
        ),
        "verification": [],
    },
    "tests": {
        "atoms": [
            "G18-R01", "G18-R02", "G18-R03", "G18-R04", "G18-R05", "G18-R06",
            "G18-R07", "G18-R08", "G18-R09", "G18-R10", "G18-R11", "G18-R12",
            "G18-R13", "G18-R14", "G22-R01", "G22-R02", "G22-R03", "G22-R04",
            "G22-R05", "G22-R06", "G22-R07", "G22-R08", "G22-R09", "G22-R10",
            "G22-R11", "G22-R12", "G22-R13", "G22-R14", "G22-R15", "G22-R16",
        ],
        "files": ["tests/test_f6_t05_feynman.py", "scripts/e2e_f6_t05_feynman.py"],
        "result": "Focused, regression, build, browser, SQLite, and visual evidence verifies the complete F6-T05 contract.",
        "verification": [],
    },
}


def append_unique(values: list[str], additions: list[str]) -> list[str]:
    return list(dict.fromkeys([*values, *additions]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", choices=sorted(BATCHES))
    parser.add_argument("--verification", action="append", default=[])
    args = parser.parse_args()
    batch = BATCHES[args.batch]
    stamp = datetime.now(timezone.utc).isoformat()
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    for entry in ledger["entries"]:
        if entry["atomic_requirement_id"] not in batch["atoms"]:
            continue
        realization = entry["realization"]
        realization["status"] = "IMPLEMENTATION_IN_PROGRESS"
        realization["implementation_evidence"] = append_unique(
            realization.get("implementation_evidence", []),
            [f"F6-T05-{args.batch} at {stamp}: {', '.join(batch['files'])}", batch["result"]],
        )
        realization["verification_evidence"] = append_unique(
            realization.get("verification_evidence", []),
            [*batch["verification"], *args.verification],
        )
    execution_batches = ledger.setdefault("execution_batches", [])
    record = next((item for item in execution_batches if item.get("id") == args.batch), None)
    if record is None:
        record = {"id": args.batch}
        execution_batches.append(record)
    record.update({
        "status": "IMPLEMENTED_PENDING_FINAL_VERIFICATION",
        "updated_at": stamp,
        "atoms": batch["atoms"],
        "files": batch["files"],
        "result": batch["result"],
        "verification": [*batch["verification"], *args.verification],
    })
    LEDGER.write_text(
        json.dumps(ledger, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Recorded F6-T05 {args.batch} batch for {len(batch['atoms'])} atoms")


if __name__ == "__main__":
    main()
