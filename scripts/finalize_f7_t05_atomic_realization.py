#!/usr/bin/env python3
"""Finalize F7-T05 per-atom realization evidence without runtime writes."""

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

COMBINED = (
    "Final F7-T05 combined regression: 29 passed in 20.47s across source projection, "
    "public Agent audit, frontend contracts and F7-T02/F7-T04 protection contracts."
)
E2E = (
    "Isolated dual-desktop E2E passed in 24.8s with 7 screenshots: exact source "
    "round-trips, four public Agent stages, failed-run honesty and historical-result "
    "separation all passed at 1440x900 and 1366x768."
)
VISUAL = (
    "Browser evidence reported 0 overflow, collisions, clipping, sub-14px text, "
    "gradients, forbidden theme colors, HTTP errors, failed requests, page errors, "
    "console errors and external requests; Impeccable detector returned []."
)
DATABASE = (
    "Isolated SQLite stayed intact with 0 foreign-key violations; learning events "
    "9->9, profile snapshots 1->1, generation tasks 0->0, assessment attempts 2->2, "
    "Chat messages 6->6, source counts 39/42 unchanged and mastery unchanged."
)
SENSITIVE = (
    "Recursive sanitizer and frontend contracts reject prompt, secret, api_key, "
    "reasoning_content, chain_of_thought, raw_trace and raw_log fields; browser text "
    "and API responses exposed none of them."
)


PRIMARY = {
    "G07-R07": {
        "implementation": (
            "app/source_refs.py and SourceCitation.vue provide one owner/course-authorized "
            "source projection for reader selections, Chat answers and resource footnotes, "
            "including stable sourceRefId/selectionId, availability and exact document location."
        ),
        "verification": (
            "Source projection tests cover current, withdrawn, permission-changed, version-drifted "
            "and removed references; browser evidence opens the exact chapter/character location "
            "from a handout and Chat answer and restores return_to."
        ),
        "visible": (
            "Every verified answer or footnote shows a source row that opens the exact document "
            "position; an unavailable source remains honestly labelled instead of becoming a "
            "fabricated or silently substituted citation."
        ),
    },
    "G12-R04": {
        "implementation": (
            "app/agent_audit.py, chat_api.py and AgentTimeline.vue expose the persisted analysis, "
            "generation, validation and decision facts beside the current Chat answer and reader "
            "selection answer."
        ),
        "verification": (
            "Agent audit tests and browser evidence verify four truthful public stages for completed "
            "and failed answers, including source inputs, validation result and final decision state."
        ),
        "visible": (
            "The learner can expand a compact four-stage collaboration summary beside the answer "
            "and see what source was used, what was checked and whether the result actually completed."
        ),
    },
    "G12-R05": {
        "implementation": (
            "The public Agent projection uses an explicit allow-list and recursively sanitizes nested "
            "inputs, summaries and errors before persistence, streaming or frontend rendering."
        ),
        "verification": SENSITIVE,
        "visible": (
            "The learner sees useful responsibilities, evidence and decision summaries without any "
            "claim or display of private reasoning, prompts, credentials, traces or raw logs."
        ),
    },
    "G12-R07": {
        "implementation": (
            "Chat persists server-owned agent_audit facts in the existing stream checkpoint and the "
            "frontend store restores those facts on progress, checkpoint, completion, stop and error "
            "events without timers or client-inferred stage completion."
        ),
        "verification": (
            "Combined contracts and E2E verify streamed answer content remains readable while pending, "
            "completed and failed Agent stages remain consistent after selection, refresh and navigation."
        ),
        "visible": (
            "The answer streams in the main column while the evidence rail shows a compact, expandable "
            "stage summary; a stopped or failed run never turns unfinished stages into completed ones."
        ),
    },
    "G22-R11": {
        "implementation": (
            "HandoutWorkspace, KnowledgeDocumentReader and Chat share exact source navigation, return "
            "context and the same public Agent audit component instead of linking to a separate technical page."
        ),
        "verification": (
            "The isolated browser journey moves from handout footnote to exact reader location, from "
            "reader selection answer to its audit, and from Chat source back to Chat with all protected "
            "learning-state counts unchanged."
        ),
        "visible": (
            "During ordinary learning, the learner can inspect how an answer was checked, open the cited "
            "course evidence and return to the same learning context without losing the conversation."
        ),
    },
    "G27-R05": {
        "implementation": (
            "SourceCitation and AgentTimeline are embedded in the real reader, handout and Chat surfaces; "
            "no Agent navigation item, standalone technology route or fixed process animation was added."
        ),
        "verification": (
            "Frontend contracts reject fabricated timers and independent Agent workbenches, and dual-desktop "
            "screenshots confirm the answer or document remains the visual subject while details stay expandable."
        ),
        "visible": (
            "Multi-Agent checking appears exactly where the learner judges an answer or source, collapsed by "
            "default and available on demand instead of interrupting the learning flow with a technology demo."
        ),
    },
    "G27-R07": {
        "implementation": (
            "Failed current Chat audits remain failed; any earlier completed answer is attached under a "
            "different identity and labelled '历史已完成回答（非本次结果）' without changing the failed run."
        ),
        "verification": (
            "Agent audit fault tests and browser E2E verify a provider failure preserves failed stages, keeps "
            "historical output read-only and creates no completion or mastery evidence."
        ),
        "visible": (
            "When the current model run fails, the learner sees the real failure and retry path; a usable older "
            "answer may still be opened, but it is clearly marked as historical rather than this run's result."
        ),
    },
}


RELATED = {
    "G07-R01": "F7-T02's 20/58/22 reader remains authoritative; shared citations stay inside the existing context rail, and the browser geometry checks prove the document remains the visual subject.",
    "G07-R02": "Canonical Markdown/PDF content still comes from the F7-T02 document/version facts; source projection adds location and availability metadata without replacing the large reader with a card preview.",
    "G07-R03": "Text and image SelectionContext ownership, normalized geometry, OCR recovery and owner isolation remain unchanged; F7-T05 only exposes their stable selectionId through the shared citation projection.",
    "G07-R04": "The existing permission-checked export path is untouched; frontend protection contracts and unchanged learning-state counts verify citation integration does not turn export into evidence or clear reader state.",
    "G07-R05": "DBSourceDocument/DBSourceRef remain the source facts; F7-T05 adds a single authorized reverse link and explicit withdrawn/drifted status, verified by source projection tests and browser round-trips.",
    "G07-R06": "GenerationJob and Artifact versioning remain owned by F2/F5; resource source snapshots reuse canonical refs, withdrawn refs block new use, and no second resource table or inline full artifact was introduced.",
    "G07-R08": "F7-T02 page/chapter/search/location semantics remain authoritative; the reader now saves against its loaded stable source_document_id during route exit, and exact return_to restoration passed E2E.",
    "G07-R09": "Selection-note ownership remains with F7-T02/F8-T03; F7-T05 preserves the existing document/page/region identity and neither rewrites note text nor introduces mastery evidence.",
    "G07-R10": "F7-T02 recovery state remains intact; exact source navigation carries the existing location and the stable loaded document fix prevents an empty position-save request when leaving the reader.",
    "G12-R01": "F7-T04 remains authoritative for PDF, PPTX, DOCX, text and image attachments; F7-T05 reads only persisted parse/source facts and the F7-T04 protection suite passed.",
    "G12-R02": "F7-T04's parse-before-send and idempotent message rules are unchanged; the audit input list is derived only from persisted sendable attachment versions, never queued or failed client guesses.",
    "G12-R03": "Attachment progress, sanitized failure reason, partial confirmation and per-item retry remain owned by F7-T04; the public audit reports those facts without replacing or beautifying the real failure state.",
    "G12-R06": "All six F7-T04 attachment states remain server-owned and recoverable; removed attachments are excluded from source/audit inputs and the closed-task frontend contracts passed in the 29-test run.",
    "G12-R08": "Attachment parse IDs, message context, source refs, selections and resource links now resolve through one projection while F7-T04 conversation and F5 resource ownership remain unchanged; exact identity/return navigation passed E2E.",
    "G27-R01": "Profile adaptation remains owned by the existing generation decisions; F7-T05 exposes only approved profile-context summaries already attached to a real result and does not recalculate or reveal private profile answers.",
    "G27-R02": "The approved analysis/generation/validation/decision protocol remains the only public collaboration sequence; server facts drive AgentTimeline and frontend timer simulation is rejected by contract tests.",
    "G27-R03": "The public audit renders persisted disagreement and revision summaries when present and states no material disagreement otherwise; tests verify no hidden reasoning or invented debate is added.",
    "G27-R04": "The validation stage consumes the same authorized SourceRef availability used by citations, so withdrawn, missing and conflicting evidence cannot display as passed; source and Agent suites passed together.",
    "G27-R06": "F2's public-field whitelist remains authoritative and F7-T05 applies the same boundary in persistence, stream and Vue rendering; recursive adversarial tests and browser scans found no private fields.",
}


def append_unique(values: list[str], additions: list[str]) -> list[str]:
    return list(dict.fromkeys([*values, *additions]))


def main() -> None:
    matches = list(LEDGER_DIR.glob("F7-T05_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F7-T05 ledger, found {len(matches)}")

    ledger_path = matches[0]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    entries = {entry["atomic_requirement_id"]: entry for entry in ledger["entries"]}
    expected = set(PRIMARY) | set(RELATED)
    if set(entries) != expected:
        raise RuntimeError(
            f"Atomic realization mismatch: missing={sorted(set(entries) - expected)}, "
            f"extra={sorted(expected - set(entries))}"
        )
    incomplete_batches = [
        batch["id"]
        for batch in ledger.get("execution_batches", [])
        if batch.get("status") != "VERIFIED"
    ]
    if incomplete_batches:
        raise RuntimeError(f"Unverified execution batches: {incomplete_batches}")

    for atom_id, evidence in PRIMARY.items():
        realization = entries[atom_id]["realization"]
        realization["implementation_evidence"] = append_unique(
            list(realization.get("implementation_evidence") or []),
            [evidence["implementation"]],
        )
        realization["verification_evidence"] = append_unique(
            list(realization.get("verification_evidence") or []),
            [evidence["verification"], COMBINED, E2E, VISUAL, DATABASE],
        )
        realization["user_visible_result"] = evidence["visible"]
        realization["compatibility_or_defer_rationale"] = (
            "F7-T05 owns only shared source projection and public Agent evidence. Closed F7-T02 "
            "reader behavior, F7-T04 conversation behavior, F5 resource facts and F2 learning-event "
            "admission remain authoritative and passed their focused protection contracts."
        )
        realization["status"] = "IMPLEMENTED_AND_VERIFIED"

    for atom_id, rationale in RELATED.items():
        realization = entries[atom_id]["realization"]
        realization["verification_evidence"] = append_unique(
            list(realization.get("verification_evidence") or []),
            [rationale, COMBINED, E2E, VISUAL, DATABASE],
        )
        realization["compatibility_or_defer_rationale"] = rationale
        realization["status"] = "COORDINATION_VERIFIED"

    temp = ledger_path.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp.replace(ledger_path)
    print(
        json.dumps(
            {
                "status": "FINALIZED",
                "task": "F7-T05",
                "primary": len(PRIMARY),
                "related": len(RELATED),
                "ledger": ledger_path.relative_to(ROOT).as_posix(),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
