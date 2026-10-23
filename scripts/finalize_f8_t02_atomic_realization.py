#!/usr/bin/env python3
"""Finalize F8-T02 per-atom realization after verified isolated acceptance."""

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
    / "f8_t02_wrong_questions"
)

FOCUSED = (
    "F8-T02 focused migration, canonical aggregation, read-model and frontend "
    "contracts passed 37 tests: 30 backend/aggregation tests and 7 frontend "
    "contracts, with only one existing dependency deprecation warning."
)
REGRESSION = (
    "F8-T02 plus F4 path/exam gate, F5 resource history, F6 quiz/formal exam, "
    "F7 Chat/source, F8 review and unified aggregation protection passed 88 "
    "tests in 52.78s with five existing framework deprecation warnings."
)
BUILD = (
    "frontend npm run build passed with 6936 modules transformed; focused git "
    "diff --check exited 0 with no whitespace errors."
)
E2E = (
    "Isolated dual-desktop E2E passed in 21.03s with eight screenshots, a "
    "deliberate 503 recovery, practice/formal source filters, source round trip, "
    "learner-confirmed diagnosis, one idempotent redo and refresh persistence."
)
VISUAL = (
    "Browser metrics at 1440x900 and 1366x768 found zero overflow, clipping, "
    "collisions, sub-14px text, forbidden theme colors or gradients. Full-size "
    "review accepted representative screenshots. Impeccable's only warning was "
    "the semantic real-error border at WrongQuestionBook.vue:535, so no visual "
    "defect was accepted."
)
DATABASE = (
    "Isolated SQLite retained one wrong-question row for the primary learner and "
    "question version. Ordinary browsing made zero learning, profile, assessment, "
    "wrong-question, mastery or path changes; the diagnosis added one non-mastery "
    "event and the redo added exactly one attempt and one trusted event. Every "
    "snapshot reports integrity_check=ok and zero foreign-key violations."
)
BOUNDARIES = (
    "No formal database, external model, external request, second question or "
    "score source, Git operation or delivery-package update was used. Expected "
    "503 diagnostics are separated from unexpected HTTP, request, page and console "
    "errors, whose final lists are empty."
)


PRIMARY = {
    "G22-R07": {
        "implementation": (
            "Migration 20260816_074 and the existing assessment projection now key a "
            "learner's wrong question by stable questionVersionId, append every owned "
            "practice and formal-exam attempt, and preserve legacy notes, pin, diagnosis "
            "and video links. app/wrong_question_read_model.py and WrongQuestionBook.vue "
            "provide the unified list/detail, source, error-pattern, review, resource, "
            "Chat, note, flashcard, similar-question, statistics and redo workflow."
        ),
        "verification": (
            "Focused tests prove safe migration, owner-scoped same-question merging, "
            "dual-source history, withheld formal feedback, zero-write reads and "
            "idempotent projection. Browser acceptance recovers a 503, confirms the "
            "candidate misconception, submits one correct redo and still shows all three "
            "attempts after refresh at both supported desktop sizes."
        ),
        "visible": (
            "The learner sees one durable record for each frozen question, understands "
            "every practice and intelligent-exam mistake in chronological context, can "
            "trace its source, confirm the real error pattern, open related deep-learning "
            "resources and submit a redo without losing prior attempts or protected 7.20 tools."
        ),
    }
}


RELATED = {
    "G21-R01": "The wrong-question workspace remains inside learning-space secondary navigation and preserves all existing assessment, path, resource, review and note destinations; navigation and browser protection passed.",
    "G21-R02": "Related lecture, video, quiz, review and Chat actions are compact deep links to their owning pages. No complete resource body or duplicate learning surface is embedded in the wrong-question page.",
    "G21-R03": "Course, knowledge-point, task, question-version, attempt and source identities come from the existing F2-F7 facts. Owner isolation and same-question merge tests found no parallel course, question or score object.",
    "G21-R04": "The existing Chat route receives the selected question, attempt and source context through its established deep link. The wrong-question first screen contains no private reasoning or duplicate Agent workbench.",
    "G21-R05": "Assessment remains limited to entry diagnosis and intelligent exam. Practice and redo remain quiz-resource behavior, while formal mistakes retain their real exam/report source without creating a third assessment module.",
    "G21-R06": "Total path, subject path and Today-required tasks remain authoritative. Only trusted redo evidence enters the existing aggregation, and ordinary browsing or diagnosis confirmation does not directly mutate path state.",
    "G21-R07": "F8-T01's 42-day review calendar, course filtering and zero-write browsing remain unchanged. Wrong-question details only expose the existing reviewTaskId and review deep link.",
    "G21-R08": "Related resources use the existing F5 resource routes and the existing F4 exam gate. The wrong-question page neither creates a second resource bundle nor bypasses locked intelligent-exam requirements.",
    "G21-R09": "Misconception confirmation is stored as a non-mastery progress event, while the server-scored redo is the trusted evidence. Browser and database evidence prove these effects remain distinct.",
    "G21-R10": "Resource history, version, source and custom-generation ownership remain with F5. Wrong questions store links and status only, and no resource content is copied into their rows.",
    "G21-R11": "Quiz-resource attempts and formal intelligent-exam responses retain separate source modes inside one history. Redo remains practice/review behavior and does not appear as a new formal examination.",
    "G21-R12": "Training task, code sandbox and interactive model remain separate resource types and routes. The wrong-question workspace only displays typed links when an admitted related resource exists.",
    "G21-R13": "Optional wrong-question study, notes, flashcards, similar questions and related resources do not become hidden intelligent-exam prerequisites; the existing Today-required gate remains the only authority.",
    "G22-R01": "Entry diagnosis remains the initial course assessment and its identities remain readable. F8-T02 consumes later mistakes without creating or bypassing diagnosis workflow.",
    "G22-R02": "Profile and path recommendations still consume the existing aggregated event snapshots. The wrong-question UI never computes mastery or recommendation state from a label or click.",
    "G22-R03": "Related learning resources continue to use the existing course, knowledge point, mastery and recent-event context; the wrong-question page supplies stable context references rather than fixed demonstration content.",
    "G22-R04": "Only a submitted and server-scored redo can produce completion/mastery evidence for the existing path aggregator. Browsing, pinning, notes and diagnosis confirmation cannot auto-check a path task.",
    "G22-R05": "The wrong-question page reads but cannot override the server-owned intelligent-exam gate. Existing locked and unlocked assessment contracts passed the combined regression.",
    "G22-R06": "Stable questionVersionId, attemptId, source event and review references are retained for F8-T05 cross-page synchronization; this task does not claim or simulate that future total synchronization work.",
    "G22-R08": "A learner can enter the existing Chat with the current mistake context and return. Full generated resources remain archived in learning space and ordinary questions remain non-mastery behavior.",
    "G22-R09": "Wrong-question rows contain canonical identities and links, not copied lecture, video or resource bodies. Missing or withdrawn sources remain honest and do not erase attempt history or user notes.",
    "G22-R10": "Related resources retain F5 history and custom-generation behavior in their owning workspace. The wrong-question link pre-fills context without adding a parallel version store.",
    "G22-R11": "Agent audit ownership remains with F7 and only its public, sanitized projection is reachable through Chat. No prompt, API key, private chain of thought or raw trace is rendered here.",
    "G22-R12": "Quiz, code and discovery capabilities stay in quiz resources, code sandbox and knowledge discovery. F8-T02 adds no embedded Chat quiz, executor or web-search workbench.",
    "G22-R13": "The empty and populated wrong-question flows use the team-provided course context and never require the learner to upload course material before deep learning.",
    "G22-R14": "Today's nine-resource package remains created and distributed by total path. Wrong questions only expose existing related-resource summaries and deep links, avoiding a second default bundle flow.",
    "G22-R15": "Intelligent-exam availability remains the F4 server contract, including missing Today-required tasks and direct routes. Wrong-question actions cannot hide or relax those requirements.",
    "G22-R16": "Load failure, empty filter, missing analysis, withdrawn source, diagnosis, redo and completion states preserve the selected question and history. The deliberate 503 recovered without losing data or relaying internal diagnostics.",
    "G24-R01": "Only meaningful misconception decisions and submitted redo attempts create existing unified learning events. The workspace adds no wrong-question-specific event bus.",
    "G24-R02": "Trusted redo evidence is consumed by the existing five-step aggregation for profile and mastery projections. The page itself writes no profile, path or plan projection.",
    "G24-R03": "The server distinguishes non-mastery diagnosis progress from accepted scored redo evidence. Client-controlled labels cannot forge strong evidence, as confirmed by API and browser tests.",
    "G24-R04": "Search, filtering, expansion, source round trips and ordinary browsing left learning events, profile mastery and path state unchanged in the isolated browser journey.",
    "G24-R05": "Stable owner plus questionVersionId identity produces one replayable wrong-question object with appended attempts. Refresh and projection replay preserve the same row and complete history.",
    "G24-R06": "Completion and mastery remain separate: diagnosis confirmation can create non-mastery progress, while only the correct submitted redo changes the knowledge-point mastery projection.",
    "G24-R07": "Database uniqueness and existing attempt/event idempotency keep one wrong-question row and one new attempt for the redo. Repeated projection cannot duplicate the object or score.",
}


def append_unique(values: list[str], additions: list[str]) -> list[str]:
    return list(dict.fromkeys([*values, *additions]))


def validate_report() -> dict:
    report_path = EVIDENCE_DIR / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "passed":
        raise RuntimeError("F8-T02 browser report is not passed")
    screenshots = report.get("screenshots") or []
    if len(screenshots) != 8 or any(
        not (EVIDENCE_DIR / "browser" / name).is_file() for name in screenshots
    ):
        raise RuntimeError("F8-T02 browser screenshot evidence is incomplete")
    for key in ("http_errors", "failed_requests", "page_errors", "console_errors", "external_requests"):
        if report.get(key) != []:
            raise RuntimeError(f"F8-T02 browser report contains {key}")
    if report.get("external_model_called") is not False:
        raise RuntimeError("F8-T02 browser report called an external model")
    if not report.get("deterministic_model_only"):
        raise RuntimeError("F8-T02 browser report is not deterministic")
    if not report.get("checks") or not all(report["checks"].values()):
        raise RuntimeError("F8-T02 browser journey checks are incomplete")

    visual = report.get("visual") or {}
    expected_visual = {
        "load_failure_1440x900",
        "merged_history_1440x900",
        "redo_complete_1440x900",
        "refresh_history_1440x900",
        "stable_workspace_1366x768",
    }
    if set(visual) != expected_visual:
        raise RuntimeError("F8-T02 browser report is missing a desktop visual state")
    for result in visual.values():
        for key in ("clipped", "smallText", "collisions", "forbiddenThemeHits", "backgrounds"):
            if result.get(key) != []:
                raise RuntimeError(f"F8-T02 visual report contains {key}")
        if result.get("pageOverflow") or result.get("rootOverflow"):
            raise RuntimeError("F8-T02 visual report contains overflow")
        if (result.get("layout") or {}).get("overlap") != 0:
            raise RuntimeError("F8-T02 list and detail panes overlap")

    database = report.get("database") or {}
    initial = database.get("initial") or {}
    read_before = database.get("read_only_before") or {}
    read_after = database.get("read_only_after") or {}
    after_diagnosis = database.get("after_diagnosis") or {}
    after_redo = database.get("after_redo") or {}
    secondary_before = database.get("secondary_read_only_before") or {}
    secondary_after = database.get("secondary_read_only_after") or {}
    final = database.get("final") or {}
    if initial != read_before or read_before != read_after:
        raise RuntimeError("F8-T02 ordinary primary-question browsing wrote business state")
    if secondary_before != secondary_after or secondary_after != final:
        raise RuntimeError("F8-T02 ordinary secondary-question browsing wrote business state")
    if after_redo != final:
        raise RuntimeError("F8-T02 refresh did not preserve the final canonical state")
    if after_diagnosis.get("learning_events") != initial.get("learning_events", 0) + 1:
        raise RuntimeError("F8-T02 misconception decision event delta changed")
    if after_diagnosis.get("assessment_attempts") != initial.get("assessment_attempts"):
        raise RuntimeError("F8-T02 misconception confirmation created an assessment attempt")
    if after_diagnosis.get("profile_mastery") != initial.get("profile_mastery"):
        raise RuntimeError("F8-T02 misconception confirmation changed mastery")
    if after_diagnosis.get("path_states") != initial.get("path_states"):
        raise RuntimeError("F8-T02 misconception confirmation changed path state")
    if after_redo.get("learning_events") != after_diagnosis.get("learning_events", 0) + 1:
        raise RuntimeError("F8-T02 redo event delta changed")
    if after_redo.get("assessment_attempts") != after_diagnosis.get("assessment_attempts", 0) + 1:
        raise RuntimeError("F8-T02 redo attempt delta changed")
    if after_redo.get("primary_attempts") != after_diagnosis.get("primary_attempts", 0) + 1:
        raise RuntimeError("F8-T02 canonical attempt history delta changed")
    if after_redo.get("correct_primary_attempts") != after_diagnosis.get("correct_primary_attempts", 0) + 1:
        raise RuntimeError("F8-T02 correct redo delta changed")
    for snapshot in database.values():
        if not isinstance(snapshot, dict):
            continue
        if snapshot.get("integrity") != "ok" or snapshot.get("foreign_key_violations") != 0:
            raise RuntimeError("F8-T02 isolated database integrity failed")
        if snapshot.get("primary_wrong_rows") != 1:
            raise RuntimeError("F8-T02 duplicated the canonical wrong-question row")
    return report


def main() -> None:
    report = validate_report()
    matches = list(LEDGER_DIR.glob("F8-T02_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F8-T02 ledger, found {len(matches)}")
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
            list(batch.get("verification") or []), final_evidence
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
            "F8-T02 owns canonical wrong-question identity, history and deep-learning "
            "workflow only. Closed F2-F8 question, assessment, resource, source, review, "
            "path and aggregation contracts remain authoritative and passed protection."
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
        "code_complete_metadata": "outputs/原系统融合重构执行/evidence/context_recovery/f8_t02_code_complete_metadata.json",
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
                "task": "F8-T02",
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
