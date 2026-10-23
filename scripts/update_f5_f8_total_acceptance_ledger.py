#!/usr/bin/env python3
"""Record one mapped F5-F8 total-acceptance work batch."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER = (
    ROOT
    / "outputs"
    / "原系统融合重构执行"
    / "evidence"
    / "f5_f8_total_acceptance"
    / "atomic_execution_ledger.json"
)
VALID_ATOMS = {f"F5F8-R{index:02d}" for index in range(1, 19)}


def atomic_write(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def unique(values: list[str], additions: list[str]) -> list[str]:
    return list(dict.fromkeys([*values, *additions]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("batch")
    parser.add_argument("--atom", action="append", required=True)
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--protection", action="append", default=[])
    parser.add_argument("--result", required=True)
    parser.add_argument("--verification", action="append", default=[])
    parser.add_argument("--visible", default="")
    parser.add_argument(
        "--status",
        choices=("IN_PROGRESS", "PASSED", "FAILED"),
        default="IN_PROGRESS",
    )
    args = parser.parse_args()

    atoms = list(dict.fromkeys(args.atom))
    unknown = sorted(set(atoms) - VALID_ATOMS)
    if unknown:
        raise RuntimeError(f"Unknown total-acceptance atoms: {unknown}")

    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    if ledger.get("task_id") != "F5-F8-TOTAL-ACCEPTANCE":
        raise RuntimeError("The active ledger is not F5-F8-TOTAL-ACCEPTANCE")
    entries = {entry["atomic_requirement_id"]: entry for entry in ledger["entries"]}
    if set(entries) != VALID_ATOMS:
        raise RuntimeError("The total-acceptance atom set changed")

    stamp = datetime.now(timezone.utc).astimezone().isoformat()
    batches = ledger.setdefault("execution_batches", [])
    if any(item.get("batch") == args.batch for item in batches):
        raise RuntimeError(f"Batch already exists: {args.batch}")
    batches.append(
        {
            "batch": args.batch,
            "status": args.status,
            "updated_at": stamp,
            "mapped_atoms": atoms,
            "protection_contracts": list(dict.fromkeys(args.protection)),
            "changed_files": list(dict.fromkeys(args.file)),
            "result": args.result,
            "verification": args.verification,
        }
    )

    evidence_line = f"{args.batch} at {stamp}: {args.result}"
    for atom_id in atoms:
        realization = entries[atom_id]["total_realization"]
        if realization.get("status") == "IMPLEMENTED_AND_VERIFIED":
            raise RuntimeError(f"Cannot append work to closed atom {atom_id}")
        realization["status"] = "VERIFICATION_IN_PROGRESS"
        realization["implementation_or_protection_evidence"] = unique(
            list(realization.get("implementation_or_protection_evidence") or []),
            [evidence_line, *args.file],
        )
        realization["verification_evidence"] = unique(
            list(realization.get("verification_evidence") or []),
            args.verification,
        )
        if args.visible:
            realization["user_visible_result"] = args.visible

    ledger["updated_at"] = stamp
    atomic_write(LEDGER, ledger)
    print(json.dumps({"status": "RECORDED", "batch": args.batch, "atoms": atoms}, ensure_ascii=False))


if __name__ == "__main__":
    main()
