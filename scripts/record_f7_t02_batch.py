#!/usr/bin/env python3
"""Record incremental F7-T02 implementation and verification evidence."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER = next((
    ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery"
    / "atomic_requirement_ledgers" / "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION"
).glob("F7-T02_*.json"))

PRIMARY = ["G07-R01", "G07-R02", "G07-R03", "G07-R04", "G07-R05", "G07-R06", "G07-R08", "G07-R10"]
RELATED = ["G07-R07", "G07-R09"]
BATCHES = {
    "backend": {
        "atoms": ["G07-R02", "G07-R03", "G07-R05", "G07-R06", "G07-R08", "G07-R10", *RELATED],
        "files": [
            "app/database.py", "app/migrations.py", "app/multimodal.py",
            "app/document_selection.py", "app/main.py",
        ],
        "result": (
            "Implemented owner-scoped reading positions and versioned text/image SelectionContext, "
            "local OCR recovery, source-bound answers, existing-note provenance, and a bridge to the "
            "existing resource generation protocol without writing learning evidence."
        ),
    },
    "backend-tests": {
        "atoms": ["G07-R02", "G07-R03", "G07-R05", "G07-R06", "G07-R08", "G07-R10", *RELATED],
        "files": ["tests/test_f7_t02_document_reader.py"],
        "result": "Focused tests verify selection geometry, ownership, version recovery, OCR, notes, sources, and generation binding.",
    },
    "frontend": {
        "atoms": [*PRIMARY, *RELATED],
        "files": [
            "frontend/src/views/KnowledgeDocumentReader.vue",
            "frontend/src/components/SelectionToolbar.vue",
            "frontend/src/api/knowledge.js", "frontend/src/router/index.js",
            "frontend/src/components/KnowledgeCourseShelf.vue", "frontend/src/views/Knowledge.vue",
        ],
        "result": "Implemented the independent 20/58/22 desktop reader with stable navigation, selections, source actions and complete local states.",
    },
    "frontend-tests": {
        "atoms": [*PRIMARY, *RELATED],
        "files": ["tests/test_f7_t02_document_reader_frontend_contract.py"],
        "result": "Static contracts verify the dedicated route, three-column hierarchy, controls, F1 visual rules, and protected legacy capabilities.",
    },
    "browser": {
        "atoms": [*PRIMARY, *RELATED],
        "files": ["scripts/e2e_f7_t02_document_reader.py", "outputs/原系统融合重构执行/evidence/f7_t02_document_reader/browser"],
        "result": "Isolated desktop E2E verifies reading, text and image selections, OCR failure recovery, notes, generation, refresh restoration and both viewports.",
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
            [f"F7-T02-{args.batch} at {stamp}: {', '.join(batch['files'])}", batch["result"]],
        )
        realization["verification_evidence"] = append_unique(
            realization.get("verification_evidence", []), args.verification,
        )
    records = ledger.setdefault("execution_batches", [])
    record = next((item for item in records if item.get("id") == args.batch), None)
    if record is None:
        record = {"id": args.batch}
        records.append(record)
    record.update({
        "status": "IMPLEMENTED_PENDING_FINAL_VERIFICATION",
        "updated_at": stamp,
        "atoms": batch["atoms"],
        "files": batch["files"],
        "result": batch["result"],
        "verification": args.verification,
    })
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"Recorded F7-T02 {args.batch} batch for {len(batch['atoms'])} atoms")


if __name__ == "__main__":
    main()
