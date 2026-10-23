#!/usr/bin/env python3
"""Record incremental F8-T02 implementation and verification evidence."""

from __future__ import annotations

import argparse
import json
import os
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
LEDGERS = list(LEDGER_DIR.glob("F8-T02_*.json"))
if len(LEDGERS) != 1:
    raise RuntimeError(f"Expected one F8-T02 ledger, found {len(LEDGERS)}")
LEDGER = LEDGERS[0]


BATCHES = {
    "schema-identity": {
        "atoms": [
            "G21-R03", "G21-R05", "G21-R09",
            "G22-R02", "G22-R04", "G22-R06", "G22-R07", "G22-R16",
            "G24-R01", "G24-R02", "G24-R03", "G24-R04", "G24-R05",
            "G24-R06", "G24-R07",
        ],
        "files": [
            "app/database.py",
            "app/migrations.py",
            "tests/test_f8_t02_wrong_questions.py",
        ],
        "result": (
            "Migration 20260816_074 establishes one wrong-question row per student and canonical "
            "question version. It binds only legacy rows with an exact canonical attempt, merges "
            "duplicates while preserving the earliest row, pin, user note, confirmed reason and "
            "legacy quiz reference, re-points governed video links, and removes only machine-owned "
            "formal-exam JSON from the user note field."
        ),
        "user_result": (
            "The same learner will see one durable wrong-question item for the same frozen question "
            "instead of a new duplicate after every failed attempt."
        ),
        "compatibility": (
            "Unmatched legacy rows remain readable, user-authored notes are preserved, existing video "
            "evidence keeps its foreign-key target, and no formal database is touched by this batch."
        ),
    },
    "aggregation-bridge": {
        "atoms": [
            "G21-R03", "G21-R05", "G21-R06", "G21-R09", "G21-R11",
            "G22-R02", "G22-R04", "G22-R06", "G22-R07", "G22-R16",
            "G24-R01", "G24-R02", "G24-R03", "G24-R04", "G24-R05",
            "G24-R06", "G24-R07",
        ],
        "files": [
            "app/learning_aggregation.py", "quiz_api.py",
            "tests/test_f8_t02_wrong_questions.py",
        ],
        "result": (
            "Canonical quiz and formal-exam projection reuses the learner/question-version identity, "
            "and the legacy quiz bridge binds its pre-existing row after the trusted canonical version "
            "is frozen without creating a second event or score source."
        ),
        "user_result": (
            "Repeated practice and formal-exam errors append to one question history and continue to "
            "drive the existing path, profile and review aggregation only through trusted submissions."
        ),
        "compatibility": (
            "The existing assessment attempt, learning event, exam gate and five-step aggregation remain "
            "authoritative; browsing and metadata actions remain non-mastery behavior."
        ),
    },
    "read-model-api": {
        "atoms": [
            "G21-R01", "G21-R02", "G21-R03", "G21-R04", "G21-R05", "G21-R06",
            "G21-R07", "G21-R08", "G21-R09", "G21-R10", "G21-R11", "G21-R12",
            "G21-R13", "G22-R01", "G22-R02", "G22-R03", "G22-R04", "G22-R05",
            "G22-R06", "G22-R07", "G22-R08", "G22-R09", "G22-R10", "G22-R11",
            "G22-R12", "G22-R13", "G22-R14", "G22-R15", "G22-R16", "G24-R01",
            "G24-R02", "G24-R03", "G24-R04", "G24-R05", "G24-R06", "G24-R07",
        ],
        "files": [
            "app/wrong_question_read_model.py",
            "quiz_api.py",
            "tests/test_f8_t02_wrong_questions.py",
        ],
        "result": (
            "The wrong-question read model exposes canonical question content, every owned attempt and "
            "source mode, formal report links, learner-confirmed misconception state, retest/review state "
            "and compact related-resource/deep-link actions without copying resource bodies."
        ),
        "user_result": (
            "A learner can understand what was wrong, where it came from, how prior attempts changed and "
            "which single next action to take, while missing or withdrawn sources remain honest."
        ),
        "compatibility": (
            "Legacy list fields, pin, note, delete, similar-question, flashcard, export and route contracts "
            "remain available; the API does not create learning evidence during reads."
        ),
    },
    "frontend": {
        "atoms": [
            "G21-R01", "G21-R02", "G21-R03", "G21-R04", "G21-R05", "G21-R06",
            "G21-R07", "G21-R08", "G21-R09", "G21-R10", "G21-R11", "G21-R12",
            "G21-R13", "G22-R01", "G22-R02", "G22-R03", "G22-R04", "G22-R05",
            "G22-R06", "G22-R07", "G22-R08", "G22-R09", "G22-R10", "G22-R11",
            "G22-R12", "G22-R13", "G22-R14", "G22-R15", "G22-R16", "G24-R01",
            "G24-R02", "G24-R03", "G24-R04", "G24-R05", "G24-R06", "G24-R07",
        ],
        "files": [
            "frontend/src/views/WrongQuestionBook.vue",
            "tests/test_f8_t02_wrong_questions_frontend_contract.py",
        ],
        "result": (
            "The protected 7.20 wrong-question capabilities are reorganized into a clear list/detail "
            "workspace with one redo/retest primary action and progressive sections for reason confirmation, "
            "attempt history, sources, related resources, notes, flashcards, similar questions and statistics. "
            "A submitted redo result now survives the canonical history refresh, and the loading surfaces use "
            "flat sans-serif F1 styling instead of gradients or a serif ordinary-page title."
        ),
        "user_result": (
            "The first screen explains the selected mistake and next action without a diagnostic dashboard, "
            "embedded video generator or competing card wall; every protected tool remains reachable."
        ),
        "compatibility": (
            "The workspace route, legacy redirect and all protected actions remain; full resources continue "
            "to open in their owning pages and no read-only interaction writes mastery evidence."
        ),
    },
    "browser-e2e": {
        "atoms": [
            "G21-R01", "G21-R02", "G21-R03", "G21-R04", "G21-R05", "G21-R06",
            "G21-R07", "G21-R08", "G21-R09", "G21-R10", "G21-R11", "G21-R12",
            "G21-R13", "G22-R01", "G22-R02", "G22-R03", "G22-R04", "G22-R05",
            "G22-R06", "G22-R07", "G22-R08", "G22-R09", "G22-R10", "G22-R11",
            "G22-R12", "G22-R13", "G22-R14", "G22-R15", "G22-R16", "G24-R01",
            "G24-R02", "G24-R03", "G24-R04", "G24-R05", "G24-R06", "G24-R07",
        ],
        "files": ["scripts/e2e_f8_t02_wrong_questions.py"],
        "result": (
            "An isolated deterministic browser journey verifies the practice/formal source filters, stable "
            "question-version merge, source round trip, learner-confirmed diagnosis, idempotent redo, refresh "
            "persistence, zero mastery writes during browsing and the two-desktop F1 visual contract."
        ),
        "user_result": (
            "A learner can recover a failed load, inspect two real mistake sources, confirm the reason, redo the "
            "question and still see the complete canonical history after refresh at both supported desktop sizes."
        ),
        "compatibility": (
            "The run uses a dedicated SQLite database, local deterministic providers, one local service and one "
            "headless Chromium instance; it preserves F2-F8 routes and performs no external model or network call."
        ),
    },
    "verification": {
        "atoms": [
            "G21-R01", "G21-R02", "G21-R03", "G21-R04", "G21-R05", "G21-R06",
            "G21-R07", "G21-R08", "G21-R09", "G21-R10", "G21-R11", "G21-R12",
            "G21-R13", "G22-R01", "G22-R02", "G22-R03", "G22-R04", "G22-R05",
            "G22-R06", "G22-R07", "G22-R08", "G22-R09", "G22-R10", "G22-R11",
            "G22-R12", "G22-R13", "G22-R14", "G22-R15", "G22-R16", "G24-R01",
            "G24-R02", "G24-R03", "G24-R04", "G24-R05", "G24-R06", "G24-R07",
        ],
        "files": [
            "tests/test_f8_t02_wrong_questions.py",
            "tests/test_f8_t02_wrong_questions_frontend_contract.py",
        ],
        "result": (
            "Focused migration, API, aggregation and frontend contracts plus the production build verify the "
            "implemented F8-T02 behavior before isolated two-desktop browser acceptance."
        ),
        "user_result": (
            "Both practice and formal-exam mistakes can be filtered, inspected, traced and redone while one "
            "canonical history survives refresh, failure and repeated submission."
        ),
        "compatibility": (
            "Protected F2-F8 behavior, zero-write browsing, owner isolation and formal-database boundaries are "
            "verified explicitly rather than inferred from a total test count."
        ),
    },
}


def append_unique(values: list[str], additions: list[str]) -> list[str]:
    return list(dict.fromkeys([*values, *additions]))


def atomic_write(path: Path, payload: dict) -> None:
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", choices=sorted(BATCHES))
    parser.add_argument("--verification", action="append", default=[])
    args = parser.parse_args()
    definition = BATCHES[args.batch]
    stamp = datetime.now(timezone.utc).isoformat()
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    entries = {entry["atomic_requirement_id"]: entry for entry in ledger["entries"]}
    missing = sorted(set(definition["atoms"]) - set(entries))
    if missing:
        raise RuntimeError(f"F8-T02 ledger atoms changed: {missing}")

    implementation = [
        f"F8-T02 {args.batch} batch at {stamp}: {', '.join(definition['files'])}",
        definition["result"],
    ]
    for atom_id in definition["atoms"]:
        entry = entries[atom_id]
        realization = entry["realization"]
        realization["status"] = "IMPLEMENTATION_IN_PROGRESS"
        realization["implementation_evidence"] = append_unique(
            realization.get("implementation_evidence", []), implementation
        )
        realization["verification_evidence"] = append_unique(
            realization.get("verification_evidence", []), args.verification
        )
        realization["user_visible_result"] = definition["user_result"]
        if entry["role"] == "related":
            realization["compatibility_or_defer_rationale"] = definition["compatibility"]

    records = ledger.setdefault("execution_batches", [])
    record = next((item for item in records if item.get("id") == args.batch), None)
    if record is None:
        record = {"id": args.batch}
        records.append(record)
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
