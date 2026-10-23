#!/usr/bin/env python3
"""Record incremental F7-T01 implementation and verification evidence."""

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
    ).glob("F7-T01_*.json")
)

PRIMARY = ["G11-R01", "G11-R02", "G11-R04", "G11-R08", "G20-R08"]
RELATED = ["G11-R03", "G11-R05", "G11-R06", "G11-R07", "G11-R09"]
BATCHES = {
    "backend": {
        "atoms": [*PRIMARY, *RELATED],
        "files": ["knowledge_api.py", "frontend/src/api/knowledge.js", "tests/test_f7_t01_knowledge_shelf.py"],
        "result": (
            "Implemented a local canonical course-shelf catalog, explainable profile/course recommendation, "
            "idempotent shelf membership, and course/source/index health protocol without external calls."
        ),
        "verification": [],
    },
    "backend-tests": {
        "atoms": [*PRIMARY, "G11-R03", "G11-R07", "G11-R09"],
        "files": ["tests/test_f7_t01_knowledge_shelf.py"],
        "result": (
            "Focused API tests verified the preloaded AI/ML course, hierarchy counts, reviewed sources, "
            "explainable recommendation, authentication, raw-source exclusion, and idempotent shelf addition."
        ),
        "verification": [],
    },
    "frontend": {
        "atoms": [*PRIMARY, *RELATED],
        "files": ["frontend/src/views/Knowledge.vue", "frontend/src/api/knowledge.js"],
        "result": (
            "Rebuilt Knowledge as a course-first bookshelf and route-aware course workspace while preserving "
            "legacy upload, retrieval, OCR, source, and graph capabilities behind progressive disclosure."
        ),
        "verification": [],
    },
    "frontend-tests": {
        "atoms": [*PRIMARY, *RELATED],
        "files": ["tests/test_f7_t01_knowledge_frontend_contract.py"],
        "result": "Static and component contracts cover the course-first layout, F1 visual rules, routes, and protected capabilities.",
        "verification": [],
    },
    "browser-prep": {
        "atoms": [*PRIMARY, *RELATED],
        "files": [
            "scripts/e2e_f7_t01_knowledge_shelf.py",
            "outputs/原系统融合重构执行/evidence/f7_t01_knowledge_shelf/batch_03_browser_mapping.json",
        ],
        "result": (
            "Prepared an isolated-database desktop E2E for failure recovery, shelf/course/discovery routes, "
            "protected advanced tools, learning-event immutability, and dual-viewport visual checks."
        ),
        "verification": [],
    },
    "recovery": {
        "atoms": [*PRIMARY, *RELATED],
        "files": [
            "scripts/read_context_recovery_task.py",
            "tests/test_context_recovery_packets.py",
            "scripts/record_f7_t01_batch.py",
            "outputs/原系统融合重构执行/evidence/f7_t01_knowledge_shelf/batch_04_recovery_mapping.json",
        ],
        "result": (
            "Repaired context recovery so a resumed task accepts only existing files already mapped by valid "
            "current-task ledger batches, while unmapped drift remains blocking."
        ),
        "verification": [],
    },
    "visual": {
        "atoms": [*PRIMARY, *RELATED],
        "files": [
            "frontend/src/views/Knowledge.vue",
            "tests/test_f7_t01_knowledge_frontend_contract.py",
            "scripts/e2e_f7_t01_knowledge_shelf.py",
            "outputs/原系统融合重构执行/evidence/f7_t01_knowledge_shelf/batch_05_document_preview_mapping.json",
        ],
        "result": (
            "Desktop E2E and screenshot review verified the complete shelf and course route states at both required "
            "sizes, including a light, readable basic course-document preview without entering F7-T02 scope."
        ),
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
            [f"F7-T01-{args.batch} at {stamp}: {', '.join(batch['files'])}", batch["result"]],
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
    record.update(
        {
            "status": "IMPLEMENTED_PENDING_FINAL_VERIFICATION",
            "updated_at": stamp,
            "atoms": batch["atoms"],
            "files": batch["files"],
            "result": batch["result"],
            "verification": [*batch["verification"], *args.verification],
        }
    )
    LEDGER.write_text(
        json.dumps(ledger, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Recorded F7-T01 {args.batch} batch for {len(batch['atoms'])} atoms")


if __name__ == "__main__":
    main()
