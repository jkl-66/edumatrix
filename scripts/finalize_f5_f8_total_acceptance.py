#!/usr/bin/env python3
"""Fail-closed reconciliation for the F5-F8 total acceptance ledger."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "outputs" / "原系统融合重构执行"
OUTPUT = BASE / "evidence" / "f5_f8_total_acceptance"
LEDGER_PATH = OUTPUT / "atomic_execution_ledger.json"
JOURNEY_PATH = OUTPUT / "report.json"
CROSSCHECK_PATH = BASE / "12_方案交叉校验报告.json"
ACTIVE_MANIFEST_PATH = BASE / "evidence" / "context_recovery" / "active_manifest.json"
CHECKPOINT_PATH = BASE / "evidence" / "context_recovery" / "current_checkpoint.json"
GOAL_PATH = BASE / "evidence" / "context_recovery" / "goal_contract.md"
F8_PHASE_REPORT_PATH = BASE / "evidence" / "f8_phase_acceptance" / "phase_report.json"
FORMAL_DATABASE_PATH = ROOT / "edumatrix.db"
TOTAL_REPORT_JSON = OUTPUT / "total_report.json"
TOTAL_REPORT_MD = OUTPUT / "total_report.md"
STATUS_PATH = BASE / "00_唯一执行状态.md"
RECOVERY_INDEX_PATH = BASE / "11_上下文恢复与实施索引.md"
WORKLOG_PATH = BASE / "02_融合重构_WORKLOG.md"

EXPECTED_ATOMS = [f"F5F8-R{index:02d}" for index in range(1, 19)]
JOURNEY_ATOMS = EXPECTED_ATOMS[:-1]
FINAL_SUMMARY_BATCH = "r18-final-verification-summary-20260817"
FINALIZATION_BATCH = "total-per-atom-finalization-20260817"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def write_json_atomic(path: Path, value: Any) -> None:
    write_text_atomic(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def resolve_evidence_ref(value: str) -> Path:
    normalized = Path(value.replace("\\", "/"))
    if normalized.parts and normalized.parts[0] == "outputs":
        return ROOT / normalized
    return BASE / normalized


def require_clean_visual(node: Any, label: str = "visual") -> None:
    false_fields = {
        "missingRoot", "documentOverflow", "rootOverflow", "pageOverflow",
        "workspaceOverlap",
    }
    empty_fields = {
        "clipped", "clippedText", "smallText", "collisions",
        "forbiddenThemeHits", "gradients", "forbiddenEffects",
        "decorativeBackgroundImages", "decorativeBackgrounds", "oversizedRadii",
    }
    if isinstance(node, dict):
        for key, value in node.items():
            current = f"{label}.{key}"
            if key in false_fields:
                require(value is False, f"{current} is not false")
            if key in empty_fields:
                require(not value, f"{current} is not empty")
            require_clean_visual(value, current)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            require_clean_visual(value, f"{label}[{index}]")


def validate_context(ledger: dict[str, Any]) -> None:
    active = load(ACTIVE_MANIFEST_PATH)
    checkpoint = load(CHECKPOINT_PATH)
    require(active.get("status") == "VERIFIED", "Active context recovery version is not VERIFIED")
    require(checkpoint.get("phase") == "F8", "Official checkpoint is not in F8")
    require(checkpoint.get("task") == "F8-T05", "Official checkpoint is not F8-T05")
    require(checkpoint.get("state") == "CLOSED", "Official F8-T05 checkpoint is not CLOSED")
    authority = ledger.get("checkpoint_authority", {})
    require(authority.get("source_task") == "F8-T05", "Total ledger checkpoint authority changed")
    require(authority.get("source_state") == "CLOSED", "Total ledger source state changed")

    source_hashes = ledger.get("source_hashes", {})
    require(digest(GOAL_PATH) == source_hashes.get("goal_contract", {}).get("sha256"), "Goal contract hash changed")
    require(digest(F8_PHASE_REPORT_PATH) == source_hashes.get("f8_phase_report", {}).get("sha256"), "F8 phase report hash changed")


def validate_contract(ledger: dict[str, Any]) -> None:
    require(ledger.get("goal_id") == "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION", "Wrong goal")
    require(ledger.get("task_id") == "F5-F8-TOTAL-ACCEPTANCE", "Wrong total-acceptance task")
    require(ledger.get("state") in {"CONTEXT_VERIFIED", "CLOSED"}, "Total ledger is in an invalid state")
    contract = ledger.get("task_atomic_execution_contract", {})
    require(contract.get("task_id") == "F5-F8-TOTAL-ACCEPTANCE", "Wrong atomic contract")
    require(contract.get("standalone_total_acceptance_contract") is True, "Total contract is not standalone")
    require(contract.get("primary_atomic_requirement_ids") == EXPECTED_ATOMS, "Total contract atom order changed")
    require(contract.get("related_atomic_requirement_ids") == [], "Total contract unexpectedly has related atoms")
    required_flags = [
        "must_read_every_primary_and_related_atom",
        "previous_task_understanding_or_evidence_cannot_substitute",
        "context_verified_requires_per_atom_understanding",
        "editing_forbidden_before_context_verified",
        "every_edit_batch_requires_atom_or_protection_mapping",
        "ledger_must_be_updated_after_each_edit_or_test_batch",
        "ledger_must_remain_active_during_planning_editing_testing_and_review",
        "conflicts_require_authoritative_source_recheck",
        "evidence_verified_requires_per_atom_realization",
        "closure_requires_per_atom_reconciliation_without_group_substitution",
        "next_task_forbidden_before_current_task_closed",
        "resume_must_continue_from_incomplete_ledger_entries",
        "task_close_requires_realization_gate",
    ]
    require(all(contract.get(flag) is True for flag in required_flags), "At least one atomic contract gate is false")

    entries = ledger.get("entries", [])
    require([entry.get("atomic_requirement_id") for entry in entries] == EXPECTED_ATOMS, "Ledger atom order changed")
    for entry in entries:
        understanding = entry.get("understanding", {})
        require(understanding.get("confirmed") is True, f"{entry.get('atomic_requirement_id')} understanding is not confirmed")
        for field in contract.get("required_understanding_fields", []):
            require(understanding.get(field), f"{entry.get('atomic_requirement_id')} understanding lacks {field}")
        refs = entry.get("closed_stage_evidence_refs", [])
        require(refs, f"{entry.get('atomic_requirement_id')} lacks closed-stage references")
        for value in refs:
            require(resolve_evidence_ref(value).exists(), f"Missing closed-stage evidence: {value}")


def resolve_screenshot(value: str) -> list[Path]:
    normalized = Path(value.replace("\\", "/"))
    rooted = ROOT / normalized
    if rooted.is_file():
        return [rooted]
    direct = OUTPUT / "browser" / normalized
    if direct.is_file():
        return [direct]
    return list((BASE / "evidence").rglob(normalized.name))


def validate_journey() -> dict[str, Any]:
    report = load(JOURNEY_PATH)
    require(report.get("status") == "PASSED", "Run 30 total journey is not PASSED")
    atoms = report.get("atoms", {})
    require(set(atoms) == set(JOURNEY_ATOMS), "Run 30 atom set is incomplete or contains extras")
    for atom in JOURNEY_ATOMS:
        record = atoms.get(atom, {})
        require(record.get("status") == "PASSED", f"{atom} did not pass Run 30")
        require(record.get("result"), f"{atom} lacks an independent Run 30 result")
        require(record.get("evidence"), f"{atom} lacks independent Run 30 evidence")

    screenshots = list(report.get("screenshots", []))
    require(len(screenshots) == 63, f"Expected 63 screenshots, got {len(screenshots)}")
    missing = [value for value in screenshots if not resolve_screenshot(value)]
    require(not missing, f"Run 30 screenshots are missing: {missing}")
    visual = report.get("visual", {})
    require(len(visual) == 44, f"Expected 44 measured visual surfaces, got {len(visual)}")
    require_clean_visual(visual)

    for field in ("http_errors", "failed_requests", "page_errors", "console_errors", "external_requests"):
        require(not report.get(field), f"Run 30 contains unexpected {field}")
    require(len(report.get("expected_http_errors", [])) == 6, "Run 30 does not record exactly six expected HTTP failures")
    require(len(report.get("expected_network_errors", [])) == 2, "Run 30 does not record exactly two expected network failures")
    require(report.get("runtime", {}).get("browser_instances") == 1, "Run 30 did not use one browser instance")
    require(report.get("cleanup", {}).get("port_closed") is True, "Run 30 did not close its owned port")

    database = report.get("database", {}).get("final", {})
    require(database.get("integrity") == "ok", "Run 30 isolated SQLite integrity is not ok")
    require(database.get("foreign_key_violations") == 0, "Run 30 isolated SQLite has foreign-key violations")
    before = report.get("formal_database_before", {})
    after = report.get("formal_database_after", {})
    require(before == after, "Formal database before/after evidence differs")
    require(before.get("bytes") == 13_152_256, "Formal database size evidence changed")
    require(before.get("sha256") == "E91506822345ABCB1977E679B06DE01753A2BEF6ACA8EFCE59D4E86EA94E5565", "Formal database hash evidence changed")
    require(FORMAL_DATABASE_PATH.stat().st_size == before["bytes"], "Current formal database size differs from Run 30")
    require(digest(FORMAL_DATABASE_PATH) == before["sha256"], "Current formal database hash differs from Run 30")
    return report


def validate_r18(ledger: dict[str, Any]) -> None:
    batches = {item.get("batch"): item for item in ledger.get("execution_batches", [])}
    summary = batches.get(FINAL_SUMMARY_BATCH, {})
    require(summary.get("status") == "PASSED", "R18 final verification summary is not PASSED")
    verification = "\n".join(summary.get("verification", []))
    for token in (
        "273 passed", "6939 modules", "20 checks", "4 individually reviewed false positives",
        "integrity=ok", "port 9180 closed",
    ):
        require(token in verification, f"R18 final verification lacks: {token}")

    crosscheck = load(CROSSCHECK_PATH)
    require(crosscheck.get("all_passed") is True, "12 crosscheck is not all_passed")
    require(crosscheck.get("status") == "PASS", "12 crosscheck status is not PASS")
    require(len(crosscheck.get("checks", [])) == 20, "12 crosscheck does not contain 20 checks")
    require(not [item for item in crosscheck["checks"] if not item.get("passed")], "12 crosscheck contains a failed check")


def append_unique(values: list[str], *items: str) -> list[str]:
    result = list(values)
    for item in items:
        if item not in result:
            result.append(item)
    return result


def replace_required(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    require(old in text, f"{label} no longer contains the expected old state")
    return text.replace(old, new, 1)


def sync_operational_documents(generated_at: str) -> None:
    status = STATUS_PATH.read_text(encoding="utf-8")
    status = replace_required(
        status,
        "F5-F8-TOTAL-ACCEPTANCE-CONTEXT-VERIFIED`",
        "F5-F8-TOTAL-ACCEPTANCE-PASS / F9-T01-NOT-STARTED-PAUSED`",
        "00 status header",
    )
    status = replace_required(status, "最近更新：2026-08-16", "最近更新：2026-08-17", "00 update date")
    status = replace_required(
        status,
        "- 当前唯一合法动作是修复阶段测试器的组合计数、截图目录、浏览器清理和失败报告写入，再重跑 F8 连续旅程。不得重做 F8-T01 至 F8-T05，不得读取、规划或实施 F9。",
        "- F5-F8 总联合验收已经 `PASS`：18 条总验收原子逐条核销，Run 30 连续旅程、最终回归、交叉校验、生产构建、Impeccable、双桌面视觉、数据完整性和进程清理均通过。F9 尚未读取、规划或实施。",
        "00 precise checkpoint",
    )
    status = replace_required(
        status,
        "- F8-T01 至 F8-T05 及 F8 阶段联合验收均已关闭并通过，均不得重做；F5-F8 总联合验收及 F9-F10 尚未完成。",
        "- F8-T01 至 F8-T05、F8 阶段联合验收和 F5-F8 总联合验收均已关闭并通过，均不得重做；F9-F10 尚未开始。",
        "00 remaining work",
    )
    section = "## 6. 下一步"
    require(section in status, "00 lacks the next-step section")
    status = status.partition(section)[0] + section + (
        "\n\nF5-F8 总联合验收为 `CLOSED / PASS`，18 条原子全部 `IMPLEMENTED_AND_VERIFIED`。"
        "Run 30 通过 63 张截图与 44 个视觉面；F2-F8 回归 `273 passed`，12 号交叉校验 `20/20 PASS`，生产构建和最终 Impeccable 均通过。\n\n"
        "唯一下一断点是 `F9 / F9-T01 / NOT_STARTED / PAUSED`。本轮没有读取、规划或实施 F9/F10，没有调用外部模型或公网，"
        "没有修改正式数据库，没有执行 Git 写操作，也没有更新交付包。\n"
    )
    write_text_atomic(STATUS_PATH, status)

    recovery = RECOVERY_INDEX_PATH.read_text(encoding="utf-8")
    recovery = replace_required(
        recovery,
        "F5-F8-TOTAL-ACCEPTANCE-CONTEXT-VERIFIED`",
        "F5-F8-TOTAL-ACCEPTANCE-PASS / F9-T01-NOT-STARTED-PAUSED`",
        "11 status header",
    )
    recovery = replace_required(recovery, "更新：2026-08-16", "更新：2026-08-17", "11 update date")
    section = "## 9. 当前唯一下一步"
    require(section in recovery, "11 lacks the next-step section")
    recovery = recovery.partition(section)[0] + section + (
        "\n\nF5-F8 总联合验收账本 `evidence/f5_f8_total_acceptance/atomic_execution_ledger.json` 已为 `CLOSED / PASS`，"
        "18 条原子全部逐项核销；总报告为 `evidence/f5_f8_total_acceptance/total_report.md`。"
        "唯一恢复断点是 `F9 / F9-T01 / NOT_STARTED / PAUSED`。不得从本结论推断 F9/F10 已开始，恢复后必须等待用户新指令。\n"
    )
    write_text_atomic(RECOVERY_INDEX_PATH, recovery)

    worklog = WORKLOG_PATH.read_text(encoding="utf-8")
    marker = "## WL-F5-F8-TOTAL-002 总联合验收逐原子关闭"
    if marker not in worklog:
        worklog = worklog.rstrip() + "\n\n" + "\n".join([
            marker,
            "",
            f"- 时间：{generated_at}。",
            "- 原子结果：`F5-F8-TOTAL-ACCEPTANCE` 的 `F5F8-R01` 至 `F5F8-R18` 全部为 `IMPLEMENTED_AND_VERIFIED`，总验收账本状态为 `CLOSED`，`PENDING=0`。",
            "- 连续旅程：Run 30 在同一隔离 SQLite、一个 Chromium 和受控服务生命周期内完成 F5-F8 全闭环，保存 63 张截图、测量 44 个视觉面；6 次预期 HTTP 故障和 2 次预期连接中断均恢复，所有意外错误列表为空。",
            "- 自动与视觉：47 个 F2-F8 命名测试文件 `273 passed, 6 warnings`；前端构建转换 6939 个模块；12 号交叉校验 `20/20 PASS`；最终广域 Impeccable 的 4 条 warning 均逐项核实为机械误报，可执行问题为 0。",
            "- 数据与边界：隔离 SQLite `integrity_check=ok`、外键违规 0；正式数据库前后均为 13,152,256 字节且 SHA-256 不变。未调用外部模型或公网，未执行 Git 写操作，未更新交付包。",
            "- 报告：`evidence/f5_f8_total_acceptance/total_report.json` 与 `total_report.md`。唯一下一断点为 `F9 / F9-T01 / NOT_STARTED / PAUSED`；F9/F10 尚未读取、规划或实施。",
        ]) + "\n"
        write_text_atomic(WORKLOG_PATH, worklog)


def reconcile_atoms(ledger: dict[str, Any], journey: dict[str, Any], generated_at: str) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for entry in ledger["entries"]:
        atom = entry["atomic_requirement_id"]
        realization = entry.get("total_realization", {})
        implementation = list(realization.get("implementation_or_protection_evidence", []))
        verification = list(realization.get("verification_evidence", []))
        if atom in JOURNEY_ATOMS:
            record = journey["atoms"][atom]
            implementation = append_unique(
                implementation,
                f"outputs/原系统融合重构执行/evidence/f5_f8_total_acceptance/report.json records {atom}=PASSED in Run 30.",
                record["result"],
            )
            verification = append_unique(
                verification,
                f"Run 30 independent evidence for {atom}: {json.dumps(record['evidence'], ensure_ascii=False)}",
                "Run 30: 63 screenshots, 44 clean visual surfaces, zero unexpected browser/network errors, isolated SQLite integrity ok and formal database unchanged.",
            )
        else:
            implementation = append_unique(
                implementation,
                "R18 final verification summary is PASSED and the dedicated total-acceptance finalizer reconciles all 18 atoms without entering F9.",
                "00, 11 and the append-only WORKLOG are synchronized to F5-F8 PASS and the paused F9-T01 not-started handoff.",
            )
            verification = append_unique(
                verification,
                "R18 final gates: Run 30 PASSED; 273 F2-F8 tests passed; production build transformed 6939 modules; 12 crosscheck passed 20 checks; broad Impeccable had 0 actionable findings after four reviewed false positives.",
            )
        user_visible = realization.get("user_visible_result")
        require(user_visible, f"{atom} lacks a user-visible result")
        rationale = (
            "No deferral. Total acceptance reused the closed F5-F8 product implementation in isolated SQLite, "
            "preserved the four 7.20 pages and read-only boundaries, did not call an external model or public network, "
            "did not modify the formal database, and did not perform Git or delivery-package writes."
        )
        entry["total_realization"] = {
            "status": "IMPLEMENTED_AND_VERIFIED",
            "implementation_or_protection_evidence": implementation,
            "verification_evidence": verification,
            "user_visible_result": user_visible,
            "compatibility_or_defer_rationale": rationale,
            "reconciled_at": generated_at,
        }
        summaries.append({
            "atom": atom,
            "title": entry["source"]["title"],
            "status": "IMPLEMENTED_AND_VERIFIED",
            "user_visible_result": user_visible,
            "evidence": "Run 30" if atom in JOURNEY_ATOMS else "R18 final gates",
        })
    require(len(summaries) == 18, "Total acceptance did not reconcile all 18 atoms")
    return summaries


def render_markdown(summaries: list[dict[str, Any]]) -> str:
    lines = [
        "# EduMatrix F5-F8 总联合验收报告",
        "",
        "> 结论：`PASS`",
        "> 范围：F5 至 F8 的完整学生学习闭环；18 条总验收原子全部逐条核销。",
        "> 边界：F9/F10 未读取、规划或实施；下一断点仅为 `F9 / F9-T01 / NOT_STARTED / PAUSED`。",
        "",
        "## 1. 总体结果",
        "",
        "同一匿名学生在隔离 SQLite、一个 Chromium 实例和受控服务生命周期内完成了总路径选择知识点、九类资源生成与恢复、资源学习、测验、交互模型、代码运行与点评、费曼、智能组卷、知识库选区、笔记、错题、复习以及六页持续反馈。Run 30 保存 63 张截图，44 个视觉面全部通过。",
        "",
        "## 2. 18 条逐项核销",
        "",
        "| 原子 | 验收能力 | 独立证据 | 结果 |",
        "|---|---|---|---|",
    ]
    for item in summaries:
        lines.append(f"| `{item['atom']}` | {item['title']} | {item['evidence']} | PASS |")
    lines.extend([
        "",
        "## 3. 最终门禁",
        "",
        "- F2-F8 命名回归：`273 passed`，6 条既有弃用警告。",
        "- 前端生产构建：`6939 modules transformed`；仅有既有大分块建议。",
        "- 12 号规格交叉校验：`20/20 PASS`。",
        "- 最终广域 Impeccable：4 条 warning 均逐项核实为机械误报，可执行问题为 0。",
        "- 双桌面视觉：44 个测量面均无溢出、裁切、碰撞、小于 14px 文字、禁用主题色或渐变。",
        "- 故障恢复：6 次预期 HTTP 故障、2 次预期连接中断均恢复；意外 HTTP、请求、页面、控制台和外部请求均为 0。",
        "- 数据：隔离 SQLite `integrity_check=ok`、外键违规 0；正式数据库前后均为 13,152,256 字节且 SHA-256 不变。",
        "",
        "## 4. 边界声明",
        "",
        "- 未调用外部模型，未依赖公网。",
        "- 未执行 Git 暂存、提交、推送或历史改写。",
        "- 未更新比赛交付包。",
        "- 本报告只表示 F5-F8 已通过总联合验收，不表示 F0-F10 全部完成。",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    require(LEDGER_PATH.is_file(), f"Missing total ledger: {LEDGER_PATH}")
    ledger = load(LEDGER_PATH)
    validate_context(ledger)
    validate_contract(ledger)
    journey = validate_journey()
    validate_r18(ledger)

    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    summaries = reconcile_atoms(ledger, journey, generated_at)
    sync_operational_documents(generated_at)
    report = {
        "schema_version": "f5-f8.total-acceptance.v1",
        "status": "PASS",
        "generated_at": generated_at,
        "scope": "F5 through F8 total continuous learner journey",
        "atomic_requirements": {
            "total": 18,
            "implemented_and_verified": 18,
            "pending": 0,
            "entries": summaries,
        },
        "continuous_journey": {
            "status": "PASS",
            "report": JOURNEY_PATH.relative_to(ROOT).as_posix(),
            "screenshots": 63,
            "visual_surfaces": 44,
            "expected_http_failures": 6,
            "expected_network_failures": 2,
            "unexpected_errors": 0,
        },
        "regression": {"test_files": 47, "passed": 273, "warnings": 6},
        "production_build": {"status": "PASS", "modules_transformed": 6939},
        "crosscheck": {"status": "PASS", "checks": 20, "failed": 0},
        "impeccable": {
            "actionable_findings": [],
            "reviewed_false_positives": [
                "Knowledge.vue:1183 mutually exclusive OCR status classes were cross-paired by the detector.",
                "Knowledge.vue:1183 parent/sibling text class was cross-paired with an inactive amber class.",
                "Review.vue:191 mutually exclusive red/red and slate/slate status classes were cross-paired.",
                "WrongQuestionBook.vue:538 is semantic inline error/result feedback, not a decorative card side-tab.",
            ],
        },
        "database": {
            "isolated": True,
            "integrity": "ok",
            "foreign_key_violations": 0,
            "formal_database_modified": False,
            "formal_database_bytes": 13_152_256,
            "formal_database_sha256": "E91506822345ABCB1977E679B06DE01753A2BEF6ACA8EFCE59D4E86EA94E5565",
        },
        "external_model_called": False,
        "public_network_required": False,
        "git_write_performed": False,
        "delivery_package_modified": False,
        "next_step": "Advance only to F9 / F9-T01 / NOT_STARTED / PAUSED without reading or implementing F9.",
    }

    ledger["state"] = "CLOSED"
    ledger["updated_at"] = generated_at
    ledger["final_acceptance"] = {
        "status": "PASS",
        "completed_at": generated_at,
        "primary_atoms": 18,
        "implemented_and_verified": 18,
        "pending": 0,
        "screenshots": 63,
        "visual_surfaces": 44,
        "next_step": "F9 / F9-T01 / NOT_STARTED / PAUSED; F9 content remains unread.",
    }
    ledger["execution_batches"] = [
        item for item in ledger.get("execution_batches", [])
        if item.get("batch") != FINALIZATION_BATCH
    ]
    ledger["execution_batches"].append({
        "batch": FINALIZATION_BATCH,
        "status": "PASSED",
        "updated_at": generated_at,
        "mapped_atoms": EXPECTED_ATOMS,
        "protection_contracts": list(ledger.get("protection_contracts", {})),
        "changed_files": [
            "scripts/finalize_f5_f8_total_acceptance.py",
            "outputs/原系统融合重构执行/evidence/f5_f8_total_acceptance/atomic_execution_ledger.json",
            "outputs/原系统融合重构执行/evidence/f5_f8_total_acceptance/total_report.json",
            "outputs/原系统融合重构执行/evidence/f5_f8_total_acceptance/total_report.md",
            "outputs/原系统融合重构执行/00_唯一执行状态.md",
            "outputs/原系统融合重构执行/11_上下文恢复与实施索引.md",
            "outputs/原系统融合重构执行/02_融合重构_WORKLOG.md",
        ],
        "result": "All 18 total-acceptance atoms have independent implementation/protection evidence, verification evidence and a user-visible result; no group-level claim substitutes for an atom entry.",
        "verification": [
            "Run 30 PASSED R01-R17 with 63 screenshots and 44 clean visual surfaces.",
            "R18 passed 273 tests, production build, 20 crosschecks and broad Impeccable review.",
            "Isolated SQLite and formal database protections passed; no external model, public network, Git write or delivery-package update occurred.",
        ],
    })

    write_json_atomic(TOTAL_REPORT_JSON, report)
    write_text_atomic(TOTAL_REPORT_MD, render_markdown(summaries))
    write_json_atomic(LEDGER_PATH, ledger)
    print("F5-F8 total acceptance PASS: 18 atoms, 63 screenshots, 44 visual surfaces")


if __name__ == "__main__":
    main()
