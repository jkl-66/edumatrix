#!/usr/bin/env python3
"""Record F6-T04's independent per-atom product understanding."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTEXT_ROOT = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery"
LEDGER_DIR = (
    CONTEXT_ROOT
    / "atomic_requirement_ledgers"
    / "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION"
)


def item(
    meaning: str,
    boundaries: list[str],
    scope: list[str],
    verification: list[str],
) -> dict[str, object]:
    return {
        "product_meaning": meaning,
        "behavior_boundaries": boundaries,
        "implementation_scope": scope,
        "verification_plan": verification,
    }


UNDERSTANDING = {
    "G16-R03": item(
        "A code review must be derived from one completed real run and separate concrete code findings, risks, and improvement directions.",
        [
            "Queued, running, stopped, missing, foreign, or stale run evidence cannot create a review.",
            "Completed success, runtime-error, or timeout attempts may be reviewed because each preserves real code, input, output, error, and terminal status.",
            "The baseline implementation remains local and deterministic; no external model data is transmitted in this task.",
        ],
        [
            "Add a strict f6.code-review.v1 protocol bound to runAttemptId, codeSha256, source resource version, stdin, stdout, stderr, checks, and exit status.",
            "Persist each review as an owned versioned artifact and expose findings, risks, improved code, evidence references, and review version through the code-sandbox API.",
        ],
        [
            "Test refusal without eligible evidence, evidence/hash binding, runtime-error analysis, and persistence recovery.",
            "Verify the review panel names the exact run and keeps run output visible if review generation fails.",
        ],
    ),
    "G16-R04": item(
        "The learner may provide an optional review focus that changes the review emphasis without changing the captured run evidence.",
        [
            "Focus text is bounded, sanitized, and stored with the review request; it is not stdin, executable code, or a hidden prompt surface.",
            "A focus cannot be submitted without an eligible runAttemptId and its exact code hash.",
        ],
        [
            "Accept focus in the review request and display it as a distinct field and result section in the right panel.",
            "Include focus in the idempotency fingerprint so a reused key cannot silently target different instructions.",
        ],
        [
            "Test focus persistence, idempotency conflict, length limits, and absence of focus from execution input.",
            "Use the desktop UI to request two differently focused reviews for real run evidence.",
        ],
    ),
    "G16-R05": item(
        "Applying review advice creates a new editable code-resource version, then the learner reruns it and compares the new attempt with the original attempt.",
        [
            "Applying advice never overwrites the original resource version, run snapshot, or review result.",
            "A stale resource lock or review bound to another resource is rejected; applying a review is idempotent.",
            "Applying advice does not itself run code, complete learning, or change mastery.",
        ],
        [
            "Add an apply action that copies the review's improved code into a new f6.code-sandbox.v1 version with review and run provenance metadata.",
            "Return both old and new version references so the UI can load the new draft, rerun through the existing executor, and compare attempts.",
        ],
        [
            "Test immutable source version, new version creation, lock conflicts, repeat apply, and successful rerun using the existing execution endpoint.",
            "Verify the UI loads the new draft, prompts for rerun, and keeps the original run and review available in history.",
        ],
    ),
    "G16-R09": item(
        "The right review panel must visibly separate issue locations, learner focus, potential risks, improved code, and concrete application advice.",
        [
            "Review failure or empty results cannot replace or hide stdout, stderr, plots, checks, or completion controls.",
            "No private reasoning, prompts, API keys, or raw Agent logs may appear in any review or audit section.",
        ],
        [
            "Create CodeReviewPanel.vue and integrate it into the existing 28-percent right column without changing the 22/50/28 workspace contract.",
            "Provide honest idle, unavailable, generating, failed, completed, applying, and applied states with one clear next action.",
        ],
        [
            "Test required section labels, sanitized public audit content, and stable layout at 1440x900 and 1366x768.",
            "Manually review an error attempt, inspect each section, apply advice, and rerun.",
        ],
    ),
    "G16-R01": item(
        "F6-T04 extends the existing editable, real-running code sandbox; it must not introduce another editor or executor.",
        ["Review actions cannot alter run scheduling, code validation, or execution semantics."],
        ["Reuse the formal /workspace/code/:resourceId surface and current code-sandbox API/router."],
        ["Run F6-T03 editing, save, run, and history regressions after review integration."],
    ),
    "G16-R02": item(
        "Review evidence must reference, not merge or replace, the real stdout, stderr, plots, and exit result already stored by F6-T03.",
        ["A review provider failure leaves all run evidence readable and unchanged."],
        ["Store hashes and public evidence references while the existing result tabs remain authoritative for full output."],
        ["Test stdout/stderr/plot projections before and after review requests and application."],
    ),
    "G16-R06": item(
        "The desktop workspace remains a stable 22/50/28 task-history, editor-input, and result-review layout.",
        ["The review panel stays inside the existing right column and does not create a fourth column or duplicate global navigation."],
        ["Replace only the F6-T03 review placeholder with the formal review component."],
        ["Measure all three columns and overflow at both required desktop viewports."],
    ),
    "G16-R07": item(
        "Run, stop, timeout, and process cleanup remain independent from review creation and application.",
        ["Review requests cannot stop, retry, reschedule, or relabel a run."],
        ["Use only terminal run snapshots and leave CodeSandboxRunCoordinator untouched unless a focused regression exposes a defect."],
        ["Repeat success, runtime error, timeout, and stop regressions after adding review endpoints."],
    ),
    "G16-R08": item(
        "Large output, error output, and plots retain their existing separated and bounded presentation while review cites their hashes and excerpts.",
        ["The review artifact cannot become a second unbounded copy of full stdout or stderr."],
        ["Use bounded evidence excerpts plus hashes in review results; full retained output stays in run tabs."],
        ["Test truncated-output reviews and confirm head-tail evidence and capture metadata remain available."],
    ),
    "G16-R10": item(
        "The no-Docker trusted-local judge mode continues to execute preset Python examples; review is an additional local evidence step, not a security claim.",
        ["The product must not describe trusted-local execution as production-grade hostile-code isolation."],
        ["Label local deterministic review and preserve the runtime-boundary message."],
        ["Run the existing no-Docker execution tests and inspect the boundary text in E2E."],
    ),
    "G16-R11": item(
        "Learning completion still requires an eligible real run and the server completion rule; receiving or applying a review alone is not mastery evidence.",
        ["Review generation and application emit no completion or mastery event."],
        ["Keep complete_run_learning authoritative and show review as optional improvement before the existing completion action."],
        ["Test that review-only and apply-only flows cannot complete learning, while valid code_tests_passed remains idempotent."],
    ),
    "G16-R12": item(
        "The code review belongs to the code-sandbox resource and does not merge the training brief or interactive model into the same artifact.",
        ["Review data uses a code-review schema and cannot masquerade as a training-task or interactive-model observation."],
        ["Keep existing linked-resource references unchanged and scope new UI to the sandbox review tab."],
        ["Run resource-type and route regressions for all three resource classes."],
    ),
    "G27-R01": item(
        "F6-T04 consumes the already selected learner/course/resource context and does not invent a second profile or claim new personalization evidence.",
        ["This task does not alter profile snapshots or infer mastery from review browsing."],
        ["Expose only the current focus and bound evidence references; preserve prior profile-driven resource generation."],
        ["Verify no profile or learning event is written by review creation or viewing."],
    ),
    "G27-R02": item(
        "The visible collaboration summary distinguishes evidence review, improvement candidate, validation, and final recommendation responsibilities.",
        ["The UI shows public role summaries, not an independent technical-demo page."],
        ["Build sanitized PublicAgentRun-compatible audit items inside the review result using existing M3 role contracts as role provenance."],
        ["Test role, inputRefs, candidateSummary, validation, revision, decisionSummary, and status fields."],
    ),
    "G27-R03": item(
        "The review explains meaningful disagreement between runtime evidence and static code concerns, plus the conservative revision chosen.",
        ["No fabricated debate is shown when no disagreement exists; the field states that no material conflict was found."],
        ["Derive public disagreement and revision summaries from deterministic checks and run evidence."],
        ["Test both a failed run with a concrete conflict and a clean run with an honest no-conflict summary."],
    ),
    "G27-R04": item(
        "Every review conclusion is traceable to the run, code hash, output/error hashes, checks, and source resource version.",
        ["Review prose cannot cite unavailable course sources or claim human approval."],
        ["Return an evidenceRefs object and show its compact identifiers in the review panel."],
        ["Assert exact evidence IDs and hashes in focused API tests and E2E."],
    ),
    "G27-R05": item(
        "Agent audit information is embedded in the real code-review flow and remains subordinate to the learner's review and rerun actions.",
        ["Do not add a separate Agent dashboard, stage workbench, or explanatory route."],
        ["Place a progressively disclosed audit section at the bottom of CodeReviewPanel.vue."],
        ["Verify the learner can complete review and rerun without opening the audit disclosure."],
    ),
    "G27-R06": item(
        "Only public responsibilities, input references, candidates, disagreements, validation, revisions, decisions, and statuses may be returned.",
        ["Prompts, API keys, secrets, private chain-of-thought, and raw logs are forbidden in persistence and responses."],
        ["Sanitize every public audit value and assert the final DTO with the existing agent_audit guard."],
        ["Inject forbidden keys and secret-like strings in tests and confirm they are absent from the API response."],
    ),
    "G27-R07": item(
        "External model unavailability must be explicit and must not block code execution; this task ships a deterministic local evidence reviewer as the reliable baseline.",
        ["The local reviewer is labeled honestly and no failed external call is presented as completed Agent work."],
        ["Return reviewMode and modelState, preserve run evidence on review failure, and keep execution endpoints model-independent."],
        ["Test deterministic review without model configuration and a forced review failure that leaves run retrieval and completion behavior intact."],
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F6-T04_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F6-T04 ledger, found {len(matches)}")
    ledger_path = matches[0]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    actual_ids = [entry["atomic_requirement_id"] for entry in ledger["entries"]]
    missing = [atom_id for atom_id in actual_ids if atom_id not in UNDERSTANDING]
    extra = [atom_id for atom_id in UNDERSTANDING if atom_id not in actual_ids]
    if missing or extra:
        raise RuntimeError(f"Atomic understanding mismatch: missing={missing}, extra={extra}")
    for entry in ledger["entries"]:
        entry["understanding"] = {
            "confirmed": True,
            **UNDERSTANDING[entry["atomic_requirement_id"]],
        }
    ledger_path.write_text(
        json.dumps(ledger, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    sys.path.insert(0, str(ROOT / "scripts"))
    from context_recovery_atomic_gate import (
        expected_entries,
        load_task_payload,
        validate_ledger_identity,
        validate_understanding,
    )

    active = json.loads((CONTEXT_ROOT / "active_manifest.json").read_text(encoding="utf-8"))
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F6-T04")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F6-T04",
        entries=expected,
    )
    failures.extend(validate_understanding(ledger, expected))
    if failures:
        raise RuntimeError(f"F6-T04 understanding gate failed: {failures}")
    print(f"Updated and validated understanding for {len(actual_ids)} F6-T04 atoms: {ledger_path}")


if __name__ == "__main__":
    main()
