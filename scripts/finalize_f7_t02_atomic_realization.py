#!/usr/bin/env python3
"""Finalize F7-T02 per-atom realization evidence without runtime writes."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "原系统融合重构执行"
CONTEXT_ROOT = OUTPUT / "evidence" / "context_recovery"
LEDGER_DIR = (
    CONTEXT_ROOT
    / "atomic_requirement_ledgers"
    / "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION"
)
SUMMARY = "outputs/原系统融合重构执行/evidence/f7_t02_document_reader/evidence_summary.md"
BROWSER_REPORT = (
    "outputs/原系统融合重构执行/evidence/f7_t02_document_reader/browser/report.json"
)
FOCUSED = (
    "F7-T02 focused and F7-T01 protection regression: 23 passed across backend reader, frontend contract, "
    "knowledge bookshelf and protected frontend behavior; existing framework deprecation warnings only"
)
BUILD = "frontend npm run build: PASS, 6939 modules transformed; existing chunk-size advisory only"
E2E = (
    "scripts/e2e_f7_t02_document_reader.py: PASS in 22.5s with 10 screenshots at 1440x900 and 1366x768; "
    "Markdown/PDF reading, text/image selection, OCR failure recovery, source return, note, generation and "
    "refresh restoration verified"
)
VISUAL = (
    "Manual screenshot review: central reader remains the visual subject; selection controls and recovery states "
    "are readable with no overlap, clipping, prohibited theme colors or decorative effects"
)
IMPECCABLE = (
    "Impeccable detect.mjs: []; no deterministic findings for KnowledgeDocumentReader.vue or SelectionToolbar.vue"
)
DATABASE = (
    "isolated F7-T02 SQLite: integrity ok, 0 foreign-key violations, learning-event count unchanged at 127, "
    "2 selections, 1 selection note and 2 source-bound generation jobs; no formal database write"
)
NO_EXTERNAL = "E2E observed 0 external requests and external_model_called=false"


def realized(
    *,
    role: str,
    implementation: list[str],
    verification: list[str],
    visible: str,
    rationale: str,
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
        rationale=(
            "F7-T02 owns this document-reader behavior and preserves F7-T05 unified source/Agent governance and "
            "F8-T03 notebook-wide linkage as later declared responsibilities."
        ),
    )


def related(
    implementation: list[str],
    visible: str,
    rationale: str,
    *verification: str,
) -> dict[str, object]:
    return realized(
        role="related",
        implementation=implementation,
        verification=list(verification) or [FOCUSED, E2E],
        visible=visible,
        rationale=rationale,
    )


REALIZATION = {
    "G07-R01": primary(
        [
            "KnowledgeDocumentReader is the dedicated /knowledge/documents/:documentId workspace entered from the existing knowledge shelf and search paths.",
            "The desktop reader uses a stable 20/58/22 directory, original-document and source/action hierarchy; the central document remains the largest surface.",
            "Reader navigation and ordinary view actions persist only reading state and do not create learning or completion evidence.",
        ],
        "The learner opens a knowledge document in one clear three-column workspace: chapter navigation on the left, the original document as the central focus, and source, question, note and generation actions on the right.",
        FOCUSED,
        BUILD,
        E2E,
        VISUAL,
        IMPECCABLE,
        DATABASE,
    ),
    "G07-R02": primary(
        [
            "reader_document returns owner-authorized canonical course Markdown or owner-scoped personal PDF pages together with version, chapter, source and processing facts.",
            "KnowledgeDocumentReader renders long Markdown as selectable text and PDF page images at readable scale instead of reducing either format to a preview card.",
            "The display-only Markdown line-break normalization keeps an explicit display-to-source offset map so canonical source offsets and quotes remain unchanged.",
        ],
        "The learner reads complete course Markdown or a real PDF page in the large central reader; long content remains readable, searchable and selectable, while unavailable or stale content fails honestly without substituting an unreviewed file.",
        FOCUSED,
        E2E,
        VISUAL,
        DATABASE,
    ),
    "G07-R03": primary(
        [
            "create_document_selection stores owner-scoped, document-versioned text ranges or validated normalized image rectangles in DBDocumentSelection.",
            "SelectionToolbar exposes question, note and resource actions beside an active selection; image OCR state is stored on the same selection.",
            "ask_about_selection returns a local source-constrained answer bound to selection_id and source_ref_id without an external-model call.",
        ],
        "The learner can select exact text or drag a rectangle over a PDF image, then ask about that selection from a compact nearby toolbar. The same selection and its precise source survive zoom and refresh; failed OCR keeps the image region available for retry.",
        FOCUSED,
        E2E,
        DATABASE,
        NO_EXTERNAL,
    ),
    "G07-R04": primary(
        [
            "KnowledgeDocumentReader.exportParsedText downloads the authorized parsed document with a stable source-aware filename.",
            "The export action is secondary to reading and selection, and an export failure leaves the current location and selection untouched.",
        ],
        "The learner can export the currently authorized parsed text from the reader toolbar with an identifiable filename; exporting does not change learning progress or lose the current reading position.",
        FOCUSED,
        E2E,
        DATABASE,
    ),
    "G07-R05": primary(
        [
            "The reader detail payload reuses existing DBSourceDocument, DBSourceRef, course, chapter, version, license and parser-status facts.",
            "The source panel follows the current page or selection and locateSelection returns the learner to the exact text range or image page.",
            "Source viewing remains read-only and does not create mastery or completion evidence.",
        ],
        "The right panel shows the real course, document version, chapter or page, format, license and parsing status. From an answer or selection, the learner can return to the cited original location.",
        FOCUSED,
        E2E,
        DATABASE,
    ),
    "G07-R06": primary(
        [
            "generate_from_document and generate_from_selection bridge the current source_ref_id or selection_id into the existing GenerationJob protocol.",
            "The bridge freezes course, document version, approved source and selected excerpt, uses existing idempotency semantics and creates no learning evidence.",
            "KnowledgeDocumentReader reports the real generation job and its resource-center destination instead of rendering a fabricated complete artifact in the side panel.",
        ],
        "From either the whole file or a valid selection, the learner starts a source-bound learning-resource job and sees its real task identity and resource-space destination. Repeating the same request reuses the job, and generation alone does not count as learning completion.",
        FOCUSED,
        E2E,
        DATABASE,
    ),
    "G07-R08": primary(
        [
            "ReadingPosition stores the owner, source document, document version, page, section, raw character offset, scroll ratio and zoom.",
            "The reader exposes chapter/page navigation, in-document search, previous/next result, zoom and a visible restoration indicator over one location protocol.",
            "Markdown search and selection use canonical raw offsets even when display-only line-break escapes are normalized.",
        ],
        "The learner can jump by chapter or page, search within the current document, move among results and change zoom. Returning or refreshing restores the last page, section, position and zoom instead of restarting the document.",
        FOCUSED,
        E2E,
        DATABASE,
    ),
    "G07-R10": primary(
        [
            "document_state restores the current ReadingPosition and latest valid SelectionContext only for the authorized owner and matching document version.",
            "retry_selection_ocr replays only OCR while preserving the page image, normalized rectangle, question draft and other successful reader state.",
            "The frontend keeps independent page, selection, OCR, question, note and generation failure states so retry does not clear readable content.",
        ],
        "After refresh or leaving and returning, the learner resumes the same document position, zoom and selection. If OCR cannot read an image region, the page, rectangle and question remain visible and a dedicated retry action is available.",
        FOCUSED,
        E2E,
        VISUAL,
        DATABASE,
    ),
    "G07-R07": related(
        [
            "Selection questions retain selection_id, source_ref_id, document version, source location, public answer text and failure state.",
            "The local answer is constrained to the selected canonical quote or verified OCR text and exposes no prompt, key, private reasoning or raw Agent log.",
        ],
        "The learner already sees a source-bound local answer and can return to the selected original location; answers without verifiable selection text fail honestly.",
        "F7-T05 remains the sole owner of unified sourceRefId/selectionId governance across answers and artifacts and of the complete public Agent candidate, disagreement, validation, revision and decision summary. F7-T02 supplies compatible source-bound records and does not claim that later governance is complete.",
        FOCUSED,
        E2E,
        NO_EXTERNAL,
    ),
    "G07-R09": related(
        [
            "save_selection_note writes through the existing owner-scoped DBNote source of truth with selection_id, source_ref_id, document version, page or section and quote/rectangle provenance.",
            "The selection toolbar preserves the note draft after failure and reports the real saved note without creating a learning event.",
        ],
        "The learner can save selected text or an image region as a source-linked note directly from the reader, and a failed save leaves both the draft and selection available.",
        "F8-T03 remains the sole owner of notebook-wide source cards, editing, history, search and source-invalidated presentation. F7-T02 reuses the existing note fact source and supplies compatible provenance without creating a second notebook or treating note creation as mastery evidence.",
        FOCUSED,
        E2E,
        DATABASE,
    ),
}


def append_unique(current: list[str], additions: list[str]) -> list[str]:
    return list(dict.fromkeys([*current, *additions]))


def main() -> None:
    matches = list(LEDGER_DIR.glob("F7-T02_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F7-T02 ledger, found {len(matches)}")
    ledger_path = matches[0]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    actual_ids = [entry["atomic_requirement_id"] for entry in ledger["entries"]]
    missing = [atom_id for atom_id in actual_ids if atom_id not in REALIZATION]
    extra = [atom_id for atom_id in REALIZATION if atom_id not in actual_ids]
    if missing or extra:
        raise RuntimeError(f"Atomic realization mismatch: missing={missing}, extra={extra}")

    for entry in ledger["entries"]:
        final = REALIZATION[entry["atomic_requirement_id"]]
        current = entry.get("realization", {})
        final["implementation_evidence"] = append_unique(
            list(current.get("implementation_evidence", [])),
            list(final["implementation_evidence"]),
        )
        final["verification_evidence"] = append_unique(
            list(current.get("verification_evidence", [])),
            list(final["verification_evidence"]),
        )
        entry["realization"] = final

    primary_ids = [entry["atomic_requirement_id"] for entry in ledger["entries"] if entry["role"] == "primary"]
    related_ids = [entry["atomic_requirement_id"] for entry in ledger["entries"] if entry["role"] == "related"]
    batch = {
        "id": "F7-T02-B06",
        "status": "VERIFIED",
        "atoms": [*primary_ids, *related_ids],
        "direct_atoms": primary_ids,
        "related_atoms": related_ids,
        "files": [
            "app/database.py",
            "app/migrations.py",
            "app/multimodal.py",
            "app/document_selection.py",
            "app/main.py",
            "frontend/src/views/KnowledgeDocumentReader.vue",
            "frontend/src/components/SelectionToolbar.vue",
            "frontend/src/api/knowledge.js",
            "frontend/src/router/index.js",
            "frontend/src/components/KnowledgeCourseShelf.vue",
            "frontend/src/views/Knowledge.vue",
            "tests/test_f7_t02_document_reader.py",
            "tests/test_f7_t02_document_reader_frontend_contract.py",
            "tests/test_f7_t01_knowledge_shelf.py",
            "tests/test_f7_t01_knowledge_frontend_contract.py",
            "scripts/e2e_f7_t02_document_reader.py",
            "scripts/finalize_f7_t02_atomic_realization.py",
            BROWSER_REPORT,
            SUMMARY,
            "outputs/原系统融合重构执行/evidence/f7_t02_document_reader/batch_06_closure_mapping.json",
            "outputs/原系统融合重构执行/evidence/f7_t02_document_reader/code_complete_metadata.json",
            "outputs/原系统融合重构执行/evidence/f7_t02_document_reader/tested_metadata.json",
            "outputs/原系统融合重构执行/evidence/f7_t02_document_reader/evidence_verified_metadata.json",
            "outputs/原系统融合重构执行/evidence/f7_t02_document_reader/closed_metadata.json",
        ],
        "verification": [FOCUSED, BUILD, E2E, VISUAL, IMPECCABLE, DATABASE, NO_EXTERNAL],
        "protection_contracts": [
            "F7-T05 retains ownership of unified source and Agent audit governance",
            "F8-T03 retains ownership of notebook-wide source, history and invalidation presentation",
            "F7-T01 canonical course, license and bookshelf behavior remains protected",
            "ordinary reading, selection, search, export, source viewing, notes and generation do not write mastery evidence",
            "personal PDF access remains owner-scoped and canonical course Markdown remains hash-verified",
            "verification uses isolated SQLite and no external model, formal database, Git or delivery package",
        ],
        "evidence_summary": SUMMARY,
    }
    batches = ledger.setdefault("execution_batches", [])
    existing = next((item for item in batches if item.get("id") == batch["id"]), None)
    if existing is None:
        batches.append(batch)
    else:
        existing.update(batch)
    ledger_path.write_text(
        json.dumps(ledger, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    sys.path.insert(0, str(ROOT / "scripts"))
    from context_recovery_atomic_gate import (
        expected_entries,
        load_task_payload,
        validate_ledger_identity,
        validate_realization,
    )

    active = json.loads((CONTEXT_ROOT / "active_manifest.json").read_text(encoding="utf-8"))
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F7-T02")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F7-T02",
        entries=expected,
    )
    failures.extend(validate_realization(ledger, expected))
    if failures:
        raise RuntimeError(f"F7-T02 atomic realization gate failed: {failures}")
    print(f"Updated and validated {len(actual_ids)} F7-T02 atomic realizations: {ledger_path}")


if __name__ == "__main__":
    main()
