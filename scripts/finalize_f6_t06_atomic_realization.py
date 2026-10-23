#!/usr/bin/env python3
"""Finalize F6-T06 per-atom implementation and verification evidence."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "原系统融合重构执行"
CONTEXT_ROOT = OUTPUT / "evidence" / "context_recovery"
LEDGER_DIR = CONTEXT_ROOT / "atomic_requirement_ledgers" / "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION"
SUMMARY = "outputs/原系统融合重构执行/evidence/f6_t06_formal_exam/evidence_summary.md"
FOCUSED = "tests/test_f6_t06_formal_exam.py (1 passed with registered migration and immutability triggers)"
REGRESSION = "F4-F6 combined regression selection (129 passed)"
BUILD = "frontend npm run build (6933 modules transformed; existing large-chunk warning only)"
COMPILE = "python -m py_compile F6 assessment modules and all six F6 E2E scripts"
E2E = (
    "scripts/e2e_f6_t06_formal_exam.py; report.json status passed; six screenshots at 1440x900 and "
    "1366x768; frozen generation, draft refresh, report, injected recoverable aggregation and replay"
)
F6_E2E = "F6-T01 through F6-T06 browser E2E reports all passed in the final phase run"
VISUAL = (
    "Impeccable detector returned [] for all F6 target UI files; browser scans found 0 overflow, overlap, "
    "clipping, text below 14px, gradients or unexpected console/network errors"
)
DATABASE = (
    "isolated f6_t06.sqlite3: integrity ok, 0 foreign-key violations, 1 exam, 4 final attempts, "
    "exactly 1 formal_exam_submitted event and processed aggregation"
)
MIGRATION = (
    "focused test applied registered migrations twice with an empty second pass and verified both response-draft "
    "and assessment-attempt immutability triggers"
)


def realized(
    *, role: str, implementation: list[str], verification: list[str], visible: str, rationale: str,
) -> dict[str, object]:
    return {
        "status": "IMPLEMENTED_AND_VERIFIED" if role == "primary" else "COORDINATION_VERIFIED",
        "implementation_evidence": implementation,
        "verification_evidence": verification,
        "user_visible_result": visible,
        "compatibility_or_defer_rationale": rationale,
    }


def primary(implementation: list[str], visible: str, *verification: str) -> dict[str, object]:
    return realized(
        role="primary",
        implementation=implementation,
        verification=list(verification) or [FOCUSED, E2E],
        visible=visible,
        rationale="F6-T06 owns the formal-exam workflow and reuses the existing gate, event and aggregation contracts.",
    )


def related(implementation: list[str], visible: str, rationale: str, *verification: str) -> dict[str, object]:
    return realized(
        role="related",
        implementation=implementation,
        verification=list(verification) or [REGRESSION, E2E],
        visible=visible,
        rationale=rationale,
    )


REALIZATION = {
    "G17-R01": primary(
        [
            "intelligent_exam_context exposes the authorized course, chapters, knowledge points, profile adaptation and frozen source counts.",
            "FormalExamWorkspace renders theme, course, chapter and knowledge-point controls in the left 35 percent and the live blueprint in the right 65 percent.",
        ],
        "After the existing gate unlocks, the learner scopes one exam by theme, course, chapters and knowledge points while seeing the resulting blueprint.",
        FOCUSED, E2E, VISUAL,
    ),
    "G17-R02": primary(
        [
            "IntelligentExamConfigInput validates duration, difficulty, source limit and per-type question counts on the server.",
            "FormalExamWorkspace uses labeled steppers for single choice, multiple choice, true/false, fill-blank and short-answer counts and prevents an empty paper.",
        ],
        "The learner changes each question-type count and immediately sees total questions, duration and score allocation before generation.",
        FOCUSED, E2E,
    ),
    "G17-R03": primary(
        [
            "build_intelligent_exam_input selects approved versions and freezes question, score, knowledge-point and source snapshots under one generation key.",
            "The generated preview lists every frozen item and source count but deliberately omits answer keys before submission.",
        ],
        "Generating the paper opens one stable frozen preview; refreshing or replaying the same request restores the same paper without revealing answers.",
        FOCUSED, E2E, DATABASE,
    ),
    "G17-R04": primary(
        [
            "save_formal_response_draft appends owner-scoped immutable revisions and binds idempotency keys to request hashes.",
            "FormalExamWorkspace provides question navigation, editable answers, per-question save, progress, timer and latest-successful-draft restoration.",
        ],
        "The learner completes the whole paper online, can revise a saved answer through a new revision, and resumes the latest saved state after refresh.",
        FOCUSED, E2E, MIGRATION,
    ),
    "G17-R05": primary(
        [
            "record_attempt freezes objective and precomputed formal subjective grades at initial insert, preserving the assessment-attempt immutability trigger.",
            "generate_report selects stored grading results and returns learner answer, correct answer, explanation, source and error reason for every item.",
        ],
        "After confirmation, the paper is scored immediately and the report shows the answer, correct answer, explanation, source and error reason question by question.",
        FOCUSED, E2E, MIGRATION, DATABASE,
    ),
    "G17-R06": primary(
        [
            "generate_report aggregates earned points and ratios per frozen knowledge point and emits wrong-question and retest actions only from stored results.",
            "FormalExamWorkspace presents knowledge-point coverage, wrong-question links, review-plan links and knowledge-point-specific retest actions.",
        ],
        "The report identifies weak knowledge points, archives wrong answers and offers direct review or targeted re-examination actions.",
        FOCUSED, E2E,
    ),
    "G17-R09": primary(
        [
            "build_intelligent_exam_input reads current course scope, selected knowledge points, profile adaptation, recent trusted events and approved frozen sources.",
            "The generation path never calls _call_quiz_model and contains no fixed competition-demo question bank or accuracy/recall product behavior.",
        ],
        "The generated paper reflects the selected course context and current learning evidence rather than a hard-coded sample paper.",
        FOCUSED, E2E, DATABASE,
    ),
    "G17-R10": primary(
        [
            "_submit_learner_generated_exam records one formal_exam_submitted event containing frozen item and knowledge-point results.",
            "process_path_event replays the same event through profile, path, next-day schedule, wrong-question and review-plan steps with recoverable checkpoints.",
        ],
        "One submission updates the learning profile, path, next-day plan, wrong-question book and review plan; a partial failure shows a truthful recovery action.",
        FOCUSED, REGRESSION, E2E, DATABASE,
    ),
    "G17-R07": related(
        [
            "AssessmentWorkspace retains only entry diagnosis and intelligent exam cards; FormalExamWorkspace contains no practice-quiz creation entry.",
            "QuizResourceWorkspace remains the dedicated learning-space route for in-learning practice.",
        ],
        "The assessment center still presents exactly entry diagnosis and intelligent examination, while practice stays in the resource space.",
        "F6-T06 adds the formal-exam surface without relocating the F6-T01 quiz resource.",
        REGRESSION, F6_E2E,
    ),
    "G17-R08": related(
        [
            "require_exam_gate rejects generation on the server until every required path task has trusted completion evidence.",
            "FormalExamWorkspace renders each missing task with resource type, completion condition and direct route instead of enabling the builder.",
        ],
        "Before unlock, the learner sees exactly which required tasks remain and can open each one directly; optional resources are not blockers.",
        "Gate ownership remains in F4-T05; F6-T06 consumes it without creating a second unlock rule.",
        FOCUSED, REGRESSION, E2E,
    ),
    "G22-R01": related(
        ["Formal-exam generation requires an existing course context and does not alter EntryDiagnostic routes, blueprints, sessions or initial reports."],
        "A new course still begins with the existing entry diagnosis before the later formal-exam workflow becomes relevant.",
        "Initialization assessment remains owned by F3 and is protected by regression rather than reimplemented here.",
        REGRESSION,
    ),
    "G22-R02": related(
        ["The exam context reads the existing profile snapshot and learning path; it does not create a competing recommendation or planning record."],
        "The paper displays the active course and uses the same profile/path context already visible elsewhere in the learning journey.",
        "Profile recommendation and path planning remain owned by F3/F4.",
        FOCUSED, REGRESSION,
    ),
    "G22-R03": related(
        ["Question selection consumes approved course questions, current profile adaptation and recent trusted evidence without starting a second resource-generation job."],
        "The formal paper is adapted to the same current mastery and recent events used by the resource package.",
        "F5 owns resource generation; F6-T06 only consumes its established context and sources.",
        FOCUSED, E2E,
    ),
    "G22-R04": related(
        ["Only trusted completion events processed by the shared aggregator can complete path tasks; configuring, previewing or browsing an exam writes no completion event."],
        "Opening and configuring the paper never falsely checks a path task; only evidence-bearing completion changes task state.",
        "Path-task completion remains owned by the shared F2/F4 aggregation protocol.",
        REGRESSION, DATABASE,
    ),
    "G22-R05": related(
        ["The server exam gate and locked UI require all current-day mandatory tasks while ignoring optional resources."],
        "After the last required task is complete, the same intelligent-exam entry changes from a missing-task list to the builder.",
        "F6-T06 verifies and consumes the F4 gate rather than duplicating its state machine.",
        FOCUSED, E2E,
    ),
    "G22-R06": related(
        ["The formal_exam_submitted event is aggregated into profile and path projections and a next-day schedule from the same frozen item results."],
        "The report confirms that profile, path and next-day learning arrangements have been synchronized from this submission.",
        "F6-T06 owns the submission payload; downstream pages continue to own their presentation.",
        FOCUSED, REGRESSION, E2E, DATABASE,
    ),
    "G22-R07": related(
        ["Wrong-question and review-plan projections are created from failed report items with source event IDs; the report links to existing review surfaces."],
        "The learner can leave the report for the wrong-question book or review plan without losing the exam report.",
        "F8 will refine protected review, notes and wrong-question layouts; this task only verifies compatible data and links.",
        REGRESSION, E2E, DATABASE,
    ),
    "G22-R08": related(
        ["The report does not embed a second chat implementation; existing intelligent-conversation routes and course-scoped query contracts remain unchanged."],
        "The formal report keeps assessment actions focused and leaves open-ended follow-up to the existing intelligent conversation entry.",
        "Dynamic conversation behavior belongs to F7 and is not claimed as implemented by F6-T06.",
        REGRESSION, BUILD,
    ),
    "G22-R09": related(
        ["FormalExamWorkspace stores the complete paper and report under exam detail routes instead of rendering generated exam content inside Chat."],
        "The learner returns to the formal-exam workspace and history to review complete papers and reports.",
        "This task preserves the approved rule that complete products live in dedicated learning spaces.",
        E2E, BUILD,
    ),
    "G22-R10": related(
        ["Exam generation keys, immutable versions, draft revisions and report versions preserve formal-exam history; no generic resource editor is added to the assessment surface."],
        "Historical papers remain selectable and each completed paper restores its own frozen report.",
        "Custom generation is provided only through formal exam configuration; F5 continues to own generic resource histories.",
        FOCUSED, E2E, DATABASE,
    ),
    "G22-R11": related(
        ["Formal local grading exposes method, frozen inputs, results and limitations but no prompt, API key, private reasoning or raw Agent log."],
        "The report honestly labels local deterministic grading and shows auditable evidence without exposing private internals.",
        "No Agent panel is invented where deterministic grading has no multi-Agent decision process.",
        FOCUSED, E2E,
    ),
    "G22-R12": related(
        ["FormalExamWorkspace contains no quiz editor, Monaco editor, process executor or network-search surface; their dedicated routes remain unchanged."],
        "The assessment page presents only formal exam configuration, answering and reporting.",
        "Quiz, code and search responsibilities stay separated under F6-T01/F6-T03 and F7.",
        REGRESSION, F6_E2E, BUILD,
    ),
    "G22-R13": related(
        ["The builder loads the team-prepared course and current profile context and contains no course-material upload prerequisite."],
        "The learner can generate a formal paper immediately from the existing course after completing required learning tasks.",
        "Natural-language onboarding and optional personal evidence remain upstream F3 responsibilities.",
        FOCUSED, E2E,
    ),
    "G22-R14": related(
        ["Generated quiz, model, sandbox and Feynman resources are consumed through their canonical artifact routes; the exam references the same course context without duplicating package generation."],
        "The formal exam follows the previously generated learning resources as the verification step of the same daily journey.",
        "Complete nine-resource package generation remains owned by F4/F5.",
        REGRESSION, F6_E2E,
    ),
    "G22-R15": related(
        ["exam_gate_status returns structured missing required tasks and FormalExamWorkspace renders direct links plus completion conditions while the builder stays absent."],
        "A locked learner knows what is missing, why the exam is locked and exactly where to continue.",
        "This is a compatibility verification of the existing F4 gate contract.",
        FOCUSED, E2E,
    ),
    "G22-R16": related(
        ["Immutable draft revisions, idempotent generation/submission keys and replayable aggregation checkpoints preserve every successful step across failures."],
        "Save or feedback synchronization failures keep the last confirmed answer and report and expose one bounded retry action.",
        "Recovery remains local to the failed operation and uses no parallel truth source.",
        FOCUSED, E2E, MIGRATION, DATABASE,
    ),
    "G24-R01": related(
        ["Only the final formal submission records formal_exam_submitted through record_learning_event; configuration, preview, navigation and draft saves record no learning event."],
        "The report reflects one meaningful formal-assessment event, while ordinary exam browsing has no mastery effect.",
        "F6-T06 contributes one event type to the unified F2 event protocol.",
        FOCUSED, DATABASE,
    ),
    "G24-R02": related(
        ["The submitted event carries knowledge-point and item results consumed by the shared profile, path and next-day schedule projection steps."],
        "The same submission result appears consistently in profile, path and the next learning arrangement.",
        "Projection ownership stays in the shared aggregation layer.",
        REGRESSION, E2E, DATABASE,
    ),
    "G24-R03": related(
        ["The formal event is mastery eligible only after server grading and stores normalized per-knowledge-point scores rather than treating all clicks equally."],
        "A completed formal paper has stronger evidence than browsing or saving a draft, and the report explains that distinction.",
        "Evidence weighting follows the existing aggregation policy rather than a new exam-only policy.",
        FOCUSED, REGRESSION,
    ),
    "G24-R04": related(
        ["GET context/detail/report, scope selection, preview, question navigation and source expansion are read-only; tests assert zero submission events before final submit."],
        "Looking at a source, changing configuration or refreshing the paper cannot increase mastery.",
        "This preserves the approved evidence boundary across the formal-exam UI.",
        FOCUSED, E2E, DATABASE,
    ),
    "G24-R05": related(
        ["DBLearningEventConsumption stores completed aggregation steps and process_path_event resumes the same event after an injected projection failure."],
        "Continuing feedback synchronization reaches the same final five-part result without changing the recorded score.",
        "Replay uses the canonical event and consumption checkpoint as the sole source of truth.",
        FOCUSED, E2E, DATABASE,
    ),
    "G24-R06": related(
        ["Draft/save state and sitting completion are separate from mastery eligibility; only the graded final event enters profile aggregation."],
        "Saved answers show progress but do not claim knowledge mastery before submission and grading.",
        "Task completion and mastery evidence remain separate fields under the shared contract.",
        FOCUSED, E2E,
    ),
    "G24-R07": related(
        ["Generation, draft saves and formal submission bind idempotency keys to content hashes; aggregation replays one source event and wrong questions use event/object uniqueness."],
        "Retrying a request or recovering feedback does not duplicate the paper, attempt, score, event or wrong-question entry.",
        "Idempotency and replay protection reuse existing database constraints and aggregation checkpoints.",
        FOCUSED, REGRESSION, E2E, MIGRATION, DATABASE,
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F6-T06_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F6-T06 ledger, found {len(matches)}")
    ledger_path = matches[0]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    actual_ids = [entry["atomic_requirement_id"] for entry in ledger["entries"]]
    missing = [atom_id for atom_id in actual_ids if atom_id not in REALIZATION]
    extra = [atom_id for atom_id in REALIZATION if atom_id not in actual_ids]
    if missing or extra:
        raise RuntimeError(f"Atomic realization mismatch: missing={missing}, extra={extra}")
    for entry in ledger["entries"]:
        entry["realization"] = REALIZATION[entry["atomic_requirement_id"]]

    primary_ids = [entry["atomic_requirement_id"] for entry in ledger["entries"] if entry["role"] == "primary"]
    related_ids = [entry["atomic_requirement_id"] for entry in ledger["entries"] if entry["role"] == "related"]
    batch = {
        "id": "F6-T06-B01",
        "status": "VERIFIED",
        "direct_atoms": primary_ids,
        "related_atoms": related_ids,
        "files": [
            "app/m5_assessment_core.py",
            "app/m5_exam_core.py",
            "app/m5_api.py",
            "app/learning_aggregation.py",
            "app/migrations.py",
            "frontend/src/api/m5.js",
            "frontend/src/views/FormalExamWorkspace.vue",
            "tests/test_f6_t06_formal_exam.py",
            "scripts/e2e_f6_t06_formal_exam.py",
            "scripts/finalize_f6_t06_atomic_realization.py",
            SUMMARY,
        ],
        "interfaces": [
            "GET /api/v1/m5/assessment/intelligent-exams/context",
            "POST /api/v1/m5/assessment/intelligent-exams",
            "GET /api/v1/m5/assessment/exams/{exam_id}",
            "POST /api/v1/m5/assessment/exam-sittings/{sitting_id}/start",
            "POST /api/v1/m5/assessment/exam-sittings/{sitting_id}/responses",
            "POST /api/v1/m5/assessment/exam-sittings/{sitting_id}/submit",
            "GET /api/v1/m5/assessment/exam-reports/{report_id}",
        ],
        "states": [
            "locked", "builder", "frozen_preview", "assigned", "in_progress", "submitted",
            "recoverable_feedback", "report_ready",
        ],
        "verification": [
            FOCUSED, REGRESSION, COMPILE, BUILD, E2E, F6_E2E, VISUAL, DATABASE, MIGRATION, "git diff --check",
        ],
        "protection_contracts": [
            "server-side required-task gate remains authoritative and optional resources do not block unlock",
            "question, score, source and answer drafts remain immutable and idempotent",
            "student preview hides answer keys and student UI hides teacher publishing/export/review tools",
            "formal submission creates one event and replay never duplicates scoring or downstream objects",
            "ordinary browsing, configuration and draft saves do not update mastery",
            "no external model, formal database, private reasoning or final-delivery package is used by verification",
        ],
        "evidence_summary": SUMMARY,
    }
    batches = ledger.setdefault("execution_batches", [])
    existing = next((item for item in batches if item.get("id") == batch["id"]), None)
    if existing is None:
        batches.append(batch)
    else:
        existing.update(batch)
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    sys.path.insert(0, str(ROOT / "scripts"))
    from context_recovery_atomic_gate import expected_entries, load_task_payload, validate_ledger_identity, validate_realization

    active = json.loads((CONTEXT_ROOT / "active_manifest.json").read_text(encoding="utf-8"))
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F6-T06")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F6-T06",
        entries=expected,
    )
    failures.extend(validate_realization(ledger, expected))
    if failures:
        raise RuntimeError(f"F6-T06 atomic realization gate failed: {failures}")
    print(f"Updated and validated {len(actual_ids)} F6-T06 atomic realizations: {ledger_path}")


if __name__ == "__main__":
    main()
