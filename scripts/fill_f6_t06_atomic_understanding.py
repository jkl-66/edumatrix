#!/usr/bin/env python3
"""Record F6-T06's independent per-atom product understanding."""

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
    "G17-R01": item(
        "After the existing server-side gate unlocks, the learner configures one formal exam by theme, course, chapters, and knowledge-point scope.",
        [
            "The gate remains authoritative on the server; a client-side enabled button cannot bypass it.",
            "The student page does not expose teacher publishing, review-management, Word, or Excel controls from the reference image.",
        ],
        [
            "Extend the formal-exam draft contract with frozen theme, course, chapter, and knowledge-point selections.",
            "Render the unlocked configuration in the left 35 percent of the student workspace and keep the complete preview on the right.",
        ],
        [
            "Test locked and unlocked creation requests directly against the API.",
            "Verify the desktop UI exposes every required scope control and no teacher-only action.",
        ],
    ),
    "G17-R02": item(
        "The learner selects difficulty, duration, source limits, and explicit counts for each supported question type before generation.",
        [
            "Counts must be validated as non-negative integers with at least one total question.",
            "The server rejects unsupported types, impossible counts, and sources outside the selected approved course context.",
        ],
        [
            "Define one validated exam configuration schema used by both generation and replay.",
            "Provide compact steppers or numeric inputs for type counts and ordinary controls for difficulty, duration, and source limits.",
        ],
        [
            "Exercise valid and invalid count combinations, duration bounds, difficulty values, and source limits.",
            "Confirm the preview question count and type distribution exactly match the frozen configuration.",
        ],
    ),
    "G17-R03": item(
        "Generation freezes a complete, inspectable exam version before the learner starts answering it.",
        [
            "Previewing cannot mutate mastery, complete a path task, or silently regenerate questions.",
            "Starting a sitting preserves the exact previewed question order, wording, scoring, source references, and configuration.",
        ],
        [
            "Persist one immutable exam-version snapshot containing configuration, questions, coverage, and source provenance.",
            "Show the complete exam preview in the right 65 percent with answers and explanations available only before start as an explicit generation review, never during answering.",
        ],
        [
            "Reload the preview and compare its identity and full payload before and after starting a sitting.",
            "Assert no learning event is written by generate, preview, or refresh actions.",
        ],
    ),
    "G17-R04": item(
        "The learner completes the frozen exam online, saves each answer independently, and can resume the same sitting after refresh.",
        [
            "Saving one answer must not lock other questions or make the submitted answer immutable before final submission.",
            "Only the sitting owner may read or change answers, and submitted sittings are read-only.",
        ],
        [
            "Support editable per-question responses with optimistic version checks and idempotency keys.",
            "Restore saved answers, current question, remaining time, and sitting status from the server on reload.",
        ],
        [
            "Save, revise, refresh, and resume answers for every supported question type.",
            "Test ownership isolation, stale-version conflicts, repeated saves, and post-submission rejection.",
        ],
    ),
    "G17-R05": item(
        "One final submission grades the whole frozen exam and returns total score plus a complete per-question explanation.",
        [
            "The baseline grader is local and deterministic; F6-T06 does not send course, profile, answers, or sources to an external model.",
            "Repeated submission returns the existing result and cannot regrade, change the score, or write another event.",
        ],
        [
            "Grade supported objective and bounded short-answer questions from frozen answer keys and rubrics.",
            "Return each learner answer, correct answer, score, explanation, source, and error reason in the report payload.",
        ],
        [
            "Assert exact grading and explanations for correct, incorrect, partial, unanswered, and replayed submissions.",
            "Search the submission path for external model calls and verify the local baseline completes with network access absent.",
        ],
    ),
    "G17-R06": item(
        "The report summarizes wrong questions, knowledge-point coverage, weak areas, and direct actions for retest and source-grounded review.",
        [
            "Coverage is calculated from the frozen exam questions, not invented after submission.",
            "A retest creates a new exam or sitting linked to the prior report and never overwrites the original attempt.",
        ],
        [
            "Derive coverage and weak-point summaries from per-question results and source-linked knowledge-point metadata.",
            "Expose targeted retest, wrong-question, review, resource, and source actions without adding teacher review tools.",
        ],
        [
            "Verify coverage arithmetic and wrong-question membership against the frozen exam.",
            "Create a targeted retest and confirm both attempts remain independently traceable.",
        ],
    ),
    "G17-R09": item(
        "Every generated question is derived from the selected course scope, learner profile snapshot, mastery evidence, recent trusted events, and approved sources.",
        [
            "Production generation cannot use fixed accuracy, recall, pointer, or other demonstration questions as universal content.",
            "Missing optional learner evidence produces a neutral source-grounded exam rather than fabricated weaknesses.",
        ],
        [
            "Build a frozen generation context and deterministically select or construct questions from approved source-linked candidates.",
            "Store context identities and coverage rationale with the exam version without exposing private prompts or reasoning.",
        ],
        [
            "Generate exams for different courses, knowledge points, profiles, and recent events and assert meaningful contextual differences.",
            "Verify every question carries approved source and knowledge-point references and no fixed demo topic leaks into production.",
        ],
    ),
    "G17-R10": item(
        "A submitted formal exam produces one trusted event whose aggregation consistently updates profile, path, next-day schedule, wrong questions, and review plan.",
        [
            "The score is recorded once even if one downstream projection initially fails.",
            "Recovery resumes only missing projections from the same event and cannot duplicate scoring, task completion, wrong questions, or review items.",
        ],
        [
            "Record one idempotent formal_exam_submitted event after grading and process it through the shared learning aggregation pipeline.",
            "Persist per-projection progress and expose honest partial, retrying, recovered, and complete aggregation states in the report.",
        ],
        [
            "Count the event and all five projections before submission, after first submission, after replay, and after injected partial failure recovery.",
            "Verify the report, profile, path, next-day schedule, wrong-question data, and review data reference the same event and exam result.",
        ],
    ),
    "G17-R07": item(
        "The assessment center contains only entry diagnosis and formal intelligent exam; learning-time quizzes remain resources in learning space.",
        ["F6-T06 must not add an instant-practice tab, quiz editor, or duplicate quiz-resource route to assessment."],
        ["Keep formal-exam routes under the existing assessment workspace and leave QuizResourceWorkspace ownership unchanged."],
        ["Inspect router and assessment navigation, and run route-contract regressions for both assessment modules and quiz resources."],
    ),
    "G17-R08": item(
        "Before all required today tasks are complete, the formal-exam entry stays disabled and lists each missing task with a direct route.",
        ["The UI cannot infer unlock from local state, optional-resource completion, or a forged request."],
        ["Reuse the F4 exam-gate response and recheck it inside every create or generate API operation."],
        ["Test missing-task links, optional-task treatment, direct API bypass, unlock, and relock after context changes."],
    ),
    "G22-R01": item(
        "The established student journey still begins a new course with the entry diagnostic before formal-exam eligibility is possible.",
        ["F6-T06 cannot add a shortcut that creates a formal exam for an uninitialized course journey."],
        ["Consume the profile and course context produced by the existing diagnostic flow."],
        ["Run the diagnostic-to-path-to-gate compatibility journey relevant to exam creation."],
    ),
    "G22-R02": item(
        "The existing profile-driven path remains the source of today's course, chapters, and knowledge points offered for exam configuration.",
        ["Formal exam configuration cannot create or silently revise a parallel learning path."],
        ["Read selectable scope from the current path and approved course context; write path changes only through final aggregation."],
        ["Assert preview and answering leave path structure unchanged and final submission updates through shared projection logic."],
    ),
    "G22-R03": item(
        "The exam generation context uses the same current mastery and recent-event evidence that produced today's resources.",
        ["Generation cannot overwrite or regenerate the nine-resource bundle."],
        ["Freeze profile, mastery, event, and source identities in the exam version while keeping resource artifacts unchanged."],
        ["Compare sibling resource IDs and versions before and after exam generation and submission."],
    ),
    "G22-R04": item(
        "Existing resource completion events check their own path tasks before the formal-exam gate is evaluated.",
        ["Exam preview, answer save, and report browsing cannot complete unrelated resource tasks."],
        ["Consume gate state produced by existing path aggregation and emit only the formal-exam completion event on submit."],
        ["Count path-task changes across generate, save, submit, replay, and report viewing actions."],
    ),
    "G22-R05": item(
        "The learner enters formal intelligent exam only after all required today tasks are complete.",
        ["Completing all generated optional resources is not required unless they are explicitly marked required today."],
        ["Keep the F4 required-task calculation authoritative and expose a clear next action when it unlocks."],
        ["Test required versus optional tasks and verify exact transition from locked to unlocked."],
    ),
    "G22-R06": item(
        "Formal assessment completion updates the learner profile and learning plan from actual scored evidence.",
        ["No profile or plan change occurs from configuration, preview, answer saving, or report browsing."],
        ["Pass the trusted scored event to the shared profile, path, and next-day projections."],
        ["Compare projection versions and source event IDs before and after one successful submission and replay."],
    ),
    "G22-R07": item(
        "The report links the learner into the existing wrong-question, review, notes, source, and resource experiences for deeper learning.",
        ["F6-T06 does not redesign or replace the protected 7.20 pages."],
        ["Return canonical route destinations and source identities that later protected-page tasks can consume."],
        ["Verify every report deep link resolves without creating duplicate page ownership."],
    ),
    "G22-R08": item(
        "General follow-up questions remain in intelligent chat, while the formal report provides bounded source-grounded explanations and links.",
        ["The formal-exam page cannot become another full chat workspace or store its complete report as chat messages."],
        ["Expose a concise ask-in-chat action carrying exam, question, and source context identifiers."],
        ["Verify formal-exam actions create no chat history and the deep link uses the existing Chat route."],
    ),
    "G22-R09": item(
        "The complete frozen exam, sitting, and report remain canonical learning-space artifacts instead of being duplicated in conversation.",
        ["Chat may later display a compact link only; it cannot become a second source of exam truth."],
        ["Keep all formal-exam state in the existing exam and sitting records and dedicated routes."],
        ["Assert one canonical exam version and sitting back every preview, answer, report, and deep link."],
    ),
    "G22-R10": item(
        "Formal exams and retests preserve complete history, source provenance, configuration, answers, and reports.",
        ["A new attempt or retest cannot mutate an older frozen exam version or submitted sitting."],
        ["Expose learner-owned exam history and link derived retests to their source report."],
        ["Complete two attempts and verify both remain independently replayable and source-traceable."],
    ),
    "G22-R11": item(
        "Visible AI audit information explains inputs, source selection, validation, and final exam decisions without exposing private internals.",
        ["No prompt text, API key, private chain of thought, raw Agent log, or hidden scoring token enters API or UI payloads."],
        ["Store and display concise generation-context identities, validation status, and source coverage summaries only."],
        ["Inspect payloads and rendered content for forbidden private fields while confirming public provenance is present."],
    ),
    "G22-R12": item(
        "Quiz practice, code sandbox, and connected discovery retain their dedicated routes; the formal exam adds no duplicate tools.",
        ["The exam workspace contains no code runner, instant-practice editor, or web-search workbench."],
        ["Change only formal-exam ownership and preserve existing quiz, sandbox, chat, and knowledge routes."],
        ["Run route regressions and inspect the exam page for duplicated legacy controls."],
    ),
    "G22-R13": item(
        "The formal-exam journey consumes the team-prepared course and natural-language learner profile without requiring a course upload.",
        ["Missing approved course context is an honest blocked state, not an upload wizard or invented content path."],
        ["Read current approved course, profile snapshot, path, and source references only."],
        ["Open the assessment route as the seeded learner and confirm no course-material upload prerequisite appears."],
    ),
    "G22-R14": item(
        "The learner reaches formal assessment after generating and completing the required members of today's full resource package.",
        ["F6-T06 cannot generate sibling resources or move full exam output into chat."],
        ["Consume resource-task completion state and preserve existing bundle provenance."],
        ["Verify all resource artifacts remain unchanged while the gate accurately reflects required completion events."],
    ),
    "G22-R15": item(
        "A locked exam page names the exact incomplete tasks and provides direct actions to finish each one.",
        ["The page cannot show a generic disabled state or falsely satisfy a missing task."],
        ["Render the F4 gate's missing-task titles, resource types, statuses, and canonical routes."],
        ["Use seeded combinations of missing tasks and verify every link and unlock transition."],
    ),
    "G22-R16": item(
        "Every generation, answer save, grading, report, event, or aggregation failure resumes from the last successful persisted state.",
        [
            "Retry targets only the failed operation and reuses its request identity.",
            "Failure cannot discard saved answers, regenerate the exam, duplicate score, or claim complete feedback.",
        ],
        [
            "Use immutable exam versions, versioned sittings, idempotent actions, transactional grading/event creation, and resumable projection status.",
        ],
        ["Inject failures at generate, save, submit, report load, and each aggregation boundary; reload and resume each one."],
    ),
    "G24-R01": item(
        "The meaningful formal-exam completion becomes one canonical learning event with the frozen exam and sitting as evidence.",
        ["Configuration, preview, answer save, refresh, and report browsing are not mastery evidence events."],
        ["Create one formal_exam_submitted event only after the submitted result is durably stored."],
        ["Count event rows across every action and assert exactly one after repeated submission."],
    ),
    "G24-R02": item(
        "The shared event can update profile, mastery, path, and learning-plan projections from the same scored evidence.",
        ["F6-T06 cannot write ad hoc page-local mastery or plan values beside the shared aggregator."],
        ["Map the formal-exam result into the existing normalized event and projection contract."],
        ["Verify all downstream records reference the same source event and snapshot versions."],
    ),
    "G24-R03": item(
        "Formal-exam evidence uses its declared evidence type and strength when mastery is aggregated.",
        ["A completion flag alone cannot be treated as a perfect score or override stronger contradictory evidence."],
        ["Reuse the established evidence-weight policy and supply normalized per-knowledge-point exam scores."],
        ["Test different scores and evidence histories against the expected weighted aggregation behavior."],
    ),
    "G24-R04": item(
        "Browsing exam pages or opening explanations cannot increase mastery without a submitted scored result.",
        ["Client analytics, page views, button focus, preview, and downloads are excluded from evidence aggregation."],
        ["Keep all non-submit endpoints free of accepted learning-event writes."],
        ["Compare event and mastery records before and after every non-submit interaction."],
    ),
    "G24-R05": item(
        "Every projection conclusion can be rebuilt by replaying the immutable formal-exam event.",
        ["The report and projections cannot depend on unrecorded client state or mutable question definitions."],
        ["Include stable exam, sitting, result, knowledge-point score, and source identities in the event payload."],
        ["Rebuild projections in an isolated database and compare them with the original aggregate state."],
    ),
    "G24-R06": item(
        "Formal-exam completion and knowledge mastery remain separate facts: submission completes the assessment task, while scored evidence changes mastery by policy.",
        ["Completing an exam cannot automatically mark every covered knowledge point mastered."],
        ["Store task completion and per-knowledge-point evidence as separate fields consumed by separate projection rules."],
        ["Submit low, mixed, and high scoring exams and verify task completion is stable while mastery results differ."],
    ),
    "G24-R07": item(
        "Event creation and every downstream aggregation projection use idempotency identities so recovery never counts the exam twice.",
        ["A retry may resume incomplete projections but cannot create a new event or rerun completed projections as new evidence."],
        ["Bind submission, event, and projection checkpoints to the same sitting and result identities."],
        ["Replay submission and inject partial projection failures; assert one score, one event, and one effect per projection."],
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F6-T06_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F6-T06 ledger, found {len(matches)}")
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
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F6-T06")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F6-T06",
        entries=expected,
    )
    failures.extend(validate_understanding(ledger, expected))
    if failures:
        raise RuntimeError("F6-T06 understanding validation failed: " + ", ".join(failures))
    print(f"updated {ledger_path.relative_to(ROOT).as_posix()} ({len(expected)} atoms)")


if __name__ == "__main__":
    main()
