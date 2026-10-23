#!/usr/bin/env python3
"""Record incremental F8-T03 implementation and verification evidence."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = (
    ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery"
    / "atomic_requirement_ledgers" / "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION"
)
MATCHES = list(LEDGER_DIR.glob("F8-T03_*.json"))
if len(MATCHES) != 1:
    raise RuntimeError(f"Expected one F8-T03 ledger, found {len(MATCHES)}")
LEDGER = MATCHES[0]


BATCHES = {
    "schema-versions": {
        "atoms": [
            "G07-R09", "G21-R03", "G21-R06", "G21-R09", "G21-R10", "G21-R12",
            "G24-R01", "G24-R02", "G24-R03", "G24-R04", "G24-R05", "G24-R06", "G24-R07",
        ],
        "files": ["app/database.py", "app/migrations.py", "app/note_workspace.py"],
        "result": (
            "Migration 20260816_075 adds optimistic note versions, immutable version snapshots, "
            "separate AI suggestions and a legacy baseline backfill. The note service binds document "
            "selections, existing learning resources and review plans without creating a second source, "
            "resource or event store, and records explicit writes as idempotent non-mastery events."
        ),
        "visible": (
            "After API and UI wiring, a learner's note body, source snapshot and prior versions can survive "
            "conflicts, source withdrawal and restoration while AI output remains a separate suggestion."
        ),
        "compatibility": (
            "Existing notes remain the current truth, existing learning_events remain the event truth, "
            "resource/source identities remain in their current tables, version history allows note deletion "
            "by cascade, and this batch does not touch the formal database."
        ),
    },
    "api-protocol": {
        "atoms": [
            "G07-R03", "G07-R04", "G07-R05", "G07-R06", "G07-R07", "G07-R08", "G07-R09",
            "G21-R02", "G21-R03", "G21-R04", "G21-R06", "G21-R08", "G21-R09", "G21-R10",
            "G21-R11", "G21-R12", "G21-R13", "G24-R01", "G24-R02", "G24-R03", "G24-R04",
            "G24-R05", "G24-R06", "G24-R07",
        ],
        "files": [
            "app/crud.py", "app/main.py", "app/document_selection.py", "frontend/src/api/notes.js",
        ],
        "result": (
            "The owner-scoped note API returns complete source projections, lock versions and separate AI "
            "suggestions; create/save/restore are idempotent, stale saves return an honest conflict, and "
            "document selection saves reuse the same version and event protocol."
        ),
        "visible": (
            "A learner can save or recover a sourced note without losing a local draft, inspect a precise "
            "source link, and choose whether to apply an AI suggestion as a new version."
        ),
        "compatibility": (
            "Legacy API shapes and direct CRUD callers remain accepted; reads, exports, source previews and "
            "filtering do not write learning evidence or alter mastery, path, review or exam-gate state."
        ),
    },
    "source-entry": {
        "atoms": [
            "G07-R01", "G07-R02", "G07-R03", "G07-R05", "G07-R08", "G07-R09", "G07-R10",
            "G21-R01", "G21-R02", "G21-R03", "G21-R04", "G21-R06", "G21-R07", "G21-R08",
            "G21-R09", "G21-R10", "G21-R11", "G21-R12", "G21-R13",
        ],
        "files": [
            "frontend/src/components/ResourceToolbar.vue", "frontend/src/views/HandoutWorkspace.vue",
            "frontend/src/views/CodeSandboxWorkspace.vue", "frontend/src/views/Review.vue",
            "frontend/src/views/KnowledgeDocumentReader.vue",
            "frontend/src/components/ReviewScheduleBoard.vue",
        ],
        "result": (
            "Document selections, personalized handouts, code-sandbox versions and review plans open one "
            "source-bound draft in the existing note workspace, while full resources stay in their owning routes."
        ),
        "visible": (
            "The learner can start a note at the point of study and later return from its source panel to the "
            "same document location, resource version or review task."
        ),
        "compatibility": (
            "F7's wide reader, F5/F6 resource ownership, F8 review schedule, two assessment types and the "
            "Today-required exam gate are linked rather than duplicated or redesigned."
        ),
    },
    "frontend-workspace": {
        "atoms": [
            "G07-R01", "G07-R02", "G07-R03", "G07-R04", "G07-R05", "G07-R06", "G07-R07",
            "G07-R08", "G07-R09", "G07-R10", "G21-R01", "G21-R02", "G21-R03", "G21-R04",
            "G21-R05", "G21-R06", "G21-R07", "G21-R08", "G21-R09", "G21-R10", "G21-R11",
            "G21-R12", "G21-R13", "G24-R01", "G24-R02", "G24-R03", "G24-R04", "G24-R05",
            "G24-R06", "G24-R07",
        ],
        "files": ["frontend/src/views/Notes.vue"],
        "result": (
            "The protected 7.20 note capabilities are reorganized into left navigation, a central editor/reader "
            "and a right source/history panel with one primary save action, progressive secondary tools, honest "
            "loading/empty/conflict/unavailable states and separate AI suggestion review."
        ),
        "visible": (
            "The learner can find, read, edit, version, source-check, export, review and assess a note without "
            "the previous blue-purple card wall or competing first-screen actions."
        ),
        "compatibility": (
            "Search, tags, concepts, edit/delete, Markdown/PDF export, AI formatting, diagrams, quiz, flashcards "
            "and review-plan actions remain reachable; ordinary browsing remains read-only."
        ),
    },
    "frontend-contract": {
        "atoms": [
            "G07-R01", "G07-R02", "G07-R03", "G07-R04", "G07-R05", "G07-R06", "G07-R07",
            "G07-R08", "G07-R09", "G07-R10", "G21-R01", "G21-R02", "G21-R03", "G21-R04",
            "G21-R05", "G21-R06", "G21-R07", "G21-R08", "G21-R09", "G21-R10", "G21-R11",
            "G21-R12", "G21-R13", "G24-R01", "G24-R02", "G24-R03", "G24-R04", "G24-R05",
            "G24-R06", "G24-R07",
        ],
        "files": [
            "frontend/src/views/Notes.vue",
            "tests/test_f8_t03_notes_frontend_contract.py",
            "scripts/update_f8_t03_atomic_ledger.py",
        ],
        "result": (
            "Static frontend contracts protect the three-column note ownership, four source types, exact "
            "selection/version fields, optimistic conflict recovery, separate AI suggestions, immutable "
            "history, all protected 7.20 actions and the absence of parallel mastery or assessment writes."
        ),
        "visible": (
            "The note workspace remains simple on first view while source, history, AI and protected study "
            "tools stay discoverable and regressions are rejected before browser acceptance."
        ),
        "compatibility": (
            "The contract preserves the legacy redirect, dedicated resource/source routes, two formal "
            "assessment types and zero-mastery browsing boundary without treating text presence alone as final evidence."
        ),
    },
    "browser-e2e": {
        "atoms": [
            "G07-R01", "G07-R02", "G07-R03", "G07-R04", "G07-R05", "G07-R06", "G07-R07",
            "G07-R08", "G07-R09", "G07-R10", "G21-R01", "G21-R02", "G21-R03", "G21-R04",
            "G21-R05", "G21-R06", "G21-R07", "G21-R08", "G21-R09", "G21-R10", "G21-R11",
            "G21-R12", "G21-R13", "G24-R01", "G24-R02", "G24-R03", "G24-R04", "G24-R05",
            "G24-R06", "G24-R07",
        ],
        "files": ["scripts/e2e_f8_t03_notes.py"],
        "result": (
            "An isolated deterministic browser journey exercises four source-bound notes, exact source return, "
            "local draft recovery, stale-version conflict, separate AI suggestion application, immutable restore, "
            "protected note tools and both frozen desktop sizes."
        ),
        "visible": (
            "A learner can move from study context into a note, save safely, inspect or recover history and return "
            "to the source without losing content or facing a dense card wall."
        ),
        "compatibility": (
            "The journey uses isolated SQLite and local deterministic providers, makes no external model or network "
            "call, and verifies ordinary browsing does not alter profile, mastery, path, review or exam-gate facts."
        ),
    },
    "backend-verification": {
        "atoms": [
            "G07-R01", "G07-R02", "G07-R03", "G07-R04", "G07-R05", "G07-R06", "G07-R07",
            "G07-R08", "G07-R09", "G07-R10", "G21-R01", "G21-R02", "G21-R03", "G21-R04",
            "G21-R05", "G21-R06", "G21-R07", "G21-R08", "G21-R09", "G21-R10", "G21-R11",
            "G21-R12", "G21-R13", "G24-R01", "G24-R02", "G24-R03", "G24-R04", "G24-R05",
            "G24-R06", "G24-R07",
        ],
        "files": [
            "tests/test_f8_t03_notes.py",
            "tests/test_f7_t02_document_reader.py",
            "scripts/finalize_f8_t03_atomic_realization.py",
        ],
        "result": (
            "The isolated backend suite verifies migration, owner scope, source withdrawal, optimistic "
            "conflicts, immutable restore, AI suggestion separation, idempotency and zero-write reads."
        ),
        "visible": "The source-bound note protocol preserves user content and history across conflicts and unavailable sources.",
        "compatibility": "Formal data, external models, Git and delivery packages remain outside this acceptance run.",
    },
}


def append_unique(values: list[str], additions: list[str]) -> list[str]:
    return list(dict.fromkeys([*values, *additions]))


def atomic_write(path: Path, payload: dict) -> None:
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", choices=sorted(BATCHES))
    parser.add_argument("--verification", action="append", default=[])
    args = parser.parse_args()
    definition = BATCHES[args.batch]
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    entries = {entry["atomic_requirement_id"]: entry for entry in ledger["entries"]}
    missing = sorted(set(definition["atoms"]) - set(entries))
    if missing:
        raise RuntimeError(f"F8-T03 ledger atoms changed: {missing}")
    stamp = datetime.now(timezone.utc).isoformat()
    implementation = [
        f"F8-T03 {args.batch} batch at {stamp}: {', '.join(definition['files'])}",
        definition["result"],
    ]
    for atom_id in definition["atoms"]:
        entry = entries[atom_id]
        realization = entry["realization"]
        realization["status"] = "IMPLEMENTATION_IN_PROGRESS"
        realization["implementation_evidence"] = append_unique(
            list(realization.get("implementation_evidence") or []), implementation,
        )
        realization["verification_evidence"] = append_unique(
            list(realization.get("verification_evidence") or []), args.verification,
        )
        realization["user_visible_result"] = definition["visible"]
        if entry["role"] == "related":
            realization["compatibility_or_defer_rationale"] = definition["compatibility"]
    batches = ledger.setdefault("execution_batches", [])
    record = next((item for item in batches if item.get("id") == args.batch), None)
    if record is None:
        record = {"id": args.batch}
        batches.append(record)
    record.update({
        "status": "IMPLEMENTED_PENDING_FINAL_VERIFICATION",
        "updated_at": stamp,
        "atoms": definition["atoms"],
        "files": definition["files"],
        "result": definition["result"],
        "verification": args.verification,
    })
    atomic_write(LEDGER, ledger)
    print(json.dumps({"status": "BATCH_RECORDED", "batch": args.batch}, ensure_ascii=False))


if __name__ == "__main__":
    main()
