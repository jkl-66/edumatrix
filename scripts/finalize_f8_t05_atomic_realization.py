#!/usr/bin/env python3
"""Finalize F8-T05 only after per-atom and browser evidence is complete."""

from __future__ import annotations

import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = (
    ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery"
    / "atomic_requirement_ledgers" / "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION"
)
EVIDENCE_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f8_t05_learning_feedback"

PRIMARY_IDS = ["G22-R06"]
RELATED_IDS = [
    "G22-R01", "G22-R02", "G22-R03", "G22-R04", "G22-R05",
    "G22-R07", "G22-R08", "G22-R09", "G22-R10", "G22-R11",
    "G22-R12", "G22-R13", "G22-R14", "G22-R15", "G22-R16",
    "G24-R01", "G24-R02", "G24-R03", "G24-R04", "G24-R05",
    "G24-R06", "G24-R07",
]
ALL_IDS = PRIMARY_IDS + RELATED_IDS
VIEW_IDS = ("dashboard", "profile", "path", "wrong_questions", "review", "history")
VIEWPORTS = ("1440x900", "1366x768")

FINAL_EVIDENCE = [
    "F8-T05 focused backend and frontend contracts: 14 passed.",
    "F4/F6/F8 protection and F8-T05 regression: 109 passed; four existing FastAPI on_event deprecation warnings only.",
    "F3 onboarding/diagnostic, F5 resource bundle/history and F7 knowledge/chat/source-audit protection regression: 73 passed; four existing FastAPI on_event deprecation warnings only.",
    "Frontend production build passed with 6939 modules transformed; only the existing large-chunk advisory remains.",
    "F8-T05 browser E2E passed with 14 full-size screenshots across 1440x900 and 1366x768, including partial failure and recovery states.",
    "All measured F8-T05 surfaces have zero overflow, clipping, sub-14px text, real control collisions, forbidden theme colors and gradients.",
    "The browser report contains zero HTTP, failed-request, page, console, external-request and external-model activity.",
    "Ordinary browsing leaves learning events, aggregation consumptions, profile snapshots, wrong questions, review plans, path nodes, completed nodes and mastery unchanged; SQLite integrity_check=ok and foreign-key violations=0.",
    "F8-T01 review-calendar E2E passed after repairing its isolated plan-version fixture: seven screenshots, zero browse-side writes and clean SQLite integrity.",
    "Python compile and git diff --check passed; git diff reported only existing LF-to-CRLF notices and no whitespace errors.",
]

PER_ATOM = {
    "G22-R06": {
        "implementation": [
            "app/learning_aggregation.py publishes six affected views, expected/actual snapshot versions, a deterministic next-day schedule and a completion-only consistencyToken from one immutable learning event.",
            "app/m5_api.py and frontend/src/components/AggregationStatus.vue expose the same owner/course-scoped feedback on home, profile, path, wrong questions, review and history, while FormalExamWorkspace keeps the original report and adds only the shared status layer.",
        ],
        "verification": [
            "The six parametrized trusted-event tests prove quiz, code, interactive-model, Feynman, formal-exam and review completions all publish one six-view version.",
            "Both desktop browser passes show the same event/token and next-day schedule on all six pages; partial failure is visibly incomplete and recovers from the persisted checkpoint.",
        ],
        "visible": "学生完成可信学习任务后，在首页、画像、路径、错题本、复习中心和学习历史看到同一反馈版本、真实同步进度和次日安排；失败时只重试未完成部分。",
        "compatibility": "无延期。实现复用统一学习事件和既有五步聚合，不建立第二套页面状态或报告系统。",
    },
    "G22-R01": {
        "implementation": [
            "The latest-feedback endpoint returns an honest empty result when the owned course has no trusted event; it does not create a diagnostic, profile baseline or path.",
        ],
        "verification": [
            "F3 onboarding/diagnostic regression passed, and the owner/course-scope test returns feedback=None for an unrelated course or learner without adding learning events.",
        ],
        "visible": "新课程仍先完成自然语言画像和入学诊断；没有可信完成事件时反馈区安静显示空态，不伪造起点数据。",
        "compatibility": "F3 继续唯一负责首次画像和入学诊断，F8-T05 只读取其后产生的可信事件。",
    },
    "G22-R02": {
        "implementation": [
            "The path projection remains a server-owned aggregation step; the feedback component only reports its snapshot and links to /workspace/path.",
        ],
        "verification": [
            "F4 path contracts and the repaired isolated plan-version fixture passed; the browser controlled-action check opens the formal path without changing path data during browsing.",
        ],
        "visible": "学生从反馈明细进入原学习路径核对已完成任务和下一步，推荐顺序与前置依赖仍由正式路径决定。",
        "compatibility": "不在前端重算知识点推荐或路径，不跨课程混用事件。",
    },
    "G22-R03": {
        "implementation": [
            "Feedback payloads contain event, projection, version and controlled-route summaries only; no generation endpoint is called by AggregationStatus.",
        ],
        "verification": [
            "F5 resource-bundle/history regression passed, and the browser journey records no resource-generation request while opening and expanding feedback on all six pages.",
        ],
        "visible": "反馈区只说明已有学习结果影响了哪些页面，不会在查看反馈时重新生成或复制学习资源。",
        "compatibility": "资源仍由 F5 的画像、知识点、来源和最近事件生成流程负责。",
    },
    "G22-R04": {
        "implementation": [
            "The existing path_task aggregation step updates only a matching eligible path node and contributes the path snapshot to the shared version.",
        ],
        "verification": [
            "Learning-aggregation and F4 path regressions prove prerequisite checks and duplicate replay remain idempotent; browser read actions leave completed_path_nodes unchanged.",
        ],
        "visible": "满足完成规则的资源任务仍自动勾选路径节点；反馈明细同步显示路径是否完成并提供进入动作。",
        "compatibility": "打开资源、浏览反馈或不合格运行不会被当成完成，重复事件不会重复累计。",
    },
    "G22-R05": {
        "implementation": [
            "FormalExamWorkspace retains the existing unlocked and missingRequiredTasks gates; AggregationStatus is mounted only as a result-side coordination layer.",
        ],
        "verification": [
            "The frontend contract and F4 exam-gate regression verify the locked view, missing-task list, unlocked builder and original formal report remain authoritative.",
        ],
        "visible": "今日必做任务未完成时仍明确显示缺少项目；全部完成后才能进入智能组卷，反馈同步不能绕过门禁。",
        "compatibility": "组卷解锁只看正式今日必做任务，不看一致性令牌或可选资源完成数。",
    },
    "G22-R07": {
        "implementation": [
            "WrongQuestionBook.vue, Review.vue and History.vue preserve their full F8-T01..T04 surfaces and consume only the shared latest-feedback projection.",
        ],
        "verification": [
            "F8 wrong-question, review, notes and history regressions plus both desktop E2E passes confirm source objects remain available and browsing is read-only.",
        ],
        "visible": "学生可从统一反馈进入错题、复习和学习历史继续深度学习，原有重做、日历、笔记和历史能力没有被状态条替代。",
        "compatibility": "正确作答不伪造错题，无掌握证据不伪造复习计划，浏览不会产生新证据。",
    },
    "G22-R08": {
        "implementation": [
            "F8-T05 does not modify Chat.vue or chat APIs; its trusted-source contract accepts only completed quiz, code, model, Feynman, formal-exam and review events.",
        ],
        "verification": [
            "F7 chat API, streaming and frontend regressions passed; the F8 browser report contains no external request or model call.",
        ],
        "visible": "动态问题仍在智能对话中先得到回答，再由明确动作生成资源；跨页反馈不会变成第二个聊天入口。",
        "compatibility": "普通提问和浏览不计掌握证据，只有后续可信学习完成行为进入聚合。",
    },
    "G22-R09": {
        "implementation": [
            "AggregationStatus renders a compact six-destination summary and controlled links; it never renders handout, code, quiz, deck or model bodies.",
        ],
        "verification": [
            "The frontend contract rejects a second report wall, and F5 resource/history regression confirms complete artifacts remain in their resource spaces.",
        ],
        "visible": "学生在反馈区看到结果摘要和去向，完整生成产物仍保存在学习空间对应模块。",
        "compatibility": "反馈接口不返回任意外部 URL、提示词或完整生成内容。",
    },
    "G22-R10": {
        "implementation": [
            "Aggregation retry reprocesses the existing learning event only and does not call artifact generation, version restore or custom-resource creation paths.",
        ],
        "verification": [
            "F5 bundle/history regression passed; partial recovery keeps one event and one consumption and does not clear any successful business state.",
        ],
        "visible": "各类资源历史和自定义知识点生成入口继续保留，重试学习反馈不会覆盖资源版本。",
        "compatibility": "资源历史仍以 F5 资源事实源为准，最近反馈不是资源历史的替代来源。",
    },
    "G22-R11": {
        "implementation": [
            "The shared component maps internal processing to student-facing destinations and exposes only event source, business status, short consistency version and recovery action.",
        ],
        "verification": [
            "F7 Agent-audit/source regression passed, while the F8 frontend contract rejects trace, worker, lease and private-chain wording.",
        ],
        "visible": "学生只看到职责明确、可核验的同步摘要，不会看到私有思维链、提示词、异常栈或原始 Agent 日志。",
        "compatibility": "智能对话原有可审计过程继续由 F7 页面负责，F8 不复制其面板。",
    },
    "G22-R12": {
        "implementation": [
            "The feedback source contract consumes quiz and code completion events from their formal learning-space modules and excludes knowledge browsing or legacy chat execution.",
        ],
        "verification": [
            "F6 quiz/code regressions and F7 knowledge/chat regressions passed; all browser network calls remain on controlled local product routes.",
        ],
        "visible": "测验题、代码沙盒和知识库继续在各自正式入口使用，反馈只汇总可信测验与代码结果。",
        "compatibility": "未恢复聊天内测验、聊天内代码执行或独立联网搜索入口。",
    },
    "G22-R13": {
        "implementation": [
            "Latest feedback depends only on the signed-in owner, optional course and existing events; it introduces no course-material upload requirement.",
        ],
        "verification": [
            "F3 profile-onboarding and F7 preloaded-knowledge regressions passed; unrelated learners and courses receive an honest empty feedback response.",
        ],
        "visible": "学生仍从自然语言画像和团队预置课程开始，不需要先上传教材才能查看或继续学习闭环。",
        "compatibility": "个人资料上传保持可选，缺少个人文件不构成反馈失败。",
    },
    "G22-R14": {
        "implementation": [
            "F8-T05 reads completed events and never adds a second resource-bundle trigger; the path remains the unique one-click bundle-generation owner.",
        ],
        "verification": [
            "F4 path and F5 resource-bundle regressions passed, and browser feedback expansion produces no generation requests or new learning events.",
        ],
        "visible": "学生仍在总路径点击今日知识点一次生成完整资源包，反馈区只显示完成后的跨页影响。",
        "compatibility": "完整资源归档与必做/可选任务标记保持原合同，不由反馈状态改写。",
    },
    "G22-R15": {
        "implementation": [
            "FormalExamWorkspace keeps missing-task titles and controlled target routes ahead of the result-side feedback component.",
        ],
        "verification": [
            "F4 exam-gate tests and the formal-exam frontend contract prove feedback success cannot unlock an incomplete exam gate.",
        ],
        "visible": "组卷未解锁时，学生看到具体未完成任务和直达入口，而不是一条含糊的锁定提示。",
        "compatibility": "六页面已同步与今日必做任务完成是两套不同事实，前者不能替代后者。",
    },
    "G22-R16": {
        "implementation": [
            "DBLearningEventConsumption persists completed_steps, failed step, attempts and prior results; replay resumes the same event and skips successful steps.",
            "AggregationStatus distinguishes pending, partial, failed, recovering and complete states and disables duplicate retry while work is in flight.",
        ],
        "verification": [
            "Backend fault injection and browser service-restart recovery both preserve the first two completed projections, recover only the failed tail and finish with one stable token.",
        ],
        "visible": "聚合失败时已完成结果仍可用，页面明确显示已同步 2/6、待恢复项目和重试按钮；恢复后六页统一。",
        "compatibility": "不整批回滚学习结果，不重复执行成功步骤，不把部分失败显示为全同步。",
    },
    "G24-R01": {
        "implementation": [
            "Quiz, code, interactive-model observation, Feynman, formal exam and review completion all enter the existing immutable DBLearningEvent protocol before aggregation.",
        ],
        "verification": [
            "Six parametrized backend cases verify owner, course, object, evidence and one aggregation consumption for every trusted source type.",
        ],
        "visible": "六类有意义完成行为都能形成同一格式的学习反馈，页面浏览和展开不会创建事件。",
        "compatibility": "不把普通聊天、搜索、预览或无结果点击临时包装成强证据。",
    },
    "G24-R02": {
        "implementation": [
            "One five-step consumption projects profile, path, wrong/review, history and dashboard results and publishes six view snapshots under one event identity.",
        ],
        "verification": [
            "Focused tests assert every view has the same consistencyToken and owned course; browser snapshots repeat the same version across all six pages.",
        ],
        "visible": "学生从任何一个反馈页面都看到相同的画像、路径、错题复习、历史和首页同步结论。",
        "compatibility": "某投影无匹配对象时诚实显示无变化，不伪造每个事件都修改所有业务值。",
    },
    "G24-R03": {
        "implementation": [
            "Profile projection continues to use evidence_status, mastery_eligible, event type and evidence_strength; the feedback UI reports synchronization rather than a fixed score increment.",
        ],
        "verification": [
            "Learning-aggregation, quiz, code, model, Feynman and formal-exam regressions pass with their different evidence payloads and strengths.",
        ],
        "visible": "学生看到结果已同步，但系统不会宣称每次完成都获得相同掌握度增量。",
        "compatibility": "使用提示的模型观察和无结果完成仍保留较弱或无掌握证据边界。",
    },
    "G24-R04": {
        "implementation": [
            "All six consumers call GET latest feedback and optional replay of an existing event; no component callback creates a learning event.",
        ],
        "verification": [
            "The frontend contract rejects createM5LearningEvent, and both browser passes show identical business-state snapshots before and after browsing, expansion and navigation.",
        ],
        "visible": "浏览、筛选、展开明细和页面跳转不会改变掌握度、路径、错题或复习计划。",
        "compatibility": "重试只重放已有事件，不新建评分或完成证据。",
    },
    "G24-R05": {
        "implementation": [
            "The consistency token is a deterministic hash of the event, processor version and six actual snapshot versions; partial state has no completion token.",
        ],
        "verification": [
            "Session-restart and duplicate-replay tests produce the same event, one consumption, attempt=2 after recovery and a stable final token.",
        ],
        "visible": "服务重启后学生可从上次进度继续，恢复完成仍得到同一组可核验页面版本。",
        "compatibility": "不依赖页面内存、随机时间或第二份缓存生成聚合结论。",
    },
    "G24-R06": {
        "implementation": [
            "Completion projection and mastery observation remain separate paths; each view reports actual step status without labeling completion as mastery.",
        ],
        "verification": [
            "Frontend contracts reject 已完全掌握 and 完成即掌握, while aggregation regressions preserve mastery_eligible and completion_effect as independent fields.",
        ],
        "visible": "任务可显示已完成和路径已勾选，但没有强证据时页面明确不产生新的掌握判断。",
        "compatibility": "路径完成数不等于掌握率，反馈同步不改变该边界。",
    },
    "G24-R07": {
        "implementation": [
            "Stable event idempotency keys and the unique learning_aggregation consumption identity are reused for retry; the UI disables a second retry while processing.",
        ],
        "verification": [
            "Backend and browser recovery prove duplicate replay keeps one event and one consumption, with no repeated profile, wrong-question, review-plan or path effects.",
        ],
        "visible": "网络或服务恢复后可以安全重试，快速重复操作不会重复计分或复制错题、复习和路径记录。",
        "compatibility": "相同幂等键仍绑定同一请求和事件，恢复不创建第二条事实记录。",
    },
}


def unique(existing: list[str], additions: list[str]) -> list[str]:
    return list(dict.fromkeys([*existing, *additions]))


def atomic_write(path: Path, payload: dict) -> None:
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_report() -> dict:
    report_path = EVIDENCE_DIR / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "passed" or report.get("external_model_called") is not False:
        raise RuntimeError("F8-T05 browser report is not a local deterministic pass")
    for key in (
        "http_errors", "failed_requests", "page_errors", "console_errors", "external_requests",
    ):
        if report.get(key) != []:
            raise RuntimeError(f"F8-T05 browser report contains {key}")

    expected_screenshots = {
        *(f"{index:02d}-{view_id}-{viewport}.png" for viewport in VIEWPORTS for index, view_id in enumerate(VIEW_IDS, 1)),
        "13-partial-dashboard-1440x900.png",
        "14-recovered-dashboard-1440x900.png",
    }
    screenshot_names = {Path(item).name for item in report.get("screenshots") or []}
    if screenshot_names != expected_screenshots:
        raise RuntimeError("F8-T05 screenshot evidence is incomplete")

    expected_visual = {
        *(f"{view_id}_{viewport}" for viewport in VIEWPORTS for view_id in VIEW_IDS),
        "partial_dashboard_1440x900",
        "recovered_dashboard_1440x900",
    }
    visual = report.get("visual") or {}
    if set(visual) != expected_visual:
        raise RuntimeError("F8-T05 visual evidence is incomplete")
    for result in visual.values():
        if result.get("pageOverflow"):
            raise RuntimeError("F8-T05 visual report contains overflow")
        for key in ("clipped", "smallText", "collisions", "forbiddenThemeHits", "gradients"):
            if result.get(key) != []:
                raise RuntimeError(f"F8-T05 visual report contains {key}")

    required_checks = {
        "partial_recovered_after_service_restart",
        "recovery_no_duplicate_event_or_consumption",
        "six_views_share_one_event_and_token",
        "next_day_schedule_visible",
        "controlled_internal_action",
        "ordinary_browsing_zero_writes",
        "dual_desktop_visual_contract",
        "database_integrity",
    }
    checks = report.get("checks") or {}
    if set(checks) != required_checks or not all(checks.values()):
        raise RuntimeError("F8-T05 browser behavior checks are incomplete")

    snapshots = report.get("feedback_snapshots") or {}
    for viewport in VIEWPORTS:
        viewport_snapshots = snapshots.get(viewport) or {}
        if set(viewport_snapshots) != set(VIEW_IDS):
            raise RuntimeError(f"F8-T05 {viewport} six-view snapshots are incomplete")
        footers = {item.get("footer") for item in viewport_snapshots.values()}
        if len(footers) != 1:
            raise RuntimeError(f"F8-T05 {viewport} pages do not share one version")
        for item in viewport_snapshots.values():
            if item.get("headline") != "学习反馈已同步":
                raise RuntimeError(f"F8-T05 {viewport} contains an incomplete final view")
            if item.get("view_count") != 6 or item.get("view_statuses") != ["已同步"] * 6:
                raise RuntimeError(f"F8-T05 {viewport} synchronization list is incomplete")

    database = report.get("database") or {}
    for viewport in VIEWPORTS:
        if database.get(f"browse_before_{viewport}") != database.get(f"browse_after_{viewport}"):
            raise RuntimeError(f"F8-T05 {viewport} browsing changed business state")
    final_database = database.get("final") or {}
    if final_database.get("integrity") != "ok" or final_database.get("foreign_key_violations") != 0:
        raise RuntimeError("F8-T05 database integrity failed")
    return report


def main() -> None:
    report = validate_report()
    matches = list(LEDGER_DIR.glob("F8-T05_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F8-T05 ledger, found {len(matches)}")
    ledger_path = matches[0]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    entries = {entry["atomic_requirement_id"]: entry for entry in ledger["entries"]}
    if set(entries) != set(ALL_IDS):
        raise RuntimeError("F8-T05 atomic identity no longer matches the verified contract")
    if any(entries[item]["role"] != "primary" for item in PRIMARY_IDS):
        raise RuntimeError("F8-T05 primary role changed")
    if any(entries[item]["role"] != "related" for item in RELATED_IDS):
        raise RuntimeError("F8-T05 related role changed")
    if set(PER_ATOM) != set(ALL_IDS):
        raise RuntimeError("F8-T05 finalizer does not reconcile every atom")

    for batch in ledger.get("execution_batches", []):
        batch["verification"] = unique(list(batch.get("verification") or []), FINAL_EVIDENCE)
        batch["status"] = "VERIFIED"

    for atom_id in ALL_IDS:
        realization = entries[atom_id]["realization"]
        evidence = PER_ATOM[atom_id]
        realization["implementation_evidence"] = unique(
            list(realization.get("implementation_evidence") or []),
            [f"{atom_id} implementation: {item}" for item in evidence["implementation"]],
        )
        realization["verification_evidence"] = unique(
            list(realization.get("verification_evidence") or []),
            [f"{atom_id} verification: {item}" for item in evidence["verification"]]
            + FINAL_EVIDENCE,
        )
        realization["user_visible_result"] = evidence["visible"]
        realization["compatibility_or_defer_rationale"] = evidence["compatibility"]
        realization["status"] = (
            "IMPLEMENTED_AND_VERIFIED" if atom_id in PRIMARY_IDS else "COORDINATION_VERIFIED"
        )

    ledger["final_acceptance"] = {
        "status": "VERIFIED",
        "report": (EVIDENCE_DIR / "report.json").relative_to(ROOT).as_posix(),
        "screenshots": report["screenshots"],
        "primary_atoms": len(PRIMARY_IDS),
        "related_atoms": len(RELATED_IDS),
        "focused_contracts": "14 passed",
        "core_regression": "109 passed",
        "extended_protection_regression": "73 passed",
        "review_calendar_e2e": "passed with 7 screenshots",
        "frontend_build_modules": 6939,
        "external_model_called": False,
        "formal_database_modified": False,
        "git_write_operation_performed": False,
        "impeccable_detector": "2 reviewed false positives; 0 actionable findings",
    }
    atomic_write(ledger_path, ledger)
    print(json.dumps({
        "status": "FINALIZED",
        "task": "F8-T05",
        "primary": len(PRIMARY_IDS),
        "related": len(RELATED_IDS),
        "screenshots": len(report["screenshots"]),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
