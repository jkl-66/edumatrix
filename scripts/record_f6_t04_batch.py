#!/usr/bin/env python3
"""Record incremental F6-T04 implementation and verification evidence."""

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
    ).glob("F6-T04_*.json")
)

BATCHES = {
    "backend": {
        "atoms": ["G16-R03", "G16-R04", "G16-R05", "G16-R09", "G27-R02", "G27-R03", "G27-R04", "G27-R06", "G27-R07"],
        "files": ["app/code_review.py", "app/code_sandbox_api.py"],
        "result": "Persisted evidence-bound local review, sanitized Agent audit, and apply-as-new-resource-version endpoints were implemented.",
        "verification": ["python -m py_compile app/code_review.py app/code_sandbox_api.py"],
    },
    "tests": {
        "atoms": ["G16-R01", "G16-R02", "G16-R03", "G16-R04", "G16-R05", "G16-R07", "G16-R08", "G16-R10", "G16-R11", "G16-R12", "G27-R04", "G27-R06", "G27-R07"],
        "files": ["tests/test_f6_t04_code_review.py"],
        "result": "Focused automated tests cover eligibility, evidence hashes, focus, idempotency, sanitization, immutable application, rerun, and completion isolation.",
        "verification": [],
    },
    "frontend": {
        "atoms": ["G16-R03", "G16-R04", "G16-R05", "G16-R06", "G16-R09", "G27-R02", "G27-R03", "G27-R04", "G27-R05", "G27-R06", "G27-R07"],
        "files": ["frontend/src/api/codeSandbox.js", "frontend/src/components/CodeReviewPanel.vue", "frontend/src/views/CodeSandboxWorkspace.vue"],
        "result": "The honest placeholder was replaced with a state-complete review panel inside the existing 28-percent result column.",
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
        atom_id = entry["atomic_requirement_id"]
        if atom_id not in batch["atoms"]:
            continue
        realization = entry["realization"]
        realization["status"] = "IMPLEMENTATION_IN_PROGRESS"
        realization["implementation_evidence"] = append_unique(
            realization.get("implementation_evidence", []),
            [f"F6-T04-{args.batch} at {stamp}: {', '.join(batch['files'])}", batch["result"]],
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
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"Recorded F6-T04 {args.batch} batch for {len(batch['atoms'])} atoms")


if __name__ == "__main__":
    main()
