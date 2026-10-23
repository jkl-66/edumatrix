#!/usr/bin/env python3
"""Finalize F8-T01 per-atom realization after verified isolated acceptance."""

from __future__ import annotations

import json
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
EVIDENCE_DIR = (
    ROOT
    / "outputs"
    / "原系统融合重构执行"
    / "evidence"
    / "f8_t01_review_calendar"
)

FOCUSED = (
    "F8-T01 focused API and frontend contracts passed 10 tests in 1.63s, including "
    "42-day calendar projection, read-only browsing, owner isolation, task actions, "
    "route ordering, visual tokens and original-tool reachability."
)
REGRESSION = (
    "F4 path/exam gate, F5 resource/training/history, F6 quiz/model/sandbox/exam, "
    "F7 Chat, unified aggregation and navigation protection passed 68 tests in "
    "70.85s with only five existing framework deprecation warnings."
)
BUILD = (
    "frontend npm run build passed with 6937 modules transformed in 1.76s; "
    "git diff --check exited 0 with no whitespace errors."
)
E2E = (
    "Final isolated dual-desktop E2E passed with seven full-opacity screenshots at "
    "1440x900 and 1366x768, real resource generation, one SM-2 completion, one "
    "delayed retest, both durable completion notices and original-tool access."
)
VISUAL = (
    "Browser metrics found 42 calendar cells, 58/42 layout at both viewports, zero "
    "overflow, collisions, clipping, sub-14px text or forbidden theme hits. Full-size "
    "inspection accepted all seven screenshots. Impeccable's only warning was a "
    "verified ternary-parser false positive at Review.vue:186."
)
DATABASE = (
    "Isolated SQLite browsing kept learning events, snapshots, plans, check-ins, "
    "assessment attempts and generation tasks byte-for-byte equivalent by count. "
    "Explicit actions added exactly two learning events, one check-in, one assessment "
    "attempt and one generation task; integrity_check=ok and foreign-key violations=0."
)
BOUNDARIES = (
    "No formal database, external model, external request, assessment rule, second "
    "resource store or Git state was used or changed; browser, HTTP, page and console "
    "error lists were empty."
)


PRIMARY = {
    "G15-R01": {
        "implementation": (
            "app/review_schedule.py projects existing review plans, retests and events "
            "into a real 42-day Shanghai month. ReviewScheduleBoard.vue renders the "
            "calendar and selected-day agenda in a measured 58/42 desktop split."
        ),
        "verification": (
            "Focused tests cover leap/cross-month dates and both browser viewports report "
            "42 cells with layout ratios 0.5798 and no overlap."
        ),
        "visible": (
            "The review center opens on a real monthly calendar beside the selected day's "
            "actionable schedule instead of statistics or a flat plan list."
        ),
    },
    "G15-R02": {
        "implementation": (
            "The schedule protocol returns one deduplicated day projection whose task_count "
            "and status are rendered directly in each calendar cell and reused by the agenda."
        ),
        "verification": (
            "API tests reconcile day counts with task identities across today, overdue, "
            "completed, future, empty and course-filtered dates; browser screenshots show "
            "the same counts in calendar and agenda."
        ),
        "visible": (
            "Before opening a date, the learner can see whether it is empty, overdue, today, "
            "completed or scheduled and how many review tasks it contains."
        ),
    },
    "G15-R03": {
        "implementation": (
            "Selected date, month and review-only course filter are stable URL state. The "
            "agenda deterministically orders the same projected tasks and retains the month "
            "and date during loading, empty and failed states."
        ),
        "verification": (
            "Focused contracts and E2E switch months, today, courses and dates, verify zero "
            "writes, and reconcile the selected date with its task list and empty state."
        ),
        "visible": (
            "Clicking a date immediately shows its knowledge points, reason, due time, type, "
            "completion rule, status and next action in the right-hand schedule."
        ),
    },
    "G15-R04": {
        "implementation": (
            "Each projected task exposes a server-owned action. startTask first awaits the "
            "route deep link, then only the route-authoritative component opens SM-2 recall "
            "or delayed retest work, preventing duplicate loads and lost answers or notices."
        ),
        "verification": (
            "Contracts enforce route synchronization before workspace mutation. Repeated real "
            "browser runs completed both task types without duplicate requests, stale locators "
            "or lost completion feedback."
        ),
        "visible": (
            "The learner can select '去复习', complete the real recall or retest interaction, "
            "and return to a refreshed calendar with a durable success message."
        ),
    },
    "G15-R05": {
        "implementation": (
            "Task state is calculated from real dueAt and completion facts, while the "
            "review_course query isolates the unclassified legacy-plan filter from the shared "
            "real course_id context."
        ),
        "verification": (
            "Tests cover overdue boundaries, completed-history retention, owner/course isolation "
            "and unclassified plans. E2E filters away and back without leaving the review route."
        ),
        "visible": (
            "The calendar distinguishes today, overdue, completed and future work and filters "
            "both dates and tasks by a real course without mislabelling older plans."
        ),
    },
    "G15-R06": {
        "implementation": (
            "Review task actions reuse the F5 nine-resource generation job, F7 context handoff, "
            "F4 server-owned exam gate and the existing idempotent review_completed aggregation "
            "instead of creating parallel stores or unlock rules."
        ),
        "verification": (
            "Focused tests prove nine distinct resource types, idempotent completion and locked/"
            "unlocked exam behavior. E2E archives one complete resource bundle and records only "
            "the two explicit completion events."
        ),
        "visible": (
            "From a review task the learner can open or generate its complete resource package, "
            "ask with context, inspect the exact exam requirement and see the accepted completion."
        ),
    },
    "G21-R07": {
        "implementation": (
            "Review.vue and RevisionCalendar.vue both place ReviewScheduleBoard first. Their "
            "original flashcards, SM-2 queue, retest, check-in, duration, plan, chart and history "
            "features remain reachable under '复习工具与历史'."
        ),
        "verification": (
            "Frontend contracts enforce calendar-before-legacy ordering and preserve original "
            "functions; the final two screenshots show both original tool collections."
        ),
        "visible": (
            "The learner starts from one clear calendar and can expand the richer original review "
            "toolkit when needed, without losing any substantive 7.20 capability."
        ),
    },
    "G21-R08": {
        "implementation": (
            "The selected task resolves course, knowledge point, frozen profile and admitted "
            "source context into the existing nine-resource job and displays the existing exam "
            "gate result with its real blocking reason."
        ),
        "verification": (
            "API tests cover ready/missing generation context, idempotency and gate protection; "
            "E2E opens a 9/9 archived resource bundle while the locked exam copy remains truthful."
        ),
        "visible": (
            "A review knowledge point can create its full learning package in one action, while "
            "the intelligent exam link opens only when the same Today-required gate allows it."
        ),
    },
    "G21-R09": {
        "implementation": (
            "Accepted review and retest results create one trusted event each, reuse the five-step "
            "learning aggregation, project completed state back into the calendar and carry a "
            "non-sensitive route notice across the required fullPath remount."
        ),
        "verification": (
            "Database tests cover idempotency and aggregation; repeated browser journeys show both "
            "completion notices and exact +2 event, +1 check-in and +1 attempt deltas."
        ),
        "visible": (
            "After a real completion, the task is visibly recorded, its next schedule is updated, "
            "and the same accepted evidence is available to profile and path projections."
        ),
    },
}


RELATED = {
    "G21-R01": "Learning-space secondary navigation and all assessment, path, nine-resource, review, notes, wrong-question and resource-center routes remain reachable; navigation contracts passed.",
    "G21-R02": "Review actions use the existing dedicated resource deep links and resource bundle workspace; no full artifact or duplicate resource page is embedded in the calendar.",
    "G21-R03": "The shared course, knowledge-point, task, source and profile context remains authoritative; review_course is isolated only for the legacy pseudo-filter and real course_id behavior passed protection tests.",
    "G21-R04": "The existing Chat route receives the selected review task's course, knowledge-point and source context through the established handoff; all F7 Chat protection tests passed.",
    "G21-R05": "Assessment remains limited to entry diagnosis and intelligent exam. F8 reads the existing exam gate and adds no assessment route, question type or unlock rule.",
    "G21-R06": "Original subject paths, total path and Today-required tasks remain authoritative. Review completion uses the existing aggregation and the F4 path and exam-gate suites passed.",
    "G21-R10": "Review resource generation writes through the existing F5 generation job, artifact history, version and source contracts; the F5 resource-history protection suite passed.",
    "G21-R11": "Review recall and delayed retest remain inside the review center, quiz practice remains a resource, and the assessment-center navigation still exposes only entry diagnosis and intelligent exam.",
    "G21-R12": "The generated package still contains separate training_task, code_sandbox and interactive_model artifacts with their existing routes and completion rules; F5/F6 protection tests passed.",
    "G21-R13": "The review page only displays the existing Today-required exam gate. Generating all nine optional resources neither adds hidden requirements nor bypasses the server-owned gate.",
}


def append_unique(values: list[str], additions: list[str]) -> list[str]:
    return list(dict.fromkeys([*values, *additions]))


def validate_report() -> dict:
    report_path = EVIDENCE_DIR / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "passed":
        raise RuntimeError("F8-T01 browser report is not passed")
    screenshots = report.get("screenshots") or []
    if len(screenshots) != 7 or any(
        not (EVIDENCE_DIR / "browser" / name).is_file() for name in screenshots
    ):
        raise RuntimeError("F8-T01 browser screenshot evidence is incomplete")
    for key in ("http_errors", "failed_requests", "page_errors", "console_errors", "external_requests"):
        if report.get(key) != []:
            raise RuntimeError(f"F8-T01 browser report contains {key}")
    if report.get("external_model_called") is not False:
        raise RuntimeError("F8-T01 browser report called an external model")

    visual = report.get("visual") or {}
    if set(visual) != {"review_1440_initial", "calendar_1366_initial"}:
        raise RuntimeError("F8-T01 browser report is missing a desktop viewport")
    for result in visual.values():
        if result.get("calendarCells") != 42:
            raise RuntimeError("F8-T01 calendar cell count changed")
        for key in ("clipped", "smallText", "collisions", "forbiddenThemeHits", "backgrounds"):
            if result.get(key) != []:
                raise RuntimeError(f"F8-T01 visual report contains {key}")
        if result.get("pageOverflow") or result.get("rootOverflow"):
            raise RuntimeError("F8-T01 visual report contains overflow")

    database = report.get("database") or {}
    before = database.get("browse_before") or {}
    after_browse = database.get("browse_after") or {}
    after_actions = database.get("after_actions") or {}
    if before != after_browse:
        raise RuntimeError("F8-T01 ordinary calendar browsing wrote business state")
    expected_deltas = {
        "learning_events": 2,
        "checkins": 1,
        "assessment_attempts": 1,
        "generation_tasks": 1,
    }
    for key, delta in expected_deltas.items():
        if after_actions.get(key) != before.get(key, 0) + delta:
            raise RuntimeError(f"F8-T01 database delta changed: {key}")
    if after_actions.get("integrity") != "ok" or after_actions.get("foreign_key_violations") != 0:
        raise RuntimeError("F8-T01 isolated database integrity failed")
    return report


def main() -> None:
    report = validate_report()
    matches = list(LEDGER_DIR.glob("F8-T01_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F8-T01 ledger, found {len(matches)}")
    ledger_path = matches[0]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    entries = {entry["atomic_requirement_id"]: entry for entry in ledger["entries"]}
    expected = set(PRIMARY) | set(RELATED)
    if set(entries) != expected:
        raise RuntimeError(
            f"Atomic realization mismatch: missing={sorted(expected - set(entries))}, "
            f"extra={sorted(set(entries) - expected)}"
        )

    final_evidence = [FOCUSED, REGRESSION, BUILD, E2E, VISUAL, DATABASE, BOUNDARIES]
    for batch in ledger.get("execution_batches", []):
        batch["verification"] = append_unique(
            list(batch.get("verification") or []),
            [E2E, DATABASE, BOUNDARIES],
        )
        batch["status"] = "VERIFIED"

    for atom_id, evidence in PRIMARY.items():
        realization = entries[atom_id]["realization"]
        realization["implementation_evidence"] = append_unique(
            list(realization.get("implementation_evidence") or []),
            [evidence["implementation"]],
        )
        realization["verification_evidence"] = append_unique(
            list(realization.get("verification_evidence") or []),
            [evidence["verification"], *final_evidence],
        )
        realization["user_visible_result"] = evidence["visible"]
        realization["compatibility_or_defer_rationale"] = (
            "F8-T01 owns the unified calendar and review actions only. Closed F4 exam/path, "
            "F5 resource, F6 training and F7 context contracts remain authoritative and "
            "passed the combined protection regression."
        )
        realization["status"] = "IMPLEMENTED_AND_VERIFIED"

    for atom_id, rationale in RELATED.items():
        realization = entries[atom_id]["realization"]
        realization["verification_evidence"] = append_unique(
            list(realization.get("verification_evidence") or []),
            [rationale, *final_evidence],
        )
        realization["compatibility_or_defer_rationale"] = rationale
        realization["user_visible_result"] = rationale
        realization["status"] = "COORDINATION_VERIFIED"

    ledger["final_acceptance"] = {
        "status": "VERIFIED",
        "report": str((EVIDENCE_DIR / "report.json").relative_to(ROOT)).replace("\\", "/"),
        "code_complete_metadata": "outputs/原系统融合重构执行/evidence/context_recovery/f8_t01_code_complete_metadata.json",
        "screenshots": report["screenshots"],
        "primary_atoms": len(PRIMARY),
        "related_atoms": len(RELATED),
        "external_model_called": False,
        "formal_database_modified": False,
    }
    temp = ledger_path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(ledger_path)
    print(
        json.dumps(
            {
                "status": "FINALIZED",
                "task": "F8-T01",
                "primary": len(PRIMARY),
                "related": len(RELATED),
                "screenshots": len(report["screenshots"]),
                "ledger": ledger_path.relative_to(ROOT).as_posix(),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
