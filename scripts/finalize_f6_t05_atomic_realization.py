#!/usr/bin/env python3
"""Finalize F6-T05 per-atom implementation and verification evidence."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "原系统融合重构执行"
CONTEXT_ROOT = OUTPUT / "evidence" / "context_recovery"
LEDGER_DIR = CONTEXT_ROOT / "atomic_requirement_ledgers" / "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION"
SUMMARY = "outputs/原系统融合重构执行/evidence/f6_t05_feynman/evidence_summary.md"
FOCUSED = "tests/test_f6_t05_feynman.py (4 passed)"
REGRESSION = "F4-F6 related regression selection (48 passed)"
BUILD = "frontend npm run build (6933 modules transformed; existing large-chunk warning only)"
COMPILE = "python -m py_compile app/feynman.py app/feynman_api.py scripts/e2e_f6_t05_feynman.py"
E2E = (
    "scripts/e2e_f6_t05_feynman.py; report.json status passed; seven screenshots at "
    "1440x900 and 1366x768; full five-stage journey, injected failure, refresh, final apply and new attempt"
)
VISUAL = (
    "Impeccable detector returned []; browser checks found 0 overflow, overlap, clipping, text below 14px "
    "or decorative background images"
)
DATABASE = (
    "isolated f6_t05.sqlite3: integrity ok, 0 foreign-key violations, 2 session artifacts with 8/1 versions, "
    "and exactly 1 final feynman_submitted event"
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
        rationale="The implementation is bounded to the dedicated Feynman resource and preserves existing learning-space contracts.",
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
    "G18-R01": primary(
        [
            "frontend/src/router/index.js binds /workspace/feynman/:resourceId to FeynmanWorkspace instead of Chat.",
            "app/feynman.py stores owner-isolated sessions as DBArtifact/DBArtifactVersion records linked to one frozen source resource version.",
        ],
        "The learner opens a dedicated Feynman workspace with independent saved state, history and completion evidence.",
        FOCUSED, E2E, DATABASE,
    ),
    "G18-R02": primary(
        [
            "create_session derives the task from course, knowledge point, profile snapshot, recent trusted evidence and source references.",
            "FeynmanWorkspace displays the dynamic task above the first open-ended text area.",
        ],
        "The first task asks the learner to explain the selected knowledge point in their own words rather than answer a fixed demo question.",
        FOCUSED, E2E,
    ),
    "G18-R03": primary(
        [
            "FeynmanWorkspace keeps the five-stage progress panel visible and maps every server status to one current stage.",
            "Completed stages are available through accessible details summaries while the current stage remains expanded.",
        ],
        "The learner can always see the current step, completed steps and the next required action.",
        BUILD, E2E, VISUAL,
    ),
    "G18-R04": primary(
        [
            "submit_round1 stores the original text and SHA-256 before evaluate_round1 can create an evaluation.",
            "FeynmanEvaluationPanel shows total score, five rubric dimensions, evidence, strengths and gaps.",
        ],
        "After saving the first original retelling, the learner receives a replayable first evaluation without altering the original text.",
        FOCUSED, E2E,
    ),
    "G18-R05": primary(
        [
            "The server requires review1_ready -> question_pending -> question_answered before round two.",
            "_answer_question grounds its answer in the frozen source snapshot and labels the deterministic local method honestly.",
        ],
        "The learner must ask a real unresolved question and receives a course-source-grounded answer before continuing.",
        FOCUSED, E2E,
    ),
    "G18-R06": primary(
        [
            "submit_round2 rejects every state except question_answered with a stored QuestionAnswer.",
            "The second text area is rendered only after the stored question-answer stage succeeds.",
        ],
        "The second retelling cannot be entered or submitted before the required learner question has been answered.",
        FOCUSED, E2E,
    ),
    "G18-R07": primary(
        [
            "evaluate_round2 stores the second original text hash and evaluates it independently with f6.feynman-rubric.v1.",
            "Both evaluations retain distinct stable evaluation IDs and dimension evidence.",
        ],
        "The learner sees an independent second evaluation using the same frozen rubric as the first round.",
        FOCUSED, E2E, DATABASE,
    ),
    "G18-R08": primary(
        [
            "_comparison derives score and dimension deltas only from the two stored evaluations and supports improved, unchanged and lower conclusions.",
            "The comparison page shows scores, real deltas, remaining gaps and source-returning next actions.",
        ],
        "The final comparison reports the actual recorded change and does not fabricate improvement when the evidence is unchanged or lower.",
        FOCUSED, E2E,
    ),
    "G18-R09": primary(
        [
            "All three required inputs are normal editable textareas with complete submit actions.",
            "SpeechRecognition is detected in the browser only and appends editable text after an explicit learner click.",
        ],
        "Text alone completes the entire journey; supported browsers may optionally use speech to fill the same fields.",
        BUILD, E2E, VISUAL,
    ),
    "G18-R10": primary(
        [
            "The generated prompt uses the selected knowledge point title, profile adaptation and recent evidence count.",
            "No accuracy, recall, pointer or fixed example question exists in the production state machine.",
        ],
        "The task follows the current course topic and learner context rather than a hard-coded demonstration subject.",
        FOCUSED, E2E,
    ),
    "G18-R11": primary(
        [
            "Each RoundEvaluation stores rubric_version, evaluation_id, original text SHA-256, dimension scores and evidence.",
            "Session versions preserve source resource/version IDs and the complete action history.",
        ],
        "Every visible score can be traced to one original text, rubric version, evaluation identity and source session.",
        FOCUSED, DATABASE,
    ),
    "G18-R12": primary(
        [
            "Every successful server action creates a new immutable session version; failures leave the current version unchanged.",
            "FeynmanWorkspace persists unsent drafts in localStorage and clears only the field confirmed by a successful transition.",
        ],
        "Refresh and single-step failures preserve learner text and all previously completed stages; retry resumes only the failed action.",
        FOCUSED, E2E, DATABASE,
    ),
    "G18-R13": primary(
        [
            "Session creation and every action bind an idempotency key to a request hash and reject conflicting reuse.",
            "Only apply records feynman_submitted through record_learning_event and process_path_event.",
        ],
        "Repeated requests do not duplicate work, and the completed journey creates exactly one trusted learning event.",
        FOCUSED, REGRESSION, E2E, DATABASE,
    ),
    "G18-R14": primary(
        [
            "The backend contract accepts text only and contains no speech dependency or alternate completion path.",
            "The UI hides speech controls when the browser API is absent and preserves text when recognition fails.",
        ],
        "A browser without speech support still presents the same stable and complete five-stage learning workflow.",
        FOCUSED, E2E,
    ),
    "G22-R01": related(
        ["F6-T05 adds only the Feynman resource route and does not change onboarding or entry-diagnostic routes, services or data."],
        "New-course learners continue to enter through the existing diagnostic journey before using generated resources.",
        "Entry diagnosis remains owned by the closed F3/F4 contracts and is not duplicated here.",
        REGRESSION,
    ),
    "G22-R02": related(
        ["create_session reads the course and knowledge-point IDs frozen into the selected generated resource instead of selecting a parallel path target."],
        "The Feynman task opens for the same knowledge point selected by the existing profile-driven path.",
        "Path selection remains authoritative; the session only consumes its frozen resource context.",
        FOCUSED, REGRESSION,
    ),
    "G22-R03": related(
        ["The source Feynman artifact is generated by the existing resource-bundle job and carries profile, recent-event and source snapshots."],
        "The learner opens Feynman as one resource inside the complete generated bundle.",
        "F2/F5 resource generation remains the only bundle source of truth.",
        FOCUSED, REGRESSION, E2E,
    ),
    "G22-R04": related(
        ["No intermediate Feynman action writes a learning event; final apply uses the shared process_path_event aggregation path."],
        "Opening, typing, evaluating or asking a question does not check the path task; only final trusted completion can do so.",
        "Evidence-gated path completion remains unchanged.",
        FOCUSED, REGRESSION, DATABASE,
    ),
    "G22-R05": related(
        ["F6-T05 changes no exam-gate code and its final event enters the same path aggregation consumed by the existing gate."],
        "Intelligent exam generation remains locked until all required today tasks are complete.",
        "Exam unlocking remains exclusively owned by the F4 exam-gate contract.",
        REGRESSION,
    ),
    "G22-R06": related(
        ["The comparison is explicitly scoped to two retelling evaluations and writes no formal-exam report or assessment attempt."],
        "The learner sees understanding change for this resource only; later assessment feedback remains separate.",
        "Feynman comparison cannot impersonate a formal assessment result.",
        FOCUSED, REGRESSION,
    ),
    "G22-R07": related(
        ["The applied state links to the existing learning path, review center and resource center without creating replacement modules."],
        "After completion the learner can continue directly into path review, spaced review or other resources.",
        "Notes and wrong-question experiences retain their existing routes and ownership.",
        BUILD, E2E,
    ),
    "G22-R08": related(
        ["The mandatory learner question is stored inside the bounded Feynman session while /learn remains mapped to Chat."],
        "The learner asks the required retelling question in context without losing the separate general intelligent-chat entry.",
        "General conversation and Feynman progression remain distinct products.",
        FOCUSED, BUILD,
    ),
    "G22-R09": related(
        ["FeynmanWorkspace renders the full artifact and history on its dedicated learning-space route; no stage is emitted as a Chat message artifact."],
        "The complete retelling product remains in learning space rather than becoming a long conversation transcript.",
        "Chat reuse was removed while resource ownership was preserved.",
        FOCUSED, E2E,
    ),
    "G22-R10": related(
        ["list_sessions exposes prior attempts and session_payload exposes every immutable version; newAttempt creates a new session id."],
        "The learner can inspect old attempts and start again without overwriting previous texts or scores.",
        "History is append-only at both attempt and version levels.",
        FOCUSED, E2E, DATABASE,
    ),
    "G22-R11": related(
        ["The Feynman payload exposes bounded source, rubric, evaluation and decision records only; it stores no prompt secrets, API keys, raw logs or private reasoning."],
        "The learner can audit sources and scoring facts without seeing private system internals.",
        "No public Agent narrative was added where the workflow does not need one.",
        FOCUSED, E2E,
    ),
    "G22-R12": related(
        ["The new route adds no quiz editor, code editor or executor; existing quiz-resource and code-sandbox routes remain unchanged."],
        "Feynman presents only retelling controls and does not duplicate migrated quiz or code tools.",
        "Resource responsibilities remain separated by their established dedicated routes.",
        REGRESSION, BUILD,
    ),
    "G22-R13": related(
        ["The session consumes the pre-generated course resource and current profile snapshot; the page contains no upload control or course-material prerequisite."],
        "The learner begins immediately from the team-prepared course and existing profile context.",
        "Course ingestion and natural-language onboarding remain upstream responsibilities.",
        FOCUSED, E2E,
    ),
    "G22-R14": related(
        ["The API requires an owned canonical Feynman source artifact created by the existing resource-bundle protocol."],
        "The selected Feynman resource comes from the complete package generated for today's knowledge point.",
        "The session does not create a second independent resource-generation path.",
        FOCUSED, REGRESSION,
    ),
    "G22-R15": related(
        ["Final apply sends the trusted Feynman event through shared path aggregation; existing exam-gate tests continue to verify missing-task links and unlock behavior."],
        "When Feynman is required, its final completion can satisfy the existing path task while the gate still lists any other missing work.",
        "The gate UI and required-task policy remain owned by F4.",
        REGRESSION, DATABASE,
    ),
    "G22-R16": related(
        ["Server versions, optimistic expected_version checks, idempotency records and client draft keys preserve the last successful state across every action."],
        "Any save, evaluation, answer, comparison or aggregation failure resumes from the last confirmed stage.",
        "Recovery is action-local and does not introduce a parallel truth source.",
        FOCUSED, E2E, DATABASE,
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F6-T05_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F6-T05 ledger, found {len(matches)}")
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
        "id": "F6-T05-B01",
        "status": "VERIFIED",
        "direct_atoms": primary_ids,
        "related_atoms": related_ids,
        "files": [
            "app/feynman.py",
            "app/feynman_api.py",
            "app/main.py",
            "frontend/src/api/feynman.js",
            "frontend/src/api/index.js",
            "frontend/src/router/index.js",
            "frontend/src/components/FeynmanEvaluationPanel.vue",
            "frontend/src/views/FeynmanWorkspace.vue",
            "tests/test_f6_t05_feynman.py",
            "scripts/e2e_f6_t05_feynman.py",
            "scripts/finalize_f6_t05_atomic_realization.py",
            SUMMARY,
        ],
        "interfaces": [
            "GET /api/v1/feynman/sessions",
            "POST /api/v1/feynman/sessions",
            "GET /api/v1/feynman/sessions/{session_id}",
            "POST /api/v1/feynman/sessions/{session_id}/actions",
        ],
        "states": [
            "draft", "round1_submitted", "review1_ready", "question_pending", "question_answered",
            "round2_submitted", "comparison_ready", "applied",
        ],
        "verification": [FOCUSED, REGRESSION, COMPILE, BUILD, E2E, VISUAL, DATABASE, "git diff --check"],
        "protection_contracts": [
            "round one is stored before evaluation and both original texts remain immutable",
            "a stored real learner question and grounded answer are mandatory before round two",
            "comparison is derived only from stored evaluations and may not fabricate improvement",
            "only final apply creates one trusted event and uses shared aggregation",
            "text remains the complete path and browser speech remains optional",
            "legacy resource, route, exam gate, path, review, notes and wrong-question contracts remain compatible",
            "no external model, formal database or private reasoning is used by verification",
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
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F6-T05")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F6-T05",
        entries=expected,
    )
    failures.extend(validate_realization(ledger, expected))
    if failures:
        raise RuntimeError(f"F6-T05 atomic realization gate failed: {failures}")
    print(f"Updated and validated {len(actual_ids)} F6-T05 atomic realizations: {ledger_path}")


if __name__ == "__main__":
    main()
