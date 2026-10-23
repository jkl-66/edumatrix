from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / (
    "outputs/原系统融合重构执行/evidence/context_recovery/atomic_requirement_ledgers/"
    "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION/"
    "F7-T04_88ADBA923D50E1E74CF0ED50B7C9BBFA7EFD7C1280F3E1E92300D9803695D985.json"
)


BATCHES = {
    "impeccable-visual-polish": {
        "G12-R03": [
            "Impeccable polish replaced the failure callout's thick colored side accent with the existing neutral border token, keeping the sanitized failure copy and recovery action as the visual signal.",
        ],
        "G12-R06": [
            "Impeccable polish kept attachment progress text, icons and actions stable while removing the nonessential width transition from the two-pixel progress indicator.",
        ],
        "G12-R07": [
            "Impeccable polish removed the nonessential width transition from answer streaming progress without changing canonical incremental content, stop or continue behavior.",
        ],
        "G20-R05": [
            "The bounded visual polish stays inside the focused Chat surface and preserves the restrained fog-white, white and ink-grey desktop system without restoring any legacy workbench.",
        ],
    },
    "inline-quiz-focus-fix": {
        "G04-R06": ["frontend/src/views/Chat.vue now opens quiz-context deep links at the top of the message scroller so the compact canonical InlineQuizCard is the first actionable content instead of being pushed below message history."],
        "G04-R04": ["The quiz-follow-up entry preserves the existing conversation and composer context while keeping the referenced question visible at entry."],
        "G20-R05": ["The focus fix stays inside the single focused Chat message scroller and does not restore a quiz workbench."],
        "G04-R01": ["scripts/e2e_f7_t04_chat.py now clicks the visible option label used by real students rather than the intentionally hidden radio input."],
        "G04-R02": ["The corrected browser interaction continues to wait for canonical server correctness and explanation feedback."],
    },
    "browser-e2e-added": {
        "G04-R06": ["scripts/e2e_f7_t04_chat.py loads the canonical InlineQuizCard, submits one server-scored answer and converts a follow-up into a preserved Chat draft."],
        "G12-R01": ["The dedicated browser E2E exercises real Markdown upload and preseeded PDF, DOCX and image attachment evidence inside one owner-scoped conversation."],
        "G12-R02": ["The dedicated browser E2E sends only a ready parsed attachment and verifies the answer completes through the canonical persisted stream path."],
        "G12-R03": ["The dedicated browser E2E renders partial and retryable failure reasons, confirms a partial result and retries the failed document without losing other state."],
        "G12-R06": ["The dedicated browser E2E covers ready, partial-failed, retryable-failed and removed attachment states with explicit actions and refreshable server state."],
        "G12-R08": ["The dedicated browser E2E verifies the context, source, attachment, return-path and compact resource evidence rails."],
        "G20-R05": ["The dedicated browser E2E asserts the focused three-column Chat workspace and formal Learning Space resource destinations."],
        "G20-R07": ["The dedicated browser E2E exercises one document-and-image-capable /learn conversation surface at both required desktop viewports."],
        "G21-R04": ["The dedicated browser E2E carries course, knowledge-point and source context through the answer and verifies protected learning/source state before quiz evidence."],
        "G22-R08": ["The dedicated browser E2E creates a completed answer first, then explicitly creates one handout link and verifies no implicit resource generation."],
        "G04-R01": ["The dedicated browser E2E uses the canonical F6 InlineQuizCard and assessment-attempt endpoint rather than a Chat-owned answer path."],
        "G04-R02": ["The dedicated browser E2E waits for server-owned correctness and explanation feedback from InlineQuizCard."],
        "G04-R03": ["The dedicated browser E2E verifies one immutable assessment attempt is added only after explicit quiz submission."],
        "G04-R04": ["The dedicated browser E2E converts the canonical quiz result and user follow-up into the Chat composer without creating another attempt."],
        "G04-R05": ["The dedicated browser E2E compares learning events, profile snapshots, source counts and mastery before and after ordinary Chat actions."],
        "G04-R07": ["The dedicated browser E2E loads a generated canonical quiz resource and its real question version instead of a fixed production example."],
        "G04-R08": ["The dedicated browser E2E keeps a visible formal full-quiz link while only one compact question is embedded in Chat."],
        "G12-R04": ["The dedicated browser E2E checks only honest answer status, counts, sources and recovery states and makes no complete F7-T05 Agent-audit claim."],
        "G12-R05": ["The dedicated browser E2E collects browser diagnostics and external-request evidence without exposing prompts, keys, private reasoning or raw logs."],
        "G12-R07": ["The dedicated browser E2E exercises normal streaming, manual stop, persisted stopped state, continue and completed recovery."],
    },
    "focused-chat-ui": {
        "G04-R06": [
            "frontend/src/views/Chat.vue reuses the canonical compact InlineQuizCard when a real quiz resource and question version are present, while full quiz navigation stays in Learning Space.",
        ],
        "G12-R01": [
            "The focused Chat composer exposes PDF, PPTX, DOCX, Markdown/text and image attachment upload through the canonical owner-scoped store.",
        ],
        "G12-R02": [
            "The composer keeps parsing attachments visible, disables send with a concrete reason and submits only canonical sendable attachment IDs.",
        ],
        "G12-R03": [
            "Attachment rows render server stages, summaries, warnings and sanitized failures while preserving the draft and other successful attachments.",
        ],
        "G12-R06": [
            "The UI renders queued, parsing, ready, partial-failed, retryable-failed and removed states with text, icon, progress and explicit per-item actions.",
        ],
        "G12-R08": [
            "The right evidence rail renders frozen ContextRefs, attachment locators, canonical sources, return paths and compact Learning Space resource links.",
        ],
        "G20-R05": [
            "frontend/src/views/Chat.vue is reduced to one focused conversation workspace; legacy quiz, code and web-search tabs redirect to their formal modules.",
        ],
        "G20-R07": [
            "Document and image context share the same /learn composer without adding another route or provider configuration surface.",
        ],
        "G21-R04": [
            "Structured course, knowledge-point, resource, source and attempt context remains visible and is sent through the canonical ContextRef protocol with a return path.",
        ],
        "G22-R08": [
            "Completed answers offer a separate explicit handout, mind-map or quiz action and show only compact Learning Space job links in Chat.",
        ],
        "G04-R01": [
            "The embedded question uses the existing InlineQuizCard and F6 server attempt endpoint rather than a Chat-owned answer path.",
        ],
        "G04-R02": [
            "Immediate correctness and explanation remain rendered from the F6 server response inside InlineQuizCard.",
        ],
        "G04-R03": [
            "Answer revision remains the existing immutable F6 attempt behavior; Chat stores no local answer history.",
        ],
        "G04-R04": [
            "Quiz follow-up query parameters are converted into a preserved draft and structured resource/attempt/source context for the focused answer path.",
        ],
        "G04-R05": [
            "Opening, selecting, attaching, citing, generating a resource or following a Chat link adds no client-side mastery or learning-event write.",
        ],
        "G04-R07": [
            "The Chat UI contains no production quiz stem or answer and only renders a question loaded from a canonical resource identity.",
        ],
        "G04-R08": [
            "The complete quiz workbench and history remain at /workspace/resources/quizzes/:resourceId; Chat carries only one compact card and deep links.",
        ],
        "G12-R04": [
            "The right rail shows only honest answer status, checkpoints, inputs and sources; the complete public Agent audit remains owned by F7-T05.",
        ],
        "G12-R05": [
            "The focused Chat template contains no prompt, key, private-reasoning or raw-log presentation surface.",
        ],
        "G12-R07": [
            "Streaming answers render incrementally with visible stop, continue, reconnect failure and persisted partial-content states.",
        ],
    },
    "resource-action-tests-added": {
        "G22-R08": [
            "tests/test_f7_t04_chat_api.py defines isolated API coverage for answer-first explicit resource generation, idempotent replay, stale-state rejection and compact Learning Space links.",
        ],
        "G12-R08": [
            "The resource-action tests cover canonical source, knowledge-point and profile requirements plus the absence of full resource content in the persisted Chat message payload.",
        ],
        "G21-R04": [
            "The tests compare owner learning-event, profile-snapshot and mastery state before and after resource-job creation.",
        ],
        "G04-R05": [
            "The tests explicitly protect the rule that resource generation itself does not mutate mastery or create learning events.",
        ],
        "G04-R06": [
            "The tests keep inline quiz interaction separate from resource-job creation and make no completion claim for the pending InlineQuizCard UI.",
        ],
        "G04-R07": [
            "The tests require a canonical knowledge point, current profile and source reference instead of a fixed production question.",
        ],
        "G04-R08": [
            "The tests require quiz history and content to remain in the Learning Space resource job while Chat stores one compact link.",
        ],
    },
    "chat-resource-action-foundation": {
        "G22-R08": [
            "app/chat_api.py adds an explicit post-answer resource action that reuses the existing single-resource GenerationJob protocol; frontend/src/api/chat.js and frontend/src/stores/chat.js call it only after a completed answer and keep the full resource in Learning Space.",
        ],
        "G12-R08": [
            "The resource action derives course, knowledge point, profile snapshot and canonical sourceRef IDs from the completed owner-scoped message, then stores only a compact generation-job link on the assistant message.",
        ],
        "G21-R04": [
            "Generated resources are linked to /workspace/resources/bundles/:jobId and no ordinary chat, attachment or source-reference action writes learning evidence.",
        ],
        "G20-R05": [
            "The explicit action creates a formal Learning Space resource job instead of restoring a Chat quiz, code or search workbench.",
        ],
        "G20-R07": [
            "The resource action remains inside the existing /learn conversation entry and adds no new multimodal route or provider configuration.",
        ],
        "G04-R01": [
            "Quiz generation uses the canonical F2/F6 resource job and does not add a second Chat-owned quiz loader, answer or scoring protocol.",
        ],
        "G04-R02": [
            "The resource action stores no correctness, answer or explanation data in Chat; F6 server-side scoring remains authoritative.",
        ],
        "G04-R03": [
            "Creating a quiz resource does not create or overwrite an attempt; immutable F6 attempt history remains unchanged.",
        ],
        "G04-R04": [
            "The generated resource link preserves the completed message and canonical source context for later question follow-up without flattening the resource into Chat text.",
        ],
        "G04-R05": [
            "Creating a resource job does not write mastery, profile, wrong-question, review or learning-event state.",
        ],
        "G04-R06": [
            "The explicit quiz action creates only the canonical quiz resource and compact link; the required inline single-question interaction remains owned by the forthcoming Chat UI reuse of InlineQuizCard.",
        ],
        "G04-R07": [
            "The action requires a current knowledge point, latest owner profile snapshot and canonical source refs; it contains no hardcoded production question or answer.",
        ],
        "G04-R08": [
            "Quiz jobs and their full content remain in Learning Space, while Chat persists only the compact generation-job link and no quiz-group history.",
        ],
    },
    "frontend-store-canonical": {
        "G12-R01": [
            "frontend/src/stores/chat.js now loads owner-scoped conversations from the server and drives PDF/PPTX/DOCX/text/image attachment upload and parsing through the canonical chat API.",
        ],
        "G12-R02": [
            "The chat store blocks selected attachments that are not sendable, preserves one idempotency key for uncertain message retries and starts streaming only after createChatMessage returns a persisted user/assistant pair.",
        ],
        "G12-R03": [
            "The chat store renders its future attachment UI from server stage, progress, warnings and sanitized failure objects, preserves successful attachments and refreshes the conversation after uncertain failures.",
        ],
        "G12-R06": [
            "The chat store keeps queued, parsing, ready, partial_failed, failed_retryable and removed states with lock-version actions, explicit partial confirmation, retry, removal, selection and refresh recovery.",
        ],
        "G12-R08": [
            "The chat store restores canonical messages, attachment locators, ContextRefs, sourceRefs, resourceLinks and return context from the server rather than localStorage.",
        ],
        "G20-R05": [
            "The chat store has one canonical sendMessage path and ignores the removed legacy mode/images/document workbench parameters in its temporary compatibility wrapper.",
        ],
        "G20-R07": [
            "The chat store unifies document and image uploads inside the existing conversation workflow without creating another route or client-side provider configuration.",
        ],
        "G21-R04": [
            "sendMessage accepts structured ContextRefs and returnTo, freezes them through the canonical message API and never writes learning evidence.",
        ],
        "G22-R08": [
            "The store creates and streams an answer first; it stores only compact resourceLinks returned by the answer and exposes no implicit GenerationJob action.",
        ],
        "G12-R04": [
            "The store preserves honest progress/checkpoint/source facts and leaves complete public Agent audit presentation to F7-T05.",
        ],
        "G12-R05": [
            "The store consumes an approved SSE/message field set and never persists or renders prompts, keys, private reasoning or raw logs.",
        ],
        "G12-R07": [
            "The store handles incremental chunks, replay replacement, checkpoints, completion, stop, continue, provider failure, reconnect refresh and current lock versions without duplicating canonical messages.",
        ],
        "G04-R01": [
            "The canonical store does not implement a second quiz loader or local quiz state; the later Chat card must reuse the F6 InlineQuizCard contract.",
        ],
        "G04-R02": [
            "The canonical store contains no client-side scoring, answer disclosure or explanation synthesis.",
        ],
        "G04-R03": [
            "The canonical store contains no local answer history and cannot overwrite F6 immutable attempts.",
        ],
        "G04-R04": [
            "Structured ContextRefs and return paths remain available for quiz follow-up without flattening the question into local chat text.",
        ],
        "G04-R05": [
            "The canonical store calls no mastery, profile, wrong-question, review or learning-event API during open, attach, ask, stop or continue actions.",
        ],
        "G04-R07": [
            "The canonical store contains no production question stem, answer or client-side question generator.",
        ],
        "G04-R08": [
            "The canonical store persists only compact message resourceLinks and creates no Chat-owned quiz group or attempt history.",
        ],
    },
    "frontend-api-foundation": {
        "G12-R01": [
            "frontend/src/api/chat.js exposes the canonical owner-scoped conversation and attachment upload APIs for PDF, PPTX, DOCX, Markdown/text and image inputs.",
        ],
        "G12-R02": [
            "frontend/src/api/chat.js keeps upload, parse, partial confirmation and message creation as explicit ordered calls, while frontend/src/api/stream.js starts canonical streaming only from a persisted user_message_id.",
        ],
        "G12-R03": [
            "frontend/src/api/chat.js returns the server attachment object from parse/confirm/remove operations so the UI can render the persisted stage, warnings and sanitized failure state rather than inventing local progress.",
        ],
        "G12-R06": [
            "frontend/src/api/chat.js carries attachment lockVersion through parse, partial confirmation and removal so stale UI actions cannot overwrite newer server state.",
        ],
        "G12-R08": [
            "frontend/src/api/chat.js loads complete canonical conversations and creates messages through the persisted context protocol; frontend/src/api/stream.js sends only user_message_id for answer streaming.",
        ],
        "G20-R05": [
            "frontend/src/api/stream.js adds a focused streamCanonicalChat path that cannot select legacy quiz, code or web-search workbench modes.",
        ],
        "G20-R07": [
            "frontend/src/api/chat.js keeps document and image attachment handling inside the existing chat API exported by frontend/src/api/index.js.",
        ],
        "G21-R04": [
            "frontend/src/api/chat.js preserves ContextRef and return-path handling inside canonical message creation and conversation recovery without introducing a second client truth source.",
        ],
        "G22-R08": [
            "frontend/src/api/stream.js streams the persisted answer first and does not expose any implicit resource-generation request in the canonical body.",
        ],
        "G12-R04": [
            "The frontend API foundation preserves structured stream events for the later F7-T05 public audit UI without adding fabricated Agent-process fields.",
        ],
        "G12-R05": [
            "The canonical frontend API surface sends identifiers, user content and lock versions only; it adds no prompt, key, private-reasoning or raw-log field.",
        ],
        "G12-R07": [
            "frontend/src/api/stream.js centralizes SSE parsing for legacy compatibility and canonical user_message_id streams while retaining abort and bounded server/network retry behavior.",
        ],
        "G04-R01": [
            "The frontend chat API foundation does not introduce a second quiz fetch, answer or scoring protocol; F6-T01 remains authoritative for interactive questions.",
        ],
        "G04-R02": [
            "The frontend chat API foundation does not implement client-side correctness or explanation data and therefore preserves server-side F6 scoring ownership.",
        ],
        "G04-R03": [
            "The frontend chat API foundation does not add local answer persistence or overwrite F6 immutable attempt history.",
        ],
        "G04-R04": [
            "Canonical message creation remains able to carry a structured ContextRef for later quiz follow-up without flattening a quiz into unlocatable text.",
        ],
        "G04-R05": [
            "The frontend chat API foundation does not call any mastery, profile, wrong-question, review or learning-event endpoint.",
        ],
        "G04-R07": [
            "The frontend chat API foundation contains no production quiz stem, answer or local quiz generator.",
        ],
        "G04-R08": [
            "The frontend chat API foundation adds no quiz-group storage to Chat and leaves canonical quiz resources and history under the F6 learning-space protocol.",
        ],
    },
    "backend-foundation": {
        "G12-R01": [
            "app/database.py defines owner-scoped DBChatConversation, DBChatAttachment and DBChatMessage records; app/chat_api.py accepts PDF, PPTX, DOCX, Markdown/text and common image uploads without promoting them to canonical course content.",
            "app/migrations.py registers additive migration 20260815_073 and app/main.py exposes the focused /api/v1/chat router.",
        ],
        "G12-R02": [
            "app/chat_api.py separates upload from parse, validates sendable terminal states, freezes attachment parse versions in the user message, and creates the user/assistant pair idempotently.",
        ],
        "G12-R03": [
            "app/chat_api.py persists stage, progress, warnings, sanitized failure code/message and retryability while preserving other attachments and the conversation.",
        ],
        "G12-R06": [
            "app/database.py and app/chat_api.py implement queued, parsing, ready, partial_failed, failed and removed states with optimistic lock versions, partial-result confirmation and terminal removal.",
        ],
        "G12-R08": [
            "app/chat_api.py freezes parser version, parse version, source hash, locations, resolved ContextRefs and return path on canonical messages for later stream/source/resource linking.",
        ],
        "G20-R07": [
            "app/chat_api.py provides one /api/v1/chat attachment protocol for document and image context inside the existing /learn conversation entry.",
        ],
        "G21-R04": [
            "app/chat_api.py validates owner/course-scoped ContextRef objects and stores resolved source and return context without creating learning evidence.",
        ],
        "G22-R08": [
            "app/chat_api.py creates a queued assistant message only after the student's question is stored; full resource generation remains a separate explicit later action.",
        ],
        "G12-R04": [
            "app/chat_api.py stores structured stream checkpoints and source context needed by F7-T05 without claiming a completed public Agent audit.",
        ],
        "G12-R05": [
            "The new chat persistence/API response contains only approved message, attachment, source, resource-link and checkpoint fields; it does not expose prompts, secrets, private reasoning or raw logs.",
        ],
        "G12-R07": [
            "app/chat_api.py supplies begin, checkpoint persistence, completion, failure, stop and continue helpers for the existing stream_api.py integration path.",
        ],
    },
    "stream-integration": {
        "G12-R01": [
            "stream_api.py converts only owner-scoped parsed image attachments to model image inputs and includes parsed PDF/PPTX/DOCX/Markdown/text content in the canonical answer prompt.",
        ],
        "G12-R02": [
            "POST /api/stream/chat accepts user_message_id and loads the already frozen message/attachment context; canonical requests cannot substitute client payload images, document IDs or slash-command modes.",
        ],
        "G12-R03": [
            "stream_api.py now reports deterministic-mode and provider OCR failures as unavailable/failed instead of fabricating successful image contents.",
        ],
        "G12-R08": [
            "app/chat_api.py resolves current source quotes against frozen parser/content versions; stream_api.py persists the same approved source refs on the completed assistant message and returns no full resource body.",
        ],
        "G20-R05": [
            "Canonical user_message_id requests are forced through the focused answer path and ignore legacy matrix, quiz, code, peer-PK and slash-command workbench switching.",
        ],
        "G20-R07": [
            "The canonical /learn stream uses the unified attachment protocol for text and image context and keeps multimodal behavior inside the existing conversation entry.",
        ],
        "G21-R04": [
            "Canonical answers consume frozen ContextRefs and return paths without writing profile, mastery, review, wrong-question or learning-event state.",
        ],
        "G22-R08": [
            "The canonical stream answers the question first, persists only answer/source/link fields, returns an empty resource_links list by default and never invokes resource generation implicitly.",
        ],
        "G12-R04": [
            "The canonical stream records honest answer/checkpoint/source facts for later F7-T05 use while exposing no fabricated Agent deliberation.",
        ],
        "G12-R05": [
            "The canonical prompt explicitly forbids prompts, keys, private reasoning and raw logs; SSE responses use an approved field whitelist and sanitized failure messages.",
        ],
        "G12-R07": [
            "The canonical stream centralizes begin, periodic checkpoints, completion, failure, stop and reconnect replay; completed messages replay without another model call and stopped messages are never overwritten as failed.",
        ],
    },
}

VERIFICATION_BATCHES = {
    "manual-visual-review-pass": {
        atom_id: [
            "Codex manually reviewed all 8 post-polish screenshots at 1440x900 and 1366x768: the focused three-column hierarchy, attachment states, error recovery, empty state, stream recovery, compact inline quiz, source rail and explicit resource links remain readable and coherent with no visible overlap, clipping, forbidden palette regression or complete resource workbench inside Chat."
        ]
        for atom_id in (
            "G04-R01", "G04-R02", "G04-R03", "G04-R04", "G04-R05", "G04-R06", "G04-R07", "G04-R08",
            "G12-R01", "G12-R02", "G12-R03", "G12-R04", "G12-R05", "G12-R06", "G12-R07", "G12-R08",
            "G20-R05", "G20-R07", "G21-R04", "G22-R08",
        )
    },
    "browser-e2e-post-polish-pass": {
        atom_id: [
            "The post-Impeccable dual-desktop browser rerun completed at 2026-08-15T17:26:59+0800 with status passed, 8 regenerated screenshots, 5 visual contracts, no HTTP, failed-request, page, console, external-request or external-model errors, SQLite integrity ok and 0 foreign-key violations."
        ]
        for atom_id in (
            "G04-R01", "G04-R02", "G04-R03", "G04-R04", "G04-R05", "G04-R06", "G04-R07", "G04-R08",
            "G12-R01", "G12-R02", "G12-R03", "G12-R04", "G12-R05", "G12-R06", "G12-R07", "G12-R08",
            "G20-R05", "G20-R07", "G21-R04", "G22-R08",
        )
    },
    "impeccable-visual-review-pass": {
        "G12-R03": [
            "The bounded post-fix Impeccable detector returned an empty finding set for Chat.vue and IncrementalMarkdownRenderer.vue, confirming the visible failure treatment no longer uses a thick colored side accent.",
        ],
        "G12-R06": [
            "The bounded post-fix Impeccable detector returned an empty finding set, confirming attachment progress no longer animates a layout property.",
        ],
        "G12-R07": [
            "The bounded post-fix Impeccable detector returned an empty finding set, confirming stream progress no longer animates a layout property.",
        ],
        "G20-R05": [
            "The bounded post-fix Impeccable detector returned an empty finding set for the focused Chat surface and its incremental renderer.",
        ],
    },
    "browser-e2e-clean-rerun-pass": {
        atom_id: [
            "The final clean dual-desktop browser rerun completed at 2026-08-15T17:11:37+0800 with status passed, 8 screenshots, 5 visual contracts, no HTTP, failed-request, page, console, external-request or external-model errors, SQLite integrity ok and 0 foreign-key violations."
        ]
        for atom_id in (
            "G04-R01", "G04-R02", "G04-R03", "G04-R04", "G04-R05", "G04-R06", "G04-R07", "G04-R08",
            "G12-R01", "G12-R02", "G12-R03", "G12-R04", "G12-R05", "G12-R06", "G12-R07", "G12-R08",
            "G20-R05", "G20-R07", "G21-R04", "G22-R08",
        )
    },
    "browser-e2e-pass": {
        "G04-R06": ["The dedicated dual-desktop E2E loaded one canonical InlineQuizCard, selected an option through the visible label, submitted it, received server feedback and kept the complete quiz in Learning Space."],
        "G12-R01": ["The dedicated E2E passed real Markdown upload plus PDF partial, DOCX retryable-failure and removed-image presentation in the owner-scoped Chat conversation."],
        "G12-R02": ["The dedicated E2E passed parse-before-send, a persisted attachment-backed question and canonical deterministic streaming completion."],
        "G12-R03": ["The dedicated E2E passed visible partial and failed reasons, partial confirmation, failed-document retry and preserved draft/other attachment state."],
        "G12-R06": ["The dedicated E2E passed ready, partial-failed, retryable-failed and removed attachment states with explicit actions and stable desktop geometry."],
        "G12-R08": ["The dedicated E2E passed course, knowledge-point, source, attachment, return-path and compact resource evidence display."],
        "G20-R05": ["The dedicated E2E passed the single focused three-column Chat workspace, empty conversation state and formal Learning Space resource destination."],
        "G20-R07": ["The dedicated E2E passed the same multimodal /learn conversation surface at 1440x900 and 1366x768 with no alternate route or provider surface."],
        "G21-R04": ["The dedicated E2E passed structured course/knowledge/source context while ordinary Chat actions left learning, profile, mastery and source state unchanged."],
        "G22-R08": ["The dedicated E2E passed answer-first behavior, explicit handout creation and one compact Learning Space job link without implicit generation."],
        "G04-R01": ["The dedicated E2E passed the canonical F6 InlineQuizCard and assessment-attempt endpoint inside Chat."],
        "G04-R02": ["The dedicated E2E passed immediate server-owned correctness and explanation feedback."],
        "G04-R03": ["The dedicated E2E passed one immutable new assessment attempt on submission and no second attempt from follow-up drafting."],
        "G04-R04": ["The dedicated E2E passed a result-aware quiz follow-up that populated the Chat composer while preserving the canonical resource context."],
        "G04-R05": ["The dedicated E2E proved ordinary Chat, attachment, stop/continue and resource-link actions did not change learning events, profile snapshots or mastery; only canonical quiz submission created evidence."],
        "G04-R07": ["The dedicated E2E loaded a generated canonical resource and real question version with no fixed production question or answer."],
        "G04-R08": ["The dedicated E2E kept one compact embedded question and a separate visible full-quiz route to Learning Space."],
        "G12-R04": ["The dedicated E2E displayed only honest answer status, received characters, sources and recovery state and made no complete F7-T05 audit claim."],
        "G12-R05": ["The dedicated E2E completed with no sensitive-field exposure, no external requests and no external model call."],
        "G12-R07": ["The dedicated E2E passed normal streaming, a manually stopped local stream, persisted stopped state, continue and completed recovery."],
    },
    "browser-e2e-sixth-run-partial": {
        atom_id: [
            "The sixth browser run confirmed the archive response completes without ERR_ABORTED and again passed all preceding Chat, attachment, resource and recovery checks. It stopped only because the runner assumed the post-archive active conversation must be a specific remaining title, while either remaining conversation is valid; the next rerun waits for any recovered message conversation before opening the explicit quiz deep link."
        ]
        for atom_id in (
            "G04-R01", "G04-R02", "G04-R03", "G04-R04", "G04-R05", "G04-R06", "G04-R07", "G04-R08",
            "G12-R01", "G12-R02", "G12-R03", "G12-R04", "G12-R05", "G12-R06", "G12-R07", "G12-R08",
            "G20-R05", "G20-R07", "G21-R04", "G22-R08",
        )
    },
    "browser-e2e-fifth-run-near-pass": {
        atom_id: [
            "The fifth browser run completed all required Chat, attachment, explicit-resource, stop/continue, empty-state, inline-quiz, follow-up, dual-viewport, visual and isolated-database checks. All HTTP responses were successful, browser/page/console/external-model checks were clean, and the only remaining runner failure was an ERR_ABORTED diagnostic emitted because the test navigated immediately after an archive endpoint that the server log confirms returned 200; the final rerun will wait for archive and conversation recovery to settle without weakening the diagnostic gate."
        ]
        for atom_id in (
            "G04-R01", "G04-R02", "G04-R03", "G04-R04", "G04-R05", "G04-R06", "G04-R07", "G04-R08",
            "G12-R01", "G12-R02", "G12-R03", "G12-R04", "G12-R05", "G12-R06", "G12-R07", "G12-R08",
            "G20-R05", "G20-R07", "G21-R04", "G22-R08",
        )
    },
    "browser-e2e-fourth-run-partial": {
        atom_id: [
            "The fourth browser run passed attachment recovery, real upload, explicit resource generation, protected-state comparison, stop/continue recovery, empty-conversation behavior and the initial inline-quiz visual contract. It stopped because the test clicked the intentionally pointer-transparent radio input instead of its visible option label; the screenshot also showed quiz deep links entering at message-bottom scroll, which is being corrected before the required rerun."
        ]
        for atom_id in (
            "G04-R01", "G04-R02", "G04-R03", "G04-R04", "G04-R05", "G04-R06", "G04-R07", "G04-R08",
            "G12-R01", "G12-R02", "G12-R03", "G12-R04", "G12-R05", "G12-R06", "G12-R07", "G12-R08",
            "G20-R05", "G20-R07", "G21-R04", "G22-R08",
        )
    },
    "browser-e2e-third-run-partial": {
        atom_id: [
            "The third browser run passed the focused initial visual contract, partial confirmation, retryable failure, real Markdown upload, canonical answer completion, attachment removal and explicit handout generation; protected learning, profile, mastery and source counts were unchanged before versus after those actions. The run stopped because the test compared post-startup seeded source totals to a pre-startup fixture total, so stop/continue, inline quiz and the second viewport still require the corrected rerun."
        ]
        for atom_id in (
            "G04-R01", "G04-R02", "G04-R03", "G04-R04", "G04-R05", "G04-R06", "G04-R07", "G04-R08",
            "G12-R01", "G12-R02", "G12-R03", "G12-R04", "G12-R05", "G12-R06", "G12-R07", "G12-R08",
            "G20-R05", "G20-R07", "G21-R04", "G22-R08",
        )
    },
    "browser-e2e-second-run-partial": {
        atom_id: [
            "The second browser run reached the real focused Chat, passed the initial 1440x900 visual contract and browser diagnostics, and successfully confirmed the partial attachment through the API; it stopped only because the test expected the combined status line as an exact standalone text, so complete browser evidence is still pending."
        ]
        for atom_id in (
            "G04-R01", "G04-R02", "G04-R03", "G04-R04", "G04-R05", "G04-R06", "G04-R07", "G04-R08",
            "G12-R01", "G12-R02", "G12-R03", "G12-R04", "G12-R05", "G12-R06", "G12-R07", "G12-R08",
            "G20-R05", "G20-R07", "G21-R04", "G22-R08",
        )
    },
    "browser-e2e-first-run-failed": {
        atom_id: [
            "The first dedicated browser run stopped before service/browser acceptance because the generated isolated-fixture script contained an unterminated Markdown string; no product behavior evidence is claimed from this run and a corrected rerun remains required."
        ]
        for atom_id in (
            "G04-R01", "G04-R02", "G04-R03", "G04-R04", "G04-R05", "G04-R06", "G04-R07", "G04-R08",
            "G12-R01", "G12-R02", "G12-R03", "G12-R04", "G12-R05", "G12-R06", "G12-R07", "G12-R08",
            "G20-R05", "G20-R07", "G21-R04", "G22-R08",
        )
    },
    "static-boundary-scan-pass": {
        "G20-R05": ["PowerShell source scan found no legacy quiz, code or web-search workbench identifiers in the focused Chat surface."],
        "G20-R07": ["PowerShell source scan confirmed the positive formal links remain /learn, /knowledge/discover and /workspace/code/:resourceId without another multimodal route."],
        "G12-R05": ["PowerShell source scan found no chain-of-thought, reasoning-content, system-prompt, raw-log or API-key presentation fields."],
        "G12-R07": ["PowerShell source scan confirmed stop, continue and persisted attachment recovery controls remain present without legacy workbench state."],
        "G21-R04": ["PowerShell source scan confirmed canonical context and formal return-link surfaces remain present without client-side learning writes."],
        "G22-R08": ["PowerShell source scan confirmed compact resource-link rendering and explicit resource menu behavior remain present."],
        "G04-R01": ["PowerShell source scan confirmed Chat imports InlineQuizCard and links full quiz navigation to the formal Learning Space route."],
        "G04-R02": ["PowerShell source scan found no client-side correctness, answer checking or scoring implementation."],
        "G04-R03": ["PowerShell source scan found no local message or answer-history truth; the sole localStorage use is a read-only course-title compatibility label."],
        "G04-R05": ["PowerShell source scan found no client-side mastery or scoring write path in the focused Chat surface."],
        "G04-R07": ["PowerShell source scan found no fixed production correct-answer field or local scoring path."],
        "G04-R08": ["PowerShell source scan confirmed the complete quiz target remains /workspace/resources/quizzes/:resourceId."],
    },
    "focused-regression-pass": {
        "G04-R06": ["The combined regression passed the canonical InlineQuizCard integration together with the F6 quiz resource contract."],
        "G12-R01": ["The combined regression passed owner-scoped document and image attachment upload, parsing and canonical Chat integration."],
        "G12-R02": ["The combined regression passed parse-before-send gating, persisted message pairing and idempotent canonical streaming."],
        "G12-R03": ["The combined regression passed sanitized attachment failure, retry and honest multimodal failure behavior."],
        "G12-R06": ["The combined regression passed the attachment state machine, lock versions, partial confirmation, retry and removal behavior."],
        "G12-R08": ["The combined regression passed frozen ContextRefs, source locators, return paths and compact resource links."],
        "G20-R05": ["The combined regression passed the focused canonical answer path while rejecting legacy Chat workbench switching."],
        "G20-R07": ["The combined regression passed one unified document and image conversation path under /learn."],
        "G21-R04": ["The combined regression passed structured context propagation while preserving learning-event and source-of-truth boundaries."],
        "G22-R08": ["The combined regression passed answer-first behavior and explicit resource creation without implicit generation."],
        "G04-R01": ["The F6 protection regression passed the canonical server-owned quiz loader and attempt path reused by Chat."],
        "G04-R02": ["The F6 protection regression passed server-owned correctness, explanation and attempt response behavior."],
        "G04-R03": ["The F6 protection regression passed immutable quiz attempt history and revision behavior."],
        "G04-R04": ["The combined regression preserved structured quiz resource and attempt context for follow-up questions."],
        "G04-R05": ["The combined regression confirmed ordinary Chat, attachment and resource-link actions do not mutate learning evidence."],
        "G04-R07": ["The combined regression preserved dynamic canonical quiz identities and contains no fixed production answer path."],
        "G04-R08": ["The F6 protection regression confirmed full quiz content and history remain owned by Learning Space."],
        "G12-R04": ["The combined regression preserved honest structured checkpoints without claiming the complete F7-T05 Agent audit UI."],
        "G12-R05": ["The combined regression response scans excluded prompts, keys, private reasoning and raw logs."],
        "G12-R07": ["The combined regression passed streaming completion, replay, stop, continue and persisted recovery behavior."],
    },
    "focused-chat-ui-contract-pass": {
        "G04-R06": ["Frontend contract tests and the production build verify the canonical InlineQuizCard is the only embedded quiz surface in Chat."],
        "G12-R01": ["Frontend contract tests verify the five document/image attachment families are exposed through the focused composer; the Vue production build passed."],
        "G12-R02": ["Frontend contract tests verify parse-before-send blocking and preserved retry actions; the Vue production build passed."],
        "G12-R03": ["Frontend contract tests verify sanitized failure, warning and retry rendering; the Vue production build passed."],
        "G12-R06": ["Frontend contract tests verify all required attachment states and actions are present with text labels; the Vue production build passed."],
        "G12-R08": ["Frontend contract tests verify the context, source, attachment, return and compact resource evidence rail; the Vue production build passed."],
        "G20-R05": ["Frontend contract tests reject the legacy Chat quiz/code/search workbenches and verify formal-module redirects; the Vue production build passed."],
        "G20-R07": ["Frontend contract tests verify one multimodal composer remains at /learn; the Vue production build passed."],
        "G21-R04": ["Frontend contract tests verify structured ContextRefs, sources and return paths remain present without learning-event client writes; the Vue production build passed."],
        "G22-R08": ["Frontend contract tests verify answer-first explicit resource actions and compact Learning Space links; the Vue production build passed."],
        "G04-R01": ["Frontend contract tests verify Chat imports the canonical InlineQuizCard and no second quiz-answer protocol."],
        "G04-R02": ["Frontend contract tests find no client-side correctness or answer fields in Chat."],
        "G04-R03": ["Frontend contract tests find no local answer-history truth in Chat."],
        "G04-R04": ["Frontend contract tests verify quiz resource, question version, attempt and follow-up compatibility parameters remain handled."],
        "G04-R05": ["Frontend source review and contract tests find no mastery, profile, wrong-question, review or learning-event mutation call in Chat."],
        "G04-R07": ["Frontend contract tests find no production quiz stem or answer in Chat and require canonical resource loading."],
        "G04-R08": ["Frontend contract tests verify full quiz navigation targets the formal Learning Space quiz route."],
        "G12-R04": ["Frontend contract tests verify only honest processing state and evidence are present, without a complete Agent-audit claim."],
        "G12-R05": ["Frontend contract tests scan the focused Chat source and find no prompt, key, private-reasoning or raw-log presentation fields."],
        "G12-R07": ["Frontend contract tests verify streaming, stop and continue controls; the semantic incremental renderer and Vue production build passed."],
    },
    "resource-action-tests-pass": {
        "G22-R08": [
            "Focused API tests passed for explicit answer-first single-resource generation, idempotent replay, stale lock rejection and compact Learning Space linking.",
        ],
        "G12-R08": [
            "Focused API tests passed for canonical course, knowledge-point, profile and source requirements; the Chat message contains only a compact link and no resource body.",
        ],
        "G21-R04": [
            "The passing test confirmed resource-job creation leaves the owner's learning-event count, profile-snapshot count and mastery fields unchanged.",
        ],
        "G20-R05": [
            "The passing test confirmed the generated quiz is represented by a Learning Space bundle route rather than a Chat-owned quiz workbench.",
        ],
        "G04-R05": [
            "The passing test confirmed explicit resource generation itself creates no learning event and changes no mastery/profile state.",
        ],
        "G04-R06": [
            "The passing test verifies canonical quiz-resource creation while leaving the separate inline single-question interaction pending for the Chat UI batch.",
        ],
        "G04-R07": [
            "The passing test rejects missing knowledge point, profile or canonical source instead of generating from a fixed example.",
        ],
        "G04-R08": [
            "The passing test confirms Chat stores one compact quiz job link while full resource ownership remains in Learning Space.",
        ],
    },
    "frontend-store-check-pass": {
        "G12-R01": [
            "The rewritten server-backed chat store compiled in the production Vue build with 6941 transformed modules.",
        ],
        "G12-R02": [
            "The rewritten store compiled with parse-before-send gating and persisted message-pair streaming intact.",
        ],
        "G12-R03": [
            "The rewritten store compiled with server-derived attachment stage/failure handling and refresh recovery intact.",
        ],
        "G12-R06": [
            "The rewritten store compiled with all attachment terminal states, selection, retry, confirmation, removal and lock-version actions intact.",
        ],
        "G12-R08": [
            "The rewritten store compiled with canonical conversation/message/source/resource-link restoration intact.",
        ],
        "G20-R05": [
            "Production build passed after the store was reduced to one canonical conversation path; the corrected static scan found no local message truth or client-side quiz-scoring fields.",
        ],
        "G20-R07": [
            "Production build passed with one document/image attachment workflow inside the existing chat store.",
        ],
        "G21-R04": [
            "Production build passed with structured ContextRefs and return paths and no learning-event client calls.",
        ],
        "G22-R08": [
            "Production build passed with answer-first streaming and no implicit resource-generation client action.",
        ],
        "G12-R04": [
            "Production build passed while the store retained only honest progress/checkpoint facts for later F7-T05 presentation.",
        ],
        "G12-R05": [
            "Corrected static scan of frontend/src/stores/chat.js passed with none of localStorage, edumatrix_chat_messages, chain_of_thought, reasoning_content, system_prompt, raw_log or client-side answer fields.",
        ],
        "G12-R07": [
            "Production build and corrected static scan passed for incremental chunks, replay, checkpoints, stop, continue and failure recovery.",
        ],
        "G04-R01": [
            "Corrected store scan found no client-side answer fields; F6 remains the interactive quiz owner.",
        ],
        "G04-R02": [
            "Corrected store scan found no correctAnswer/correct_answer or local scoring implementation.",
        ],
        "G04-R03": [
            "Corrected store scan found no localStorage message or answer-history truth.",
        ],
        "G04-R04": [
            "Production build preserves structured ContextRef support for later quiz follow-up integration.",
        ],
        "G04-R05": [
            "Corrected store scan and source review found no mastery/profile/wrong-question/review mutation path in the store.",
        ],
        "G04-R07": [
            "Corrected store scan found no hardcoded production question or answer field.",
        ],
        "G04-R08": [
            "Production build passed without a Chat-owned quiz-group store.",
        ],
    },
    "frontend-store-check-first-run": {
        "G12-R05": [
            "First frontend store verification command used frontend/src/stores/chat.js while already running inside frontend/, so the sensitive/local-truth static scan did not execute; the same command still completed the production build with 6941 transformed modules. The path error is recorded and must be rerun correctly.",
        ],
        "G12-R07": [
            "The first frontend store verification command completed the production build, but its preceding static scan used a duplicated frontend/ path and therefore cannot yet count as complete store verification.",
        ],
        "G20-R05": [
            "The first store verification build passed against the existing Chat caller, while the separate legacy/local-truth scan must be rerun because of the recorded path error.",
        ],
    },
    "frontend-api-build-pass": {
        "G12-R01": [
            "Frontend production build passed with the new canonical conversation and attachment API exported through frontend/src/api/index.js.",
        ],
        "G12-R02": [
            "Frontend production build passed with explicit attachment parse/message creation helpers and the user_message_id canonical stream entry.",
        ],
        "G12-R03": [
            "Frontend production build passed with server attachment-state results preserved for later honest UI rendering.",
        ],
        "G12-R06": [
            "Frontend production build passed with lockVersion-based parse, partial-confirmation and removal calls.",
        ],
        "G12-R08": [
            "Frontend production build passed with canonical conversation recovery and source-context message APIs.",
        ],
        "G20-R05": [
            "Frontend production build passed with streamCanonicalChat separated from legacy workbench mode parameters.",
        ],
        "G20-R07": [
            "Frontend production build passed with the multimodal chat API inside the existing application API surface.",
        ],
        "G21-R04": [
            "Frontend production build passed with canonical message/context APIs and no second client persistence module.",
        ],
        "G22-R08": [
            "Frontend production build passed with the answer-only canonical SSE request body.",
        ],
        "G12-R04": [
            "Frontend production build passed without adding a fabricated Agent audit UI or private-process fields.",
        ],
        "G12-R05": [
            "Frontend production build passed with no prompt, key, private-reasoning or raw-log field in the new API module.",
        ],
        "G12-R07": [
            "Frontend production build passed with centralized abortable SSE parsing for canonical and protected legacy callers.",
        ],
    },
    "stream-lock-version-pass": {
        "G12-R07": [
            "Focused command `python -m pytest -q tests/test_f7_t04_chat_stream.py` passed after SSE progress/checkpoint events began returning the current assistant lock version for reliable stop/continue actions.",
        ],
    },
    "stream-backend-regression": {
        "G12-R01": [
            "Combined isolated-SQLite regression `python -m pytest -q tests/test_f7_t04_chat_api.py tests/test_f7_t04_chat_stream.py tests/test_m5_stream_context.py` passed 21 tests across attachment formats, parsing and canonical streaming.",
        ],
        "G12-R02": [
            "The 21-test regression preserves parse-before-send, idempotent message pairing and persisted user_message_id stream binding.",
        ],
        "G12-R03": [
            "The 21-test regression preserves sanitized attachment failures and honest vision unavailable/failed responses.",
        ],
        "G12-R06": [
            "The 21-test regression preserves all attachment states, lock versions, partial confirmation and terminal removal.",
        ],
        "G12-R08": [
            "The 21-test regression preserves frozen ContextRefs/source refs through completion and replay without changing canonical source counts.",
        ],
        "G20-R05": [
            "The 21-test regression proves canonical messages bypass legacy workbench mode switching while legacy tests continue to pass.",
        ],
        "G20-R07": [
            "The 21-test regression proves one owner-scoped chat protocol handles documents, images and answer streaming.",
        ],
        "G21-R04": [
            "The 21-test regression confirms ordinary chat, source references and stream replay do not create learning events.",
        ],
        "G22-R08": [
            "The 21-test regression confirms ordinary answers complete with no implicit resource generation and replay without a second model call.",
        ],
        "G12-R04": [
            "The 21-test regression preserves structured checkpoint facts for F7-T05 without claiming a completed public audit.",
        ],
        "G12-R05": [
            "The 21-test regression preserves sensitive-field response scans across API and SSE payloads.",
        ],
        "G12-R07": [
            "The 21-test regression verifies begin/checkpoint/complete/fail/stop/continue and completed replay through one canonical stream path.",
        ],
    },
    "stream-tests-first-run": {
        "G12-R07": [
            "First focused stream run `python -m pytest -q tests/test_f7_t04_chat_stream.py tests/test_m5_stream_context.py` produced 15 passed / 1 failed: the canonical branch hit Python local-name shadowing from legacy in-function run_db_op imports before any model call or state mutation; the failure is recorded for correction without weakening assertions.",
        ],
        "G20-R05": [
            "The first focused stream run reached the canonical user_message_id branch before legacy mode processing; execution stopped on the recorded database-runner name-shadowing defect.",
        ],
    },
    "stream-tests-second-run": {
        "G12-R07": [
            "Second focused stream run produced 15 passed / 1 failed after both answer chunks were emitted: completion committed successfully, but the returned SQLAlchemy row was expired and detached before SSE serialization; stream state helpers require refresh-before-return.",
        ],
        "G12-R08": [
            "The second run reached canonical source-bound completion and failed only while serializing the detached completed message, not while resolving or persisting source refs.",
        ],
    },
    "backend-tests-first-run": {
        "G12-R01": [
            "First isolated-SQLite API run: tests/test_f7_t04_chat_api.py produced 4 passed / 1 failed; PDF/text/image attachment paths and owner isolation passed, while one protection-count assertion sampled before startup seed and was corrected without weakening the protection check.",
        ],
        "G12-R02": [
            "First isolated-SQLite API run passed parse-before-send rejection, retry recovery, partial-result confirmation and idempotent message replay scenarios.",
        ],
        "G12-R03": [
            "First isolated-SQLite API run passed sanitized retryable failure and partial failure visibility scenarios.",
        ],
        "G12-R06": [
            "First isolated-SQLite API run passed queued, ready, partial_failed, failed_retryable and removed terminal-state assertions.",
        ],
        "G12-R08": [
            "First isolated-SQLite API run passed frozen attachment/source context recovery; the failed assertion concerned startup seed timing rather than chat source mutation.",
        ],
        "G20-R07": [
            "First isolated-SQLite API run passed Markdown and image attachment handling through the single chat protocol.",
        ],
        "G21-R04": [
            "First isolated-SQLite API run passed owner-scoped conversation recovery and canonical ContextRef freezing without chat-created learning evidence.",
        ],
        "G22-R08": [
            "First isolated-SQLite API run passed canonical queued assistant creation and stop/continue recovery without invoking an external model.",
        ],
        "G12-R05": [
            "First isolated-SQLite API response scan contained none of api_key, chain_of_thought, reasoning_content, system_prompt or raw_log.",
        ],
        "G12-R07": [
            "First isolated-SQLite API run passed queued -> stopped -> queued continuation state transitions.",
        ],
    },
    "backend-tests-pass": {
        "G12-R01": [
            "Fresh isolated-SQLite command `python -m pytest -q tests/test_f7_t04_chat_api.py` passed 5 tests, including Markdown and image upload/parse plus honest legacy-PPT and unsupported-format rejection.",
        ],
        "G12-R02": [
            "The passing API suite proves queued/parsing terminal gating, retry recovery, partial-result confirmation and idempotent message-pair replay.",
        ],
        "G12-R03": [
            "The passing API suite proves sanitized failure code/message, warnings, retryability and preservation of other conversation state.",
        ],
        "G12-R06": [
            "The passing API suite proves queued, ready, partial_failed, failed_retryable and removed state behavior, lock-version checks and terminal raw-byte removal.",
        ],
        "G12-R08": [
            "The passing API suite proves parser/source version locators and canonical ContextRef data survive conversation recovery without mutating source documents or source refs.",
        ],
        "G20-R07": [
            "The passing API suite proves one chat conversation accepts text documents and images through the same owner-scoped protocol.",
        ],
        "G21-R04": [
            "The passing API suite proves course/source ContextRefs are resolved and frozen with a return path while learning-event counts remain unchanged.",
        ],
        "G22-R08": [
            "The passing API suite proves a question creates only a queued answer placeholder; no resource generation or external model call occurs implicitly.",
        ],
        "G12-R04": [
            "The passing API suite preserves structured checkpoints while making no claim that the F7-T05 public Agent audit is complete.",
        ],
        "G12-R05": [
            "The passing API suite recursively scans the response and confirms approved fields do not contain private reasoning, prompts, API keys or raw logs.",
        ],
        "G12-R07": [
            "The passing API suite proves recoverable queued -> stopped -> queued continuation transitions without duplicating messages.",
        ],
    },
    "stream-tests-pass": {
        "G12-R01": [
            "Focused stream tests prove parsed attachment content is used through the canonical message and no client-supplied legacy image/document payload can replace it.",
        ],
        "G12-R02": [
            "Focused stream tests prove user_message_id binds the stream to the persisted canonical message pair and duplicate stream requests replay the same completed answer.",
        ],
        "G12-R03": [
            "tests/test_m5_stream_context.py verifies successful vision output is marked successful while provider failure is explicitly marked as failed and never as a fabricated success.",
        ],
        "G12-R08": [
            "Focused stream tests verify completed assistant source refs remain the frozen canonical refs and resource_links remains compact and empty unless an explicit later action creates a resource.",
        ],
        "G20-R05": [
            "Focused stream tests submit legacy matrix/quiz payload fields alongside user_message_id and prove the canonical answer path ignores workbench switching.",
        ],
        "G20-R07": [
            "Focused stream tests verify the single canonical conversation endpoint serves the multimodal-capable answer path without adding another route.",
        ],
        "G21-R04": [
            "Isolated SQLite protection counts prove canonical streaming does not create learning events or mutate canonical source-document/source-ref counts.",
        ],
        "G22-R08": [
            "Focused stream tests prove ordinary answer completion produces no implicit resource generation and completed replay performs no second model call.",
        ],
        "G12-R04": [
            "Response scans and persisted checkpoints contain only honest answer-stage facts and make no F7-T05 audit-completion claim.",
        ],
        "G12-R05": [
            "Focused response scans contain none of api_key, chain_of_thought, reasoning_content, system_prompt or raw_log.",
        ],
        "G12-R07": [
            "Focused stream tests verify one centralized completion, persisted content, completed replay and no duplicate provider call.",
        ],
    },
}


EXECUTION_BATCHES = {
    "manual-visual-review-pass": {
        "files": [
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/01-focused-chat-1440x900.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/02-attachments-and-resource-link-1440x900.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/03-stop-continue-recovery-1440x900.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/04-empty-conversation-1440x900.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/05-inline-quiz-1440x900.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/06-inline-quiz-feedback-follow-up-1440x900.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/07-focused-chat-1366x768.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/05-inline-quiz-1366x768.png",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": "Passed the bounded manual visual review of every final F7-T04 desktop screenshot.",
        "verification": [
            "Manual review -> 8/8 post-polish screenshots coherent and readable; no visible overlap, clipping, forbidden theme regression or complete workbench inside Chat",
        ],
    },
    "browser-e2e-post-polish-pass": {
        "files": [
            "frontend/src/views/Chat.vue",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/report.json",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/manifest.json",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/01-focused-chat-1440x900.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/02-attachments-and-resource-link-1440x900.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/03-stop-continue-recovery-1440x900.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/04-empty-conversation-1440x900.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/05-inline-quiz-1440x900.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/06-inline-quiz-feedback-follow-up-1440x900.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/07-focused-chat-1366x768.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/05-inline-quiz-1366x768.png",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": (
            "Passed the complete isolated Chat, attachment, recovery, explicit-resource, inline-quiz, "
            "dual-desktop visual and database acceptance after the bounded Impeccable polish."
        ),
        "verification": [
            "python scripts/e2e_f7_t04_chat.py -> status passed at 2026-08-15T17:26:59+0800; 8 screenshots; 5 visual contracts; all error arrays empty; external_model_called false; SQLite integrity ok; 0 foreign-key violations",
        ],
    },
    "impeccable-visual-review-pass": {
        "files": [
            "frontend/src/views/Chat.vue",
            "frontend/src/components/IncrementalMarkdownRenderer.vue",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": "Passed the bounded post-fix Impeccable source review with no findings.",
        "verification": [
            "node C:/Users/iray/.codex/skills/impeccable/scripts/detect.mjs --json frontend/src/views/Chat.vue frontend/src/components/IncrementalMarkdownRenderer.vue -> []",
        ],
    },
    "impeccable-visual-polish": {
        "files": [
            "frontend/src/views/Chat.vue",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": (
            "Applied the bounded Impeccable polish findings: removed two layout-property transitions "
            "and replaced one thick colored side accent with the incumbent neutral border token."
        ),
        "verification": [
            "node C:/Users/iray/.codex/skills/impeccable/scripts/detect.mjs --json frontend/src/views/Chat.vue frontend/src/components/IncrementalMarkdownRenderer.vue -> pre-fix findings: 2 layout-transition warnings and 1 side-tab warning",
        ],
    },
    "browser-e2e-clean-rerun-pass": {
        "files": [
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/report.json",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/manifest.json",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/01-focused-chat-1440x900.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/02-attachments-and-resource-link-1440x900.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/03-stop-continue-recovery-1440x900.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/04-empty-conversation-1440x900.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/05-inline-quiz-1440x900.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/06-inline-quiz-feedback-follow-up-1440x900.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/07-focused-chat-1366x768.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/05-inline-quiz-1366x768.png",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": (
            "Recorded the final clean dual-desktop Chat rerun after the prior successful evidence, "
            "with no browser, network, external-model or isolated-database errors."
        ),
        "verification": [
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/report.json -> status passed at 2026-08-15T17:11:37+0800; 8 screenshots; 5 visual contracts; all error arrays empty; external_model_called false; SQLite integrity ok; 0 foreign-key violations",
        ],
    },
    "browser-e2e-pass": {
        "files": [
            "frontend/src/views/Chat.vue",
            "scripts/e2e_f7_t04_chat.py",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/report.json",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/manifest.json",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/01-focused-chat-1440x900.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/02-attachments-and-resource-link-1440x900.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/03-stop-continue-recovery-1440x900.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/04-empty-conversation-1440x900.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/05-inline-quiz-1440x900.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/06-inline-quiz-feedback-follow-up-1440x900.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/07-focused-chat-1366x768.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/05-inline-quiz-1366x768.png",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": (
            "Passed the complete isolated Chat, attachment, recovery, explicit-resource, inline-quiz, "
            "dual-desktop visual and database acceptance with no browser or external-call errors."
        ),
        "verification": [
            "python scripts/e2e_f7_t04_chat.py -> status passed; 8 screenshots; 5 visual contracts; 0 HTTP/failed-request/page/console/external-request errors; SQLite integrity ok and 0 foreign-key violations",
            "cd frontend; npm run build -> 6931 modules transformed, build passed after quiz-entry focus fix",
        ],
    },
    "browser-e2e-sixth-run-partial": {
        "files": [
            "scripts/e2e_f7_t04_chat.py",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/report.json",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": (
            "Confirmed stable archive completion and stopped only on an invalid assumption about "
            "which remaining conversation becomes active after archive."
        ),
        "verification": [
            "python scripts/e2e_f7_t04_chat.py -> PARTIAL: archive response settled without aborted request; post-archive specific-title locator timed out",
        ],
    },
    "browser-e2e-fifth-run-near-pass": {
        "files": [
            "scripts/e2e_f7_t04_chat.py",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/report.json",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/manifest.json",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": (
            "Completed all intended browser and database checks; retained a strict failure only "
            "for an archive request marked aborted after its confirmed 200 response during immediate navigation."
        ),
        "verification": [
            "python scripts/e2e_f7_t04_chat.py -> NEAR PASS: all flows, 8 screenshots, 5 visual contracts and SQLite checks passed; one archive request ERR_ABORTED after server 200",
        ],
    },
    "inline-quiz-focus-fix": {
        "files": [
            "frontend/src/views/Chat.vue",
            "scripts/e2e_f7_t04_chat.py",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": (
            "Kept quiz-context deep links focused on the compact question card and corrected the "
            "browser test to use the visible label interaction available to students."
        ),
        "verification": [],
    },
    "browser-e2e-fourth-run-partial": {
        "files": [
            "scripts/e2e_f7_t04_chat.py",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/report.json",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": (
            "Passed the complete Chat and recovery flow through inline-quiz loading; stopped on "
            "a hidden-radio test interaction and revealed the quiz-entry scroll-position issue."
        ),
        "verification": [
            "python scripts/e2e_f7_t04_chat.py -> PARTIAL: Chat/attachments/resource/stop-continue/empty/quiz-load PASS; hidden radio input click intercepted",
        ],
    },
    "browser-e2e-third-run-partial": {
        "files": [
            "scripts/e2e_f7_t04_chat.py",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/report.json",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": (
            "Passed attachment recovery, real upload, answer completion, removal and explicit "
            "resource creation with protected state unchanged; stopped on a pre/post-startup seed-count assertion."
        ),
        "verification": [
            "python scripts/e2e_f7_t04_chat.py -> PARTIAL: attachment/resource flow PASS and protected before/after state equal; fixture pre-startup source total assertion failed",
        ],
    },
    "browser-e2e-second-run-partial": {
        "files": [
            "scripts/e2e_f7_t04_chat.py",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/01-focused-chat-1440x900.png",
            "outputs/原系统融合重构执行/evidence/f7_t04_chat/browser/report.json",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": (
            "Reached the real browser workspace, passed the initial desktop visual and diagnostic "
            "contract, and confirmed the partial attachment; stopped on an overly exact text locator."
        ),
        "verification": [
            "python scripts/e2e_f7_t04_chat.py -> PARTIAL: 1440x900 initial visual PASS, 0 browser/request errors, partial-confirm API 200; exact combined-status locator timed out",
        ],
    },
    "browser-e2e-first-run-failed": {
        "files": [
            "scripts/e2e_f7_t04_chat.py",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": (
            "Stopped before browser acceptance because the generated isolated fixture contained "
            "an unterminated Markdown string; no business state or product evidence was produced."
        ),
        "verification": [
            "python scripts/e2e_f7_t04_chat.py -> FAILED before service start: generated fixture SyntaxError (unterminated string literal)",
        ],
    },
    "browser-e2e-added": {
        "files": [
            "scripts/e2e_f7_t04_chat.py",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": (
            "Added the isolated-SQLite, deterministic-model, dual-desktop browser acceptance "
            "for the focused Chat, attachments, recovery, explicit resources and inline quiz."
        ),
        "verification": [],
    },
    "static-boundary-scan-pass": {
        "files": [
            "frontend/src/views/Chat.vue",
            "frontend/src/components/IncrementalMarkdownRenderer.vue",
            "frontend/src/stores/chat.js",
            "frontend/src/api/chat.js",
            "frontend/src/api/stream.js",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": (
            "Verified removed-workbench, local-truth, sensitive-field, client-scoring and "
            "F1 desktop visual boundaries with native PowerShell source scans."
        ),
        "verification": [
            "Select-String legacy workbench/local truth/sensitive/client scoring/gradient/under-14px scan -> PASS; one read-only course-title localStorage compatibility label only",
            "Chat color enumeration -> #F5F7F7, white, ink/navy-grey and dark-red error-state tokens only",
        ],
    },
    "focused-regression-pass": {
        "files": [
            "tests/test_f7_t04_chat_api.py",
            "tests/test_f7_t04_chat_stream.py",
            "tests/test_m5_stream_context.py",
            "tests/test_f6_t01_quiz_resource.py",
            "tests/test_f7_t04_chat_frontend_contract.py",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": (
            "Verified the focused Chat API, canonical stream, M5 context, F6 quiz protection "
            "and frontend source contracts together against isolated local test state."
        ),
        "verification": [
            "python -m pytest -q tests/test_f7_t04_chat_api.py tests/test_f7_t04_chat_stream.py tests/test_m5_stream_context.py tests/test_f6_t01_quiz_resource.py tests/test_f7_t04_chat_frontend_contract.py -> 35 passed",
        ],
    },
    "focused-chat-ui-contract-pass": {
        "files": [
            "frontend/src/views/Chat.vue",
            "frontend/src/components/IncrementalMarkdownRenderer.vue",
            "tests/test_f7_t04_chat_frontend_contract.py",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": (
            "Verified the focused desktop Chat source contract, removed-workbench boundaries, "
            "attachment states, explicit resource actions, sensitive-field exclusions and "
            "production compilation."
        ),
        "verification": [
            "python -m pytest -q tests/test_f7_t04_chat_frontend_contract.py -> 8 passed",
            "cd frontend; npm run build -> 6931 modules transformed, build passed",
        ],
    },
    "focused-chat-ui": {
        "files": [
            "frontend/src/views/Chat.vue",
            "frontend/src/components/IncrementalMarkdownRenderer.vue",
            "tests/test_f7_t04_chat_frontend_contract.py",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": (
            "Replaced the legacy super-workbench with the focused three-column conversation, "
            "answer and evidence workspace while preserving canonical attachments, quiz attempts, "
            "source context, streaming recovery and formal module deep links."
        ),
        "verification": [],
    },
    "resource-action-tests-pass": {
        "files": [
            "tests/test_f7_t04_chat_api.py",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": (
            "Verified the explicit resource action contract, honest rejection states, compact "
            "Chat payload and protected learning state in isolated SQLite."
        ),
        "verification": [
            "python -m pytest -q tests/test_f7_t04_chat_api.py -> 7 passed",
        ],
    },
    "resource-action-tests-added": {
        "files": [
            "tests/test_f7_t04_chat_api.py",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": (
            "Added isolated API coverage for successful, idempotent and rejected explicit "
            "resource actions without weakening F6 quiz or learning-evidence boundaries."
        ),
        "verification": [],
    },
    "chat-resource-action-foundation": {
        "files": [
            "app/chat_api.py",
            "frontend/src/api/chat.js",
            "frontend/src/stores/chat.js",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": (
            "Added the explicit answer-first resource action using the existing single-resource "
            "GenerationJob protocol, with canonical source/profile context and compact Learning "
            "Space links only."
        ),
        "verification": [],
    },
    "frontend-store-check-pass": {
        "files": [
            "frontend/src/stores/chat.js",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": (
            "Verified the canonical server-backed store compiles and contains no local message "
            "truth, sensitive process fields or client-side quiz scoring."
        ),
        "verification": [
            "cd frontend; npm run build -> 6941 modules transformed, build passed",
            "Select-String src/stores/chat.js forbidden local-truth/sensitive/answer fields -> PASS",
        ],
    },
    "frontend-store-check-first-run": {
        "files": [
            "frontend/src/stores/chat.js",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": (
            "Recorded a successful production build and an invalid duplicated-path static scan; "
            "the store verification remains incomplete until the corrected scan runs."
        ),
        "verification": [
            "frontend static scan -> path error (frontend/frontend/src/stores/chat.js)",
            "cd frontend; npm run build -> 6941 modules transformed, build passed",
        ],
    },
    "frontend-store-canonical": {
        "files": [
            "frontend/src/stores/chat.js",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": (
            "Replaced localStorage chat truth with the canonical server conversation, message, "
            "attachment and stream state while preserving F6 quiz and F7-T05 audit ownership."
        ),
        "verification": [],
    },
    "frontend-api-foundation": {
        "files": [
            "frontend/src/api/chat.js",
            "frontend/src/api/index.js",
            "frontend/src/api/stream.js",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": (
            "Added the focused frontend conversation, attachment and canonical SSE API surface "
            "while preserving F6 quiz ownership and excluding legacy Chat workbench modes."
        ),
        "verification": [],
    },
    "frontend-api-build-pass": {
        "files": [
            "frontend/src/api/chat.js",
            "frontend/src/api/index.js",
            "frontend/src/api/stream.js",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": (
            "Verified that the new frontend chat API surface compiles inside the existing Vue "
            "application without adding a second Chat workbench or sensitive client fields."
        ),
        "verification": [
            "cd frontend; npm run build -> 6941 modules transformed, build passed",
        ],
    },
    "backend-foundation": {
        "files": [
            "app/database.py",
            "app/migrations.py",
            "app/main.py",
            "app/chat_api.py",
            "scripts/update_f7_t04_atomic_ledger.py",
            "outputs/原系统融合重构执行/evidence/context_recovery/f7_t04_editing_metadata.json",
        ],
        "result": (
            "Implemented the owner-scoped canonical conversation, message and attachment "
            "foundation and registered its recovery evidence without changing course knowledge "
            "or learning evidence."
        ),
        "verification": [],
    },
    "backend-tests-pass": {
        "files": [
            "tests/test_f7_t04_chat_api.py",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": (
            "Verified the canonical chat API against an isolated SQLite database, including "
            "attachment parsing, recovery, ownership, idempotency and evidence isolation."
        ),
        "verification": [
            "python -m pytest -q tests/test_f7_t04_chat_api.py -> 5 passed",
        ],
    },
    "stream-integration": {
        "files": [
            "app/chat_api.py",
            "stream_api.py",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": (
            "Connected canonical chat messages, attachments and source locators to one focused "
            "streaming answer path with honest multimodal failure and recoverable persistence."
        ),
        "verification": [],
    },
    "stream-tests-pass": {
        "files": [
            "tests/test_f7_t04_chat_stream.py",
            "tests/test_m5_stream_context.py",
            "scripts/update_f7_t04_atomic_ledger.py",
        ],
        "result": (
            "Verified canonical stream binding, replay, evidence isolation, legacy-mode bypass "
            "and honest vision failure with deterministic local test doubles."
        ),
        "verification": [
            "python -m pytest -q tests/test_f7_t04_chat_stream.py tests/test_m5_stream_context.py -> 16 passed",
        ],
    },
}


def append_unique(values: list[str], additions: list[str]) -> list[str]:
    result = list(values)
    for item in additions:
        if item not in result:
            result.append(item)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", required=True, choices=sorted(set(BATCHES) | set(VERIFICATION_BATCHES)))
    args = parser.parse_args()

    payload = json.loads(LEDGER.read_text(encoding="utf-8"))
    entries = {entry["atomic_requirement_id"]: entry for entry in payload["entries"]}
    target_field = "implementation_evidence" if args.batch in BATCHES else "verification_evidence"
    selected = BATCHES.get(args.batch) or VERIFICATION_BATCHES[args.batch]
    for atom_id, evidence in selected.items():
        entry = entries[atom_id]
        realization = entry["realization"]
        realization[target_field] = append_unique(
            realization.get(target_field) or [], evidence
        )
        if realization.get("status") == "PENDING":
            realization["status"] = "IN_PROGRESS"
    batch_definition = EXECUTION_BATCHES.get(args.batch)
    if batch_definition:
        batches = payload.setdefault("execution_batches", [])
        record = next((item for item in batches if item.get("id") == args.batch), None)
        if record is None:
            record = {"id": args.batch}
            batches.append(record)
        record.update(
            {
                "status": "IMPLEMENTED_PENDING_FINAL_VERIFICATION",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "atoms": sorted(selected),
                "files": batch_definition["files"],
                "result": batch_definition["result"],
                "verification": batch_definition["verification"],
            }
        )
    LEDGER.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "UPDATED", "batch": args.batch, "field": target_field, "atoms": sorted(selected)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
