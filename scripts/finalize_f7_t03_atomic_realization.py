#!/usr/bin/env python3
"""Finalize F7-T03 per-atom realization evidence without runtime writes."""

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
SUMMARY = "outputs/原系统融合重构执行/evidence/f7_t03_graph_admission/evidence_summary.md"
BROWSER_REPORT = (
    "outputs/原系统融合重构执行/evidence/f7_t03_graph_admission/browser/report.json"
)
BROWSER_MANIFEST = (
    "outputs/原系统融合重构执行/evidence/f7_t03_graph_admission/browser/manifest.json"
)
FOCUSED = (
    "F7-T03 backend and frontend focused contracts: 12 passed across canonical graph, authenticated "
    "discovery, owner-scoped admission and visual/navigation boundaries"
)
REGRESSION = (
    "F7-T03, F7-T01, F7-T02 and F4 profile protection regression: 40 passed; only pre-existing "
    "FastAPI lifecycle deprecation warnings remained"
)
BUILD = "frontend npm run build: PASS, 6940 modules transformed; existing chunk-size advisory only"
E2E = (
    "scripts/e2e_f7_t03_graph_admission.py: PASS at 1440x900 and 1366x768 with 13 screenshots; "
    "course graph, relationship projection, hierarchy fallback, source deep links, discovery, "
    "license gating, personal admission, withdrawal, failure recovery and profile protection verified"
)
VISUAL = (
    "Manual screenshot and canvas review: deterministic course-only concentric layout has no edge "
    "clipping; graph/overview and discovery layouts have no overflow, collision, clipped content, "
    "sub-14px text or prohibited theme treatment"
)
IMPECCABLE = (
    "Impeccable detect.mjs found no issue in F7-T03 graph, discovery and shared explorer targets; "
    "reported Chat.vue findings were pre-existing out-of-scope visual debt"
)
DATABASE = (
    "isolated F7-T03 SQLite: integrity_check=ok, 0 foreign-key violations; protected counts remained "
    "learning_events=127, profile_snapshots=15, path_nodes=4 and canonical source_refs=41; final "
    "candidate status=withdrawn"
)
NO_EXTERNAL = "Browser report recorded external_requests=[] and external_model_called=false"


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
        verification=list(verification) or [FOCUSED, REGRESSION, E2E],
        visible=visible,
        rationale=(
            "F7-T03 owns this course-graph or web-candidate behavior. F7-T01 remains authoritative "
            "for the canonical shelf and recommendations, F7-T02 for document reading, and F7-T05 "
            "for unified source and public Agent audit governance."
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
        verification=list(verification) or [REGRESSION, E2E],
        visible=visible,
        rationale=rationale,
    )


REALIZATION = {
    "G11-R03": primary(
        [
            "source_admission.search_web_materials accepts a real query, keeps only valid HTTP(S) source URLs and returns an honest network-disabled or network-failure result instead of fabricated fallback material.",
            "DBWebSourceCandidate and the authenticated discovery API persist the query, title, source URL, domain, author/organization, format, license, usage, parsing impact, trust, review state and imported version per owner.",
            "KnowledgeDiscoveryWorkspace keeps the search term and saved candidates across failure and provides retry without changing the canonical shelf, course graph or learning state.",
        ],
        "The learner searches for public course material in a dedicated discovery page, opens the real source, saves a candidate for review and can retry a failed search without losing the query or existing candidates. The preloaded course remains usable offline.",
        FOCUSED,
        REGRESSION,
        E2E,
        DATABASE,
        NO_EXTERNAL,
    ),
    "G11-R05": primary(
        [
            "build_course_graph reads only an authorized published course, chapters, knowledge points, prerequisites, canonical source documents and source refs, then returns stable typed nodes, deduplicated relations, statistics and source locations.",
            "The authenticated course-graph API excludes DBWebSourceCandidate records and returns a hierarchy fallback from the same canonical facts when graph display is unavailable or too large.",
            "KnowledgeGraphWorkspace renders the canonical response through KnowledgeGraphExplorer and routes source nodes to the existing F7-T02 reader with course, chapter and source-ref context.",
        ],
        "The learner opens a real course graph, searches and filters its chapters, knowledge points and relations, selects a node and follows its canonical source into the large document reader. A hierarchy view remains available when the graph cannot be used.",
        FOCUSED,
        REGRESSION,
        E2E,
        VISUAL,
        DATABASE,
    ),
    "G11-R06": primary(
        [
            "KnowledgeGraphWorkspace uses a stable 75/25 graph-and-overview grid with course summary before selection and node type, relations, source state and source actions after selection.",
            "The toolbar exposes search, chapter and relation filters, graph/projection modes and hierarchy fallback while keeping one clear source action in the selected-node state.",
            "KnowledgeGraphExplorer uses a deterministic course-only concentric layout with safe margins and source-label de-cluttering; the learner-profile graph retains its existing force layout by default.",
        ],
        "The learner sees the graph as the large visual subject and a readable right-side overview. Selecting a node updates its real course, relation and source details; missing or unavailable sources are explained rather than linked falsely.",
        FOCUSED,
        BUILD,
        E2E,
        VISUAL,
        IMPECCABLE,
    ),
    "G11-R07": primary(
        [
            "DBWebSourceCandidate is an owner-scoped table separate from DBSourceRef, DBSourceDocument and DBCourseDocument; search, preview and candidate save never write canonical course facts.",
            "source_admission enforces pending_review/license_required/imported/rejected/withdrawn transitions, allowed-license and usage checks, idempotent import identity and owner authorization.",
            "Even after personal admission, authorityScope remains personal_candidate_reference and the API/UI explicitly exclude the item from canonical course graph, RAG and resource generation; withdrawal preserves the audit record.",
        ],
        "The learner can review, reject, personally admit or withdraw a web candidate, but every state clearly says that it is not an authoritative course source and cannot enter the course graph, RAG or generated learning resources.",
        FOCUSED,
        REGRESSION,
        E2E,
        DATABASE,
    ),
    "G11-R09": primary(
        [
            "serialize_candidate returns real source URL/domain, author or explicit not-provided text, format, license status/text, usage hint, parsing impact, trust level, review status, imported version, blockers and authority scope.",
            "KnowledgeDiscoveryWorkspace shows those facts in the result and preview panes and disables admission while license or usage blockers remain.",
            "The page reports successful personal admission, rejection and withdrawal with the actual resulting version and state, without exposing crawler internals, traces, prompts, keys or raw logs.",
        ],
        "Before any admission action, the learner can inspect the original site, author or organization, format, license and use terms, parsing coverage, trust level and review state. Unknown licensing produces a visible blocker instead of implied permission.",
        FOCUSED,
        E2E,
        VISUAL,
        DATABASE,
    ),
    "G20-R06": primary(
        [
            "KnowledgeGraphExplorer accepts an optional relationship_projection layout mode that reuses the same nodes, edges, selection and source facts as the default graph.",
            "KnowledgeGraphWorkspace presents graph and relationship projection as a segmented secondary mode; projection changes only layout and preserves search, filters, legend and overview.",
            "The superseded Chat manifold entry was removed, no student top-level route was added, and the shared explorer defaults keep the existing profile graph behavior.",
        ],
        "The learner switches from the normal course graph to a relationship projection inside the same knowledge-graph page, examines the same facts and returns to the normal view. There is no separate manifold tool in Chat or the top-level navigation.",
        FOCUSED,
        REGRESSION,
        BUILD,
        E2E,
        VISUAL,
    ),
    "G10-R01": related(
        [
            "KnowledgeGraphExplorer adds course-only behavior behind optional props; StudentAnalysis keeps its default grouping, node data and protected /profile/learning route.",
        ],
        "The learning-profile graph still groups learner knowledge nodes in its original workspace while the course graph uses its own route and data.",
        "F4-T02 remains the sole owner of profile grouping. F7-T03 only verified backward compatibility of the shared explorer and did not redesign StudentAnalysis.",
        REGRESSION,
        E2E,
    ),
    "G10-R02": related(
        [
            "The shared explorer still accepts the existing source/target edge shape and emits the same adjacent-node selection behavior; explicit course relation types remain confined to the course graph response.",
        ],
        "Profile prerequisite and skill edges remain visible and selectable; course chapter/source relations appear only in the course graph.",
        "F4-T02 owns learner-profile edge meaning. F7-T03 adds course relation types without changing the default profile edge contract.",
        REGRESSION,
        E2E,
    ),
    "G10-R03": related(
        [
            "KnowledgeGraphExplorer preserves mastery/masteryBand symbols and tooltips by default, while KnowledgeGraphWorkspace opts out of mastery text for canonical course facts.",
        ],
        "Profile nodes continue to show learner mastery or honest unknown/conflict states; course nodes do not pretend source trust is mastery.",
        "F2/F4 evidence aggregation remains authoritative for mastery. F7-T03 reads no new mastery evidence and keeps course facts separate.",
        REGRESSION,
        E2E,
        DATABASE,
    ),
    "G10-R04": related(
        [
            "The shared explorer retains the node-select event signature and default selected-node behavior used by StudentAnalysis; the course workspace owns a separate source overview state.",
        ],
        "Selecting a profile node still opens its analysis, evidence and next-step panel; selecting a course node opens only course and source facts.",
        "F4-T02 remains the owner of profile analysis and advice. F7-T03 verified that the separate course overview cannot replace or overwrite it.",
        REGRESSION,
        E2E,
    ),
    "G10-R05": related(
        [
            "The /profile/learning route, StudentAnalysis tabs and original profile actions remain mounted; F7-T03 introduces only knowledge-library deep routes.",
        ],
        "The learner can still use the rich profile and its mastery graph independently of the new course graph.",
        "F4-T02 owns the protected 7.20 profile. F7-T03 did not move, remove or simplify its substantive capabilities.",
        REGRESSION,
        E2E,
    ),
    "G10-R06": related(
        [
            "Course graph reads are GET-only and discovery writes remain in the candidate table; graph filtering, projection, zoom, selection, source opening and candidate review never call learning aggregation.",
        ],
        "Browsing either graph and reviewing web candidates leaves mastery, path and completion state unchanged.",
        "F2-T02 remains the owner of trusted learning-event admission. F7-T03 proves all graph/discovery interactions are ordinary activity, not mastery evidence.",
        REGRESSION,
        E2E,
        DATABASE,
    ),
    "G10-R07": related(
        [
            "StudentAnalysis and its profile API remain protected; the shared explorer defaults preserve profile dimensions, analysis, advice, editing and resource actions.",
        ],
        "The learner still reaches profile dimensions, detailed analysis, personalized advice, editing and resource actions after the course-graph addition.",
        "F4-T02 remains the sole owner of these 7.20 capabilities. F7-T03 performed compatibility verification only and introduced no task-out-of-scope profile refactor.",
        REGRESSION,
        E2E,
    ),
    "G11-R01": related(
        [
            "The F7-T01 shelf response and KnowledgeCourseShelf remain the first knowledge-library surface; discovery candidates are stored and rendered separately.",
        ],
        "The learner still enters the preloaded shelf first and reaches discovery or a course graph through clear knowledge-library actions.",
        "F7-T01 remains the sole owner of My Shelf. F7-T03 adds deep workspaces without mixing candidates into canonical shelf membership.",
        REGRESSION,
        E2E,
        DATABASE,
    ),
    "G11-R02": related(
        [
            "The F7-T01 recommendation API and UI are unchanged; DBWebSourceCandidate is not queried by the recommendation or canonical catalog path.",
        ],
        "Existing approved-course recommendations remain available even when discovery fails; unscreened web results never appear as recommendations.",
        "F7-T01 remains the sole owner of course/profile recommendations. F7-T03 only preserves the exclusion boundary for web candidates.",
        REGRESSION,
        E2E,
    ),
    "G11-R04": related(
        [
            "Course graph source nodes carry canonical documentId, sourceRefId, chapterId and location labels and deep-link to /knowledge/documents/:documentId.",
        ],
        "From a graph node, the learner opens the existing large reader at the matching course, chapter and source instead of a second preview implementation.",
        "F7-T01 owns canonical course search and F7-T02 owns the reader. F7-T03 supplies compatible source deep links and does not create another document viewer.",
        REGRESSION,
        E2E,
    ),
    "G11-R08": related(
        [
            "The graph service reads the F7-T01 canonical 12-chapter AI/ML course and its reviewed source refs; raw GitHub repositories and web candidates are absent from the graph query.",
        ],
        "The learner sees a complete preloaded course graph and source trail without uploading material or requiring live internet access.",
        "F7-T01 remains the sole owner of the curated course manifest, license audit and shelf. F7-T03 consumes those frozen facts read-only and verifies offline availability.",
        REGRESSION,
        E2E,
        DATABASE,
    ),
}


def append_unique(current: list[str], additions: list[str]) -> list[str]:
    return list(dict.fromkeys([*current, *additions]))


def main() -> None:
    matches = list(LEDGER_DIR.glob("F7-T03_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F7-T03 ledger, found {len(matches)}")
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
        "id": "F7-T03-B06",
        "status": "VERIFIED",
        "atoms": [*primary_ids, *related_ids],
        "direct_atoms": primary_ids,
        "related_atoms": related_ids,
        "files": [
            "app/database.py",
            "app/migrations.py",
            "app/knowledge_graph.py",
            "app/source_admission.py",
            "knowledge_api.py",
            "frontend/src/api/knowledge.js",
            "frontend/src/components/KnowledgeGraphExplorer.vue",
            "frontend/src/views/KnowledgeGraphWorkspace.vue",
            "frontend/src/views/KnowledgeDiscoveryWorkspace.vue",
            "frontend/src/router/index.js",
            "frontend/src/views/Chat.vue",
            "tests/test_f7_t03_graph_and_admission.py",
            "tests/test_f7_t03_graph_and_admission_frontend_contract.py",
            "scripts/e2e_f7_t03_graph_admission.py",
            "scripts/record_f7_t03_batch.py",
            "scripts/fill_f7_t03_atomic_understanding.py",
            "scripts/finalize_f7_t03_atomic_realization.py",
            BROWSER_REPORT,
            BROWSER_MANIFEST,
            SUMMARY,
            "outputs/原系统融合重构执行/evidence/f7_t03_graph_admission/code_complete_metadata.json",
            "outputs/原系统融合重构执行/evidence/f7_t03_graph_admission/tested_metadata.json",
            "outputs/原系统融合重构执行/evidence/f7_t03_graph_admission/evidence_verified_metadata.json",
            "outputs/原系统融合重构执行/evidence/f7_t03_graph_admission/closed_metadata.json",
        ],
        "verification": [FOCUSED, REGRESSION, BUILD, E2E, VISUAL, IMPECCABLE, DATABASE, NO_EXTERNAL],
        "protection_contracts": [
            "F7-T01 retains ownership of the canonical shelf, curated course and recommendations",
            "F7-T02 retains ownership of the large document reader and exact source locations",
            "F7-T05 retains ownership of unified source and public Agent audit governance",
            "F4-T02 learner profile graph and all substantive 7.20 profile actions remain protected",
            "web candidates never enter canonical course facts, graph, RAG or resource generation",
            "graph and discovery browsing never write mastery or completion evidence",
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
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F7-T03")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F7-T03",
        entries=expected,
    )
    failures.extend(validate_realization(ledger, expected))
    if failures:
        raise RuntimeError(f"F7-T03 atomic realization gate failed: {failures}")
    print(f"Updated and validated {len(actual_ids)} F7-T03 atomic realizations: {ledger_path}")


if __name__ == "__main__":
    main()
