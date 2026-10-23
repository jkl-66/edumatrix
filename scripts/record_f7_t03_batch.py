#!/usr/bin/env python3
"""Record incremental F7-T03 implementation evidence in its atomic ledger."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = (
    ROOT
    / "outputs"
    / "原系统融合重构执行"
    / "evidence"
    / "context_recovery"
    / "atomic_requirement_ledgers"
    / "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION"
)
LEDGERS = list(LEDGER_DIR.glob("F7-T03_*.json"))
if len(LEDGERS) != 1:
    raise RuntimeError(f"Expected one F7-T03 ledger, found {len(LEDGERS)}")
LEDGER = LEDGERS[0]

RELATED = [
    "G10-R01",
    "G10-R02",
    "G10-R03",
    "G10-R04",
    "G10-R05",
    "G10-R06",
    "G10-R07",
    "G11-R01",
    "G11-R02",
    "G11-R04",
    "G11-R08",
]
BATCHES = {
    "backend": {
        "atoms": ["G11-R03", "G11-R05", "G11-R06", "G11-R07", "G11-R09", *RELATED],
        "files": [
            "app/database.py",
            "app/migrations.py",
            "app/knowledge_graph.py",
            "app/source_admission.py",
            "knowledge_api.py",
        ],
        "result": (
            "Added an owner-scoped web candidate boundary and a canonical course graph projection. "
            "Candidates retain URL, license, usage, parsing impact, trust and review state without "
            "creating authoritative source refs; the graph reads only published course, chapter, "
            "knowledge-point and canonical source records and exposes source deep-link metadata."
        ),
    },
    "frontend_foundation": {
        "atoms": [
            "G11-R03",
            "G11-R05",
            "G11-R06",
            "G11-R07",
            "G11-R09",
            "G20-R06",
            *RELATED,
        ],
        "files": [
            "frontend/src/api/knowledge.js",
            "frontend/src/components/KnowledgeGraphExplorer.vue",
            "frontend/src/router/index.js",
            "frontend/src/views/Chat.vue",
            "frontend/src/views/KnowledgeGraphWorkspace.vue",
        ],
        "result": (
            "Added the authenticated graph and discovery API client surface, routed the course "
            "graph to a dedicated workspace, and extended the shared graph explorer with an "
            "optional relationship projection while preserving its default learner-profile "
            "behavior and removed the superseded manifold entry from Chat. The course workspace "
            "provides the required 75/25 graph and overview, "
            "canonical source deep links, filters, and a hierarchy fallback."
        ),
    },
    "discovery_ui": {
        "atoms": [
            "G11-R03",
            "G11-R07",
            "G11-R09",
            "G11-R01",
            "G11-R02",
            "G11-R04",
            "G11-R08",
        ],
        "files": ["frontend/src/views/KnowledgeDiscoveryWorkspace.vue"],
        "result": (
            "Added the source discovery workspace with query-preserving failure recovery, real-URL "
            "search results, owner-scoped candidate saving, format/license/review filters, complete "
            "source and parsing evidence, license-aware admission, rejection and withdrawal. The UI "
            "states explicitly that admitted items remain personal references and are ineligible for "
            "the canonical course graph, RAG, or resource generation."
        ),
    },
    "frontend_contract": {
        "atoms": [
            "G11-R03",
            "G11-R05",
            "G11-R06",
            "G11-R07",
            "G11-R09",
            "G20-R06",
            *RELATED,
        ],
        "files": ["tests/test_f7_t03_graph_and_admission_frontend_contract.py"],
        "result": (
            "Added static frontend contracts for the dedicated graph and discovery routes, 75/25 "
            "layout, same-data relationship projection, source deep links, query-preserving search "
            "failure, candidate metadata and admission boundaries, profile graph compatibility, "
            "and the absence of mastery writes or a Chat manifold entry."
        ),
    },
    "browser_e2e": {
        "atoms": [
            "G11-R03",
            "G11-R05",
            "G11-R06",
            "G11-R07",
            "G11-R09",
            "G20-R06",
            *RELATED,
        ],
        "files": [
            "scripts/e2e_f7_t03_graph_admission.py",
            "outputs/原系统融合重构执行/evidence/f7_t03_graph_admission/browser/report.json",
            "outputs/原系统融合重构执行/evidence/f7_t03_graph_admission/browser/manifest.json",
        ],
        "result": (
            "Added isolated-SQLite browser acceptance for both desktop viewports, covering graph "
            "filters, relationship projection, hierarchy fallback, source-reader deep links, real-URL "
            "candidate discovery, license blocking, admission, withdrawal, recoverable network failure, "
            "profile graph compatibility and read-only learning-state invariants."
        ),
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
            [
                f"F7-T03-{args.batch} at {stamp}: {', '.join(batch['files'])}",
                batch["result"],
            ],
        )
        realization["verification_evidence"] = append_unique(
            realization.get("verification_evidence", []), args.verification
        )
    records = ledger.setdefault("execution_batches", [])
    record = next((item for item in records if item.get("id") == args.batch), None)
    if record is None:
        record = {"id": args.batch}
        records.append(record)
    record.update(
        {
            "status": "IMPLEMENTED_PENDING_FINAL_VERIFICATION",
            "updated_at": stamp,
            "atoms": batch["atoms"],
            "files": batch["files"],
            "result": batch["result"],
            "verification": args.verification,
        }
    )
    LEDGER.write_text(
        json.dumps(ledger, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Recorded F7-T03 {args.batch} batch for {len(batch['atoms'])} atoms")


if __name__ == "__main__":
    main()
