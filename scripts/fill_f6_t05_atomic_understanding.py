#!/usr/bin/env python3
"""Record F6-T05's independent per-atom product understanding."""

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
    "G18-R01": item(
        "Feynman retelling is a dedicated learning resource with its own route, saved state, history, and completion evidence.",
        [
            "It remains inside the existing learning-space resource system and does not become another chat workbench.",
            "Legacy Markdown Feynman resources remain readable and are not rewritten as completed sessions.",
        ],
        [
            "Replace the current Chat route binding with one dedicated /workspace/feynman/:resourceId workspace.",
            "Persist each learner session as owned versioned artifacts linked to the frozen source resource version.",
        ],
        [
            "Test route ownership, source-resource type checks, refresh recovery, and read-only legacy compatibility.",
            "Verify the resource opens from the resource center and history remains available.",
        ],
    ),
    "G18-R02": item(
        "The learner receives one open-ended retelling task that asks them to explain the current knowledge point in their own words.",
        [
            "The task is not a formal exam question and does not expose an answer key.",
            "The prompt must remain tied to the selected course, knowledge point, profile snapshot, evidence, and source references.",
        ],
        [
            "Build a task snapshot when the session is created and store its prompt and frozen context in version one.",
            "Show the task above the current-stage input with its completion expectations and source disclosure.",
        ],
        [
            "Create sessions for different knowledge points and assert their prompts and context snapshots differ.",
            "Check the UI contains one open-ended retelling action rather than quiz controls.",
        ],
    ),
    "G18-R03": item(
        "The learner can always see where they are across first retelling, review and question, second retelling, comparison, and application.",
        [
            "Progress is derived from persisted state, not optimistic client-only state.",
            "Completed stages may collapse, but their summaries and original records remain reachable.",
        ],
        [
            "Render a stable five-step progress strip and state-driven stage sections.",
            "Expand only the current action by default and keep completed sections as accessible summaries.",
        ],
        [
            "Assert every persisted state maps to the correct progress step and one primary action.",
            "Refresh at each stage and verify the same progress and completed summaries return.",
        ],
    ),
    "G18-R04": item(
        "After the first text is safely stored, a separately replayable evaluation shows its score, strengths, gaps, and omissions.",
        [
            "Evaluation cannot run before the first original text is persisted.",
            "A failed evaluation leaves the submitted text and round1_submitted state intact for retry.",
        ],
        [
            "Store the original text first, then create a rubric-versioned deterministic evaluation in a later artifact version.",
            "Display score, dimension evidence, strengths, gaps, and omitted explanation elements.",
        ],
        [
            "Test the draft-to-submitted-to-reviewed transitions, retry, idempotency, and immutable original text.",
            "Verify the first evaluation appears before the learner-question action.",
        ],
    ),
    "G18-R05": item(
        "The learner must enter a real unresolved question and receive a source-grounded answer before round two.",
        [
            "An empty, placeholder, or unchanged fixed question cannot satisfy the gate.",
            "The answer is produced by the local deterministic baseline from frozen context; no external model call is required.",
        ],
        [
            "Add a question_pending state, validate and store learner text, then store a concise answer with source references.",
            "Keep the learner question and answer visible in the completed-stage summary.",
        ],
        [
            "Test empty-question rejection, successful answer creation, ownership, source references, and replay.",
            "Verify round-two controls stay unavailable until question_answered.",
        ],
    ),
    "G18-R06": item(
        "Only after the stored learner question has a stored answer does the workspace ask for a second retelling.",
        [
            "The API, not just the disabled button, enforces this transition.",
            "The second prompt asks the learner to revise their own explanation, not copy a generated answer.",
        ],
        [
            "Permit submit_round2 only from question_answered and show the second text area in that state.",
            "Carry forward the original task, first evaluation, and question-answer context without overwriting them.",
        ],
        [
            "Call submit_round2 from every earlier state and assert rejection.",
            "Complete the real question flow and verify round two then becomes the only primary action.",
        ],
    ),
    "G18-R07": item(
        "The second original text receives an independent evaluation using the same frozen rubric version as round one.",
        [
            "The second score is calculated from the actual second text and cannot be copied from or forced above round one.",
            "A failed second evaluation preserves both original texts and the completed question-answer stage.",
        ],
        [
            "Persist round two before evaluation, then evaluate it with the same transparent deterministic rubric.",
            "Store score, dimension results, strengths, gaps, omissions, and evaluation identity.",
        ],
        [
            "Test identical, improved, and weaker second texts and assert their independent calculated results.",
            "Verify retry after round2_submitted does not duplicate or alter the original text.",
        ],
    ),
    "G18-R08": item(
        "The final view compares both recorded evaluations, shows real score and dimension deltas, remaining gaps, and concrete next learning actions.",
        [
            "No positive improvement is shown when the calculated result is equal or lower.",
            "The comparison is concise and structured rather than one untraceable generated paragraph.",
        ],
        [
            "Build comparison data directly from the two saved evaluations and retain their identifiers and rubric version.",
            "Show first score, second score, delta, improved dimensions, remaining gaps, and application destinations.",
        ],
        [
            "Assert comparison arithmetic and dimension deltas against persisted round records.",
            "Inspect the final desktop view for visible remaining gaps and one application action.",
        ],
    ),
    "G18-R09": item(
        "Text entry is the complete supported path; browser speech recognition is only an optional convenience for filling the same text fields.",
        [
            "Speech absence, denial, or failure never blocks, clears, or changes text submission.",
            "No microphone permission is requested unless the learner explicitly starts speech input.",
        ],
        [
            "Keep ordinary textareas and keyboard submission authoritative for every learner-written stage.",
            "Offer a conditional browser speech button that appends recognized text and reports failure locally.",
        ],
        [
            "Run the full flow with speech APIs absent and assert all stages complete.",
            "Inject a speech error and verify typed text remains unchanged.",
        ],
    ),
    "G18-R10": item(
        "The retelling task is generated from the selected course context rather than hard-coded accuracy, recall, pointers, or another demo topic.",
        [
            "Example terms may appear only inside explicitly labelled test fixtures or source-derived content.",
            "Missing optional profile details produce an honest neutral prompt, not invented weaknesses.",
        ],
        [
            "Resolve course, knowledge point, profile snapshot, recent accepted evidence, and source refs when creating the task snapshot.",
            "Use those facts to build the prompt and adaptation note without an external model.",
        ],
        [
            "Search production Feynman code for forbidden fixed demo questions and test multiple frozen contexts.",
            "Verify the UI exposes the actual course and knowledge point context.",
        ],
    ),
    "G18-R11": item(
        "Every score is traceable to its rubric version, source session, original text hash, dimension evidence, and evaluation identity.",
        [
            "The system never edits stored round texts after evaluation and never fabricates improvement metadata.",
            "Changing the rubric in future must not reinterpret old saved results.",
        ],
        [
            "Define a frozen f6.feynman-rubric.v1 result schema and persist both text and evaluation records in session versions.",
            "Return hashes and evaluation IDs in the public payload while keeping the explanation learner-readable.",
        ],
        [
            "Assert text hashes, rubric version, evaluation IDs, score bounds, and immutable old versions.",
            "Verify comparison references the exact two evaluation records.",
        ],
    ),
    "G18-R12": item(
        "Refresh and any failed answer, evaluation, save, or speech step preserve all successful earlier stages and learner input.",
        [
            "Retry replays only the failed action with the same idempotency key.",
            "The UI does not claim a later state until its server version exists.",
        ],
        [
            "Use one artifact version per successful transition and optimistic version checks for stale clients.",
            "Retain unsent textarea drafts in local storage and return direct retry actions for submitted-stage failures.",
        ],
        [
            "Inject action failures and version conflicts, reload, then continue from the last persisted state.",
            "Verify no earlier version, text, evaluation, or question-answer record is removed.",
        ],
    ),
    "G18-R13": item(
        "Repeated actions are idempotent, and only the final apply action records one accepted Feynman learning event and runs the shared aggregation pipeline.",
        [
            "Drafting, evaluating, asking, answering, and comparing do not change mastery or complete the path task.",
            "A repeated apply cannot duplicate score, profile, path, review, or history effects.",
        ],
        [
            "Bind each transition to an action idempotency key and request hash.",
            "On apply, create one trusted feynman_submitted event from the second evaluation and process it through existing aggregation.",
        ],
        [
            "Count events and aggregate projections before comparison, after first apply, and after replay.",
            "Assert the event references the source resource, session, evaluation, knowledge point, and normalized score.",
        ],
    ),
    "G18-R14": item(
        "Speech remains an optional enhancement duplicated nowhere in the backend contract; the local text workflow is independently complete and stable.",
        [
            "No server speech service, external model, or audio upload is required by F6-T05.",
            "Speech-derived text is visibly editable before it is submitted as ordinary learner text.",
        ],
        [
            "Keep speech handling entirely in the dedicated view and feed its result into the same text state.",
            "Label availability honestly and keep all API schemas text-only.",
        ],
        [
            "Build and run E2E in Chromium without granting microphone access.",
            "Verify no audio endpoint is called and the complete five-stage flow still succeeds.",
        ],
    ),
    "G22-R01": item(
        "The established journey still starts a new course with the already-closed entry diagnostic flow.",
        ["F6-T05 must not add a diagnostic substitute or bypass."],
        ["Consume only the course and profile context produced by earlier stages."],
        ["Run the existing diagnostic-to-resource compatibility tests relevant to Feynman context."],
    ),
    "G22-R02": item(
        "The existing profile-driven path remains the source of the selected knowledge point.",
        ["F6-T05 cannot create or replan a second learning path."],
        ["Read the frozen resource metadata and current path context; write only the final shared event."],
        ["Assert task creation leaves path nodes unchanged and final apply uses the shared aggregator."],
    ),
    "G22-R03": item(
        "The Feynman task remains one member of the already-generated nine-resource bundle and uses its frozen mastery, recent-event, and source context.",
        ["Opening the route cannot regenerate the whole bundle or overwrite successful sibling resources."],
        ["Bind the session to the existing Feynman artifact and its current source version."],
        ["Verify sibling resource IDs and generation status are unchanged throughout the session."],
    ),
    "G22-R04": item(
        "The path task is checked only after a trusted completion event, not by viewing or partially progressing through Feynman stages.",
        ["No earlier Feynman action may emit completion evidence."],
        ["Create the event only from comparison_ready -> applied and reuse current aggregation."],
        ["Count path completion before and after every stage and assert only apply changes it."],
    ),
    "G22-R05": item(
        "The existing exam gate remains responsible for unlocking intelligent exam generation after all required today tasks are complete.",
        ["F6-T05 cannot unlock, create, or submit an intelligent exam directly."],
        ["Provide a post-apply next link while leaving all gate calculations to F4/F6-T06."],
        ["Run the exam-gate regression and verify a Feynman event only satisfies its own bound task."],
    ),
    "G22-R06": item(
        "Final assessment feedback remains a later shared-aggregation responsibility and is not simulated by Feynman comparison.",
        ["Feynman score deltas cannot be labelled as formal exam results."],
        ["Use the generic learning event pipeline without adding exam-specific projections."],
        ["Verify event and UI labels distinguish Feynman evidence from formal assessment."],
    ),
    "G22-R07": item(
        "The learner can continue from Feynman results into the existing resource, review, notes, and later wrong-question experiences.",
        ["F6-T05 does not redesign the four protected 7.20 pages."],
        ["Return existing route destinations and let aggregation create any eligible review projection."],
        ["Check protected-page source hashes and verify post-apply route links resolve."],
    ),
    "G22-R08": item(
        "General dynamic questions still belong to intelligent chat; the required Feynman learner question stays inside the bounded retelling session.",
        ["The session answer cannot turn the page into the full Chat interface or emit arbitrary resources."],
        ["Answer only the stored Feynman question from frozen source context and offer intelligent chat as a separate optional deep link."],
        ["Verify no chat history or chat resource cards are created by Feynman actions."],
    ),
    "G22-R09": item(
        "The full Feynman artifact and its history remain in learning space rather than being rendered as a chat message product.",
        ["Only a compact link may later appear in chat; F6-T05 creates no duplicate content there."],
        ["Use the dedicated resource route and existing resource-center catalogue entry."],
        ["Verify the route and resource center reference one canonical artifact ID."],
    ),
    "G22-R10": item(
        "Feynman sessions preserve their complete version history and may start a new attempt without overwriting the prior attempt.",
        ["A restart creates a new session artifact; it does not reset or mutate the old one."],
        ["Expose session/version history and a new-attempt action after completion."],
        ["Complete two attempts and assert both remain owner-visible and independently traceable."],
    ),
    "G22-R11": item(
        "Any visible AI work summary remains public and auditable without exposing prompts, secrets, raw logs, or private reasoning.",
        ["F6-T05 needs no separate Agent dashboard and no chain-of-thought panel."],
        ["Label local deterministic task, evaluation, and answer modes with concise evidence references only."],
        ["Search API payloads and rendered text for forbidden private fields and secret-like content."],
    ),
    "G22-R12": item(
        "The old chat quiz and code surfaces remain migrated to their dedicated quiz-resource and code-sandbox routes; Feynman adds no duplicate controls.",
        ["The dedicated Feynman view contains no code runner, formal quiz, or web-search tabs."],
        ["Change only the Feynman route component and preserve existing quiz, sandbox, and knowledge routes."],
        ["Run route-contract regressions and inspect the dedicated view for duplicated legacy tools."],
    ),
    "G22-R13": item(
        "The established onboarding journey uses the team-prepared course and natural-language profile; the Feynman page never asks for course uploads.",
        ["Missing source context is an honest blocked state, not an upload wizard."],
        ["Read the existing source resource, profile snapshot, and source references only."],
        ["Open the route as the seeded learner and verify no upload prerequisite is presented."],
    ),
    "G22-R14": item(
        "The selected Feynman resource is consumed from the complete bundle already created from today's knowledge point.",
        ["F6-T05 must not create sibling resources or put full generated outputs in chat."],
        ["Keep source artifact and bundle provenance in the session context and catalogue route."],
        ["Verify bundle and sibling artifacts remain unchanged after all Feynman transitions."],
    ),
    "G22-R15": item(
        "If intelligent exam remains locked, its existing gate continues to show missing required tasks and direct links, including the Feynman resource when required.",
        ["The Feynman view cannot hide, override, or falsely satisfy other missing tasks."],
        ["Emit one completion event for the correct source resource and leave gate UI/logic untouched."],
        ["Run the gate before and after apply and verify only the matching task changes."],
    ),
    "G22-R16": item(
        "Every Feynman save, evaluation, answer, comparison, and aggregation failure resumes from the last successful server version.",
        ["Retries reuse the failed step's idempotency key and never replay successful stages.", "Failure cannot fabricate a later state or positive result."],
        ["Use versioned transitions, request hashes, clear errors, local unsent drafts, and transactional final application."],
        ["Inject failures at evaluation, answer, second evaluation, and aggregation; reload and resume each one."],
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F6-T05_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F6-T05 ledger, found {len(matches)}")
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
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F6-T05")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F6-T05",
        entries=expected,
    )
    failures.extend(validate_understanding(ledger, expected))
    if failures:
        raise RuntimeError("F6-T05 understanding validation failed: " + ", ".join(failures))
    print(f"updated {ledger_path.relative_to(ROOT).as_posix()} ({len(expected)} atoms)")


if __name__ == "__main__":
    main()
