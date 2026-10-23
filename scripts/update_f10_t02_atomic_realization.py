"""Write verified F10-T02 report evidence into its task-local atomic ledger."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f10_t02_final_acceptance" / "final_acceptance_report.json"
LEDGER_PATH = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery" / "atomic_requirement_ledgers" / "EDUMATRIX-F9-F10-CONTEXT-SAFE-FUSION-COMPLETION" / "F10-T02_404D1D120CAB6E67E6B6C629420F8BA28D3585BDBB748FF93BABF5F4B38EB46A.json"


def main() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    if report.get("status") != "PASSED":
        raise RuntimeError("F10-T02 report is not PASSED")
    if report.get("viewports") != [[1440, 900], [1366, 768]]:
        raise RuntimeError("F10-T02 report does not contain the two frozen desktop viewports")
    route_results = report.get("route_results") or []
    if len(route_results) != 100 or any(item.get("result") != "PASSED" for item in route_results):
        raise RuntimeError("F10-T02 report does not contain 100 passed route records")
    if not report.get("ordinary_browse", {}).get("unchanged"):
        raise RuntimeError("ordinary browsing changed protected learning state")
    if report.get("external_model_called") is not False:
        raise RuntimeError("external model boundary was not preserved")
    audit = report.get("database_audit") or {}
    if audit.get("integrity") != "ok" or audit.get("foreign_key_violations") != 0:
        raise RuntimeError("database integrity or foreign-key boundary failed")
    model_evidence = report.get("external_model_evidence") or {}
    if (
        model_evidence.get("provider") != "deterministic"
        or model_evidence.get("endpoint_configured") is not False
        or model_evidence.get("model_calls_before_journey") != 0
        or model_evidence.get("model_calls_before_browse")
        != model_evidence.get("model_calls_after_browse")
        or model_evidence.get("ordinary_browse_model_calls_unchanged") is not True
        or model_evidence.get("off_origin_requests") != 0
        or audit.get("model_calls") != model_evidence.get("model_calls_after_browse")
    ):
        raise RuntimeError("local model-audit or external-model boundary failed")
    cleanup = report.get("cleanup") or {}
    if not cleanup.get("server_stopped") or not cleanup.get("port_closed") or cleanup.get("error"):
        raise RuntimeError("managed F10-T02 runtime was not cleanly stopped")

    entries = ledger.get("entries") or []
    evidence = report.get("atomic_evidence") or {}
    expected = {entry["atomic_requirement_id"] for entry in entries}
    if len(entries) != 23 or set(evidence) != expected:
        raise RuntimeError("report evidence and the 23-entry task ledger disagree")
    for entry in entries:
        atom_id = entry["atomic_requirement_id"]
        atom = evidence[atom_id]
        if entry.get("role") != "related" or atom.get("status") != "COMPATIBILITY_VERIFIED":
            raise RuntimeError(f"invalid related-atom evidence for {atom_id}")
        if not atom.get("verification_evidence") or not atom.get("compatibility_or_defer_rationale"):
            raise RuntimeError(f"incomplete related-atom evidence for {atom_id}")
        entry["realization"] = {
            "compatibility_or_defer_rationale": atom["compatibility_or_defer_rationale"],
            "implementation_evidence": [],
            "status": "COMPATIBILITY_VERIFIED",
            "user_visible_result": "",
            "verification_evidence": atom["verification_evidence"],
        }
    batches = [item for item in ledger.get("execution_batches", []) if item.get("batch_id") != "F10-T02-B01"]
    batches.append({
        "batch_id": "F10-T02-B01",
        "status": "VERIFIED",
        "mapping_file": "outputs/原系统融合重构执行/evidence/f10_t02_final_acceptance/batch_01_final_acceptance_mapping.json",
        "atoms": sorted(expected),
        "direct_atoms": [],
        "protected_atoms": sorted(expected),
        "files": [
            "scripts/e2e_f10_t02_final_acceptance.py",
            "scripts/update_f10_t02_atomic_realization.py",
            "scripts/transition_context_checkpoint.py",
            "tests/test_context_recovery_packets.py",
            "outputs/原系统融合重构执行/evidence/f10_t02_final_acceptance/context_checkpoint_metadata.json",
            "outputs/原系统融合重构执行/evidence/f10_t02_final_acceptance/final_acceptance_report.json",
            "outputs/原系统融合重构执行/evidence/f10_t02_final_acceptance/screenshots/all-routes/01-作品展示页-1366x768.png",
            "outputs/原系统融合重构执行/evidence/f10_t02_final_acceptance/screenshots/all-routes/01-作品展示页-1440x900.png",
        ],
        "result": (
            "F10-T02 generated 100 passed route records for the same 50 target routes at both desktop "
            "viewports and completed one student journey through onboarding, diagnostic, path, nine resources, "
            "required work, formal exam, report and downstream feedback. Ordinary browsing was byte-stable, "
            "SQLite passed integrity and foreign-key checks, explicit journey actions produced only local deterministic "
            "audit records while ordinary browsing added none, and the managed runtime stopped. Recovery metadata uses "
            "concrete screenshot files, and guarded checkpoint refresh synchronizes the verified ledger record."
        ),
    })
    ledger["execution_batches"] = batches
    LEDGER_PATH.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "UPDATED",
        "task": ledger["task"],
        "related_atoms": len(entries),
        "batch": "F10-T02-B01",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
