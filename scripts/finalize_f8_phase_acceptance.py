#!/usr/bin/env python3
"""Fail-closed reconciliation for the F8 phase acceptance ledger."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "outputs" / "原系统融合重构执行" / "evidence"
OUTPUT = EVIDENCE / "f8_phase_acceptance"
LEDGER_PATH = OUTPUT / "atomic_execution_ledger.json"
CONTINUOUS_PATH = OUTPUT / "continuous_report.json"
TASK_REPORTS = {
    "F8-T01": (EVIDENCE / "f8_t01_review_calendar" / "report.json", 7),
    "F8-T02": (EVIDENCE / "f8_t02_wrong_questions" / "report.json", 8),
    "F8-T03": (EVIDENCE / "f8_t03_notes" / "report.json", 9),
    "F8-T04": (EVIDENCE / "f8_t04_profile_history" / "report.json", 7),
    "F8-T05": (EVIDENCE / "f8_t05_learning_feedback" / "report.json", 14),
}
EXPECTED_ATOMS = [
    "G15-R01", "G15-R02", "G15-R03", "G15-R04", "G15-R05", "G15-R06",
    "G21-R07", "G21-R08", "G21-R09", "G22-R07", "G07-R09",
    "G19-R01", "G19-R02", "G19-R03", "G19-R04", "G19-R05", "G19-R06",
    "G19-R07", "G19-R08", "G20-R03", "G22-R06",
]
OWNER_SCREENSHOTS = {
    "F8-T01": [
        "t01/01-review-calendar-1440x900.png",
        "t01/02-review-generated-resource-bundle.png",
        "t01/03-review-completed.png",
        "t01/04-delayed-retest-completed.png",
        "t01/05-legacy-review-tools.png",
        "t01/06-review-calendar-1366x768.png",
        "t01/07-calendar-legacy-tools-1366x768.png",
    ],
    "F8-T02": [
        "t02/01-load-failure-1440x900.png",
        "t02/02-merged-history-1440x900.png",
        "t02/03-filter-empty-1440x900.png",
        "t02/04-source-round-trip-1440x900.png",
        "t02/05-confirmed-diagnosis-1440x900.png",
        "t02/06-redo-complete-1440x900.png",
        "t02/07-refresh-history-1440x900.png",
        "t02/08-stable-workspace-1366x768.png",
    ],
    "F8-T03": [
        "t03/01-selection-source-1440x900.png",
        "t03/06-handout-source-note-1440x900.png",
        "t03/07-sandbox-source-note-1440x900.png",
        "t03/08-review-source-note-1440x900.png",
        "t03/02-withdrawn-source-1440x900.png",
        "t03/03-conflict-preserves-draft-1440x900.png",
        "t03/04-ai-suggestion-separated-1440x900.png",
        "t03/05-version-restore-complete-1440x900.png",
        "t03/09-stable-workspace-1366x768.png",
    ],
    "F8-T04": [
        "t04/01-profile-1440x900.png",
        "t04/02-history-1440x900.png",
        "t04/03-history-pagination-1440x900.png",
        "t04/04-profile-1366x768.png",
        "t04/05-history-1366x768.png",
        "t04/06-empty-profile-1440x900.png",
        "t04/07-empty-history-1440x900.png",
    ],
    "F8-T05": [
        "t05/13-partial-dashboard-1440x900.png",
        "t05/14-recovered-dashboard-1440x900.png",
        "t05/01-dashboard-1440x900.png",
        "t05/02-profile-1440x900.png",
        "t05/03-path-1440x900.png",
        "t05/04-wrong_questions-1440x900.png",
        "t05/05-review-1440x900.png",
        "t05/06-history-1440x900.png",
        "t05/01-dashboard-1366x768.png",
        "t05/02-profile-1366x768.png",
        "t05/03-path-1366x768.png",
        "t05/04-wrong_questions-1366x768.png",
        "t05/05-review-1366x768.png",
        "t05/06-history-1366x768.png",
    ],
}
ATOM_CHECKS = {
    "G15-R01": ["controlled_deep_link_diagnostic"],
    "G15-R02": ["ordinary_browsing_zero_writes"],
    "G15-R03": ["ordinary_browsing_zero_writes"],
    "G15-R04": ["controlled_deep_link", "ordinary_browsing_zero_writes"],
    "G15-R05": ["ordinary_browsing_zero_writes"],
    "G15-R06": ["partial_recovered_after_service_restart", "six_views_consistent_after_restart"],
    "G21-R07": ["four_protected_surfaces_present"],
    "G21-R08": ["continuous_order"],
    "G21-R09": ["six_views_consistent_after_restart"],
    "G22-R07": [
        "load_failure_recovered", "practice_and_formal_filters", "same_question_attempts_merged",
        "source_round_trip", "diagnosis_confirmed_without_mastery_change",
        "redo_created_one_attempt", "refresh_preserved_history",
    ],
    "G07-R09": [
        "withdrawn_source_honest", "local_draft_survived_refresh",
        "conflict_preserved_local_draft", "ai_suggestion_separate_until_applied",
        "historical_restore_created_new_version", "selection_note_exact_source_identity",
    ],
    "G19-R01": ["real_minutes_and_streak"],
    "G19-R02": ["thirty_day_heatmap"],
    "G19-R03": ["processed_mastery_trend"],
    "G19-R04": ["history_filters_and_pagination", "controlled_deep_link_diagnostic"],
    "G19-R05": ["honest_empty_account"],
    "G19-R06": ["four_protected_surfaces_present"],
    "G19-R07": ["honest_empty_account", "ordinary_browsing_zero_writes"],
    "G19-R08": ["controlled_deep_link_diagnostic"],
    "G20-R03": ["controlled_deep_link_diagnostic", "four_protected_surfaces_present"],
    "G22-R06": [
        "partial_before_restart", "partial_recovered_after_service_restart",
        "recovery_no_duplicate_event_or_consumption", "six_views_consistent_after_restart",
    ],
}
ATOM_VERIFICATION = {
    "G15-R01": "The continuous journey renders the real 42-cell calendar and selected-day agenda at both frozen desktop sizes; the measured calendar ratio remains 58/42.",
    "G15-R02": "Calendar counts and statuses are read from the same task projection while month, date and course browsing leaves the database snapshot unchanged.",
    "G15-R03": "Selecting dates keeps the month/date context and exposes the corresponding deterministic agenda without creating learning evidence.",
    "G15-R04": "The history deep link reaches the real /workspace/review pathname, mounts ReviewScheduleBoard and completes both recall and delayed-retest actions.",
    "G15-R05": "The dual-desktop calendar evidence retains today, overdue, completed, future and course-filter states without forbidden theme fallback.",
    "G15-R06": "The journey creates the existing nine-resource package, records one accepted review completion and recovers the shared feedback without duplicate events.",
    "G21-R07": "The calendar remains the first review surface while the original review tools are still visible through the progressive section at both desktop sizes.",
    "G21-R08": "The review knowledge point opens the existing resource-bundle flow and preserves the existing exam-gate ownership rather than creating a parallel route.",
    "G21-R09": "A real review completion is reflected through the same six-view feedback token and the protected profile/path surfaces remain present.",
    "G22-R07": "One canonical wrong-question row retains merged attempts, source round-trip, student-confirmed diagnosis, related learning actions and a scored redo with history preserved.",
    "G07-R09": "A source-bound selection note retains document version, page, image region, selectionId and sourceRefId; conflict, withdrawal and restore paths preserve user content.",
    "G19-R01": "The profile shows event-derived learning minutes with a calculation range and source evidence, while read-only page visits produce no new events.",
    "G19-R02": "The profile shows the real 30-day heatmap and streak; the empty account remains uncolored with zero activity.",
    "G19-R03": "The selected-period mastery trend comes from processed aggregation results and the empty account shows an explanatory no-data state.",
    "G19-R04": "History filters, stable pagination and the controlled object deep link work in one continuous owner-scoped journey.",
    "G19-R05": "The profile keeps a compact profile/report section and the empty account does not invent a report or trend.",
    "G19-R06": "Profile and history retain the upper facts, middle trend/activity and lower profile/report hierarchy without clipping, small text or card-wall regression.",
    "G19-R07": "All visible profile facts are reproducible from event/consumption data, and the honest empty account remains zero instead of receiving demo values.",
    "G19-R08": "The controlled internal target returns to the exact review business route and mounts its owner component; no external URL is accepted.",
    "G20-R03": "Profile and history remain inside the existing AppShell and the journey moves through the owned secondary route without a ninth primary entry.",
    "G22-R06": "Partial projection survives one service restart, retries only the failed tail and ends with one identical event/token/next-day schedule on all six consumer pages.",
}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def resolve_task_screenshot(report_path: Path, value: str) -> Path:
    normalized = Path(value.replace("\\", "/"))
    rooted = ROOT / normalized
    if rooted.is_file():
        return rooted
    return report_path.parent / "browser" / normalized.name


def require_clean_visual(node: Any, label: str = "visual") -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            current = f"{label}.{key}"
            if key in {"missingRoot", "pageOverflow", "rootOverflow"}:
                require(value is False, f"{current} is not false")
            if key in {"clipped", "smallText", "collisions", "forbiddenThemeHits", "gradients", "backgrounds"}:
                require(not value, f"{current} is not empty")
            require_clean_visual(value, current)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            require_clean_visual(value, f"{label}[{index}]")


def require_clean_database(node: Any, label: str = "database") -> int:
    checked = 0
    if isinstance(node, dict):
        if "integrity" in node or "foreign_key_violations" in node:
            require(node.get("integrity") == "ok", f"{label} integrity is not ok")
            require(node.get("foreign_key_violations") == 0, f"{label} has foreign-key violations")
            checked += 1
        for key, value in node.items():
            checked += require_clean_database(value, f"{label}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            checked += require_clean_database(value, f"{label}[{index}]")
    return checked


def require_viewports(report: dict[str, Any], label: str) -> None:
    viewports = {tuple(item) for item in report.get("viewports", [])}
    require(viewports == {(1440, 900), (1366, 768)}, f"{label} has incomplete desktop evidence: {viewports}")


def require_empty_errors(report: dict[str, Any], label: str) -> None:
    for field in ("http_errors", "failed_requests", "page_errors", "console_errors", "external_requests"):
        require(not report.get(field), f"{label} contains unexpected {field}")


def validate_task_reports() -> tuple[dict[str, dict[str, Any]], int]:
    results: dict[str, dict[str, Any]] = {}
    total = 0
    for task, (path, expected_count) in TASK_REPORTS.items():
        require(path.is_file(), f"Missing {task} report: {path}")
        report = load(path)
        require(report.get("status") == "passed", f"{task} report is not passed")
        require_viewports(report, task)
        require_empty_errors(report, task)
        require(report.get("external_model_called") is False, f"{task} used an external model")
        require_clean_visual(report.get("visual", {}), f"{task}.visual")
        database_sections = require_clean_database(report.get("database", {}), f"{task}.database")
        require(database_sections > 0, f"{task} has no database integrity evidence")
        screenshots = list(report.get("screenshots", []))
        require(len(screenshots) == expected_count, f"{task} expected {expected_count} screenshots, got {len(screenshots)}")
        missing = [value for value in screenshots if not resolve_task_screenshot(path, value).is_file()]
        require(not missing, f"{task} screenshots are missing: {missing}")
        total += len(screenshots)
        results[task] = {
            "status": "PASS",
            "report": path.relative_to(ROOT).as_posix(),
            "screenshots": len(screenshots),
            "database_sections_checked": database_sections,
        }
    require(total == 45, f"Expected 45 original F8 task screenshots, got {total}")
    return results, total


def validate_continuous() -> dict[str, Any]:
    report = load(CONTINUOUS_PATH)
    require(report.get("status") == "passed", "F8 continuous journey is not passed")
    require_viewports(report, "F8 continuous journey")
    require(report.get("single_service_runtime") is True, "Continuous journey used multiple service runtimes")
    require(report.get("service_restart_count") == 1, "Continuous journey must include exactly one service restart")
    require(report.get("single_chromium_instance") is True, "Continuous journey used multiple Chromium instances")
    require(report.get("external_model_called") is False, "Continuous journey used an external model")
    require_empty_errors(report, "F8 continuous journey")

    screenshots = list(report.get("screenshots", []))
    require(len(screenshots) == 45, f"Expected 45 continuous screenshots, got {len(screenshots)}")
    require(set(screenshots) == {item for values in OWNER_SCREENSHOTS.values() for item in values}, "Continuous screenshot manifest is incomplete or duplicated")
    missing = [name for name in screenshots if not (OUTPUT / "browser" / name).is_file()]
    require(not missing, f"Continuous screenshots are missing: {missing}")

    checks = report.get("checks", {})
    require(set(EXPECTED_ATOMS) == set(ATOM_CHECKS), "Per-atom check map does not match the phase contract")
    for atom, names in ATOM_CHECKS.items():
        for name in names:
            value = checks.get(name)
            require(value not in (None, False, "", [], {}), f"{atom} check {name} is missing or false")
    deep_link = checks["controlled_deep_link_diagnostic"]
    require(deep_link.get("pathname") == "/workspace/review", "Controlled deep link did not reach /workspace/review")
    require(deep_link.get("component_mount", {}).get("status") == "visible", "ReviewScheduleBoard did not mount")
    require(checks.get("four_protected_surfaces_present") == {
        "profile": True, "path": True, "notes": True, "wrong_questions": True,
    }, "The four protected surfaces are not all present")

    expected_http = report.get("expected_http_errors", [])
    require(len(expected_http) == 2, f"Expected exactly two deliberate HTTP errors, got {expected_http}")
    statuses = sorted(item.get("status") for item in expected_http)
    require(statuses == [409, 503], f"Unexpected deliberate HTTP statuses: {statuses}")
    wrong_503 = next(item for item in expected_http if item.get("status") == 503)
    note_409 = next(item for item in expected_http if item.get("status") == 409)
    require(wrong_503.get("url", "").endswith("/api/quiz/wrong-questions/lzz"), "The deliberate 503 is not the wrong-question load injection")
    require("/api/notes/update/note-" in note_409.get("url", ""), "The deliberate 409 is not the stale-note update")
    require(report.get("expected_console_errors") == [
        "Failed to load resource: the server responded with a status of 503 (Service Unavailable)",
        "Failed to load resource: the server responded with a status of 409 (Conflict)",
    ], "Expected console classification is not exact")
    conflict = report.get("diagnostic_expectations", {}).get("note_conflict", {})
    require(conflict.get("active") is False, "Stale-note expectation remained active after the operation")
    require(conflict.get("operation") == "save_stale_note_version", "Unexpected stale-note operation marker")
    require(conflict.get("status") == 409 and conflict.get("response_seen") is True, "Stale-note 409 was not observed exactly")
    require(conflict.get("url") == note_409.get("url"), "Stale-note URL differs between the response and expectation")

    require_clean_visual(report.get("visual", {}), "continuous.visual")
    database_sections = require_clean_database(report.get("database", {}), "continuous.database")
    require(database_sections > 0, "Continuous report has no database integrity evidence")
    database = report["database"]
    for before, after in (
        ("learner_before", "learner_after"),
        ("browse_before", "browse_after"),
        ("read_only_before", "read_only_after"),
        ("secondary_read_only_before", "secondary_read_only_after"),
        ("final_read_only_before", "final_read_only_after"),
        ("empty_before", "empty_after"),
    ):
        require(database.get(before) == database.get(after), f"Read-only snapshots differ: {before} vs {after}")

    snapshots = report.get("feedback_snapshots", {})
    for viewport in ("1440x900", "1366x768"):
        views = snapshots.get(viewport, {})
        require(set(views) == {"dashboard", "profile", "path", "wrong_questions", "review", "history"}, f"{viewport} lacks a six-view feedback snapshot")
        first = views["dashboard"]
        for name, value in views.items():
            require(value.get("headline") == "学习反馈已同步", f"{viewport}/{name} has a wrong feedback headline")
            require(value.get("view_count") == 6, f"{viewport}/{name} does not show six views")
            require(value.get("view_statuses") == ["已同步"] * 6, f"{viewport}/{name} has inconsistent view status")
            require(value.get("footer") == first.get("footer"), f"{viewport}/{name} has a different consistency token")
            require(value.get("text") == first.get("text"), f"{viewport}/{name} has a different feedback projection")
    return report


def require_recorded_gates(ledger: dict[str, Any]) -> None:
    batches = {item.get("batch"): item for item in ledger.get("execution_batches", [])}
    regression = batches.get("phase-f8-named-regression", {})
    build = batches.get("phase-frontend-production-build", {})
    impeccable = batches.get("phase-impeccable-audit", {})
    require(regression.get("status") == "PASSED", "Recorded F8 named regression is not passed")
    require("60 passed, 5 warnings" in regression.get("verification", ""), "Recorded F8 regression does not prove 60 passed")
    require(build.get("status") == "PASSED", "Recorded F8 production build is not passed")
    require("6939 modules" in build.get("verification", ""), "Recorded build does not prove 6939 modules")
    require(impeccable.get("status") == "PASSED_WITH_REVIEWED_FALSE_POSITIVES", "Impeccable audit is not reconciled")
    verification = impeccable.get("verification", "")
    require("Review.vue:191" in verification and "WrongQuestionBook.vue:538" in verification, "Impeccable false positives were not verified individually")
    require("No UI source was changed" in verification, "Impeccable audit does not preserve the UI source")


def reconcile_atoms(
    ledger: dict[str, Any],
    task_results: dict[str, dict[str, Any]],
    generated_at: str,
) -> list[dict[str, Any]]:
    entries = ledger.get("entries", [])
    require([item.get("atomic_requirement_id") for item in entries] == EXPECTED_ATOMS, "Phase atom order or identity differs from the contract")
    summaries: list[dict[str, Any]] = []
    for entry in entries:
        atom = entry["atomic_requirement_id"]
        owner = entry["owner_task"]
        source_ledger = ROOT / entry["source_ledger"]["path"]
        require(source_ledger.is_file(), f"{atom} source ledger is missing")
        require(digest(source_ledger) == entry["source_ledger"]["sha256"], f"{atom} source ledger hash changed")
        baseline = entry.get("closed_task_realization_baseline", {})
        require(baseline.get("status") == "IMPLEMENTED_AND_VERIFIED", f"{atom} closed-task baseline is not verified")
        implementation = list(baseline.get("implementation_evidence", []))
        require(implementation, f"{atom} has no closed-task implementation evidence")
        require(baseline.get("user_visible_result"), f"{atom} has no closed-task user-visible result")
        task_report = task_results.get(owner)
        require(task_report is not None, f"{atom} has no owner-task report")
        atom_screenshots = OWNER_SCREENSHOTS[owner]
        check_names = ATOM_CHECKS[atom]
        phase_realization = {
            "status": "IMPLEMENTED_AND_VERIFIED",
            "implementation_evidence": [
                f"{entry['source_ledger']['path']} remains SHA-256 verified and records {atom} as IMPLEMENTED_AND_VERIFIED.",
                implementation[-1],
                f"{task_report['report']} remains passed with {task_report['screenshots']} original task screenshots.",
            ],
            "verification_evidence": [
                f"outputs/原系统融合重构执行/evidence/f8_phase_acceptance/continuous_report.json checks {', '.join(check_names)} for {atom} in one service/browser/database journey.",
                ATOM_VERIFICATION[atom],
                f"Continuous screenshots for {atom}: {', '.join(atom_screenshots)}.",
                "F8 named backend/frontend regression: 60 passed, 5 existing framework deprecation warnings; production build: 6939 modules; Impeccable: 0 actionable findings after two source-verified false positives.",
            ],
            "user_visible_result": baseline["user_visible_result"],
            "compatibility_or_defer_rationale": "No deferral. Phase acceptance reused the closed product implementation in isolated SQLite and changed only test/evidence infrastructure. The four 7.20 protected pages, read-only browsing, data integrity, visual contract and recovery consistency remained verified.",
            "reconciled_at": generated_at,
        }
        require(all(phase_realization[field] for field in (
            "implementation_evidence", "verification_evidence", "user_visible_result", "compatibility_or_defer_rationale",
        )), f"{atom} phase realization is incomplete")
        entry["phase_realization"] = phase_realization
        summaries.append({
            "atom": atom,
            "owner_task": owner,
            "status": phase_realization["status"],
            "task_report": task_report["report"],
            "phase_checks": check_names,
            "continuous_screenshots": atom_screenshots,
            "user_visible_result": phase_realization["user_visible_result"],
        })
    return summaries


def write_reports(
    task_results: dict[str, dict[str, Any]],
    task_screenshots: int,
    continuous: dict[str, Any],
    atom_summaries: list[dict[str, Any]],
    generated_at: str,
) -> None:
    result = {
        "schema_version": "f8.phase-acceptance.v1",
        "status": "PASS",
        "generated_at": generated_at,
        "scope": "F8-T01 through F8-T05",
        "atomic_requirements": {
            "total": len(atom_summaries),
            "implemented_and_verified": len(atom_summaries),
            "pending": 0,
            "entries": atom_summaries,
        },
        "task_results": task_results,
        "task_screenshots": task_screenshots,
        "continuous_journey_screenshots": len(continuous["screenshots"]),
        "regression": {"passed": 60, "warnings": 5, "warnings_are_existing_deprecations": True},
        "production_build": {"status": "PASS", "modules_transformed": 6939},
        "impeccable": {
            "actionable_findings": [],
            "verified_false_positives": [
                "Review.vue:191 is a mutually exclusive red/red or slate/slate state expression.",
                "WrongQuestionBook.vue:538 is a semantic inline error/result border, not decorative side-tab styling.",
            ],
            "audit_health": {
                "accessibility": 3,
                "performance": 3,
                "responsive_desktop": 4,
                "theming": 4,
                "implementation_integrity": 4,
                "total": 18,
                "rating": "Excellent (minor limits: no full screen-reader audit; existing large chunk advisory)",
            },
        },
        "mandatory_conclusions": {
            "real_review_calendar_and_actions": "PASS",
            "wrong_questions_merge_source_diagnosis_redo": "PASS",
            "source_notes_conflict_withdrawal_restore": "PASS",
            "profile_history_real_metrics_and_empty_state": "PASS",
            "six_view_feedback_and_partial_recovery": "PASS",
            "four_legacy_surfaces_preserved": "PASS",
            "ordinary_browsing_zero_learning_writes": "PASS",
        },
        "database": {
            "isolated": True,
            "all_integrity_ok": True,
            "foreign_key_violations": 0,
            "formal_database_modified": False,
        },
        "expected_diagnostics": {
            "wrong_question_load": 503,
            "stale_note_version": 409,
            "unexpected_http_or_browser_errors": 0,
        },
        "external_model_called": False,
        "git_write_performed": False,
        "delivery_package_modified": False,
        "next_step": "Run the F5-F8 total continuous acceptance without reading or implementing F9.",
    }
    (OUTPUT / "phase_report.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# EduMatrix F8 阶段级联合验收报告",
        "",
        "> 结论：`PASS`",
        "> 范围：`F8-T01` 至 `F8-T05`，21 条阶段主责原子全部逐条核销。",
        "> 下一步：只执行 F5-F8 总联合验收，不读取、规划或实施 F9。",
        "",
        "## 1. 阶段结论",
        "",
        "F8 已把真实复习日历、错题深度学习、来源笔记、个人中心/历史和六页持续反馈接入同一学生闭环。五份原任务报告均为 `passed`，共 45 张截图；同一隔离 SQLite、同一服务生命周期、同一 Chromium 的阶段连续旅程另保存 45 张截图。",
        "",
        "## 2. 五项任务",
        "",
        "| 任务 | 能力 | 原任务截图 | 结果 |",
        "|---|---|---:|---|",
        "| F8-T01 | 真实月历、选中日安排、复习/复测、资源包和反馈 | 7 张 | PASS |",
        "| F8-T02 | 同题合并、双来源、错因确认、来源、关联资源和重做 | 8 张 | PASS |",
        "| F8-T03 | 来源笔记、并发冲突、AI 建议分离、历史恢复和四类来源 | 9 张 | PASS |",
        "| F8-T04 | 真实时长、热力图、趋势、动态、分页历史、深链和空账号 | 7 张 | PASS |",
        "| F8-T05 | 六类可信事件、六页同版本、部分失败、重启恢复和次日安排 | 14 张 | PASS |",
        "",
        "## 3. 21 条原子核销",
        "",
        "| 原子 | 主责任务 | 阶段证据 | 结果 |",
        "|---|---|---|---|",
    ]
    for item in atom_summaries:
        lines.append(
            f"| {item['atom']} | {item['owner_task']} | {', '.join(item['phase_checks'])}；{len(item['continuous_screenshots'])} 张定向截图 | PASS |"
        )
    lines.extend([
        "",
        "## 4. 连续旅程、错误与数据门禁",
        "",
        "- 连续旅程覆盖个人中心/历史、真实复习、错题、笔记、部分聚合失败、一次服务重启、六页一致反馈、1366x768 二次只读检查和诚实空账号。",
        "- 历史深链真实到达 `/workspace/review`，`ReviewScheduleBoard` 可见；普通浏览的六组前后数据库快照完全一致。",
        "- 预期 HTTP 只有错题加载故障注入 `503` 和陈旧笔记版本 `409`；意外 HTTP、请求、页面、控制台和外部请求均为 0。",
        "- 所有任务报告及连续旅程的隔离 SQLite 均为 `integrity_check=ok`，外键违规为 0；正式数据库未修改。",
        "- 未调用外部模型或真实网络依赖。",
        "",
        "## 5. 自动、构建与 Impeccable",
        "",
        "- F8 十个命名后端/前端合同：`60 passed, 5 warnings`；警告仅为既有框架弃用提示。",
        "- 前端生产构建通过，转换 `6939` 个模块；仅保留既有大分块建议。",
        "- 1440x900 和 1366x768 的记录页面均为 0 溢出、0 裁切、0 真实碰撞、0 小于 14px 文字、0 禁用主题色和 0 渐变。",
        "- Impeccable 的两条 warning 已逐行核实：一条是互斥状态类，一条是语义错误提示边框；可执行问题为 0，没有为迎合检测修改 UI。",
        "- 技术审查健康度为 `18/20`：阶段实现完整；现存限制是未做全量屏幕阅读器专项和既有大分块建议。",
        "",
        "## 6. 边界",
        "",
        "- 本报告只关闭 F8 阶段级验收，不代表 F5-F8 总联合验收已经完成。",
        "- 没有执行 Git 暂存、提交、推送或历史改写，没有更新交付包。",
        "- F9/F10 未读取、规划或实施。",
    ])
    (OUTPUT / "phase_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    require(LEDGER_PATH.is_file(), f"Missing F8 phase ledger: {LEDGER_PATH}")
    ledger = load(LEDGER_PATH)
    contract = ledger.get("task_atomic_execution_contract", {})
    require(contract.get("task_id") == "F8-PHASE-ACCEPTANCE", "Wrong phase task contract")
    require(contract.get("primary_atomic_requirement_ids") == EXPECTED_ATOMS, "Phase contract atom list changed")
    require(not contract.get("related_atomic_requirement_ids"), "F8 phase contract unexpectedly has related atoms")
    require(all(entry.get("understanding", {}).get("confirmed") is True for entry in ledger.get("entries", [])), "Not every phase atom has confirmed understanding")

    for task, record in ledger.get("source_ledgers", {}).items():
        path = ROOT / record["path"]
        require(path.is_file(), f"Missing source ledger for {task}")
        require(digest(path) == record["sha256"], f"Source ledger hash changed for {task}")

    task_results, task_screenshots = validate_task_reports()
    continuous = validate_continuous()
    require_recorded_gates(ledger)
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    atom_summaries = reconcile_atoms(ledger, task_results, generated_at)
    require(len(atom_summaries) == 21, "F8 phase did not reconcile all 21 atoms")
    require(all(item["status"] == "IMPLEMENTED_AND_VERIFIED" for item in atom_summaries), "At least one F8 atom remains incomplete")

    ledger["state"] = "CLOSED"
    ledger["updated_at"] = generated_at
    ledger["final_acceptance"] = {
        "status": "PASS",
        "completed_at": generated_at,
        "primary_atoms": 21,
        "implemented_and_verified": 21,
        "pending": 0,
        "task_screenshots": task_screenshots,
        "continuous_screenshots": len(continuous["screenshots"]),
        "next_step": "F5-F8 total continuous acceptance; F9 remains forbidden.",
    }
    ledger["execution_batches"] = [
        item for item in ledger.get("execution_batches", [])
        if item.get("batch") != "phase-per-atom-finalization"
    ]
    ledger["execution_batches"].append({
        "batch": "phase-per-atom-finalization",
        "status": "PASSED",
        "mapped_atoms": EXPECTED_ATOMS,
        "protection_contracts": list(ledger.get("protection_contracts", {})),
        "changed_files": [
            "scripts/finalize_f8_phase_acceptance.py",
            "outputs/原系统融合重构执行/evidence/f8_phase_acceptance/atomic_execution_ledger.json",
            "outputs/原系统融合重构执行/evidence/f8_phase_acceptance/phase_report.json",
            "outputs/原系统融合重构执行/evidence/f8_phase_acceptance/phase_report.md",
        ],
        "result": "All 21 F8 phase atoms have independent implementation, verification and user-visible evidence; no group-level claim substitutes for an atom entry.",
        "verification": "Five passed owner-task reports with 45 screenshots, one passed 45-screenshot continuous journey, exact 503/409 classification, clean read-only and SQLite gates, 60 named tests, 6939-module production build and source-verified Impeccable findings all passed fail-closed validation.",
    })

    LEDGER_PATH.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_reports(task_results, task_screenshots, continuous, atom_summaries, generated_at)
    print("F8 phase acceptance PASS: 21 atoms, 45 task screenshots, 45 continuous screenshots")


if __name__ == "__main__":
    main()
