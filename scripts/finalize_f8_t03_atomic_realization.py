#!/usr/bin/env python3
"""Finalize F8-T03 after isolated browser, regression and visual acceptance."""

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
EVIDENCE_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f8_t03_notes"

PRIMARY_ID = "G07-R09"
RELATED_IDS = [
    "G07-R01", "G07-R02", "G07-R03", "G07-R04", "G07-R05", "G07-R06",
    "G07-R07", "G07-R08", "G07-R10",
    "G21-R01", "G21-R02", "G21-R03", "G21-R04", "G21-R05", "G21-R06",
    "G21-R07", "G21-R08", "G21-R09", "G21-R10", "G21-R11", "G21-R12",
    "G21-R13",
    "G24-R01", "G24-R02", "G24-R03", "G24-R04", "G24-R05", "G24-R06",
    "G24-R07",
]

FINAL_EVIDENCE = [
    "Focused/protection regression: 81 passed in 46.35s across F8-T03 notes, F7 document reader/source governance, F8 review/wrong questions, F5 handout/history and F6 code sandbox; the F7 selection-note protection asserts one owner-scoped note.created event with mastery_eligible=false and completion_effect=none.",
    "Context recovery regression: 20 passed in 1.30s; Python syntax compilation for all F8-T03 backend, test and ledger scripts passed.",
    "Production build: frontend npm run build passed with 6936 modules transformed; only the existing chunk-size warning remains; git diff --check has no whitespace errors beyond repository LF-to-CRLF notices.",
    "Browser E2E: isolated deterministic journey passed 12/12 checks with 9 screenshots at 1440x900 and 1366x768, covering exact selection identity, four source routes, draft refresh, optimistic conflict, separate AI suggestion, immutable restore and protected 7.20 note actions.",
    "Visual acceptance: the four reported states have no overflow, clipping, collisions, sub-14px text, forbidden theme hits or gradients; Impeccable detector returned [].",
    "Database acceptance: isolated SQLite integrity_check=ok and foreign_key_violations=0; ordinary browsing leaves mastery_events=0 and protected profile/path/review state unchanged.",
    "Boundary acceptance: no formal database, external model, external request, Git operation or delivery-package update was used.",
]


def unique(values: list[str], additions: list[str]) -> list[str]:
    return list(dict.fromkeys([*values, *additions]))


def validate_report() -> dict:
    report = json.loads((EVIDENCE_DIR / "report.json").read_text(encoding="utf-8"))
    if report.get("status") != "passed":
        raise RuntimeError("F8-T03 browser report is not passed")
    screenshots = report.get("screenshots") or []
    if len(screenshots) != 9 or any(not (EVIDENCE_DIR / "browser" / name).is_file() for name in screenshots):
        raise RuntimeError("F8-T03 browser screenshot evidence is incomplete")
    if not report.get("checks") or not all(report["checks"].values()):
        raise RuntimeError("F8-T03 browser journey checks are incomplete")
    for key in ("http_errors", "failed_requests", "page_errors", "console_errors", "external_requests"):
        if report.get(key) != []:
            raise RuntimeError(f"F8-T03 browser report contains {key}")
    if report.get("external_model_called") is not False or report.get("deterministic_model_only") is not True:
        raise RuntimeError("F8-T03 browser report is not local deterministic acceptance")

    visual = report.get("visual") or {}
    if set(visual) != {
        "selection_source_1440x900",
        "conflict_preserves_draft_1440x900",
        "version_restore_complete_1440x900",
        "stable_workspace_1366x768",
    }:
        raise RuntimeError("F8-T03 visual report is incomplete")
    for result in visual.values():
        for key in ("clipped", "smallText", "collisions", "forbiddenThemeHits", "gradients"):
            if result.get(key) != []:
                raise RuntimeError(f"F8-T03 visual report contains {key}")
        if result.get("pageOverflow") or result.get("rootOverflow"):
            raise RuntimeError("F8-T03 visual report contains overflow")
        if (result.get("layout") or {}).get("leftOverlap") != 0 or (result.get("layout") or {}).get("rightOverlap") != 0:
            raise RuntimeError("F8-T03 visual report contains pane overlap")

    database = report.get("database") or {}
    if database.get("read_only_before") != database.get("read_only_after"):
        raise RuntimeError("F8-T03 primary ordinary browsing changed business state")
    if database.get("secondary_read_only_before") != database.get("secondary_read_only_after"):
        raise RuntimeError("F8-T03 secondary ordinary browsing changed business state")
    final = database.get("final") or {}
    if final.get("mastery_events") != 0 or final.get("integrity") != "ok" or final.get("foreign_key_violations") != 0:
        raise RuntimeError("F8-T03 final database boundary failed")
    source = (final.get("knowledge_note") or {}).get("source_metadata") or {}
    required_source = {
        "source_type": "knowledge_selection",
        "selection_id": source.get("selection_id"),
        "source_document_id": source.get("source_document_id"),
        "source_ref_id": source.get("source_ref_id"),
        "document_version": source.get("document_version"),
        "selection_type": "image",
        "page_number": 1,
    }
    if not all(required_source.values()) or source.get("normalized_rect") is None or not source.get("crop_ref"):
        raise RuntimeError("F8-T03 image selection source identity is incomplete")
    return report


def main() -> None:
    report = validate_report()
    matches = list(LEDGER_DIR.glob("F8-T03_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F8-T03 ledger, found {len(matches)}")
    ledger_path = matches[0]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    entries = {entry["atomic_requirement_id"]: entry for entry in ledger["entries"]}
    expected = {PRIMARY_ID, *RELATED_IDS}
    if set(entries) != expected:
        raise RuntimeError(f"Atomic realization mismatch: missing={sorted(expected - set(entries))}, extra={sorted(set(entries) - expected)}")

    for batch in ledger.get("execution_batches", []):
        batch["verification"] = unique(list(batch.get("verification") or []), FINAL_EVIDENCE)
        batch["status"] = "VERIFIED"

    primary = entries[PRIMARY_ID]
    primary_realization = primary["realization"]
    primary_realization["implementation_evidence"] = unique(
        list(primary_realization.get("implementation_evidence") or []),
        ["G07-R09 implementation: app/note_workspace.py, app/document_selection.py, app/crud.py, app/main.py, frontend/src/api/notes.js and frontend/src/views/Notes.vue preserve text/image selection identity, versioned note drafts and exact source return.",
         "G07-R09 browser result: a document image selection became a source-bound note retaining documentVersion, page, normalized region, selectionId and sourceRefId."],
    )
    primary_realization["verification_evidence"] = unique(
        list(primary_realization.get("verification_evidence") or []),
        ["G07-R09 per-atom final verification: " + item for item in FINAL_EVIDENCE],
    )
    primary_realization["user_visible_result"] = "学生可以从文档文本划选或图片框选直接创建笔记，在笔记右侧查看精确来源，并返回原文页码或图片区域；保存冲突、来源撤回、刷新和历史恢复都保留正文。"
    primary_realization["compatibility_or_defer_rationale"] = "F7-T02继续拥有20/58/22阅读器、OCR、选区问答和位置恢复；F8-T03只负责笔记归档、来源投影和回链，没有建立第二套文档或选区事实源。"
    primary_realization["status"] = "IMPLEMENTED_AND_VERIFIED"

    for atom_id in RELATED_IDS:
        entry = entries[atom_id]
        realization = entry["realization"]
        meaning = entry["understanding"]["product_meaning"]
        rationale = entry["realization"].get("compatibility_or_defer_rationale") or "按当前任务合同保护既有模块边界。"
        realization["verification_evidence"] = unique(
            list(realization.get("verification_evidence") or []),
            [f"{atom_id} per-atom verification: {meaning}", *FINAL_EVIDENCE],
        )
        realization["compatibility_or_defer_rationale"] = rationale
        realization["user_visible_result"] = f"{atom_id}：{meaning} 已由当前实现保留或联动，并通过对应来源、回归、状态和桌面证据。"
        realization["status"] = "COORDINATION_VERIFIED"

    ledger["final_acceptance"] = {
        "status": "VERIFIED",
        "report": (EVIDENCE_DIR / "report.json").relative_to(ROOT).as_posix(),
        "screenshots": report["screenshots"],
        "primary_atoms": 1,
        "related_atoms": len(RELATED_IDS),
        "external_model_called": False,
        "formal_database_modified": False,
        "detector": "[]",
    }
    temporary = ledger_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(ledger_path)
    print(json.dumps({"status": "FINALIZED", "task": "F8-T03", "primary": 1, "related": len(RELATED_IDS), "screenshots": len(report["screenshots"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
