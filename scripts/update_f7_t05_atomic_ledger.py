from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / (
    "outputs/原系统融合重构执行/evidence/context_recovery/atomic_requirement_ledgers/"
    "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION/"
    "F7-T05_F14B31E18C5D66B11417E2B978E11B9DFEBA707BC4AAED6527FD881FA6CE62AA.json"
)

PRIMARY = {
    "G07-R07",
    "G12-R04",
    "G12-R05",
    "G12-R07",
    "G22-R11",
    "G27-R05",
    "G27-R07",
}
RELATED = {
    "G07-R01",
    "G07-R02",
    "G07-R03",
    "G07-R04",
    "G07-R05",
    "G07-R06",
    "G07-R08",
    "G07-R09",
    "G07-R10",
    "G12-R01",
    "G12-R02",
    "G12-R03",
    "G12-R06",
    "G12-R08",
    "G27-R01",
    "G27-R02",
    "G27-R03",
    "G27-R04",
    "G27-R06",
}


PLANNED_BATCHES = {
    "source-projection": {
        "atoms": sorted({"G07-R07", "G12-R08", "G22-R11", "G27-R04", "G27-R05"} | {atom for atom in RELATED if atom.startswith("G07-")}),
        "files": [
            "app/source_refs.py",
            "app/m1_api.py",
            "app/document_selection.py",
            "app/chat_api.py",
            "app/resource_bundles.py",
        ],
        "result": "One owner- and course-scoped source projection resolves canonical refs and selections to exact document locations, current availability and stable reverse routes without rewriting historical metadata.",
    },
    "chat-agent-audit": {
        "atoms": sorted(PRIMARY - {"G07-R07"} | {atom for atom in RELATED if atom.startswith("G12-") or atom.startswith("G27-")}),
        "files": ["app/agent_audit.py", "app/chat_api.py", "stream_api.py"],
        "result": "Canonical Chat persists a sanitized four-stage public audit in the existing stream checkpoint; stopped and failed runs remain honest and any historical fallback is explicitly labelled as prior output.",
    },
    "frontend-evidence": {
        "atoms": sorted(PRIMARY | RELATED),
        "files": [
            "frontend/src/components/SourceCitation.vue",
            "frontend/src/components/AgentTimeline.vue",
            "frontend/src/views/Chat.vue",
            "frontend/src/views/KnowledgeDocumentReader.vue",
            "frontend/src/views/HandoutWorkspace.vue",
            "frontend/src/stores/chat.js",
        ],
        "result": "Chat, document selection answers and handout footnotes use shared source navigation and a compact fact-driven Agent timeline while preserving the existing desktop reading and conversation layouts.",
    },
    "focused-verification": {
        "atoms": sorted(PRIMARY | RELATED),
        "files": [
            "tests/test_f7_t05_source_refs.py",
            "tests/test_f7_t05_agent_audit.py",
        ],
        "result": "Focused isolated-SQLite verification covers the canonical source projection and sanitized persisted Agent audit before frontend integration.",
    },
    "frontend-verification": {
        "atoms": sorted(PRIMARY | RELATED),
        "files": [
            "tests/test_f7_t05_frontend_contract.py",
            "scripts/e2e_f7_t05_evidence.py",
        ],
        "result": "Frontend contracts, production build and dual-desktop browser evidence verify honest Agent states and exact source reverse navigation.",
    },
}


def append_unique(values: list[str], additions: list[str]) -> list[str]:
    result = list(values)
    for value in additions:
        if value not in result:
            result.append(value)
    return result


def atomic_write_json(path: Path, payload: dict) -> None:
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def register_plans(payload: dict) -> None:
    batches = payload.setdefault("execution_batches", [])
    for batch_id, definition in PLANNED_BATCHES.items():
        record = next((item for item in batches if item.get("id") == batch_id), None)
        if record is None:
            record = {
                "id": batch_id,
                "status": "PLANNED_ATOM_MAPPED",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "verification": [],
            }
            batches.append(record)
        record.update(definition)
        record.setdefault("status", "PLANNED_ATOM_MAPPED")
        record.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
        record.setdefault("verification", [])


def apply_evidence(
    payload: dict,
    batch_id: str,
    field: str,
    evidence: str,
    verification: str,
    batch_status: str,
) -> None:
    definition = PLANNED_BATCHES[batch_id]
    entries = {entry["atomic_requirement_id"]: entry for entry in payload["entries"]}
    for atom_id in definition["atoms"]:
        realization = entries[atom_id]["realization"]
        if evidence:
            realization[field] = append_unique(realization.get(field) or [], [evidence])
        if realization.get("status") == "PENDING":
            realization["status"] = "IN_PROGRESS"
    record = next(item for item in payload["execution_batches"] if item.get("id") == batch_id)
    record["status"] = batch_status or (
        "VERIFIED" if field == "verification_evidence" else "IMPLEMENTED_PENDING_FINAL_VERIFICATION"
    )
    record["updated_at"] = datetime.now(timezone.utc).isoformat()
    if verification:
        record["verification"] = append_unique(record.get("verification") or [], [verification])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--register-plans", action="store_true")
    parser.add_argument("--batch", choices=sorted(PLANNED_BATCHES))
    parser.add_argument("--field", choices=("implementation_evidence", "verification_evidence"))
    parser.add_argument("--evidence", default="")
    parser.add_argument("--verification", default="")
    parser.add_argument(
        "--batch-status",
        choices=("PLANNED_ATOM_MAPPED", "IMPLEMENTED_PENDING_FINAL_VERIFICATION", "PARTIAL_VERIFIED", "VERIFIED"),
        default="",
    )
    args = parser.parse_args()
    if not args.register_plans and not (args.batch and args.field):
        parser.error("use --register-plans or provide --batch and --field")

    payload = json.loads(LEDGER.read_text(encoding="utf-8"))
    register_plans(payload)
    if args.batch and args.field:
        apply_evidence(
            payload,
            args.batch,
            args.field,
            args.evidence,
            args.verification,
            args.batch_status,
        )
    atomic_write_json(LEDGER, payload)
    print(json.dumps({"status": "UPDATED", "batch": args.batch or "plans"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
