#!/usr/bin/env python3
"""Record incremental F5-T07 realization evidence without closing the task."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER = next((ROOT / "outputs/原系统融合重构执行/evidence/context_recovery/atomic_requirement_ledgers/EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION").glob("F5-T07_*.json"))
FILES = [
    "frontend/src/views/ResourceCenter.vue",
    "frontend/src/components/ResourcePreviewDrawer.vue",
    "frontend/src/components/ResourceHistoryDrawer.vue",
    "frontend/src/components/ResourceEditorDialog.vue",
    "frontend/src/components/ResourceToolbar.vue",
    "frontend/src/views/HandoutWorkspace.vue",
    "frontend/src/views/MindmapWorkspace.vue",
    "frontend/src/views/TrainingTaskWorkspace.vue",
    "frontend/src/views/VideoRecommendationWorkspace.vue",
    "frontend/src/views/WebDeckWorkspace.vue",
    "frontend/src/api/m5.js",
]
PRIMARY = {"G05-R04", "G08-R04", "G08-R05", "G08-R06", "G08-R07", "G21-R10", "G22-R10"}


def main() -> None:
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    ledger["entries"] = [entry for entry in ledger.get("entries", []) if entry.get("atomic_requirement_id")]
    stamp = datetime.now(timezone.utc).isoformat()
    for entry in ledger["entries"]:
        atom_id = entry["atomic_requirement_id"]
        realization = entry["realization"]
        if atom_id in PRIMARY:
            realization.update({
                "status": "IMPLEMENTATION_IN_PROGRESS",
                "implementation_evidence": [
                    f"F5-T07-B01 at {stamp}: {', '.join(FILES)}",
                    "ResourceCenter now owns history/compare/restore/complete and single-generation state transitions.",
                ],
                "user_visible_result": "资源中心批次已接入统一操作入口，等待自动测试和桌面验收核销。",
                "compatibility_or_defer_rationale": "验证证据将在本批聚焦测试、构建和桌面检查后回填；任务尚未关闭。",
            })
        else:
            realization.update({
                "status": "PENDING",
                "implementation_evidence": [
                    f"F5-T07-B01 compatibility surface: {', '.join(FILES)}",
                    "Existing resource-center filtering, deep links, resource-specific workspaces, F4 completion owner and F5-T02 bundle executor remain the protected callers.",
                ],
                "compatibility_or_defer_rationale": "本批先接入统一资源操作外壳；相关原子的逐条兼容/协同验证待自动回归和桌面验收后回填。",
            })
    for batch in ledger.get("execution_batches", []):
        if batch.get("id") == "F5-T07-B01":
            batch["status"] = "IMPLEMENTED_PENDING_VERIFICATION"
            batch["updated_at"] = stamp
            batch["result"] = "资源中心统一历史、比较、恢复、完成和单资源生成 UI 已接入；工作区统一外壳仍待下一批。"
    for batch in ledger.get("execution_batches", []):
        if batch.get("id") == "F5-T07-B02":
            batch["status"] = "IMPLEMENTED_PENDING_VERIFICATION"
            batch["updated_at"] = stamp
            batch["result"] = "ResourceCenter generic editor saves as a new version and preserves source and historical content."
    if not any(batch.get("id") == "F5-T07-B02" for batch in ledger.get("execution_batches", [])):
        ledger.setdefault("execution_batches", []).append({
            "id": "F5-T07-B02",
            "status": "PLANNED",
            "direct_atoms": ["G08-R04", "G08-R05", "G08-R06"],
            "related_atoms": ["G05-R04", "G05-R06", "G08-R01", "G08-R03", "G21-R01", "G21-R02", "G21-R03", "G21-R10", "G21-R12", "G22-R10"],
            "files": [
                "frontend/src/views/ResourceCenter.vue",
                "frontend/src/components/ResourcePreviewDrawer.vue",
                "frontend/src/components/ResourceEditorDialog.vue",
            ],
            "interfaces": ["GET /api/v1/m5/resources/{artifact_id}", "POST /api/v1/m5/resources/{artifact_id}/versions"],
            "states": ["edit_source", "save_as_new_version", "edit_conflict", "edit_failure", "historical_read_only"],
            "verification": ["tests/test_f5_t07_resource_history.py", "frontend production build", "desktop browser edit and refresh check"],
            "protection_contracts": ["structured resource content_format validation remains server-owned", "old versions remain immutable", "specialized resource workspaces retain their existing editors and exports"],
        })
    if not any(batch.get("id") == "F5-T07-B03" for batch in ledger.get("execution_batches", [])):
        ledger.setdefault("execution_batches", []).append({
            "id": "F5-T07-B03",
            "status": "IMPLEMENTED_PENDING_VERIFICATION",
            "direct_atoms": ["G05-R04", "G08-R04", "G08-R05", "G08-R06", "G08-R07"],
            "related_atoms": ["G21-R10", "G22-R10"],
            "files": [
                "frontend/src/components/ResourceToolbar.vue",
                "frontend/src/components/ResourceHistoryDrawer.vue",
                "frontend/src/views/HandoutWorkspace.vue",
                "frontend/src/views/MindmapWorkspace.vue",
                "frontend/src/views/TrainingTaskWorkspace.vue",
                "frontend/src/views/VideoRecommendationWorkspace.vue",
                "frontend/src/views/WebDeckWorkspace.vue",
            ],
            "interfaces": [
                "GET /api/v1/m5/resources/{artifact_id}",
                "GET /api/v1/m5/resources/{artifact_id}/compare",
                "POST /api/v1/m5/resources/{artifact_id}/restore",
            ],
            "states": ["workspace_loading", "historical_read_only", "history_compare", "history_restore", "restore_failure", "workspace_recovery"],
            "verification": [
                "tests/test_f5_t03_handout_workspace.py",
                "tests/test_f5_t04_mindmap_workspace.py",
                "tests/test_f5_t05_training_task_workspace.py",
                "tests/test_f5_t06_video_deck_workspace.py",
                "frontend production build",
                "desktop E2E at 1440x900 and 1366x768",
            ],
            "protection_contracts": [
                "specialized editors, source jumps, media playback and exports remain available",
                "history restore creates a new current version",
                "training task support panel keeps the primary sandbox action visible",
            ],
        })
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"Recorded incremental F5-T07 batch evidence for {len(ledger['entries'])} atoms")


if __name__ == "__main__":
    main()
