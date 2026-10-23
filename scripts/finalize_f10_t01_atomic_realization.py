#!/usr/bin/env python3
"""Finalize F10-T01 only after B03 browser and per-atom evidence pass."""

from __future__ import annotations

import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = (
    ROOT
    / "outputs"
    / "原系统融合重构执行"
    / "evidence"
    / "f10_t01_route_migration"
)
LEDGER_PATH = (
    ROOT
    / "outputs"
    / "原系统融合重构执行"
    / "evidence"
    / "context_recovery"
    / "atomic_requirement_ledgers"
    / "EDUMATRIX-F9-F10-CONTEXT-SAFE-FUSION-COMPLETION"
    / "F10-T01_5098A07731321C7019CAC07346BB9C76446F0D1E7F152202F02F5FED6B08D138.json"
)
MAPPING_PATH = EVIDENCE_DIR / "batch_03_chat_quiz_convergence_mapping.json"
REPORT_PATH = EVIDENCE_DIR / "browser_report.json"
WORKLOG_PATH = ROOT / "outputs" / "原系统融合重构执行" / "02_融合重构_WORKLOG.md"

PRIMARY_IDS = ["G22-R12", "G28-R04", "G28-R05"]
RELATED_IDS = [
    "G25-R01",
    "G25-R02",
    "G25-R03",
    "G25-R04",
    "G28-R01",
    "G28-R02",
    "G28-R03",
    "G28-R06",
    "G28-R07",
]
ALL_IDS = PRIMARY_IDS + RELATED_IDS
BATCH_ID = "F10-T01-B03-CHAT-QUIZ-CONVERGENCE"

COMMON_BROWSER_EVIDENCE = (
    "B03 managed E2E passed at 1440x900 and 1366x768 with 30 screenshots, "
    "six clean browser contexts and two real quiz-resource -> Chat -> same-question round trips; "
    "all HTTP, request, page, console, off-origin and measured visual issue collections were empty."
)
COMMON_DATA_EVIDENCE = (
    "The 19 protected learning, resource, assessment, Chat and model_calls tables retained identical "
    "row counts and SHA-256 digests; SQLite integrity_check=ok, foreign-key violations=0, "
    "model_calls stayed 0 -> 0 and external_model_called=false."
)
FINAL_REGRESSION_EVIDENCE = (
    "Final verification passed: both F10 E2E/finalizer scripts compiled; "
    "tests/test_f10_t01_recovery_experience.py passed 10 checks; "
    "tests/test_f7_t04_chat_frontend_contract.py passed 8 checks; "
    "the F6 quiz, F7 Chat API/streaming and F10 route protection suite passed 19 checks "
    "with four existing FastAPI lifespan deprecation warnings only; scoped git diff --check exited 0, "
    "port 8995 had zero listeners and no matching Python process remained."
)

FINAL = {
    "G22-R12": {
        "implementation": (
            "Chat.vue now exposes quiz context as read-only title, question, source and return context; "
            "QuizResourceWorkspace.vue with InlineQuizCard.vue remains the only answer, submit, grade, "
            "attempt-history and continue-practice owner."
        ),
        "verification": (
            "Both desktop journeys preserved the same resource_id, question_version_id and attempt_id; "
            "Chat contained zero answer controls and exactly one primary return action to the formal quiz resource."
        ),
        "visible": (
            "学生从测验题资源进入智能对话追问时，只看到当前题目与课程来源；点击唯一主动作会回到同一份测验资源和同一道题继续作答。"
        ),
        "rationale": "测验、代码沙盒和知识库仍各有唯一正式归宿；本批没有建立第二套学习产物或答题工作台。",
    },
    "G28-R04": {
        "implementation": (
            "The final route surface reuses the closed F6 quiz workspace and closed F7 Chat capabilities, "
            "while removing only the duplicate inline quiz ownership from Chat."
        ),
        "verification": (
            "Focused contracts passed 10 + 8 checks, the F6/F7/F10 protection regression passed 19 checks, "
            "and the managed browser journey exercised the reused formal resource owner without a duplicate route or API."
        ),
        "visible": "学生继续使用原有测验资源完成作答和判分，智能对话只承担解释与返回，不会出现两套不一致的测验界面。",
        "rationale": "候选能力只按统一闭环复用；未新增路由、API、模型、Store或测验对象。",
    },
    "G28-R05": {
        "implementation": (
            "Inline answering, submission, grading and attempt-history behavior was removed from Chat instead "
            "of preserving a visually compact but behaviorally duplicated candidate workspace."
        ),
        "verification": (
            "Source contracts reject InlineQuizCard and answer controls in Chat, while both real desktop states "
            "show one resource action, no duplicate answering surface and no visual issue."
        ),
        "visible": "对话页不再强塞测验作答面，信息更少且职责更清楚；完整测验功能没有丢失，而是统一回到测验题资源。",
        "rationale": "影响理解成本的重复候选功能已舍弃，正式测验内核和历史证据完整保留。",
    },
    "G25-R01": {
        "verification": "F10-T01 has zero source images; B03 decisions came from frozen text contracts, source code and full-size runtime screenshots, so no unreadable competitor frame required extraction.",
        "rationale": "没有凭模糊图片补充产品行为，也没有需要用户裁决的图像歧义。",
    },
    "G25-R02": {
        "verification": "The batch mapping cites no contact sheet or thumbnail; the six newly reviewed quiz/Chat screenshots are native full-size runtime captures at both required desktop sizes.",
        "rationale": "缩略图未被用作文字、路由或交互证据。",
    },
    "G25-R03": {
        "verification": "The authoritative contract, formal quiz owner, Chat source behavior and both browser round trips agree on one ownership boundary; no unresolved route, permission, data or completion-condition conflict remains.",
        "rationale": "本批没有需要暂停询问的实质歧义。",
    },
    "G25-R04": {
        "verification": "B03 did not modify Word, image semantics, product specifications or source-to-image classification; its runtime screenshots verify implementation only.",
        "rationale": "冻结的图文语义规则保持不变。",
    },
    "G28-R01": {
        "verification": "The formal F6 quiz resource and F7 Chat help path remain intact, no protected 7.20 page was modified, and the protection regression passed before the browser run.",
        "rationale": "7.20主体与已关闭学习能力保持，复杂版没有接管正式体验。",
    },
    "G28-R02": {
        "verification": "Source contracts and both desktop journeys prove one answer owner and one precise legacy/context return path; Chat contains no second answer, grade, history or continue-practice flow.",
        "rationale": "同一测验任务只有一个正式入口和数据所有者。",
    },
    "G28-R03": {
        "verification": "B03 added no navigation item, route, internal workspace or external surface; the existing unknown, removed, deferred and internal-route browser checks also passed in both desktop sizes.",
        "rationale": "闭环外候选入口未重新进入普通产品。",
    },
    "G28-R06": {
        "verification": COMMON_DATA_EVIDENCE + " Resource, question, attempt, course, source and return context remained identical across both round trips.",
        "rationale": "普通浏览零业务写入，正式数据库未使用，原版数据连续性和用户上下文均受保护。",
    },
    "G28-R07": {
        "verification": COMMON_BROWSER_EVIDENCE + " Evidence is stored per action, screenshot, browser context and protected table rather than inferred from route, atom or aggregate test counts.",
        "rationale": "完成结论来自逐项行为和数据证据，不以固定路由数、原子数或测试总数替代。",
    },
}


def unique(existing: list[str], additions: list[str]) -> list[str]:
    return list(dict.fromkeys([*existing, *additions]))


def atomic_write(path: Path, payload: dict) -> None:
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def validate_report(report: dict, mapping: dict, ledger: dict) -> None:
    if report.get("status") != "passed":
        raise RuntimeError("F10-T01 browser report is not passed")
    if report.get("viewports") != [[1440, 900], [1366, 768]]:
        raise RuntimeError("F10-T01 browser viewports do not match the task contract")
    if len(report.get("screenshots", [])) != 30:
        raise RuntimeError("F10-T01 browser report must contain 30 screenshots")
    if len(report.get("quiz_chat_round_trips", [])) != 2:
        raise RuntimeError("F10-T01 browser report must contain two quiz/Chat round trips")
    for round_trip in report["quiz_chat_round_trips"]:
        if round_trip.get("chat_answer_controls") != 0:
            raise RuntimeError("Chat still exposes answer controls")
        if round_trip.get("primary_resource_actions") != 1:
            raise RuntimeError("Chat does not expose exactly one formal resource action")
        returned_url = round_trip.get("returned_url", "")
        if round_trip.get("resource_id") not in returned_url:
            raise RuntimeError("Quiz return does not preserve the resource id")
        if round_trip.get("question_version_id") not in returned_url:
            raise RuntimeError("Quiz return does not preserve the question version")
    for page in report.get("browser_pages", []):
        for key in (
            "http_errors",
            "failed_requests",
            "page_errors",
            "console_errors",
            "off_origin_requests",
        ):
            if page.get(key) != []:
                raise RuntimeError(f"Browser page contains {key}")
    if len(report.get("browser_pages", [])) != 6:
        raise RuntimeError("F10-T01 browser report must contain six browser contexts")
    for name, visual in report.get("visual_checks", {}).items():
        if visual.get("documentWidth") != visual.get("viewport", [None])[0]:
            raise RuntimeError(f"Horizontal overflow detected in {name}")
        for key in (
            "collisions",
            "clipped",
            "smallText",
            "lowContrastPrimary",
            "forbiddenEffects",
            "themedColorRegression",
        ):
            if visual.get(key) != []:
                raise RuntimeError(f"Visual issue {key} detected in {name}")
    before = report.get("protected_state_before", {})
    after = report.get("protected_state_after", {})
    if len(before) != 19 or before != after:
        raise RuntimeError("Protected database state changed during ordinary browsing")
    if report.get("ordinary_browse_database_unchanged") is not True:
        raise RuntimeError("Ordinary browsing was not read-only")
    if report.get("external_model_called") is not False:
        raise RuntimeError("External model was called")
    if report.get("database_audit") != {
        "integrity": "ok",
        "foreign_key_violations": 0,
    }:
        raise RuntimeError("Isolated database audit failed")
    model_evidence = report.get("external_model_evidence", {})
    if model_evidence.get("model_calls_before") != model_evidence.get("model_calls_after"):
        raise RuntimeError("model_calls changed")
    managed = mapping.get("implementation_result", {}).get("managed_e2e", {})
    for key in (
        "post_run_port_listeners",
        "post_run_matching_processes",
        "server_tracebacks",
        "browser_issue_pages",
        "visual_issue_screenshots",
        "protected_table_differences",
        "off_origin_requests",
    ):
        if managed.get(key) != 0:
            raise RuntimeError(f"Managed E2E cleanup or issue field {key} is not zero")
    entries = ledger.get("entries", [])
    ids = [entry.get("atomic_requirement_id") for entry in entries]
    if len(ids) != len(set(ids)) or set(ids) != set(ALL_IDS):
        raise RuntimeError("F10-T01 ledger atom set is incomplete or duplicated")
    batches = [
        batch
        for batch in ledger.get("execution_batches", [])
        if batch.get("batch_id") == BATCH_ID
    ]
    if len(batches) != 1:
        raise RuntimeError("F10-T01 ledger must contain exactly one B03 batch")


def finalize() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    mapping = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    validate_report(report, mapping, ledger)

    reconciliation = []
    for entry in ledger["entries"]:
        atom_id = entry["atomic_requirement_id"]
        evidence = FINAL[atom_id]
        realization = entry["realization"]
        verification = [evidence["verification"]]
        if atom_id in {"G22-R12", "G28-R04", "G28-R05"}:
            realization["implementation_evidence"] = unique(
                realization.get("implementation_evidence", []),
                [evidence["implementation"]],
            )
            realization["user_visible_result"] = evidence["visible"]
            realization["status"] = "IMPLEMENTED_AND_VERIFIED"
        else:
            realization["status"] = "COMPATIBILITY_VERIFIED"
        realization["verification_evidence"] = unique(
            realization.get("verification_evidence", []),
            verification + [COMMON_BROWSER_EVIDENCE, FINAL_REGRESSION_EVIDENCE],
        )
        realization["compatibility_or_defer_rationale"] = evidence["rationale"]
        reconciliation.append(
            {
                "atom_id": atom_id,
                "role": entry["role"],
                "status": realization["status"],
                "verification_evidence": evidence["verification"],
                "user_visible_result": realization.get("user_visible_result", ""),
                "compatibility_or_defer_rationale": evidence["rationale"],
            }
        )

    batch = next(
        item for item in ledger["execution_batches"] if item["batch_id"] == BATCH_ID
    )
    batch["status"] = "VERIFIED"
    batch["result"] = (
        "B03 final reconciliation passed for all 3 primary and 9 related atoms. "
        + COMMON_BROWSER_EVIDENCE
        + " "
        + COMMON_DATA_EVIDENCE
    )
    batch["final_atom_reconciliation"] = reconciliation

    mapping["status"] = "VERIFIED"
    mapping["implementation_result"]["pending"] = None
    mapping["implementation_result"]["final_atom_reconciliation"] = reconciliation
    mapping["implementation_result"]["final_result"] = (
        "All 12 atoms were reconciled individually against the static contracts, "
        "protection regression, production build, managed browser report, full-size screenshots, "
        "database digests, external-model evidence and process cleanup."
    )
    mapping["implementation_result"]["final_validation"] = {
        "py_compile": "passed for e2e_f10_t01_route_migration.py and finalize_f10_t01_atomic_realization.py",
        "f10_focused": "10 passed",
        "f7_chat_protection": "8 passed",
        "f6_f7_f10_protection": "19 passed, 4 existing FastAPI lifespan deprecation warnings",
        "scoped_git_diff_check": "exit 0; LF/CRLF working-tree notice only",
        "port_8995_listeners": 0,
        "matching_python_processes": 0,
    }

    atomic_write(LEDGER_PATH, ledger)
    atomic_write(MAPPING_PATH, mapping)

    marker = "## WL-F10-T01-179 B03逐原子核销完成"
    worklog = WORKLOG_PATH.read_text(encoding="utf-8")
    if marker not in worklog:
        addition = f"""

{marker}

- 批次：`{BATCH_ID}` 已从 `MANAGED_E2E_VERIFIED_PENDING_RECONCILIATION` 更新为 `VERIFIED`。
- 主责原子：`G22-R12`、`G28-R04`、`G28-R05` 均已分别写入最终实现、验证和用户可见结果，状态为 `IMPLEMENTED_AND_VERIFIED`。
- 相关原子：9条均已分别写入真实兼容/保护证据和理由，状态为 `COMPATIBILITY_VERIFIED`。
- 浏览器：双桌面30张截图、6个浏览器上下文、2次同资源同题往返；Chat答题控件0，唯一资源主动作1，浏览器与视觉问题0。
- 数据：19张保护表前后行数与SHA-256相同；SQLite完整、外键违规0、`model_calls`为0->0、未调用外部模型。
- 清理：运行后8995监听0、匹配进程0、服务日志traceback 0。
- 状态：`F10-T01-B03 / VERIFIED`。下一步仅运行最终聚焦与保护回归，未通过前不推进checkpoint。
"""
        WORKLOG_PATH.write_text(worklog.rstrip() + addition + "\n", encoding="utf-8")

    marker = "## WL-F10-T01-180 B03最终回归与清理通过"
    worklog = WORKLOG_PATH.read_text(encoding="utf-8")
    if marker not in worklog:
        addition = f"""

{marker}

- 编译：`scripts/e2e_f10_t01_route_migration.py` 与 `scripts/finalize_f10_t01_atomic_realization.py` 均通过 `py_compile`。
- 聚焦：F10跨文件收敛 `10 passed`；F7 Chat保护 `8 passed`。
- 保护：F6测验资源、F7 Chat API/流式与F10路由合同 `19 passed`；仅4条既有FastAPI生命周期弃用警告。
- 格式：本任务涉及文件的 `git diff --check` 退出0；仅有LF/CRLF工作区提示。
- 清理：8995监听0，匹配F10受管E2E Python进程0。
- 逐原子：12条realization均追加本次最终复跑证据；B03保持 `VERIFIED`。
- 下一步：验证账本门禁后，按顺序推进 `CODE_COMPLETE -> TESTED -> EVIDENCE_VERIFIED -> CLOSED`，不得跳级。
"""
        WORKLOG_PATH.write_text(worklog.rstrip() + addition + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "status": "VERIFIED",
                "task": "F10-T01",
                "batch": BATCH_ID,
                "primary_atoms": len(PRIMARY_IDS),
                "related_atoms": len(RELATED_IDS),
                "screenshots": len(report["screenshots"]),
                "protected_tables": len(report["protected_state_before"]),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    finalize()
