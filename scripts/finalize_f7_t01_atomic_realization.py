#!/usr/bin/env python3
"""Finalize F7-T01 per-atom realization evidence without changing runtime data."""

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
SUMMARY = "outputs/原系统融合重构执行/evidence/f7_t01_knowledge_shelf/evidence_summary.md"
FOCUSED = (
    "F7-T01 focused and related regression: 66 passed across bookshelf, frontend, curated-course, license, "
    "version, source-location, graph-boundary, F1-shell and context-recovery tests"
)
BUILD = "frontend npm run build: PASS, 6935 modules transformed; existing chunk-size advisory only"
COMPILE = "python -m py_compile: PASS for F7-T01 production, E2E, ledger and focused-test Python files"
DIFF = "git diff --check: PASS; existing Windows LF/CRLF notices only, no whitespace errors"
E2E = (
    "scripts/e2e_f7_t01_knowledge_shelf.py: PASS in 26.6s with 11 screenshots at 1440x900 and 1366x768; "
    "catalog failure recovery, bookshelf, course workspace, canonical document, course search, graph contract, "
    "discovery boundary and protected advanced tools verified"
)
VISUAL = (
    "Browser scans: 0 overflow, overlap, clipping, sub-14px text, decorative backgrounds, unexpected HTTP, "
    "request, page or console errors on the contracted states; light document preview manually reviewed"
)
IMPECCABLE = (
    "Impeccable detector: two gray-on-color warnings at Knowledge.vue:1172 manually verified as false positives; "
    "the mutually exclusive Vue classes render slate/slate for ready and amber/amber otherwise"
)
DATABASE = (
    "isolated F7-T01 SQLite: integrity ok, 0 foreign-key violations, learning-event count unchanged at 127; "
    "no formal database write"
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


def primary(
    implementation: list[str],
    visible: str,
    *verification: str,
) -> dict[str, object]:
    return realized(
        role="primary",
        implementation=implementation,
        verification=list(verification) or [FOCUSED, E2E],
        visible=visible,
        rationale="F7-T01 owns this bookshelf foundation and keeps later F7 reader, graph and discovery work in their declared tasks.",
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
    "G11-R01": primary(
        [
            "knowledge_api._course_catalog_payload and GET /api/knowledge/courses aggregate published courses, memberships, chapters, documents, knowledge points and source/index health.",
            "KnowledgeCourseShelf renders 我的书架 -> 智能推荐 -> 联网发现 and routes course-first entries to /knowledge/courses/:courseId.",
            "The frozen public flagship course is added to the default shelf in the response without creating a synthetic membership or requiring upload.",
        ],
        "A new student opens Knowledge and immediately sees a course bookshelf, can enter the preloaded machine-learning course, and is never asked to upload course material first.",
        FOCUSED,
        E2E,
        VISUAL,
        DATABASE,
    ),
    "G11-R02": primary(
        [
            "_course_recommendation_basis reads current profile goals and weak points or declares a neutral local-catalog basis when evidence is absent.",
            "_recommendation_for_course returns a visible reason and ranks only published local courses; POST /api/knowledge/courses/{course_id}/shelf is membership-idempotent.",
            "KnowledgeCourseShelf shows recommendation reasons, progress, success feedback and moves a joined course into the bookshelf after refresh.",
        ],
        "The learner sees why each reviewed course is recommended and can add it once; repeating the action reuses the same shelf membership instead of creating duplicates.",
        FOCUSED,
        E2E,
        NO_EXTERNAL,
        DATABASE,
    ),
    "G11-R04": primary(
        [
            "build_canonical_course_source_detail authorizes the frozen default course or active members, reads the published DBCourseDocument body and verifies its processed SHA-256.",
            "KnowledgeCourseShelf loads the course outline, opens a chapter source through Knowledge, and performs course-scoped cross-language body search with locatable results.",
            "Knowledge renders the basic course-document dialog with normalized Markdown line breaks, source/version/license metadata, readable light styling and explicit close/recovery behavior.",
        ],
        "From a shelf course, the learner opens a chapter document and reads the real frozen Markdown body, then searches within the course and opens a located result without leaving the knowledge space.",
        FOCUSED,
        E2E,
        VISUAL,
        DATABASE,
    ),
    "G11-R08": primary(
        [
            "data/curated/machine_learning_foundations_v1 contains a versioned manifest, upstream license and 12 ordered Chinese Markdown chapters.",
            "The canonical course response reports 12 chapters, 12 documents, 13 knowledge points, 12 ready sources and 12 indexed documents from database objects seeded from the reviewed manifest.",
            "Catalog health is derived from actual license, source processing and document chunk fields rather than display-only claims.",
        ],
        "The shipped bookshelf visibly contains a complete '机器学习基础与实践' course with chapter, document, knowledge-point, source, license and index status, and it remains readable and searchable without network access.",
        FOCUSED,
        E2E,
        NO_EXTERNAL,
        DATABASE,
    ),
    "G20-R08": primary(
        [
            "Knowledge remains one student primary route; course, document, graph and discovery deep links all render inside the same Knowledge page shell.",
            "KnowledgeCourseShelf uses the frozen mist-white, white-surface and ink/slate design contract with progressive disclosure for legacy upload, OCR, retrieval and graph tools.",
            "The course-document preview now uses dialog semantics, a light readable surface, stable desktop geometry and no F7-T02 selection or OCR-question controls.",
        ],
        "Knowledge now starts as a concise course-oriented bookshelf with a clear next step while the 7.20 reading, retrieval, OCR and graph capabilities remain reachable under the same entry instead of becoming a second product.",
        FOCUSED,
        BUILD,
        E2E,
        VISUAL,
        IMPECCABLE,
        DIFF,
    ),
    "G11-R03": related(
        [
            "KnowledgeCourseShelf keeps /knowledge/discover as the third section and states that network results remain candidates until source and license review.",
            "F7-T01 contains no discovery download/import call and its browser run observed no external request.",
        ],
        "The learner can reach a clear source-discovery explanation while the preloaded bookshelf continues to work offline.",
        "F7-T03 owns real network search, preview, license confirmation and admission; F7-T01 intentionally provides only the safe entry and preserves existing APIs.",
        FOCUSED,
        E2E,
        NO_EXTERNAL,
    ),
    "G11-R05": related(
        [
            "The course workspace exposes /knowledge/graph/:courseId and retains KnowledgeGraphExplorer behind the same knowledge route.",
            "The graph contract labels current chapter/knowledge-point structure as verified course context and preserves derived_non_fact governance for tag co-occurrence.",
        ],
        "The learner can enter the course graph context from the course page without ordinary browsing changing mastery.",
        "F7-T03 owns the full graph canvas, real relationship interaction and layout fallback; F7-T01 only protects the route, summary data and fact boundary.",
        FOCUSED,
        E2E,
    ),
    "G11-R06": related(
        [
            "KnowledgeCourseShelf graph-layout reserves a 3fr/1fr course-structure and overview split and carries the selected chapter, knowledge-point and source-health fields needed by the later graph page.",
            "The graph deep link keeps course facts separate from the learning-profile mastery graph.",
        ],
        "The current graph entry already presents course structure beside a course/chapter overview, with the complete node workspace explicitly left for the next graph task.",
        "F7-T03 owns the complete 75/25 node canvas and node-detail interaction; this task verifies compatible geometry, route and data without claiming that later interaction is complete.",
        FOCUSED,
        E2E,
        VISUAL,
    ),
    "G11-R07": related(
        [
            "_course_catalog_payload selects published database courses and marks catalog entries authoritative; it never reads data/raw/github_repos as runtime course truth.",
            "The discovery response and UI state that candidates require source and license confirmation before entry into the authoritative library.",
        ],
        "Unreviewed raw repositories never appear in the learner's bookshelf, course body or authoritative recommendation list.",
        "F7-T03 will implement candidate admission; F7-T01 enforces the consumption boundary by serving only reviewed canonical courses.",
        FOCUSED,
        E2E,
        NO_EXTERNAL,
    ),
    "G11-R09": related(
        [
            "_course_manifest_provenance preserves repository, revision, source hash, SPDX license, license file/hash and obligations for reviewed course documents.",
            "The catalog and document preview retain source URL, parser version/status, content hash, source reference, chapter, license and fixed-version fields.",
            "The discovery page explains that origin, author/institution, format, license/use and parsing impact must be checked before admission.",
        ],
        "For preloaded reviewed documents, the learner can inspect real source and license metadata; candidate items are not offered an unsafe one-click import.",
        "F7-T03 owns candidate result cards and the complete pre-admission confirmation flow; F7-T01 preserves the required metadata protocol and rejects missing authority implicitly by excluding candidates.",
        FOCUSED,
        E2E,
    ),
}


def append_unique(current: list[str], additions: list[str]) -> list[str]:
    return list(dict.fromkeys([*current, *additions]))


def main() -> None:
    matches = list(LEDGER_DIR.glob("F7-T01_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F7-T01 ledger, found {len(matches)}")
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
        "id": "F7-T01-B06",
        "status": "VERIFIED",
        "atoms": [*primary_ids, *related_ids],
        "direct_atoms": primary_ids,
        "related_atoms": related_ids,
        "files": [
            "knowledge_api.py",
            "frontend/src/api/knowledge.js",
            "frontend/src/components/KnowledgeCourseShelf.vue",
            "frontend/src/views/Knowledge.vue",
            "frontend/src/router/index.js",
            "tests/test_f7_t01_knowledge_shelf.py",
            "tests/test_f7_t01_knowledge_frontend_contract.py",
            "scripts/e2e_f7_t01_knowledge_shelf.py",
            "scripts/finalize_f7_t01_atomic_realization.py",
            "scripts/verify_context_recovery_packets.py",
            "tests/test_context_recovery_packets.py",
            "outputs/原系统融合重构执行/evidence/f7_t01_knowledge_shelf/batch_06_closure_mapping.json",
            SUMMARY,
            "outputs/原系统融合重构执行/evidence/f7_t01_knowledge_shelf/code_complete_metadata.json",
            "outputs/原系统融合重构执行/evidence/f7_t01_knowledge_shelf/tested_metadata.json",
            "outputs/原系统融合重构执行/evidence/f7_t01_knowledge_shelf/evidence_verified_metadata.json",
            "outputs/原系统融合重构执行/evidence/f7_t01_knowledge_shelf/closed_metadata.json",
        ],
        "verification": [FOCUSED, BUILD, COMPILE, DIFF, E2E, VISUAL, IMPECCABLE, DATABASE, NO_EXTERNAL],
        "protection_contracts": [
            "F7-T02 retains ownership of wide reading, pages, text selection, image-region selection, OCR questions and position recovery",
            "F7-T03 retains ownership of real network candidate admission and the complete course graph workspace",
            "ordinary browsing, searching, expanding and previewing do not write mastery or completion evidence",
            "raw GitHub repositories are candidates only; the bookshelf consumes reviewed canonical courses",
            "existing personal documents, OCR, retrieval and graph tools remain reachable through progressive disclosure",
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
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F7-T01")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F7-T01",
        entries=expected,
    )
    failures.extend(validate_realization(ledger, expected))
    if failures:
        raise RuntimeError(f"F7-T01 atomic realization gate failed: {failures}")
    print(f"Updated and validated {len(actual_ids)} F7-T01 atomic realizations: {ledger_path}")


if __name__ == "__main__":
    main()
