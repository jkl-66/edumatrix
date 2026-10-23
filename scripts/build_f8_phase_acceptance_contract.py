#!/usr/bin/env python3
"""Build the standalone atomic contract for F8 phase acceptance."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECOVERY = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery"
LEDGER_DIR = RECOVERY / "atomic_requirement_ledgers" / "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION"
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f8_phase_acceptance"
OUTPUT_PATH = OUTPUT_DIR / "atomic_execution_ledger.json"
TASK_ID = "F8-PHASE-ACCEPTANCE"

EXPECTED = {
    "F8-T01": [
        "G15-R01", "G15-R02", "G15-R03", "G15-R04", "G15-R05", "G15-R06",
        "G21-R07", "G21-R08", "G21-R09",
    ],
    "F8-T02": ["G22-R07"],
    "F8-T03": ["G07-R09"],
    "F8-T04": [
        "G19-R01", "G19-R02", "G19-R03", "G19-R04", "G19-R05",
        "G19-R06", "G19-R07", "G19-R08", "G20-R03",
    ],
    "F8-T05": ["G22-R06"],
}

IMAGE_PATHS = {
    7: "outputs/原系统融合重构执行/evidence/dual_version_audit/improvement_ideas/07_image7.png",
    21: "outputs/原系统融合重构执行/evidence/dual_version_audit/improvement_ideas/21_image21.jpeg",
    29: "outputs/原系统融合重构执行/evidence/dual_version_audit/improvement_ideas/29_image29.jpeg",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def source_ledger(task_id: str) -> Path:
    matches = list(LEDGER_DIR.glob(f"{task_id}_*.json"))
    require(len(matches) == 1, f"Expected one ledger for {task_id}, got {matches}")
    return matches[0]


def build_entry(task_id: str, atom_id: str, ledger: dict, ledger_path: Path) -> dict:
    matches = [entry for entry in ledger["entries"] if entry["atomic_requirement_id"] == atom_id]
    require(len(matches) == 1, f"{task_id} must contain one {atom_id}")
    source = matches[0]
    require(source["role"] == "primary", f"{task_id}/{atom_id} is not primary")
    require(source["understanding"].get("confirmed") is True, f"{task_id}/{atom_id} understanding is not confirmed")
    require(source["realization"].get("status") == "IMPLEMENTED_AND_VERIFIED", f"{task_id}/{atom_id} is not realized")
    for field in ("product_meaning", "behavior_boundaries", "implementation_scope", "verification_plan"):
        require(source["understanding"].get(field), f"{task_id}/{atom_id} lacks {field}")
    require(source["source"].get("full_original_words"), f"{task_id}/{atom_id} lacks full source words")

    phase_understanding = {
        "product_meaning": source["understanding"]["product_meaning"],
        "behavior_boundaries": [
            *source["understanding"]["behavior_boundaries"],
            "本阶段验收只验证已关闭实现，不新增、替换或削弱任何业务事实源和7.20保护能力。",
        ],
        "implementation_scope": [
            "在同一隔离SQLite、同一服务和同一无头Chromium中连续验证该原子的用户旅程。",
            "复用正式页面和既有E2E助手，仅新增阶段验收脚本、报告、截图与逐原子证据。",
        ],
        "verification_plan": [
            *source["understanding"]["verification_plan"],
            "将本原子映射到连续旅程动作、数据库前后快照、双桌面截图和最终阶段报告；不得以总体测试数代替逐条结论。",
        ],
        "confirmed": True,
    }
    return {
        "atomic_requirement_id": atom_id,
        "role": "primary",
        "owner_task": task_id,
        "source_ledger": {
            "path": ledger_path.relative_to(ROOT).as_posix(),
            "sha256": digest(ledger_path),
        },
        "source": source["source"],
        "understanding": phase_understanding,
        "closed_task_realization_baseline": source["realization"],
        "phase_realization": {
            "status": "PENDING",
            "implementation_evidence": [],
            "verification_evidence": [],
            "user_visible_result": "",
            "compatibility_or_defer_rationale": "",
        },
    }


def main() -> None:
    active = load(RECOVERY / "active_manifest.json")
    checkpoint = load(RECOVERY / "current_checkpoint.json")
    require(active.get("status") == "VERIFIED", "Active recovery manifest is not VERIFIED")
    require(checkpoint.get("task") == "F8-T05" and checkpoint.get("state") == "CLOSED", "F8-T05 is not CLOSED")
    require("F8 阶段联合验收" in checkpoint.get("next_step", ""), "Checkpoint does not authorize F8 phase acceptance")

    entries = []
    ledger_records = {}
    for task_id, atom_ids in EXPECTED.items():
        path = source_ledger(task_id)
        ledger = load(path)
        require(ledger.get("task") == task_id, f"Ledger task mismatch for {task_id}")
        require(ledger.get("final_acceptance", {}).get("status") == "VERIFIED", f"{task_id} final acceptance is not VERIFIED")
        primary_ids = [entry["atomic_requirement_id"] for entry in ledger["entries"] if entry["role"] == "primary"]
        require(primary_ids == atom_ids, f"Primary atom mismatch for {task_id}: {primary_ids}")
        ledger_records[task_id] = {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": digest(path),
            "primary_atom_ids": atom_ids,
        }
        entries.extend(build_entry(task_id, atom_id, ledger, path) for atom_id in atom_ids)

    image_records = {}
    referenced_images = sorted({image for entry in entries for image in entry["source"].get("source_images", [])})
    require(referenced_images == sorted(IMAGE_PATHS), f"Unexpected phase image set: {referenced_images}")
    for image_id, relative in IMAGE_PATHS.items():
        path = ROOT / relative
        require(path.is_file(), f"Missing full-size image {image_id}: {path}")
        image_records[str(image_id)] = {"path": relative, "sha256": digest(path), "inspected_with_word_context": True}

    atom_ids = [entry["atomic_requirement_id"] for entry in entries]
    require(len(atom_ids) == len(set(atom_ids)) == 21, "F8 phase acceptance requires 21 unique primary atoms")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    result = {
        "schema_version": "f8.phase-acceptance.atomic-ledger.v1",
        "goal_id": "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        "task_id": TASK_ID,
        "phase": "F8",
        "state": "CONTEXT_VERIFIED",
        "created_at": now,
        "updated_at": now,
        "checkpoint_authority": {
            "path": checkpoint.get("schema_version") and "outputs/原系统融合重构执行/evidence/context_recovery/current_checkpoint.json",
            "source_task": "F8-T05",
            "source_state": "CLOSED",
            "authorized_next_step": checkpoint["next_step"],
        },
        "task_atomic_execution_contract": {
            "schema_version": "context-recovery.task-atomic-contract.v1",
            "task_id": TASK_ID,
            "scope_is_task_local": True,
            "standalone_phase_acceptance_contract": True,
            "primary_atomic_requirement_ids": atom_ids,
            "related_atomic_requirement_ids": [],
            "required_understanding_fields": ["product_meaning", "behavior_boundaries", "implementation_scope", "verification_plan"],
            "required_primary_realization_fields": ["implementation_evidence", "verification_evidence", "user_visible_result"],
            "must_read_every_primary_and_related_atom": True,
            "must_correlate_word_paragraphs_and_full_size_images": True,
            "previous_task_understanding_or_evidence_cannot_substitute": True,
            "context_verified_requires_per_atom_understanding": True,
            "editing_forbidden_before_context_verified": True,
            "every_edit_batch_requires_atom_or_protection_mapping": True,
            "ledger_must_be_updated_after_each_edit_or_test_batch": True,
            "ledger_must_remain_active_during_planning_editing_testing_and_review": True,
            "conflicts_require_authoritative_source_recheck": True,
            "evidence_verified_requires_per_atom_realization": True,
            "closure_requires_per_atom_reconciliation_without_group_substitution": True,
            "next_task_forbidden_before_current_task_closed": True,
            "resume_must_continue_from_incomplete_ledger_entries": True,
            "task_close_requires_realization_gate": True,
        },
        "source_ledgers": ledger_records,
        "full_size_image_records": image_records,
        "protection_contracts": {
            "recovery_consistency": "active_manifest、官方checkpoint、00、11、阶段账本和WORKLOG必须指向同一真实断点；旧任务关闭事实只能标记为历史。",
            "legacy_profile": "7.20学习画像的维度、证据和完整页面保持可达；普通浏览零写入。",
            "legacy_path": "7.20学习路径、今日必做与智能组卷门禁保持可达且不被反馈组件替代。",
            "legacy_notes": "7.20笔记编辑、分类、搜索、历史和用户正文保持可用；来源失效不删正文。",
            "legacy_wrong_questions": "7.20错题筛选、解析、反思、相似题、备注、固定、闪卡、重做与导出保持可用。",
            "read_only_browsing": "切月、选日、筛选、展开、来源下钻、分页和跨页浏览不得改变掌握度或新增学习证据。",
            "data_integrity": "所有验收使用隔离SQLite；integrity_check=ok且外键违规为0；正式数据库不得修改。",
            "visual": "1440x900和1366x768均为0溢出、0裁切、0真实碰撞、0小于14px文字、0禁用主题色、0渐变。",
        },
        "entries": entries,
        "execution_batches": [
            {
                "batch": "phase-contract-recovery",
                "mapped_atoms": atom_ids,
                "protection_contracts": ["data_integrity"],
                "changed_files": ["scripts/build_f8_phase_acceptance_contract.py", OUTPUT_PATH.relative_to(ROOT).as_posix()],
                "result": "Built a complete standalone phase-acceptance contract from five verified task ledgers; no business code changed.",
                "verification": "21 unique primary atoms, all source words/understandings present, images 7/21/29 content-addressed, F8-T05 CLOSED and active manifest VERIFIED.",
            },
            {
                "batch": "phase-journey-implementation",
                "status": "FAILED_DIAGNOSIS",
                "mapped_atoms": atom_ids,
                "protection_contracts": [
                    "legacy_profile", "legacy_path", "legacy_notes", "legacy_wrong_questions",
                    "read_only_browsing", "data_integrity", "visual",
                ],
                "changed_files": [
                    "scripts/e2e_f8_t02_wrong_questions.py",
                    "scripts/e2e_f8_t03_notes.py",
                    "scripts/e2e_f8_t04_profile_history.py",
                    "scripts/e2e_f8_t05_learning_feedback.py",
                    "scripts/e2e_f8_phase_acceptance.py",
                    "scripts/finalize_f8_phase_acceptance.py",
                ],
                "expected_result": "One continuous F8 journey and a fail-closed per-atom phase report; no business code changes.",
                "verification": "Compilation passed. First browser run failed in the shared profile-history note filter because the composite fixture no longer exposed exactly 13 note events; failure cleanup then attempted to close an already stopped Playwright browser. No business code was changed and no phase atom was marked verified.",
            },
        ],
        "final_acceptance": {
            "status": "PENDING",
            "required_outcomes": [
                "F8-T01 through F8-T05 reports remain passed and complete.",
                "One continuous service/browser/database journey covers review, wrong questions, notes, profile/history and six-view feedback recovery.",
                "Four 7.20 protected pages retain substantive capability.",
                "Review starts from the real calendar; notes and wrong questions reverse to source; six views agree.",
                "Ordinary browsing performs zero learning-state writes.",
                "Dual desktop, database, build, regression and Impeccable gates pass.",
            ],
        },
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "CONTEXT_VERIFIED", "task": TASK_ID, "atoms": len(entries), "output": OUTPUT_PATH.relative_to(ROOT).as_posix()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
