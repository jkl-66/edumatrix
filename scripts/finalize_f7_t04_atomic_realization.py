#!/usr/bin/env python3
"""Finalize F7-T04 per-atom realization evidence without runtime writes."""

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
SUMMARY = "outputs/原系统融合重构执行/evidence/f7_t04_chat/evidence_summary.md"
BROWSER_REPORT = "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/report.json"
BROWSER_MANIFEST = "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/manifest.json"

FOCUSED = (
    "F7-T04 focused regression: 35 passed across owner-scoped chat API, canonical stream, M5 "
    "context, F6 quiz protection and frontend source contracts; only existing FastAPI lifecycle "
    "deprecation warnings remained"
)
BUILD = "frontend npm run build: PASS, 6931 modules transformed; existing chunk-size advisory only"
E2E = (
    "scripts/e2e_f7_t04_chat.py: PASS at 1440x900 and 1366x768 with 8 screenshots; owner-scoped "
    "conversations, real Markdown upload, PDF partial confirmation, DOCX retry, image removal, "
    "answer-first resource generation, stop/continue, empty state, inline quiz and follow-up verified"
)
VISUAL = (
    "Five browser visual contracts and manual review of all 8 final screenshots: 228px conversation "
    "rail, flexible answer column and 292px evidence rail remained readable with no overflow, overlap, "
    "clipped text, sub-14px text, background image or forbidden theme hit"
)
IMPECCABLE = (
    "Impeccable post-fix detect.mjs returned [] for Chat.vue and IncrementalMarkdownRenderer.vue after "
    "removing two layout-property transitions and one thick colored side accent"
)
DATABASE = (
    "isolated F7-T04 SQLite: integrity_check=ok and 0 foreign-key violations; ordinary Chat actions "
    "kept learning events, profile snapshots, mastery and canonical sources unchanged; only the "
    "canonical quiz submission created the expected evidence"
)
NO_EXTERNAL = (
    "Browser report recorded http_errors=[], failed_requests=[], page_errors=[], console_errors=[], "
    "external_requests=[] and external_model_called=false"
)
DIFF = "Focused git diff --check passed; only existing Windows LF-to-CRLF notices were emitted"


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
        verification=list(verification) or [FOCUSED, BUILD, E2E, VISUAL],
        visible=visible,
        rationale=(
            "F7-T04 owns the focused conversation, attachment, stream and compact-resource behavior. "
            "F6-T01 remains authoritative for quiz generation and scoring, F7-T02 for document source "
            "locations, and F7-T05 for the complete public Agent audit and cross-product source governance."
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
        verification=list(verification) or [FOCUSED, E2E, DATABASE],
        visible=visible,
        rationale=rationale,
    )


REALIZATION = {
    "G04-R06": primary(
        [
            "frontend/src/views/Chat.vue embeds exactly one canonical InlineQuizCard when resourceId and questionVersionId identify a real F6 quiz question, and keeps the complete quiz route in Learning Space.",
            "The quiz deep-link entry focuses the compact question at the top of the message scroller; the follow-up action preserves the question, attempt and source context in the Chat draft.",
            "scripts/e2e_f7_t04_chat.py submits the visible answer option through the F6 endpoint, waits for server feedback and verifies no extra attempt is created by drafting a follow-up.",
        ],
        "The learner opens one compact question inside Chat, chooses and submits an answer, sees the server-owned result and explanation in place, asks a follow-up, or opens the complete quiz and history in Learning Space.",
        FOCUSED,
        BUILD,
        E2E,
        VISUAL,
        DATABASE,
    ),
    "G12-R01": primary(
        [
            "app/chat_api.py persists owner-scoped conversations, messages and attachment parses separately from canonical course documents and learning evidence.",
            "frontend/src/api/chat.js and frontend/src/stores/chat.js support PDF, PPTX, DOCX, Markdown/text and image upload through the canonical attachment protocol.",
            "Chat.vue exposes the five attachment families in one composer and restores their server state after conversation refresh.",
        ],
        "The learner attaches PDF, PPTX, DOCX, Markdown/text or an image to the existing /learn conversation and sees the file in the current conversation without uploading course material or creating a new product route.",
        FOCUSED,
        BUILD,
        E2E,
        DATABASE,
        NO_EXTERNAL,
    ),
    "G12-R02": primary(
        [
            "app/chat_api.py accepts only owner-authorized attachment IDs in sendable terminal states and freezes the exact parse versions on the persisted message pair.",
            "frontend/src/stores/chat.js blocks send while a selected attachment is queued or parsing, preserves one idempotency key for uncertain retries and starts the stream only from a persisted user_message_id.",
            "Chat.vue explains the concrete blocking attachment and allows partial-result confirmation, retry or removal without losing the draft.",
        ],
        "The learner cannot send an attachment before parsing finishes. A partial result must be confirmed, a retryable failure can be retried, and the same question is persisted only once before streaming begins.",
        FOCUSED,
        E2E,
        DATABASE,
    ),
    "G12-R03": primary(
        [
            "The attachment API returns stable stage, progress, warning, sanitized error, retryable and checkpoint fields without trace, path, prompt or secret leakage.",
            "Chat.vue shows each file's parsing summary, usable and failed scope, recovery action and removal action while preserving other successful files and the question draft.",
            "The bounded Impeccable polish replaced the failure callout's thick colored side accent with the incumbent neutral border token and retained the explicit recovery copy.",
        ],
        "The learner sees which file and stage failed, what content remains usable and whether to retry, confirm or remove it; other attachments and the typed question remain intact.",
        FOCUSED,
        E2E,
        VISUAL,
        IMPECCABLE,
        NO_EXTERNAL,
    ),
    "G12-R06": primary(
        [
            "The attachment state machine supports queued, parsing, ready, partial_failed, failed_retryable and removed states with lock-version guarded transitions.",
            "Chat.vue renders state text, icon, progress and per-item actions; removed files are excluded from future message context and restored from server truth rather than localStorage.",
            "The post-fix UI removes layout-property animation from the attachment progress bar while keeping stable row geometry and keyboard-accessible actions.",
        ],
        "Each attachment visibly moves through waiting, parsing, ready, partial, retryable failure or removed states, and the learner always has a clear next action without relying on color alone.",
        FOCUSED,
        E2E,
        VISUAL,
        IMPECCABLE,
    ),
    "G12-R08": primary(
        [
            "Canonical messages persist ContextRefs, attachmentParseIds, sourceRefs, resourceLinks and streamCheckpoint under owner authorization.",
            "stream_api.py consumes only the persisted user_message_id and validated context, then returns approved source and compact resource locator fields on the centralized completion path.",
            "Chat.vue's evidence rail presents course, knowledge point, attachment location, canonical source, return path and Learning Space resource links without embedding full resource content.",
        ],
        "The learner can see which course, knowledge point, file or source supported an answer, return to the originating learning position and open the generated resource in its formal Learning Space route.",
        FOCUSED,
        E2E,
        DATABASE,
        NO_EXTERNAL,
    ),
    "G20-R05": primary(
        [
            "Chat.vue is reduced to the focused 228px/flexible/292px conversation, answer and evidence workspace; the legacy quiz, code and web-search workbenches are removed.",
            "Legacy quiz, code and search query modes redirect to /workspace/resources/quizzes/:resourceId, /workspace/code/:resourceId or /knowledge/discover instead of mounting a second editor.",
            "The focused Chat retains the 7.20 conversation list, history, attachments, streaming and context while preserving the fixed eight-item student navigation.",
        ],
        "The learner sees one understandable Chat workspace. Full quizzes, code execution and web discovery remain available in their proper modules through clear deep links rather than competing Chat tabs.",
        FOCUSED,
        BUILD,
        E2E,
        VISUAL,
        IMPECCABLE,
    ),
    "G20-R07": primary(
        [
            "The existing /learn route is the sole multimodal conversation entry; documents and images share the same composer, owner-scoped history and stream.",
            "No provider-settings route, separate multimodal demo or additional top-level navigation item was introduced.",
            "Unsupported vision behavior remains an honest backend limitation while parsed text and local source context stay available; automated verification makes no external model call.",
        ],
        "The learner uses document and image context from the same Intelligent Chat entry on both required desktop sizes, with no separate setup page or duplicate conversation product.",
        FOCUSED,
        E2E,
        NO_EXTERNAL,
    ),
    "G21-R04": primary(
        [
            "The /learn context adapter accepts structured course, knowledge-point, resource, question, attempt, source and returnTo references and resolves them under the current owner.",
            "Chat.vue displays the active context in the right rail and provides a return-to-learning action without rewriting the referenced resource or source.",
            "F6 quiz and F7 document source contracts remain authoritative; opening or changing Chat context never writes learning evidence.",
        ],
        "From a learning resource or question, the learner arrives in Chat with the relevant course and source already attached, asks a focused question and can return to the original learning position.",
        FOCUSED,
        E2E,
        DATABASE,
    ),
    "G22-R08": primary(
        [
            "The canonical stream completes the answer before app/chat_api.py exposes an explicit handout, mind-map or quiz generation action.",
            "The explicit action reuses the existing single-resource GenerationJob protocol with current course, knowledge point, profile snapshot, recent event context and source refs.",
            "Chat persists only compact job status and Learning Space links; full content, versions, history and editors remain in resource modules, and idempotent retries reuse the same job.",
        ],
        "The learner first receives a readable sourced answer, then deliberately chooses a resource type. Chat shows only a compact generation link while the complete resource is stored in Learning Space.",
        FOCUSED,
        E2E,
        DATABASE,
    ),
    "G04-R01": related(
        [
            "Chat imports and renders the existing InlineQuizCard and submits through the F6 assessment-attempt endpoint; it defines no second quiz loader or answer protocol.",
        ],
        "The embedded Chat question behaves like the same real quiz resource used in Learning Space.",
        "F6-T01 remains the sole owner of quiz generation, question identity and server attempt creation. F7-T04 supplies only the compact conversation placement and verified compatibility.",
        FOCUSED,
        E2E,
    ),
    "G04-R02": related(
        [
            "Correctness, correct answer, explanation and source feedback are rendered only from the F6 server response; Chat contains no client-side scoring or answer disclosure logic.",
        ],
        "After submission, the learner sees immediate authoritative feedback in the compact card; a failed submission keeps the selection available for retry.",
        "F6-T01 remains authoritative for scoring and explanation. F7-T04 verified that the focused Chat neither duplicates nor weakens that contract.",
        FOCUSED,
        E2E,
    ),
    "G04-R03": related(
        [
            "Chat stores no answer history; answer revision continues to create immutable F6 attempts and refreshes from the latest server state.",
        ],
        "The learner may revise an answer without overwriting the earlier attempt; the complete attempt history remains in the quiz resource.",
        "F6-T01 owns immutable attempt history. F7-T04 verifies one new attempt appears only after explicit submission and follow-up drafting creates none.",
        FOCUSED,
        E2E,
        DATABASE,
    ),
    "G04-R04": related(
        [
            "InlineQuizCard follow-up emits the canonical resource, question version, attempt and source context into the Chat composer instead of flattening the question into an untraceable message.",
        ],
        "The learner continues from the result into a prefilled, editable follow-up while the referenced question and source remain identifiable.",
        "F6-T01 owns the question and attempt facts. F7-T04 coordinates their ContextRef transfer into ordinary Chat without rescoring or mastery mutation.",
        FOCUSED,
        E2E,
    ),
    "G04-R05": related(
        [
            "Opening, selecting, attaching, citing, stopping, continuing, following links and creating a resource job call no Chat-owned mastery, profile, wrong-question, review or learning-event write path.",
            "The isolated browser comparison proves only canonical quiz submission adds learning evidence; ordinary Chat actions preserve prior learning and mastery state.",
        ],
        "Using Chat does not silently change mastery. Only submitting the real quiz question produces the expected downstream learning evidence.",
        "F2/F6 learning-event admission and aggregation remain authoritative. F7-T04 only verified that its ordinary actions are non-evidence and its embedded quiz reuses the canonical submission path.",
        FOCUSED,
        E2E,
        DATABASE,
    ),
    "G04-R07": related(
        [
            "Chat accepts only canonical resourceId/questionVersionId quiz identities and contains no production question stem, fixed answer or client-side generator.",
        ],
        "The learner sees a real course-specific generated question; when no canonical question is available, Chat links to the Learning Space generation flow instead of inventing one.",
        "F6-T01 owns dynamic question generation from course, profile and evidence. F7-T04 consumes only the generated identity and statically verifies no fixed production example exists.",
        FOCUSED,
        E2E,
    ),
    "G04-R08": related(
        [
            "Chat renders one compact question and a formal /workspace/resources/quizzes/:resourceId link; it stores no quiz-group content, navigation strip or local attempt history.",
        ],
        "The learner answers the immediate question in Chat and opens the full quiz, versions and history in Learning Space when deeper practice is needed.",
        "F6-T01 and F5 resource history retain ownership of the complete quiz workspace. F7-T04 verifies the compact embedding and separate formal route.",
        FOCUSED,
        E2E,
    ),
    "G12-R04": related(
        [
            "Canonical messages and streams persist honest status, checkpoint, input and source facts for later audit, while the current right rail avoids fabricated candidates, disagreements or validation claims.",
        ],
        "The learner can inspect the answer status and supporting inputs now; a complete multi-Agent audit is not falsely presented before its dedicated task.",
        "F7-T05 remains the sole owner of the complete public Agent responsibility, candidate, disagreement, validation, revision and decision presentation. F7-T04 provides compatible factual checkpoints only.",
        FOCUSED,
        E2E,
        NO_EXTERNAL,
    ),
    "G12-R05": related(
        [
            "The chat API and stream use approved response fields, and Chat.vue/IncrementalMarkdownRenderer.vue expose no prompt, API key, private reasoning, reasoning_content, chain-of-thought or raw-log surface.",
        ],
        "The learner sees useful processing status and sources without internal prompts, credentials or private model reasoning.",
        "The approved product decision interprets detailed process as a public factual summary. F7-T05 owns the expanded summary, while F7-T04 enforces the privacy boundary on every current response and error state.",
        FOCUSED,
        E2E,
        IMPECCABLE,
        NO_EXTERNAL,
    ),
    "G12-R07": related(
        [
            "frontend/src/stores/chat.js and frontend/src/api/stream.js use canonical message IDs and stream checkpoints for incremental chunks, replay replacement, stop, continue and persisted recovery.",
            "stream_api.py centralizes completion persistence so reconnect or continue does not duplicate the user message or already received answer content.",
        ],
        "The learner sees the answer arrive incrementally, can stop it, return to the saved partial answer and continue to completion without duplicate messages.",
        "F7-T04 owns the real streaming and checkpoint mechanics. F7-T05 may attach public Agent stages later but cannot replace or expose private stream internals.",
        FOCUSED,
        E2E,
        VISUAL,
        IMPECCABLE,
    ),
}


def append_unique(current: list[str], additions: list[str]) -> list[str]:
    return list(dict.fromkeys([*current, *additions]))


def main() -> None:
    matches = list(LEDGER_DIR.glob("F7-T04_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F7-T04 ledger, found {len(matches)}")
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

    primary_ids = [
        entry["atomic_requirement_id"] for entry in ledger["entries"] if entry["role"] == "primary"
    ]
    related_ids = [
        entry["atomic_requirement_id"] for entry in ledger["entries"] if entry["role"] == "related"
    ]
    batch = {
        "id": "F7-T04-FINAL-REALIZATION",
        "status": "VERIFIED",
        "atoms": [*primary_ids, *related_ids],
        "direct_atoms": primary_ids,
        "related_atoms": related_ids,
        "files": [
            "app/database.py",
            "app/migrations.py",
            "app/chat_api.py",
            "app/main.py",
            "stream_api.py",
            "frontend/src/api/chat.js",
            "frontend/src/api/stream.js",
            "frontend/src/stores/chat.js",
            "frontend/src/views/Chat.vue",
            "frontend/src/components/IncrementalMarkdownRenderer.vue",
            "tests/test_f7_t04_chat_api.py",
            "tests/test_f7_t04_chat_stream.py",
            "tests/test_f7_t04_chat_frontend_contract.py",
            "scripts/e2e_f7_t04_chat.py",
            "scripts/update_f7_t04_atomic_ledger.py",
            "scripts/finalize_f7_t04_atomic_realization.py",
            BROWSER_REPORT,
            BROWSER_MANIFEST,
            SUMMARY,
        ],
        "verification": [FOCUSED, BUILD, E2E, VISUAL, IMPECCABLE, DATABASE, NO_EXTERNAL, DIFF],
        "protection_contracts": [
            "F6-T01 retains ownership of quiz generation, scoring and immutable attempts",
            "F7-T02 retains ownership of canonical document reading and exact source locations",
            "F7-T05 retains ownership of unified sources and the complete public Agent audit",
            "complete resources remain in Learning Space and Chat stores compact links only",
            "ordinary Chat, attachment, source and resource-link actions never write mastery evidence",
            "private reasoning, prompts, keys and raw logs never reach the client",
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
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F7-T04")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F7-T04",
        entries=expected,
    )
    failures.extend(validate_realization(ledger, expected))
    if failures:
        raise RuntimeError(f"F7-T04 atomic realization gate failed: {failures}")
    print(f"Updated and validated {len(actual_ids)} F7-T04 atomic realizations: {ledger_path}")


if __name__ == "__main__":
    main()
