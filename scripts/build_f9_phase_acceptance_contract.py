#!/usr/bin/env python3
"""Build the standalone atomic contract for F9 phase acceptance."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECOVERY = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery"
LEDGER_DIR = RECOVERY / "atomic_requirement_ledgers" / "EDUMATRIX-F9-F10-CONTEXT-SAFE-FUSION-COMPLETION"
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f9_phase_acceptance"
OUTPUT_PATH = OUTPUT_DIR / "atomic_execution_ledger.json"
TASK_ID = "F9-PHASE-ACCEPTANCE"

EXPECTED = {
    "F9-T01": [
        "G14-R01", "G14-R02", "G14-R03", "G14-R04", "G14-R05",
        "G14-R06", "G14-R07", "G14-R08", "G20-R09",
    ],
    "F9-T04": [
        "G23-R01", "G23-R02", "G23-R03", "G23-R04", "G23-R05", "G23-R06",
        "G24-R01", "G24-R02", "G24-R03", "G24-R04", "G24-R05", "G24-R06", "G24-R07",
        "G27-R01", "G27-R02", "G27-R03", "G27-R04", "G27-R05", "G27-R06", "G27-R07",
    ],
}

TASK_CONTRACTS = ("F9-T01", "F9-T02", "F9-T03", "F9-T04")
IMAGE_PATHS = {
    17: "outputs/原系统融合重构执行/evidence/dual_version_audit/improvement_ideas/17_image17.png",
    18: "outputs/原系统融合重构执行/evidence/dual_version_audit/improvement_ideas/18_image18.png",
    19: "outputs/原系统融合重构执行/evidence/dual_version_audit/improvement_ideas/19_image19.png",
    20: "outputs/原系统融合重构执行/evidence/dual_version_audit/improvement_ideas/20_image20.png",
}
REALIZED_STATUSES = {
    "IMPLEMENTED_AND_VERIFIED", "COMPATIBILITY_VERIFIED", "COORDINATION_VERIFIED",
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
    require(source["understanding"].get("confirmed") is True, f"{task_id}/{atom_id} understanding is not confirmed")
    require(source["realization"].get("status") in REALIZED_STATUSES, f"{task_id}/{atom_id} is not reconciled")
    for field in ("product_meaning", "behavior_boundaries", "implementation_scope", "verification_plan"):
        require(source["understanding"].get(field), f"{task_id}/{atom_id} lacks {field}")
    require(source["source"].get("full_original_words"), f"{task_id}/{atom_id} lacks full source words")

    return {
        "atomic_requirement_id": atom_id,
        "role": "primary",
        "source_task": task_id,
        "source_task_role": source["role"],
        "source_ledger": {
            "path": ledger_path.relative_to(ROOT).as_posix(),
            "sha256": digest(ledger_path),
        },
        "source": source["source"],
        "understanding": {
            "product_meaning": source["understanding"]["product_meaning"],
            "behavior_boundaries": [
                *source["understanding"]["behavior_boundaries"],
                "本阶段只联合验证已关闭实现，不新增、替换或削弱 F0-F8 与 F9-T01 至 F9-T04 的业务事实源。",
            ],
            "implementation_scope": [
                "在同一隔离 SQLite、同一服务进程和同一无头 Chromium 实例中连续验证该原子。",
                "只新增阶段验收脚本、报告、截图和逐原子证据；发现真实回归时才允许按原子边界修复。",
            ],
            "verification_plan": [
                *source["understanding"]["verification_plan"],
                "把本原子映射到连续旅程动作、数据库前后快照、双桌面截图和阶段报告，禁止用总体测试数替代逐条证据。",
            ],
            "confirmed": True,
        },
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
    require(checkpoint.get("task") == "F9-T04" and checkpoint.get("state") == "CLOSED", "F9-T04 is not CLOSED")
    authorized_next_step = checkpoint.get("next_step", "")
    require(
        "F9 阶段联合验收" in authorized_next_step
        or "F9 phase-level joint acceptance" in authorized_next_step,
        "Checkpoint does not authorize F9 phase acceptance",
    )

    ledger_records = {}
    ledgers = {}
    for task_id in TASK_CONTRACTS:
        path = source_ledger(task_id)
        ledger = load(path)
        require(ledger.get("task") == task_id, f"Ledger task mismatch for {task_id}")
        require(ledger.get("entries"), f"{task_id} has no atomic entries")
        require(all(entry["understanding"].get("confirmed") is True for entry in ledger["entries"]), f"{task_id} has unconfirmed atoms")
        require(all(entry["realization"].get("status") in REALIZED_STATUSES for entry in ledger["entries"]), f"{task_id} has unreconciled atoms")
        ledger_records[task_id] = {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": digest(path),
            "atom_ids": [entry["atomic_requirement_id"] for entry in ledger["entries"]],
        }
        ledgers[task_id] = (ledger, path)

    entries = []
    for task_id, atom_ids in EXPECTED.items():
        ledger, path = ledgers[task_id]
        entries.extend(build_entry(task_id, atom_id, ledger, path) for atom_id in atom_ids)

    atom_ids = [entry["atomic_requirement_id"] for entry in entries]
    require(len(atom_ids) == len(set(atom_ids)) == 29, "F9 phase acceptance requires 29 unique atoms")
    referenced_images = sorted({image for entry in entries for image in entry["source"].get("source_images", [])})
    require(referenced_images == sorted(IMAGE_PATHS), f"Unexpected phase image set: {referenced_images}")
    image_records = {}
    for image_id, relative in IMAGE_PATHS.items():
        path = ROOT / relative
        require(path.is_file(), f"Missing full-size image {image_id}: {path}")
        image_records[str(image_id)] = {
            "path": relative,
            "sha256": digest(path),
            "inspected_with_word_context": True,
        }

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    result = {
        "schema_version": "f9.phase-acceptance.atomic-ledger.v1",
        "goal_id": "EDUMATRIX-F9-F10-CONTEXT-SAFE-FUSION-COMPLETION",
        "task_id": TASK_ID,
        "phase": "F9",
        "state": "CONTEXT_VERIFIED",
        "created_at": now,
        "updated_at": now,
        "checkpoint_authority": {
            "path": "outputs/原系统融合重构执行/evidence/context_recovery/current_checkpoint.json",
            "source_task": "F9-T04",
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
            "closed_scope": "F0-F8 与 F9-T01 至 F9-T04 的关闭事实不可重做；阶段验收只复用正式实现。",
            "market_copy": "市场保存必须创建所有者隔离的真实个人副本；上游下架不得静默覆盖或删除副本。",
            "teacher_read_only": "教师只能读取授权课程和学生，干预或测评不得直接修改掌握度。",
            "admin_minimal_scope": "管理员只保留账号、模型、内容审核和系统状态四项任务。",
            "formal_roles": "正式工作区只承认学生、教师和管理员；历史 assistant 不得获得私有对象权限。",
            "learning_state": "市场浏览与后台读写不得伪造学习证据；只有可信学生行为可改变掌握聚合。",
            "audit_privacy": "审计仅保存业务摘要，不得包含密钥、令牌、密码、提示词、私有推理、trace、原始日志或敏感原文。",
            "data_integrity": "验收只使用隔离 SQLite；integrity_check=ok、外键违规为0，正式数据库不修改。",
            "visual": "1440x900 与 1366x768 均要求0溢出、0裁切、0真实碰撞、0小于14px文字、0低对比、0禁用主题色和0渐变。",
            "environment": "只使用本地确定性模型和本地数据，不调用外部模型或外网，结束后释放服务端口。",
        },
        "entries": entries,
        "execution_batches": [{
            "batch": "PA-B00-phase-contract-recovery",
            "status": "VERIFIED",
            "mapped_atoms": atom_ids,
            "protection_contracts": ["closed_scope", "data_integrity", "environment"],
            "changed_files": [
                "scripts/build_f9_phase_acceptance_contract.py",
                "outputs/原系统融合重构执行/evidence/f9_phase_acceptance/phase_task_card.md",
                OUTPUT_PATH.relative_to(ROOT).as_posix(),
            ],
            "result": "Built a standalone F9 phase-acceptance contract from all four closed F9 task ledgers; no business code changed.",
            "verification": "29 unique atoms, complete source words and confirmed understandings, images 17-20 inspected with Word paragraphs 36-38, F9-T04 CLOSED and active manifest VERIFIED.",
            "fail_closed_diagnostics": [
                "Attempt 1 rejected an equivalent English checkpoint next-step phrase; authorization matching was corrected without changing the checkpoint.",
                "Attempt 2 rejected an incorrect expected count of 30; the explicit atom groups were recounted as 9+6+7+7=29 and the uniqueness gate was corrected.",
            ],
        }],
        "final_acceptance": {
            "status": "PENDING",
            "required_outcomes": [
                "F9-T01 through F9-T04 closed-task ledgers and reports remain valid.",
                "One isolated database, service process and Chromium instance cover marketplace, teacher, administrator and authorization journeys.",
                "Market personal copies survive upstream withdrawal without learning-state writes.",
                "Teacher mastery stays read-only and administrator scope stays limited to four tasks.",
                "Student, teacher, administrator and historical assistant boundaries are enforced by the server.",
                "Audit/API/DOM scans expose no sensitive fields or private reasoning.",
                "Dual desktop, database, regression, production build and visual gates pass.",
            ],
        },
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "CONTEXT_VERIFIED", "task": TASK_ID, "atoms": len(entries), "output": OUTPUT_PATH.relative_to(ROOT).as_posix()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
