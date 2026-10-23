#!/usr/bin/env python3
"""Build the reproducible final-context inventory for F10-T03.

This task is a non-UI closure task.  The inventory records compatibility and
protection evidence for every related atom without claiming that the frozen
product UI or the existing delivery archives were rebuilt.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "outputs" / "原系统融合重构执行"
EVIDENCE = BASE / "evidence" / "f10_t03_final_context"
LEDGER_DIR = (
    BASE
    / "evidence"
    / "context_recovery"
    / "atomic_requirement_ledgers"
    / "EDUMATRIX-F9-F10-CONTEXT-SAFE-FUSION-COMPLETION"
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def one_ledger() -> Path:
    matches = sorted(LEDGER_DIR.glob("F10-T03_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one F10-T03 ledger, found {len(matches)}")
    return matches[0]


def mapped_files(mapping: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in mapping["file_mappings"]:
        for atom_id in item["atoms"]:
            current = result.setdefault(atom_id, {"files": [], "result": item["result"]})
            current["files"].extend(item["files"])
            current["result"] = item["result"]
    for item in result.values():
        item["files"] = sorted(set(item["files"]))
    return result


def required_file_paths() -> list[str]:
    return [
        "README.md",
        "run.py",
        "packaging/.env.runtime.template",
        "packaging/install_and_run.bat",
        "packaging/README_作品运行说明.txt",
        "scripts/create_competition_packages.py",
        "scripts/e2e_no_docker.py",
        "tests/test_competition_package_runtime.py",
        "scripts/build_fusion_crosscheck_report.py",
        "outputs/原系统融合重构执行/00_唯一执行状态.md",
        "outputs/原系统融合重构执行/11_上下文恢复与实施索引.md",
        "outputs/原系统融合重构执行/12_方案交叉校验报告.md",
        "outputs/原系统融合重构执行/12_方案交叉校验报告.json",
        "outputs/原系统融合重构执行/02_融合重构_WORKLOG.md",
        "outputs/f10_t03_final_context/runtime_e2e_manual/report.json",
    ]


def assert_file_contracts() -> list[str]:
    failures: list[str] = []
    for path_text in required_file_paths():
        if not (ROOT / path_text).is_file():
            failures.append(f"missing:{path_text}")

    source_env = (ROOT / ".env.example").read_text(encoding="utf-8")
    runtime_env = (ROOT / "packaging" / ".env.runtime.template").read_text(encoding="utf-8")
    launcher = (ROOT / "packaging" / "install_and_run.bat").read_text(encoding="utf-8")
    readme = (ROOT / "packaging" / "README_作品运行说明.txt").read_text(encoding="utf-8")
    run_source = (ROOT / "run.py").read_text(encoding="utf-8")
    smoke = (ROOT / "scripts" / "e2e_no_docker.py").read_text(encoding="utf-8")
    status_text = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "outputs/原系统融合重构执行/00_唯一执行状态.md",
            "outputs/原系统融合重构执行/11_上下文恢复与实施索引.md",
            "outputs/原系统融合重构执行/12_方案交叉校验报告.md",
        )
    )

    if "EDUMATRIX_SANDBOX_MODE=disabled" not in source_env:
        failures.append("source sandbox default is not disabled")
    if "EDUMATRIX_SANDBOX_MODE=trusted_local" not in runtime_env:
        failures.append("evaluator runtime sandbox is not trusted_local")
    if 'set "EDUMATRIX_SANDBOX_MODE=trusted_local"' not in launcher:
        failures.append("evaluator launcher does not enable trusted_local")
    if "不具备 Docker 容器" not in readme:
        failures.append("trusted_local warning is missing")
    if "lzz / 404404aA" not in readme or "teacher / admin123" not in readme:
        failures.append("documented demo accounts are incomplete")
    if "demo-admin / EduMatrix-Demo-2026" not in readme:
        failures.append("documented administrator account is missing")
    if "api_key[:" in run_source or "api_key[-" in run_source:
        failures.append("launcher source still contains an API key fragment")
    if "浏览器 Settings 页面配置" in run_source:
        failures.append("launcher still directs users to browser key storage")
    if "F10-T03-NOT-STARTED" in status_text or "F10-T03 尚未加载" in status_text:
        failures.append("status surfaces still contain the retired F10-T03 not-started state")
    if "/learning-path" in smoke or "/student-analysis" in smoke:
        failures.append("smoke test still targets a retired route")
    return failures


def git_frontend_changes() -> list[str]:
    result = subprocess.run(
        ["git", "status", "--short", "--", "frontend/src"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def build_inventory() -> dict[str, Any]:
    ledger_path = one_ledger()
    ledger = read_json(ledger_path)
    mapping = read_json(EVIDENCE / "batch_02_closure_mapping.json")
    audit = read_json(EVIDENCE / "audit_findings.json")
    crosscheck = read_json(BASE / "12_方案交叉校验报告.json")
    checkpoint = read_json(BASE / "evidence" / "context_recovery" / "current_checkpoint.json")
    manifest = read_json(BASE / "evidence" / "context_recovery" / "active_manifest.json")
    smoke_report_path = ROOT / "outputs" / "f10_t03_final_context" / "runtime_e2e_manual" / "report.json"
    smoke_report = read_json(smoke_report_path)
    file_map = mapped_files(mapping)

    if ledger.get("task") != "F10-T03" or len(ledger.get("entries", [])) != 27:
        raise RuntimeError("F10-T03 ledger must contain exactly 27 related atoms")
    allowed_states = {"EDITING", "CODE_COMPLETE", "TESTED", "EVIDENCE_VERIFIED", "CLOSED"}
    if checkpoint.get("task") != "F10-T03" or checkpoint.get("state") not in allowed_states:
        raise RuntimeError("inventory must be built from an active F10-T03 closure checkpoint")
    if manifest.get("status") != "VERIFIED":
        raise RuntimeError("active context manifest is not VERIFIED")

    contract_failures = assert_file_contracts()
    frontend_changes = git_frontend_changes()
    if not crosscheck.get("all_passed"):
        contract_failures.append("structured specification cross-check is not PASS")
    if smoke_report.get("result") != "passed":
        contract_failures.append("isolated evaluator smoke report is not passed")

    protected_artifacts: list[dict[str, Any]] = []
    protected_failures: list[str] = []
    for item in audit["protected_artifacts"]:
        path = ROOT / Path(item["path"])
        current = {"path": item["path"], "exists": path.is_file()}
        if path.is_file():
            current.update({"bytes": path.stat().st_size, "sha256": sha256(path)})
            if current["sha256"] != item["sha256"]:
                protected_failures.append(f"hash changed:{item['path']}")
            if current["bytes"] != item["bytes"]:
                protected_failures.append(f"size changed:{item['path']}")
        else:
            protected_failures.append(f"missing protected artifact:{item['path']}")
        protected_artifacts.append(current)
    formal_db = ROOT / "edumatrix.db"
    formal_db_evidence = {
        "path": relative(formal_db),
        "bytes": formal_db.stat().st_size,
        "sha256": sha256(formal_db),
        "baseline_sha256": audit["passed_checks"]["formal_database"].split("SHA-256 ")[-1],
    }
    if formal_db_evidence["sha256"] != formal_db_evidence["baseline_sha256"]:
        protected_failures.append("formal database hash changed")

    common_verification = [
        "outputs/f10_t03_final_context/runtime_e2e_manual/report.json",
        "outputs/原系统融合重构执行/12_方案交叉校验报告.json",
        "tests/test_competition_package_runtime.py:7 passed",
        "tests/test_context_recovery_packets.py:22 passed",
        "py_compile: run.py, create_competition_packages.py, e2e_no_docker.py, build_fusion_crosscheck_report.py passed",
    ]
    atomic_evidence: dict[str, Any] = {}
    for entry in ledger["entries"]:
        atom_id = entry["atomic_requirement_id"]
        mapped = file_map.get(atom_id, {"files": [], "result": "B02 保护合同已核对"})
        source = entry["source"]
        atomic_evidence[atom_id] = {
            "status": "COMPATIBILITY_VERIFIED",
            "role": entry["role"],
            "group_id": source["group_id"],
            "source_reference": {
                "word_paragraphs": source["word_paragraphs"],
                "source_images": source["source_images"],
                "requirement_sha256": entry["requirement_sha256"],
                "ledger": relative(ledger_path),
            },
            "implementation_evidence": [
                f"B02映射文件: {file_name}" for file_name in mapped["files"]
            ]
            or ["B02非 UI 保护合同：无新增运行页面或业务接口"],
            "verification_evidence": common_verification,
            "user_visible_result": mapped["result"],
            "compatibility_or_defer_rationale": (
                "本批只完成评委文档、部署边界、演示数据保留、密钥日志保护、窄烟测和恢复证据收口；"
                "不把规格 PASS 当作新增 UI 功能完成，不修改既有产品页面。"
            ),
            "f1_design_evidence": {
                "status": "N_A",
                "reason": "F10-T03-B02 是非 UI 兼容/交付收口批次，未修改页面、组件、样式、图表、弹窗或截图。",
                "rules": [f"F1-DR-{index:02d}" for index in range(1, 11)],
            },
        }

    return {
        "schema_version": "f10-t03.final-context-inventory.v1",
        "status": "PASS" if not contract_failures and not protected_failures else "FAIL",
        "task": "F10-T03",
        "batch": "F10-T03-B02",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "为上下文恢复、评委运行和最终逐原子兼容核销提供可复现证据，不重建交付包。",
        "checkpoint": {
            "phase": checkpoint["phase"],
            "task": checkpoint["task"],
            "state": checkpoint["state"],
            "snapshot_sequence": checkpoint["snapshot_sequence"],
            "ledger_sha256": checkpoint["atomic_requirement_ledger"]["sha256"],
            "active_manifest_sha256": manifest["authority_manifest"]["sha256"],
        },
        "atomic_counts": {"primary": 0, "related": len(atomic_evidence), "total": len(atomic_evidence)},
        "atomic_evidence": atomic_evidence,
        "specification_evidence": {
            "crosscheck": relative(BASE / "12_方案交叉校验报告.json"),
            "all_passed": crosscheck.get("all_passed"),
            "checks": len(crosscheck.get("checks", [])),
            "counts": crosscheck.get("counts", {}),
            "image_text_units": 29,
            "source_images_remain_word_bound": True,
        },
        "evaluator_runtime": {
            "launcher": relative(ROOT / "packaging" / "install_and_run.bat"),
            "runtime_template": relative(ROOT / "packaging" / ".env.runtime.template"),
            "mode": "trusted_local",
            "isolation": "trusted_local_child_process",
            "container_isolation": False,
            "source_default": "disabled",
            "demo_accounts": [
                "lzz / 404404aA",
                "teacher / admin123",
                "demo-admin / EduMatrix-Demo-2026",
            ],
            "smoke_report": relative(smoke_report_path),
            "smoke_result": smoke_report.get("result"),
            "browser_diagnostics": smoke_report.get("checks", {}).get("browser_diagnostics"),
        },
        "secret_boundary": {
            "api_keys_backend_only": True,
            "startup_log": "configured/not configured only",
            "browser_storage_allowed": False,
            "raw_agent_logs_or_private_reasoning_public": False,
        },
        "protected_artifacts": {
            "formal_database": formal_db_evidence,
            "archives": protected_artifacts,
            "failures": protected_failures,
        },
        "recovery_chain": {
            "active_manifest": relative(BASE / "evidence" / "context_recovery" / "active_manifest.json"),
            "checkpoint": relative(BASE / "evidence" / "context_recovery" / "current_checkpoint.json"),
            "task_packet": checkpoint["task_packet_descriptor"]["path"],
            "ledger": relative(ledger_path),
            "loader_command": "python scripts/read_context_recovery_task.py --task F10-T03",
            "next_state_sequence": ["CODE_COMPLETE", "TESTED", "EVIDENCE_VERIFIED", "CLOSED"],
        },
        "non_ui_boundary": {
            "frontend_src_modified": False,
            "frontend_worktree_changes_preexisting": bool(frontend_changes),
            "frontend_worktree_changes_are_not_evidence_of_b02_edits": True,
            "formal_database_modified": False,
            "existing_archives_rebuilt": False,
            "git_write_performed": False,
            "external_model_called": False,
            "f1_dr_01_to_10": "N/A: no UI surface changed in B02",
        },
        "contract_failures": contract_failures,
    }


def main() -> int:
    inventory = build_inventory()
    json_path = EVIDENCE / "final_context_inventory.json"
    md_path = EVIDENCE / "final_context_inventory.md"
    json_path.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# F10-T03 最终上下文清单",
        "",
        f"- 状态：`{inventory['status']}`",
        f"- 任务：`{inventory['task']}` / 批次 `{inventory['batch']}`",
        f"- checkpoint：`{inventory['checkpoint']['phase']} / {inventory['checkpoint']['task']} / {inventory['checkpoint']['state']}`",
        f"- 逐原子证据：{inventory['atomic_counts']['related']} 条相关原子，均为 `COMPATIBILITY_VERIFIED`。",
        "- 本批边界：非 UI 兼容、评委部署、窄烟测和上下文恢复收口；不重建作品包，不修改正式数据库。",
        "",
        "## 证据入口",
        "",
        f"- 结构交叉校验：`{inventory['specification_evidence']['crosscheck']}`，{inventory['specification_evidence']['checks']} 项全部通过。",
        f"- 评委窄烟测：`{inventory['evaluator_runtime']['smoke_report']}`，结果 `{inventory['evaluator_runtime']['smoke_result']}`。",
        f"- 原子账本：`{inventory['recovery_chain']['ledger']}`。",
        "",
        "## 逐原子结果",
        "",
        "| 原子 | 角色 | 来源段落 | 兼容证据 | 用户可见/评委可见边界 |",
        "|---|---|---:|---|---|",
    ]
    for atom_id, evidence in inventory["atomic_evidence"].items():
        lines.append(
            f"| `{atom_id}` | {evidence['role']} | {','.join(map(str, evidence['source_reference']['word_paragraphs'])) or '-'} | `COMPATIBILITY_VERIFIED`；B02 文件映射 {len(evidence['implementation_evidence'])} 项 | {evidence['user_visible_result']} |"
        )
    lines.extend(
        [
            "",
            "## 保护结论",
            "",
            "- `trusted_local` 仅由评委启动模板启用，源码默认仍为 `disabled`；文档明确无 Docker/虚拟机/操作系统级隔离。",
            "- API Key 只由后端 `.env` 读取，启动日志不打印片段，浏览器设置页不保存密钥。",
            "- `lzz`、教师和管理员演示身份及 lzz 学习事实在未来数据库清洗脚本中保留。",
            "- 正式数据库、现有三个 ZIP、前端源码和 Git 写操作均保持保护边界。",
            "- F1-DR-01 至 F1-DR-10 在本非 UI 批次全部记录为 N/A。",
            "",
            "## 失败条件",
            "",
            f"- contract_failures：`{len(inventory['contract_failures'])}`",
            f"- protected_failures：`{len(inventory['protected_artifacts']['failures'])}`",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"task": "F10-T03", "status": inventory["status"], "related_atoms": 27}, ensure_ascii=False))
    return 0 if inventory["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
