#!/usr/bin/env python3
"""Update the task-local F10-T03 ledger from concrete audit/final evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f10_t03_final_context"
LEDGER_DIR = (
    ROOT
    / "outputs"
    / "原系统融合重构执行"
    / "evidence"
    / "context_recovery"
    / "atomic_requirement_ledgers"
    / "EDUMATRIX-F9-F10-CONTEXT-SAFE-FUSION-COMPLETION"
)


def atomic_write(path: Path, payload: dict) -> None:
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def ledger_path() -> Path:
    matches = sorted(LEDGER_DIR.glob("F10-T03_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one F10-T03 ledger, found {len(matches)}")
    return matches[0]


def update_audit(ledger: dict) -> None:
    evidence = [
        "outputs/原系统融合重构执行/evidence/f10_t03_final_context/batch_01_audit_mapping.json",
        "outputs/原系统融合重构执行/evidence/f10_t03_final_context/audit_findings.json",
        "outputs/原系统融合重构执行/evidence/f10_t03_final_context/spec_crosscheck_baseline.json",
        "python -m pytest -q tests/test_competition_package_runtime.py tests/test_context_recovery_packets.py -> 25 passed",
        "scripts/runtime_preflight.py with project .venv -> PASS",
    ]
    for entry in ledger["entries"]:
        realization = entry["realization"]
        realization["status"] = "AUDIT_VERIFIED_IN_PROGRESS"
        realization["verification_evidence"] = evidence
        realization["compatibility_or_defer_rationale"] = (
            "F10-T03-B01 verified the existing specification/evidence chain and recorded "
            "the concrete documentation, deployment, demo-data, sandbox, secret-log and smoke-test "
            "actions that must be corrected before final compatibility can be claimed."
        )


def update_final(ledger: dict) -> None:
    inventory_path = EVIDENCE / "final_context_inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    if inventory.get("status") != "PASS":
        raise RuntimeError("final context inventory is not PASS")
    atomic_evidence = inventory.get("atomic_evidence", {})
    for entry in ledger["entries"]:
        atom_id = entry["atomic_requirement_id"]
        evidence = atomic_evidence.get(atom_id)
        if not evidence or evidence.get("status") != "COMPATIBILITY_VERIFIED":
            raise RuntimeError(f"missing final evidence for {atom_id}")
        realization = entry["realization"]
        realization["status"] = "COMPATIBILITY_VERIFIED"
        realization["implementation_evidence"] = evidence["implementation_evidence"]
        realization["verification_evidence"] = evidence["verification_evidence"]
        realization["user_visible_result"] = evidence["user_visible_result"]
        realization["compatibility_or_defer_rationale"] = evidence[
            "compatibility_or_defer_rationale"
        ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("audit", "final"), required=True)
    args = parser.parse_args()
    path = ledger_path()
    ledger = json.loads(path.read_text(encoding="utf-8"))
    if ledger.get("task") != "F10-T03" or len(ledger.get("entries", [])) != 27:
        raise RuntimeError("unexpected F10-T03 ledger")
    if args.stage == "audit":
        update_audit(ledger)
    else:
        update_final(ledger)
    atomic_write(path, ledger)
    print(json.dumps({"task": "F10-T03", "stage": args.stage, "entries": 27}))


if __name__ == "__main__":
    main()
