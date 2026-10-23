#!/usr/bin/env python3
"""Record incremental F8-T05 implementation and verification evidence."""

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
MATCHES = list(LEDGER_DIR.glob("F8-T05_*.json"))
if len(MATCHES) != 1:
    raise RuntimeError(f"Expected one F8-T05 ledger, found {len(MATCHES)}")
LEDGER = MATCHES[0]


G22 = ["G22-R06", *[f"G22-R{index:02d}" for index in range(1, 17) if index != 6]]
G24 = [f"G24-R{index:02d}" for index in range(1, 8)]

BATCHES = {
    "backend-protocol": {
        "atoms": [
            "G22-R06", "G22-R02", "G22-R04", "G22-R07", "G22-R16",
            *G24,
        ],
        "files": [
            "app/learning_aggregation.py", "app/m5_learning.py",
            "app/interactive_lab.py", "app/m5_api.py",
        ],
        "result": (
            "The existing five-step recoverable aggregator now declares six affected views, expected and actual "
            "snapshot versions, deterministic next-day work and a completion-only consistency token. The interactive "
            "model joins quiz, code, Feynman, formal exam and review evidence, and the owner/course-scoped API exposes "
            "one latest feedback projection without creating a second state system."
        ),
        "visible": (
            "After frontend wiring, one trusted completion can be followed across home, profile, path, wrong questions, "
            "review and history with one version; partial failure remains recoverable from the completed checkpoint."
        ),
    },
    "backend-regression": {
        "atoms": G22 + G24,
        "files": ["tests/test_learning_aggregation.py", "tests/test_next_interactive_lab.py"],
        "result": (
            "Existing aggregation and interactive-model regressions prove ordered/out-of-order determinism, duplicate "
            "idempotency, five-step checkpoint recovery, no-mastery browsing, owner isolation and preserved interactive "
            "lab behavior after the protocol extension."
        ),
        "visible": (
            "Existing diagnostic, path, resource, exam, result-history and evidence boundaries remain protected while "
            "the new feedback protocol is added."
        ),
    },
    "focused-backend-tests": {
        "atoms": G22 + G24,
        "files": ["tests/test_f8_t05_learning_feedback.py"],
        "result": (
            "F8-T05 isolated tests cover all six trusted source types, six-view snapshot identity, next-day scheduling, "
            "latest-feedback ownership/course scope, service-session recovery, partial failure and duplicate replay."
        ),
        "visible": "Every feedback item is reproducible from one owned immutable event and can be safely resumed without duplicate learning credit.",
    },
    "frontend-feedback": {
        "atoms": [
            "G22-R06", "G22-R02", "G22-R04", "G22-R05", "G22-R07", "G22-R09",
            "G22-R11", "G22-R15", "G22-R16", "G24-R02", "G24-R04", "G24-R06", "G24-R07",
        ],
        "files": [
            "frontend/src/api/m5.js", "frontend/src/components/AggregationStatus.vue",
            "frontend/src/views/Dashboard.vue", "frontend/src/views/StudentAnalysis.vue",
            "frontend/src/views/LearningPathGraph.vue", "frontend/src/views/WrongQuestionBook.vue",
            "frontend/src/views/Review.vue", "frontend/src/views/History.vue",
            "frontend/src/views/FormalExamWorkspace.vue",
        ],
        "result": (
            "One compact shared component renders loading, quiet-empty, partial, failed, recovery and complete states, "
            "uses the same event/token on all six consumers, and exposes controlled internal actions without replacing "
            "the original result pages or histories."
        ),
        "visible": (
            "The learner sees a concise synchronization banner; details reveal six business destinations, a next-day "
            "task and one recovery action only when needed."
        ),
    },
    "frontend-contract": {
        "atoms": G22 + G24,
        "files": ["tests/test_f8_t05_learning_feedback_frontend_contract.py"],
        "result": (
            "Static frontend contracts verify all consumers use the shared component and API, no read action creates "
            "learning evidence, formal-exam locking remains present and frozen visual/wording rules are enforced."
        ),
        "visible": "Cross-page feedback remains readable and consistent without a duplicated report wall or mastery-by-browsing regression.",
    },
    "related-regression": {
        "atoms": G22 + G24,
        "files": [
            "tests/test_f4_path_contract.py", "tests/test_f4_exam_gate.py",
            "tests/test_f6_t01_quiz_resource.py", "tests/test_f6_t02_interactive_model_resource.py",
            "tests/test_f6_t03_code_sandbox_resource.py", "tests/test_f6_t04_code_review.py",
            "tests/test_f6_t05_feynman.py", "tests/test_f6_t06_formal_exam.py",
            "tests/test_f8_t01_review_schedule.py", "tests/test_f8_t01_review_frontend_contract.py",
            "tests/test_f8_t02_wrong_questions.py", "tests/test_f8_t02_wrong_questions_frontend_contract.py",
            "tests/test_f8_t03_notes.py", "tests/test_f8_t03_notes_frontend_contract.py",
            "tests/test_f8_t04_personal_activity.py", "tests/test_f8_t04_profile_frontend_contract.py",
            "tests/test_learning_aggregation.py", "tests/test_next_interactive_lab.py",
            "tests/test_f8_t05_learning_feedback.py",
            "tests/test_f8_t05_learning_feedback_frontend_contract.py",
        ],
        "result": (
            "F4 path and exam gates, all six F6 trusted evidence sources, all four F8 protected surfaces and the "
            "aggregation protocol remain compatible after the F8-T05 feedback integration."
        ),
        "visible": (
            "The learner keeps the established diagnostic, path, assessment, review, wrong-question, note and "
            "personal-history behavior while receiving one consistent cross-page feedback layer."
        ),
    },
    "impeccable-audit": {
        "atoms": G22 + G24,
        "files": [
            "frontend/src/components/AggregationStatus.vue", "frontend/src/views/Dashboard.vue",
            "frontend/src/views/StudentAnalysis.vue", "frontend/src/views/LearningPathGraph.vue",
            "frontend/src/views/WrongQuestionBook.vue", "frontend/src/views/Review.vue",
            "frontend/src/views/History.vue", "frontend/src/views/FormalExamWorkspace.vue",
        ],
        "result": (
            "Impeccable reported two warnings. Source review confirmed the wrong-question side border belongs only to "
            "real inline error/result messages, while Review.vue uses mutually exclusive red-on-red and slate-on-slate "
            "status classes; neither warning is an actionable design regression."
        ),
        "visible": (
            "Error and due-state emphasis remains restrained, semantic and readable without introducing decorative "
            "AI styling or changing the frozen light visual system."
        ),
    },
    "browser-e2e": {
        "atoms": G22 + G24,
        "files": ["scripts/e2e_f8_t05_learning_feedback.py"],
        "result": (
            "The isolated browser journey opens the same feedback on all six pages, follows controlled actions, recovers "
            "a failed event, verifies a formal-exam result and checks both frozen desktop sizes with zero read-side writes."
        ),
        "visible": "A complete learning result remains continuous, understandable and recoverable across every consumer page.",
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
        raise RuntimeError(f"F8-T05 ledger atoms changed: {missing}")
    stamp = datetime.now(timezone.utc).isoformat()
    implementation = [
        f"F8-T05 {args.batch} batch at {stamp}: {', '.join(definition['files'])}",
        definition["result"],
    ]
    for atom_id in definition["atoms"]:
        realization = entries[atom_id]["realization"]
        realization["status"] = "IMPLEMENTATION_IN_PROGRESS"
        realization["implementation_evidence"] = append_unique(
            list(realization.get("implementation_evidence") or []), implementation,
        )
        realization["verification_evidence"] = append_unique(
            list(realization.get("verification_evidence") or []), args.verification,
        )
        realization["user_visible_result"] = definition["visible"]
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
